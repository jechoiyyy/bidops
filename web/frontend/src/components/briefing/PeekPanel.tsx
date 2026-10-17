import { Button } from "@astryxdesign/core/Button";
import { Link } from "react-router-dom";
import {
  changeFieldLabel,
  deadlineCell,
  deadlineDetail,
  itemSubline,
  reactionRecord,
  reasonLabel,
  safeRecordPath,
  stageLabel,
} from "../../lib/briefing";
import type { BriefingItemView, BriefingReaction } from "../../lib/types";
import { ReactionButtons } from "./ReactionButtons";

/*
 * 피크 패널(ui-spec §3·§4.1, RL-01 spec "화면 `/briefing`").
 *
 * 머리(단계 pill · D-day) · 제목 · 보조 · 반응 버튼 3개 · 반응 기록 한 줄 · 왜 추천(칩) ·
 * 자세히 보기만 그린다. **판정 블록(사유·확인할 것)·다음 행동 체크는 대응 필드가 없어 그리지
 * 않는다**(RL-03·RL-02가 채운다, 빈 블록 금지). `blocking[]`도 화면에는 그리지 않는다 —
 * 차단 조건은 Slack 메시지의 판정 줄에만 쓰인다.
 *
 * 추적 변화 행은 반응이 없으므로 버튼·반응 기록을 그리지 않고 "왜 추천" 자리에 바뀐
 * 항목을 적는다.
 */

interface PeekPanelProps {
  item: BriefingItemView;
  busy: boolean;
  onReact: (item: BriefingItemView, reaction: BriefingReaction) => void;
  onClose: () => void;
}

export function PeekPanel({ item, busy, onReact, onClose }: PeekPanelProps) {
  const deadline = deadlineCell(item);
  const recordPath = safeRecordPath(item.record_path);
  const isRecommendation = item.kind === "recommendation" && item.reaction !== null;
  return (
    <aside aria-label="선택한 공고" className="briefing-peek" data-peek-item={item.item_id}>
      <header className="briefing-peek-head">
        <span className="briefing-pill is-stage">{stageLabel(item.stage)}</span>
        {deadline.days !== null ? (
          <span className={`briefing-dday${deadline.urgent ? " is-urgent" : ""}`} data-urgent={deadline.urgent ? "true" : "false"}>
            {deadline.main}
          </span>
        ) : null}
        <Button className="briefing-peek-close" label="닫기" onClick={onClose} size="sm" variant="ghost" />
      </header>
      <h3 className="briefing-peek-title">{item.title}</h3>
      <p className="briefing-peek-sub">{itemSubline(item)} · {deadlineDetail(item)}</p>
      {isRecommendation ? (
        <>
          <ReactionButtons busy={busy} item={item} onReact={onReact} />
          <p className="briefing-peek-record" data-testid="briefing-peek-record">{reactionRecord(item)}</p>
        </>
      ) : null}
      {isRecommendation && item.reasons.length > 0 ? (
        <section aria-labelledby={`peek-why-${item.item_id}`} className="briefing-peek-block">
          <h4 id={`peek-why-${item.item_id}`}>왜 추천</h4>
          <ul className="briefing-chips">
            {item.reasons.map((reason, index) => (
              <li className="briefing-chip" key={`${reason.kind}-${index}`}>{reasonLabel(reason)}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {!isRecommendation && item.change_fields.length > 0 ? (
        <section aria-labelledby={`peek-changed-${item.item_id}`} className="briefing-peek-block">
          <h4 id={`peek-changed-${item.item_id}`}>바뀐 항목</h4>
          <ul className="briefing-chips">
            {item.change_fields.map((field) => (
              <li className="briefing-chip" key={field}>{changeFieldLabel(field)}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {recordPath ? (
        <Link className="briefing-peek-link" to={recordPath}>자세히 보기</Link>
      ) : null}
    </aside>
  );
}
