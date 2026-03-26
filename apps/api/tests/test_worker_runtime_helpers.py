import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.codex_worker as codex_worker_module  # noqa: E402
import app.preflight as preflight_module  # noqa: E402
import app.task_container as task_container_module  # noqa: E402
from app.codex_worker import (  # noqa: E402
    _append_stdout,
    _blocking_preflight_messages,
    _codex_home_copy_script_lines,
    _format_change_list,
    _parse_action_requests,
    _task_run_age_seconds,
    _workspace_context_prompt,
)
from app.preflight import (  # noqa: E402
    PreflightCheck,
    _check_process_runtime,
    _resolve_dockerfile_path as resolve_preflight_dockerfile_path,
    evaluate_task_preflight,
)
from app.task_container import (  # noqa: E402
    BuildError,
    _build_image_error_detail,
    _resolve_dockerfile_path as resolve_task_container_dockerfile_path,
    _task_container_environment,
    _task_container_volumes,
    container_name_for_task,
    container_runtime_file_path,
    container_workspace_path,
    container_workdir,
    destroy_task_container,
    ensure_task_container,
    run_command_in_task_container,
)


def test_codex_worker_helper_functions_cover_parsing_and_output(monkeypatch):
    assert _format_change_list("Modified", ["a.py", "b.py"]).startswith("### Modified")
    assert "- `a.py`" in _format_change_list("Modified", ["a.py"])
    assert "(none)" in _format_change_list("Created", [])

    requests, errors = _parse_action_requests(
        '\n'.join(
            [
                'ACTION_REQUEST: runtime.install_package {"registry":"pypi.org","package_name":"pytest"}',
                'ACTION_REQUEST: runtime.host_access {"target_path":"/etc/hosts"}',
                "ACTION_REQUEST: runtime.bad {oops}",
            ]
        )
    )
    assert len(requests) == 2
    assert requests[0][0] == "runtime.install_package"
    assert errors and "runtime.bad" in errors[0]

    task_run = SimpleNamespace(stdout=None)
    _append_stdout(task_run, "hello")
    _append_stdout(task_run, " world")
    assert task_run.stdout == "hello world"

    preflight = SimpleNamespace(
        checks=[
            PreflightCheck("ok", "pass", "ok"),
            PreflightCheck("bad", "fail", "broken", blocking=True),
        ]
    )
    assert _blocking_preflight_messages(preflight) == ["broken"]

    monkeypatch.setattr(
        codex_worker_module,
        "utc_now",
        lambda: datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
    )
    age = _task_run_age_seconds(SimpleNamespace(started_at=datetime(2026, 3, 20, 11, 59)))
    assert age == 60.0

    prompt = _workspace_context_prompt(
        SimpleNamespace(name="Office", latest_goal_text="Собрать модуль", id="p1"),
        SimpleNamespace(
            title="Сделать API",
            brief="Нужен endpoint",
            acceptance_criteria=["Есть маршрут", "Есть тест"],
            assigned_agent=SimpleNamespace(role="BackendEngineer"),
        ),
    )
    assert "Assigned role: BackendEngineer" in prompt
    assert "Есть маршрут" in prompt


