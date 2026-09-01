# BidOps 발주계획 C-2 선별 제품 요구사항

| 항목 | 내용 |
|---|---|
| 문서 상태 | 초안 — 구현 범위 합의용 |
| 문서 버전 | v0.1 |
| 기준일 | 2026-09-01 |
| 대상 사용자 | 기획·사업개발 담당자, 운영자 |
| 채택 방식 | `BM25 Top 300 + Qwen` |
| 관련 결정 | [ADR-0037](tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md) |
| 구현 계획 | [PLAN.md](PLAN.md) |

이 문서는 나라장터 발주계획을 수집한 뒤 C-2 1차 선별을 수동으로 실행하고, 결과를 사람이
검토할 수 있게 만드는 제품 요구사항을 정의한다. 기존 생애주기 전체 요구와 충돌할 때는
`business-rules.md`, `security.md`, `contracts.md`와 채택된 ADR이 우선한다.

## 1. 배경

발주계획은 입찰공고보다 이른 시점에 사업 신호를 제공하지만, 관측 규모가 3일 약 1,200건,
1주 약 2,000건이라 전수 사람 검토가 어렵다. 동시에 제목만으로 판단하는 단계이므로 관련
사업을 확정하거나 참여 가능성을 판단하는 근거로는 부족하다.

2026-08-27 00:00부터 2026-08-31 00:00 미만 KST의 일반용역·기술용역 625건을 고정해
비교한 결과, BM25 상위 300건에 Qwen을 적용하는 방식이 C-2로 채택됐다. 당시 측정값은
관련 59건 중 57건 유지, 검토 유지 recall 96.61%, 검토 후보 127건, Qwen 처리시간
598,947ms, 총 44,183 token이다. BM25 단계에서 빠진 낮은 우선순위 2건은 결정권자가
명시적으로 수용했다.

현재 저장소에는 다음 기반이 이미 있다.

- `collected-order-plans.json` / `bidops.collected-order-plans.v1` 생산자
- PostgreSQL의 누적 `OrderPlan`, 회차별 `OrderPlanObservation`
- 발주계획·사전규격·입찰공고를 연결하는 `Opportunity`, `OpportunityLink`
- 사설 vLLM 연결용 목적별 egress, 분석 worker, 모델 응답 보관 경계
- C-2 비교 실험 코드와 불변 실행 증거

반면 C-2를 제품에서 실행하는 adapter, 전용 실행·결과 계약, 수동 실행 API와 검토 화면은
아직 없다. 기존 공고의 다섯 관점 판정은 적합성 등급과 참여 준비 상태를 다루므로 발주계획의
단순 관련성 선별을 대신하지 않는다.

## 2. 제품 목표

MVP의 목표는 다음 네 가지다.

1. 수집된 발주계획 전체를 삭제 없이 보존하면서 BM25 상위 300건을 결정적으로 선택한다.
2. 상위 300건만 승인된 회사 역량 요약과 제목으로 사설 vLLM Qwen에 전달한다.
3. Qwen의 `relevant|uncertain`을 사람 검토 대상으로 제시하고, 제외·실패 이유와 실행
   계보를 함께 보여 준다.
4. 같은 입력·정책·모델 binding으로 결과를 재현하고 소요시간·token·실패를 비교할 수 있게
   한다.

제품은 사람의 탐색 비용을 줄이는 의사결정 지원 도구다. 관련성 선별 결과가 적합성 등급,
참여 준비 상태, 추적 선택 또는 최종 입찰 Go/No-Go를 자동 결정해서는 안 된다.

## 3. 범위

### 3.1 MVP 포함 범위

| 영역 | 요구사항 |
|---|---|
| 입력 | 이미 수집·적재된 발주계획 회차를 사람이 선택한다 |
| 실행 | 사람이 명시적으로 C-2 실행을 요청한다 |
| 1단계 | 전체 제목을 BM25로 순위화하고 상위 300건을 고정한다 |
| 2단계 | Qwen이 25건씩 고정 batch로 `relevant|not_relevant|uncertain`을 반환한다 |
| 결과 | 전체 모집단의 stage, BM25 점수·순위, Qwen 결과·사유·실패를 보존한다 |
| 검토 | `relevant|uncertain` 후보를 기본 목록으로 제공하고 전체·탈락·실패도 조회할 수 있게 한다 |
| 계측 | 실행·batch별 시간, 입력·출력·총 token, 성공·실패 건수를 기록한다 |
| 감사 | 요청자, 목적, 허용 payload 필드, binding, 시작·종료·결과를 안전한 metadata로 남긴다 |

