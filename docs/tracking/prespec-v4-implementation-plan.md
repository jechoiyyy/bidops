# 사전규격 v4 페이지 개요·회사 핏 연속 처리 구현 계획

기준일: 2026-09-08  
상태: 진행 중  
정본: 이 문서는 현재 구현의 단계·인수 기준·중단 경계를 보존한다. 단계 시작과 컨텍스트 복구 때 다시 읽는다.

## 목표와 범위

`우선 검토` 대상 중 적용 대상이 동결된 문서만 대상으로, 원문에서 검증된 PDF를 먼저 준비하고, PDF의 선택 페이지로 v4 페이지 개요를 실행·검증·저장한다. 현재 승인된 회사 프로필과 대조해 `matched`일 때에만 기존 심층 검토 생성 서비스로 연결한다. 실제 모델 응답이 DB·REST·관리 화면에서 동일한 현재 결과로 보이는 것까지를 목표로 한다.

다음 경계는 유지한다.

- 발주계획 선별, 추적 승인, 최종 입찰 Go/No-Go는 건드리지 않는다.
- 기존 legacy 개요·사람 리뷰·심층 리뷰를 덮어쓰거나 자동 재실행하지 않는다.
- 참조 실행은 `unmeasured_reference`를 유지하며 품질 측정·운영 정책 활성화 근거로 승격하지 않는다.
- 기본 비활성·scheduler 비활성·hosted fallback 금지·실제 외부 호출 승인 경계를 유지한다.
- PDF 검증이 실패하면 v4 자동 실행과 후속 회사 핏·심층 시작을 중단하고 사람 확인 상태로 남긴다.

## 최소 변경 접근과 재사용 지점

새 범용 실행 엔진·플러그인·설정 프레임워크·재시작 UI·일반 기록 테이블을 만들지 않는다.

1. 기존 `DocumentProcessor`의 non-root quarantine 경계, vendored `rhwp`, 기존 제한 subprocess, PDF 구조 추출과 `DocumentBundleService`/`document_structure`를 재사용한다. 필요한 것은 HWP/HWPX 원본과 변환 PDF를 구분하고 PDF 페이지·텍스트 대응을 불변 객체로 저장하는 최소 계약이다.
2. 기존 `prespec_page_overview`, `PreSpecOverviewRunner`, `app/core/model_client.py`, overview 용도 binding·lease·raw 응답 암호화 저장·공유 validator를 재사용한다. v4 policy/few-shot만 정규 정책으로 옮기고 기존 legacy 결과 경로는 보존한다.
3. 기존 회사 핏 서비스·합성 analysis worker의 단일 슬롯·자동 심층 생성 게이트를 확장해 v4 결과와 현재성 검사를 연결한다. 회사 핏/심층 전용 일반 엔진은 추가하지 않는다.
4. 기존 목록·상세 REST projection과 React 페이지 개요·회사 핏 화면을 확장한다. 서버가 선택한 현재 결과와 진행 상태를 투영하고, 화면은 재요약·임의 절단 없이 렌더링한다.
5. DB는 현재 head 뒤 migration만 추가한다. 기존 구조로 불변 PDF snapshot, 적용 대상, attempt, 정책 적용 이력을 안전하게 표현할 수 있으면 새 테이블을 만들지 않는다. 새 구조가 필요한 경우에도 실제 조회·불변성·재시작 fence에 필요한 최소 열과 제약만 둔다.

## 단계와 체크리스트

### 0. 기준선·실행 경계 확인

- [x] 저장소 지침, 상태·업무 규칙·계약·보안·운영 문서와 backend/web AGENTS를 읽었다.
- [ ] 현재 `bidops-web-1`, `bidops-overview-actual`, `bidops-prespec-actual` 컨테이너의 역할과 작업 중복을 확인한다. 운영 서비스 재시작·정책 활성화·live 호출은 하지 않는다.
- [ ] 기존 `R26BD00271191` 필수 표본과 현재 DB 관측 시각/첨부 이력을 확인한다. `DocumentVersion.created_at`만으로 신규를 판정하지 않는다.
- [ ] 현재 작업트리의 baseline 변경과 이 계획에서 직접 수정한 파일을 분리해 기록한다.

