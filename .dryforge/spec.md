# 사양: 첨부문서 심층 검토 Lean v1

> 상태: Lean v1 최종 승인·동결 — `dryforge go` 실행 전 기준선
> 기준일: 2026-08-25
> DB 권위 계약: `docs/deep-review-erd.md`

## 1. 목표

유효 등급이 `우선 검토`인 공고의 모든 첨부를 안전하게 구조화하고, 담당자가 문서
준비 완료를 확인한 뒤 로컬 Qwen 분석을 실행한다. 웹 보고서의 모든 중요 사실·수치·계산은
실무자가 원문 위치까지 확인할 수 있어야 한다.

Lean v1은 이 핵심 흐름만 완결한다. 운영 control plane, 관리 UI와 미래 인증을 동시에
구현하지 않는다.

## 2. 범위

### 2.1 포함

- SQLite 13개 테이블의 PostgreSQL 전량 이관과 reconciliation
- HWP 원본 보존 및 headless HWPX 변환, HWPX, text/scanned PDF, 이미지의 격리 처리와 OCR
- MIME/magic/archive/PDF/ClamAV 안전 검사와 quarantine
- 첨부 역할·효력일·대체·최신본 확인 및 immutable ready bundle
- immutable company profile/policy seed version과 분석 입력 고정
- Qwen 3단계 분석, 주장·근거·계산 검증
- immutable full report revision, 사람 수정, 재검증과 최종 의견
- 원문 page/paragraph/table cell/bbox 이동이 가능한 웹 보고서
- PostgreSQL/MinIO 독립 백업 runbook과 SQLite cutover

### 2.2 단계 2로 제외

- Langfuse self-host stack과 trace UI
- profile/policy 생성·복제·활성화 웹 UI/API
- URL evidence capture/SSRF fetcher
- 수동 malware release
- 인앱 OCR text correction
- deep review 간 claim diff와 사람 수정 가져오기
- 범용 retention purge/hold 및 backup checkpoint DB control plane
- SSO identity/attribution schema
- 전문검색/vector/partitioning/table-cell 별도 projection

제외 항목은 구현자가 편의상 선구현하지 않는다.

## 3. 기존 계약과 우선순위

- 기존 수집·사람 검토 API와 결과 계약을 깨지 않는다.
- 사람 정정 등급이 시스템 등급보다 우선한다.
- 애플리케이션 정본 DBMS는 PostgreSQL 17이고 SQLite는 일회성 이관 원본이다.
- 메인 워크트리의 미커밋·미추적 파일은 사용자 소유이며 읽기 전용 참고만 허용한다.
- 이 사양과 `docs/deep-review-erd.md`가 이번 기능의 권위 계약이다.
- OpenAI 호출은 v1 범위에 없고 기본 비활성 상태를 유지한다. 분석은 고정된 로컬 Qwen
  endpoint만 사용한다.

### 3.1 이름-only 경계

- 화면에서 받은 이름은 `claimed_name`이며 인증이나 권한 증명이 아니다.
- 조회는 사내망 익명을 허용하고 모든 mutation은 `X-BidOps-Actor-Name`을 요구한다.
- 서버는 길이·공백·제어문자를 검증한 이름 snapshot을 각 mutation 행과 audit에 직접 저장한다.
- 같은 이름을 UUID actor로 합치지 않는다. 이름이 같은 사람과 타인 이름 입력을 구분하지 못한다.
- 모든 이름 입력 사용자는 같은 변경 권한을 가진다. 외부 공개는 인증 도입 전 금지한다.
- worker는 내부 `system` attribution을 사용하며 HTTP에서 system을 선택할 수 없다.
- 향후 인증은 검증된 subject의 새 actor를 만들고 과거 이름 행을 재작성·자동 병합하지 않는다.

## 4. 핵심 도메인 규칙

### 4.1 대상 공고

`effective_grade = latest_human_corrected_grade ?? latest_system_grade`

