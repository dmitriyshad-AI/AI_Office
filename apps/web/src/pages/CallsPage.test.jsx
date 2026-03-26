import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import CallsPage from "./CallsPage";

function createInsight(overrides = {}) {
  return {
    id: "insight-1",
    source_filename: "2026-03-19__call-1001.mp3",
    source_call_id: "call-1001",
    source_record_id: "record-1001",
    phone: "+79990001122",
    manager_name: "Леонова Анна",
    started_at: "2026-03-19T10:00:00.000Z",
    created_at: "2026-03-19T10:00:00.000Z",
    updated_at: "2026-03-19T10:10:00.000Z",
    duration_sec: 312.4,
    history_summary:
      "Менеджер обсудил курс математики, родитель запросил материалы и ждёт повторный звонок.",
    lead_priority: "hot",
    follow_up_score: 86,
    processing_status: "done",
    match_status: "pending_match",
    matched_amo_contact_id: null,
    review_status: "pending",
    review_reason: "Один номер телефона связан с несколькими учениками семьи.",
    review_summary: null,
    sent_by: null,
    sent_at: null,
    created_by: "director",
    payload: {
      identity_hints: {
        parent_fio: "Иванова Анна",
        child_fio: "Петр Иванов",
        email: "family@example.com",
        grade_current: "9",
        school: "Школа 57",
      },
      call_summary: {
        evidence: [
          {
            speaker: "Клиент",
            ts: "00:32.1",
            text: "Нас интересует математика для 9 класса.",
          },
        ],
      },
      sales_insight: {
        interests: {
          products: ["Годовые курсы"],
          format: ["Онлайн"],
          subjects: ["Математика"],
        },
        objections: ["Цена"],
        next_step: {
          action: "Отправить материалы и перезвонить",
          due: "на этой неделе",
        },
      },
    },
    ...overrides,
  };
}

function createProps(overrides = {}) {
  const firstInsight = createInsight();
  const secondInsight = createInsight({
    id: "insight-2",
    phone: "+79990003344",
    manager_name: "Крылова Дарья",
    lead_priority: "warm",
    match_status: "matched",
    matched_amo_contact_id: 75807689,
    review_status: "approved",
    review_reason: null,
    review_summary: "Контакт подтверждён.",
    payload: {
      identity_hints: {
        parent_fio: "Самойлова Дарья Дмитриевна",
        child_fio: "Федор Александрович Левашко",
        grade_current: "5",
      },
      call_summary: { evidence: [] },
      sales_insight: {
        interests: {
          products: ["ЛШВ"],
          format: ["Очно"],
          subjects: ["Физика"],
        },
        objections: [],
        next_step: {
          action: "Ожидать оплату",
          due: "до конца недели",
        },
      },
    },
  });

  return {
    callMessage: "",
    callsArtifacts: [
      {
        id: "artifact-1",
        title: "Mango payload spec",
        content: "Схема догрузки call insights в AMO.",
        created_at: "2026-03-19T09:00:00.000Z",
      },
    ],
    callInsights: [firstInsight, secondInsight],
    callInsightsCount: 2,
    callReviewBusy: "",
    callSendBusy: false,
    callsApprovedCount: 1,
    callsFocusTasks: [
      {
        id: "task-1",
        title: "Собрать pipeline Mango -> AMO",
        brief: "Добавить приём call insight payload.",
        assigned_agent_role: "BackendEngineer",
        status: "ready",
      },
    ],
    callsHotCount: 1,
    callsManualReviewCount: 1,
    callsMatchedCount: 1,
    callsModuleState: {
      status: "active",
      label: "Работает",
      summary: "В модуле уже есть реальные звонки, загруженные из локального пайплайна.",
      nextStep: "Проверить спорные семейные случаи и довести controlled write в AMO.",
    },
    callsPendingMatchCount: 1,
    displayAgentRole: (value) => value,
    formatCallMatchStatus: (value) =>
      ({
        pending_match: "Ждёт матчинга",
        matched: "Привязан",
        family_review: "Проверка по семье",
        duplicate_candidate: "Проверка на дубль",
      })[value] || value,
    formatCallPriority: (value) =>
      ({
        hot: "Горячий",
        warm: "Тёплый",
      })[value] || value,
    formatCallProcessingStatus: (value) =>
      ({
        done: "Готово",
      })[value] || value,
    formatDate: () => "19.03.2026",
    formatReviewStatus: (value) =>
      ({
        pending: "Ждёт проверки",
        approved: "Одобрено",
        family_case: "Семейный кейс",
      })[value] || value,
    formatTaskStatus: (value) => value,
    handleOpenApprovals: vi.fn(),
    handleOpenDirector: vi.fn(),
    handleOpenRuns: vi.fn(),
    handleResolveCallReview: vi.fn(),
    handleSendCallInsight: vi.fn(),
    selectedCallInsight: firstInsight,
    selectedProject: { id: "project-1", name: "CRM Office" },
    setSelectedCallInsightId: vi.fn(),
    shortenText: (value) => value,
    statusClass: (value) => value,
    ...overrides,
  };
}

