#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/manual-workflow-common.sh
source "${SCRIPT_DIR}/manual-workflow-common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/run-daily-lifecycle.sh [--date YYYY-MM-DD] [--dry-run] [-h|--help]

Runs one day of collection and selective ingest, in order:
  1. Preflight (web health; collectors check BIDOPS_G2B_API_KEY themselves).
  2. Order plans: 21-day window ending on the reference day (inclusive),
     run id lifecycle-<YYYYMMDD>-plans.
  3. Notices (pre-specs + bids, tagged with 1468 SW-industry status): 3-day
     window ending on the reference day (inclusive both ends), run id
     lifecycle-<YYYYMMDD>-notices.
  4. Ingest in order: plans (--collection) -> notices (--collection) ->
     --tracked-backfill -> attachment fetch-eligibility refresh.

Options:
  --date YYYY-MM-DD   Reference day in Asia/Seoul (default: today, KST).
  --dry-run           Print computed run ids, windows, and the exact
                       commands; do not collect, ingest, or touch Docker.
  -h, --help          Show this help.

Safety:
  - Stops on the first failure (no partial silent continuation).
  - Never overwrites an existing immutable run directory.
  - Never deletes anything and never installs cron; the scheduler stays
    disabled by default (see CLAUDE.md). No model calls are made.
EOF
}

opt_date=""
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date) opt_date="${2:-}"; shift 2 ;;
    --dry-run) dry_run="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; workflow_die "unknown option: $1" ;;
  esac
done

if [[ -n "${opt_date}" ]]; then
  [[ "${opt_date}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
    || workflow_die "--date must be YYYY-MM-DD: ${opt_date}"
  ref_date="${opt_date}"
else
  ref_date="$(TZ=Asia/Seoul date +%Y-%m-%d)"
fi
# Canonicalize and reject invalid calendar dates (GNU date rejects e.g. 2026-02-30).
ref_date="$(date -d "${ref_date}" +%Y-%m-%d 2>/dev/null)" \
  || workflow_die "invalid --date value: ${opt_date}"
ref_compact="$(date -d "${ref_date}" +%Y%m%d)"

plans_run_id="lifecycle-${ref_compact}-plans"
notices_run_id="lifecycle-${ref_compact}-notices"
plans_run_dir="$(workflow_run_dir "${plans_run_id}")"
notices_run_dir="$(workflow_run_dir "${notices_run_id}")"

# collect_order_plans.py --to-date is exclusive; collect_notices.py --to-date is
# inclusive. Both windows below are computed to include the reference day.
plans_from_date="$(date -d "${ref_date} -20 days" +%Y-%m-%d)"
plans_to_date="$(date -d "${ref_date} +1 day" +%Y-%m-%d)"
notices_from_date="$(date -d "${ref_date} -2 days" +%Y-%m-%d)"
notices_to_date="${ref_date}"

print_plan() {
  workflow_note "reference day (KST): ${ref_date}"
  workflow_note "order-plan run: ${plans_run_id}"
  workflow_note "  window: --from-date ${plans_from_date} --to-date ${plans_to_date} (half-open, exclusive end; 21 days incl. ${ref_date})"
  workflow_note "  dir:    ${plans_run_dir}"
  workflow_note "notice run: ${notices_run_id}"
  workflow_note "  window: --from-date ${notices_from_date} --to-date ${notices_to_date} (closed, inclusive both ends; 3 days incl. ${ref_date})"
  workflow_note "  dir:    ${notices_run_dir}"
}

print_dry_run_commands() {
  cat <<EOF
[dry-run] would run:
  python3 skills/bidops-collect/scripts/collect_order_plans.py \\
    --from-date ${plans_from_date} --to-date ${plans_to_date} \\
    --output-dir ${plans_run_dir} --timeout 300
  jq '{schema_version, metadata, counts}' ${plans_run_dir}/collected-order-plans.json

  python3 skills/bidops-collect/scripts/collect_notices.py \\
    --from-date ${notices_from_date} --to-date ${notices_to_date} \\
    --output-dir ${notices_run_dir} --timeout 300 --tag-bid-sw-industry
  jq '{schema_version, counts, sw_industry_1468: (.metadata.sw_industry_1468 // null)}' ${notices_run_dir}/collected-notices.json

  docker compose -f docker-compose.yml cp ${plans_run_dir} web:/app/data/runs/
  docker compose -f docker-compose.yml cp ${notices_run_dir} web:/app/data/runs/
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --run ${plans_run_id} --collection
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --run ${notices_run_id} --collection
  docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.ingest.cli --tracked-backfill
  docker compose -f docker-compose.yml exec -T web python -c \\
    'from app.core.db import SessionLocal; from app.deep_review.services.prespec_attachments import refresh_fetch_eligibility; s=SessionLocal(); print(refresh_fetch_eligibility(s)); s.commit()'
EOF
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
  workflow_check_new_run_dir "${plans_run_dir}"
  workflow_note "collecting order plans into immutable run ${plans_run_id}"
  python3 skills/bidops-collect/scripts/collect_order_plans.py \
    --from-date "${plans_from_date}" --to-date "${plans_to_date}" \
    --output-dir "${plans_run_dir}" --timeout 300
  jq '{schema_version, metadata, counts}' "${plans_run_dir}/collected-order-plans.json"
}

collect_notices_step() {
  workflow_check_new_run_dir "${notices_run_dir}"
  workflow_note "collecting notices (pre-specs + bids, 1468 tagged) into immutable run ${notices_run_id}"
  python3 skills/bidops-collect/scripts/collect_notices.py \
    --from-date "${notices_from_date}" --to-date "${notices_to_date}" \
    --output-dir "${notices_run_dir}" --timeout 300 --tag-bid-sw-industry
  jq '{schema_version, counts, sw_industry_1468: (.metadata.sw_industry_1468 // null)}' \
    "${notices_run_dir}/collected-notices.json"
}

ingest_step() {
  workflow_copy_run_if_missing "${plans_run_id}" "${plans_run_dir}"
  workflow_copy_run_if_missing "${notices_run_id}" "${notices_run_dir}"

  local result
  workflow_note "ingesting order-plan run ${plans_run_id} (--collection)"
  result="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.lifecycle.ingest.cli --run "${plans_run_id}" --collection)"
  print_result "order-plan ingest" "${result}"

  workflow_note "ingesting notice run ${notices_run_id} (--collection)"
  result="$(COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.yml \
    exec -T web python -m app.lifecycle.ingest.cli --run "${notices_run_id}" --collection)"
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

workflow_common_preflight
collect_order_plans_step
collect_notices_step
ingest_step
workflow_note "daily lifecycle run complete for ${ref_date}"
