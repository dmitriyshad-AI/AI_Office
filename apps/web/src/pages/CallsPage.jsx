import { useEffect, useState } from "react";

function renderTaskMeta(task, displayAgentRole, formatTaskStatus) {
  return `${formatTaskStatus(task.status)} · ${displayAgentRole(task.assigned_agent_role)}`;
}

function displayInsightTitle(insight) {
  const childName = insight?.payload?.identity_hints?.child_fio;
  if (childName) {
    return childName;
  }
  return insight?.source_filename || insight?.source_call_id || "Звонок без имени";
}

function displayInsightSubtitle(insight) {
  const parent = insight?.payload?.identity_hints?.parent_fio;
  const phone = insight?.phone || insight?.payload?.identity_hints?.phone;
  if (parent && phone) {
    return `${parent} · ${phone}`;
  }
  if (parent) {
    return parent;
  }
  return phone || "Контакт не определён";
}

function renderDetailField(label, value) {
  return (
    <div className="calls-field-item" key={label}>
      <span>{label}</span>
      <strong>{value || "—"}</strong>
    </div>
  );
}

function renderPillList(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return <span className="calls-inline-muted">—</span>;
  }

  return (
    <div className="calls-pill-list">
      {items.map((item) => (
        <span className="calls-pill" key={item}>
          {item}
        </span>
      ))}
    </div>
  );
}

const REVIEW_DECISIONS = [
  {
    value: "approved",
    label: "Подтвердить ученика",
    hint: "Контакт AMO найден, можно делать контролируемую запись.",
  },
  {
    value: "family_case",
    label: "Семейный кейс",
    hint: "Один номер относится к нескольким ученикам, нужен ручной выбор.",
  },
  {
    value: "needs_correction",
    label: "Нужна корректировка",
    hint: "Нужно поправить анализ звонка или исходные данные.",
  },
  {
    value: "insufficient_data",
    label: "Недостаточно данных",
    hint: "Звонок не даёт безопасно определить ученика.",
  },
  {
    value: "duplicate",
    label: "Похоже на дубль",
    hint: "Похоже, что кейс уже обработан в другой карточке или звонке.",
  },
];

const QUEUE_FILTERS = [
  { value: "needs_action", label: "Требуют решения" },
  { value: "approved", label: "Одобрены" },
  { value: "sent", label: "Отправлены" },
  { value: "hot", label: "Срочные" },
  { value: "all", label: "Все" },
];

function reviewNeedsOperatorAction(reviewStatus) {
  return !["approved", "not_required", "", null, undefined].includes(reviewStatus);
}

function matchesQueueFilter(insight, filter) {
  if (filter === "all") {
    return true;
  }
  if (filter === "approved") {
    return insight.review_status === "approved";
  }
  if (filter === "sent") {
    return insight.status === "sent";
  }
  if (filter === "hot") {
    return insight.lead_priority === "hot" || Number(insight.follow_up_score || 0) >= 75;
  }
  return reviewNeedsOperatorAction(insight.review_status);
}

function reviewHint(decision) {
  return REVIEW_DECISIONS.find((item) => item.value === decision)?.hint || "Выберите решение оператора.";
}

