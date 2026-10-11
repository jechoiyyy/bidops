# DEMO-03 STEP-007 대표 1건 실제 Luna 심층 — 진행 기록

증거 정본은 `docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md`다. 이 파일은 단계별 승인·실행·검증을 시간순으로 적는다. 비밀 값·원문·모델 원응답은 적지 않는다.

## 승인 이력

| 시각(KST) | 승인 | 범위 |
|---|---|---|
| 2026-10-11 01:5x | 사용자 "1단계 실행 승인" (AskUserQuestion 선택) | 백업·롤백 태그 → DEMO-03 이미지 빌드 → 격리 `bidops-local` DB 0036 migration. 그 외(3사 등록·정책 import·env·스택 교체·대표 공고·실제 호출)는 포함하지 않음 |

## 1단계 (2026-10-11, 완료)

- 사전 확인: `bidops-local` 프로젝트는 `/Users/temp/orca/bidops`(main checkout)에서 `.sdlc/local-runtime/manage.sh`로 기동돼 있었고 web 이미지는 `bidops-local:litellm-20261009`(d754995 기반 + LiteLLM 패치), DB head `0033_assumption_analysis`. compose 파일 5개와 `web/Dockerfile`·`scripts/migrate.sh`는 기능 worktree와 동일, `scripts/runtime-privileges.sql`만 DEMO-03 변경분이 있다(이미지 안의 사본을 migrate가 쓰므로 새 이미지로 적용).
- 백업: `demo03-step007-backup.log` exit 0, dump `backups/postgres/full/bidops-20261010T165821Z.dump`(1,208,621 B, sha256 `dac2f2b2…8718`), `demo03-step007-backup-toc.log` = `pg_restore --list` 1131행. 객체 manifest 백업은 schema 변경만이라 생략(기록).
- 롤백 태그: `before-demo03-local-20261011` → d754995.
- 이미지: `demo03-step007-image-build.log` exit 0 → `bidops-local:demo03-20261011`(sha256 `02e90973…e06a`). 이미지 안 0036·회사 모듈·정책 sha·권한 SQL sha·`ALEMBIC_HEAD` 확인, `demo-fixtures` 미포함.
- migration: `demo03-step007-migrate.log` exit 0(0033→0034→0035→0036 + runtime-privileges). 사후 `alembic current` = `0036_company_analysis (head)`. 구 web 계속 healthy(추가 열 모두 nullable).
- 하지 않은 것: web·analysis-worker 교체, codex-runner 기동, 3사 등록, 정책 import, `env/demo.env`, 실제 모델 호출.

## 2단계 import (2026-10-11, 완료 — 사용자 "import 승인 (actor=jechoi)")

- 사전 dry-run 3건(actor `demo03-preflight`, 컨테이너 마운트 경로 검증) exit 0·errors=[]·source sha256 = 재승인 hash.
- 실제 import 3건 `demo03-step007-companies-import.log`: demo-cloud-si `f3a41b46…`, demo-data-ai `0a826b35…`, demo-public-si `69bb13e4…` 모두 created=true·activated=false. ID 표는 README.
- DB 직접 SELECT는 세션 권한 정책(production reads 거부)으로 하지 않음.
- activate(사용자 "activate 승인 (3사)") 3건 `demo03-step007-companies-activate.log`: 3사 모두 changed=true, revision=1.

## 3단계 정책 import (2026-10-11, 완료 — 사용자 "2건 모두 import 승인")

- `demo03-step007-policy-import.log`: 심층 demo 정책 `cd59bbdd-b4a6-4308-94f0-6b8aea180efc`(sha 일치, label `analysis-policy-luna-demo-v1`) + 전역 프로필 version `8064fda4…`(부수 생성, 기록); 회사 핏 정책 `4cef3dff-8654-4f5e-a953-7a11ccf82b6e`(created=true). 활성화·env 변경·재기동 없음.

## 4단계 env·스택 교체 (2026-10-11, 완료 — 사용자 "4단계 실행 승인", 인증 파일 경로 사용자 지정)

- `env/demo.env`(기능 worktree, gitignore) 작성; scratch overlay `demo03-stack.yml`(demo env 3개 → web·analysis-worker, codex-runner image)·wrapper `demo03-compose.sh`(manage.sh + luna.yml + overlays + demo.env + `--profile luna`).
- codex-runner 이미지 빌드 `demo03-step007-codex-runner-build.log` exit 0(arm64). `config --format json` 렌더로 flag·네트워크·secret 확인.
- `up -d --no-deps --no-build --force-recreate web analysis-worker codex-runner` exit 0(`demo03-step007-stack-up.log`). health 200, `/api/companies` total=3, 컨테이너 env flag 확인, codex-runner 8091 listening(404 응답), 모델 호출 없음.
- 기록된 차이: 운영 참조 bind mount·host publish는 기존 bidops-local 그대로(DEMO-05의 demo overlay 범위).

## 5·6단계 준비 — 대표 공고 179 미리보기 fail-closed (2026-10-11)

- 후보: 공고 179 "2027년 한부모가족 혼인정보 연계시스템 운영 및 유지관리"(로컬 스택에서 유일하게 ready bundle `2a6f728f…`·완료 개요 `ff144ffa…`를 가진 공고, SW=Y, 문서 1개 HWPX, 구조 blocks 4141·text 120,150자).
- `POST /api/companies/{3사 각각}/pre-specs/179/deep-review-previews {bundle_id}` → 3건 모두 **409 `company_input_invalid`**. 모델 호출·DB 쓰기 없음(preview 실패는 행을 남기지 않는다).
- 원인(읽기 전용 진단 `scratch/diag/diag_preview.py`, 일회용 web 컨테이너에서 준비 단계를 하나씩 재현, 데이터 미출력): gate·회사 binding(node 29·edge 33)·정책·개요·SW·bundle은 통과. 분할 단위 47개(fallback 0). `document_segments.inventory_context`의 `expected_ids`=11(prefix 11개: COR·DAR·FUR·MHR·MPR·PMR·PR·PSR·QUR·SER·TR)인데 단위 본문에서 읽힌 ID는 50개(`COR-2…8`, `DAR-2` 등은 inventory에 없음) → `company_source_units`의 엄격 일치 검사(`company_deep_review.py:306`)가 거부. legacy Luna worker도 같은 입력을 `source_requirement_inventory_mismatch`(`deep_reviews.py:1753`)로 거부하므로 DEMO-03 고유 결함이 아니라 문서 inventory 추출의 기존 한계(`docs/tracking/findings.md` "inventory 식별자 vs 본문 식별자 차이" 항목)다.
- 회사 핏이 아닌 심층 경로만 시도했고 완화·우회는 하지 않았다.

## 결정 — T9 이관 (2026-10-11, 사용자 "T9를 DEMO-05로 이관(replan)")

- STEP-007을 "실제 격리 스택 준비·호출 전 게이트 확인"으로 재정의(spec T9·plan 수정, `sync-plan`, `run _ accept-spec`). 원안 대표 1건 실제 Luna 심층은 DEMO-05 첫 대표 1건×3사 인수로 이관(DEMO-05 spec/intent, roadmap, ADR-0070 개정, `feature.json` real_data_run applies_when, findings 재현 추가).
- 실행한 모델 호출 0, SQL 보정 0, 검사 완화 0. 스택은 demo flag·Luna enable·codex-runner 기동 상태로 남겨 두었다(중지는 별도 확인).
- 남은 것: 최종 검사 재실행·proof 기록·validating·커밋 대기.
