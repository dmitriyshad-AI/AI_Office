import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.call_insights import (  # noqa: E402
    CallInsightError,
    _coerce_datetime,
    _derive_call_review_reason,
    build_call_insight_artifact_content,
    build_call_insight_amo_payload,
    build_call_insight_source_key,
    create_call_insight,
    resolve_call_insight_review,
    send_call_insight_to_amo,
)
from app.db import Base  # noqa: E402
from app.models import Artifact, CallInsight, EventLog, Project  # noqa: E402


def build_payload(**overrides):
    payload = {
        "source": {
            "system": "mango_analyse",
            "source_call_id": "call-1001",
            "call_record_id": "record-1001",
            "source_file": "/tmp/record-1001.mp3",
            "source_filename": "record-1001.mp3",
            "started_at": "2026-03-19T10:00:00Z",
            "duration_sec": 305.2,
            "manager_name": "Анна",
            "phone": "+79990001122",
        },
        "processing": {"analysis_status": "done"},
        "identity_hints": {
            "parent_fio": "Иванова Анна",
            "child_fio": "Петр Иванов",
            "email": "family@example.com",
            "phone": "+79990001122",
        },
        "call_summary": {
            "history_summary": "Родитель запросил материалы и согласовал follow-up.",
            "history_short": "Нужен follow-up.",
            "evidence": [{"speaker": "Клиент", "ts": "00:21.0", "text": "Пришлите материалы."}],
        },
        "sales_insight": {
            "lead_priority": "warm",
            "follow_up_score": 72,
            "next_step": {"action": "Отправить материалы", "due": "завтра"},
            "objections": ["цена"],
            "interests": {"products": ["Годовой курс"], "subjects": ["Математика"]},
        },
    }
    for key, value in overrides.items():
        payload[key] = value
    return payload


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def test_coerce_datetime_accepts_iso_strings_and_datetime_values():
    aware = _coerce_datetime("2026-03-19T10:00:00Z")
    assert aware == datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

    naive = _coerce_datetime(datetime(2026, 3, 19, 10, 0))
    assert naive == datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

    empty = _coerce_datetime("")
    assert empty is None


def test_coerce_datetime_rejects_invalid_values():
    with pytest.raises(CallInsightError):
        _coerce_datetime("not-a-date")

    with pytest.raises(CallInsightError):
        _coerce_datetime(123)


def test_build_call_insight_source_key_uses_best_available_identifier():
    assert build_call_insight_source_key(build_payload()) == "call:call-1001"

    no_call_id = build_payload(
        source={
            "call_record_id": "record-42",
            "source_file": "/tmp/fallback.mp3",
            "source_filename": "fallback.mp3",
        }
    )
    assert build_call_insight_source_key(no_call_id) == "record:record-42"

    file_only = build_payload(
        source={
            "source_file": "/tmp/only-file.mp3",
            "source_filename": "only-file.mp3",
        }
    )
    assert build_call_insight_source_key(file_only) == "file:/tmp/only-file.mp3"

    filename_only = build_payload(
        source={
            "source_filename": "only-name.mp3",
            "started_at": "2026-03-19T10:00:00Z",
        }
    )
    assert (
        build_call_insight_source_key(filename_only)
        == "filename:only-name.mp3|started_at:2026-03-19T10:00:00Z"
    )

    with pytest.raises(CallInsightError):
        build_call_insight_source_key({"source": {}})


def test_build_call_insight_artifact_content_is_human_readable_with_fallbacks():
    content = build_call_insight_artifact_content(build_payload())
    assert "Источник: mango_analyse" in content
    assert "Ученик: Петр Иванов" in content
    assert "Следующий шаг: Отправить материалы" in content

    fallback_content = build_call_insight_artifact_content(
        {
            "source": {},
            "identity_hints": {},
            "call_summary": {},
            "sales_insight": {},
        }
    )
    assert "Источник: unknown" in fallback_content
    assert "Ключ звонка: —" in fallback_content
    assert "AI-сводка:\n—" in fallback_content


