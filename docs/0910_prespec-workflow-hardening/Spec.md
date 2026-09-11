# 사전규격 수집·개요 검토 안정화 명세

작성일: 2026-09-10 · 상태: 구현·격리 검증 반영, 실사용 초안4건 모두 사람 검토 필요([Plan](Plan.md)) · 상위 결정: [ADR](ADR.md)

아래는 안정화 구현의 계약이다. 실제 완료·검증과 미실행 범위는 [Plan](Plan.md)에 구분하며 운영 배포·모델 전송 승인으로 해석하지 않는다. 기존 [계약](../contracts.md), [업무 규칙](../business-rules.md), [보안](../security.md), [운영](../operations.md) 문서와 함께 관리한다.

## 수집 CLI와 회차 생성

```text
신규 수집:
  collect_notices.py --from-date DATE --to-date DATE --output-dir NEW_RUN [기존 원천 옵션]
기존 raw 재분류:
  collect_notices.py --from-date DATE --to-date DATE --from-raw SOURCE_RAW --output-dir NEW_RUN [기존 원천 옵션]
```

- `--from-raw`는 bool에서 경로 인자로 변경한다. 인자 없는 이전 호출은 사용법 오류로 종료하고 새 명령을 안내한다. 웹의 `from_raw: boolean` 입력은 유지하고 서버가 해당 회차의 허용 raw 경로로 변환한다.
- 수집기가 출력 폴더를 `mkdir(exist_ok=False)`로 획득한다. 기존 빈 폴더도 거부한다. 허용 루트와 부모 경로의 symlink·경로 이탈을 검사한 뒤, API key 로딩·HTTP client 생성·호출 전에 수행한다.
- 허용 루트는 기본 `PROJECT_ROOT/data/runs`이며, CLI의 `--allowed-root PATH`로 격리 실행 루트를 명시할 수 있다. 웹·예약 호출은 `settings.bidops_root/data/runs`를 전달한다. 입력·출력 모두 이 루트 아래여야 한다.
- raw와 최종 JSON은 `x`/`xb` 모드로 생성한다. 직렬화 가능한지 먼저 검사하고 기존 파일은 교체하지 않는다. 디렉터리 검사만으로 파일 보호를 대신하지 않는다.
- 재분류 입력·출력은 분리한다. 입력은 허용 루트의 일반 파일만 읽고 새 raw에 배타적으로 복사하며 hash를 대조한다. symlink를 만들지 않는다. 재분류는 HTTP·API key가 필요 없다.
- 중단한 회차의 raw를 보존한다. 기존 부분 수집 경고와 종료 실패 계약을 유지하며 완전 수집으로 적재하지 않는다. 재실행은 날짜와 고유 suffix가 있는 새 경로를 사용한다.
- `collected-notices.json`의 현재 v2 업무 계약과 원천별 날짜 경계는 유지한다. 호출 인자·원본 회차·파일 hash 연결은 기존 provenance 계약을 사용하고, 추가 파일이 필요하면 명시적 버전으로 정의한다.
- 재분류 계보는 배타 생성하는 `collection-provenance.json` / `bidops.collection-provenance.v1`에 기록한다. 원본 raw의 허용 루트 상대 경로, 날짜·원천 옵션, 복사한 페이지별 SHA-256을 보존하며 수집 업무 JSON의 의미는 바꾸지 않는다.
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
| 절 후보 산출물 | `bidops.section-candidates.v2` | v1은 그대로 읽고 새 `outline`·부분 반환 의미를 v1에 끼워 넣지 않음 |
| 범위 조회 | `bidops.prespec-overview-range-view.v2` | pages.v2의 nested range_review. v1로 표현 불가하면 업그레이드 필요 409 |

`v4`는 기존 workflow 이름이고 최종 JSON·정책·활성화의 버전 번호와 별개다. 새 정책 digest에는 두 stage의 prompt·schema·generation·검증기 버전·재시도·호출/시간 상한을 모두 포함한다. 기존 digest에 새 동작을 끼워 넣지 않는다.

