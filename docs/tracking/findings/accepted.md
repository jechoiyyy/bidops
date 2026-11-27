# 수용한 제약 문제 기록

[전체 색인](../findings.md). 명시적인 수용 결정이 있는 항목이다. 수용 범위·날짜를 유지하며 후속 변경으로 자동 해소됐다고 추정하지 않는다.

## 목록 행 체크박스의 클릭 대상이 24px에 못 미친다 (2026-09-20, 수용됨)

- 재현: 1280×800, `/order-plans`·`/pre-specs` 목록 행 체크박스의 `getBoundingClientRect()`가 14.39×14.39 CSS px다
  (`--bo-ui-scale: 0.9` 적용 뒤). 선택 툴바 단추는 25.19px로 기준을 넘는다.
- 영향: WCAG 2.2 AA "Target Size (Minimum)"의 24 CSS px에 못 미친다. 주변 간격으로 충족하는 예외에 해당할
  여지는 있으나 행 자체도 클릭 대상이라 단정하지 않는다. 탐색 화면 통일(ADR-0062) 이전에도 같은 값이었다.
- 지금 해결하지 않은 이유: `box-sizing: border-box`와 명시 width/height 때문에 padding으로는 대상이 커지지
  않는다. `--size-element-sm`(약 25px)로 올리면 승인 시안의 체크박스 모양과 픽셀 기준선이 함께 바뀐다.
- 2026-09-20 사용자가 그대로 두기로 했다. 확대한다면 시안을 먼저 확인한다.
- 2026-11-18 메모: 밀도 축척(`--bo-ui-scale: 0.9`)을 없애고 4px 격자로 옮겼다(`docs/specs/1118_launch-hardening/설계고도화안.md` §4 B). 같은 재현에서 체크박스는 16×16 CSS px로 여전히 24px에 못 미친다. 수용 결정은 바꾸지 않았다.

## 승인된 프로필 기준선 commit이 현재 저장소 history에 없다 (2026-08-31 결정으로 수용)

- 재현 조건: `git cat-file -e ee621835db934ddac944f7a07a986ed0b73ecc7a^{commit}`을
  현재 checkout에서 실행한다.
- 증상: 승인 commit과 그 path의 blob이 둘 다 Git object DB에 없다.
- 실제 영향: **없다.** byte-identical 파일이
  `web/backend/app/screening/baseline_company_profile.md`로 벤더링돼 있고
  `BASELINE_PROFILE_SHA256= a231ab54…`로 검증된다. `read_git_source()`는 git 조회가
  불가할 때만 이 파일로 fallback하고, git이 있으면 동등성을 교차 확인해 drift를 막는다.
  `test_profile_snapshot*` 14건은 현재 모두 통과한다.
- 범위 정정: 이 commit은 `model_comparison` 품질 gate 전용 **역사 anchor**다.
  `operational_approval`은 `profile_source = "current"`를 요구하고 런타임의
  `snapshot_current()`는 현재 working tree 프로필(sha256 `96731dd5f77d…`)을 읽는다.
  운영 판정은 이미 현재 프로필을 쓰고 있으므로 정본이 갈라진 상태가 아니다.
- 결정: 2026-08-31에 이 상태를 그대로 두기로 했다. 현재 프로필을 역사 anchor에 덮어쓰면
  `model_comparison`이 현재-대-현재 비교가 되어 "역사 baseline과 설명 가능한 비교"라는
  목적 자체가 사라지므로 하지 않는다.
- 남는 제약: `git:ee621…`을 요구하는 model comparison gate는 git 경로로 재현할 수 없고
  벤더링 파일에만 의존한다. 그 파일이 저장소에서 사라지면 역사 비교가 불가능해진다.

## 사업기회 추적 이력을 읽을 계약이 없고 구역별 집계도 서버가 세지 않는다