인수 기준: 운영 상태 변경 없이 현재 head·migration·권한·서비스 역할·필수 표본의 관측 근거를 확인하고, 기존 회귀 실패를 새 실패로 분류할 수 있다.

### 1. PDF 선행 변환·페이지 대응

- [x] HWP/HWPX를 bytes-only로 받아 non-root document worker에서 vendored rhwp 페이지 SVG를 생성하고 Chromium 인쇄로 PDF를 만든다. 네트워크·자격증명·호스트 파일 확장을 허용하지 않는다. `labor_template.hwp`와 vendored export로 만든 정상 HWPX가 별도 검증 이미지에서 실제 통과했으며, 실표본 RFP HWPX는 snapshot 단계에 남아 있다.
- [ ] HWP/HWPX 원본, 변환 설정·글꼴/renderer 버전, PDF bytes/hash/page count/page text를 각각 불변 object/version으로 보존한다. 동일 원본·설정 성공 PDF는 재사용하고 덮어쓰지 않는다.
- [x] 변환 PDF의 실제 페이지 수·텍스트 추출·한글·주요 표·금액·페이지 대응을 검사한다. `labor_template.hwp`의 2개 물리 페이지에서 모두 통과했고, 빈 텍스트·이미지화·페이지 대응 불가·표 관계 불명확·제한 초과는 `needs_human_review`/실패로 남긴다. 정상 공백 페이지는 보존하고 경고만 남긴다.
- [x] HWPX 구조에 가짜 PDF page를 붙이지 않는다. 기존 HWP→HWPX만 성공한 경로는 PDF 준비 완료로 취급하지 않는다. `rfp.hwpx` 최소 fixture는 렌더 표본으로 사용하지 않았다.
- [x] 기존 입력·압축 해제·페이지·출력 안전 한도와 부분 파일 정리를 유지하고, rhwp와 Chromium은 하나의 작업 deadline을 공유한다. SVG/HTML 합계에도 출력 예산을 적용하며 child마다 별도 300초를 부여하지 않는다.

인수 기준: 현재 검증된 HWP/HWPX 표본과 생성 PDF의 PDF 입력 경로는 실제 페이지·텍스트 대응을 통과했고, 실패 입력은 자동 실행 대상에서 제외된다. PDF byte hash는 Chromium 실행 시각 metadata로 실행마다 달라질 수 있어 text/page hash와 설정·원본 결속을 보존해야 한다. 실표본 RFP HWPX snapshot과 불변 PDF snapshot/sidecar 영속화가 완료되기 전에는 v4 자동 실행을 활성화하지 않는다.

검증 근거: [2026-09-08 PDF 선행 검증 기록](../validation-runs/20260908-prespec-pdf-preflight.md). SVG 생성과 Chromium 인쇄는 통과했으며, worker scratch 결과에 PDF bytes/metadata를 영속화하는 연결은 다음 단계로 남긴다.

이번 단계의 safe 검증 요약: `compileall` 통과, vendored `SHA256SUMS` manifest 검사
통과, `labor_template.hwp` SVG 2페이지 생성 통과, 동일 표본 Chromium PDF 2 physical
pages·한글·금액/숫자·표 형태 text 대응 통과. PDF bytes/metadata scratch sidecar와
정상 HWPX export와 생성 PDF의 PDF 입력 경로는 통과했으며, 실표본 RFP HWPX snapshot과 PDF bytes/metadata scratch sidecar는 미완료다.

### 2. PDF 계약·범위 선택·입력 동결

