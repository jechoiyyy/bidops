# 사전규격 개요 검토

[전체 계약](../contracts.md). 기준일: 2026-10-21. 공통 REST·상태 규칙은 상위 문서를 함께 적용한다. 계약의 존재는 운영 활성화·품질 인수를 뜻하지 않는다.

## 사전규격 개요 검토와 예비 적합성 판단 (MVP, 2026-09-21)

v3 권고형 개요, legacy v4 단일 호출 개요, v5 주장 검증 스택(activation v2·call
ledger·verification)은 폐기했다([ADR-0054](../tracking/decisions/0054-prespec-overview-mvp-rewrite.md)).
`prespec_overview_run` 단일 테이블과 `bidops.prespec-overview.v1|v2` 계약으로 처리한다. v1은
기존 개요 run, v2는 사실 개요와 예비 판단을 분리해 담는 새 run이다([ADR-0066](../tracking/decisions/0065-prespec-overview-preliminary-assessment.md)). 첨부
취득·묶음·자동 준비·document_mcp 변환·PDF/쪽 텍스트 스냅샷(`prespec_v4_pdf_snapshot`,
migration 0021/0023/0024)과 주장 결정적 검증 함수는 그대로 유지한다.

### 설정

- `BIDOPS_PRESPEC_OVERVIEW_ENABLED`(bool, 기본 `false`). `true`면 묶음이 ready가 될 때 개요
  run을 자동 enqueue한다. `false`면 enqueue하지 않고 queued run은 `cancelled`로 닫는다.
  이미 `running`인 run은 끝까지 진행한다. `true`인 동안에는 자동 준비와 개요 enqueue의 등급
  조건이 "effective grade `우선 검토` **또는** `SW사업대상=Y`"로 완화된다(2026-09-11 MVP 결정).
  운영 DB에 C-1 판정이 0건이라 `우선 검토`가 없으면 개요를 한 번도 실행할 수 없기 때문이며,
  플래그가 `false`면 완화 없이 기존 등급 규칙만 적용한다.
- `BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH`(기본 `app/deep_review/policies/prespec-overview-policy-v7.json`).
  v7은 개요를 **앞부분 요약 세 절**로 좁힌다([ADR-0057](../tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md)).
  loader는 v7, 불변 `prespec-overview-policy-v8.json`, 로컬 LiteLLM 참조용
  `prespec-overview-policy-v7-litellm-v1.json`의 exact identity만 읽는다. LiteLLM 정책은 v7에서
  `model_name=local-agent-main`, `model_endpoint_ref=litellm-openai-compatible`,
  `prompt_version=prespec-overview-v7-litellm-v1`만 다르고 schema·generation·검증·한도는 같다.
  `prespec-overview-policy-v7-litellm-v2.json`(2026-10-15 Mac 운영 경로)은 litellm-v1과 같은 프롬프트에
  stage 호출 timeout 900초·`max_completion_tokens` 8192·run `timeout_seconds` 900·`lease_seconds`
  3060만 다르다. loader는 (timeout, generation) 짝을 `model_client.APPROVED_EXECUTION_PROFILES`의
  표준(300/16384)·LiteLLM(900/8192) 둘 중 하나로만 받고, LiteLLM 짝은 `model_endpoint_ref`가
  LiteLLM transport인 정책에서만, 모든 stage가 같은 짝이고 run 한도가 그 짝의 한도와 같을 때만 받는다.
  `litellm` dialect 요청 body에는 `reasoning_effort=none`이 함께 실린다.
  기본 경로나 전역 모델 설정을 바꾸지 않으며 로컬 참조 실행에서 경로로 명시 선택한다. v8은 같은 세 절과
  예비 판단을 통합 생성하지만 기본 경로가 아니며 품질 비교·migration·배포·정책 변경 승인 전에는
  운영 활성 정책으로 보지 않는다. v6 파일은 기존 run 기록으로만 남는다.

### v8 생성·판정 계약

- 통합 초안 `bidops.prespec-overview-assessment-draft.v1`은 기존 사실 claim 객체와
  `bidops.prespec-preliminary-assessment.v1`을 자식으로 갖는다. 안전한 최상위 JSON을 확인한 뒤
  두 자식을 독립 파싱한다. 판단 자식만 틀리면 개요를 보존하고 `held`로 기록한다.
- 판단은 세 축 `ai_data|blockchain_did|public_si_integration`, 관계
  `direct|partial|indirect|unrelated|unknown`, 실제 수행 역할, 핵심 과업 claim ID, 선택한 회사
  fact ID, 확인 항목을 담는다. 모델은 한국어 등급 라벨을 출력하지 않는다.
- 서버 등급은 가장 강한 유효 관계로 계산한다. 핵심 과업·원문 claim·회사 fact 참조가 유효하지
  않거나 profile이 손상됐거나 역할/관계가 미확인이면 `assessment_status=held`,
  `assessment_grade=null`이다. 세 축이 모두 무관한 `제외`는 선택 의미검증 통과가 필수다.
