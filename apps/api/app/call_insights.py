from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crm_bridge import (
    CrmBridgeError,
    amo_write_requires_review,
    map_amo_contact_profile_fields,
    redact_pii_payload,
    send_amo_field_payload,
)
from app.models import Artifact, CallInsight, Project
from app.orchestration import log_event


class CallInsightError(ValueError):
    pass


CALL_OPERATOR_REVIEW_STATUSES = {
    "pending",
    "needs_correction",
    "family_case",
    "duplicate",
    "insufficient_data",
    "rejected",
}
CALL_REVIEW_SUMMARY_DEFAULTS = {
    "approved": "Оператор подтвердил ученика и разрешил controlled write в AMO.",
    "needs_correction": "Оператор вернул звонок на корректировку или повторный анализ.",
    "family_case": "Оператор отметил семейный кейс: нужно выбрать ученика без автоматического merge.",
    "duplicate": "Оператор считает звонок дублем существующего сценария и остановил автозапись.",
    "insufficient_data": "Оператор не смог безопасно сопоставить звонок: данных недостаточно.",
    "rejected": "Оператор отклонил запись звонка до ручного уточнения.",
}
CALL_REVIEW_REASON_DEFAULTS = {
    "approved": "Контакт AMO подтверждён оператором перед controlled write.",
    "needs_correction": "Нужно исправить анализ звонка или уточнить смысл разговора.",
    "family_case": "Один родительский номер относится к нескольким ученикам семьи.",
    "duplicate": "Похоже на дубль уже обработанного контакта или звонка.",
    "insufficient_data": "Не хватает данных для безопасного сопоставления звонка с учеником.",
    "rejected": "Звонок отклонён оператором до ручной проверки.",
}


@dataclass
class CallInsightCreateResult:
    insight: CallInsight
    artifact: Artifact
    summary: str


def _coerce_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise CallInsightError("Call insight source.started_at must be a valid ISO datetime.") from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    raise CallInsightError("Call insight source.started_at must be a datetime or ISO string.")


def build_call_insight_source_key(payload: dict) -> str:
    source = payload.get("source") if isinstance(payload, dict) else {}
    if not isinstance(source, dict):
        raise CallInsightError("Call insight payload must include a source object.")

    source_call_id = str(source.get("source_call_id") or "").strip()
    call_record_id = str(source.get("call_record_id") or "").strip()
    source_file = str(source.get("source_file") or "").strip()
    source_filename = str(source.get("source_filename") or "").strip()
    started_at = str(source.get("started_at") or "").strip()

    if source_call_id:
        return f"call:{source_call_id}"
    if call_record_id:
        return f"record:{call_record_id}"
    if source_file:
        return f"file:{source_file}"
    if source_filename and started_at:
        return f"filename:{source_filename}|started_at:{started_at}"
    if source_filename:
        return f"filename:{source_filename}"

    raise CallInsightError(
        "Call insight payload must include source_call_id, call_record_id, source_file, or source_filename."
    )


def build_call_insight_artifact_content(payload: dict) -> str:
    source = payload.get("source") if isinstance(payload, dict) else {}
    identity_hints = payload.get("identity_hints") if isinstance(payload, dict) else {}
    call_summary = payload.get("call_summary") if isinstance(payload, dict) else {}
    sales_insight = payload.get("sales_insight") if isinstance(payload, dict) else {}
    next_step = sales_insight.get("next_step") if isinstance(sales_insight, dict) else {}

    if not isinstance(source, dict):
        source = {}
    if not isinstance(identity_hints, dict):
        identity_hints = {}
    if not isinstance(call_summary, dict):
        call_summary = {}
    if not isinstance(sales_insight, dict):
        sales_insight = {}
    if not isinstance(next_step, dict):
        next_step = {}

    lines = [
        f"Источник: {source.get('system') or 'unknown'}",
        f"Ключ звонка: {source.get('source_call_id') or source.get('call_record_id') or '—'}",
        f"Файл: {source.get('source_filename') or source.get('source_file') or '—'}",
        f"Телефон: {source.get('phone') or identity_hints.get('phone') or '—'}",
        f"Менеджер: {source.get('manager_name') or '—'}",
        f"Ученик: {identity_hints.get('child_fio') or '—'}",
        f"Родитель: {identity_hints.get('parent_fio') or '—'}",
        f"Приоритет: {sales_insight.get('lead_priority') or '—'}",
        f"Follow-up score: {sales_insight.get('follow_up_score') or '—'}",
        f"Следующий шаг: {next_step.get('action') or '—'}",
        "",
        "AI-сводка:",
        str(call_summary.get("history_summary") or "—"),
    ]
    return "\n".join(lines).strip()


