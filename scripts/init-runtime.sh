#!/usr/bin/env bash
set -euo pipefail

# Run inside the explicitly named Compose project after external secrets
# are loaded.  The services are idempotent and this helper never removes data.
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bidops}" docker compose -f docker-compose.yml run --rm postgres-init
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bidops}" docker compose -f docker-compose.yml run --rm migrate
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bidops}" docker compose -f docker-compose.yml run --rm minio-init
