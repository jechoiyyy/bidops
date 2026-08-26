# 구현·검증 현황

기준일: 2026-08-27
최종 리뷰 코드 기준: `3c8486f` (`bidops-deep-review`)
T1~T8 구현과 검증을 완료했고, 최종 독립 리뷰에서 확인된 회귀를 수정했다. push/merge/release는 하지 않았다.

## 코드 상태

| 영역 | 현재 상태 | 근거 |
|---|---|---|
| 수집·후보·다섯 관점 판정·보고 | 구현됨 | `bidops.*.v2` 계약, 회차 산출물, pipeline/backend 테스트 |
| PostgreSQL 정본과 SQLite 이관 | 구현됨, 실제 백업본 리허설 미수행 | PostgreSQL 17 `bidops` schema, Alembic, 13개 legacy table import/reconciliation 코드 |
| MinIO·ClamAV·문서 격리 | 구현됨, 실제 운영 권한 검증 미수행 | 목적별 bucket/credential, clean scan, `document-worker network_mode:none`, object hash/location |
| 단계 B document bundle | 구현됨 | 7개 bundle/document API, HWP/HWPX/PDF 검사·구조화, immutable ready snapshot |
| Agent 공통 계약·projection | 구현됨 | `web/backend/app/agents/common/`, 별도 Agent 상태 table 없음 |
| DocumentPreparation/DeepReview/Decision Agent | 구현됨 | 세 package의 typed command·adapter·projection과 대응 테스트 |
| 기존 mutation router 연결 | 구현됨 | document bundle·deep review·report mutation이 해당 Agent adapter를 호출하고 Lean v1 14개 API 계약 유지 |
| 단계 C deep-review runtime | 구현됨, provider-neutral | 세 stage, bounded chunk/retry, fenced job, encrypted raw response, report/validation/evidence API |
| React 심층 검토 화면 | 핵심 조회·리포트 검토 구현됨 | ready bundle 선택, review 시작, report/revision/final opinion 화면과 기능 테스트; T8 frontend 코드는 변경하지 않음 |
| Qwen 품질 activation gate | 계산·import 연결 구현됨, 실제 품질 증적 없음 | human-adjudicated scorer, 0.80/0.70/0.10 gate, policy SHA 일치 import |
| T7 Agent 연속 인수 | 실제 격리 Mock E2E 통과 | PostgreSQL·MinIO·ClamAV·document worker 2개·analysis worker·web, `passed=true`, 종료 active WorkJob 0 |
| legacy run ingest | 최종 리뷰에서 해결·실제 재검증됨 | `screening_basis TEXT` migration, 깨끗한 PostgreSQL에서 40 notices/40 judgments를 두 번 멱등 적재, 102자 원문 보존 |
| 백업·복구 자동화 | 구현됨, 실제 snapshot 복구 훈련 미수행 | object-first restore, PostgreSQL restore, active hash 검증 script |

## 2026-08-27 T8 검증 결과

| 실행 명령 | 결과 |
|---|---|
| `./run-tests.sh` | 성공. `skills/bidops-collect` 28개, `skills/bidops-report` 13개, `skills/bidops-screen` 21개, root `tests` 2개가 모두 `OK`(총 64개) |
| `./web/run-web-tests.sh` | 성공. backend `356 passed, 4 skipped, 6 warnings`; 이어서 frontend Vite build 성공(135 modules transformed) |
| `web/backend/.venv/bin/pytest web/backend/tests` | 성공. `356 passed, 4 skipped, 6 warnings in 20.02s` |
| `cd web/frontend && npm run build` | 성공. Vite 6.4.3, 135 modules transformed, `built in 1.88s` |
| `git diff --check` | T8 문서 수정 완료 후 최종 실행에서 성공 확인 |

backend의 4 skip은 `test_document_bundles.py` 1개와 `test_minio_e2e.py` 3개로, 별도 isolated T7
MinIO service가 필요한 live integration test다. pytest의 6 warnings는 Pydantic `schema` field
shadowing 5건과 Starlette/httpx deprecation 1건이며 이번 실행을 실패로 만들지 않았다.

