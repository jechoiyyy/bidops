# BidOps 심층 검토 PostgreSQL ERD — Lean v1

> 상태: Lean v1 최종 승인·동결 — 구현·검증 기준 계약
> 기준일: 2026-08-25
> 대상: PostgreSQL 정본 전환, 안전한 첨부 구조화, Qwen 근거 기반 보고서

이 문서는 Lean v1의 DB 권위 계약이다. Mermaid는 관계 개요이고, 본문의 제약·이관
대조·삭제 정책이 실제 Alembic DDL의 기준이다. 기존 SQLite 컬럼은 명시적 승인 없이
폐기하지 않는다.

## 1. 축소 원칙

- PostgreSQL database `bidops`의 단일 application schema `bidops`를 사용한다. 기능별
  다중 schema와 교차 schema 권한 설계는 v1에 도입하지 않는다.
- 기존 13개 SQLite 테이블을 전량 이관하고 신규 테이블은 25개로 제한한다.
- 사람 식별은 인증되지 않은 이름 문자열뿐이다. v1에는 `actor` 테이블을 만들지 않고
  mutation 행에 `claimed_name` snapshot을 직접 저장한다.
- content bytes, 업무상 document version, 확인된 bundle, 분석 attempt와 report revision을
  분리한다. 이 구분은 재현성을 위한 핵심 경계이므로 축소하지 않는다.
- ready bundle은 확인 시점 입력 snapshot이다. 분석·보고서는 live attachment/document
  projection을 다시 읽지 않는다.
- machine output, report revision, validation, final opinion은 append-only다. 수정은 새
  revision/행으로만 표현한다.
- 원본과 전체 document structure JSON은 S3 호환 객체 저장소에 두고 PostgreSQL에는
  hash, versioned location과 근거 조회용 block projection만 둔다.
- 모든 시각은 `timestamptz`/UTC, 금액은 `numeric`, 외부 신규 ID는 UUID다. UUID는
  애플리케이션에서 생성하며 v1은 추가 PostgreSQL extension에 의존하지 않는다.
- Langfuse, SSO, 범용 retention control plane은 단계 2다. v1 분석은 이들 없이 완결된다.
- 3개 분석 stage는 업무 결과의 경계다. 각 stage 안에서는 입력을 문서·요구사항 단위의 제한된
  slice로 나누어 여러 번 호출할 수 있으며, 전체 원문을 하나의 거대 prompt로 보내지 않는다.
- v1 심층 분석 profile/policy는 배포 운영자가 import하는 설정이며 사용자 편집 기능이 아니다.
  향후 사용자 편집을 제공할 때는 관리 화면과 새 immutable version 생성을 함께 도입한다.

## 2. 규모 변화

| 구분 | 기존 확장안 | Lean v1 |
|---|---:|---:|
| 기존 SQLite 테이블 | 13 | 13 |
| 신규 테이블 | 약 53 | 25 |
| 전체 모델 엔터티 | 66 | 38 |
| 분석 단계 | 7 | 3 |
| 구현 작업 | 11 | 7 |

## 3. 전체 관계

```mermaid
flowchart LR
    LEGACY[기존 13개 수집·검토 테이블]
    ATTACHMENT[attachment]
    CONTENT[content_object / location / scan]
    DOCUMENT[document_version / structure / block]
    BUNDLE[document_bundle / item]
    PROFILE[profile_version / evidence]
    POLICY[analysis_policy_version]
    REVIEW[deep_review / attempt / stage]
    CLAIM[claim / evidence_ref]
    REPORT[report_revision / validation / opinion]
    OPS[work_job / idempotency / audit]
    STORE[MinIO / S3]
    MCP[격리 문서 처리기]
    QWEN[vLLM / Qwen]

    LEGACY --> ATTACHMENT
    ATTACHMENT --> DOCUMENT
    CONTENT --> DOCUMENT
    CONTENT --> STORE
    DOCUMENT --> MCP
    DOCUMENT --> BUNDLE
    BUNDLE --> REVIEW
    PROFILE --> REVIEW
    POLICY --> REVIEW
    REVIEW --> QWEN
    REVIEW --> CLAIM
    CLAIM --> REPORT
    OPS --> REVIEW
```

## 4. 기존 데이터와 이름 기록

### 4.1 기존 13개 테이블

`run`, `notice`, `judgment`, `perspective`, `evidence`, `counterargument`,
`verification_item`, `matched_performance`, `attachment`, `agency_portal`, `review`,
`verification_answer`, `ingest_warning`을 전량 이관한다. 기존 `evidence`만 신규 분석
근거와 구분하기 위해 `screening_evidence`로 rename한다.

| SQLite 테이블 | PostgreSQL 처리 |
|---|---|
| `run` | integer/string PK와 모든 컬럼 유지, JSON은 `jsonb` |
| `notice` | integer PK와 분류·지역·match·raw JSON 등 모든 컬럼 유지 |
| `judgment` | `notice_pk→notice_id`, 나머지 전량 유지 |
| `perspective`, `verification_item`, `matched_performance` | 전량 유지 |
| `evidence` | `screening_evidence`로 rename, 전량 유지 |
| `counterargument` | `text→body`, 나머지 유지 |
| `review` | `notice_pk→notice_id`; `reviewer`는 `reviewer_snapshot`으로 보존 |
| `verification_answer` | review 내부 전체 교체 detail로 유지 |
| `attachment` | `url→source_url`, `stored_path→legacy_stored_path`; legacy extract 상태 원문 보존 |
| `agency_portal` | `note` 포함 전량 유지 |
| `ingest_warning` | `context_json→context_jsonb`, 나머지 유지 |

import 도구가 manifest에 없는 legacy 컬럼을 발견하면 폐기하지 않고 중단한다. integer PK를
그대로 적재한 뒤 모든 sequence에 `setval`을 적용한다.

### 4.2 이름-only attribution

- 사람 mutation은 정규화된 `claimed_name`과 작성 당시 표시 문자열을 행에 저장한다.
- 이름은 인증·권한·동일인 판별 수단이 아니다. 같은 이름을 하나의 UUID identity로
  합치지 않는다.
- worker mutation은 `actor_kind='system'`과 null `claimed_name`을 사용한다. HTTP에서
  `system`을 선택할 수 없다.
- 기존 `review.reviewer_snapshot`을 claimed name과 자동 병합하거나 재작성하지 않는다.
- 향후 SSO는 검증된 issuer/subject 기반의 새 actor를 만들고 과거 이름 행은 계속
  `미인증 이름 기록`으로 남긴다. 이름·이메일 기반 자동 병합은 금지한다.

### 4.3 attachment retirement

`attachment`에 `source_system`, `source_attachment_key`, `last_seen_at`, `retired_at`,
`retired_reason`, `retired_by_name`을 추가한다.

