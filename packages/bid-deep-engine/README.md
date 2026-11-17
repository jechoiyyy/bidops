# bid-deep-engine.v1

Extracted offline engine from `bid-deep-agent` commit
`7ad9283d8e8a405074374d12c5f0a13ccb8e5b1f`. `UPSTREAM.json` records SHA-256 of every
imported source/test file and local dirty-file exclusions. The dirty upstream
`claude_cli.py` is excluded. The 3-pass pipeline, normalizer, gates, scoring,
quote verification, source matching and readiness logic are retained; import
names become `bid_deep_engine`. `llm.py` contains upstream value/error types only,
`tracing.py` is offline, and `config.py` has no configuration or credential loader.

The only executable boundary is `python -m bid_deep_engine.runner`: a bounded
`bidops.engine-input.v1` stdin envelope and `bidops.engine-output.v1` stdout.
No CLI/task DB, A2A/chat, credentials, original company data, network transport,
telemetry or fallback is included. Python 3.12, Pydantic and PyYAML are required.
The containing application owns PostgreSQL, MinIO, jobs, identity and human review.

Only `mock_reference` executes. It runs the real pipeline with synthetic source
quotes and UNKNOWN fits, never a real model. Results remain `partial`; they do
not prove model quality or eligibility. Only explicitly mapped confirmed v2
company fields enter the engine profile. Unmapped and proposed facts stay in
the immutable source snapshot but do not become capabilities. Original structured
tables and blocks enter the upstream normalizer; exact verified quotes receive
additional BidOps document/block/hash locators. HWPX parser and legacy source
quality limitations remain visible rather than being promoted by integration.

Backend fingerprints every packaged Python/prompt file when enqueueing and
rejects execution if code changed. The API reports pinned documents/profile/
graph plus input currentness independently from run status and quality status.

Synthetic upstream tests: `PYTHONPATH=src:. python -m pytest engine_tests`.
The application image copies this package and invokes it in a subprocess; it
never imports the old pipeline into the web process.
