# Qwen 우선 심층 검토 평가 계획

> 상태: **분석 구조 결정 대기**  
> 선행 문서: [인수인계](README.md), [완료된 실험](experiment-results.md)

## 1. 평가 질문

1. Qwen과 Luna 중 어느 모델이 원문 사실·요구사항·조건·예외를 더 정확하고 충분하게
   정리하는가?
2. 문서 분할과 영역별 routing이 모델 입력량과 누락 원인 추적에 실질적인 이득을 주는가?
3. HWPX 페이지와 요구사항 inventory로 모델 결과를 결정적으로 검증할 수 있는가?
4. 선택한 구조를 하루 평균 25~30건의 `SW사업대상=Y` 유입에 적용할 때 호출 수와 비용은
   어느 정도인가?

## 2. 실행 전 결정 게이트

새 Qwen 심층 호출 전에 분석 구조를 하나로 확정한다.

### 안 A: 문서당 단일 호출

- 입력: `deep_review`로 선택한 페이지와 필요한 공통 문맥의 합집합
- 호출: 모델별 문서당 1회
- 출력: 한 JSON 안의 기술·기능, 수행·운영, 품질·보안, 자격·평가, 계약·책임, 위험·종합
- 장점: 호출·병합 계약이 단순하고 모델 비교 입력을 맞추기 쉽다.
- 한계: 영역별 입력 격리가 없고, Qwen 분할이 문서 대부분을 선택하면 분할 호출의 비용 이득이
  작다.

### 안 B: 영역별 호출과 종합

- 입력: 영역별 `purposes`에 해당하는 segment의 페이지 합집합
- 호출: 독립 영역 분석을 병렬 실행하고 검증된 결과만 종합 호출에 전달
- 출력: 영역별 구조화 결과와 최종 종합 JSON
- 장점: 각 영역이 보는 원문을 제한하고 누락·왜곡 원인을 해당 영역으로 좁힐 수 있다.
- 한계: 혼합 페이지 중복, 호출 수 증가, claim identity와 병합·충돌 계약이 필요하다.

한 요청 안에 여섯 입력 필드를 구분해 넣는 방식은 안 A로 분류한다. 모델이 모든 필드를 볼 수
있으므로 안 B의 입력 격리를 제공하지 않는다.

선택한 안은 Qwen과 Luna에 동일하게 적용한다. 서로 다른 구조를 사용한 결과는 모델 성능 비교로
사용하지 않는다.

## 3. 입력 준비

표본은 소방(01), 반도체(04), 대구(03) 세 건이다.

1. 원본 HWP SHA-256을 기존 manifest와 대조한다.
2. `rhwp export-hwpx INPUT OUTPUT --verify --json`으로 새 HWPX snapshot을 만든다.
3. `--verify-pages`는 사용하지 않는다.
4. rhwp 버전·binary SHA-256, 종료 상태, 원본·변환본 SHA-256을 기록한다.
5. HWPX를 페이지 텍스트로 추출하고 page count, 빈 페이지, 페이지별 SHA-256을 기록한다.
6. 기존 Qwen v2 입력과 page count 및 페이지별 텍스트 hash가 모두 같으면 기존 page plan을
   재사용한다.
7. 하나라도 다르면 해당 문서만 새 snapshot에서 page plan을 다시 생성한다.

기존 page plan을 재사용할 때도 그 plan의 `pdf_physical_1_based_inclusive` 문자열을 HWPX 근거로
그대로 주장하지 않는다. 입력 manifest에 기존 plan의 페이지 번호가 새 HWPX 페이지와 1:1로
일치했음을 별도로 기록한다.

## 4. Qwen 실행

공통 조건:

- 모델 `qwen3.8-27B`
- 승인된 사설 vLLM의 `deep_review` 목적 endpoint
- thinking 비활성
- temperature 0.7, top_p 0.8, top_k 20, seed 0
- 입력 상한 preflight와 strict JSON Schema
- 원본 response와 파싱 결과 분리 보존
- `quality_status=unmeasured_reference`, `deployable=false`

