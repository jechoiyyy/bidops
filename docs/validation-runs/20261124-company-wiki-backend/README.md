# 백엔드 검증과 회사 근거 화면까지의 운영 배포

2026-11-24 11:00 KST 확인. 운영 DB를 `0043_company_wiki_ingest`로 올리고 web·analysis-worker·첨부 worker를 `bidops:main-20261124-ab08343`(`sha256:1064f93c7ea7ca6d11c2709458e741744ca4b209f17a6161f77d1f814851eb7e`, linux/amd64)로 교체했다. 회사 근거 화면(`/company`)이 회사 위키를 읽는다. **실적 넣기 스위치는 꺼 둔 그대로다.** 이 기록은 코드 배포 기록이며 넣기 기능의 활성화나 분류 품질의 근거가 아니다(넣기 결과는 `mock_reference`).

사용자 결정: 2026-11-24 "백엔드 검사 환경 만들어서 검증하고 회사 근거까지 배포", 계획 확인 뒤 "지금 진행".

## 1. 백엔드 검사 환경

이 checkout에는 `web/backend/.venv`가 없고, Mac 호스트에서 저장소 루트 환경으로 돌리면 Linux 전용 경로(`/proc`, `renameat2`, 네이티브 변환기)와 BSD 도구 때문에 수백 건이 실패한다. 그래서 운영 이미지의 런타임을 검사 환경으로 삼았다.

- 대상: main의 깨끗한 복제본(`git clone`, 커밋된 내용만)을 `/repo`로 마운트.
- 런타임: 배포할 이미지 자체(python 3.12, `requirements.lock`, OS 도구, linux/amd64).
- DB: 일회용 `postgres:17.11`, Docker 내부 네트워크(외부 통신 없음, 운영 DB·API에 닿지 않음).
- 실행: [`scripts/run-backend-tests.sh`](scripts/run-backend-tests.sh) `<이미지> <복제본> <로그> [pytest 인자]`. 전체 스위트는 약 31분.
- 호스트 스크립트 검사(`tests/app/test_daily_*`, 게이트 측정)는 `jq`가 필요해 검증 전용 층 [`scripts/Dockerfile.verify-tools`](scripts/Dockerfile.verify-tools)을 얹은 이미지에서 다시 돌렸다(이 이미지는 배포하지 않는다). docker CLI가 필요한 `test_compose_selection.py`는 호스트에서 돌렸다.

## 2. 검증 결과

| 확인 | 결과 |
|---|---|
| 전체 스위트, main `79cc306` | 4,258 통과 · 190 실패 · 336 건너뜀 ([실패 목록](failures-main-79cc306.txt)) |
| 같은 환경, 변경 전 `61420c9` | 4,209 통과 · 189 실패 · 336 건너뜀 ([실패 목록](failures-baseline-61420c9.txt)) |
| main에서만 실패 | 2건: `tests/deep_review/test_litellm_demo_profile.py`의 용량 검사. `c660e72`가 개요 호출부에서 `run.model_revision`을 읽게 했는데 검사의 가짜 run 객체에 그 필드가 없었다. `ab08343`에서 fixture에 `model_revision=None`을 넣었고 그 파일 18건이 통과한다 |
| 기준에서만 실패 | 1건(`test_runtime_contract.py::test_mock_reference_override_…`), main에서는 통과 |
| 호스트 스크립트 검사 6개 파일 | `jq` 층 이미지에서 206 통과 · 5 실패. 5건 중 4건(`test_compose_selection.py`)은 docker CLI가 필요해 호스트에서 통과를 확인했고, 1건(`test_daily_briefing_script.py::test_cron_example_reuses_the_track_lock_and_wraps_in_timeout`)은 두 환경 모두 실패한다 — cron 예시가 `cron-daily-track.sh`로 바뀐 뒤(2026-11-18) 검사가 옛 줄 모양을 찾는다 |

**변경 전부터 실패하던 35건**(스크립트 검사 제외)은 구현에 관여하지 않은 컨텍스트가 traceback·검사·코드를 읽어 분류했다. 런타임 결함은 없다.

