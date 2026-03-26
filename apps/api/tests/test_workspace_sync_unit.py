import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.workspace_sync as workspace_sync_module  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import Artifact, Project, Task, TaskWorkspace  # noqa: E402
from app.workspace_sync import WorkspacePromotionError, promote_workspace_changes_to_source  # noqa: E402


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def test_promote_workspace_changes_to_source_applies_created_modified_and_deleted(monkeypatch, tmp_path):
    session = make_session()
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="frontend_foundation",
        title="Implement help page",
        brief="Add help page",
        acceptance_criteria=["Page exists"],
        status="running",
    )
    source_root = tmp_path / "source"
    workspace_root = tmp_path / "workspace"
    runtime_root = tmp_path / "runtime"
    source_root.mkdir()
    workspace_root.mkdir()
    runtime_root.mkdir()

    (source_root / "existing.txt").write_text("old", encoding="utf-8")
    (source_root / "deleted.txt").write_text("remove", encoding="utf-8")
    (workspace_root / "existing.txt").write_text("new", encoding="utf-8")
    (workspace_root / "added.txt").write_text("created", encoding="utf-8")

    baseline_path = runtime_root / "WORKSPACE_BASELINE.json"
    baseline_path.write_text(
        json.dumps(
            {
                "manifest": {
                    "existing.txt": {"sha256": "old"},
                    "deleted.txt": {"sha256": "remove"},
                }
            }
        ),
        encoding="utf-8",
    )

    workspace = TaskWorkspace(
        project=project,
        task=task,
        root_path=str(runtime_root),
        workspace_path=str(workspace_root),
        source_root_path=str(source_root),
        context_file_path=str(runtime_root / "TASK_CONTEXT.json"),
        state="reviewing",
    )
    session.add_all([project, task, workspace])
    session.commit()

    monkeypatch.setattr(
        workspace_sync_module,
        "evaluate_policy_action",
        lambda *args, **kwargs: SimpleNamespace(
            allowed=True,
            approval_decision=SimpleNamespace(summary="approved"),
        ),
    )

    result = promote_workspace_changes_to_source(session, project, task, workspace)

    assert (source_root / "existing.txt").read_text(encoding="utf-8") == "new"
    assert (source_root / "added.txt").read_text(encoding="utf-8") == "created"
    assert not (source_root / "deleted.txt").exists()
    assert result.created_paths == ["added.txt"]
    assert result.modified_paths == ["existing.txt"]
    assert result.deleted_paths == ["deleted.txt"]
    assert session.scalars(select(Artifact)).first().kind == "source_workspace_sync_summary"


def test_promote_workspace_changes_to_source_rejects_policy_block(monkeypatch, tmp_path):
    session = make_session()
    project = Project(name="Office", description="Test")
    task = Task(
        project=project,
        task_key="frontend_foundation",
        title="Implement help page",
        brief="Add help page",
        acceptance_criteria=["Page exists"],
        status="running",
    )
    source_root = tmp_path / "source"
    workspace_root = tmp_path / "workspace"
    runtime_root = tmp_path / "runtime"
    source_root.mkdir()
    workspace_root.mkdir()
    runtime_root.mkdir()

    (workspace_root / "added.txt").write_text("created", encoding="utf-8")
    (runtime_root / "WORKSPACE_BASELINE.json").write_text(json.dumps({"manifest": {}}), encoding="utf-8")

    workspace = TaskWorkspace(
        project=project,
        task=task,
        root_path=str(runtime_root),
        workspace_path=str(workspace_root),
        source_root_path=str(source_root),
        context_file_path=str(runtime_root / "TASK_CONTEXT.json"),
        state="reviewing",
    )
    session.add_all([project, task, workspace])
    session.commit()

    monkeypatch.setattr(
        workspace_sync_module,
        "evaluate_policy_action",
        lambda *args, **kwargs: SimpleNamespace(
            allowed=False,
            approval_decision=SimpleNamespace(summary="blocked by policy"),
        ),
    )

    with pytest.raises(WorkspacePromotionError, match="blocked by policy"):
        promote_workspace_changes_to_source(session, project, task, workspace)
