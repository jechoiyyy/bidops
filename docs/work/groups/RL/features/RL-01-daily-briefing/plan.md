# 평일 브리핑 생성·Slack 전송·반응 저장 — plan

- 기능 ID: `RL-01-daily-briefing`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-16

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/lifecycle/policies/briefing-policy-v1.json | 신규 | 규칙 파일(sha256 고정) |
| web/backend/app/lifecycle/models.py | 수정 | `Briefing`·`BriefingItem`·`BriefingReactionEvent` |
| web/backend/alembic/versions/0038_briefing.py | 신규 | 테이블 3개·CHECK·UNIQUE |
| scripts/runtime-privileges.sql, tests/app/test_runtime_database_privileges.py | 수정 | 권한 |
| web/backend/app/lifecycle/services/briefing_rules.py | 신규 | 회사 사실 읽기·제외·점수·정렬·tracked_change |
| web/backend/app/lifecycle/services/briefing.py | 신규 | 생성(멱등·rebuild)·반응 저장·조회 projection |
| web/backend/app/lifecycle/extensions.py, app/screening/(제공자), app/deep_review/(제공자) | 수정 | 확장점 `briefing_order_plan_candidates`(screening)·`company_facts_projection`(deep_review) 선언·제공 |
| web/backend/app/lifecycle/routers/briefings.py, schemas/briefings.py, main.py 라우터 순서 | 신규/수정 | REST 4개 |
| web/backend/app/lifecycle/services/workload.py, schemas/workload.py, tests/app/test_workload_api.py, web/frontend/src/lib/types.ts, tests/api-mock.ts | 수정 | `briefing_pending` 어휘·순서 동기 |
| web/backend/tests/app/boundary_map.py(TABLE_OWNER), tests/app/test_db_migrations.py(NEW_TABLES) | 수정 | 새 테이블 등록 |
| web/backend/app/core/slack.py, core/config.py, core/idempotency_fence.py(사설 fence 승격) | 신규/수정 | 전송기·설정·멱등 fence 공용화 |
| web/backend/app/lifecycle/cli.py, lifecycle/slack_worker.py | 신규 | `build-briefing`·`slack-worker` |
| web/backend/requirements.txt, requirements.lock, pyproject.toml | 수정 | `slack_sdk`(hash-pin lock 갱신) |
| docker-compose.yml, docker-compose.slack-egress.yml, env/slack.env.example | 수정/신규 | `slack-worker` 서비스(profile `slack`)·egress |
| scripts/run-daily-briefing.sh, web/backend/tests/app/test_daily_briefing_script.py(`test_daily_lifecycle_script.py` 패턴), tests/app/test_module_cli_entrypoints.py | 신규/수정 | 호스트 스크립트·dry-run 검사·CLI 진입점 표 |
| web/backend/tests/lifecycle/test_briefing_rules.py, test_briefing_service.py, tests/app/test_briefing_api.py, test_briefing_api_postgres.py, test_slack_transport.py, test_slack_worker.py | 신규 | T1~T9 |
| web/frontend/src/pages/BriefingPage.tsx, components/briefing/{BriefingTable,PeekPanel,ReactionButtons}.tsx, lib/api.ts, lib/apiErrors.ts, components/shell/Sidebar.tsx | 수정/신규 | 화면·건수 |
| web/frontend/tests/briefing.spec.ts, tests/api-mock.ts | 신규/수정 | T10 |
| docs/contracts.md, business-rules.md, operations.md, ARCHITECTURE.md, work/constitution/tech-stack.md, roadmap.md, ADR.md | 수정 | STEP-008 |

## 작업 순서

1. STEP-001 저장 모델·migration·권한·규칙 파일 [standard]
   - 목표: 테이블 3개와 CHECK·부분 UNIQUE(models·migration 동일 선언), 권한(DELETE 없음), 규칙 파일 sha256 로딩, 확장점 2개 선언.
   - 작업 대상: models.py, 0038_briefing.py(실제 head 기준 번호), runtime-privileges.sql, briefing-policy-v1.json, config.py, extensions.py.
   - 검증: `pytest tests/app/test_db_migrations.py tests/app/test_alembic_autogenerate.py tests/app/test_runtime_database_privileges.py`(PG).
