# Luna v4 정책 선검증 — spec

- 기능 ID: `DEMO-00-luna-preflight`
- 근거: [intent.md](./intent.md)
- 작성일: 2026-10-06

## 큰 틀 문서와의 관계

- 인용하는 절: [ADR-0069](../../../../../tracking/decisions/0069-user-requested-luna-deep-review.md) 승인 기반 Luna,
  [0922 Luna 적용 절차](../../../../../0922_luna-deep-review/apply.md), [ADR-0070 개정](../../../../../tracking/decisions/0070-multi-company-knowledge-demo.md),
  [공통 계약 §5](../../../../demo-contract.md)의 "v4 기반 demo 정책" 문장.
- 이 문서에서 새로 확정하는 항목: v4 정책의 기준(v2 정상 검증 유지), 판정 기준, 운영 적용 순서.
- 큰 틀 문서 수정이 필요한 항목: 실행 뒤 [status](../../../../../tracking/status.md)의 Luna 현황 문장과 0922 apply 후속 절.

## 입력·출력 계약

- 정책 파일 `web/backend/app/deep_review/policies/analysis-policy-luna-v4.json`: schema `bidops.analysis-policy.v2`, `model_endpoint_ref=codex-exec`,
  모델·effort는 v2와 같다(`gpt-5.6-luna`/xhigh). 검증은 v2와 같이 켠다(`result_checks`를 끄지 않음).
- v4는 STEP-001 원인 분류에 근거한 차이만 가진다. 최소한 `considered_claim_ids`는 입력 `verified_claims`에서만 고르고(없으면 `[]`)
  출력 로컬 ID와 역할이 다르다는 규칙을 프롬프트에 둔다. dangling evidence의 원인이 프롬프트면 프롬프트로, 입력·검증기 결함이면 코드로 고친다.
- 필수 근거 FK·인용·숫자·coverage 검사를 경고로 낮추거나 끄지 않는다. 선택적 related_claim 경고 규칙(v2)은 유지할 수 있다.
- 승인 경로 매핑 `_approved_policy_path`는 지금 정책 내용(`validation.result_checks`·`related_claim_policy`)으로 v1~v3를 고르므로,
  v2 검증을 유지하는 v4는 그대로면 v2 파일로 매핑돼 "승인되지 않은 analysis policy"로 거부된다.
  v4에는 v1~v3에 없는 고유 식별 필드(예: `policy_label`)를 두고 매핑이 그 필드를 v1~v3 판별보다 먼저 검사한다.
  필드 이름은 STEP-002에서 정해 이 spec과 공통 계약 §5에 적고 T1로 고정한다. 기존 v1~v3 파일·매핑·DB 행은 바꾸지 않는다.
- 검토 마감(2026-10-07 결정): 코드가 정책 `execution.review_timeout_seconds`를 읽어 검토 전체 마감으로 쓴다(지금은 `deep_reviews.py:1584`에 7200 고정).
  v1~v3 정책은 값이 7200이라 동작이 바뀌지 않는다. v4는 18000(5시간)이다. 1489는 원문 단위 19개라 최소 39회 호출(약 3.5시간)이다.
- 교정 재요청(2026-10-07 결정): 1·2단계 slice 응답이 결정적 검증(형식·근거 FK·필수 검사)에서 실패하면 같은 slice에 한해 1회,
  같은 동결 입력에 실패 code와 위치 요약(원문·응답 본문 없이 ID·필드 이름)만 붙여 다시 요청한다. 정책 키 `execution.validation_repair_attempts`
  (v4=1, 키가 없는 v1~v3=0). 재요청 응답도 같은 검증을 거치고 다시 실패하면 기존대로 실패로 끝난다. 검증 자체는 끄거나 낮추지 않는다.
  두 응답의 원문을 모두 암호화 보존하고 호출 기록·보고서 경고에 재요청 사실을 남긴다. 새 자료를 보내지 않으므로 기존 건별 승인 범위 안이다.
  ADR-0069의 '자동 재호출 없음'에 대한 이 한 가지 예외는 ADR-0070 개정에 기록한다. transport 재시도 규칙은 그대로다.
- 판정 기록 `docs/validation-runs/<실행일>-luna-v4-preflight/README.md`:
  {policy_sha256, policy_version_id, notice_id:1489, preview_id, input_sha256, review_id, attempt_id, 종료 상태, 실패 code|null,
  slice 수/처리 slice 수, slice별 소요 시간, 총 소요 시간, 검증 요약, 사용자 판정}. 원응답·secret·원문은 쓰지 않는다.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID | UUID | 운영 현재값 | v4 import 결과 | `env/luna.env`. 실행 뒤 유지 여부는 사용자 결정 |