- `effective_grade == "우선 검토"`일 때만 새 bundle과 deep review를 만들 수 있다.
- 분석 시작 시 등급과 근거 run/review ID를 snapshot한다.
- 시작 후 등급 변경은 과거 결과를 바꾸지 않지만 새 분석에는 현재 등급을 적용한다.

### 4.2 content, document와 attachment

- 같은 bytes는 하나의 `content_object`, 각 업무 등록은 별도 `document_version`이다.
- provider attachment는 안정 source key로 식별하고 수동 upload는 이름/URL로 deduplicate하지 않는다.
- 저장 bytes가 없는 provider attachment는 `source_system`별 allowlist connector만 취득한다.
  사용자가 임의 URL을 입력하는 fetch 기능은 없으며 host/TLS/redirect/DNS-IP/timeout/50 MiB를
  제한하고 최초 bytes는 반드시 quarantine으로 보낸다.
- attachment는 hard delete하지 않고 retirement로 관리한다.
- document version은 source URL/key/filename, bytes hash, 역할·효력일·대체관계와 안전 상태를
  자체 snapshot한다.
- 새 파일·정정 파일·새 OCR 결과는 기존 행을 덮지 않고 새 document version을 만든다.

### 4.3 안전 검사

처리 순서:

1. 파일당 최대 50 MiB와 HWP/HWPX/PDF/지원 이미지 확장자 allowlist
2. magic bytes와 MIME 일치
3. HWPX/ZIP 압축 해제 크기·파일 수·중첩·path traversal
4. PDF 암호화·손상·과도한 object 검사
5. ClamAV
6. 격리 subprocess/문서 처리기에서 구조 추출

- 최초 bytes는 quarantine namespace에만 쓴다.
- 모든 검사를 통과한 bytes만 source namespace에 새 location으로 기록한다.
- ClamAV 미가용·불확실·실패는 quarantine이다. v1에는 수동 해제가 없다.
- quarantine object를 viewer, Qwen 또는 일반 download API에 노출하지 않는다.

### 4.4 구조화와 OCR

- 전체 `bidops.document-structure.v1` JSON이 구조 정본이다.
- PostgreSQL `document_block`은 locator 조회 projection이다. page metadata와 table cell
  row/column은 payload/block attributes에 저장한다.
- HWPX는 paragraph/table/cell key, PDF/OCR은 page/bbox/text range를 보존한다.
- scanned 문서는 page image와 OCR confidence를 보존한다.
- HWP 원본 bytes는 그대로 보존하고 격리된 headless 변환기로 HWPX를 만든 뒤 구조화한다.
  변환 실패는 `변환 확인 필요` blocking issue이며 HWP 원본을 Qwen에 직접 전달하지 않는다.
- 낮은 confidence는 확정 사실이 아니며 bundle issue 또는 report unknown으로 표시한다.
- OCR 오류는 정정 파일 재업로드로 새 document version을 만든다. v1 화면에서 text를 직접
  고치지 않는다.

### 4.5 문서 묶음

상태:

`draft -> processing -> needs_review -> ready`

실패/대체 상태:

`quarantined | failed | superseded`

- upload 직후가 아니라 담당자의 명시적 `문서 준비 완료` 확인이 분석 시작 조건이다.
- 시스템은 역할·효력일·대체관계·최신본과 OCR issue를 제안한다.
- unresolved blocking issue, quarantine, 구조 실패가 하나라도 있으면 ready를 거부한다.
- ready confirmation은 bundle/document/structure를 잠근 한 트랜잭션에서 수행한다.
- ready item은 content/structure hash, MIME/size/filename/source, 역할·날짜·대체·최신본,
  safety 상태를 확인 시점 snapshot으로 고정한다.
- 새 첨부·정정 파일은 새 bundle을 만들고 이전 bundle/report를 보존한다.
- bundle은 확인 시점의 모든 non-retired attachment를 다뤄야 한다. provider 원문 취득 실패,
  누락 bytes 또는 source 변경은 blocking issue이며 담당자가 대체 파일을 등록하거나 근거 있는
  retirement를 확정하기 전에는 ready가 될 수 없다.

