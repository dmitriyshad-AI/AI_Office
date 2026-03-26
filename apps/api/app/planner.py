from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import (
    ActionIntent,
    Agent,
    ApprovalRequest,
    ApprovalDecision,
    Artifact,
    EventLog,
    Message,
    Project,
    RiskAssessment,
    ReviewFinding,
    Task,
    TaskDependency,
    TaskReview,
    TaskRun,
)
from app.policy import ensure_project_policies
from app.orchestration import initialize_task_graph
from app.runtime import cleanup_task_runtime_resources, provision_project_runtime


AGENT_BLUEPRINTS = [
    {
        "role": "Director",
        "name": "Director",
        "specialization": "Owns orchestration, project decomposition, and approval routing.",
    },
    {
        "role": "ProductManager",
        "name": "Product Lead",
        "specialization": "Breaks goals into product tracks, milestones, and acceptance criteria.",
    },
    {
        "role": "Methodologist",
        "name": "Methodology Lead",
        "specialization": "Designs learning or process structures, modules, and assessments.",
    },
    {
        "role": "Architect",
        "name": "System Architect",
        "specialization": "Shapes platform architecture, data flows, interfaces, and constraints.",
    },
    {
        "role": "FrontendEngineer",
        "name": "Frontend Engineer",
        "specialization": "Owns user experience, component structure, and client-side implementation.",
    },
    {
        "role": "BackendEngineer",
        "name": "Backend Engineer",
        "specialization": "Owns APIs, persistence, orchestration services, and domain logic.",
    },
    {
        "role": "QAReviewer",
        "name": "QA Reviewer",
        "specialization": "Defines verification, risk coverage, and acceptance checks.",
    },
    {
        "role": "DevOps",
        "name": "DevOps Engineer",
        "specialization": "Prepares environments, runtime boundaries, and delivery readiness.",
    },
]


PLANNING_TASK_BLUEPRINTS = [
    {
        "task_key": "product_strategy",
        "role": "ProductManager",
        "title": "Define project scope and product shape",
        "priority": 100,
        "brief": "Translate the project goal into product scope, user flows, and milestone structure.",
        "acceptance_criteria": [
            "Defines target users and primary value proposition.",
            "Lists core workflows required for V1.",
            "Identifies major delivery risks and open decisions.",
        ],
        "depends_on": [],
    },
    {
        "task_key": "methodology_blueprint",
        "role": "Methodologist",
        "title": "Outline methodology or process design",
        "priority": 90,
        "brief": "Create the domain structure, content or process modules, and evaluation logic required by the goal.",
        "acceptance_criteria": [
            "Breaks the work into modules or tracks.",
            "Defines progression and validation checkpoints.",
            "Highlights content dependencies for engineering.",
        ],
        "depends_on": ["product_strategy"],
    },
    {
        "task_key": "system_architecture",
        "role": "Architect",
        "title": "Design system architecture",
        "priority": 95,
        "brief": "Define services, data model boundaries, integration points, and runtime constraints.",
        "acceptance_criteria": [
            "Specifies main services and responsibilities.",
            "Covers data entities and external boundaries.",
            "Documents technical risks and sequencing constraints.",
        ],
        "depends_on": ["product_strategy"],
    },
    {
        "task_key": "frontend_foundation",
        "role": "FrontendEngineer",
        "title": "Plan the director and user interface",
        "priority": 80,
        "brief": "Turn the product scope and architecture into pages, states, and component areas.",
        "acceptance_criteria": [
            "Defines main pages and navigation.",
            "Lists required UI states for critical flows.",
            "Aligns UI structure with backend contracts.",
        ],
        "depends_on": ["product_strategy", "system_architecture"],
    },
    {
        "task_key": "backend_foundation",
        "role": "BackendEngineer",
        "title": "Plan API and orchestration backend",
        "priority": 85,
        "brief": "Translate the architecture into APIs, services, persistence, and execution boundaries.",
        "acceptance_criteria": [
            "Identifies API surfaces and primary entities.",
            "Defines orchestration and persistence responsibilities.",
            "Documents validation and error handling concerns.",
        ],
        "depends_on": ["product_strategy", "system_architecture"],
    },
    {
        "task_key": "qa_strategy",
        "role": "QAReviewer",
        "title": "Prepare QA and acceptance strategy",
        "priority": 70,
        "brief": "Prepare validation criteria, smoke checks, and failure scenarios for the first delivery slice.",
        "acceptance_criteria": [
            "Lists core acceptance scenarios for the project.",
            "Defines smoke checks for product and runtime.",
            "Highlights blocking risks that need coverage before release.",
        ],
        "depends_on": ["frontend_foundation", "backend_foundation", "methodology_blueprint"],
    },
    {
        "task_key": "delivery_runtime",
        "role": "DevOps",
        "title": "Prepare local runtime and delivery constraints",
        "priority": 60,
        "brief": "Define local infrastructure, environment handling, container boundaries, and release assumptions.",
        "acceptance_criteria": [
            "Covers local runtime components and environment variables.",
            "Defines isolation and container expectations.",
            "Lists delivery prerequisites for future execution workers.",
        ],
        "depends_on": ["system_architecture", "backend_foundation"],
    },
]

