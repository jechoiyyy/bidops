#!/usr/bin/env bash
# The only command a crontab line calls for the daily tracks, so what is
# tested is what is installed (2026-11-18 independent verification B3).
# No `set -e`: the real exit status of the track must reach the final log line.
set -uo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/cron-daily-track.sh <notices|order-plans>            cron run
  scripts/cron-daily-track.sh <notices|order-plans> --dry-run  same settings, dry run
  scripts/cron-daily-track.sh --print-crontab                  recommended crontab lines
  scripts/cron-daily-track.sh -h|--help

Runs scripts/run-daily-lifecycle.sh --track <track> --catch-up-days <N> from
this checkout under one lock shared by both tracks and a timeout, and appends
everything to <log dir>/<track>-YYYYMM.log:
  [cron] <date time> track=<track> start pid=<pid> ...   first line of a run
  ... the track's own output ...
  [cron] <date time> track=<track> exit=<rc>              last line, real status
A start line without an exit line means the run died (host restart, kill).

It sets PATH itself (GNU coreutils, OrbStack docker, Homebrew, system), so the
crontab needs no PATH line.

Required (no default; a missing or "<...>" placeholder value fails with exit 2):
  BIDOPS_DAILY_GAP_FLOOR_DATE   YYYY-MM-DD, see docs/operations/daily.md
  BIDOPS_C2_DAILY_ACTOR         order-plans only; claimed name, not authentication

Defaults (environment overrides them):
  BIDOPS_ENV=prod
  BIDOPS_WORKFLOW_WEB_URL=http://127.0.0.1:18788
  BIDOPS_DAILY_GAP_LOOKBACK_DAYS=31
  BIDOPS_DAILY_CATCH_UP_DAYS=3
  BIDOPS_DAILY_LOCK_FILE=$HOME/.local/state/bidops/daily.lock   (both tracks)
  BIDOPS_DAILY_LOG_DIR=$HOME/.local/state/bidops/logs
  lock wait 3600 s (notices) / 7200 s (order-plans), BIDOPS_DAILY_LOCK_WAIT_SECONDS
  timeout 3h (notices) / 6h (order-plans), BIDOPS_DAILY_TRACK_TIMEOUT

Exit (also written as exit=<rc>):
  0   success or normal skip
  10  gap_detected / unjudged_detected (attention needed; processed days ended normally)
  75  the shared lock was still held after the wait (nothing ran)
  124 the track hit the timeout
  2   configuration or script check failed; other non-zero: a failing command
--dry-run takes no lock, uses no timeout and prints to the terminal instead of
the log.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LOCK_BUSY_EXIT=75

die_usage() {
  printf '[cron] error: %s\n' "$1" >&2
  usage >&2
  exit 2
}

print_crontab() {
  cat <<EOF
# BidOps daily tracks (installed by a person at cron approval; fill both placeholders).
# Logs: \${HOME}/.local/state/bidops/logs/<track>-YYYYMM.log, last line "[cron] ... exit=<rc>".
30 6 * * * BIDOPS_DAILY_GAP_FLOOR_DATE=<YYYY-MM-DD> ${REPO_ROOT}/scripts/cron-daily-track.sh notices
0 7 * * * BIDOPS_DAILY_GAP_FLOOR_DATE=<YYYY-MM-DD> BIDOPS_C2_DAILY_ACTOR=<담당자 이름> ${REPO_ROOT}/scripts/cron-daily-track.sh order-plans
EOF
}

track=""
dry_run="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    notices|order-plans)
      [[ -z "${track}" ]] || die_usage "only one track per run"
      track="$1"; shift ;;
    --dry-run) dry_run="true"; shift ;;
    --print-crontab) print_crontab; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) die_usage "unknown argument: $1" ;;
  esac
done
[[ -n "${track}" ]] || die_usage "a track is required (notices|order-plans)"

# cron starts with PATH=/usr/bin:/bin. The daily scripts need GNU date -d,
# timeout and flock (Homebrew) and the OrbStack docker CLI.
export PATH="/opt/homebrew/opt/coreutils/libexec/gnubin:/Applications/OrbStack.app/Contents/MacOS/xbin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
export BIDOPS_ENV="${BIDOPS_ENV:-prod}"
export BIDOPS_WORKFLOW_WEB_URL="${BIDOPS_WORKFLOW_WEB_URL:-http://127.0.0.1:18788}"
export BIDOPS_DAILY_GAP_LOOKBACK_DAYS="${BIDOPS_DAILY_GAP_LOOKBACK_DAYS:-31}"
catch_up_days="${BIDOPS_DAILY_CATCH_UP_DAYS:-3}"
state_dir="${HOME}/.local/state/bidops"
lock_file="${BIDOPS_DAILY_LOCK_FILE:-${state_dir}/daily.lock}"
log_dir="${BIDOPS_DAILY_LOG_DIR:-${state_dir}/logs}"
if [[ "${track}" == "notices" ]]; then
  lock_wait="${BIDOPS_DAILY_LOCK_WAIT_SECONDS:-3600}"
  track_timeout="${BIDOPS_DAILY_TRACK_TIMEOUT:-3h}"
