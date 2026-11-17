#!/usr/bin/env bash
# Shared, side-effect-free selection. Safe to source during --dry-run.
BIDOPS_ENV="${BIDOPS_ENV:-dev}"
case "$BIDOPS_ENV" in
  dev) bidops_default_project=bidops-dev; BIDOPS_DEFAULT_WEB_PORT=18789 ;;
  mock) bidops_default_project=bidops-mock; BIDOPS_DEFAULT_WEB_PORT=18790 ;;
  prod) bidops_default_project=bidops; BIDOPS_DEFAULT_WEB_PORT=18788 ;;
  *) printf 'BIDOPS_ENV must be dev, prod, or mock\n' >&2; exit 2 ;;
esac
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$bidops_default_project}"
case "$COMPOSE_PROJECT_NAME" in
  ''|*[!a-z0-9_-]*) printf 'Invalid Compose project name\n' >&2; exit 2 ;;
esac
if [[ "$BIDOPS_ENV" == prod && "$COMPOSE_PROJECT_NAME" != bidops ]] ||
   [[ "$BIDOPS_ENV" != prod && ( "$COMPOSE_PROJECT_NAME" == bidops || "$COMPOSE_PROJECT_NAME" == bidops-local ) ]]; then
  printf 'Project/environment mismatch: prod requires bidops; dev/mock must not use bidops or bidops-local\n' >&2
  exit 2
fi
export BIDOPS_ENV COMPOSE_PROJECT_NAME BIDOPS_DEFAULT_WEB_PORT
