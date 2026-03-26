# AI Office

`AI Office` is a local `Virtual AI Office` workspace. The current increment includes the bootstrap architecture plus the first persistent backend slice: one web app, one API service, local infrastructure, written V1 boundaries, a database schema, and the first planning API.

## Current bootstrap

- `apps/web`: `Vite + React` shell for the future director console
- `apps/api`: `FastAPI` app with SQLAlchemy models, Alembic migrations, and planning endpoints
- `packages/common`: shared workspace placeholder
- `docker-compose.yml`: local `Postgres`, `Redis`, `API`, and `Web`
- [`docs/V1_SCOPE.md`](./docs/V1_SCOPE.md): product and technical boundaries for V1

## Repository structure

```text
.
├── apps
│   ├── api
│   └── web
├── docs
│   └── V1_SCOPE.md
├── packages
│   └── common
├── .env.example
├── docker-compose.yml
├── package.json
└── README.md
```

## Prerequisites

- `Docker` with `docker compose`
- `Node.js` 20+
- `Python` 3.9+ for local API development

## Local run

1. Create a local env file:

```bash
cp .env.example .env
```

2. Start the full stack:

```bash
docker compose up --build
```

3. Open the apps:

- Web: [http://localhost:5174](http://localhost:5174)
- API docs: [http://localhost:8001/docs](http://localhost:8001/docs)
- API health: [http://localhost:8001/health](http://localhost:8001/health)

Web UI routes:

- `/director`
- `/team`
- `/approvals`
- `/artifacts`

The default local profile is now a real task-container setup on non-conflicting ports. If you need different ports for one run, override them explicitly:

```bash
API_PORT=8010 WEB_PORT=5180 POSTGRES_PORT=5440 REDIS_PORT=6390 VITE_API_BASE_URL=http://localhost:8010 docker compose up --build
```

## Server as thin gateway (recommended for VPS)

Use this profile when heavy processing stays on your MacBook and the VPS only hosts UI/API and external CRM HTTP calls.

```bash
cp .env.example .env
```

Set at least:

```bash
POSTGRES_BIND_HOST=127.0.0.1
REDIS_BIND_HOST=127.0.0.1
API_BIND_HOST=127.0.0.1
WEB_BIND_HOST=127.0.0.1

CODEX_WORKER_MODE=mock
TASK_CONTAINER_DRIVER=process
DIRECTOR_AUTO_RUN_ENABLED=false
DIRECTOR_HEARTBEAT_ENABLED=false

CRM_TALLANTO_MODE=http
CRM_AMO_MODE=http
CRM_ANALYSIS_MODE=heuristic
```

Then run:

```bash
docker compose up -d --build
```

In this mode, Postgres/Redis/API/Web bind only to localhost and should be exposed publicly through reverse proxy (Caddy/Nginx), not by direct Docker port publishing.

API endpoints under `/projects/*` and `/task-runs/*` now require `X-API-Key`. SSE no longer uses long-lived keys in URL: web client requests a short-lived token via `POST /projects/{id}/stream-token` and connects with `?stream_token=...`.
Keep `AI_OFFICE_API_KEY` and `VITE_API_KEY` aligned in `.env`.
For role-based local access, set `AI_OFFICE_API_KEYS` with comma-separated entries in `token:Role:actor` format (for example: `director-key:Director:director,human-key:Human:human`).
Server-side policy checks now use role/actor from API key context and ignore `actor`/`requested_by` values sent by clients.
Set `AI_OFFICE_STREAM_TOKEN_SECRET` in local `.env` to rotate/override SSE token signing material.
Docker API now starts with `API_RELOAD=false` by default for stable SSE behavior.
Set `API_RELOAD=true` only when you explicitly need backend hot reload.
For high parallel load (SSE + many tabs), tune Postgres pool with `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, and `DB_POOL_RECYCLE_SECONDS`.

For real Codex execution, the API process must be able to access a `codex` binary and credentials. The default `.env.example` points to the macOS desktop app binary. If you run the API inside Docker, set `CODEX_CLI_PATH` to a path available inside the container or switch to `CODEX_WORKER_MODE=mock` for demos and tests.

Runtime isolation now also depends on `SOURCE_WORKSPACE_ROOT`:

- by default it points to the repository root
- Docker mounts that root into the API container as `/workspace_root` so approved changes can be promoted back into the main repository
- `RUNTIME_ROOT` must be an absolute host-visible path when `TASK_CONTAINER_DRIVER=docker`; the default compose setup uses `<repo>/runtime` and mounts it at the same absolute path into the API container
- task runtime seeds each workspace from the visible source tree using either `snapshot-copy` or `git-worktree`
- when `.git` is unavailable or not writable, the runtime falls back to `snapshot-copy`
- each execution task provisions a dedicated Docker container that bind-mounts only that task runtime root
- the default task image is `ai-office-task-runner:latest`; API auto-builds it from `apps/task-runner/Dockerfile` when missing
- for real containerized execution, configure `TASK_CONTAINER_CODEX_HOME_HOST_PATH` so task containers can read host Codex credentials from `~/.codex`
- credentials mount is read-only (`TASK_CONTAINER_CODEX_HOME_CONTAINER_PATH`), then worker copies only an allowlisted subset (`TASK_CONTAINER_CODEX_HOME_COPY_ALLOWLIST`) into writable runtime `CODEX_HOME` (`TASK_CONTAINER_CODEX_HOME_RUNTIME_PATH`) before `codex exec`
- runtime copy now excludes heavy Codex state (`sessions`, `sqlite`, `state_5.sqlite*`) to prevent per-task storage blow-up
- task runtime `CODEX_HOME` is deleted automatically after each worker run (success/failure), so task folders do not keep Codex cache history
- default hardened mode for demos uses `TASK_CONTAINER_NETWORK=none`, empty `TASK_CONTAINER_ENV_PASSTHROUGH`, and mock execution
- real Codex runs require an explicit opt-in: set `CODEX_WORKER_MODE=real`, choose an outbound network mode, and pass only required credentials
- for real task-container execution, prefer `TASK_CONTAINER_CODEX_SANDBOX=danger-full-access`; Docker already constrains the worker to the task runtime root, and this avoids Linux sandbox failures inside nested container execution
- director auto-run is enabled by default (`DIRECTOR_AUTO_RUN_ENABLED=true`) and limits automatic rework loops with `DIRECTOR_AUTO_MAX_ATTEMPTS`
- proactive queue checks are enabled by default (`DIRECTOR_HEARTBEAT_ENABLED=true`) and run every `DIRECTOR_HEARTBEAT_POLL_SECONDS` seconds
- each heartbeat tick dispatches at most `DIRECTOR_HEARTBEAT_MAX_DISPATCH_PER_TICK` tasks and prioritizes recently updated projects
- stale `running` executions are auto-recovered after `CODEX_EXECUTION_TIMEOUT_SECONDS + DIRECTOR_STALE_RUN_GRACE_SECONDS`
- auto-retry is applied only for fresh stale runs within `DIRECTOR_STALE_RUN_AUTO_RETRY_WINDOW_SECONDS` after that threshold
- on API startup, heartbeat performs an immediate orphaned-run recovery pass (`running` runs from the previous process)
- snapshot workspace seeding excludes `.env` and `.env.*` files

## API endpoints available now

- `POST /projects`
- `GET /projects`
- `GET /projects/{id}`
- `POST /projects/{id}/goal`
- `GET /projects/{id}/tasks`
- `GET /projects/{id}/agents`
- `GET /projects/{id}/artifacts`
- `GET /projects/{id}/action-intents`
- `GET /projects/{id}/approvals`
- `GET /projects/{id}/approval-policies`
- `GET /projects/{id}/approval-decisions`
- `GET /projects/{id}/risk-assessments`
- `GET /projects/{id}/reviews`
- `GET /projects/{id}/messages`
- `GET /projects/{id}/events`
- `GET /projects/{id}/runs`
- `GET /projects/{id}/tasks/{taskId}/runtime`
- `GET /projects/{id}/tasks/{taskId}/preflight`
- `GET /projects/{id}/tasks/{taskId}/action-intents`
- `GET /projects/{id}/tasks/{taskId}/reviews`
- `POST /projects/{id}/approvals/{approvalRequestId}/resolve`
- `POST /projects/{id}/action-intents/{actionIntentId}/retry`
- `POST /projects/{id}/policy-checks`
- `POST /projects/{id}/tasks/{taskId}/run`
- `POST /projects/{id}/director/advance`
- `POST /projects/{id}/stream-token`
- `GET /projects/{id}/events/stream`
- `POST /projects/{id}/tasks/{taskId}/actions`
- `POST /task-runs/{id}/cancel`
- `GET /task-runs/{id}/logs`
- `POST /projects/{id}/crm/previews`
- `GET /projects/{id}/crm/previews`
- `GET /projects/{id}/crm/previews/{previewId}`
- `POST /projects/{id}/crm/previews/{previewId}/send`
- `GET /api/integrations/amocrm/status`
- `POST /api/integrations/amocrm/refresh`
- `POST /api/integrations/amocrm/contact-fields/sync`
- `POST /api/integrations/amocrm/secrets`
- `GET /api/integrations/amocrm/callback`

## CRM Bridge V1 (Tallanto -> AMO)

- `CRM_TALLANTO_MODE=mock|http` controls source fetch mode for Tallanto.
- `CRM_AMO_MODE=mock|http` controls destination write mode for AMO.
- `CRM_ANALYSIS_MODE=heuristic|codex` controls preview analysis mode.
- In `mock` mode the bridge is fully local and safe for UI testing.
- In `http` mode set `CRM_TALLANTO_BASE_URL`, `CRM_TALLANTO_API_TOKEN`, `CRM_TALLANTO_STUDENT_PATH`, and either:
  - direct `CRM_AMO_BASE_URL + CRM_AMO_API_TOKEN`, or
  - external OAuth settings `CRM_AMO_OAUTH_REDIRECT_URI + CRM_AMO_OAUTH_SECRETS_URI`.
- Tallanto HTTP mode is now implemented against the real `rest.php` API:
  - auth header: `X-Auth-Token`
  - endpoint path default: `/service/api/rest.php`
  - supported preview lookup modes: `auto`, `contact_id`, `phone`, `email`, `full_name`
  - `auto` currently prioritizes exact contact ID, exact email, normalized phone variants, then name fallback
- Workflow:
  1. Create preview (`POST /projects/{id}/crm/previews`): fetches Tallanto student data, builds canonical payload, and prepares AMO field payload.
  2. Inspect preview in UI/API (`GET /projects/{id}/crm/previews`).
  3. Send selected fields to AMO (`POST /projects/{id}/crm/previews/{previewId}/send`) with optional `field_overrides` for pointwise manual correction before write.
- Safety defaults:
  - empty `selected_fields` does not trigger full write; send is rejected as failed
  - already sent preview cannot be sent again (use a new preview for repeated transfer)
  - in `CRM_AMO_MODE=http`, AMO writes are escalated to human approval policy
  - API responses and CRM artifacts redact sensitive source/canonical payload fields

## External amoCRM OAuth (server callback mode)

Use this mode when amoCRM must call back to your public server, while the rest of the office still runs from your MacBook.

Set in `.env`:

```bash
CRM_AMO_MODE=http
CRM_AMO_BASE_URL=https://educent.amocrm.ru
CRM_AMO_OAUTH_REDIRECT_URI=https://api.fotonai.online/api/integrations/amocrm/callback
CRM_AMO_OAUTH_SECRETS_URI=https://api.fotonai.online/api/integrations/amocrm/secrets
CRM_AMO_OAUTH_SCOPES=crm
CRM_AMO_OAUTH_NAME=AI Office
CRM_AMO_OAUTH_DESCRIPTION=Интеграция AI Office для безопасной записи данных в amoCRM.
CRM_AMO_OAUTH_ACCOUNT_BASE_URL=https://educent.amocrm.ru
```

Then:

1. Deploy the server build and verify:
   - `GET /api/integrations/amocrm/status`
   - `POST /api/integrations/amocrm/secrets`
   - `GET /api/integrations/amocrm/callback`
2. In the amoCRM external integration button/config use:
   - `redirect_uri = https://api.fotonai.online/api/integrations/amocrm/callback`
   - `secrets_uri = https://api.fotonai.online/api/integrations/amocrm/secrets`
3. After authorization, call `POST /api/integrations/amocrm/contact-fields/sync` once.
4. CRM/Calls controlled write will then use the stored OAuth token and resolve custom field IDs from `GET /api/v4/contacts/custom_fields`.

## Local development without Docker

### API

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### API smoke tests

```bash
cd apps/api
pip install -r requirements-dev.txt
pytest
```

### Web

```bash
npm install
npm run dev -w @ai-office/web
```

## Reviewer loop

Codex execution now passes through an automatic reviewer step:

- execution result is persisted as `codex_result`
- task moves from `running` to `review`
- `QAReviewer` produces structured findings with `low/medium/high/critical`
- approved reviews move the task to `done`
- high-risk reviews return the task to `ready` and mark runtime state as `changes_requested`

Director orchestration now auto-runs the queue:

- after goal planning, director starts the top `ready` task automatically
- after each review, director either re-runs the same task (if changes requested) or starts the next `ready` task
- background heartbeat periodically scans projects and continues execution if a `ready` task appears without a direct trigger
- if a task exceeds `DIRECTOR_AUTO_MAX_ATTEMPTS`, director blocks it and requires human intervention
- `POST /projects/{id}/director/advance` can be used as a safe manual nudge when you need to re-check the queue immediately

Human approvals now support inbox resolution:

- pending approval requests can be approved or rejected from the UI or API
- resolved human approvals are reused on retry of the same action and metadata
- rejected human approvals keep the action blocked without creating a fresh pending duplicate

High-risk actions now create executable action intents:

- a blocked human-only action is persisted as an `ActionIntent`
- the intent is linked to the originating task and optional task run
- human approval automatically resumes the intent through a runtime dispatcher and records the outcome as an artifact
- human rejection marks the intent as rejected without manual retry
- failed dispatcher attempts create dedicated `TaskRun` log entries such as `intent:runtime.host_access`
- failed dispatcher attempts can move to `retry_scheduled` with backoff and be resumed via `POST /projects/{id}/action-intents/{actionIntentId}/retry`

Codex workers can also request privileged runtime actions from inside a task run:

- emit a single line in the final worker message using `ACTION_REQUEST: action.key {"json":"payload"}`
- current supported keys are `runtime.install_package`, `runtime.host_access`, and `runtime.secret_write`
- every accepted or blocked request is evaluated by the policy engine and stored as an `ActionIntent` when human approval is required

Task runtime isolation now includes source-aware workspace seeding:

- each task workspace records `source_root_path`, `workspace_mode`, and `sync_status`
- `snapshot-copy` is the default safe fallback when the source tree is not a writable git repository
- `git-worktree` is used only when the source tree is a writable git repository and `git` is available
- runtime metadata exposes source/workspace mount modes and network isolation hints in the UI
- when `TASK_CONTAINER_DRIVER=docker`, execution happens inside a dedicated per-task container and runtime metadata exposes `container_name`, `container_id`, and `container_workdir`
- task containers now auto-build from `apps/task-runner/Dockerfile` if `TASK_CONTAINER_IMAGE` is missing and `TASK_CONTAINER_IMAGE_AUTO_BUILD=true`
- task image includes `Codex CLI`, `git`, and `python3` for real engineering runs in containerized mode
- task preflight checks validate Docker/image/credentials/runtime writability before run start
- watchdog marks hanging runs as `timed_out`, cancels run execution, and cleans task containers
- operator can cancel running tasks via `POST /task-runs/{id}/cancel`
- each completed task now emits `workspace_change_summary` artifact with created/modified/deleted files against seeded baseline

## What is intentionally not implemented yet

- Multi-page UI with route-level navigation
- Dedicated history pages and filtering for event/message timelines
- Verified `git-worktree` flow in a writable git repository
- External reviewer CLI integration such as Claude Code

Those come in later stages after the core API and UI skeleton are stable.
