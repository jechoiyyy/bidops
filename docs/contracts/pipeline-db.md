# 파이프라인 파일·DB

[전체 계약](../contracts.md). 기준일: 2026-10-21. 공통 REST·상태 규칙은 상위 문서를 함께 적용한다. 계약의 존재는 운영 활성화·품질 인수를 뜻하지 않는다.

## 파이프라인 파일 계약

모든 파일은 UTF-8, 불변 run 디렉터리, 명시적 schema version을 사용한다.

| 파일·schema | 생산자 | 소비자 | 핵심 의미 |
|---|---|---|---|
| `review-inputs/manifest.json` / `bidops.order-plan-review-inputs-manifest.v1` | 발주계획 실험 담당자 | 입력 검증기, 실행 담당자 | Git에서 제외된 회사 역량·prompt 본문의 상대 경로, 승인·초안 상태, 실행 허용 여부, SHA-256과 active 선택 |
| `selection-decision.json` / `bidops.order-plan-screening-selection-decision.v1` | C-2 사람 결정권자 | 선별 제품 정책·구현 담당자 | 선택한 stage1·stage2 binding, 측정 지표, 수용한 누락 artifact, 운영 활성화와 분리된 선택 상태 |
| `collected-notices.json` / `bidops.collected.v2` | collect | 표본 선정, 웹 적재 | 원본 회차, 정규화 notices, source window |
| `collection-provenance.json` / `bidops.collection-provenance.v1` | 사전규격·입찰 공통 collector | 재분류·운영 확인 | 원본 raw 상대 경로, 실행 옵션, 보존 페이지 SHA-256, 완전성·경고 |
| `collected-order-plans.json` / `bidops.collected-order-plans.v1` | `collect_order_plans.py` | 웹 적재 | 전체 발주계획 projection, 공식 계획번호·연관 공고번호·관측 범위·원문 hash |
| `validation-set.json` / `bidops.validation-set.v2` | collect sample | screen v2, 품질 기준선 | 고정 표본과 source identity |
| `screening-input.json` / `bidops.screening-input.v1` | runtime orchestrator | screen v3 worker | execution/run, 후보, 불변 binding |
| `screening-decisions.json` / `bidops.decisions.v2` | 과거 screen | v2 merge, 품질 baseline | 과거 판정 계약 |
| `screening-decisions.json` / `bidops.decisions.v3` | 현재 screen | v3 merge, 웹 적재 | 5개 관점, 반론, 종합, 근거 |
| `screening-failures.json` / `bidops.screening-failures.v1` | screen | 웹, 운영자 | 실패 stage/type, retry, 안전한 요약 |
| `screening-telemetry.jsonl` / `bidops.screening-telemetry.v1` | screen | 관측 적재 | 호출 span, model digest, token/duration |
| `screening-results.json` / `bidops.screening.v2` | legacy merge | report, 웹 적재 | 과거 결정적 HTML·feedback 입력 |
| `screening-results.json` / `bidops.screening.v3` | runtime merge | 웹 적재 | 성공 subset, partial/failure·execution binding; 현재 report renderer는 미지원 |
| `review-feedback.yaml` / `bidops.feedback.v2` | report/API export | 호환 가져오기 | 사람 리뷰 교환; DB가 적재 뒤 정본 |
| replacement provenance / `bidops.screening-replacement.v1` | full rerun publish | 적재·감사 | source run과 새 execution 관계 |

허용 merge는 `validation-set.v2 + decisions.v2 → screening.v2`와 `screening-input.v1 + decisions.v3 → screening.v3`다. 세대를 섞으면 중단한다. v3 성공 결과는 execution, run, policy, prompt, model digest, profile digest, input digest를 역추적할 수 있어야 한다. 일부 notice 실패 시 성공 subset과 failure artifact를 함께 보존하고 `partial_artifact=true`로 표시한다.

현재 `render_report.py`는 `bidops.screening.v2`만 허용한다. v3를 report stage에 전달하면 계약 오류로 종료하며, v3 HTML·feedback 연결은 구현되지 않았다. 소비자는 v3가 자동으로 보고서까지 이어진다고 가정하지 않는다.

