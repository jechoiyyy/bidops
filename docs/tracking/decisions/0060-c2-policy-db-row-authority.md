# C-2 policy의 활성 정본은 DB 행이고 파일의 상태성 필드는 발행 시점 스냅샷이다

- 상태: 채택 — 계약만 (2026-09-19 사용자 승인: 활성 정본 = DB 행, 전송 승인 단위 = binding 튜플, 일일 스크립트 actor = cron 설치자. 구현은 `docs/0918_daily-operation/plan.md` 웨이브 2~4, 운영 활성화는 사람 결정 D-a~D-e 뒤)
- 일자: 2026-09-18
- 관련 결정: [ADR-0038](0038-order-plan-c2-phase0-contracts.md) 부분 개정(binding `status` 허용값, "현재 차단 경계"의 실행 조건), [ADR-0017](0017-human-enabled-quality-gate.md)(품질 게이트 통과 후 사람이 활성화), [ADR-0037](0037-order-plan-c2-bm25-top300-qwen.md)(C-2 방식), [ADR-0042](0042-c2-model-revision-declared-at-deployment.md)(model revision 선언), [ADR-0061](0061-daily-collection-window.md)(일 단위 수집)
- 근거 요청: 일일 운영 고도화 계획(`docs/0918_daily-operation/`) intent 결정 2·18~22, spec §1·§3·§4·§8
- 정본: wire·DB 세부는 [`docs/contracts.md`](../../contracts.md)의 "C-2 수동 REST 계약"과 "C-2 DB·migration 경계"

## 맥락

C-2 실행 API는 DB의 policy 행이 `policy_status='active'`이고 `quality_gate_status='passed'`이기를 요구한다
(`web/backend/app/screening/services/order_plan_screening.py:256`). 그런데 같은 서비스(`:262`)와 worker
(`workers/order_plan.py:265`)가 **policy 파일 payload**의 `policy_status`도 `active`이기를 요구하고, worker는 binding
`status`가 정확히 `blocked`이기를 요구한다(`:274`). 동시에 worker는 `external_transport.execution_allowed is True`를
요구하므로, 실행하려면 "`blocked`인 채로 실행이 허용되고 policy 파일이 `active`로 다시 발행된" 조합이 필요하다.

policy 파일을 `active`로 다시 발행하면 sha256이 바뀌고 binding의 `policy.sha256`, DB 행의 `policy_sha256`이 연쇄로
따라간다. DB 행의 payload·digest는 immutable이므로 새 `policy_version`이 필요하다 — 파일을 정본으로 두면 활성화할
때마다 버전이 늘어난다.

`policy_status`만의 문제가 아니다. 파일에는 시간이 지나면 바뀌는 상태가 더 있다 — `activation.status/enabled/
approved_by/approved_at/blockers`, `quality_gate.status/targets/human_adjudication_count/draft_label_count/
remaining_confirmation_count/activation_eligible`, `audit_sample.status/pending_decision`. 품질 게이트는 그 파일의
digest로 측정하므로 측정 뒤 이 값을 고치면 측정이 무효가 된다. 같은 순환이다.

게이트 측정에도 순환이 있다. 실행 API가 active policy만 받으면 "게이트를 통과하려면 실행 결과가 필요하고, 실행하려면
게이트 통과가 필요하다". 지금까지의 참조 실행은 테스트용 SQL로 DB 행을 직접 active로 만든 것이라 활성화 근거가 될 수
없다(`CLAUDE.md` 강제 게이트). batch 구성만 바꿔도 판정이 41/65/194 → 25/77/198로 흔들린 전례가 있어 실험 산출물
재채점도 제품 결과를 대표하지 못한다.

마지막으로 매일 무인 실행이 필요하다. 요청 스키마(`schemas/order_plans.py:16-22`)는 추가 필드를 거부하고 `producer`를
`human-review-client`로 고정하며, actor 검증은 `system`을 거부한다(`core/api_errors.py:103`). 건별 전송 승인은 매일
무인으로 도는 실행과 양립하지 않는다.

## 결정

### 1. 활성 여부의 정본은 DB 행이다

`order_plan_screening_policy` 행의 `policy_status`·`quality_gate_status`·`active_slot`이 활성 여부의 유일한 정본이다.
운영 실행 게이트는 `row.policy_status == 'active' ∧ row.quality_gate_status == 'passed'`와 digest 일치만 본다.
서비스(`:262`)와 worker(`:265`)의 파일 payload `policy_status == 'active'` 검사는 없앤다. 파일 `policy_status`는
enum 유효성(`draft|activation_candidate|active|retired`)만 검사한다. worker의 `:282`는 "파일과 binding의
`policy_status`가 서로 같다"는 상호 일치만 유지한다.

