# DEMO-03 STEP-007 — 실제 격리 스택 준비와 호출 전 게이트 확인 (2026-10-10 전제 점검 · 2026-10-11 적용·종결)

이 디렉터리는 DEMO-03 spec T9의 실제 `bidops-local` 증거다. **실제 Luna 모델 호출은 한 번도 수행하지 않았다.**
2026-10-11 사용자가 단계별로 승인한 1~4단계(백업·롤백 태그·이미지·0036 migration → 3사 import → 3사 activate → demo 정책 2건 import → `env/demo.env`·web/analysis-worker 교체·codex-runner 기동)를 적용했고, 유일한 준비 공고 179의 회사 미리보기는 모델 호출 전에 `company_input_invalid`로 fail-closed됐다(기존 findings inventory 불일치).
사용자 결정(2026-10-11)으로 원안 T9 "대표 1건 실제 Luna 심층"은 DEMO-05 첫 대표 1건×3사 인수로 이관했고 STEP-007은 "실제 격리 스택 준비·호출 전 게이트 확인"으로 재정의해 종결했다. 문서화·코드 검증 완료는 실행 승인이 아니다.
재현 자료: `compose/`(이미지·스택 overlay, compose wrapper, 읽기 전용 진단 스크립트 — 경로는 이 세션 기준이라 재사용 시 수정). 스택은 demo flag·Luna enable·codex-runner 기동 상태로 남아 있다(중지·되돌림은 별도 확인).

## 코드 상태(fake 검증까지)

- 기능 worktree `sdlc/demo0203-20261009-DEMO-03-grounded-analysis`, 기준 0d980bd, 미커밋.
- fake Luna 종단(`web/backend/tests/app/test_company_e2e.py`: preview→승인→공용 슬롯 claim→3단계→보고서/근거/비교 일치)은 일회용 PostgreSQL에서 통과(`docs/work/_runs/demo0203-20261009/demo03-step006-leader.log`).
- fake runner는 codex-runner wire 계약(`POST /calls`→`GET /calls/{id}`→`DELETE`)을 따르되 `running` 상태를 돌리지 않으므로 LunaClient polling loop는 실제 실행에서 처음 검사된다.

## 2026-10-10 전제 점검(읽기 전용)

| 항목 | 상태 | 비고 |
|---|---|---|
| `bidops-local` 스택 | web·postgres·minio·clamav·document-worker 2개 Up | analysis-worker·codex-runner 미기동. web은 아직 `bidops-local:litellm-20261009`(DEMO-03 이전 코드)로 실행 중, 교체는 다음 확인 대상 |
| DB head | 2026-10-11 `0036_company_analysis` 적용 완료 (이전 `0033_assumption_analysis`) | 아래 1단계 기록. 적용 전 백업 `bidops-20261010T165821Z.dump` |
| env | `env/local.env`·`env/local-model.env`만 존재 | `env/demo.env`(demo flag·policy ID·`BIDOPS_CODEX_AUTH_FILE`) 없음 |
| compose overlay | `docker-compose.luna.yml` 존재 | `docker-compose.demo.yml`(§10 volume `!override`) 없음 — DEMO-05 준비 범위 |
| 3사 등록·활성 binding | 미등록(DEMO-02는 fixture 승인까지) | `import-company-knowledge`/`activate-company-knowledge` 필요 |
| demo 정책 행 | 미import | 심층 `analysis-policy-luna-demo-v1`(sha256 `9cb6254ef2f7fa3fbc608d775951aed14d958204f5366b30f92da661a4cbc3b0`), 핏 `company-fit-demo-v2.json` |
| 대표 공고 | 미선정 | SW=Y·ready bundle(실제 structure·DocumentBlock)·completed v7 개요 필요, 원문 unit 수 적은 공고 우선(§7) |

## 1단계 적용 기록 (2026-10-11, 사용자 승인 "1단계 실행 승인")

스택 정의는 `bidops-local` 프로젝트(`/Users/temp/orca/bidops` main checkout, `.sdlc/local-runtime/manage.sh`: docker-compose.yml → edge → model-egress → prespec-attachment → `.sdlc/local-runtime/compose.yml` → `litellm.yml`, env `env/local.env`·`env/local-model.env`)를 그대로 쓰고, 이미지만 바꾸는 overlay 한 장을 덧붙였다(아래). 운영 DB·MinIO·volume은 건드리지 않았다. 로그는 `docs/work/_runs/demo0203-20261009/demo03-step007-*.log`.

