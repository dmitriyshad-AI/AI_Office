from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.action_intents import (
    create_action_intent,
    find_action_intent_for_approval_request,
    reject_action_intent,
    resume_action_intent,
)
from app.config import get_settings
from app.models import (
    ActionIntent,
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    Project,
    RiskAssessment,
    Task,
    TaskRun,
    utc_now,
)
from app.orchestration import log_event


settings = get_settings()


def _is_protected_relative_path(relative_path: str) -> bool:
    normalized = relative_path.strip().replace("\\", "/")
    if not normalized:
        return True
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        return True

    path = PurePosixPath(normalized)
    if not path.parts:
        return True

    for part in path.parts:
        if part in {".git", "node_modules", "dist", "build", "__pycache__"}:
            return True
        if part == ".env" or part.startswith(".env."):
            return True
        if part.endswith(".egg-info"):
            return True
    return False


POLICY_BLUEPRINTS = [
    {
        "action_key": "runtime.provision",
        "scope": "runtime",
        "default_risk_level": "low",
        "approval_mode": "auto",
        "allowed_roles": ["Director", "DevOps", "System"],
        "allowlist": ["task-workspace"],
        "denylist": ["/var/run/docker.sock", "/Users/", "~/.ssh"],
        "rationale": "Provision isolated runtime metadata inside the task workspace.",
    },
    {
        "action_key": "task.start",
        "scope": "task",
        "default_risk_level": "low",
        "approval_mode": "auto",
        "allowed_roles": ["Director"],
        "allowlist": ["ready-task"],
        "denylist": [],
        "rationale": "Start a ready task inside an already provisioned workspace.",
    },
    {
        "action_key": "task.complete",
        "scope": "task",
        "default_risk_level": "low",
        "approval_mode": "auto",
        "allowed_roles": ["Director"],
        "allowlist": ["running-task"],
        "denylist": [],
        "rationale": "Complete a running task without changing sandbox boundaries.",
    },
    {
        "action_key": "task.block",
        "scope": "task",
        "default_risk_level": "medium",
        "approval_mode": "director",
        "allowed_roles": ["Director", "QAReviewer"],
        "allowlist": ["director-console"],
        "denylist": [],
        "rationale": "Blocking a task changes project flow, but stays inside orchestration scope.",
    },
    {
        "action_key": "task.reset",
        "scope": "task",
        "default_risk_level": "medium",
        "approval_mode": "director",
        "allowed_roles": ["Director"],
        "allowlist": ["director-console"],
        "denylist": [],
        "rationale": "Resetting a task re-opens execution and must be routed through the director.",
    },
    {
        "action_key": "runtime.install_package",
        "scope": "runtime",
        "default_risk_level": "medium",
        "approval_mode": "director",
        "allowed_roles": ["Director", "DevOps", "BackendEngineer"],
        "allowlist": ["pypi.org", "registry.npmjs.org"],
        "denylist": ["/Users/", "~/.ssh"],
        "rationale": "Package installation is allowed only from approved registries inside the sandbox.",
    },
    {
        "action_key": "runtime.write_workspace",
        "scope": "runtime",
        "default_risk_level": "medium",
        "approval_mode": "director",
        "allowed_roles": ["Director", "FrontendEngineer", "BackendEngineer", "DevOps"],
        "allowlist": ["task-workspace-only"],
        "denylist": ["..", "/Users/", "~/.ssh", "/etc/"],
        "rationale": "Workspace writes are allowed only inside the task-specific runtime directory.",
    },
    {
        "action_key": "runtime.promote_workspace",
        "scope": "runtime",
        "default_risk_level": "medium",
        "approval_mode": "director",
        "allowed_roles": ["Director"],
        "allowlist": ["source-workspace-only"],
        "denylist": [".env", ".env.", ".git", "node_modules", "dist", "build", "/etc/", "~/.ssh"],
        "rationale": "Promoting reviewed workspace changes back to the source project is allowed only for safe project files.",
    },
    {
        "action_key": "runtime.host_access",
        "scope": "runtime",
        "default_risk_level": "high",
        "approval_mode": "human",
        "allowed_roles": ["Director"],
        "allowlist": [],
        "denylist": ["/Users/", "~/.ssh", "/var/run/docker.sock", "/etc/"],
        "rationale": "Host access is outside the sandbox boundary and always requires human approval.",
    },
    {
        "action_key": "runtime.secret_write",
        "scope": "runtime",
        "default_risk_level": "high",
        "approval_mode": "human",
        "allowed_roles": ["Director"],
        "allowlist": [],
        "denylist": [".env", "secrets", "~/.ssh", "/etc/"],
        "rationale": "Writing secrets or credentials requires explicit human approval.",
    },
    {
        "action_key": "crm.tallanto.read",
        "scope": "integration",
        "default_risk_level": "low",
        "approval_mode": "auto",
        "allowed_roles": ["Director", "DevOps", "BackendEngineer", "System"],
        "allowlist": ["tallanto-api"],
        "denylist": [],
        "rationale": "Reading source CRM records is allowed for controlled integration preview.",
    },
    {
        "action_key": "crm.preview.create",
        "scope": "integration",
        "default_risk_level": "low",
        "approval_mode": "auto",
        "allowed_roles": ["Director", "DevOps", "BackendEngineer"],
        "allowlist": ["crm-bridge"],
        "denylist": [],
        "rationale": "Preview creation is read-oriented and does not mutate external systems.",
    },
    {
        "action_key": "crm.amo.write",
        "scope": "integration",
        "default_risk_level": "medium",
        "approval_mode": "director",
        "allowed_roles": ["Director", "Human", "DevOps"],
        "allowlist": ["amo-api"],
        "denylist": [],
        "rationale": "AMO writes are pointwise and audited through explicit UI action.",
    },
    {
        "action_key": "calls.insight.ingest",
        "scope": "integration",
        "default_risk_level": "low",
        "approval_mode": "auto",
        "allowed_roles": ["Director", "DevOps", "BackendEngineer", "System"],
        "allowlist": ["local-mango-engine"],
        "denylist": [],
        "rationale": "Ingesting already processed call insights is an internal audited data handoff.",
    },
    {
        "action_key": "calls.insight.read",
        "scope": "integration",
        "default_risk_level": "low",
        "approval_mode": "auto",
        "allowed_roles": ["Director", "Human", "DevOps", "BackendEngineer", "System"],
        "allowlist": ["calls-module"],
        "denylist": [],
        "rationale": "Reading ingested call insights is safe and stays inside the office workspace.",
    },
    {
        "action_key": "calls.amo.write",
        "scope": "integration",
        "default_risk_level": "medium",
        "approval_mode": "director",
        "allowed_roles": ["Director", "Human", "DevOps"],
        "allowlist": ["amo-api"],
        "denylist": [],
        "rationale": "Call insights may update AMO only after explicit review and audit.",
    },
]


