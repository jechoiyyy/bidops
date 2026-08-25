# 실행 계획: 첨부문서 심층 검토 Lean v1

> 상태: Lean v1 최종 승인·동결 — `dryforge go` 대기

모든 경로는 `bidops-agent/` 기준이다. `.dryforge/spec.md`와
`docs/deep-review-erd.md`의 Lean v1 경계를 지킨다. 단계 2 항목을 선구현하지 않는다.

## T1. PostgreSQL 모델과 SQLite 이관

- **목표**: 기존 데이터 전량 보존과 Lean v1 신규 25개 테이블의 DB 기반을 만든다.
- **의존성**: 없음
- **작업 대상**:
  - `web/backend/app/models.py`
  - `web/backend/app/db.py`
  - `web/backend/alembic.ini`, `web/backend/alembic/` 신규
  - `web/backend/app/migrations/import_sqlite.py` 신규
  - `web/backend/tests/test_deep_review_migrations.py` 신규
- **구현**:
  - PostgreSQL 17, database/schema `bidops`, app-generated UUID와 text+check 상태를 사용한다.
  - 기존 13개 테이블의 모든 컬럼·integer PK와 reviewer snapshot을 보존한다.
  - attachment retirement와 안정 source key partial unique를 추가한다.
  - ERD의 document 8, knowledge 3, analysis 11, ops 3개 테이블만 추가한다.
  - claimed name을 mutation 행에 직접 저장하고 `actor` 테이블은 만들지 않는다.
  - ready bundle snapshot, active attempt/job partial unique, evidence scope composite FK,
    full report revision과 final-opinion validation check를 구현한다.
  - 기본 FK는 RESTRICT, 판정 내부 detail/verification answer만 제한 CASCADE,
    attachment 보조 FK만 SET NULL이다.
  - `migration_staging` import/reconciliation과 sequence `setval`을 구현한다.
- **검증**:
  - clean PostgreSQL 17에서 추가 extension 없이 migration
  - 모든 legacy 컬럼·row count·PK/FK·reviewer·file size/hash reconciliation
  - 미등록 legacy 컬럼 발견 시 import 중단
  - partial unique, composite FK, final opinion check, attachment retirement
  - app 서비스가 immutable 행을 제자리 수정·삭제하지 않는 회귀
- **위험**: `RISKY` — SQLite 정본 전환과 전체 모델 변경

## T2. 격리 문서 처리기

- **목표**: HWP 원본을 안전하게 HWPX로 변환하고 HWPX/PDF/image를 제한된 입력으로 구조화한다.
- **의존성**: 없음
- **작업 대상**:
  - `web/backend/app/document_mcp/` 신규
  - `web/backend/tests/test_document_mcp.py` 신규
  - `web/backend/tests/fixtures/documents/` 신규
- **구현**:
  - `hwpx-skill` commit `96a2633f23a08f707679d7e212ebdc59948260e6`을 고정한다.
  - HWP 원본을 보존하고 격리된 headless 변환기로 HWPX를 만든다. 변환 실패는
    `변환 확인 필요`로 차단하며 원본 HWP를 Qwen에 직접 전달하지 않는다.
  - HWPX paragraph/table/cell, PDF page/bbox, image/scanned PDF OCR와 page render를 구현한다.
  - bytes/media type/options만 받고 path/URL/shell/output path를 받지 않는다.
  - network·resource·timeout·output 크기를 제한하고 storage/DB credential을 주지 않는다.
  - page/cell은 별도 DB projection 없이 structure payload/block attributes로 표현한다.
- **검증**:
  - 정상 HWP→HWPX/HWPX/text PDF/scanned PDF/image fixture
  - traversal/archive bomb/oversize/timeout/malformed output
  - upstream commit, license/third-party notice
- **위험**: `RISKY` — 비신뢰 문서 파싱

## T3. 안전 asset과 문서 bundle

- **목표**: quarantine부터 담당자 ready 확인까지의 단일 문서 준비 흐름을 만든다.
- **의존성**: T1, T2
- **작업 대상**:
  - `web/backend/app/services/assets.py` 신규
  - `web/backend/app/services/document_bundles.py` 신규
  - `web/backend/app/routers/document_bundles.py` 신규
  - `web/backend/app/schemas/document_bundles.py` 신규
  - `web/backend/tests/test_document_bundles.py` 신규