IMPLEMENTATION_TASK_BLUEPRINTS = [
    {
        "task_key": "product_strategy",
        "role": "ProductManager",
        "title": "Lock delivery slice and acceptance",
        "priority": 100,
        "brief": "Pin down the exact user-visible outcome, boundaries, and acceptance criteria for the requested implementation slice.",
        "acceptance_criteria": [
            "Defines the exact outcome that should exist after implementation.",
            "Lists what is explicitly in scope and out of scope for this slice.",
            "Translates the goal into acceptance criteria that can be verified against real changes.",
        ],
        "depends_on": [],
    },
    {
        "task_key": "methodology_blueprint",
        "role": "Methodologist",
        "title": "Prepare user guidance and supporting content",
        "priority": 90,
        "brief": "Create or update the user-facing copy, onboarding hints, or process guidance required for the implementation slice.",
        "acceptance_criteria": [
            "Produces the user-facing explanations required by the goal.",
            "Keeps wording simple, consistent, and suitable for non-technical users.",
            "Aligns support content with the actual UI and workflow.",
        ],
        "depends_on": ["product_strategy"],
    },
    {
        "task_key": "system_architecture",
        "role": "Architect",
        "title": "Define implementation boundaries and constraints",
        "priority": 95,
        "brief": "Identify which modules, files, contracts, and runtime constraints must change to implement the requested slice safely.",
        "acceptance_criteria": [
            "Identifies the main code areas that need to change.",
            "Lists runtime or policy constraints that affect implementation.",
            "Clarifies any sequencing constraints between frontend, backend, and runtime work.",
        ],
        "depends_on": ["product_strategy"],
    },
    {
        "task_key": "frontend_foundation",
        "role": "FrontendEngineer",
        "title": "Implement user-facing interface changes",
        "priority": 80,
        "brief": "Make the required UI and client-side changes directly in the workspace, keeping the product understandable for the target user.",
        "acceptance_criteria": [
            "Implements the requested user-facing screen, state, or interaction changes.",
            "Keeps the interface language and structure consistent with the product.",
            "Includes focused frontend verification or notes about what was checked.",
        ],
        "depends_on": ["product_strategy", "system_architecture"],
    },
    {
        "task_key": "backend_foundation",
        "role": "BackendEngineer",
        "title": "Implement backend and orchestration changes",
        "priority": 85,
        "brief": "Make the required backend, orchestration, and persistence changes directly in the workspace so the feature works end-to-end.",
        "acceptance_criteria": [
            "Implements the required API, service, or orchestration changes in code.",
            "Preserves or improves validation, state handling, and runtime behavior.",
            "Includes focused backend verification or notes about what was checked.",
        ],
        "depends_on": ["product_strategy", "system_architecture"],
    },
    {
        "task_key": "qa_strategy",
        "role": "QAReviewer",
        "title": "Run QA and acceptance verification",
        "priority": 70,
        "brief": "Verify the delivered implementation slice against acceptance criteria using the actual workspace changes and focused checks.",
        "acceptance_criteria": [
            "Validates the implementation against the agreed acceptance criteria.",
            "Runs or documents focused checks for the changed paths.",
            "Flags any blockers or remaining risks before the slice is accepted.",
        ],
        "depends_on": ["frontend_foundation", "backend_foundation", "methodology_blueprint"],
    },
    {
        "task_key": "delivery_runtime",
        "role": "DevOps",
        "title": "Validate local runtime and delivery path",
        "priority": 60,
        "brief": "Update and verify the local runtime, build, or launch path required to use the implementation slice in the office.",
        "acceptance_criteria": [
            "Validates the local runtime or build path required by the slice.",
            "Updates any configuration or launch assumptions needed for local use.",
            "Captures delivery caveats or rollback notes for the implemented change.",
        ],
        "depends_on": ["system_architecture", "backend_foundation"],
    },
]

