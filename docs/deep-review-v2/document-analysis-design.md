# Deep Review v2 첨부문서 분석 설계

> 상태: 제안 설계 — **결정적 부분만 구현됨**, 역할별 모델 분석과 Luna 평가는 보류
>
> [ADR-0051](../tracking/decisions/0051-deep-review-v2-deterministic-subset.md)이 §4의 segment
> 경계·요구사항 inventory와 §6의 결정적 검증 연결을 채택해 구현했다. §5의 역할별 모델 분석,
> segment의 모델 보조 분류, §7.2의 `edwardkim/rhwp` A/B는 구현하지 않았다. 구현 상태는 아래
> §2 표의 `현재 구현` 열이 정본이다.
>
> 기준일: 2026-09-03 (KST)
>
> 관련 문서: [Luna 시안·품질 검증 계획](luna-evaluation-plan.md),
> [업무 규칙](../business-rules.md), [계약](../contracts.md),
> [심층 검토 ERD](../deep-review-erd.md) (모델 전송 정책은 ADR-0050 완화 항목 참조)

## 1. 목적과 결정 경계

이 설계의 목적은 제안요청서 전체를 한 번에 요약하는 방식에서 벗어나, 원문을 목적별로
분할하고 역할별 분석과 결정적 검증을 결합해 기획 담당자가 검토 가능한 심층 리포트를
만드는 것이다.

시스템은 다음을 지원한다.

- 입찰 자격·평가·사업 조건과 회사의 승인된 사실을 대조한다.
- 기술·기능 요구사항을 빠짐없이 식별하고 회사 역량과의 gap을 표시한다.
- 품질·보안·계약·공동수급·거버넌스 위험과 필요한 대응 행동을 정리한다.
- 모든 중요한 주장과 숫자를 원문 locator 또는 승인된 회사 사실에 연결한다.
- 검증된 결과만 종합해 시스템 권고를 제시한다.

다음 결정은 자동화하지 않는다.

- 회사 자격·실적의 사실 확정
- 심층 추적 승인
- 공동수급사 선정과 대외 연락
- 제안 금액 확정
- 최종 입찰 Go/No-Go

시스템 권고는 현재 계약의 `추진 검토`, `조건부 추진 검토`, `보류`, `검토 종료`를
사용한다. 이를 최종 입찰 `Go/No-Go`로 저장하거나 자동 변환하지 않는다.

## 2. 현재 구현 기준선

이 절은 목표가 아니라 2026-09-03 작업트리에서 확인한 현재 동작이다.

| 영역 | 현재 구현 | 확인된 한계 |
|---|---|---|
| 첨부 안전 처리 | HWP/HWPX/PDF, 50 MiB, quarantine, MIME·magic, ClamAV, source hash 검증 | 변환·추출 성공이 의미 구조 보존까지 보장하지 않음 |
| HWP | 원본 보존 후 vendored WASM 런타임으로 HWPX 변환 | 변환된 구조와 실제 페이지·표·장절의 완전성 검증이 제한적 |
| HWPX | stdlib XML parser가 문단·표·표 셀을 block으로 구조화 | heading 의미와 목차 관계가 canonical block에 충분히 남지 않음 |
| PDF | 페이지별 text/block 추출과 poppler fallback | 표 구조와 읽기 순서가 HWPX보다 약할 수 있음 |
| 입력 고정 | ready document bundle이 document version·structure·hash를 snapshot | — |
| 심층 검토 | `requirements_and_evaluation`, `delivery_risk_economics`, `synthesis_and_validation` 3단계 | 역할별 목적이 입력 분할 계약으로 명확히 분리되지 않음 |
| chunk | 페이지 block을 문자 수와 행 수로 제한한 excerpt로 분할 | `requirement_id`가 원문의 SYR/QUR 등이 아니라 excerpt용 가상 ID임 |
| segment manifest | **결정적 부분 구현됨.** 구조 저장 시점에 `document_segment_manifest`·`document_segment`·`requirement_inventory_item`을 만들고 `GET /api/document-structures/{id}/segments`로 읽는다 | 분류는 결정적 규칙만 쓴다(`classification_source=deterministic`, `confidence` 항상 `null`). 모델 보조 분류는 보류. 이 변경 전 구조에는 manifest가 없고 조회가 404이며 사후 재구성이 불가능하다 |
| segment coverage | **결정적 부분 구현됨.** `segment_coverage` check가 간극·중첩을 warning(보통)으로 남긴다 | 차단하지 않는다 |
| 역할별 분석 | **미구현.** §5의 네 역할과 출력 schema는 보류다 | 기존 3단계가 그대로다 |
| 요구사항 검증 | **결정적 부분 구현됨.** `requirement_inventory` check가 심층 검토 검증 경로에서 누락·예상 밖 ID를 `failed`(중대), 중복을 warning으로 남긴다 | ID 체계가 없는 문서는 warning "inventory 없음"이다. claim이 ID를 적지 않으면 실패하므로 기존 통과 리뷰를 뒤집을 수 있다 |
| 근거·보고서 | claim/evidence, exact quote, locator, 계산 검증, append-only revision | 형식 완결성이 의미상 요구사항 전수성이나 역할별 적합성을 보장하지 않음 |
| 사람 결정 | 최종 의견을 별도 revision으로 기록 | 유지해야 하는 경계이며 자동 권고와 합치지 않음 |

