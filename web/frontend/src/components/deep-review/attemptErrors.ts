/**
 * 실패한 분석 회차·단계에 붙는 안전 코드의 사람 말 문장.
 *
 * 서버가 정한 안전 코드를 화면이 코드 그대로 내보이던 자리(`안전한 오류 코드:
 * model_timeout`)를 사람 말 한 문장으로 바꾼다(ADR-0065 결정 1 `조건부`,
 * `docs/0921_practitioner-screens/spec.md` §3.2). **코드는 사라지지 않고** 같은
 * 자리의 접힌 `기술 정보`에 전문 그대로 남는다.
 *
 * **여기 있는 코드만 문장으로 바꾼다.** 목록은 이 화면의 응답
 * (`attempt.last_error_code`·`stage.last_error_code`)에 실제로 실리는 값에서
 * 왔다 — 워커가 실패를 기록하는 자리
 * (`web/backend/app/deep_review/services/deep_reviews.py:1355` `_fail_claim`,
 * 호출부 `:1619`·`:1622`·`:1625`)와 그 코드를 만드는 모델 client
 * (`web/backend/app/core/model_client.py`)다. 모르는 코드는 바꾸거나 숨기지
 * 않고 문장 안에 그대로 보인다(`web/frontend/AGENTS.md`, ADR-0065 결정 3).
 *
 * 문장은 어느 것도 실패를 성공·완료·변경 없음으로 읽히게 하지 않는다.
 */
export const ATTEMPT_ERROR_SENTENCES: Record<string, string> = {
  // 워커가 직접 기록하는 코드.
  validation_failed:
    "모델 결과가 결정적 검증을 통과하지 못해 분석을 마치지 못했습니다. 화면이 실패를 보정하지 않습니다.",
  processing_failed: "분석 실행이 실패해 결과가 만들어지지 않았습니다.",
  service_unavailable: "분석에 필요한 서비스를 사용할 수 없어 분석을 마치지 못했습니다.",
  // 모델 호출이 분류한 실패(`model_client.py:1187-1199`).
  timeout: "모델 응답이 제한 시간 안에 오지 않아 분석을 마치지 못했습니다.",
  // 같은 뜻으로 저장된 값이 응답에 실려 온다(`tests/api-mock.ts`의 회차 fixture).
  model_timeout: "모델 응답이 제한 시간 안에 오지 않아 분석을 마치지 못했습니다.",
  response_too_large: "모델 응답이 허용 크기를 넘어 분석을 마치지 못했습니다.",
  provider_http_error: "모델 서버가 오류를 돌려주어 분석을 마치지 못했습니다.",
  provider_unavailable: "모델 서버에 연결하지 못해 분석을 마치지 못했습니다.",
  truncated_json: "모델 응답이 끝까지 오지 않아 분석을 마치지 못했습니다.",
  malformed_json: "모델 응답을 약속된 형식으로 읽지 못해 분석을 마치지 못했습니다.",
  provider_error: "모델 호출이 실패해 분석을 마치지 못했습니다.",
  // 모델 신원·설정 확인이 막은 실패(`model_client.py:860-967`, `:1109`·`:1116`).
  identity_unavailable: "분석 모델의 신원을 확인하지 못해 분석을 멈췄습니다.",
  model_not_served: "승인된 분석 모델이 서버에 올라와 있지 않아 분석을 멈췄습니다.",
  model_revision_invalid: "서버가 알린 모델 판이 승인된 값과 달라 분석을 멈췄습니다.",
  generation_config_mismatch: "서버의 생성 설정이 승인된 값과 달라 분석을 멈췄습니다.",
  // 호출 전에 fail closed로 막힌 경우(`model_client.py:676`·`:1072`-`:1085`).
  input_capacity_exceeded: "입력이 모델이 한 번에 받을 수 있는 크기를 넘어 분석을 마치지 못했습니다.",
  model_not_allowed: "승인되지 않은 모델이라 호출하지 않고 멈췄습니다.",
  policy_invalid: "분석 정책 설정이 올바르지 않아 호출하지 않고 멈췄습니다.",
  correction_invalid: "재시도 지시가 올바르지 않아 호출하지 않고 멈췄습니다.",
};

/** 사람 말 문장. 사전에 없는 코드는 코드를 문장 안에 그대로 싣는다. */
export function attemptFailureSentence(code: string): string {
  return ATTEMPT_ERROR_SENTENCES[code] ?? `분석을 마치지 못했습니다 · 코드 ${code}`;
}
