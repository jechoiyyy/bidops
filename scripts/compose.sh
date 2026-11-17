#!/usr/bin/env bash
# One configuration selector for Make, manual workflows, and scheduled jobs.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/compose-env.sh
[[ -z "${COMPOSE_FILE:-}" && -z "${COMPOSE_PROFILES:-}" ]] || {
  printf 'Use BIDOPS_ENV/BIDOPS_COMPOSE_FEATURES instead of COMPOSE_FILE/COMPOSE_PROFILES\n' >&2; exit 2;
}
# Do not let a second project/file selection silently bypass the selector.
compose_command=""
for arg in "$@"; do
  case "$arg" in
    -f|-f?*|--file|--file=*|-p|-p?*|--project-name|--project-name=*|--project-directory|--project-directory=*|--env-file|--env-file=*|--profile|--profile=*)
      printf 'Compose selection is owned by scripts/compose.sh; use BIDOPS_ENV and env files\n' >&2; exit 2 ;;
    -*) ;;
    *)
      if [[ -z "$compose_command" ]]; then
        compose_command="$arg"
        # Docker's exec/run payload belongs to the application, not Compose.
        case "$compose_command" in exec|run) break ;; esac
      fi
      ;;
  esac
done
files=(-f docker/docker-compose.yml -f docker/docker-compose.edge.yml)
envs=()
if [[ "$BIDOPS_ENV" == prod ]]; then
  envs=(--env-file "${BIDOPS_ENV_FILE:-.env}" --env-file "${BIDOPS_MODEL_ENV_FILE:-env/model.env}" --env-file "${BIDOPS_ATTACHMENT_ENV_FILE:-env/prespec-attachment.env}" --env-file "${BIDOPS_C2_ENV_FILE:-env/c2.env}")
  files+=(-f docker/docker-compose.prod.yml)
else
  # Explicit env-file suppresses Docker's implicit loading of production .env.
  envs=(--env-file "${BIDOPS_ENV_FILE:-env/${BIDOPS_ENV}.env}")
  if [[ "$BIDOPS_ENV" == mock ]]; then files+=(-f docker/docker-compose.mock-reference.yml); fi
fi
# Persist optional capabilities in the selected primary env file. Never source it
# as shell code: only the allowlisted value below is read, then validated.
features="${BIDOPS_COMPOSE_FEATURES-}"
if [[ -z "${BIDOPS_COMPOSE_FEATURES+x}" && -r "${envs[1]}" ]]; then
  features="$(awk -F= '$1 == "BIDOPS_COMPOSE_FEATURES" {value=$2} END {print value}' "${envs[1]}" | tr -d "\\\"'\r ")"
fi
if [[ "$BIDOPS_ENV" == mock && -n "$features" ]]; then
  printf 'Mock does not allow external Luna or Slack capabilities\n' >&2; exit 2
fi
IFS=, read -r -a feature_list <<< "${features:-none}"
for feature in "${feature_list[@]}"; do
  case "$feature" in
    none) ;;
    luna) files+=(-f docker/docker-compose.luna.yml) ;;
    slack) files+=(-f docker/docker-compose.slack-egress.yml) ;;
    *) printf 'Unknown BIDOPS_COMPOSE_FEATURES value (allowed: luna,slack)\n' >&2; exit 2 ;;
  esac
done
# Native document conversion must not run under Rosetta's RLIMIT_DATA failure.
if [[ -z "${BIDOPS_DOCUMENT_PLATFORM:-}" ]]; then
  case "$(uname -m)" in arm64|aarch64) BIDOPS_DOCUMENT_PLATFORM=linux/arm64 ;; *) BIDOPS_DOCUMENT_PLATFORM=linux/amd64 ;; esac
fi
export BIDOPS_DOCUMENT_PLATFORM
exec docker compose --project-directory "$PWD" -p "$COMPOSE_PROJECT_NAME" "${envs[@]}" "${files[@]}" "$@"
