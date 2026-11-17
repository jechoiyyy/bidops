# 첨부·변환·문서 준비 문제 기록

[전체 색인](../findings.md). 미해결 또는 일부 조치 뒤 검증이 남은 항목이다. 제목의 날짜는 마지막 관측·기록 시점이며 2026-10-21에 다시 재현했다는 뜻이 아니다. 과거 기능명·정책·환경을 현재에 적용하기 전에 소스와 마지막 실행 증거를 확인한다.

## HP 평가 후보116 HWP의 native 검증 실패 (2026-10-15, 미해결)

- 재현: bidops-local 사전규격116 첨부169, 원문 SHA `827843bd9edb6ba7c5784f63104238d21a70cc03cda9474c14c68aecdc84f5f4`,4,265,984bytes. ClamAV clean 뒤 local document-worker-1의 `process_document(..., options={prepare_pdf:true,timeout_seconds:120})`가 `DocumentProcessingError/hwpx_verify_failed`로 종료한다. 진단도 같은 코드다.
- 영향: 국가슈퍼컴퓨팅센터 후보의 카드·쪽·사람 작성자료를 발행할 수 없다. 원문·scan SHA·진단은 Git 밖 `.sdlc/local-runtime/hp-evaluation-20261015/`에 보존했다.
- 현재 범위는 평가자료 준비여서 converter/vendor 수정과 원문 손실 원인 규명은 별도 작업이다. verify 게이트를 우회하지 않는다. 후속은 이 고정 원본으로 native HWP→HWPX 검증 차이를 좁혀 원문 보존을 확인하거나 사용자가 정상 변환된 대체 후보를 선택하는 것이다. 교체 후보 준비는 최종 표본 승인으로 처리하지 않는다.


## Rosetta 변환 실패로 `차단`된 사전규격 첨부를 다시 취득할 경로가 없다 (2026-10-15, 미해결)

- 재현: 2026-10-15 Mac 운영 스택이 amd64 문서 worker로 돌던 약 5분 동안 HWP·HWPX 첨부 14건이
  `conversion_required`로 `attachment_fetch.status='차단'`이 됐다(공고 id 30·33·38·93·96·98·99·
  102·104·105·111·117·122·124). 원인은 Rosetta와 자식 `RLIMIT_DATA`의 충돌이었고
  (engineering-notes), arm64 문서 worker로 바꾼 뒤에는 새 `차단`이 없다.
- 영향: `차단`은 종결 상태라 `refresh_fetch_eligibility`가 되살리지 않는다. 이 공고들은 묶음이
  `bundle_has_blocking_issues`로 남아 개요가 만들어지지 않는다. 같은 일이 실제 손상 문서가
  아니라 일시 환경 장애로도 일어난다는 것이 드러났다.
- 지금 해결하지 않는 이유: 첨부 취득 실패·묶음 failed 재시작 화면은 구현 전이고, 운영 DB 행을
  SQL로 고치지 않는다. 화면에서 사람이 원문을 업로드해 묶음을 다시 만드는 경로는 있다.
- 후속 방향: 감사가 남는 CLI/REST로 `차단` 행을 새 취득 시도로 다시 여는 기능(오류 코드가
  환경성인 `conversion_required`·`converter_unavailable`에 한정)을 만든다.

## 요구사항 표의 행별 셀 위치 차이로 심층검토가 호출 전에 실패한다 (2026-09-22, 미해결)

- 대상: 사전규격 1443, 심층검토 `bf17c9d9-f92b-49a1-8bc1-d4d1293c2a90`.
  첫 실행 `764e7dc5-962b-4bdc-8411-0b0b69a1a1f1`과 재실행
  `74c69327-d15a-424b-ac81-9b8dc1e37a1a`은 각각 05:34:40Z/05:35:14Z 시작 후
  약 0.7초 만에 failed. 모두 stage 시작 시각은 null이고 work_job 오류는 `validation_failed`다.
- 읽기 전용 재현: 운영 worker의 고정 bundle/profile/context 로드는 성공한다. source unit은
  70개이며 inventory 식별자 19개, 입력 본문에서 읽은 식별자 48개로 차이가 난다.
  빠진 expected ID는 0개, 추가 ID는 29개다. 이는 실제 요구사항 수가 48개라는 품질 판정이
  아니라 두 추출 경로의 집합 차이다. 해당 조건은 `source_requirement_inventory_mismatch`를
  발생시키며 Qwen 호출보다 앞에 있다. 재현 중 모델 호출·DB 변경은 하지 않았다.
- 원인: `document_segments._table_columns`는 `table-1-12`의 ID 열을 column=1로 정하고,
  `_collect_candidates`는 그 열만 읽는다. 같은 구조의 `SER-1`은 r1-c1에 있지만 `SER-2`는
  r2-c0에 있다. 추가 29개는 모두 table_cell에 있고 이 표의 column=0에서 독립 ID로 확인된다.
  고정 열번호에 의존한 inventory는 일부를 놓치고, 전체 본문을 읽는 심층 입력은 이들을 찾는다.
  원본의 셀 병합 정보는 현재 block attributes에 없으므로 병합 구조 자체의 원인 판정은 별도다.
- 오류 표시 결함: 이 실패는 stage_row가 정해지기 전 발생한다. `_fail_claim`이 stage 없는
  세부 진단을 보존하지 않고 `_attempt_view`도 stage 오류만 읽어 API의 last_error_code는 null,
  모든 단계는 queued로 보인다. 실제 job 실패 원인을 화면에서 알 수 없다.
- 현재 범위와 후속: 이번 요청은 실패 원인 조사다. 표의 논리적 열/행과 요구사항 추출 기준을
  맞추고 새 불변 manifest/묶음 경로를 검증해야 한다. 단순 집합 불일치를 모델 오류로 취급하지
  않도록 입력 품질의 불확실성 처리도 검토한다. stage 전 실패 진단의 보존·조회도 보완 대상이다.
  원문 인용·숫자 대조 스위치는 이 검사를 끄지 않으며 같은 입력의 재시도로 해결되지 않는다.