- provider attachment는 `source_attachment_key IS NOT NULL`일 때 partial unique
  `(notice_id, source_system, source_attachment_key)`를 사용한다.
- 수동 업로드는 파일명·URL로 deduplicate하지 않는다.
- 일반 업무 흐름에서 attachment를 물리 삭제하지 않는다.

## 5. 신규 document 모델 — 8개 테이블

```mermaid
erDiagram
    CONTENT_OBJECT {
        uuid id PK
        string sha256 UK
        bigint size_bytes
        string detected_mime
        string retention_class
        timestamptz created_at
    }
    CONTENT_OBJECT_LOCATION {
        uuid id PK
        uuid content_object_id FK
        string namespace_key
        string object_key
        string object_version_id
        string etag
        string status
        string encryption_key_ref
        timestamptz verified_at
        timestamptz purged_at
        timestamptz created_at
    }
    CONTENT_SCAN {
        uuid id PK
        uuid content_object_id FK
        string scanner
        string scanner_version
        string status
        jsonb safe_result
        timestamptz scanned_at
    }
    DOCUMENT_VERSION {
        uuid id PK
        bigint notice_id FK
        bigint attachment_id FK
        uuid content_object_id FK
        int version
        string source_kind
        string source_system
        string source_attachment_key
        text source_url
        string original_filename
        string role
        date effective_date
        uuid replaces_document_version_id FK
        boolean is_current
        string safety_status
        boolean needs_human_review
        string created_by_name
        timestamptz created_at
    }
    DOCUMENT_STRUCTURE {
        uuid id PK
        uuid document_version_id FK,UK
        string source_sha256
        string media_type
        string extractor_name
        string extractor_version
        string upstream_commit
        uuid payload_content_object_id FK
        string payload_sha256
        int page_count
        int block_count
        string validation_status
        timestamptz created_at
    }
    DOCUMENT_BLOCK {
        uuid id PK
        uuid structure_id FK
        string block_key
        string parent_block_key
        string block_type
        int page
        jsonb bbox
        text content
        numeric confidence
        jsonb attributes
    }
    DOCUMENT_BUNDLE {
        uuid id PK
        bigint notice_id FK
        int revision
        int version
        string status
        uuid supersedes_bundle_id FK
        jsonb issues_snapshot
        string created_by_name
        string confirmed_by_name
        timestamptz confirmed_at
        timestamptz created_at
    }
    DOCUMENT_BUNDLE_ITEM {
        uuid bundle_id PK,FK
        uuid document_version_id PK,FK
        int ordinal
        int document_version_version
        uuid content_object_id
        string content_sha256
        string detected_mime
        bigint size_bytes
        string original_filename
        string source_kind
        string source_system
        string source_attachment_key
        text source_url
        string role_at_confirmation
        date effective_date_at_confirmation
        uuid replaces_id_at_confirmation
        boolean is_current_at_confirmation
        string safety_status_at_confirmation
        uuid structure_id_at_confirmation
        string structure_payload_sha256
    }

    CONTENT_OBJECT ||--o{ CONTENT_OBJECT_LOCATION : stored_at
    CONTENT_OBJECT ||--o{ CONTENT_SCAN : scanned_by
    CONTENT_OBJECT ||--o{ DOCUMENT_VERSION : reused_by
    DOCUMENT_VERSION ||--o| DOCUMENT_STRUCTURE : structured_as
    DOCUMENT_STRUCTURE ||--o{ DOCUMENT_BLOCK : projects
    DOCUMENT_BUNDLE ||--|{ DOCUMENT_BUNDLE_ITEM : contains
    DOCUMENT_VERSION ||--o{ DOCUMENT_BUNDLE_ITEM : snapshotted_as
```

핵심 규칙:

- `content_object.sha256`는 byte identity다. 같은 bytes가 여러 업무 document version에
  사용될 수 있다.
- location의 `namespace_key`는 배포 설정의 `source`, `structure`, `quarantine`,
  `model-response` namespace를 참조한다. credential/endpoint 비밀은 DB에 저장하지 않는다.
- bytes를 먼저 기록하고 다시 읽어 SHA-256/size를 검증한 뒤 location과 업무 참조를 commit한다.
- upload는 quarantine에만 쓰고 MIME/magic/archive/PDF/ClamAV 검사를 통과한 bytes를 source
  location에 새로 기록한다. v1에는 수동 안전 해제가 없다. 검사 불가·불확실은 계속 격리한다.
- bytes가 없는 provider attachment는 사용자가 입력한 임의 URL을 fetch하지 않는다. 검증된
  `source_system`별 connector가 allowlist host/TLS/redirect/DNS-IP/timeout/50 MiB 제한 아래
  기존 `source_url`을 취득해 quarantine으로만 기록한다. 취득 실패·변경·소실은 blocking
  bundle issue이며, 성공한 bytes의 hash를 기존 URL metadata와 함께 새 document version에 고정한다.
- 구조 전체 `bidops.document-structure.v1` JSON이 정본이다. `document_block`은 locator 조회
  projection이고 page metadata와 table cell 좌표는 payload 및 block `attributes`에 둔다.
- OCR 오류는 `미확인`으로 남기거나 담당자가 정정 파일을 새 document version으로 다시
  등록한다. 인앱 OCR text 수정과 별도 correction 테이블은 v1에 없다.
- bundle issue는 ready 전 계산하고 확인 시 `issues_snapshot`에 고정한다. unresolved blocking
  issue가 있으면 ready 전환을 거부한다.
- ready 전환은 bundle/document/structure를 잠근 한 트랜잭션에서 수행한다. item snapshot은
  UPDATE/DELETE하지 않고 정정은 새 version과 새 bundle을 만든다.
- `document_bundle_item`은 unique `(bundle_id, document_version_id,
  structure_id_at_confirmation)`를 가져 evidence composite FK의 기준이 된다. ready 시
  출처상 nullable인 URL·대체 ID 외 snapshot 필드는 non-null이다.
- 안전 상태가 나중에 차단되면 과거 snapshot은 바꾸지 않지만 신규 분석·원문 열람은 막고
  과거 보고서에 경고한다.

## 6. 신규 knowledge 모델 — 3개 테이블

```mermaid
erDiagram
    PROFILE_VERSION {
        uuid id PK
        int version UK
        string label
        jsonb profile_payload
        string profile_sha256
        string source_kind
        string created_by_name
        timestamptz created_at
    }
    PROFILE_EVIDENCE {
        uuid id PK
        uuid profile_version_id FK
        string fact_key
        uuid content_object_id FK
        string source_sha256
        string locator_type
        jsonb locator
        text quote
        string confirmed_by_name
        timestamptz confirmed_at
    }
    ANALYSIS_POLICY_VERSION {
        uuid id PK
        int version UK
        string label
        string model_endpoint_ref
        string model_name
        jsonb prompts
        jsonb validation_rules
        string policy_sha256
        string created_by_name
        timestamptz created_at
    }

    PROFILE_VERSION ||--o{ PROFILE_EVIDENCE : supports
```

