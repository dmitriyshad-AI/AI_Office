import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.reviewer as reviewer_module  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import Agent, Artifact, Message, Project, Task, TaskReview, TaskRun, TaskWorkspace  # noqa: E402
from app.reviewer import _build_findings, _criterion_covered, run_task_review  # noqa: E402


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def create_review_bundle(session):
    project = Project(name="Office", description="Review test")
    reviewer = Agent(
        project=project,
        role="QAReviewer",
        name="QA",
        specialization="Review",
    )
    task = Task(
        project=project,
        assigned_agent=reviewer,
        task_key="task-review",
        title="Сделать экран помощи",
        brief="Нужен понятный экран помощи",
        acceptance_criteria=["экран помощи", "русский язык", "понятный сценарий"],
        status="review",
    )
    workspace = TaskWorkspace(
        project=project,
        task=task,
        root_path="/tmp/runtime-root",
        workspace_path="/tmp/workspace",
        source_root_path="/tmp/source",
        state="reviewing",
    )
    task_run = TaskRun(
        task=task,
        status="review",
        stdout="worker summary",
        stderr=None,
    )
    session.add_all([project, reviewer, task, workspace, task_run])
    session.commit()
    return project, task, task_run, workspace


def test_reviewer_helpers_and_review_flow(monkeypatch):
    content = "Экран помощи на русском языке объясняет сценарий работы и показывает экран помощи."
    assert _criterion_covered("экран помощи", content) is True
    assert _criterion_covered("", content) is True

    short_findings = _build_findings(
        SimpleNamespace(acceptance_criteria=["экран помощи"]),
        SimpleNamespace(stderr="boom"),
        "todo",
    )
    severities = {item.severity for item in short_findings}
    assert "high" in severities
    assert "medium" in severities

    session = make_session()
    project, task, task_run, workspace = create_review_bundle(session)
    result_artifact = Artifact(
        project_id=project.id,
        task_id=task.id,
        kind="codex_result",
        title="Result",
        content=(
            "Экран помощи на русском языке объясняет понятный сценарий работы, "
            "показывает первый шаг, второй шаг и типовые ошибки для владельца."
        ),
    )
    session.add(result_artifact)
    session.commit()

    monkeypatch.setattr(reviewer_module, "settings", SimpleNamespace(codex_worker_mode="mock"))
    monkeypatch.setattr(reviewer_module, "transition_task", lambda *args, **kwargs: SimpleNamespace(summary="review approved"))
    monkeypatch.setattr(reviewer_module, "post_director_progress_update", lambda *args, **kwargs: None)

    review = run_task_review(session, project, task, task_run, result_artifact, workspace)
    session.flush()

    assert isinstance(review, TaskReview)
    assert review.recommendation == "approved"
    assert workspace.state == "done"
    assert task_run.status == "done"
    assert "Reviewer approved" in (task_run.stdout or "")
    assert session.scalars(select(Message)).first() is not None
    assert any(item.kind == "review_report" for item in session.scalars(select(Artifact)).all())


def test_reviewer_requests_changes_when_workspace_promotion_fails(monkeypatch):
    session = make_session()
    project, task, task_run, workspace = create_review_bundle(session)
    result_artifact = Artifact(
        project_id=project.id,
        task_id=task.id,
        kind="codex_result",
        title="Result",
        content=(
            "Экран помощи на русском языке объясняет сценарий работы, русский язык и понятный сценарий."
        ),
    )
    session.add(result_artifact)
    session.commit()

    monkeypatch.setattr(reviewer_module, "settings", SimpleNamespace(codex_worker_mode="real"))
    monkeypatch.setattr(
        reviewer_module,
        "promote_workspace_changes_to_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            reviewer_module.WorkspacePromotionError("promotion failed")
        ),
    )
    monkeypatch.setattr(reviewer_module, "transition_task", lambda *args, **kwargs: SimpleNamespace(summary="needs changes"))
    monkeypatch.setattr(reviewer_module, "post_director_progress_update", lambda *args, **kwargs: None)

    review = run_task_review(session, project, task, task_run, result_artifact, workspace)
    assert review.recommendation == "changes_requested"
    assert workspace.state == "changes_requested"
    assert task_run.status == "changes_requested"
