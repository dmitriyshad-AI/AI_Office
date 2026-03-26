from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: Optional[str] = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str]
    status: str
    latest_goal_text: Optional[str]
    created_at: datetime
    updated_at: datetime


class ProjectStatusUpdateResponse(BaseModel):
    project: ProjectRead
    summary: str


class GoalSubmission(BaseModel):
    goal_text: str = Field(min_length=5)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    role: str
    name: str
    status: str
    specialization: str
    current_task_title: Optional[str]
    quality_score: Optional[float]
    average_task_time_seconds: Optional[int]
    created_at: datetime


class TaskRead(BaseModel):
    id: str
    project_id: str
    assigned_agent_id: Optional[str]
    assigned_agent_role: Optional[str]
    task_key: str
    title: str
    brief: str
    acceptance_criteria: list[str]
    status: str
    priority: int
    depends_on_ids: list[str]
    created_at: datetime
    updated_at: datetime


class GoalPlanResponse(BaseModel):
    project: ProjectRead
    summary: str
    created_tasks: list[TaskRead]


class TaskActionRequest(BaseModel):
    action: Literal["start", "complete", "block", "reset"]
    reason: Optional[str] = None


class TaskActionResponse(BaseModel):
    project: ProjectRead
    task: TaskRead
    summary: str


class TaskRunLogRead(BaseModel):
    id: str
    task_id: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    worktree_path: Optional[str]
    environment_name: Optional[str]
    stdout: Optional[str]
    stderr: Optional[str]


class TaskRunRead(BaseModel):
    id: str
    task_id: str
    task_title: str
    task_key: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    worktree_path: Optional[str]
    environment_name: Optional[str]


class ActionIntentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: Optional[str]
    task_run_id: Optional[str]
    dispatch_task_run_id: Optional[str]
    approval_request_id: Optional[str]
    action_key: str
    dispatcher_kind: str
    status: str
    requested_by: str
    payload: dict
    execution_summary: Optional[str]
    last_error: Optional[str]
    attempt_count: int
    max_attempts: int
    next_retry_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]


class TaskExecutionResponse(BaseModel):
    project: ProjectRead
    task: TaskRead
    run: TaskRunRead
    summary: str


class DirectorAdvanceResponse(BaseModel):
    project: ProjectRead
    dispatched_task_id: Optional[str] = None
    dispatched_run_id: Optional[str] = None
    summary: str


class TaskRunCancelRequest(BaseModel):
    actor: str = Field(default="human", min_length=2, max_length=120)
    reason: Optional[str] = Field(default=None, max_length=500)


class TaskRunCancelResponse(BaseModel):
    run: TaskRunRead
    summary: str


class PreflightCheckRead(BaseModel):
    key: str
    status: Literal["pass", "warn", "fail"]
    message: str
    blocking: bool


class TaskPreflightRead(BaseModel):
    ready: bool
    checks: list[PreflightCheckRead]
    summary: str


class TaskWorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: str
    root_path: str
    workspace_path: str
    source_root_path: Optional[str]
    workspace_mode: str
    sync_status: str
    sandbox_mode: str
    state: str
    context_file_path: Optional[str]
    created_at: datetime
    updated_at: datetime


class TaskEnvironmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: str
    name: str
    runtime_kind: str
    runtime_status: str
    base_image: str
    container_name: Optional[str]
    container_id: Optional[str]
    container_workdir: Optional[str]
    source_mount_mode: str
    workspace_mount_mode: str
    network_mode: str
    env_vars: dict
    mounts: list[str]
    created_at: datetime
    updated_at: datetime


class RunPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: str
    policy_level: str
    network_access: str
    filesystem_scope: str
    package_installation_mode: str
    default_risk_level: str
    notes: str
    created_at: datetime
    updated_at: datetime


class TaskRuntimeRead(BaseModel):
    workspace: TaskWorkspaceRead
    environment: TaskEnvironmentRead
    run_policy: RunPolicyRead
    runs: list[TaskRunRead]


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: Optional[str]
    kind: str
    title: str
    content: str
    created_at: datetime


class CallInsightSourcePayload(BaseModel):
    system: str = Field(min_length=2, max_length=120)
    call_record_id: Optional[str] = Field(default=None, max_length=120)
    source_call_id: Optional[str] = Field(default=None, max_length=120)
    source_file: Optional[str] = Field(default=None, max_length=1024)
    source_filename: Optional[str] = Field(default=None, max_length=255)
    started_at: Optional[datetime] = None
    duration_sec: Optional[float] = Field(default=None, ge=0)
    direction: Optional[str] = Field(default=None, max_length=64)
    manager_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=64)


class CallInsightProcessingPayload(BaseModel):
    transcription_status: Optional[str] = Field(default=None, max_length=32)
    resolve_status: Optional[str] = Field(default=None, max_length=32)
    analysis_status: Optional[str] = Field(default=None, max_length=32)
    resolve_quality_score: Optional[float] = None


