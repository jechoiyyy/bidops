# BidOps 심층 검토 설계 — Cold Session 인계

> **2026-08-26 구현 완료로 대체됨:** 본문의 워크트리 경로, 구현 전 지시,
> 확장안과 미결정 목록은 역사 참고용이다. 현재 권위 계약은
> `docs/business-rules.md`, `docs/deep-review-erd.md`, `docs/contracts.md`,
> `docs/security.md`, `docs/architecture.md`다. 본문에서 언급하는 `.dryforge` 세 문서는
> 설계 기준선 commit `d5941c7`의 Git 이력에만 보존되어 있다.

이 문서는 이전 대화가 없는 새 세션에서 PostgreSQL ERD 검토와 심층 검토 기능 설계를 안전하게 이어가기 위한 인계 문서다.

## 1. 새 세션 시작용 프롬프트

아래 블록을 새 세션의 첫 메시지로 그대로 사용할 수 있다.

```text
다음 프로젝트의 BidOps 첨부문서 심층 검토 기능 설계를 이어서 진행해줘.

작업 워크트리:
/home/jechoi/orca/workspaces/side/bidops-deep-review

프로젝트 디렉터리:
/home/jechoi/orca/workspaces/side/bidops-deep-review/bidops-agent

브랜치:
bidops-deep-review

먼저 다음 파일을 모두 읽어:
- docs/deep-review-cold-session-handoff.md
- docs/deep-review-erd.md
- .dryforge/spec.md
- .dryforge/plan.md
- .dryforge/handoff.md
- web/backend/app/models.py
- web/backend/app/db.py
- web/backend/app/ingest/loader.py
- web/backend/app/services/attachments.py
- docs/architecture.md
- docs/contracts.md
- docs/operations.md
- docs/security.md

현재 목표는 유효 등급이 우선 검토인 공고의 모든 첨부문서를 안전하게 구조화하고, 담당자가 문서 준비 완료를 확인한 뒤 Qwen 심층 분석을 수행하여 모든 주장과 수치의 원문 근거를 실무자가 확인할 수 있는 웹 보고서를 제공하는 것이다.

애플리케이션 정본 DBMS는 PostgreSQL로 확정됐다. 기존 SQLite는 일회성 이관 원본이다. 현재 ERD는 검토안이며 구현 승인된 최종 ERD가 아니다. Claude Opus 5 high의 독립 DB 리뷰에서 발견된 P0 항목을 먼저 검토하고 사용자와 결정한 뒤 ERD와 dryforge 문서를 갱신해야 한다.

이 세션에서는 바로 구현하거나 dryforge go를 실행하지 마라. 먼저:
1. 현재 git status와 파일 충돌 여부를 확인한다.
2. 인계 문서의 확정 사항과 미결정 사항을 구분한다.
3. P0 차단점을 ERD에 어떻게 반영할지 제안한다.
4. 사용자 결정이 필요한 항목을 추천안과 함께 순서대로 검토한다.
5. 사용자 승인 후 docs/deep-review-erd.md와 .dryforge 3개 문서의 정합성을 함께 갱신한다.

메인 워크트리 /home/jechoi/projects/side에는 다른 세션과 사용자 미커밋 파일이 있다. 읽기 전용 참고만 가능하며 수정·복사·삭제·정리하지 마라. 현재 bidops-deep-review 워크트리 밖의 파일을 수정하지 마라.

답변과 문서는 한국어로 작성해. 설계를 무조건 승인하지 말고 DB 제약, 재현성, 이관, 보안, 운영 복구 관점에서 비판적으로 검토해.
```

## 2. 작업 위치

| 항목 | 값 |
|---|---|
| Git 저장소 | `/home/jechoi/orca/workspaces/side/bidops-deep-review` |
| 프로젝트 | `/home/jechoi/orca/workspaces/side/bidops-deep-review/bidops-agent` |
| Orca 워크트리 | `bidops-deep-review` |
| Git 브랜치 | `bidops-deep-review` |
| 기준 commit | `3e076156b44d5e13a12fbf14dc733075fb8b8ab3` |
| 부모 워크트리 | `/home/jechoi/projects/side` |
| 현재 설계 상태 | 사용자 검토 중, 구현 미착수 |