| BIDOPS_LUNA_DEEP_REVIEW_ENABLED | bool | false | 실행 창에서만 true | 실행 뒤 false로 되돌린다 |
| BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED | bool | false | false 고정 | 바꾸지 않는다 |
| execution.review_timeout_seconds | 초 | v1~v3 7200 | v4 18000 | 코드가 정책 값을 읽는다 |
| execution.validation_repair_attempts | int | 0(키 없음) | v4 1 | slice당 교정 재요청 상한 |

## 상태 값과 실패 처리

- 통과: 1489 attempt가 completed이고 현재 보고서가 v2 수준 검증을 통과했다.
- 실패: 그 외 종료(교정 재요청 뒤에도 검증 실패·마감 초과·runner 오류). 실패 code와 진행 slice, 교정 재요청 횟수를 기록하고 원응답을 보존한다.
  교정 재요청 1회 외의 자동 재호출은 없다.
- 기능 완료(done)는 통과/실패와 무관하게 판정 기록과 사용자 결정(진행 또는 범위 재결정)이 남았을 때다. 실패를 통과로 바꾸지 않는다.

## 저장

정책 파일 1개(신규), 운영 DB AnalysisPolicyVersion 행 1개(append-only), 1489 DeepReview attempt와 보고서/검증 기록(기존 테이블).
migration 없음.

## 인터페이스(CLI·UI·API)

새 인터페이스 없음. 기존 `import-profile-policy` CLI, 사전규격 상세의 전송 미리보기·승인 화면(`LunaRequest`), 기존 report GET을 쓴다.
외부 호출은 기존 Luna 승인 gate(미리보기 hash·사람 승인·공용 슬롯)가 막는다.

## 결정과 이유

| 결정 | 근거 | 적용하지 않는 대안 |
|---|---|---|
| main·운영 배포 | 승인 정책은 이미지 파일과 코드 매핑으로만 인정됨(`input_versions.py:696-724`), 격리 스택은 로컬 LLM 엔드포인트 전이라 개요를 못 만듦 | 격리 스택 선검증(엔드포인트 대기로 지연) |
| 1489 재사용 | 이전 실패 3회와 같은 입력이라 원인 비교가 가능하고 문서 준비·개요가 이미 있음 | 새 공고 |
| 그래프 입력 제외 | 실패 원인을 Luna 정책·검증 경계로 좁힌다 | demo 정책 바로 실행 |
| 검증 유지 | ADR-0070: 검증 off 정책은 완성 보고서 인수에 쓰지 않는다 | v3 계승 |
| 마감을 정책 값으로 | 1489는 오류가 없어도 7200초 안에 끝날 수 없음(STEP-001) | 고정값 유지·추론 강도 하향 |
| slice 1회 교정 재요청 | 한 보고서 39회 이상 호출이라 드문 근거 ID 오류도 전체 실패로 이어짐(2026-10-07 사용자) | 프롬프트 자기 점검만·위험 수용 |
| 운영 단계는 운영 호스트에서 사용자가 실행 | 이 작업 장비에 운영 스택이 없음(2026-10-07 사용자) | 원격 접속·별도 세션 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | v4 정책 canonical bytes·매핑 | v4는 고유 식별 필드로 v4 파일에 매핑·import 성공·sha 고정, 식별 필드 없는 v2 내용 변형은 v2 파일로 매핑돼 거부, v1~v3 매핑·행 불변 | 단위 |
| T2 | 이전 실패 응답 재현(fake) | v1/v2/v3 실패 응답 형태를 fake로 넣었을 때 v4 경로의 처리(거부 또는 통과)가 원인 분류와 일치 | 회귀 |
| T3 | 필수 검증 유지 | dangling evidence·out-of-slice 참조는 여전히 실패, 검증 off 경로 없음 | 회귀 |
| T4 | 운영 적용 | 컨테이너 env에 v4 ID·Luna 토글 렌더 확인, 자동 시작 false 유지 | 운영 확인 |
| T5 | 실제 1489 1건 | 사람 승인 1회·attempt 1개·판정 기록 완성 | 실제 모델 |
| T6 | 교정 재요청(fake) | 첫 응답 dangling → 재요청 1회 → 통과, 재요청도 실패 → failed, slice당 최대 1회, v1~v3는 재요청 0, 원응답 2개 보존·경고 기록 | 회귀 |
| T7 | 정책 마감 | v1~v3는 7200, v4는 18000을 LunaClient deadline에 전달 | 단위 |
