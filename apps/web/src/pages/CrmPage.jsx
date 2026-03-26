import { useEffect, useState } from "react";

const REVIEW_DECISIONS = [
  {
    value: "approved",
    label: "Можно писать в AMO",
    hint: "Профиль проверен, можно делать контролируемую запись.",
  },
  {
    value: "family_case",
    label: "Семейный кейс",
    hint: "Общий телефон или email относятся к нескольким ученикам.",
  },
  {
    value: "needs_correction",
    label: "Нужна корректировка",
    hint: "Нужно исправить поля профиля или источник данных.",
  },
  {
    value: "insufficient_data",
    label: "Недостаточно данных",
    hint: "Пока нельзя безопасно выбрать ученика или карточку.",
  },
  {
    value: "duplicate",
    label: "Похоже на дубль",
    hint: "Есть риск, что запись дублирует существующую карточку.",
  },
];

const QUEUE_FILTERS = [
  { value: "needs_action", label: "Требуют решения" },
  { value: "approved", label: "Одобрены" },
  { value: "sent", label: "Отправлены" },
  { value: "failed", label: "С ошибкой" },
  { value: "all", label: "Все" },
];

function reviewNeedsOperatorAction(reviewStatus) {
  return !["approved", "not_required", "", null, undefined].includes(reviewStatus);
}

function matchesQueueFilter(preview, filter) {
  if (filter === "all") {
    return true;
  }
  if (filter === "approved") {
    return preview.review_status === "approved";
  }
  if (filter === "sent") {
    return preview.status === "sent";
  }
  if (filter === "failed") {
    return preview.status === "failed";
  }
  return reviewNeedsOperatorAction(preview.review_status);
}