- [ ] scratch 요청은 버전이 구분된 제한 파일과 크기/hash만 전달하며 PDF bytes를 JSON에 넣지 않는다. 경로 이탈·symlink·부분 파일을 차단한다.
- [ ] 대표 문서 선택 규칙을 재사용한다. 제안요청서 파일명이 없거나 모호하면 사람 확인으로 보내고 임의 대표 문서를 고르지 않는다.
- [ ] PDF 제목·문단과 기존 제목 규칙으로 사업 개요·목적·범위·주요 과업 절을 선택한다. 상위 제목 문맥을 포함하고, `감리대상 사업` 개발 내용을 이번 감리 과업으로 바꾸지 않는다.
- [ ] 선택 페이지 본문·경계·표 관계·입력 한도를 동결한다. 정상적으로 여러 PDF 페이지에 걸친 범위는 필요한 모든 페이지를 포함하고, 경계나 표 관계가 불명확할 때만 사람 확인으로 보낸다. 전체 문서 fallback·임의 절단·공고 메타데이터의 PDF 사실 대체를 하지 않는다.
- [ ] 예산·기간이 원문에 없으면 `unknown`/확인 항목으로 유지한다.

인수 기준: 입력 manifest가 대상 문서 version·원문 hash·PDF hash·페이지 수·선택 페이지·텍스트 hash·범위 사유를 재현하고, 선택 밖 페이지의 사실을 모델 payload에 넣지 않는다.

### 3. v4 정책·실행·저장

- [ ] 실험 `policy.json`의 지시문/few-shot/generation을 정규 overview 정책에 이관하고 `prompt-v4.md` 일치 테스트를 추가한다. 출력 계약은 `bidops.prespec-overview-page-review.v3`를 유지한다.
- [ ] 실행에 policy 전문/digest, prompt version, generation, model name/revision/digest, input/PDF hash를 묶는다. 하드코딩 digest·실험 run 폴더 의존을 제거한다.
- [ ] `overview` 용도 승인 ModelClient만 사용하고 허용 host·64자 revision·승인 설정을 호출 전에 확인한다. v4 retry 0, timeout 300초, lease 600초, 단일 analysis 슬롯을 유지한다.
- [ ] 동일 대상의 legacy/v4 중복 예약과 동일 입력 중복을 막고, 재시작은 새 attempt로만 한다. running stale는 자동 성공/무한 resume하지 않는다.
- [ ] 응답을 암호화 저장하고 페이지·숫자·금액 역할·필수 schema를 공유 validator로 검증한다. schema/근거 실패는 raw 응답 보존 후 실패 attempt로 닫고 정상 결과를 강제 삽입하지 않는다.
- [ ] 정책 변경·문서 변경·profile 변경은 과거 결과를 변경하지 않고 새 이력으로 남긴다.

인수 기준: 실제/통제 응답이 올바른 v3 JSON과 선택 PDF 페이지를 통과해야만 `completed`로 저장되고, 잘못된 응답은 `failed`와 raw 보존으로 남는다. API/UI가 임의로 최신 행을 성공으로 가장하지 않는다.

### 4. 적용 대상·이력·조회 projection

- [ ] 정책 적용 기록에는 표본/신규 모드, 활성 기준, policy/model binding, 표본 목록, 활성 시각·기준 이력을 남긴다. 기존 정책/실행 구조로 표현 가능한 내용은 재사용한다.
- [ ] 적용 대상은 활성화 이후 최초 관측 공고 또는 기존 공고의 새 첨부 변경 관측만 허용한다. 동일 content hash 재수집·재변환, 지연 변환 완료는 신규가 아니다. 근거 관측 이력이 없으면 자동 제외한다.
- [ ] Notice 관측 property와 Attachment `created_at`/`last_seen_at` 등 기존 관측 snapshot을 사용한다. DocumentVersion 생성시각을 신규 기준으로 단독 사용하지 않는다.
- [ ] 대상 dry-run, 동결 표본 enqueue, 실패 명시 retry(new attempt) ops 명령/서비스를 기존 worker 경계에 최소 확장한다. 재시작 전용 UI는 추가하지 않는다.
- [ ] overview-pages 조회에 현재 실행 상태·현재 결과 ID·안전 실패 사유를 추가하되 기존 목록·PDF URL 호환성을 유지한다. 현재 결과는 적용 대상 문서·정책 결속과 validator를 확인해 판정한다.
- [ ] GET은 변경/호출을 만들지 않으며 queued/running/failed를 과거 성공으로 숨기지 않는다. status/count/filter/detail 진행 projection과 PG FK·불변·권한을 검증한다.