- 재현 추가(2026-10-11, 데모 브랜치 `bidops-local`): 사전규격 179(HWPX 1개, blocks 4141)에서 DEMO-03 회사
  심층 미리보기가 같은 조건으로 호출 전 `company_input_invalid`(409)로 끝났다. 분할 단위 47개, inventory
  `expected_ids` 11개(prefix 11개) vs 본문 관측 ID 50개(빠진 expected 0, 추가 39). 회사 경로는 legacy와 같은
  엄격 일치를 유지하므로 이 결함이 해결될 때까지 요구사항 표가 있는 실제 공고는 어느 경로로도 심층에 들어가지
  않는다. DEMO-05 대표 공고 선정은 모델 호출 전에 inventory 일치를 먼저 검사한다
  (`docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md`).

## 판정 입력에 참여 판단용 날짜·비율 항목이 없고 늘리려면 검증기 여섯 곳을 함께 열어야 한다 (2026-09-21, 미해결)

- 재현 조건: 실무자가 참여 여부를 정할 때 보는 자격등록 마감, 공동수급협정 마감, 설명회 일시, 입찰 개시,
  낙찰하한율, 사전규격 납품기한은 어느 화면·어느 API에도 없다. 수집기 정규화 결과에 그 항목이 없기 때문이며
  화면·투영만으로는 채울 수 없다.
- 영향: 항목 하나를 더하려면 판정 입력 계약의 **닫힌 검증기 전체**를 한 변경으로 열어야 한다 — 수집기
  (`skills/bidops-collect/scripts/collect_notices.py`) → `web/backend/app/lifecycle/ingest/contracts.py` →
  `loader.py:669-725`(null 생략 선택 키 집합, 옛 회차의 digest 보존) →
  `web/backend/app/screening/orchestrator.py:1278,1341`(선택 lifecycle 키와 `opening_at` aware 검사) →
  `skills/bidops-screen/scripts/build_screening_results.py:583`(선택 projection 목록) →
  `loader.py:2934-2946,3052-3082`(`_SCREENING_*_KEYS` 허용 키 집합). 한 곳만 열면 기존 회차 적재가 깨지거나 새
  필드가 조용히 버려진다. 과거 회차는 소급하지 않으므로 채워지지 않는 칸이 반드시 생긴다.
- 지금 해결하지 않은 이유: 2026-09-21 사용자 결정 7(`docs/0921_practitioner-screens/intent.md` §3·§4)로 실무
  화면 고도화 범위 밖으로 분리했다. **미수집 / 원문 빈 값 / 해석 실패 / 정상**의 4상태 계약을 먼저 설계해야
  한다. 그 계약 없이 필드만 더하면 빈 값이 "그런 조건이 없음"으로 읽혀
  [ADR-0066](../decisions/0066-practitioner-ops-information-boundary.md) 결정 4(뜻이 다른 빈 값을 합치지 않는다)를
  바로 깬다.
- 후속: 4상태 계약 확정 → 위 여섯 지점을 한 변경으로 확장(`schema_version` 올림과 이전 소비자 처리 포함) →
  과거 회차는 `미수집`으로 표시 → `docs/contracts.md`에 등록. 착수 시점은 사람이 정한다.

## host 측정이 정상 PDF를 손상 문서로 판정한다

- 재현 조건: poppler가 없는 host에서 `app.document_mcp.processor.DocumentProcessor.process()`에 정상 PDF를 넣는다. 실측은 [`20260831-prespec-rfp-structure.md`](../../validation-runs/20260831-prespec-rfp-structure.md)에 있다.
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

## 문서 준비와 실패 심층 검토 재시작을 화면에서 완료할 수 없다

- 재현 조건: ready document bundle이 없는 공고를 브라우저에서 열거나 deep-review attempt가 실패한 상태를 연다.
- 증상: 조회와 ready bundle 이후 심층 검토 화면은 있지만 bundle 생성·문서 upload·metadata 수정·확정, 실패 attempt의 새 attempt 생성 action이 없다.
- 영향: 담당자는 curl 또는 CLI를 사용해야 하므로 목표 업무 흐름이 화면에서 끊기고, actor·idempotency·상태 fence를 잘못 다룰 가능성이 커진다.
- 지금 해결할 수 없는 이유: backend 계약은 준비됐지만 frontend Phase 3 구현과 browser 회귀 검증이 별도 코드 작업으로 남아 있다.
- 접근 방법: typed Lean API client, document preparation panel, terminal failure 전용 retry, polling, 403/503 상태 표현을 구현하고 fake API browser 흐름과 좁은 viewport를 검증한다.
- 종결(2026-09-16): 코드에 구현됨(DocumentPreparationPanel 연결). 첨부 취득 실패 재시작만 미구현으로 남는다.

## 이 변경 전에 만들어진 문서 구조에는 segment manifest가 없다

- 확인: 2026-09-05
- 재현 조건: `0018` 이전에 저장된 `DocumentStructure`의 ID로
  `GET /api/document-structures/{structure_id}/segments`를 호출한다.
- 증상: 404 `not_found`다. manifest는 **구조 저장 시점의 메모리 payload로만** 만들어지고
  저장된 `document_block`에는 ordinal이 없어 경계를 사후에 되짚을 수 없다.
- 영향: 옛 문서로 만든 심층 검토는 문서 inventory 패널이 비고, `requirement_inventory`
  check도 그 문서에 대해서는 근거가 없다. 그 사실이 조용히 "요구사항 누락 없음"으로 읽히면
  안 되므로 화면과 검증이 각각 없음을 밝힌다.
- 지금 해결할 수 없는 이유: 사후 재구성이 **불가능**하다. `document_block`에 ordinal을 더하는
  것은 저장된 구조의 의미를 바꾸는 일이고, 기존 행에 넣을 값이 없다.
- 접근 방법: 그 문서를 다시 올려 새 `DocumentVersion`·`DocumentStructure`를 만든다. 옛
  구조를 고치지 않는다. 대량 재처리가 필요하면 별도 결정으로 다룬다.

## 개요 제목 인식이 공백·번호·표 구조를 놓치고 목차를 본문으로 선택한다