- 기존 company profile Markdown을 최초 immutable `profile_version`으로 import한다.
- v1 profile evidence는 안전 검사를 통과한 업로드 파일만 허용한다. URL capture/SSRF 취득은
  단계 2다.
- `fact_key`는 immutable profile payload 안의 안정 key다. import/validation이 fact 존재와
  locator를 검사한 뒤 evidence를 저장한다.
- `profile_evidence`는 unique `(profile_version_id, id)`를 두어 분석 evidence가 pinned
  profile version 밖의 증빙을 참조하지 못하게 한다.
- policy prompts와 규칙은 한 immutable JSON payload로 저장한다. prompt별 테이블과 activation
  event/pointer는 만들지 않는다.
- active profile/policy ID는 배포 설정으로 지정한다. 분석 생성 시 존재·hash를 확인해
  `deep_review`에 고정한다.
- v1에는 profile/policy 생성·복제·활성화 웹 UI/API가 없다. 변경은 검증된 server import CLI와
  새 immutable version으로만 수행한다.
- import 후보는 고정 표본에서 필수 항목 재현율 80% 이상, 사람 판정 일치율 70% 이상,
  근거 부족 오판율 10% 이하를 충족해야 active ID로 지정할 수 있다. 측정 결과와 표본 hash는
  policy payload의 검증 metadata에 포함한다.
- 이는 v1 심층 분석 기준을 사용자 편집 대상으로 노출하지 않는 범위 결정이다. 향후 UI에서
  편집하게 되면 저장 시 기존 행을 수정하지 않고 새 policy version을 생성해야 한다.

## 7. 신규 analysis 모델 — 11개 테이블

```mermaid
erDiagram
    DEEP_REVIEW {
        uuid id PK
        bigint notice_id FK
        uuid bundle_id FK
        uuid profile_version_id FK
        uuid policy_version_id FK
        string effective_grade_at_start
        string status
        uuid current_attempt_id FK
        string requested_by_name
        timestamptz created_at
        timestamptz completed_at
    }
    DEEP_REVIEW_ATTEMPT {
        uuid id PK
        uuid deep_review_id FK
        int sequence
        string status
        uuid work_job_id FK
        bigint lease_fence
        string requested_by_name
        timestamptz started_at
        timestamptz completed_at
    }
    DEEP_REVIEW_STAGE {
        uuid id PK
        uuid attempt_id FK
        string stage
        int sequence
        string status
        jsonb structured_output
        jsonb invocation_metadata
        uuid raw_response_content_object_id FK
        timestamptz started_at
        timestamptz completed_at
    }
    CLAIM {
        uuid id PK
        uuid deep_review_id FK
        uuid stage_id FK
        string category
        string claim_type
        text body
        string status
        text formula
        jsonb premise_claim_ids
        text reason
    }
    EVIDENCE_REF {
        uuid id PK
        uuid deep_review_id FK
        string source_kind
        bigint notice_id FK
        uuid bundle_id FK
        uuid document_version_id FK
        uuid structure_id FK
        uuid profile_version_id FK
        uuid profile_evidence_id FK
        string locator_type
        jsonb locator
        text quote
        numeric confidence
        string source_sha256
    }
    CLAIM_EVIDENCE {
        uuid deep_review_id PK,FK
        uuid claim_id PK,FK
        uuid evidence_ref_id PK,FK
        int ordinal
    }
    REPORT_REVISION {
        uuid id PK
        uuid deep_review_id FK
        int sequence
        uuid parent_revision_id FK
        string origin
        jsonb report_payload
        string report_sha256
        string change_reason
        string created_by_name
        timestamptz created_at
    }
    REPORT_REVISION_EVIDENCE {
        uuid deep_review_id PK,FK
        uuid report_revision_id PK,FK
        uuid evidence_ref_id PK,FK
    }
    VALIDATION_RUN {
        uuid id PK
        uuid deep_review_id FK
        uuid report_revision_id FK
        int sequence
        string status
        timestamptz created_at
    }
    VALIDATION_CHECK {
        uuid id PK
        uuid validation_run_id FK
        string check_type
        string status
        string severity
        text message
        jsonb related_claim_ids
        jsonb related_evidence_ids
    }
    FINAL_OPINION {
        uuid id PK
        uuid deep_review_id FK
        uuid report_revision_id FK
        int sequence
        string value
        text reason
        uuid validation_run_id FK
        string validation_status_at_opinion
        boolean acknowledged_validation_failure
        string claimed_name
        timestamptz created_at
    }

    DEEP_REVIEW ||--o{ DEEP_REVIEW_ATTEMPT : runs
    DEEP_REVIEW_ATTEMPT ||--|{ DEEP_REVIEW_STAGE : contains
    DEEP_REVIEW_STAGE ||--o{ CLAIM : produces
    CLAIM ||--o{ CLAIM_EVIDENCE : cites
    EVIDENCE_REF ||--o{ CLAIM_EVIDENCE : supports
    DEEP_REVIEW ||--|{ REPORT_REVISION : reported_as
    REPORT_REVISION ||--o{ REPORT_REVISION_EVIDENCE : cites
    EVIDENCE_REF ||--o{ REPORT_REVISION_EVIDENCE : supports
    REPORT_REVISION ||--o{ VALIDATION_RUN : validated_by
    VALIDATION_RUN ||--|{ VALIDATION_CHECK : contains
    REPORT_REVISION ||--o{ FINAL_OPINION : decided_on
```

핵심 제약:

- unique `deep_review(notice_id, bundle_id, profile_version_id, policy_version_id)`.
- `deep_review`에는 unique `(id, notice_id)`, `(id, bundle_id)`, `(id, profile_version_id)`를
  두어 evidence scope composite FK의 기준으로 사용한다.
- 한 deep review의 `queued|running` attempt는 partial unique로 하나만 허용한다.
- `current_attempt_id`는 `(deep_review_id, attempt_id)` 복합 FK로 같은 review 소속만 허용한다.
- attempt는 unique `(deep_review_id, sequence)`, stage는 unique `(attempt_id, stage)`와
  unique `(attempt_id, sequence)`를 사용한다.
- 분석 단계는 `requirements_and_evaluation`, `delivery_risk_economics`,
  `synthesis_and_validation` 3개다. stage별 model request/response hash, token, latency, error는
  `invocation_metadata`에 검증된 형태로 저장한다.
