export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_KEY = import.meta.env.VITE_API_KEY || "";
const API_REQUEST_TIMEOUT_MS = 10000;

export const defaultHealth = {
  status: "checking",
  service: "api",
};

export const TASK_STATUS_LABELS = {
  planned: "Запланирована",
  ready: "Готова к запуску",
  running: "В работе",
  review: "На проверке",
  blocked: "Заблокирована",
  done: "Выполнена",
  failed: "С ошибкой",
  changes_requested: "Нужны доработки",
  cancelled: "Остановлена",
  timed_out: "Превышено время",
};

export const CRM_STATUS_LABELS = {
  previewed: "Готово к отправке",
  sent: "Отправлено",
  failed: "Ошибка",
};

export const REVIEW_STATUS_LABELS = {
  pending: "Ждёт проверки",
  approved: "Одобрено",
  family_case: "Семейный кейс",
  needs_correction: "Нужна корректировка",
  insufficient_data: "Не хватает данных",
  duplicate: "Похоже на дубль",
  rejected: "Отклонено",
  not_required: "Не требуется",
};

export const CALL_MATCH_STATUS_LABELS = {
  pending_match: "Нужно определить ученика",
  manual_review: "Ручная проверка",
  family_review: "Проверка по семье",
  duplicate_candidate: "Проверка на дубль",
  matched: "Ученик найден",
  linked: "Привязано",
  sent: "Отправлено в CRM",
};

export const CALL_PRIORITY_LABELS = {
  hot: "Срочно",
  warm: "Тёплый",
  cold: "Холодный",
};

export const CALL_PROCESSING_STATUS_LABELS = {
  pending: "Ожидает анализа",
  running: "Анализируется",
  done: "Готово",
  failed: "Ошибка анализа",
};

export const APPROVAL_STATUS_LABELS = {
  pending: "Ждёт решения",
  approved: "Одобрено",
  rejected: "Отклонено",
};

export const PROJECT_STATUS_LABELS = {
  draft: "Черновик",
  active: "Активен",
  paused: "Пауза",
  archived: "Архив",
};

export const STREAM_STATUS_LABELS = {
  idle: "Отключено",
  connecting: "Подключение",
  live: "Онлайн",
  offline: "Нет связи",
};

export const HEALTH_STATUS_LABELS = {
  checking: "Проверка",
  ok: "В норме",
  healthy: "В норме",
  unreachable: "Недоступно",
};

export const RISK_LEVEL_LABELS = {
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
};

export const AGENT_ROLE_LABELS = {
  Director: "Директор",
  director: "Директор",
  ProductManager: "Продакт-менеджер",
  Methodologist: "Методист",
  Architect: "Архитектор",
  FrontendEngineer: "Frontend-инженер",
  BackendEngineer: "Backend-инженер",
  QAReviewer: "Ревьюер QA",
  reviewer: "Ревьюер",
  DevOps: "DevOps",
  devops: "DevOps",
  Human: "Владелец",
  human: "Владелец",
  System: "Система",
  system: "Система",
};

export const AGENT_ROLE_BADGES = {
  Director: "DR",
  director: "DR",
  ProductManager: "PM",
  Methodologist: "ME",
  Architect: "AR",
  FrontendEngineer: "FE",
  BackendEngineer: "BE",
  QAReviewer: "QA",
  reviewer: "QA",
  DevOps: "DO",
  devops: "DO",
  Human: "HM",
  human: "HM",
  System: "SYS",
  system: "SYS",
};

export const AGENT_STATUS_LABELS = {
  idle: "Ожидает",
  planning: "Планирует",
  ready: "Готов",
  running: "В работе",
  reviewing: "Проверяет",
  blocked: "Заблокирован",
  done: "Завершил",
};

export const EVENT_LABELS = {
  project_created: "Проект создан",
  project_archived: "Проект перенесён в архив",
  project_restored: "Проект возвращён в работу",
  goal_planned: "Цель разобрана на план",
  task_graph_replaced: "План задач обновлён",
  task_created: "Задача создана",
  task_assigned: "Задача назначена",
  task_status_changed: "Статус задачи изменён",
  task_run_started: "Запуск задачи начат",
  task_completed: "Задача завершена",
  task_failed: "Ошибка выполнения задачи",
  task_blocked: "Задача заблокирована",
  task_execution_cancelled: "Запуск задачи отменён",
  task_execution_timed_out: "Превышено время выполнения",
  agent_status_changed: "Статус сотрудника изменён",
  task_container_ready: "Контейнер задачи готов",
  task_container_cleaned: "Контейнер задачи очищен",
  director_auto_dispatched: "Директор автозапустил задачу",
  director_auto_dispatch_blocked: "Автозапуск директора заблокирован",
  director_auto_handoff_required: "Директор передал задачу человеку",
  director_stale_run_recovered: "Директор восстановил зависший запуск",
  director_progress_update: "Отчёт директора о прогрессе",
  crm_preview_created: "Создано CRM-превью",
  crm_send_completed: "Отправка в AMO завершена",
  crm_send_failed: "Ошибка отправки в AMO",
  call_insight_ingested: "Инсайт по звонку сохранён",
};

export function labelFromMap(map, key, fallback = "Неизвестно") {
  if (!key) {
    return fallback;
  }
  return map[key] || key;
}

export function statusClass(value) {
  return String(value || "unknown").replaceAll("_", "-").toLowerCase();
}

