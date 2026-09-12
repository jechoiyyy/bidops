#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/manual-workflow-common.sh
source "${SCRIPT_DIR}/manual-workflow-common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/run-order-plan-workflow.sh <command> [options]

Commands:
  preflight       Check web health and the immutable C-2 Phase 0 binding.
  collect         Collect an immutable order-plan run on the host.
  ingest          Copy one collected run into web and ingest it.
  start-worker    Start the shared analysis worker with C-2 enabled.
  run             Enqueue one C-2 execution through the REST contract.
  status          Show C-2 executions for a source run.
  all             preflight -> collect -> ingest -> start-worker -> run.
  stop-worker     Stop the shared analysis worker without removing data.

Options:
  --run-id ID               Source run ID. Generated for collect/all if omitted.
  --from-date YYYY-MM-DD    Inclusive collection start.
  --to-date YYYY-MM-DD      Exclusive collection end; requires --from-date.
  --days N                  Recent-day window when explicit dates are omitted (default: 21).
  --actor NAME              Audit name required by run/all.
  --policy VERSION          Active C-2 policy (default: c2-order-plan-screening-v2).
  --model-env PATH          Model endpoint env file (default: env/model.env).
  --approve-model-call      Explicit approval for this invocation's live model work.
  -h, --help                Show this help.

Examples:
  scripts/run-order-plan-workflow.sh collect --days 3
  scripts/run-order-plan-workflow.sh all --days 3 --actor '홍길동' --approve-model-call
  scripts/run-order-plan-workflow.sh status --run-id order-plans-20260911T170000
EOF
}

command_name="${1:-help}"
if [[ "${command_name}" == "-h" || "${command_name}" == "--help" ]]; then
  command_name="help"
fi
[[ $# -eq 0 ]] || shift

run_id=""
from_date=""
to_date=""
days="21"
actor="${BIDOPS_REVIEWER:-}"
policy_version="c2-order-plan-screening-v2"
model_env="env/model.env"
model_approved="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) run_id="${2:-}"; shift 2 ;;
    --from-date) from_date="${2:-}"; shift 2 ;;
    --to-date) to_date="${2:-}"; shift 2 ;;
    --days) days="${2:-}"; shift 2 ;;
    --actor) actor="${2:-}"; shift 2 ;;
    --policy) policy_version="${2:-}"; shift 2 ;;
    --model-env) model_env="${2:-}"; shift 2 ;;
    --approve-model-call) model_approved="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) workflow_die "unknown option: $1" ;;
  esac
done

if [[ -z "${run_id}" && ("${command_name}" == "collect" || "${command_name}" == "all") ]]; then
  run_id="order-plans-$(date +%Y%m%dT%H%M%S)"
fi

preflight() {
  workflow_common_preflight
  workflow_note "checking the C-2 Phase 0 binding without calling external services"
  local output
  if ! output="$(python3 skills/bidops-screen/scripts/validate_order_plan_phase0.py --json)"; then
    printf '%s\n' "${output}"
    workflow_die "C-2 Phase 0 validation failed"
  fi
  printf '%s\n' "${output}" | jq .
  [[ "$(printf '%s\n' "${output}" | jq -r '.execution_allowed // false')" == "true" ]] \
    || workflow_die "C-2 Phase 0 does not allow execution"
}

collect() {
  workflow_require_value "--run-id" "${run_id}"
  workflow_validate_run_id "${run_id}"
  local run_dir
  run_dir="$(workflow_run_dir "${run_id}")"
  workflow_check_new_run_dir "${run_dir}"
  local args=(--output-dir "${run_dir}" --timeout 300)
  if [[ -n "${from_date}" || -n "${to_date}" ]]; then
    [[ -n "${from_date}" && -n "${to_date}" ]] \
      || workflow_die "--from-date and --to-date must be provided together"
    args+=(--from-date "${from_date}" --to-date "${to_date}")
  else
    [[ "${days}" =~ ^[1-9][0-9]*$ ]] || workflow_die "--days must be a positive integer"
    args+=(--days "${days}")
  fi
  workflow_note "collecting order plans into immutable run ${run_id}"
  python3 skills/bidops-collect/scripts/collect_order_plans.py "${args[@]}"
  jq '{schema_version, metadata, counts}' "${run_dir}/collected-order-plans.json"
}

