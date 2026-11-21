import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { Ellipsis } from "lucide-react";
import { PageHeaderActions } from "../common/PageHeaderActions";
import type { RecordDecisionAxis, RecordPill } from "../../lib/record";

/*
 * 레코드 헤더(ui-spec §3, RL-02 spec "레코드 헤더"): 기관 머리글자 아이콘(40px, teal) · 제목 ·
 * pill 4개(단계·마감·판정·추적 상태, 순서 고정) · 액션.
 *
 * 판정 보기는 서버가 준 판정 결과가 있을 때만 열린다(RL-03). 판정 탭에서는 제안서 초안 · 다시 판정 · ⋯가
 * 액션이고 ⋯에 판정 오류 제보·실행 정보가 더해진다. 제안서 초안은 완료된 판정이 있을 때만 열리고 제안서
 * 탭으로 간다(RL-04). 제안서 탭에서는 PDF로 내보내기(주) · 다시 만들기 · ⋯가 액션이고 ⋯에 제출 준비로 표시와
 * 후속(HWP·버전 비교, 비활성)이 더해진다. ⋯ 메뉴의 추적 항목은 기존 추적 대화상자를 여는 자리일 뿐 저장
 * 규칙을 새로 갖지 않는다.
 *
 * pill 아래 결정 축 요약 줄(설계고도화안 C-6)은 사람이 내리는 결정 셋(추적 결정 · 판정 확인 · 최종
 * Go/No-Go)을 축마다 이름과 상태로 적는다. pill이 사업 사실(단계·마감)과 판정 결과를 짧게 보이는 자리라면
 * 이 줄은 "누가 무엇을 아직 정하지 않았나"를 보이는 자리이며 셋을 한 상태로 합치지 않는다.
 */

export type RecordMenuAction = "tracking" | "reset" | "signal" | "candidate";
export type VerdictMenuAction = "verdict-feedback" | "verdict-run-info";

/** 판정 관련 헤더 액션(RL-03). 판정 탭이 아니면 `판정 보기`, 판정 탭이면 `다시 판정`과 ⋯ 추가 항목이다. */
export interface RecordVerdictActions {
  /** 지금 판정 탭인가. */
  onVerdictTab: boolean;
  /** 최종 판정 결과가 있어 `판정 보기`를 열 수 있는가. */
  hasResult: boolean;
  onOpenVerdict: () => void;
  /** `다시 판정`을 막는 이유. 열 수 있으면 `null`이다. */
  requestBlockedReason: string | null;
  /** 요청 단추 이름. 판정 기록이 없으면 `판정 요청`, 있으면 `다시 판정`이다(`verdictRequestLabel`). */
  requestLabel: string;
  onRequestVerdict: () => void;
  /** ⋯의 판정 오류 제보·실행 정보를 막는 이유(없으면 `null`). */
  feedbackBlockedReason: string | null;
  runInfoBlockedReason: string | null;
  onVerdictMenu: (action: VerdictMenuAction) => void;
  /** `제안서 초안`(제안서 탭으로 간다)을 막는 이유. 완료된 판정이 있으면 `null`이다(RL-04). */
  proposalBlockedReason: string | null;
  onOpenProposal: () => void;
}

/** 제안서 탭의 헤더 액션(RL-04). */
export interface RecordProposalActions {
  /** 지금 제안서 탭인가. */
  onProposalTab: boolean;
  showActions: boolean;
  /** `PDF로 내보내기`를 막는 이유(없으면 `null`). */
  exportBlockedReason: string | null;
  exportPending: boolean;
  onExport: () => void;
  /** `다시 만들기`(새 초안)를 막는 이유(없으면 `null`). */
  regenerateBlockedReason: string | null;
  onRegenerate: () => void;
  /** ⋯의 `제출 준비로 표시`를 막는 이유(없으면 `null`). */
  readyBlockedReason: string | null;
  onReady: () => void;
}

