# syntax=docker/dockerfile:1

# Keep the frontend build isolated from the runtime image. npm ci consumes the
# committed lockfile, so a build cannot silently resolve another dependency tree.
FROM node:22-alpine AS frontend

WORKDIR /build
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend/ ./
RUN npm run build

# The document worker executes the pinned HWP converter with Node.  Keep the
# runtime binary in the application image while its processing network remains
# isolated by Compose.
FROM node:22-bookworm-slim AS node-runtime

# Build-time UID/GID defaults match .env.example and may be changed to the host
# account. The image never creates an operating database, .env, API key, or run
# data.
FROM python:3.12-slim AS runtime

ARG BIDOPS_UID=1000
ARG BIDOPS_GID=1000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BIDOPS_ROOT=/app \
    BIDOPS_DATA_DIR=/app/web/data \
    BIDOPS_ATTACHMENTS_DIR=/app/web/data/attachments \
    BIDOPS_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    BIDOPS_SCHEDULER_ENABLED=false

WORKDIR /app/web/backend
COPY web/backend/requirements.lock ./
RUN python -m pip install --no-cache-dir --no-deps --only-binary=:all: \
        --require-hashes --requirement requirements.lock \
    && python -m pip check

# poppler-utils, clamav, and postgresql-client are document-pipeline and
# PostgreSQL operator tools. Git is retained only as an optional
# source-inspection tool: the image has no repository metadata, and the wrapper
# below serves the one exact baseline lookup needed by the compatibility test
# and delegates all other commands to Git.
RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        git poppler-utils clamav postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Refuse root as a build-time application identity and create a stable runtime
# account. Compose may set the same numeric IDs to match the host account.
RUN case "$BIDOPS_UID:$BIDOPS_GID" in \
        0:*|*:0) echo 'BIDOPS_UID and BIDOPS_GID must be non-zero' >&2; exit 1 ;; \
        *[!0-9:]*|*:|:*) echo 'BIDOPS_UID and BIDOPS_GID must be numeric' >&2; exit 1 ;; \
    esac \
    && groupadd --gid "$BIDOPS_GID" bidops \
    && useradd --uid "$BIDOPS_UID" --gid "$BIDOPS_GID" --create-home --shell /usr/sbin/nologin bidops

COPY web/backend/ ./
COPY --from=frontend /build/dist /app/web/frontend/dist
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY scripts /app/scripts
COPY docker-compose.t7.yml /app/docker-compose.t7.yml
RUN chmod +x /app/scripts/*.sh

# Bundle the immutable execution contract as a fallback for docker run.
# The T7 web service supplies the current company profile as a read-only bind
# mount; the profile and its source documents are intentionally not copied.
# Only the non-sensitive runtime reference material needed by the collection
# subprocess is copied below.
COPY skills/ /app/skills/
COPY docs/reference/company-performance-titles.tsv /app/docs/reference/company-performance-titles.tsv
COPY skills/references/ /app/skills/references/
COPY web/container-entrypoint.sh /usr/local/bin/bidops-entrypoint
COPY web/container-ops.sh /usr/local/bin/bidops-ops
COPY web/container-git-wrapper.sh /usr/local/bin/git

# Data, report, backup, and scratch roots are group-writable, not
# world-writable. A named volume inherits these permissions on first use, so
# every mount point a non-root service writes to must exist here first;
# Docker otherwise creates the volume root-owned and the service cannot start.
# /scratch is the document-converter handoff shared by web and document-worker.
RUN install -d -o bidops -g bidops -m 0770 \
        /app/data /app/reports /app/backups /app/web/data \
        /app/web/data/attachments /app/web/data/profile-snapshots /scratch \
    && chmod 0555 /usr/local/bin/bidops-entrypoint /usr/local/bin/bidops-ops /usr/local/bin/git \
    && chown -R root:root /app/skills /app/docs \
    && find /app/skills /app/docs -type d -exec chmod 0555 {} + \
    && find /app/skills /app/docs -type f -exec chmod 0444 {} + \
    && chown -R bidops:bidops /app/web/backend /app/web/frontend/dist

USER bidops:bidops

EXPOSE 8787

# Python's standard library HTTP client is present in every supported runtime;
# health does not contact Ollama or any external API.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; response=urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3); raise SystemExit(0 if response.status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/bidops-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
