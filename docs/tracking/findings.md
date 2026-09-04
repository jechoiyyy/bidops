# 미해결 문제

기준일: 2026-09-03

## 승인 사설 vLLM이 weight revision을 노출하지 않는다

- 확인: 2026-09-03
- 상태: **해결** (2026-09-03, [ADR-0042](decisions/0042-c2-model-revision-declared-at-deployment.md))
- 재현 조건: 승인 endpoint `http://192.168.0.139:58765/v1`의 chat completion 응답 최상위
  key는 `choices, created, id, kv_transfer_params, model, object, prompt_logprobs,
  prompt_text, prompt_token_ids, service_tier, system_fingerprint, usage`뿐이고
  `model_revision`도 `revision`도 없다. `/v1/models`도 `id`·`root`·`created`·
  `max_model_len`·`permission`만 준다. OpenAI 호환 vLLM에는 weight revision을
  노출하는 면이 없다.
- 당시 영향: 제품 adapter가 매 응답의 `model_revision`을 binding digest와 대조하고
  있어 모든 batch가 `model_mismatch / model_revision_invalid`로 거부됐다.
  발주계획 1,040건 회차에서 stage 1은 300 선정 / 740 탈락으로 정상 완주했고 stage 2는
  batch 1·2가 각각 약 224초 생성 뒤 거부됐다. 결과는 `selected/rejected` 50건으로
  보존됐고 자동 보정은 없었다.
- 해결: ADR-0042로 검증을 배포 시점 1회 선언 대조로 되돌렸다. 배포가
  `BIDOPS_VLLM_MODEL_REVISION`으로 운영자 확인 digest를 선언하고 adapter 생성 시
  binding과 대조한다. 응답의 `model_revision`은 **있으면 대조하고 없으면 통과**한다.
- 남은 공백 1: **digest 계산 방법이 이 저장소 어디에도 없다.** 런북은 "서버 운영자가
  제공한 64자 model artifact digest"라고만 하고, safetensors 파일들의 sha256인지
  manifest의 sha256인지, 어떤 순서로 묶는지가 없다. 따라서 "지금 서버의 digest가
  여전히 `6ae70ca3…`인가"를 이 저장소만으로 다시 확인할 수 없다. 운영자에게 계산
  방법을 받아 문서로 고정해야 한다. 그때까지 이 선언과 실제 적재된 weight의 일치는
  사람의 확인에 달려 있다.

## C-2 stage 2 구현이 측정된 방법과 어긋나 있었다

- 확인: 2026-09-03
- 상태: **해결** (2026-09-03, [ADR-0044](decisions/0044-c2-stage2-matches-the-measured-method.md))
- 재현 조건: 제품이 보내던 요청이 ADR-0037이 625건으로 측정한
  `experiments/order-plan-screening/scripts/methods.py::QwenAdapter._score_batch`와
  네 곳에서 달랐다. ① `plan_id`/`company` vs 승인 prompt가 계약한 `item_id`/
  `company_capabilities` ② `json_object` vs strict `json_schema`
  ③ `chat_template_kwargs`가 `extra_body`에 중첩돼 vLLM이 무시
  ④ generation config를 읽지 않고 하드코딩.
- 원인: stage 1 BM25와 병합은 `skills/` 스크립트를 subprocess로 부르지만 stage 2만
  백엔드가 재구현했고, 그 구현을 실제 서버로 검증한 적이 없었다. 기존 테스트는 오히려
  잘못된 모양(`extra_body` 중첩)을 단언해 네 건을 모두 통과시켰다.
- 해결: 요청 조립을 측정된 방법과 같게 맞추고, 승인 generation config를 아티팩트로
  복원해 실제로 읽게 했으며, 두 body가 같은지 단언하는 적합성 테스트를 넣었다.
  발주계획 1,040건 회차 재실행에서 300/300 완료·실패 0건.
- 남은 공백: BM25와 Qwen 요청 조립이 `experiments/`와 `web/backend/`에 각각 존재한다.
  적합성 테스트가 드리프트를 잡지만 구현이 하나가 된 것은 아니다. stage 2를 stage 1처럼
  subprocess 계약으로 내리는 것은 raw 응답 전달과 실패 코드 계약을 새로 설계해야 해서
  이번 범위에서 하지 않았다.

## legacy v3 screening orchestrator가 부분 성공 대신 실패를 게시한다

- 확인: 2026-09-03
- 상태: **미해결 · 기존 결함**
- 재현 조건: clean `main`(`6788c4f`)에서 `pytest tests/test_screening_orchestrator.py`를
  (모듈 이주 뒤 `pytest tests/screening/test_screening_orchestrator.py`) 돌리면
  `test_full_run_continues_after_one_notice_failure_and_publishes_partial` 과
  `test_partial_rejudgment_retains_prior_projection_and_revision` 이
  `'실패' == '부분 성공'` 으로 실패한다(34 passed, 2 failed, 약 53초).
- 부하 의존 flake가 아니다. 단독 실행과 전체 실행에서 같은 두 건이 재현되고,
  변경을 stash한 clean tree에서도 같다.
- 영향: 한 건이 실패한 회차의 부분 게시 경로가 성공으로 마감되지 않는다.
  C-2와 무관한 legacy 판정 경로다.

## 감독 작업 transcript에 G2B API key가 노출됐다

- 확인: 2026-08-31
- 상태: **키 회전 필요**
- 재현 조건: T14 하네스 진단을 위임받은 첫 감독 작업자가 환경을 점검하며
  `BIDOPS_G2B_API_KEY`의 실제 값을 Orca 작업 transcript에 출력했다.
- 영향: 해당 transcript에 접근할 수 있는 주체가 기존 key를 알 수 있으므로 기존 key를
  더 이상 안전하다고 간주할 수 없다. key 값은 저장소 파일·테스트 출력에 다시 기록하지
  않았고, 후속 작업은 외부 호출을 비활성화한 허용 목록 환경에서만 실행했다.
- 즉시 대응: 영향받은 dispatch를 실패·봉인하고 새 안전 작업으로 교체했다.
- 남은 조치: 승인된 외부 secret manager에서 해당 key를 폐기·재발급하고, 영향받은
  transcript·접근 log의 조회 범위를 감사한다. 현재 작업에는 secret manager 권한이 없어 회전을
  수행하지 못했다.

## 저장소 `.env`가 host 백엔드 테스트를 깨뜨리고 90배 느리게 만든다

- 확인: 2026-08-29
- 상태: **해결** (2026-08-29)

`web/backend/app/core/config.py:71`(당시 `app/config.py:33`)이 `env_file=DEFAULT_BIDOPS_ROOT / ".env"`로 저장소 루트의
`.env`를 읽는다. 그 파일에는 컨테이너 안에서만 유효한 값이 들어 있어서 host에서 pytest를
돌리면 실패와 지연을 만든다.

**재현**: HEAD를 별도 worktree(`git worktree add`)로 떼면 `.env`가 gitignore 대상이라 딸려오지
않는다. 같은 코드에 `.env`만 넣고 빼서 비교했다.

| 조건 | 결과 |
|---|---|
| `.env` 없음 | `tests/agents/test_document_preparation.py` 9 passed in **4.5초** |
| `.env` 있음 | 같은 파일 6 failed, 3 passed in **404초** |

원인을 키 단위로 좁혔다.

- **실패 6건**: `BIDOPS_OBJECT_STORE_BACKEND=minio`. 이 세 줄만 넣어도 재현된다(5.2초, 6 failed).
  host에는 MinIO가 없다.
- **404초 지연**: object-store와 ClamAV 키만으로는 재현되지 않는다(5.4초). 전체 `.env`가 있어야
  나오므로 MinIO 자격증명까지 있어야 실제 접속을 시도하며 재시도하는 것으로 보인다. 미확정.

`.env`가 있는 원래 트리에서는 `test_quality_gate.py`·`test_deep_reviews.py`·
`test_document_bundles.py`가 90초 안에 끝나지 않아 행으로 오인했다. 깨끗한 worktree에서는
각각 108초·10.8초·12.6초에 **전부 통과한다.**

**영향**: `.env`가 있는 상태의 host 테스트 결과는 baseline으로 쓸 수 없다. 실패 12건 중 6건이
`.env` 때문이고, 실행 시간도 신뢰할 수 없다.

**해결 방향**: `docker-compose.yml`이 `BIDOPS_CLAMAV_HOST`·`BIDOPS_OBJECT_STORE_*`를
이미 106~110행과 163~165행에서 선언한다. 공통 `.env`에 중복으로 둘 이유가 없으므로 제거한다.
같은 이유로 `BIDOPS_ROOT`·`BIDOPS_DATA_DIR`·`BIDOPS_ATTACHMENTS_DIR`은 2026-08-29에 이미
제거했다(그 셋은 `PermissionError: /app`으로 수집 단계에서 48개 파일을 전멸시켰다).

**적용 결과 (2026-08-29)**: `.env`와 `.env.example`에서 `BIDOPS_OBJECT_STORE_*`와
`BIDOPS_CLAMAV_*`를 제거했다. `BIDOPS_ROOT`·`BIDOPS_DATA_DIR`·`BIDOPS_ATTACHMENTS_DIR`은
같은 날 먼저 제거했다.

| | 제거 전 | 제거 후 |
|---|---|---|
| 전체 스위트 | 25분 초과로 완주 실패 | **3분 36초** |
| 통과 | 484 (느린 3개 제외 측정) | **711** |
| 실패 | 12 | **6** |

이 시점에 남았던 실패 6건은 `.env`와 무관했다. 2026-08-31에
`tests/test_integration_t14.py` 환경 실패는 pytest 수집 전 일회용 PostgreSQL 17·fresh DB·
필수 환경변수를 구성하는 하네스로 해결했다. profile 2건은 승인 Git blob 부재 시
snapshot을 만들지 않는 fail-closed 계약을 검증하도록 분리했으며, 승인 객체 부재 자체는
아래 미해결 항목으로 남아 있다.

**남은 미확인**: 404초 지연의 정확한 원인 키는 특정하지 못했다. object-store와 ClamAV 키만
넣었을 때는 5.4초에 끝났고 전체 `.env`가 있어야 재현됐으므로, MinIO 자격증명이 관여하는 것으로
보이나 확인하지 않았다. 지연 자체는 사라졌으므로 추적을 중단한다.

## 사전규격 정규화가 원문의 첨부·SW대상·업무구분을 버린다

