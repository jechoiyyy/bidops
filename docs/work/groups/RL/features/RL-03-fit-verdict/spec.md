# 카드 기반 참여 판정(추출→대조→역할→종합)과 판정 화면 — spec

- 기능 ID: `RL-03-fit-verdict`
- 근거: [intent.md](./intent.md). **wire 계약의 원본은 [HP-03 spec](../../../HP/features/HP-03-two-tier-analysis/spec.md) "단계 wire 계약"·"설정·상태·저장"·"승인 wire와 호환 경계" 절과 [HP-04 spec](../../../HP/features/HP-04-practitioner-verdict/spec.md) "API 계약" 절**이며, 이 문서는 그 계약을 그대로 채택하고 아래 "루트랩 재명세 차이"만 바꾼다. 두 HP 문서는 blocked 기능의 기록이지만 계약 본문은 이 spec의 일부로 읽는다.
- 작성일: 2026-10-16 (같은 날 독립 검사 1차 18건 반영; 2026-10-17 배치 B 인터뷰 D1·D2·D5·D9·D13과 v2 fixture 대조 결함 정정 반영 — [batch-b-interview.md](../../batch-b-interview.md))

## 큰 틀 문서와의 관계

- 인용하는 절: HP 계약 §0(모델 identity)·§3(카드)·§6(unit·1층 Extract)·§7(대조·역할·종합·enum·호출 수·시간)·§8(화면 5블록·REST), DEMO 계약 §5(동결 입력·현재성)·§6(회사별 REST)·§9(정확한 실행 계약·오류·gate), RL-00 spec(사실 status·origin·value 확장 표), RL-01 spec(`BriefingItemView.verdict_display`, Slack 전송기), RL-02 spec(활동 확장점·탭 라우트), ui-spec §3(SourcePanel)·§4.4, bid-procedure §3(자격 항목).
- 이 문서에서 새로 확정하는 항목: 정책 단위 사전 승인 테이블·CLI·검사 순서, 자동 트리거와 일일 상한, 루트랩 fact_key 대조 allowlist, `proposed` 취급, 새 정책 파일 identity, 테이블 이름, 사업기회 경로 REST·수동 요청 REST, 화면 상태 매핑, 활동·브리핑·Slack 연결.
- 큰 틀 문서 수정이 필요한 항목(STEP-010): DEMO 계약 §9 "건별 승인" → RL 개정(정책 승인 + 자동 preview/approval), DEMO 계약 §5·§6 "회사 경로 자격·현재성의 개요 completed" → RL `card-v1` 경로 예외(개요 비의존, `overview_*` null — 아래 "개요 의존 제거"), HP 계약 §6~8 머리에 "RL-03이 루트랩 기준으로 구현" 주석, contracts.md(REST 3·테이블 2·정책·오류 code), business-rules.md "RL 자동 분석과 판정 상태" 절, operations.md "정책 승인·cap·시운전", ADR.md 한 줄(ADR-0050·0069 완화 실행), ui-spec §4.4(`proposed` 표시).

## 범위 결정: 1차는 사전규격만

현재 코드는 입찰공고(`source_type='bid_notice'`)에 첨부 취득·문서 준비·개요·SW 게이트가 없다(`maybe_auto_prepare`·`effective_grade`·`company_notices`·`prepare_company_deep_review`가 모두 `pre_spec` 전제). RL-03 1차 분석 대상은 **사전규격**이며(2026-10-17 인터뷰 D9 "spec대로" 확인), 같은 사업기회에 입찰공고가 뒤에 연결되면 사전규격 판정을 레코드·브리핑에 "사전규격 기준 판정"으로 표시한다(재분석 없음). 입찰공고 문서 취득·판정은 후속 기능이다(브리핑의 입찰공고 항목은 연결된 사전규격 판정을 "사전규격 판정 참조"로, 없으면 "판정 대상 아님"으로 표시 — RL-01 `verdict_display` v2 값 추가).

RL 자동 경로도 기존 서비스 gate를 그대로 지난다: `BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED`는 **계속 요구**한다(결과는 `unmeasured_reference`). 단, **개요 run은 전제가 아니다**(2026-10-17 사용자 인터뷰 D1): 개요는 LiteLLM/vLLM 경로라 RL 모델 제약(codex-exec Luna 하나)을 어기므로, RL 경로는 개요 run을 기다리거나 부르지 않고 자격을 공고 메타 `qualification_flags_json.sw_business_status='Y'`(기존 `effective_grade.sw_business_notice_ids`) ∧ 문서 묶음 `ready`로 본다. Luna는 판정 단계(`card-extract-v1`·`card-role-v1`·`card-synthesis-v1`)에만 호출한다.

### 개요 의존 제거 (D1)의 정확한 변경

새 테이블·열·REST·설정 키는 없다. 바뀌는 것은 아래뿐이다.

