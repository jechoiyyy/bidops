# Phase 0–2 변경 명세

[plan.md](./plan.md)의 각 작업이 만들어야 할 정확한 결과. 작업자는 이 문서의 해당 절만
구현하고, 명시되지 않은 파일은 건드리지 않는다.

공통 규칙:

- 기존 산출물 계약(`bidops.*.v*`)과 스킬 스크립트 호출 방식을 바꾸지 않는다.
- 앱 시작·entrypoint가 migrate·`create_all`·seed를 하지 않는 성질을 유지한다.
- 변경 후 `web/backend`에서 `python -m pytest -q`가 기존 통과 수를 유지해야 한다.
- 커밋하지 않는다. 작업 트리에만 변경을 남긴다.

---

## T0 — 개발 진입점 정합

### 배경

루트 `docker-compose.yml`의 `web` 서비스는 `BIDOPS_DATABASE_URL: sqlite:////app/web/data/bidops.db`를
주입하는데, `app/db.py`의 `assert_postgresql_runtime()`이 lifespan에서 이를 거부한다.
실제로 기동하면 다음으로 끝난다.

```
RuntimeError: BIDOPS_DATABASE_URL must point to PostgreSQL 17; live SQLite is forbidden
```

`docs/operations.md` 6절은 여전히 `docker compose up -d web`을 지시하고,
`.env.example`도 같은 SQLite URL을 담고 있다. 즉 문서를 그대로 따라 하면 반드시 실패한다.

애플리케이션 런타임의 정본 스택은 `docker-compose.t7.yml`이다. 루트 compose는
SQLite migration 입력 스냅숏을 다루는 `ops` profile 전용 도구로 축소한다.

### T0-1 `docker-compose.yml`

1. `services.web`를 통째로 삭제한다. `ports` 항목도 함께 사라진다.
2. 파일 상단 주석을 다음 사실로 교체한다.
   - 이 파일은 SQLite migration 입력 스냅숏을 다루는 operator 도구만 담는다.
   - 애플리케이션 런타임(`web`, `document-worker`, `analysis-worker`)은
     `docker-compose.t7.yml`이 담당한다.
   - 모든 서비스는 `ops` profile이므로 인자 없는 `docker compose up`은 아무것도 띄우지 않는다.
3. `x-bidops-runtime`의 `BIDOPS_DATABASE_URL: sqlite:////app/web/data/bidops.db`는
   **유지한다.** 삭제하지 않는다. 다만 바로 위 주석을 "이 SQLite 경로는 정본이 아니라
   `db-backup`/`db-migrate`/`db-verify`가 다루는 migration 입력 스냅숏이다"로 바꾼다.
4. `db-backup`, `db-migrate`, `db-verify`, `policy-seed` 네 서비스와
   `bidops-web-data`, `bidops-backups` volume은 그대로 둔다.

### T0-2 `.env.example`

1. `BIDOPS_DATABASE_URL=sqlite:////app/web/data/bidops.db` 줄을 삭제한다.
   그 자리에 주석을 남긴다: 애플리케이션 DB URL은 compose가 주입하며
   `.env`에서 덮어쓰지 않는다. 루트 compose의 ops 도구는 SQLite 스냅숏 경로를
   자체적으로 고정한다.
2. `BIDOPS_ROOT`, `BIDOPS_DATA_DIR`, `BIDOPS_ATTACHMENTS_DIR`는 그대로 둔다.
3. `BIDOPS_OLLAMA_BASE_URL` 주석에 한 문장을 추가한다: T7 스택에서 판정 파이프라인이
   이 endpoint를 호출하려면 `docker-compose.t7.screening.yml` 오버레이가 필요하다.

### T0-3 `docs/operations.md`

1. 「표준 Docker 순서」 6절 `web 시작 및 health`의 명령을 T7 형식으로 바꾼다.

   ```bash
   COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml \
     up -d web document-worker analysis-worker
   curl -fsS http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health
   COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml \
     logs --tail=100 web
   ```

   포트가 `8787`이 아니라 `BIDOPS_WEB_PORT`(기본 18787)라는 점을 본문에 명시한다.
2. 7절 live smoke의 `docker compose exec web ...`도 같은 `COMPOSE_PROJECT_NAME` +
   `-f docker-compose.t7.yml` 형식으로 바꾼다.
3. 1절 「서비스 중지」의 `docker compose down`도 T7 스택 기준으로 바꾸고,
   루트 compose의 `ops` profile 명령(2·3·4·5절)은 SQLite 스냅숏 도구이므로
   지금 형태를 유지한다는 한 문장을 덧붙인다.
4. 178행 장애 표의 `docker compose logs web`도 같은 형식으로 맞춘다.