@dataclass
class PolicyEvaluationResult:
    allowed: bool
    approval_policy: Optional[ApprovalPolicy]
    risk_assessment: RiskAssessment
    approval_decision: ApprovalDecision
    approval_request: Optional[ApprovalRequest]
    action_intent: Optional[ActionIntent]


@dataclass
class ApprovalResolutionResult:
    approval_request: ApprovalRequest
    approval_decision: ApprovalDecision
    risk_assessment: Optional[RiskAssessment]
    action_intent: Optional[ActionIntent]
    summary: str


def ensure_project_policies(session: Session, project: Project) -> dict[str, ApprovalPolicy]:
    existing_policies = {
        policy.action_key: policy
        for policy in session.scalars(
            select(ApprovalPolicy).where(ApprovalPolicy.project_id == project.id)
        ).all()
    }

    for blueprint in POLICY_BLUEPRINTS:
        policy = existing_policies.get(blueprint["action_key"])
        if policy is None:
            policy = ApprovalPolicy(project_id=project.id, **blueprint, enabled=True)
            session.add(policy)
            session.flush()
            existing_policies[policy.action_key] = policy
            continue

        policy.scope = blueprint["scope"]
        policy.default_risk_level = blueprint["default_risk_level"]
        policy.approval_mode = blueprint["approval_mode"]
        policy.allowed_roles = blueprint["allowed_roles"]
        policy.allowlist = blueprint["allowlist"]
        policy.denylist = blueprint["denylist"]
        policy.rationale = blueprint["rationale"]
        policy.enabled = True

    return existing_policies


