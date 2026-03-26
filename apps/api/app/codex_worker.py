from __future__ import annotations

import json
import re
import shlex
import subprocess
import threading
import time
from datetime import timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.director_reporting import post_director_progress_update
from app.models import (
    Artifact,
    Message,
    Project,
    Task,
    TaskEnvironment,
    TaskRun,
    TaskWorkspace,
    utc_now,
)
from app.orchestration import OrchestrationError, log_event, transition_task
from app.preflight import TaskPreflightResult, evaluate_task_preflight
from app.policy import evaluate_policy_action
from app.reviewer import run_task_review
from app.runtime import (
    collect_workspace_manifest,
    ensure_task_runtime,
    register_task_run_transition,
    task_runtime_root,
    workspace_baseline_path,
)
from app.task_container import (
    container_runtime_enabled,
    container_runtime_file_path,
    container_workspace_path,
    destroy_task_container,
    ensure_task_container,
    run_command_in_task_container,
)


settings = get_settings()
ACTION_REQUEST_PATTERN = re.compile(r"^ACTION_REQUEST:\s*([a-z0-9_.-]+)\s+(\{.*\})\s*$")
RUN_CONTROL_LOCK = threading.Lock()
DIRECTOR_DISPATCH_LOCK = threading.Lock()
RUN_CANCELLATION_FLAGS: set[str] = set()


@dataclass(frozen=True)
class DirectorDispatch:
    task_id: str
    task_run_id: str
    task_title: str


def _prompt_path(project_id: str, task_id: str) -> Path:
    return task_runtime_root(project_id, task_id) / "CODEX_PROMPT.md"


def _last_message_path(project_id: str, task_id: str) -> Path:
    return task_runtime_root(project_id, task_id) / "codex_last_message.md"


def _request_run_cancellation(task_run_id: str) -> None:
    with RUN_CONTROL_LOCK:
        RUN_CANCELLATION_FLAGS.add(task_run_id)


def _is_run_cancellation_requested(task_run_id: str) -> bool:
    with RUN_CONTROL_LOCK:
        return task_run_id in RUN_CANCELLATION_FLAGS


def _clear_run_cancellation(task_run_id: str) -> None:
    with RUN_CONTROL_LOCK:
        RUN_CANCELLATION_FLAGS.discard(task_run_id)


def _load_workspace_baseline_manifest(project_id: str, task_id: str) -> dict[str, dict]:
    baseline_path = workspace_baseline_path(project_id, task_id)
    if not baseline_path.exists():
        return {}
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    manifest = payload.get("manifest")
    if not isinstance(manifest, dict):
        return {}
    return manifest


def _format_change_list(title: str, paths: list[str], *, limit: int = 20) -> str:
    if not paths:
        return f"### {title}\n- (none)\n"
    lines = [f"### {title}"]
    shown_paths = paths[:limit]
    lines.extend(f"- `{path}`" for path in shown_paths)
    remaining = len(paths) - len(shown_paths)
    if remaining > 0:
        lines.append(f"- ... and {remaining} more")
    return "\n".join(lines) + "\n"


def _create_workspace_change_summary_artifact(
    session,
    project: Project,
    task: Task,
    workspace: TaskWorkspace,
) -> Artifact:
    baseline_manifest = _load_workspace_baseline_manifest(project.id, task.id)
    current_manifest = collect_workspace_manifest(Path(workspace.workspace_path))

    baseline_paths = set(baseline_manifest.keys())
    current_paths = set(current_manifest.keys())
    created_paths = sorted(current_paths - baseline_paths)
    deleted_paths = sorted(baseline_paths - current_paths)
    modified_paths = sorted(
        path
        for path in (baseline_paths & current_paths)
        if (baseline_manifest.get(path) or {}).get("sha256")
        != (current_manifest.get(path) or {}).get("sha256")
    )

    summary = (
        f"# Workspace Change Summary for {task.title}\n\n"
        f"- Created files: {len(created_paths)}\n"
        f"- Modified files: {len(modified_paths)}\n"
        f"- Deleted files: {len(deleted_paths)}\n\n"
        f"{_format_change_list('Created', created_paths)}\n"
        f"{_format_change_list('Modified', modified_paths)}\n"
        f"{_format_change_list('Deleted', deleted_paths)}\n"
    )

    artifact = Artifact(
        project_id=project.id,
        task_id=task.id,
        kind="workspace_change_summary",
        title=f"Workspace change summary for {task.title}",
        content=summary,
    )
    session.add(artifact)
    session.flush()
    log_event(
        session,
        project.id,
        "artifact_created",
        {"artifact_id": artifact.id, "kind": artifact.kind, "title": artifact.title},
        task_id=task.id,
    )
    return artifact


