import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { ActorField } from "../components/common/ActorField";
import { EmptyState } from "../components/common/EmptyState";
import { MutationFeedback } from "../components/common/MutationFeedback";
import { HintedButton } from "../components/proposal/HintedButton";
import { ProposalConfirmDialog } from "../components/proposal/ProposalConfirmDialog";
import { RequirementLinks } from "../components/proposal/RequirementLinks";
import { SECTION_PANEL_ID, SectionTabs } from "../components/proposal/SectionTabs";
import { SectionBody } from "../components/proposal/SectionBody";
import type { ProposalController } from "../components/proposal/useProposalController";
import { ApiError } from "../lib/api";
import { describeProposalApiError } from "../lib/apiErrors";
import {
  draftStatusLabel,
  findSection,
  isDraftActive,
  linkedRequirements,
  sectionLabel,
  sectionStatusLabel,
  SECTION_KEYS,
} from "../lib/proposal";
import { formatKstMinute } from "../lib/record";
import type { PractitionerVerdictView, ProposalDraft, ProposalSectionKey } from "../lib/types";
import { requirementText } from "../lib/verdict";
import "../styles/opportunity-record.css";
import "../styles/proposal.css";
import "../styles/verdict.css";

/*
 * 사업기회 레코드의 제안서 탭(`/opportunities/:id/proposal`, RL-04 spec "화면", ui-spec §4.5).
 *
 * 상태는 서버 `ProposalView`를 그대로 읽는다 — 화면이 초안·절 상태나 단계를 다시 계산하지 않는다.
 *   draft=null            "제안서 초안은 판정 뒤 만들 수 있습니다" + 초안 만들기(완료된 판정이 있을 때만 활성)
 *   queued · running      "초안 생성 중" + 절별 진행(만들어진 절은 바로 읽을 수 있다)
 *   partial               실패한 절 카드에 "생성 실패 · 다시 쓰기", 나머지 절은 그대로 검토
 *   failed                "초안 생성에 실패했습니다" + 절별 실패 사유
 *   superseded            "이전 초안입니다"(읽기 전용, `?draft_id=`로만 연다)
 *   completed             절 탭 → 본문 카드 + 우측 "이 절이 답하는 요구사항"
 * 좌측(단계·숫자·채워야 할 것)은 레코드 페이지의 좌측 열이라 이 파일이 그리지 않는다.
 * 정책 id·모델명·hash·토큰 수는 이 파일 어디에도 그리지 않는다. 가격·투입 인력·전략 수치와 최종 입찰 결정은
 * 이 탭에 없다 — 초안은 참고 자료이고 빈 자리는 사람이 채운다.
 */

export const PROPOSAL_ACTOR_ID = "pp-actor";

interface OpportunityProposalTabProps {
  controller: ProposalController;
  verdictView: PractitionerVerdictView | null;
  /** 완료된 판정이 있어 초안을 만들 수 있는가(서버 판정 view의 결과 유무). */
  verdictCompleted: boolean;
  actorName: string;
  actorMissing: boolean;
  onActorChange: (value: string) => void;
  /** 이전 초안(`?draft_id=`)을 보고 있을 때 최신 초안으로 돌아간다. */
  onShowLatest: () => void;
  viewingDraftId: string | null;
  /** 저장하지 않은 문장 수정이 있는지(이탈 확인). */
  onDirtyChange: (dirty: boolean) => void;
}

function ActorBar({ actorName, actorMissing, onActorChange }: Pick<OpportunityProposalTabProps, "actorName" | "actorMissing" | "onActorChange">) {
  return (
    <div className="pp-actor">
      <ActorField
        aria-invalid={actorMissing ? true : undefined}
        autoComplete="off"
        description="기록에 남는 표식이며 인증이 아닙니다."
        id={PROPOSAL_ACTOR_ID}
        label="기록자"
        onChange={onActorChange}
        placeholder="이름 입력"
        showRememberNote={false}
        value={actorName}
      />
      {actorMissing ? <p className="pp-actor-missing" role="alert">조작하려면 기록자 이름을 입력하십시오.</p> : null}
    </div>
  );
}

