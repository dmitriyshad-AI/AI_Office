import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.routers.projects as projects_router_module  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import ActionIntent, ApprovalRequest, CallInsight, CrmSyncPreview, EventLog, Project, Task, TaskRun  # noqa: E402
from app.auth import AuthContext  # noqa: E402
from app.routers.projects import (  # noqa: E402
    advance_director_queue,
    apply_task_action,
    archive_project,
    cancel_task_run,
    create_project_call_insight,
    create_project_crm_preview,
    get_action_intent_or_404,
    get_call_insight_or_404,
    get_crm_preview_or_404,
    get_project_or_404,
    get_task_preflight,
    get_task_or_404,
    get_task_run_or_404,
    get_task_run_logs,
    issue_project_stream_token,
    list_projects,
    resolve_project_call_review,
    resolve_project_crm_review,
    restore_project,
    run_task_with_codex,
    send_project_call_insight,
    send_project_crm_preview,
    stream_project_events,
)
from app.schemas import (  # noqa: E402
    CallInsightCreateRequest,
    CallInsightReviewResolveRequest,
    CallInsightSendRequest,
    CrmReviewResolveRequest,
    CrmSyncPreviewCreateRequest,
    CrmSyncSendRequest,
    TaskActionRequest,
    TaskRunCancelRequest,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def test_router_record_helpers_return_objects_and_raise_404s():
    session = make_session()
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="task-1",
        title="Подготовить API",
        brief="Нужен endpoint",
        acceptance_criteria=["Есть маршрут"],
        status="ready",
    )
    task_run = TaskRun(task=task, status="running")
    preview = CrmSyncPreview(
        project=project,
        source_student_id="student-1",
        source_system="tallanto",
        source_payload={},
        canonical_payload={},
        amo_field_payload={},
        field_mapping={},
        analysis_summary="ok",
        created_by="director",
    )
    call_insight = CallInsight(
        project=project,
        source_system="mango",
        source_key="call:1",
        history_summary="summary",
        payload={"source": {"system": "mango"}},
        created_by="director",
    )
    action_intent = ActionIntent(
        project=project,
        task=task,
        task_run=task_run,
        action_key="runtime.host_access",
        status="requested",
        requested_by="codex-worker",
        payload={"target_path": "/Users/dmitrijfabarisov/.ssh"},
    )
    session.add_all([project, task, task_run, preview, call_insight, action_intent])
    session.commit()

    assert get_project_or_404(session, project.id).id == project.id
    assert get_task_or_404(session, project.id, task.id).id == task.id
    assert get_task_run_or_404(session, task_run.id, project.id).id == task_run.id
    assert get_crm_preview_or_404(session, project.id, preview.id).id == preview.id
    assert get_call_insight_or_404(session, project.id, call_insight.id).id == call_insight.id
    assert get_action_intent_or_404(session, project.id, action_intent.id).id == action_intent.id

    with pytest.raises(HTTPException):
        get_project_or_404(session, "missing")
    with pytest.raises(HTTPException):
        get_task_or_404(session, project.id, "missing")
    with pytest.raises(HTTPException):
        get_task_run_or_404(session, "missing", project.id)
    with pytest.raises(HTTPException):
        get_crm_preview_or_404(session, project.id, "missing")
    with pytest.raises(HTTPException):
        get_call_insight_or_404(session, project.id, "missing")
    with pytest.raises(HTTPException):
        get_action_intent_or_404(session, project.id, "missing")


def test_project_listing_prefers_recent_updates_and_archive_restore_flow():
    session = make_session()
    older = Project(name="Older", description="older")
    newer = Project(name="Newer", description="newer")
    session.add_all([older, newer])
    session.commit()

    older.latest_goal_text = "Обновили позже"
    session.commit()

    listed = list_projects(session)
    assert listed[0].id == older.id

    auth = AuthContext(api_key_id="local", role="Director", actor="director")
    archive_response = archive_project(older.id, session, auth)
    assert archive_response.project.status == "archived"
    restore_response = restore_project(older.id, session, auth)
    assert restore_response.project.status == "active"


