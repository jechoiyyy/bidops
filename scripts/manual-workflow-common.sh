#!/usr/bin/env bash
set -euo pipefail

WORKFLOW_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_ROOT="$(cd -- "${WORKFLOW_SCRIPT_DIR}/.." && pwd)"
cd "${WORKFLOW_ROOT}"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bidops}"
workflow_default_web_port="${BIDOPS_WEB_PORT:-}"
if [[ -z "${workflow_default_web_port}" ]] && command -v docker >/dev/null 2>&1; then
  workflow_published_web="$(
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
      port web 8787 2>/dev/null || true
  )"
  if [[ "${workflow_published_web}" =~ :([0-9]+)$ ]]; then
    workflow_default_web_port="${BASH_REMATCH[1]}"
  fi
fi
if [[ -z "${workflow_default_web_port}" && -f "${WORKFLOW_ROOT}/.env" ]]; then
  workflow_default_web_port="$(
    awk -F= '$1 == "BIDOPS_WEB_PORT" { value=$2 } END { print value }' "${WORKFLOW_ROOT}/.env" \
      | tr -d '\r"' \
      | tr -d "'"
  )"
fi
[[ "${workflow_default_web_port}" =~ ^[0-9]+$ ]] || workflow_default_web_port="18787"
BIDOPS_WORKFLOW_WEB_URL="${BIDOPS_WORKFLOW_WEB_URL:-http://127.0.0.1:${workflow_default_web_port}}"

workflow_note() {
  printf '[bidops-workflow] %s\n' "$*"
}

workflow_die() {
  printf '[bidops-workflow] error: %s\n' "$*" >&2
  exit 2
}

workflow_require_command() {
  command -v "$1" >/dev/null 2>&1 || workflow_die "required command not found: $1"
}

workflow_require_file() {
  [[ -f "$1" && -r "$1" ]] || workflow_die "required readable file not found: $1"
}

workflow_require_value() {
  local name="$1"
  local value="$2"
  [[ -n "${value}" ]] || workflow_die "${name} is required"
}

workflow_validate_run_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$ ]] \
    || workflow_die "invalid run id: $1"
}

workflow_run_dir() {
  local run_id="$1"
  workflow_validate_run_id "${run_id}"
  printf '%s/data/runs/%s\n' "${WORKFLOW_ROOT}" "${run_id}"
}

workflow_check_new_run_dir() {
  local run_dir="$1"
  [[ ! -e "${run_dir}" ]] \
    || workflow_die "run directory already exists; choose a new run id: ${run_dir}"
}

# --- Run lookup (daily collection resume) -----------------------------------
# A date's run is lifecycle-<YYYYMMDD>-<plans|notices> or its -retry<N>
# recollections. Directories are only read here: an incomplete directory is
# never removed or overwritten; a new -retry<N> takes its place.

# Prints the existing run ids for a base run id, base first, then -retry<N>
# in ascending N. Symlinked entries are skipped (they are never ours).
workflow_run_candidates() {
  local base="$1" root="${WORKFLOW_ROOT}/data/runs" path name
  workflow_validate_run_id "${base}"
  if [[ -d "${root}/${base}" && ! -L "${root}/${base}" ]]; then
    printf '%s\n' "${base}"
  fi
  for path in "${root}/${base}"-retry*; do
    name="${path##*/}"
    [[ "${name}" =~ ^${base}-retry([1-9][0-9]*)$ ]] || continue
    [[ -d "${path}" && ! -L "${path}" ]] || continue
    printf '%s %s\n' "${BASH_REMATCH[1]}" "${name}"
  done | sort -n | awk '{ print $NF }'
}

# Prints the smallest N >= 1 for which <base>-retry<N> does not exist at all
# (a file, dangling symlink, or directory all occupy the name).
workflow_next_retry_number() {
  local base="$1" root="${WORKFLOW_ROOT}/data/runs" n=1
  workflow_validate_run_id "${base}"
  while [[ -e "${root}/${base}-retry${n}" || -L "${root}/${base}-retry${n}" ]]; do
    n=$((n + 1))
  done
  printf '%s\n' "${n}"
}

# Prints counts.total when the collected artifact in run_dir carries a true
# completion marker; prints nothing when the marker is missing, false,
# unreadable, or the total is not a non-negative integer.
#   plans:   collected-order-plans.json .metadata.collection.complete
#   notices: collection-provenance.json .complete (collected-notices.json has
#            no marker of its own), total from collected-notices.json
workflow_complete_collection_total() {
  local kind="$1" run_dir="$2" total_filter
  total_filter='.counts.total | select(type == "number" and . >= 0 and . == floor)'
  case "${kind}" in
    plans)
      [[ -f "${run_dir}/collected-order-plans.json" ]] || return 0
      jq -er "select(.metadata.collection.complete == true) | ${total_filter}" \
        "${run_dir}/collected-order-plans.json" 2>/dev/null || true
      ;;
    notices)
      [[ -f "${run_dir}/collection-provenance.json" && -f "${run_dir}/collected-notices.json" ]] \
        || return 0
      jq -e '.complete == true' "${run_dir}/collection-provenance.json" >/dev/null 2>&1 \
        || return 0
      jq -er "${total_filter}" "${run_dir}/collected-notices.json" 2>/dev/null || true
      ;;
    *) workflow_die "unknown collection kind: ${kind}" ;;
  esac
}

# Exit 0 when the web has a Run row for run_id (200), 1 when it does not
# (404). Any other answer, including no answer, stops the caller.
workflow_run_row_exists() {
  local run_id="$1" code
  workflow_validate_run_id "${run_id}"
  code="$(curl --connect-timeout 3 --max-time 10 --silent --show-error \
    --output /dev/null --write-out '%{http_code}' \
    "${BIDOPS_WORKFLOW_WEB_URL}/api/runs/${run_id}")" \
    || workflow_die "run lookup failed: ${BIDOPS_WORKFLOW_WEB_URL}/api/runs/${run_id}"
  case "${code}" in
    200) return 0 ;;
    404) return 1 ;;
    *) workflow_die "run lookup returned HTTP ${code}: ${BIDOPS_WORKFLOW_WEB_URL}/api/runs/${run_id}" ;;
  esac
}

workflow_check_web() {
  curl --connect-timeout 3 --max-time 10 --fail --silent --show-error \
    "${BIDOPS_WORKFLOW_WEB_URL}/api/health" >/dev/null \
    || workflow_die "web health check failed: ${BIDOPS_WORKFLOW_WEB_URL}/api/health"
}

workflow_copy_run_if_missing() {
  local run_id="$1"
  local run_dir="$2"
  if COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
      exec -T web test -e "/app/data/runs/${run_id}"; then
    workflow_note "container run directory already exists; preserving it and skipping copy: ${run_id}"
    return
  fi
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    cp "${run_dir}" web:/app/data/runs/
}

workflow_ingest_run() {
  local run_id="$1"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.lifecycle.ingest.cli --run "${run_id}"
}

workflow_require_model_approval() {
  local approved="$1"
  [[ "${approved}" == "true" ]] || workflow_die \
    "this action can send approved inputs to the configured model; rerun with --approve-model-call"
}

workflow_json_get() {
  local path="$1"
  jq -er "${path}"
}

workflow_common_preflight() {
  workflow_require_command curl
  workflow_require_command docker
  workflow_require_command jq
  workflow_require_command python3
  docker compose version >/dev/null
  workflow_check_web
}
