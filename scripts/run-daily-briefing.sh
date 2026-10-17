#!/usr/bin/env bash
set -euo pipefail

# Exit codes owned by this script (the CLI's own non-zero code is passed through
# unchanged, so 1 = build-briefing failed, e.g. company_not_registered).
EXIT_USAGE=2
EXIT_SLACK_SEND_FAILED=3
EXIT_OUTPUT_UNREADABLE=4

usage() {
  cat <<'EOF'
Usage:
  scripts/run-daily-briefing.sh [--date YYYY-MM-DD] [--send] [--dry-run]
  scripts/run-daily-briefing.sh -h|--help

Builds the weekday briefing once (RL-01) by running, inside the running web
container:

  docker compose -f docker-compose.yml exec -T web \
    python -m app.lifecycle.cli build-briefing --date <D> --json [--send]

Run it after the notices track of the same morning has finished: the briefing
for day D reads the notices collection of D-1 (the notices run
lifecycle-<D-1>-notices) and marks itself collection_incomplete when that run
is missing, ambiguous, or has ingest warnings.

Options:
  --date YYYY-MM-DD   Briefing date D in Asia/Seoul (default: today, KST). The
                      CLI treats Saturday and Sunday as no-ops (exit 0, no row,
                      slack.skipped_reason=weekend). Running the same day again
                      keeps the existing row (created=false).
  --send              Also post the briefing to Slack, once. The CLI sends only
                      when BIDOPS_SLACK_ENABLED=true with token, channel and an
                      allowed host, the status is not empty, and nothing was sent
                      yet. Re-running with --send after a failure sends only the
                      messages that are still missing.
  --dry-run           Print the call sequence and exit 0. Nothing is executed:
                      no docker, no docker compose port lookup, no web call, no
                      Slack. It does not pass --dry-run to the CLI either; run the
                      CLI by hand for a computed preview.
  -h, --help          Show this help.

Environment:
  COMPOSE_PROJECT_NAME  Compose project of the running stack (default bidops).
                        Nothing else is read, so the script works from a clean
                        cron environment (env -i HOME=... PATH=...).

Exit codes:
  0  success, including every normal skip (weekend, empty, already_sent,
     slack_disabled, token_missing, channel_missing, host_not_allowed,
     not_requested) and data-state warnings such as collection_run_missing.
  1  the CLI failed to build the briefing (e.g. company_not_registered); any
     other non-zero CLI or docker exit code is passed through unchanged.
  2  usage error, or docker/jq missing.
  3  slack_send_failed. The CLI exits 0 for it and only lists the code in the
     JSON warnings[], so cron would call a failed delivery a success; this
     script reads the JSON and turns it into a non-zero exit. The briefing row
     stays; re-run the same command with --send to send the missing messages.
  4  the CLI exited 0 but its stdout is not the expected JSON object, so
     slack_send_failed cannot be ruled out (fail closed).

Safety:
  - Never installs cron. The scheduler stays disabled by default (CLAUDE.md);
    an example line with flock and timeout is in docs/operations.md.
  - The script takes no lock itself (neither do the two track scripts). The
    cron line wraps it in flock on both track locks (notices.lock and
    plans.lock, see docs/operations.md) and in timeout.
  - No automatic catch-up: a missed day is run by hand with --date.
  - The briefing is append-only. There is no regenerate or delete option.
EOF
}

note() {
  printf '[bidops-briefing] %s\n' "$*" >&2
}

die() {
  printf '[bidops-briefing] error: %s\n' "$*" >&2
  exit "${EXIT_USAGE}"
}

