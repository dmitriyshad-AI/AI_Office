import { afterEach, describe, expect, it, vi } from "vitest";
import {
  collectBlockingPreflightChecks,
  displayAgentBadge,
  displayAgentRole,
  displayAgentStatus,
  eventTitle,
  formatCrmStatus,
  formatDate,
  formatTaskStatus,
  inferEventScope,
  isDateWithinWindow,
  isTechnicalProject,
  labelFromMap,
  requestJson,
  shortenText,
  statusClass,
  summarizeEventPayload,
} from "./App";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("App helpers", () => {
  it("formats labels and fallbacks", () => {
    expect(labelFromMap({ a: "A" }, "a")).toBe("A");
    expect(labelFromMap({ a: "A" }, "b", "fallback")).toBe("b");
    expect(labelFromMap({}, "", "fallback")).toBe("fallback");
  });

  it("formats task and crm status labels", () => {
    expect(formatTaskStatus("ready")).toBe("Готова к запуску");
    expect(formatCrmStatus("sent")).toBe("Отправлено");
  });

  it("normalizes visual helpers", () => {
    expect(statusClass("changes_requested")).toBe("changes-requested");
    expect(displayAgentRole("Director")).toBe("Директор");
    expect(displayAgentStatus("running")).toBe("В работе");
    expect(displayAgentBadge("BackendEngineer")).toBe("BE");
    expect(displayAgentBadge("")).toBe("AG");
  });

  it("formats date and text helpers", () => {
    expect(formatDate("2026-03-19T09:00:00.000Z")).toContain("19.03.2026");
    expect(shortenText("abcdef", 3)).toContain("...");
    expect(shortenText("", 3)).toBe("");
  });

  it("builds event titles and summaries", () => {
    expect(eventTitle("crm_send_failed")).toBe("Ошибка отправки в AMO");
    expect(eventTitle("project_archived")).toBe("Проект перенесён в архив");
    expect(eventTitle("custom_event")).toBe("Custom Event");
    expect(eventTitle("")).toBe("Событие");
    expect(summarizeEventPayload({ a: 1, b: 2 })).toContain("a: 1");
    expect(summarizeEventPayload({})).toBe("Без деталей");
    expect(inferEventScope("crm_send_failed")).toBe("crm");
    expect(inferEventScope("call_insight_ingested")).toBe("calls");
    expect(inferEventScope("director_progress_update")).toBe("director");
  });

  it("filters blocking preflight checks and checks windows", () => {
    expect(
      collectBlockingPreflightChecks({
        checks: [
          { key: "a", status: "fail", blocking: true },
          { key: "b", status: "warn", blocking: true },
        ],
      }),
    ).toHaveLength(1);
    expect(isDateWithinWindow("2026-03-19T09:00:00.000Z", "all")).toBe(true);
    expect(isDateWithinWindow(new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), "24h")).toBe(true);
    expect(isDateWithinWindow(new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), "7d")).toBe(true);
    expect(isDateWithinWindow(new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(), "30d")).toBe(true);
    expect(isDateWithinWindow(new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(), "30d")).toBe(false);
    expect(isDateWithinWindow("bad-date", "24h")).toBe(false);
    expect(isTechnicalProject({ name: "Smoke Probe", description: "Технический прогон" })).toBe(true);
    expect(isTechnicalProject({ name: "CRM Office", description: "Рабочий проект" })).toBe(false);
  });

  it("performs successful json requests", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        async json() {
          return { ok: true };
        },
      }),
    );

    await expect(requestJson("/health")).resolves.toEqual({ ok: true });
  });

  it("surfaces api detail and plain-text errors", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        async text() {
          return JSON.stringify({ detail: "bad request" });
        },
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        async text() {
          return "server exploded";
        },
      });
    vi.stubGlobal("fetch", fetch);

    await expect(requestJson("/bad")).rejects.toThrow("bad request");
    await expect(requestJson("/worse")).rejects.toThrow("server exploded");
  });

  it("turns abort errors into timeout messages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("Timed out", "AbortError")));

    await expect(requestJson("/slow")).rejects.toThrow("API не отвечает дольше 10 сек.");
  });
});
