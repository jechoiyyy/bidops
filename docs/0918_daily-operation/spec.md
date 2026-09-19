# 일일 운영 고도화 — 명세

- 상태: 초안 (구현 착수 전). 2026-09-18 fable 검토와 같은 날 2차 검토 인터뷰(결정 10~27)를 반영해 개정했다. 의도는 [`intent.md`](intent.md), 순서는 [`plan.md`](plan.md).
- 이 문서는 **바뀐 뒤의 동작**을 적는다. 값이 사람 결정에 달린 곳은 `null`로 두고 추정하지 않는다.

## 0. 바뀐 뒤의 하루

네 장면으로 적는다. 기준일은 항상 **전일(KST)** 이다(scheduler 일일 예약 관례와 같다, `scheduler.py:373`).

### ⓐ 구현이 끝난 직후 — 아직 활성화 전

```
매일 D일 — cron 한 줄만 돈다
  cron B  run-daily-lifecycle.sh --track notices
    1 preflight
    2 공고 수집      lifecycle-<D−1>-notices  창 [D−4, D−1] 4일(양끝 포함). 사전규격+입찰공고 (§9.4)
    3 적재: notices --collection → --tracked-backfill → 첨부 자격 갱신
    └ 상시 워커(이벤트, 기존 동작): 첨부 취득 → 문서 준비 → 사전규격 개요 → 게이트 통과 시 심층 검토

  발주계획 트랙은 보류다(결정 10). cron A를 올려도 매일 `daily_trigger_off`로 끝나고 수집하지 않는다.
  C-1은 운영에 쓰지 않는다(결정 27).
```

### ⓑ 활성화까지의 길 — 사람이 걷는다

```
1 gold 확정        풀링 방식 권고(D-a): 후보·불확실 건 전수 확정 + 나머지 무작위 표본 확인
2 임계값 4개        D-b. 게시일별 채점 기준, 검토량 상한은 하루 기준
3 표본 상한 N·주기   D-c
4 v3 policy·binding 발행 → 컨테이너 마운트 → 적재 CLI로 draft 행 생성 (§1.3, §3.1)
5 전송 승인          D-d. binding 튜플 단위. BIDOPS_C2_EXECUTION_ALLOWED=true, 방화벽/egress
6 후보 지정          draft → activation_candidate (§3.2)
7 게이트 생성        임계값·gold digest·측정 회차(게시일별 파생 회차 4개) 고정 (§4)
8 측정 실행 2회      후보 상태에서 측정 전용 실행. pass 1·2 각각 회차 4개, 회당 ≈ 22분 (§4)
9 채점·기록          사람이 만든 gate artifact를 evaluation으로 기록 → 통과·미달·보류·미측정
10 활성화            활성화 화면에서 digest·게이트 결과·blocker 확인 후 승인 (§3.3, §11)
11 자동 실행 켜기     같은 화면의 스위치. 환경 cap은 운영자가 설치 때 한 번 (§3.4)
12 cron A 설치       운영시작일부터. 앞선 날짜는 --from-date/--to-date로 하루씩
```

### ⓒ 활성화 뒤의 하루

```
매일 D일 — cron 두 줄. 같은 스크립트를 트랙별로 부른다(§8)

  cron A  run-daily-lifecycle.sh --track order-plans              시각은 D-e
    1 preflight
    2 자동 실행 가능 여부 확인  GET …/daily-trigger → effective_enabled·policy_version
         꺼져 있으면 사유 한 줄 출력 후 종료. **수집하지 않는다.**
    3 발주계획 수집  lifecycle-<D−1>-plans    창 [D−1, D)   1일 — 21일 재조회 폐기
         0건이면 empty_population으로 종료
    4 적재: plans --collection → --tracked-backfill
    5 C-2 실행 요청  요청 본문은 v1(full_source_run) 그대로, 헤더 X-BidOps-Trigger: daily_script
         → BM25 → 상위 300 → Qwen 12배치 ≈ 10분 → 결과 행. 실패한 배치의 건은 사람 검토 필요로 남는다
    6 종료 후 감사 표본 자동 draw(§5)

  cron B  run-daily-lifecycle.sh --track notices                  시각은 D-e (ⓐ와 같다)

  분석 워커 한 슬롯이 C-2·개요·회사 핏·심층 검토를 하나씩 처리한다. 쉬지 않고 일한 시간이 N을 넘으면 M 쉰다(§10).
  두 트랙은 서로 기다리지 않는다. 한 트랙의 실패가 다른 트랙을 멈추지 않는다(§8).

사람
  발주계획 화면은 회차를 고르지 않아도 누적으로 열린다. 기본 보기 = 추적을 정하지 않은 관련 건(§7).
  어제 판정한 건이 오늘도 그대로 보이고 행마다 판정한 policy 버전과 첫 관측일이 보인다.
  누적 후보 검토는 월요일·목요일이다(`docs/business-rules.md:55`) — 관련 여부 라벨, 추적 여부, 감사 표본 라벨.
  추적 승인과 최종 Go/No-Go는 사람이 정한다.
```

### ⓓ 예외인 날

```
0건인 날            수집 뒤 empty_population으로 정상 종료. 적재·실행 없음
policy가 비활성인 날  트랙 전체를 건너뛴다(수집도 안 함). 복귀 뒤 날짜 범위로 따라잡는다
policy를 교체한 날   자동 실행 스위치는 옛 버전에 묶여 있다 → 새 버전에서 다시 켤 때까지 cron A는 switch_bound_to_other_version으로 끝난다.
                   화면·스크립트가 그 사실을 안내한다(§3.4, §11). 과거 판정은 누적에 그대로 남는다(§7)
실행이 실패한 날     대기 후 같은 날 1회 재실행. 또 실패하면 멈춘다. 그 회차는 사람이 --extra-attempt로만 재개한다
cron이 빠진 날       --from-date A --to-date B. 트랙마다, 날짜마다 따로. 완전한 회차가 없으면 수집부터,
                   회차는 있고 성공 실행이 없으면 실행부터. 여러 날을 한 파일로 합치지 않는다. 실행은 날짜 순으로 하나씩
수집이 중간에 죽은 날  남은 디렉터리는 지우거나 덮지 않는다. 다음 실행이 -retryN 접미사로 새로 수집한다
```

발주계획 하나 = 회차 하나 = 실행 하나. 재관측이 없으므로 모집단 축소 규칙·부트스트랩 floor·이월 문제가 없다.
겹치지 않는 세 회차 사이에 같은 통합번호가 다시 나온 경우는 0건이었다(2026-09-18 실측).

## 1. 계약 수정

코드보다 먼저 고친다. 모순된 계약 위에 코드를 얹지 않는다.

### 1.1 policy 활성 여부의 정본은 DB 행이다. 파일의 상태성 필드는 게이트에서 뺀다

| | 지금 | 바뀐 뒤 |
|---|---|---|
| policy 파일 `policy_status` | `active`여야 실행 가능 — 서비스 `services/order_plan_screening.py:262`, worker `workers/order_plan.py:265` | enum 유효성(`draft\|activation_candidate\|active\|retired`)만 검사. **실행 게이트에서 값을 뺀다** |
| DB 행 `policy_status` | `active` 요구 (`:256`) | 활성 여부의 **정본**. 그대로 |
| 서비스 검사 | `row.policy_status=='active' and quality_gate_status=='passed'` **and** `payload.policy_status=='active'` | `row.policy_status=='active' and quality_gate_status=='passed'` + digest 일치. payload status 검사 삭제. 측정 전용 실행의 예외는 §4 |
| worker 검사 | 파일 `policy_status != "active"` → `binding_mismatch` (`:265`); binding `policy.policy_status == 파일 값` (`:282`) | `:265` 삭제. `:282`는 "파일과 binding이 **서로 같다**"만 유지 |

**`policy_status`만이 아니다(결정 18).** policy 파일에는 시간이 지나면 바뀌는 상태가 더 들어 있다 —
`activation.status/enabled/approved_by/approved_at/blockers`, `quality_gate.status/targets/human_adjudication_count/
draft_label_count/remaining_confirmation_count/activation_eligible`, `audit_sample.status/pending_decision`. 적재 후에는
payload·digest가 immutable이고 게이트는 그 digest로 측정하므로, 측정이 끝난 뒤 이 값을 고치려면 새 버전이 필요하고
그러면 측정이 무효가 된다. 그래서:

- 이 필드들은 **발행 시점 스냅샷**이다. 어떤 게이트도 읽지 않는다. `docs/contracts.md`와 ADR ①에 그렇게 적는다.
  파일 스키마(`bidops.order-plan-screening-policy.v1`, `c2_contracts.py:492`)는 바꾸지 않는다.
