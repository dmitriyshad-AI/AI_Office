const EVENT_SCOPE_OPTIONS = [
  { value: "all", label: "Все события" },
  { value: "director", label: "Директор" },
  { value: "runtime", label: "Запуски и среда" },
  { value: "crm", label: "CRM" },
  { value: "calls", label: "Звонки" },
  { value: "approvals", label: "Одобрения" },
  { value: "office", label: "Прочее по офису" },
];

export default function EventsPage({
  eventScopeFilter,
  eventTitle,
  eventWindowFilter,
  filteredEvents,
  formatDate,
  setEventScopeFilter,
  setEventWindowFilter,
  summarizeEventPayload,
}) {
  return (
    <section className="grid grid-single page-scroll">
      <article className="panel">
        <header className="panel-header">
          <div>
            <p className="panel-kicker">События</p>
            <h2>История того, что реально сделал офис</h2>
          </div>
        </header>
        <div className="note-block">
          <p className="muted-label">Зачем нужен этот экран</p>
          <p>
            Здесь собраны все заметные действия офиса: постановка цели, запуск задач, прогресс директора,
            создание CRM-превью, обработка звонков и другие изменения состояния. Это основной журнал,
            когда нужно понять, что уже произошло и почему офис пришёл к текущему статусу.
          </p>
        </div>
        <div className="filter-row">
          <label>
            Период
            <select
              value={eventWindowFilter}
              onChange={(event) => setEventWindowFilter(event.target.value)}
            >
              <option value="all">За всё время</option>
              <option value="24h">24 часа</option>
              <option value="7d">7 дней</option>
              <option value="30d">30 дней</option>
            </select>
          </label>
          <label>
            Область
            <select
              value={eventScopeFilter}
              onChange={(event) => setEventScopeFilter(event.target.value)}
            >
              {EVENT_SCOPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {filteredEvents.length === 0 ? (
          <p className="empty-state">Под выбранный фильтр событий нет.</p>
        ) : (
          <div className="event-list">
            {filteredEvents.map((event) => (
              <article className="event-card" key={event.id}>
                <div className="event-head">
                  <strong>{eventTitle(event.event_type)}</strong>
                  <span>{formatDate(event.created_at)}</span>
                </div>
                <p className="hint-text">Тип события: {event.event_type}</p>
                <p>{summarizeEventPayload(event.payload)}</p>
              </article>
            ))}
          </div>
        )}
      </article>
    </section>
  );
}
