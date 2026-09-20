import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ApiError, ORDER_PLAN_BULK_END_MAX_SELECTION, api, OrderPlanBulkTrackingResultUnconfirmedError } from "../../lib/api";
import { describeOrderPlanBulkTrackingError } from "../../lib/apiErrors";
import { generateRequestId } from "../../lib/requestId";
import type {
  OrderPlanBulkPreviewResponse,
  OrderPlanBulkReceipt,
  OrderPlanBulkSummary,
} from "../../lib/types";
import "../../styles/order-plans.css";

/** 일괄 추적 시작과 종료(ADR-0063)는 같은 상태 기계를 목표 상태만 바꿔 쓴다. */
export type OrderPlanBulkTrackingMode = "start" | "end";

export interface OrderPlanBulkTrackingDialogProps {
  open: boolean;
  /** 목표 작업. 문구·호출 endpoint만 이 값으로 가른다 — 단계 흐름은 공유한다. */
  mode: OrderPlanBulkTrackingMode;
  selectedIds: readonly number[];
  selectionGeneration: number;
  filterFingerprint: string;
  actorName: string;
  onClose: () => void;
  /** `summary`는 A4의 종료 안내 줄이 성공 건수(`succeeded_plan_count`)를 읽는 자리다. */
  onApplied: (resolvedIds: readonly number[], generation: number, summary: OrderPlanBulkSummary) => void;
  onInvalidate: () => Promise<void> | void;
  onPersistSelection?: () => { ok: boolean; error?: { message?: string } | null };
  onPendingChange?: (pending: boolean) => void;
  /** The list selection hook's storage status. */
  storageAvailable: boolean;
  storageError?: string | null;
}

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type BulkPhase = "edit" | "previewing" | "confirming" | "pending" | "result" | "unknown" | "error";

interface PendingBulkRequest {
  request_id: string;
  order_plan_ids: number[];
  actor: string;
  reason: string;
  selection_generation: number;
  filter_fingerprint: string;
  /** ADR-0063: 저장된 요청이 어느 endpoint로 가는지. 열린 다이얼로그의 `mode`보다 우선한다. */
  action: OrderPlanBulkTrackingMode;
}

interface PreviewBinding {
  ids: number[];
  selection_generation: number;
  filter_fingerprint: string;
}

interface BulkDialogCopy {
  dialogTitle: string;
  subtitle: string;
  confirmHeading: string;
  reasonLabel: string;
  reasonPlaceholder: string;
  reasonRequiredError: string;
  eligibleLabel: string;
  confirmButtonLabel: string;
  cannotStartMessage: string;
  storageUnavailableTitle: string;
  writeErrorSuffix: string;
  pendingHeading: string;
  unknownFallbackTitle: string;
  resultHeading: string;
  resultExtraNote: string | null;
  failuresAriaLabel: string;
  errorFallbackDescription: string;
  endWarning: string | null;
  confirmDisabledFallback: string;
  overSelectionMessage: string;
}

/** 문구는 여기 한 곳에 모은다. 단계 흐름·검증·복구 로직은 모드와 무관하게 공유한다. */
const COPY: Record<OrderPlanBulkTrackingMode, BulkDialogCopy> = {
  start: {
    dialogTitle: "발주계획 일괄 추적",
    subtitle: "미선택 상태인 계획만 계속 추적으로 저장합니다. 이미 결정된 상태와 소유권을 확인할 수 없는 항목은 바꾸지 않습니다.",
    confirmHeading: "",
    reasonLabel: "공통 추적 사유",
    reasonPlaceholder: "선택한 계획을 함께 추적하는 이유",
    reasonRequiredError: "공통 추적 사유를 입력하십시오.",
    eligibleLabel: "미선택 · 실행 가능",
    confirmButtonLabel: "확인하고 일괄 추적 시작",
    cannotStartMessage: "일괄 추적을 시작할 수 없습니다. 선택 저장소를 사용할 수 없어 단건 추적 경로를 사용하십시오.",
    storageUnavailableTitle: "일괄 추적을 사용할 수 없습니다.",
    writeErrorSuffix: "일괄 추적을 보내지 않았습니다. 단건 추적 경로를 사용하십시오.",
    pendingHeading: "일괄 추적 저장 중",
    unknownFallbackTitle: "일괄 추적 결과를 확인할 수 없습니다.",
    resultHeading: "일괄 추적 결과를 확인했습니다.",
    resultExtraNote: null,
    failuresAriaLabel: "일괄 추적 실패 항목",
    errorFallbackDescription: "일괄 추적 작업을 완료하지 못했습니다.",
    endWarning: null,
    confirmDisabledFallback: "담당자 이름과 공통 추적 사유를 입력해야 저장할 수 있습니다.",
    overSelectionMessage: "",
  },
  end: {
    dialogTitle: "발주계획 일괄 추적 종료",
    subtitle: "추적을 아직 정하지 않은 계획만 추적 종료로 저장합니다",
    confirmHeading: "추적 종료 내용을 확인하십시오",
    reasonLabel: "공통 종료 사유",
    reasonPlaceholder: "선택한 계획의 추적을 끝내는 이유",
    reasonRequiredError: "공통 종료 사유를 입력하십시오.",
    eligibleLabel: "미선택 · 종료 가능",
    confirmButtonLabel: "확인하고 일괄 추적 종료",
    cannotStartMessage: "일괄 추적 종료를 시작할 수 없습니다. 선택 저장소를 사용할 수 없어 단건 추적 경로를 사용하십시오.",
    storageUnavailableTitle: "일괄 추적 종료를 사용할 수 없습니다.",
    writeErrorSuffix: "일괄 추적 종료를 보내지 않았습니다. 단건 추적 경로를 사용하십시오.",
    pendingHeading: "일괄 추적 종료 저장 중",
    unknownFallbackTitle: "일괄 추적 종료 결과를 확인할 수 없습니다.",
    resultHeading: "일괄 추적 종료 결과를 확인했습니다.",
    resultExtraNote: "종료한 건은 추적 필터 '종료'와 사업 추적의 '추적 종료' 구역에서 볼 수 있습니다.",
    failuresAriaLabel: "일괄 추적 종료 실패 항목",
    errorFallbackDescription: "일괄 추적 종료 작업을 완료하지 못했습니다.",
    endWarning: "종료한 계획은 기본 보기(검토 대상)에서 사라집니다. 추적 필터 '종료'에서 한 건씩 되돌릴 수 있고, 한꺼번에 되돌리는 기능은 없습니다.",
    confirmDisabledFallback: "담당자 이름과 공통 종료 사유를 입력해야 저장할 수 있습니다.",
    overSelectionMessage: `한 번에 ${ORDER_PLAN_BULK_END_MAX_SELECTION}건까지 종료할 수 있습니다. 선택을 줄이십시오.`,
  },
};

