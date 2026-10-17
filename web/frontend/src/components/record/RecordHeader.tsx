import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { Ellipsis } from "lucide-react";
import { initialOf, type RecordPill } from "../../lib/record";

/*
 * 레코드 헤더(ui-spec §3, RL-02 spec "레코드 헤더"): 기관 머리글자 아이콘(40px, teal) · 제목 ·
 * pill 4개(단계·마감·판정·추적 상태, 순서 고정) · 액션.
 *
 * 판정 보기는 서버가 준 판정 결과가 있을 때만 열린다(RL-03). 판정 탭에서는 제안서 초안(RL-04 전
 * 비활성) · 다시 판정 · ⋯가 액션이고 ⋯에 판정 오류 제보·실행 정보가 더해진다. 제안서 초안은 RL-04가
 * 열기 전까지 비활성이다. ⋯ 메뉴의 추적 항목은 기존 추적 대화상자를 여는 자리일 뿐 저장 규칙을 새로
 * 갖지 않는다.
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
  onRequestVerdict: () => void;
  /** ⋯의 판정 오류 제보·실행 정보를 막는 이유(없으면 `null`). */
  feedbackBlockedReason: string | null;
  runInfoBlockedReason: string | null;
  onVerdictMenu: (action: VerdictMenuAction) => void;
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
  agency: string | null;
  pills: readonly RecordPill[];
  menu: RecordMenuState;
  verdict: RecordVerdictActions;
}

export function RecordHeader({ title, agency, pills, menu, verdict }: RecordHeaderProps) {
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
  const items = verdict.onVerdictTab
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
    <header className="rec-header" data-testid="record-header">
      <span aria-hidden="true" className="rec-icon">{initialOf(agency)}</span>
      <div className="rec-heading">
        <h2 className="rec-title" data-testid="record-title">{title}</h2>
        <ul aria-label="사업기회 상태" className="rec-pills">
          {pills.map((pill) => (
            <li className={`rec-pill is-${pill.tone}`} data-pill={pill.key} key={pill.key}>{pill.label}</li>
          ))}
        </ul>
      </div>
      <div className="rec-actions">
        {verdict.onVerdictTab ? (
          <>
            {/* 제안서 초안은 RL-04가 열기 전까지 비활성이다. 이유는 title(마우스)과 숨은 설명(낭독기) 둘 다로 준다. */}
            <span className="rec-action-hint" title="RL-04에서 열립니다">
              <Button aria-describedby="rec-proposal-hint" isDisabled label="제안서 초안" size="sm" variant="primary" />
              <span className="visually-hidden" id="rec-proposal-hint">RL-04에서 열립니다</span>
            </span>
            <span className="rec-action-hint" title={verdict.requestBlockedReason ?? undefined}>
              <Button
                aria-describedby={verdict.requestBlockedReason ? "rec-request-hint" : undefined}
                isDisabled={verdict.requestBlockedReason !== null}
                label="다시 판정"
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
            <span className="rec-action-hint" title={verdict.hasResult ? undefined : "아직 판정이 없습니다"}>
              <Button
                aria-describedby={verdict.hasResult ? undefined : "rec-verdict-hint"}
                isDisabled={!verdict.hasResult}
                label="판정 보기"
                onClick={verdict.onOpenVerdict}
                size="sm"
                variant="primary"
              />
              {verdict.hasResult ? null : <span className="visually-hidden" id="rec-verdict-hint">아직 판정이 없습니다</span>}
            </span>
            <span className="rec-action-hint" title="RL-04에서 열립니다">
              <Button aria-describedby="rec-proposal-hint" isDisabled label="제안서 초안" size="sm" variant="secondary" />
              <span className="visually-hidden" id="rec-proposal-hint">RL-04에서 열립니다</span>
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
    </header>
  );
}
