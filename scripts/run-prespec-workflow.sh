#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/manual-workflow-common.sh
source "${SCRIPT_DIR}/manual-workflow-common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/run-prespec-workflow.sh <command> [options]

Commands:
  preflight       Check web, active C-1 policy, env files, and reference inputs.
  import-inputs   Import immutable deep-review profile/policy; does not edit .env.
  collect         Collect only pre-specifications into a new immutable run.
  ingest          Select a validation sample, copy it, ingest it, and refresh fetch eligibility.
  start-workers   Start C-1 web, attachment, document, and analysis workers.
  run-c1          Request C-1 full-run judgment; later stages continue asynchronously.
  enqueue         Enqueue overview work for one notice or eligible backfill.
  status          Show C-1, pre-spec, overview, and company-fit status.
  all             preflight -> collect -> ingest -> start-workers -> run-c1.
  stop-workers    Stop analysis and attachment workers without removing data.

Options:
  --run-id ID               Source run ID. Generated for collect/all if omitted.
  --from-date YYYY-MM-DD    Inclusive collection start (required by collect/all).
  --to-date YYYY-MM-DD      Exclusive collection end (required by collect/all).
  --actor NAME              Audit name required by import-inputs/run-c1.
  --c1-policy VERSION       Active C-1 policy; auto-detected when omitted.
  --notice-id ID            Exact notice for enqueue/status.
  --analysis-count N        Validation sample analysis count.
  --audit-count N           Validation sample audit count.
  --limit N                 Eligible overview backfill limit (default: 10).
  --model-env PATH          Model endpoint env for every purpose (default: env/model.env).
  --attachment-env PATH     Attachment egress env (default: env/prespec-attachment.env).
  --approve-model-call      Explicit approval for this invocation's live model work.
  -h, --help                Show this help.

Examples:
  scripts/run-prespec-workflow.sh import-inputs --actor '홍길동'
  scripts/run-prespec-workflow.sh all --from-date 2026-09-10 --to-date 2026-09-12 \
    --actor '홍길동' --approve-model-call
  scripts/run-prespec-workflow.sh status --notice-id 767
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
actor="${BIDOPS_REVIEWER:-}"
c1_policy=""
notice_id=""
analysis_count=""
audit_count=""
limit="10"
model_env="env/model.env"
attachment_env="env/prespec-attachment.env"
model_approved="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) run_id="${2:-}"; shift 2 ;;
    --from-date) from_date="${2:-}"; shift 2 ;;
    --to-date) to_date="${2:-}"; shift 2 ;;
    --actor) actor="${2:-}"; shift 2 ;;
    --c1-policy) c1_policy="${2:-}"; shift 2 ;;
    --notice-id) notice_id="${2:-}"; shift 2 ;;
    --analysis-count) analysis_count="${2:-}"; shift 2 ;;
    --audit-count) audit_count="${2:-}"; shift 2 ;;
    --limit) limit="${2:-}"; shift 2 ;;
    --model-env) model_env="${2:-}"; shift 2 ;;
    --attachment-env) attachment_env="${2:-}"; shift 2 ;;
    --approve-model-call) model_approved="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) workflow_die "unknown option: $1" ;;
  esac
done

if [[ -z "${run_id}" && ("${command_name}" == "collect" || "${command_name}" == "all") ]]; then
  run_id="prespecs-$(date +%Y%m%dT%H%M%S)"
fi

active_c1_policy() {
  curl --fail --silent --show-error "${BIDOPS_WORKFLOW_WEB_URL}/api/policies?status=active" \
    | jq -er '.active_policy_version // empty'
}

preflight() {
  workflow_common_preflight
  workflow_require_file "${model_env}"
  workflow_require_file "${attachment_env}"
  workflow_require_file docs/reference/company-profile.md
  workflow_require_file docs/reference/company-performance-titles.tsv
  workflow_require_file web/backend/app/screening/baseline_company_profile.md
  local detected_policy
  detected_policy="$(active_c1_policy || true)"
  [[ -n "${detected_policy}" ]] \
    || workflow_die "no active C-1 policy; activate an approved quality-gated policy first"
  workflow_note "active C-1 policy: ${detected_policy}"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose \
    --env-file .env --env-file "${model_env}" --env-file "${attachment_env}" \
    -f docker-compose.yml -f docker-compose.edge.yml \
    -f docker-compose.model-egress.yml -f docker-compose.prespec-attachment.yml \
    config -q
}