이 워크트리는 메인 워크트리에서 동시에 실행되던 두 dryforge ready 작업의 `.dryforge` 파일 충돌을 피하기 위해 분리했다.

## 3. 반드시 읽을 문서

### 권위 설계

| 파일 | 역할 |
|---|---|
| `.dryforge/spec.md` | 목표, 상태, JSON/API/근거 계약 |
| `.dryforge/plan.md` | 구현 작업 T1–T11과 의존 관계 |
| `.dryforge/handoff.md` | 실행 경계와 사용자 변경 보호 |
| `docs/deep-review-erd.md` | PostgreSQL 스키마별 ERD 검토안 |

### 기존 구현과 운영 계약

| 파일 | 확인 목적 |
|---|---|
| `web/backend/app/models.py` | 현재 SQLite 테이블, FK와 cascade |
| `web/backend/app/db.py` | 현재 SQLite WAL 설정과 SQLAlchemy session |
| `web/backend/app/ingest/loader.py` | 첨부 재적재·물리 삭제 동작 |
| `web/backend/app/services/attachments.py` | 수동 첨부 저장과 경로 정책 |
| `docs/architecture.md` | 현재 구성요소와 의존 방향 |
| `docs/contracts.md` | 현재 API·산출물 계약 |
| `docs/operations.md` | 현재 SQLite·Docker 운영 방식 |
| `docs/security.md` | 파일·원문·비밀정보 경계 |

## 4. 제품 목표

모니터링에서 유효 등급이 `우선 검토`인 공고에 대해 다음 흐름을 완성한다.

```text
공고 모니터링·사람 등급 정정
          ↓
      유효 등급 확인
          ↓
첨부 확보·업로드·안전 검사
          ↓
HWPX/PDF/OCR 구조화와 원문 locator 생성
          ↓
역할·효력일·정정·최신본을 담당자가 확인
          ↓
       문서 준비 완료
          ↓
bundle + profile version + policy version 고정
          ↓
Qwen 단계별 분석과 결정적 검증
          ↓
근거 중심 웹 보고서와 사람 최종 의견
```

보고서의 사실·수치·자격·요구사항·배점·위험·회사 역량 주장은 원문 위치 또는 불변 회사 증빙으로 이동할 수 있어야 한다. 근거가 없으면 추정하지 않고 `알 수 없음`, `미확인`, `계산 불가`로 남긴다.

## 5. 사용자와 확정한 사항

### 업무 흐름

1. 사람의 최신 정정 등급이 시스템 등급보다 우선한다.
2. 분석은 첫 첨부 업로드가 아니라 담당자의 `문서 준비 완료` 확인 후 시작한다.
3. 새 첨부, 정정문서, OCR 정정은 새 bundle과 새 분석을 만들고 이전 결과를 보존한다.
4. 역할·효력일·대체 관계·최신본 충돌이 남으면 분석을 시작하지 않는다.
5. 진행, 실패, 사람 확인 필요, 검증 실패를 웹에서 표시한다.
6. 시스템 권고와 사람 최종 의견을 분리한다.
7. 사람 최종 의견은 `추진`, `조건부 추진`, `보류`, `검토 종료`다.
8. 검증 실패 보고서에도 경고 확인과 사유 후 최종 의견을 남길 수 있으나 실패 라벨은 유지한다.
9. 새 분석은 과거 사람 수정과 최종 의견을 자동 승계하지 않는다.

### 문서와 근거

1. HWPX, PDF, 스캔 PDF/이미지를 제한형 문서 MCP 계약으로 처리한다.
2. OCR은 페이지 이미지, bbox, confidence를 보존한다.
3. 사람 OCR 정정은 원본을 덮지 않고 새 document version을 만든다.
4. ClamAV 미가용·불확실 결과는 격리한다.
5. 수동 격리 해제에는 별도 검사 증빙, 사유와 확인자가 필요하다.
6. 웹 URL 근거는 URL 문자열만 저장하지 않고 응답 바이트, 최종 URL, SHA-256과 locator를 고정한다.
7. 사람의 사실 수정에는 근거와 사유가 필요하고 재검증한다.

