import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import CrmPage from "./CrmPage";

function createProps(overrides = {}) {
  return {
    crmApprovedCount: 1,
    crmFailedCount: 0,
    crmFieldValues: { name: "Иван Иванов" },
    crmLookupMode: "auto",
    crmMessage: "",
    crmPreviewBusy: false,
    crmPreviews: [
      {
        id: "preview-1",
        source_student_id: "student-1001",
        amo_entity_type: "contact",
        amo_entity_id: "75807689",
        status: "previewed",
        review_status: "approved",
        review_reason: "Поля уже проверены.",
        review_summary: "Разрешено записывать в AMO.",
        created_at: "2026-03-19T09:00:00.000Z",
        analysis_summary: "Готово",
        canonical_payload: { full_name: "Иван Иванов", grade: "9" },
        amo_field_payload: { name: "Иван Иванов" },
      },
    ],
    crmReviewBusy: "",
    crmReviewQueueCount: 0,
    crmSelectedFields: ["name"],
    crmSendBusy: false,
    crmSentCount: 0,
    crmStudentId: "student-1001",
    formatCrmStatus: (status) => status,
    formatDate: () => "19.03.2026",
    formatReviewStatus: (status) => status,
    handleCreateCrmPreview: vi.fn((event) => event.preventDefault()),
    handleCrmFieldValueChange: vi.fn(),
    handleResolveCrmReview: vi.fn(),
    handleSendCrmPreview: vi.fn(),
    handleToggleCrmField: vi.fn(),
    selectedCrmPreview: {
      id: "preview-1",
      source_student_id: "student-1001",
      amo_entity_id: "75807689",
      review_status: "approved",
      review_reason: "Поля уже проверены.",
      review_summary: "Разрешено записывать в AMO.",
      analysis_summary: "Готово",
      canonical_payload: { full_name: "Иван Иванов", grade: "9" },
      amo_field_payload: { name: "Иван Иванов" },
    },
    selectedProject: { id: "p1", name: "CRM" },
    setCrmLookupMode: vi.fn(),
    setCrmStudentId: vi.fn(),
    setSelectedCrmPreviewId: vi.fn(),
    statusClass: (value) => value,
    ...overrides,
  };
}

