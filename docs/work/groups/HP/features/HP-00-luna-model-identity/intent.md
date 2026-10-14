# codex-exec 모델 identity 전환 (gpt-6-luna / high) — intent

- 기능 ID: `HP-00-luna-model-identity`
- 상위 항목: [HP 로드맵](../../../../constitution/roadmap.md), [HP 공통 계약](../../../../hp-contract.md) §0
- 크기: M — backend·runner·frontend·정책 파일·테스트 20여 곳을 바꾸지만 새 REST 계약은 없다. 실제 모델 호출(smoke)은 건별 승인 대상이다.
- 작성일: 2026-10-14

## 문제

codex-exec 경로는 모델 `gpt-5.6-luna`, reasoning `xhigh`, CLI `0.155.1`을 runner 상수, client 상수, 서비스 상수, pydantic Literal, 정책 파일, 프런트 문자열·fixture 등 20여 곳에 복제해 고정하고 있다.
사용자는 2026-10-14에 HP의 모든 호출을 `gpt-6-luna`·`high`로 바꾸기로 했고 Terra는 취소했다. 정책 파일은 불변이므로 새 정책을 발행해야 하며, 문자열 복제를 그대로 두면 다음 전환 때 같은 일을 반복한다.

## 기대 결과

runner가 `codex exec --model gpt-6-luna -c model_reasoning_effort="high"`를 실행하고, 새 정책 `analysis-policy-luna-hp-v1`로 만든 preview·승인·attempt·감사 기록과 화면이 `gpt-6-luna · high · codex-exec`를 보이며, 그 값은 고정된 정책 row와 identity 모듈 한 곳에서 나온다.
기존 `gpt-5.6-luna` 정책·row는 그대로 조회된다. 격리 스택의 runner 이미지는 사용자가 다시 빌드하고, 첫 실제 호출은 건별 승인 뒤 한 번만 한다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| runner 인수 | `pytest tests/deep_review/test_codex_runner.py` | argv에 `--model gpt-6-luna`, `model_reasoning_effort="high"`; `CLI_VERSION == 0.162.1`이 backend identity와 같다 |
| client identity 검사 | 같은 테스트의 MockTransport | runner가 `cli_version=0.162.1`을 주면 성공, `0.155.1`이면 `runner_identity_mismatch` |
| 정책 발행·import | `python -m app.deep_review.cli import-profile-policy --policy <hp-v1 또는 v5 파일> --actor <name> --label <identity>` | row `model_name=gpt-6-luna`, canonical bytes = 파일 bytes, demo-v1·v4 import도 여전히 성공 |
| 회사 preview | `POST /api/companies/{id}/pre-specs/{notice}/deep-review-previews`(DEMO 계약 §9) with `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=<hp-v1 row>` | 응답 `model=gpt-6-luna`, `reasoning_effort=high`; 같은 요청을 demo-v1 row로 하면 503 `model_binding_invalid` |
| attempt·감사 | 승인 뒤 attempt view·AuditEvent safe_metadata | `model`·`reasoning_effort`·`cli_version`이 정책 row·identity에서 온 값; legacy attempt(gpt-5.6-luna)도 그대로 조회 |
| 가정 분석 | `POST /api/notices/{id}/assumption-analysis/previews` 응답 `input.scenario.settings` | `model=gpt-6-luna`, `reasoning_effort=high`; legacy settings가 저장된 run은 worker가 호출 없이 종결 |
| 화면 | Playwright `luna-deep-review.spec.ts`·`company-review.spec.ts` | 승인 상자에 `gpt-6-luna · high · codex-exec` |
| legacy 정책 fail-closed | v4(gpt-5.6-luna) 정책으로 일반 preview / legacy 정책에 고정된 승인 attempt를 worker가 claim / v5 정책으로 일반 preview | 503 `model_binding_invalid` / runner 호출 0·attempt failed `model_binding_invalid` / 200 (기존 일반 경로 유지) |
| 격리 스택 overlay | `docker compose … -f docker-compose.hp-local.yml config` | codex-runner image가 `BIDOPS_DEMO_CODEX_RUNNER_IMAGE` 값으로 렌더됨 |
| 격리 스택 smoke(수동, 건별 승인) | runner 이미지 재빌드 → `codex --version`=0.162.1 → 승인된 preview 1건 실행 | attempt `invocation_metadata.model=gpt-6-luna`; 승인이 없으면 proof는 pending |

## 선행·후속 기능

- 선행: 없음.
- 후속: HP-03-two-tier-analysis(새 파이프라인 정책 `analysis-policy-hp-v1`이 이 identity를 상속).

