# 그래프 근거 기반 회사 핏과 Luna 심층검토 — spec

- 기능 ID: `DEMO-03-grounded-analysis`
- 작성일: 2026-10-06 (같은 날 재계획 개정)
- 근거: [intent](intent.md), [공통 계약](../../../../demo-contract.md) §5·6·9 및 §10의 “조회용 동결 계보”
- 상태: 구현 목표. 현재 제품 계약과 구별한다. 데모 브랜치 전용이며 운영에 배포하지 않는다.

## 큰 틀 문서와의 관계

ADR-0070(개정 포함) 및 기존 정본의 DEMO 목표 절을 구체화한다.
공통 계약 §5·6·9 및 §10의 “조회용 동결 계보”의 필드·필수/nullable·enum 전체·식별/유일성·실패 규칙은 이 spec의 일부다.
기존 단일회사 wire·불변성은 유지한다. 계약 변경은 관련 기능/정본에 함께 반영한다.

## 입력·출력 계약 및 저장

공통 v7 개요를 사용한다. 회사 의존 v8 예비 판정을 공통 결과로 재사용하지 않는다.
graph path뿐 아니라 원문 requirements·profile facts·원본 evidence를 함께 모델에 전달한다.
검색 경로는 충족 판정이 아니다. 원문에 없는 인력·자격·실적을 생성하지 않는다.
공통 §5의 용어 정규화·한글 부분 문자열/영문 경계 일치·concept/alias 매핑·3 hop·필수 정보 보존·분할/coverage를 그대로 구현한다.
원문 단위는 기존 분할기 `DeepReviewService._requirements`의 출력과 requirement_id 형식을 그대로 쓰고, 필드가 빠진 fallback unit은 company_input_invalid로 실패한다.

회사 핏은 승인 흐름 없이 `enqueue-company-fit` CLI(공통 §9)로 attempt를 만든다. CLI는 worker DB 역할로 실행하며
기존 worker-only attempt INSERT 권한을 app 역할에 열지 않는다. 입력은 enqueue transaction에서 동결해 attempt에 저장한다.
기존 runner는 company_id 유무로 입력 구성기를 분기해 claim하고, 기존 자동 enqueue는 NULL 행만 만든다(DEMO-01 경계 유지).
심층은 기존 DeepReviewPreview·DeepReviewApproval에 company_id를 더해 재사용한다. 새 preview/request/approval/receipt 테이블은 만들지 않는다.
요청 body·replay·preview_used/preview_changed 규칙은 기존 Luna와 같고, worker의 approval_invalid 검사는 회사 preview에도 적용한다.
회사 경로 자격은 SW사업대상=Y·ready bundle·completed v7 개요·활성 binding·정책이다. C-1 `우선 검토` 등급은 요구하지 않으며,
이를 위해 기존 `effective_grade` 함수를 재사용하지 않고 SW사업대상만 보는 판정을 둔다(legacy grade_not_priority는 NULL 경로에만 남는다).
DEMO-01 회사 FK에 graph/profile/company 일치를 강제하는 복합 FK를 추가한다.
심층 unique 입력 키에 graph_version을 포함한다. 동일 입력 생성은 409 review_exists이며 정확한 request_id replay만 기존 응답을 반환한다. 실패 재시도는 target_review_id를 고정한 새 승인+attempt다.
새 graph/profile로 재분석하면 새 review를 만든다. 입력 변경 뒤 기존 실행은 승인·enqueue 당시 값을 유지한다.
새 Luna demo 정책은 DEMO-00이 검증한 `analysis-policy-luna-v4`에 회사·그래프 입력 설명만 더하며 v3 검증 off는 계승하지 않는다.
Luna 분석 정책은 이미지 파일과 `_approved_policy_path` 매핑으로만 인정되므로 demo 정책에 DEMO-00이 정한 고유 식별 필드·매핑·테스트를 추가한다.
핏 attempt의 정책 FK는 purpose별 하나(공통 §8 CHECK)이며, 승인 때 심층 입력을 다시 만들 때는 저장된 preview id를 nonce로 쓴다(공통 §9).
fit 정책(CompanyFitPolicyVersion)도 같은 방식으로 import CLI가 이미지의 승인 파일 bytes와 대조한다.
considered_claim_ids는 입력 verified claims이고 출력 로컬 ID와 다름을 명시한다. dangling evidence·coverage·숫자·인용 검사를 유지한다.
합성 worker 슬롯/lease/heartbeat와 제한된 transport 재시도 정책을 그대로 사용한다.
회사별 목록·비교·상세 projection은 lifecycle 공개 확장점으로 제공해 역방향 import를 만들지 않는다.
deep_review가 lifecycle의 새 공개 파일(`schemas/companies.py` 등)을 import하면 `tests/app/boundary_map.py` 공개 표면을 갱신한다.
새 테이블·열 권한은 `scripts/runtime-privileges.sql`, 새 오류 code는 응답 router 허용 목록에 등록한다.
DEMO-03은 fake 모델을 쓴 제품 경로 통합까지 인수한다. 실제 18/9건은 DEMO-05가 소유한다.