사전규격·입찰 공통 collector는 `--output-dir`을 배타 생성한다. 기존 빈 폴더·파일·symlink와
허용 루트 이탈은 키 확인·HTTP 전에 거부하며 raw와 최종 JSON도 배타 쓰기한다. 웹·예약 호출은
출력 폴더를 선생성하지 않는다. `--from-raw SOURCE_RAW`는 원본을 읽기만 하고 별도의 새 회차에
바이트·hash를 검증 복사한다. 기본 `--allowed-root`는 저장소의 `data/runs`, 웹·예약은
`settings.bidops_root/data/runs`다. 테스트만 별도 허용 루트를 명시 주입한다.
provenance v1 필드는 `schema_version`, `generated_at`, nullable `source_raw`, `source_window`,
`options(rows,timeout,skip_bids,skip_prespecs)`, `sources`, `complete`, `warnings`,
`raw_pages[{path,source_path,sha256}]`다. 원본 경로는 허용 루트 상대 경로이고 자격증명은 없다.
페이지 누락·건수 불일치·안전 상한 등 부분 수집은 경고와 `complete=false`, exit 1로 남기며
웹·예약은 자동 적재하지 않는다. 중간 실패의 raw를 보존하고 재시도는 새 회차에서 수행한다.
정규화 v2와 사전규격·입찰의 종료일 포함(0000~2359), 발주계획의 종료일 제외는 유지한다.

`collected-notices.json`의 `bidops.collected.v2`는 T-11에서 유지한다. 입찰공고 원문에 이미 있는
`orderPlanUntyNo`를 기존 `lifecycle` 안의 선택적 `order_plan_no`로 투영할 뿐이며, 기존 필드의
의미·필수성·레코드 종류를 바꾸지 않는다. 따라서 과거 v2 파일은 그대로 유효하고, 새 v2 파일만
이 선택 필드를 가질 수 있다. 발주계획 전체 원본은 공고 계약의 조용한 확장이 아니라 아래의
독립적인 `collected-order-plans.json` / `bidops.collected-order-plans.v1`로 분리한다.

`bidops.collected.v2`는 사업 추적 연결을 위한 optional 필드 넷을 추가로 가질 수 있다(spec §1.2,
2026-09-17). 모두 미확인이면 `null`이고 기존 필드의 의미는 바꾸지 않는다.

| 필드 | 원천 | 값 |
|---|---|---|
| 사전규격 `demand_agency` | `rlDminsttNm` | 문자열 또는 `null`. 기존 `agency`는 발주기관(`orderInsttNm`) 그대로 |
| 입찰공고 `lifecycle.opening_at` | `opengDt` | timezone-aware ISO 또는 `null` |
| 입찰공고 `qualification_flags.sw_industry_1468` | 1468(소프트웨어사업자) 업종 조회 | `Y`(포함)·`N`(조회 성공·미포함)·`null`(조회 실패·부분 수집) |
| 발주계획 `bid_ntice_no_list` | `bidNtceNoList` | `collect_order_plans.py`의 필드명 오타를 고친 뒤 원문 값 |

`sw_industry_1468`은 수집기 플래그 `--tag-bid-sw-industry`로 켠 조회이며 1468 조회 원문은
`raw/industry1468-page-NNN.json`으로 별도 보관한다(파일명이 `bid-`로 시작하지 않으므로 재분류가
입찰공고 raw 페이지로 잘못 읽지 않는다). 수집 파일 최상위 `metadata.sw_industry_1468`에
`{status: complete|failed|partial|not_requested, total, pages}`를 남긴다. 조회가 실패·부분이면
그 회차의 모든 입찰공고 `sw_industry_1468`이 `null`이고 수집기는 경고와 함께 비0 종료 코드로
끝나 일일 스크립트가 적재 전에 멈춘다(다음 날 창에서 다시 조회). `demand_agency`·
`lifecycle.opening_at`·`qualification_flags.sw_industry_1468`은 값이 `null`이면 관측 snapshot에
넣지 않고, `demand_agency`는 값이 있어도 snapshot에 넣지 않는다(C-1 판정 입력이 이 필드를 싣지
않으므로 같은 회차 C-1 적재와 snapshot hash가 충돌하지 않는다). `Notice.demand_agency` DB 열에는
저장한다.

