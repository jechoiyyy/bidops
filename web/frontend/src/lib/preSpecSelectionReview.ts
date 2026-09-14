import { generateRequestId } from "./requestId";

const REVIEW_KEY_PREFIX = "bidops.pre-specs.review.v1.";
const TOKEN_PARAM = "selection_review";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const LIST_PARAMS = new Set([
  "sw_only", "business_division", "origin", "grade", "auto_preparation_status",
  "tracking_decision", "view", "q", "sort", "offset", "selected", "run",
]);

export interface PreSpecSelectionReview {
  version: 1;
  reviewId: string;
  orderedNoticeIds: number[];
  listSearch: string;
  filterFingerprint: string;
  selectionGeneration: number;
  entryNoticeId: number;
}

export type ReviewStorageResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

/** Only list-owned query parameters may cross the detail/list boundary. */
export function preSpecListSearch(search: string): string {
  const params = new URLSearchParams(search);
  for (const key of [...params.keys()]) {
    if (!LIST_PARAMS.has(key)) params.delete(key);
  }
  return params.toString();
}

export function preSpecListUrl(search: string): string {
  const query = preSpecListSearch(search);
  return `/pre-specs${query ? `?${query}` : ""}`;
}

export function preSpecDetailUrl(noticeId: number, search: string, reviewId?: string): string {
  const params = new URLSearchParams(preSpecListSearch(search));
  if (reviewId) params.set(TOKEN_PARAM, reviewId);
  const query = params.toString();
  return `/pre-specs/${noticeId}${query ? `?${query}` : ""}`;
}

function validId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isReview(value: unknown): value is PreSpecSelectionReview {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const fields = ["version", "reviewId", "orderedNoticeIds", "listSearch",
    "filterFingerprint", "selectionGeneration", "entryNoticeId"];
  if (Object.keys(record).length !== fields.length || fields.some((key) => !(key in record))) return false;
  return record.version === 1 && typeof record.reviewId === "string" && UUID.test(record.reviewId)
    && Array.isArray(record.orderedNoticeIds) && record.orderedNoticeIds.length > 0
    && record.orderedNoticeIds.every(validId)
    && new Set(record.orderedNoticeIds).size === record.orderedNoticeIds.length
    && typeof record.listSearch === "string"
    && preSpecListSearch(record.listSearch) === record.listSearch
    && typeof record.filterFingerprint === "string"
    && record.filterFingerprint.length > 0
    && typeof record.selectionGeneration === "number"
    && Number.isSafeInteger(record.selectionGeneration) && record.selectionGeneration >= 0
    && validId(record.entryNoticeId) && record.orderedNoticeIds.includes(record.entryNoticeId);
}

/** Call only after the existing unsaved-input guard approves navigation. */
export function createPreSpecSelectionReview(
  input: Omit<PreSpecSelectionReview, "version" | "reviewId">,
): ReviewStorageResult<PreSpecSelectionReview> {
  let reviewId: string;
  try {
    reviewId = generateRequestId();
  } catch {
    return {
      ok: false,
      error: "보안 난수를 생성하지 못해 선택 검토를 시작할 수 없습니다. 브라우저의 보안 난수 기능을 확인한 뒤 다시 시도해 주세요.",
    };
  }

  try {
    const snapshot: PreSpecSelectionReview = {
      ...input,
      version: 1,
      reviewId,
      orderedNoticeIds: [...input.orderedNoticeIds],
      listSearch: preSpecListSearch(input.listSearch),
    };
    if (!isReview(snapshot)) return { ok: false, error: "선택 검토 순서를 확인할 수 없습니다. 목록을 다시 확인해 주세요." };
    const serialized = JSON.stringify(snapshot);
    const key = REVIEW_KEY_PREFIX + snapshot.reviewId;
    sessionStorage.setItem(key, serialized);
    if (sessionStorage.getItem(key) !== serialized) {
      return { ok: false, error: "이 탭에 검토 순서를 저장하지 못했습니다. 단건 상세를 이용해 주세요." };
    }
    return { ok: true, value: snapshot };
  } catch {
    return { ok: false, error: "이 탭에 검토 순서를 저장하지 못했습니다. 브라우저 저장소 설정을 확인하거나 단건 상세를 이용해 주세요." };
  }
}

/** Invalid/missing context is single-record mode, never an inferred selection. */
export function readPreSpecSelectionReview(
  search: string,
  noticeId: number | null,
): PreSpecSelectionReview | null {
  const params = new URLSearchParams(search);
  const tokens = params.getAll(TOKEN_PARAM);
  const token = tokens[0];
  if (tokens.length !== 1 || !token || !UUID.test(token) || !validId(noticeId)) return null;
  try {
    const raw = sessionStorage.getItem(REVIEW_KEY_PREFIX + token);
    if (raw === null) return null;
    const snapshot: unknown = JSON.parse(raw);
    if (!isReview(snapshot) || snapshot.reviewId !== token || !snapshot.orderedNoticeIds.includes(noticeId)) return null;
    return snapshot;
  } catch {
    return null;
  }
}

export function preSpecReviewListUrl(search: string, noticeId: number | null): string {
  const review = readPreSpecSelectionReview(search, noticeId);
  return preSpecListUrl(review?.listSearch ?? search);
}
