import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.planner as planner_module  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import Project  # noqa: E402
from app.planner import create_goal_plan, detect_goal_mode, detect_goal_plan_kind  # noqa: E402


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def test_detect_goal_mode_defaults_to_implementation_for_real_changes():
    assert detect_goal_mode("Сделай новый экран помощи и добавь тесты.") == "implementation"
    assert detect_goal_mode("Fix the onboarding UI and update tests.") == "implementation"
    assert detect_goal_mode("Create a concise markdown architecture note and execution plan.") == "planning"
    assert detect_goal_plan_kind("Сделай новый экран помощи и добавь базовые frontend-тесты.", "implementation") == "micro"
    assert detect_goal_plan_kind("Сделай MVP платформы с backend, runtime и docker.", "implementation") == "standard"


def test_create_goal_plan_uses_implementation_blueprints(monkeypatch):
    session = make_session()
    project = Project(name="Office", description="Test")
    session.add(project)
    session.commit()

    monkeypatch.setattr(planner_module, "ensure_project_policies", lambda session, project: {})
    monkeypatch.setattr(planner_module, "provision_project_runtime", lambda session, project, tasks: None)

    result = create_goal_plan(
        session,
        project,
        "Сделай полноценный CRM-модуль с backend, runtime, docker и операторской очередью.",
    )

    titles = {task.task_key: task.title for task in result.created_tasks}
    assert result.goal_mode == "implementation"
    assert "implementation tasks" in result.summary
    assert titles["frontend_foundation"] == "Implement user-facing interface changes"
    assert titles["backend_foundation"] == "Implement backend and orchestration changes"
    assert titles["qa_strategy"] == "Run QA and acceptance verification"
    assert result.plan_kind == "standard"


def test_create_goal_plan_uses_micro_implementation_blueprints(monkeypatch):
    session = make_session()
    project = Project(name="Office", description="Test")
    session.add(project)
    session.commit()

    monkeypatch.setattr(planner_module, "ensure_project_policies", lambda session, project: {})
    monkeypatch.setattr(planner_module, "provision_project_runtime", lambda session, project, tasks: None)

    result = create_goal_plan(
        session,
        project,
        "Сделай новый экран помощи и добавь короткие пояснения для пользователя.",
    )

    titles = {task.task_key: task.title for task in result.created_tasks}
    roles = {task.task_key: task.assigned_agent.role for task in result.created_tasks}

    assert result.goal_mode == "implementation"
    assert result.plan_kind == "micro"
    assert len(result.created_tasks) == 3
    assert "micro implementation tasks" in result.summary
    assert titles["delivery_slice"] == "Implement the requested user-facing slice"
    assert roles["delivery_slice"] == "FrontendEngineer"
    assert roles["support_content"] == "Methodologist"
    assert roles["qa_verification"] == "QAReviewer"


def test_create_goal_plan_uses_planning_blueprints(monkeypatch):
    session = make_session()
    project = Project(name="Office", description="Test")
    session.add(project)
    session.commit()

    monkeypatch.setattr(planner_module, "ensure_project_policies", lambda session, project: {})
    monkeypatch.setattr(planner_module, "provision_project_runtime", lambda session, project, tasks: None)

    result = create_goal_plan(
        session,
        project,
        "Create a concise markdown architecture note and execution plan.",
    )

    titles = {task.task_key: task.title for task in result.created_tasks}
    assert result.goal_mode == "planning"
    assert result.plan_kind == "standard"
    assert "planned tasks" not in result.summary
    assert titles["frontend_foundation"] == "Plan the director and user interface"
    assert titles["backend_foundation"] == "Plan API and orchestration backend"
