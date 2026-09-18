# Plan: 사업 추적 연결·조치 고도화 — [`intent.md`](intent.md) 2026-09-17 기준

목표: [`spec.md`](spec.md)의 규칙을 구현한다. 단계(P0~P6)마다 게이트를 통과한 뒤 다음 단계로
간다. 통짜 위임·통짜 검증을 하지 않는다.

## 시작 전 확인

- 기준 트리 `main` 3344076(4896429 이후 개요 fallback 병합 — 이 계획 파일과 겹치지 않음). 이 계획이 건드리는 파일을 수정하는 미병합 브랜치는 없다(ADR-0049
  문서 편집 브랜치만 있음).
- 모든 변경 전에 `docs/standards.md`, `docs/engineering-notes.md`, 변경 경로의 가장 가까운
  `AGENTS.md`를 읽는다. 백엔드는 모듈 경계 검사(`tests/app/test_module_boundaries.py`)를 지킨다.
- 실행 방식:
  - 단계별 worktree 브랜치(`feat/ot-<단계>`)를 쓴다. 워크트리에는 `.venv`·`node_modules`를 symlink하고
    `experiments/order-plan-screening/review-inputs/`를 복사한다.
  - 구현은 서브에이전트에 맡긴다. 설계 판단이 있는 작업은 opus, 기계적 작업은 sonnet이다.
    단계 사이 게이트와 로직 diff 검수는 관리자가 한다.
  - **merge하지 않고** 브랜치·커밋·검증 결과를 보고한다.
- migration 순서를 고정한다: `0027_collection_index_and_linkage`(P2a) → `0028_final_decision_basis`(P3).
  각 migration은 `app/core/db.py:103` `ALEMBIC_HEAD`를 갱신한다. P3는 P2a 커밋에서 분기한다.
- 새 ADR 번호는 0058(결정 근거 분리)·0059(전량 수집·선별 적재·색인 검색)다.
- 위임 프롬프트에 박을 것:
  - 수정 허용 파일 목록
  - "통과한 테스트 재실행 금지, 지시 파일 밖 실행 금지, 검사를 느슨하게 하거나 재시도 루프를 넣지 말 것"
  - 보고 항목당 한 줄
  - 픽셀 기준선 갱신 금지

## 바뀌는 파일

| 단계 | 파일 |
|---|---|
| P0 | `docs/validation-runs/20260917-bid-collection-probe.md`(완료) |
| P1-1 | `skills/bidops-collect/scripts/collect_order_plans.py`, `skills/bidops-collect/tests/test_collect_order_plans.py` |
| P1-2 | `web/frontend/src/components/opportunities/OpportunityDetail.tsx`, `src/lib/opportunity.ts`, `tests/opportunities-fixtures.ts`, `tests/opportunities.spec.ts` |
| P1-3 | `docs/tracking/findings.md`, `docs/business-rules.md`(:170) |
| P2a | `skills/bidops-collect/scripts/collect_notices.py`·tests, `skills/bidops-screen/scripts/build_screening_results.py`, `skills/references/workflow-contract.md`, `web/backend/app/screening/orchestrator.py`(optional 키 목록만), `app/lifecycle/ingest/{loader.py,cli.py,contracts.py}`, `app/lifecycle/models.py`, `app/lifecycle/services/collection_index.py`·`name_matching.py`(신설), `alembic/versions/0027_*.py`, `app/core/db.py`, `scripts/runtime-privileges.sql`, `tests/lifecycle/test_collection_ingest.py`(신설), 권한·migration 테스트 |
| P2b | `app/lifecycle/ingest/loader.py`, `services/opportunity_integrity.py`, `services/opportunity_tracking.py`, `routers/opportunities.py`, `schemas/opportunities.py`(link literal·ack 요청), `tests/lifecycle/test_opportunity_integrity.py`·`test_opportunity_tracking.py`·`test_opportunity_links.py`, `tests/app/test_api_opportunities.py` |
| P2c | `services/opportunity_candidates.py`(신설), `services/opportunity_queries.py`, `schemas/opportunities.py`, `services/workload.py`, `schemas/workload.py`, `routers/opportunities.py`(searches), `routers/pre_specs.py`(후보 조회), `tests/lifecycle/test_opportunity_sections.py`·`test_opportunity_candidates.py`(신설), `tests/app/test_workload_api.py` |
| P3 | `app/deep_review/services/{bid_delta.py,bid_delta_currentness.py,decision_queue.py,prespec_projection.py,bid_conditions.py(신설)}`, `schemas/bid_delta.py`, `routers/bid_delta.py`, `alembic/versions/0028_*.py`, `app/core/db.py`, `scripts/runtime-privileges.sql`, `tests/deep_review/test_bid_delta*.py`·`test_decision_queues.py`, `tests/app/test_runtime_database_privileges.py`, `docs/bid-delta-contract-spec.md`, `docs/deep-review-erd.md` |
| P4 | `scripts/run-daily-lifecycle.sh`(신설), `docs/operations.md` |
| P5-F0 | `web/frontend/src/lib/api.ts`, `src/lib/types.ts`, `tests/api-mock.ts`, `tests/opportunities-fixtures.ts`, `tests/go-no-go-fixtures.ts`, `tests/fixtures/lifecycle-v2.ts`, `tests/dashboard-fixtures.ts`, `tests/screen-semantics.spec.ts`(:74), `tests/common-interactions.spec.ts`(:453) |
| P5-F1 | `src/pages/OpportunitiesPage.tsx`, `src/components/opportunities/*`, `src/styles/opportunities-relaxed.css`, `tests/opportunities.spec.ts` |
| P5-F2 | `src/pages/DashboardPage.tsx`, `src/components/dashboard/*`, `src/styles/dashboard-erp.css`, `tests/dashboard.spec.ts` |
| P5-F3 | `src/pages/BidDeltaDecisionPage.tsx`, `src/pages/GoNoGoPage.tsx`, `src/components/bid-delta/*`, `src/styles/go-no-go.css`, `tests/go-no-go.spec.ts`, `tests/bid-delta.spec.ts` |
| P5-F4 | `src/pages/PreSpecDetailPage.tsx`(후보 구역), `src/components/pre-specs/OrderPlanCandidatesSection.tsx`(신설), `tests/pre-specs.spec.ts` |
| P6 | `docs/contracts.md`, `docs/business-rules.md`, `docs/operations.md`, `docs/ARCHITECTURE.md`, `docs/ADR.md`, `docs/tracking/decisions/0058-*.md`·`0059-*.md`, ADR-0025·0028·0030·0053 개정 메모, `docs/tracking/status.md`, `AGENTS.md`·`CLAUDE.md` |