def _derive_call_review_reason(payload: dict) -> str | None:
    identity_hints = payload.get("identity_hints") if isinstance(payload, dict) else {}
    quality_flags = payload.get("quality_flags") if isinstance(payload, dict) else {}
    if not isinstance(identity_hints, dict):
        identity_hints = {}
    if not isinstance(quality_flags, dict):
        quality_flags = {}

    reasons: list[str] = []
    if amo_write_requires_review():
        reasons.append("Перед записью звонка в AMO нужна ручная проверка совпадения семьи и контакта.")
    if not str(identity_hints.get("child_fio") or "").strip():
        reasons.append("В результате анализа не определен конкретный ученик.")
    if bool(quality_flags.get("manual_review_required")):
        reasons.append("Локальный анализатор запросил ручную проверку.")
    if bool(quality_flags.get("ambiguous_identity")) or bool(quality_flags.get("family_match")):
        reasons.append("Есть неоднозначность матчинга по семье или телефону.")

    if not reasons:
        return None
    return " ".join(reasons)


def build_call_insight_amo_payload(insight: CallInsight) -> dict[str, object]:
    payload = insight.payload if isinstance(insight.payload, dict) else {}
    call_summary = payload.get("call_summary") if isinstance(payload, dict) else {}
    sales_insight = payload.get("sales_insight") if isinstance(payload, dict) else {}
    identity_hints = payload.get("identity_hints") if isinstance(payload, dict) else {}

    if not isinstance(call_summary, dict):
        call_summary = {}
    if not isinstance(sales_insight, dict):
        sales_insight = {}
    if not isinstance(identity_hints, dict):
        identity_hints = {}

    interests = sales_insight.get("interests")
    next_step = sales_insight.get("next_step")
    if not isinstance(interests, dict):
        interests = {}
    if not isinstance(next_step, dict):
        next_step = {}

    subjects = interests.get("subjects") if isinstance(interests.get("subjects"), list) else []
    products = interests.get("products") if isinstance(interests.get("products"), list) else []
    formats = interests.get("format") if isinstance(interests.get("format"), list) else []
    tags = sales_insight.get("tags") if isinstance(sales_insight.get("tags"), list) else []

    office_profile: dict[str, object] = {
        "auto_history": insight.history_summary,
        "match_status": insight.match_status,
        "ai_priority": insight.lead_priority,
        "ai_next_step": next_step.get("action"),
        "ai_summary": call_summary.get("history_short") or insight.history_summary,
    }
    extra_summary_parts = [
        ", ".join(str(item).strip() for item in products if str(item).strip()),
        ", ".join(str(item).strip() for item in subjects if str(item).strip()),
        ", ".join(str(item).strip() for item in formats if str(item).strip()),
        ", ".join(str(item).strip() for item in tags if str(item).strip()),
        str(sales_insight.get("follow_up_reason") or "").strip(),
        str(identity_hints.get("parent_fio") or "").strip(),
        str(identity_hints.get("child_fio") or "").strip(),
    ]
    extra_summary = " | ".join(part for part in extra_summary_parts if part)
    if extra_summary:
        office_profile["auto_history"] = f"{office_profile['auto_history']} [{extra_summary}]"

    mapped_payload, _ = map_amo_contact_profile_fields(office_profile)
    return mapped_payload