### 모델·도구·DB

1. 기본 모델은 사내 Ollama `qwen3.8:27b`다.
2. OpenAI 등 외부 상용 AI는 이번 범위에서 제외한다.
3. `https://github.com/jkf87/hwpx-skill.git`의 코드 사용·수정 허락을 사용자가 확보했다.
4. 고정 upstream commit은 `96a2633f23a08f707679d7e212ebdc59948260e6`이다.
5. 저작권·제3자 고지와 로컬 변경 내역을 보존한다.
6. 애플리케이션 정본 DBMS는 PostgreSQL로 확정했다.
7. 기존 SQLite는 일회성 이관 원본이며 reconciliation 완료 전 폐기하지 않는다.

### 회사 프로필과 정책

1. 기존 `docs/reference/company-profile.md`를 최초 프로필 버전으로 가져온다.
2. 이후 회사 프로필은 근거가 연결된 구조화 불변 버전으로 관리한다.
3. 분석 정책의 모델 endpoint/name, 단계별 prompt, validation rule도 불변 버전으로 관리한다.
4. 활성화 변경은 activation event와 current pointer로 기록하고 이후 분석에만 적용한다.

## 6. 아직 확정되지 않은 설계안

다음은 ERD에 표현됐지만 사용자가 최종 승인하지 않은 항목이다.

- PostgreSQL 내 `core`, `document`, `knowledge`, `analysis`, `ops` 다중 schema
- 기존 integer PK 유지 + 신규 UUID PK 혼합
- 원문·렌더·구조 payload를 MinIO/S3에 저장하고 block projection을 PostgreSQL에 저장
- 별도 Python worker와 `ops.work_job` DB queue
- `FOR UPDATE SKIP LOCKED` 기반 job claim
- 초기 worker 동시성 1
- BidOps와 Langfuse가 같은 PostgreSQL/MinIO 인스턴스를 쓰되 DB·bucket·role을 분리하는 배치
- Langfuse를 T7 분석 오케스트레이터 구현 시 tracing/evaluation 용도로 같이 연결
- Langfuse prompt management는 초기 범위에서 제외
- report revision의 overlay 저장 방식

## 7. 현재 ERD 구성

`docs/deep-review-erd.md`는 다음 영역으로 나뉜다.

| schema | 주요 테이블 |
|---|---|
| `core` | actor, run, notice, judgment, perspective, screening_evidence, review, attachment 등 |
| `document` | content_object, content_scan, document_version, structure/block, bundle/item, conflict, ocr_correction |
| `knowledge` | profile version/fact/evidence/activation, policy version/prompt/activation |
| `analysis` | deep_review, attempt, stage, llm_invocation, claim/evidence, report, validation, final_opinion |
| `ops` | work_job, work_job_event, idempotency_record, audit_event |

Langfuse 내부 PostgreSQL·ClickHouse·Redis·MinIO 테이블은 BidOps ERD에 포함하지 않는다. BidOps는 provider와 외부 trace/observation/generation ID만 저장하는 방향이다.

## 8. Claude Opus 5 high 독립 DB 리뷰

다음 명령 계열로 읽기 전용 리뷰를 수행했다.

```text
claude -p --model claude-opus-5 --effort high
```

Claude에는 `Read`, `Glob`, `Grep`만 허용했고 파일 수정 권한은 주지 않았다. 결론은 다음과 같다.

> 큰 계보와 버전 방향은 타당하지만, 많은 불변 조건이 산문에만 있고 DB constraint로 내려오지 않았다. 가장 시급한 결함은 ready bundle이 사후 변경되는 구조다.

### P0 — ERD 반영 전 구현 금지

#### P0-1. 기존 SQLite 컬럼 전량 대조

현재 ERD에는 `notice`의 기존 JSON·표본·분류 컬럼, `judgment.primary_focus`, `review.reviewer` 등 기존 데이터가 일부 빠져 있다.