활성 권한은 실행 디렉터리를 만드는 유일한 생산자인 서비스가 DB 행으로 판정한다. worker의 역할은 실행 디렉터리
artifact의 digest 일치 확인이지 활성 권한 판정이 아니다.

### 2. 파일의 상태성 필드는 전부 발행 시점 스냅샷이며 어떤 게이트도 읽지 않는다

policy 파일의 다음 필드는 발행 당시의 기록일 뿐이다. 실행·활성화·조회 blocker·스위치 어디에서도 읽지 않는다.

- `policy_status`
- `activation.status`·`enabled`·`approved_by`·`approved_at`·`blockers`
- `quality_gate.status`·`targets`·`human_adjudication_count`·`draft_label_count`·`remaining_confirmation_count`·`activation_eligible`
- `audit_sample.status`·`pending_decision`

파일에서 읽는 것은 **설정값뿐**이다 — policy `audit_sample.enabled`·`max_per_execution`·`review_cadence`·`strata`·
`selection_order`·`replacement`, binding `external_transport.*`. 파일 스키마(`bidops.order-plan-screening-policy.v1`)는
바꾸지 않는다. v3 파일의 `quality_gate.targets`는 `null`로 발행한다.

- **blocker와 활성화 가능 여부는 전부 런타임에서 계산한다** — DB 게이트 행과 evaluation, binding, 컨테이너의 파일
  존재, 스위치. 조회 API의 blocker와 활성화 검증은 같은 조건을 쓰므로 둘의 답이 갈리지 않는다.
- **임계값 4개의 정본은 DB 게이트 행**(`order_plan_screening_quality_gate.threshold_*`)이다. 값이 `NULL`이면 사람
  결정(D-b)이 없다는 뜻이고 evaluation은 `미측정`만 기록되며 활성화는 fail closed한다.

효과: 활성화·retire·게이트 통과가 policy 파일 재발행을 요구하지 않는다. D-c(`audit_sample`)·D-d(`external_transport`)
값을 넣으려고 v3 policy·binding을 **한 번** 발행하고, 그 뒤로는 DB 행만 바뀐다.

### 3. binding `status` 허용값을 넓히고 모순 조합은 거부한다

worker와 서비스는 binding `status ∈ {blocked, activation_candidate, approved}`를 받는다. 단 `status == "blocked"`이면서
`external_transport.execution_allowed is True`인 조합은 모순이므로 `binding_mismatch`로 거부한다. 지금까지 실행에 필요한
유일한 조합이 바로 이것이었다. v3 binding은 `activation_candidate` 또는 `approved`로 발행한다. ADR-0038 "현재 차단 경계"의
`blocked` binding은 v1·v2의 발행 당시 사실로 남는다.

### 4. digest는 파일 bytes 기준이고 운영 컨테이너에 파일이 항상 있어야 한다

policy·binding의 digest는 `sha256(파일 bytes)`다. canonical 재직렬화가 아니다 — v2 파일은 canonical JSON이 아니며 파일
digest(`fa58501f…`)와 canonical digest(`9161c120…`)가 다르다. `_policy_binding`(`services/order_plan_screening.py:264-271`)은
마운트된 파일이 digest 일치일 때만 파일 bytes를 쓰고 없으면 canonical로 fallback해 항상 `binding_mismatch`가 된다. 따라서
운영 컨테이너에 `BIDOPS_C2_POLICY_PATH`·`BIDOPS_C2_BINDING_PATH` 파일이 항상 있어야 하고, 없으면 조회 blocker
`policy_file_missing`으로 드러난다. 적재 CLI(`python -m app.screening.c2_policy load`)는 파일 bytes의 digest를 기록하고
파일의 상태성 필드 값과 무관하게 행을 항상 `draft`로 만든다.

`skills/bidops-screen/scripts/validate_order_plan_phase0.py`는 **v2 phase-0 증거 전용**이다. 20260827 phase-0 증거에
고정돼 있고 gold의 `activation_eligible is False`를 요구한다(`:1365`). v3 binding은 이 validator의 검증 범위 밖이며
v3의 정합성은 적재 CLI 검증과 런타임 blocker가 맡는다.

### 5. 전송 승인의 단위는 binding 튜플이다

외부 전송 승인(D-d)의 단위는 immutable 튜플 (policy, binding, `model_digest`, 호출 대상 allowlist)이다. v3 binding의
`external_transport`는 `execution_allowed`, `approval_scope: "per_binding"`, `approved_by`, `approved_at`,
`approval_required_per_execution: false`를 갖는다. 튜플의 어느 하나가 바뀌면 새 binding·새 policy 버전이 필요하고 기존
policy는 retire한다. 승인자·시각·`model_digest` 값이 비어 있으면 `execution_allowed=true`로 발행하지 않는다.