- 재현 조건: `skills/bidops-collect/scripts/collect_notices.py`의 `normalize_prespec`을 `HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc` 응답에 적용하고 결과의 `url`과 `attachments`를 확인한다. 실측은 [`20260828-lifecycle-linkage-survey.md`](../validation-runs/20260828-lifecycle-linkage-survey.md)에 있다.
- 증상: `url`이 읽는 `specDocFileUrl`과 `bfSpecDtlUrl`이 응답에 존재하지 않아 항상 `None`이 된다. 실제 규격서 URL은 `specDocFileUrl1`~`specDocFileUrl5`이며 650건 중 586건이 최소 하나를 갖는다. `attachments`는 빈 배열로 고정돼 있어 과업지시서·제안요청서를 한 건도 확보하지 못한다. `swBizObjYn`(650/650), `bsnsDivNm`(650/650), `bidNtceNoList`(29/650)도 정규화에 담기지 않는다.
- 영향: 사전규격 심층 검토의 입력원이 성립하지 않는다. 문서 묶음을 만들 원문이 없으므로 [ARCHITECTURE.md의 사전규격·문서 준비 흐름](../ARCHITECTURE.md#53-첨부와-문서-준비)이 현재 수집 결과만으로는 시작될 수 없다. SW사업대상과 업무구분이 저장되지 않아 수집 대상 선별의 근거도 남지 않고, 공고 전환 감지에 쓸 `bidNtceNoList`도 유실된다.
- 상태: **해결** (2026-08-30, T-4). `PPSSrch`로 전환하고 `specDocFileUrl1~5`를 `attachments`로, `swBizObjYn`·`bsnsDivNm`을 `qualification_flags`로, `bidNtceNoList`를 `lifecycle`로 옮겼다. 응답에 없는 필드를 읽던 `url` 경로는 제거했다. 원문에 URL이 없는 건은 `unknown_fields`에 `attachments`로 남는다. **첨부를 실제로 내려받는 경로는 여전히 미구현이며 별도 작업이다.** `bidops.collected.v2`는 유지했다 — 기존 필드의 값이 채워지는 변화이고 병합기에 optional로 등록했다.
- (해결 전 기록) 지금 해결할 수 없는 이유: 정규화 계약을 바꾸면 `collected-notices.json` 소비자와 적재 경로의 계약이 함께 바뀐다. 첨부 URL을 실제로 내려받는 경로는 허용 형식·크기, 서버 생성 key, 악성코드 검사, quarantine, 객체 version 검증을 함께 갖춰야 하므로 정규화 필드 추가만으로 끝나지 않는다.
- 접근 방법: 수집 endpoint를 `getPublicPrcureThngInfoServcPPSSrch`로 바꾸고 `inqryDiv=1`(접수일시)로 구간 조회한다. **`swBizObjYn`을 서버 조건으로 얹지 않는다.** 이 문단의 이전 판은 `swBizObjYn=Y` 필터를 지시했으나 [ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md)가 그 반대를 결정했다. 650건 중 `Y`는 55건(8.5%)뿐이고 필터를 켜면 91.5%가 사라진다. 업무구분(일반용역·기술용역)으로만 좁히고 `swBizObjYn`은 저장 후 표시·필터 값으로만 쓴다. 이미 아는 등록번호를 다시 읽을 때는 `inqryDiv=2`가 날짜 구간 없이 단건을 반환한다. 두 endpoint의 응답은 650건에서 필드·값이 완전히 동일하므로 정규화 계약은 그대로 쓸 수 있다. 그 위에서 `specDocFileUrl1`~`5`를 `attachments`로, `swBizObjYn`·`bsnsDivNm`·`bidNtceNoList`를 구조화 필드로 옮긴다. 응답에 없는 필드를 읽는 현재 `url` 경로는 제거한다. 다운로드는 기존 첨부 파이프라인의 검사·격리 경계를 그대로 통과시키고, 원문에 URL이 없는 건은 추정 없이 `unknown`으로 남긴다. 회귀 테스트는 실제 응답 형태의 fixture로 첨부 개수와 SW대상 값이 보존되는지 고정한다.

## host 측정이 정상 PDF를 손상 문서로 판정한다

- 재현 조건: poppler가 없는 host에서 `app.document_mcp.processor.DocumentProcessor.process()`에 정상 PDF를 넣는다. 실측은 [`20260831-prespec-rfp-structure.md`](../validation-runs/20260831-prespec-rfp-structure.md)에 있다.
- 증상: 실제 조달 PDF 16건 중 15건이 `malformed_pdf`가 된다. 같은 파일을 `bidops-mock-t7-web` 이미지 안에서 처리하면 16건 전부 통과한다.
- 영향: 결함이 아니라 측정 함정이다. host에서 문서 파이프라인을 재면 처리 실패율이 크게 부풀려지고, 그 수치로 "PDF는 못 쓴다" 같은 잘못된 결론을 내리게 된다. T-21 초기 측정이 실제로 이 오류를 냈다.
- 상태: **원인 확인.** 표준 PDF 파서가 실패하면 poppler fallback으로 넘어가는데(`processor.py:315`) `pdftotext`·`pdfinfo`가 없으면 fallback이 `malformed_pdf`를 던진다(`processor.py:447-449`). `poppler-utils`는 런타임 이미지에만 있다(`web/Dockerfile:48`).
- 접근 방법: 문서 파이프라인 측정은 런타임 이미지 안에서 한다. 코드 수정은 필요 없다 — 운영 환경에는 poppler가 있다. 다만 fallback이 없을 때의 오류 코드가 `malformed_pdf`(문서 탓)인 것은 오해를 부른다. `converter_unavailable`처럼 환경 탓임이 드러나는 코드로 바꾸면 같은 혼동을 막을 수 있다. 이는 안전 판정을 완화하지 않는 변경이지만 오류 코드 계약을 건드리므로 별도로 다룬다.

## legacy 첨부 취득이 객체 식별자를 provenance 자리에 넣어 운영 백엔드에서 원문을 잃는다

- 재현 조건: `MinioObjectStore`처럼 `FilesystemObjectStore`가 아닌 object store에서 `assets.acquire_legacy_attachment()`를 호출하고 반환된 asset으로 `read_quarantine()`을 호출한다. `web/backend/tests/deep_review/test_legacy_attachment_provenance.py`가 가짜 store로 이 조건을 재현한다.
- 증상: `acquire_legacy_attachment()`가 12필드 `QuarantinedAsset`에 인자를 **9개만 위치로** 넘겼다. `object_key`가 `source_system` 자리에, object version id가 `source_attachment_key` 자리에, etag가 `source_url` 자리에 들어가고 `object_key`·`object_version_id`·`object_etag`는 `None`으로 남았다. `acquire_legacy_attachment()`는 store가 filesystem이 아니면 put 직후 로컬 quarantine 파일을 지우는데, `read_quarantine()`은 `object_key`가 없으면 그 지워진 로컬 경로를 읽으려 한다.
- 영향: 운영 기본 백엔드가 MinIO이므로(`docker-compose.yml`) legacy 첨부 ingest가 운영에서 항상 실패한다. 테스트는 filesystem store를 쓰기 때문에 로컬 파일이 남아 전부 통과했다. `test_minio_e2e`는 upload와 provider 경로만 덮고 legacy 경로를 덮지 않아 이 결함이 드러나지 않았다. 감사·응답으로 object key가 새지는 않는다 — 호출부가 `asset.source_*`를 쓰지 않고 자신의 snapshot 값을 쓴다.
- 상태: **해결** (2026-08-31). 세 생성 지점을 모두 키워드 인자로 바꾸고 `QuarantinedAsset`을 `@dataclass(frozen=True, kw_only=True)`로 만들어 위치 인자 구성을 아예 막았다. 생성 지점이 `assets.py` 안 세 곳뿐이라 외부 호출부에 영향이 없다. 회귀 테스트 4건을 추가했고 결함을 일부러 되살려 두 건이 실패하는 것을 확인했다.
- 남은 위험: 이 결함은 "운영 백엔드에서만 실패하고 테스트 백엔드에서는 통과한다"는 부류다. `test_minio_e2e`는 `BIDOPS_MINIO_E2E=1`이 없으면 skip되므로 같은 부류가 또 잠복할 수 있다. 새 테스트는 MinIO 없이도 도는 가짜 store로 이 부류를 잡는다.

## ADR-0027의 21일 재조회 근거가 종단 관측에서 재현되지 않는다

- 재현 조건: `experiments/lifecycle-linkage-survey/scripts/survey.py`로 게시일 2026-08-24~2026-08-26 구간을 재조회하고 `--baseline-raw`로 이전 관측과 대조한다. 실행 기록은 [`20260831-order-plan-longitudinal.md`](../validation-runs/20260831-order-plan-longitudinal.md)에 있다.
- 증상: 같은 997건이 5일 동안 `bidNtceNoList` 채움률 45.6% → 46.6%로 **1 포인트**만 올랐다. 같은 나이(6일)의 횡단면 점은 67.8%다. 횡단면 곡선은 3일 45.8% → 6일 67.8% → 9일 77.1%로 가파르게 오르지만 실제로 추적 가능한 코호트는 그 속도로 채워지지 않는다.
- 영향: [ADR-0027](decisions/0027-order-plan-requery-window.md)이 재조회 범위를 최근 21일로 정한 근거는 횡단면 곡선의 "15~17일 평탄화"다. 실제 코호트가 훨씬 느리게 채워진다면 평탄화 시점이 21일보다 뒤일 수 있고 그러면 창이 짧아 공고 전환을 놓친다. [fill-curve](../validation-runs/20260829-order-plan-fill-curve.md)가 "횡단면과 종단이 어긋나면 종단이 정본"이라고 미리 정해 두었으므로 이 관측이 우선한다.
- 지금 해결할 수 없는 이유: 종단 관측점이 세 개이고 기간이 5일뿐이다. 21일이 틀렸다고 단정하기에 부족하다. 나이 15일과 21일 근처(2026-09-08, 2026-09-14 무렵) 관측이 나와야 판단할 수 있고, 재조회 범위 변경은 수집 비용과 API 한도에 직접 영향을 주므로 사람 결정이 필요하다.
- 접근 방법: 같은 구간의 재조회를 계속 쌓아 나이 21일 이후까지 본다. 횡단면 구간들은 폭이 3일로 같은데 건수가 28~997로 흔들려(08-15 광복절 구간이 28건) 비교 가능한 코호트가 아니다. 횡단면 기울기가 나이 효과인지 코호트 구성 차이인지 구분하려면 요일 구성이 같은 구간끼리 비교하거나, 08-21~08-23 구간도 종단으로 추적해 두 방법을 같은 코호트에서 직접 대조한다.

## Alembic revision 식별자가 version table 컬럼보다 길어 PostgreSQL 배포가 불가능했다

- 재현 조건: 빈 PostgreSQL 17에서 `alembic upgrade head`를 실행한다. `docs/validation-runs/20260831-postgresql-migration-verification.md`에 실행 기록이 있다.
- 증상: `0003`까지 적용한 뒤 `psycopg.errors.StringDataRightTruncation: value too long for type character varying(32)`로 중단한다. Alembic 1.19.1은 version table을 만들 때 `Column("version_num", String(32))`를 하드코딩하는데(`alembic/ddl/impl.py:169`) `0004_cumulative_external_identity`(33자)와 `0006_bid_first_opportunity_registration`(39자)이 그보다 길다. PostgreSQL DDL은 트랜잭션이라 실행 전체가 롤백되어 `alembic_version` table조차 남지 않는다.
- 영향: `0004` 이후 어떤 배포도 불가능했다. PostgreSQL만 선언 길이를 강제하고 SQLite는 무시하므로 전체 테스트 스위트는 통과하고 있었다. T-7·T-8·T-12·T-16a가 추가한 스키마가 정본 저장소에 한 번도 적용된 적이 없다.
- 상태: **해결** (2026-08-31, T-9). `alembic/env.py`가 migration 실행 전에 version table을 `VARCHAR(64)`로 직접 만들고, 기본 폭으로 이미 만들어진 table은 `ALTER TABLE IF EXISTS`로 넓힌다. Alembic은 `Table.create(checkfirst=True)`로 생성하므로 이미 있는 table을 건드리지 않는다. 두 문장 모두 멱등이다. 폭은 `app.db.ALEMBIC_VERSION_NUM_WIDTH` 한 곳에 있고 `test_every_revision_identifier_fits_the_version_column`이 모든 revision 식별자를 그 안에 가둔다.
- (해결 전 기록) 대안이던 revision 식별자 단축은 `down_revision` 사슬, 파일명, `contracts.md`·`findings.md`·`lifecycle-workstream.md`의 문서화된 식별자를 모두 바꿔야 해서 선택하지 않았다.

## PostgreSQL 전용 테스트가 스키마 변경 뒤에도 갱신되지 않고 skip됐다

- 재현 조건: `BIDOPS_TEST_POSTGRES_URL`을 disposable PostgreSQL 17에 맞추고 `pytest tests/test_models_runtime.py`를 실행한다.
- 증상: 9건이 `column "run_id" of relation "notice" does not exist`로 실패한다. `seed_base()`가 `insert into notice(run_id, notice_key)`를 실행하는데 `run_id`는 `0004_cumulative_external_identity`가 ADR-0026에 따라 `notice`에서 없애고 `notice_observation`으로 옮긴 컬럼이다.
- 영향: T-7이 공고 정체성 모델을 바꿀 때 이 테스트가 함께 갱신되지 않았다. `BIDOPS_TEST_POSTGRES_URL`이 없으면 `requires_postgres`가 조용히 skip하므로 스위트는 계속 초록이었다. **정본 저장소의 불변식을 검증하라고 만든 테스트가 검증하지 않는 상태로 남아 있었다.**
- 상태: **해결** (2026-08-31, T-9). `seed_base()`가 `notice`를 누적 행으로 넣고 `notice_observation(notice_id, run_id, ...)`을 따로 넣는다. 13건 전부 통과한다.
- 남은 위험: skip이 기본값이라는 구조는 그대로다. `web/run-web-tests.sh`를 거치면 임시 PostgreSQL 17이 항상 서므로 이 경로에서는 잠복하지 않는다. 그러나 `pytest tests/test_foo.py`처럼 개별 파일을 직접 지정하면 여전히 조용히 skip하고 exit 0이다(`addopts = "-ra"`가 사유는 출력한다). 이 경로까지 막을지, CI로 대신할지는 D-11의 남은 결정이다.

## 애플리케이션 스택의 publish port가 host에서 열리지 않는다

- 재현 조건: Docker Engine 29.7.2에서 `docker compose -f docker-compose.yml up -d`로 기동한 뒤 `curl http://127.0.0.1:18787/api/health`, `ss -ltn`으로 15432·18787·19000·19001을 확인한다.
- 증상: 컨테이너는 정상이고 `web` 컨테이너 안에서 `/api/health`가 `{"status":"ok"}`를 반환하지만 host에서는 어떤 publish port도 바인딩되지 않는다. `HostConfig.PortBindings`에는 매핑이 남아 있으나 `NetworkSettings.Ports`가 `null`이다. `--internal` bridge 하나에만 붙은 컨테이너에 `-p`를 준 최소 재현에서도 host 연결이 실패하고, 일반 bridge에서는 같은 구성이 성공한다. `docker-compose.yml`의 `database`·`storage`·`scanning`·`analysis`는 모두 `internal: true`이므로 web·postgres·minio의 publish 선언이 전부 무효다.
- 영향: 문서화된 최초 기동 절차의 host `curl` health 확인과 관리 화면 접근이 현재 Docker 버전에서 동작하지 않는다. 컨테이너 내부 실행으로만 상태를 확인할 수 있어 통합 검증 절차와 운영 접근 경로가 성립하지 않는다.
- 지금 해결할 수 없는 이유: 해결하려면 `web`에 non-internal network를 추가해야 하는데, 이는 "기본 network는 내부망"이라는 배포 경계와 `test_runtime_contract.py`의 `all(network.get("internal") is True ...)` 계약을 함께 바꾸는 변경이다. 보안 경계 변경이므로 결정 기록과 회귀 테스트 갱신이 선행되어야 한다.
- 접근 방법: `com.docker.network.bridge.enable_ip_masquerade=false`를 지정한 전용 edge bridge를 만들어 `web`에만 연결하는 방식을 실측했다. host에서 publish port가 열리고 컨테이너의 외부 TCP 연결은 계속 차단된다(다만 embedded DNS를 통한 외부 이름 해석은 남는다). 함께 `127.0.0.1` 바인딩을 명시해 현재 `0.0.0.0` publish를 좁히고, postgres·minio는 publish 없이 `docker compose exec`로만 접근하도록 분리한다. 계약 테스트는 "egress network는 overlay에서만 추가한다"와 "edge network는 masquerade 비활성"을 확인하도록 바꾼다.

## 발주계획 Qwen 잘림 응답의 실패 token 계측이 보존되지 않는다

- 재현 조건: 실행 `20260824-20260826-interim-v4`의 동결 모집단 997건을 Qwen `qwen3.8:27b`, 고정 batch 25, `think="high"`, `num_predict=4096`으로 판정한다. 40개 중 10개 batch에서 Ollama가 `done_reason=length`를 반환한다.
- 증상: adapter가 `done_reason=length`를 확인하자마자 `truncated_output` 예외를 발생시켜 실패 응답의 `prompt_eval_count`, `eval_count`, thinking/content 길이와 duration을 결과에 옮기지 못한다. 해당 batch의 25건은 오류와 분배 latency만 갖고 input/output token은 `null`로 남는다.
- 영향: 생성 길이 제한이 직접 종료 원인이라는 것은 확인할 수 있지만, batch 크기, thinking 길이, 최종 JSON 길이가 각각 한도 소진에 얼마나 기여했는지 분해할 수 없다. 현재 실행은 747/997건만 성공했으므로 Qwen을 운영 후보로 승인하거나 안전한 batch·token 값을 결정할 근거가 부족하다.
- 지금 해결할 수 없는 이유: 현재 범위는 기존 불변 실행의 사후 결과 기록이다. 실패 batch telemetry를 추가하려면 method-result 계약의 batch 진단 표현, 비밀·본문 비보존 경계, renderer와 단위 테스트를 함께 변경하고 새 run ID로 live 재검증해야 한다.
- 접근 방법: 실패 응답 본문은 저장하지 않고 `done_reason`, prompt/eval token count, total/eval duration, thinking/content 문자 수만 안전한 batch 진단으로 보존한다. 동일 실패 batch에서 기준 설정을 재현한 뒤 batch 10, `num_predict=8192`, 모델이 지원하는 thinking 설정을 한 변수씩 분리해 비교한다. 상세 증거와 artifact hash는 [`20260828-order-plan-screening-interim-v4.md`](../validation-runs/20260828-order-plan-screening-interim-v4.md)에 기록했다.

## 개발용 Codex 심층 검토 경로가 외부 전송 허용 범위를 넘는다

- 재현 조건: (제거 전) `docker-compose.codex-reference.yml`로 `BIDOPS_ANALYSIS_PROVIDER=codex-exec`, reference mode, 승인 notice ID를 설정하고 심층 검토 stage를 실행한다.
- 증상: `CodexExecClient.invoke()`가 일반 vLLM과 같은 `build_prompt()`를 사용한다. stage 입력에는 구조화된 RFP 요구사항 excerpt가 들어가고 delivery stage에는 회사 profile facts·evidence가 들어가므로 hosted Codex에 전송될 수 있다.
- 영향: 공개 발주계획 메타데이터와 별도 승인된 최소 회사 역량 요약만 외부 모델에 보낸다는 확정 정책을 위반한다. 공고 allowlist와 기본 비활성은 실행 승인만 제한할 뿐 금지된 payload 종류를 제거하지 않는다.
- 상태: **해결** (2026-09-03, provider 제거). hosted 외부 deep-review provider와 그 Compose overlay·env 예시·설정·문서를 저장소에서 삭제했다. 남는 심층 검토 provider는 `vllm`과 `mock`뿐이며, 이 경로로 RFP·첨부·profile 전문·evidence가 외부로 나갈 수 있는 코드는 존재하지 않는다.
- 검증: `Settings.analysis_provider`의 선택지가 `{"vllm", "mock"}`뿐이고 `codex` 이름의 설정·속성이 남지 않았음을 `web/backend/tests/core/test_config_t9.py`가 고정한다. backend 전체 suite는 `2 failed, 1091 passed, 5 skipped`였고 실패 2건은 이 변경과 무관한 `tests/screening/test_screening_orchestrator.py`의 기존 결함이다(기준선 `1097 passed`에서 삭제한 테스트 7건을 빼고 새 테스트 1건을 더한 값).
- 후속: 외부 비교 실험이 다시 필요하면 발주계획 전용 projection·payload preview·사람 승인 경계를 새로 설계한다. 그 구현의 테스트는 RFP, 첨부, profile 전문·evidence, 내부 review 필드가 payload에 들어가면 호출 전에 실패하는지 확인해야 한다.

## 런타임 이미지에 회사 프로필 자료가 포함된다

- 재현 조건: 현재 `web/Dockerfile`로 runtime image를 build한 뒤 `/app/docs/reference`와 `/app/web/backend/app/screening` 내용을 검사한다.
- 증상: `COPY docs/reference /app/docs/reference`가 `company-profile.md`와 회사 실적 제목 TSV를 복사하고, 별도 TSV copy가 이를 반복한다. `COPY web/backend/ ./`는 `baseline_company_profile.md`도 복사한다. `.dockerignore`는 reference PDF만 제외한다. Dockerfile의 회사자료 제외 주석과 실제 image 내용이 다르다.
- 영향: image registry, build cache, image export에 회사 프로필·실적 근거가 포함될 수 있어 회사자료를 image에 넣지 않는 보안 경계를 위반한다.
- 상태: **해결** (2026-09-01, runtime image 경계 보완). `docs/reference`의 build-context 예외를 제거하고 backend baseline을 `.dockerignore`로 제외했다. `COPY web/backend/ ./`는 유지하되 세 회사자료는 image에 복사하지 않으며, current profile·회사 실적 제목 TSV·승인 baseline은 `web` 서비스에만 read-only bind mount로 실행 시 주입한다. 기존 baseline digest 검증은 그대로 사용한다.
- 검증: 기존 runtime contract test는 Dockerfile의 세 파일 copy 부재, `.dockerignore`의 세 파일 제외, `web`의 세 read-only mount를 함께 확인했고 `11 passed`였다. 2026-09-01 실제 image build/run에서 `/app/docs/reference/`에는 `.`·`..`만 있었고 profile·실적·baseline 이름을 찾는 `find`는 무출력이었다. `docker compose -f docker-compose.yml config`는 `COMPOSE_OK`, backend 전체 suite는 `1037 passed, 5 skipped, 6 warnings`로 실패 0건이었다.
- 접근 방법: 일반 `docs/reference`와 backend baseline의 bulk copy를 build context 단계에서 차단하고, `skills/`와 그 공개 workflow contract만 image에 둔다. 프로필·실적 reference·baseline은 승인된 read-only host checkout 경계로 실행 시 주입하고, baseline은 기존 digest 검증으로 무결성을 확인한다.

## 프로필 조회 API가 원문과 서버 경로를 노출한다

- 재현 조건: `GET /api/profile/snapshots`, `GET /api/profile/sections`, `GET /api/profile/unknowns`를 호출하거나 프로필 파일 읽기 오류를 유발한다.
- 증상: snapshots item의 working-tree `source_ref`는 내부 상대 파일 경로다. sections 응답은 filesystem `source`, `raw_blocks[].raw`, section `raw`, `source_line`을 포함한다. unknowns도 filesystem `source`를 반환하며 `parse_errors` 문자열에 원본 `OSError`의 절대 경로가 들어갈 수 있다. sections·unknowns는 현재 working tree parser 결과에 묶이고 승인된 불변 profile version·digest를 응답에 고정하지 않는다.
- 영향: 사내망 사용자 모두에게 UI에 필요한 범위를 넘는 회사 프로필 원문과 서버 배치 구조가 노출된다. 실행 중 working tree가 변하면 같은 조회 route가 다른 프로필을 반환할 수 있어 승인 snapshot 경계도 흐려진다.
- 상태: **해결** (2026-09-01, A-3 최소 projection 전환). 세 route는 승인된 snapshot version·digest와 구조화 projection만 반환하고, working-tree `source_ref`·filesystem source·source line·raw block/text·원문 예외를 wire에서 제외한다. Git blob은 40자 SHA만 계보 식별자로 유지하며 파싱·읽기 실패는 닫힌 `error_codes`로 표현한다.
- 검증: 실제 `docs/reference/company-profile.md`의 특징적 문자열과 임시 snapshot artifact 누락 경로를 포함한 `test_profile_projection.py`가 snapshots·sections·unknowns 응답에 원문·절대 경로·원문 parse error가 없음을 확인했다. 백엔드는 `1038 passed, 5 skipped, 6 warnings in 566.02s (0:09:26)`, 프론트엔드는 `598 passed, 10 skipped (5.5m)`으로 완료했고 `tsc`·production build도 통과했다.

## legacy 첨부 업로드가 악성코드 검사와 객체 격리를 우회한다

- 재현 조건: `POST /api/notices/{notice_pk}/attachments`로 허용 확장자·크기의 파일을 등록한 뒤 download endpoint를 호출한다.
- 증상: legacy attachment service는 확장자와 50MiB 한도만 확인하고 `/app/web/data/attachments`로 rename한 뒤 DB를 commit한다. MIME 판별, quarantine, ClamAV, MinIO object version·hash 없이 바로 다운로드할 수 있다. T7은 `/app/data`와 `/app/reports`만 volume으로 연결하므로 이 attachment 경로는 container 재생성 때 유실될 수도 있다. `AttachmentResponse.stored_path`는 DB 값을 그대로 내보내 notice directory와 로컬 저장 layout을 client 계약에 노출한다.
- 영향: 파일 내용이 확장자와 다르거나 악성인 첨부가 웹 process의 로컬 저장소와 사용자 download 경로로 들어가 Lean document upload의 안전 경계를 우회한다. DB row는 남고 파일만 사라지는 불일치도 생길 수 있고, path 노출은 서버 배치 구조를 외부 wire에 고정한다.
- 상태: **해결** (2026-09-01, A-2 legacy upload 안전 경계·응답 projection·보관 volume 보완). 기존 `Attachment` schema와 id 기반 legacy download 호환성은 유지한다.
- 검증: 감염 표식·ClamAV 사용 불가 파일은 4xx로 등록되지 않고 filesystem 산출물이 남지 않으며, safe PDF만 등록된다. 첨부 처리·notice detail 응답에는 `stored_path`가 없고 `docker compose -f docker-compose.yml config`가 통과한다.
- 접근 방법: 업로드 바이트를 quarantine object에 저장하고 MIME·구조·ClamAV 검사를 통과한 경우에만 source object로 승격한 뒤 legacy `Attachment`와 named-volume의 로컬 호환 사본을 만든다. `stored_path`는 내부 metadata로만 유지하고 response schema·serializer에서 제거했다. 기존 attachment object metadata schema 이전은 별도 범위다.

## MinIO versioning 초기화가 실패해도 stack이 계속 기동한다

- 재현 조건: MinIO에서 bucket versioning 명령이 권한·호환성 오류로 실패하는 환경에서 `scripts/minio-init.sh`를 실행한다.
- 증상: `mc version enable` 뒤 `|| true`가 모든 실패를 삼키고 실제 versioning 상태를 다시 확인하지 않는다. init service는 versioning이 꺼져 있어도 성공할 수 있다.
- 영향: DB가 object version ID를 불변 정본처럼 저장하는 전제가 깨지고 overwrite·backup·restore에서 같은 object key의 역사 bytes를 보장할 수 없다.
- 상태: **해결** (2026-09-01). `|| true`를 제거하고 bucket마다 `mc version info --json`으로 상태를 되읽어 `"versioning":{"status":"Enabled"`가 아니면 init service를 실패로 끝낸다. `mc version enable`은 이미 versioned인 bucket에서도 성공하므로 멱등성은 유지된다.
- 되읽기가 필요한 이유: `mc version info`는 **un-versioned bucket에서도 exit 0**을 반환한다(`RELEASE.2025-08-13T08-35-41Z`에서 실측). 종료 상태만으로는 versioning 여부를 구분할 수 없어 status 문자열이 유일한 증거다. mc image에는 `sed`·`awk`가 없어 셸 `case` 매칭으로 판별한다.
- 검증: disposable MinIO(`RELEASE.2025-09-07T16-13-09Z`)에 실제 스크립트를 실행했다. 정상 기동은 exit 0에 4개 bucket 모두 `versioning is enabled`, 재실행도 exit 0. `mc version enable`이 실패하는 상황을 넣으면 수정 전 스크립트는 **exit 0으로 성공하면서 4개 bucket 전부 `un-versioned`** 였고, 수정 후에는 `bucket versioning is not enabled: bidops-source`와 함께 exit 1로 끝난다.

## 객체 복구가 원본 version ID와 복구 대상 version ID를 혼동한다

- 재현 조건: `backup-objects.sh`로 version별 backup을 만든 뒤 빈 MinIO에 `restore.sh`를 실행하고 `verify-active-hashes.sh`로 검사한다.
- 증상: backup manifest는 source version ID를 기록하지만 local file을 target에 `mc cp`하면 새 target version ID가 생긴다. restore는 새 ID를 기록하지 않고 verifier는 source version ID로 target object를 조회한다. `ACTIVE_HASH_MANIFEST`를 DB active reference에서 생성·완전성 검사하는 경로도 없다.
- 영향: 정상 복구도 version lookup에서 실패하거나, 수동 manifest가 일부 active object를 빠뜨려도 DB 연결만 확인한 채 복구 검증이 끝날 수 있다. object-first 복구 완료를 주장할 수 없다.
- 상태: **해결** (2026-09-01, A-6 object-first restore MVP).
- 검증: `backup-objects.sh`가 source stored-byte hash를 확인하고, `restore.sh`가 매 object의 target version ID를 `object-version-mapping.tsv`에 기록한다. 복구 뒤 DB에서 `content_object_location`과 `content_object`를 query해 active manifest를 생성하고, verifier가 일반 namespace의 target ID·stored-byte hash와 model-response의 target ID·존재를 확인하며 DB active 집합 및 복구된 모든 version 집합의 누락·추가·중복을 실패시킨다. disposable MinIO 원본·case별 빈 복구 대상과 PostgreSQL 17에서 정상 복구, 손상 backup, 누락 active object 세 경우를 실행해 확인했다.
- 접근 방법: restore 때 source version → target version mapping과 stored-byte hash를 기록하고 DB가 가리키는 모든 active object를 query해 manifest와 일대일 대조한다. verifier는 일반 namespace에 target version ID와 stored-byte hash를, model-response에는 target version ID와 존재를 검사하며 누락·추가·중복을 모두 실패시킨다.

## 암호화된 model-response active object는 stored-byte hash로 검증할 수 없다

- 재현 조건: 암호화된 model-response를 생성해 `ContentObjectLocation(namespace_key='model-response', status='verified')`로 active manifest에 포함한 뒤 복구 검증을 실행한다. `ContentObject.sha256`는 plaintext aggregate의 SHA-256이고 MinIO object bytes는 `BIDOPS-AESGCM-V1\0` envelope와 nonce·ciphertext다.
- 영향: manifest의 model-response hash를 MinIO stored bytes의 SHA-256과 비교하면 정상 복구도 항상 불일치해 검증이 실패한다. 암호화된 payload의 stored-byte 무결성은 현재 DB hash로 입증할 수 없다.
- 남은 제약: verifier는 model-response의 stored-byte hash 비교를 하지 않고 target version에서 object 존재와 version만 확인한다. 다만 DB active 집합 일치, 누락·추가·중복 실패, source→target version mapping 및 target version 존재 검사는 다른 namespace와 동일하게 유지한다.
- 지금 이렇게 두는 이유: 이번 A-6의 목적은 정상 복구를 검증 가능하게 만드는 것이며, 기존 `ContentObject.sha256`의 plaintext 의미와 암호화 저장 경계를 보존해야 한다. 스키마 변경 없이 이 namespace만 예외 처리하는 것이 현재 복구 계약과 fail-closed 집합 검사를 모두 유지하는 방법이다.
- 후속 방향: stored-byte hash를 별도 필드로 기록하는 스키마 보완을 설계·적용해 암호화 envelope도 내용 무결성까지 검증한다. 이는 이번 범위가 아니다.

## 분석 worker DB 역할이 모든 업무 table을 수정할 수 있다

- 재현 조건: migration 뒤 PostgreSQL에서 `worker` role의 table privilege를 조회한다.
- 증상: `scripts/migrate.sh`가 현재와 미래의 `bidops` 모든 table에 `SELECT, INSERT, UPDATE, DELETE`를 부여한다.
- 영향: 분석 worker 자격증명이 탈취되거나 코드가 오동작하면 사람 리뷰·최종 의견·정책·감사 등 worker 책임 밖의 row도 수정할 수 있어 최소 권한과 사람 결정 경계가 DB에서 강제되지 않는다.
- 상태: **해결** (2026-08-31, MVP DB 보완). `scripts/runtime-privileges.sql`이 migration 뒤 기존 blanket/default grant를 회수하고 app·worker의 table·operation·column allowlist만 다시 부여한다. 미래 table은 두 runtime role에 DML을 자동 상속하지 않고 `ro_backup` 만 `SELECT`를 상속한다.
- 검증: disposable PostgreSQL 17에서 실제 `has_table_privilege`·`has_column_privilege`를 검사한다. worker는 사람 review·judgment/review revision·quality policy·final opinion을 수정할 수 없고, overview도 실제 deterministic preparation에 필요한 review/snapshot 생성과 review 지정 상태 컬럼 갱신만 허용한다.

## PostgreSQL과 MinIO 관리 port가 모든 host interface에 publish된다

- 재현 조건: 기본 `docker-compose.yml`을 기동하고 host의 listen address를 확인한다.
- 증상: PostgreSQL, MinIO API, MinIO console port mapping에 host IP가 없어 Docker가 기본적으로 모든 host interface에 bind할 수 있다.
- 영향: Compose internal network와 무관하게 LAN에서 DB·객체 저장소 port에 직접 접근할 수 있어 애플리케이션 API만 사용하는 접근 경계를 우회한다. 실제 노출 범위가 host firewall 상태에 의존한다.
- 상태: **해결** (2026-09-01). 세 mapping 모두 `${BIDOPS_ADMIN_BIND_HOST:-127.0.0.1}:` prefix를 갖는다. 기본 template은 loopback에만 bind하고, 원격 관리는 `.env`에서 이 값을 명시적으로 넓히는 opt-in이다. `test_admin_ports_bind_to_loopback_by_default`가 세 mapping의 host IP field 존재를 계약으로 고정한다.
- publish를 제거하지 않은 이유: host에서 `psql`·`mc`로 DB·객체를 확인하는 개발 검증 경로가 살아 있어야 한다. loopback bind는 그 경로를 유지하면서 LAN 노출만 없앤다. **애플리케이션 port(`BIDOPS_WEB_PORT`)는 사내망 접근이 설계된 경계이므로 좁히지 않았다.**
- 남은 위험: 이 stack의 network가 전부 `internal: true`라 현재 Docker 버전에서는 publish 자체가 host에 bind되지 않는다(위 "애플리케이션 스택의 publish port가 host에서 열리지 않는다"). 그 항목을 해결해 실제로 bind되기 시작할 때 이 loopback 기본값이 효력을 갖는다. 지금은 선제적 방어다.

## legacy mutation 일부가 담당자 이름과 감사 기록 없이 실행된다

- 재현 조건: legacy review upsert, attachment upload·delete, agency portal create·patch, run ingest·subprocess 실행 endpoint를 호출한다.
- 증상: 해당 경로는 `X-BidOps-Actor-Name`을 요구하지 않거나 reviewer가 optional이고, 작업별 `AuditEvent`를 같은 transaction에 남기지 않는다. Lean 문서·심층 검토와 screening control 계열만 별도 actor·audit 경계를 가진다.
- 영향: 사내 사용자가 변경·승인할 때 이름을 남긴다는 채택 결정이 API 전체에서 성립하지 않으며 누가 첨부를 지우거나 포털·리뷰·회차를 바꿨는지 일관되게 추적할 수 없다.
- 상태: **부분 해결** (2026-09-01, A-4). 첨부 upload/delete, agency portal create/patch, screening policy create/candidate/activate에 기존 actor parser와 append-only `AuditEvent`를 적용했다. legacy review와 일부 run/subprocess mutation은 여전히 별도 작업이다.
- 검증: 세 router의 7개 mutation이 actor 없는 요청을 400으로 거부하고, actor가 있으면 같은 transaction에 `AuditEvent`를 남기는 회귀가 통과했다. frontend API 호출부와 포털·정책 화면도 actor header를 전송한다.
- 접근 방법: 새 감사 테이블이나 helper layer를 만들지 않고 기존 `validate_actor`와 `AuditEvent`를 각 mutation transaction에 연결했다. 과거 actor 없는 row는 추정하지 않는다.

## 현재 보고서 renderer가 screening v3를 처리하지 못한다

- 재현 조건: `bidops.screening.v3`의 `screening-results.json`을 현재 report stage 또는 `render_report.py`에 전달한다.
- 증상: current screening runtime은 v3를 만들고 적재기는 v3를 받지만 report renderer는 `bidops.screening.v2`만 허용해 즉시 종료한다.
- 영향: 새 판정 실행의 결과를 기존 HTML·feedback 흐름으로 연결할 수 없고 자동 pipeline에서 판정과 보고 사이가 끊긴다.
- 지금 해결할 수 없는 이유: v3의 partial/failure·execution binding을 HTML과 feedback에 어떻게 표시할지 소비자 계약과 회귀 기준이 필요하다.
- 접근 방법: v2 의미를 바꾸지 않은 채 renderer에 명시적 v3 adapter를 추가하고 부분 성공·failure artifact·승계 provenance를 표시한다. v2와 v3 fixture의 결정성을 각각 검증한다.

## 승인된 프로필 기준선 commit이 현재 저장소 history에 없다 (2026-08-31 결정으로 수용)

- 재현 조건: `git cat-file -e ee621835db934ddac944f7a07a986ed0b73ecc7a^{commit}`을
  현재 checkout에서 실행한다.
- 증상: 승인 commit과 그 path의 blob이 둘 다 Git object DB에 없다.
- 실제 영향: **없다.** byte-identical 파일이
  `web/backend/app/screening/baseline_company_profile.md`로 벤더링돼 있고
  `BASELINE_PROFILE_SHA256= a231ab54…`로 검증된다. `read_git_source()`는 git 조회가
  불가할 때만 이 파일로 fallback하고, git이 있으면 동등성을 교차 확인해 drift를 막는다.
  `test_profile_snapshot*` 14건은 현재 모두 통과한다.
- 범위 정정: 이 commit은 `model_comparison` 품질 gate 전용 **역사 anchor**다.
  `operational_approval`은 `profile_source = "current"`를 요구하고 런타임의
  `snapshot_current()`는 현재 working tree 프로필(sha256 `96731dd5f77d…`)을 읽는다.
  운영 판정은 이미 현재 프로필을 쓰고 있으므로 정본이 갈라진 상태가 아니다.
- 결정: 2026-08-31에 이 상태를 그대로 두기로 했다. 현재 프로필을 역사 anchor에 덮어쓰면
  `model_comparison`이 현재-대-현재 비교가 되어 "역사 baseline과 설명 가능한 비교"라는
  목적 자체가 사라지므로 하지 않는다.
- 남는 제약: `git:ee621…`을 요구하는 model comparison gate는 git 경로로 재현할 수 없고
  벤더링 파일에만 의존한다. 그 파일이 저장소에서 사라지면 역사 비교가 불가능해진다.

## 문서 준비와 실패 심층 검토 재시작을 화면에서 완료할 수 없다

- 재현 조건: ready document bundle이 없는 공고를 브라우저에서 열거나 deep-review attempt가 실패한 상태를 연다.
- 증상: 조회와 ready bundle 이후 심층 검토 화면은 있지만 bundle 생성·문서 upload·metadata 수정·확정, 실패 attempt의 새 attempt 생성 action이 없다.
- 영향: 담당자는 curl 또는 CLI를 사용해야 하므로 목표 업무 흐름이 화면에서 끊기고, actor·idempotency·상태 fence를 잘못 다룰 가능성이 커진다.
- 지금 해결할 수 없는 이유: backend 계약은 준비됐지만 frontend Phase 3 구현과 browser 회귀 검증이 별도 코드 작업으로 남아 있다.
- 접근 방법: typed Lean API client, document preparation panel, terminal failure 전용 retry, polling, 403/503 상태 표현을 구현하고 fake API browser 흐름과 좁은 viewport를 검증한다.

## 개발계정 일일 1,000회 한도의 실제 여유가 측정되지 않았다

- 재현 조건: 발주계획·사전규격을 3일 window로 page 끝까지 수집하고 endpoint·page·retry별 실제 요청 수를 집계한다.
- 증상: 알려진 것은 약 1,200개 발주계획과 약 40개 SW 사전규격이라는 레코드 규모뿐이며, 페이지 크기·endpoint 분할·정정 조회·재시도를 포함한 호출 수 기록은 없다.
- 영향: 일 1,000회가 초기 실험에 충분하다는 추정은 가능하지만 scheduler를 안전하게 활성화하거나 운영 증액량을 산정할 근거는 부족하다.
- 지금 해결할 수 없는 이유: 신규 수집기와 quota telemetry가 아직 없고 실제 개발계정 응답의 pagination을 관측하지 않았다.
- 접근 방법: 동결 3일 실험에서 실제 HTTP 요청을 endpoint·page·retry별로 기록하고 cache hit를 분리한다. 700회 경고, 900회 신규 요청 중지로 시작한 뒤 관측치를 이용해 운영계정 활용사례와 증액량을 정한다.

## 사설 vLLM model artifact가 불변 digest로 고정되지 않았다

- 재현 조건: analysis worker preflight와 `/v1/models` 응답으로 실행 model identity를 확인한다.
- 증상: served model ID `qwen3.8-27B`는 확인할 수 있지만 weight digest가 응답에 없고 server image도 mutable tag를 사용할 수 있다.
- 영향: 같은 model name이 다른 bytes를 가리켜도 실행 당시 승인한 artifact와의 차이를 자동 검출하지 못할 수 있다.
- 지금 해결할 수 없는 이유: image digest와 model revision 또는 로컬 artifact digest는 모델 서버 운영자가 제공해야 한다.
- 접근 방법: server image digest, immutable model revision·artifact digest를 deployment manifest에 고정하고 startup preflight가 이를 quality manifest와 대조하도록 provider 계약을 확장한다.

## 실제 심층 검토 품질 corpus와 사람 gold가 부족하다

- 재현 조건: 대표 HWP/PDF에서 요구사항 recall, 사람 일치율, unsupported claim 비율을 계산하려 한다.
- 증상: 55개 요구사항 기대 ID 사례는 있으나 원문·claim별 gold mapping과 다양한 기관·문서 형식의 사람 adjudication이 충분하지 않다.
- 영향: Mock E2E와 단일 후보 호출은 실제 사업 판단 품질이나 0.80/0.70/0.10 activation 기준을 증명하지 못한다.
- 지금 해결할 수 없는 이유: 완료 사업의 사용 승인된 첨부와 담당자 기준 답안이 더 필요하다.
- 접근 방법: 공공 SI와 AI·데이터 또는 블록체인 축에서 서로 다른 HWP/PDF 사례를 선정하고 source hash, requirement·자격·배점·위험 gold, claim별 사람 판정을 만든다. 실제 immutable model로 gate를 측정한다.

## 실제 backup·권한·복구 훈련이 없다

- 재현 조건: 운영과 같은 secret·MinIO policy·firewall을 가진 격리 환경에서 PostgreSQL dump와 versioned object backup을 빈 대상에 복구한다.
- 증상: script와 Mock E2E는 있지만 실제 snapshot, object manifest, allow/deny matrix, object → DB → active hash 복구 기록이 없다.
- 영향: RPO·RTO, 최소 권한, 암호화 key 복구, container 재생성 뒤 참조 무결성을 운영 수준으로 주장할 수 없다.
- 지금 해결할 수 없는 이유: 실제 secret manager 주입, 백업 보관 위치, 운영 snapshot, 빈 pre-production target은 저장소 밖의 운영 준비가 필요하다.
- 접근 방법: 운영자가 승인한 복사본으로 역할별 DB 권한, MinIO namespace allow/deny, egress, UID/GID를 검사하고 객체를 먼저 복구한 뒤 DB와 active hash를 대조하는 훈련을 기록한다.

## 담당자 이름은 신원을 증명하지 않는다

- 재현 조건: 사내망 사용자가 mutation에서 다른 담당자의 이름을 입력한다.
- 증상: 시스템은 입력 이름을 감사에 남기지만 실제 사용자의 내부 계정과 일치하는지 확인하지 못한다.
- 영향: 리뷰, 정책 활성화, 외부 모델 전송 승인 기록의 작성자 신뢰도가 사내망 접근 통제 수준에 머문다.
- 지금 해결할 수 없는 이유: 현재는 사내망과 claimed name만 사용하기로 했고 SSO·계정·역할 정보가 연결되지 않았다.
- 접근 방법: 향후 SSO subject를 내부 계정에 매핑하고 세션 만료, 역할, 권한 회수, 기존 claimed-name 감사와의 연결 정책을 도입한다.

## 심층 검토 보고서를 사업기회·공고로 되찾을 목록 계약이 없다

- 재현 조건: 공고 판정 이력에서 심층 검토를 생성해 `/deep-reviews/{id}`로 이동한 뒤 화면을 벗어난다. 사업기회 화면이나 공고 화면에서 그 보고서를 다시 연다.
- 증상: `web/backend/app/deep_review/routers/deep_reviews.py`가 제공하는 읽기 계약은 `GET /deep-reviews/{deep_review_id}` 단건뿐이다. 사업기회·공고로 보고서를 나열하는 endpoint가 없고, 사업기회 목록·상세 응답과 공고 응답에도 `deep_review_id`가 없다. 보고서 식별자를 따로 적어 두지 않으면 만든 보고서로 돌아갈 길이 없다.
- 영향: `docs/design/PRD.md` §2.2가 요구한 "사업기회 화면의 명시적 진입점"을 데이터로 채울 수 없다. 2026-09-02 화면 개선 2단계는 사업기회 상세에 식별자로 여는 진입점을 두고 목록을 제공할 수 없다는 사실을 화면에 명시하는 선에서 멈췄다. 목록이 비어 보이는 것을 보고서가 없다는 뜻으로 오해할 위험은 문구로만 막고 있다.
- 지금 해결할 수 없는 이유: 해결에는 REST 계약 추가(사업기회 또는 공고별 심층 검토 목록)나 기존 응답에 식별자 노출이 필요하다. 화면 개선 2단계의 범위는 프론트엔드이며 `docs/contracts.md`의 소비자 계약과 백엔드를 바꾸지 않기로 했다.
- 접근 방법: `GET /opportunities/{id}/deep-reviews` 또는 `GET /notices/{notice_id}/deep-reviews`를 추가해 보고서 식별자·생성 시각·현재 상태를 돌려주고, `docs/contracts.md`와 `docs/deep-review-erd.md`에 소비자 계약으로 등록한다. 그 뒤 사업기회 화면의 진입점을 식별자 입력이 아니라 목록으로 바꾼다.

## Go/No-Go 결정 대기 사업기회를 N+1 없이 집계할 endpoint가 없다

- 재현 조건: 대시보드 "지금 처리할 일"이나 `GoNoGoPage.tsx`에서 "최종 Go/No-Go 결정 대기" 건수를 구하려 한다.
- 증상: `web/backend/app/deep_review/routers/bid_delta.py`는 사업기회 하나의 workspace만 반환하고(`GET /opportunities/{id}/bid-delta` 계열), "계속 추적 중이며 아직 최종 결정이 없는 사업기회 수" 같은 집계 endpoint가 없다. `GoNoGoPage.tsx`는 이를 우회하려고 추적 중 사업기회 목록을 받은 뒤 사업기회마다 bid-delta workspace를 조회하는 N+1을 이미 쓰고 있다(2026-09-02 화면 개선 2단계, 코드 머리 주석에 기록).
- 영향: 대시보드처럼 N+1을 반복할 수 없는 화면(`web/backend/AGENTS.md`·`CLAUDE.md`의 N+1 금지 게이트)은 이 건수를 전혀 계산할 수 없다. 2026-09-03 3단계는 대시보드 항목의 건수를 `null`(확인 불가)로 표시하고 이동 경로만 제공하는 선에서 멈췄다 — 페이지 자체(`GoNoGoPage.tsx`)의 기존 N+1도 아직 걷어내지 못했다.
- 지금 해결할 수 없는 이유: 해결에는 새 집계 REST 계약(예: 사업기회당 최신 `latest_final_decision` 유무를 서버가 먼저 걸러 세는 endpoint)이 필요하며, 이는 백엔드 스키마·서비스 변경이라 이번 프론트엔드 범위를 벗어난다.
- 접근 방법: `GET /opportunities?tracking_status=계속 추적&decision_status=pending` 같은 서버 필터 또는 `GET /bid-delta/pending-count` 집계 endpoint를 추가해 `docs/contracts.md`와 `docs/bid-delta-contract-spec.md`에 등록한다. 그 뒤 `GoNoGoPage.tsx`의 기존 N+1과 대시보드의 `null` 표시를 실제 건수로 교체한다.

## 발주계획 목록 API에 "사람 피드백 미기록" 필터가 없다

- 재현 조건: 대시보드 "지금 처리할 일"에서 "C-2 검토 대기" 건수를 사람이 아직 판정하지 않은 발주계획 수로 정의하려 한다.
- 증상: `GET /api/order-plans`(`web/backend/app/screening/routers/order_plans.py:78`)는 `qwen_relevance`·`human_relevance`를 필터로 받지만, `human_relevance`는 특정 relevance 값(`relevant`|`not_relevant`|`uncertain`)만 받고 "사람 피드백 행 자체가 없음"을 나타내는 값(`missing`/`null`)을 받지 않는다.
- 영향: 2026-09-03 3단계는 이 항목을 "Qwen 신호가 relevant 또는 uncertain인 발주계획" 건수(사람 피드백 여부와 무관)로 근사했다. 실제 "검토 대기"(아직 아무도 보지 않은 건)보다 넓은 집합이라 과대 계상될 수 있고, 화면 설명 문구로만 그 차이를 알린다.
- 지금 해결할 수 없는 이유: `human_relevance=missing` 같은 값을 추가하려면 서비스 쿼리(`OrderPlanScreeningService.list_order_plans`)와 라우터 계약을 함께 바꿔야 하며, 이번 프론트엔드 범위의 대시보드 작업만으로는 안전하게 변경할 수 없다.
- 접근 방법: `human_relevance`에 `missing` 같은 sentinel 값을 추가해 "사람 피드백 행 없음"을 서버에서 걸러주고, `docs/contracts.md`의 `GET /api/order-plans` 항목에 등록한다. 그 뒤 대시보드와 `OrderPlansPage.tsx`의 "검토 대상" 프리셋이 이 필터를 실제 "미판정" 의미로 좁힐 수 있다.

## 사전규격 목록 API에 마감 구간 필터도 임박 집계도 없다

- 재현 조건: 대시보드 "지금 처리할 일"에서 "사전규격 의견등록 마감 임박" 건수를 구하려 한다.
- 증상: `GET /api/pre-specs`(`web/backend/app/lifecycle/routers/pre_specs.py:95`)는 `sw_only`·`business_division`·`origin`·`q`·`sort`·`limit`·`offset`만 받는다. 마감 구간 필터가 없고 집계 응답도 없다. `sort=deadline`은 `deadline_at ASC NULLS LAST`(`pre_specs.py:180`)라 **첫 페이지가 이미 지난 마감으로 채워진다.** 따라서 한 페이지를 받아 클라이언트에서 세면 두 가지가 동시에 틀린다. (1) 지난 마감을 임박으로 센다 — 회차 산출물 `stats.imminent_deadlines`와 달리 서버가 좁혀 준 창이 없는데 `criticalDeadlineCount`에는 하한이 없다. (2) 임박 구간이 페이지 창 밖이라 애초에 도달하지 못한다.
- 영향: 2026-09-03 3단계는 이 항목의 건수를 `null`(확인 불가)로 두고 이동 경로만 제공하는 선에서 멈췄다. 구현 위임 초안은 `limit=50` 한 페이지를 세어 숫자를 표시했는데, 누적 데이터에서는 거의 항상 "만료된 사전규격 수"를 "마감 3일 이내"로 보여주는 값이라 검수에서 되돌렸다.
- 지금 해결할 수 없는 이유: 해결에는 목록 계약에 마감 구간 필터(`deadline_from`·`deadline_to`)나 임박 집계를 추가해야 하며, 이는 백엔드 라우터·스키마 변경이라 이번 대시보드 작업 범위를 벗어난다.
- 접근 방법: `GET /api/pre-specs`에 `deadline_within_days` 또는 `deadline_from`·`deadline_to`를 추가하고 `docs/contracts.md`의 `PreSpecList` 항목에 등록한다. 그 뒤 대시보드의 `null` 표시를 실제 건수로 바꾸고, `criticalDeadlineCount`의 하한 없음이 회차 산출물 전용 전제임을 호출부에서 다시 확인한다.

## C-1과 C-2가 모델 호출 경계를 서로 반대로 잡는다

- 확인: 2026-09-03
- 재현 조건: 같은 "선별" 업무의 두 사례가 모델을 부르는 방식을 비교한다.
- 증상: C-2(발주계획)는 `web/backend/app/core/config.py:351,353`이
  `skills/bidops-screen/scripts/rank_order_plans_bm25.py`와
  `build_order_plan_screening_results.py`를 subprocess로 호출한다.
  [ADR-0001](decisions/0001-artifact-boundary.md)의 경계 그대로다.
  반면 C-1(공고)은 `web/backend/app/screening/orchestrator.py:1555`에서 웹 프로세스 안의
  `OllamaClient`를 직접 생성하고, `app/screening/`에 `ollama.py`(653줄)·`prompts.py`·
  `worker.py`(1,656줄)가 들어와 있다.
- 영향: 같은 업무 규칙이 두 경계에 나뉘어 있어 모델 전송 감사·테스트 격리·정책 pinning의
  확인 지점이 사례마다 다르다. 새 선별 흐름을 추가할 때 어느 쪽을 따라야 하는지 규칙이 없다.
- 지금 해결할 수 없는 이유: C-1은 [ADR-0013](decisions/0013-screening-orchestrator-boundary.md)이
  판정 단계만 애플리케이션 오케스트레이터로 옮긴 결과이고 이미 운영 중인 흐름이다.
  경계를 되돌리려면 정책 활성화·품질 게이트·큐 재실행 경로를 함께 옮겨야 하며
  [ADR-0043](decisions/0043-screening-deep-review-module-boundary.md)·[ADR-0045](decisions/0045-backend-module-layout.md)의 모듈 이주 범위를 넘는다.
- 접근 방법: 모듈 경계 이주가 끝난 뒤 C-1 오케스트레이터의 모델 호출부만 떼어
  C-2와 같은 subprocess 계약으로 맞출 수 있는지 별도로 판단한다. 그 전까지는 두 경계가
  다르다는 사실을 `ARCHITECTURE.md`에 명시해 새 흐름이 임의로 한쪽을 고르지 않게 한다.

## 운영 백엔드가 `experiments/`를 런타임 의존한다

- 확인: 2026-09-03
- 재현 조건: C-2 실행 경로가 읽는 정책·binding 파일의 위치를 확인한다.
- 증상: `web/backend/app/core/config.py:342,344,346`과 `web/backend/app/screening/ingest.py:1324,1333`이
  `experiments/order-plan-screening/config/order-plan-screening-policy.v1.json`과
  `order-plan-screening-phase0-binding.v1.json`을 읽는다.
  [ADR-0038](decisions/0038-order-plan-c2-phase0-contracts.md)이 고정한 계약의 정본이
  이름상 실험 보관소인 디렉터리에 있다.
- 영향: 실험 정리가 운영을 깨뜨릴 수 있고, 반대로 운영 때문에 실험 디렉터리를 자유롭게
  정리할 수 없다. 계약 파일의 집이 `skills/bidops-screen/contracts/`,
  `web/backend/app/deep_review/contracts/`, `experiments/.../config/` 세 곳으로 갈려
  새 계약을 어디 둘지 규칙이 없다. 물리적 중복은 없다(md5 대조 확인).
- 지금 해결할 수 없는 이유: 경로를 옮기면 `core/config.py`·`screening/ingest.py`와 실행 중인 회차의
  binding 참조가 함께 바뀌므로 C-2 종단 실행으로 재검증해야 한다.
- 접근 방법: 정책·binding을 `skills/bidops-screen/contracts/`로 승격하고 위 참조 경로를
  갱신한 뒤 C-2 종단 실행으로 확인한다. 계약 파일의 위치 규칙을 `docs/contracts.md`에 적는다.

## 모듈 이주가 드러낸 죽은 이름 네 자리

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 세 `_LEGACY_GENERATION_CONFIG*` 상수와 `_validate_relative_source_ref`를
  지웠다(지우기 전 `app/`·`tests/`·`scripts/`·`alembic/`·`docs/` 문자열 참조까지 전수 확인).
  `PageFilters`는 core에서 lifecycle로 내렸다 — 의존 규칙 위반은 아니었고(타입이 screening을
  import하지 않는다), "둘 이상이 쓰는 것을 core에 둔다"는 배정 원칙에서 소비자가
  `NoticeListResponse.filters`와 `lifecycle/routers/notices.py` 하나뿐이었다. 옛 자리에 재수출을
  남기지 않았고 응답 계약은 그대로다. 다섯째였던 `RuntimePipelineBridge.pipeline`도 지웠다 —
  받아서 들고만 있고 부르지 않던 인자라, `ScreeningRuntime`·`build_runtime`·조립 계층이 그것을
  넘기던 사슬을 함께 걷어 냈다. 그 결과 `app/runtime.py`의 모듈 runtime 생성 루프에서
  screening만 다르게 부르던 분기가 사라졌다(모듈 순서를 `screening,lifecycle`로 주면 그 인자가
  `None`이 되던 자리이기도 하다).
- 재현 조건: 아래 네 이름의 읽는 쪽을 `web/backend/app/`과 `tests/` 전체에서 찾는다.
- 증상: 대입만 되고 읽히지 않거나, 정의만 되고 불리지 않는다.
  - `_LEGACY_GENERATION_CONFIG`, `_LEGACY_GENERATION_CONFIG_VALUE`,
    `_LEGACY_GENERATION_CONFIG_DIGEST`(`app/screening/models.py:46,49,52`) — 세 이름 모두
    대입뿐이고 참조가 없다.
  - `_validate_relative_source_ref`(`app/core/schema_base.py:74`) — 호출자가 없다.
  - `RuntimePipelineBridge.pipeline`(`app/screening/runtime.py:56`) — 생성자가 lifecycle
    파이프라인 실행기를 받아 보관하지만 읽는 곳이 없다. 이주 전부터 그랬고, 소유 관계를
    드러내려고 남겼다는 주석이 붙어 있다.
  - `PageFilters`(`app/core/schema_base.py:28`)가 core에 있는데 `grade`·`readiness`·`focus`·
    `sample_role` 필드는 선별 어휘다. 실제 사용처는 lifecycle 하나뿐이다
    (`app/lifecycle/routers/notices.py`, `app/lifecycle/schemas/__init__.py`).
- 영향: 읽는 사람이 "선별 계보가 core에 있다" 또는 "legacy generation config가 아직 쓰인다"고
  읽는다. `PageFilters`는 core가 도메인 어휘를 갖지 않는다는 규칙(ADR-0045 §2)의 예외처럼
  보이지만 실제로는 lifecycle 응답 model이 선별 필터를 그대로 되비추는 REST 계약
  (`NoticeList`의 `filters`)의 결과다.
- 지금 해결할 수 없는 이유: 이번 작업의 원칙은 **동작 보존**이었다. 네 이름을 지우거나 옮기면
  import 그래프와 wire schema 이름이 바뀌어, 이주가 REST 표면을 바꾸지 않았다는 확인이
  흐려진다. `PageFilters`를 lifecycle로 내리는 것은 응답 model의 소유를 바꾸는 일이라 계약
  검토가 따로 필요하다.
- 접근 방법: 죽은 세 자리(legacy generation config 3개, `_validate_relative_source_ref`,
  `RuntimePipelineBridge.pipeline`)는 동작 변화가 없으므로 다음 정리 작업에서 삭제한다.
  `PageFilters`는 `NoticeList`의 `filters` 계약을 `docs/contracts.md`에서 먼저 확인한 뒤
  lifecycle로 내릴지, core에 남기되 필드 소유를 문서로 못박을지 판단한다.

## `experiments/`의 회사자료가 gitignore되어 `git archive` 사본이 자족적이지 않다

- 확인: 2026-09-04
- 재현 조건: `git archive <ref> experiments/order-plan-screening | tar -x -C <새 디렉터리>` 로
  실험 트리를 복사한 뒤 `review-inputs/company/`와 `review-inputs/prompts/`를 본다.
- 증상: `.gitignore:7,8`이 `experiments/order-plan-screening/review-inputs/company/*.json`과
  `review-inputs/prompts/*.txt`를 제외한다. 회사자료를 저장소에 넣지 않는다는 경계의 결과이며
  의도된 것이다. 다만 그래서 git에서 만든 사본에는 그 입력이 없다.
- 영향: 격리 검증을 위해 트리 사본을 만드는 절차(모듈 폴더를 지운 복사본에서 테스트를 돌리는
  식)가 C-2 관련 경로에 닿으면 사본이 자족적이지 않다는 것을 검증자가 미리 알아야 한다.
  모르면 "복사본에서만 실패한다"를 코드 결함으로 오해한다.
- 지금 해결할 수 없는 이유: 회사자료를 저장소나 image에 넣지 않는 것이 확정 경계다
  ([security.md](../security.md), 런타임 이미지 항목). gitignore를 푸는 것은 답이 아니다.
- 접근 방법: 트리 사본을 만드는 검증 절차는 `git archive` 뒤에 그 두 디렉터리를 작업 트리에서
  따로 복사하는 단계를 포함한다. 사본 기반 검증을 문서로 고정할 때 이 단계를 함께 적는다.

## `create_app()`은 한 프로세스에서 두 번 부를 수 없다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 확장점 등록에 **소유자 키**를 붙였다. 등록 함수는
  `register_*(provider, *, owner: str)` 형태이고, 같은 owner가 다시 등록하면 제자리 교체(예외
  없음), 다른 owner가 이미 찬 projection 자리를 채우려 하면 여전히 `RuntimeError`다. hook은
  `(종류, owner)`로 키를 잡아 **두 번 등록되지 않는다** — 가드를 그냥 없앴다면 회차 적재 hook이
  두 번 실행됐을 것이고, 가드가 그 결함을 가리고 있었다. 실행 순서는 최초 등록 순서
  (= `BIDOPS_MODULES` 순서) 그대로다. owner는 lifecycle이 해석하지 않는 불투명한 문자열이다.
  `uvicorn --factory app.main:create_app`이 동작한다. 등록 시점은 여전히 `main.py` 조립 시점이다.
- 재현 조건: 같은 인터프리터에서 `from app.main import create_app`을 한 뒤
  `create_app()`을 부른다.
- 증상: `RuntimeError: 판정 projection 제공자가 이미 등록됐다`로 끝난다.
  `app/main.py`의 확장점 등록 구역은 **프로세스 전역** registry에 등록하고,
  같은 파일의 모듈 수준 `app = create_app()`이 import만으로 그 등록을 소진한다.
  `app/lifecycle/extensions.py`의 중복 등록 가드가 두 번째 호출을 막는다.
- 영향: 운영은 `web/Dockerfile`의 `uvicorn app.main:app`이라 무해하다. 그러나
  `uvicorn --factory app.main:create_app`은 즉시 죽고, 앱을 두 개 만들려는 코드는
  `reset_extension_registry`와 `restore_extension_registry`를 손으로 짝지어야 한다
  (`tests/app/test_module_selection.py`의 fixture가 그 boilerplate다). 이 제약이
  어느 문서에도 없어 다음 사람이 factory 방식으로 바꾸려다 막힌다.
- 지금 해결할 수 없는 이유: 중복 등록 가드는 "제공자가 조용히 교체되지 않는다"는
  보장이라 그냥 없앨 수 없다. registry 수명을 앱 객체에 매다는 것은 확장점 설계를
  다시 여는 일이고, 이번 이주의 "동작을 바꾸지 않는다"를 벗어난다.
- 접근 방법: `create_app`이 자기 등록 구역의 registry 수명을 소유하게 하거나
  (앱마다 registry를 새로 만들고 등록한다), 재등록을 같은 제공자에 한해 idempotent로
  만든다. 어느 쪽이든 격리 API 테스트에서 projection이 비지 않는 것을 먼저 확인한다.

## 모듈 공개 표면에 밖에서 아무도 쓰지 않는 이름이 많다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 실제 소비자를 AST로 전수 조사해 줄였다 — lifecycle 61→49,
  screening 66→22, deep_review 12→11. 남은 이름 중 정적 import가 없는 것은 조립 계층이
  `getattr`로 가져가는 router 인스턴스 21개와 `build_runtime` 3개뿐이며, 표에 왜 공개인지를
  구역 주석(조립이 쓴다 / 형제 모듈이 쓴다 / 진입점이 쓴다)으로 적었다. deep_review가 쓰는
  screening seam 세 이름은 그대로다. 더 중요한 것은 **경계 검사 6**을 새로 넣은 것이다 —
  조립 계층의 startup 파일(`app/__init__.py`, `main.py`, `runtime.py`)이 상태를 바꾸거나 모델을
  부르는 이름(`activate_policy`, `seed_policy`, `create_profile_snapshot`, `ingest_run`,
  `OllamaClient`, `ScreeningWorker` 등)을 import하면 실패한다. 별도 프로세스 진입점
  (`workers/analysis.py`, `migrations/import_sqlite.py`)과 `alembic/`은 그것이 목적이므로 제외다.
- 재현 조건: `app/**`와 `tests/**`에서 `from app.<module> import X` / `from ..<module> import X`
  를 AST로 모아 각 모듈 `__init__.py`의 `_EXPORTS` 키와 대조한다.
- 증상: screening 공개 이름 66개 중 router 인스턴스와 `build_runtime`을 빼면 40여 개가
  모듈 밖 소비자가 없다(`activate_policy`, `create_policy`, `seed_policy`,
  `ScreeningOrchestrator`, `ScreeningWorker`, `OllamaClient`, `ArtifactStore`,
  `assemble_*_prompt`, `load_run_judgments` 등). lifecycle에도
  `ATTACHMENT_ORIGINS`·`get_notice`·`get_run`·`list_agency_portals`·`match_agency_portal`·
  `list_attachments_for_notice`·`list_order_plans_for_run`·`IngestResult`·
  `ClaimedDirectoryLoad`가 같은 상태다. 테스트조차 하위 경로로 받는다
  (`from app.screening.ollama import OllamaClient`).
- 영향: 넓이 자체보다 **조립 계층이 그 이름들을 쓸 수 있게 된 것**이 문제다.
  `main.py`가 `from .screening import activate_policy, seed_policy`를 하고 startup에서
  부르면 "앱 startup은 seed·정책 활성화를 하지 않는다"는 경계를 깨는데, 경계 검사
  다섯 중 어느 것도 그것을 잡지 못한다 — 조립 계층 → screening 공개 이름은 허용
  방향이기 때문이다.
- 지금 해결할 수 없는 이유: 어느 이름이 "지금 안 쓰이지만 공개여야 하는가"는 모듈
  진입점 설계의 판단이고, 표를 줄이면 `_EXPORTS`와 `__all__`을 함께 손봐야 해서
  이주 검증이 끝난 시점에 넣을 변경이 아니다.
- 접근 방법: 밖에서 안 쓰는 이름을 `_EXPORTS`에서 빼거나, 뺄 수 없으면 표를 구역으로
  나눠 왜 공개인지(조립이 쓴다 / 형제 모듈이 쓴다 / 진입점이다)를 적는다. startup이
  하면 안 되는 일은 별도 검사로 고정하는 편이 낫다.

## `app/deep_review/contracts/schemas.py`는 호출자가 없는 재수출 파일이다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 파일을 지웠다. 재수출하던 이름 10개가 모두
  `app/deep_review/contracts/__init__.py`의 `__all__`에 이미 있고, `schema_path()`가 `.json`
  파일 이름으로 계약을 찾으므로 이 파일의 존재는 무관했다. 계약 JSON과 `_validator.py`는 그대로다.
- 재현 조건: `grep -rn "contracts.schemas\|from .schemas import" web/backend/app web/backend/tests`
- 증상: 파일 첫 줄이 `"""Compatibility exports for callers that prefer a schemas module."""`
  인데 `app/`·`tests/`·`scripts/`·`docs/` 어디에도 호출자가 없다. 이주 전
  (`app/contracts/deep_review/schemas.py`)에도 이미 그랬다.
- 영향: 없다. 다만 "옛 import 경로에 호환 shim을 두지 않는다"는 이번 경계 작업의
  원칙과 파일이 스스로 밝힌 목적이 어긋나 보여, 읽는 사람이 살아 있는 호환 경로로 오해한다.
- 지금 해결할 수 없는 이유: 죽은 코드 정리는 이번 이주의 범위 밖이었다. 이주가 파일을
  옮긴 commit에서 함께 지웠어야 한다.
- 접근 방법: 지운다. 지우기 전에 `deep_review/contracts/__init__.py`가 같은 이름을
  올리고 있는지만 확인한다.

## lifecycle의 확장점 실패 로그가 특정 제공자의 어휘를 쓴다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 이벤트 이름을 `prespec_attachment.refresh_failed`에서
  `extension.tracking_decision_hook_failed`로, 메시지를 "tracking decision extension hook
  failed"로 바꿨다. 제공자 이름 대신 lifecycle이 정당하게 아는 값만 남긴다(등록된 hook 수,
  예외 타입). try/except **동작은 그대로**이며 registry 조회도 try 안에 남겼다 — 밖으로 빼면
  삼켜지던 오류가 500이 된다. `app/lifecycle/**` 전체를 훑었고 이 자리가 유일한 누수였다.
  `services/pipeline.py`의 `screening-results.json`은 형제 모듈이 아니라 파이프라인 **파일 계약**
  이름이라 남겼다.
