# 사전규격 수집·개요 검토 안정화 명세

작성일: 2026-09-10 · 상태: 제안 구현 계약 · 상위 결정: [ADR](ADR.md)

아래 새 이름·상태·경로는 구현할 계약이다. 현재 제공되는 기능으로 해석하지 않는다. 구현과 함께 기존 [계약](../contracts.md), [업무 규칙](../business-rules.md), [보안](../security.md), [운영](../operations.md) 문서를 갱신한다.

## 수집 CLI와 회차 생성

```text
신규 수집:
  collect_notices.py --from-date DATE --to-date DATE --output-dir NEW_RUN [기존 원천 옵션]
기존 raw 재분류:
  collect_notices.py --from-date DATE --to-date DATE --from-raw SOURCE_RAW --output-dir NEW_RUN [기존 원천 옵션]
```

- `--from-raw`는 bool에서 경로 인자로 변경한다. 인자 없는 이전 호출은 사용법 오류로 종료하고 새 명령을 안내한다. 웹의 `from_raw: boolean` 입력은 유지하고 서버가 해당 회차의 허용 raw 경로로 변환한다.
- 수집기가 출력 폴더를 `mkdir(exist_ok=False)`로 획득한다. 기존 빈 폴더도 거부한다. 허용 루트와 부모 경로의 symlink·경로 이탈을 검사한 뒤, API key 로딩·HTTP client 생성·호출 전에 수행한다.
- raw와 최종 JSON은 `x`/`xb` 모드로 생성한다. 직렬화 가능한지 먼저 검사하고 기존 파일은 교체하지 않는다. 디렉터리 검사만으로 파일 보호를 대신하지 않는다.
- 재분류 입력·출력은 분리한다. 입력은 허용 루트의 일반 파일만 읽고 새 raw에 배타적으로 복사하며 hash를 대조한다. symlink를 만들지 않는다. 재분류는 HTTP·API key가 필요 없다.
- 중단한 회차의 raw를 보존한다. 기존 부분 수집 경고와 종료 실패 계약을 유지하며 완전 수집으로 적재하지 않는다. 재실행은 날짜와 고유 suffix가 있는 새 경로를 사용한다.
- `collected-notices.json`의 현재 v2 업무 계약과 원천별 날짜 경계는 유지한다. 호출 인자·원본 회차·파일 hash 연결은 기존 provenance 계약을 사용하고, 추가 파일이 필요하면 명시적 버전으로 정의한다.
- 수집 helper를 공통화하더라도 skill 내부에 두며 웹은 subprocess만 호출한다. 발주계획 전용 수집기까지 공통 helper로 바꾸는 경우 동일 불변성 회귀를 확인한다.

## 개요 계약 버전

| 용도 | 새 계약 | 이전 소비자 처리 |
|---|---|---|
| 구조화 초안 | `bidops.prespec-overview-claims.v1` | 새 runner 내부 입력·출력, 과거 결과 재해석 금지 |
| 주장별 검증 기록 | `bidops.prespec-overview-claim-checks.v1` | 결정적 검사와 의미 판정을 분리 저장 |
| 최종 페이지 개요 | `bidops.prespec-overview-page-review.v4` | v3와 함께 저장·조회, 버전별 parser |
| 모델 정책 | `bidops.prespec-overview-policy.v5` | v4 파일·digest 보존, 새 실행만 v5 사용 |
| 활성화 artifact | `bidops.prespec-v4-activation.v2` (`version=2`) | 기존 v1은 읽기·중지 가능, 새 두 단계 실행 승인으로 재사용 금지 |
| 웹 조회 envelope | `bidops.prespec-overview-pages.v2` | 신규 조회 경로와 소비자를 함께 배포 |

`v4`는 기존 workflow 이름이고 최종 JSON·정책·활성화의 버전 번호와 별개다. 새 정책 digest에는 두 stage의 prompt·schema·generation·검증기 버전·재시도·호출/시간 상한을 모두 포함한다. 기존 digest에 새 동작을 끼워 넣지 않는다.

## 초안·인용·최종 구성