### 완료 기준

- `docker compose config --services`가 `db-backup`, `db-migrate`, `db-verify`, `policy-seed`만 낸다.
- `docs/operations.md`에 `docker compose up -d web`이라는 문자열이 남아 있지 않다.
- `.env.example`에 `BIDOPS_DATABASE_URL=` 이라는 대입이 남아 있지 않다.
- 백엔드 테스트 통과 수가 유지된다.

---

## T1 — 구조화 로깅 기반

설계 근거는 `docs/legacy/review/logging-plan.md` 2절과 3-1절이다. 이 절이 그 설계의 구현 명세다.

### T1-1 `web/backend/app/redaction.py` 신설

`app/services/pipeline.py`의 `mask_secrets`(101–112행)를 이 새 모듈로 **이동**한다.

- `services/pipeline.py`는 `from ..redaction import mask_secrets`로 다시 가져온다.
  `pipeline.mask_secrets` 이름이 계속 유효해야 한다(기존 3개 호출 지점 유지).
- 새 모듈은 `re`만 import한다. `config`, `db`, `models`를 import하지 않는다.
  `logging_setup`이 import할 것이므로 순환 참조가 생기면 안 된다.
- 함수 본문과 정규식은 바꾸지 않는다.

### T1-2 `web/backend/app/logging_setup.py` 신설

```python
SAFE_KEYS = frozenset({
    "event", "execution_id", "run_id", "notice_id", "notice_pk",
    "deep_review_id", "attempt_id", "stage", "job_id", "fence",
    "worker_id", "status", "error_code", "failure_type", "retry_count",
    "duration_ms", "size_bytes", "sha256", "digest",
    "policy_version", "profile_version", "generation_config_digest",
    "queue_no", "exit_code", "http_status", "count",
})
```

- `SecretMaskingFilter(logging.Filter)`
  - `record.msg`를 `mask_secrets(str(record.msg))`로 치환한다.
  - `record.bidops`가 dict이면 `SAFE_KEYS`에 있는 키만 남긴다. dict가 아니거나 없으면 `{}`로 만든다.
  - 남긴 값 중 `str`인 것은 `mask_secrets`를 한 번 더 통과시키고 200자로 자른다.
  - 항상 `True`를 반환한다.
- `JsonFormatter(logging.Formatter)`
  - `ts`(ISO-8601, UTC), `level`, `logger`, `message`와 `record.bidops`의 키를 평평하게 합친다.
  - `record.exc_info`가 있고 traceback 옵션이 켜져 있을 때만 `traceback` 키를 넣는다.
  - `json.dumps(..., ensure_ascii=False, sort_keys=True)`로 낸다.
  - `bidops` 키가 `ts`/`level`/`logger`/`message`와 충돌하면 예약 키가 이긴다.
- `configure(settings=None) -> None`
  - `stderr` 핸들러 하나를 루트 로거에 붙인다. 필터와 포매터를 적용한다.
  - **재진입 안전해야 한다.** 두 번 호출해도 핸들러가 중복 추가되지 않는다.
  - 레벨은 `settings.log_level`, traceback 여부는 `settings.log_traceback`에서 읽는다.
  - `uvicorn.access` 로거는 `propagate = False`로 두어 쿼리 문자열이 흘러들지 않게 한다.

### T1-3 `web/backend/app/config.py`

`Settings`에 두 필드를 추가한다.

| 필드 | 환경변수 | 타입 | 기본값 |
|---|---|---|---|
| `log_level` | `BIDOPS_LOG_LEVEL` | `Literal["DEBUG","INFO","WARNING","ERROR"]` | `"WARNING"` |
| `log_traceback` | `BIDOPS_LOG_TRACEBACK` | `bool` | `False` |

`log_level`은 대소문자를 가리지 않도록 validator에서 `.upper()` 한다.
허용 목록 밖의 값은 `ValueError`로 거부한다.

### T1-4 호출 지점

세 곳에서만 `configure()`를 부른다.

1. `app/main.py`의 `lifespan` — `assert_postgresql_runtime()` 호출 **이전**,
   함수 본문 맨 앞. 기동 실패 원인이 로그에 남아야 하기 때문이다.
2. `app/workers/analysis.py`의 `main()` — `get_settings()` 직후.
3. `app/workers/document.py`의 `main()` — `get_settings()` 직후.

`configure()`가 DB나 오브젝트 스토어를 건드리면 안 된다. 기동 순서 계약을 바꾸지 않는다.

### T1-5 `.env.example`

「Optional reviewer/API settings」 근처에 추가한다.