PLANNING_KEYWORDS = (
    "plan",
    "roadmap",
    "spec",
    "specification",
    "architecture note",
    "brief",
    "audit",
    "strategy",
    "document",
    "checklist",
    "guide",
    "instruction",
    "план",
    "дорожн",
    "спецификац",
    "документ",
    "чек-лист",
    "чеклист",
    "инструкц",
    "аудит",
    "стратег",
    "архитектурн",
)

IMPLEMENTATION_STRONG_KEYWORDS = (
    "implement",
    "fix",
    "deliver",
    "ship",
    "wire",
    "screen",
    "page",
    "route",
    "endpoint",
    "frontend",
    "backend",
    "ui",
    "ux",
    "test",
    "реализ",
    "доработ",
    "сделай",
    "добав",
    "исправ",
    "обнов",
    "создай",
    "экран",
    "страниц",
    "интерфейс",
    "кнопк",
    "маршрут",
    "api",
    "тест",
)

IMPLEMENTATION_GENERIC_KEYWORDS = (
    "build",
    "add",
    "create",
    "update",
    "добав",
    "обнов",
    "создай",
    "сделай",
)

MICRO_UI_KEYWORDS = (
    "help",
    "onboarding",
    "tooltip",
    "button",
    "label",
    "page",
    "screen",
    "route",
    "copy",
    "text",
    "помощ",
    "онбординг",
    "подсказ",
    "кнопк",
    "текст",
    "экран",
    "страниц",
    "маршрут",
    "навигац",
)

MICRO_DOCS_KEYWORDS = (
    "markdown",
    "readme",
    "guide",
    "checklist",
    "instruction",
    "faq",
    ".md",
    "документ",
    "инструкц",
    "чек-лист",
    "чеклист",
    "памятк",
    "справк",
)

MICRO_BACKEND_KEYWORDS = (
    "endpoint",
    "validator",
    "schema",
    "migration",
    "api",
    "эндпоинт",
    "валидац",
    "схем",
    "миграц",
)

MICRO_RUNTIME_KEYWORDS = (
    "docker compose",
    "dockerfile",
    "preflight",
    "env file",
    "compose",
    "докер",
    "окружени",
    ".env",
)

LARGE_SCOPE_KEYWORDS = (
    "platform",
    "workspace",
    "system",
    "mvp",
    "pipeline",
    "orchestration",
    "runtime",
    "worker",
    "database",
    "postgres",
    "redis",
    "docker",
    "container",
    "policy",
    "approval",
    "template",
    "review loop",
    "multi-agent",
    "платформ",
    "систем",
    "пайплайн",
    "оркестр",
    "рантайм",
    "воркер",
    "база данных",
    "постгрес",
    "редис",
    "контейнер",
    "одобрени",
    "шаблон",
    "многоагент",
)


