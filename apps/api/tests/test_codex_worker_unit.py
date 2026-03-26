import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.codex_worker as codex_worker_module  # noqa: E402
from app.codex_worker import (  # noqa: E402
    _blocking_preflight_messages,
    _clear_run_cancellation,
    _execute_task_run,
    _format_change_list,
    _is_run_cancellation_requested,
    _load_workspace_baseline_manifest,
    _parse_action_requests,
    _request_run_cancellation,
    _task_run_age_seconds,
    _watch_task_run_timeout,
    recover_stale_task_runs,
    stale_run_recovery_threshold_seconds,
    _cleanup_task_container_runtime,
    _create_workspace_change_summary_artifact,
    _handle_pending_cancellation,
    _mark_run_stopped,
    _run_mock_worker,
    _run_real_worker,
    _workspace_context_prompt,
    dispatch_director_next_ready_task,
    prepare_task_run_for_codex,
    start_codex_execution,
)
from app.db import Base  # noqa: E402
from app.models import Agent, Artifact, EventLog, Message, Project, Task, TaskEnvironment, TaskRun, TaskWorkspace  # noqa: E402
from app.orchestration import OrchestrationError  # noqa: E402


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def make_project_bundle(session):
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="backend_task",
        title="Сделать API",
        brief="Нужен endpoint",
        acceptance_criteria=["Есть маршрут"],
        status="running",
        priority=80,
    )
    workspace = TaskWorkspace(
        project=project,
        task=task,
        root_path="/tmp/runtime-root",
        workspace_path="/tmp/workspace",
        source_root_path="/tmp/source",
        state="running",
    )
    environment = TaskEnvironment(
        project=project,
        task=task,
        name="python",
        runtime_kind="task-container",
        runtime_status="container-ready",
        base_image="ai-office-task:latest",
        container_name="task-container",
        container_id="container-id",
        container_workdir="/task",
        env_vars={},
        mounts=[],
    )
    task_run = TaskRun(
        task=task,
        status="running",
        worktree_path=workspace.workspace_path,
        environment_name=environment.name,
        stdout="before\n",
    )
    session.add_all([project, task, workspace, environment, task_run])
    session.commit()
    return project, task, workspace, environment, task_run


def test_workspace_change_summary_and_cleanup(monkeypatch):
    session = make_session()
    project, task, workspace, environment, _ = make_project_bundle(session)

    monkeypatch.setattr(
        codex_worker_module,
        "_load_workspace_baseline_manifest",
        lambda project_id, task_id: {"old.py": {"sha256": "a"}, "same.py": {"sha256": "x"}},
    )
    monkeypatch.setattr(
        codex_worker_module,
        "collect_workspace_manifest",
        lambda path: {"same.py": {"sha256": "x"}, "new.py": {"sha256": "b"}},
    )

    artifact = _create_workspace_change_summary_artifact(session, project, task, workspace)
    assert artifact.kind == "workspace_change_summary"
    assert "Created files: 1" in artifact.content
    assert "Deleted files: 1" in artifact.content
    assert session.scalars(select(Artifact)).first() is not None

    cleaned = []
    monkeypatch.setattr(codex_worker_module, "container_runtime_enabled", lambda: True)
    monkeypatch.setattr(codex_worker_module, "destroy_task_container", lambda env: cleaned.append(env.container_name))
    _cleanup_task_container_runtime(
        session,
        project,
        task,
        environment,
        runtime_status="container-cleaned",
        event_type="task_container_cleaned",
        event_reason="completed",
    )
    assert cleaned == ["task-container"]
    assert environment.runtime_status == "container-cleaned"
    assert environment.container_id is None


def test_mark_run_stopped_and_pending_cancellation(monkeypatch):
    session = make_session()
    project, task, workspace, environment, task_run = make_project_bundle(session)

    monkeypatch.setattr(codex_worker_module, "fail_task_execution", lambda *args, **kwargs: "Task failed")
    monkeypatch.setattr(codex_worker_module, "_cleanup_task_container_runtime", lambda *args, **kwargs: None)
    summary = _mark_run_stopped(
        session,
        project,
        task,
        task_run,
        workspace,
        environment,
        status="cancelled",
        reason="Cancelled by operator",
        actor="operator",
        event_type="task_execution_cancelled",
    )
    assert "marked as cancelled" in summary
    assert task_run.status == "cancelled"
    assert "Cancelled by operator" in task_run.stderr
    assert "Task failed" in task_run.stdout

    project, task, workspace, environment, task_run = make_project_bundle(session)
    task.status = "running"
    calls = []
    monkeypatch.setattr(codex_worker_module, "_is_run_cancellation_requested", lambda task_run_id: True)
    monkeypatch.setattr(codex_worker_module, "_mark_run_stopped", lambda *args, **kwargs: calls.append(kwargs["status"]))
    session.refresh = lambda instance: None
    session.commit = lambda: calls.append("commit")
    assert _handle_pending_cancellation(
        session,
        project,
        task,
        task_run,
        workspace,
        environment,
        reason="Need cancel",
    ) is True
    assert calls == ["cancelled", "commit"]


