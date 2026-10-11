import { useRef, useState, type ReactNode } from "react";
import { Button } from "@astryxdesign/core";
import { previewDeepReview } from "./api";
import type { DeepReviewPreview } from "./types";
import { generateRequestId } from "../../lib/requestId";
import { describeApiError, describeCompanyApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import { companyApi, shortIdentity, type CompanyDTO, type CompanyDeepReviewPreview, type Uuid } from "../../lib/companyApi";
import { qualityStatusLabel } from "../../lib/qualityStatus";

/**
 * 같은 Luna 요청 흐름을 다른 endpoint 계열에 붙이는 adapter.
 *
 * 미리보기·승인·request_id 규칙은 이 컴포넌트가 소유하고(새 미리보기마다 승인 초기화,
 * 같은 승인의 재시도는 같은 request_id, 중복 클릭은 한 번만 전송, `preview_changed`·
 * `preview_used`는 승인 폐기), adapter는 미리보기를 어느 endpoint로 만들지와 오류 문구,
 * 승인 화면에 덧붙일 문맥만 정한다. adapter가 없으면 기존 사전규격 경로 그대로다.
 */
export interface LunaRequestAdapter<P extends DeepReviewPreview = DeepReviewPreview> {
  /** 사람이 `전송 내용 미리보기`를 누를 때만 부른다. 화면을 열기만 해서는 부르지 않는다. */
  preview: () => Promise<P>;
  describeError: (failure: unknown, fallback: string) => ApiErrorDescription;
  /** 승인 상자 맨 위에 덧붙일 문맥(전송 대상 회사·버전·입력 범위 등). */
  renderApprovalContext?: (preview: P) => ReactNode;
  /** 승인을 막아야 하는 이유(예: 응답의 회사가 요청한 회사와 다름). `null`이면 막지 않는다. */
  approvalBlockedReason?: (preview: P) => string | null;
}

/** 승인을 폐기해야 하는 서버 코드. 같은 미리보기로 다시 승인하지 않는다. */
const APPROVAL_DISCARD_CODES = ["preview_changed", "preview_used"];

/** Mount with an input identity key: changed settings discard the old consent. */
export function LunaRequest<P extends DeepReviewPreview = DeepReviewPreview>({ noticeId, bundleId, reviewId, verification, actor, onSubmit, adapter }: {
  noticeId: number; bundleId: string; reviewId?: string; verification: boolean; actor: string;
  onSubmit: (previewId: string, requestId: string) => Promise<unknown>;
  adapter?: LunaRequestAdapter<P>;
}) {
  const [preview, setPreview] = useState<P | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef<string | null>(null);
  const lock = useRef(false);
  const [submitted, setSubmitted] = useState(false);
  async function act(submit: boolean) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      if (submit && preview) {
        requestId.current ??= generateRequestId();
        await onSubmit(preview.preview_id, requestId.current);
        setSubmitted(true);
      } else {
        const next = adapter
          ? await adapter.preview()
          : await previewDeepReview(noticeId, bundleId, verification, reviewId) as P;
        setPreview(next);
        requestId.current = null;
      }
    } catch (failure) {
      const problem = adapter
        ? adapter.describeError(failure, "요청을 처리할 수 없습니다.")
        : describeApiError(failure, "요청을 처리할 수 없습니다.");
      setError(`${problem.code}: ${problem.title} ${problem.detail}`);
      if (APPROVAL_DISCARD_CODES.includes(problem.code ?? "")) setPreview(null);
    } finally { lock.current = false; setBusy(false); }
  }
  const policy = preview?.input.policy;
  const validation = policy && typeof policy === "object" && "validation" in policy ? policy.validation : null;
  const validationOff = validation && typeof validation === "object" && "result_checks" in validation && validation.result_checks === "disabled_reference_v1";
  const blockedReason = preview && adapter?.approvalBlockedReason ? adapter.approvalBlockedReason(preview) : null;
  return <section aria-label="Luna 심층검토 요청">
    <p>사용자 요청 시 순차 실행합니다. 참조 분석이며 품질은 미측정입니다. 실행 중 개요검토가 대기할 수 있습니다.</p>
    <Button label="전송 내용 미리보기" onClick={() => void act(false)} isDisabled={busy || submitted} />
    {preview && <section aria-label="외부 전송 승인">
      {adapter?.renderApprovalContext ? adapter.renderApprovalContext(preview) : null}
      <p>{preview.model} · {preview.reasoning_effort} · {preview.provider}</p>
      <p>{validationOff ? "내용·참조·누락 검증 미실시 · 형식·저장 무결성 검사만 수행" : `원문 대조 ${preview.source_verification_enabled ? "사용" : "사용 안 함"}`} · 품질 미측정</p>
      <p>아래 문서 내용과 회사자료, 같은 실행의 선행 분석 결과를 외부 모델에 전송합니다.</p>
      <details><summary>전송 원천 입력과 정책 전체 확인</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxBlockSize: "calc(var(--spacing-12) * 8)", overflow: "auto" }}>{JSON.stringify(preview.input, null, 2)}</pre></details>
      <p style={{ overflowWrap: "anywhere" }}>입력 해시: {preview.input_sha256}</p>
      <p>담당자 이름은 감사 기록입니다. 최종 제출하면 이 실행의 외부 전송에 동의한 것으로 기록합니다.</p>
      {blockedReason ? <p role="alert">{blockedReason}</p> : null}
      <Button label={submitted ? "요청 등록됨" : busy ? "처리 중" : "전송 승인하고 심층검토 요청"} onClick={() => void act(true)} isDisabled={busy || submitted || !actor.trim() || blockedReason !== null} />
    </section>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