@dataclass
class GoalPlanResult:
    created_tasks: list[Task]
    summary: str
    goal_mode: str
    plan_kind: str


def detect_goal_mode(goal_text: str) -> Literal["planning", "implementation"]:
    normalized = " ".join(goal_text.lower().split())
    has_strong_implementation_signal = any(
        keyword in normalized for keyword in IMPLEMENTATION_STRONG_KEYWORDS
    )
    has_generic_implementation_signal = any(
        keyword in normalized for keyword in IMPLEMENTATION_GENERIC_KEYWORDS
    )
    has_planning_signal = any(keyword in normalized for keyword in PLANNING_KEYWORDS)

    if has_strong_implementation_signal:
        return "implementation"
    if has_planning_signal:
        return "planning"
    if has_generic_implementation_signal:
        return "implementation"
    return "implementation"


def detect_goal_plan_kind(goal_text: str, goal_mode: str) -> Literal["standard", "micro"]:
    if goal_mode != "implementation":
        return "standard"

    normalized = " ".join(goal_text.lower().split())
    if any(keyword in normalized for keyword in LARGE_SCOPE_KEYWORDS):
        return "standard"

    has_ui_signal = any(keyword in normalized for keyword in MICRO_UI_KEYWORDS)
    has_docs_signal = any(keyword in normalized for keyword in MICRO_DOCS_KEYWORDS)
    has_backend_signal = any(keyword in normalized for keyword in MICRO_BACKEND_KEYWORDS)
    has_runtime_signal = any(keyword in normalized for keyword in MICRO_RUNTIME_KEYWORDS)
    matched_domains = sum([has_ui_signal or has_docs_signal, has_backend_signal, has_runtime_signal])

    if matched_domains > 1:
        return "standard"

    if (has_ui_signal or has_docs_signal or has_backend_signal or has_runtime_signal) and len(normalized.split()) <= 160:
        return "micro"

    return "standard"


def detect_micro_delivery_role(goal_text: str) -> str:
    normalized = " ".join(goal_text.lower().split())
    has_ui_signal = any(keyword in normalized for keyword in MICRO_UI_KEYWORDS)
    has_docs_signal = any(keyword in normalized for keyword in MICRO_DOCS_KEYWORDS)
    has_backend_signal = any(keyword in normalized for keyword in MICRO_BACKEND_KEYWORDS)
    has_runtime_signal = any(keyword in normalized for keyword in MICRO_RUNTIME_KEYWORDS)

    if has_runtime_signal:
        return "DevOps"
    if has_backend_signal:
        return "BackendEngineer"
    if has_ui_signal:
        return "FrontendEngineer"
    if has_docs_signal:
        return "Methodologist"
    return "FrontendEngineer"


