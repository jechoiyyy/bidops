# 세션 인수인계

최종 갱신: 2026-08-31

각 절이 가리키는 문서가 정본이다. 이 파일은 **어디를 봐야 하는지**와
**지금 어디에 서 있는지**만 적는다.

---

## 1. 먼저 읽을 것

| 순서 | 문서 | 왜 |
|---|---|---|
| 1 | [`tracking/decisions-pending-20260831.md`](tracking/decisions-pending-20260831.md) | **사람이 정해야 진행되는 것 8건.** 지금 모든 남은 작업이 여기 걸려 있다 |
| 2 | [`tracking/lifecycle-workstream.md`](tracking/lifecycle-workstream.md) | 작업 목록 정본. 확정된 사실·결정·할 일·끝낸 일 |
| 3 | [`engineering-notes.md`](engineering-notes.md) 마지막 여섯 절 | host 테스트 실행법과 이번 세션에 새로 걸린 함정들 |
| 4 | [`tracking/findings.md`](tracking/findings.md) | 재현 가능한 미해결 문제 |

`CLAUDE.md`와 `AGENTS.md`는 내용이 같고 작업 진입점이다. 변경 전에 반드시 읽는다.

---

## 2. 지금 상태

### 테스트 기준선 (2026-08-31 실측)

```
백엔드      6 failed, 834 passed, 37 skipped   (4분 26초)
파이프라인  41 + 13 + 52 + 2 = 108 OK
프론트엔드  tsc -b 통과, vite build 통과
Alembic     head = 0008_prespec_attachment_fetch
```

**실패 6건은 환경 요구이며 이 작업과 무관하다.** 작업 후에도 정확히 같은 6개 이름이어야
하고 passed는 늘어야 한다.

- `test_integration_t14.py` 4건 — PostgreSQL과 컨테이너 env가 필요하다.
  **영구 제약이 아니다.** 아래 5절의 방법으로 주면 8건 전부 통과한다.
- `test_profile_snapshot*` 2건 — 승인된 git blob이 저장소 history에 없다
  ([findings.md](tracking/findings.md)).

`skipped` 37건 중 대부분은 `BIDOPS_TEST_POSTGRES_URL`이 없어서 건너뛴 PostgreSQL
테스트다. **skip을 통과로 읽지 마라.** 이번 세션의 결함 두 개가 이 skip 뒤에 숨어 있었다.

### 결정 없이 진행할 수 있는 작업은 모두 끝났다

완료: T-1a, T-1b, T-2, T-2b(3점), T-2c, T-3, T-4, T-5, T-7~T-18, T-20, T-21, T-24.
남은 T-19·T-22·T-23과 선별 제품 구현은 전부 결정 대기다.

---

## 3. 결정 대기 8건 (요약)

정본은 [`tracking/decisions-pending-20260831.md`](tracking/decisions-pending-20260831.md)다.
각 항목에 근거·선택지·권고가 있다.

| ID | 무엇 | 막고 있는 것 |
|---|---|---|
| **D-5** | 1차 분류 방식 실험 승인 | 선별 제품 구현 전체. 소비 계층은 다 있고 모델만 비어 있다 |
| **D-12** | 앞부분 잘라내기 규칙 (T-22) | T-22 → T-23. **측정이 끝나 결정만 남았다** |
| **D-7** | `www.g2b.go.kr` egress 방화벽 승인 | T-20 운영 활성화. 기능은 완성, 기본 비활성 |
| **D-6** | 판정의 모델 계보 정본 | T-19 |
| **D-8** | ADR-0027의 21일 재조회 범위 유지 여부 | 재조회 정책. **2026-09-08·09-14 관측이 결정적** |
| **D-9** | 첨부 URL 수명 측정 여부 | **2026-09-13이 지나면 이번 표본으로 못 잰다** |
| **D-10** | 다운로드 원문 보존 정책 (확인만) | 없음. 권고는 현행 유지 |
| **D-11** | PostgreSQL 테스트 필수화 | 없음. 같은 부류 결함 재발 방지 |

**시한이 있는 둘은 D-8과 D-9다.** 9월 중순이 지나면 두 측정 모두 기회를 놓친다.

---

## 4. 이번 세션에 찾은 결함 (전부 해결, 재발 방지 테스트 있음)

네 건 모두 **"테스트는 초록인데 운영에서 깨진다"** 는 같은 부류였다.

