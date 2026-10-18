import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import type { ToastVariant } from "../common/Toast";
import { api } from "../../lib/api";
import { describeProposalApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import { isDraftActive, isSectionActive } from "../../lib/proposal";
import { generateRequestId } from "../../lib/requestId";
import type { ProposalDraft, ProposalSectionKey, ProposalView } from "../../lib/types";

/*
 * 제안서 초안 탭의 서버 상태와 조작(RL-04 spec "REST", ui-spec §4.5).
 *
 * 헤더 액션(PDF 내보내기·다시 만들기·⋯)과 탭 본문이 같은 초안을 읽고 같은 조작 규칙을 쓰도록 레코드
 * 페이지가 이 hook을 한 번 부른다. 화면은 초안·단계·절 상태를 다시 계산하지 않고 서버 응답을 읽기만 한다.
 *
 * - 담당자 이름은 기록에 남는 표식이며 인증이 아니다. 없으면 요청하지 않고 이름 칸으로 안내한다.
 * - 요청 식별자는 같은 입력의 재시도에서 같은 값을 쓴다(응답을 잃은 요청이 두 번 접수되지 않게).
 *   성공하면 지워서 다음 조작은 새 식별자를 쓴다.
 * - 새 초안·절 다시 쓰기·제출 준비는 확인 대화상자를 거친다. 확인 전에는 요청하지 않는다.
 * - 초안이나 절이 생성 중이면 5초마다 다시 읽는다.
 */

const PROPOSAL_POLL_MS = 5000;

export type ProposalConfirm =
  | { kind: "create" }
  | { kind: "regenerate"; sectionKey: ProposalSectionKey }
  | { kind: "ready" };

export const ACTOR_MISSING: ApiErrorDescription = {
  title: "기록자 이름이 필요합니다.",
  detail: "위 기록자 칸에 이름을 입력한 뒤 다시 시도하십시오. 이름은 기록에 남는 표식이며 인증이 아닙니다.",
  action: null,
  code: null,
};

const ACTION_BUSY: ApiErrorDescription = {
  title: "다른 조작을 처리하고 있습니다.",
  detail: "처리가 끝난 뒤 다시 저장하십시오. 입력한 문장은 그대로 남아 있습니다.",
  action: null,
  code: null,
};

export interface ProposalController {
  query: UseQueryResult<ProposalView>;
  draft: ProposalDraft | null;
  /** 처리 중인 조작. 없으면 `null`이다. */
  pending: "create" | "regenerate" | "review" | "edit" | "export" | "ready" | null;
  problem: ApiErrorDescription | null;
  dismissProblem: () => void;
  confirm: ProposalConfirm | null;
  openConfirm: (next: ProposalConfirm) => void;
  closeConfirm: () => void;
  runConfirm: () => Promise<void>;
  reviewSection: (sectionKey: ProposalSectionKey, revision: number) => Promise<void>;
  /** 성공이면 `null`, 실패면 편집 영역에 보일 오류를 돌려준다. */
  editSentence: (sentenceId: string, text: string) => Promise<ApiErrorDescription | null>;
  exportPdf: () => Promise<void>;
  /** 이미 내보낸 최근 PDF를 다시 내려받는다(새 PDF를 만들지 않는다). */
  downloadLatest: () => Promise<void>;
  /** 오류를 다시 읽어 최신 상태를 가져온다. */
  reload: () => void;
}

interface Options {
  opportunityId: number;
  /** 제안서 탭이 열려 있을 때만 읽는다. */
  enabled: boolean;
  /** `?draft_id=`로 고른 이전 초안. 없으면 최신 초안이다. */
  draftId: string | null;
  actorName: string;
  /** 이름이 비어 있을 때 호출한다(이름 칸으로 초점을 옮긴다). */
  onActorMissing: () => void;
  showToast: (message: string, variant?: ToastVariant) => void;
  /** 새 초안 요청이 접수되면(`?draft_id=` 같은 이전 초안 선택을 풀러 간다). */
  onCreated: () => void;
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // 내려받기가 시작된 뒤에 해제한다.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

const PDF_MISMATCH: ApiErrorDescription = {
  title: "내려받은 PDF가 기록과 다릅니다.",
  detail: "서버가 알려 준 PDF 해시와 받은 파일의 해시가 달라 저장하지 않았습니다. 잠시 뒤 다시 내보내거나 담당자에게 문의하십시오.",
  action: null,
  code: null,
};

class PdfMismatchError extends Error {}

export function useProposalController({
  opportunityId,
  enabled,
  draftId,
  actorName,
  onActorMissing,
  showToast,
  onCreated,
}: Options): ProposalController {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["opportunity-proposal", opportunityId, draftId ?? "latest"],
    queryFn: ({ signal }) => api.getOpportunityProposal(opportunityId, { draftId }, { signal }),
    enabled,
    retry: false,
    refetchInterval: (state) => {
      const draft = state.state.data?.draft ?? null;
      const active = isDraftActive(draft) || (draft?.sections.some((section) => isSectionActive(section)) ?? false);
      return active ? PROPOSAL_POLL_MS : false;
    },
  });
  const draft = query.data?.draft ?? null;

  const [pending, setPending] = useState<ProposalController["pending"]>(null);
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const [confirm, setConfirm] = useState<ProposalConfirm | null>(null);
  const lock = useRef(false);
  const requestIds = useRef(new Map<string, string>());

  const requestIdFor = (fingerprint: string): string => {
    const existing = requestIds.current.get(fingerprint);
    if (existing) return existing;
    const created = generateRequestId();
    requestIds.current.set(fingerprint, created);
    return created;
  };

  const refresh = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["opportunity-proposal", opportunityId] }),
      queryClient.invalidateQueries({ queryKey: ["opportunity-activity", opportunityId] }),
    ]);
  }, [opportunityId, queryClient]);

  const fetchAndSave = async (targetDraftId: string, exportId: string, expectedSha: string) => {
    const { blob, sha256 } = await api.getProposalExportPdf(targetDraftId, exportId);
    // 서버가 알려 준 PDF 해시와 받은 파일의 헤더 해시가 다르면 저장하지 않는다.
    if (sha256 !== null && sha256 !== expectedSha) throw new PdfMismatchError();
    triggerDownload(blob, `제안서-초안-${opportunityId}.pdf`);
  };

  const actor = actorName.trim();
  const needActor = (): boolean => {
    if (actor) return false;
    onActorMissing();
    return true;
  };

  const openConfirm = useCallback((next: ProposalConfirm) => {
    if (!actorName.trim()) {
      onActorMissing();
      return;
    }
    setProblem(null);
    setConfirm(next);
  }, [actorName, onActorMissing]);

  const closeConfirm = useCallback(() => {
    if (lock.current) return;
    setConfirm(null);
  }, []);

  const runConfirm = async () => {
    if (!confirm || lock.current || needActor()) return;
    lock.current = true;
    setProblem(null);
    try {
      if (confirm.kind === "create") {
        setPending("create");
        const fingerprint = `create:${opportunityId}`;
        await api.requestOpportunityProposal(opportunityId, requestIdFor(fingerprint), actor);
        requestIds.current.delete(fingerprint);
        setConfirm(null);
        onCreated();
        showToast("제안서 초안을 요청했습니다. 생성이 끝나면 절별로 보입니다.");
      } else if (confirm.kind === "regenerate" && draft) {
        setPending("regenerate");
        const section = draft.sections.find((entry) => entry.section_key === confirm.sectionKey);
        const fingerprint = `regenerate:${draft.draft_id}:${confirm.sectionKey}:${section?.revision ?? 0}`;
        await api.regenerateProposalSection(draft.draft_id, confirm.sectionKey, requestIdFor(fingerprint), actor);
        requestIds.current.delete(fingerprint);
        setConfirm(null);
        showToast("이 절을 다시 쓰도록 요청했습니다. 새 버전이 만들어지면 보입니다.");
      } else if (confirm.kind === "ready" && draft) {
        setPending("ready");
        const fingerprint = `ready:${draft.draft_id}`;
        await api.markProposalReady(draft.draft_id, requestIdFor(fingerprint), actor);
        requestIds.current.delete(fingerprint);
        setConfirm(null);
        showToast("제출 준비로 표시했습니다.");
      }
      await refresh();
    } catch (error) {
      // 입력은 그대로 두고 같은 조작의 재시도는 같은 요청 식별자를 쓴다.
      setConfirm(null);
      setProblem(describeProposalApiError(error, "요청을 처리하지 못했습니다."));
      void refresh();
    } finally {
      lock.current = false;
      setPending(null);
    }
  };

  const reviewSection = async (sectionKey: ProposalSectionKey, revision: number) => {
    if (!draft || lock.current || needActor()) return;
    lock.current = true;
    setPending("review");
    setProblem(null);
    try {
      const fingerprint = `review:${draft.draft_id}:${sectionKey}:${revision}`;
      await api.reviewProposalSection(draft.draft_id, sectionKey, requestIdFor(fingerprint), actor);
      requestIds.current.delete(fingerprint);
      showToast("이 절을 검토 완료로 표시했습니다.");
      await refresh();
    } catch (error) {
      setProblem(describeProposalApiError(error, "검토 완료로 표시하지 못했습니다."));
      void refresh();
    } finally {
      lock.current = false;
      setPending(null);
    }
  };

  const editSentence = async (sentenceId: string, text: string): Promise<ApiErrorDescription | null> => {
    if (!draft) return null;
    if (lock.current) return ACTION_BUSY;
    if (!actor) {
      onActorMissing();
      return ACTOR_MISSING;
    }
    lock.current = true;
    setPending("edit");
    setProblem(null);
    try {
      const fingerprint = `edit:${draft.draft_id}:${sentenceId}:${text}`;
      await api.editProposalSentence(draft.draft_id, sentenceId, text, requestIdFor(fingerprint), actor);
      requestIds.current.delete(fingerprint);
      showToast("문장을 고쳤습니다. 생성 원문은 바뀌지 않고 수정 기록으로 남습니다.");
      await refresh();
      return null;
    } catch (error) {
      void refresh();
      return describeProposalApiError(error, "문장을 저장하지 못했습니다.");
    } finally {
      lock.current = false;
      setPending(null);
    }
  };

  const exportPdf = async () => {
    if (!draft || lock.current || needActor()) return;
    lock.current = true;
    setPending("export");
    setProblem(null);
    try {
      const fingerprint = `export:${draft.draft_id}`;
      const receipt = await api.exportProposal(draft.draft_id, requestIdFor(fingerprint), actor);
      requestIds.current.delete(fingerprint);
      // 생성은 POST, 내려받기는 부작용 없는 GET이다. 같은 내용이면 서버가 기존 PDF를 돌려준다(created=false).
      await fetchAndSave(draft.draft_id, receipt.export_id, receipt.pdf_sha256);
      showToast(receipt.created ? "PDF를 만들었습니다. 내려받기를 시작합니다." : "내용이 같은 PDF가 이미 있어 그대로 내려받습니다.");
      await refresh();
    } catch (error) {
      setProblem(error instanceof PdfMismatchError ? PDF_MISMATCH : describeProposalApiError(error, "PDF를 내보내지 못했습니다."));
      void refresh();
    } finally {
      lock.current = false;
      setPending(null);
    }
  };

  const downloadLatest = async () => {
    const latest = draft?.latest_export ?? null;
    if (!draft || !latest || lock.current) return;
    lock.current = true;
    setPending("export");
    setProblem(null);
    try {
      await fetchAndSave(draft.draft_id, latest.export_id, latest.pdf_sha256);
    } catch (error) {
      setProblem(error instanceof PdfMismatchError ? PDF_MISMATCH : describeProposalApiError(error, "PDF를 내려받지 못했습니다."));
    } finally {
      lock.current = false;
      setPending(null);
    }
  };

  return {
    query,
    draft,
    pending,
    problem,
    dismissProblem: () => setProblem(null),
    confirm,
    openConfirm,
    closeConfirm,
    runConfirm,
    reviewSection,
    editSentence,
    exportPdf,
    downloadLatest,
    reload: () => { setProblem(null); void query.refetch(); void refresh(); },
  };
}
