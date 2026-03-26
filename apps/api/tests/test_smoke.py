import json
import inspect
import io
from pathlib import Path
import time
import sys
from datetime import timedelta
from dataclasses import replace
from urllib import parse as url_parse
from urllib import error as url_error

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_test_client(
    monkeypatch,
    database_path: Path,
    runtime_root: Path,
    worker_mode: str = "mock",
    timeout_seconds: int = 900,
    director_auto_run_enabled: bool = False,
    director_heartbeat_enabled: bool = False,
):
    director_key = "test-director-key"
    human_key = "test-human-key"
    devops_key = "test-devops-key"
    api_keys_spec = (
        f"{director_key}:Director:director,"
        f"{human_key}:Human:human,"
        f"{devops_key}:DevOps:devops"
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("SOURCE_WORKSPACE_ROOT", str(Path(__file__).resolve().parents[3]))
    monkeypatch.setenv("AI_OFFICE_API_KEY", director_key)
    monkeypatch.setenv("AI_OFFICE_API_KEYS", api_keys_spec)
    monkeypatch.setenv("AI_OFFICE_STREAM_TOKEN_SECRET", "test-stream-secret")
    monkeypatch.setenv("TASK_CONTAINER_DRIVER", "process")
    monkeypatch.setenv("CODEX_WORKER_MODE", worker_mode)
    monkeypatch.setenv("CODEX_EXECUTION_TIMEOUT_SECONDS", str(timeout_seconds))
    monkeypatch.setenv(
        "DIRECTOR_AUTO_RUN_ENABLED",
        "true" if director_auto_run_enabled else "false",
    )
    monkeypatch.setenv(
        "DIRECTOR_HEARTBEAT_ENABLED",
        "true" if director_heartbeat_enabled else "false",
    )
    monkeypatch.setenv("DIRECTOR_HEARTBEAT_POLL_SECONDS", "1")
    monkeypatch.setenv("DIRECTOR_STALE_RUN_GRACE_SECONDS", "10")

    for module_name in [
        "app.amo_integration",
        "app.config",
        "app.auth",
        "app.db",
        "app.main",
        "app.codex_worker",
        "app.models",
        "app.orchestration",
        "app.runtime",
        "app.policy",
        "app.planner",
        "app.preflight",
        "app.reviewer",
        "app.call_insights",
        "app.crm_bridge",
        "app.action_intents",
        "app.director_heartbeat",
        "app.routers.integrations",
        "app.routers.projects",
    ]:
        sys.modules.pop(module_name, None)

    from app.db import Base, engine
    from app.main import app

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)
    client.headers.update({"X-API-Key": director_key})
    return client


def build_call_insight_payload(
    *,
    source_call_id: str = "mango-call-1001",
    source_filename: str = "2026-03-19__10-00-00__79990001122__Иванов Иван_1001.mp3",
    phone: str = "+79990001122",
) -> dict:
    return {
        "schema_version": "call_insight_v1",
        "source": {
            "system": "mango_analyse",
            "call_record_id": "1001",
            "source_call_id": source_call_id,
            "source_file": f"/tmp/{source_filename}",
            "source_filename": source_filename,
            "started_at": "2026-03-19T10:00:00Z",
            "duration_sec": 312.4,
            "direction": "outbound",
            "manager_name": "Иванов Иван",
            "phone": phone,
        },
        "processing": {
            "transcription_status": "done",
            "resolve_status": "done",
            "analysis_status": "done",
            "resolve_quality_score": 91.0,
        },
        "identity_hints": {
            "phone": phone,
            "parent_fio": "Иванова Анна",
            "child_fio": "Петр Иванов",
            "email": "family@example.com",
            "grade_current": "9",
            "school": "Школа 57",
            "preferred_channel": "telegram",
        },
        "call_summary": {
            "history_summary": (
                "19.03.2026 10:00 менеджер Иванов Иван обсудил с родителем программу по математике "
                "для 9 класса. Родитель уточнил формат и бюджет, попросил материалы. "
                "Договорились отправить программу и перезвонить на этой неделе."
            ),
            "history_short": "Обсудили программу по математике и договорились о follow-up.",
            "evidence": [
                {
                    "speaker": "Клиент",
                    "ts": "00:32.1",
                    "text": "Нас интересует математика для 9 класса.",
                }
            ],
        },
        "sales_insight": {
            "interests": {
                "products": ["годовые курсы"],
                "format": ["онлайн"],
                "subjects": ["математика"],
                "exam_targets": ["ОГЭ"],
            },
            "commercial": {
                "price_sensitivity": "medium",
                "budget": "до 100000",
                "discount_interest": True,
            },
            "objections": ["цена"],
            "next_step": {
                "action": "Отправить материалы и перезвонить",
                "due": "на этой неделе",
            },
            "lead_priority": "warm",
            "follow_up_score": 72,
            "follow_up_reason": "Есть интерес и согласованный следующий шаг.",
            "personal_offer": None,
            "pain_points": ["цена"],
            "tags": ["follow_up", "math"],
        },
        "quality_flags": {
            "stereo_mode": "split",
            "same_ts_cross": 0,
            "non_conversation": False,
        },
        "raw_analysis": {
            "analysis_schema_version": "v2",
        },
    }