export function reviewNeedsOperatorAction(reviewStatus) {
  return !["approved", "not_required", "", null, undefined].includes(reviewStatus);
}

export async function requestJson(path, options) {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), API_REQUEST_TIMEOUT_MS);
  const headers = {
    "Content-Type": "application/json",
    ...(options?.headers || {}),
  };
  if (API_KEY) {
    headers["X-API-Key"] = API_KEY;
  }
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers,
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`API не отвечает дольше ${Math.round(API_REQUEST_TIMEOUT_MS / 1000)} сек.`);
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }

  if (!response.ok) {
    let detail = await response.text();
    if (detail) {
      try {
        const parsed = JSON.parse(detail);
        if (typeof parsed?.detail === "string") {
          detail = parsed.detail;
        }
      } catch {
        // Keep original text when not JSON.
      }
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return response.json();
}

export function formatDate(value) {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString("ru-RU");
}

export function shortenText(value, max = 600) {
  if (!value) {
    return "";
  }
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max)}\n...`;
}

export function summarizeEventPayload(payload) {
  if (!payload || Object.keys(payload).length === 0) {
    return "Без деталей";
  }

  return Object.entries(payload)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
}

export function eventTitle(eventType) {
  if (!eventType) {
    return "Событие";
  }
  if (EVENT_LABELS[eventType]) {
    return EVENT_LABELS[eventType];
  }
  return eventType
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function displayAgentRole(role) {
  return labelFromMap(AGENT_ROLE_LABELS, role, role || "Не указана");
}

export function displayAgentStatus(statusValue) {
  return labelFromMap(AGENT_STATUS_LABELS, statusValue, statusValue || "Не указано");
}

export function displayAgentBadge(role) {
  const label = labelFromMap(AGENT_ROLE_BADGES, role, "");
  if (label) {
    return label;
  }
  const normalized = String(role || "AG").replace(/[^A-Za-zА-Яа-я0-9]/g, "");
  return normalized.slice(0, 2).toUpperCase() || "AG";
}

export function formatTaskStatus(statusValue) {
  return labelFromMap(TASK_STATUS_LABELS, statusValue, statusValue || "Неизвестно");
}

export function formatCrmStatus(statusValue) {
  return labelFromMap(CRM_STATUS_LABELS, statusValue, statusValue || "Неизвестно");
}

export function formatReviewStatus(statusValue) {
  return labelFromMap(REVIEW_STATUS_LABELS, statusValue, statusValue || "Неизвестно");
}

export function formatCallMatchStatus(statusValue) {
  return labelFromMap(
    CALL_MATCH_STATUS_LABELS,
    statusValue,
    statusValue ? String(statusValue).replaceAll("_", " ") : "Неизвестно",
  );
}

export function formatCallPriority(priorityValue) {
  return labelFromMap(CALL_PRIORITY_LABELS, priorityValue, priorityValue || "Не указано");
}

export function formatCallProcessingStatus(statusValue) {
  return labelFromMap(
    CALL_PROCESSING_STATUS_LABELS,
    statusValue,
    statusValue ? String(statusValue).replaceAll("_", " ") : "Неизвестно",
  );
}

export function collectBlockingPreflightChecks(preflight) {
  if (!preflight?.checks?.length) {
    return [];
  }
  return preflight.checks.filter((check) => check.status === "fail" && check.blocking);
}

export function isDateWithinWindow(value, windowValue) {
  if (!value || windowValue === "all") {
    return true;
  }

  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return false;
  }

  const now = Date.now();
  if (windowValue === "24h") {
    return now - timestamp <= 24 * 60 * 60 * 1000;
  }
  if (windowValue === "7d") {
    return now - timestamp <= 7 * 24 * 60 * 60 * 1000;
  }
  if (windowValue === "30d") {
    return now - timestamp <= 30 * 24 * 60 * 60 * 1000;
  }
  return true;
}

const TECHNICAL_PROJECT_PATTERNS = [
  /smoke/i,
  /probe/i,
  /audit/i,
  /demo/i,
  /mock/i,
  /retry/i,
  /sandbox/i,
  /\btest\b/i,
  /тест/i,
  /проверк/i,
];

export function isTechnicalProject(project) {
  if (!project) {
    return false;
  }
  const haystack = `${project.name || ""}`;
  return TECHNICAL_PROJECT_PATTERNS.some((pattern) => pattern.test(haystack));
}

export function inferEventScope(eventType) {
  if (!eventType) {
    return "office";
  }
  if (eventType.startsWith("crm_")) {
    return "crm";
  }
  if (eventType.startsWith("call_")) {
    return "calls";
  }
  if (
    eventType.startsWith("task_run") ||
    eventType.startsWith("task_execution") ||
    eventType.startsWith("task_container")
  ) {
    return "runtime";
  }
  if (eventType.startsWith("approval_")) {
    return "approvals";
  }
  if (
    eventType.startsWith("director_") ||
    eventType === "goal_planned" ||
    eventType === "task_graph_replaced"
  ) {
    return "director";
  }
  return "office";
}

export function matchesModuleKeywords(moduleDefinition, value) {
  if (!moduleDefinition?.keywords?.length || !value) {
    return false;
  }

  const normalized = String(value).toLowerCase();
  return moduleDefinition.keywords.some((keyword) => normalized.includes(keyword));
}