## 작업 순서

### P0 — 실측·확인 (완료, 2026-09-17)

결과: [`../validation-runs/20260917-bid-collection-probe.md`](../validation-runs/20260917-bid-collection-probe.md).

- `indstrytyCd=1468`은 서버 필터로 동작한다(3일 138건, 전부 전체 결과의 부분집합, 전부
  업종제한 Y). SW 사전규격을 가리키는 입찰공고 84건 중 24건(29%)이 1468 밖이다. 수집 필터로
  쓰지 않는 결정을 유지한다.
- 발주계획 적재는 `collected-order-plans.json` 전량이다(`_load_order_plans`).
- C-1 full_run 적재는 수집 레코드를 그대로 쓰므로 관측 snapshot이 같다. 통합 테스트로 고정한다.

**게이트**: 실측 문서 커밋. 1468 표시 방식은 spec §1.2대로 진행.

### P1 — 작은 수정 (sonnet 3개 병렬)

1. **P1-1**: `bidNtceNoList` 오타 수정. 정규화 결과 `bid_ntice_no_list`가 원문 값으로 채워지는
   단언을 추가한다.
2. **P1-2**: spec §11.1 마지막 항목(심층 검토 보고서 목록).
   - `lib/opportunity.ts:143-183` 죽은 helper와 그 전용 상수·import를 삭제한다.
   - `opportunities-fixtures.ts`에 `/api/opportunities/*/deep-reviews` mock(항목 있음·빈 목록)을 추가한다.
   - `opportunities.spec.ts:613` 기대를 목록으로 바꾼다.
3. **P1-3**: findings "사업기회 추적 이력을 읽을 계약이 없고 구역별 집계도 서버가 세지 않는다"에
   종결 줄을 추가한다(구현: `GET …/tracking-decisions`, `section`·`section_counts`, 2026-09-17).
   `business-rules.md:170`을 ADR-0030(같은 사업기회에 붙이고 재검토 신호)에 맞춘다.

**게이트**: `./run-tests.sh`, `npx tsc -b`, `npx playwright test tests/opportunities.spec.ts`,
diff 확인.

### P2 — lifecycle 백엔드 (opus, P2a → P2b → P2c 순차)

- **P2a**: spec §1.2, §2 전체.
  - 수집기 필드·1468 표시 조회, optional 키 허용 목록, snapshot null 제외
  - migration 0027(색인 테이블·`notice.demand_agency`·링크 CHECK 확장·`search_target_kind`)과 권한
  - 이름 정규화 모듈 이식(`name_matching.py`, 실험 테스트 케이스 포함)
  - `ingest.cli --collection`·`--tracked-backfill` 진입점, 선별 규칙, 적재 통계
  - 테스트 `test_collection_ingest.py`: 선별 사유 8종, `null` 조건 제외, 재실행 멱등, 같은 회차 C-1 적재 무충돌, 과거 회차 snapshot 불변
