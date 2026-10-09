# 로컬 개발 준비와 Luna 게이트 이관 — spec

- 기능 ID: `DEMO-00-luna-preflight`
- 근거: [intent.md](./intent.md)
- 작성일: 2026-10-06

## 큰 틀 문서와의 관계

- 인용하는 절: [ADR-0069](../../../../../tracking/decisions/0069-user-requested-luna-deep-review.md) 승인 기반 Luna,
  [0922 Luna 적용 절차](../../../../../0922_luna-deep-review/apply.md), [ADR-0070 개정](../../../../../tracking/decisions/0070-multi-company-knowledge-demo.md),
  [공통 계약 §5](../../../../demo-contract.md)의 "v4 기반 demo 정책" 문장.
- 기존 v4 정책 기준과 검증은 STEP-002 완료 계약으로 유지한다.
- 2026-10-09에 새로 확정하는 항목: 로컬 준비 완료 조건과 운영 1489·실제 Luna 인수 게이트의 DEMO-03/05 이관.

## 입력·출력 계약

- 정책 파일 `web/backend/app/deep_review/policies/analysis-policy-luna-v4.json`: schema `bidops.analysis-policy.v2`, `model_endpoint_ref=codex-exec`,
  모델·effort는 v2와 같다(`gpt-5.6-luna`/xhigh). 검증은 v2와 같이 켠다(`result_checks`를 끄지 않음).
- v4는 STEP-001 원인 분류에 근거한 차이만 가진다. 최소한 `considered_claim_ids`는 입력 `verified_claims`에서만 고르고(없으면 `[]`)
  출력 로컬 ID와 역할이 다르다는 규칙을 프롬프트에 둔다. dangling evidence의 원인이 프롬프트면 프롬프트로, 입력·검증기 결함이면 코드로 고친다.
- 필수 근거 FK·인용·숫자·coverage 검사를 경고로 낮추거나 끄지 않는다. 선택적 related_claim 경고 규칙(v2)은 유지할 수 있다.
- 승인 경로 매핑 `_approved_policy_path`는 지금 정책 내용(`validation.result_checks`·`related_claim_policy`)으로 v1~v3를 고르므로,
  v2 검증을 유지하는 v4는 그대로면 v2 파일로 매핑돼 "승인되지 않은 analysis policy"로 거부된다.
  v4에는 v1~v3에 없는 고유 식별 필드 `policy_identity:"analysis-policy-luna-v4"`를 두고 매핑이 이 필드를 v1~v3 판별보다 먼저 검사한다.
  모르는 `policy_identity`는 내용 기반 판별로 낮추지 않고 거부한다. 기존 v1~v3 파일·매핑·DB 행은 바꾸지 않는다.
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

## 2026-10-09 로컬 준비 계약

- 상세 transport·metadata·용량·불변 정책·target worker 계약은 [LiteLLM 참조 실행 계획](../../../../../validation-runs/20261009-litellm-reference/plan.md)을 이 spec의 실행 근거로 포함한다.
- `bidops-local`의 2026-10-06~08 KST 실제 수집 범위와 건수를 후속 corpus의 출처로 확인한다. 정확한 6건의 정규 run ID·source hash는 DEMO-05 manifest에서 동결한다.
- notice 179의 native ARM 문서 준비(80쪽 immutable snapshot)와 물리 4쪽만 승인한 LiteLLM `local-agent-main` 개요를 준비 증거로 쓴다.
- 개요는 2 calls, 8 claims, 결정적 인용·offset 검증 통과, `quality_status=unmeasured_reference`와 quantity 경고 4종 보존이어야 한다.
- 물리 5쪽 text/display 불일치와 80쪽 전체 시각 검증 미수행을 미해결 한계로 남긴다.
- 제품 source hash가 증거의 `final-source-hashes.json`과 같아야 기존 231개 모델 검사와 155개 문서 검사를 재사용할 수 있다. 재실행한 검사로 기록하지 않는다.
- 이 계약은 overview 준비만 증명한다. 실제 Luna 심층은 DEMO-03 T9와 DEMO-05 T4/T5를 통과해야 한다.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID | UUID | 운영 현재값 | v4 import 결과 | `env/luna.env`. 실행 뒤 유지 여부는 사용자 결정 |
| BIDOPS_LUNA_DEEP_REVIEW_ENABLED | bool | false | 실행 창에서만 true | 실행 뒤 false로 되돌린다 |
| BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED | bool | false | false 고정 | 바꾸지 않는다 |
| BIDOPS_VLLM_OVERVIEW_API_DIALECT | enum | vllm | 로컬 참조에서 litellm | overview purpose만; Luna와 분리 |
| BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH | path | 기존 v7 | `prespec-overview-policy-v7-litellm-v1.json` | 명시 선택, 기존 v7/v8 불변 |
| overview model_name | string | policy 값 | `local-agent-main` | `/models`·`/model/info`로 별칭·입력 상한 확인 |
| execution.review_timeout_seconds | 초 | v1~v3 7200 | v4 18000 | 코드가 정책 값을 읽는다 |
| execution.validation_repair_attempts | int | 0(키 없음) | v4 1 | slice당 교정 재요청 상한 |

