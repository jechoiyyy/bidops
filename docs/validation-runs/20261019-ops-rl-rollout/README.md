# 2026-10-19 Mac 운영 스택 RL 반영 (main `b8005ef`)

- 승인: 2026-10-19 사용자 일괄 승인("A+B 일괄 승인") — A1 C-2 Mac 작업 커밋·main 병합, A2 리허설, A3 백업·롤백 태그, A4 이미지, A5 PDF 키·minio-init, A6 migration·교체, A7 확인. 모델 호출·cron·origin push 없음.
- 대상: compose 프로젝트 `bidops`(`scripts/mac-compose.sh`, 작업 트리 `/Users/temp/orca/bidops-c2mac`, 브랜치 `feat/c2-litellm-mac`를 main `b8005ef`로 fast-forward). 운영 경로·env·회차 데이터·volume은 그대로다.

## 반영 전 상태

| 항목 | 값 |
|---|---|
| 코드 | `c242850` + 미커밋 C-2 Mac 작업 51파일 → 커밋 `fba05f6`(롤백 태그 `before-rl-rollout-20261019`) |
| 이미지 | `bidops:c2mac-20261015`(amd64), `bidops:document-arm64-c2mac-20261015`(arm64) — 롤백용으로 보존 |
| Alembic head | `0033_assumption_analysis` |
| C-2 | `c2-order-plan-screening-v5`(`1e6d4ef1…`) 활성, 일일 스위치 ON |

## 단계와 결과

| 단계 | 결과 |
|---|---|
| A1 병합 | `feat/c2-litellm-mac`(fba05f6) → main merge `b8005ef`. 충돌 2건(docs/ADR.md 색인에 ADR-0072 줄, findings.md 양쪽 항목 보존). 병합 영향 테스트 486 passed(일회용 postgres:17.11, 모듈 경계·runtime 권한·alembic autogenerate·migration 포함), doctor 0 |
| A3 백업 | DB `backups/postgres/full/bidops-20261019T011818Z.dump`(59,691,320 B, sha256 `d1d0c4685123fd0365f55356e75340634392ef679f085e74b14fb3eb99d50059`, `pg_restore --list` TABLE DATA 87). 객체 `backups/objects/20261019T0120Z/`(version 2,024: source 558·structure 747·quarantine 451·model-response 268, 1.7 GB, `object-versions.tsv`). env 사본 `backups/env-before-rl-rollout-20261019`(0600). 모두 운영 작업 트리 안 gitignore 경로 |
| A2 리허설 | 덤프를 일회용 postgres:17.11(내부망)에 복원 → 새 이미지 `migrate.sh`: `0033→0041` 8개 revision 통과, runtime-privileges 적용, `alembic check` "No new upgrade operations detected". 행 수 notice 820·opportunity 3,239·deep_review 0 동일, 감사 28→36(migration 표식 8) |
| A4 이미지 | `bidops:rl-20261019`(amd64, `c19ddc9c…`), `bidops:document-arm64-rl-20261019`(arm64, rhwp `cac9b4f7`, 앱 트리 = `git archive b8005ef web/backend/app` − baseline_company_profile.md, manifest sha `c13b05d2…`; 이전 manifest는 `.sdlc/local-runtime/rhwp-arm/bidops-app.sha256.pre-rl-20261019`로 보존). 문서 worker 모듈 import 확인 |
| A5 키·MinIO | 운영 `.env`에 새로 생성한 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY` 추가(로컬 키 재사용 없음, 값 미출력), `BIDOPS_IMAGE`·`BIDOPS_DOCUMENT_IMAGE` 교체. compose 렌더에서 PDF 키는 web·minio-init에만. minio-init 재실행 exit 0 → 버킷 `bidops-proposal-pdf`(versioning enabled, 최신 version 365일 만료), 전용 사용자 1명·정책 연결. 기존 버킷 4개 유지 |
| A6 교체 | analysis-worker·document-worker 정지 → `run --rm --no-deps migrate` exit 0(`0033→0041`) → `up -d --no-deps --no-build --force-recreate --scale document-worker=2 web analysis-worker document-worker` |
| A7 확인 | web healthy·`/api/health` 200, Alembic `0041_proposal_draft`, 컨테이너 env의 PDF 키는 web 2·analysis/document worker 0, `c2-mac-model-preflight.sh` ok(alias local-agent-main, digest `41a558fc…`), daily-trigger 반영 전과 동일(v5 `1e6d4ef1…`, switch ON, reasons 없음), 사업·회차·정책 GET 200, worker 로그 오류 없음 |

## 반영 뒤 상태와 남은 것

- RL-03·RL-04 경로(`/api/opportunities/{id}/verdict|proposal…`)는 `BIDOPS_RL_ANALYSIS_ENABLED=false`(기본)라 404 — 설계대로 숨김. 운영에서 켜려면 RL-00 실회사 등록, codex runner overlay, 정책 단위 전송 승인이 별도 결정으로 필요하다.
- `/api/briefings/latest` = `briefing_not_found`: 운영 DB에 루트랩 회사 근거·브리핑 생성이 아직 없다(RL-00 등록·RL-01 일일 생성은 별도 결정).
- 사전규격 개요 플래그·상시 첨부 worker는 이전처럼 꺼진 상태로 두었다.
- 롤백: `.env`를 `backups/env-before-rl-rollout-20261019`로 되돌리고 이전 이미지로 `up -d --no-deps --no-build --force-recreate`, 스키마는 `bidops-20261019T011818Z.dump`를 빈 DB에 복원(operations "복구" 절). 0034~0041은 nullable 열·새 테이블만 더하므로 이전 코드가 새 스키마를 읽는 데 막힘은 확인되지 않았으나 시험하지 않았다.
