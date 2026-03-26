import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.director_heartbeat as director_heartbeat_module  # noqa: E402
import app.preflight as preflight_module  # noqa: E402
import app.task_container as task_container_module  # noqa: E402
from app.db import Base  # noqa: E402
from app.director_heartbeat import DirectorHeartbeatService, tick_director_queue_once  # noqa: E402
from app.models import Agent, EventLog, Project, Task, TaskEnvironment, TaskRun, TaskWorkspace  # noqa: E402
from app.preflight import _check_container_runtime, _check_workspace  # noqa: E402
from app.task_container import (  # noqa: E402
    DockerException,
    ImageNotFound,
    NotFound,
    _docker_client,
    _ensure_task_image,
    _remove_existing_container,
    destroy_task_container,
    ensure_task_container,
    run_command_in_task_container,
)


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


class FakeContainer:
    def __init__(self, container_id="container-1"):
        self.id = container_id
        self.reloaded = False
        self.removed = False

    def reload(self):
        self.reloaded = True

    def remove(self, force=False):
        self.removed = force


class FakeApi:
    def __init__(self, exec_output=b"worker output", exit_code=0):
        self.exec_output = exec_output
        self.exit_code = exit_code
        self.exec_calls = []

    def exec_create(self, container_id, command, **kwargs):
        self.exec_calls.append((container_id, command, kwargs))
        return {"Id": "exec-1"}

    def exec_start(self, exec_id, **kwargs):
        return self.exec_output

    def exec_inspect(self, exec_id):
        return {"ExitCode": self.exit_code}


class FakeDockerClient:
    def __init__(self, *, image_missing=False, ping_error=None, exec_output=b"worker output", exit_code=0):
        self.closed = False
        self.image_missing = image_missing
        self.ping_error = ping_error
        self.images = SimpleNamespace(get=self._get_image, build=self._build_image)
        self.containers = SimpleNamespace(get=self._get_container, run=self._run_container)
        self.api = FakeApi(exec_output=exec_output, exit_code=exit_code)
        self.container = FakeContainer()
        self.built = []
        self.run_kwargs = None

    def _get_image(self, image_name):
        if self.image_missing:
            raise ImageNotFound("missing")
        return {"id": image_name}

    def _build_image(self, **kwargs):
        self.built.append(kwargs)
        self.image_missing = False
        return ({"id": kwargs["tag"]}, [])

    def _get_container(self, name):
        if name == "missing":
            raise NotFound("missing")
        return self.container

    def _run_container(self, **kwargs):
        self.run_kwargs = kwargs
        return self.container

    def ping(self):
        if self.ping_error is not None:
            raise self.ping_error
        return True

    def close(self):
        self.closed = True


def test_task_container_docker_client_and_image_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(task_container_module, "docker", None)
    with pytest.raises(RuntimeError):
        _docker_client()

    monkeypatch.setattr(
        task_container_module,
        "docker",
        SimpleNamespace(from_env=lambda timeout: (_ for _ in ()).throw(DockerException("daemon down"))),
    )
    with pytest.raises(RuntimeError):
        _docker_client()

    build_context = tmp_path / "docker"
    build_context.mkdir()
    dockerfile = build_context / "Dockerfile.task"
    dockerfile.write_text("FROM busybox", encoding="utf-8")
    monkeypatch.setattr(
        task_container_module,
        "settings",
        SimpleNamespace(
            task_container_image="ai-office-task:latest",
            task_container_image_auto_build=True,
            task_container_image_build_context=str(build_context),
            task_container_image_dockerfile="Dockerfile.task",
            task_container_workdir="/task",
            task_container_name_prefix="ai-office-task",
            task_container_codex_home_host_path=None,
            task_container_codex_home_container_path="/codex-source",
            task_container_env_passthrough=(),
            task_container_network="none",
            task_container_driver="docker",
        ),
    )

    fake_client = FakeDockerClient(image_missing=True)
    _ensure_task_image(fake_client)
    assert fake_client.built[0]["tag"] == "ai-office-task:latest"

    task_container_module.settings.task_container_image_auto_build = False
    with pytest.raises(RuntimeError):
        _ensure_task_image(FakeDockerClient(image_missing=True))

    _remove_existing_container(fake_client, "container-1")
    assert fake_client.container.removed is True
    _remove_existing_container(fake_client, "missing")