- blocker와 활성화 가능 여부는 **전부 런타임에서 계산**한다(§3.2) — DB 게이트 행·evaluation, binding, 파일 존재, 스위치.
- D-b 임계값의 **정본은 DB 게이트 행**(§2.1)이다. v3 파일의 `quality_gate.targets`는 `null`로 둔다.
- 파일에서 읽는 것은 **설정값뿐**이다 — policy `audit_sample.enabled`·`max_per_execution`·`review_cadence`·`strata`·
  `selection_order`·`replacement`(§5), binding `external_transport.*`(D-d).

효과: 활성화·retire·게이트 통과가 policy 파일 재발행(→ sha256 연쇄 변경)을 요구하지 않는다. D-c(`audit_sample`)·
D-d(`external_transport`) 값을 넣기 위해 v3 policy·binding 파일을 **한 번** 새로 발행하고, 그 뒤로는 DB 행만 바뀐다.
worker의 역할은 실행 디렉터리 artifact의 digest 일치이지 활성 권한이 아니다. 활성 권한은 실행 디렉터리를 만드는 유일한
생산자인 서비스가 DB 행으로 판정한다.

v3 binding의 `external_transport`(결정 20): `execution_allowed`, `approval_scope: "per_binding"`, `approved_by`,
`approved_at`, `approval_required_per_execution: false`. 승인 단위는 immutable (policy, binding, model_digest, allowlist)
튜플이고 튜플이 바뀌면 policy를 retire한다. 승인자·시각·model_digest **값**은 사람 결정(D-d)이며 비어 있으면
`execution_allowed`를 `true`로 발행하지 않는다.

### 1.2 binding status 허용값을 넓힌다

`workers/order_plan.py:274`의 `binding.get("status") != "blocked"`를
`status not in {blocked, activation_candidate, approved}`로 바꾼다.

`status == "blocked"`이면서 `external_transport.execution_allowed is True`인 조합(현재 실행에 필요한 유일한 조합)은
모순이므로 worker와 서비스가 `binding_mismatch`로 거부한다. v3 binding은 `activation_candidate` 또는 `approved`로 발행한다.

### 1.3 바꾸지 않는 것·전제

- `bidops.order-plan-screening-input.v1` 스키마와 `execution-create-request.v1` **본문**. 모집단 범위 필드도 트리거
  필드도 더하지 않는다(§6). 요청 스키마는 추가 필드를 거부하고 `producer`가 `human-review-client`로 고정이다
  (`schemas/order_plans.py:16-22`).
- **트리거 표식은 요청 헤더로 보낸다(결정 19).** `X-BidOps-Trigger: daily_script | manual_resume | gate_measurement`.
  없으면 사람의 수동 운영 실행이다. 그 외 값은 `invalid_request`. 헤더는 `docs/contracts.md`에 추가한다. 헤더는 요청
  hash에 들어가지 않는다 — idempotency는 `request_id`와 본문으로만 판정한다.
- BM25 절단 코드 전부(단 binding `status` 검사 `:330`은 §1.2와 같은 허용값으로 넓힌다 — 2026-09-18 S4b가 발견, 이 검사가 `blocked`만 받아 새 규칙에서는 어떤 binding도 실행되지 않았다): `skills/bidops-screen/scripts/rank_order_plans_bm25.py:45,275-276,336,576`,
  `build_order_plan_screening_results.py:53,290-294`, `workers/order_plan.py:299,415`. 모집단이 300 미만인 날은
  `min(TOP_K, len(ranked))`로 전건이 선택된다(`:576`) — 주말 9~18건도 그대로 돈다.
- `validate_order_plan_phase0.py`. v2 phase-0 증거 전용으로 못박고 v3 binding을 검증 범위에서
  제외한다고 문서에 명시한다.
- **digest는 파일 bytes 기준이다.** policy·binding v2 파일은 canonical JSON이 아니다(파일 digest `fa58501f…` ≠
  canonical digest `9161c120…`, 실측). `_policy_binding`(`services/order_plan_screening.py:264-271`)은 마운트된 파일이
  digest 일치일 때만 파일 bytes를 쓰고 없으면 canonical로 fallback해 항상 `binding_mismatch`가 된다. 따라서 **운영
  컨테이너에 `BIDOPS_C2_POLICY_PATH`·`BIDOPS_C2_BINDING_PATH` 파일이 항상 있어야 한다.** CLI는 canonical 재직렬화를
  하지 않는다.
- **그 파일을 마운트하는 곳은 overlay가 아니라 base compose다.** `docker-compose.yml:177-178`(web)·`:245-246`
  (analysis-worker)이 v2 파일명으로 고정해 마운트하고, 설정 기본 경로도 v2다(`app/core/config.py:298-301`).
  `docker-compose.c2-order-plan.yml`은 회사 역량·프롬프트만 마운트한다. v3를 발행하면 compose 마운트와 기본 경로를 함께
  바꿔야 한다([`plan.md` S3b](plan.md)).

## 2. 데이터 모델 (Alembic `0029`)

현재 head는 `0028_final_decision_basis`(`app/core/db.py:103`)이므로 다음은 `0029`다.

### 2.1 신규 테이블 4개

기존 `quality_gate` 재사용은 버린다. `policy_version`·`pass_a/b_execution_id`·
`company_profile_version`·`baseline_run_id`가 전부 NOT NULL이고(`app/screening/models.py:581-595`)
C-2는 이 중 어느 것도 채울 수 없다. `purpose`에 세 번째 값을 더하면
`PolicyRepository._valid_gate`(`policy.py:532-597`)와 `docs/model-quality-gate.md`가 정한 C-1
활성화 경로를 전부 재검토해야 한다.

**`order_plan_screening_quality_gate`**

| 열 | 비고 |
|---|---|
| `gate_id` PK | `c2gate-` + 32 hex |
| `policy_version`, `policy_sha256`, `binding_sha256` | 활성화 시 policy 행과 정확히 대조 |
| `gold_manifest_sha256`, `gold_artifact_sha256`, `gold_status` | 채점 입력 |
| `scoring_input_sha256` | |
| `evaluation_basis` | `product_rerun` \| `reference_artifact_rescore` (§4 — 활성화를 여는 것은 `product_rerun`뿐) |
| `scoring_unit` | `per_published_day` 고정(결정 23) |
| `measurement_run_ids_json` | 측정 대상 회차 id 목록(gold 회차의 게시일별 파생 회차). 측정 전용 실행은 이 목록의 회차에만 만들 수 있다 |
| `required_pass_count` | `2` 고정(결정 22) |
| `threshold_recall_pct`, `threshold_precision_pct`, `threshold_important_missed_max`, `threshold_review_load_max` | **전부 NULL 허용.** NULL = D-b 미결정. `review_load_max`는 **하루** 기준 |
| `created_by`, `created_at` | |

payload·digest는 immutable이다. 임계값의 정본이 이 행이다(§1.1).

**`order_plan_screening_quality_evaluation`** (append-only)

| 열 | 비고 |
|---|---|
| `evaluation_id` PK, `gate_id` FK | |
| `revision` | `UNIQUE(gate_id, revision)` |
| `result_status` | `통과` \| `미달` \| `미측정` \| `보류` |
| `pass_execution_ids_json` | `{"pass_1":[…], "pass_2":[…]}`. 각 실행은 `purpose='gate_measurement'`, gate와 같은 policy·binding digest, gate의 `measurement_run_ids_json`과 같은 회차 집합이어야 한다(코드가 대조) |
| `measured_recall_pct`, `measured_precision_pct`, `measured_important_missed`, `measured_review_load` | nullable. **두 pass 중 나쁜 쪽**(recall·precision은 작은 값, 누락·검토량은 큰 값). recall·precision·누락은 게시일별 결과를 합산한 값, 검토량은 게시일별 검토 후보 수의 최댓값 |
| `metrics_json`, `reasons_json` | pass별 값, 두 pass의 판정 일치율, 4일치 일괄 채점 참고값(`reference_full_window`) |
| `artifact_sha256` | 활성화 요청의 `quality_gate_artifact_sha256`와 대조되는 값 |
| `evaluated_by`, `evaluated_at` | |

- UPDATE/DELETE 금지 trigger.
- CHECK: **임계값이 하나라도 NULL이면 `result_status`는 `미측정`만 허용.**

**`order_plan_screening_audit_sample`** (append-only)

`id` PK, `execution_id` FK, `order_plan_id` FK, `stratum`(3종 CHECK), `selection_rank`,
`plan_id_sha256`, `filtered_out_count`, `max_per_execution`, `review_cadence`, `policy_version`, `policy_sha256`,
`drawn_by`, `drawn_at`. `UNIQUE(execution_id, order_plan_id)`가 무복원 근거다.

**`order_plan_screening_daily_trigger`** (append-only, 결정 21)

