import type { BundleView } from "../components/deep-review/types";
import { attachmentOriginalUrl } from "./collectedWebUrl";
import type { FeatureState } from "./featureFlags";
import type { AttachmentResponse, PageOverviewCurrent, PageOverviewRangeReview, PreSpecListItem } from "./types";

/**
 * 사전규격 상세 `사업 개요와 주요 과업` 맨 위의 문제 상태 안내 한 블록(2026-11-21 시안 `docs/1121_prespec-detail/`
 * c1~c5, 근거 `docs/tracking/findings/model-review.md` 첫 항목).
 *
 * **이 파일이 사유 코드 → 문장 표를 모두 갖는다.** 화면은 이미 받은 서버 객체만 넘기고, 여기서는 상태를 새로
 * 판정하지 않는다. 문장은 고정 문자열이고 숫자·쪽 범위·파일 이름·실패한 문장은 서버 값을 그대로 끼운다(바꿔 쓰거나
 * 다시 계산하지 않는다). 값이 없으면 `미확인`이다. 모르는 사유 코드는 문장을 지어내지 않고 코드 그대로 보인다.
 *
 * 안내가 없는 상태(`null`)는 화면이 종전 문구·종전 기본 열림을 그대로 쓴다.
 */

export type PreSpecProblemKind =
  /** c1 — 개요 run `failed` + `input_capacity_exceeded`. */
  | "overview_range_too_wide"
  /** c2 — 개요 run `needs_human_review` + `semantic_review_failed`·`deterministic_check_failed`. */
  | "overview_draft_held"
  /** 그 밖의 개요 run `failed`·`needs_human_review`(`provider_http_error`·모르는 코드·사유 없음). */
  | "overview_run_problem"
  /** c3 — 최신 묶음이 확정 전이고 차단 issue가 있다. */
  | "document_blocked"
  /** c4 — 묶음 없이 `auto_preparation_reason=attachments_failed`. */
  | "attachments_failed"
  /** c5 — 묶음 확정(`bundle_ready`), 개요 run·범위 확인 자리 없음, 개요 자동 검토 켜짐, 의견 마감 전. */
  | "overview_waiting";

export type PreSpecProblemTone = "error" | "warning" | "neutral";

/** 열린 `처리 상태·기술 정보`에서 먼저 보일 블록. 나머지는 `나머지 기술 정보 보기` 뒤로 간다. */
export type PreSpecProcessBlock = "run" | "documents" | "fetch" | "steps";

export type PreSpecProblemAction =
  /** 범위 확정 폼을 안내 안에 바로 둔다(c1). */
  | { kind: "range_form" }
  /** `다른 범위로 다시 실행하기`를 누르면 범위 확정 폼이 열린다(c2·그 밖의 개요 문제). */
  | { kind: "range_form_toggle" }
  /** 이 run이 읽은 고정 PDF의 그 쪽. 완료 개요의 `PDF n페이지 ↗`와 같은 주소다. */
  | { kind: "pdf_page"; runId: string; page: number }
  /** `처리 상태·기술 정보`를 열고 문서 준비 패널로 옮긴다. */
  | { kind: "open_documents" }
  /** 원본 주소가 있는 첨부가 정확히 한 건일 때 그 주소. */
  | { kind: "attachment_original"; url: string }
  /** 그 밖에는 `원문·첨부` 구역으로 옮긴다. */
  | { kind: "evidence_section" };

export interface PreSpecProblemClaim {
  claimId: string;
  /** 서버가 준 문장 그대로. */
  text: string;
  /** 근거로 든 쪽(중복 없이 오름차순). 비어 있으면 근거 쪽이 없다. */
  pages: number[];
  /** 주장 사유 코드마다 고정 이름. 모르는 코드는 코드 그대로다. */
  reasonLabels: string[];
}

