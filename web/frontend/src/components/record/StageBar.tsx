import { Check } from "lucide-react";
import { Link } from "react-router-dom";
import { recordRoute } from "../opportunities/trackingFlow";
import { formatKstDay, stageLabelAt, STAGE_STATE_LABEL } from "../../lib/record";
import type { OpportunityLinkView, OpportunityStageEntry } from "../../lib/types";

/*
 * 단계 바(ui-spec §3, RL-02 spec "단계 바"): 발주계획·사전규격·입찰공고·마감·개찰·계약 6단계.
 *
 * 상태는 서버가 판정한 값이다. 완료=✓ 채움, 현재=채움+링, 다가오는 마감=warning 테두리,
 * 대기·미확인=회색 테두리. `unknown`은 라벨 뒤에 `미확인`을 글자로 적는다(건너뛴 단계나
 * 데이터가 없는 단계를 추정해 채우지 않는다). 색만으로 말하지 않도록 상태 이름을 글자로 함께
 * 둔다(미확인 외에는 화면 낭독기용 숨은 글자).
 */
/**
 * 단계 칸은 그 단계의 대표 권위 연결(`link_id`, 서버가 고른다)이 상세 `links`에 있으면 원천 화면
 * 링크가 된다(설계고도화안 C-3). 대상 화면은 추적 흐름과 같은 `recordRoute`가 정하며, 연결이 없는
 * 단계(마감 이후·계약·미연결)는 글자로 남는다.
 */
export function StageBar({ stages, links = [] }: { stages: readonly OpportunityStageEntry[]; links?: readonly OpportunityLinkView[] }) {
  const byId = new Map(links.map((link) => [link.id, link] as const));
  return (
    <ol aria-label="사업 단계" className="rec-stagebar" data-testid="stage-bar">
      {stages.map((stage, index) => {
        const label = stageLabelAt(index, stage);
        const day = stage.state === "pending" || stage.state === "unknown" ? null : formatKstDay(stage.at);
        return (
          <li className="rec-stage" data-state={stage.state} data-stage={label} key={`${index}-${stage.key}`}>
            <span aria-hidden="true" className="rec-stage-marker">
              {stage.state === "done" ? <Check strokeWidth={3} /> : null}
            </span>
            {(() => {
              const content = (
                <>
                  {label}
                  {stage.state === "unknown"
                    ? <span className="rec-stage-unknown"> 미확인</span>
                    : <span className="visually-hidden"> · {STAGE_STATE_LABEL[stage.state]}</span>}
                </>
              );
              // 발주계획·사전규격·입찰공고 세 칸만 연결을 대표한다. 마감·개찰은 입찰공고 대표를 따르므로
              // 같은 화면을 두 번 걸지 않도록 앞 세 칸에서만 링크를 만든다.
              const link = index < 3 && stage.link_id !== null ? byId.get(stage.link_id) ?? null : null;
              const to = link ? recordRoute(link) : null;
              return to
                ? <Link className="rec-stage-label rec-stage-link" title={`${label} 열기`} to={to}>{content}</Link>
                : <span className="rec-stage-label">{content}</span>;
            })()}
            {day ? <span className="rec-stage-day">{day}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
