# 사업기회 레코드·활동 타임라인·상태 변화 알림 — spec

- 기능 ID: `RL-02-opportunity-timeline`
- 근거: [intent.md](./intent.md), RL-01 spec(§tracked_change·Slack·규칙 파일), contracts.md "사업기회와 추적"·"사업기회 구역·사유·보류 기한", business-rules.md "입찰공고 전환"·"조치 필요·신규 입찰공고 구역", ui-spec §1.3·§3·§4.3
- 작성일: 2026-10-16 (같은 날 독립 검사 1차 18건·2차 13건 반영; 3차 검사는 돌리지 않음)

## 큰 틀 문서와의 관계

- 인용하는 절: contracts.md `GET /api/opportunities/{id}`(links 전체)·`GET …/tracking-decisions`(결정·recheck 이력)·`PATCH …/tracking-status`·`GET /api/notices/{pk}/history`·`/related`; business-rules "입찰공고 전환"(권위 연결·확정); ADR-0067 마감 임박 창(링크 단위 `deadline_at`); ui-spec §3(RecordHeader·AttributeList·StageBar·ActivityItem·작성기·체크 항목)·§4.3; RL-01 spec `tracked_change`·Slack 메시지·`briefing-policy`.
- 이 문서에서 새로 확정하는 항목: 활동 피드 항목 enum과 파생 규칙, 단계 바 6단계 판정 규칙, 노트 테이블·REST, 마감 알림 규칙(규칙 파일 v2), 레코드 화면 라우트·탭·빈 상태, 상단 경로 이름.
- 큰 틀 문서 수정이 필요한 항목(STEP-007): contracts.md REST 3개·`opportunity_note`·`briefing-policy-v2`, business-rules.md "사업기회 레코드 단계 바·활동 피드" 절, ui-spec §4.3(제출 서류 블록 후속 주석·탭 빈 상태), ARCHITECTURE §5.1a 한 줄, ADR.md 한 줄.

## 입력·출력 계약

### 레코드 라우트 (ui-spec §1.4)

- `/opportunities/:id` → `/opportunities/:id/activity`(replace). 탭 경로 `activity | verdict | proposal | documents | source | similar`. 대체 대상은 **라우트 페이지 `OpportunityDetailPage`만**이다. 목록 화면 우측 pane의 `OpportunityDetail`(React state `intent`로 열림, `?selected=<id>` 딥링크 지원)은 그대로 두며 두 상세 UI의 공존이 의도다(목록은 빠른 조작 — 3단계 연결 현황·찾아보기·후보 대화상자·확인 항목·병합 처리, 레코드는 전체 이력). 그래서 기존 `opportunities.spec.ts`의 단독 라우트 테스트 22건(연결 현황·찾아보기·후보·확인 항목·병합 거절)은 **`/opportunities?selected=<id>`로 이식**하고 레코드 페이지에는 그 표면을 만들지 않는다(T7 범위). 기존 추적 대화상자(`TrackingStatusDialog`·`TrackingResetControl`·`RecheckAcknowledgement`·`CandidateLinkDialog`)는 ⋯ 메뉴·활동 항목에서 그대로 연다.
- 용어: "권위 연결" = contracts "마감 임박 창" 정의(`official`·`확정` 또는 `candidate`·`사람 확인 완료`·`accepted`). 단계 구분: 발주계획 = `stage=order_plan`; 사전규격 = `stage=notice` ∧ `Notice.source_type ∈ PRE_SPEC_SOURCE_TYPES`(`services/opportunity_candidates.py` 공개 상수); 입찰공고 = `stage=notice` ∧ `source_type='bid_notice'`.
- 상단 경로의 첫 칸 "사업기회"는 route-meta의 "사업 추적" 라벨 4곳(`opportunities.title`, `bidDelta.ancestors`, deep-review `from: opportunities` ancestors, notices 계열 ancestors)을 "사업기회"로 바꿔 얻는다(이 기능이 소유; `opportunities.spec.ts`·`common-interactions.spec.ts`의 "사업 추적" 기대값 갱신은 T7에 포함).
- 상단 경로: "사업기회 / <레코드 제목>". 레코드 제목 = 권위 연결 중 가장 뒤 단계(입찰공고 > 사전규격 > 발주계획)의 `title`; 없으면 `#<id>`. route-meta의 `record.label`은 동기 함수이고 셸→TopBar는 props뿐이므로 **`RecordTitleContext`**(프런트 context, 값 `{opportunityId, title}|null`)를 신설한다: 레코드 페이지가 activity 응답 `title`을 넣고 `AppShell`이 현재 match의 `opportunityId`와 같을 때만 record crumb 라벨을 덮어쓴다(로딩 전·불일치는 `#<id>`).

