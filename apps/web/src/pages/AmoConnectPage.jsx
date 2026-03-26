import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { formatDate, requestJson } from "../appShared";

const AMO_BUTTON_SRC = "https://www.amocrm.ru/auth/button.min.js";

function buildStatusChip(status) {
  if (status?.connected) {
    return { className: "ready", label: "Подключено" };
  }
  if (status?.client_id_present && status?.client_secret_present) {
    return { className: "planned", label: "Нужно завершить OAuth" };
  }
  return { className: "idle", label: "Не подключено" };
}

function createAmoOauthButtonScript(status) {
  if (!status?.redirect_uri || !status?.secrets_uri) {
    return null;
  }

  const script = document.createElement("script");
  script.className = "amocrm_oauth";
  script.charset = "utf-8";
  script.dataset.name = status.integration_name || "AI Office";
  script.dataset.description = status.integration_description || "";
  script.dataset.redirect_uri = status.redirect_uri;
  script.dataset.secrets_uri = status.secrets_uri;
  script.dataset.logo = status.logo_url || "";
  script.dataset.scopes = Array.isArray(status.scopes) ? status.scopes.join(",") : "crm";
  script.dataset.title = status.connected ? "Переподключить amoCRM" : "Подключить amoCRM";
  script.dataset.mode = "popup";
  script.src = AMO_BUTTON_SRC;
  return script;
}

function renderFieldList(fields, emptyText) {
  if (!fields?.length) {
    return <p className="hint-text">{emptyText}</p>;
  }

  return (
    <ul className="steps-list">
      {fields.map((fieldName) => (
        <li key={fieldName}>{fieldName}</li>
      ))}
    </ul>
  );
}

