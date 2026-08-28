# `web/` 코드 리뷰

- 기준일: 2026-08-27
- 기준 HEAD: `d8d60ea` (`merge: integrate ui component refresh`)
- 범위: `web/backend`, `web/frontend`, 루트 compose 파일 5종
- 리뷰 관점: **기능 구현 1순위.** 오버엔지니어링과 세부 스타일은 결함으로 세지 않는다

관련 문서
- [워크플로우 입출력 지도](./workflow-io-map.md)
- [데이터베이스 구성](./database-setup.md)
- [로깅 도입 계획](./logging-plan.md)

---

## 0. 결론

코드 품질은 좋다. 계약이 문서대로 지켜지고, 회차 불변성·입력 동결·감사 기록이
DB 제약과 트리거로 강제되며, 테스트가 실제로 통과한다.

막고 있는 것은 코드가 아니라 **연결**이다. 우선순위 순으로 세 가지다.

| # | 문제 | 영향 |
|---:|---|---|
| 1 | 기본 `docker-compose.yml`로 `web`을 기동할 수 없다 | `docs/operations.md`의 기동 절차가 실패한다 |
| 2 | 문서 준비(단계 B) 화면이 없다 | 심층 검토를 UI에서 시작할 수 없다 |
| 3 | 백엔드 로거가 0건이다 | 워커가 조용히 죽으면 원인을 알 수 없다 |

---

## 1. 검증 실행 결과

| 명령 | 결과 |
|---|---|
| `docker build -f web/Dockerfile` | 성공 |
| `alembic upgrade head` (격리 PostgreSQL 17.11) | `0003_screening_runtime_pg` 도달 |
| `pytest` (레포 마운트 + PostgreSQL) | **733 passed, 5 skipped, 2 failed** |
| `npm ci && npm run build` | 성공. Vite 6.4.3, 266 modules, 5.80s |

2건의 실패는 `test_profile_snapshot.py::test_baseline_git_snapshot_and_source_validation`과
`test_profile_snapshot_container_fallback.py::test_vendored_baseline_equals_git_show_in_a_source_checkout`이다.
승인된 baseline blob `ee621835db934ddac944f7a07a986ed0b73ecc7a`가 이 저장소 히스토리에
존재하지 않아 발생한다(선행 저장소 `bidops-agent`의 커밋).

```bash
$ git cat-file -e ee621835db934ddac944f7a07a986ed0b73ecc7a
commit NOT in this repo history
```

`web/container-git-wrapper.sh`는 `-C /app`일 때만 vendored baseline으로 응답하는데,
검증 시 소스를 `/src`에 마운트해서 wrapper가 실제 git으로 위임했다.
**환경 아티팩트이며 코드 결함이 아니다.** 5건의 skip은 격리 T7 MinIO 서비스가 필요한
live integration test다.

프론트엔드 번들이 657KB(gzip 192KB)로 500KB 경고를 넘지만, 사내 관리 화면이므로
지금 단계에서 조치할 필요는 없다.

---

## 2. 심각 — 기본 compose로 애플리케이션이 기동하지 않는다

### 증상

`docker-compose.yml`은 SQLite를 지정한다.

```yaml
BIDOPS_DATABASE_URL: sqlite:////app/web/data/bidops.db
```

`app/main.py`의 lifespan은 PostgreSQL을 강제한다.

```python
if not using_test_db and not isolated_test_boundary_active():
    assert_postgresql_runtime()      # ← 여기서 실패
    assert_object_store_runtime()    # ← MinIO도 없다
```

실제 재현 결과:

```
STARTUP FAILED: RuntimeError
BIDOPS_DATABASE_URL must point to PostgreSQL 17; live SQLite is forbidden
```

### 왜 남아 있나