초안은 다음 논리 구조를 엄격한 schema로 정의한다. 모든 객체는 알 수 없는 필드를 거부한다. hash는 SHA-256 소문자 hex, 페이지는 1부터 시작하는 물리 PDF 순번이다.

```text
Draft {
  schema_version,
  claims: [{id, section, text, evidence: [{page, quote}], quantities: [Quantity]}],
  analysis: [{id, text, supporting_claim_ids}],
  unknowns: [{id, topic, reason_code}],
}
Quantity {
  subject, role, value_decimal, unit, currency|null, vat|null,
  period_basis|null, evidence_index
}
VerifiedEvidence {page, quote, start_char, end_char, page_text_sha256}
```

- `section`은 `business_overview|main_tasks|budget_and_period|important_conditions`다. 하나의 claim은 독립 검증할 수 있는 주장 단위로 만든다. 복수 사실을 포함하면 모든 절의 근거가 필요하다. ID는 초안 안에서 유일하고 text는 비어 있지 않아야 한다. 사업 개요와 주요 과업이 각각 하나 이상 있어야 하며 빈 주장 집합의 검사를 완료 통과로 취급하지 않는다. 해당 필수 내용을 원문에서 확인할 수 없으면 사람 검토로 보낸다.
- 모델이 생성한 `page/quote`가 동결한 페이지 텍스트에서 정확히 한 위치로 대응하는지 서버가 확인한다. 서버가 계산한 `[start_char,end_char)`는 해당 텍스트의 Unicode code point 기준이다. `VerifiedEvidence.quote`는 그 원문 slice를 저장하여 `text[start:end] == quote`를 만족한다. 공백 등가 매칭이 필요하면 원문 offset 대응표를 보존하며 부호·숫자·부정을 제거하지 않는다. 모델이 쓴 원래 quote는 암호화 원응답에 남긴다.
- 모델이 적은 수치 metadata를 신뢰하지 않고 **주장 텍스트와 원문 양쪽에서** 독립 추출해 비교한다. 수치 누락·추가·정수화 손실을 검사한다. 단위뿐 아니라 사업 주체, 예산/계약금액/기간 등의 역할, VAT, 기산점, 날짜·ID를 대조한다. 관계가 확정되지 않으면 통과시키지 않는다.
- 숫자 비교는 `Decimal`과 명시적 단위 규칙만 사용한다. 검증 과정에서 명확한 등가 표기를 비교할 수 있지만 원문에 없는 금액·날짜·기간을 계산해 최종 문장으로 생성하지 않는다. 모호한 표의 열 관계와 생략 단위를 추정하지 않는다.
- `analysis`는 의견임을 표시하고 모든 사실 전제를 `supporting_claim_ids`로 연결한다. 의미 검토는 이 문장도 대상으로 삼아 새로운 사실·강화된 의무·회사 역량 단정을 거부한다. 참조가 비거나 잘못된 분석은 통과하지 않는다.
- `unknowns`는 제한된 topic/reason enum을 받아 서버 문구로 표시한다. topic은 `budget|period|eligibility|scope|schedule|company_comparison`, reason은 `not_in_reviewed_input|ambiguous_source|company_comparison_not_performed`다. 검토 범위 내 미확인만 나타내며 문서 전체의 부재를 단정하지 않는다. 의미 검토는 원문에 있는 내용을 미확인으로 잘못 표시했는지도 검사한다. 회사 대조 미실행은 서버가 실제 실행 범위로 확인한다. `input_limitations`는 실제 선택 범위·변환 metadata에서 서버가 구성한다.
- 입력·출력·주장 수·인용 길이 상한은 새 정책의 값과 모델 client의 context 예산으로 호출 전에 검사한다. 초과분을 조용히 버리지 않는다. 상한의 구체 값은 정책 fixture와 함께 확정하며 기존 승인 context를 늘리지 않는다.