### 3.2 고도화 단계로 미루는 범위

- scheduler에 의한 자동 수집·자동 C-2 실행
- always-on 활성화와 누락 기간 자동 회수
- 월요일·목요일 검토 큐 자동 생성 또는 알림
- 메일·메신저·외부 시스템 알림
- 여러 Qwen batch의 동시 모델 호출
- BM25 이외의 dense·RRF를 운영 fallback으로 사용하는 기능

고도화 단계에서도 scheduler는 같은 execution·attempt·artifact 계약에 작업을 넣을 뿐,
별도 선별 규칙이나 모델 호출 경로를 만들지 않는다.

### 3.3 명시적 제외 범위

- hosted OpenAI 또는 다른 모델로의 자동 fallback
- draft인 negative prompt v4의 자동 승인·적용
- 모델이 만든 정답을 사람 gold로 승격하는 기능
- 발주기관 연락, 입찰서 제출, 자동 Go/No-Go
- 사전규격·입찰공고의 첨부 본문을 발주계획 1차 선별 payload에 포함하는 기능
- `SW사업대상` 값으로 일반용역·기술용역 원본을 선제 제거하는 기능

## 4. 사용자와 핵심 흐름

### 4.1 기획·사업개발 담당자

담당자는 수집 회차와 C-2 binding을 확인하고 실행을 요청한다. 실행이 끝나면 기본적으로
`relevant|uncertain`만 검토하되, BM25 탈락과 Qwen 비관련·실패 결과도 필터로 확인할 수
있어야 한다. 사람의 피드백은 모델 결과와 별도 기록으로 남아야 한다.

### 4.2 운영자

운영자는 승인된 vLLM endpoint·literal host allowlist·모델 revision, 회사 역량과 prompt의
승인본, PostgreSQL·MinIO 권한과 백업 상태를 관리한다. 앱 시작이나 migration만으로 정책이나
실행을 활성화하지 않는다.

### 4.3 MVP 핵심 흐름

```text
사람이 발주계획 수집 회차 선택
  → 입력 완전성·binding·전송 필드 미리보기 확인
  → 수동 C-2 실행 요청과 감사 기록
  → 전체 모집단 BM25 순위화
  → 상위 300건을 25건씩 Qwen 판정
  → 결과 검증·불변 artifact·DB 적재
  → relevant|uncertain 사람 검토
  → 사람 피드백과 후속 opportunity 상태는 별도 기록
```

## 5. 기능 요구사항

### 5.1 입력과 실행

| ID | 요구사항 |
|---|---|
| FR-001 | 실행은 `bidops.collected-order-plans.v1`과 정확한 source run·artifact digest를 고정해야 한다. |
| FR-002 | 부분 수집 회차는 완전한 회차처럼 실행하지 않는다. 운영 정책이 허용하지 않으면 시작을 거부하고 사유를 보여 준다. |
| FR-003 | 실행 요청 전 대상 건수, 모델, 허용 payload 필드, prompt·회사 역량·BM25 config digest를 확인할 수 있어야 한다. |
| FR-004 | 실행 생성은 담당자 이름, idempotency key 또는 request ID를 요구하고 202 상태로 즉시 반환해야 한다. |
| FR-005 | 실행은 `대기`, `실행 중`, `중지 요청`, `성공`, `부분 성공`, `실패`, `중단됨`을 구분해야 한다. |
| FR-006 | 재실행은 과거 실행을 수정하지 않고 새 execution ID와 계보를 만들어야 한다. |

### 5.2 BM25 1단계