- 재현 조건: `app/lifecycle/routers/opportunities.py`의 추적 결정 hook 호출부를 본다.
- 증상: 바로 위 주석이 "어느 모듈이 무엇을 하는지는 모르고"라고 적어 두고, 아래 except
  블록은 `"pre-spec attachment eligibility refresh failed"`와
  `event: "prespec_attachment.refresh_failed"`를 남긴다. 그 문구는 지금 등록된 유일한
  제공자(deep_review)의 어휘다.
- 영향: `BIDOPS_MODULES`에서 deep_review를 빼고 다른 제공자를 붙이면 로그가 거짓이 된다.
  lifecycle이 형제 모듈을 모른다는 규칙이 코드에서는 지켜지는데 로그에서만 새는 자리다.
  (호출부의 try/except 동작 자체는 이주 전과 같다.)
- 지금 해결할 수 없는 이유: 없다. 작은 문자열 변경이지만 이주 검증이 끝난 뒤에 로그
  이벤트 이름을 바꾸면 그 이름에 기대는 관측 기록과 어긋난다.
- 접근 방법: 이벤트 이름을 확장점 이름 기준으로 바꾸고(`extension.tracking_hook_failed`),
  어느 제공자가 실패했는지는 registry가 아는 이름을 함께 남긴다. 로그 이름을 바꾸는
  작업과 함께 묶는다.

