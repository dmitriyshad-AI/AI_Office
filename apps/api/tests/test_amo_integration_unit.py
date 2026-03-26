import io
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib import error as url_error

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.amo_integration as amo_module  # noqa: E402
from app.amo_integration import (  # noqa: E402
    AmoIntegrationError,
    build_custom_fields_values,
    exchange_callback_code,
    fetch_contact_field_catalog,
    get_active_connection,
    get_amo_connection_status,
    record_external_secrets,
    refresh_connection_tokens,
    send_contact_custom_field_update,
)
from app.db import Base  # noqa: E402


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    return session_factory()


def make_settings(**overrides):
    defaults = {
        "crm_amo_api_token": None,
        "crm_amo_base_url": "https://educent.amocrm.ru/api/v4",
        "crm_amo_oauth_redirect_uri": "https://api.fotonai.online/api/integrations/amocrm/callback",
        "crm_amo_oauth_secrets_uri": "https://api.fotonai.online/api/integrations/amocrm/secrets",
        "crm_amo_oauth_scopes": ("crm",),
        "crm_amo_oauth_name": "AI Office",
        "crm_amo_oauth_description": "amo integration",
        "crm_amo_oauth_logo_url": None,
        "crm_amo_oauth_account_base_url": "https://educent.amocrm.ru",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_record_external_secrets_and_status_summary(monkeypatch):
    monkeypatch.setattr(amo_module, "settings", make_settings())
    session = make_session()

    connection, summary = record_external_secrets(
        session,
        payload={
            "client_id": "client-123",
            "secret_key": "secret-abc",
            "state": "state-1",
            "subdomain": "educent",
        },
    )

    assert connection.client_id == "client-123"
    assert connection.client_secret == "secret-abc"
    assert connection.status == "awaiting_callback"
    assert connection.account_base_url == "https://educent.amocrm.ru"
    assert "сохранены" in summary.lower()

    status_payload = get_amo_connection_status(session)
    assert status_payload["connected"] is False
    assert status_payload["status"] == "awaiting_callback"
    assert status_payload["client_id_present"] is True
    assert status_payload["client_secret_present"] is True
    assert status_payload["required_contact_fields_missing"]
    assert "button_snippet" in status_payload


def test_callback_refresh_catalog_and_contact_update(monkeypatch):
    monkeypatch.setattr(amo_module, "settings", make_settings())
    session = make_session()
    connection, _ = record_external_secrets(
        session,
        payload={
            "client_id": "client-123",
            "client_secret": "secret-abc",
            "state": "state-1",
            "referer": "https://educent.amocrm.ru",
        },
    )

    exchange_calls = []

    def fake_exchange_token(**kwargs):
        exchange_calls.append(kwargs)
        if kwargs["grant_type"] == "authorization_code":
            return {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        return {
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "token_type": "Bearer",
            "expires_in": 7200,
        }

    http_calls = []

    def fake_http_request(**kwargs):
        http_calls.append(kwargs)
        url = kwargs["url"]
        if "/api/v4/contacts/custom_fields" in url and "page=2" not in url:
            return {
                "_embedded": {
                    "custom_fields": [
                        {"id": 101, "name": "Id Tallanto", "code": None, "type": "text"},
                        {"id": 102, "name": "Авто история общения", "code": None, "type": "text"},
                    ]
                },
                "_links": {
                    "next": {
                        "href": "/api/v4/contacts/custom_fields?page=2&limit=50",
                    }
                },
            }
        if "/api/v4/contacts/custom_fields" in url and "page=2" in url:
            return {
                "_embedded": {
                    "custom_fields": [
                        {"id": 103, "name": "AI-приоритет", "code": None, "type": "text"},
                    ]
                }
            }
        if url.endswith("/api/v4/contacts/75807689"):
            return {"id": 75807689, "updated_at": 123456}
        raise AssertionError(f"Unexpected amo request: {kwargs}")

    monkeypatch.setattr(amo_module, "_exchange_token", fake_exchange_token)
    monkeypatch.setattr(amo_module, "_amo_http_request", fake_http_request)

    connection, summary = exchange_callback_code(
        session,
        code="code-123",
        state="state-1",
        referer="https://educent.amocrm.ru",
    )
    assert connection.status == "active"
    assert connection.access_token == "access-1"
    assert "токены сохранены" in summary.lower()

    fields = fetch_contact_field_catalog(session, force_refresh=True)
    assert [field["id"] for field in fields] == [101, 102, 103]
    assert get_amo_connection_status(session)["contact_field_count"] == 3

    connection.expires_at = amo_module.utc_now() - amo_module.timedelta(minutes=5)
    refreshed = refresh_connection_tokens(session, connection)
    assert refreshed.access_token == "access-2"
    assert refreshed.refresh_token == "refresh-2"

    update_result = send_contact_custom_field_update(
        session,
        contact_id=75807689,
        field_payload={
            "Id Tallanto": "245fb3d4-14d6-d7fb-aabf-69ae8a2d3270",
            "Авто история общения": "Связаться с семьей после звонка.",
        },
    )
    assert update_result["entity_id"] == 75807689
    assert update_result["updated_fields"] == ["Id Tallanto", "Авто история общения"]
    patch_call = http_calls[-1]
    assert patch_call["method"] == "PATCH"
    assert patch_call["body"]["custom_fields_values"][0]["field_id"] == 101
    assert patch_call["body"]["custom_fields_values"][1]["field_id"] == 102
    assert exchange_calls[0]["grant_type"] == "authorization_code"
    assert exchange_calls[1]["grant_type"] == "refresh_token"


def test_build_custom_fields_values_requires_known_fields():
    with pytest.raises(AmoIntegrationError):
        build_custom_fields_values(
            {"Unknown field": "value"},
            [{"id": 1, "name": "Id Tallanto", "code": None}],
        )


def test_callback_requires_secrets_first(monkeypatch):
    monkeypatch.setattr(amo_module, "settings", make_settings())
    session = make_session()

    with pytest.raises(AmoIntegrationError) as exc_info:
        exchange_callback_code(
            session,
            code="code-123",
            state="state-unknown",
            referer="https://educent.amocrm.ru",
        )

    assert exc_info.value.status_code == 409
    pending_connection = get_active_connection(session)
    assert pending_connection is not None
    assert pending_connection.status == "awaiting_secrets"


def test_base_url_http_and_setup_helpers_cover_edge_cases(monkeypatch):
    monkeypatch.setattr(
        amo_module,
        "settings",
        make_settings(
            crm_amo_base_url="educent.amocrm.ru/api/v4",
            crm_amo_oauth_redirect_uri="",
            crm_amo_oauth_secrets_uri="",
            crm_amo_oauth_scopes=(" ", ""),
            crm_amo_oauth_account_base_url="",
        ),
    )

    assert amo_module._normalize_base_url(None) is None
    assert amo_module._normalize_base_url("educent.amocrm.ru/path") == "https://educent.amocrm.ru"
    assert amo_module._normalize_base_url("http://educent.amocrm.ru/api") == "http://educent.amocrm.ru"
    assert amo_module._account_subdomain(None) is None
    assert amo_module._account_subdomain("https://educent.amocrm.ru") == "educent"
    assert amo_module._resolve_scopes() == ["crm"]
    assert amo_module._resolve_redirect_uri() is None
    assert amo_module._resolve_secrets_uri() is None
    assert amo_module._resolve_account_base_url_hint() == "https://educent.amocrm.ru"
    assert amo_module._extract_account_base_url({"subdomain": "educent"}) == "https://educent.amocrm.ru"
    assert amo_module._extract_account_base_url({}, fallback="educent.amocrm.ru") == "https://educent.amocrm.ru"
    assert amo_module._pick_first_non_empty({"x": ["", "value"]}, "x") == "value"
    assert amo_module._extract_state({"request_state": "abc"}) == "abc"

    setup = amo_module.build_external_oauth_setup()
    assert setup["button_snippet"] is None
    assert setup["redirect_uri"] is None
    assert setup["secrets_uri"] is None

    with pytest.raises(AmoIntegrationError):
        amo_module._token_endpoint("")
    with pytest.raises(AmoIntegrationError):
        amo_module._contacts_custom_fields_endpoint("")
    with pytest.raises(AmoIntegrationError):
        amo_module._contact_update_endpoint("", 1)


def test_amo_http_request_handles_empty_list_and_error_responses(monkeypatch):
    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        amo_module.url_request,
        "urlopen",
        lambda request, timeout: FakeResponse(b""),
    )
    assert amo_module._amo_http_request(method="GET", url="https://example.com") == {}

    monkeypatch.setattr(
        amo_module.url_request,
        "urlopen",
        lambda request, timeout: FakeResponse(b'["a", "b"]'),
    )
    assert amo_module._amo_http_request(method="GET", url="https://example.com") == {
        "data": ["a", "b"]
    }

    def raise_http_error(request, timeout):
        raise url_error.HTTPError(
            request.full_url,
            403,
            "forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"forbidden"}'),
        )

    monkeypatch.setattr(amo_module.url_request, "urlopen", raise_http_error)
    with pytest.raises(AmoIntegrationError) as http_exc:
        amo_module._amo_http_request(method="GET", url="https://example.com")
    assert "HTTP 403" in str(http_exc.value)

    monkeypatch.setattr(
        amo_module.url_request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(url_error.URLError("offline")),
    )
    with pytest.raises(AmoIntegrationError) as url_exc:
        amo_module._amo_http_request(method="GET", url="https://example.com")
    assert "Failed to reach amoCRM" in str(url_exc.value)

    monkeypatch.setattr(
        amo_module.url_request,
        "urlopen",
        lambda request, timeout: FakeResponse(b"{not-json"),
    )
    with pytest.raises(AmoIntegrationError) as json_exc:
        amo_module._amo_http_request(method="GET", url="https://example.com")
    assert "Invalid JSON response" in str(json_exc.value)


def test_resolve_context_refresh_guards_and_field_helpers(monkeypatch):
    monkeypatch.setattr(amo_module, "settings", make_settings())
    session = make_session()

    env_settings = make_settings(
        crm_amo_api_token="env-token",
        crm_amo_base_url="https://educent.amocrm.ru",
    )
    monkeypatch.setattr(amo_module, "settings", env_settings)
    env_context = amo_module.resolve_amo_access_context(session)
    assert env_context.token_source == "env"
    assert env_context.access_token == "env-token"

    monkeypatch.setattr(amo_module, "settings", make_settings(crm_amo_api_token=None))
    with pytest.raises(AmoIntegrationError) as no_connection_exc:
        amo_module.resolve_amo_access_context(session)
    assert no_connection_exc.value.status_code == 409

    connection = amo_module._ensure_connection(
        session,
        state="state-x",
        client_id="client-x",
        account_base_url="https://educent.amocrm.ru",
    )
    connection.client_id = "client-x"
    connection.client_secret = "secret-x"
    connection.refresh_token = "refresh-x"
    connection.access_token = None
    connection.expires_at = None
    session.flush()

    monkeypatch.setattr(amo_module, "_token_is_stale", lambda current: False)
    with pytest.raises(AmoIntegrationError) as unusable_exc:
        amo_module.resolve_amo_access_context(session)
    assert "usable access token" in str(unusable_exc.value)

    with pytest.raises(AmoIntegrationError):
        amo_module.refresh_connection_tokens(session, connection)

    connection.access_token = "access-x"
    connection.client_id = None
    with pytest.raises(AmoIntegrationError):
        amo_module.refresh_connection_tokens(session, connection)

    monkeypatch.setattr(amo_module, "settings", make_settings(crm_amo_oauth_redirect_uri=""))
    connection.client_id = "client-x"
    with pytest.raises(AmoIntegrationError):
        amo_module.refresh_connection_tokens(session, connection)

    monkeypatch.setattr(
        amo_module,
        "settings",
        make_settings(
            crm_amo_oauth_account_base_url="",
            crm_amo_base_url="",
        ),
    )
    connection.redirect_uri = "https://api.fotonai.online/api/integrations/amocrm/callback"
    connection.account_base_url = None
    with pytest.raises(AmoIntegrationError):
        amo_module.refresh_connection_tokens(session, connection)

    token_connection = amo_module._ensure_connection(
        session,
        state="state-y",
        client_id="client-y",
        account_base_url="https://educent.amocrm.ru",
    )
    token_connection.client_id = "client-y"
    token_connection.client_secret = "secret-y"
    token_connection.redirect_uri = None
    session.flush()
    monkeypatch.setattr(amo_module, "settings", make_settings(crm_amo_oauth_redirect_uri=""))
    with pytest.raises(AmoIntegrationError):
        amo_module.exchange_callback_code(
            session,
            code="code-y",
            state="state-y",
            referer="https://educent.amocrm.ru",
        )

    field_catalog = [
        {"id": 101, "name": "Id Tallanto", "code": "UF_TALLANTO_ID"},
        {"id": 102, "name": "Комментарий", "code": "UF_COMMENT"},
    ]
    assert amo_module._find_field_meta(field_catalog, "UF_TALLANTO_ID")["id"] == 101
    assert amo_module._field_values(["a", None, "b"]) == [{"value": "a"}, {"value": "b"}]
    assert amo_module._follow_next_link("https://educent.amocrm.ru", "https://other.test/page") == "https://other.test/page"

    connection.contact_field_catalog = field_catalog
    connection.contact_field_catalog_synced_at = amo_module.utc_now()
    connection.account_base_url = "https://educent.amocrm.ru"
    connection.access_token = "access"
    session.flush()
    cached_fields = fetch_contact_field_catalog(session, force_refresh=False)
    assert cached_fields == field_catalog

    monkeypatch.setattr(
        amo_module,
        "resolve_amo_access_context",
        lambda db: amo_module.AmoAccessContext(
            account_base_url="https://educent.amocrm.ru",
            access_token="access",
            token_source="oauth",
            connection=connection,
        ),
    )
    monkeypatch.setattr(amo_module, "fetch_contact_field_catalog", lambda db: field_catalog)
    with pytest.raises(AmoIntegrationError):
        send_contact_custom_field_update(session, contact_id=75807689, field_payload={})


def test_apply_token_payload_and_record_external_secrets_validation(monkeypatch):
    monkeypatch.setattr(amo_module, "settings", make_settings())
    session = make_session()
    connection = amo_module._ensure_connection(
        session,
        state="state-z",
        client_id="client-z",
        account_base_url="https://educent.amocrm.ru",
    )

    with pytest.raises(AmoIntegrationError):
        amo_module._apply_token_payload(
            connection,
            payload={"access_token": "only-access"},
            account_base_url="https://educent.amocrm.ru",
        )

    amo_module._apply_token_payload(
        connection,
        payload={
            "access_token": "access-z",
            "refresh_token": "refresh-z",
            "expires_in": "bad-value",
        },
        account_base_url="https://educent.amocrm.ru",
    )
    assert connection.expires_at is None
    assert connection.token_type == "Bearer"

    with pytest.raises(AmoIntegrationError) as secrets_exc:
        record_external_secrets(session, payload={"state": "missing-secrets"})
    assert secrets_exc.value.status_code == 400
