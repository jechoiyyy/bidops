# T15 Phase 1 live smoke 기록

## 실행 범위와 결론

- 검증 일시: 2026-08-26 08:55:05Z–09:04:37Z / 2026-08-26 17:55:05 KST–18:04:37 KST
- 대상 endpoint: `http://192.168.0.139:11434`
- 모델 tag: `qwen3.8:27b`
- `/api/tags`에서 확인한 digest: `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`
- BF16 tag(`qwen3.8:27b-bf16`)와 OpenAI/vLLM 경로는 사용하지 않았다.
- 결과: 단일 공고 live 실행은 모델 호출까지 진행했으나 `synthesis`가 2회 모두 `truncated_output`으로 실패했다. 최종 execution status는 `실패`이며, 유효한 v3 judgment는 0건이다.
- 이 결과는 성공으로 보정하지 않았다. 7-span 성공 조건이 충족되지 않았으므로 stop smoke와 Phase 2/3 gate는 수행하지 않았다.

## 격리 경계와 사전 준비

모든 DB·data·profile snapshot·artifact·로그는 다음 전용 runtime root 아래에만 생성했다.

`/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime`

실행 환경은 다음 경계를 명시했다.

- `BIDOPS_ROOT=/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime`
- `BIDOPS_DATA_DIR=/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/data`
- `BIDOPS_ATTACHMENTS_DIR=/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/data/attachments`
- `BIDOPS_DATABASE_URL=sqlite:////home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase1-db/bidops.db`
- `BIDOPS_OLLAMA_BASE_URL=http://192.168.0.139:11434`
- `BIDOPS_OLLAMA_MODEL=qwen3.8:27b`
- `BIDOPS_LIVE_OLLAMA_TEST=true`
- `BIDOPS_SCHEDULER_ENABLED=false`
- `BIDOPS_SCREEN_MAX_CONCURRENCY=1`

`alembic upgrade head`를 fresh SQLite에 명시 실행했고 revision은 `0004_migration_audit`였다. 이후 actor `t15-validation`으로 `screening-policy.v1.20260825`를 명시 seed했으며 상태는 `activation_candidate`였다. 정책 content digest는 `954f8275f8737183885d5007597f2d4c785b10d8720031d38015008f4c9c1289`이다.

tracked run `20260817-20260823`의 `validation-set.json`, `screening-decisions.json`, `screening-results.json`과 수집 산출물을 runtime으로 복사한 뒤 ingest했다. ingest 결과는 notices 40, judgments 40, reviews 0, warning 18이었다. 생성된 DB run ID는 `20260817-20260823--20260824T090927.138116Z`이다.

입력 파일 SHA-256:

| runtime relative path | SHA-256 |
|---|---|
| `data/runs/20260817-20260823/validation-set.json` | `2ea6a21e6b121f691195bbc891b8ec7766817f821d6b343c20b12b608f3e47e3` |
| `data/runs/20260817-20260823/screening-decisions.json` | `69a444e5ec9846c592de4b454472817477abaa4a109c97dbe84787dff9c6789d` |
| `data/runs/20260817-20260823/screening-results.json` | `fb9160602771ff057b708d69b197b9fc7e464f9e021615a7ebaa83a94733903b` |
| `data/runs/20260817-20260823/collected-notices.json` | `ec5021f5e09c6c15ccde090998df39b57dfdaf728f7a30a1bf24c8f1f1d98ce0` |

## 공고 선택과 실행 binding

선택 공고는 tracked validation-set의 첫 번째 deterministic candidate인 `bid:R26BK01689645:000`이다. DB에서 해당 run의 `candidate_pool`, `analysis`, `AI/데이터` row로 확인했으며, 임의 데이터나 fake 결과를 사용하지 않았다.

- execution ID: `scr-32011bae911d407e945308ea2ea63e57`
- queue no: `1`
- trigger/scope: `cli_single` / `single_notice`
- requested actor: `t15-validation`
- source run: `20260817-20260823--20260824T090927.138116Z`
- notice ID: `bid:R26BK01689645:000`
- policy/prompt: `screening-policy.v1.20260825` / `screening-prompt.v1`
- model: `qwen3.8:27b` / `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`
- current profile version/digest: `company-profile.sha256:96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e` / `96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e`
- input artifact: `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/screening-input.json`
- input artifact digest: `c627107d4813fd047270e0ed27567805c05f97a72ffb8f197a8209626bd75f26`
- artifact directory: `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57`

현재 profile은 사용자 dirty working-tree 파일을 읽기 전용으로 복사해 snapshot했으며 원본은 수정하지 않았다.

## v3/7-span, telemetry, 실패

실행 시작/종료는 `2026-08-26T09:00:39Z`–`2026-08-26T09:03:57Z` (`18:00:39`–`18:03:57` KST)이다. 논리 stage는 정확히 7개였고, 실제 attempt는 synthesis의 bounded retry 1회를 포함해 8개였다.

| stage | attempt | status | failure | prompt tokens | output tokens | total duration (ns) |
|---|---:|---|---|---:|---:|---:|
| 기술 적합성 | 1 | success | — | 593 | 236 | 95479281671 |
| 실적 정합성 | 1 | success | — | 587 | 254 | 6436238038 |
| 공공 SI 적합성 | 1 | success | — | 845 | 300 | 7055147667 |
| 사업성·자격 제약 | 1 | success | — | 459 | 272 | 6281827707 |
| 전략 부합 | 1 | success | — | 723 | 296 | 6715422526 |
| counterargument | 1 | success | — | 1954 | 410 | 12657975112 |
| synthesis | 1 | failure | truncated_output | 2419 | 2048 | 32057973554 |
| synthesis | 2 | failure | truncated_output | 2419 | 2048 | 29927135779 |

