import { searchKey } from "./search";

/**
 * Pure state, persistence, and ordering helpers for the list review surfaces.
 *
 * The state intentionally contains no page data.  A tab owns the selected
 * identifiers and the small amount of context needed to return to a list;
 * query results remain API-owned and are never copied into this store.
 */

export const LIST_SELECTION_VERSION = 1 as const;
export const ORDER_PLANS_SELECTION_STORAGE_KEY = "bidops.order-plans.selection.v1";
export const PRE_SPECS_SELECTION_STORAGE_KEY = "bidops.pre-specs.selection.v1";

/** Both list surfaces use positive integer database primary keys. */
export type ListSelectionId = number;

export interface ListSelectionState<Id extends ListSelectionId = ListSelectionId, Metadata = unknown> {
  version: typeof LIST_SELECTION_VERSION;
  filterFingerprint: string;
  selectionGeneration: number;
  selectedIds: Id[];
  selectedSortMetadata: Record<string, Metadata>;
  listSearch: string;
  activeId: Id | null;
  listScrollTop: number;
}

export interface ListSelectionStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem?(key: string): void;
}

export type ListSelectionStorageErrorCode =
  | "storage_unavailable"
  | "storage_read_failed"
  | "storage_write_failed"
  | "invalid_state";

export interface ListSelectionStorageError {
  code: ListSelectionStorageErrorCode;
  message: string;
}

export interface ListSelectionReadResult<Id extends ListSelectionId = ListSelectionId, Metadata = unknown> {
  state: ListSelectionState<Id, Metadata> | null;
  status: "missing" | "restored" | "invalid" | "unavailable" | "error";
  error: ListSelectionStorageError | null;
}

export interface ListSelectionWriteResult {
  ok: boolean;
  error: ListSelectionStorageError | null;
}

export interface ListSelectionValidationOptions<Id extends ListSelectionId = ListSelectionId, Metadata = unknown> {
  isValidMetadata?: (value: unknown, id: Id) => value is Metadata;
}

export interface ListSelectionValidationResult<Id extends ListSelectionId = ListSelectionId, Metadata = unknown> {
  state: ListSelectionState<Id, Metadata> | null;
  error: ListSelectionStorageError | null;
}

export interface CreateListSelectionOptions<Id extends ListSelectionId = ListSelectionId, Metadata = unknown> {
  selectionGeneration?: number;
  selectedIds?: readonly Id[];
  selectedSortMetadata?: Record<string, Metadata>;
  listSearch?: string;
  activeId?: Id | null;
  listScrollTop?: number;
}

/** Positive, safe integer primary keys are the only supported list IDs. */
export function isListSelectionId(value: unknown): value is ListSelectionId {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isSelectionIdOf<Id extends ListSelectionId>(value: unknown): value is Id {
  return isListSelectionId(value);
}

export function dedupeIds<Id extends ListSelectionId>(
  ids: readonly Id[],
): Id[] {
  const result: Id[] = [];
  const seen = new Set<Id>();
  for (const id of ids) {
    if (!isListSelectionId(id) || seen.has(id)) continue;
    seen.add(id);
    result.push(id);
  }
  return result;
}

function metadataKey(id: ListSelectionId): `${number}` {
  return String(id) as `${number}`;
}

function isTimestampMetadata(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return "published_at" in record || "deadline_at" in record;
}

function normalizedGeneration(value: number | undefined): number {
  if (value === undefined || !Number.isSafeInteger(value) || value < 0) return 0;
  return value;
}

export function nextSelectionGeneration(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0) return 0;
  if (value >= Number.MAX_SAFE_INTEGER) return Number.MAX_SAFE_INTEGER;
  return value + 1;
}

