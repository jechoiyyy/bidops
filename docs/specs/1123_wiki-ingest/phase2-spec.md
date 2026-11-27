# 회사 근거 화면의 실적 넣기 — 2단계 명세 (참조 분류, 모델 호출 없음)

2026-11-23. 1단계([phase1-spec.md](phase1-spec.md))가 만든 위키 화면에 "실적 넣기"를 더한다. 수행한 사업의 제안요청서 파일을 올리면 백엔드가 요구사항을 뽑아 업무 단위로 분류하고, 사람이 확인한 뒤 위키의 업무별 근거 지도에 반영한다.

사용자 결정(2026-11-23):

- 이번 범위는 업로드부터 위키 반영까지 **전체 흐름을 모델 호출 없이** 연결한다. 분류 단계는 참조 응답(`mock_reference`)이다. 실제 모델 호출은 전송 승인 정책에 용도를 더한 뒤 다음 단계에서 켠다.
- 위키를 고치기 직전에 폴더 사본을 남기고 반영 전·후 digest를 기록한다.
- 분류 방식은 프롬프트 한 번 + 코드 검사 + 재질문 1회다(다음 단계에서 붙인다. 이번에는 그 자리의 계약만 맞춘다).

구현은 이 복제본에서 한다. 운영 작업 폴더는 읽기만 한다.

## 흐름과 상태

```
접수(queued) → 변환·추출(extracting) → 분류(classifying) → 검토 대기(awaiting_review)
   → 승인됨(approved) → 반영(applying) → 완료(applied)
실패(failed, error_code) · 반려(rejected) · 중단(aborted: 오래 멈춘 실행)
```

- 한 번의 업로드가 실행(run) 하나다. 실행은 불변 입력(파일, 대상 실적)과 append-only 상태 전이를 갖는다. 다시 넣으려면 새 실행을 만든다. 종결된 실행을 덮어쓰지 않는다.
- 변환·추출·분류·반영은 요청 안에서 기다리지 않는다. 업로드는 202와 실행을 돌려주고, 일은 분석 합성 worker(`app/workers/analysis.py`)가 한다. 기존 엔진 실행(`engine_run` + `WorkJob`, `app/deep_review/services/engine_runs.py`의 `run_once`)과 같은 방식으로 **기존 슬롯 하나**를 쓴다. 새 worker 진입점을 만들지 않는다.
- 승인은 사람이 한다. 승인 API는 상태만 `approved`로 바꾸고 반영 job을 넣는다. 반영도 worker가 한다(위키 폴더에 쓰는 주체는 worker 하나다).

## 백엔드

소유 모듈은 `deep_review`다.

### 설정 (`app/core/config.py`)

| 설정 | 환경 변수 | 기본값 | 뜻 |
|---|---|---|---|
| `company_wiki_ingest_enabled` | `BIDOPS_COMPANY_WIKI_INGEST_ENABLED` | `false` | 꺼져 있으면 넣기 API의 쓰기 요청은 404 `company_wiki_ingest_disabled`, worker는 claim하지 않는다 |
| `company_wiki_ingest_apply_reference_enabled` | `BIDOPS_COMPANY_WIKI_INGEST_APPLY_REFERENCE_ENABLED` | `false` | 참조 분류(`mock_reference`) 결과를 위키에 반영할 수 있는지. 꺼져 있으면 승인 요청이 409 `reference_apply_disabled` |
| `company_wiki_backup_dir` | `BIDOPS_COMPANY_WIKI_BACKUP_DIR` | `""` | 반영 직전 사본을 둘 폴더. 비어 있으면 반영은 `backup_dir_unset`으로 실패한다 |

위키 위치는 1단계와 같이 `engine_company_bundle_dir`·`engine_company_bundle_slug`다.

### DB (migration `0043_company_wiki_ingest`)