`CLAUDE.md`의 "외부 모델은 승인된 payload만 건별 전송한다"와의 관계:

- **payload 승인은 그대로다.** 나가는 것은 binding이 고정한 승인 prompt·회사 역량 요약·generation config와 발주계획
  제목뿐이고, 실제 발주계획 번호는 보내지 않는다(`docs/contracts.md` "C-2 stage 2 wire 계약"). 모든 실행이 이 digest
  일치를 검사하고, 어긋나면 호출 전에 거부한다. 무엇을 보내도 되는지의 승인은 여전히 payload 형태 단위다.
- **바뀌는 것은 승인 행위의 단위뿐이다.** 같은 튜플 안의 실행마다 사람이 다시 승인하지 않는다. 튜플을 승인한 기록
  (`approved_by`·`approved_at`)이 그 튜플로 나가는 모든 전송의 승인이다. hosted provider fallback 금지는 그대로다.

### 6. 일일 스크립트의 actor는 cron을 설치한 사람이다

일일 스크립트와 `run-daily-c2.sh`는 실행 API를 사람 경로와 같은 REST로 부르고 actor는 `human`이다.
`BIDOPS_C2_DAILY_ACTOR`는 필수이고 기본값이 없다. 이것은 "cron을 설치하고 자기 이름을 actor로 넣은 사람의 옵트인"으로
해석한다 — 그 사람이 매일의 실행 버튼을 미리 누르기로 한 것이다. `core/api_errors.py:103`이 `system`을 거부하므로
시스템 actor는 만들지 않는다. 앞 판이 scheduler 경로만 "`human` 위조"로 기각했던 근거는 cron 스크립트에도 똑같이
해당하므로 기각 근거로 쓰지 않는다. scheduler를 C-2에 붙이지 않는 이유는 `docs/PLAN.md` Phase 6의 수정 금지 제약이다.

트리거 표식은 요청 헤더 `X-BidOps-Trigger: daily_script | manual_resume | gate_measurement`로 보낸다. 헤더가 없으면
사람의 수동 운영 실행이다. 요청 본문 `execution-create-request.v1`은 바꾸지 않고, 헤더는 요청 hash에 들어가지 않는다.
표식은 audit `safe_metadata.trigger`에 남고 `actor_kind`는 `human` 그대로다.

### 7. 일일 자동 실행은 환경 cap과 버전에 묶인 DB 스위치가 모두 켜질 때만 돈다

`effective_enabled`는 네 조건이 모두 참일 때만 참이다(4중 기본-닫힘).

1. 환경 cap `BIDOPS_C2_DAILY_TRIGGER_ENABLED`(기본 false) — 운영자가 설치 때 한 번 켠다
2. DB 스위치 — 현재 active `policy_version`의 최신 `order_plan_screening_daily_trigger` 행이 `enabled=true`
3. `BIDOPS_C2_EXECUTION_ALLOWED` ∧ binding `external_transport.execution_allowed`
4. policy 행 `active` + `quality_gate_status='passed'` + policy·binding 파일 존재

스위치는 append-only 행이고 policy 버전에 묶인다. 새 버전을 활성화하면 새 버전에는 행이 없으므로 스위치는 꺼진다. 옛
버전에 켜진 행이 남아 있으면 사유 `switch_bound_to_other_version`으로 드러난다. 서비스는 `daily_script`·`manual_resume`
요청에 같은 조건을 다시 검사하므로 스크립트가 조회를 건너뛰어도 실행은 생기지 않는다. 활성화와 스위치를 켜는 것은
**별개의 사람 결정**이다(D-e).

### 8. 게이트 측정은 후보 상태의 측정 전용 실행으로 한다 — D-f를 제품 재실행으로 닫는다

`X-BidOps-Trigger: gate_measurement` 실행은 policy 행이 `activation_candidate` 또는 `active`이면 `quality_gate_status`를
요구하지 않는다. 그 대신 `source_run_id`가 그 policy_version의 gate 중 하나의 측정 회차 목록(`measurement_run_ids_json`)에
있어야 한다 — 측정 경로로 일일 회차를 돌리는 우회를 막는다. 전송 승인·환경 변수·digest·파일 존재·active slot 1은 운영
실행과 똑같이 적용한다. 일일 스위치와 환경 cap은 요구하지 않는다(사람이 돌린다). 결과 실행 행은
`purpose='gate_measurement'`이고 누적 투영·워크로드·감사 표본에서 빠진다.

D-f(측정 방식)를 **제품 재실행**으로 닫는 이유: 측정 대상은 "정확히 이 설정 묶음이 제품 경로에서 내는 결과"다. 제품 경로를
그대로 타야 batch 구성·prompt 조립·transport·병합까지 운영과 같은 조건이 된다. 실험 산출물 재채점은 그 조건을 보장하지
못한다(위 41/65/194 → 25/77/198 전례).

