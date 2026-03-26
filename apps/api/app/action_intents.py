from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActionIntent, ApprovalRequest, Artifact, Project, Task, TaskRun, utc_now
from app.orchestration import log_event


@dataclass
class ActionIntentExecutionResult:
    action_intent: ActionIntent
    summary: str


def find_action_intent_for_approval_request(
    session: Session,
    approval_request_id: str,
) -> Optional[ActionIntent]:
    return session.scalars(
        select(ActionIntent)
        .where(ActionIntent.approval_request_id == approval_request_id)
        .order_by(ActionIntent.created_at.desc())
    ).first()


def create_action_intent(
    session: Session,
    project: Project,
    action_key: str,
    *,
    task: Optional[Task],
    task_run: Optional[TaskRun],
    approval_request: ApprovalRequest,
    requested_by: str,
    metadata: dict,
) -> ActionIntent:
    existing = find_action_intent_for_approval_request(session, approval_request.id)
    if existing is not None:
        return existing

    action_intent = ActionIntent(
        project_id=project.id,
        task_id=task.id if task is not None else None,
        task_run_id=task_run.id if task_run is not None else None,
        approval_request_id=approval_request.id,
        action_key=action_key,
        dispatcher_kind="runtime-dispatcher",
        status="pending_approval",
        requested_by=requested_by,
        payload=metadata,
        execution_summary="Waiting for human approval before this action can continue.",
        attempt_count=0,
        max_attempts=max(1, int(metadata.get("max_attempts", 3) or 3)),
    )
    session.add(action_intent)
    session.flush()
    log_event(
        session,
        project.id,
        "action_intent_created",
        {
            "action_intent_id": action_intent.id,
            "action_key": action_key,
            "status": action_intent.status,
        },
        task_id=action_intent.task_id,
    )
    return action_intent


def get_action_intent(session: Session, action_intent_id: str) -> Optional[ActionIntent]:
    return session.get(ActionIntent, action_intent_id)


def _intent_summary(action_intent: ActionIntent) -> str:
    if action_intent.action_key == "runtime.host_access":
        target_path = action_intent.payload.get("target_path", "host path")
        return f"Host access intent was resumed and recorded for {target_path}."
    if action_intent.action_key == "runtime.secret_write":
        return "Secret write intent was resumed and recorded for the requested secret target."
    if action_intent.action_key == "runtime.install_package":
        package_name = action_intent.payload.get("package_name", "package")
        registry = action_intent.payload.get("registry", "registry")
        return f"Package install override intent resumed for {package_name} from {registry}."
    return f"Action intent '{action_intent.action_key}' resumed successfully."


def _write_action_intent_artifact(
    session: Session,
    project: Project,
    action_intent: ActionIntent,
    summary: str,
) -> None:
    artifact = Artifact(
        project_id=project.id,
        task_id=action_intent.task_id,
        kind="action_intent_result",
        title=f"Action intent result for {action_intent.action_key}",
        content=summary,
    )
    session.add(artifact)
    session.flush()
    log_event(
        session,
        project.id,
        "artifact_created",
        {"artifact_id": artifact.id, "kind": artifact.kind, "title": artifact.title},
        task_id=action_intent.task_id,
    )


def _begin_dispatch_run(
    session: Session,
    action_intent: ActionIntent,
    workspace_path: Optional[str],
) -> Optional[TaskRun]:
    if action_intent.task_id is None:
        return None

    dispatch_run = TaskRun(
        task_id=action_intent.task_id,
        status="running",
        started_at=utc_now(),
        worktree_path=workspace_path,
        environment_name=f"intent:{action_intent.action_key}",
        stdout=f"Starting runtime dispatcher for {action_intent.action_key}.\n",
        stderr=None,
    )
    session.add(dispatch_run)
    session.flush()
    action_intent.dispatch_task_run_id = dispatch_run.id
    return dispatch_run


def _append_dispatch_log(dispatch_run: Optional[TaskRun], chunk: str) -> None:
    if dispatch_run is None:
        return
    dispatch_run.stdout = f"{dispatch_run.stdout or ''}{chunk}"


def _dispatcher_root(project_id: str, task_id: Optional[str], action_intent_id: str) -> Path:
    if task_id is not None:
        from app.runtime import task_runtime_root

        root = task_runtime_root(project_id, task_id) / "intent-results"
    else:
        from app.runtime import runtime_root_path

        root = runtime_root_path() / "projects" / project_id / "intents"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{action_intent_id}.json"


def _simulate_dispatch_failure(action_intent: ActionIntent) -> None:
    failures_remaining = int(action_intent.payload.get("simulate_failures_remaining", 0) or 0)
    if failures_remaining <= 0:
        return
    action_intent.payload = {
        **action_intent.payload,
        "simulate_failures_remaining": failures_remaining - 1,
    }
    raise RuntimeError("Simulated dispatcher failure for recovery testing.")


def _write_dispatch_payload(
    action_intent: ActionIntent,
    *,
    actor: str,
    status: str,
) -> str:
    output_path = _dispatcher_root(action_intent.project_id, action_intent.task_id, action_intent.id)
    payload = {
        "action_intent_id": action_intent.id,
        "action_key": action_intent.action_key,
        "status": status,
        "actor": actor,
        "requested_by": action_intent.requested_by,
        "attempt_count": action_intent.attempt_count,
        "payload": action_intent.payload,
        "created_at": action_intent.created_at.isoformat(),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output_path)


def _next_backoff_seconds(attempt_count: int) -> int:
    return min(30 * (2 ** max(attempt_count - 1, 0)), 300)