import_inputs() {
  workflow_common_preflight
  workflow_require_value "--actor" "${actor}"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.deep_review.cli import-profile-policy --actor "${actor}"
  workflow_note "copy the returned profile_version_id and policy_version_id into .env, then recreate web and analysis-worker"
}

collect() {
  workflow_require_value "--run-id" "${run_id}"
  workflow_require_value "--from-date" "${from_date}"
  workflow_require_value "--to-date" "${to_date}"
  local run_dir
  run_dir="$(workflow_run_dir "${run_id}")"
  workflow_check_new_run_dir "${run_dir}"
  workflow_note "collecting pre-specifications only into immutable run ${run_id}"
  python3 skills/bidops-collect/scripts/collect_notices.py \
    --from-date "${from_date}" --to-date "${to_date}" \
    --output-dir "${run_dir}" --skip-bids --timeout 300
  jq '{schema_version, metadata, counts}' "${run_dir}/collected-notices.json"
}

ingest() {
  workflow_common_preflight
  workflow_require_value "--run-id" "${run_id}"
  local run_dir sample_args=()
  run_dir="$(workflow_run_dir "${run_id}")"
  workflow_require_file "${run_dir}/collected-notices.json"
  [[ -z "${analysis_count}" || "${analysis_count}" =~ ^[0-9]+$ ]] \
    || workflow_die "--analysis-count must be a non-negative integer"
  [[ -z "${audit_count}" || "${audit_count}" =~ ^[0-9]+$ ]] \
    || workflow_die "--audit-count must be a non-negative integer"
  [[ -z "${analysis_count}" ]] || sample_args+=(--analysis-count "${analysis_count}")
  [[ -z "${audit_count}" ]] || sample_args+=(--audit-count "${audit_count}")
  if [[ ! -e "${run_dir}/validation-set.json" ]]; then
    python3 skills/bidops-collect/scripts/select_validation_sample.py \
      "${run_dir}/collected-notices.json" \
      --output "${run_dir}/validation-set.json" "${sample_args[@]}"
  else
    workflow_note "validation-set.json already exists; preserving it"
  fi
  workflow_copy_run_if_missing "${run_id}" "${run_dir}"
  workflow_ingest_run "${run_id}"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -c \
    'from app.core.db import SessionLocal; from app.deep_review.services.prespec_attachments import refresh_fetch_eligibility; s=SessionLocal(); print(refresh_fetch_eligibility(s)); s.commit(); s.close()'
}

start_workers() {
  workflow_require_model_approval "${model_approved}"
  workflow_require_file "${model_env}"
  workflow_require_file "${attachment_env}"
  workflow_note "starting C-1 web, document, attachment, overview, and company-fit workers"
  local resolved
  resolved="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose \
    --env-file .env --env-file "${model_env}" --env-file "${attachment_env}" \
    -f docker-compose.yml -f docker-compose.edge.yml \
    -f docker-compose.model-egress.yml -f docker-compose.prespec-attachment.yml \
    config --format json)"
  printf '%s\n' "${resolved}" | jq -e '
    .services.web.environment.BIDOPS_PRESPEC_OVERVIEW_ENABLED == "true" and
    .services.web.environment.BIDOPS_PRESPEC_COMPANY_FIT_ENABLED == "true" and
    .services.web.environment.BIDOPS_REFERENCE_WORKFLOW_MODE == "true" and
    (.services.web.environment.BIDOPS_ACTIVE_PROFILE_VERSION_ID | length > 0) and
    (.services.web.environment.BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID | length > 0) and
    (.services.web.environment.BIDOPS_PRESPEC_COMPANY_FIT_MODEL | length > 0) and
    .services["analysis-worker"].environment.BIDOPS_C2_EXECUTION_ALLOWED == "false"
  ' >/dev/null || workflow_die \
    "effective config must enable overview/company-fit/reference mode, set active profile/policy/model, and keep C-2 disabled"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose \
    --env-file .env --env-file "${model_env}" --env-file "${attachment_env}" \
    -f docker-compose.yml -f docker-compose.edge.yml \
    -f docker-compose.model-egress.yml -f docker-compose.prespec-attachment.yml \
    up -d web document-worker prespec-attachment-worker analysis-worker
  workflow_check_web
}