- **P2b**: spec §3, §5, §6.
  - 병합 규칙과 수락 병합, 공식 키 보완(차수·역참조)
  - 고아 경로 대체, 추적 보충, 신호 확장·ack·이력 이벤트, 오류 코드 등록
  - 기존 테스트 중 `종료` 한정 신호·병합 거부를 단언하는 곳을 새 규칙으로 갱신한다(`test_opportunity_integrity.py:182-240`, `test_opportunity_tracking.py:409-455`).
- **P2c**: spec §4, §7, §8(백엔드).
  - SW=Y 자동 후보, 찾아보기, 사전규격 후보 조회(`name_matching.py` 사용)
  - 구역·사유·보류 기한·`q`, workload 키
  - `test_opportunity_sections.py:70-121` 갱신

**게이트(각 하위 단계)**:
- 해당 단계 테스트 파일과 경계 검사 `tests/app/test_module_boundaries.py`를 돌린다.
- PostgreSQL 제약·권한·migration은 `BIDOPS_TEST_POSTGRES_URL`로 `tests/app/test_db_migrations.py`·
  `test_revision_migrations.py`·`test_runtime_database_privileges.py`를 1회 돌린다.
- 로직 diff를 검수한다.

### P3 — Go/No-Go 분리 (opus, P2a 커밋에서 분기, P2b·P2c와 병렬)

spec §9 전체.
- ADR-0058 초안을 쓴다.
- migration 0028과 권한을 반영한다.
- 공고 조건 요약 서비스와 endpoint를 만든다.
- 결정 endpoint를 만든다(기존 검사 공유 함수 추출).
- basis 인식 currentness를 추가하고 decision_queue·workspace·projection 소비자를 수정한다.
- 문서 두 개(`bid-delta-contract-spec.md`, `deep-review-erd.md`)를 갱신한다.

**게이트**: `tests/deep_review/test_bid_delta*.py`, `test_decision_queues.py`, 권한·migration
테스트를 `BIDOPS_TEST_POSTGRES_URL`로 1회 돌리고 diff를 검수한다.

### P4 — 일일 실행 스크립트 (sonnet, P2a 이후)

- `scripts/run-daily-lifecycle.sh [--date YYYY-MM-DD]`:
  1. collector를 직접 호출해 발주계획 21일을 `lifecycle-YYYYMMDD-plans`로 수집한다.
  2. 사전규격·입찰공고 3일과 1468 표시를 `lifecycle-YYYYMMDD-notices`로 수집한다.
  3. 컨테이너로 복사한 뒤 `ingest.cli --run <plans> --collection` → `--run <notices> --collection`
     → `--tracked-backfill` → 첨부 취득 자격 갱신(`refresh_fetch_eligibility`) 순으로 실행한다.
  4. 단계마다 호출 수와 선별·제외 건수를 출력한다. 실패하면 중단하고 비0으로 종료한다.
  5. 기존 워크플로 스크립트를 source하지 않는다(dispatch 실행 방지). 공통 함수는
     `manual-workflow-common.sh`만 쓴다.
- `docs/operations.md`: cron 예시(설치하지 않음)·보관 용량·중단 기준을 적고 함정 1·2를 갱신한다.

**게이트**: `bash -n`, `--help` 출력, diff 확인. 실데이터 실행은 사용자 승인 후 1회만 한다.

### P5 — 프런트엔드 (F0 sonnet 선행 → F1~F4 opus 병렬)

- **F0**: P2·P3 계약을 타입·client·mock·fixture에 반영하고, 구역 기대값이 바뀐 두 spec을 갱신한다.
  이후 웨이브는 이 파일들을 수정하지 않는다(필요하면 보고서의 요청 사항으로 올린다).
- **F1**: spec §11.1(심층 검토 목록 제외, P1-2에서 끝남).
- **F2**: spec §8 패널·§11.2.
- **F3**: spec §11.3.
- **F4**: spec §11.4.
- Playwright 포트를 분리한다(`PW_PORT` F1 4311, F2 4312, F3 4313, F4 4314, `PW_OUT_DIR` 각각).

**게이트**:
- `npx tsc -b && npm run build`, `npm run test:contrast`를 돌린다.
- 각 WP의 spec 파일을 돌린다.
- `api-mock.ts`를 고쳤으므로 병합 전 통합 트리에서 `--project=app` 전체를 1회 돌린다.
- 1280×800·1440×900 캡처(데이터 로드 뒤)를 사용자에게 제시하고, 승인 후 픽셀 기준선을 교체한다
  (사유·영향 화면·승인자 기록).