describe("CrmPage", () => {
  it("renders crm module and allows send", async () => {
    const props = createProps();
    render(<CrmPage {...props} />);

    expect(screen.getByText("Перенос и обогащение данных Tallanto -> AMO")).toBeInTheDocument();
    expect(screen.getByText(/Здесь скрыты технические mapping-настройки/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Отправить в AMO" }));
    expect(props.handleSendCrmPreview).toHaveBeenCalledWith({ amoEntityId: "75807689" });
  });

  it("shows operator review controls and saves a family-case decision", async () => {
    const props = createProps({
      crmReviewQueueCount: 1,
      crmApprovedCount: 0,
      crmPreviews: [
        {
          id: "preview-1",
          source_student_id: "student-1001",
          amo_entity_type: "contact",
          status: "previewed",
          review_status: "pending",
          review_reason: "Нужна ручная проверка.",
          review_summary: null,
          created_at: "2026-03-19T09:00:00.000Z",
          analysis_summary: "Готово",
          canonical_payload: { full_name: "Иван Иванов" },
          amo_field_payload: { name: "Иван Иванов" },
        },
      ],
      selectedCrmPreview: {
        id: "preview-1",
        source_student_id: "student-1001",
        review_status: "pending",
        review_reason: "Нужна ручная проверка.",
        review_summary: null,
        analysis_summary: "Готово",
        canonical_payload: { full_name: "Иван Иванов" },
        amo_field_payload: { name: "Иван Иванов" },
      },
    });
    render(<CrmPage {...props} />);

    expect(screen.getByText("Нужна ручная проверка.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Решение"), "family_case");
    await userEvent.type(screen.getByLabelText("Комментарий оператора"), "Похоже на семью с двумя детьми");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить решение" }));

    expect(props.handleResolveCrmReview).toHaveBeenCalledWith({
      outcome: "family_case",
      summary: "Похоже на семью с двумя детьми",
      amoEntityId: null,
    });
    expect(screen.getByRole("button", { name: "Отправить в AMO" })).toBeDisabled();
  });

  it("renders empty project state", () => {
    render(<CrmPage {...createProps({ selectedProject: null, crmPreviews: [], selectedCrmPreview: null })} />);
    expect(screen.getByText("Сначала создайте и выберите проект.")).toBeInTheDocument();
  });

  it("updates preview form fields and creates preview", async () => {
    const props = createProps();
    render(<CrmPage {...props} />);

    await userEvent.clear(screen.getByPlaceholderText("ID / телефон / email / ФИО в Tallanto"));
    await userEvent.type(screen.getByPlaceholderText("ID / телефон / email / ФИО в Tallanto"), "student-2002");
    await userEvent.selectOptions(screen.getByLabelText("Как искать в Tallanto"), "email");
    await userEvent.click(screen.getByRole("button", { name: "Построить превью" }));

    expect(props.setCrmStudentId).toHaveBeenCalled();
    expect(props.setCrmLookupMode).toHaveBeenCalledWith("email");
    expect(props.handleCreateCrmPreview).toHaveBeenCalled();
  });

  it("lets the user select preview, toggle fields, and edit values", async () => {
    const props = createProps({
      crmSelectedFields: ["name"],
      crmFieldValues: { name: "Иван Иванов", phone: "+79990000000" },
      selectedCrmPreview: {
        id: "preview-1",
        source_student_id: "student-1001",
        analysis_summary: "Готово",
        canonical_payload: { full_name: "Иван Иванов" },
        amo_field_payload: { name: "Иван Иванов", phone: "+79990000000" },
      },
      crmPreviews: [
        {
          id: "preview-1",
          source_student_id: "student-1001",
          amo_entity_type: "contact",
          status: "previewed",
          created_at: "2026-03-19T09:00:00.000Z",
          analysis_summary: "Готово",
          canonical_payload: { full_name: "Иван Иванов" },
          amo_field_payload: { name: "Иван Иванов", phone: "+79990000000" },
        },
      ],
    });
    render(<CrmPage {...props} />);

    await userEvent.click(screen.getByRole("checkbox", { name: /phone/i }));
    await userEvent.type(screen.getByDisplayValue("Иван Иванов"), " Jr");

    expect(props.handleToggleCrmField).toHaveBeenCalledWith("phone");
    expect(props.handleCrmFieldValueChange).toHaveBeenCalled();
  });

  it("renders empty states when preview is missing or has no payload", () => {
    const { rerender } = render(
      <CrmPage {...createProps({ selectedCrmPreview: null, crmPreviews: [] })} />,
    );

    expect(screen.getByText("Под выбранный фильтр записей нет.")).toBeInTheDocument();
    expect(screen.getByText("Выберите превью в очереди, чтобы проверить профиль.")).toBeInTheDocument();

    rerender(
      <CrmPage
        {...createProps({
          selectedCrmPreview: {
            id: "preview-2",
            source_student_id: "student-2002",
            analysis_summary: "Нет полей",
            canonical_payload: {},
            amo_field_payload: {},
          },
        })}
      />,
    );

    expect(screen.getByText("Нет полей для отправки.")).toBeInTheDocument();
  });

  it("supports queue filters and fallback titles for previews without full profile data", async () => {
    render(
      <CrmPage
        {...createProps({
          crmPreviews: [
            {
              id: "preview-pending",
              source_student_id: "student-pending",
              status: "previewed",
              review_status: "pending",
              created_at: "2026-03-19T09:00:00.000Z",
              analysis_summary: "Нужна проверка",
              canonical_payload: {},
              amo_field_payload: { note: "pending" },
            },
            {
              id: "preview-untitled",
              source_student_id: "",
              status: "previewed",
              review_status: "pending",
              created_at: "2026-03-19T09:30:00.000Z",
              analysis_summary: "Без имени",
              canonical_payload: {},
              amo_field_payload: { note: "untitled" },
            },
            {
              id: "preview-sent",
              source_student_id: "student-sent",
              status: "sent",
              review_status: "approved",
              created_at: "2026-03-19T10:00:00.000Z",
              analysis_summary: "Отправлено",
              canonical_payload: { phone: "+79990000000" },
              amo_field_payload: { note: "sent" },
            },
            {
              id: "preview-failed",
              source_student_id: "student-failed",
              status: "failed",
              review_status: "approved",
              created_at: "2026-03-19T11:00:00.000Z",
              analysis_summary: "Ошибка",
              canonical_payload: { program: "Физика" },
              amo_field_payload: { note: "failed" },
            },
          ],
          selectedCrmPreview: null,
        })}
      />,
    );

    expect(screen.getAllByText("student-pending").length).toBeGreaterThan(0);
    expect(screen.getByText("Превью без имени")).toBeInTheDocument();
    expect(screen.getByText("Карточка без дополнительных данных")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "sent");
    expect(screen.getAllByText("student-sent").length).toBeGreaterThan(0);
    expect(screen.queryByText("student-pending")).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "failed");
    expect(screen.getAllByText("student-failed").length).toBeGreaterThan(0);
    expect(screen.queryByText("student-sent")).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "all");
    expect(screen.getAllByText("student-pending").length).toBeGreaterThan(0);
    expect(screen.getAllByText("student-sent").length).toBeGreaterThan(0);
    expect(screen.getAllByText("student-failed").length).toBeGreaterThan(0);
    expect(screen.getByText("Превью без имени")).toBeInTheDocument();
  });

  it("blocks review save for already sent previews and shows busy review state", () => {
    render(
      <CrmPage
        {...createProps({
          crmReviewBusy: "preview-1",
          selectedCrmPreview: {
            id: "preview-1",
            source_student_id: "student-1001",
            status: "sent",
            review_status: "approved",
            review_reason: "Уже отправлено.",
            review_summary: "Повторная запись не нужна.",
            analysis_summary: "Готово",
            canonical_payload: { full_name: "Иван Иванов" },
            amo_field_payload: { name: "Иван Иванов" },
          },
        })}
      />,
    );

    expect(screen.getByRole("button", { name: "Сохраняю..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Отправить в AMO" })).toBeEnabled();
  });
});
