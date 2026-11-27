# 외부 계약

2026-10-21 기준 현재 RL 계약은 아래 색인의 브리핑(v2), 레코드 활동/노트, 카드 기반 참여 판정, 제안서 초안 문서와 각 도메인 DTO·validator를 따른다. 카드 판정 import 기본 정책은 v11, 역할·종합 출력 계약은 v3이며 과거 버전 파일·행은 보존한다. 코드 DB head는 `0045_engine_review`다. 계약의 존재와 실제 인수·운영 활성화는 [현황](tracking/status.md)에서 구분한다.

아래 Ollama **참조 적재** 제약은 해당 import 프로필에만 적용한다. 게이트를 통과한 Mac C-2 v5의 제품 실행·활성화는 [ADR-0072](tracking/decisions/0072-c2-mac-litellm-ollama.md)와 C-2 정책 REST 계약을 따른다.

C-2 Ollama 참조 적재는 `skills/bidops-screen/contracts/ollama-reference/`의 별도
검증 프로필을 사용한다. 기존 Phase 0 catalog·schema hash는 불변이다. 파일/DB의
C-2 v1 envelope는 유지하되 `qwen3.8:27b` identity는 새 참조 프로필로 검증한다.
정책은 `activation_candidate`·`not_measured`·활성화 차단이어야 하며, 원 실행의
`quality_status=unmeasured_reference`와 응답·사후 변환 provenance를 보존한다.
DB에는 해당 정책의 `quality_gate_status=not_measured`, `active_slot=null`로 남긴다.
기존 실행 API의 `성공`은 처리 완료만 뜻하며 품질 측정·운영 활성화를 뜻하지 않는다.
모델 판정 binding은 정책의 고정 binding과 필드별 일치해야 한다.

C-2 ranking은 순위 순서, input/result는 수집 원본 순서다. 전체 ID 집합은 같아야 하고
모델 batch는 순위 순서로 구성한다. DB 점수는 `Numeric(20,10)`으로 투영하되 원래
점수 전체 자릿수는 불변 artifact와 `result_sha256`으로 검증한다.

C-1 `candidate_selection`의 기존 `collect-candidate.v2 / candidate_pool_all /
["candidate_pool"]` 조합은 보존한다. 새 정책 버전은 `rules_version=sw-business-selection.v1`,
`mode=sw_business_all`, `include_collection_buckets=[]` 조합을 사용할 수 있다.
이 경우 `full_run`은 수집본의 `qualification_flags.sw_business_status`가 정확히 `Y`인
공고 전체를 동결한다. `N`·누락·null을 Y로 간주하지 않는다.
`single_notice`의 사용자 지정 대상과 기존 고정 `quality_sample` 계약은 유지한다.
기존 정책의 내용·digest를 바꾸거나 새 규칙을 품질 승인으로 취급하지 않는다.

웹 클라이언트, 파이프라인 subprocess, 운영 도구가 의존하는 기본 REST 경로는 `/api`다. 발주계획·사업기회 경로는 아래의 현재 버전 계약만 사용하며, 문서에 없는 경로를 추정해 호출하지 않는다.

## 계약 찾기

| 범위 | 정본 |
|---|---|
| 회사 위키 읽기·프로필·업무별 근거 | [회사 위키 REST](contracts/company-wiki.md) |
| 실회사 근거·브리핑·카드 판정·제안서 | [RL](contracts/rl.md) |
| 생애주기 목록·추적·레코드 활동/노트·입찰 delta | [생애주기 REST](contracts/lifecycle-rest.md) |
| C-2 정책·품질 게이트·일일 스위치 | [C-2](contracts/c2.md) |
| 사전규격 엔진 검토 요청·승인·읽음 | [엔진 검토](contracts/engine-review.md) |
| 사전규격 개요 run·결과 | [개요 검토](contracts/prespec-overview.md) |
| PDF snapshot·회사 핏·심층 artifact·Luna 참조 정책 | [문서·심층 검토](contracts/deep-review.md) |
| subprocess·불변 파일·적재·DB migration | [파이프라인·DB](contracts/pipeline-db.md) |
| 종료된 DEMO에서 재사용하는 코드 | [가상회사 계약](contracts/company-demo.md) |

아래 공통 REST·상태·wire shape 규칙은 위 도메인 문서와 함께 적용한다. 도메인 계약의 필드·허용 값·오류 의미는 이번 분리에서 변경하지 않았다.

## 공통 REST 규칙

- JSON 요청과 응답은 UTF-8이다. timestamp는 timezone 정보를 포함하고, 알 수 없는 값은 `null`과 사유로 표현한다.
- 목록 응답은 원칙적으로 `items`, `total`, `limit`, `offset`을 사용한다. legacy endpoint 중 배열이나 별도 pagination을 반환하는 곳은 호환성을 유지한다.
- 일반 validation 오류는 422, 존재하지 않는 자원은 404, 중복·불가능한 상태 전이는 409, 준비되지 않은 외부 의존성은 503이다.
- Lean document/deep-review API에서 router·service가 반환하는 안정 오류는 다음 형식을 사용한다. `request_id`는 요청에 UUID가 없거나 검증 전에 실패하면 `null`이다.

```json
{
  "error": {
    "code": "bundle_not_ready",
    "message": "ready document bundle이 필요합니다",
    "details": null
  },
  "request_id": "request-id"
}
```

- Lean API도 path·JSON body·multipart/form 자체가 Pydantic/FastAPI 검증을 통과하지 못한 422에는 FastAPI 기본 `{"detail":[...]}`를 반환한다. 그 밖의 Lean 안정 오류만 위 `error` envelope를 사용한다. legacy API는 다른 `{"detail": ...}` 오류도 계속 반환할 수 있으므로 소비자는 endpoint와 status에 맞는 parser를 사용한다.
- 새 API와 Lean API 응답은 내부 filesystem path, 객체 저장소 key의 자격증명, prompt, 모델 원응답, 회사 프로필 전문을 포함하지 않는다. `AttachmentResponse`에도 서버 내부 `stored_path`를 포함하지 않는다.
- Lean mutation과 actor·감사 경계에 편입된 legacy mutation은 `X-BidOps-Actor-Name`을 요구한다. 대상은 문서·심층 검토·리포트·사업기회·첨부·기관 포털·정책 mutation이다. 이 값은 감사 표식이지 인증 정보가 아니다. 비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 canonical UTF-8 percent encoding을 함께 사용한다. 형식이 없으면 printable ASCII를 그대로 보존하며 malformed·제어문자 입력은 `actor_name_invalid`로 거부한다.