def _resolve_policy(
    policy: Optional[ApprovalPolicy], metadata: dict
) -> tuple[str, str, str]:
    if policy is None:
        return (
            "high",
            "human",
            "No matching policy exists for this action. Escalated by default.",
        )

    risk_level = policy.default_risk_level
    approval_mode = policy.approval_mode
    reasons = [policy.rationale]

    target_path = str(metadata.get("target_path", ""))
    workspace_path = str(metadata.get("workspace_path", ""))
    registry = str(metadata.get("registry", ""))
    writes_inside_workspace = (
        policy is not None
        and policy.action_key == "runtime.write_workspace"
        and bool(target_path)
        and bool(workspace_path)
        and target_path.startswith(workspace_path)
    )

    if target_path:
        matched_deny = next(
            (
                fragment
                for fragment in policy.denylist
                if fragment
                and fragment in target_path
                and not (writes_inside_workspace and fragment == "/Users/")
            ),
            None,
        )
        if matched_deny is not None:
            risk_level = "high"
            approval_mode = "human"
            reasons.append(f"Target path matches denylist fragment '{matched_deny}'.")

    if policy.action_key == "runtime.write_workspace" and target_path and workspace_path:
        if not target_path.startswith(workspace_path):
            risk_level = "high"
            approval_mode = "human"
            reasons.append("Requested path is outside the task workspace.")
        else:
            reasons.append("Requested path stays inside the task workspace.")

    if policy.action_key == "runtime.promote_workspace":
        source_root_path = str(metadata.get("source_root_path", ""))
        changed_paths = metadata.get("relative_paths") or []
        if not source_root_path:
            risk_level = "high"
            approval_mode = "human"
            reasons.append("Source workspace root is missing for workspace promotion.")
        protected_paths = [
            path
            for path in changed_paths
            if isinstance(path, str) and _is_protected_relative_path(path)
        ]
        if protected_paths:
            risk_level = "high"
            approval_mode = "human"
            reasons.append(
                "Workspace promotion includes protected paths: "
                + ", ".join(protected_paths[:5])
            )
        else:
            reasons.append(
                f"Workspace promotion is limited to {len(changed_paths)} reviewed project file(s)."
            )

    if policy.action_key == "runtime.install_package":
        if registry and registry not in policy.allowlist:
            risk_level = "high"
            approval_mode = "human"
            reasons.append(f"Registry '{registry}' is outside the allowlist.")
        else:
            reasons.append(
                f"Registry '{registry or 'unspecified'}' is allowed by the policy."
            )

    if policy.action_key in {"crm.amo.write", "calls.amo.write"}:
        amo_mode = str(metadata.get("amo_mode", settings.crm_amo_mode)).strip().lower()
        review_status = str(metadata.get("review_status", "")).strip().lower()
        if amo_mode != "mock" and review_status != "approved":
            risk_level = "high"
            approval_mode = "human"
            reasons.append(
                "AMO write in HTTP mode requires explicit review approval before execution."
            )
        elif amo_mode != "mock":
            reasons.append("AMO write is allowed because the record is explicitly approved in review queue.")
        else:
            reasons.append("AMO write runs in mock mode.")

    return risk_level, approval_mode, " ".join(reasons)


