#!/usr/bin/env bash
set -euo pipefail

# Run inside the explicitly named T7 Compose project after external secrets
# are loaded.  The services are idempotent and this helper never removes data.
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bidops-deep-review-t7}" docker compose -f docker-compose.t7.yml run --rm postgres-init
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bidops-deep-review-t7}" docker compose -f docker-compose.t7.yml run --rm migrate
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bidops-deep-review-t7}" docker compose -f docker-compose.t7.yml run --rm minio-init
