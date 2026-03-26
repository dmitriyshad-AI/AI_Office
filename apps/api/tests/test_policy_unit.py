import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base  # noqa: E402
from app.models import ActionIntent, ApprovalDecision, ApprovalRequest, Project, Task, TaskRun  # noqa: E402
from app.policy import (  # noqa: E402
    _is_protected_relative_path,
    _resolve_policy,
    ensure_project_policies,
    evaluate_policy_action,
    resolve_approval_request,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def make_project_bundle(session):
    project = Project(name="Office", description="Test project")
    task = Task(
        project=project,
        task_key="task-1",
        title="Выполнить задачу",
        brief="Нужна проверка policy.",
        acceptance_criteria=["Есть результат"],
        status="ready",
    )
    task_run = TaskRun(task=task, status="running")
    session.add_all([project, task, task_run])
    session.commit()
    return project, task, task_run


def test_protected_path_detection_and_policy_resolution_branches():
    assert _is_protected_relative_path("") is True
    assert _is_protected_relative_path("/etc/passwd") is True
    assert _is_protected_relative_path("../secrets.txt") is True
    assert _is_protected_relative_path("src/.env") is True
    assert _is_protected_relative_path("node_modules/react/index.js") is True
    assert _is_protected_relative_path("pkg/demo.egg-info/PKG-INFO") is True
    assert _is_protected_relative_path("src/app/main.py") is False

    missing_policy = _resolve_policy(None, {})
    assert missing_policy[0] == "high"
    assert missing_policy[1] == "human"

    write_policy = SimpleNamespace(
        action_key="runtime.write_workspace",
        default_risk_level="medium",
        approval_mode="director",
        rationale="Workspace write.",
        allowlist=["task-workspace-only"],
        denylist=["/Users/"],
    )
    inside_result = _resolve_policy(
        write_policy,
        {"target_path": "/tmp/workspace/src/app.py", "workspace_path": "/tmp/workspace"},
    )
    assert inside_result[0] == "medium"
    assert inside_result[1] == "director"
    assert "inside the task workspace" in inside_result[2]

    outside_result = _resolve_policy(
        write_policy,
        {"target_path": "/tmp/other/file.py", "workspace_path": "/tmp/workspace"},
    )
    assert outside_result[0] == "high"
    assert outside_result[1] == "human"
    assert "outside the task workspace" in outside_result[2]

    promote_policy = SimpleNamespace(
        action_key="runtime.promote_workspace",
        default_risk_level="medium",
        approval_mode="director",
        rationale="Promote workspace.",
        allowlist=["source-workspace-only"],
        denylist=[".env"],
    )
    promote_missing_root = _resolve_policy(
        promote_policy,
        {"relative_paths": ["src/app.py"]},
    )
    assert promote_missing_root[0] == "high"
    assert "missing for workspace promotion" in promote_missing_root[2]

    promote_protected = _resolve_policy(
        promote_policy,
        {"source_root_path": "/workspace", "relative_paths": ["src/.env", "src/app.py"]},
    )
    assert promote_protected[0] == "high"
    assert "protected paths" in promote_protected[2]

    promote_clean = _resolve_policy(
        promote_policy,
        {"source_root_path": "/workspace", "relative_paths": ["src/app.py"]},
    )
    assert promote_clean[0] == "medium"
    assert "reviewed project file" in promote_clean[2]

    install_policy = SimpleNamespace(
        action_key="runtime.install_package",
        default_risk_level="medium",
        approval_mode="director",
        rationale="Install package.",
        allowlist=["pypi.org"],
        denylist=["/Users/"],
    )
    blocked_registry = _resolve_policy(install_policy, {"registry": "example.org"})
    assert blocked_registry[0] == "high"
    assert blocked_registry[1] == "human"
    assert "outside the allowlist" in blocked_registry[2]

    allowed_registry = _resolve_policy(install_policy, {"registry": "pypi.org"})
    assert allowed_registry[0] == "medium"
    assert allowed_registry[1] == "director"
    assert "is allowed by the policy" in allowed_registry[2]

    amo_policy = SimpleNamespace(
        action_key="crm.amo.write",
        default_risk_level="medium",
        approval_mode="director",
        rationale="Write to AMO.",
        allowlist=["amo-api"],
        denylist=[],
    )
    needs_review = _resolve_policy(amo_policy, {"amo_mode": "http", "review_status": "pending"})
    assert needs_review[0] == "high"
    assert needs_review[1] == "human"
    assert "requires explicit review approval" in needs_review[2]

    approved_review = _resolve_policy(amo_policy, {"amo_mode": "http", "review_status": "approved"})
    assert approved_review[0] == "medium"
    assert approved_review[1] == "director"
    assert "explicitly approved" in approved_review[2]

    mock_review = _resolve_policy(amo_policy, {"amo_mode": "mock"})
    assert mock_review[0] == "medium"
    assert "mock mode" in mock_review[2]


def test_evaluate_policy_action_covers_auto_director_denied_and_human_reuse():
    session = make_session()
    project, task, task_run = make_project_bundle(session)

    auto_result = evaluate_policy_action(
        session,
        project,
        "runtime.provision",
        task=task,
        requested_by="director",
        requester_role="Director",
        metadata={"workspace": "task-workspace"},
    )
    assert auto_result.allowed is True
    assert auto_result.approval_decision.actor == "system"
    assert auto_result.approval_decision.outcome == "approved"

    director_result = evaluate_policy_action(
        session,
        project,
        "runtime.install_package",
        task=task,
        requested_by="engineer",
        requester_role="BackendEngineer",
        metadata={"registry": "pypi.org"},
    )
    assert director_result.allowed is True
    assert director_result.approval_decision.actor == "director"
    assert director_result.approval_decision.outcome == "approved"

    denied_result = evaluate_policy_action(
        session,
        project,
        "task.start",
        task=task,
        requested_by="human",
        requester_role="Human",
        metadata={"task_status": "ready"},
    )
    assert denied_result.allowed is False
    assert denied_result.approval_decision.outcome == "rejected"
    assert denied_result.approval_request is None
    assert "not allowed" in denied_result.risk_assessment.rationale

    human_result = evaluate_policy_action(
        session,
        project,
        "runtime.host_access",
        task=task,
        task_run=task_run,
        requested_by="director",
        requester_role="Director",
        metadata={"target_path": "/Users/dmitrijfabarisov/.ssh/config"},
    )
    assert human_result.allowed is False
    assert human_result.approval_request is not None
    assert human_result.approval_request.status == "pending"
    assert human_result.action_intent is not None
    assert human_result.action_intent.status == "pending_approval"

    repeated_result = evaluate_policy_action(
        session,
        project,
        "runtime.host_access",
        task=task,
        task_run=task_run,
        requested_by="director",
        requester_role="Director",
        metadata={"target_path": "/Users/dmitrijfabarisov/.ssh/config"},
    )
    assert repeated_result.allowed is False
    assert repeated_result.approval_request is not None
    assert repeated_result.approval_request.id == human_result.approval_request.id
    assert repeated_result.action_intent is not None
    assert repeated_result.action_intent.id == human_result.action_intent.id

    approved_resolution = resolve_approval_request(
        session,
        project,
        human_result.approval_request,
        outcome="approved",
        actor="owner",
    )
    assert approved_resolution.approval_request.status == "approved"
    assert approved_resolution.action_intent is not None
    assert approved_resolution.action_intent.status == "completed"

    approved_result = evaluate_policy_action(
        session,
        project,
        "runtime.host_access",
        task=task,
        task_run=task_run,
        requested_by="director",
        requester_role="Director",
        metadata={"target_path": "/Users/dmitrijfabarisov/.ssh/config"},
    )
    assert approved_result.allowed is True
    assert approved_result.approval_request is not None
    assert approved_result.approval_request.status == "approved"
    assert approved_result.approval_decision.outcome == "approved"

    rejected_result = evaluate_policy_action(
        session,
        project,
        "runtime.secret_write",
        task=task,
        task_run=task_run,
        requested_by="director",
        requester_role="Director",
        metadata={"target_path": ".env.secret"},
    )
    assert rejected_result.approval_request is not None
    reject_resolution = resolve_approval_request(
        session,
        project,
        rejected_result.approval_request,
        outcome="rejected",
        actor="owner",
        summary="Секреты писать нельзя",
    )
    assert reject_resolution.approval_request.status == "rejected"
    assert reject_resolution.action_intent is not None
    assert reject_resolution.action_intent.status == "rejected"

    denied_again = evaluate_policy_action(
        session,
        project,
        "runtime.secret_write",
        task=task,
        task_run=task_run,
        requested_by="director",
        requester_role="Director",
        metadata={"target_path": ".env.secret"},
    )
    assert denied_again.allowed is False
    assert denied_again.approval_request is not None
    assert denied_again.approval_request.status == "rejected"
    assert denied_again.approval_decision.outcome == "rejected"


def test_ensure_project_policies_updates_existing_blueprint_and_resolution_validation():
    session = make_session()
    project, task, _ = make_project_bundle(session)
    policies = ensure_project_policies(session, project)
    install_policy = policies["runtime.install_package"]
    install_policy.scope = "broken"
    install_policy.default_risk_level = "high"
    install_policy.approval_mode = "human"
    install_policy.allowed_roles = ["Nobody"]
    install_policy.allowlist = ["broken"]
    install_policy.denylist = ["broken"]
    install_policy.rationale = "broken"
    install_policy.enabled = False
    session.commit()

    refreshed = ensure_project_policies(session, project)
    assert refreshed["runtime.install_package"].scope == "runtime"
    assert refreshed["runtime.install_package"].default_risk_level == "medium"
    assert refreshed["runtime.install_package"].approval_mode == "director"
    assert refreshed["runtime.install_package"].enabled is True

    human_result = evaluate_policy_action(
        session,
        project,
        "runtime.host_access",
        task=task,
        requested_by="director",
        requester_role="Director",
        metadata={"target_path": "/Users/test/.ssh"},
    )
    approval_request = human_result.approval_request
    assert approval_request is not None

    other_project = Project(name="Other", description="Other project")
    session.add(other_project)
    session.commit()

    with pytest.raises(ValueError):
        resolve_approval_request(
            session,
            other_project,
            approval_request,
            outcome="approved",
            actor="owner",
        )

    with pytest.raises(ValueError):
        resolve_approval_request(
            session,
            project,
            approval_request,
            outcome="unsupported",
            actor="owner",
        )

    resolve_approval_request(
        session,
        project,
        approval_request,
        outcome="approved",
        actor="owner",
    )
    with pytest.raises(ValueError):
        resolve_approval_request(
            session,
            project,
            approval_request,
            outcome="approved",
            actor="owner",
        )

    decisions = session.scalars(select(ApprovalDecision)).all()
    intents = session.scalars(select(ActionIntent)).all()
    assert decisions
    assert intents
