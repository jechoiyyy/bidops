#!/usr/bin/env bash
# Mac 운영 호스트의 compose 조합 (ADR-0072). 인자는 docker compose에 그대로 넘긴다.
#   scripts/mac-compose.sh config
#   scripts/mac-compose.sh up -d --no-build
# 사전규격 첨부 취득(2026-10-15)부터 첨부 overlay와 `prespec` profile을 함께 붙인다.
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=bidops
exec docker compose \
  --env-file .env --env-file env/model.env --env-file env/prespec-attachment.env --env-file env/c2.env \
  -f docker-compose.yml -f docker-compose.edge.yml \
  -f docker-compose.model-egress.yml -f docker-compose.prespec-attachment.yml \
  -f docker-compose.c2-order-plan.yml \
  -f docker-compose.mac.yml --profile prespec "$@"