def _cleanup_task_container_runtime(
    session,
    project: Project,
    task: Task,
    environment: Optional[TaskEnvironment],
    *,
    runtime_status: str,
    event_type: str,
    event_reason: str,
) -> None:
    if not container_runtime_enabled() or environment is None:
        return
    if not environment.container_name:
        return

    destroy_task_container(environment)
    environment.runtime_status = runtime_status
    environment.container_id = None
    log_event(
        session,
        project.id,
        event_type,
        {
            "task_key": task.task_key,
            "container_name": environment.container_name,
            "reason": event_reason,
        },
        task_id=task.id,
    )


def _mark_run_stopped(
    session,
    project: Project,
    task: Task,
    task_run: TaskRun,
    workspace: Optional[TaskWorkspace],
    environment: Optional[TaskEnvironment],
    *,
    status: str,
    reason: str,
    actor: str,
    event_type: str,
) -> str:
    if task_run.status != "running":
        raise OrchestrationError("Only running task runs can be stopped.")

    task_run.status = status
    task_run.finished_at = utc_now()
    task_run.stderr = reason
    _append_stdout(task_run, f"\nExecution {status}: {reason}\n")

    if workspace is not None:
        workspace.state = status

    if task.status == "running":
        failure_summary = fail_task_execution(session, project, task, reason)
        _append_stdout(task_run, f"{failure_summary}\n")

    _cleanup_task_container_runtime(
        session,
        project,
        task,
        environment,
        runtime_status=f"container-{status}-cleaned",
        event_type="task_container_cleaned",
        event_reason=f"{status}:{reason}",
    )
    log_event(
        session,
        project.id,
        event_type,
        {
            "task_run_id": task_run.id,
            "task_key": task.task_key,
            "actor": actor,
            "reason": reason,
        },
        task_id=task.id,
    )
    return f"Task run {task_run.id} marked as {status} by {actor}: {reason}"


def _handle_pending_cancellation(
    session,
    project: Project,
    task: Task,
    task_run: TaskRun,
    workspace: Optional[TaskWorkspace],
    environment: Optional[TaskEnvironment],
    *,
    reason: str,
    actor: str = "worker",
) -> bool:
    if not _is_run_cancellation_requested(task_run.id):
        return False

    session.refresh(task_run)
    if task_run.status == "running":
        _mark_run_stopped(
            session,
            project,
            task,
            task_run,
            workspace,
            environment,
            status="cancelled",
            reason=reason,
            actor=actor,
            event_type="task_execution_cancelled",
        )
        session.commit()
    return True


def _workspace_context_prompt(project: Project, task: Task) -> str:
    role_name = task.assigned_agent.role if task.assigned_agent is not None else "Generalist"
    acceptance = "\n".join(f"- {criterion}" for criterion in task.acceptance_criteria)
    task_key = getattr(task, "task_key", "")
    direct_execution_task = task_key in {
        "frontend_foundation",
        "backend_foundation",
        "qa_strategy",
        "delivery_runtime",
    } or any(
        keyword in f"{task.title} {task.brief}".lower()
        for keyword in ("implement", "validate", "run qa", "доработ", "реализ", "исправ", "обнов", "сделай")
    )
    execution_bias = (
        "- Prefer direct code and file changes over planning prose.\n"
        "- Run focused verification commands when relevant and mention what was checked.\n"
        "- Create markdown notes only when the task explicitly asks for documentation or when documentation is needed to ship the change.\n"
        if direct_execution_task
        else "- Documentation is acceptable when it is the natural output of the assigned role.\n"
    )
    return (
        "You are the execution worker inside Virtual AI Office.\n"
        f"Project: {project.name}\n"
        f"Goal: {project.latest_goal_text or 'Not provided'}\n"
        f"Assigned role: {role_name}\n"
        f"Task title: {task.title}\n"
        f"Task brief: {task.brief}\n"
        "Acceptance criteria:\n"
        f"{acceptance}\n\n"
        "Rules:\n"
        "- Work only inside the provided workspace.\n"
        "- Produce the requested files or edits directly in the workspace when needed.\n"
        f"{execution_bias}"
        "- Finish with a concise execution summary that names changed files and checks performed.\n"
        "- Do not request host-level access.\n"
        "- If a privileged runtime action is required, emit a single line in this format:\n"
        '  ACTION_REQUEST: runtime.install_package {"registry":"pypi.org","package_name":"pytest"}\n'
        "- Supported privileged actions are runtime.install_package, runtime.host_access, and runtime.secret_write.\n"
    )