| 항목 | 결과 |
|---|---|
| 적용 전 head | `0033_assumption_analysis` (`alembic current`, migrate 역할, 기존 이미지) |
| 전체 백업 | `--profile backup run --rm ro-backup` exit 0 → `backups/postgres/full/bidops-20261010T165821Z.dump` 1,208,621 B, SHA-256 `dac2f2b2214f48617d78b9b38888bfec6b3ca6a099870aa57455f89a2d2d8718`, `pg_restore --list` exit 0(TOC 1131행, TABLE DATA 87, alembic_version 포함). 객체 manifest 백업은 하지 않았다(schema 변경만, 객체 불변; 기존 2026-10-09 백업과 같은 범위) |
| 롤백 태그 | `before-demo03-local-20261011` → `d754995`(현재 실행 이미지의 빌드 기준 커밋, 기존 `before-litellm-local-20261009`·`before-native-arm-local-20261009`와 같은 대상). 런타임 롤백은 기존 이미지 `bidops-local:litellm-20261009`로 재기동 + 위 dump 복원 |
| 이미지 | `docker build --platform linux/amd64 -f web/Dockerfile -t bidops-local:demo03-20261011 .`(기능 worktree, 기준 0d980bd + 미커밋 변경 39 파일 +1867/−221·신규 63) exit 0, image `sha256:02e90973b68f999d937fe9994bbca0b246e0592b231c1e3a699a1cb9b255e06a`. 확인: `alembic/versions`에 0034·0035·0036, 회사 라우터·CLI·정책 2개 존재, `runtime-privileges.sql`·정책 sha256이 worktree와 일치(`9cb6254e…c3b0`, `eb075ecb…71e7`), `ALEMBIC_HEAD="0036_company_analysis"`, `/app/docs`에 `demo-fixtures` 없음 |
| migration | `run --rm --no-deps migrate`(새 이미지) exit 0: 0033→0034→0035→0036, `runtime-privileges.sql` 적용. 적용 후 `alembic current` = `0036_company_analysis (head)` |
| 기존 서비스 | 구 web(`litellm-20261009`) 계속 Up·`/api/health` 200·`/api/pre-specs?workspace=all` 응답. 0034~0036이 기존 table에 더한 열은 모두 nullable이라 구 코드와 공존한다 |
| document-worker | `bidops-local:document-arm64-cac9b4f7-20261009`(native arm64) 유지. DEMO-03은 문서 파이프라인 경로를 바꾸지 않았다 |

이미지 overlay(`demo03-images.yml`, 세션 scratch에 두었고 Git 밖):

```yaml
services:
  migrate:         { image: bidops-local:demo03-20261011 }
  ro-backup:       { image: bidops-local:demo03-20261011 }
  web:             { image: bidops-local:demo03-20261011 }
  analysis-worker: { image: bidops-local:demo03-20261011 }
```

## 실행 순서(각 단계 직전 사용자 확인)

