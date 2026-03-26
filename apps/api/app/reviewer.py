from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.director_reporting import post_director_progress_update
from app.models import (
    Agent,
    Artifact,
    Message,
    Project,
    ReviewFinding,
    Task,
    TaskReview,
    TaskRun,
    TaskWorkspace,
    utc_now,
)
from app.orchestration import log_event, transition_task
from app.workspace_sync import WorkspacePromotionError, promote_workspace_changes_to_source


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
settings = get_settings()
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "by",
    "for",
    "from",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


@dataclass
class FindingDraft:
    severity: str
    title: str
    details: str
    suggested_fix: str | None = None


def _tokenize(text: str) -> set[str]:
    tokens = {token for token in re.findall(r"[a-zA-Z0-9]{3,}", text.lower())}
    return {token for token in tokens if token not in STOPWORDS}


def _criterion_covered(criterion: str, content: str) -> bool:
    criterion_tokens = _tokenize(criterion)
    if not criterion_tokens:
        return True
    content_tokens = _tokenize(content)
    matched = criterion_tokens.intersection(content_tokens)
    return len(matched) >= min(2, len(criterion_tokens))


def _build_findings(task: Task, task_run: TaskRun, content: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []

    if not content.strip():
        findings.append(
            FindingDraft(
                severity="critical",
                title="Missing task deliverable",
                details="The execution finished without a substantive result artifact.",
                suggested_fix="Re-run the task and ensure the workspace contains the requested output.",
            )
        )

    if task_run.stderr:
        findings.append(
            FindingDraft(
                severity="high",
                title="Execution emitted stderr output",
                details="The worker run produced stderr content, so the result cannot be trusted as-is.",
                suggested_fix="Inspect the execution logs, fix the failing step, and re-run the task.",
            )
        )

    word_count = len(content.split())
    if 0 < word_count < 20:
        findings.append(
            FindingDraft(
                severity="medium",
                title="Result is too short for confident validation",
                details="The artifact is present but too compact to demonstrate full task coverage.",
                suggested_fix="Expand the final deliverable or summary with explicit decisions and outputs.",
            )
        )

    for criterion in task.acceptance_criteria:
        if _criterion_covered(criterion, content):
            continue
        findings.append(
            FindingDraft(
                severity="medium",
                title="Acceptance criterion lacks evidence",
                details=f"Reviewer could not find clear evidence for: {criterion}",
                suggested_fix="Update the task output so this criterion is explicitly covered.",
            )
        )

    if "todo" in content.lower() or "tbd" in content.lower():
        findings.append(
            FindingDraft(
                severity="medium",
                title="Result still contains unfinished placeholders",
                details="The deliverable includes TODO or TBD markers that indicate incomplete work.",
                suggested_fix="Resolve placeholders before sending the task back to review.",
            )
        )

    return findings


def _severity_counts(findings: list[FindingDraft]) -> dict[str, int]:
    counts = Counter(finding.severity for finding in findings)
    return {
        "low": counts.get("low", 0),
        "medium": counts.get("medium", 0),
        "high": counts.get("high", 0),
        "critical": counts.get("critical", 0),
    }


def _recommendation_for(findings: list[FindingDraft]) -> str:
    max_severity = max((SEVERITY_ORDER[finding.severity] for finding in findings), default=-1)
    return "changes_requested" if max_severity >= SEVERITY_ORDER["high"] else "approved"


def _summary_for(task: Task, recommendation: str, findings: list[FindingDraft]) -> str:
    if recommendation == "changes_requested":
        return (
            f"Reviewer requested rework for '{task.title}'. "
            f"{len(findings)} finding(s) were raised, including at least one high-risk issue."
        )
    if findings:
        return (
            f"Reviewer approved '{task.title}' with {len(findings)} note(s). "
            "The result is acceptable, but the notes should inform the next iteration."
        )
    return f"Reviewer approved '{task.title}' with no findings."


def _review_report(task_review: TaskReview, findings: list[FindingDraft]) -> str:
    lines = [
        "# Review Report",
        "",
        f"Status: {task_review.status}",
        f"Recommendation: {task_review.recommendation}",
        f"Summary: {task_review.summary}",
        "",
        "Severity counts:",
    ]
    for severity, count in task_review.severity_counts.items():
        lines.append(f"- {severity}: {count}")

    if findings:
        lines.extend(["", "Findings:"])
        for finding in findings:
            lines.append(f"- [{finding.severity}] {finding.title}: {finding.details}")
            if finding.suggested_fix:
                lines.append(f"  Suggested fix: {finding.suggested_fix}")
    else:
        lines.extend(["", "Findings:", "- None"])

    return "\n".join(lines)


def run_task_review(
    session: Session,
    project: Project,
    task: Task,
    task_run: TaskRun,
    result_artifact: Artifact,
    workspace: TaskWorkspace,
) -> TaskReview:
    reviewer_agent = session.scalars(
        select(Agent).where(Agent.project_id == project.id, Agent.role == "QAReviewer")
    ).first()

    review = TaskReview(
        project_id=project.id,
        task_id=task.id,
        task_run_id=task_run.id,
        reviewer_agent_id=reviewer_agent.id if reviewer_agent is not None else None,
        status="running",
        recommendation="pending",
        summary="Reviewer is validating the execution result.",
        severity_counts={"low": 0, "medium": 0, "high": 0, "critical": 0},
    )
    session.add(review)
    session.flush()

    log_event(
        session,
        project.id,
        "task_review_started",
        {
            "task_review_id": review.id,
            "task_run_id": task_run.id,
            "reviewer_role": reviewer_agent.role if reviewer_agent is not None else "QAReviewer",
        },
        task_id=task.id,
    )

    findings = _build_findings(task, task_run, result_artifact.content)
    review.status = "completed"
    review.recommendation = _recommendation_for(findings)
    if (
        review.recommendation == "approved"
        and settings.codex_worker_mode == "real"
        and workspace.workspace_path
    ):
        try:
            promotion_result = promote_workspace_changes_to_source(session, project, task, workspace)
            sync_summary = (
                f" Applied to source workspace: +{len(promotion_result.created_paths)} "
                f"~{len(promotion_result.modified_paths)} -{len(promotion_result.deleted_paths)}."
            )
        except WorkspacePromotionError as exc:
            findings.append(
                FindingDraft(
                    severity="high",
                    title="Source workspace promotion failed",
                    details=str(exc),
                    suggested_fix="Fix the promotion issue and re-run the task so approved changes can be applied to the main project.",
                )
            )
            review.recommendation = "changes_requested"
            sync_summary = ""
    else:
        sync_summary = ""

    review.summary = _summary_for(task, review.recommendation, findings) + sync_summary
    review.severity_counts = _severity_counts(findings)
    review.completed_at = utc_now()

    for finding in findings:
        session.add(
            ReviewFinding(
                project_id=project.id,
                task_id=task.id,
                task_review_id=review.id,
                severity=finding.severity,
                title=finding.title,
                details=finding.details,
                suggested_fix=finding.suggested_fix,
            )
        )

    report = _review_report(review, findings)
    review_artifact = Artifact(
        project_id=project.id,
        task_id=task.id,
        kind="review_report",
        title=f"Review report for {task.title}",
        content=report,
    )
    session.add(review_artifact)
    session.flush()
    log_event(
        session,
        project.id,
        "artifact_created",
        {
            "artifact_id": review_artifact.id,
            "kind": review_artifact.kind,
            "title": review_artifact.title,
        },
        task_id=task.id,
    )
    session.add(
        Message(
            project_id=project.id,
            role="reviewer",
            content=review.summary,
        )
    )

    log_event(
        session,
        project.id,
        "task_review_completed",
        {
            "task_review_id": review.id,
            "task_run_id": task_run.id,
            "recommendation": review.recommendation,
            "severity_counts": review.severity_counts,
        },
        task_id=task.id,
    )

    if review.recommendation == "approved":
        completion = transition_task(session, project, task, "approve_review", review.summary)
        workspace.state = "done"
        task_run.status = "done"
        task_run.finished_at = utc_now()
        task_run.stdout = (
            f"{task_run.stdout or ''}\nReviewer approved the result.\n{completion.summary}\n"
        )
        post_director_progress_update(
            session,
            project,
            milestone="review_approved",
            summary=f"Принял результат по задаче «{task.title}».",
            task_id=task.id,
        )
    else:
        rework = transition_task(session, project, task, "request_rework", review.summary)
        workspace.state = "changes_requested"
        task_run.status = "changes_requested"
        task_run.finished_at = utc_now()
        task_run.stdout = (
            f"{task_run.stdout or ''}\nReviewer requested changes.\n{rework.summary}\n"
        )
        post_director_progress_update(
            session,
            project,
            milestone="review_changes_requested",
            summary=f"Вернул задачу «{task.title}» на доработку.",
            task_id=task.id,
        )

    return review
