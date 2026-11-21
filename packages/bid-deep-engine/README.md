# bid-deep-engine.v1

Extracted offline engine from `bid-deep-agent` commit
`14756a011bc0af5164f564328dbad4334a54466b`. `UPSTREAM.json` lists every file in
`src/` and `engine_tests/` exactly once, in one of three groups (`hash_semantics`):
`files` are upstream files with the SHA-256 of the upstream bytes at that commit and
the adaptation applied here (`import rename`, or a declared excerpt); `replaced_files`
replace an upstream file of the same path and `authored_files` are written in BidOps,
both with the SHA-256 of the vendored bytes. `engine_tests/test_manifest.py` checks
all three offline. Local dirty-file exclusions are listed as well. The dirty upstream
`claude_cli.py` is excluded. The 3-pass pipeline, normalizer, gates, scoring,
quote verification, source matching and readiness logic are retained; import
names become `bid_deep_engine`. `llm.py` contains upstream value/error types only,
`tracing.py` is offline, and `config.py` has no configuration or credential loader.

The only executable boundary is `python -m bid_deep_engine.runner`: a bounded
`bidops.engine-input.v1` stdin envelope and `bidops.engine-output.v1` stdout.
No CLI/task DB, A2A/chat, credentials, original company data, network transport,
telemetry or fallback is included. Python 3.12, Pydantic and PyYAML are required.
The containing application owns PostgreSQL, MinIO, jobs, identity and human review.

Only `mock_reference` executes. It runs the real pipeline with one synthetic
project quote and UNKNOWN fits, never a real model, and infers no eligibility rule
from document text; tests drive the gate path with explicit `MockRule`s passed to
`execute(mock_rules=...)`, which `main()` never does. Results remain `partial`; they
do not prove model quality or eligibility. The company fingerprint passed to the
pipeline is the engine's own `CompanyEvidenceView(profile).company_input_hash`, and
the runner writes `bundle.json` beside `rfp.json`, so a fresh run's stages are
current rather than stale; BidOps' `profile_sha256` is kept separately in
`analysis.company_projection`. Only explicitly mapped confirmed v2
company fields enter the engine profile. Unmapped and proposed facts stay in
the immutable source snapshot but do not become capabilities. Original structured
tables and blocks enter the upstream normalizer; exact verified quotes receive
additional BidOps document/block/hash locators, searched within the section the
engine cites and marked `exact` or `ambiguous`. HWPX parser and legacy source
quality limitations remain visible rather than being promoted by integration.

Failures carry one defined `error_code` (`runner.ERROR_CODES`) and only the
exception class name as `error_class`; messages, stderr and source text are never
emitted. Backend fingerprints every packaged Python/prompt file under `src/` when
enqueueing and rejects execution if code changed. The backend path is off unless
`BIDOPS_ENGINE_ANALYSIS_ENABLED=true`. The API reports pinned documents/profile/
graph plus input currentness independently from run status and quality status.

Tests: `PYTHONPATH=src:. python -m pytest engine_tests` (1,493 on 2026-11-19).
They are 18 upstream test files that run against the vendored core without the
excluded transport (`files` in the manifest, synthetic fixtures included) plus the
BidOps-authored adapter, runner and manifest tests. `engine_tests/ingest_writer.py`
is a test-only stand-in for upstream `ingest/writer.py`, which is not vendored.
Upstream tests that import excluded modules (transport, CLI, report, regate, golden,
tasks/service/agent, ingest discovery/parsers), or need upstream company data or the
real company profile fixture `tests/fixtures/knowledge/profile.yaml` (not copied),
are left out.
The application image copies this package and invokes it in a subprocess; it
never imports the old pipeline into the web process.
