# 로깅 도입 계획

- 기준일: 2026-08-27
- 대상: `web/backend`
- 목적: 개발·테스트 중 "왜 실패했는지"를 재현 없이 알 수 있게 한다

---

## 1. 현재 상태

### 1-1. 백엔드에 로거가 하나도 없다

```bash
$ grep -rn "import logging" web/backend/app/
(결과 없음)
```

`app/` 전체 (약 40,000 라인)에 `logging` import가 **0건**이다. `print()`는
CLI 진입점(`db_admin.py`, `screening/cli.py`, `ingest/cli.py`, `cli/*.py`)에만 있고
서비스·워커·라우터에는 없다. uvicorn 접근 로그만 남는다.

### 1-2. 예외 정보를 의도적으로 버리고 있다

| 패턴 | 건수 | 의미 |
|---|---:|---|
| `raise … from None` | 153 | 원인 예외 체인을 **삭제**한다 |
| `except Exception` | 92 | 광범위하게 잡는다 |
| `except …: pass` / `continue` | 40+ | 조용히 넘어간다 |

가장 극단적인 예가 `app/workers/analysis.py`다.

```python
except Exception:
    # Connection/claim failures are retried on the bounded interval;
    # no exception contents are logged because they may contain DSN
    # material or provider details.
    pass
```

analysis worker가 DB 접속 실패, 자격 증명 오류, provider 오류 중 무엇으로
죽고 있는지 **바깥에서 알 방법이 전혀 없다.** 컨테이너는 정상 기동한 채
아무 일도 하지 않는다.

이 설계는 의도적이며 근거가 있다. `docs/security.md`는 API 키·회사 자료·DSN이
로그에 노출되는 것을 보고 대상 사고로 규정한다. 문제는 "노출 금지"를
"기록 금지"로 구현했다는 점이다. 개발·테스트 단계에서는 이 비용이 너무 크다.

### 1-3. 이미 있는 관측 수단 (중복 구현 금지)

새 로거를 넣기 전에, 이미 **DB에 영구 보존되는** 기록을 먼저 알아야 한다.

| 저장소 | 내용 | 조회 |
|---|---|---|
| `screening_audit_event` | 판정 런타임·스케줄러 감사 (append-only) | SQL |
| `audit_event` | Lean v1 변경 경계 (actor 이름 포함) | SQL |
| `ingest_warning` | 적재 경고 (level·code·message·context) | `GET /api/runs/{id}/warnings` |
| `screening_attempt` | 공고별 시도, 실패 유형, 재시도 횟수 | `GET /api/screening/executions/{id}` |
| `deep_review_stage.invocation_metadata` | stage별 모델 호출 metadata | `GET /api/deep-reviews/{id}` |
| `work_job.last_error_code` | 심층 검토 job 실패 코드 | SQL |
| `schedule_execution.failure_reason` | 스케줄 실행 실패 사유 | `GET /api/schedule/executions` |
| `PipelineService.lines` | subprocess stdout/stderr (마스킹됨) | `GET /api/runs/{id}/pipeline/logs` |

**로깅이 채워야 할 공백은 이것들이 아니다.** 위 기록은 전부 "무엇이 실패했다"는
*분류*까지만 남긴다. 없는 것은 "어떤 값 때문에 그 분류가 나왔는가"이고,
`from None` 153건이 정확히 그 정보를 버리고 있다.

또 하나: `PipelineService.lines`는 **프로세스 메모리에만** 있다. 컨테이너를
재시작하면 파이프라인 로그 전체가 사라진다.

---

## 2. 설계 원칙

1. **구조화 로그만 남긴다.** 자유 문자열이 아니라 고정 키의 `extra` dict.
   허용 목록에 없는 필드는 애초에 넣지 않는다.
2. **마스킹은 선택이 아니라 필터다.** 개별 호출자가 기억해서 마스킹하는 대신,
   `logging.Filter`가 모든 레코드에 강제 적용된다.
3. **원문·프롬프트·모델 응답·회사 자료는 로그에 넣지 않는다.**
   식별자(execution_id, notice_id, sha256, digest)와 크기·시간만 남긴다.
4. **기존 DB 감사 기록을 로그로 복제하지 않는다.** 로그는 휘발성 진단용,
   DB는 정본이다.
5. **레벨 정책**
   | 레벨 | 용도 |
   |---|---|
   | `DEBUG` | 단계 진입/이탈, 선택된 정책·프로필 digest. 개발에서만 켠다 |
   | `INFO` | 상태 전이 (enqueue, claim, publish, ingest 완료) |
   | `WARNING` | 재시도, 부분 실패, stale 회수, lease 만료 |
   | `ERROR` | 실행 실패로 확정된 지점. **여기에 `exc_info`를 붙인다** |