1. **Alembic revision 식별자가 version table 컬럼보다 길었다.**
   `0004`(33자)와 `0006`(39자)이 `VARCHAR(32)`를 넘겨 `alembic upgrade head`가
   PostgreSQL에서 통째로 롤백됐다. **`0004` 이후 어떤 배포도 불가능한 상태였고
   T-7·T-8·T-12·T-16a의 스키마가 정본 저장소에 한 번도 적용된 적이 없었다.**
   → `alembic/env.py`가 version table을 `VARCHAR(64)`로 먼저 만든다.
   폭은 `app.db.ALEMBIC_VERSION_NUM_WIDTH` 한 곳에 있고
   `test_every_revision_identifier_fits_the_version_column`이 강제한다.

2. **PostgreSQL 전용 테스트가 스키마 변경 뒤 갱신되지 않은 채 skip됐다.**
   `test_models_runtime.py`가 `0004`가 없앤 `notice.run_id`에 insert하고 있었다.

3. **legacy 첨부가 객체 식별자를 provenance 자리에 넣었다.**
   12필드 dataclass에 9개를 위치로 넘겨 `object_key`가 `source_system`에 들어갔다.
   MinIO에서 격리 원문을 읽지 못한다. → `kw_only=True`로 재발을 구조적으로 차단.

4. **host에 poppler가 없어 정상 PDF를 손상 판정한다.** (결함이 아니라 측정 함정)

---

## 5. 검증 실행법

### 백엔드

```bash
cd /home/jechoi/projects/bidops/web/backend
.venv/bin/python -m pytest tests -q
```

4분 넘게 걸리고 `TestClient` 구간에서 멈춘 것처럼 보인다. **기다려라.**
uvloop로 우회할 필요 없다 — 기본 asyncio에서 정상 종료하는 것을 세 번 확인했다.

### 파이프라인

```bash
./run-tests.sh
```

### 프론트엔드

```bash
cd /home/jechoi/projects/bidops/web/frontend
npx tsc -b        # 따로
npm run build     # 따로
```

`npm run build`가 rollup native 모듈 누락으로 깨지면
`npm install @rollup/rollup-linux-x64-gnu --no-save`로 복구한다.

### PostgreSQL (스키마를 바꿨으면 필수)

host에 Docker가 있으면 일회용 서버로 실제 검증할 수 있다.

```bash
docker run -d --rm --name bidops-pg \
  -e POSTGRES_DB=bidops -e POSTGRES_USER=owner -e POSTGRES_PASSWORD=local \
  -p 15499:5432 \
  postgres:17.11@sha256:051f7b7b3abdd564d5d1bd1e8c4b9c1b6e77087d1dd22020ede611c096a272e0 \
  postgres -c search_path=bidops,public

docker exec -e PGPASSWORD=local bidops-pg psql -U owner -d bidops \
  -c "CREATE SCHEMA IF NOT EXISTS bidops;" \
  -c "CREATE ROLE migrate LOGIN PASSWORD 'migratepw';" \
  -c "GRANT USAGE, CREATE ON SCHEMA bidops TO migrate;" \
  -c "GRANT CONNECT, CREATE ON DATABASE bidops TO migrate;" \
  -c "ALTER SCHEMA bidops OWNER TO migrate;"

cd web/backend
BIDOPS_DATABASE_URL="postgresql+psycopg://migrate:migratepw@127.0.0.1:15499/bidops" \
  .venv/bin/python -m alembic upgrade head

# 저장소에 있는 PostgreSQL 테스트 (평소에는 조용히 skip된다)
BIDOPS_TEST_POSTGRES_URL="postgresql+psycopg://owner:local@127.0.0.1:15499/postgres" \
  .venv/bin/python -m pytest tests/test_db_migrations.py tests/test_models_runtime.py -q

docker rm -f bidops-pg
```

`test_integration_t14.py` 8건을 통과시키려면 컨테이너 전용 env가 함께 필요하다.

```bash
BIDOPS_DATABASE_URL=<위 PostgreSQL URL> BIDOPS_ROOT=/home/jechoi/projects/bidops \
BIDOPS_DATA_DIR=<임시> BIDOPS_ATTACHMENTS_DIR=<임시> \
  .venv/bin/python -m pytest tests/test_integration_t14.py -q
```

### 문서 파이프라인 측정

**host가 아니라 런타임 이미지 안에서 한다.** host에는 poppler가 없어 정상 PDF가
`malformed_pdf`로 거부된다.