- 확인: 2026-09-07, 미해결. 실제 64건 중 제목 경계 미확정 29건, 완료 공고 52에서 목차 10블록 입력을 확인했다.
- 재현: `_normalise_heading_text("1. 사업 개요")`는 `사업 개요`를 반환하지만 닫힌 어휘는 `사업개요`다. 마침표 없는 로마숫자는 남고 paragraph 대체 인식은 표 셀과 절 계층을 보존하지 않는다.
- 영향: 본문이 있어도 검토 대기하거나 다른 절·목차가 개요 입력으로 확정된다. locator 검증 통과를 본문 선택·사실 정확성 검증으로 사용할 수 없다.
- 현재 범위와 미해결 이유: 원인 조사 및 파싱 비교 실험이며 운영 파서·불변 snapshot을 수정하지 않았다. 어휘만 늘리는 수정으로는 목차와 계층 오류가 남는다.
- 후속: 동일 원문의 결정적 파서·Qwen·직접 검토를 비교하고 제목 정규화·목차 배제·표 제목·절 계층을 함께 검증한다. 기존 결과는 보존하고 수정 후 새 버전으로 재분석한다.
- 증거: [미완료 52건 분석](../../validation-runs/20260907-prespec-failure-analysis.md).
- 추가 재현(2026-09-08): `R26BD00271191`(notice 142)의 완료 attempt
  `992b2824-3573-4c2f-8c8a-29b02f95cc6b`는 감리용역 자체가 아닌 감리대상 사업의
  개요를 발췌했다. 구조 `22541eb7-4e1b-4a0a-9ec4-e0d329dbc774`의 상위 절
  `paragraph-1-71`이 입력에서 빠지고 `paragraph-1-72`부터 `paragraph-1-74` 직전까지만
  선택됐다. 빈 블록 제외 3개로 재구성한 prompt SHA-256은 실행 preflight와 일치했다.
  인용문·요약의 정확 일치 검사를 통과해도 금액·기간이 어느 사업에 속하는지 보장하지
  못한다. 요청 범위는 저장 데이터·생성 경로 조회여서 기존 snapshot·완료 결과는
  보존했다. 후속 검증에는 상위 절 맥락과 발주 대상/감리 대상 구분을 포함해야 한다.

## HWP/HWPX 구조의 page 값은 실제 PDF 페이지가 아니다

- 확인: 2026-09-07, 사전규격 개요 실패 6건의 직접 검토 및 PDF 페이지 참조 실행.
- 재현: `document_mcp/hwpx.py::extract_hwpx`는 `section_names`의 순번을 `page_number`로 넣는다. HWP도 `processor.py`에서 HWPX로 변환한 뒤 같은 추출기를 사용한다. 여러 실제 페이지를 가진 단일 구역 문서가 page=1인 블록들로 저장된다.
- 영향: 이 값을 PDF 실제 쪽수로 표시하면 잘못된 근거 위치를 안내한다. 이번 ID 137의 구조화 개요에서는 예산·기간 문구가 빈 기호로 추출됐지만, 같은 원본의 참조 변환 PDF 4페이지에서는 두 값이 확인됐다. 따라서 입력 범위 수정과 텍스트 추출 품질 검토도 함께 필요하다.
- 현재 조치: 기존 불변 구조·개요 결과는 변경하지 않았다. 별도 참조 실행은 HWP/HWPX 원본 해시, 변환 PDF 해시, 물리적 PDF 페이지(표지 포함 1부터), 선택 페이지 텍스트 해시를 결속한다. 모델 출력에는 각 사실의 PDF 페이지와 인용문을 직접 연결한다. 기존 page를 PDF 페이지로 승격시키지 않는다.
- 남은 작업: 운영 문서 구조 계약에 페이지 기준(실제 PDF/구역 등)과 변환본 버전을 명시하고, 변환 PDF의 저장·검증·조회 및 청크별 페이지 범위를 동일한 불변 입력에 결속해야 한다. PDF 변환 품질과 본문 추출 누락도 검증해야 한다. 기존 구조 전체를 재해석하거나 덮어쓰는 방식으로 해결할 수 없어 이번 참조 실행에서 운영 구조 migration은 하지 않았다.
- 증거: `experiments/prespec-overview-pdf-reference/README.md`, 이번 실행의 비공개 source/PDF/input manifest. 참조 PDF는 고정된 rhwp SVG와 Chromium으로 생성했으며 한컴 렌더링과 동일한 페이지 배치를 보증하지 않는다.

## [해결됨] 필수 RFP의 rhwp SVG PDF가 표 안의 원문을 보존하지 못한다 (2026-09-08)

- 확인: root 독립 worker 조건 검증에서 실제 RFP HWPX
  `/tmp/bidops-v4-required-sample.h0vd7q/source.hwpx`를 변환했다. 원본은
  `840114` bytes, SHA-256은
  `7cc3b5f3894d984ce641e9462030990cbb4cfc1d6869b18bc9047899a23f4665`이며, 생성 PDF는
  `10113018` bytes, 85 physical pages, object marker `70080`, SHA-256은
  `ca77c04344886ca6e4cf57a3b2deed1955fc469d0e36aa5155c51cd88947b4f6`였다.
- 재현: 생성 PDF p5 `3. 감리대상 사업 > □ 사업개요`의 파란 상자가 시각적으로
  완전히 비어 있다. 원본 HWPX XML과 `renderPageHtml`/`getPageTextLayout`에는
  사업명, 사업비 `13,225,835,150원 VAT포함`, 착수일부터 12개월이 존재한다.
  `renderPageHtml`은 중첩 absolute 좌표 때문에 그대로 인쇄할 수 없고, 같은 vendored
  WASM의 실제 canvas 경로에서는 해당 내용이 표시되는 별도 비교 결과가 있다.
- 영향: 위 수치는 구형 SVG adapter의 historical 결과이며 현재 경로의 성공 근거로
  사용하지 않는다. 원문 XML을 PDF 위에 덧붙이거나 숫자·문장을 추정 보정하지 않았다.
