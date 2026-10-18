import { Tab, TabList } from "@astryxdesign/core/TabList";
import {
  SECTION_KEYS,
  findSection,
  sectionConfirmCount,
  sectionLabel,
  sectionStatusLabel,
} from "../../lib/proposal";
import type { ProposalDraft, ProposalSectionKey } from "../../lib/types";

/*
 * 절 탭 6개(ui-spec §4.5). 요구사항 수행방안 탭에만 확인 건수 pill(빈 자리 + 제안 수치)을 붙인다.
 * 아직 본문이 없거나 실패한 절은 탭 이름 뒤에 상태를 글자로 함께 적는다(색만으로 말하지 않는다).
 */

export const SECTION_PANEL_ID = "pp-section-panel";

interface SectionTabsProps {
  draft: ProposalDraft;
  value: ProposalSectionKey;
  onChange: (key: ProposalSectionKey) => void;
}

export function SectionTabs({ draft, value, onChange }: SectionTabsProps) {
  return (
    <TabList
      className="pp-section-tabs"
      onChange={(next) => onChange(next as ProposalSectionKey)}
      role="tablist"
      size="sm"
      value={value}
    >
      {SECTION_KEYS.map((key) => {
        const section = findSection(draft, key);
        const confirmCount = key === "requirements" ? sectionConfirmCount(section) : 0;
        const status = section?.status ?? null;
        const needsMark = status === "failed" || status === "queued" || status === "running";
        return (
          <Tab
            endContent={
              confirmCount > 0 || needsMark ? (
                <span className="pp-tab-end">
                  {needsMark && status ? <span className="pp-tab-status" data-status={status}>{sectionStatusLabel(status)}</span> : null}
                  {confirmCount > 0 ? (
                    <span className="pp-tab-count" data-testid="requirements-confirm-count">{confirmCount}</span>
                  ) : null}
                </span>
              ) : undefined
            }
            id={`pp-tab-${key}`}
            key={key}
            label={sectionLabel(key)}
            panelId={SECTION_PANEL_ID}
            value={key}
          />
        );
      })}
    </TabList>
  );
}
