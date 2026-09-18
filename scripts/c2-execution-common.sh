#!/usr/bin/env bash
# C-2 execution helpers shared by the daily order-plans track
# (scripts/run-daily-lifecycle.sh) and scripts/run-daily-c2.sh.
# Source after scripts/manual-workflow-common.sh (workflow_note/workflow_die and
# BIDOPS_WORKFLOW_WEB_URL come from there).
#
# Wire: docs/contracts.md "C-2 일일 운영 계약" (실행 트리거 헤더와 게이트, 감사 표본
# REST, 일일 자동 실행 스위치 REST) and "C-2 수동 REST 계약". Behaviour:
# docs/0918_daily-operation/spec.md §8. Only the web REST surface is used; no
# model is called from here (the analysis worker owns the execution).
set -euo pipefail

# request_id namespace for uuidv5. Fixed so the same (source run, policy
# version, attempt) always maps to the same request_id on every host and every
# rerun: a POST repeated after a crash replays the original 202 instead of
# creating a second execution. Changing it would break that replay for runs
# already in flight. Value: uuid5(NAMESPACE_URL, "urn:bidops:c2-daily-execution").
C2_REQUEST_NAMESPACE="4e9f787e-8b77-500c-8957-fe046c52e9cf"

# Wait before the automatic same-day retry. It waits out a transient outage; it
# is not the GPU rest (the worker owns that, spec §10).
C2_RETRY_WAIT_SECONDS="${BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS:-600}"
# Poll budget per execution. A C-2 run takes about 10 minutes (12 Qwen batches)
# but may first wait behind one overview/deep-review job in the single analysis
# worker slot, be reclaimed after c2_worker_stale_seconds (900) if the worker
# restarts, and wait out an optional GPU rest (BIDOPS_GPU_REST_SECONDS, §10).
# 7200 s covers that sum with a wide margin; on timeout the execution keeps
# running in the worker and the next invocation skips it as active.
C2_POLL_TIMEOUT_SECONDS="${BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS:-7200}"
C2_POLL_INTERVAL_SECONDS="${BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS:-30}"

C2_GUIDANCE="policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다."

# Automatic retry cap: attempt 1 plus one same-day retry (decision 12).
C2_MAX_AUTO_ATTEMPT=2

C2_ACTOR_HEADERS=()
C2_HTTP_CODE=""
C2_HTTP_BODY=""
C2_TRIGGER_ENABLED=""
C2_POLICY_VERSION=""
C2_TRIGGER_REASONS=""
C2_RUN_EXECUTIONS="[]"
C2_EXECUTION_ID=""
C2_EXECUTION_STATUS=""
# Outcome of c2_run_source_run: executed, already_executed,
# active_execution_exists, retry_limit_reached, daily_trigger_off,
# policy_not_active, service_unavailable. Hard failures exit instead.
C2_OUTCOME=""

c2_require_non_negative_int() {
  local name="$1" value="$2"
  [[ "${value}" =~ ^[0-9]+$ ]] || workflow_die "${name} must be a non-negative integer: ${value}"
}

c2_validate_settings() {
  c2_require_non_negative_int BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS "${C2_RETRY_WAIT_SECONDS}"
  c2_require_non_negative_int BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS "${C2_POLL_TIMEOUT_SECONDS}"
  c2_require_non_negative_int BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS "${C2_POLL_INTERVAL_SECONDS}"
}