### 적재 CLI와 수집 색인 (spec §2)

`python -m app.lifecycle.ingest.cli`는 세 모드를 갖는다(`--run`/`--all`은 상호 배타).

| 모드 | 뜻 |
|---|---|
| `--run <회차>`(기본 `selection="validation"`) | 검증 표본(`validation-set.json`)이나 C-1 입력(`screening-input.json`)의 공고만 적재한다. 발주계획은 전량 적재한다. 기존 C-1 적재 경로이며 코드의 실제 selector 값은 `validation`이다 |
| `--run <회차> --collection`(`selection="collection"`) | 표본이 없어도 오류가 아니다. `collected-order-plans.json`·`collected-notices.json`의 모든 레코드를 `collected_record_index`(migration `0027`)에 한 행씩 남기고, 선별 규칙(아래 표)에 맞는 레코드만 같은 적재 경로로 적재한다 |
| `--tracked-backfill` | `계속 추적`·`보류` 사업기회가 가리키는 색인의 미적재 레코드를 찾아 적재한다(추적 상태 저장 직후와 daily 스크립트 마지막 단계에서도 호출) |

선별 사유 코드(`ck_collected_record_index_selection_reason`과 같은 닫힌 집합)는
`order_plan_all`, `pre_spec_sw`, `pre_spec_referenced`, `pre_spec_known`, `bid_same_notice_no`,
`bid_tracked_reference`, `bid_sw_prespec_reference`, `bid_sw_industry_competitive`,
`tracked_backfill`, `search_result` 10개다. 조건에 쓰는 값이 `null`이면 그 조건은 불일치로 보고
색인에만 남긴다(추정 적재하지 않는다). `--collection` 적재의 `IngestResult.selection`과
`run.counts_json["selection"]`은 원천(`order_plan`·`pre_spec`·`bid_notice`)별
`{collected, selected: {사유코드: 건수}, skipped}`이며 `collected = sum(selected) + skipped`가
항상 성립한다. 이 통계는 **그 회차 적재 시점의 선별 결과 snapshot**이다 — 나중에 추적 보충
(`--tracked-backfill`)이나 찾아보기(`POST /api/opportunities/{id}/searches`)로 적재된 레코드는
색인 행의 `selection_reason`에만 반영되고 회차 통계는 다시 쓰지 않는다. 같은 회차 재실행은
색인 unique 제약과 관측 snapshot 검사로 no-op이다.

발주계획 artifact의 canonical `order_plans[]`는 실측 API 필드를 다음처럼 보존·정규화한다.

artifact의 `metadata`에는 endpoint 식별자와 적용한 업무구분 범위를 함께 남긴다. 현재
생산자 범위는 `bsnsDivNm`의 `일반용역`·`기술용역` allowlist이며, 범위 밖으로 제외한 원문
건수는 `counts.excluded_out_of_scope`와 `counts.excluded_business_divisions`에 기록한다.
`metadata.order_month_scope`는 PPSSrch가 요구하는 `200412`~`999912` 보조 범위이고,
`metadata.collection.complete=false`이면 페이지 안전 상한 등으로 부분 수집된 회차다.

- `order_plan_unty_no` ← `orderPlanUntyNo`, `title` ← `bizNm`
- 기관은 `orderInsttCd`·`orderInsttNm`·`totlmngInsttNm`, 업무·서비스는
  `bsnsDivCd`·`bsnsDivNm`·`bsnsTyCd`·`bsnsTyNm`을 사용한다.
- 금액은 `sumOrderAmt`·`orderContrctAmt`, 예정 시기는 `orderYear` + `orderMnth`,
  방식은 `prcrmntMethd`·`cntrctMthdNm`을 사용한다.
- `published_at`/`changed_at`은 각각 `nticeDt`/`chgDt`, 연관 공고는
  `bid_ntice_no_list` ← `bidNtceNoList`, 게시 여부는 `notice_posted` ← `ntceNticeYn`,
  원문 URL은 `source_url` ← `orderPlanDtlUrl`이다.
