import { NavLink } from "react-router-dom";
import { MODULE_STATUS_LABELS } from "../navigation";

const PROJECT_STATUS_LABELS = {
  draft: "Черновик",
  active: "Активен",
  paused: "Пауза",
  archived: "Архив",
};

function labelFromMap(map, key, fallback = "Неизвестно") {
  if (!key) {
    return fallback;
  }
  return map[key] || key;
}

function formatProjectOption(project) {
  const statusLabel = labelFromMap(PROJECT_STATUS_LABELS, project.status, project.status || "Проект");
  return `${project.name} · ${statusLabel}`;
}

export default function OfficeToolbar({
  hiddenProjectsCount,
  moduleItems,
  officeItems,
  onRefreshProjects,
  onSelectProject,
  onToggleShowArchivedProjects,
  onToggleShowTechnicalProjects,
  projects,
  projectsRefreshing,
  selectedProject,
  selectedProjectId,
  showArchivedProjects,
  showTechnicalProjects,
}) {
  return (
    <header className="topbar">
      <div>
        <p className="topbar-kicker">Локальная многоагентная система</p>
        <h1>AI Офис</h1>
      </div>
      <div className="topbar-right">
        <div className="nav-sections">
          <section className="nav-section">
            <p className="nav-section-title">Офис</p>
            <nav className="main-nav" aria-label="Офис">
              {officeItems.map((item) => (
                <NavLink
                  key={item.id}
                  to={item.path}
                  className={({ isActive }) => (isActive ? "nav-item nav-item-active" : "nav-item")}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </section>

          <section className="nav-section">
            <p className="nav-section-title">Модули</p>
            <nav className="main-nav" aria-label="Модули">
              {moduleItems.map((item) => (
                <NavLink
                  key={item.id}
                  to={item.path}
                  className={({ isActive }) => (isActive ? "nav-item nav-item-active" : "nav-item")}
                >
                  <span>{item.label}</span>
                  {item.status !== "active" ? (
                    <span className="nav-item-badge">{MODULE_STATUS_LABELS[item.status] || item.status}</span>
                  ) : null}
                </NavLink>
              ))}
            </nav>
          </section>
        </div>

        <div className="project-switcher">
          <label htmlFor="project-select">Рабочий проект</label>
          <select
            id="project-select"
            value={selectedProjectId}
            onChange={(event) => onSelectProject(event.target.value)}
            disabled={projects.length === 0}
          >
            {projects.length === 0 ? <option value="">Нет проектов</option> : null}
            {projects.length > 0 ? <option value="">Выберите проект вручную</option> : null}
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {formatProjectOption(project)}
              </option>
            ))}
          </select>
          <p className="project-switcher-hint">
            Здесь показаны локальные проекты из текущей базы AI Office. По умолчанию архив и технические прогоны скрыты.
          </p>
          <div className="project-switcher-toggles">
            <label className="checkbox-inline">
              <input
                checked={showArchivedProjects}
                onChange={(event) => onToggleShowArchivedProjects(event.target.checked)}
                type="checkbox"
              />
              <span>Показать архив</span>
            </label>
            <label className="checkbox-inline">
              <input
                checked={showTechnicalProjects}
                onChange={(event) => onToggleShowTechnicalProjects(event.target.checked)}
                type="checkbox"
              />
              <span>Показать технические</span>
            </label>
          </div>
          {hiddenProjectsCount > 0 ? (
            <p className="project-switcher-hint">
              Сейчас скрыто проектов: {hiddenProjectsCount}. Включите фильтры выше, если нужен архив или старые учебные прогоны.
            </p>
          ) : null}
          {projects.length > 1 && !selectedProjectId ? (
            <p className="project-switcher-warning">
              Проект не выбран. Это безопаснее, чем автоматически открывать старый тестовый проект.
            </p>
          ) : null}
          {selectedProject ? (
            <div className="project-switcher-meta">
              <strong>{selectedProject.name}</strong>
              <small>
                {selectedProject.description || "Описание не задано."}
              </small>
            </div>
          ) : null}
          <button className="button-ghost button-small" onClick={onRefreshProjects} type="button">
            {projectsRefreshing ? "Обновляю..." : "Обновить проекты"}
          </button>
        </div>
      </div>
    </header>
  );
}
