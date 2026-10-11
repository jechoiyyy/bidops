Read-only independent SDLC batch final review, gpt-5.6-sol/high. No tests, edits, agents, workflows, Docker, model/API calls, or commits. Return a concise Korean verdict (PASS / PASS_WITH_NOTES / FAIL) with concrete blockers only; list non-blocking notes one line each.

Batch run `demo0203-20261009`: DEMO-02-company-knowledge then DEMO-03-grounded-analysis on demo branch `demo/local-20261009`. Approved base SHA `506ac77`. The final batch tree is this worktree: commit `7a110ce` plus uncommitted doc-only corrections (8 Markdown lines; see `git diff`). Review the whole change with `git diff 506ac77` (working tree vs base).

Read root AGENTS.md, docs/standards.md, docs/work/demo-contract.md, and the DEMO-02 and DEMO-03 feature documents under docs/work/groups/DEMO/features/ (intent.md, spec.md acceptance criteria, plan.md). The common constraints are in `python3 scripts/feature_status.py config` (constraints list); you may run that read-only command.

Prior evidence in docs/work/_runs/demo0203-20261009/: per-feature independent reviews review.md (DEMO-02) and demo03-review.md (DEMO-03), a batch-level review batch-review.md, leader test logs batch-demo02-final-tests.log (DEMO-02 9 files on final code, 308 passed, skip 0) and demo03-final-leader.log (510 passed, skip 0), and STEP-007 real isolated stack evidence docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md. Do not re-run tests; judge whether the evidence matches the final source.

Decide:
1. Does the final tree satisfy every DEMO-02 and DEMO-03 spec acceptance criterion as currently written (DEMO-03 was re-planned on 2026-10-11: T9 real Luna representative run moved to DEMO-05; STEP-007 = real bidops-local stack prep plus pre-call fail-closed check; real_data_run not applicable)?
2. Do the two features' code and contract paragraphs (docs/contracts.md, docs/ARCHITECTURE.md, docs/business-rules.md, docs/deep-review-erd.md, docs/operations.md) agree with each other and with the code?
3. Common constraints: append-only/immutable inputs, unknown/null not promoted, per-item approval and no fallback for external models, single analysis-worker slot and module dependency direction, new tables/columns registered in scripts/runtime-privileges.sql with no GRANT in migrations, no main/ops changes.
4. No document claims real model quality or a completed real Luna run; no secrets in committed evidence.

Do not inspect candidate notice content or actual company data beyond the committed fixtures. Report only blockers you verified in the source, with file:line and the exact criterion violated.