최종 v4는 기존 네 사실 섹션에 `{claim_id,text,evidence:[VerifiedEvidence]}`를 두고, `reviewer_analysis`에는 검증된 `{id,text,supporting_claim_ids}`를 둔다. `unknowns`, `input_limitations`는 서버가 만든 문구이며 `verification_id`, `verification_sha256`로 검증 기록을 연결한다. 사실·분석 문장은 검증 후 재작성하지 않고 섹션 배치·표시 형식만 결정적으로 구성한다.

## 결정적 검사와 의미 검토

검증 기록은 `attempt_id`, 초안 hash, 동결 입력 hash, policy/model binding digest, 검사기 버전과 다음 구조를 가진다.

```text
checks: [{
  claim_id,
  deterministic: {status: passed|failed, reason_codes, verified_evidence},
  semantic: {status: supported|contradicted|insufficient|not_run, reason_codes}
}]
analysis_checks: [{analysis_id, status: supported|contradicted|insufficient|not_run, reason_codes}]
unknown_checks: [{unknown_id, status: supported|contradicted|insufficient|not_run, reason_codes}]
overall: passed|needs_human_review
```

원문 인용·범위·숫자·단위·역할·ID 검사 중 하나라도 실패하면 의미 호출 없이 `needs_human_review`다. 근거 누락·범위 밖 페이지·필수 사실 누락은 schema 단계에서 발견하더라도 형식 재시도 대상이 아닌 사실 검증 실패다. 형식 재생성 허용 코드는 파싱·최상위 컨테이너·자료형 등으로 제한한 allowlist로 고정한다.

의미 호출에는 같은 승인 범위의 동결 페이지 문맥, 초안, 검증된 인용을 전달한다. 인용 조각만 주어 부정·예외·조건이 잘리지 않게 한다. 원문과 초안은 비신뢰 데이터임을 별도 검토 prompt에 명시한다. 출력은 claim/analysis/unknown ID별 enum 판정과 제한된 오류 코드이며 자유 reasoning을 요구하지 않는다. 누락·중복 ID, 입력 밖 근거, 알 수 없는 판정은 통과할 수 없다.

`passed`는 모든 결정적 검사와 모든 의미 판정이 통과한 경우뿐이다. 자료가 충분한지 모르는 상태는 `insufficient`다. 긍정적인 의미 판정이 수치 오류를 무효화할 수 없다.

## 호출·재확인·실행 시간

| 항목 | 계약 |
|---|---|
| 정상 경로 | 초안 1회 + 의미 검토 1회 |
| 허용 재생성 | 초안의 malformed/truncated JSON 또는 구조 형식 오류에 한해 1회, 안전한 오류 코드만 보정 지시로 전달 |
| 최대 호출 | attempt당 생성 호출 3회, 의미 호출은 최대 1회. transport 자동 재시도 0회 |
| 종료 분류 | 형식 재생성 소진·호출 timeout·저장 장애는 `failed`; 해석 가능한 주장 불일치·의미 불확실은 `needs_human_review` |
| 의미 응답 형식 오류 | 재호출 없이 `failed/semantic_response_invalid`; 완료 결과 없음 |
| 호출 시간 | 호출당 300초, 새 다단계 attempt lease 1,200초. 추가 dispatch 전 360초 이상 남아야 함 |
| lease 부족·만료 | 새 호출 금지, `failed/lease_budget_exhausted` 또는 `failed/lease_expired`; 늦은 응답 게시 금지 |
| identity 일시 실패 | 미실행 큐가 있을 때 10→30→60→120→300초 간격, 이후 300초 간격으로 재확인. worker thread를 sleep으로 묶지 않음 |
| identity 고정 실패 | 허용 host·설정·인증·served ID·revision 불일치면 설정 수정/재기동까지 차단. 다른 provider나 revision으로 자동 재결합 금지 |

정상 identity binding은 purpose·endpoint 설정 fingerprint·model·revision·policy digest를 키로 캐시한다. 네트워크/5xx 등 일시 장애는 성공 캐시와 분리하고 응답 분류가 불명확하면 차단한다. 실행 중 identity 오류도 성공 캐시를 무효화하되 이미 시작한 실패 attempt를 자동 resume하지 않는다. client를 내부 생성한 경우 실패 시 닫고, 주입 client는 소유권 계약을 따른다.

