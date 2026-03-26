import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib import error as url_error

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.crm_bridge as crm_bridge_module  # noqa: E402
from app.crm_bridge import (  # noqa: E402
    CrmBridgeError,
    _http_json_request,
    _mock_tallanto_student,
    _send_to_amo,
    _append_query_items,
    _build_url,
    _detect_lookup_mode,
    _normalize_phone_lookup_candidates,
    _parse_amo_contact_field_map,
    analyze_crm_preview,
    build_controlled_crm_contact_payload,
    fetch_tallanto_student,
    map_amo_contact_profile_fields,
    redact_pii_payload,
    resolve_crm_sync_preview_review,
    sanitize_crm_preview_output,
    send_crm_sync_preview,
)
from app.db import Base  # noqa: E402
from app.models import Artifact, CrmSyncPreview, EventLog, Project  # noqa: E402


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def create_preview(session, project, **overrides):
    payload = {
        "project_id": project.id,
        "source_student_id": "student-1001",
        "source_system": "tallanto",
        "amo_entity_type": "contact",
        "amo_entity_id": None,
        "source_payload": {"id": "student-1001", "email1": "family@example.com"},
        "canonical_payload": {
            "student_id": "student-1001",
            "source_contact_id": "student-1001",
            "branch": "Выездные школы",
            "balance": 50000,
            "recharge_money": 100000,
            "spend_money": 50000,
            "amo_contact_id": None,
            "program": "Олимпиадный курс",
            "last_activity_summary": "Был на пробном занятии.",
            "contact_notice": "Позвонить после выходных.",
        },
        "amo_field_payload": {"Id Tallanto": "student-1001", "Авто история общения": "summary"},
        "field_mapping": {"Id Tallanto": "tallanto_id"},
        "analysis_summary": "Карточка готова к проверке.",
        "status": "previewed",
        "review_status": "pending",
        "review_reason": "Нужна ручная проверка.",
        "created_by": "director",
    }
    payload.update(overrides)
    preview = CrmSyncPreview(**payload)
    session.add(preview)
    session.flush()
    return preview


def test_crm_helpers_cover_urls_lookup_mapping_and_redaction(monkeypatch):
    assert _build_url("https://crm.example/api", "/contacts/1") == "https://crm.example/api/contacts/1"
    assert _append_query_items("https://crm.example/api", [("a", "1"), ("b", "2")]).endswith("a=1&b=2")
    assert _append_query_items("https://crm.example/api?x=1", [("a", "1")]).endswith("x=1&a=1")

    phone_candidates = _normalize_phone_lookup_candidates("8 (916) 916-41-48")
    assert "+79169164148" in phone_candidates
    assert "89169164148" in phone_candidates
    assert _detect_lookup_mode("fbpagency@gmail.com") == "email"
    assert _detect_lookup_mode("+7 916 916 41 48") == "phone"
    assert _detect_lookup_mode("245fb3d4-14d6-d7fb-aabf-69ae8a2d3270") == "contact_id"
    assert _detect_lookup_mode("Иванов Петр") == "full_name"

    monkeypatch.setattr(crm_bridge_module, "settings", SimpleNamespace(crm_amo_contact_field_map=None))
    parsed_default = _parse_amo_contact_field_map()
    assert parsed_default["tallanto_id"] == "Id Tallanto"

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(crm_amo_contact_field_map='{"tallanto_id":"ID Tallanto","ai_summary":"AI Summary"}'),
    )
    parsed_custom = _parse_amo_contact_field_map()
    assert parsed_custom == {"tallanto_id": "ID Tallanto", "ai_summary": "AI Summary"}

    with pytest.raises(CrmBridgeError):
        monkeypatch.setattr(
            crm_bridge_module,
            "settings",
            SimpleNamespace(crm_amo_contact_field_map='{"broken":'),
        )
        _parse_amo_contact_field_map()

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(crm_amo_contact_field_map='{"tallanto_id":"ID Tallanto","ai_summary":"AI Summary"}'),
    )
    mapped, reverse = map_amo_contact_profile_fields(
        {"tallanto_id": "student-1001", "ai_summary": "Готов к касанию", "empty": ""}
    )
    assert mapped == {"ID Tallanto": "student-1001", "AI Summary": "Готов к касанию"}
    assert reverse == {"ID Tallanto": "tallanto_id", "AI Summary": "ai_summary"}

    redacted = sanitize_crm_preview_output(
        {
            "source_payload": {"email": "parent@example.com", "phone": "+79990001122"},
            "canonical_payload": {"full_name": "Иванов Петр"},
            "send_result": {"email": "parent@example.com"},
        }
    )
    assert redacted["source_payload"]["email"].startswith("pa")
    assert redacted["source_payload"]["phone"].startswith("+")
    assert "*" in redacted["canonical_payload"]["full_name"]
    assert redact_pii_payload("child@example.com", key_hint="email").startswith("ch")