1. gate: `prepare_company_deep_review`의 순서(binding → policy → model → 개요 → SW → bundle)에서 선택된 정책 행의 `pipeline_version == "card-v1"`이면 **개요 단계를 건너뛴다**(`current_company_overviews`를 읽지 않음). SW≠Y는 기존 403 `effective_grade_ineligible`, ready 묶음 없음은 기존 409 `bundle_not_ready`. `narrative-v2`(기존 회사 심층 경로)는 지금처럼 개요 completed를 요구하며 바뀌지 않는다.
2. 입력: HP-03 v2 최상위 키 집합은 그대로다(`overview_run_id`·`overview_sha256` 키 유지). `card-v1` 경로는 두 값을 모두 `null`로 동결한다. v2 입력 모델과 `FrozenProvenance`(`schemas/company_analysis.py`)의 두 필드를 `UUID | None`·`Sha256 | None`으로 완화하고 "둘 다 null이거나 둘 다 값" validator를 둔다(`FrozenProvenance` 키 집합 불변). v1 입력(`bidops.company-analysis-input.v1`, `narrative-v2`)에 null이 들어오면 지금처럼 `company_input_invalid`.
3. 현재성: `_review_current`는 `card-v1` review에서 개요 비교 대신 "동결값 `overview_run_id`·`overview_sha256`이 둘 다 null"을 확인한다. SW=Y·bundle `ready`·문서 current·binding·정책/model/generation 비교는 그대로. HP-04 `stale_reasons` 집합은 바뀌지 않는다.
4. DB: `deep_review_preview`·`deep_review`에는 개요 열·trigger가 없어 migration이 필요 없다(`prespec_company_fit`의 개요 trigger는 회사 핏 전용이라 무관).
5. 오류 code: RL 경로(자동·수동)는 `overview_not_completed`를 내지 않는다.
6. 기존 개요 자동 enqueue(`maybe_auto_prepare`의 `_enqueue_overview`, `BIDOPS_PRESPEC_OVERVIEW_ENABLED`)는 범위 밖이라 코드를 바꾸지 않는다. RL 격리 스택의 실제 호출(T12)에서는 이 기존 플래그를 false로 둬 개요 모델 호출이 생기지 않게 한다(새 키 아님).

## 루트랩 재명세 차이 (HP-03·04 대비)