export interface PreSpecProblemNotice {
  kind: PreSpecProblemKind;
  /** 상태 단어(글자 표식). 색만으로 말하지 않는다. */
  tag: string;
  tone: PreSpecProblemTone;
  /** 무슨 일이 있었나(굵게). */
  lead: string;
  /** `이유` 줄. 문장들을 공백으로 잇는다. */
  reason: string[];
  /** c2의 맞지 않는 문장(서버 `failed_claims` 그대로). */
  claims: PreSpecProblemClaim[];
  /** `할 일` 줄. */
  todo: string;
  actions: PreSpecProblemAction[];
  /** 범위 폼 옆의 맥락 한 줄(`이전 범위 a~b쪽 · 전체 n쪽`). 폼이 없으면 `null`. */
  rangeContext: string | null;
  /** 작게 보이는 원 사유 코드. */
  codes: string[];
  /** 접힌 `처리 상태·기술 정보` 제목 줄의 요약(멈춘 단계를 말로). */
  foldSummary: string;
  firstBlock: PreSpecProcessBlock;
}

export interface PreSpecProblemNoticeInput {
  /** 현재 개요 run(`/overview` envelope의 `current`를 옮긴 것). 없으면 `null`. */
  overview: PageOverviewCurrent | null;
  rangeReview: PageOverviewRangeReview | null;
  /** 최신 revision 묶음. 없으면 `null`. */
  bundle: BundleView | null;
  item: PreSpecListItem | null;
  attachments: readonly AttachmentResponse[];
  /** 개요 자동 검토 기능 상태. `unknown`이면 대기 안내를 하지 않는다. */
  overviewFeature: FeatureState;
  /** 의견 마감이 지났는가. 마감을 모르면 `null`이고 대기 안내를 하지 않는다. */
  deadlinePassed: boolean | null;
}

const UNKNOWN = "미확인";

/* ── 개요 run 사유 ─────────────────────────────────────────────────────── */

/** 개요 run이 실패·보류된 사유 코드의 `이유` 문장. 여기에 없는 코드는 `사유 코드 <code>`로 보인다. */
const RUN_REASON_SENTENCE: Record<string, string> = {
  input_capacity_exceeded: "한 번에 읽을 수 있는 분량보다 많았어요.",
  semantic_review_failed: "초안 문장을 원문과 대조했더니 맞지 않는 문장이 있었어요.",
  deterministic_check_failed: "초안의 숫자·날짜·인용을 원문과 하나씩 대조했더니 맞지 않는 곳이 있었어요.",
  provider_http_error: "모델 서버에 요청했지만 오류 응답을 받았어요.",
  timeout: "제한 시간 안에 끝나지 않았어요.",
  draft_format_retry_exhausted: "모델이 쓴 초안이 정해진 형식을 두 번 모두 어겼어요.",
  semantic_response_invalid: "원문 대조 응답이 정해진 형식을 어겼어요.",
  manifest_invalid: "읽을 쪽에서 본문 글자를 얻지 못했어요.",
  overview_disabled: "개요 자동 검토가 꺼져 있어 기다리던 실행을 닫았어요.",
};

const RANGE_FALLBACK_SENTENCE = "사업 개요 위치를 자동으로 찾지 못해 범위를 넓게 잡았어요.";

/** 맞지 않는 문장마다 붙는 사유 이름. 여기에 없는 코드는 코드 그대로다. */
const CLAIM_REASON_LABEL: Record<string, string> = {
  insufficient_evidence: "근거 부족 · 그 쪽에서 이 내용을 찾지 못했어요",
  contradicted: "원문과 어긋남",
  quote_not_found: "인용문을 원문에서 찾지 못함",
  quote_ambiguous: "인용문 위치가 하나로 정해지지 않음",
  quote_empty: "인용문 없음",
  evidence_missing: "인용 없음",
  page_out_of_range: "읽은 범위 밖의 쪽",
  quantity_mismatch: "수치가 원문과 다름",
  quantity_metadata_mismatch: "수치의 단위·기준이 원문과 다름",
  quantity_unit_missing: "수치에 단위가 없음",
  date_mismatch: "날짜가 원문과 다름",
  role_mismatch: "역할·주체가 원문과 다름",
  negation_mismatch: "긍정·부정이 원문과 다름",
  condition_mismatch: "조건이 원문과 다름",
  obligation_strengthened: "원문보다 강한 의무로 바뀜",
  unsupported_fact: "원문이 뒷받침하지 않음",
};