## 영향 범위

- 모듈·컴포넌트: `web/codex-runner/{runner.py,Dockerfile}`, `web/backend/app/deep_review/services/{luna_identity.py(신규),luna_client.py,luna_inputs.py,company_deep_review.py,deep_reviews.py,input_versions.py,assumption_inputs.py,assumption_analysis.py}`, `web/backend/app/deep_review/schemas/deep_reviews.py`(및 회사 preview DTO), `web/backend/app/deep_review/policies/analysis-policy-luna-hp-v1.json`(신규), 프런트 `companyApi.ts`·`assumption-analysis/Request.tsx`·테스트 fixture 3종·spec 2종.
- 큰 틀 문서의 절: HP 공통 계약 §0, contracts.md ADR-0069 절(model/reasoning_effort 문장), DEMO 계약 §9 한 줄(HP identity 참조).
- 데이터·저장소: `AnalysisPolicyVersion`에 새 row(import). 기존 row·migration 변경 없음.
- 외부 서비스·호출: smoke 1건(사용자 건별 승인). 그 외 없음.

## 제약

- (공통) 원문·프로필·정책·모델 입력과 결과·사람 리뷰는 불변/append-only로 보존한다.
- (공통) unknown/null·적합성·참여 준비·추적·Go/No-Go를 서로 대신하지 않는다.
- (공통) 외부 모델은 승인 payload만 건별 전송하며 전역 fallback과 자동 추적 결정을 금지한다.
- (공통) PostgreSQL 17·versioned MinIO·합성 analysis worker의 슬롯 1개와 모듈 의존 방향을 유지한다.
- (공통) 문서 변경은 diff/문서 검사만, 제품 변경은 직접 영향 검사만 실행하고 성공 후 반복하지 않는다.
- (공통) 운영 변경·실제 모델 호출은 직전 확인 대상이며 문서화 승인을 실행 승인으로 사용하지 않는다.
- (공통) HP 기능은 데모 브랜치 demo/local-20261009와 bidops-local 격리 자원에서만 구현·검증하며 main 병합·운영 전환은 별도 작업이다(ADR-0071).
- (공통) HP의 모델 호출은 codex-exec gpt-6-luna/high 하나다. LiteLLM local-agent-main·Qwen·Terra를 쓰지 않고, 기존 정책 파일·실행 row는 바꾸지 않는다(ADR-0071).
- (공통) HWP/HWPX 원본이 입력 정본이며 PDF는 PDF 전용 첨부와 쪽 locator에만 쓴다. OCR은 범위 밖이다(ADR-0071).
- (공통) 새 DB 테이블·열 권한은 scripts/runtime-privileges.sql에 등록하고 migration에 GRANT를 쓰지 않는다.
- (공통) 사용자 요청 없이 commit·merge·push·브랜치 삭제하지 않는다.
- (기능별) 정책 파일은 version+sha256 불변이다. 기존 v1~v4·demo-v1 파일의 bytes를 바꾸지 않는다. runner는 요청에서 모델을 받지 않고 상수로만 실행한다(수동적 경계 유지).
- 기준 출처/hash: [source-baseline](../../../../source-baseline.json). 실행용 복사: [feature.json](../../../../feature.json)의 constraints/constraint_sources.

## 범위 밖

- 새 파이프라인·정책 `analysis-policy-hp-v1`(HP-03). Terra·LiteLLM 경로 변경(폐기, 코드 삭제는 하지 않음). 운영 스택 배포. 운영 1489 가정 분석의 재실행.
- v1~v4·demo-v1 정책으로의 새 실행(정책 모델 불일치로 `model_binding_invalid` fail-closed). NULL 계보는 함께 발행하는 `analysis-policy-luna-v5`(v4 + identity 키)로만 실행하며, 이 정책의 전역 활성화는 격리 스택 테스트 범위이고 운영 활성화는 별도 작업이다.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| CLI 버전 | runner·client·정책 `0.155.1` | 호스트 codex `0.162.1`이 gpt-6 계열과 함께 SDLC 도구에서 검증됨 | `0.162.1`로 올린다(`tunable`, 사용자 미지정) |
| 표식의 출처 | 코드 상수 복제 | 공통 계약 §0: 정책 row·identity 모듈에서 읽는다 | identity 모듈 신설, 조회는 정책 row 우선 |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 격리 스택 smoke 실행 승인 | 구현 중(STEP-006 직전) | 사용자 건별 승인. 승인 없으면 proof pending으로 남기고 HP-03 대표 1건에서 함께 확인 |