def test_build_controlled_payload_and_review_resolution_paths(monkeypatch):
    monkeypatch.setattr(crm_bridge_module, "settings", SimpleNamespace(crm_amo_contact_field_map=None))
    payload, reverse = build_controlled_crm_contact_payload(
        {
            "student_id": "student-1001",
            "source_contact_id": "student-1001",
            "branch": "Выездные школы",
            "balance": 50000,
            "recharge_money": 100000,
            "spend_money": 50000,
            "amo_contact_id": None,
            "program": "Олимпиадный курс",
            "last_activity_summary": "Был на пробном занятии.",
            "contact_notice": "Позвонить после выходных.",
            "contact_card": "Сильный ученик.",
            "stage": "warm",
        },
        analysis_summary="Готов к записи.",
    )
    assert payload["Id Tallanto"] == "student-1001"
    assert payload["Филиал Tallanto"] == "Выездные школы"
    assert "AI-сводка" in payload["Авто история общения"]
    assert reverse["AI-приоритет"] == "ai_priority"

    session = make_session()
    project = Project(name="CRM", description="Test project")
    session.add(project)
    session.commit()
    preview = create_preview(session, project)
    session.commit()

    resolved_preview, family_summary = resolve_crm_sync_preview_review(
        session,
        project,
        preview,
        outcome="family_case",
        actor="operator",
        summary=None,
    )
    assert resolved_preview.review_status == "family_case"
    assert resolved_preview.status == "previewed"
    assert "семейный кейс" in family_summary.lower()

    resolved_preview, approved_summary = resolve_crm_sync_preview_review(
        session,
        project,
        preview,
        outcome="approved",
        actor="operator",
        amo_entity_id="75807689",
    )
    assert resolved_preview.review_status == "approved"
    assert resolved_preview.amo_entity_id == "75807689"
    assert "разрешил controlled write" in approved_summary.lower()

    preview.status = "sent"
    with pytest.raises(CrmBridgeError):
        resolve_crm_sync_preview_review(
            session,
            project,
            preview,
            outcome="approved",
            actor="operator",
        )


def test_send_crm_sync_preview_applies_filters_overrides_and_artifact(monkeypatch):
    session = make_session()
    project = Project(name="CRM", description="Test project")
    session.add(project)
    session.commit()
    preview = create_preview(
        session,
        project,
        review_status="approved",
        amo_field_payload={
            "Id Tallanto": "student-1001",
            "Авто история общения": "Сводка",
            "AI-приоритет": "warm",
        },
    )
    session.commit()

    monkeypatch.setattr(crm_bridge_module, "amo_write_requires_review", lambda: True)

    sent_calls = []

    def fake_send_amo_field_payload(**kwargs):
        sent_calls.append(kwargs)
        return {"result": "ok", "fields": kwargs["field_payload"]}

    monkeypatch.setattr(crm_bridge_module, "send_amo_field_payload", fake_send_amo_field_payload)

    updated_preview, summary = send_crm_sync_preview(
        session,
        project,
        preview,
        actor="operator",
        amo_entity_id="75807689",
        selected_fields=["Id Tallanto", "AI-приоритет"],
        field_overrides={"AI-приоритет": "hot", "Unknown": "ignored"},
    )
    session.flush()

    assert updated_preview.status == "sent"
    assert updated_preview.amo_entity_id == "75807689"
    assert "изменено вручную" in summary
    assert sent_calls[0]["field_payload"] == {"Id Tallanto": "student-1001", "AI-приоритет": "hot"}

    artifacts = session.scalars(select(Artifact)).all()
    assert any(item.kind == "crm_sync_result" for item in artifacts)
    events = session.scalars(select(EventLog)).all()
    assert any(item.event_type == "crm_send_completed" for item in events)

    blocked_preview = create_preview(session, project, review_status="family_case")
    session.commit()
    with pytest.raises(CrmBridgeError):
        send_crm_sync_preview(
            session,
            project,
            blocked_preview,
            actor="operator",
        )


