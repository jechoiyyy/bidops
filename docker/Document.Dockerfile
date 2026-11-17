# syntax=docker/dockerfile:1.7
# Native conversion: no ignored source trees, prebuilt local images, or credentials.
FROM rust:1.93.1-slim-bookworm AS rhwp-builder
ENV CARGO_BUILD_JOBS=2
RUN apt-get update && apt-get install --no-install-recommends --yes git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/edwardkim/rhwp.git \
    && git fetch --depth=1 origin cac9b4f7cc743535cd7c00fe4f286abd67e7145b \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = cac9b4f7cc743535cd7c00fe4f286abd67e7145b \
    && cargo build --release --locked --bin rhwp \
    && target/release/rhwp --version | grep -Fx 'rhwp v0.8.6'

FROM python:3.12-slim-bookworm AS runtime
ARG BIDOPS_UID=1000
ARG BIDOPS_GID=1000
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BIDOPS_ROOT=/app BIDOPS_DOCUMENT_SCRATCH_DIR=/scratch \
    BIDOPS_OPENAI_ENABLED=false BIDOPS_C2_EXECUTION_ALLOWED=false
WORKDIR /app/web/backend
COPY web/backend/requirements-document.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes -r requirements.lock \
    && python -m pip check \
    && apt-get update \
    && apt-get install --no-install-recommends --yes fontconfig fonts-nanum fonts-noto-cjk poppler-utils \
    && rm -rf /var/lib/apt/lists/*
RUN case "$BIDOPS_UID:$BIDOPS_GID" in \
      0:*|*:0|*[!0-9:]*|*:|:*) echo 'Nonzero numeric UID/GID required' >&2; exit 1 ;; esac \
    && groupadd --gid "$BIDOPS_GID" bidops \
    && useradd --uid "$BIDOPS_UID" --gid "$BIDOPS_GID" --create-home --shell /usr/sbin/nologin bidops \
    && install -d -o bidops -g bidops -m 0770 /scratch /app/data /app/web/data /app/web/data/attachments
COPY web/backend/app ./app
COPY --from=rhwp-builder /src/target/release/rhwp /app/web/backend/app/deep_review/document_mcp/vendor/rhwp/bin/rhwp
# The source contract stays pinned; only the native binary's manifest row changes.
RUN cd app/deep_review/document_mcp/vendor \
    && test "$(grep -Fxc 'c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c  rhwp/bin/rhwp' SHA256SUMS)" = 1 \
    && cp SHA256SUMS /usr/local/share/bidops-vendor-SHA256SUMS.amd64 \
    && built_sha="$(sha256sum rhwp/bin/rhwp | cut -d ' ' -f 1)" \
    && sed -i "s/^c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c  rhwp\/bin\/rhwp$/$built_sha  rhwp\/bin\/rhwp/" SHA256SUMS \
    && sha256sum --check --strict SHA256SUMS \
    && chmod 0555 rhwp/bin/rhwp
USER bidops:bidops
CMD ["python", "-m", "app.deep_review.workers.document"]
