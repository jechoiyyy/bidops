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
  scripts/run-daily-lifecycle.sh --track <order-plans|notices> [--date YYYY-MM-DD] [--catch-up-days N] [--dry-run]
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
  --catch-up-days N   Before the reference day, process the missing days
                      (no complete run directory, see "Gap check") among the
                      N days before it, oldest first, each resumed stage by
                      stage as above; then the reference day. On the
                      order-plans track the unjudged days of that window join
                      too (only their missing stages run), except days held
                      by an active execution or with several Run rows. Default 0 (only
                      the reference day). N must not exceed
                      BIDOPS_DAILY_GAP_LOOKBACK_DAYS; days before
                      BIDOPS_DAILY_GAP_FLOOR_DATE are not caught up. Not
                      combinable with --from-date/--to-date or --collect-only.
                      The first failing day stops the track as above.
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
                      canonical run id C-2 needs is not resolved. The
                      catch-up days are listed with their decisions, and the
                      gap check prints the days a real run would still report
                      ("[dry-run] would report: gap_detected ...") and the
                      exit code it would end with; a dry run itself exits 0.
  -h, --help          Show this help.

Gap check (both tracks): after the day's own work (and any catch-up days) the
script looks at the reference day (the last day of a range) and the
BIDOPS_DAILY_GAP_LOOKBACK_DAYS days before it. A day counts as present when it
has a run directory (base or -retry<N>) whose collection is marked complete,
an empty one included; only local directories are read. Days before
BIDOPS_DAILY_GAP_FLOOR_DATE are not counted. Each missing day prints
  gap_detected track=<track> date=YYYY-MM-DD
and the script then exits 10 (see Exit). Fill a gap with --from-date/--to-date
or --catch-up-days, or acknowledge an outage with BIDOPS_DAILY_GAP_FLOOR_DATE.
On the order-plans track a complete, non-empty day of the window (the days
this invocation processed included) without a 성공/부분 성공 operational C-2
execution prints
  unjudged_detected track=order-plans date=YYYY-MM-DD run=<dir> reason=<r>
with r = not_ingested | multiple_run_rows:<n> | active:<status> |
last:<status> | no_execution, and also exits 10. This reads the web
(GET /api/runs/<dir> for the canonical id, GET /api/runs for the row count,
the executions list by canonical id); a failed read stops the script with a
failure code, never as "no gap". A dry run reads no web and only says it
would check judged state.
A failing day exits with its own failure code before the gap check. The
order-plans track that ends at daily_trigger_off (nothing collected) does not
run the gap check.

Environment (both tracks):
  BIDOPS_DAILY_GAP_LOOKBACK_DAYS         default 7; 0 disables the gap check.
  BIDOPS_DAILY_GAP_FLOOR_DATE            optional YYYY-MM-DD; earlier days are
                                         neither reported nor caught up.

Environment (order-plans track):
  BIDOPS_C2_DAILY_ACTOR                  required, no default; not needed for
                                         --collect-only or --dry-run.
  BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS     default 600.
  BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS   default 7200.
  BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS  default 30.

Exit:
Exit 0 for success and the normal skips (daily_trigger_off, empty_population,
active_execution_exists, already_executed, retry_limit_reached, and an
execution POST answered with policy_not_active, daily_trigger_off, or 503).
An active execution that has been queued or running for more than twice
BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS is not a normal skip: it is printed with
its id, status and age and exits non-zero so somebody looks at the worker.
daily_trigger_off, policy_not_active, 503, and active_execution_exists end the
track there (later days of a range would get the same answer); the other skips
continue with the next day. The gap check still runs after a skip that ends
the track (except daily_trigger_off before collection).
Exit 10 means attention needed (gap_detected and/or unjudged_detected): every
day this invocation processed ended in success or a normal skip, and at least
one day of the gap window is missing or, on order-plans, unjudged. The
summary line counts both.
Real failures exit with another non-zero code (2 for the script's own checks,
or the failing command's code).

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
opt_catch_up=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date) opt_date="${2:-}"; shift 2 ;;
    --catch-up-days) opt_catch_up="${2:-}"; shift 2 ;;
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

# Gap check and catch-up settings (docs/operations/daily.md "누락일 감지").
# Validated before any call so a bad value never half-runs a day.
gap_lookback_days="${BIDOPS_DAILY_GAP_LOOKBACK_DAYS:-7}"
[[ "${gap_lookback_days}" =~ ^[0-9]+$ ]] \
  || workflow_die "BIDOPS_DAILY_GAP_LOOKBACK_DAYS must be a non-negative integer: ${gap_lookback_days}"