현재 vendored 런타임의 출처는 `DoHyun468/claw-hwp` 고정 commit이다. 이 설계에서 비교
후보로 언급하는 `edwardkim/rhwp`와는 별개의 upstream이므로 버전·license·hash를 섞어
기록하지 않는다.

## 3. 목표 데이터 흐름

~~~mermaid
flowchart LR
    source[불변 원문]
    structure[검증된 document structure]
    inventory[heading·TOC·요구사항 inventory]
    segments[목적별 segment manifest]
    eligibility[입찰·사업성 역할]
    tech[기술 적합성 역할]
    risk[위험·거버넌스 역할]
    validate[결정적 검증]
    synth[종합 역할]
    report[기획자 리포트]
    human[사람 검토·최종 결정]

    source --> structure --> inventory --> segments
    segments --> eligibility
    segments --> tech
    segments --> risk
    eligibility --> validate
    tech --> validate
    risk --> validate
    validate --> synth --> report --> human
~~~

`segment manifest`와 각 역할 결과는 동일한 bundle, profile, policy, prompt, model
identity에 묶인 불변 산출물이다. 재실행은 기존 결과를 고치지 않고 새 attempt 또는 새
execution으로 남긴다.

## 4. 문서 분할 설계

### 4.1 범용 taxonomy

페이지 번호나 특정 RFP의 장 제목을 고정하지 않고 다음 목적 taxonomy를 사용한다.

| 코드 | 의미 | 대표 내용 | 주요 소비자 |
|---|---|---|---|
| `business_eligibility_evaluation` | 사업·입찰·평가 | 사업 개요, 기간, 예산, 참가 자격, 제출물, 정량·정성 배점 | 입찰·사업성 역할 |
| `technical_functional` | 기술·기능 | 시스템·기능 요구사항, 인터페이스, 데이터, AI, 운영 기능 | 기술 적합성 역할 |
| `quality_security_constraints` | 품질·보안·제약 | 품질, 성능, 보안, 개인정보, 인증, 법무, 지식재산, 계약 제약 | 위험·거버넌스 역할 |
| `partnership_governance` | 공동수급·거버넌스 | 공동수급, 분담이행, 하도급, 보고 체계, 품질 게이트, 역할·책임 | 입찰·사업성 및 위험 역할 |

하나의 조항이 두 목적에 필요할 수 있다. 이때 원문을 복제해 별도 진실로 만들지 않고
하나의 segment ID에 taxonomy label을 여러 개 연결한다. 예를 들어 QA사의 독립적
Pass/Fail 권한은 `quality_security_constraints`와 `partnership_governance`를 동시에
가질 수 있다.

### 4.2 경계 탐지 순서