`id` PK, `policy_version` FK, `policy_sha256`, `enabled`(bool), `reason`(nullable, 200자), `set_by`, `set_at`,
`request_id`(UNIQUE). 스위치의 현재 값은 **그 policy_version의 최신 행**이다. policy 버전에 묶여 있으므로 새 버전을
활성화하면 새 버전에는 행이 없고 스위치는 꺼진 것으로 본다.

### 2.2 기존 테이블 컬럼 추가 — 1개

`order_plan_screening_execution.purpose` — `String(24)` NOT NULL, 기본 `'operational'`,
CHECK `purpose IN ('operational','gate_measurement')`(결정 22). 기존 행은 전부 `operational`로 채운다.

첫 초안의 `population_scope_version`·`source_population_count`·`excluded_count`·`excluded_sha256`(실행)과
`input_title_sha256`(결과)은 **삭제**한다. 발주계획 재관측이 없으므로(§0) 모집단 범위도 제목 변경 재판정도 없다.

### 2.3 권한 (`scripts/runtime-privileges.sql`)

- 신규 4테이블: `SELECT` + `INSERT`를 **app 역할에만**. worker 역할은 없다. `UPDATE` 없다.
- `order_plan_screening_policy`의 app UPDATE 목록에 `quality_gate_status` 한 컬럼만 추가한다. 활성화 트랜잭션에서만 쓴다.
- `order_plan_screening_execution.purpose`는 app이 INSERT 때만 쓴다. worker UPDATE 목록에 넣지 않는다.

재사용할 패턴: `models.py:807-867`(CheckConstraint·`dual()`·`DualSQL`),
`models.py:603-626`(revision unique).

## 3. policy 적재와 활성화

### 3.1 적재 CLI

`python -m app.screening.c2_policy load --policy <path> --binding <path> --created-by <name>`

policy 행을 만드는 **명시적 운영 명령**이다. startup·image build·migration은 이 일을 하지 않는다.

- digest는 `sha256(파일 bytes)`다. canonical 재직렬화가 아니다(§1.3).
- 검증: binding의 `policy.sha256 == policy_sha256`, `policy_version` 일치,
  `OrderPlanScreeningPolicyArtifact.model_validate` 통과(`c2_contracts.py:492`),
  `decision_scope == c2_order_plan_first_pass`.
- 파일의 상태성 필드 값은 검사하지 않는다(§1.1). DB 행은 파일 값과 무관하게 항상 `draft`로 만든다.
- idempotency: 같은 `policy_version` + 같은 digest = 기존 행 반환. 다른 digest = `immutable_conflict`.
- 재사용: `app/screening/policy.py:104` `_reject_duplicate_keys`, `:245` `load_policy_file`,
  `:321` `PolicyRepository.create`.

### 3.2 REST

| endpoint | 동작 | 오류 |
|---|---|---|
| `GET /api/order-plan-screening/policies/{policy_version}` | 행 + `activation_allowed` + `blockers[]`. blocker는 **전부 런타임 계산값**이다(결정 18, payload의 `activation.blockers`는 읽지 않는다): `quality_gate_missing`, `quality_gate_not_passed`(최신 evaluation이 `통과`가 아님 — `미측정`·`미달`·`보류`를 `detail`로 구분), `quality_gate_thresholds_undecided`, `audit_sample_policy_unapproved`, `execution_transport_not_allowed`, `binding_digest_mismatch`, `policy_file_missing`(컨테이너 경로에 digest 일치 파일이 없음). prompt·profile 본문 없음 | `not_found(404)` |
| `GET /api/order-plan-screening/policies` | 행 목록(버전·상태·digest·`activated_at`). 활성화 화면용 | |
| `POST /api/order-plan-screening/policies/candidate` | `{request_id, policy_version, base_policy_sha256, candidate_sha256, reason}`. `base_policy_sha256`가 현재 active 행과 일치(없으면 `null` 허용)해야 `draft→activation_candidate` | `invalid_request`, `idempotency_conflict`, `immutable_conflict` |
| `POST /api/order-plan-screening/policies/{policy_version}/activate` | `{request_id, policy_sha256, quality_gate_artifact_sha256, explicit_confirmation}` | `activation_blocked(409)` |

### 3.3 활성화 검증 순서

한 트랜잭션 안에서, 게이트 행을 `with_for_update()`로 잠근 채:

1. 행이 `activation_candidate`
2. 요청 `policy_sha256` == 행 값 (아니면 409)
3. 요청 `quality_gate_artifact_sha256`와 같은 `artifact_sha256`를 가진 evaluation을 찾고, 그것이 **그 gate의 최신 revision**인지
   확인한다(같은 policy_version에 gate가 여러 개여도 artifact digest가 gate를 특정한다. 최신이 아니면 `activation_blocked`)
4. `result_status == '통과'` **and** gate의 `evaluation_basis == 'product_rerun'` **and** gate의
   `policy_sha256`/`binding_sha256`가 행과 일치 **and** policy·binding 파일이 컨테이너 경로에 digest 일치로 존재
5. 임계값 4개 중 하나라도 NULL → `activation_blocked` (**D-b 미결정 fail closed**)
6. policy payload의 `audit_sample.enabled is not True` 또는 `max_per_execution`·`review_cadence` 중 하나라도 없음
   → `activation_blocked` (**D-c**)
7. `binding.external_transport.execution_allowed is not True` 또는 `approval_scope != "per_binding"` 또는
   `approved_by`·`approved_at`이 비어 있음 → `activation_blocked` (**D-d**)
8. `explicit_confirmation is not True` → `invalid_request`
9. 기존 active 행을 `retired`로 내리고 `active_slot` 해제 → flush → 대상 승격, `quality_gate_status='passed'` 기록.
   **unique index가 최종 심판이다.**

payload의 `activation.blockers`·`quality_gate.activation_eligible`은 이 순서 어디에서도 읽지 않는다(§1.1). 조회 API의
blocker와 활성화 검증은 같은 런타임 조건을 쓰므로 둘의 답이 갈리지 않는다.

재사용: `app/screening/policy.py:419-520` `PolicyRepository.activate`의 순서를 그대로 복제.
라우터 형태는 `routers/policies.py:176-241`, actor 오류는 `:60-69`,
idempotency는 `services/order_plan_screening.py:235-249` `_idempotent` + `IdempotencyRecord`
(operation `c2_policy_candidate` / `c2_policy_activate`).

감사: `AuditEvent(actor_kind="human", action="c2.policy_activated",
aggregate_type="order_plan_screening_policy", aggregate_id=policy_version,
safe_metadata={from_status, to_status, policy_sha256, binding_sha256,
quality_gate_artifact_sha256, evaluation_id, previous_active_policy_version})`.
prompt·profile 본문과 경로는 넣지 않는다.

### 3.4 일일 자동 실행 스위치 (결정 21)

| endpoint | 동작 |
|---|---|
| `GET /api/order-plan-screening/daily-trigger` | `{effective_enabled, policy_version, policy_sha256, switch: {enabled, set_by, set_at} \| null, reasons[]}`. `policy_version`은 현재 active 행(없으면 `null`). 일일 스크립트가 **수집 전에** 부른다 |
| `POST /api/order-plan-screening/daily-trigger` | `{request_id, policy_version, enabled, reason, explicit_confirmation}` → append-only 행 + `AuditEvent(action="c2.daily_trigger_set")`. 대상은 **현재 active 버전만**(아니면 `invalid_request`) |

`effective_enabled`는 다음이 전부 참일 때만 참이다 — **4중 기본-닫힘**:

1. 환경 cap `BIDOPS_C2_DAILY_TRIGGER_ENABLED`(기본 false). 운영자가 설치 때 한 번 켠다
2. DB 스위치 — active policy_version의 최신 행이 `enabled=true`
3. `BIDOPS_C2_EXECUTION_ALLOWED` ∧ binding `execution_allowed`
4. policy `active` + `quality_gate_status='passed'` + policy·binding 파일 존재

`reasons[]`: `env_cap_off`, `no_active_policy`, `switch_off`, `switch_bound_to_other_version`(옛 버전에 켜진 행이 있고
현재 버전에는 없음), `execution_transport_not_allowed`, `policy_file_missing`.

서비스는 `X-BidOps-Trigger: daily_script | manual_resume` 요청에 같은 조건을 **다시** 검사한다 — 스크립트가 GET을
건너뛰어도 실행은 생기지 않는다.

**안내문구(사용자 요구).** "policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다."를 다음 네 곳에 둔다:
스위치 옆(§11), 활성화 확인 대화(옛 버전의 스위치가 켜져 있을 때 "현재 버전 X의 자동 실행이 꺼집니다"), 발주계획
화면 배너(active policy가 있는데 `effective_enabled=false`일 때 사유와 활성화 화면 링크), 스크립트의 사유 출력.