const PENDING_STORAGE_KEY = "bidops.order-plans.bulk-tracking.pending.v2";
/** v1 잔존분 마이그레이션 전용. 새로 쓰지 않는다 — 읽고 나면 v2로 옮기고 지운다. */
const LEGACY_PENDING_STORAGE_KEY_V1 = "bidops.order-plans.bulk-tracking.pending.v1";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Backend human-name validation mirrored only for preflight UX. */
function validateActor(value: string): string | null {
  const clean = value.trim();
  if (!clean) return "공통 담당자 이름을 입력하십시오.";
  if ([...clean].length > 128) return "담당자 이름은 128자 이하여야 합니다.";
  // C0, DEL, and C1 controls are rejected by the tracking service.
  if (/[\u0000-\u001f\u007f-\u009f]/u.test(clean)) return "담당자 이름에 제어 문자를 넣을 수 없습니다.";
  if (/^system$/iu.test(clean)) return "담당자 이름으로 system을 사용할 수 없습니다.";
  return null;
}

function validateReason(value: string, requiredError: string): string | null {
  return value.trim() ? null : requiredError;
}

function getStorage(): StorageLike | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

const PENDING_KEYS_V2 = [
  "request_id", "order_plan_ids", "actor", "reason", "selection_generation", "filter_fingerprint", "action",
] as const;
const LEGACY_PENDING_KEYS_V1 = [
  "request_id", "order_plan_ids", "actor", "reason", "selection_generation", "filter_fingerprint",
] as const;

function validPendingCore(record: Record<string, unknown>): boolean {
  if (typeof record.request_id !== "string" || !UUID_PATTERN.test(record.request_id)
    || typeof record.actor !== "string" || validateActor(record.actor) !== null
    || typeof record.reason !== "string" || !record.reason.trim()
    || typeof record.filter_fingerprint !== "string"
    || !record.filter_fingerprint
    || !Number.isSafeInteger(record.selection_generation) || (record.selection_generation as number) < 0
    || !Array.isArray(record.order_plan_ids) || record.order_plan_ids.length === 0) return false;
  const ids = record.order_plan_ids;
  return ids.every((id) => typeof id === "number" && Number.isSafeInteger(id) && id > 0)
    && ids.every((id, index) => index === 0 || ids[index - 1] < id);
}

function validPending(value: unknown): value is PendingBulkRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).length !== PENDING_KEYS_V2.length || PENDING_KEYS_V2.some((key) => !(key in record))) return false;
  if (record.action !== "start" && record.action !== "end") return false;
  return validPendingCore(record);
}

/** v1 키(`action` 없이 항상 시작이던 시절)에 남은 잔존분만 읽는 검사다. */
function validLegacyPendingV1(value: unknown): value is Omit<PendingBulkRequest, "action"> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).length !== LEGACY_PENDING_KEYS_V1.length
    || LEGACY_PENDING_KEYS_V1.some((key) => !(key in record))) return false;
  return validPendingCore(record);
}

/**
 * v1 키에 남은 요청을 `action: "start"`로 읽어 v2로 옮긴다. v1은 시작만 있던 시절의
 * 계약이라 그 뜻 그대로 보존하고, v2에 다시 쓴 뒤 v1 키를 지운다(A2 마이그레이션).
 */