- 선택 의미검증은 `bidops.prespec-overview-assessment-semantic.v1`이며 claim과 세 axis를 함께
  검사한다. 제외 후보, `quantity_relation_ambiguous`, `delivery_role=unclear`, 모델 uncertainty,
  검증 인용과 생성 문장의 부정·조건 표식 차이가 trigger다. 상태는 `not_run|passed|failed`, 범위는
  `overview_full`, `assessment_axes`, `claim:<id>`, `axis:<id>`로 저장한다. 미실행을 통과로 바꾸지 않는다.
- 호출 상한은 정상 1, 선택 의미검증 포함 2, 형식 재시도 포함 3회다. 사실 오류 재생성, 의미검증
  재시도, 다른 provider fallback은 없다. 선택 의미검증의 기술 실패는 유효한 개요를 유지하고
  등급만 보류한다.
- 선택 프로필은 `BIDOPS_ACTIVE_PROFILE_VERSION_ID`만 독립 해석한다. 미설정은
  `not_configured`, 누락·hash/lineage 손상은 `invalid`이며 손상된 fact는 모델에 보내지 않는다.
  `ready`에서도 `confirmed` fact의 최소 `ref|value|quote`만 동결한다.

### 상태 의미

| status | 뜻 | 자동 심층 검토 |
|---|---|---|
| `queued` / `running` | 대기·실행 중 | 대기 |
| `completed` | 남은 주장이 결정적 검사·의미 검토를 통과, `result_json` 있음 | 진행 가능 |
| `needs_human_review` | 통과 주장이 절반 미만·주장 0개(`claims_empty`)·주장/분석의 의미 검토 contradicted/insufficient | `overview_not_completed` |
| `failed` | 기술 실패(`reason_codes`: `pdf_preparation_failed:<code>`, `manifest_invalid`, `draft_format_retry_exhausted`, `semantic_schema_invalid`, `semantic_missing_ids`, `semantic_duplicate_ids`, `semantic_response_invalid`, `timeout`, `input_capacity_exceeded`, `call_budget_exhausted`, `response_store_unavailable`, `lease_expired`, `runner_failed`) | `overview_not_completed` |
| `cancelled` | 플래그 off로 닫힘 | `overview_not_completed` |

종결 사유 코드 중 실행 자체가 막혀 닫는 세 가지는 다음과 같다.

| reason code | 닫히는 status | 뜻 |
|---|---|---|
| `attempts_exhausted` | `failed` | `work_job.max_attempts`를 이미 쓴 queued run을 claim하지 않고 닫았다 |
| `identity_unavailable` | `failed` | 모델 신원 확인이 연속으로 막혀 남은 시도를 다 썼다 |
| `operator_close` | `queued`→`cancelled`, `running`→`failed` | 운영자가 `close-overview-run`으로 닫았다 |

공고의 "현재 개요"는 `created_at` 최신 run이다. 이력은 그 공고의 모든 run.
목록·상세의 `overview_review_status`는 최신 run의 status를 그대로 쓰고, run이 없으면 `null`이다.
자동 심층 검토 사유 판정 순서는 `not_sw_business → bundle_not_auto_ready →
overview_not_completed → service_unavailable → 회사 핏 사유`다. `overview_recommendation_closed`·
`overview_bundle_mismatch`는 삭제됐다.

### REST (`bidops.prespec-overview.v1|v2`)

