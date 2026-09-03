# PostgreSQL 17 마이그레이션 실행 검증 (2026-08-31, T-9)

`0004`~`0007`은 SQLite 테스트만 통과한 채 한 번도 PostgreSQL에서 실행된 적이 없었다.
`lifecycle-workstream.md`의 T-9이 이를 **배포 전 필수**로 표시하고
"disposable PG가 없어 미검증"으로 남겨 두었다.

Docker 29.7.2가 host에 있어 일회용 PostgreSQL 17을 띄우고 실제로 실행했다.

## 방법

```bash
docker run -d --rm --name bidops-t9-pg \
  -e POSTGRES_DB=bidops -e POSTGRES_USER=owner -e POSTGRES_PASSWORD=<local> \
  -p 15499:5432 \
  postgres:17.11@sha256:051f7b7b3abdd564d5d1bd1e8c4b9c1b6e77087d1dd22020ede611c096a272e0 \
  postgres -c search_path=bidops,public
```

`scripts/postgres-init.sh`의 최소 부분(`bidops` schema, `migrate` role, 소유권)을 적용한 뒤
`web/backend/.venv`의 Alembic CLI로 실행했다. 이미지 digest는 `docker-compose.t7.yml`과 같다.

## 찾아낸 결함 — `alembic upgrade head`가 PostgreSQL에서 전혀 동작하지 않았다

```
sqlalchemy.exc.DataError: (psycopg.errors.StringDataRightTruncation)
value too long for type character varying(32)
[SQL: UPDATE bidops.alembic_version SET version_num='0004_cumulative_external_identity'
      WHERE bidops.alembic_version.version_num = '0003_screening_runtime_pg']
```

Alembic 1.19.1은 version table을 만들 때
`Column("version_num", String(32))`를 **하드코딩한다**
(`alembic/ddl/impl.py:169`, `version_table_impl`). revision 식별자 두 개가 그보다 길다.

| revision | 길이 |
|---|---|
| `0004_cumulative_external_identity` | **33** |
| `0006_bid_first_opportunity_registration` | **39** |

PostgreSQL은 선언 길이를 강제하고 SQLite는 무시한다. 그래서 이 결함은 정본 저장소에서만
드러나고 테스트에서는 보이지 않았다. PostgreSQL의 DDL이 트랜잭션이라 실패한 실행은
통째로 롤백되어 `alembic_version` table조차 남지 않는다.
**즉 `0004` 이후 어떤 배포도 불가능한 상태였다.**

`context.configure(version_table_column_type=...)`는 Alembic 1.19에 존재하지 않는 옵션이라
조용히 무시된다. 실제로 이 경로를 먼저 시도했고 같은 오류가 재현됐다.

### 대응

`alembic/env.py`가 migration 실행 전에 version table을 **직접 만든다.** Alembic은
`Table.create(..., checkfirst=True)`로 생성하므로(`runtime/migration.py:542`)
이미 있는 table을 건드리지 않는다.

```sql
CREATE TABLE IF NOT EXISTS bidops.alembic_version (
  version_num VARCHAR(64) NOT NULL,
  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
ALTER TABLE IF EXISTS bidops.alembic_version
  ALTER COLUMN version_num TYPE VARCHAR(64);
```

두 문장 모두 멱등이다. `ALTER`는 기본 폭으로 이미 만들어진 table을 넓힌다.

대안은 revision 식별자를 32자 이하로 줄이는 것이었다. 그쪽은 `down_revision` 사슬,
파일명, `contracts.md`·`findings.md`·`lifecycle-workstream.md`의 문서화된 식별자를
모두 바꿔야 해서 선택하지 않았다.

## 검증 결과

| 항목 | 결과 |
|---|---|
| `alembic upgrade head` (`0001`→`0007`) | 통과 |
| 단계별 `downgrade` `0007`→`0003` | 통과 |
| `downgrade` `0003`→`0002` | **의도된 실패.** `0002`가 `RuntimeError`로 막는다 (긴 `screening_basis` 손실 방지) |
| head 재적용 | 통과 |
| head 상태 | table 56, CHECK 제약 165, trigger 37 |

### 제약조건이 실제로 거부하는가