def test_prepare_task_run_and_thread_start(monkeypatch):
    session = make_session()
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="backend_task",
        title="Сделать API",
        brief="Нужен endpoint",
        acceptance_criteria=["Есть маршрут"],
        status="ready",
        priority=80,
    )
    workspace = TaskWorkspace(
        project=project,
        task=task,
        root_path="/tmp/runtime-root",
        workspace_path="/tmp/workspace",
        source_root_path="/tmp/source",
        state="seeded",
    )
    environment = TaskEnvironment(
        project=project,
        task=task,
        name="python",
        runtime_kind="process",
        runtime_status="ready",
        base_image="local",
        env_vars={},
        mounts=[],
    )
    session.add_all([project, task, workspace, environment])
    session.commit()

    monkeypatch.setattr(codex_worker_module, "ensure_task_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        codex_worker_module,
        "evaluate_policy_action",
        lambda *args, **kwargs: SimpleNamespace(allowed=True),
    )
    monkeypatch.setattr(codex_worker_module, "transition_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(codex_worker_mode="mock"),
    )

    task_run = prepare_task_run_for_codex(
        session,
        project,
        task,
        requested_by="director",
        requester_role="Director",
    )
    assert task_run.status == "running"
    assert task_run.stdout.startswith("Codex execution queued")

    monkeypatch.setattr(
        codex_worker_module,
        "evaluate_policy_action",
        lambda *args, **kwargs: SimpleNamespace(allowed=False),
    )
    task.status = "ready"
    session.commit()
    with pytest.raises(OrchestrationError):
        prepare_task_run_for_codex(
            session,
            project,
            task,
            requested_by="director",
            requester_role="Director",
        )

    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target
            self.args = args
            self.started = False
            started.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(codex_worker_module.threading, "Thread", FakeThread)
    start_codex_execution("project-1", "task-1", "run-1")
    assert len(started) == 2
    assert all(thread.started for thread in started)


def test_run_mock_and_real_worker_cover_process_and_container_paths(monkeypatch, tmp_path):
    session = make_session()
    project = SimpleNamespace(id="project-1", name="Office", latest_goal_text="Собрать модуль")
    task = SimpleNamespace(
        id="task-1",
        title="Сделать API",
        assigned_agent=SimpleNamespace(role="BackendEngineer"),
        brief="Нужен endpoint",
        acceptance_criteria=["Есть маршрут", "Есть тест"],
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    workspace = SimpleNamespace(workspace_path=str(workspace_dir))
    environment = SimpleNamespace(container_workdir="/task")
    task_run = SimpleNamespace(stdout=None)

    monkeypatch.setattr(codex_worker_module, "container_runtime_enabled", lambda: False)
    process_result = _run_mock_worker(session, project, task, task_run, workspace, environment)
    assert "Mock Codex Result" in process_result
    assert (workspace_dir / "CODEX_RESULT.md").exists()
    assert "Mock worker wrote" in task_run.stdout

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    monkeypatch.setattr(codex_worker_module, "task_runtime_root", lambda project_id, task_id: runtime_root)
    monkeypatch.setattr(codex_worker_module, "container_runtime_enabled", lambda: True)
    monkeypatch.setattr(codex_worker_module, "container_workspace_path", lambda: "/task/workspace")
    monkeypatch.setattr(codex_worker_module, "container_runtime_file_path", lambda file_name: f"/task/{file_name}")
    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(
            codex_execution_timeout_seconds=30,
            task_container_codex_home_container_path="/task/.codex-source",
            task_container_codex_home_runtime_path="/task/.codex",
            task_container_codex_home_copy_allowlist=("auth.json",),
            task_container_codex_command="codex",
            task_container_codex_sandbox="workspace-write",
            codex_cli_path="codex",
            codex_model="gpt-5.4",
        ),
    )

    def fake_run_command(environment, task_run, shell_command, timeout_seconds):
        (runtime_root / "codex_last_message.md").write_text("Container summary", encoding="utf-8")
        return 0

    monkeypatch.setattr(codex_worker_module, "run_command_in_task_container", fake_run_command)
    container_result = _run_real_worker(session, project, task, task_run, workspace, environment)
    assert container_result == "Container summary"
    assert (runtime_root / "run_codex_worker.sh").exists()

    monkeypatch.setattr(codex_worker_module, "container_runtime_enabled", lambda: False)
    (runtime_root / "codex_last_message.md").unlink(missing_ok=True)

    class FakePopen:
        def __init__(self, command, cwd=None, stdout=None, stderr=None, text=None, bufsize=None):
            self.command = command
            self.stdout = iter(["line 1\n", "line 2\n"])
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text("Process summary", encoding="utf-8")

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(codex_worker_module.subprocess, "Popen", FakePopen)
    process_real_result = _run_real_worker(session, project, task, task_run, workspace, environment)
    assert process_real_result == "Process summary"
    assert "line 1" in task_run.stdout