T15/deep-review 브랜치가 PostgreSQL로 전환되면서 `docker-compose.t7.yml`이
실질적 배포 템플릿이 됐는데, 루트 `docker-compose.yml`은 SQLite 시절 그대로다.
`ops` profile의 `db-backup`/`db-migrate`/`db-verify`/`policy-seed`는 SQLite
마이그레이션 입력 전용 도구로 여전히 유효하지만, **`web` 서비스 정의는 유효하지 않다.**

### 문서와의 충돌

`docs/operations.md` 6절이 그대로 이 파일을 쓴다.

```bash
docker compose up -d web            # ← 기동 실패
curl -fsS http://127.0.0.1:8787/api/health
```

### 권고

두 방향 중 하나를 택한다.

- **A안 (권장)** — 루트 `docker-compose.yml`에서 `web` 서비스를 제거하고
  `ops` profile만 남긴다. 파일 상단 주석에 "런타임 스택은 `docker-compose.t7.yml`"을
  명시하고 `docs/operations.md` 6절을 `-f docker-compose.t7.yml`로 고친다.
- **B안** — 루트 compose에 postgres/minio/migrate 서비스를 추가해 t7과 동등하게 만든다.
  두 파일이 갈라져 다시 어긋날 위험이 있다.

---

## 3. 높음 — 문서 준비 단계에 화면이 없다

백엔드 4개 엔드포인트가 완성되어 있고 테스트도 통과하는데, 프론트엔드에
대응 함수가 없다.

| 백엔드 | 프론트엔드 |
|---|---|
| `POST /api/notices/{id}/document-bundles` | 없음 |
| `POST /api/document-bundles/{id}/documents` | 없음 |
| `PATCH /api/document-versions/{id}` | 없음 |
| `POST /api/document-bundles/{id}/confirm` | 없음 |
| `GET /api/notices/{id}/document-bundles` | `getDocumentBundles` ✓ |

`NoticeDetailPage`는 `status === "ready"`인 bundle을 찾아 시작 버튼을 띄우고,
없으면 이렇게 표시한다.

> 문서 준비가 완료된 ready bundle이 있어야 심층 검토를 시작할 수 있습니다.

그 bundle을 만드는 경로가 화면에 없으므로, 심층 검토는 curl/CLI로만 시작할 수 있다.

`docs/tracking/findings.md`의 「단계 B 준비와 retry 제어 UI가 완결되지 않음」에
이미 기록되어 있고 "E2E API 인수에는 차단 요인이 아니"라고 판단했지만,
**기능 구현이 1순위인 현 단계 기준으로는 가장 큰 미완성 항목이다.**
`AttachmentsPage`가 이미 업로드 UI 패턴을 갖고 있으므로 재사용 여지가 크다.

추가로 실패한 attempt를 재시작하는 `POST /api/deep-reviews/{id}/attempts`도
UI에 노출되어 있지 않다.

---

## 4. 높음 — 로거가 0건이다

`web/backend/app/` 전체에 `import logging`이 **없다.** 동시에
`raise … from None`이 153건, `except Exception`이 92건이다. 원인 정보를
의도적으로 버리고 있는데 대체 기록처가 없다.

가장 위험한 지점 (`app/workers/analysis.py`):

```python
except Exception:
    # ... no exception contents are logged because they may contain DSN
    # material or provider details.
    pass
```

analysis-worker가 DB 접속 실패인지, 자격 증명 오류인지, provider 오류인지
바깥에서 알 방법이 없다. 컨테이너는 healthy로 보이면서 아무 일도 하지 않는다.

보안 요구(`docs/security.md`)를 "기록 금지"가 아니라 "마스킹된 구조화 기록"으로
구현하면 해결된다. 구체적 도입 순서와 금지 목록은
[로깅 도입 계획](./logging-plan.md)에 정리했다.

---

## 5. 중간 — T7 compose가 파이프라인 산출물을 볼륨에 남기지 않는다

`docker-compose.t7.yml`의 `web` 서비스 볼륨은 하나뿐이다.