- 하나의 stage는 동일한 stage 행 아래 여러 bounded invocation을 가질 수 있다.
  `invocation_metadata`는 invocation별 input slice hash, model/prompt hash, token, latency와
  오류를 배열로 보존한다. 요구사항 ID와 locator는 결정적으로 먼저 고정하고 slice별 결과를
  schema 검증 후 병합한다. 3단계를 3개의 거대 prompt로 구현해서는 안 된다.
- raw model response는 암호화된 ephemeral object로 최대 90일 보존하고 stage의 response hash,
  structured output과 실행 metadata는 계속 남긴다.
- fact는 evidence 필수, calculation은 식과 입력 근거 필수, inference는 같은 review의
  premise claim ID와 근거 필수다. premise JSON은 저장 전에 cycle/소속을 검증한다.
- evidence는 source-kind check union을 사용한다. document이면 bundle/document/structure가
  non-null이고 profile 필드는 null, profile이면 profile version/evidence가 non-null이고
  document 필드는 null이다.
- document evidence는 `(deep_review_id, bundle_id) → deep_review(id, bundle_id)`와
  `(bundle_id, document_version_id, structure_id) → document_bundle_item(...)` 복합 FK로
  ready snapshot 범위를 강제한다.
- profile evidence는 `(deep_review_id, profile_version_id) → deep_review(id,
  profile_version_id)`와 `(profile_version_id, profile_evidence_id) → profile_evidence(...)`
  복합 FK로 pinned profile 범위를 강제한다.
- claim/evidence 및 report/evidence join은 `deep_review_id`를 포함한 복합 FK를 사용한다.
- 최초 machine report도 `report_revision(origin='machine')`의 완전한 immutable JSON snapshot이다.
  사람 수정은 parent를 가리키는 새 `origin='human'` full snapshot이다. delta overlay 합성은 없다.
- report revision은 unique `(deep_review_id, sequence)`와 unique `(deep_review_id, id)`를
  사용한다. machine origin은 `created_by_name`이 null, human origin은 non-null이고 parent와
  change reason이 필수라는 check를 둔다.
- factual change는 reason과 evidence link가 필요하고 새 validation run을 만든다.
- validation check의 관련 ID 배열은 write 시 같은 review 소속을 검증한다. 진단용 관계를 위한
  별도 join table은 만들지 않는다.
- system recommendation은 `추진 검토|조건부 추진 검토|보류|검토 종료`이고, 이와 분리된
  final opinion은 `추진|조건부 추진|보류|검토 종료`다. final opinion은 실제 validation run/status snapshot과
  sequence를 고정한다. unique `(validation_run.id, status)`와 composite FK
  `(validation_run_id, validation_status_at_opinion)`으로 실제 상태 일치를 강제하고 validation
  실패면 acknowledgement와 reason이 DB check로 필수다.

## 8. 신규 ops 모델 — 3개 테이블

```mermaid
erDiagram
    WORK_JOB {
        uuid id PK
        string job_type
        string aggregate_type
        uuid aggregate_id
        string status
        int priority
        string lease_owner
        timestamptz lease_expires_at
        bigint lease_fence
        int attempt_count
        int max_attempts
        timestamptz scheduled_at
        string last_error_code
        timestamptz created_at
        timestamptz completed_at
    }
    IDEMPOTENCY_RECORD {
        uuid id PK
        string operation
        string aggregate_type
        string aggregate_id
        string claimed_name
        uuid request_id
        string request_sha256
        int response_status
        jsonb response_snapshot
        timestamptz created_at
    }
    AUDIT_EVENT {
        uuid id PK
        string actor_kind
        string claimed_name
        string action
        string aggregate_type
        string aggregate_id
        jsonb safe_metadata
        string request_id
        timestamptz created_at
    }
```

- idempotency는 upload/bundle confirm/deep review create·retry/report revision/final opinion처럼
  재실행 피해가 있는 mutation에만 적용한다. record는 v1에서 자동 purge하지 않는다.
- idempotency unique scope는 `(claimed_name, operation, aggregate_type, aggregate_id,
  request_id)`이며 request hash는 canonical metadata와 upload byte hash를 포함한다. response
  snapshot에는 원문 bytes나 비밀을 넣지 않는다.
- active job partial unique `(job_type, aggregate_type, aggregate_id) WHERE status IN
  ('queued','running')`을 둔다.
- worker는 짧은 `FOR UPDATE SKIP LOCKED` claim과 증가하는 `lease_fence`를 사용한다. stage/report
  저장은 현재 job/owner/fence가 일치하는 조건부 SQL로만 수행한다. 전용 DB stored function과
  복잡한 결과 테이블 권한 회수는 v1에 넣지 않는다.
- job 전이는 별도 event 테이블 대신 `audit_event`에 안전한 상태 metadata로 기록한다.
- DB role은 `bidops_owner`/migration, `bidops_app`, `bidops_worker`, `bidops_ro_backup` 네 경계로
  제한한다.

## 8.1 결정적 문서 segment 저장소 — 신규 3개 테이블 (`0018`)

[ADR-0051](tracking/decisions/0051-deep-review-v2-deterministic-subset.md)이 채택한 결정적
segment·요구사항 inventory를 담는다. Lean v1 동결 이후 추가된 표이므로 §2의 규모 표에는
포함하지 않고 여기서 계약을 고정한다.

| 테이블 | 담는 것 |
|---|---|
| `document_segment_manifest` | 구조 하나에 대한 manifest. taxonomy version, extractor binding과 그 SHA-256, payload hash, inventory 요약, coverage, 경고 |
| `document_segment` | 순서가 있는 segment. taxonomy label, 시작·끝 locator, 요구사항 ID, source block key, 상태 |
| `requirement_inventory_item` | 문서에서 읽은 요구사항 ID 항목 |

계약은 다음과 같다.

- 세 표 모두 **append-only**다. runtime role에는 `SELECT`와 `INSERT`만 준다.
- FK는 `ondelete=CASCADE`이며 `(document_version_id, structure_id)` 복합 FK로 구조와 문서
  버전의 짝을 강제한다.
- manifest의 유일키는 `(structure_id, taxonomy_version, extractor_binding_sha256)`다.
- **`schema_version` 열을 두지 않는다.** 판을 표시하는 것은 `taxonomy_version`과
  `extractor_binding`이며, 규칙 표가 바뀌면 `rules_sha256`이 바뀌어 새 identity 키 = 새 row가
  된다. 기존 row를 덮어쓰는 경로가 없다.
- `document_segment.status`는 `classified|needs_human_review`, `classification_source`는
  `deterministic` 고정, `ordinal >= 1`이다. `needs_human_review`면 `confidence`는 반드시
  `NULL`이다. 실제로는 `classified`에서도 항상 `NULL`이다 — 결정적 규칙에는 확률이 없다.