### 기능 스위치 `GET /api/feature-flags` (2026-11-18)

- core가 소유하며 `BIDOPS_MODULES`와 무관하게 항상 있다(`/api/demo-config`와 같은 자리). 읽기 전용이고 다른 method는 405다. seed·migration·enqueue를 하지 않는다.
- 응답: `{"schema_version":"feature-flags.v1","rl_analysis":bool,"prespec_overview":bool,"engine_analysis":bool,"engine_review":"off"|"mock_reference"|"live"}`. `rl_analysis`=`BIDOPS_RL_ANALYSIS_ENABLED`, `prespec_overview`=`BIDOPS_PRESPEC_OVERVIEW_ENABLED`, `engine_analysis`=`BIDOPS_ENGINE_ANALYSIS_ENABLED`(2026-11-19 추가, [엔진 실행 계약](contracts/engine-runs.md)). `engine_review`=`BIDOPS_ENGINE_REVIEW_MODE`([엔진 검토 계약](contracts/engine-review.md)). 비밀값·host·모델 이름·정책 경로를 싣지 않는다.
- 소비자(관리 화면)는 `false`인 기능을 요청 전에 "이 환경에서 꺼져 있음"으로 보이고 요청 control을 막는다(설계고도화안 C-4). `true`는 그 기능의 다른 전제(실회사 등록·정책 행·전송 승인)가 갖춰졌다는 뜻이 아니며 각 API는 지금처럼 fail closed한다. 조회에 실패하면 화면은 켜져 있다고 가정하지 않고 기존 오류 경로를 그대로 쓴다.

### 목록 검색 `q`

발주계획·사전규격·사업 추적의 raw `q`는 URL/API에서 보존한다. 비교 시 Unicode White_Space 25자(`U+0009`–`000D`, `0020`, `0085`, `00A0`, `1680`, `2000`–`200A`, `2028`, `2029`, `202F`, `205F`, `3000`)와 `U+FEFF`를 제거하고 ASCII `A`–`Z`만 소문자로 바꾼다. 각 필드의 연속 부분 문자열을 독립적으로 비교한다. `%`, `_`, 역슬래시는 literal이며 공백/BOM만 있는 `q`는 검색 해제다. 서버 검색은 다른 필터와 AND이고 `total`·집계·페이지 분할 전에 적용한다.

- 사전규격은 `Notice.title|agency|demand_agency`, 사업 추적은 authoritative 소유 링크 대상의 `OrderPlan.title|agency_name`·`Notice.title|agency|demand_agency`, 발주계획은 `OrderPlan.title|agency_name|order_plan_unty_no`를 검색한다.
- 사업 추적의 2~100자 한계는 위 공백의 연속 구간을 ASCII SPACE 한 칸으로 줄여 양끝을 제거한 값의 Unicode 코드포인트 수로 검사한다. 유효한 raw `q`는 바꾸지 않는다.
- Go/No-Go의 `q`는 API 인자가 아니다. 받은 decision queue 행의 실제 `title|agency`만 클라이언트에서 검색하며 서버 `total`은 유지한다. 상세 동작은 [검색 UX 명세](0921_search-ux/spec.md)를 따른다.

## 상태와 식별자

- 수집·판정·심층 검토 실행은 서로 다른 불변 execution ID를 사용한다. 재시도는 기존 실행을 덮지 않고 새 attempt 또는 새 execution으로 남긴다.
- 공고 식별자는 외부 공고번호와 DB 내부 식별자를 구분한다. API 경로의 `{notice_pk}`와 `{notice_id}` 의미를 endpoint schema 그대로 따른다.
- 판정 실행 status는 대기, 실행, 부분 성공, 성공, 실패, 중단을 구분한다. terminal status에는 종료 시각이 있어야 한다.
- 심층 검토 attempt stage는 `requirements_and_evaluation`, `delivery_risk_economics`, `synthesis_and_validation`만 허용한다.
- `계속 추적`, `보류`, `종료`와 최종 입찰 `Go/No-Go`는 별도 필드·별도 이벤트다. 현재 final opinion 값에 임의 매핑하지 않는다. R-07의 입찰 delta·최종 결정 계약은 [ADR-0034](tracking/decisions/0034-bid-delta-final-decision.md)로 **채택**했고 R-08에서 endpoint·table·migration을 **구현**했다. 비교를 실제로 계산하는 worker와 모델 binding 실행은 아직 없다.

## JSON wire shape 규칙

아래에서 `field?`는 field가 wire에 있을 때 JSON `null`이 허용된다는 뜻이다. 생략 가능성은 `optional`, null 가능성은 `nullable`로 각각 적는다. `optional`은 생략, `nullable`은 `null`, `optional nullable`은 둘 다를 허용한다. Lean request·response는 열거하지 않은 field를 거부한다. legacy model은 호환 동작을 유지하므로 새 소비자는 정의된 field만 사용한다.

