from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from typing import Optional
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

from app.config import get_settings
from app.models import Artifact, CrmSyncPreview, Project, utc_now
from app.orchestration import log_event


settings = get_settings()
CRM_OPERATOR_REVIEW_STATUSES = {
    "pending",
    "needs_correction",
    "family_case",
    "duplicate",
    "insufficient_data",
    "rejected",
}
CRM_REVIEW_SUMMARY_DEFAULTS = {
    "approved": "Оператор подтвердил запись и разрешил controlled write в AMO.",
    "needs_correction": "Оператор вернул запись на корректировку профиля перед отправкой.",
    "family_case": "Оператор отметил семейный кейс: нужен выбор ученика без автоматического merge.",
    "duplicate": "Оператор считает запись потенциальным дублем и вынес её на отдельную проверку.",
    "insufficient_data": "Оператор не смог подтвердить запись: данных для безопасной отправки недостаточно.",
    "rejected": "Оператор отклонил запись до ручной корректировки.",
}
CRM_REVIEW_REASON_DEFAULTS = {
    "approved": "Запись прошла явную операторскую проверку перед отправкой в AMO.",
    "needs_correction": "Нужно исправить поля профиля или источник данных перед записью в AMO.",
    "family_case": "Общий телефон или email относятся к нескольким ученикам семьи.",
    "duplicate": "Похоже на дубль существующего контакта или на конфликт с уже созданной карточкой.",
    "insufficient_data": "Недостаточно данных для безопасной привязки карточки в AMO.",
    "rejected": "Запись отклонена оператором до уточнения данных.",
}

DEFAULT_FIELD_MAPPING = {
    "name": "full_name",
    "email": "email",
    "phone": "phone",
    "city": "city",
    "program": "program",
    "stage": "stage",
    "last_activity": "last_activity_summary",
}

TALLANTO_CONTACT_SELECT_FIELDS = (
    "id",
    "date_entered",
    "date_modified",
    "first_name",
    "last_name",
    "email1",
    "email2",
    "phone_mobile",
    "phone_work",
    "balance",
    "description",
    "assigned_user_name",
    "primary_address_city",
    "type_client_c",
    "subject1_name",
    "subject2_name",
    "subject3_name",
    "tags",
    "source",
    "contact_notice",
    "contact_card",
    "spend_money",
    "recharge_money",
    "last_contact_date",
    "amo_id",
    "disable_amo_sync",
    "marital_status_c",
    "parents_birthdate",
)


class CrmBridgeError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def amo_write_requires_review() -> bool:
    return settings.crm_amo_mode != "mock"


SENSITIVE_KEY_FRAGMENTS = {
    "email",
    "phone",
    "mobile",
    "full_name",
    "student_name",
    "first_name",
    "last_name",
    "description",
    "notice",
    "contact_card",
    "birthdate",
    "parent",
}

DEFAULT_AMO_CONTACT_FIELD_MAP = {
    "tallanto_id": "Id Tallanto",
    "tallanto_branch": "Филиал Tallanto",
    "tallanto_balance": "Баланс Tallanto",
    "tallanto_recharged_total": "Пополнено Tallanto",
    "tallanto_spent_total": "Списано Tallanto",
    "auto_history": "Авто история общения",
    "match_status": "Статус матчинга",
    "ai_priority": "AI-приоритет",
    "ai_next_step": "AI-рекомендованный следующий шаг",
    "ai_summary": "Последняя AI-сводка",
}

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _mask_email(value: str) -> str:
    if "@" not in value:
        return "***"
    local_part, domain_part = value.split("@", 1)
    if not local_part:
        return f"***@{domain_part}"
    visible = local_part[:2]
    return f"{visible}{'*' * max(3, len(local_part) - len(visible))}@{domain_part}"


def _mask_phone(value: str) -> str:
    digits = [char for char in value if char.isdigit()]
    if len(digits) < 4:
        return "***"
    tail = "".join(digits[-2:])
    prefix = "+" if value.strip().startswith("+") else ""
    return f"{prefix}{'*' * max(4, len(digits) - 2)}{tail}"


def _mask_name(value: str) -> str:
    chunks = [chunk for chunk in value.split() if chunk]
    if not chunks:
        return "***"
    masked_chunks = []
    for chunk in chunks:
        masked_chunks.append(f"{chunk[:1]}{'*' * max(2, len(chunk) - 1)}")
    return " ".join(masked_chunks)