- `rcrit_rgst_no` ← `rcritRgstNo`는 빈 응답도 `null`인 계약 필드로 남긴다. 발주계획 응답에서
  측정되지 않은 SW 상태는 `sw_business_status: null`과 `unknown_fields`로 검증 대기 상태를
  구분한다. `first_discovered_at`, `last_discovered_at`, `source_sha256`, `raw_source`도
  각 항목에 유지한다.
- `bidNtceNoList`와 `ntceNticeYn`은 공고 전환·재관측 비교의 신호다. `chgDt`는 관측 값으로
  보존하지만 갱신 감지 신호로 사용하지 않는다.

이 artifact의 loader는 `OrderPlan`을 공식 계획번호로 누적 upsert하고
`OrderPlanObservation(order_plan_id, run_id)`를 추가한다. 신규 observation은
`bidops.order-plan-observation-snapshot.v1`의 결정적 정규화 snapshot과 그 lowercase
SHA-256을 함께 보존한다. 확인되지 않은 키는 warning으로 기록하고 해석하지 않는다.
이전 실험 산출물의 `bidops.order-plan-population.v1`와 `items` 목록은 읽기 전용 호환
입력으로만 취급하고 canonical 파일을 덮어쓰지 않는다.

`NoticeObservation`의 신규 snapshot schema는
`bidops.notice-observation-snapshot.v1`이다. 두 snapshot 모두 top-level
`schema_version`, `record_kind`, `record`를 가지며 notice snapshot은 수집 artifact가
첨부 목록을 제공한 경우 안전한 첨부 metadata 목록도 가진다. snapshot hash는 이 payload를
UTF-8, key 정렬, 공백 없는 JSON으로 직렬화해 계산한다. 같은 외부 식별자와 run에 같은 hash가
다시 들어오면 no-op이고 다른 hash면 회차 전체를 rollback한다. `0009` 이전 observation의 세
snapshot field는 추정 backfill하지 않으며, 같은 과거 회차 재적재는 warning과 함께 projection
변경 없이 건너뛴다.

승계 판정은 `carried_over=true`, 최초 `judged_in_run`, 현재 `recorded_in_run`을 보존한다. 승계를 새 모델 호출로 기록하지 않는다. 승계 validation 실패는 별도 성공 판정으로 만들지 않고 사람 검토 대기 failure로 남긴다.

## DB와 migration 계약

