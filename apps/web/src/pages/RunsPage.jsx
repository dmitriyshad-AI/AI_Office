function renderRuntimeValue(value, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join(", ") : fallback;
  }
  return String(value);
}

const PREFLIGHT_LABELS = {
  "workspace.exists": "Рабочая копия задачи доступна",
  "workspace.writable": "В рабочую копию можно записывать изменения",
  "workspace.root_available": "Корень проекта доступен",
  "docker.available": "Docker доступен",
  "docker.image_present": "Базовый образ найден",
  "docker.network_ready": "Сеть окружения готова",
  "git.available": "Git доступен",
  "git.worktree_ready": "Рабочая копия Git подготовлена",
  "codex.available": "Codex доступен",
  "codex.auth_ready": "Авторизация Codex готова",
};

function prettifyCheckKey(key) {
  if (!key) {
    return "Проверка";
  }
  return String(key)
    .replaceAll(".", " ")
    .replaceAll("_", " ")
    .trim()
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

function labelForCheck(key) {
  return PREFLIGHT_LABELS[key] || prettifyCheckKey(key);
}

function summarizeRunState(status) {
  switch (status) {
    case "running":
      return "Задача сейчас выполняется. Можно следить за логом или остановить запуск.";
    case "review":
      return "Задача ждёт проверки результата. Следующий шаг — посмотреть итог и принять решение.";
    case "done":
      return "Задача завершилась. Следующий шаг — проверить артефакты и итоговые изменения.";
    case "failed":
      return "Запуск завершился с ошибкой. Сначала посмотрите лог ошибок, потом решайте, что исправлять.";
    case "timed_out":
      return "Запуск превысил лимит времени. Проверьте, где задача зависла, и нужен ли повторный запуск.";
    case "cancelled":
      return "Запуск остановлен вручную. При необходимости его можно перезапустить позже.";
    default:
      return "Здесь видно текущее состояние задачи, её результат и следующий шаг.";
  }
}

function summarizePreflight(preflight) {
  const checks = Array.isArray(preflight?.checks) ? preflight.checks : [];
  const failed = checks.filter((check) => check.status === "fail").length;
  const warned = checks.filter((check) => check.status === "warn").length;
  const passed = checks.filter((check) => check.status === "pass").length;
  return { total: checks.length, failed, warned, passed };
}

export default function RunsPage({
  activeRunPreflight,
  activeRunRuntime,
  cancelBusy,
  cancelledRunsCount,
  failedRunsCount,
  formatDate,
  formatTaskStatus,
  handleCancelRun,
  handleSelectRun,
  pendingApprovalsCount,
  preflightStatus,
  projectRuns,
  reviewRunsCount,
  runLogs,
  runningRunsCount,
  runtimeStatus,
  selectedProject,
  selectedRun,
  selectedRunTask,
  statusClass,
  totalRunsCount,
}) {
  const preflightSummary = summarizePreflight(activeRunPreflight);

  return (
    <>
      <section className="grid grid-single page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Запуски</p>
              <h2>Исполнение задач и результат работы офиса</h2>
            </div>
          </header>
          <div className="note-block">
            <p>
              Экран показывает только то, что нужно для ручной проверки: идёт ли задача, чем она
              закончилась и что делать дальше. Технические детали запуска можно раскрыть ниже, если
              они действительно нужны.
            </p>
          </div>
          <div className="runs-overview-grid">
            <article className="run-overview-card">
              <span>Всего запусков</span>
              <strong>{totalRunsCount}</strong>
              <small>по текущему проекту</small>
            </article>
            <article className="run-overview-card">
              <span>Сейчас работают</span>
              <strong>{runningRunsCount}</strong>
              <small>активные исполнения</small>
            </article>
            <article className="run-overview-card">
              <span>На проверке</span>
              <strong>{reviewRunsCount}</strong>
              <small>ожидают оценки</small>
            </article>
            <article className="run-overview-card">
              <span>С риском</span>
              <strong>{pendingApprovalsCount}</strong>
              <small>одобрений ждут решения</small>
            </article>
            <article className="run-overview-card">
              <span>С ошибкой</span>
              <strong>{failedRunsCount}</strong>
              <small>ошибки и таймауты</small>
            </article>
            <article className="run-overview-card">
              <span>Остановлены</span>
              <strong>{cancelledRunsCount}</strong>
              <small>запуски отменены вручную</small>
            </article>
          </div>
        </article>
      </section>

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Очередь запусков</p>
              <h2>{selectedProject ? `Проект: ${selectedProject.name}` : "Выберите проект"}</h2>
            </div>
          </header>
          {!selectedProject ? (
            <p className="empty-state">Сначала создайте и выберите проект.</p>
          ) : projectRuns.length === 0 ? (
            <p className="empty-state">Запусков пока нет. Они появятся после первого исполнения задачи.</p>
          ) : (
            <div className="task-list">
              {projectRuns.map((run) => (
                <button
                  className={`task-row ${run.id === selectedRun?.id ? "task-row-active" : ""}`}
                  key={run.id}
                  onClick={() => handleSelectRun(run)}
                  type="button"
                >
                  <div>
                    <strong>{run.task_title}</strong>
                    <span>
                      {run.task_key} · {renderRuntimeValue(run.environment_name, "Окружение не задано")}
                    </span>
                    <span>{formatDate(run.started_at)}</span>
                  </div>
                  <span className={`status-chip status-${statusClass(run.status)}`}>
                    {formatTaskStatus(run.status)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Детали запуска</p>
              <h2>{selectedRun ? selectedRun.task_title : "Выберите запуск"}</h2>
            </div>
          </header>
          {!selectedRun ? (
            <p className="empty-state">Выберите запуск слева, чтобы увидеть детали.</p>
          ) : (
            <>
              <div className="runs-details-grid">
                <div className="note-block">
                  <p className="muted-label">Что происходит сейчас</p>
                  <p>
                    <strong>{formatTaskStatus(selectedRun.status)}</strong>
                  </p>
                  <p className="hint-text">
                    Старт: {formatDate(selectedRun.started_at)} · Завершение:{" "}
                    {formatDate(selectedRun.finished_at)}
                  </p>
                  <p>{summarizeRunState(selectedRun.status)}</p>
                </div>
                <div className="note-block">
                  <p className="muted-label">Что делает задача</p>
                  <p>
                    <strong>{selectedRun.task_title}</strong>
                  </p>
                  <p>{selectedRunTask?.brief || "Описание задачи появится после выбора контекста."}</p>
                </div>
              </div>

              {selectedRun.status === "running" ? (
                <div className="action-row">
                  <button className="button-ghost" onClick={handleCancelRun} disabled={cancelBusy} type="button">
                    {cancelBusy ? "Останавливаю..." : "Остановить запуск"}
                  </button>
                </div>
              ) : null}

              <div className="note-block">
                <p className="muted-label">Результат и лог</p>
                <p className="hint-text">
                  Здесь показан рабочий вывод запуска. Если задача завершилась с ошибкой, сначала
                  смотрите этот блок.
                </p>
                <pre className="log-box">
                  {runLogs?.stdout || runLogs?.stderr || "Логи появятся после запуска задачи."}
                </pre>
                {runLogs?.stderr ? (
                  <>
                    <p className="muted-label">Ошибки</p>
                    <pre className="log-box">{runLogs.stderr}</pre>
                  </>
                ) : null}
              </div>
            </>
          )}
        </article>
      </section>

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Готовность</p>
              <h2>Можно ли безопасно продолжать запуск</h2>
            </div>
          </header>
          {!selectedRun ? (
            <p className="empty-state">Сначала выберите запуск.</p>
          ) : runtimeStatus === "loading" || !activeRunRuntime ? (
            <p className="empty-state">Загружаю окружение задачи...</p>
          ) : (
            <>
              <div className="runs-details-grid">
                <div className="note-block">
                  <p className="muted-label">Короткий вывод</p>
                  <p>
                    <strong>
                      {preflightSummary.failed > 0
                        ? "Есть блокирующие проблемы"
                        : preflightSummary.warned > 0
                          ? "Есть предупреждения"
                          : "Окружение выглядит готовым"}
                    </strong>
                  </p>
                  <p className="hint-text">
                    Пройдено: {preflightSummary.passed} · Предупреждений: {preflightSummary.warned} ·
                    Ошибок: {preflightSummary.failed}
                  </p>
                </div>
                <div className="note-block">
                  <p className="muted-label">Следующий шаг</p>
                  <p>
                    {preflightSummary.failed > 0
                      ? "Сначала разберите блокирующие проверки, потом повторяйте запуск."
                      : selectedRun.status === "running"
                        ? "Следите за логом и дождитесь результата задачи."
                        : "Если результат вас устраивает, переходите к артефактам или следующей задаче."}
                  </p>
                </div>
              </div>

              <details className="artifact-details technical-details">
                <summary>Открыть технические детали запуска</summary>
                <div className="runtime-grid">
                  <div className="note-block">
                    <p className="muted-label">Рабочая копия задачи</p>
                    <p className="path-text">{renderRuntimeValue(activeRunRuntime.workspace.workspace_path)}</p>
                    <p className="hint-text">
                      Корень проекта: {renderRuntimeValue(activeRunRuntime.workspace.root_path)}
                    </p>
                  </div>
                  <div className="note-block">
                    <p className="muted-label">Среда исполнения</p>
                    <p>
                      {renderRuntimeValue(activeRunRuntime.environment.runtime_kind)} ·{" "}
                      {renderRuntimeValue(activeRunRuntime.environment.runtime_status)}
                    </p>
                    <p className="hint-text">
                      Сеть: {renderRuntimeValue(activeRunRuntime.environment.network_mode)} · Образ:{" "}
                      {renderRuntimeValue(activeRunRuntime.environment.base_image)}
                    </p>
                  </div>
                  <div className="note-block">
                    <p className="muted-label">Политика безопасности</p>
                    <p>
                      {renderRuntimeValue(activeRunRuntime.run_policy.policy_level)} ·{" "}
                      {renderRuntimeValue(activeRunRuntime.run_policy.default_risk_level)}
                    </p>
                    <p className="hint-text">
                      Установка пакетов:{" "}
                      {renderRuntimeValue(activeRunRuntime.run_policy.package_installation_mode)}
                    </p>
                  </div>
                  <div className="note-block">
                    <p className="muted-label">Подключённые папки</p>
                    <p>{renderRuntimeValue(activeRunRuntime.environment.mounts)}</p>
                  </div>
                </div>
              </details>
            </>
          )}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Проверка перед запуском</p>
              <h2>Что именно проверила система</h2>
            </div>
          </header>
          {!selectedRun ? (
            <p className="empty-state">Сначала выберите запуск.</p>
          ) : preflightStatus === "loading" || !activeRunPreflight ? (
            <p className="empty-state">Загружаю проверку окружения...</p>
          ) : (
            <>
              <div className="note-block">
                <p>{activeRunPreflight.summary}</p>
              </div>
              {activeRunPreflight.checks?.length > 0 ? (
                <ul className="runs-check-list">
                  {activeRunPreflight.checks.map((check) => (
                    <li key={check.key} className={`runs-check runs-check-${check.status}`}>
                      <strong>{labelForCheck(check.key)}</strong>
                      <span>{check.message}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">Проверок пока нет.</p>
              )}
            </>
          )}
        </article>
      </section>
    </>
  );
}