| 항목 | HP-03·04 | RL-03 |
|---|---|---|
| 회사 | `hp-onweb` 가상, `company_sha256`(basis 파일) | RL-00 실회사 활성 binding. `hp_analysis`의 `company_basis`·`scenario_sha256`·`registration_sha256`·`company_sha256`은 **제거**. `card_analysis` **정확 키 집합** = `{schema_version:"bidops.card-analysis-input.v1", company_binding:{graph_version_id, graph_sha256, profile_version_id, profile_sha256, ontology_version, ontology_sha256}, units, batches, missing_sections, selector}`(`ontology_sha256`은 최상위 v2 키에도 그대로 남고 둘이 같아야 함; `selector.version="card-sections-v1"`, 규칙은 HP-03 표 그대로) |
| 정책 파일 | `analysis-policy-hp-v1` | `analysis-policy-luna-rl-v1.json`: `policy_identity="analysis-policy-luna-rl-v1"`, `pipeline_version="card-v1"`, 나머지 키·값은 HP-03 "승인 wire" 절 그대로. `prompt_output_contract.company_input_rule`을 실회사 문구로 교체: "회사 입력은 실회사 ㈜루트랩의 등록 사실이며 origin은 company_brochure·homepage·user_interview·agent_proposal 중 하나다. status가 confirmed인 사실만 보유·수행·자격의 근거다. proposed(에이전트 제안값)와 unknown은 확인되지 않은 값이며 보유·미보유 어느 쪽 근거도 아니다." |
| 대조 fact_key allowlist | HP02 retained_facts 10개(scalar) | 루트랩 노드 id와 **읽는 value 경로**(RL-00 구성 규칙·value 확장 표): 상주 인원·지역→`staff:onsite` `value.available`·`value.region`; 총 인력→`staff:total.value.total`(회사소개서 confirmed 58명; 이 노드가 confirmed가 아니면 unknown, 분야 합산으로 대신하지 않음 — 2026-10-17 배치 B 인터뷰 추가 결정); 디자인→`staff:design_publishing.value.available`(v2 fixture에서 `total`은 null, `available`=5); 직접생산 품명→`qual:direct_production` `value.held`·`value.detail`(`detail` null이면 품명 비교 불가→`unknown`); 업종 1468→`qual:procurement_1468.value.held`; 중소기업 확인서→`qual:sme_certificate.value.held`(`valid_until` null이면 유효기간 요구는 unknown); SW사업자→`qual:sw_business.value.held`; 신용등급→`qual:credit_rating`(`proposed`→unknown); 정보보호 인증→`qual:infosec_cert.value.detail`(null이면 ISMS/ISMS-P 구분 불가→unknown); 부정당 제재→`qual:sanction_free.value.held`(true=요구 충족); 지역제한→`qual:branch.value.detail`(v2 fixture에서 value는 문자열이 아니라 qualification 객체이고 지점 문자열 "대구(본점), 세종"은 `detail`; `held`만으로는 지역 판정 불가, `detail` null이면 unknown)+`staff:onsite.value.region`; 금액 상한→`pref:solo_cap.value.params.krw`; 공동수급·하도급→`pref:consortium.value.params`·`pref:subcontract.value.params.allowed`. `qual:social_enterprise`·`qual:staff_certifications`는 가점·정보 항목이라 대조 밖(비교 대상 아님). 목록 밖 요구는 연결 거부·unknown. 비교기는 scalar가 아니라 위 경로의 값을 읽는다. (2026-10-17 `rootlab.source.v2.json` 대조: `qual:branch`·`staff:design_publishing` 두 경로를 정정했고 나머지 경로는 fixture 모양과 일치한다) |
| `proposed` | 없음 | compare에서 `unknown_fact`와 같은 reason_code `proposed_fact`(**추가 enum**)로 unknown(compare는 동결 입력을 로컬에서 읽으므로 모델에 값이 필요 없다). 역할·종합 전송 payload의 `profile_facts`에는 `proposed`·`unknown`을 `{fact_key, status}` 두 키만 넣고(값 없음, 아래 "전송 payload 규칙"), evidence는 `confirmed`만 `profile_evidence`에 넣는다 |
| 전송 승인 | 건별 preview→사람 approval | `transfer_policy_approval` 활성 행이 있으면 service가 preview·approval 행을 **자동 생성**: `preview_company_deep_review`·`create_company_review`·`create_company_attempt`·`luna_inputs.approve`에 `actor_kind`(`system`)와 `commit=False`(호출자가 transaction 소유) 인자를 추가하고, `claimed_name="system:transfer-policy"`, `request_id = uuid5(transfer_policy_approval.id, input_sha256)`. 사람 클릭 경로는 그대로 두되 RL 자동 경로는 쓰지 않는다 |
| 트리거 | 없음(수동) | 아래 "자동 트리거" |
| 저장 테이블 | `hp_analysis_stage` | `card_analysis_stage`(열·제약 동일) |
| 정책 행·선택 | demo env `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`, `pipeline_version=="narrative-v2"` 강제 | RL 정책 = `import-profile-policy`로 import한 `AnalysisPolicyVersion` 행. 선택 env **`BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`**(새 키, demo env와 분리). `transfer_policy_approval.policy_sha256` = 그 행의 canonical sha(`input_versions` 규칙, 파일 raw sha 아님). `resolve_company_deep_policy`·worker claim의 pipeline 검사를 `narrative-v2 \| card-v1` 허용으로 넓히고 `_LUNA_POLICY_FILES_BY_IDENTITY`·`COMPANY_POLICY_IDENTITIES`에 `analysis-policy-luna-rl-v1` 추가 |
| 재판정 경로 | — | 같은 계보(회사·공고·bundle·profile·정책 partial UNIQUE)면 `target_review_id` 고정 preview → `create_company_attempt`(기존 code `active_attempt_exists`·`bundle_not_ready` 재사용; failed는 superseded); 계보가 다르면 새 review. 새 code `analysis_in_progress`·`documents_not_ready`는 두지 않는다 |
| 시각 | attempt `created_at` 없음 | cap 집계·"최신 attempt" 정렬은 `DeepReviewApproval.approved_at`(자동 생성 시각) 기준 |
| 오류 code 접두 | `hp_*` | `card_*`(`card_source_selection_incomplete`·`card_extract_invalid`·`card_compare_invalid`·`card_role_invalid`·`card_synthesis_invalid`·`card_review_timeout`), `input_budget_exceeded` 유지, 추가 `policy_not_approved`·`daily_cap_reached`·`verdict_source_missing` |
| runner contract | `hp-extract-v1|hp-role-v1|hp-synthesis-v1` | `card-extract-v1|card-role-v1|card-synthesis-v1` |
| 체크리스트 매핑 | HP-04 | 동일 5 key. `qualification_track_record`에 bid-procedure §3 항목 중 allowlist의 자격 8개(1468·직접생산·중소기업·SW사업자·신용등급·정보보호·지역·제재)가 들어가고 실적은 `project:*`·`project:certified_list`(unknown) |
| view `source_binding` | `company_version_id`·`company_sha256`(basis) | `company_version_id`=graph_version_id, **`company_sha256`=graph_sha256**(basis 파일 없음) — view schema_version은 HP-04 값 유지(의미만 재정의, 키 동일) |
| 회사 선택 UI | hp-onweb만 | 회사 선택 없음(실회사 1곳) |

## 전송 payload 규칙 (2026-10-17 사용자 인터뷰 D2)

동결 입력(`deep_review_preview.input_snapshot`, `input_sha256` 대상)과 Luna로 실제 나가는 단계 payload(`card-extract-v1`·`card-role-v1`·`card-synthesis-v1` prompt 입력)를 구분한다. 동결 입력은 위 v2 키 집합 그대로 보존하고, 단계 payload는 동결 입력에서 결정적으로 만든 projection이며 다음만 담는다.