조치:

- 기존 컬럼마다 `유지`, `리네임`, `jsonb 전환`, `폐기`를 표시하는 대조표 작성
- 폐기는 사용자 승인 필수
- ERD가 전체 DDL인지 핵심 컬럼 표시인지 명확히 표시

#### P0-2. Ready bundle 입력 스냅샷

현재 `document_bundle_item`이 document ID와 ordinal만 보존한다. 이후 document version의 역할·날짜·현재 여부·안전 상태가 바뀌면 과거 bundle도 바뀐다.

추가 권고 컬럼:

```text
role_at_confirmation
effective_date_at_confirmation
is_current_at_confirmation
safety_status_at_confirmation
structure_id_at_confirmation
content_sha256_at_confirmation
```

과거 bundle과 report는 snapshot만 읽어야 한다.

#### P0-3. Attachment soft delete와 출처 분리

현재 loader는 재적재 시 사라진 첨부를 `session.delete()`하고 ORM도 `delete-orphan`을 사용한다.

조치:

- `attachment.retired_at`
- unique `(notice_id, name, source_url)`
- `document_version.source_url`, `source_attachment_key` 자체 보관
- `attachment_id`는 nullable `ON DELETE SET NULL` 보조 참조
- attachment `delete-orphan` 제거

#### P0-4. FK 삭제 정책 표

핵심 이력은 `RESTRICT`다.

- run/notice/review/attachment
- document version/structure/bundle
- deep review/report/evidence

판정 재적재 시 함께 재생성되는 내부 detail과 verification answer만 제한적으로 `CASCADE`를 허용한다.

#### P0-5. Active attempt 하나를 DB로 강제

```sql
create unique index uq_attempt_active
on analysis.deep_review_attempt (deep_review_id)
where status in ('queued', 'running');
```

`deep_review.current_attempt_id`와 version 증가 규칙도 필요하다.

#### P0-6. Worker heartbeat와 fencing

추가 필드와 제약:

- `lease_heartbeat_at`
- `lease_fence`
- running lease 만료 partial index
- active `(job_type, aggregate_type, aggregate_id)` partial unique
- attempt/stage 저장 시 fence token 조건 검사
- status enum/check와 dead 전이

#### P0-7. Evidence를 deep review 범위로 제한

`analysis.evidence_ref`에 다음을 추가한다.

- `deep_review_id NOT NULL`
- `notice_id NOT NULL`
- `structure_id`

claim/report edit/validation의 evidence 연결은 deep review ID를 포함한 복합 FK로 범위를 강제한다.

#### P0-8. Report revision 정본 결정

Claude 권고는 overlay 방식이다.

- machine claim은 불변
- 사람 수정은 report edit로 저장
- 렌더 시 machine report + edit 합성
- 합성 결과 `rendered_sha256` 저장
- `report_revision.version` 추가
- `latest_validation_run_id` 추가
- unique `(report_revision_id, field_path)`

전체 claim/evidence를 revision마다 복제하는 방식은 비권장이다.

#### P0-9. Final opinion 검증 상태 스냅샷

추가 필드:

- `sequence`
- `validation_status_at_opinion`

필수 check:

```text
validation_status_at_opinion != failed
OR acknowledged_validation_failure = true
```

unique `(deep_review_id, sequence)`로 최신 의견 순서를 결정한다.

#### P0-10. Profile evidence occurrence/version 분리

```text
profile_evidence_source
  1 ── N profile_evidence_source_version
             1 ── 0..1 confirmation
```

URL 재캡처와 파일 교체 시 어느 불변 원문을 사람이 확인했는지 표현할 수 있어야 한다.

#### P0-11. Profile/policy 불변성과 pointer 강제

- pointer UUID PK + 고정 key check
- `(pointer_key, pointer_version)` unique
- prompt unique `(policy_version_id, stage)`
- stage 7개 check
- 불변 버전 테이블의 app role UPDATE/DELETE 권한 회수
- activation은 expected pointer version 조건부 update

#### P0-12. SQLite 첨부 해시 이관 기준