1. document block을 원래 순서와 locator로 정규화한다.
2. 목차 후보, 번호형 heading, 요구사항 표 header, 요구사항 ID를 결정적 규칙으로 찾는다.
3. 목차 항목과 본문 heading을 문자열 정규화·번호 체계·순서로 연결한다.
4. 요구사항 표는 ID와 행 경계를 우선해 inventory로 만든다.
5. heading, 표 시작·종료, 문서 종료를 이용해 segment 후보를 만든다.
6. keyword와 요구사항 ID prefix를 이용해 확실한 taxonomy를 부여한다.
7. 규칙이 둘 이상 충돌하거나 label을 정하지 못한 후보만 제한된 모델 분류에 보낸다.
8. 시작·종료 locator가 불명확하거나 모델과 규칙이 충돌하면 `needs_human_review`로 남긴다.

모델은 원문 경계를 새로 만들 수 없다. 이미 생성된 후보 경계의 taxonomy를 선택하거나
불명확하다고 표시할 수 있을 뿐이다.

### 4.3 요구사항 inventory

inventory는 SYR/QUR/SER/PSR/IPCR 같은 특정 prefix만 전제로 하지 않는다. 다음 형태를
모두 후보로 탐지하고 문서별 prefix 집합을 먼저 확정한다.

- 영문 prefix와 숫자: `SYR-01`, `QUR-005`
- 한글·영문 혼합 번호
- 표의 `요구사항 ID`, `요구사항 고유번호`, `ID` 열
- 장별로 다시 시작되는 번호

각 inventory 항목은 원문 ID, 정규화 ID, 문서·structure ID, 표·행·셀 또는 문단 locator,
제목, 원문 순서를 가진다. 모델 결과의 requirement ID는 이 inventory에 존재해야 한다.
누락, 중복, 예상 밖 ID는 `compare_requirement_ids()`로 계산하며 모델이 보고한 개수를
신뢰하지 않는다.

ID가 없는 서술형 의무도 삭제하지 않는다. 해당 항목은 안정적인 내부 item ID와
`source_requirement_id=null`을 갖고 사람 확인 대상으로 구분한다.

### 4.4 segment manifest 후보 계약

평가 단계에서 다음 후보 계약을 사용하고, 승인 전에는 `docs/contracts.md`의 정본 계약으로
간주하지 않는다.

```text
schema: bidops.document-segments.v1
bundle_id, document_version_id, structure_id, source_sha256
taxonomy_version, extractor_binding, created_at
segments[]:
  segment_id, ordinal, taxonomy_labels[]
  title, start_locator, end_locator
  requirement_ids[], source_block_keys[]
  classification_source: deterministic|model_assisted|human
  confidence, status: ready|needs_human_review
inventory_summary:
  expected_ids[], duplicate_ids[], ambiguous_items[]
warnings[]
```

`segment_id`는 document version, start/end locator, taxonomy version으로 결정적으로 만든다.
모델이 만든 제목이나 요약을 identity 계산에 넣지 않는다.

## 5. 역할별 분석 설계

역할은 독립 서비스나 자율 에이전트를 뜻하지 않는다. 기존 analysis worker 안에서 서로
다른 입력 allowlist, 프롬프트, 출력 JSON Schema를 가진 계약 기반 호출 단위다.

### 5.1 입찰·사업성 역할

입력은 `business_eligibility_evaluation`, 필요한 `partnership_governance`, 승인된 회사
최소 projection이다.

출력은 다음을 포함한다.

- 입찰 필수 자격별 `충족 확인`, `불충족 확인`, `unknown`
- 회사 사실과 공고 조건의 양방향 근거
- 정량 평가 항목과 계산 가능한 예상 점수
- 공동수급·분담이행·하도급 제약과 필요한 파트너 역할
- 예산·기간·계약 조건의 사업성 위험
- `추진 검토`, `조건부 추진 검토`, `보류`, `검토 종료` 후보와 선결조건

필수 자격이 회사 projection에 없으면 `충족`으로 추정하지 않는다. `불충족 확인`도
반대 사실이 검증된 경우에만 사용한다.

### 5.2 기술 적합성 역할

입력은 `technical_functional` segment와 승인된 기술·실적 projection이다.

각 요구사항은 다음 상태 중 하나를 가진다.

- `대응 가능`: 직접 근거가 있는 현재 역량
- `추가 확인`: 관련 역량은 있으나 범위·성능·인력 확인이 필요함
- `갭`: 확인된 요구와 확인된 역량 사이의 차이
- `해당 없음`: 문서상 회사 수행 범위가 아님

