/**
 * 화면 문구의 용어 사전.
 *
 * 이 화면을 쓰는 사람은 기획·사업개발 담당자다. 개발자가 계약·구현에서 쓰던
 * 낱말(`attempt`, `revision`, `bundle`, `snapshot`, `digest`, `binding`,
 * `locator`, `projection`, `manifest`, `append-only`…)이 화면 문자열에 그대로
 * 남아 있었고, 같은 개념이 화면마다 다른 낱말로 나왔다. 이 표가 정본이며,
 * 새 문구를 쓸 때 여기 있는 낱말을 쓴다.
 *
 * **바꾸지 않는 것.**
 *
 * - 목록·필터는 한글 라벨로 표시한다. 계약 토큰은 상세의 기술 정보에서만 표시한다.
 *   번역은 표시만 바꾸며 서버 값과 unknown·null의 의미는 보존한다.
 * - 식별자와 해시 값 자체(문서 버전 ID, SHA-256, request ID). 사람이 눈으로
 *   대조하는 값이므로 **줄이지 않는다.** 실무 화면에서 운영 화면이나 같은 화면의
 *   접힌 기술 정보로 **옮길 수는 있다**(ADR-0066 결정 2). 옮길 때도 값을 자르지
 *   않으며, 그 값을 가리키는 **이름**만 이 표의 낱말로 바꾼다(`digest` → `식별 해시`).
 * - 이미 라벨 맵이 있는 업무 상태(`BUNDLE_STATUS_LABELS`,
 *   `PRE_SPEC_*_LABEL`, `QUALITY_STATUS_LABEL` …). 그 맵이 그 도메인의 정본이다.
 */
export const TERM = {
  /** `attempt`. 한 검토·비교를 다시 실행한 한 번. 수집 회차(run)와 다른 축이다. */
  attempt: "분석 회차",
  /** `revision`. 덮어쓰지 않고 새로 쌓는 기록 한 벌. */
  revision: "수정본",
  /** `bundle`. 심층 검토 입력이 되는 문서 한 묶음. */
  bundle: "문서 묶음",
  /** `snapshot`. 분석이 고정해 두고 쓰는 입력. */
  snapshot: "고정 입력",
  /** 문맥이 "그 시점에 복사해 둔 것"일 때 쓰는 `snapshot`의 다른 이름. */
  snapshotCopy: "저장 시점 사본",
  /** `digest`. 담당자가 눈으로 대조하는 짧은 해시 값. */
  digest: "식별 해시",
  /** `binding`. 실행에 묶인 모델·정책·프로필 조합. */
  binding: "모델 연결",
  /** `locator`. 근거가 가리키는 원문의 자리. */
  locator: "원문 위치",
  /** `claimed name`. 감사 표식일 뿐 인증이 아니다. */
  claimedName: "담당자 이름",
  /** `workspace`. 한 사업기회의 비교를 모아 둔 화면. */
  workspace: "작업 화면",
  /** `projection`. 서버가 여러 원본에서 만들어 둔 읽기용 요약. */
  projection: "요약 정보",
  /** `append-only`. 짧게 쓸 때. */
  appendOnly: "추가만 기록",
  /** `append-only`를 한 문장으로 풀 때. 덮어쓰지 않는다는 사실이 핵심이다. */
  appendOnlyNote: "추가만 기록하며 덮어쓰지 않습니다.",
  /** `manifest`. 문서 안 구간을 훑는 목록. */
  manifest: "목록",
  /** `validation`. 서버가 돌린 결정적 검증. */
  validation: "검증",
  /** `currentness`. 저장된 결정이 지금도 유효한지. */
  currentness: "최신 여부",
  /** `fence`. 저장 요청이 어떤 값에 묶여 나가는지. */
  fence: "저장 조건",
  /** `evidence`. 원문에서 끌어온 근거. */
  evidence: "근거",
} as const;

export type GlossaryTerm = keyof typeof TERM;

/**
 * 발주계획 실무 화면의 계약 값 → 한글 라벨(ADR-0066 결정 3, 0921 명세 §3.1).
 *
 * **표시만 바꾼다.** URL 질의 값과 서버로 보내는 값은 아래 key 그대로이며,
 * `unknown`·`null`의 의미도 그대로다. 표에 없는 값(서버가 새 enum을 준 경우)은
 * 바꾸거나 숨기지 않고 원문을 그대로 통과시킨다(`orderPlanLabel`).
 */
export const ORDER_PLAN_RELEVANCE_LABEL = {
  relevant: "관련",
  uncertain: "판단 보류",
  not_relevant: "비관련",
} as const;

/** 1차 선별(`stage1_status`). 배지로 그릴지는 화면이 정한다(선정·제외는 그리지 않는다). */
export const ORDER_PLAN_STAGE1_LABEL = {
  selected: "선정",
  filtered_out: "제외",
  failed: "실패",
  rejected: "거부",
} as const;

/**
 * 모델 처리 상태(`stage2_status`). 미판정·실패·거부·미확인을 하나로 뭉개지 않는다 —
 * 모델 판단이 없는 이유가 서로 다르기 때문이다.
 */
export const ORDER_PLAN_STAGE2_LABEL = {
  not_attempted: "모델 미판정",
  success: "모델 판정 완료",
  failed: "모델 판정 실패",
  rejected: "모델 응답 거부",
  unknown: "모델 상태 미확인",
} as const;

/** 사람 판단 수정의 우선순위. 값이 없는 것(`null`)은 `미지정`이며 여기 넣지 않는다. */
export const ORDER_PLAN_PRIORITY_LABEL = {
  high: "높음",
  medium: "보통",
  low: "낮음",
} as const;

/** 서버가 값을 주지 않은 축(`null` 토큰)의 필터 라벨. `미확인`·`계산 불가`와 다르다. */
export const ORDER_PLAN_NULL_LABEL = "값 없음";

/** 추적 축의 `none`. 소유 사업기회를 확인하지 못한 행이며 `미선택`이 아니다. */
export const ORDER_PLAN_TRACKING_NONE_LABEL = "사업기회 미연결";

/** 표에 있는 값만 옮기고 모르는 값은 원문 그대로 보인다(ADR-0066 결정 3). */
export function orderPlanLabel(labels: Readonly<Record<string, string>>, value: string): string {
  return labels[value] ?? value;
}