```yaml
volumes:
  - document-scratch:/scratch
```

`/app/data`와 `/app/reports`는 이미지가 `install -d`로 만든 컨테이너 내부
디렉토리이고 볼륨이 아니다. 따라서 컨테이너 재생성 시 다음이 사라진다.

| 경로 | 내용 |
|---|---|
| `/app/data/runs/` | 수집 결과, 발행된 파생 회차 |
| `/app/data/screening-executions/` | 동결 입력, 판정 산출물, 실패 목록 |
| `/app/reports/` | 렌더링된 HTML 보고서, `review-feedback.yaml` |

DB의 `run`/`notice`/`judgment` 행은 남고 파일만 사라지므로,
`GET /api/runs/{id}`의 산출물 검증이 `not_available`이 되고 재보고서 생성과
재적재가 불가능해진다. 루트 `docker-compose.yml`은 `./data:/app/data`,
`./reports:/app/reports`를 마운트하고 있어 오히려 이 부분은 맞다.

`web/AGENTS.md`의 불변 조건과도 어긋난다.

> `data`와 `reports`는 파이프라인 산출물을 위해 읽기·쓰기로 (…) 마운트한다.

**권고**: t7 `web` 서비스에 `./data:/app/data`, `./reports:/app/reports`
(또는 명명 볼륨)를 추가한다.

---

## 6. 중간 — T7 스택의 `web`은 Ollama에 도달할 수 없다

1차 판정 워커(`ScreeningWorker`)는 `web` 컨테이너 안에서 돈다
(`ApplicationRuntime.start()`가 `bidops-screening-worker` 스레드를 띄운다).
이 워커는 Ollama HTTP 엔드포인트를 호출한다.

- `docker-compose.t7.yml`의 `web`은 `BIDOPS_OLLAMA_BASE_URL`을 설정하지 않는다
  → `config.py` 기본값 `http://192.168.0.139:11434`
- `web`의 네트워크는 `[database, storage, scanning]`
- 네 네트워크(`database`, `storage`, `scanning`, `analysis`)가 **모두 `internal: true`**

즉 `web` 컨테이너에는 외부 egress가 전혀 없다. 심층 검토용
`analysis-worker`에는 `docker-compose.t7.remote-vllm.yml`이 `model-egress`
네트워크를 붙여 주는 대응 장치가 있지만, **1차 판정에는 같은 장치가 없다.**

`docs/tracking/findings.md`의 「1차 판정 프롬프트 응답 시간이 실측되지 않음」에서
"판정 에이전트가 아직 애플리케이션에 연결되지 않아 실제 계측을 수행하지 못했다"고
기록한 것과 정합한다. T7에서 실제 판정을 돌리려면 `ollama-egress` 오버레이가
하나 더 필요하다.

수집(`collect_notices.py`)도 나라장터 OpenAPI를 호출하므로 같은 제약을 받는다.

---

## 7. 중간 — 회차 화면이 판정 단계를 두 번, 서로 다르게 말한다

`RunsPage` 한 화면에서 두 위젯이 충돌한다.

| 위젯 | 표시 |
|---|---|
| `PipelineStages` | 3단계 "에이전트 판정", `execution_allowed=false`, "판정은 에이전트가 screening-decisions.json을 직접 작성해야 하므로 여기서 실행하지 않습니다." |
| `ScreeningRunPanel` | "전량 판정 대기열에 넣기" → `POST /api/runs/{id}/pipeline/judgment` (202) |

원인은 `app/routers/runs.py`의 `_pipeline()`이다. judgment 항목의
`execution_allowed=False`와 message가 T15 이전 모델(에이전트가 파일을 직접 작성)에
맞춰져 있고, 그 뒤 애플리케이션이 판정을 실행하도록 바뀌었는데 문구가 남았다.

`PipelineService.start()`도 여전히 judgment를 거부한다.

