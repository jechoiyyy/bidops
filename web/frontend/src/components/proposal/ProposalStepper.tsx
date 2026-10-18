import { Check } from "lucide-react";
import { STAGE_STEPS, STEP_STATE_LABEL, stepState } from "../../lib/proposal";
import type { ProposalStage } from "../../lib/types";

/*
 * 좌측 세로 stepper(ui-spec §4.5): 목차 · 초안 · 검토 완료 · 제출 준비.
 *
 * 단계는 서버 `stage`를 그대로 읽는다(생성 시 toc → 첫 절 완료 시 draft → 6절 검토 완료 시 reviewed →
 * 사람이 표시하면 ready). 완료는 ✓ 채움, 현재는 채움 + 링, 대기는 회색 테두리이며 색만으로 말하지 않도록
 * 단계 이름 뒤에 상태 글자를 숨은 설명으로 함께 둔다.
 */

export function ProposalStepper({ stage }: { stage: ProposalStage }) {
  return (
    <ol aria-label="초안 단계" className="pp-stepper" data-stage={stage}>
      {STAGE_STEPS.map((step, index) => {
        const state = stepState(stage, index);
        return (
          <li
            aria-current={state === "current" ? "step" : undefined}
            className="pp-step"
            data-state={state}
            data-step={step.stage}
            key={step.stage}
          >
            <span aria-hidden="true" className="pp-step-marker">
              {state === "done" ? <Check /> : null}
            </span>
            <span className="pp-step-label">{step.label}</span>
            <span className="visually-hidden"> · {STEP_STATE_LABEL[state]}</span>
          </li>
        );
      })}
    </ol>
  );
}
