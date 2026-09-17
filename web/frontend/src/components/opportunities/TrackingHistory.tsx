import { linkRecordLabel } from "../../lib/opportunity";
import type {
  OpportunityLinkView,
  OpportunityRecheckEventView,
  OpportunityTrackingDecisionItem,
} from "../../lib/types";
import { compareInstants, formatMoment, recheckEventLabel, stageOfLink } from "./trackingFlow";

/**
 * 추적 이력 (spec §6.3, §11.1).
 *
 * 추적 결정 revision과 재검토 신호 이벤트(`recheck_events`)를 **시간순으로 함께**
 * 보여 준다(최신이 위). 두 기록은 서버가 준 그대로이며 화면이 합치거나 지우지 않는다.
 * 확인 메모의 원문은 계약에 없으므로 메모가 있었는지만 말한다.
 */

type HistoryEntry =
  | { kind: "decision"; at: string; order: number; decision: OpportunityTrackingDecisionItem }
  | { kind: "recheck"; at: string; order: number; event: OpportunityRecheckEventView };

function externalIdOf(link: OpportunityLinkView): string {
  return link.record_external_id || link.external_id || link.evidence_external_no || "식별자 미확인";
}

function evidenceText(linkId: number | null, links: readonly OpportunityLinkView[]): string {
  if (linkId === null) return "근거 연결 미확인";
  const link = links.find((entry) => entry.id === linkId);
  if (!link) return `근거 연결 #${linkId}`;
  return `근거 ${stageOfLink(link) ?? linkRecordLabel(link)} · ${externalIdOf(link)}`;
}

export function mergeTrackingHistory(
  decisions: readonly OpportunityTrackingDecisionItem[],
  events: readonly OpportunityRecheckEventView[],
): HistoryEntry[] {
  const entries: HistoryEntry[] = [
    ...decisions.map((decision, order): HistoryEntry => ({ kind: "decision", at: decision.decided_at, order, decision })),
    ...events.map((event, order): HistoryEntry => ({ kind: "recheck", at: event.created_at, order, event })),
  ];
  // 최신이 위. 같은 시각이면 결정을 먼저 두고, 같은 종류 안에서는 서버가 준 순서를 지킨다.
  return entries.sort((left, right) => compareInstants(right.at, left.at)
    || (left.kind === right.kind ? left.order - right.order : left.kind === "decision" ? -1 : 1));
}

export interface TrackingHistoryProps {
  decisions: readonly OpportunityTrackingDecisionItem[];
  events: readonly OpportunityRecheckEventView[];
  links: readonly OpportunityLinkView[];
}

export function TrackingHistory({ decisions, events, links }: TrackingHistoryProps) {
  const entries = mergeTrackingHistory(decisions, events);
  if (entries.length === 0) return null;
  return (
    <ol aria-label="추적 이력" className="opportunity-history">
      {entries.map((entry) => entry.kind === "decision" ? (
        <li className="opportunity-history-item" data-history-kind="decision" key={`decision-${entry.decision.audit_event_id}`}>
          <p className="opportunity-history-kind">추적 결정</p>
          <div>
            <p>
              <strong>
                {entry.decision.previous_tracking_status
                  ? `${entry.decision.previous_tracking_status} → ${entry.decision.tracking_status}`
                  : entry.decision.tracking_status}
              </strong>
            </p>
            <p>{entry.decision.reason?.trim() || "선택 사유 미확인"}</p>
            <p className="opportunity-caption">
              {entry.decision.claimed_name?.trim() || "기록자 미확인"} · {formatMoment(entry.decision.decided_at)}
              {entry.decision.cleared_recheck_signal ? " · 재검토 신호 함께 해제" : ""}
            </p>
          </div>
        </li>
      ) : (
        <li
          className="opportunity-history-item"
          data-history-kind="recheck"
          key={`recheck-${entry.event.kind}-${entry.event.created_at}-${entry.order}`}
        >
          <p className="opportunity-history-kind">재검토 신호</p>
          <div>
            <p><strong>{recheckEventLabel(entry.event.kind)}</strong></p>
            <p className="opportunity-caption">
              {entry.event.actor_kind === "system" ? "시스템" : entry.event.claimed_name?.trim() || "기록자 미확인"}
              {" · "}{formatMoment(entry.event.created_at)}
              {" · "}{evidenceText(entry.event.link_id, links)}
              {entry.event.note_present ? " · 메모 있음" : ""}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
