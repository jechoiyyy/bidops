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
 * 한 뜻에 한 낱말(설계고도화안 C-6, 2026-11-19).
 *
 * 같은 낱말이 화면마다 다른 뜻으로 쓰였다. 아래 표가 뜻마다 낱말 하나를 정하고, 화면은
 * 이 상수를 읽는다. **계약·DB 값은 그대로다** — 여기서 고르는 것은 화면 문구뿐이며,
 * `business-rules.md`·계약 문서가 이미 쓰는 낱말을 따른다.
 *
 * "다음 행동"(세 뜻):
 * - `nextActionGuide` 서버가 정한 탐색용 안내(사전규격·공고 판정의 `next_action`). 새 업무 상태가
 *   아니다. business-rules "사전규격 C-1 기본 대상"의 "다음 행동 안내".
 * - `nextActionNote` 사람이 레코드에 남기는 할 일 메모(`opportunity_note kind=action`). 활동 피드
 *   제목 `다음 행동: …`은 서버가 만든다(contracts/lifecycle-rest.md) — 그래서 이 뜻이 맨 낱말을 갖는다.
 * - `verdictNextAction` RL 판정 종합이 제안한 행동(모델 행 + 코드 "사람 확인" 행). contracts/rl.md의
 *   "종합 다음 행동".
 *
 * "보류"(뜻마다 다른 낱말):
 * - `trackingHold` 추적 결정 값 `보류` 하나에만 맨 낱말을 쓴다(business-rules 생애주기 표).
 * - `judgmentWithheld` 판단을 내지 않았다 — 사전규격 등급 `held`, 회사 핏 `unknown`, 사람 판단
 *   relevance `uncertain`, 리뷰 증거 판단(business-rules가 모두 "판단 보류"로 적는다).
 * - `modelUncertain` 발주계획 모델 판단 `uncertain`. 목록 탭 이름(`불확실`)과 같다.
 * - `gateIncomplete` 품질 게이트 결과 `보류`(측정이 끝나지 않음). 미달이 아니다.
 * - 최종 Go/No-Go에는 보류 값이 없다. 결정을 미루려면 저장하지 않는다.
 */
export const TERM_SENSE = {
  nextActionGuide: "다음 행동 안내",
  nextActionNote: "다음 행동",
  verdictNextAction: "종합 다음 행동",
  trackingHold: "보류",
  judgmentWithheld: "판단 보류",
  modelUncertain: "불확실",
  gateIncomplete: "측정 미완",
} as const;

/**
 * 사전규격 업무 보기와 다음 행동 안내의 낱말(2026-11-19 사전규격 단계 수정안 §3 B).
 *
 * - `actionable` 검토할 항목: 추적 결정 없음 ∧ 개요 `완료`·`사람 확인 필요`. 사람이 개요를 읽고
 *   추적을 정한다.
 * - `needsCheck` 확인 필요: 추적 결정 없음 ∧ 개요가 결과 없이 끝났거나(실패·취소) 문서 준비가
 *   사람 없이는 끝나지 않는다(준비 중단·초안·준비된 문서 없음). 개요 상태 `사람 확인 필요`
 *   (`needs_human_review`)와 다른 뜻이다 — 그쪽은 `개요 확인 필요`다.
 * - 다음 행동 안내 `review_overview`는 `개요 확인`, `confirm_overview`는 `개요 확인 필요`다.
 *   추적 결정은 추적만 정하며 분석 실행 승인이 아니다.
 */
export const PRE_SPEC_TERM = {
  actionable: "검토할 항목",
  needsCheck: "확인 필요",
  reviewOverview: "개요 확인",
  confirmOverview: "개요 확인 필요",
} as const;

/**
 * 사람이 내리는 결정 축(business-rules "적합성 등급·참여 준비 상태·추적 선택·최종 Go/No-Go를
 * 서로 대신하지 않는다", 설계고도화안 §3 "추적 시작, 판정 확인, Go/No-Go는 사람이 결정한다").
 * 레코드 헤더의 결정 축 요약 줄이 이 이름을 쓰며, 축을 한 상태로 합치지 않는다.
 */
export const DECISION_AXIS_LABEL = {
  tracking: "추적 결정",
  verdictConfirmation: "판정 확인",
  goNoGo: "최종 Go/No-Go",
} as const;

/**
 * 품질 게이트 결과(`result_status`) → 화면 낱말. 값 `보류`는 측정이 끝나지 않았다는 뜻이라
 * 추적 결정 `보류`와 다른 낱말로 보인다(C-6). 표에 없는 값은 그대로 통과시킨다.
 */