def test_http_transport_fetch_and_analysis_cover_error_branches(monkeypatch):
    class FakeResponse:
        def __init__(self, raw):
            self._raw = raw

        def read(self):
            return self._raw.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        crm_bridge_module.url_request,
        "urlopen",
        lambda request, timeout=25: FakeResponse('["ok", 1]'),
    )
    assert _http_json_request(method="GET", url="https://crm.example/api") == {"data": ["ok", 1]}

    monkeypatch.setattr(
        crm_bridge_module.url_request,
        "urlopen",
        lambda request, timeout=25: FakeResponse(""),
    )
    assert _http_json_request(method="GET", url="https://crm.example/api") == {}

    def raise_http_error(request, timeout=25):
        raise url_error.HTTPError(
            request.full_url,
            400,
            "bad request",
            hdrs=None,
            fp=BytesIO(b'{"number":1502,"name":"Not Find"}'),
        )

    monkeypatch.setattr(crm_bridge_module.url_request, "urlopen", raise_http_error)
    allowed_payload = _http_json_request(
        method="GET",
        url="https://crm.example/api",
        allowed_error_statuses={400},
    )
    assert allowed_payload["number"] == 1502

    def raise_bad_json_error(request, timeout=25):
        raise url_error.HTTPError(
            request.full_url,
            400,
            "bad request",
            hdrs=None,
            fp=BytesIO(b"not-json"),
        )

    monkeypatch.setattr(crm_bridge_module.url_request, "urlopen", raise_bad_json_error)
    with pytest.raises(CrmBridgeError):
        _http_json_request(
            method="GET",
            url="https://crm.example/api",
            allowed_error_statuses={400},
        )

    def raise_server_error(request, timeout=25):
        raise url_error.HTTPError(
            request.full_url,
            500,
            "server error",
            hdrs=None,
            fp=BytesIO(b"boom"),
        )

    monkeypatch.setattr(crm_bridge_module.url_request, "urlopen", raise_server_error)
    with pytest.raises(CrmBridgeError):
        _http_json_request(method="GET", url="https://crm.example/api")

    monkeypatch.setattr(
        crm_bridge_module.url_request,
        "urlopen",
        lambda request, timeout=25: (_ for _ in ()).throw(url_error.URLError("offline")),
    )
    with pytest.raises(CrmBridgeError):
        _http_json_request(method="GET", url="https://crm.example/api")

    monkeypatch.setattr(crm_bridge_module, "settings", SimpleNamespace(crm_tallanto_mode="mock"))
    assert _mock_tallanto_student("1001")["program"]
    assert fetch_tallanto_student("1001")["id"] == "1001"

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_tallanto_mode="http",
            crm_tallanto_base_url=None,
            crm_tallanto_api_token="token",
            crm_tallanto_student_path="/service/api/rest.php",
            crm_analysis_mode="heuristic",
            codex_cli_path="codex",
            codex_model="gpt-5.4",
            crm_amo_mode="mock",
            crm_amo_base_url="",
            crm_amo_api_token="",
            crm_amo_upsert_path="/contacts/{entity_id}",
            crm_amo_contact_field_map=None,
        ),
    )
    with pytest.raises(CrmBridgeError):
        fetch_tallanto_student("student-1")

    legacy_calls = []
    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_tallanto_mode="http",
            crm_tallanto_base_url="https://tallanto.example",
            crm_tallanto_api_token="token",
            crm_tallanto_student_path="/students/{student_id}",
            crm_analysis_mode="heuristic",
            codex_cli_path="codex",
            codex_model="gpt-5.4",
            crm_amo_mode="mock",
            crm_amo_base_url="",
            crm_amo_api_token="",
            crm_amo_upsert_path="/contacts/{entity_id}",
            crm_amo_contact_field_map=None,
        ),
    )
    monkeypatch.setattr(
        crm_bridge_module,
        "_fetch_tallanto_student_legacy",
        lambda student_id: legacy_calls.append(student_id) or {"id": student_id, "full_name": "Legacy"},
    )
    legacy_payload = fetch_tallanto_student("legacy-1")
    assert legacy_payload["id"] == "legacy-1"
    assert legacy_calls == ["legacy-1"]

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_tallanto_mode="http",
            crm_tallanto_base_url="https://tallanto.example",
            crm_tallanto_api_token="token",
            crm_tallanto_student_path="/service/api/rest.php",
            crm_analysis_mode="heuristic",
            codex_cli_path="codex",
            codex_model="gpt-5.4",
            crm_amo_mode="mock",
            crm_amo_base_url="",
            crm_amo_api_token="",
            crm_amo_upsert_path="/contacts/{entity_id}",
            crm_amo_contact_field_map=None,
        ),
    )
    monkeypatch.setattr(crm_bridge_module, "_lookup_tallanto_contact_by_field", lambda field, value: None)
    monkeypatch.setattr(
        crm_bridge_module,
        "_lookup_tallanto_contact_list",
        lambda field_values: {"id": "student-2", "full_name": "Иванов Иван"} if "phone_mobile" in field_values else None,
    )
    phone_payload = fetch_tallanto_student("+7 999 000 11 22", lookup_mode="phone")
    assert phone_payload["_lookup_mode"] == "phone"

    monkeypatch.setattr(
        crm_bridge_module,
        "_lookup_tallanto_contact_list",
        lambda field_values: {"id": "student-3", "full_name": "Петров Петр"} if "last_name" in field_values else None,
    )
    full_name_payload = fetch_tallanto_student("Петр Петров", lookup_mode="full_name")
    assert full_name_payload["_lookup_mode"] == "full_name"

    monkeypatch.setattr(crm_bridge_module, "_lookup_tallanto_contact_list", lambda field_values: None)
    with pytest.raises(CrmBridgeError):
        fetch_tallanto_student("Петр Петров", lookup_mode="full_name")

    heuristic = analyze_crm_preview({"full_name": "", "phone": "", "email": "", "program": ""}, {"Поле": "значение"})
    assert "эвристика" not in heuristic.lower()

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_analysis_mode="codex",
            codex_cli_path="codex",
            codex_model="gpt-5.4",
            crm_amo_contact_field_map=None,
        ),
    )
    monkeypatch.setattr(crm_bridge_module, "_codex_analysis", lambda canonical, payload: None)
    fallback_analysis = analyze_crm_preview({"program": "курс"}, {"Поле": "значение"})
    assert "Codex-анализ недоступен" in fallback_analysis
    monkeypatch.setattr(crm_bridge_module, "_codex_analysis", lambda canonical, payload: "Codex summary")
    assert analyze_crm_preview({"program": "курс"}, {"Поле": "значение"}) == "Codex summary"


