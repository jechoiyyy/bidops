# v4 policy/attempt/current focused validation (2026-09-08)

This record covers the isolated consumer after the immutable PDF snapshot and
input manifest. It does not claim an operational DB/MinIO write, a live model
call, policy activation, or UI acceptance.

```text
cd web/backend
.venv/bin/python -m pytest tests/deep_review/test_prespec_v4_runner.py tests/app/test_analysis_worker_slots.py -q --tb=short
12 passed, 3 warnings

.venv/bin/python -m pytest tests/app/test_models.py tests/app/test_db_migrations.py -q --tb=short
3 passed, 32 skipped (PostgreSQL URL not configured in this shell)

.venv/bin/python -m pytest tests/app/test_analysis_worker_slots.py tests/deep_review/test_page_overview.py tests/deep_review/test_prespec_v4_preparation.py tests/deep_review/test_prespec_v4_runner.py tests/app/test_runtime_database_privileges.py -q --tb=short
36 passed, 2 skipped, 8 warnings

.venv/bin/python -m pytest tests/core/test_model_client.py -q --tb=short
42 passed

.venv/bin/python - <<'PY'
import os, subprocess, sys
from tests.postgres import temporary_postgres_server
with temporary_postgres_server() as url:
    env = os.environ.copy()
    env['BIDOPS_TEST_POSTGRES_URL'] = url
    result = subprocess.run(
        [sys.executable, '-m', 'pytest',
         'tests/deep_review/test_prespec_v4_postgres.py',
         'tests/app/test_runtime_database_privileges.py',
         '-q', '--tb=short'], env=env, text=True
    )
    raise SystemExit(result.returncode)
PY
12 passed
```

The focused roundtrip used the existing isolated source/snapshot/manifest
helpers and a controlled client. It verified that only selected page text
reaches the model seam as policy-compatible `blocks[{pdf_page,text}]`, a
successful v3 payload appends `PreSpecPageOverview`
and is exposed by `current`, duplicate enqueue returns the existing active
attempt, a schema failure stores the exact raw payload in the encrypted-store
contract and creates no result, and a PDF preparation failure is visible as a
terminal current attempt. The analysis worker keeps its legacy v1 slot when no
v4 target attempt exists; a queued/running v4 attempt reserves the slot.
When a v4 target or preparation/attempt row claims a document, the legacy
selector receives only that document's exclusion set; unrelated legacy queue
items remain eligible.

The policy parity check compares the deployed v4 policy's system prompt, stage
instruction, output schema, generation, chunking, reader format, and both
synthetic few-shot examples with the existing reference policy. Only the
deployment identifiers are normalized to policy v4, `qwen3.8-27B`, and
`prespec-overview-v4`. The model client regression confirms a bounded malformed
or truncated response can retain the exact raw response bytes for encrypted
failure storage. Batch current projection loads attempts, targets, snapshots,
documents, content/scans, and results by ID sets, then compares the stored
model digest with the configured overview revision without a provider call; it
also requires `needs_human_review=false` and `evidence_check_status=passed`.

The v4 policy is `qwen3.8-27B`, `prespec-overview-v4`, schema
`bidops.prespec-overview-page-review.v3`, retry `0`, timeout `300`, and lease
`600` seconds. `mock_reference` remains a controlled result marker and is not
an automatic deep-review or quality activation signal.

The temporary PostgreSQL 17 check upgraded through `0022_prespec_v4_attempt`
and passed FK/scope, duplicate active target, terminal immutability, and
runtime privilege smoke. Production DB/MinIO and live model execution remain
untouched. The separate UI worker passed its current-contract checks, but live
API/browser acceptance remains pending.