`bidops.company_wiki_ingest_run` 한 테이블. `0042_engine_run`을 본으로 삼는다(불변 실행 봉투 + `WorkJob` 재사용). 열:

- `id`(uuid, PK), `request_id`(uuid, 멱등 키, unique), `project_id`(text, `P\d{4}-\d{2}`), `project_title`(text)
- `status`(위 상태 집합 CHECK), `error_code`(text, null), `quality_status`(text: 이번 단계는 항상 `mock_reference`)
- 원본: `source_object_key`, `source_object_version`, `source_sha256`, `source_media_type`, `source_size_bytes`, `source_filename`(화면 표시용, 로그에 쓰지 않는다)
- 추출: `requirement_count`(int, null), `document_requirement_ids_unlisted`(int, null — 문서에 번호는 있는데 추출 목록에 없는 개수)
- 분류: `mapping`(JSONB, null — `bidops.wiki-ingest-mapping.v1`), `classification_attempts`(int, 기본 0)
- 반영: `wiki_sha256_before`, `wiki_sha256_after`, `backup_name`(text, null)
- 사람: `created_by_name`, `decided_by_name`(null), `decision_reason`(null)
- 시각: `created_at`, `updated_at`, `decided_at`, `applied_at`
- 실행 중 표식: `worker_id`, `heartbeat_at`(오래 멈춘 실행을 `aborted`로 닫는 데 쓴다)

`scripts/runtime-privileges.sql`에 `engine_run`과 같은 방식으로 app·worker 권한을 더한다(app: SELECT·INSERT·상태 전이에 필요한 UPDATE 열, worker: SELECT·UPDATE). migration은 빈 PostgreSQL 17에서 올라가고 내려가야 한다.

### 원본 저장

- 업로드는 형식(`.hwp`·`.hwpx`·`.pdf`)과 크기(기존 첨부 상한과 같은 값)를 요청에서 검사한다. 저장 키는 서버가 만든다(`<run id>/source`). 사용자 파일명으로 경로를 만들지 않는다.
- 객체 저장소(`app/core/object_store.py`)의 새 namespace `company-wiki-ingest`에 넣는다. namespace 등록 방식은 기존 namespace(엔진 실행 결과 저장)를 따른다.
- 악성코드 검사와 변환은 worker가 `ScratchDocumentProcessor.process()`(`app/deep_review/services/document_converter.py`)로 한다. 이 함수가 ClamAV 검사 뒤 문서 worker에 넘긴다. `malware_detected`면 실행을 그 코드로 실패시키고 원본 객체를 지운다.
- 요청이 실패하면 그 요청이 만든 객체와 DB 변경을 정리한다.

### 요구사항 추출과 분류 (엔진 패키지, subprocess)

웹·worker 프로세스는 엔진 패키지를 import하지 않고 subprocess로 부른다(`engine_runs.invoke_engine`과 같은 방식: `sys.executable -m …`, `PYTHONPATH`는 패키지 루트, 시간 제한, stdout JSON).

`packages/bid-deep-engine/src/bid_deep_engine/wiki_tools.py`에 명령을 더한다(테스트는 `engine_tests/test_wiki_tools.py`, 패키지 목록 `UPSTREAM.json`의 해당 파일 해시 갱신 필요 — `engine_tests/test_manifest.py`가 검사한다).

1. `source-from-blocks --project P2026-03 --title "…"` (stdin: `{"blocks": [...]}` — 문서 구조의 블록, `adapter.py`가 엔진 실행 입력에서 받는 것과 같은 모양) → stdout: `{"project", "title", "requirements": [{"id", "name", "definition", "details"}], "unlisted_ids": [...]}`.
   - 요구사항은 엔진이 분석 때 쓰는 것과 **같은 파서**로 뽑는다(runner가 블록에서 문서를 만드는 경로를 재사용한다. 파서를 다시 구현하지 않는다).
   - `unlisted_ids`: 문서 본문에 요구사항 번호 모양(`[A-Z]{2,4}-\d{2,3}`)으로 나오지만 추출 목록에 없는 것.
   - `details`는 700자에서 자르고 금액은 `(금액 생략)`으로 바꾼다(실적 페이지 금액 금지 규칙).