기존 attachment에는 SHA-256이 없다.

- 저장 파일이 있으면 이관 시 hash 계산 후 content object 생성
- URL만 있으면 `not_acquired` 상태로 남기고 hash reconciliation 대상에서 제외
- 이관 대조는 DB row count뿐 아니라 파일 존재와 실제 hash를 검증

## 9. Claude가 추가로 권고한 테이블

| 테이블 | 이유 |
|---|---|
| `document.document_structure_page` | 페이지 크기와 렌더 이미지 객체 보존 |
| `document.document_table_cell` | HWPX/PDF table-cell locator를 FK 가능한 형태로 해소 |
| `document.safety_release` | 수동 격리 해제 증빙·사유·확인자 보존 |
| `knowledge.profile_evidence_source_version` | 증빙 occurrence와 불변 원문 버전 분리 |
| `ops.work_job_lease` | 선택 사항. 고빈도 heartbeat로 인한 work_job bloat 분리 |
| `core.notice_effective_grade` | 선택 사항. 결정적 등급 조회 projection/view |

## 10. 주요 P1 운영 피드백

- `document_structure`에 payload SHA-256, bytes, page count, block count 필요
- document block의 대형 text 저장 상한과 source of truth 결정 필요
- table cell을 별도 테이블 또는 자식 block으로 정규화할지 결정 필요
- `safety_release`를 문서·프로필 증빙 공통으로 사용할 수 있게 설계
- deep review/stage/claim의 상태 enum과 교차 check 명시
- claim과 evidence가 같은 deep review에 속하도록 복합 FK
- effective grade의 latest 기준을 `review.updated_at DESC, id DESC`로 고정
- SQLite integer PK 이관 후 PostgreSQL sequence `setval` 필수
- SQLite 이관은 staging schema + reconciliation + cutover 방식을 권고
- 컷오버 중 쓰기 차단 또는 서비스 중단 창 필요
- PostgreSQL과 MinIO 백업은 immutable object 특성을 이용해 MinIO 먼저, DB 나중 순서 권고
- DB/worker connection pool 분리
- 스키마별 `bidops_app`, `bidops_worker`, `bidops_migrate`, `bidops_ro` 권한 설계
- 한국어 전문검색이 요구사항이 아니라면 확장과 인덱스를 초기 범위에서 제외

## 11. Langfuse 관련 결론

현재 합의된 사항이 아니라 검토안이다.

- Langfuse 내부 DB를 직접 참조하지 않는다.
- `deep_review_attempt`에 provider/trace ID, stage와 invocation에 observation/generation ID를 둔다.
- provider는 attempt 단위로 고정한다.
- 원문 파일, 전체 구조, 회사 증빙은 Langfuse에 보내지 않는다.
- tracing 장애는 분석을 실패시키지 않는 fail-open이다.
- Langfuse에도 input/output을 보내지 않고 BidOps에도 hash만 남기면 실제 모델 응답이 사라진다.
- `llm_invocation.response_content_object_id`로 모델 응답 원문을 암호화 객체 저장소에 제한 기간 보존하는 방안을 검토한다.
- 1인 운영이면 Langfuse 배포를 늦추고 nullable telemetry ID와 `llm_invocation`부터 구현하는 선택도 가능하다.
- prompt management는 BidOps policy version과 권위가 겹치므로 초기에는 사용하지 않는 방향이 권고안이다.

## 12. 다음 세션에서 사용자와 결정할 순서

한꺼번에 전부 묻지 말고 아래 순서로 검토한다.

### 1차 — 입력 재현성과 보고서 정본

1. Ready bundle snapshot 컬럼 추가 — 추천: 추가
2. Attachment soft delete 전환 — 추천: 전환
3. Report revision 저장 — 추천: overlay
4. Evidence 공유 방식 — 추천: deep review 내부에서 deduplicate하고 복합 FK로 범위 제한
5. Final opinion 검증 상태 snapshot — 추천: 추가

### 2차 — 문서 구조 저장