export function createEmptyListSelection<Id extends ListSelectionId = ListSelectionId, Metadata = unknown>(
  filterFingerprint: string,
  options: CreateListSelectionOptions<Id, Metadata> = {},
): ListSelectionState<Id, Metadata> {
  const selectedIds = dedupeIds(options.selectedIds ?? []);
  const metadata: Record<string, Metadata> = {};
  for (const id of selectedIds) {
    const value = options.selectedSortMetadata?.[metadataKey(id)];
    if (value !== undefined) metadata[metadataKey(id)] = value;
  }
  return {
    version: LIST_SELECTION_VERSION,
    filterFingerprint,
    selectionGeneration: normalizedGeneration(options.selectionGeneration),
    selectedIds,
    selectedSortMetadata: metadata,
    listSearch: options.listSearch ?? "",
    activeId: options.activeId !== null
      && options.activeId !== undefined
      && isListSelectionId(options.activeId)
      ? options.activeId
      : null,
    listScrollTop: Number.isFinite(options.listScrollTop) && (options.listScrollTop ?? 0) >= 0
      ? options.listScrollTop ?? 0
      : 0,
  };
}

function invalidState(message: string): { state: null; error: ListSelectionStorageError } {
  return {
    state: null,
    error: { code: "invalid_state", message },
  };
}

/**
 * Validates and normalizes a decoded storage value.  Duplicate IDs are
 * removed in first-seen order; metadata for IDs not in the selection is
 * discarded so stale row data cannot leak back into a page.
 */
export function validateListSelection<Id extends ListSelectionId = ListSelectionId, Metadata = unknown>(
  value: unknown,
  options: ListSelectionValidationOptions<Id, Metadata> = {},
): ListSelectionValidationResult<Id, Metadata> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return invalidState("저장된 목록 선택 상태가 객체가 아닙니다.");
  }
  const record = value as Record<string, unknown>;
  if (record.version !== LIST_SELECTION_VERSION) {
    return invalidState("저장된 목록 선택 상태의 버전이 현재 화면과 다릅니다.");
  }
  if (typeof record.filterFingerprint !== "string") {
    return invalidState("저장된 목록 선택 상태에 필터 지문이 없습니다.");
  }
  if (!Number.isSafeInteger(record.selectionGeneration) || (record.selectionGeneration as number) < 0) {
    return invalidState("저장된 목록 선택 상태의 세대 값이 올바르지 않습니다.");
  }
  if (!Array.isArray(record.selectedIds)) {
    return invalidState("저장된 목록 선택 상태의 ID 목록이 올바르지 않습니다.");
  }
  if (typeof record.selectedSortMetadata !== "object" || record.selectedSortMetadata === null || Array.isArray(record.selectedSortMetadata)) {
    return invalidState("저장된 목록 선택 상태의 정렬 메타데이터가 올바르지 않습니다.");
  }
  if (typeof record.listSearch !== "string") {
    return invalidState("저장된 목록 선택 상태의 목록 검색어가 올바르지 않습니다.");
  }
  const activeId: Id | null = record.activeId === null
    ? null
    : isSelectionIdOf<Id>(record.activeId)
      ? record.activeId
      : null;
  if (record.activeId !== null && activeId === null) {
    return invalidState("저장된 목록 선택 상태의 활성 ID가 올바르지 않습니다.");
  }
  if (typeof record.listScrollTop !== "number" || !Number.isFinite(record.listScrollTop) || record.listScrollTop < 0) {
    return invalidState("저장된 목록 선택 상태의 목록 스크롤 위치가 올바르지 않습니다.");
  }

  const selectedIds: Id[] = [];
  const seen = new Set<Id>();
  for (const id of record.selectedIds) {
    if (!isSelectionIdOf<Id>(id)) return invalidState("저장된 목록 선택 상태에 올바르지 않은 ID가 있습니다.");
    if (!seen.has(id)) {
      seen.add(id);
      selectedIds.push(id);
    }
  }

  const metadata = record.selectedSortMetadata as Record<string, unknown>;
  const selectedSortMetadata: Record<string, Metadata> = {};
  for (const id of selectedIds) {
    const key = metadataKey(id);
    if (!(key in metadata)) continue;
    const entry = metadata[key];
    if (isTimestampMetadata(entry) && !isPreSpecSelectionSortMetadata(entry)) {
      return invalidState("저장된 목록 선택 상태의 사전규격 정렬 시각이 올바르지 않습니다.");
    }
    if (isPreSpecSelectionSortMetadata(entry) && entry.id !== id) {
      return invalidState("저장된 목록 선택 상태의 정렬 메타데이터 ID가 선택 ID와 다릅니다.");
    }
    if (options.isValidMetadata && !options.isValidMetadata(entry, id)) {
      return invalidState("저장된 목록 선택 상태의 정렬 메타데이터가 올바르지 않습니다.");
    }
    selectedSortMetadata[key] = entry as Metadata;
  }

  return {
    state: {
      version: LIST_SELECTION_VERSION,
      filterFingerprint: record.filterFingerprint,
      selectionGeneration: record.selectionGeneration as number,
      selectedIds,
      selectedSortMetadata,
      listSearch: record.listSearch,
      activeId,
      listScrollTop: record.listScrollTop,
    },
    error: null,
  };
}