activation v2의 `execution`에는 policy schema·digest, 두 stage 이름, 생성 호출 3회·의미 호출 1회·호출당 300초·lease 1,200초를 고정한다. `explicit_sample`의 실행 승인 항목은 기존 notice/document/source 결속에 `target_id`, `input_sha256`, `selection_manifest_sha256`, `pdf_sha256`을 더해 실제 승인한 입력 범위를 제한한다. source만 고정한 표본은 문서 준비까지만 허용하고 enqueue/dispatch는 거부한다. 기본 v2 파일은 표본과 승인 policy digest가 없는 미승인 템플릿이며 그대로 활성화할 수 없다. `--preview-activation`은 이 결속과 stage별 hash·호출 상한을 읽기 전용으로 보여 준다.

## 변환 core와 보조 후보·범위 확인

- 승인 원본의 기존 격리 worker·안전 검사, PDF·전체 페이지 텍스트의 version/hash/소속 확인은 유지한다. rhwp 자체·변환 알고리즘은 교체하지 않는다.
- `digest --sections`의 `outline|clause|page`를 수용한다. `sectionCount`는 전체 수, `len(sections)`는 반환 수다. 전체≥반환이고 부분 반환에는 upstream `truncated=true`가 필요하다. `truncated`는 발췌 절단일 수도 있으므로 이것만으로 후보 목록 불완전을 단정하지 않는다.
- 새 후보 v2는 기존 `schema,page_count,mode,section_count,sections`에 `returned_count,truncated,candidates_truncated`를 더한다. `candidates_truncated == (returned_count < section_count)`, 반환 수는 목록 길이와 일치해야 한다. 각 후보 좌표·타입·정규 bytes 상한을 유지한다. v1의 기존 의미·bytes는 보존한다.
- native core를 검증한 뒤 별도 digest를 처리한다. digest의 bounded 실패·해석 실패는 후보를 사용하지 않고 `section_candidates_unavailable`, 부분 반환은 `section_candidates_incomplete` 경고를 남긴다. 필수 core 생성·안전·무결성 실패를 이 처리로 통과시키지 않는다.
- scratch 생산자·소비자는 위 경고가 명시된 경우에만 후보 descriptor의 명시적 null을 허용한다. 후보가 있으면 hash·canonical JSON·결속을 계속 검사하며, 원본·PDF·페이지 텍스트·대응표 검사는 후보 유무와 무관하게 유지한다. 후보 없는 신규 snapshot도 기존 nullable 참조 세 열을 함께 null로 저장하고 같은 검사를 거쳐 재사용한다.
- 후보 목록이 부분이면 자동 범위와 후보 index 기반 확정/모델 범위 보조를 막고 직접 쪽 선택으로 연결한다. 후보가 없을 때 명확한 본문 heading은 활용할 수 있다. 같은 본문 줄의 복수 로마숫자 장 제목이나 `제안개요` 작성 양식이 선택되면 `ambiguous_scope_boundary`로 수동 확인한다. 기존 자동 ready target은 덮지 않고 같은 경고를 조회에 표시한다. 목차 유형·다단 전체 해석기는 만들지 않는다.
- 일부 페이지의 공백은 삭제·정규화하지 않는다. 적어도 한 페이지에 유효 본문이 있어야 하며 전체 공백이면 runner가 `manifest_invalid`로 전송 전에 차단한다. 공백 인용은 검증된 근거가 될 수 없다.

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
- 입력·출력·주장 수·인용 길이 상한은 새 정책과 모델 client의 context 예산으로 각 호출 전에 검사한다. **선택 페이지 합계 5,000자는 실패 기준이 아니다.** 페이지 수 24, user prompt 24,000자, draft 10,000자, 응답 16,000자, 주장 8개/분석 4개/unknown 6개, 문장 300자/주장당 인용 2개(각 300자)/수치 metadata 4개 상한은 유지한다. 기존 stage generation의 최대 출력 token 16,384를 늘리지 않는다.
- 초안과 의미 검토는 각각 실제 system/user 메시지·형식 보정 메시지·출력 schema·요청 부가 필드의 크기와 확인된 모델 컨텍스트·출력 예약을 함께 고려한다. C-1 전용 `BIDOPS_SCREENING_CONTEXT_SIZE`를 개요 컨텍스트로 사용하지 않는다. 컨텍스트를 확인할 수 없으면 전송하지 않는다. 로컬 보수 추정치는 실제 tokenizer 측정값이라고 표시하지 않는다.
  - v5의 승인 context ceiling은 262,144토큰이고 유효 한도는 `min(/models의 해당 served ID max_model_len, policy ceiling)`이다. context metadata가 없거나 유효한 양의 정수가 아니면 차단한다. 기존 reader/다른 용도는 이 필드를 새 필수 조건으로 삼지 않는다.
  - 단일 core 요청 조립기가 실제 SDK에 넘기는 인자(system/user/correction, response_format schema, model/generation/extra_body/timeout)를 canonical UTF-8로 직렬화한 byte 수를 입력 token 상계로 쓴다. 이 상계 + chat template 예약 1,024 + 출력 예약 16,384가 유효 한도 이하여야 한다. 외부 tokenizer 호출이나 평균 글자/token 비율로 승인 전 문서를 보내거나 안전 한도를 추정하지 않는다.
  - `max_page_text_chars=24,000`은 user prompt 상한에서 도출한 빠른 사전 상한일 뿐이며 이 값 이하라는 이유만으로 허용하지 않는다. 실제 prompt에는 지시·JSON·초안·인용도 포함되므로 stage별 24,000자 상한과 위 context 예산을 모두 통과해야 한다.