def test_run_mock_worker_container_path_and_failure(monkeypatch, tmp_path):
    session = make_session()
    project = SimpleNamespace(id="project-1", name="Office", latest_goal_text="Собрать модуль")
    task = SimpleNamespace(
        id="task-1",
        title="Сделать API",
        assigned_agent=SimpleNamespace(role="BackendEngineer"),
        brief="Нужен endpoint",
        acceptance_criteria=["Есть маршрут", "Есть тест"],
    )
    workspace = SimpleNamespace(workspace_path=str(tmp_path / "workspace"))
    environment = SimpleNamespace(container_workdir="/task")
    task_run = SimpleNamespace(stdout=None)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()

    monkeypatch.setattr(codex_worker_module, "task_runtime_root", lambda project_id, task_id: runtime_root)
    monkeypatch.setattr(codex_worker_module, "container_runtime_enabled", lambda: True)
    monkeypatch.setattr(codex_worker_module, "container_workspace_path", lambda: "/task/workspace")
    monkeypatch.setattr(codex_worker_module, "container_runtime_file_path", lambda file_name: f"/task/{file_name}")
    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(codex_execution_timeout_seconds=30),
    )
    monkeypatch.setattr(codex_worker_module, "run_command_in_task_container", lambda *args, **kwargs: 0)

    container_result = _run_mock_worker(session, project, task, task_run, workspace, environment)
    assert "Mock Codex Result" in container_result
    assert (runtime_root / "run_mock_worker.sh").exists()

    monkeypatch.setattr(codex_worker_module, "run_command_in_task_container", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError):
        _run_mock_worker(session, project, task, task_run, workspace, environment)


def test_dispatch_director_next_ready_task_covers_handoff_block_and_success(monkeypatch):
    session = make_session()
    project = Project(name="Office", description="Test", status="active")
    over_limit_task = Task(
        project=project,
        task_key="t1",
        title="Слишком много попыток",
        brief="brief",
        acceptance_criteria=["ok"],
        status="ready",
        priority=100,
    )
    blocked_task = Task(
        project=project,
        task_key="t2",
        title="Падает на preflight",
        brief="brief",
        acceptance_criteria=["ok"],
        status="ready",
        priority=90,
    )
    good_task = Task(
        project=project,
        task_key="t3",
        title="Готова к запуску",
        brief="brief",
        acceptance_criteria=["ok"],
        status="ready",
        priority=80,
    )
    session.add_all([project, over_limit_task, blocked_task, good_task])
    session.commit()

    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(
            director_auto_run_enabled=True,
            director_auto_max_attempts=2,
        ),
    )
    monkeypatch.setattr(
        codex_worker_module,
        "_count_task_attempts",
        lambda session, task_id: 2 if task_id == over_limit_task.id else 0,
    )
    monkeypatch.setattr(
        codex_worker_module,
        "build_task_preflight",
        lambda session, project, task: SimpleNamespace(
            ready=task.id == good_task.id,
            summary="blocked",
            checks=[SimpleNamespace(status="fail", blocking=True, message="runtime not ready")],
        ),
    )
    monkeypatch.setattr(codex_worker_module, "post_director_progress_update", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        codex_worker_module,
        "prepare_task_run_for_codex",
        lambda session, project, task, requested_by, requester_role: SimpleNamespace(id="run-123"),
    )
    monkeypatch.setattr(
        codex_worker_module,
        "transition_task",
        lambda session, project, task, action, reason: setattr(task, "status", "blocked"),
    )

    dispatch = dispatch_director_next_ready_task(session, project, trigger="test")
    assert dispatch is not None
    assert dispatch.task_id == good_task.id

    session.flush()
    messages = session.scalars(select(Message).where(Message.project_id == project.id)).all()
    assert len(messages) == 2
    assert "достигнут лимит попыток" in messages[0].content
    assert "preflight-проверкой" in messages[1].content

    events = session.scalars(select(EventLog).where(EventLog.project_id == project.id)).all()
    event_types = {item.event_type for item in events}
    assert "director_auto_handoff_required" in event_types
    assert "director_auto_dispatch_blocked" in event_types
    assert "director_auto_dispatched" in event_types