6. 기본 레벨은 `WARNING`. `BIDOPS_LOG_LEVEL`로 올린다.
   `BIDOPS_LOG_TRACEBACK=1`을 명시하지 않으면 `exc_info`를 출력하지 않는다
   (운영 기본값은 코드만, 개발은 traceback 포함).

---

## 3. 도입 순서

### 3-1. 공통 모듈 신설 — `app/logging_setup.py`

```python
"""구조화 로깅 설정. 마스킹은 필터에서 강제한다."""

import logging, json, os
from .services.pipeline import mask_secrets   # 이미 있는 마스커 재사용

SAFE_KEYS = frozenset({
    "event", "execution_id", "run_id", "notice_id", "notice_pk",
    "deep_review_id", "attempt_id", "stage", "job_id", "fence",
    "worker_id", "status", "error_code", "failure_type", "retry_count",
    "duration_ms", "size_bytes", "sha256", "digest",
    "policy_version", "profile_version", "generation_config_digest",
    "queue_no", "exit_code", "http_status",
})

class SecretMaskingFilter(logging.Filter):
    def filter(self, record):
        record.msg = mask_secrets(str(record.msg))
        record.bidops = {k: v for k, v in getattr(record, "bidops", {}).items()
                         if k in SAFE_KEYS}
        return True

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **getattr(record, "bidops", {}),
        }
        if record.exc_info and os.getenv("BIDOPS_LOG_TRACEBACK") == "1":
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

def configure() -> None: ...
```

호출 지점은 두 곳뿐이다.

- `app/main.py`의 `lifespan` 시작 시
- `app/workers/analysis.py` / `app/workers/document.py`의 `main()` 시작 시

라우터·서비스는 모듈 상단에서 `logger = logging.getLogger(__name__)`만 한다.

### 3-2. 1순위 — 지금 완전히 침묵하는 지점 (5곳)

이것만 해도 개발 중 체감이 가장 크게 바뀐다.

| 파일 | 위치 | 넣을 것 |
|---|---|---|
| `app/workers/analysis.py` | 두 `except Exception: pass` | `logger.warning("analysis worker poll failed", extra={"bidops": {"event": "worker.poll_failed", "worker_id": …}}, exc_info=True)` |
| `app/workers/document.py` | `convert_one` 루프 | 요청 claim 성공/실패, 변환 소요 시간 |
| `app/runtime.py:120` | `except (OSError, ValueError, KeyError, TypeError): pass` — `RuntimePipelineBridge.run_stage` | 어떤 stage가 어떤 예외로 실패했는지. **현재 `{"status":"failed"}`만 남고 원인이 전부 사라진다** |
| `app/services/scheduler.py:326` | `except Exception` | 스케줄 콜백 실패 |
| `app/screening/queue.py` | `QueueBusy` / `QueueDatabaseError` 전환 (`from None`) | busy 재시도 횟수와 최종 포기 |

### 3-3. 2순위 — 판정 파이프라인 (A)

| 파일 | 함수 | 이벤트 |
|---|---|---|
| `app/screening/orchestrator.py` | `create*` | `screening.enqueued` (execution_id, run_id, scope, policy_version, profile_version, generation_config_digest, candidate_count) |
| `app/screening/queue.py` | claim | `screening.claimed` / `screening.slot_released` / `screening.stale_recovered` |
| `app/screening/worker.py` | `_process` | `screening.started` / `screening.finished` (duration_ms, result_count, failure_count) |
| `app/screening/worker.py` | `_run_notice` | 공고별 `screening.notice_ok` / `screening.notice_failed` (notice_id, stage, failure_type, retry_count) |
| `app/screening/worker.py` | `_verify_binding` | digest 불일치 시 `ERROR` + 기대/실제 digest **양쪽** |
| `app/screening/worker.py` | `_merge` | subprocess `returncode`, stderr 앞 500자(마스킹). **현재 `WorkerError("execution_failure")` 한 줄로 뭉개진다** |
| `app/screening/worker.py` | `_publish` | 발행 대상 디렉토리명, 실패 시 정리 결과 |
| `app/screening/ollama.py` | `generate` | `model.call` (stage, duration_ms, prompt/completion tokens, done_reason). 프롬프트 본문은 절대 금지 |
| `app/ingest/loader.py` | `ingest_run` | `ingest.done` (run_id, notices, judgments, reviews, warning_counts) |
| `app/services/pipeline.py` | `_execute` | 시작·종료·exit_code. **로그 라인을 파일로도 남길지 결정 필요** (아래 5절) |

### 3-4. 3순위 — 심층 검토 파이프라인 (B)