| ID | 요구사항 |
|---|---|
| FR-101 | 회차의 전체 발주계획을 대상으로 승인된 BM25 config를 사용한다. |
| FR-102 | 같은 정규화 입력과 config는 같은 점수·순위·Top 300을 만들어야 한다. |
| FR-103 | 동점 순위의 tie-break 규칙은 계약으로 고정하며 실행마다 바뀌지 않아야 한다. |
| FR-104 | 상위 300건만 `selected`, 나머지는 `filtered_out`으로 기록한다. |
| FR-105 | `filtered_out`을 Qwen의 `not_relevant`로 표현하지 않는다. |
| FR-106 | 모집단이 300건 이하인 경우의 처리와 감사 표본 정책은 운영 정책 확정 전까지 fail closed한다. |
| FR-107 | BM25 실패 또는 입력 누락은 임의 점수로 보정하지 않고 실행 실패 또는 건별 검토 대기로 보낸다. |

### 5.3 Qwen 2단계

| ID | 요구사항 |
|---|---|
| FR-201 | 입력은 발주계획 식별자·제목과 별도 승인된 최소 회사 역량 요약만 허용한다. |
| FR-202 | Qwen model은 `qwen3.8-27B`, revision은 `6ae70ca30563209f09ec0114ce5813f7a232b38e5bb409f2adbd0e9bbe318b11`에 고정한다. |
| FR-203 | 승인 prompt는 `order-plan-batch-relevance-v3`, SHA-256 `639f7332e1120a41b2e8d8306126f121ae1ed37068a81b1687aff9ce66ab9d12`에 고정한다. |
| FR-204 | 회사 역량 승인본 SHA-256은 `8f60dfece1934bdf857cd7e57d0fdd1860d01871131d98c3f2e8f9d71f271eae`와 일치해야 한다. |
| FR-205 | generation config version `vllm-qwen-order-plan-batch-nonthinking-v4`, SHA-256 `1fd2f511a0b1c99f5a57125ebd9e1d67314d98202d42327394daa540abd27754`를 고정한다. |
| FR-206 | batch size는 25건이며 마지막 batch만 25건보다 작을 수 있다. |
| FR-207 | 응답은 strict JSON schema로 검증하고 모든 입력 ID가 정확히 한 번 존재해야 한다. |
| FR-208 | 허용 relevance는 `relevant|not_relevant|uncertain`이며 점수는 유한한 0..1 값이어야 한다. |
| FR-209 | timeout, 잘림, schema 위반, ID 누락·중복은 제한된 규칙으로 실패 처리하고 임의 보정하지 않는다. |
| FR-210 | 한 batch 실패가 다른 성공 batch를 폐기하지 않으며 전체 실행은 `부분 성공`으로 구분한다. |
| FR-211 | Qwen 또는 endpoint 실패를 다른 모델이나 hosted provider로 자동 전환하지 않는다. |

### 5.4 결과와 사람 검토

| ID | 요구사항 |
|---|---|
| FR-301 | 전체 모집단에 대해 plan ID, source observation, BM25 점수·순위·근접 역량, stage1 상태를 보존한다. |
| FR-302 | Qwen 대상에는 relevance, score, 사유, batch ID, attempt, token·duration과 모델 binding을 보존한다. |
| FR-303 | 기본 검토 목록은 `relevant|uncertain`이며 Qwen 비관련, BM25 탈락, 실패를 명시적 필터로 제공한다. |
| FR-304 | 실패 결과는 `비관련`으로 보이지 않고 `사람 검토 필요` 또는 안전한 실패 상태로 보인다. |
| FR-305 | 사람 relevance·우선순위·메모는 모델 결과와 별도 append-only 또는 revision 이력으로 보존한다. 정확한 enum과 수정 규칙은 구현 전 계약으로 확정한다. |
| FR-306 | 사람 피드백이 적합성 등급, 참여 준비 상태, 추적 상태, 최종 Go/No-Go를 암묵적으로 변경하지 않는다. |
| FR-307 | 수용한 BM25 누락 2건과 같은 알려진 누락을 실행 계보와 함께 조회할 수 있어야 한다. |

### 5.5 관측과 감사

| ID | 요구사항 |
|---|---|
| FR-401 | execution·batch·attempt별 시작·종료 시각과 duration을 기록한다. |
| FR-402 | input, cached input, output, total token은 제공된 값만 기록하고 미측정 값은 `null`로 둔다. |
| FR-403 | 전체·Top 300·탈락·Qwen 성공·실패·검토 유지 건수를 기록한다. |
| FR-404 | 로그와 감사에는 prompt, 회사 역량 본문, 모델 응답 본문, 자격증명, endpoint query를 넣지 않는다. |
| FR-405 | 감사에는 목적, actor kind와 claimed name, 실행·회차 ID, 허용 필드, binding digest, 결과와 안전한 실패 code를 남긴다. |

