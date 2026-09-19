#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/manual-workflow-common.sh
source "${SCRIPT_DIR}/manual-workflow-common.sh"
# shellcheck source=scripts/c2-execution-common.sh
source "${SCRIPT_DIR}/c2-execution-common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/run-daily-lifecycle.sh --track <order-plans|notices> [--date YYYY-MM-DD] [--dry-run]
  scripts/run-daily-lifecycle.sh --track <order-plans|notices> --from-date YYYY-MM-DD --to-date YYYY-MM-DD [--dry-run]
  scripts/run-daily-lifecycle.sh --track <order-plans|notices> --collect-only --run-suffix NAME [--date YYYY-MM-DD] [--dry-run]
  scripts/run-daily-lifecycle.sh -h|--help

Runs one day of collection and selective ingest for a single track (the
order-plans and notices tracks are independent; run each on its own
schedule):
  order-plans track: preflight -> daily C-2 trigger check (GET
    /api/order-plan-screening/daily-trigger; when effective_enabled is false
    it prints daily_trigger_off with its reasons and exits 0 WITHOUT
    collecting) -> order-plan collection (1-day window, [reference day,
    reference day + 1), exclusive end) -> ingest (--collection) ->
    --tracked-backfill -> canonical run id lookup (GET /api/runs/<run dir>)
    -> C-2 execution (X-BidOps-Trigger: daily_script, polled to a terminal
    status) -> audit-sample draw. Run id lifecycle-<YYYYMMDD>-plans. The four
    stages always run together (decision 10); the C-2 rules are those of
    scripts/run-daily-c2.sh. Requires BIDOPS_C2_DAILY_ACTOR (no default).
  notices track (pre-specs + bids, tagged with 1468 SW-industry status):
    preflight -> notice collection (4-day window ending on the reference
    day, both ends inclusive (late-published pre-specs)) -> ingest
    (--collection) -> --tracked-backfill -> attachment fetch-eligibility
    refresh. Run id lifecycle-<YYYYMMDD>-notices.

Each reference day resumes from the first missing stage:
  complete        a run directory whose collection is marked complete and
                  whose Run row exists in the web -> nothing to do. The Run
                  row is keyed by <run dir>--<generated_at>Z; the web resolves
                  the directory name to it and C-2 uses that canonical id.
  empty           a complete collection with counts.total == 0 -> done; no
                  ingest (no Run row is needed).
  ingest_pending  a complete collection without a Run row -> ingest only.
  (order-plans)   after the above, a non-empty run continues with the C-2
                  stage: no 성공/부분 성공 execution -> execute first; one
                  exists -> draw the audit sample if not drawn yet. An empty
                  run ends as empty_population (no execution).
  collect_new     no run directory -> collect into lifecycle-<day>-<kind>.
  collect_retry<N>
                  only incomplete directories (marker missing or false) ->
                  they are left untouched and a new collection goes into
                  lifecycle-<day>-<kind>-retry<N> (smallest unused N >= 1).

Options:
  --track order-plans|notices
                      Which track to run this invocation (required, no
                      default).
  --date YYYY-MM-DD   Reference day in Asia/Seoul (default: yesterday, KST).
  --from-date YYYY-MM-DD, --to-date YYYY-MM-DD
                      Catch up an inclusive range of reference days, oldest
                      first, each resumed stage by stage as above. Both are
                      required together; not combinable with --date or
                      --collect-only. No sleep between days. The first
                      failing day stops the track; later days do not run.
  --collect-only      Collect only; skip preflight, the daily C-2 trigger
                      check, run lookup, ingest, and C-2 entirely. Requires --run-suffix so it does not occupy
                      the daily run id.
  --run-suffix NAME   Suffix appended to the run id. Only valid with
                      --collect-only. Lowercase alphanumeric/hyphen
                      (1-40 chars, starts with alphanumeric); must not be
                      retry<N> (reserved for recollection).
  --dry-run           Print each day's decision, run id, window, and the
                      exact commands of its stage; do not collect, ingest,
                      or touch Docker or the web. Local run directories are
                      read; the web Run lookup is skipped, so a complete
                      collection shows as complete_or_ingest_pending and the
                      canonical run id C-2 needs is not resolved.
  -h, --help          Show this help.

