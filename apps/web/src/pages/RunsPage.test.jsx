import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RunsPage from "./RunsPage";

function createProps(overrides = {}) {
  return {
    activeRunPreflight: {
      summary: "Среда готова",
      checks: [{ key: "workspace.exists", status: "pass", message: "ok" }],
    },
    activeRunRuntime: {
      workspace: { workspace_path: "/runtime/task-1", root_path: "/runtime" },
      environment: { runtime_kind: "workspace-runtime", runtime_status: "ready", network_mode: "none", base_image: "python:3.12", mounts: ["/workspace"] },
      run_policy: { policy_level: "medium", default_risk_level: "medium", package_installation_mode: "allowlist" },
    },
    cancelBusy: false,
    cancelledRunsCount: 0,
    failedRunsCount: 0,
    formatDate: () => "19.03.2026",
    formatTaskStatus: (status) => status,
    handleCancelRun: vi.fn(),
    handleSelectRun: vi.fn(),
    pendingApprovalsCount: 1,
    preflightStatus: "ready",
    projectRuns: [
      {
        id: "run-1",
        task_id: "task-1",
        task_title: "Собрать API",
        task_key: "api",
        status: "running",
        started_at: "2026-03-19T09:00:00.000Z",
        finished_at: null,
        worktree_path: "/runtime/task-1",
        environment_name: "api-env",
      },
    ],
    reviewRunsCount: 0,
    runLogs: { stdout: "Started", stderr: "" },
    runningRunsCount: 1,
    runtimeStatus: "ready",
    selectedProject: { id: "p1", name: "CRM" },
    selectedRun: {
      id: "run-1",
      task_id: "task-1",
      task_title: "Собрать API",
      task_key: "api",
      status: "running",
      started_at: "2026-03-19T09:00:00.000Z",
      finished_at: null,
      worktree_path: "/runtime/task-1",
      environment_name: "api-env",
    },
    selectedRunTask: { id: "task-1", brief: "Собрать API" },
    statusClass: (value) => value,
    totalRunsCount: 1,
    ...overrides,
  };
}