def build_micro_implementation_blueprints(goal_text: str) -> list[dict]:
    primary_role = detect_micro_delivery_role(goal_text)
    if primary_role == "Methodologist":
        delivery_title = "Prepare the requested guide or document"
        delivery_brief = (
            "Produce the requested user-facing guide, checklist, or document directly in the workspace."
        )
        delivery_acceptance = [
            "Creates the requested document or guidance in the workspace.",
            "Keeps the wording simple, direct, and suitable for non-technical users.",
            "Matches the document structure to the requested audience and scope.",
        ]
    elif primary_role == "BackendEngineer":
        delivery_title = "Implement the requested backend slice"
        delivery_brief = (
            "Make the narrow backend or API change directly in the workspace without expanding the scope into a full platform redesign."
        )
        delivery_acceptance = [
            "Implements the requested narrow backend change in code.",
            "Keeps validation and state handling safe for the changed path.",
            "Limits the change to the requested delivery slice.",
        ]
    elif primary_role == "DevOps":
        delivery_title = "Implement the requested runtime or delivery change"
        delivery_brief = (
            "Make the narrow runtime, configuration, or delivery-path change directly in the workspace."
        )
        delivery_acceptance = [
            "Implements the requested runtime or configuration change.",
            "Keeps local execution clear and reproducible.",
            "Documents any important caveat for the changed path.",
        ]
    else:
        delivery_title = "Implement the requested user-facing slice"
        delivery_brief = (
            "Implement the requested screen, page, copy, or navigation change directly in the workspace."
        )
        delivery_acceptance = [
            "Implements the requested user-facing change in code.",
            "Keeps the interface understandable for a non-technical user.",
            "Limits the delivery to the requested narrow slice instead of redesigning the entire office.",
        ]

    blueprints = [
        {
            "task_key": "delivery_slice",
            "role": primary_role,
            "title": delivery_title,
            "priority": 100,
            "brief": delivery_brief,
            "acceptance_criteria": delivery_acceptance,
            "depends_on": [],
        }
    ]
    qa_dependencies = ["delivery_slice"]

    if primary_role == "FrontendEngineer":
        blueprints.append(
            {
                "task_key": "support_content",
                "role": "Methodologist",
                "title": "Align supporting copy and guidance",
                "priority": 85,
                "brief": "Update the visible wording, empty states, or short help text so the new slice is understandable without extra explanation.",
                "acceptance_criteria": [
                    "Aligns visible copy with the delivered interface.",
                    "Keeps wording concise and suitable for a non-technical owner.",
                    "Covers the key explanation or onboarding text required by the slice.",
                ],
                "depends_on": ["delivery_slice"],
            }
        )
        qa_dependencies.append("support_content")

    blueprints.append(
        {
            "task_key": "qa_verification",
            "role": "QAReviewer",
            "title": "Verify the narrow delivery slice",
            "priority": 70,
            "brief": "Check the actual workspace result against the requested narrow slice and report any blocker or remaining risk.",
            "acceptance_criteria": [
                "Validates the delivered result against the requested slice.",
                "Runs or documents focused checks for the changed path.",
                "Highlights blockers or residual risks before the slice is accepted.",
            ],
            "depends_on": qa_dependencies,
        }
    )
    return blueprints


def ensure_project_agents(session: Session, project: Project) -> dict[str, Agent]:
    existing_agents = session.scalars(
        select(Agent).where(Agent.project_id == project.id)
    ).all()
    agents_by_role = {agent.role: agent for agent in existing_agents}

    for blueprint in AGENT_BLUEPRINTS:
        if blueprint["role"] in agents_by_role:
            continue
        agent = Agent(
            project_id=project.id,
            role=blueprint["role"],
            name=blueprint["name"],
            specialization=blueprint["specialization"],
            status="planning" if blueprint["role"] == "Director" else "idle",
        )
        session.add(agent)
        session.flush()
        agents_by_role[agent.role] = agent

    return agents_by_role


def _goal_suffix(goal_text: str) -> str:
    clean_goal = " ".join(goal_text.split())
    return clean_goal[:180]