### P6 — 문서 (sonnet + 관리자)

spec §12 목록을 갱신한다. ADR 색인 `docs/ADR.md`에 0058·0059 줄을 추가한다. `docs/tracking/status.md`에
구현 상태 한 줄을 적는다.

**게이트**: 문서 diff 확인만 한다(앱 빌드·화면 테스트 없음).

## 검증 (변경 경로만, 단계당 1회, 통과 테스트 재실행 금지)

| 요구 | 입력 | 기대 | 명령·위치 |
|---|---|---|---|
| 수집기 | 오타·새 optional 필드·1468 조회 실패 fixture | 정규화 값, 실패 시 `null` | `./run-tests.sh` |
| 대표 통합 | `tests/app/test_tracking_lifecycle_flow.py`(신설 1파일) 아래 시나리오 | 단계별 상태·감사·건수 | `cd web/backend && BIDOPS_TEST_POSTGRES_URL=<일회용 PG17> .venv/bin/python -m pytest tests/app/test_tracking_lifecycle_flow.py -q`(sandbox 해제) |
| migration·권한 | 빈 DB → 0028, 제약·append-only·역할 | 통과 | `tests/app/test_db_migrations.py`, `test_revision_migrations.py`, `test_deep_review_migrations.py`, `test_runtime_database_privileges.py` |
| API 계약 | 404/409/422/503, actor encoding, idempotency, details | 계약대로 | `tests/app/test_api_opportunities.py`, `test_workload_api.py`, 단계별 신설·갱신 파일 |
| 화면 | 변경 spec | 통과 | `tests/opportunities.spec.ts`, `dashboard.spec.ts`, `go-no-go.spec.ts`, `bid-delta.spec.ts`, `pre-specs.spec.ts`; 통합 트리 `--project=app` 1회 |
| 캡처 | 데이터 로드 뒤 두 폭 | 조치 필요 사유 칩, 신규 입찰공고, 대시보드 보류 패널, Go/No-Go 공고 조건, 사전규격 후보 구역 | 사용자 승인 |
| 실데이터(승인 시) | 로컬 compose DB, 1일 창 | 수집 대비 사유별 적재·제외, 후보 수, 호출 수 | `scripts/run-daily-lifecycle.sh --date …` |

대표 통합 시나리오(한 파일, 시간·타임존·null 조건을 처음부터 포함):

1. 발주계획 적재 → 사업기회 `계속 추적`
2. 같은 기관 SW=Y 사전규격(공고명 가운뎃점 변형, `demand_agency` 있음) 적재 → 발주계획 소유 후보 → 수락 병합(추적 유지, `사람 확인 병합`, unique index 통과)
3. 입찰공고 1차수(`bfSpecRgstNo`) 적재 → `bid_sw_prespec_reference` → 자동 연결·신호 → ack(추적 상태 불변)
4. 2차수(키 없음, 같은 `bid_no`) → `bid_same_notice_no`로 같은 사업기회
5. 무관 입찰공고와 1468 수의계약 → 제외 건수, 1468 경쟁입찰 → `신규 입찰공고` 구역
6. 사람 선택이 두 사업기회에 있는 공식 키 → `merge_confirmation` 후보, 공고는 고아가 아님
7. 색인에만 있는 입찰공고를 가리키는 사업기회를 나중에 `보류`로 저장 → 추적 보충 적재
8. 보류 저장 시각 +14일 경계(KST 자정 전후, 마이크로초) → `hold_overdue`, workload 건수, `조치 필요`
9. 공고 조건 근거 go 저장 → 3차수 도착 시 currentness `stale`, decision-queue에 표시
10. 같은 notices 회차에 C-1 full_run 적재 → 관측 snapshot 충돌 없음

## 위험과 대응

- **C-1 적재와의 snapshot 충돌**: P0 코드 확인과 시나리오 10으로 막는다. 깨지면 P2a에서 멈추고 보고한다.
- **자동 병합 규칙 변경**: 새 적재부터 적용하고 기존 데이터에 소급하지 않는다. ADR-0028·0030 개정 메모로 남긴다.
- **색인 누적**(하루 약 1,200행 × 재조회 창 중복): 작은 열만 담고 화면에 노출하지 않는다.
  보관 기간은 operations에 기록만 하고 자동 삭제는 만들지 않는다.
- **1468 표시 조회 실패**: `null`로 남아 ③ 사유로 적재되지 않는다. 다음 날 창에서 다시 조회한다.