| 분류 | 건수 | 내용 |
|---|---:|---|
| 낡은 검사 | 28 | `test_auto_preparation.py` 12건(자동 심층 시작 기본값이 꺼짐으로 바뀜, ADR-0069) · `test_order_plan_list_v2.py` 6건(검색을 전체 casefold에서 ASCII 대소문자·공백 무시로 바꿈, `docs/contracts.md`) · `test_api_opportunities.py` 2건(fixture의 `created_at=2026-09-30`이 과거가 되어 "오래된 행 유지" 규칙의 결과가 뒤집힘) · `test_mapper_isolation.py`·`test_models.py`(테이블 수·목록을 값으로 고정, 0042·0043 미반영) · `test_profile.py`와 그것을 다시 돌리는 `test_postgres_harness.py`(회사 프로필 문서에 8번째 절 추가) · `test_document_segments_postgres.py`(`ALEMBIC_HEAD`를 0037 자리로 씀, 중간 확신) |
| 환경 제약 | 6 | amd64 에뮬레이션에서 자식 프로세스의 `RLIMIT_DATA`가 네이티브 변환기를 죽이는 알려진 제약(`docs/engineering-notes.md`) — `test_prespec_attachment_fetch.py` 1, `test_document_mcp.py` 2, `test_prespec_e2e.py` 2(추정). `test_codex_runner.py` 1은 애플리케이션 이미지에 `codex` CLI가 없어서다 |
| 코드 규칙 위반 | 1 | `test_module_boundaries.py::test_routers_do_not_touch_the_orm_directly` — `app/lifecycle/routers/opportunities.py`의 `start_selected_pre_specs`가 라우터 안에서 `session.execute(select(...).with_for_update())`를 부른다(`294be33`, 2026-11-21). 동작에는 영향이 없고 허용 목록은 줄어드는 방향만 허용이라 서비스 함수로 옮겨야 한다. 이번에 고치지 않았다 |

낡은 검사와 규칙 위반은 이번 범위에서 고치지 않았다. 다음에 전체 스위트를 돌리는 사람은 위 목록을 기준선으로 쓸 수 있다.

### 실제 데이터로 한 리허설 (격리)

배포 전 아침 백업(`bidops-20261123T220952Z.dump`, revision 0042)을 일회용 PostgreSQL에 복원해 내부 네트워크에서 돌렸다. 운영 서비스에는 연결하지 않았다. 스크립트: [`scripts/rehearse-migration.sh`](scripts/rehearse-migration.sh), [`scripts/rehearse-web.sh`](scripts/rehearse-web.sh).

- 새 이미지의 `scripts/migrate.sh`(Alembic upgrade head + `runtime-privileges.sql`): `0042`→`0043` 성공. 기존 111개 테이블의 행 수는 `screening_audit_event` +1(migration 감사 행)만 달라졌고 새 테이블 `company_wiki_ingest_run`은 0행. 트리거 `wiki_ingest_guard` 생성, 새 테이블 권한 app `INSERT,SELECT`·worker `SELECT`·ro_backup `SELECT`.
- app 역할로 새 이미지의 `init_db()` 통과. 이전 이미지는 migration 뒤 DB를 "Database migration required … expected 0042_engine_run"으로 거부한다 — **그래서 worker도 같이 교체했다.**
- 롤백: `alembic downgrade 0042_engine_run`(넣기 행이 없을 때만 허용) 뒤 이전 이미지가 DB를 받아들인다.
- 새 이미지의 web을 그 사본에 띄워 운영 화면이 부르는 GET 84개를 재생했다: 회사 위키 5개가 404→200, 나머지 79개는 운영과 상태 코드가 같다(200 74 · 404 3 · 503 2). 본문까지 같은 것은 58개이고 나머지 21개는 리허설의 꺼 둔 스위치와 복원 시점 뒤의 운영 데이터 변화가 들어가는 응답이다(본문은 해시만 비교했다). 서버 오류·Traceback 0. 이 web의 객체 저장소 설정은 자리표시 값이었다 — 실제 MinIO에 붙은 기동은 아래 운영 교체가 처음이다.
- 새 이미지에서 실제 회사 묶음(`./wiki`, 읽기 전용, 네트워크 없음)을 읽어 요약·프로필·실적 58·업무 주제 38·페이지 99가 응답 모델을 통과했다.

### 운영 이미지와 새 이미지의 코드 비교

실행 중이던 세 이미지에서 `app`·`packages`·`scripts`·`alembic`을 꺼내 새 이미지와 비교했다. **운영에만 있고 새 이미지에 없는 파일은 없다.** web에 더해진 것은 회사 위키 변경분(수정 18·신규 12 파일)뿐이고, analysis-worker와 첨부 worker는 거기에 `c660e72`의 변경(입찰 delta·결정 대기열·사업기회·발주계획·개요 토큰 예산 등)이 더해졌다. Python 의존성은 web 이미지와 같고(58개 동일), 번들된 skills·entrypoint도 같다. 프런트엔드 번들은 아침 배포와 같은 `assets/index-B991YZw6.js`다.

## 3. 운영 적용

| 단계 | 시각(KST) | 결과 |
|---|---|---|
| 직전 확인 | 10:59 | cron 프로세스 0, 실행 중·대기 C-2 0, 진행 중 개요 0, worker 둘 다 10분간 로그 없음 |
| 전체 백업 | 10:59 | `backups/postgres/full/bidops-20261124T015946Z.dump`(126,217,680 bytes, SHA-256 `d248679c9d5fb4aa509175105d4eed3828215be9f7c0468d8258ace10e5d3815`, TABLE DATA 111). `run --rm --no-deps ro-backup`, postgres 컨테이너 ID·생성 시각 동일 |
| 보존 태그 | 11:00 | 이미지 `bidops:before-company-wiki-20261124-{web,analysis-worker,attachment-worker}`, git `before-company-wiki-20261124`(`79cc306`). `backups/company-wiki/` 생성(analysis-worker 사본 마운트 자리) |
| 이미지 지정 | 11:00 | `.env`의 `BIDOPS_IMAGE` 한 줄만 변경(나머지 줄 해시 동일) |
| DB 변경 | 11:00:19~22 | `BIDOPS_ENV=prod scripts/compose.sh run --rm --no-deps migrate` exit 0. revision `0043_company_wiki_ingest`, 테이블 112, 행 수 변화는 `screening_audit_event` 37→38뿐. postgres 컨테이너 동일 |
| 서비스 교체 | 11:00:31~39 | `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web analysis-worker prespec-attachment-worker` exit 0, 셋 다 healthy. postgres·minio·clamav·document-worker 컨테이너 ID 동일 |

