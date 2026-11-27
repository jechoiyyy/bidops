# 문서 준비·심층 검토와 참조 정책

[전체 계약](../contracts.md). 기준일: 2026-10-21. 공통 REST·상태 규칙은 상위 문서를 함께 적용한다. 계약의 존재는 운영 활성화·품질 인수를 뜻하지 않는다.

## 심층 검토 내부 artifact

| schema | 용도 |
|---|---|
| `bidops.agent-command.v1` | API가 worker에 전달하는 fenced command |
| `bidops.agent-run.v1` | worker 실행, 입력·출력 hash, 상태와 lineage |
| `bidops.document-converter-request.v1` | network 없는 변환 worker 요청 |
| `bidops.document-converter-result.v1` | 변환 결과와 안전한 오류 |
| `bidops.document-converter-request.v2` | `prepare_pdf=true` 문서 변환 요청과 원문 hash/scan 결속 |
| `bidops.document-converter-result.v2` | 구조 JSON과 request UUID 결속 PDF sidecar metadata |
| `bidops.document-structure.v1` | page/block/table 구조와 원문 locator |
| `bidops.para-page-map.v1` | native rhwp 구조 블록과 물리 PDF 페이지 대응 (생성·검증·버전 고정 저장) |
| `bidops.document-bundle.v1` | 확정된 document versions와 structure snapshot |
| `bidops.deep-review-stage.v1` | 세 단계의 claims, evidence, unknowns, warnings |
| `bidops.deep-review-report.v1` | 검증된 claim을 이용한 보고서 |
| `bidops.deep-review-validation.v1` | 근거·수치·계약 검증 결과 |
| `bidops.analysis-policy.v1` | 모델, chunk, retry, generation, validation 정책 |
| `bidops.company-profile.v1` | 승인된 회사 profile snapshot |

