# 데이터베이스 구성

- 기준일: 2026-08-27
- 정본 엔진: **PostgreSQL 17** (`postgres:17.11`, digest 고정)
- 스키마: `bidops` 단일 스키마
- Alembic head: `0003_screening_runtime_pg`
- 테이블 수: **50개** (legacy 13 + Lean v1 신규 25 + screening runtime 12)

---

## 1. 엔진과 접속

### 1-1. SQLite는 정본이 아니다

`web/backend/app/db.py`는 세 지점에서 SQLite를 live 런타임에서 차단한다.

| 함수 | 동작 |
|---|---|
| `assert_postgresql_runtime()` | `BIDOPS_DATABASE_URL`이 `postgresql`/`postgres`로 시작하지 않으면 `RuntimeError` |
| `init_db()` | SQLite + 테스트 경계 아님 → `RuntimeError` |
| `ensure_database_current()` | `bidops.run` 테이블 존재 확인 + `alembic_version`이 head인지 확인 |

SQLite가 허용되는 경우는 두 가지뿐이다.

1. 격리 테스트 (`PYTEST_CURRENT_TEST` 또는 `BIDOPS_TEST_MODE=1`) — 명시적 `bind`로
   `Base.metadata.create_all()`을 호출한다
2. 일회성 마이그레이션 입력 (`app/migrations/import_sqlite.py`)

선언형 테이블은 스키마 없는 로컬 키로 정의하고, PostgreSQL 세션에서만
`schema_translate_map={None: "bidops"}`로 변환한다(`db.schema_bound()`). 덕분에
SQLite 테스트 바인드는 스키마 없이 그대로 동작한다.

### 1-2. JSON 직렬화 계약

모든 엔진이 같은 바이트를 만들어야 한다. `generation_config`의 SHA-256 digest가
이 바이트 위에서 계산되기 때문이다.

```python
json.dumps(value, ensure_ascii=False, sort_keys=True,
           separators=(",", ":"), allow_nan=False)
```

### 1-3. 애플리케이션은 관리자가 아니다

FastAPI lifespan은 Alembic을 실행하지 않고, `create_all`을 호출하지 않고,
포털·정책 행을 seed하지 않는다. 순서가 보장된 `postgres-init → migrate` 게이트가
이미 끝났는지만 **읽기 전용으로** 확인한다. 비어 있거나, 버전이 없거나, head가
아니면 애플리케이션이 기동하지 않는 것이 정상 안전 동작이다.

---

## 2. 역할과 권한

`scripts/postgres-init.sh`가 역할을 만들고 `scripts/migrate.sh`가 권한을 준다.

| 역할 | 용도 | 권한 |
|---|---|---|
| `owner` | 부트스트랩 전용 | 데이터베이스 소유자 |
| `migrate` | Alembic DDL | `bidops` 스키마 소유, `USAGE, CREATE` |
| `app` | FastAPI 프로세스 | 전 테이블 `SELECT/INSERT/UPDATE/DELETE`, 시퀀스 `USAGE, SELECT`. **CREATE 없음** |
| `worker` | analysis-worker | `app`과 동일한 DML 권한 |
| `ro_backup` | 백업 | 전 테이블 `SELECT`만 |

`ALTER DEFAULT PRIVILEGES`가 걸려 있어 이후 마이그레이션이 만든 테이블도 자동으로
같은 권한을 받는다. 런타임 역할이 DDL 권한을 갖지 않는 것이 "애플리케이션은
관리자가 아니다"를 DB 수준에서 강제하는 장치다.

---

## 3. 테이블 구성

세 tuple은 서로 겹치지 않으며(`models.py` 하단), 이 분리가 같은 테이블을 두 리비전이
중복 생성하는 것을 막는다.

### 3-1. `LEGACY_TABLES` (13) — 회차·판정·리뷰 투영

`0001_lean_v1_postgresql`이 생성.

```
run  notice  judgment  perspective  screening_evidence  counterargument
verification_item  matched_performance  attachment  agency_portal
review  verification_answer  ingest_warning
```

계층: `run` 1—N `notice` 1—1 `judgment` 1—N `perspective` 1—N `screening_evidence`.
`judgment`는 `counterargument`, `verification_item`, `matched_performance`도
`cascade="all, delete-orphan"`으로 소유한다.

`review`는 `notice` + `run`을 함께 참조한다. 회차마다 별도 리뷰를 남기고 이전 회차의
리뷰를 덮어쓰지 않기 위해서다.

### 3-2. `NEW_TABLES` (25) — Lean v1 문서·심층 검토

`0001_lean_v1_postgresql`이 생성.