```
# 진단 로그. 기본은 WARNING이며 로그에는 식별자와 소요 시간만 남는다.
# 프롬프트·모델 응답·자격 증명·쿼리 문자열은 어떤 레벨에서도 남기지 않는다.
BIDOPS_LOG_LEVEL=WARNING
BIDOPS_LOG_TRACEBACK=false
```

### T1-6 테스트 `web/backend/tests/test_logging_setup.py` 신설

최소 다음을 덮는다.

1. `SAFE_KEYS` 밖의 키(`prompt`, `password`, `reviewer_name` 등)가 출력에서 사라진다.
2. `api_key=abc123` 같은 메시지가 `[비밀 값]`으로 치환된다.
3. `configure()`를 두 번 불러도 핸들러가 하나다.
4. `log_traceback=False`이면 예외 로깅에 `traceback` 키가 없고, `True`이면 있다.
5. 출력 한 줄이 `json.loads`로 파싱된다.

### 완료 기준

- 기존 테스트 통과 수 유지 + 신규 테스트 통과.
- `app/logging_setup.py`가 `app.config` 외의 애플리케이션 모듈을 import하지 않는다.
- `logging.basicConfig` 호출이 코드베이스에 없다.

---

## T2 — 침묵 지점 계측

`docs/legacy/review/logging-plan.md` 3-2절의 5곳. 각 모듈 상단에
`logger = logging.getLogger(__name__)`만 두고, `configure()`는 부르지 않는다.

레벨 정책: 재시도·부분 실패·stale 회수는 `WARNING`, 실행 실패 확정은 `ERROR`,
상태 전이는 `INFO`.

| # | 파일 | 위치 | 넣을 것 |
|---|---|---|---|
| 1 | `app/workers/analysis.py` | 40행·45행의 두 `except Exception` | `logger.warning`, `event="worker.job_failed"` / `"worker.poll_failed"`, `worker_id`, `exc_info=True`. **기존 `session.rollback()`과 `pass` 동작을 바꾸지 않는다** |
| 2 | `app/workers/document.py` | 변환 루프 | 요청 claim 성공 시 `INFO event="document.claimed"`, 실패 시 `WARNING event="document.convert_failed"`. `duration_ms` 포함. 파일명·경로는 넣지 않고 `sha256`과 `size_bytes`만 |
| 3 | `app/runtime.py` | 120–122행 `except (OSError, ValueError, KeyError, TypeError): pass` | `logger.error`, `event="runtime.stage_failed"`, `stage`, `run_id`, `exc_info=True`. 반환값 `{"status": "failed", ...}`는 그대로 |
| 4 | `app/services/scheduler.py` | 326행 `except Exception: pass` (`_remove_jobs`) | `logger.warning`, `event="scheduler.job_remove_failed"`, `job_id` |
| 5 | `app/screening/queue.py` | 299·300·307행의 `raise Queue… from None` | 각 지점 직전에 `logger.warning`, `event="screening.queue_busy"` / `"screening.queue_error"`, `retry_count`. **`from None`은 그대로 둔다** — 예외 체인 삭제는 의도된 정보 차단이고, 원인은 로그로만 남긴다 |

### 금지

- 프롬프트 본문, 모델 응답 본문, 회사 자료, `BIDOPS_DATABASE_URL`, MinIO 자격 증명,
  쿼리 문자열 원문, 업로드 파일의 사용자 제공 경로, 담당자 이름.
- 예외 `str()`을 `extra`에 직접 넣는 것. 반드시 `exc_info=True`로 넘겨
  마스킹 필터와 traceback 게이트를 거치게 한다.
- 제어 흐름 변경. 이 작업은 관측만 추가하고 동작을 바꾸지 않는다.

### 완료 기준

- 기존 테스트 통과 수 유지.
- 다섯 지점 모두 실패 시 최소 한 줄의 구조화 로그를 낸다.
- `except` 절의 반환값·재발생·롤백 동작이 이전과 동일하다.

---

## T3 — T7 산출물 지속성

### 배경

`docker-compose.t7.yml`의 `web`은 `document-scratch:/scratch`만 마운트한다.
`/app/data`(회차 원본과 `screening-executions/`)와 `/app/reports`가 컨테이너 계층에만 있어
`docker compose up --force-recreate` 한 번에 사라진다. `web/AGENTS.md`가 요구하는
산출물 보존과 어긋난다.

`docs/operations.md`는 "일상 운영에서 host 실데이터 bind mount를 사용하지 않는다"고 정한다.
따라서 host bind mount가 아니라 **named volume**으로 해결한다.

### 변경

`docker-compose.t7.yml`만 수정한다.