## 인터페이스·상태·실패

공통 계약 §5·6·9 및 §10의 “조회용 동결 계보”의 endpoint/CLI/DTO를 사용한다.
unknown/null·준비 전·stale·실패·참조 표식을 성공/부적합으로 변환하지 않는다.
쓰기/전송 전에 회사·version·hash를 검사한다. 원문 경로·secret·모델 본문을 일반 응답/로그에 노출하지 않는다.

## 설정 키와 기본값

| 키 | 기본값 | 허용/적용 | 근거 |
|---|---|---|---|
| BIDOPS_DEMO_ENABLED | false | bool; 격리 데모에서 명시 활성 | 운영 경계 |
| BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED | false | 기존 bool | 사람 요청 분석 |
| BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID / BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID | null | UUID; 목적별 필수, 전역 fallback 없음 | 공통 §9 |
| BIDOPS_PRESPEC_COMPANY_FIT_ENABLED | false | 기존 bool; enqueue CLI·worker gate | 기존 핏 |
| chunking.path_limit_per_requirement | 32 | 양의 정수, tunable; demo 정책 loader가 직접 검사 | 공통 §9 |

## 결정과 이유

| 결정 | 근거 | 적용하지 않는 대안 |
|---|---|---|
| 핏 CLI·무승인 | 사설 vLLM이며 기존 핏도 건별 승인 없음, 2주 범위 | 핏 preview/approve·승인 화면 |
| 기존 Luna 승인 재사용 | 같은 외부 전송 경계, 기존 화면·worker 검사 재사용 | 새 CompanyAnalysis* 테이블 |
| SW=Y 자격 | C-1 등급은 실제 회사 프로필 판정 | 우선 검토 요구 |
| 기존 분할기 ID | 기존 경로 무변경 | 새 doc:… 형식 |
| 단일 원본에서 근거 생성 | 불변성·그래프 분석 활용 요구 | 프로필/그래프 별도 편집 |
| 외부 그래프 서비스 | N/A — 업무 온톨로지·기존 PostgreSQL 사용 | RDF/OWL·별도 DB |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | graph 입력/동의어/모호함/한글 조사·복합어/영문 경계 | 허용 사전만 매핑·"ai"가 "mail"에 미일치·unknown/필수 자격·coverage 보존·fallback unit 실패 | 단위 |
| T2 | 심층 승인/소속/hash/replay, 핏 enqueue 소속/중복 | 불일치 호출 전 거부·replay 작업 1개·같은 회사·공고 활성 핏 중복 거부 | API/PG |
| T3 | mismatch/unknown 수동 심층, 우선 검토 아닌 SW=Y 공고 | 준비·승인 충족 시 실행·fit 불변·C-1 등급 무관 | 통합 |
| T4 | 서비스 fake 종단 | 핏: enqueue→claim→결과, 심층: preview→approve→claim→3단계→보고서/근거 company/graph 일치 | PG 통합 |
| T5 | Luna ID/숫자/coverage | 필수 근거 오류/누락은 실패·원응답 보존·v4/demo 정책 매핑과 기존 정책 호환 | 회귀 |
| T6 | 현재성/재시도/버전 | 옛 결과 stale·같은 review 새 attempt·새 graph 새 review·current_attempt별 동결 provenance | API |
| T7 | 목록/비교/provider 부재 | 회사 혼합 없음·missing/null/다른 입력·N+1 없음·queued/completed GET의 provenance/hash가 동결 snapshot 및 최상위 identity와 일치 | 통합 |
| T8 | 슬롯/승인 없는 외부 전송 | 심층 무승인·hash 불일치 호출 0·동시 슬롯 1·안전 로그·legacy runner가 회사 행을 NULL 입력으로 처리하지 않음 | 통합 |

## 컨벤션 반영 항목

새 회사 경로·origin·graph/version identity는 공통 계약, 상태 분리는 business-rules,
DB·외부 호출은 해당 정본의 DEMO 절에 반영한다. 구현 목표를 현재 동작으로 표시하지 않는다.