- `RunSummary`: `run_id`, `window_from?`, `window_to?`, `timezone`, `generated_at`, `screening_basis?`, `status`, `superseded_by?`, `counts`. `counts`는 `notices`, `order_plans`, `judgments`, `reviews`, `collection`이다.
- `IngestRequest`: body의 optional nullable `run_id`와 query의 optional nullable `run_id` 중 적어도 하나가 필요하다. `IngestResponse`는 `run_id`, `notices`, optional `order_plans`(기본 0), `judgments`, `reviews`, `warnings[]`, `warning_counts`다. 같은 회차 재적재는 지원되는 갱신·멱등 경로이며 중복 자체로 409를 반환하지 않는다.
- `NoticeList` query: required `run_id`; optional `grade`, `readiness`, `focus`, `sample_role`(default `analysis`), `attachment=any|none|manual`, `q`, `sort=deadline|grade|published`, `limit` 1..500(default 50), `offset` 0 이상. 응답은 `items`, `total`, 실제 적용한 `filters`다.
- `PreSpecList` query: optional `sw_only`(default `true`), `business_division`, `origin=추적|신규`, `deadline_within_days`(1..365), `q`, `sort=published|deadline|observed`, `limit` 1..500(default 50), `offset` 0 이상. 기본적으로 누적 `notice.source_type='pre_spec'`를 조회한다. `sw_only=true`는 `sw_business_status='Y'` 또는 추적 중인 발주계획 연결을 포함한다. 이 연결은 같은 opportunity의 notice 링크 status가 `확정`·`사람 확인 완료`·`후보 확인 대기` 중 하나이고 opportunity tracking status가 `계속 추적`·`보류` 중 하나이며, 그 opportunity에 authoritative `order_plan` 링크(`order_plan_id` 존재)가 있는 경우다. 따라서 `검색 미확인`, `미선택`, `종료`, authoritative order-plan 링크가 없는 연결은 예외가 아니다. 응답은 `items`, `total`, `limit`, `offset`, `overview_status_counts`이며 item은 `notice_pk`, `pre_spec_no`, `title`, `agency`, `demand_agency`(추가형, PoC), `published_at`, `deadline_at`, `budget`, 원문 그대로의 `sw_business_status`·`business_division`, `origin`, `opportunity_id`, `tracking_status`, `kept_by_tracking`, `document`, `overview_review_status`를 가진다. `demand_agency`는 사전규격 원문 `rlDminsttNm`(수요기관)이며 값이 없으면 `null`이다. **수요기관은 사전규격에서만 값이 있다** — 입찰공고는 `agency`가 이미 수요기관 우선값이라 입찰공고 상세는 `demand_agency`를 투영하지 않는다. `opportunity_id`·`tracking_status`·`origin`은 pending/rejected/search-unconfirmed link가 아니라 해당 notice의 authoritative active owner만 투영한다. `document`는 `attachments`, `완료`, `대기`, `진행`, `차단`, `실패` 건수이며 큐 행이 없는 첨부는 총계에만 포함한다. `kept_by_tracking`는 `sw_business_status`가 `Y`가 아닌 행이 위 예외로 남을 때만 `true`다. `origin`은 연결된 opportunity의 `first_registered_stage`에서 `order_plan→추적`, `pre_spec|bid_notice→신규`로 투영하고 연결이 없으면 `null`이다. `overview_review_status`(추가, 구 `docs/design/PLAN.md` 3단계, git 이력에서 확인)는 해당 notice의 최신
`prespec_overview_run.status`를 `notice_id`로 LEFT JOIN해 투영한 `PreSpecOverviewReviewStatus`
10값(`awaiting_document|awaiting_structure|preparing|awaiting_model|queued|running|completed|needs_human_review|failed|cancelled`) 중 하나이며, 그 notice에
run 행이 아직 없으면 `null`이다(개요 검토 미시작). `overview_status_counts`(추가)는
`{status, count}[]`로, 10개 계약값과 `status=null`(run 행 없음) 총 11개 항목이 이 목록 조회의
필터(`sw_only`·`business_division`·`origin`·`q`)는 전부 반영하되 `limit`/`offset`과 무관하게 **필터에 일치하는 전체 건수**를 담아 항상 존재한다(건수 0인 항목도 포함). 클라이언트는 반환된 `items`(현재 페이지)만 그룹에 채우고 그룹 헤더 건수는 `overview_status_counts`를 표시해 페이지네이션과 그룹 건수 표시를 분리한다. 응답에는 object key·로컬 경로·URL을 넣지 않는다.
  item에는 등급과 자동 문서 준비 필드 다섯이 더 있다([ADR-0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)). nullable `grade`, nullable `grade_source=screening_judgment|human_review`, 비 null `auto_preparation_status`(기본 `not_applicable`), nullable `auto_preparation_reason`, nullable `latest_deep_review_id`다. `grade`가 `null`이면 판정도 사람 정정도 없다는 뜻이고 그때 `grade_source`도 `null`이다 — 둘 중 하나만 채우거나 "없음"을 특정 등급으로 접지 않는다. `auto_preparation_status`는 `not_applicable|waiting_attachments|bundle_draft|bundle_ready|overview_running|deep_review_started|overview_settled|blocked` 여덟 값이며(2026-11-19: `overview_settled`의 옛 이름은 `deep_review_ready_for_click`이다. 저장되지 않는 파생값이라 이름만 바뀌었고 목록 술어·다음 행동은 이 값을 보지 않는다) `not_applicable`은 "대상이 아님"이지 "알 수 없음"이 아니다. `auto_preparation_reason`은 안전 코드이며 어휘는 `grade_not_priority`, `deadline_passed_untracked`(2026-11-19: 개요 플래그로 자격이 열리는 `SW사업대상=Y`이지만 의견 마감이 지났고 사업기회가 추적 중이 아니어서 자동 처리 범위 밖), `awaiting_fetch`, `no_ready_document`, `engine_review_request`([열린 요청의 문서 준비](contracts/lifecycle-rest.md#결정-대기-집계와-큐-응답)), `attachments_failed`(취득 행이 모두 `차단`·`실패`로 끝났고 준비된 문서가 없어 `blocked`가 된 경우), `bundle_has_blocking_issues`, `bundle_unchanged`, `human_bundle_draft`, `processing_failed`와 문서 묶음 service가 내는 안전 코드다. 2026-11-19부터 `overview_settled`는 사유 없이(`null`) 나간다 — 옛 `deep_review_ready_for_click`에 붙던 기존 자동 심층 시작 사유(`not_sw_business`, `bundle_not_auto_ready`, `overview_not_completed`, `service_unavailable`, `manual_request_required`, `company_fit_*`)는 목록 투영에 싣지 않고, 그 판단은 쓰기 경로(`maybe_auto_start_deep_review`)에만 남는다. 이 다섯 값은 저장된 열이 아니라 조회 시점의 파생값이며 공고 수와 무관한 상수 회 조회로 계산한다. 등급과 상태 필터는 아래 누적 탐색 계약에 따라 서버에서 적용한다.
  사전규격 검토 제외 확장(PoC, additive): item에
  `review_exclusion_status=included|excluded`(비 null), `review_exclusion_actor_name`,
  `review_exclusion_reason`, `review_exclusion_changed_at`(timezone 포함 시각)을 추가한다.
  최초 상태는 included이며 변경 정보 세 필드는 null이다.
  `review_exclusion=all|included|excluded` 필터의 기본값은 all이다. 다른 명시적 필터와 AND로
  결합한다. actionable·recent는 excluded를 항상 제외하며 tracking·all은 그대로 표시한다.
  total·페이지·workspace_counts·overview_status_counts도 같은 규칙을 쓴다. 명시적 excluded와
  actionable/recent를 결합하면 0건이다. 전체 이력 UI만 포함 여부 필터를 제공하며 URL과 선택
  fingerprint에 포함하고 다른 보기 이동 시 초기화한다. 상세 왕복 URL도 이를 보존한다.

  `POST /api/pre-specs/review-exclusions` 요청은
  `{notice_ids: int[], status: "included"|"excluded", actor_name: str, reason: str}`다.
  ID는 양의 DB integer(최대 2147483647) 1~200개로 중복을 허용하지 않는다. ID 없음·다른
  source_type·잘못된 ID가 섞이면 전체 422(`invalid_pre_spec_notice_ids`는 대상 조회 실패)다.
  actor_name·reason은 양끝 공백 제거 후 필수이며 각 128·2000자 한도다. 응답은 200
  `{items: [{notice_id, status, outcome: "changed"|"unchanged"}]}`이며 요청 순서다.
  공고를 ID 오름차순으로 잠그고 상태·마지막 변경 정보·`pre_spec.review_exclusion_changed`
  audit_event를 원자적으로 저장한다. 감사 aggregate는 notice/ID이며 safe_metadata에
  previous_status·status·actor_name·reason·changed_at을 남긴다. unchanged는 쓰기를 하지 않는다.
  별도 요청 재생 저장소는 없고 같은 목표 상태의 재요청은 unchanged로 처리한다.
  이 API는 추적·등급·리뷰·분석 자격·원본 관측을 변경하지 않는다.

  2026-09-16 누적 탐색 확장:
  `grade`(기존 등급 및 `판정 없음`), `overview_view=all|attention|pending|completed|failed|cancelled|not_started`,
  `tracking_decision=pending`, `tracking_status=계속 추적|보류|종료|미선택`, `source_run_id`,
  `observed_from`·`observed_to`(날짜), `deadline_status=open|passed|unknown`은 모두 서버 필터다.
  `workspace=actionable|recent|tracking|all`을 추가하며 미지정 API 기본값은 `all`이다.
  `sort`에는 `observed`가 추가된다. 각 필터는 페이지 분할 전에 적용한다.
  `pending`은 실제 대기·실행 상태이고 run 부재는 `not_started`로 구분한다.
  관측 기간은 한국 시간 양끝 날짜를 포함하며, 회차와 기간은 같은 관측 행에 적용한다.
  회차를 지정해도 공고 내용·분석·추적은 현재 상태다. `recent`에 양 날짜가 없으면
  한국 시간 오늘 포함 최근 7일을 적용한다. `actionable`은 개요 사람 확인 필요,
  심층 검토 클릭 대기, 개요 완료이면서 기존 신규·미선택/null 추적 결정 대기의 합집합이다.
  2026-09-22 개정([ADR-0064](tracking/decisions/0064-prespec-actionable-deadline-scope.md) 결정 4
  개정, 후속 시안 M7 ③ 승인): 그 합집합에 **추적 상태가 null 또는 `미선택`**이라는 조건을 바깥
  AND로 건다. 사람이 `계속 추적`·`보류`·`종료` 중 무엇을 골랐든 그 공고는 이유 불문 `actionable`에서
  빠지고 `tracking`(계속 추적·보류)·`all`에서 보인다. 추적 상태를 `미선택`으로 되돌리면 다시
  들어온다. 이 조건은 `workspace_counts["actionable"]`과 `deadline_scope_counts`에도 같이 걸린다.
  `recent`·`tracking`·`all`과 `next_action` 필드는 바뀌지 않는다.
  **2026-11-19 개정(사전규격 단계 수정안 §3 B):** `actionable` = 추적 상태 null 또는 `미선택`
  ∧ `overview_review_status ∈ {completed, needs_human_review}`. 옛 합집합의 "심층 검토 클릭
  대기"와 "신규" 조건은 빠진다 — 실패·취소로 끝난 개요는 더 이상 `actionable`이 아니다.
  `workspace=needs_check`(확인 필요)를 추가한다: 추적 상태 null 또는 `미선택` ∧ `actionable`이
  아님 ∧ (`overview_review_status ∈ {failed, cancelled}` ∨ `auto_preparation_status ∈ {blocked,
  bundle_draft}` ∨ `auto_preparation_reason = no_ready_document`). 두 보기는 서로소다.
  `needs_check`도 검토 제외 숨김과 `deadline_scope`를 `actionable`과 같은 순서로 적용하며,
  `workspace_counts`에 `needs_check` 키가 생긴다. 비 null `needs_check_deadline_scope_counts{current,passed}`는
  `deadline_scope_counts`와 같은 정의를 `needs_check` 분기에 적용한 분할이다.
  `tracking`은 계속 추적·보류다. 마감이 지났다는 이유로 업무 대상에서 제외하지 않는다.
  2026-09-21 확장([ADR-0064](tracking/decisions/0064-prespec-actionable-deadline-scope.md)):
  `deadline_scope=current|passed|all`(기본 `all`)을 추가한다. `current`는 `deadline_at`이
  요청 시각 이상이거나 `null`인 건, `passed`는 `deadline_at`이 요청 시각 미만인 건이다.
  두 값은 서로소이고 합집합이 전체다. `deadline_scope`는 actionable workspace 술어의
  일부다. 따라서 `workspace_counts`의 `actionable` 칸에는 활성 workspace와 무관하게
  적용되고, `items`·`total`·`overview_status_counts`에는 `workspace=actionable`일 때만
  영향을 준다. `recent`·`tracking`·`all` 칸과 그 workspace의 `items`·`total`은 영향받지
  않는다. `current`는 `마감 미확인`(null)을 포함한다 — 마감 경과로 접지 않는다.
  검토 제외 숨김은 구간 술어보다 먼저 적용하므로 제외 건은 어느 구간에도 들어가지 않는다.
  잘못된 값은 422 `deadline_scope is invalid`다. 구간 건수는 아래 집계 문단이 정의한다.
  item에는 nullable `first_observed_at`, `last_observed_at`,
  `next_action=confirm_overview|review_overview|null`이 추가된다(2026-11-19 개정: 옛
  `open_deep_review`·`decide_tracking`은 나오지 않는다). `confirm_overview`는 개요
  `needs_human_review`이며 추적 결정과 무관하다. `review_overview`는 개요 `completed` ∧ 추적
  상태 null 또는 `미선택`이다. 다음 행동은 나열된 순서로 첫 일치를 쓰며 새로운 업무 상태가 아니다.
  응답의 `workspace_counts`는 다섯 보기 이름을 키로 한 건수 map이며 활성 workspace만
  제외한 필터를 적용한다(recent의 기본 7일 조건은 recent 건수에만 적용).
  `overview_status_counts`는 활성 workspace와 나머지 필터를 적용하고 `overview_view`만
  제외한다. `total`·`items`는 모든 필터를 적용한다. 집계는 limit/offset과 무관하다.
  비 null `deadline_scope_counts{current,passed}`(2026-09-21 추가)는 구간을 적용하기 **전**
  actionable 집합을 두 구간으로 나눈 건수이며, 활성 workspace·활성 `deadline_scope`와
  무관하게 언제나 같은 값이고 언제나 존재한다. 나머지 필터(`q`·`deadline_status`·`grade`
  등)는 모두 반영하고 기준 집합은 `workspace_counts`와 같다. 두 칸의 합은 구간 미적용
  actionable 건수이고, `deadline_scope=current`이면
  `workspace_counts["actionable"] == deadline_scope_counts.current`이며
  `workspace=actionable`을 함께 주면 `total == deadline_scope_counts.current`다. 합계 키
  (`all`)는 두지 않는다 — 필요하면 소비자가 두 칸을 더한다.
  마감 정렬은 마감 전 가까운 순, 마감 경과 최근순, 미확인 순이며 ID로 동률을 해소한다.
  2026-09-22 확장([ADR-0067](tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md)):
  optional `deadline_within_days`(정수 1..365)는 의견등록 마감이
  `[요청 시각, 요청 시각 KST 일자 + N일의 끝)`에 드는 건만 남기는 **창** 필터다.
  상한은 `+(N+1)`일 00:00 KST의 열린 경계이고(D-day 표시가 날짜 단위이므로 창도 날짜로
  끊는다) 하한이 요청 시각이라 이미 지난 마감은 임박이 아니다. `deadline_at`이 `null`인
  `마감 미확인`은 창에 **들지 않는다** — 미확인을 임박으로 승격시키지 않는다(이 점이
  `deadline_scope=current`와 다르다). `deadline_status`와 같은 자리의 서버 필터이므로
  `items`·`total`과 모든 집계(`workspace_counts`·`overview_status_counts`·
  `deadline_scope_counts`)가 같은 모집단을 읽는다. 인자를 주지 않으면 창이 없다.
  범위를 벗어난 값은 422 `deadline_within_days is invalid`다.
  별도의 사전규격 **상세** endpoint는 없다. 상세 화면도 이 목록 endpoint를 쓴다.
- `NoticeListItem`: `id`, `notice_key`, `run_id`, `title?`, `agency?`, `published_at?`, `deadline_at?`, `estimated_price?`, `sample_role?`, `sample_stratum?`, `collection_bucket?`, `grade?`, `readiness?`, `focus?`, `attachment_count`, `attachment_status=none|g2b|manual`이다.
- `ReviewUpsertRequest`: required `run_id`; optional nullable `disposition`, `system_judgment_review`, `corrected_grade`, `corrected_readiness`, `weakest_perspective`, `reason`, `reviewer`; optional `verification_answers`(default `[]`), 요소는 optional nullable `item`, `answer`다. `ReviewResponse`는 `id`, `run_id`, `notice_pk`, 같은 nullable review field, `created_at?`, `updated_at?`, `answers[{id,item?,answer?}]`다. 이 legacy schema의 review 문자열은 wire enum으로 강제되지 않으므로 소비자가 임의의 추가 enum을 가정하지 않는다.
- `AgencyPortalCreateRequest`: required `agency_pattern`, `system_name`, `search_url_template`; optional non-null `enabled`(default `true`), optional nullable `note`. PATCH는 이 다섯 field의 partial body이다. PATCH `enabled`는 nullable이며 `null`을 보내면 현재 값을 바꾸지 않는 no-op이다. `AgencyPortalResponse`는 `id`, 위 다섯 field다.
- legacy `AttachmentResponse`: `id`, `name?`, `url?`, `origin?`, `file_ext?`, `size_bytes?`, `extract_status?`, `created_at?`, `acquired_file?`. `acquired_file`은 `{filename, file_ext?, size_bytes?}` 또는 `null`이다(2026-11-21 추가). 나라장터 사전규격 목록은 첨부를 주소로만 줘서 `name`이 수집 때 붙인 자리표시자(`첨부 1`)이므로, 원문을 내려받은 첨부에 한해 현재 문서 version의 실제 파일명·접미사 대문자 확장자·원문 크기를 함께 싣는다. 짝은 `document_version.attachment_id`이며 순번·주소·이름으로 추정하지 않는다. 아직 내려받지 않았거나 제공 모듈이 없으면 `null`이고 `name`·`file_ext`·`size_bytes`(첨부 행 값)는 바꾸지 않는다. `stored_path`는 wire field가 아니며 서버 내부 호환 저장 metadata로만 남는다. notice detail과 첨부 처리 상태에 nested 될 수 있고 다운로드는 `url`의 id 기반 endpoint를 사용한다.
- `RunDetailResponse`는 `RunSummary` 전체와 `collection_scope`, `pipeline[]`, `artifacts[]`, `warning_counts`다. `collection_scope`는 `window_from?`, `window_to?`, `timezone`, `business_area?`, `pre_spec_available?`, `pre_spec_reason?`, `focus_axes[]`, `performance_reference_count?`다. pipeline item은 `name`, `status`, `artifact?`, `script?`, `execution_id?`, `started_at?`, `finished_at?`, `exit_code?`, `execution_allowed`, `message?`다. artifact item은 `name`, `present`, `schema_version?`, `expected_schema_version?`, `valid?`, `warnings[]`다. legacy `status`들은 wire enum으로 강제되지 않는 string이다.
- `RunStatsResponse`: `run_id`, `timezone`, `generated_at`, `collected_count?`, `candidate_count?`, `sample_count`, `priority_review_count`, `audit_missed_count`, `funnel[]`, grade/readiness/focus `*_distribution[]`, `verification_requests[]`, `imminent_deadlines[]`. funnel item은 `key`, `label`, `count?`; distribution item은 `key`, `label`, `count`; verification request는 `item`, `count`, `notice_pks[]`, `profile_sections[]`; deadline item은 `NoticeListItem` 전체와 `blocking_verification_items[]`다.
- `WarningListResponse`: `run_id`, `items[]`, `total`, `level?`, `code?`. warning item은 `id`, `run_id`, `level`, `code`, `message`, nullable opaque JSON `context?`다. `level`은 legacy wire에서 enum으로 강제되지 않는다.
- `NoticeDetailResponse`는 `NoticeListItem` 전체와 `bid_no?`, `bid_ord?`, `source_type?`, `budget?`, `method?`, `url?`, `timezone`, nullable opaque JSON `procurement_class?`, `region_limit?`, `lifecycle?`, `qualification_flags?`, opaque JSON list `focus_matches[]`, `performance_matches[]`, `candidate_sources[]`, `performance_top_score?`, `judgment?`, `attachments[]`, `reviews[]`다.
  - `lifecycle`·`procurement_class`는 opaque JSON이며 서버 schema 검증이 없다. 사전규격 수집기가 채우는 알려진 키는 `lifecycle.pre_spec_no`, `lifecycle.bid_ntice_no_list`(문자열 그대로, 분할하지 않음), `lifecycle.changed_at`, `lifecycle.change_reason`, `procurement_class.detail`·`code`다. 화면은 문자열인지 확인해 읽으며 키가 없거나 형식이 다르면 `미확인`으로 남긴다. 특히 본공고 번호 미확인은 본공고가 없다는 뜻이 아니다.
- `JudgmentResponse`: `id`, `schema_version?`, `grade?`, `readiness?`, `primary_focus?`, `exclusion_category?`, `summary?`, `next_action?`, `perspectives[]`, `counterarguments[]`, `verification_items[]`, `matched_performances[]`. perspective는 `id`, `position?`, `name?`, `assessment?`, `reason?`, `evidence[{id,source?,status?,fact?}]`; counterargument는 `id`, `position?`, `text?`; verification item은 `id`, `item?`, `why?`, `blocking`, `status?`; matched performance는 `id`, `name?`, `match_reason?`, `mismatch_or_limit?`, `source?`, `status?`다. 이 legacy 문자열도 wire enum으로 강제되지 않는다.
- `RelatedNoticeListResponse`: `notice_pk`, `items[]`; item은 `relation=ordinal|unified|pre_spec`, `notice_pk`, `notice_key`, `title?`, `grade?`, `published_at?`, `change_reason?`다. `NoticeHistoryResponse`는 `notice_key`, `items[]`; history item은 `notice_pk`, `run_id`, `window_from?`, `window_to?`, `timezone`, `generated_at`, `grade?`, `readiness?`, `focus?`, `summary?`, `corrected_grade?`, `corrected_readiness?`, `review_reason?`다.
- `NoticeRevisionHistoryResponse`는 정확히 `notice_pk`, `judgments[]`, `reviews[]`를 갖는다. judgment item은 `id`, `sequence>=1`, `source_kind=runtime|legacy_import|carry_over`, nullable `run_id`, nullable `recording_execution_id`, nullable `source_revision_id`, nullable `origin_execution_id`, `payload_schema_version`, opaque JSON object `payload`, 64자 lowercase SHA-256 `payload_sha256`, `captured_at`이다. review item은 `id`, `sequence>=1`, `source_kind=human|legacy_import`, nullable `run_id`, nullable `judgment_revision_id`, nullable `origin_execution_id`, `payload_schema_version`, opaque JSON object `payload`, 64자 lowercase SHA-256 `payload_sha256`, `captured_at`이다. `origin_execution_id`는 judgment 승계 chain 또는 review가 고정한 exact judgment revision의 runtime root이며, legacy/unaligned 이력은 `null`이다.
- `OpportunityListResponse`는 `section_counts`, `action_reason_counts`, `items`, `total`, `limit`, `offset`이다. 기본 목록에는 `merged_into_opportunity_id`가 없는 active row만 포함한다. item은 `id`, `tracking_status=미선택|계속 추적|보류|종료`, `tracking_reason?`, `tracking_selected_by?`, `tracking_selected_at?`, `recheck_signal`, `recheck_signal_at?`, `recheck_signal_link_id?`, `first_registered_stage=order_plan|pre_spec|bid_notice`, nullable `merged_into_opportunity_id`·`merged_at`·`merge_reason`, `section?`, `action_reasons[]`, nullable `hold_review_due_at`, `links[]`다. `first_registered_stage=order_plan`이면 화면 의미는 `추적`, 그 밖의 `pre_spec|bid_notice`이면 `신규`이며 이 매핑을 화면이 다시 정하지 않는다. `section_counts`는 `조치 필요`·`추적 중`·`보류`·`추적 종료`·`신규 입찰공고`·`미결정` 6키다. `action_reason_counts`는 `new_link`·`candidate_pending`·`merge_confirmation`·`blocking_item`·`hold_overdue` 5키이며 현재 활성 `reason` 필터만 뺀 조건으로 센다(spec §7.4). 구역·사유 정의는 아래 "사업기회 구역·사유·보류 기한" 절을 따른다.
- `OpportunityDetailResponse`는 위 사업기회 field와 `links[]` 전체를 반환한다. link는 `id`, `stage=order_plan|notice`, `link_type=official|candidate`, `status=확정|후보 확인 대기|사람 확인 완료|검색 미확인|사람 확인 병합`, `search_strategy?=full|breaking_split|normalized|longest_fragment|prefix12|merge_confirmation`, `attempted_strategies[]`, `agency_match?`, `last_searched_at?`, `evidence_external_no?`, `evidence_bid_no?`, `search_target_kind?=pre_spec|bid_notice`, `human_decision?`, `reviewer_name?`, `reviewed_at?`, `review_reason?`, `record_type?`, `record_id?`, `notice_id?`, `order_plan_id?`, `source_type?`, `title?`, `agency?`, `external_id?`, `record_external_id?`, `budget?`, `deadline_at?`, `planned_order_year?`, `planned_order_month?`(추가형, PoC)다. 뒤 넷은 link 단위 값이다 — link이 공고(`notice`)를 가리키면 `budget`·`deadline_at`을, 발주계획(`order_plan`)을 가리키면 `budget`(=`budget_amount`)·`planned_order_year`·`planned_order_month`를 싣고 대상이 없거나 해당하지 않는 필드는 `null`이다. 서버는 사업기회 단위의 "대표 마감"을 고르지 않는다. `검색 미확인` link도 포함하며 이 상태를 `사전규격 없음`으로 변환하지 않는다. `사람 확인 병합`은 병합으로 끝난 후보 수락 link(비소유, `human_decision=accepted`)이고, `search_strategy=merge_confirmation`은 사람 상태가 있는 사업기회끼리 자동 병합을 거부해 만든 `후보 확인 대기` link다(spec §3.2·§3.3). `search_target_kind`는 `검색 미확인` link가 어느 종류를 찾다 실패했는지 구분한다. target이 있으면 `title`·`record_external_id`가 해당 공고 또는 발주계획을 가리키고, `id`와 `evidence_external_no`로 link 자체와 근거 번호를 식별한다. raw record, filesystem path, object-store metadata는 반환하지 않는다.
- `TrackingStatusUpdateRequest`는 body의 `tracking_status`와 nonblank `reason`만 받는다. actor는 body에 두지 않고 `X-BidOps-Actor-Name` header에서 얻는다. `tracking_status`는 위 네 값만 허용하며 서버 시각을 `tracking_selected_at`으로 기록한다. `미선택`으로 되돌릴 때 현재 row의 작성자·이유·시각은 null이지만 감사 이벤트에는 남는다. `status`·`tracking_reason`는 이전 호출자와의 호환 입력 alias이며 새 client는 canonical field를 사용한다.
- authoritative opportunity link는 `(official + 확정)` 또는 `(candidate + 사람 확인 완료 + human_decision=accepted)`뿐이다. 후보 대기·거절·검색 미확인은 소유권과 자동 병합에 사용하지 않고 이력으로 보존한다. `PATCH /api/opportunities/links/{link_id}/decision`은 actor header와 `{decision: accepted|rejected, reason}`을 받아 후보 판정·검토 시각·감사 이벤트를 같은 transaction에 기록한다. 같은 reviewer·decision·reason 재전송은 기존 결과를 반환하고 다른 재판정은 409다.
- `AttachmentProcedureResponse`: `notice_pk`, `agency?`, `bid_no?`, `title?`, `status`, `matched_portal?`, `search_url?`, `portal_message`, `steps[]`, `attachments[]`. 현재 producer의 status는 `missing|provided|completed`이지만 legacy schema는 일반 string으로 받는다. `AttachmentQueueResponse`는 `run_id`, `total`, `items[]`; item은 `NoticeListItem` 전체와 `bid_no?`, `matched_portal?`, `search_url?`, `portal_message`다.
- `ValidationMetricsResponse`: `run_id`, `metrics[]`. metric은 `key`, `label`, `value?`, `percentage?`, nullable opaque JSON `threshold?`, `meets_threshold?`, `status=pass|fail|measured|not_measurable`, `basis`, `reason?`; basis는 `numerator`, `denominator`, opaque JSON object `detail`이다.
- `ProfileSectionsProjectionResponse`: `schema_version=bidops.profile-projection.v1`, `profile_version`, `profile_digest`, `sections[]`, `status_counts`, `error_codes[]`. section은 `id`, `number?`, `title`, `heading`, `level`, `state=confirmed|inferred|unknown|mixed|unrecorded`, `status_counts`, `items[]`, `error_codes[]`, `children[]`다. item은 `key`, `label`, `section_id`, `section_number?`, `status=confirmed|inferred|unknown`, `value?`다.
- `ProfileUnknownsProjectionResponse`: 같은 schema·profile binding, `items[]`, `total`, `reference_fields`, `error_codes[]`. item은 `key`, `label`, `section_id`, `section_number?`, `section_title`, `status=unknown`, `value?`, `reference_count?`, `reference_status=counted|unavailable`다. 두 projection은 filesystem `source`, source line, `raw_blocks`, `raw`, 자유 형식 `parse_errors`를 허용하지 않는다. 절 구조화 실패의 위치는 section `id`·`number?`·`title`·`heading` 요약으로만 제공한다. `error_codes`는 `profile_snapshot_unavailable|profile_source_unavailable|profile_yaml_unclosed|profile_yaml_invalid|profile_section_unstructured|profile_references_unavailable` 중 하나이며 예외 문자열을 포함하지 않는다.
- snapshot list item은 `version`, `digest`, `source_kind=working_tree|git_blob`, `created_at`를 반환한다. `source_kind=git_blob`일 때만 `source_ref`에 40자 lowercase commit SHA가 추가되며, `working_tree`의 저장소 상대 경로 `source_ref`는 wire에서 생략하고 내부 provenance로만 보존한다.
- 이전 profile wire의 `source`, source line, `raw_blocks`, `raw`, `parse_errors`, working-tree `source_ref`는 역사적 구현 사실일 뿐 현재 응답에는 더 이상 포함되지 않는다.
- `PipelineExecutionResponse`: `execution_id`, `source_run_id`, `result_run_id?`, `stage`, `status`, start/finish, `exit_code?`, `error?`, `log_count`. log 응답은 `run_id`, `executions[]`, `items[{timestamp,stream,level,message}]`, `total`이다.
- screening create request는 `policy_version`, `profile_source=current|git:<40 lowercase hex>`, `requested_by`다. stop request는 `requested_by`다.
- `ScreeningExecutionResponse`: `queue_no`, `execution_id`, `trigger=cli_single|manual_run|quality_gate|schedule`, `source_run_id`, `scope=single_notice|full_run|quality_sample`, `notice_id?`, `status=대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨`, `requested_by`, `policy_version`, `prompt_version`, `model_name`, `model_digest`, `company_profile_version`, `company_profile_digest`, `generation_config`, `generation_config_digest`, `input_artifact_digest`, `queued_at`, `started_at?`, `finished_at?`, `heartbeat_at?`, `stop_requested_at?`, `stop_requested_by?`, `stop_reason=user_requested|process_interrupted|null`, `candidate_count`, `completed_count`, `failure_count`, `published_run_id?`, `error_summary?`, `queue_position?`, `current_notice_id?`, `current_stage?`, `result_urls`. result URL field는 nullable `decisions`, `failures`, `telemetry`, `screening_result`, `published_run`이며 non-null 값은 `/api/`로 시작한다.
- execution은 `single_notice`일 때만 `notice_id`를 갖는다. `대기`일 때만 `queue_position`이 필수이며, `중지 요청`은 요청 시각·actor를 필요로 한다. terminal `성공|부분 성공|실패|중단됨`은 `finished_at`이 필수다. model/profile/generation/input digest는 64자 lowercase SHA-256이고 profile version과 digest는 서로 일치한다.
- `current_stage`는 `기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|counterargument|synthesis|merge|publish|null`이다. `ScreeningExecutionDetailResponse`는 execution field 전체와 `attempts[]`, `failures[]`다. attempt는 `attempt_id`, `execution_id`, `notice_id`, `stage`, `attempt_no`, `status=success|failure`, `failure_type?`, `done_reason?`, `trace_id`, `span_id`, `prompt_eval_count?`, `eval_count?`, `prompt_eval_duration_ns?`, `eval_duration_ns?`, `load_duration_ns?`, `total_duration_ns?`, `generation_config_digest?`, `num_ctx?`, `num_predict?`, `started_at`, `finished_at`, `error_summary?`다. OpenAI 호환 transport로 통일한 뒤([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)) `done_reason`은 provider의 `finish_reason`을 담고 `prompt_eval_count`·`eval_count`는 `usage.*`에서 온다. **`*_duration_ns` 네 열은 항상 `null`이다** — 응답에 서버 측 소요 시간 계측이 없고, client 측 경과 시간으로 채우면 과거 회차의 계측과 뜻이 다른 숫자가 같은 열에 섞이기 때문이다. 0으로 바꾸지 않는다. attempt stage는 `기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|counterargument|synthesis|carried_over_validation`이다.
- failure는 `notice_id`, `failed_stage=기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|반론 검토|종합 판정|병합·검증`, `failure_type=timeout|truncated_output|schema_violation|evidence_missing|counterargument_repetition`, `last_attempt_at`, `retry_count`, `status=사람 검토 대기`, `failure_context=carried_over_validation|null`, `trace_id?`, `span_id?`, `error_summary`다. success attempt에는 failure type이 없고 failure attempt에는 필수다.
- quality gate create request는 `purpose=model_comparison|operational_approval`, `policy_version`, `profile_source`, `created_by`다. comparison은 고정 역사 Git profile, approval은 `current`만 허용한다. review upsert는 `reviewer`, `evidence_judgment=동의|근거 부족|판단 보류`, optional note다.
- `QualityGateResponse`: `gate_id`, `purpose`, `execution_status=대기|실행 중|완료|실패|중단됨`, `result_status=통과|미달|미측정|보류`, `baseline_run_id`, `sample_artifact_digest`, `baseline_decisions_digest`, `policy_version`, `prompt_version`, `model_name`, `model_digest`, `company_profile_version`, `company_profile_digest`, `generation_config`, `generation_config_digest`, `pass_a_execution_id`, `pass_b_execution_id`, `created_by`, `created_at`, `completed_at?`, `latest_evaluation_id`, opaque `metrics`, `reasons[]`. terminal execution은 completion time이 필수이고 비terminal에는 없으며 pass A/B ID는 다르다.
- `QualityGateDetailResponse`는 gate field 전체와 `pass_a`, `pass_b`, `evaluations[]`, `reviews[]`다. evaluation은 `evaluation_id`, `gate_id`, `revision`, `result_status`, opaque `metrics`, `reasons[]`, `valid_review_count`, `distinct_notice_review_count`, `generation_config`, `generation_config_digest`, `created_at`이다. review는 `review_id`, `gate_id`, `execution_id`, `notice_id`, `decision_digest`, `reviewer`, `evidence_judgment`, `note?`, `created_at`, `updated_at`이다.
- policy create request는 `policy_version`, `created_by`, `prompt_version`, 정확히 다섯 perspective prompt object, `counterargument_prompt`, `synthesis_prompt`, `candidate_selection`, `thresholds`를 가진다. candidate request는 `confirmed_by`, activation request는 `quality_gate_result_id`와 `confirmed_by`다. `PolicyVersionResponse`는 `schema_version=bidops.screening-policy.v1`, `policy_version`, `prompt_version`, `perspective_prompts`, `counterargument_prompt`, `synthesis_prompt`, `candidate_selection`, `thresholds`, `content_digest`, `status=draft|activation_candidate|active`, `created_at`, `created_by`, `activated_at?`, `activated_by?`, `quality_gate_result_id?`다. active일 때 activation metadata 세 field는 모두 필수이고 나머지 status에서는 모두 null이다. activation response는 `policy`, `previous_active_policy_version?`, `quality_gate_result_id`, `activation_status=activated`, `activated_at`이다.
- schedule settings update는 optional nullable `daily_time`, `weekly_time`, `prespec_enabled` 중 non-null 하나 이상과 required `updated_by`가 필요하다. 시각은 24시간 `HH:MM`이다. `ScheduleSettingsResponse`는 `timezone=Asia/Seoul`, `daily_time`, `weekly_time`, `prespec_enabled`, `updated_at`, `updated_by`다. schedule execution create는 `job_kind=daily|weekly`, `window_from`, `window_to`, optional nullable `recovery_of_execution_id`, required `requested_by`다. daily window는 하루, weekly는 월→일 7일이다.
- `ScheduleExecutionSummary`: `run_key`, `run_id?`, `window_from`, `window_to`, `job_kind`, `status=예약|실행 중|성공|부분 성공|실패|건너뜀`, `execution_id`, `trigger=schedule|manual`, `duplicate_of_execution_id?`, `recovery_of_execution_id?`, `skip_reason?`, `failure_reason?`, `requested_by`, `started_at?`, `finished_at?`, `candidate_count?`, `result_count?`, `failure_count?`, `partial_artifact?`, `policy_version?`, `model_name?`, `model_digest?`, `prompt_version?`, `company_profile_version?`, `company_profile_digest?`, `generation_config?`, `generation_config_digest?`다. daily run key는 `YYYYMMDD-YYYYMMDD`, weekly는 `weekly:YYYYMMDD-YYYYMMDD`다. duplicate와 recovery는 동시에 있을 수 없고 duplicate는 `건너뜀`+필수 skip reason, recovery는 manual trigger다. profile·generation binding은 각각 pair다. list는 `items,total,limit,offset`이다.
- always-on update는 `enabled`, `confirmed_by`, optional nullable `quality_gate_result_id`이며 enabled일 때 gate ID가 필요하다. `AlwaysOnSwitchResponse`는 `configured_enabled`, `effective_enabled`, `environment_enabled`, `quality_gate_status?`, `quality_gate_result_id?`, `policy_version?`, `model_name?`, `model_digest?`, `prompt_version?`, `company_profile_version?`, `company_profile_digest?`, `generation_config?`, `generation_config_digest?`, `updated_at`, `updated_by`, `rejection_reason?`다. profile version·digest와 generation config·digest는 각각 둘 다 있거나 둘 다 null이어야 한다.

## 추출 분석 엔진

[엔진 실행 계약](contracts/engine-runs.md)은 별도 mock_reference 실행의 접수·계보·현재성·결과 조회를 정의한다. 기존 RL 판정·사람 결정 계약을 대체하지 않는다.