export interface RecordMenuState {
  /** 비활성이면 그 이유. 활성이면 `null`이다. */
  resetBlockedReason: string | null;
  signalBlockedReason: string | null;
  candidateBlockedReason: string | null;
  onSelect: (action: RecordMenuAction) => void;
}

interface RecordHeaderProps {
  title: string;
  /** 예전 머리글자 아이콘 자리. 최종 시안에서 아이콘을 뺐고 값은 셸 헤더의 화면 이름 줄이 쓴다. */
  agency?: string | null;
  /** 예전 상태 줄(pill·결정 축). 2026-11-19부터 셸 헤더의 태그·사실 줄이 같은 값을 보인다(여기서는 그리지 않는다). */
  pills?: readonly RecordPill[];
  axes?: readonly RecordDecisionAxis[];
  menu: RecordMenuState;
  verdict: RecordVerdictActions;
  proposal: RecordProposalActions;
}

const FOLLOW_UP_REASON = "후속 기능이에요";

export function RecordHeader({ title, menu, verdict, proposal }: RecordHeaderProps) {
  const trackingItems = [
    { label: "추적 상태 변경", onClick: () => menu.onSelect("tracking") },
    {
      label: "추적 되돌리기",
      description: menu.resetBlockedReason ?? undefined,
      isDisabled: menu.resetBlockedReason !== null,
      onClick: () => menu.onSelect("reset"),
    },
    {
      label: "신호 확인",
      description: menu.signalBlockedReason ?? undefined,
      isDisabled: menu.signalBlockedReason !== null,
      onClick: () => menu.onSelect("signal"),
    },
    {
      label: "후보 연결",
      description: menu.candidateBlockedReason ?? undefined,
      isDisabled: menu.candidateBlockedReason !== null,
      onClick: () => menu.onSelect("candidate"),
    },
  ];
  const items = proposal.onProposalTab && proposal.showActions
    ? [
        ...trackingItems,
        { type: "divider" as const },
        {
          label: "제출 준비로 표시",
          description: proposal.readyBlockedReason ?? undefined,
          isDisabled: proposal.readyBlockedReason !== null,
          onClick: proposal.onReady,
        },
        { label: "HWP로 내보내기", description: FOLLOW_UP_REASON, isDisabled: true },
        { label: "버전 비교", description: FOLLOW_UP_REASON, isDisabled: true },
      ]
    : verdict.onVerdictTab
    ? [
        ...trackingItems,
        { type: "divider" as const },
        {
          label: "판정 오류 제보",
          description: verdict.feedbackBlockedReason ?? undefined,
          isDisabled: verdict.feedbackBlockedReason !== null,
          onClick: () => verdict.onVerdictMenu("verdict-feedback"),
        },
        {
          label: "실행 정보",
          description: verdict.runInfoBlockedReason ?? undefined,
          isDisabled: verdict.runInfoBlockedReason !== null,
          onClick: () => verdict.onVerdictMenu("verdict-run-info"),
        },
      ]
    : trackingItems;
  return (
    <>
      {/* 2026-11-19 최종 시안: 레코드 제목은 셸 패널 헤더의 `<h1>`이고, 상태(추적 태그·단계·마감·판정·판정 확인·최종
          Go/No-Go)는 헤더의 태그와 사실 줄이 보인다. 이 컴포넌트는 탭별 액션을 헤더 오른쪽 슬롯으로 올리고 제목은
          구역 이름으로 낭독기에만 남긴다. */}
      <h2 className="rec-title visually-hidden" data-testid="record-title">{title}</h2>
      <PageHeaderActions>
      <div className="rec-actions" data-testid="record-header">
        {proposal.onProposalTab && proposal.showActions ? (
          <>
            {/* 초안이 없거나 생성 중이면 내보낼 수 없다. 이유는 title(마우스)과 숨은 설명(낭독기) 둘 다로 준다. */}
            <span className="rec-action-hint" title={proposal.exportBlockedReason ?? undefined}>
              <Button
                aria-describedby={proposal.exportBlockedReason ? "rec-export-hint" : undefined}
                isDisabled={proposal.exportBlockedReason !== null}
                label={proposal.exportPending ? "내보내는 중…" : "PDF로 내보내기"}
                onClick={proposal.onExport}
                size="sm"
                variant="primary"
              />
              {proposal.exportBlockedReason ? (
                <span className="visually-hidden" id="rec-export-hint">{proposal.exportBlockedReason}</span>
              ) : null}
            </span>
            <span className="rec-action-hint" title={proposal.regenerateBlockedReason ?? undefined}>
              <Button
                aria-describedby={proposal.regenerateBlockedReason ? "rec-regenerate-hint" : undefined}
                isDisabled={proposal.regenerateBlockedReason !== null}
                label="다시 만들기"
                onClick={proposal.onRegenerate}
                size="sm"
                variant="secondary"
              />
              {proposal.regenerateBlockedReason ? (
                <span className="visually-hidden" id="rec-regenerate-hint">{proposal.regenerateBlockedReason}</span>
              ) : null}
            </span>
          </>
        ) : proposal.onProposalTab ? null : verdict.onVerdictTab ? (
          <>
            {/* 제안서 초안은 완료된 판정이 있을 때만 열린다. 이유는 title(마우스)과 숨은 설명(낭독기) 둘 다로 준다. */}
            <span className="rec-action-hint" title={verdict.proposalBlockedReason ?? undefined}>
              <Button
                aria-describedby={verdict.proposalBlockedReason ? "rec-proposal-hint" : undefined}
                isDisabled={verdict.proposalBlockedReason !== null}
                label="제안서 초안"
                onClick={verdict.onOpenProposal}
                size="sm"
                variant="primary"
              />
              {verdict.proposalBlockedReason ? (
                <span className="visually-hidden" id="rec-proposal-hint">{verdict.proposalBlockedReason}</span>
              ) : null}
            </span>
            <span className="rec-action-hint" title={verdict.requestBlockedReason ?? undefined}>
              <Button
                aria-describedby={verdict.requestBlockedReason ? "rec-request-hint" : undefined}
                isDisabled={verdict.requestBlockedReason !== null}
                label={verdict.requestLabel}
                onClick={verdict.onRequestVerdict}
                size="sm"
                variant="secondary"
              />
              {verdict.requestBlockedReason ? (
                <span className="visually-hidden" id="rec-request-hint">{verdict.requestBlockedReason}</span>
              ) : null}
            </span>
          </>
        ) : (
          <>
            {/* 판정 결과가 없으면 열 수 없다. 이유는 title(마우스)과 숨은 설명(낭독기) 둘 다로 준다. */}
            <span className="rec-action-hint" title={verdict.hasResult ? undefined : "아직 판정이 없어요"}>
              <Button
                aria-describedby={verdict.hasResult ? undefined : "rec-verdict-hint"}
                isDisabled={!verdict.hasResult}
                label="판정 보기"
                onClick={verdict.onOpenVerdict}
                size="sm"
                variant="primary"
              />
              {verdict.hasResult ? null : <span className="visually-hidden" id="rec-verdict-hint">아직 판정이 없어요</span>}
            </span>
            <span className="rec-action-hint" title={verdict.proposalBlockedReason ?? undefined}>
              <Button
                aria-describedby={verdict.proposalBlockedReason ? "rec-proposal-hint" : undefined}
                isDisabled={verdict.proposalBlockedReason !== null}
                label="제안서 초안"
                onClick={verdict.onOpenProposal}
                size="sm"
                variant="secondary"
              />
              {verdict.proposalBlockedReason ? (
                <span className="visually-hidden" id="rec-proposal-hint">{verdict.proposalBlockedReason}</span>
              ) : null}
            </span>
          </>
        )}
        <DropdownMenu
          alignment="end"
          button={{ icon: <Ellipsis />, isIconOnly: true, label: "사업기회 더보기", size: "sm", variant: "ghost" }}
          hasChevron={false}
          items={items}
          menuWidth={224}
        />
      </div>
      </PageHeaderActions>
    </>
  );
}