# BIDOPS_C2_DAILY_ACTOR is required and has no default (spec §8 actor). It is a
# claimed name for audit, not authentication; the cron installer puts their own
# name here. Headers follow validate_actor (web/backend/app/core/api_errors.py)
# and the frontend actorHeaders(): ASCII names go as-is, anything else as
# UTF-8'' + RFC 3986 percent-encoding with X-BidOps-Actor-Name-Format.
c2_require_actor() {
  local actor="${BIDOPS_C2_DAILY_ACTOR:-}" encoded
  actor="${actor#"${actor%%[![:space:]]*}"}"
  actor="${actor%"${actor##*[![:space:]]}"}"
  [[ -n "${actor}" ]] \
    || workflow_die "BIDOPS_C2_DAILY_ACTOR is required (the name of the person who installed this schedule); not starting"
  # Code points, not regex: oniguruma cannot hold NUL in a character class.
  jq -en --arg a "${actor}" \
    '($a | explode) as $c | ($c | length) <= 128
     and ($c | any(. < 32 or (. >= 127 and . <= 159)) | not)
     and ($a | ascii_downcase) != "system"' \
    >/dev/null || workflow_die "BIDOPS_C2_DAILY_ACTOR is not a valid actor name"
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

# uuidv5 (RFC 4122 §4.3) with sha1sum only, so no interpreter is needed.
c2_uuid5() {
  local name="$1" ns_hex digest variant
  ns_hex="${C2_REQUEST_NAMESPACE//-/}"
  digest="$(
    {
      # shellcheck disable=SC2059 # the format is built from fixed hex pairs
      printf "$(sed -E 's/(..)/\\x\1/g' <<<"${ns_hex}")"
      printf '%s' "${name}"
    } | sha1sum | cut -c1-32
  )"
  variant="$(printf '%x' $(( (16#${digest:16:1} & 3) | 8 )))"
  printf '%s-%s-5%s-%s%s-%s\n' \
    "${digest:0:8}" "${digest:8:4}" "${digest:13:3}" "${variant}" "${digest:17:3}" "${digest:20:12}"
}

# request_id = uuidv5(NAMESPACE, "<source_run_id>|<policy_version>|<attempt>")
c2_execution_request_id() {
  c2_uuid5 "$1|$2|$3"
}

c2_audit_sample_request_id() {
  c2_uuid5 "audit-sample|$1"
}

# c2_request METHOD PATH BODY [HEADER...] — sets C2_HTTP_CODE and C2_HTTP_BODY.
# An empty BODY sends no body. A transport failure stops the caller.
c2_request() {
  local method="$1" path="$2" body="$3" header response
  shift 3
  local args=(--connect-timeout 3 --max-time 30 --silent --show-error -X "${method}")
  for header in "$@"; do
    args+=(-H "${header}")
  done
  if [[ -n "${body}" ]]; then
    args+=(-H "Content-Type: application/json" --data-binary "${body}")
  fi
  args+=(--write-out '\n%{http_code}')
  response="$(curl "${args[@]}" "${BIDOPS_WORKFLOW_WEB_URL}${path}")" \
    || workflow_die "request failed: ${method} ${BIDOPS_WORKFLOW_WEB_URL}${path}"
  C2_HTTP_CODE="${response##*$'\n'}"
  if [[ "${response}" == *$'\n'* ]]; then
    C2_HTTP_BODY="${response%$'\n'*}"
  else
    C2_HTTP_BODY=""
  fi
}

c2_error_code() {
  jq -r '.error.code // empty' <<<"${C2_HTTP_BODY}" 2>/dev/null || true
}

c2_die_http() {
  workflow_die "$1 returned HTTP ${C2_HTTP_CODE}: $(jq -c '.error // .' <<<"${C2_HTTP_BODY}" 2>/dev/null || printf '%s' "${C2_HTTP_BODY}")"
}

c2_print_trigger_off() {
  local reasons="$1"
  workflow_note "daily_trigger_off: ${reasons:-unknown}"
  workflow_note "${C2_GUIDANCE}"
}

# GET /api/order-plan-screening/daily-trigger. Sets C2_TRIGGER_ENABLED
# (true|false), C2_POLICY_VERSION (the active version to execute with; the
# script never carries its own) and C2_TRIGGER_REASONS (comma separated).
c2_fetch_daily_trigger() {
  c2_request GET /api/order-plan-screening/daily-trigger ""
  [[ "${C2_HTTP_CODE}" == "200" ]] || c2_die_http "daily-trigger lookup"
  C2_TRIGGER_ENABLED="$(jq -r 'if .effective_enabled == true then "true" else "false" end' <<<"${C2_HTTP_BODY}")" \
    || workflow_die "daily-trigger response is not JSON"
  C2_TRIGGER_REASONS="$(jq -r '(.reasons // []) | join(",")' <<<"${C2_HTTP_BODY}")"
  C2_POLICY_VERSION="$(jq -r '.policy_version // empty' <<<"${C2_HTTP_BODY}")"
  if [[ "${C2_TRIGGER_ENABLED}" == "true" && -z "${C2_POLICY_VERSION}" ]]; then
    workflow_die "daily-trigger is enabled without an active policy_version"
  fi
}

# Operational executions of one source run (gate_measurement is never ours).
c2_list_run_executions() {
  local run_id="$1"
  workflow_validate_run_id "${run_id}"
  c2_request GET "/api/order-plan-screening/executions?source_run_id=${run_id}&limit=500" ""
  [[ "${C2_HTTP_CODE}" == "200" ]] || c2_die_http "execution list for ${run_id}"
  jq -e '.total <= (.items | length)' <<<"${C2_HTTP_BODY}" >/dev/null \
    || workflow_die "execution list for ${run_id} has more than one page"
  C2_RUN_EXECUTIONS="$(jq -c --arg run "${run_id}" \
    '[.items[] | select(.source_run_id == $run and .purpose == "operational")]' <<<"${C2_HTTP_BODY}")"
}

# POST one execution. Sets C2_EXECUTION_ID on 202, otherwise C2_OUTCOME for a
# normal skip (spec §8: the state may change between the GET and the POST).
c2_create_execution() {
  local run_id="$1" policy_version="$2" attempt="$3" trigger="$4" request_id body code
  request_id="$(c2_execution_request_id "${run_id}" "${policy_version}" "${attempt}")"
  body="$(jq -nc --arg rid "${request_id}" --arg run "${run_id}" --arg pv "${policy_version}" \
    '{schema_version: "execution-create-request.v1", producer: "human-review-client",
      consumer: "screening-api", request_id: $rid, source_run_id: $run, policy_version: $pv}')"
  workflow_note "c2: requesting execution for ${run_id} (policy ${policy_version}, attempt ${attempt}, trigger ${trigger}, request_id ${request_id})"
  C2_EXECUTION_ID=""
  c2_request POST /api/order-plan-screening/executions "${body}" \
    "${C2_ACTOR_HEADERS[@]}" "X-BidOps-Trigger: ${trigger}"
  code="$(c2_error_code)"
  case "${C2_HTTP_CODE}:${code}" in
    202:*)
      C2_EXECUTION_ID="$(jq -er '.execution_id' <<<"${C2_HTTP_BODY}")" \
        || workflow_die "execution create response has no execution_id"
      workflow_note "c2: execution ${C2_EXECUTION_ID} queued"
      ;;
    409:daily_trigger_off)
      C2_OUTCOME="daily_trigger_off"
      c2_print_trigger_off "$(jq -r '(.error.details.reasons // []) | join(",")' <<<"${C2_HTTP_BODY}")"
      ;;
    409:policy_not_active)
      C2_OUTCOME="policy_not_active"
      workflow_note "policy_not_active: ${policy_version} is no longer the active policy; no execution created"
      workflow_note "${C2_GUIDANCE}"
      ;;
    409:active_execution_exists)
      C2_OUTCOME="active_execution_exists"
      workflow_note "active_execution_exists: another C-2 execution holds the active slot; no execution created"
      ;;
    503:*)
      C2_OUTCOME="service_unavailable"
      workflow_note "service_unavailable: C-2 transport is not available (HTTP 503); no execution created"
      ;;
    *) c2_die_http "execution create for ${run_id}" ;;
  esac
}