describe("RunsPage", () => {
  it("renders selected run and allows cancellation", async () => {
    const props = createProps();
    render(<RunsPage {...props} />);

    expect(screen.getByText("Исполнение задач и результат работы офиса")).toBeInTheDocument();
    expect(screen.getByText("Задача сейчас выполняется. Можно следить за логом или остановить запуск.")).toBeInTheDocument();
    expect(screen.getByText("Started")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Остановить запуск" }));
    expect(props.handleCancelRun).toHaveBeenCalled();
  });

  it("renders empty state without project", () => {
    render(<RunsPage {...createProps({ selectedProject: null, projectRuns: [], selectedRun: null })} />);
    expect(screen.getAllByText(/Сначала создайте и выберите проект|Сначала выберите запуск/).length).toBeGreaterThan(0);
  });

  it("renders empty queue state for selected project without runs", () => {
    render(<RunsPage {...createProps({ projectRuns: [], selectedRun: null })} />);
    expect(screen.getByText("Запусков пока нет. Они появятся после первого исполнения задачи.")).toBeInTheDocument();
  });

  it("covers loading context and stderr fallback", () => {
    render(
      <RunsPage
        {...createProps({
          selectedRun: {
            id: "run-2",
            task_id: "task-2",
            task_title: "Проверить API",
            task_key: "qa",
            status: "failed",
            started_at: "2026-03-19T09:00:00.000Z",
            finished_at: "2026-03-19T09:05:00.000Z",
            worktree_path: "",
            environment_name: "",
          },
          selectedRunTask: null,
          runLogs: { stdout: "", stderr: "Traceback" },
          runtimeStatus: "loading",
          activeRunRuntime: null,
          preflightStatus: "loading",
          activeRunPreflight: null,
        })}
      />,
    );

    expect(screen.queryByRole("button", { name: "Остановить запуск" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Traceback").length).toBeGreaterThan(0);
    expect(screen.getByText("Загружаю окружение задачи...")).toBeInTheDocument();
    expect(screen.getByText("Загружаю проверку окружения...")).toBeInTheDocument();
  });

  it("renders humanized preflight labels and hides technical details behind disclosure", async () => {
    render(<RunsPage {...createProps()} />);

    expect(screen.getByText("Рабочая копия задачи доступна")).toBeInTheDocument();
    expect(screen.getByText("Открыть технические детали запуска")).toBeInTheDocument();
  });

  it("shows blocking preflight summary, fallback values and prettified custom checks", () => {
    render(
      <RunsPage
        {...createProps({
          selectedRun: {
            id: "run-3",
            task_id: "task-3",
            task_title: "Импортировать CRM",
            task_key: "crm",
            status: "failed",
            started_at: "2026-03-19T09:00:00.000Z",
            finished_at: "2026-03-19T09:15:00.000Z",
            worktree_path: "",
            environment_name: "",
          },
          selectedRunTask: { id: "task-3", brief: "Проверить импорт CRM" },
          runLogs: { stdout: "", stderr: "Boom" },
          activeRunPreflight: {
            summary: "Найдены проблемы перед запуском.",
            checks: [
              { key: "docker.available", status: "fail", message: "Docker недоступен" },
              { key: "custom_check_name", status: "warn", message: "Нужно проверить вручную" },
            ],
          },
          activeRunRuntime: {
            workspace: { workspace_path: null, root_path: "" },
            environment: {
              runtime_kind: "workspace-runtime",
              runtime_status: "blocked",
              network_mode: "",
              base_image: null,
              mounts: ["/workspace", "/cache"],
            },
            run_policy: {
              policy_level: "high",
              default_risk_level: "high",
              package_installation_mode: "",
            },
          },
        })}
      />,
    );

    expect(screen.getByText("Есть блокирующие проблемы")).toBeInTheDocument();
    expect(screen.getByText("Сначала разберите блокирующие проверки, потом повторяйте запуск.")).toBeInTheDocument();
    expect(screen.getByText("Custom check name")).toBeInTheDocument();
    expect(screen.getByText("Docker доступен")).toBeInTheDocument();
    expect(screen.getAllByText("Boom").length).toBeGreaterThan(0);
    expect(screen.getByText("Запуск завершился с ошибкой. Сначала посмотрите лог ошибок, потом решайте, что исправлять.")).toBeInTheDocument();
  });

  it("covers additional run states and no-check preflight branch", () => {
    const { rerender } = render(
      <RunsPage
        {...createProps({
          selectedRun: {
            id: "run-review",
            task_id: "task-4",
            task_title: "Проверить результат",
            task_key: "qa",
            status: "review",
            started_at: "2026-03-19T09:00:00.000Z",
            finished_at: "2026-03-19T09:10:00.000Z",
            worktree_path: "/runtime/task-4",
            environment_name: "qa-env",
          },
          activeRunPreflight: { summary: "Проверок нет.", checks: [] },
        })}
      />,
    );

    expect(screen.getByText("Задача ждёт проверки результата. Следующий шаг — посмотреть итог и принять решение.")).toBeInTheDocument();
    expect(screen.getByText("Проверок пока нет.")).toBeInTheDocument();

    rerender(
      <RunsPage
        {...createProps({
          selectedRun: {
            id: "run-done",
            task_id: "task-5",
            task_title: "Сделать отчёт",
            task_key: "docs",
            status: "done",
            started_at: "2026-03-19T09:00:00.000Z",
            finished_at: "2026-03-19T09:10:00.000Z",
            worktree_path: "/runtime/task-5",
            environment_name: "docs-env",
          },
        })}
      />,
    );
    expect(screen.getByText("Задача завершилась. Следующий шаг — проверить артефакты и итоговые изменения.")).toBeInTheDocument();

    rerender(
      <RunsPage
        {...createProps({
          selectedRun: {
            id: "run-timeout",
            task_id: "task-6",
            task_title: "Долгий прогон",
            task_key: "ops",
            status: "timed_out",
            started_at: "2026-03-19T09:00:00.000Z",
            finished_at: "2026-03-19T09:10:00.000Z",
            worktree_path: "/runtime/task-6",
            environment_name: "ops-env",
          },
        })}
      />,
    );
    expect(screen.getByText("Запуск превысил лимит времени. Проверьте, где задача зависла, и нужен ли повторный запуск.")).toBeInTheDocument();

    rerender(
      <RunsPage
        {...createProps({
          selectedRun: {
            id: "run-cancelled",
            task_id: "task-7",
            task_title: "Остановленный прогон",
            task_key: "ops",
            status: "cancelled",
            started_at: "2026-03-19T09:00:00.000Z",
            finished_at: "2026-03-19T09:10:00.000Z",
            worktree_path: "/runtime/task-7",
            environment_name: "ops-env",
          },
        })}
      />,
    );
    expect(screen.getByText("Запуск остановлен вручную. При необходимости его можно перезапустить позже.")).toBeInTheDocument();
  });

  it("covers neutral run state and ready preflight without warnings", () => {
    render(
      <RunsPage
        {...createProps({
          selectedRun: {
            id: "run-planned",
            task_id: "task-8",
            task_title: "Подготовить структуру",
            task_key: "product",
            status: "planned",
            started_at: "2026-03-19T09:00:00.000Z",
            finished_at: null,
            worktree_path: "/runtime/task-8",
            environment_name: "product-env",
          },
          activeRunPreflight: {
            summary: "Среда готова к запуску.",
            checks: [{ key: "git.available", status: "pass", message: "Git найден" }],
          },
        })}
      />,
    );

    expect(screen.getByText("Здесь видно текущее состояние задачи, её результат и следующий шаг.")).toBeInTheDocument();
    expect(screen.getByText("Окружение выглядит готовым")).toBeInTheDocument();
    expect(screen.getByText("Если результат вас устраивает, переходите к артефактам или следующей задаче.")).toBeInTheDocument();
    expect(screen.getByText("Git доступен")).toBeInTheDocument();
  });

  it("shows run-level empty states when project exists but no run is selected", () => {
    render(
      <RunsPage
        {...createProps({
          selectedProject: { id: "p1", name: "CRM" },
          projectRuns: [
            {
              id: "run-1",
              task_id: "task-1",
              task_title: "Собрать API",
              task_key: "api",
              status: "running",
              started_at: "2026-03-19T09:00:00.000Z",
              finished_at: null,
              worktree_path: "/runtime/task-1",
              environment_name: "api-env",
            },
          ],
          selectedRun: null,
        })}
      />,
    );

    expect(screen.getAllByText("Сначала выберите запуск.").length).toBeGreaterThan(1);
    expect(screen.getByText("Выберите запуск слева, чтобы увидеть детали.")).toBeInTheDocument();
  });
});