run_c1() {
  workflow_common_preflight
  workflow_require_model_approval "${model_approved}"
  workflow_require_value "--run-id" "${run_id}"
  workflow_require_value "--actor" "${actor}"
  if [[ -z "${c1_policy}" ]]; then
    c1_policy="$(active_c1_policy || true)"
  fi
  workflow_require_value "active C-1 policy or --c1-policy" "${c1_policy}"
  local response state_dir execution_id state_file
  response="$(jq -n --arg policy "${c1_policy}" \
    '{scope:"full_run",policy_version:$policy,profile_source:"current"}' \
    | curl --fail --silent --show-error -X POST \
      -H 'Content-Type: application/json' \
      -H "X-BidOps-Actor-Name: ${actor}" \
      --data-binary @- \
      "${BIDOPS_WORKFLOW_WEB_URL}/api/runs/${run_id}/pipeline/judgment")"
  printf '%s\n' "${response}" | jq .
  state_dir="reports/manual-workflows"
  mkdir -p "${state_dir}"
  execution_id="$(printf '%s\n' "${response}" | workflow_json_get '.execution_id')"
  state_file="${state_dir}/${run_id}.c1-${execution_id}.json"
  [[ ! -e "${state_file}" ]] || workflow_die "execution response already exists: ${state_file}"
  printf '%s\n' "${response}" >"${state_file}"
  workflow_note "saved the safe execution response to ${state_file}"
  workflow_note "C-1 is queued; attachment -> document -> overview -> company fit continues asynchronously"
}

enqueue_overview() {
  workflow_common_preflight
  workflow_require_model_approval "${model_approved}"
  if [[ -n "${notice_id}" ]]; then
    [[ "${notice_id}" =~ ^[1-9][0-9]*$ ]] || workflow_die "--notice-id must be a positive integer"
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
      exec -T web python -m app.deep_review.cli enqueue-overview --notice-id "${notice_id}"
    return
  fi
  [[ "${limit}" =~ ^[1-9][0-9]*$ ]] || workflow_die "--limit must be a positive integer"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.deep_review.cli prepare-overviews --all-eligible --limit "${limit}"
}

status() {
  workflow_common_preflight
  if [[ -n "${run_id}" ]]; then
    workflow_note "C-1 execution status for ${run_id}"
    curl --fail --silent --show-error --get \
      --data-urlencode "run_id=${run_id}" \
      "${BIDOPS_WORKFLOW_WEB_URL}/api/screening/executions" \
      | jq '{executions:[.items[]|{execution_id,status,candidate_count,completed_count,failure_count,published_run_id,error_summary,started_at,finished_at}]}'
  fi
  if [[ -n "${notice_id}" ]]; then
    [[ "${notice_id}" =~ ^[1-9][0-9]*$ ]] || workflow_die "--notice-id must be a positive integer"
    workflow_note "overview status for notice ${notice_id}"
    curl --fail --silent --show-error \
      "${BIDOPS_WORKFLOW_WEB_URL}/api/pre-specs/${notice_id}/overview" \
      | jq '{notice_id,current:(.current|if .==null then null else {id,status,reason_codes,call_count,created_at,completed_at} end)}'
    workflow_note "company-fit status for notice ${notice_id}"
    curl --fail --silent --show-error \
      "${BIDOPS_WORKFLOW_WEB_URL}/api/pre-specs/${notice_id}/company-fit" \
      | jq '{notice_id,automation_enabled,current}'
  fi
  if [[ -z "${run_id}" && -z "${notice_id}" ]]; then
    curl --fail --silent --show-error "${BIDOPS_WORKFLOW_WEB_URL}/api/pre-specs?limit=50" \
      | jq '{total,overview_status_counts,items:[.items[]|{notice_pk,title,grade,document,overview_review_status,auto_preparation_status,auto_preparation_reason,latest_deep_review_id}]}'
  fi
}

case "${command_name}" in
  help) usage ;;
  preflight) preflight ;;
  import-inputs) import_inputs ;;
  collect) collect ;;
  ingest) ingest ;;
  start-workers) start_workers ;;
  run-c1) run_c1 ;;
  enqueue) enqueue_overview ;;
  status) status ;;
  all)
    workflow_require_model_approval "${model_approved}"
    preflight
    collect
    ingest
    start_workers
    run_c1
    workflow_note "use status --run-id ${run_id}, then status --notice-id <id> to follow overview and company fit"
    ;;
  stop-workers)
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
      stop analysis-worker prespec-attachment-worker
    ;;
  *) usage >&2; workflow_die "unknown command: ${command_name}" ;;
esac
