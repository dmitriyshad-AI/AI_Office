from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def generate_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    latest_goal_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    agents: Mapped[list["Agent"]] = relationship(back_populates="project")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")
    messages: Mapped[list["Message"]] = relationship(back_populates="project")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="project")
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(back_populates="project")
    approval_policies: Mapped[list["ApprovalPolicy"]] = relationship(back_populates="project")
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="project")
    approval_decisions: Mapped[list["ApprovalDecision"]] = relationship(back_populates="project")
    event_logs: Mapped[list["EventLog"]] = relationship(back_populates="project")
    task_workspaces: Mapped[list["TaskWorkspace"]] = relationship(back_populates="project")
    task_environments: Mapped[list["TaskEnvironment"]] = relationship(back_populates="project")
    run_policies: Mapped[list["RunPolicy"]] = relationship(back_populates="project")
    task_reviews: Mapped[list["TaskReview"]] = relationship(back_populates="project")
    review_findings: Mapped[list["ReviewFinding"]] = relationship(back_populates="project")
    action_intents: Mapped[list["ActionIntent"]] = relationship(back_populates="project")
    crm_sync_previews: Mapped[list["CrmSyncPreview"]] = relationship(back_populates="project")
    call_insights: Mapped[list["CallInsight"]] = relationship(back_populates="project")


class AmoIntegrationConnection(Base):
    __tablename__ = "amo_integration_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    integration_mode: Mapped[str] = mapped_column(String(32), default="external")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    state: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    account_base_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    account_subdomain: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    client_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    secrets_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_secrets_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_callback_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    contact_field_catalog: Mapped[Optional[list[dict]]] = mapped_column(JSON, nullable=True)
    contact_field_catalog_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    role: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(50), default="idle")
    specialization: Mapped[str] = mapped_column(Text)
    current_task_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_task_time_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="agents")
    tasks: Mapped[list["Task"]] = relationship(back_populates="assigned_agent")
    task_reviews: Mapped[list["TaskReview"]] = relationship(back_populates="reviewer_agent")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    assigned_agent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    task_key: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(200))
    brief: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), default="planned")
    priority: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="tasks")
    assigned_agent: Mapped[Optional["Agent"]] = relationship(back_populates="tasks")
    dependencies: Mapped[list["TaskDependency"]] = relationship(
        back_populates="task", foreign_keys="TaskDependency.task_id"
    )
    task_runs: Mapped[list["TaskRun"]] = relationship(back_populates="task")
    task_workspace: Mapped[Optional["TaskWorkspace"]] = relationship(back_populates="task")
    task_environment: Mapped[Optional["TaskEnvironment"]] = relationship(back_populates="task")
    run_policy: Mapped[Optional["RunPolicy"]] = relationship(back_populates="task")
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(back_populates="task")
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="task")
    approval_decisions: Mapped[list["ApprovalDecision"]] = relationship(back_populates="task")
    task_reviews: Mapped[list["TaskReview"]] = relationship(back_populates="task")
    review_findings: Mapped[list["ReviewFinding"]] = relationship(back_populates="task")
    action_intents: Mapped[list["ActionIntent"]] = relationship(back_populates="task")


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    depends_on_task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))

    task: Mapped["Task"] = relationship(back_populates="dependencies", foreign_keys=[task_id])


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    status: Mapped[str] = mapped_column(String(50), default="planned")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worktree_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    environment_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="task_runs")
    task_reviews: Mapped[list["TaskReview"]] = relationship(back_populates="task_run")
    action_intents: Mapped[list["ActionIntent"]] = relationship(
        back_populates="task_run",
        foreign_keys="ActionIntent.task_run_id",
    )