# Polls until the execution reaches a terminal status; sets C2_EXECUTION_STATUS.
c2_poll_execution() {
  local execution_id="$1" started="${SECONDS}"
  while true; do
    c2_request GET "/api/order-plan-screening/executions/${execution_id}" ""
    [[ "${C2_HTTP_CODE}" == "200" ]] || c2_die_http "execution ${execution_id} lookup"
    C2_EXECUTION_STATUS="$(jq -er '.status' <<<"${C2_HTTP_BODY}")" \
      || workflow_die "execution ${execution_id} response has no status"
    case "${C2_EXECUTION_STATUS}" in
      성공|"부분 성공"|실패|중단됨)
        workflow_note "c2: execution ${execution_id} finished: ${C2_EXECUTION_STATUS}"
        return 0
        ;;
    esac
    if (( SECONDS - started >= C2_POLL_TIMEOUT_SECONDS )); then
      workflow_die "execution ${execution_id} is still ${C2_EXECUTION_STATUS} after ${C2_POLL_TIMEOUT_SECONDS}s; it keeps running in the worker and the next run skips it as active"
    fi
    sleep "${C2_POLL_INTERVAL_SECONDS}"
  done
}

# Audit-sample draw for a successful execution (spec §5·§8). A failure exits
# non-zero; the execution's result rows are kept either way.
c2_draw_audit_sample() {
  local execution_id="$1" trigger="$2" request_id body status
  c2_request GET "/api/order-plan-screening/executions/${execution_id}/audit-sample" ""
  [[ "${C2_HTTP_CODE}" == "200" ]] \
    || c2_die_http "audit-sample lookup for ${execution_id} (execution results are kept)"
  if [[ "$(jq -r '.status' <<<"${C2_HTTP_BODY}")" == "drawn" ]]; then
    workflow_note "audit sample already drawn for ${execution_id}"
    return 0
  fi

  request_id="$(c2_audit_sample_request_id "${execution_id}")"
  body="$(jq -nc --arg rid "${request_id}" \
    '{schema_version: "audit-sample-draw-request.v1", producer: "human-review-client",
      consumer: "audit-sample-api", request_id: $rid}')"
  c2_request POST "/api/order-plan-screening/executions/${execution_id}/audit-sample" "${body}" \
    "${C2_ACTOR_HEADERS[@]}" "X-BidOps-Trigger: ${trigger}"
  case "${C2_HTTP_CODE}" in
    200|201) ;;
    *) c2_die_http "audit-sample draw for ${execution_id} (execution results are kept)" ;;
  esac
  status="$(jq -r '.status' <<<"${C2_HTTP_BODY}")"
  case "${status}" in
    drawn)
      workflow_note "audit sample drawn for ${execution_id}: $(jq -r '(.sample // []) | length' <<<"${C2_HTTP_BODY}") item(s)"
      ;;
    pending_human_approval)
      workflow_note "audit sample pending_human_approval: $(jq -r '.pending_decision // "unknown"' <<<"${C2_HTTP_BODY}")"
      ;;
    not_applicable)
      workflow_note "audit sample not_applicable: $(jq -r '.reason // "unknown"' <<<"${C2_HTTP_BODY}")"
      ;;
    *) workflow_die "audit-sample draw for ${execution_id} returned unexpected status: ${status}" ;;
  esac
}