describe("CallsPage", () => {
  it("renders live module metrics and selected call details", async () => {
    const props = createProps();
    render(<CallsPage {...props} />);

    expect(
      screen.getByText("Звонки, разбор разговоров и догрузка сигналов в CRM"),
    ).toBeInTheDocument();
    expect(screen.getByText("получено из локального пайплайна")).toBeInTheDocument();
    expect(screen.getByText(/Сырые записи разговоров не загружаются в AI Office вручную/i)).toBeInTheDocument();
    expect(screen.getAllByText("Петр Иванов").length).toBeGreaterThan(0);
    expect(screen.getByText("Иванова Анна")).toBeInTheDocument();
    expect(screen.getByText("Нас интересует математика для 9 класса.")).toBeInTheDocument();
    expect(screen.getByLabelText("ID контакта в AMO")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "К директору" }));
    await userEvent.click(screen.getByRole("button", { name: "Открыть запуски" }));
    await userEvent.click(screen.getByRole("button", { name: "Одобрения" }));

    expect(props.handleOpenDirector).toHaveBeenCalled();
    expect(props.handleOpenRuns).toHaveBeenCalled();
    expect(props.handleOpenApprovals).toHaveBeenCalled();
  });

  it("lets the user save a family-case decision", async () => {
    const props = createProps();
    render(<CallsPage {...props} />);

    await userEvent.selectOptions(screen.getByLabelText("Решение оператора"), "family_case");
    await userEvent.type(screen.getByLabelText("Комментарий оператора"), "Нужно проверить семью");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить решение" }));

    expect(props.handleResolveCallReview).toHaveBeenCalledWith({
      outcome: "family_case",
      matchedAmoContactId: null,
      summary: "Нужно проверить семью",
    });
  });

  it("allows AMO send when the call is already approved", async () => {
    const props = createProps({
      selectedCallInsight: createInsight({
        review_status: "approved",
        matched_amo_contact_id: 75807689,
        review_reason: null,
      }),
    });
    render(<CallsPage {...props} />);

    const idField = screen.getByLabelText("ID контакта в AMO");
    await userEvent.clear(idField);
    await userEvent.type(idField, "75807689");
    await userEvent.click(screen.getByRole("button", { name: "Записать вывод в AMO" }));
    expect(props.handleSendCallInsight).toHaveBeenCalledWith({ matchedAmoContactId: "75807689" });
  });

  it("lets the user pick another call insight from the queue", async () => {
    const props = createProps();
    render(<CallsPage {...props} />);

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "all");
    await userEvent.click(screen.getByRole("button", { name: /Федор Александрович Левашко/i }));

    expect(props.setSelectedCallInsightId).toHaveBeenCalledWith("insight-2");
  });

  it("renders fallback titles, muted pills, and empty evidence honestly", () => {
    render(
      <CallsPage
        {...createProps({
          selectedCallInsight: createInsight({
            source_filename: "fallback-call.mp3",
            history_summary: "Короткая сводка без точной идентификации ученика.",
            payload: {
              identity_hints: {
                parent_fio: "Родитель без имени ученика",
              },
              call_summary: {
                evidence: [],
              },
              sales_insight: {
                interests: {
                  products: [],
                  format: [],
                  subjects: [],
                },
                objections: [],
                next_step: {},
              },
            },
          }),
        })}
      />,
    );

    expect(screen.getAllByText("fallback-call.mp3").length).toBeGreaterThan(0);
    expect(screen.getByText("Родитель без имени ученика")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("Для этого звонка пока нет выделенных цитат.")).toBeInTheDocument();
  });

  it("shows honest empty states when there are no imported calls yet", () => {
    render(
      <CallsPage
        {...createProps({
          callsArtifacts: [],
          callInsights: [],
          callInsightsCount: 0,
          callsFocusTasks: [],
          callsHotCount: 0,
          callsManualReviewCount: 0,
          callsMatchedCount: 0,
          callsPendingMatchCount: 0,
          selectedCallInsight: null,
          selectedProject: null,
        })}
      />,
    );

    expect(screen.getByText("Проект не выбран")).toBeInTheDocument();
    expect(screen.getByText(/Под выбранный фильтр звонков нет/)).toBeInTheDocument();
    expect(screen.getByText(/Директор пока не создал отдельные задачи по звонкам/)).toBeInTheDocument();
    expect(screen.getByText(/Артефактов по звонкам пока нет/)).toBeInTheDocument();
  });

  it("supports approved, sent and hot filters and alternate subtitle fallbacks", async () => {
    render(
      <CallsPage
        {...createProps({
          callInsights: [
            createInsight({
              id: "insight-parent-only",
              source_filename: "",
              source_call_id: "",
              phone: "",
              review_status: "approved",
              status: "previewed",
              follow_up_score: 40,
              lead_priority: "warm",
              payload: {
                identity_hints: { parent_fio: "Только родитель" },
                call_summary: { evidence: [] },
                sales_insight: { interests: {}, objections: [], next_step: {} },
              },
            }),
            createInsight({
              id: "insight-phone-only",
              source_filename: "",
              source_call_id: "call-phone-only",
              phone: "+79990005566",
              review_status: "pending",
              status: "sent",
              follow_up_score: 10,
              lead_priority: "cold",
              payload: {
                identity_hints: {},
                call_summary: { evidence: [] },
                sales_insight: { interests: {}, objections: [], next_step: {} },
              },
            }),
            createInsight({
              id: "insight-hot",
              source_filename: "hot.mp3",
              review_status: "pending",
              status: "previewed",
              follow_up_score: 76,
              lead_priority: "warm",
              payload: {
                identity_hints: {
                  child_fio: "Горячий ученик",
                  parent_fio: "Горячий родитель",
                },
                call_summary: { evidence: [] },
                sales_insight: { interests: {}, objections: [], next_step: {} },
              },
            }),
          ],
          selectedCallInsight: null,
        })}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "approved");
    expect(screen.getByText("Только родитель")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "sent");
    expect(screen.getByText("call-phone-only")).toBeInTheDocument();
    expect(screen.getByText("+79990005566")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Показать"), "hot");
    expect(screen.getByText("Горячий ученик")).toBeInTheDocument();
    expect(screen.queryByText("call-phone-only")).not.toBeInTheDocument();
  });

  it("falls back to unknown contact label when neither parent nor phone are available", () => {
    render(
      <CallsPage
        {...createProps({
          callInsights: [
            createInsight({
              id: "insight-no-contact",
              source_filename: "",
              source_call_id: "",
              phone: "",
              payload: {
                identity_hints: {},
                call_summary: { evidence: [] },
                sales_insight: { interests: {}, objections: [], next_step: {} },
              },
            }),
          ],
          selectedCallInsight: null,
        })}
      />,
    );

    expect(screen.getByText("Звонок без имени")).toBeInTheDocument();
    expect(screen.getByText("Контакт не определён")).toBeInTheDocument();
  });
});