## B-F 설계 승인 baseline과 manifest가 없어 전체 설계 게이트를 완료할 수 없다

- 재현 조건: `web/frontend`에서 `npm run test:design`을 실행하고 `docs/design/mockups/canvas.json`의 14개 artboard와 `tests/design-snapshots/`·manifest-driven `design.spec.ts`를 대조한다. 기존 공통 시각 회귀는 `npx playwright test visual.spec.ts`로 실행한다.
- 증상: PLAN.md §3·§5·§7이 요구하는 14-artboard manifest, 승인된 PNG baseline, fixture·viewport·crop 매핑과 그 변경 승인 기록이 저장소에 없다. 현재 design suite는 shell 차원의 5 passed·3 skipped에 그치며, 기존 visual suite는 현 UI와 맞지 않는 baseline 때문에 204 passed·144 failed로 끝난다.
- 영향: B-F 화면의 기능·반응형·접근성 검증은 가능하지만, 승인된 기준 이미지와 픽셀/crop 일치 여부를 주장할 수 없다. 승인 없이 기존 snapshot을 갱신하면 설계 검수 증거를 덮어쓰게 된다.
- 상태: **차단** (2026-09-03 독립검증). 코드 구현 완료의 차단이 아니라 PLAN 전체 완료 정의에 포함된 승인 설계 자산의 부재다.
- 지금 해결할 수 없는 이유: 14개 artboard의 제품 승인 PNG와 각 fixture·viewport·crop의 승인 메타데이터가 저장소나 현재 요청에 제공되지 않았다. 이를 임의로 생성하거나 기존 baseline을 승인본으로 승격할 권한이 없다.
- 접근 방법: 제품·디자인 담당자가 14개 PNG와 source hash, viewport, fixture, crop, 승인자·승인 시각을 제공하면 `tests/design-snapshots/manifest.json`과 manifest-driven `design.spec.ts`를 추가하고, 기준선 변경은 승인 기록이 있을 때만 갱신한다. 그 뒤 laptop 1280x800·desktop 1440x900 두 폭(ADR-0047)과 접근성 게이트를 다시 실행한다. 2026-09-04 팔레트 전환으로 기준 이미지는 무드보드 v2로 만들어야 하며, 그 선행 조건은 [design/PLAN.md](../design/PLAN.md) §0-3·0-4다.

