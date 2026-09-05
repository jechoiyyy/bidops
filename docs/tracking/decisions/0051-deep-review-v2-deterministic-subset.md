# deep-review-v2의 결정적 부분만 먼저 채택하고 역할별 모델 분석과 Luna 평가는 보류한다

- 상태: 채택 — 부분 채택
- 일자: 2026-09-05

## 맥락

[`docs/deep-review-v2/document-analysis-design.md`](../../deep-review-v2/document-analysis-design.md)는
제안요청서를 목적별로 분할하고 역할별 모델 분석을 붙여 심층 리포트를 만드는 설계를
`제안` 상태로 두었다. 그 설계는 구현 순서 §9에서 자신을
[`luna-evaluation-plan.md`](../../deep-review-v2/luna-evaluation-plan.md)의 승인 뒤에 시작한다고
적었다.

Luna 평가 계획은 실행되지 않았고, 실행할 수도 없다. `docs/security.md`가 실험용 외부 모델에
공개 발주계획 metadata와 승인된 회사 역량 요약만 허용하며 제안요청서·첨부 전송을 금지하기
때문이다. 계획 자신이 §2에서 "현 정책 상태에서는 이 실험을 실행할 수 없다"고 적고 1회성
제한 예외 승인을 선행 조건으로 걸어 두었다. 그 승인은 나지 않았다.

그런데 설계가 담고 있는 것 중 **모델을 전혀 부르지 않는 부분**이 있다.

- 범용 taxonomy에 따른 문서 segment 경계 탐지
- 요구사항 ID inventory 추출과 누락·중복·예상 밖 ID 비교
- segment coverage(간극·중첩) 계산
- 그 결과를 심층 검토 검증 경로에 연결

이 넷은 규칙과 문서 구조만으로 결정된다. 확률도 모델 응답도 없다. 이것들을 Luna 평가에
묶어 두면 실행되지 않는 외부 승인 하나 때문에 결정적 검증이 계속 대기한다. 반대로 이것들을
먼저 넣으면, 나중에 역할별 모델 분석을 붙일 때 **모델이 무엇을 보아야 하는지**를 이미
결정적으로 알고 있는 상태에서 시작한다.

## 결정

deep-review-v2 설계에서 **모델을 부르지 않는 부분만** 채택해 구현하고, 역할별 모델 분석과
Luna 외부 평가는 보류한다.

### 1. 채택하는 것 — 결정적 segment와 요구사항 inventory

문서 구조를 저장할 때 같은 메모리 payload에서 segment manifest를 함께 만든다. 저장 대상은
세 표다.

- `document_segment_manifest` — 구조 하나에 대한 manifest. taxonomy version, extractor
  binding과 그 SHA-256, payload hash, inventory 요약, coverage, 경고를 갖는다.
- `document_segment` — 순서가 있는 segment. taxonomy label, 시작·끝 locator, 요구사항 ID,
  source block key, 상태를 갖는다.
- `requirement_inventory_item` — 문서에서 읽은 요구사항 ID 항목.

세 표 모두 append-only다. `schema_version` 열은 두지 않는다 — 판을 표시하는 것은
`taxonomy_version`과 `extractor_binding`이고, 규칙이 바뀌면 `rules_sha256`이 바뀌어
**새 identity 키 = 새 row**가 된다. 유일키는 `(structure_id, taxonomy_version,
extractor_binding_sha256)`이다.

taxonomy version은 `bidops.segment-taxonomy.v1`이고 label은 넷이다.
`business_eligibility_evaluation`, `technical_functional`, `quality_security_constraints`,
`partnership_governance`.

**분류 출처는 `deterministic` 고정이고 `confidence`는 언제나 `null`이다.** 결정적 규칙에는
확률이 없다. 규칙이 경계를 정하지 못한 자리는 확률을 지어내지 않고 `status`로 구분한다 —
`classified` 또는 `needs_human_review`다.