- 공고: 원문 unit(카드 unit + 여섯 영역 segment unit; HP-03 unit·batch 규칙)과 단계 입력(이전 단계 검증 결과).
- 회사 `confirmed` 사실 **전부**(자격·인증·실적·인력·선호/제외, `pref:*` 금액·컨소시엄·하도급 조건 포함): `fact_key`·type·label·status·origin·value와 `confirmed` evidence.
- 회사 `proposed`·`unknown` 사실: `{fact_key, status}` 두 키만. value·label·quote·source_refs·evidence는 넣지 않는다. graph 노드·경로가 payload에 들어가면 같은 규칙(노드는 `{id, status}`만)을 따른다.
- 넣지 않는 것: RL-02 노트 본문, 운영 정보(승인 id·cap·`today_used`·브리핑/Slack 식별자·attempt/review id), 모델/정책 identity(`policy_version_id`·`policy_sha256`·`model_name`·`model_revision`·`generation_config_sha256`)와 회사 binding version id·sha.

payload 검사(T9)는 이 규칙을 단계별로 strict하게 단언하고, 어기면 호출 전에 기존 code `company_input_invalid`로 fail closed한다(기존 `company_part_is_prompt_safe` 검사와 같은 자리).

## 자동 트리거와 일일 상한

- 조건(모두 참일 때 attempt 생성): (1) 브리핑 `kind=recommendation`·stage `pre_spec` 항목이 생성됨(lifecycle `extensions.py`에 hook `on_briefing_recommendation(session, notice_id, briefing_item_id)`를 **선언**하고 deep_review가 제공; RL-01 생성 service가 호출), (2) 그 공고의 최신 문서 묶음이 `ready`(없으면 `maybe_auto_prepare`를 reason `briefing_recommendation`으로 호출해 준비를 시작하고, ready 전환 hook에서 다시 (3)~(7)을 평가), (3) 공고 메타 `qualification_flags_json.sw_business_status='Y'`(기존 `sw_business_notice_ids`; 개요 run은 보지 않는다 — 2026-10-17 인터뷰 D1), (4) `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=true`, (5) 활성 `transfer_policy_approval`이 있고 그 `policy_sha256`이 선택된 정책 행의 canonical sha와 같음, (6) 오늘(KST, `approved_at` 기준) 생성된 RL attempt 수 < `daily_cap`, (7) 그 공고에 `verdict_request(status=rejected, reason=gold_holdout)` 행이 없음(RL-05 홀드아웃; 수동 요청은 이 행을 `started`로 바꿔 해제한다).
- 실행 역할: ready 전환은 첨부/문서 worker(`worker` 역할)에서 일어나므로 자동 preview·review·attempt·approval 생성도 worker 역할이 한다. `scripts/runtime-privileges.sql`에 worker INSERT를 `deep_review`·`deep_review_attempt`·`deep_review_stage`·`deep_review_preview`·`deep_review_approval` 5개 테이블에 추가하고 `test_runtime_database_privileges.py`의 app 전용 단언을 갱신한다(대안 "하루 1회 drain만"은 같은 날 자동화를 잃는다).
- (6) 실패 시 WorkJob을 만들지 않고 `verdict_request` 행을 `queued`·`daily_cap_reached`로 남긴다. 다음 날 브리핑 생성 직후 `drain-verdict-queue`(같은 CLI, `build-briefing`가 호출)가 cap 안에서 오래된 순으로 attempt를 만든다.
- 수동 "다시 판정"은 cap을 소비하되 cap 초과면 409 `daily_cap_reached`(큐에 넣지 않음).
- 같은 (notice, 문서 fingerprint, 회사 graph version, 정책 sha) 조합의 completed attempt가 있으면 자동 트리거는 새로 만들지 않는다(현재성 규칙 DEMO §5). 수동은 항상 새 attempt.

## 정책 단위 사전 승인

- `transfer_policy_approval` {id UUID PK, policy_identity TEXT, policy_version_id UUID FK analysis_policy_version, policy_sha256 CHAR(64)(행 canonical sha), model_name TEXT, reasoning_effort TEXT, cli_version TEXT, scope JSONB(`{stages:["pre_spec"], purposes:["deep_review"]}`), daily_cap INT, approved_by TEXT, approved_at TS, revoked_by TEXT NULL, revoked_at TS NULL, revoke_reason TEXT NULL, request_id UUID UNIQUE(CLI가 `uuid4()`로 만들고 출력에 적는다; `--request-id`로 재생 가능)}. 활성 = `revoked_at IS NULL`; UNIQUE(policy_sha256) WHERE revoked_at IS NULL. append-only: 기존 선례대로 trigger가 `revoked_*` 세 열 외 UPDATE와 DELETE를 거부한다.
- CLI `python -m app.deep_review.cli approve-transfer-policy --policy <identity> --actor <name> --daily-cap N [--dry-run]` → `{approval_id, policy_identity, policy_sha256, model_name, reasoning_effort, cli_version, daily_cap, created:bool, errors:[]}`; identity·sha·모델 identity가 HP-00 상수·정책 파일과 다르면 `policy_identity_mismatch` exit 2. `revoke-transfer-policy --approval-id --actor --reason`.
- `GET /api/analysis/transfer-policy` → `{schema_version:"bidops.transfer-policy.v1", active: {approval_id, policy_identity, policy_sha256, daily_cap, approved_at, approved_by, today_used:int} | null}`(설정 화면용·운영 정보이므로 실무 화면에는 안 보임).
- 실행 직전 검사 순서(기존 §9 gate 앞에 추가): 승인 활성 → sha 일치 → scope 포함 → cap → 기존 identity/binding/소유권 gate. 어긋나면 호출 전에 fail closed.
- 건별 감사 이벤트 `analysis.transfer.sent`(actor_kind=`system`, worker가 attempt claim 직후·첫 호출 **전** 1회; safe_metadata: approval_id, policy_sha256, input_sha256, unit_count, planned_call_count, notice_id, attempt_id). 기존 `deep_review.external_transfer_approved`는 자동 approval 생성 시 그대로 남는다(둘은 다른 시점). 토큰·원문·회사 값은 넣지 않는다.