def create_goal_plan(session: Session, project: Project, goal_text: str) -> GoalPlanResult:
    agents_by_role = ensure_project_agents(session, project)
    ensure_project_policies(session, project)
    goal_fragment = _goal_suffix(goal_text)
    goal_mode = detect_goal_mode(goal_text)
    plan_kind = detect_goal_plan_kind(goal_text, goal_mode)
    if goal_mode == "planning":
        task_blueprints = PLANNING_TASK_BLUEPRINTS
    elif plan_kind == "micro":
        task_blueprints = build_micro_implementation_blueprints(goal_text)
    else:
        task_blueprints = IMPLEMENTATION_TASK_BLUEPRINTS
    tasks_by_key: dict[str, Task] = {}
    created_tasks: list[Task] = []
    existing_task_ids = session.scalars(
        select(Task.id).where(Task.project_id == project.id)
    ).all()

    if existing_task_ids:
        cleanup_task_runtime_resources(session, existing_task_ids)
        session.execute(
            update(ActionIntent)
            .where(ActionIntent.task_id.in_(existing_task_ids))
            .values(task_id=None, task_run_id=None, dispatch_task_run_id=None)
        )
        session.execute(
            delete(ReviewFinding).where(ReviewFinding.task_id.in_(existing_task_ids))
        )
        session.execute(
            delete(TaskReview).where(TaskReview.task_id.in_(existing_task_ids))
        )
        session.execute(
            delete(TaskRun).where(TaskRun.task_id.in_(existing_task_ids))
        )
        session.execute(
            update(Artifact)
            .where(Artifact.task_id.in_(existing_task_ids))
            .values(task_id=None)
        )
        session.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.task_id.in_(existing_task_ids))
            .values(task_id=None)
        )
        session.execute(
            update(ApprovalDecision)
            .where(ApprovalDecision.task_id.in_(existing_task_ids))
            .values(task_id=None)
        )
        session.execute(
            update(EventLog)
            .where(EventLog.task_id.in_(existing_task_ids))
            .values(task_id=None)
        )
        session.execute(
            update(RiskAssessment)
            .where(RiskAssessment.task_id.in_(existing_task_ids))
            .values(task_id=None)
        )
        session.execute(
            delete(TaskDependency).where(TaskDependency.project_id == project.id)
        )
        session.execute(delete(Task).where(Task.project_id == project.id))
        session.add(
            EventLog(
                project_id=project.id,
                event_type="task_graph_replaced",
                payload={"removed_tasks": len(existing_task_ids)},
            )
        )

    session.add(
        Message(
            project_id=project.id,
            role="user",
            content=goal_text,
        )
    )

    for blueprint in task_blueprints:
        task = Task(
            project_id=project.id,
            assigned_agent_id=agents_by_role[blueprint["role"]].id,
            task_key=blueprint["task_key"],
            title=blueprint["title"],
            brief=f"{blueprint['brief']} Project goal: {goal_fragment}",
            acceptance_criteria=blueprint["acceptance_criteria"],
            status="planned",
            priority=blueprint["priority"],
        )
        session.add(task)
        session.flush()
        tasks_by_key[task.task_key] = task
        created_tasks.append(task)

        session.add(
            EventLog(
                project_id=project.id,
                task_id=task.id,
                event_type="task_created",
                payload={
                    "task_key": task.task_key,
                    "assigned_role": blueprint["role"],
                    "priority": task.priority,
                },
            )
        )
        session.add(
            EventLog(
                project_id=project.id,
                task_id=task.id,
                event_type="task_assigned",
                payload={
                    "agent_id": agents_by_role[blueprint["role"]].id,
                    "agent_role": blueprint["role"],
                },
            )
        )

    for blueprint in task_blueprints:
        task = tasks_by_key[blueprint["task_key"]]
        for dependency_key in blueprint["depends_on"]:
            session.add(
                TaskDependency(
                    project_id=project.id,
                    task_id=task.id,
                    depends_on_task_id=tasks_by_key[dependency_key].id,
                )
            )
    session.flush()

    summary_kind = "micro implementation" if goal_mode == "implementation" and plan_kind == "micro" else goal_mode
    summary = f"Director created {len(created_tasks)} {summary_kind} tasks for goal: {goal_fragment}"

    session.add(
        Message(
            project_id=project.id,
            role="director",
            content=summary,
        )
    )
    session.add(
        EventLog(
            project_id=project.id,
            event_type="goal_planned",
            payload={
                "tasks_created": len(created_tasks),
                "goal_mode": goal_mode,
                "plan_kind": plan_kind,
            },
        )
    )

    project.latest_goal_text = goal_text
    initialize_task_graph(session, project)
    provision_project_runtime(session, project, created_tasks)

    return GoalPlanResult(
        created_tasks=created_tasks,
        summary=summary,
        goal_mode=goal_mode,
        plan_kind=plan_kind,
    )
