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
 * - 서버 계약의 enum 토큰(`relevant`, `filtered_out`, `needs_human_review`,
 *   `passed`, `pending`, `completed`, `go`, `no_go` …). 값 자체가 계약이므로
 *   번역해서 표시하면 화면이 서버 상태를 재정의하는 것이 된다. 한국어 설명을
 *   덧붙이는 것은 되지만(`CALCULATION_LABELS` 같은 라벨 맵) 토큰을 지우지 않는다.
 * - 식별자와 해시 값 자체(문서 버전 ID, SHA-256, request ID). 사람이 눈으로
 *   대조하는 값이므로 줄이거나 옮기지 않는다. 옮기는 것은 그 값을 가리키는
 *   **이름**뿐이다(`digest` → `식별 해시`).
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