def test_send_to_amo_and_create_preview_edge_cases(monkeypatch):
    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_amo_mode="mock",
            crm_amo_base_url="",
            crm_amo_api_token="",
            crm_amo_upsert_path="/contacts/{entity_id}",
            crm_amo_contact_field_map=None,
        ),
    )
    mock_payload = _send_to_amo(
        amo_entity_type="contact",
        amo_entity_id="123",
        field_payload={"Id Tallanto": "student-1"},
    )
    assert mock_payload["mode"] == "mock"

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_amo_mode="http",
            crm_amo_base_url=None,
            crm_amo_api_token="token",
            crm_amo_upsert_path="/contacts/{entity_id}",
            crm_amo_contact_field_map=None,
        ),
    )
    with pytest.raises(CrmBridgeError):
        _send_to_amo(amo_entity_type="contact", amo_entity_id="123", field_payload={"x": 1})

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_amo_mode="http",
            crm_amo_base_url="https://educent.amocrm.ru/api/v4",
            crm_amo_api_token="token",
            crm_amo_upsert_path="/contacts/{broken}",
            crm_amo_contact_field_map=None,
        ),
    )
    with pytest.raises(CrmBridgeError):
        _send_to_amo(amo_entity_type="contact", amo_entity_id="123", field_payload={"x": 1})

    captured = {}
    monkeypatch.setattr(
        crm_bridge_module,
        "_http_json_request",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_amo_mode="http",
            crm_amo_base_url="https://educent.amocrm.ru/api/v4",
            crm_amo_api_token="token",
            crm_amo_upsert_path="/contacts/{entity_id}",
            crm_amo_contact_field_map=None,
        ),
    )
    result = _send_to_amo(amo_entity_type="contact", amo_entity_id="123", field_payload={"x": 1})
    assert result == {"ok": True}
    assert captured["method"] == "PATCH"
    assert captured["body"]["entity_id"] == "123"

    session = make_session()
    project = Project(name="CRM", description="Test project")
    session.add(project)
    session.commit()

    monkeypatch.setattr(crm_bridge_module, "fetch_tallanto_student", lambda student_id, lookup_mode="auto": {"id": student_id})
    monkeypatch.setattr(crm_bridge_module, "build_canonical_student", lambda student_id, source_payload: {"student_id": student_id})
    monkeypatch.setattr(crm_bridge_module, "analyze_crm_preview", lambda canonical, payload: "ok")
    monkeypatch.setattr(crm_bridge_module, "amo_write_requires_review", lambda: True)
    with pytest.raises(CrmBridgeError):
        crm_bridge_module.create_crm_sync_preview(
            session,
            project,
            student_id="student-1",
            lookup_mode="auto",
            amo_entity_type="lead",
            amo_entity_id=None,
            field_mapping=None,
            created_by="director",
        )

    preview = create_preview(session, project, review_status="approved", amo_field_payload={"Id Tallanto": "1"})
    session.commit()
    preview.status = "sent"
    with pytest.raises(CrmBridgeError):
        resolve_crm_sync_preview_review(
            session,
            project,
            preview,
            outcome="approved",
            actor="operator",
        )

    preview.status = "previewed"
    with pytest.raises(CrmBridgeError):
        resolve_crm_sync_preview_review(
            session,
            project,
            preview,
            outcome="unsupported",
            actor="operator",
        )

    monkeypatch.setattr(crm_bridge_module, "amo_write_requires_review", lambda: False)
    empty_preview = create_preview(session, project, review_status="not_required", amo_field_payload={"Field A": "value"})
    session.commit()
    failed_preview, empty_summary = send_crm_sync_preview(
        session,
        project,
        empty_preview,
        actor="operator",
        selected_fields=["Unknown field"],
    )
    assert failed_preview.status == "failed"
    assert "нет выбранных полей" in empty_summary.lower()