def _should_redact_key(key_hint: str) -> bool:
    normalized = key_hint.strip().lower()
    if not normalized:
        return False
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact_pii_payload(value, *, key_hint: str = ""):
    if isinstance(value, dict):
        return {
            key: redact_pii_payload(item, key_hint=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_pii_payload(item, key_hint=key_hint) for item in value]
    if not isinstance(value, str):
        return value

    if _should_redact_key(key_hint):
        normalized_key = key_hint.strip().lower()
        if "email" in normalized_key:
            return _mask_email(value)
        if "phone" in normalized_key or "mobile" in normalized_key:
            return _mask_phone(value)
        return _mask_name(value)

    if EMAIL_PATTERN.match(value.strip()):
        return _mask_email(value)
    return value


def sanitize_crm_preview_output(preview_payload: dict) -> dict:
    payload = dict(preview_payload)
    if "source_payload" in payload:
        payload["source_payload"] = redact_pii_payload(
            payload.get("source_payload"),
            key_hint="source_payload",
        )
    if "canonical_payload" in payload:
        payload["canonical_payload"] = redact_pii_payload(
            payload.get("canonical_payload"),
            key_hint="canonical_payload",
        )
    if "send_result" in payload and payload.get("send_result") is not None:
        payload["send_result"] = redact_pii_payload(
            payload["send_result"],
            key_hint="send_result",
        )
    return payload


def _to_serializable(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def _http_json_request(
    *,
    method: str,
    url: str,
    headers: Optional[dict[str, str]] = None,
    body: Optional[dict] = None,
    form_items: Optional[list[tuple[str, str]]] = None,
    allowed_error_statuses: Optional[set[int]] = None,
    timeout_seconds: int = 25,
) -> dict:
    payload = None
    request_headers = {"Accept": "application/json"}

    if headers:
        request_headers.update(headers)

    if body is not None:
        payload = json.dumps(body, ensure_ascii=False, default=_to_serializable).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    elif form_items is not None:
        payload = url_parse.urlencode(form_items, doseq=True).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = url_request.Request(
        url,
        data=payload,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with url_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            if not raw.strip():
                return {}
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                return decoded
            return {"data": decoded}
    except url_error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        if allowed_error_statuses and exc.code in allowed_error_statuses:
            if not details.strip():
                return {}
            try:
                decoded = json.loads(details)
            except json.JSONDecodeError as decode_error:
                raise CrmBridgeError(
                    f"Invalid JSON response from {url}",
                    status_code=502,
                ) from decode_error
            if isinstance(decoded, dict):
                return decoded
            return {"data": decoded}
        raise CrmBridgeError(
            f"HTTP {exc.code} from {url}: {details}",
            status_code=502,
        ) from exc
    except url_error.URLError as exc:
        raise CrmBridgeError(
            f"Failed to reach {url}: {exc.reason}",
            status_code=502,
        ) from exc
    except json.JSONDecodeError as exc:
        raise CrmBridgeError(
            f"Invalid JSON response from {url}",
            status_code=502,
        ) from exc


def _build_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/") + "/"
    normalized_path = path.lstrip("/")
    return url_parse.urljoin(normalized_base, normalized_path)


def _append_query_items(url: str, query_items: list[tuple[str, str]]) -> str:
    encoded_query = url_parse.urlencode(query_items, doseq=True)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{encoded_query}"


def _mock_tallanto_student(student_id: str) -> dict:
    normalized_id = "".join(ch for ch in student_id if ch.isdigit()) or "1001"
    suffix = normalized_id[-4:]
    return {
        "id": student_id,
        "full_name": f"Ученик {suffix}",
        "email": f"student{suffix}@example.edu",
        "phone": f"+7900000{suffix:0>4}",
        "balance": 50000,
        "city": "Москва",
        "program": "Подготовка к олимпиаде по ИИ",
        "stage": "active",
        "tags": ["olympiad", "ai", "pilot"],
        "last_activity_at": datetime.now(timezone.utc).isoformat(),
        "last_activity_summary": "Ученик прошёл 2 диагностических теста и ожидает обратную связь.",
    }


def _tallanto_headers() -> dict[str, str]:
    if not settings.crm_tallanto_api_token:
        raise CrmBridgeError(
            "CRM_TALLANTO_API_TOKEN is not configured.",
            status_code=503,
        )
    return {"X-Auth-Token": settings.crm_tallanto_api_token}


def _tallanto_rest_path() -> str:
    raw_path = (settings.crm_tallanto_student_path or "").strip()
    if not raw_path:
        return "/service/api/rest.php"
    return raw_path


def _tallanto_not_found(payload: dict) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("number") == 1502
        and "not find" in str(payload.get("name", "")).lower()
    )


def _tallanto_select_query_items() -> list[tuple[str, str]]:
    return [("select_fields[]", field_name) for field_name in TALLANTO_CONTACT_SELECT_FIELDS]


def _tallanto_request(
    *,
    method_name: str,
    http_method: str = "GET",
    query_items: Optional[list[tuple[str, str]]] = None,
    form_items: Optional[list[tuple[str, str]]] = None,
) -> dict:
    if not settings.crm_tallanto_base_url:
        raise CrmBridgeError(
            "CRM_TALLANTO_BASE_URL is not configured.",
            status_code=503,
        )

    endpoint_url = _build_url(settings.crm_tallanto_base_url, _tallanto_rest_path())
    final_query_items = [("method", method_name), ("module", "Contact"), *_tallanto_select_query_items()]
    if query_items:
        final_query_items.extend(query_items)
    request_url = _append_query_items(endpoint_url, final_query_items)
    return _http_json_request(
        method=http_method,
        url=request_url,
        headers=_tallanto_headers(),
        form_items=form_items,
        allowed_error_statuses={400},
    )


def _fetch_tallanto_student_legacy(student_id: str) -> dict:
    path = settings.crm_tallanto_student_path.format(
        student_id=url_parse.quote(student_id, safe="")
    )
    url = _build_url(settings.crm_tallanto_base_url, path)
    response = _http_json_request(
        method="GET",
        url=url,
        headers={"Authorization": f"Bearer {settings.crm_tallanto_api_token}"},
    )
    if isinstance(response.get("student"), dict):
        return response["student"]
    return response


def _normalize_phone_lookup_candidates(value: str) -> list[str]:
    candidates: list[str] = []
    normalized_value = value.strip()
    digits = "".join(char for char in normalized_value if char.isdigit())

    for candidate in (
        normalized_value,
        normalized_value.replace(" ", ""),
        digits,
        f"+{digits}" if digits else "",
        f"+7{digits[1:]}" if digits.startswith("8") and len(digits) == 11 else "",
        f"+{digits}" if digits.startswith("7") and len(digits) == 11 else "",
        f"+7{digits}" if len(digits) == 10 else "",
    ):
        candidate = candidate.strip()
        if not candidate or candidate in candidates:
            continue
        candidates.append(candidate)
    return candidates


def _lookup_tallanto_contact_by_id(contact_id: str) -> Optional[dict]:
    response = _tallanto_request(
        method_name="get_entry_by_id",
        query_items=[("id", contact_id)],
    )
    if _tallanto_not_found(response):
        return None
    return response if isinstance(response, dict) else None


def _lookup_tallanto_contact_by_field(field_name: str, value: str) -> Optional[dict]:
    response = _tallanto_request(
        method_name="get_entry_by_fields",
        query_items=[(f"fields_values[{field_name}]", value)],
    )
    if _tallanto_not_found(response):
        return None
    return response if isinstance(response, dict) else None


def _lookup_tallanto_contact_list(field_values: dict[str, str]) -> Optional[dict]:
    form_items = [(f"fields_values[{field_name}]", field_value) for field_name, field_value in field_values.items()]
    form_items.append(("offset", "0"))
    response = _tallanto_request(
        method_name="get_entry_list",
        http_method="POST",
        form_items=form_items,
    )
    entries = response.get("entry_list") if isinstance(response, dict) else None
    if not isinstance(entries, list) or len(entries) == 0:
        return None
    if len(entries) > 1:
        raise CrmBridgeError(
            "Tallanto returned multiple contacts for this lookup. Use ID, email, or exact phone.",
            status_code=409,
        )
    entry = entries[0]
    return entry if isinstance(entry, dict) else None


def _detect_lookup_mode(student_id: str) -> str:
    value = student_id.strip()
    if UUID_PATTERN.match(value):
        return "contact_id"
    if EMAIL_PATTERN.match(value):
        return "email"
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) >= 10:
        return "phone"
    return "full_name"


def fetch_tallanto_student(student_id: str, lookup_mode: str = "auto") -> dict:
    if settings.crm_tallanto_mode == "mock":
        return _mock_tallanto_student(student_id)

    if not settings.crm_tallanto_base_url:
        raise CrmBridgeError(
            "CRM_TALLANTO_BASE_URL is not configured.",
            status_code=503,
        )

    if not settings.crm_tallanto_api_token:
        raise CrmBridgeError(
            "CRM_TALLANTO_API_TOKEN is not configured.",
            status_code=503,
        )

    # Backward compatibility for older generic REST experiments.
    if "{student_id}" in (settings.crm_tallanto_student_path or ""):
        return _fetch_tallanto_student_legacy(student_id)

    resolved_lookup_mode = lookup_mode if lookup_mode != "auto" else _detect_lookup_mode(student_id)
    resolved_payload: Optional[dict] = None

    if resolved_lookup_mode == "contact_id":
        resolved_payload = _lookup_tallanto_contact_by_id(student_id.strip())
    elif resolved_lookup_mode == "email":
        resolved_payload = _lookup_tallanto_contact_by_field("email1", student_id.strip().lower())
    elif resolved_lookup_mode == "phone":
        for candidate in _normalize_phone_lookup_candidates(student_id):
            resolved_payload = _lookup_tallanto_contact_by_field("phone_mobile", candidate)
            if resolved_payload is not None:
                break
            resolved_payload = _lookup_tallanto_contact_list({"phone_mobile": candidate})
            if resolved_payload is not None:
                break
    else:
        normalized_name = " ".join(student_id.split())
        if normalized_name:
            name_candidates = [{"first_name": normalized_name}]
            parts = normalized_name.split(" ")
            if len(parts) >= 2:
                name_candidates.append({"first_name": parts[0], "last_name": " ".join(parts[1:])})
                name_candidates.append({"first_name": " ".join(parts[:-1]), "last_name": parts[-1]})
            else:
                name_candidates.append({"last_name": normalized_name})

            for candidate in name_candidates:
                try:
                    resolved_payload = _lookup_tallanto_contact_list(candidate)
                except CrmBridgeError:
                    raise
                if resolved_payload is not None:
                    break

    if resolved_payload is None:
        raise CrmBridgeError(
            f"Tallanto contact was not found for '{student_id}' ({resolved_lookup_mode}).",
            status_code=404,
        )

    resolved_payload["_lookup_mode"] = resolved_lookup_mode
    resolved_payload["_lookup_value"] = student_id
    return resolved_payload


def build_canonical_student(student_id: str, source_payload: dict) -> dict:
    def pick(*keys):
        for key in keys:
            value = source_payload.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None

    tags = pick("tags", "labels", "segments")
    if isinstance(tags, str):
        tags = [segment.strip() for segment in tags.split(",") if segment.strip()]
    if not isinstance(tags, list):
        tags = []

    first_name = pick("first_name")
    last_name = pick("last_name")
    full_name = pick("full_name", "name", "student_name")
    if full_name is None:
        full_name = " ".join(part for part in (first_name, last_name) if part)
    email = pick("email", "email_address", "email1")
    phone = pick("phone", "phone_number", "mobile", "phone_mobile", "phone_work")
    city = pick("city", "location_city", "primary_address_city")
    program = pick("program", "track", "course_name", "subject1_name", "subject2_name")
    stage = pick("stage", "pipeline_stage", "status", "type_client_c")
    last_activity_summary = pick(
        "last_activity_summary",
        "latest_note",
        "comment",
        "description",
        "contact_notice",
        "contact_card",
    )
    last_activity_at = pick("last_activity_at", "updated_at", "last_seen_at", "last_contact_date", "date_modified")

    if last_activity_summary is None and isinstance(source_payload.get("activity"), dict):
        last_activity_summary = source_payload["activity"].get("summary")

    return {
        "student_id": student_id,
        "source_contact_id": pick("id"),
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "city": city,
        "program": program,
        "stage": stage,
        "tags": tags,
        "tags_csv": ", ".join(tags),
        "last_activity_summary": last_activity_summary,
        "last_activity_at": last_activity_at,
        "assigned_user_name": pick("assigned_user_name"),
        "branch": pick("filial", "filial_name", "branch", "branch_name"),
        "balance": pick("balance"),
        "source": pick("source"),
        "parent_name": pick("marital_status_c"),
        "contact_notice": pick("contact_notice"),
        "contact_card": pick("contact_card"),
        "description": pick("description"),
        "amo_contact_id": pick("amo_id"),
        "recharge_money": pick("recharge_money"),
        "spend_money": pick("spend_money"),
    }


def _parse_amo_contact_field_map() -> dict[str, str]:
    raw_mapping = settings.crm_amo_contact_field_map
    if not raw_mapping:
        return dict(DEFAULT_AMO_CONTACT_FIELD_MAP)
    try:
        parsed = json.loads(raw_mapping)
    except json.JSONDecodeError as exc:
        raise CrmBridgeError(
            "CRM_AMO_CONTACT_FIELD_MAP must be valid JSON.",
            status_code=500,
        ) from exc
    if not isinstance(parsed, dict):
        raise CrmBridgeError(
            "CRM_AMO_CONTACT_FIELD_MAP must be a JSON object.",
            status_code=500,
        )
    normalized: dict[str, str] = {}
    for office_key, amo_field_name in parsed.items():
        key = str(office_key).strip()
        field_name = str(amo_field_name).strip()
        if key and field_name:
            normalized[key] = field_name
    return normalized or dict(DEFAULT_AMO_CONTACT_FIELD_MAP)


def map_amo_contact_profile_fields(profile_fields: dict[str, object]) -> tuple[dict[str, object], dict[str, str]]:
    field_map = _parse_amo_contact_field_map()
    mapped_payload: dict[str, object] = {}
    reverse_mapping: dict[str, str] = {}
    for office_key, amo_field_name in field_map.items():
        value = profile_fields.get(office_key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        mapped_payload[amo_field_name] = value
        reverse_mapping[amo_field_name] = office_key
    return mapped_payload, reverse_mapping


def _build_auto_history_summary(
    canonical_payload: dict,
    *,
    analysis_summary: str,
) -> str:
    parts: list[str] = []
    if canonical_payload.get("program"):
        parts.append(f"Программа: {canonical_payload['program']}.")
    if canonical_payload.get("last_activity_summary"):
        parts.append(f"Последняя активность: {canonical_payload['last_activity_summary']}.")
    if canonical_payload.get("contact_notice"):
        parts.append(f"Заметка: {canonical_payload['contact_notice']}.")
    if canonical_payload.get("contact_card"):
        parts.append(f"Карточка: {canonical_payload['contact_card']}.")
    parts.append(f"AI-сводка: {analysis_summary}")
    return " ".join(part.strip() for part in parts if str(part).strip()).strip()


def build_controlled_crm_contact_payload(
    canonical_payload: dict,
    *,
    analysis_summary: str,
) -> tuple[dict[str, object], dict[str, str]]:
    office_profile = {
        "tallanto_id": canonical_payload.get("source_contact_id") or canonical_payload.get("student_id"),
        "tallanto_branch": canonical_payload.get("branch"),
        "tallanto_balance": canonical_payload.get("balance"),
        "tallanto_recharged_total": canonical_payload.get("recharge_money"),
        "tallanto_spent_total": canonical_payload.get("spend_money"),
        "auto_history": _build_auto_history_summary(canonical_payload, analysis_summary=analysis_summary),
        "match_status": "linked" if canonical_payload.get("amo_contact_id") else "pending",
        "ai_priority": canonical_payload.get("stage"),
        "ai_next_step": "Проверить карточку, семью и выбрать следующий коммерческий шаг.",
        "ai_summary": analysis_summary,
    }
    return map_amo_contact_profile_fields(office_profile)


def build_amo_field_payload(canonical_payload: dict, field_mapping: dict[str, str]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for amo_field, canonical_key in field_mapping.items():
        value = canonical_payload.get(canonical_key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if str(item).strip())
        payload[amo_field] = value
    return payload


def _heuristic_analysis(canonical_payload: dict, amo_field_payload: dict) -> str:
    missing = []
    if not canonical_payload.get("full_name"):
        missing.append("нет ФИО")
    if not canonical_payload.get("phone") and not canonical_payload.get("email"):
        missing.append("нет телефона и email")
    if not canonical_payload.get("program"):
        missing.append("нет программы обучения")

    readiness = (
        "Карточка готова к точечной отправке в AMO."
        if not missing
        else "Перед отправкой стоит проверить обязательные поля."
    )
    mapped_fields = ", ".join(sorted(amo_field_payload.keys())) or "нет полей для отправки"
    issues = "; ".join(missing) if missing else "критичных пропусков не найдено"
    return (
        f"{readiness}\n"
        f"Поля к отправке: {mapped_fields}.\n"
        f"Проверка данных: {issues}."
    )


def _codex_analysis(canonical_payload: dict, amo_field_payload: dict) -> Optional[str]:
    prompt = (
        "Ты аналитик CRM-интеграции. Дай краткое решение в 4-6 предложений:\n"
        "1) готовность карточки к записи в AMO,\n"
        "2) риски качества данных,\n"
        "3) какие поля лучше перепроверить вручную.\n\n"
        f"Canonical student:\n{json.dumps(canonical_payload, ensure_ascii=False, indent=2)}\n\n"
        f"AMO payload:\n{json.dumps(amo_field_payload, ensure_ascii=False, indent=2)}"
    )
    command = [
        settings.codex_cli_path,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-C",
        settings.source_workspace_root,
        prompt,
    ]
    if settings.codex_model:
        command[2:2] = ["--model", settings.codex_model]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except OSError:
        return None
    except subprocess.TimeoutExpired:
        return None

    if completed.returncode != 0:
        return None
    output = (completed.stdout or "").strip()
    if not output:
        return None
    return output[:1500]


def analyze_crm_preview(canonical_payload: dict, amo_field_payload: dict) -> str:
    heuristic = _heuristic_analysis(canonical_payload, amo_field_payload)
    if settings.crm_analysis_mode != "codex":
        return heuristic

    codex_summary = _codex_analysis(canonical_payload, amo_field_payload)
    if codex_summary:
        return codex_summary
    return f"{heuristic}\nCodex-анализ недоступен, использована эвристика."


def create_crm_sync_preview(
    session,
    project: Project,
    *,
    student_id: str,
    lookup_mode: str = "auto",
    amo_entity_type: str,
    amo_entity_id: Optional[str],
    field_mapping: Optional[dict[str, str]],
    created_by: str,
) -> CrmSyncPreview:
    source_payload = fetch_tallanto_student(student_id, lookup_mode=lookup_mode)
    resolved_source_student_id = str(source_payload.get("id") or student_id)
    canonical_payload = build_canonical_student(resolved_source_student_id, source_payload)
    if amo_write_requires_review() and amo_entity_type != "contact":
        raise CrmBridgeError(
            "Controlled AMO writer currently supports only contact records.",
            status_code=409,
        )

    mapping = dict(DEFAULT_FIELD_MAPPING)
    if field_mapping:
        mapping.update(field_mapping)

    preview_field_payload = build_amo_field_payload(canonical_payload, mapping)
    analysis_summary = analyze_crm_preview(canonical_payload, preview_field_payload)
    if amo_write_requires_review():
        amo_field_payload, controlled_mapping = build_controlled_crm_contact_payload(
            canonical_payload,
            analysis_summary=analysis_summary,
        )
        mapping = controlled_mapping
    else:
        amo_field_payload = preview_field_payload
    review_required = amo_write_requires_review()
    review_reason = (
        "Перед записью в AMO нужна явная проверка полей и выбранного контакта."
        if review_required
        else None
    )

    preview = CrmSyncPreview(
        project_id=project.id,
        source_student_id=resolved_source_student_id,
        source_system="tallanto",
        amo_entity_type=amo_entity_type,
        amo_entity_id=amo_entity_id,
        source_payload=source_payload,
        canonical_payload=canonical_payload,
        amo_field_payload=amo_field_payload,
        field_mapping=mapping,
        analysis_summary=analysis_summary,
        status="previewed",
        review_status="pending" if review_required else "not_required",
        review_reason=review_reason,
        created_by=created_by,
    )
    session.add(preview)
    session.flush()

    log_event(
        session,
        project.id,
        "crm_preview_created",
        {
            "preview_id": preview.id,
            "source_student_id": resolved_source_student_id,
            "lookup_mode": lookup_mode,
            "requested_lookup": student_id,
            "amo_entity_type": amo_entity_type,
            "mapped_field_count": len(amo_field_payload),
        },
    )

    artifact = Artifact(
        project_id=project.id,
        kind="crm_preview",
        title=f"CRM preview for student {resolved_source_student_id}",
        content=json.dumps(
            {
                "preview_id": preview.id,
                "requested_lookup": student_id,
                "source_student_id": resolved_source_student_id,
                "lookup_mode": lookup_mode,
                "canonical_payload": redact_pii_payload(
                    canonical_payload,
                    key_hint="canonical_payload",
                ),
                "amo_field_payload": redact_pii_payload(
                    amo_field_payload,
                    key_hint="amo_field_payload",
                ),
                "analysis_summary": analysis_summary,
            },
            ensure_ascii=False,
            indent=2,
            default=_to_serializable,
        ),
    )
    session.add(artifact)
    session.flush()
    log_event(
        session,
        project.id,
        "artifact_created",
        {"artifact_id": artifact.id, "kind": artifact.kind, "title": artifact.title},
    )

    return preview


def _send_to_amo(
    *,
    amo_entity_type: str,
    amo_entity_id: Optional[str],
    field_payload: dict[str, object],
) -> dict:
    if settings.crm_amo_mode == "mock":
        return {
            "mode": "mock",
            "entity_type": amo_entity_type,
            "entity_id": amo_entity_id or "new",
            "updated_fields": field_payload,
            "result": "ok",
        }

    if not settings.crm_amo_base_url:
        raise CrmBridgeError("CRM_AMO_BASE_URL is not configured.", status_code=503)
    if not settings.crm_amo_api_token:
        raise CrmBridgeError("CRM_AMO_API_TOKEN is not configured.", status_code=503)

    try:
        path = settings.crm_amo_upsert_path.format(
            entity_type=amo_entity_type,
            entity_id=url_parse.quote(str(amo_entity_id or ""), safe=""),
        )
    except KeyError as exc:
        raise CrmBridgeError(
            "CRM_AMO_UPSERT_PATH must use placeholders {entity_type} and/or {entity_id}.",
            status_code=500,
        ) from exc
    url = _build_url(settings.crm_amo_base_url, path)
    return _http_json_request(
        method="PATCH",
        url=url,
        headers={"Authorization": f"Bearer {settings.crm_amo_api_token}"},
        body={
            "entity_type": amo_entity_type,
            "entity_id": amo_entity_id,
            "fields": field_payload,
        },
    )


def send_amo_field_payload(
    *,
    amo_entity_type: str,
    amo_entity_id: Optional[str],
    field_payload: dict[str, object],
) -> dict:
    return _send_to_amo(
        amo_entity_type=amo_entity_type,
        amo_entity_id=amo_entity_id,
        field_payload=field_payload,
    )


def resolve_crm_sync_preview_review(
    session,
    project: Project,
    preview: CrmSyncPreview,
    *,
    outcome: str,
    actor: str,
    summary: Optional[str] = None,
    amo_entity_id: Optional[str] = None,
) -> tuple[CrmSyncPreview, str]:
    if preview.status == "sent":
        raise CrmBridgeError(
            "CRM preview is already sent and can no longer change review state.",
            status_code=409,
        )
    if outcome not in CRM_REVIEW_SUMMARY_DEFAULTS:
        raise CrmBridgeError("Unsupported CRM review outcome.", status_code=400)

    resolved_summary = summary or CRM_REVIEW_SUMMARY_DEFAULTS[outcome]
    preview.review_status = outcome
    preview.review_summary = resolved_summary
    preview.reviewed_by = actor
    preview.reviewed_at = utc_now()
    if amo_entity_id is not None:
        preview.amo_entity_id = amo_entity_id
    if outcome != "approved":
        preview.status = "previewed"
    preview.review_reason = CRM_REVIEW_REASON_DEFAULTS[outcome]

    log_event(
        session,
        project.id,
        "crm_review_resolved",
        {
            "preview_id": preview.id,
            "outcome": outcome,
            "actor": actor,
            "amo_entity_id": preview.amo_entity_id,
        },
    )
    return preview, resolved_summary


def send_crm_sync_preview(
    session,
    project: Project,
    preview: CrmSyncPreview,
    *,
    actor: str,
    amo_entity_id: Optional[str] = None,
    selected_fields: Optional[list[str]] = None,
    field_overrides: Optional[dict[str, object]] = None,
) -> tuple[CrmSyncPreview, str]:
    if amo_write_requires_review() and preview.review_status != "approved":
        raise CrmBridgeError(
            "CRM preview must be approved in the review queue before AMO write.",
            status_code=409,
        )
    if amo_entity_id is not None:
        preview.amo_entity_id = amo_entity_id

    field_payload = dict(preview.amo_field_payload or {})
    mapped_field_keys = set(field_payload.keys())
    if selected_fields is not None:
        normalized_selected_fields = []
        seen_fields = set()
        for field_name in selected_fields:
            candidate = str(field_name).strip()
            if not candidate or candidate in seen_fields:
                continue
            seen_fields.add(candidate)
            normalized_selected_fields.append(candidate)
        allowed = {
            field_name
            for field_name in normalized_selected_fields
            if field_name in mapped_field_keys
        }
        field_payload = {key: value for key, value in field_payload.items() if key in allowed}

    applied_overrides = 0
    if field_overrides:
        for field_name, override_value in field_overrides.items():
            if field_name not in mapped_field_keys:
                continue
            if selected_fields is not None and field_name not in field_payload:
                continue
            field_payload[field_name] = override_value
            applied_overrides += 1

    if not field_payload:
        preview.status = "failed"
        preview.sent_by = actor
        preview.sent_at = utc_now()
        preview.error_message = "No mapped fields selected for AMO update."
        preview.send_result = {"result": "failed", "reason": preview.error_message}
        summary = "Отправка в AMO отменена: нет выбранных полей."
    else:
        try:
            result_payload = send_amo_field_payload(
                amo_entity_type=preview.amo_entity_type,
                amo_entity_id=preview.amo_entity_id,
                field_payload=field_payload,
            )
            preview.status = "sent"
            preview.sent_by = actor
            preview.sent_at = utc_now()
            preview.error_message = None
            preview.send_result = result_payload
            if applied_overrides > 0:
                summary = (
                    f"Отправка в AMO выполнена: {len(field_payload)} полей "
                    f"для {preview.amo_entity_type}, изменено вручную: {applied_overrides}."
                )
            else:
                summary = (
                    f"Отправка в AMO выполнена: {len(field_payload)} полей "
                    f"для {preview.amo_entity_type}."
                )
        except CrmBridgeError as exc:
            preview.status = "failed"
            preview.sent_by = actor
            preview.sent_at = utc_now()
            preview.error_message = str(exc)
            preview.send_result = {"result": "failed", "reason": str(exc)}
            summary = f"Отправка в AMO завершилась ошибкой: {exc}"

    log_event(
        session,
        project.id,
        "crm_send_completed" if preview.status == "sent" else "crm_send_failed",
        {
            "preview_id": preview.id,
            "status": preview.status,
            "amo_entity_type": preview.amo_entity_type,
            "amo_entity_id": preview.amo_entity_id,
            "field_count": len(field_payload),
            "manual_override_count": applied_overrides,
            "actor": actor,
        },
    )

    artifact = Artifact(
        project_id=project.id,
        kind="crm_sync_result",
        title=f"CRM send result for preview {preview.id}",
        content=json.dumps(
            {
                "preview_id": preview.id,
                "status": preview.status,
                "amo_entity_type": preview.amo_entity_type,
                "amo_entity_id": preview.amo_entity_id,
                "field_payload": redact_pii_payload(
                    field_payload,
                    key_hint="field_payload",
                ),
                "send_result": redact_pii_payload(
                    preview.send_result,
                    key_hint="send_result",
                ),
                "error_message": preview.error_message,
                "sent_by": preview.sent_by,
                "sent_at": preview.sent_at,
            },
            ensure_ascii=False,
            indent=2,
            default=_to_serializable,
        ),
    )
    session.add(artifact)
    session.flush()
    log_event(
        session,
        project.id,
        "artifact_created",
        {"artifact_id": artifact.id, "kind": artifact.kind, "title": artifact.title},
    )

    return preview, summary