### 4.6 company profile과 policy

- 기존 company profile Markdown을 최초 immutable `profile_version`으로 import한다.
- v1 profile evidence는 안전 검사된 업로드 파일, locator, quote, fact key와 확인 이름을 가진다.
- profile payload 안의 모든 회사 역량 사실은 evidence 또는 명시적 unknown이어야 한다.
- URL evidence는 v1에 없다.
- model endpoint reference, model name, 3단계 prompt와 validation rule은 한 immutable
  `analysis_policy_version`에 저장한다.
- active profile/policy ID는 배포 설정으로 지정하고 deep review 생성 시 hash와 함께 고정한다.
- 변경은 server import CLI로 새 version을 만들며 웹 관리 화면은 없다.
- v1 심층 분석 기준은 배포 운영자 소유 설정이며 사용자 편집 기능이 아니다. 향후 사용자
  편집을 제공할 때는 관리 화면에서 저장할 때마다 새 immutable version을 생성한다.
- policy 후보는 고정 표본에서 필수 항목 재현율 80% 이상, 사람 판정 일치율 70% 이상,
  근거 부족 오판율 10% 이하를 충족해야 active 설정으로 지정할 수 있다. 표본 hash와 측정
  결과를 policy 검증 metadata로 남긴다.

### 4.7 deep review와 attempt

- `deep_review`는 notice/bundle/profile/policy 조합의 논리 분석이다.
- `deep_review_attempt`는 실행·재시도 단위다.
- unique `(notice_id, bundle_id, profile_version_id, policy_version_id)`.
- queued/running attempt는 한 review에 하나만 허용한다.
- 같은 입력 재실행은 기존 review 아래 새 attempt다. 입력이 바뀌면 새 review다.
- 이전 사람 수정·최종 의견을 새 review에 자동 승계하지 않는다.

분석 단계:

1. `requirements_and_evaluation`: 자격, 요구사항, 제출물, 일정, 평가·배점
2. `delivery_risk_economics`: 수행 방안, 위험, 회사 역량, 금액·경제성
3. `synthesis_and_validation`: 종합 권고, unknown/충돌 정리, 권위 schema 검증

3개 stage는 업무상 결과 경계이며 모델 호출 횟수가 아니다. 요구사항 ID와 locator를 먼저
결정적으로 고정하고, 문서·요구사항 단위의 제한된 input slice를 여러 bounded invocation으로
처리한 뒤 schema 검증을 통과한 결과만 병합한다. 전체 원문을 한 번에 보내는 거대 prompt는
금지한다. 문서 변환·OCR은 분석 단계 안에서 다시 수행하지 않는다.

### 4.8 주장과 근거

claim type:

- `fact`: 직접 근거 필수
- `calculation`: 식과 모든 입력값 근거 필수
- `inference`: 같은 review의 premise claim, 근거와 추론 설명 필수
- `opinion`: 사유 필수
- `unknown`: 근거 부족·충돌을 명시

- 자격·요구사항·제출물·일정·금액·배점·위험·회사 역량의 근거 누락은 validation 실패다.
- document evidence는 deep review의 ready bundle snapshot 밖을 인용할 수 없다.
- profile evidence는 deep review가 고정한 profile version 밖을 인용할 수 없다.
- evidence locator는 content/source hash와 함께 저장한다.

### 4.9 보고서와 최종 의견

- 최초 machine 결과는 `report_revision(origin="machine")`의 완전한 immutable JSON이다.
- 사람 수정도 parent revision을 가리키는 완전한 immutable JSON snapshot이다.
- delta overlay chain과 별도 machine report 테이블은 만들지 않는다.
- factual change는 reason과 evidence가 필수이며 새 validation run을 만든다.
- validation result는 revision마다 append-only로 남긴다.
- 보고서는 최소한 프로젝트 기본정보, 참가 자격 matrix, 범위·산출물, 요구사항 대응 matrix,
  평가·배점 matrix와 제안 전략, 수행 계획 초안, 기술·연계 위험, 보안·법률·계약 위험,
  경제성 시나리오, 경쟁·제안 전략, 질문·내부 조치, 문서 묶음·한계를 포함한다.