identity 확인은 모델 생성 호출 수와 별도로 계측한다. 대기 상태의 원인·다음 재확인 시각은 안전한 worker 로그로 남긴다. 웹 프로세스가 worker 메모리를 조회할 수 있다고 가정하지 않으며 새 runtime 상태 API는 이 범위에 추가하지 않는다.

## DB·불변 기록

- `prespec_v4_attempt.status`를 32자로 확장하고 `needs_human_review`를 추가한다. 상태·target·완료 시각·결과·lease 제약과 PostgreSQL 불변 트리거, ORM 검사를 함께 갱신한다.
- 새 attempt에 `activation_id`를 고정한다. 과거 행은 null을 허용하지만 새 정책의 queued/running에는 필수다. 기존 활성 attempt는 전환 시 명시적으로 취소하고 새 정책에 재결합하지 않는다.
- `prespec_page_overview`는 v3와 v4를 허용하고 schema별 검증을 적용한다. 완료된 과거 행은 수정하지 않는다.
- `prespec_overview_call_event`를 append-only로 추가한다. `call_id`, `attempt_id`, ordinal, stage, event kind(`dispatch|response|error`), 입력/prompt/binding hash, raw 응답 hash와 내부 저장 참조, 안전한 오류 코드·token·시간을 기록한다. `(call_id,event kind)` 중복을 막고 응답/오류는 하나만 허용한다. dispatch 이후 취소돼도 응답 이벤트를 추가할 수 있다.
- dispatch 이벤트는 전송 권한을 확인한 사실이며 실제 전송/수신 성공을 뜻하지 않는다. 응답을 받지 못한 채 worker가 죽으면 결과는 미확정이고 lease 만료로 닫는다. 이미 종료한 attempt를 수정해서 늦은 응답 hash를 붙이지 않는다.
- `prespec_overview_verification`은 attempt별 append-only 검증 기록이다. schema·초안/입력/binding hash와 구조화된 검사 결과를 저장한다. 취소 후에는 새 검증/최종 결과를 게시하지 않고 call 이벤트만 보존한다.
- 모델 원문은 기존 암호화 저장소를 사용한다. call ledger가 다단계 실행 provenance의 정본이며 기존 단일 `raw_response_sha256` 필드는 호환용으로 남긴다. API·감사 로그에는 내부 저장 참조를 노출하지 않는다.
- 정상 종료에서 검증 기록·결과·attempt/WorkJob 종료를 같은 DB 트랜잭션으로 확정한다. `needs_human_review`에서는 결과 없이 검증 기록과 종료를 확정한다. 원응답 저장 실패는 완료를 차단한다.

| attempt 전이 | result | WorkJob 처리 |
|---|---|---|
| queued → running | null | running, 동일 lease 소유자 |
| queued → cancelled / failed | null | cancelled / failed, 종료·lease 해제 |
| running → completed | 필수 | completed |
| running → needs_human_review | null | failed, `last_error_code=claim_verification_required` |
| running → failed / cancelled | null | failed / cancelled |
| 모든 terminal → 다른 상태 | 금지 | 재실행은 새 attempt/job |

`needs_human_review`는 target이 있는 실행에 한정하고 `completed_at` 필수·lease null이다. `stale`은 현재성 조회 projection이며 새 attempt 저장 상태로 추가하지 않는다. 작업 집계/UI는 WorkJob의 기술적 실패와 attempt의 사람 검토 사유를 구분한다.

## 작업 배정·중지·게시의 동시성

enqueue·activation 변경·claim·dispatch 승인·최종 게시·만료 종료는 동일한 PostgreSQL transaction advisory lock을 사용한다. 잠금 순서는 gate → attempt → WorkJob이다. lock 키는 코드의 고정 namespace로 정의하고 임의 hash나 최신 감사 행 잠금으로 대신하지 않는다. HTTP 동안 DB 트랜잭션을 유지하지 않는다.