| 시도 | 결과 |
|---|---|
| `tracking_status='아무거나'` | 거부 |
| `미선택`인데 `tracking_selected_by`가 있음 | `ck_opportunity_tracking_metadata` 거부 |
| `계속 추적`인데 선택자·시각 없음 | `ck_opportunity_tracking_metadata` 거부 |
| 기본 삽입 | `tracking_status='미선택'`로 생성 |
| `candidate` 링크가 `확정` | `ck_opportunity_link_candidate_not_confirmed` 거부 |
| `official` 링크에 근거번호 없음 | `ck_opportunity_link_official_evidence` 거부 |
| `검색 미확인`인데 `stage='order_plan'` | `ck_opportunity_link_search_unconfirmed_kind` 거부 |
| 대상 없는 `official` 링크 + 참조번호 | 허용 (ADR-0028대로) |

### plpgsql trigger가 실제로 발동하는가

| 시도 | 결과 |
|---|---|
| 확정된 policy body 수정 | `screening policy identity/body is immutable` |
| 품질 게이트 결과 없이 policy 활성화 | `active policy requires latest passing operational approval` |

## 저장소에 이미 있던 PostgreSQL 테스트를 처음 실행했다

`tests/postgres.py`가 `BIDOPS_TEST_POSTGRES_URL`로 disposable DB를 만드는 장치를 갖고
있었으나 변수가 없어 계속 skip됐다.

```bash
BIDOPS_TEST_POSTGRES_URL="postgresql+psycopg://owner:<local>@127.0.0.1:15499/postgres" \
  .venv/bin/python -m pytest tests/test_db_migrations.py -q
# 16 passed
```

| 파일 | 결과 |
|---|---|
| `test_db_migrations.py` | 16 passed |
| `test_deep_review_migrations.py`, `test_scheduler.py`, `test_screening_recovery.py` | passed |
| `test_models_runtime.py` | 처음엔 9 failed → 수정 후 13 passed |

### `test_models_runtime.py`가 `0004` 이후 갱신되지 않았다

`seed_base()`가 `insert into notice(run_id, notice_key)`를 실행한다. `run_id`는
`0004_cumulative_external_identity`가 ADR-0026에 따라 `notice`에서 없애고
`notice_observation`으로 옮긴 컬럼이다. T-7이 스키마를 바꿀 때 이 테스트가 함께 갱신되지
않았고, PostgreSQL이 없어 skip되느라 드러나지 않았다.

`notice`를 누적 행으로 넣고 `notice_observation(notice_id, run_id, ...)`을 따로 넣도록
고쳤다. 한 곳 수정으로 13건 전부 통과한다.

## 기준선 실패 6건의 성격이 바뀌었다

2026-08-30 인수인계 기록(현재는 통합 ADR·PRD·ARCHITECTURE와 tracking 문서가 대체)은 `6 failed`를 "이 작업과 무관한 환경 요구"로 기록했다.
그중 `test_integration_t14.py` 4건은 **영구적 제약이 아니었다.** PostgreSQL과
컨테이너 env를 주면 통과한다.

```bash
BIDOPS_DATABASE_URL="postgresql+psycopg://migrate:<local>@127.0.0.1:15499/bidops_t14" \
BIDOPS_ROOT=<repo> BIDOPS_DATA_DIR=<tmp> BIDOPS_ATTACHMENTS_DIR=<tmp> \
  .venv/bin/python -m pytest tests/test_integration_t14.py -q
# 8 passed
```

이 파일은 `BIDOPS_ROOT`·`BIDOPS_DATA_DIR`·`BIDOPS_ATTACHMENTS_DIR`·`BIDOPS_DATABASE_URL`을
모두 요구한다. 이 값들은 `.env`에서 host 테스트를 깨뜨린다는 이유로 제거된 컨테이너 전용
키다([findings.md](../tracking/findings.md)). 즉 이 테스트는 컨테이너 범위 통합 테스트이고
host 기본 실행에서 실패하는 것이 설계된 동작이다.

남은 `test_profile_snapshot*` 2건은 승인된 git blob이 저장소 history에 없어서 실패하며
이는 findings.md에 이미 기록된 미해결 항목이다.

## 측정하지 않은 것

- `0008` 이후 revision. T-20b가 추가하면 같은 절차로 다시 검증해야 한다.
- MinIO·ClamAV를 포함한 전체 스택 통합. 이번 검증은 PostgreSQL만 대상이다.
- 운영 데이터가 있는 DB에서의 downgrade. 빈 DB에서만 확인했다.
- `scripts/postgres-init.sh`의 전체 role 분리(`app`·`worker`·`ro_backup`)와
  `scripts/migrate.sh`의 GRANT 단계. 이번에는 `migrate` role만 만들어 검증했다.