검증 환경에 `web/backend/.venv`가 처음 없어서 `./web/run-web-tests.sh`의 첫 실행은
`/usr/bin/python3: No module named pytest`(exit 1)로 끝났다. `.gitignore` 대상 virtualenv에
`web/backend/requirements.txt`를 설치한 뒤 같은 명령을 재실행해 위 성공 결과를 얻었다. 첫 실패를
통과 결과로 세지 않는다.

## 2026-08-27 최종 리뷰 검증 결과

- `web/backend/.venv/bin/pytest -q web/backend/tests`: `359 passed, 4 skipped, 6 warnings`
- `./run-tests.sh`: collect 28, report 13, screen 21, root 2; 총 64개 성공
- `./web/run-web-tests.sh`: backend 위 결과와 frontend Vite build 성공
- 별도 `npm run build`: Vite 6.4.3, 135 modules transformed, 성공
- 깨끗한 PostgreSQL 17: Alembic head `0002_screening_basis_text`, 같은 legacy 회차를 두 번 적재해
  40 notices/40 judgments와 동일 run ID, `screening_basis` 102자 무절단 보존 확인
- Luna Max 독립 리뷰에서 `UTF-8''`로 시작하는 printable ASCII actor 이름의 identity 회귀와
  percent 조합 충돌을 확인해 명시적 format header 방식으로 수정했다. Unicode round-trip, 모든 ASCII
  보존, unknown format과 malformed/ASCII-only/control encoding 거부를 포함한 관련 회귀
  `208 passed, 1 skipped`를 재검증했다.

## 2026-08-27 T7 실제 격리 E2E

- `docker-compose.t7.yml` + `docker-compose.t7.mock-reference.yml`의 새 격리 project에서 실행했다.
- PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web을 사용했다.
- provider/model은 `mock-analysis` / `bidops-deterministic-mock-v1`이다.
- 외부 OpenAI/Codex/Qwen 호출은 0건이고 종료 queued/running WorkJob은 0건이었다.
- 결과 schema는 `bidops.t7-e2e-result.v1`, `passed=true`였다.
- 종료 후 격리 container, network, volume을 정리했다.

두 날짜의 bundle/review/revision/opinion ID와 projection checkpoint는
[`docs/mock-workflow-e2e-result.md`](../mock-workflow-e2e-result.md)에 보존한다. Mock 결과의
`mock_quality.evaluated=false`는 실제 Qwen 품질 gate를 통과했다는 의미가 아니다.

## 배포 후보 승격 전 남은 일

1. 원격 vLLM image digest와 `Qwen/Qwen3.8-27B` immutable revision/artifact digest를 고정하고,
   대표 HWP/PDF와 55개 요구사항 gold로 실제 0.80/0.70/0.10 품질 gate를 측정한다.
2. measured profile/policy import와 승인된 외부 egress·secret·MinIO 권한을 실제 배포 환경에서
   검증한다. Mock E2E 증적을 Qwen evidence로 재사용하지 않는다.
3. 운영 SQLite가 아닌 백업 복사본으로 13개 table row/PK/FK, sequence, 리뷰·첨부 metadata,
   실패 후 재실행과 object→DB→active hash 복구를 리허설한다.
4. 고정 Playwright image/font에서 28개 snapshot을 재생성하고 사람이 승인한다. T8에서는 Playwright
   visual test를 실행하지 않았다.
5. 위 조건을 충족하기 전에는 main merge, push, release, Lean v1 tag를 수행하지 않는다.

현재는 T1~T7 Agent 구현과 Mock workflow 인수는 완료됐지만, 실제 Qwen 품질 승인·clean legacy
운영 복구/권한 검증은 완료되지 않은 상태다. clean legacy ingest 차단 문제는 최종 리뷰에서
해결하고 실제 PostgreSQL로 재검증했다.