def test_codex_analysis_and_lookup_edge_cases(monkeypatch):
    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            codex_cli_path="codex",
            codex_model="gpt-5.4",
            source_workspace_root="/workspace",
        ),
    )

    monkeypatch.setattr(
        crm_bridge_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing binary")),
    )
    assert crm_bridge_module._codex_analysis({"student_id": "1"}, {"Field": "value"}) is None

    monkeypatch.setattr(
        crm_bridge_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            crm_bridge_module.subprocess.TimeoutExpired(cmd="codex", timeout=120)
        ),
    )
    assert crm_bridge_module._codex_analysis({"student_id": "1"}, {"Field": "value"}) is None

    monkeypatch.setattr(
        crm_bridge_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="failed"),
    )
    assert crm_bridge_module._codex_analysis({"student_id": "1"}, {"Field": "value"}) is None

    monkeypatch.setattr(
        crm_bridge_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""),
    )
    assert crm_bridge_module._codex_analysis({"student_id": "1"}, {"Field": "value"}) is None

    monkeypatch.setattr(
        crm_bridge_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="summary " * 400),
    )
    successful_summary = crm_bridge_module._codex_analysis({"student_id": "1"}, {"Field": "value"})
    assert successful_summary is not None
    assert len(successful_summary) == 1500

    monkeypatch.setattr(
        crm_bridge_module,
        "settings",
        SimpleNamespace(
            crm_tallanto_base_url="https://tallanto.example",
            crm_tallanto_api_token="token",
            crm_tallanto_student_path="/service/api/rest.php",
        ),
    )
    assert crm_bridge_module._tallanto_headers() == {"X-Auth-Token": "token"}
    assert crm_bridge_module._tallanto_rest_path() == "/service/api/rest.php"
    assert crm_bridge_module._tallanto_not_found({"number": 1502, "name": "Can not find"}) is True
    assert crm_bridge_module._tallanto_select_query_items()

    monkeypatch.setattr(
        crm_bridge_module,
        "_tallanto_request",
        lambda **kwargs: {"number": 1502, "name": "Can not find"},
    )
    assert crm_bridge_module._lookup_tallanto_contact_by_id("student-1") is None
    assert crm_bridge_module._lookup_tallanto_contact_by_field("email1", "family@example.com") is None

    monkeypatch.setattr(
        crm_bridge_module,
        "_tallanto_request",
        lambda **kwargs: {"entry_list": [{}, {}]},
    )
    with pytest.raises(CrmBridgeError):
        crm_bridge_module._lookup_tallanto_contact_list({"phone_mobile": "+79990001122"})

    monkeypatch.setattr(
        crm_bridge_module,
        "_http_json_request",
        lambda **kwargs: {"student": {"id": "student-legacy"}},
    )
    assert crm_bridge_module._fetch_tallanto_student_legacy("student-legacy") == {"id": "student-legacy"}
    monkeypatch.setattr(crm_bridge_module, "_http_json_request", lambda **kwargs: {"id": "student-direct"})
    assert crm_bridge_module._fetch_tallanto_student_legacy("student-direct") == {"id": "student-direct"}
