import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  BellRing,
  ClipboardList,
  FileSearch,
  FileText,
  Gavel,
  Link2,
  ListChecks,
  Megaphone,
  PencilLine,
  Sparkles,
  StickyNote,
} from "lucide-react";
import { activityDateTimeAttr, activityTimeLabel, initialOf, safeActivityLink, splitActor } from "../../lib/record";
import type { OpportunityActivityItem } from "../../lib/types";

/*
 * 활동 항목 한 줄(ui-spec §3 `ActivityItem`): 26px 원형 아이콘(사람이면 머리글자) · 본문(이름 600 ·
 * 상태 pill 인라인) · 보조 줄(시각 · 링크). 날짜 묶음 머리는 없고 시각에 `오늘`·날짜를 적는다.
 *
 * 제목·보조 설명·링크는 서버가 파생한 값이다. 시각은 분 단위까지만 보이며 초는 쓰지 않는다
 * (관측 시각은 회차 생성 시각이라 초 단위를 사람 행동처럼 보이게 하지 않는다).
 */

const KIND_ICON: Record<string, ReactNode> = {
  order_plan_found: <ClipboardList />,
  pre_spec_opened: <FileSearch />,
  bid_posted: <Megaphone />,
  notice_corrected: <PencilLine />,
  recheck_signal: <BellRing />,
  link_reviewed: <Link2 />,
  note_added: <StickyNote />,
  action_added: <ListChecks />,
  action_done: <ListChecks />,
  verdict_completed: <Gavel />,
  draft_prepared: <Sparkles />,
};

export function ActivityItem({ item, now }: { item: OpportunityActivityItem; now: Date }) {
  const link = safeActivityLink(item.link);
  const { lead, rest } = splitActor(item.title, item.actor, item.kind);
  const person = item.actor?.trim() ? item.actor.trim() : null;
  return (
    <li className="rec-activity" data-item-id={item.item_id} data-kind={item.kind}>
      {person ? (
        <span aria-hidden="true" className="rec-activity-mark is-person" title={person}>{initialOf(person)}</span>
      ) : (
        <span aria-hidden="true" className="rec-activity-mark">{KIND_ICON[item.kind] ?? <FileText />}</span>
      )}
      <div className="rec-activity-body">
        <p className="rec-activity-title">
          {lead ? <strong>{lead}</strong> : null}
          {rest}
          {item.status_pill ? <span className="rec-activity-pill">{item.status_pill}</span> : null}
        </p>
        {item.detail ? <p className="rec-activity-detail">{item.detail}</p> : null}
        <p className="rec-activity-meta">
          <time dateTime={activityDateTimeAttr(item.at) ?? undefined}>{activityTimeLabel(item.at, now)}</time>
          {link ? (
            <>
              <span aria-hidden="true"> · </span>
              {link.kind === "internal" ? (
                <Link className="rec-activity-link" to={link.to}>{link.label}</Link>
              ) : (
                <a className="rec-activity-link" href={link.href} rel="noopener noreferrer" target="_blank">{link.label}</a>
              )}
            </>
          ) : null}
        </p>
      </div>
    </li>
  );
}