2. STEP-002 결정적 규칙 엔진 [complex]
   - 목표: 회사 사실 projection(confirmed만, deep_review 제공자)·후보(stage별 필드 매핑)·제외·점수·`similar_project` 식·정렬·top_n·tracked_change(공고당 1행)를 순수 함수로 구현한다.
   - 작업 대상: briefing_rules.py, deep_review 제공자(`company_facts_projection`), screening 제공자(`briefing_order_plan_candidates`), `tests/app/test_module_boundaries.py` 통과.
   - 검증: T1, T2, T3. 실회사 projection의 실제 값 검증은 RL-00 병합 뒤 T12에서(그 전엔 가짜 projection).
3. STEP-003 생성 service·CLI [complex]
   - 목표: 멱등 생성(재생성 없음)·첫 실행 창·collection_incomplete 회차 조회(0/1/2행)·JSON 출력·exit 규칙·CLI 진입점 표.
   - 작업 대상: briefing.py(생성), lifecycle/cli.py, extension 등록.
   - 검증: T4, T5, `tests/app/test_ingest_cli_extensions.py` 패턴의 진입점 검사.
4. STEP-004 REST·반응·workload [complex]
   - 목표: 조회 projection(운영 정보 제외), 반응 PATCH 멱등·revision·이벤트, 추적 불변, `briefing_pending`.
   - 작업 대상: routers/briefings.py(로컬 오류 map), schemas, briefing.py(반응), core/idempotency_fence.py, workload.py·test_workload_api.py.
   - 검증: T6(PG 포함), T7.
5. STEP-005 Slack 전송기·미리보기·`--send` [complex]
   - 목표: allowlist·토큰·enabled·주말·0건 fail-closed, payload 허용 키만, 재전송 규칙.
   - 작업 대상: core/slack.py, slack-preview 라우트, cli `--send`, compose overlay, env example.
   - 검증: T8.
6. STEP-006 Socket Mode worker [complex]
   - 목표: block_actions → 반응 저장(멱등) → chat.update, 다른 action 무시, 3초 ack.
   - 작업 대상: lifecycle/slack_worker.py, cli `slack-worker`, compose 서비스.
   - 검증: T9.
7. STEP-007 화면 [standard]
   - 목표: ui-spec §4.1 표·탭·피크·키보드·토스트·상태 3종, 사이드바 건수.
   - 작업 대상: BriefingPage.tsx, briefing 컴포넌트 3개, api.ts, apiErrors.ts, Sidebar.tsx, api-mock.ts, briefing.spec.ts.
   - 검증: T10(`npm run build`, Playwright app 해당 spec + common-interactions).
8. STEP-008 호스트 스크립트·문서·시운전 [standard]
   - 목표: `run-daily-briefing.sh` dry-run, 문서 6종 갱신, bidops-local 감독 시운전 1회(실제 Slack 발송은 테스트 채널·사람 확인 뒤).
   - 작업 대상: scripts/run-daily-briefing.sh, docs 6개, validation-runs README.
   - 검증: T11, T12, `doctor _`.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 낮음 | standard | 스키마·권한 패턴 존재(0034~0037) |