export function getListSelectionStorage(): ListSelectionStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function readListSelection<Id extends ListSelectionId = ListSelectionId, Metadata = unknown>(
  key: string,
  storage: ListSelectionStorage | null = getListSelectionStorage(),
  options: ListSelectionValidationOptions<Id, Metadata> = {},
): ListSelectionReadResult<Id, Metadata> {
  if (!storage) {
    return {
      state: null,
      status: "unavailable",
      error: { code: "storage_unavailable", message: "이 탭의 목록 선택 저장소를 사용할 수 없습니다." },
    };
  }
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return {
      state: null,
      status: "error",
      error: { code: "storage_read_failed", message: "이 탭의 목록 선택 상태를 읽지 못했습니다." },
    };
  }
  if (raw === null) return { state: null, status: "missing", error: null };
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    return {
      state: null,
      status: "invalid",
      error: { code: "invalid_state", message: "저장된 목록 선택 상태의 JSON이 손상되었습니다." },
    };
  }
  const result = validateListSelection(decoded, options);
  return result.error
    ? { state: null, status: "invalid", error: result.error }
    : { state: result.state, status: "restored", error: null };
}

export function writeListSelection<Id extends ListSelectionId, Metadata>(
  key: string,
  state: ListSelectionState<Id, Metadata>,
  storage: ListSelectionStorage | null = getListSelectionStorage(),
): ListSelectionWriteResult {
  if (!storage) {
    return {
      ok: false,
      error: { code: "storage_unavailable", message: "이 탭의 목록 선택 저장소를 사용할 수 없어 복원 상태를 저장하지 못했습니다." },
    };
  }
  const validation = validateListSelection<Id, Metadata>(state);
  if (validation.error || !validation.state) {
    return { ok: false, error: validation.error ?? { code: "invalid_state", message: "목록 선택 상태를 저장할 수 없습니다." } };
  }
  try {
    storage.setItem(key, JSON.stringify(validation.state));
    return { ok: true, error: null };
  } catch {
    return {
      ok: false,
      error: { code: "storage_write_failed", message: "이 탭의 목록 선택 상태를 저장하지 못했습니다. 새로고침 복원을 제공할 수 없습니다." },
    };
  }
}

export function toggleSelection<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  id: Id,
  metadata?: Metadata,
): ListSelectionState<Id, Metadata> {
  if (!isListSelectionId(id)) return state;
  const index = state.selectedIds.indexOf(id);
  if (index >= 0) {
    const selectedIds = state.selectedIds.filter((value) => value !== id);
    const selectedSortMetadata = { ...state.selectedSortMetadata };
    delete selectedSortMetadata[metadataKey(id)];
    return { ...state, selectedIds, selectedSortMetadata };
  }
  const selectedSortMetadata = { ...state.selectedSortMetadata };
  if (metadata !== undefined) selectedSortMetadata[metadataKey(id)] = metadata;
  return {
    ...state,
    selectedIds: [...state.selectedIds, id],
    selectedSortMetadata,
  };
}