### 레코드 헤더 (RecordHeader)

- 아이콘: 발주기관 머리글자(teal 바탕). 제목: 위 레코드 제목(`#<id>` 대기 중에는 그대로). pill 4개 순서 고정: 단계(`발주계획|사전규격|입찰공고`, 현재 단계 = 제목을 준 연결의 단계), 마감(입찰공고가 있으면 `D-n`·지난 마감은 `마감 지남`; 사전규격만 있으면 라벨 `의견 마감 D-n`; 둘 다 없으면 pill 생략), 판정(RL-03 전까지 `분석 대기`; 발주계획만 있으면 `연차 추적`), 추적 상태(`미선택|계속 추적|보류|종료`).
- 액션: 주 버튼 "판정 보기"(verdict 탭, RL-03 전에는 비활성 + title "RL-03에서 열립니다"), "제안서 초안"(비활성, RL-04), ⋯(추적 상태 변경 · 추적 되돌리기 · 신호 확인 · 후보 연결 — 기존 대화상자).

### 좌측 정보 (AttributeList, 280px)

속성 8개 순서 고정·값 없으면 "미공개": 발주기관(`agency`), 사업기간(공고 테이블에 기간 열이 없으므로 **항상 "미공개"**; RL-03 추출 결과가 생기면 후속에서 채움), 금액(`estimated_price` → 없으면 `budget`, 억/천만 단위 한글 표기), 계약방법(`method`), 공동수급(`qualification_flags_json.joint_contract_method` 방식명 문자열 그대로, 없으면 미공개 — 허용/불허 불리언은 없다), 입찰 마감(입찰공고 `deadline_at` 일시; 사전규격만이면 "미공개" — 의견 마감은 헤더 pill에만), 담당(마지막 반응·결정의 actor 이름, 없으면 "미지정"), 추적(추적 상태 + 선택자). 발주계획만 있는 레코드는 금액=`budget_amount`, 사업기간=`planned_order_month` "n월 발주 예정".
- 다음 행동: `kind=action`·`done_at IS NULL` 노트 목록(체크 + 담당 머리글자), 최대 5 + "모두 보기"(피드 필터).
- 제출 서류 블록: 비활성 안내 1줄 "제출 서류 체크는 준비 중입니다"(후속 기능). 진행 막대·숫자는 그리지 않는다.

### 단계 바 (StageBar) — 6단계 판정 규칙

| 단계 | `done` | `current` | `upcoming_deadline` | `unknown` |
|---|---|---|---|---|
| 발주계획 | 권위 연결 `stage=order_plan` 존재 | 그것이 가장 뒤 단계 | — | — |
| 사전규격 | 권위 연결 사전규격 존재 | 가장 뒤 단계 | — | — |
| 입찰공고 | 권위 연결 입찰공고 존재 | 가장 뒤 단계이고 마감 전 | — | — |
| 마감 | 입찰공고 `deadline_at < now` | — | 입찰공고 `deadline_at ≥ now` | 입찰공고 없음 또는 `deadline_at` null |
| 개찰 | 입찰공고 `lifecycle_json.opening_at`(ISO, 키 없음/null 가능)이 있고 지남 | — | 있고 미래 | 키 없음·null, 또는 입찰공고 없음 |
| 계약 | 데이터 없음 → 항상 `unknown` | — | — | 항상 |

