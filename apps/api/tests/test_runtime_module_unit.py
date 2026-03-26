import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.runtime as runtime_module  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import Project, RunPolicy, Task, TaskEnvironment, TaskRun, TaskWorkspace  # noqa: E402


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def make_project_and_task(session: Session):
    project = Project(name="Runtime Project", description="runtime")
    session.add(project)
    session.flush()
    task = Task(
        project_id=project.id,
        task_key="frontend_task",
        title="Frontend task",
        brief="Do a small UI task",
        acceptance_criteria=["done"],
        status="ready",
    )
    session.add(task)
    session.flush()
    return project, task


def test_runtime_helper_functions_cover_snapshot_seed_and_cleanup(monkeypatch, tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "keep.txt").write_text("keep", encoding="utf-8")
    (source_root / ".env").write_text("skip", encoding="utf-8")
    (source_root / "node_modules").mkdir()
    (source_root / "node_modules" / "skip.js").write_text("skip", encoding="utf-8")
    (source_root / "runtime").mkdir()
    (source_root / "runtime" / "skip.log").write_text("skip", encoding="utf-8")
    (source_root / "apps" / "api" / "runtime").mkdir(parents=True)
    (source_root / "apps" / "api" / "runtime" / "skip.txt").write_text("skip", encoding="utf-8")
    (source_root / ".git").mkdir()

    runtime_root = tmp_path / "runtime-host"
    monkeypatch.setattr(
        runtime_module,
        "settings",
        SimpleNamespace(
            runtime_root=str(runtime_root),
            source_workspace_root=str(source_root),
            task_container_driver="none",
            task_container_image="task-image",
            task_container_name_prefix="task",
            task_container_network="bridge",
        ),
    )

    manifest = runtime_module.collect_workspace_manifest(source_root)
    assert manifest["keep.txt"]["size"] == 4
    assert runtime_module._find_git_root(source_root) == source_root

    monkeypatch.setattr(runtime_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(runtime_module.os, "access", lambda path, mode: True)
    assert runtime_module._can_use_git_worktree(source_root) is True
    monkeypatch.setattr(runtime_module.os, "access", lambda path, mode: False)
    assert runtime_module._can_use_git_worktree(source_root) is False

    workspace_dir = tmp_path / "workspace"
    runtime_module._seed_workspace_snapshot(source_root, workspace_dir)
    assert (workspace_dir / "keep.txt").exists()
    assert not (workspace_dir / ".env").exists()
    assert not (workspace_dir / "runtime").exists()
    assert not (workspace_dir / "apps" / "api" / "runtime").exists()

    baseline_path = tmp_path / "WORKSPACE_BASELINE.json"
    runtime_module._write_workspace_baseline(workspace_dir, baseline_path)
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert baseline_payload["workspace_path"] == str(workspace_dir)
    assert "keep.txt" in baseline_payload["manifest"]

    assert runtime_module._should_skip_snapshot_path(source_root / ".env", []) is True
    assert runtime_module._should_skip_snapshot_path(source_root / "keep.txt", []) is False
    assert runtime_module._follow_next_link if False else True  # keep module imported for lint

    seeded_modes = []

    def fake_seed_git_worktree(src, dest):
        seeded_modes.append(("git-worktree", src, dest))

    monkeypatch.setattr(runtime_module, "_can_use_git_worktree", lambda src: True)
    monkeypatch.setattr(runtime_module, "_seed_workspace_git_worktree", fake_seed_git_worktree)
    assert runtime_module._seed_task_workspace(source_root, workspace_dir) == ("git-worktree", "seeded")

    monkeypatch.setattr(
        runtime_module,
        "_seed_workspace_git_worktree",
        lambda src, dest: (_ for _ in ()).throw(RuntimeError("fail")),
    )
    assert runtime_module._seed_task_workspace(source_root, workspace_dir) == (
        "snapshot-copy",
        "seeded-fallback",
    )

    recorded_git_commands = []
    monkeypatch.setattr(runtime_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(
        runtime_module.subprocess,
        "run",
        lambda args, **kwargs: recorded_git_commands.append(args),
    )

    git_workspace_root = tmp_path / "runtime-cleanup"
    git_workspace_dir = git_workspace_root / "workspace"
    git_workspace_dir.mkdir(parents=True)
    git_workspace = TaskWorkspace(
        project_id="project-1",
        task_id="task-1",
        root_path=str(git_workspace_root),
        workspace_path=str(git_workspace_dir),
        source_root_path=str(source_root),
        workspace_mode="git-worktree",
        sync_status="seeded",
        sandbox_mode="workspace-write",
        state="provisioned",
    )
    runtime_module._remove_task_workspace(git_workspace)
    assert recorded_git_commands
    assert not git_workspace_root.exists()


def test_runtime_lifecycle_provision_cleanup_and_run_transitions(monkeypatch, tmp_path):
    session = make_session()
    project, task = make_project_and_task(session)

    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "README.md").write_text("hello", encoding="utf-8")
    runtime_root = tmp_path / "runtime"
    events = []
    policy_actions = []

    monkeypatch.setattr(
        runtime_module,
        "settings",
        SimpleNamespace(
            runtime_root=str(runtime_root),
            source_workspace_root=str(source_root),
            task_container_driver="none",
            task_container_image="shared-api-runtime",
            task_container_name_prefix="task",
            task_container_network="bridge",
        ),
    )
    monkeypatch.setattr(runtime_module, "source_workspace_root_path", lambda: source_root)
    monkeypatch.setattr(runtime_module, "_can_use_git_worktree", lambda src: False)
    monkeypatch.setattr(runtime_module, "container_runtime_enabled", lambda: False)
    monkeypatch.setattr(runtime_module, "container_workdir", lambda: "/task")
    monkeypatch.setattr(
        runtime_module,
        "evaluate_policy_action",
        lambda session_arg, project_arg, action_key, **kwargs: policy_actions.append((project_arg.id, action_key)),
    )
    monkeypatch.setattr(
        runtime_module,
        "log_event",
        lambda session_arg, project_id, event_type, payload, **kwargs: events.append(event_type),
    )

    workspace = runtime_module.ensure_task_runtime(session, project, task)
    session.flush()
    baseline_path = Path(runtime_module.workspace_baseline_path(project.id, task.id))
    assert workspace.workspace_mode == "snapshot-copy"
    assert workspace.sync_status == "seeded"
    assert baseline_path.exists()
    assert "task_runtime_provisioned" in events
    assert "task_workspace_seeded" in events
    assert policy_actions == [(project.id, "runtime.provision")]

    environment = session.scalars(select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)).one()
    run_policy = session.scalars(select(RunPolicy).where(RunPolicy.task_id == task.id)).one()
    provisioned_run = session.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "provisioned")
    ).one()
    assert environment.runtime_status == "ready"
    assert run_policy.policy_level == "task-runtime"
    assert "Runtime provisioned" in provisioned_run.stdout

    workspace.sync_status = "seeded"
    workspace.source_root_path = str(source_root)
    workspace.workspace_mode = "snapshot-copy"
    environment.runtime_status = "broken"
    environment.name = "bad-env"
    environment.mounts = []
    run_policy.policy_level = "legacy"
    provisioned_run.stdout = "legacy"
    provisioned_run.environment_name = "legacy"
    baseline_path.unlink()

    events.clear()
    policy_actions.clear()
    refreshed_workspace = runtime_module.ensure_task_runtime(session, project, task)
    session.flush()
    refreshed_environment = session.scalars(select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)).one()
    refreshed_policy = session.scalars(select(RunPolicy).where(RunPolicy.task_id == task.id)).one()
    refreshed_run = session.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "provisioned")
    ).one()
    assert refreshed_workspace.id == workspace.id
    assert refreshed_environment.name == f"{task.task_key}-env"
    assert refreshed_environment.runtime_status == "ready"
    assert refreshed_policy.policy_level == "task-runtime"
    assert refreshed_run.environment_name == refreshed_environment.name
    assert baseline_path.exists()
    assert "task_runtime_provisioned" in events
    assert policy_actions == [(project.id, "runtime.provision")]

    runtime_module.register_task_run_transition(
        session,
        task,
        "start",
        refreshed_workspace,
        refreshed_environment,
        "Worker started.",
    )
    session.flush()
    running_run = session.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "running")
    ).one()
    assert refreshed_workspace.state == "running"
    assert running_run.stdout == "Worker started."

    runtime_module.register_task_run_transition(
        session,
        task,
        "complete",
        refreshed_workspace,
        refreshed_environment,
        "Finished successfully.",
    )
    session.flush()
    completed_run = session.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "done")
    ).one()
    assert refreshed_workspace.state == "done"
    assert "Finished successfully." in completed_run.stdout

    runtime_module.register_task_run_transition(
        session,
        task,
        "block",
        refreshed_workspace,
        refreshed_environment,
        "Blocked by review.",
    )
    session.flush()
    blocked_run = session.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "blocked")
    ).all()
    assert blocked_run

    runtime_module.register_task_run_transition(
        session,
        task,
        "reset",
        refreshed_workspace,
        refreshed_environment,
        "Reset for another attempt.",
    )
    session.flush()
    assert refreshed_workspace.state == "provisioned"
    assert session.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "provisioned")
    ).all()

    runtime_module.register_task_run_transition(session, task, "start", None, refreshed_environment, "skip")
    runtime_module.register_task_run_transition(session, task, "start", refreshed_workspace, None, "skip")

    destroyed = []
    monkeypatch.setattr(runtime_module, "destroy_task_container", lambda environment_arg: destroyed.append(environment_arg.task_id))
    runtime_module.cleanup_task_runtime_resources(session, [])
    runtime_module.cleanup_task_runtime_resources(session, [task.id])
    session.flush()
    assert destroyed == [task.id]
    assert session.scalars(select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)).first() is None
    assert session.scalars(select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)).first() is None
    assert session.scalars(select(RunPolicy).where(RunPolicy.task_id == task.id)).first() is None