function DraftBanners({
  draft,
  controller,
  onShowLatest,
}: {
  draft: ProposalDraft;
  controller: ProposalController;
  onShowLatest: () => void;
}) {
  const failed = draft.sections.filter((section) => section.status === "failed").length;
  return (
    <>
      {isDraftActive(draft) ? (
        <div className="vd-banner" data-testid="draft-running-banner" role="status">
          <div className="vd-banner-body">
            <strong>초안 생성 중</strong>
            <p>절이 만들어지는 대로 아래 탭에서 읽을 수 있습니다. 끝나면 자동으로 갱신됩니다.</p>
            <ol aria-label="절별 진행" className="pp-progress">
              {SECTION_KEYS.map((key) => {
                const section = findSection(draft, key);
                return (
                  <li className="pp-progress-item" data-section={key} data-status={section?.status ?? "queued"} key={key}>
                    <span>{sectionLabel(key)}</span>
                    <span className="pp-progress-status">{sectionStatusLabel(section?.status ?? "queued")}</span>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>
      ) : null}
      {draft.status === "partial" ? (
        <div className="vd-banner is-warning" data-testid="draft-partial-banner" role="status">
          <div className="vd-banner-body">
            <strong>일부 절을 만들지 못했습니다</strong>
            <p>
              실패한 절 {failed}개는 해당 절 카드에서 다시 쓰거나 사람이 직접 작성하십시오. 나머지 절은 그대로 검토할 수 있고,
              PDF에는 실패한 절이 생성 실패로 표시됩니다.
            </p>
          </div>
        </div>
      ) : null}
      {draft.status === "failed" ? (
        <div className="vd-banner is-warning" data-testid="draft-failed-banner" role="status">
          <div className="vd-banner-body">
            <strong>초안 생성에 실패했습니다</strong>
            <p>실패한 절의 사유는 각 절에 적혀 있습니다. 검증을 통과하지 못한 결과는 자동으로 고치지 않습니다. 다시 만들거나 사람이 직접 작성하십시오.</p>
          </div>
        </div>
      ) : null}
      {draft.status === "superseded" ? (
        <div className="vd-banner" data-testid="draft-superseded-banner" role="status">
          <span className="vd-pill is-muted">{draftStatusLabel("superseded")}</span>
          <p>더 새로운 초안이 있어 이 초안은 읽기만 할 수 있습니다.</p>
          <Button label="최신 초안 보기" onClick={onShowLatest} size="sm" />
        </div>
      ) : null}
      {draft.latest_export ? (
        <p className="rec-side-note" data-testid="latest-export">
          최근 PDF · {formatKstMinute(draft.latest_export.created_at)}{" "}
          <button className="pp-export-link" disabled={controller.pending !== null} onClick={() => { void controller.downloadLatest(); }} type="button">
            다시 내려받기
          </button>
        </p>
      ) : null}
      {controller.problem ? (
        <MutationFeedback onRecover={controller.reload} problem={controller.problem} tone="error" />
      ) : null}
    </>
  );
}

function DraftView({
  draft,
  controller,
  verdictView,
  onShowLatest,
  onDirtyChange,
}: {
  draft: ProposalDraft;
  controller: ProposalController;
  verdictView: PractitionerVerdictView | null;
  onShowLatest: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [sectionKey, setSectionKey] = useState<ProposalSectionKey>("overview");
  const [selectedSentenceId, setSelectedSentenceId] = useState<string | null>(null);
  const [focusedParagraphId, setFocusedParagraphId] = useState<string | null>(null);

  const section = findSection(draft, sectionKey);
  const readOnly = draft.status === "superseded";
  // 검토 완료·제출 준비 단계에서는 절을 다시 쓰지 않는다(새 초안은 헤더 "다시 만들기", 결정 B50).
  const rewriteLocked = draft.stage === "reviewed" || draft.stage === "ready";
  const busy = controller.pending !== null;
  const links = section ? linkedRequirements(section, verdictView, requirementText) : [];

  return (
    <>
      <DraftBanners controller={controller} draft={draft} onShowLatest={onShowLatest} />
      <SectionTabs
        draft={draft}
        onChange={(key) => {
          setSectionKey(key);
          setSelectedSentenceId(null);
          setFocusedParagraphId(null);
        }}
        value={sectionKey}
      />
      <div
        aria-labelledby={`pp-tab-${sectionKey}`}
        className="pp-panel"
        id={SECTION_PANEL_ID}
        role="tabpanel"
      >
        <SectionBody
          busy={busy}
          focusedParagraphId={focusedParagraphId}
          onDirtyChange={onDirtyChange}
          onRegenerate={() => controller.openConfirm({ kind: "regenerate", sectionKey })}
          onReview={() => { if (section) void controller.reviewSection(sectionKey, section.revision); }}
          onSaveSentence={(sentenceId, text) => controller.editSentence(sentenceId, text)}
          onSelectSentence={setSelectedSentenceId}
          pendingAction={controller.pending}
          readOnly={readOnly}
          rewriteLocked={rewriteLocked}
          section={section}
          sectionKey={sectionKey}
          selectedSentenceId={selectedSentenceId}
        />
        <RequirementLinks onGoParagraph={setFocusedParagraphId} rows={links} />
      </div>
    </>
  );
}

export function OpportunityProposalTab({
  controller,
  verdictView,
  verdictCompleted,
  actorName,
  actorMissing,
  onActorChange,
  onShowLatest,
  viewingDraftId,
  onDirtyChange,
}: OpportunityProposalTabProps) {
  const { query, draft } = controller;

  if (query.isPending) {
    return <p className="rec-status" role="status">제안서 초안을 불러오는 중입니다.</p>;
  }
  if (query.isError || !query.data) {
    const notFound = query.error instanceof ApiError && query.error.status === 404 && viewingDraftId !== null;
    return notFound ? (
      <EmptyState
        action={{ label: "최신 초안 보기", onClick: onShowLatest }}
        compact
        description="없거나 이 사업기회의 초안이 아닙니다. 최신 초안으로 돌아가 확인하십시오."
        title="초안을 찾을 수 없습니다"
      />
    ) : (
      <EmptyState
        action={{ label: "다시 시도", onClick: () => { void query.refetch(); } }}
        compact
        problem={describeProposalApiError(query.error, "제안서 초안을 불러오지 못했습니다.")}
        title="제안서 초안을 불러오지 못했습니다"
        tone="error"
      />
    );
  }

  const actorBar = <ActorBar actorMissing={actorMissing} actorName={actorName} onActorChange={onActorChange} />;
  const dialog = (
    <ProposalConfirmDialog
      confirm={controller.confirm}
      onClose={controller.closeConfirm}
      onConfirm={() => { void controller.runConfirm(); }}
      pending={controller.pending !== null}
    />
  );

  if (draft === null) {
    return (
      <div className="pp-main" data-testid="proposal-empty">
        {actorBar}
        {controller.problem ? <MutationFeedback onRecover={controller.reload} problem={controller.problem} tone="error" /> : null}
        <EmptyState
          compact
          description={
            verdictCompleted
              ? "판정이 끝났습니다. 초안을 만들면 제안서 6개 절이 생성됩니다. 가격·투입 인력·전략 수치는 만들지 않고 빈 자리로 둡니다."
              : "아직 완료된 판정이 없습니다. 판정 탭에서 판정 상태를 확인한 뒤 초안을 만들 수 있습니다."
          }
          title="제안서 초안은 판정 뒤 만들 수 있습니다"
        />
        <div className="pp-empty-actions">
          <HintedButton
            blockedReason={
              !verdictCompleted ? "아직 완료된 판정이 없습니다" : controller.pending !== null ? "처리 중입니다" : null
            }
            label="초안 만들기"
            onClick={() => controller.openConfirm({ kind: "create" })}
            pendingLabel={controller.pending === "create" ? "요청 중…" : null}
            variant="primary"
          />
        </div>
        {dialog}
      </div>
    );
  }

  return (
    <div className="pp-main" data-draft-status={draft.status} data-testid="proposal-draft">
      {actorBar}
      <DraftView
        controller={controller}
        draft={draft}
        key={draft.draft_id}
        onDirtyChange={onDirtyChange}
        onShowLatest={onShowLatest}
        verdictView={verdictView}
      />
      {dialog}
    </div>
  );
}