gap_lookback_days=$((10#${gap_lookback_days}))
gap_floor_date=""
if [[ -n "${BIDOPS_DAILY_GAP_FLOOR_DATE:-}" ]]; then
  gap_floor_date="$(canonical_date BIDOPS_DAILY_GAP_FLOOR_DATE "${BIDOPS_DAILY_GAP_FLOOR_DATE}")"
fi
catch_up_days=0
if [[ -n "${opt_catch_up}" ]]; then
  [[ "${opt_catch_up}" =~ ^[0-9]+$ ]] \
    || workflow_die "--catch-up-days must be a non-negative integer: ${opt_catch_up}"
  catch_up_days=$((10#${opt_catch_up}))
  [[ "${range_mode}" != "true" ]] \
    || workflow_die "--catch-up-days cannot be combined with --from-date/--to-date"
  [[ "${collect_only}" != "true" ]] \
    || workflow_die "--catch-up-days cannot be combined with --collect-only"
  (( catch_up_days <= gap_lookback_days )) \
    || workflow_die "--catch-up-days (${catch_up_days}) must not exceed BIDOPS_DAILY_GAP_LOOKBACK_DAYS (${gap_lookback_days})"
fi
# Exit code that means only "gap_detected" (every processed day succeeded or
# ended in a normal skip). Distinct from workflow_die (2) and command failures.
GAP_EXIT_CODE=10

case "${opt_track}" in
  order-plans) track_kind="plans" ;;
  notices) track_kind="notices" ;;
esac

# The day's run: the first directory (base, then -retry<N> ascending) whose
# collection is marked complete, as resolve_run_state picks it. Sets
# DAY_RUN_ID and DAY_RUN_TOTAL (counts.total) and exits 0; exits 1 when the day
# has no such directory. Reads local directories only.
DAY_RUN_ID=""
DAY_RUN_TOTAL=""
day_complete_run() {
  local day="$1" base candidate total
  base="lifecycle-$(date -d "${day}" +%Y%m%d)-${track_kind}"
  DAY_RUN_ID=""
  DAY_RUN_TOTAL=""
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    total="$(workflow_complete_collection_total "${track_kind}" "$(workflow_run_dir "${candidate}")")"
    if [[ -n "${total}" ]]; then
      DAY_RUN_ID="${candidate}"
      DAY_RUN_TOTAL="${total}"
      return 0
    fi
  done < <(workflow_run_candidates "${base}")
  return 1
}

# Exit 0 when the day has a complete run directory, an empty one included.
day_has_complete_run() {
  day_complete_run "$1"
}

# Order-plans only, reads the web. Exit 0 when the day's complete, non-empty
# run has no 성공/부분 성공 operational C-2 execution — the same "done" the
# per-day resume uses before it decides to execute (c2_run_source_run counts a
# success of any policy version) — and sets DAY_UNJUDGED_REASON:
#   not_ingested           no Run row for the directory (GET /api/runs/<dir> 404)
#   multiple_run_rows:<n>  more than one Run row; which one to judge is a human call
#   active:<status>        a 대기/실행 중/중지 요청 execution holds it
#   last:<status>          only failed/stopped executions (newest by queued_at)
#   no_execution           no operational execution at all
# The executions list is read with the canonical run id only. Any web answer
# other than the expected ones stops the script (workflow_die), so a read
# failure never reads as "judged".
DAY_UNJUDGED_REASON=""
day_unjudged() {
  local day="$1" canonical
  DAY_UNJUDGED_REASON=""
  day_complete_run "${day}" || return 1
  [[ "${DAY_RUN_TOTAL}" != "0" ]] || return 1
  if ! workflow_lookup_run_row "${DAY_RUN_ID}"; then
    DAY_UNJUDGED_REASON="not_ingested"
    return 0
  fi
  canonical="${WORKFLOW_RUN_ROW_ID}"
  workflow_count_run_rows "${DAY_RUN_ID}"
  case "${WORKFLOW_RUN_ROW_COUNT}" in
    1) ;;
    0) workflow_die "the run list has no Run row for ${DAY_RUN_ID} although the run lookup answered 200" ;;
    *)
      DAY_UNJUDGED_REASON="multiple_run_rows:${WORKFLOW_RUN_ROW_COUNT}"
      return 0
      ;;
  esac
  c2_list_run_executions "${canonical}"
  if jq -e 'any(.[]; .status == "성공" or .status == "부분 성공")' <<<"${C2_RUN_EXECUTIONS}" >/dev/null; then
    return 1
  fi
  DAY_UNJUDGED_REASON="$(jq -r '
    ([.[] | select(.status == "대기" or .status == "실행 중" or .status == "중지 요청")] | first | .status) as $active
    | if $active then "active:" + $active
      elif length > 0 then "last:" + (sort_by(.queued_at // "") | last | .status)
      else "no_execution" end' <<<"${C2_RUN_EXECUTIONS}")" \
    || workflow_die "execution list for ${canonical} is not the expected JSON"
  return 0
}

# True when the day is before BIDOPS_DAILY_GAP_FLOOR_DATE.
day_before_floor() {
  [[ -n "${gap_floor_date}" && "$1" < "${gap_floor_date}" ]]
}

# --catch-up-days N: the missing days among the N days before the reference
# day run first, oldest first, then the reference day itself. In a real
# order-plans run (mode=real, after the trigger check) an unjudged day joins
# too, so the per-day resume runs only its missing C-2 stage; days held by an
# active execution or with more than one Run row are left to the gap report
# (resuming them would only skip or stop). mode=dry reads no web: missing days
# only.
select_catch_up_dates() {
  local mode="$1" n day catch_up_dates=()
  (( catch_up_days > 0 )) || return 0
  for (( n = catch_up_days; n >= 1; n-- )); do
    day="$(date -d "${ref_dates[0]} -${n} days" +%Y-%m-%d)"
    if day_before_floor "${day}"; then
      continue
    fi
    if day_has_complete_run "${day}"; then
      [[ "${mode}" == "real" && "${opt_track}" == "order-plans" ]] || continue
      day_unjudged "${day}" || continue
      case "${DAY_UNJUDGED_REASON}" in
        active:*|multiple_run_rows:*) continue ;;
      esac
    fi
    catch_up_dates+=("${day}")
  done
  ref_dates=(${catch_up_dates[@]+"${catch_up_dates[@]}"} "${ref_dates[@]}")
}