export default function CallsPage({
  callMessage,
  callsArtifacts,
  callInsights,
  callInsightsCount,
  callReviewBusy,
  callSendBusy,
  callsApprovedCount,
  callsFocusTasks,
  callsHotCount,
  callsManualReviewCount,
  callsMatchedCount,
  callsModuleState,
  callsPendingMatchCount,
  displayAgentRole,
  formatCallMatchStatus,
  formatCallPriority,
  formatCallProcessingStatus,
  formatDate,
  formatReviewStatus,
  formatTaskStatus,
  handleOpenApprovals,
  handleOpenDirector,
  handleOpenRuns,
  handleResolveCallReview,
  handleSendCallInsight,
  selectedCallInsight,
  selectedProject,
  setSelectedCallInsightId,
  shortenText,
  statusClass,
}) {
  const [queueFilter, setQueueFilter] = useState("needs_action");
  const [reviewDecision, setReviewDecision] = useState("approved");
  const [reviewNote, setReviewNote] = useState("");
  const [matchedAmoContactId, setMatchedAmoContactId] = useState("");

  useEffect(() => {
    if (!selectedCallInsight) {
      setReviewDecision("approved");
      setReviewNote("");
      setMatchedAmoContactId("");
      return;
    }
    setReviewDecision(
      REVIEW_DECISIONS.some((item) => item.value === selectedCallInsight.review_status)
        ? selectedCallInsight.review_status
        : "approved",
    );
    setReviewNote(selectedCallInsight.review_summary || "");
    setMatchedAmoContactId(
      selectedCallInsight.matched_amo_contact_id
        ? String(selectedCallInsight.matched_amo_contact_id)
        : "",
    );
  }, [selectedCallInsight?.id]);

  const identity = selectedCallInsight?.payload?.identity_hints || {};
  const summary = selectedCallInsight?.payload?.call_summary || {};
  const salesInsight = selectedCallInsight?.payload?.sales_insight || {};
  const interests = salesInsight?.interests || {};
  const nextStep = salesInsight?.next_step || {};
  const evidence = Array.isArray(summary?.evidence) ? summary.evidence : [];
  const filteredInsights = callInsights.filter((insight) => matchesQueueFilter(insight, queueFilter));

  return (
    <>
      <section className="grid grid-single page-scroll">
        <article className="panel module-hero-panel calls-hero-panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Модуль звонков</p>
              <h2>Звонки, разбор разговоров и догрузка сигналов в CRM</h2>
            </div>
            <div className="calls-hero-status">
              <span className={`status-chip status-${statusClass(callsModuleState.status)}`}>
                {callsModuleState.label}
              </span>
              <small>{selectedProject?.name || "Проект не выбран"}</small>
            </div>
          </header>

          <div className="calls-hero-grid">
            <article className="calls-summary-box">
              <p className="muted-label">Что видно сразу</p>
              <strong>{callsModuleState.summary}</strong>
              <p>{callsModuleState.nextStep}</p>
            </article>

            <div className="module-stats-grid calls-metrics-grid">
              <article className="module-stat-card">
                <span>Инсайты</span>
                <strong>{callInsightsCount}</strong>
                <small>получено из локального пайплайна</small>
              </article>
              <article className="module-stat-card">
                <span>Ждут матчинга</span>
                <strong>{callsPendingMatchCount}</strong>
                <small>ученик ещё не определён</small>
              </article>
              <article className="module-stat-card">
                <span>Требуют решения</span>
                <strong>{callsManualReviewCount}</strong>
                <small>нужен операторский выбор</small>
              </article>
              <article className="module-stat-card">
                <span>Одобрено</span>
                <strong>{callsApprovedCount}</strong>
                <small>можно писать в AMO</small>
              </article>
              <article className="module-stat-card">
                <span>Срочные лиды</span>
                <strong>{callsHotCount}</strong>
                <small>требуют приоритетного контакта</small>
              </article>
            </div>
          </div>

          <div className="note-block">
            <p className="muted-label">Как устроен модуль звонков</p>
            <p>
              Сырые записи разговоров не загружаются в AI Office вручную. Их обрабатывает локальный
              пайплайн на MacBook, а в этот модуль приходят уже готовые результаты: краткая сводка,
              кандидат ученика, сигналы для продаж и рекомендуемый следующий шаг.
            </p>
            <p>
              Ваша задача здесь: выбрать нужный звонок в очереди, проверить кого нашла система,
              при необходимости указать контакт AMO и принять операторское решение.
            </p>
          </div>

          <div className="calls-flow-strip">
            <div className="calls-flow-step">
              <span>1</span>
              <strong>Локальный пайплайн</strong>
              <small>готовит расшифровку и AI-анализ звонка</small>
            </div>
            <div className="calls-flow-step">
              <span>2</span>
              <strong>Приём в AI Office</strong>
              <small>сохраняет инсайт как артефакт и событие</small>
            </div>
            <div className="calls-flow-step">
              <span>3</span>
              <strong>Выбор ученика</strong>
              <small>не даёт слить брата и сестру по одному номеру</small>
            </div>
            <div className="calls-flow-step">
              <span>4</span>
              <strong>Запись в AMO</strong>
              <small>только после контролируемого решения</small>
            </div>
          </div>
        </article>
      </section>

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Операторская очередь</p>
              <h2>Очередь звонков для проверки</h2>
            </div>
            <label className="crm-inline-field">
              Показать
              <select value={queueFilter} onChange={(event) => setQueueFilter(event.target.value)}>
                {QUEUE_FILTERS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </header>

          {filteredInsights.length === 0 ? (
            <p className="empty-state">
              Под выбранный фильтр звонков нет. Когда локальный пайплайн начнёт присылать готовые
              результаты разбора, здесь появится рабочая очередь звонков.
            </p>
          ) : (
            <>
              <div className="note-block calls-inline-guide">
                <p className="muted-label">Что означают статусы</p>
                <p>Ждёт проверки — нужен человек, чтобы подтвердить ученика или выбрать семейный кейс.</p>
                <p>Ученик найден — система уже считает матч надёжным.</p>
                <p>Одобрено — можно записывать вывод в AMO.</p>
              </div>
              <div className="calls-insight-list">
              {filteredInsights.map((insight) => {
                const isActive = insight.id === selectedCallInsight?.id;
                return (
                  <button
                    className={`calls-insight-row${isActive ? " calls-insight-row-active" : ""}`}
                    key={insight.id}
                    onClick={() => setSelectedCallInsightId(insight.id)}
                    type="button"
                  >
                    <div className="calls-insight-row-head">
                      <div>
                        <strong>{displayInsightTitle(insight)}</strong>
                        <span>{displayInsightSubtitle(insight)}</span>
                        <span>Нажмите, чтобы открыть разбор звонка</span>
                      </div>
                      <div className="calls-insight-statuses">
                        <span className={`status-chip status-${statusClass(insight.review_status)}`}>
                          {formatReviewStatus(insight.review_status)}
                        </span>
                        <span className={`status-chip status-${statusClass(insight.match_status)}`}>
                          {formatCallMatchStatus(insight.match_status)}
                        </span>
                        <span className={`status-chip status-${statusClass(insight.lead_priority || "idle")}`}>
                          {formatCallPriority(insight.lead_priority)}
                        </span>
                      </div>
                    </div>

                    <p>{shortenText(insight.history_summary, 160)}</p>

                    <div className="calls-insight-meta">
                      <span>{formatDate(insight.started_at || insight.created_at)}</span>
                      <span>{insight.manager_name || "Менеджер не указан"}</span>
                      <span>{insight.follow_up_score ?? "—"} / 100</span>
                    </div>
                  </button>
                );
              })}
              </div>
            </>
          )}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Карточка звонка</p>
              <h2>Разбор выбранного инсайта</h2>
            </div>
          </header>

          {!selectedCallInsight ? (
            <p className="empty-state">Выберите звонок слева, чтобы посмотреть детали.</p>
          ) : (
            <div className="calls-detail-stack">
              <article className="calls-summary-box calls-summary-box-strong">
                <div className="calls-detail-topline">
                  <strong>{displayInsightTitle(selectedCallInsight)}</strong>
                  <span>{formatDate(selectedCallInsight.started_at || selectedCallInsight.created_at)}</span>
                </div>
                <p>{selectedCallInsight.history_summary}</p>
              </article>

              <div className="calls-detail-grid">
                <article className="calls-detail-card">
                  <p className="muted-label">Состояние</p>
                  <div className="calls-field-grid">
                    {renderDetailField("Сопоставление", formatCallMatchStatus(selectedCallInsight.match_status))}
                    {renderDetailField("Анализ", formatCallProcessingStatus(selectedCallInsight.processing_status))}
                    {renderDetailField("Проверка", formatReviewStatus(selectedCallInsight.review_status))}
                    {renderDetailField("Приоритет", formatCallPriority(selectedCallInsight.lead_priority))}
                    {renderDetailField(
                      "Оценка следующего шага",
                      selectedCallInsight.follow_up_score !== null
                        ? `${selectedCallInsight.follow_up_score}/100`
                        : "—",
                    )}
                    {renderDetailField("Менеджер", selectedCallInsight.manager_name)}
                    {renderDetailField(
                      "Длительность",
                      selectedCallInsight.duration_sec
                        ? `${Math.round(selectedCallInsight.duration_sec)} сек.`
                        : "—",
                    )}
                  </div>
                </article>

                <article className="calls-detail-card">
                  <p className="muted-label">Кого система поняла</p>
                  <div className="calls-field-grid">
                    {renderDetailField("Ученик", identity.child_fio)}
                    {renderDetailField("Родитель", identity.parent_fio)}
                    {renderDetailField("Телефон", selectedCallInsight.phone || identity.phone)}
                    {renderDetailField("Email", identity.email)}
                    {renderDetailField("Класс", identity.grade_current)}
                    {renderDetailField("Школа", identity.school)}
                  </div>
                </article>
              </div>

              <div className="calls-detail-grid">
                <article className="calls-detail-card">
                  <p className="muted-label">Сигналы для продаж</p>
                  <div className="calls-signal-block">
                    <span>Продукты</span>
                    {renderPillList(interests.products)}
                  </div>
                  <div className="calls-signal-block">
                    <span>Предметы</span>
                    {renderPillList(interests.subjects)}
                  </div>
                  <div className="calls-signal-block">
                    <span>Формат</span>
                    {renderPillList(interests.format)}
                  </div>
                  <div className="calls-signal-block">
                    <span>Возражения</span>
                    {renderPillList(salesInsight.objections)}
                  </div>
                  <div className="calls-field-grid">
                    {renderDetailField("Следующий шаг", nextStep.action)}
                    {renderDetailField("Когда", nextStep.due)}
                  </div>
                </article>

                <article className="calls-detail-card">
                  <p className="muted-label">Источник и контроль</p>
                  <div className="calls-field-grid">
                    {renderDetailField("Файл", selectedCallInsight.source_filename)}
                    {renderDetailField("ID звонка", selectedCallInsight.source_call_id)}
                    {renderDetailField("ID записи", selectedCallInsight.source_record_id)}
                    {renderDetailField(
                      "Контакт в AMO",
                      selectedCallInsight.matched_amo_contact_id
                        ? String(selectedCallInsight.matched_amo_contact_id)
                        : "Пока не привязан",
                    )}
                    {renderDetailField("Кем загружено", selectedCallInsight.created_by)}
                    {renderDetailField("Обновлено", formatDate(selectedCallInsight.updated_at))}
                  </div>
                  <div className="note-block">
                    <p className="muted-label">Где лежат файлы и где результат</p>
                    <p>
                      Аудиофайлы и расшифровка живут во внешнем локальном пайплайне. В AI Office вы видите
                      уже итог разбора: сводку разговора, сигналы для продаж и решение по записи в AMO.
                    </p>
                  </div>
                  {selectedCallInsight.review_reason ? (
                    <div className="note-block calls-attention-block">
                      <p className="muted-label">Почему нужен человек</p>
                      <p>{selectedCallInsight.review_reason}</p>
                    </div>
                  ) : null}
                  {selectedCallInsight.review_summary ? (
                    <div className="note-block">
                      <p className="muted-label">Последнее решение</p>
                      <p>{selectedCallInsight.review_summary}</p>
                    </div>
                  ) : null}
                  {callMessage ? (
                    <div className="note-block">
                      <p className="muted-label">Статус</p>
                      <p>{callMessage}</p>
                    </div>
                  ) : null}
                  <div className="calls-review-controls">
                    <label className="crm-inline-field">
                      Решение оператора
                      <select value={reviewDecision} onChange={(event) => setReviewDecision(event.target.value)}>
                        {REVIEW_DECISIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="note-block">
                      <p className="muted-label">Что это означает</p>
                      <p>{reviewHint(reviewDecision)}</p>
                    </div>
                    <label className="crm-inline-field">
                      ID контакта в AMO
                      <input
                        value={matchedAmoContactId}
                        onChange={(event) => setMatchedAmoContactId(event.target.value)}
                        placeholder="Нужно только если вы уже знаете нужный контакт"
                      />
                    </label>
                    <label className="crm-inline-field">
                      Комментарий оператора
                      <textarea
                        value={reviewNote}
                        onChange={(event) => setReviewNote(event.target.value)}
                        placeholder="Коротко: почему принято это решение"
                      />
                    </label>
                    <div className="action-row">
                      <button
                        disabled={Boolean(callReviewBusy) || selectedCallInsight.status === "sent"}
                        onClick={() =>
                          handleResolveCallReview({
                            outcome: reviewDecision,
                            matchedAmoContactId: matchedAmoContactId.trim() || null,
                            summary: reviewNote.trim() || null,
                          })
                        }
                        type="button"
                      >
                        {callReviewBusy ? "Сохраняю..." : "Сохранить решение"}
                      </button>
                      <button
                        disabled={
                          callSendBusy ||
                          selectedCallInsight.review_status !== "approved" ||
                          !matchedAmoContactId.trim()
                        }
                        onClick={() =>
                          handleSendCallInsight({
                            matchedAmoContactId: matchedAmoContactId.trim(),
                          })
                        }
                        type="button"
                      >
                        {callSendBusy ? "Отправляю..." : "Записать вывод в AMO"}
                      </button>
                    </div>
                  </div>
                </article>
              </div>

              <article className="calls-detail-card">
                <header className="panel-header calls-detail-card-head">
                  <div>
                    <p className="panel-kicker">Фрагменты разговора</p>
                    <h3>На чём основан вывод</h3>
                  </div>
                  <div className="action-row">
                    <button className="button-ghost" onClick={handleOpenRuns} type="button">
                      Открыть запуски
                    </button>
                    <button className="button-ghost" onClick={handleOpenApprovals} type="button">
                      Одобрения
                    </button>
                    <button type="button" onClick={handleOpenDirector}>
                      К директору
                    </button>
                  </div>
                </header>

                {evidence.length === 0 ? (
                  <p className="empty-state">Для этого звонка пока нет выделенных цитат.</p>
                ) : (
                  <div className="calls-evidence-list">
                    {evidence.map((item, index) => (
                      <article className="calls-evidence-item" key={`${item.ts || "na"}-${index}`}>
                        <div className="calls-evidence-head">
                          <strong>{item.speaker || "Спикер не определён"}</strong>
                          <span>{item.ts || "без таймкода"}</span>
                        </div>
                        <p>{item.text}</p>
                      </article>
                    ))}
                  </div>
                )}
              </article>
            </div>
          )}
        </article>
      </section>

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Связанные задачи</p>
              <h2>Что делает офис вокруг звонков</h2>
            </div>
          </header>

          {callsFocusTasks.length === 0 ? (
            <p className="empty-state">
              Директор пока не создал отдельные задачи по звонкам. Следующий ход: поставить цель
              на приём звонков, матчинг по семье и контролируемую запись в AMO.
            </p>
          ) : (
            <div className="task-list">
              {callsFocusTasks.map((task) => (
                <article className="task-row task-row-static" key={task.id}>
                  <div>
                    <strong>{task.title}</strong>
                    <span>{renderTaskMeta(task, displayAgentRole, formatTaskStatus)}</span>
                    <span>{task.brief}</span>
                  </div>
                  <span className={`status-chip status-${statusClass(task.status)}`}>
                    {formatTaskStatus(task.status)}
                  </span>
                </article>
              ))}
            </div>
          )}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Артефакты модуля</p>
              <h2>Что уже сохранил AI Office</h2>
            </div>
          </header>

          {callsArtifacts.length === 0 ? (
            <p className="empty-state">Артефактов по звонкам пока нет.</p>
          ) : (
            <div className="task-list">
              {callsArtifacts.map((artifact) => (
                <article className="task-row task-row-static" key={artifact.id}>
                  <div>
                    <strong>{artifact.title}</strong>
                    <span>{formatDate(artifact.created_at)}</span>
                    <span>{shortenText(artifact.content, 140)}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </article>
      </section>
    </>
  );
}