## REST

| 호출 | 입력 | 성공 | 실패 |
|---|---|---|---|
| `GET /api/companies/{company_id}/pre-specs/{notice_id}/verdict?attempt_id=` | HP-04 그대로 | HP-04 `bidops.practitioner-verdict-view.v1` + 추가 키 `briefing_item_id: UUID\|null`, `opportunity_id: int\|null` | HP-04 |
| `GET /api/opportunities/{opportunity_id}/verdict?attempt_id=` | 사업기회 id | 같은 view(**deep_review 소유 라우터** `routers/verdicts.py`, ADR-0045). 대상 공고 = 권위 연결 **사전규격**(같은 단계가 여럿이면 `created_at` 최신·id 내림); 사전규격이 없으면 200 `availability=none` | 404 `opportunity_not_found` |
| `POST /api/opportunities/{opportunity_id}/verdict-requests` | actor 헤더; body `{request_id}` | 202 `{request_id, attempt_id, status:"queued"}` | 400 actor; 403 `effective_grade_ineligible`(SW≠Y, 기존 code); 404; 409 `policy_not_approved\|daily_cap_reached\|active_attempt_exists\|bundle_not_ready`(기존 code 재사용; `overview_not_completed`는 내지 않음 — D1); 422 |
| `POST /api/companies/{company_id}/pre-specs/{notice_id}/verdict-feedback` | body `{attempt_id, kind: wrong_verdict\|wrong_unit\|not_requirement\|source_mismatch, unit_id?: string, note?: ≤500자, request_id}` | 201 `{feedback_id}` | 404·422 |

- 가드 두 겹: (a) `main.py` 미들웨어 `_is_demo_only_path`는 `BIDOPS_RL_ANALYSIS_ENABLED=true`일 때 `GET /api/companies/{id}/pre-specs/{nid}/verdict`·`POST …/verdict-feedback`·`GET /api/analysis/transfer-policy`·`/api/opportunities/{id}/verdict*`를 통과시킨다(그 외 회사별 경로는 RL-00 규칙 그대로); (b) 서비스 `_gate_company`·`company_projection._company`는 "실회사 ∧ RL enabled" 분기를 추가하되 `reference_workflow_mode`·`luna_deep_review_enabled` 검사는 유지한다. 가상회사는 기존 demo 규칙.
- 응답에 identity(정책·모델·시각)는 HP-04대로 포함하되 **화면은 ⋯ "실행 정보"에서만 보여 준다**(ui-spec §4.4 규칙).

## 화면 `/opportunities/:id/verdict` (ui-spec §4.4)

- 좌측(280px): 판정 이름 20px/700(색: 진행 가능 success·조건부 warning·진행 어려움 error·판단 불가 secondary) + 사유 2문장(종합 `reason`을 두 문장으로 자르지 않고 그대로; 길면 "더 보기") / 체크리스트 5행(key→라벨: 자격·실적, 상주·인력, 금액·기간, 기술, 운영·SLA; pill `met`→충족, `gap`→부족, `unknown`→확인 필요) / 다음 행동(`next_actions`, owner 머리글자; owner null은 "미지정") / 고지 1줄 "판정은 참고 의견입니다. 추적 여부와 참여 결정은 담당자가 정합니다."
- 헤더 액션: 제안서 초안(RL-04 전 비활성) · 다시 판정(POST) · ⋯(판정 오류 제보 → feedback POST, 실행 정보).
- 중앙: "요구사항 n" + 보조 "부족 a · 확인 필요 b · 충족 c"(`matrix` 집계; 분모 n은 unit 수 — 이 셋은 ui-spec이 허용한 집계) + 도구(상태 select 기본 "부족·확인 필요만", 필수만 토글). 표 4열: 요구사항(`normalized_requirement` 600 + 보조 "<type> · 필수/조건부/미표기"), 대조(pill), 회사 근거(첫 `role_findings.reason` 한 줄 + 보조 fact label), 원문(`page_range` 있으면 "n쪽" 링크, `mapping_status=inherited`면 뒤에 "(추정)", `unavailable`이면 글자 "쪽 미확인"). 정렬 gap→unknown→met. 50행 페이지 "n건 더 보기".
- 우측(300~380px, 행 선택): SourcePanel — 제목 "원문 · n쪽", `evidence_refs` quote ≤2개 `<mark>`, "쪽 전체 보기"(기존 `GET /api/document-structures/{id}/pages/{page}`), 행동 2개(요구사항 아님 → feedback `not_requirement`, 원문과 다름 → `source_mismatch`).
- 상태: `none` → "아직 판정이 없습니다" + 다시 판정(승인·준비 조건 안내는 오류 code 문구로), `pending|running` → "분석 중" + 검증된 부분표, `failed|needs_human_review` → "사람 검토가 필요합니다" + 부분표 + 다시 판정, `legacy` → 기존 보고서 링크, `is_current=false` → "과거 기준" pill + stale 사유 한글.
- 금지 문자열: 정책 id·모델명·sha·`unmeasured_reference`는 ⋯ 실행 정보 다이얼로그 밖 DOM에 없어야 한다.