```python
if stage == JUDGMENT_STAGE:
    raise PipelineInputError("판정 단계는 애플리케이션에서 실행하지 않습니다.")
```

이 방어 자체는 옳다(파일 계약 subprocess 경로로는 판정을 돌리지 않는다).
고쳐야 할 것은 `_pipeline()`의 표시 계약이다. judgment 행을 실제 실행 상태
(`screening_execution`)에 연결하거나, 최소한 message를 "아래 전량 판정 패널에서
실행합니다"로 바꾼다.

---

## 8. 낮음 — 연결되지 않은 대체 경로

`DocumentBundleService.ingest_legacy_attachment`(1166–1416)와
`ingest_provider_attachment`(1418–1661), 합쳐 약 500줄이 어떤 라우터·워커·
서비스에서도 호출되지 않는다. 별칭 `ingest_legacy_document` /
`ingest_provider_document`도 마찬가지다.

실제 문서 등록은 `upload_document`(847)가 담당하며,
`POST /api/document-bundles/{id}/documents` → `DocumentPreparationAgent.register_document`
→ `upload_document` 경로가 유일하게 살아 있다.

기능에는 영향이 없지만 정본이 무엇인지 코드만으로는 알 수 없다.
계획된 미래 경로라면 주석으로 명시하고, 아니면 삭제한다.

---

## 9. 낮음 — 문서 드리프트 2건

| 문서 | 내용 | 현재 코드 |
|---|---|---|
| `docs/agent-runtime.md` | "claim은 SQLite `BEGIN IMMEDIATE`로 수행하고 busy retry는 제한된다" | `queue.py:_begin_immediate()`는 `dialect.name == "sqlite"`일 때만 동작. PostgreSQL은 `active_slot=1` partial unique index로 보장 |
| `docs/operations.md` 6절 | `docker compose up -d web` | 2절 참조 |

---

## 10. 계약 준수 확인 (문제 없음)

기능 검토에서 확인한 것 중 **제대로 지켜지고 있는** 항목이다.

| 계약 | 근거 |
|---|---|
| skill 코드를 import하지 않고 subprocess + 파일 계약으로 연결 | `PipelineService._command`, `ScreeningWorker._merge`, `RuntimePipelineBridge._run` 모두 `python3 skills/…` 호출 |
| 등급과 준비 상태를 섞지 않는다 | `constants.py`가 유일 정본. `제외` 등급의 readiness 제약을 `validate_judgment`가 강제 |
| 기본 필터에서 `제외` 공고를 숨긴다 | `notices.py:93` |
| 회차 불변, 재실행은 새 행 | 파생 회차 `--screen-<stamp>-<hex8>` 발행, 이전 회차는 `superseded` 표시만 |
| 판정 없는 회차가 판정 있는 회차를 밀어내지 않는다 | `pipeline.py:_reload()`의 `result.judgments > 0` 조건 (주석에 이유 명시) |
| 입력 동결 digest 재검증 | orchestrator freeze → worker `_verify_binding` → DB CHECK + IMMUTABLE 함수 |
| 전역 동시성 1 | `uq_screening_execution_active_slot` partial unique index |
| 심층 검토 고정 입력 유일성 | `(notice_id, bundle_id, profile_version_id, policy_version_id)` unique |
| 심층 검토는 `우선 검토` 등급만 | `create_bundle` 403, `create_review` 403 (이중 검사) |
| 외부 provider 건별 승인 | `BIDOPS_CODEX_EXEC_APPROVED_NOTICE_IDS` allowlist + `require_notice_approval` |
| API 키 마스킹 | `mask_secrets()`가 값 치환 + 키 패턴 치환 |
| 첨부 경로 격리 | 서버 생성 경로, `origin=manual`만 삭제, 실패 시 파일 정리 |
| SPA fallback이 `/api`를 가로채지 않는다 | `SPAStaticFiles.get_response`가 `/api` 제외, mount는 라우터 등록 이후 |
| 프론트 빌드 없어도 API 기동, 화면은 503 | `install_frontend()`의 `missing_frontend` |
| 애플리케이션이 관리자가 아니다 | lifespan은 Alembic/create_all/seed를 실행하지 않고, `app` 역할에 CREATE 권한이 없다 |
| document-worker에 자격 증명·네트워크 없음 | `network_mode: none`, `environment: {}`, scratch 볼륨만 공유 |
| CSP·보안 헤더 | `security_headers` 미들웨어, `/api/*`는 `Cache-Control: no-store` |

