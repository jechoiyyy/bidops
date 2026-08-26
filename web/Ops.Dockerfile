# Isolated recovery/backup runtime.  This profile is never started by the
# application stack; operators inject external credentials and target paths at
# invocation time.  It deliberately contains both pinned mc and PostgreSQL
# client/coreutils binaries so mounted scripts do not depend on host tooling.
FROM minio/mc:RELEASE.2025-08-13T08-35-41Z AS minio-client

FROM python:3.12-slim
COPY --from=minio-client /usr/bin/mc /usr/local/bin/mc
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client coreutils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts /opt/bidops/scripts
RUN chmod +x /opt/bidops/scripts/*.sh
WORKDIR /work
ENTRYPOINT ["/bin/sh"]
