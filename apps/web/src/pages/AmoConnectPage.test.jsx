import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import AmoConnectPage from "./AmoConnectPage";

function createJsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body;
    },
    async text() {
      return typeof body === "string" ? body : JSON.stringify(body);
    },
  };
}

function createStatus(overrides = {}) {
  return {
    integration_mode: "external",
    redirect_uri: "https://api.fotonai.online/api/integrations/amocrm/callback",
    secrets_uri: "https://api.fotonai.online/api/integrations/amocrm/secrets",
    scopes: ["crm"],
    integration_name: "AI Office",
    integration_description: "Интеграция AI Office для безопасной записи данных в amoCRM.",
    logo_url: null,
    account_base_url_hint: "https://educent.amocrm.ru",
    button_snippet: "<script></script>",
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
    required_contact_fields_missing: ["Id Tallanto", "Филиал Tallanto"],
    token_source: null,
    ...overrides,
  };
}

describe("AmoConnectPage", () => {
  it("loads integration status and mounts the official amo button script", async () => {
    const fetchMock = vi.fn(async (input, options = {}) => {
      const url = new URL(String(input), "http://localhost");
      const method = (options.method || "GET").toUpperCase();
      if (url.pathname === "/api/integrations/amocrm/status" && method === "GET") {
        return createJsonResponse(createStatus());
      }
      return createJsonResponse({ detail: "Unhandled request" }, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <AmoConnectPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Подключение amoCRM через внешнюю интеграцию")).toBeInTheDocument();
    expect(screen.getByText("Не подключено")).toBeInTheDocument();
    expect(screen.getByText("Id Tallanto")).toBeInTheDocument();

    await waitFor(() => {
      const script = document.querySelector(".integration-button-host script.amocrm_oauth");
      expect(script).not.toBeNull();
      expect(script?.getAttribute("src")).toBe("https://www.amocrm.ru/auth/button.min.js");
      expect(script?.getAttribute("data-secrets_uri")).toBe(
        "https://api.fotonai.online/api/integrations/amocrm/secrets",
      );
      expect(script?.getAttribute("data-title")).toBe("Подключить amoCRM");
    });
  });

  it("syncs amo contact fields after a live connection appears", async () => {
    let connected = true;
    const fetchMock = vi.fn(async (input, options = {}) => {
      const url = new URL(String(input), "http://localhost");
      const method = (options.method || "GET").toUpperCase();

      if (url.pathname === "/api/integrations/amocrm/status" && method === "GET") {
        return createJsonResponse(
          createStatus(
            connected
              ? {
                  connected: true,
                  status: "connected",
                  client_id_present: true,
                  client_secret_present: true,
                  access_token_present: true,
                  refresh_token_present: true,
                  contact_field_count: 12,
                  required_contact_fields_present: ["Id Tallanto"],
                  required_contact_fields_missing: ["Филиал Tallanto"],
                }
              : {},
          ),
        );
      }

      if (url.pathname === "/api/integrations/amocrm/contact-fields/sync" && method === "POST") {
        return createJsonResponse({
          status: "ok",
          summary: "Каталог полей контактов amoCRM синхронизирован.",
          field_count: 12,
          synced_at: "2026-03-26T18:30:00.000Z",
        });
      }

      return createJsonResponse({ detail: "Unhandled request" }, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <AmoConnectPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Подключено")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Синхронизировать поля контактов" }));

    await waitFor(() => {
      expect(screen.getByText("Каталог полей контактов amoCRM синхронизирован.")).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/integrations/amocrm/contact-fields/sync"),
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("shows empty setup state when redirect or secrets uri is missing", async () => {
    const fetchMock = vi.fn(async () =>
      createJsonResponse(
        createStatus({
          redirect_uri: null,
          secrets_uri: null,
          button_snippet: null,
          last_error: "Webhook secrets ещё не приходил.",
        }),
      ),
    );

    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <AmoConnectPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Сервер ещё не знает redirect_uri или secrets_uri/i)).toBeInTheDocument();
    expect(screen.getByText(/Последняя ошибка интеграции: Webhook secrets ещё не приходил./i)).toBeInTheDocument();
    expect(document.querySelector(".integration-button-host script.amocrm_oauth")).toBeNull();
  });

  it("explains that oauth is still incomplete after a manual status refresh", async () => {
    const fetchMock = vi.fn(async () => createJsonResponse(createStatus()));

    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <AmoConnectPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Не подключено")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Обновить статус" }));

    expect(
      await screen.findByText(/Статус обновлён\. Если вы только что прошли авторизацию в popup/i),
    ).toBeInTheDocument();
  });

  it("shows sync error when amo field catalog refresh fails", async () => {
    const fetchMock = vi.fn(async (input, options = {}) => {
      const url = new URL(String(input), "http://localhost");
      const method = (options.method || "GET").toUpperCase();

      if (url.pathname === "/api/integrations/amocrm/status" && method === "GET") {
        return createJsonResponse(
          createStatus({
            connected: true,
            status: "connected",
            client_id_present: true,
            client_secret_present: true,
            access_token_present: true,
            refresh_token_present: true,
          }),
        );
      }

      if (url.pathname === "/api/integrations/amocrm/contact-fields/sync" && method === "POST") {
        return createJsonResponse({ detail: "AMO временно недоступна." }, 502);
      }

      return createJsonResponse({ detail: "Unhandled request" }, 404);
    });

    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <AmoConnectPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Подключено")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Синхронизировать поля контактов" }));

    expect(await screen.findByText("AMO временно недоступна.")).toBeInTheDocument();
  });
});
