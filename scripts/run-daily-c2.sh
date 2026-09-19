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
  scripts/run-daily-c2.sh <order-plan run id> [--extra-attempt] [--dry-run]
  scripts/run-daily-c2.sh -h|--help

Runs the C-2 order-plan screening stage for one ingested order-plan run and
draws its audit sample (docs/0918_daily-operation/spec.md §8). The daily
order-plans track (scripts/run-daily-lifecycle.sh --track order-plans) runs the
same stage after ingest; this script runs it on its own.

The run id may be the run directory (lifecycle-<YYYYMMDD>-plans[-retry<N>]) or
the canonical run id the ingest loader keys the Run row by
(<directory>--<generated_at>Z). The C-2 API takes the canonical id only, so
this script always resolves it from the web before calling C-2.

  1 GET /api/order-plan-screening/daily-trigger. When effective_enabled is
    false, print daily_trigger_off with its reasons and exit 0. The policy
    version to execute with comes from this answer.
  2 A complete local collection with counts.total == 0 ends as
    empty_population (exit 0, no execution).
  3 GET /api/runs/<run directory> gives the canonical run id every later call
    uses. No Run row (404) or more than one Run row for the directory stops
    the script.
  4 Operational executions of the run decide the next step:
      성공/부분 성공 exists      -> already_executed; draw the audit sample
                                     if it is not drawn yet
      대기/실행 중/중지 요청 exists -> active_execution_exists (exit 0)
      only 실패/중단됨             -> wait BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS
                                     (default 600) and run attempt N+1;
                                     attempt > 2 -> retry_limit_reached (exit 0)
  5 POST the execution (X-BidOps-Trigger: daily_script), poll it to a
    terminal status, then POST the audit-sample draw.

Options:
  --extra-attempt     Human-requested extra attempt for a run past the retry
                      limit: one execution with X-BidOps-Trigger:
                      manual_resume, no automatic retry, no wait.
  --dry-run           Print the planned steps and requests; call nothing.
  -h, --help          Show this help.

Environment:
  BIDOPS_C2_DAILY_ACTOR                  required, no default. Claimed name
                                         for audit (not authentication).
  BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS     default 600.
  BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS   default 7200.
  BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS  default 30.

Exit 0 for success and the normal skips (daily_trigger_off, empty_population,
active_execution_exists, already_executed, retry_limit_reached, and a POST
answered with policy_not_active, daily_trigger_off, or 503). Anything else,
including a failed retry, a failed audit-sample draw (execution results are
kept), and an active execution older than twice
BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS, exits non-zero.
EOF
}

run_id=""
extra_attempt="false"
dry_run="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --extra-attempt) extra_attempt="true"; shift ;;
    --dry-run) dry_run="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; workflow_die "unknown option: $1" ;;
    *)
      [[ -z "${run_id}" ]] || workflow_die "only one run id is accepted: $1"
      run_id="$1"; shift ;;
  esac
done
[[ -n "${run_id}" ]] || { usage >&2; workflow_die "an order-plan run id is required"; }
# The run directory holds the collection artifact; the Run row is keyed by
# <directory>--<generated_at>Z. Accept either spelling and derive the other.
run_dir_name="$(workflow_run_directory_name "${run_id}")"
run_dir="$(workflow_run_dir "${run_dir_name}")"
mode="daily"
trigger="daily_script"
if [[ "${extra_attempt}" == "true" ]]; then
  mode="extra"
  trigger="manual_resume"
fi
c2_validate_settings

if [[ "${dry_run}" == "true" ]]; then
  workflow_note "dry-run: no web request is made"
  if [[ -z "${BIDOPS_C2_DAILY_ACTOR:-}" ]]; then
    workflow_note "BIDOPS_C2_DAILY_ACTOR is not set; a real run would not start"
  fi
  cat <<EOF
[dry-run] would run for ${run_dir_name} (mode ${mode}):
  GET  ${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/daily-trigger   (off -> daily_trigger_off, exit 0)
  empty_population check on ${run_dir}/collected-order-plans.json
  GET  ${BIDOPS_WORKFLOW_WEB_URL}/api/runs/${run_dir_name}   -> <canonical run id> = ${run_dir_name}--<generated_at>Z
       (the canonical id comes from the web; a dry run calls nothing, so it is
        not resolved here. Every call below uses it, not the directory name.)
  GET  ${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/executions?source_run_id=<canonical run id>&limit=500
  POST ${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/executions   X-BidOps-Trigger: ${trigger}
       request_id = uuidv5(${C2_REQUEST_NAMESPACE}, "<canonical run id>|<policy_version>|<attempt>")
  GET  ${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/executions/<id>   every ${C2_POLL_INTERVAL_SECONDS}s, up to ${C2_POLL_TIMEOUT_SECONDS}s
  POST ${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/executions/<id>/audit-sample   X-BidOps-Trigger: ${trigger}
EOF
  exit 0
fi

c2_require_actor
workflow_require_command curl
workflow_require_command jq
workflow_check_web

c2_fetch_daily_trigger
if [[ "${C2_TRIGGER_ENABLED}" != "true" ]]; then
  c2_print_trigger_off "${C2_TRIGGER_REASONS}"
  exit 0
fi

total="$(workflow_complete_collection_total plans "${run_dir}")"
if [[ "${total}" == "0" ]]; then
  workflow_note "empty_population: ${run_dir_name} has counts.total == 0; no C-2 execution"
  exit 0
fi

workflow_lookup_run_row "${run_dir_name}" \
  || workflow_die "no Run row for ${run_dir_name}; ingest the run first (ingest.cli --run ${run_dir_name} --collection)"
workflow_require_single_run_row "${run_dir_name}"
source_run_id="${WORKFLOW_RUN_ROW_ID}"
if [[ "${run_id}" != "${run_dir_name}" && "${run_id}" != "${source_run_id}" ]]; then
  workflow_die "the web resolves ${run_dir_name} to ${source_run_id}, not to the given ${run_id}; check the Run rows before choosing one"
fi
workflow_note "c2 source run: ${source_run_id} (directory ${run_dir_name})"

c2_run_source_run "${source_run_id}" "${C2_POLICY_VERSION}" "${mode}"
workflow_note "C-2 stage for ${source_run_id} done: ${C2_OUTCOME}"
