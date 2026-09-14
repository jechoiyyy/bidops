import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ApiError, api, OrderPlanBulkTrackingResultUnconfirmedError } from "../../lib/api";
import { describeOrderPlanBulkTrackingError } from "../../lib/apiErrors";
import { generateRequestId } from "../../lib/requestId";
import type {
  OrderPlanBulkPreviewResponse,
  OrderPlanBulkStartResponse,
} from "../../lib/types";
import "../../styles/order-plans.css";

export interface OrderPlanBulkTrackingDialogProps {
  open: boolean;
  selectedIds: readonly number[];
  selectionGeneration: number;
  filterFingerprint: string;
  actorName: string;
  onClose: () => void;
  onApplied: (resolvedIds: readonly number[], generation: number) => void;
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
}

interface PreviewBinding {
  ids: number[];
  selection_generation: number;
  filter_fingerprint: string;
}

const PENDING_STORAGE_KEY = "bidops.order-plans.bulk-tracking.pending.v1";
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

function validateReason(value: string): string | null {
  return value.trim() ? null : "공통 추적 사유를 입력하십시오.";
}

function getStorage(): StorageLike | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function validPending(value: unknown): value is PendingBulkRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const keys = [
    "request_id", "order_plan_ids", "actor", "reason", "selection_generation", "filter_fingerprint",
  ];
  if (Object.keys(record).length !== keys.length || keys.some((key) => !(key in record))) return false;
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

function readPending(): { value: PendingBulkRequest | null; error: string | null } {
  const storage = getStorage();
  if (!storage) return { value: null, error: "이 탭의 일괄 요청 저장소를 사용할 수 없습니다." };
  let raw: string | null;
  try {
    raw = storage.getItem(PENDING_STORAGE_KEY);
  } catch {
    return { value: null, error: "이 탭의 일괄 요청 저장소를 읽지 못했습니다." };
  }
  if (raw === null) return { value: null, error: null };
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
    && left.order_plan_ids.length === right.order_plan_ids.length
    && left.order_plan_ids.every((id, index) => id === right.order_plan_ids[index]);
}

function persistedRequestMatches(request: PendingBulkRequest): boolean {
  const stored = readPending();
  return stored.value !== null && samePending(stored.value, request);
}

