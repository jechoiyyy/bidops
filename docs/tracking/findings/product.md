# 화면·수집·회귀 검증 문제 기록

[전체 색인](../findings.md). 미해결 또는 일부 조치 뒤 검증이 남은 항목이다. 제목의 날짜는 마지막 관측·기록 시점이며 2026-10-21에 다시 재현했다는 뜻이 아니다. 과거 기능명·정책·환경을 현재에 적용하기 전에 소스와 마지막 실행 증거를 확인한다.

## 데모 기준 `c50ed55`의 화면 스위트에 기존 실패 3종이 있다 (2026-10-12, 미해결)

- 재현: 데모 브랜치 `demo/local-20261009` @ `c50ed55`의 빌드를 macOS(Apple Silicon)의 Playwright chromium v1234로 실행했다. 이 Mac에서는 `vite preview`가 IPv6 localhost에만 바인딩되므로, preview를 `--host 127.0.0.1`로 직접 띄우고 `PW_PORT`로 재사용했다.
  - `prespec-list-work.spec.ts:678`·`:734`(LS-06): 담당자 이름만 입력한 상태에서 필터·쪽 이동을 하면 이탈 확인 창을 기대하지만, 창이 뜨지 않는다. 현재 `TrackingDecisionControl`은 사유가 있을 때만 dirty로 본다. 검사의 기대와 제품 규칙이 어긋나 있는 것으로 보인다.
  - `design-shell.spec.ts:228` "native compact 셸…": 드롭다운에서 선택한 항목의 중심이 trigger 중심과 5~7px 어긋나 허용치 4px를 넘는다. 두 폭 모두 실패한다. native select의 OS 기하에 의존하는 것으로 보인다.
  - `mock-review-prototype.spec.ts`: `src/mock-review/scenario`가 `.md`를 import해 Playwright 수집 단계에서 SyntaxError가 난다. 이 때문에 파일을 지정하지 않은 `test:screens` 전체 실행이 시작되지 않는다.
  - 증거는 DEMO-04 run의 `docs/work/_runs/demo04-20261012/baseline-design-shell.log`·`baseline-admin-listwork.log`·`feature-final-screens.log`에 있다. 같은 run에서 `admin-workspace-consistency.spec.ts:23` 2건도 실패했는데, 이는 아래 2026-09-16 항목에 이미 있다.
- 영향: 화면 게이트(`test:screens`)를 그대로 돌리면 수집 오류로 멈추고, spec을 나열해 돌려도 6건이 항상 실패한다. 그래서 새 회귀를 기존 실패와 가르려면 기준 빌드와 대조해야 한다.
- 지금 해결하지 않은 이유: 셋 다 DEMO-04가 바꾸지 않은 파일이나 규칙에 걸려 있다. 특히 LS-06은 검사와 제품 중 무엇이 맞는지 판단이 필요하다.
- 후속: LS-06은 dirty 규칙(담당자만 입력한 경우도 dirty로 볼지)을 정한 뒤 검사나 제품을 맞춘다. `mock-review-prototype`은 `.md` import를 Playwright가 읽을 수 있는 방식으로 바꾸거나 `testIgnore`에 넣는다. design-shell 기하 허용치는 Linux CI 기준값과 대조한다.

## 심층 보고서 직접 진입 시 공통 상세 레이아웃 CSS가 로드되지 않는다 (2026-09-22, 미해결)

- 재현: 기존 `BIDOPS_MOCK_API=1` 개발 서버의 `/deep-reviews/fixture-review`를 새 브라우저로
  연다. 1280×800·1440×900에서 `.deep-review-report-grid`의 computed display가 `block`이다.
  오른쪽 범위·편집·이력 구역이 본문 아래로 내려간다. 합성 fixture 화면에서 확인했다.
- 원인: `DeepReviewPage.tsx`가 사용하는 `detail-skeleton.css`는 lazy route인
  `PreSpecDetailPage.tsx`에서만 import한다. 심층 페이지는 자기 CSS만 import한다.
- 현재 범위와 후속: 화면 점검만 수행했고 production build·배포는 하지 않았다.
  공통 스타일을 실제 소비자가 로드하게 하고 직접 진입·새로고침·SPA 이동을 함께 검증한다.
  별도로 근거 버튼은 선택 상태만 바꾸므로, 본문 아래 원문 뷰어로 이동하거나 인접해서
  확인하는 동작이 필요하다. 기존 합성 fixture에서 클릭 뒤 뷰어가 화면 밖에 남음을 확인했다.
## `test_auto_deep_review_start.py` 11건이 `bda1288` 이후 실패한다 (2026-09-22, 미해결)

