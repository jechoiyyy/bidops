import { expect, test } from "@playwright/test";
import type { BundleStatus, BundleView } from "../src/components/deep-review/types";
import { documentPanelDefaultOpen } from "../src/lib/documentPanelDefaultOpen";
import type { PreSpecAutoPreparationStatus } from "../src/lib/types";

function bundle(status: BundleStatus): BundleView {
  return {
    id: "panel-rule",
    notice_id: 991,
    revision: 1,
    version: 1,
    status,
    documents: [],
    issues: [],
    confirmed_by: null,
    confirmed_at: null,
    created_at: "2026-09-01T00:00:00Z",
  };
}

test("문서 준비 기본 열림은 조치와 처리 중 폴링을 우선한다", () => {
  expect(documentPanelDefaultOpen(null, "deep_review_started")).toBe(true);
  for (const status of ["draft", "processing", "needs_review", "quarantined", "failed"] as const) {
    expect(documentPanelDefaultOpen(bundle(status), "deep_review_started"), status).toBe(true);
  }
  const cases: [PreSpecAutoPreparationStatus, boolean][] = [
    ["deep_review_ready_for_click", true],
    ["blocked", true],
    ["waiting_attachments", true],
    ["bundle_draft", true],
    ["not_applicable", false],
    ["bundle_ready", false],
    ["overview_running", false],
    ["deep_review_started", false],
  ];
  for (const status of ["ready", "superseded"] as const) {
    for (const [autoStatus, open] of cases) {
      expect(documentPanelDefaultOpen(bundle(status), autoStatus), `${status}/${autoStatus}`).toBe(open);
    }
    expect(documentPanelDefaultOpen(bundle(status), null), `${status}/unknown`).toBe(false);
  }
});