Environment (order-plans track):
  BIDOPS_C2_DAILY_ACTOR                  required, no default; not needed for
                                         --collect-only or --dry-run.
  BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS     default 600.
  BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS   default 7200.
  BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS  default 30.

Exit 0 for success and the normal skips (daily_trigger_off, empty_population,
active_execution_exists, already_executed, retry_limit_reached, and an
execution POST answered with policy_not_active, daily_trigger_off, or 503).
An active execution that has been queued or running for more than twice
BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS is not a normal skip: it is printed with
its id, status and age and exits non-zero so somebody looks at the worker.
daily_trigger_off, policy_not_active, 503, and active_execution_exists end the
track there (later days of a range would get the same answer); the other skips
continue with the next day.

Safety:
  - Stops on the first failure (no partial silent continuation).
  - Never overwrites or deletes an existing immutable run directory,
    including incomplete ones.
  - Never installs cron; the scheduler stays disabled by default (see
    CLAUDE.md). The script itself calls no model; a C-2 execution it
    requests runs in the analysis worker under the approved binding.
EOF
}

opt_date=""
opt_from_date=""
opt_to_date=""
opt_track=""
dry_run="false"
collect_only="false"
run_suffix=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date) opt_date="${2:-}"; shift 2 ;;
    --from-date) opt_from_date="${2:-}"; shift 2 ;;
    --to-date) opt_to_date="${2:-}"; shift 2 ;;
    --track) opt_track="${2:-}"; shift 2 ;;
    --dry-run) dry_run="true"; shift ;;
    --collect-only) collect_only="true"; shift ;;
    --run-suffix) run_suffix="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; workflow_die "unknown option: $1" ;;
  esac
done

if [[ -z "${opt_track}" ]]; then
  usage >&2
  workflow_die "--track is required (order-plans|notices)"
fi
case "${opt_track}" in
  order-plans|notices) ;;
  *) workflow_die "--track must be order-plans or notices: ${opt_track}" ;;
esac

if [[ "${collect_only}" == "true" && -z "${run_suffix}" ]]; then
  workflow_die "--collect-only requires --run-suffix"
fi
if [[ -n "${run_suffix}" && "${collect_only}" != "true" ]]; then
  workflow_die "--run-suffix is only valid with --collect-only"
fi
if [[ -n "${run_suffix}" ]]; then
  [[ "${run_suffix}" =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]] \
    || workflow_die "invalid --run-suffix: ${run_suffix}"
  if [[ "${run_suffix}" =~ ^retry[0-9]+$ ]]; then
    workflow_die "--run-suffix must not be retry<N> (reserved for recollection)"
  fi
fi

range_mode="false"
if [[ -n "${opt_from_date}" || -n "${opt_to_date}" ]]; then
  range_mode="true"
  [[ -n "${opt_from_date}" && -n "${opt_to_date}" ]] \
    || workflow_die "--from-date and --to-date must be given together"
  [[ -z "${opt_date}" ]] \
    || workflow_die "--date cannot be combined with --from-date/--to-date"
  [[ "${collect_only}" != "true" ]] \
    || workflow_die "--collect-only cannot be combined with --from-date/--to-date"
fi