/* ── 문서 준비 차단 사유 ───────────────────────────────────────────────── */

/** 차단 issue 코드 하나가 무엇을 말하는가. `file`은 issue가 가리킨 문서의 원래 파일 이름(서버 값)이다. */
const DOCUMENT_ISSUE: Record<string, { lead: string; reason: (file: string | null) => string; todo: string; fold: string }> = {
  ocr_issue: {
    lead: "문서 준비가 멈췄어요. 첨부 문서를 사람이 확인해야 해요",
    reason: (file) => `${file ? `${file}에서 ` : ""}첨부 문서의 글자 인식(OCR)이나 쪽 구조를 자동으로 확정하지 못했어요.`,
    todo: "문서 준비에서 문서를 확인하고 확정해 주세요. 확정해야 개요를 실행할 수 있어요.",
    fold: "문서 준비 막힘 · 문서 확인 필요",
  },
  attachment_bytes_missing: {
    lead: "문서 준비가 멈췄어요. 받지 못한 첨부가 있어요",
    reason: () => "문서 준비에는 모든 첨부의 원문이 필요한데 받지 못한 첨부가 있어요.",
    todo: "문서 준비에서 빠진 첨부를 확인해 주세요. 이 화면에서는 아직 첨부를 다시 받을 수 없어요.",
    fold: "문서 준비 막힘 · 받지 못한 첨부 있음",
  },
  structure_unavailable: {
    lead: "문서 준비가 멈췄어요. 첨부 문서를 사람이 확인해야 해요",
    reason: (file) => `${file ? `${file}에서 ` : ""}문서 구조를 확인하지 못했어요.`,
    todo: "문서 준비에서 문서를 확인하고 확정해 주세요. 확정해야 개요를 실행할 수 있어요.",
    fold: "문서 준비 막힘 · 문서 확인 필요",
  },
};

/** 차단 코드가 여럿이면 안내의 굵은 줄은 이 순서의 첫 코드가 정한다. 나머지 코드는 사유 코드 줄에 남는다. */
const DOCUMENT_ISSUE_PRIORITY = ["ocr_issue", "attachment_bytes_missing", "structure_unavailable"];

/* ── 대기 ──────────────────────────────────────────────────────────────── */

const WAITING_NOTICE = {
  lead: "개요 실행을 기다리고 있어요",
  reason: "원문 준비는 끝났고 개요는 아직 시작하지 않았어요.",
  todo: "따로 할 일은 없어요. 개요는 의견 마감 전이거나 추적 중인 사전규격에서 자동으로 진행해요. 마감이 지난 건은 추적을 시작하면 진행해요.",
} as const;

/* ── 보조 ──────────────────────────────────────────────────────────────── */

function pageRange(start: number | null, end: number | null): string | null {
  return start !== null && end !== null ? `${start}~${end}쪽` : null;
}

function totalPages(count: number | null): string {
  return count === null ? `전체 쪽수 ${UNKNOWN}` : `전체 ${count}쪽`;
}

function uniqueSorted(values: readonly number[]): number[] {
  return [...new Set(values)].sort((left, right) => left - right);
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)];
}

function attachmentCounts(item: PreSpecListItem | null): string {
  if (!item) return `첨부 취득 집계 ${UNKNOWN}`;
  const counts = item.document;
  return `첨부 ${counts.attachments}건 · 완료 ${counts["완료"]} · 대기 ${counts["대기"]} · 진행 ${counts["진행"]} · 차단 ${counts["차단"]} · 실패 ${counts["실패"]}`;
}

/** 범위 확정 폼을 안내 안에 둘 수 있는가. 사람이 확정해야 하는 자리(`needs_human_review`)일 때만이다. */
function rangeFormAvailable(rangeReview: PageOverviewRangeReview | null): boolean {
  return rangeReview?.selection_status === "needs_human_review";
}

function runReasonSentences(codes: readonly string[]): string[] {
  if (codes.length === 0) return [`사유 코드 ${UNKNOWN}.`];
  return codes.map((code) => RUN_REASON_SENTENCE[code] ?? `사유 코드 ${code}.`);
}

