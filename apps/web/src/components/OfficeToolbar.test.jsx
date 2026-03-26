import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import OfficeToolbar from "./OfficeToolbar";

describe("OfficeToolbar", () => {
  it("renders office and module navigation with project selector", async () => {
    const onRefreshProjects = vi.fn();
    const onSelectProject = vi.fn();
    const onToggleShowArchivedProjects = vi.fn();
    const onToggleShowTechnicalProjects = vi.fn();

    render(
      <MemoryRouter initialEntries={["/director"]}>
        <OfficeToolbar
          hiddenProjectsCount={2}
          moduleItems={[
            { id: "crm", path: "/crm", label: "CRM", status: "active" },
            { id: "calls", path: "/calls", label: "Звонки", status: "planned" },
          ]}
          officeItems={[
            { id: "director", path: "/director", label: "Директор" },
            { id: "runs", path: "/runs", label: "Запуски" },
          ]}
          onRefreshProjects={onRefreshProjects}
          onSelectProject={onSelectProject}
          onToggleShowArchivedProjects={onToggleShowArchivedProjects}
          onToggleShowTechnicalProjects={onToggleShowTechnicalProjects}
          projects={[{ id: "p1", name: "CRM", status: "draft", description: "Тестовый проект" }]}
          projectsRefreshing={false}
          selectedProject={{ id: "p1", name: "CRM", description: "Тестовый проект" }}
          selectedProjectId="p1"
          showArchivedProjects={false}
          showTechnicalProjects={false}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("navigation", { name: "Офис" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Модули" })).toBeInTheDocument();
    expect(screen.getByText("Готовится")).toBeInTheDocument();
    expect(screen.getByText(/По умолчанию архив и технические прогоны скрыты/)).toBeInTheDocument();
    expect(screen.getByText(/Сейчас скрыто проектов: 2/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Обновить проекты" }));
    await userEvent.selectOptions(screen.getByLabelText("Рабочий проект"), "p1");
    await userEvent.click(screen.getByLabelText("Показать архив"));
    await userEvent.click(screen.getByLabelText("Показать технические"));

    expect(onRefreshProjects).toHaveBeenCalled();
    expect(onSelectProject).toHaveBeenCalledWith("p1");
    expect(onToggleShowArchivedProjects).toHaveBeenCalledWith(true);
    expect(onToggleShowTechnicalProjects).toHaveBeenCalledWith(true);
  });

  it("shows safe empty selection state and refresh progress when several projects exist", () => {
    render(
      <MemoryRouter initialEntries={["/crm"]}>
        <OfficeToolbar
          hiddenProjectsCount={0}
          moduleItems={[{ id: "crm", path: "/crm", label: "CRM", status: "active" }]}
          officeItems={[{ id: "director", path: "/director", label: "Директор" }]}
          onRefreshProjects={vi.fn()}
          onSelectProject={vi.fn()}
          onToggleShowArchivedProjects={vi.fn()}
          onToggleShowTechnicalProjects={vi.fn()}
          projects={[
            { id: "p1", name: "Проект 1", status: "draft", description: "" },
            { id: "p2", name: "Проект 2", description: "" },
          ]}
          projectsRefreshing
          selectedProject={null}
          selectedProjectId=""
          showArchivedProjects={false}
          showTechnicalProjects={false}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Проект не выбран. Это безопаснее, чем автоматически открывать старый тестовый проект.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обновляю..." })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Проект 1 · Черновик" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Проект 2 · Проект" })).toBeInTheDocument();
    expect(screen.queryByText(/Сейчас скрыто проектов/)).not.toBeInTheDocument();
  });

  it("renders empty project list without selection metadata", () => {
    render(
      <MemoryRouter initialEntries={["/runs"]}>
        <OfficeToolbar
          hiddenProjectsCount={0}
          moduleItems={[]}
          officeItems={[{ id: "runs", path: "/runs", label: "Запуски" }]}
          onRefreshProjects={vi.fn()}
          onSelectProject={vi.fn()}
          onToggleShowArchivedProjects={vi.fn()}
          onToggleShowTechnicalProjects={vi.fn()}
          projects={[]}
          projectsRefreshing={false}
          selectedProject={null}
          selectedProjectId=""
          showArchivedProjects={false}
          showTechnicalProjects={false}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("option", { name: "Нет проектов" })).toBeInTheDocument();
    expect(screen.queryByText("Описание не задано.")).not.toBeInTheDocument();
  });
});