def _find_matching_human_approval(
    session: Session,
    project: Project,
    action_key: str,
    task: Optional[Task],
    metadata: dict,
) -> Optional[ApprovalRequest]:
    task_id = task.id if task is not None else None
    requests = session.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.project_id == project.id,
            ApprovalRequest.action == action_key,
            ApprovalRequest.task_id == task_id,
        )
        .options(selectinload(ApprovalRequest.risk_assessment))
        .order_by(ApprovalRequest.created_at.desc())
    ).all()

    for approval_request in requests:
        if (
            approval_request.risk_assessment is not None
            and approval_request.risk_assessment.details == metadata
        ):
            return approval_request
    return None


def resolve_approval_request(
    session: Session,
    project: Project,
    approval_request: ApprovalRequest,
    *,
    outcome: str,
    actor: str,
    summary: Optional[str] = None,
) -> ApprovalResolutionResult:
    if approval_request.project_id != project.id:
        raise ValueError("Approval request does not belong to the project.")
    if approval_request.status != "pending":
        raise ValueError("Only pending approval requests can be resolved.")

    if outcome not in {"approved", "rejected"}:
        raise ValueError("Unsupported approval outcome.")

    resolution_summary = summary or (
        f"Human {outcome} action '{approval_request.action}'."
    )
    approval_request.status = outcome
    approval_request.resolved_by = actor
    approval_request.resolved_at = utc_now()
    approval_request.resolution_summary = resolution_summary

    if approval_request.risk_assessment is not None:
        approval_request.risk_assessment.status = outcome

    decision = ApprovalDecision(
        project_id=project.id,
        task_id=approval_request.task_id,
        risk_assessment_id=approval_request.risk_assessment_id,
        approval_request_id=approval_request.id,
        action_key=approval_request.action,
        risk_level=approval_request.risk_level,
        actor=actor,
        outcome=outcome,
        summary=resolution_summary,
    )
    session.add(decision)
    intent_result = None
    if outcome == "approved":
        intent_result = resume_action_intent(session, project, approval_request)
    else:
        intent_result = reject_action_intent(session, project, approval_request, resolution_summary)

    log_event(
        session,
        project.id,
        "approval_resolved",
        {
            "approval_request_id": approval_request.id,
            "action_key": approval_request.action,
            "outcome": outcome,
            "actor": actor,
        },
        task_id=approval_request.task_id,
    )
    log_event(
        session,
        project.id,
        f"approval_{outcome}",
        {
            "approval_request_id": approval_request.id,
            "action_key": approval_request.action,
            "actor": actor,
        },
        task_id=approval_request.task_id,
    )

    return ApprovalResolutionResult(
        approval_request=approval_request,
        approval_decision=decision,
        risk_assessment=approval_request.risk_assessment,
        action_intent=intent_result.action_intent if intent_result is not None else None,
        summary=intent_result.summary if intent_result is not None else resolution_summary,
    )