function readLegacyPendingV1(storage: StorageLike): { value: PendingBulkRequest | null; error: string | null } {
  let legacyRaw: string | null;
  try {
    legacyRaw = storage.getItem(LEGACY_PENDING_STORAGE_KEY_V1);
  } catch {
    return { value: null, error: "이 탭의 일괄 요청 저장소를 읽지 못했습니다." };
  }
  if (legacyRaw === null) return { value: null, error: null };
  let legacyValue: unknown;
  try {
    legacyValue = JSON.parse(legacyRaw);
  } catch {
    return { value: null, error: "저장된 일괄 요청을 읽지 못했습니다." };
  }
  if (!validLegacyPendingV1(legacyValue)) {
    return { value: null, error: "저장된 일괄 요청 형식이 올바르지 않습니다." };
  }
  const migrated: PendingBulkRequest = { ...legacyValue, action: "start" };
  const writeError = savePending(migrated);
  if (writeError) return { value: null, error: writeError };
  try {
    storage.removeItem(LEGACY_PENDING_STORAGE_KEY_V1);
  } catch {
    // v2 사본은 이미 저장했다. v1 잔존은 다음 읽기에서 다시 정리를 시도한다.
  }
  return { value: migrated, error: null };
}

function readPending(): { value: PendingBulkRequest | null; error: string | null } {
  const storage = getStorage();
  if (!storage) return { value: null, error: "이 탭의 일괄 요청 저장소를 사용할 수 없습니다." };
  let raw: string | null;
  try {
    raw = storage.getItem(PENDING_STORAGE_KEY);
  } catch {
    return { value: null, error: "이 탭의 일괄 요청 저장소를 읽지 못했습니다." };
  }
  if (raw === null) return readLegacyPendingV1(storage);
  try {
    const value: unknown = JSON.parse(raw);
    return validPending(value)
      ? { value, error: null }
      : { value: null, error: "저장된 일괄 요청 형식이 올바르지 않습니다." };
  } catch {
    return { value: null, error: "저장된 일괄 요청을 읽지 못했습니다." };
  }
}

function savePending(value: PendingBulkRequest): string | null {
  const storage = getStorage();
  if (!storage) return "이 탭의 일괄 요청 저장소를 사용할 수 없습니다.";
  try {
    const serialized = JSON.stringify(value);
    storage.setItem(PENDING_STORAGE_KEY, serialized);
    const roundTrip = storage.getItem(PENDING_STORAGE_KEY);
    if (roundTrip === null) return "일괄 요청 저장 결과를 확인하지 못했습니다.";
    let decoded: unknown;
    try {
      decoded = JSON.parse(roundTrip);
    } catch {
      return "일괄 요청 저장 결과가 올바른 JSON이 아닙니다.";
    }
    if (!validPending(decoded) || JSON.stringify(decoded) !== serialized) {
      return "일괄 요청 저장 결과가 원래 입력과 일치하지 않습니다.";
    }
    return null;
  } catch {
    return "일괄 요청을 저장하지 못했습니다. 저장소 용량·보안 설정을 확인하십시오.";
  }
}

function removePending(): string | null {
  const storage = getStorage();
  if (!storage) return "일괄 요청 저장소를 사용할 수 없습니다.";
  try {
    storage.removeItem(PENDING_STORAGE_KEY);
    if (storage.getItem(PENDING_STORAGE_KEY) !== null) return "일괄 요청 정리를 확인하지 못했습니다.";
    return null;
  } catch {
    return "완료된 일괄 요청을 정리하지 못했습니다.";
  }
}

export function hasPendingOrderPlanBulkTrackingRequest(): boolean {
  return readPending().value !== null;
}

/**
 * 저장된 대기 요청의 작업 종류. 다이얼로그를 열기 전에 이 값으로 `mode`를 맞춰
 * 복구 문구가 실제로 보낼 endpoint와 어긋나지 않게 한다(A2).
 */
export function getPendingOrderPlanBulkTrackingAction(): OrderPlanBulkTrackingMode | null {
  return readPending().value?.action ?? null;
}

function isUnconfirmedError(error: unknown): boolean {
  return error instanceof OrderPlanBulkTrackingResultUnconfirmedError
    || (error instanceof ApiError && (error.status === 0 || error.status >= 500));
}

const failureLabels: Record<string, string> = {
  order_plan_not_found: "발주계획 없음",
  owning_opportunity_missing: "소유 사업기회 없음",
  owner_changed: "소유권 변경",
  ownership_conflict: "소유권 충돌",
  processing_failed: "처리 실패",
  temporarily_unavailable: "일시적으로 처리할 수 없음",
};

function failureLabel(code: string | null): string {
  return code ? failureLabels[code] ?? code : "확인 불가";
}

function normalizeIds(ids: readonly number[]): number[] {
  return Array.from(new Set(ids.filter((id) => Number.isSafeInteger(id) && id > 0))).sort((a, b) => a - b);
}

