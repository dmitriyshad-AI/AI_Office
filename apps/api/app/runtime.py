from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Project,
    RunPolicy,
    Task,
    TaskEnvironment,
    TaskRun,
    TaskWorkspace,
    utc_now,
)
from app.orchestration import log_event
from app.policy import evaluate_policy_action
from app.task_container import container_runtime_enabled, container_workdir, destroy_task_container


settings = get_settings()
RUNTIME_KIND = "task-container" if settings.task_container_driver == "docker" else "workspace-runtime"
RUNTIME_BASE_IMAGE = (
    settings.task_container_image if settings.task_container_driver == "docker" else "shared-api-runtime"
)
RUNTIME_POLICY_NOTES = (
    "Provisioned task workspace for local Codex execution and policy-gated action intents."
)
SNAPSHOT_EXCLUDE_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".DS_Store",
}


def runtime_root_path() -> Path:
    root = Path(settings.runtime_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def source_workspace_root_path() -> Path:
    return Path(settings.source_workspace_root)


def task_runtime_root(project_id: str, task_id: str) -> Path:
    return runtime_root_path() / "projects" / project_id / "tasks" / task_id


def task_workspace_path(project_id: str, task_id: str) -> Path:
    return task_runtime_root(project_id, task_id) / "workspace"


def task_context_path(project_id: str, task_id: str) -> Path:
    return task_runtime_root(project_id, task_id) / "TASK_CONTEXT.json"


def workspace_baseline_path(project_id: str, task_id: str) -> Path:
    return task_runtime_root(project_id, task_id) / "WORKSPACE_BASELINE.json"


def collect_workspace_manifest(workspace_dir: Path) -> dict[str, dict[str, object]]:
    manifest: dict[str, dict[str, object]] = {}
    if not workspace_dir.exists():
        return manifest

    for file_path in sorted(path for path in workspace_dir.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(workspace_dir).as_posix()
        digest = hashlib.sha256()
        with file_path.open("rb") as source:
            while True:
                chunk = source.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
        stat = file_path.stat()
        manifest[relative_path] = {
            "sha256": digest.hexdigest(),
            "size": int(stat.st_size),
            "mtime": int(stat.st_mtime),
        }
    return manifest


def _write_workspace_baseline(workspace_dir: Path, baseline_path: Path) -> None:
    baseline_payload = {
        "workspace_path": str(workspace_dir),
        "manifest": collect_workspace_manifest(workspace_dir),
    }
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(baseline_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _find_git_root(source_root: Path) -> Optional[Path]:
    resolved = source_root.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _can_use_git_worktree(source_root: Path) -> bool:
    git_root = _find_git_root(source_root)
    return (
        git_root is not None
        and shutil.which("git") is not None
        and os.access(git_root, os.W_OK)
    )


def _clear_workspace_dir(workspace_dir: Path) -> None:
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir, ignore_errors=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
def _excluded_runtime_source_paths(source_root: Path) -> list[Path]:
    excluded_paths: list[Path] = []
    runtime_root = runtime_root_path().resolve()
    source_root_resolved = source_root.resolve()
    conventional_candidates = [
        source_root_resolved / "runtime",
        source_root_resolved / "apps" / "api" / "runtime",
    ]

    try:
        runtime_root.relative_to(source_root_resolved)
        excluded_paths.append(runtime_root)
    except ValueError:
        api_root = Path(__file__).resolve().parents[1]
        try:
            runtime_suffix = runtime_root.relative_to(api_root.resolve())
            mapped_api_root = source_root_resolved / "apps" / "api"
            if mapped_api_root.exists():
                excluded_paths.append((mapped_api_root / runtime_suffix).resolve())
        except ValueError:
            pass

    for candidate in conventional_candidates:
        if candidate.exists():
            excluded_paths.append(candidate.resolve())

    return excluded_paths


def _should_skip_snapshot_path(path: Path, excluded_roots: list[Path]) -> bool:
    if (
        path.name in SNAPSHOT_EXCLUDE_NAMES
        or path.name.endswith(".egg-info")
        or path.name == ".env"
        or path.name.startswith(".env.")
    ):
        return True

    for excluded_root in excluded_roots:
        try:
            path.resolve().relative_to(excluded_root)
            return True
        except ValueError:
            continue

    return False


def _seed_workspace_snapshot(source_root: Path, workspace_dir: Path) -> None:
    excluded_roots = _excluded_runtime_source_paths(source_root)
    _clear_workspace_dir(workspace_dir)

    for current_root, dir_names, file_names in os.walk(source_root):
        current_path = Path(current_root)
        dir_names[:] = sorted(
            [
                directory_name
                for directory_name in dir_names
                if not _should_skip_snapshot_path(current_path / directory_name, excluded_roots)
            ]
        )

        relative_path = current_path.relative_to(source_root)
        destination_root = (
            workspace_dir if str(relative_path) == "." else workspace_dir / relative_path
        )
        destination_root.mkdir(parents=True, exist_ok=True)

        for file_name in sorted(file_names):
            source_file = current_path / file_name
            if _should_skip_snapshot_path(source_file, excluded_roots):
                continue
            destination_file = destination_root / file_name
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_file)


def _seed_workspace_git_worktree(source_root: Path, workspace_dir: Path) -> None:
    git_root = _find_git_root(source_root)
    if git_root is None:
        raise RuntimeError("Git repository root was not found for worktree mode.")

    if workspace_dir.exists():
        shutil.rmtree(workspace_dir, ignore_errors=True)
    workspace_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(git_root), "worktree", "add", "--detach", str(workspace_dir), "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )


def _seed_task_workspace(
    source_root: Path,
    workspace_dir: Path,
) -> tuple[str, str]:
    requested_mode = "git-worktree" if _can_use_git_worktree(source_root) else "snapshot-copy"
    try:
        if requested_mode == "git-worktree":
            _seed_workspace_git_worktree(source_root, workspace_dir)
            return "git-worktree", "seeded"
    except Exception:
        _seed_workspace_snapshot(source_root, workspace_dir)
        return "snapshot-copy", "seeded-fallback"

    _seed_workspace_snapshot(source_root, workspace_dir)
    return "snapshot-copy", "seeded"


def _remove_task_workspace(workspace: TaskWorkspace) -> None:
    workspace_dir = Path(workspace.workspace_path)
    root_path = Path(workspace.root_path)

    if workspace.workspace_mode == "git-worktree" and workspace.source_root_path:
        git_root = _find_git_root(Path(workspace.source_root_path))
        if git_root is not None and shutil.which("git") is not None:
            subprocess.run(
                ["git", "-C", str(git_root), "worktree", "remove", "--force", str(workspace_dir)],
                check=False,
                capture_output=True,
                text=True,
            )

    if root_path.exists():
        shutil.rmtree(root_path, ignore_errors=True)


def _write_task_context(task: Task, workspace: TaskWorkspace) -> None:
    context_path = Path(workspace.context_file_path) if workspace.context_file_path else None
    if context_path is None:
        return
    context_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task.id,
        "project_id": task.project_id,
        "task_key": task.task_key,
        "title": task.title,
        "brief": task.brief,
        "acceptance_criteria": task.acceptance_criteria,
        "assigned_role": task.assigned_agent.role if task.assigned_agent else None,
        "workspace_path": workspace.workspace_path,
        "source_root_path": workspace.source_root_path,
        "workspace_mode": workspace.workspace_mode,
        "sync_status": workspace.sync_status,
        "sandbox_mode": workspace.sandbox_mode,
    }
    context_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_task_runtime(session: Session, project: Project, task: Task) -> TaskWorkspace:
    workspace = session.scalars(
        select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
    ).first()
    environment = session.scalars(
        select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
    ).first()
    run_policy = session.scalars(
        select(RunPolicy).where(RunPolicy.task_id == task.id)
    ).first()

    runtime_dir = task_runtime_root(project.id, task.id)
    workspace_dir = task_workspace_path(project.id, task.id)
    context_path = task_context_path(project.id, task.id)
    baseline_path = workspace_baseline_path(project.id, task.id)
    source_root = source_workspace_root_path()
    if not source_root.exists():
        raise RuntimeError(f"Source workspace root does not exist: {source_root}")
    expected_workspace_mode = "git-worktree" if _can_use_git_worktree(source_root) else "snapshot-copy"
    previous_source_root = workspace.source_root_path if workspace is not None else None
    previous_workspace_mode = workspace.workspace_mode if workspace is not None else None

    runtime_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    runtime_changed = False

    if workspace is None:
        workspace = TaskWorkspace(
            project_id=project.id,
            task_id=task.id,
            root_path=str(runtime_dir),
            workspace_path=str(workspace_dir),
            source_root_path=str(source_root),
            workspace_mode=expected_workspace_mode,
            sync_status="pending",
            sandbox_mode="workspace-write",
            state="provisioned",
            context_file_path=str(context_path),
        )
        session.add(workspace)
        session.flush()
        runtime_changed = True
    else:
        if (
            workspace.root_path != str(runtime_dir)
            or workspace.workspace_path != str(workspace_dir)
            or workspace.source_root_path != str(source_root)
            or workspace.workspace_mode != expected_workspace_mode
            or workspace.context_file_path != str(context_path)
        ):
            runtime_changed = True
        workspace.root_path = str(runtime_dir)
        workspace.workspace_path = str(workspace_dir)
        workspace.source_root_path = str(source_root)
        workspace.workspace_mode = expected_workspace_mode
        workspace.context_file_path = str(context_path)

    workspace_needs_seed = (
        previous_source_root != str(source_root)
        or previous_workspace_mode != expected_workspace_mode
        or
        workspace.sync_status == "pending"
        or not workspace_dir.exists()
        or not any(workspace_dir.iterdir())
    )
    if workspace_needs_seed:
        workspace_mode, sync_status = _seed_task_workspace(source_root, workspace_dir)
        workspace.workspace_mode = workspace_mode
        workspace.sync_status = sync_status
        _write_workspace_baseline(workspace_dir, baseline_path)
        runtime_changed = True
    elif not baseline_path.exists():
        _write_workspace_baseline(workspace_dir, baseline_path)
        runtime_changed = True

    if environment is None:
        environment = TaskEnvironment(
            project_id=project.id,
            task_id=task.id,
            name=f"{task.task_key}-env",
            runtime_kind=RUNTIME_KIND,
            runtime_status=(
                "container-pending" if container_runtime_enabled() else "ready"
            ),
            base_image=RUNTIME_BASE_IMAGE,
            container_name=(
                f"{settings.task_container_name_prefix}-{task.id[:12]}"
                if container_runtime_enabled()
                else None
            ),
            container_id=None,
            container_workdir=container_workdir() if container_runtime_enabled() else None,
            source_mount_mode=workspace.workspace_mode,
            workspace_mount_mode=(
                "bind-task-runtime-root" if container_runtime_enabled() else "read-write-task-workspace"
            ),
            network_mode=settings.task_container_network if container_runtime_enabled() else "restricted",
            env_vars={
                "PROJECT_ID": project.id,
                "TASK_ID": task.id,
                "TASK_KEY": task.task_key,
            },
            mounts=[
                (
                    f"{runtime_dir}:{container_workdir()}"
                    if container_runtime_enabled()
                    else str(workspace_dir)
                )
            ],
        )
        session.add(environment)
        runtime_changed = True
    else:
        if (
            environment.name != f"{task.task_key}-env"
            or environment.runtime_kind != RUNTIME_KIND
            or environment.runtime_status
            != ("container-pending" if container_runtime_enabled() else "ready")
            or environment.base_image != RUNTIME_BASE_IMAGE
            or environment.container_name
            != (
                f"{settings.task_container_name_prefix}-{task.id[:12]}"
                if container_runtime_enabled()
                else None
            )
            or environment.container_workdir != (container_workdir() if container_runtime_enabled() else None)
            or environment.source_mount_mode != workspace.workspace_mode
            or environment.workspace_mount_mode
            != (
                "bind-task-runtime-root"
                if container_runtime_enabled()
                else "read-write-task-workspace"
            )
            or environment.network_mode
            != (settings.task_container_network if container_runtime_enabled() else "restricted")
            or environment.env_vars
            != {
                "PROJECT_ID": project.id,
                "TASK_ID": task.id,
                "TASK_KEY": task.task_key,
            }
            or environment.mounts
            != [
                (
                    f"{runtime_dir}:{container_workdir()}"
                    if container_runtime_enabled()
                    else str(workspace_dir)
                )
            ]
        ):
            runtime_changed = True
        environment.name = f"{task.task_key}-env"
        environment.runtime_kind = RUNTIME_KIND
        environment.runtime_status = "container-pending" if container_runtime_enabled() else "ready"
        environment.base_image = RUNTIME_BASE_IMAGE
        environment.container_name = (
            f"{settings.task_container_name_prefix}-{task.id[:12]}"
            if container_runtime_enabled()
            else None
        )
        if not container_runtime_enabled():
            environment.container_id = None
        environment.container_workdir = container_workdir() if container_runtime_enabled() else None
        environment.source_mount_mode = workspace.workspace_mode
        environment.workspace_mount_mode = (
            "bind-task-runtime-root" if container_runtime_enabled() else "read-write-task-workspace"
        )
        environment.network_mode = (
            settings.task_container_network if container_runtime_enabled() else "restricted"
        )
        environment.env_vars = {
            "PROJECT_ID": project.id,
            "TASK_ID": task.id,
            "TASK_KEY": task.task_key,
        }
        environment.mounts = [
            (
                f"{runtime_dir}:{container_workdir()}"
                if container_runtime_enabled()
                else str(workspace_dir)
            )
        ]

    if run_policy is None:
        run_policy = RunPolicy(
            project_id=project.id,
            task_id=task.id,
            policy_level="task-runtime",
            network_access="restricted",
            filesystem_scope="task-workspace-only",
            package_installation_mode="allowlist-only",
            default_risk_level="medium",
            notes=RUNTIME_POLICY_NOTES,
        )
        session.add(run_policy)
        runtime_changed = True
    else:
        if (
            run_policy.policy_level != "task-runtime"
            or run_policy.network_access != "restricted"
            or run_policy.filesystem_scope != "task-workspace-only"
            or run_policy.package_installation_mode != "allowlist-only"
            or run_policy.default_risk_level != "medium"
            or run_policy.notes != RUNTIME_POLICY_NOTES
        ):
            runtime_changed = True
        run_policy.policy_level = "task-runtime"
        run_policy.network_access = "restricted"
        run_policy.filesystem_scope = "task-workspace-only"
        run_policy.package_installation_mode = "allowlist-only"
        run_policy.default_risk_level = "medium"
        run_policy.notes = RUNTIME_POLICY_NOTES

    provisioned_run = session.scalars(
        select(TaskRun)
        .where(TaskRun.task_id == task.id, TaskRun.status == "provisioned")
        .order_by(TaskRun.started_at.desc())
    ).first()
    if provisioned_run is None:
        provisioned_run = TaskRun(
            task_id=task.id,
            status="provisioned",
            started_at=utc_now(),
            worktree_path=str(workspace_dir),
            environment_name=environment.name,
            stdout="Runtime provisioned. No worker execution has started yet.",
            stderr=None,
        )
        session.add(provisioned_run)
        runtime_changed = True
    else:
        if (
            provisioned_run.worktree_path != str(workspace_dir)
            or provisioned_run.environment_name != environment.name
            or provisioned_run.stdout
            != "Runtime provisioned. No worker execution has started yet."
        ):
            runtime_changed = True
        provisioned_run.worktree_path = str(workspace_dir)
        provisioned_run.environment_name = environment.name
        provisioned_run.stdout = "Runtime provisioned. No worker execution has started yet."

    _write_task_context(task, workspace)
    if runtime_changed:
        evaluate_policy_action(
            session,
            project,
            "runtime.provision",
            task=task,
            requested_by="runtime-manager",
            requester_role="System",
            metadata={
                "workspace_path": str(workspace_dir),
                "source_root_path": str(source_root),
                "workspace_mode": workspace.workspace_mode,
                "environment_name": environment.name,
            },
        )
        log_event(
            session,
            project.id,
            "task_runtime_provisioned",
            {
                "task_key": task.task_key,
                "workspace_path": str(workspace_dir),
                "source_root_path": str(source_root),
                "workspace_mode": workspace.workspace_mode,
                "sync_status": workspace.sync_status,
                "environment_name": environment.name,
                "policy_level": run_policy.policy_level,
            },
            task_id=task.id,
        )
        if workspace_needs_seed:
            log_event(
                session,
                project.id,
                "task_workspace_seeded",
                {
                    "task_key": task.task_key,
                    "workspace_path": str(workspace_dir),
                    "source_root_path": str(source_root),
                    "workspace_mode": workspace.workspace_mode,
                    "sync_status": workspace.sync_status,
                },
                task_id=task.id,
            )
    return workspace


def provision_project_runtime(session: Session, project: Project, tasks: Iterable[Task]) -> None:
    for task in tasks:
        ensure_task_runtime(session, project, task)


def cleanup_task_runtime_resources(session: Session, task_ids: list[str]) -> None:
    if not task_ids:
        return

    workspaces = session.scalars(
        select(TaskWorkspace).where(TaskWorkspace.task_id.in_(task_ids))
    ).all()
    environments = session.scalars(
        select(TaskEnvironment).where(TaskEnvironment.task_id.in_(task_ids))
    ).all()
    environments_by_task_id = {environment.task_id: environment for environment in environments}
    for workspace in workspaces:
        environment = environments_by_task_id.get(workspace.task_id)
        if environment is not None:
            destroy_task_container(environment)
        _remove_task_workspace(workspace)

    session.execute(delete(RunPolicy).where(RunPolicy.task_id.in_(task_ids)))
    session.execute(delete(TaskEnvironment).where(TaskEnvironment.task_id.in_(task_ids)))
    session.execute(delete(TaskWorkspace).where(TaskWorkspace.task_id.in_(task_ids)))


def register_task_run_transition(
    session: Session,
    task: Task,
    action: str,
    workspace: Optional[TaskWorkspace],
    environment: Optional[TaskEnvironment],
    summary: str,
) -> None:
    if workspace is None or environment is None:
        return

    if action == "start":
        workspace.state = "running"
        session.add(
            TaskRun(
                task_id=task.id,
                status="running",
                started_at=utc_now(),
                worktree_path=workspace.workspace_path,
                environment_name=environment.name,
                stdout=summary,
                stderr=None,
            )
        )
        return

    if action in {"complete", "block"}:
        workspace.state = "done" if action == "complete" else "blocked"
        active_run = session.scalars(
            select(TaskRun)
            .where(TaskRun.task_id == task.id, TaskRun.status == "running")
            .order_by(TaskRun.started_at.desc())
        ).first()
        if active_run is None:
            active_run = TaskRun(
                task_id=task.id,
                status="running",
                started_at=utc_now(),
                worktree_path=workspace.workspace_path,
                environment_name=environment.name,
                stdout="Recovered run state during transition.",
                stderr=None,
            )
            session.add(active_run)
            session.flush()

        active_run.status = "done" if action == "complete" else "blocked"
        active_run.finished_at = utc_now()
        active_run.stdout = f"{active_run.stdout or ''}\n{summary}".strip()
        return

    if action == "reset":
        workspace.state = "provisioned"
        session.add(
            TaskRun(
                task_id=task.id,
                status="provisioned",
                started_at=utc_now(),
                worktree_path=workspace.workspace_path,
                environment_name=environment.name,
                stdout=summary,
                stderr=None,
            )
        )