/**
 * spec §3.4: `전체 선택`은 현재 페이지의 `ids`를 기존 `selectedIds` 뒤에 순서
 * 그대로, 중복 없이 덧붙인다. 이미 선택된 id는 자리도 메타데이터도 바꾸지
 * 않고, 새 id의 메타데이터는 `toggleSelection`과 같은 규칙(값이 있을 때만
 * `metadataKey(id)`로 기록)을 따른다. 추가된 것이 없으면 같은 참조를 반환한다.
 */
export function selectMany<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  ids: readonly Id[],
  metadataById?: Record<string, Metadata>,
): ListSelectionState<Id, Metadata> {
  const existing = new Set(state.selectedIds);
  const additions = dedupeIds(ids).filter((id) => !existing.has(id));
  if (additions.length === 0) return state;
  const selectedSortMetadata = { ...state.selectedSortMetadata };
  for (const id of additions) {
    const metadata = metadataById?.[metadataKey(id)];
    if (metadata !== undefined) selectedSortMetadata[metadataKey(id)] = metadata;
  }
  return {
    ...state,
    selectedIds: [...state.selectedIds, ...additions],
    selectedSortMetadata,
  };
}

export function updateSelectionSortMetadata<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  id: Id,
  metadata: Metadata,
): ListSelectionState<Id, Metadata> {
  if (!state.selectedIds.includes(id)) return state;
  return {
    ...state,
    selectedSortMetadata: { ...state.selectedSortMetadata, [metadataKey(id)]: metadata },
  };
}

export function setSelectionActiveId<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  activeId: Id | null,
): ListSelectionState<Id, Metadata> {
  if (activeId !== null && !isListSelectionId(activeId)) return state;
  return state.activeId === activeId ? state : { ...state, activeId };
}

export function setSelectionContext<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  context: Pick<Partial<ListSelectionState<Id, Metadata>>, "listSearch" | "listScrollTop" | "activeId">,
): ListSelectionState<Id, Metadata> {
  const listSearch = context.listSearch === undefined ? state.listSearch : context.listSearch;
  const activeId = context.activeId === undefined
    ? state.activeId
    : context.activeId === null || isListSelectionId(context.activeId)
      ? context.activeId
      : state.activeId;
  const listScrollTop = context.listScrollTop === undefined
    ? state.listScrollTop
    : Number.isFinite(context.listScrollTop) && context.listScrollTop >= 0
      ? context.listScrollTop
      : 0;
  if (listSearch === state.listSearch && activeId === state.activeId && listScrollTop === state.listScrollTop) {
    return state;
  }
  return {
    ...state,
    listSearch,
    activeId,
    listScrollTop,
  };
}

export function resetSelectionForFilter<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  filterFingerprint: string,
): ListSelectionState<Id, Metadata> {
  if (state.filterFingerprint === filterFingerprint) return state;
  return {
    ...state,
    filterFingerprint,
    selectionGeneration: nextSelectionGeneration(state.selectionGeneration),
    selectedIds: [],
    selectedSortMetadata: {},
  };
}

export function clearSelection<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  incrementGeneration = true,
): ListSelectionState<Id, Metadata> {
  if (state.selectedIds.length === 0 && Object.keys(state.selectedSortMetadata).length === 0) return state;
  return {
    ...state,
    selectionGeneration: incrementGeneration
      ? nextSelectionGeneration(state.selectionGeneration)
      : state.selectionGeneration,
    selectedIds: [],
    selectedSortMetadata: {},
  };
}

/**
 * Remove only outcomes that belong to the request's generation.  Failed IDs
 * are deliberately omitted from `resolvedIds` and therefore remain selected.
 */