def test_task_container_provision_destroy_and_exec(monkeypatch, tmp_path):
    fake_client = FakeDockerClient()
    monkeypatch.setattr(task_container_module, "container_runtime_enabled", lambda: True)
    monkeypatch.setattr(task_container_module, "_docker_client", lambda **kwargs: fake_client)
    monkeypatch.setattr(task_container_module, "_ensure_task_image", lambda client: None)
    monkeypatch.setattr(task_container_module, "_remove_existing_container", lambda client, name: None)
    monkeypatch.setattr(
        task_container_module,
        "settings",
        SimpleNamespace(
            task_container_driver="docker",
            task_container_image="ai-office-task:latest",
            task_container_workdir="/task",
            task_container_name_prefix="ai-office-task",
            task_container_codex_home_host_path="/host/codex",
            task_container_codex_home_container_path="/container/codex",
            task_container_env_passthrough=("OPENAI_API_KEY",),
            task_container_network="none",
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    environment = SimpleNamespace(
        runtime_status="pending",
        runtime_kind="task-container",
        base_image="",
        container_name=None,
        container_id=None,
        container_workdir=None,
        workspace_mount_mode=None,
        network_mode=None,
        mounts=[],
    )
    workspace = SimpleNamespace(root_path=str(tmp_path / "runtime"))
    task = SimpleNamespace(id="abcdef1234567890")

    updated = ensure_task_container(SimpleNamespace(id="project-1"), task, workspace, environment)
    assert updated.runtime_status == "container-ready"
    assert updated.container_name == "ai-office-task-abcdef123456"
    assert updated.container_id == "container-1"
    assert fake_client.run_kwargs["network_disabled"] is True
    assert fake_client.run_kwargs["environment"] == {"OPENAI_API_KEY": "secret"}

    task_run = SimpleNamespace(stdout=None)
    exit_code = run_command_in_task_container(
        updated,
        task_run,
        "echo hi",
        timeout_seconds=10,
    )
    assert exit_code == 0
    assert "worker output" in task_run.stdout

    destroy_task_container(updated)
    assert fake_client.closed is True


def test_preflight_workspace_and_container_runtime_branches(monkeypatch, tmp_path):
    workspace = SimpleNamespace(
        workspace_path=str(tmp_path / "missing-workspace"),
        root_path=str(tmp_path / "runtime-root"),
    )
    monkeypatch.setattr(preflight_module, "_is_writable_directory", lambda path: False)
    checks = _check_workspace(workspace)
    assert [item.status for item in checks] == ["fail", "fail"]

    monkeypatch.setattr(preflight_module, "docker", None)
    container_checks = _check_container_runtime(workspace, SimpleNamespace(runtime_kind="task-container", base_image="img"))
    assert container_checks[0].key == "docker.sdk"

    build_context = tmp_path / "build"
    build_context.mkdir()
    dockerfile = build_context / "Dockerfile"
    dockerfile.write_text("FROM busybox", encoding="utf-8")
    monkeypatch.setattr(
        preflight_module,
        "settings",
        SimpleNamespace(
            task_container_image="ai-office-task:latest",
            task_container_image_build_context=str(build_context),
            task_container_image_dockerfile="Dockerfile",
            task_container_image_auto_build=True,
            codex_worker_mode="real",
            task_container_network="bridge",
            task_container_codex_home_host_path=None,
            task_container_env_passthrough=("OPENAI_API_KEY",),
            codex_execution_timeout_seconds=120,
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr(preflight_module, "_is_writable_directory", lambda path: True)
    monkeypatch.setattr(preflight_module, "_api_runtime_is_containerized", lambda: False)
    fake_client = FakeDockerClient(image_missing=True)
    monkeypatch.setattr(preflight_module, "docker", SimpleNamespace(from_env=lambda timeout: fake_client))
    container_checks = _check_container_runtime(
        SimpleNamespace(root_path=str(tmp_path / "runtime-root")),
        SimpleNamespace(runtime_kind="task-container", base_image="img"),
    )
    check_map = {item.key: item for item in container_checks}
    assert check_map["docker.daemon"].status == "pass"
    assert check_map["task_image.available"].status == "warn"
    assert check_map["codex.credentials"].status == "pass"
    assert check_map["codex_home.writable"].status == "pass"

    preflight_module.settings.task_container_network = "none"
    network_checks = _check_container_runtime(
        SimpleNamespace(root_path=str(tmp_path / "runtime-root")),
        SimpleNamespace(runtime_kind="task-container", base_image="img"),
    )
    assert any(item.key == "task_network.mode" and item.status == "fail" for item in network_checks)


def test_director_heartbeat_service_and_tick_dispatch(monkeypatch):
    monkeypatch.setattr(
        director_heartbeat_module,
        "settings",
        SimpleNamespace(
            director_auto_run_enabled=True,
            director_heartbeat_enabled=True,
            director_heartbeat_max_dispatch_per_tick=2,
        ),
    )

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=None):
            self.target = target
            self.started = False
            self.joined = False

        def start(self):
            self.started = True

        def is_alive(self):
            return self.started and not self.joined

        def join(self, timeout=None):
            self.joined = True

    monkeypatch.setattr(director_heartbeat_module.threading, "Thread", FakeThread)
    service = DirectorHeartbeatService(poll_seconds=3)
    service.start()
    assert service.is_running() is True
    service.start()
    service.stop()
    assert service.is_running() is False

    started_runs = []

    class FakeScalarResult:
        def __init__(self, values):
            self._values = values

        def all(self):
            return list(self._values)

    class FakeSession:
        def __init__(self):
            self.closed = False

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            self.closed = True

        def scalars(self, query):
            return FakeScalarResult(["project-1"])

        def get(self, model, object_id):
            return SimpleNamespace(id=object_id)

    monkeypatch.setattr(director_heartbeat_module, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        director_heartbeat_module,
        "recover_stale_task_runs",
        lambda session, trigger, stale_after_seconds=None: [("project-stale", "task-stale", "run-stale")],
    )
    monkeypatch.setattr(
        director_heartbeat_module,
        "dispatch_director_next_ready_task",
        lambda session, project, trigger: SimpleNamespace(
            task_id="task-1",
            task_run_id="run-1",
            task_title="Task 1",
        ),
    )
    monkeypatch.setattr(
        director_heartbeat_module,
        "start_codex_execution",
        lambda project_id, task_id, task_run_id: started_runs.append((project_id, task_id, task_run_id)),
    )

    dispatched = tick_director_queue_once(trigger="test")
    assert dispatched == 2
    assert ("project-stale", "task-stale", "run-stale") in started_runs
    assert ("project-1", "task-1", "run-1") in started_runs


def test_preflight_process_mode_and_additional_heartbeat_branches(monkeypatch, tmp_path):
    workspace_root = tmp_path / "runtime-root"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    workspace = SimpleNamespace(workspace_path=str(workspace_dir), root_path=str(workspace_root))

    monkeypatch.setattr(preflight_module, "_is_writable_directory", lambda path: True)
    workspace_checks = _check_workspace(workspace)
    assert [item.status for item in workspace_checks] == ["pass", "pass"]

    monkeypatch.setattr(
        preflight_module,
        "settings",
        SimpleNamespace(
            codex_worker_mode="real",
            codex_cli_path="/missing/codex",
            codex_execution_timeout_seconds=0,
        ),
    )
    monkeypatch.setattr(preflight_module, "container_runtime_enabled", lambda: False)
    monkeypatch.setattr(preflight_module.shutil, "which", lambda path: None)
    process_result = preflight_module.evaluate_task_preflight(
        workspace,
        SimpleNamespace(runtime_kind="process", base_image="local"),
    )
    assert process_result.ready is False
    assert "blocking issue" in process_result.summary
    assert any(item.key == "codex.cli" and item.status == "fail" for item in process_result.checks)
    assert any(item.key == "execution.timeout" and item.status == "fail" for item in process_result.checks)

    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setattr(
        preflight_module,
        "settings",
        SimpleNamespace(
            task_container_image="ai-office-task:latest",
            task_container_image_build_context=str(tmp_path),
            task_container_image_dockerfile="Dockerfile",
            task_container_image_auto_build=False,
            codex_worker_mode="real",
            task_container_network="bridge",
            task_container_codex_home_host_path=str(codex_home),
            task_container_env_passthrough=(),
            codex_execution_timeout_seconds=120,
            codex_cli_path="codex",
        ),
    )
    monkeypatch.setattr(preflight_module, "docker", SimpleNamespace(from_env=lambda timeout: FakeDockerClient()))
    container_result = _check_container_runtime(
        SimpleNamespace(root_path=str(workspace_root)),
        SimpleNamespace(runtime_kind="task-container", base_image="img"),
    )
    assert any(item.key == "codex.credentials" and item.status == "pass" for item in container_result)
    assert any(item.key == "runtime.kind" and item.status == "pass" for item in container_result)

    monkeypatch.setattr(
        director_heartbeat_module,
        "settings",
        SimpleNamespace(
            director_auto_run_enabled=False,
            director_heartbeat_enabled=False,
            director_heartbeat_max_dispatch_per_tick=1,
        ),
    )
    service = DirectorHeartbeatService(poll_seconds=1)
    service.start()
    assert service.is_running() is False
    assert tick_director_queue_once(trigger="disabled") == 0

    logged = []
    monkeypatch.setattr(director_heartbeat_module, "tick_director_queue_once", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(director_heartbeat_module.logger, "exception", lambda message: logged.append(message))
    service._safe_tick()
    assert logged == ["Director heartbeat tick failed"]


def test_preflight_container_edge_cases_and_heartbeat_loop_paths(monkeypatch, tmp_path):
    absolute_dockerfile = preflight_module._resolve_dockerfile_path(tmp_path, "/tmp/Dockerfile")
    assert str(absolute_dockerfile) == "/tmp/Dockerfile"

    monkeypatch.setattr(
        preflight_module,
        "docker",
        SimpleNamespace(from_env=lambda timeout: (_ for _ in ()).throw(DockerException("daemon down"))),
    )
    docker_fail_checks = _check_container_runtime(
        SimpleNamespace(root_path=str(tmp_path / "runtime-root")),
        SimpleNamespace(runtime_kind="task-container", base_image="img"),
    )
    assert docker_fail_checks[0].key == "docker.daemon"
    assert docker_fail_checks[0].status == "fail"

    failing_client = FakeDockerClient(ping_error=DockerException("ping failed"))
    failing_client.images.get = lambda image_name: (_ for _ in ()).throw(DockerException("inspect failed"))
    monkeypatch.setattr(preflight_module, "docker", SimpleNamespace(from_env=lambda timeout: failing_client))
    monkeypatch.setattr(
        preflight_module,
        "settings",
        SimpleNamespace(
            task_container_image="ai-office-task:latest",
            task_container_image_build_context=str(tmp_path),
            task_container_image_dockerfile="Dockerfile",
            task_container_image_auto_build=False,
            codex_worker_mode="real",
            task_container_network="bridge",
            task_container_codex_home_host_path="/missing/codex",
            task_container_env_passthrough=(),
            codex_execution_timeout_seconds=120,
        ),
    )
    monkeypatch.setattr(preflight_module, "_api_runtime_is_containerized", lambda: True)
    monkeypatch.setattr(preflight_module, "_is_writable_directory", lambda path: False)
    container_checks = _check_container_runtime(
        SimpleNamespace(root_path=str(tmp_path / "runtime-root")),
        SimpleNamespace(runtime_kind="task-container", base_image="img"),
    )
    check_map = {item.key: item for item in container_checks}
    assert check_map["docker.daemon"].status == "fail"
    assert check_map["task_image.available"].status == "fail"
    assert check_map["codex.credentials"].status == "warn"
    assert check_map["codex_home.writable"].status == "fail"

    monkeypatch.setattr(
        director_heartbeat_module,
        "settings",
        SimpleNamespace(
            director_auto_run_enabled=True,
            director_heartbeat_enabled=True,
            director_heartbeat_max_dispatch_per_tick=1,
        ),
    )
    service = DirectorHeartbeatService(poll_seconds=1)
    heartbeat_ticks = []
    monkeypatch.setattr(service, "_safe_tick", lambda recover_immediately=False: heartbeat_ticks.append(recover_immediately))

    class FakeStopEvent:
        def __init__(self):
            self.calls = 0

        def wait(self, timeout):
            self.calls += 1
            return self.calls > 1

    service._stop_event = FakeStopEvent()
    service._run_loop()
    assert heartbeat_ticks == [True, False]

    class FakeScalarResult:
        def __init__(self, values):
            self._values = values

        def all(self):
            return list(self._values)

    class FakeSession:
        def __init__(self):
            self.closed = False
            self.rollbacks = 0

        def commit(self):
            return None

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closed = True

        def scalars(self, query):
            return FakeScalarResult(["missing-project", "project-2"])

        def get(self, model, object_id):
            if object_id == "missing-project":
                return None
            return SimpleNamespace(id=object_id)

    fake_session = FakeSession()
    monkeypatch.setattr(director_heartbeat_module, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(
        director_heartbeat_module,
        "recover_stale_task_runs",
        lambda session, trigger, stale_after_seconds=None: [("project-stale", "task-stale", "run-stale")],
    )
    heartbeat_logs = []
    monkeypatch.setattr(director_heartbeat_module.logger, "exception", lambda message, *args: heartbeat_logs.append(message))
    monkeypatch.setattr(
        director_heartbeat_module,
        "dispatch_director_next_ready_task",
        lambda session, project, trigger: (_ for _ in ()).throw(RuntimeError("dispatch failed")),
    )
    started_runs = []
    monkeypatch.setattr(
        director_heartbeat_module,
        "start_codex_execution",
        lambda project_id, task_id, task_run_id: started_runs.append((project_id, task_id, task_run_id)),
    )
    dispatched = tick_director_queue_once(trigger="heartbeat")
    assert dispatched == 1
    assert started_runs == []
    assert fake_session.rollbacks == 0
    assert heartbeat_logs == []