def test_create_call_insight_persists_insight_artifact_and_events():
    session = make_session()
    project = Project(name="Calls", description="Test project")
    session.add(project)
    session.commit()

    result = create_call_insight(
        session,
        project,
        payload=build_payload(),
        created_by="director",
    )
    session.commit()

    assert result.insight.project_id == project.id
    assert result.insight.match_status == "pending_match"
    assert result.insight.processing_status == "done"
    assert result.artifact.kind == "call_insight"
    assert "Call insight сохранён." in result.summary

    persisted_insight = session.scalar(select(CallInsight))
    persisted_artifact = session.scalar(select(Artifact))
    events = session.scalars(select(EventLog).order_by(EventLog.created_at.asc())).all()

    assert persisted_insight is not None
    assert persisted_artifact is not None
    assert persisted_artifact.project_id == project.id
    assert [event.event_type for event in events] == ["artifact_created", "call_insight_ingested"]
    assert persisted_insight.review_status == "not_required"


def test_call_review_reason_and_amo_payload_cover_operational_cases(monkeypatch):
    monkeypatch.setattr("app.call_insights.amo_write_requires_review", lambda: True)

    payload = build_payload(
        identity_hints={
            "parent_fio": "Иванова Анна",
            "child_fio": "",
            "phone": "+79990001122",
        },
        quality_flags={"manual_review_required": True},
    )
    reason = _derive_call_review_reason(payload)
    assert reason is not None
    assert "ручная проверка" in reason.lower()
    assert "не определен конкретный ученик" in reason.lower()

    session = make_session()
    project = Project(name="Calls", description="Test project")
    session.add(project)
    session.commit()

    result = create_call_insight(
        session,
        project,
        payload=build_payload(),
        created_by="director",
    )
    amo_payload = build_call_insight_amo_payload(result.insight)
    assert amo_payload["Авто история общения"].startswith("Родитель запросил")
    assert amo_payload["AI-рекомендованный следующий шаг"] == "Отправить материалы"
    assert "Нужен follow-up." in amo_payload["Последняя AI-сводка"]


def test_resolve_call_review_requires_match_for_approval():
    session = make_session()
    project = Project(name="Calls", description="Test project")
    session.add(project)
    session.commit()

    result = create_call_insight(
        session,
        project,
        payload=build_payload(quality_flags={"manual_review_required": True}),
        created_by="director",
    )
    session.commit()

    with pytest.raises(CallInsightError):
        resolve_call_insight_review(
            session,
            project,
            result.insight,
            outcome="approved",
            actor="director",
        )

    insight, summary = resolve_call_insight_review(
        session,
        project,
        result.insight,
        outcome="approved",
        actor="director",
        matched_amo_contact_id=75807689,
    )
    assert insight.review_status == "approved"
    assert insight.match_status == "matched"
    assert insight.matched_amo_contact_id == 75807689
    assert "подтвердил ученика" in summary.lower()


def test_create_call_insight_rejects_missing_history_and_duplicate_source_keys():
    session = make_session()
    project = Project(name="Calls", description="Test project")
    session.add(project)
    session.commit()

    with pytest.raises(CallInsightError):
        create_call_insight(
            session,
            project,
            payload=build_payload(call_summary={"history_summary": ""}),
            created_by="director",
        )

    create_call_insight(
        session,
        project,
        payload=build_payload(),
        created_by="director",
    )
    session.commit()

    with pytest.raises(CallInsightError):
        create_call_insight(
            session,
            project,
            payload=build_payload(),
            created_by="director",
        )


def test_create_call_insight_validates_shape_and_review_reason_edge_cases(monkeypatch):
    session = make_session()
    project = Project(name="Calls", description="Test project")
    session.add(project)
    session.commit()

    monkeypatch.setattr("app.call_insights.amo_write_requires_review", lambda: True)
    family_reason = _derive_call_review_reason(
        build_payload(
            identity_hints={"parent_fio": "Иванова Анна", "child_fio": "Петр Иванов"},
            quality_flags={"ambiguous_identity": True, "family_match": True},
        )
    )
    assert family_reason is not None
    assert "неоднозначность" in family_reason.lower()

    with pytest.raises(CallInsightError):
        create_call_insight(
            session,
            project,
            payload={"source": [], "call_summary": {}, "sales_insight": {}},
            created_by="director",
        )

    with pytest.raises(CallInsightError):
        create_call_insight(
            session,
            project,
            payload=build_payload(source={"system": "mango", "started_at": 123}),
            created_by="director",
        )