ingest() {
  workflow_common_preflight
  workflow_require_value "--run-id" "${run_id}"
  local run_dir
  run_dir="$(workflow_run_dir "${run_id}")"
  workflow_require_file "${run_dir}/collected-order-plans.json"
  workflow_copy_run_if_missing "${run_id}" "${run_dir}"
  workflow_ingest_run "${run_id}"
}

start_worker() {
  workflow_require_model_approval "${model_approved}"
  workflow_require_file "${model_env}"
  workflow_note "validating and starting the C-2 analysis worker"
  local resolved
  resolved="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose \
    --env-file .env --env-file "${model_env}" \
    -f docker-compose.yml -f docker-compose.edge.yml \
    -f docker-compose.model-egress.yml -f docker-compose.c2-order-plan.yml \
    config --format json)"
  printf '%s\n' "${resolved}" | jq -e '
    .services.web.environment.BIDOPS_C2_EXECUTION_ALLOWED == "true" and
    .services["analysis-worker"].environment.BIDOPS_C2_EXECUTION_ALLOWED == "true" and
    .services["analysis-worker"].environment.BIDOPS_PRESPEC_OVERVIEW_ENABLED == "false" and
    .services["analysis-worker"].environment.BIDOPS_PRESPEC_COMPANY_FIT_ENABLED == "false"
  ' >/dev/null || workflow_die \
    "effective config must enable C-2 in web/analysis-worker and disable pre-spec overview/company fit"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose \
    --env-file .env --env-file "${model_env}" \
    -f docker-compose.yml -f docker-compose.edge.yml \
    -f docker-compose.model-egress.yml -f docker-compose.c2-order-plan.yml \
    up -d web analysis-worker
  workflow_check_web
}

enqueue_run() {
  workflow_common_preflight
  workflow_require_model_approval "${model_approved}"
  workflow_require_command uuidgen
  workflow_require_value "--run-id" "${run_id}"
  workflow_require_value "--actor" "${actor}"
  workflow_require_value "--policy" "${policy_version}"
  local request_id response state_dir execution_id state_file
  request_id="$(uuidgen)"
  response="$(jq -n \
    --arg request_id "${request_id}" \
    --arg source_run_id "${run_id}" \
    --arg policy_version "${policy_version}" \
    '{schema_version:"execution-create-request.v1",producer:"human-review-client",consumer:"screening-api",request_id:$request_id,source_run_id:$source_run_id,policy_version:$policy_version}' \
    | curl --fail --silent --show-error -X POST \
      -H 'Content-Type: application/json' \
      -H "X-BidOps-Actor-Name: ${actor}" \
      --data-binary @- \
      "${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/executions")"
  printf '%s\n' "${response}" | jq .
  state_dir="reports/manual-workflows"
  mkdir -p "${state_dir}"
  execution_id="$(printf '%s\n' "${response}" | workflow_json_get '.execution_id')"
  state_file="${state_dir}/${run_id}.c2-${execution_id}.json"
  [[ ! -e "${state_file}" ]] || workflow_die "execution response already exists: ${state_file}"
  printf '%s\n' "${response}" >"${state_file}"
  workflow_note "saved the safe execution response to ${state_file}"
}

status() {
  workflow_common_preflight
  workflow_require_value "--run-id" "${run_id}"
  curl --fail --silent --show-error --get \
    --data-urlencode "source_run_id=${run_id}" \
    --data-urlencode 'limit=20' \
    "${BIDOPS_WORKFLOW_WEB_URL}/api/order-plan-screening/executions" \
    | jq '{total,items:[.items[]|{execution_id,status,counts,partial_artifact,error_code,queued_at,started_at,finished_at}]}'
}

case "${command_name}" in
  help) usage ;;
  preflight) preflight ;;
  collect) collect ;;
  ingest) ingest ;;
  start-worker) start_worker ;;
  run) enqueue_run ;;
  status) status ;;
  all)
    preflight
    collect
    ingest
    start_worker
    enqueue_run
    workflow_note "C-2 is queued; use: scripts/run-order-plan-workflow.sh status --run-id ${run_id}"
    ;;
  stop-worker)
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml stop analysis-worker
    ;;
  *) usage >&2; workflow_die "unknown command: ${command_name}" ;;
esac
