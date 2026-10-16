# 토큰 계측과 로컬 LLM 최적화 검토 — plan

- 기능 ID: `RL-06-local-llm-optimization`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-16

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/codex-runner/runner.py, web/backend/tests/deep_review/test_codex_runner.py | 수정 | usage 파싱·응답 키 2개(T0) |
| web/backend/app/deep_review/services/luna_client.py | 수정 | InvocationResult 토큰 채움 |
| web/backend/app/deep_review/models.py, alembic/versions/<head 다음>_stage_usage.py | 수정/신규 | 열 6개 |
| docs/experiments/ (디렉터리 신설) | 신규 | 보고서 |
| web/backend/app/deep_review/services/card_analysis.py, proposal_draft.py | 수정 | usage 저장 |
| web/backend/app/deep_review/cli/usage_report.py, cli/__init__.py | 신규/수정 | 보고 CLI |
| web/backend/tests/deep_review/test_usage_report.py, tests/app/test_stage_usage_postgres.py | 신규 | T1~T4 |
| docs/experiments/<날짜>-local-llm-token-optimization.md | 신규 | 보고서 |
| docs/contracts.md, deep-review-erd.md, operations.md, ADR.md | 수정 | STEP-004 |

## 작업 순서

1. STEP-001 runner 토큰 응답·계측 열·저장 [complex]
   - 목표: runner가 codex JSONL usage를 읽어 응답 키 2개를 더하고(contract 불변), `luna_client`가 채우며, 열 6개 migration과 stage/절 저장(null 보존·repair 분리).
   - 작업 대상: runner.py, test_codex_runner.py, luna_client.py, models.py, migration, card_analysis.py, proposal_draft.py.
   - 검증: T0, T1, T4(PG).
2. STEP-002 usage-report CLI [complex]
   - 목표: 집계 계약(기간·null·p90·cap·상위 50)·JSON/MD 출력.
   - 작업 대상: usage_report.py.
   - 검증: T2, T3.
3. STEP-003 실제 보고·실험 보고서 [standard]
   - 목표: bidops-local 기간 1회 보고, 보고서 5절 작성(실험 미실행 명시).
   - 작업 대상: docs/experiments.
   - 검증: T5.
4. STEP-004 문서 [standard]
   - 목표: contracts·erd·operations·ADR.
   - 검증: `doctor _`.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | runner 파싱(버전 의존)·identity 불변·repair 분리 |
| STEP-002 | M | 높음 | complex | 집계 경계·null 규칙·p90 |
| STEP-003 | S | 중간 | standard | 보고서 양식 닫힘 |
| STEP-004 | S | 낮음 | standard | 문서 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 보고서를 실험 결과로 오독 | "결론: 전환" 문장 | "실험 미실행·제안만" 명시 |
| null을 0으로 합산 | 합계가 호출 수와 어긋남 | `unmeasured_calls` 분리, T2 |
| 로컬 모델 호출 유혹 | runner 외 endpoint | 범위 밖·제약 |
| codex CLI 버전마다 usage 이벤트가 다름 | 토큰 null 급증 | 이벤트 이름을 cli_version별로 고정, 모르면 null(`unmeasured_calls`) |

## 증명

- docs: `doctor _`.
- tests: `pytest tests/deep_review/test_usage_report.py tests/deep_review/test_codex_runner.py`.
- postgres: `test_stage_usage_postgres.py`·`test_db_migrations.py`·`test_runtime_database_privileges.py`.
- frontend·api_guard·real_data_run: 비적용(화면·외부 호출·모델 실행 없음; T5는 읽기 보고).

## 결과

구현 후 작성한다.