---

## 11. Agent 분리 현황과 방향

### 11-1. 지금 무엇이 Agent인가

`AgentName` enum은 4개를 선언하지만 구현은 3개다.

```python
class AgentName(str, Enum):
    opportunity_discovery = "opportunity_discovery"   # ← 이름만 예약, 모듈 없음
    document_preparation  = "document_preparation"    # ✓
    deep_review           = "deep_review"             # ✓
    decision              = "decision"                # ✓
```

| 업무 | 구현 위치 | Agent인가 |
|---|---|---|
| 수집·정규화·표본 | `skills/bidops-collect/` (별도 프로세스) | ✗ |
| 1차 판정 | `app/screening/` (orchestrator + queue + worker + ollama, 약 8,000줄) | ✗ |
| 보고서 렌더링 | `skills/bidops-report/` | ✗ |
| 문서 준비 | `app/agents/document_preparation/` | ✓ |
| 심층 검토 | `app/agents/deep_review/` | ✓ |
| 사람 의사결정 | `app/agents/decision/` | ✓ |

### 11-2. 여기서 "Agent"의 정확한 의미

자율 판단 주체가 아니다. `docs/agent-workflow-design.md`가 명시한다.

> Agent는 자율적으로 업무 결정을 내리는 주체가 아니라 기존 도메인 서비스와
> 상태 기계를 감싸는 application-level facade다.

실제 구현도 그렇다. `DeepReviewAgent`는 41줄짜리 어댑터이고 docstring이
`"""Thin DeepReviewAgent adapter over DeepReviewService."""`다. 세 Agent가
공통으로 제공하는 것은 두 가지뿐이다.

1. **typed command 경계** — `AgentCommand[Payload]`가 actor, `request_id`,
   `aggregate`, `input_refs`, `expected_version`을 강제한다. 라우터가
   서비스를 직접 호출하지 않고 이 명령을 만들어 넘긴다.
2. **read-only projection** — `AgentRunView` / `AgentStepView`는 별도 테이블이
   아니라 기존 aggregate·attempt·stage·revision·validation 행에서 **계산**된다.
   Agent 전용 persistence는 없다.

`AgentSafeError` / `AgentWait`도 같은 목적이다. 도메인 오류를 폐쇄형 코드
집합으로 좁혀서, 내부 진단이 API 응답으로 새지 않게 한다.

### 11-3. 두 파이프라인이 비대칭인 이유

`app/screening/`은 Agent가 아니지만, Agent가 제공하는 보증을 **자기 방식으로**
이미 갖고 있다.

| 보증 | Agent 3종 | `app/screening/` |
|---|---|---|
| 입력 동결 | `DocumentBundleItem` 불변 snapshot | `screening-input.json` + SHA-256 + `generation_config` digest |
| 멱등성 | `IdempotencyRecord` + `request_id` | `execution_id` + FIFO + `active_slot` |
| 실행 소유권 | `WorkJob.lease_fence` + `SKIP LOCKED` | `active_slot=1` partial unique index + heartbeat |
| 감사 | `audit_event` | `screening_audit_event` |
| 재시도 | `DeepReviewAttempt` | `ScreeningAttempt` |
| 상태 조회 | `AgentRunView` projection | `GET /api/screening/executions/{id}` |