def test_resolve_and_send_call_insight_cover_success_failure_and_rejection(monkeypatch):
    session = make_session()
    project = Project(name="Calls", description="Test project")
    session.add(project)
    session.commit()

    monkeypatch.setattr("app.call_insights.amo_write_requires_review", lambda: True)
    result = create_call_insight(
        session,
        project,
        payload=build_payload(quality_flags={"manual_review_required": True}),
        created_by="director",
    )
    session.commit()

    family_insight, family_summary = resolve_call_insight_review(
        session,
        project,
        result.insight,
        outcome="family_case",
        actor="operator",
    )
    assert family_insight.match_status == "family_review"
    assert "семейный кейс" in family_summary.lower()

    duplicate_insight, _ = resolve_call_insight_review(
        session,
        project,
        family_insight,
        outcome="duplicate",
        actor="operator",
    )
    assert duplicate_insight.match_status == "duplicate_candidate"

    with pytest.raises(CallInsightError):
        resolve_call_insight_review(
            session,
            project,
            duplicate_insight,
            outcome="unsupported",
            actor="operator",
        )

    success_result = create_call_insight(
        session,
        project,
        payload=build_payload(
            source={"system": "mango", "source_call_id": "call-2001", "phone": "+79995557766"},
            quality_flags={"manual_review_required": True},
        ),
        created_by="director",
    )
    session.commit()
    resolve_call_insight_review(
        session,
        project,
        success_result.insight,
        outcome="approved",
        actor="operator",
        matched_amo_contact_id=75807689,
    )

    monkeypatch.setattr(
        "app.call_insights.send_amo_field_payload",
        lambda **kwargs: {"result": "ok", "field_payload": kwargs["field_payload"]},
    )
    sent_insight, sent_summary = send_call_insight_to_amo(
        session,
        project,
        success_result.insight,
        actor="operator",
        field_overrides={"AI-приоритет": "hot"},
    )
    assert sent_insight.status == "sent"
    assert sent_insight.send_result["result"] == "ok"
    assert "контакта 75807689" in sent_summary

    failing_result = create_call_insight(
        session,
        project,
        payload=build_payload(
            source={"system": "mango", "source_call_id": "call-3001", "phone": "+79994443322"},
            quality_flags={"manual_review_required": True},
        ),
        created_by="director",
    )
    session.commit()
    resolve_call_insight_review(
        session,
        project,
        failing_result.insight,
        outcome="approved",
        actor="operator",
        matched_amo_contact_id=100500,
    )

    def fail_send(**kwargs):
        from app.crm_bridge import CrmBridgeError

        raise CrmBridgeError("AMO unavailable", status_code=502)

    monkeypatch.setattr("app.call_insights.send_amo_field_payload", fail_send)
    failed_insight, failed_summary = send_call_insight_to_amo(
        session,
        project,
        failing_result.insight,
        actor="operator",
    )
    assert failed_insight.status == "failed"
    assert "ошибкой" in failed_summary.lower()

    waiting_result = create_call_insight(
        session,
        project,
        payload=build_payload(
            source={"system": "mango", "source_call_id": "call-4001", "phone": "+79991110011"},
            quality_flags={"manual_review_required": True},
        ),
        created_by="director",
    )
    session.commit()
    with pytest.raises(CallInsightError):
        send_call_insight_to_amo(
            session,
            project,
            waiting_result.insight,
            actor="operator",
        )

    waiting_result.insight.review_status = "approved"
    waiting_result.insight.matched_amo_contact_id = None
    with pytest.raises(CallInsightError):
        send_call_insight_to_amo(
            session,
            project,
            waiting_result.insight,
            actor="operator",
        )

    sent_insight.status = "sent"
    with pytest.raises(CallInsightError):
        resolve_call_insight_review(
            session,
            project,
            sent_insight,
            outcome="approved",
            actor="operator",
            matched_amo_contact_id=75807689,
        )

    artifacts = session.scalars(select(Artifact)).all()
    assert any(item.kind == "call_sync_result" for item in artifacts)
