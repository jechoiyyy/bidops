# Qwen–Luna 심층 검토 평가 인수인계

> 상태: **분석 구조 결정 대기 — Qwen 심층 시험 미실행**  
> 기준일: 2026-09-17 (KST)  
> 다음 문서: [완료된 실험](experiment-results.md), [후속 평가 계획](evaluation-plan.md)

## 1. 목적

사전규격 제안요청서를 개요 검토와 심층 검토에 사용할 입력으로 구성하고, Qwen과 Luna의
결과 품질·비용·처리 시간을 같은 조건에서 비교한다. 문서 양식은 유사하지만 일치하지 않으므로
고정 목차 번호만으로 범위를 정하지 않는다.

이 폴더는 2026-09-17 논의와 로컬 표본 실험의 현재 상태를 새 세션에서 그대로 이어가기 위한
정본이다. 완료된 사실과 앞으로 할 일을 구분하며, 기존 참조 실행을 운영 품질 근거로 승격하지
않는다.

## 2. 현재 합의

- HWP 원본은 보존하고 `rhwp export-hwpx --verify`로 HWPX를 만든다.
- `--verify-pages`는 사용하지 않는다.
- 변환 HWPX와 rhwp 페이지 텍스트를 모델 입력과 페이지 locator의 정본으로 사용한다.
- 별도로 입수한 PDF의 물리 페이지를 HWPX 페이지와 같다고 가정하지 않는다.
- Qwen 시험을 먼저 수행하고 그 결과를 검토한 뒤 Luna를 비교한다.
- Luna 비교는 API가 아니라 격리된 `codex exec`, 모델 `gpt-5.6-luna`, reasoning
  `medium`으로 수행한다.
- Luna API와 Batch 연동은 Luna가 최종 채택된 뒤에만 설계·구현한다.
- 모델의 원본 응답은 자동 보정하지 않는다. 스키마·페이지·요구사항 ID·숫자·근거 검증은
  별도의 결정적 검사로 수행한다.
- 어떤 모델이 선택되더라도 자동 입찰이나 최종 Go/No-Go를 수행하지 않는다.

## 3. 반드시 구분할 세 가지 실행 구조

### 실제로 완료한 Luna medium 요약 시험

`luna-medium-review-summary-20260917-144029` 실행은 영역별 모델 호출이 아니었다.

- 개요와 심층을 문서별로 각각 한 번 호출했다.
- 심층은 page plan에서 `review_use=deep_review`인 모든 페이지를 합친 단일 입력이었다.
- `purposes`는 필터로 쓰지 않았다(`purpose_filtering=false`).
- 개요 페이지를 심층에 공유하지 않았다(`overview_shared_with_deep_review=false`).
- 한 응답 안에서 기술·운영·보안·자격·계약·예외 영역을 작성했다.

따라서 이 결과를 "영역별로 필요한 원문만 본 Luna 결과"라고 설명하면 안 된다.

### 현재 제품의 Qwen 심층 검토

현재 런타임은 `requirements_and_evaluation`, `delivery_risk_economics`,
`synthesis_and_validation` 세 단계다.

- 1단계는 묶음의 문서 원문 전체를 페이지 excerpt로 만들고 약 18,000자 예산으로 나눠 읽는다.
- 2단계도 문서 원문 전체를 약 15,000자 예산으로 다시 나눠 읽고 회사 profile slice를 붙인다.
- 2단계가 1단계 결과만 소비하는 구조는 아니다.
- 3단계는 원문 전체 대신 앞 단계에서 검증된 claim과 evidence를 소비한다.

즉, 단계가 세 개여도 1·2단계가 목적별 페이지만 받는 현재 구현은 아니다.

### 과거 Deep Review v2 역할별 설계안

[기존 분석 설계](../deep-review-v2/document-analysis-design.md)와
[Luna 평가 계획](../deep-review-v2/luna-evaluation-plan.md)에는 문서를 목적별로 분할하고
역할별 모델 분석을 수행하는 목표안이 있다. 결정적 segment manifest와 요구사항 inventory는
구현됐지만 역할별 모델 분석과 Luna 평가는 채택·실행되지 않았다.

이 목표안과 실제 Luna medium 요약 시험, 현재 3단계 제품 코드를 같은 것으로 취급하지 않는다.