# Prints the canonical YYYY-MM-DD for a user-given day or dies. GNU date
# rejects invalid calendar dates such as 2026-02-30.
canonical_date() {
  local flag="$1" value="$2" canonical
  [[ "${value}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
    || workflow_die "${flag} must be YYYY-MM-DD: ${value}"
  canonical="$(date -d "${value}" +%Y-%m-%d 2>/dev/null)" \
    || workflow_die "invalid ${flag} value: ${value}"
  printf '%s\n' "${canonical}"
}

ref_dates=()
if [[ "${range_mode}" == "true" ]]; then
  range_from="$(canonical_date --from-date "${opt_from_date}")"
  range_to="$(canonical_date --to-date "${opt_to_date}")"
  [[ ! "${range_from}" > "${range_to}" ]] \
    || workflow_die "--from-date must not be after --to-date: ${range_from} > ${range_to}"
  day="${range_from}"
  while [[ ! "${day}" > "${range_to}" ]]; do
    ref_dates+=("${day}")
    day="$(date -d "${day} +1 day" +%Y-%m-%d)"
  done
elif [[ -n "${opt_date}" ]]; then
  ref_dates=("$(canonical_date --date "${opt_date}")")
else
  ref_dates=("$(TZ=Asia/Seoul date -d 'yesterday' +%Y-%m-%d)")
fi

case "${opt_track}" in
  order-plans) track_kind="plans" ;;
  notices) track_kind="notices" ;;
esac

# Per-day context, set by set_day_context and resolve_run_state.
ref_date=""
from_date=""
to_date=""
base_run_id=""
run_id=""
run_dir=""
state=""

set_day_context() {
  ref_date="$1"
  base_run_id="lifecycle-$(date -d "${ref_date}" +%Y%m%d)-${track_kind}"
  # order-plans: 1 day, [reference day, reference day + 1) — collect_order_plans.py
  # --to-date is exclusive.
  # notices: 4 days ending on the reference day, both ends inclusive —
  # pre-specs are queried by rgstDt but become visible at rcptDt up to 3 days
  # later (M0, 2026-09-18). collect_notices.py --to-date is inclusive.
  if [[ "${opt_track}" == "order-plans" ]]; then
    from_date="${ref_date}"
    to_date="$(date -d "${ref_date} +1 day" +%Y-%m-%d)"
  else
    from_date="$(date -d "${ref_date} -3 days" +%Y-%m-%d)"
    to_date="${ref_date}"
  fi
}

use_run() {
  run_id="$1"
  run_dir="$(workflow_run_dir "${run_id}")"
}

# Decides the day's stage (spec §8 "완전한 회차"·"불완전 디렉터리"·"0건인 날").
# The first directory (base, then -retry<N> ascending) whose collection is
# marked complete is the day's run; incomplete directories are only skipped.
# With check_rows=false (dry-run) the web is not asked, so a non-empty
# complete collection is complete_or_ingest_pending.
resolve_run_state() {
  local check_rows="$1" candidate total n
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    total="$(workflow_complete_collection_total "${track_kind}" "$(workflow_run_dir "${candidate}")")"
    [[ -n "${total}" ]] || continue
    use_run "${candidate}"
    if [[ "${total}" == "0" ]]; then
      state="empty"
    elif [[ "${check_rows}" != "true" ]]; then
      state="complete_or_ingest_pending"
    elif workflow_lookup_run_row "${candidate}"; then
      state="complete"
    else
      state="ingest_pending"
    fi
    return 0
  done < <(workflow_run_candidates "${base_run_id}")

  use_run "${base_run_id}"
  if [[ ! -e "${run_dir}" && ! -L "${run_dir}" ]]; then
    state="collect_new"
    return 0
  fi
  n="$(workflow_next_retry_number "${base_run_id}")"
  use_run "${base_run_id}-retry${n}"
  state="collect_retry${n}"
}

print_plan() {
  workflow_note "track: ${opt_track}"
  workflow_note "reference day (KST): ${ref_date}"
  workflow_note "run: ${run_id}"
  if [[ "${opt_track}" == "order-plans" ]]; then
    workflow_note "  window: --from-date ${from_date} --to-date ${to_date} (half-open, exclusive end; 1 day: ${ref_date})"
  else
    workflow_note "  window: --from-date ${from_date} --to-date ${to_date} (closed, inclusive both ends; 4 days: ${from_date}..${ref_date})"
  fi
  workflow_note "  dir:    ${run_dir}"
  if [[ "${collect_only}" == "true" ]]; then
    workflow_note "mode: collect-only (no preflight, no ingest)"
  fi
}