function samePending(left: PendingBulkRequest, right: PendingBulkRequest): boolean {
  return left.request_id === right.request_id
    && left.actor === right.actor
    && left.reason === right.reason
    && left.selection_generation === right.selection_generation
    && left.filter_fingerprint === right.filter_fingerprint
    && left.action === right.action
    && left.order_plan_ids.length === right.order_plan_ids.length
    && left.order_plan_ids.every((id, index) => id === right.order_plan_ids[index]);
}

function persistedRequestMatches(request: PendingBulkRequest): boolean {
  const stored = readPending();
  return stored.value !== null && samePending(stored.value, request);
}

function resultMatchesRequest(result: OrderPlanBulkReceipt, request: PendingBulkRequest): boolean {
  const ids = result.items.map((item) => item.order_plan_id);
  const expected = request.order_plan_ids;
  return result.request_id === request.request_id
    && ids.length === expected.length
    && ids.every((id, index) => id === expected[index])
    && result.summary.selected_plan_count === expected.length
    && result.summary.succeeded_plan_count
      + result.summary.excluded_plan_count
      + result.summary.failed_plan_count === expected.length;
}

function PreviewFacts({ preview, eligibleLabel }: { preview: OrderPlanBulkPreviewResponse; eligibleLabel: string }) {
  return (
    <div className="c2l-bulk-facts" data-testid="order-plan-bulk-preview">
      <div><span>선택 계획</span><strong>{preview.selected_plan_count.toLocaleString("ko-KR")}건</strong></div>
      <div><span>선택 계획 ID</span><strong>{preview.items.map((item) => item.order_plan_id).join(", ")}</strong></div>
      <div><span>중복 제거한 소유 사업기회</span><strong>{preview.unique_owner_count.toLocaleString("ko-KR")}건</strong></div>
      <div><span>{eligibleLabel}</span><strong>{preview.eligible_plan_count.toLocaleString("ko-KR")}건 · 소유자 {preview.eligible_owner_count.toLocaleString("ko-KR")}건</strong></div>
      <div><span>소유권·조회 실패</span><strong>{preview.failure_plan_count.toLocaleString("ko-KR")}건</strong></div>
      <div><span>계속 추적으로 이미 결정됨</span><strong>{preview.excluded_by_status["계속 추적"].plan_count}건 · 소유자 {preview.excluded_by_status["계속 추적"].owner_count}건</strong></div>
      <div><span>보류로 제외</span><strong>{preview.excluded_by_status["보류"].plan_count}건 · 소유자 {preview.excluded_by_status["보류"].owner_count}건</strong></div>
      <div><span>종료로 제외</span><strong>{preview.excluded_by_status["종료"].plan_count}건 · 소유자 {preview.excluded_by_status["종료"].owner_count}건</strong></div>
      {preview.items.filter((item) => item.eligibility === "failed").map((item) => (
        <div key={item.order_plan_id}>
          <span>실패 계획 ID {item.order_plan_id}</span>
          <strong>{failureLabel(item.code)}</strong>
        </div>
      ))}
    </div>
  );
}

