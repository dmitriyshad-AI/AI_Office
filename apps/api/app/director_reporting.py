from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.models import ApprovalRequest, Message, Project, Task
from app.orchestration import log_event


@dataclass(frozen=True)
class ProgressSnapshot:
    total_tasks: int
    done_tasks: int
    running_tasks: int
    review_tasks: int
    ready_tasks: int
    blocked_tasks: int
    failed_tasks: int
    pending_approvals: int
    active_task_title: str | None
    next_task_title: str | None


def _load_progress_snapshot(session, project_id: str) -> ProgressSnapshot:
    tasks = session.scalars(
        select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()
    total = len(tasks)
    done = sum(1 for task in tasks if task.status == "done")
    running = sum(1 for task in tasks if task.status == "running")
    review = sum(1 for task in tasks if task.status == "review")
    ready = sum(1 for task in tasks if task.status == "ready")
    blocked = sum(1 for task in tasks if task.status == "blocked")
    failed = sum(1 for task in tasks if task.status == "failed")
    active_task = next((task.title for task in tasks if task.status == "running"), None)
    next_task = next((task.title for task in tasks if task.status == "ready"), None)
    pending_approvals = len(
        session.scalars(
            select(ApprovalRequest.id).where(
                ApprovalRequest.project_id == project_id,
                ApprovalRequest.status == "pending",
            )
        ).all()
    )
    return ProgressSnapshot(
        total_tasks=total,
        done_tasks=done,
        running_tasks=running,
        review_tasks=review,
        ready_tasks=ready,
        blocked_tasks=blocked,
        failed_tasks=failed,
        pending_approvals=pending_approvals,
        active_task_title=active_task,
        next_task_title=next_task,
    )


def post_director_progress_update(
    session,
    project: Project,
    *,
    milestone: str,
    summary: str,
    task_id: str | None = None,
) -> None:
    snapshot = _load_progress_snapshot(session, project.id)
    total = snapshot.total_tasks
    done = snapshot.done_tasks
    percent = int(round((done / total) * 100)) if total > 0 else 0

    message_parts = [f"{summary}"]
    message_parts.append(f"Прогресс: {done}/{total} ({percent}%).")
    if snapshot.active_task_title:
        message_parts.append(f"Сейчас в работе: «{snapshot.active_task_title}».")
    elif snapshot.next_task_title:
        message_parts.append(f"Следующая задача: «{snapshot.next_task_title}».")
    if snapshot.pending_approvals > 0:
        message_parts.append(
            f"Требуют вашего решения: {snapshot.pending_approvals}."
        )
    if snapshot.blocked_tasks > 0:
        message_parts.append(f"Заблокировано задач: {snapshot.blocked_tasks}.")
    if snapshot.failed_tasks > 0:
        message_parts.append(f"С ошибкой: {snapshot.failed_tasks}.")

    content = " ".join(message_parts)
    session.add(
        Message(
            project_id=project.id,
            role="director",
            content=content,
        )
    )
    log_event(
        session,
        project.id,
        "director_progress_update",
        {
            "milestone": milestone,
            "summary": summary,
            "progress": {
                "done": snapshot.done_tasks,
                "total": snapshot.total_tasks,
                "percent": percent,
                "running": snapshot.running_tasks,
                "review": snapshot.review_tasks,
                "ready": snapshot.ready_tasks,
                "blocked": snapshot.blocked_tasks,
                "failed": snapshot.failed_tasks,
                "pending_approvals": snapshot.pending_approvals,
            },
            "active_task_title": snapshot.active_task_title,
            "next_task_title": snapshot.next_task_title,
        },
        task_id=task_id,
    )
