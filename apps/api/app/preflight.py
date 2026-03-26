from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.models import TaskEnvironment, TaskWorkspace
from app.task_container import container_runtime_enabled

try:
    import docker
    from docker.errors import DockerException, ImageNotFound
except ImportError:  # pragma: no cover - depends on runtime dependencies
    docker = None

    class DockerException(RuntimeError):
        pass

    class ImageNotFound(DockerException):
        pass


settings = get_settings()


def _is_image_not_found_exception(exc: Exception) -> bool:
    return exc.__class__.__name__ == "ImageNotFound"


def _api_runtime_is_containerized() -> bool:
    return Path("/.dockerenv").exists()


@dataclass(frozen=True)
class PreflightCheck:
    key: str
    status: str
    message: str
    blocking: bool = False


@dataclass(frozen=True)
class TaskPreflightResult:
    ready: bool
    checks: list[PreflightCheck]
    summary: str


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".preflight_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _check_workspace(workspace: TaskWorkspace) -> list[PreflightCheck]:
    workspace_path = Path(workspace.workspace_path)
    runtime_root = Path(workspace.root_path)
    checks: list[PreflightCheck] = []

    if workspace_path.exists():
        checks.append(
            PreflightCheck(
                key="workspace.exists",
                status="pass",
                message=f"Task workspace is available at {workspace_path}.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                key="workspace.exists",
                status="fail",
                message=f"Task workspace path does not exist: {workspace_path}.",
                blocking=True,
            )
        )

    if _is_writable_directory(runtime_root):
        checks.append(
            PreflightCheck(
                key="runtime_root.writable",
                status="pass",
                message=f"Runtime root is writable at {runtime_root}.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                key="runtime_root.writable",
                status="fail",
                message=f"Runtime root is not writable: {runtime_root}.",
                blocking=True,
            )
        )
    return checks


def _resolve_dockerfile_path(build_context: Path, dockerfile_value: str) -> Path:
    dockerfile = Path(dockerfile_value)
    if dockerfile.is_absolute():
        return dockerfile
    return build_context / dockerfile