## 발주계획 추적 결정(결정 1)을 저장할 REST 계약이 없다

- 재현 조건: `web/backend/app/screening/routers/order_plans.py`의 경로 다섯 개를 확인한다. 목록·상세·screening-history·screening-feedback(GET/POST)뿐이다. `PATCH /opportunities/{id}/tracking-status`는 사업기회 식별자로만 부를 수 있고, `OrderPlanListItem`·`OrderPlanDetailResponse`(둘 다 `_Strict`)에는 `opportunity_id`도 추적 상태도 없다.
- 증상: [ADR-0046](../design/ADR.md) 결정 4가 추적 결정을 발주계획 화면의 결정 1로 채택했는데, 그 결정을 읽을 수도 쓸 수도 없다. `docs/design/PLAN.md` 단계 C 작업 5(추적 결정을 상세 pane 바닥의 결정 액션으로)와 완료 게이트 2("추적 결정과 사람 판단 수정이 서로 다른 요청으로 저장된다")를 서버 없이 만족시킬 수 없다.
- 영향: 단계 C의 화면은 만들 수 있으나 **결정이 서버에 남지 않는다.** 이 상태에서 결정을 화면 상태나 localStorage에 기록하면 담당자에게 저장된 것처럼 보이면서 실제로는 사라지므로, 그렇게 만들지 않는다.
- 상태: **차단** (2026-09-04). 화면 구현의 차단이 아니라 계약의 부재다.
- 지금 해결할 수 없는 이유: REST·DB 계약은 백엔드 파트의 소유이고, 화면 작업이 임의로 endpoint를 만들거나 기존 사업기회 계약의 의미를 바꿀 권한이 없다.
- 접근 방법: 요청안을 [`order-plan-tracking-contract-request.md`](../design/order-plan-tracking-contract-request.md)로 작성해 백엔드 파트에 보낸다. 조사 결과 **새 table은 필요하지 않을 가능성이 높다** — 소유 사업기회와 `stage='order_plan'` official 링크는 `ingest/loader.py`가 이미 만들고, 상태 4값과 append-only `AuditEvent`도 이미 있다. 없는 것은 응답에 그 상태를 싣는 것과 발주계획 식별자로 쓸 경로 둘이다. 계약이 확정될 때까지 화면은 요청안 §7의 규칙을 지킨다: adapter 한 곳으로 호출을 모으고, 실패를 성공으로 보이게 하지 않으며, 응답에 추적 상태가 없으면 `계약 미구현`으로 표시하고 `미선택`으로 바꾸지 않는다. 계약이 구현·검증되기 전에는 단계 C를 완료로 적지 않는다.

