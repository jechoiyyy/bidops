# HP-00 validation and resume

Feature workspace: `/Users/temp/orca/bidops/.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/hp0001-20261014-HP-00-luna-model-identity`
Base and HEAD at evidence start: `fba715332e70e0994e2296a8899acf8270f5bd6b` (changes uncommitted).

STEP-001 through STEP-005 were implemented and reviewed. STEP-006 deployment, policy registration/selection, and the single approved smoke attempt have now run in the isolated `bidops-local` stack. The T11 runtime identity assertion is confirmed by actual invocation metadata. The attempt ended on validation failure, so it is not a successful analysis or quality result; quality remains unmeasured. Feature status/proof and integration remain owned by the run leader.

## Implementation validation evidence

- `backend-tests.log`: 156 passed, 4 failed because fixtures still selected legacy-model policies. The product code stayed unchanged; fixture-only follow-up `backend-fixture-fix.log`: 4 passed. Final relevant coverage is 160 passing cases; the initial failures remain recorded.
- `step001-tests.log`: 15 passed; `step002-tests.log`: 7 passed; `step002-boundaries.log`: 5 passed. These are earlier step checks, not additional unique final cases.
- `frontend-tests.log`: TypeScript and production build succeeded. The browser run initially could not start because IPv6 localhost was unavailable; the same dist was served explicitly on IPv4 and `frontend-browser-tests.log` records 27 passed. The leader inspected `1280px luna-preview.png` and the current identity text.
- `compose-check.log`: synthetic image rendering and rejection of a missing required image passed.
- `final-feature-review.md`: independent `gpt-5.6-sol/high` review, zero blockers.

Implementation checks used disposable PostgreSQL 17.11. STEP-006 used the isolated `bidops-local` PostgreSQL database without applying a migration; its head stayed `0036_company_analysis`. The separate `bidops` project was not changed.

## STEP-006 runtime evidence

The reviewed app image was `bidops-local:hp00-20261014` (`sha256:44ad212a95008ca9a3900d0b5b4487c862435bdd4048886a266e7ffe208150c9`). The runner image was `bidops-local:codex-runner-20261014` (`sha256:64bf4925bdbc6e1a891a3a32753e5d61d0def8ef3eb95eeebf7ac407d44e620b`), with CLI 0.162.1. Only `web`, `analysis-worker`, and `codex-runner` were initially recreated in `bidops-local`; the web was healthy, `/` and `/api/health` returned HTTP 200, and no migration ran. Deployment, backup, and rollback details are in `step006-deployment.md`.

The immutable HP-v1 and v5 policies were registered through the policy-only product service. Their exact hashes, DB UUIDs, and existing-row preservation are recorded in `step006-policy-import.md`. After the approved selection, only `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID` in the external mode-0600 `hp00.env` changed to HP-v1 UUID `09fe587d-cd12-4449-8d9f-9d453b297de0`; a pre-selection copy and a post-registration PostgreSQL restore point are preserved outside Git. Only `web` and `analysis-worker` were recreated for that selection; the runner stayed on the reviewed image.

One existing frozen preview was approved and submitted through the product API: fictional company `demo-cloud-si`, public notice 139, preview `1a6c85a9-e823-4e24-9f5b-4fb3e53eef74`, input SHA-256 `7e980046f9c70911f1390f2efc4d4855eec9149b907f93c4dbb9a04f546302f5`. The payload was 626,762 bytes with 45 source units; no new source material was added. The resulting review is `6012b94c-a51a-4e6f-b6c6-45fa648a50b5`, attempt 1 is `7a0b03e1-b762-45a4-a8dc-026b9c00d444`.

The actual first-slice invocation metadata records `provider=codex-exec`, `model=gpt-6-luna`, `cli_version=0.162.1`, `reasoning_effort=high`, and the selected HP-v1 policy SHA. This satisfies T11's identity assertion. The initial response failed `validation:fact_number_not_in_evidence`; the single policy-permitted repair failed `narrative:document_evidence_out_of_slice`. The attempt and work job are terminal `failed`, the later two stages did not run, there are no active work jobs, and no retry or additional attempt was created. `quality_status=unmeasured_reference`; no analysis-success or quality claim is made. Safe details and response hashes are in `step006-smoke-attempt.json`; raw prompt, source text, and model response are not included.

The policy allows a 900-second per-call timeout and a 18,000-second review timeout, disables automatic retry, and permits one validation repair. The frozen input implies 45 source-stage slices (up to 90 calls if every slice needed that repair); later-stage slice counts depend on model output, with no finite total-call cap in the policy. This attempt made exactly two Codex invocations on slice 0 and stopped after repair failure.

Leader independently verified the actual terminal invocation metadata and immutable policy rows. Product/test files are unchanged since the recorded passing automated checks; only deployment/authorization evidence and plan results changed. Those checks are reused without rerunning unrelated suites. The real_data_run human acceptance proof applies only to HP-03/HP-06 per feature.json; HP-00 T11 runtime identity is evidenced separately here and in step006-smoke-attempt.json, without claiming human acceptance or analysis quality.
