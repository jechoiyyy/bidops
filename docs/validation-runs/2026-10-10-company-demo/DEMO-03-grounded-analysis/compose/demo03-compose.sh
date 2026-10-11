#!/usr/bin/env bash
# DEMO-03 STEP-007: bidops-local compose wrapper = .sdlc/local-runtime/manage.sh
# + docker-compose.luna.yml + demo image/stack overlays + env/demo.env + --profile luna.
set -euo pipefail
cd /Users/temp/orca/bidops
SCRATCH=/private/tmp/claude-502/-Users-temp-orca-bidops--sdlc-worktrees-demo-local-20261009--sdlc-worktrees-batch-demo0203-20261009/debd3fe0-3d60-4655-b3fd-d1fa7fb26fcb/scratchpad
FEATURE=/Users/temp/orca/bidops/.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/demo0203-20261009-DEMO-03-grounded-analysis
exec docker compose --project-name bidops-local \
  --env-file env/local.env --env-file env/local-model.env --env-file "$FEATURE/env/demo.env" \
  -f docker-compose.yml -f docker-compose.edge.yml \
  -f docker-compose.model-egress.yml -f docker-compose.prespec-attachment.yml \
  -f .sdlc/local-runtime/compose.yml -f .sdlc/local-runtime/litellm.yml \
  -f docker-compose.luna.yml \
  -f "$SCRATCH/demo03-images.yml" -f "$SCRATCH/demo03-stack.yml" \
  --profile luna "$@"