# c2_run_source_run RUN_ID POLICY_VERSION daily|extra
# Applies spec §8 skip/retry rules to one complete, non-empty order-plan run and
# draws the audit sample after success. Sets C2_OUTCOME.
#   daily: header daily_script, attempt <= 2 with one waited same-day retry.
#   extra: header manual_resume, exactly one execution, no retry (decision 12).
c2_run_source_run() {
  local run_id="$1" policy_version="$2" mode="$3" trigger success_id attempt created=0
  case "${mode}" in
    daily) trigger="daily_script" ;;
    extra) trigger="manual_resume" ;;
    *) workflow_die "unknown C-2 mode: ${mode}" ;;
  esac
  C2_OUTCOME=""

  while true; do
    c2_list_run_executions "${run_id}"
    success_id="$(jq -r '[.[] | select(.status == "성공" or .status == "부분 성공")]
      | sort_by(.finished_at // "") | last | .execution_id // empty' <<<"${C2_RUN_EXECUTIONS}")"
    if [[ -n "${success_id}" ]]; then
      if (( created == 0 )); then
        C2_OUTCOME="already_executed"
        workflow_note "already_executed: ${run_id} has a successful execution ${success_id}; no new execution"
      else
        C2_OUTCOME="executed"
      fi
      c2_draw_audit_sample "${success_id}" "${trigger}"
      return 0
    fi
    if jq -e 'any(.[]; .status == "대기" or .status == "실행 중" or .status == "중지 요청")' \
        <<<"${C2_RUN_EXECUTIONS}" >/dev/null; then
      C2_OUTCOME="active_execution_exists"
      workflow_note "active_execution_exists: ${run_id} has a queued or running execution; no new execution"
      return 0
    fi

    attempt="$(jq -r --arg pv "${policy_version}" '[.[] | select(.policy_version == $pv)] | length + 1' \
      <<<"${C2_RUN_EXECUTIONS}")"
    if (( created > 0 )) && [[ "${mode}" == "extra" || "${attempt}" -gt "${C2_MAX_AUTO_ATTEMPT}" ]]; then
      workflow_die "C-2 execution for ${run_id} ended ${C2_EXECUTION_STATUS}; no further automatic attempt today. Resume with: scripts/run-daily-c2.sh ${run_id} --extra-attempt"
    fi
    if [[ "${mode}" == "daily" && "${attempt}" -gt "${C2_MAX_AUTO_ATTEMPT}" ]]; then
      C2_OUTCOME="retry_limit_reached"
      workflow_note "retry_limit_reached: ${run_id} already failed $((attempt - 1)) time(s) under ${policy_version}; no automatic retry"
      workflow_note "resume manually with: scripts/run-daily-c2.sh ${run_id} --extra-attempt"
      return 0
    fi
    if [[ "${mode}" == "daily" && "${attempt}" -gt 1 ]]; then
      workflow_note "c2: previous attempt of ${run_id} failed; waiting ${C2_RETRY_WAIT_SECONDS}s before attempt ${attempt}"
      sleep "${C2_RETRY_WAIT_SECONDS}"
    fi

    c2_create_execution "${run_id}" "${policy_version}" "${attempt}" "${trigger}"
    [[ -n "${C2_EXECUTION_ID}" ]] || return 0
    created=$((created + 1))
    c2_poll_execution "${C2_EXECUTION_ID}"
  done
}

# Outcomes after which later days of the same invocation cannot proceed either:
# the switch or the policy changed, transport is down, or the active slot is
# taken. The track ends with exit 0 (spec §8 정상 스킵).
c2_outcome_stops_track() {
  case "$1" in
    daily_trigger_off|policy_not_active|service_unavailable|active_execution_exists) return 0 ;;
    *) return 1 ;;
  esac
}
