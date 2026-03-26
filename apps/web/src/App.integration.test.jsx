import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { installEventSourceMock, installFetchMock } from "./test/appTestUtils";

function renderApp(route, options) {
  installEventSourceMock();
  const fetchMockState = installFetchMock(options);

  const rendered = render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );

  return { ...rendered, ...fetchMockState };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("App integration", () => {
  it("shows create project flow when there are no projects", async () => {
    renderApp("/director", { noProjects: true, enableCreateProject: true });

    expect(
      await screen.findByRole("heading", { name: "Создайте первый проект" }),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Название проекта"), "Новый проект");
    await userEvent.click(screen.getByRole("button", { name: "Создать проект" }));

    expect(
      await screen.findByRole("heading", { name: "Поставьте новую цель" }),
    ).toBeInTheDocument();
  });

  it("renders director route with project data", async () => {
    renderApp("/director");

    expect(await screen.findByLabelText("Рабочий проект")).toHaveDisplayValue("CRM Office · Черновик");
    expect(await screen.findByRole("heading", { name: "Поставьте новую цель" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Куда директору идти дальше" })).toBeInTheDocument();
    expect(screen.getAllByText("Собрать backend-пайплайн CRM").length).toBeGreaterThan(0);
  });

  it("does not auto-open an old project when several projects exist", async () => {
    renderApp("/director", { multipleProjects: true });

    expect(await screen.findByText("Выберите рабочий проект")).toBeInTheDocument();
    expect(screen.getByText(/Сейчас скрыто проектов: 1/i)).toBeInTheDocument();
  });

  it("lets the user reveal technical projects from the toolbar filter", async () => {
    renderApp("/director", { multipleProjects: true });

    await userEvent.click(await screen.findByLabelText("Показать технические"));

    expect(screen.getByRole("option", { name: /Smoke Probe/i })).toBeInTheDocument();
  });

  it("renders team route with loaded agents", async () => {
    renderApp("/team");

    expect(await screen.findByText("Кто чем занят сейчас")).toBeInTheDocument();
    expect(await screen.findByText("Координация офиса")).toBeInTheDocument();
    expect(screen.getByText("API и интеграции")).toBeInTheDocument();
  });

  it("renders runs route with execution details", async () => {
    renderApp("/runs");

    expect(await screen.findByText("Исполнение задач и результат работы офиса")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Рабочий проект"), "project-1");
    expect(await screen.findByText("Можно ли безопасно продолжать запуск")).toBeInTheDocument();
    expect(await screen.findByText("Рабочая копия задачи доступна")).toBeInTheDocument();
  });

  it("renders approvals route and resolves pending approval", async () => {
    renderApp("/approvals", { enableResolveApproval: true });

    expect(await screen.findByText("Действия с риском")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Одобрить" }));

    await waitFor(() => {
      expect(screen.getByText("Под выбранный фильтр записей нет.")).toBeInTheDocument();
    });
  });

  it("renders events route with office history", async () => {
    renderApp("/events");

    expect(await screen.findByText("История того, что реально сделал офис")).toBeInTheDocument();
    expect(await screen.findByText("Отчёт директора о прогрессе")).toBeInTheDocument();
  });

  it("renders crm route and sends selected preview", async () => {
    renderApp("/crm", { enableSendPreview: true });

    expect(await screen.findByText("Перенос и обогащение данных Tallanto -> AMO")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Отправить в AMO" }));

    await waitFor(() => {
      expect(screen.getByText("Отправка завершена.")).toBeInTheDocument();
    });
  });

  it("resolves CRM review queue from the module screen", async () => {
    const { calls } = renderApp("/crm", { crmPreviewPending: true });

    expect(await screen.findByText("Перенос и обогащение данных Tallanto -> AMO")).toBeInTheDocument();
    await screen.findByText("Нужна ручная проверка.");
    await userEvent.selectOptions(screen.getByLabelText("Решение"), "family_case");
    await userEvent.type(screen.getByLabelText("Комментарий оператора"), "Нужно проверить семью");
    await userEvent.click(await screen.findByRole("button", { name: "Сохранить решение" }));

    await waitFor(() => {
      expect(
        calls.some(
          ({ method, path }) =>
            method === "POST" && path === "/projects/project-1/crm/review-queue/preview-1/resolve",
        ),
      ).toBe(true);
    });
  });

  it("renders calls route as a first-class module with live call insights", async () => {
    renderApp("/calls");

    expect(await screen.findByLabelText("Рабочий проект")).toHaveDisplayValue("CRM Office · Черновик");
    expect(
      await screen.findByText("Звонки, разбор разговоров и догрузка сигналов в CRM"),
    ).toBeInTheDocument();
    expect(screen.getByText("Очередь звонков для проверки")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText("Петр Иванов").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/Один номер телефона связан с несколькими учениками семьи/)).toBeInTheDocument();
  });

  it("approves a call and sends it to AMO from calls module", async () => {
    const { calls } = renderApp("/calls");

    expect(
      await screen.findByText("Звонки, разбор разговоров и догрузка сигналов в CRM"),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText("Петр Иванов").length).toBeGreaterThan(0);
    });
    const matchedInput = await screen.findByLabelText("ID контакта в AMO");
    fireEvent.change(matchedInput, { target: { value: "7001" } });
    await userEvent.selectOptions(screen.getByLabelText("Решение оператора"), "approved");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить решение" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Записать вывод в AMO" })).toBeEnabled();
    });
    await userEvent.click(screen.getByRole("button", { name: "Записать вывод в AMO" }));

    await waitFor(() => {
      expect(
        calls.some(
          ({ method, path }) =>
            method === "POST" && path === "/projects/project-1/calls/review-queue/insight-1/resolve",
        ),
      ).toBe(true);
      expect(
        calls.some(
          ({ method, path }) =>
            method === "POST" && path === "/projects/project-1/calls/insights/insight-1/send",
        ),
      ).toBe(true);
    });
  });

  it("refreshes projects, submits goal, and lets the director continue", async () => {
    const { calls } = renderApp("/director");

    expect(await screen.findByRole("heading", { name: "Поставьте новую цель" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Обновить проекты" }));
    await userEvent.type(
      screen.getByPlaceholderText(
        "Например: Подготовь CRM-пайплайн по анализу учеников и безопасной записи в AMO CRM",
      ),
      "Собери план по переносу данных в CRM",
    );
    await userEvent.click(screen.getByRole("button", { name: "Отправить цель директору" }));

    await waitFor(() => {
      expect(screen.getAllByText("Новый план задач построен.").length).toBeGreaterThan(0);
    });

    await userEvent.click(screen.getByRole("button", { name: "Дать директору продолжить" }));

    await waitFor(() => {
      expect(
        calls.some(({ method, path }) => method === "POST" && path === "/projects/project-1/goal"),
      ).toBe(true);
      expect(
        calls.some(
          ({ method, path }) => method === "POST" && path === "/projects/project-1/director/advance",
        ),
      ).toBe(true);
    });
  });

  it("archives and restores the selected project from director screen", async () => {
    const { calls } = renderApp("/director");

    await screen.findByRole("heading", { name: "Поставьте новую цель" });
    await userEvent.click(screen.getByRole("button", { name: "Архивировать проект" }));

    await waitFor(() => {
      expect(
        calls.some(({ method, path }) => method === "POST" && path === "/projects/project-1/archive"),
      ).toBe(true);
    });

    await userEvent.click(await screen.findByRole("button", { name: "Вернуть проект в работу" }));

    await waitFor(() => {
      expect(
        calls.some(({ method, path }) => method === "POST" && path === "/projects/project-1/restore"),
      ).toBe(true);
    });
  });

  it("blocks and resets a task from the director screen", async () => {
    const { calls } = renderApp("/director");

    expect(await screen.findByRole("heading", { name: "Поставьте новую цель" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Заблокировать" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Вернуть в работу" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "Вернуть в работу" }));

    await waitFor(() => {
      expect(
        calls.filter(
          ({ method, path }) =>
            method === "POST" && path === "/projects/project-1/tasks/task-1/actions",
        ).length,
      ).toBeGreaterThanOrEqual(2);
    });
  });

  it("cancels a running run from the director screen", async () => {
    const { calls } = renderApp("/runs");

    expect(await screen.findByText("Исполнение задач и результат работы офиса")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Рабочий проект"), "project-1");
    expect(await screen.findByRole("button", { name: /Остановить запуск/i })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Остановить запуск" }));

    await waitFor(() => {
      expect(
        calls.some(({ method, path }) => method === "POST" && path === "/task-runs/run-1/cancel"),
      ).toBe(true);
    });
  });

  it("rejects an approval and allows filtering history", async () => {
    renderApp("/approvals", { enableResolveApproval: true });

    expect(await screen.findByText("Действия с риском")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Показать"), "all");
    await userEvent.click(screen.getByRole("button", { name: "Отклонить" }));

    await waitFor(() => {
      expect(screen.getByText(/Решение: Владелец/)).toBeInTheDocument();
    });
  });

  it("changes artifact period filter", async () => {
    renderApp("/artifacts");

    expect(await screen.findByText("Понятные результаты работы офиса")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Период"), "24h");

    expect(screen.getByText("CRM plan")).toBeInTheDocument();
  });

  it("creates CRM preview without technical mapping controls", async () => {
    renderApp("/crm");

    expect(await screen.findByText("Перенос и обогащение данных Tallanto -> AMO")).toBeInTheDocument();
    await userEvent.type(
      await screen.findByPlaceholderText("ID / телефон / email / ФИО в Tallanto"),
      "student-9000",
    );
    await userEvent.click(screen.getByRole("button", { name: "Построить превью" }));

    await waitFor(() => {
      expect(screen.getByText(/Превью создано/)).toBeInTheDocument();
    });
  });

  it("handles CRM field selection, editing, validation, and send", async () => {
    renderApp("/crm", { enableSendPreview: true });

    expect(await screen.findByText("Перенос и обогащение данных Tallanto -> AMO")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("checkbox", { name: /name Иван Иванов/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /phone \+79990000000/i }));
    expect(screen.getByRole("button", { name: "Отправить в AMO" })).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /name Иван Иванов/i }));
    const nameInput = screen.getByDisplayValue("Иван Иванов");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Иван CRM");
    await userEvent.click(screen.getByRole("button", { name: "Отправить в AMO" }));

    await waitFor(() => {
      expect(screen.getByText("Отправка завершена.")).toBeInTheDocument();
    });
  });

  it("renders artifacts route with project results", async () => {
    renderApp("/artifacts");

    expect(await screen.findByText("Понятные результаты работы офиса")).toBeInTheDocument();
    expect(await screen.findByText("CRM plan")).toBeInTheDocument();
  });
});
