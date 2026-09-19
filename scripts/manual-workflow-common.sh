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

# --- Canonical run identity -------------------------------------------------
# A run directory is `lifecycle-<YYYYMMDD>-<plans|notices>[-retry<N>]`, but the
# ingest loader keys the Run row by `<directory>--<generated_at>Z`
# (app/core/run_id.py deterministic_run_id, loader `_upsert_run`). Only
# `GET /api/runs/{id}` resolves a bare directory name to that row; every other
# API takes the primary key. C-2 in particular looks its source run up by
# primary key and answers 409 source_run_incomplete for a directory name
# (app/screening/services/order_plan_screening.py). So these scripts ask the
# web for the canonical id once and use it for every C-2 call.

WORKFLOW_HTTP_CODE=""
WORKFLOW_HTTP_BODY=""
# Canonical run id of the last successful workflow_lookup_run_row.
WORKFLOW_RUN_ROW_ID=""

# workflow_get PATH — sets WORKFLOW_HTTP_CODE and WORKFLOW_HTTP_BODY. A
# transport failure stops the caller.
workflow_get() {
  local path="$1" response
  response="$(curl --connect-timeout 3 --max-time 10 --silent --show-error \
    --write-out '\n%{http_code}' "${BIDOPS_WORKFLOW_WEB_URL}${path}")" \
    || workflow_die "request failed: GET ${BIDOPS_WORKFLOW_WEB_URL}${path}"
  WORKFLOW_HTTP_CODE="${response##*$'\n'}"
  if [[ "${response}" == *$'\n'* ]]; then
    WORKFLOW_HTTP_BODY="${response%$'\n'*}"
  else
    WORKFLOW_HTTP_BODY=""
  fi
}

# The directory a run id belongs to: a canonical id without its `--<stamp>Z`
# suffix (app/core/run_id.py RUN_ID_RE), or the id itself when it has none.
workflow_run_directory_name() {
  local run_id="$1"
  if [[ "${run_id}" =~ ^(.+)--[0-9]{8}T[0-9]{6}(\.[0-9]{1,6})?Z$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    printf '%s\n' "${run_id}"
  fi
}

# Exit 0 when the web has a Run row for the directory name (200), 1 when it
# does not (404). On 200 WORKFLOW_RUN_ROW_ID holds the canonical run id of that
# row. Any other answer, including no answer, stops the caller.
workflow_lookup_run_row() {
  local name="$1" canonical
  workflow_validate_run_id "${name}"
  WORKFLOW_RUN_ROW_ID=""
  workflow_get "/api/runs/${name}"
  case "${WORKFLOW_HTTP_CODE}" in
    200) ;;
    404) return 1 ;;
    *) workflow_die "run lookup returned HTTP ${WORKFLOW_HTTP_CODE}: ${BIDOPS_WORKFLOW_WEB_URL}/api/runs/${name}" ;;
  esac
  canonical="$(jq -er '.run_id // empty' <<<"${WORKFLOW_HTTP_BODY}")" \
    || workflow_die "run lookup for ${name} answered without a run_id"
  workflow_validate_run_id "${canonical}"
  [[ "$(workflow_run_directory_name "${canonical}")" == "${name}" ]] \
    || workflow_die "run lookup for ${name} resolved to another run directory: ${canonical}"
  WORKFLOW_RUN_ROW_ID="${canonical}"
  return 0
}

# Dies unless exactly one Run row belongs to this directory name. `GET
# /api/runs/{directory}` answers with the newest row and hides the others, so
# the count comes from the run list. Two rows mean the directory was ingested
# under two different `generated_at` values, which can only happen if the run
# artifact changed after the first ingest (the immutable-run rule forbids it).
# Which row C-2 should judge is then a human decision, not a guess.
workflow_require_single_run_row() {
  local name="$1" ids count
  workflow_validate_run_id "${name}"
  workflow_get "/api/runs"
  [[ "${WORKFLOW_HTTP_CODE}" == "200" ]] \
    || workflow_die "run list returned HTTP ${WORKFLOW_HTTP_CODE}: ${BIDOPS_WORKFLOW_WEB_URL}/api/runs"
  ids="$(jq -er --arg base "${name}" \
    '[.items[].run_id | select(. == $base or startswith($base + "--"))] | sort | join(" ")' \
    <<<"${WORKFLOW_HTTP_BODY}")" \
    || workflow_die "run list is not the expected JSON: ${BIDOPS_WORKFLOW_WEB_URL}/api/runs"
  count="$(wc -w <<<"${ids}")"
  case "${count}" in
    1) return 0 ;;
    0) workflow_die "the run list has no Run row for ${name} although the run lookup answered 200" ;;
    *) workflow_die "${count} Run rows belong to the directory ${name} (${ids}); the run artifact must have changed after the first ingest. Pick the run to judge by hand (scripts/run-daily-c2.sh <canonical run id>) after checking why." ;;
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