즉 **같은 문제를 두 번, 다른 어휘로 풀었다.** 이것이 비대칭의 실체이고,
기능 결함은 아니다.

### 11-4. 권고 방향

`docs/agent-workflow-design.md`가 이미 정한 목표를 유지한다.

```
OpportunityDiscoveryAgent   ← 지금의 app/screening/ + skills/bidops-collect
        ↓
DocumentPreparationAgent    ← 구현됨
        ↓
DeepReviewAgent             ← 구현됨
        ↓
DecisionAgent               ← 구현됨

BidOpsCoordinator           ← 미구현, 별도 승인 대상
```

다만 **지금 착수할 일은 아니다.** 근거:

- `app/screening/`을 Agent로 감싸는 작업은 순수 리팩터링이고, 사용자가 쓸 수
  있는 기능을 하나도 늘리지 않는다.
- 반면 3절(문서 준비 UI)은 심층 검토 전체를 UI에서 차단하고 있다.
- 6절(Ollama egress)이 해결되기 전에는 1차 판정 런타임을 T7에서 실행할 수
  없으므로, 그 계층을 지금 재구조화하면 검증 없이 바꾸는 셈이 된다.

**제안하는 순서**

1. **지금** — 2·3·4절 (compose 기동, 문서 준비 UI, 로깅). 기능과 진단이 회복된다.
2. **다음** — 5·6절 (T7 볼륨, Ollama egress). 1차 판정을 T7에서 실측할 수 있게 된다.
3. **그다음** — 1차 판정 실측(응답 시간, 등급 재현성)으로 품질 게이트를 채운다.
4. **마지막** — `OpportunityDiscoveryAgent`로 `app/screening/`을 감싼다.
   이때 새 저장소를 만들지 말고, 세 Agent와 똑같이 **어댑터 + projection만**
   추가한다. `screening_execution` → `AgentRunView`, `ScreeningAttempt` →
   `AgentStepView` 매핑이면 충분하다.
5. `BidOpsCoordinator`는 네 Agent가 모두 같은 projection 어휘를 갖게 된 뒤에
   판단한다. 지금 도입하면 감쌀 대상이 두 어휘로 갈라져 있다.

한 가지는 지금 바로 해도 좋다. **`AgentName.opportunity_discovery` enum 값 옆에
"모듈 없음, 4단계에서 구현" 주석을 남기는 것.** 지금은 enum만 보고
구현이 있다고 오해하기 쉽다.

---

## 12. 조치 목록

| 우선순위 | 항목 | 위치 |
|---|---|---|
| 1 | 루트 `docker-compose.yml`의 `web` 서비스 제거 또는 PostgreSQL화 | `docker-compose.yml`, `docs/operations.md` 6절 |
| 1 | 문서 준비 UI 4개 엔드포인트 연결 | `web/frontend/src/components/deep-review/api.ts` + 새 화면 |
| 1 | `app/logging_setup.py` 신설 후 1순위 5곳 침묵 제거 | [로깅 계획](./logging-plan.md) 3-1, 3-2 |
| 2 | t7 `web`에 `./data`, `./reports` 마운트 추가 | `docker-compose.t7.yml` |
| 2 | 1차 판정용 `ollama-egress` 오버레이 추가 | 새 `docker-compose.t7.ollama.yml` |
| 3 | `_pipeline()`의 judgment 표시를 실제 런타임에 맞춤 | `app/routers/runs.py:191` |
| 3 | `POST /deep-reviews/{id}/attempts` 재시도 UI 노출 | `DeepReviewPage` |
| 4 | `ingest_legacy_attachment` / `ingest_provider_attachment` 정리 또는 주석 | `app/services/document_bundles.py` |
| 4 | `agent-runtime.md`의 SQLite claim 문구 갱신 | `docs/agent-runtime.md` |
| 4 | `AgentName.opportunity_discovery`에 미구현 주석 | `app/agents/common/contracts.py` |
