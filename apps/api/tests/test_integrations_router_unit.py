import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_app(monkeypatch, tmp_path):
    database_path = tmp_path / "integrations_router.db"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("SOURCE_WORKSPACE_ROOT", str(Path(__file__).resolve().parents[3]))
    monkeypatch.setenv("AI_OFFICE_API_KEY", "test-key")
    monkeypatch.delenv("AI_OFFICE_API_KEYS", raising=False)
    monkeypatch.setenv("AI_OFFICE_STREAM_TOKEN_SECRET", "test-stream-secret")
    monkeypatch.setenv("DIRECTOR_AUTO_RUN_ENABLED", "false")
    monkeypatch.setenv("DIRECTOR_HEARTBEAT_ENABLED", "false")

    for module_name in [
        "app.amo_integration",
        "app.config",
        "app.db",
        "app.main",
        "app.routers.integrations",
        "app.routers.projects",
    ]:
        sys.modules.pop(module_name, None)

    import app.main as main_module

    return importlib.reload(main_module)


def test_amocrm_integrations_routes_cover_secrets_callback_status_and_sync(monkeypatch, tmp_path):
    main_module = load_app(monkeypatch, tmp_path)

    import app.routers.integrations as integrations_router

    monkeypatch.setattr(
        integrations_router,
        "record_external_secrets",
        lambda db, payload: (
            SimpleNamespace(status="awaiting_callback"),
            f"saved:{payload.get('state')}",
        ),
    )
    monkeypatch.setattr(
        integrations_router,
        "exchange_callback_code",
        lambda db, code, state, referer: (
            SimpleNamespace(account_base_url="https://educent.amocrm.ru"),
            f"ok:{code}:{state}:{referer}",
        ),
    )
    monkeypatch.setattr(
        integrations_router,
        "get_amo_connection_status",
        lambda db: {
            "integration_mode": "external",
            "redirect_uri": "https://api.fotonai.online/api/integrations/amocrm/callback",
            "secrets_uri": "https://api.fotonai.online/api/integrations/amocrm/secrets",
            "scopes": ["crm"],
            "integration_name": "AI Office",
            "integration_description": "amo integration",
            "logo_url": None,
            "account_base_url_hint": "https://educent.amocrm.ru",
            "button_snippet": "<script></script>",
            "connected": True,
            "status": "active",
            "account_base_url": "https://educent.amocrm.ru",
            "account_subdomain": "educent",
            "client_id_present": True,
            "client_secret_present": True,
            "access_token_present": True,
            "refresh_token_present": True,
            "authorized_at": None,
            "expires_at": None,
            "last_error": None,
            "contact_field_catalog_synced_at": None,
            "contact_field_count": 5,
            "required_contact_fields_present": ["Id Tallanto"],
            "required_contact_fields_missing": [],
            "token_source": "oauth",
        },
    )
    monkeypatch.setattr(
        integrations_router,
        "get_active_connection",
        lambda db: SimpleNamespace(status="active", expires_at=None, contact_field_catalog_synced_at=None),
    )
    monkeypatch.setattr(
        integrations_router,
        "refresh_connection_tokens",
        lambda db, connection: SimpleNamespace(status="active", expires_at=None),
    )
    monkeypatch.setattr(
        integrations_router,
        "fetch_contact_field_catalog",
        lambda db, force_refresh: [{"id": 101, "name": "Id Tallanto"}],
    )

    with TestClient(main_module.app) as client:
        secrets_response = client.post(
            "/api/integrations/amocrm/secrets",
            json={"state": "state-1", "client_id": "cid"},
        )
        assert secrets_response.status_code == 200
        assert secrets_response.json()["summary"] == "saved:state-1"

        callback_response = client.get(
            "/api/integrations/amocrm/callback",
            params={"code": "abc", "state": "state-1", "referer": "https://educent.amocrm.ru"},
        )
        assert callback_response.status_code == 200
        assert "ok:abc:state-1:https://educent.amocrm.ru" in callback_response.text

        status_response = client.get(
            "/api/integrations/amocrm/status",
            headers={"X-API-Key": "test-key"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["connected"] is True

        refresh_response = client.post(
            "/api/integrations/amocrm/refresh",
            headers={"X-API-Key": "test-key"},
        )
        assert refresh_response.status_code == 200
        assert refresh_response.json()["status"] == "active"

        sync_response = client.post(
            "/api/integrations/amocrm/contact-fields/sync",
            headers={"X-API-Key": "test-key"},
        )
        assert sync_response.status_code == 200
        assert sync_response.json()["field_count"] == 1


@pytest.mark.anyio
async def test_parse_request_payload_supports_query_json_invalid_json_and_form(monkeypatch, tmp_path):
    main_module = load_app(monkeypatch, tmp_path)
    import app.routers.integrations as integrations_router

    async def receive_empty():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"state=q1",
            "headers": [],
        },
        receive_empty,
    )
    assert await integrations_router._parse_request_payload(request) == {"state": "q1"}

    async def receive_invalid_json():
        return {"type": "http.request", "body": b"{broken", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        receive_invalid_json,
    )
    assert await integrations_router._parse_request_payload(request) == {}

    async def receive_form():
        return {
            "type": "http.request",
            "body": b"client_id=cid&client_secret=sec",
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"state=query",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        },
        receive_form,
    )
    assert await integrations_router._parse_request_payload(request) == {
        "state": "query",
        "client_id": "cid",
        "client_secret": "sec",
    }


