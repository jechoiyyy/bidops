import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { StatusBadge, type StatusTone } from "../common/StatusBadge";
import { describeApiError } from "../../lib/apiErrors";
import { TERM } from "../../lib/glossary";
import {
  confirmDocumentBundle,
  createDeepReview,
  createDocumentBundle,
  getDocumentBundles,
  patchDocumentVersion,
  uploadDocument,
} from "./api";
import type {
  BundleStatus,
  BundleView,
  DeepReviewView,
  DocumentRole,
  DocumentVersionView,
  SafetyStatus,
  StructureStatus,
} from "./types";
import "../../styles/document-preparation.css";

const DOCUMENT_ROLES: DocumentRole[] = ["공고", "정정", "제안요청서", "과업지시서", "내역서", "제출서식", "부록", "기타"];
const MAX_FILE_SIZE = 50 * 1024 * 1024;

/** 사전규격 상세의 자동 준비 단계 표시도 같은 문구를 쓴다. 묶음 상태 이름을
 * 두 곳에서 따로 정의하지 않는다. */
export const BUNDLE_STATUS_LABELS: Record<BundleStatus, string> = {
  draft: "초안",
  processing: "처리 중",
  needs_review: "사람 확인 필요",
  ready: "확정 완료",
  quarantined: "격리됨",
  failed: "실패",
  superseded: "이전 확정본",
};

const SAFETY_STATUS_LABELS: Record<SafetyStatus, string> = {
  quarantined: "격리 보관 중",
  scanning: "안전 검사 중",
  safe: "안전 확인",
  blocked: "안전 검사 차단",
};

const STRUCTURE_STATUS_LABELS: Record<StructureStatus, string> = {
  pending: "변환·구조화 대기",
  processing: "변환·구조화 진행 중",
  ready: "구조화 완료",
  failed: "변환·구조화 실패",
  needs_review: "구조화 사람 확인 필요",
};

type UploadOutcome = {
  key: string;
  filename: string;
  status: "uploading" | "succeeded" | "failed";
  message: string;
};

interface DocumentPreparationPanelProps {
  noticeId: number;
  /** 사전규격 projection의 **현재 등급**(사람 정정이 있으면 그 값). 화면은 현재
   * 등급 하나만 보여 주므로 이 패널은 등급을 다시 그리지 않고, 서버가 시작
   * 시점에 effective grade를 다시 본다는 사실만 이 값으로 안내한다. 화면의
   * 등급 표시는 상세 헤더가 소유한다(명세 §6.2). */
  currentGrade: string | null;
  onDeepReviewCreated: (review: DeepReviewView) => void;
}

function bundleIsImmutable(bundle: BundleView): boolean {
  return bundle.status === "ready" || bundle.status === "superseded";
}

function statusTone(status: string): StatusTone {
  if (status === "safe" || status === "ready") return "success";
  if (status === "blocked" || status === "failed") return "danger";
  if (status === "needs_review") return "warning";
  return "info";
}

function invalidFileReason(file: File): string | null {
  if (!/\.(hwp|hwpx|pdf)$/i.test(file.name)) return "HWP, HWPX, PDF 파일만 등록할 수 있습니다.";
  if (file.size > MAX_FILE_SIZE) return "파일당 50MiB를 넘을 수 없습니다.";
  return null;
}

