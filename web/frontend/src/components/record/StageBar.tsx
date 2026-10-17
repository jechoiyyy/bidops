import { Check } from "lucide-react";
import { formatKstDay, stageLabelAt, STAGE_STATE_LABEL } from "../../lib/record";
import type { OpportunityStageEntry } from "../../lib/types";

/*
 * 단계 바(ui-spec §3, RL-02 spec "단계 바"): 발주계획·사전규격·입찰공고·마감·개찰·계약 6단계.
 *
 * 상태는 서버가 판정한 값이다. 완료=✓ 채움, 현재=채움+링, 다가오는 마감=warning 테두리,
 * 대기·미확인=회색 테두리. `unknown`은 라벨 뒤에 `미확인`을 글자로 적는다(건너뛴 단계나
 * 데이터가 없는 단계를 추정해 채우지 않는다). 색만으로 말하지 않도록 상태 이름을 글자로 함께
 * 둔다(미확인 외에는 화면 낭독기용 숨은 글자).
 */
export function StageBar({ stages }: { stages: readonly OpportunityStageEntry[] }) {
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
            <span className="rec-stage-label">
              {label}
              {stage.state === "unknown"
                ? <span className="rec-stage-unknown"> 미확인</span>
                : <span className="visually-hidden"> · {STAGE_STATE_LABEL[stage.state]}</span>}
            </span>
            {day ? <span className="rec-stage-day">{day}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