그 밖(어느 칸에도 안 맞는 경우): 그 단계보다 뒤 단계가 `done|current`이면 `unknown`(건너뛴 단계는 추정하지 않음), 아니면 `pending`. 예: 발주계획만 있으면 사전규격·입찰공고 `pending`, 마감·개찰 `unknown`; 사전규격 없이 입찰공고가 있으면 사전규격 `unknown`. `unknown`은 회색 테두리 + 라벨 뒤 "미확인". 응답 필드 `stages: [{key, state: done|current|upcoming_deadline|pending|unknown, at: ts|null, link_id: int|null}]` 6개 고정 순서. `link_id`는 그 단계 대표 권위 연결 id(마감·개찰은 입찰공고 대표, 없거나 계약이면 `null`)이고 화면은 대표 연결을 이 id로만 찾는다(2026-10-17 결정 #21). `raw_source`는 파일 경로 문자열이라 읽지 않는다.

### 활동 피드 `GET /api/opportunities/{id}/activity?kinds=&limit=&before=`

- 응답 `{schema_version:"bidops.opportunity-activity.v1", opportunity_id, merged_into_opportunity_id: int|null, title, stages[], items: ActivityItem[], next_before: string|null}`. 병합된 사업기회도 200이며 화면이 `merged_into_opportunity_id`로 리다이렉트한다(409 `opportunity_merged`는 쓰기 REST만). `limit` 1..200(기본 50), `before`는 opaque 커서 `"<at ISO>|<item_id>"`(동률 경계 보존), `kinds`는 아래 enum csv 필터.
- `ActivityItem = {item_id: string, kind, at: ts, actor: string|null, title: string, detail: string|null, link: {label, path}|null, status_pill: string|null}`. `item_id`는 `"<kind>:<원본 PK>"`(결정적, 저장 안 함). 정렬 `at` 내림, 동률 `item_id` 내림. 화면은 `at`을 분 단위까지만 표시한다(관측 `at`은 회차 `generated_at`이므로 초 단위 노출 금지).
- `kind` enum 전체와 파생 원본:

| kind | 원본 | title 규칙 | link |
|---|---|---|---|
| `order_plan_found` | 권위 연결 `stage=order_plan` `created_at` | "발주계획 발견 · <기관>" | `/order-plans/<pk>` |
| `pre_spec_opened` | 권위 연결 사전규격 `created_at` | "사전규격 공개" | `/pre-specs/<notice_pk>` |
| `bid_posted` | 권위 연결 입찰공고 `created_at` | "입찰공고 게시" | 공고 외부 URL(`Notice.url`)을 새 창으로; 내부 입찰공고 상세 라우트는 없으므로 만들지 않는다 |
| `notice_corrected` | `NoticeObservation.changed_fields_json ∩ {deadline_at,title,budget,estimated_price,method} ≠ ∅`(첫 관측 `is_new` 제외; `method`는 피드에만 있고 RL-01 알림 필드 집합에는 없다 — 규칙 파일 v2에서 `tracked_change_fields`에 `method`를 더해 일치시킨다) | "정정 · <바뀐 필드 한글>" | 사전규격이면 `/pre-specs/<pk>#ps-record-history`, 입찰공고면 외부 URL |
| `tracking_decided` | 감사 `opportunity.tracking_status.changed`(`Opportunity.tracking_status` 경로만; 데모 회사별 `CompanyTrackingEvent`는 대상 아님) | "<이름>이 <상태>로 결정"; 새 상태가 `미선택`이면 "<이름>이 추적 되돌림" + `detail`=사유 | — |
| `recheck_signal` | 감사 `opportunity.recheck_signal.created/acknowledged` | "재확인 신호" / "<이름>이 신호 확인" | — |
| `link_reviewed` | `OpportunityLink.human_decision` 있는 후보 | "<이름>이 연결 후보 <수락/거절>" | — |
| `briefing_reacted` | `briefing_reaction_event`(RL-01) `new ≠ 대기` | "<이름>이 <반응>" (`status_pill`=반응) | `/briefing?date=<briefing_date>&selected=<item_id>`(RL-01 화면 계약에 `selected=<item_id>` 추가 — 이 기능이 RL-01 spec 화면 절에 한 줄 더한다) |
| `note_added` | `opportunity_note kind=note` | 본문 첫 줄(≤120자) | — |
| `action_added` / `action_done` | `opportunity_note kind=action` `created_at` / `done_at` | "다음 행동: <본문>" / "<이름>이 완료: <본문>" | — |
| `verdict_completed` | RL-03 확장점(현재 없음 → 항목 0) | — | verdict 탭 |
| `draft_prepared` | RL-04 확장점(현재 없음 → 항목 0) | — | proposal 탭 |

lifecycle이 다른 모듈 사건을 받을 확장점 `opportunity_activity_items(session, opportunity_id) -> list[ActivityItem]`을 **hook 방식**(owner별 등록, 복수 허용, 등록 순서로 합친 뒤 공통 정렬)으로 선언한다(RL-03·04가 제공). `ActivityItem` 타입은 `lifecycle/schemas/opportunity_activity.py`에 두고 `tests/app/boundary_map.py`의 lifecycle 공개 표면 allowlist에 추가해(또는 `schemas/__init__.py` 재수출) 제공자가 import한다. 시스템 처리(수집 회차·변환·호출·정책)는 어떤 kind에도 넣지 않는다.

### 노트·다음 행동

- `opportunity_note` {id UUID PK, opportunity_id INT FK, kind `note|action`, body TEXT(1..2000, trim), actor TEXT NOT NULL, owner TEXT NOT NULL(다음 행동 담당 이름, 비면 actor), created_at, done_at TS NULL, done_by TEXT NULL}. CHECK `kind IN ('note','action')`, `(done_at IS NULL) = (done_by IS NULL)`. 본문은 수정·삭제 없음(append-only). `done_at`·`done_by`만 1회 채울 수 있다.
- 멱등은 기존 관례 core `IdempotencyRecord`(`operation="opportunity_note.create"`/`"opportunity_note.done"`, `aggregate_type="opportunity"`, `aggregate_id=<id>`, `claimed_name=actor`, `request_id=body`)로 한다: 같은 key·같은 hash는 저장 snapshot 재생(200), 다른 hash는 409 `idempotency_conflict`. 테이블 UNIQUE(request_id)는 두지 않는다(actor가 범위 밖이면 남의 노트를 돌려줌).
- `POST /api/opportunities/{id}/notes` actor 헤더; body `{kind, body, owner?: string, request_id}` → 201 `NoteView={note_id, kind, body, actor, owner, created_at, done_at, done_by}`. 404 `opportunity_not_found`, 409 `opportunity_merged`·`idempotency_conflict`, 422 body.
- `PATCH /api/opportunities/{id}/notes/{note_id}/done` actor 헤더; body `{request_id}` → 200 `NoteView`(`done_by`=actor); 이미 완료면 200 그대로(멱등); `kind=note`면 409 `note_not_action`; 400 `actor_name_required|actor_name_invalid`. `owner`는 NOT NULL(서버가 비면 actor로 채움).
- 노트 본문은 어떤 모델 입력에도 넣지 않는다(RL-03·04 spec이 이 규칙을 상속).

### 마감 알림 (RL-01 확장)

- 규칙 파일 `briefing-policy-v2.json`: v1 전체 + `deadline_reminder_days:[3,1]` + `tracked_change_fields`에 `method` 추가. RL-01 `tracked_change` 계산에 사유 `deadline_reminder`를 더한다: 추적 상태 `계속 추적|보류`, 권위 연결 **입찰공고**(`source_type='bid_notice'`; 사전규격 의견 마감은 대상 아님) `deadline_at`의 KST 날짜 − 브리핑 날짜 ∈ `deadline_reminder_days`. RL-01 규칙대로 (브리핑, 공고)당 1행이며 같은 날 정정이 있으면 그 행의 `change_fields`에 `deadline_reminder`를 합치고 `verdict_display`는 "재검토 중", 마감 사유만이면 "마감 임박"(RL-01 enum에 이미 있음). 브리핑 날짜 UNIQUE로 하루 1회다.
- Slack: RL-01 추적 변화 메시지에 같은 형식 1행으로 들어간다(별도 메시지 없음). 정정은 RL-01 규칙 그대로.
- `BriefingItemView.change_fields` 값 집합에 `deadline_reminder`를 추가한다(RL-01 계약 추가형).

### 화면 (ui-spec §4.3)

- 중앙: StageBar → 작성기("노트 남기기…" TextArea + 버튼 "노트"·"다음 행동", 다음 행동은 담당 입력 선택) → 활동 목록(ActivityItem: 26px 원형 머리글자 또는 사건 아이콘, 본문 이름 600 + pill, 보조 시각 "오늘 08:41" / "10월 14일"). 필터 칩: 전체·사람·사업 사건(클라이언트, `kinds`).
- 탭 빈 상태 문장: 판정 "판정은 분석이 끝나면 여기에 보입니다", 제안서 "제안서 초안은 판정 뒤 만들 수 있습니다", 서류 "제출 서류 체크는 준비 중입니다", 원문 "원문은 공고 상세에서 봅니다"(+ 링크), 비슷한 공고 = 가장 뒤 단계 공고 pk로 `GET /api/notices/{pk}/related` 목록(기존); 공고가 없으면(발주계획만) 빈 상태 "공고가 연결되면 비슷한 공고를 찾습니다".
- 금지 문자열 검사: DOM에 `run_id`·회차 디렉터리명·정책 id·모델명·`unmeasured_reference`가 없어야 한다.
- 키보드: 탭 이동 ←→, 작성기 ⌘Enter 저장. 기존 추적 대화상자 접근성 그대로.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| `briefing-policy-v2.json` `deadline_reminder_days` | int[] | [3,1] | 1..30, 중복 없음 | `tunable`, 새 버전 파일 |
| `activity` `limit` | int | 50 | 1..200 | 질의 인자 |

## 상태 값과 실패 처리

- 단계 state `done|current|upcoming_deadline|pending|unknown`; 활동 kind 13값(위 표); 노트 kind `note|action`.
- 오류 code 추가: `note_not_action`(라우터 로컬 map + `apiErrors.ts`), (기존 재사용) `opportunity_not_found`·`opportunity_merged`·`idempotency_conflict`. GET은 병합 행도 200(`merged_into_opportunity_id`)이고 화면이 리다이렉트, POST/PATCH만 409 `opportunity_merged`.

## 저장

- `opportunity_note` 위 정의. migration 번호는 구현 시점의 단일 head 다음. 권한(`runtime-privileges.sql`, 열 단위 GRANT 선례): web `SELECT, INSERT`, `UPDATE (done_at, done_by)`만; worker SELECT; ro_backup SELECT; DELETE 없음. 본문 UPDATE는 DB가 거부한다(T4는 DB 거부 검사).

## 인터페이스(CLI·UI·API)

위 REST 3개와 라우트. 외부 호출은 RL-01 Slack 전송기만(보호 장치 동일).

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 피드를 저장하지 않고 파생 | 원본(연결·관측·감사·반응)이 이미 append-only; 중복 저장은 불일치 원인 | 이벤트 테이블 |
| 개찰·계약 `unknown` | 데이터 없음, 추정 금지(강제 게이트) | 마감 기준 추정 |
| 마감 알림을 RL-01 묶음에 통합 | ux-review 결정 4 "하루 1회 본문 + 예외 알림(정정·D-3·D-1)" | 별도 알림 worker |
| 제출 서류 블록 후속 | 체크리스트 계약·저장 없음; RL-04 서류 목록이 입력 | 임시 하드코딩 27종 |
| 노트는 모델 입력 금지 | 사람 메모의 외부 전송 승인 범위 밖 | 노트 포함 |
| 레코드 제목 = 가장 뒤 단계 제목 | ui-spec §1.3 "사업기회 / 공고명" | `#id` 유지 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | 연결 조합(발주계획만 / 사전규격+공고 / 공고 마감 지남 / 개찰 키 유무) | 단계 6개 state 규칙 일치, 제목·현재 단계 선택 | 단위 |
| T2 | 피드 파생: 관측 변경(첫 관측 제외), 추적 결정, 신호, 후보 수락, 반응, 노트·행동·완료 | kind·title·actor·정렬·커서 페이지, 시스템 사건 0 | 단위 |
| T3 | 확장점 제공자 없음/있음 | 항목 0 / 합쳐서 정렬 | 단위 |
| T4 | 노트 POST 멱등(같은 actor 재생·다른 actor 같은 request_id는 별개)·409, done 1회·멱등·`note_not_action`·actor 400, 본문 UPDATE 시도(app role; `test_document_segments_postgres.py`의 역할 생성+privileges 적용 선례) | 계약대로, DB 권한 거부로 본문 불변 | 통합(PostgreSQL, 별도 `_postgres.py`) |
| T5 | 마감 D-3/D-1 추적 중·미추적·보류·종료, 사전규격 의견 마감(대상 아님), 같은 날 정정+마감 동시 | 추적 중·보류·입찰공고만, 공고당 1행에 사유 합침·표시 "재검토 중", 하루 1회 | 단위(RL-01 규칙 테스트 확장) |
| T6 | 화면: 리다이렉트·헤더 pill·속성 "미공개"·단계 바·작성기·체크·탭 빈 상태·금지 문자열, 1280·1440 | Playwright app 통과 | 프런트 |
| T7 | 기존 `opportunities.spec.ts` 단독 라우트 22건을 `/opportunities?selected=<id>`로 이식, "사업 추적"→"사업기회" 기대값 갱신(opportunities·common-interactions) | 이식 뒤 전부 통과, 추적 대화상자·되돌리기 회귀 없음 | 프런트 |

## 컨벤션 반영 항목

- `bidops.opportunity-activity.v1`·kind enum·stage state enum·opaque 커서·`opportunity_note`(열 단위 UPDATE 권한)·`note_not_action`·`briefing-policy-v2`·hook 확장점 `opportunity_activity_items`·`RecordTitleContext`·route-meta `opportunities.title="사업기회"` → contracts.md·business-rules.md·ui-spec §1.3.