| STEP-002 | M | 높음 | complex | 제외·점수·동점·창 경계 불변식 |
| STEP-003 | M | 높음 | complex | 멱등·rebuild·회차 경고 판정 |
| STEP-004 | M | 높음 | complex | 멱등 레코드·revision·추적 불변 |
| STEP-005 | S | 높음 | complex | 외부 전송 보호 장치 |
| STEP-006 | M | 높음 | complex | 외부 이벤트 수신·중복 전달 |
| STEP-007 | L | 중간 | standard | ui-spec·컴포넌트 규칙이 닫힘, 기존 훅 재사용 |
| STEP-008 | S | 낮음 | standard | 스크립트·문서 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 규칙이 `proposed` 사실을 읽어 추천이 부풀음 | T2 실패, 추천에 관심 분야 밖 키워드 | status 필터를 규칙 입구 한 곳에서 강제 |
| 발주계획 relevant 전부가 들어와 하루 검토량 폭증 | order_plan 항목 > 3건/일 | 반복∧유사 규칙 고정, excluded_counts로 관찰 |
| Slack 토큰 로그 노출 | 오류 문자열에 `xoxb-` | T8 토큰 문자열 검사, 전송기 외 토큰 접근 금지 |
| Socket Mode 중복 전달로 반응 2회 | 이벤트 2건·revision 2 | request_id=UUIDv5(trigger_id) 멱등 |
| 창 경계(전 브리핑 이후)에서 누락·중복 | 같은 공고가 이틀 연속 | `first_observed_at` 기준 + 이미 항목인 공고 제외 검사(T4) |
| lifecycle이 deep_review를 import | `test_module_boundaries.py` 실패 | 확장점만, 제공자는 deep_review |
| 반응이 추적 상태를 바꾸는 구현 유혹 | T6 불변 검사 실패 | service가 tracking 모듈을 import하지 않음 |
| 운영 cron을 문서화만 보고 설치 | crontab에 줄 생김 | STEP-008은 예시만, 설치는 사람 |

## 증명

- docs: `python3 scripts/feature_status.py doctor _`, 문서 6종 diff.
- tests: `cd web/backend && pytest tests/lifecycle/test_briefing_rules.py tests/lifecycle/test_briefing_service.py tests/app/test_briefing_api.py tests/app/test_slack_transport.py tests/app/test_slack_worker.py tests/app/test_ingest_cli_extensions.py`.
- postgres: 일회용 `postgres:17.11`로 `tests/app/test_db_migrations.py tests/app/test_runtime_database_privileges.py tests/app/test_briefing_api_postgres.py`.
- frontend: `npm run build && npx playwright test --project=app briefing.spec.ts common-interactions.spec.ts`.
- api_guard: T8·T9(allowlist·토큰·enabled·멱등) + 추적 불변(T6).
- real_data_run: 비적용(모델 없음). 단 STEP-008 감독 시운전 1회를 operations 증거로 기록.

## 결과

run `rla-20261016`, 기능 브랜치 `sdlc/rla-20261016-RL-01-daily-briefing`, 기준 df02b33(배치, RL-00 통합 후). 상세 `docs/work/_runs/rla-20261016/RL-01-daily-briefing.md`, 결정 `decisions.md`.

- 단계 8/8 done(STEP-001~007 위임, STEP-008 스크립트·문서 위임 + T12 리더 실행).
- 증명: tests 237 passed·52 skipped(PG 변형) exit 0; postgres(17.11) 274 passed + 리뷰 수정 뒤 영향 파일 32 passed(모듈 경계·권한·alembic drift 포함); frontend build·contrast 8/8·Playwright 45; T11 스크립트 43 passed; T12 bidops-local `bidops_rla` 감독 시운전(생성·REST·반응 왕복·화면, `--send` 제외).
- spec 개정(accept-spec): 지역 제외 보류 — 수집 `basis`는 판단 기준이라 참가 가능 지역 이름이 없음(독립 리뷰 BLOCKING, 사용자 결정). findings 2026-10-17.
- 회사 파일: 루트랩 v2(`excl:region.keywords=["대구","세종"]`) 발행·활성(revision 2).
- RL-00 회귀 수정: `tests/deep_review/test_decision_queues.py` strict dict 2건에 `company_attention`(provider_absent) 추가.
- 미증명: 실제 Slack 전송·Socket Mode 연결·3초 ack(토큰 없음), slack-worker 컨테이너 기동, worker 역할의 실제 PG 반응 경로 일부.
- backlog: decisions.md #8 항목, 반응 버튼 재누름=대기 토글·피크 제목 14px(4단 타이포) 확인, lock 정책 통일(notices.lock·plans.lock vs "공용 lock" 문구).
- 기존 실패(무관): `tests/app/test_daily_lifecycle_script.py` 18건(macOS BSD date·bash 3.2), frontend design-shell 2·admin-workspace-consistency 2·route-context 12.