export default function AmoConnectPage() {
  const buttonHostRef = useRef(null);
  const [integrationStatus, setIntegrationStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function loadStatus({ silent = false } = {}) {
    if (!silent) {
      setError("");
    }
    const nextStatus = await requestJson("/api/integrations/amocrm/status");
    setIntegrationStatus(nextStatus);
    return nextStatus;
  }

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      setLoading(true);
      try {
        const nextStatus = await loadStatus({ silent: true });
        if (!cancelled) {
          setIntegrationStatus(nextStatus);
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(
            nextError instanceof Error
              ? nextError.message
              : "Не удалось получить текущий статус интеграции amoCRM.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    bootstrap();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const host = buttonHostRef.current;
    if (!host) {
      return undefined;
    }

    host.replaceChildren();
    const script = createAmoOauthButtonScript(integrationStatus);
    if (!script) {
      return undefined;
    }
    host.appendChild(script);

    return () => {
      host.replaceChildren();
    };
  }, [integrationStatus]);

  async function handleRefreshStatus() {
    setRefreshing(true);
    setError("");
    setMessage("");
    try {
      const nextStatus = await loadStatus();
      setMessage(
        nextStatus.connected
          ? "AI Office видит действующее подключение amoCRM."
          : "Статус обновлён. Если вы только что прошли авторизацию в popup, проверьте, появились ли client_id и токены.",
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Не удалось обновить статус интеграции amoCRM.",
      );
    } finally {
      setRefreshing(false);
    }
  }

  async function handleSyncFields() {
    setSyncing(true);
    setError("");
    setMessage("");
    try {
      const response = await requestJson("/api/integrations/amocrm/contact-fields/sync", {
        method: "POST",
      });
      await loadStatus();
      setMessage(
        response.summary ||
          `Каталог полей amoCRM синхронизирован. Получено полей: ${response.field_count}.`,
      );
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Не удалось синхронизировать поля контактов amoCRM.",
      );
    } finally {
      setSyncing(false);
    }
  }

  const chip = buildStatusChip(integrationStatus);

  return (
    <>
      <section className="grid grid-single page-scroll">
        <article className="panel module-hero-panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Интеграции</p>
              <h2>Подключение amoCRM через внешнюю интеграцию</h2>
            </div>
            {!loading && integrationStatus ? (
              <span className={`status-chip status-${chip.className}`}>{chip.label}</span>
            ) : null}
          </header>

          <div className="module-hero-copy">
            <p>
              Здесь запускается официальный сценарий amoCRM: popup авторизации, передача секретов на
              сервер AI Office и возврат кода на публичный callback без ручного копирования параметров.
            </p>
            <p>
              После подключения этот экран покажет, дошли ли ключи, появились ли токены и можно ли уже
              синхронизировать каталог полей контактов перед первой записью в CRM.
            </p>
          </div>

          <div className="module-stats-grid">
            <article className="module-stat-card">
              <span>Аккаунт</span>
              <strong>{integrationStatus?.account_subdomain || "educent"}</strong>
              <small>{integrationStatus?.account_base_url || "Аккаунт будет подтверждён после OAuth"}</small>
            </article>
            <article className="module-stat-card">
              <span>Ключи интеграции</span>
              <strong>
                {integrationStatus?.client_id_present && integrationStatus?.client_secret_present
                  ? "Получены"
                  : "Пока нет"}
              </strong>
              <small>client_id и client_secret из webhook secrets</small>
            </article>
            <article className="module-stat-card">
              <span>Токены</span>
              <strong>
                {integrationStatus?.access_token_present && integrationStatus?.refresh_token_present
                  ? "Готово"
                  : "Нет"}
              </strong>
              <small>access_token и refresh_token после callback</small>
            </article>
            <article className="module-stat-card">
              <span>Поля контактов</span>
              <strong>{integrationStatus?.contact_field_count ?? 0}</strong>
              <small>синхронизировано из amoCRM</small>
            </article>
            <article className="module-stat-card">
              <span>Последняя авторизация</span>
              <strong>{integrationStatus?.authorized_at ? formatDate(integrationStatus.authorized_at) : "Ещё не было"}</strong>
              <small>последний успешный OAuth-цикл</small>
            </article>
          </div>

          <div className="action-row">
            <button className="button-ghost" onClick={handleRefreshStatus} type="button" disabled={loading || refreshing}>
              {refreshing ? "Обновляю статус..." : "Обновить статус"}
            </button>
            <button
              onClick={handleSyncFields}
              type="button"
              disabled={loading || syncing || !integrationStatus?.connected}
            >
              {syncing ? "Синхронизирую поля..." : "Синхронизировать поля контактов"}
            </button>
            <Link className="button-ghost integration-link-button" to="/crm">
              Вернуться в CRM-модуль
            </Link>
          </div>
        </article>
      </section>

      {message ? <p className="success-banner">{message}</p> : null}
      {error ? <p className="error-banner">{error}</p> : null}

      <section className="grid grid-main page-scroll">
        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Шаг 1</p>
              <h2>Официальный запуск внешней интеграции</h2>
            </div>
          </header>

          <div className="note-block">
            <p className="muted-label">Как пользоваться этой страницей</p>
            <p>1. Нажмите кнопку ниже и разрешите доступ для аккаунта educent.amocrm.ru.</p>
            <p>2. После закрытия popup нажмите «Обновить статус».</p>
            <p>3. Когда статус станет «Подключено», синхронизируйте поля контактов.</p>
          </div>

          {!integrationStatus?.redirect_uri || !integrationStatus?.secrets_uri ? (
            <p className="empty-state">
              Сервер ещё не знает redirect_uri или secrets_uri. Сначала проверьте настройки `.env` на VPS.
            </p>
          ) : (
            <div className="integration-button-panel">
              <p className="muted-label">Popup amoCRM откроется поверх этой страницы</p>
              <div className="integration-button-host" ref={buttonHostRef} />
              <p className="hint-text">
                Если браузер блокирует popup, разрешите всплывающее окно для{" "}
                <strong>api.fotonai.online</strong> и повторите запуск.
              </p>
            </div>
          )}
        </article>

        <article className="panel">
          <header className="panel-header">
            <div>
              <p className="panel-kicker">Шаг 2</p>
              <h2>Что уже знает AI Office</h2>
            </div>
          </header>

          {loading && !integrationStatus ? (
            <p className="empty-state">Загружаю параметры интеграции...</p>
          ) : (
            <>
              <div className="integration-details-grid">
                <article className="integration-detail-card">
                  <span>Redirect URI</span>
                  <strong>{integrationStatus?.redirect_uri || "Не задан"}</strong>
                </article>
                <article className="integration-detail-card">
                  <span>Secrets URI</span>
                  <strong>{integrationStatus?.secrets_uri || "Не задан"}</strong>
                </article>
                <article className="integration-detail-card">
                  <span>Источник токена</span>
                  <strong>{integrationStatus?.token_source || "Пока нет"}</strong>
                </article>
                <article className="integration-detail-card">
                  <span>Токен истекает</span>
                  <strong>{integrationStatus?.expires_at ? formatDate(integrationStatus.expires_at) : "Пока нет"}</strong>
                </article>
              </div>

              <div className="note-block">
                <p className="muted-label">Поля контактов, которые ждёт модуль CRM</p>
                {renderFieldList(
                  integrationStatus?.required_contact_fields_missing,
                  "Все обязательные поля уже найдены в amoCRM.",
                )}
              </div>

              <div className="note-block">
                <p className="muted-label">Поля, которые уже обнаружены</p>
                {renderFieldList(
                  integrationStatus?.required_contact_fields_present,
                  "Пока ни одно обязательное поле не синхронизировано.",
                )}
              </div>

              {integrationStatus?.last_error ? (
                <p className="error-banner">Последняя ошибка интеграции: {integrationStatus.last_error}</p>
              ) : null}
            </>
          )}
        </article>
      </section>
    </>
  );
}
