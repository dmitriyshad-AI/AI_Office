from __future__ import annotations

import asyncio
from collections import defaultdict
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import (
    AuthContext,
    ensure_role,
    get_auth_context,
    issue_stream_token,
    require_api_key,
)
from app.call_insights import (
    CALL_OPERATOR_REVIEW_STATUSES,
    CallInsightError,
    create_call_insight,
    resolve_call_insight_review,
    send_call_insight_to_amo,
)
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import (
    ActionIntent,
    Agent,
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    Artifact,
    CallInsight,
    CrmSyncPreview,
    EventLog,
    Message,
    Project,
    RiskAssessment,
    RunPolicy,
    Task,
    TaskDependency,
    TaskEnvironment,
    TaskReview,
    TaskRun,
    TaskWorkspace,
)
from app.codex_worker import (
    build_task_preflight,
    cancel_codex_execution,
    dispatch_director_next_ready_task,
    prepare_task_run_for_codex,
    start_codex_execution,
)
from app.action_intents import get_action_intent as get_action_intent_record
from app.action_intents import retry_action_intent as retry_runtime_action_intent
from app.crm_bridge import (
    CRM_OPERATOR_REVIEW_STATUSES,
    CrmBridgeError,
    amo_write_requires_review,
    create_crm_sync_preview,
    resolve_crm_sync_preview_review,
    sanitize_crm_preview_output,
    send_crm_sync_preview,
)
from app.orchestration import (
    OrchestrationError,
    load_dependency_map,
    transition_task,
)
from app.planner import create_goal_plan, ensure_project_agents
from app.policy import ensure_project_policies, evaluate_policy_action
from app.policy import resolve_approval_request as resolve_human_approval_request
from app.runtime import ensure_task_runtime, register_task_run_transition
from app.schemas import (
    ApprovalDecisionRead,
    ApprovalPolicyRead,
    ApprovalResolveRequest,
    ApprovalResolveResponse,
    ActionIntentRead,
    ActionIntentRetryRequest,
    ActionIntentRetryResponse,
    DirectorAdvanceResponse,
    AgentRead,
    ApprovalRequestRead,
    ArtifactRead,
    CallInsightCreateRequest,
    CallInsightCreateResponse,
    CallInsightRead,
    CallInsightReviewResolveRequest,
    CallInsightReviewResolveResponse,
    CallInsightSendRequest,
    CallInsightSendResponse,
    CrmReviewResolveRequest,
    CrmSyncPreviewCreateRequest,
    CrmSyncPreviewRead,
    CrmReviewResolveResponse,
    CrmSyncSendRequest,
    CrmSyncSendResponse,
    EventLogRead,
    GoalPlanResponse,
    GoalSubmission,
    MessageRead,
    PolicyCheckRequest,
    PolicyCheckResponse,
    ProjectCreate,
    ProjectRead,
    ProjectStatusUpdateResponse,
    RiskAssessmentRead,
    TaskActionRequest,
    TaskActionResponse,
    TaskExecutionResponse,
    TaskPreflightRead,
    PreflightCheckRead,
    TaskEnvironmentRead,
    TaskRunCancelRequest,
    TaskRunCancelResponse,
    TaskRead,
    TaskReviewRead,
    TaskRunRead,
    TaskRunLogRead,
    TaskRuntimeRead,
    TaskWorkspaceRead,
    RunPolicyRead,
    ReviewFindingRead,
    StreamTokenRead,
)


router = APIRouter(dependencies=[Depends(require_api_key)])
settings = get_settings()


def get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def get_task_or_404(db: Session, project_id: str, task_id: str) -> Task:
    task = db.scalars(
        select(Task)
        .where(Task.project_id == project_id, Task.id == task_id)
        .options(selectinload(Task.assigned_agent))
    ).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def get_approval_request_or_404(
    db: Session, project_id: str, approval_request_id: str
) -> ApprovalRequest:
    approval_request = db.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.project_id == project_id,
            ApprovalRequest.id == approval_request_id,
        )
        .options(selectinload(ApprovalRequest.risk_assessment))
    ).first()
    if approval_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found",
        )
    return approval_request


def get_task_run_or_404(db: Session, task_run_id: str, project_id: str) -> TaskRun:
    task_run = db.scalars(
        select(TaskRun)
        .join(Task, Task.id == TaskRun.task_id)
        .where(TaskRun.id == task_run_id, Task.project_id == project_id)
    ).first()
    if task_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task run not found",
        )
    return task_run


def get_action_intent_or_404(
    db: Session, project_id: str, action_intent_id: str
) -> ActionIntent:
    action_intent = get_action_intent_record(db, action_intent_id)
    if action_intent is None or action_intent.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action intent not found",
        )
    return action_intent


def get_crm_preview_or_404(
    db: Session, project_id: str, preview_id: str
) -> CrmSyncPreview:
    preview = db.scalars(
        select(CrmSyncPreview).where(
            CrmSyncPreview.project_id == project_id,
            CrmSyncPreview.id == preview_id,
        )
    ).first()
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CRM preview not found",
        )
    return preview


def get_call_insight_or_404(
    db: Session, project_id: str, call_insight_id: str
) -> CallInsight:
    insight = db.scalars(
        select(CallInsight).where(
            CallInsight.project_id == project_id,
            CallInsight.id == call_insight_id,
        )
    ).first()
    if insight is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call insight not found",
        )
    return insight