2. `reference-mapping --root <위키>` (stdin: 위 source JSON) → stdout: 형식이 맞는 분류 파일. 모델을 부르지 않는 **참조 분류기**다: 요구사항 명칭·내용에 업무 단위 제목의 낱말이 들어 있으면 그 단위를 붙이고, 없으면 빈 배열로 둔다. 결정적이어야 한다. 결과는 `validate_mapping`을 통과해야 한다. 품질을 주장하지 않는다(문서와 화면이 그렇게 말한다).
3. `expand-requirements --root <위키> --project P2026-03` (stdin: source JSON) → 그 실적 페이지의 `## 수행한 요구 범위` 아래에 `### 요구사항 전체 목록(원문)` 소절을 쓴다(한 줄에 번호·명칭·내용 앞 300자, 다시 실행하면 같은 결과). 원본 저장소의 `scripts/expand_portfolio_requirements.py`와 같은 규칙이다(그 파일은 `/Users/temp/orca/projects/bid-deep-agent/scripts/`에 있다. 읽어서 규칙을 옮긴다). 실적 페이지가 없으면 실패한다.
4. 기존 `ingest-apply`, `lint`, `check`를 그대로 쓴다.

다음 단계(실제 모델)에서는 2번 자리에 `ingest-prompt` → 모델 → `ingest-validate`(재질문 1회)가 들어간다. 이번 단계의 worker 코드는 "분류기"를 주입 가능한 함수 하나로 두어 그때 바꿔 끼울 수 있게 한다.

### worker 단계

1. **추출:** 원본 객체를 읽어 `ScratchDocumentProcessor.process()` → 블록 → `source-from-blocks`. 요구사항이 0건이면 `no_requirements`로 실패. 대상 실적이 실적 목록 YAML에 없으면 `project_not_registered`, 실적 페이지가 없으면 `portfolio_page_missing`으로 실패(이번 단계는 이미 등록된 실적만 넣는다).
2. **분류:** `reference-mapping` → `mapping` 저장, `quality_status = mock_reference`, 상태 `awaiting_review`.
3. **반영(승인 뒤):**
   - 위키 digest를 계산해 `wiki_sha256_before`에 적는다.
   - 위키 묶음 전체(`<slug>.yaml` 세 파일과 `<slug>/`)를 `company_wiki_backup_dir/<UTC 시각>-<run id 앞 8자>/`로 복사하고 `backup_name`에 폴더 이름을 적는다.
   - `expand-requirements` → `ingest-apply` → `lint`·`check`. 하나라도 실패하면 **사본에서 위키를 되돌리고** 실행을 `apply_failed`로 실패시킨다.
   - 성공하면 digest를 다시 계산해 `wiki_sha256_after`에 적고 `applied`.
   - 반영은 한 번에 하나만 돈다(기존 슬롯이 보장한다). 반영 시작 시 다른 실행이 `applying`이면 claim하지 않는다.
4. heartbeat가 설정 시간(기존 엔진 실행과 같은 값)보다 오래 멈춘 실행은 `aborted`로 닫는다. 자동 재개하지 않는다. `applying`에서 멈춘 실행을 닫을 때도 사본에서 되돌린다.

### API (`routers/company_wiki_ingests.py`, `services/company_wiki_ingests.py`, `schemas/…`)