안 A가 선택되면 문서별 입력을 한 번 호출한다. 안 B가 선택되면 영역별 입력 mapping, 중복 허용
규칙, 종합 입력 allowlist를 실행 전에 schema와 manifest에 고정한다. 결과를 본 뒤 특정 문서만
prompt나 mapping을 바꾸지 않는다. 변경이 필요하면 새 prompt/policy version으로 전체 표본을
다시 비교한다.

결과 디렉터리 권장 형식:

```text
/mnt/c/Users/rootlab/Downloads/sample/qwen-hwpx-deep-review-<timestamp>/
  experiment.json
  artifact-manifest.json
  token-usage.json
  validation-summary.json
  comparison.md
  01|04|03/
    preparation.json
    pages.json
    page-plan.json
    input*.json
    response*.json
    result*.json
    execution*.json
```

## 5. Qwen 원문 대조

Qwen 실행 후 Luna를 호출하기 전에 다음을 완료한다.

- JSON Schema와 문서·snapshot identity 검사
- 모델이 선언한 source pages와 실제 입력 페이지 일치
- 모든 evidence page가 입력 범위 안에 존재
- 요구사항 ID가 결정적 inventory에 존재
- gold 요구사항 ID recall
- 금액·기간·배점·비율·수량의 원문 대조
- 필수 자격·평가·제출·보안·계약·예외의 중대 누락
- 원문에 없는 의무·자격·회사 역량 생성
- 상충하거나 확인할 수 없는 내용을 `unknown|conflict`로 보존했는지 확인
- 텍스트로 확인할 수 없는 표·도식·이미지를 확정 사실로 만든 사례 확인

실패 원인은 다음 셋으로 구분한다.

1. 모델 입력에 필요한 원문이 없었음
2. 입력에는 있었지만 모델 결과가 누락·왜곡했음
3. HWPX 추출 단계에서 원문 구조나 시각 정보가 보존되지 않았음

## 6. Luna 동등 입력 비교

Qwen 검토가 끝난 뒤 같은 분석 구조로 Luna를 실행한다.

- 모델 `gpt-5.6-luna`
- reasoning `medium`
- 격리된 `codex exec`
- user config, project rules, web, shell, apps, hooks, plugins, memory와 multi-agent 비활성
- ephemeral, read-only sandbox
- Qwen과 동일한 입력 projection, 시스템 프롬프트와 출력 스키마
- 도구 호출 0건 검사
- 원본 output 자동 보정 금지

문서·영역별 입력 SHA-256이 Qwen 실행과 같지 않으면 해당 결과는 직접 비교에서 제외한다.

## 7. 평가와 채택 기준

필수 게이트:

- gold의 명시적 요구사항 ID recall 100%
- 필수 자격 false positive 0건
- 중대 자격·평가·계약·예외 누락 0건
- 금액·기간·배점 산술 검증 100%
- 핵심 claim의 유효 locator 100%
- 회사 자료에 없는 역량의 임의 확정 0건
- validation 실패가 성공 결과로 승격되는 경로 0건

비교 지표:

- 입력·cached input·출력·reasoning 토큰
- 문서당 호출 수와 재시도 수
- wall-clock 시간
- 영역별 누락·왜곡·unsupported claim 수
- 사람이 평가한 정확성·충분성·읽기 용이성
- 일일 25건과 30건 기준 예상 토큰·비용

사람 평가는 가능한 한 모델명을 가린 결과로 수행한다. 모델 출력을 gold로 사용하지 않는다.

## 8. 모델 선택 뒤 제품 반영

- 선택 모델과 분석 구조를 새 policy version으로 만든다.
- 현재 활성 정책과 과거 review/result는 덮어쓰지 않는다.
- 선택 구조에 맞게 입력 snapshot, stage 또는 영역 상태, raw response, validation과 report
  materialization 계약을 함께 변경한다.
- Qwen 선택 시 승인된 사설 vLLM 경계를 유지한다.
- Luna 선택 시에만 OpenAI API와 Batch adapter를 설계한다.
- Luna Batch 설계에서는 payload allowlist, 모델 snapshot, secret 마스킹, batch 상태와 결과 결합,
  부분 실패, 재시도, 24시간 완료 창과 비용을 별도로 검증한다.
- 외부 provider 장애 시 hosted 모델로 자동 fallback하지 않는다.
- 품질 게이트와 운영 활성화는 별도 결정으로 유지한다.