출력은 요구사항별 상태, 근거, gap, 보완 방법, 필요한 역할, 의존성, 검증 방법을 가진다.
M/M은 승인된 생산성·인력·범위 정보가 있을 때만 계산한다. 그렇지 않으면 단일 숫자를
만들지 않고 `산정 불가`, 필요한 입력, 조건부 범위를 표시한다.

### 5.3 위험·거버넌스 역할

입력은 `quality_security_constraints`, `partnership_governance`와 필요한 사업 segment다.

각 위험은 기존 등급인 `차단`, `중대`, `보통`, `낮음`을 사용하며 다음을 가진다.

- 문서상 의무와 원문 근거
- 발생 조건과 영향
- 제안 전 확인 또는 수행 중 완화 행동
- 담당 역할과 기한
- 잔여 위험
- 사실, 계산, 추론, 의견의 구분

인증 취득 가능성, 외부 파트너 수용 여부, 법적 해석은 근거 없이 확정하지 않는다.

### 5.4 종합 역할

종합 역할은 원문 전체를 다시 받지 않는다. 결정적 검증을 통과한 역할별 claim, 실패·경고,
unknown, segment coverage만 입력으로 받는다.

종합 결과는 다음 순서로 작성한다.

1. 시스템 권고와 이유
2. 입찰 차단 조건과 확인 기한
3. 기술 gap과 대응 전략
4. 품질·보안·거버넌스 핵심 위험
5. 제안서·PT 차별화 전략
6. 내부 담당자별 다음 행동
7. 문서·회사 정보의 한계

차단성 검증 실패가 있으면 종합 결과를 성공으로 발행하지 않는다. 사람 검토용 부분
결과와 실패 사유만 남긴다.

### 5.5 기존 3단계와의 호환

DB와 REST의 기존 stage enum은 우선 유지한다.

| 기존 stage | 내부 역할 artifact |
|---|---|
| `requirements_and_evaluation` | 입찰·사업성, 기술 적합성 |
| `delivery_risk_economics` | 위험·거버넌스, 결정적 사업성 계산 |
| `synthesis_and_validation` | 검증 결과와 종합 역할 |

역할별 호출 수와 artifact가 늘어도 기존 `StageView`의 의미를 바꾸지 않는다. 역할 상태를
외부 API에 노출해야 한다면 기존 field를 재해석하지 않고 versioned 확장 계약을 만든다.

## 6. 결정적 계산과 검증

모델은 근거 후보를 제시하고 의미 분류를 돕지만 다음은 코드가 계산한다.

- 요구사항 ID 유일 개수, 누락, 중복, 예상 밖 ID
- 자격 조건의 공고 근거와 회사 사실 존재 여부
- 평가 배점 합계와 항목별 산술
- 금액, VAT 포함 여부, 실비 항목, 기간과 마감일
- 인용 문자열이 locator의 원문에 실제 존재하는지
- claim이 참조한 document/profile version과 실행 binding의 일치
- segment의 겹침, 빈 구간, 문서 coverage
- 같은 사실에 대한 역할 결과의 충돌

검증기는 모델 문장을 수정해 통과시키지 않는다. 실패 check, 관련 claim/evidence ID,
severity를 보존하고 사람에게 보낸다.

정량 점수는 규칙이 계산하며 상태는 다음처럼 분리한다.

- `computed`: 모든 전제와 산술이 검증됨
- `partial`: 일부 항목만 계산 가능함
- `unknown`: 필수 회사 사실 또는 공고 기준이 없음
- `not_applicable`: 해당 평가 항목이 적용되지 않음

`unknown`과 `not_applicable`을 0점으로 바꾸지 않는다.

## 7. HWPX와 PDF 처리 방향

### 7.1 기본 방향

초기 구현 후보는 현재 원칙을 유지한다.

- HWP 원본을 불변 보존한다.
- 검증된 HWPX 변환 결과를 의미 구조 canonical로 사용한다.
- PDF는 페이지 시각 확인과 locator 보조 파생본으로 사용한다.
- 변환기·추출기 이름, 버전, upstream commit, binary hash를 structure에 기록한다.