export function applySelectionResult<Id extends ListSelectionId, Metadata>(
  state: ListSelectionState<Id, Metadata>,
  resolvedIds: readonly Id[],
  expectedGeneration = state.selectionGeneration,
): ListSelectionState<Id, Metadata> {
  if (state.selectionGeneration !== expectedGeneration || resolvedIds.length === 0) return state;
  const resolved = new Set(resolvedIds);
  const selectedIds = state.selectedIds.filter((id) => !resolved.has(id));
  if (selectedIds.length === state.selectedIds.length) return state;
  const selectedSortMetadata = { ...state.selectedSortMetadata };
  for (const id of resolvedIds) delete selectedSortMetadata[metadataKey(id)];
  return { ...state, selectedIds, selectedSortMetadata };
}

type CanonicalValue = null | boolean | number | string | CanonicalValue[] | { [key: string]: CanonicalValue };

function canonicalValue(value: unknown): CanonicalValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) {
    const values = value.map(canonicalValue);
    return values.sort((left, right) => (JSON.stringify(left) ?? "").localeCompare(JSON.stringify(right) ?? ""));
  }
  if (typeof value === "object") {
    const result: { [key: string]: CanonicalValue } = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      const item = (value as Record<string, unknown>)[key];
      if (item !== undefined) result[key] = canonicalValue(item);
    }
    return result;
  }
  return null;
}

export function canonicalizeFilterValue(value: unknown): string {
  return JSON.stringify(canonicalValue(value));
}

type AppliedFilterTokens = readonly string[] | ReadonlySet<string>;

function canonicalFilterTokens(value: AppliedFilterTokens): string[] {
  return Array.from(value).sort();
}

/** Filter fingerprint for the order-plan list's applied semantic axes. */
export function orderPlansFilterFingerprint(filters: {
  sourceRunId: string | null;
  qwen: AppliedFilterTokens;
  stage1: AppliedFilterTokens;
  feedback: AppliedFilterTokens;
  tracking: AppliedFilterTokens;
  issue: boolean;
  q: string;
}): string {
  const normalized = {
    sourceRunId: filters.sourceRunId,
    qwen: canonicalFilterTokens(filters.qwen),
    stage1: canonicalFilterTokens(filters.stage1),
    feedback: canonicalFilterTokens(filters.feedback),
    tracking: canonicalFilterTokens(filters.tracking),
    issue: filters.issue,
    q: searchKey(filters.q),
  };
  return `order-plans:${canonicalizeFilterValue(normalized)}`;
}

/** Filter fingerprint for the pre-spec list's applied semantic axes. */
export function preSpecsFilterFingerprint(filters: {
  reviewExclusion?: string;
  swOnly: boolean;
  businessDivision: string;
  origin: string;
  grade: string;
  autoPreparationStatus: string;
  trackingDecision: string;
  trackingStatus?: string;
  workspace?: string;
  overviewView?: string;
  sourceRunId?: string;
  observedFrom?: string;
  observedTo?: string;
  deadlineStatus?: string;
  q: string;
}): string {
  const normalized = {
    reviewExclusion: filters.reviewExclusion ?? "all",
    swOnly: filters.swOnly,
    businessDivision: filters.businessDivision,
    origin: filters.origin,
    grade: filters.grade,
    autoPreparationStatus: filters.autoPreparationStatus,
    trackingDecision: filters.trackingDecision,
    trackingStatus: filters.trackingStatus ?? "",
    workspace: filters.workspace ?? "",
    overviewView: filters.overviewView ?? "",
    sourceRunId: filters.sourceRunId ?? "",
    observedFrom: filters.observedFrom ?? "",
    observedTo: filters.observedTo ?? "",
    deadlineStatus: filters.deadlineStatus ?? "",
    q: searchKey(filters.q),
  };
  return `pre-specs:${canonicalizeFilterValue(normalized)}`;
}