def test_workspace_context_prompt_biases_implementation_tasks_to_real_changes():
    project = SimpleNamespace(name="Office", latest_goal_text="Сделай новый экран помощи")
    task = SimpleNamespace(
        task_key="frontend_foundation",
        title="Implement user-facing interface changes",
        brief="Make UI changes directly in the workspace",
        acceptance_criteria=["Implements the requested screen"],
        assigned_agent=SimpleNamespace(role="FrontendEngineer"),
    )

    prompt = _workspace_context_prompt(project, task)

    assert "Prefer direct code and file changes over planning prose." in prompt
    assert "Finish with a concise execution summary that names changed files and checks performed." in prompt


def test_worker_action_requests_and_helper_branches(monkeypatch, tmp_path):
    valid_content = (
        'ACTION_REQUEST: runtime.install_package {"registry":"pypi.org","package_name":"pytest"}\n'
        'ACTION_REQUEST: runtime.host_access {"target_path":"/Users/test/.ssh"}\n'
        'ACTION_REQUEST: runtime.secret_write {"target":"env"}\n'
        'ACTION_REQUEST: runtime.install_package {"broken": }\n'
    )
    requests, errors = _parse_action_requests(valid_content)
    assert len(requests) == 3
    assert len(errors) == 1

    session = make_session()
    project, task, _, _, task_run = make_project_bundle(session)
    agent = Agent(
        project=project,
        role="BackendEngineer",
        name="Backend",
        specialization="API",
    )
    session.add(agent)
    session.flush()
    task.assigned_agent = agent

    def fake_evaluate(*args, **kwargs):
        action_key = args[2]
        if action_key == "runtime.install_package":
            return SimpleNamespace(allowed=True, approval_request=None, action_intent=None)
        if action_key == "runtime.host_access":
            return SimpleNamespace(
                allowed=False,
                approval_request=SimpleNamespace(id="approval-1"),
                action_intent=SimpleNamespace(id="intent-1"),
            )
        return SimpleNamespace(allowed=False, approval_request=None, action_intent=None)

    monkeypatch.setattr(codex_worker_module, "evaluate_policy_action", fake_evaluate)
    count = codex_worker_module._apply_worker_action_requests(
        session,
        project,
        task,
        task_run,
        valid_content,
    )
    assert count == 3
    assert "policy allowed the action" in task_run.stdout
    assert "human approval is required" in task_run.stdout
    assert "policy rejected" in task_run.stdout

    manifest_path = tmp_path / "baseline.json"
    manifest_path.write_text('{"manifest":{"src/app.py":{"sha256":"abc"}}}', encoding="utf-8")
    monkeypatch.setattr(codex_worker_module, "workspace_baseline_path", lambda project_id, task_id: manifest_path)
    assert _load_workspace_baseline_manifest("project-1", "task-1") == {"src/app.py": {"sha256": "abc"}}
    manifest_path.write_text("not-json", encoding="utf-8")
    assert _load_workspace_baseline_manifest("project-1", "task-1") == {}

    formatted = _format_change_list("Modified", [f"file-{index}.py" for index in range(25)], limit=3)
    assert "... and 22 more" in formatted
    assert "(none)" in _format_change_list("Deleted", [])

    _request_run_cancellation("run-1")
    assert _is_run_cancellation_requested("run-1") is True
    _clear_run_cancellation("run-1")
    assert _is_run_cancellation_requested("run-1") is False

    preflight_messages = _blocking_preflight_messages(
        SimpleNamespace(
            checks=[
                SimpleNamespace(status="pass", blocking=True, message="ok"),
                SimpleNamespace(status="fail", blocking=False, message="warn"),
                SimpleNamespace(status="fail", blocking=True, message="critical"),
            ]
        )
    )
    assert preflight_messages == ["critical"]

    aware_run = SimpleNamespace(started_at=codex_worker_module.utc_now())
    assert _task_run_age_seconds(aware_run) >= 0

    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(codex_execution_timeout_seconds=120, director_stale_run_grace_seconds=15),
    )
    assert stale_run_recovery_threshold_seconds() == 135


