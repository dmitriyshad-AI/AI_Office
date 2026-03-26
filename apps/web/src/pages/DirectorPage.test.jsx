import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import DirectorPage from "./DirectorPage";

function createProps(overrides = {}) {
  return {
    actionBusy: "",
    blockedTasks: [],
    blockedTasksCount: 0,
    busy: false,
    busyAgentsCount: 1,
    cancelBusy: false,
    completionPercent: 40,
    createDescription: "",
    createName: "",
    directorAgent: { role: "Director", name: "Директор", status: "planning" },
    displayAgentBadge: (role) => role.slice(0, 2).toUpperCase(),
    displayAgentRole: (role) => role,
    displayAgentStatus: (status) => status,
    doneTasksCount: 1,
    eventTitle: () => "Событие",
    executionBusy: false,
    focusTasks: [],
    formatDate: () => "19.03.2026",
    formatTaskStatus: (status) => status,
    goalText: "",
    handleAdvanceDirector: vi.fn(),
    handleCancelRun: vi.fn(),
    handleCreateProject: vi.fn((event) => event.preventDefault()),
    handleOpenApprovals: vi.fn(),
    handleOpenCrm: vi.fn(),
    handleOpenEvents: vi.fn(),
    handleOpenRuns: vi.fn(),
    handleOpenTaskRuns: vi.fn(),
    handleOpenTeam: vi.fn(),
    handleArchiveProject: vi.fn(),
    handleRestoreProject: vi.fn(),
    handleSubmitGoal: vi.fn((event) => event.preventDefault()),
    handleTaskAction: vi.fn(),
    latestDirectorMessage: null,
    latestEvent: null,
    nextAction: { title: "Действие", description: "Описание", buttonLabel: null, buttonAction: null },
    officeAgents: [],
    pendingApprovalsCount: 0,
    planSummary: "",
    preflightBlockingChecks: [],
    preflightStatus: "ready",
    projectsCount: 0,
    readyTasks: [],
    readyTasksCount: 0,
    recentDirectorMessages: [],
    reviewTasksCount: 0,
    runLogs: null,
    runningTaskRun: null,
    runningTasksCount: 0,
    selectedProject: null,
    selectedRun: null,
    selectedTask: null,
    selectedTaskPreflight: null,
    setCreateDescription: vi.fn(),
    setCreateName: vi.fn(),
    setGoalText: vi.fn(),
    setSelectedTaskId: vi.fn(),
    shortenText: (value) => value,
    sortedAgentsCount: 1,
    statusClass: (value) => value,
    summarizeEventPayload: () => "payload",
    projectActionBusy: "",
    ...overrides,
  };
}

