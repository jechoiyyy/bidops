# C-2 발주계획 선별은 BM25 Top 300 뒤 Qwen으로 확정한다

- 상태: 채택
- 일자: 2026-09-01

## 맥락

[ADR-0021](0021-filter-experiment-before-implementation.md)은 발주계획 선별 제품을 만들기 전에
고정 모집단에서 비용·누락·검토량을 비교하고 사람이 방식을 선택하도록 했다. C-2 선택을 위해
2026-08-27 00:00부터 2026-08-31 00:00 미만 KST의 일반용역·기술용역 625건을 고정하고,
BM25 상위 300건에 사설 vLLM Qwen을 적용했다.

실행 정본은
[`20260827-20260830-bm25-qwen300-v3`](../../../data/experiments/order-plan-screening/20260827-20260830-bm25-qwen300-v3/)이고,
사람의 C-2 선택은
[`selection-decision.json`](../../../data/experiments/order-plan-screening/20260827-20260830-bm25-qwen300-v3/selection-decision.json)에
기록했다. 결정 파일 SHA-256은
`e242077be204fddb6213bb4ba96f24ec51a8acac3cc5fb95654a191be9c1aa44`다.

## 결정

C-2 발주계획 1차 선별 방식을 `BM25 Top 300 + Qwen`으로 확정한다.

1. 전체 발주계획 제목을 BM25로 순위화하고 상위 300건만 2단계로 보낸다.
2. Qwen은 승인된 회사 역량 v1과 제목만 받고 25건씩 고정 batch로 판정한다.
3. Qwen의 `relevant`와 `uncertain`을 사람 검토 후보로 유지한다.
4. BM25 탈락 325건은 Qwen의 `not_relevant` 판정으로 바꾸지 않고
   `stage1 filtered_out`으로 보존한다.
5. Qwen 실패를 다른 모델이나 hosted OpenAI로 자동 전환하지 않는다.

고정 binding은 다음과 같다.

- BM25 config SHA-256:
  `e026b2bdd2f99ddc09ae17bc83b1cd9cc40ef413f3b72372a35db32918d696da`
- Qwen model: `qwen3.8-27B`
- Qwen revision:
  `6ae70ca30563209f09ec0114ce5813f7a232b38e5bb409f2adbd0e9bbe318b11`
- prompt: `order-plan-batch-relevance-v3`, SHA-256
  `639f7332e1120a41b2e8d8306126f121ae1ed37068a81b1687aff9ce66ab9d12`
- 회사 역량 파일 SHA-256:
  `8f60dfece1934bdf857cd7e57d0fdd1860d01871131d98c3f2e8f9d71f271eae`

## 측정된 교환

gold v2 전체 625건 기준으로 관련 59건 중 57건을 `relevant|uncertain`으로 유지했다.

| 지표 | 측정값 |
|---|---:|
| BM25 선택 / 탈락 | 300 / 325 |
| Qwen 성공 / 실패 | 300 / 0 |
| 검토 유지 recall | 96.61% |
| 검토 유지 precision | 44.88% |
| 사람 검토 후보 | 127건 |
| Qwen 소요시간 | 598,947ms |
| Qwen 입력 / 출력 / 총 token | 23,725 / 20,458 / 44,183 |

Qwen direct 대비 검토 유지 recall은 3.39%p 낮고, Qwen 소요시간과 token은 각각 약 52% 줄었다.
사람 검토 후보는 142건에서 127건으로 15건 줄었다. C-2 결정권자는 이 교환을 수용했다.

## 수용한 누락

BM25 1단계가 다음 두 건을 놓쳤다. 둘 다 현재 gold에서 `관련`, 우선순위 `낮음`,
label source `draft`다.

| plan ID | BM25 rank | 사업명 |
|---|---:|---|
| `R26DD20855622` | 447 | 춘의동 일원(K26) 노후 상수도관 교체공사 GIS DB 갱신 용역 |
| `R26DD20857501` | 538 | 화생방 제독작전모의 SW 구현 용역 |

누락 기록 정본은
[`accepted-stage1-misses.tsv`](../../../data/experiments/order-plan-screening/20260827-20260830-bm25-qwen300-v3/review/accepted-stage1-misses.tsv)이고
SHA-256은 `ba8aea251e39e0b83cf2ecb85c220fa62213d72635471a6579a21ba7a741d13c`다.

## 경계와 후속

이 결정은 C-2 방식 선택을 닫는다. 제품의 stage 구조와 불변 결과 계약 구현은 착수할 수 있다.
다만 아래를 자동으로 뜻하지 않는다.

- 현재 draft label을 전부 사람 정답으로 승격
- negative prompt v4 승인 또는 적용
- cutoff·재검토 감사 표본을 포함한 운영 정책 버전 확정
- scheduler·always-on 활성화
- 적합성 등급, 참여 준비 상태, 추적 선택, 최종 입찰 Go/No-Go 자동 결정

threshold와 감사 표본 정책은 별도 version으로 고정하고 품질 게이트를 통과한 뒤 운영자가
명시적으로 활성화한다.

## 대안

- Qwen direct는 관련 59건을 모두 검토 후보로 유지하지만 Qwen 시간과 token이 약 두 배다.
- BM25 단독은 모델 비용이 없지만 제목 어휘 불일치와 역할 판단을 보완하지 못한다.
- dense/RRF 또는 다른 LLM 조합은 같은 모집단·정답으로 다시 비교할 수 있지만 이번 C-2의
  선택을 자동 대체하지 않는다. 대체하려면 새 결정과 새 binding이 필요하다.