## 4. 품질 게이트 — 측정과 기록

**목적.** 활성화 전에 한 번 치르는 인수 시험이다. 사람이 정답을 단 고정 표본에서, 정확히 이 설정 묶음(policy·binding·
프롬프트·model digest·회사 역량)이 누락과 검토량을 사람이 정한 한도 안에 둔다는 것을 증명한다. 묶음이 바뀌면 다시
치른다. 상시 감시는 감사 표본(§5)과 피드백 라벨이 맡는다.

### 4.1 측정 전용 실행 (결정 22)

실행 API가 active policy만 받으면 "게이트를 통과하려면 실행 결과가 필요하고 실행하려면 게이트 통과가 필요한" 순환이
된다(`services/order_plan_screening.py:256`). 지금까지의 참조 실행은 테스트용 SQL로 DB 행을 직접 active로 만든 것이라
활성화 근거가 될 수 없다(CLAUDE.md). batch 구성만 바꿔도 판정이 41/65/194 → 25/77/198로 흔들린 전례가 있어 실험
산출물 재채점도 제품 결과를 대표하지 못한다. 그래서 제품 경로를 그대로 타는 측정 전용 실행을 둔다. **D-f는 제품
재실행으로 닫는다.**

`POST /api/order-plan-screening/executions`에 `X-BidOps-Trigger: gate_measurement`가 붙으면:

| 검사 | 값 |
|---|---|
| policy 행 상태 | `activation_candidate` 또는 `active`. `quality_gate_status`는 요구하지 않는다 |
| 전송 승인·env | 운영 실행과 **같다** — `BIDOPS_C2_EXECUTION_ALLOWED` ∧ binding `execution_allowed`. 아니면 503 |
| digest·파일 존재 | 운영 실행과 같다 |
| `source_run_id` | 그 policy_version의 gate 중 하나의 `measurement_run_ids_json`에 있어야 한다. 없으면 `invalid_request` — 측정 경로로 일일 회차를 돌리는 우회를 막는다 |
| 일일 스위치·환경 cap | 요구하지 않는다. 측정은 사람이 돌린다 |
| 결과 | `purpose='gate_measurement'`, audit `safe_metadata.trigger="gate_measurement"` |
| 한 슬롯 | `active_execution_exists`는 그대로 적용된다 |

측정 실행은 누적 투영(§7)·워크로드·감사 표본 draw(§5)에서 빠진다. 헤더가 없거나 `daily_script`·`manual_resume`인
요청은 지금처럼 active + `passed`만 받는다.

### 4.2 채점 단위와 반복 (결정 22·23)

- **게시일별 채점이 판정이다.** gold 회차(`order-plans-20260827-20260830-retry1`, 625건)를 게시일별 파생 회차
  4개(308·290·9·18건)로 나눠 일일 운영과 같은 조건으로 실행한다. 파생 회차는 원본을 고치지 않고 새 회차로 만들며
  (분할 도구는 [`plan.md` S5b](plan.md)) `--collection`으로 적재한다. 4일치 일괄 채점은 ADR-0037 실험과 비교하는
  **참고값**으로 `metrics_json.reference_full_window`에 함께 남긴다.
- **같은 묶음으로 두 번 돌려 둘 다 통과해야 통과다.** pass 하나는 회차 4개 ≈ 26배치 ≈ 22분이다. 두 pass의 판정
  일치율을 `metrics_json`에 기록한다(임계값은 두지 않는다).
- recall·precision·중요 누락은 게시일별 결과를 합산해 pass마다 계산한다. 검토량은 **하루 기준** — 게시일별 검토
  후보 수의 최댓값이다.

### 4.3 기록

**코드가 채점하지 않는다.** 사람이 만든 gate artifact에서 읽어 기록한다. 코드는 연결과 판정 규칙만 검사한다.
제품 밖 도구 `scripts/score-c2-gate.py`가 gold와 실행 결과를 대조해 그 artifact 초안과 POST body를 만들며,
아무것도 POST하지 않는다 — 사람이 확인하고 제출한다(`docs/operations.md` 활성화 절차 9단계).

| endpoint | 내용 |
|---|---|
| `POST /api/order-plan-screening/quality-gates` | policy/binding/gold digest + 임계값 4개(**요청에서 `null` 허용**) + `evaluation_basis` + `measurement_run_ids` |
| `GET /api/order-plan-screening/quality-gates?policy_version=…` | gate와 최신 evaluation. 활성화 화면용 |
| `POST /api/order-plan-screening/quality-gates/{gate_id}/evaluations` | pass별 측정값 + `pass_execution_ids` + `artifact_sha256`. 코드가 나쁜 쪽 값을 `measured_*`에 넣고 판정한다 |

판정 규칙 (코드가 계산, **하나라도 미달이면 차단** — 결정 24):

| 조건 | `result_status` |
|---|---|
| 임계값 중 하나라도 NULL | `미측정` |
| pass가 2개 미만, 측정값 중 하나라도 NULL, 또는 pass 실행 중 `성공`이 아닌 것이 있음 | `보류` |
| 두 pass 모두 4개 지표 충족 | `통과` |
| 어느 pass든 하나라도 미달 | `미달` |

**계산 불가를 통과로 바꾸지 않는다.**

`evaluation_basis == reference_artifact_rescore`이면 `reasons_json`에 "제품 파이프라인이 낸 결과가 아님"을
**필수로 남기고**, 그 gate의 evaluation은 `통과`여도 활성화를 열지 못한다(§3.3 4번). 비교·탐색용 기록으로만 쓴다.
CLAUDE.md의 "참조 실행 결과를 운영 근거로 적지 않는다"를 데이터로 강제한다.

재사용: `routers/quality_gates.py:95-105` `_latest()`, `policy.py:268-291` `_audit()`.

## 5. 감사 표본

300 절단을 유지하므로 모집단이 300을 넘는 날 `stage1_filtered_out`이 남는다. 실측 기준 평일 하루 **0~79건**이고
평일 6일 중 5일에 절단이 걸렸다([`intent.md` §4](intent.md)). 감사 표본은 평일마다 도는 업무다. 그 층에서 결정적으로 뽑는다.

| endpoint | 동작 |
|---|---|
| `GET /api/order-plan-screening/executions/{id}/audit-sample` | 계산만(미저장 미리보기) |
| `POST` 같은 경로 | append-only 기록 + `AuditEvent(action="c2.audit_sample_drawn")` |

- 입력: `execution_id` 일치 + `stage1_status == 'filtered_out'`인 결과 행.
  `stage1_rank`·`stage1_score`·`nearest_capability`가 이미 보존돼 있다(`models.py:1134-1137`).
- **형태(결정 15): 실행당 상한 N건, 탈락이 N 이하인 날은 전건.** v3 policy `audit_sample.max_per_execution`(정수,
  발행 전까지 `null`). 기존 `sample_size`는 v3에서 쓰지 않는다(`null`로 둔다). `audit_sample`은 자유 형식 dict라
  (`c2_contracts.py:502`) 검증 모델은 바뀌지 않는다.
- strata 3종 (정책 `audit_sample.strata` 그대로) — 상한을 넘는 날에만 의미가 있다:
  - `classification_proximity` — 회사 대상 조달분류와 일치하는 탈락 건
  - `performance_similarity_proximity` — BM25 rank가 컷(300) **직후** 구간
  - `uniform_hash` — `sha256(plan_id)` 오름차순
- 순서: 정책 문자열 `stratum_priority_then_sha256_plan_id` 그대로 — 층 우선순위 → 층 안에서
  `sha256(plan_id)` 오름차순.
- `replacement: none`: 한 draw 안에서 같은 plan이 두 층에 걸치면 먼저 나온 층에만 배정한다.
  `UNIQUE(execution_id, order_plan_id)`가 강제한다.
- **fail closed**: `enabled`·`max_per_execution`·`review_cadence` 중 하나라도 없으면
  `{"status":"pending_human_approval","sample":null,"pending_decision":"max_per_execution_and_review_cadence"}`
  (200, 오류 아님). **값을 추정하지 않는다.**
- **not_applicable**: `population_count <= 300`이면
  `{"status":"not_applicable","reason":"stage1.population.at_or_below_top_k"}`. 측정 전용 실행이면
  `{"status":"not_applicable","reason":"execution.purpose.gate_measurement"}`.
- 표본 건의 사람 라벨은 기존 `order_plan_screening_feedback` 경로를 재사용한다
  (`services/order_plan_screening.py:776`). 새 라벨 축을 만들지 않는다.
- draw는 §8의 일일 스크립트가 실행 종료 후 자동으로 부른다. 사람은 라벨만 단다.

## 6. 모집단 범위 — v1 그대로

