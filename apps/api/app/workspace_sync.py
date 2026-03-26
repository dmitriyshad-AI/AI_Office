from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from app.models import Artifact, Project, Task, TaskWorkspace
from app.orchestration import log_event
from app.policy import evaluate_policy_action
from app.runtime import collect_workspace_manifest, workspace_baseline_path


@dataclass(frozen=True)
class WorkspacePromotionResult:
    created_paths: list[str]
    modified_paths: list[str]
    deleted_paths: list[str]
    artifact: Artifact

    @property
    def changed_paths(self) -> list[str]:
        return [*self.created_paths, *self.modified_paths, *self.deleted_paths]


class WorkspacePromotionError(RuntimeError):
    pass


def _load_baseline_manifest(workspace: TaskWorkspace, project_id: str, task_id: str) -> dict[str, dict]:
    baseline_candidates = []
    if workspace.root_path:
        baseline_candidates.append(Path(workspace.root_path) / "WORKSPACE_BASELINE.json")
    baseline_candidates.append(workspace_baseline_path(project_id, task_id))

    baseline_path = next((path for path in baseline_candidates if path.exists()), None)
    if baseline_path is None:
        return {}
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    manifest = payload.get("manifest")
    return manifest if isinstance(manifest, dict) else {}


def _validate_relative_path(relative_path: str) -> PurePosixPath:
    normalized = relative_path.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise WorkspacePromotionError(f"Unsafe workspace path for promotion: {relative_path}")
    return path


def _remove_empty_parent_dirs(target_path: Path, source_root: Path) -> None:
    current = target_path.parent
    while current != source_root and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _build_sync_summary(task: Task, created_paths: list[str], modified_paths: list[str], deleted_paths: list[str]) -> str:
    def format_section(title: str, paths: list[str]) -> str:
        if not paths:
            return f"### {title}\n- (none)\n"
        lines = [f"### {title}"]
        lines.extend(f"- `{path}`" for path in paths[:30])
        remaining = len(paths) - min(len(paths), 30)
        if remaining > 0:
            lines.append(f"- ... and {remaining} more")
        return "\n".join(lines) + "\n"

    return (
        f"# Source Workspace Sync Summary for {task.title}\n\n"
        f"- Created files applied: {len(created_paths)}\n"
        f"- Modified files applied: {len(modified_paths)}\n"
        f"- Deleted files applied: {len(deleted_paths)}\n\n"
        f"{format_section('Created', created_paths)}\n"
        f"{format_section('Modified', modified_paths)}\n"
        f"{format_section('Deleted', deleted_paths)}\n"
    )


def promote_workspace_changes_to_source(
    session: Session,
    project: Project,
    task: Task,
    workspace: TaskWorkspace,
) -> WorkspacePromotionResult:
    source_root = Path(workspace.source_root_path or "").resolve()
    workspace_root = Path(workspace.workspace_path).resolve()
    if not source_root.exists():
        raise WorkspacePromotionError(f"Source workspace root does not exist: {source_root}")
    if not workspace_root.exists():
        raise WorkspacePromotionError(f"Task workspace does not exist: {workspace_root}")

    baseline_manifest = _load_baseline_manifest(workspace, project.id, task.id)
    current_manifest = collect_workspace_manifest(workspace_root)
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
    changed_paths = [*created_paths, *modified_paths, *deleted_paths]

    evaluation = evaluate_policy_action(
        session,
        project,
        action_key="runtime.promote_workspace",
        requested_by="director",
        requester_role="Director",
        task=task,
        metadata={
            "target_path": str(source_root),
            "source_root_path": str(source_root),
            "workspace_path": str(workspace_root),
            "relative_paths": changed_paths,
        },
    )
    if not evaluation.allowed:
        raise WorkspacePromotionError(evaluation.approval_decision.summary)

    for relative_path in [*created_paths, *modified_paths]:
        relative = _validate_relative_path(relative_path)
        source_file = workspace_root / Path(*relative.parts)
        target_file = source_root / Path(*relative.parts)
        if not source_file.exists():
            raise WorkspacePromotionError(f"Workspace file is missing during promotion: {relative_path}")
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)

    for relative_path in deleted_paths:
        relative = _validate_relative_path(relative_path)
        target_file = source_root / Path(*relative.parts)
        if target_file.exists():
            target_file.unlink()
            _remove_empty_parent_dirs(target_file, source_root)

    summary = _build_sync_summary(task, created_paths, modified_paths, deleted_paths)
    artifact = Artifact(
        project_id=project.id,
        task_id=task.id,
        kind="source_workspace_sync_summary",
        title=f"Source workspace sync summary for {task.title}",
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
    log_event(
        session,
        project.id,
        "workspace_promoted_to_source",
        {
            "task_key": task.task_key,
            "created_count": len(created_paths),
            "modified_count": len(modified_paths),
            "deleted_count": len(deleted_paths),
        },
        task_id=task.id,
    )

    return WorkspacePromotionResult(
        created_paths=created_paths,
        modified_paths=modified_paths,
        deleted_paths=deleted_paths,
        artifact=artifact,
    )