1. ~~백업·롤백 태그 → DEMO-03 이미지 빌드 → `0036_company_analysis` migration(격리 DB만).~~ 2026-10-11 완료(위 기록).
2. 3사 원본 import·activate(승인 기록 `../../2026-10-09-company-demo/DEMO-02-company-knowledge/fixture-approval.md`의 hash와 대조).
   - **import 완료(2026-10-11, 사용자 "import 승인 (actor=jechoi)")**: 일회용 `web` 컨테이너(새 이미지, app 역할, `--no-deps`, `docs/demo-fixtures`를 `/run/demo-fixtures`로 read-only 마운트)에서 `import-company-knowledge --ontology … --company … --actor jechoi`를 회사별로 실행. 사전 dry-run 3건 exit 0·errors=[]. 결과(`docs/work/_runs/demo0203-20261009/demo03-step007-companies-import.log`):

     | 회사 | company_id | profile_version_id | graph_version_id | source_sha256(재승인 기록과 일치) | graph_sha256 |
     |---|---|---|---|---|---|
     | demo-cloud-si | `f3a41b46-ed69-497d-bdaf-df351671e180` | `90bca931-1cf2-413c-b6e4-b9c3edadca69` | `58549433-9153-4eb2-bccb-eeffbeb47988` | `ae3a1ad3…74c41` | `e863e119…8ad6` |
     | demo-data-ai | `0a826b35-c413-4fa6-92ea-946190640e71` | `4ce80ab6-0c4f-4262-b0e1-1095e6b5b4aa` | `f389a5e0-70d8-40c5-8560-dbbd1e5ac5ac` | `19366eab…8fdc2` | `0ae128b3…9d82` |
     | demo-public-si | `69bb13e4-4a64-47cb-bcb7-28e88e7bf84c` | `be128cbf-120c-4910-8d40-663acc00cdbd` | `a2410635-4825-4adb-b81d-2fa363d09e5b` | `7b83417b…4670` | `d8d32ca1…fe18` |

     모두 `created=true`, `activated=false`, ontology v1. DB 직접 SELECT 검증은 이 세션의 권한 정책으로 하지 않았고, CLI 응답과 이후 새 web의 회사 읽기 API로 확인한다.
   - **activate 완료(2026-10-11, 사용자 "activate 승인 (3사)")**: `activate-company-knowledge --company-id … --graph-version-id … --actor jechoi` 3회(`demo03-step007-companies-activate.log`). 3사 모두 `changed=true`, `revision=1`, profile_version_id는 import 결과와 동일. 정책 import·모델 호출 없음.
3. 정책 import: `python -m app.deep_review.cli import-profile-policy --policy app/deep_review/policies/analysis-policy-luna-demo-v1.json --expected-policy-sha256 9cb6254ef2f7fa3fbc608d775951aed14d958204f5366b30f92da661a4cbc3b0`(전역 프로필도 함께 import됨을 기록), `import-company-fit-policy --policy app/deep_review/policies/company-fit-demo-v2.json --actor <이름>`. 활성화 없음.
   - **완료(2026-10-11, 사용자 "2건 모두 import 승인")**, 일회용 `web` 컨테이너(새 이미지, 이미지 안 정책 파일), 로그 `demo03-step007-policy-import.log`:

     | 정책 | policy_version_id | sha256 | 비고 |
     |---|---|---|---|
     | 심층 `analysis-policy-luna-demo-v1` (label 동일) | `cd59bbdd-b4a6-4308-94f0-6b8aea180efc` | `9cb6254e…c3b0` (expected와 일치) | 같은 명령이 전역 프로필 version `8064fda4-434d-42bd-9ad1-5d199c9dc758`(`docs/reference/company-profile.md` bind mount, profile_sha256 `3810debb…c311`)도 격리 DB/MinIO에 만들었다. `active_configuration_changed=false`. 품질 인자 없음 → 참조 실행용 |
     | 회사 핏 `company-fit-demo-v2` | `4cef3dff-8654-4f5e-a953-7a11ccf82b6e` | `eb075ecb…71e7` | `created=true`, 활성화 없음 |

     이 UUID 2개가 `env/demo.env`의 `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`·`BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID` 값이다. 전역 `BIDOPS_ACTIVE_*`는 비워 둔다(legacy 경로 미사용).
