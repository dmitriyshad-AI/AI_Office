export default function ApprovalsPage({
  approvalActionBusy,
  approvalStatusLabels,
  approvalsFilter,
  displayAgentRole,
  filteredApprovals,
  formatDate,
  handleResolveApproval,
  labelFromMap,
  riskLevelLabels,
  setApprovalsFilter,
  statusClass,
}) {
  return (
    <section className="grid grid-single page-scroll">
      <article className="panel">
        <header className="panel-header">
          <div>
            <p className="panel-kicker">Одобрения</p>
            <h2>Действия с риском</h2>
          </div>
        </header>
        <div className="filter-row">
          <label>
            Показать
            <select value={approvalsFilter} onChange={(event) => setApprovalsFilter(event.target.value)}>
              <option value="pending">Только ожидающие</option>
              <option value="all">Все</option>
              <option value="approved">Одобренные</option>
              <option value="rejected">Отклонённые</option>
            </select>
          </label>
        </div>
        {filteredApprovals.length === 0 ? (
          <p className="empty-state">Под выбранный фильтр записей нет.</p>
        ) : (
          <div className="event-list">
            {filteredApprovals.map((approval) => (
              <article className="event-card" key={approval.id}>
                <div className="event-head">
                  <strong>{approval.action}</strong>
                  <span>{formatDate(approval.created_at)}</span>
                </div>
                <p>
                  Статус:{" "}
                  <strong>{labelFromMap(approvalStatusLabels, approval.status, approval.status)}</strong>
                </p>
                <p>
                  Риск:{" "}
                  <span className={`risk-chip risk-${statusClass(approval.risk_level)}`}>
                    {labelFromMap(riskLevelLabels, approval.risk_level, approval.risk_level)}
                  </span>
                </p>
                <p>{approval.reason}</p>
                {approval.status === "pending" ? (
                  <div className="action-row">
                    <button
                      onClick={() => handleResolveApproval(approval.id, "approved")}
                      disabled={Boolean(approvalActionBusy)}
                      type="button"
                    >
                      {approvalActionBusy === `${approval.id}:approved` ? "Одобряю..." : "Одобрить"}
                    </button>
                    <button
                      className="button-ghost"
                      onClick={() => handleResolveApproval(approval.id, "rejected")}
                      disabled={Boolean(approvalActionBusy)}
                      type="button"
                    >
                      {approvalActionBusy === `${approval.id}:rejected` ? "Отклоняю..." : "Отклонить"}
                    </button>
                  </div>
                ) : (
                  <p className="hint-text">
                    Решение: {displayAgentRole(approval.resolved_by || "System")} ·{" "}
                    {formatDate(approval.resolved_at)}
                  </p>
                )}
              </article>
            ))}
          </div>
        )}
      </article>
    </section>
  );
}