def test_amocrm_integrations_routes_cover_error_branches(monkeypatch, tmp_path):
    main_module = load_app(monkeypatch, tmp_path)

    import app.routers.integrations as integrations_router

    monkeypatch.setattr(
        integrations_router,
        "record_external_secrets",
        lambda db, payload: (
            SimpleNamespace(status="awaiting_callback"),
            f"saved:{payload.get('client_secret')}",
        ),
    )
    monkeypatch.setattr(
        integrations_router,
        "exchange_callback_code",
        lambda db, code, state, referer: (_ for _ in ()).throw(
            integrations_router.AmoIntegrationError("callback failed", status_code=409)
        ),
    )
    monkeypatch.setattr(integrations_router, "get_active_connection", lambda db: None)
    monkeypatch.setattr(
        integrations_router,
        "refresh_connection_tokens",
        lambda db, connection: (_ for _ in ()).throw(
            integrations_router.AmoIntegrationError("refresh failed", status_code=409)
        ),
    )
    monkeypatch.setattr(
        integrations_router,
        "fetch_contact_field_catalog",
        lambda db, force_refresh: (_ for _ in ()).throw(
            integrations_router.AmoIntegrationError("sync failed", status_code=502)
        ),
    )

    with TestClient(main_module.app) as client:
        secrets_response = client.post(
            "/api/integrations/amocrm/secrets",
            content="client_id=cid&client_secret=sec",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert secrets_response.status_code == 200
        assert secrets_response.json()["summary"] == "saved:sec"

        missing_code = client.get("/api/integrations/amocrm/callback")
        assert missing_code.status_code == 400
        assert "не пришёл параметр code" in missing_code.text

        failed_callback = client.get(
            "/api/integrations/amocrm/callback",
            params={"code": "abc", "referer": "https://educent.amocrm.ru"},
        )
        assert failed_callback.status_code == 409
        assert "callback failed" in failed_callback.text

        refresh_response = client.post(
            "/api/integrations/amocrm/refresh",
            headers={"X-API-Key": "test-key"},
        )
        assert refresh_response.status_code == 409
        assert refresh_response.json()["detail"] == "AMO integration is not connected yet."

        monkeypatch.setattr(
            integrations_router,
            "get_active_connection",
            lambda db: SimpleNamespace(status="awaiting_callback", expires_at=None),
        )
        refresh_failed = client.post(
            "/api/integrations/amocrm/refresh",
            headers={"X-API-Key": "test-key"},
        )
        assert refresh_failed.status_code == 409
        assert refresh_failed.json()["detail"] == "refresh failed"

        sync_failed = client.post(
            "/api/integrations/amocrm/contact-fields/sync",
            headers={"X-API-Key": "test-key"},
        )
        assert sync_failed.status_code == 502
        assert sync_failed.json()["detail"] == "sync failed"
