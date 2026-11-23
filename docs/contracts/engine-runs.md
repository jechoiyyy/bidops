# Extracted engine reference run contract

`bid-deep-engine.v1` is the subprocess extraction of `bid-deep-agent`
`14756a011bc0af5164f564328dbad4334a54466b`. `packages/bid-deep-engine/UPSTREAM.json`
lists every vendored file once: upstream files with the upstream-bytes hash and the
adaptation, replaced and BidOps-authored files with the vendored-bytes hash
(`engine_tests/test_manifest.py` checks it offline), plus exclusions. Runtime computes
a digest over every packaged Python and prompt file under `src/`; enqueue freezes it
and execution rejects changed code (`engine_version_changed`).

- Switch: `BIDOPS_ENGINE_ANALYSIS_ENABLED` (bool, default `false`; 2026-11-19). Off,
  `POST` returns 503 `engine_analysis_disabled` before idempotent replay or any read
  or write, and the composed worker's engine slot claims nothing (queued runs stay
  queued until the switch is on). Both `GET` endpoints stay available so existing
  runs remain auditable; they have no side effects. `GET /api/feature-flags` reports
  it as `engine_analysis`. On still means mock_reference only; no compose or env file
  passes the variable today.

- `POST /api/companies/{company_id}/notices/{notice_id}/engine-runs` accepts
  `{request_id, bundle_id, mode: "mock_reference"}` with the existing encoded
  `X-BidOps-Actor-Name` header. It returns 202. Repeated identical request/actor
  returns the same run; a changed scope or actor is 409 `idempotency_conflict`.
  `mode: "live"` returns 409 `engine_live_not_approved` before work is queued (when the
  switch is on; off, the 503 above comes first).
- `GET` on that collection returns `{items,total}` with `limit` 1–100, default 20,
  and nonnegative `offset`. `GET /api/engine-runs/{id}` returns one run or 404.
- A run contains `id`, `request_id`, `company_id`, `notice_id`, `bundle_id`,
  `engine_version`, `engine_sha256`, `quality_status`, `status`, `input_sha256`,
  `profile_version_id`, `profile_sha256`, `graph_version_id`, `graph_sha256`,
  `documents[{document_version_id,source_sha256,structure_id,structure_sha256}]`,
  `input_currentness`, `created_at`, nullable `started_at`, `completed_at`,
  `error_code`, `analysis`, and `warnings[]`. Source paths, object keys and company
  source payloads are not public fields.
- `error_code` of a failed run is one defined code. Runner (inside the subprocess):
  `engine_live_not_approved`, `structure_unavailable` (no text block),
  `invalid_table_coordinates`, `table_too_large`, `input_too_large`,
  `engine_input_invalid` (undecodable or non-object input), `engine_pipeline_failed`
  (any other engine failure). Worker: `input_hash_mismatch`, `engine_version_changed`,
  `engine_unavailable`, `engine_timeout` (90 s), `engine_process_failed` (non-zero
  exit), `engine_output_invalid` (oversized, non-JSON, wrong envelope, or a runner code
  outside the list above), `engine_execution_failed` (unexpected worker-side error),
  `result_storage_failed`, `lease_expired`. Each failure logs one
  `engine_run.failed` line with `run_id`, `worker_id`, `error_code` and
  `failure_type` (exception class name only); no message, stderr or document text.
- `input_currentness=current|stale|unknown` compares active company binding,
  latest ready bundle, current/safe documents and packaged engine digest. It
  means input currency only. It does not imply measured quality or acceptance.
- `status=queued|running|completed|partial|failed` is execution state.
  This version produces only `partial` or `failed` after execution and always
  `quality_status=mock_reference`. It never modifies existing reviews, tracking,
  final Go/No-Go, or accepted quality state.

POST resolves the existing active company knowledge binding and confirmed ready
bundle. It reads the pinned structure object version, validates its hash and
source/document scope, and freezes ordered blocks/tables and source/profile/graph
lineage. HWP/HWPX original lineage is required. No caller-supplied document text,
path, profile, response, model or transport is accepted.

The existing `WorkJob` queue owns execution (`bid_deep_engine_v1`). The composed
single-slot analysis worker invokes the extracted pipeline in a bounded 90-second
subprocess with no inherited credentials. A 120-second fenced lease prevents stale
workers publishing. Expired work is terminal and never silently replayed. Input
and terminal result rows are immutable in PostgreSQL (`0042_engine_run`); web can
insert/select, worker can update result/state columns only, neither can delete.
Results are stored in versioned MinIO `structure` and PostgreSQL in the same fenced
publication path. Storage failure produces a safe failed state without a result.

