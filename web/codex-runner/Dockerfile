FROM node:22.16.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/* \
    && npm install --global @openai/codex@0.162.1
WORKDIR /app
COPY web/codex-runner/runner.py /app/runner.py
COPY web/backend/app/deep_review/contracts/bidops.deep-review-stage.v2.json /app/stage.json
COPY web/backend/app/deep_review/contracts/bidops.assumption-stage.v1.json /app/assumption.json
COPY web/backend/app/deep_review/contracts/bidops.requirement-extract.v1.json /app/card-extract.json
COPY web/backend/app/deep_review/contracts/bidops.requirement-extract.v2.json /app/card-extract-v2.json
COPY web/backend/app/deep_review/contracts/bidops.verdict-role.v1.json /app/card-role.json
COPY web/backend/app/deep_review/contracts/bidops.verdict-role.v2.json /app/card-role-v2.json
COPY web/backend/app/deep_review/contracts/bidops.practitioner-verdict.v1.json /app/card-synthesis.json
COPY web/backend/app/deep_review/contracts/bidops.practitioner-verdict.v2.json /app/card-synthesis-v2.json
COPY web/backend/app/deep_review/contracts/bidops.proposal-section.v1.json /app/proposal-section.json
USER node
CMD ["python3", "/app/runner.py"]