읽기 계약은 `GET /api/document-structures/{structure_id}/segments`(`bidops.document-segments.v1`)
하나다. **응답에 원문 text가 없다.** locator와 block key만 준다. 구조가 없거나 manifest가
없으면 404 `not_found`, 안전하지 않은 문서는 403 `unsafe_document`다.

### 2. 채택하는 것 — 검증 경로 연결

심층 검토 검증에 결정적 check 두 종을 더한다.

| check | 실패 등급 | 규칙 |
|---|---|---|
| `requirement_inventory` | 누락·예상 밖 ID는 `failed`·중대, 중복은 warning, ID 체계가 없는 문서는 warning "inventory 없음" | 문서가 준 ID 집합과 claim이 적은 ID 집합을 대조 |
| `segment_coverage` | warning·보통 | 간극·중첩을 표시하되 차단하지 않는다 |

stage 1 claim에는 요구사항 ID 필드가 없으므로 claim 본문에서 결정적으로 읽는다. **문서에
ID 체계가 있는데 claim이 ID를 적지 않으면 `requirement_inventory`가 `failed`가 된다.** 이것이
이번 채택이 만든 유일한 동작 변화이며, 기존에 통과하던 리뷰를 뒤집을 수 있다. 설계의 의도
그대로다 — 요구사항 전수성은 형식 완결성으로 대신할 수 없다.

### 3. 보류하는 것

다음은 이번에 구현하지 않는다.

- 역할별(입찰·사업성 / 기술 적합성 / 위험·거버넌스 / 종합) 모델 분석과 그 출력 schema
- segment의 **모델 보조 분류** — 이번 구현은 결정적 규칙만 쓴다
- `edwardkim/rhwp` 조건부 A/B와 구조 추출 교체
- Luna(`gpt-5.6-luna`) 외부 평가 실행

`document-analysis-design.md`는 `제안` 상태를 유지하되, 위 1·2에 해당하는 항목은
**결정적 부분 구현됨**으로 표시한다. `luna-evaluation-plan.md`는 실행하지 않은 계획으로
그대로 남기고 상태만 **보류(결정적 부분 먼저 구현)**로 바꾼다. 그 계획의 어떤 지표도
측정되지 않았고, 실행하지 않은 계획을 근거로 쓰지 않는다.

## 대안과 기각 이유

- **Luna 승인까지 전부 대기한다** — 외부 전송 예외 승인은 이 저장소가 만들 수 없고 시점도
  알 수 없다. 그동안 요구사항 누락을 잡을 결정적 검증이 없는 상태가 이어진다.
- **segment 분류에 모델을 함께 쓴다** — 확률이 들어오면 `confidence`를 저장해야 하고,
  그 값이 낮을 때 무엇을 할지가 새 정책이 된다. 결정적 규칙만으로 두면 못 정한 자리가
  `needs_human_review`로 그대로 드러난다.
- **manifest를 나중에 재구성한다** — `document_block`에 ordinal이 없어 저장 시점의 메모리
  payload 없이는 경계를 되짚을 수 없다. 그래서 이 변경 **전에** 만들어진 구조는 manifest가
  없고 조회가 404다. 이 사실을 findings와 운영 절차서에 적는다.
- **응답에 segment 제목이나 본문을 싣는다** — 원문 text를 wire에 싣지 않기로 한 기존 경계를
  깬다. 목록은 ordinal·taxonomy label·요구사항 ID·block key·page 링크만 보이고, 제목이 없는
  이유를 화면이 직접 밝힌다.

## 결과

- 심층 검토 검증이 요구사항 전수성을 결정적으로 확인한다.
- 보고서 화면이 문서 inventory와 사람 확인 필요 segment를 보여 준다. 다만 묶음에서 문서들의
  `structure_id`를 얻을 endpoint가 없어 **선택된 근거가 가리키는 문서 하나**만 보인다.
  화면이 그 사실을 문장으로 밝힌다. findings에 기록했다.
- 역할별 분석을 나중에 붙일 때 입력 분할 계약이 이미 있다.
- 이 결정은 모델 품질을 측정하지 않았고 어떤 운영 활성화 근거도 만들지 않는다.
