#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/manual-workflow-common.sh
source "${SCRIPT_DIR}/manual-workflow-common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/run-daily-lifecycle.sh --track <order-plans|notices> [--date YYYY-MM-DD] [--dry-run]
  scripts/run-daily-lifecycle.sh --track <order-plans|notices> --collect-only --run-suffix NAME [--date YYYY-MM-DD] [--dry-run]
  scripts/run-daily-lifecycle.sh -h|--help

Runs one day of collection and selective ingest for a single track (the
order-plans and notices tracks are independent; run each on its own
schedule):
  order-plans track: preflight -> order-plan collection (1-day window,
    [reference day, reference day + 1), exclusive end) -> ingest
    (--collection) -> --tracked-backfill. Run id lifecycle-<YYYYMMDD>-plans.
    C-2 screening is not wired into the order-plans track yet; do not
    schedule that track until it is (decision 10, docs/0918_daily-operation).
  notices track (pre-specs + bids, tagged with 1468 SW-industry status):
    preflight -> notice collection (1-day window, both ends inclusive) ->
    ingest (--collection) -> --tracked-backfill -> attachment
    fetch-eligibility refresh. Run id lifecycle-<YYYYMMDD>-notices.

Options:
  --track order-plans|notices
                      Which track to run this invocation (required, no
                      default).
  --date YYYY-MM-DD   Reference day in Asia/Seoul (default: yesterday, KST).
  --collect-only      Collect only; skip preflight and ingest entirely.
                      Requires --run-suffix so it does not occupy the daily
                      run id.
  --run-suffix NAME   Suffix appended to the run id. Only valid with
                      --collect-only. Lowercase alphanumeric/hyphen
                      (1-40 chars, starts with alphanumeric); must not be
                      retry<N> (reserved for recollection).
  --dry-run           Print the computed run id, window, and the exact
                      commands for the selected track; do not collect,
                      ingest, or touch Docker.
  -h, --help          Show this help.

Safety:
  - Stops on the first failure (no partial silent continuation).
  - Never overwrites an existing immutable run directory.
  - Never deletes anything and never installs cron; the scheduler stays
    disabled by default (see CLAUDE.md). No model calls are made.
EOF
}

opt_date=""
opt_track=""
dry_run="false"
collect_only="false"
run_suffix=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date) opt_date="${2:-}"; shift 2 ;;
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

if [[ -n "${opt_date}" ]]; then
  [[ "${opt_date}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
    || workflow_die "--date must be YYYY-MM-DD: ${opt_date}"
  ref_date="${opt_date}"
else
  ref_date="$(TZ=Asia/Seoul date -d 'yesterday' +%Y-%m-%d)"
fi
# Canonicalize and reject invalid calendar dates (GNU date rejects e.g. 2026-02-30).
ref_date="$(date -d "${ref_date}" +%Y-%m-%d 2>/dev/null)" \
  || workflow_die "invalid --date value: ${opt_date}"
ref_compact="$(date -d "${ref_date}" +%Y%m%d)"

case "${opt_track}" in
  order-plans) track_kind="plans" ;;
  notices) track_kind="notices" ;;
esac

run_id="lifecycle-${ref_compact}-${track_kind}"
if [[ -n "${run_suffix}" ]]; then
  run_id="${run_id}-${run_suffix}"
fi
run_dir="$(workflow_run_dir "${run_id}")"

# Both tracks now cover exactly the reference day (1 day). collect_order_plans.py
# --to-date is exclusive; collect_notices.py --to-date is inclusive.
if [[ "${opt_track}" == "order-plans" ]]; then
  from_date="${ref_date}"
  to_date="$(date -d "${ref_date} +1 day" +%Y-%m-%d)"
else
  from_date="${ref_date}"
  to_date="${ref_date}"
fi

print_plan() {
  workflow_note "track: ${opt_track}"
  workflow_note "reference day (KST): ${ref_date}"
  workflow_note "run: ${run_id}"
  if [[ "${opt_track}" == "order-plans" ]]; then
    workflow_note "  window: --from-date ${from_date} --to-date ${to_date} (half-open, exclusive end; 1 day: ${ref_date})"
  else
    workflow_note "  window: --from-date ${from_date} --to-date ${to_date} (closed, inclusive both ends; 1 day: ${ref_date})"
  fi
  workflow_note "  dir:    ${run_dir}"
  if [[ "${collect_only}" == "true" ]]; then
    workflow_note "mode: collect-only (no preflight, no ingest)"
  fi
}

print_dry_run_commands() {
  if [[ "${opt_track}" == "order-plans" ]]; then
    cat <<EOF
[dry-run] would run:
  python3 skills/bidops-collect/scripts/collect_order_plans.py \\
    --from-date ${from_date} --to-date ${to_date} \\
    --output-dir ${run_dir} --timeout 300
  jq '{schema_version, metadata, counts}' ${run_dir}/collected-order-plans.json
EOF
    if [[ "${collect_only}" != "true" ]]; then
      cat <<EOF

  docker compose -f docker-compose.yml cp ${run_dir} web:/app/data/runs/
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --run ${run_id} --collection
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill
EOF
    fi
  else
    cat <<EOF
[dry-run] would run:
  python3 skills/bidops-collect/scripts/collect_notices.py \\
    --from-date ${from_date} --to-date ${to_date} \\
    --output-dir ${run_dir} --timeout 300 --tag-bid-sw-industry
  jq '{schema_version, counts, sw_industry_1468: (.metadata.sw_industry_1468 // null)}' ${run_dir}/collected-notices.json
EOF
    if [[ "${collect_only}" != "true" ]]; then
      cat <<EOF

  docker compose -f docker-compose.yml cp ${run_dir} web:/app/data/runs/
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --run ${run_id} --collection
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill
  docker compose -f docker-compose.yml exec -T web python -c \\
    'from app.core.db import SessionLocal; from app.deep_review.services.prespec_attachments import refresh_fetch_eligibility; s=SessionLocal(); print(refresh_fetch_eligibility(s)); s.commit()'
EOF
    fi
  fi
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

print_plan

if [[ "${dry_run}" == "true" ]]; then
  workflow_require_command jq
  workflow_note "dry-run: skipping workflow_common_preflight (it requires a running web container)"
  print_dry_run_commands
  exit 0
fi

if [[ "${collect_only}" == "true" ]]; then
  workflow_require_command python3
  workflow_require_command jq
  if [[ "${opt_track}" == "order-plans" ]]; then
    collect_order_plans_step
  else
    collect_notices_step
  fi
  workflow_note "collect-only run complete: ${run_id} (not ingested)"
elif [[ "${opt_track}" == "notices" ]]; then
  workflow_common_preflight
  collect_notices_step
  ingest_notices_step
  workflow_note "daily notices track complete for ${ref_date}"
else
  workflow_common_preflight
  collect_order_plans_step
  ingest_order_plans_step
  workflow_note "daily order-plans track complete for ${ref_date}"
fi