else
  lock_wait="${BIDOPS_DAILY_LOCK_WAIT_SECONDS:-7200}"
  track_timeout="${BIDOPS_DAILY_TRACK_TIMEOUT:-6h}"
fi

stamp() { date '+%Y-%m-%d %H:%M:%S %Z'; }

# Configuration problems: collected first, reported to the terminal (cron mail)
# and, outside a dry run, to the log with a start and an exit line.
problems=()
require_value() {
  local name="$1" value="${!1:-}"
  if [[ -z "${value//[[:space:]]/}" ]]; then
    problems+=("${name} is required (no default)")
  elif [[ "${value}" == *"<"* || "${value}" == *">"* ]]; then
    problems+=("${name} still holds a placeholder: ${value}")
  fi
}
require_value BIDOPS_DAILY_GAP_FLOOR_DATE
if [[ "${track}" == "order-plans" ]]; then
  require_value BIDOPS_C2_DAILY_ACTOR
fi
[[ "${catch_up_days}" =~ ^[0-9]+$ ]] || problems+=("BIDOPS_DAILY_CATCH_UP_DAYS must be a non-negative integer: ${catch_up_days}")
[[ "${lock_wait}" =~ ^[0-9]+$ ]] || problems+=("BIDOPS_DAILY_LOCK_WAIT_SECONDS must be a non-negative integer: ${lock_wait}")

cmd=("${SCRIPT_DIR}/run-daily-lifecycle.sh" --track "${track}" --catch-up-days "${catch_up_days}")

cd "${REPO_ROOT}" || exit 2

if [[ "${dry_run}" == "true" ]]; then
  if (( ${#problems[@]} > 0 )); then
    printf '[cron] error: %s\n' "${problems[@]}" >&2
    exit 2
  fi
  printf '[cron] dry-run: track=%s env=%s web=%s lookback=%s floor=%s catch_up=%s\n' \
    "${track}" "${BIDOPS_ENV}" "${BIDOPS_WORKFLOW_WEB_URL}" "${BIDOPS_DAILY_GAP_LOOKBACK_DAYS}" \
    "${BIDOPS_DAILY_GAP_FLOOR_DATE}" "${catch_up_days}"
  printf '[cron] dry-run: a cron run would execute: flock -o -w %s -E %s %s timeout -k 60 %s %s\n' \
    "${lock_wait}" "${LOCK_BUSY_EXIT}" "${lock_file}" "${track_timeout}" "${cmd[*]}"
  printf '[cron] dry-run: and append to %s/%s-%s.log; no lock is taken now\n' "${log_dir}" "${track}" "$(date +%Y%m)"
  "${cmd[@]}" --dry-run
  exit $?
fi

mkdir -p "${log_dir}" "$(dirname -- "${lock_file}")" || exit 2
log_file="${log_dir}/${track}-$(date +%Y%m).log"
exec 3>&2
exec >>"${log_file}" 2>&1

printf '[cron] %s track=%s start pid=%s env=%s web=%s lookback=%s floor=%s catch_up=%s lock=%s wait=%ss timeout=%s\n' \
  "$(stamp)" "${track}" "$$" "${BIDOPS_ENV}" "${BIDOPS_WORKFLOW_WEB_URL}" "${BIDOPS_DAILY_GAP_LOOKBACK_DAYS}" \
  "${BIDOPS_DAILY_GAP_FLOOR_DATE:-}" "${catch_up_days}" "${lock_file}" "${lock_wait}" "${track_timeout}"

if (( ${#problems[@]} > 0 )); then
  for problem in "${problems[@]}"; do
    printf '[cron] error: %s\n' "${problem}"
    printf '[cron] error: %s (log %s)\n' "${problem}" "${log_file}" >&3
  done
  rc=2
else
  # -o: the lock fd is not inherited by the track, so a stray child cannot keep
  # the lock after the run ends. -E: a lock still held after the wait is 75,
  # distinct from every exit code of the track itself.
  flock -o -w "${lock_wait}" -E "${LOCK_BUSY_EXIT}" "${lock_file}" \
    timeout -k 60 "${track_timeout}" "${cmd[@]}"
  rc=$?
  if (( rc == LOCK_BUSY_EXIT )); then
    printf '[cron] lock still held after %ss: %s (another daily track or a manual run holds it); nothing ran\n' \
      "${lock_wait}" "${lock_file}"
  elif (( rc == 124 )); then
    printf '[cron] the track hit the timeout %s\n' "${track_timeout}"
  fi
fi
printf '[cron] %s track=%s exit=%s\n' "$(stamp)" "${track}" "${rc}"
exit "${rc}"