- **구현**:
  - streaming upload, SHA-256, MIME/magic/archive/PDF/ClamAV 검사를 구현한다.
  - bytes 없는 provider attachment는 source-system별 allowlist connector로만 취득한다. TLS,
    redirect host, DNS/IP 재검증, timeout, streaming 50 MiB 제한을 적용하고 quarantine으로 쓴다.
  - quarantine에서 모든 검사를 통과한 bytes만 source location으로 복사·재검증한다.
  - 수동 안전 해제와 인앱 OCR correction은 구현하지 않는다.
  - source/attachment snapshot, document version, structure payload/block projection을 만든다.
  - 역할·효력일·대체·최신본·OCR issue를 계산하고 ready 전 blocking issue를 거부한다.
  - 모든 non-retired attachment의 bytes/structure 포함을 확인하고 취득 실패·source 변경·누락은
    대체 파일 등록 또는 근거 있는 retirement 전까지 ready를 차단한다.
  - ready 확인 transaction이 모든 item snapshot을 고정한다.
  - OCR 오류는 unknown 또는 정정 파일 재업로드로 처리한다.
- **검증**:
  - ClamAV 미가용·EICAR·잘못된 MIME·암호화/손상 PDF quarantine
  - quarantine viewer/Qwen 접근 거부
  - bytes-first/location commit, hash mismatch 중단
  - provider redirect/private IP/oversize/timeout/source 소실과 재취득 hash 변경
  - ready 전 분석 차단, 동시 confirm 충돌, 새 file의 새 bundle
- **위험**: `RISKY` — upload와 원문 계보의 보안 경계

## T4. 권위 schema와 결정적 검증

- **목표**: 문서·bundle·3단계 분석·보고서·validation payload를 모델 출력과 분리해 검증한다.
- **의존성**: T1
- **작업 대상**:
  - `web/backend/app/contracts/deep_review/` 신규
  - `web/backend/app/services/deep_review_validation.py` 신규
  - `web/backend/tests/test_deep_review_contracts.py` 신규
  - `web/backend/tests/fixtures/deep_review/` 신규
- **구현**:
  - spec의 5개 JSON Schema와 additional-properties 차단을 구현한다.
  - claim type별 evidence/formula/premise/reason 규칙을 구현한다.
  - bundle/profile scope, locator/hash, dangling/cycle/duplicate와 계산 재실행을 검증한다.
  - validation check의 관련 ID 배열이 같은 deep review에 속하는지 저장 전에 검사한다.
  - 필수 보고 section, system recommendation·risk severity enum을 schema로 강제한다.
- **검증**:
  - valid/invalid golden fixture
  - 근거 없는 fact, 식 없는 calculation, cycle/dangling premise, bundle 밖 evidence
  - 소방예방 55/52 수치와 양산 평가 의무 누락 회귀
  - stage 내부 청킹 결과의 중복·누락 없는 결정적 병합 회귀
- **위험**: `RISKY` — 잘못된 보고서를 차단하는 최종 경계

## T5. profile/policy seed와 Qwen 3단계 분석

- **목표**: 고정 입력으로 재시도 가능한 3단계 심층 분석을 실행한다.
- **의존성**: T1, T3, T4
- **작업 대상**:
  - `web/backend/app/services/input_versions.py` 신규
  - `web/backend/app/services/deep_reviews.py` 신규
  - `web/backend/app/services/ollama_client.py` 신규
  - `web/backend/app/workers/deep_review.py` 신규
  - `web/backend/app/routers/deep_reviews.py` 신규
  - `web/backend/app/cli/import_profile_policy.py` 신규
  - `web/backend/tests/test_deep_reviews.py` 신규
- **구현**:
  - 기존 company profile Markdown과 초기 policy를 immutable version으로 멱등 import한다.
  - profile evidence는 안전한 file/locator/fact key만 받는 server CLI로 import한다.
  - active IDs는 배포 설정에서 resolve하고 deep review에 고정한다.
  - 고정 표본의 필수 항목 재현율 80%, 사람 판정 일치율 70%, 근거 부족 오판율 10% 이하를
    검증한 policy만 active로 지정하고 표본 hash·측정 결과를 남긴다.
  - 유효 등급/ready bundle/profile/policy를 한 transaction에서 확인한다.
  - deep review/attempt/job을 분리하고 `SKIP LOCKED` + lease fence 조건부 SQL을 사용한다.
  - 3개 업무 stage를 순서대로 실행하되 요구사항 ID/locator를 먼저 고정하고 stage 내부를
    bounded input slice로 나눈다. invocation별 hash/token/latency/error와 결정적 병합 결과를 저장한다.
  - raw model response는 암호화 object로 최대 90일 보존한다.
  - Langfuse 없이 완결하고 external trace 저장에 의존하지 않는다.
- **검증**:
  - 정상, timeout, malformed JSON, 중간 실패/새 attempt, duplicate request
  - active 설정 변경이 이미 시작한 review의 입력 version을 바꾸지 않음
  - stale fence 결과 저장 거부
  - Qwen에 내부 path/credential/전체 불필요 원문을 전달하지 않음
  - 전체 원문 단일 prompt 금지, 큰 문서·55개 이상 요구사항의 청킹/재시도/병합
- **위험**: `RISKY` — 비결정적 모델과 결정적 상태 연결