def serialize_task(task: Task, dependency_map: dict[str, list[str]]) -> TaskRead:
    assigned_role = task.assigned_agent.role if task.assigned_agent is not None else None
    return TaskRead(
        id=task.id,
        project_id=task.project_id,
        assigned_agent_id=task.assigned_agent_id,
        assigned_agent_role=assigned_role,
        task_key=task.task_key,
        title=task.title,
        brief=task.brief,
        acceptance_criteria=task.acceptance_criteria,
        status=task.status,
        priority=task.priority,
        depends_on_ids=dependency_map.get(task.id, []),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def serialize_task_run(task_run: TaskRun, task: Task) -> TaskRunRead:
    return TaskRunRead(
        id=task_run.id,
        task_id=task_run.task_id,
        task_title=task.title,
        task_key=task.task_key,
        status=task_run.status,
        started_at=task_run.started_at,
        finished_at=task_run.finished_at,
        worktree_path=task_run.worktree_path,
        environment_name=task_run.environment_name,
    )


def serialize_crm_preview(preview: CrmSyncPreview) -> CrmSyncPreviewRead:
    payload = CrmSyncPreviewRead.model_validate(preview).model_dump(mode="json")
    sanitized_payload = sanitize_crm_preview_output(payload)
    return CrmSyncPreviewRead.model_validate(sanitized_payload)


def serialize_call_insight(insight: CallInsight) -> CallInsightRead:
    return CallInsightRead(
        id=insight.id,
        project_id=insight.project_id,
        source_system=insight.source_system,
        source_key=insight.source_key,
        source_call_id=insight.source_call_id,
        source_record_id=insight.source_record_id,
        source_file=insight.source_file,
        source_filename=insight.source_filename,
        phone=insight.phone,
        manager_name=insight.manager_name,
        started_at=insight.started_at,
        duration_sec=insight.duration_sec,
        history_summary=insight.history_summary,
        lead_priority=insight.lead_priority,
        follow_up_score=insight.follow_up_score,
        processing_status=insight.processing_status,
        status=insight.status,
        match_status=insight.match_status,
        matched_amo_contact_id=insight.matched_amo_contact_id,
        review_status=insight.review_status,
        review_reason=insight.review_reason,
        review_summary=insight.review_summary,
        reviewed_by=insight.reviewed_by,
        reviewed_at=insight.reviewed_at,
        sent_by=insight.sent_by,
        sent_at=insight.sent_at,
        send_result=insight.send_result,
        error_message=insight.error_message,
        payload=insight.payload,
        created_by=insight.created_by,
        created_at=insight.created_at,
        updated_at=insight.updated_at,
    )


def serialize_action_intent(action_intent: ActionIntent) -> ActionIntentRead:
    return ActionIntentRead.model_validate(action_intent)


def serialize_task_review(task_review: TaskReview) -> TaskReviewRead:
    reviewer_agent = task_review.reviewer_agent
    findings = [
        ReviewFindingRead.model_validate(finding)
        for finding in sorted(task_review.findings, key=lambda item: item.created_at)
    ]
    return TaskReviewRead(
        id=task_review.id,
        project_id=task_review.project_id,
        task_id=task_review.task_id,
        task_run_id=task_review.task_run_id,
        reviewer_agent_id=task_review.reviewer_agent_id,
        reviewer_role=reviewer_agent.role if reviewer_agent is not None else None,
        reviewer_name=reviewer_agent.name if reviewer_agent is not None else None,
        status=task_review.status,
        recommendation=task_review.recommendation,
        summary=task_review.summary,
        severity_counts=task_review.severity_counts,
        findings=findings,
        created_at=task_review.created_at,
        completed_at=task_review.completed_at,
    )


def load_task_runtime_records(
    db: Session, task_id: str
) -> tuple[TaskWorkspace | None, TaskEnvironment | None, RunPolicy | None, list[TaskRun]]:
    workspace = db.scalars(
        select(TaskWorkspace).where(TaskWorkspace.task_id == task_id)
    ).first()
    environment = db.scalars(
        select(TaskEnvironment).where(TaskEnvironment.task_id == task_id)
    ).first()
    run_policy = db.scalars(select(RunPolicy).where(RunPolicy.task_id == task_id)).first()
    runs = db.scalars(
        select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.started_at.desc())
    ).all()
    return workspace, environment, run_policy, runs


def serialize_preflight_result(preflight_result) -> TaskPreflightRead:
    return TaskPreflightRead(
        ready=preflight_result.ready,
        summary=preflight_result.summary,
        checks=[
            PreflightCheckRead(
                key=check.key,
                status=check.status,
                message=check.message,
                blocking=check.blocking,
            )
            for check in preflight_result.checks
        ],
    )


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(
        name=payload.name,
        description=payload.description,
        status="draft",
    )
    db.add(project)
    db.flush()

    ensure_project_agents(db, project)
    ensure_project_policies(db, project)
    db.add(
        EventLog(
            project_id=project.id,
            event_type="project_created",
            payload={"name": project.name},
        )
    )
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return db.scalars(select(Project).order_by(Project.updated_at.desc(), Project.created_at.desc())).all()


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    return get_project_or_404(db, project_id)