function DocumentMetadataEditor({
  actorName,
  document,
  documents,
  editable,
  onSaved,
}: {
  actorName: string;
  document: DocumentVersionView;
  documents: DocumentVersionView[];
  editable: boolean;
  onSaved: (message: string) => Promise<void>;
}) {
  const [role, setRole] = useState<DocumentRole>(document.role);
  const [effectiveDate, setEffectiveDate] = useState(document.effective_date ?? "");
  const [replacesId, setReplacesId] = useState(document.replaces_document_version_id ?? "");
  const [isCurrent, setIsCurrent] = useState(document.is_current);

  useEffect(() => {
    setRole(document.role);
    setEffectiveDate(document.effective_date ?? "");
    setReplacesId(document.replaces_document_version_id ?? "");
    setIsCurrent(document.is_current);
  }, [document.effective_date, document.is_current, document.replaces_document_version_id, document.role, document.version]);

  const dirty = role !== document.role
    || effectiveDate !== (document.effective_date ?? "")
    || replacesId !== (document.replaces_document_version_id ?? "")
    || isCurrent !== document.is_current;

  const mutation = useMutation({
    mutationFn: () => patchDocumentVersion(document.id, actorName, {
      role,
      effective_date: effectiveDate || null,
      replaces_document_version_id: replacesId || null,
      is_current: isCurrent,
      version: document.version,
    }),
    onSuccess: async (saved) => {
      await onSaved(`${saved.original_filename} 문서 정보를 버전 ${saved.version}으로 저장했습니다.`);
    },
  });
  const disabledReason = mutation.isPending
    ? "문서 정보 저장 요청을 처리하고 있습니다."
    : !editable
      ? "확정된 묶음·이전 확정본·최신이 아닌 묶음의 문서는 수정하지 않습니다."
      : !actorName.trim()
        ? "저장하려면 담당자 이름이 필요합니다."
        : !dirty
          ? "저장할 변경이 없습니다."
          : null;

  return (
    <article className="document-preparation-document">
      <header>
        <div>
          <strong>{document.original_filename}</strong>
          <span className="mono tabular-nums">문서 버전 {document.version}</span>
        </div>
        <div className="document-preparation-status-pair">
          <StatusBadge tone={statusTone(document.safety_status)} label={SAFETY_STATUS_LABELS[document.safety_status]} />
          <StatusBadge tone={statusTone(document.structure_status)} label={STRUCTURE_STATUS_LABELS[document.structure_status]} />
        </div>
      </header>

      <div className="document-preparation-metadata">
        <label>
          <span>문서 역할</span>
          <select
            aria-label={`문서 역할 · ${document.original_filename}`}
            value={role}
            onChange={(event) => setRole(event.target.value as DocumentRole)}
            disabled={!editable || mutation.isPending}
            aria-describedby={!editable || mutation.isPending ? `metadata-disabled-${document.id}` : undefined}
          >
            {DOCUMENT_ROLES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          <span>시행일</span>
          <input
            aria-label={`시행일 · ${document.original_filename}`}
            type="date"
            value={effectiveDate}
            onChange={(event) => setEffectiveDate(event.target.value)}
            disabled={!editable || mutation.isPending}
            aria-describedby={!editable || mutation.isPending ? `metadata-disabled-${document.id}` : undefined}
          />
        </label>
        <label>
          <span>대체 문서</span>
          <select
            aria-label={`대체 문서 · ${document.original_filename}`}
            value={replacesId}
            onChange={(event) => setReplacesId(event.target.value)}
            disabled={!editable || mutation.isPending}
            aria-describedby={!editable || mutation.isPending ? `metadata-disabled-${document.id}` : undefined}
          >
            <option value="">대체 대상 없음</option>
            {documents.filter((candidate) => candidate.id !== document.id).map((candidate) => (
              <option key={candidate.id} value={candidate.id}>{candidate.original_filename} · v{candidate.version}</option>
            ))}
          </select>
        </label>
        <label className="document-preparation-current">
          <input
            aria-label={`현재 버전 · ${document.original_filename}`}
            type="checkbox"
            checked={isCurrent}
            onChange={(event) => setIsCurrent(event.target.checked)}
            disabled={!editable || mutation.isPending}
            aria-describedby={!editable || mutation.isPending ? `metadata-disabled-${document.id}` : undefined}
          />
          <span>현재 버전으로 사용</span>
        </label>
      </div>

      <div className="document-preparation-document-actions">
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={!editable || mutation.isPending || !actorName.trim() || !dirty}
          aria-describedby={disabledReason ? `metadata-disabled-${document.id}` : undefined}
        >
          {mutation.isPending ? "문서 정보 저장 중" : "문서 정보 저장"}
        </button>
        {disabledReason ? <DisabledReason id={`metadata-disabled-${document.id}`}>{disabledReason}</DisabledReason> : null}
      </div>
      {mutation.error ? <MutationFeedback tone="error" problem={describeApiError(mutation.error, "문서 정보를 저장하지 못했습니다.")} /> : null}
    </article>
  );
}

export function DocumentPreparationPanel({ noticeId, currentGrade, onDeepReviewCreated }: DocumentPreparationPanelProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [actorName, setActorName] = useState("");
  const [selectedBundleId, setSelectedBundleId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploadOutcomes, setUploadOutcomes] = useState<UploadOutcome[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);

  const bundleQuery = useQuery({
    queryKey: ["document-bundles", noticeId],
    queryFn: () => getDocumentBundles(noticeId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const pending = items.some((bundle) => bundle.status === "processing"
        || bundle.documents.some((document) => document.safety_status === "quarantined"
          || document.safety_status === "scanning"
          || document.structure_status === "pending"
          || document.structure_status === "processing"));
      return pending ? 2_000 : false;
    },
    refetchIntervalInBackground: false,
  });

  const bundles = useMemo(
    () => [...(bundleQuery.data?.items ?? [])].sort((left, right) => right.revision - left.revision),
    [bundleQuery.data?.items],
  );
  const latestBundle = bundles[0] ?? null;
  const selectedBundle = bundles.find((bundle) => bundle.id === selectedBundleId) ?? latestBundle;
  const selectedIsLatest = Boolean(selectedBundle && latestBundle && selectedBundle.id === latestBundle.id);
  const editable = Boolean(selectedBundle && !bundleIsImmutable(selectedBundle) && selectedIsLatest);

  useEffect(() => {
    if (bundles.length === 0) {
      setSelectedBundleId(null);
      return;
    }
    if (!selectedBundleId || !bundles.some((bundle) => bundle.id === selectedBundleId)) {
      setSelectedBundleId(bundles[0].id);
    }
  }, [bundles, selectedBundleId]);

  const invalidateBundles = async () => {
    await queryClient.invalidateQueries({ queryKey: ["document-bundles", noticeId] });
  };

  const createMutation = useMutation({
    mutationFn: () => createDocumentBundle(noticeId, actorName),
    onSuccess: async (bundle) => {
      setSelectedBundleId(bundle.id);
      setFeedback(`문서 묶음 수정본 ${bundle.revision} 초안을 만들었습니다.`);
      await invalidateBundles();
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      const outcomes: UploadOutcome[] = files.map((file, index) => ({
        key: `${file.name}-${file.size}-${index}`,
        filename: file.name,
        status: "uploading",
        message: "격리 저장과 안전 검사를 요청하는 중입니다.",
      }));
      setUploadOutcomes(outcomes);

      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const invalidReason = invalidFileReason(file);
        if (invalidReason) {
          outcomes[index] = { ...outcomes[index], status: "failed", message: invalidReason };
          setUploadOutcomes([...outcomes]);
          continue;
        }
        try {
          const requestId = crypto.randomUUID();
          const uploaded = await uploadDocument(selectedBundle?.id ?? "", file, actorName, requestId);
          outcomes[index] = {
            ...outcomes[index],
            status: "succeeded",
            message: `${SAFETY_STATUS_LABELS[uploaded.safety_status]} · ${STRUCTURE_STATUS_LABELS[uploaded.structure_status]}`,
          };
        } catch (error) {
          outcomes[index] = {
            ...outcomes[index],
            status: "failed",
            message: describeApiError(error, "문서를 등록하지 못했습니다.").title,
          };
        }
        setUploadOutcomes([...outcomes]);
      }
      return outcomes;
    },
    onSuccess: async (outcomes) => {
      const succeeded = outcomes.filter((outcome) => outcome.status === "succeeded").length;
      const failed = outcomes.filter((outcome) => outcome.status === "failed").length;
      setFeedback(failed > 0
        ? `업로드 일부 실패 · 성공 ${succeeded}건 / 실패 ${failed}건. 전체 성공으로 처리하지 않았습니다.`
        : `문서 ${succeeded}건을 순차 등록했습니다.`);
      await invalidateBundles();
    },
  });

  const documents = selectedBundle?.documents ?? [];
  const blockingIssues = selectedBundle?.issues.filter((issue) => issue.blocking) ?? [];
  const confirmReasons: string[] = [];
  if (!selectedBundle) confirmReasons.push("확정할 초안 묶음이 없습니다.");
  else {
    if (bundleIsImmutable(selectedBundle)) confirmReasons.push(`${BUNDLE_STATUS_LABELS[selectedBundle.status]} 묶음은 다시 확정하지 않습니다.`);
    if (!selectedIsLatest) confirmReasons.push("최신 수정본이 아닌 묶음은 수정하거나 다시 확정하지 않습니다.");
    if (documents.length === 0) confirmReasons.push("문서를 1건 이상 등록해야 합니다.");
    if (documents.some((document) => document.safety_status !== "safe")) confirmReasons.push("모든 문서가 안전 확인 상태여야 합니다.");
    if (documents.some((document) => document.structure_status !== "ready")) confirmReasons.push("모든 문서의 변환·구조화가 끝나야 합니다.");
    if (blockingIssues.length > 0) confirmReasons.push(`차단 항목 ${blockingIssues.length}건을 먼저 해결해야 합니다.`);
  }
  if (!actorName.trim()) confirmReasons.push("담당자 이름이 필요합니다.");

  const confirmMutation = useMutation({
    mutationFn: () => confirmDocumentBundle(selectedBundle?.id ?? "", actorName, {
      request_id: crypto.randomUUID(),
      version: selectedBundle?.version ?? 0,
      confirmed_documents: documents.map((document) => ({
        document_version_id: document.id,
        version: document.version,
      })),
    }),
    onSuccess: async (bundle) => {
      setSelectedBundleId(bundle.id);
      setFeedback(`문서 묶음 수정본 ${bundle.revision}을 확정했습니다. 이제 수정할 수 없습니다.`);
      await invalidateBundles();
    },
  });

  const deepReviewMutation = useMutation({
    mutationFn: () => createDeepReview(noticeId, selectedBundle?.id ?? "", actorName),
    onSuccess: onDeepReviewCreated,
  });

  const createProblem = createMutation.error ? describeApiError(createMutation.error, "새 문서 묶음을 만들지 못했습니다.") : null;
  const deepReviewProblem = deepReviewMutation.error ? describeApiError(deepReviewMutation.error, "심층 검토를 시작하지 못했습니다.") : null;
  const canCreate = !latestBundle || bundleIsImmutable(latestBundle);
  const confirmDisabledReasons = confirmMutation.isPending
    ? ["문서 묶음 확정 요청을 처리하고 있습니다."]
    : confirmReasons;
  const createDisabledReason = createMutation.isPending
    ? "새 문서 묶음 생성 요청을 처리하고 있습니다."
    : !canCreate && latestBundle
      ? `최신 수정본 ${latestBundle.revision}이 ${BUNDLE_STATUS_LABELS[latestBundle.status]} 상태이므로 중복 초안을 만들지 않습니다.`
      : !actorName.trim()
        ? "새 문서 묶음을 만들려면 담당자 이름을 입력하십시오."
        : null;
  const deepReviewDisabledReason = deepReviewMutation.isPending
    ? "심층 검토 생성 요청을 처리하고 있습니다."
    : !actorName.trim()
      ? "심층 검토를 시작하려면 담당자 이름을 입력하십시오."
      : null;
  const handleFiles = (files: File[]) => {
    if (!editable || uploadMutation.isPending || files.length === 0) return;
    setFeedback(null);
    uploadMutation.mutate(files);
  };
  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    handleFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  };
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    handleFiles(Array.from(event.dataTransfer.files));
  };
  const handleDropzoneKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInputRef.current?.click();
    }
  };

  const safetySummary = documents.length === 0
    ? "등록 문서 없음"
    : documents.every((document) => document.safety_status === "safe")
      ? "모든 문서 안전 확인"
      : documents.some((document) => document.safety_status === "blocked")
        ? "차단 문서 있음"
        : "검사 대기·진행 중";
  const structureSummary = documents.length === 0
    ? "등록 문서 없음"
    : documents.every((document) => document.structure_status === "ready")
      ? "모든 문서 구조화 완료"
      : documents.some((document) => document.structure_status === "failed")
        ? "구조화 실패 문서 있음"
        : documents.some((document) => document.structure_status === "needs_review")
          ? "사람 확인 필요 문서 있음"
          : "변환·구조화 대기·진행 중";

  return (
    <section id="document-preparation" className="document-preparation" aria-labelledby="document-preparation-title">
      <header className="document-preparation-heading">
        <div>
          <span className="document-preparation-eyebrow">안전한 문서 준비 작업대</span>
          <h3 id="document-preparation-title">문서 묶음 준비부터 심층 검토까지</h3>
          <p>문서 등록, 안전 검사, 변환·구조화, 역할 확인, 묶음 확정을 각 단계로 나눠 확인합니다. 이 화면은 심층 검토 입력을 준비할 뿐 추적 승인이나 최종 Go/No-Go를 정하지 않습니다.</p>
        </div>
      </header>

      {currentGrade !== "우선 검토" ? (
        <p className="document-preparation-gate" role="status">
          서버는 문서 묶음을 만들 때와 심층 검토를 시작할 때 등급을 다시 확인합니다. 우선 검토가 아니면 서버가 거부하며, 화면에 보이는 등급으로 우회할 수 없습니다.
        </p>
      ) : null}

      <div className="document-preparation-actor">
        <ActorField label="문서 준비 담당자 이름" value={actorName} onChange={setActorName} autoComplete="off" />
      </div>

      {bundleQuery.isPending ? <p role="status" aria-live="polite">문서 묶음 이력을 불러오는 중입니다.</p> : null}
      {bundleQuery.error ? <MutationFeedback tone="error" problem={describeApiError(bundleQuery.error, "문서 묶음 이력을 확인하지 못했습니다.")} /> : null}

      <div className="document-preparation-bundle-bar">
        <div>
          <strong>{TERM.bundle} {TERM.revision} 이력</strong>
          <span>최신 작업본을 기본으로 고르며 확정 완료·이전 확정본은 읽기 전용입니다.</span>
        </div>
        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={!canCreate || createMutation.isPending || !actorName.trim()}
          aria-describedby={createDisabledReason ? "document-bundle-create-disabled" : undefined}
        >
          {createMutation.isPending ? "새 문서 묶음 만드는 중" : "새 문서 묶음 만들기"}
        </button>
      </div>
      {createDisabledReason ? <DisabledReason id="document-bundle-create-disabled">{createDisabledReason}</DisabledReason> : null}
      {createProblem ? (
        <MutationFeedback tone="error" problem={createProblem}>
          {/* 서버가 등급으로 막은 경우에만 붙이는 화면 사실. 서버 message가
              아니라 이 화면이 아는 규칙이다. */}
          {createProblem.code === "effective_grade_ineligible"
            ? <p>서버는 시작할 때 등급을 다시 확인합니다. 화면에 보이는 등급으로 서버 조건을 우회할 수 없습니다.</p>
            : null}
        </MutationFeedback>
      ) : null}

      {bundles.length > 0 ? (
        <ol className="document-preparation-history" aria-label="문서 묶음 수정본 이력">
          {bundles.map((bundle) => (
            <li key={bundle.id}>
              <button
                type="button"
                className={selectedBundle?.id === bundle.id ? "is-selected" : ""}
                aria-pressed={selectedBundle?.id === bundle.id}
                onClick={() => setSelectedBundleId(bundle.id)}
              >
                <span className="mono tabular-nums">{TERM.revision} {bundle.revision}</span>
                <StatusBadge tone={statusTone(bundle.status)} label={BUNDLE_STATUS_LABELS[bundle.status]} />
                <span>{bundle.documents.length}개 문서</span>
              </button>
            </li>
          ))}
        </ol>
      ) : bundleQuery.isSuccess ? <p className="document-preparation-empty">아직 만든 문서 묶음이 없습니다.</p> : null}

      {selectedBundle ? (
        <div className="document-preparation-workspace">
          <div className="document-preparation-selected">
            <div>
              <span className="mono tabular-nums">선택한 묶음 · 수정본 {selectedBundle.revision} · 버전 {selectedBundle.version}</span>
              <strong>{BUNDLE_STATUS_LABELS[selectedBundle.status]}</strong>
            </div>
            {bundleIsImmutable(selectedBundle) ? <p>이 문서 묶음과 그 안의 문서 버전은 확정돼 바뀌지 않습니다.</p> : null}
            {!selectedIsLatest ? <p>최신 수정본이 아니므로 과거 이력으로만 표시합니다.</p> : null}
          </div>

          <ol className="document-preparation-steps" aria-label="문서 준비 단계">
            <li><span>1</span><div><strong>문서 등록</strong><small>{documents.length}개 문서 등록</small></div></li>
            <li><span>2</span><div><strong>안전 검사</strong><small>{safetySummary}</small></div></li>
            <li><span>3</span><div><strong>변환</strong><small>별도 상태를 추정하지 않고 구조화 상태와 함께 확인</small></div></li>
            <li><span>4</span><div><strong>구조화</strong><small>{structureSummary}</small></div></li>
            <li><span>5</span><div><strong>역할·버전 확인</strong><small>{documents.length > 0 ? "문서별 정보 확인" : "문서 등록 뒤 확인"}</small></div></li>
            <li><span>6</span><div><strong>묶음 확정</strong><small>{selectedBundle.status === "ready" ? "확정 완료" : "사람이 직접 확정해야 함"}</small></div></li>
          </ol>

          <div
            className={`document-preparation-dropzone ${dragging ? "is-dragging" : ""} ${!editable ? "is-disabled" : ""}`.trim()}
            role="button"
            tabIndex={editable ? 0 : -1}
            aria-disabled={!editable || uploadMutation.isPending}
            aria-describedby={!editable ? "document-upload-disabled" : undefined}
            aria-label="안전한 문서 등록"
            onClick={() => { if (editable && !uploadMutation.isPending) fileInputRef.current?.click(); }}
            onKeyDown={handleDropzoneKey}
            onDragEnter={(event) => { event.preventDefault(); if (editable) setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              className="visually-hidden"
              type="file"
              accept=".hwp,.hwpx,.pdf"
              multiple
              onChange={handleFileInput}
              disabled={!editable || uploadMutation.isPending}
            />
            <strong>{uploadMutation.isPending ? "문서를 순차 등록하는 중입니다." : "HWP · HWPX · PDF 문서 선택 또는 놓기"}</strong>
            <span>파일당 50MiB · 문서마다 따로 격리하고 검사합니다.</span>
            {!editable ? <span id="document-upload-disabled">최신 초안 묶음에서만 문서를 등록할 수 있습니다.</span> : null}
          </div>

          {uploadOutcomes.length > 0 ? (
            <ul className="document-preparation-upload-results" aria-label="문서별 업로드 결과">
              {uploadOutcomes.map((outcome) => (
                <li key={outcome.key} className={`is-${outcome.status}`}>
                  <strong>{outcome.filename}</strong>
                  <span>{outcome.status === "uploading" ? "진행 중" : outcome.status === "succeeded" ? "등록 성공" : "등록 실패"}</span>
                  <p>{outcome.message}</p>
                </li>
              ))}
            </ul>
          ) : null}

          {documents.length > 0 ? (
            <div className="document-preparation-documents">
              {documents.map((document) => (
                <DocumentMetadataEditor
                  key={document.id}
                  actorName={actorName}
                  document={document}
                  documents={documents}
                  editable={editable}
                  onSaved={async (message) => {
                    setFeedback(message);
                    await invalidateBundles();
                  }}
                />
              ))}
            </div>
          ) : <p className="document-preparation-empty">선택한 묶음에 등록된 문서가 없습니다.</p>}

          {selectedBundle.issues.length > 0 ? (
            <div className="document-preparation-issues">
              <strong>묶음 확인 항목</strong>
              <ul>
                {selectedBundle.issues.map((issue) => (
                  <li key={issue.issue_id} className={issue.blocking ? "is-blocking" : ""}>
                    <span>{issue.blocking ? "차단" : issue.severity}</span>
                    <p>{issue.message}</p>
                    <code>{issue.code}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="document-preparation-confirm">
            <div>
              <strong>문서 묶음 확정</strong>
              {confirmDisabledReasons.length === 0 ? (
                <p className="is-ready" role="status">문서 1건 이상 · 모든 문서 안전 확인 · 모든 문서 구조화 완료 · 차단 항목 0건을 확인했습니다. 서버가 같은 조건을 다시 검사합니다.</p>
              ) : (
                <ul id="document-confirm-disabled" aria-label="문서 묶음 확정 비활성 사유">
                  {confirmDisabledReasons.map((reason) => <li key={reason}>{reason}</li>)}
                </ul>
              )}
            </div>
            <button
              type="button"
              onClick={() => confirmMutation.mutate()}
              disabled={confirmReasons.length > 0 || confirmMutation.isPending}
              aria-describedby={confirmDisabledReasons.length > 0 ? "document-confirm-disabled" : undefined}
            >
              {confirmMutation.isPending ? "문서 묶음 확정 중" : "문서 묶음 확정하기"}
            </button>
          </div>
          {confirmMutation.error ? <MutationFeedback tone="error" problem={describeApiError(confirmMutation.error, "문서 묶음을 확정하지 못했습니다.")} /> : null}

          {selectedBundle.status === "ready" ? (
            <div className="document-preparation-start-review">
              <div>
                <strong>심층 검토 시작</strong>
                <p>확정된 문서 묶음만 입력으로 씁니다. 사전규격 심층 검토는 최종 입찰 Go/No-Go를 대신하지 않습니다.</p>
              </div>
              <div className="document-preparation-action-control">
                <button
                  type="button"
                  onClick={() => deepReviewMutation.mutate()}
                  disabled={deepReviewMutation.isPending || !actorName.trim()}
                  aria-describedby={deepReviewDisabledReason ? "deep-review-start-disabled" : undefined}
                >
                  {deepReviewMutation.isPending ? "심층 검토 생성 중" : "확정된 문서 묶음으로 심층 검토 시작"}
                </button>
                {deepReviewDisabledReason ? <DisabledReason id="deep-review-start-disabled">{deepReviewDisabledReason}</DisabledReason> : null}
              </div>
            </div>
          ) : null}
          {deepReviewProblem ? (
        <MutationFeedback tone="error" problem={deepReviewProblem}>
          {/* fail-closed 사실은 서버 message가 아니라 이 화면의 규칙이다. */}
          {deepReviewProblem.code === "service_unavailable"
            ? <p>활성 회사 프로필 버전과 분석 정책 버전이 모두 있어야 심층 검토를 시작합니다. 외부 제공자나 hosted OpenAI로 자동 전환하지 않습니다.</p>
            : null}
        </MutationFeedback>
      ) : null}
        </div>
      ) : null}

      {feedback ? <MutationFeedback tone="success">{feedback}</MutationFeedback> : null}
    </section>
  );
}