def test_recover_stale_runs_watchdog_and_real_worker_error_paths(monkeypatch, tmp_path):
    session = make_session()
    project, task, workspace, environment, task_run = make_project_bundle(session)
    task_run.started_at = codex_worker_module.utc_now() - timedelta(seconds=5)
    session.commit()

    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(
            codex_execution_timeout_seconds=30,
            director_stale_run_grace_seconds=10,
            director_stale_run_auto_retry_window_seconds=60,
            director_auto_run_enabled=True,
        ),
    )
    monkeypatch.setattr(codex_worker_module, "_request_run_cancellation", lambda task_run_id: None)

    def fake_mark_run_stopped(*args, **kwargs):
        stale_run = args[3]
        stale_run.status = kwargs["status"]
        return "stopped"

    monkeypatch.setattr(codex_worker_module, "_mark_run_stopped", fake_mark_run_stopped)
    monkeypatch.setattr(
        codex_worker_module,
        "transition_task",
        lambda session, project, task, action, reason: (
            setattr(task, "status", "ready"),
            SimpleNamespace(summary="Reset complete"),
        )[1],
    )
    monkeypatch.setattr(codex_worker_module, "register_task_run_transition", lambda *args, **kwargs: None)
    monkeypatch.setattr(codex_worker_module, "post_director_progress_update", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        codex_worker_module,
        "dispatch_director_next_ready_task",
        lambda session, project, trigger: SimpleNamespace(task_id="next-task", task_run_id="run-next"),
    )
    dispatches = recover_stale_task_runs(session, trigger="test", stale_after_seconds=0)
    assert dispatches == [(project.id, "next-task", "run-next")]

    timeout_project, timeout_task, timeout_workspace, timeout_environment, timeout_run = make_project_bundle(session)
    timeout_run_id = timeout_run.id
    monkeypatch.setattr(codex_worker_module.time, "sleep", lambda seconds: None)
    timeout_calls = []
    monkeypatch.setattr(codex_worker_module, "_request_run_cancellation", lambda task_run_id: timeout_calls.append(("cancel", task_run_id)))
    monkeypatch.setattr(
        codex_worker_module,
        "_mark_run_stopped",
        lambda *args, **kwargs: timeout_calls.append(("stop", kwargs["status"], kwargs["actor"])),
    )
    monkeypatch.setattr(codex_worker_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(codex_execution_timeout_seconds=1),
    )
    _watch_task_run_timeout(timeout_project.id, timeout_task.id, timeout_run_id)
    assert ("cancel", timeout_run_id) in timeout_calls
    assert ("stop", "timed_out", "watchdog") in timeout_calls

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    monkeypatch.setattr(codex_worker_module, "task_runtime_root", lambda project_id, task_id: runtime_root)
    project_ns = SimpleNamespace(id="project-1", name="Office", latest_goal_text="Goal")
    task_ns = SimpleNamespace(
        id="task-1",
        title="Сделать API",
        assigned_agent=SimpleNamespace(role="BackendEngineer"),
        brief="brief",
        acceptance_criteria=["ok"],
    )
    workspace_ns = SimpleNamespace(workspace_path=str(workspace_dir))
    environment_ns = SimpleNamespace(container_workdir="/task")
    task_run_ns = SimpleNamespace(stdout=None)
    monkeypatch.setattr(codex_worker_module, "container_runtime_enabled", lambda: False)
    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(
            codex_cli_path="codex",
            codex_model="gpt-5.4",
            codex_execution_timeout_seconds=5,
        ),
    )

    class FailingPopen:
        def __init__(self, *args, **kwargs):
            self.stdout = iter(["line\n"])

        def wait(self, timeout=None):
            return 1

        def kill(self):
            return None

    monkeypatch.setattr(codex_worker_module.subprocess, "Popen", FailingPopen)
    with pytest.raises(RuntimeError):
        _run_real_worker(session, project_ns, task_ns, task_run_ns, workspace_ns, environment_ns)

    class TimeoutPopen:
        def __init__(self, *args, **kwargs):
            self.stdout = iter(["line\n"])
            self.killed = False

        def wait(self, timeout=None):
            raise codex_worker_module.subprocess.TimeoutExpired(cmd="codex", timeout=timeout)

        def kill(self):
            self.killed = True

    monkeypatch.setattr(codex_worker_module.subprocess, "Popen", TimeoutPopen)
    with pytest.raises(RuntimeError):
        _run_real_worker(session, project_ns, task_ns, task_run_ns, workspace_ns, environment_ns)

    class SuccessNoMessagePopen:
        def __init__(self, *args, **kwargs):
            self.stdout = iter(["line 1\n", "line 2\n"])

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(codex_worker_module.subprocess, "Popen", SuccessNoMessagePopen)
    result = _run_real_worker(session, project_ns, task_ns, task_run_ns, workspace_ns, environment_ns)
    assert "line 1" in result