```bash
docker run --rm --network none -u "$(id -u):$(id -g)" \
  -e PYTHONPATH=/app/web/backend -v "<표본>:/data" -w /app/web/backend \
  bidops-mock-t7-web:latest python /data/<script>.py /data
```

HWP 변환기는 반대로 host에서도 동작한다(Node + 벤더링된 `app/document_mcp/vendor/rhwp`).

---

## 6. codex 위임

```bash
codex exec -m gpt-5.6-luna -c model_reasoning_effort="max" \
  -c approval_policy="never" -c sandbox_mode="workspace-write" \
  "$(cat <프롬프트파일>)" < /dev/null > <로그파일> 2>&1
```

### 이번 세션에 겪은 실패 세 가지

전부 **성공한 것처럼 보이는** 실패였다.

- **`&`로 배경 실행하면 셸만 즉시 반환한다.** 프로세스는 계속 돈다. 죽은 줄 알고
  다시 띄우면 **두 codex가 같은 파일을 동시에 고친다.** 실제로 겪었다.
  재실행 전에 `pgrep -af "codex exec"`로 확인한다.
- **작업 디렉터리가 sandbox 쓰기 범위를 정한다.** 하위 디렉터리에서 띄우면
  저장소 루트의 문서와 다른 모듈을 못 고치고 중단한다. 셸 작업 디렉터리는 호출 사이에
  유지되므로 **실행 직전에 `pwd`로 확인한다.**
- **전체 스위트를 "환경 문제"로 단정한다.** 세 번의 위임 모두 `TestClient` 정체를
  보고했지만 직접 돌리면 정상이었다.

### 검수 원칙

**완료 보고를 근거로 쓰지 않는다.** 전체 스위트를 직접 돌리고 바뀐 파일을 직접 읽는다.
이번 세션에서 codex가 T-24 범위 밖의 fail-closed 가드(worker의 object-store 검증)를
조용히 삭제한 것을 그렇게 잡았다.

---

## 7. 다음 작업 순서

결정이 나오는 대로 아래를 진행한다.

```
D-12 결정 → T-22 ADR 작성 → T-23 사전규격 개요 검토 구현
D-6  결정 → T-19 판정 모델 계보 노출
D-5  승인 → 선별 비교 실험 → 운영 방식·threshold 선택
D-7  승인 → T-20 운영 활성화 (overlay 적용)
```

관측은 결정과 무관하게 계속 쌓아야 한다.

- **T-2b**: 2026-08-24~26 구간 재조회. 2026-09-08(나이 15일)과 09-14(나이 21일) 무렵이
  ADR-0027 판단의 분기점이다. 명령은
  [validation-run](validation-runs/20260831-order-plan-longitudinal.md) 마지막 절에 있다.
- **D-9**: 2026-08-30 표본 30건의 URL 재호출. 2026-09-13 무렵.

---

## 8. 이번 범위가 아닌 것

- 입찰공고 전체 문서 분석과 delta 비교는 후속 고도화다
  ([ADR-0031](tracking/decisions/0031-prespec-overview-review-stage.md)).
- SSO·역할 권한·알림은 [`tracking/status.md`](tracking/status.md)의 14번 이후다.
- 현재 애플리케이션에는 로그인과 역할 기반 권한이 없다. 사내망 접근 제한이 경계이고
  담당자 이름은 감사 표식일 뿐 인증이 아니다.

---

## 9. 작업 트리 주의

`main`에 두 갈래가 진행 중이다.

- 이 세션의 작업은 커밋됐다(`80841ad`~`fcc0d65`).
- **`bid-delta` UI 작업이 커밋되지 않은 채 작업 트리에 있다.**
  `BidDeltaDecisionPage.tsx`, `components/bid-delta/`, `bid-delta-decision.css`,
  `deep-review-evidence.css`와 `OpportunitiesPage.tsx`·`DeepReviewPage.tsx`·
  `opportunities-relaxed.css`의 변경이 그것이다.
  `routes.tsx`와 `AppShell.tsx`에는 이 작업과 `/pre-specs`가 함께 들어 있다.

`data/experiments/`는 `.gitignore`가 제외하지 않아 원문 API 페이지가 커밋에 포함된다.
실험 원문은 `--from-raw`로 재생성할 수 있으므로 저장소 크기가 문제되면 제외를 검토한다.
