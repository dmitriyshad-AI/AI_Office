import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_main_module(monkeypatch, tmp_path, *, api_key="test-key", auto_run=False, heartbeat=False):
    database_path = tmp_path / "main_test.db"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("SOURCE_WORKSPACE_ROOT", str(Path(__file__).resolve().parents[3]))
    monkeypatch.setenv("AI_OFFICE_API_KEY", api_key)
    monkeypatch.delenv("AI_OFFICE_API_KEYS", raising=False)
    monkeypatch.setenv("AI_OFFICE_STREAM_TOKEN_SECRET", "test-stream-secret")
    monkeypatch.setenv("DIRECTOR_AUTO_RUN_ENABLED", "true" if auto_run else "false")
    monkeypatch.setenv("DIRECTOR_HEARTBEAT_ENABLED", "true" if heartbeat else "false")
    monkeypatch.setenv("DIRECTOR_HEARTBEAT_POLL_SECONDS", "1")

    for module_name in [
        "app.amo_integration",
        "app.config",
        "app.db",
        "app.director_heartbeat",
        "app.main",
        "app.routers.integrations",
        "app.routers.projects",
    ]:
        sys.modules.pop(module_name, None)

    import app.main as main_module

    return importlib.reload(main_module)


def test_root_and_health_routes_do_not_leak_runtime_secrets(tmp_path, monkeypatch):
    main_module = load_main_module(monkeypatch, tmp_path)

    with TestClient(main_module.app) as client:
        root_response = client.get("/")
        assert root_response.status_code == 200
        assert root_response.json() == {
            "service": "ai-office-api",
            "version": "0.1.0",
            "status": "ok",
        }

        health_response = client.get("/health")
        assert health_response.status_code == 200
        health_payload = health_response.json()
        assert health_payload["status"] == "ok"
        assert health_payload["auth_mode"] == "api_key"
        assert health_payload["director_heartbeat"]["enabled"] is False
        assert health_payload["director_heartbeat"]["running"] is False
        assert "database_url" not in health_payload
        assert "redis_url" not in health_payload
        assert "stream_token_secret" not in health_payload


def test_lifespan_starts_and_stops_heartbeat_service_once(tmp_path, monkeypatch):
    main_module = load_main_module(
        monkeypatch,
        tmp_path,
        auto_run=True,
        heartbeat=True,
    )
    calls: list[str] = []

    monkeypatch.setattr(main_module.director_heartbeat_service, "start", lambda: calls.append("start"))
    monkeypatch.setattr(main_module.director_heartbeat_service, "stop", lambda: calls.append("stop"))

    with TestClient(main_module.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert calls == ["start"]

    assert calls == ["start", "stop"]


def test_amo_integration_routes_are_available_with_and_without_api_prefix(tmp_path, monkeypatch):
    main_module = load_main_module(monkeypatch, tmp_path)

    with TestClient(main_module.app) as client:
        prefixed = client.get("/api/integrations/amocrm/callback")
        compat = client.get("/integrations/amocrm/callback")

        assert prefixed.status_code == 400
        assert compat.status_code == 400
        assert "параметр code" in prefixed.text
        assert "параметр code" in compat.text
