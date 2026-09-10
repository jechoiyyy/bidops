.DEFAULT_GOAL := help

COMPOSE_PROJECT_NAME ?= bidops
# edge overlay는 선택이 아니다. base의 web은 internal network에만 붙어 있어
# 이 파일 없이 재생성하면 포트 publish가 조용히 사라진다.
COMPOSE := docker compose -p "$(COMPOSE_PROJECT_NAME)" -f docker-compose.yml -f docker-compose.edge.yml
WAIT_TIMEOUT ?= 60
LOG_TAIL ?= 100

# Reuse installed containers, including their deployment settings and static UI.
# Keep initialization jobs and model/collection workers outside daily web startup.
SERVER_SERVICES := postgres minio clamav document-worker web

.PHONY: help up start stop down restart status logs health build check-containers

help:
	@printf '%s\n' \
	  'make up       기존 웹 서버와 필요한 서비스 시작 (make start와 동일)' \
	  'make stop     웹 서버만 중지; DB·저장소·worker 유지' \
	  'make down     현재 Compose 프로젝트의 모든 서비스 중지; 컨테이너·volume 유지' \
	  'make restart  웹 서버만 재시작; 기존 컨테이너·UI 유지' \
	  'make status   웹 서버와 필요한 서비스 상태 확인' \
	  'make logs     웹 로그 실시간 확인 (Ctrl+C로 종료)' \
	  'make health   API와 화면 응답 확인' \
	  'make build    모든 Compose 이미지 빌드; 기존 컨테이너는 갱신하지 않음' \
	  '' \
	  '옵션: COMPOSE_PROJECT_NAME=bidops WAIT_TIMEOUT=60 LOG_TAIL=100' \
	  '최초 설치·새 이미지 배포: docs/operations.md 참고'

up: start

start: check-containers
	@set -eu; \
	  postgres_ids="$$($(COMPOSE) ps --all --quiet postgres)"; \
	  minio_ids="$$($(COMPOSE) ps --all --quiet minio)"; \
	  clamav_ids="$$($(COMPOSE) ps --all --quiet clamav)"; \
	  document_worker_ids="$$($(COMPOSE) ps --all --quiet document-worker)"; \
	  web_ids="$$($(COMPOSE) ps --all --quiet web)"; \
	  if [ -z "$$postgres_ids" ] || [ -z "$$minio_ids" ] || [ -z "$$clamav_ids" ] \
	    || [ -z "$$document_worker_ids" ] || [ -z "$$web_ids" ]; then \
	    printf '%s\n' '필요한 기존 컨테이너가 모두 있어야 시작할 수 있습니다. docs/operations.md의 최초 기동 절차를 먼저 진행하세요.' >&2; \
	    exit 1; \
	  fi; \
	  for id in $$postgres_ids $$minio_ids $$clamav_ids $$document_worker_ids; do \
	    state="$$(docker inspect --format '{{.State.Status}}' "$$id")"; \
	    if [ "$$state" != running ]; then docker start "$$id" >/dev/null; fi; \
	  done; \
	  deadline=$$(( $$(date +%s) + $(WAIT_TIMEOUT) )); \
	  while :; do \
	    postgres_ready=true; postgres_health=unknown; \
	    for id in $$postgres_ids; do \
	      postgres_health="$$(docker inspect --format '{{.State.Health.Status}}' "$$id")"; \
	      [ "$$postgres_health" = healthy ] || postgres_ready=false; \
	    done; \
	    minio_ready=true; minio_health=unknown; \
	    for id in $$minio_ids; do \
	      minio_health="$$(docker inspect --format '{{.State.Health.Status}}' "$$id")"; \
	      [ "$$minio_health" = healthy ] || minio_ready=false; \
	    done; \
	    clamav_ready=true; clamav_state=unknown; \
	    for id in $$clamav_ids; do \
	      clamav_state="$$(docker inspect --format '{{.State.Status}}' "$$id")"; \
	      [ "$$clamav_state" = running ] || clamav_ready=false; \
	    done; \
	    worker_ready=true; worker_state=unknown; \
	    for id in $$document_worker_ids; do \
	      worker_state="$$(docker inspect --format '{{.State.Status}}' "$$id")"; \
	      [ "$$worker_state" = running ] || worker_ready=false; \
	    done; \
	    if [ "$$postgres_ready" = true ] && [ "$$minio_ready" = true ] \
	      && [ "$$clamav_ready" = true ] && [ "$$worker_ready" = true ]; then break; fi; \
	    if [ $$(date +%s) -ge $$deadline ]; then \
	      printf '기반 서비스 준비 시간 초과: postgres=%s minio=%s clamav=%s document-worker=%s\n' \
	        "$$postgres_health" "$$minio_health" "$$clamav_state" "$$worker_state" >&2; \
	      exit 1; \
	    fi; \
	    sleep 1; \
	  done; \
	  for id in $$web_ids; do \
	    state="$$(docker inspect --format '{{.State.Status}}' "$$id")"; \
	    if [ "$$state" != running ]; then docker start "$$id" >/dev/null; fi; \
	  done; \
	  while :; do \
	    binding="$$($(COMPOSE) port web 8787 2>/dev/null || true)"; \
	    port="$${binding##*:}"; \
	    if [ -n "$$port" ]; then \
	      base_url="http://127.0.0.1:$$port"; \
	      if curl --fail --silent --show-error --connect-timeout 1 --max-time 3 "$$base_url/api/health" >/dev/null \
	        && curl --fail --silent --show-error --connect-timeout 1 --max-time 3 --output /dev/null "$$base_url/"; then \
	        printf 'API·화면 응답 정상: %s\n' "$$base_url"; \
	        break; \
	      fi; \
	    fi; \
	    if [ $$(date +%s) -ge $$deadline ]; then \
	      printf '웹 API·화면 준비 시간 초과 (WAIT_TIMEOUT=%s)\n' '$(WAIT_TIMEOUT)' >&2; \
	      exit 1; \
	    fi; \
	    sleep 1; \
	  done

stop:
	$(COMPOSE) stop web

down:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart --no-deps web

build:
	$(COMPOSE) build

status:
	$(COMPOSE) ps --all $(SERVER_SERVICES)

logs:
	$(COMPOSE) logs --follow --tail "$(LOG_TAIL)" web

# Read the installed port mapping rather than guessing from a changed .env file.
health:
	@set -eu; \
	  binding="$$($(COMPOSE) port web 8787)"; \
	  port="$${binding##*:}"; \
	  test -n "$$port"; \
	  base_url="http://127.0.0.1:$$port"; \
	  curl --fail --silent --show-error --connect-timeout 3 --max-time 10 "$$base_url/api/health"; \
	  printf '\n'; \
	  curl --fail --silent --show-error --connect-timeout 3 --max-time 10 --output /dev/null "$$base_url/"; \
	  printf 'API·화면 응답 정상: %s\n' "$$base_url"

check-containers:
	@set -eu; \
	  for service in $(SERVER_SERVICES); do \
	    containers="$$($(COMPOSE) ps --all --quiet "$$service")"; \
	    if [ -z "$$containers" ]; then \
	      printf '%s\n' "$$service 컨테이너가 없습니다. docs/operations.md의 최초 기동 절차를 먼저 진행하세요." >&2; \
	      exit 1; \
	    fi; \
	  done
