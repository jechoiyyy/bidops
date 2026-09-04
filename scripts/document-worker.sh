#!/usr/bin/env bash
set -euo pipefail
exec python -m app.deep_review.workers.document