@router.post("/projects/{project_id}/archive", response_model=ProjectStatusUpdateResponse)
def archive_project(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> ProjectStatusUpdateResponse:
    ensure_role(auth, "Director", "Human", "DevOps")
    project = get_project_or_404(db, project_id)
    if project.status != "archived":
        previous_status = project.status
        project.status = "archived"
        db.add(
            EventLog(
                project_id=project.id,
                event_type="project_archived",
                payload={"from_status": previous_status, "actor": auth.actor},
            )
        )
        db.commit()
        db.refresh(project)

    return ProjectStatusUpdateResponse(
        project=ProjectRead.model_validate(project),
        summary=f"Проект «{project.name}» перенесён в архив.",
    )


@router.post("/projects/{project_id}/restore", response_model=ProjectStatusUpdateResponse)
def restore_project(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> ProjectStatusUpdateResponse:
    ensure_role(auth, "Director", "Human", "DevOps")
    project = get_project_or_404(db, project_id)
    if project.status == "archived":
        restored_status = "active" if project.latest_goal_text else "draft"
        project.status = restored_status
        db.add(
            EventLog(
                project_id=project.id,
                event_type="project_restored",
                payload={"to_status": restored_status, "actor": auth.actor},
            )
        )
        db.commit()
        db.refresh(project)

    return ProjectStatusUpdateResponse(
        project=ProjectRead.model_validate(project),
        summary=f"Проект «{project.name}» возвращён в рабочий список.",
    )


@router.post("/projects/{project_id}/goal", response_model=GoalPlanResponse)
def submit_goal(
    project_id: str,
    payload: GoalSubmission,
    db: Session = Depends(get_db),
) -> GoalPlanResponse:
    project = get_project_or_404(db, project_id)
    plan_result = create_goal_plan(db, project, payload.goal_text)
    director_dispatch = dispatch_director_next_ready_task(
        db,
        project,
        trigger="goal_submitted",
    )
    db.commit()
    if director_dispatch is not None:
        start_codex_execution(project.id, director_dispatch.task_id, director_dispatch.task_run_id)
    db.refresh(project)

    tasks = (
        db.scalars(
            select(Task)
            .where(Task.id.in_([task.id for task in plan_result.created_tasks]))
            .options(selectinload(Task.assigned_agent))
            .order_by(Task.priority.desc(), Task.created_at.asc())
        ).all()
        if plan_result.created_tasks
        else []
    )
    dependencies = db.scalars(
        select(TaskDependency).where(TaskDependency.project_id == project.id)
    ).all()
    dependency_map: dict[str, list[str]] = defaultdict(list)
    for dependency in dependencies:
        dependency_map[dependency.task_id].append(dependency.depends_on_task_id)

    response_summary = plan_result.summary
    if director_dispatch is not None:
        response_summary = (
            f"{response_summary} Директор автоматически запустил задачу "
            f"'{director_dispatch.task_title}'."
        )

    return GoalPlanResponse(
        project=ProjectRead.model_validate(project),
        summary=response_summary,
        created_tasks=[serialize_task(task, dependency_map) for task in tasks],
    )


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
def list_project_tasks(project_id: str, db: Session = Depends(get_db)) -> list[TaskRead]:
    get_project_or_404(db, project_id)
    tasks = db.scalars(
        select(Task)
        .where(Task.project_id == project_id)
        .options(selectinload(Task.assigned_agent))
        .order_by(Task.priority.desc(), Task.created_at.asc())
    ).all()
    dependencies = db.scalars(
        select(TaskDependency).where(TaskDependency.project_id == project_id)
    ).all()
    dependency_map: dict[str, list[str]] = defaultdict(list)
    for dependency in dependencies:
        dependency_map[dependency.task_id].append(dependency.depends_on_task_id)
    return [serialize_task(task, dependency_map) for task in tasks]


@router.get("/projects/{project_id}/agents", response_model=list[AgentRead])
def list_project_agents(project_id: str, db: Session = Depends(get_db)) -> list[Agent]:
    get_project_or_404(db, project_id)
    return db.scalars(
        select(Agent).where(Agent.project_id == project_id).order_by(Agent.role.asc())
    ).all()


@router.get("/projects/{project_id}/runs", response_model=list[TaskRunRead])
def list_project_runs(project_id: str, db: Session = Depends(get_db)) -> list[TaskRunRead]:
    get_project_or_404(db, project_id)
    runs = db.scalars(
        select(TaskRun)
        .join(Task, Task.id == TaskRun.task_id)
        .where(Task.project_id == project_id)
        .order_by(TaskRun.started_at.desc())
    ).all()
    tasks_by_id = {
        task.id: task
        for task in db.scalars(select(Task).where(Task.project_id == project_id)).all()
    }
    return [serialize_task_run(run, tasks_by_id[run.task_id]) for run in runs]


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactRead])
def list_project_artifacts(project_id: str, db: Session = Depends(get_db)) -> list[Artifact]:
    get_project_or_404(db, project_id)
    return db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id)
        .order_by(Artifact.created_at.desc())
    ).all()