class TaskWorkspace(Base):
    __tablename__ = "task_workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    root_path: Mapped[str] = mapped_column(String(255))
    workspace_path: Mapped[str] = mapped_column(String(255))
    source_root_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    workspace_mode: Mapped[str] = mapped_column(String(50), default="snapshot-copy")
    sync_status: Mapped[str] = mapped_column(String(50), default="seeded")
    sandbox_mode: Mapped[str] = mapped_column(String(50), default="workspace-write")
    state: Mapped[str] = mapped_column(String(50), default="provisioned")
    context_file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="task_workspaces")
    task: Mapped["Task"] = relationship(back_populates="task_workspace")


class TaskEnvironment(Base):
    __tablename__ = "task_environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    runtime_kind: Mapped[str] = mapped_column(String(80))
    runtime_status: Mapped[str] = mapped_column(String(50), default="ready")
    base_image: Mapped[str] = mapped_column(String(120))
    container_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    container_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    container_workdir: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_mount_mode: Mapped[str] = mapped_column(String(80), default="read-only")
    workspace_mount_mode: Mapped[str] = mapped_column(String(80), default="read-write")
    network_mode: Mapped[str] = mapped_column(String(80), default="restricted")
    env_vars: Mapped[dict] = mapped_column(JSON)
    mounts: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="task_environments")
    task: Mapped["Task"] = relationship(back_populates="task_environment")


class RunPolicy(Base):
    __tablename__ = "run_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    policy_level: Mapped[str] = mapped_column(String(50), default="task-runtime")
    network_access: Mapped[str] = mapped_column(String(50), default="restricted")
    filesystem_scope: Mapped[str] = mapped_column(String(80), default="task-workspace-only")
    package_installation_mode: Mapped[str] = mapped_column(
        String(80), default="allowlist-only"
    )
    default_risk_level: Mapped[str] = mapped_column(String(50), default="medium")
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="run_policies")
    task: Mapped["Task"] = relationship(back_populates="run_policy")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="artifacts")


class CrmSyncPreview(Base):
    __tablename__ = "crm_sync_previews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_student_id: Mapped[str] = mapped_column(String(120), index=True)
    source_system: Mapped[str] = mapped_column(String(80), default="tallanto")
    amo_entity_type: Mapped[str] = mapped_column(String(50), default="contact")
    amo_entity_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source_payload: Mapped[dict] = mapped_column(JSON)
    canonical_payload: Mapped[dict] = mapped_column(JSON)
    amo_field_payload: Mapped[dict] = mapped_column(JSON)
    field_mapping: Mapped[dict] = mapped_column(JSON)
    analysis_summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="previewed")
    review_status: Mapped[str] = mapped_column(String(32), default="not_required")
    review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120))
    sent_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    send_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="crm_sync_previews")


class CallInsight(Base):
    __tablename__ = "call_insights"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_system",
            "source_key",
            name="uq_call_insights_project_source_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_system: Mapped[str] = mapped_column(String(80), index=True)
    source_key: Mapped[str] = mapped_column(String(255), index=True)
    source_call_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    source_record_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    source_file: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    source_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    manager_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    history_summary: Mapped[str] = mapped_column(Text)
    lead_priority: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    follow_up_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="ingested")
    match_status: Mapped[str] = mapped_column(String(50), default="pending_match")
    matched_amo_contact_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    send_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="call_insights")


class TaskReview(Base):
    __tablename__ = "task_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    task_run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    reviewer_agent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), default="pending")
    recommendation: Mapped[str] = mapped_column(String(50), default="pending")
    summary: Mapped[str] = mapped_column(Text)
    severity_counts: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="task_reviews")
    task: Mapped["Task"] = relationship(back_populates="task_reviews")
    task_run: Mapped[Optional["TaskRun"]] = relationship(back_populates="task_reviews")
    reviewer_agent: Mapped[Optional["Agent"]] = relationship(back_populates="task_reviews")
    findings: Mapped[list["ReviewFinding"]] = relationship(back_populates="task_review")


