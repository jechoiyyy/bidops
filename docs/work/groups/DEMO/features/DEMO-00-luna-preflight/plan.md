# 로컬 개발 준비와 Luna 게이트 이관 — plan

- 기능 ID: `DEMO-00-luna-preflight`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-06

기준 브랜치는 main이다(DEMO-01~05의 데모 브랜치가 아니다). 이 run은 승인된 변경을 수동 commit·merge하고 운영 배포는 하지 않는다.

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/policies/analysis-policy-luna-v4.json | 신규 | v2 기반 불변 정책, 원인 분류에 따른 프롬프트 차이 |
| web/backend/app/deep_review/services/input_versions.py | 수정 | `_approved_policy_path` v4 명시 매핑 |
| web/backend/app/deep_review/services/deep_reviews.py | 수정 | 정책 `review_timeout_seconds`로 마감, slice 1회 교정 재요청과 기록 |
| web/backend/app/deep_review/services/narrative_inputs.py, services/verification.py | 조건부 수정 | STEP-001이 입력·검증기 결함으로 분류한 경우만 |
| web/backend/tests/app/test_luna_deep_review.py | 수정 | v4 매핑·import·fake 실패 응답 회귀 |
| web/backend/tests/app/test_narrative_review.py | 수정 | 필수 검증 유지 회귀 |
| docs/validation-runs/<실행일>-luna-v4-preflight/README.md | 신규 | 원인 분류·적용·실행·판정 기록 |
| docs/validation-runs/<실행일>-luna-v4-preflight/runbook.md | 신규 | 운영 호스트에서 사용자가 실행할 단계별 명령·확인 항목 |
| docs/tracking/status.md, docs/0922_luna-deep-review/apply.md | 수정 | 실행 결과와 v4 적용 절차 |
| web/backend/app/core/config.py, model_client.py | 수정 | LiteLLM dialect·별칭 metadata·보수적 입력 상한·기존 transport 회귀 |
| web/backend/app/deep_review/policies/prespec-overview-policy-v7-litellm-v1.json | 신규 | `local-agent-main`용 별도 불변 v7 정책 |
| web/backend/app/deep_review/services/prespec_attachments.py, workers/prespec_attachment.py | 수정 | 기본 FIFO를 보존하는 선택적 notice target one-shot |
| docker-compose.model-egress.yml, .env.example, env/model.env.example | 수정 | purpose별 LiteLLM 설정 전달·예제 |
| web/backend/tests/core/test_model_client.py, tests/app/test_prespec_attachment_fetch.py, tests/deep_review/test_prespec_overview_claim_validation.py | 수정 | transport·정책·target worker 회귀 |
| docs/ARCHITECTURE.md, docs/contracts.md, docs/operations.md, docs/tracking/findings.md | 수정 | 연결·실행·문서 변환 한계 |
| docs/validation-runs/20261009-litellm-reference/, docs/work/_runs/demo00-20261007/local-readiness-evidence.md | 기존/신규 | 실제 로컬 준비 증거와 대조 기록 |

## 작업 순서

1. STEP-001 이전 실패 원인 분류 [complex]
   - 목표: v1~v3의 claim_relation_out_of_slice, considered_claim_out_of_slice, dangling_evidence를 프롬프트/입력 계약/검증기 결함으로 분류한다.
   - 작업 대상: `docs/validation-runs/20260922-luna-deep-review`, `20260923-luna-related-claims`, `20260923-luna-validation-off`, 운영 DB 원응답(읽기 전용)
   - 검증: 분류마다 근거 위치(파일·행 또는 attempt ID)를 README에 기록
2. STEP-002 v4 정책과 회귀 테스트 [complex]
   - 목표: 분류 결과만 반영한 v4 정책·고유 식별 필드·매핑, 정책 마감 읽기, slice 1회 교정 재요청을 만들고 필수 검증을 유지한다.
   - 작업 대상: 정책 파일, `input_versions.py`, 조건부 narrative/verification 코드, 두 테스트 파일
   - 검증: spec T1,T2,T3,T6,T7; 아래 명령
3. STEP-003 로컬 개발 준비 증거 판정 [complex]
   - 변경 이력: 2026-10-09에 기존 `운영 적용` 단계의 의미를 변경했다.
   - 목표: 실제 3일 수집·notice 179 문서 준비·물리 4쪽 LiteLLM 개요·두 viewport·제품 source hash를 대조하고 재사용 가능한 준비 증거와 한계를 기록한다.
   - 작업 대상: `docs/validation-runs/20261009-litellm-reference/`, `local-readiness-evidence.md`
   - 검증: spec T8,T9; 기존 모델 231건·문서 155건 증거와 source hash 대조, `unmeasured_reference`, quantity 경고, PDF 5쪽 불일치, 자동 overview/deep-review false 보존
