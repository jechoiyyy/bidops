import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { Ellipsis } from "lucide-react";
import { initialOf, type RecordPill } from "../../lib/record";

/*
 * 레코드 헤더(ui-spec §3, RL-02 spec "레코드 헤더"): 기관 머리글자 아이콘(40px, teal) · 제목 ·
 * pill 4개(단계·마감·판정·추적 상태, 순서 고정) · 액션.
 *
 * 판정 보기·제안서 초안은 RL-03·RL-04가 열기 전까지 비활성이다. ⋯ 메뉴는 기존 추적
 * 대화상자를 여는 자리일 뿐 저장 규칙을 새로 갖지 않는다.
 */

export type RecordMenuAction = "tracking" | "reset" | "signal" | "candidate";

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
}

export function RecordHeader({ title, agency, pills, menu }: RecordHeaderProps) {
  const items = [
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
        {/* 후속 기능이 열기 전까지 비활성이다. 이유는 title(마우스)과 숨은 설명(낭독기) 둘 다로 준다. */}
        <span className="rec-action-hint" title="RL-03에서 열립니다">
          <Button aria-describedby="rec-verdict-hint" isDisabled label="판정 보기" size="sm" variant="primary" />
          <span className="visually-hidden" id="rec-verdict-hint">RL-03에서 열립니다</span>
        </span>
        <span className="rec-action-hint" title="RL-04에서 열립니다">
          <Button aria-describedby="rec-proposal-hint" isDisabled label="제안서 초안" size="sm" variant="secondary" />
          <span className="visually-hidden" id="rec-proposal-hint">RL-04에서 열립니다</span>
        </span>
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