## 연결

- 활동 피드(RL-02 hook `opportunity_activity_items`, deep_review 제공): attempt `completed`→`verdict_completed`("판정 완료 · <verdict>"), `failed`→없음(시스템 사건 아님, 화면 상태로만).
- 브리핑 `verdict_display`: lifecycle `extensions.py`에 projection 확장점 `briefing_verdict_display(session, notice_ids) -> {notice_id: str}`를 선언하고 deep_review가 제공(최신 completed attempt의 verdict; running "분석 중"; 없음 "분석 대기"; 입찰공고는 연결 사전규격 판정 "사전규격 판정 참조"/"판정 대상 아님"). RL-01 `bidops.briefing.v1`→**v2**: `verdict_display` 값 집합에 판정 enum 4값과 위 2값을 더한다.
- Slack 스레드: `core/slack.py`에 `post_thread_reply(channel, thread_ts, text)`를 추가(RL-01 전송기와 같은 allowlist·토큰 검사). completed 시 그 공고 항목이 들어 있던 브리핑 메시지(`briefing_item`에 `slack_message_ts` 열 추가 — RL-01 스키마 추가형, 어느 메시지에 들어갔는지 기록)의 `thread_ts`에 "판정 완료 · <verdict> · 확인할 것 n" 1줄. 실패는 스레드에 쓰지 않는다. `slack_message_ts`가 null이면(토큰 없음·미게시) 답글을 건너뛰며 오류가 아니다. Slack 토큰이 없는 동안 이 연결의 증명은 가짜 서버 검사(T8)까지이고 실제 Slack 게시 증명으로 적지 않는다(2026-10-17 인터뷰 D5).

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| `BIDOPS_RL_ANALYSIS_ENABLED` | bool | false | | 실회사 분석 REST·게이트 개방 |
| `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED` | bool | false | | 자동 트리거 |
| `BIDOPS_RL_ANALYSIS_POLICY_PATH` | path | `policies/analysis-policy-luna-rl-v1.json` | | immutable 파일(import 원본) |
| `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID` | UUID | 없음 | | import된 정책 행 선택(비면 RL 경로 fail closed) |
| `BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED` | bool | 기존 | | RL 경로도 요구(변경 없음) |
| 승인 행 `daily_cap` | int | 10 | 1..50 | `tunable`, 승인 CLI 인자 |
| 정책 `card`(HP-03) `batch_size`/`batch_max_chars`/`repair_attempts`/`target_seconds` | | 8/12000/1/2400 | HP-03 범위 | `tunable`(HP-03 위임값) |
| `review_timeout_seconds` | int | 3600 | 고정 | 사용자 확정(HP §7) |

## 상태 값과 실패 처리

- attempt·review status, availability, stale_reasons, Fit, Type, role, verdict enum: HP-03·04 그대로. compare reason_code에 `proposed_fact` 추가. 오류 code: 위 표(`analysis_in_progress`·`documents_not_ready`·`verdict_source_missing`은 **쓰지 않는다**; 기존 `active_attempt_exists`·`bundle_not_ready`·`effective_grade_ineligible` 재사용, `overview_not_completed`는 RL 경로에서 쓰지 않는다 — D1).
- `company_knowledge_retrieval.py`: `FACT_STATUSES`에 `proposed` 추가, `COMPANY_ORIGIN` 단일 값 대신 RL-00 origin 7값 허용, origin 덮어쓰기를 **보존**으로 바꾼다. DEMO §5 `ProfileFactInput`·`ProfileEvidenceInput`의 `origin: Literal["fictional_scenario"]`를 7값으로 개정(STEP-004·STEP-010 문서).
- `verdict_request` {id, opportunity_id, notice_id, actor, request_id UNIQUE, status `queued|started|rejected`, reason(`daily_cap_reached|gold_holdout|manual|null`), created_at, started_attempt_id} — 수동·cap 큐·홀드아웃 기록. `rejected·gold_holdout`은 자동 트리거 차단 표식이며 수동 요청이 `started`로 바꾼다. CLI `drain-verdict-queue --hold <notice_id,…> --reason gold_holdout`가 만든다(RL-05).

## 저장