- 재현 조건: `web/backend/app/lifecycle/routers/opportunities.py`의 경로 넷을 확인한다. 목록(`GET ""`)·상세(`GET /{id}`)·후보 연결 판정(`PATCH /links/{id}/decision`)·추적 상태 변경(`PATCH /{id}/tracking-status`)뿐이다. 목록 query는 `tracking_status`·`first_registered_stage`·`sort`·`limit`·`offset`이다.
- 증상 1 — **추적 이력이 최근 한 건뿐이다.** `opportunity_tracking`은 상태 변경마다 append-only `AuditEvent`(`opportunity.tracking_status.changed`)를 남기지만 그것을 읽는 endpoint가 없다. 화면이 받는 것은 `OpportunityStateView`의 `tracking_status`·`tracking_reason`·`tracking_selected_by`·`tracking_selected_at` 넷, 즉 **마지막 한 건**이다. ADR-0046(git 이력 docs/design/ADR.md, 삭제됨) 결정 2가 요구한 사업 추적 상세의 `추적 이력` 탭이 이전 결정을 보여줄 수 없다.
- 증상 2 — **구역별 집계와 필터가 없다.** ADR-0046 결정 2의 구역 `조치 필요`는 저장된 상태가 아니라 "미선택이거나, 재검토 신호나 예외 작업이 남았다"는 파생 조건이다. 서버에 `recheck_signal` 필터도 후보 연결 대기 필터도 집계 응답도 없어, 화면이 한 페이지를 받아 직접 나눈다.
- 영향: (1) `추적 이력` 탭은 최근 한 건만 보여주고, 그것이 이전 결정이 없다는 뜻이 아님을 화면이 직접 밝힌다(`.opportunity-contract-gap`). 이전 revision을 화면이 지어내지 않는다. (2) `조치 필요` 구역의 건수는 **받은 페이지 안에서 센 값**이며, 목록 머리말이 그 사실과 남은 건수를 함께 적는다. 전체 총계로 읽으면 과소 계상된다.
- 상태: **수용됨** (2026-09-04, 단계 E). 화면 구현의 차단이 아니라 계약의 부재이며, 두 한계 모두 화면이 숨기지 않고 표시한다.
- 지금 해결할 수 없는 이유: REST·DB 계약은 백엔드 파트의 소유이고, 화면 작업이 감사 기록 읽기 경로를 새로 만들거나 목록 계약의 의미를 바꿀 권한이 없다.
- 접근 방법: (1) `GET /api/opportunities/{id}/tracking-decisions`를 추가해 append-only 이력을 `revision`·`tracking_status`·`reason`·`selected_by`·`selected_at`·`audit_event_id`로 연다. 발주계획 쪽 같은 요청(`order-plan-tracking-contract-request.md`(git 이력 docs/design/order-plan-tracking-contract-request.md, 삭제됨) §2.1)과 같은 wire shape를 쓰면 화면이 `ReviewRevisionHistory` 하나로 둘을 그린다. (2) 목록에 `recheck_signal`·`has_pending_candidate_link` 필터와 구역별 `section_counts` 집계를 추가하고 `docs/contracts.md`의 `OpportunityList` 항목에 등록한다. 그 전까지 화면은 저장된 추적 상태로 서버를 거르고(`추적 중`·`보류`·`추적 종료`) `조치 필요`만 받은 페이지에서 나눈다.
- 종결(2026-09-17): 코드에 구현됨(`GET /api/opportunities/{id}/tracking-decisions`가 append-only 추적 이력을, `GET /api/opportunities`의 `section` 필터와 `section_counts`가 서버 구역 집계를 제공한다).

## 비교 근거 최종 결정 경로가 runtime `app` 역할에서 실행되지 않는다 (2026-09-17, 수용됨)

- 재현 조건: `scripts/runtime-privileges.sql:55`에서 `bid_delta_comparison`은 app에 SELECT만
  주고, `bid_delta_attempt`·`bid_delta_item`·`bid_delta_evidence`는 app·worker 어느 쪽에도
  아무 권한이 없다(파일 어디에도 이름이 없다). `POST /api/opportunities/{id}/bid-delta/comparisons`
  (`services/bid_delta.py:806` `create_comparison`)는 `session.add(comparison)`·
  `session.add(attempt)`로 두 table에 INSERT한다. 최소 권한의 `app` DB 역할로 이 endpoint를
  호출하면 PostgreSQL이 권한 오류(SQLSTATE `42501`)로 거부한다.
- 증상: 비교 생성 202 응답과 `pending` comparison·`queued` attempt는 테스트·상승된 DB 자격
  증명(migration/superuser 역할)으로 검증됐을 뿐, 운영이 쓰는 `app` 역할로는 재현되지 않는다.
  이 경로는 애초에 비교를 실제로 계산하는 worker가 없어 `pending`에 머무는 것으로 문서화돼
  있었지만([ADR-0058](../decisions/0058-final-decision-basis-separated-from-comparison.md) 맥락,
  `docs/contracts.md` "구현된 계약 — 입찰 delta와 최종 결정"), 이번 확인으로 **`pending`조차
  runtime 권한으로는 만들 수 없다**는 사실이 드러났다.
- 영향: `basis_kind=comparison` 최종 결정 경로 전체(비교 생성 → attempt 재시도 →
  완료된 비교 기반 결정)가 운영 `app` 역할에서 시작조차 되지 않는다. `basis_kind=
  notice_conditions` 경로(공고 조건 결정, ADR-0058)는 영향 없다 — 그 경로는 `bid_final_decision`
  INSERT와 `UPDATE (id)`만 필요하며 두 권한 모두 이미 app에 있다(`runtime-privileges.sql:150,224`).