## 6. 데이터와 계약 요구사항

새 파일 계약은 기존 공고 `screening.v3`와 구분되는 발주계획 전용 schema여야 한다. 정확한
파일명과 schema 이름은 구현 전 `contracts.md`에서 확정하되 다음을 만족해야 한다.

- 수집 artifact와 C-2 실행 입력·결과는 생성 뒤 덮어쓰지 않는다.
- 실행 입력은 source run, population digest, BM25 config, prompt, 회사 역량, 모델,
  generation config를 고정한다.
- 결과 artifact는 전체 모집단을 포함하고 stage1 탈락을 삭제하지 않는다.
- 원시 모델 응답은 암호화된 versioned object로 저장하고 DB에는 안전한 참조와 hash만 둔다.
- PostgreSQL이 적재 뒤 사람 검토와 실행 상태의 운영 정본이다.
- 재적재는 같은 hash면 no-op, 같은 execution·plan에 다른 hash면 충돌로 전체 transaction을
  rollback한다.
- 기존 `OrderPlan`과 `OrderPlanObservation`을 재사용하고 공고 `Judgment`·`ScreeningExecution`
  의미를 조용히 확장하지 않는다.

## 7. 정책·프롬프트·회사 역량 관리

사람이 검토하는 원본은 `experiments/order-plan-screening/review-inputs/` 아래에서 관리한다.
Git에는 manifest와 hash만 남기고 prompt·회사 역량 본문은 넣지 않는다. 제품 실행은 이 작업
폴더를 실시간으로 다시 읽지 않고, 실행 생성 시 승인 상태와 hash를 검증한 불변 snapshot만
사용한다.

현재 허용 입력은 다음과 같다.

- 승인 회사 역량 v1
- 승인 prompt v3
- BM25 config digest
- Qwen model·revision과 generation config

negative prompt v4는 draft이며 별도 승인·비교·새 binding 없이는 사용할 수 없다.

## 8. 비기능 요구사항

| 영역 | 기준 |
|---|---|
| 재현성 | 동일 input·binding은 동일 BM25 결과를 만들고 Qwen 실행 계보를 비교 가능하게 남긴다 |
| 완전성 | 수집된 전체 모집단과 각 stage 상태의 합이 정확히 일치해야 한다 |
| 안전한 실패 | 미확인·미측정·부분 성공을 0·비관련·성공으로 보정하지 않는다 |
| 동시성 | 분석 모델 active slot은 1을 유지한다. MVP에서 batch 병렬 실행을 추가하지 않는다 |
| 보안 | 사내망, 목적별 egress, literal host allowlist, 환경 주입 secret, no redirect·proxy를 유지한다 |
| 접근 | 조회자는 사내망 경계로 접근한다. 담당자 이름은 감사 표식이며 인증으로 표현하지 않는다 |
| 저장 | PostgreSQL 17 `bidops` schema와 versioned MinIO를 정본으로 사용한다 |
| 배포 | 앱 startup은 migration, policy seed·activation, 수집, 모델 호출을 수행하지 않는다 |
| 접근성 | 상태를 색만으로 표현하지 않고 문자 라벨과 안전한 설명을 함께 제공한다 |

## 9. 성공 기준과 품질 게이트

### 9.1 MVP 기능 완료 기준

- 고정 fixture에서 전체 모집단 보존과 Top 300 경계가 결정적으로 검증된다.
- Qwen에는 Top 300 외 레코드가 전달되지 않는다.
- 12개 batch 또는 입력 크기에 따른 정확한 batch 수와 모든 attempt가 조회된다.
- 일부 batch 실패 시 성공·실패가 함께 보존되고 `부분 성공`으로 표시된다.
- 실행 시간과 token이 `null` 의미를 보존한 채 집계된다.
- 모델·prompt·회사 역량·BM25 config·입력 digest가 결과에서 역추적된다.
- 수동 실행 API와 결과 화면이 scheduler 없이 동작한다.