- 위험 심각도는 `차단|중대|보통|낮음`, system recommendation은
  `추진 검토|조건부 추진 검토|보류|검토 종료`다. 한 화면 decision card에는 recommendation,
  핵심 근거, 차단 위험, 미확인 사항과 다음 조치를 요약한다.
- 사람 최종 의견은 `추진|조건부 추진|보류|검토 종료`다.
- final opinion은 대상 revision, 실제 validation run/status, sequence, claimed name과 reason을 고정한다.
- validation 실패 상태에서도 명시적 acknowledgement와 reason 후 의견을 남길 수 있지만 실패
  label은 유지한다.

## 5. 권위 JSON 계약

구현 시 `web/backend/app/contracts/deep_review/`에 다음 JSON Schema를 둔다. 모든 schema는
기본적으로 `additionalProperties: false`, UUID 문자열, timezone 포함 RFC 3339를 사용한다.

### 5.1 `bidops.document-structure.v1`

필수 상위 필드:

`schema, structure_id, document_version_id, source_sha256, media_type, extractor, pages,
blocks, warnings, created_at`

- extractor: `name, version, upstream_commit|null`
- page: `number, width, height, image_content_object_id|null`
- block: `block_key, parent_block_key|null, type, page, bbox|null, text, confidence|null,
attributes`
- table cell은 block type과 `attributes.table_key/row/column`으로 표현한다.

### 5.2 `bidops.document-bundle.v1`

필수 상위 필드:

`schema, bundle_id, notice_id, revision, status, documents, issues, confirmed_by,
confirmed_at, created_at`

ready document item은 ERD의 모든 snapshot 필드를 포함한다.

### 5.3 `bidops.deep-review-stage.v1`

필수 상위 필드:

`schema, deep_review_id, attempt_id, stage, claims, unknowns, warnings`

claim은 `claim_id, category, claim_type, body, status, formula|null, premise_claim_ids,
reason|null, evidence_ids`를 가진다.

### 5.4 `bidops.deep-review-report.v1`

필수 상위 필드:

`schema, deep_review_id, notice_id, bundle_id, profile_version_id, policy_version_id,
sections, system_recommendation, claims, unknowns, validation_summary, created_at`

보고서 HTML은 이 JSON projection이며 직접 편집하지 않는다.

### 5.5 `bidops.deep-review-validation.v1`

필수 상위 필드:

`schema, validation_run_id, report_revision_id, status, checks, created_at`

check는 `check_type, status, severity, message, related_claim_ids, related_evidence_ids`다.

DB 저장 전 다음을 결정적으로 검증한다.

- ID/enum/type/additional field
- claim/evidence 소속과 locator 해소
- fact evidence, calculation 식·입력, inference premise
- duplicate/dangling/cyclic reference
- source hash와 bundle/profile scope
- validation-failed final opinion acknowledgement

## 6. 제한형 문서 처리기

- `hwpx-skill` commit `96a2633f23a08f707679d7e212ebdc59948260e6`을 고정한다.
- 사용자는 필요한 코드 사용·수정 허락을 확보했다. 저작권과 제3자 고지는 보존한다.
- 구현은 별도 subprocess/container 또는 같은 수준의 격리 경계에서 실행한다.
- 공개 동작은 bytes 입력, media type, 제한된 options와 구조 JSON 출력뿐이다.
- 임의 local path, URL, shell, output path를 받지 않는다.
- CPU/memory/time/output/file count/archive depth를 제한하고 network를 차단한다.
- 비밀, storage credential과 DB write 권한을 주지 않는다.

필수 처리:

- HWP 원본 보존과 격리 headless HWPX 변환
- HWPX paragraph/table/cell 추출
- text PDF page/bbox 추출
- scanned PDF/image OCR
- page render