export interface OrderPlanSortable {
  order_plan_pk: number;
  qwen_relevance?: string | null;
}

const RELEVANCE_PRIORITY: Record<string, number> = {
  relevant: 0,
  uncertain: 1,
  not_relevant: 2,
  null: 3,
};

export function compareOrderPlanItems(left: OrderPlanSortable, right: OrderPlanSortable): number {
  const leftRank = RELEVANCE_PRIORITY[left.qwen_relevance ?? "null"] ?? RELEVANCE_PRIORITY.null;
  const rightRank = RELEVANCE_PRIORITY[right.qwen_relevance ?? "null"] ?? RELEVANCE_PRIORITY.null;
  if (leftRank !== rightRank) return leftRank - rightRank;
  return left.order_plan_pk - right.order_plan_pk;
}

export function sortOrderPlanItems<T extends OrderPlanSortable>(items: readonly T[]): T[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => compareOrderPlanItems(left.item, right.item) || left.index - right.index)
    .map(({ item }) => item);
}

export interface PreSpecSelectionSortMetadata {
  id: ListSelectionId;
  published_at: string | null;
  deadline_at: string | null;
  last_observed_at?: string | null;
}

export function isPreSpecSelectionSortMetadata(value: unknown): value is PreSpecSelectionSortMetadata {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  const hasObserved = keys.includes("last_observed_at");
  const expectedKeys = hasObserved
    ? ["deadline_at", "id", "last_observed_at", "published_at"]
    : ["deadline_at", "id", "published_at"];
  return keys.length === expectedKeys.length
    && expectedKeys.every((key, index) => keys[index] === key)
    && isListSelectionId(record.id)
    && (record.published_at === null || (typeof record.published_at === "string" && normalizeTimestamp(record.published_at) !== null))
    && (record.deadline_at === null || (typeof record.deadline_at === "string" && normalizeTimestamp(record.deadline_at) !== null))
    && (!hasObserved || record.last_observed_at === null || (typeof record.last_observed_at === "string" && normalizeTimestamp(record.last_observed_at) !== null));
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeapYear(year) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

/** Proleptic Gregorian day count used instead of Date (which remaps years 0–99). */
function daysFromCivil(year: number, month: number, day: number): number {
  const adjustedYear = year - (month <= 2 ? 1 : 0);
  const era = Math.floor(adjustedYear / 400);
  const yearOfEra = adjustedYear - era * 400;
  const monthIndex = month + (month > 2 ? -3 : 9);
  const dayOfYear = Math.floor((153 * monthIndex + 2) / 5) + day - 1;
  const dayOfEra = yearOfEra * 365
    + Math.floor(yearOfEra / 4)
    - Math.floor(yearOfEra / 100)
    + dayOfYear;
  return era * 146097 + dayOfEra - 719468;
}

/**
 * Converts an aware ISO/PostgreSQL timestamp into integer microseconds from
 * the Unix epoch.  Returning null for malformed values keeps the comparator
 * from treating an invalid server value as a meaningful date.
 */
export function normalizeTimestamp(value: string | null | undefined): bigint | null {
  if (typeof value !== "string" || value === "") return null;
  const match = /^(\d{4,6})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}(?::?\d{2})?)$/.exec(value);
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, fractionText = "", zone] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (fractionText.length > 6) return null;
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month) || hour > 23 || minute > 59 || second > 59) return null;
  let offsetMinutes = 0;
  if (zone !== "Z") {
    const sign = zone[0] === "-" ? -1 : 1;
    const digits = zone.slice(1).replace(":", "");
    const offsetHour = Number(digits.slice(0, 2));
    const offsetMinute = digits.length > 2 ? Number(digits.slice(2, 4)) : 0;
    if (offsetHour > 23 || offsetMinute > 59) return null;
    offsetMinutes = sign * (offsetHour * 60 + offsetMinute);
  }
  const fraction = Number(fractionText.padEnd(6, "0"));
  const utcSeconds = daysFromCivil(year, month, day) * 86_400
    + hour * 3_600
    + minute * 60
    + second
    - offsetMinutes * 60;
  return BigInt(utcSeconds) * 1_000_000n + BigInt(fraction);
}