- 해결: `rhwp_render_pages.mjs`를 제거하고 같은 vendored WASM의
  `renderPageToCanvas`와 `getPageTextLayout().runs`를 기존 Chromium print HTML에
  연결했다. 실표본을 같은 non-root/network-none 조건에서 다시 실행해 85 physical
  pages, p4 `298,735,350원`·`365일`·`189MD`, p5
  `13,225,835,150원`·`12개월`, p7~8의 감리 절 구분을 text와 p4/p5 PNG로
  확인했다. Canvas PDF는 SHA-256
  `77fa66fca472a89f2b6a1608602eb6afb0be802068e62998dfec007f539f0010`, 전체
  extracted text SHA-256은
  `e58ab1e90fd216005d283417e11991eab177300e2f0f4ed3afbdd0dc837328ef`다.
- 남은 범위: v2 scratch sidecar는 통과했지만 실표본 PDF의 DB/MinIO immutable
  snapshot과 v4 runner/model/UI 연결은 아직 수행하지 않는다. dependency upgrade,
  OCR/XML 보정, 범용 renderer framework는 추가하지 않았다.

## [원인 확인] notice 142 표준 PDF 준비가 300초 deadline에서 종료됨 (2026-09-09)

- 재현: `R26BD00271191` 필수 HWPX를 명시 표본 표준 prepare로 실행했다. 첫 시도는
  `conversion_required`, 두 번째 시도는 `pdf_preparation_failed`였고, 마지막 2GiB
  worker 시도도 job `9a8ded11-f357-4847-a534-65be6a0810f8`, attempt
  `954abd8b-e161-457a-9236-464fb47604ba`, `300048ms` timeout으로 실패했다.
- 영향: notice 142에는 성공 PDF, immutable snapshot, current result를 저장하지
  않았으며 실제 PDF/UI 인수는 미검증이다. 이미 완료된 35 개발 HWP와 59 운영 PDF
  current 결과에는 영향을 주지 않는다.
- 조치: 원인으로 입증되지 않은 Chromium `RLIMIT_FSIZE=256MiB` 임시 변경은
  원복했다. 2GiB 조건에서도 timeout이 발생했으므로 fsize를 해결책으로 확정하지
  않는다. 추가 변환 진단·대체 테스트·모델 호출은 수행하지 않았다.
- 후속: worker 원래 runtime 조건으로 복원하고, 별도 승인된 환경 원인 조사 후에만
  재시도한다. 실패 attempt는 보존하며 자동 성공·기존 snapshot 재사용으로 우회하지
  않는다.

- 원인 확인(2026-09-09): 운영 worker image `bidops-v4-luna-reference:20260909-final`에서 같은
  source bytes로 격리 재실행해 두 한계를 분리했다. (1) compose `pids_limit: 128`이 Chromium 렌더
  thread를 굶겨(`pthread_create: Resource temporarily unavailable (11)`, pids 123/128, 렌더러 CPU
  1~5% 유휴) deadline까지 진행하지 못했다. (2) v4 CLI 기본 출력 예산 20 MiB(Chromium
  `RLIMIT_FSIZE`는 그 4배인 80 MiB)가 85쪽 렌더에 부족해 PDF 없이 `conversion_required`로 끝났다.
  memory 2 GiB와 `RLIMIT_FSIZE=256 MiB` 가설은 원인이 아니다.

  | pids_limit | max_output_bytes | 결과 |
  |---|---|---|
  | 128 (당시 compose) | 100 MiB | 300초 timeout, Chromium `pthread_create` 실패 |
  | 128 | 20 MiB (당시 CLI 기본값) | 21초 `conversion_required` (PDF 미생성) |
  | 512 | 20 MiB | 18초 `conversion_required` |
  | 512 | 32 / 48 / 100 MiB | 성공 16.8~20.8초, 85쪽, 11,041,060 bytes |

  ```bash
  docker run --network none --user 1000:1000 --memory 1g --cap-drop=ALL \
    --security-opt no-new-privileges --pids-limit <128|512> \
    bidops-v4-luna-reference:20260909-final python -c \
    'DocumentProcessor(clamav_checker=lambda _: True).process(bytes, "application/hwp+zip", opts)'
  ```
- 조치(2026-09-09): compose document-worker `pids_limit`을 512로, v4 CLI 기본 `max_output_bytes`를
  64 MiB(`ProcessorOptions` 상한 100 MiB 이내)로 올렸다. **운영 재실행은 하지 않았다** — 컨테이너
  재생성과 notice 142 새 attempt는 별도 운영 단계이며 그 전까지 142는 `unverified`로 남는다.
- 운영 재실행(2026-09-10): `212e5ed`가 main에 들어온 뒤 document-worker 두 개를 base compose와 image 고정
  overlay(`bidops-v4-luna-reference:20260909-final`)로 재생성해 `PidsLimit=512`·memory 1 GiB·`network_mode none`·
  `cap_drop ALL`·동일 image·`/scratch` volume을 확인했다. overview endpoint `192.168.0.139:58765`가 닿지 않아
  `--activate`는 `model_binding_unavailable`로 실패했고, 2026-09-08 감사의 Luna reference-only
  binding(`692b50e4…`, `gpt-5.6-luna`, `reference_only=true`, `deployable=false`)을 `--binding`으로 재구성해
  `explicit_sample`로 활성화했다. 첫 `--prepare`는 43초 뒤 attempt `dbbc7b5f-35c5-4f21-8adb-1c2b042dd61e`(sequence 5)
  `pdf_preparation_failed`였고 3분 뒤 같은 입력의 직접 재현이 22.8초에 성공했으므로 원인은 **미확정**이다. 두 번째 실행은
  23.1초에 snapshot `e68670e0-4bf7-4cd9-baa1-174f19e5e994`(85쪽, 11,041,060 bytes, PDF SHA-256 `2774fd76…`,
  `verified`·ClamAV `clean`)와 target `200e9557-d5d5-4a0f-afa8-896d44b41261`(`ready`, `heading_scope`, 3~13쪽)을
  남겼다. attempt는 enqueue하지 않았고 activation은 즉시 OFF로 되돌렸다(감사 `31bee035-6263-4444-bafe-439b0f16c12a`).
  첫 시도 중 append된 감사 `176c61bb-2538-459c-a1f3-ec208debed57`의 사유
  `notice_142_prepare_done_activation_restored_off`는 그 시점에 준비된 것이 없어 사실과 다르지만, 감사 행은
  append-only이므로 고치지 않고 부정확함만 기록한다. 새 target에 attempt가 없어 `current`는 여전히 실패 attempt
  `dbbc7b5f…`를 보여 주고 142의 UI/PDF 링크 인수는 Qwen endpoint 복구까지 미완이다.
