export default function TeamPage({
  blockedAgentsCount,
  displayAgentBadge,
  displayAgentRole,
  displayAgentStatus,
  idleAgentsCount,
  reviewingAgentsCount,
  runningAgentsCount,
  sortedAgents,
  statusClass,
}) {
  return (
    <section className="grid grid-single page-scroll">
      <article className="panel">
        <header className="panel-header">
          <div>
            <p className="panel-kicker">Команда</p>
            <h2>Кто чем занят сейчас</h2>
          </div>
        </header>
        <div className="team-metrics">
          <div className="team-metric">
            <span>В работе</span>
            <strong>{runningAgentsCount}</strong>
          </div>
          <div className="team-metric">
            <span>На проверке</span>
            <strong>{reviewingAgentsCount}</strong>
          </div>
          <div className="team-metric">
            <span>Заблокированы</span>
            <strong>{blockedAgentsCount}</strong>
          </div>
          <div className="team-metric">
            <span>Ожидают</span>
            <strong>{idleAgentsCount}</strong>
          </div>
        </div>
        {sortedAgents.length === 0 ? (
          <p className="empty-state">Сотрудники появятся после создания проекта и плана задач.</p>
        ) : (
          <div className="agent-grid">
            {sortedAgents.map((agent) => (
              <article className="agent-card" key={agent.id}>
                <div className="agent-avatar">{displayAgentBadge(agent.role)}</div>
                <div className="agent-content">
                  <div className="agent-head">
                    <h3>{agent.name}</h3>
                    <span className={`status-chip status-${statusClass(agent.status)}`}>
                      {displayAgentStatus(agent.status)}
                    </span>
                  </div>
                  <p>{displayAgentRole(agent.role)}</p>
                  <p>{agent.current_task_title || "Нет активной задачи"}</p>
                  <p className="hint-text">{agent.specialization}</p>
                </div>
              </article>
            ))}
          </div>
        )}
      </article>
    </section>
  );
}
