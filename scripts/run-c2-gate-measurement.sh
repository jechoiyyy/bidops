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
  scripts/run-c2-gate-measurement.sh --policy-version <v> --gate-id <c2gate-...> \
      --pass 1|2 [--attempt N] [--dry-run]
  scripts/run-c2-gate-measurement.sh -h|--help

Runs one pass of a C-2 quality gate's measurement executions
(docs/0918_daily-operation/spec.md §4.1·§4.2) through the product path, in the
order the gate lists its measurement_run_ids, and prints the execution ids for
the person to paste into a quality-gates/{gate_id}/evaluations POST. It does
not score anything and does not record an evaluation.

  1 GET /api/order-plan-screening/quality-gates?policy_version=<v>, find the
    item whose gate_id matches --gate-id (none found -> exit non-zero), and
    take its measurement_run_ids in order.
  2 For each run id, POST an execution with X-BidOps-Trigger: gate_measurement
    and request_id = uuidv5(NAMESPACE,
    "gate-measurement|<gate_id>|pass<N>|attempt<A>|<run_id>"). A non-202
    answer prints the error body and stops (no skip: this is a
    person-initiated measurement, not the daily schedule).
  3 Poll the execution to a terminal status. Anything other than 성공
    (including 부분 성공, a hold reason under the gate's pass rule) prints the
    execution id and status and stops before the next run id.
  4 When every run id succeeds, print one JSON line on stdout:
    {"gate_id":…, "pass":N, "attempt":A,
     "executions":[{"source_run_id":…, "execution_id":…}, ...]}

Options:
  --policy-version V   Policy version to execute the measurement runs with.
  --gate-id ID         c2gate-<32 hex> gate to measure.
  --pass 1|2           Which of the gate's two required passes this is.
  --attempt N          Positive integer, default 1. Use a new attempt to
                        redo a pass after a failure; the same
                        (gate, pass, attempt, run) always maps to the same
                        request_id, so a rerun with the same arguments
                        replays the original 202 instead of creating a
                        second execution.
  --dry-run            Print the planned steps and, with --measurement-runs,
                        the request_id for each run id. Calls nothing.
  --measurement-runs a,b,c
                        Dry-run only: print each run's request_id without a
                        quality-gates lookup. Rejected outside --dry-run.
  -h, --help            Show this help.

Environment:
  BIDOPS_C2_GATE_ACTOR                   required, no default. Claimed name
                                         for audit (not authentication);
                                         distinct from BIDOPS_C2_DAILY_ACTOR
                                         because this is a person running a
                                         measurement, not the daily schedule.
  BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS   default 7200 (shared with the daily
                                         scripts' polling).
  BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS  default 30.

Exit 0 only when every run id in the pass reaches 성공. Anything else,
including a bad --gate-id/--pass/--attempt, a missing actor, a gate that is
not found for --policy-version, a non-202 execution create, and a run that
ends 부분 성공/실패/중단됨, exits non-zero.
EOF
}

# BIDOPS_C2_GATE_ACTOR is required and has no default. It is a claimed name
# for audit, not authentication, kept separate from BIDOPS_C2_DAILY_ACTOR
# because a gate measurement is run by a person, not the daily schedule.
# Mirrors c2_require_actor (scripts/c2-execution-common.sh) exactly, keyed to
# a different environment variable.
gate_require_actor() {
  local actor="${BIDOPS_C2_GATE_ACTOR:-}" encoded
  actor="${actor#"${actor%%[![:space:]]*}"}"
  actor="${actor%"${actor##*[![:space:]]}"}"
  [[ -n "${actor}" ]] \
    || workflow_die "BIDOPS_C2_GATE_ACTOR is required (the name of the person running this measurement); not starting"
  # Code points, not regex: oniguruma cannot hold NUL in a character class.
  jq -en --arg a "${actor}" \
    '($a | explode) as $c | ($c | length) <= 128
     and ($c | any(. < 32 or (. >= 127 and . <= 159)) | not)
     and ($a | ascii_downcase) != "system"' \
    >/dev/null || workflow_die "BIDOPS_C2_GATE_ACTOR is not a valid actor name"
  if jq -en --arg a "${actor}" '$a | explode | any(. > 127)' >/dev/null; then
    encoded="$(jq -rn --arg a "${actor}" '$a | @uri')"
    C2_ACTOR_HEADERS=(
      "X-BidOps-Actor-Name: UTF-8''${encoded}"
      "X-BidOps-Actor-Name-Format: utf-8-percent-v1"
    )
  else
    C2_ACTOR_HEADERS=("X-BidOps-Actor-Name: ${actor}")
  fi
}

# request_id = uuidv5(NAMESPACE, "gate-measurement|<gate_id>|pass<N>|attempt<A>|<run_id>")
gate_measurement_request_id() {
  local gate_id="$1" pass_num="$2" attempt="$3" run_id="$4"
  c2_uuid5 "gate-measurement|${gate_id}|pass${pass_num}|attempt${attempt}|${run_id}"
}

policy_version=""
gate_id=""
pass_num=""
attempt="1"
dry_run="false"
measurement_runs_arg=""
measurement_runs_given="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --policy-version) policy_version="${2:-}"; shift 2 ;;
    --gate-id) gate_id="${2:-}"; shift 2 ;;
    --pass) pass_num="${2:-}"; shift 2 ;;
    --attempt) attempt="${2:-}"; shift 2 ;;
    --dry-run) dry_run="true"; shift ;;
    --measurement-runs) measurement_runs_arg="${2:-}"; measurement_runs_given="true"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; workflow_die "unknown option: $1" ;;
  esac
