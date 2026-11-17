# Extracted engine reference run contract

`bid-deep-engine.v1` is the subprocess extraction of `bid-deep-agent`
`7ad9283d8e8a405074374d12c5f0a13ccb8e5b1f`. `packages/bid-deep-engine/UPSTREAM.json`
pins source hashes and exclusions. Runtime computes a digest over every packaged
Python and prompt file; enqueue freezes it and execution rejects changed code.

- `POST /api/companies/{company_id}/notices/{notice_id}/engine-runs` accepts
  `{request_id, bundle_id, mode: "mock_reference"}` with the existing encoded
  `X-BidOps-Actor-Name` header. It returns 202. Repeated identical request/actor
  returns the same run; a changed scope or actor is 409 `idempotency_conflict`.
  `mode: "live"` always returns 409 `engine_live_not_approved` before work is queued.
- `GET` on that collection returns `{items,total}` with `limit` 1–100, default 20,
  and nonnegative `offset`. `GET /api/engine-runs/{id}` returns one run or 404.
- A run contains `id`, `request_id`, `company_id`, `notice_id`, `bundle_id`,
  `engine_version`, `engine_sha256`, `quality_status`, `status`, `input_sha256`,
  `profile_version_id`, `profile_sha256`, `graph_version_id`, `graph_sha256`,
  `documents[{document_version_id,source_sha256,structure_id,structure_sha256}]`,
  `input_currentness`, `created_at`, nullable `started_at`, `completed_at`,
  `error_code`, `analysis`, and `warnings[]`. Source paths, object keys and company
  source payloads are not public fields.
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
source quotes and unknown fits; zero tokens/cost are mock counters. Supported
confirmed company project/credit fields are conservatively projected; proposed,
unknown and unmapped fields never become capabilities. `analysis.company_projection`
lists mapped fields, always `complete=false`. `analysis.source_evidence` adds exact
verified quote mappings to document ID, source hash, block key, page and offsets.
Existing engine evidence locations remain unchanged; unsupported mapping remains
unavailable. Parser defects and RL-05 rejection are not promoted by this work.

Synthetic E2E seeds use real HWPX fixture bytes and the existing bounded extractor;
they do not constitute antivirus, native rendering or actual model quality evidence.

## 프로세스 파일 계약

분석 adapter는 stdin의 `schema_version=bidops.engine-input.v1` JSON과 stdout의 `schema_version=bidops.engine-output.v1` JSON만 교환한다. 입력은 mode=mock_reference, engine_version/engine_sha256, run slug, 공고/회사/bundle 식별자, profile/graph 버전·hash, 원문·구조 document lineage, 순서를 보존한 구조 block/table을 고정한다. 입력은 8MiB 상한이며 하위 프로세스는 자격증명 없이 실행되고 timeout은90초다. 소비자는 버전·엔진 hash·mock 표식·결과 상태를 검증한다.

출력은 engine_version, quality_status=mock_reference, status=partial|failed, nullable error_code/analysis, warnings, artifacts를 포함한다. 부분 결과의 analysis는 원본 Analysis schema를 따른다. 입력과 구조의 불완전한 projection은 warning을 유지한다. 원본 경로·회사 원문·프롬프트·하위 프로세스 stderr를 API 오류에 반환하지 않는다. 정밀 schema/변환은 `packages/bid-deep-engine/src/bid_deep_engine/runner.py`와 backend `services/engine_runs.py`가 소유하며 원본 revision은 패키지 UPSTREAM manifest를 따른다.