### 9.2 운영 활성화 전 품질 게이트

현재 96.61% recall은 draft label이 섞인 gold v2 기준의 비교 결과이며 운영 승인 그 자체가
아니다. 다음 조건이 충족되기 전에는 active policy나 always-on으로 승격하지 않는다.

현재 C-1 manifest는 `partially_human_adjudicated`이며 사람 판정 22건, draft 603건, 잔여 확인
87건이다. 이 수치는 승인 gold가 아니므로 품질 gate의 측정값이나 운영 threshold로 재사용하지
않는다. Phase 0 validator가 이 상태와 digest를 확인하지만 gold를 완료로 승격하지 않는다.

1. C-1 사람 gold 재판정 잔여 항목을 확정한다.
2. Top 300 경계와 탈락 감사 표본 정책을 별도 policy version으로 확정한다.
3. 승인 gold에서 recall, precision, 검토량, 중요 누락, 시간·token을 다시 계산한다.
4. fake와 live 실행을 분리해 model revision·payload·결과 hash를 검증한다.
5. 운영자가 품질 gate와 정확한 binding을 명시적으로 승인한다.

목표 recall·감사 표본률·최대 허용 중요 누락은 아직 확정하지 않았으므로 숫자를 추정해 넣지
않는다. 확정 전 상태는 `미측정` 또는 `승인 대기`다.

## 10. 위험과 대응

| 위험 | 대응 |
|---|---|
| BM25 어휘 불일치로 관련 사업 누락 | 전체 탈락 보존, 감사 표본, 알려진 누락 목록과 사람 gold 재평가 |
| Qwen batch 구성에 따른 판정 변동 | batch size·순서·prompt·generation config 고정, 반복 실행 계보 비교 |
| 모델 장애가 비관련으로 오인됨 | 실패 상태 분리, 자동 fallback 금지, 사람 검토로 종료 |
| 회사자료 또는 prompt 노출 | 본문 Git·로그·감사 제외, 승인 snapshot과 hash만 binding |
| 기존 1차 등급과 의미 혼합 | 발주계획 relevance 전용 계약·테이블·API 사용 |
| scheduler가 미승인 실행을 반복 | scheduler를 고도화 단계로 격리하고 기본 비활성 유지 |
| 실행 결과 일부만 저장 | 파일·DB 계약에서 전체 모집단 합계와 hash를 검증하고 불일치 시 발행 거부 |

## 11. Phase 0에서 고정한 항목과 남은 승인

다음 계약은 [PLAN.md](PLAN.md)의 Phase 0에서 고정했다. 상세 required key/status와 REST·DB
경계는 [contracts.md의 C-2 절](contracts.md#c-2-phase-0-fixed-contract)을 정본으로 한다.

- 모집단 300건 이하 처리: `select_all`; 감사 표본은 별도 사람 승인 전까지 비활성
- BM25: NFKC·casefold·공백 축약, char n-gram 2..5, score 내림차순·계획번호 오름차순
- Top 300 탈락: `filtered_out`으로 전체 결과에 보존하며 Qwen `not_relevant`로 바꾸지 않음
- 사람 relevance·우선순위·메모: wire relevance `relevant|not_relevant|uncertain`, priority
  `high|medium|low|null`, execution·plan별 append-only revision
- Qwen: batch 25, active slot 1, retryable failure 최대 2회, fallback 없음, 실패는 사람 검토 대기
- 실행 상태: `대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨`; stale 자동 resume 없음
- 전용 file schema·REST 경로·DB table 이름: C-2 v1 계약으로 고정

아직 사람 승인이 필요한 항목은 C-1 잔여 gold 87건, 탈락 감사 표본의 크기·주기, 승인 gold
기반 recall·precision·중요 누락·검토량 threshold, execution별 private vLLM 전송 승인이다.
이 값들은 `null`·`미측정`·`승인 대기`로 보존하며 추정하지 않는다. scheduler 시간·catch-up·
중복 예약·자동 실행 승인은 MVP Phase 0 범위가 아니다.

scheduler 시간, catch-up, 중복 예약, 자동 실행 승인 방식은 MVP 구현 전 결정 대상이 아니다.
수동 흐름과 품질 승인이 끝난 뒤 고도화 요구사항으로 별도 확정한다.
