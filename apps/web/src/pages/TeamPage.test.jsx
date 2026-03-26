import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TeamPage from "./TeamPage";

function createProps(overrides = {}) {
  return {
    blockedAgentsCount: 1,
    displayAgentBadge: (role) => role.slice(0, 2).toUpperCase(),
    displayAgentRole: (role) => role,
    displayAgentStatus: (status) => status,
    idleAgentsCount: 1,
    reviewingAgentsCount: 1,
    runningAgentsCount: 2,
    sortedAgents: [
      {
        id: "a1",
        role: "BackendEngineer",
        name: "Backend",
        status: "running",
        current_task_title: "API",
        specialization: "Интеграции",
      },
    ],
    statusClass: (value) => value,
    ...overrides,
  };
}

describe("TeamPage", () => {
  it("renders metrics and team members", () => {
    render(<TeamPage {...createProps()} />);

    expect(screen.getByText("Кто чем занят сейчас")).toBeInTheDocument();
    expect(screen.getByText("В работе")).toBeInTheDocument();
    expect(screen.getByText("Backend")).toBeInTheDocument();
    expect(screen.getByText("Интеграции")).toBeInTheDocument();
  });

  it("renders empty state without agents", () => {
    render(<TeamPage {...createProps({ sortedAgents: [] })} />);

    expect(screen.getByText("Сотрудники появятся после создания проекта и плана задач.")).toBeInTheDocument();
  });

  it("shows fallback text when agent has no active task", () => {
    render(
      <TeamPage
        {...createProps({
          sortedAgents: [
            {
              id: "a2",
              role: "QAReviewer",
              name: "QA",
              status: "reviewing",
              current_task_title: "",
              specialization: "Проверка качества",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("Нет активной задачи")).toBeInTheDocument();
    expect(screen.getByText("Проверка качества")).toBeInTheDocument();
  });
});