export function OrderPlanBulkTrackingDialog({
  open,
  mode,
  selectedIds,
  selectionGeneration,
  filterFingerprint,
  actorName,
  onClose,
  onApplied,
  onInvalidate,
  onPersistSelection,
  onPendingChange,
  storageAvailable,
  storageError = null,
}: OrderPlanBulkTrackingDialogProps) {
  const [phase, setPhase] = useState<BulkPhase>("edit");
  const [reason, setReason] = useState("");
  const [bulkActor, setBulkActor] = useState(actorName);
  const [preview, setPreview] = useState<OrderPlanBulkPreviewResponse | null>(null);
  const [result, setResult] = useState<OrderPlanBulkReceipt | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [storageMessage, setStorageMessage] = useState<string | null>(null);
  const [previewIds, setPreviewIds] = useState<number[]>([]);
  const [previewBinding, setPreviewBinding] = useState<PreviewBinding | null>(null);
  const [previewContextError, setPreviewContextError] = useState<string | null>(null);
  const [request, setRequest] = useState<PendingBulkRequest | null>(null);
  const [recovery, setRecovery] = useState<PendingBulkRequest | null>(null);
  const [pendingStorageError, setPendingStorageError] = useState<string | null>(null);
  const [cleanupError, setCleanupError] = useState<string | null>(null);
  const [postResultError, setPostResultError] = useState<string | null>(null);
  const currentIds = useMemo(() => normalizeIds(selectedIds), [selectedIds]);
  const inFlightRef = useRef(false);
  const openRef = useRef(false);
  const mountedRef = useRef(false);
  const requestRef = useRef<PendingBulkRequest | null>(null);
  const previewSequenceRef = useRef(0);
  const previewAbortRef = useRef<AbortController | null>(null);
  const currentContextRef = useRef({
    generation: selectionGeneration,
    fingerprint: filterFingerprint,
    ids: currentIds,
  });
  currentContextRef.current = {
    generation: selectionGeneration,
    fingerprint: filterFingerprint,
    ids: currentIds,
  };
  const actorRef = useRef(actorName);
  actorRef.current = actorName;

  // 저장된 요청이 있으면 그 요청의 action이 이긴다 — 열린 다이얼로그의 mode와
  // 어긋나도 같은 request_id가 다른 endpoint로 가면 안 된다(A2).
  const effectiveMode: OrderPlanBulkTrackingMode = request?.action ?? recovery?.action ?? mode;
  const copy = COPY[effectiveMode];
  const pendingIds = request?.order_plan_ids ?? recovery?.order_plan_ids ?? previewIds;
  const failedIds = result?.items.filter((item) => item.outcome === "failed").map((item) => item.order_plan_id) ?? [];
  const storageBlocked = !storageAvailable || Boolean(storageError) || Boolean(storageMessage) || Boolean(pendingStorageError) || Boolean(cleanupError);
  const retryBlocked = Boolean(pendingStorageError);
  const readyToPreview = !storageBlocked && currentIds.length > 0;
  const actor = bulkActor.trim();
  const trimmedReason = reason.trim();
  const actorError = validateActor(bulkActor);
  const reasonError = validateReason(reason, copy.reasonRequiredError);
  const previewContextMatches = previewBinding !== null
    && previewBinding.selection_generation === selectionGeneration
    && previewBinding.filter_fingerprint === filterFingerprint
    && previewBinding.ids.length === currentIds.length
    && previewBinding.ids.every((id, index) => id === currentIds[index]);
  const previewContextChanged = phase === "confirming" && !previewContextMatches;
  const overSelectionLimit = effectiveMode === "end" && previewIds.length > ORDER_PLAN_BULK_END_MAX_SELECTION;
  const confirmDisabledReason = previewContextChanged
    ? "현재 선택으로 다시 미리보기한 뒤 확인하십시오."
    : overSelectionLimit
      ? copy.overSelectionMessage
      : actorError ?? reasonError
        ?? (!actor || !trimmedReason ? copy.confirmDisabledFallback : null)
        ?? (storageBlocked ? "일괄 요청 저장소를 확인할 수 없어 새 요청을 만들 수 없습니다." : "확인하면 현재 미리보기의 계획을 저장합니다.");
  const retryContextMatches = request === null
    || (request.selection_generation === selectionGeneration && request.filter_fingerprint === filterFingerprint);
  const canConfirm = phase === "confirming" && Boolean(actor) && Boolean(trimmedReason)
    && !actorError && !reasonError && Boolean(preview?.selected_plan_count) && !inFlightRef.current
    && !storageBlocked && !previewContextChanged && !overSelectionLimit;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      inFlightRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!open || openRef.current) return;
    openRef.current = true;
    setError(null);
    setStorageMessage(null);
    setPendingStorageError(null);
    setCleanupError(null);
    setPostResultError(null);
    setPreviewContextError(null);
    const stored = readPending();
    if (stored.error) {
      setStorageMessage(stored.error);
      setPendingStorageError(stored.error);
      setRecovery(null);
    } else if (stored.value) {
      setRecovery(stored.value);
      setRequest(stored.value);
      requestRef.current = stored.value;
      setReason(stored.value.reason);
      setBulkActor(stored.value.actor);
      setPhase("unknown");
    } else {
      setRecovery(null);
      setRequest(null);
      requestRef.current = null;
      setResult(null);
      setPreview(null);
      setPreviewIds(currentIds);
      setPreviewBinding(null);
      setPreviewContextError(null);
      setReason("");
      setBulkActor(actorRef.current);
      setPhase("edit");
    }
  }, [currentIds, open]);

  useEffect(() => {
    if (!open) {
      previewSequenceRef.current += 1;
      previewAbortRef.current?.abort();
      previewAbortRef.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (open) return;
    openRef.current = false;
    if (phase !== "pending") {
      setPhase("edit");
      setError(null);
    }
  }, [open, phase]);

  useEffect(() => {
    if (phase !== "pending") return;
    function protectNavigation(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", protectNavigation);
    return () => window.removeEventListener("beforeunload", protectNavigation);
  }, [phase]);

  useEffect(() => {
    onPendingChange?.(phase === "pending");
    return () => onPendingChange?.(false);
  }, [onPendingChange, phase]);

  async function previewSelection(ids: readonly number[]) {
    const normalized = normalizeIds(ids);
    if (!storageAvailable || storageError) {
      setStorageMessage(copy.cannotStartMessage);
      return;
    }
    if (normalized.length === 0) return;
    previewSequenceRef.current += 1;
    const sequence = previewSequenceRef.current;
    previewAbortRef.current?.abort();
    const controller = new AbortController();
    previewAbortRef.current = controller;
    setPreviewIds(normalized);
    setPreviewBinding({
      ids: normalized,
      selection_generation: selectionGeneration,
      filter_fingerprint: filterFingerprint,
    });
    setPreviewContextError(null);
    setPhase("previewing");
    setError(null);
    try {
      const response = await api.previewOrderPlanTracking(normalized, { signal: controller.signal });
      const context = currentContextRef.current;
      const contextMatches = context.generation === selectionGeneration
        && context.fingerprint === filterFingerprint
        && context.ids.length === normalized.length
        && context.ids.every((id, index) => id === normalized[index]);
      if (!mountedRef.current || !openRef.current || sequence !== previewSequenceRef.current || !contextMatches) {
        if (mountedRef.current && openRef.current && sequence === previewSequenceRef.current && !contextMatches) {
          setPreview(null);
          setPreviewBinding(null);
          setPreviewIds(context.ids);
          setPreviewContextError("목록 조건·선택이 바뀌어 이전 미리보기를 버렸습니다. 현재 선택을 다시 미리보십시오.");
          setPhase("edit");
        }
        return;
      }
      setPreview(response);
      setPhase("confirming");
    } catch (caught) {
      if (controller.signal.aborted || sequence !== previewSequenceRef.current || !mountedRef.current || !openRef.current) return;
      const context = currentContextRef.current;
      const contextMatches = context.generation === selectionGeneration
        && context.fingerprint === filterFingerprint
        && context.ids.length === normalized.length
        && context.ids.every((id, index) => id === normalized[index]);
      if (!contextMatches) {
        setPreview(null);
        setPreviewBinding(null);
        setPreviewIds(context.ids);
        setPreviewContextError("목록 조건·선택이 바뀌어 이전 미리보기 오류를 버렸습니다. 현재 선택을 다시 미리보십시오.");
        setPhase("edit");
        return;
      }
      setError(caught);
      setPhase("edit");
    } finally {
      if (previewAbortRef.current === controller) previewAbortRef.current = null;
    }
  }

  async function send(savedRequest: PendingBulkRequest) {
    if (inFlightRef.current) return;
    if (!mountedRef.current || !persistedRequestMatches(savedRequest)) return;
    inFlightRef.current = true;
    setRequest(savedRequest);
    requestRef.current = savedRequest;
    setPhase("pending");
    setError(null);
    try {
      const response = savedRequest.action === "end"
        ? await api.endOrderPlanTracking({
          schema_version: "order-plan-bulk-end-request.v1",
          request_id: savedRequest.request_id,
          order_plan_ids: savedRequest.order_plan_ids,
          reason: savedRequest.reason,
        }, savedRequest.actor)
        : await api.startOrderPlanTracking({
          schema_version: "order-plan-bulk-start-request.v1",
          request_id: savedRequest.request_id,
          order_plan_ids: savedRequest.order_plan_ids,
          reason: savedRequest.reason,
        }, savedRequest.actor);
      if (!resultMatchesRequest(response, savedRequest)) {
        throw new OrderPlanBulkTrackingResultUnconfirmedError();
      }
      // A route unmount or a newer request may have taken ownership of the
      // persisted slot while this response was in flight. In that case the
      // old response must not touch the new mounted selection or storage.
      if (!mountedRef.current || requestRef.current !== savedRequest || !persistedRequestMatches(savedRequest)) return;
      setResult(response);
      setPhase("result");
      setRecovery(null);
      const resolved = response.items
        .filter((item) => item.outcome === "succeeded" || item.outcome === "excluded")
        .map((item) => item.order_plan_id);
      try {
        onApplied(resolved, savedRequest.selection_generation, response.summary);
      } catch {
        if (mountedRef.current) setPostResultError("선택 상태를 최신 결과와 동기화하지 못했습니다. 결과는 확정되어 있습니다.");
      }
      if (!mountedRef.current || !persistedRequestMatches(savedRequest)) return;
      const removeError = removePending();
      if (removeError) {
        setCleanupError(removeError);
      }
      try {
        await onInvalidate();
      } catch {
        if (mountedRef.current) setPostResultError("최신 목록을 다시 불러오지 못했습니다. 결과는 확정되어 있으며 새 목록 조회를 다시 시도하십시오.");
      }
    } catch (caught) {
      if (!mountedRef.current) return;
      setError(caught);
      setPhase(isUnconfirmedError(caught) ? "unknown" : "error");
      // The request remains in sessionStorage and is the only retry key.
    } finally {
      inFlightRef.current = false;
    }
  }

  function confirm() {
    // This is intentionally the first check: same-frame clicks must not mint
    // another UUID or overwrite the durable pending request while send() runs.
    if (inFlightRef.current) return;
    if (!canConfirm || !preview) return;
    if (!previewContextMatches) {
      setPreviewContextError("목록 조건·선택이 바뀌어 미리보기와 현재 대상이 다릅니다. 현재 선택을 다시 미리보십시오.");
      return;
    }
    const ids = normalizeIds(previewIds);
    if (!ids.length || !actor || !trimmedReason || actorError || reasonError || storageBlocked || overSelectionLimit) return;
    const savedRequest: PendingBulkRequest = {
      request_id: request?.request_id ?? generateRequestId(),
      order_plan_ids: ids,
      actor,
      reason: trimmedReason,
      selection_generation: selectionGeneration,
      filter_fingerprint: filterFingerprint,
      action: effectiveMode,
    };
    const selectionWrite = onPersistSelection?.();
    if (selectionWrite && !selectionWrite.ok) {
      setStorageMessage(`${selectionWrite.error?.message ?? "선택 상태를 저장하지 못했습니다."} 단건 추적 경로를 사용하십시오.`);
      return;
    }
    const writeError = savePending(savedRequest);
    if (writeError) {
      setStorageMessage(`${writeError} ${copy.writeErrorSuffix}`);
      setPhase("confirming");
      return;
    }
    void send(savedRequest);
  }

  function retrySameRequest() {
    if (!request || inFlightRef.current) return;
    void send(request);
  }

  function retryFailed() {
    if (!failedIds.length) return;
    if (!retryContextMatches) {
      setPreviewContextError("목록 조건·선택 세대가 바뀌어 이전 실패 건을 바로 재시도할 수 없습니다. 현재 선택을 다시 미리보십시오.");
      return;
    }
    setRequest(null);
    setPreview(null);
    setResult(null);
    setError(null);
    setRecovery(null);
    setPreviewIds(failedIds);
    setPhase("edit");
  }

  const description = error
    ? describeOrderPlanBulkTrackingError(
      isUnconfirmedError(error) ? new OrderPlanBulkTrackingResultUnconfirmedError() : error,
      copy.errorFallbackDescription,
      copy.unknownFallbackTitle,
    )
    : null;
  const close = () => {
    if (phase === "pending") return;
    openRef.current = false;
    previewSequenceRef.current += 1;
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    onClose();
  };

  // Keep the state/recovery hooks alive across parent route and filter
  // changes, but do not leave a closed Dialog subtree in the accessibility
  // tree. Hidden bulk fields would collide with the single-row actor input.
  if (!open) return null;

  return (
    <Dialog
      isOpen={open}
      maxHeight="90dvh"
      onOpenChange={(next) => { if (!next) close(); }}
      purpose="form"
      width={680}
    >
      <div className="c2l-bulk-dialog" data-testid="order-plan-bulk-tracking-dialog">
        <DialogHeader
          title={effectiveMode === "end" && phase === "confirming" ? copy.confirmHeading : copy.dialogTitle}
          onOpenChange={() => close()}
        />
        <div className="c2l-dialog-body">
          <Text type="supporting" color="secondary" as="p">
            {copy.subtitle}
          </Text>
          {!storageAvailable || storageError || storageMessage ? (
            <div className="c2l-bulk-error" role="alert">
              <strong>{copy.storageUnavailableTitle}</strong>
              <span>{storageMessage ?? storageError ?? "선택 저장소를 사용할 수 없습니다."} 단건 추적 경로를 사용하십시오.</span>
            </div>
          ) : null}
          {recovery && phase === "unknown" && !error ? (
            <div className="c2l-bulk-recovery" role="status">
              저장된 요청 결과를 아직 확인하지 않았습니다. 새 요청을 만들지 않고 같은 요청으로 확인하십시오.
              <Button label="저장된 요청 결과 확인" variant="primary" isDisabled={retryBlocked || !request || inFlightRef.current} onClick={retrySameRequest} />
            </div>
          ) : null}
          {previewContextError && phase !== "confirming" ? (
            <div className="c2l-bulk-error" role="alert">
              <strong>미리보기를 다시 확인하십시오.</strong>
              <span>{previewContextError}</span>
            </div>
          ) : null}
          {phase === "edit" ? (
            <>
              <div className="c2l-bulk-selection-summary">
                <Badge variant="neutral" label={`선택 ${currentIds.length}건`} />
                <Text type="supporting" color="secondary" as="span">여러 페이지에서 고른 ID를 함께 확인합니다.</Text>
              </div>
              <TextInput
                label="공통 담당자 이름 · 감사 표식"
                value={bulkActor}
                onChange={setBulkActor}
                placeholder="이름 입력"
              />
              <TextArea
                label={copy.reasonLabel}
                value={reason}
                onChange={setReason}
                rows={3}
                placeholder={copy.reasonPlaceholder}
              />
              <div className="c2l-bulk-actions">
                <Button
                  label="선택 대상 미리보기"
                  variant="primary"
                  isDisabled={!readyToPreview}
                  onClick={() => void previewSelection(currentIds)}
                />
              </div>
            </>
          ) : null}
          {phase === "previewing" ? <Text type="body" color="secondary" as="p" role="status">선택 대상의 최신 상태를 미리 확인하는 중…</Text> : null}
          {phase === "confirming" && preview ? (
            <>
              <PreviewFacts preview={preview} eligibleLabel={copy.eligibleLabel} />
              {previewContextChanged ? (
                <div className="c2l-bulk-error" role="alert">
                  <strong>현재 선택과 미리보기의 기준이 다릅니다.</strong>
                  <span>{previewContextError ?? "브라우저 뒤로·앞으로 또는 필터 변경으로 선택 세대가 바뀌었습니다. 새 요청을 만들기 전에 현재 선택을 다시 미리보십시오."}</span>
                  <Button label="현재 선택으로 다시 미리보기" variant="secondary" isDisabled={storageBlocked || currentIds.length === 0} onClick={() => void previewSelection(currentIds)} />
                </div>
              ) : null}
              <Text type="supporting" color="secondary" as="p">
                미리보기 뒤 저장 시점에 서버가 최신 소유권·추적 상태를 다시 확인합니다. 최종 건수는 달라질 수 있습니다.
              </Text>
              {copy.endWarning ? (
                <p className="c2l-bulk-warning">{copy.endWarning}</p>
              ) : null}
              <TextInput label="공통 담당자 이름 · 감사 표식" value={bulkActor} onChange={setBulkActor} placeholder="이름 입력" />
              <TextArea label={copy.reasonLabel} value={reason} onChange={setReason} rows={3} placeholder={copy.reasonPlaceholder} />
              <div className="c2l-bulk-actions">
                <Button label="미리보기로 돌아가기" variant="ghost" isDisabled={inFlightRef.current} onClick={() => setPhase("edit")} />
                <Button aria-describedby="c2l-bulk-confirm-reason" label={copy.confirmButtonLabel} variant="primary" isDisabled={!canConfirm} onClick={confirm} />
              </div>
              <Text id="c2l-bulk-confirm-reason" type="supporting" color="secondary" as="p" role="status">
                {confirmDisabledReason}
              </Text>
            </>
          ) : null}
          {phase === "pending" ? (
            <div className="c2l-bulk-pending" role="status" aria-live="polite">
              <strong>{copy.pendingHeading}</strong>
              <span>{pendingIds.length}건 · 입력과 선택은 잠겨 있습니다. 응답을 기다리는 동안 이탈할 수 없습니다.</span>
            </div>
          ) : null}
          {phase === "unknown" && error ? (
            <div className="c2l-bulk-error" role="alert">
              <strong>{description?.title ?? copy.unknownFallbackTitle}</strong>
              <span>{description?.detail ?? "같은 요청 결과 확인을 눌러 저장된 결과를 확인하십시오."}</span>
              {request ? <span>요청 식별자 <code>{request.request_id}</code> · 새 요청을 자동으로 만들지 않았습니다.</span> : null}
              <div className="c2l-bulk-actions">
                <Button label="같은 요청 결과 확인" variant="primary" isDisabled={retryBlocked || !request || inFlightRef.current} onClick={retrySameRequest} />
              </div>
            </div>
          ) : null}
          {phase === "result" && result ? (
            <div className="c2l-bulk-result" role="status" data-testid="order-plan-bulk-result">
              <strong>{copy.resultHeading}</strong>
              {postResultError ? <span role="alert">{postResultError}</span> : null}
              {cleanupError ? <span role="alert">{cleanupError} 새 요청은 저장소 확인 후에만 만들 수 있습니다.</span> : null}
              <Text type="body" color="secondary" as="p">
                성공 {result.summary.succeeded_plan_count}건 · 상태 제외 {result.summary.excluded_plan_count}건 · 실패 {result.summary.failed_plan_count}건
              </Text>
              {copy.resultExtraNote ? (
                <Text type="supporting" color="secondary" as="p">{copy.resultExtraNote}</Text>
              ) : null}
              {failedIds.length ? (
                <>
                  <Text type="supporting" color="secondary" as="p">실패 항목은 선택에 남아 있습니다. 원인을 확인한 뒤 실패 건만 새 요청으로 재시도할 수 있습니다.</Text>
                  <ul className="c2l-bulk-failures" aria-label={copy.failuresAriaLabel}>
                    {result.items.filter((item) => item.outcome === "failed").map((item) => (
                      <li key={item.order_plan_id}>계획 ID {item.order_plan_id} · {failureLabel(item.code)}</li>
                    ))}
                  </ul>
                  <Button label="실패 건 재시도 준비" variant="secondary" isDisabled={storageBlocked || !retryContextMatches} onClick={retryFailed} />
                </>
              ) : null}
              <Button label="닫기" variant="ghost" onClick={onClose} />
            </div>
          ) : null}
          {error && phase !== "unknown" ? (
            <div className="c2l-bulk-error" role="alert">
              <strong>{description?.title ?? "일괄 추적 미리보기를 확인할 수 없습니다."}</strong>
              <span>{description?.detail ?? "선택을 바꾸지 않고 다시 시도하십시오."}</span>
              {phase === "error" ? <span>서버가 요청을 거부했습니다. 같은 요청을 자동으로 다시 보내지 않았습니다.</span> : null}
            </div>
          ) : null}
          {phase !== "pending" && phase !== "result" ? (
            <div className="c2l-bulk-actions">
              <Button label="닫기" variant="ghost" onClick={close} />
            </div>
          ) : null}
          {phase === "edit" && !currentIds.length ? <Text type="supporting" color="secondary" as="p">선택한 발주계획이 없습니다.</Text> : null}
        </div>
      </div>
    </Dialog>
  );
}
