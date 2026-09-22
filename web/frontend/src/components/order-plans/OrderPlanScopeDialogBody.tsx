import { Text } from "@astryxdesign/core/Text";
import type { OrderPlanListScope } from "../../lib/types";
import { scopeLabel } from "./orderPlanDialogShared";

/**
 * `이 목록의 기준` 다이얼로그 본문.
 *
 * 실행 요약 줄(실행 식별자·상태·모델 연결 허용 여부)과 회차 식별자 전문은 운영 화면의
 * `발주계획 선별` 탭으로 옮겼다(0921 명세 §3.1·§4). 여기 남는 것은 **무엇을 보고 있고
 * 무엇이 아닌지**를 말하는 문장이다 — 강제 게이트 문장(모델 판단 ≠ 추적 선택·적합성
 * 등급·참여 준비·최종 Go/No-Go)과 값들이 서로 바뀌지 않는다는 구분이 그대로 남는다.
 */
export function OrderPlanScopeDialogBody({
  isCumulative,
  listScope,
  runLabel,
}: {
  isCumulative: boolean;
  listScope: OrderPlanListScope | null | undefined;
  runLabel: string | null;
}) {
  return (
    <div className="c2l-dialog-body">
      <Text type="body" color="secondary" as="p">
        {isCumulative
          ? "1차 선별 신호와 모델 판단 신호를 분리해, 운영 실행 결과를 발주계획마다 최신 1건씩 누적해 검토합니다."
          : "1차 선별 신호와 모델 판단 신호를 분리해 선택한 회차의 완료된 실행을 검토합니다."} 모델 판단은 추적 선택·적합성 등급·참여 준비·최종 Go/No-Go가 아닙니다.
      </Text>
      <Text type="supporting" color="secondary" as="p">
        <b>1차 선별 제외</b>는 1차 선별에서 빠진 것, <b>비관련</b>은 모델 판단, <b>모델 상태 미확인</b>은 정보 부족,
        {" "}<b>값 없음</b>은 판정이 없거나 적용되지 않은 것이며 서로 바꾸지 않습니다.
      </Text>
      {/* 기본 화면의 결정 줄에서 뺀 문장. 뜻은 그대로 남기고 자리만 옮겼다. */}
      <Text type="supporting" color="secondary" as="p">
        미선택은 추적 종료가 아닙니다. 추적 선택은 추적 상태만 기록하며 모델 판단·적합성 등급·참여 준비 상태·최종 Go/No-Go를 바꾸지 않습니다.
      </Text>
      {listScope !== undefined ? (
        <Text type="supporting" color="secondary" as="p">목록 범위 · {scopeLabel(listScope, runLabel)}</Text>
      ) : null}
    </div>
  );
}