- `requirement_inventory_item.ordinal >= 1`이며 ID와 locator는 구조 검사를 받는다.
- manifest는 **구조 저장 시점의 메모리 payload로만** 만든다. `document_block`에 ordinal이
  없어 사후 재구성이 불가능하므로, 이 migration 이전에 만들어진 `DocumentStructure`에는
  manifest가 없고 `GET /api/document-structures/{id}/segments`가 404다.

## 8.2 `0018`의 기존 제약 변경과 명세 이름 정정

`0018_prespec_auto_preparation_segments`는 기존 CHECK 둘을 바꾼다.

| CHECK | 이전 | 이후 |
|---|---|---|
| `attachment_fetch.ck_attachment_fetch_eligibility_reason` | `('sw_business_object','tracked_order_plan','both')` | 여기에 `'priority_grade'`를 더한다 |
| `prespec_overview_attempt.ck_prespec_overview_attempt_completed_binding` | `status <> 'completed' OR (reference_only IS FALSE AND deployable IS TRUE)` | `status <> 'completed' OR reference_only IS FALSE` |

둘째 변경의 뜻은 **품질을 아직 재지 않은 실제 모델 실행(`deployable=false`,
`reference_only=false`)도 `completed`가 될 수 있고, mock 참조 실행(`reference_only=true`)만
완료를 막는다**는 것이다. 상태 전이 trigger는 그대로 둔다.

**명세 이름 정정.** 이 변경을 요구한 명세(§7·§6.3)는 대상 CHECK를
`ck_prespec_overview_attempt_completion`으로 **이름으로** 지목했다. 그 CHECK는 실제로는
status·시각·result 참조의 생애주기 불변식이고, "완료는 배포 가능 binding만"을 강제하던 것은
`ck_prespec_overview_attempt_completed_binding`이다. 명세가 인용한 새 본문의 모양도 후자의
것이다. `..._completion`을 그 본문으로 바꾸면 §7이 건드리지 말라고 한 생애주기 불변식이
사라진다. 따라서 **이름이 아니라 인용된 본문을 정본으로 읽어** `..._completed_binding`을
교체했다. 이 정정은 migration 파일 머리주석에도 같은 내용으로 남아 있다.

또한 `prespec_overview_attempt`에 nullable `lease_owner`(varchar 255)와
`lease_expires_at`(timestamptz)이 추가된다. worker의 column-scoped UPDATE 허용 열은
`status`·`started_at`·`completed_at`·`result_id`·`lease_owner`·`lease_expires_at` 여섯이다.
lease 길이는 환경변수가 아니라 모듈 상수 1,200초다.

**downgrade는 조용히 데이터를 잃지 않는다.** `priority_grade` 자격 행,
`deployable=false`인 완료 attempt, 세 segment 표의 행 중 하나라도 있으면 추정 보정 없이
거부한다.

개요 attempt와 암호화된 원응답 사이에는 직접 FK가 없다. 원응답은 `ContentObject`와
`ContentObjectLocation('model-response')`로 저장되고, 대조는 감사 이벤트의
`response_sha256`으로 한다. 명세가 이 표에 두 열만 허용했으므로 이번 범위에서 FK를 만들지
않았다.

## 8.3 회사 핏 판정 이력 (`0020`, 2026-09-08 추가)

