#!/usr/bin/env bash
# Run every BidOps test suite. Each skill keeps its own tests next to the
# scripts it covers, and tests/ holds the cross-skill pipeline checks.
set -euo pipefail

cd "$(dirname "$0")"

status=0
for directory in skills/*/tests tests; do
  [ -d "$directory" ] || continue
  compgen -G "$directory/test_*.py" > /dev/null || continue
  echo "== $directory"
  python3 -m unittest discover -s "$directory" -p "test_*.py" -t "$directory" -v || status=1
done
exit $status