| 파일 | 함수 | 이벤트 |
|---|---|---|
| `app/services/deep_reviews.py` | `claim_next_job` | `deep_review.claimed` / `reclaimed` (job_id, fence, worker_id) |
| `app/services/deep_reviews.py` | `run_claim` | stage별 시작·완료·소요 시간 |
| `app/services/deep_reviews.py` | `_fail_claim` | `ERROR` + error_code + invocation metadata 요약 |
| `app/services/deep_reviews.py` | `_renew_lease` | 갱신 실패(=fence 탈취) 시 `WARNING` |
| `app/services/vllm_client.py` | `invoke` | 시도별 http_status, duration_ms, 재시도 사유. 응답 본문 금지 |
| `app/services/document_bundles.py` | `upload_document` | 격리 → 스캔 → 구조화 각 단계 결과, `safety_status`, `scan_status` |
| `app/document_mcp/processor.py` | 변환 subprocess | timeout / OSError 구분 |
| `app/services/reports.py` | `materialize_machine_report` | 생성된 revision·validation id, 검증 실패 항목 수 |

### 3-5. 4순위 — 요청 경계

`app/main.py`의 기존 `security_headers` 미들웨어 옆에 요청 로깅 미들웨어를 추가한다.

```python
@app.middleware("http")
async def request_log(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000)
    if response.status_code >= 400 or duration_ms > 1000:
        logger.warning("api request", extra={"bidops": {
            "event": "api.request", "http_status": response.status_code,
            "duration_ms": duration_ms}})
    return response
```

경로는 남기되 **쿼리 문자열은 남기지 않는다**(`serviceKey` 등이 들어올 수 있다).
`request.url.path`만 쓰고 `request.url.query`는 쓰지 않는다.

또한 라우터의 광범위한 `except Exception` → 500 변환 지점
(`routers/deep_reviews.py`, `document_bundles.py`, `reports.py`의 `_unexpected`)에
`logger.exception()`을 추가한다. 지금은 클라이언트에 안전한 코드만 나가고
서버에도 아무것도 남지 않는다.

---

## 4. 넣지 말아야 할 것

| 금지 | 이유 |
|---|---|
| 프롬프트 본문, 모델 응답 본문 | 회사 자료와 공고 원문이 들어 있다 |
| `company-profile.md` 절 내용 | 동일 |
| `BIDOPS_DATABASE_URL`, MinIO 자격 증명, `BIDOPS_G2B_API_KEY` | `docs/security.md` 보고 대상 |
| 쿼리 문자열 원문 | `serviceKey` 노출 경로 |
| 업로드 파일의 사용자 제공 경로 | 경로 이탈 시도 문자열이 그대로 남는다. `sha256`과 크기만 |
| 담당자 이름 | 감사 기록은 `audit_event`가 정본. 로그에 중복 저장하면 삭제 요구에 대응할 수 없다 |
| 예외 `str()`을 그대로 | 마스킹 필터를 반드시 거친다 |

---

## 5. 열려 있는 결정

`docs/tracking/findings.md`의 「관측 도구 도입 여부가 미정임」과 이어진다.
이 계획은 그 결정 **이전 단계**에서 개발·테스트 생산성을 회복하기 위한 것이고,
아래 두 가지는 별도 판단이 필요하다.

1. **파이프라인 로그의 영속화.** 현재 `PipelineService.lines`는 메모리에만 있어
   컨테이너 재시작 시 소실된다. `data/screening-executions/<id>/pipeline.log`로
   파일 저장할지, `ingest_warning`처럼 DB 테이블로 남길지 정해야 한다.
   T7 스택에서는 `/app/data`가 볼륨이 아니므로 파일 저장을 택하면
   compose 볼륨 추가가 선행되어야 한다.
2. **로그 수집처.** 사내 자료가 프롬프트에 들어가므로 외부 SaaS는 대상이 아니다.
   `docker compose logs` → 파일 → 자체 호스팅 도구 순으로 단계적으로 본다.

---

## 6. 요약 체크리스트

- [ ] `app/logging_setup.py` 신설 (마스킹 필터 + JSON 포매터 + 허용 키 목록)
- [ ] `main.py` lifespan, `workers/analysis.py`, `workers/document.py`에서 `configure()` 호출
- [ ] `BIDOPS_LOG_LEVEL`, `BIDOPS_LOG_TRACEBACK`을 `config.py`와 `.env.example`에 추가
- [ ] 1순위 5곳의 침묵 제거
- [ ] 판정 워커 7개 지점
- [ ] 심층 검토 8개 지점
- [ ] 요청 경계 미들웨어 + `_unexpected` 3곳
- [ ] 금지 항목이 로그에 나오지 않는지 검증하는 테스트 추가
      (`caplog`에 `sha256`은 있고 프롬프트 문자열은 없는지)