교체 전후의 compose 렌더를 실행 중 컨테이너와 대조했다. web과 첨부 worker는 이미지 외에 달라진 것이 없다. analysis-worker에는 회사 묶음 설정(`BIDOPS_ENGINE_COMPANY_BUNDLE_DIR/SLUG`), 넣기 스위치 둘(`false`), 사본 경로(빈 값), 넣기용 객체 키, 그리고 마운트 둘(`./wiki` rw, `./backups/company-wiki` rw)이 새로 붙었다. 넣기가 꺼져 있어 worker는 claim하지 않는다(교체 뒤 `wiki/`에 바뀐 파일 0).

## 4. 적용 뒤 확인

- 헬스: `http://127.0.0.1:18788/api/health` 200, tailnet `http://42-ax.tail0ab8c5.ts.net:8188/api/health` 200. 세 컨테이너 재시작 0회, 로그에 `Exception in thread`·`Traceback`·`migration required` 0건.
- 스위치: 일일 자동 실행 `effective_enabled: true`·`c2-order-plan-screening-v6`(변경 없음). web·analysis-worker 모두 `BIDOPS_COMPANY_WIKI_INGEST_ENABLED=false`, `…_APPLY_REFERENCE_ENABLED=false`.
- 회사 근거: `GET /api/company-wiki` 200(㈜루트랩, 실적 58·근거 지도에 든 실적 23·업무 263·근거 연결 3,969). `GET /api/company-wiki/ingests`는 404 `company_wiki_ingest_disabled`이고 화면은 "실적 넣기는 아직 켜지지 않았어요"를 보이며 넣기 기록 탭을 숨긴다.
- 화면: Chromium으로 22개 주소를 1280×800·1440×900·1920×1080에서, 회사 근거의 다섯 보기를 1440·1280에서 열었다. 브라우저에서 GET 이외 요청을 차단했고 차단된 쓰기 0건, 화면 예외 0, 가로 넘침 0. 4xx/5xx는 넣기 404(위)와 이전부터 같던 `/api/company`·`/api/briefings/latest` 404, `/api/profile/*` 503뿐이다. 캡처는 [`shots/`](shots/).

**확인하지 않은 것**

- 운영에서의 쓰기 동작(추적 시작·보류·종료, 최종 결정 저장, 정책 스위치)은 눌러 보지 않았다.
- 새 worker 이미지로 실제 작업(첨부 취득, 개요 실행, 문서 준비)이 도는 것은 보지 못했다. 교체 시점에 대기 작업이 없었다.
- 다음 cron(2026-11-25 06:30·07:00)이 이 이미지로 적재 CLI와 C-2를 돌리는 것은 그날 아침 로그로 확인해야 한다.
- 넣기 기능(접수·분류·반영)은 켜지 않았고 운영에서 시험하지 않았다. 켜려면 [절차](../../operations/company-wiki-ingest.md)의 버킷·전용 키·스위치 단계가 남아 있고 각 단계 직전 확인 대상이다.

## 5. 롤백

넣기 행이 없는 동안(스위치 off)에는 아래 순서로 되돌린다. 리허설에서는 같은 `alembic downgrade`를 새 이미지에서 직접 실행해 확인했고, 아래 compose 형태의 명령 자체는 실행해 보지 않았다.

1. `BIDOPS_ENV=prod scripts/compose.sh run --rm --no-deps --entrypoint alembic migrate downgrade 0042_engine_run` (작업 디렉터리 `/app/web/backend`, 새 이미지로 실행).
2. `.env`의 `BIDOPS_IMAGE`를 서비스별 이전 이미지로 되돌려 교체한다: web `bidops:before-company-wiki-20261124-web`(= `bidops:table-workbench-fe-20261124`), analysis-worker `…-analysis-worker`(= `bidops:overview-qwen-budget-20261122-worker`), 첨부 worker `…-attachment-worker`(= `bidops:engine-sync-20261121-2d47d42`). 서비스마다 `BIDOPS_IMAGE`를 바꿔 `up -d --no-deps --no-build --force-recreate --wait <서비스>`를 따로 실행한다.

넣기 실행 기록이 생긴 뒤에는 0043 downgrade가 차단되므로 백업 복원이 필요하다.