1. `services.web.volumes`에 두 항목을 추가한다. `document-scratch:/scratch`는 유지한다.
   ```yaml
   volumes:
     - document-scratch:/scratch
     - pipeline-data:/app/data
     - pipeline-reports:/app/reports
   ```
2. 최상위 `volumes:`에 `pipeline-data:`와 `pipeline-reports:`를 추가한다.
3. 두 항목 위에 주석으로 근거를 남긴다: 회차 원본과 보고서는 컨테이너 재생성보다 오래 살아야 하며,
   프로젝트 이름으로 격리된 named volume이므로 host 실데이터를 bind mount하지 않는다.
   host에서 꺼낼 때는 `docker compose cp`를 쓴다.

`document-worker`, `analysis-worker`, `postgres`, `minio`는 건드리지 않는다.
`analysis-worker`에 `/app/data`를 주지 않는다 — 이 워커는 오브젝트 스토어만 읽는다.

### 완료 기준

- `test_t7_worker_network_and_command_boundaries_are_explicit`가 계속 통과한다
  (이 테스트는 `"document-scratch:/scratch" in web["volumes"]`를 확인하므로 추가는 안전하다).
- `docker compose -f docker-compose.t7.yml config`가 오류 없이 파싱된다.

---

## T4 — 판정 egress 오버레이

### 배경

`docker-compose.t7.yml`의 네 network는 모두 `internal: true`다. 판정 워커 스레드와
`collect_notices.py`는 `web` 컨테이너 안에서 돌지만, `web`에는 외부로 나가는 network가 없다.
따라서 T7 스택에서는 Ollama(`http://192.168.0.139:11434`)와 나라장터 API 호출이 모두 실패한다.

`analysis-worker`의 vLLM egress는 이미 `docker-compose.t7.remote-vllm.yml`이 오버레이로
제공한다. 같은 방식으로 판정 쪽 egress를 **명시적 opt-in 오버레이**로 만든다.
기본 스택의 격리는 그대로 둔다.

### 신설 `docker-compose.t7.screening.yml`

```yaml
# 판정 파이프라인(단계 A) 전용 egress 오버레이.
# `web` 컨테이너 안의 판정 워커 스레드가 승인된 Ollama endpoint를,
# collect 단계가 나라장터 OpenAPI를 호출해야 할 때만 명시적으로 추가한다.
# 기본 docker-compose.t7.yml의 격리는 이 파일 없이는 유지된다.
# host 방화벽에서 승인된 IP/port 외 egress를 차단한 뒤에 사용한다.
services:
  web:
    networks: [database, storage, scanning, screening-egress]
    environment:
      BIDOPS_OLLAMA_BASE_URL: "${BIDOPS_OLLAMA_BASE_URL:?set an approved Ollama endpoint}"
      BIDOPS_OLLAMA_MODEL: "${BIDOPS_OLLAMA_MODEL:-qwen3.8:27b}"

networks:
  screening-egress:
```

- network 이름은 `model-egress`(vLLM 전용)와 **분리한다.** 두 오버레이를 함께 쓸 수 있어야 하고,
  방화벽 규칙을 endpoint별로 걸 수 있어야 한다.
- `BIDOPS_OLLAMA_BASE_URL`은 기본값 없는 `:?` 형태로 둔다. 실수로 loopback을 향한 채
  판정이 도는 것보다 기동 실패가 낫다.
- `analysis-worker`, `document-worker`는 이 오버레이에 넣지 않는다.

### 테스트 `web/backend/tests/test_t7_runtime_contract.py`

`test_remote_vllm_egress_is_an_explicit_override` 바로 아래에 같은 형태로 추가한다.

```python
def test_screening_egress_is_an_explicit_override():
    override = yaml.safe_load((ROOT / "docker-compose.t7.screening.yml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"web"}
    assert set(override["services"]["web"]["networks"]) == {
        "database", "storage", "scanning", "screening-egress",
    }
    assert override["networks"] == {"screening-egress": None}
    base = yaml.safe_load((ROOT / "docker-compose.t7.yml").read_text(encoding="utf-8"))
    assert "screening-egress" not in base["networks"]
    assert all(network.get("internal") is True for network in base["networks"].values())
```

### `.env.example`

`BIDOPS_OLLAMA_BASE_URL` 주석에 이 오버레이 파일 이름을 적는다(T0-2에서 이미 반영).

### 완료 기준

- 새 테스트를 포함해 백엔드 테스트 전량 통과.
- `docker compose -f docker-compose.t7.yml -f docker-compose.t7.screening.yml config`가
  `BIDOPS_OLLAMA_BASE_URL`이 설정된 환경에서 오류 없이 파싱된다.
- 기본 `docker-compose.t7.yml`의 network 네 개가 모두 `internal: true`로 남는다.