| 묶음 | 테이블 |
|---|---|
| 콘텐츠 저장소 | `content_object`, `content_object_location`, `content_scan` |
| 문서 | `document_version`, `document_structure`, `document_block`, `document_bundle`, `document_bundle_item` |
| 고정 입력 | `profile_version`, `profile_evidence`, `analysis_policy_version` |
| 심층 검토 | `deep_review`, `deep_review_attempt`, `deep_review_stage` |
| 근거 | `claim`, `evidence_ref`, `claim_evidence` |
| 보고서 | `report_revision`, `report_revision_evidence`, `validation_run`, `validation_check`, `final_opinion` |
| 실행·감사 | `work_job`, `idempotency_record`, `audit_event` |

`content_object`는 바이트를 담지 않는다. `sha256`, `size_bytes`, `detected_mime`,
`retention_class`만 갖고, 실제 위치는 `content_object_location`(MinIO 네임스페이스별
object key + version id + etag)에 둔다. 하나의 콘텐츠가 `quarantine` → `source` →
`structure`로 옮겨 다녀도 DB 식별자는 하나다.

### 3-3. `SCREENING_RUNTIME_TABLES` (12) — 1차 판정 런타임

`0003_screening_runtime_pg`가 생성.

```
screening_execution  screening_attempt  company_profile_snapshot
quality_gate  quality_gate_evaluation  quality_gate_review
screening_policy  schedule_setting  schedule_reservation
schedule_execution  always_on_state  screening_audit_event
```

---

## 4. 불변성을 강제하는 장치

집계: `CheckConstraint` **148개**, `UniqueConstraint` **33개**, `Index` **8개**,
plpgsql 트리거 **21개**, IMMUTABLE 함수 **3개**.

### 4-1. 전역 동시성 1 (FIFO 슬롯)

```python
Index("uq_screening_execution_active_slot", "active_slot",
      unique=True, sqlite_where=text("active_slot IS NOT NULL"))
CheckConstraint(
  "((status IN ('실행 중','중지 요청') AND active_slot = 1) "
  " OR (status NOT IN ('실행 중','중지 요청') AND active_slot IS NULL))")
```

동시에 두 판정 실행이 `실행 중`이 될 수 없다. 애플리케이션 락이 아니라
DB partial unique index가 마지막 방어선이다.

### 4-2. 심층 검토 고정 입력의 유일성

`deep_review`는 `(notice_id, bundle_id, profile_version_id, policy_version_id)`
unique 제약을 갖는다. 같은 입력 조합으로 두 번째 review를 만들 수 없고,
`create_review`는 `IntegrityError`를 409 replay로 변환한다.

### 4-3. plpgsql 트리거 21개

`0003`은 T15 브랜치의 SQLite `BEFORE … RAISE(ABORT)` 트리거를 PostgreSQL
plpgsql로 재현한다. 모두 SQLSTATE `23514`(check_violation)을 던지므로
SQLAlchemy에서 `IntegrityError`로 잡힌다.

| 그룹 | 트리거 | 강제하는 규칙 |
|---|---|---|
| 프로필 짝 | `screening_execution_profile_pair_*`, `quality_gate_profile_pair_*` | 프로필 source/version/digest가 항상 함께 있어야 한다 |
| 공고 식별 | `screening_execution_notice_identity_*` | scope와 notice 식별자의 조합 강제 |
| 게이트 불변 | `quality_gate_input_immutable`, `quality_gate_evaluation_no_update` | 게이트 입력·평가는 append-only |
| 정책 불변 | `screening_policy_body_immutable`, `screening_policy_active_gate_*` | 정책 body 수정 금지, activation은 게이트 통과 필요 |
| 게이트 리뷰 | `quality_gate_review_pass_a_*` | 리뷰가 실제 pass A 판정 digest를 참조해야 한다 |
| 스케줄 | `schedule_execution_job_kind_*`, `schedule_execution_relation_*` | job kind와 예약의 관계 강제 |
| 상시 운전 | `always_on_enabled_*` | enable 전에 감사 행을 먼저 기록 |

### 4-4. IMMUTABLE 함수 3개

`generation_config` 동결값을 DB가 직접 검증한다.

| 함수 | 역할 |
|---|---|
| `bidops.generation_config_canonical_json(text)` | 저장소 canonical JSON 바이트 규칙 재현 |
| `bidops.generation_config_strict_int(jsonb, bigint, bigint)` | `num_ctx`/`num_predict` 범위 검증 |
| `bidops.generation_config_digest(text)` | SHA-256 계산 |