DB execution row는 `status=실패`, `candidate_count=1`, `completed_count=0`, `failure_count=1`, `error_summary=execution_failure`로 보존되었다. failure artifact에는 `failure_type=truncated_output`, `status=사람 검토 대기`가 기록되었다. `screening-decisions.json`은 `bidops.decisions.v3`지만 `judgments=0`이고, 성공 `screening-results.json`은 생성되지 않았다. 따라서 “7-span 성공”이나 v3 결과 게시를 주장하지 않는다.

Ollama 호출 payload 구현은 `think=false`, `stream=false`를 사용하며, 이번 실행의 각 응답은 단일 JSON envelope과 `done`/telemetry 계측으로 반환되었다. telemetry schema 자체에는 이 두 boolean 필드가 없으므로 raw prompt나 모델 응답을 로그에 복제하지 않고, payload 경로와 실행 계측으로 확인했다. 모델·profile·prompt 원문은 문서나 로그에 기록하지 않았다.

## 보존 artifact와 SHA-256

| runtime relative path | SHA-256 |
|---|---|
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/screening-input.json` | `c627107d4813fd047270e0ed27567805c05f97a72ffb8f197a8209626bd75f26` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/screening-telemetry.jsonl` | `f819898818bedc67ec8df25dcf3364ed1ec36a663c96cabf3441268c48e5a3a4` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/screening-decisions.json` | `bb46f66e5e5e44ca89237ea08ab5886c6cd2f967d24074d3ae78b4cc3fb08b60` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/screening-failures.json` | `c3d96b68fdc3748f560c0005dfd2c1ed4762bc66271ba1b3f2eacb3ca43e6d42` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/responses/0133d6d76c9b9944/기술 적합성-1.json` | `ec01288fd69701afe69b9c5d4f08cdf2db5e71dbfcceda5f7a96a5f3a1f77c50` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/responses/0133d6d76c9b9944/실적 정합성-1.json` | `e486570140b55b08a87afadac4592bc818eba3780bbc51fa47d6f2ec4db62680` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/responses/0133d6d76c9b9944/공공 SI 적합성-1.json` | `bd8a0548eba081041f97edc364ac15c16a77695b803e58d121a2d7fb260a4ebd` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/responses/0133d6d76c9b9944/사업성·자격 제약-1.json` | `ffec4a65b8d492d427686beceaef41cf1c12a1031fa1eb2160006486194d0132` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/responses/0133d6d76c9b9944/전략 부합-1.json` | `c4aaec43885188aeac6ae314892302568a24deedbcb562903358f5aa37cb00a4` |
| `data/screening-executions/scr-32011bae911d407e945308ea2ea63e57/responses/0133d6d76c9b9944/counterargument-1.json` | `5fc900155f439ace8554bccfa458e082a89e782d9bff3d5e01ec5642f957e74b` |
| `web/data/profile-snapshots/96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e.md` | `96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e` |
| `phase1-db/bidops.db` | `674dacbedfdaf725f99493ebdf46533901e9570f3cb37637f94fc5c1a9fd7449` |

`phase1-logs/`의 migration, seed, ingest, 최초 preflight input 오류, 수정 후 live 실행 로그도 runtime에 삭제 없이 보존했다.

## stop smoke 및 활성화 상태

stop smoke는 실행하지 않았다. 단일 smoke가 v3 judgment와 7-span 성공 조건을 충족하지 못했기 때문에 중지 요청을 추가하는 것은 계약상 의미가 없다. 해당 execution의 `stop_requested_by`와 `stop_reason`은 모두 null이며, 중지 actor/reason 또는 stop artifact는 존재하지 않는다.

시작/종료 DB 확인은 동일했다.

- policy `screening-policy.v1.20260825`: `activation_candidate`
- always-on DB switch: `false` (`updated_by=system:migration`)
- always-on quality gate binding: 없음
- scheduler environment: `BIDOPS_SCHEDULER_ENABLED=false`
- schedule DB `prespec_enabled`: `false`
- policy activation, candidate 변경, always-on enable, scheduler enable: 수행하지 않음

## source defect와 검증

첫 CLI 시도는 모델 생성 전 `input_error`로 종료되었다. 실제 `collected-notices.json`에는 `sample_stratum`과 `sample_role`이 없고, `_notice_common()`이 두 optional field까지 exact key set으로 강제한 것이 원인이었다. `de9665f`에서 두 키의 부재를 `None`으로 보존하도록 최소 수정하고 회귀 테스트를 추가했다.

검증 명령:

```text
cd web/backend && .venv/bin/pytest -q tests/test_screening_orchestrator.py -k 'collected_notice_without_sample_annotations or single_success_writes_exact_seven_attempts'
```

결과: exit code 0, 2 passed, 23 deselected.

추가 fake-only 회귀 확인:

```text
cd web/backend && .venv/bin/pytest -q tests/test_screening*.py
```

결과: exit code 0, 137 passed.

남은 blocker는 Qwen synthesis 출력이 `num_predict=2048`에서 두 번 잘린 점이다. 이 Phase 1 실행은 실패 상태로 보존되며, 성공을 만들기 위한 모델 설정 변경·추가 live smoke·fake 대체는 하지 않았다.
