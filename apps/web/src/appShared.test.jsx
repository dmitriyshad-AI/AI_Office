import { afterEach, describe, expect, it, vi } from "vitest";
import {
  collectBlockingPreflightChecks,
  formatCallMatchStatus,
  formatCallPriority,
  formatCallProcessingStatus,
  formatReviewStatus,
  inferEventScope,
  isDateWithinWindow,
  isTechnicalProject,
  matchesModuleKeywords,
  requestJson,
  reviewNeedsOperatorAction,
} from "./appShared";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("appShared helpers", () => {
  it("covers additional label fallbacks and operator review helper", () => {
    expect(formatReviewStatus("rejected")).toBe("Отклонено");
    expect(formatReviewStatus("custom_review")).toBe("custom_review");
    expect(formatCallMatchStatus("family_match_needed")).toBe("family_match_needed");
    expect(formatCallPriority("")).toBe("Не указано");
    expect(formatCallProcessingStatus("manual_hold")).toBe("manual_hold");
    expect(reviewNeedsOperatorAction("approved")).toBe(false);
    expect(reviewNeedsOperatorAction("not_required")).toBe(false);
    expect(reviewNeedsOperatorAction("pending")).toBe(true);
  });

  it("covers empty preflight, date fallback windows and technical project guard", () => {
    expect(collectBlockingPreflightChecks(null)).toEqual([]);
    expect(isDateWithinWindow("2026-03-19T09:00:00.000Z", "custom")).toBe(true);
    expect(isTechnicalProject(null)).toBe(false);
  });

  it("covers event scopes and keyword matching branches", () => {
    expect(inferEventScope("task_run_started")).toBe("runtime");
    expect(inferEventScope("approval_requested")).toBe("approvals");
    expect(inferEventScope("unknown_event")).toBe("office");
    expect(matchesModuleKeywords({ keywords: ["crm", "amo"] }, "CRM integration")).toBe(true);
    expect(matchesModuleKeywords({ keywords: ["crm"] }, "")).toBe(false);
    expect(matchesModuleKeywords(null, "crm")).toBe(false);
  });

  it("falls back to status code message when api error body is empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        async text() {
          return "";
        },
      }),
    );

    await expect(requestJson("/empty-error")).rejects.toThrow("Request failed with 503");
  });
});