print_decision() {
  workflow_note "decision ${ref_date}: ${state} (${run_id})"
}

print_dry_run_collect() {
  if [[ "${opt_track}" == "order-plans" ]]; then
    cat <<EOF
[dry-run] would run:
  python3 skills/bidops-collect/scripts/collect_order_plans.py \\
    --from-date ${from_date} --to-date ${to_date} \\
    --output-dir ${run_dir} --timeout 300
  jq '{schema_version, metadata, counts}' ${run_dir}/collected-order-plans.json
EOF
  else
    cat <<EOF
[dry-run] would run:
  python3 skills/bidops-collect/scripts/collect_notices.py \\
    --from-date ${from_date} --to-date ${to_date} \\
    --output-dir ${run_dir} --timeout 300 --tag-bid-sw-industry
  jq '{schema_version, counts, sw_industry_1468: (.metadata.sw_industry_1468 // null)}' ${run_dir}/collected-notices.json
EOF
  fi
}

print_dry_run_ingest() {
  cat <<EOF

  docker compose -f docker-compose.yml cp ${run_dir} web:/app/data/runs/
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --run ${run_id} --collection
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill
EOF
  if [[ "${opt_track}" == "notices" ]]; then
    cat <<EOF
  docker compose -f docker-compose.yml exec -T web python -c \\
    'from app.core.db import SessionLocal; from app.deep_review.services.prespec_attachments import refresh_fetch_eligibility; s=SessionLocal(); print(refresh_fetch_eligibility(s)); s.commit()'
EOF
  fi
}

print_dry_run_c2() {
  [[ "${opt_track}" == "order-plans" ]] || return 0
  cat <<EOF

  C-2 stage (same rules as scripts/run-daily-c2.sh ${run_id}):
    GET  /api/runs/${run_id}   -> <canonical run id> = ${run_id}--<generated_at>Z
         (the ingest loader keys the Run row that way; C-2 takes that id only.
          A dry run calls no web, so the id is not resolved here.)
    GET  /api/order-plan-screening/executions?source_run_id=<canonical run id>&limit=500
    POST /api/order-plan-screening/executions   X-BidOps-Trigger: daily_script
         (only without a 성공/부분 성공/대기/실행 중/중지 요청 execution; attempt > 2 -> retry_limit_reached)
    GET  /api/order-plan-screening/executions/<id>   until terminal
    POST /api/order-plan-screening/executions/<id>/audit-sample   X-BidOps-Trigger: daily_script
EOF
}

print_dry_run_day() {
  case "${state}" in
    empty)
      if [[ "${opt_track}" == "order-plans" ]]; then
        workflow_note "[dry-run] empty run (counts.total == 0): nothing to ingest; empty_population, no C-2 execution"
      else
        workflow_note "[dry-run] empty run (counts.total == 0): nothing to ingest"
      fi
      ;;
    complete_or_ingest_pending)
      workflow_note "[dry-run] web lookup skipped; complete if the Run row exists, otherwise ingest only:"
      print_dry_run_ingest
      print_dry_run_c2
      ;;
    collect_*)
      print_dry_run_collect
      if [[ "${collect_only}" != "true" ]]; then
        printf '\n  (ingest only when the collection is marked complete and counts.total > 0)'
        print_dry_run_ingest
        print_dry_run_c2
      fi
      ;;
  esac
}

print_result() {
  local label="$1" result="$2"
  workflow_note "${label} result:"
  printf '%s\n' "${result}" | jq .
  printf '%s\n' "${result}" | jq -c '
    if has("selection") then {selection}
    elif has("selected") then {selected}
    elif has("counts") then {counts}
    else empty end'
}

