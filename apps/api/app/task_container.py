from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.models import Project, Task, TaskEnvironment, TaskRun, TaskWorkspace

try:
    import docker
    from docker.errors import APIError, BuildError, DockerException, ImageNotFound, NotFound
except ImportError:  # pragma: no cover - exercised in container-enabled runtime only
    docker = None

    class DockerException(RuntimeError):
        pass

    class APIError(DockerException):
        def __init__(self, message: str) -> None:
            super().__init__(message)
            self.explanation = message

    class NotFound(DockerException):
        pass

    class ImageNotFound(DockerException):
        pass

    class BuildError(DockerException):
        def __init__(self, message: str, build_log=None) -> None:
            super().__init__(message)
            self.build_log = build_log or []


settings = get_settings()


def container_runtime_enabled() -> bool:
    return settings.task_container_driver == "docker"


def container_workdir() -> str:
    return settings.task_container_workdir.rstrip("/") or "/task"


def container_workspace_path() -> str:
    return f"{container_workdir()}/workspace"


def container_runtime_file_path(file_name: str) -> str:
    return f"{container_workdir()}/{file_name}"


def container_name_for_task(task: Task) -> str:
    return f"{settings.task_container_name_prefix}-{task.id[:12]}"


def _docker_client(*, timeout_seconds: int = 60):
    if docker is None:
        raise RuntimeError("Python Docker SDK is not installed in the API runtime.")

    try:
        return docker.from_env(timeout=timeout_seconds)
    except DockerException as exc:  # pragma: no cover - depends on daemon availability
        raise RuntimeError(f"Failed to connect to the Docker daemon: {exc}") from exc


def _remove_existing_container(client, container_name: str) -> None:
    try:
        client.containers.get(container_name).remove(force=True)
    except NotFound:
        return
    except DockerException as exc:  # pragma: no cover - depends on daemon availability
        raise RuntimeError(f"Failed to remove existing task container: {exc}") from exc


def _build_image_error_detail(exc: Exception) -> str:
    if isinstance(exc, BuildError):
        log_chunks = []
        for line in exc.build_log or []:
            message = line.get("stream") or line.get("error") or ""
            if message:
                log_chunks.append(message.strip())
        if log_chunks:
            return log_chunks[-1]
    return getattr(exc, "explanation", str(exc))


def _resolve_dockerfile_path(build_context: Path) -> str:
    dockerfile = Path(settings.task_container_image_dockerfile)
    if dockerfile.is_absolute():
        resolved = dockerfile.resolve()
        try:
            return str(resolved.relative_to(build_context.resolve()))
        except ValueError as exc:
            raise RuntimeError(
                "Task image Dockerfile must be inside the configured build context."
            ) from exc
    resolved = (build_context / dockerfile).resolve()
    if not resolved.exists():
        raise RuntimeError(f"Task image Dockerfile was not found: {resolved}")
    return str(dockerfile)


def _ensure_task_image(client) -> None:
    image_name = settings.task_container_image
    try:
        client.images.get(image_name)
        return
    except ImageNotFound:
        pass
    except DockerException as exc:  # pragma: no cover - depends on daemon availability
        raise RuntimeError(f"Failed to query task image '{image_name}': {exc}") from exc

    if not settings.task_container_image_auto_build:
        raise RuntimeError(
            f"Task container image '{image_name}' is missing and auto-build is disabled."
        )

    build_context = Path(settings.task_container_image_build_context).resolve()
    if not build_context.exists():
        raise RuntimeError(f"Task image build context does not exist: {build_context}")
    if not build_context.is_dir():
        raise RuntimeError(f"Task image build context is not a directory: {build_context}")

    dockerfile = _resolve_dockerfile_path(build_context)
    try:
        client.images.build(
            path=str(build_context),
            dockerfile=dockerfile,
            tag=image_name,
            rm=True,
            pull=False,
        )
    except (BuildError, APIError, DockerException) as exc:  # pragma: no cover
        detail = _build_image_error_detail(exc)
        raise RuntimeError(
            f"Failed to build task image '{image_name}' from {dockerfile}: {detail}"
        ) from exc