- gate의 `evaluation_basis`는 `product_rerun | reference_artifact_rescore`다. **활성화를 여는 것은 `product_rerun`뿐이다.**
  `reference_artifact_rescore` gate의 evaluation은 `통과`여도 활성화를 열지 못하고, `reasons`에 "제품 파이프라인이 낸
  결과가 아님"이 반드시 남는다. `CLAUDE.md`의 "참조 실행 결과를 운영 근거로 적지 않는다"를 데이터로 강제한다.
- 채점은 게시일별이 판정이다. 같은 묶음으로 두 번(pass 1·2) 돌려 둘 다 통과해야 `통과`다. evaluation의 `measured_*`는
  두 pass 중 나쁜 쪽 값이다. 판정 규칙은 "하나라도 미달이면 차단"이고 계산 불가(`미측정`·`보류`)를 통과로 바꾸지 않는다.
- 코드는 채점하지 않는다. 사람이 만든 gate artifact를 기록하고 연결·판정 규칙만 검사한다.

## 대안

- **파일을 정본으로 두고 활성화마다 파일을 재발행** — 기각. 활성화·retire·게이트 통과마다 새 `policy_version`이 생기고
  재발행 순간 측정이 무효가 된다(맥락의 순환).
- **`policy_status`만 스냅샷으로 강등하고 나머지 상태성 필드는 계속 읽기** — 기각. `activation.blockers`·
  `quality_gate.activation_eligible`을 읽는 조회와 읽지 않는 활성화의 답이 갈린다. 같은 순환이 필드 하나 옆에서 반복된다.
- **기존 C-1 `quality_gate` 테이블 재사용** — 기각. `policy_version`·`pass_a/b_execution_id`·`company_profile_version`·
  `baseline_run_id`가 전부 NOT NULL이고 C-2는 어느 것도 채울 수 없다. `purpose`에 값을 더하면 C-1 활성화 경로
  (`PolicyRepository._valid_gate`, `docs/model-quality-gate.md`)를 전부 재검토해야 한다. C-2 전용 4테이블을 둔다.
- **테스트용 SQL로 행을 active로 만들어 측정** — 기각. 활성화 근거가 될 수 없는 참조 실행이다.
- **실험 산출물 재채점만으로 게이트 통과** — 기각. 제품 결과를 대표하지 못한다. 비교·탐색용 기록(`reference_artifact_rescore`)
  으로만 남긴다.
- **실행마다 사람 승인(건별 전송 승인 유지)** — 기각. 매일 무인 실행과 양립하지 않는다. 호출 대상 셋이 binding digest에
  고정돼 있고 모든 실행이 digest 일치를 검사하므로 튜플 승인으로 같은 보장을 얻는다.
- **요청 본문에 `trigger` 필드 추가(`execution-create-request.v2`)** — 기각. 스키마가 추가 필드를 거부하고, 표식을 본문에
  넣으면 idempotency hash가 바뀐다. 헤더로 보낸다.
- **scheduler에서 C-2 호출** — 이 결정의 범위 밖이다. `docs/PLAN.md` Phase 6이 별도 ADR과 별도 변경 계획을 요구한다.

## 결과

- 신규 DB 4테이블(`order_plan_screening_quality_gate`, `order_plan_screening_quality_evaluation`,
  `order_plan_screening_audit_sample`, `order_plan_screening_daily_trigger`)과 `order_plan_screening_execution.purpose`
  열이 Alembic `0029`로 들어간다. evaluation·audit_sample·daily_trigger는 append-only다.
- 신규 REST: policy 목록·단건·후보 지정·활성화, 품질 게이트 생성·조회·evaluation 기록, 감사 표본 미리보기·기록, 일일 자동
  실행 스위치 조회·설정. wire는 `docs/contracts.md`가 정본이다.
- 이 결정은 계약만 고정한다. 임계값(D-b)·gold 승인(D-a)·감사 표본 값(D-c)·전송 승인 값(D-d)이 없으면 모든 경로가 fail
  closed한다 — 게이트는 `미측정`, 활성화는 `activation_blocked`, 감사 표본은 `pending_human_approval`, 실행은 503,
  자동 실행은 `effective_enabled=false`. 활성화와 스위치를 누르는 것은 사람이다(D-e).
- `validate_order_plan_phase0.py`와 v1·v2 policy·binding 파일은 바꾸지 않는다. v3 발행과 compose 마운트 변경은 사람
  결정 뒤 별도 단계다.
- `docs/PLAN.md` Phase 5의 "실행 버튼은 사람이 눌러야 한다"는 "사람 또는 사람이 옵트인한 일일 스크립트"가 된다.
