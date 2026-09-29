import { useRef, useState } from "react";
import { Button } from "@astryxdesign/core";
import { previewDeepReview } from "./api";
import type { DeepReviewPreview } from "./types";
import { generateRequestId } from "../../lib/requestId";
import { describeApiError } from "../../lib/apiErrors";

/** Mount with an input identity key: changed settings discard the old consent. */
export function LunaRequest({ noticeId, bundleId, reviewId, verification, actor, onSubmit }: {
  noticeId: number; bundleId: string; reviewId?: string; verification: boolean; actor: string;
  onSubmit: (previewId: string, requestId: string) => Promise<unknown>;
}) {
  const [preview, setPreview] = useState<DeepReviewPreview | null>(null);
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
        setPreview(await previewDeepReview(noticeId, bundleId, verification, reviewId));
        requestId.current = null;
      }
    } catch (failure) {
      const problem = describeApiError(failure, "요청을 처리할 수 없습니다.");
      setError(`${problem.code}: ${problem.title} ${problem.detail}`);
      if (["preview_changed", "preview_used"].includes(problem.code ?? "")) setPreview(null);
    } finally { lock.current = false; setBusy(false); }
  }
  const policy = preview?.input.policy;
  const validation = policy && typeof policy === "object" && "validation" in policy ? policy.validation : null;
  const validationOff = validation && typeof validation === "object" && "result_checks" in validation && validation.result_checks === "disabled_reference_v1";
  return <section aria-label="Luna 심층검토 요청">
    <p>사용자 요청 시 순차 실행합니다. 참조 분석이며 품질은 미측정입니다. 실행 중 개요검토가 대기할 수 있습니다.</p>
    <Button label="전송 내용 미리보기" onClick={() => void act(false)} isDisabled={busy || submitted} />
    {preview && <section aria-label="외부 전송 승인">
      <p>{preview.model} · {preview.reasoning_effort} · {preview.provider}</p>
      <p>{validationOff ? "내용·참조·누락 검증 미실시 · 형식·저장 무결성 검사만 수행" : `원문 대조 ${preview.source_verification_enabled ? "사용" : "사용 안 함"}`} · 품질 미측정</p>
      <p>아래 문서 내용과 회사자료, 같은 실행의 선행 분석 결과를 외부 모델에 전송합니다.</p>
      <details><summary>전송 원천 입력과 정책 전체 확인</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxBlockSize: "calc(var(--spacing-12) * 8)", overflow: "auto" }}>{JSON.stringify(preview.input, null, 2)}</pre></details>
      <p style={{ overflowWrap: "anywhere" }}>입력 해시: {preview.input_sha256}</p>
      <p>담당자 이름은 감사 기록입니다. 최종 제출하면 이 실행의 외부 전송에 동의한 것으로 기록합니다.</p>
      <Button label={submitted ? "요청 등록됨" : busy ? "처리 중" : "전송 승인하고 심층검토 요청"} onClick={() => void act(true)} isDisabled={busy || submitted || !actor.trim()} />
    </section>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