describe("DirectorPage", () => {
  it("renders project creation state", async () => {
    render(<DirectorPage {...createProps()} />);

    expect(screen.getByText("Создайте первый проект")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Создать проект" }));
  });

  it("updates creation form fields and busy project state", async () => {
    const props = createProps({ busy: true });
    render(<DirectorPage {...props} />);

    await userEvent.type(screen.getByPlaceholderText("Название проекта"), "CRM Office");
    await userEvent.type(screen.getByPlaceholderText("Описание (необязательно)"), "Перенос данных");

    expect(props.setCreateName).toHaveBeenCalled();
    expect(props.setCreateDescription).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Создаю..." })).toBeDisabled();
  });

  it("shows explicit project selection state when projects already exist", () => {
    render(<DirectorPage {...createProps({ projectsCount: 3 })} />);

    expect(screen.getByText("Выберите рабочий проект")).toBeInTheDocument();
    expect(
      screen.getByText(/Сначала выберите рабочий проект в верхней панели или создайте новый/i),
    ).toBeInTheDocument();
  });

  it("renders active project state and quick actions", async () => {
    const props = createProps({
      selectedProject: { id: "p1", name: "CRM", description: "desc" },
      latestDirectorMessage: { content: "Отчёт директора" },
      officeAgents: [{ id: "a1", role: "BackendEngineer", name: "Backend", status: "running" }],
      focusTasks: [
        {
          id: "t1",
          title: "Сделать API",
          assigned_agent_role: "BackendEngineer",
          brief: "Собрать API",
          status: "ready",
        },
      ],
      selectedTask: {
        id: "t1",
        title: "Сделать API",
        brief: "Собрать API",
        status: "ready",
      },
      selectedTaskPreflight: { summary: "Готово" },
      nextAction: {
        title: "Следующий шаг",
        description: "Нужно запустить задачу",
        buttonLabel: "Открыть",
        buttonAction: vi.fn(),
      },
      readyTasks: [{ id: "t1", title: "Сделать API", assigned_agent_role: "BackendEngineer" }],
      recentDirectorMessages: [{ id: "m1", content: "Свежий отчёт", created_at: "2026-03-19T09:00:00.000Z" }],
    });
    render(<DirectorPage {...props} />);

    expect(screen.getByRole("heading", { name: "Куда директору идти дальше" })).toBeInTheDocument();
    expect(screen.getAllByText("Сделать API").length).toBeGreaterThan(0);
    await userEvent.click(screen.getAllByRole("button", { name: "Открыть" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Открыть события" }));
    expect(props.nextAction.buttonAction).toHaveBeenCalled();
    expect(props.handleOpenEvents).toHaveBeenCalled();
  });

  it("allows archiving and restoring the selected project", async () => {
    const props = createProps({
      selectedProject: { id: "p1", name: "CRM", description: "desc", status: "draft" },
    });
    const archivedProps = createProps({
      selectedProject: { id: "p1", name: "CRM", description: "desc", status: "archived" },
    });
    const { rerender } = render(<DirectorPage {...props} />);

    await userEvent.click(screen.getByRole("button", { name: "Архивировать проект" }));
    expect(props.handleArchiveProject).toHaveBeenCalled();

    rerender(
      <DirectorPage {...archivedProps} />,
    );

    expect(screen.getByText("Проект в архиве")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отправить цель директору" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Вернуть проект в работу" }));
    expect(archivedProps.handleRestoreProject).toHaveBeenCalled();
  });

  it("covers running task actions, blocked queue, reports, and run details", async () => {
    const props = createProps({
      selectedProject: { id: "p1", name: "CRM", description: "desc" },
      directorAgent: { role: "Director", name: "Директор", status: "running" },
      officeAgents: [{ id: "a1", role: "BackendEngineer", name: "Backend", status: "running" }],
      focusTasks: [
        {
          id: "t-running",
          title: "Сделать API",
          assigned_agent_role: "BackendEngineer",
          brief: "Собрать API",
          status: "running",
        },
      ],
      blockedTasks: [{ id: "t-blocked", title: "Починить policy", status: "blocked" }],
      blockedTasksCount: 1,
      readyTasks: [],
      readyTasksCount: 0,
      selectedTask: {
        id: "t-running",
        title: "Сделать API",
        brief: "Собрать API",
        status: "running",
      },
      selectedTaskPreflight: {
        summary: "Есть блокер",
        checks: [{ key: "workspace.exists", message: "Нет workspace", status: "fail", blocking: true }],
      },
      preflightBlockingChecks: [{ key: "workspace.exists", message: "Нет workspace" }],
      latestEvent: {
        id: "e1",
        event_type: "director_progress_update",
        payload: { progress: "80%" },
        created_at: "2026-03-19T09:00:00.000Z",
      },
      recentDirectorMessages: [{ id: "m1", content: "Краткий отчёт", created_at: "2026-03-19T09:00:00.000Z" }],
      runningTaskRun: { id: "r1" },
      selectedRun: {
        id: "r1",
        status: "running",
        started_at: "2026-03-19T09:00:00.000Z",
        finished_at: null,
      },
      runLogs: { stdout: "run log output" },
    });

    render(<DirectorPage {...props} />);

    await userEvent.click(screen.getByRole("button", { name: "Отметить как выполненную" }));
    await userEvent.click(screen.getByRole("button", { name: "Остановить запуск" }));
    await userEvent.click(screen.getByRole("button", { name: "Заблокировать" }));
    await userEvent.click(screen.getByRole("button", { name: "Открыть в запусках" }));
    await userEvent.click(screen.getByRole("button", { name: "В фокус" }));
    await userEvent.click(screen.getByRole("button", { name: /Сделать API/ }));

    expect(props.handleTaskAction).toHaveBeenCalledWith("complete");
    expect(props.handleTaskAction).toHaveBeenCalledWith("block");
    expect(props.handleCancelRun).toHaveBeenCalled();
    expect(props.handleOpenTaskRuns).toHaveBeenCalledWith("t-running");
    expect(props.setSelectedTaskId).toHaveBeenCalledWith("t-blocked");
    expect(props.setSelectedTaskId).toHaveBeenCalledWith("t-running");
    expect(screen.getByText("Есть блокер")).toBeInTheDocument();
    expect(screen.getByText(/workspace\.exists/)).toBeInTheDocument();
    expect(screen.getByText("run log output")).toBeInTheDocument();
    expect(screen.getByText("Краткий отчёт")).toBeInTheDocument();
  });

  it("covers failed task reset and preflight loading state", async () => {
    const props = createProps({
      selectedProject: { id: "p1", name: "CRM", description: "desc" },
      selectedTask: {
        id: "t-failed",
        title: "Починить API",
        brief: "Исправить падение",
        status: "failed",
      },
      focusTasks: [
        {
          id: "t-failed",
          title: "Починить API",
          assigned_agent_role: "BackendEngineer",
          brief: "Исправить падение",
          status: "failed",
        },
      ],
      preflightStatus: "loading",
      selectedTaskPreflight: null,
      selectedRun: null,
      runningTaskRun: null,
    });

    render(<DirectorPage {...props} />);

    await userEvent.click(screen.getByRole("button", { name: "Вернуть в работу" }));
    expect(props.handleTaskAction).toHaveBeenCalledWith("reset");
    expect(screen.getByText("Проверяю условия...")).toBeInTheDocument();
  });
});