- 허용한 선택 원문은 두 단계에 전체를 제공한다. 자동 절단·사전 요약·주장 상한 자동 축소·자동 분할로 용량을 맞추지 않는다. 의미 검토의 실제 payload는 초안과 결정적 검사 이후 만들어지므로 해당 요청 직전에 다시 검사한다. 가능 최대 초안의 크기만으로 실제 요청이 가능한 원문을 일률 차단하지 않는다.
- 한도를 넘으면 해당 단계 dispatch/전송 전에 `failed/input_capacity_exceeded`, 결과 없음으로 종료한다. 이는 내용 검증 실패인 `needs_human_review`와 다르다. 의미 요청에서 초과했으면 앞선 초안 호출·원응답을 보존하며 전체 호출 0회로 표시하지 않는다. 운영자는 선택 범위·요청 예산을 확인하고 범위를 바꿀 때 새 승인 target을 만든다. 호출 증가나 검증 방식을 바꾸는 분할은 별도 승인 대상이다.

최종 v4는 기존 네 사실 섹션에 `{claim_id,text,evidence:[VerifiedEvidence]}`를 두고, `reviewer_analysis`에는 검증된 `{id,text,supporting_claim_ids}`를 둔다. `unknowns`, `input_limitations`는 서버가 만든 문구이며 `verification_id`, `verification_sha256`로 검증 기록을 연결한다. 사실·분석 문장은 검증 후 재작성하지 않고 섹션 배치·표시 형식만 결정적으로 구성한다.

## 결정적 검사와 의미 검토

검증 기록은 `attempt_id`, 초안 hash, 동결 입력 hash, policy/model binding digest, 검사기 버전과 다음 구조를 가진다.

