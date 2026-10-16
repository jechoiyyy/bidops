# 사업기회 레코드·활동 타임라인·상태 변화 알림 — plan

- 기능 ID: `RL-02-opportunity-timeline`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-16 (독립 검사 1차 반영)

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/lifecycle/models.py, alembic/versions/<head 다음>_opportunity_note.py, scripts/runtime-privileges.sql | 수정/신규 | `OpportunityNote`, 열 단위 UPDATE GRANT |
| web/backend/app/lifecycle/schemas/opportunity_activity.py, web/backend/tests/app/boundary_map.py | 신규/수정 | `ActivityItem`·응답 모델, lifecycle 공개 표면 allowlist |
| web/backend/app/lifecycle/services/opportunity_stages.py | 신규 | 단계 바·레코드 제목 규칙 |
| web/backend/app/lifecycle/services/opportunity_activity.py | 신규 | 피드 파생·정렬·커서·확장점 호출 |
| web/backend/app/lifecycle/services/opportunity_notes.py | 신규 | 노트 생성·완료·멱등 |
| web/backend/app/lifecycle/extensions.py | 수정 | hook `opportunity_activity_items` |
| web/backend/app/lifecycle/routers/opportunities.py, schemas/opportunities.py | 수정 | REST 3개·view 모델 |
| web/backend/app/lifecycle/policies/briefing-policy-v2.json, services/briefing_rules.py, core/config.py 기본 경로 | 신규/수정 | 마감 알림 |
| web/backend/tests/lifecycle/test_opportunity_stages.py, test_opportunity_activity.py, tests/app/test_opportunity_notes_api.py, tests/app/test_opportunity_notes_api_postgres.py, tests/lifecycle/test_briefing_rules.py | 신규/수정 | T1~T5 |
| web/frontend/src/pages/OpportunityRecordPage.tsx | 신규 | 레코드 셸·탭 라우팅 |
| web/frontend/src/components/record/{RecordHeader,AttributeList,StageBar,ActivityItem,ActivityFeed,Composer,NextActions}.tsx | 신규 | ui-spec §3 컴포넌트 |
| web/frontend/src/routes.tsx, components/shell/route-meta.ts("사업 추적" 4곳→"사업기회"), AppShell.tsx, components/shell/RecordTitleContext.tsx(신규) | 수정/신규 | 라우트·경로 이름·레코드 제목 context |
| web/frontend/src/lib/api.ts, apiErrors.ts, tests/api-mock.ts | 수정 | 클라이언트·mock |
| web/frontend/tests/opportunity-record.spec.ts, opportunities.spec.ts(22건 `?selected=` 이식), common-interactions.spec.ts | 신규/수정 | T6·T7 |
| docs/contracts.md, business-rules.md, 1016_rootlab-redefinition/ui-spec.md, ARCHITECTURE.md, ADR.md | 수정 | STEP-007 |

## 작업 순서

1. STEP-001 단계 바·레코드 제목 규칙 [complex]
   - 목표: 연결 조합별 6단계 state("그 밖" 규칙·`lifecycle_json.opening_at`)와 제목 선택을 순수 함수로.
   - 작업 대상: opportunity_stages.py, 테스트.
   - 검증: T1.
2. STEP-002 활동 피드 파생 [complex]
   - 목표: 11종 사건 파생·정렬·opaque 커서·hook 확장점, 시스템 사건 배제, 병합 행 200.
   - 작업 대상: opportunity_activity.py, schemas/opportunity_activity.py, extensions.py, boundary_map.py, 테스트.
   - 검증: T2, T3.
3. STEP-003 노트 테이블·REST [complex]
   - 목표: append-only 노트·다음 행동 완료(actor 헤더), `IdempotencyRecord` 멱등, 열 단위 UPDATE 권한.
   - 작업 대상: models.py, migration(<head 다음>), runtime-privileges.sql, opportunity_notes.py, routers/schemas.
   - 검증: T4(PG 포함), `test_runtime_database_privileges.py`.