def create_call_insight(
    session: Session,
    project: Project,
    *,
    payload: dict,
    created_by: str,
) -> CallInsightCreateResult:
    source = payload.get("source") if isinstance(payload, dict) else {}
    call_summary = payload.get("call_summary") if isinstance(payload, dict) else {}
    sales_insight = payload.get("sales_insight") if isinstance(payload, dict) else {}
    processing = payload.get("processing") if isinstance(payload, dict) else {}
    identity_hints = payload.get("identity_hints") if isinstance(payload, dict) else {}

    if not isinstance(source, dict) or not isinstance(call_summary, dict) or not isinstance(sales_insight, dict):
        raise CallInsightError("Call insight payload is malformed.")
    if not isinstance(identity_hints, dict):
        identity_hints = {}

    history_summary = str(call_summary.get("history_summary") or "").strip()
    if not history_summary:
        raise CallInsightError("Call insight payload must include call_summary.history_summary.")

    source_system = str(source.get("system") or "").strip() or "mango_analyse"
    source_key = build_call_insight_source_key(payload)

    existing = session.scalars(
        select(CallInsight).where(
            CallInsight.project_id == project.id,
            CallInsight.source_system == source_system,
            CallInsight.source_key == source_key,
        )
    ).first()
    if existing is not None:
        raise CallInsightError("Call insight for this source key already exists in the project.")

    review_reason = _derive_call_review_reason(payload)

    insight = CallInsight(
        project_id=project.id,
        source_system=source_system,
        source_key=source_key,
        source_call_id=str(source.get("source_call_id") or "").strip() or None,
        source_record_id=str(source.get("call_record_id") or "").strip() or None,
        source_file=str(source.get("source_file") or "").strip() or None,
        source_filename=str(source.get("source_filename") or "").strip() or None,
        phone=str(source.get("phone") or identity_hints.get("phone") or "").strip() or None,
        manager_name=str(source.get("manager_name") or "").strip() or None,
        started_at=_coerce_datetime(source.get("started_at")),
        duration_sec=source.get("duration_sec"),
        history_summary=history_summary,
        lead_priority=str(sales_insight.get("lead_priority") or "").strip() or None,
        follow_up_score=sales_insight.get("follow_up_score"),
        processing_status=str(processing.get("analysis_status") or "").strip() or None,
        match_status="pending_match",
        matched_amo_contact_id=None,
        review_status="pending" if review_reason else "not_required",
        review_reason=review_reason,
        payload=payload,
        created_by=created_by,
    )
    session.add(insight)
    session.flush()

    artifact_title = (
        f"Call insight · {insight.source_filename}"
        if insight.source_filename
        else f"Call insight · {insight.source_call_id or insight.phone or insight.id}"
    )
    artifact = Artifact(
        project_id=project.id,
        task_id=None,
        kind="call_insight",
        title=artifact_title,
        content=build_call_insight_artifact_content(payload),
    )
    session.add(artifact)
    session.flush()
    log_event(
        session,
        project.id,
        "artifact_created",
        {"artifact_id": artifact.id, "kind": artifact.kind, "title": artifact.title},
    )

    log_event(
        session,
        project.id,
        "call_insight_ingested",
        payload={
            "call_insight_id": insight.id,
            "source_system": insight.source_system,
            "source_key": insight.source_key,
            "source_call_id": insight.source_call_id,
            "phone": insight.phone,
            "lead_priority": insight.lead_priority,
            "follow_up_score": insight.follow_up_score,
        },
    )

    summary = (
        f"Call insight сохранён. Источник: {insight.source_system}. "
        f"Match-статус: {insight.match_status}."
    )
    return CallInsightCreateResult(
        insight=insight,
        artifact=artifact,
        summary=summary,
    )