- R6 운영 인수(2026-09-10): native 이미지 `bidops-rdp-r6:20260910`과 0023 migration 뒤 같은 source bytes로 native snapshot
  `f8a42b74-8710-4cc8-90f0-9ca8ae4ed3f1`(`rhwp-svg-pdf` 0.8.6, 79쪽, PDF SHA-256 `aee7e648…` 4,829,134 bytes, 기존 구조
  `22541eb7…` 결속, 대응표 `38958774…`)과 target `f7c73503-8f70-47d4-a309-c9fbd9cfd122`(`ready`, 4~12쪽)를 31초에 준비했다.
  Canvas snapshot `e68670e0…`·target `200e9557…`은 보존됐고 attempt는 없다. `GET /api/document-structures/22541eb7…/pdf`가
  이 PDF를 돌려주고 segments 77건이 `mapped` 35·`partial` 42다. `current`는 여전히 `dbbc7b5f…`이며 아래 projection 항목은 열려 있다
  ([R6 기록](../../validation-runs/2026-09-10-rhwp-pipeline.md)).
- 사실 정정(2026-09-11): 위 "조치(2026-09-09)"가 기록한 `pids_limit: 512`는 R6 이후 이미지
  재생성(`bidops-rdp-r6:20260910` 이후)에서 `fc-list` 추가와 함께 **128로 되돌아갔다** — R6·R7·
  현재 운영 document-worker는 모두 `PidsLimit=128`이다(R6/R7 기록, 2026-09-10). 512로 올린
  기록은 2026-09-09~10 사이의 중간 상태일 뿐 현재 사실이 아니므로, 운영 pids 값을 확인할
  때는 이 항목이 아니라 `docker inspect <container> --format '{{.HostConfig.PidsLimit}}'`
  실측을 정본으로 한다.

## pdf_preparation_failed가 변환기의 실제 오류 코드를 감춘다 (2026-09-10)

- 재현: `prespec-v4 --prepare`로 변환을 실패시키면 `prepare_v4_pdf_snapshot`이 converter 예외를 종류와 무관하게
  `pdf_preparation_failed` 하나로 감싼다(`web/backend/app/deep_review/services/prespec_v4.py:855`).
- 영향: 2026-09-10 notice 142의 43초 실패 attempt `dbbc7b5f-35c5-4f21-8adb-1c2b042dd61e`에는 그 일반 코드만 남아
  deadline·출력 예산·렌더 실패를 구분할 수 없었고, 3분 뒤 같은 입력의 직접 재현이 성공해 원인은 미확정으로 남았다.
- 해결 구현(R3, 운영 미적용): converter의 허용된 안전 코드를
  `pdf_preparation_failed:<code>`와 감사 `safe_metadata.converter_code`에 함께 보존한다.
  미등록 예외는 일반 코드로 남기며 경로·원문·프롬프트·stderr는 넣지 않는다.
  [R3 검증](../../validation-runs/2026-09-10-rhwp-r3-snapshot.md)을 참고한다.
  과거 실패 attempt는 그대로 보존하고 당시 원인도 미확정으로 유지한다.
- `current` projection은 attempt가 없는 `ready` target을 드러내지 않는다. 142의 새 target
  `200e9557-d5d5-4a0f-afa8-896d44b41261`이 `ready`여도 `GET /api/pre-specs/142/overview-pages`의 `current`는 직전
  실패 attempt를 계속 보여 준다.


## 같은 문서 버전의 native 구조가 기존 구조와 다르면 준비를 거부한다 (2026-09-10)

- 재현 조건: `document_structure`가 이미 있는 문서 버전을 다른 native renderer
  identity로 준비하면서 새 구조의 pages 또는 blocks가 기존 payload와 다르다.
  R3의 합성 충돌 테스트로 확인했으며 운영 표본에서 발생했다고 단정하지 않는다.
- 영향: `structure_binding_mismatch`로 준비를 실패시키고 기존 구조·리뷰를 보존한다.
  원본이 같다는 이유만으로 서로 다른 블록에 기존 structure ID를 붙이지 않는다.
- 현재 범위에서 구조를 추가할 수 없는 이유: `document_structure.document_version_id`
  UNIQUE와 기존 소비자의 단일 구조 조회 계약이 있다. R3에서 이 계약을 없애거나
  재렌더링만으로 업무 문서 버전을 새로 만들지 않는다.
- 후속: 운영 인수 전에 기존 구조와 비교한다. 충돌이 있는 문서를 지원하려면
  구조 revision과 리뷰의 명시적 구조 참조를 함께 설계·승인한 뒤 이관한다.
- 운영 확인(2026-09-10 R6): 세 표본의 기존 구조 payload와 R6 이미지 native 출력을 대조했다. 142(`hwpx-stdlib`, 1쪽·2,561 blocks)와
  59(`pdf-poppler-fallback`, 84·84)는 pages·blocks가 동일해 준비가 기존 구조에 결속됐다. **35는 다르다** — 기존 `hwp-rhwp-hwpx`
  구조(WASM rhwp export, 1,349 blocks)와 native rhwp 0.8.6 export 구조(1,454 blocks)가 64개 구간에서 갈린다. 실행하면
  `structure_binding_mismatch` 실패 attempt가 append돼 35의 `current`(completed Luna reference)를 덮으므로 R6에서 35는 준비하지
  않았다. 35의 native snapshot은 구조 revision 설계·승인 뒤에만 만든다.

## 개요 범위 보조 호출에 temperature 0을 줄 수 없다 (2026-09-10)

