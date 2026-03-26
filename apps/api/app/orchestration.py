from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Agent, EventLog, Project, Task, TaskDependency


class OrchestrationError(ValueError):
    pass


@dataclass
class TransitionResult:
    task: Task
    summary: str


def log_event(
    session: Session,
    project_id: str,
    event_type: str,
    payload: dict,
    task_id: Optional[str] = None,
) -> None:
    session.add(
        EventLog(
            project_id=project_id,
            task_id=task_id,
            event_type=event_type,
            payload=payload,
        )
    )


def load_project_tasks(session: Session, project_id: str) -> list[Task]:
    return session.scalars(
        select(Task)
        .where(Task.project_id == project_id)
        .options(selectinload(Task.assigned_agent))
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()


def load_dependency_map(session: Session, project_id: str) -> dict[str, list[str]]:
    dependencies = session.scalars(
        select(TaskDependency).where(TaskDependency.project_id == project_id)
    ).all()
    dependency_map: dict[str, list[str]] = {}
    for dependency in dependencies:
        dependency_map.setdefault(dependency.task_id, []).append(dependency.depends_on_task_id)
    return dependency_map


def dependency_ids_for_task(
    session: Session,
    project_id: str,
    task_id: str,
) -> list[str]:
    dependency_map = load_dependency_map(session, project_id)
    return dependency_map.get(task_id, [])


def dependencies_satisfied(
    task: Task,
    tasks_by_id: dict[str, Task],
    dependency_map: dict[str, list[str]],
) -> bool:
    for dependency_id in dependency_map.get(task.id, []):
        dependency_task = tasks_by_id.get(dependency_id)
        if dependency_task is None or dependency_task.status != "done":
            return False
    return True


def initialize_task_graph(session: Session, project: Project) -> None:
    tasks = load_project_tasks(session, project.id)
    dependency_map = load_dependency_map(session, project.id)
    tasks_by_id = {task.id: task for task in tasks}

    for task in tasks:
        next_status = "ready" if dependencies_satisfied(task, tasks_by_id, dependency_map) else "planned"
        task.status = next_status
        if next_status == "ready":
            log_event(
                session,
                project.id,
                "task_ready",
                {
                    "task_key": task.task_key,
                    "assigned_role": task.assigned_agent.role if task.assigned_agent else None,
                },
                task_id=task.id,
            )

    sync_agent_statuses(session, project)
    sync_project_status(session, project)


def activate_ready_tasks(session: Session, project: Project) -> list[Task]:
    tasks = load_project_tasks(session, project.id)
    dependency_map = load_dependency_map(session, project.id)
    tasks_by_id = {task.id: task for task in tasks}
    newly_ready: list[Task] = []

    for task in tasks:
        if task.status != "planned":
            continue
        if not dependencies_satisfied(task, tasks_by_id, dependency_map):
            continue
        task.status = "ready"
        newly_ready.append(task)
        log_event(
            session,
            project.id,
            "task_ready",
            {
                "task_key": task.task_key,
                "assigned_role": task.assigned_agent.role if task.assigned_agent else None,
            },
            task_id=task.id,
        )

    return newly_ready


def sync_agent_statuses(session: Session, project: Project) -> None:
    tasks = load_project_tasks(session, project.id)
    agents = session.scalars(
        select(Agent).where(Agent.project_id == project.id).order_by(Agent.role.asc())
    ).all()

    for agent in agents:
        old_status = agent.status
        old_title = agent.current_task_title
        assigned_tasks = [task for task in tasks if task.assigned_agent_id == agent.id]

        if agent.role == "Director":
            if any(task.status == "running" for task in tasks):
                new_status = "running"
                new_title = "Monitoring active task execution"
            elif any(task.status == "review" for task in tasks):
                new_status = "reviewing"
                new_title = "Validating execution outcomes"
            elif any(task.status == "blocked" for task in tasks):
                new_status = "blocked"
                new_title = "Waiting on blocked task resolution"
            elif any(task.status == "ready" for task in tasks):
                new_status = "ready"
                new_title = "Tasks are ready for execution"
            elif any(task.status == "planned" for task in tasks):
                new_status = "planning"
                new_title = "Coordinating project plan"
            elif any(task.status == "done" for task in tasks):
                new_status = "done"
                new_title = "Project plan completed"
            else:
                new_status = "idle"
                new_title = None
        else:
            running_task = next((task for task in assigned_tasks if task.status == "running"), None)
            blocked_task = next((task for task in assigned_tasks if task.status == "blocked"), None)
            review_task = next((task for task in assigned_tasks if task.status == "review"), None)
            ready_task = next((task for task in assigned_tasks if task.status == "ready"), None)
            planned_task = next((task for task in assigned_tasks if task.status == "planned"), None)
            done_task = next((task for task in assigned_tasks if task.status == "done"), None)

            if running_task is not None:
                new_status = "running"
                new_title = running_task.title
            elif blocked_task is not None:
                new_status = "blocked"
                new_title = blocked_task.title
            elif review_task is not None:
                new_status = "reviewing"
                new_title = review_task.title
            elif ready_task is not None:
                new_status = "ready"
                new_title = ready_task.title
            elif planned_task is not None:
                new_status = "idle"
                new_title = f"Waiting for dependencies: {planned_task.title}"
            elif done_task is not None:
                new_status = "done"
                new_title = done_task.title
            else:
                new_status = "idle"
                new_title = None

        if old_status != new_status or old_title != new_title:
            agent.status = new_status
            agent.current_task_title = new_title
            log_event(
                session,
                project.id,
                "agent_status_changed",
                {
                    "agent_id": agent.id,
                    "agent_role": agent.role,
                    "from_status": old_status,
                    "to_status": new_status,
                    "current_task_title": new_title,
                },
            )


def sync_project_status(session: Session, project: Project) -> None:
    if project.status == "archived":
        return

    tasks = load_project_tasks(session, project.id)
    old_status = project.status

    if not tasks:
        new_status = "draft"
    elif all(task.status == "done" for task in tasks):
        new_status = "done"
    elif any(task.status == "running" for task in tasks):
        new_status = "running"
    elif any(task.status == "review" for task in tasks):
        new_status = "review"
    elif any(task.status == "blocked" for task in tasks):
        new_status = "blocked"
    elif any(task.status == "ready" for task in tasks):
        new_status = "ready"
    else:
        new_status = "planning"

    if old_status != new_status:
        project.status = new_status
        log_event(
            session,
            project.id,
            "project_status_changed",
            {"from_status": old_status, "to_status": new_status},
        )


def transition_task(
    session: Session,
    project: Project,
    task: Task,
    action: str,
    reason: Optional[str] = None,
) -> TransitionResult:
    summary: str

    if action == "start":
        if task.status != "ready":
            raise OrchestrationError("Only ready tasks can be started.")
        task.status = "running"
        log_event(
            session,
            project.id,
            "task_started",
            {"task_key": task.task_key, "assigned_role": task.assigned_agent.role if task.assigned_agent else None},
            task_id=task.id,
        )
        summary = f"Task '{task.title}' moved to running."
    elif action == "send_to_review":
        if task.status != "running":
            raise OrchestrationError("Only running tasks can be sent to review.")
        task.status = "review"
        log_event(
            session,
            project.id,
            "task_sent_to_review",
            {"task_key": task.task_key},
            task_id=task.id,
        )
        summary = f"Task '{task.title}' moved to review."
    elif action == "approve_review":
        if task.status != "review":
            raise OrchestrationError("Only review tasks can be approved.")
        task.status = "done"
        log_event(
            session,
            project.id,
            "task_review_approved",
            {"task_key": task.task_key, "reason": reason or ""},
            task_id=task.id,
        )
        log_event(
            session,
            project.id,
            "task_completed",
            {"task_key": task.task_key},
            task_id=task.id,
        )
        newly_ready = activate_ready_tasks(session, project)
        if newly_ready:
            summary = (
                f"Review approved for '{task.title}'. {len(newly_ready)} dependent task(s) became ready."
            )
        else:
            summary = f"Review approved for '{task.title}'."
    elif action == "request_rework":
        if task.status != "review":
            raise OrchestrationError("Only review tasks can be returned for rework.")
        task.status = "ready"
        log_event(
            session,
            project.id,
            "task_review_changes_requested",
            {"task_key": task.task_key, "reason": reason or ""},
            task_id=task.id,
        )
        summary = f"Review requested changes for '{task.title}'. Task returned to ready."
    elif action == "complete":
        if task.status != "running":
            raise OrchestrationError("Only running tasks can be completed.")
        task.status = "done"
        log_event(
            session,
            project.id,
            "task_completed",
            {"task_key": task.task_key},
            task_id=task.id,
        )
        newly_ready = activate_ready_tasks(session, project)
        if newly_ready:
            summary = (
                f"Task '{task.title}' completed. {len(newly_ready)} dependent task(s) became ready."
            )
        else:
            summary = f"Task '{task.title}' completed."
    elif action == "block":
        if task.status == "done":
            raise OrchestrationError("Completed tasks cannot be blocked.")
        previous_status = task.status
        task.status = "blocked"
        log_event(
            session,
            project.id,
            "task_blocked",
            {"task_key": task.task_key, "from_status": previous_status, "reason": reason or "No reason provided"},
            task_id=task.id,
        )
        summary = f"Task '{task.title}' was blocked."
    elif action == "reset":
        if task.status not in {"blocked", "failed"}:
            raise OrchestrationError("Only blocked or failed tasks can be reset.")
        tasks = load_project_tasks(session, project.id)
        dependency_map = load_dependency_map(session, project.id)
        tasks_by_id = {candidate.id: candidate for candidate in tasks}
        next_status = "ready" if dependencies_satisfied(task, tasks_by_id, dependency_map) else "planned"
        task.status = next_status
        log_event(
            session,
            project.id,
            "task_reset",
            {"task_key": task.task_key, "to_status": next_status},
            task_id=task.id,
        )
        if next_status == "ready":
            log_event(
                session,
                project.id,
                "task_ready",
                {"task_key": task.task_key, "assigned_role": task.assigned_agent.role if task.assigned_agent else None},
                task_id=task.id,
            )
        summary = f"Task '{task.title}' was reset to {next_status}."
    else:
        raise OrchestrationError(f"Unsupported task action: {action}")

    sync_agent_statuses(session, project)
    sync_project_status(session, project)
    return TransitionResult(task=task, summary=summary)