/* ── 개요 run 문제 ─────────────────────────────────────────────────────── */

function overviewRunNotice(run: PageOverviewCurrent, rangeReview: PageOverviewRangeReview | null): PreSpecProblemNotice | null {
  if (run.status !== "failed" && run.status !== "needs_human_review") return null;
  const codes = run.reason_codes;
  const range = pageRange(run.page_start, run.page_end);
  const total = totalPages(run.pdf_page_count);
  const formHere = rangeFormAvailable(rangeReview);
  const rangeContext = formHere ? `이전 범위 ${range ?? UNKNOWN} · ${total}` : null;
  const noFormTodo = rangeReview
    ? "처리 상태·기술 정보에서 개요 입력 범위와 실행 기록을 확인해 주세요."
    : "이 화면에서는 지금 범위를 다시 정할 수 없어요. 처리 상태·기술 정보에서 실행 기록을 확인해 주세요.";

  // c1 — 범위가 너무 넓어 호출 전 용량 검사에서 끝났다.
  if (run.status === "failed" && codes.includes("input_capacity_exceeded")) {
    // fallback도 화면이 아니라 서버가 자동으로 넓게 잡은 범위다(시안 c1 문장). 사람이 정한 범위만 다르게 부른다.
    const who = run.range_source === "human" ? "담당자가 정한 범위" : "자동으로 고른 범위";
    const subject = range ? `${who} ${range}(${total})이` : `${who}(${UNKNOWN}, ${total})가`;
    const reason = [`${subject} ${RUN_REASON_SENTENCE.input_capacity_exceeded}`];
    if (run.range_source === "fallback") reason.push(RANGE_FALLBACK_SENTENCE);
    for (const code of codes) if (code !== "input_capacity_exceeded") reason.push(RUN_REASON_SENTENCE[code] ?? `사유 코드 ${code}.`);
    return {
      kind: "overview_range_too_wide",
      tag: "개요 실패",
      tone: "error",
      lead: "개요를 만들지 못했어요. 읽을 범위가 너무 넓어요",
      reason,
      claims: [],
      todo: formHere
        ? "사업 개요가 있는 쪽으로 범위를 좁혀 확정해 주세요. 확정하면 그 범위로 개요를 한 번 새로 실행해요."
        : noFormTodo,
      actions: formHere ? [{ kind: "range_form" }] : [],
      rangeContext,
      codes: [...codes, `range_source ${run.range_source}`],
      foldSummary: formHere ? "개요 실패 · 범위 확정 필요" : "개요 실패 · 읽을 범위가 너무 넓음",
      firstBlock: "run",
    };
  }

  // c2 — 초안을 원문과 대조해 보류했다.
  const heldCode = codes.find((code) => code === "semantic_review_failed" || code === "deterministic_check_failed");
  if (run.status === "needs_human_review" && heldCode) {
    const claims: PreSpecProblemClaim[] = run.failed_claims.map((claim) => ({
      claimId: claim.claim_id,
      text: claim.text,
      pages: uniqueSorted(claim.evidence.map((evidence) => evidence.page)),
      reasonLabels: claim.reason_codes.map((code) => CLAIM_REASON_LABEL[code] ?? code),
    }));
    // 쪽 링크는 읽은 PDF 안의 쪽만 둔다. 앞에서부터 최대 두 쪽이다.
    const pdfPages = uniqueSorted(claims.flatMap((claim) => claim.pages))
      .filter((page) => page >= 1 && (run.pdf_page_count === null || page <= run.pdf_page_count))
      .slice(0, 2);
    const reason = [
      range ? `${range}을 읽고 초안을 만들었어요.` : "초안을 만들었어요.",
      ...codes.map((code) => RUN_REASON_SENTENCE[code] ?? `사유 코드 ${code}.`),
      claims.length > 0 ? `맞지 않는 문장은 ${claims.length}개예요.` : "맞지 않는 문장 목록은 비어 있어요.",
    ];
    const pagesText = pdfPages.map((page) => `${page}`).join("·");
    const todo = pdfPages.length > 0
      ? formHere
        ? `원문 ${pagesText}쪽을 열어 직접 확인하거나, 다른 범위를 확정해 개요를 다시 실행해 주세요.`
        : `원문 ${pagesText}쪽을 열어 직접 확인해 주세요.`
      : formHere
        ? "다른 범위를 확정해 개요를 다시 실행해 주세요."
        : noFormTodo;
    return {
      kind: "overview_draft_held",
      tag: "개요 보류",
      tone: "warning",
      lead: "개요 초안을 보류했어요. 원문과 맞지 않는 문장이 있어요",
      reason,
      claims,
      todo,
      actions: [
        ...(run.attempt_id ? pdfPages.map((page) => ({ kind: "pdf_page" as const, runId: run.attempt_id as string, page })) : []),
        ...(formHere ? [{ kind: "range_form_toggle" as const }] : []),
      ],
      rangeContext,
      codes: unique([...codes, run.status, ...run.failed_claims.flatMap((claim) => claim.reason_codes)]),
      foldSummary: "개요 보류 · 원문 대조 확인 필요",
      firstBlock: "run",
    };
  }

  // 그 밖의 실패·보류. 다시 실행 단추는 제품에 없으므로 범위 확정 폼만 다시 실행하는 길이다.
  const failed = run.status === "failed";
  return {
    kind: "overview_run_problem",
    tag: failed ? "개요 실패" : "개요 보류",
    tone: failed ? "error" : "warning",
    lead: failed ? "개요를 만들지 못했어요" : "개요 초안을 보류했어요",
    reason: runReasonSentences(codes),
    claims: [],
    todo: formHere
      ? "쪽 범위를 확정하면 그 범위로 개요를 한 번 새로 실행해요. 같은 범위로 다시 실행하는 단추는 이 화면에 없어요."
      : noFormTodo,
    actions: formHere ? [{ kind: "range_form_toggle" }] : [],
    rangeContext,
    codes: codes.length > 0 ? unique([...codes, run.status]) : [run.status, `사유 코드 ${UNKNOWN}`],
    foldSummary: failed ? "개요 실패 · 사유 확인 필요" : "개요 보류 · 사유 확인 필요",
    firstBlock: "run",
  };
}