| 경로 | 응답 |
|---|---|
| `GET /api/pre-specs/{notice_id}/overview` | `{schema, notice_id, current: Run\|null, history: Run[], range_review: RangeReview\|null, verification: Verification\|null}` |
| `POST /api/pre-specs/{notice_id}/overview/range-confirmations` | body `{page_start, page_end, note?}` **또는** `{candidate_indices: [시작 index, 끝 index], note?}`(둘을 함께 보내면 `range_invalid`), `X-BidOps-Actor-Name` 헤더(비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent`). 409 `run_active`(queued/running 있음), 409 `document_not_current_safe`, 422 `range_invalid\|candidate_range_incomplete\|candidate_range_unavailable`. 201 `{run_id, attempt_enqueued: true, page_start, page_end}` |
| `GET /api/pre-specs/{notice_id}/overview/runs/{run_id}/pdf` | 그 run이 읽은 고정 스냅샷 PDF. 404/409 safe 오류 |
| `GET /api/pre-specs/{notice_id}/overview/snapshot/pdf` | run이 없어도 여는 최신 고정 스냅샷 PDF(범위 확정용). run PDF와 같은 경계. 404 `not_found`, 409 `document_not_current_safe`, 503 `pdf_unavailable` |

절 후보 index로 확정하면 서버가 쪽으로 바꾼다: 시작은 고른 절의 쪽, 끝은 **다음 절의 쪽**(마지막
절이면 문서 끝 쪽)이다. 화면은 이 계산을 하지 않는다. 후보가 일부만 있으면
`candidate_range_incomplete`, 후보를 읽을 수 없으면 `candidate_range_unavailable`이며 둘 다
사람이 쪽 범위를 직접 넣어야 한다.

Run 응답 필드: `id, status, range_source(auto|fallback|human), page_start, page_end,
range_reason_codes, reason_codes, warnings, result(완료 시:
business_overview/main_tasks/budget_and_period 각
[{claim_id,text,evidence:[{page,quote}]}], input_limitations[]),
failed_claims(`completed`·`needs_human_review` 모두:
[{claim_id,section,text,reason_codes,evidence}]), model_name, model_revision,
call_count, actor_name, created_at, started_at, completed_at`. 모델 원문·`raw_response_refs`·
내부 경로는 반환하지 않는다.

v2 Run은 여기에 `contract_version=overview-assessment-v1`, `assessment{result,checks,grade,
status,semantic_status,semantic_scope}`와 `input_binding{policy_digest,prompt_version,
validator_version,profile_version_id,profile_digest,profile_status,generation_config_digest,
input_binding_sha256,reused_from_run_id}`를 더한다. profile fact 본문과 원응답 참조는 공개하지 않는다. v1·v2 이력이
섞이면 각 run의 저장 버전으로 읽고, envelope `schema`는 v2 run이 하나라도 있으면
`bidops.prespec-overview.v2`다.

`GET /api/pre-specs`는 기존 `grade`·`grade_source`를 유지하면서 `display_assessment`를 추가한다.
`display_assessment`는 `{grade?,status=graded|held|none,source=human_review|preliminary_assessment|
screening_judgment|none,basis_run_id?,assessed_at?,quality_status?,reason_codes[],axes[],
verification_items[],semantic_status?,semantic_scope[],latest_run_status?}`다. 대표값은 사람 정정 →
현재·safe 문서의 최신 v2 graded/held → 기존 선별 등급 → 없음 순이다. 최신 기술 실패·취소·대기는
이전 유효 대표값을 지우지 않고 `latest_run_status`에만 나타난다.

목록 query `display_grade`는 `우선 검토|검토 권장|관찰 대상|제외|판단 보류|판정 없음`이고 기존
`grade` 필터와 독립이다. 서버가 페이지 분할 전에 적용해 `items`, `total`, 건수가 같은 집합을
읽는다. 구버전 화면 URL의 `grade`는 프런트가 `display_grade`로 한 번 정규화한다.

Run의 파생 필드(저장 값을 옮긴 것이며 새 판정이 아니다):

| 필드 | 값 |
|---|---|
| `result_id` | `completed`면 run id, 그 밖에는 `null` |
| `prompt_version` | 정책 문서의 `prompt_version`. 정책을 읽을 수 없으면 `null` |
| `verification_status` | `checks_json`이 있으면 `passed\|needs_human_review`, 없으면 `null` |
| `document_version_id` | run이 읽은 문서 |
| `source_sha256`·`pdf_sha256`·`pdf_page_count` | run의 동결 스냅샷 값. 준비 전이면 `null` |
| `reviewed_pages` | `[page_start..page_end]` 정수 배열. 범위가 없으면 `[]` |
| `payload_sha256` | `result_json`의 canonical JSON sha256. 없으면 `null` |
| `quality_status` | `model_name`이 `mock`으로 시작하면 `mock_reference`, 아니면 `unmeasured_reference`. **측정된 품질이 아니다** |
| `validation_status`·`evidence_check_status` | `completed`면 `passed`, 그 밖에는 `failed` |
| `validation_errors`·`evidence_check_errors` | run의 `reason_codes` 배열 |

`range_review`(ready 묶음 RFP 문서의 최신 스냅샷이 없으면 `null`):

| 필드 | 값 |
|---|---|
| `target_id` | 최신 run id. run이 없으면 `null` |
| `status` | 최신 run이 `human`이면 `human_confirmed`; `fallback`이거나 `needs_human_review\|failed\|cancelled`이거나 run이 없으면 `pending`; 그 밖에는 `ready` |
| `document_version_id`·`pdf_page_count` | 스냅샷 값 |
| `mode` | 후보 산출물의 `outline\|clause\|page`. 후보가 없으면 `null` |
| `candidate_status` | `complete\|partial\|unavailable` |
| `candidate_count_total`·`candidate_count_returned` | 후보 산출물의 `section_count`와 반환 수 |
| `candidates` | `[{index(0부터), title, page(1부터), char_count}]` |
| `selected_pages` | 최신 run의 `[page_start, page_end]`. 없으면 `null` |
| `warning_codes` | 후보가 부분이면 `section_candidates_incomplete`, 읽을 수 없으면 `section_candidates_unavailable` |
| `reason_code` | 최신 run의 `range_reason_codes[0]`, 없으면 후보 경고 코드, 그것도 없으면 `null` |
| `can_confirm` | 활성 run이 없고 문서·원본이 지금 current·safe일 때만 `true` |
| `assisted` | 항상 `null`(범위 보조 실행은 MVP에 없다) |
| `confirmation` | 가장 최근 사람 확정 `{page_start, page_end, actor_name, note, created_at}`. `note` 본문은 저장하지 않으므로 항상 `null`이고 없으면 전체가 `null` |

2026-09-16 [ADR-0057](../tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md) 결정 1로
`result`에서 `important_conditions`·`reviewer_analysis`·`unknowns` **key가 사라졌다.** 빈 배열이
아니라 key 자체가 없으며, 그 자리는 심층 검토가 갖는다. 저장된 `result_json`의 계약 식별자는
`bidops.prespec-overview-claims.v2`이고 폐기된 `bidops.prespec-overview-page-review.v4`는 더
이상 생산하지 않는다. v4 시절 행은 그대로 두고 읽을 때 세 절만 투영한다.

`verification`(현재 run에 `checks_json`이 없으면 `null`): `{verification_id: run id, status:
passed\|needs_human_review, reason_codes: [], claims: [{claim_id, section, text,
deterministic: {status: passed\|failed, reason_codes: []}, semantic: {status:
supported\|contradicted\|insufficient\|not_run, reason_codes: []}, verified_evidence: [{page,
quote, start_char, end_char}]}]}`. `page_text_sha256`은 내부 결속 값이라 나가지 않는다.

### 실행 흐름

analysis worker의 개요 slot이 enqueue(플래그 on ∧ 활성 run 없음 ∧ effective grade
`우선 검토` ∧ ready 묶음에 RFP 문서) → claim(WorkJob lease 1,200초) →
prepare(snapshot 없으면 `prepare_v4_pdf_snapshot`, 변환 300초) → range(human 확정값 또는
자동 선택, 실패 시 fallback 1쪽~min(60쪽,100,000자)에 `range_fallback_head`; 전 쪽 공백이면
`failed/manifest_invalid`) → draft(1회, 형식 오류 시 1회 재생성) →
deterministic(인용 1곳 대응·페이지 범위·duplicate_id 실패와 주장 0개
(`claims_empty`)는 `needs_human_review`; 섹션 배정·수치·역할·VAT·기산점·date·latin·
requirement_id는 warnings) →
semantic(1회; 남은 주장이 모두 supported면 `completed`) → save 순서로 진행한다. 호출 상한은 attempt당
3회(초안 2, 의미 1)이며 상한을 넘기면 `call_budget_exhausted`로 닫는다. 정책은
`prespec-overview-policy-v7.json`(max_pages 60, max_page_text_chars 100000,
max_prompt_chars 120000, max_claims 12, max_model_context_tokens 393216).
의미 단계 입력에는 `expected_claim_ids`와 `expected_check_count`가 들어가고, 그 run의 응답
schema `checks`는 `minItems=maxItems=expected_check_count`로 좁혀 나간다. 정책 파일의
`max_claims`는 상한 검증으로만 남고 **정책 digest는 바뀌지 않는다.** 문맥 상한 판정은 요청 JSON의 byte 수를 token 상계로 쓰므로
한국어 100,000자 입력이 지나갈 수 있도록 천장을 함께 올렸다. 서버가 `max_model_len`을 내지
않으면 초과 판정을 하지 않고 run의 `warnings`에 `context_unverified`를 남긴다.

결정적 검사에서 `quantity_mismatch`·`quantity_metadata_mismatch`·`quantity_relation_ambiguous`·
`quantity_unit_missing`·`date_mismatch`·`requirement_id_mismatch`·`latin_term_mismatch`·
`required_fact_missing`(섹션 배정 쏠림)·`evidence_fragment_match`(2단 편집 쪽에서 인용을 줄·
리스트 표식·생략 기호(`…`·`...`) 조각으로 나눠 순서대로 대조해 통과)·`evidence_dropped`(인용
둘 중 하나만 `quote_not_found`·`quote_ambiguous`라서 그 인용만 뺐다)는 **비차단 경고**이며
run의 `warnings`에만 남는다. 차단은 `quote_not_found`·`quote_ambiguous`·`quote_empty`·
`page_out_of_range`·`evidence_missing`·`fact_empty`·`duplicate_id`뿐이며, 주장이 한 개도
없으면 run은 `needs_human_review/claims_empty`로 닫는다.

#### 범위 선택 전략과 사유 코드 (2026-09-16)

자동 선택은 **목차 우선**이다(ADR-0057 결정 2). 입력 manifest의 `strategy`는
`toc_scope`(목차 항목의 인쇄 쪽을 본문 제목 대조로 물리 쪽에 맞춰 고름)·`heading_scope`(본문
heading만으로 고름)·`human_confirmed`(사람이 확정한 쪽 span) 셋이다. `range_source`는
그대로 `auto|fallback|human`이며 `toc_scope`·`heading_scope` 모두 `auto`다. 목차 전략은 절 후보를
쓰지 않으므로 절 후보 완결성(`candidates_truncated`)과 무관하게 먼저 시도하며, 후보가 잘렸을 때의
자동 확정 금지(`section_candidates_incomplete`)는 목차가 실패한 뒤의 본문 전략에만 적용한다.

목차 전략이 실패하면 본문 전략으로 내려간다. 실패 사유는 `toc_missing`(앞 5쪽에
"제목 … 쪽번호" 항목이 4개 이상인 쪽이 없음)·`toc_alignment_failed`(인쇄 쪽 → 물리 쪽
offset을 두 장 이상에서 같은 값으로 확정하지 못함)·`toc_target_missing`(시작·끝으로 삼을 장
항목이 없음) 셋이다. **자동 선택이 성공하면 `range_reason_codes`는 비어 있다** — 어느 전략을
썼는지는 manifest `strategy`가 말하며, 성공한 선택에 사유를 붙여 `range_review.reason_code`로
노출하지 않는다. 목차 사유는 최종 결과가 fallback이거나 사람 검토일 때만 본문 사유
(`range_too_small`·`scope_heading_missing` 등) **뒤에** `range_fallback_head` 앞자리로 남는다.

의미 검토 응답에 기대 주장 ID가 모두 정확히 한 번씩 있으면 그 밖의 항목은 무시하고 경고
`semantic_extra_ids`를 남긴다. 누락은 `failed/semantic_missing_ids`, 중복은
`failed/semantic_duplicate_ids`, schema·상한 위반은 `failed/semantic_schema_invalid`다
([ADR-0057](../tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md) 결정 3).

선택 범위에 예산·기간이 없어 결과의 절이 비면 run의 `warnings`에 `section_empty:<section>`을
남긴다. 빈 절은 사실이며 채우지 않는다.

#### 부분 완료 (2026-09-11, 2026-09-16 갱신)

주장별 차단 코드는 **그 주장만** 결과에서 뺀다. 통과 주장이 1개 이상이고 전체 주장의
`ceil(n/2)` 이상이면 남은 주장으로 의미 검토·구성을 계속해 `completed`가 되고, 미만이면
`needs_human_review/deterministic_check_failed`로 닫는다. `duplicate_id`처럼 초안 전체에
붙는 코드는 그대로 전체를 닫는다. 주장의 인용이 둘이고 하나만 `quote_not_found`·
`quote_ambiguous`이면 **그 인용만** 빼고 주장은 통과하며 경고 `evidence_dropped`가 남는다.
인용이 모두 어긋나면 종전대로 그 주장이 빠진다. 의미 검토에서 주장이 `contradicted`·
`insufficient`면 `needs_human_review/semantic_review_failed`로 닫는다.

이때 run의 `warnings`에 남는 코드는 `claims_dropped`(주장이 하나 이상 빠짐)·
`evidence_dropped`·`semantic_extra_ids`·`section_empty:<section>`이다.
`draft_json`·`checks_json`은 빠진 주장까지 담은 **전체**를 그대로 저장하며(`failed_claims`
투영이 `checks_json`에서 계산된다), 의미 검토·구성에 쓰는 부분집합은 저장하지 않는다.
`result_json`에는 빠진 주장과 빠진 인용이 들어가지 않는다.

개요 입력 PDF의 원본 위치가 여러 공고에 공유되면(같은 첨부 bytes) `source` 위치가 둘 이상이다.
원본의 정체는 hash이므로 가장 오래된 검증 위치 하나를 고정해 고른다.

### DB: `prespec_overview_run` (migration 0026, 0031 확장)

`id, notice_id, document_version_id, snapshot_id?, work_job_id, status, range_source,
page_start?, page_end?, range_reason_codes, input_sha256?, policy_digest, model_name,
model_revision?, draft_json?, checks_json?, result_json?, warnings_json, reason_codes,
call_count, raw_response_refs, actor_name?, created_at, started_at, completed_at`.
0031은 `contract_version, prompt_version?, validator_version?, profile_version_id?, reused_from_run_id?, profile_digest?,
profile_status, profile_facts_json, generation_config_json?, generation_config_digest?,
input_binding_sha256?, assessment_json?, assessment_checks_json?, assessment_grade?, assessment_status,
semantic_status, semantic_scope_json`을 추가한다. 기존 행은 `contract_version=overview-v1`,
`profile_status=not_configured`, `assessment_status=none`, `semantic_status=not_run`, 빈 scope/facts로
보존한다. `profile_version_id`는 `profile_version(id)`를 `RESTRICT`로 참조하고 hash는 lowercase
hex64, status·grade 조합은 CHECK로 강제한다. downgrade는 결과 이력 보존을 위해 백업 복구만 허용한다.
`raw_response_refs`의 각 항목은 `{stage, sha256, prompt_tokens, output_tokens, latency_ms}`이며 세 계측값은 provider가 낸 사실이고 실패 호출에서는 `null`이다.
인덱스 `ix_prespec_overview_run_notice_created(notice_id, created_at desc)`, 부분 유니크
`uq_prespec_overview_run_active(notice_id) where status in ('queued','running')`. app role은
SELECT/INSERT/UPDATE, worker role은 SELECT/INSERT/UPDATE만 갖는다.

`prespec_company_fit_attempt`의 `page_overview_id`/`overview_result_id`는
`overview_run_id uuid null FK prespec_overview_run(id)`로 바뀐다.

### 삭제되는 계약

`bidops.prespec-overview-reviews.v1/v2`, `bidops.prespec-overview-pages.v1/v2`,
`bidops.prespec-overview-page-review.v3/v4`(v4는 2026-09-16
[ADR-0057](../tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md)로 폐기,
결과 계약은 `bidops.prespec-overview-claims.v2`), `bidops.prespec-overview-claims.v1`(초안
단계 내부용으로만 유지, 문서 계약 아님), `bidops.prespec-overview-claim-checks.v1`,
`bidops.prespec-overview-policy.v1/v4/v5`, `bidops.prespec-v4-activation.v1/v2`,
`bidops.prespec-overview-range-view.v2`, v4 cohort ops CLI, Luna 명시 참조 실행. 함께 drop되는
테이블은 `prespec_overview_verification`, `prespec_overview_call_event`,
`prespec_v4_attempt`, `prespec_v4_target`, `prespec_page_overview`,
`prespec_overview_attempt_event`, `prespec_overview_result`, `prespec_overview_attempt`,
`prespec_overview_snapshot`, `prespec_overview_review`이고 함수
`tf_prespec_v4_attempt_guard()`도 drop한다. `bidops.section-candidates.v1/v2`와 snapshot
계약(`prespec_v4_pdf_snapshot`)은 유지한다. 적용 전 pg_dump 백업 절차는
`docs/operations.md`의 "0026 적용 전 개요 테이블 백업" 절을 따른다.

bundle confirm은 악성코드 clean 결과, document version, structure snapshot과 hash를 고정한다. 심층 attempt와 report materializer는 live 첨부를 다시 읽지 않고 이 snapshot만 사용한다. validation 실패는 report에서 드러나며 자동 통과로 바뀌지 않는다.

Lean wire model의 정확한 shape는 다음과 같다. 별도 `optional` 표기가 없으므로 모든 field는 wire에 필수이며 `?` field만 필수 nullable이다. UUID·date·datetime은 JSON 문자열이고 `source_sha256`는 64자 lowercase SHA-256이다.

- `DocumentVersionView`: `id`, `bundle_id`, `version>=1`, `role`, `effective_date?`, `replaces_document_version_id?`, `is_current`, `safety_status`, `structure_status`, `original_filename`. `role=공고|정정|제안요청서|과업지시서|내역서|제출서식|부록|기타`, `safety_status=quarantined|scanning|safe|blocked`, `structure_status=pending|processing|ready|failed|needs_review`다.
- `BundleIssue`: `issue_id`, `code`, `severity=차단|중대|보통|낮음`, `blocking`, `document_version_id?`, `message`, `locator_type=none|page|paragraph|table_cell|bbox`, nullable opaque object `locator?`다. `BundleView`: `id`, `notice_id`, `revision>=1`, `version>=1`, `status=draft|processing|needs_review|ready|quarantined|failed|superseded`, `documents: DocumentVersionView[]`, `issues: BundleIssue[]`, `confirmed_by?`, `confirmed_at?`, `created_at`. `BundleListResponse`는 pagination field 없는 정확히 `{items: BundleView[]}`다. 새 issue code `unsupported_attachment_excluded`(severity 보통, `blocking=false`)는 허용 형식 밖 첨부가 묶음에서 제외됐음을 알린다. 그 첨부의 `extract_status`는 `provider_unsupported_excluded`이며, 이름이 `provider_`로 시작하지만 **비차단**이다 — issue 계산이 다른 `provider_*` 규칙보다 먼저 이 값을 검사한다. issue code `source_name_differs`(severity 보통, `blocking=false`)는 첨부 목록의 이름과 document snapshot의 파일명이 다름을 알린다. 원본의 정체는 해시·크기이고 목록 이름은 자리표시자일 수 있으므로 차단하지 않으며, message에 두 이름을 담지 않는다. 원문 크기·provider source snapshot 불일치는 그대로 차단 `source_changed`, source location hash 불일치는 차단 `source_hash_mismatch`다.
- `PatchDocumentVersionRequest`는 `role`, nullable `effective_date`, nullable `replaces_document_version_id`, `is_current`, `version>=1`이 모두 필수다. `ConfirmRequest`는 `request_id`, `version>=1`, `confirmed_documents[]`; 각 확인 항목은 `document_version_id`, `version>=1`이다.
- `DocumentStructure`: `schema=bidops.document-structure.v1`, `structure_id`, `document_version_id`, `source_sha256`, `media_type`, `extractor`, `pages[]`, `blocks[]`, `warnings[]`, `created_at`. extractor는 `name`, `version`, nullable `upstream_commit`; page metadata는 `number>=1`, `width>0`, `height>0`, nullable `image_content_object_id`; block은 `block_key`, nullable `parent_block_key`, `type`, `page>=1`, nullable numeric `bbox[]`, `text`, nullable `confidence`(0..1), opaque object `attributes`다. `DocumentStructurePageView`는 `structure_id`, `page>=1`, `metadata`, `blocks[]`다.
- `DocumentSegmentsView`(`bidops.document-segments.v1`): `schema`, `structure_id`, `document_version_id`, `source_sha256`, `taxonomy_version`, `extractor_binding`, `extractor_binding_sha256`, `payload_sha256`, `segments[]`, `inventory_summary`, `coverage`, `warnings[]`, `created_at`다. 현재 `taxonomy_version`은 `bidops.segment-taxonomy.v2`이며 `extractor_binding`은 `name`(`bidops-document-segments`), `version`, `taxonomy_version`, `rules_sha256`, `schema`를 갖는다. 각 segment는 `segment_id`, `ordinal>=1`, `taxonomy_labels[]`(`business_eligibility_evaluation|technical_functional|quality_security_constraints|partnership_governance|operations_maintenance`), `start_locator`, `end_locator`, `requirement_ids[]`, `source_block_keys[]`, `classification_source`(항상 `deterministic`), `confidence`(항상 `null`), `status=classified|needs_human_review`, `page_range`, `mapping_status`를 갖는다. locator는 `kind=paragraph|table_cell|block`, `block_key`, `page>=1`, `ordinal>=0`, nullable `table_key`·`row`·`column`이다. `inventory_summary`는 `expected_ids[]`, `duplicate_ids[]`, `ambiguous_items[]`, `prefixes[]`, `item_count`, 필수 정수 `card_item_count`·`label_value_table_count`, `coverage`를 갖는다. `coverage`는 `block_count`, `covered_block_count`, `segment_count`, `gap_count`, `overlap_count`, `gaps[]`, `overlaps[]`, `needs_human_review_count`, `toc`를 갖는다. **응답에는 원문 text와 segment 제목이 없다** — 화면은 ordinal·label·요구사항 ID·block key·page 링크만 보이고 제목이 없는 이유를 직접 밝힌다.
- `page_range`는 `{first,last}`(둘 다 1 이상, 물리 PDF 순번) 또는 `null`이고 `mapping_status`는 `mapped|partial|inherited|unavailable`이다. 둘은 **문단↔쪽 대응표(`bidops.para-page-map.v1`)에서 조회 시점에 계산하는 wire 전용 값**이며 manifest·segment 행에 저장하지 않고 `payload_sha256`의 hash 대상에도 넣지 않는다. segment의 `source_block_keys` 중 직접 매핑된 키가 있으면 우선한다. 전부 매핑되면 `mapped`, 일부만이면 `partial`이고 범위는 매핑된 키의 `min(page_first)`~`max(page_last)`다. 직접 매핑이 없으면 build 시점에 저장한 가까운 비어 있지 않은 앞 문단 최대 3개 중 첫 매핑 문단의 `page_first`를 한 쪽짜리 `inherited` 범위로 쓴다. 대응표나 매핑된 anchor가 없으면 `unavailable`·`page_range=null`로 남겨 쪽을 추정하지 않는다. 대응표를 가진 snapshot의 객체를 읽지 못하거나 저장 SHA-256·schema 검증에 실패하면 500 `processing_failed`로 닫는다.
- `requirement_inventory_item`은 기존 열 제목 경로와 새 라벨·값 경로를 함께 보존한다. 기존 행은 `source=column_header_table`, `card=null`이고, 카드 행은 `source=label_value_table`과 원래 category·title·definition·details·선택 필드·table identity·경고·build 시점 `page_anchor_block_keys`를 가진다. 추가 열은 `source TEXT NOT NULL DEFAULT 'column_header_table'`, nullable `card JSONB`, `document_segment.page_anchor_block_keys JSONB NULL`이다. DB 전용 카드 값은 `DocumentSegmentsView`에 원문을 추가하지 않는다.
- analysis-worker CLI `python -m app.deep_review.cli rebuild-segment-manifests (--structure-id <uuid> | --all) [--dry-run]`은 구조마다 `{structure_id, created, manifest_id, errors[]}` JSON 한 줄을 출력한다. DB와 객체 저장소에 접근할 수 있는 analysis-worker 역할에서 실행하고 `--all`은 `ready` 구조만 처리하며 기존 manifest 행은 보존한다. 종료 코드는 성공 0, 입력 오류 2, 처리 오류 1이다.
- 로컬 증거 명령 `PYTHONPATH=web/backend python3 scripts/hp-card-inventory-check.py`는 반복 `--structure <json> --page-map <json>` 입력 또는 짝이 맞는 `<name>.structure.json`·`<name>.para_page_map.json` 파일을 둔 `--dir <directory>`를 받는다. 제품의 manifest builder와 page resolver를 호출하고 DB·네트워크·객체 저장소 접근 없이 문서별 `{name, card_count, inherited_page_count, mapped_page_count, unavailable_count, prefixes, categories, duplicate_ids, warnings}` JSON 배열을 stdout에 출력한다. `--out <path>`는 새 파일을 만들고 기존 경로를 덮어쓰지 않는다. 입력·처리 오류에 원문 text를 포함하지 않는다.
- `DeepReviewCreateRequest`는 `request_id`, `bundle_id`; `DeepReviewAttemptRequest`는 `request_id`다. `StageView`는 `stage=requirements_and_evaluation|delivery_risk_economics|synthesis_and_validation`, `sequence>=1`, `status=queued|running|completed|failed`, `started_at?`, `completed_at?`, `last_error_code?`. `AttemptView`는 `id`, `sequence>=1`, `status=queued|running|completed|failed|superseded`, `stages: StageView[]`, `started_at?`, `completed_at?`, `last_error_code?`. `DeepReviewView`는 `id`, `notice_id`, `bundle_id`, `status=queued|running|completed|failed`, `current_attempt?`, `attempts: AttemptView[]`, `created_at`, `completed_at?`, nullable `quality_status=measured|unmeasured_reference|mock_reference`다. `quality_status`가 `null`이면 **표식 없음**이며, 표식이 없던 시절의 실행을 미측정이나 측정으로 승격시키지 않는다.
- `ReportRow`: nonblank `row_key`, nonblank `label`, `cells[]`, `claim_ids[]`. `ReportBlock`: nonblank `block_id`, `type=paragraph|matrix|decision_card|scenario|action_list`, nullable `title`, nullable `body`, `claim_ids[]`, `rows: ReportRow[]`. `ReportSection`: `section_key`, nonblank `title`, `blocks: ReportBlock[]`. section key는 `project_overview|eligibility_matrix|scope_deliverables|requirements_matrix|evaluation_strategy|delivery_plan|technical_integration_risks|security_legal_contract_risks|economics_scenarios|competitive_proposal_strategy|questions_internal_actions|document_bundle_limitations|decision_card`다.
- `ReportClaim`: `claim_id`, nonblank `category`, `claim_type=fact|calculation|inference|opinion|unknown`, nonblank `body`, `status=supported|unsupported|conflicting|unknown`, nullable `formula`, `premise_claim_ids[]`, nullable `reason`, `evidence_ids[]`. `ValidationSummary`: `status=passed|failed`, nonnegative `failed`, `warnings`, `passed`다.
- `DeepReviewReport`: `schema=bidops.deep-review-report.v1`, `deep_review_id`, `notice_id`, `bundle_id`, `profile_version_id`, `policy_version_id`, `sections: ReportSection[]`, `system_recommendation=추진 검토|조건부 추진 검토|보류|검토 종료`, `claims: ReportClaim[]`, `unknowns[]`, `validation_summary`, `created_at`, optional nullable `quality_status=measured|unmeasured_reference|mock_reference`. `quality_status`는 `contracts/bidops.deep-review-report.v1.json`에 **required가 아닌** optional nullable enum으로 추가됐으므로 이전에 저장된 revision은 이 key가 없거나 `null`이며 그것이 "표식 없음"이다. 사람 수정본은 이 값을 편집할 수 없고 서버가 생성 계보에서 다시 계산한다.
- `ValidationCheck`: nonblank `check_type`, `status=passed|failed|warning`, `severity=차단|중대|보통|낮음`, nonblank `message`, `related_claim_ids[]`, `related_evidence_ids[]`. `check_type`에는 결정적 check 두 종이 추가됐다([ADR-0051](../tracking/decisions/0051-deep-review-v2-deterministic-subset.md)). `requirement_inventory`는 누락·예상 밖 요구사항 ID를 `failed`·중대, 중복을 warning, ID 체계 없는 문서를 warning "inventory 없음"으로 남기고, `segment_coverage`는 간극·중첩을 warning·보통으로 남기며 차단하지 않는다. `DeepReviewValidation`: `schema=bidops.deep-review-validation.v1`, `validation_run_id`, `report_revision_id`, `status=passed|failed`, `checks: ValidationCheck[]`, `created_at`. `RevisionHistoryItem`: `revision_id`, `sequence>=1`, `origin=machine|human`, nullable `validation_status=passed|failed`, nullable `created_by_name`, `created_at`.
- `FinalOpinionView`: `id`, `sequence>=1`, `value=추진|조건부 추진|보류|검토 종료`, `reason`, `validation_status_at_opinion=passed|failed`, `acknowledged_validation_failure`, `claimed_name`, `created_at`. `ReportView`: `deep_review_id`, `current_revision_id`, `report: DeepReviewReport`, `validation: DeepReviewValidation`, `history: RevisionHistoryItem[]`, nullable `final_opinion: FinalOpinionView`다.
- `ReportRevisionRequest`: `request_id`, `base_revision_id`, `report: DeepReviewReport`, nonblank `reason`, `factual_change_evidence_ids[]`. `FinalOpinionRequest`: `request_id`, `report_revision_id`, `validation_run_id`, `value=추진|조건부 추진|보류|검토 종료`, `reason`, `acknowledged_validation_failure`; schema는 빈 문자열을 구조적으로 거부하지 않지만 service는 blank reason을 400 `final_opinion_reason_required`로 거부한다.
- `EvidenceView`: `evidence_id`, `source_kind=document|profile`, nullable `document_version_id`, nullable `structure_id`, nullable `profile_version_id`, nullable `profile_evidence_id`, `locator_type=page|paragraph|table_cell|bbox|profile_fact`, opaque object `locator`, `quote`, nullable `confidence`(0..1), `source_sha256`, nullable `page: DocumentStructurePageView`다.

Lean 안정 오류 code의 전체 vocabulary는 `invalid_request`, `actor_name_required`, `actor_name_invalid`, `not_found`, `effective_grade_ineligible`, `bundle_not_ready`, `bundle_has_blocking_issues`, `unsafe_document`, `structure_unavailable`, `version_conflict`, `idempotency_conflict`, `active_attempt_exists`, `service_unavailable`, `review_not_ready`, `evidence_out_of_scope`, `factual_change_evidence_required`, `validation_failed`, `final_opinion_reason_required`, `processing_failed`다. 소비자는 table에 적힌 endpoint별 status/code 조합만 정상 계약으로 처리하고, 알려지지 않은 조합은 안전하게 실패시킨다.