- 재현 조건: `web/backend`에서 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false pytest tests/app/test_auto_deep_review_start.py -q` → 11 failed / 3 passed.
  `92c7f32`(09-21 배포 코드)에서는 14 passed. `bda1288`(사전규격 개요·예비 적합성 통합)에서 처음 깨진다.
- 증상: `AutoDeepReviewOutcome(created=False, reason='overview_not_completed')` — 개요 run이 완료로 간주되는 조건이 예비 판단
  통합으로 바뀌었는데(`display_assessment`·`assessment_status` 등) 자동 심층 검토 시작 테스트의 fixture가 그 조건을 갖추지 않는다.
- 영향: 자동 심층 검토 시작 경로의 회귀를 이 파일이 더는 막지 못한다. 실무 화면 고도화 묶음 ③·④ 게이트(백엔드 전체 2454 passed)에서
  발견했고 그 변경과 무관하다(clean `bda1288`에서 재현).
- 지금 해결하지 않는 이유: `bda1288`의 작업(다른 세션, `docs/0921_prespec-preliminary-assessment/`) 몫이다. 제품 결함(예비 판단이 없으면
  자동 시작이 막히는 것이 의도인지)인지 fixture 결함인지 그 작업이 가려야 한다.
- 후속 방향: 그 작업에서 개요 완료 판정의 새 조건을 명세로 못 박고 fixture를 맞추거나, 자동 시작이 예비 판단과 무관해야 하면 게이트를 되돌린다.

## 심층 검토 화면에 8자 축약 식별자 두 곳이 남아 있다 (2026-09-21, 미해결)

- 재현 조건: `/deep-reviews/:id` 상단 머리의 `보고서 식별자 · {reviewId 앞 8자}`(`DeepReviewPage.tsx`)와 주장 표의 근거 칩
  `근거 · {evidence id 앞 8자}`(`EvidenceButton`).
- 영향: ADR-0066 결정 2("식별자·해시는 줄이지 않는다")와 어긋난다. 전문은 같은 화면의 접힌 `기술 정보`에서 읽을 수 있어 대조 자체는 가능하다.
- 지금 해결하지 않는 이유: 표 안 칩을 전문으로 바꾸면 1280px에서 넘치고, 칩의 역할(근거로 이동)을 다른 표기(순번 등)로 바꾸는 것은 시안 M4의 승인 범위 밖이다.
- 후속 방향: 칩을 `근거 1`·`근거 2` 같은 화면 내 순번으로 바꾸고 식별자는 접힌 곳에만 두는 안을 다음 심층 검토 화면 시안에서 다룬다.

## 프런트 fixture의 심층 검토 오류 코드가 백엔드 계약에 없는 값이다 (2026-09-21, 미해결)

- 재현 조건: `web/frontend/tests/api-mock.ts`의 분석 회차 fixture가 `last_error_code: "model_timeout"`을 쓴다. 백엔드가 내는 값은 `timeout`이다
  (`web/backend/app/core/model_client.py`의 오류 분류, `app/deep_review/services/deep_reviews.py`의 `_fail_claim`).
- 영향: 가짜가 실제 계약과 다른 값을 품고 있어, 이 값에 기대는 화면 문장(`components/deep-review/attemptErrors.ts`)이 운영에서 오지 않는 코드까지 매핑하고 있다.
- 후속 방향: 실무 화면 고도화 패키지 F0에서 fixture를 `timeout`으로 맞추고 사전에서 `model_timeout` 줄을 지운다(사전에 없는 코드는 문장 안에 그대로 보이므로 화면은 깨지지 않는다).

## `test_order_plan_list_v2.py` 6건이 clean main에서 실패한다 (2026-09-21, 미해결)

- 재현 조건: main 92c7f32, `web/backend`에서 일회용 `postgres:17.11` + `BIDOPS_TEST_POSTGRES_URL` +
  `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`로 `pytest tests/screening/test_order_plan_list_v2.py -q` → 6 failed, 20 passed.
  `test_search_preserves_unicode_casefold_with_sql_total_and_page` 5개 parameter(SQLite에서도 실패, `limit=1&offset=1`이 `[]`)와
  `test_postgres_list_filters_pagination_and_tracking_projection`(PostgreSQL 전용, `assert 0 == 2`).
- 영향: 발주계획 목록의 검색·페이지 경계 회귀를 이 파일이 더는 막지 못한다. 실무 화면 고도화의 B1(목록 v5·상세 v4 투영) 검수에서
  발견했고 B1 변경과 무관하다(B1 적용 전후·main 트리 모두 같은 6건).
- 지금 해결하지 않는 이유: 원인을 가리지 않았다. 누적 투영 v4(dcce827) 이후 목록이 활성화 이력이 있는 policy의 운영 완료 실행만
  투영하는데 테스트 fixture가 그 조건을 갖추지 않아 0건이 되는 것인지(테스트 결함), 검색·페이지 SQL의 제품 결함인지 먼저 구분해야 한다.
- 후속 방향: 실패 1건을 단독으로 돌려 SQL과 fixture를 대조한다. 제품 결함이면 발주계획 검색 회귀로 올리고, fixture 결함이면
  누적 투영 조건을 갖추도록 고친다. 그 전에는 이 파일의 나머지 20건만 회귀 근거로 쓴다.

## 발주 예정월·사전규격 등록 후 경과를 알리는 재확인 신호가 없다 (2026-09-21, 미해결)

- 재현 조건: 발주 예정월이 지나도, 사전규격이 등록된 지 오래돼도 화면이 아무 말을 하지 않는다. 후보 임계값은
  발주 예정월 + 2개월, 사전규격 등록 후 45일이다.
- 영향: 임계값의 경험적 근거가 없다. 근거 없이 "지연"이라고 적으면 확인되지 않은 사실을 단정하는 표시가 되므로
  이름은 "재확인 알림"이 맞다. 효과는 두 선택지 중 하나다. ⓐ **배지 전용** — 행·상세에 표식만 그리고 구역·
  집계는 건드리지 않는다. ⓑ **`action_reasons`에 사유 코드 추가** — 이 경우 분류식
  (`web/backend/app/lifecycle/services/opportunity_queries.py:375-381`)에 의해 열린 추적 상태의 건이 자동으로
  `조치 필요` 구역으로 올라가고, 행의 주 행동 우선순위와 칩 순서
  (`web/frontend/src/components/opportunities/trackingFlow.ts:157-171`)에도 자리를 잡아야 한다. 같은 모양의
  선례가 `hold_overdue`다(`opportunity_queries.py:355`의 술어 → 같은 분류식 → `trackingFlow.ts`의 라벨·우선순위).
  ⓑ는 대시보드 건수와 사업 추적 구역 건수를 함께 움직이므로 되돌리기 어렵다.
- 지금 해결하지 않은 이유: 2026-09-21 사용자 결정 7로 실무 화면 고도화 범위 밖으로 분리했다. 임계값 근거,
  해제 조건(후속 단계가 연결되면 알림을 끄는가), 월 경계 정의(발주 예정은 월 단위라 "+2개월"의 기준일이
  모호하다)가 모두 미정이다.
- 후속: 실제 데이터로 임계값 근거를 관측한 뒤 ⓐ/ⓑ를 정한다. ⓑ면 `OpportunityActionReason` union·라벨·
  우선순위·필터·대시보드 집계를 한 변경으로 바꾸고 `docs/contracts.md`에 등록한다.

## 발주처 담당자 연락처가 정규화 스키마 밖에 남아 있다 (2026-09-21, 결정 보류)

- 재현 조건: 발주계획 원문 응답에는 담당자 정보가 들어 있으나 `OrderPlan` 정규화 컬럼에는 없다.
  `web/backend/app/lifecycle/models.py:266-273`의 docstring이 그 경계를 적는다 — "The columns below are the
  fields selected by the measured order-plan normalizer.  Contact fields and the remaining response payload stay
  in ``raw_source``/``unknown_fields_json`` rather than becoming guessed schema." 따라서 값은 보존되지만 명명된
  projection이 없어 API·화면에 나올 수 없다.
- 영향: 발주처에 확인할 것이 생겼을 때 실무자가 화면 밖(원문 포털)으로 나가야 한다. `docs/PRD.md` §5.4는
  "발주기관 연락·협상·알림 발송"을 명시적 제외로 두고 있는데, 그것은 **시스템이 대신 연락하는 기능**의 제외이지
  사람이 볼 연락처를 화면에 두는 것을 금지한 문장이 아니다. 두 가지를 같은 것으로 읽으면 결정이 근거 없이 닫힌다 —
  이 항목은 PRD가 이미 금지한 것이 아니라 **아직 결정하지 않은 것**이다.
- 지금 해결하지 않은 이유: 2026-09-21 사용자 결정 8(`docs/0921_practitioner-screens/intent.md` §3)로 이번 범위에서
  빼고 후속 결정으로만 기록하기로 했다. 측정된 정규화 스키마를 넓히는 것은 기존 레코드의 저장 identity에 영향을 줄
  수 있고(`docs/engineering-notes.md` "선택 필드를 계약 모델에 더하면 기존 레코드의 저장 identity가 바뀐다"),
  개인 연락처를 API 응답·로그·감사에 어디까지 실을지가 먼저 정해져야 한다.
- 후속: 표시 여부와 범위(이름 / 부서 / 전화 / 이메일)를 사람이 정한다. 표시하기로 하면 `raw_source`에서 명명된
  projection으로 올리고, 로그·감사·오류 응답에 넣지 않는 규칙을 `docs/contracts.md`와 함께 적는다. 연락 기능
  자체는 PRD §5.4대로 계속 비목표다.

## 입찰공고 `budget`이 세 원문 필드의 fallback이라 무엇을 본 값인지 알 수 없다 (2026-09-21, 미해결)

- 재현 조건: `skills/bidops-collect/scripts/collect_notices.py:612`가
  `"budget": first(record, "asignBdgtAmt", "presmptPrce", "bsisAmount")`로 배정예산 → 추정가격 → 기초금액을 순서대로
  고른다. 바로 다음 줄(`:613`)의 `estimated_price`는 `presmptPrce` 하나다. 저장된 `budget` 값만 보면 셋 중 어느
  원문 필드에서 왔는지 알 수 없고, 두 번째 후보로 떨어진 공고는 `budget`과 `estimated_price`가 같은 값이 된다.
- 영향: 화면이 이 값을 '배정예산'이라 부르면 사실이 아닌 라벨이 된다. 그래서 실무 화면 고도화는 `예산(원문 제공
  금액)`과 `추정가격`을 따로 보이고 값이 같아도 합치지 않는 선에서 멈췄다(`docs/0921_practitioner-screens/spec.md`
  §6.3, [ADR-0066](../decisions/0066-practitioner-ops-information-boundary.md) 결정 4). 두 값이 같을 때 그것이 "실제로
  같은 금액"인지 "fallback으로 같아진 것"인지는 여전히 화면에서 구분되지 않는다.
- 지금 해결하지 않은 이유: 출처를 남기려면 수집기 정규화 출력에 `budget_source` 같은 필드를 더해야 하고, 그러면 위
  "판정 입력에 참여 판단용 날짜·비율 항목이 없고…" 항목과 같은 닫힌 검증기 사슬과 과거 회차 소급 문제가 그대로
  따라온다. 2026-09-21 사용자 결정으로 이번 범위 밖이다(intent §4).
- 후속: 위 항목의 4상태 계약과 함께 `budget_source`(또는 세 금액을 각각 보존하는 형태)를 정한다. 과거 회차는
  소급하지 않고 `미수집`으로 남는다. 그때까지 화면·문서는 이 값을 '배정예산'이라 부르지 않는다.

## 발주계획 일괄 추적 시작에는 record backfill도 선택 상한도 없다 (2026-09-20, 미해결)

- 재현: 단건 `PATCH /api/opportunities/{id}/tracking-status`는 `계속 추적`·`보류`로 바뀔 때 router에서
  `_backfill_tracked_records`를 부른다(`app/lifecycle/routers/opportunities.py`). 일괄
  `POST …/order-plan-tracking/bulk-start`의 서비스(`order_plan_bulk_tracking.py`)는 commit 뒤
  `tracking_decision_changed` hook만 부르고 backfill은 부르지 않는다. 같은 요청 스키마의 `order_plan_ids`는
  `min_length=1`뿐이고 상한이 없다.
- 영향: 같은 `계속 추적` 결정이 단건이냐 일괄이냐에 따라 선별 적재로 빠져 있던 연결 레코드의 backfill 여부가
  갈릴 수 있다(의도인지 미확인). 상한이 없으므로 한 요청이 수천 owner를 한 transaction에서 잠글 수 있다.
- 지금 해결하지 않은 이유: 일괄 추적 종료(ADR-0063) 작업 중 코드를 읽다 확인했다. 종료는 backfill 대상
  상태가 아니라 이 차이의 영향을 받지 않고, bulk-start v1은 계약 불변으로 두기로 했다. bulk-end에만 200건
  상한을 뒀다.
- 후속: backfill 누락이 의도인지 0917 사업 추적 계획의 선별 적재 규칙과 대조한다. 상한은 v2 요청 스키마를
  발행할 때 함께 정한다.

## 담당자 이름은 신원을 증명하지 않는다

- 재현 조건: 사내망 사용자가 mutation에서 다른 담당자의 이름을 입력한다.
- 증상: 시스템은 입력 이름을 감사에 남기지만 실제 사용자의 내부 계정과 일치하는지 확인하지 못한다.
- 영향: 리뷰, 정책 활성화, 외부 모델 전송 승인 기록의 작성자 신뢰도가 사내망 접근 통제 수준에 머문다.
- 지금 해결할 수 없는 이유: 현재는 사내망과 claimed name만 사용하기로 했고 SSO·계정·역할 정보가 연결되지 않았다.
- 접근 방법: 향후 SSO subject를 내부 계정에 매핑하고 세션 만료, 역할, 권한 회수, 기존 claimed-name 감사와의 연결 정책을 도입한다.

## 심층 검토 보고서를 사업기회·공고로 되찾을 목록 계약이 없다

- 재현 조건: 공고 판정 이력에서 심층 검토를 생성해 `/deep-reviews/{id}`로 이동한 뒤 화면을 벗어난다. 사업기회 화면이나 공고 화면에서 그 보고서를 다시 연다.
- 증상: `web/backend/app/deep_review/routers/deep_reviews.py`가 제공하는 읽기 계약은 `GET /deep-reviews/{deep_review_id}` 단건뿐이다. 사업기회·공고로 보고서를 나열하는 endpoint가 없고, 사업기회 목록·상세 응답과 공고 응답에도 `deep_review_id`가 없다. 보고서 식별자를 따로 적어 두지 않으면 만든 보고서로 돌아갈 길이 없다.
- 영향: 구 `docs/design/PRD.md`(git 이력, 삭제됨) §2.2가 요구한 "사업기회 화면의 명시적 진입점"을 데이터로 채울 수 없다. 2026-09-02 화면 개선 2단계는 사업기회 상세에 식별자로 여는 진입점을 두고 목록을 제공할 수 없다는 사실을 화면에 명시하는 선에서 멈췄다. 목록이 비어 보이는 것을 보고서가 없다는 뜻으로 오해할 위험은 문구로만 막고 있다.
- 지금 해결할 수 없는 이유: 해결에는 REST 계약 추가(사업기회 또는 공고별 심층 검토 목록)나 기존 응답에 식별자 노출이 필요하다. 화면 개선 2단계의 범위는 프론트엔드이며 `docs/contracts.md`의 소비자 계약과 백엔드를 바꾸지 않기로 했다.
- 접근 방법: `GET /opportunities/{id}/deep-reviews` 또는 `GET /notices/{notice_id}/deep-reviews`를 추가해 보고서 식별자·생성 시각·현재 상태를 돌려주고, `docs/contracts.md`와 `docs/deep-review-erd.md`에 소비자 계약으로 등록한다. 그 뒤 사업기회 화면의 진입점을 식별자 입력이 아니라 목록으로 바꾼다.
- 종결(2026-09-16): 코드에 구현됨(GET /api/opportunities/{id}/deep-reviews).

## Go/No-Go 결정 대기 사업기회를 N+1 없이 집계할 endpoint가 없다

- 재현 조건: 대시보드 "지금 처리할 일"이나 `GoNoGoPage.tsx`에서 "최종 Go/No-Go 결정 대기" 건수를 구하려 한다.
- 증상: `web/backend/app/deep_review/routers/bid_delta.py`는 사업기회 하나의 workspace만 반환하고(`GET /opportunities/{id}/bid-delta` 계열), "계속 추적 중이며 아직 최종 결정이 없는 사업기회 수" 같은 집계 endpoint가 없다. `GoNoGoPage.tsx`는 이를 우회하려고 추적 중 사업기회 목록을 받은 뒤 사업기회마다 bid-delta workspace를 조회하는 N+1을 이미 쓰고 있다(2026-09-02 화면 개선 2단계, 코드 머리 주석에 기록).
- 영향: 대시보드처럼 N+1을 반복할 수 없는 화면(`web/backend/AGENTS.md`·`CLAUDE.md`의 N+1 금지 게이트)은 이 건수를 전혀 계산할 수 없다. 2026-09-03 3단계는 대시보드 항목의 건수를 `null`(확인 불가)로 표시하고 이동 경로만 제공하는 선에서 멈췄다 — 페이지 자체(`GoNoGoPage.tsx`)의 기존 N+1도 아직 걷어내지 못했다.
- 지금 해결할 수 없는 이유: 해결에는 새 집계 REST 계약(예: 사업기회당 최신 `latest_final_decision` 유무를 서버가 먼저 걸러 세는 endpoint)이 필요하며, 이는 백엔드 스키마·서비스 변경이라 이번 프론트엔드 범위를 벗어난다.
- 접근 방법: `GET /opportunities?tracking_status=계속 추적&decision_status=pending` 같은 서버 필터 또는 `GET /bid-delta/pending-count` 집계 endpoint를 추가해 `docs/contracts.md`와 `docs/bid-delta-contract-spec.md`에 등록한다. 그 뒤 `GoNoGoPage.tsx`의 기존 N+1과 대시보드의 `null` 표시를 실제 건수로 교체한다.

## 발주계획 목록 API에 "사람 피드백 미기록" 필터가 없다

- 재현 조건: 대시보드 "지금 처리할 일"에서 "C-2 검토 대기" 건수를 사람이 아직 판정하지 않은 발주계획 수로 정의하려 한다.
- 증상: `GET /api/order-plans`(`web/backend/app/screening/routers/order_plans.py:78`)는 `qwen_relevance`·`human_relevance`를 필터로 받지만, `human_relevance`는 특정 relevance 값(`relevant`|`not_relevant`|`uncertain`)만 받고 "사람 피드백 행 자체가 없음"을 나타내는 값(`missing`/`null`)을 받지 않는다.
- 영향: 2026-09-03 3단계는 이 항목을 "Qwen 신호가 relevant 또는 uncertain인 발주계획" 건수(사람 피드백 여부와 무관)로 근사했다. 실제 "검토 대기"(아직 아무도 보지 않은 건)보다 넓은 집합이라 과대 계상될 수 있고, 화면 설명 문구로만 그 차이를 알린다.
- 지금 해결할 수 없는 이유: `human_relevance=missing` 같은 값을 추가하려면 서비스 쿼리(`OrderPlanScreeningService.list_order_plans`)와 라우터 계약을 함께 바꿔야 하며, 이번 프론트엔드 범위의 대시보드 작업만으로는 안전하게 변경할 수 없다.
- 접근 방법: `human_relevance`에 `missing` 같은 sentinel 값을 추가해 "사람 피드백 행 없음"을 서버에서 걸러주고, `docs/contracts.md`의 `GET /api/order-plans` 항목에 등록한다. 그 뒤 대시보드와 `OrderPlansPage.tsx`의 "검토 대상" 프리셋이 이 필터를 실제 "미판정" 의미로 좁힐 수 있다.

## 사전규격 목록 API에 마감 구간 필터도 임박 집계도 없다

- 재현 조건: 대시보드 "지금 처리할 일"에서 "사전규격 의견등록 마감 임박" 건수를 구하려 한다.
- 증상: `GET /api/pre-specs`(`web/backend/app/lifecycle/routers/pre_specs.py:95`)는 `sw_only`·`business_division`·`origin`·`q`·`sort`·`limit`·`offset`만 받는다. 마감 구간 필터가 없고 집계 응답도 없다. `sort=deadline`은 `deadline_at ASC NULLS LAST`(`pre_specs.py:180`)라 **첫 페이지가 이미 지난 마감으로 채워진다.** 따라서 한 페이지를 받아 클라이언트에서 세면 두 가지가 동시에 틀린다. (1) 지난 마감을 임박으로 센다 — 회차 산출물 `stats.imminent_deadlines`와 달리 서버가 좁혀 준 창이 없는데 `criticalDeadlineCount`에는 하한이 없다. (2) 임박 구간이 페이지 창 밖이라 애초에 도달하지 못한다.
- 영향: 2026-09-03 3단계는 이 항목의 건수를 `null`(확인 불가)로 두고 이동 경로만 제공하는 선에서 멈췄다. 구현 위임 초안은 `limit=50` 한 페이지를 세어 숫자를 표시했는데, 누적 데이터에서는 거의 항상 "만료된 사전규격 수"를 "마감 3일 이내"로 보여주는 값이라 검수에서 되돌렸다.
- 지금 해결할 수 없는 이유: 해결에는 목록 계약에 마감 구간 필터(`deadline_from`·`deadline_to`)나 임박 집계를 추가해야 하며, 이는 백엔드 라우터·스키마 변경이라 이번 대시보드 작업 범위를 벗어난다.
- 접근 방법: `GET /api/pre-specs`에 `deadline_within_days` 또는 `deadline_from`·`deadline_to`를 추가하고 `docs/contracts.md`의 `PreSpecList` 항목에 등록한다. 그 뒤 대시보드의 `null` 표시를 실제 건수로 바꾸고, `criticalDeadlineCount`의 하한 없음이 회차 산출물 전용 전제임을 호출부에서 다시 확인한다.
- 부분 해소 (2026-09-21, [ADR-0064](../decisions/0064-prespec-actionable-deadline-scope.md)): 위 `증상`의 인자 목록은 이미 낡았다 — 2026-09-16에 `deadline_status=open|passed|unknown`이, 2026-09-21에 `deadline_scope=current|passed|all`과 응답 집계 `deadline_scope_counts{current,passed}`가 들어왔다. `sort=deadline`도 3버킷(마감 전 오름 → 경과 최근 → null)이라 "첫 페이지가 지난 마감으로 채워진다"는 현상은 사라졌고, 검토할 항목의 기본 구간에는 경과 건이 아예 오지 않는다. **남은 것**: 새 구간은 `마감 전·미확인 / 마감 경과` 2분할이지 D-n 임박 **창**이 아니다. `deadline_within_days`류의 창 인자와 그 집계는 여전히 없으므로 대시보드 "사전규격 의견등록 마감 임박" 건수는 계속 `null`(확인 불가)로 남는다. `criticalDeadlineCount`의 하한 없음 주의도 그대로 유효하다.

## 발주계획 추적 결정(결정 1)을 저장할 REST 계약이 없다

- 재현 조건: `web/backend/app/screening/routers/order_plans.py`의 경로 다섯 개를 확인한다. 목록·상세·screening-history·screening-feedback(GET/POST)뿐이다. `PATCH /opportunities/{id}/tracking-status`는 사업기회 식별자로만 부를 수 있고, `OrderPlanListItem`·`OrderPlanDetailResponse`(둘 다 `_Strict`)에는 `opportunity_id`도 추적 상태도 없다.
- 증상: ADR-0046(git 이력 docs/design/ADR.md, 삭제됨) 결정 4가 추적 결정을 발주계획 화면의 결정 1로 채택했는데, 그 결정을 읽을 수도 쓸 수도 없다. 구 `docs/design/PLAN.md`(git 이력, 삭제됨) 단계 C 작업 5(추적 결정을 상세 pane 바닥의 결정 액션으로)와 완료 게이트 2("추적 결정과 사람 판단 수정이 서로 다른 요청으로 저장된다")를 서버 없이 만족시킬 수 없다.
- 영향: 단계 C의 화면은 만들 수 있으나 **결정이 서버에 남지 않는다.** 이 상태에서 결정을 화면 상태나 localStorage에 기록하면 담당자에게 저장된 것처럼 보이면서 실제로는 사라지므로, 그렇게 만들지 않는다.
- 상태: **차단** (2026-09-04). 화면 구현의 차단이 아니라 계약의 부재다.
- 지금 해결할 수 없는 이유: REST·DB 계약은 백엔드 파트의 소유이고, 화면 작업이 임의로 endpoint를 만들거나 기존 사업기회 계약의 의미를 바꿀 권한이 없다.
- 접근 방법: 요청안을 `order-plan-tracking-contract-request.md`(git 이력 docs/design/order-plan-tracking-contract-request.md, 삭제됨)로 작성해 백엔드 파트에 보낸다. 조사 결과 **새 table은 필요하지 않을 가능성이 높다** — 소유 사업기회와 `stage='order_plan'` official 링크는 `ingest/loader.py`가 이미 만들고, 상태 4값과 append-only `AuditEvent`도 이미 있다. 없는 것은 응답에 그 상태를 싣는 것과 발주계획 식별자로 쓸 경로 둘이다. 계약이 확정될 때까지 화면은 요청안 §7의 규칙을 지킨다: adapter 한 곳으로 호출을 모으고, 실패를 성공으로 보이게 하지 않으며, 응답에 추적 상태가 없으면 `계약 미구현`으로 표시하고 `미선택`으로 바꾸지 않는다. 계약이 구현·검증되기 전에는 단계 C를 완료로 적지 않는다.
- 종결(2026-09-16): 코드에 구현됨(일괄·단건 추적 REST).

## 보고서의 문서 inventory 패널이 문서 하나만 보여 준다

- 확인: 2026-09-05
- 재현 조건: 여러 문서가 든 묶음으로 심층 검토를 하고 보고서 화면의 우측 문서 inventory
  패널을 본다.
- 증상: 패널은 **선택된 근거가 가리키는 문서 하나**의 manifest만 보여 준다. 묶음이나 공고에서
  그 안의 문서들의 `structure_id` 목록을 주는 endpoint가 없고, `DocumentVersionView`에도
  `structure_id`가 없기 때문이다.
- 영향: "문서별 inventory"를 요구한 설계를 절반만 만족한다. 근거를 고르지 않으면 패널이
  비고, 고르면 그 문서만 보인다. 화면이 어느 문서의 것인지 문장으로 밝히므로 다른 문서의
  값으로 오해할 위험은 막고 있다.
- 지금 해결할 수 없는 이유: 해결에 REST 계약 추가가 필요한데, 이번 범위가 허용한 REST 추가
  목록에 그 endpoint가 없다.
- 접근 방법: `DocumentVersionView`에 nullable `structure_id`를 더하거나
  `GET /api/document-bundles/{bundle_id}/structures`를 추가해 `docs/contracts.md`에 등록한다.
  그 뒤 패널을 문서 목록으로 바꾼다.

## 사전규격 목록의 등급 필터가 브라우저 쪽이라 집계와 비대칭이다

- 확인: 2026-09-05
- 재현 조건: `/pre-specs?grade=우선 검토`를 연다.
- 증상: `GET /api/pre-specs`에 `grade` 질의 인자가 없다. 화면 필터는 **이미 불러온 페이지만**
  좁히고, 같은 응답의 `overview_status_counts`는 **필터 이전 전체 집합**을 가리킨다. 두 수의
  대상 집합이 다르다.
- 영향: 페이지를 넘기면 등급별로 보이는 건수가 페이지마다 달라지고, 그룹 헤더 건수와 목록
  건수가 맞지 않는다. 화면이 이 사실을 직접 적어 두었으므로 잘못된 총계로 읽힐 위험은
  문구로 막고 있다.
- 지금 해결할 수 없는 이유: 서버 쪽 `grade` 인자는 `PreSpecList` query 계약과 등급 projection
  확장점을 함께 바꾸는 일이고, 이번 범위가 허용한 REST 변경 밖이다.
- 접근 방법: `PreSpecList` query에 `grade`를 더하고 판정 projection 확장점의
  `notice_ids_for_filters`로 서버에서 거른다. 그때 `overview_status_counts`도 같은 필터를
  반영하게 해 두 수의 대상 집합을 맞춘다.

## 리뷰 저장 hook과 첨부 취득 worker가 같은 문서 집합으로 묶음을 둘 만들 수 있다

- 확인: 2026-09-05
- 재현 조건: 같은 사전규격에 대해 사람이 등급을 정정해 `effective_grade_changed` hook이 도는
  순간과 첨부 취득 worker가 그 공고의 취득을 종결하는 순간이 겹친다. 둘 다
  `maybe_auto_prepare`를 부른다.
- 증상: 두 경로가 각각 현재 문서 집합을 읽고 "묶음이 없거나 지문이 달라졌다"고 판단하면 같은
  문서 집합으로 묶음 revision이 둘 생길 수 있다. worker끼리는 concurrency 1이라 배제되지만
  hook은 web 프로세스에서 돈다.
- 영향: 좁은 경합이며 데이터가 깨지지는 않는다. 묶음은 append-only이고 revision이 하나 더
  생길 뿐이다. 다만 자동 확정이 두 번 일어나면 감사에 `document_bundle.auto_confirm`이 둘
  남고, 어느 것이 심층 검토의 입력인지는 심층 검토 row가 가리키는 `bundle_id`로만 확정된다.
- 지금 해결할 수 없는 이유: 공고 단위 잠금을 자동 준비 경로에 넣으면 회차 적재 hook이 수천
  건에 대해 잠금을 걸게 되고, 그것이 회차 적재 transaction의 성능 특성을 바꾼다. 어느 쪽이
  나은지는 실측 없이 정할 수 없다.
- 접근 방법: 자동 준비 진입에 공고별 advisory lock을 걸거나, 묶음 생성에 문서 지문 기반
  unique 제약을 더해 둘째 생성을 idempotent replay로 만든다. 둘 다 회차 적재 hot path의
  실측이 먼저다.

## PDF 개요 연결 검증에서 확인한 범위 밖 회귀 실패 (2026-09-07)

- 재현: backend에서 `pytest tests/deep_review/test_prespec_projection.py::test_projection_satisfies_the_lifecycle_protocol tests/screening/test_projection.py::test_projection_and_hook_satisfy_the_lifecycle_protocols`.
  `OverviewDocumentProjection`과 `JudgmentProjection`의 요구 메서드를 현재 구현체가 모두
  제공하지 않아 runtime protocol 검사가 실패한다. 해당 protocol/구현 파일은 이번 PDF
  개요 저장 변경에서 수정하지 않았다. 별도 생애주기 필터·차단 항목 집계 구현과 함께
  정합성을 맞춰야 하므로 설명형 개요 저장 범위에서 임의의 빈 응답 메서드를 추가하지 않았다.
- frontend에서 `npm run test:screens`: 337 passed / 11 failed / 4 skipped.
  실패는 `common-interactions`, `route-context`, `screen-semantics`의 기존 화면 제목
  (`검토 대기열` 기대 / `공고 판정 이력` 표시), 회차 영역 기대값, 중복 `사람 검토 필요`
  문구 선택자다. 새 `page-overview.spec.ts`와 사전규격 관련 38개 검사는 통과했다.
  현재 화면 명칭·회차 구분의 정본에 맞춰 해당 기존 회귀 기대값을 검토해야 한다.
- 영향: 전체 회귀 게이트를 통과했다고 주장하거나 이 기록만으로 배포 승인 근거로 사용할
  수 없다. 재현 명령과 이번 변경의 상세 검증은
  `docs/validation-runs/20260907-prespec-page-overview-integration.md`에 기록한다.

## 화면 스위트의 발주계획·공통 골격 spec 53건이 main에서 실패한다 (2026-09-16, 원인 미확인)

- 재현: main `bdd6c25`에서 `PW_PORT=4183 npx playwright test <spec> --project=app --workers=2`.
  `order-plans.spec.ts` 46건, `review-primitives.spec.ts` 3건, `admin-workspace-consistency.spec.ts` 2건,
  `review-workspace-consistency.spec.ts` 1건, `explore-workspace-consistency.spec.ts` 1건이 실패한다.
  발주계획 목록은 mock 응답이 있는데도 "조건에 맞는 계획이 없습니다"로 비어 `.c2l-row`가 0개이고,
  실행 상태 화면은 `.rs-detail-foot`이 없다. 부하를 줄여(worker 2) 다시 돌려도 같은 건수다.
- 영향: 같은 날 오전 `10cb5be` 기록은 `--project=app` 449 passed·0 failed였다. 그 사이 main의 프런트 코드
  변경은 없고(백엔드·권한 SQL·문서만), 개요 3섹션 변경(ADR-0057) 통합 트리도 같은 53건만 실패했다
  (그 외 1건은 의도한 배치 변경의 spec 기대값 누락이라 고쳤다). 따라서 이번 변경의 회귀는 아니다.
- 지금 해결하지 않은 이유: 원인을 확인하지 않았다. 날짜에 의존하는 mock 데이터(관측 기간·마감 기준)나
  공유 mock의 회차 목록이 후보다. 이번 범위는 개요 검토 재설계라 확장하지 않았다.
- 후속: `10cb5be`를 격리 워크트리로 체크아웃해 같은 spec을 돌려 날짜 의존인지 코드 의존인지 먼저 가른다.
- 2026-09-20 재확인(main `acdf0d9`, 같은 명령): `order-plans.spec.ts`·`explore-workspace-consistency.spec.ts`·
  `review-primitives.spec.ts`·`pre-specs.spec.ts`·`prespec-list-work.spec.ts`는 **156 passed · 0 failed**다.
  발주계획 목록이 비던 50건은 더 재현되지 않는다(그 사이 무엇이 고쳤는지는 가르지 않았다). **남은 것은
  `admin-workspace-consistency.spec.ts:23`의 2건(1280·1440)**으로, 수정 없는 main에서 실행 상태 화면의
  `.rs-detail-foot`이 보이지 않아 똑같이 실패한다. 이 항목은 그 2건으로 좁혀 유지한다.
- 2026-09-20 함께 확인된 기존 실패 1건: `common-interactions.spec.ts:266` "사이드바는 7항목…"이 main에서 8개를
  본다. `acdf0d9`(나라장터 바로가기 추가)가 8번째 `.sidebar-item`을 넣고 `design-shell.spec.ts`만 갱신했다.
  바로가기를 `SIDEBAR_ITEMS`에 넣을지 카운트에서 뺄지는 그 변경의 의도에 달려 있어 고치지 않았다.
  → 같은 날 해소(`dd5da1d`): 바로가기는 그룹 밖 외부 링크이고 `design-shell.spec.ts`가 따로 검사하므로 주 메뉴 항목만 세게 했다.

## 발주계획 화면이 누적 목록을 500행씩 전부 받아 브라우저에서 거른다 (2026-09-18, 미해결)

- 재현 조건: `web/frontend/src/pages/OrderPlansPage.tsx:77`의 `PAGE_SIZE = 500`으로 누적 목록을 한 번에
  최대 500행 받아 브라우저에서 필터링한다. 활성화 뒤 발주계획은 하루 약 300건씩 누적으로 늘어난다
  (`docs/0918_daily-operation/spec.md` §7 — 활성화된 적 있는 policy의 운영 목적 완료 실행 전부가 누적
  범위).
- 영향: 누적 기간이 늘수록(며칠만 지나도 500건을 넘는다) 서버가 이미 필터링해 줄 수 있는 조건도 클라이언트가
  전량을 받아서 걸러야 하므로 응답 크기와 렌더 비용이 계속 커진다. 목록 응답의 `human_feedback`에
  `execution_id`가 없어 화면이 `expected_revision`(다음 사람 피드백 저장 시 낙관적 잠금에 쓰는 값)을
  계산하려면 별도 조회가 필요하다.
- 지금 해결할 수 없는 이유: 서버 쪽 필터·페이지네이션은 목록 쿼리(`services/order_plan_screening.py`의
  누적 투영)와 화면 양쪽을 함께 다시 설계해야 하고, 이번 일일 운영 고도화 계획은 누적 투영을 "회차 선택
  없이 전체를 한 번에 반환"하는 현재 모양으로 두고 활성화 경로만 구현했다.
- 후속 방향: 별도 계획으로 목록 API에 서버 쪽 필터·페이지 파라미터를 추가하고, 응답 `human_feedback`에
  `execution_id`를 실어 화면이 재조회 없이 `expected_revision`을 계산하게 한다(`docs/contracts.md`
  변경 제안).

## 2026-10-17 브리핑 지역 제외에 쓸 참가 가능 지역 값이 수집되지 않음

- 재현: 수집기 `skills/bidops-collect/scripts/collect_notices.py`의 `region_limit.basis`는 `rgnLmtBidLocplcJdgmBssNm`(지역제한 소재지 판단 기준, 예 "본사소재지")이고 `joint_contract_regions`는 공동도급 의무 지역(`jntcontrctDutyRgnNm1~3`)이다. 공고의 **참가 가능 지역 이름**은 나라장터 목록 오퍼레이션에 없고 별도 오퍼레이션에서만 온다.
- 영향: RL-01 spec 초안의 지역 제외식(`basis`+공동도급 지역에 허용 지역 이름이 없으면 제외)은 지역제한 공고를 지역과 무관하게 전부 제외한다. 독립 리뷰가 지적했고 T12 실데이터에서는 `region:0`이라 드러나지 않았다.
- 현재 조치(사용자 결정 2026-10-17): 브리핑의 `region` 제외를 보류(`excluded.region` 항상 0). 루트랩 회사 파일 v2의 허용 지역(대구·세종)은 값만 보존한다.
- 지금 해결하지 않는 이유: 참가 가능 지역 수집은 새 외부 호출·수집 계약·적재 열 변경이라 배치 A 범위(외부 호출 없음) 밖이다.
- 후속: 수집기에 참가가능지역 오퍼레이션을 추가하는 별도 기능으로 등록하고, 값이 생기면 지역 제외를 다시 켠다. 그 전까지 지역 적격성은 RL-03 판정(원문 대조)에서 확인한다.

## 팔레트 전환 뒤 화면 단위 시각 회귀를 잡을 기준선이 없다 (해결)

정리 메모(2026-10-21): 주 결함은 조치됐으나 아래 잔여 한계는 당시 기록 그대로이며 현재 재검증하지 않았다.

- 재현 조건: `web/frontend`에서 `npx playwright test`를 실행한다. 2026-09-04 단계 A(무드보드 팔레트 적용, ADR-0048) 이후 기준이다.
- 증상: 단계 A 직후 `370 passed, 75 failed, 3 skipped`. 실패 75건 중 73건이 `visual.spec.ts`다. 팔레트가 모든 화면의 색을 바꿨으므로 옛 무채색 기준선과 다른 것이 정상이며, 실패 자체는 회귀의 증거가 아니다.
- 정정 (2026-09-04, 단계 B): 그 73건은 전부 스냅샷이 아니다. **팔레트 스냅샷 72건 + `/queue` 1280px 가로 오버플로 1건**이다. 오버플로 1건은 색과 무관한 레이아웃 실패이며(`.notice-attachments-panel`의 첨부 파일명이 19.77px 넘침), 단계 B의 변경 전후로 같은 값이 나오는 것을 확인했다. 단계 E가 `검토 대기열`을 이행할 때 함께 정리한다. 단계 B 이후 수치는 `382 passed, 74 failed, 2 skipped`이며 새 실패는 없다(74 = 위 73건 + `visual.spec.ts:257` flake 1건, 단독 실행 시 통과).
- 해소 (2026-09-04, 단계 E): `/queue` 오버플로 1건을 고쳤다. `.attachment-name`이 ellipsis로 자르고 있었지만 **자름은 부모의 시각 효과일 뿐 자식 `span`의 레이아웃 상자는 그대로 넘쳐 있었다.** 자식이 스스로 `max-width: 100%`와 ellipsis를 갖도록 고쳤고 `visual.spec.ts`의 가로 넘침 36건이 모두 통과한다. **남은 실패는 팔레트 스냅샷 72건뿐이며, 이 finding이 말하는 신호 손실은 그 72건에만 해당한다.**
- 영향: **그 73건이 실패로 남아 있는 동안 화면 단위 레이아웃 회귀를 자동으로 구분할 수 없다.** "색이 바뀌어서 실패"와 "레이아웃이 깨져서 실패"가 같은 실패로 보인다. 셸은 `tests/design-shell.spec.ts`의 구조 검사(테마 scope, computed 색 대 PRD §4.1, 248/76px 치수, 1280·1440·1920px 가로 오버플로 없음, legacy 토큰 회귀)로 지켜지지만 이 검사는 셸 범위이고 화면 내부 레이아웃은 보지 않는다.
- 상태: **해결** (2026-09-04). 당시 판단은 "시안을 다시 렌더해야 기준선을 만들 수 있다"였는데, 그것은 **시안 충실도 대조**의 조건이지 앱 자기 회귀 기준선의 조건이 아니었다. 둘을 한 덩어리로 묶어 둔 탓에 픽셀 72건이 계속 빨간 채로 남아 있었다.
- **해결 (2026-09-04, 화면 검사 층 분리).** 원인은 팔레트가 아니라 **한 파일이 세 가지 일을 하고 있었던 것**이다. `visual.spec.ts` 87개가 픽셀 36 + 가로 넘침 36 + 의미 15로 섞여 있어, 픽셀이 깨지면 나머지 51개의 초록이 같은 실행 결과에 묻혔다. 그래서 "실패하지만 정상"이라는 단서를 문서 다섯 군데에 적어야 했다.
- 조치: 파일을 세 층으로 갈랐다 — `screen-semantics.spec.ts`(의미, 한 폭) · `overflow.spec.ts`(구조, 두 폭) · `pixel-screens.spec.ts`(픽셀, 게이트 밖). 공유 fixture는 `screen-fixtures.ts`로 뺐다. 게이트는 앞의 두 층(`npm run test:screens`)이고 픽셀은 `npm run test:pixel`로만 돈다.
- **기준선 교체 승인 기록.** 사유: 팔레트 전환(ADR-0048)으로 옛 무채색 기준선이 전부 무효가 됐고, 앞으로 화면을 고칠 계획이라 회귀 기준선이 필요하다. 영향 화면: 아래 여덟 장으로 줄였다 — `dashboard`·`criteria`·`order-plans-list`·`order-plan-detail`·`pre-specs-list`·`opportunities-list`·`deep-review-complete`·`bid-delta-changed`. 통짜 36장은 화면을 건드릴 때마다 기준선 커밋을 끌고 오면서 실제로 잡아 주는 것은 골격 여덟 가지가 거의 다였다. 나머지 화면은 구조·의미 층이 본다. 승인: 저장소 소유자의 명시 지시(2026-09-04). 옛 기준선 144장(39MB)은 지우고 새 여덟 장(1.1MB)을 만들었다.
- **남은 한계.** 이 기준선은 **앱이 자기 화면을 찍은 회귀 기준선이며 승인된 시안이 아니다.** 시안 충실도 대조는 여전히 열려 있고 그 선행 조건은 design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) §0-3·0-4다 — 위의 "B-F 설계 승인 baseline과 manifest가 없어 전체 설계 게이트를 완료할 수 없다"가 그 항목이다. 또한 발주계획 추적 결정 계약이 없어 화면이 `계약 미구현`을 띄우는 상태가 기준 이미지에 그대로 들어 있다. 회귀 감지에는 문제없지만 **"이 화면이 옳다"는 승인으로 읽지 않는다.**
- 곁들여 고친 것: 마감·감사 경로 검사가 전체 실행에서만 깨지던 flake. 이동 후 주소 확인 여유가 기본 5초여서 400여 개가 동시에 붙으면 못 들어왔다. 단독 실행 6회는 통과했다. 여유를 15초로 늘렸다.

## 운영 DB의 C-2 policy v2가 활성화 API 없이 active·passed로 있다 (2026-09-18, 운영 조치 완료 2026-09-19)

정리 메모(2026-10-21): 주 결함은 조치됐으나 아래 잔여 한계는 당시 기록 그대로이며 현재 재검증하지 않았다.

- 재현 조건: 운영 DB에 `c2-order-plan-screening-v2`가 `policy_status=active`·`quality_gate_status=passed`
  (`active_slot=1`)로, v1이 `retired`·`passed`로 있다. 2026-09-03 종단 확인 때 테스트 전용 SQL로 직접
  DB 행을 활성화한 것이며(`docs/tracking/status.md`의 발주계획 C-2 선별 항목 "테스트 전용 policy 사본으로만
  활성화했고 품질 근거가 아니다"), 그 활성화에 대응하는 `AuditEvent(action="c2.policy_activated")`나 그
  실행 이력이 없다.
- 영향: 이번 웨이브의 새 활성화 탭(`/order-plan-policies`)은 policy 행의 `policy_status`·
  `quality_gate_status`·`active_slot`을 읽어 게이트를 통과한 활성 policy처럼 보여준다 — v2는 이 조건을
  전부 만족한다. 실제로는 v2 binding의 `external_transport.execution_allowed`가 승인되지 않았고
  `BIDOPS_C2_EXECUTION_ALLOWED`도 기본 false이므로 C-2 실행과 일일 자동 실행은 여전히 fail closed다. 화면
  표시와 실제 실행 가능 여부가 갈리는 지점이라 담당자가 "이미 활성화됐다"고 오인할 수 있다.
- 지금 해결할 수 없는 이유: 활성 행을 되돌리는 것은 DB 데이터를 직접 고치는 운영 작업이라 사람 승인이
  필요하고, 이번 계획의 범위(코드·문서)를 넘는다. v2를 그대로 retire하면 그 근거가 된 2026-09-03 종단
  확인 기록과의 관계도 함께 정리해야 한다.
- 후속 방향: 배포 때 `python -m app.screening.c2_policy retire`로 v2를 내린다(사람 승인됨, 2026-09-19).
  교체 없이 `retired`·`active_slot=NULL`로 내려가고 감사 이벤트(`c2.policy_retired`,
  `replaced_by_policy_version=null`)가 남으며, 활성 policy가 없으므로 일일 자동 실행도
  `no_active_policy`로 꺼진 채 시작한다(절차는 `docs/operations.md`의 C-2 활성화 절). 운영 조치 전이므로
  이 항목은 실제 실행과 그 결과 확인 뒤에 닫는다. v3를 정식 활성화하면 그 시점에는 활성화 transaction이
  이전 active를 자동으로 내린다(§3.3 9번, `docs/0918_daily-operation/spec.md`).
- 조치 결과(2026-09-19): 운영 DB를 백업(`backups/postgres/full/bidops-20260919T063021Z.dump`, SHA-256
  `f0fb31f1…3e4a09`)하고 그 사본으로 0026→0029 migration과 retire CLI를 격리 리허설한 뒤, 운영에 migration
  `0029_c2_quality_gate`를 적용하고 web 컨테이너에서 retire CLI를 실행했다(담당자 `jechoi`). v2는
  `retired`·`active_slot=NULL`이고 `c2.policy_retired` 감사 이벤트 1건이 남았다. `activated_by=e2e-test`·
  `quality_gate_status=passed`는 이력으로 그대로 남는다 — 품질 근거가 아니다. 화면 확인: 활성화 탭 "운영 활성
  없음", 발주계획 "누적 판정 없음"(참조 실행을 "최근 운영 실행"으로 적지 않음), 자동 실행 배너 없음, 대시보드
  "완료된 선별 실행 없음". 활성화 탭은 교체 없이 내린 v2도 "교체됨"으로 표시한다(문구 미수정).

## 발주계획 목록 검색 테스트 6건이 PostgreSQL에서 실패한다 (2026-11-18, 미해결·원인 미확인)

- 재현: 일회용 `postgres:17.11`과 `BIDOPS_TEST_POSTGRES_URL`로 `tests/screening/test_order_plan_list_v2.py`를
  돌리면 `test_search_preserves_unicode_casefold_with_sql_total_and_page[…]` 5건과
  `test_postgres_list_filters_pagination_and_tracking_projection` 1건이 `assert searched["total"] == 2`에서
  0으로 실패한다. C-2 Top150 변경(`d7e9186`) 전 코드(`d1ce3ae`)에서도 같은 6건이 실패했다 — 이번 변경과
  무관한 기존 실패다. PostgreSQL URL 없이 파일만 지정하면 skip되어 보이지 않는다.
- 영향: 실패 사례는 독일어·그리스어 등 대소문자 변환(casefold) 문자를 쓴 검색이다. 운영 화면의 한글·영문
  검색은 2026-11-18에 동작을 확인했다. 그 외 문자의 검색 결과가 빠질 수 있는지는 확인하지 않았다.
- 지금 해결하지 않은 이유: 원인(테스트 fixture, DB collation, 검색 SQL 중 어느 쪽인지)을 가리지 않았고
  Top150 작업 범위 밖이다.
- 후속 방향: 실패 1건을 골라 생성 SQL과 fixture의 정규화 값을 대조해 제품 결함인지 테스트 환경 문제인지
  먼저 구분한다.
- 함께 본 것: 화면 스위트 `tests/order-plans.spec.ts:1309`("사람 피드백 축과 텍스트 검색도 다른 축과 AND로
  조합된다")가 197건 실행 중 한 번 실패했고 단독·파일 전체 재실행에서는 통과했다. 원인 미확인(같은 시간에
  백엔드 테스트가 돌고 있었다). `tests/design-shell.spec.ts:234`는 변경 전 commit에서도 실패한다.