class _JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_project_goal_flow(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_test.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    unauthorized_projects = client.get("/projects", headers={"X-API-Key": "wrong-key"})
    assert unauthorized_projects.status_code == 401

    project = client.post(
        "/projects",
        json={"name": "Smoke Test Project", "description": "API smoke test"},
    )
    assert project.status_code == 201

    project_id = project.json()["id"]

    stream_token_response = client.post(f"/projects/{project_id}/stream-token")
    assert stream_token_response.status_code == 200
    stream_token_payload = stream_token_response.json()
    assert stream_token_payload["token"]
    assert stream_token_payload["expires_at"]

    from app.main import app

    anonymous_client = TestClient(app)
    unauthorized_stream = anonymous_client.get(f"/projects/{project_id}/events/stream")
    assert unauthorized_stream.status_code == 401

    invalid_stream_token = anonymous_client.get(
        f"/projects/{project_id}/events/stream",
        params={"stream_token": "invalid"},
    )
    assert invalid_stream_token.status_code == 401
    import app.auth as auth_module

    stream_principal = auth_module.verify_stream_token(
        stream_token_payload["token"],
        project_id=project_id,
    )
    assert stream_principal.role == "Director"
    assert stream_principal.actor == "director"

    policies = client.get(f"/projects/{project_id}/approval-policies")
    assert policies.status_code == 200
    assert len(policies.json()) >= 9

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    assert len(goal.json()["created_tasks"]) == 7

    tasks = client.get(f"/projects/{project_id}/tasks")
    assert tasks.status_code == 200
    task_payload = tasks.json()
    assert len(task_payload) == 7
    ready_tasks = [task for task in task_payload if task["status"] == "ready"]
    assert len(ready_tasks) == 1

    ready_task_id = ready_tasks[0]["id"]
    ready_task_key = ready_tasks[0]["task_key"]

    project_runs = client.get(f"/projects/{project_id}/runs")
    assert project_runs.status_code == 200
    assert len(project_runs.json()) == 7
    assert {run["status"] for run in project_runs.json()} == {"provisioned"}

    runtime = client.get(f"/projects/{project_id}/tasks/{ready_task_id}/runtime")
    assert runtime.status_code == 200
    runtime_payload = runtime.json()
    assert runtime_payload["workspace"]["task_id"] == ready_task_id
    assert runtime_payload["workspace"]["sandbox_mode"] == "workspace-write"
    assert runtime_payload["workspace"]["state"] == "provisioned"
    assert runtime_payload["workspace"]["workspace_mode"] in {"snapshot-copy", "git-worktree"}
    assert runtime_payload["workspace"]["sync_status"].startswith("seeded")
    assert Path(runtime_payload["workspace"]["source_root_path"]).exists()
    assert runtime_payload["environment"]["runtime_kind"] == "workspace-runtime"
    assert runtime_payload["environment"]["runtime_status"] == "ready"
    assert runtime_payload["run_policy"]["filesystem_scope"] == "task-workspace-only"
    assert len(runtime_payload["runs"]) == 1
    assert runtime_payload["runs"][0]["status"] == "provisioned"

    preflight = client.get(f"/projects/{project_id}/tasks/{ready_task_id}/preflight")
    assert preflight.status_code == 200
    preflight_payload = preflight.json()
    assert preflight_payload["ready"] is True
    assert any(check["key"] == "workspace.exists" and check["status"] == "pass" for check in preflight_payload["checks"])
    assert any(check["key"] == "execution.timeout" and check["status"] == "pass" for check in preflight_payload["checks"])

    workspace_path = Path(runtime_payload["workspace"]["workspace_path"])
    context_file_path = Path(runtime_payload["workspace"]["context_file_path"])
    assert workspace_path.exists()
    assert context_file_path.exists()

    context_payload = json.loads(context_file_path.read_text(encoding="utf-8"))
    assert context_payload["task_key"] == ready_task_key
    assert context_payload["workspace_path"] == str(workspace_path)
    assert context_payload["source_root_path"] == runtime_payload["workspace"]["source_root_path"]
    assert context_payload["workspace_mode"] == runtime_payload["workspace"]["workspace_mode"]
    assert (workspace_path / "README.md").exists()

    initial_decisions = client.get(f"/projects/{project_id}/approval-decisions")
    assert initial_decisions.status_code == 200
    assert any(
        decision["action_key"] == "runtime.provision" and decision["outcome"] == "approved"
        for decision in initial_decisions.json()
    )

    start_task = client.post(f"/projects/{project_id}/tasks/{ready_task_id}/run")
    assert start_task.status_code == 200
    assert start_task.json()["task"]["status"] == "running"
    execution_run_id = start_task.json()["run"]["id"]

    for _ in range(60):
        task_log = client.get(f"/task-runs/{execution_run_id}/logs")
        assert task_log.status_code == 200
        if task_log.json()["status"] == "done":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Codex mock execution did not complete in time")

    completed_log = client.get(f"/task-runs/{execution_run_id}/logs")
    assert completed_log.status_code == 200
    assert completed_log.json()["status"] == "done"
    assert "Mock worker wrote" in completed_log.json()["stdout"]
    assert "Reviewer approved" in completed_log.json()["stdout"]

    runtime_after_start = client.get(f"/projects/{project_id}/tasks/{ready_task_id}/runtime")
    assert runtime_after_start.status_code == 200
    assert runtime_after_start.json()["workspace"]["state"] == "done"

    runtime_after_complete = client.get(f"/projects/{project_id}/tasks/{ready_task_id}/runtime")
    assert runtime_after_complete.status_code == 200
    assert runtime_after_complete.json()["workspace"]["state"] == "done"

    package_policy_check = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.install_package",
            "task_id": ready_task_id,
            "requested_by": "director",
            "metadata": {"registry": "pypi.org", "package_name": "pytest"},
        },
    )
    assert package_policy_check.status_code == 200
    assert package_policy_check.json()["allowed"] is True
    assert package_policy_check.json()["approval_decision"]["actor"] == "director"
    assert package_policy_check.json()["approval_decision"]["outcome"] == "approved"
    assert package_policy_check.json()["approval_request"] is None

    package_policy_check_human = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.install_package",
            "task_id": ready_task_id,
            "requested_by": "director",
            "metadata": {"registry": "pypi.org", "package_name": "pytest"},
        },
        headers={"X-API-Key": "test-human-key"},
    )
    assert package_policy_check_human.status_code == 200
    assert package_policy_check_human.json()["allowed"] is False
    assert package_policy_check_human.json()["approval_decision"]["outcome"] == "rejected"
    assert package_policy_check_human.json()["approval_request"] is None

    tasks_after_completion = client.get(f"/projects/{project_id}/tasks")
    assert tasks_after_completion.status_code == 200
    tasks_by_key = {task["task_key"]: task for task in tasks_after_completion.json()}
    assert tasks_by_key["product_strategy"]["status"] == "done"
    assert tasks_by_key["methodology_blueprint"]["status"] == "ready"
    assert tasks_by_key["system_architecture"]["status"] == "ready"

    block_task = client.post(
        f"/projects/{project_id}/tasks/{tasks_by_key['methodology_blueprint']['id']}/actions",
        json={"action": "block", "reason": "Manual audit block"},
    )
    assert block_task.status_code == 200
    assert block_task.json()["task"]["status"] == "blocked"

    blocked_runtime = client.get(
        f"/projects/{project_id}/tasks/{tasks_by_key['methodology_blueprint']['id']}/runtime"
    )
    assert blocked_runtime.status_code == 200
    assert blocked_runtime.json()["workspace"]["state"] == "blocked"

    reset_task = client.post(
        f"/projects/{project_id}/tasks/{tasks_by_key['methodology_blueprint']['id']}/actions",
        json={"action": "reset"},
    )
    assert reset_task.status_code == 200
    assert reset_task.json()["task"]["status"] == "ready"

    reset_runtime = client.get(
        f"/projects/{project_id}/tasks/{tasks_by_key['methodology_blueprint']['id']}/runtime"
    )
    assert reset_runtime.status_code == 200
    assert reset_runtime.json()["workspace"]["state"] == "provisioned"

    host_access_policy_check = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.host_access",
            "task_id": ready_task_id,
            "task_run_id": execution_run_id,
            "requested_by": "director",
            "metadata": {"target_path": "/Users/dmitrijfabarisov/.ssh"},
        },
    )
    assert host_access_policy_check.status_code == 200
    assert host_access_policy_check.json()["allowed"] is False
    assert host_access_policy_check.json()["approval_decision"]["outcome"] == "pending_human"
    assert host_access_policy_check.json()["approval_request"]["status"] == "pending"
    assert host_access_policy_check.json()["action_intent"]["status"] == "pending_approval"
    assert host_access_policy_check.json()["action_intent"]["task_run_id"] == execution_run_id
    approval_request_id = host_access_policy_check.json()["approval_request"]["id"]

    resolve_approval_forbidden = client.post(
        f"/projects/{project_id}/approvals/{approval_request_id}/resolve",
        json={
            "outcome": "approved",
            "summary": "DevOps should not be allowed to resolve human approvals.",
        },
        headers={"X-API-Key": "test-devops-key"},
    )
    assert resolve_approval_forbidden.status_code == 403

    resolve_approval = client.post(
        f"/projects/{project_id}/approvals/{approval_request_id}/resolve",
        json={
            "outcome": "approved",
            "actor": "human",
            "summary": "Human approved host access for this simulation.",
        },
        headers={"X-API-Key": "test-human-key"},
    )
    assert resolve_approval.status_code == 200
    assert resolve_approval.json()["approval_request"]["status"] == "approved"
    assert resolve_approval.json()["approval_decision"]["outcome"] == "approved"
    assert resolve_approval.json()["risk_assessment"]["status"] == "approved"
    assert resolve_approval.json()["action_intent"]["status"] == "completed"
    assert resolve_approval.json()["action_intent"]["dispatch_task_run_id"] is not None
    assert "resumed" in resolve_approval.json()["action_intent"]["execution_summary"].lower()

    host_access_policy_retry = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.host_access",
            "task_id": ready_task_id,
            "task_run_id": execution_run_id,
            "requested_by": "director",
            "metadata": {"target_path": "/Users/dmitrijfabarisov/.ssh"},
        },
    )
    assert host_access_policy_retry.status_code == 200
    assert host_access_policy_retry.json()["allowed"] is True
    assert host_access_policy_retry.json()["approval_decision"]["outcome"] == "approved"
    assert host_access_policy_retry.json()["approval_request"]["status"] == "approved"
    assert host_access_policy_retry.json()["action_intent"]["status"] == "completed"

    messages = client.get(f"/projects/{project_id}/messages")
    assert messages.status_code == 200
    message_roles = [message["role"] for message in messages.json()]
    assert message_roles[0] == "user"
    assert "director" in message_roles
    assert "reviewer" in message_roles
    assert any(
        message["role"] == "director" and "Прогресс:" in message["content"]
        for message in messages.json()
    )

    artifacts = client.get(f"/projects/{project_id}/artifacts")
    assert artifacts.status_code == 200
    assert any(artifact["kind"] == "codex_result" for artifact in artifacts.json())
    assert any(artifact["kind"] == "review_report" for artifact in artifacts.json())
    assert any(artifact["kind"] == "workspace_change_summary" for artifact in artifacts.json())

    reviews = client.get(f"/projects/{project_id}/reviews")
    assert reviews.status_code == 200
    assert len(reviews.json()) == 1
    assert reviews.json()[0]["task_id"] == ready_task_id
    assert reviews.json()[0]["recommendation"] == "approved"
    assert reviews.json()[0]["reviewer_role"] == "QAReviewer"

    risk_assessments = client.get(f"/projects/{project_id}/risk-assessments")
    assert risk_assessments.status_code == 200
    assert any(
        assessment["action_key"] == "runtime.host_access"
        and assessment["status"] == "approved"
        for assessment in risk_assessments.json()
    )

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert "project_created" in event_types
    assert "goal_planned" in event_types
    assert "task_created" in event_types
    assert "task_started" in event_types
    assert "task_completed" in event_types
    assert "task_execution_queued" in event_types
    assert "task_execution_started" in event_types
    assert "task_execution_completed" in event_types
    assert "task_review_started" in event_types
    assert "task_review_completed" in event_types
    assert "task_sent_to_review" in event_types
    assert "task_review_approved" in event_types
    assert "artifact_created" in event_types
    assert "task_blocked" in event_types
    assert "task_reset" in event_types
    assert "task_runtime_provisioned" in event_types
    assert "risk_assessed" in event_types
    assert "approval_decided" in event_types
    assert "approval_requested" in event_types
    assert "approval_resolved" in event_types
    assert "approval_approved" in event_types
    assert "agent_status_changed" in event_types
    assert "project_status_changed" in event_types

    approvals = client.get(f"/projects/{project_id}/approvals")
    assert approvals.status_code == 200
    assert len(approvals.json()) == 1
    assert approvals.json()[0]["action"] == "runtime.host_access"
    assert approvals.json()[0]["status"] == "approved"
    assert approvals.json()[0]["resolved_by"] == "human"

    action_intents = client.get(f"/projects/{project_id}/action-intents")
    assert action_intents.status_code == 200
    assert len(action_intents.json()) == 1
    assert action_intents.json()[0]["approval_request_id"] == approval_request_id
    assert action_intents.json()[0]["status"] == "completed"
    assert action_intents.json()[0]["task_run_id"] == execution_run_id
    assert action_intents.json()[0]["dispatch_task_run_id"] is not None

    task_action_intents = client.get(
        f"/projects/{project_id}/tasks/{ready_task_id}/action-intents"
    )
    assert task_action_intents.status_code == 200
    assert len(task_action_intents.json()) == 1

    project_runs_after_intent = client.get(f"/projects/{project_id}/runs")
    assert project_runs_after_intent.status_code == 200
    assert any(
        run["environment_name"] == "intent:runtime.host_access" and run["status"] == "done"
        for run in project_runs_after_intent.json()
    )

    old_runtime_root = Path(runtime_payload["workspace"]["root_path"])
    goal_refresh = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Refresh the plan for the same workspace"},
    )
    assert goal_refresh.status_code == 200
    assert not old_runtime_root.exists()

    refreshed_tasks = client.get(f"/projects/{project_id}/tasks")
    assert refreshed_tasks.status_code == 200
    assert len(refreshed_tasks.json()) == 7

    refreshed_runs = client.get(f"/projects/{project_id}/runs")
    assert refreshed_runs.status_code == 200
    assert len(refreshed_runs.json()) == 7
    assert {run["status"] for run in refreshed_runs.json()} == {"provisioned"}

    refreshed_messages = client.get(f"/projects/{project_id}/messages")
    assert refreshed_messages.status_code == 200
    assert len(refreshed_messages.json()) >= 5

    refreshed_decisions = client.get(f"/projects/{project_id}/approval-decisions")
    assert refreshed_decisions.status_code == 200
    assert len(refreshed_decisions.json()) >= len(initial_decisions.json())

    refreshed_events = client.get(f"/projects/{project_id}/events")
    assert refreshed_events.status_code == 200
    refreshed_event_types = {event["event_type"] for event in refreshed_events.json()}
    assert "task_graph_replaced" in refreshed_event_types

    agents = client.get(f"/projects/{project_id}/agents")
    assert agents.status_code == 200
    assert len(agents.json()) == 8

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["auth_mode"] in {"api_key", "disabled"}
    assert health.json()["director_heartbeat"]["max_dispatch_per_tick"] >= 1
    assert "database_url" not in health.json()
    assert "redis_url" not in health.json()