def test_director_queue_stream_token_and_task_actions(monkeypatch):
    session = make_session()
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="task-1",
        title="Подготовить экран",
        brief="Нужно действие",
        acceptance_criteria=["Есть экран"],
        status="ready",
    )
    task_run = TaskRun(task=task, status="running")
    session.add_all([project, task, task_run])
    session.commit()

    auth = AuthContext(api_key_id="local", role="Director", actor="director")
    monkeypatch.setattr(projects_router_module, "issue_stream_token", lambda project_id, auth: ("token-1", project.created_at))
    token_response = issue_project_stream_token(project.id, session, auth)
    assert token_response.token

    started = []
    monkeypatch.setattr(projects_router_module, "dispatch_director_next_ready_task", lambda db, project, trigger: None)
    monkeypatch.setattr(projects_router_module, "start_codex_execution", lambda *args: started.append(args))
    no_dispatch = advance_director_queue(project.id, session, auth)
    assert no_dispatch.dispatched_task_id is None
    assert "Нет готовых задач" in no_dispatch.summary
    assert started == []

    monkeypatch.setattr(
        projects_router_module,
        "dispatch_director_next_ready_task",
        lambda db, project, trigger: type(
            "Dispatch", (), {"task_id": task.id, "task_run_id": "run-200", "task_title": task.title}
        )(),
    )
    yes_dispatch = advance_director_queue(project.id, session, auth)
    assert yes_dispatch.dispatched_task_id == task.id
    assert started[-1] == (project.id, task.id, "run-200")

    monkeypatch.setattr(projects_router_module, "ensure_task_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        projects_router_module,
        "load_task_runtime_records",
        lambda db, task_id: (None, None, None, None),
    )
    monkeypatch.setattr(
        projects_router_module,
        "evaluate_policy_action",
        lambda *args, **kwargs: type(
            "Eval", (), {"allowed": True, "approval_decision": type("Decision", (), {"summary": "ok"})()}
        )(),
    )
    monkeypatch.setattr(
        projects_router_module,
        "transition_task",
        lambda db, project, task, action, reason: (
            setattr(task, "status", "blocked" if action == "block" else "ready"),
            type("Result", (), {"summary": f"Task {action}"})(),
        )[1],
    )
    monkeypatch.setattr(projects_router_module, "register_task_run_transition", lambda *args, **kwargs: None)
    monkeypatch.setattr(projects_router_module, "load_dependency_map", lambda db, project_id: {})
    monkeypatch.setattr(projects_router_module, "dispatch_director_next_ready_task", lambda db, project, trigger: None)
    action_response = apply_task_action(
        project.id,
        task.id,
        TaskActionRequest(action="block", reason="Нужна пауза"),
        session,
        auth,
    )
    assert action_response.task.status == "blocked"
    assert "Task block" in action_response.summary

    monkeypatch.setattr(
        projects_router_module,
        "evaluate_policy_action",
        lambda *args, **kwargs: type(
            "Eval", (), {"allowed": False, "approval_decision": type("Decision", (), {"summary": "forbidden"})()}
        )(),
    )
    with pytest.raises(HTTPException) as denied_exc:
        apply_task_action(
            project.id,
            task.id,
            TaskActionRequest(action="reset", reason="Нужен сброс"),
            session,
            auth,
        )
    assert denied_exc.value.status_code == 403


def test_run_and_cancel_task_and_log_routes(monkeypatch):
    session = make_session()
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="task-2",
        title="Выполнить задачу",
        brief="Нужно запустить Codex",
        acceptance_criteria=["Есть артефакт"],
        status="ready",
    )
    session.add_all([project, task])
    session.commit()

    auth = AuthContext(api_key_id="local", role="Director", actor="director")
    monkeypatch.setattr(projects_router_module, "build_task_preflight", lambda db, project, task: type("Preflight", (), {"ready": False, "summary": "blocked", "checks": []})())
    with pytest.raises(HTTPException) as preflight_exc:
        run_task_with_codex(project.id, task.id, session, auth)
    assert preflight_exc.value.status_code == 409

    run_record = TaskRun(task=task, status="running")
    session.add(run_record)
    session.commit()

    monkeypatch.setattr(projects_router_module, "build_task_preflight", lambda db, project, task: type("Preflight", (), {"ready": True, "summary": "ok", "checks": []})())
    monkeypatch.setattr(
        projects_router_module,
        "prepare_task_run_for_codex",
        lambda db, project, task, requested_by, requester_role: run_record,
    )
    monkeypatch.setattr(projects_router_module, "load_dependency_map", lambda db, project_id: {})
    started = []
    monkeypatch.setattr(projects_router_module, "start_codex_execution", lambda *args: started.append(args))
    execution_response = run_task_with_codex(project.id, task.id, session, auth)
    assert execution_response.run.id == run_record.id
    assert started[-1] == (project.id, task.id, run_record.id)

    run_record.status = "done"
    session.commit()
    with pytest.raises(HTTPException) as cancel_done_exc:
        cancel_task_run(run_record.id, TaskRunCancelRequest(reason="stop"), session, auth)
    assert cancel_done_exc.value.status_code == 409

    run_record.status = "running"
    run_record.stdout = "line 1"
    session.commit()
    monkeypatch.setattr(projects_router_module, "cancel_codex_execution", lambda db, project, task, task_run, actor, reason=None: "cancelled")
    cancel_response = cancel_task_run(run_record.id, TaskRunCancelRequest(reason="stop"), session, auth)
    assert cancel_response.summary == "cancelled"

    log_response = get_task_run_logs(run_record.id, session)
    assert log_response.stdout == "line 1"

    with pytest.raises(HTTPException):
        get_task_run_logs("missing", session)


