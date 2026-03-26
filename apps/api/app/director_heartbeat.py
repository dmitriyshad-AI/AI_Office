from __future__ import annotations

import logging
import threading
from typing import Optional

from sqlalchemy import select

from app.codex_worker import (
    dispatch_director_next_ready_task,
    recover_stale_task_runs,
    start_codex_execution,
)
from app.config import get_settings
from app.db import SessionLocal
from app.models import Project, Task


settings = get_settings()
logger = logging.getLogger(__name__)


class DirectorHeartbeatService:
    def __init__(self, poll_seconds: int) -> None:
        self._poll_seconds = max(1, poll_seconds)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if not settings.director_auto_run_enabled or not settings.director_heartbeat_enabled:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="director-heartbeat",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop_event.set()
        if thread is not None:
            thread.join(timeout=max(1, self._poll_seconds))
        self._stop_event.clear()

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _run_loop(self) -> None:
        self._safe_tick(recover_immediately=True)
        while not self._stop_event.wait(self._poll_seconds):
            self._safe_tick()

    def _safe_tick(self, *, recover_immediately: bool = False) -> None:
        try:
            tick_director_queue_once(
                trigger="heartbeat",
                recover_immediately=recover_immediately,
            )
        except Exception:
            logger.exception("Director heartbeat tick failed")


def tick_director_queue_once(
    *,
    trigger: str = "heartbeat",
    recover_immediately: bool = False,
) -> int:
    if not settings.director_auto_run_enabled:
        return 0

    session = SessionLocal()
    dispatched_runs: list[tuple[str, str, str]] = []
    try:
        recovered_dispatches = recover_stale_task_runs(
            session,
            trigger=trigger,
            stale_after_seconds=(0 if recover_immediately else None),
        )
        dispatched_runs.extend(recovered_dispatches)
        session.commit()

        remaining_slots = max(
            0,
            settings.director_heartbeat_max_dispatch_per_tick - len(dispatched_runs),
        )
        if remaining_slots == 0:
            return len(dispatched_runs)

        project_ids = session.scalars(
            select(Project.id)
            .join(Task, Task.project_id == Project.id)
            .where(Task.status == "ready")
            .group_by(Project.id)
            .order_by(Project.updated_at.desc())
        ).all()
        for project_id in project_ids:
            if remaining_slots <= 0:
                break
            project = session.get(Project, project_id)
            if project is None:
                continue
            try:
                dispatch = dispatch_director_next_ready_task(
                    session,
                    project,
                    trigger=trigger,
                )
                session.commit()
            except Exception:
                session.rollback()
                logger.exception(
                    "Director heartbeat failed to evaluate project %s",
                    project_id,
                )
                continue
            if dispatch is None:
                continue
            dispatched_runs.append(
                (project.id, dispatch.task_id, dispatch.task_run_id)
            )
            remaining_slots -= 1
    finally:
        session.close()

    for project_id, task_id, task_run_id in dispatched_runs:
        start_codex_execution(project_id, task_id, task_run_id)
    return len(dispatched_runs)


director_heartbeat_service = DirectorHeartbeatService(
    poll_seconds=settings.director_heartbeat_poll_seconds
)