def test_codex_home_copy_script_and_task_container_helpers(monkeypatch, tmp_path):
    monkeypatch.setattr(
        codex_worker_module,
        "settings",
        SimpleNamespace(
            task_container_codex_home_container_path="/codex-src",
            task_container_codex_home_runtime_path="/codex-runtime",
            task_container_codex_home_copy_allowlist=["auth.json", "config.toml"],
        ),
    )
    script_lines = _codex_home_copy_script_lines()
    assert any("auth.json" in line for line in script_lines)
    assert any("state_5.sqlite" in line for line in script_lines)

    monkeypatch.setattr(
        task_container_module,
        "settings",
        SimpleNamespace(
            task_container_workdir="/task-root",
            task_container_name_prefix="office-task",
            task_container_codex_home_host_path="/host/codex",
            task_container_codex_home_container_path="/container/codex",
            task_container_env_passthrough=["OPENAI_API_KEY", "MISSING_ENV"],
            task_container_image_dockerfile="docker/Dockerfile.task",
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    assert container_workdir() == "/task-root"
    assert container_workspace_path() == "/task-root/workspace"
    assert container_runtime_file_path("run.sh") == "/task-root/run.sh"
    assert container_name_for_task(SimpleNamespace(id="abcdef1234567890")) == "office-task-abcdef123456"

    volumes = _task_container_volumes(tmp_path)
    assert volumes[str(tmp_path)]["bind"] == "/task-root"
    assert volumes["/host/codex"]["mode"] == "ro"
    assert _task_container_environment() == {"OPENAI_API_KEY": "secret"}


def test_task_container_dockerfile_resolution_and_build_error_detail(monkeypatch, tmp_path):
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    dockerfile = docker_dir / "Dockerfile.task"
    dockerfile.write_text("FROM python:3.12", encoding="utf-8")

    monkeypatch.setattr(
        task_container_module,
        "settings",
        SimpleNamespace(
            task_container_image_dockerfile="docker/Dockerfile.task",
            task_container_workdir="/task-root",
            task_container_name_prefix="office-task",
            task_container_codex_home_host_path=None,
            task_container_env_passthrough=[],
        ),
    )
    assert resolve_task_container_dockerfile_path(tmp_path) == "docker/Dockerfile.task"
    assert resolve_preflight_dockerfile_path(tmp_path, "docker/Dockerfile.task") == dockerfile

    task_container_module.settings.task_container_image_dockerfile = str(dockerfile)
    assert resolve_task_container_dockerfile_path(tmp_path) == "docker/Dockerfile.task"

    outside = tmp_path.parent / "outside.Dockerfile"
    outside.write_text("FROM busybox", encoding="utf-8")
    task_container_module.settings.task_container_image_dockerfile = str(outside)
    with pytest.raises(RuntimeError):
        resolve_task_container_dockerfile_path(tmp_path)

    build_error = BuildError(
        "failed",
        build_log=[{"stream": "step 1\n"}, {"error": "boom"}],
    )
    assert _build_image_error_detail(build_error) == "boom"
    assert _build_image_error_detail(RuntimeError("plain failure")) == "plain failure"


def test_task_container_process_fallback_and_execution_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(task_container_module, "container_runtime_enabled", lambda: False)
    environment = SimpleNamespace(
        runtime_status="pending",
        container_name="old-name",
        container_id="old-id",
        container_workdir="/tmp/work",
        runtime_kind="process",
    )
    updated = ensure_task_container(
        SimpleNamespace(id="project-1"),
        SimpleNamespace(id="task-1"),
        SimpleNamespace(root_path=str(tmp_path / "runtime")),
        environment,
    )
    assert updated.runtime_status == "process-fallback"
    assert updated.container_name is None

    destroy_task_container(SimpleNamespace(container_name=None))

    with pytest.raises(RuntimeError):
        run_command_in_task_container(
            SimpleNamespace(container_name=None),
            SimpleNamespace(stdout=None),
            "echo hi",
            timeout_seconds=10,
        )

    monkeypatch.setattr(task_container_module, "container_runtime_enabled", lambda: True)
    with pytest.raises(RuntimeError):
        run_command_in_task_container(
            SimpleNamespace(container_name=None),
            SimpleNamespace(stdout=None),
            "echo hi",
            timeout_seconds=10,
        )


def test_preflight_process_runtime_and_evaluation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        preflight_module,
        "settings",
        SimpleNamespace(
            codex_worker_mode="mock",
            codex_cli_path="codex",
            codex_execution_timeout_seconds=120,
        ),
    )
    checks = _check_process_runtime()
    assert checks[0].status == "pass"
    assert checks[1].status == "warn"

    monkeypatch.setattr(preflight_module, "container_runtime_enabled", lambda: False)
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    workspace = SimpleNamespace(
        workspace_path=str(workspace_path),
        root_path=str(tmp_path / "runtime-root"),
    )
    environment = SimpleNamespace(runtime_kind="process", base_image="local")
    result = evaluate_task_preflight(workspace, environment)
    assert result.ready is True
    assert any(check.key == "execution.timeout" for check in result.checks)

    preflight_module.settings.codex_worker_mode = "real"
    monkeypatch.setattr(preflight_module, "shutil", SimpleNamespace(which=lambda value: None))
    preflight_module.settings.codex_cli_path = "/missing/codex"
    failing_checks = _check_process_runtime()
    assert failing_checks[0].status == "fail"

    monkeypatch.setattr(preflight_module, "shutil", SimpleNamespace(which=lambda value: "/usr/bin/codex"))
    preflight_module.settings.codex_cli_path = "codex"
    available_checks = _check_process_runtime()
    assert available_checks[0].status == "pass"
