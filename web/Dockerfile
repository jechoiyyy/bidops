# 1단계: 프론트엔드 빌드
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

# 2단계: 백엔드 실행 이미지
FROM python:3.12-slim AS runtime

# 파이프라인 단계는 skills/ 아래 스크립트를 python3 서브프로세스로 실행한다.
# 해당 스크립트는 표준 라이브러리만 사용하므로 추가 의존성이 필요하지 않다.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BIDOPS_ROOT=/app

WORKDIR /app/web/backend
COPY web/backend/requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils clamav postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY web/backend/ ./
COPY --from=frontend /build/dist /app/web/frontend/dist
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY docs/reference /app/docs/reference
COPY scripts /app/scripts
COPY docker-compose.t7.yml /app/docker-compose.t7.yml
RUN chmod +x /app/scripts/*.sh

# 데이터베이스와 첨부 원문이 쌓이는 위치. compose 에서 볼륨으로 덮어쓴다.
# 호스트 사용자로 실행할 수 있도록 쓰기 권한을 열어 둔다.
RUN mkdir -p /app/web/data && chmod 777 /app/web/data

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health').read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