- 코드의 현재 Alembic head는 `0041_proposal_draft`(`app/core/db.py`)다. 마지막 운영 적용은 2026-10-19의 0041이며 [현황](../tracking/status.md)을 따른다. 아래 migration 목록은 도입 이력이고 최신 head 전체 목록이 아니다. 전체 해설은 [DB 가이드](../database-guide.md), `0037`~`0041`의 현재 소비 계약은 [RL](rl.md)·[레코드 활동](lifecycle-rest.md)에 있다.
- 사전규격 개요 `0026`은 [개요 DB 계약](prespec-overview.md#db-prespec_overview_run-migration-0026-0031-확장), 이전 T-23 phase 2 증거는 `0014_prespec_overview_attempt_result` 경계에 해당한다.
- `0001_lean_v1_postgresql`은 기존 수집·리뷰와 심층 검토 table, `0002_screening_basis_text`는 긴 판정 설명 보존, `0003_screening_runtime_pg`는 판정 실행·품질·정책·일정·감사와 불변 trigger를 추가한다.
- `0004_cumulative_external_identity`, `0005_opportunity_links`, `0006_bid_first_opportunity_registration`은 공고·발주계획 누적 관측, opportunity 공식 링크, 입찰공고 최초 등록과 대기 참조 해소를 추가한다.
- `0007_opportunity_tracking_state`는 사업기회 추적 상태를 추가한다. `tracking_status`는 `미선택`·`계속 추적`·`보류`·`종료`이고 기본값은 `미선택`이다. CHECK가 `미선택`일 때 작성자·이유·시각이 없고 그 밖의 값일 때 작성자와 시각이 반드시 있음을 강제한다. 시스템 재검토 신호(`recheck_signal_at`, `recheck_signal_link_id`)는 사람 선택 컬럼과 분리되어 있고 근거가 된 `opportunity_link`를 가리킨다.
- `0008_prespec_attachment_fetch`는 사전규격 첨부 바이트의 조건부 취득·재평가·lease 상태를 `attachment_fetch`에 기록한다. 문서 bundle 없이 source provenance가 있는 `DocumentVersion`을 만든다.
- `0009_observation_snapshot_retention`은 신규 공고·발주계획 observation에 nullable legacy 호환 snapshot schema·JSONB·SHA-256 묶음을 추가한다. 기존 observation은 `null` 그대로 두며, 수집에서 사라진 provider 첨부는 삭제하지 않고 `retired_at`·`retired_reason`으로 보존한다.
- `0010_opportunity_link_integrity`는 authoritative target별 partial unique index와 non-destructive opportunity merge lineage를 추가한다. migration은 기존 authoritative 중복을 자동 수정하지 않고 충돌 target/link ID를 제시하며 중단한다. 자동 merge는 모든 row가 `미선택`이고 recheck state가 없을 때만 가능하다.
- `0011_judgment_review_revisions`는 현재 `Judgment`·`Review` projection을 유지하면서 notice별 append-only `judgment_revision`·`review_revision` 이력을 추가한다. 판정 revision은 observation run, 기록 screening execution, 같은 notice의 승계 parent를 분리해 보존하고, 사람 review revision은 선택적으로 정확한 judgment revision을 고정한다. 두 payload는 ID를 넣지 않은 `bidops.judgment-revision-payload.v1`·`bidops.review-revision-payload.v1` JSON object와 canonical lowercase SHA-256을 저장한다. 기존 review의 run이 같은 notice observation이 아니면 migration은 ID를 제시하고 중단하며, legacy review의 과거 judgment alignment는 추정하지 않아 `judgment_revision_id=null`로 남긴다.
- `0012_prespec_overview_review`는 사전규격 개요 review의 현재 상태와 clean `DocumentVersion`·`DocumentStructure`를 연결한 append-only 절단 snapshot, 향후 모델 attempt 계보를 추가했다. snapshot은 source/payload hash와 deterministic prefix locator를 고정하고, 현재 구조가 갱신되면 과거 snapshot을 덮지 않고 새 row를 만든다. 이 revision의 attempt 전체 append-only trigger는 `0014`에서 제한된 lifecycle UPDATE 계약으로 교체된다.
- `0013_document_integrity`는 attachment가 있는 문서의 `(attachment_id, version)`과 attachment별 current 최대 1개를 partial unique index로, bundle 안 ordinal을 UNIQUE로 강제한다. 기존 충돌은 ID와 키를 제시하고 추정 보정 없이 migration을 중단한다.
- `0014_prespec_overview_attempt_result`는 phase-1 attempt의 review/input/binding/result 참조와 result/event table을 추가한다. FK·UNIQUE·CHECK가 row 구조를 강제하고, 단일 DB trigger는 허용 상태 간선만 검증한다. runtime privilege는 app에 안전 조회, worker에 attempt/result/event의 최소 SELECT·INSERT와 attempt의 `status`·`started_at`·`completed_at`·`result_id` column UPDATE만 허용해 입력 계보와 result/event의 UPDATE·DELETE를 막는다. result scope, timestamp 의미, event 동반과 review projection은 service transaction에서 검증하며 교차 table trigger로 중복하지 않는다. legacy inline result/completed attempt가 발견되면 추정 보정 없이 upgrade를 중단하고, downgrade도 phase-2 row가 남아 있으면 거부한다.
- `0018_prespec_auto_preparation_segments`는 자동 준비와 결정적 문서 segment를 추가한다.
  `ck_attachment_fetch_eligibility_reason`에 `priority_grade` 자격 사유를 더하고,
  `ck_prespec_overview_attempt_completed_binding`을
  `status <> 'completed' OR reference_only IS FALSE`로 교체한다. 품질을 아직 재지 않은 실제
  모델 실행(`deployable=false`)도 완료될 수 있고 **mock 참조 실행(`reference_only=true`)만**
  완료를 막는다는 뜻이다. 상태 전이 trigger는 그대로 둔다. `prespec_overview_attempt`에 nullable
  `lease_owner`(varchar 255)와 `lease_expires_at`(timestamptz)을 더하고, worker의 column-scoped
  UPDATE 허용 열을 `status`·`started_at`·`completed_at`·`result_id`·`lease_owner`·`lease_expires_at`으로
  넓힌다. 새 table 셋(`document_segment_manifest`, `document_segment`,
  `requirement_inventory_item`)은 append-only이며 FK는 `ondelete=CASCADE`,
  `(document_version_id, structure_id)` 복합 FK를 함께 갖고, 유일키는
  `(structure_id, taxonomy_version, extractor_binding_sha256)`다. runtime role에는 SELECT와
  INSERT만 준다. downgrade는 `priority_grade` 행, `deployable=false` 완료 attempt, 세 table의
  행이 하나라도 있으면 추정 보정 없이 거부한다.
- `0027_collection_index_and_linkage`는 `collected_record_index`(선별 여부와 무관하게 수집
  레코드마다 한 행, unique `(run_id, record_kind, record_key)`)와 자식 `collected_record_token`
  (`bidNtceNoList` 토큰)을 추가한다. `notice.demand_agency`(사전규격 수요기관)와 같은 공고번호의
  다른 차수 조회용 `ix_notice_bid_no`(기존 `0001`로 생성된 신규 DB에는 이미 있음, 기존 DB에만
  추가)도 더한다. `opportunity_link`의 `ck_opportunity_link_status`에 `사람 확인 병합`,
  `ck_opportunity_link_search_strategy`에 `merge_confirmation`을 더하고 `검색 미확인` 행이 어느
  종류를 찾다 실패했는지 구분하는 nullable `search_target_kind`(`pre_spec`·`bid_notice`)와 CHECK를
  추가한다. downgrade는 색인 행, non-null `demand_agency`, 새 status·strategy·search_target_kind
  값이 하나라도 있으면 거부한다. 권한: app SELECT/INSERT와 색인의 `selection_reason`·
  `ingested_*` 열 UPDATE, worker SELECT; 토큰 table은 app SELECT/INSERT.
- `0028_final_decision_basis`(ADR-0058)는 `bid_final_decision`의 비교 5열
  (`comparison_id`·`comparison_version`·`result_sha256`·양쪽 document version ID)을 nullable로
  바꾸고, `basis_kind`(`comparison`\|`notice_conditions`, NOT NULL, 기존 행은 `comparison`),
  `basis_notice_id`(FK `notice`), `basis_observation_sha256`(64 hex)을 추가한다. CHECK는 근거가
  `comparison`이면 비교 5열이 모두 있고 basis 두 열이 비고, `notice_conditions`면 그 반대임을
  강제한다. `ADD COLUMN ... DEFAULT`로 기존 행을 채운 뒤 기본값은 지워 새 INSERT가 근거를
  명시하게 한다. append-only trigger·unique·supersession FK는 그대로다. downgrade는
  `notice_conditions` 행이 하나라도 있으면 거부한다. 권한: app에 `bid_final_decision` INSERT와
  tip 잠금용 `UPDATE (id)`를 추가하며 비교·attempt·item·evidence 권한은 바꾸지 않는다.
- `0029`(ADR-0060, 예정)는 C-2 품질 게이트·evaluation·감사 표본·일일 스위치 4테이블과
  `order_plan_screening_execution.purpose`를 추가한다. 열·제약·권한은 [C-2 DB·migration 경계](c2.md#c-2-dbmigration-경계-phase-2-구현-입력)의 `0029` 절이 정본이다.
- 앱 startup은 revision과 필수 table 존재만 확인한다. migration과 seed를 실행하지 않는다.
- fresh migration은 schedule과 always-on singleton, migration audit만 만든다. screening policy와 agency portal은 명시적 운영 명령 또는 API로 생성한다.
- active screening slot과 active policy는 각각 최대 하나다. queue claim은 queue number FIFO와 짧은 transaction으로 처리한다. deep-review job claim은 PostgreSQL row lock과 `SKIP LOCKED`를 사용한다.