- 재현: `app/core/model_client.py`의 `complete_structured`는 승인 generation 상수 `APPROVED_GENERATION["temperature"]=0.7`을 고정 전송하고 per-call 인자가 없다. R7 `--assist-range`는 결정적 제안을 위해 temperature 0을 계약했지만 넣을 자리가 없어 재시도 0·seed 0·strict json_schema로 대신했다.
- 영향: 같은 후보 목록에 대한 모델 제안이 호출마다 달라질 수 있다. 제안은 사람이 확인하는 참조일 뿐 target을 바꾸지 않으므로 업무 영향은 없다.
- 현재 범위에서 해결할 수 없는 이유: 승인 generation 값은 용도별 품질 게이트와 묶여 있어 R7 범위에서 core 계약을 바꾸지 않았다.
- 후속: `complete_structured`에 용도별 per-call generation override(허용 목록 안에서만)를 두거나 range-assist 용도의 승인 generation을 별도로 선언한다.
- 종결(2026-09-11): `--assist-range` CLI와 그 대상인 `prespec_v4_target`은
  [ADR-0054](../decisions/0054-prespec-overview-mvp-rewrite.md)로 삭제됐다. 새 계약에는 모델
  보조 range 제안 CLI가 없으므로 이 문제는 해당 스택 폐기로 종결됐다.

## 실표본에서 사람 확정 흐름을 재현할 문서가 없다 (2026-09-10)

- 상황: 35/59/142 모두 heading 선택기가 `ready`라 `needs_human_review` target이 만들어지지 않는다. R7의 확정 REST·화면·CLI 보조는 API 종단 테스트(`test_page_overview`·`test_prespec_v4_ops`)와 Playwright 목 검사로만 확인했다.
- 후속: 다음 수집 회차에서 heading 선택기가 미결정인 사전규격이 나오면 `docs/validation-runs/2026-09-10-rhwp-r7-range-review.md`의 절차로 운영 확인하고 결과를 이 항목에 덧붙인다.
- 종결(2026-09-11): 확정 REST는 `POST /api/pre-specs/{notice_id}/overview/range-confirmations`로,
  대상 테이블은 `prespec_overview_run`으로 바뀌었다([ADR-0054](../decisions/0054-prespec-overview-mvp-rewrite.md)).
  옛 target 기반 확정 흐름과 그 테스트(`test_prespec_v4_ops`)는 함께 삭제됐으므로 이 항목은
  해당 스택 폐기로 종결하고, 실표본 사람 확정 재현은 새 endpoint 기준으로 별도 후속을
  연다.

## 0910의 수동 범위·대체 문서·안전 오류 후속 (2026-09-11, 미완료)

- 실패6건의 core 재준비 뒤754·755의 자동 ready가 각각49쪽124자/30쪽145자의 `제안개요` 작성 양식을 선택한 것을 확인했다. 해당 명시 장 제목만 `ambiguous_scope_boundary`로 보내는 최소 가드와 기존 ready의 읽기 전용 경고를 검증·배포했다. 기술적 용량이 작아도 범위가 부적격이므로 입력 준비 완료에 넣지 않는다. 기존 target은 보존하며743·745·746·747·751·753·754·755·756·758·760 총11건의 정당한 범위를 담당자가 확인해야 한다. 운영 확인 (`../../.dryforge/prespec-mvp-deploy-20260911-OIBy24/scope-api-verification.json`, 실행 당시 로컬 산출물·현재 checkout 없음).
- 753의 기존 2–18쪽/65,141자 범위는 같은 줄 복수 장 경계로 모호하다. 새 선택기는 전체 page-text/PDF hash를 읽기 전용 대조한 뒤 `ambiguous_scope_boundary`를 반환했고 기존 target은 보존했다. 751·756·758·760과 함께 담당자가 PDF에서 정당한 범위를 확인해야 한다. 용량 한도 확대·요약·자동 분할은 하지 않는다.
- 752에는 안전한 과업지시서/용역설명서가 있으나 v4는 파일명 기반 RFP 선택만 한다. 기존 document role 수정 API와 bundle 선택은 이 실행 선택에 연결되지 않는다. 권장 최소안은 explicit_sample 준비의 정확한 document_version_id 선택과 notice/current/safe/hash/source 승인·actor 감사 결속이다. 자동 선택 확대나 role 변경으로 우회하지 않고 계약/담당자 결정 대기로 남긴다.
- 750·757의 저장 오류 `unsafe_document`만으로 악성 여부를 판정할 수 없다. attachment 경계는 allowlist 밖 세부 processor 코드를 unsafe_document로, API는 일부 안전 오류를 포괄 코드로 낮춘다. 기존 안전한 저장 정보에서는 더 좁은 원인을 확인하지 못했다. 승인된 격리 재진단/안전한 코드 확장 없이는 추정하지 않으며 차단과 원본을 보존한다.

## 운영 `attachment.name`이 나라장터 자리표시자라 파일명 대조가 무의미하다 (2026-09-11, 경고로 완화됨·미해결)

- 재현: 운영 나라장터 응답의 `attachment.name`은 흔히 "첨부 1"류 자리표시자이고
  실제 파일명은 취득 응답 header에서만 온다. `document_bundles.py`의 확정 검사가
  `attachment.name != document.original_filename`이면 `source_name_differs`를
  내지만, 이 코드는 `blocking=False`(비차단 경고)로 완화돼 있다 — 원문 정체는
  이름이 아니라 hash·크기로 확인하기 때문이다(`web/backend/app/deep_review/services/document_bundles.py:428`
  부근 주석 참고).
  실제 원문이 바뀐 경우는 크기·hash·provider snapshot 검사가 별도로 차단한다.
- 영향: 나라장터가 원문 이름을 주지 않는 한 이 경고는 정상 케이스에서도 계속
  남고, 이름 기반 대조 자체는 사실상 정보를 주지 못한다. 확정을 막지는 않는다.
- 후속: 수집 단계(`skills/bidops-collect`)에서 취득 응답 header의 실제 파일명을
  더 이른 시점에 확보해 `attachment.name`에 반영할 수 있으면 이 경고를 줄일 수
  있다. 지금 범위에서는 해결하지 않는다.
