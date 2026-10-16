# 토큰 계측과 로컬 LLM 최적화 검토 — spec

- 기능 ID: `RL-06-local-llm-optimization`
- 근거: [intent.md](./intent.md), RL-03 spec(`card_analysis_stage`), RL-04 spec(`proposal_section` 토큰 열), codex-runner 응답 필드(`prompt_tokens`·`output_tokens`·`latency_ms`), HP 계약 §10(실험 보고서 형식 선례)
- 작성일: 2026-10-16 (같은 날 독립 검사 1차 17건 반영)

## 큰 틀 문서와의 관계

- 인용하는 절: contracts.md "심층 검토 내부 artifact", deep-review-erd.md, HP 계약 §10(가설→기준→명령→결과→판단), RL-05 spec(품질 기준).
- 새로 확정: 계측 열·저장 규칙, usage-report 출력 계약, 보고서 구조·채택 기준.
- 큰 틀 문서 수정(STEP-004): contracts.md·deep-review-erd.md 열 3개·CLI, operations.md 보고 명령, ADR.md 한 줄.

## 입력·출력 계약

### 토큰 수의 출처 (runner 변경)

- 현재 codex-runner는 `status·raw_response·cli_version·input_sha256·latency_ms`만 돌려주고 codex `--json` stdout을 버린다. `luna_client`는 토큰 자리를 항상 `None`으로 채운다. 그래서 이 기능이 **runner를 바꾼다**: `codex exec --json`의 stdout JSONL에서 usage 이벤트(`input_tokens`·`output_tokens`; codex CLI 0.162 이벤트 이름은 구현 때 고정하고 버전이 다르면 null)를 읽어 응답에 `prompt_tokens`·`output_tokens`(int|null)를 **추가**한다. 응답 키 추가형이며 contract·schema·모델 identity(HP-00)는 바꾸지 않는다. `luna_client.InvocationResult`가 두 값을 채우고, 테스트 가짜 runner에 토큰 있는/없는 응답을 둔다. intent "범위 밖"의 "runner contract 변경"은 **contract(schema allowlist) 변경 금지**를 뜻하며 응답 키 추가는 허용한다.

### 계측 열

- `card_analysis_stage`에 `prompt_tokens INT NULL`, `output_tokens INT NULL`, `latency_ms INT NULL`, `repair_prompt_tokens INT NULL`, `repair_output_tokens INT NULL`, `repair_latency_ms INT NULL` 추가(열 6개). `latency_ms`는 최종 성공 호출, `repair_*`는 repair 호출(없으면 null). 값은 runner 응답 그대로, 없으면 null(0 보정 금지). 저장은 stage INSERT 시 1회(append-only 유지).
- `proposal_section`(RL-04)의 `prompt_tokens`·`output_tokens`·`latency_ms`는 RL-04의 INSERT 후 1회 UPDATE 허용 열이며 repair는 분리하지 않는다(절당 repair ≤ 1, 합산 저장). RL-04 권한 절의 UPDATE 허용 열에 이 세 열이 포함돼야 한다(RL-04 spec에 기재됨).
- 실패 호출의 출처: deep_review(card-v1)는 stage 행이 없으므로 attempt의 `error_code`·`invocation_metadata`(기존 관측 JSON) 에서 센다; proposal은 `proposal_section.status='failed'`·`error_code`.

### `usage-report` CLI

- `python -m app.deep_review.cli usage-report --from YYYY-MM-DD --to YYYY-MM-DD [--purpose deep_review|proposal|all] --out <dir> [--json-only]`. 기간: 각 행의 `created_at`(stage)·`created_at`(section)을 Asia/Seoul로 바꾼 시각이 `[from 00:00:00, to+1일 00:00:00)`. 모집단: `deep_review` = `pipeline_version=card-v1` attempt의 `card_analysis_stage`(legacy narrative·회사 핏 제외), `proposal` = `proposal_section`. exit: 성공 0, 모든 오류 2 + stdout `{"error": code}`(기존 CLI 관례). 성공 stdout = `{"out_dir", "files": ["usage.json","usage.md"], "sha256": {file: sha}}`.
- `usage.json` = `{schema_version:"bidops.usage-report.v1", from, to, generated_at, purposes:[{purpose, calls:int, failed_calls:int, failed_by_code:{code:int}, prompt_tokens_sum:int, output_tokens_sum:int, unmeasured_calls:int, latency_ms:{median:int|null, p90:int|null}, by_stage:[{stage, calls, prompt_tokens_sum, output_tokens_sum, prompt_tokens_median:int|null, latency_ms_median:int|null, failed_calls, failed_by_code}], by_day:[{date, calls, units:int, unit_kind: attempts|drafts, cap:int|null, cap_reached:bool}], by_notice:[{notice_id, title, calls, prompt_tokens_sum, output_tokens_sum, attempts:int}]}]}`.
  - 호출 1건 = stage 행 1개(+repair가 있으면 repair도 1건으로 세고 `stage` 뒤에 `:repair`), proposal은 section 행 1개. `compare`처럼 호출이 없는 stage는 `by_stage`에서 생략. stage enum: deep_review `extract|role|synthesis`(+`:repair`), proposal = 절 key 6개.
  - `unmeasured_calls` = `prompt_tokens`·`output_tokens` 중 하나라도 null인 호출; 그 호출은 두 합계 모두에서 뺀다.
  - 중앙값·p90: null 제외, 오름차순 정렬, 중앙값은 하위 중간값(`sorted[(n-1)//2]`), p90은 nearest-rank `sorted[ceil(0.9·n)-1]`, n=0 → null.
  - `by_day.units`는 deep_review면 그날 `approved_at` 기준 attempt 수(`unit_kind=attempts`), proposal이면 draft 수(`drafts`); `cap`은 그날 KST 23:59:59 시점에 활성인 용도별 `transfer_policy_approval.daily_cap`(없으면 null); `cap_reached = units >= cap`(cap null이면 false).
  - `by_notice`는 토큰 합 내림차순 상위 50, `title`은 공고 제목(허용 필드).