class ReviewFinding(Base):
    __tablename__ = "review_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    task_review_id: Mapped[str] = mapped_column(ForeignKey("task_reviews.id"))
    severity: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str] = mapped_column(Text)
    suggested_fix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="review_findings")
    task: Mapped["Task"] = relationship(back_populates="review_findings")
    task_review: Mapped["TaskReview"] = relationship(back_populates="findings")


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    approval_policy_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("approval_policies.id"), nullable=True
    )
    risk_assessment_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("risk_assessments.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(200))
    risk_level: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(120))
    resolved_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="approval_requests")
    task: Mapped[Optional["Task"]] = relationship(back_populates="approval_requests")
    approval_policy: Mapped[Optional["ApprovalPolicy"]] = relationship(
        back_populates="approval_requests"
    )
    risk_assessment: Mapped[Optional["RiskAssessment"]] = relationship(
        back_populates="approval_request"
    )
    approval_decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="approval_request"
    )
    action_intents: Mapped[list["ActionIntent"]] = relationship(
        back_populates="approval_request"
    )


class ApprovalPolicy(Base):
    __tablename__ = "approval_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    action_key: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(80))
    default_risk_level: Mapped[str] = mapped_column(String(50))
    approval_mode: Mapped[str] = mapped_column(String(50))
    allowed_roles: Mapped[list[str]] = mapped_column(JSON)
    allowlist: Mapped[list[str]] = mapped_column(JSON)
    denylist: Mapped[list[str]] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="approval_policies")
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="approval_policy"
    )
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(
        back_populates="approval_policy"
    )


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    approval_policy_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("approval_policies.id"), nullable=True
    )
    action_key: Mapped[str] = mapped_column(String(120))
    requested_by: Mapped[str] = mapped_column(String(120))
    risk_level: Mapped[str] = mapped_column(String(50))
    approval_mode: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    rationale: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="risk_assessments")
    task: Mapped[Optional["Task"]] = relationship(back_populates="risk_assessments")
    approval_policy: Mapped[Optional["ApprovalPolicy"]] = relationship(
        back_populates="risk_assessments"
    )
    approval_request: Mapped[Optional["ApprovalRequest"]] = relationship(
        back_populates="risk_assessment"
    )
    approval_decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="risk_assessment"
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    risk_assessment_id: Mapped[str] = mapped_column(ForeignKey("risk_assessments.id"))
    approval_request_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("approval_requests.id"), nullable=True
    )
    action_key: Mapped[str] = mapped_column(String(120))
    risk_level: Mapped[str] = mapped_column(String(50))
    actor: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="approval_decisions")
    task: Mapped[Optional["Task"]] = relationship(back_populates="approval_decisions")
    risk_assessment: Mapped["RiskAssessment"] = relationship(
        back_populates="approval_decisions"
    )
    approval_request: Mapped[Optional["ApprovalRequest"]] = relationship(
        back_populates="approval_decisions"
    )


class ActionIntent(Base):
    __tablename__ = "action_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    task_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("task_runs.id"), nullable=True
    )
    dispatch_task_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("task_runs.id"), nullable=True
    )
    approval_request_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("approval_requests.id"), nullable=True
    )
    action_key: Mapped[str] = mapped_column(String(120))
    dispatcher_kind: Mapped[str] = mapped_column(String(80), default="runtime-dispatcher")
    status: Mapped[str] = mapped_column(String(50), default="pending_approval")
    requested_by: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    execution_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="action_intents")
    task: Mapped[Optional["Task"]] = relationship(back_populates="action_intents")
    task_run: Mapped[Optional["TaskRun"]] = relationship(
        back_populates="action_intents",
        foreign_keys=[task_run_id],
    )
    dispatch_task_run: Mapped[Optional["TaskRun"]] = relationship(
        foreign_keys=[dispatch_task_run_id]
    )
    approval_request: Mapped[Optional["ApprovalRequest"]] = relationship(
        back_populates="action_intents"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    role: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="messages")


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="event_logs")