- 지금 해결할 수 없는 이유: 비교를 실제로 계산하는 worker가 아직 구현되지 않았고 이번 계획은
  그 구현을 명시적으로 보류했다(ADR-0058 §6 "비교 계산 worker와 모델 binding은 계속 보류").
  worker 없이 `bid_delta_comparison`·`bid_delta_attempt`·`bid_delta_item`·`bid_delta_evidence`
  INSERT 권한만 먼저 열면 계산되지 않는 `pending` 행만 쌓이고 실제 문제(모델 호출·계산 로직
  부재)는 그대로다. 권한 설계는 그 worker의 쓰기 경계(app이 만들고 worker가 계산·완료하는
  분리, `bid_final_decision`이 이미 쓰는 패턴)와 함께 정해야 중복 개정을 피한다.
- 접근 방법: 비교 계산 worker를 구현할 때 함께 `scripts/runtime-privileges.sql`에 app의
  `bid_delta_comparison`·`bid_delta_attempt` INSERT(비교·attempt 생성은 API가 함)와 worker의
  계산 완료용 column-scoped UPDATE(`0014_prespec_overview_attempt_result`가 쓴 것과 같은
  패턴: `status`·`started_at`·`completed_at`·result 참조 열만)를 추가하고
  `tests/app/test_runtime_database_privileges.py`에 각 table의 허용 INSERT/UPDATE와 거부되는
  DELETE·다른 열 UPDATE를 고정한다.
- 상태: 수용됨. 현재 범위(공고 조건 근거 경로)는 이 권한 공백과 무관하게 동작하므로 이번
  계획에서는 수정하지 않는다.

## C-1 수동 경로가 후보 policy를 받고 그 `제외`가 기본 목록에서 숨는다 (2026-09-18, 수용됨)

- 재현 조건: C-1 공고 판정을 수동 경로(`cli_single`·`manual_run`)로 부르면 `activation_candidate` policy도 받는다 —
  `web/backend/app/screening/orchestrator.py:1623`(trigger가 `schedule`이 아니면 `activation_candidate|active` 허용),
  `web/backend/app/screening/worker.py:375-377`, `web/backend/app/screening/queue.py:427-429`. 그 결과의 `제외` 판정은
  필터가 없을 때 공고 목록 기본 조건에서 빠진다(`web/backend/app/screening/projection.py:52`의
  `DEFAULT_EXCLUDED_GRADE = "제외"`, `:585`의 `Judgment.grade != DEFAULT_EXCLUDED_GRADE`).
- 영향: 품질 게이트를 통과한 적 없는 policy의 `제외`가 담당자의 기본 보기에서 공고를 숨긴다. 테이블 채우기 같은 참조
  실행 절차(`docs/e2e-lifecycle-fill.md` 6단계의 `/runs` 화면 판정 실행)가 이 경로를 쓰므로 참조 실행 결과가 운영 화면의 기본 보기를 바꿀 수 있다.
  C-1 게이트는 0건이고 policy 둘 다 `activation_candidate`이며 `BIDOPS_SCHEDULER_ENABLED=false`다(2026-09-18 운영 확인).
- 지금 해결할 수 없는 이유: 활성화된 적 없는 policy의 `제외`를 숨기지 않게 할지, 수동 경로도 `active`만 받게 할지는
  C-1 자동화 방식과 함께 정해야 한다. 뒤쪽을 고르면 참조 실행 절차를 함께 고쳐야 한다. 일일 운영 고도화 계획은
  C-1 코드를 그대로 두고 **C-1 자동화 전까지 C-1을 운영에 쓰지 않기로** 정했다(결정 27).
- 후속 방향: C-1 자동화 때 [`0918_daily-operation/plan.md` §7](../../specs/0918_daily-operation/plan.md)의 선행조건 ② "수동 경로
  정리"에서 두 안 중 하나를 고른다. 그 전까지 C-1을 점검용으로 부른 판정은 미측정 policy의 판정이며 운영 판단의
  근거로 쓰지 않는다.

## 1280 폭 대시보드에 세로 스크롤이 생긴다 (2026-09-19, 수용됨)

- 재현 조건: viewport 1280x800에서 대시보드(`/`)를 열고 사업 추적 보류 패널이 5행일 때 페이지에 약 170px
  세로 스크롤이 생긴다. 2026-09-17 사업 추적 고도화(main 7249ae9)에서 들어온 배치이며 그 작업의 화면 확인
  때 관측한 값이다. 2026-09-19에는 다시 재지 않았다.
- 영향: 1280 폭에서 대시보드 하단 패널을 보려면 스크롤해야 한다. 가로 스크롤이나 별도 레이아웃 전환이
  아니므로 ADR-0047(지원 폭 1280~1920px) 위반은 아니다.
- 지금 해결할 수 없는 이유: 일일 운영 고도화(`feat/do-integration`) 병합 범위와 무관한 기존 main의 배치이고,
  패널 행 수·높이를 줄이는 것은 대시보드 구성 결정이다. 2026-09-19 사용자가 그대로 두기로 했다.
- 후속 방향: 대시보드를 다시 손댈 때 보류 패널의 행 상한 또는 패널 높이 배분을 함께 정한다.