# Prints nothing and returns 1 unless $1 is a real calendar day (YYYY-MM-DD).
# Pure bash: GNU `date -d` is not available everywhere and the clean cron
# environment must not depend on it.
valid_date() {
  local value="$1" year month day max
  [[ "${value}" =~ ^([0-9]{4})-([0-9]{2})-([0-9]{2})$ ]] || return 1
  year=$((10#${BASH_REMATCH[1]}))
  month=$((10#${BASH_REMATCH[2]}))
  day=$((10#${BASH_REMATCH[3]}))
  (( month >= 1 && month <= 12 )) || return 1
  case "${month}" in
    1|3|5|7|8|10|12) max=31 ;;
    4|6|9|11) max=30 ;;
    *)
      if (( year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) )); then
        max=29
      else
        max=28
      fi
      ;;
  esac
  (( day >= 1 && day <= max ))
}

opt_date=""
send="false"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; die "--date needs a value"; }
      opt_date="$2"
      shift 2
      ;;
    --send) send="true"; shift ;;
    --dry-run) dry_run="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

if [[ -n "${opt_date}" ]]; then
  valid_date "${opt_date}" || die "--date must be a real day in YYYY-MM-DD: ${opt_date}"
  briefing_date="${opt_date}"
else
  # Briefing date D = today in KST. The CLI derives the collection day D-1.
  briefing_date="$(TZ=Asia/Seoul date +%Y-%m-%d)"
fi

project="${COMPOSE_PROJECT_NAME:-bidops}"

cli_args=(build-briefing --date "${briefing_date}" --json)
if [[ "${send}" == "true" ]]; then
  cli_args+=(--send)
fi

# The scripts/ directory's parent is the repository root; `-f docker-compose.yml`
# finds the running web container of the project (the same call shape as
# run-daily-lifecycle.sh). The overlays only matter when the stack is created.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."

if [[ "${dry_run}" == "true" ]]; then
  cat <<EOF
[dry-run] daily briefing for ${briefing_date} (KST); nothing is executed.
[dry-run] would run, in this order:
  1. docker compose version
  2. COMPOSE_PROJECT_NAME=${project} docker compose -f docker-compose.yml exec -T web python -m app.lifecycle.cli ${cli_args[*]}
  3. read the JSON the CLI printed:
       CLI exit non-zero               -> exit with that code
       stdout is not a JSON object     -> exit ${EXIT_OUTPUT_UNREADABLE}
       warnings has slack_send_failed  -> exit ${EXIT_SLACK_SEND_FAILED} (the briefing is kept; re-run the same command to send what is missing)
       otherwise                       -> exit 0
EOF
  exit 0
fi

command -v docker >/dev/null 2>&1 || die "required command not found: docker"
command -v jq >/dev/null 2>&1 || die "required command not found: jq"
docker compose version >/dev/null || die "docker compose is not available"

note "building the briefing for ${briefing_date} (send=${send}, project=${project})"
cli_status=0
output="$(COMPOSE_PROJECT_NAME="${project}" docker compose -f docker-compose.yml \
  exec -T web python -m app.lifecycle.cli "${cli_args[@]}")" || cli_status=$?

if [[ -n "${output}" ]]; then
  printf '%s\n' "${output}"
fi

if (( cli_status != 0 )); then
  note "build-briefing exited ${cli_status}; see the output above"
  exit "${cli_status}"
fi

# Exit 0 does not mean delivered: slack_send_failed is a warning, not an exit
# code. Anything that is not the expected JSON object is not trusted either.
if ! jq -e 'type == "object" and ((.warnings // []) | type == "array")' <<<"${output}" >/dev/null 2>&1; then
  note "build-briefing printed no readable JSON object; cannot rule out slack_send_failed"
  exit "${EXIT_OUTPUT_UNREADABLE}"
fi

summary="$(jq -r '"status=\(.status // "null") created=\(.created) items=\(.item_count) tracked_changes=\(.tracked_change_count) slack.sent=\(.slack.sent // false) slack.skipped_reason=\(.slack.skipped_reason // "null")"' <<<"${output}" 2>/dev/null)" || summary=""
[[ -z "${summary}" ]] || note "${summary}"

if jq -e '(.warnings // []) | index("slack_send_failed") != null' <<<"${output}" >/dev/null 2>&1; then
  note "slack_send_failed: the briefing is saved; run the same command with --send again to send the missing messages"
  exit "${EXIT_SLACK_SEND_FAILED}"
fi

exit 0
