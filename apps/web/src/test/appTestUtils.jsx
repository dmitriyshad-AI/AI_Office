import { vi } from "vitest";

const NOW = new Date(Date.now() - 60 * 60 * 1000).toISOString();

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function createJsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return deepClone(body);
    },
    async text() {
      return typeof body === "string" ? body : JSON.stringify(body);
    },
  };
}

export function createAppData() {
  const project = {
    id: "project-1",
    name: "CRM Office",
    description: "Тестовый проект интеграции CRM",
    status: "draft",
    latest_goal_text: "Подготовить CRM-пайплайн",
    created_at: NOW,
    updated_at: NOW,
  };

  const tasks = [
    {
      id: "task-1",
      project_id: project.id,
      assigned_agent_id: "agent-2",
      assigned_agent_role: "BackendEngineer",
      task_key: "backend_pipeline",
      title: "Собрать backend-пайплайн CRM",
      brief: "Сделать безопасный перенос данных в AMO CRM.",
      acceptance_criteria: ["Есть API", "Есть проверка"],
      status: "ready",
      priority: 100,
      depends_on_ids: [],
      created_at: NOW,
      updated_at: NOW,
    },
    {
      id: "task-2",
      project_id: project.id,
      assigned_agent_id: "agent-3",
      assigned_agent_role: "QAReviewer",
      task_key: "qa_review",
      title: "Проверить перенос",
      brief: "Проверить данные и найти риски.",
      acceptance_criteria: ["Риски описаны"],
      status: "blocked",
      priority: 80,
      depends_on_ids: ["task-1"],
      created_at: NOW,
      updated_at: NOW,
    },
  ];

  const runs = [
    {
      id: "run-1",
      task_id: "task-1",
      task_title: "Собрать backend-пайплайн CRM",
      task_key: "backend_pipeline",
      status: "running",
      started_at: NOW,
      finished_at: null,
      worktree_path: "/runtime/task-1",
      environment_name: "crm-env",
    },
  ];

  return {
    project,
    health: { status: "ok", service: "api" },
    projects: [project],
    agents: [
      {
        id: "agent-1",
        project_id: project.id,
        role: "Director",
        name: "Директор",
        status: "planning",
        specialization: "Координация офиса",
        current_task_title: "Планирует этап",
        quality_score: 0.98,
        average_task_time_seconds: 120,
        created_at: NOW,
      },
      {
        id: "agent-2",
        project_id: project.id,
        role: "BackendEngineer",
        name: "Backend сотрудник",
        status: "running",
        specialization: "API и интеграции",
        current_task_title: "Собрать backend-пайплайн CRM",
        quality_score: 0.92,
        average_task_time_seconds: 340,
        created_at: NOW,
      },
    ],
    tasks,
    approvals: [
      {
        id: "approval-1",
        project_id: project.id,
        task_id: "task-1",
        approval_policy_id: "policy-1",
        risk_assessment_id: "risk-1",
        action: "runtime.host_access",
        risk_level: "high",
        status: "pending",
        reason: "Требуется доступ к защищённому пути.",
        requested_by: "director",
        resolved_by: null,
        resolved_at: null,
        resolution_summary: null,
        created_at: NOW,
      },
    ],
    artifacts: [
      {
        id: "artifact-1",
        project_id: project.id,
        task_id: "task-1",
        kind: "spec",
        title: "CRM plan",
        content: "Итоговая спецификация CRM.",
        created_at: NOW,
      },
    ],
    messages: [
      {
        id: "message-1",
        project_id: project.id,
        role: "director",
        content: "Директор собрал план и готов продолжать.",
        created_at: NOW,
      },
    ],
    events: [
      {
        id: "event-1",
        project_id: project.id,
        task_id: "task-1",
        event_type: "director_progress_update",
        payload: { progress: "50%", focus: "CRM" },
        created_at: NOW,
      },
    ],
    runs,
    runtime: {
      workspace: {
        id: "workspace-1",
        project_id: project.id,
        task_id: "task-1",
        root_path: "/runtime",
        workspace_path: "/runtime/task-1",
        source_root_path: "/source",
        workspace_mode: "snapshot-copy",
        sync_status: "seeded",
        sandbox_mode: "workspace-write",
        state: "running",
        context_file_path: "/runtime/task-1/TASK_CONTEXT.json",
        created_at: NOW,
        updated_at: NOW,
      },
      environment: {
        id: "env-1",
        project_id: project.id,
        task_id: "task-1",
        name: "crm-env",
        runtime_kind: "workspace-runtime",
        runtime_status: "ready",
        base_image: "python:3.12",
        container_name: null,
        container_id: null,
        container_workdir: "/workspace",
        source_mount_mode: "ro",
        workspace_mount_mode: "rw",
        network_mode: "none",
        env_vars: {},
        mounts: ["/workspace"],
        created_at: NOW,
        updated_at: NOW,
      },
      run_policy: {
        id: "policy-1",
        project_id: project.id,
        task_id: "task-1",
        policy_level: "medium",
        network_access: "none",
        filesystem_scope: "task-workspace-only",
        package_installation_mode: "allowlist",
        default_risk_level: "medium",
        notes: "Тестовая политика",
        created_at: NOW,
        updated_at: NOW,
      },
      runs,
    },
    preflight: {
      ready: true,
      checks: [
        {
          key: "workspace.exists",
          status: "pass",
          message: "Workspace is ready.",
          blocking: false,
        },
      ],
      summary: "Среда готова к запуску.",
    },
    runLog: {
      id: "run-1",
      task_id: "task-1",
      status: "running",
      started_at: NOW,
      finished_at: null,
      worktree_path: "/runtime/task-1",
      environment_name: "crm-env",
      stdout: "Mock worker started.\n",
      stderr: "",
    },
    crmPreviews: [
      {
        id: "preview-1",
        project_id: project.id,
        source_student_id: "student-1001",
        source_system: "Tallanto",
        amo_entity_type: "contact",
        amo_entity_id: "75807689",
        source_payload: { student_id: "student-1001" },
        canonical_payload: { full_name: "Иван Иванов", phone: "+79990000000" },
        amo_field_payload: {
          name: "Иван Иванов",
          phone: "+79990000000",
        },
        field_mapping: { name: "full_name", phone: "phone" },
        analysis_summary: "Ученик интересен для точечного CRM-переноса.",
        status: "previewed",
        review_status: "approved",
        review_reason: "Проверка уже завершена.",
        review_summary: "Поля подтверждены для controlled write.",
        reviewed_by: "director",
        reviewed_at: NOW,
        created_by: "director",
        sent_by: null,
        sent_at: null,
        send_result: null,
        error_message: null,
        created_at: NOW,
        updated_at: NOW,
      },
    ],
    callInsights: [
      {
        id: "insight-1",
        project_id: project.id,
        source_system: "mango_analyse",
        source_key: "call:mango-1001",
        source_call_id: "mango-1001",
        source_record_id: "1001",
        source_file: "/tmp/calls/2026-03-19__10-00-00__79990001122__Леонова Анна_1001.mp3",
        source_filename: "2026-03-19__10-00-00__79990001122__Леонова Анна_1001.mp3",
        phone: "+79990001122",
        manager_name: "Леонова Анна",
        started_at: NOW,
        duration_sec: 312.4,
        history_summary:
          "19.03.2026 менеджер Леонова Анна обсудила курс математики для 9 класса. Родитель запросил материалы и ждёт повторный звонок.",
        lead_priority: "hot",
        follow_up_score: 86,
        processing_status: "done",
        status: "ingested",
        match_status: "pending_match",
        matched_amo_contact_id: null,
        review_status: "pending",
        review_reason: "Один номер телефона связан с несколькими учениками семьи.",
        review_summary: null,
        reviewed_by: null,
        reviewed_at: null,
        sent_by: null,
        sent_at: null,
        send_result: null,
        error_message: null,
        payload: {
          identity_hints: {
            parent_fio: "Иванова Анна",
            child_fio: "Петр Иванов",
            email: "family@example.com",
            grade_current: "9",
            school: "Школа 57",
            preferred_channel: "telegram",
          },
          call_summary: {
            history_short: "Нужен follow-up по курсу математики.",
            evidence: [
              {
                speaker: "Клиент",
                ts: "00:32.1",
                text: "Нас интересует математика для 9 класса.",
              },
            ],
          },
          sales_insight: {
            interests: {
              products: ["Годовые курсы"],
              format: ["Онлайн"],
              subjects: ["Математика"],
              exam_targets: ["ОГЭ"],
            },
            objections: ["Цена"],
            next_step: {
              action: "Отправить материалы и перезвонить",
              due: "на этой неделе",
            },
            tags: ["follow_up", "math"],
          },
        },
        created_by: "director",
        created_at: NOW,
        updated_at: NOW,
      },
      {
        id: "insight-2",
        project_id: project.id,
        source_system: "mango_analyse",
        source_key: "call:mango-1002",
        source_call_id: "mango-1002",
        source_record_id: "1002",
        source_file: "/tmp/calls/2026-03-19__11-15-00__79990003344__Крылова Дарья_1002.mp3",
        source_filename: "2026-03-19__11-15-00__79990003344__Крылова Дарья_1002.mp3",
        phone: "+79990003344",
        manager_name: "Крылова Дарья",
        started_at: "2026-03-19T11:15:00.000Z",
        duration_sec: 208.1,
        history_summary:
          "19.03.2026 менеджер Крылова Дарья подтвердила детали по летней смене и нашла существующего ученика.",
        lead_priority: "warm",
        follow_up_score: 63,
        processing_status: "done",
        status: "ingested",
        match_status: "matched",
        matched_amo_contact_id: 75807689,
        review_status: "approved",
        review_reason: null,
        review_summary: "Контакт подтверждён.",
        reviewed_by: "director",
        reviewed_at: NOW,
        sent_by: null,
        sent_at: null,
        send_result: null,
        error_message: null,
        payload: {
          identity_hints: {
            parent_fio: "Самойлова Дарья Дмитриевна",
            child_fio: "Федор Александрович Левашко",
            grade_current: "5",
            preferred_channel: "email",
          },
          call_summary: {
            history_short: "Материалы отправлены, follow-up не срочный.",
            evidence: [],
          },
          sales_insight: {
            interests: {
              products: ["ЛШВ"],
              format: ["Очно"],
              subjects: ["Физика"],
              exam_targets: [],
            },
            objections: [],
            next_step: {
              action: "Ожидать оплату",
              due: "до конца недели",
            },
            tags: ["matched"],
          },
        },
        created_by: "director",
        created_at: NOW,
        updated_at: NOW,
      },
    ],
  };
}