def _dispatch_action_intent(
    session: Session,
    project: Project,
    action_intent: ActionIntent,
    *,
    actor: str,
    manual_retry: bool = False,
) -> ActionIntentExecutionResult:
    workspace_path = None
    if action_intent.task_id is not None:
        from app.runtime import ensure_task_runtime

        task = session.get(Task, action_intent.task_id)
        if task is not None:
            workspace = ensure_task_runtime(session, project, task)
            workspace_path = workspace.workspace_path

    dispatch_run = _begin_dispatch_run(session, action_intent, workspace_path)
    action_intent.attempt_count += 1
    action_intent.status = "executing"
    action_intent.last_error = None
    action_intent.next_retry_at = None
    action_intent.execution_summary = (
        "Manual retry started." if manual_retry else "Human approval granted. Resuming action intent."
    )
    log_event(
        session,
        project.id,
        "action_intent_dispatch_started",
        {
            "action_intent_id": action_intent.id,
            "action_key": action_intent.action_key,
            "attempt_count": action_intent.attempt_count,
            "manual_retry": manual_retry,
        },
        task_id=action_intent.task_id,
    )

    try:
        _simulate_dispatch_failure(action_intent)
        output_path = _write_dispatch_payload(action_intent, actor=actor, status="completed")
        summary = _intent_summary(action_intent)
        _append_dispatch_log(dispatch_run, f"Dispatcher wrote payload to {output_path}.\n{summary}\n")

        if dispatch_run is not None:
            dispatch_run.status = "done"
            dispatch_run.finished_at = utc_now()

        action_intent.status = "completed"
        action_intent.execution_summary = summary
        action_intent.completed_at = utc_now()
        _write_action_intent_artifact(session, project, action_intent, summary)
        log_event(
            session,
            project.id,
            "action_intent_completed",
            {
                "action_intent_id": action_intent.id,
                "action_key": action_intent.action_key,
                "dispatch_task_run_id": dispatch_run.id if dispatch_run is not None else None,
            },
            task_id=action_intent.task_id,
        )
        return ActionIntentExecutionResult(action_intent=action_intent, summary=summary)
    except Exception as exc:
        if dispatch_run is not None:
            dispatch_run.status = "failed"
            dispatch_run.finished_at = utc_now()
            dispatch_run.stderr = str(exc)
            _append_dispatch_log(dispatch_run, f"Dispatcher failed: {exc}\n")

        action_intent.last_error = str(exc)
        action_intent.completed_at = None

        if action_intent.attempt_count < action_intent.max_attempts:
            backoff_seconds = _next_backoff_seconds(action_intent.attempt_count)
            action_intent.status = "retry_scheduled"
            action_intent.next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
            action_intent.execution_summary = (
                f"Dispatch failed and retry was scheduled in {backoff_seconds} seconds."
            )
            log_event(
                session,
                project.id,
                "action_intent_retry_scheduled",
                {
                    "action_intent_id": action_intent.id,
                    "action_key": action_intent.action_key,
                    "attempt_count": action_intent.attempt_count,
                    "next_retry_at": action_intent.next_retry_at.isoformat(),
                    "error": str(exc),
                },
                task_id=action_intent.task_id,
            )
            return ActionIntentExecutionResult(
                action_intent=action_intent,
                summary=action_intent.execution_summary,
            )

        action_intent.status = "failed"
        action_intent.execution_summary = (
            f"Dispatch failed after {action_intent.attempt_count} attempts: {exc}"
        )
        action_intent.completed_at = utc_now()
        log_event(
            session,
            project.id,
            "action_intent_failed",
            {
                "action_intent_id": action_intent.id,
                "action_key": action_intent.action_key,
                "error": str(exc),
            },
            task_id=action_intent.task_id,
        )
        return ActionIntentExecutionResult(
            action_intent=action_intent,
            summary=action_intent.execution_summary,
        )


def reject_action_intent(
    session: Session,
    project: Project,
    approval_request: ApprovalRequest,
    summary: str,
) -> Optional[ActionIntentExecutionResult]:
    action_intent = find_action_intent_for_approval_request(session, approval_request.id)
    if action_intent is None:
        return None

    action_intent.status = "rejected"
    action_intent.execution_summary = summary
    action_intent.last_error = summary
    action_intent.next_retry_at = None
    action_intent.completed_at = utc_now()
    log_event(
        session,
        project.id,
        "action_intent_rejected",
        {
            "action_intent_id": action_intent.id,
            "action_key": action_intent.action_key,
        },
        task_id=action_intent.task_id,
    )
    return ActionIntentExecutionResult(action_intent=action_intent, summary=summary)


def resume_action_intent(
    session: Session,
    project: Project,
    approval_request: ApprovalRequest,
) -> Optional[ActionIntentExecutionResult]:
    action_intent = find_action_intent_for_approval_request(session, approval_request.id)
    if action_intent is None:
        return None

    log_event(
        session,
        project.id,
        "action_intent_resumed",
        {
            "action_intent_id": action_intent.id,
            "action_key": action_intent.action_key,
        },
        task_id=action_intent.task_id,
    )
    return _dispatch_action_intent(session, project, action_intent, actor="human")


def retry_action_intent(
    session: Session,
    project: Project,
    action_intent: ActionIntent,
    *,
    actor: str,
    ignore_backoff: bool = True,
) -> ActionIntentExecutionResult:
    if action_intent.project_id != project.id:
        raise ValueError("Action intent does not belong to the project.")
    if action_intent.status not in {"retry_scheduled", "failed"}:
        raise ValueError("Only failed or retry-scheduled action intents can be retried.")
    if (
        not ignore_backoff
        and action_intent.next_retry_at is not None
        and action_intent.next_retry_at > utc_now()
    ):
        raise ValueError("Action intent is still waiting for its retry backoff window.")

    return _dispatch_action_intent(
        session,
        project,
        action_intent,
        actor=actor,
        manual_retry=True,
    )