1. 객체 저장소 payload가 정본이고 PostgreSQL block/cell은 projection인지
2. table cell을 별도 테이블로 둘지 자식 block으로 둘지
3. 페이지 메타데이터를 별도 table로 둘지
4. OCR correction의 원문/정정 block 연결 방식
5. content object 암호화 key rotation을 지원할지

추천 방향:

- 원본 구조 JSON은 객체 저장소 정본
- `document_structure_page` 별도 테이블
- `document_block` + `document_table_cell` projection
- 생성기 버전과 payload SHA-256으로 projection 재생성 가능

### 3차 — Worker와 멱등성

1. job heartbeat/fencing 방식
2. idempotency key 범위를 spec 4튜플과 ERD 5튜플 중 무엇으로 통일할지
3. replay 응답 body를 snapshot할지
4. multipart request hash에 파일 바이트 hash를 포함할지

추천 방향:

- active job partial unique
- heartbeat + fence token
- response body snapshot 저장
- 업로드 파일 SHA-256을 request hash에 포함

### 4차 — PostgreSQL 이관과 운영

1. staging schema swap 사용 여부 — 추천: 사용
2. 컷오버 중 쓰기 중단 허용 여부
3. actor를 환경 운영자로 시작할지 로그인 사용자로 시작할지
4. 예상 월 공고·문서·페이지·block 수
5. PostgreSQL 버전과 확장 설치 가능 여부
6. RPO/RTO와 보존 기간

### 5차 — Langfuse

1. T7부터 tracing adapter를 같이 넣을지
2. self-hosted Langfuse 배포를 첫 운영에 포함할지
3. 모델 응답 원문 보존 여부와 기간
4. MinIO 인스턴스를 BidOps와 Langfuse가 공유할지

추천 방향:

- 코드의 tracing adapter와 nullable external ID는 T7에서 구현
- Langfuse 실제 배포는 기능 완료 뒤 선택 가능
- prompt management는 제외
- 모델 입력 원문은 전송하지 않음
- 모델 응답은 BidOps 암호화 객체로 제한 보존

## 13. ERD 수정 완료 기준

다음이 모두 충족되어야 구현 단계로 넘어간다.

- 기존 SQLite 컬럼 전량 이관 대조표가 있다.
- 모든 핵심 FK의 `ON DELETE`가 명시되어 있다.
- ready bundle 입력이 사후 변경되지 않는다.
- 동시에 active attempt/job 하나만 DB가 강제한다.
- worker fencing으로 만료 worker의 쓰기를 막는다.
- claim과 evidence가 deep review 범위를 벗어나지 않는다.
- 보고서 기계 원본, 사람 edit, 검증 입력의 정본 관계가 하나로 정해졌다.
- profile evidence occurrence와 immutable source version이 분리됐다.
- profile/policy 불변성과 pointer 동시성이 DB 제약·권한으로 강제된다.
- final opinion의 검증 실패 확인이 DB check로 강제된다.
- SQLite 이관·검증·컷오버·롤백 절차가 있다.
- PostgreSQL과 객체 저장소의 백업·복구 정합성 절차가 있다.
- Langfuse와 BidOps의 데이터 권위·보존 경계가 정해졌다.

## 14. 작업 안전 규칙

- 부모 메인 워크트리 `/home/jechoi/projects/side`는 수정하지 않는다.
- 메인 워크트리의 미커밋·미추적 파일은 사용자 소유다.
- 현재 사용자가 검토 중이므로 ERD 승인 전 애플리케이션 구현을 시작하지 않는다.
- `.dryforge/spec.md`, `plan.md`, `handoff.md`는 ERD 결정이 끝난 뒤 세 파일을 함께 갱신한다.
- 기존 API·테스트를 단순히 새 설계에 맞춰 삭제하지 않는다.
- 첨부, 리뷰, 보고서와 사람 의견의 과거 이력을 물리 삭제하지 않는다.
- Langfuse나 모델 호출 실패가 업무 정본을 손상시키지 않게 한다.
- 구현을 시작할 때도 사용자가 승인한 범위를 넘어 외부 서비스나 추가 인프라를 자동 도입하지 않는다.