export function installEventSourceMock() {
  class MockEventSource {
    constructor(url) {
      this.url = url;
      this.listeners = new Map();
      setTimeout(() => {
        this.onopen?.();
      }, 0);
    }

    addEventListener(type, callback) {
      this.listeners.set(type, callback);
    }

    close() {}
  }

  vi.stubGlobal("EventSource", MockEventSource);
}

export function installFetchMock({
  noProjects = false,
  enableCreateProject = false,
  enableResolveApproval = false,
  enableSendPreview = false,
  crmPreviewPending = false,
  multipleProjects = false,
} = {}) {
  const data = createAppData();
  const technicalProject = {
    ...deepClone(data.project),
    id: "project-2",
    name: "Smoke Probe",
    description: "Технический учебный прогон",
  };
  const state = {
    projects: noProjects ? [] : multipleProjects ? [deepClone(data.project), technicalProject] : deepClone(data.projects),
    project: deepClone(data.project),
    agents: deepClone(data.agents),
    tasks: noProjects ? [] : deepClone(data.tasks),
    approvals: noProjects ? [] : deepClone(data.approvals),
    artifacts: noProjects ? [] : deepClone(data.artifacts),
    messages: noProjects ? [] : deepClone(data.messages),
    events: noProjects ? [] : deepClone(data.events),
    runs: noProjects ? [] : deepClone(data.runs),
    runtime: deepClone(data.runtime),
    preflight: deepClone(data.preflight),
    runLog: deepClone(data.runLog),
    crmPreviews: noProjects ? [] : deepClone(data.crmPreviews),
    callInsights: noProjects ? [] : deepClone(data.callInsights),
    amoIntegrationStatus: {
      integration_mode: "external",
      redirect_uri: "https://api.fotonai.online/api/integrations/amocrm/callback",
      secrets_uri: "https://api.fotonai.online/api/integrations/amocrm/secrets",
      scopes: ["crm"],
      integration_name: "AI Office",
      integration_description: "Интеграция AI Office для безопасной записи данных в amoCRM.",
      logo_url: null,
      account_base_url_hint: "https://educent.amocrm.ru",
      button_snippet:
        '<script class="amocrm_oauth" charset="utf-8" data-name="AI Office" data-description="Интеграция AI Office для безопасной записи данных в amoCRM." data-redirect_uri="https://api.fotonai.online/api/integrations/amocrm/callback" data-secrets_uri="https://api.fotonai.online/api/integrations/amocrm/secrets" data-logo="" data-scopes="crm" data-title="Подключить amoCRM" data-mode="popup" src="https://www.amocrm.ru/auth/button.min.js"></script>',
      connected: false,
      status: "not_connected",
      account_base_url: "https://educent.amocrm.ru",
      account_subdomain: "educent",
      client_id_present: false,
      client_secret_present: false,
      access_token_present: false,
      refresh_token_present: false,
      authorized_at: null,
      expires_at: null,
      last_error: null,
      contact_field_catalog_synced_at: null,
      contact_field_count: 0,
      required_contact_fields_present: [],
      required_contact_fields_missing: [
        "Id Tallanto",
        "Филиал Tallanto",
        "Баланс Tallanto",
      ],
      token_source: null,
    },
  };

  if (crmPreviewPending && state.crmPreviews[0]) {
    state.crmPreviews[0] = {
      ...state.crmPreviews[0],
      review_status: "pending",
      review_reason: "Нужна ручная проверка.",
      review_summary: null,
      reviewed_by: null,
      reviewed_at: null,
    };
  }

  const createdProject = deepClone(data.project);
  const calls = [];

  const mock = vi.fn(async (input, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;

    calls.push({ method, path });

    if (path === "/health" && method === "GET") {
      return createJsonResponse(data.health);
    }

    if (path === "/api/integrations/amocrm/status" && method === "GET") {
      return createJsonResponse(state.amoIntegrationStatus);
    }

    if (path === "/api/integrations/amocrm/contact-fields/sync" && method === "POST") {
      state.amoIntegrationStatus = {
        ...state.amoIntegrationStatus,
        connected: true,
        status: "connected",
        client_id_present: true,
        client_secret_present: true,
        access_token_present: true,
        refresh_token_present: true,
        token_source: "oauth",
        contact_field_catalog_synced_at: NOW,
        contact_field_count: 14,
        required_contact_fields_present: ["Id Tallanto", "Филиал Tallanto"],
        required_contact_fields_missing: ["Баланс Tallanto"],
      };
      return createJsonResponse({
        status: "ok",
        summary: "Каталог полей контактов amoCRM синхронизирован.",
        field_count: 14,
        synced_at: NOW,
      });
    }

    if (path === "/projects" && method === "GET") {
      return createJsonResponse(state.projects);
    }

    if (path === "/projects" && method === "POST" && enableCreateProject) {
      state.projects = [createdProject];
      return createJsonResponse(createdProject, 201);
    }

    if (!state.projects.length) {
      return createJsonResponse({ detail: "Not found" }, 404);
    }

    const projectId = state.project.id;

    if (path === `/projects/${projectId}` && method === "GET") {
      return createJsonResponse(state.project);
    }
    if (path === `/projects/${projectId}/archive` && method === "POST") {
      state.project = { ...state.project, status: "archived", updated_at: NOW };
      state.projects = state.projects.map((project) =>
        project.id === projectId ? { ...project, status: "archived", updated_at: NOW } : project,
      );
      return createJsonResponse({
        project: state.project,
        summary: `Проект «${state.project.name}» перенесён в архив.`,
      });
    }
    if (path === `/projects/${projectId}/restore` && method === "POST") {
      state.project = { ...state.project, status: "active", updated_at: NOW };
      state.projects = state.projects.map((project) =>
        project.id === projectId ? { ...project, status: "active", updated_at: NOW } : project,
      );
      return createJsonResponse({
        project: state.project,
        summary: `Проект «${state.project.name}» возвращён в рабочий список.`,
      });
    }
    if (path === `/projects/${projectId}/agents` && method === "GET") {
      return createJsonResponse(state.agents);
    }
    if (path === `/projects/${projectId}/tasks` && method === "GET") {
      return createJsonResponse(state.tasks);
    }
    if (path === `/projects/${projectId}/goal` && method === "POST") {
      const payload = JSON.parse(options.body || "{}");
      state.project = {
        ...state.project,
        latest_goal_text: payload.goal_text || state.project.latest_goal_text,
        updated_at: NOW,
      };
      state.messages = [
        ...state.messages,
        {
          id: `message-${state.messages.length + 1}`,
          project_id: projectId,
          role: "director",
          content: "Новый план задач построен.",
          created_at: NOW,
        },
      ];
      state.events = [
        {
          id: `event-${state.events.length + 1}`,
          project_id: projectId,
          task_id: null,
          event_type: "goal_planned",
          payload: { goal_text: payload.goal_text || "" },
          created_at: NOW,
        },
        ...state.events,
      ];
      return createJsonResponse({
        project: state.project,
        created_tasks: state.tasks,
        summary: "Новый план задач построен.",
      });
    }
    if (path === `/projects/${projectId}/director/advance` && method === "POST") {
      state.tasks = state.tasks.map((task) =>
        task.id === "task-1" ? { ...task, status: "running", updated_at: NOW } : task,
      );
      state.agents = state.agents.map((agent) =>
        agent.id === "agent-1"
          ? { ...agent, status: "running", current_task_title: "Запускает backend-пайплайн" }
          : agent.id === "agent-2"
            ? { ...agent, status: "running", current_task_title: "Собрать backend-пайплайн CRM" }
            : agent,
      );
      state.runtime = {
        ...state.runtime,
        runs: state.runtime.runs.map((run) =>
          run.id === "run-1" ? { ...run, status: "running" } : run,
        ),
      };
      state.runs = state.runs.map((run) =>
        run.id === "run-1" ? { ...run, status: "running" } : run,
      );
      return createJsonResponse({
        summary: "Директор проверил очередь и продолжил работу.",
        dispatched_task_id: "task-1",
        dispatched_run_id: "run-1",
      });
    }
    if (path === `/projects/${projectId}/approvals` && method === "GET") {
      return createJsonResponse(state.approvals);
    }
    if (path === `/projects/${projectId}/artifacts` && method === "GET") {
      return createJsonResponse(state.artifacts);
    }
    if (path === `/projects/${projectId}/messages` && method === "GET") {
      return createJsonResponse(state.messages);
    }
    if (path === `/projects/${projectId}/events` && method === "GET") {
      return createJsonResponse(state.events);
    }
    if (path === `/projects/${projectId}/runs` && method === "GET") {
      return createJsonResponse(state.runs);
    }
    if (path === `/projects/${projectId}/crm/previews` && method === "GET") {
      return createJsonResponse(state.crmPreviews);
    }
    if (path === `/projects/${projectId}/calls/insights` && method === "GET") {
      return createJsonResponse(state.callInsights);
    }
    if (path === `/projects/${projectId}/tasks/task-1/runtime` && method === "GET") {
      return createJsonResponse(state.runtime);
    }
    if (path === `/projects/${projectId}/tasks/task-1/preflight` && method === "GET") {
      return createJsonResponse(state.preflight);
    }
    if (path === `/projects/${projectId}/tasks/task-2/runtime` && method === "GET") {
      return createJsonResponse({
        ...state.runtime,
        workspace: {
          ...state.runtime.workspace,
          task_id: "task-2",
          workspace_path: "/runtime/task-2",
        },
        runs: [],
      });
    }
    if (path === `/projects/${projectId}/tasks/task-2/preflight` && method === "GET") {
      return createJsonResponse({
        ...state.preflight,
        summary: "Для заблокированной задачи запуск не готов.",
        checks: [
          {
            key: "task.dependencies",
            status: "fail",
            message: "Есть незавершённые зависимости.",
            blocking: true,
          },
        ],
      });
    }
    if (path === `/projects/${projectId}/stream-token` && method === "POST") {
      return createJsonResponse({
        token: "stream-token",
        expires_at: "2026-03-19T10:00:00.000Z",
      });
    }
    if (path === "/task-runs/run-1/logs" && method === "GET") {
      return createJsonResponse(state.runLog);
    }
    const approvalMatch = path.match(new RegExp(`^/projects/${projectId}/approvals/([^/]+)/resolve$`));
    if (approvalMatch && method === "POST" && enableResolveApproval) {
      const approvalId = approvalMatch[1];
      const payload = JSON.parse(options.body || "{}");
      const outcome = payload.outcome || "approved";
      state.approvals = state.approvals.map((approval) =>
        approval.id === approvalId
          ? {
              ...approval,
              status: outcome,
              resolved_by: "human",
              resolved_at: NOW,
            }
          : approval,
      );
      return createJsonResponse({
        approval_request: state.approvals.find((approval) => approval.id === approvalId),
        approval_decision: {
          id: "decision-1",
          project_id: projectId,
          task_id: "task-1",
          risk_assessment_id: "risk-1",
          approval_request_id: approvalId,
          action_key: "runtime.host_access",
          risk_level: "high",
          actor: "human",
          outcome,
          summary: outcome === "approved" ? "Одобрено вручную." : "Отклонено вручную.",
          created_at: NOW,
        },
        risk_assessment: null,
        action_intent: null,
        summary: outcome === "approved" ? "Одобрение сохранено." : "Отклонение сохранено.",
      });
    }
    const taskActionMatch = path.match(new RegExp(`^/projects/${projectId}/tasks/([^/]+)/actions$`));
    if (taskActionMatch && method === "POST") {
      const taskId = taskActionMatch[1];
      const payload = JSON.parse(options.body || "{}");
      state.tasks = state.tasks.map((task) => {
        if (task.id !== taskId) {
          return task;
        }
        if (payload.action === "complete") {
          return { ...task, status: "done", updated_at: NOW };
        }
        if (payload.action === "block") {
          return { ...task, status: "blocked", updated_at: NOW };
        }
        if (payload.action === "reset") {
          return { ...task, status: "ready", updated_at: NOW };
        }
        return task;
      });
      return createJsonResponse({
        summary: "Статус задачи обновлён.",
      });
    }
    const cancelMatch = path.match(/^\/task-runs\/([^/]+)\/cancel$/);
    if (cancelMatch && method === "POST") {
      const runId = cancelMatch[1];
      state.runs = state.runs.map((run) =>
        run.id === runId ? { ...run, status: "cancelled", finished_at: NOW } : run,
      );
      state.runtime = {
        ...state.runtime,
        runs: state.runtime.runs.map((run) =>
          run.id === runId ? { ...run, status: "cancelled", finished_at: NOW } : run,
        ),
      };
      return createJsonResponse({
        summary: "Запуск отменён.",
      });
    }
    if (path === `/projects/${projectId}/crm/previews` && method === "POST") {
      const payload = JSON.parse(options.body || "{}");
      const preview = {
        id: `preview-${state.crmPreviews.length + 1}`,
        project_id: projectId,
        source_student_id: payload.student_id || "student-generated",
        source_system: "Tallanto",
        amo_entity_type: "contact",
        amo_entity_id: payload.amo_entity_id || null,
        source_payload: { student_id: payload.student_id || "student-generated" },
        canonical_payload: { full_name: "Иван Иванов", phone: "+79990000000" },
        amo_field_payload: {
          name: "Иван Иванов",
          phone: "+79990000000",
        },
        field_mapping: { name: "full_name", phone: "phone" },
        analysis_summary: "Превью готово к проверке.",
        status: "previewed",
        review_status: "pending",
        review_reason: "Нужна ручная проверка перед записью.",
        review_summary: null,
        reviewed_by: null,
        reviewed_at: null,
        created_by: "director",
        sent_by: null,
        sent_at: null,
        send_result: null,
        error_message: null,
        created_at: NOW,
        updated_at: NOW,
      };
      state.crmPreviews = [preview, ...state.crmPreviews];
      return createJsonResponse(preview, 201);
    }
    const sendPreviewMatch = path.match(new RegExp(`^/projects/${projectId}/crm/previews/([^/]+)/send$`));
    if (sendPreviewMatch && method === "POST" && enableSendPreview) {
      const previewId = sendPreviewMatch[1];
      const payload = JSON.parse(options.body || "{}");
      state.crmPreviews = state.crmPreviews.map((preview) =>
        preview.id === previewId
          ? {
              ...preview,
              status: "sent",
              amo_entity_id: payload.amo_entity_id ?? preview.amo_entity_id,
              sent_by: "director",
              sent_at: NOW,
            }
          : preview,
      );
      return createJsonResponse({
        preview: state.crmPreviews.find((preview) => preview.id === previewId),
        summary: "Отправка завершена.",
      });
    }
    const resolveCrmReviewMatch = path.match(
      new RegExp(`^/projects/${projectId}/crm/review-queue/([^/]+)/resolve$`),
    );
    if (resolveCrmReviewMatch && method === "POST") {
      const previewId = resolveCrmReviewMatch[1];
      const payload = JSON.parse(options.body || "{}");
      state.crmPreviews = state.crmPreviews.map((preview) =>
        preview.id === previewId
          ? {
              ...preview,
              review_status: payload.outcome,
              review_summary: payload.summary || null,
              review_reason:
                payload.outcome === "approved"
                  ? "Запись прошла операторскую проверку."
                  : "Запись оставлена в операторской очереди.",
              amo_entity_id: payload.amo_entity_id ?? preview.amo_entity_id,
              reviewed_by: "director",
              reviewed_at: NOW,
            }
          : preview,
      );
      return createJsonResponse({
        preview: state.crmPreviews.find((preview) => preview.id === previewId),
        summary: payload.summary || "Решение по CRM-превью сохранено.",
      });
    }
    const resolveCallReviewMatch = path.match(
      new RegExp(`^/projects/${projectId}/calls/review-queue/([^/]+)/resolve$`),
    );
    if (resolveCallReviewMatch && method === "POST") {
      const insightId = resolveCallReviewMatch[1];
      const payload = JSON.parse(options.body || "{}");
      state.callInsights = state.callInsights.map((insight) =>
        insight.id === insightId
          ? {
              ...insight,
              review_status: payload.outcome,
              review_summary: payload.summary || null,
              review_reason:
                payload.outcome === "approved"
                  ? "Контакт подтверждён оператором."
                  : "Нужна дополнительная ручная проверка.",
              reviewed_by: "director",
              reviewed_at: NOW,
              matched_amo_contact_id:
                payload.matched_amo_contact_id ?? insight.matched_amo_contact_id,
              match_status:
                payload.outcome === "approved"
                  ? "matched"
                  : payload.outcome === "family_case"
                    ? "family_review"
                    : payload.outcome === "duplicate"
                      ? "duplicate_candidate"
                      : "manual_review",
            }
          : insight,
      );
      return createJsonResponse({
        insight: state.callInsights.find((insight) => insight.id === insightId),
        summary: payload.summary || "Решение по звонку сохранено.",
      });
    }
    const sendCallMatch = path.match(new RegExp(`^/projects/${projectId}/calls/insights/([^/]+)/send$`));
    if (sendCallMatch && method === "POST") {
      const insightId = sendCallMatch[1];
      const payload = JSON.parse(options.body || "{}");
      state.callInsights = state.callInsights.map((insight) =>
        insight.id === insightId
          ? {
              ...insight,
              status: "sent",
              matched_amo_contact_id:
                payload.matched_amo_contact_id ?? insight.matched_amo_contact_id,
              sent_by: "director",
              sent_at: NOW,
            }
          : insight,
      );
      return createJsonResponse({
        insight: state.callInsights.find((insight) => insight.id === insightId),
        summary: "Звонок отправлен в AMO.",
      });
    }

    return createJsonResponse({ detail: `Unhandled ${method} ${path}` }, 404);
  });

  vi.stubGlobal("fetch", mock);

  return { calls, data, state, mock };
}