// ---------------------------------------------------------------------------
// 회사 경로 adapter (가상회사 데모, `docs/work/demo-contract.md` §6·§9)

function countOf(input: Record<string, unknown>, key: string): string {
  const value = input[key];
  return Array.isArray(value) ? `${value.length}건` : "확인 불가";
}

function textOf(input: Record<string, unknown>, key: string): string | null {
  const value = input[key];
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return null;
}

/**
 * 회사 심층 검토의 Luna 요청 adapter. 미리보기는 `POST /api/companies/{company_id}/pre-specs/{notice_id}/deep-review-previews`
 * (재시도면 `review_id`를 함께) 한 곳뿐이며, 승인·생성 body와 request_id 규칙은 기존 Luna 흐름과 같다.
 *
 * 회사 경로 계약은 원문 대조 사용(`source_verification_enabled: true`)만 받으므로 그 값만 보낸다.
 * 응답의 회사·공고·문서 묶음·재시도 대상이 요청과 다르면 승인을 막는다(쓰기 전에 회사·버전 검사).
 */
export function createCompanyLunaAdapter({ companyId, company, noticeId, bundleId, reviewId }: {
  companyId: Uuid;
  company: CompanyDTO | null;
  noticeId: number;
  bundleId: Uuid;
  reviewId?: Uuid;
}): LunaRequestAdapter<CompanyDeepReviewPreview> {
  return {
    preview: () => companyApi.createDeepReviewPreview(companyId, noticeId, {
      bundle_id: bundleId,
      source_verification_enabled: true,
      ...(reviewId ? { review_id: reviewId } : {}),
    }),
    describeError: describeCompanyApiError,
    approvalBlockedReason: (preview) => {
      const input = preview.input;
      // 승인 상자는 어느 회사로 실행이 가는지 이름으로 보여야 한다. 회사 조회가 끝나지 않았거나
      // 실패했거나 다른 회사이면 승인하지 않는다.
      if (company === null) {
        return "전송 대상 회사 정보를 아직 확인하지 못했습니다(불러오는 중이거나 실패). 회사 이름이 확인될 때까지 승인할 수 없습니다.";
      }
      if (company.company_id !== companyId) {
        return "확인한 회사 정보가 이 화면의 회사와 다릅니다. 이 미리보기로는 승인하지 않습니다.";
      }
      if (preview.company_id !== companyId || textOf(input, "company_id") !== companyId) {
        return "미리보기 응답의 회사가 이 화면의 회사와 다릅니다. 이 미리보기로는 승인하지 않습니다.";
      }
      if (textOf(input, "notice_id") !== String(noticeId) || textOf(input, "bundle_id") !== bundleId) {
        return "미리보기 응답의 공고 또는 문서 묶음이 요청과 다릅니다. 이 미리보기로는 승인하지 않습니다.";
      }
      if ((textOf(input, "target_review_id") ?? null) !== (reviewId ?? null)) {
        return "미리보기 응답의 재시도 대상이 요청과 다릅니다. 이 미리보기로는 승인하지 않습니다.";
      }
      return null;
    },
    renderApprovalContext: (preview) => {
      const input = preview.input;
      return (
        <div className="cw-approval-context" data-testid="company-approval-context">
          <p data-testid="company-approval-company">
            전송 대상 회사 · <strong>{company?.name ?? "회사 이름 확인 중"}</strong>
            {" · "}
            {company === null ? "가상회사 표식 확인 중" : company.is_fictional ? "가상회사" : "가상회사 표식 없음"}
          </p>
          <p data-testid="company-approval-quality">품질 표식 · {qualityStatusLabel(preview.quality_status)}</p>
          <p data-testid="company-approval-verification">원문 대조 · {preview.source_verification_enabled ? "사용" : "사용 안 함"} (회사 경로는 사용만 허용)</p>
          <dl className="cw-facts" aria-label="회사 지식 버전">
            <dt>프로필 버전</dt><dd title={preview.profile_version_id}>{preview.profile_version_id}</dd>
            <dt>그래프 버전</dt><dd title={preview.graph_version_id}>{preview.graph_version_id}</dd>
            <dt>그래프 해시</dt><dd title={preview.graph_sha256}>{shortIdentity(preview.graph_sha256)}</dd>
            <dt>온톨로지</dt><dd>{preview.ontology_version}</dd>
          </dl>
          <dl className="cw-facts" aria-label="전송 입력 범위" data-testid="company-approval-scope">
            <dt>공고</dt><dd>notice {textOf(input, "notice_id") ?? "확인 불가"}</dd>
            <dt>문서 묶음</dt><dd title={textOf(input, "bundle_id") ?? undefined}>{shortIdentity(textOf(input, "bundle_id"))}</dd>
            <dt>문서 버전</dt><dd>{countOf(input, "document_version_ids")}</dd>
            <dt>요구사항</dt><dd>{countOf(input, "requirements")}</dd>
            <dt>회사 사실</dt><dd>{countOf(input, "profile_facts")}</dd>
            <dt>회사 근거</dt><dd>{countOf(input, "profile_evidence")}</dd>
            <dt>그래프 경로</dt><dd>{countOf(input, "graph_paths")}</dd>
            <dt>재시도 대상</dt><dd>{textOf(input, "target_review_id") ?? "없음 · 새 검토"}</dd>
          </dl>
          <p className="cw-caption">회사 설정은 가상 시나리오이며 실제 회사 사실이 아닙니다. 이 승인은 외부 전송 동의이며 회사 핏(적합성) 판정 승인이 아닙니다.</p>
        </div>
      );
    },
  };
}