The pipeline uses the upstream normalizer, extraction/matching/synthesis stages,
gates, scoring, quote verification and readiness logic. Synthetic transport emits
one project quote from the first section and unknown fits, and infers no eligibility
rule from any sentence (tests script rules explicitly); zero tokens/cost are mock
counters. The engine company fingerprint is the engine's own hash of the projected
profile, so a fresh run is not stale; `analysis.company_projection` records both
`source_profile_sha256` (BidOps binding) and `engine_company_input_hash`. Supported
confirmed company project/credit fields are conservatively projected; proposed,
unknown and unmapped fields never become capabilities. `analysis.company_projection`
lists mapped fields, always `complete=false`. `analysis.source_evidence` adds exact
verified quote mappings to document ID, source hash, block key, page and offsets.
The search covers the blocks of the section the engine cites for that quote; only
without a usable citation, or when the quote is not inside it, is the whole input
searched. Every occurrence is listed with `location_status=exact|ambiguous` (one or
several occurrences) and `basis=cited_section|whole_input`.
Existing engine evidence locations remain unchanged; unsupported mapping remains
unavailable. Parser defects and RL-05 rejection are not promoted by this work.

Synthetic E2E seeds use real HWPX fixture bytes and the existing bounded extractor;
they do not constitute antivirus, native rendering or actual model quality evidence.

## 프로세스 파일 계약

분석 adapter는 stdin의 `schema_version=bidops.engine-input.v1` JSON과 stdout의 `schema_version=bidops.engine-output.v1` JSON만 교환한다. 입력은 mode=mock_reference, engine_version/engine_sha256, run slug, 공고/회사/bundle 식별자, profile/graph 버전·hash, 원문·구조 document lineage, 순서를 보존한 구조 block/table을 고정한다. 입력은 8MiB 상한이며 하위 프로세스는 자격증명 없이 실행되고 timeout은90초다. 소비자는 버전·엔진 hash·mock 표식·결과 상태를 검증한다.

회사 자료 폴더(`BIDOPS_ENGINE_COMPANY_BUNDLE_DIR`)와 회사 slug(`BIDOPS_ENGINE_COMPANY_BUNDLE_SLUG`)가 모두 설정되면 입력은 `schema_version=bidops.engine-input.v2`다. v2는 `profile_payload`·`graph_nodes` 본문 대신 `company_bundle`을 싣는다: `profile_file`(프로필 파일 이름), `files`(`<slug>.yaml`·`<slug>.*.yaml`의 이름 → 본문), `knowledge`(회사 위키 `<slug>/` 아래 `.md`의 상대 경로 → 본문, 깊이 2 이하), `bundle_sha256`(앞의 세 항목의 canonical JSON sha256). profile/graph 버전·hash 바인딩은 v1과 같이 남는다. 엔진은 digest를 다시 계산하고 원본 로더로 프로필·출처 sidecar·위키를 읽어, 공고마다 위키 발췌를 골라 대조·종합에 쓴다. 출력의 `analysis.company_projection`은 `source=company_bundle`, `complete=true`, `bundle_sha256`, `knowledge_hash`를 담고 `analysis.knowledge`에 선택한 유형·페이지가 남는다. 폴더를 설정했는데 읽을 수 없으면 생성은 409 `company_bundle_unavailable`, 묶음이 엔진 검증을 통과하지 못하면 실행은 `company_bundle_invalid`로 실패한다. 묶음 digest는 `engine_run.queued` 감사 메타데이터에 `company_bundle_sha256`으로 남는다.

출력은 engine_version, quality_status=mock_reference, status=partial|failed, nullable error_code/error_class/analysis, warnings, artifacts를 포함한다. error_code는 위 runner 코드 목록 중 하나이고 error_class는 예외 클래스 이름(식별자)뿐이다. 소비자는 목록 밖 코드를 engine_output_invalid로 거부하고 식별자가 아닌 error_class는 버린다. 부분 결과의 analysis는 원본 Analysis schema를 따른다. 입력과 구조의 불완전한 projection은 warning을 유지한다. 원본 경로·회사 원문·프롬프트·하위 프로세스 stderr를 API 오류에 반환하지 않는다. 정밀 schema/변환은 `packages/bid-deep-engine/src/bid_deep_engine/runner.py`와 backend `services/engine_runs.py`가 소유하며 원본 revision은 패키지 UPSTREAM manifest를 따른다.
