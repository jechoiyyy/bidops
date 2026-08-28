# 웹 통합 모듈 작업 규칙

## 책임

이 모듈은 frontend build와 FastAPI runtime image, PostgreSQL·MinIO·ClamAV·worker Compose 조립, 목적별 network overlay, 통합 검증 진입점을 소유한다. 업무 판정 로직과 화면 컴포넌트를 Dockerfile이나 Compose에 구현하지 않는다.

## 배포 경계

- `docker-compose.t7.yml`이 애플리케이션 스택이다. 루트 Compose의 ops profile을 웹 런타임으로 바꾸지 않는다.
- 기본 database, storage, scanning, analysis network는 internal이다. Ollama·나라장터, 사설 vLLM egress는 서로 다른 명시적 overlay로만 연다.
- `document-worker`는 network 없이 scratch request만 처리한다. 자격증명이나 HTTP listener를 추가하지 않는다.
- 이미지에 `.env`, API key, DB dump, 객체 원문, run, report, 회사자료를 복사하지 않는다.
- PostgreSQL, MinIO, pipeline data, report는 project-scoped volume으로 보존한다. 다른 Compose project의 volume을 공유하거나 삭제하지 않는다.

## 런타임 불변 조건

- 컨테이너는 non-root로 동작하고 쓰기 경로는 image build 시 생성한다. named volume이 root 소유로 생겨 런타임 chown이 필요해지는 구성을 만들지 않는다.
- web은 8787에서 API와 production frontend를 제공한다. frontend build가 없으면 API는 기동하되 화면 요청은 503을 반환한다.
- API route가 SPA fallback보다 먼저 매칭되어야 한다.
- healthcheck는 내부 `/api/health`만 사용하고 나라장터, 모델, 외부 인터넷을 호출하지 않는다.
- 앱 startup은 DB migration, MinIO policy 생성, seed, 모델 호출을 수행하지 않는다. 초기화 서비스가 성공한 뒤 web과 worker를 시작한다.
- screening worker concurrency와 analysis worker concurrency는 각각 1이다. document worker만 계약된 replica 수로 실행한다.

## 변경 패턴

- Python image는 exact lockfile을 설치하고 frontend는 lockfile 기반 production build를 사용한다.
- network 변경은 source와 destination, protocol, port, 필요한 service를 최소 범위로 적고 기본 stack에 광범위 egress를 추가하지 않는다.
- 새 persistent path는 backup·restore·ownership·container recreation 검증을 함께 추가한다.
- 새 secret은 외부 주입 placeholder, 해당 service만의 environment, 로그 마스킹 검증을 함께 추가한다.
- 운영 명령은 명시적 `COMPOSE_PROJECT_NAME`을 요구하고 `down -v`나 자동 volume 정리를 포함하지 않는다.

## 검증

```bash
./web/run-web-tests.sh
COMPOSE_PROJECT_NAME=bidops-verify docker compose -f docker-compose.t7.yml build
COMPOSE_PROJECT_NAME=bidops-verify docker compose -f docker-compose.t7.yml config
```

임시 project에서 health, SPA, migration-before-start, internal network, worker 자격증명, volume 재생성 후 데이터 보존, non-root 쓰기 권한을 확인한다. 검증용 project만 제거하며 운영 volume은 건드리지 않는다.