CHECK 제약이 이 함수들을 호출하므로, 애플리케이션을 우회해 직접 INSERT해도
digest가 맞지 않는 실행 행은 만들 수 없다. SQLite 테스트에서는
`register_sqlite_functions()`가 같은 이름의 Python UDF를 connect 이벤트에 등록한다.

### 4-5. 이중 방언 CHECK 제약

`app/sql_dialect.py`의 `dual()`이 CHECK 제약을 SQLite 문법 하나로 쓰고
PostgreSQL 문법을 파생시킨다.

| SQLite | PostgreSQL |
|---|---|
| `X NOT GLOB '*[^0-9a-f]*'` | POSIX `~` 정규식 |
| `json_valid(x) AND json_type(x)='object'` | `json_typeof(x)='object'` |
| `char(92)` | `chr(92)` |

번역할 수 없는 구문은 **import 시점에** `UntranslatableSQL`로 실패한다.
한쪽 방언에서만 제약이 조용히 사라지는 상황을 막는다.

---

## 5. 마이그레이션

```
0001_lean_v1_postgresql   (down_revision = None)   38 테이블
      ↓
0002_screening_basis_text                          run.screening_basis → TEXT
      ↓
0003_screening_runtime_pg                          12 테이블 + 함수 3 + 트리거 21
```

- `0001`은 `Base.metadata.create_all(tables=LEGACY_TABLES + NEW_TABLES, checkfirst=False)`.
  `checkfirst=False`이므로 부분 프로비저닝된 DB에 걸면 조용히 넘어가지 않고 실패한다.
- downgrade는 기본 차단. `BIDOPS_ALLOW_DISPOSABLE_ALEMBIC_DOWNGRADE=1`을 명시한
  일회용 검증 DB에서만 열린다.
- 실행 경로:
  ```bash
  COMPOSE_PROJECT_NAME=<isolated> docker compose -f docker-compose.t7.yml run --rm migrate
  ```

---

## 6. 백업과 복구

| 도구 | 대상 |
|---|---|
| `scripts/backup-postgres.sh` | PostgreSQL 정본 (`ro_backup` 역할, `backup` profile) |
| `scripts/backup-objects.sh` | MinIO object |
| `scripts/restore.sh` | object 우선 복구 |
| `scripts/verify-active-hashes.sh` | 복구 후 active hash 대조 |
| `docker compose --profile ops run --rm db-backup` / `db-verify` | **SQLite 마이그레이션 입력 스냅숏 전용** |

`docs/operations.md`의 경고대로 일상 운영에서 `docker compose down -v`를 쓰지 않는다.

---

## 7. 검증 결과 (2026-08-27)

격리 PostgreSQL 17 컨테이너 + 레포 마운트로 실행.

```
alembic upgrade head        → 0003_screening_runtime_pg 도달
pytest                      → 733 passed, 5 skipped, 2 failed
```

2건의 실패는 `test_profile_snapshot*`이며, 승인된 baseline blob
`ee621835…:bidops-agent/docs/reference/company-profile.md`가 이 저장소 히스토리에
없어서 발생하는 **환경 아티팩트**다(선행 저장소 `bidops-agent`의 커밋).
실제 컨테이너 경로(`BIDOPS_ROOT=/app`)에서는 `container-git-wrapper.sh`가
vendored baseline으로 응답하므로 통과한다. 코드 결함이 아니다.

5건의 skip은 격리 T7 MinIO 서비스가 필요한 live integration test다.

---

## 8. 알려진 위험

| 위험 | 상태 |
|---|---|
| SQLite → PostgreSQL 실제 백업본 이관 리허설 미수행 | `docs/tracking/findings.md`에 기록됨 |
| snapshot 복구 훈련 미수행 (RPO 4h / RTO 8h 미검증) | 동일 |
| MinIO 목적별 credential의 실제 allow/deny matrix 미실행 | 동일 |
| **`docker-compose.t7.yml`의 `web`이 `/app/data`, `/app/reports`를 볼륨에 남기지 않음** | 아래 참조 |

마지막 항목은 이번 리뷰에서 새로 확인했다. T7 스택의 `web` 서비스는
`document-scratch:/scratch`만 마운트하므로, 판정 산출물
(`data/screening-executions/`), 발행된 파생 회차(`data/runs/…--screen-…`),
렌더링된 보고서(`reports/`)가 컨테이너 재생성 시 사라진다. DB 행은 남고 파일은
없어져서 회차 화면의 산출물 검증이 `not_available`로 바뀐다. 자세한 내용은
[`2026-08-27-web-review.md`](./2026-08-27-web-review.md)를 참조한다.