function prettifyFieldLabel(fieldName) {
  return String(fieldName || "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .trim();
}

function renderPayloadRows(payload) {
  const entries = Object.entries(payload || {}).filter(([, value]) => value !== null && value !== "");
  if (entries.length === 0) {
    return <p className="empty-state">Нет данных для отображения.</p>;
  }

  return (
    <div className="calls-field-grid">
      {entries.slice(0, 10).map(([key, value]) => (
        <div className="calls-field-item" key={key}>
          <span>{prettifyFieldLabel(key)}</span>
          <strong>{typeof value === "string" ? value : JSON.stringify(value)}</strong>
        </div>
      ))}
    </div>
  );
}

function reviewHint(decision) {
  return REVIEW_DECISIONS.find((item) => item.value === decision)?.hint || "Выберите действие оператора.";
}

function displayPreviewTitle(preview) {
  const fullName = preview?.canonical_payload?.full_name;
  if (fullName) {
    return fullName;
  }
  return preview?.source_student_id || "Превью без имени";
}

function displayPreviewSubtitle(preview) {
  const sourceId = preview?.source_student_id;
  const program = preview?.canonical_payload?.program;
  const phone = preview?.canonical_payload?.phone;
  return [sourceId, program, phone].filter(Boolean).join(" · ") || "Карточка без дополнительных данных";
}

export default function CrmPage({
  crmApprovedCount,
  crmFailedCount,
  crmFieldValues,
  crmLookupMode,
  crmMessage,
  crmPreviewBusy,
  crmPreviews,
  crmReviewBusy,
  crmReviewQueueCount,
  crmSelectedFields,
  crmSendBusy,
  crmSentCount,
  crmStudentId,
  formatCrmStatus,
  formatDate,
  formatReviewStatus,
  handleCreateCrmPreview,
  handleCrmFieldValueChange,
  handleOpenAmoConnect,
  handleResolveCrmReview,
  handleSendCrmPreview,
  handleToggleCrmField,
  selectedCrmPreview,
  selectedProject,
  setCrmLookupMode,
  setCrmStudentId,
  setSelectedCrmPreviewId,
  statusClass,
}) {
  const [queueFilter, setQueueFilter] = useState("needs_action");
  const [reviewDecision, setReviewDecision] = useState("approved");
  const [reviewNote, setReviewNote] = useState("");
  const [amoContactId, setAmoContactId] = useState("");

  useEffect(() => {
    if (!selectedCrmPreview) {
      setReviewDecision("approved");
      setReviewNote("");
      setAmoContactId("");
      return;
    }
    setReviewDecision(
      REVIEW_DECISIONS.some((item) => item.value === selectedCrmPreview.review_status)
        ? selectedCrmPreview.review_status
        : "approved",
    );
    setReviewNote(selectedCrmPreview.review_summary || "");
    setAmoContactId(selectedCrmPreview.amo_entity_id || "");
  }, [selectedCrmPreview?.id]);

  const filteredPreviews = crmPreviews.filter((preview) => matchesQueueFilter(preview, queueFilter));

  return (
    <>
      <section className="grid grid-single page-scroll">
        <article className="panel module-hero-panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Модуль CRM</p>
              <h2>Перенос и обогащение данных Tallanto -&gt; AMO</h2>
            </div>
          </header>

          <div className="module-hero-copy">
            <p>
              Модуль нужен для точечного переноса: найти ученика в Tallanto, собрать профиль,
              проверить его оператором и только потом записать нужные поля в AMO.
            </p>
            <p>
              Здесь скрыты технические mapping-настройки. На экране остаются только действия, которые
              реально нужны владельцу или оператору: найти ученика, проверить карточку, принять решение
              и отправить одобренные поля.
            </p>
          </div>

          {handleOpenAmoConnect ? (
            <div className="action-row">
              <button className="button-ghost" onClick={handleOpenAmoConnect} type="button">
                Подключить или проверить amoCRM
              </button>
            </div>
          ) : null}

          <div className="module-stats-grid">
            <article className="module-stat-card">
              <span>Проект</span>
              <strong>{selectedProject?.name || "Не выбран"}</strong>
              <small>рабочий контекст модуля</small>
            </article>
            <article className="module-stat-card">
              <span>Требуют решения</span>
              <strong>{crmReviewQueueCount}</strong>
              <small>операторская очередь перед записью</small>
            </article>
            <article className="module-stat-card">
              <span>Одобрено</span>
              <strong>{crmApprovedCount}</strong>
              <small>можно писать в AMO</small>
            </article>
            <article className="module-stat-card">
              <span>Отправлено</span>
              <strong>{crmSentCount}</strong>
              <small>контролируемая запись завершена</small>
            </article>
            <article className="module-stat-card">
              <span>Ошибки</span>
              <strong>{crmFailedCount}</strong>
              <small>требуют разбора</small>
            </article>
          </div>
        </article>
      </section>

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Источник</p>
              <h2>Найти ученика и собрать превью</h2>
            </div>
          </header>

          {!selectedProject ? (
            <p className="empty-state">Сначала создайте и выберите проект.</p>
          ) : (
            <form className="stack-form" onSubmit={handleCreateCrmPreview}>
              <p className="muted-label">
                Проект: <strong>{selectedProject.name}</strong>
              </p>
              <input
                value={crmStudentId}
                onChange={(event) => setCrmStudentId(event.target.value)}
                placeholder="ID / телефон / email / ФИО в Tallanto"
                required
              />
              <label className="crm-inline-field">
                Как искать в Tallanto
                <select value={crmLookupMode} onChange={(event) => setCrmLookupMode(event.target.value)}>
                  <option value="auto">Авто</option>
                  <option value="contact_id">ID контакта</option>
                  <option value="phone">Телефон</option>
                  <option value="email">Email</option>
                  <option value="full_name">ФИО</option>
                </select>
              </label>
              <button type="submit" disabled={crmPreviewBusy}>
                {crmPreviewBusy ? "Создаю превью..." : "Построить превью"}
              </button>
            </form>
          )}

          <div className="note-block">
            <p className="muted-label">Что делать в этом модуле</p>
            <p>1. Найдите ученика по ID, телефону, email или ФИО.</p>
            <p>2. Выберите слева нужное превью из очереди.</p>
            <p>3. Проверьте карточку и примите решение оператора.</p>
            <p>4. Только после статуса «Одобрено» отправляйте выбранные поля в AMO.</p>
          </div>

          {crmMessage ? (
            <div className="note-block">
              <p className="muted-label">Статус</p>
              <p>{crmMessage}</p>
            </div>
          ) : null}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Операторская очередь</p>
              <h2>CRM-превью проекта</h2>
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

          {filteredPreviews.length === 0 ? (
            <p className="empty-state">Под выбранный фильтр записей нет.</p>
          ) : (
            <div className="task-list">
              {filteredPreviews.map((preview) => (
                <button
                  className={`task-row ${preview.id === selectedCrmPreview?.id ? "task-row-active" : ""}`}
                  key={preview.id}
                  onClick={() => setSelectedCrmPreviewId(preview.id)}
                  type="button"
                >
                  <div>
                    <strong>{displayPreviewTitle(preview)}</strong>
                    <span>{formatDate(preview.created_at)}</span>
                    <span>{displayPreviewSubtitle(preview)}</span>
                    <span>{preview.analysis_summary}</span>
                  </div>
                  <div className="crm-row-statuses">
                    <span className={`status-chip status-${statusClass(preview.review_status)}`}>
                      {formatReviewStatus(preview.review_status)}
                    </span>
                    <span className={`status-chip status-${statusClass(preview.status)}`}>
                      {formatCrmStatus(preview.status)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </article>
      </section>

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Выбранная запись</p>
              <h2>{selectedCrmPreview ? selectedCrmPreview.source_student_id : "Выберите CRM-превью"}</h2>
            </div>
          </header>

          {!selectedCrmPreview ? (
            <p className="empty-state">Выберите превью в очереди, чтобы проверить профиль.</p>
          ) : (
            <div className="calls-detail-stack">
              <div className="note-block">
                <p className="muted-label">Статус проверки</p>
                <p>
                  <strong>{formatReviewStatus(selectedCrmPreview.review_status)}</strong>
                </p>
                {selectedCrmPreview.review_reason ? <p>{selectedCrmPreview.review_reason}</p> : null}
                {selectedCrmPreview.review_summary ? <p>{selectedCrmPreview.review_summary}</p> : null}
              </div>

              <div className="note-block">
                <p className="muted-label">Сводка по карточке</p>
                <p>{selectedCrmPreview.analysis_summary}</p>
              </div>
              <div className="note-block">
                <p className="muted-label">Как читать эту карточку</p>
                <p>
                  Сначала посмотрите, кого именно система нашла в Tallanto. Затем проверьте поля,
                  которые предлагает записать в AMO. Если речь о брате или сестре с общим телефоном,
                  выбирайте «Семейный кейс», а не «Одобрено».
                </p>
              </div>

              <article className="calls-detail-card">
                <p className="muted-label">Ключевые поля профиля</p>
                {renderPayloadRows(selectedCrmPreview.canonical_payload)}
              </article>

              <article className="calls-detail-card">
                <p className="muted-label">Что система предлагает записать в AMO</p>
                {renderPayloadRows(selectedCrmPreview.amo_field_payload)}
              </article>
            </div>
          )}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Решение оператора</p>
              <h2>Проверка перед записью в AMO</h2>
            </div>
          </header>

          {!selectedCrmPreview ? (
            <p className="empty-state">Сначала выберите CRM-превью.</p>
          ) : (
            <>
              <label className="crm-inline-field">
                Решение
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
                  value={amoContactId}
                  onChange={(event) => setAmoContactId(event.target.value)}
                  placeholder="Заполняйте только если карточка в AMO уже известна"
                />
              </label>
              <label className="crm-inline-field">
                Комментарий оператора
                <textarea
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                  placeholder="Коротко: почему принято именно это решение"
                />
              </label>
              <div className="action-row">
                <button
                  type="button"
                  disabled={Boolean(crmReviewBusy) || selectedCrmPreview.status === "sent"}
                  onClick={() =>
                    handleResolveCrmReview({
                      outcome: reviewDecision,
                      summary: reviewNote.trim() || null,
                      amoEntityId: amoContactId.trim() || null,
                    })
                  }
                >
                  {crmReviewBusy ? "Сохраняю..." : "Сохранить решение"}
                </button>
              </div>
            </>
          )}
        </article>
      </section>

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Точечная отправка</p>
              <h2>Что именно уйдёт в AMO</h2>
            </div>
          </header>

          {!selectedCrmPreview ? (
            <p className="empty-state">Сначала выберите CRM-превью.</p>
          ) : Object.keys(selectedCrmPreview.amo_field_payload || {}).length === 0 ? (
            <p className="empty-state">Нет полей для отправки.</p>
          ) : (
            <>
              <div className="crm-fields-grid">
                {Object.entries(selectedCrmPreview.amo_field_payload || {}).map(([fieldName]) => (
                  <label className="crm-send-field" key={fieldName}>
                    <span className="crm-send-check">
                      <input
                        type="checkbox"
                        checked={crmSelectedFields.includes(fieldName)}
                        onChange={() => handleToggleCrmField(fieldName)}
                      />
                      <strong>{fieldName}</strong>
                    </span>
                    <input
                      value={crmFieldValues[fieldName] ?? ""}
                      onChange={(event) => handleCrmFieldValueChange(fieldName, event.target.value)}
                      disabled={!crmSelectedFields.includes(fieldName)}
                    />
                  </label>
                ))}
              </div>
              <p className="hint-text">
                Выбрано полей: {crmSelectedFields.length}. Значения можно вручную исправить перед записью.
              </p>
              <div className="note-block">
                <p className="muted-label">Контроль записи</p>
                <p>
                  Отправка доступна только после статуса{" "}
                  <strong>{formatReviewStatus("approved")}</strong>.
                </p>
                <p>
                  Здесь показаны только поля, которые реально могут уйти в AMO. Служебные технические
                  mapping-настройки на этом экране скрыты.
                </p>
              </div>
              <div className="action-row">
                <button
                  onClick={() => handleSendCrmPreview({ amoEntityId: amoContactId.trim() || null })}
                  disabled={
                    crmSendBusy ||
                    crmSelectedFields.length === 0 ||
                    selectedCrmPreview.review_status !== "approved"
                  }
                  type="button"
                >
                  {crmSendBusy ? "Отправляю..." : "Отправить в AMO"}
                </button>
              </div>
            </>
          )}
        </article>
      </section>
    </>
  );
}