def _check_container_runtime(workspace: TaskWorkspace, environment: TaskEnvironment) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    if docker is None:
        checks.append(
            PreflightCheck(
                key="docker.sdk",
                status="fail",
                message="Python Docker SDK is not installed in API runtime.",
                blocking=True,
            )
        )
        return checks

    try:
        client = docker.from_env(timeout=20)
    except Exception as exc:
        checks.append(
            PreflightCheck(
                key="docker.daemon",
                status="fail",
                message=f"Docker daemon is unavailable: {exc}",
                blocking=True,
            )
        )
        return checks

    try:
        try:
            client.ping()
            checks.append(
                PreflightCheck(
                    key="docker.daemon",
                    status="pass",
                    message="Docker daemon is reachable from API runtime.",
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="docker.daemon",
                    status="fail",
                    message=f"Docker daemon ping failed: {exc}",
                    blocking=True,
                )
            )

        image_name = settings.task_container_image
        try:
            client.images.get(image_name)
            checks.append(
                PreflightCheck(
                    key="task_image.available",
                    status="pass",
                    message=f"Task container image is available: {image_name}.",
                )
            )
        except Exception as exc:
            if not _is_image_not_found_exception(exc):
                checks.append(
                    PreflightCheck(
                        key="task_image.available",
                        status="fail",
                        message=f"Failed to inspect task image {image_name}: {exc}",
                        blocking=True,
                    )
                )
                image_name = None
            else:
                build_context = Path(settings.task_container_image_build_context)
                dockerfile = _resolve_dockerfile_path(
                    build_context,
                    settings.task_container_image_dockerfile,
                )
                if settings.task_container_image_auto_build and dockerfile.exists():
                    checks.append(
                        PreflightCheck(
                            key="task_image.available",
                            status="warn",
                            message=(
                                f"Task image {image_name} is missing and will be auto-built from "
                                f"{dockerfile} on first run."
                            ),
                        )
                    )
                else:
                    checks.append(
                        PreflightCheck(
                            key="task_image.available",
                            status="fail",
                            message=(
                                f"Task image {image_name} is missing and auto-build is not ready "
                                f"(context={build_context}, dockerfile={dockerfile})."
                            ),
                            blocking=True,
                        )
                    )
    finally:
        client.close()

    if settings.codex_worker_mode == "real" and settings.task_container_network == "none":
        checks.append(
            PreflightCheck(
                key="task_network.mode",
                status="fail",
                message=(
                    "TASK_CONTAINER_NETWORK=none blocks outbound API calls required for real "
                    "Codex execution."
                ),
                blocking=True,
            )
        )
    else:
        checks.append(
            PreflightCheck(
                key="task_network.mode",
                status="pass",
                message=f"Task container network mode is {settings.task_container_network}.",
            )
        )

    codex_home_source = settings.task_container_codex_home_host_path
    if settings.codex_worker_mode == "real":
        has_env_credentials = (
            "OPENAI_API_KEY" in settings.task_container_env_passthrough
            and bool(os.getenv("OPENAI_API_KEY"))
        )
        if not codex_home_source and not has_env_credentials:
            checks.append(
                PreflightCheck(
                    key="codex.credentials",
                    status="fail",
                    message=(
                        "No Codex credential source configured. Set "
                        "TASK_CONTAINER_CODEX_HOME_HOST_PATH or provide OPENAI_API_KEY "
                        "via TASK_CONTAINER_ENV_PASSTHROUGH."
                    ),
                    blocking=True,
                )
            )
        elif not codex_home_source and has_env_credentials:
            checks.append(
                PreflightCheck(
                    key="codex.credentials",
                    status="pass",
                    message=(
                        "OPENAI_API_KEY is configured through task container env passthrough."
                    ),
                )
            )
        else:
            source_path = Path(codex_home_source)
            if source_path.exists():
                checks.append(
                    PreflightCheck(
                        key="codex.credentials",
                        status="pass",
                        message=f"Codex credential source is available at {source_path}.",
                    )
                )
            elif _api_runtime_is_containerized():
                checks.append(
                    PreflightCheck(
                        key="codex.credentials",
                        status="warn",
                        message=(
                            "Credential host path is not visible inside API container; "
                            "validation deferred to Docker runtime."
                        ),
                    )
                )
            else:
                checks.append(
                    PreflightCheck(
                        key="codex.credentials",
                        status="fail",
                        message=f"Codex credential source path does not exist: {source_path}.",
                        blocking=True,
                    )
                )
    else:
        checks.append(
            PreflightCheck(
                key="codex.credentials",
                status="pass",
                message="Credentials check skipped in mock worker mode.",
            )
        )

    runtime_codex_home = Path(workspace.root_path) / ".codex"
    if _is_writable_directory(runtime_codex_home):
        checks.append(
            PreflightCheck(
                key="codex_home.writable",
                status="pass",
                message=f"Writable CODEX_HOME runtime path is available at {runtime_codex_home}.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                key="codex_home.writable",
                status="fail",
                message=f"CODEX_HOME runtime path is not writable: {runtime_codex_home}.",
                blocking=True,
            )
        )

    if environment.runtime_kind == "task-container":
        checks.append(
            PreflightCheck(
                key="runtime.kind",
                status="pass",
                message=(
                    f"Task runtime kind is {environment.runtime_kind} with base image "
                    f"{environment.base_image}."
                ),
            )
        )
    return checks


def _check_process_runtime() -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    if settings.codex_worker_mode == "real":
        codex_cli = settings.codex_cli_path
        if shutil.which(codex_cli) or Path(codex_cli).exists():
            checks.append(
                PreflightCheck(
                    key="codex.cli",
                    status="pass",
                    message=f"Codex CLI is available at {codex_cli}.",
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    key="codex.cli",
                    status="fail",
                    message=f"Codex CLI is not available at {codex_cli}.",
                    blocking=True,
                )
            )
    else:
        checks.append(
            PreflightCheck(
                key="codex.cli",
                status="pass",
                message="Codex CLI check skipped in mock worker mode.",
            )
        )

    checks.append(
        PreflightCheck(
            key="runtime.kind",
            status="warn",
            message="Runtime driver is process mode; isolation is weaker than task-container mode.",
        )
    )
    return checks


def evaluate_task_preflight(
    workspace: TaskWorkspace,
    environment: TaskEnvironment,
) -> TaskPreflightResult:
    checks = _check_workspace(workspace)

    if container_runtime_enabled():
        checks.extend(_check_container_runtime(workspace, environment))
    else:
        checks.extend(_check_process_runtime())

    if settings.codex_execution_timeout_seconds <= 0:
        checks.append(
            PreflightCheck(
                key="execution.timeout",
                status="fail",
                message="CODEX_EXECUTION_TIMEOUT_SECONDS must be greater than zero.",
                blocking=True,
            )
        )
    else:
        checks.append(
            PreflightCheck(
                key="execution.timeout",
                status="pass",
                message=(
                    f"Execution timeout is {settings.codex_execution_timeout_seconds} seconds."
                ),
            )
        )

    blocking_failures = [check for check in checks if check.status == "fail" and check.blocking]
    ready = len(blocking_failures) == 0
    summary = (
        "Task runtime preflight passed."
        if ready
        else f"Task runtime preflight failed with {len(blocking_failures)} blocking issue(s)."
    )
    return TaskPreflightResult(ready=ready, checks=checks, summary=summary)