요청 계약은 `execution-create-request.v1`(`full_source_run`) 그대로다. **회차 파일 = 모집단**이다. 발주계획 수집이
전일 1일 창이고 재조회가 없으므로 한 발주계획은 한 회차·한 실행에만 속한다(§0). 같은 회차의 재실행은 §8의 재시도
규칙만 따른다. 기존 불변식 "파일 모집단 == 회차 DB 관측"(`services/order_plan_screening.py:377-382`)은 그대로다.

정책의 `stage1.config.scoring.idf_corpus = full_population_titles`는 그날 회차의 전 모집단을 뜻한다. 하루치
290~379건이 코퍼스이므로 점수는 ADR-0037의 4일치 625건 기준과 다르다. ADR에 명시한다. 게이트를 게시일별로 채점하는
이유이기도 하다(§4.2).

gold의 게시일별 파생 회차는 원본과 같은 발주계획을 다시 관측한다. `source_sha256`이 같으므로 관측 snapshot은 no-op이고
"한 발주계획 = 한 운영 실행"은 깨지지 않는다 — 측정 실행은 운영 실행이 아니다(§2.2).

## 7. 판정의 누적 투영

| | 지금 | 바뀐 뒤 |
|---|---|---|
| 실행 선택 | `execution_id = 최신 완료 실행 1개` (`:997`) | 없앤다 |
| 결과 조인 | `result.execution_id == execution_id` (`:1026`) | 사업 단위 최신 1건 — `row_number() over (partition_by order_plan_id, order_by 실행 finished_at desc)` |
| feedback 조인 | `feedback.execution_id == execution_id` (`:1017`) | 사업 단위 최신 1건 — `row_number() over (partition_by order_plan_id, order_by created_at desc, revision desc)`. 실행과 무관 |
| 관측 조인 | 이미 같은 방식 (`:1000-1008`) | 그대로 |
| 누적 범위 | — | **활성화된 적 있는 policy(`activated_at IS NOT NULL`)의 운영 목적(`purpose='operational'`) 완료 실행 전부**(결정 11). 현재 active인지는 묻지 않는다 — policy를 교체해도 과거 판정이 남는다. 참조 실행(policy v2, 한 번도 active가 아님)과 측정 전용 실행은 자연히 제외된다. C-2 실행 행에는 `quality_status` 표식이 없다(deep_review 전용) |
| 행 표시 | — | 행마다 판정한 `policy_version`과 발주계획의 **첫 관측일**을 싣는다(결정 16 — 발주계획은 첫 관측 그대로 고정된다) |
| `source_run_id` | 화면이 항상 보냄 | 주면 그 회차의 실행으로 좁히고(감사용, policy·purpose 무관), 안 주면 누적. **API 계약은 이미 둘 다 지원한다** |
| `scope` 응답 | 단일 실행 서술 | 누적 모드에서는 `{"mode":"cumulative","policy_versions":[…],"activated_policy_versions":[…]}`. `policy_versions`는 **위 누적 범위에 실행이 실제로 있는** 버전만이며 활성화 이력만 있고 범위 실행이 0건이면 빈 목록이다(워크로드 `null`과 함께 간다). `activated_policy_versions`는 **활성화된 적 있는 버전 전부**(완료 여부를 묻지 않는다)이고 `policy_versions ⊆ activated_policy_versions`다 — 화면은 앞쪽으로 판정 유무를, 뒤쪽으로 실행 상태 표시 범위를 정한다. 회차 모드에서는 기존 서술. 화면이 둘을 구분해 표시한다 |
| 워크로드 | `no_completed_execution`이면 건수가 사라짐 (`projection.py:744-747`) | 누적 기준. 실행이 없는 날에도 0으로 죽지 않는다 |
| 화면 | 회차 선택기가 필수 (`OrderPlansPage.tsx:1789`, `:433,437`) | 기본 해제. 기본 보기는 "추적을 정하지 않은 관련 건". 자동 실행이 꺼져 있으면 배너(§3.4) |

사업 추적·최종 Go/No-Go 화면이 이미 누적이다. 대시보드의 `누적` 문구가 그때 사실이 된다.

## 8. 일일 스크립트 — 트랙 분리와 C-2 트리거

**발주계획 트랙과 공고 트랙을 나눈다(결정 9).** 스크립트는 `run-daily-lifecycle.sh` 하나이고 `--track`으로 한
트랙만 돈다. cron에는 두 줄로 올린다. 입찰공고는 사전규격과 같은 공고 트랙이다 — `collect_notices.py` 한 번이 한
회차에 둘을 함께 수집하고, 입찰공고 선별이 SW 사전규격 참조(`bid_sw_prespec_reference`)를 읽는다.

**C-2 위치: 발주계획 트랙에서 REST 호출.** APScheduler에 붙이지 않는다.

이유: `docs/PLAN.md` Phase 6이 scheduler 파일 4개를 "C-2 자동 실행 목적으로 수정 금지"로 못박았고, 스크립트는 이미
회차 id를 소유한다. actor는 어느 경로든 `human`이다 — `core/api_errors.py:103`이 `"system"`을 거부하고, cron을 설치하고
자기 이름을 actor로 넣은 사람의 옵트인이라는 해석을 ADR에 남긴다(결정 19). 앞 판이 scheduler 경로만 "`human` 위조"라고
적은 것은 cron 스크립트에도 똑같이 해당하므로 기각 근거에서 뺀다.

**발주계획 트랙은 한 묶음이다(결정 10).** 수집·적재·C-2·draw를 항상 함께 돌고 `--c2` 플래그는 없다. 자동 실행이
꺼져 있으면 **수집부터 하지 않는다** — 판정 없는 발주계획을 화면에 쌓지 않는다.