def _codex_home_copy_script_lines() -> list[str]:
    source_root = settings.task_container_codex_home_container_path.rstrip("/")
    runtime_root = settings.task_container_codex_home_runtime_path.rstrip("/")
    source_root_q = shlex.quote(source_root)
    runtime_root_q = shlex.quote(runtime_root)
    allowlist = tuple(
        entry.strip()
        for entry in settings.task_container_codex_home_copy_allowlist
        if entry.strip()
    )
    script_lines = [
        f"if [ -d {source_root_q} ]; then",
        f"  mkdir -p {runtime_root_q}",
    ]
    if allowlist:
        for entry in allowlist:
            source_path_q = shlex.quote(f"{source_root}/{entry}")
            runtime_path_q = shlex.quote(f"{runtime_root}/{entry}")
            script_lines.extend(
                [
                    f"  if [ -e {source_path_q} ]; then",
                    f"    cp -R {source_path_q} {runtime_path_q} 2>/dev/null || true",
                    "  fi",
                ]
            )
    else:
        script_lines.append(
            f"  cp -R {source_root_q}/. {runtime_root_q}/ 2>/dev/null || true"
        )
    script_lines.extend(
        [
            "fi",
            f"rm -rf {runtime_root_q}/sessions {runtime_root_q}/sqlite 2>/dev/null || true",
            (
                f"rm -f {runtime_root_q}/state_5.sqlite {runtime_root_q}/state_5.sqlite-wal "
                f"{runtime_root_q}/state_5.sqlite-shm 2>/dev/null || true"
            ),
        ]
    )
    return script_lines


def _append_stdout(task_run: TaskRun, chunk: str) -> None:
    task_run.stdout = f"{task_run.stdout or ''}{chunk}"


def _parse_action_requests(content: str) -> tuple[list[tuple[str, dict]], list[str]]:
    requests: list[tuple[str, dict]] = []
    errors: list[str] = []
    for line in content.splitlines():
        match = ACTION_REQUEST_PATTERN.match(line.strip())
        if match is None:
            continue
        action_key = match.group(1)
        try:
            metadata = json.loads(match.group(2))
        except json.JSONDecodeError as exc:
            errors.append(f"{action_key}: {exc}")
            continue
        requests.append((action_key, metadata))
    return requests, errors


def _apply_worker_action_requests(
    session,
    project: Project,
    task: Task,
    task_run: TaskRun,
    content: str,
) -> int:
    requests, errors = _parse_action_requests(content)
    for error in errors:
        _append_stdout(task_run, f"Worker emitted an invalid action request marker: {error}\n")

    if not requests:
        return 0

    worker_role = task.assigned_agent.role if task.assigned_agent is not None else "System"
    for action_key, metadata in requests:
        evaluation = evaluate_policy_action(
            session,
            project,
            action_key,
            task=task,
            task_run=task_run,
            requested_by="codex-worker",
            requester_role=worker_role,
            metadata=metadata,
        )
        if evaluation.allowed:
            _append_stdout(
                task_run,
                f"Worker requested {action_key}; policy allowed the action.\n",
            )
        elif evaluation.approval_request is not None:
            _append_stdout(
                task_run,
                f"Worker requested {action_key}; human approval is required.\n",
            )
        else:
            _append_stdout(
                task_run,
                f"Worker requested {action_key}; policy rejected for role {worker_role}.\n",
            )
        log_event(
            session,
            project.id,
            "worker_action_requested",
            {
                "task_run_id": task_run.id,
                "action_key": action_key,
                "allowed": evaluation.allowed,
                "action_intent_id": (
                    evaluation.action_intent.id if evaluation.action_intent is not None else None
                ),
            },
            task_id=task.id,
        )

    return len(requests)


def _create_result_artifact(session, project: Project, task: Task, content: str) -> Artifact:
    artifact = Artifact(
        project_id=project.id,
        task_id=task.id,
        kind="codex_result",
        title=f"Codex result for {task.title}",
        content=content,
    )
    session.add(artifact)
    session.flush()
    log_event(
        session,
        project.id,
        "artifact_created",
        {"artifact_id": artifact.id, "kind": artifact.kind, "title": artifact.title},
        task_id=task.id,
    )
    return artifact


def fail_task_execution(session, project: Project, task: Task, reason: str) -> str:
    if task.status != "running":
        raise OrchestrationError("Only running tasks can be marked as failed.")

    task.status = "failed"
    log_event(
        session,
        project.id,
        "task_failed",
        {"task_key": task.task_key, "reason": reason},
        task_id=task.id,
    )

    from app.orchestration import sync_agent_statuses, sync_project_status

    sync_agent_statuses(session, project)
    sync_project_status(session, project)
    return f"Task '{task.title}' failed: {reason}"