def resolve_call_insight_review(
    session: Session,
    project: Project,
    insight: CallInsight,
    *,
    outcome: str,
    actor: str,
    summary: str | None = None,
    matched_amo_contact_id: int | None = None,
) -> tuple[CallInsight, str]:
    if insight.status == "sent":
        raise CallInsightError("Call insight is already sent to AMO and cannot be re-reviewed.")
    if outcome not in CALL_REVIEW_SUMMARY_DEFAULTS:
        raise CallInsightError("Unsupported call insight review outcome.")
    if outcome == "approved" and matched_amo_contact_id is None and insight.matched_amo_contact_id is None:
        raise CallInsightError("Approved call insight review requires matched_amo_contact_id.")

    if matched_amo_contact_id is not None:
        insight.matched_amo_contact_id = matched_amo_contact_id
    if outcome == "approved":
        insight.match_status = "matched"
    elif outcome == "family_case":
        insight.match_status = "family_review"
    elif outcome == "duplicate":
        insight.match_status = "duplicate_candidate"
    else:
        insight.match_status = "manual_review"

    resolved_summary = summary or CALL_REVIEW_SUMMARY_DEFAULTS[outcome]
    insight.review_status = outcome
    insight.review_summary = resolved_summary
    insight.review_reason = CALL_REVIEW_REASON_DEFAULTS[outcome]
    insight.reviewed_by = actor
    insight.reviewed_at = datetime.now(timezone.utc)

    log_event(
        session,
        project.id,
        "call_review_resolved",
        {
            "call_insight_id": insight.id,
            "outcome": outcome,
            "actor": actor,
            "matched_amo_contact_id": insight.matched_amo_contact_id,
        },
    )
    return insight, resolved_summary


def send_call_insight_to_amo(
    session: Session,
    project: Project,
    insight: CallInsight,
    *,
    actor: str,
    matched_amo_contact_id: int | None = None,
    field_overrides: dict | None = None,
) -> tuple[CallInsight, str]:
    if insight.status == "sent":
        raise CallInsightError("Call insight is already sent to AMO.")
    if amo_write_requires_review() and insight.review_status != "approved":
        raise CallInsightError("Call insight must be approved in the review queue before AMO write.")

    if matched_amo_contact_id is not None:
        insight.matched_amo_contact_id = matched_amo_contact_id
        insight.match_status = "matched"
    if insight.matched_amo_contact_id is None:
        raise CallInsightError("Call insight must reference matched_amo_contact_id before AMO write.")

    field_payload = build_call_insight_amo_payload(insight)
    if field_overrides:
        for raw_key, raw_value in field_overrides.items():
            key = str(raw_key).strip()
            if key:
                field_payload[key] = raw_value

    try:
        result_payload = send_amo_field_payload(
            amo_entity_type="contact",
            amo_entity_id=str(insight.matched_amo_contact_id),
            field_payload=field_payload,
        )
        insight.status = "sent"
        insight.sent_by = actor
        insight.sent_at = datetime.now(timezone.utc)
        insight.error_message = None
        insight.send_result = result_payload
        summary = (
            f"Call insight отправлен в AMO: {len(field_payload)} полей для контакта "
            f"{insight.matched_amo_contact_id}."
        )
    except CrmBridgeError as exc:
        insight.status = "failed"
        insight.sent_by = actor
        insight.sent_at = datetime.now(timezone.utc)
        insight.error_message = str(exc)
        insight.send_result = {"result": "failed", "reason": str(exc)}
        summary = f"Отправка call insight в AMO завершилась ошибкой: {exc}"

    log_event(
        session,
        project.id,
        "call_send_completed" if insight.status == "sent" else "call_send_failed",
        {
            "call_insight_id": insight.id,
            "actor": actor,
            "matched_amo_contact_id": insight.matched_amo_contact_id,
            "field_count": len(field_payload),
            "status": insight.status,
        },
    )

    artifact = Artifact(
        project_id=project.id,
        kind="call_sync_result",
        title=f"Call send result for insight {insight.id}",
        content=json.dumps(
            {
                "call_insight_id": insight.id,
                "matched_amo_contact_id": insight.matched_amo_contact_id,
                "status": insight.status,
                "field_payload": redact_pii_payload(field_payload, key_hint="field_payload"),
                "send_result": redact_pii_payload(insight.send_result, key_hint="send_result"),
                "error_message": insight.error_message,
                "sent_by": insight.sent_by,
                "sent_at": insight.sent_at.isoformat() if insight.sent_at is not None else None,
            },
            ensure_ascii=False,
            indent=2,
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

    return insight, summary