function compareNullableTimestamp(left: string | null | undefined, right: string | null | undefined, direction: 1 | -1): number {
  if (left === undefined || right === undefined) {
    throw new Error("사전규격 정렬 메타데이터에 timestamp 필드가 없습니다.");
  }
  const leftValue = normalizeTimestamp(left);
  const rightValue = normalizeTimestamp(right);
  if (left !== null && leftValue === null) {
    throw new Error(`사전규격 정렬 메타데이터의 timestamp가 올바르지 않습니다: ${left}`);
  }
  if (right !== null && rightValue === null) {
    throw new Error(`사전규격 정렬 메타데이터의 timestamp가 올바르지 않습니다: ${right}`);
  }
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  if (leftValue === null || rightValue === null) {
    throw new Error("사전규격 정렬 메타데이터의 timestamp를 확인할 수 없습니다.");
  }
  if (leftValue === rightValue) return 0;
  return leftValue < rightValue ? -direction : direction;
}

function compareDeadlineTimestamp(left: string | null, right: string | null): number {
  if (left === null || right === null) return compareNullableTimestamp(left, right, 1);
  const leftValue = normalizeTimestamp(left);
  const rightValue = normalizeTimestamp(right);
  if (leftValue === null || rightValue === null) {
    throw new Error("사전규격 정렬 메타데이터의 마감 timestamp를 확인할 수 없습니다.");
  }
  const now = BigInt(Date.now()) * 1_000n;
  const leftPassed = leftValue < now;
  const rightPassed = rightValue < now;
  if (leftPassed !== rightPassed) return leftPassed ? 1 : -1;
  // Future deadlines are nearest first; past deadlines are most recently
  // passed first so the server and the selection-review order agree.
  if (leftValue === rightValue) return 0;
  if (leftPassed) return leftValue < rightValue ? 1 : -1;
  return leftValue < rightValue ? -1 : 1;
}

export function comparePreSpecMetadata(
  left: PreSpecSelectionSortMetadata,
  right: PreSpecSelectionSortMetadata,
  sort: "published" | "deadline" | "observed",
): number {
  if (!isPreSpecSelectionSortMetadata(left) || !isPreSpecSelectionSortMetadata(right)) {
    throw new Error("사전규격 정렬 메타데이터가 올바르지 않습니다.");
  }
  const timestampResult = sort === "published"
    ? compareNullableTimestamp(left.published_at, right.published_at, -1)
    : sort === "deadline"
      ? compareDeadlineTimestamp(left.deadline_at, right.deadline_at)
      // Old persisted selections predate observed metadata. Treat their
      // missing value as null so adding the recent sort does not invalidate
      // an otherwise restorable selection.
      : compareNullableTimestamp(left.last_observed_at ?? null, right.last_observed_at ?? null, -1);
  if (timestampResult !== 0) return timestampResult;
  if (left.id === right.id) return 0;
  const idResult = typeof left.id === "number" && typeof right.id === "number"
    ? left.id < right.id ? -1 : 1
    : String(left.id).localeCompare(String(right.id));
  return sort === "published" || sort === "observed" ? -idResult : idResult;
}

export function sortPreSpecMetadata(
  items: readonly PreSpecSelectionSortMetadata[],
  sort: "published" | "deadline" | "observed",
): PreSpecSelectionSortMetadata[] {
  for (const item of items) {
    if (!isPreSpecSelectionSortMetadata(item)) {
      throw new Error("사전규격 정렬 메타데이터가 올바르지 않습니다.");
    }
  }
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => comparePreSpecMetadata(left.item, right.item, sort) || left.index - right.index)
    .map(({ item }) => item);
}