def _run_mock_worker(
    session,
    project: Project,
    task: Task,
    task_run: TaskRun,
    workspace: TaskWorkspace,
    environment: TaskEnvironment,
) -> str:
    if container_runtime_enabled():
        runtime_root = task_runtime_root(project.id, task.id)
        script_path = runtime_root / "run_mock_worker.sh"
        content = (
            f"# Mock Codex Result\n\n"
            f"Task: {task.title}\n\n"
            f"Role: {task.assigned_agent.role if task.assigned_agent else 'Generalist'}\n\n"
            f"Goal: {project.latest_goal_text or 'Not set'}\n"
        )
        script_path.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    "set -eu",
                    f"cat <<'EOF' > {container_workspace_path()}/CODEX_RESULT.md",
                    content,
                    "EOF",
                    'echo "Mock worker wrote CODEX_RESULT.md inside the task container workspace."',
                    f"cat {container_workspace_path()}/CODEX_RESULT.md",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return_code = run_command_in_task_container(
            environment,
            task_run,
            f"sh {container_runtime_file_path('run_mock_worker.sh')}",
            timeout_seconds=settings.codex_execution_timeout_seconds,
        )
        if return_code != 0:
            raise RuntimeError(f"Task container mock worker exited with code {return_code}.")
        return content

    output_path = Path(workspace.workspace_path) / "CODEX_RESULT.md"
    content = (
        f"# Mock Codex Result\n\n"
        f"Task: {task.title}\n\n"
        f"Role: {task.assigned_agent.role if task.assigned_agent else 'Generalist'}\n\n"
        f"Goal: {project.latest_goal_text or 'Not set'}\n"
    )
    output_path.write_text(content, encoding="utf-8")
    _append_stdout(
        task_run,
        "Mock worker wrote CODEX_RESULT.md inside the task workspace.\n",
    )
    return content