- 영향/다음 판단: 입력 준비·전송·암호화 저장·검증 실패/근거 PDF 조회는 작동하나 검증된 개요를 얻는 실제 성공 경로는 미확인이다. 다음 개선은 초안 section/quantity/unknown 계약과 결정적 규칙의 실원문 적합성을 이 고정 응답/인용으로 좁혀 확인하는 것이 우선이다. 이번 실행 요청에서 새 정책/검증 방식 변경·사실 자동 수정·재호출을 임의로 진행하지 않는다. 원문·기존 결과/사람 리뷰/참조 표식과 실패 응답을 보존했다.

## 2026-10-09 로컬 ARM Mac의 Rosetta 문서 변환 실패

- 실제 3일 공고 회차 `dev-notices-20261006-20261008`에서 notice 40 / attachment 57의 HWP 취득이 `conversion_required`로 차단됐다. 격리 원문 SHA-256은 `ea8c18e7075044249cf267c1d8ebabe2c190843a9f9b021c8de97ea32e4f5d07`이다.
- 같은 로컬 `linux/amd64` document-worker에서 pinned rhwp 0.8.6 `export-hwpx --verify --verify-pages --json` 직접 진단은 exit 0이다. 제품 `_child_environment`와 `_resource_limiter`를 적용한 같은 명령은 exit -5이고 stderr의 안전 분류는 Rosetta/mmap 오류(57 bytes)다. 문서 손상으로 확정할 근거는 없다. 개별 rlimit 중 원인까지는 분리하지 않았다.
- 영향: 이 Mac의 x86 에뮬레이션 환경에서는 HWP 변환과 이후 실제 개요 실행을 완료했다고 할 수 없다. 직접 변환된 진단 산출물을 제품에 수동 적재하거나 자원 제한을 해제해 우회하지 않는다. native x86 실행 환경 또는 동일 격리·검증을 갖춘 native ARM 변환기 검증이 후속 방향이다. LiteLLM 연결 수정 범위에서 renderer/보안 경계는 변경하지 않는다.
- 별도 upstream 자료 문제: notice 27 / attachment 36은 파일명 `.hwp`, 실제 MIME `application/hwp+zip`(116,322 bytes)라서 `mime_mismatch`로 차단됐다. 두 실패의 원문과 행은 보존했고 자동 재시작하지 않았다. 실행 증거는 로컬 `.sdlc/local-runtime/overview-preflight-result.json`이다.

### 같은 날 후속 진단·로컬 복구 진행

- 개별 제한 진단으로 HWP→HWPX 실패를 DATA 상한 512 MiB(Rosetta mmap)로 분리했다. 네트워크 없음·1 GiB cgroup·pids 128·권한 0·NoNewPrivs 조건을 모두 검사하는 로컬 `rosetta` opt-in을 추가했고, native rhwp에만 DATA 768 MiB를 허용한다. 보조 도구는 512 MiB를 유지한다. 기본 설정은 변하지 않았다.
- 공고 179 / 첨부 264(한부모가족 혼인정보 연계시스템 운영·유지관리)의 실제 HWPX 388,356 bytes는 정규 수집·ClamAV·구조화 경로로 완료됐다. 지정 공고 one-shot 실행 전후 264개 큐 행 중 이 행만 바뀌었으며 기존 차단 2건을 포함한 263개 행은 그대로다. 원문 SHA-256은 `d62ee1f0bee0039ab4e741f099f76680bb2d607a791f9389dece287aa2aa439c`다.
- 같은 원문의 개요용 PDF export는 768 MiB 환경에서도 메모리 할당 실패(exit -6, 524,288 bytes 할당 실패)로 중단됐다. 구조화 성공을 PDF/개요 완료로 표시하지 않는다. 실제 모델 전송은 0회다. 같은 upstream commit을 사용한 native ARM 격리 워커 빌드를 진행하며, 기본 제한을 추가로 높이지 않는다. 상세는 `docs/validation-runs/20261009-litellm-reference/target179-document.json`과 `plan.md`다.

### Native ARM 후속 결과와 남은 PDF 표시 문제

- 동일 upstream commit의 native ARM worker에서 기본 DATA512MiB를 그대로 사용해 공고179의 정규 PDF snapshot 준비가 성공했다(80쪽). Rosetta 완화 코드는 최종 변경에서 제거했다. 적용된 로컬 이미지와 바인딩은 `docs/validation-runs/20261009-litellm-reference/target179-document.json`에 기록했다.
- 물리5쪽에서 export-text와 Poppler 텍스트층에는 웹사이트 현황·도메인이 있지만, 직접 렌더링한 화면에는 그 일부가 보이지 않는다. PDF 렌더링/텍스트 표시 불일치이며 모델 문제가 아니다. 전체80쪽의 시각적 정확도를 승인한 것으로 취급하지 않는다. 이 작업은 해당5쪽을 모델 전송에서 제외하고, 시각적으로 대조된4쪽만 개요 검증 후보로 고정했다.
- 재현: 위 sourceSHA의 snapshotPDF `eb394a414704b70de1e23d264df4a61a50b38c0aea3c3fdc3232a7a7c5896bcb`를 `pdftoppm -f5 -l5 -png`로 렌더하고 `pdftotext -f5 -l5 -layout` 및 동결page-text와 대조한다. 로컬 증거는 `.sdlc/local-runtime/target179/page-05.png`, `page05-poppler.txt`, `snapshot-pages.json`이다. 원본HWPX와 snapshot은 보존했다. 렌더러 레이아웃/가림 분석은 별도 후속 범위이며 텍스트나 PDF를 수동 보정하지 않는다.


## 2026-10-14 HP 카드 쪽 연결의 실측 한계와 PDF 표 겹침