사용자가 요청한 개요 뒤 회사 핏 판정과 상세 사유 표시를 위해
`prespec_company_fit_attempt`를 추가한다. 기존 개요·심층 검토 결과를 덮어쓰지 않는다.
세부 JSON/조회 계약은 [회사 핏 계약](contracts.md#사전규격-회사-핏-계약-bidopsprespec-company-fitv1)을 따른다.

- `notice_id`·`document_version_id`를 같은 공고의 문서에 고정한다.
  `overview_run_id`(`prespec_overview_run(id)` FK, nullable)는 원본 개요가 같은
  공고·문서를 가리키는지 INSERT trigger에서 확인한다.
- 승인 프로필·심층 정책 FK, 원본 개요·프로필 hash, 회사 핏 정책 전문·모델 binding과
  구조화 입력은 실행 전에 고정한다. `input_sha256`은 UNIQUE이며 입력 열은 갱신할 수 없다.
- `queued → running → completed/failed/needs_human_review`만 허용한다. 오래된 queued
  입력은 failed로 닫을 수 있다. running에는 lease가 필요하고 종결 상태에는 종료 시각이
  필요하다. completed에는 결과 JSON·hash가 필요하다. 종결 행 UPDATE와 모든 DELETE를 거부한다.
- worker는 지정된 상태·결과·lease·사용량 열만 갱신할 수 있다. app은 SELECT만 가능하다.
  downgrade는 이력이 하나라도 있으면 거부한다.
- 품질은 `unmeasured_reference` 또는 `mock_reference`만 저장한다. 현재 운영용 측정 정책은
  없으며 참조 실행 활성화 없이 모델 실행·자동 심층 생성을 허용하지 않는다.

## 8.4 native rhwp snapshot 참조 (`0023`, 2026-09-10 추가)

`0021`의 `prespec_v4_pdf_snapshot`에 다음 nullable 열을 추가한다. 기존 행은
그대로 보존하며 snapshot의 UPDATE/DELETE 금지 trigger도 유지한다.

| 열 | 참조·계약 |
|---|---|
| `hwpx_content_object_id`, `hwpx_location_id` | HWP 변환본의 `content_object`, `content_object_location` FK; 원본 HWPX는 둘 다 null |
| `hwpx_verify_jsonb` | HWP 변환 검증의 안전한 IR 동일성·차이 개수·전후 페이지 수 |
| `structure_id`, `structure_location_id` | 같은 문서의 `document_structure` FK와 payload의 정확한 location FK |
| `para_page_map_content_object_id`, `para_page_map_location_id`, `para_page_map_sha256` | 대응표 객체·location FK와 SHA-256 |
| `section_candidates_content_object_id`, `section_candidates_location_id`, `section_candidates_sha256` | 절 후보(신규 `bidops.section-candidates.v2`, 기존 v1 읽기 유지) 객체·location FK와 SHA-256 (`0024`, 모두 nullable이며 셋이 함께 null이거나 함께 채워진다. 0024 이전 snapshot 또는 핵심 산출물은 유효하나 `section_candidates_unavailable` 경고가 있는 신규 snapshot은 함께 null로 보존·재사용한다) |
| `rhwp_binary_sha256`, `rhwp_version` | native renderer provenance |

모든 신규 FK는 `ON DELETE RESTRICT`다. renderer는 기존 JSON 안의 값으로서
`rhwp-svg-pdf`를 허용하며 별도 renderer 열을 추가하지 않는다. native
`renderer_digest`는 renderer JSON 전체의 canonical SHA-256이다. 기존
`(document_version_id,source_sha256,config_sha256,renderer_digest,font_digest)`
UNIQUE는 유지한다. 서비스가 원본·객체 버전·해시·HWPX 검증·page-text/map 결속을
검증하고 DB는 FK·UNIQUE·불변 trigger를 담당한다.

`document_structure.document_version_id` UNIQUE도 유지한다. 기존 구조의 원본
해시·MIME·pages·blocks가 native 결과와 같아야 재사용하고, 차이는
`structure_binding_mismatch`로 닫는다. 다른 구조를 기존 리뷰 위에 덮지 않는다.

`0022`가 추가했던 `prespec_v4_target`·`prespec_v4_attempt`(그 위에 얹힌
`validation_warnings` 등 모든 후속 열 포함)는 **0026에서 삭제**한다. `prespec_v4_pdf_snapshot`
(`0021`)은 이 절의 열과 함께 유지한다.

## 8.5 사전규격 개요 run (`0026`)

v3 개요 review/snapshot/attempt/result(`0012`·`0014`), v4 target/attempt(`0022`), v5 주장
검증·call ledger(`0025`)를 모두 폐기하고 `prespec_overview_run` 단일 테이블로 재작성한다
([ADR-0054](tracking/decisions/0054-prespec-overview-mvp-rewrite.md)). 상세 계약 정본은
[contracts.md](contracts.md#사전규격-개요-검토-mvp-2026-09-11)다.

| 열 | 타입 | 뜻 |
|---|---|---|
| `id` | uuid PK | |
| `notice_id` | bigint FK `notice` | |
| `document_version_id` | uuid FK `document_version` | 묶음의 RFP 문서 |
| `snapshot_id` | uuid FK `prespec_v4_pdf_snapshot`, null | 준비 전이면 null |
| `work_job_id` | uuid FK `work_job` | `job_type=prespec_overview`, `aggregate_type=prespec_overview_run` |
| `status` | varchar(32) CHECK | `queued\|running\|completed\|needs_human_review\|failed\|cancelled` |
| `range_source` | varchar(16) CHECK | `auto\|fallback\|human` |
| `page_start`, `page_end` | int, null | 1부터 시작하는 물리 PDF 쪽. 준비 전 null |
| `range_reason_codes` | jsonb | 자동 선택·fallback 사유 코드 목록 |
| `input_sha256` | char(64), null | 동결 입력 hash |
| `policy_digest` | char(64) | 정책 v7 digest |
| `model_name` | text | |
| `model_revision` | text, null | |
| `draft_json`, `checks_json`, `result_json` | jsonb, null | 초안·검사 결과·최종 개요. `result_json`(`bidops.prespec-overview-claims.v2`)은 앞부분 요약 세 절 `business_overview`·`main_tasks`·`budget_and_period`와 `input_limitations`만 갖고 `important_conditions`·`reviewer_analysis`·`unknowns` key는 **없다**([ADR-0057](tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md)). 2026-09-16 이전 행의 `bidops.prespec-overview-page-review.v4` 결과는 그대로 두고 읽을 때 세 절만 투영한다 |
| `warnings_json` | jsonb | 수치·역할·날짜 대조 경고 등 비차단 경고 |
| `reason_codes` | jsonb | 실패·사람 검토 사유 코드 |
| `call_count` | int | 모델 호출 수 |
| `raw_response_refs` | jsonb | 암호화 원응답 참조 목록(`{sha256, object_key}[]`); API에 노출 금지 |
| `actor_name` | text, null | 사람 범위 확정 시 담당자 |
| `created_at`, `started_at`, `completed_at` | timestamptz | |

인덱스 `ix_prespec_overview_run_notice_created(notice_id, created_at desc)`, 부분 유니크
`uq_prespec_overview_run_active(notice_id) where status in ('queued','running')`. app role은
SELECT/INSERT/UPDATE, worker role은 SELECT/INSERT/UPDATE만 갖는다. 함께 drop하는 테이블은
`prespec_overview_verification`, `prespec_overview_call_event`, `prespec_v4_attempt`,
`prespec_v4_target`, `prespec_page_overview`, `prespec_overview_attempt_event`,
`prespec_overview_result`, `prespec_overview_attempt`, `prespec_overview_snapshot`,
`prespec_overview_review`이고 함수 `tf_prespec_v4_attempt_guard()`도 drop한다.
`prespec_v4_pdf_snapshot`(`0021`)과 `bidops.section-candidates.v1/v2`는 유지한다. 적용 전
pg_dump 백업 절차는 [operations.md](operations.md#0026-적용-전-개요-테이블-백업)를 따른다.

## 8.6 입찰 최종 결정 근거 (`0028`, 2026-09-17 추가)

입찰 delta 5개 table(`bid_delta_comparison`·`bid_delta_attempt`·`bid_delta_item`·
`bid_delta_evidence`·`bid_final_decision`)은 `0015`가 만들고 상세 제약은
[입찰 delta 계약 명세](bid-delta-contract-spec.md) §5가 정본이다. `0028`은
`bid_final_decision`의 결정 근거를 모델 비교와 분리한다
([ADR-0058](tracking/decisions/0058-final-decision-basis-separated-from-comparison.md)).

| 열 | 타입 | 뜻 |
|---|---|---|
| `basis_kind` | varchar(32) NOT NULL CHECK | `comparison\|notice_conditions`. 기존 행은 `comparison`으로 채우고 기본값은 두지 않는다 |
| `comparison_id`, `comparison_version`, `result_sha256`, `baseline_document_version_id`, `comparison_document_version_id` | 기존 타입, **nullable로 변경** | 비교 근거 fence |
| `basis_notice_id` | int FK `notice`(RESTRICT), null | 공고 조건 근거인 authoritative 입찰공고 |
| `basis_observation_sha256` | varchar(64), null, 64 hex CHECK | 결정 시점 그 공고의 최신 관측 `source_sha256` |

- `ck_bid_final_decision_basis_fields`: 비교 근거는 비교 5열 NOT NULL·basis 2열 NULL, 공고 조건
  근거는 반대다. 섞이거나 빠진 행은 DB가 거부한다.
- append-only trigger(`tr_bid_delta_final_decision_append_only`), sequence·supersession·idempotency
  unique, supersession·comparison 범위 FK는 그대로다. 기존 행은 UPDATE하지 않는다.
- 현재성은 저장하지 않는다. 공고 조건 근거는 기준 공고보다 새 authoritative 입찰공고나 관측 hash
  변경이 있으면 `stale`, 판정 불가면 `unknown`으로 읽을 때 계산한다.
- app role은 `bid_final_decision` SELECT·INSERT와 잠금용 `UPDATE (id)`만 갖는다. worker는 권한이 없다.
- downgrade는 `notice_conditions` 행이 하나라도 있으면 거부하고, 없으면 비교 5열 NOT NULL을 되돌린다.

## 9. FK 삭제와 불변 정책

기본 FK는 `RESTRICT`/`NO ACTION`이다.

| 부모 → 자식 | 정책 |
|---|---|
| run/notice → 업무 이력 | `RESTRICT`; archive만 허용 |
| judgment → 판정 내부 detail | 명시적 전체 교체에만 `CASCADE` |
| review → verification answer | review PUT 전체 교체에만 `CASCADE` |
| attachment → document version | `SET NULL`; document version이 출처 snapshot 보유 |
| content/document/structure/bundle → 정본 계보 | `RESTRICT` |
| profile/policy → deep review/evidence | `RESTRICT` |
| deep review → attempt/claim/report/validation/opinion | `RESTRICT` |

ready item, profile/policy version, claim/evidence, report revision, validation과 final opinion은
일반 앱 서비스에서 UPDATE/DELETE하지 않는다. 초기에는 복잡한 table별 grant보다 서비스
경계·DDL check/unique/FK와 회귀 테스트로 강제하고, 실제 위반 위험이 확인되면 제한 trigger나
세분 role을 추가한다.

## 10. SQLite 이관과 컷오버

1. 쓰기를 중단하고 SQLite backup API snapshot과 attachment file manifest를 만든다.
2. PostgreSQL `migration_staging`에 원시 행, import batch와 hash를 멱등 적재한다.
3. 저장 파일의 실제 SHA-256/size를 계산한다. URL-only, missing-file을 구분한다.
4. 모든 legacy 컬럼, row count, PK/FK, reviewer snapshot, file 존재·size·hash를 대조한다.
5. 성공 batch만 한 트랜잭션에서 `bidops` schema로 승격하고 sequence를 보정한다.
6. read-only 표본 검증 뒤 PostgreSQL 쓰기를 연다.
7. PostgreSQL 쓰기 개방 후 뒤처진 SQLite로 단순 rollback하지 않는다. pre-cutover backup
   복원 또는 forward fix를 사용한다.

URL-only provider attachment는 migration 성공과 별개로 남길 수 있지만 ready bundle에는 넣을
수 없다. T3의 allowlist connector로 bytes를 취득·검사한 뒤 document version을 만들며, source가
소실되면 담당자가 대체 원문을 등록하거나 attachment를 명시적으로 retired 처리하기 전까지
공고의 준비 완료를 차단한다.

## 11. Lean v1 백업·보존

- RPO 4시간, RTO 8시간을 초기 목표로 한다. 실제 pilot 복구시간과 업무 손실 허용치를
  확인한 뒤 강화한다.
- PostgreSQL은 매일 full base backup과 연속 WAL archive를 사용한다. source/structure 객체는
  최소 4시간 간격으로 version-aware 독립 저장소에 복사한다.
- 복구점 manifest는 외부 backup 도구가 관리한다. 애플리케이션 DB에 backup checkpoint나
  restore drill 테이블을 만들지 않는다.
- backup repository는 live MinIO와 다른 host/credential/장애 도메인에 둔다. 객체를 먼저
  복원한 뒤 PostgreSQL을 복원하고 active location SHA-256을 검증한다.
- 보존은 일별 14일, 주별 8주, 월별 6개월이다. production 전 1회, 이후 분기별로 격리된
  전체 restore drill을 수행한다.
- backup lag은 운영 alert로 처리한다. v1 애플리케이션이 backup 상태 때문에 모든 mutation을
  자동 차단하지 않는다.
- 정본 공고·원문·bundle·structure·profile/policy·report·opinion은 자동 삭제하지 않는다.
  범용 purge/hold 엔진은 만들지 않는다.
- 암호화 모델 원응답 90일은 `bidops-model-response` lifecycle, 선택적 Langfuse trace 보존은
  Langfuse 자체 정책으로 관리한다. 모델 원응답 기간은
  `BIDOPS_MODEL_RESPONSE_RETENTION_DAYS`, backup 보존은 외부 backup 설정으로 변경하며
  일반 앱 API를 만들지 않는다.

## 12. PostgreSQL·용량 기준

- PostgreSQL 17의 검증한 current minor/image digest를 고정한다. v1 필수 extension은 없다.
- 초기 검색은 B-tree/partial/expression index와 제한된 `ILIKE`만 사용한다. `pg_trgm`,
  vector/한국어 전문 검색과 partitioning은 실측 후 검토한다.
- 계획 부하는 월 100 notices, 800 document versions, 32,000 pages, 약 960,000 blocks다.
- 시작 기준은 PostgreSQL 4 vCPU/16 GiB/암호화 NVMe 200 GiB, MinIO usable 1 TiB다.
- import 예상 사용량이 가용 공간 70%를 넘으면 cutover를 막는다. disk free 30% 미만,
  block 2천만 행 또는 핵심 query p95 500 ms 초과 시 증설·인덱스·partitioning을 재평가한다.

## 13. 단계 2로 명시적으로 연기

- Langfuse self-host stack과 trace UI
- profile/policy 생성·복제·활성화 관리 UI와 activation event
- profile URL capture와 SSRF fetcher
- 수동 malware release
- 인앱 OCR text correction
- deep review 간 claim diff와 사람 수정 가져오기
- 범용 retention purge/hold control plane
- backup checkpoint/restore drill DB control plane
- SSO identity/attribution link schema
- 한국어 전문검색, vector 검색, table-cell 별도 projection과 partitioning

이 목록은 v1 구현자가 편의상 선구현하지 않는다. 실제 사용 요구와 별도 승인 뒤 새 migration과
명세로 추가한다.

## 14. 결정 상태

Lean v1 축소안은 기존 P0 무결성 경계를 유지하면서 운영·미래 기능을 단계 2로 분리했다.
사용자가 2026-08-25 최종 승인했으며 기준선 ID는
`bidops-deep-review-lean-v1-2026-08-25`다. 미결정 설계 항목은 없다. 이 문서를 포함한 승인
설계 기준선은 commit `d5941c7`에 보존되어 있다. 이후 변경은 문서와 migration 영향을 함께
검토하는 새 승인 대상으로 취급한다.

### 설명형 보고서 v2의 저장 경계 (2026-09-22)

v2의 문장 역할·절·주제·요구사항·연관 주장·핵심 여부는 완료 stage의
`structured_output` JSON 정본에 저장한다. 기존 `claim` 행에는 기존 공통 필드만 투영한다.
보고서 조립 때 공통 필드와 evidence 순서를 DB 행과 대조한 뒤 정본 metadata를 결합한다.
불일치·누락·단계 간 schema 혼합은 발행하지 않는다. stage 순서와 응답 내 문장 순서를
보존하며 UUID 정렬을 편집 순서로 사용하지 않는다.

`analysis_policy_version.validation_rules.policy_snapshot`은 v2 정책 전체 canonical
payload를 보존한다. hash, 등록 파일, model/prompt/generation/validation의 중복 열을
모두 대조한다. 회사 근거 선택 범위·예산 제외는 `invocation_metadata.profile_selection`,
종합 범위는 `synthesis_phase=partial|global`에 남긴다. 원문을 일반 로그로 보내지 않는다.

원문 인용·숫자 대조 선택은 attempt별 `deep_review.source_verification_selected`
감사 행(`aggregate_type=deep_review_attempt`, `safe_metadata.enabled`)에 고정한다.
없는 과거 행은 true이며 중복/잘못된 선택 행은 거부한다. 끈 실행의 report는 저장된
validation check `source_verification_skipped`와 분석 한계로 구별한다. 근거 조회도 해당
근거를 사용한 claim→stage→attempt 선택을 읽으며 현재 attempt의 값을 소급 적용하지 않는다.
page 인용이 여러 문단에 걸치면 DB block key 정렬 대신 고정 structure payload의 원래
문단 순서로 대조한다. 출처/해시/페이지 범위는 off에서도 유지한다.

새 테이블·열·migration은 없다. v1 행·revision/hash·의견을 갱신하는 이전 작업도 없다.
운영 활성화는 별도 사람 확인을 거치며, 코드가 존재한다는 이유로 활성 정책을 바꾸지 않는다.

## 사용자 요청 기반 Luna 입력·승인 (0032)

- `deep_review_preview`: UUID PK, notice/bundle/profile/policy FK(RESTRICT),
  입력 SHA-256, 동결 JSON, 생성 시각. 구조·profile 본문은 이 입력 저장소에만 둔다.
- `deep_review_approval`: UUID PK, preview/attempt FK(RESTRICT), 담당자,
  request UUID, 승인 시각. preview와 attempt 각각 unique다.
- 두 표는 append-only이며 DB trigger/ORM과 최소 권한이 보호한다. 승인 행이 있으면
  downgrade할 수 없다. 본문 없이 preview ID·해시·모델만 일반 감사에 기록한다.
- attempt·stage·보고서·사람 수정 이력은 기존 관계를 사용한다.
  [ADR-0069](tracking/decisions/0069-user-requested-luna-deep-review.md).

Luna v2 보조 연결 제외 기록은 완료 stage의 기존 invocation metadata에 저장한다.
모델 원본은 암호화 객체에 보존하고 파생 claim metadata만 제외된 연결을 반영한다.
validation check의 관련 ID에는 유효한 대상 claim만 넣으며 제외한 ID는 넣지 않는다.
보고서 수정본도 같은 stage의 경고를 이어받는다. [계약](contracts.md#luna-v2-보조-연결-경고-2026-09-23).

## 가정 분석 별도 이력 (0033, 운영 적용 전)

`assumption_input_version`은 notice/bundle/profile FK와 동결 JSON/hash,
`assumption_run`은 고유 input version·request·work job 및 담당자/승인 시각,
`assumption_stage`는 run·stage·part 고유 호출 결과와 시작/종료·소요 시간·오류·암호화
content object FK를 가진다. 세 표는 DB trigger와 ORM에서 UPDATE/DELETE를 거부한다.
app은 입력/실행 INSERT와 세 표 SELECT, worker는 결과 INSERT와 세 표 SELECT만 받는다.
실행 상태/lease는 기존 work_job, 호출 시작은 원문 없는 audit_event로 기록한다.
[REST 및 결과 계약](0923_assumption-analysis/spec.md).


## 가상 SI 3사 데모 계약 (2026-10-09, DEMO-01·02 데모 브랜치 구현; 2026-10-10 DEMO-03 구현, 실제 Luna 대표 1건은 2026-10-11 DEMO-05로 이관)

DEMO-01은 별도 데모 브랜치의 migration에 `ProfileVersion`·`DeepReview`·
`PreSpecCompanyFitAttempt`의 nullable `company_id`와 회사/profile 소속 제약을 추가했다.
기존 행은 NULL 계보로 보존하고 main·운영에는 미반영이다.
DEMO-02는 migration `0035_company_knowledge`로 `knowledge_ontology_version`·`company_knowledge_source`·`company_knowledge_version`·
`company_knowledge_node`·`company_knowledge_edge`·`company_knowledge_binding`·`company_knowledge_binding_event`를 추가했다.
version·source·node·edge·event는 append-only이고 binding pointer만 갱신되며, 회사·profile·source·graph 소속은 composite FK로 묶는다. 권한은 `scripts/runtime-privileges.sql`이 부여한다.
승인 binding·회사 분석 입력과 실행 저장은 DEMO-03의 미구현 후속 범위며 기존 불변 입력·근거 FK·슬롯 1개 계약을 유지한다.
DEMO-03는 migration `0036_company_analysis`로 `company_fit_policy_version`(id, sha256 UNIQUE, payload, created_at; UPDATE/DELETE 거부 trigger)을 추가하고,
`prespec_company_fit_attempt`에 `company_fit_policy_version_id`(FK)·`graph_version_id`·`provenance_jsonb`를 더해 `deep_policy_version_id`·`model_revision`을 nullable로 바꿨다(정책 FK는 purpose별 하나 CHECK, legacy 행 hex64 유지, 회사 행은 선언 revision 또는 NULL). (graph, company, profile)→`company_knowledge_version` 복합 FK와 회사 행의 동결 입력 일치 INSERT guard(nonce=행 id, 개요 문서 포함 문서 집합, bundle/target null)를 둔다.
`deep_review`에 `graph_version_id`+복합 FK+불변 trigger를 더하고 `uq_deep_review_company_inputs`에 graph_version_id를 포함했다. `deep_review_preview`에 `company_id`·`graph_version_id`·`provenance_jsonb`(0034 scope trigger 재사용), `deep_review_approval`에 `company_id`를 더했다. 회사 열이 있는 행이 존재하면 upgrade를 거부하고 빈 DB downgrade를 검사했다. EvidenceRef·ReportRevision·ValidationRun에는 회사 열을 두지 않고 `deep_review_id`로 계보를 잇는다. 권한은 `scripts/runtime-privileges.sql`(app: fit policy SELECT/INSERT; worker: 지식 테이블·fit policy SELECT, binding_event 제외, 쓰기 없음).
[ADR-0070](tracking/decisions/0070-multi-company-knowledge-demo.md) · [공통 계약](work/demo-contract.md) · [기능 로드맵](work/constitution/roadmap.md).
