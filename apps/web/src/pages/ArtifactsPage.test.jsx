import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ArtifactsPage from "./ArtifactsPage";

function createProps(overrides = {}) {
  return {
    artifactWindowFilter: "all",
    filteredArtifacts: [
      {
        id: "artifact-1",
        title: "CRM plan",
        kind: "spec",
        content: "Полное содержимое артефакта",
        created_at: "2026-03-19T09:00:00.000Z",
      },
    ],
    formatDate: () => "19.03.2026",
    setArtifactWindowFilter: vi.fn(),
    shortenText: (value) => value,
    ...overrides,
  };
}

describe("ArtifactsPage", () => {
  it("renders artifacts list and details", () => {
    render(<ArtifactsPage {...createProps()} />);

    expect(screen.getByText("Понятные результаты работы офиса")).toBeInTheDocument();
    expect(screen.getByText(/Документ или спецификация/i)).toBeInTheDocument();
    expect(screen.getByText("CRM plan")).toBeInTheDocument();
    expect(screen.getByText("Открыть содержимое")).toBeInTheDocument();
  });

  it("updates artifact period filter", async () => {
    const props = createProps();
    render(<ArtifactsPage {...props} />);

    await userEvent.selectOptions(screen.getByLabelText("Период"), "7d");

    expect(props.setArtifactWindowFilter).toHaveBeenCalledWith("7d");
  });

  it("renders empty state", () => {
    render(<ArtifactsPage {...createProps({ filteredArtifacts: [] })} />);

    expect(screen.getByText("За выбранный период артефактов нет.")).toBeInTheDocument();
  });

  it("uses generic labels for unknown artifact kinds", () => {
    render(
      <ArtifactsPage
        {...createProps({
          filteredArtifacts: [
            {
              id: "artifact-2",
              title: "Unknown payload",
              kind: "custom_blob",
              content: "Содержимое нестандартного артефакта",
              created_at: "2026-03-19T09:00:00.000Z",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("Категория: Сохранённый результат работы")).toBeInTheDocument();
    expect(screen.getByText("Это сохранённый результат работы офиса.")).toBeInTheDocument();
  });
});