1. 개요 slot의 매 tick에서 활성 여부와 무관하게 만료를 정리한다. DB/현재성 조회 오류를 “v4 작업 없음”으로 바꾸어 legacy로 진행하지 않는다.
2. 현재 활성 artifact, pinned activation ID, policy/binding, 승인 sample 범위가 모두 일치하는 queued만 FIFO로 claim한다. 모델 대기는 claim 이전에 처리한다.
3. 각 호출 직전 gate 안에서 실행 상태·lease·승인·입력 현재성·호출 예산을 재검사하고 dispatch 이벤트를 확정한다. 중지 확정 이후 새 dispatch 승인은 없다. 승인 직후 전송과 중지가 경합하는 요청은 이미 승인된 in-flight 요청으로 취급한다.
4. OFF 트랜잭션은 OFF 이벤트와 모든 미종료 v4 attempt/job 취소를 함께 기록하고 취소 건수를 반환한다. 이미 OFF여도 남은 미종료 작업을 정리한다. 기존 완료는 변경하지 않는다.
5. 각 응답 후와 최종 게시 직전 activation ID·상태·lease·입력·binding을 다시 검사한다. 이전 activation에서 온 응답은 OFF→ON 뒤에도 게시할 수 없다.
6. 실행 가능한 v4가 없으면 모든 v4 target/attempt가 예약한 document version을 제외하고 legacy를 배정한다. 비활성·실패·취소한 v4 문서도 자동 우회시키지 않는다. 상위 composite worker의 slot·우선순위는 유지한다.

중지와 게시의 기준 시점은 각 트랜잭션 commit이다. 중지 먼저면 결과 삽입 0건, 게시 먼저면 해당 완료 이력은 남는다. 이미 전송한 HTTP는 서버에서 계속 계산할 수 있으며 단일 worker의 다음 업무는 요청 반환/timeout까지 기다릴 수 있다.

## REST·웹·후속 소비자

| 경로 | 계약 |
|---|---|
| `GET /api/pre-specs/{notice_id}/overview-pages/v2` | v2 envelope: `notice_id`, `current`, `reviews`, `range_review`, `verification`. reviews는 schema로 v3/v4를 구분하며 verification은 현재 attempt의 제한된 진단 또는 null |
| 기존 `GET .../overview-pages` | v1/v3 조회 유지. 해당 공고에 새 계약 실행이 생겨 v1로 정직하게 표현할 수 없으면 안전한 409 `overview_contract_upgrade_required`; 과거 성공으로 대체하지 않음 |
| 기존 `GET .../overview-pages/{review_id}/pdf` | 완료 이력의 exact PDF 조회 유지 |
| `GET .../overview-pages/attempts/{attempt_id}/pdf` | result가 없는 검증 실패도 고정 snapshot PDF를 열 수 있게 함. notice/attempt/document 관계와 기존 clean/version/hash 경계 검사 |

v2 `current`는 기존 attempt 상태 projection을 유지하고 검증 요약을 추가한다. `verification`은 검증 기록 ID·상태·reason code·문제 claim text·검증된 인용/page만 제공한다. 인용이 검증되지 않았으면 사실 근거로 표시하지 않고 reason을 보여 준다. 모델 원문·자유 reasoning·내부 경로는 반환하지 않는다. 새 PDF 경로도 safe 404/409/503 오류를 사용한다.

웹은 현재 개요, 검증 진단, 과거 이력을 분리한다. `needs_human_review`에는 “근거 확인 필요”, `cancelled`에는 “중지됨”을 표시하고 완료 본문을 만들지 않는다. v3에는 “이전 검증 기준”, 참조 결과에는 “미측정 참조”를 표시한다. 범위 확정은 계속 `attempt_enqueued=false`이고 명시적 새 실행을 대신하지 않는다.

회사 핏 등의 소비자는 새 schema parser와 현재 결과의 전체 검증 통과·hash 일치를 확인한다. 현재 실패·중지·stale일 때 과거 결과나 legacy 권고를 대신 사용하지 않는다. 신규 사실 검증이 적용되지 않은 기존 경로는 기존 계약을 유지하며 새 표준 통과로 취급하지 않는다.
