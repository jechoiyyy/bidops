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

.PHONY: help up start stop restart status logs health check-containers

help:
	@printf '%s\n' \
	  'make up       기존 웹 서버와 필요한 서비스 시작 (make start와 동일)' \
	  'make stop     웹 서버만 중지; DB·저장소·worker 유지' \
	  'make restart  웹 서버만 재시작; 기존 컨테이너·UI 유지' \
	  'make status   웹 서버와 필요한 서비스 상태 확인' \
	  'make logs     웹 로그 실시간 확인 (Ctrl+C로 종료)' \
	  'make health   API와 화면 응답 확인' \
	  '' \
	  '옵션: COMPOSE_PROJECT_NAME=bidops WAIT_TIMEOUT=60 LOG_TAIL=100' \
	  '최초 설치·새 이미지 배포: docs/operations.md 참고'

up: start

start: check-containers
	$(COMPOSE) start --wait --wait-timeout "$(WAIT_TIMEOUT)" $(SERVER_SERVICES)

stop:
	$(COMPOSE) stop web

restart:
	$(COMPOSE) restart --no-deps web

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