- `POST /api/company-wiki/ingests` (multipart: `project_id`, `file`; 헤더 `X-BidOps-Actor-Name`(+`-Format`), `Idempotency-Key`(uuid)) → 202 실행. 같은 키로 다시 오면 같은 실행을 돌려준다. 대상 실적이 실적 목록에 없으면 422 `project_not_registered`. 같은 실적에 종결되지 않은 실행이 있으면 409 `ingest_in_progress`.
- `GET /api/company-wiki/ingests?limit&offset` → 최신순 목록.
- `GET /api/company-wiki/ingests/{id}` → 실행 상세: 상태, `error_code`, `quality_status`, 원본 메타(파일명·크기·형식), `requirement_count`, `unlisted_id_count`, 분류 요약(`units`: 단위 id·제목·건수, `unassigned_count`, `new_units`), 요구사항별 배정(`assignments`: 번호·명칭·단위 제목들), digest 전·후, 사람·시각.
- `POST /api/company-wiki/ingests/{id}/approve` (actor 헤더, body `{"expected_status": "awaiting_review"}`) → 상태가 다르면 409 `status_conflict`. 참조 분류인데 `apply_reference_enabled`가 꺼져 있으면 409 `reference_apply_disabled`.
- `POST /api/company-wiki/ingests/{id}/reject` (actor 헤더, body `{"expected_status": "awaiting_review", "reason": "…"}`).
- 쓰기 요청은 actor 이름을 요구하고(기존 `validate_actor`), 상태 전이와 감사 이벤트를 같은 transaction에 남긴다(감사 기록 방식은 `engine_runs.create`를 따른다). 감사 상세에 파일명·요구사항 본문을 넣지 않는다.
- 오류는 안전한 코드와 문장만. 내부 경로·subprocess stderr·예외 문자열을 싣지 않는다.

### 테스트

- `tests/deep_review/test_company_wiki_ingests.py`: 가짜 변환기(`ScratchDocumentProcessor` 자리에 주입, 기존 테스트의 가짜를 재사용)와 임시 위키·임시 객체 저장소로 전체 흐름: 업로드 202 → worker 한 바퀴 → `awaiting_review` → 승인 → worker 한 바퀴 → `applied`, 위키의 근거 지도·실적 페이지·`log.txt`가 바뀌고 digest 전·후가 다르고 사본 폴더가 있다.
- 실패 경로: 꺼진 기능 404, 허용 밖 형식·크기, 미등록 실적, 진행 중 중복 409, 멱등 키 재요청, 악성코드, 요구사항 0건, 실적 페이지 없음, 참조 반영 꺼짐 409, 상태 충돌 409, 반영 중 lint 실패 시 사본에서 복구되고 위키 digest가 원래 값, 사본 폴더 미설정, 오래 멈춘 실행 닫기.
- 불변성: 종결된 실행에 대한 승인·반려는 409.
- 응답과 로그에 경로·파일 본문·금액이 없다.
- PostgreSQL 변형: 이 파일은 `BIDOPS_TEST_POSTGRES_URL`이 있으면 PostgreSQL로도 돈다(기존 엔진 실행 테스트의 방식).
- migration 테스트(기존 `tests/app/`의 migration 검사)가 0043을 포함해 통과한다.
- `tests/app/test_module_boundaries.py`, `test_module_selection.py` 통과.
- 엔진 패키지: 세 새 명령의 테스트(파서 재사용, 참조 분류의 결정성·유효성, 요구사항 목록 소절의 멱등성·금액 가리기), `test_manifest.py` 통과.

## 프런트엔드

1단계 화면에 넣기를 더한다.