| 항목 | 값 |
|---|---|
| 기준일 | 기본 **전일**(KST). `--date`로 지정 가능. `run-daily-lifecycle.sh:54`의 "오늘" 기본값을 바꾼다 |
| 발주계획 창 | `[기준일, 기준일+1)` 1일 (`:68-69`의 `-20 days`를 없앤다). 회차 `lifecycle-<기준일>-plans` |
| 공고 창 | `[기준일−3일, 기준일]` 4일 (`:70`의 `-2 days`를 `-3 days`로. `:71` to는 그대로 — collector의 `--to-date`는 포함구간). 회차 `lifecycle-<기준일>-notices`. 사전규격 공개 지연 때문이다(§9.4, 결정 28) |
| 트랙 | `--track order-plans\|notices` **필수**, 기본값 없음. 한 번 호출에 한 트랙만 돈다. 기준일 계산·preflight·공백일 반복·회차 조회는 두 트랙이 같은 코드를 쓴다 |
| cron | 두 줄. 두 시각은 D-e. C-2·개요·회사 핏·심층 검토는 분석 워커 한 슬롯이 직렬로 처리하므로(`app/workers/analysis.py:60-75`) **시각을 떼는 것은 GPU 충돌 회피가 아니라 처리 순서의 선호일 뿐이다.** scheduler `daily_time`(기본 02:00)과의 관계는 C-1 자동화 때 정한다(§9) |
| 트랙 독립 | 두 트랙은 서로의 성공을 전제하지 않는다. `set -euo pipefail`은 그 트랙 안에서만 멈춘다 |
| 적재 순서 | `docs/operations.md:479-480`의 "발주계획 → 공고 순서 고정"을 푼다. 공고 선별이 읽는 발주계획 상태는 사람이 정한 추적 상태(`계속 추적`·`보류`·`종료`, `bid_tracked_reference`)이고, 1일 창에서 그날 들어온 발주계획에는 추적 상태가 없다. 그러므로 그날 발주계획이 먼저 적재됐는지가 공고 선별 결과를 바꾸지 않는다. 계약(`contracts.md:760`)에서 추론한 것이며 S9 테스트로 확인한다 |
| `--tracked-backfill` | 두 트랙 끝에서 각각 부른다. 다시 불러도 no-op이다 |
| 자동 실행 확인 | 발주계획 트랙은 preflight 뒤, **수집 전에** `GET …/daily-trigger`를 부른다. `effective_enabled=false`면 `daily_trigger_off: <reasons>`와 §3.4 안내문구를 출력하고 exit 0. 실행에 쓸 `policy_version`도 이 응답에서 받는다(스크립트가 버전을 따로 들고 있지 않는다) |
| 완전한 회차 | `collected-*.json`의 `metadata.collection.complete is True` **and** 해당 `Run` 행 존재. 0건 회차는 `counts.total == 0`이고 complete이면 "빈 회차"로 완결이다(적재·실행 없음) |
| 불완전 디렉터리 | 수집이 중간에 죽어 남은 디렉터리는 **지우거나 덮지 않는다**(원본 불변). 그 날짜에 완전한 회차가 없으면 `lifecycle-<기준일>-plans-retry<N>`(가장 작은 빈 N)으로 새로 수집한다. 스킵·attempt 규칙은 그 날짜의 **완전한 회차**를 기준으로 한다 |
| 0건인 날 | 빈 모집단은 서비스가 409 `source_run_incomplete`로 거부한다(`services/order_plan_screening.py:199-200`). 스크립트가 POST 전에 `counts.total == 0`을 보고 `empty_population`으로 exit 0. 수집기가 0건을 완전한 산출물로 쓰는지는 S9에서 확인하고 아니면 수집기를 고친다 |
| 공백일 | `--from-date A --to-date B`면 그 트랙에서 날짜마다 **단계별로 재개**한다 — 완전한 회차가 없으면 수집부터, 회차는 있고 `성공\|부분 성공` 실행이 없으면 실행부터, 실행은 있고 draw가 없으면 draw만. 덮어쓰기 없음. 실행은 날짜 순으로 하나씩이고 스크립트는 날짜 사이에 자체 sleep을 두지 않는다 — 휴지는 워커가 소유한다(§10) |
| 4중 기본-닫힘 | §3.4. 환경 cap ∧ DB 스위치(버전 고정) ∧ `BIDOPS_C2_EXECUTION_ALLOWED` ∧ (policy `active` + gate `통과`) |
| actor | `BIDOPS_C2_DAILY_ACTOR` 필수·기본값 없음. 없으면 시작하지 않는다 |
| 트리거 표식 | 요청 헤더 `X-BidOps-Trigger: daily_script`(§1.3). `create_execution`이 헤더 값을 `trigger` 인자로 받아 `safe_metadata`에 `{"trigger":"daily_script"}`를 남긴다. `actor_kind`는 `human` 유지 |
| idempotency | `request_id = uuidv5(NAMESPACE, f"{source_run_id}\|{policy_version}\|{attempt}")`. `attempt`는 `GET /api/order-plan-screening/executions?source_run_id=…`(`routers/order_plans.py:134`)로 같은 회차·같은 policy의 **운영 목적** 실행을 세어 정한다 |
| 스킵 규칙 | 그 회차에 `성공\|부분 성공\|대기\|실행 중\|중지 요청` 실행이 하나라도 있으면 새 실행을 만들지 않는다(exit 0, `already_executed` 또는 `active_execution_exists`) |
| 재시도 | `실패\|중단됨`만 있으면 `BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS`(기본 600, GPU 휴지와 별개 설정)만큼 기다린 뒤 `attempt = 그 수 + 1`로 새 실행. **`attempt > 2`면 `retry_limit_reached` 스킵**(자동 재시도 상한 1회). 다른 provider나 재호출로 복구하지 않는다 |
| 사람의 추가 시도 | 한도를 넘긴 회차는 `run-daily-c2.sh <run id> --extra-attempt`로만 재개한다(결정 12). 호출 한 번에 실행 하나, 자동 재시도 없음, 헤더 `X-BidOps-Trigger: manual_resume`, actor 필수. `retry_limit_reached`를 출력할 때 이 명령을 함께 안내한다 |
| 진행 | POST 후 terminal까지 폴링. timeout은 `c2_worker_stale_seconds`(900s)와 §10 휴지 시간의 합보다 넉넉히 |
| 감사 표본 draw | 실행이 `성공\|부분 성공`이면 `POST …/executions/{id}/audit-sample`을 부른다. `pending_human_approval`·`not_applicable`은 사유 한 줄 출력 후 exit 0. draw 실패는 실행 실패와 분리한다(exit 비0, 결과 행은 유지). audit `safe_metadata.trigger="daily_script"` |
| 정상 스킵(exit 0) | `daily_trigger_off`, `empty_population`, `active_execution_exists`, `already_executed`, `retry_limit_reached` — 사유 한 줄 출력. GET과 POST 사이에 상태가 바뀌어 서비스가 `policy_not_active`·`503 service_unavailable`을 돌려준 경우도 같다 |
| 그 외 | exit 비0. `set -euo pipefail` 유지. 같은 날 재시도까지 실패하면 exit 비0 |
| `--collect-only` | 측정·점검용. 수집만 하고 적재·실행은 하지 않는다. 자동 실행 확인도 하지 않는다. **`--run-suffix <name>` 필수** — 일일 회차 id(`lifecycle-<기준일>-plans`)를 차지하지 않는다. 늦은 색인 측정(§9.4)이 이 옵션을 쓴다 |

순서:

- 발주계획 트랙: preflight → **자동 실행 확인**(신규) → 발주계획 수집 → (0건이면 종료) → `plans --collection` → `--tracked-backfill` → **C-2 실행**(신규) → **감사 표본 draw**(신규)
- 공고 트랙: preflight → 공고 수집 → `notices --collection` → `--tracked-backfill` → 첨부 자격 갱신

`run-daily-c2.sh <plans run id>`는 발주계획 트랙이 부르고 단독으로도 실행할 수 있다. 스킵·재시도 규칙은 같다.

## 9. 공고 수집 이중 경로 통합

**적용 범위.** adopt(아래 본문)·§9.1 snapshot v2·§9.3은 **C-1 자동화 때 적용한다 — 이 계획 밖**(2026-09-18,
[`plan.md` §7](plan.md)). §9.2의 승계 범위 확인과 §9.4 공고 수집 창(4일)은 이 계획에 적용된다.

- 뺀 이유: scheduler C-1은 C-1 품질 게이트·policy 활성화·always-on 승인·`BIDOPS_SCHEDULER_ENABLED`가 모두
  있어야 켜지는데 이 계획은 그중 어느 것도 다루지 않는다. adopt와 snapshot v2는 이 계획 안에서 운영 효과가 없고,
  snapshot v2는 모든 적재가 지나는 loader 계약을 바꾼다.
- C-1 자동화를 scheduler adopt가 아니라 공고 트랙의 REST 호출로 정하면 §9.1의 충돌이 생기지 않아 snapshot v2가
  필요 없을 수 있다 — 결과가 파생 회차(`--screen-…`, `worker.py:1060`)로 적재된다. 그때도 `active` policy·게이트
  통과 확인이 따로 필요하다. 수동 경로는 `activation_candidate`도 받는다(`orchestrator.py:1622`).
- scheduler를 켜기 전에 adopt가 먼저다. 없이 켜면 scheduler가 따로 수집해 같은 날 공고가 두 회차에 들어간다(scheduler는
  1일 창, 스크립트 공고 트랙은 4일 창이라 겹친 공고가 여러 회차에 들어간다 — 결정 28 뒤로 adopt는 창 차이까지 풀어야 한다).
- **그때까지 C-1은 운영에 쓰지 않는다(결정 27).** 수동 경로(`POST /api/runs/{run_id}/pipeline/judgment`)는 게이트를
  거치지 않은 `activation_candidate` policy도 받고(`orchestrator.py:1623`), 그 결과의 `제외`는 기본 목록에서 공고를
  숨긴다(`screening/projection.py:52,585`). 점검용으로 부를 수는 있지만 그 판정은 **미측정 policy의 판정**이며 운영
  판단의 근거로 쓰지 않는다. 코드는 바꾸지 않는다 — 게이트 재측정과 수동 경로 정리는 C-1 자동화의 선행조건이다
  ([`plan.md` §7](plan.md)).

아래 분석은 그때를 위해 남긴다.

**방향: scheduler `collect`가 스크립트 회차를 채택(adopt).** 역방향은 순환이다 — 스크립트는
host에서 `docker compose exec`로 컨테이너를 몰고 scheduler는 컨테이너 안에서 돈다.

`app/screening/runtime.py:94-105`의 `collect` 분기만 바꾼다.

새 동작: `collect_notices.py`를 부르지 않는다. `run_key`(`YYYYMMDD-YYYYMMDD`, 전일)에서
`lifecycle-<전일>-notices`를 계산하고 다음을 확인한다. 스크립트 기준일도 전일이므로 id가 그대로 맞는다. 단 §8의
`-retryN` 규칙 때문에 그 날짜의 회차 id가 접미사를 가질 수 있으므로, adopt도 "그 날짜의 완전한 회차"를 같은
조회로 찾아야 한다.

- 디렉터리 존재
- `collected-notices.json`의 `metadata.collection.complete is True`
- 해당 `Run` 행 존재
- `IngestWarning` 0건

전부 통과하면 `{"status":"success","run_id":그 회차}`. 하나라도 불충족이면
`{"status":"failed","failure_reason":"collect_source_missing"}` — **수집을 대신 하지 않는다.**

### 9.1 snapshot 충돌 — 확정, 원인과 해법