## 팔레트 전환 뒤 화면 단위 시각 회귀를 잡을 기준선이 없다 (해결)

- 재현 조건: `web/frontend`에서 `npx playwright test`를 실행한다. 2026-09-04 단계 A(무드보드 팔레트 적용, ADR-0048) 이후 기준이다.
- 증상: 단계 A 직후 `370 passed, 75 failed, 3 skipped`. 실패 75건 중 73건이 `visual.spec.ts`다. 팔레트가 모든 화면의 색을 바꿨으므로 옛 무채색 기준선과 다른 것이 정상이며, 실패 자체는 회귀의 증거가 아니다.
- 정정 (2026-09-04, 단계 B): 그 73건은 전부 스냅샷이 아니다. **팔레트 스냅샷 72건 + `/queue` 1280px 가로 오버플로 1건**이다. 오버플로 1건은 색과 무관한 레이아웃 실패이며(`.notice-attachments-panel`의 첨부 파일명이 19.77px 넘침), 단계 B의 변경 전후로 같은 값이 나오는 것을 확인했다. 단계 E가 `검토 대기열`을 이행할 때 함께 정리한다. 단계 B 이후 수치는 `382 passed, 74 failed, 2 skipped`이며 새 실패는 없다(74 = 위 73건 + `visual.spec.ts:257` flake 1건, 단독 실행 시 통과).
- 해소 (2026-09-04, 단계 E): `/queue` 오버플로 1건을 고쳤다. `.attachment-name`이 ellipsis로 자르고 있었지만 **자름은 부모의 시각 효과일 뿐 자식 `span`의 레이아웃 상자는 그대로 넘쳐 있었다.** 자식이 스스로 `max-width: 100%`와 ellipsis를 갖도록 고쳤고 `visual.spec.ts`의 가로 넘침 36건이 모두 통과한다. **남은 실패는 팔레트 스냅샷 72건뿐이며, 이 finding이 말하는 신호 손실은 그 72건에만 해당한다.**
- 영향: **그 73건이 실패로 남아 있는 동안 화면 단위 레이아웃 회귀를 자동으로 구분할 수 없다.** "색이 바뀌어서 실패"와 "레이아웃이 깨져서 실패"가 같은 실패로 보인다. 셸은 `tests/design-shell.spec.ts`의 구조 검사(테마 scope, computed 색 대 PRD §4.1, 248/76px 치수, 1280·1440·1920px 가로 오버플로 없음, legacy 토큰 회귀)로 지켜지지만 이 검사는 셸 범위이고 화면 내부 레이아웃은 보지 않는다.
- 상태: **해결** (2026-09-04). 당시 판단은 "시안을 다시 렌더해야 기준선을 만들 수 있다"였는데, 그것은 **시안 충실도 대조**의 조건이지 앱 자기 회귀 기준선의 조건이 아니었다. 둘을 한 덩어리로 묶어 둔 탓에 픽셀 72건이 계속 빨간 채로 남아 있었다.
- **해결 (2026-09-04, 화면 검사 층 분리).** 원인은 팔레트가 아니라 **한 파일이 세 가지 일을 하고 있었던 것**이다. `visual.spec.ts` 87개가 픽셀 36 + 가로 넘침 36 + 의미 15로 섞여 있어, 픽셀이 깨지면 나머지 51개의 초록이 같은 실행 결과에 묻혔다. 그래서 "실패하지만 정상"이라는 단서를 문서 다섯 군데에 적어야 했다.
- 조치: 파일을 세 층으로 갈랐다 — `screen-semantics.spec.ts`(의미, 한 폭) · `overflow.spec.ts`(구조, 두 폭) · `pixel-screens.spec.ts`(픽셀, 게이트 밖). 공유 fixture는 `screen-fixtures.ts`로 뺐다. 게이트는 앞의 두 층(`npm run test:screens`)이고 픽셀은 `npm run test:pixel`로만 돈다.
- **기준선 교체 승인 기록.** 사유: 팔레트 전환(ADR-0048)으로 옛 무채색 기준선이 전부 무효가 됐고, 앞으로 화면을 고칠 계획이라 회귀 기준선이 필요하다. 영향 화면: 아래 여덟 장으로 줄였다 — `dashboard`·`criteria`·`order-plans-list`·`order-plan-detail`·`pre-specs-list`·`opportunities-list`·`deep-review-complete`·`bid-delta-changed`. 통짜 36장은 화면을 건드릴 때마다 기준선 커밋을 끌고 오면서 실제로 잡아 주는 것은 골격 여덟 가지가 거의 다였다. 나머지 화면은 구조·의미 층이 본다. 승인: 저장소 소유자의 명시 지시(2026-09-04). 옛 기준선 144장(39MB)은 지우고 새 여덟 장(1.1MB)을 만들었다.
- **남은 한계.** 이 기준선은 **앱이 자기 화면을 찍은 회귀 기준선이며 승인된 시안이 아니다.** 시안 충실도 대조는 여전히 열려 있고 그 선행 조건은 [design/PLAN.md](../design/PLAN.md) §0-3·0-4다 — 위의 "B-F 설계 승인 baseline과 manifest가 없어 전체 설계 게이트를 완료할 수 없다"가 그 항목이다. 또한 발주계획 추적 결정 계약이 없어 화면이 `계약 미구현`을 띄우는 상태가 기준 이미지에 그대로 들어 있다. 회귀 감지에는 문제없지만 **"이 화면이 옳다"는 승인으로 읽지 않는다.**
- 곁들여 고친 것: 마감·감사 경로 검사가 전체 실행에서만 깨지던 flake. 이동 후 주소 확인 여유가 기본 5초여서 400여 개가 동시에 붙으면 못 들어왔다. 단독 실행 6회는 통과했다. 여유를 15초로 늘렸다.