## 4. 현재 미확정 결정

Qwen 심층 시험 전에 아래 두 구조 중 하나를 확정해야 한다.

### A. 문서당 단일 모델 호출

- 선택된 심층 페이지를 한 입력으로 보낸다.
- 한 응답에서 기술·기능, 수행·운영, 품질·보안, 자격·평가, 계약·책임, 위험·종합을 생성한다.
- 호출 수가 적고 Qwen과 Luna를 동일한 입력으로 비교하기 쉽다.
- 모델이 모든 원문을 함께 보므로 영역별 입력 격리는 보장하지 않는다.
- Qwen page plan이 심층에서 문서 대부분을 선택하면 분할 호출의 비용 절감 효과가 작다.

### B. 영역별 입력과 모델 호출

- 각 영역에 관련된 segment만 전달한다.
- 각 모델 호출은 자기 영역 원문만 보며, 검증된 결과를 별도 종합 단계가 소비한다.
- 영역별 입력 격리와 누락 원인 추적이 가능하다.
- 페이지가 여러 목적에 속하면 중복 입력이 생기며 호출 수와 병합 계약이 늘어난다.
- "한 호출 안에 영역별 텍스트 필드를 나눠 넣기"는 모델이 모든 필드를 볼 수 있으므로 엄격한
  입력 격리가 아니다.

2026-09-17 마지막 논의에서 사용자는 Luna가 실제로 B 방식으로 시험된 것으로 이해하고 있었으나,
실행 기록상 기존 Luna 시험은 A 방식이었다. 이 차이를 확인한 상태에서 대화가 문서화 요청으로
전환됐다. **다음 세션은 A와 B 중 원하는 구조를 먼저 확인하고, 그 전에는 새 Qwen 심층 호출을
시작하지 않는다.**

## 5. 표본과 주요 산출물

Linux 표본 루트:

```text
/mnt/c/Users/rootlab/Downloads/sample
```

| ID | 문서 | HWPX/rhwp 페이지 |
|---|---|---:|
| 01 | 소방안전 빅데이터 플랫폼 위탁운영 | 94 |
| 04 | 반도체 소재·부품 정보제공 플랫폼 고도화 | 60 |
| 03 | 대구산업경제동향 시스템 기능개선·유지보수 | 20 |

주요 결과 디렉터리:

```text
qwen-v2-page-plan-20260917-172202/
luna-medium-revised-page-plan-20260917-142125/
luna-medium-review-summary-20260917-144029/
qwen-hwpx-pdf-overview-ab-20260917-173725/
hwpx-pdf-overview-ab-20260917-173238/
```

각 디렉터리의 `experiment.json`, `token-usage.json`, `execution.json`, 원본 응답과 validation을
함께 읽는다. `comparison.md`만으로 모델 품질이 승인됐다고 판단하지 않는다.

## 6. 다음 세션 시작 순서

1. 이 문서와 [완료된 실험](experiment-results.md)을 읽는다.
2. A 단일 호출과 B 영역별 호출 중 의도한 분석 구조를 사용자에게 확인한다.
3. 선택한 구조를 [후속 평가 계획](evaluation-plan.md)의 해당 분기에 고정한다.
4. HWP 3건을 `rhwp export-hwpx --verify`로 다시 준비한다.
5. 페이지별 텍스트 hash가 기존 Qwen v2 입력과 같은지 확인한다.
6. Qwen 심층 시험을 실행하고 원문 대조를 마친다.
7. 같은 입력 계약으로 Luna medium `codex exec`를 실행한다.
8. 사람 평가와 결정적 검증을 통과한 뒤 모델과 제품 구조를 결정한다.

## 7. 저장소 변경 경계

- 이 기록을 작성하는 시점에는 제품 코드, DB, REST 계약, 활성 모델 정책을 변경하지 않는다.
- 새 모델 실행은 `unmeasured_reference`, `deployable=false`로 취급한다.
- Qwen 또는 Luna 선택 전까지 현재 심층 검토 런타임을 교체하지 않는다.
- 기존 작업 트리의 다른 변경과 `docs/0916_deep-review-ui`,
  `docs/0917_opportunity-tracking` 등 다른 미추적 작업은 건드리지 않는다.