collect_order_plans_step() {
  workflow_check_new_run_dir "${run_dir}"
  workflow_note "collecting order plans into immutable run ${run_id}"
  python3 skills/bidops-collect/scripts/collect_order_plans.py \
    --from-date "${from_date}" --to-date "${to_date}" \
    --output-dir "${run_dir}" --timeout 300
  jq '{schema_version, metadata, counts}' "${run_dir}/collected-order-plans.json"
}

collect_notices_step() {
  workflow_check_new_run_dir "${run_dir}"
  workflow_note "collecting notices (pre-specs + bids, 1468 tagged) into immutable run ${run_id}"
  python3 skills/bidops-collect/scripts/collect_notices.py \
    --from-date "${from_date}" --to-date "${to_date}" \
    --output-dir "${run_dir}" --timeout 300 --tag-bid-sw-industry
  jq '{schema_version, counts, sw_industry_1468: (.metadata.sw_industry_1468 // null)}' \
    "${run_dir}/collected-notices.json"
}

ingest_order_plans_step() {
  workflow_copy_run_if_missing "${run_id}" "${run_dir}"

  local result
  workflow_note "ingesting order-plan run ${run_id} (--collection)"
  result="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.lifecycle.ingest.cli --run "${run_id}" --collection)"
  print_result "order-plan ingest" "${result}"

  workflow_note "running tracked backfill"
  result="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill)"
  print_result "tracked backfill" "${result}"
}

ingest_notices_step() {
  workflow_copy_run_if_missing "${run_id}" "${run_dir}"

  local result
  workflow_note "ingesting notice run ${run_id} (--collection)"
  result="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.lifecycle.ingest.cli --run "${run_id}" --collection)"
  print_result "notice ingest" "${result}"

  workflow_note "running tracked backfill"
  result="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill)"
  print_result "tracked backfill" "${result}"

  workflow_note "refreshing attachment fetch eligibility"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -c \
    'from app.core.db import SessionLocal; from app.deep_review.services.prespec_attachments import refresh_fetch_eligibility; s=SessionLocal(); print(refresh_fetch_eligibility(s)); s.commit()'
}

collect_step() {
  if [[ "${opt_track}" == "order-plans" ]]; then
    collect_order_plans_step
  else
    collect_notices_step
  fi
}

ingest_step() {
  if [[ "${opt_track}" == "order-plans" ]]; then
    ingest_order_plans_step
  else
    ingest_notices_step
  fi
}

# Collection and ingest stages of one day. Leaves state at complete or empty
# on success; any failure exits the script (set -e), so later days never run.
collect_and_ingest_day() {
  local total
  case "${state}" in
    complete)
      workflow_note "run ${run_id} is complete; skipping collection and ingest"
      ;;
    empty)
      workflow_note "run ${run_id} is empty (counts.total == 0); nothing to ingest"
      ;;
    ingest_pending)
      workflow_note "run ${run_id} is collected but not ingested; resuming at ingest"
      ingest_step
      state="complete"
      ;;
    collect_*)
      collect_step
      total="$(workflow_complete_collection_total "${track_kind}" "${run_dir}")"
      [[ -n "${total}" ]] || workflow_die \
        "collection of ${run_id} is not marked complete; the directory is kept and the next run recollects into -retry<N>"
      if [[ "${total}" == "0" ]]; then
        state="empty"
        workflow_note "run ${run_id} is empty (counts.total == 0); nothing to ingest"
      else
        ingest_step
        state="complete"
      fi
      ;;
    *) workflow_die "unexpected run state: ${state}" ;;
  esac
}

