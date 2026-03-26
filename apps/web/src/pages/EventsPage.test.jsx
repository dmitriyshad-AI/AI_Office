import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import EventsPage from "./EventsPage";

function createProps(overrides = {}) {
  return {
    eventScopeFilter: "all",
    eventTitle: (eventType) => (eventType === "goal_planned" ? "Цель разобрана на план" : eventType),
    eventWindowFilter: "all",
    filteredEvents: [
      {
        id: "event-1",
        event_type: "goal_planned",
        payload: { tasks_created: 3, plan_kind: "micro" },
        created_at: "2026-03-21T09:00:00.000Z",
      },
    ],
    formatDate: () => "21.03.2026",
    setEventScopeFilter: vi.fn(),
    setEventWindowFilter: vi.fn(),
    summarizeEventPayload: () => "tasks_created: 3 · plan_kind: micro",
    ...overrides,
  };
}

describe("EventsPage", () => {
  it("renders events list and filters", async () => {
    const props = createProps();
    render(<EventsPage {...props} />);

    expect(screen.getByText("История того, что реально сделал офис")).toBeInTheDocument();
    expect(screen.getByText("Цель разобрана на план")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Период"), "7d");
    await userEvent.selectOptions(screen.getByLabelText("Область"), "crm");

    expect(props.setEventWindowFilter).toHaveBeenCalledWith("7d");
    expect(props.setEventScopeFilter).toHaveBeenCalledWith("crm");
  });

  it("renders empty state", () => {
    render(<EventsPage {...createProps({ filteredEvents: [] })} />);
    expect(screen.getByText("Под выбранный фильтр событий нет.")).toBeInTheDocument();
  });
});