PDF만 canonical로 바꾸면 표의 행·열, heading 계층, 요구사항 ID 연결이 약해질 수 있다.
반대로 HWPX만으로 실제 페이지와 시각 배치를 정확히 증명하기 어려울 수 있으므로 둘은
대체 관계가 아니라 의미 구조와 시각 검증의 보완 관계로 평가한다.

### 7.2 `edwardkim/rhwp` 조건부 A/B

[edwardkim/rhwp](https://github.com/edwardkim/rhwp)는 직접 구조·표 추출과 PDF/SVG/PNG
출력을 제공하는 별도 후보이다. 현행 HWPX 기준선이 다음 유형에서 품질 gate를 통과하지
못할 때만 A/B를 연다.

- 표 셀 또는 요구사항 ID 누락
- 실제 페이지와 locator 불일치
- heading·목차 연결 실패
- HWP→HWPX 변환 단계의 구조 손실

A/B는 동일 원본 hash, 동일 gold, 동일 역할 프롬프트로 수행한다. 채택 시 Skill이나 범용
MCP가 아니라 version과 commit을 고정한 CLI subprocess를 기존 networkless document
worker 안에 연결하는 방식을 우선한다. upstream의 MCP 기능은 개발자 수동 조사에는 쓸 수
있지만 운영 문서 정본, DB, MinIO 자격증명을 직접 받지 않는다.

## 8. 실패와 사람 검토 전환

| 실패 | 처리 |
|---|---|
| 변환·구조 hash 불일치 | 모델 호출 없이 `structure_unavailable` 또는 사람 검토 |
| 목차·heading 경계 불명확 | segment를 `needs_human_review`로 남김 |
| 요구사항 ID inventory 불완전 | 역할 결과를 완주로 발행하지 않음 |
| 역할 JSON schema 위반·잘림 | 제한 재시도 후 stage 실패 |
| 원문 인용·locator 불일치 | claim을 미검증으로 두고 validation 실패 |
| 역할 간 자격·위험 판정 충돌 | 종합 역할에 확정 사실로 전달하지 않음 |
| 회사 사실 부재 | `unknown`과 확인 행동을 남김 |
| 모델 endpoint 장애 | hosted provider로 자동 fallback하지 않음 |

부분 성공은 성공과 구분해 저장한다. 기존 report revision과 사람 의견을 덮어쓰지 않는다.

## 9. 구현 순서와 수용 기준

**1~3과 5·6의 결정적 부분은 [ADR-0051](../tracking/decisions/0051-deep-review-v2-deterministic-subset.md)로 이미 구현했다.** 남은 항목(4·7·8과 5·6의 모델 관련 부분)은 [Luna 시안·품질 검증 계획](luna-evaluation-plan.md)의 승인 뒤 시작한다.

1. segment·inventory 후보 계약과 fixture를 확정한다.
2. HWPX 기준 결정적 heading/ID inventory와 segmenter를 구현한다.
3. `compare_requirement_ids()`를 실제 deep-review 검증 경로에 연결한다.
4. 기존 3단계 안에 역할별 입력 allowlist와 출력 schema를 추가한다.
5. 결정적 점수·근거·coverage 검증을 추가한다.
6. 검증된 결과만 기존 report materializer에 연결한다.
7. API/UI 확장이 필요하면 새 version 계약과 이전 소비자 호환을 함께 구현한다.
8. HWPX 실패가 측정된 경우에만 `edwardkim/rhwp` A/B와 통합을 별도 수행한다.

최소 수용 기준은 다음과 같다.

- gold에 있는 명시적 요구사항 ID recall 100%
- 확정된 segment 경계 오류 0건
- 필수 자격 false positive 0건
- report의 source hash·locator·인용 검증 100%
- 배점·금액·기간 산술 검증 100%
- 회사 결측 사실의 `unknown` 보존 100%
- validation 실패가 성공 report나 사람 최종결정으로 자동 승격되는 경로 0건
- 기존 deep-review API, revision history, final opinion 회귀 테스트 통과

이 문서는 목표 설계다. 위 §2 표에서 **결정적 부분 구현됨**으로 표시한 것 말고는, 승인된 평가
결과와 후속 ADR·계약 변경 전에 현재 런타임이 그 동작을 제공한다고 표시하지 않는다.