export const GATE_RESULT_LABEL: Readonly<Record<string, string>> = {
  통과: "통과",
  미달: "미달",
  미측정: "미측정",
  보류: TERM_SENSE.gateIncomplete,
};

export function gateResultLabel(value: string): string {
  return GATE_RESULT_LABEL[value] ?? value;
}

/**
 * 발주계획 실무 화면의 계약 값 → 한글 라벨(ADR-0066 결정 3, 0921 명세 §3.1).
 *
 * **표시만 바꾼다.** URL 질의 값과 서버로 보내는 값은 아래 key 그대로이며,
 * `unknown`·`null`의 의미도 그대로다. 표에 없는 값(서버가 새 enum을 준 경우)은
 * 바꾸거나 숨기지 않고 원문을 그대로 통과시킨다(`orderPlanLabel`).
 */
export const ORDER_PLAN_RELEVANCE_LABEL = {
  relevant: "관련",
  /* C-6: 모델 `uncertain`은 목록 탭 이름과 같은 `불확실`이다. 추적 결정 `보류`와 낱말을 나눈다. */
  uncertain: TERM_SENSE.modelUncertain,
  not_relevant: "비관련",
} as const;

/**
 * 사람 판단 수정의 관련성(`human_feedback.relevance`). 같은 machine 값이지만 business-rules가
 * 사람 feedback을 `관련|비관련|판단보류`로 적으므로 `uncertain`은 `판단 보류`다(C-6에서 리더 확인 대상으로 보고).
 */
export const ORDER_PLAN_FEEDBACK_RELEVANCE_LABEL = {
  relevant: "관련",
  uncertain: TERM_SENSE.judgmentWithheld,
  not_relevant: "비관련",
} as const;

/** 1차 선별(`stage1_status`). 배지로 그릴지는 화면이 정한다(선정·제외는 그리지 않는다). */
export const ORDER_PLAN_STAGE1_LABEL = {
  selected: "선정",
  /* 2026-11-18 수정안 3B: 모델 판정 범위(BM25 상위 N건) 밖이라는 뜻을 그대로 말한다. 값(`filtered_out`)은 그대로다. */
  filtered_out: "순위 밖",
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

/**
 * 발주계획 검토의 세 단(2026-11-18 수정안 3B). **화면 문구만 나눈다** — 실행 계약의
 * `human_review_count`(관련 + 불확실 + 무판정)와 게이트의 검토 후보 규칙은 그대로다.
 *
 * - 필수 검토: 모델 판단 `관련`.
 * - 훑어보기: 모델 판단 `불확실`(판단 보류).
 * - 모델 미판정: 모델이 판정하지 않은 건. 두 갈래다 — 순위 밖(1차 선별 `filtered_out`, 모델 판정
 *   범위 밖)과 판정 실패(1차 선별·모델 판정의 실패·거부). 옛 용어 `1차 선별 제외`·`선별 실패`의 자리다.
 */
export const ORDER_PLAN_REVIEW_TIER_LABEL = {
  relevant: "필수 검토",
  uncertain: "훑어보기",
} as const;

export const ORDER_PLAN_UNJUDGED_LABEL = "모델 미판정";

export const ORDER_PLAN_UNJUDGED_KIND_LABEL = {
  out_of_rank: "순위 밖",
  judgment_failed: "판정 실패",
} as const;

/**
 * 일일 실행 요약의 검토 건수 한 줄. 서버 집계(`stage2_relevant_count`·`stage2_uncertain_count`)와
 * 그 차이로 얻은 무판정 몫(`lib/orderPlanDaily.ts`의 `noJudgmentCount`)을 그대로 적는다.
 * 무판정 몫은 0보다 클 때만 붙인다. 그 몫은 실패·거부·미확인뿐이고 `순위 밖`이 들지 않으므로
 * `모델 미판정`(순위 밖 포함 탭 이름)이 아니라 `판정 실패`로 부른다.
 */
export function orderPlanReviewTierSummary(
  relevantCount: number,
  uncertainCount: number,
  unjudgedCount: number | null,
  format: (value: number) => string,
): string {
  const parts = [
    `${ORDER_PLAN_REVIEW_TIER_LABEL.relevant} ${format(relevantCount)}건(관련)`,
    `${ORDER_PLAN_REVIEW_TIER_LABEL.uncertain} ${format(uncertainCount)}건(불확실)`,
  ];
  if (unjudgedCount !== null && unjudgedCount > 0) parts.push(`${ORDER_PLAN_UNJUDGED_KIND_LABEL.judgment_failed} ${format(unjudgedCount)}건`);
  return parts.join(" · ");
}

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