인수 기준: 범위 밖 공고 전단계는 예약되지 않고, 재수집 중복·stale lease·재시작 중복이 방지되며, API는 현재 결과와 진행/실패를 일관되게 보여 준다.

### 5. 회사 핏·심층 자동 시작

- [ ] v4 적용 대상에는 v4 결과만 사용하고 legacy 권고로 우회하지 않는다. 자동 심층은 `SW사업대상=Y`·`우선 검토`·자동 확정 `ready` bundle·현재성 검증된 v4 개요·현재 회사 핏 `matched`를 모두 만족할 때만 허용한다.
- [ ] v4 개요 사실과 승인 회사 구조정보를 대조하고 `matched|mismatch|unknown|failed|stale|validation_failed`를 별도 이유와 양쪽 근거로 보존한다. `review_analysis`는 사실 근거로 쓰지 않는다.
- [ ] 현재 입력의 `matched`만 기존 DeepReviewService로 연결한다. `mock_reference`는 자동 시작을 차단하며, 승인 설정의 실제 `unmeasured_reference` 참조 실행은 현재성·게이트를 모두 통과한 `matched`일 때 허용한다. 동일 bundle/profile/deep policy는 중복 생성하지 않는다.
- [ ] 사람 추적 결정·사람 리뷰·최종 Go/No-Go는 보존하고 회사 핏 판단과 자동 시작을 서로 대신하지 않는다.

인수 기준: controlled response와 실제 service 조건에서 `matched`만 자동 생성되고 mismatch/unknown/failed/stale/mock은 대기·사람 확인으로 남는다. 자동 시작 여부는 실제 review ID와 감사 이벤트로 판별한다.

### 6. API·UI 연결

- [ ] 목록 선택 상세와 개별 상세가 동일한 최신 v4 projection을 사용한다.
- [ ] 본문 순서는 `business_overview`, `main_tasks`, `budget_and_period`, `important_conditions`, `reviewer_analysis`, `unknowns`, `input_limitations`를 유지하고 빈 값·검증 실패·unknown을 구분한다.
- [ ] legacy는 과거 이력으로 접고, UI가 본문을 재요약하거나 글자 수로 자르지 않는다. 동결 PDF의 실제 페이지 링크와 회사 핏 양쪽 근거·확인사항·심층 결과 ID를 연결한다.
- [ ] 실행 중 polling, 완료 시 목록·본문 동시 갱신, prompt 실행 시각·품질·현재/과거 표시를 제공한다. 기존 `자동 심층 상태 변경하지 않음` 문구는 실제 게이트 의미에 맞춘다.
- [ ] 1280×800·1440×900에서 긴 문장·빈 배열·API 실패·키보드·PDF 링크·사람 결정 보존을 확인한다.

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

검증 근거는 완료된 단계의 실제 명령·결과·시각을 `docs/validation-runs/`에 기록하고 이 문서에서 링크한다. 현재 연결된 선행 근거는 [회사 핏 단계 검증](../validation-runs/20260908-prespec-company-fit.md)과 [PDF 선행 검증](../validation-runs/20260908-prespec-pdf-preflight.md)이며, 후자는 HWP/HWPX 및 생성 PDF의 PDF 입력 경로까지의 근거다. v4 정규 실행·실표본 RFP HWPX snapshot·sidecar 영속화의 근거는 아직 없다.

남은 일은 단계 체크리스트의 미완료 항목으로 관리한다. 단계 완료 시 인수 기준·검증 링크·변경 파일을 갱신한다. 현재 이 PDF 선행 단계에서 직접 수정한 파일은 아래 표에 기록한다. `docs/tracking/status.md`는 이 단계에서 수정하지 않았다. 이후 구현 파일은 변경 시마다 아래에 추가한다.