def _run_real_worker(
    session,
    project: Project,
    task: Task,
    task_run: TaskRun,
    workspace: TaskWorkspace,
    environment: TaskEnvironment,
) -> str:
    prompt_path = _prompt_path(project.id, task.id)
    last_message_path = _last_message_path(project.id, task.id)
    prompt = _workspace_context_prompt(project, task)
    prompt_path.write_text(prompt, encoding="utf-8")

    if container_runtime_enabled():
        runtime_root = task_runtime_root(project.id, task.id)
        script_path = runtime_root / "run_codex_worker.sh"
        runtime_codex_home_q = shlex.quote(settings.task_container_codex_home_runtime_path)
        script_path.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    "set -eu",
                    f"cleanup_codex_home() {{ rm -rf {runtime_codex_home_q} 2>/dev/null || true; }}",
                    "trap cleanup_codex_home EXIT",
                    *_codex_home_copy_script_lines(),
                    f"export CODEX_HOME={settings.task_container_codex_home_runtime_path}",
                    f"PROMPT=$(cat {container_runtime_file_path('CODEX_PROMPT.md')})",
                    (
                        f"{settings.task_container_codex_command} exec --skip-git-repo-check "
                        f"--sandbox {settings.task_container_codex_sandbox} --output-last-message "
                        f"{container_runtime_file_path('codex_last_message.md')} --color never "
                        f"-C {container_workspace_path()} \"$PROMPT\""
                    ),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return_code = run_command_in_task_container(
            environment,
            task_run,
            f"sh {container_runtime_file_path('run_codex_worker.sh')}",
            timeout_seconds=settings.codex_execution_timeout_seconds,
        )
        if return_code != 0:
            raise RuntimeError(f"Task container Codex worker exited with code {return_code}.")
        if last_message_path.exists():
            return last_message_path.read_text(encoding="utf-8")
        return task_run.stdout or "Codex finished without a final message."

    command = [
        settings.codex_cli_path,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "--output-last-message",
        str(last_message_path),
        "--color",
        "never",
        "-C",
        workspace.workspace_path,
        prompt,
    ]

    if settings.codex_model:
        command[2:2] = ["--model", settings.codex_model]

    process = subprocess.Popen(
        command,
        cwd=workspace.workspace_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    try:
        assert process.stdout is not None
        for line in process.stdout:
            _append_stdout(task_run, line)
            session.commit()
        return_code = process.wait(timeout=settings.codex_execution_timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        raise RuntimeError("Codex execution timed out.")

    if return_code != 0:
        raise RuntimeError(f"Codex exited with code {return_code}.")

    if last_message_path.exists():
        return last_message_path.read_text(encoding="utf-8")

    return task_run.stdout or "Codex finished without a final message."


def _count_task_attempts(session, task_id: str) -> int:
    attempts = session.scalar(
        select(func.count(TaskRun.id)).where(
            TaskRun.task_id == task_id,
            TaskRun.status != "provisioned",
        )
    )
    return int(attempts or 0)


def _blocking_preflight_messages(preflight_result: TaskPreflightResult) -> list[str]:
    return [
        check.message
        for check in preflight_result.checks
        if check.status == "fail" and check.blocking
    ]


def _task_run_age_seconds(task_run: TaskRun) -> float:
    now = utc_now()
    started_at = task_run.started_at
    if started_at.tzinfo is None:
        started_utc = started_at.replace(tzinfo=timezone.utc)
    else:
        started_utc = started_at.astimezone(timezone.utc)
    if now.tzinfo is None:
        now_utc = now.replace(tzinfo=timezone.utc)
    else:
        now_utc = now.astimezone(timezone.utc)
    return max(0.0, (now_utc - started_utc).total_seconds())


def stale_run_recovery_threshold_seconds() -> int:
    return max(
        60,
        settings.codex_execution_timeout_seconds + settings.director_stale_run_grace_seconds,
    )


def recover_stale_task_runs(
    session,
    *,
    trigger: str,
    stale_after_seconds: int | None = None,
) -> list[tuple[str, str, str]]:
    stale_after_seconds = (
        stale_run_recovery_threshold_seconds()
        if stale_after_seconds is None
        else max(0, stale_after_seconds)
    )
    stale_runs = session.scalars(
        select(TaskRun)
        .where(TaskRun.status == "running")
        .order_by(TaskRun.started_at.asc())
    ).all()
    if not stale_runs:
        return []

    affected_project_ids: set[str] = set()
    for stale_run in stale_runs:
        run_age_seconds = _task_run_age_seconds(stale_run)
        if run_age_seconds < stale_after_seconds:
            continue

        task = session.get(Task, stale_run.task_id)
        if task is None:
            continue
        project = session.get(Project, task.project_id)
        if project is None:
            continue

        workspace = session.scalars(
            select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
        ).first()
        environment = session.scalars(
            select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
        ).first()

        _request_run_cancellation(stale_run.id)
        timeout_reason = (
            "Recovered stale task execution after "
            f"{int(run_age_seconds)} seconds "
            f"(threshold {stale_after_seconds}s, trigger={trigger})."
        )
        try:
            _mark_run_stopped(
                session,
                project,
                task,
                stale_run,
                workspace,
                environment,
                status="timed_out",
                reason=timeout_reason,
                actor="director-recovery",
                event_type="task_execution_timed_out",
            )
        except OrchestrationError:
            continue

        auto_retry_summary: str | None = None
        auto_retry_allowed = (
            run_age_seconds
            <= (
                stale_after_seconds
                + settings.director_stale_run_auto_retry_window_seconds
            )
        )
        if auto_retry_allowed:
            try:
                reset_transition = transition_task(
                    session,
                    project,
                    task,
                    "reset",
                    reason="Auto-reset after stale execution recovery.",
                )
                register_task_run_transition(
                    session,
                    task,
                    "reset",
                    workspace,
                    environment,
                    reset_transition.summary,
                )
                auto_retry_summary = reset_transition.summary
                affected_project_ids.add(project.id)
            except OrchestrationError:
                auto_retry_summary = None

        recovery_message = (
            f"Обнаружил зависший запуск задачи «{task.title}» "
            f"и завершил его по таймауту ({int(run_age_seconds)} сек)."
        )
        if auto_retry_summary:
            recovery_message = (
                f"{recovery_message} Выполнил автосброс и вернул задачу в очередь."
            )
        post_director_progress_update(
            session,
            project,
            milestone="stale_run_recovered",
            summary=recovery_message,
            task_id=task.id,
        )
        log_event(
            session,
            project.id,
            "director_stale_run_recovered",
            {
                "task_id": task.id,
                "task_key": task.task_key,
                "task_run_id": stale_run.id,
                "run_age_seconds": int(run_age_seconds),
                "threshold_seconds": stale_after_seconds,
                "trigger": trigger,
                "auto_retry_allowed": auto_retry_allowed,
                "auto_reset": bool(auto_retry_summary),
            },
            task_id=task.id,
        )

    dispatches: list[tuple[str, str, str]] = []
    session.flush()
    for project_id in sorted(affected_project_ids):
        project = session.get(Project, project_id)
        if project is None:
            continue
        dispatch = dispatch_director_next_ready_task(
            session,
            project,
            trigger=f"{trigger}:stale-recovery",
        )
        if dispatch is not None:
            dispatches.append((project.id, dispatch.task_id, dispatch.task_run_id))
    return dispatches


def dispatch_director_next_ready_task(
    session,
    project: Project,
    *,
    trigger: str,
) -> Optional[DirectorDispatch]:
    if not settings.director_auto_run_enabled:
        return None

    with DIRECTOR_DISPATCH_LOCK:
        has_running_task = session.scalars(
            select(Task.id).where(
                Task.project_id == project.id,
                Task.status == "running",
            )
        ).first()
        if has_running_task is not None:
            return None

        ready_tasks = session.scalars(
            select(Task)
            .where(Task.project_id == project.id, Task.status == "ready")
            .order_by(Task.priority.desc(), Task.created_at.asc())
        ).all()
        if not ready_tasks:
            return None

        for ready_task in ready_tasks:
            attempt_count = _count_task_attempts(session, ready_task.id)
            if attempt_count >= settings.director_auto_max_attempts:
                reason = (
                    f"Director auto-run limit reached after {attempt_count} attempts. "
                    "Human review is required."
                )
                if ready_task.status == "ready":
                    transition_task(session, project, ready_task, "block", reason)
                session.add(
                    Message(
                        project_id=project.id,
                        role="director",
                        content=(
                            f"Автозапуск остановлен для задачи '{ready_task.title}': "
                            f"достигнут лимит попыток ({attempt_count})."
                        ),
                    )
                )
                log_event(
                    session,
                    project.id,
                    "director_auto_handoff_required",
                    {
                        "task_id": ready_task.id,
                        "task_key": ready_task.task_key,
                        "attempt_count": attempt_count,
                        "max_attempts": settings.director_auto_max_attempts,
                        "trigger": trigger,
                    },
                    task_id=ready_task.id,
                )
                continue

            preflight_result = build_task_preflight(session, project, ready_task)
            if not preflight_result.ready:
                blocking = _blocking_preflight_messages(preflight_result)
                session.add(
                    Message(
                        project_id=project.id,
                        role="director",
                        content=(
                            f"Автозапуск задачи '{ready_task.title}' остановлен preflight-проверкой: "
                            f"{'; '.join(blocking) if blocking else preflight_result.summary}"
                        ),
                    )
                )
                log_event(
                    session,
                    project.id,
                    "director_auto_dispatch_blocked",
                    {
                        "task_id": ready_task.id,
                        "task_key": ready_task.task_key,
                        "trigger": trigger,
                        "preflight_summary": preflight_result.summary,
                        "blocking_checks": blocking,
                    },
                    task_id=ready_task.id,
                )
                continue

            try:
                task_run = prepare_task_run_for_codex(
                    session,
                    project,
                    ready_task,
                    requested_by="director",
                    requester_role="Director",
                )
            except OrchestrationError as exc:
                session.add(
                    Message(
                        project_id=project.id,
                        role="director",
                        content=(
                            f"Директор не смог автоматически запустить задачу "
                            f"'{ready_task.title}': {exc}"
                        ),
                    )
                )
                log_event(
                    session,
                    project.id,
                    "director_auto_dispatch_blocked",
                    {
                        "task_id": ready_task.id,
                        "task_key": ready_task.task_key,
                        "trigger": trigger,
                        "error": str(exc),
                    },
                    task_id=ready_task.id,
                )
                continue

            post_director_progress_update(
                session,
                project,
                milestone="task_dispatched",
                summary=f"Запустил задачу «{ready_task.title}».",
                task_id=ready_task.id,
            )
            log_event(
                session,
                project.id,
                "director_auto_dispatched",
                {
                    "task_id": ready_task.id,
                    "task_key": ready_task.task_key,
                    "task_run_id": task_run.id,
                    "trigger": trigger,
                },
                task_id=ready_task.id,
            )
            return DirectorDispatch(
                task_id=ready_task.id,
                task_run_id=task_run.id,
                task_title=ready_task.title,
            )

    return None


def _execute_task_run(project_id: str, task_id: str, task_run_id: str) -> None:
    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        task = session.get(Task, task_id)
        task_run = session.get(TaskRun, task_run_id)
        if project is None or task is None or task_run is None:
            return

        ensure_task_runtime(session, project, task)
        workspace = session.scalars(
            select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
        ).first()
        environment = session.scalars(
            select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
        ).first()
        if workspace is None or environment is None:
            raise RuntimeError("Task runtime is not available for Codex execution.")
        if task_run.status != "running":
            return
        if _handle_pending_cancellation(
            session,
            project,
            task,
            task_run,
            workspace,
            environment,
            reason="Task run was cancelled before execution started.",
        ):
            return
        if container_runtime_enabled():
            ensure_task_container(project, task, workspace, environment)
        if _handle_pending_cancellation(
            session,
            project,
            task,
            task_run,
            workspace,
            environment,
            reason="Task run was cancelled before worker dispatch.",
        ):
            return

        log_event(
            session,
            project.id,
            "task_execution_started",
            {
                "task_run_id": task_run.id,
                "worker": "codex",
                "mode": settings.codex_worker_mode,
                "runtime_driver": settings.task_container_driver,
            },
            task_id=task.id,
        )
        session.commit()

        if settings.codex_worker_mode == "mock":
            final_message = _run_mock_worker(
                session, project, task, task_run, workspace, environment
            )
        else:
            final_message = _run_real_worker(
                session, project, task, task_run, workspace, environment
            )
        # Persist worker logs before refresh so we don't drop stdout generated by mock/container runs.
        session.flush()
        session.commit()
        session.refresh(task_run)
        if task_run.status != "running":
            _append_stdout(
                task_run,
                f"\nExecution output ignored because run is {task_run.status}.\n",
            )
            _cleanup_task_container_runtime(
                session,
                project,
                task,
                environment,
                runtime_status=f"container-{task_run.status}-cleaned",
                event_type="task_container_cleaned",
                event_reason=f"post-run:{task_run.status}",
            )
            session.commit()
            return

        result_artifact = _create_result_artifact(session, project, task, final_message)
        _create_workspace_change_summary_artifact(session, project, task, workspace)
        requested_action_count = _apply_worker_action_requests(
            session,
            project,
            task,
            task_run,
            final_message,
        )
        if requested_action_count:
            _append_stdout(
                task_run,
                f"Registered {requested_action_count} worker-requested runtime action(s).\n",
            )
        review_summary = transition_task(session, project, task, "send_to_review")
        workspace.state = "reviewing"
        task_run.status = "review"
        _append_stdout(task_run, f"\n{review_summary.summary}\n")
        log_event(
            session,
            project.id,
            "task_execution_completed",
            {"task_run_id": task_run.id, "worker": "codex"},
            task_id=task.id,
        )
        run_task_review(session, project, task, task_run, result_artifact, workspace)
        _cleanup_task_container_runtime(
            session,
            project,
            task,
            environment,
            runtime_status="container-cleaned",
            event_type="task_container_cleaned",
            event_reason="completed",
        )
        next_dispatch = dispatch_director_next_ready_task(
            session,
            project,
            trigger="task_review_completed",
        )
        session.commit()
        if next_dispatch is not None:
            start_codex_execution(project.id, next_dispatch.task_id, next_dispatch.task_run_id)
    except Exception as exc:
        session.rollback()
        retry_session = SessionLocal()
        try:
            project = retry_session.get(Project, project_id)
            task = retry_session.get(Task, task_id)
            task_run = retry_session.get(TaskRun, task_run_id)
            if project is None or task is None or task_run is None:
                return
            workspace = retry_session.scalars(
                select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
            ).first()
            environment = retry_session.scalars(
                select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
            ).first()

            if _is_run_cancellation_requested(task_run.id):
                if task_run.status == "running":
                    _mark_run_stopped(
                        retry_session,
                        project,
                        task,
                        task_run,
                        workspace,
                        environment,
                        status="cancelled",
                        reason=str(exc),
                        actor="worker",
                        event_type="task_execution_cancelled",
                    )
                else:
                    _cleanup_task_container_runtime(
                        retry_session,
                        project,
                        task,
                        environment,
                        runtime_status=f"container-{task_run.status}-cleaned",
                        event_type="task_container_cleaned",
                        event_reason="terminal-state-recovery",
                    )
                retry_session.commit()
                return

            if task_run.status in {"cancelled", "timed_out"}:
                _cleanup_task_container_runtime(
                    retry_session,
                    project,
                    task,
                    environment,
                    runtime_status=f"container-{task_run.status}-cleaned",
                    event_type="task_container_cleaned",
                    event_reason="terminal-state-recovery",
                )
                retry_session.commit()
                return

            task_run.status = "failed"
            task_run.finished_at = utc_now()
            task_run.stderr = str(exc)
            if workspace is not None:
                workspace.state = "failed"
            if task.status == "running":
                failure_summary = fail_task_execution(retry_session, project, task, str(exc))
                _append_stdout(task_run, f"\n{failure_summary}\n")
            _cleanup_task_container_runtime(
                retry_session,
                project,
                task,
                environment,
                runtime_status="container-failed-cleaned",
                event_type="task_container_cleaned",
                event_reason=f"failed:{exc}",
            )
            log_event(
                retry_session,
                project.id,
                "task_execution_failed",
                {"task_run_id": task_run.id, "worker": "codex", "error": str(exc)},
                task_id=task.id,
            )
            retry_session.commit()
        finally:
            retry_session.close()
    finally:
        _clear_run_cancellation(task_run_id)
        session.close()


def build_task_preflight(session, project: Project, task: Task) -> TaskPreflightResult:
    ensure_task_runtime(session, project, task)
    workspace = session.scalars(
        select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
    ).first()
    environment = session.scalars(
        select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
    ).first()
    if workspace is None or environment is None:
        raise OrchestrationError("Task runtime is not available for preflight checks.")
    return evaluate_task_preflight(workspace, environment)


def cancel_codex_execution(
    session,
    project: Project,
    task: Task,
    task_run: TaskRun,
    *,
    actor: str,
    reason: Optional[str] = None,
) -> str:
    workspace = session.scalars(
        select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
    ).first()
    environment = session.scalars(
        select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
    ).first()

    _request_run_cancellation(task_run.id)
    stop_reason = reason or "Task execution was cancelled by operator."
    return _mark_run_stopped(
        session,
        project,
        task,
        task_run,
        workspace,
        environment,
        status="cancelled",
        reason=stop_reason,
        actor=actor,
        event_type="task_execution_cancelled",
    )


def _watch_task_run_timeout(project_id: str, task_id: str, task_run_id: str) -> None:
    timeout_seconds = settings.codex_execution_timeout_seconds
    if timeout_seconds <= 0:
        return
    time.sleep(timeout_seconds + 1)

    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        task = session.get(Task, task_id)
        task_run = session.get(TaskRun, task_run_id)
        if project is None or task is None or task_run is None:
            return
        if task_run.status != "running":
            return

        workspace = session.scalars(
            select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
        ).first()
        environment = session.scalars(
            select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
        ).first()
        _request_run_cancellation(task_run.id)
        timeout_reason = (
            f"Execution exceeded timeout of {timeout_seconds} seconds."
        )
        _mark_run_stopped(
            session,
            project,
            task,
            task_run,
            workspace,
            environment,
            status="timed_out",
            reason=timeout_reason,
            actor="watchdog",
            event_type="task_execution_timed_out",
        )
        session.commit()
    finally:
        session.close()


def start_codex_execution(project_id: str, task_id: str, task_run_id: str) -> None:
    thread = threading.Thread(
        target=_execute_task_run,
        args=(project_id, task_id, task_run_id),
        daemon=True,
    )
    thread.start()
    timeout_thread = threading.Thread(
        target=_watch_task_run_timeout,
        args=(project_id, task_id, task_run_id),
        daemon=True,
    )
    timeout_thread.start()


def prepare_task_run_for_codex(
    session,
    project: Project,
    task: Task,
    *,
    requested_by: str,
    requester_role: str,
) -> TaskRun:
    existing_running = session.scalars(
        select(TaskRun)
        .where(TaskRun.task_id == task.id, TaskRun.status == "running")
        .order_by(TaskRun.started_at.desc())
    ).first()
    if existing_running is not None:
        raise OrchestrationError("Task already has an active execution run.")

    ensure_task_runtime(session, project, task)
    workspace = session.scalars(
        select(TaskWorkspace).where(TaskWorkspace.task_id == task.id)
    ).first()
    environment = session.scalars(
        select(TaskEnvironment).where(TaskEnvironment.task_id == task.id)
    ).first()
    if workspace is None or environment is None:
        raise OrchestrationError("Task runtime is not provisioned.")

    start_policy = evaluate_policy_action(
        session,
        project,
        "task.start",
        task=task,
        requested_by=requested_by,
        requester_role=requester_role,
        metadata={"task_status": task.status},
    )
    write_policy = evaluate_policy_action(
        session,
        project,
        "runtime.write_workspace",
        task=task,
        requested_by=requested_by,
        requester_role=requester_role,
        metadata={
            "target_path": workspace.workspace_path,
            "workspace_path": workspace.workspace_path,
        },
    )
    if not start_policy.allowed or not write_policy.allowed:
        raise OrchestrationError(
            "Task execution was rejected by policy or still requires approval."
        )

    transition_task(session, project, task, "start")
    workspace.state = "running"
    task_run = TaskRun(
        task_id=task.id,
        status="running",
        started_at=utc_now(),
        worktree_path=workspace.workspace_path,
        environment_name=environment.name,
        stdout="Codex execution queued.\n",
        stderr=None,
    )
    session.add(task_run)
    session.flush()
    log_event(
        session,
        project.id,
        "task_execution_queued",
        {"task_run_id": task_run.id, "worker": "codex", "mode": settings.codex_worker_mode},
        task_id=task.id,
    )
    return task_run