- `usage.md` = 같은 내용의 표(단계별·일별·상위 공고 10). 금지(T3): prompt 원문 조각, 회사 사실 value 문자열, `raw_response`, 토큰 비밀(`xoxb-`·API 키 패턴), 모델 오류 raw. 허용: 공고 제목·id, 수치, stage 이름, error_code.
- `cap`은 그날 활성 `transfer_policy_approval.daily_cap`(용도별), 없으면 null.

### 보고서 `docs/experiments/<날짜>-local-llm-token-optimization.md`

1. 가설: "1층 추출(batch)이 토큰의 과반을 쓰고 출력 schema가 엄격해 로컬 모델 대체 후보다; 역할·종합은 Luna 유지."
2. 기준(채택 조건, 후속 실험용): 후보 단계를 로컬 모델로 바꿔도 RL-05 gold 10건에서 판정 일치·차단 recall·카드 상태 일치가 Luna 기준 대비 비열화(각 지표 하락 0), 호출당 지연 개선, 단계별 검증 실패율(`by_stage.failed_by_code`의 `card_extract_invalid` / calls) 증가 ≤ 5%p(기준선은 이 보고서의 usage.json). 운영 비용 단가는 이번 보고서에서 산정하지 않는다.
3. 명령: `usage-report` 실행 명령과 입력 기간, 결과 파일 sha256.
4. 결과: 단계별 토큰 분포 표(usage.json에서), 후보 단계 표(단계·근거·필요한 변경: 정책 파일·runner contract·allowlist·승인).
5. 판단: 후보 단계 선정과 "다음 기능(실제 비교 실험)" 범위 제안. 실험을 실행하지 않았음을 명시.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| `usage-report --purpose` | enum | all | deep_review\|proposal\|all | |
| `by_notice` 상위 수 | int | 50 | 고정 | |

## 상태 값과 실패 처리

- 토큰 null은 미측정으로 보존. CLI 오류 code `invalid_range`(from > to), `database_unavailable`, `invalid_purpose`(모두 exit 2).

## 저장

- migration(단일 head 다음, RL-03·04 테이블이 있어야 함) 열 6개 nullable. 권한: worker INSERT는 테이블 단위라 추가 없음; `proposal_section`의 UPDATE 허용 열은 RL-04 소유. `test_runtime_database_privileges.py`로 확인.
- 착수 조건: RL-03·RL-04가 `validating` 이후(큐 depends_on). 그 전에는 변경 대상 파일이 없다.

## 인터페이스

- CLI 1개. UI 없음. 외부 호출 없음.

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 실제 로컬 호출은 하지 않음 | 제약 "RL 호출은 Luna 하나"; 전환은 정책·allowlist·승인 변경이 필요한 별도 기능 | 이 기능에서 비교 실험 |
| 토큰 null 보존 | 미측정을 0으로 승격 금지(강제 게이트) | 0 보정 |
| 보고서는 docs/experiments | HP 계약 §10 선례 | 화면 |
| repair 토큰 분리 | repair 비율이 후보 판단 입력 | 합산 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T0 | runner: codex `--json` usage 이벤트 있음/없음/버전 불일치 | 응답에 `prompt_tokens`·`output_tokens` int / null, 기존 키·contract 불변 | 단위(runner 테스트 + 가짜 codex) |
| T1 | `luna_client` 응답 → stage 저장(1차·repair 분리) | 값 그대로 / null | 단위 |
| T2 | usage-report 집계: KST 경계·null(한쪽만 포함) 제외·중앙값/p90 정의·`by_day` units/cap(철회·재승인 날)·stage 생략·상위 50·legacy attempt 제외 | 수치 정확, `unmeasured_calls` | 단위(fixture) |
| T3 | `usage.md`에 prompt 원문·토큰 비밀 없음 | 금지 문자열 0 | 단위 |
| T4 | PG migration·권한 | head 일치, worker INSERT 열 포함 | PostgreSQL |
| T5 | 실제 bidops-local 기간 보고 1회 → 보고서 작성 | 파일 sha·표 | 수동 |

## 컨벤션 반영 항목

- runner 응답 키 2개(추가형), 열 6개, `bidops.usage-report.v1`, CLI `usage-report`(exit 2 통일·성공 stdout 키), `docs/experiments/` 디렉터리 신설.