@pytest.mark.anyio
async def test_stream_and_operator_endpoints_cover_queue_and_error_paths(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    session = session_factory()
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="task-3",
        title="Проверить queue",
        brief="Нужны операторские ветки",
        acceptance_criteria=["Есть результат"],
        status="ready",
    )
    approval_request = ApprovalRequest(
        project=project,
        action="runtime.host_access",
        risk_level="high",
        reason="needs approval",
        requested_by="director",
    )
    preview = CrmSyncPreview(
        project=project,
        source_student_id="student-1",
        source_system="tallanto",
        source_payload={},
        canonical_payload={},
        amo_field_payload={},
        field_mapping={},
        analysis_summary="ok",
        created_by="director",
        status="previewed",
        review_status="pending",
    )
    insight = CallInsight(
        project=project,
        source_system="mango",
        source_key="call-queue",
        history_summary="summary",
        payload={"source": {"system": "mango"}},
        created_by="director",
        review_status="pending",
    )
    session.add_all([project, task, approval_request, preview, insight])
    session.flush()
    event = EventLog(
        project_id=project.id,
        event_type="task_created",
        payload={"task_key": "task-3"},
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()

    auth = AuthContext(api_key_id="local", role="Director", actor="director")
    monkeypatch.setattr(projects_router_module, "SessionLocal", session_factory)

    class FakeRequest:
        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 1

    response = await stream_project_events(project.id, FakeRequest())
    first_chunk = await response.body_iterator.__anext__()
    assert "keepalive" in first_chunk or "project_event" in first_chunk

    policy_denied = type("Eval", (), {"allowed": False, "approval_decision": type("Decision", (), {"summary": "forbidden"})()})()
    monkeypatch.setattr(projects_router_module, "evaluate_policy_action", lambda *args, **kwargs: policy_denied)
    with pytest.raises(HTTPException) as call_ingest_exc:
        create_project_call_insight(
            project.id,
            CallInsightCreateRequest.model_validate(
                {
                    "source": {"system": "mango", "source_call_id": "call-1"},
                    "processing": {"analysis_status": "done"},
                    "identity_hints": {"phone": "+79990001122"},
                    "call_summary": {"history_summary": "summary"},
                    "sales_insight": {"lead_priority": "warm"},
                }
            ),
            session,
            auth,
        )
    assert call_ingest_exc.value.status_code == 403

    monkeypatch.setattr(
        projects_router_module,
        "resolve_call_insight_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(projects_router_module.CallInsightError("bad review")),
    )
    with pytest.raises(HTTPException) as call_review_exc:
        resolve_project_call_review(
            project.id,
            insight.id,
            CallInsightReviewResolveRequest(outcome="approved", matched_amo_contact_id=123),
            session,
            auth,
        )
    assert call_review_exc.value.status_code == 409

    insight.status = "sent"
    session.commit()
    with pytest.raises(HTTPException) as sent_call_exc:
        send_project_call_insight(
            project.id,
            insight.id,
            CallInsightSendRequest(matched_amo_contact_id=123),
            session,
            auth,
        )
    assert sent_call_exc.value.status_code == 409

    insight.status = "pending"
    insight.review_status = "pending"
    session.commit()
    monkeypatch.setattr(projects_router_module, "amo_write_requires_review", lambda: True)
    with pytest.raises(HTTPException) as not_approved_call_exc:
        send_project_call_insight(
            project.id,
            insight.id,
            CallInsightSendRequest(matched_amo_contact_id=123),
            session,
            auth,
        )
    assert not_approved_call_exc.value.status_code == 409

    monkeypatch.setattr(projects_router_module, "evaluate_policy_action", lambda *args, **kwargs: policy_denied)
    with pytest.raises(HTTPException) as crm_preview_exc:
        create_project_crm_preview(
            project.id,
            CrmSyncPreviewCreateRequest(student_id="student-1", lookup_mode="auto", amo_entity_type="contact"),
            session,
            auth,
        )
    assert crm_preview_exc.value.status_code == 403

    monkeypatch.setattr(
        projects_router_module,
        "resolve_crm_sync_preview_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(projects_router_module.CrmBridgeError("bad review", status_code=409)),
    )
    with pytest.raises(HTTPException) as crm_review_exc:
        resolve_project_crm_review(
            project.id,
            preview.id,
            CrmReviewResolveRequest(outcome="approved"),
            session,
            auth,
        )
    assert crm_review_exc.value.status_code == 409

    preview.status = "sent"
    session.commit()
    with pytest.raises(HTTPException) as sent_preview_exc:
        send_project_crm_preview(
            project.id,
            preview.id,
            CrmSyncSendRequest(),
            session,
            auth,
        )
    assert sent_preview_exc.value.status_code == 409

    preview.status = "previewed"
    preview.review_status = "pending"
    session.commit()
    monkeypatch.setattr(projects_router_module, "amo_write_requires_review", lambda: True)
    with pytest.raises(HTTPException) as review_required_exc:
        send_project_crm_preview(
            project.id,
            preview.id,
            CrmSyncSendRequest(),
            session,
            auth,
        )
    assert review_required_exc.value.status_code == 409

    monkeypatch.setattr(
        projects_router_module,
        "build_task_preflight",
        lambda db, project, task: (_ for _ in ()).throw(projects_router_module.OrchestrationError("broken preflight")),
    )
    with pytest.raises(HTTPException) as preflight_exc:
        get_task_preflight(project.id, task.id, session)
    assert preflight_exc.value.status_code == 409