/* ── 문서 준비·첨부 ────────────────────────────────────────────────────── */

function documentBlockedNotice(bundle: BundleView, item: PreSpecListItem | null): PreSpecProblemNotice | null {
  if (bundle.status === "ready" || bundle.status === "superseded") return null;
  const blocking = bundle.issues.filter((issue) => issue.blocking);
  if (blocking.length === 0) return null;
  const codes = unique(blocking.map((issue) => issue.code));
  const primaryCode = DOCUMENT_ISSUE_PRIORITY.find((code) => codes.includes(code)) ?? codes[0];
  const primaryIssue = blocking.find((issue) => issue.code === primaryCode) ?? null;
  const file = primaryIssue?.document_version_id
    ? bundle.documents.find((document) => document.id === primaryIssue.document_version_id)?.original_filename ?? null
    : null;
  const known = DOCUMENT_ISSUE[primaryCode];
  const reason = known
    ? [known.reason(file)]
    : ["문서 준비를 막는 이유가 있어요.", `사유 코드 ${primaryCode}.`];
  if (primaryCode === "attachment_bytes_missing") reason.push(`${attachmentCounts(item)}.`);
  const others = codes.length - 1;
  if (others > 0) reason.push(`그 밖에 막힌 이유가 ${others}가지 더 있어요.`);
  return {
    kind: "document_blocked",
    tag: "문서 준비 막힘",
    tone: "warning",
    lead: known?.lead ?? "문서 준비가 멈췄어요",
    reason,
    claims: [],
    todo: known?.todo ?? "문서 준비에서 막힌 이유를 확인해 주세요.",
    actions: [{ kind: "open_documents" }],
    rangeContext: null,
    codes,
    foldSummary: known?.fold ?? "문서 준비 막힘 · 사유 확인 필요",
    firstBlock: "documents",
  };
}