## 7. API 계약

### 7.1 공통

- 모든 mutation은 `X-BidOps-Actor-Name`을 요구한다.
- upload, bundle confirm, deep review create/retry, report revision, final opinion은
  `request_id: UUID`를 요구한다.
- 같은 operation/aggregate/claimed-name/request ID와 같은 request hash는 최초 응답을 재현한다.
  다른 hash는 `409 idempotency_conflict`다.
- optimistic concurrency가 필요한 bundle/document/revision mutation은 body `version` 또는
  `If-Match`를 사용한다.
- 오류는 원문·내부 경로·prompt·비밀을 포함하지 않는 stable code와 안전한 message다.

### 7.2 문서와 bundle

- `GET /api/notices/{notice_id}/document-bundles`
- `POST /api/notices/{notice_id}/document-bundles`
- `POST /api/document-bundles/{bundle_id}/documents` multipart upload
- `PATCH /api/document-versions/{document_version_id}`
  - role, effective_date, replaces_document_version_id, is_current, version
- `POST /api/document-bundles/{bundle_id}/confirm`
  - request_id, version, confirmed_documents
- `GET /api/document-structures/{structure_id}`
- `GET /api/document-structures/{structure_id}/pages/{page}`

manual release와 OCR correction endpoint는 없다.

### 7.3 deep review와 report

- `POST /api/notices/{notice_id}/deep-reviews`
  - request_id, bundle_id; profile/policy는 서버 active config로 resolve
- `GET /api/deep-reviews/{deep_review_id}`
- `POST /api/deep-reviews/{deep_review_id}/attempts`
- `GET /api/deep-reviews/{deep_review_id}/report`
- `POST /api/deep-reviews/{deep_review_id}/report-revisions`
  - request_id, base_revision_id, full report payload, reason
- `POST /api/deep-reviews/{deep_review_id}/final-opinions`
- `GET /api/evidence/{evidence_id}`

compare, import, profile/policy 관리 endpoint는 없다.

## 8. 웹 화면

### 8.1 공고 상세/문서 준비

- 유효 등급과 심층 검토 가능 여부
- attachment별 안전·구조화·역할·효력일·최신본 상태
- blocking issue와 원문 위치
- 파일 등록, 문서 metadata 확인, 준비 완료
- 새 파일 등록 시 이전 bundle/report 보존과 새 bundle 안내

### 8.2 분석·보고서

- 3단계 상태와 안전한 실패 코드
- 구조화 보고서, 시스템 권고, unknown/validation 경고
- 한 화면 decision card와 자격·요구사항·평가 matrix, 수행 계획·경제성 시나리오
- claim의 원문 page/paragraph/table cell/bbox 이동
- 원문, 추출 text, OCR confidence와 source hash 표시
- full snapshot revision 생성과 이력
- 시스템 권고와 분리된 사람 최종 의견

profile/policy 관리, cross-review diff, OCR 직접 수정 화면은 없다.

## 9. worker·동시성

- PostgreSQL `FOR UPDATE SKIP LOCKED`로 짧게 job을 claim한 뒤 commit한다.
- active job/attempt partial unique를 둔다.
- claim/reclaim마다 fence를 증가시키고 현재 owner/fence와 일치하는 조건부 SQL로만 stage/report를
  저장한다.
- 모델·OCR 실행 동안 DB transaction을 열어 두지 않는다.
- 초기 동시성은 analysis worker 1, document worker 2다.
- fence 전용 stored function과 table별 세분 DML revoke는 v1에 없다.

## 10. 저장소·보존·복구

- bucket/namespace는 `bidops-source`, `bidops-structure`, `bidops-quarantine`,
  `bidops-model-response`로 분리한다.