```text
checks: [{
  claim_id, section, text,
  deterministic: {status: passed|failed, reason_codes, verified_evidence},
  semantic: {status: supported|contradicted|insufficient|not_run, reason_codes}
}]
analysis_checks: [{analysis_id, status: supported|contradicted|insufficient|not_run, reason_codes}]
unknown_checks: [{unknown_id, status: supported|contradicted|insufficient|not_run, reason_codes}]
analysis: [{id, text, supporting_claim_ids}]
unknowns: [{id, topic, reason_code}]
reason_codes: [전체 초안의 안전한 실패 코드]
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
| 입력 용량 초과 | 해당 단계 호출 전 `failed/input_capacity_exceeded`; 검증 실패·성공·품질 승인으로 표시하지 않음 |
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
- `prespec_overview_call_event`를 append-only로 추가한다. `call_id`, `attempt_id`, ordinal, stage, event kind(`dispatch|response|error`), 입력/prompt/binding hash, raw 응답 hash와 내부 저장 참조, 안전한 오류 코드·token·시간을 기록한다. `input_sha256`은 attempt/target의 동결 입력 hash이며 `prompt_sha256`은 `{system_prompt,user_prompt,correction,seed}` 유효 요청 문맥의 canonical JSON SHA-256이다. seed는 생략 시 승인 기본값을 넣으며 stage schema/generation은 policy digest로 결속한다. `(call_id,event kind)` 중복을 막고 응답/오류는 하나만 허용한다. dispatch 이후 취소돼도 응답 이벤트를 추가할 수 있다.
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
| `GET .../overview-pages/targets/{target_id}/pdf` | attempt가 없어도 안전한 준비 PDF 조회. notice/target/document/snapshot 연결, 원본 및 PDF 최신 clean scan, source hash/size와 PDF version/etag/size/hash 검사. 성공·승인 의미 없음 |

v2 `current`는 기존 attempt 상태 projection을 유지하고 검증 요약을 추가한다. `verification`은 검증 기록 ID·상태·reason code·문제 claim text·검증된 인용/page만 제공한다. 인용이 검증되지 않았으면 사실 근거로 표시하지 않고 reason을 보여 준다. 모델 원문·자유 reasoning·내부 경로는 반환하지 않는다. 새 PDF 경로도 safe 404/409/503 오류를 사용한다.

웹은 현재 개요, 검증 진단, 과거 이력을 분리한다. `needs_human_review`에는 “근거 확인 필요”, `cancelled`에는 “중지됨”을 표시하고 완료 본문을 만들지 않는다. v3에는 “이전 검증 기준”, 참조 결과에는 “미측정 참조”를 표시한다. 범위 확정은 계속 `attempt_enqueued=false`이고 명시적 새 실행을 대신하지 않는다.

pages.v2의 `range_review`는 최신 pending/human-confirmed뿐 아니라 자동 ready도 반환한다. 새 nested schema의 필드는 기존 값과 `candidate_status=complete|partial|unavailable`, `candidate_count_total`(불명확하면 null), `candidate_count_returned`, `warning_codes`, `selected_pages`, `can_confirm`이다. mode에는 outline을 추가한다. 후보 읽기 실패는 경고와 수동 쪽 선택으로 연결하고 필수 manifest/page-text 오류는 계속 닫는다. 기존 자동 target에서 새로 발견한 모호함은 warning으로 표시하며 저장 상태·과거 실패를 소급 수정하지 않는다.

기존 `POST .../range-confirmations`의 body·actor·감사·새 target/201 응답을 유지한다. 최신 ready 또는 needs_human_review만 허용하고 현재 안전한 문서·원본/PDF clean 상태를 재확인한다. enqueue와 공유하는 기존 notice 행 잠금으로 queued/running과 경쟁을 막으며 active이면 409 `target_execution_active`, 안전 현재성이 없으면 409 `document_not_current_safe`다. 입력 확정에 전역 실행 gate를 추가하지 않는다. 후보가 있어도 직접 쪽을 선택할 수 있다. 부분 후보 index는 422 `candidate_range_incomplete`, 읽을 수 없는 후보 index는 422 `candidate_range_unavailable`이다. 새 범위 뒤 옛 target enqueue는 `target_superseded`로 차단한다. 범위 확정은 모델 전송 승인·activation·attempt·내용 검증을 생성하지 않는다.

회사 핏 등의 소비자는 새 schema parser와 현재 결과의 전체 검증 통과·hash 일치를 확인한다. 현재 실패·중지·stale일 때 과거 결과나 legacy 권고를 대신 사용하지 않는다. 신규 사실 검증이 적용되지 않은 기존 경로는 기존 계약을 유지하며 새 표준 통과로 취급하지 않는다.
사람이 새 범위를 확정하면 이전 target의 완료 결과는 이력에 남고 current는
`stale/target_superseded`, result_id=null로 투영한다. 회사 핏도 같은 현재성 규칙을 읽어
이전 범위의 검증 완료를 새 범위의 검증으로 사용하지 않는다. 저장된 완료/검증 행은 바꾸지 않는다.
이 경우 이전 verification도 v2의 현재 diagnostic/verification_status에 붙이지 않는다.