`merge_load`가 같은 디렉터리를 `selection="validation"`으로 **재적재**한다(`runtime.py:_ingest`가
selection 인자를 주지 않아 기본값). 그때 각 공고의 관측 snapshot이 `--collection` 패스가 쓴 것과
같아야 no-op이고(`loader.py:658-666`), 다르면 `ObservationSnapshotConflictError`다. 이 예외를 잡는 곳이 없어
**`ingest_run` 전체가 실패한다.**

- **원인은 `sw_industry_1468`이 아니다.** null이면 snapshot에서 빠진다(`loader.py:698-700`). 원인은 표본
  선정기가 record에 덧붙이는 `sample_stratum`·`sample_role`(`select_validation_sample.py:105,142-143`)이다.
  `_notice_values`가 둘을 snapshot 값에 넣는다(`loader.py:519-520`). `--collection` 패스는 둘 다 null, 재적재는
  값 있음 → 충돌.
- **`selection="collection"` 재적재는 해법이 아니다.** 그 모드도 `_complete_run_ingest`가 hook을 돌리고
  (`loader.py:4528`), C-1 결과 hook이 `screening-results.json`의 notice(`sample_stratum` 포함)로 같은
  `_upsert_notice`를 부른다(`loader.py:3162`).
- 오늘 안 깨지는 이유: scheduler는 collect 직후 validation 적재 때 validation-set.json이 없어 공고 관측을 만들지
  않고 merge_load에서 처음 만든다. 수동 C-1은 DB에서 입력을 만들어 stratum이 null이다. adopt가 두 세계를 처음
  만나게 한다.
- **해법 (A)**: `sample_role`·`sample_stratum`을 `demand_agency`(`loader.py:1987-1992`)처럼 **snapshot 밖 projection
  컬럼**으로 뺀다. 표본 층은 파생 라벨이지 관측 사실이 아니다.
  - `NOTICE_OBSERVATION_SNAPSHOT_SCHEMA`(`loader.py:125`)를 `bidops.notice-observation-snapshot.v2`로 올린다.
    발주계획 snapshot은 그대로.
  - `_check_existing_observation_snapshot`(`:616-666`): 저장된 관측이 v1이면 pre-0009 관측과 같은 규칙 — 경고
    `observation_snapshot_legacy_schema` + no-op. v1 값을 다시 계산해 비교하지 않는다.
  - `Notice.sample_role`·`sample_stratum`은 artifact가 값을 줄 때만 쓰고 비어 있는 값으로 기존 값을 지우지 않는다.

### 9.2 창 일치와 승계의 범위

scheduler 일일 예약은 `window_from == window_to == 전일`(1일, `scheduler.py:373`)이다. 스크립트 공고 회차는 처음
1일로 정해 예약 창과 같았으나 **결정 28로 기준일 포함 4일이 됐다(§9.4).** 그래서 adopt하면 scheduler C-1
(`scheduled_pipeline.py:407-414`, `scope="full_run"`)이 고르는 대상(`orchestrator.py:1452`)에 앞 회차와 겹치는 공고가
매일 다시 들어간다. 아래 승계 분석대로 이 겹침은 중복 판정이 된다 — C-1 자동화 때 판정 대상을 "그 회차에서 처음
관측된 공고"로 좁히거나 창을 맞추는 방법을 정해야 한다([`plan.md` §7](plan.md)).

회차 사이 겹침이 있으면 중복 판정이 된다. **`승계`(carry_over, ADR-0016)는 회차 사이에서 작동하지 않는다**
(2026-09-18 코드 확인). 3일 겹침을 없앤 근거 중 하나다.

- 이전 판정은 판정 대상 회차 폴더 `data/runs/<run_id>/`의 `screening-input.json`·`screening-decisions.json`에서만
  읽는다(`orchestrator.py:1492-1507`, 호출 `:1614,1778`). worker의 `_carry`도 같다(`worker.py:689-693`). 둘 중
  하나라도 없으면 전부 `신규`다(`orchestrator.py:1512-1513`).
- 실행 artifact는 `data/screening-executions/<execution_id>/`에 쓰이고(`orchestrator.py:1674,1836`,
  `worker.py:399`), 발행은 새 파생 회차 `<원본>--screen-<시각>-<hex>`로 나간다(`worker.py:1060`). 날마다 새로 생기는
  `lifecycle-<기준일>-notices`에는 두 파일이 없다.
- 공고 id로 다른 회차나 DB의 이전 판정을 찾는 경로는 없다. 기존 테스트도 같은 폴더에 이전 파일을 손으로 넣고
  승계를 검증한다(`tests/screening/test_screening_orchestrator.py:847-866`).

따라서 승계는 이미 판정한 파생 회차를 C-1에 다시 넣을 때만 걸린다. 3일 겹침 회차를 adopt했다면 겹친 이틀 치
공고가 매일 `신규`로 다시 판정되어 공고 하나가 최대 3번 판정됐을 것이다.

### 9.3 함께 기록할 것

- `_upsert_run`이 매 적재마다 그 회차의 `IngestWarning`을 전부 지운다(`loader.py:2850`).
  따라서 adopt의 "경고 0건" 검사는 **마지막 적재 기준**이다. C-2는 발주계획 회차
  (`lifecycle-*-plans`)를 보므로 공고 회차의 재적재와 무관하다.
- 스크립트가 `docker compose cp`로 넣은 **컨테이너 사본**에 scheduler가 `validation-set.json`·
  `screening-results.json`을 추가한다. host 사본은 수집 원본 보관본으로 그대로다. 기존에도 같은 패턴
  (sample→merge_load가 같은 디렉터리에 쓴다)이므로 새 위반이 아니다. `collected-*.json`은 절대 덮지 않는다.

### 9.4 공고 수집 창 — 기준일 포함 4일 (D-g, 결정 28)

`collect_notices.py`는 사전규격을 등록일(`rgstDt`), 입찰공고를 게시일(`bidNtceDt`) 기준으로
`from 00:00 ~ to 23:59` **양끝 포함**으로 조회한다(`:921-923`). 스크립트는 from = 기준일−3일, to = 기준일을 준다.

**처음 결정(결정 8)은 1일 창이었다. M0 측정으로 4일로 바꿨다(결정 28,
[`../validation-runs/20260918-late-indexing.md`](../validation-runs/20260918-late-indexing.md)).**

- 발주계획(8일)·입찰공고(3일)는 늦은 색인 0건이다. 입찰공고는 `bidNtceDt ≤ rgstDt`라 등록 즉시 조회된다.
- **사전규격은 조회 기준과 공개 시각이 다르다.** API 날짜 조회(`inqryDiv=1`)는 등록일시 `rgstDt` 기준인데 목록 공개는
  접수일시 `rcptDt`부터다. 708건 중 11건이 다음 날 이후에 접수됐다(1일 7·2일 1·3일 3). 매일 07:00 수집 기준 창별
  누락은 1일 11건(1.55%, SW=Y 2/68)·2일 4·3일 3·**4일 0**이다. 기존 기록이 `inqryDiv=1`을 "접수일시"라 적은 것은 오기다.
- 수집기 창이 원천 공통이라 입찰공고도 4일로 수집된다. 입찰공고는 늦은 색인이 없으므로 재관측만 늘어난다.

겹친 창에서 다시 관측된 공고의 처리(코드 확인):

| 단계 | 재관측 시 |
|---|---|
| 공고 행 | notice_key로 같은 행을 갱신하고 관측 행만 추가한다(`loader.py:1994`). 값이 같으면 `changed_fields`가 빈다 |
| 첨부 | provider key·(이름, URL)로 같은 행을 재사용한다. 이미 취득 행이 있으면 새로 받지 않는다(`prespec_attachments.py:253`) |
| 문서 묶음 | 문서 집합 fingerprint가 같으면 새 묶음을 만들지 않는다(`auto_preparation.py:313`) |
| 심층 검토 | 이미 있으면 새로 시작하지 않는다(`deep_review_exists`) |
| **개요 run** | 지금은 활성 run(대기·실행 중)만 확인해(`overview_runs.py:744`) **완료된 run이 있어도 다시 들어간다.** 결정 28로 같은 공고·같은 문서 버전·같은 policy digest에 `completed`·`needs_human_review` run이 있으면 넣지 않는다([`plan.md` S15](plan.md)). `failed`·`cancelled`는 지금처럼 다음 촉발에서 재시도한다 |

근거로 남는 것(1일 창을 검토할 때 확인한 사실, 입찰공고에는 여전히 참이다):

- **입찰공고의 정정·재공고는 새 공고 id와 그 건의 게시일로 올라온다.** 공고 id는 `bid:{공고번호}:{차수}`
  (`collect_notices.py:559,603`)이고 게시일은 차수별 `bidNtceDt`다(`:610`). 정정(변경·취소공고)은 같은 번호의 새
  차수, 재공고(`reNtceYn=Y`)는 새 번호의 차수 `000`이다. `20260817-20260823` 표본 40건 중 15건이 정정·재공고였고
  모두 그 건의 게시일로 창 안에 있었다.