## 사업기회 추적 이력을 읽을 계약이 없고 구역별 집계도 서버가 세지 않는다

- 재현 조건: `web/backend/app/lifecycle/routers/opportunities.py`의 경로 넷을 확인한다. 목록(`GET ""`)·상세(`GET /{id}`)·후보 연결 판정(`PATCH /links/{id}/decision`)·추적 상태 변경(`PATCH /{id}/tracking-status`)뿐이다. 목록 query는 `tracking_status`·`first_registered_stage`·`sort`·`limit`·`offset`이다.
- 증상 1 — **추적 이력이 최근 한 건뿐이다.** `opportunity_tracking`은 상태 변경마다 append-only `AuditEvent`(`opportunity.tracking_status.changed`)를 남기지만 그것을 읽는 endpoint가 없다. 화면이 받는 것은 `OpportunityStateView`의 `tracking_status`·`tracking_reason`·`tracking_selected_by`·`tracking_selected_at` 넷, 즉 **마지막 한 건**이다. [ADR-0046](../design/ADR.md) 결정 2가 요구한 사업 추적 상세의 `추적 이력` 탭이 이전 결정을 보여줄 수 없다.
- 증상 2 — **구역별 집계와 필터가 없다.** ADR-0046 결정 2의 구역 `조치 필요`는 저장된 상태가 아니라 "미선택이거나, 재검토 신호나 예외 작업이 남았다"는 파생 조건이다. 서버에 `recheck_signal` 필터도 후보 연결 대기 필터도 집계 응답도 없어, 화면이 한 페이지를 받아 직접 나눈다.
- 영향: (1) `추적 이력` 탭은 최근 한 건만 보여주고, 그것이 이전 결정이 없다는 뜻이 아님을 화면이 직접 밝힌다(`.opportunity-contract-gap`). 이전 revision을 화면이 지어내지 않는다. (2) `조치 필요` 구역의 건수는 **받은 페이지 안에서 센 값**이며, 목록 머리말이 그 사실과 남은 건수를 함께 적는다. 전체 총계로 읽으면 과소 계상된다.
- 상태: **수용됨** (2026-09-04, 단계 E). 화면 구현의 차단이 아니라 계약의 부재이며, 두 한계 모두 화면이 숨기지 않고 표시한다.
- 지금 해결할 수 없는 이유: REST·DB 계약은 백엔드 파트의 소유이고, 화면 작업이 감사 기록 읽기 경로를 새로 만들거나 목록 계약의 의미를 바꿀 권한이 없다.
- 접근 방법: (1) `GET /api/opportunities/{id}/tracking-decisions`를 추가해 append-only 이력을 `revision`·`tracking_status`·`reason`·`selected_by`·`selected_at`·`audit_event_id`로 연다. 발주계획 쪽 같은 요청([`order-plan-tracking-contract-request.md`](../design/order-plan-tracking-contract-request.md) §2.1)과 같은 wire shape를 쓰면 화면이 `ReviewRevisionHistory` 하나로 둘을 그린다. (2) 목록에 `recheck_signal`·`has_pending_candidate_link` 필터와 구역별 `section_counts` 집계를 추가하고 `docs/contracts.md`의 `OpportunityList` 항목에 등록한다. 그 전까지 화면은 저장된 추적 상태로 서버를 거르고(`추적 중`·`보류`·`추적 종료`) `조치 필요`만 받은 페이지에서 나눈다.