4. STEP-004 후속 Luna 게이트 이관과 진행 판정 [standard]
   - 변경 이력: 2026-10-09에 기존 `실제 1489 1건과 판정` 단계의 의미를 변경했다.
   - 목표: 운영 1489 미실행을 보존하고 실제 Luna 심층 인수를 DEMO-03 T9와 DEMO-05 T4/T5에 명시한 뒤 DEMO-01 착수 가능 여부를 판정한다.
   - 작업 대상: 공통 기준·ADR-0070·DEMO-03/05 spec/plan·실행 기록
   - 검증: spec T4,T5; 운영 적용·새 모델 호출·정책 활성화가 없고 품질 기준이 낮아지지 않음

## 위임

| 단계 | 작업량(S/M/L) | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 실패를 프롬프트·계약·검증기로 가르는 판단 |
| STEP-002 | M | 높음 | complex | 승인 매핑·검증 불변식 |
| STEP-003 | S | 높음 | complex | 실제 증거 범위와 품질 한계 판정 |
| STEP-004 | S | 중간 | standard | 기능 간 게이트와 진행 순서 정합성 |

## 검사 명령과 증거

```sh
cd web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false python3 -m pytest tests/app/test_luna_deep_review.py tests/app/test_narrative_review.py -q
```

위 명령은 STEP-002 제품 변경 때 완료한 검사다. 2026-10-09 재계획은 제품 코드를 바꾸지 않아 앱 검사를 다시 실행하지 않는다.
`final-source-hashes.json`과 현재 8개 제품 파일이 같은 것을 확인해 기존 모델 231건·문서 155건 증거를 재사용하며 새 실행으로 표기하지 않는다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 원인이 Luna 출력 변동이라 정책으로 못 고침 | 같은 입력에서 다른 위반 code | 실패 보존, DEMO 범위(최소 3건 기준 포함) 사용자 재결정 |
| 마감 초과 | 39회 이상 × 호출당 5~6분 | v4 마감 18000초, 초과 시 기록하고 재결정 |
| 교정 재요청이 검증 완화로 변질 | 재요청 뒤 검사 생략·경고 강등 | 재요청 응답도 같은 검증, T3·T6 |
| 개요를 심층 성공으로 오인 | notice 179 completed를 Luna 보고서로 합산 | `unmeasured_reference` 보존, DEMO-03/05 실제 Luna 게이트 유지 |
| PDF text/display 불일치 | 물리 5쪽의 숨은 text가 모델 입력에 포함 | 해당 쪽 제외 유지, 후속 renderer 해결 전 전체 문서 품질 주장 금지 |
| 검증 완화로 통과 유도 | 필수 검사 off·경고 강등 | T3로 차단, 리뷰에서 diff 확인 |

## 증명

- docs: 원인 분류·로컬 준비 판정·후속 게이트·status 이력 일치.
- tests: STEP-002 Luna 검사와 T9의 기존 모델 231건·문서 155건 결과·skip·source hash 기록. 이번 문서 재계획에서 재실행하지 않음.
- postgres: N/A — 응답 shape·스키마 변경 없음(바뀌면 실행).
- frontend: N/A — 화면 변경 없음.
- api_guard: notice 179 승인 물리 4쪽과 input hash·자동화 off를 기존 실행 기록으로 확인.
- real_data_run: 로컬 준비는 T8, 실제 Luna 심층은 DEMO-03 T9와 DEMO-05 T4/T5가 소유.

## 결과

2026-10-08 기존 run `demo00-20261007`을 Codex로 재개했다. STEP-001의 원응답 미재검사 한계는 유지한다.
STEP-002는 v4 정책(`policy_identity=analysis-policy-luna-v4`), 정책 마감, 1·2단계 slice 1회 교정 재요청,
암호화 원응답 보존과 보고서 경고를 구현했다. 기존 v1~v3 정책 파일은 변경하지 않았다.
관련 두 테스트 파일의 첫 검사는 일회용 PostgreSQL 17.11 포함 68 passed, 0 skipped다.
검사 중 마지막 metadata 호환성 수정이 들어가 최종 Luna 영향 검사를 다시 수행해 32 passed, 0 skipped를 확인했다.
독립 리뷰의 검사 누락 보완 뒤 추가/변경 사례만 10 passed, 29 deselected, 0 skipped이며 제품 코드 hash는 그대로다.
gpt-5.6-sol/high 독립 리뷰는 runbook 고정 SHA 지적 수정 후 로컬 범위 PASS다.
최종 검사·독립 리뷰 근거는 `docs/work/_runs/demo00-20261007/`에 기록했다.

기존 STEP-003의 [운영 runbook](../../../../../validation-runs/20261007-luna-v4-preflight/runbook.md)은 역사로 보존한다.
2026-10-09 재계획에서 STEP-003은 [로컬 준비 증거](../../../../_runs/demo00-20261007/local-readiness-evidence.md) 판정으로,
STEP-004는 후속 Luna 게이트 이관과 진행 판정으로 의미를 바꿨다. 운영 배포·정책 import·1489 전송은 미수행 상태다.
현재 run을 수동 commit·main 통합한 뒤 DEMO-01은 별도 데모 브랜치와 새 run으로 시작한다.