# True when this invocation processes (or, in a dry run, would process) the day.
day_is_planned() {
  local planned
  for planned in "${ref_dates[@]}"; do
    [[ "${planned}" != "$1" ]] || return 0
  done
  return 1
}

# Gap check (A-3, findings W-3·W-4·W-5). Looks at the last processed day and
# the BIDOPS_DAILY_GAP_LOOKBACK_DAYS days before it, minus days before the
# floor. A day without a complete run directory prints gap_detected; on the
# order-plans track a complete, non-empty day without a judged result
# (day_unjudged, web reads) prints unjudged_detected — the days processed by
# this invocation included, so a normal skip today surfaces today. Either kind
# ends the run with GAP_EXIT_CODE. mode=dry reads no web: it skips the days this
# invocation would process (a real run handles them first or fails), does not
# check judged state, and only says which exit code a real run would end with.
gap_check() {
  local mode="$1" anchor first="" day n missing=0 unjudged=0 prefix=""
  anchor="${ref_dates[${#ref_dates[@]}-1]}"
  [[ "${mode}" != "dry" ]] || prefix="[dry-run] "
  if (( gap_lookback_days == 0 )); then
    workflow_note "${prefix}gap check: disabled (BIDOPS_DAILY_GAP_LOOKBACK_DAYS=0)"
    return 0
  fi
  for (( n = gap_lookback_days; n >= 0; n-- )); do
    day="$(date -d "${anchor} -${n} days" +%Y-%m-%d)"
    if day_before_floor "${day}"; then
      continue
    fi
    [[ -n "${first}" ]] || first="${day}"
    if [[ "${mode}" == "dry" ]] && day_is_planned "${day}"; then
      continue
    fi
    if day_has_complete_run "${day}"; then
      if [[ "${mode}" == "real" && "${opt_track}" == "order-plans" ]] && day_unjudged "${day}"; then
        unjudged=$((unjudged + 1))
        workflow_note "unjudged_detected track=${opt_track} date=${day} run=${DAY_RUN_ID} reason=${DAY_UNJUDGED_REASON}"
      fi
      continue
    fi
    missing=$((missing + 1))
    if [[ "${mode}" == "dry" ]]; then
      workflow_note "[dry-run] would report: gap_detected track=${opt_track} date=${day}"
    else
      workflow_note "gap_detected track=${opt_track} date=${day}"
    fi
  done
  if [[ "${mode}" == "dry" && "${opt_track}" == "order-plans" ]]; then
    workflow_note "[dry-run] a real run would also check judged state: every complete, non-empty run in the window (the days above included) needs a 성공/부분 성공 C-2 execution (GET /api/runs/<dir>, GET /api/runs, executions list by canonical id); otherwise unjudged_detected and exit ${GAP_EXIT_CODE}. Not read here."
  fi
  if [[ -z "${first}" ]]; then
    workflow_note "${prefix}gap check: no gap; no day on or after the floor ${gap_floor_date} up to ${anchor}"
    return 0
  fi
  if (( missing == 0 && unjudged == 0 )); then
    workflow_note "${prefix}gap check: no gap for ${opt_track} in ${first}..${anchor}${gap_floor_date:+ (floor ${gap_floor_date})}"
    return 0
  fi
  if [[ "${mode}" == "dry" ]]; then
    workflow_note "[dry-run] gap check: ${missing} missing day(s) for ${opt_track} in ${first}..${anchor}; a real run would exit ${GAP_EXIT_CODE} (gap_detected)"
    return 0
  fi
  workflow_note "gap check: ${missing} missing, ${unjudged} unjudged day(s) for ${opt_track} in ${first}..${anchor}${gap_floor_date:+ (floor ${gap_floor_date})}; exit ${GAP_EXIT_CODE} (attention needed; every processed day ended in success or a normal skip). Fill missing days with --from-date/--to-date or --catch-up-days, resume unjudged days with --date (or scripts/run-daily-c2.sh <run>), or acknowledge an outage with BIDOPS_DAILY_GAP_FLOOR_DATE."
  exit "${GAP_EXIT_CODE}"
}

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

  scripts/compose.sh cp ${run_dir} web:/app/data/runs/
  scripts/compose.sh exec -T web python -m app.lifecycle.ingest.cli --run ${run_id} --collection
  scripts/compose.sh exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill
EOF
  if [[ "${opt_track}" == "notices" ]]; then
    cat <<EOF
  scripts/compose.sh exec -T web python -c \\
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
  result="$("${WORKFLOW_SCRIPT_DIR}/compose.sh" \
    exec -T web python -m app.lifecycle.ingest.cli --run "${run_id}" --collection)"
  print_result "order-plan ingest" "${result}"

  workflow_note "running tracked backfill"
  result="$("${WORKFLOW_SCRIPT_DIR}/compose.sh" \
    exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill)"
  print_result "tracked backfill" "${result}"
}

ingest_notices_step() {
  workflow_copy_run_if_missing "${run_id}" "${run_dir}"

  local result
  workflow_note "ingesting notice run ${run_id} (--collection)"
  result="$("${WORKFLOW_SCRIPT_DIR}/compose.sh" \
    exec -T web python -m app.lifecycle.ingest.cli --run "${run_id}" --collection)"
  print_result "notice ingest" "${result}"

  workflow_note "running tracked backfill"
  result="$("${WORKFLOW_SCRIPT_DIR}/compose.sh" \
    exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill)"
  print_result "tracked backfill" "${result}"

  workflow_note "refreshing attachment fetch eligibility"
  "${WORKFLOW_SCRIPT_DIR}/compose.sh" \
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

# Set by c2_day when an outcome later days would share ends the track (a
# normal skip). The day loop stops there; the gap check still runs.
track_stopped=""

# C-2 stage of one order-plans day (spec §8): an empty run ends as
# empty_population; a complete run executes (or, when already executed, only
# draws the audit sample). Outcomes that later days would share end the track
# (track_stopped); without a gap the invocation then exits 0.
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
    track_stopped="${C2_OUTCOME}"
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
    [[ -z "${track_stopped}" ]] || return 0
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
    workflow_note "[dry-run] would check GET /api/order-plan-screening/daily-trigger once before any collection (effective_enabled=false -> daily_trigger_off, exit 0, nothing collected, no gap check)"
  fi
  if (( catch_up_days > 0 )); then
    select_catch_up_dates dry
    workflow_note "[dry-run] catch-up: $(( ${#ref_dates[@]} - 1 )) missing day(s) within ${catch_up_days} day(s) before ${ref_dates[${#ref_dates[@]}-1]} run first"
    if [[ "${opt_track}" == "order-plans" ]]; then
      workflow_note "[dry-run] a real run would also catch up unjudged days of that window (judged state is not read here)"
    fi
  fi
  for day in "${ref_dates[@]}"; do
    set_day_context "${day}"
    resolve_run_state "false"
    print_plan
    print_decision
    print_dry_run_day
  done
  gap_check dry
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
if (( catch_up_days > 0 )); then
  # After the preflight and, for order-plans, the trigger check: the
  # unjudged-day selection reads the web.
  select_catch_up_dates real
  workflow_note "catch-up: $(( ${#ref_dates[@]} - 1 )) missing or unjudged day(s) within ${catch_up_days} day(s) before ${ref_dates[${#ref_dates[@]}-1]} run first"
fi
for day in "${ref_dates[@]}"; do
  run_day "${day}"
  [[ -z "${track_stopped}" ]] || break
done
if [[ -z "${track_stopped}" && "${range_mode}" == "true" ]]; then
  workflow_note "daily ${opt_track} track caught up: ${ref_dates[0]}..${ref_dates[${#ref_dates[@]}-1]}"
fi
gap_check real
