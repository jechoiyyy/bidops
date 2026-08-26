#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    echo "BidOps container refuses to run as root; set non-zero BIDOPS_UID/BIDOPS_GID." >&2
    exit 77
fi

# Do not chown or chmod mounted paths at startup. A bind mount must already be
# owned by the configured host UID/GID; a clear failure is safer than silently
# changing an operator's files or falling back to world-writable permissions.
for directory in /app/data /app/reports /app/backups /app/web/data; do
    if [ ! -d "$directory" ]; then
        echo "BidOps runtime directory is missing: $directory" >&2
        echo "Create it and grant it to BIDOPS_UID/BIDOPS_GID before starting." >&2
        exit 78
    fi
    if [ ! -r "$directory" ] || [ ! -w "$directory" ]; then
        echo "BidOps runtime directory is not readable and writable: $directory" >&2
        echo "Use the configured non-root BIDOPS_UID/BIDOPS_GID; no chmod 777 fallback is used." >&2
        exit 78
    fi
done

if [ ! -r /app/skills ] || [ ! -r /app/docs ]; then
    echo "BidOps immutable skills/docs mount is missing or unreadable." >&2
    exit 79
fi

# In particular, do not run Alembic, create_all, policy seed, or any other
# mutating setup here. Normal app startup performs the read-only migration head
# check and exits with an actionable error for empty/lagging databases.
exec "$@"