- HP-01의 제품 파서로 실제 RFP 5건에서 27/57/31/35/48장(합계 198장)을 추출했다. 현재 명세의 가까운 비어 있지 않은 문단 3개 anchor 규칙으로는 0/18/31/35/4장, 합계 88장만 `inherited`이며 110장은 `unavailable`이다. 셀 직접 매핑은 0장이다. 초안 scratchpad의 198/198을 재현하지 못했으며 완료·품질 수치로 인용하지 않는다.
- 미확인 카드의 가장 가까운 매핑 가능한 앞 문단은 4~39개 앞에 있었다. 원문·대응표와 고정 규칙은 유지한다. anchor 수를 무제한으로 늘리면 먼 앞쪽 페이지를 카드 쪽으로 잘못 연결할 수 있으므로 이번 범위에서 임의 변경하지 않았다. 후속은 직접 셀 매핑 개선 또는 별도 버전의 anchor 규칙과 정확도 검증이다.
- 문서당 첫·마지막 카드 2개, 총 10개 PDF 렌더를 리더가 직접 확인했다. 상속값이 있는 6개는 해당 물리 PDF 쪽에 카드가 있고, 4개는 PDF에 카드가 있으나 제품 쪽은 미확인으로 남는다. 전체 198장의 쪽 정확도를 검증한 것은 아니다. `hp01-pdf-spotcheck.json`·`hp01-page-map-diagnosis.json` 및 변환 입력 hash는 `docs/work/_runs/hp0001-20261014/`에 있다.
- 같은 표본 중 `school` 물리 PDF 13쪽은 첫 DAR-001 카드가 보이지만 아래 DAR-003 부근 텍스트가 겹친다. 구조 추출 성공이 PDF 전체의 시각적 정확성을 뜻하지 않는다. 재현 산출물은 Git 외부 `.sdlc/local-runtime/hp01-20261014-fixtures/school.pdf`와 `samples/school-13.png`이며 원문/변환 hash는 위 실행 기록에 있다. renderer 수정은 HP 카드 inventory 범위 밖이다. 원문과 구조를 보존하고 PDF를 수동 보정하지 않는다.

## R5 런타임 이미지에 `fc-list`가 없어 native 변환이 전부 실패했다 (2026-09-10, 해결)

정리 메모(2026-10-21): 주 결함은 조치됐으나 아래 잔여 한계는 당시 기록 그대로이며 현재 재검증하지 않았다.

- 재현: `bidops-rdp-r5:20260910`(R5 게이트를 통과한 이미지)에서 notice 142 HWPX를 격리 조건(pids 128·1 GiB·network none)으로
  `DocumentProcessor`에 넣으면 rhwp 네 호출이 끝난 뒤 26.8초에 `converter_unavailable`("PDF 글꼴 manifest를 확인할 수 없습니다")로
  끝난다. `_font_manifest_sha256`이 `shutil.which("fc-list")`를 요구하는데 이미지에 `fontconfig` 패키지가 없다.
- 원인: R0~R3 이미지의 `fontconfig`는 Chromium(`libpango`)의 의존성으로만 설치돼 있었고, R5가 Chromium을 제거하면서 함께
  사라졌다. R5 게이트("chromium·node 없음, runtime contract")는 폰트 manifest 실행 경로를 검사하지 않았다.
- 영향: 그대로 배포했다면 HWP·HWPX 준비가 모두 실패하고 notice 범위 실패 attempt가 `current`를 덮었을 것이다. 운영 배포 전
  R6 격리 실측에서 발견해 운영 영향은 없다.
- 조치: `web/Dockerfile` apt 목록에 `fontconfig`를 명시하고 `tests/app/test_runtime_contract.py`의 단언을
  `fontconfig fonts-nanum fonts-noto-cjk`로 고쳤다. `bidops-rdp-r6:20260910`에서 `fc-list`와 폰트 manifest
  `92e5dc4f…1650a9`(R3 이미지와 동일)를 확인했다([R6 기록](../../validation-runs/2026-09-10-rhwp-pipeline.md)).
- 남은 것: 이미지 안에서 실제 변환기 실행을 검사하는 게이트가 없다. 다음 이미지 변경부터는 R6 기록의 probe 명령으로 표본 1건을
  실제 실행해 확인한다.

## 0910 신규 RFP 절 후보 검사 실패 (2026-09-11 운영 core 재준비6건 해결)

정리 메모(2026-10-21): 주 결함은 조치됐으나 아래 잔여 한계는 당시 기록 그대로이며 현재 재검증하지 않았다.

- 재현: 승인된 신규 notice743·745·746·747·754·755의 안전한 RFP를 기존 `bidops-rdp-r7:20260910` worker, prepare_pdf=true/300초/64MiB 조건으로 각1회 준비하면 `pdf_preparation_failed:section_candidates_invalid`로 terminal 실패한다. 같은 실행의 다른9건은 snapshot을 만들었다.
- 영향: 위6건은 개요 입력을 동결하지 못해 Qwen 호출 대상에서 제외된다. 원본15개 전체의 version/hash/size 재조회는 일치했으며 이 실패를 원문 변조나 악성코드 검출로 단정하지 않는다.
- 원인: 사이드 리뷰의 pinned rhwp digest 재현은 6건 모두 exit0였다. 743·745·754·755는 정상 outline(전체/반환 5/5·5/5·28/28·1/1), 746·747은 67/50·111/50 부분 반환인데 BidOps가 mode와 전체=반환을 잘못 강제했다. 이는 전체 PDF 재변환 성공 근거는 아니다.
- 수정/검증: outline·총/반환 수를 구분한 후보 v2, digest의 advisory 실패와 검증된 core 분리, 부분 후보의 수동 쪽 선택을 구현했다. native parser/processor·sidecar 소비·범위 연결 격리 검사가 통과했다(Plan(0910 안정화 Plan, 폐기됨 — git 이력 `71b9954`)).
- 운영 확인: 후속 승인으로 수정 web/document-worker2를 반영하고 위6건만 각1회 준비해 모두 core PDF/page-text를 얻었다. 원본·기존 실패·결과·리뷰는 동일하고 새 snapshot/target각6을 추가했다. 743·745는 범위 시작 미확정,746·747은 부분 후보라 수동 확인이다. 754·755는 제안 작성 양식 오선택을 발견해 아래 후속으로 분리했다. Qwen은0, source-only 준비 뒤 OFF다. 새 실행 증거 (`../../.dryforge/prespec-mvp-deploy-20260911-OIBy24/README.md`, 실행 당시 로컬 산출물·현재 checkout 없음), 이전 실패 보존 (`../../.dryforge/prespec-0910-preparation-3vfrYK/pdf-execution.json`, 실행 당시 로컬 산출물·현재 checkout 없음).