def _task_container_volumes(runtime_root: Path) -> dict[str, dict[str, str]]:
    volumes: dict[str, dict[str, str]] = {
        str(runtime_root): {
            "bind": container_workdir(),
            "mode": "rw",
        }
    }
    codex_home = settings.task_container_codex_home_host_path
    if codex_home:
        volumes[codex_home] = {
            "bind": settings.task_container_codex_home_container_path,
            "mode": "ro",
        }
    return volumes


def _task_container_environment() -> Optional[dict[str, str]]:
    passthrough: dict[str, str] = {}
    for key in settings.task_container_env_passthrough:
        value = os.getenv(key)
        if value:
            passthrough[key] = value
    return passthrough or None


def ensure_task_container(
    project: Project,
    task: Task,
    workspace: TaskWorkspace,
    environment: TaskEnvironment,
) -> TaskEnvironment:
    if not container_runtime_enabled():
        environment.runtime_status = "process-fallback"
        environment.container_name = None
        environment.container_id = None
        environment.container_workdir = None
        return environment

    container_name = container_name_for_task(task)
    runtime_root = Path(workspace.root_path).resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    client = _docker_client()

    try:
        _ensure_task_image(client)
        _remove_existing_container(client, container_name)
        run_kwargs = {
            "image": settings.task_container_image,
            "name": container_name,
            "working_dir": container_workdir(),
            "volumes": _task_container_volumes(runtime_root),
            "command": ["sleep", "infinity"],
            "detach": True,
        }
        environment_vars = _task_container_environment()
        if environment_vars is not None:
            run_kwargs["environment"] = environment_vars
        if settings.task_container_network == "none":
            run_kwargs["network_disabled"] = True
        else:
            run_kwargs["network_mode"] = settings.task_container_network

        container = client.containers.run(**run_kwargs)
        container.reload()
    except (APIError, DockerException) as exc:  # pragma: no cover - depends on daemon availability
        detail = getattr(exc, "explanation", str(exc))
        raise RuntimeError(f"Failed to provision task container: {detail}") from exc
    finally:
        client.close()

    environment.runtime_kind = "task-container"
    environment.runtime_status = "container-ready"
    environment.base_image = settings.task_container_image
    environment.container_name = container_name
    environment.container_id = container.id
    environment.container_workdir = container_workdir()
    environment.workspace_mount_mode = "bind-task-runtime-root"
    environment.network_mode = settings.task_container_network
    environment.mounts = [f"{runtime_root}:{container_workdir()}"]
    return environment


def destroy_task_container(environment: TaskEnvironment) -> None:
    if not container_runtime_enabled() or not environment.container_name:
        return

    client = _docker_client()
    try:
        _remove_existing_container(client, environment.container_name)
    finally:
        client.close()


def run_command_in_task_container(
    environment: TaskEnvironment,
    task_run: TaskRun,
    shell_command: str,
    *,
    timeout_seconds: int,
) -> int:
    if not container_runtime_enabled():
        raise RuntimeError("Task container runtime is not enabled.")
    if not environment.container_name:
        raise RuntimeError("Task container is not provisioned.")

    client = _docker_client(timeout_seconds=timeout_seconds)
    try:
        container = client.containers.get(environment.container_name)
        exec_instance = client.api.exec_create(
            container.id,
            ["sh", "-lc", shell_command],
            workdir=environment.container_workdir or container_workdir(),
            stdout=True,
            stderr=True,
        )
        output = client.api.exec_start(exec_instance["Id"], stream=False, demux=False)
        if output:
            text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
            task_run.stdout = f"{task_run.stdout or ''}{text}"

        result = client.api.exec_inspect(exec_instance["Id"])
        return int(result.get("ExitCode") or 0)
    except NotFound as exc:  # pragma: no cover - depends on daemon availability
        raise RuntimeError("Task container is not available for execution.") from exc
    except TimeoutError as exc:  # pragma: no cover - depends on daemon availability
        raise RuntimeError("Task container command timed out.") from exc
    except DockerException as exc:  # pragma: no cover - depends on daemon availability
        raise RuntimeError(f"Task container command failed: {exc}") from exc
    finally:
        client.close()
