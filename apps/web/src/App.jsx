import { useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import OfficeToolbar from "./components/OfficeToolbar";
import { MODULE_REGISTRY, MODULE_NAV_ITEMS, OFFICE_NAV_ITEMS } from "./navigation";
import {
  API_BASE_URL,
  APPROVAL_STATUS_LABELS,
  AGENT_ROLE_LABELS,
  CALL_MATCH_STATUS_LABELS,
  CALL_PRIORITY_LABELS,
  CALL_PROCESSING_STATUS_LABELS,
  CRM_STATUS_LABELS,
  EVENT_LABELS,
  HEALTH_STATUS_LABELS,
  PROJECT_STATUS_LABELS,
  RISK_LEVEL_LABELS,
  STREAM_STATUS_LABELS,
  collectBlockingPreflightChecks,
  defaultHealth,
  displayAgentBadge,
  displayAgentRole,
  displayAgentStatus,
  eventTitle,
  formatCallMatchStatus,
  formatCallPriority,
  formatCallProcessingStatus,
  formatCrmStatus,
  formatDate,
  formatReviewStatus,
  formatTaskStatus,
  inferEventScope,
  isDateWithinWindow,
  isTechnicalProject,
  labelFromMap,
  matchesModuleKeywords,
  requestJson,
  reviewNeedsOperatorAction,
  shortenText,
  statusClass,
  summarizeEventPayload,
} from "./appShared";
import ApprovalsPage from "./pages/ApprovalsPage";
import ArtifactsPage from "./pages/ArtifactsPage";
import CallsPage from "./pages/CallsPage";
import CrmPage from "./pages/CrmPage";
import DirectorPage from "./pages/DirectorPage";
import EventsPage from "./pages/EventsPage";
import RunsPage from "./pages/RunsPage";
import TeamPage from "./pages/TeamPage";
export {
  API_BASE_URL,
  APPROVAL_STATUS_LABELS,
  AGENT_ROLE_LABELS,
  CALL_MATCH_STATUS_LABELS,
  CALL_PRIORITY_LABELS,
  CALL_PROCESSING_STATUS_LABELS,
  CRM_STATUS_LABELS,
  EVENT_LABELS,
  HEALTH_STATUS_LABELS,
  PROJECT_STATUS_LABELS,
  RISK_LEVEL_LABELS,
  STREAM_STATUS_LABELS,
  collectBlockingPreflightChecks,
  displayAgentBadge,
  displayAgentRole,
  displayAgentStatus,
  eventTitle,
  formatCallMatchStatus,
  formatCallPriority,
  formatCallProcessingStatus,
  formatCrmStatus,
  formatDate,
  formatReviewStatus,
  formatTaskStatus,
  inferEventScope,
  isDateWithinWindow,
  isTechnicalProject,
  labelFromMap,
  requestJson,
  shortenText,
  statusClass,
  summarizeEventPayload,
} from "./appShared";

function App() {
  const navigate = useNavigate();
  const refreshTimerRef = useRef(null);
  const streamReconnectTimerRef = useRef(null);

  const [health, setHealth] = useState(defaultHealth);
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedProject, setSelectedProject] = useState(null);
  const [agents, setAgents] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [messages, setMessages] = useState([]);
  const [events, setEvents] = useState([]);
  const [projectRuns, setProjectRuns] = useState([]);
  const [crmPreviews, setCrmPreviews] = useState([]);
  const [callInsights, setCallInsights] = useState([]);

  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedTaskRuntime, setSelectedTaskRuntime] = useState(null);
  const [selectedTaskPreflight, setSelectedTaskPreflight] = useState(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runLogs, setRunLogs] = useState(null);
  const [selectedCrmPreviewId, setSelectedCrmPreviewId] = useState("");
  const [selectedCallInsightId, setSelectedCallInsightId] = useState("");

  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [goalText, setGoalText] = useState("");
  const [planSummary, setPlanSummary] = useState("");
  const [crmStudentId, setCrmStudentId] = useState("");
  const [crmLookupMode, setCrmLookupMode] = useState("auto");
  const [crmSelectedFields, setCrmSelectedFields] = useState([]);
  const [crmFieldValues, setCrmFieldValues] = useState({});
  const [crmMessage, setCrmMessage] = useState("");
  const [callMessage, setCallMessage] = useState("");

  const [busy, setBusy] = useState(false);
  const [projectsRefreshing, setProjectsRefreshing] = useState(false);
  const [projectActionBusy, setProjectActionBusy] = useState("");
  const [executionBusy, setExecutionBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [approvalActionBusy, setApprovalActionBusy] = useState("");
  const [cancelBusy, setCancelBusy] = useState(false);
  const [crmPreviewBusy, setCrmPreviewBusy] = useState(false);
  const [crmReviewBusy, setCrmReviewBusy] = useState("");
  const [crmSendBusy, setCrmSendBusy] = useState(false);
  const [callReviewBusy, setCallReviewBusy] = useState("");
  const [callSendBusy, setCallSendBusy] = useState(false);
  const [streamStatus, setStreamStatus] = useState("idle");
  const [runtimeStatus, setRuntimeStatus] = useState("idle");
  const [preflightStatus, setPreflightStatus] = useState("idle");
  const [error, setError] = useState("");

  const [approvalsFilter, setApprovalsFilter] = useState("pending");
  const [artifactWindowFilter, setArtifactWindowFilter] = useState("all");
  const [eventWindowFilter, setEventWindowFilter] = useState("all");
  const [eventScopeFilter, setEventScopeFilter] = useState("all");
  const [showArchivedProjects, setShowArchivedProjects] = useState(false);
  const [showTechnicalProjects, setShowTechnicalProjects] = useState(false);

  const selectedTask = tasks.find((task) => task.id === selectedTaskId) || tasks[0] || null;
  const selectedProjectRun = projectRuns.find((run) => run.id === selectedRunId) || null;
  const selectedRun =
    selectedProjectRun ||
    selectedTaskRuntime?.runs?.find((run) => run.id === selectedRunId) ||
    selectedTaskRuntime?.runs?.[0] ||
    null;
  const selectedRunTask = tasks.find((task) => task.id === selectedRun?.task_id) || selectedTask || null;
  const selectedRunRuntimeMatchesTask =
    Boolean(selectedRun?.task_id) && selectedTaskRuntime?.workspace?.task_id === selectedRun?.task_id;
  const activeRunRuntime = selectedRunRuntimeMatchesTask ? selectedTaskRuntime : null;
  const activeRunPreflight = selectedRunRuntimeMatchesTask ? selectedTaskPreflight : null;
  const runningTaskRun = selectedTaskRuntime?.runs?.find((run) => run.status === "running") || null;
  const selectedCrmPreview =
    crmPreviews.find((preview) => preview.id === selectedCrmPreviewId) ||
    crmPreviews[0] ||
    null;
  const selectedCallInsight =
    callInsights.find((insight) => insight.id === selectedCallInsightId) ||
    callInsights[0] ||
    null;
  const preflightBlockingChecks = collectBlockingPreflightChecks(selectedTaskPreflight);

  const pendingApprovals = approvals.filter((approval) => approval.status === "pending");
  const runningTasksCount = tasks.filter((task) => task.status === "running").length;
  const readyTasksCount = tasks.filter((task) => task.status === "ready").length;
  const doneTasksCount = tasks.filter((task) => task.status === "done").length;
  const blockedTasksCount = tasks.filter((task) => task.status === "blocked").length;
  const reviewTasksCount = tasks.filter((task) => task.status === "review").length;
  const totalTasksCount = tasks.length;

  const latestEvent = events[0] || null;
  const directorMessages = messages.filter((message) => message.role === "director");
  const latestDirectorMessage =
    directorMessages.length > 0 ? directorMessages[directorMessages.length - 1] : null;
  const recentDirectorMessages = [...directorMessages].slice(-5).reverse();
  const sortedAgents = [...agents].sort((left, right) => left.name.localeCompare(right.name));
  const directorAgent =
    sortedAgents.find((agent) => agent.role === "Director" || agent.role === "director") || null;
  const officeAgents = sortedAgents
    .filter((agent) => agent.id !== directorAgent?.id)
    .slice(0, 7);
  const busyAgentsCount = sortedAgents.filter((agent) =>
    ["running", "reviewing", "planning", "ready"].includes(agent.status),
  ).length;
  const runningAgentsCount = sortedAgents.filter((agent) => agent.status === "running").length;
  const reviewingAgentsCount = sortedAgents.filter((agent) => agent.status === "reviewing").length;
  const blockedAgentsCount = sortedAgents.filter((agent) => agent.status === "blocked").length;
  const idleAgentsCount = sortedAgents.filter((agent) => agent.status === "idle").length;
  const completionPercent = totalTasksCount > 0 ? Math.round((doneTasksCount / totalTasksCount) * 100) : 0;
  const runningRunsCount = projectRuns.filter((run) => run.status === "running").length;
  const reviewRunsCount = projectRuns.filter((run) => run.status === "review").length;
  const failedRunsCount = projectRuns.filter((run) => ["failed", "timed_out"].includes(run.status)).length;
  const cancelledRunsCount = projectRuns.filter((run) => run.status === "cancelled").length;
  const readyTasks = tasks.filter((task) => task.status === "ready").slice(0, 4);
  const blockedTasks = tasks.filter((task) => task.status === "blocked").slice(0, 4);
  const focusTasks = tasks
    .filter((task) =>
      ["ready", "running", "review", "blocked", "failed", "changes_requested"].includes(task.status),
    )
    .slice(0, 6);
  const crmSentCount = crmPreviews.filter((preview) => preview.status === "sent").length;
  const crmFailedCount = crmPreviews.filter((preview) => preview.status === "failed").length;
  const crmReviewQueueCount = crmPreviews.filter((preview) =>
    reviewNeedsOperatorAction(preview.review_status),
  ).length;
  const crmApprovedCount = crmPreviews.filter((preview) => preview.review_status === "approved").length;
  const callInsightsCount = callInsights.length;
  const callsPendingMatchCount = callInsights.filter(
    (insight) => insight.match_status === "pending_match",
  ).length;
  const callsManualReviewCount = callInsights.filter((insight) =>
    reviewNeedsOperatorAction(insight.review_status),
  ).length;
  const callsMatchedCount = callInsights.filter(
    (insight) =>
      insight.matched_amo_contact_id !== null ||
      ["matched", "linked", "sent"].includes(insight.match_status),
  ).length;
  const callsHotCount = callInsights.filter(
    (insight) => insight.lead_priority === "hot" || Number(insight.follow_up_score || 0) >= 75,
  ).length;
  const callsApprovedCount = callInsights.filter((insight) => insight.review_status === "approved").length;
  const callsModuleDefinition = MODULE_REGISTRY.find((moduleDefinition) => moduleDefinition.id === "calls");
  const callsFocusTasks = tasks
    .filter((task) =>
      matchesModuleKeywords(
        callsModuleDefinition,
        `${task.title || ""} ${task.brief || ""} ${task.task_key || ""}`,
      ),
    )
    .slice(0, 6);
  const callsArtifacts = artifacts
    .filter((artifact) =>
      matchesModuleKeywords(
        callsModuleDefinition,
        `${artifact.title || ""} ${artifact.kind || ""} ${artifact.content || ""}`,
      ),
    )
    .slice(0, 6);
  const callsModuleState = !selectedProject
    ? {
        status: "idle",
        label: "Нет проекта",
        summary: "Сначала нужен проект и цель директора, иначе модуль не к чему привязать.",
        nextStep: "Создать проект и описать, как должны анализироваться звонки и куда писать результаты.",
      }
    : callInsightsCount > 0
      ? {
          status: callsManualReviewCount > 0 ? "review" : "running",
          label: callsManualReviewCount > 0 ? "Нужна проверка" : "Поток работает",
          summary:
            callsManualReviewCount > 0
              ? `В модуле уже есть реальные звонки. ${callsManualReviewCount} из них требуют ручного решения по сопоставлению ученика или качеству разбора.`
              : `В модуле уже есть реальные звонки: ${callInsightsCount} инсайтов загружено, ${callsPendingMatchCount} ещё ждут определения ученика.`,
          nextStep:
            callsManualReviewCount > 0
              ? "Собрать отдельную очередь проверки и дать владельцу быстрый сценарий ручного выбора ученика."
              : "Подключить следующий слой: семейное сопоставление и контролируемую запись результатов в AMO.",
        }
      : callsFocusTasks.length > 0 || callsArtifacts.length > 0
      ? {
          status: "planned",
          label: "Контур собран",
          summary:
            "Архитектура и артефакты модуля уже есть, но реальные результаты анализа звонков ещё не поступают в офис.",
          nextStep: "Запустить локальный экспорт результатов анализа звонков и убедиться, что первые звонки реально появляются в модуле.",
        }
      : {
          status: "planned",
          label: "Готовится",
          summary:
            "Модуль вынесен как отдельный рабочий режим, но боевой поток обработки звонков ещё не подключен к проекту.",
          nextStep:
            "Поставить директору цель на локальную загрузку звонков, расшифровку, разбор семейных кейсов и запись сигналов в AMO.",
        };

  const filteredApprovals = approvals
    .filter((approval) => approvalsFilter === "all" || approval.status === approvalsFilter)
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime());

  const filteredArtifacts = artifacts
    .filter((artifact) => isDateWithinWindow(artifact.created_at, artifactWindowFilter))
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime());
  const filteredEvents = events
    .filter((event) => isDateWithinWindow(event.created_at, eventWindowFilter))
    .filter((event) => eventScopeFilter === "all" || inferEventScope(event.event_type) === eventScopeFilter)
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime());
  const visibleProjects = projects.filter((project) => {
    if (!showArchivedProjects && project.status === "archived") {
      return false;
    }
    if (!showTechnicalProjects && isTechnicalProject(project)) {
      return false;
    }
    return true;
  });
  const toolbarProjects =
    selectedProject && !visibleProjects.some((project) => project.id === selectedProject.id)
      ? [selectedProject, ...visibleProjects]
      : visibleProjects;
  const hiddenProjectsCount = Math.max(0, projects.length - visibleProjects.length);

  let nextAction = {
    title: "Рабочее место готово",
    description: "Задачи запущены. Проверяйте прогресс и подтверждайте рискованные действия.",
    buttonLabel: "Открыть одобрения",
    buttonAction: () => navigate("/approvals"),
  };

  if (!selectedProject) {
    nextAction = {
      title: "Создайте первый проект",
      description: "Начните с названия проекта. Затем отправьте цель директору.",
      buttonLabel: null,
      buttonAction: null,
    };
  } else if (tasks.length === 0) {
    nextAction = {
      title: "Отправьте цель директору",
      description: "После цели директор сам создаст план задач.",
      buttonLabel: null,
      buttonAction: null,
    };
  } else if (pendingApprovals.length > 0) {
    nextAction = {
      title: "Есть действия, которые ждут решения",
      description: `Сейчас ждут одобрения: ${pendingApprovals.length}. Без этого часть задач не продолжится.`,
      buttonLabel: "Перейти к одобрениям",
      buttonAction: () => navigate("/approvals"),
    };
  } else {
    const firstReadyTask = tasks.find((task) => task.status === "ready");
    if (firstReadyTask) {
      nextAction = {
        title: "Можно запускать следующую задачу",
        description: `${firstReadyTask.title} (${displayAgentRole(firstReadyTask.assigned_agent_role)})`,
        buttonLabel: "Открыть задачу",
        buttonAction: () => {
          setSelectedTaskId(firstReadyTask.id);
          navigate("/runs");
        },
      };
    } else if (runningTasksCount > 0) {
      nextAction = {
        title: "Задачи выполняются",
        description: "Сейчас главное следить за логами и блокерами.",
        buttonLabel: "Открыть запуски",
        buttonAction: () => navigate("/runs"),
      };
    }
  }

  async function refreshProjects(preferredProjectId = "") {
    const projectList = await requestJson("/projects");
    setProjects(projectList);

    if (projectList.length === 0) {
      setSelectedProjectId("");
      return "";
    }

    if (preferredProjectId && projectList.some((project) => project.id === preferredProjectId)) {
      setSelectedProjectId(preferredProjectId);
      return preferredProjectId;
    }

    if (selectedProjectId && projectList.some((project) => project.id === selectedProjectId)) {
      return selectedProjectId;
    }

    if (projectList.length === 1) {
      setSelectedProjectId(projectList[0].id);
      return projectList[0].id;
    }

    setSelectedProjectId("");
    return "";
  }

  async function handleRefreshProjects() {
    setProjectsRefreshing(true);
    setError("");
    try {
      const projectId = await refreshProjects(selectedProjectId);
      if (projectId) {
        await loadProjectWorkspace(projectId);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось обновить список проектов");
    } finally {
      setProjectsRefreshing(false);
    }
  }

  async function handleArchiveProject() {
    if (!selectedProjectId) {
      return;
    }
    setProjectActionBusy("archive");
    setError("");
    try {
      const response = await requestJson(`/projects/${selectedProjectId}/archive`, {
        method: "POST",
      });
      setPlanSummary(response.summary || "");
      await refreshProjects(selectedProjectId);
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось архивировать проект");
    } finally {
      setProjectActionBusy("");
    }
  }

  async function handleRestoreProject() {
    if (!selectedProjectId) {
      return;
    }
    setProjectActionBusy("restore");
    setError("");
    try {
      const response = await requestJson(`/projects/${selectedProjectId}/restore`, {
        method: "POST",
      });
      setPlanSummary(response.summary || "");
      await refreshProjects(selectedProjectId);
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось вернуть проект в работу");
    } finally {
      setProjectActionBusy("");
    }
  }

  async function loadProjectWorkspace(projectId) {
    if (!projectId) {
      setSelectedProject(null);
      setAgents([]);
      setTasks([]);
      setApprovals([]);
      setArtifacts([]);
      setMessages([]);
      setEvents([]);
      setProjectRuns([]);
      setCrmPreviews([]);
      setCallInsights([]);
      setSelectedTaskId("");
      setSelectedTaskRuntime(null);
      setSelectedTaskPreflight(null);
      setSelectedRunId("");
      setRunLogs(null);
      setSelectedCrmPreviewId("");
      setSelectedCallInsightId("");
      setCrmSelectedFields([]);
      setCrmFieldValues({});
      setCrmMessage("");
      setCallMessage("");
      return;
    }

    try {
      const [
        project,
        projectAgents,
        projectTasks,
        projectApprovals,
        projectArtifacts,
        projectMessages,
        projectEvents,
        projectTaskRuns,
        projectCrmPreviews,
        projectCallInsights,
      ] = await Promise.all([
        requestJson(`/projects/${projectId}`),
        requestJson(`/projects/${projectId}/agents`),
        requestJson(`/projects/${projectId}/tasks`),
        requestJson(`/projects/${projectId}/approvals`),
        requestJson(`/projects/${projectId}/artifacts`),
        requestJson(`/projects/${projectId}/messages`),
        requestJson(`/projects/${projectId}/events`),
        requestJson(`/projects/${projectId}/runs`),
        requestJson(`/projects/${projectId}/crm/previews`),
        requestJson(`/projects/${projectId}/calls/insights`),
      ]);

      setSelectedProject(project);
      setAgents(projectAgents);
      setTasks(projectTasks);
      setApprovals(projectApprovals);
      setArtifacts(projectArtifacts);
      setMessages(projectMessages);
      setEvents(projectEvents);
      setProjectRuns(projectTaskRuns);
      setCrmPreviews(projectCrmPreviews);
      setCallInsights(projectCallInsights);
      setSelectedTaskId((current) => {
        if (current && projectTasks.some((task) => task.id === current)) {
          return current;
        }
        return projectTasks[0]?.id || "";
      });
      setSelectedCrmPreviewId((current) => {
        if (current && projectCrmPreviews.some((preview) => preview.id === current)) {
          return current;
        }
        return projectCrmPreviews[0]?.id || "";
      });
      setSelectedCallInsightId((current) => {
        if (current && projectCallInsights.some((insight) => insight.id === current)) {
          return current;
        }
        return projectCallInsights[0]?.id || "";
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось загрузить проект");
    }
  }

  async function loadTaskContext(projectId, taskId) {
    if (!projectId || !taskId) {
      setSelectedTaskRuntime(null);
      setSelectedTaskPreflight(null);
      setSelectedRunId("");
      setRunLogs(null);
      setRuntimeStatus("idle");
      setPreflightStatus("idle");
      return;
    }

    setRuntimeStatus("loading");
    setPreflightStatus("loading");

    try {
      const [runtime, preflight] = await Promise.all([
        requestJson(`/projects/${projectId}/tasks/${taskId}/runtime`),
        requestJson(`/projects/${projectId}/tasks/${taskId}/preflight`),
      ]);
      setSelectedTaskRuntime(runtime);
      setRuntimeStatus("ready");
      setSelectedTaskPreflight(preflight);
      setPreflightStatus("ready");
    } catch (nextError) {
      setRuntimeStatus("error");
      setPreflightStatus("error");
      setError(nextError instanceof Error ? nextError.message : "Не удалось загрузить контекст задачи");
    }
  }

  async function refreshTaskPreflight(projectId, taskId) {
    setPreflightStatus("loading");
    const preflight = await requestJson(`/projects/${projectId}/tasks/${taskId}/preflight`);
    setSelectedTaskPreflight(preflight);
    setPreflightStatus("ready");
    return preflight;
  }

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        const [healthData, projectsData] = await Promise.all([
          requestJson("/health"),
          requestJson("/projects"),
        ]);
        if (cancelled) {
          return;
        }
        setHealth(healthData);
        setProjects(projectsData);
        setSelectedProjectId((current) => {
          if (projectsData.length === 1) {
            return projectsData[0].id;
          }
          if (current && projectsData.some((project) => project.id === current)) {
            return current;
          }
          return "";
        });
      } catch (nextError) {
        if (!cancelled) {
          setHealth({
            status: "unreachable",
            service: "api",
            error: nextError instanceof Error ? nextError.message : "Unknown error",
          });
          setError(nextError instanceof Error ? nextError.message : "Не удалось подключиться к API");
        }
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    loadProjectWorkspace(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    loadTaskContext(selectedProjectId, selectedTaskId);
  }, [selectedProjectId, selectedTaskId]);

  useEffect(() => {
    if (projectRuns.length === 0) {
      setSelectedRunId("");
      return;
    }

    setSelectedRunId((current) => {
      if (current && projectRuns.some((run) => run.id === current)) {
        return current;
      }
      return projectRuns[0].id;
    });
  }, [projectRuns]);

  useEffect(() => {
    if (!selectedTaskRuntime?.runs?.length) {
      if (projectRuns.length === 0) {
        setSelectedRunId("");
        setRunLogs(null);
      }
      return;
    }

    setSelectedRunId((current) => {
      if (
        current &&
        (selectedTaskRuntime.runs.some((run) => run.id === current) ||
          projectRuns.some((run) => run.id === current))
      ) {
        return current;
      }
      return selectedTaskRuntime.runs[0].id;
    });
  }, [projectRuns, selectedTaskRuntime]);

  useEffect(() => {
    if (!selectedCrmPreview) {
      setCrmSelectedFields([]);
      setCrmFieldValues({});
      return;
    }

    const payload = selectedCrmPreview.amo_field_payload || {};
    const keys = Object.keys(payload);
    const initialValues = {};
    keys.forEach((key) => {
      const rawValue = payload[key];
      if (rawValue === null || rawValue === undefined) {
        initialValues[key] = "";
        return;
      }
      initialValues[key] = typeof rawValue === "string" ? rawValue : String(rawValue);
    });
    setCrmSelectedFields(keys);
    setCrmFieldValues(initialValues);
  }, [selectedCrmPreview?.id]);

  useEffect(() => {
    let cancelled = false;
    let intervalId = null;

    async function loadRunLogs() {
      if (!selectedRunId) {
        setRunLogs(null);
        return;
      }
      try {
        const logs = await requestJson(`/task-runs/${selectedRunId}/logs`);
        if (!cancelled) {
          setRunLogs(logs);
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : "Не удалось загрузить логи запуска");
        }
      }
    }

    loadRunLogs();

    if (selectedRun?.status === "running") {
      intervalId = window.setInterval(loadRunLogs, 1000);
    }

    return () => {
      cancelled = true;
      if (intervalId) {
        window.clearInterval(intervalId);
      }
    };
  }, [selectedRunId, selectedRun?.status]);

  useEffect(() => {
    if (!selectedProjectId) {
      setStreamStatus("idle");
      return undefined;
    }

    let cancelled = false;
    let eventSource = null;

    const clearReconnectTimer = () => {
      if (streamReconnectTimerRef.current) {
        window.clearTimeout(streamReconnectTimerRef.current);
        streamReconnectTimerRef.current = null;
      }
    };

    const connectStream = async () => {
      setStreamStatus("connecting");
      clearReconnectTimer();

      try {
        const tokenPayload = await requestJson(`/projects/${selectedProjectId}/stream-token`, {
          method: "POST",
        });

        if (cancelled) {
          return;
        }

        eventSource = new EventSource(
          `${API_BASE_URL}/projects/${selectedProjectId}/events/stream?stream_token=${encodeURIComponent(
            tokenPayload.token,
          )}`,
        );

        eventSource.onopen = () => {
          if (!cancelled) {
            setStreamStatus("live");
          }
        };

        eventSource.addEventListener("project_event", () => {
          if (cancelled) {
            return;
          }
          setStreamStatus("live");
          if (refreshTimerRef.current) {
            window.clearTimeout(refreshTimerRef.current);
          }
          refreshTimerRef.current = window.setTimeout(() => {
            loadProjectWorkspace(selectedProjectId);
          }, 200);
        });

        eventSource.onerror = () => {
          if (cancelled) {
            return;
          }
          setStreamStatus("offline");
          if (eventSource) {
            eventSource.close();
            eventSource = null;
          }
          clearReconnectTimer();
          streamReconnectTimerRef.current = window.setTimeout(() => {
            connectStream();
          }, 1600);
        };
      } catch {
        if (cancelled) {
          return;
        }
        setStreamStatus("offline");
        clearReconnectTimer();
        streamReconnectTimerRef.current = window.setTimeout(() => {
          connectStream();
        }, 2200);
      }
    };

    connectStream();

    return () => {
      cancelled = true;
      clearReconnectTimer();
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [selectedProjectId]);

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) {
        window.clearTimeout(refreshTimerRef.current);
      }
      if (streamReconnectTimerRef.current) {
        window.clearTimeout(streamReconnectTimerRef.current);
      }
    };
  }, []);

  async function handleCreateProject(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const project = await requestJson("/projects", {
        method: "POST",
        body: JSON.stringify({
          name: createName,
          description: createDescription || null,
        }),
      });
      setCreateName("");
      setCreateDescription("");
      setPlanSummary("Проект создан.");
      await refreshProjects(project.id);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось создать проект");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitGoal(event) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }

    setBusy(true);
    setError("");

    try {
      const result = await requestJson(`/projects/${selectedProjectId}/goal`, {
        method: "POST",
        body: JSON.stringify({ goal_text: goalText }),
      });

      setSelectedProject(result.project);
      setTasks(result.created_tasks);
      setSelectedTaskId(result.created_tasks[0]?.id || "");
      setPlanSummary(result.summary || "План обновлён.");
      setGoalText("");
      await loadProjectWorkspace(selectedProjectId);
      await refreshProjects(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось отправить цель");
    } finally {
      setBusy(false);
    }
  }

  async function handleAdvanceDirector() {
    if (!selectedProjectId) {
      return;
    }

    setExecutionBusy(true);
    setError("");

    try {
      const response = await requestJson(`/projects/${selectedProjectId}/director/advance`, {
        method: "POST",
      });
      setPlanSummary(response.summary || "Директор проверил очередь задач.");
      if (response.dispatched_task_id) {
        setSelectedTaskId(response.dispatched_task_id);
      }
      if (response.dispatched_run_id) {
        setSelectedRunId(response.dispatched_run_id);
      }
      const taskToRefresh = response.dispatched_task_id || selectedTask?.id;
      if (taskToRefresh) {
        await loadTaskContext(selectedProjectId, taskToRefresh);
      }
      await loadProjectWorkspace(selectedProjectId);
      await refreshProjects(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось обновить очередь директора");
    } finally {
      setExecutionBusy(false);
    }
  }

  async function handleTaskAction(action) {
    if (!selectedProjectId || !selectedTask) {
      return;
    }

    setActionBusy(action);
    setError("");

    try {
      const response = await requestJson(
        `/projects/${selectedProjectId}/tasks/${selectedTask.id}/actions`,
        {
          method: "POST",
          body: JSON.stringify({
            action,
            reason: action === "block" ? "Заблокировано вручную из интерфейса." : null,
          }),
        },
      );
      setPlanSummary(response.summary || "Статус задачи обновлён.");
      await loadProjectWorkspace(selectedProjectId);
      await refreshProjects(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось изменить статус задачи");
    } finally {
      setActionBusy("");
    }
  }

  async function handleCancelRun() {
    if (!selectedProjectId || !selectedTask) {
      return;
    }

    const runToCancel = runningTaskRun?.id || selectedRunId;
    if (!runToCancel) {
      return;
    }

    setCancelBusy(true);
    setError("");

    try {
      const response = await requestJson(`/task-runs/${runToCancel}/cancel`, {
        method: "POST",
        body: JSON.stringify({
          actor: "director",
          reason: "Отмена из интерфейса.",
        }),
      });
      setPlanSummary(response.summary || "Запуск отменён.");
      await loadTaskContext(selectedProjectId, selectedTask.id);
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось отменить запуск");
    } finally {
      setCancelBusy(false);
    }
  }

  async function handleResolveApproval(approvalId, outcome) {
    if (!selectedProjectId) {
      return;
    }

    setApprovalActionBusy(`${approvalId}:${outcome}`);
    setError("");

    try {
      const response = await requestJson(`/projects/${selectedProjectId}/approvals/${approvalId}/resolve`, {
        method: "POST",
        body: JSON.stringify({
          outcome,
          summary:
            outcome === "approved"
              ? "Одобрено владельцем через интерфейс."
              : "Отклонено владельцем через интерфейс.",
        }),
      });
      setPlanSummary(response.summary || "Решение по одобрению сохранено.");
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось обработать одобрение");
    } finally {
      setApprovalActionBusy("");
    }
  }

  async function handleCreateCrmPreview(event) {
    event.preventDefault();
    if (!selectedProjectId) {
      return;
    }

    setCrmPreviewBusy(true);
    setError("");
    setCrmMessage("");

    try {
      const preview = await requestJson(`/projects/${selectedProjectId}/crm/previews`, {
        method: "POST",
        body: JSON.stringify({
          student_id: crmStudentId,
          lookup_mode: crmLookupMode,
        }),
      });
      setSelectedCrmPreviewId(preview.id);
      setCrmMessage("Превью создано. Проверьте поля, review-статус и только потом отправляйте в AMO.");
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось создать CRM превью");
    } finally {
      setCrmPreviewBusy(false);
    }
  }

  function handleToggleCrmField(fieldName) {
    setCrmSelectedFields((current) => {
      if (current.includes(fieldName)) {
        return current.filter((value) => value !== fieldName);
      }
      return [...current, fieldName];
    });
  }

  function handleCrmFieldValueChange(fieldName, value) {
    setCrmFieldValues((current) => ({
      ...current,
      [fieldName]: value,
    }));
  }

  async function handleSendCrmPreview({ amoEntityId } = {}) {
    if (!selectedProjectId || !selectedCrmPreview) {
      return;
    }

    const availableFields = selectedCrmPreview.amo_field_payload || {};
    const selectedFields = crmSelectedFields.filter(
      (fieldName) => Object.prototype.hasOwnProperty.call(availableFields, fieldName),
    );
    if (selectedFields.length === 0) {
      setError("Выбери хотя бы одно поле для отправки в AMO.");
      return;
    }

    const fieldOverrides = {};
    selectedFields.forEach((fieldName) => {
      const value = crmFieldValues[fieldName];
      if (value === undefined) {
        return;
      }
      fieldOverrides[fieldName] = value;
    });

    setCrmSendBusy(true);
    setError("");
    setCrmMessage("");

    try {
      const response = await requestJson(
        `/projects/${selectedProjectId}/crm/previews/${selectedCrmPreview.id}/send`,
        {
          method: "POST",
          body: JSON.stringify({
            amo_entity_id: amoEntityId || null,
            selected_fields: selectedFields,
            field_overrides: fieldOverrides,
          }),
        },
      );
      setCrmMessage(response.summary || "Отправка завершена.");
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось отправить данные в AMO");
    } finally {
      setCrmSendBusy(false);
    }
  }

  async function handleResolveCrmReview({ outcome, summary, amoEntityId } = {}) {
    if (!selectedProjectId || !selectedCrmPreview) {
      return;
    }
    if (!outcome) {
      return;
    }

    setCrmReviewBusy(outcome);
    setError("");
    setCrmMessage("");

    try {
      const response = await requestJson(
        `/projects/${selectedProjectId}/crm/review-queue/${selectedCrmPreview.id}/resolve`,
        {
          method: "POST",
          body: JSON.stringify({
            outcome,
            summary: summary || null,
            amo_entity_id: amoEntityId || null,
          }),
        },
      );
      setCrmMessage(response.summary || "Решение по CRM-превью сохранено.");
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось обработать review CRM-превью");
    } finally {
      setCrmReviewBusy("");
    }
  }

  async function handleResolveCallReview({ outcome, summary, matchedAmoContactId } = {}) {
    if (!selectedProjectId || !selectedCallInsight) {
      return;
    }
    if (!outcome) {
      return;
    }
    const trimmedMatchedId = String(matchedAmoContactId || "").trim();
    if (outcome === "approved" && !trimmedMatchedId) {
      setError("Для одобрения звонка укажи ID контакта AMO.");
      return;
    }

    setCallReviewBusy(outcome);
    setError("");
    setCallMessage("");

    try {
      const response = await requestJson(
        `/projects/${selectedProjectId}/calls/review-queue/${selectedCallInsight.id}/resolve`,
        {
          method: "POST",
          body: JSON.stringify({
            outcome,
            matched_amo_contact_id: outcome === "approved" ? Number(trimmedMatchedId) : null,
            summary: summary || null,
          }),
        },
      );
      setCallMessage(response.summary || "Решение по звонку сохранено.");
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось обработать review звонка");
    } finally {
      setCallReviewBusy("");
    }
  }

  async function handleSendCallInsight({ matchedAmoContactId } = {}) {
    if (!selectedProjectId || !selectedCallInsight) {
      return;
    }

    const trimmedMatchedId = String(
      matchedAmoContactId || selectedCallInsight.matched_amo_contact_id || "",
    ).trim();
    if (!trimmedMatchedId) {
      setError("Перед отправкой укажи или подтверди ID контакта AMO.");
      return;
    }

    setCallSendBusy(true);
    setError("");
    setCallMessage("");

    try {
      const response = await requestJson(
        `/projects/${selectedProjectId}/calls/insights/${selectedCallInsight.id}/send`,
        {
          method: "POST",
          body: JSON.stringify({
            matched_amo_contact_id: Number(trimmedMatchedId),
          }),
        },
      );
      setCallMessage(response.summary || "Звонок отправлен в AMO.");
      await loadProjectWorkspace(selectedProjectId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не удалось отправить данные звонка в AMO");
    } finally {
      setCallSendBusy(false);
    }
  }

  function handleSelectRun(run) {
    setSelectedTaskId(run.task_id);
    setSelectedRunId(run.id);
  }

  function handleOpenTaskRuns(taskId) {
    if (!taskId) {
      navigate("/runs");
      return;
    }

    setSelectedTaskId(taskId);
    const relatedRun = projectRuns.find((run) => run.task_id === taskId);
    if (relatedRun) {
      setSelectedRunId(relatedRun.id);
    }
    navigate("/runs");
  }

  return (
    <main className="shell">
      <OfficeToolbar
        moduleItems={MODULE_NAV_ITEMS}
        officeItems={OFFICE_NAV_ITEMS}
        onRefreshProjects={handleRefreshProjects}
        onSelectProject={setSelectedProjectId}
        onToggleShowArchivedProjects={setShowArchivedProjects}
        onToggleShowTechnicalProjects={setShowTechnicalProjects}
        projects={toolbarProjects}
        projectsRefreshing={projectsRefreshing}
        selectedProject={selectedProject}
        selectedProjectId={selectedProjectId}
        showArchivedProjects={showArchivedProjects}
        showTechnicalProjects={showTechnicalProjects}
        hiddenProjectsCount={hiddenProjectsCount}
      />

      <section className="summary-strip">
        <article className="summary-card">
          <span>API</span>
          <strong>{labelFromMap(HEALTH_STATUS_LABELS, health.status, health.status)}</strong>
          <small>{API_BASE_URL}</small>
        </article>
        <article className="summary-card">
          <span>События</span>
          <strong>{labelFromMap(STREAM_STATUS_LABELS, streamStatus, streamStatus)}</strong>
          <small>онлайн-обновления</small>
        </article>
        <article className="summary-card">
          <span>Задачи сейчас</span>
          <strong>{runningTasksCount}</strong>
          <small>в работе</small>
        </article>
        <article className="summary-card">
          <span>Одобрения</span>
          <strong>{pendingApprovals.length}</strong>
          <small>требуют решения</small>
        </article>
      </section>

      {error ? <p className="error-banner">{error}</p> : null}

      <div className="route-content">
        <Routes>
          <Route path="/" element={<Navigate replace to="/director" />} />

          <Route
            path="/director"
            element={(
              <DirectorPage
                actionBusy={actionBusy}
                blockedTasks={blockedTasks}
                blockedTasksCount={blockedTasksCount}
                busy={busy}
                busyAgentsCount={busyAgentsCount}
                cancelBusy={cancelBusy}
                completionPercent={completionPercent}
                createDescription={createDescription}
                createName={createName}
                directorAgent={directorAgent}
                displayAgentBadge={displayAgentBadge}
                displayAgentRole={displayAgentRole}
                displayAgentStatus={displayAgentStatus}
                doneTasksCount={doneTasksCount}
                eventTitle={eventTitle}
                executionBusy={executionBusy}
                focusTasks={focusTasks}
                formatDate={formatDate}
                formatTaskStatus={formatTaskStatus}
                goalText={goalText}
                handleAdvanceDirector={handleAdvanceDirector}
                handleCancelRun={handleCancelRun}
                handleCreateProject={handleCreateProject}
                handleOpenApprovals={() => navigate("/approvals")}
                handleOpenCrm={() => navigate("/crm")}
                handleOpenEvents={() => navigate("/events")}
                handleOpenRuns={() => navigate("/runs")}
                handleOpenTaskRuns={handleOpenTaskRuns}
                handleOpenTeam={() => navigate("/team")}
                handleArchiveProject={handleArchiveProject}
                handleRestoreProject={handleRestoreProject}
                handleSubmitGoal={handleSubmitGoal}
                handleTaskAction={handleTaskAction}
                latestDirectorMessage={latestDirectorMessage}
                latestEvent={latestEvent}
                nextAction={nextAction}
                officeAgents={officeAgents}
                pendingApprovalsCount={pendingApprovals.length}
                planSummary={planSummary}
                preflightBlockingChecks={preflightBlockingChecks}
                preflightStatus={preflightStatus}
                projectsCount={projects.length}
                readyTasks={readyTasks}
                readyTasksCount={readyTasksCount}
                recentDirectorMessages={recentDirectorMessages}
                reviewTasksCount={reviewTasksCount}
                runLogs={runLogs}
                runningTaskRun={runningTaskRun}
                runningTasksCount={runningTasksCount}
                selectedProject={selectedProject}
                selectedRun={selectedRun}
                selectedTask={selectedTask}
                selectedTaskPreflight={selectedTaskPreflight}
                setCreateDescription={setCreateDescription}
                setCreateName={setCreateName}
                setGoalText={setGoalText}
                setSelectedTaskId={setSelectedTaskId}
                shortenText={shortenText}
                sortedAgentsCount={sortedAgents.length}
                statusClass={statusClass}
                summarizeEventPayload={summarizeEventPayload}
                projectActionBusy={projectActionBusy}
              />
            )}
          />

          <Route
            path="/team"
            element={(
              <TeamPage
                blockedAgentsCount={blockedAgentsCount}
                displayAgentBadge={displayAgentBadge}
                displayAgentRole={displayAgentRole}
                displayAgentStatus={displayAgentStatus}
                idleAgentsCount={idleAgentsCount}
                reviewingAgentsCount={reviewingAgentsCount}
                runningAgentsCount={runningAgentsCount}
                sortedAgents={sortedAgents}
                statusClass={statusClass}
              />
            )}
          />

          <Route
            path="/runs"
            element={(
              <RunsPage
                activeRunPreflight={activeRunPreflight}
                activeRunRuntime={activeRunRuntime}
                cancelBusy={cancelBusy}
                failedRunsCount={failedRunsCount}
                formatDate={formatDate}
                formatTaskStatus={formatTaskStatus}
                handleCancelRun={handleCancelRun}
                handleSelectRun={handleSelectRun}
                pendingApprovalsCount={pendingApprovals.length}
                preflightStatus={preflightStatus}
                projectRuns={projectRuns}
                reviewRunsCount={reviewRunsCount}
                runLogs={runLogs}
                runningRunsCount={runningRunsCount}
                runtimeStatus={runtimeStatus}
                selectedProject={selectedProject}
                selectedRun={selectedRun}
                selectedRunTask={selectedRunTask}
                statusClass={statusClass}
                totalRunsCount={projectRuns.length}
                cancelledRunsCount={cancelledRunsCount}
              />
            )}
          />

          <Route
            path="/events"
            element={(
              <EventsPage
                eventScopeFilter={eventScopeFilter}
                eventTitle={eventTitle}
                eventWindowFilter={eventWindowFilter}
                filteredEvents={filteredEvents}
                formatDate={formatDate}
                setEventScopeFilter={setEventScopeFilter}
                setEventWindowFilter={setEventWindowFilter}
                summarizeEventPayload={summarizeEventPayload}
              />
            )}
          />

          <Route
            path="/approvals"
            element={(
              <ApprovalsPage
                approvalActionBusy={approvalActionBusy}
                approvalStatusLabels={APPROVAL_STATUS_LABELS}
                approvalsFilter={approvalsFilter}
                displayAgentRole={displayAgentRole}
                filteredApprovals={filteredApprovals}
                formatDate={formatDate}
                handleResolveApproval={handleResolveApproval}
                labelFromMap={labelFromMap}
                riskLevelLabels={RISK_LEVEL_LABELS}
                setApprovalsFilter={setApprovalsFilter}
                statusClass={statusClass}
              />
            )}
          />

          <Route
            path="/artifacts"
            element={(
              <ArtifactsPage
                artifactWindowFilter={artifactWindowFilter}
                filteredArtifacts={filteredArtifacts}
                formatDate={formatDate}
                setArtifactWindowFilter={setArtifactWindowFilter}
                shortenText={shortenText}
              />
            )}
          />

          <Route
            path="/crm"
            element={(
              <CrmPage
                crmApprovedCount={crmApprovedCount}
                crmFailedCount={crmFailedCount}
                crmFieldValues={crmFieldValues}
                crmLookupMode={crmLookupMode}
                crmMessage={crmMessage}
                crmPreviewBusy={crmPreviewBusy}
                crmPreviews={crmPreviews}
                crmReviewBusy={crmReviewBusy}
                crmReviewQueueCount={crmReviewQueueCount}
                crmSelectedFields={crmSelectedFields}
                crmSendBusy={crmSendBusy}
                crmSentCount={crmSentCount}
                crmStudentId={crmStudentId}
                formatCrmStatus={formatCrmStatus}
                formatDate={formatDate}
                formatReviewStatus={formatReviewStatus}
                handleCreateCrmPreview={handleCreateCrmPreview}
                handleCrmFieldValueChange={handleCrmFieldValueChange}
                handleResolveCrmReview={handleResolveCrmReview}
                handleSendCrmPreview={handleSendCrmPreview}
                handleToggleCrmField={handleToggleCrmField}
                selectedCrmPreview={selectedCrmPreview}
                selectedProject={selectedProject}
                setCrmLookupMode={setCrmLookupMode}
                setCrmStudentId={setCrmStudentId}
                setSelectedCrmPreviewId={setSelectedCrmPreviewId}
                statusClass={statusClass}
              />
            )}
          />

          <Route
            path="/calls"
            element={(
              <CallsPage
                callMessage={callMessage}
                callsArtifacts={callsArtifacts}
                callsFocusTasks={callsFocusTasks}
                callInsights={callInsights}
                callsApprovedCount={callsApprovedCount}
                callsHotCount={callsHotCount}
                callsManualReviewCount={callsManualReviewCount}
                callsMatchedCount={callsMatchedCount}
                callsModuleState={callsModuleState}
                callsPendingMatchCount={callsPendingMatchCount}
                callInsightsCount={callInsightsCount}
                callReviewBusy={callReviewBusy}
                callSendBusy={callSendBusy}
                displayAgentRole={displayAgentRole}
                formatCallMatchStatus={formatCallMatchStatus}
                formatCallPriority={formatCallPriority}
                formatCallProcessingStatus={formatCallProcessingStatus}
                formatDate={formatDate}
                formatReviewStatus={formatReviewStatus}
                formatTaskStatus={formatTaskStatus}
                handleOpenApprovals={() => navigate("/approvals")}
                handleOpenDirector={() => navigate("/director")}
                handleOpenRuns={() => navigate("/runs")}
                handleResolveCallReview={handleResolveCallReview}
                handleSendCallInsight={handleSendCallInsight}
                selectedCallInsight={selectedCallInsight}
                selectedProject={selectedProject}
                setSelectedCallInsightId={setSelectedCallInsightId}
                shortenText={shortenText}
                statusClass={statusClass}
              />
            )}
          />

          <Route path="*" element={<Navigate replace to="/director" />} />
        </Routes>
      </div>
    </main>
  );
}

export default App;
