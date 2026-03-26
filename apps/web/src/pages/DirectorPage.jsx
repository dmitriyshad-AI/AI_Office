export default function DirectorPage({
  actionBusy,
  blockedTasks,
  blockedTasksCount,
  busy,
  busyAgentsCount,
  cancelBusy,
  completionPercent,
  createDescription,
  createName,
  directorAgent,
  displayAgentBadge,
  displayAgentRole,
  displayAgentStatus,
  doneTasksCount,
  eventTitle,
  executionBusy,
  focusTasks,
  formatDate,
  formatTaskStatus,
  goalText,
  handleAdvanceDirector,
  handleCancelRun,
  handleCreateProject,
  handleOpenApprovals,
  handleOpenCrm,
  handleOpenEvents,
  handleOpenRuns,
  handleOpenTaskRuns,
  handleOpenTeam,
  handleArchiveProject,
  handleRestoreProject,
  handleSubmitGoal,
  handleTaskAction,
  latestDirectorMessage,
  latestEvent,
  nextAction,
  officeAgents,
  pendingApprovalsCount,
  planSummary,
  preflightBlockingChecks,
  preflightStatus,
  projectsCount,
  readyTasks,
  readyTasksCount,
  recentDirectorMessages,
  reviewTasksCount,
  runLogs,
  runningTaskRun,
  runningTasksCount,
  selectedProject,
  selectedRun,
  selectedTask,
  selectedTaskPreflight,
  setCreateDescription,
  setCreateName,
  setGoalText,
  setSelectedTaskId,
  shortenText,
  sortedAgentsCount,
  statusClass,
  summarizeEventPayload,
  projectActionBusy,
}) {
  const hasProject = Boolean(selectedProject);
  const hasAnyProjects = projectsCount > 0;
  const projectArchived = selectedProject?.status === "archived";

  return (
    <div className="director-layout">
      <section className="grid grid-main">
        <article className="panel director-hero-panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Директор</p>
              <h2>
                {hasProject ? "Поставьте новую цель" : hasAnyProjects ? "Выберите рабочий проект" : "Создайте первый проект"}
              </h2>
            </div>
          </header>

          {hasProject ? (
            <form className="stack-form" onSubmit={handleSubmitGoal}>
              <p className="muted-label">
                Проект: <strong>{selectedProject.name}</strong>
              </p>
              {projectArchived ? (
                <div className="note-block">
                  <p className="muted-label">Проект в архиве</p>
                  <p>
                    Архив полезен для старых учебных прогонов и завершённых задач. Чтобы снова ставить цели,
                    сначала верните проект в рабочий список.
                  </p>
                </div>
              ) : null}
              <textarea
                value={goalText}
                onChange={(event) => setGoalText(event.target.value)}
                placeholder="Например: Подготовь CRM-пайплайн по анализу учеников и безопасной записи в AMO CRM"
                disabled={projectArchived}
                required
              />
              <p className="hint-text">
                Директор разобьёт цель на задачи, назначит сотрудников и начнёт исполнение по очереди.
              </p>
              <div className="director-form-actions">
                <button type="submit" disabled={busy || projectArchived}>
                  {busy ? "Отправляю..." : "Отправить цель директору"}
                </button>
                <button
                  className="button-ghost"
                  onClick={projectArchived ? handleRestoreProject : handleArchiveProject}
                  type="button"
                >
                  {projectActionBusy === "archive"
                    ? "Архивирую..."
                    : projectActionBusy === "restore"
                      ? "Возвращаю..."
                      : projectArchived
                        ? "Вернуть проект в работу"
                        : "Архивировать проект"}
                </button>
              </div>
            </form>
          ) : (
            <form className="stack-form" onSubmit={handleCreateProject}>
              <p className="muted-label">
                {hasAnyProjects
                  ? "Сначала выберите рабочий проект в верхней панели или создайте новый, если нужен отдельный контур работы."
                  : "Без проекта директор не сможет построить план и команду."}
              </p>
              <input
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                placeholder={hasAnyProjects ? "Название нового проекта" : "Название проекта"}
                required
              />
              <input
                value={createDescription}
                onChange={(event) => setCreateDescription(event.target.value)}
                placeholder="Описание (необязательно)"
              />
              <button type="submit" disabled={busy}>
                {busy ? "Создаю..." : "Создать проект"}
              </button>
            </form>
          )}

          <div className="director-summary-card">
            <p className="muted-label">Последний ответ директора</p>
            <p>
              {planSummary ||
                latestDirectorMessage?.content ||
                "После первой цели директор покажет здесь краткий план и ход работы."}
            </p>
          </div>
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Состояние проекта</p>
              <h2>Что происходит прямо сейчас</h2>
            </div>
          </header>

          <div className="office-visual">
            <div className="progress-ring-card">
              <div className="progress-ring" style={{ "--progress": `${completionPercent}%` }}>
                <strong>{completionPercent}%</strong>
                <span>выполнено</span>
              </div>
              <ul className="progress-list">
                <li>
                  <span>Готово к запуску</span>
                  <strong>{readyTasksCount}</strong>
                </li>
                <li>
                  <span>В работе</span>
                  <strong>{runningTasksCount}</strong>
                </li>
                <li>
                  <span>На проверке</span>
                  <strong>{reviewTasksCount}</strong>
                </li>
                <li>
                  <span>Выполнено</span>
                  <strong>{doneTasksCount}</strong>
                </li>
                <li>
                  <span>Требуют решения</span>
                  <strong>{pendingApprovalsCount + blockedTasksCount}</strong>
                </li>
              </ul>
            </div>

            <div className="team-visual">
              <p className="muted-label">Команда сейчас</p>
              <div className="office-team-grid">
                <article className="office-person office-person-director">
                  <div className="office-avatar">{displayAgentBadge(directorAgent?.role || "Director")}</div>
                  <div>
                    <strong>{directorAgent?.name || "Директор"}</strong>
                    <p>{displayAgentRole(directorAgent?.role || "Director")}</p>
                    {!hasProject ? <p className="hint-text">Нет активного проекта</p> : null}
                    <span className={`status-chip status-${statusClass(directorAgent?.status || "idle")}`}>
                      {displayAgentStatus(directorAgent?.status || "idle")}
                    </span>
                  </div>
                </article>
                {officeAgents.length > 0 ? (
                  officeAgents.map((agent) => (
                    <article className="office-person" key={agent.id}>
                      <div className="office-avatar">{displayAgentBadge(agent.role)}</div>
                      <div>
                        <strong>{agent.name}</strong>
                        <p>{displayAgentRole(agent.role)}</p>
                        <span className={`status-chip status-${statusClass(agent.status)}`}>
                          {displayAgentStatus(agent.status)}
                        </span>
                      </div>
                    </article>
                  ))
                ) : (
                  <p className="hint-text">Сотрудники появятся после первой цели.</p>
                )}
              </div>
              <p className="hint-text">
                Активно заняты: {busyAgentsCount} из {sortedAgentsCount} сотрудников.
              </p>
            </div>
          </div>
        </article>
      </section>

      <section className="grid grid-main">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Следующее действие</p>
              <h2>Куда директору идти дальше</h2>
            </div>
          </header>

          <div className="director-next-action">
            <div className="note-block">
              <p>
                <strong>{nextAction.title}</strong>
              </p>
              <p>{nextAction.description}</p>
              {nextAction.buttonLabel && nextAction.buttonAction ? (
                <button className="button-ghost" onClick={nextAction.buttonAction} type="button">
                  {nextAction.buttonLabel}
                </button>
              ) : null}
            </div>

            <div className="director-quick-actions">
              <button className="button-ghost" onClick={handleOpenRuns} type="button">
                Открыть запуски
              </button>
              <button className="button-ghost" onClick={handleOpenEvents} type="button">
                Открыть события
              </button>
              <button className="button-ghost" onClick={handleOpenApprovals} type="button">
                Открыть одобрения
              </button>
              <button className="button-ghost" onClick={handleOpenTeam} type="button">
                Открыть команду
              </button>
              <button className="button-ghost" onClick={handleOpenCrm} type="button">
                Открыть CRM-модуль
              </button>
            </div>
          </div>

          <div className="director-block-grid">
            <div className="note-block">
              <p className="muted-label">Готово к запуску</p>
              {readyTasks.length > 0 ? (
                <ul className="simple-list compact-list">
                  {readyTasks.map((task) => (
                    <li key={task.id}>
                      <div>
                        <strong>{task.title}</strong>
                        <span>{displayAgentRole(task.assigned_agent_role)}</span>
                      </div>
                      <button className="button-ghost button-small" onClick={() => handleOpenTaskRuns(task.id)} type="button">
                        Открыть
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">Нет задач, готовых к запуску.</p>
              )}
            </div>

            <div className="note-block">
              <p className="muted-label">Заблокировано</p>
              {blockedTasks.length > 0 ? (
                <ul className="simple-list compact-list">
                  {blockedTasks.map((task) => (
                    <li key={task.id}>
                      <div>
                        <strong>{task.title}</strong>
                        <span>{formatTaskStatus(task.status)}</span>
                      </div>
                      <button className="button-ghost button-small" onClick={() => setSelectedTaskId(task.id)} type="button">
                        В фокус
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">Критических блокировок сейчас нет.</p>
              )}
            </div>
          </div>
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Отчёты директора</p>
              <h2>Краткая управленческая сводка</h2>
            </div>
          </header>

          <div className="note-block">
            <p className="muted-label">Последнее событие</p>
            {latestEvent ? (
              <>
                <p>
                  <strong>{eventTitle(latestEvent.event_type)}</strong>
                </p>
                <p>{summarizeEventPayload(latestEvent.payload)}</p>
                <p className="hint-text">{formatDate(latestEvent.created_at)}</p>
              </>
            ) : (
              <p className="empty-state">Событий пока нет.</p>
            )}
          </div>

          <div className="note-block">
            <p className="muted-label">Последние отчёты</p>
            {recentDirectorMessages.length > 0 ? (
              <ul className="simple-list compact-list">
                {recentDirectorMessages.map((message) => (
                  <li key={message.id}>
                    <div>
                      <strong>{shortenText(message.content, 170)}</strong>
                      <span>{formatDate(message.created_at)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-state">Отчётов пока нет.</p>
            )}
          </div>
        </article>
      </section>

      <section className="grid grid-main">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Задачи в фокусе</p>
              <h2>Что важно отслеживать директору</h2>
            </div>
          </header>
          {focusTasks.length === 0 ? (
            <p className="empty-state">После первой цели директор создаст список задач.</p>
          ) : (
            <div className="task-list">
              {focusTasks.map((task) => (
                <button
                  className={`task-row ${task.id === selectedTask?.id ? "task-row-active" : ""}`}
                  key={task.id}
                  onClick={() => setSelectedTaskId(task.id)}
                  type="button"
                >
                  <div>
                    <strong>{task.title}</strong>
                    <span>{displayAgentRole(task.assigned_agent_role)}</span>
                    <span>{task.brief}</span>
                  </div>
                  <span className={`status-chip status-${statusClass(task.status)}`}>
                    {formatTaskStatus(task.status)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Текущий фокус</p>
              <h2>{selectedTask ? selectedTask.title : "Выберите задачу"}</h2>
            </div>
          </header>

          {!selectedTask ? (
            <p className="empty-state">Выберите задачу слева, чтобы увидеть детали.</p>
          ) : (
            <>
              <div className="note-block">
                <p className="muted-label">Суть задачи</p>
                <p>{selectedTask.brief || "Описание не заполнено."}</p>
              </div>

              <div className="action-row">
                {selectedTask.status === "ready" ? (
                  <button onClick={handleAdvanceDirector} disabled={executionBusy} type="button">
                    {executionBusy ? "Проверяю..." : "Дать директору продолжить"}
                  </button>
                ) : null}
                {selectedTask.status === "running" ? (
                  <button
                    onClick={() => handleTaskAction("complete")}
                    disabled={Boolean(actionBusy)}
                    type="button"
                  >
                    {actionBusy === "complete" ? "Завершаю..." : "Отметить как выполненную"}
                  </button>
                ) : null}
                {runningTaskRun ? (
                  <button className="button-ghost" onClick={handleCancelRun} disabled={cancelBusy} type="button">
                    {cancelBusy ? "Останавливаю..." : "Остановить запуск"}
                  </button>
                ) : null}
                {["planned", "ready", "running"].includes(selectedTask.status) ? (
                  <button
                    className="button-ghost"
                    onClick={() => handleTaskAction("block")}
                    disabled={Boolean(actionBusy)}
                    type="button"
                  >
                    {actionBusy === "block" ? "Блокирую..." : "Заблокировать"}
                  </button>
                ) : null}
                {["blocked", "failed"].includes(selectedTask.status) ? (
                  <button
                    className="button-ghost"
                    onClick={() => handleTaskAction("reset")}
                    disabled={Boolean(actionBusy)}
                    type="button"
                  >
                    {actionBusy === "reset" ? "Возвращаю..." : "Вернуть в работу"}
                  </button>
                ) : null}
                <button className="button-ghost" onClick={() => handleOpenTaskRuns(selectedTask.id)} type="button">
                  Открыть в запусках
                </button>
              </div>

              <div className="note-block">
                <p className="muted-label">Проверка перед запуском</p>
                {preflightStatus === "loading" ? (
                  <p>Проверяю условия...</p>
                ) : selectedTaskPreflight ? (
                  <>
                    <p>{selectedTaskPreflight.summary}</p>
                    {preflightBlockingChecks.length > 0 ? (
                      <ul className="preflight-list">
                        {preflightBlockingChecks.map((check) => (
                          <li key={check.key}>
                            <strong>{check.key}</strong>: {check.message}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </>
                ) : (
                  <p className="empty-state">Пока нет данных.</p>
                )}
              </div>

              {selectedRun ? (
                <div className="note-block">
                  <p className="muted-label">Последний запуск</p>
                  <p>
                    Статус: <strong>{formatTaskStatus(selectedRun.status)}</strong>
                  </p>
                  <p className="hint-text">
                    Начат: {formatDate(selectedRun.started_at)} · Завершён: {formatDate(selectedRun.finished_at)}
                  </p>
                  <pre className="log-box">
                    {shortenText(runLogs?.stdout || "Логи появятся после запуска.", 900)}
                  </pre>
                </div>
              ) : null}
            </>
          )}
        </article>
      </section>
    </div>
  );
}