function resultMatchesRequest(result: OrderPlanBulkStartResponse, request: PendingBulkRequest): boolean {
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

function PreviewFacts({ preview }: { preview: OrderPlanBulkPreviewResponse }) {
  return (
    <div className="c2l-bulk-facts" data-testid="order-plan-bulk-preview">
      <div><span>선택 계획</span><strong>{preview.selected_plan_count.toLocaleString("ko-KR")}건</strong></div>
      <div><span>선택 계획 ID</span><strong>{preview.items.map((item) => item.order_plan_id).join(", ")}</strong></div>
      <div><span>중복 제거한 소유 사업기회</span><strong>{preview.unique_owner_count.toLocaleString("ko-KR")}건</strong></div>
      <div><span>미선택 · 실행 가능</span><strong>{preview.eligible_plan_count.toLocaleString("ko-KR")}건 · 소유자 {preview.eligible_owner_count.toLocaleString("ko-KR")}건</strong></div>
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
  const [result, setResult] = useState<OrderPlanBulkStartResponse | null>(null);
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

  const pendingIds = request?.order_plan_ids ?? recovery?.order_plan_ids ?? previewIds;
  const failedIds = result?.items.filter((item) => item.outcome === "failed").map((item) => item.order_plan_id) ?? [];
  const storageBlocked = !storageAvailable || Boolean(storageError) || Boolean(storageMessage) || Boolean(pendingStorageError) || Boolean(cleanupError);
  const retryBlocked = Boolean(pendingStorageError);
  const readyToPreview = !storageBlocked && currentIds.length > 0;
  const actor = bulkActor.trim();
  const trimmedReason = reason.trim();
  const actorError = validateActor(bulkActor);
  const reasonError = validateReason(reason);
  const previewContextMatches = previewBinding !== null
    && previewBinding.selection_generation === selectionGeneration
    && previewBinding.filter_fingerprint === filterFingerprint
    && previewBinding.ids.length === currentIds.length
    && previewBinding.ids.every((id, index) => id === currentIds[index]);
  const previewContextChanged = phase === "confirming" && !previewContextMatches;
  const confirmDisabledReason = previewContextChanged
    ? "현재 선택으로 다시 미리보기한 뒤 확인하십시오."
    : actorError ?? reasonError
      ?? (!actor || !trimmedReason ? "담당자 이름과 공통 추적 사유를 입력해야 저장할 수 있습니다." : null)
      ?? (storageBlocked ? "일괄 요청 저장소를 확인할 수 없어 새 요청을 만들 수 없습니다." : "확인하면 현재 미리보기의 계획을 저장합니다.");
  const retryContextMatches = request === null
    || (request.selection_generation === selectionGeneration && request.filter_fingerprint === filterFingerprint);
  const canConfirm = phase === "confirming" && Boolean(actor) && Boolean(trimmedReason)
    && !actorError && !reasonError && Boolean(preview?.selected_plan_count) && !inFlightRef.current
    && !storageBlocked && !previewContextChanged;

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
      setStorageMessage("일괄 추적을 시작할 수 없습니다. 선택 저장소를 사용할 수 없어 단건 추적 경로를 사용하십시오.");
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
      const response = await api.startOrderPlanTracking({
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
        onApplied(resolved, savedRequest.selection_generation);
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
    if (!ids.length || !actor || !trimmedReason || actorError || reasonError || storageBlocked) return;
    const savedRequest: PendingBulkRequest = {
      request_id: request?.request_id ?? generateRequestId(),
      order_plan_ids: ids,
      actor,
      reason: trimmedReason,
      selection_generation: selectionGeneration,
      filter_fingerprint: filterFingerprint,
    };
    const selectionWrite = onPersistSelection?.();
    if (selectionWrite && !selectionWrite.ok) {
      setStorageMessage(`${selectionWrite.error?.message ?? "선택 상태를 저장하지 못했습니다."} 단건 추적 경로를 사용하십시오.`);
      return;
    }
    const writeError = savePending(savedRequest);
    if (writeError) {
      setStorageMessage(`${writeError} 일괄 추적을 보내지 않았습니다. 단건 추적 경로를 사용하십시오.`);
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
      "일괄 추적 작업을 완료하지 못했습니다.",
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
        <DialogHeader title="발주계획 일괄 추적" onOpenChange={() => close()} />
        <div className="c2l-dialog-body">
          <Text type="supporting" color="secondary" as="p">
            미선택 상태인 계획만 계속 추적으로 저장합니다. 이미 결정된 상태와 소유권을 확인할 수 없는 항목은 바꾸지 않습니다.
          </Text>
          {!storageAvailable || storageError || storageMessage ? (
            <div className="c2l-bulk-error" role="alert">
              <strong>일괄 추적을 사용할 수 없습니다.</strong>
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
                label="공통 추적 사유"
                value={reason}
                onChange={setReason}
                rows={3}
                placeholder="선택한 계획을 함께 추적하는 이유"
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
              <PreviewFacts preview={preview} />
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
              <TextInput label="공통 담당자 이름 · 감사 표식" value={bulkActor} onChange={setBulkActor} placeholder="이름 입력" />
              <TextArea label="공통 추적 사유" value={reason} onChange={setReason} rows={3} placeholder="선택한 계획을 함께 추적하는 이유" />
              <div className="c2l-bulk-actions">
                <Button label="미리보기로 돌아가기" variant="ghost" isDisabled={inFlightRef.current} onClick={() => setPhase("edit")} />
                <Button aria-describedby="c2l-bulk-confirm-reason" label="확인하고 일괄 추적 시작" variant="primary" isDisabled={!canConfirm} onClick={confirm} />
              </div>
              <Text id="c2l-bulk-confirm-reason" type="supporting" color="secondary" as="p" role="status">
                {confirmDisabledReason}
              </Text>
            </>
          ) : null}
          {phase === "pending" ? (
            <div className="c2l-bulk-pending" role="status" aria-live="polite">
              <strong>일괄 추적 저장 중</strong>
              <span>{pendingIds.length}건 · 입력과 선택은 잠겨 있습니다. 응답을 기다리는 동안 이탈할 수 없습니다.</span>
            </div>
          ) : null}
          {phase === "unknown" && error ? (
            <div className="c2l-bulk-error" role="alert">
              <strong>{description?.title ?? "일괄 추적 결과를 확인할 수 없습니다."}</strong>
              <span>{description?.detail ?? "같은 요청 결과 확인을 눌러 저장된 결과를 확인하십시오."}</span>
              {request ? <span>요청 식별자 <code>{request.request_id}</code> · 새 요청을 자동으로 만들지 않았습니다.</span> : null}
              <div className="c2l-bulk-actions">
                <Button label="같은 요청 결과 확인" variant="primary" isDisabled={retryBlocked || !request || inFlightRef.current} onClick={retrySameRequest} />
              </div>
            </div>
          ) : null}
          {phase === "result" && result ? (
            <div className="c2l-bulk-result" role="status" data-testid="order-plan-bulk-result">
              <strong>일괄 추적 결과를 확인했습니다.</strong>
              {postResultError ? <span role="alert">{postResultError}</span> : null}
              {cleanupError ? <span role="alert">{cleanupError} 새 요청은 저장소 확인 후에만 만들 수 있습니다.</span> : null}
              <Text type="body" color="secondary" as="p">
                성공 {result.summary.succeeded_plan_count}건 · 상태 제외 {result.summary.excluded_plan_count}건 · 실패 {result.summary.failed_plan_count}건
              </Text>
              {failedIds.length ? (
                <>
                  <Text type="supporting" color="secondary" as="p">실패 항목은 선택에 남아 있습니다. 원인을 확인한 뒤 실패 건만 새 요청으로 재시도할 수 있습니다.</Text>
                  <ul className="c2l-bulk-failures" aria-label="일괄 추적 실패 항목">
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