- "실적" 보기의 선택한 실적 영역에 **실적 넣기** 단추(이 화면의 주 단추 하나). 누르면 대화상자: 대상 실적(선택된 실적), 파일 선택(`.hwp`·`.hwpx`·`.pdf`), 담당자 이름은 사이드바의 값(`useRememberedActorName`, 비어 있으면 `requestActorInput()`). 제출하면 실행이 만들어지고 "넣기 기록" 보기로 간다.
- 새 보기 "넣기 기록"(`view=ingests`): 실행 목록(실적, 파일명, 상태, 요구사항 수, 시각)과 선택한 실행의 상세.
  - 상태 문구: 접수됨 / 요구사항 추출 중 / 분류 중 / 검토 대기 / 승인됨 / 반영 중 / 반영 완료 / 실패(사유 코드와 문장) / 반려 / 중단. 진행 중인 실행은 주기적으로 다시 조회한다(기존 실행 상태 컴포넌트의 폴링 관례).
  - 품질 표식: `mock_reference`는 "mock 참조"로 적고 성공·실패 색을 쓰지 않는다. 상세에 "이 분류는 모델이 아니라 참조 규칙이 만든 것이에요. 위키에 반영되지 않아요"(반영이 꺼진 환경) 또는 "…참조 분류예요. 반영하면 근거 지도에 그대로 들어가요"(켜진 환경)를 적는다. 어느 쪽인지는 승인 요청의 409 `reference_apply_disabled`로만 알 수 있으므로, 상세 응답에 `apply_allowed`(bool)를 더해 화면이 미리 알게 한다(백엔드 schema에 포함).
  - 검토 대기 상세: 분류 요약(단위별 건수, 미분류 건수, 문서에 있으나 목록에 없는 번호 수), 요구사항별 배정 표, **위키에 반영**·**반려** 단추. 반영은 확인 대화상자를 거친다("위키를 고치기 전에 사본을 남겨요").
  - 완료 상세: 반영 전·후 digest 앞 12자, 사본 이름, 근거 지도 보기로 가는 링크.
- 넣기 기능이 꺼져 있으면(목록 조회 404 `company_wiki_ingest_disabled`) 단추와 "넣기 기록" 보기를 그리지 않고, "실적" 보기에 한 줄로 "실적 넣기는 아직 켜지지 않았어요"를 적는다.
- 테스트: `tests/company-wiki-ingest.spec.ts`(가짜 API). 업로드 → 기록 보기 이동, 각 상태 문구, mock 참조 표식, 반영 확인 대화상자, 꺼진 기능, 오류 코드별 문장, 이름 없을 때 사이드바 칸으로 이동.

## Compose·운영 (문서와 설정 파일만, 배포는 하지 않는다)

- `docker/docker-compose.prod.yml`·`docker-compose.mock-reference.yml`: analysis-worker에 위키 폴더를 **읽기·쓰기**로, 사본 폴더를 쓰기로 붙이고 worker에 위 환경 변수를 준다. web은 읽기 전용 그대로다. 기본값은 모두 꺼짐이다.
- `docs/contracts/company-wiki.md`에 넣기 API와 상태·오류 코드를 더한다. `docs/operations/`에 켜는 절차 초안(순서: migration → 권한 SQL → 환경 변수 → worker 재기동, 각 단계 직전 사람 확인)을 쓴다.
- 이 단계의 결과는 `mock_reference`이며 운영 활성화·품질 근거가 아니라는 문장을 문서에 둔다.

## 하지 않는 것

- 실제 모델 호출, 전송 승인 정책 변경.
- 새 실적 항목 만들기(실적 목록 YAML에 없는 사업 넣기), 실적 삭제.
- 되돌려 쓰기(분석 피드백 반영) 화면, 분류 수정 편집기.
- 운영 배포, 운영 DB migration.

## 검증 명령

```bash
cd web/backend && /Users/temp/orca/bidops/.venv/bin/python -m pytest tests/deep_review/test_company_wiki.py tests/deep_review/test_company_wiki_ingests.py tests/app/test_module_boundaries.py tests/app/test_module_selection.py -q
cd /path/to/repo && PYTHONPATH=packages/bid-deep-engine/src:packages/bid-deep-engine /Users/temp/orca/bidops/.venv/bin/python -m pytest packages/bid-deep-engine/engine_tests/test_wiki_tools.py packages/bid-deep-engine/engine_tests/test_manifest.py -q
cd web/frontend && npm run build && npm run test:screens
```
