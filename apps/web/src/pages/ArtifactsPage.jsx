const ARTIFACT_KIND_LABELS = {
  spec: "Документ или спецификация",
  crm_preview: "Черновик переноса в CRM",
  crm_sync_result: "Результат записи в AMO",
  call_insight: "Разбор звонка",
  call_sync_result: "Результат записи звонка в AMO",
  codex_result: "Результат выполнения задачи",
  workspace_change_summary: "Изменения в рабочей папке",
  source_workspace_sync_summary: "Применение изменений в основной проект",
};

const ARTIFACT_KIND_HINTS = {
  spec: "Полезно, когда нужно понять, что именно спроектировал или описал офис.",
  crm_preview: "Показывает, что система подготовила перед записью данных в AMO.",
  crm_sync_result: "Фиксирует итог контролируемой записи в AMO и возможную ошибку.",
  call_insight: "Содержит краткий разбор звонка и выводы для продаж.",
  call_sync_result: "Показывает, какие выводы по звонку были записаны в CRM.",
  codex_result: "Это итог конкретного запуска сотрудника или директора.",
  workspace_change_summary: "Помогает понять, какие файлы реально изменились в рабочей папке.",
  source_workspace_sync_summary: "Показывает, какие одобренные изменения были перенесены из изолированной рабочей папки в основной проект.",
};

function formatArtifactKind(kind) {
  return ARTIFACT_KIND_LABELS[kind] || "Сохранённый результат работы";
}

function formatArtifactHint(kind) {
  return ARTIFACT_KIND_HINTS[kind] || "Это сохранённый результат работы офиса.";
}

export default function ArtifactsPage({
  artifactWindowFilter,
  filteredArtifacts,
  formatDate,
  setArtifactWindowFilter,
  shortenText,
}) {
  return (
    <section className="grid grid-single page-scroll">
      <article className="panel">
        <header className="panel-header">
          <div>
            <p className="panel-kicker">Артефакты</p>
            <h2>Понятные результаты работы офиса</h2>
          </div>
        </header>
        <div className="note-block">
          <p className="muted-label">Что такое артефакт</p>
          <p>
            Артефакт — это любой сохранённый результат работы офиса: документ, черновик переноса в CRM,
            итог записи в AMO, разбор звонка или список изменений в рабочей папке.
          </p>
        </div>
        <div className="filter-row">
          <label>
            Период
            <select
              value={artifactWindowFilter}
              onChange={(event) => setArtifactWindowFilter(event.target.value)}
            >
              <option value="all">За всё время</option>
              <option value="24h">24 часа</option>
              <option value="7d">7 дней</option>
              <option value="30d">30 дней</option>
            </select>
          </label>
        </div>
        {filteredArtifacts.length === 0 ? (
          <p className="empty-state">За выбранный период артефактов нет.</p>
        ) : (
          <div className="event-list">
            {filteredArtifacts.map((artifact) => (
              <article className="event-card" key={artifact.id}>
                <div className="event-head">
                  <strong>{artifact.title}</strong>
                  <span>{formatDate(artifact.created_at)}</span>
                </div>
                <p className="hint-text">Категория: {formatArtifactKind(artifact.kind)}</p>
                <p className="hint-text">{formatArtifactHint(artifact.kind)}</p>
                <p>{shortenText(artifact.content, 280)}</p>
                <details className="artifact-details">
                  <summary>Открыть содержимое</summary>
                  <pre className="log-box">{shortenText(artifact.content, 2400)}</pre>
                </details>
              </article>
            ))}
          </div>
        )}
      </article>
    </section>
  );
}