4. STEP-004 활동 REST [standard]
   - 목표: `GET …/activity` 응답 조립(stages+items), 404·merged 처리.
   - 작업 대상: routers/opportunities.py, schemas.
   - 검증: T2의 API 부분(기존 `test_api_opportunities.py` 패턴).
5. STEP-005 마감 알림(규칙 파일 v2) [standard]
   - 목표: D-3·D-1 사유(입찰공고만), `method` 필드 추가, 공고당 1행 합치기, 하루 1회, Slack 묶음 포함. **RL-01 구현이 끝난 뒤에만 착수**(큐 depends_on RL-01); RL-01 전에 RL-02를 시작해야 하면 이 단계와 `briefing_reacted` kind만 뒤 묶음으로 미룬다.
   - 작업 대상: briefing-policy-v2.json, briefing_rules.py, config 기본 경로, RL-01 테스트 확장.
   - 검증: T5.
6. STEP-006 레코드 화면 [standard]
   - 목표: 리다이렉트·헤더·좌측·단계 바·작성기·피드·탭 빈 상태·`RecordTitleContext`·경로 이름("사업기회" 4곳)·병합 리다이렉트, 기존 대화상자 연결, opportunities.spec 22건 `?selected=` 이식·기대값 갱신.
   - 작업 대상: OpportunityRecordPage.tsx, record 컴포넌트 7개, routes/route-meta/TopBar, api.ts, mock, spec.
   - 검증: T6, T7(`npm run build`, Playwright app).
7. STEP-007 문서 [standard]
   - 목표: contracts·business-rules·ui-spec §4.3·ARCHITECTURE·ADR 갱신.
   - 작업 대상: 문서 5개.
   - 검증: `doctor _`, diff.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | S | 높음 | complex | 단계 판정 엣지(마감 null·개찰 키 유무·병합) |
| STEP-002 | M | 높음 | complex | 다중 원본 파생·첫 관측 제외·커서 |
| STEP-003 | M | 높음 | complex | append-only·멱등·권한 |
| STEP-004 | S | 중간 | standard | 기존 라우터 패턴 |
| STEP-005 | S | 중간 | standard | RL-01 규칙 함수 확장 |
| STEP-006 | L | 중간 | standard | ui-spec·컴포넌트 규칙이 닫힘, 기존 대화상자 재사용 |
| STEP-007 | S | 낮음 | standard | 문서 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 피드가 시스템 사건(회차·변환)을 섞음 | 금지 문자열 검사 실패 | kind enum 밖 원본 금지, T2 배제 검사 |
| 개찰·계약을 마감으로 추정 | `unknown`이 아닌 state | T1 고정 |
| 기존 상세의 추적 조작 회귀 | opportunities.spec 실패 | 대화상자 컴포넌트 그대로 재사용, T7 |
| 노트 본문이 RL-03/04 입력에 들어감 | 전송 payload에 note | RL-03·04 spec 상속 규칙 + payload 허용 키 검사 |
| 레코드 제목 로딩 전 경로 깜빡임 | 상단바 `#id`→제목 전환 | 로딩 중 `#id` 고정, 전환 1회 |
| RL-01 미구현 상태에서 착수 | `briefing_reaction_event`·규칙 파일 없음 | 큐 depends_on RL-01; 먼저 착수해야 하면 `briefing_reacted`·STEP-005를 뒤 묶음으로 분리 |

## 증명

- docs: `doctor _`, 문서 diff.
- tests: `pytest tests/lifecycle/test_opportunity_stages.py tests/lifecycle/test_opportunity_activity.py tests/app/test_opportunity_notes_api.py tests/lifecycle/test_briefing_rules.py`.
- postgres: 일회용 PG로 `tests/app/test_opportunity_notes_api_postgres.py tests/app/test_db_migrations.py tests/app/test_runtime_database_privileges.py`.
- frontend: `npm run build && npx playwright test --project=app opportunity-record.spec.ts opportunities.spec.ts common-interactions.spec.ts`.
- api_guard: Slack은 RL-01 전송기 재사용(변경 없음) → 비적용; 노트 외부 전송 없음 확인(T4 범위).
- real_data_run: 비적용.

## 결과

구현 후 작성한다.