## T6. 보고서 API와 웹 흐름

- **목표**: 원문 근거를 탐색하고 full revision과 최종 의견을 관리하는 실무 화면을 만든다.
- **의존성**: T5
- **작업 대상**:
  - `web/backend/app/services/reports.py` 신규
  - `web/backend/app/services/evidence.py` 신규
  - `web/backend/app/routers/reports.py` 신규
  - `web/backend/app/schemas/reports.py` 신규
  - `web/frontend/src/pages/DeepReviewPage.tsx` 신규
  - `web/frontend/src/components/deep-review/` 신규
  - 관련 backend/frontend 테스트 신규
- **구현**:
  - machine 결과를 최초 immutable full report revision으로 저장한다.
  - 사람 수정은 parent와 reason을 가진 새 full JSON revision이다. delta overlay를 만들지 않는다.
  - factual change evidence와 재검증, revision optimistic concurrency를 구현한다.
  - validation 실패 acknowledgement와 final opinion snapshot을 구현한다.
  - 공고 상세에 문서 준비 panel, 분석 3단계 진행, report/evidence viewer를 연결한다.
  - page/paragraph/table cell/bbox 이동과 OCR confidence/source hash를 표시한다.
  - 필수 section, 자격·요구사항·평가 matrix, 수행 계획·경제성 시나리오와 한 화면
    decision card를 제공하고 system recommendation과 사람 final opinion을 분리한다.
  - compare/import, profile/policy UI와 OCR 직접 수정 UI는 만들지 않는다.
- **검증**:
  - stale revision, 근거 없는 factual edit, 사유 없는 opinion 거부
  - validation failed label 유지
  - keyboard/focus/narrow viewport/긴 표
  - 새 분석이 이전 사람 revision/opinion을 자동 승계하지 않음
- **위험**: `RISKY` — 근거 탐색과 사람 판단 이력

## T7. 통합·배포·복구

- **목표**: 공용 진입점, PostgreSQL/MinIO/Ollama/ClamAV 설정과 전체 회귀를 통합한다.
- **의존성**: T2, T3, T4, T5, T6
- **공용 파일 단독 소유**:
  - `web/backend/app/main.py`, `routers/__init__.py`, `config.py`
  - dependency manifest, compose/실행 script
  - `web/frontend/src/App.tsx`, routes/api/types/theme
  - architecture/contracts/security/operations 등 기존 문서
- **구현**:
  - PostgreSQL 17 current minor/digest, schema `bidops`, owner/app/worker/ro_backup role을 연결한다.
  - bucket은 source/structure/quarantine/model-response로 분리하고 목적별 credential을 둔다.
  - model-response 90일 lifecycle만 구성하고 범용 purge/hold는 만들지 않는다.
  - Langfuse는 배포 필수 요소에서 제외한다.
  - RPO 4시간/RTO 8시간, daily full+WAL, 4시간 object copy, daily 14/weekly 8/monthly 6
    보존과 object→DB→hash restore runbook을 작성한다.
  - production 전 전체 restore drill을 수행하고 이후 분기별 절차를 문서화한다.
  - claimed-name header, 사내망 경계, log redaction, CSP/download header를 통합한다.
- **검증**:
  - `./run-tests.sh`
  - `./web/run-web-tests.sh`
  - `web/backend/.venv/bin/pytest web/backend/tests`
  - `cd web/frontend && npm run build`
  - document security contract, 두 pilot, browser visual/accessibility
  - SQLite cutover dry run과 PostgreSQL/object restore/hash 검증
  - `git diff --check`, 비밀/원문 로그 누출 점검
- **위험**: `RISKY` — 공용 연결과 cutover

## 실행 그래프

```yaml
tasks:
  T1: {depends_on: []}
  T2: {depends_on: []}
  T3: {depends_on: [T1, T2]}
  T4: {depends_on: [T1]}
  T5: {depends_on: [T1, T3, T4]}
  T6: {depends_on: [T5]}
  T7: {depends_on: [T2, T3, T4, T5, T6]}
```

T1/T2를 병렬 시작하고 T7만 공용 등록 파일을 수정한다.

## 단계 2 금지선

다음 이름의 기능·테이블·endpoint가 v1 diff에 나타나면 별도 승인 없이는 실패다.

- actor/actor_identity/attribution link
- safety release/manual release
- OCR correction endpoint/table
- profile/policy web CRUD·activation event
- machine report + delta report edit chain
- validation check join matrix
- retention purge/hold
- backup checkpoint/restore drill DB table
- Langfuse ClickHouse/Redis/MinIO deployment
- deep review compare/import

## 완료 보고

각 task는 변경 파일, 구현한 계약, 테스트 결과, 환경 의존 실패, 남은 위험과 다음 task 입력을
보고한다. 핵심 흐름 하나라도 재현되지 않으면 완료가 아니다.