done

workflow_require_value --policy-version "${policy_version}"
workflow_require_value --gate-id "${gate_id}"
workflow_require_value --pass "${pass_num}"
[[ "${gate_id}" =~ ^c2gate-[0-9a-f]{32}$ ]] \
  || workflow_die "--gate-id must match ^c2gate-[0-9a-f]{32}\$: ${gate_id}"
[[ "${pass_num}" == "1" || "${pass_num}" == "2" ]] \
  || workflow_die "--pass must be 1 or 2: ${pass_num}"
[[ "${attempt}" =~ ^[1-9][0-9]*$ ]] \
  || workflow_die "--attempt must be a positive integer: ${attempt}"
if [[ "${measurement_runs_given}" == "true" && "${dry_run}" != "true" ]]; then
  workflow_die "--measurement-runs is dry-run only"
fi
c2_validate_settings

if [[ "${dry_run}" == "true" ]]; then
  workflow_note "dry-run: no web request is made"
  if [[ -z "${BIDOPS_C2_GATE_ACTOR:-}" ]]; then
    workflow_note "BIDOPS_C2_GATE_ACTOR is not set; a real run would not start"
  fi
  workflow_note "[dry-run] gate ${gate_id} policy ${policy_version} pass ${pass_num} attempt ${attempt}"
  if [[ "${measurement_runs_given}" == "true" ]]; then
    IFS=',' read -r -a dry_run_ids <<<"${measurement_runs_arg}"
    for run_id in "${dry_run_ids[@]}"; do
      [[ -n "${run_id}" ]] || continue
      request_id="$(gate_measurement_request_id "${gate_id}" "${pass_num}" "${attempt}" "${run_id}")"
      workflow_note "[dry-run] would execute ${run_id} request_id=${request_id}"
    done
  else
    workflow_note "[dry-run] measurement run ids come from GET ${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/quality-gates?policy_version=${policy_version}"
  fi
  exit 0
fi

gate_require_actor
workflow_require_command curl
workflow_require_command jq
workflow_check_web

c2_request GET "/api/order-plan-screening/quality-gates?policy_version=${policy_version}" ""
[[ "${C2_HTTP_CODE}" == "200" ]] || c2_die_http "quality-gates lookup for ${policy_version}"
run_ids_json="$(jq -c --arg gid "${gate_id}" \
  '[.items[]? | select(.gate_id == $gid)][0].measurement_run_ids // empty' <<<"${C2_HTTP_BODY}")"
[[ -n "${run_ids_json}" && "${run_ids_json}" != "null" ]] \
  || workflow_die "gate ${gate_id} not found for policy_version ${policy_version}"

executions_json="[]"
while IFS= read -r run_id; do
  request_id="$(gate_measurement_request_id "${gate_id}" "${pass_num}" "${attempt}" "${run_id}")"
  body="$(jq -nc --arg rid "${request_id}" --arg run "${run_id}" --arg pv "${policy_version}" \
    '{schema_version: "execution-create-request.v1", producer: "human-review-client",
      consumer: "screening-api", request_id: $rid, source_run_id: $run, policy_version: $pv}')"
  workflow_note "gate-measurement: requesting execution for ${run_id} (gate ${gate_id}, pass ${pass_num}, attempt ${attempt}, request_id ${request_id})"
  c2_request POST /api/order-plan-screening/executions "${body}" \
    "${C2_ACTOR_HEADERS[@]}" "X-BidOps-Trigger: gate_measurement"
  [[ "${C2_HTTP_CODE}" == "202" ]] || c2_die_http "execution create for ${run_id}"
  execution_id="$(jq -er '.execution_id' <<<"${C2_HTTP_BODY}")" \
    || workflow_die "execution create response has no execution_id"
  workflow_note "gate-measurement: execution ${execution_id} queued for ${run_id}"

  c2_poll_execution "${execution_id}"
  if [[ "${C2_EXECUTION_STATUS}" != "성공" ]]; then
    workflow_die "execution ${execution_id} for ${run_id} ended ${C2_EXECUTION_STATUS}; gate measurement stops (no further run id is executed)"
  fi
  executions_json="$(jq -cn --argjson arr "${executions_json}" --arg run "${run_id}" --arg eid "${execution_id}" \
    '$arr + [{source_run_id: $run, execution_id: $eid}]')"
done < <(jq -r '.[]' <<<"${run_ids_json}")

jq -nc --arg gid "${gate_id}" --argjson pass "${pass_num}" --argjson attempt "${attempt}" --argjson execs "${executions_json}" \
  '{gate_id: $gid, pass: $pass, attempt: $attempt, executions: $execs}'