모델 response 원문은 암호화된 객체로 저장하고 DB에는 namespace, version, hash, key reference만 둔다. RL-04 제안서 초안 PDF는 namespace `proposal-pdf`(버킷 `bidops-proposal-pdf`, 자격증명 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`)에 암호화 없이 저장하고 `content_object.sha256`이 저장 바이트 hash이며 `retention_class=proposal-pdf-365d`(365일 만료)다. 백업·복구·active hash 검증 대상이다(결정 B48). evidence locator는 document version, structure ID, page·block 또는 표 좌표를 포함하며 report의 사실·숫자와 연결된다.

`bidops.para-page-map.v1`은 `page_count`, `paragraph_count`, `paragraphs[]`,
`blocks[]`, `unmapped_block_keys[]`, `mapping`을 갖는다. 문단 identity는
`(section, para_index)`이고 `page_first`·`page_last`는 1 기준 물리 PDF 순번이다.
구조 블록의 `match=exact`는 검증된 source HWPX 문단 identity에만 사용한다.
HWP 변환본·표 셀의 `match=page_text`는 전체 텍스트의 유일 발생만 허용하고
`para_index=null`이며, 확인하지 못한 source section도 `null`로 둔다.
빈 블록·미확인 연결은 `unmapped_block_keys`에 보존하며 매핑률 0도 유효하다.
`mapping`의 세 블록 집계는 mapped·unmapped의 중복 없는 전체 분할과 같아야 하고
`rule=para-page-align.v1`로 고정한다. [상세 계약과 정렬 규칙](../0910_rhwp-document-pipeline/Spec.md)을 따른다.
대응표와 canonical JSON 바이트는 native `ProcessedDocument`의 별도 속성이다.
기존 구조 JSON·REST는 유지하고 scratch v2의 `native_sidecars` descriptor와
`prespec_v4_pdf_snapshot`의 객체 참조로 저장 경계를 연결한다.

문서 변환 scratch 계약은 v1 구조 결과와 v2 PDF preparation 결과를 구분한다. v1은
기존 `request.v1`/`result.v1` envelope와 structure JSON만 사용한다. 요청 options의
`prepare_pdf=true`는 `bidops.document-converter-request.v2`를 선택하고, 성공 결과는
`bidops.document-converter-result.v2`의 `pdf_sidecar`를 반드시 포함한다. sidecar는
JSON/base64로 넣지 않고 request UUID에서 도출한 단일
`pdf/<request_uuid>.pdf` 파일로 원자적으로 publish한다. 결과 JSON은
`file`, `byte_count`, `sha256`, 기존 `pdf_metadata`, `source_kind`를 결속하며,
worker는 PDF sidecar를 먼저 완료한 뒤 결과 JSON을 마지막에 publish한다.

consumer는 고정 namespace와 UUID filename을 다시 계산하고 stat·bounded read,
regular-file/no-symlink, byte count·SHA-256·`%PDF-` 검사를 통과한 sidecar만
`ProcessedDocument.converted_pdf_bytes`와 `.pdf_metadata`로 복원한다. 생성 PDF는
trusted-side ClamAV로 exact bytes를 재검사하며, 원본 PDF 입력은 `.original_bytes`를
그대로 보존하고 v2 sidecar의 `source_kind=original`로 구분한다. 이 경우 request의
선언 MIME가 아니라 검증된 structure의 `media_type=application/pdf`를 기준으로 하며,
sidecar bytes와 원문 hash가 exact match여야 한다. `pdf_metadata`는 빈 object를
허용하지 않고 `bidops.pdf-snapshot.v1`의 physical `page_count`와 페이지별
`number`, `width`, `height`, normalized text의 `text_sha256`를 structure와 함께
검증한다. 성공 소비 뒤 해당 request의 result/sidecar만 삭제하며, timeout 중 claimed
input과 다른 request 파일은 삭제하지 않는다. scratch는 임시 handoff이고 DB/MinIO
정본이나 영속 snapshot이 아니다.

native `renderer=rhwp-svg-pdf` 성공 결과는 `native_sidecars`에 `hwpx`, `page_text`,
`para_page_map`, `section_candidates`, `hwpx_verify`를 추가한다. 파일 descriptor는 `{file,byte_count,sha256}`이고
`native/<request_uuid>.hwpx`, `.page-text.json`, `.para-page-map.json`으로만 해소한다.
원본 HWPX는 `hwpx`·`hwpx_verify`가 `null`이고 원문을 재사용한다. HWP 변환본은
`hwpx_verify={identical:true,diff_count:0,pages:{before:N,after:N,identical:true}}`를
반드시 갖는다. 원문·PDF·변환 HWPX를 trusted-side scanner로 검사한다. native
page-text는 `bidops.rhwp-page-text.v1`의 `page_count`, 물리 페이지의
`number,display_page,section,text,text_sha256`를 보존한다. 모든 sidecar를 완료한 뒤
성공 JSON을 publish하며 소비자는 고정 경로·regular file·상한·hash·페이지 수와
schema를 검사한다. 구조 블록을 합쳐 PDF page text를 대신하지 않는다.

후보는 현재 `bidops.section-candidates.v2`로 생성하고 기존 v1도 읽는다.
후보 산출 실패가 구조의 `section_candidates_unavailable` 경고에 명시되어 있고 핵심
산출물의 독립 검증이 통과한 경우에만 `native_sidecars.section_candidates=null`을
허용한다. descriptor 키 자체의 누락이나 경고 없는 null은 거부한다. 실제 후보 파일의
JSON `null`도 유효 후보가 아니며 거부한다. 후보가 있으면
고정 경로·byte 수·hash·canonical JSON·후보 결속 검사를 그대로 적용한다. 저장된
snapshot의 후보 참조 세 열은 이 경우 함께 null이며 원본·PDF·페이지 텍스트·대응표의
필수 참조와 검사는 생략하지 않는다. 후보 미제공은 변환 또는 내용 검토 성공을 뜻하지 않는다.

## v4 PDF 준비 snapshot (2026-09-08, 2026-09-11 갱신)

PDF 준비는 기존 `DocumentStructure`·legacy 개요를 갱신하지 않는다.
`0021_prespec_v4_pdf_contract`가 추가한 `prespec_v4_pdf_snapshot`은 유지하는 입력
스냅숏이다. `0022`가 추가했던 `prespec_v4_target`·`prespec_v4_attempt`는 migration
0026에서 삭제하고, 개요 run(`prespec_overview_run`)이 이 snapshot을 가리킨다.

- `prespec_v4_pdf_snapshot`은 current·safe `DocumentVersion`의 정확한 원문
  `ContentObjectLocation`, PDF `ContentObjectLocation`, full page-text JSON
  `ContentObjectLocation`, PDF metadata, page count·page text hash, ClamAV clean
  verdict, worker renderer/font digest와 정규화된 processor options를 묶는다.
  Canvas 이력 행과 새 native/원본 PDF의 full page text object는
  `bidops.prespec-v4-page-text.v1` JSON의 모든 물리 페이지
  `{number,text,text_sha256}`를 보존하며 PDF metadata의 페이지별 hash와 일치해야
  한다. 생성 PDF는 기존 `source` namespace에 저장하고 page-text·선택 manifest는
  `structure` namespace에 둔다. 원본 PDF는 동일 source object/location과 bytes를
  그대로 재사용한다.
- 준비 API는 source hash, renderer/font/config digest로 기존 snapshot을 변환 전에
  조회한다. 같은 source version·worker provenance·options이면 worker를 다시
  호출하지 않고 같은 PDF/page-text object version을 반환한다. cache hit도 source,
  PDF, page-text object를 저장된 namespace·object key·version·etag·size·SHA-256으로
  bounded read하고 최신 `ContentScan.status=clean`을 확인한다. Canvas renderer로
  만든 이력 행은 읽기만 하며, 새 snapshot은 native 지문(`rhwp_version`·
  `rhwp_binary_sha256`)과 실제 설치 파일 바이트를 정렬해 만든 font manifest
  (`font_manifest_sha256`)만 결속한다. 배포가 선언한 `worker_image_digest`가 있을 때만 선택적으로 함께 결속하며, 선언이 없을
  때 asset fingerprint를 이미지 digest로 가장하지 않고 `null`로 둔다. generated
  PDF에서는 이 값이 caller dict가 아니라 실제 document-worker가 PDF metadata에
  넣은 native renderer·font fingerprint와 일치해야 한다. 원본 PDF는
  `rerendered=false`와 실제 bounded Poppler/stdlib text-extractor provenance를 기록하고 `font_provenance=null`로 둔다. config의 `options`는
  `ProcessorOptions.from_mapping`의 확정 기본값을 포함한 정규화 mapping이어야 한다.
- native snapshot은 `hwpx_content_object_id`·`hwpx_location_id`·`hwpx_verify_jsonb`
  (HWP만), `structure_id`·`structure_location_id`, `para_page_map_content_object_id`·
  `para_page_map_location_id`·`para_page_map_sha256`, `rhwp_binary_sha256`·`rhwp_version`을
  추가로 결속한다. 모두 nullable로 추가하며 과거 행을 backfill하지 않는다. 변환
  HWPX는 `source`, 구조·native page-text·대응표는 `structure` namespace다. renderer
  값은 `pdf_metadata_jsonb.renderer`와 `renderer_jsonb`에 있고 별도 열은 없다.
  native renderer digest는 renderer JSON 전체의 canonical SHA-256이고 font/config
  digest와 함께 캐시 identity를 구성한다. 저장·재사용 때 모든 객체의 정확한
  version·etag·size·hash를 확인하고 HWPX 검증 결과와 page-text/map 계약을 재검증한다.
  같은 문서 버전의 기존 구조는 원본·MIME·pages·blocks가 모두 같은 경우에만 재사용하며
  다르면 `structure_binding_mismatch`로 거부한다. 기존 구조와 리뷰는 덮어쓰지 않는다.
converter의 허용된 안전 오류는 `pdf_preparation_failed:<code>`와
`AuditEvent.safe_metadata.converter_code`에 남기며 미등록 예외는 일반 코드로 닫고
원문·경로·stderr는 넣지 않는다. 개요 run이 이 snapshot을 가리킨다 — run은 자기 범위
선택(`range_source`·`page_start`·`page_end`)만 따로 갖고 snapshot 자체는 재사용한다.

## 사전규격 회사 핏 계약 (`bidops.prespec-company-fit.v2`)

`GET /api/pre-specs/{notice_id}/company-fit`은 해당 공고의 attempt 목록, 자동 판정 활성 여부, 카드 모드 상태, 엔진 분석 추천, 서버가 계산한 자동 준비 사유와 실제 최신 `deep_review_id`를 반환한다. 공고 없음/다른 source type은 404, 잘못된 id는 422, 내부 오류는 안전한 `processing_failed` 503이다. GET은 실행을 만들거나 모델을 호출하지 않는다.

- 최상위: `schema_version`, `notice_id`, `attempts[]`, `automation_enabled`(v1 정의 그대로 `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED and BIDOPS_REFERENCE_WORKFLOW_MODE`), `mode`, `engine_suggested`, `auto_deep_review_reason`, `deep_review_id`.
- `attempts`는 그 공고의 가장 최근 행(`created_at desc, id desc`, 회사 lineage 제외)과 **같은 lineage**의 행만 최신순으로 최대 20개다. 행이 없으면 빈 목록이다.
- 각 attempt는 `lineage=profile|card`, `card_version`·`card_sha256`·`judged_by=model|claude_reference`·`company_fact_labels`(`{ref: 표시 이름}`, 카드 lineage만; 프로필 lineage는 모두 null)와 nullable `profile_version_id`·`profile_sha256`(카드 lineage는 null)를 갖는다. 나머지 필드와 재검증 규칙은 v1과 같다.
- `mode`는 카드 모드 실효 상태 `{mode=off|suggest, effective, reason_code, card_version, card_sha256, prompt_version}`이다. 사유는 `company_fit_disabled` → `company_fit_reference_only` → `company_fit_model_unavailable`(overview binding 실패 또는 revision이 64자 소문자 hex가 아님) → `card_unavailable` → `card_sha256_mismatch` → `switch_off` 순서의 첫 미충족이다. MVP에서 모드는 env `BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE=off|suggest`(기본 `off`)이며 모드 테이블·REST·CLI는 없다. 카드 정보는 앞 조건과 상관없이 카드를 읽어 채운다.
- `engine_suggested`는 `attempts[0]`이 카드 lineage이고 `completed`·재검증 통과·현재·`matched`이며 env 카드 모드가 `suggest`일 때만 true다. 실행기 실효(`mode.effective`)는 요구하지 않는다. 추천은 표시뿐이며 추적·분석 요청을 만들지 않는다.
- 실행 상태: `queued|running|completed|failed|needs_human_review`. 결과가 없거나 검증에 실패한 실행의 `result`는 null이다.
- 결과: `bidops.prespec-company-fit-result.v1`, `decision=matched|mismatch|unknown`, `summary`, `reasons[]`, `verification_items[]`. 각 사유는 `kind=scope_match|scope_mismatch|information_gap`, 모델 의견 `explanation`, `notice_refs[]`, `company_refs[]`를 갖는다. 입력에 없는 ref, 중복 ref, 확인되지 않은 회사 근거로 만든 일치/불일치, 인용 근거에 없는 숫자는 검증 실패다. 자동 보정하지 않는다.
- `notice_facts`는 해당 개요의 문장과 PDF 페이지 또는 HWPX 구조 블록 위치, 공고 제목이다. `company_facts`는 프로필 lineage면 승인 프로필의 fact key/status/value, 카드 lineage면 사업 범위 카드 투영(scope·policy의 ref/이름·kind/`confirmed`/선택 필드)만 반환한다. 회사 원문·quote·filesystem source·카드 경로·객체 경로는 응답하지 않는다.
- `overview_run_id`, `document_version_id`, 개요 run status, profile id/digest 또는 카드 version/sha, policy digest, model name/revision, prompt version, 품질 표식, 생성/완료 시각과 입력/출력 토큰·소요시간을 보존한다. 사용량 부재는 null, 실제 0은 0이다.
- `is_current=false`이면 과거 입력 기준이다. 프로필 lineage는 프로필·활성 심층 정책·개요·문서·핏 정책/모델 변경, 입력 hash 불일치가 현재성을 막는다. 카드 lineage는 현재 개요 id·sha, 현재 카드 sha, `prompt_version=prespec-company-fit-v3.1`, 입력의 모델 이름으로 다시 계산한 policy digest, 입력 hash만 본다(모델 binding은 실행기가 claim·호출 때 따로 확인한다). 카드를 읽을 수 없으면 모든 카드 행이 현재가 아니다. 회사 핏 결과와 실제 심층 검토 생성 여부를 서로 추정하지 않는다.
- 자동 사유는 `company_fit_disabled|pending|queued|running|stale|mismatch|unknown|failed|needs_human_review|validation_failed|reference_only|suggest_only`에서 접두사 `company_fit_`을 각각 붙인 코드다. `company_fit_suggest_only`는 카드 모드가 실효인 동안 등급과 상관없이 모든 공고에 나오며 회사 핏을 통한 심층 자동 시작을 막는다. 기존 자동 준비 사유도 그대로 반환한다.

`prespec_company_fit_attempt`는 입력 JSON과 SHA-256, 개요/문서 FK를 동결하며 lineage가 셋이다(`ck_prespec_company_fit_policy_scope`, 0044).

- 프로필 lineage(`company_id IS NULL AND card_sha256 IS NULL`): `bidops.prespec-company-fit-input.v1`(정책 전문 포함), 프로필·심층 정책 FK.
- 카드 lineage(`company_id IS NULL AND card_sha256 IS NOT NULL`, PS-01): `bidops.prespec-company-fit-input.v2`, 열 `card_version`·`card_sha256`(64자 소문자 hex), 프로필·정책·graph 없음. 입력은 개요 사실·카드 투영·표시 이름·`policy_digest`·모델 이름/revision·`prompt_version=prespec-company-fit-v3.1`·품질 표식·`judged_by`·`fit_policy`(v1에서 프롬프트 버전과 instruction만 카드 v3.1로 바꾼 것)이다. 모델에는 그중 `schema_version, notice_id, notice_facts, input_limitations, company_facts, model_name, prompt_version` 일곱 키만 보낸다. insert guard는 입력의 schema·notice·문서·개요·카드 version/sha·모델·품질·policy digest가 같은 열과 같고 `prompt_version`이 상수이며 `judged_by`가 `model|claude_reference`인지 본다. 대상은 카드 모드 실효 중 개요가 결정적 검사를 통과한 SW사업대상 전체(C-1 등급 무관)이며 마감 전·미확인이거나 추적 중인 건이다. 카드 행은 심층 자동 시작에 쓰지 않는다. 카드 모드 실효 중에는 프로필 lineage의 자동 enqueue와 claim을 멈춘다.
- 회사 lineage(`company_id IS NOT NULL`, DEMO-03): 회사 핏 정책·graph·provenance.

입력 digest는 유일하다. 실행 상태·lease·결과·사용량만 전이할 수 있고 종결 후 UPDATE/DELETE는 DB/ORM에서 거부한다. 원응답은 기존 암호화 model-response 저장소에 저장한다. 종결 이력(0026)이나 카드 lineage 행(0044)이 있으면 migration downgrade를 거부한다. 앱 역할은 SELECT, 합성 worker만 INSERT 및 제한된 상태 열 UPDATE를 받는다(카드 열은 그 목록에 없다).

가져오기 도구 `python -m app.deep_review.cli import-company-fit-judgments --file <json> --actor <name> [--dry-run]`(worker 역할, MVP)은 `{"judged_by":"claude_reference","card_sha256":…,"rows":[{"notice_id","result"}]}` 묶음을 현재 DB 기준 카드 동결 입력(`model_name=claude-reference-judgment`, `model_revision`=묶음 파일 sha256, `judged_by=claude_reference`)으로 만들고, `validate_result`를 통과한 결과만 같은 transaction에서 `queued → running → completed`로 넣는다. 개요 입력이 없거나 검증에 실패한 공고·이미 있는 입력은 건너뛴다. 카드를 쓸 수 없거나 묶음의 `card_sha256`이 현재 카드와 다르면 전체를 거부한다(exit 2). 모델은 부르지 않는다.

## 심층검토 설명형 보고서 v2 (2026-09-22, 선택형 PoC)

`analysis-policy-narrative-v2.json`으로 시작한 실행은 `bidops.deep-review-stage.v2`와
`bidops.deep-review-report.v2`를 사용한다. 기존 v1 정책·stage·report의 의미와 저장된
payload/hash는 변경하지 않는다. `ReportView.report`, `ReportRevisionRequest.report`,
의견 에이전트의 full revision은 `schema`로 구별하는 v1/v2 union이다. 응답 envelope는 유지한다.

- v2 claim은 기존 사실/계산/해석/의견/미확인 계약에 `report_section`, `narrative_role`,
  `topic_key`, `source_unit_ids`, `requirement_ids`, `related_claim_ids`, `is_key_point`를 추가한다.
  `requirement_ids`는 실제 문서 ID이며 `source_unit_ids`의 내부 분할 ID와 구별한다.
- stage는 `coverage[{source_unit_id,status:reviewed|needs_review,claim_ids,reason}]`와
  `considered_claim_ids`를 갖는다. 입력 조각의 원문·회사 근거·선행 주장 밖 참조를 거부한다.
  회사 대조 단계도 입력에 제공된 선행 주장 목록을 선택적으로 반환할 수 있다.
  전체 종합 단계에서는 모든 선행 주장 포함을 계속 요구한다. 회사 근거 ID를 주장 ID로
  대신 사용하는 것은 원문 대조 on/off와 무관하게 거부한다.
  읽을 수 없는 원문·길이 초과·전체 종합 불가를 결과 누락으로 감추지 않는다.
  v2 사실 문장의 숫자는 인용 근거의 숫자와 대조하고 계산은 식을 재연산한다.
  숫자 존재 대조만으로 단위·관계·문장 의미까지 검증되었다고 하지 않는다.
- v2 인용은 고정 원문 위치 안에서 공백·줄바꿈·따옴표 모양·전각 ASCII 차이를
  허용하고, 유일하게 대응하는 **원문의 실제 문자열**을 저장한다. 숫자/영문 토큰 사이의
  공백은 보존한다. page 위치는 같은 페이지의 원문 순서상 연속된 문단까지 허용하고, paragraph/cell 위치는 해당 블록에 한정한다. 중간 문단 생략·순서 변경·다른 페이지 결합은 거부한다. 의미·수치·단위·부정어 변경이나
  다른 문서/위치의 인용은 허용하지 않는다. 암호화된 모델 응답 원본은 그대로 보존한다.
- 원화 금액은 Decimal로 단위를 환산해 같은 값인지 검사한다(84백만원=84,000,000원).
  축약 연도와 대응하는 풀어 쓴 연도는 `year_notation` warning으로 보고서를 허용하되
  세기를 확정하지 않는다. 해당 claim/evidence 연결과 분석 한계를 저장하고 본문 문장
  옆에 확인 사항을 표시한다. 다른 연도·금액은 계속 실패한다.
- 한 원문 조각의 선행 분석이 회사 대조 입력 예산을 넘으면 여러 호출로 분할한다.
  전체 선행 claim ID를 누락 없이 전달하고 같은 원문 조각의 coverage를 합칠 때
  `needs_review`를 우선 보존한다. 전체 종합 입력 상한은 그대로 유지한다.
- 모델이 생성한 로컬 UUID는 호출별 attempt/stage/slice/phase namespace에 결속하고
  내부 참조를 함께 치환한다. 원문·회사 근거 ID와 선행 참조는 유지하며 중복 선언·범위
  밖 참조는 거부한다. 업무 내용이나 검증 실패를 자동 수정하는 경로가 아니다.
- report는 `assessment|scope|company_fit|delivery|evaluation|contract_economics|actions|decision_conditions`
  8개 절이다. 절의 `status=available|not_analyzed`, 문단 하나에 claim 하나를 보존한다.
  모든 claim은 정확히 한 번 본문에 나타나며 body/역할/핵심 표시는 원 claim과 일치해야 한다.
  분류할 결과가 없으면 다른 절의 claim으로 채우지 않는다.
- report의 `generator_version=narrative-v2`, `coverage`, `analysis_limitations`,
  `validation_summary`와 claim의 역할·연결 metadata는 서버 소유다. 후속 revision에서
  schema를 바꾸거나 이를 편집할 수 없다. 본문 수정은 claim과 연결 문단을 함께 바꾸고
  기존처럼 사유·범위 내 근거·base revision 검증을 거쳐 새 snapshot으로 저장한다.
- v2의 검증 요약 건수는 저장할 실제 check의 상태별 건수다. `unknowns`는 업무 미확인
  내용이며 경고 건수로 합산하지 않는다. 구조·근거 검증 통과는 의미 정확성·품질 측정 통과와 다르다.
- `GET /deep-reviews/{id}/report`는 현재 실행이 재시도 중/실패여도 가장 최근 저장된
  revision과 그 revision의 의견을 반환한다. 저장된 보고서가 없으면 409
  `review_not_ready`다. 실행 상태는 기존 `GET /deep-reviews/{id}`로 별도 조회한다.
  GET은 생성·보정하지 않으며 수정/의견 저장에는 기존 완료 실행 gate가 유지된다.

상세 설계·검증 범위는 [0922 명세](../0922_deep-review-improvement/spec.md)와
[구현 기록](../0922_deep-review-improvement/plan.md)을 따른다.

#### 실행별 원문 대조 선택

- `POST /notices/{id}/deep-reviews`와 `POST /deep-reviews/{id}/attempts`는
  `source_verification_enabled` boolean을 받는다. 기본값 true, 문자열/숫자 coercion은
  거부한다. 시작/재실행 Agent payload도 같은 선택을 받는다. 생략/true의 기존
  idempotency hash는 유지하고 false는 별도 hash이므로 같은 request ID로 바꿀 수 없다.
- 새 attempt의 선택은 `deep_review.source_verification_selected` 감사 행에
  `aggregate_type=deep_review_attempt`, `aggregate_id=attempt ID`,
  `safe_metadata={enabled,scope:source_quotes_and_numbers}`로 한 번 기록한다.
  기존 행이 없는 과거 attempt는 항상 대조를 사용했으므로 true다. worker는 실행 시작에
  해당 선택을 고정해 stage·합병·report 검증에 공통 적용한다. DB migration은 없다.
- false는 원문 인용 문자열 일치와 사실 숫자/계산 입력값의 근거 대조만 생략한다.
  원문 hash·문서/회사자료·페이지/블록 범위·읽기 권한·안전 검사·JSON 형식·참조 연결·
  계산식 재연산·전체 입력 누락 검사는 유지한다. 원본 응답과 인용 내용을 자동 보정하지 않는다.
- `AttemptView.source_verification_enabled`와 `EvidenceView.source_verification_enabled`가
  선택을 표시한다. evidence는 이를 사용한 원래 attempt에서 읽으며 최신 attempt의 설정을
  소급 적용하지 않는다. 끈 실행의 문서 근거 조회는 모델 인용과 실제 원문 페이지를 함께
  반환한다. 회사 근거의 `quote`는 기존처럼 승인 프로필의 실제 원문을 반환한다.
- report의 저장된 checks에 `source_verification_skipped` warning을 남긴다. v2는 분석
  한계에도 표시한다. `validation.status=passed`는 유지된 계약 검사의 통과일 수 있으며
  이 warning이 있으면 UI는 **원문 대조 미실시**로 표시한다. ‘근거 검증 통과’로 표시하거나
  품질 측정·사람 승인을 대신하지 않는다. 과거 revision/checks는 변경하지 않는다.

## 사용자 요청 기반 Luna 심층검토 (ADR-0069)

`POST /api/notices/{notice_id}/deep-review-previews`는
`{bundle_id, source_verification_enabled=true, review_id=null}`를 받아
`DeepReviewPreviewView`를 반환한다. 재실행은 `review_id`의 고정 정책·프로필을 쓴다.
입력은 `preview_id`, `input_sha256`, `provider=codex-exec`, 고정 정책 row의 `model_name`과
`generation.reasoning_effort`, `quality_status=unmeasured_reference`, 대조 설정과 `input`이다.
`input`은 문서·회사 근거를 포함하므로 일반 로그·감사 metadata에 넣지 않는다.
HP-00의 새 identity는 `gpt-6-luna`/`high`, codex CLI `0.162.1`이다. preview·승인 표식의 모델과
effort는 고정 정책 row에서 읽고 실행 metadata의 CLI version은 identity 모듈에서 읽는다. 정책의
모델·effort가 runner identity와 다르면 preview·생성·worker claim은 외부 호출 전에 거부하며
REST는 503 `model_binding_invalid`, worker는 호출 없이 실패로 종결한다. 모델 artifact revision은 없다.
기존 정책 v1~v4·demo-v1과 실행 row는 변경하지 않고, `gpt-5.6-luna`/`xhigh`는 legacy 조회에만 허용한다.
NULL 계보용 `analysis-policy-luna-v5`는 v4에서 `policy_identity`, `model_name`,
`generation.reasoning_effort`, `execution.cli_version` 네 값만 바꾼 불변 정책이다. 가정 분석의
새 불변 input snapshot은 승인 당시 정책을 재확인하도록 `policy_binding={policy_version_id,
policy_sha256,model,reasoning_effort}`를 포함하며 기존 snapshot은 수정하지 않는다.

생성 및 재실행 API·Agent payload에 optional `preview_id`가 추가됐다. Luna 정책에서는
필수이며 없으면 409 `preview_required`, 입력·설정 불일치는 `preview_changed`,
이미 사용한 미리보기는 `preview_used`다. 같은 request ID·actor·payload는 기존 응답을
재생한다. 별도 요청으로 같은 입력 검토를 만들면 `review_exists`, 동일 공고의 실행 중
검토는 `active_attempt_exists`다. 기존 검토는 attempts API로 새 attempt를 만든다.
개요 미완료는 `review_not_ready`, 기능/참조 모드 비활성은 `service_unavailable`이다.

`AttemptView`에 nullable `provider`, `model`, `reasoning_effort`, `preview_id`가 추가됐다.
과거 승인 기록이 없으면 null이며 과거 모델 출처를 추정하지 않는다. 사전규격 목록은
페이지 단위 조회한 `latest_deep_review_status=queued|running|completed|failed|null`을
반환한다. 준비 상태와 실행 상태는 별도다.

migration `0032_luna_deep_review`는 `deep_review_preview`와 `deep_review_approval`을
추가한다. 둘 다 UPDATE/DELETE를 DB trigger와 ORM이 거부한다. 승인 preview와 attempt는
각각 unique이며 FK는 RESTRICT다. app은 SELECT/INSERT, worker는 SELECT만 갖는다.
승인이 존재하면 downgrade를 거부한다. 정책과 모델 revision의 확인되지 않은 값은
추정하지 않는다. 실행 metadata의 CLI version은 HP-00 identity 기준 `0.162.1`이고
모델 artifact revision은 없다.

내부 runner API는 `/calls` POST → `/calls/{id}` GET heartbeat/result → DELETE 취소다.
외부 공개 API가 아니며 worker 전용 내부망에서만 사용한다. prompt는 stdin으로 전달하고
응답은 worker 암호화 저장소로만 보낸다. 실패는 authentication_failed, model_access_denied,
model_timeout, review_timeout, output_truncated, schema_invalid, lease_lost/lease_expired,
validation_failed 등 안전 코드로 남는다. 일부 성공 보고서는 발행하지 않는다.

## Luna v2 보조 연결 경고 (2026-09-23)

사용자 승인 후 새 불변 `analysis-policy-luna-v2.json`에만
`validation.related_claim_policy=omit_invalid_with_warning_v1`을 적용한다.
범위 밖 `related_claim_ids`는 파생 결과에서 제외하며 주장 본문·근거·전제를 고치지 않는다.
암호화 원응답은 보존하고 stage `invocation_metadata.related_claim_diagnostics`에
대상 claim ID·제외 ID·고정 사유를 기록한다. 실제 검증은 제외 후 동일하게 수행한다.
`related_claim_out_of_scope_omitted` validation warning을 해당 문장 및 분석 한계에 표시한다.
`premise_claim_ids`, `evidence_ids`, considered/coverage, 원문·수치·해시 검사는 완화하지 않는다.
종합은 여전히 모든 선행 주장 연결을 요구한다. 중복·자기 참조도 기존처럼 거부한다.
기존 Luna v1/Qwen 정책은 엄격한 동작을 유지하며 과거 실패·보고서를 다시 쓰지 않는다.
새 테이블·migration·응답 schema 변경은 없으며 참조 표식은 유지한다.

## 2026-09-23 검증 off 참조 정책

사용자 요청에 따라 새 Luna v3 정책의 `validation.result_checks=disabled_reference_v1`에서
내용·참조 의미·coverage/considered/요구사항 누락 검증을 수행하지 않는다.
원문 인용·숫자 대조도 끄며 일반 실행의 검증 통과로 표시하지 않는다.
미리보기·보고서에 검증 미실시를 표시하고 `result_validation_skipped` warning을 저장한다.
인증/건별 승인/동결 입력 hash/정책 불변성/lease/JSON schema/DB 식별자 중복·근거 FK/
문서·프로필 소속과 hash/보고서 본문 보존 검사는 유지한다.
이름이 같아도 v1/v2의 정책·결과에는 소급 적용하지 않는다. 실제 모델 품질은 미측정이다.

검사: 저장된 v2 실패 응답의 후보 코드 replay, 기존 회귀+새 off/해시/근거 FK 차단,
PostgreSQL 17.11 저장·REST, 두 폭 경고와 승인 미리보기. 운영 적용/새 호출은 검사 후 진행.

### Luna v4 정책·slice 교정 계약 (2026-10-08, 로컬 구현)

새 불변 `analysis-policy-luna-v4.json`은 `policy_identity=analysis-policy-luna-v4`로 승인 파일을
명시하며, 매핑은 이 값을 v1~v3 내용 기반 판별보다 먼저 확인한다. 모르는 identity는 거부한다.
정책 `execution.review_timeout_seconds=18000`이 검토 전체 Luna deadline이고,
`execution.validation_repair_attempts=1`은 1·2단계의 각 slice에만 적용된다. 최초 응답이
형식·근거 FK·필수 결정 검사를 통과하지 못하면 승인된 같은 동결 입력에 안전한 오류 code와
필드 위치만 더해 완전한 대체 응답을 최대 한 번 요청한다. 3단계 종합과 v1~v3는 자동 교정하지 않는다.
두 원응답은 기존 model-response aggregate 모양을 유지해 암호화 보존하고, 호출 metadata와
보고서 `validation_repair_applied` warning에 교정 사실을 남긴다. 교정 응답도 같은 인용·숫자·
coverage·considered·전제·근거 검사를 모두 통과해야 하며 검사를 끄거나 warning으로 낮추지 않는다.
이 절은 [DEMO-00 STEP-002](../work/groups/DEMO/features/DEMO-00-luna-preflight/spec.md)의 로컬 구현
계약이며 운영 배포·정책 import·실제 Luna 호출 또는 품질 검증 완료를 뜻하지 않는다.

## 1489번 가정 분석 v1 (2026-09-23, 운영 적용 전)

기존 심층검토와 별도 계약이다. [작업 명세](../0923_assumption-analysis/spec.md)를 따른다.

- `POST /api/notices/{notice_id}/assumption-analysis-previews` (`bundle_id`)는 동결 입력,
  hash, 이전 가정 분석/심층검토 미리보기와 달라진 필드를 반환한다. 전송은 하지 않는다.
- `POST /api/notices/{notice_id}/assumption-analyses` (`preview_id`, `request_id`, 기존
  담당자 헤더)는 승인·입력 재확인 뒤 202 `{id, notice_id}`를 반환한다. 동일 요청의
  replay도 같은 응답이다. 이 가정 버전의 대상은 1489번뿐이다.
- `GET /api/notices/{notice_id}/assumption-analyses`는 실행 목록,
  `GET /api/assumption-analyses/{id}`는 상태·호출 수·현재 호출·단계 부분 결과·근거
  레지스트리·계산표와 완성 보고서(`report`, 미완료는 null)를 반환한다.
- schema는 `bidops.assumption-analysis.v1`. 완료는 세 단계와 8절 설명 본문이 있을 때만
  게시한다. 모델 품질은 `unmeasured_reference`; 사실 주장을 검증된 사실로 승격하지 않는다.
- `preview_changed`, `preview_used`, `active_run_exists`, `idempotency_conflict`는 409.
  기존 Luna readiness/접근 게이트는 유지한다. 미연결 근거는 FK로 만들지 않고 문자열 ID와
  `unlinked`를 보존한다. 원문 인용 불일치·숫자 근거 미확인은 문단 경고다.
- migration `0033_assumption_analysis`: 입력 버전·승인 실행·호출 결과는 append-only.
  공용 `work_job`의 `assumption_analysis` job을 합성 worker 한 슬롯에서 처리한다.
  기존 심층검토 정책/회사 프로필/결과는 수정하지 않는다.
