# 사전규격 v4 페이지 개요·회사 핏 연속 처리 구현 계획

기준일: 2026-09-09
상태: 진행 중  
정본: 이 문서는 현재 구현의 단계·인수 기준·중단 경계를 보존한다. 단계 시작과 컨텍스트 복구 때 다시 읽는다.

## 목표와 범위

`우선 검토` 대상 중 적용 대상이 동결된 문서만 대상으로, 원문에서 검증된 PDF를 먼저 준비하고, PDF의 선택 페이지로 v4 페이지 개요를 실행·검증·저장한다. 현재 승인된 회사 프로필과 대조해 `matched`일 때에만 기존 심층 검토 생성 서비스로 연결한다. 실제 모델 응답이 DB·REST·관리 화면에서 동일한 현재 결과로 보이는 것까지를 목표로 한다.

## 최신 운영 상태 (2026-09-09)

- explicit sample activation은 OFF다. `AuditEvent` `07c1d75a-c36a-48c7-9de5-a7efa1e741c7`가 `reference_samples_complete_with_142_unverified` 사유를 남긴다. 142·35·59 모두 grade는 `None`이고 automatic deep를 우회하거나 강제하지 않았다. 사람 결정은 변경하지 않았다.
- 35 overview result `a28a188b-0638-4dbb-b867-ea5a12c6c168`는 completed/current다. company-fit attempt `bb2d93f4-1915-4e72-a4f5-f647d8860a5e`는 `completed/current/unknown`, raw SHA-256은 `c147828b4efa9423d7af2ac138705e8d775a5a8c674a543275fb35dfc276d822`이고 API payload가 Luna reference 첫 응답과 exact 일치한다.
- 59 overview result `04d6182f-f073-450a-b8be-30f141db9f02`는 completed/current다. company-fit attempt `4af5b488-59c2-445e-8cf3-4a33baad44be`는 `needs_human_review/current`, result는 `null`, raw SHA-256은 `67b292a7ca012a7995f7a98d7be11d972fd97e72b603cf5e17552cb272254f11`이다. `unsupported_number`로 index 0 선택 근거에 24시간이 없어졌고 암호화 raw를 보존했으며 보정·재시도하지 않았다.
- 142 PDF는 반복 timeout 뒤 `unverified`다. offline Luna JSON은 참조 입력으로만 보존하며 성공 PDF/current로 승격하지 않았다. 실제 UI는 35/59에서 사업명 검색·목록/상세·독립 상세·refresh/reentry와 1280×800·1440×900을 통과했고, API 본문·제한사항·prompt/result ID·PDF hash/link를 확인했다. 35의 `unknown` 근거와 59의 `needs_human_review` 안전 문구·판정 본문 비노출도 확인했다.
- 운영 경로는 `localhost:18887/pre-specs/{35,59}`이며 18787 bind 실패를 기록한다. `overview-actual`은 중지했고 `prespec-actual`은 원래 `sleep infinity`로 복원했다. document-worker 두 개는 `bidops-v4-luna-reference:20260909-final`, 1 GiB 조건으로 복원됐다. persistent reference artifacts는 `.dryforge/prespec-v4-luna-20260909/{overview-generation,company-fit-input-35-59,company-fit-generation-35-59}`에 두며 credentials를 포함하지 않는다.
- 142 PDF 실패의 원인은 document-worker `pids_limit` 128과 v4 CLI 기본 출력 예산 20 MiB로 확인돼 수정(pids 512·기본 64 MiB)이 `212e5ed`로 병합됐고, 2026-09-10 worker 두 개를 pids 512로 재생성한 뒤 142의 표준 PDF snapshot `e68670e0-4bf7-4cd9-baa1-174f19e5e994`(85쪽)와 target `200e9557-d5d5-4a0f-afa8-896d44b41261`(3~13쪽)을 준비했다. activation은 즉시 OFF로 되돌렸고, Qwen endpoint가 닿지 않아 attempt·`current`·UI 인수는 여전히 미완이다([findings](findings.md#원인-확인-notice-142-표준-pdf-준비가-300초-deadline에서-종료됨-2026-09-09)).
- UI acceptance 결과는 `.dryforge/prespec-v4-luna-20260909/ui-acceptance-result.json`과 실행 script에 보존한다. 이 상태는 explicit reference 실행과 controlled backend 결과를 기록한 것이며 전체 계획 완료를 뜻하지 않는다. automatic cohort/deep와 142 PDF는 미완료다.

### 구현·검증 종료 규칙

검증 목적은 저장된 계획의 인수 기준 충족 확인이다. 변경 경로와 실제 실패 위험에 필요한 최소 검증만 수행한다. 통과한 검증은 관련 코드 변경이나 새로운 실패 근거가 없으면 반복하지 않는다. 요구사항 위반, 데이터 손상, 보안 문제, 실제 사용 흐름을 막는 결함만 이번 작업에서 수정한다. 추상화·리팩터링·추가 기능·가상의 예외 대응은 범위를 확대하지 말고 후속 사항으로 기록한다. 인수 기준을 충족하면 검토를 종료한다. 환경 문제로 실행하지 못한 항목은 미검증으로 명시하고 대체 테스트를 계속 늘리지 않는다.

다음 경계는 유지한다.

- 발주계획 선별, 추적 승인, 최종 입찰 Go/No-Go는 건드리지 않는다.
- 기존 legacy 개요·사람 리뷰·심층 리뷰를 덮어쓰거나 자동 재실행하지 않는다.
- 참조 실행은 `unmeasured_reference`를 유지하며 품질 측정·운영 정책 활성화 근거로 승격하지 않는다.
- 기본 비활성·scheduler 비활성·hosted fallback 금지·실제 외부 호출 승인 경계를 유지한다.
- PDF 검증이 실패하면 v4 자동 실행과 후속 회사 핏·심층 시작을 중단하고 사람 확인 상태로 남긴다.

## 최소 변경 접근과 재사용 지점

새 범용 실행 엔진·플러그인·설정 프레임워크·재시작 UI·일반 기록 테이블을 만들지 않는다.

1. 기존 `DocumentProcessor`의 non-root quarantine 경계, vendored `rhwp`, 기존 제한 subprocess, PDF 구조 추출과 `DocumentBundleService`/`document_structure`를 재사용한다. 필요한 것은 HWP/HWPX 원본과 변환 PDF를 구분하고 PDF 페이지·텍스트 대응을 불변 객체로 저장하는 최소 계약이다.
2. 기존 `prespec_page_overview`, `PreSpecOverviewRunner`, `app/core/model_client.py`, overview 용도 binding·lease·raw 응답 암호화 저장·공유 validator를 재사용한다. v4 policy/few-shot과 실제 `PrespecV4OverviewRunner`를 정규 경로로 연결하되, v4 target/attempt가 없는 기본 상태에서는 기존 legacy queue를 보존한다.
3. 기존 회사 핏 서비스·합성 analysis worker의 단일 슬롯·자동 심층 생성 게이트를 확장해 v4 결과와 현재성 검사를 연결한다. 회사 핏/심층 전용 일반 엔진은 추가하지 않는다.
4. 기존 목록·상세 REST projection과 React 페이지 개요·회사 핏 화면을 확장한다. 서버가 선택한 현재 결과와 진행 상태를 투영하고, 화면은 재요약·임의 절단 없이 렌더링한다.
5. DB는 현재 head 뒤 migration만 추가한다. 0021의 불변 PDF snapshot/manifest와
   0022의 실제 소비 attempt에 필요한 최소 열·FK·append-only·lease fence만 둔다.
   회사 핏·심층 대상/정책 활성 이력과 UI 상세는 후속 단계에서 기존 구조를 재사용한다.

## 단계와 체크리스트

### 0. 기준선·실행 경계 확인

- [x] 저장소 지침, 상태·업무 규칙·계약·보안·운영 문서와 backend/web AGENTS를 읽었다.
- [x] 현재 `bidops-web-1`, `bidops-overview-actual`, `bidops-prespec-actual` 컨테이너의 역할과 작업 중복을 read-only로 확인했다. 운영 서비스 재시작·정책 활성화·live 호출은 하지 않았다.
- [x] 기존 `R26BD00271191` 필수 표본과 현재 DB 관측 시각/첨부 이력을 read-only로 확인했다. `DocumentVersion.created_at`만으로 신규를 판정하지 않는다.
- [x] 현재 작업트리의 baseline 변경과 이 계획에서 직접 수정한 파일을 분리해 기록한다.

인수 기준: 운영 상태 변경 없이 현재 head·migration·권한·서비스 역할·필수 표본의 관측 근거를 확인하고, 기존 회귀 실패를 새 실패로 분류할 수 있다.

### 1. PDF 선행 변환·페이지 대응

- [x] HWP/HWPX를 bytes-only로 받아 non-root document worker에서 동일 vendored rhwp WASM의 Canvas 페이지와 renderer text-run을 만들고, trusted inline module/CSP와 Chromium 인쇄로 PDF를 만든다. 원문은 base64 data로만 주입하고 text-run은 `textContent`로 넣으며, `color: transparent` 레이어를 검색 가능한 텍스트로 사용한다. 네트워크·자격증명·호스트 파일 확장을 허용하지 않는다. 구형 SVG page adapter는 제거했다. `labor_template.hwp`, vendored export HWPX, 실표본 RFP HWPX가 별도 검증 이미지에서 실제 통과했다.
- [x] HWP/HWPX 원본, 변환 설정·글꼴/renderer 버전, PDF bytes/hash/page count/full page text를 각각 기존 versioned object/location으로 보존한다. worker가 산출한 adapter·processor/CSS 포함 runtime, 실제 Chromium ELF, font 파일 바이트 manifest fingerprint를 caller 기대값과 대조하고, 동일 source version·worker provenance·정규 options 성공 PDF는 변환 전에 object version·etag·최신 clean scan까지 확인해 재사용한다. 실제 image digest 선언이 없을 때는 `worker_image_digest=null`로 남기고 asset hash를 image digest로 사용하지 않는다. PDF 선행 인수 시점에는 운영 row 저장 전이었으며, 후속 실제 연결에서 35/59에만 이 계약을 적용했고 142는 미검증으로 남겼다.
- [x] 변환 PDF의 실제 페이지 수·텍스트 추출·한글·주요 표·금액·페이지 대응을 검사한다. `labor_template.hwp`의 2개와 export HWPX의 3개 물리 페이지에서 통과했고, 생성 PDF의 `application/pdf` 입력 경로도 같은 page text를 확인했다. PDF object 제한은 기본 `4,096`을 유지하며, 형식 회귀에는 `max_pdf_objects=10,000`, 실표본 RFP Canvas 인수에는 기존 허용 범위 안의 명시 옵션 `max_pdf_objects=100,000`을 사용했다(생성 PDF의 실제 object marker는 `9,009`). object limit를 Poppler fallback으로 우회하지 않는다. 빈 텍스트·이미지화·페이지 대응 불가·표 관계 불명확·제한 초과는 `needs_human_review`/실패로 남긴다. 정상 공백 페이지는 보존하고 경고만 남긴다.
- [x] HWPX 구조에 가짜 PDF page를 붙이지 않는다. 기존 HWP→HWPX만 성공한 경로는 PDF 준비 완료로 취급하지 않는다. `rfp.hwpx` 최소 fixture는 렌더 표본으로 사용하지 않았다.
- [x] 기존 입력·압축 해제·페이지·출력 안전 한도와 부분 파일 정리를 유지하고, rhwp와 Chromium은 하나의 작업 deadline을 공유한다. Canvas/HTML 합계에도 출력 예산을 적용하고, 요청별 Chrome profile·완료 receipt·고정 raster scale 1을 사용하며 child마다 별도 300초를 부여하지 않는다. 아주 작은 기존 PDF fixture처럼 Poppler가 거절하는 경우에만 bounded stdlib portable-text fallback을 허용하고, 복잡한 준비 PDF의 정본은 Poppler로 유지한다.

인수 기준: 현재 검증된 HWP/HWPX 표본과 생성 PDF의 PDF 입력 경로는 실제 페이지·텍스트 대응을 통과했고, 실패 입력은 자동 실행 대상에서 제외된다. PDF byte hash는 Chromium 실행 시각 metadata로 실행마다 달라질 수 있어 text/page hash와 설정·원본 결속을 보존해야 한다. 실표본 RFP HWPX snapshot과 불변 PDF snapshot/sidecar 영속화가 완료되기 전에는 v4 자동 실행을 활성화하지 않는다.

검증 근거: [2026-09-08 PDF 선행 검증 기록](../validation-runs/20260908-prespec-pdf-preflight.md). Canvas 생성·Chromium 인쇄·v2 scratch sidecar 전달 계약과 실표본 RFP 내용 인수는 통과했다. 불변 snapshot 영속화는 후속 실제 연결에서 35/59에 적용했고, 142는 마지막 표준 prepare timeout 뒤 미검증으로 남겼다.

현재 bounded 단계 checkpoint: immutable PDF snapshot/선택 manifest와 v4 policy·attempt·
current projection을 구현했다. attempt 선행 스키마를 보류했던 이전 checkpoint는
실제 소비자가 생기기 전 상태를 기록한 과거 요약이다.
snapshot은 원문/PDF와 full page-text JSON을 각각 기존 versioned
`ContentObject`/`ContentObjectLocation`으로 결속하고, manifest는 선택된 페이지의
정확한 substring만 별도 구조 object로 저장한다. `PrespecV4Attempt`는 이제 실제
runner가 소비하는 target-scoped fenced attempt로 연결되어 정상·실패·준비 실패를
`current`에 투영한다. 개발 HWP의 nonempty-but-gibberish
font glyph 추출은 v4 `prepare_pdf`의 Poppler 정본 텍스트 경로로 교정했고, 개발/운영
실표본 범위 경계는 본문 장 전체와 필요한 첫 과업 절만 보존하도록 수정했다. 이
checkpoint의 isolated 검증 시점에는 운영 DB/MinIO 쓰기, live 모델 호출, scheduler
활성화를 수행하지 않았다. 이후 2026-09-09 백업 후 migration·권한·배포 경계를
적용해 35/59의 실제 target→attempt→worker 흐름을 실행했다. 35는 target
`5664dbef-4341-4348-b4f0-da2f6b455168`, attempt
`0200ccfd-5b08-42c8-a677-6aa8aa8ca117`가 완료됐고, 59는 target
`a188de71-9aaa-46e4-b30e-2fc484e53e82`, attempt
`3b82e19d-7939-4d3d-b07a-a02b795b2f80`, result
`04d6182f-f073-450a-b8be-30f141db9f02`와 `current=completed`를 확인했다.
59의 결과는 `gpt-5.6-luna` 명시 `unmeasured_reference`로 보존했으며 품질 승격이나
자동 심층 시작은 하지 않았다. 142는 표준 prepare를 마지막 300초 timeout까지
실행했지만 성공하지 않아 미검증으로 남겼다. current 계약을 소비하는 UI focused
검사와 backend controlled 검증, 35/59 실제 API/UI acceptance를 통과했다. 35/59의
명시 company-fit 결과도 저장했지만 automatic company-fit/deep gate는 수행하지
않았다.
cache hit도 source/PDF/page-text object의 exact version·etag·size/hash와 최신
`ContentScan.status=clean`을 확인하며, 더 최신 infected/unavailable scan이 있으면
재사용하지 않는다. 생성 worker provenance는 caller dict만 신뢰하지 않고 실제 worker가
반환한 metadata fingerprint와 비교한다. runtime fingerprint에는 vendored adapter와
processor/CSS를 포함하고, Chromium launcher가 아닌 실제 Debian Chromium ELF의
hash와 font 파일 바이트 manifest를 기록한다. 실제 image digest 선언이 없으면
`worker_image_digest=null`로 남긴다. 원본 PDF sidecar는 재렌더하지 않음을 표시하고
실제 Poppler/stdlib extractor provenance와 `font_provenance=null`을 기록한다.

이번 단계의 safe 검증 요약: `compileall`·vendored `SHA256SUMS` manifest 검사와
Canvas HTML/CSP 회귀가 통과했다. `labor_template.hwp`는 2 physical pages, 정상
export HWPX는 3 pages, 생성 PDF의 PDF 입력 경로도 3 pages로 통과했다. 실표본
`R26BD00271191` HWPX(840,114 bytes, SHA-256
`7cc3b5f3894d984ce641e9462030990cbb4cfc1d6869b18bc9047899a23f4665`)는
동일 worker 조건에서 Canvas scale 1, Noto Sans CJK KR fallback, Chromium 완료
receipt와 함께 85 physical pages/11,041,060 bytes를 생성했다. PDF SHA-256은
`77fa66fca472a89f2b6a1608602eb6afb0be802068e62998dfec007f539f0010`, 전체
`pdftotext -layout -enc UTF-8` SHA-256은
`e58ab1e90fd216005d283417e11991eab177300e2f0f4ed3afbdd0dc837328ef`이다.
p4에서 `298,735,350원`·`365일`·`189MD`, p5에서 `13,225,835,150원`·`12개월`,
p7~8에서 `감리 방법`·`감리 과업내용`·`제안 시 고려사항`을 추출했고, p4/p5 PNG
시각 대조에서도 표·금액·기간이 보존됐다. 생성 PDF object marker는 9,009개라
검증 호출에 기존 허용 범위의 `max_pdf_objects=100000`을 명시했다. sidecar 전달과
DB/MinIO snapshot·attempt 운영 영속화와 실제 모델 호출은 이 선행 검증 시점에는
하지 않았다. 후속 실제 연결에서는 35/59에 한정해 명시 Luna reference response를
재사용했고, 142는 마지막 prepare timeout으로 미검증이다. 통제 model client roundtrip은 선택
manifest→v3 validator→encrypted raw/result/current projection만 검증했다.

### 2. PDF 계약·범위 선택·입력 동결

- [x] scratch 요청은 v1 구조 경로와 v2 `prepare_pdf` 경로를 schema로 구분하고, 제한 파일·크기/hash만 전달하며 PDF bytes를 JSON에 넣지 않는다. v2는 request UUID에서 도출한 단일 PDF sidecar를 원자 publish하고 경로 이탈·symlink·부분 파일·크기/hash 불일치를 차단한다.
- [x] 대표 문서 선택 규칙을 재사용한다. 제안요청서 파일명이 없거나 모호하면 사람 확인으로 보내고 임의 대표 문서를 고르지 않는다.
- [x] PDF 제목·문단과 기존 제목 규칙으로 사업 개요·목적·범위·주요 과업 절을 선택한다. 상위 제목 문맥을 포함하고, `감리대상 사업` 개발 내용을 이번 감리 과업으로 바꾸지 않는다. 실제 Poppler 구조에서 142는 p3–13, 개발 35는 p4–8, 운영 59는 p3–5 경계를 확인했다.
- [x] 선택 page substring·locator·full-page hash를 versioned JSON manifest로 동결한다. 정상적으로 여러 PDF 페이지에 걸친 범위는 필요한 모든 페이지를 포함하고, 경계나 표 관계가 불명확할 때만 사람 확인으로 보낸다. 전체 문서 fallback·임의 절단·공고 메타데이터의 PDF 사실 대체를 하지 않는다.
- [ ] 예산·기간이 원문에 없으면 `unknown`/확인 항목으로 유지한다.

인수 기준: scratch v2 consumer가 원문/structure 검증을 유지하면서 PDF bytes와
`pdf_metadata`를 `ProcessedDocument`로 복원하고 exact-byte ClamAV 결과를 확인한다.
성공 소비·오류·timeout은 요청 UUID 소유 파일만 정리하며, timeout 중 claimed input과
다른 request를 지우지 않는다. scratch 전달과 격리 snapshot/manifest roundtrip은
완료했다. 후속 실제 연결에서 35/59 snapshot/manifest/target/attempt를 저장·재사용했고,
142의 snapshot/target은 prepare timeout으로 저장하지 않았다.

### 3. v4 정책·실행·저장

- [x] 실험 `policy.json`의 system prompt·stage 지시문·reader format·두 synthetic few-shot·output schema·generation·chunking을 `prespec-overview-policy-v4.json`으로 그대로 이관했고 출력 계약은 `bidops.prespec-overview-page-review.v3`를 유지한다. 배포 식별자만 policy v4/model/prompt version으로 정규화했다.
- [x] 실행에 policy 전문/digest, prompt version, generation, model name/revision/digest, input/PDF/source hash를 묶었다. 하드코딩 digest·실험 run 폴더 의존은 없다.
- [x] `overview` 용도 승인 ModelClient만 사용하고 허용 host·64자 revision·승인 설정을 호출 전에 확인한다. v4 retry 0, timeout 300초, lease 600초, 단일 analysis 슬롯을 유지한다. v4 target이 없을 때 기존 legacy queue도 보존한다.
- [x] 동일 대상의 legacy/v4 중복 예약과 동일 입력 중복을 막고, 재시작은 새 attempt로만 한다. running stale는 failed로 닫고 자동 성공/무한 resume하지 않는다.
- [x] analysis의 기존 legacy queue는 v4 target/준비·attempt가 없는 문서에 계속 적용하고, v4 경계가 잡힌 문서만 legacy selector에서 제외한다. v4 active work가 있으면 단일 슬롯 우선순위만 적용한다.
- [x] 응답을 암호화 저장하고 선택 page text·숫자·필수 schema를 공유 validator로 검증한다. schema/근거 실패는 raw 응답 digest를 보존한 failed attempt로 닫고 결과 row를 만들지 않는다.
- [x] 정책·문서 binding이 current/safe·snapshot/result와 맞지 않으면 current를 `stale`로 보이며 과거 결과를 변경하지 않는다.

인수 기준: 실제/통제 응답이 올바른 v3 JSON과 선택 PDF 페이지를 통과해야만 `completed`로 저장되고, 잘못된 응답은 `failed`와 raw 보존으로 남는다. API/UI가 임의로 최신 행을 성공으로 가장하지 않는다.

### 4. 적용 대상·이력·조회 projection

- [x] 정책 적용 기록에는 표본/신규 모드, 활성 기준, policy/model binding, 표본 목록, 활성 시각·기준 이력을 남긴다. 새 registry/table 없이 `AuditEvent` append-only activation metadata를 사용한다.
- [x] 적용 대상은 활성화 이후 최초 관측 공고 또는 기존 공고의 새 첨부 변경 관측만 허용한다. 동일 content hash 재수집·재변환, 지연 변환 완료는 신규가 아니다. 근거 관측 이력이 없으면 자동 제외한다.
- [x] Notice 관측 property와 Attachment snapshot metadata를 실제 DocumentVersion source hash/size와 결속한다. DocumentVersion 생성시각을 신규 기준으로 단독 사용하지 않는다.
- [x] 대상 dry-run, 동결 표본 enqueue, 실패 명시 retry(new attempt) ops 명령/서비스를 기존 worker 경계에 최소 확장했다. 재시작 전용 UI는 추가하지 않는다.
- [x] overview-pages 조회에 현재 실행 상태·현재 결과 ID·안전 실패 사유를 `current`로 추가하되 기존 목록·PDF URL 호환성을 유지한다. 현재 결과는 적용 대상 문서·정책 결속과 validator를 확인해 판정한다.
- [x] GET은 변경/호출을 만들지 않으며 queued/running/failed를 과거 성공으로 숨기지 않는다. current projection과 PG FK·불변·권한을 검증한다. count/filter/detail과 UI polling은 후속 화면 단계다.

인수 기준: 범위 밖 공고 전단계는 예약되지 않고, 재수집 중복·stale lease·재시작 중복이 방지되며, API는 현재 결과와 진행/실패를 일관되게 보여 준다. ops focused 검사는 기본 off, 활성/중단, 관측 전후·동일 metadata, explicit sample, snapshot cache 재사용, retry 새 sequence와 prepare→enqueue를 통과했다. 후속 실제 연결은 35/59로 제한했고 scheduler와 automatic deep는 활성화하지 않았다. 35/59 명시 company-fit 결과와 실제 UI는 인수했지만 자동 gate와 142는 미완료다.

#### 단계 5·6 controlled 연결 상태 (2026-09-09)

- [x] backend v4 runner/current/권한 및 임시 PostgreSQL migration 계약을 controlled 환경에서 확인했다. `test_prespec_v4_runner.py test_prespec_v4_postgres.py test_page_overview.py test_runtime_database_privileges.py test_analysis_worker_slots.py` 결과는 `34 passed, 8 baseline warnings, skipped 0`이다.
- [x] current 계약을 소비하는 UI focused 검사는 Playwright `6 passed`와 build·TypeScript·contrast 검사를 통과했다.
- [x] 실제 API 브라우저/UI acceptance는 35/59에서 사업명 검색·목록/상세·독립 상세·refresh/reentry, 1280×800·1440×900, 본문·제한사항·prompt/result ID·PDF hash/link를 확인했다. 35의 `unknown` 근거와 59의 `needs_human_review` 오류·안전 문구 및 판정 본문 비노출도 확인했다.
- [ ] automatic company-fit/deep gate 연결과 142의 attempt·`current` 완료는 남아 있다. 142의 표준 prepare는 2026-09-10에 마쳤다(snapshot `e68670e0-4bf7-4cd9-baa1-174f19e5e994` 85쪽, target `200e9557-d5d5-4a0f-afa8-896d44b41261` 3~13쪽 `ready`). attempt가 없으므로 `current`는 여전히 직전 실패 attempt `dbbc7b5f-35c5-4f21-8adb-1c2b042dd61e`를 보여 주고 PDF/UI 인수는 Qwen endpoint 복구까지 미완이다. 35/59의 explicit Luna reference company-fit 결과는 `unmeasured_reference` 맥락에서만 표시하며 자동 심층·품질 승격의 근거로 사용하지 않는다.

### 5. 회사 핏·심층 자동 시작

- [ ] v4 적용 대상에는 v4 결과만 사용하고 legacy 권고로 우회하지 않는다. 자동 심층은 `SW사업대상=Y`·`우선 검토`·자동 확정 `ready` bundle·현재성 검증된 v4 개요·현재 회사 핏 `matched`를 모두 만족할 때만 허용한다.
- [ ] v4 개요 사실과 승인 회사 구조정보를 대조하고 `matched|mismatch|unknown|failed|stale|validation_failed`를 별도 이유와 양쪽 근거로 보존한다. `review_analysis`는 사실 근거로 쓰지 않는다.
- [ ] 현재 입력의 `matched`만 기존 DeepReviewService로 연결한다. `mock_reference`는 자동 시작을 차단하며, 승인 설정의 실제 `unmeasured_reference` 참조 실행은 현재성·게이트를 모두 통과한 `matched`일 때 허용한다. 동일 bundle/profile/deep policy는 중복 생성하지 않는다.
- [ ] 사람 추적 결정·사람 리뷰·최종 Go/No-Go는 보존하고 회사 핏 판단과 자동 시작을 서로 대신하지 않는다.

인수 기준: controlled response와 실제 service 조건에서 `matched`만 자동 생성되고 mismatch/unknown/failed/stale/mock은 대기·사람 확인으로 남는다. 자동 시작 여부는 실제 review ID와 감사 이벤트로 판별한다.

### 6. API·UI 연결

- [x] 목록 선택 상세와 개별 상세가 동일한 최신 v4 projection을 사용한다.
- [x] 본문 순서는 `business_overview`, `main_tasks`, `budget_and_period`, `important_conditions`, `reviewer_analysis`, `unknowns`, `input_limitations`를 유지하고 빈 값·검증 실패·unknown을 구분한다.
- [x] legacy는 과거 이력으로 접고, UI가 본문을 재요약하거나 글자 수로 자르지 않는다. 동결 PDF의 실제 페이지 링크와 회사 핏 양쪽 근거·확인사항·심층 결과 ID를 연결한다.
- [x] 실행 중 상태와 완료 결과의 목록·본문 갱신, prompt 실행 시각·품질·현재/과거 표시를 확인했다. 자동 심층은 활성화하지 않았다.
- [x] 1280×800·1440×900에서 긴 문장·오류/needs-human-review·PDF 링크·사람 결정 보존을 확인했다.

인수 기준: 실제 API의 동일 result ID/content/prompt version이 두 상세 화면에 표시되고, 새로고침·재진입 후에도 같은 상태와 PDF version/page가 보인다.

### 7. 검증·표본 인수·적용 판단

- [ ] 관련 backend/frontend 단위·계약·migration·worker·security 테스트를 한 번 통과시킨다. 실패 원인과 변경이 없는 전체 반복은 하지 않는다.
- [ ] 문서 격리·변환·페이지 대응·상위 문맥·잘못된 숫자/페이지/역할·중복/lease/stale/재수집·권한·기존 보존을 검사한다.
- [ ] mock 종단은 코드 연결 검증으로만 사용하고 자동 시작 품질 증명으로 쓰지 않는다. 실제 사설 모델 참조 실행은 승인 범위와 실제 input/output 대조를 거친다.
- [ ] `R26BD00271191`과 개발/운영 유형·형식 보완 실표본을 원문 확인 후 동결한다. 감리 과업과 대상 개발사업, 감리 예산과 대상사업 금액·기간을 분리하고 없는 정보는 unknown으로 둔다.
- [ ] raw→DB→실제 API→실제 UI의 result/prompt/content/PDF version을 대조하고 두 상세 화면의 6개 본문 구역 누락·변형을 검사한다.
- [ ] 실제 matched 표본이 없으면 실제 심층 자동 시작은 미검증으로 명시하고 합성 대체하지 않는다. 사용량·시간은 내부 검증 기록에만 둔다.
- [ ] 변경 파일·테스트·실제 UI·실제 자동 시작·미측정 상태를 분리해 문서화한다. 전체 green을 주장하지 않고 기존 무관 실패를 기록한다.

인수 기준: 표본 제한 배포 전 PDF 선행·manifest·binding·권한·backup·migration 실행 계획이 준비되고, 실패 시 자동 시작이 중단되며 복구는 데이터 삭제·legacy 자동 재실행 없이 새 attempt/새 이력으로 가능하다.

## 적용·중단 경계

적용은 `PDF 선행 검증 통과 → 격리 통합 검증 → 대상 manifest/policy/model binding/권한/migration/backup 준비 → 표본 제한 배포 → 실제 인수 → 신규 참조 자동 처리 기준 동결` 순서로만 진행한다. 기본 off 상태에서는 신규 예약·호출·후속 단계가 시작되지 않고 진행 결과는 보존한다.

다음 경우 즉시 해당 실행을 중단하고 `docs/tracking/findings.md`에 재현 조건·영향·후속 방향을 남긴다.

- 허용 경로 이탈, symlink, 부분 파일, privileged/host 파일 접근, PDF 페이지 대응 불가가 발생하면 즉시 해당 실행을 중단한다. 일반 변환 실패·빈 텍스트는 attempt의 안전 실패 사유로 보존하고 자동 후속 실행을 막는다.
- 원문·PDF·모델 입력 hash 결속 실패, schema/근거/금액 역할 검증 실패를 성공으로 저장하려는 경로.
- 승인되지 않은 host/revision/profile/document가 모델 payload에 포함되거나 hosted fallback이 시도되는 경우.
- 기존 원문·리뷰·결과를 덮어쓰거나, 범위 밖 공고·동일 content hash를 신규 대상/예약으로 잡는 경우.
- PG migration/권한/불변 trigger가 기존 데이터를 보존하지 못하는 경우.

일반 변환·입력·검증 실패는 해당 attempt의 안전 오류와 재현 명령으로 기록한다.
`docs/tracking/findings.md`에는 보안 경계 또는 구조 계약을 깨는 재현만 추가한다.

운영 DB migration, 서비스 재시작, 실제 사설 모델 호출, 정책 활성화는 대상·입력·설정·호출 범위·복구 계획을 먼저 준비하고, 기존 사용자 세션에 이미 부여된 승인 범위와 저장소 보안·운영 규칙을 따른다. 별도 승인 체계를 추가하지 않으며, 승인 범위를 벗어나는 실행은 수행하지 않고 조건을 기록한다. 코드·mock·참조 실행만으로 운영 완료를 보고하지 않는다.

## 검증 근거와 남은 일

검증 근거는 완료된 단계의 실제 명령·결과·시각을 `docs/validation-runs/`에 기록하고 이 문서에서 링크한다. 현재 연결된 선행 근거는 [회사 핏 단계 검증](../validation-runs/20260908-prespec-company-fit.md)과 [PDF 선행 검증](../validation-runs/20260908-prespec-pdf-preflight.md)이며, 후자는 HWP/HWPX 및 생성 PDF의 PDF 입력 경로까지의 근거다. 이번 bounded 단계는 isolated v4 target→attempt→page-v3 result/current roundtrip, failure raw 보존, legacy fallback, exact reference policy contract, runtime privilege와 임시 PostgreSQL 17 migration/FK/trigger를 검증했다. 사용자 명시 Luna generation record 3건과 35/59 company-fit 입력/응답은 실제 policy/input/output hash와 `gpt-5.6-luna` reference provenance를 검사했다. 후속 실제 연결에서 35/59의 target→attempt→worker→current와 company-fit current/error 상태, 실제 API/UI acceptance를 확인했으며, 142는 마지막 300초 timeout으로 미검증 확정이다. automatic company-fit/deep gate와 142 PDF는 아직 없다.

남은 일은 단계 체크리스트의 미완료 항목으로 관리한다. 단계 완료 시 인수 기준·검증 링크·변경 파일을 갱신한다. 이번 bounded 단계에서 직접 수정한 파일은 아래 표에 기록한다. 최신 운영 상태는 `docs/tracking/status.md`에도 반영했다. 이후 구현 파일은 변경 시마다 아래에 추가한다.

### 직접 수정 파일 기록

| 단계 | 파일 | 변경 목적 | baseline과 구분되는 검증 |
|---|---|---|---|
| PDF 선행 | `web/Dockerfile` | Chromium·chromium-sandbox·Noto CJK 런타임 의존성 | 검증 이미지에서 Chromium/font/pdfinfo 실행 |
| PDF 선행 | `docker-compose.yml` | document-worker memory/pids cgroup, `cap_drop: ALL`, `no-new-privileges` 경계 | Compose runtime 계약 13 passed |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/processor.py` | rhwp Canvas/text-run→CSP print HTML→Chromium PDF, deadline·receipt·출력·페이지 검사 | 필수 RFP 85페이지 내용·이미지·텍스트 통과 |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/safety.py` | 기존 입력·archive 안전 경계 재사용 | HWPX 경계 회귀 |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/vendor/SHA256SUMS` | vendored renderer 무결성 manifest | manifest 검사 1 passed |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/vendor/rhwp_render_canvas.mjs` | bounded page geometry adapter; actual Canvas print은 Chromium inline module | non-root/network none에서 HWP/HWPX geometry 통과 |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/vendor/PROVENANCE.md` | Canvas adapter와 unchanged WASM provenance | SHA256SUMS manifest 검사 |
| PDF 선행 | `web/backend/app/deep_review/services/document_converter.py` | 안전 오류·metadata mapping | 관련 worker protocol 검사 |
| PDF 선행 | `web/backend/app/deep_review/services/prespec_attachments.py` | 변환 안전 오류 mapping | 관련 문서 처리 검사 |
| PDF 선행 | `web/backend/tests/deep_review/test_document_mcp.py` | Canvas CSP/textContent/exact pdfinfo receipt·PDF·HWPX archive/object budget·actual provenance 회귀 | 41 passed |
| PDF 선행 | `web/backend/tests/app/test_runtime_contract.py` | worker cgroup 계약 회귀 | 13 passed |
| PDF scratch | `web/backend/app/deep_review/document_protocol.py` | v1 호환 및 v2 PDF sidecar 원자 handoff·bounded read·원본 PDF 실제 processor/Poppler provenance | v1/v2 protocol 회귀 통과 |
| PDF scratch | `web/backend/app/deep_review/services/document_converter.py` | sidecar hash/size/path/ClamAV 검증 및 `ProcessedDocument` 복원 | v2 roundtrip·cleanup 회귀 통과 |
| PDF scratch | `web/backend/tests/deep_review/test_document_worker_protocol.py` | v1 호환·v2 roundtrip·경계·scanner·cleanup·원본 PDF passthrough 회귀 | 14 passed |
| v4 snapshot/input/attempt | `web/backend/app/deep_review/models.py` | full page-text/PDF/renderer/font/config binding, 준비 input identity, fenced attempt와 append-only ORM 경계 | isolated model/current/attempt checks |
| v4 snapshot/input | `web/backend/alembic/versions/0021_prespec_v4_pdf_contract.py` | 기존 0020 회사 핏 head 뒤 snapshot·prepared input 두 table과 PostgreSQL FK/check/immutable trigger·audit marker | 임시 PostgreSQL 17 upgrade/FK/중복/append-only 회귀; 2026-09-09 운영 적용은 백업 후 수행 |
| v4 snapshot/input | `web/backend/app/deep_review/services/prespec_v4.py` | scratch processor→versioned source/structure artifacts→exact scan/hash snapshot→heading substring manifest, worker fingerprint·cache artifact 재검증 | focused roundtrip/range/scan-binding tests |
| v4 snapshot/input | `web/backend/tests/deep_review/test_prespec_v4_preparation.py` | full page text 저장·생성 PDF source namespace·snapshot reuse-before-conversion·scanner/identity/range/provenance boundary | 5 passed |
| v4 snapshot/input | `web/backend/tests/deep_review/test_prespec_v4_postgres.py` | 임시 PostgreSQL 17 실제 upgrade 후 FK/중복/append-only trigger 검증 | combined PostgreSQL smoke 12 passed |
| v4 policy/runner | `web/backend/app/deep_review/policies/prespec-overview-policy-v4.json` | policy v4·output schema v3·prompt v4·qwen3.8-27B·retry0/timeout300/generation binding | policy loader/reference parity check |
| v4 policy/runner | `web/backend/app/deep_review/policies/prespec-overview-prompt-v4.md` | 정규 policy의 실행 지시·few-shot·reader format을 사람이 검토할 수 있는 원문으로 고정 | reference policy/prompt parity check |
| v4 policy/runner | `web/backend/app/deep_review/services/prespec_v4_runner.py` | 선택 manifest만 모델에 전달, target/legacy fence, 600초 lease, raw/result/current projection, batch current binding | runner/dispatch/current focused checks |
| v4 dispatch | `web/backend/app/deep_review/services/prespec_overview.py`, `web/backend/app/deep_review/services/prespec_overview_runner.py` | v4가 주장한 document version만 legacy candidate/claim에서 제외하고 범위 밖 legacy queue 보존 | dispatch focused checks |
| v4 dispatch | `web/backend/app/workers/analysis.py`, `web/backend/app/deep_review/workers/prespec_overview.py` | 기존 단일 analysis 슬롯에서 v4 runner와 legacy fallback을 함께 호출 | analysis worker slot checks |
| v4 model binding | `web/backend/app/core/model_client.py` | malformed/truncated provider response의 bounded exact raw bytes를 암호화 failure 저장 경계까지 전달 | model client 42 passed |
| v4 policy/runner | `web/backend/alembic/versions/0022_prespec_v4_attempt.py` | target-scoped attempt, preparation failure, PG FK/duplicate/terminal trigger·audit marker | 임시 PostgreSQL upgrade/constraint 검사; 2026-09-09 운영 적용은 백업 후 수행 |
| v4 API/권한 | `web/backend/app/deep_review/schemas/page_overview.py`, `web/backend/app/deep_review/services/page_overview.py` | legacy reviews 호환과 서버 current pointer | page overview/runner focused checks |
| v4 runtime | `scripts/runtime-privileges.sql` | snapshot/target read·prepare write 및 worker attempt/result lifecycle grant | privilege policy focused check |
| v4 tests | `web/backend/tests/deep_review/test_prespec_v4_runner.py` | reference policy parity, blocks-only model input, controlled roundtrip, duplicate, encrypted raw failure, preparation failure/current, scoped legacy dispatch | focused runner command |
| v4 tests | `web/backend/tests/deep_review/test_prespec_v4_postgres.py`, `web/backend/tests/app/test_runtime_database_privileges.py` | 임시 PostgreSQL 17 migration/trigger와 app·worker 권한 smoke | 12 passed |
| v4 Luna reference | `web/backend/app/deep_review/services/prespec_v4_luna_reference.py`, `web/backend/app/deep_review/cli/prespec_v4.py` | generation-record/input/output hash·prompt·공통 record 실행 digest와 sample audit digest 검증, app enqueue/worker replay CLI; Qwen revision 사칭 금지 | 세 sample loader 통과; 35/59 실제 target/worker current 확인, 142 미검증 |
| v4 Luna tests | `web/backend/tests/deep_review/test_prespec_v4_luna_reference.py` | exact prompt/input/output를 주입해 기존 raw→validator→result/current 경로와 Luna current binding을 검증 | `1 passed` |
| 계획·검증 | `docs/tracking/prespec-v4-implementation-plan.md` | 단계 상태·범위·남은 운영 인수 기록 | 문서 기록은 구현/운영 인수 근거가 아님 |
| 계획·검증 | `docs/validation-runs/20260908-prespec-v4-runner.md` | v4 policy/runner/current/권한·임시 PostgreSQL 검증 명령·결과 | 격리/임시 DB 검증이며 운영 인수 근거가 아님 |
| 계획·검증 | `docs/validation-runs/20260908-prespec-pdf-preflight.md` | 실제 명령·safe metadata·Canvas 내용 대조·sidecar·남은 snapshot 경계 기록 | Canvas PDF/content pass와 DB/MinIO snapshot 미완료를 분리 |
| 계획·검증 | `docs/validation-runs/20260909-prespec-v4-cohort-ops.md`, `docs/contracts.md`, `docs/operations.md` | cohort ops와 Luna 명시 참조 입력·역할 분리·남은 live 인수 기록 | loader/runner focused 결과와 미실행 경계 분리 |
| 계획·검증 | `docs/tracking/status.md` | 35/59 explicit reference current, 142 미검증, activation/UI 상태를 최신화 | 운영 상태 기록이며 전체 인수 근거가 아님 |
| 142 PDF 한계 | `docker-compose.yml` | document-worker `pids_limit` 128→512 (Chromium 렌더 thread 고갈) | `test_runtime_contract` + `docker compose config` |
| 142 PDF 한계 | `web/backend/app/deep_review/cli/prespec_v4.py` | v4 준비 기본 `max_output_bytes` 20→64 MiB | `test_runtime_contract` + `docker compose config` |

기준선 기록: 앞선 bounded 실행의 명령은 `cd web/backend && .venv/bin/python -m pytest tests/deep_review/test_document_mcp.py tests/deep_review/test_document_worker_protocol.py tests/deep_review/test_document_integrity.py tests/deep_review/test_document_segments.py tests/deep_review/test_prespec_attachment_assets.py tests/deep_review/test_prespec_e2e.py tests/app/test_runtime_contract.py -q --tb=short`이며 `116 passed, 5 skipped, 3 warnings`가 보고됐다. 이 단계에서 archive-boundary·Canvas CSP/text-layer/receipt 회귀를 추가해 무관한 전체 반복은 하지 않았다. current focused 명령 `tests/deep_review/test_document_mcp.py tests/deep_review/test_document_worker_protocol.py tests/app/test_runtime_contract.py -q --tb=short`는 `65 passed`였고, 정확한 결과는 검증 기록에 분리했다. root의 독립 `tests/deep_review/test_document_mcp.py -q --tb=short` 기준선은 PDF 추가 회귀 전 `33 passed`다.

실표본 관측 및 후속 운영 상태: notice id `142`, notice key `pre:R26BD00271191`, RFP `별첨.제안요청서.hwpx`, document version `59cbc6ef-53f5-421d-84d0-d97c9185ac09`, 원본 SHA-256 `7cc3b5f3894d984ce641e9462030990cbb4cfc1d6869b18bc9047899a23f4665`, `safe/current`, 기존 extractor `hwpx-stdlib` page_count `1`이다. 동봉 HWP는 `붙임.구매규격 사전공개(안).hwp`이다. 기존 구조를 PDF로 덮어쓰지 않고 별도 immutable snapshot으로 연결한다. 35 overview result `a28a188b-0638-4dbb-b867-ea5a12c6c168`와 59 overview result `04d6182f-f073-450a-b8be-30f141db9f02`는 completed/current다. 35 company-fit attempt `bb2d93f4-1915-4e72-a4f5-f647d8860a5e`는 `completed/current/unknown`, 59 company-fit attempt `4af5b488-59c2-445e-8cf3-4a33baad44be`는 `needs_human_review/current/result=null`이다. 59의 `unsupported_number`는 index 0 선택 근거에 24시간이 없어 발생했고 암호화 raw를 보존했으며 보정·재시도하지 않았다. 142는 첫 `conversion_required`, 두 번째 `pdf_preparation_failed`, 마지막 2GiB 실행의 300초 timeout(`attempt=954abd8b-e161-457a-9236-464fb47604ba`, `job=9a8ded11-f357-4847-a534-65be6a0810f8`) 후 미검증으로 확정했으며 성공 snapshot/current로 기록하지 않는다. fsize 256MiB 임시 가설 패치는 원복했고, 해당 worker binding digest는 제품 provenance로 사용하지 않는다. explicit activation은 OFF이며 audit `07c1d75a-c36a-48c7-9de5-a7efa1e741c7` 사유는 `reference_samples_complete_with_142_unverified`다. 운영 DB는 백업 후 0020→0022 migration과 worker 권한 보정을 적용했고, worker는 `bidops-v4-luna-reference:20260909-final`·1GiB 조건으로 복원했다. 실제 UI acceptance는 `.dryforge/prespec-v4-luna-20260909/ui-acceptance-result.json`과 script에 보존했고, automatic company-fit/deep gate와 142 PDF는 남아 있다. 폐기한 provenance 주입용 `/tmp/bidops-v4-freeze-artifacts.py.discarded`는 사용하지 않는다.

마지막 갱신: 2026-09-09 (0020→0022·runtime grant와 35/59 실제 API/UI acceptance 완료; 142 미검증·activation OFF·automatic deep pending)
