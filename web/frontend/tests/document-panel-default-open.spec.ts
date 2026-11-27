import { expect, test } from "@playwright/test";
import type { BundleStatus, BundleView } from "../src/components/deep-review/types";
import { documentPanelDefaultOpen } from "../src/lib/documentPanelDefaultOpen";
import { preSpecProcessDefaultOpen, preSpecTechnicalInfoDefaultOpen } from "../src/lib/preSpecProcessDefaultOpen";
import type {
  CompanyFitAttempt,
  PageOverviewCurrent,
  PageOverviewRangeReview,
  PageOverviewVerification,
  PreSpecAutoPreparationStatus,
} from "../src/lib/types";

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
    // 2026-11-19: 개요가 끝난 확정 묶음(옛 `deep_review_ready_for_click`)은 심층 검토를 누를
    // 자리가 없어졌으므로 접힌 기본값이다.
    ["overview_settled", false],
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

// 2026-11-21 `처리 상태·기술 정보` 구역의 기본 열림(시안 `docs/specs/1121_prespec-detail/`). 기본은 닫힘이고, 옮겨 온 두 접힘
// (문서 준비 패널·기술 정보)이 스스로 열리던 조건과 범위 확정 필요만 합쳐 연다. 규칙 한 곳 = `preSpecProcessDefaultOpen`.
const readyBundle = bundle("ready");
const none = { bundle: null, overviewCurrent: null, companyFitAttempt: null, verification: null } as const;
const overview = (status: string) => ({ status }) as unknown as PageOverviewCurrent;
const fitAttempt = (status: string) => ({ status }) as unknown as CompanyFitAttempt;
const verification = (status: string) => ({ status }) as unknown as PageOverviewVerification;
const range = (selection_status: string) => ({ selection_status }) as unknown as PageOverviewRangeReview;

test("처리 상태 구역은 문제가 없으면 닫히고 문서 준비 조치·실패·사람 확인·범위 확정 필요일 때 열린다", () => {
  const closed = { ...none, bundle: readyBundle, autoStatus: "overview_settled" as PreSpecAutoPreparationStatus, rangeReview: null };
  expect(preSpecProcessDefaultOpen(closed), "정상(확정 묶음·개요 끝)").toBe(false);
  expect(preSpecProcessDefaultOpen({ ...closed, overviewCurrent: overview("completed") }), "개요 completed").toBe(false);
  expect(preSpecProcessDefaultOpen({ ...closed, rangeReview: range("ready") }), "범위 선택됨(사람 확정 불필요)").toBe(false);
  expect(preSpecProcessDefaultOpen({ ...closed, autoStatus: null }), "자동 준비 상태 미확인").toBe(false);

  // 문서 준비 패널이 열리던 조건(폴링이 멈추면 안 되므로 그대로 이어진다).
  expect(preSpecProcessDefaultOpen({ ...closed, bundle: null }), "묶음 없음").toBe(true);
  for (const status of ["draft", "processing", "needs_review", "quarantined", "failed"] as const) {
    expect(preSpecProcessDefaultOpen({ ...closed, bundle: bundle(status) }), `묶음 ${status}`).toBe(true);
  }
  for (const autoStatus of ["blocked", "waiting_attachments", "bundle_draft"] as const) {
    expect(preSpecProcessDefaultOpen({ ...closed, autoStatus }), `자동 준비 ${autoStatus}`).toBe(true);
  }
  // 접힌 기술 정보가 열리던 조건.
  for (const status of ["failed", "needs_human_review", "cancelled"]) {
    expect(preSpecProcessDefaultOpen({ ...closed, overviewCurrent: overview(status) }), `개요 ${status}`).toBe(true);
  }
  for (const status of ["failed", "needs_human_review"]) {
    expect(preSpecProcessDefaultOpen({ ...closed, companyFitAttempt: fitAttempt(status) }), `회사 적합성 ${status}`).toBe(true);
  }
  expect(preSpecProcessDefaultOpen({ ...closed, companyFitAttempt: fitAttempt("completed") }), "회사 적합성 completed").toBe(false);
  expect(preSpecProcessDefaultOpen({ ...closed, verification: verification("needs_human_review") }), "주장 검증 사람 확인").toBe(true);
  expect(preSpecProcessDefaultOpen({ ...closed, verification: verification("passed") }), "주장 검증 passed").toBe(false);
  // 시안 a3: 사람이 범위를 확정해야 하는 상태.
  expect(preSpecProcessDefaultOpen({ ...closed, rangeReview: range("needs_human_review") }), "범위 확정 필요").toBe(true);
});

test("기술 정보 접힘의 기본 열림은 문서 준비 조건과 별개로 개요·회사 적합성·묶음·검증 실패만 본다", () => {
  expect(preSpecTechnicalInfoDefaultOpen(none)).toBe(false);
  // 문서 준비 패널이 열리는 조건(묶음 없음·draft)만으로는 기술 정보를 열지 않는다.
  expect(preSpecTechnicalInfoDefaultOpen({ ...none, bundle: bundle("draft") })).toBe(false);
  for (const status of ["failed", "quarantined", "needs_review"] as const) {
    expect(preSpecTechnicalInfoDefaultOpen({ ...none, bundle: bundle(status) }), `묶음 ${status}`).toBe(true);
  }
  expect(preSpecTechnicalInfoDefaultOpen({ ...none, overviewCurrent: overview("failed") })).toBe(true);
  expect(preSpecTechnicalInfoDefaultOpen({ ...none, companyFitAttempt: fitAttempt("needs_human_review") })).toBe(true);
  expect(preSpecTechnicalInfoDefaultOpen({ ...none, verification: verification("needs_human_review") })).toBe(true);
});