# C-2 stage of one order-plans day (spec §8): an empty run ends as
# empty_population; a complete run executes (or, when already executed, only
# draws the audit sample). Outcomes that later days would share end the track
# with exit 0.
c2_day() {
  local source_run_id
  if [[ "${state}" == "empty" ]]; then
    workflow_note "empty_population: ${run_id} has counts.total == 0; no C-2 execution"
    return 0
  fi
  # C-2 takes the canonical run id (the Run primary key), not the directory
  # name: the directory name only resolves in GET /api/runs/{id}, and the
  # execution POST answers 409 source_run_incomplete for it.
  workflow_lookup_run_row "${run_id}" \
    || workflow_die "no Run row for ${run_id} after ingest; C-2 cannot run without the canonical run id"
  workflow_require_single_run_row "${run_id}"
  source_run_id="${WORKFLOW_RUN_ROW_ID}"
  workflow_note "c2 source run: ${source_run_id} (directory ${run_id})"
  c2_run_source_run "${source_run_id}" "${C2_POLICY_VERSION}" daily
  workflow_note "C-2 stage for ${source_run_id} done: ${C2_OUTCOME}"
  if c2_outcome_stops_track "${C2_OUTCOME}"; then
    workflow_note "daily ${opt_track} track stopped at ${ref_date}: ${C2_OUTCOME} (normal skip)"
    exit 0
  fi
}

run_day() {
  set_day_context "$1"
  resolve_run_state "true"
  print_plan
  print_decision
  collect_and_ingest_day
  if [[ "${opt_track}" == "order-plans" ]]; then
    c2_day
  fi
  workflow_note "daily ${opt_track} track done for ${ref_date}: ${state} (${run_id})"
}

if [[ "${collect_only}" == "true" ]]; then
  set_day_context "${ref_dates[0]}"
  use_run "${base_run_id}-${run_suffix}"
  print_plan
  if [[ "${dry_run}" == "true" ]]; then
    workflow_require_command jq
    print_dry_run_collect
    exit 0
  fi
  workflow_require_command python3
  workflow_require_command jq
  collect_step
  workflow_note "collect-only run complete: ${run_id} (not ingested)"
  exit 0
fi

if [[ "${opt_track}" == "order-plans" ]]; then
  c2_validate_settings
fi

if [[ "${dry_run}" == "true" ]]; then
  workflow_require_command jq
  workflow_note "dry-run: skipping workflow_common_preflight (it requires a running web container)"
  workflow_note "dry-run: web lookup skipped (Run rows are not checked)"
  if [[ "${opt_track}" == "order-plans" ]]; then
    if [[ -z "${BIDOPS_C2_DAILY_ACTOR:-}" ]]; then
      workflow_note "BIDOPS_C2_DAILY_ACTOR is not set; a real run would not start"
    fi
    workflow_note "[dry-run] would check GET /api/order-plan-screening/daily-trigger once before any collection (effective_enabled=false -> daily_trigger_off, exit 0, nothing collected)"
  fi
  for day in "${ref_dates[@]}"; do
    set_day_context "${day}"
    resolve_run_state "false"
    print_plan
    print_decision
    print_dry_run_day
  done
  exit 0
fi

if [[ "${opt_track}" == "order-plans" ]]; then
  c2_require_actor
fi
workflow_common_preflight
if [[ "${opt_track}" == "order-plans" ]]; then
  # Checked once per invocation, before any collection (spec §8 자동 실행 확인):
  # while the trigger is off no order plan is collected without a verdict.
  c2_fetch_daily_trigger
  if [[ "${C2_TRIGGER_ENABLED}" != "true" ]]; then
    c2_print_trigger_off "${C2_TRIGGER_REASONS}"
    workflow_note "daily ${opt_track} track skipped: nothing collected"
    exit 0
  fi
  workflow_note "daily C-2 trigger on: policy ${C2_POLICY_VERSION}"
fi
for day in "${ref_dates[@]}"; do
  run_day "${day}"
done
if [[ "${range_mode}" == "true" ]]; then
  workflow_note "daily ${opt_track} track caught up: ${ref_dates[0]}..${ref_dates[-1]}"
fi