- `transfer_policy_approval`, `card_analysis_stage`(HP-03 정의: attempt FK, stage, stage_key, input/result sha, payload JSONB, UNIQUE(attempt_id,stage,stage_key), INSERT만), `verdict_request`, `verdict_feedback` {id, attempt_id, kind, unit_id, note, actor, request_id UNIQUE, created_at}, RL-01 `briefing_item.slack_message_ts TEXT NULL`(추가형). migration(단일 head 다음). 권한 runtime-privileges.sql: worker INSERT/SELECT `card_analysis_stage`, worker INSERT 추가 5개(`deep_review`·`deep_review_attempt`·`deep_review_stage`·`deep_review_preview`·`deep_review_approval`), worker INSERT/UPDATE(status) `verdict_request`; web SELECT stage·INSERT request/feedback·INSERT approval·`UPDATE (revoked_by, revoked_at, revoke_reason)` approval; ro_backup SELECT. append-only trigger: approval(위 세 열 외 거부)·stage·feedback. 새 테이블은 `boundary_map.TABLE_OWNER`(deep_review)·`test_db_migrations.NEW_TABLES`·권한 테스트에 등록.

## 인터페이스(CLI·UI·API)

- CLI: `approve-transfer-policy`, `revoke-transfer-policy`, `drain-verdict-queue [--date]`(RL-01 `build-briefing`가 뒤에 호출).
- 외부 호출 보호 장치: `luna_client`(runner 고정 endpoint·client 측 contract allowlist에 `card-extract-v1|card-role-v1|card-synthesis-v1` 추가·prompt 100,000자 상한 적용·`validate_payload`를 세 schema에도 적용)·`company_deep_review` gate 순서·`transfer_policy` 검사·cap. contract→schema 파일→client 검증 매핑: `card-extract-v1`→`bidops.requirement-extract.v1.json`, `card-role-v1`→`bidops.verdict-role.v1.json`, `card-synthesis-v1`→`bidops.practitioner-verdict.v1.json`(runner `CONTRACTS`와 `contracts/__init__.py` 맵에 동시 등록). hosted fallback 없음.

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| HP-03·04 wire 계약 채택, 차이만 명세 | HP 계약 §6~8이 "확정 뼈대"이고 사용자 결정 7(HP 설계는 입력으로 재사용) | 전면 재작성 |
| 정책 승인 + 자동 preview/approval | ADR-0073 결정 5(정책 단위) + 기존 동결·재검사 코드 재사용 | approval 테이블 제거 |
| `proposed`→`proposed_fact` unknown | ADR-0073 결정 6; 사용자 "proposed 추가" 결정 | inferred 취급 |
| 트리거 = 브리핑 추천 ∧ 준비 ready ∧ SW=Y(`sw_business_status='Y'`) | 사용자 수용(2026-10-16); 2026-10-17 사용자 인터뷰 D1로 개요 completed 조건 제거 | 등급 기반(기존), 개요 completed 유지(개요가 LiteLLM/vLLM 경로라 RL 모델 제약 위반) |
| 개요 비의존: `card-v1`은 개요 gate 생략·`overview_*` null·현재성에서 개요 비교 제외 | 2026-10-17 사용자 인터뷰 D1. 키 집합·테이블을 유지해 새 저장 없이 끝남 | `overview_*` 키 삭제(v2 키 집합·provenance 변경), Luna 개요 경로 부활(폐기 브랜치) |
| 전송 payload = 원문 unit + `confirmed` 전부 + `proposed`/`unknown`은 `{fact_key, status}` | 2026-10-17 사용자 인터뷰 D2. 초판 spec(값 포함)과 intent·T9(값 없음)의 충돌을 intent 쪽으로 정리 | `proposed`·`unknown` 값 전송, 대조 allowlist만 전송 |
| `qual:branch`는 `value.detail`, `staff:design_publishing`은 `value.available` | 2026-10-17 v2 fixture 대조(branch value는 객체, 디자인 `total` null) | 초판 경로 유지(항상 unknown·비교 불가) |
| 1차 범위 사전규격만 | 입찰공고는 첨부 취득·준비·개요 경로가 없음(코드 확인). 입찰공고 판정은 후속 기능. 2026-10-17 사용자 인터뷰 D9 확인 | 입찰공고 포함(파이프라인 신설 필요) |
| Slack 스레드는 가짜 서버까지 | 2026-10-17 인터뷰 D5(리더 권장안): 토큰 없음, `slack_message_ts` null이면 건너뜀 | 실제 Slack 증명 요구 |
| "확인 필요" 비중은 데이터 상태 | 2026-10-17 사용자 인터뷰 D13: 루트랩 v2(unknown 21건) 그대로 진행, 보강은 RL-05 전 인터뷰 | 판정 전 보강 |
| 자동 생성을 worker 역할이 수행(INSERT grant 5개) | 같은 날 자동화 유지; 대안 drain 1회/일은 하루 지연 | app 역할 drain만 |
| 참조 모드·Luna 플래그 유지 | 결과가 `unmeasured_reference`이고 기존 gate를 우회하지 않음 | 플래그 면제 |
| cap 초과는 다음 날 큐 | 사용자 수용; 자동 catch-up 금지 규칙과 충돌 없음(브리핑 생성 뒤 drain 1회) | 즉시 거부 |
| 사업기회 경로 REST 별칭 | ui-spec 레코드가 사업기회 id 기반 | 프런트에서 링크 해석 |
| 실패 완료는 스레드에 안 씀 | ux-review 결정 4 "분석 완료는 스레드" + 실패는 화면 상태 | 실패도 알림 |
| N/A — 역할 충돌 자동 해소 | HP §7 "종합이 해소하지 않음" | |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | HP-03 T1~T5(unit·batch·extract 검증·compare·역할/종합)를 루트랩 v2 fixture로 | 동일 기대 + `proposed_fact` unknown, allowlist 밖 요구 unknown, 직접생산 detail null → unknown, 지역제한은 `qual:branch.value.detail`("대구(본점), 세종")로 비교, 디자인 인력은 `staff:design_publishing.value.available`(5)로 비교 | 단위 |
| T2 | 정책 승인 CLI: identity·sha·모델 불일치, 중복 활성, 철회 | exit 2 code·UNIQUE·철회 1회 | 단위 |
| T3 | gate 순서: 승인 없음/sha 다름/scope 밖/cap 초과/RL 비활성/SW≠Y; 개요 run 없는 공고에서 `card-v1`은 통과·`narrative-v2`는 기존대로 `overview_not_completed` | 호출 0(실패 분기), code 정확(SW≠Y는 403 `effective_grade_ineligible`), preview 행 없음; `card-v1` 동결 입력 `overview_run_id`·`overview_sha256` = null | 단위 |
| T4 | 자동 트리거: 추천 생성 → 준비 없음→준비 시작→ready hook→(SW=Y 확인, 개요 run 없음)→worker 역할로 preview/approval/attempt 생성; completed 재트리거 없음; cap 큐·drain; 입찰공고·SW≠Y 추천은 트리거 없음 | WorkJob 수·순서·`verdict_request` 상태·worker 권한으로 INSERT 성공·`actor_kind=system`; 개요 run·개요 모델 호출 0 | 통합(PostgreSQL) |
| T5 | HP-03 T6~T8(PG append-only·fence·timeout) 테이블 이름 변경본 | 동일 | PostgreSQL |
| T6 | HP-04 T1·T2 + 사업기회 경로 별칭(사전규격 둘→최신·없음→none·병합) + feedback POST + 미들웨어 통과 경로(RL on/off) + `source_binding.company_sha256=graph_sha256` + `card-v1` review 현재성(개요 없이 `is_current=true`, bundle·문서·SW 변화는 stale) | shape·404·none | 통합(PG) |
| T7 | 화면: 상태 6종·표 정렬·필터·원문 패널·(추정)·쪽 미확인·금지 문자열·1280/1440 | Playwright app | 프런트 |
| T8 | 활동 `verdict_completed`·브리핑 `verdict_display`·Slack 스레드(가짜 서버) | 각 1건, 실패 시 0, `slack_message_ts` null이면 답글 0·오류 없음 | 단위 |
| T9 | 단계별 전송 payload 검사(위 "전송 payload 규칙", 루트랩 v2 fixture): (a) 활성 binding의 `confirmed` 사실이 빠짐없이 값과 함께 있음(`pref:solo_cap`·`pref:consortium`·`pref:subcontract`·`pref:amount_range` 포함), (b) `proposed`·`unknown` 항목의 키 집합이 정확히 `{fact_key, status}`(노드는 `{id, status}`)이고 `qual:credit_rating` value 문자열("BBB0")이 payload 어디에도 없음, (c) RL-02 노트 본문·승인 id·cap·`policy_version_id`·`policy_sha256`·`model_name`·`model_revision`·`generation_config_sha256`·binding sha 부재, (d) 공고 unit은 카드 + 여섯 영역 segment만, (e) 최상위 허용 키 집합 정확; 위반 fixture는 호출 전 `company_input_invalid` | strict | 단위 |
| T10 | 감사 이벤트 `analysis.transfer.sent` 필드·토큰/원문 부재 | 정확 집합 | 단위 |
| T11 | mock 전체 경로(bidops-local, 모델 없음; 자동 트리거 on 포함) | 연결 증명만(품질 아님), 자동 트리거 연결은 여기서만 증명 | 수동 |
| T12 | 실제 Luna 1건(폴리텍 사전규격, 로컬 원본 HWP; 자동 트리거 off·수동 요청; 승인·cap·사람 직전 확인; attempt당 약 24회 이내; 검증 실패 시 1회만 재시도) | 단계·근거·시간·감사 증거, `quality_status=unmeasured_reference`; "확인 필요" 비중은 데이터 상태로 기록 | 수동(real_data_run) |

## 컨벤션 반영 항목

- 테이블 4개(+`briefing_item.slack_message_ts`), REST 4개, 오류 code(`policy_not_approved`·`daily_cap_reached`·`policy_identity_mismatch`·`card_*` 6), reason_code `proposed_fact`, runner contract 3개, 정책 identity·행 선택 env, 설정 4개, 감사 action `analysis.transfer.sent`, lifecycle 확장점 `on_briefing_recommendation`(hook)·`briefing_verdict_display`(projection), `core/slack.post_thread_reply`, `bidops.briefing.v2`(verdict_display 확장), DEMO §5 origin enum 개정, worker INSERT grant 5개, `card-v1` 개요 비의존(v2 입력·`FrozenProvenance`의 `overview_*` nullable, DEMO §5·§6 예외 주석), 전송 payload 규칙(D2).