4. `env/demo.env`: `BIDOPS_DEMO_ENABLED=true`, `REFERENCE_WORKFLOW_MODE=true`, `BIDOPS_LUNA_DEEP_REVIEW_ENABLED=true`, `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`·`BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID`(web·analysis-worker 동일), `BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false`, mock provider off, `BIDOPS_CODEX_AUTH_FILE`. 렌더된 config/컨테이너 env로 확인.
   - **완료(2026-10-11, 사용자 "4단계 실행 승인", 인증 파일은 사용자가 지정한 기본 Codex 인증 파일 — 경로는 `env/demo.env`에만 있음)**:
     - `env/demo.env`는 기능 worktree `env/`에 두었고 gitignore(`env/*.env`) 확인. 위 flag 외에 `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=false`·`BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`·`BIDOPS_SCHEDULER_ENABLED=false`·`BIDOPS_C2_DAILY_TRIGGER_ENABLED=false`·전역 `BIDOPS_ACTIVE_*` 빈 값.
     - compose 조합 = manage.sh 6개 파일 + `docker-compose.luna.yml` + `demo03-images.yml` + `demo03-stack.yml`(web·analysis-worker에 `BIDOPS_DEMO_ENABLED`·demo 정책 ID 2개 environment 추가, codex-runner image 지정) + `--env-file env/demo.env` + `--profile luna`. `config --format json` 렌더에서 web·analysis-worker의 위 flag·정책 ID, analysis-worker `BIDOPS_LUNA_RUNNER_URL=http://codex-runner:8091`·`luna-internal` 네트워크, codex-runner `luna-internal`+`luna-egress`·secret `codex_auth`만 확인(`demo03-config.json`은 scratch).
     - codex-runner 이미지 `bidops-local:codex-runner-20261011`(arm64, `web/codex-runner/Dockerfile`, @openai/codex 0.155.1; 입력 파일 4개는 main checkout과 동일) `demo03-step007-codex-runner-build.log` exit 0.
     - `up -d --no-deps --no-build --force-recreate web analysis-worker codex-runner` exit 0(`demo03-step007-stack-up.log`). web `demo03-20261011` healthy, `/api/health` 200, `/api/companies` 200 total=3(slug 3개, `is_fictional=true`). 컨테이너 env에서 flag 렌더 확인(web·analysis-worker). analysis-worker 로그는 pydantic UserWarning만, 모델 호출 없음.
     - 계약 §10과의 차이(기록): web의 운영 참조 bind mount(`docs/reference/company-profile.md` 등)와 host publish 18787은 기존 `bidops-local` 그대로 유지했다. `!override` volume 교체·`docker-compose.demo.yml`·`prepare-company-demo.sh`는 DEMO-05 범위.
5. 대표 공고 1건 선정·문서 준비·개요 one-shot(자동 시작 false 유지), SW=Y 확인.
   - **2026-10-11 후보 179 → 미리보기 fail-closed**: 로컬 스택에서 ready bundle(`2a6f728f…`, HWPX 1개, blocks 4141·120,150자)과 완료 개요(`ff144ffa…`)를 가진 공고는 179 하나였다(SW=Y). 3사 각각 `POST …/pre-specs/179/deep-review-previews` → **409 `company_input_invalid`**, 모델 호출 0·DB 쓰기 0.
     읽기 전용 단계 재현(일회용 web 컨테이너, 데이터 미출력): binding·정책·개요·SW·bundle 통과, 분할 단위 47개, segment manifest `expected_ids` 11개(prefix 11개) vs 단위 본문 관측 ID 50개(`COR-2…8`, `DAR-2` 등이 inventory에 없음) → `company_source_units` 엄격 일치 거부. legacy Luna worker의 `source_requirement_inventory_mismatch`와 같은 조건이며 `docs/tracking/findings.md` "요구사항 표의 행별 셀 위치 차이로 심층검토가 호출 전에 실패한다(2026-09-22, 미해결)"의 재현이다(DEMO-03 고유 결함 아님, 완화·우회하지 않음). 세부는 `docs/work/_runs/demo0203-20261009/demo03-step007-result.md`.
6. 회사 1개에 대해 `POST /api/companies/{id}/pre-specs/{notice}/deep-review-previews` → 사람이 입력 확인 → `POST .../deep-reviews`(건별 승인) → analysis-worker 1 슬롯 claim → 3단계 → `GET .../deep-reviews/{review}`·`/report`·근거 원문 대조.
7. 증거: review/attempt/report revision ID, company·input hash, model/policy, 종료 상태, 검증 요약, 사용량/시간(null 보존), 화면 캡처, 담당자 확인 — 원문·secret·원응답은 기록하지 않는다. `quality_status=unmeasured_reference` 유지.

## 미실행 사유

위 전제 중 스택 이미지·migration·env·3사 등록·정책 import·대표 공고가 모두 미완이며 각각 운영 변경 또는 실제 모델 호출 직전 확인 대상이다. 사용자 승인 전까지 STEP-007은 in_progress(준비만)로 둔다.