- **사업 연결은 기존 경로가 한다.** ADR-0059 선별 적재 ①·②, ADR-0058의 새 차수·정정 → 최종 결정 `stale`.

대가·주의:

- **scheduler 예약 창(1일)과 공고 회차 창(4일)이 다르다.** C-1 자동화 때 §9.2의 중복 판정 문제가 다시 생긴다
  (승계는 회차 사이에서 작동하지 않는다). C-1 자동화의 선행조건으로 남긴다([`plan.md` §7](plan.md)).
- 회차별 선별 통계에 재관측분이 섞인다 — "그날 새로 들어온 건수"가 아니다.
- 사전규격의 등록 후 변경은 등록 뒤 3일 안의 것만 다시 관측된다. 그 뒤의 변경(`chgDt`)은 여전히 못 본다
  (수집본 4개에서 회차당 0.7~3.6%). 필요해지면 변경일 기준 조회로 따로 푼다(API 지원 여부는 확인하지 않았다).
- 재공고·정정은 C-1에서 `신규`로 판정된다(기존 동작).
- 4일 창의 누락 0은 한 주 표본이다. 3일 넘게 늦는 건이 드물게 있을 수 있다.

ADR: ADR-0059 결정 1의 "사전규격·입찰공고 3일 창"과 발주계획 21일 재조회를 함께
[ADR-0061](../tracking/decisions/0061-daily-collection-window.md)에서 개정한다.

## 10. 작업 단위 사이 GPU 휴지 — 연속 가동 시간 기준 (결정 13)

C-2는 별도 워커가 아니다. 분석 워커 루프가 한 poll에 C-2·심층 검토·회사 핏·개요 중 **하나만** 잡는다
(`app/workers/analysis.py:60-75`, C-2 claim 우선). 작업 하나 뒤마다 같은 값으로 쉬면 10분짜리 C-2와 1분 남짓한
개요 run이 똑같이 쉬고, 휴지를 길게 잡으면 개요 큐가 하루 안에 빠지지 않는다. GPU 온도가 걱정이라면 재야 할 것은
**쉬지 않고 일한 시간**이다.

| 항목 | 값 |
|---|---|
| 설정 | `gpu_busy_limit_seconds`(`BIDOPS_GPU_BUSY_LIMIT_SECONDS`, N), `gpu_rest_seconds`(`BIDOPS_GPU_REST_SECONDS`, M). `app/core/config.py:221` 옆 |
| 기본값 | **둘 다 0.0 = 현재 동작 무변경.** 둘 다 0보다 커야 켜진다 |

- **규칙**: 워커는 마지막 휴지 이후 작업을 처리한 시간의 합(`busy`)을 든다. 작업을 하나 마친 시점에 `busy ≥ N`이면
  다음 claim 전에 M만큼 쉬고 `busy`를 0으로 돌린다. **작업 중간은 끊지 않는다**(결정 3) — C-2 한 실행이나 심층 검토
  한 건이 N을 넘겨도 끝까지 간 뒤에 쉰다. 잡을 작업이 없는 idle이 M 이상 이어지면 그것이 곧 휴지이므로 `busy`를 0으로
  돌린다.
- **분석 워커** (`app/workers/analysis.py`): 한 poll이 잡을 처리했는지(`did_work`)와 걸린 시간을 집계한다 —
  C-2 `run_once`, 심층 검토 `claimed`, 회사 핏 `run_once`, 개요 `claimed`. 루프 끝(`:113`)의 대기를 위 규칙으로 바꾼다.
  잡을 처리했고 `busy < N`이면 기존처럼 `poll`만 쉰다(짧은 개요 run이 이어질 때 바로 다음 것을 잡는다).
- **SIGTERM**: 10분 `time.sleep`은 `docker stop` 기본 10초 안에 깨어나지 않는다.
  `stop()` 핸들러(`:49-52`)가 `threading.Event`를 set 하게 하고 `event.wait(delay)`로 대기한다.
- **C-1 워커** (`app/screening/worker.py:292-297`): web 프로세스 안의 별도 스레드다(`runtime.py:177,217`). 같은 규칙을
  **따로** 적용한다. **`run_until`(`:299`)에는 넣지 않는다** — 예약 파이프라인이 특정 실행을 끝까지 몰아야 한다.
- **한계**: 분석 워커와 C-1 워커는 서로 조율하지 않는다. 둘이 동시에 일하면 GPU 전체가 쉬는 구간은 보장되지 않는다.
  C-1을 운영에 쓰지 않는 동안(결정 27)에는 분석 워커 하나가 GPU를 독점하므로 문제가 되지 않는다. C-1 자동화 때
  다시 본다([`plan.md` §7](plan.md)).
- **일일 스크립트**: 자체 sleep을 두지 않는다. 공백일 따라잡기에서 날짜별 실행 사이의 휴지는 워커가 건다. 재시도 전
  대기(§8)는 장애 회복을 기다리는 값이지 GPU 휴지가 아니다.
- **건드리지 않는 곳**: `workers/order_plan.py:876-886` C-2 배치 루프. 결정 3대로 모델 호출
  사이 cooldown은 없다.

## 11. C-2 활성화 화면 (결정 25)

`docs/PLAN.md` P5-2 item 5의 화면이다. 후보 policy를 사람이 확인하고 명시적으로 승인하는 동선이며, 일일 자동 실행
스위치도 여기에 둔다. 관리 화면은 데스크톱 전용(1280~1920px)이고 검증 viewport는 1280x800과 1440x900이다.

위치: 기준 화면(`pages/CriteriaPage.tsx`)은 C-1 정책(`PoliciesPage`)과 품질 게이트(`QualityGatesPage`)를 탭으로 싣는다.
그 옆에 **"발주계획 선별 정책" 탭 하나**를 더한다(신규 `pages/OrderPlanPolicyPage.tsx`). 두 화면의 구성·actor 입력·확인
대화 패턴을 재사용한다. 색은 `bidops` 테마 토큰만 읽는다(ADR-0048).

| 구역 | 내용 |
|---|---|
| policy 목록 | 버전, 상태(`draft`·`activation_candidate`·`active`·`retired`), `activated_at`, policy·binding digest(앞 12자 + 복사). 승인 전에는 활성 정책처럼 보이지 않게 한다 |
| 선택한 policy | exact digest 전체, 컨테이너의 파일 존재 여부, 전송 승인(`approval_scope`·`approved_by`·`approved_at`), 감사 표본 설정(`enabled`·`max_per_execution`·`review_cadence`) |
| 게이트 결과 | 최신 evaluation. **`미측정`과 `미달`은 다른 표면이다** — `미측정`은 "임계값 미정"(중립), `보류`는 "측정 미완"(중립 + 빠진 항목), `미달`은 실패 의미색 + 미달 지표, `통과`는 성공 의미색. 임계값 대 측정값 표(pass 1·pass 2·나쁜 쪽), 두 pass 일치율, 4일치 일괄 참고값. `reference_artifact_rescore` gate는 "활성화 근거 아님" 표식 |
| 측정 실행 | 그 policy의 `gate_measurement` 실행 목록과 상태(읽기 전용). 측정 실행을 만드는 것은 측정 스크립트다([`plan.md` S5c](plan.md)) |
| blocker | §3.2의 런타임 blocker를 사람 말로 풀어 보여 준다. 하나라도 있으면 승인 단추는 비활성이고 이유가 옆에 보인다 |
| 동작 | `후보로 지정`(draft일 때), `활성화`(candidate이고 blocker 0건일 때). 확인 대화에서 policy digest 앞자리와 gate artifact digest를 다시 보여 주고 `explicit_confirmation`을 받는다. 담당자 이름은 기존 actor 입력을 쓴다 |
| 일일 자동 실행 | active policy에만 보이는 스위치. `effective_enabled`와 `reasons[]`를 사람 말로 함께 보여 준다(환경 cap이 꺼져 있으면 "운영자가 환경 설정을 켜야 합니다"). 켜고 끌 때 확인 대화 + 사유 입력 |
| 안내문구 | 스위치 옆: "policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다." 활성화 확인 대화(옛 버전의 스위치가 켜져 있을 때): "현재 버전 X의 자동 실행이 꺼집니다. 활성화 뒤 이 화면에서 다시 켜세요." |

발주계획 화면(`OrderPlansPage.tsx`)에는 active policy가 있는데 `effective_enabled=false`일 때만 배너를 둔다 — 사유와
이 화면으로 가는 링크.

화면은 승인과 스위치만 쓴다. gate 생성·evaluation 기록·측정 실행은 REST를 부르는 스크립트가 한다 — 드물고 artifact
digest를 다루는 일이라 화면 입력보다 스크립트가 안전하다.