def test_execute_task_run_covers_success_and_failure_branches(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)

    seed_session = session_factory()
    project, task, workspace, environment, task_run = make_project_bundle(seed_session)
    task.status = "running"
    task_run.status = "running"
    seed_session.commit()

    monkeypatch.setattr(codex_worker_module, "SessionLocal", session_factory)
    monkeypatch.setattr(codex_worker_module, "ensure_task_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(codex_worker_module, "container_runtime_enabled", lambda: False)
    monkeypatch.setattr(codex_worker_module, "_handle_pending_cancellation", lambda *args, **kwargs: False)
    monkeypatch.setattr(codex_worker_module, "_run_mock_worker", lambda *args, **kwargs: "Final worker message")
    monkeypatch.setattr(
        codex_worker_module,
        "_create_workspace_change_summary_artifact",
        lambda session, project, task, workspace: Artifact(
            project_id=project.id,
            task_id=task.id,
            kind="workspace_change_summary",
            title="summary",
            content="ok",
        ),
    )
    monkeypatch.setattr(codex_worker_module, "_apply_worker_action_requests", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        codex_worker_module,
        "transition_task",
        lambda session, project, task, action: (
            setattr(task, "status", "review"),
            SimpleNamespace(summary="Отправлено на проверку"),
        )[1],
    )
    monkeypatch.setattr(codex_worker_module, "run_task_review", lambda *args, **kwargs: None)
    monkeypatch.setattr(codex_worker_module, "_cleanup_task_container_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(codex_worker_module, "dispatch_director_next_ready_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(codex_worker_mode="mock", task_container_driver="process"),
    )

    _execute_task_run(project.id, task.id, task_run.id)

    verify_session = session_factory()
    verify_run = verify_session.get(TaskRun, task_run.id)
    verify_task = verify_session.get(Task, task.id)
    artifacts = verify_session.scalars(select(Artifact).where(Artifact.task_id == task.id)).all()
    assert verify_run.status == "review"
    assert verify_task.status == "review"
    assert "Registered 1 worker-requested runtime action" in (verify_run.stdout or "")
    assert any(item.kind == "codex_result" for item in artifacts)

    error_project = Project(name="Office 2", description="Error flow")
    error_task = Task(
        project=error_project,
        task_key="task-err",
        title="Сломанная задача",
        brief="Падает на worker",
        acceptance_criteria=["Есть результат"],
        status="running",
    )
    error_workspace = TaskWorkspace(
        project=error_project,
        task=error_task,
        root_path="/tmp/runtime-root",
        workspace_path="/tmp/workspace-2",
        source_root_path="/tmp/source-2",
        state="running",
    )
    error_environment = TaskEnvironment(
        project=error_project,
        task=error_task,
        name="python",
        runtime_kind="process",
        runtime_status="ready",
        base_image="local",
        env_vars={},
        mounts=[],
    )
    error_run = TaskRun(task=error_task, status="running", stdout="")
    verify_session.add_all([error_project, error_task, error_workspace, error_environment, error_run])
    verify_session.commit()

    monkeypatch.setattr(codex_worker_module, "_run_mock_worker", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(codex_worker_module, "_is_run_cancellation_requested", lambda task_run_id: False)
    monkeypatch.setattr(
        codex_worker_module,
        "fail_task_execution",
        lambda session, project, task, reason: (setattr(task, "status", "failed"), "Task failed hard")[1],
    )

    _execute_task_run(error_project.id, error_task.id, error_run.id)

    failed_session = session_factory()
    failed_run = failed_session.get(TaskRun, error_run.id)
    failed_task = failed_session.get(Task, error_task.id)
    assert failed_run.status == "failed"
    assert failed_run.stderr == "boom"
    assert failed_task.status == "failed"