### 직접 수정 파일 기록

| 단계 | 파일 | 변경 목적 | baseline과 구분되는 검증 |
|---|---|---|---|
| PDF 선행 | `web/Dockerfile` | Chromium·chromium-sandbox·Noto CJK 런타임 의존성 | 검증 이미지에서 Chromium/font/pdfinfo 실행 |
| PDF 선행 | `docker-compose.yml` | document-worker memory/pids cgroup 경계 | Compose runtime 계약 13 passed |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/processor.py` | rhwp SVG→CSP print HTML→Chromium PDF, deadline·출력·페이지 검사 | HWP worker 조건에서 2페이지 PDF 통과 |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/safety.py` | 기존 입력·archive 안전 경계 재사용 | HWPX 경계 회귀 |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/vendor/SHA256SUMS` | vendored renderer 무결성 manifest | manifest 검사 1 passed |
| PDF 선행 | `web/backend/app/deep_review/document_mcp/vendor/rhwp_render_pages.mjs` | 페이지별 SVG 출력 adapter | non-root/network none에서 SVG 2페이지 |
| PDF 선행 | `web/backend/app/deep_review/services/document_converter.py` | 안전 오류·metadata mapping | 관련 worker protocol 검사 |
| PDF 선행 | `web/backend/app/deep_review/services/prespec_attachments.py` | 변환 안전 오류 mapping | 관련 문서 처리 검사 |
| PDF 선행 | `web/backend/tests/deep_review/test_document_mcp.py` | PDF·HWPX archive boundary 회귀 | 34 passed |
| PDF 선행 | `web/backend/tests/app/test_runtime_contract.py` | worker cgroup 계약 회귀 | 13 passed |
| 계획·검증 | `docs/tracking/prespec-v4-implementation-plan.md` | 단계 상태·범위·남은 sidecar 기록 | 문서 기록은 구현/운영 인수 근거가 아님 |
| 계획·검증 | `docs/validation-runs/20260908-prespec-pdf-preflight.md` | 실제 명령·safe metadata·장애·재현 경로 보존 | SVG/PDF pass와 sidecar 미완료를 분리 |

기준선 기록: 앞선 bounded 실행의 명령은 `cd web/backend && .venv/bin/python -m pytest tests/deep_review/test_document_mcp.py tests/deep_review/test_document_worker_protocol.py tests/deep_review/test_document_integrity.py tests/deep_review/test_document_segments.py tests/deep_review/test_prespec_attachment_assets.py tests/deep_review/test_prespec_e2e.py tests/app/test_runtime_contract.py -q --tb=short`이며 `116 passed, 5 skipped, 3 warnings`가 보고됐다. 이 단계에서 archive-boundary 회귀 1개를 추가해 무관한 전체 반복은 하지 않았다. 정확한 current focused 검사는 검증 기록에 분리했다. root의 독립 `tests/deep_review/test_document_mcp.py -q --tb=short` 기준선은 PDF 추가 회귀 전 `33 passed`다.

실표본 read-only 관측(다음 snapshot 단계의 입력): notice id `142`, notice key `pre:R26BD00271191`, RFP `별첨.제안요청서.hwpx`, document version `59cbc6ef-53f5-421d-84d0-d97c9185ac09`, 원본 SHA-256 `7cc3b5f3894d984ce641e9462030990cbb4cfc1d6869b18bc9047899a23f4665`, `safe/current`, 기존 extractor `hwpx-stdlib` page_count `1`. 동봉 HWP는 `붙임.구매규격 사전공개(안).hwp`이다. 기존 구조를 PDF로 덮어쓰지 않고 별도 immutable snapshot으로 연결한다. 현재 DB revision `0019_prespec_page_overview` 뒤에는 `0020_prespec_company_fit` 회사 핏 migration이 이미 있으며, snapshot 연결에 필요한 추가 migration은 다음 단계에서 검토한다.

마지막 갱신: 2026-09-08 (PDF container preflight 통과, snapshot sidecar 연결 대기)