class CallInsightIdentityHintsPayload(BaseModel):
    phone: Optional[str] = Field(default=None, max_length=64)
    parent_fio: Optional[str] = Field(default=None, max_length=255)
    child_fio: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    grade_current: Optional[str] = Field(default=None, max_length=32)
    school: Optional[str] = Field(default=None, max_length=255)
    preferred_channel: Optional[str] = Field(default=None, max_length=64)


class CallInsightEvidencePayload(BaseModel):
    speaker: Optional[str] = Field(default=None, max_length=120)
    ts: Optional[str] = Field(default=None, max_length=64)
    text: str = Field(min_length=1, max_length=500)


class CallInsightCallSummaryPayload(BaseModel):
    history_summary: str = Field(min_length=5)
    history_short: Optional[str] = None
    evidence: list[CallInsightEvidencePayload] = Field(default_factory=list)


class CallInsightInterestsPayload(BaseModel):
    products: list[str] = Field(default_factory=list)
    format: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    exam_targets: list[str] = Field(default_factory=list)


class CallInsightCommercialPayload(BaseModel):
    price_sensitivity: Optional[Literal["high", "medium", "low"]] = None
    budget: Optional[str] = None
    discount_interest: Optional[bool] = None


class CallInsightNextStepPayload(BaseModel):
    action: Optional[str] = Field(default=None, max_length=255)
    due: Optional[str] = Field(default=None, max_length=120)


class CallInsightSalesPayload(BaseModel):
    interests: CallInsightInterestsPayload = Field(default_factory=CallInsightInterestsPayload)
    commercial: CallInsightCommercialPayload = Field(default_factory=CallInsightCommercialPayload)
    objections: list[str] = Field(default_factory=list)
    next_step: CallInsightNextStepPayload = Field(default_factory=CallInsightNextStepPayload)
    lead_priority: Optional[Literal["hot", "warm", "cold"]] = None
    follow_up_score: Optional[int] = Field(default=None, ge=0, le=100)
    follow_up_reason: Optional[str] = None
    personal_offer: Optional[str] = None
    pain_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CallInsightCreateRequest(BaseModel):
    schema_version: Literal["call_insight_v1"] = "call_insight_v1"
    source: CallInsightSourcePayload
    processing: CallInsightProcessingPayload = Field(default_factory=CallInsightProcessingPayload)
    identity_hints: CallInsightIdentityHintsPayload = Field(
        default_factory=CallInsightIdentityHintsPayload
    )
    call_summary: CallInsightCallSummaryPayload
    sales_insight: CallInsightSalesPayload
    quality_flags: dict[str, Any] = Field(default_factory=dict)
    raw_analysis: dict[str, Any] = Field(default_factory=dict)


class CallInsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_system: str
    source_key: str
    source_call_id: Optional[str]
    source_record_id: Optional[str]
    source_file: Optional[str]
    source_filename: Optional[str]
    phone: Optional[str]
    manager_name: Optional[str]
    started_at: Optional[datetime]
    duration_sec: Optional[float]
    history_summary: str
    lead_priority: Optional[str]
    follow_up_score: Optional[int]
    processing_status: Optional[str]
    status: str
    match_status: str
    matched_amo_contact_id: Optional[int]
    review_status: str
    review_reason: Optional[str]
    review_summary: Optional[str]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    sent_by: Optional[str]
    sent_at: Optional[datetime]
    send_result: Optional[dict[str, Any]]
    error_message: Optional[str]
    payload: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


class CallInsightCreateResponse(BaseModel):
    insight: CallInsightRead
    summary: str


class CrmSyncPreviewCreateRequest(BaseModel):
    student_id: str = Field(min_length=2, max_length=120)
    lookup_mode: Literal["auto", "contact_id", "phone", "email", "full_name"] = "auto"
    amo_entity_type: Literal["contact", "lead"] = "contact"
    amo_entity_id: Optional[str] = Field(default=None, max_length=120)
    field_mapping: Optional[dict[str, str]] = None


class CrmSyncPreviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_student_id: str
    source_system: str
    amo_entity_type: str
    amo_entity_id: Optional[str]
    source_payload: dict
    canonical_payload: dict
    amo_field_payload: dict
    field_mapping: dict
    analysis_summary: str
    status: str
    review_status: str
    review_reason: Optional[str]
    review_summary: Optional[str]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    created_by: str
    sent_by: Optional[str]
    sent_at: Optional[datetime]
    send_result: Optional[dict]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class CrmSyncSendRequest(BaseModel):
    amo_entity_id: Optional[str] = Field(default=None, max_length=120)
    selected_fields: Optional[list[str]] = None
    field_overrides: Optional[dict[str, Any]] = None

    @field_validator("amo_entity_id")
    @classmethod
    def normalize_amo_entity_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None

    @field_validator("selected_fields")
    @classmethod
    def normalize_selected_fields(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_field in value:
            candidate = str(raw_field).strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized

    @field_validator("field_overrides")
    @classmethod
    def normalize_field_overrides(
        cls,
        value: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                continue
            normalized[key] = raw_value
        return normalized


class CrmSyncSendResponse(BaseModel):
    preview: CrmSyncPreviewRead
    summary: str


class RecordReviewResolveRequest(BaseModel):
    outcome: Literal[
        "approved",
        "needs_correction",
        "family_case",
        "duplicate",
        "insufficient_data",
        "rejected",
    ]
    summary: Optional[str] = Field(default=None, max_length=2000)


class CrmReviewResolveRequest(RecordReviewResolveRequest):
    amo_entity_id: Optional[str] = Field(default=None, max_length=120)

    @field_validator("amo_entity_id")
    @classmethod
    def normalize_crm_amo_entity_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None


class CrmReviewResolveResponse(BaseModel):
    preview: CrmSyncPreviewRead
    summary: str


class CallInsightReviewResolveRequest(RecordReviewResolveRequest):
    matched_amo_contact_id: Optional[int] = Field(default=None, ge=1)


class CallInsightReviewResolveResponse(BaseModel):
    insight: CallInsightRead
    summary: str


class CallInsightSendRequest(BaseModel):
    matched_amo_contact_id: Optional[int] = Field(default=None, ge=1)
    field_overrides: Optional[dict[str, Any]] = None

    @field_validator("field_overrides")
    @classmethod
    def normalize_call_field_overrides(
        cls,
        value: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                continue
            normalized[key] = raw_value
        return normalized


class CallInsightSendResponse(BaseModel):
    insight: CallInsightRead
    summary: str


class ReviewFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: str
    task_review_id: str
    severity: str
    title: str
    details: str
    suggested_fix: Optional[str]
    created_at: datetime


class TaskReviewRead(BaseModel):
    id: str
    project_id: str
    task_id: str
    task_run_id: Optional[str]
    reviewer_agent_id: Optional[str]
    reviewer_role: Optional[str]
    reviewer_name: Optional[str]
    status: str
    recommendation: str
    summary: str
    severity_counts: dict
    findings: list[ReviewFindingRead]
    created_at: datetime
    completed_at: Optional[datetime]


class ApprovalRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: Optional[str]
    approval_policy_id: Optional[str]
    risk_assessment_id: Optional[str]
    action: str
    risk_level: str
    status: str
    reason: str
    requested_by: str
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]
    resolution_summary: Optional[str]
    created_at: datetime


class ApprovalPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    action_key: str
    scope: str
    default_risk_level: str
    approval_mode: str
    allowed_roles: list[str]
    allowlist: list[str]
    denylist: list[str]
    rationale: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class RiskAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: Optional[str]
    approval_policy_id: Optional[str]
    action_key: str
    requested_by: str
    risk_level: str
    approval_mode: str
    status: str
    rationale: str
    details: dict
    created_at: datetime


class ApprovalDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: Optional[str]
    risk_assessment_id: str
    approval_request_id: Optional[str]
    action_key: str
    risk_level: str
    actor: str
    outcome: str
    summary: str
    created_at: datetime


class PolicyCheckRequest(BaseModel):
    action_key: str = Field(min_length=3, max_length=120)
    task_id: Optional[str] = None
    task_run_id: Optional[str] = None
    requested_by: str = Field(default="director", min_length=2, max_length=120)
    metadata: dict = Field(default_factory=dict)


class PolicyCheckResponse(BaseModel):
    allowed: bool
    approval_policy: Optional[ApprovalPolicyRead]
    risk_assessment: RiskAssessmentRead
    approval_decision: ApprovalDecisionRead
    approval_request: Optional[ApprovalRequestRead]
    action_intent: Optional[ActionIntentRead]


class ApprovalResolveRequest(BaseModel):
    outcome: Literal["approved", "rejected"]
    summary: Optional[str] = Field(default=None, max_length=500)
    actor: str = Field(default="human", min_length=2, max_length=120)


class ApprovalResolveResponse(BaseModel):
    approval_request: ApprovalRequestRead
    approval_decision: ApprovalDecisionRead
    risk_assessment: Optional[RiskAssessmentRead]
    action_intent: Optional[ActionIntentRead]
    summary: str


class ActionIntentRetryRequest(BaseModel):
    actor: str = Field(default="director", min_length=2, max_length=120)
    ignore_backoff: bool = True


class ActionIntentRetryResponse(BaseModel):
    action_intent: ActionIntentRead
    summary: str


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    role: str
    content: str
    created_at: datetime


class EventLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: Optional[str]
    event_type: str
    payload: dict
    created_at: datetime


class StreamTokenRead(BaseModel):
    token: str
    expires_at: datetime
