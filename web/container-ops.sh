#!/bin/sh
set -eu

command_name=${1:-}
if [ "$#" -gt 0 ]; then
    shift
fi

case "$command_name" in
    backup)
        if [ "$#" -ne 0 ]; then
            echo "usage: backup (set BIDOPS_BACKUP_OUTPUT to override the output path)" >&2
            exit 2
        fi
        output=${BIDOPS_BACKUP_OUTPUT:-/app/backups/bidops-$(date -u +%Y%m%dT%H%M%SZ).db}
        exec python -m app.db_admin backup --output "$output"
        ;;
    migrate)
        if [ "$#" -ne 0 ]; then
            echo "usage: migrate (set BIDOPS_BACKUP_MANIFEST and BIDOPS_CONFIRM_SERVICE_STOPPED=true)" >&2
            exit 2
        fi
        if [ "${BIDOPS_CONFIRM_SERVICE_STOPPED:-}" != "true" ]; then
            echo "refusing to migrate: stop the web service and set BIDOPS_CONFIRM_SERVICE_STOPPED=true" >&2
            exit 2
        fi
        manifest=${BIDOPS_BACKUP_MANIFEST:-}
        if [ -z "$manifest" ]; then
            echo "refusing to migrate: set BIDOPS_BACKUP_MANIFEST to the retained backup manifest" >&2
            exit 2
        fi
        exec python -m app.db_admin migrate \
            --backup-manifest "$manifest" \
            --confirm-service-stopped
        ;;
    verify)
        if [ "$#" -ne 0 ]; then
            echo "usage: verify" >&2
            exit 2
        fi
        exec python -m app.db_admin verify
        ;;
    seed-policy)
        if [ "$#" -ne 0 ]; then
            echo "usage: seed-policy (set BIDOPS_POLICY_SEED_ACTOR)" >&2
            exit 2
        fi
        actor=${BIDOPS_POLICY_SEED_ACTOR:-}
        if [ -z "$actor" ]; then
            echo "refusing to seed policy: set non-empty BIDOPS_POLICY_SEED_ACTOR" >&2
            exit 2
        fi
        exec python -m app.screening.policy seed-default --created-by "$actor"
        ;;
    *)
        echo "unknown operator command: ${command_name:-<empty>} (backup, migrate, verify, seed-policy)" >&2
        exit 2
        ;;
esac
