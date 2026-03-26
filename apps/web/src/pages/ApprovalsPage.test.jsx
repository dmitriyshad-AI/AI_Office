import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ApprovalsPage from "./ApprovalsPage";

function createProps(overrides = {}) {
  return {
    approvalActionBusy: "",
    approvalStatusLabels: { pending: "Ждёт решения", approved: "Одобрено", rejected: "Отклонено" },
    approvalsFilter: "pending",
    displayAgentRole: (value) => (value === "human" ? "Владелец" : value),
    filteredApprovals: [
      {
        id: "approval-1",
        action: "runtime.host_access",
        created_at: "2026-03-19T09:00:00.000Z",
        risk_level: "high",
        status: "pending",
        reason: "Нужен доступ к хосту",
        resolved_by: null,
        resolved_at: null,
      },
    ],
    formatDate: () => "19.03.2026",
    handleResolveApproval: vi.fn(),
    labelFromMap: (map, key, fallback) => map[key] || fallback,
    riskLevelLabels: { high: "Высокий" },
    setApprovalsFilter: vi.fn(),
    statusClass: (value) => value,
    ...overrides,
  };
}

describe("ApprovalsPage", () => {
  it("renders approvals and allows decisions", async () => {
    const props = createProps();
    render(<ApprovalsPage {...props} />);

    expect(screen.getByText("Действия с риском")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Одобрить" }));
    await userEvent.click(screen.getByRole("button", { name: "Отклонить" }));

    expect(props.handleResolveApproval).toHaveBeenCalledWith("approval-1", "approved");
    expect(props.handleResolveApproval).toHaveBeenCalledWith("approval-1", "rejected");
  });

  it("renders resolved history and filter updates", async () => {
    const props = createProps({
      approvalsFilter: "all",
      filteredApprovals: [
        {
          id: "approval-2",
          action: "runtime.install_package",
          created_at: "2026-03-19T09:00:00.000Z",
          risk_level: "medium",
          status: "approved",
          reason: "Нужно поставить пакет",
          resolved_by: "human",
          resolved_at: "2026-03-19T09:10:00.000Z",
        },
      ],
      riskLevelLabels: { medium: "Средний" },
    });
    render(<ApprovalsPage {...props} />);

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "approved");

    expect(props.setApprovalsFilter).toHaveBeenCalledWith("approved");
    expect(screen.getByText(/Решение: Владелец/)).toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(<ApprovalsPage {...createProps({ filteredApprovals: [] })} />);

    expect(screen.getByText("Под выбранный фильтр записей нет.")).toBeInTheDocument();
  });
});