@router.post(
    "/projects/{project_id}/calls/insights",
    response_model=CallInsightCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_call_insight(
    project_id: str,
    payload: CallInsightCreateRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CallInsightCreateResponse:
    ensure_role(auth, "Director", "DevOps", "BackendEngineer")
    project = get_project_or_404(db, project_id)

    evaluation = evaluate_policy_action(
        db,
        project,
        "calls.insight.ingest",
        requested_by=auth.actor,
        requester_role=auth.role,
        metadata={
            "source_system": payload.source.system,
            "source_call_id": payload.source.source_call_id or "",
            "source_file": payload.source.source_file or "",
            "source_filename": payload.source.source_filename or "",
            "phone": payload.source.phone or payload.identity_hints.phone or "",
        },
    )
    if not evaluation.allowed:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=evaluation.approval_decision.summary,
        )

    try:
        result = create_call_insight(
            db,
            project,
            payload=payload.model_dump(mode="json"),
            created_by=auth.actor,
        )
    except CallInsightError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return CallInsightCreateResponse(
        insight=serialize_call_insight(result.insight),
        summary=result.summary,
    )


@router.get("/projects/{project_id}/calls/insights", response_model=list[CallInsightRead])
def list_project_call_insights(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> list[CallInsightRead]:
    ensure_role(auth, "Director", "Human", "DevOps", "BackendEngineer")
    get_project_or_404(db, project_id)
    insights = db.scalars(
        select(CallInsight)
        .where(CallInsight.project_id == project_id)
        .order_by(CallInsight.created_at.desc())
    ).all()
    return [serialize_call_insight(insight) for insight in insights]


@router.get(
    "/projects/{project_id}/calls/insights/{call_insight_id}",
    response_model=CallInsightRead,
)
def get_project_call_insight(
    project_id: str,
    call_insight_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CallInsightRead:
    ensure_role(auth, "Director", "Human", "DevOps", "BackendEngineer")
    get_project_or_404(db, project_id)
    insight = get_call_insight_or_404(db, project_id, call_insight_id)
    return serialize_call_insight(insight)


@router.get(
    "/projects/{project_id}/calls/review-queue",
    response_model=list[CallInsightRead],
)
def list_project_call_review_queue(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> list[CallInsightRead]:
    ensure_role(auth, "Director", "Human", "DevOps", "BackendEngineer")
    get_project_or_404(db, project_id)
    insights = db.scalars(
        select(CallInsight)
        .where(
            CallInsight.project_id == project_id,
            CallInsight.review_status.in_(sorted(CALL_OPERATOR_REVIEW_STATUSES)),
        )
        .order_by(CallInsight.created_at.desc())
    ).all()
    return [serialize_call_insight(insight) for insight in insights]


@router.post(
    "/projects/{project_id}/calls/review-queue/{call_insight_id}/resolve",
    response_model=CallInsightReviewResolveResponse,
)
def resolve_project_call_review(
    project_id: str,
    call_insight_id: str,
    payload: CallInsightReviewResolveRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CallInsightReviewResolveResponse:
    ensure_role(auth, "Director", "Human", "DevOps")
    project = get_project_or_404(db, project_id)
    insight = get_call_insight_or_404(db, project_id, call_insight_id)
    try:
        insight, summary = resolve_call_insight_review(
            db,
            project,
            insight,
            outcome=payload.outcome,
            actor=auth.actor,
            summary=payload.summary,
            matched_amo_contact_id=payload.matched_amo_contact_id,
        )
    except CallInsightError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return CallInsightReviewResolveResponse(
        insight=serialize_call_insight(insight),
        summary=summary,
    )


@router.post(
    "/projects/{project_id}/calls/insights/{call_insight_id}/send",
    response_model=CallInsightSendResponse,
)
def send_project_call_insight(
    project_id: str,
    call_insight_id: str,
    payload: CallInsightSendRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CallInsightSendResponse:
    ensure_role(auth, "Director", "Human", "DevOps")
    project = get_project_or_404(db, project_id)
    insight = get_call_insight_or_404(db, project_id, call_insight_id)
    if insight.status == "sent":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Call insight already sent to AMO.",
        )
    if amo_write_requires_review() and insight.review_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Call insight must be approved in review queue before AMO write.",
        )

    evaluation = evaluate_policy_action(
        db,
        project,
        "calls.amo.write",
        requested_by=auth.actor,
        requester_role=auth.role,
        metadata={
            "call_insight_id": insight.id,
            "matched_amo_contact_id": payload.matched_amo_contact_id or insight.matched_amo_contact_id,
            "amo_mode": settings.crm_amo_mode,
            "review_status": insight.review_status,
            "override_fields": sorted((payload.field_overrides or {}).keys()),
        },
    )
    if not evaluation.allowed:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=evaluation.approval_decision.summary,
        )

    try:
        insight, summary = send_call_insight_to_amo(
            db,
            project,
            insight,
            actor=auth.actor,
            matched_amo_contact_id=payload.matched_amo_contact_id,
            field_overrides=payload.field_overrides,
        )
    except CallInsightError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CrmBridgeError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    db.commit()
    return CallInsightSendResponse(
        insight=serialize_call_insight(insight),
        summary=summary,
    )


@router.post(
    "/projects/{project_id}/crm/previews",
    response_model=CrmSyncPreviewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_crm_preview(
    project_id: str,
    payload: CrmSyncPreviewCreateRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CrmSyncPreviewRead:
    ensure_role(auth, "Director", "DevOps", "BackendEngineer")
    project = get_project_or_404(db, project_id)

    read_evaluation = evaluate_policy_action(
        db,
        project,
        "crm.tallanto.read",
        requested_by=auth.actor,
        requester_role=auth.role,
        metadata={
            "student_id": payload.student_id,
            "lookup_mode": payload.lookup_mode,
            "source_system": "tallanto",
        },
    )
    if not read_evaluation.allowed:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=read_evaluation.approval_decision.summary,
        )

    preview_evaluation = evaluate_policy_action(
        db,
        project,
        "crm.preview.create",
        requested_by=auth.actor,
        requester_role=auth.role,
        metadata={
            "student_id": payload.student_id,
            "lookup_mode": payload.lookup_mode,
            "amo_entity_type": payload.amo_entity_type,
            "amo_entity_id": payload.amo_entity_id or "",
        },
    )
    if not preview_evaluation.allowed:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=preview_evaluation.approval_decision.summary,
        )

    try:
        preview = create_crm_sync_preview(
            db,
            project,
            student_id=payload.student_id,
            lookup_mode=payload.lookup_mode,
            amo_entity_type=payload.amo_entity_type,
            amo_entity_id=payload.amo_entity_id,
            field_mapping=payload.field_mapping,
            created_by=auth.actor,
        )
    except CrmBridgeError as exc:
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return serialize_crm_preview(preview)


@router.get("/projects/{project_id}/crm/previews", response_model=list[CrmSyncPreviewRead])
def list_project_crm_previews(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> list[CrmSyncPreviewRead]:
    ensure_role(auth, "Director", "Human", "DevOps", "BackendEngineer")
    get_project_or_404(db, project_id)
    previews = db.scalars(
        select(CrmSyncPreview)
        .where(CrmSyncPreview.project_id == project_id)
        .order_by(CrmSyncPreview.created_at.desc())
    ).all()
    return [serialize_crm_preview(preview) for preview in previews]


@router.get(
    "/projects/{project_id}/crm/review-queue",
    response_model=list[CrmSyncPreviewRead],
)
def list_project_crm_review_queue(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> list[CrmSyncPreviewRead]:
    ensure_role(auth, "Director", "Human", "DevOps", "BackendEngineer")
    get_project_or_404(db, project_id)
    previews = db.scalars(
        select(CrmSyncPreview)
        .where(
            CrmSyncPreview.project_id == project_id,
            CrmSyncPreview.review_status.in_(sorted(CRM_OPERATOR_REVIEW_STATUSES)),
        )
        .order_by(CrmSyncPreview.created_at.desc())
    ).all()
    return [serialize_crm_preview(preview) for preview in previews]


@router.get(
    "/projects/{project_id}/crm/previews/{preview_id}",
    response_model=CrmSyncPreviewRead,
)
def get_project_crm_preview(
    project_id: str,
    preview_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CrmSyncPreviewRead:
    ensure_role(auth, "Director", "Human", "DevOps", "BackendEngineer")
    get_project_or_404(db, project_id)
    preview = get_crm_preview_or_404(db, project_id, preview_id)
    return serialize_crm_preview(preview)


@router.post(
    "/projects/{project_id}/crm/review-queue/{preview_id}/resolve",
    response_model=CrmReviewResolveResponse,
)
def resolve_project_crm_review(
    project_id: str,
    preview_id: str,
    payload: CrmReviewResolveRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CrmReviewResolveResponse:
    ensure_role(auth, "Director", "Human", "DevOps")
    project = get_project_or_404(db, project_id)
    preview = get_crm_preview_or_404(db, project_id, preview_id)
    try:
        preview, summary = resolve_crm_sync_preview_review(
            db,
            project,
            preview,
            outcome=payload.outcome,
            actor=auth.actor,
            summary=payload.summary,
            amo_entity_id=payload.amo_entity_id,
        )
    except CrmBridgeError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    db.commit()
    return CrmReviewResolveResponse(
        preview=serialize_crm_preview(preview),
        summary=summary,
    )


@router.post(
    "/projects/{project_id}/crm/previews/{preview_id}/send",
    response_model=CrmSyncSendResponse,
)
def send_project_crm_preview(
    project_id: str,
    preview_id: str,
    payload: CrmSyncSendRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> CrmSyncSendResponse:
    ensure_role(auth, "Director", "Human", "DevOps")
    project = get_project_or_404(db, project_id)
    preview = get_crm_preview_or_404(db, project_id, preview_id)
    if preview.status == "sent":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CRM preview already sent. Create a new preview for repeated transfer.",
        )
    if amo_write_requires_review() and preview.review_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CRM preview must be approved in review queue before AMO write.",
        )

    evaluation = evaluate_policy_action(
        db,
        project,
        "crm.amo.write",
        requested_by=auth.actor,
        requester_role=auth.role,
        metadata={
            "preview_id": preview.id,
            "source_student_id": preview.source_student_id,
            "amo_entity_type": preview.amo_entity_type,
            "amo_entity_id": payload.amo_entity_id or preview.amo_entity_id or "",
            "amo_mode": settings.crm_amo_mode,
            "review_status": preview.review_status,
            "selected_fields": (
                payload.selected_fields
                if payload.selected_fields is not None
                else ["__all__"]
            ),
            "override_fields": sorted((payload.field_overrides or {}).keys()),
        },
    )
    if not evaluation.allowed:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=evaluation.approval_decision.summary,
        )

    updated_preview, summary = send_crm_sync_preview(
        db,
        project,
        preview,
        actor=auth.actor,
        amo_entity_id=payload.amo_entity_id,
        selected_fields=payload.selected_fields,
        field_overrides=payload.field_overrides,
    )
    db.commit()
    return CrmSyncSendResponse(
        preview=serialize_crm_preview(updated_preview),
        summary=summary,
    )


@router.get("/projects/{project_id}/action-intents", response_model=list[ActionIntentRead])
def list_project_action_intents(
    project_id: str, db: Session = Depends(get_db)
) -> list[ActionIntentRead]:
    get_project_or_404(db, project_id)
    intents = db.scalars(
        select(ActionIntent)
        .where(ActionIntent.project_id == project_id)
        .order_by(ActionIntent.created_at.desc())
    ).all()
    return [serialize_action_intent(intent) for intent in intents]


@router.post(
    "/projects/{project_id}/action-intents/{action_intent_id}/retry",
    response_model=ActionIntentRetryResponse,
)
def retry_project_action_intent(
    project_id: str,
    action_intent_id: str,
    payload: ActionIntentRetryRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> ActionIntentRetryResponse:
    ensure_role(auth, "Director", "DevOps")
    project = get_project_or_404(db, project_id)
    action_intent = get_action_intent_or_404(db, project_id, action_intent_id)

    try:
        result = retry_runtime_action_intent(
            db,
            project,
            action_intent,
            actor=auth.actor,
            ignore_backoff=payload.ignore_backoff,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return ActionIntentRetryResponse(
        action_intent=serialize_action_intent(result.action_intent),
        summary=result.summary,
    )


@router.get(
    "/projects/{project_id}/tasks/{task_id}/action-intents",
    response_model=list[ActionIntentRead],
)
def list_task_action_intents(
    project_id: str, task_id: str, db: Session = Depends(get_db)
) -> list[ActionIntentRead]:
    get_project_or_404(db, project_id)
    get_task_or_404(db, project_id, task_id)
    intents = db.scalars(
        select(ActionIntent)
        .where(ActionIntent.project_id == project_id, ActionIntent.task_id == task_id)
        .order_by(ActionIntent.created_at.desc())
    ).all()
    return [serialize_action_intent(intent) for intent in intents]


@router.get("/projects/{project_id}/reviews", response_model=list[TaskReviewRead])
def list_project_reviews(project_id: str, db: Session = Depends(get_db)) -> list[TaskReviewRead]:
    get_project_or_404(db, project_id)
    reviews = db.scalars(
        select(TaskReview)
        .where(TaskReview.project_id == project_id)
        .options(selectinload(TaskReview.reviewer_agent), selectinload(TaskReview.findings))
        .order_by(TaskReview.created_at.desc())
    ).all()
    return [serialize_task_review(review) for review in reviews]


@router.get("/projects/{project_id}/tasks/{task_id}/reviews", response_model=list[TaskReviewRead])
def list_task_reviews(
    project_id: str, task_id: str, db: Session = Depends(get_db)
) -> list[TaskReviewRead]:
    get_project_or_404(db, project_id)
    get_task_or_404(db, project_id, task_id)
    reviews = db.scalars(
        select(TaskReview)
        .where(TaskReview.project_id == project_id, TaskReview.task_id == task_id)
        .options(selectinload(TaskReview.reviewer_agent), selectinload(TaskReview.findings))
        .order_by(TaskReview.created_at.desc())
    ).all()
    return [serialize_task_review(review) for review in reviews]


@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalRequestRead])
def list_project_approvals(
    project_id: str, db: Session = Depends(get_db)
) -> list[ApprovalRequest]:
    get_project_or_404(db, project_id)
    return db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.project_id == project_id)
        .order_by(ApprovalRequest.created_at.desc())
    ).all()


@router.post(
    "/projects/{project_id}/approvals/{approval_request_id}/resolve",
    response_model=ApprovalResolveResponse,
)
def resolve_project_approval(
    project_id: str,
    approval_request_id: str,
    payload: ApprovalResolveRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> ApprovalResolveResponse:
    ensure_role(auth, "Human", "Director")
    project = get_project_or_404(db, project_id)
    approval_request = get_approval_request_or_404(db, project_id, approval_request_id)

    try:
        resolution = resolve_human_approval_request(
            db,
            project,
            approval_request,
            outcome=payload.outcome,
            actor=auth.actor,
            summary=payload.summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()

    return ApprovalResolveResponse(
        approval_request=ApprovalRequestRead.model_validate(resolution.approval_request),
        approval_decision=ApprovalDecisionRead.model_validate(resolution.approval_decision),
        risk_assessment=(
            RiskAssessmentRead.model_validate(resolution.risk_assessment)
            if resolution.risk_assessment is not None
            else None
        ),
        action_intent=(
            serialize_action_intent(resolution.action_intent)
            if resolution.action_intent is not None
            else None
        ),
        summary=resolution.summary,
    )


@router.get("/projects/{project_id}/approval-policies", response_model=list[ApprovalPolicyRead])
def list_project_approval_policies(
    project_id: str, db: Session = Depends(get_db)
) -> list[ApprovalPolicy]:
    project = get_project_or_404(db, project_id)
    ensure_project_policies(db, project)
    db.flush()
    return db.scalars(
        select(ApprovalPolicy)
        .where(ApprovalPolicy.project_id == project_id)
        .order_by(ApprovalPolicy.action_key.asc())
    ).all()


@router.get("/projects/{project_id}/approval-decisions", response_model=list[ApprovalDecisionRead])
def list_project_approval_decisions(
    project_id: str, db: Session = Depends(get_db)
) -> list[ApprovalDecision]:
    get_project_or_404(db, project_id)
    return db.scalars(
        select(ApprovalDecision)
        .where(ApprovalDecision.project_id == project_id)
        .order_by(ApprovalDecision.created_at.desc())
    ).all()


@router.get("/projects/{project_id}/risk-assessments", response_model=list[RiskAssessmentRead])
def list_project_risk_assessments(
    project_id: str, db: Session = Depends(get_db)
) -> list[RiskAssessment]:
    get_project_or_404(db, project_id)
    return db.scalars(
        select(RiskAssessment)
        .where(RiskAssessment.project_id == project_id)
        .order_by(RiskAssessment.created_at.desc())
    ).all()


@router.get("/projects/{project_id}/messages", response_model=list[MessageRead])
def list_project_messages(project_id: str, db: Session = Depends(get_db)) -> list[Message]:
    get_project_or_404(db, project_id)
    return db.scalars(
        select(Message)
        .where(Message.project_id == project_id)
        .order_by(Message.created_at.asc())
    ).all()


@router.get("/projects/{project_id}/events", response_model=list[EventLogRead])
def list_project_events(project_id: str, db: Session = Depends(get_db)) -> list[EventLog]:
    get_project_or_404(db, project_id)
    return db.scalars(
        select(EventLog)
        .where(EventLog.project_id == project_id)
        .order_by(EventLog.created_at.desc())
    ).all()


@router.get("/projects/{project_id}/tasks/{task_id}/runtime", response_model=TaskRuntimeRead)
def get_task_runtime(
    project_id: str, task_id: str, db: Session = Depends(get_db)
) -> TaskRuntimeRead:
    project = get_project_or_404(db, project_id)
    task = get_task_or_404(db, project_id, task_id)
    workspace, environment, run_policy, runs = load_task_runtime_records(db, task.id)
    if workspace is None or environment is None or run_policy is None:
        ensure_task_runtime(db, project, task)
        db.commit()
        workspace, environment, run_policy, runs = load_task_runtime_records(db, task.id)

    if workspace is None or environment is None or run_policy is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Task runtime could not be provisioned",
        )

    return TaskRuntimeRead(
        workspace=TaskWorkspaceRead.model_validate(workspace),
        environment=TaskEnvironmentRead.model_validate(environment),
        run_policy=RunPolicyRead.model_validate(run_policy),
        runs=[serialize_task_run(run, task) for run in runs],
    )


@router.get(
    "/projects/{project_id}/tasks/{task_id}/preflight",
    response_model=TaskPreflightRead,
)
def get_task_preflight(
    project_id: str, task_id: str, db: Session = Depends(get_db)
) -> TaskPreflightRead:
    project = get_project_or_404(db, project_id)
    task = get_task_or_404(db, project_id, task_id)
    try:
        preflight_result = build_task_preflight(db, project, task)
    except OrchestrationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    return serialize_preflight_result(preflight_result)


@router.post("/projects/{project_id}/policy-checks", response_model=PolicyCheckResponse)
def create_policy_check(
    project_id: str,
    payload: PolicyCheckRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> PolicyCheckResponse:
    project = get_project_or_404(db, project_id)
    task = get_task_or_404(db, project_id, payload.task_id) if payload.task_id else None
    task_run = (
        get_task_run_or_404(db, payload.task_run_id, project_id)
        if payload.task_run_id
        else None
    )
    if task is not None and task_run is not None and task_run.task_id != task.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="task_run_id does not belong to the provided task_id",
        )

    evaluation = evaluate_policy_action(
        db,
        project,
        payload.action_key,
        task=task,
        task_run=task_run,
        requested_by=auth.actor,
        requester_role=auth.role,
        metadata=payload.metadata,
    )
    db.commit()

    return PolicyCheckResponse(
        allowed=evaluation.allowed,
        approval_policy=(
            ApprovalPolicyRead.model_validate(evaluation.approval_policy)
            if evaluation.approval_policy is not None
            else None
        ),
        risk_assessment=RiskAssessmentRead.model_validate(evaluation.risk_assessment),
        approval_decision=ApprovalDecisionRead.model_validate(evaluation.approval_decision),
        approval_request=(
            ApprovalRequestRead.model_validate(evaluation.approval_request)
            if evaluation.approval_request is not None
            else None
        ),
        action_intent=(
            serialize_action_intent(evaluation.action_intent)
            if evaluation.action_intent is not None
            else None
        ),
    )


@router.get("/projects/{project_id}/events/stream")
async def stream_project_events(
    project_id: str,
    request: Request,
) -> StreamingResponse:
    project_check_session = SessionLocal()
    try:
        get_project_or_404(project_check_session, project_id)
    finally:
        project_check_session.close()

    async def event_generator():
        bootstrap_session = SessionLocal()
        try:
            latest_existing_event = bootstrap_session.scalars(
                select(EventLog)
                .where(EventLog.project_id == project_id)
                .order_by(EventLog.created_at.desc())
            ).first()
            last_seen_at = latest_existing_event.created_at if latest_existing_event else None
            seen_ids = {latest_existing_event.id} if latest_existing_event else set()
        finally:
            bootstrap_session.close()

        while True:
            if await request.is_disconnected():
                break

            session = SessionLocal()
            try:
                query = select(EventLog).where(EventLog.project_id == project_id)
                if last_seen_at is not None:
                    query = query.where(EventLog.created_at >= last_seen_at)
                events = session.scalars(query.order_by(EventLog.created_at.asc())).all()

                emitted = False
                for event in events:
                    if last_seen_at is not None and event.created_at == last_seen_at and event.id in seen_ids:
                        continue

                    payload = EventLogRead.model_validate(event).model_dump(mode="json")
                    yield (
                        f"id: {event.id}\n"
                        "event: project_event\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                    emitted = True

                    if last_seen_at is None or event.created_at > last_seen_at:
                        last_seen_at = event.created_at
                        seen_ids = {event.id}
                    else:
                        seen_ids.add(event.id)

                if not emitted:
                    yield ": keepalive\n\n"
            finally:
                session.close()

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/projects/{project_id}/stream-token",
    response_model=StreamTokenRead,
)
def issue_project_stream_token(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> StreamTokenRead:
    get_project_or_404(db, project_id)
    token, expires_at = issue_stream_token(project_id=project_id, auth=auth)
    return StreamTokenRead(token=token, expires_at=expires_at)


@router.post(
    "/projects/{project_id}/director/advance",
    response_model=DirectorAdvanceResponse,
)
def advance_director_queue(
    project_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> DirectorAdvanceResponse:
    ensure_role(auth, "Director", "DevOps")
    project = get_project_or_404(db, project_id)
    director_dispatch = dispatch_director_next_ready_task(
        db,
        project,
        trigger="manual_director_advance",
    )
    db.commit()
    if director_dispatch is not None:
        start_codex_execution(project.id, director_dispatch.task_id, director_dispatch.task_run_id)
        summary = (
            f"Директор запустил задачу '{director_dispatch.task_title}' автоматически."
        )
    else:
        summary = "Нет готовых задач для автозапуска или уже есть активный запуск."

    db.refresh(project)
    return DirectorAdvanceResponse(
        project=ProjectRead.model_validate(project),
        dispatched_task_id=(director_dispatch.task_id if director_dispatch is not None else None),
        dispatched_run_id=(director_dispatch.task_run_id if director_dispatch is not None else None),
        summary=summary,
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/actions",
    response_model=TaskActionResponse,
)
def apply_task_action(
    project_id: str,
    task_id: str,
    payload: TaskActionRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> TaskActionResponse:
    ensure_role(auth, "Director", "QAReviewer", "DevOps")
    project = get_project_or_404(db, project_id)
    task = get_task_or_404(db, project_id, task_id)
    ensure_task_runtime(db, project, task)
    workspace, environment, _, _ = load_task_runtime_records(db, task.id)
    evaluation = evaluate_policy_action(
        db,
        project,
        f"task.{payload.action}",
        task=task,
        requested_by=auth.actor,
        requester_role=auth.role,
        metadata={"reason": payload.reason or "", "task_status": task.status},
    )
    if not evaluation.allowed:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=evaluation.approval_decision.summary,
        )

    try:
        result = transition_task(db, project, task, payload.action, payload.reason)
    except OrchestrationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    register_task_run_transition(db, task, payload.action, workspace, environment, result.summary)
    director_dispatch = dispatch_director_next_ready_task(
        db,
        project,
        trigger=f"task_action:{payload.action}",
    )

    db.commit()
    if director_dispatch is not None:
        start_codex_execution(project.id, director_dispatch.task_id, director_dispatch.task_run_id)
        summary = (
            f"{result.summary} Директор автоматически запустил задачу "
            f"'{director_dispatch.task_title}'."
        )
    else:
        summary = result.summary
    db.refresh(project)

    refreshed_task = get_task_or_404(db, project_id, task_id)
    dependency_map = load_dependency_map(db, project_id)
    return TaskActionResponse(
        project=ProjectRead.model_validate(project),
        task=serialize_task(refreshed_task, dependency_map),
        summary=summary,
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/run",
    response_model=TaskExecutionResponse,
)
def run_task_with_codex(
    project_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> TaskExecutionResponse:
    ensure_role(auth, "Director", "DevOps")
    project = get_project_or_404(db, project_id)
    task = get_task_or_404(db, project_id, task_id)
    preflight_result = build_task_preflight(db, project, task)
    if not preflight_result.ready:
        db.commit()
        blocking = [
            check.message
            for check in preflight_result.checks
            if check.status == "fail" and check.blocking
        ]
        detail_message = (
            f"{preflight_result.summary} Blocking checks: {'; '.join(blocking)}"
            if blocking
            else preflight_result.summary
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_message,
        )

    try:
        task_run = prepare_task_run_for_codex(
            db,
            project,
            task,
            requested_by=auth.actor,
            requester_role=auth.role,
        )
    except OrchestrationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    db.refresh(project)

    refreshed_task = get_task_or_404(db, project_id, task_id)
    dependency_map = load_dependency_map(db, project_id)
    serialized_run = serialize_task_run(task_run, refreshed_task)
    start_codex_execution(project.id, refreshed_task.id, task_run.id)

    return TaskExecutionResponse(
        project=ProjectRead.model_validate(project),
        task=serialize_task(refreshed_task, dependency_map),
        run=serialized_run,
        summary=f"Codex execution started for task '{refreshed_task.title}'.",
    )


@router.post(
    "/task-runs/{task_run_id}/cancel",
    response_model=TaskRunCancelResponse,
)
def cancel_task_run(
    task_run_id: str,
    payload: TaskRunCancelRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> TaskRunCancelResponse:
    ensure_role(auth, "Director", "DevOps", "Human")
    task_run = db.get(TaskRun, task_run_id)
    if task_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task run not found")
    task = db.get(Task, task_run.task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    project = db.get(Project, task.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if task_run.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only running task runs can be cancelled (current status: {task_run.status}).",
        )

    try:
        summary = cancel_codex_execution(
            db,
            project,
            task,
            task_run,
            actor=auth.actor,
            reason=payload.reason,
        )
    except OrchestrationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    refreshed_task = db.get(Task, task.id)
    if refreshed_task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    db.refresh(task_run)
    return TaskRunCancelResponse(
        run=serialize_task_run(task_run, refreshed_task),
        summary=summary,
    )


@router.get("/task-runs/{task_run_id}/logs", response_model=TaskRunLogRead)
def get_task_run_logs(task_run_id: str, db: Session = Depends(get_db)) -> TaskRunLogRead:
    task_run = db.get(TaskRun, task_run_id)
    if task_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task run not found")

    return TaskRunLogRead(
        id=task_run.id,
        task_id=task_run.task_id,
        status=task_run.status,
        started_at=task_run.started_at,
        finished_at=task_run.finished_at,
        worktree_path=task_run.worktree_path,
        environment_name=task_run.environment_name,
        stdout=task_run.stdout,
        stderr=task_run.stderr,
    )