def test_stream_endpoint_does_not_keep_request_scoped_db_session(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_stream.db"
    runtime_root = tmp_path / "runtime"
    build_test_client(monkeypatch, database_path, runtime_root)

    import app.routers.projects as projects_router

    signature = inspect.signature(projects_router.stream_project_events)
    assert "db" not in signature.parameters


def test_director_auto_starts_queue_after_goal(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_director_auto.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(
        monkeypatch,
        database_path,
        runtime_root,
        director_auto_run_enabled=True,
    )

    project = client.post(
        "/projects",
        json={"name": "Director Auto Queue", "description": "auto run test"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a project plan and execute it end-to-end automatically"},
    )
    assert goal.status_code == 200
    assert "автоматически запустил задачу" in goal.json()["summary"].lower()

    run_started = False
    for _ in range(60):
        runs = client.get(f"/projects/{project_id}/runs")
        assert runs.status_code == 200
        statuses = {run["status"] for run in runs.json()}
        if statuses.intersection({"running", "review", "done", "changes_requested", "failed"}):
            run_started = True
            break
        time.sleep(0.1)
    assert run_started is True

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    assert any(event["event_type"] == "director_auto_dispatched" for event in events.json())
    assert any(event["event_type"] == "director_progress_update" for event in events.json())

    messages = client.get(f"/projects/{project_id}/messages")
    assert messages.status_code == 200
    assert any(
        message["role"] == "director" and "Прогресс:" in message["content"]
        for message in messages.json()
    )


def test_director_heartbeat_continues_ready_queue_without_manual_click(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_director_heartbeat.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(
        monkeypatch,
        database_path,
        runtime_root,
        director_auto_run_enabled=False,
        director_heartbeat_enabled=False,
    )

    project = client.post(
        "/projects",
        json={"name": "Director Heartbeat Queue", "description": "heartbeat test"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Prepare a local AI office rollout plan"},
    )
    assert goal.status_code == 200

    tasks_before = client.get(f"/projects/{project_id}/tasks")
    assert tasks_before.status_code == 200
    assert any(task["status"] == "ready" for task in tasks_before.json())

    import app.codex_worker as codex_worker
    import app.director_heartbeat as director_heartbeat

    monkeypatch.setattr(
        codex_worker,
        "settings",
        replace(codex_worker.settings, director_auto_run_enabled=True),
    )
    monkeypatch.setattr(
        director_heartbeat,
        "settings",
        replace(director_heartbeat.settings, director_auto_run_enabled=True),
    )

    dispatched_count = director_heartbeat.tick_director_queue_once(trigger="test_heartbeat")
    assert dispatched_count >= 1

    run_started = False
    for _ in range(60):
        runs = client.get(f"/projects/{project_id}/runs")
        assert runs.status_code == 200
        statuses = {run["status"] for run in runs.json()}
        if statuses.intersection({"running", "review", "done", "changes_requested", "failed"}):
            run_started = True
            break
        time.sleep(0.1)
    assert run_started is True

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    assert any(
        event["event_type"] == "director_auto_dispatched"
        and event.get("payload", {}).get("trigger") == "test_heartbeat"
        for event in events.json()
    )


def test_director_heartbeat_respects_dispatch_limit_per_tick(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_dispatch_limit.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(
        monkeypatch,
        database_path,
        runtime_root,
        director_auto_run_enabled=False,
        director_heartbeat_enabled=False,
    )

    project_one = client.post(
        "/projects",
        json={"name": "Heartbeat Limit One", "description": "dispatch limit test"},
    )
    assert project_one.status_code == 201
    project_one_id = project_one.json()["id"]
    goal_one = client.post(
        f"/projects/{project_one_id}/goal",
        json={"goal_text": "Prepare a local AI office rollout plan A"},
    )
    assert goal_one.status_code == 200

    project_two = client.post(
        "/projects",
        json={"name": "Heartbeat Limit Two", "description": "dispatch limit test"},
    )
    assert project_two.status_code == 201
    project_two_id = project_two.json()["id"]
    goal_two = client.post(
        f"/projects/{project_two_id}/goal",
        json={"goal_text": "Prepare a local AI office rollout plan B"},
    )
    assert goal_two.status_code == 200

    import app.codex_worker as codex_worker
    import app.director_heartbeat as director_heartbeat

    monkeypatch.setattr(
        codex_worker,
        "settings",
        replace(codex_worker.settings, director_auto_run_enabled=True),
    )
    monkeypatch.setattr(
        director_heartbeat,
        "settings",
        replace(
            director_heartbeat.settings,
            director_auto_run_enabled=True,
            director_heartbeat_max_dispatch_per_tick=1,
        ),
    )

    dispatched_count = director_heartbeat.tick_director_queue_once(
        trigger="test_dispatch_limit"
    )
    assert dispatched_count == 1

    events_one = client.get(f"/projects/{project_one_id}/events")
    assert events_one.status_code == 200
    events_two = client.get(f"/projects/{project_two_id}/events")
    assert events_two.status_code == 200
    project_one_dispatched = any(
        event["event_type"] == "director_auto_dispatched"
        and event.get("payload", {}).get("trigger") == "test_dispatch_limit"
        for event in events_one.json()
    )
    project_two_dispatched = any(
        event["event_type"] == "director_auto_dispatched"
        and event.get("payload", {}).get("trigger") == "test_dispatch_limit"
        for event in events_two.json()
    )
    assert int(project_one_dispatched) + int(project_two_dispatched) == 1


def test_director_heartbeat_recovers_stale_running_run(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_stale_recovery.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(
        monkeypatch,
        database_path,
        runtime_root,
        director_auto_run_enabled=False,
        director_heartbeat_enabled=False,
    )

    project = client.post(
        "/projects",
        json={"name": "Stale Recovery Project", "description": "recover stale run"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    start_action = client.post(
        f"/projects/{project_id}/tasks/{ready_task['id']}/actions",
        json={"action": "start", "reason": "seed stale execution"},
    )
    assert start_action.status_code == 200

    running_run = next(
        run
        for run in client.get(f"/projects/{project_id}/runs").json()
        if run["task_id"] == ready_task["id"] and run["status"] == "running"
    )
    stale_run_id = running_run["id"]

    from app.db import SessionLocal
    from app.director_heartbeat import tick_director_queue_once
    from app.models import TaskRun, utc_now

    session = SessionLocal()
    try:
        stale_run = session.get(TaskRun, stale_run_id)
        assert stale_run is not None
        stale_run.started_at = utc_now() - timedelta(seconds=1200)
        stale_run.stdout = "Codex execution queued."
        session.commit()
    finally:
        session.close()

    import app.codex_worker as codex_worker
    import app.director_heartbeat as director_heartbeat

    monkeypatch.setattr(
        codex_worker,
        "settings",
        replace(codex_worker.settings, director_auto_run_enabled=True),
    )
    monkeypatch.setattr(
        director_heartbeat,
        "settings",
        replace(director_heartbeat.settings, director_auto_run_enabled=True),
    )

    dispatched_count = tick_director_queue_once(trigger="test_stale_recovery")
    assert dispatched_count >= 1

    stale_recovered = False
    restarted = False
    for _ in range(80):
        runs = client.get(f"/projects/{project_id}/runs")
        assert runs.status_code == 200
        run_payload = runs.json()
        stale = next((run for run in run_payload if run["id"] == stale_run_id), None)
        if stale is not None and stale["status"] == "timed_out":
            stale_recovered = True
        restarted = any(
            run["task_id"] == ready_task["id"]
            and run["id"] != stale_run_id
            and run["status"] in {"running", "review", "done", "changes_requested"}
            for run in run_payload
        )
        if stale_recovered and restarted:
            break
        time.sleep(0.05)

    assert stale_recovered is True
    assert restarted is True

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    assert any(event["event_type"] == "director_stale_run_recovered" for event in events.json())


def test_director_stale_recovery_does_not_auto_retry_very_old_run(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_stale_old.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(
        monkeypatch,
        database_path,
        runtime_root,
        director_auto_run_enabled=False,
        director_heartbeat_enabled=False,
    )

    project = client.post(
        "/projects",
        json={"name": "Very Old Stale Project", "description": "stale no auto retry"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    start_action = client.post(
        f"/projects/{project_id}/tasks/{ready_task['id']}/actions",
        json={"action": "start", "reason": "seed very old stale execution"},
    )
    assert start_action.status_code == 200

    stale_run = next(
        run
        for run in client.get(f"/projects/{project_id}/runs").json()
        if run["task_id"] == ready_task["id"] and run["status"] == "running"
    )
    stale_run_id = stale_run["id"]

    from app.db import SessionLocal
    from app.director_heartbeat import tick_director_queue_once
    from app.models import TaskRun, utc_now

    session = SessionLocal()
    try:
        stale_run_record = session.get(TaskRun, stale_run_id)
        assert stale_run_record is not None
        stale_run_record.started_at = utc_now() - timedelta(seconds=6000)
        stale_run_record.stdout = "Codex execution queued."
        session.commit()
    finally:
        session.close()

    import app.codex_worker as codex_worker
    import app.director_heartbeat as director_heartbeat

    monkeypatch.setattr(
        codex_worker,
        "settings",
        replace(codex_worker.settings, director_auto_run_enabled=True),
    )
    monkeypatch.setattr(
        director_heartbeat,
        "settings",
        replace(director_heartbeat.settings, director_auto_run_enabled=True),
    )

    tick_director_queue_once(trigger="test_stale_old_recovery")

    stale_recovered = False
    for _ in range(80):
        runs = client.get(f"/projects/{project_id}/runs")
        assert runs.status_code == 200
        stale = next((run for run in runs.json() if run["id"] == stale_run_id), None)
        if stale is not None and stale["status"] == "timed_out":
            stale_recovered = True
            break
        time.sleep(0.05)
    assert stale_recovered is True

    tasks = client.get(f"/projects/{project_id}/tasks")
    assert tasks.status_code == 200
    task_by_id = {task["id"]: task for task in tasks.json()}
    assert task_by_id[ready_task["id"]]["status"] == "failed"

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    stale_events = [
        event for event in events.json() if event["event_type"] == "director_stale_run_recovered"
    ]
    assert len(stale_events) >= 1
    assert stale_events[0]["payload"]["auto_retry_allowed"] is False
    assert stale_events[0]["payload"]["auto_reset"] is False


def test_director_startup_recovery_recovers_orphaned_running_run(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_startup_recovery.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(
        monkeypatch,
        database_path,
        runtime_root,
        director_auto_run_enabled=False,
        director_heartbeat_enabled=False,
    )

    project = client.post(
        "/projects",
        json={"name": "Startup Recovery Project", "description": "orphaned run recovery"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    start_action = client.post(
        f"/projects/{project_id}/tasks/{ready_task['id']}/actions",
        json={"action": "start", "reason": "seed orphaned running execution"},
    )
    assert start_action.status_code == 200

    stale_run = next(
        run
        for run in client.get(f"/projects/{project_id}/runs").json()
        if run["task_id"] == ready_task["id"] and run["status"] == "running"
    )
    stale_run_id = stale_run["id"]

    import app.codex_worker as codex_worker
    import app.director_heartbeat as director_heartbeat

    monkeypatch.setattr(
        codex_worker,
        "settings",
        replace(codex_worker.settings, director_auto_run_enabled=True),
    )
    monkeypatch.setattr(
        director_heartbeat,
        "settings",
        replace(director_heartbeat.settings, director_auto_run_enabled=True),
    )

    dispatched_count = director_heartbeat.tick_director_queue_once(
        trigger="test_startup_recovery",
        recover_immediately=True,
    )
    assert dispatched_count >= 1

    stale_recovered = False
    restarted = False
    for _ in range(80):
        runs = client.get(f"/projects/{project_id}/runs")
        assert runs.status_code == 200
        run_payload = runs.json()
        stale = next((run for run in run_payload if run["id"] == stale_run_id), None)
        if stale is not None and stale["status"] == "timed_out":
            stale_recovered = True
        restarted = any(
            run["task_id"] == ready_task["id"]
            and run["id"] != stale_run_id
            and run["status"] in {"running", "review", "done", "changes_requested"}
            for run in run_payload
        )
        if stale_recovered and restarted:
            break
        time.sleep(0.05)

    assert stale_recovered is True
    assert restarted is True


def test_reviewer_requests_rework_for_empty_result(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_review_fail.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)
    import app.codex_worker as codex_worker

    def empty_mock_worker(session, project, task, task_run, workspace, environment):
        return ""

    monkeypatch.setattr(codex_worker, "_run_mock_worker", empty_mock_worker)

    project = client.post(
        "/projects",
        json={"name": "Review Fail Project", "description": "review rework test"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200

    tasks = client.get(f"/projects/{project_id}/tasks")
    ready_task = next(task for task in tasks.json() if task["status"] == "ready")

    start_task = client.post(f"/projects/{project_id}/tasks/{ready_task['id']}/run")
    assert start_task.status_code == 200
    execution_run_id = start_task.json()["run"]["id"]

    for _ in range(60):
        task_log = client.get(f"/task-runs/{execution_run_id}/logs")
        assert task_log.status_code == 200
        if task_log.json()["status"] == "changes_requested":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Reviewer did not return the task for rework in time")

    final_log = client.get(f"/task-runs/{execution_run_id}/logs")
    assert final_log.status_code == 200
    assert final_log.json()["status"] == "changes_requested"
    assert "Reviewer requested changes" in final_log.json()["stdout"]

    updated_tasks = client.get(f"/projects/{project_id}/tasks")
    assert updated_tasks.status_code == 200
    task_by_id = {task["id"]: task for task in updated_tasks.json()}
    assert task_by_id[ready_task["id"]]["status"] == "ready"

    runtime = client.get(f"/projects/{project_id}/tasks/{ready_task['id']}/runtime")
    assert runtime.status_code == 200
    assert runtime.json()["workspace"]["state"] == "changes_requested"

    reviews = client.get(f"/projects/{project_id}/tasks/{ready_task['id']}/reviews")
    assert reviews.status_code == 200
    assert len(reviews.json()) == 1
    assert reviews.json()[0]["recommendation"] == "changes_requested"
    assert reviews.json()[0]["severity_counts"]["critical"] >= 1

    host_access_policy_check = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.host_access",
            "task_id": ready_task["id"],
            "task_run_id": execution_run_id,
            "requested_by": "director",
            "metadata": {"target_path": "/Users/dmitrijfabarisov/.ssh"},
        },
    )
    assert host_access_policy_check.status_code == 200
    assert host_access_policy_check.json()["allowed"] is False
    assert host_access_policy_check.json()["action_intent"]["status"] == "pending_approval"
    approval_request_id = host_access_policy_check.json()["approval_request"]["id"]

    reject_approval = client.post(
        f"/projects/{project_id}/approvals/{approval_request_id}/resolve",
        json={
            "outcome": "rejected",
            "actor": "human",
            "summary": "Human rejected host access for this simulation.",
        },
        headers={"X-API-Key": "test-human-key"},
    )
    assert reject_approval.status_code == 200
    assert reject_approval.json()["approval_request"]["status"] == "rejected"
    assert reject_approval.json()["approval_decision"]["outcome"] == "rejected"
    assert reject_approval.json()["action_intent"]["status"] == "rejected"

    host_access_policy_retry = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.host_access",
            "task_id": ready_task["id"],
            "task_run_id": execution_run_id,
            "requested_by": "director",
            "metadata": {"target_path": "/Users/dmitrijfabarisov/.ssh"},
        },
    )
    assert host_access_policy_retry.status_code == 200
    assert host_access_policy_retry.json()["allowed"] is False
    assert host_access_policy_retry.json()["approval_decision"]["outcome"] == "rejected"
    assert host_access_policy_retry.json()["approval_request"]["status"] == "rejected"
    assert host_access_policy_retry.json()["action_intent"]["status"] == "rejected"

    action_intents = client.get(f"/projects/{project_id}/action-intents")
    assert action_intents.status_code == 200
    assert len(action_intents.json()) == 1
    assert action_intents.json()[0]["status"] == "rejected"

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert "task_review_completed" in event_types
    assert "task_review_changes_requested" in event_types
    assert "approval_rejected" in event_types
    assert "action_intent_created" in event_types
    assert "action_intent_rejected" in event_types


def test_runtime_write_workspace_allows_host_mounted_task_workspace(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_host_path_policy.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "Host Path Policy Project", "description": "policy path classification"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    policy_check = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.write_workspace",
            "task_id": ready_task["id"],
            "requested_by": "director",
            "metadata": {
                "target_path": "/Users/dmitrijfabarisov/Projects/AI Office/runtime/projects/demo/tasks/demo/workspace/README.md",
                "workspace_path": "/Users/dmitrijfabarisov/Projects/AI Office/runtime/projects/demo/tasks/demo/workspace",
            },
        },
    )
    assert policy_check.status_code == 200
    assert policy_check.json()["allowed"] is True
    assert policy_check.json()["approval_decision"]["outcome"] == "approved"
    assert policy_check.json()["approval_request"] is None


def test_cancel_running_codex_execution(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_cancel.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root, timeout_seconds=60)
    import app.codex_worker as codex_worker

    def slow_mock_worker(session, project, task, task_run, workspace, environment):
        time.sleep(2.0)
        return "# Slow worker result\n\nThis should not be committed after cancellation."

    monkeypatch.setattr(codex_worker, "_run_mock_worker", slow_mock_worker)

    project = client.post(
        "/projects",
        json={"name": "Cancel Project", "description": "cancel running task"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    run_response = client.post(f"/projects/{project_id}/tasks/{ready_task['id']}/run")
    assert run_response.status_code == 200
    run_id = run_response.json()["run"]["id"]

    cancel_response = client.post(
        f"/task-runs/{run_id}/cancel",
        json={"actor": "human", "reason": "Manual cancellation for stabilization test."},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["run"]["status"] == "cancelled"

    for _ in range(80):
        task_log = client.get(f"/task-runs/{run_id}/logs")
        assert task_log.status_code == 200
        if task_log.json()["status"] == "cancelled":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Task run was not marked as cancelled in time")

    tasks = client.get(f"/projects/{project_id}/tasks")
    assert tasks.status_code == 200
    task_by_id = {task["id"]: task for task in tasks.json()}
    assert task_by_id[ready_task["id"]]["status"] == "failed"

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert "task_execution_cancelled" in event_types


def test_watchdog_times_out_hanging_run(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_timeout.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(
        monkeypatch,
        database_path,
        runtime_root,
        timeout_seconds=1,
    )
    import app.codex_worker as codex_worker

    def hanging_mock_worker(session, project, task, task_run, workspace, environment):
        time.sleep(3.0)
        return "# Hanging worker result\n\nLate completion."

    monkeypatch.setattr(codex_worker, "_run_mock_worker", hanging_mock_worker)

    project = client.post(
        "/projects",
        json={"name": "Timeout Project", "description": "watchdog timeout"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    run_response = client.post(f"/projects/{project_id}/tasks/{ready_task['id']}/run")
    assert run_response.status_code == 200
    run_id = run_response.json()["run"]["id"]

    for _ in range(120):
        task_log = client.get(f"/task-runs/{run_id}/logs")
        assert task_log.status_code == 200
        if task_log.json()["status"] == "timed_out":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Task run was not timed out by watchdog")

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert "task_execution_timed_out" in event_types


def test_preflight_containerized_api_does_not_block_host_codex_home(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_CONTAINER_DRIVER", "docker")
    monkeypatch.setenv("CODEX_WORKER_MODE", "real")
    missing_codex_home = tmp_path / "missing_codex_home"
    monkeypatch.setenv("TASK_CONTAINER_CODEX_HOME_HOST_PATH", str(missing_codex_home))
    monkeypatch.setenv("TASK_CONTAINER_IMAGE", "ai-office-task-runner:latest")
    monkeypatch.setenv("CODEX_EXECUTION_TIMEOUT_SECONDS", "60")

    for module_name in ["app.config", "app.task_container", "app.preflight"]:
        sys.modules.pop(module_name, None)

    from app import preflight
    from app.models import TaskEnvironment, TaskWorkspace

    class FakeImages:
        def get(self, _image_name: str):
            return object()

    class FakeDockerClient:
        def __init__(self) -> None:
            self.images = FakeImages()

        def ping(self) -> bool:
            return True

        def close(self) -> None:
            return None

    class FakeDockerModule:
        @staticmethod
        def from_env(timeout: int = 20) -> FakeDockerClient:
            return FakeDockerClient()

    runtime_root = tmp_path / "runtime"
    workspace_dir = runtime_root / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    workspace = TaskWorkspace(
        project_id="project",
        task_id="task",
        root_path=str(runtime_root),
        workspace_path=str(workspace_dir),
        source_root_path=None,
        workspace_mode="snapshot-copy",
        sync_status="seeded",
        sandbox_mode="workspace-write",
        state="provisioned",
        context_file_path=None,
    )
    environment = TaskEnvironment(
        project_id="project",
        task_id="task",
        name="task-environment",
        runtime_kind="task-container",
        runtime_status="container-ready",
        base_image="ai-office-task-runner:latest",
        container_name="task-container",
        container_id="container-id",
        container_workdir="/task",
        source_mount_mode="read-only",
        workspace_mount_mode="read-write",
        network_mode="bridge",
        env_vars={},
        mounts=[],
    )

    monkeypatch.setattr(preflight, "docker", FakeDockerModule)
    monkeypatch.setattr(preflight, "container_runtime_enabled", lambda: True)
    monkeypatch.setattr(preflight, "_api_runtime_is_containerized", lambda: True)
    monkeypatch.setattr(preflight, "_is_writable_directory", lambda _path: True)

    result = preflight.evaluate_task_preflight(workspace, environment)
    credential_check = next(check for check in result.checks if check.key == "codex.credentials")

    assert credential_check.status in {"warn", "pass"}
    assert credential_check.status != "fail"
    assert credential_check.blocking is False
    assert result.ready is True


def test_action_intent_retry_and_recovery(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_retry.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "Retry Project", "description": "intent retry flow"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    host_access_policy_check = client.post(
        f"/projects/{project_id}/policy-checks",
        json={
            "action_key": "runtime.host_access",
            "task_id": ready_task["id"],
            "requested_by": "director",
            "metadata": {
                "target_path": "/Users/dmitrijfabarisov/.ssh",
                "simulate_failures_remaining": 1,
            },
        },
    )
    assert host_access_policy_check.status_code == 200
    approval_request_id = host_access_policy_check.json()["approval_request"]["id"]

    resolve_approval = client.post(
        f"/projects/{project_id}/approvals/{approval_request_id}/resolve",
        json={
            "outcome": "approved",
            "actor": "human",
            "summary": "Approve and let the dispatcher recover after one failure.",
        },
        headers={"X-API-Key": "test-human-key"},
    )
    assert resolve_approval.status_code == 200
    assert resolve_approval.json()["action_intent"]["status"] == "retry_scheduled"
    assert resolve_approval.json()["action_intent"]["attempt_count"] == 1
    assert resolve_approval.json()["action_intent"]["next_retry_at"] is not None
    assert resolve_approval.json()["action_intent"]["last_error"] is not None

    action_intent_id = resolve_approval.json()["action_intent"]["id"]
    retry_intent = client.post(
        f"/projects/{project_id}/action-intents/{action_intent_id}/retry",
        json={"actor": "director", "ignore_backoff": True},
    )
    assert retry_intent.status_code == 200
    assert retry_intent.json()["action_intent"]["status"] == "completed"
    assert retry_intent.json()["action_intent"]["attempt_count"] == 2
    assert retry_intent.json()["action_intent"]["last_error"] is None
    assert retry_intent.json()["action_intent"]["dispatch_task_run_id"] is not None

    runs = client.get(f"/projects/{project_id}/runs")
    assert runs.status_code == 200
    intent_runs = [
        run
        for run in runs.json()
        if run["environment_name"] == "intent:runtime.host_access"
    ]
    assert len(intent_runs) == 2
    assert {run["status"] for run in intent_runs} == {"failed", "done"}

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert "action_intent_retry_scheduled" in event_types
    assert "action_intent_dispatch_started" in event_types
    assert "action_intent_completed" in event_types


def test_codex_worker_requests_runtime_action(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_office_worker_request.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)
    import app.codex_worker as codex_worker

    def action_request_mock_worker(session, project, task, task_run, workspace, environment):
        return (
            "# Worker Result\n\n"
            "Prepared the main deliverable.\n"
            'ACTION_REQUEST: runtime.host_access {"target_path": "/Users/dmitrijfabarisov/.ssh"}\n'
        )

    monkeypatch.setattr(codex_worker, "_run_mock_worker", action_request_mock_worker)

    project = client.post(
        "/projects",
        json={"name": "Worker Request Project", "description": "worker action request"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    goal = client.post(
        f"/projects/{project_id}/goal",
        json={"goal_text": "Create a local virtual office for AI agents"},
    )
    assert goal.status_code == 200
    ready_task = next(task for task in goal.json()["created_tasks"] if task["status"] == "ready")

    start_task = client.post(f"/projects/{project_id}/tasks/{ready_task['id']}/run")
    assert start_task.status_code == 200
    execution_run_id = start_task.json()["run"]["id"]

    for _ in range(60):
        task_log = client.get(f"/task-runs/{execution_run_id}/logs")
        assert task_log.status_code == 200
        if task_log.json()["status"] == "done":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Codex mock execution did not complete in time")

    final_log = client.get(f"/task-runs/{execution_run_id}/logs")
    assert final_log.status_code == 200
    assert "Worker requested runtime.host_access" in final_log.json()["stdout"]
    assert "policy rejected for role ProductManager" in final_log.json()["stdout"]

    approvals = client.get(f"/projects/{project_id}/approvals")
    assert approvals.status_code == 200
    assert len(approvals.json()) == 0

    action_intents = client.get(f"/projects/{project_id}/action-intents")
    assert action_intents.status_code == 200
    assert len(action_intents.json()) == 0

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert "worker_action_requested" in event_types
    assert "approval_requested" not in event_types
    assert "action_intent_created" not in event_types


def test_crm_bridge_preview_and_send_flow(tmp_path, monkeypatch):
    database_path = tmp_path / "crm_bridge_test.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "CRM Bridge Project", "description": "CRM preview/send smoke test"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={
            "student_id": "student-1007",
            "amo_entity_type": "contact",
            "amo_entity_id": "12345",
            "field_mapping": {
                "name": "full_name",
                "phone": "phone",
                "email": "email",
                "pipeline_stage": "stage",
            },
        },
    )
    assert preview_response.status_code == 201
    preview_payload = preview_response.json()
    assert preview_payload["status"] == "previewed"
    assert preview_payload["source_system"] == "tallanto"
    assert preview_payload["source_student_id"] == "student-1007"
    assert "name" in preview_payload["amo_field_payload"]
    assert preview_payload["analysis_summary"]
    assert preview_payload["source_payload"]["email"] != "student1007@example.edu"
    assert "*" in preview_payload["source_payload"]["email"]
    assert preview_payload["canonical_payload"]["full_name"] != "Ученик 1007"
    assert "*" in preview_payload["canonical_payload"]["full_name"]

    preview_id = preview_payload["id"]

    list_previews = client.get(f"/projects/{project_id}/crm/previews")
    assert list_previews.status_code == 200
    assert len(list_previews.json()) == 1
    assert list_previews.json()[0]["id"] == preview_id

    get_preview = client.get(f"/projects/{project_id}/crm/previews/{preview_id}")
    assert get_preview.status_code == 200
    assert get_preview.json()["id"] == preview_id

    send_response = client.post(
        f"/projects/{project_id}/crm/previews/{preview_id}/send",
        json={
            "selected_fields": ["name", "phone"],
            "field_overrides": {
                "phone": "+79990001122",
            },
        },
    )
    assert send_response.status_code == 200
    send_payload = send_response.json()
    assert send_payload["preview"]["id"] == preview_id
    assert send_payload["preview"]["status"] == "sent"
    assert send_payload["preview"]["send_result"]["mode"] == "mock"
    assert send_payload["preview"]["send_result"]["updated_fields"]["phone"] != "+79990001122"
    assert send_payload["preview"]["send_result"]["updated_fields"]["phone"].endswith("22")
    assert "Отправка в AMO выполнена" in send_payload["summary"]

    artifacts = client.get(f"/projects/{project_id}/artifacts")
    assert artifacts.status_code == 200
    artifact_kinds = {artifact["kind"] for artifact in artifacts.json()}
    assert "crm_preview" in artifact_kinds
    assert "crm_sync_result" in artifact_kinds
    crm_preview_artifact = next(
        artifact for artifact in artifacts.json() if artifact["kind"] == "crm_preview"
    )
    assert "student1007@example.edu" not in crm_preview_artifact["content"]

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = {event["event_type"] for event in events.json()}
    assert "crm_preview_created" in event_types
    assert "crm_send_completed" in event_types


def test_crm_send_empty_selected_fields_does_not_send_all(tmp_path, monkeypatch):
    database_path = tmp_path / "crm_bridge_empty_fields.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "CRM Empty Fields", "description": "empty selected fields"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={"student_id": "student-1001", "amo_entity_type": "contact"},
    )
    assert preview_response.status_code == 201
    preview_id = preview_response.json()["id"]

    send_response = client.post(
        f"/projects/{project_id}/crm/previews/{preview_id}/send",
        json={"selected_fields": []},
    )
    assert send_response.status_code == 200
    send_payload = send_response.json()
    assert send_payload["preview"]["status"] == "failed"
    assert send_payload["preview"]["send_result"]["result"] == "failed"
    assert "нет выбранных полей" in send_payload["summary"].lower()


def test_crm_send_duplicate_preview_is_blocked(tmp_path, monkeypatch):
    database_path = tmp_path / "crm_bridge_duplicate_send.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "CRM Duplicate Send", "description": "duplicate send guard"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={"student_id": "student-1201", "amo_entity_type": "contact"},
    )
    assert preview_response.status_code == 201
    preview_id = preview_response.json()["id"]

    first_send = client.post(
        f"/projects/{project_id}/crm/previews/{preview_id}/send",
        json={"selected_fields": ["name"]},
    )
    assert first_send.status_code == 200
    assert first_send.json()["preview"]["status"] == "sent"

    second_send = client.post(
        f"/projects/{project_id}/crm/previews/{preview_id}/send",
        json={"selected_fields": ["name"]},
    )
    assert second_send.status_code == 409
    assert "already sent" in second_send.json()["detail"].lower()


def test_crm_preview_http_mode_missing_config_returns_service_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_TALLANTO_MODE", "http")
    monkeypatch.delenv("CRM_TALLANTO_BASE_URL", raising=False)
    monkeypatch.delenv("CRM_TALLANTO_API_TOKEN", raising=False)

    database_path = tmp_path / "crm_bridge_http_missing.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "CRM HTTP Config", "description": "missing upstream config"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={"student_id": "student-1301", "amo_entity_type": "contact"},
    )
    assert preview_response.status_code == 503
    assert "CRM_TALLANTO_BASE_URL" in preview_response.json()["detail"]


def test_crm_preview_http_mode_reads_tallanto_contact_by_email(tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_TALLANTO_MODE", "http")
    monkeypatch.setenv("CRM_TALLANTO_BASE_URL", "http://kmipt.tallanto.com")
    monkeypatch.setenv("CRM_TALLANTO_API_TOKEN", "tallanto-token")
    monkeypatch.setenv("CRM_TALLANTO_STUDENT_PATH", "/service/api/rest.php")

    database_path = tmp_path / "crm_bridge_http_email.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    import app.crm_bridge as crm_bridge

    captured_requests = []

    def fake_urlopen(request, timeout=0):
        captured_requests.append(
            {
                "url": request.full_url,
                "headers": {key.lower(): value for key, value in request.header_items()},
                "data": request.data,
            }
        )
        return _JsonResponse(
            {
                "id": "contact-2001",
                "first_name": "Julia",
                "last_name": "Ivanova",
                "email1": "julia@example.com",
                "phone_mobile": "+79169164148",
                "description": "Interested in olympiad preparation",
                "amo_id": "75320451",
            }
        )

    monkeypatch.setattr(crm_bridge.url_request, "urlopen", fake_urlopen)

    project = client.post(
        "/projects",
        json={"name": "CRM Tallanto Email", "description": "Tallanto email lookup"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={
            "student_id": "julia@example.com",
            "lookup_mode": "email",
            "amo_entity_type": "contact",
        },
    )
    assert preview_response.status_code == 201
    preview_payload = preview_response.json()
    assert preview_payload["source_student_id"] == "contact-2001"
    assert preview_payload["source_payload"]["email1"] != "julia@example.com"
    assert "*" in preview_payload["source_payload"]["email1"]
    assert preview_payload["canonical_payload"]["full_name"] != "Julia Ivanova"
    assert "*" in preview_payload["canonical_payload"]["full_name"]
    assert preview_payload["analysis_summary"]
    assert any("method=get_entry_by_fields" in item["url"] for item in captured_requests)
    assert any("fields_values%5Bemail1%5D=julia%40example.com" in item["url"] for item in captured_requests)
    assert captured_requests[0]["headers"]["x-auth-token"] == "tallanto-token"


def test_crm_preview_http_mode_normalizes_phone_lookup_for_tallanto(tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_TALLANTO_MODE", "http")
    monkeypatch.setenv("CRM_TALLANTO_BASE_URL", "http://kmipt.tallanto.com")
    monkeypatch.setenv("CRM_TALLANTO_API_TOKEN", "tallanto-token")
    monkeypatch.setenv("CRM_TALLANTO_STUDENT_PATH", "/service/api/rest.php")

    database_path = tmp_path / "crm_bridge_http_phone.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    import app.crm_bridge as crm_bridge

    attempted_urls = []

    def fake_urlopen(request, timeout=0):
        attempted_urls.append(request.full_url)
        request_body = (
            request.data.decode("utf-8", errors="ignore")
            if getattr(request, "data", None)
            else ""
        )
        if "%2B79169164148" in request.full_url or "%2B79169164148" in request_body:
            return _JsonResponse(
                {
                    "id": "contact-3001",
                    "first_name": "Julia",
                    "email1": "julia@example.com",
                    "phone_mobile": "+79169164148",
                }
            )
        return _JsonResponse(
            {"name": "Not find by id", "number": 1502, "description": "Entry does not exist"}
        )

    monkeypatch.setattr(crm_bridge.url_request, "urlopen", fake_urlopen)

    project = client.post(
        "/projects",
        json={"name": "CRM Tallanto Phone", "description": "Tallanto phone normalization"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={
            "student_id": "8 (916) 916-41-48",
            "lookup_mode": "phone",
            "amo_entity_type": "contact",
        },
    )
    assert preview_response.status_code == 201
    preview_payload = preview_response.json()
    assert preview_payload["source_student_id"] == "contact-3001"
    assert any("%2B79169164148" in url for url in attempted_urls)


def test_crm_preview_http_mode_handles_tallanto_400_not_found_during_phone_lookup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CRM_TALLANTO_MODE", "http")
    monkeypatch.setenv("CRM_TALLANTO_BASE_URL", "http://kmipt.tallanto.com")
    monkeypatch.setenv("CRM_TALLANTO_API_TOKEN", "tallanto-token")
    monkeypatch.setenv("CRM_TALLANTO_STUDENT_PATH", "/service/api/rest.php")

    database_path = tmp_path / "crm_bridge_http_phone_400.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    import app.crm_bridge as crm_bridge

    attempted_urls = []

    def fake_urlopen(request, timeout=0):
        attempted_urls.append(request.full_url)
        if "%2B79169164148" in request.full_url:
            return _JsonResponse(
                {
                    "id": "contact-3002",
                    "first_name": "Julia",
                    "email1": "julia@example.com",
                    "phone_mobile": "+79169164148",
                }
            )
        payload = json.dumps(
            {"name": "Not find by id", "number": 1502, "description": "Entry does not exist"}
        ).encode("utf-8")
        raise url_error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr(crm_bridge.url_request, "urlopen", fake_urlopen)

    project = client.post(
        "/projects",
        json={"name": "CRM Tallanto Phone 400", "description": "Tallanto phone normalization"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={
            "student_id": "8 (916) 916-41-48",
            "lookup_mode": "phone",
            "amo_entity_type": "contact",
        },
    )
    assert preview_response.status_code == 201
    preview_payload = preview_response.json()
    assert preview_payload["source_student_id"] == "contact-3002"
    assert any("%2B79169164148" in url for url in attempted_urls)


def test_crm_amo_http_mode_uses_review_queue_before_controlled_write(tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_AMO_MODE", "http")
    monkeypatch.setenv("CRM_AMO_BASE_URL", "https://amo.example.test")
    monkeypatch.setenv("CRM_AMO_API_TOKEN", "token")

    database_path = tmp_path / "crm_bridge_amo_human_approval.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    import app.crm_bridge as crm_bridge

    requests = []

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        body = request.data.decode("utf-8", errors="ignore") if request.data else ""
        requests.append(
            {
                "url": url,
                "method": request.get_method(),
                "data": body,
            }
        )
        if "/api/v4/contacts/custom_fields" in url:
            return _JsonResponse(
                {
                    "_embedded": {
                        "custom_fields": [
                            {"id": 101, "name": "Id Tallanto", "type": "text"},
                            {"id": 102, "name": "Авто история общения", "type": "text"},
                            {"id": 103, "name": "AI-приоритет", "type": "text"},
                            {"id": 104, "name": "AI-рекомендованный следующий шаг", "type": "text"},
                            {"id": 105, "name": "Последняя AI-сводка", "type": "text"},
                            {"id": 106, "name": "Филиал Tallanto", "type": "text"},
                            {"id": 107, "name": "Баланс Tallanto", "type": "numeric"},
                            {"id": 108, "name": "Пополнено Tallanto", "type": "numeric"},
                            {"id": 109, "name": "Списано Tallanto", "type": "numeric"},
                            {"id": 110, "name": "Статус матчинга", "type": "text"},
                        ]
                    }
                }
            )
        return _JsonResponse({"result": "ok"})

    monkeypatch.setattr(crm_bridge.url_request, "urlopen", fake_urlopen)

    project = client.post(
        "/projects",
        json={"name": "CRM AMO HTTP Approval", "description": "human approval check"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={"student_id": "student-1401", "amo_entity_type": "contact"},
    )
    assert preview_response.status_code == 201
    preview_id = preview_response.json()["id"]
    assert preview_response.json()["review_status"] == "pending"
    assert "Id Tallanto" in preview_response.json()["amo_field_payload"]
    assert "phone" not in preview_response.json()["amo_field_payload"]

    send_response = client.post(
        f"/projects/{project_id}/crm/previews/{preview_id}/send",
        json={"selected_fields": ["name"]},
    )
    assert send_response.status_code == 409
    assert "review queue" in send_response.json()["detail"].lower()

    review_queue = client.get(f"/projects/{project_id}/crm/review-queue")
    assert review_queue.status_code == 200
    assert len(review_queue.json()) == 1
    assert review_queue.json()[0]["id"] == preview_id
    assert review_queue.json()[0]["review_status"] == "pending"

    resolve_response = client.post(
        f"/projects/{project_id}/crm/review-queue/{preview_id}/resolve",
        json={
            "outcome": "approved",
            "summary": "Проверка полей завершена.",
            "amo_entity_id": "75807689",
        },
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["preview"]["review_status"] == "approved"

    second_send = client.post(
        f"/projects/{project_id}/crm/previews/{preview_id}/send",
        json={"selected_fields": ["Id Tallanto"]},
    )
    assert second_send.status_code == 200
    assert second_send.json()["preview"]["status"] == "sent"
    assert any(item["method"] == "PATCH" for item in requests)
    assert any("/api/v4/contacts/custom_fields" in item["url"] for item in requests)
    assert any(item["url"].endswith("/api/v4/contacts/75807689") for item in requests if item["method"] == "PATCH")


def test_crm_review_queue_keeps_family_case_in_operator_backlog(tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_AMO_MODE", "http")
    monkeypatch.setenv("CRM_AMO_BASE_URL", "https://amo.example.test")
    monkeypatch.setenv("CRM_AMO_API_TOKEN", "token")

    database_path = tmp_path / "crm_review_queue_family_case.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "CRM Family Queue", "description": "operator queue flow"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    preview_response = client.post(
        f"/projects/{project_id}/crm/previews",
        json={"student_id": "student-1401", "amo_entity_type": "contact"},
    )
    assert preview_response.status_code == 201
    preview_id = preview_response.json()["id"]
    assert preview_response.json()["review_status"] == "pending"

    resolve_response = client.post(
        f"/projects/{project_id}/crm/review-queue/{preview_id}/resolve",
        json={
            "outcome": "family_case",
            "summary": "Найден общий номер родителя, нужен ручной выбор ученика.",
        },
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["preview"]["review_status"] == "family_case"

    queue_response = client.get(f"/projects/{project_id}/crm/review-queue")
    assert queue_response.status_code == 200
    assert len(queue_response.json()) == 1
    assert queue_response.json()[0]["id"] == preview_id

    send_response = client.post(
        f"/projects/{project_id}/crm/previews/{preview_id}/send",
        json={"selected_fields": ["Id Tallanto"]},
    )
    assert send_response.status_code == 409
    assert "must be approved" in send_response.json()["detail"].lower()


def test_call_insight_ingest_flow(tmp_path, monkeypatch):
    database_path = tmp_path / "calls_intake.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "Calls Module", "description": "call insight intake"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    human_forbidden = client.post(
        f"/projects/{project_id}/calls/insights",
        json=build_call_insight_payload(source_call_id="mango-call-human-denied"),
        headers={"X-API-Key": "test-human-key"},
    )
    assert human_forbidden.status_code == 403

    create_response = client.post(
        f"/projects/{project_id}/calls/insights",
        json=build_call_insight_payload(),
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()
    assert "сохранён" in create_payload["summary"].lower()
    assert create_payload["insight"]["source_system"] == "mango_analyse"
    assert create_payload["insight"]["source_key"] == "call:mango-call-1001"
    assert create_payload["insight"]["match_status"] == "pending_match"
    assert create_payload["insight"]["lead_priority"] == "warm"
    assert create_payload["insight"]["follow_up_score"] == 72
    assert create_payload["insight"]["manager_name"] == "Иванов Иван"
    assert create_payload["insight"]["payload"]["schema_version"] == "call_insight_v1"
    assert create_payload["insight"]["started_at"].startswith("2026-03-19T10:00:00")
    call_insight_id = create_payload["insight"]["id"]

    list_response = client.get(f"/projects/{project_id}/calls/insights")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1
    assert list_payload[0]["id"] == call_insight_id
    assert list_payload[0]["history_summary"].startswith("19.03.2026 10:00")

    list_human = client.get(
        f"/projects/{project_id}/calls/insights",
        headers={"X-API-Key": "test-human-key"},
    )
    assert list_human.status_code == 200
    assert len(list_human.json()) == 1

    detail_response = client.get(f"/projects/{project_id}/calls/insights/{call_insight_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["id"] == call_insight_id
    assert detail_payload["phone"] == "+79990001122"
    assert detail_payload["payload"]["call_summary"]["history_short"]

    artifacts = client.get(f"/projects/{project_id}/artifacts")
    assert artifacts.status_code == 200
    assert any(
        artifact["kind"] == "call_insight" and "Call insight" in artifact["title"]
        for artifact in artifacts.json()
    )

    events = client.get(f"/projects/{project_id}/events")
    assert events.status_code == 200
    event_types = [event["event_type"] for event in events.json()]
    assert "call_insight_ingested" in event_types
    assert "artifact_created" in event_types

    duplicate_response = client.post(
        f"/projects/{project_id}/calls/insights",
        json=build_call_insight_payload(),
    )
    assert duplicate_response.status_code == 409
    assert "already exists" in duplicate_response.json()["detail"].lower()


def test_call_insight_review_queue_and_controlled_send(tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_AMO_MODE", "http")
    monkeypatch.setenv("CRM_AMO_BASE_URL", "https://amo.example.test")
    monkeypatch.setenv("CRM_AMO_API_TOKEN", "token")

    database_path = tmp_path / "calls_review_queue.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    import app.crm_bridge as crm_bridge

    requests = []

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        body = request.data.decode("utf-8", errors="ignore") if request.data else ""
        requests.append(
            {
                "url": url,
                "method": request.get_method(),
                "data": body,
            }
        )
        if "/api/v4/contacts/custom_fields" in url:
            return _JsonResponse(
                {
                    "_embedded": {
                        "custom_fields": [
                            {"id": 101, "name": "Id Tallanto", "type": "text"},
                            {"id": 102, "name": "Авто история общения", "type": "text"},
                            {"id": 103, "name": "AI-приоритет", "type": "text"},
                            {"id": 104, "name": "AI-рекомендованный следующий шаг", "type": "text"},
                            {"id": 105, "name": "Последняя AI-сводка", "type": "text"},
                            {"id": 110, "name": "Статус матчинга", "type": "text"},
                        ]
                    }
                }
            )
        return _JsonResponse({"result": "ok"})

    monkeypatch.setattr(crm_bridge.url_request, "urlopen", fake_urlopen)

    project = client.post(
        "/projects",
        json={"name": "Calls Queue", "description": "reviewed call write"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    create_response = client.post(
        f"/projects/{project_id}/calls/insights",
        json=build_call_insight_payload(source_call_id="mango-call-queue-1001"),
    )
    assert create_response.status_code == 201
    insight = create_response.json()["insight"]
    call_insight_id = insight["id"]
    assert insight["review_status"] == "pending"
    assert "ручная проверка" in insight["review_reason"].lower()

    send_before_review = client.post(
        f"/projects/{project_id}/calls/insights/{call_insight_id}/send",
        json={"matched_amo_contact_id": 75807689},
    )
    assert send_before_review.status_code == 409
    assert "review queue" in send_before_review.json()["detail"].lower()

    review_queue = client.get(f"/projects/{project_id}/calls/review-queue")
    assert review_queue.status_code == 200
    assert len(review_queue.json()) == 1
    assert review_queue.json()[0]["id"] == call_insight_id

    resolve_missing_match = client.post(
        f"/projects/{project_id}/calls/review-queue/{call_insight_id}/resolve",
        json={"outcome": "approved"},
    )
    assert resolve_missing_match.status_code == 409
    assert "matched_amo_contact_id" in resolve_missing_match.json()["detail"]

    resolve_response = client.post(
        f"/projects/{project_id}/calls/review-queue/{call_insight_id}/resolve",
        json={
            "outcome": "approved",
            "matched_amo_contact_id": 75807689,
            "summary": "Подтвердили ученика и контакт AMO.",
        },
    )
    assert resolve_response.status_code == 200
    resolved_insight = resolve_response.json()["insight"]
    assert resolved_insight["review_status"] == "approved"
    assert resolved_insight["matched_amo_contact_id"] == 75807689

    send_response = client.post(
        f"/projects/{project_id}/calls/insights/{call_insight_id}/send",
        json={"field_overrides": {"call_priority": "hot"}},
    )
    assert send_response.status_code == 200
    sent_insight = send_response.json()["insight"]
    assert sent_insight["status"] == "sent"
    assert sent_insight["sent_by"] == "director"
    assert any(item["method"] == "PATCH" for item in requests)
    assert any("/api/v4/contacts/custom_fields" in item["url"] for item in requests)
    assert any(item["url"].endswith("/api/v4/contacts/75807689") for item in requests if item["method"] == "PATCH")

    artifacts = client.get(f"/projects/{project_id}/artifacts")
    assert artifacts.status_code == 200
    assert any(
        artifact["kind"] == "call_sync_result"
        for artifact in artifacts.json()
    )

    events = client.get(f"/projects/{project_id}/events")
    event_types = [event["event_type"] for event in events.json()]
    assert "call_review_resolved" in event_types
    assert "call_send_completed" in event_types


def test_call_insight_requires_history_summary(tmp_path, monkeypatch):
    database_path = tmp_path / "calls_intake_invalid.db"
    runtime_root = tmp_path / "runtime"
    client = build_test_client(monkeypatch, database_path, runtime_root)

    project = client.post(
        "/projects",
        json={"name": "Calls Invalid", "description": "validation"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    payload = build_call_insight_payload()
    payload["call_summary"]["history_summary"] = ""

    response = client.post(
        f"/projects/{project_id}/calls/insights",
        json=payload,
    )
    assert response.status_code == 422