function attachmentsFailedNotice(item: PreSpecListItem, attachments: readonly AttachmentResponse[]): PreSpecProblemNotice {
  const counts = item.document;
  const blocked = counts["차단"];
  const failed = counts["실패"];
  const outcome = blocked > 0 && failed > 0
    ? `${blocked}건이 차단되고 ${failed}건이 실패했어요`
    : blocked > 0
      ? `${blocked}건이 차단됐어요`
      : failed > 0 ? `${failed}건이 실패했어요` : "받지 못했어요";
  const originals = attachments
    .map((attachment) => attachmentOriginalUrl(attachment.url))
    .filter((url): url is string => url !== null);
  const fold = blocked > 0 && failed > 0
    ? `첨부 받기 실패 · ${counts.attachments}건 중 차단 ${blocked} · 실패 ${failed}`
    : failed > 0
      ? `첨부 받기 실패 · ${counts.attachments}건 중 ${failed}건 실패`
      : `첨부 받기 실패 · ${counts.attachments}건 중 ${blocked}건 차단`;
  return {
    kind: "attachments_failed",
    tag: "첨부 받기 실패",
    tone: "error",
    lead: "첨부를 받지 못해 개요를 만들 수 없어요",
    reason: [
      `나라장터에서 첨부 ${counts.attachments}건을 받으려 했지만 ${outcome}.`,
      counts["완료"] === 0
        ? "받은 첨부가 없어 문서를 준비하지 못했어요."
        : "받은 첨부 중 쓸 수 있는 문서가 없어 문서를 준비하지 못했어요.",
    ],
    claims: [],
    todo: "원본 열기로 나라장터에서 첨부를 직접 확인해 주세요. 이 화면에서는 아직 첨부를 다시 받을 수 없어요.",
    actions: [originals.length === 1 ? { kind: "attachment_original", url: originals[0] } : { kind: "evidence_section" }],
    rangeContext: null,
    codes: ["attachments_failed", `첨부 ${counts.attachments}건`, `차단 ${blocked}`, `실패 ${failed}`],
    foldSummary: fold,
    firstBlock: "fetch",
  };
}

function waitingNotice(): PreSpecProblemNotice {
  return {
    kind: "overview_waiting",
    tag: "개요 대기",
    tone: "neutral",
    lead: WAITING_NOTICE.lead,
    reason: [WAITING_NOTICE.reason],
    claims: [],
    todo: WAITING_NOTICE.todo,
    actions: [],
    rangeContext: null,
    codes: ["bundle_ready", "개요 실행 기록 없음"],
    foldSummary: "원문 준비 완료 · 개요 대기",
    firstBlock: "steps",
  };
}

/**
 * 받은 서버 객체로 안내 하나를 고른다. 순서: 최신 묶음의 차단(c3) → 첨부 받기 실패(c4) → 개요 run 실패·보류(c1·c2·그 밖)
 * → 개요 대기(c5). 해당 없으면 `null`이다.
 *
 * c5는 확실할 때만 낸다: 자동 준비 상태가 `bundle_ready`이고 최신 묶음이 확정이며, 개요 run과 범위 확인 자리가 모두
 * 없고, 개요 자동 검토가 켜져 있고(`on`), 의견 마감이 지나지 않았다고 알 때. 마감이 지났거나 모르면, 또는 기능이
 * 꺼졌거나 모르면 종전 문구를 쓴다(추적 여부로 자동 처리 범위를 화면이 다시 계산하지 않는다).
 */
export function preSpecProblemNotice(input: PreSpecProblemNoticeInput): PreSpecProblemNotice | null {
  const { overview, rangeReview, bundle, item, attachments, overviewFeature, deadlinePassed } = input;
  if (bundle) {
    const blocked = documentBlockedNotice(bundle, item);
    if (blocked) return blocked;
  }
  if (bundle === null && item?.auto_preparation_reason === "attachments_failed") {
    return attachmentsFailedNotice(item, attachments);
  }
  if (overview) return overviewRunNotice(overview, rangeReview);
  if (
    item?.auto_preparation_status === "bundle_ready"
    && bundle?.status === "ready"
    && rangeReview === null
    && overviewFeature === "on"
    && deadlinePassed === false
  ) {
    return waitingNotice();
  }
  return null;
}