## 상태 값과 실패 처리

- 로컬 준비 통과: 위 수집·문서·개요·화면·source hash 증거가 일치하고 남은 한계와 후속 Luna 게이트가 기록돼 있다.
- 운영 1489: 미실행 상태를 보존한다. 로컬 준비 통과가 운영 적용이나 실제 Luna 품질 통과로 바꾸지 않는다.
- 기능 완료(done)는 기존 STEP-001/002 이력, 로컬 준비 판정, 후속 게이트 이관이 함께 기록됐을 때다.

## 저장

기존 STEP-002의 Luna 정책 파일과 제품 변경은 그대로다. 현재 batch의 LiteLLM transport·불변 개요 정책·target attachment worker 변경도 main 통합 범위다.
이번 재계획 자체는 제품 코드를 더 바꾸지 않으며 DB schema·migration은 없다. 실제 로컬 DB의 실패·완료 행은 덮어쓰지 않았다.

## 인터페이스(CLI·UI·API)

기존 Luna에는 새 인터페이스가 없다. 로컬 준비 변경은 설정 dialect `litellm`, 명시적인 개요 policy path,
attachment worker의 선택 인자 `--notice-id`를 추가한다. 기본 FIFO·lease/fence/retry와 기존 vLLM/Ollama 기본값은 유지한다.
개요·Luna 외부 호출은 각각 자기 policy·purpose 설정과 승인 경계를 쓰며 fallback하거나 key를 공유하지 않는다.

## 결정과 이유

| 결정 | 근거 | 적용하지 않는 대안 |
|---|---|---|
| main 통합·운영 미배포 | v4와 LiteLLM 준비 변경을 후속 데모 기준선으로 사용 | 운영 배포를 DEMO-01 선행조건으로 유지 |
| 1489 후속 이관 | 로컬 준비는 갖췄지만 LiteLLM 개요가 Luna 심층을 증명하지 않음 | 미실행 1489를 완료 처리 |
| 그래프 입력 제외 | 실패 원인을 Luna 정책·검증 경계로 좁힌다 | demo 정책 바로 실행 |
| 검증 유지 | ADR-0070: 검증 off 정책은 완성 보고서 인수에 쓰지 않는다 | v3 계승 |
| 마감을 정책 값으로 | 1489는 오류가 없어도 7200초 안에 끝날 수 없음(STEP-001) | 고정값 유지·추론 강도 하향 |
| slice 1회 교정 재요청 | 한 보고서 39회 이상 호출이라 드문 근거 ID 오류도 전체 실패로 이어짐(2026-10-07 사용자) | 프롬프트 자기 점검만·위험 수용 |
| 실제 Luna는 DEMO-03/05에서 검증 | 회사·graph 입력이 완성된 최종 경로를 직접 인수 | 단일회사 운영 1489를 계속 전체 구현 blocker로 둠 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | v4 정책 canonical bytes·매핑 | v4는 고유 식별 필드로 v4 파일에 매핑·import 성공·sha 고정, 식별 필드 없는 v2 내용 변형은 v2 파일로 매핑돼 거부, v1~v3 매핑·행 불변 | 단위 |
| T2 | 이전 실패 응답 재현(fake) | v1/v2/v3 실패 응답 형태를 fake로 넣었을 때 v4 경로의 처리(거부 또는 통과)가 원인 분류와 일치 | 회귀 |
| T3 | 필수 검증 유지 | dangling evidence·out-of-slice 참조는 여전히 실패, 검증 off 경로 없음 | 회귀 |
| T4 | 후속 게이트 이관 | DEMO-03 T9와 DEMO-05 T4/T5에 실제 Luna 인수가 남고 자동 시작 false 유지 | 문서 계약 |
| T5 | 운영 1489 상태 보존 | 운영 적용·attempt·판정이 미완료로 기록되고 로컬 개요와 합산되지 않음 | 문서 계약 |
| T6 | 교정 재요청(fake) | 첫 응답 dangling → 재요청 1회 → 통과, 재요청도 실패 → failed, slice당 최대 1회, v1~v3는 재요청 0, 원응답 2개 보존·경고 기록 | 회귀 |
| T7 | 정책 마감 | v1~v3는 7200, v4는 18000을 LunaClient deadline에 전달 | 단위 |
| T8 | 로컬 준비 증거 | 3일 corpus·notice 179 문서·물리 4쪽 개요·두 viewport·source hash 일치, `unmeasured_reference`와 PDF 5쪽 한계 보존 | 실제 자료/문서 |
| T9 | LiteLLM·target worker 제품 변경 | metadata 별칭/용량/권한/redirect·기존 dialect 회귀, immutable policy, target queue 격리·default FIFO·invalid id, native ARM 문서 경계 | 단위/통합 |