def evaluate_policy_action(
    session: Session,
    project: Project,
    action_key: str,
    *,
    task: Optional[Task] = None,
    task_run: Optional[TaskRun] = None,
    requested_by: str,
    requester_role: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> PolicyEvaluationResult:
    metadata = dict(metadata or {})
    if requester_role and "requester_role" not in metadata:
        metadata["requester_role"] = requester_role
    policies = ensure_project_policies(session, project)
    policy = policies.get(action_key)
    risk_level, approval_mode, rationale = _resolve_policy(policy, metadata)
    role_allowed = True
    if (
        policy is not None
        and requester_role is not None
        and bool(policy.allowed_roles)
        and requester_role not in policy.allowed_roles
    ):
        role_allowed = False
        risk_level = "high"
        approval_mode = "denied"
        rationale = (
            f"{rationale} Requester role '{requester_role}' is not allowed for "
            f"'{action_key}'. Allowed roles: {', '.join(policy.allowed_roles)}."
        )
    approval_request = None
    created_approval_request = False
    allowed = False
    actor = "director"
    outcome = "pending_human"
    summary = f"Escalated '{action_key}' for human approval."
    status = "pending_human"

    if not role_allowed:
        actor = "policy"
        outcome = "rejected"
        status = "rejected"
        summary = (
            f"Policy rejected '{action_key}' for role "
            f"'{requester_role or 'unknown'}'."
        )
        allowed = False
    elif approval_mode == "auto":
        actor = "system"
        outcome = "approved"
        summary = f"Auto-approved by policy for action '{action_key}'."
        status = "approved"
        allowed = True
    elif approval_mode == "director":
        actor = "director"
        outcome = "approved"
        summary = f"Director auto-approved medium-risk action '{action_key}'."
        status = "approved"
        allowed = True
    else:
        approval_request = _find_matching_human_approval(
            session,
            project,
            action_key,
            task,
            metadata,
        )
        if approval_request is not None:
            if approval_request.status == "approved":
                actor = approval_request.resolved_by or "human"
                outcome = "approved"
                status = "approved"
                summary = f"Reused approved human decision for '{action_key}'."
                allowed = True
            elif approval_request.status == "rejected":
                actor = approval_request.resolved_by or "human"
                outcome = "rejected"
                status = "rejected"
                summary = f"Human rejected '{action_key}'."
                allowed = False
            else:
                actor = "director"
                outcome = "pending_human"
                status = "pending_human"
                summary = f"'{action_key}' is already waiting for human approval."
                allowed = False

    assessment = RiskAssessment(
        project_id=project.id,
        task_id=task.id if task is not None else None,
        approval_policy_id=policy.id if policy is not None else None,
        action_key=action_key,
        requested_by=requested_by,
        risk_level=risk_level,
        approval_mode=approval_mode,
        status=status,
        rationale=rationale,
        details=metadata,
    )
    session.add(assessment)
    session.flush()

    if approval_mode == "human" and approval_request is None:
        approval_request = ApprovalRequest(
            project_id=project.id,
            task_id=task.id if task is not None else None,
            approval_policy_id=policy.id if policy is not None else None,
            risk_assessment_id=assessment.id,
            action=action_key,
            risk_level=risk_level,
            status="pending",
            reason=rationale,
            requested_by=requested_by,
        )
        session.add(approval_request)
        session.flush()
        created_approval_request = True

    action_intent = None
    if approval_mode == "human" and approval_request is not None:
        if created_approval_request:
            action_intent = create_action_intent(
                session,
                project,
                action_key,
                task=task,
                task_run=task_run,
                approval_request=approval_request,
                requested_by=requested_by,
                metadata=metadata,
            )
        else:
            action_intent = find_action_intent_for_approval_request(session, approval_request.id)

    decision = ApprovalDecision(
        project_id=project.id,
        task_id=task.id if task is not None else None,
        risk_assessment_id=assessment.id,
        approval_request_id=approval_request.id if approval_request is not None else None,
        action_key=action_key,
        risk_level=risk_level,
        actor=actor,
        outcome=outcome,
        summary=summary,
    )
    session.add(decision)

    log_event(
        session,
        project.id,
        "risk_assessed",
        {
            "action_key": action_key,
            "risk_level": risk_level,
            "approval_mode": approval_mode,
            "requested_by": requested_by,
            "requester_role": requester_role,
        },
        task_id=task.id if task is not None else None,
    )
    log_event(
        session,
        project.id,
        "approval_decided",
        {
            "action_key": action_key,
            "actor": actor,
            "outcome": outcome,
            "risk_level": risk_level,
        },
        task_id=task.id if task is not None else None,
    )
    if created_approval_request:
        log_event(
            session,
            project.id,
            "approval_requested",
            {
                "action_key": action_key,
                "risk_level": risk_level,
                "requested_by": requested_by,
            },
            task_id=task.id if task is not None else None,
        )

    return PolicyEvaluationResult(
        allowed=allowed,
        approval_policy=policy,
        risk_assessment=assessment,
        approval_decision=decision,
        approval_request=approval_request,
        action_intent=action_intent,
    )