- 목적별 credential을 분리하고 API/worker에 source/structure delete 권한을 주지 않는다.
- 정본 데이터는 자동 삭제하지 않는다.
- raw model response bytes만 암호화 상태로 기본 90일 lifecycle을 적용한다. 기간은
  `BIDOPS_MODEL_RESPONSE_RETENTION_DAYS`로 변경하며 hash와 structured output은 남긴다.
- 범용 retention purge/hold 테이블과 web purge API는 없다.
- RPO 4시간, RTO 8시간. PostgreSQL daily full + continuous WAL, object version-aware copy를
  최소 4시간 간격으로 독립 장애 도메인에 보관한다.
- backup 보존은 daily 14일, weekly 8주, monthly 6개월이다.
- object 먼저 복원, PostgreSQL 복원, active location SHA-256 대조 순서다.
- production 전 1회, 이후 분기별 전체 restore drill을 운영 runbook으로 수행한다.
- backup 상태는 외부 도구/alert가 관리하며 앱이 자동 read-only로 전환하지 않는다.

## 11. PostgreSQL·이관

- PostgreSQL 17 current minor/image digest를 고정하고 추가 extension 없이 migration한다.
- database `bidops`, schema `bidops`, role은 owner/migrate, app, worker, ro_backup 네 경계다.
- SQLite backup → `migration_staging` → row/key/file/hash reconciliation → read-only 검증 →
  cutover 순서다.
- 모든 legacy 컬럼과 integer PK를 보존하고 sequence를 보정한다.
- PostgreSQL 쓰기 개방 뒤 SQLite로 단순 rollback하지 않는다.
- object bytes를 먼저 기록·검증한 뒤 DB ref를 commit한다.

## 12. 보안·관측

- quarantine bytes, prompt, 원문 전체, 비밀, 내부 path를 로그에 남기지 않는다.
- download는 safe MIME, `Content-Disposition`, CSP와 `nosniff`를 적용한다.
- document processor와 Qwen에 storage credential/임의 URL/path를 주지 않는다.
- provider connector만 source별 allowlist outbound 권한을 가지며 문서 처리기와 Qwen은 network가 없다.
- DB의 stage invocation metadata와 audit event로 상태, latency, token, error code를 관측한다.
- Langfuse는 단계 2 선택 사항이며 장애나 미설치가 분석을 막지 않는다.
- 사내망 경계가 없으면 인증 도입 전 서비스를 외부에 노출하지 않는다.

## 13. 검증과 완료 조건

필수 검증:

- 기존 backend/frontend 회귀
- SQLite 모든 컬럼·row/key/reviewer/file hash reconciliation
- PostgreSQL FK/check/unique/partial unique와 concurrent job/attempt
- 악성 MIME, EICAR, archive bomb, traversal, encrypted/corrupt PDF, ClamAV 미가용
- HWP→HWPX/text PDF/scanned PDF/image 구조 contract와 50 MiB 제한
- URL-only provider 첨부의 allowlist 취득, redirect/DNS-IP 재검증과 실패 시 ready 차단
- ready 전 분석 차단과 새 file의 새 bundle/review 계보
- bundle/profile 밖 evidence 거부
- 근거 없는 fact, 식 없는 calculation, cycle/dangling premise 거부
- full report revision concurrency와 factual edit 재검증
- validation 실패 acknowledgement와 final opinion snapshot
- object/DB restore 및 active hash 검증
- 두 pilot의 55/52 수치 차이와 평가 의무 누락 회귀
- 고정 표본 policy 품질 기준과 stage 내부 청킹·병합 회귀

완료 명령:

- `./run-tests.sh`
- `./web/run-web-tests.sh`
- `web/backend/.venv/bin/pytest web/backend/tests`
- `cd web/frontend && npm run build`
- `git diff --check`

완료 판단:

준비 완료된 `우선 검토` 공고 하나에서 안전 검사, 담당자 ready 확인, 3단계 Qwen 분석,
모든 중요 claim의 원문 이동, 사람 full revision 재검증, 최종 의견, 새 file 이후 과거 보존과
새 계보가 모두 재현되어야 한다. 하나라도 실패하면 완료가 아니다.
