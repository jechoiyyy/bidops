# 발주계획 선별 `interim-v4`·`interim-v5`·`interim-v6` 회차 비교 분석

검증일: 2026-08-28 (KST)  
실행 ID: `20260824-20260826-interim-v4`, `20260824-20260826-interim-v5`, `20260824-20260826-interim-v6`  
분석 방식: 저장된 불변 산출물만 읽은 read-only 사후 분석. 분석 중 모델·네트워크를 호출하거나 기존 산출물을 수정하지 않았다.

## 결론

- 세 회차는 동일한 불변 raw 표본 997건을 사용했다. Qwen은 v4에서 747건 성공·250건 `truncated_output`, v5에서 597건 성공·400건 `timeout`, v6에서 997건 전부 성공했다.
- v4와 v6의 공정 비교 집합은 양쪽 모두 `status=success`인 plan_id 747건이다. 이 집합에서 v4→v6의 relevance는 `relevant` 99→149건, `uncertain` 88→196건, `not_relevant` 560→402건으로 이동했다. 이는 의도한 방향과 일치하는 분포 이동이지만 사람 정답에 의한 품질 개선을 뜻하지 않는다.
- v6의 reason에는 신규 capability 4개가 각각 29건, 6건, 21건, 77건 인용됐다. 인용된 항목의 v6 판정은 `relevant` 또는 `uncertain`에만 있었으나, v4에는 해당 capability가 없었고 v4 일부 항목은 실패했으므로 이 결과만으로 capability의 선별 품질을 판단할 수 없다.
- 제목 키워드 부분집합에서도 네 도메인의 `relevant`·`uncertain` 증가와 `not_relevant` 감소가 관찰됐고, Qwen Top-50 진입 수는 소방·재난안전 0→1, 헬스케어·의료 1→0, 교육·학습 5→8, R&D·실증 3→4였다. 단순 제목 키워드 집합이며 사람 정답이 없으므로 품질 결론은 내리지 않는다.
- v4·v6 Qwen Top-50 교집합은 31건이다. v6의 Qwen·TF-IDF·BGE-M3 dense Top-50 세 방식 모두에 공통인 건수는 12건이다.
- 성공 결과의 `reason`은 v4 747건과 v6 997건 모두 150자 상한을 넘지 않았고, relevance-score 구간 위반도 양 회차 모두 0건이었다.
- v4→v6에는 capabilities, prompt, 최대 출력 토큰, timeout이 동시에 바뀌었다. 따라서 관찰된 relevance 이동을 어느 한 변경의 효과로 귀속하지 않는다. 사람 정답과 별도의 단일 변수 실험 없이는 recall·precision·품질 우승·운영 활성화 결론을 낼 수 없다.

## 실행 범위와 고정 binding

세 회차 모두 조회 구간은 2026-08-24~26 (KST), 대상은 일반용역·기술용역, 모집단은 997건이며 별도 사전 필터는 없었다. Qwen 입력은 제목만 허용했고 세 회차의 결과 `input_sha256`은 `3a91dab71cd483faa45de393f1cbea990f7b543cc7a7b686e6fae5b18ab4d28f`로 같다.

| 항목 | `interim-v4` | `interim-v5` | `interim-v6` |
|---|---|---|---|
| capabilities | 6개 (`2ee0ebdd…`) | 10개 (`b2e07cba…`) | 10개 (`b2e07cba…`) |
| prompt | v2 (`593e3fdb…`) | v3 (`639f7332…`) | v3 (`639f7332…`) |
| 최대 출력 토큰 | 4,096 | 8,192 | 8,192 |
| 요청 timeout | 120초 | 120초 | 300초 |
| Qwen 결과 | 747/997 성공, 250 실패 (`truncated_output`) | 597/997 성공, 400 실패 (`timeout`) | 997/997 성공, 0 실패 |

Qwen 공통 설정은 `qwen3.8:27b` (digest `22130167…`), `think=high`, batch size 25, `temperature=0`, strict JSON schema다. v4의 기존 6개 capability는 `ai-data-analytics`, `data-platform-integration`, `blockchain-did-credentials`, `public-si-lifecycle`, `saas-cloud`, `ontology-knowledge-graph`이고, v5·v6에서 추가된 4개는 다음과 같다.

- `domain-disaster-fire-safety`
- `domain-healthcare-data`
- `domain-education-credentials`
- `delivery-research-poc`

prompt v2→v3의 변경은 유보 표현이 있는 capability 하나만 유일한 근거일 때 `relevant` 대신 `uncertain`을 우선하는 원칙 7 신설, relevance 확정 후 해당 구간에서 score를 정하도록 한 자기검증 문장 추가, `reason` 상한 500자→150자 변경의 세 가지다.

## 회차별 실행 결과와 지연 관측

| 방식 | 실행 상태 | 성공 / 모집단 | 실패 | 실패 코드 | selected | 총 소요시간 |
|---|---|---:|---:|---|---:|---:|
| Qwen v4 | `partial_failure` | 747 / 997 | 250 | `truncated_output` | 50 | 3,517.903초 |
| Qwen v5 | `partial_failure` | 597 / 997 | 400 | `timeout` | 50 | 4,391.155초 |
| Qwen v6 | `success` | 997 / 997 | 0 | 없음 | 50 | 4,632.346초 |

성공 배치의 실측 지연은 다음과 같다. v6의 최대 170초는 구 timeout 120초를 초과하므로 v5의 `timeout` 진단을 뒷받침하는 결정적 관측이다.

| 회차 | 성공 배치 중앙값 | 성공 배치 최대 |
|---|---:|---:|
| v4 | 91초 | 106초 |
| v5 | 105초 | 118초 |
| v6 | 110초 | 170초 |

## 분석 정의

- relevance 교차표와 도메인 relevance 변화는 v4와 v6 모두 `status=success`인 747건에서 계산했다. v4 실패 250건은 어떤 relevance도 부여하지 않고 제외했다.
- 전체 모집단 분포는 분모를 997건으로 고정하고, 실패 건을 별도 열에 표시했다. 실패를 `not_relevant`로 보정하지 않았다.
- capability 인용은 v6 `reason` 문자열에 capability ID가 한 번 이상 포함되는지로 집계했다. 하나의 reason이 여러 ID를 인용하면 각 ID에 각각 1건으로 집계하므로 capability별 수치는 서로 배타적이지 않다.
- 도메인 부분집합은 population title에 지정 키워드가 하나라도 포함되는 경우로 만들었다. 부분집합 간 중복은 허용했다. Top-50은 각 결과 JSON의 `selected=true`인 50건으로 집계했다.
- score 정합성은 `relevant: 0.65≤score≤1.0`, `uncertain: 0.35≤score<0.65`, `not_relevant: 0≤score<0.35`로 검사했다.

## 1. 공정 비교 집합과 relevance 이동

v4와 v6 양쪽에서 성공한 plan_id 교집합은 예상대로 747건이었다. `not_relevant < uncertain < relevant` 순서를 기준으로 이 집합의 이동은 동일 535건, 상승 198건, 하락 14건이다.

### v4 relevance × v6 relevance 교차표

| v4 \ v6 | `relevant` | `uncertain` | `not_relevant` | 합계 |
|---|---:|---:|---:|---:|
| `relevant` | 91 | 8 | 0 | 99 |
| `uncertain` | 34 | 48 | 6 | 88 |
| `not_relevant` | 24 | 140 | 396 | 560 |
| 합계 | 149 | 196 | 402 | 747 |

공통 성공 집합 내 분포는 v4의 `relevant` 99건(13.3%), `uncertain` 88건(11.8%), `not_relevant` 560건(75.0%)에서 v6의 `relevant` 149건(19.9%), `uncertain` 196건(26.2%), `not_relevant` 402건(53.8%)로 바뀌었다. 건수 변화는 각각 +50, +108, -158건이다.

### 전체 모집단 기준 분포

괄호는 997건 전체를 분모로 한 비율이다. relevance가 없는 실패 건은 별도로 표시했다.

| 회차 | `relevant` | `uncertain` | `not_relevant` | 실패·relevance 미기록 | 합계 |
|---|---:|---:|---:|---:|---:|
| v4 | 99 (9.9%) | 88 (8.8%) | 560 (56.2%) | 250 (25.1%) | 997 |
| v5 | 119 (11.9%) | 146 (14.6%) | 332 (33.3%) | 400 (40.1%) | 997 |
| v6 | 210 (21.1%) | 265 (26.6%) | 522 (52.4%) | 0 (0.0%) | 997 |

v4와 v5의 전체 모집단 표는 실패 건이 포함된 불완전 관측이다. 따라서 v4의 747건 성공 결과만으로 v6의 997건 분포와 직접 비교하면 누락 편향이 생기며, 위 교차표의 747건 공통 집합이 그 편향을 줄이는 비교 기준이다.

## 2. 신규 capability 4개의 인용과 판정 분포

v6 `reason`에서 10개 capability ID의 포함 건수를 모두 집계했다. 전체 ID 포함은 218개 result item에서 관찰됐고, ID별 포함 건수의 합은 306건이다. 이 중 77개 reason은 두 개 이상의 capability ID를 함께 인용했다.

| capability ID | v6 reason 인용 항목 수 | v6 `relevant` | v6 `uncertain` | v6 `not_relevant` | v6 score 중앙값 (범위) |
|---|---:|---:|---:|---:|---:|
| `ai-data-analytics` | 68 | 61 (89.7%) | 7 (10.3%) | 0 | 0.75 (0.40–0.90) |
| `data-platform-integration` | 42 | 41 (97.6%) | 1 (2.4%) | 0 | 0.80 (0.50–0.90) |
| `blockchain-did-credentials` | 2 | 2 (100.0%) | 0 | 0 | 0.80 (0.75–0.85) |
| `public-si-lifecycle` | 44 | 37 (84.1%) | 7 (15.9%) | 0 | 0.75 (0.40–0.90) |
| `saas-cloud` | 11 | 10 (90.9%) | 1 (9.1%) | 0 | 0.75 (0.50–0.85) |
| `ontology-knowledge-graph` | 6 | 5 (83.3%) | 1 (16.7%) | 0 | 0.825 (0.40–0.85) |
| `domain-disaster-fire-safety` 신규 | 29 | 14 (48.3%) | 15 (51.7%) | 0 | 0.50 (0.40–0.85) |
| `domain-healthcare-data` 신규 | 6 | 3 (50.0%) | 3 (50.0%) | 0 | 0.55 (0.45–0.75) |
| `domain-education-credentials` 신규 | 21 | 19 (90.5%) | 2 (9.5%) | 0 | 0.70 (0.40–0.90) |
| `delivery-research-poc` 신규 | 77 | 66 (85.7%) | 11 (14.3%) | 0 | 0.70 (0.45–0.85) |

신규 4개에 대해 relevance별 score 분포를 더 세분하면 다음과 같다. 표의 score는 `중앙값 (최솟값–최댓값)`이다.

| 신규 capability | v6 `relevant` | v6 `uncertain` | v6 `not_relevant` |
|---|---|---|---|
| `domain-disaster-fire-safety` | 14건, 0.70 (0.65–0.85) | 15건, 0.45 (0.40–0.50) | 0건 |
| `domain-healthcare-data` | 3건, 0.70 (0.65–0.75) | 3건, 0.45 (0.45–0.45) | 0건 |
| `domain-education-credentials` | 19건, 0.70 (0.65–0.90) | 2건, 0.425 (0.40–0.45) | 0건 |
| `delivery-research-poc` | 66건, 0.70 (0.65–0.85) | 11건, 0.50 (0.45–0.55) | 0건 |

v4에는 신규 4개 ID가 capability projection에 없으므로 v4 reason의 해당 ID 인용은 모두 0건이다. 같은 plan_id를 v4 결과에서 조회한 대조는 다음과 같다. v4 relevance는 v4 성공 건만 분모로 하며, v4 실패는 별도로 보존했다.

| v6에서 신규 ID를 인용한 항목 | v6 인용 수 | v4 성공 / 실패 | v4 `relevant` / `uncertain` / `not_relevant` | v4 score 중앙값 (범위, 성공분모) |
|---|---:|---:|---:|---:|
| `domain-disaster-fire-safety` | 29 | 18 / 11 | 1 / 2 / 15 | 0.05 (0.05–0.78) |
| `domain-healthcare-data` | 6 | 2 / 4 | 1 / 1 / 0 | 0.625 (0.40–0.85) |
| `domain-education-credentials` | 21 | 12 / 9 | 4 / 2 / 6 | 0.30 (0.05–0.90) |
| `delivery-research-poc` | 77 | 44 / 33 | 10 / 18 / 16 | 0.40 (0.05–0.85) |

따라서 신규 capability가 실제 reason에 사용된 사실과 v4 대비 판정 분포 차이는 확인되지만, 인용 자체는 모델의 자기 설명이며 사람 정답이나 원문 과업 검증을 대신하지 않는다.

## 3. 제목 키워드 기반 도메인별 변화

키워드 매칭 결과와 공정 비교에 사용된 분모는 다음과 같다. v6는 전건 성공이므로 `v4 성공`과 공통 성공 수가 같다.

| 도메인 | title 매칭 모집단 | v4 성공 | v4 실패 | 공통 성공 분모 |
|---|---:|---:|---:|---:|
| 소방·재난안전 (`소방`/`재난`/`119`/`산업안전`) | 30 | 24 | 6 | 24 |
| 헬스케어·의료 (`의료`/`병원`/`보건`/`헬스`/`치과`) | 27 | 23 | 4 | 23 |
| 교육·학습 (`교육`/`학습`/`배움`/`배지`) | 72 | 47 | 25 | 47 |
| R&D·실증 (`실증`/`연구개발`/`R&D`) | 12 | 11 | 1 | 11 |

공통 성공 분모에서 `relevant / uncertain / not_relevant` 건수와 v6-v4 변화는 다음과 같다.

| 도메인 | v4 R / U / NR | v6 R / U / NR | 변화 ΔR / ΔU / ΔNR |
|---|---:|---:|---:|
| 소방·재난안전 | 0 / 1 / 23 | 2 / 9 / 13 | +2 / +8 / -10 |
| 헬스케어·의료 | 2 / 0 / 21 | 4 / 5 / 14 | +2 / +5 / -7 |
| 교육·학습 | 8 / 10 / 29 | 18 / 20 / 9 | +10 / +10 / -20 |
| R&D·실증 | 4 / 2 / 5 | 9 / 1 / 1 | +5 / -1 / -4 |

Qwen Top-50에서 해당 title 부분집합에 속한 건수는 다음과 같다.

| 도메인 | v4 Qwen Top-50 | v6 Qwen Top-50 | 변화 |
|---|---:|---:|---:|
| 소방·재난안전 | 0 | 1 | +1 |
| 헬스케어·의료 | 1 | 0 | -1 |
| 교육·학습 | 5 | 8 | +3 |
| R&D·실증 | 3 | 4 | +1 |

이 분석은 title의 부분 문자열만 사용하므로 공사·설계·행사 등 도메인 과업이 아닌 항목의 오탐이 섞일 수 있다. 키워드 집합의 분포 이동은 탐색 의도와의 일치 여부를 보는 보조 관측이지, 도메인별 선별 품질 측정이 아니다.

## 4. Top-50 비교

각 방법의 `selected=true` 집합은 모두 50건이었고 rank 1–50과 일치했다.

| 비교 | 교집합 |
|---|---:|
| v4 Qwen ∩ v6 Qwen | 31건 (v4만 19건, v6만 19건) |
| v6 Qwen ∩ v6 TF-IDF | 22건 |
| v6 Qwen ∩ v6 BGE-M3 dense | 24건 |
| v6 TF-IDF ∩ v6 BGE-M3 dense | 25건 |
| v6 Qwen ∩ TF-IDF ∩ BGE-M3 dense | 12건 |

교집합 크기는 방법별 순위가 얼마나 겹치는지를 나타낼 뿐, 어느 방법이 사람 정답에 더 가깝다는 결론은 제공하지 않는다.

## 5. prompt v3 효과에 대한 결정적 검증

### `reason` 길이

성공 결과에 실제 문자열이 있는 건만 측정했으며, v4 실패 250건의 `reason` 부재는 0자로 보정하지 않았다. 길이는 저장된 문자열의 문자 수다.

| 회차 | 관측 n | ≤50자 | 51–100자 | 101–150자 | >150자 | 중앙값 | p95 | 최대 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v4 | 747 | 334 | 409 | 4 | 0 | 53 | 81 | 105 |
| v6 | 997 | 448 | 541 | 8 | 0 | 53 | 89 | 109 |

v4와 v6 모두 검사한 성공 reason이 150자 상한 안에 있다. v4는 prompt v2의 500자 상한이었지만 실제 저장 결과도 최대 105자였고, v6의 prompt v3 결과 최대는 109자였다.

### relevance-score 구간 정합성

| 회차 | 검사 성공 건수 | relevant score 범위 | uncertain score 범위 | not_relevant score 범위 | 위반 건수 |
|---|---:|---:|---:|---:|---:|
| v4 | 747 | 0.65–0.95 | 0.35–0.55 | 0.00–0.20 | 0 |
| v6 | 997 | 0.65–0.95 | 0.35–0.60 | 0.00–0.25 | 0 |

검사한 성공 결과에서는 score 또는 relevance 누락도 없었다. 실패 결과는 relevance-score 쌍이 없으므로 정합성 위반으로 세지 않고 실패 상태로 남겼다.

## v4→v6 변화의 교란과 해석 경계

v4에서 v6으로 갈 때 다음 네 변수가 동시에 바뀌었다.

1. capabilities: 6개→10개
2. prompt: v2→v3
3. 최대 출력 토큰: 4,096→8,192
4. timeout: 120초→300초

그러므로 공통 747건에서 관찰된 relevance 이동이 신규 capability 때문인지, prompt 원칙 때문인지, 생성 예산 때문인지, 또는 실행 완료 여부와 결합된 효과인지 단일 원인으로 귀속할 수 없다. v5→v6은 capabilities·prompt·최대 출력 토큰이 같고 timeout만 120초→300초로 바뀐 중간 비교이며, v5의 400건 timeout과 v6의 전건 성공은 기술적 coverage 차이가 timeout 관측과 일치함을 보여준다. 이것도 relevance 품질 차이를 입증하는 실험은 아니다.

## 현재 결론의 한계와 후속 검증

- 사람 정답 라벨과 adjudication 결과가 없으므로 recall, precision, 중요 누락, 품질 우승을 계산하지 않았다.
- `relevant`·`uncertain` 분포의 증가는 의도한 방향과 일치하는 관찰일 뿐 품질 개선으로 단정하지 않는다.
- v4 실패 250건은 모델 판정을 갖지 않으므로 v4 전체 분포를 완전한 relevance 분포로 해석할 수 없다.
- 신규 capability 인용은 모델 reason의 문자열 관측이다. capability의 실제 회사 역량 적합성, 자격, 실적을 검증한 결과가 아니다.
- 운영 활성화 여부는 이 보고서에서 결정하지 않는다. 동일 동결 표본에 사람 정답을 부여하고, 이후에는 한 번에 한 변수만 바꾸는 별도 실험으로 품질·지연·검토량을 함께 검증해야 한다.

## 보존 증거

| artifact | SHA-256 |
|---|---|
| `data/experiments/order-plan-screening/20260824-20260826-interim-v4/population.json` | `6e8d5f275ac45c3cbc59cb7c543f7945c8851f6dba720ae8f14bd4259b2cc1d6` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v4/results/qwen.json` | `1c48cda8e60d708769264d0b94d607e932421845003fcb7a4fe5539935f859ef` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v5/population.json` | `d66c96ff926f8e090bf52244d021c04286d09d76efd36ca8f42de13b6b23c9b4` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v5/results/qwen.json` | `038e93e7076d27f30ebdaeec755260401f1bd346b73f3f2082e95c5f42de7aad` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v6/population.json` | `0fcab97e7a74d752954d985976badf0cf65eb7e8d675e814ee468273724a7ed6` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v6/results/qwen.json` | `3c7da300b960e001320e433111029215561acb865365fb5ee5517ae0e55249ed` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v6/results/tfidf.json` | `48ec7d6c71f00e25c0869176d371d5b4f41f458b506eb8980b16570dda4a60db` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v6/results/bge_m3_dense.json` | `7ef32af89dae4136de0495ffa669cd9d7728f81881af07a067037224a7cb5c5b` |
| approved prompt v2 | `593e3fdb97d1c4bf325d831eea7494908e4510e0cee999e349db224a2b5cf4d1` |
| approved prompt v3 | `639f7332e1120a41b2e8d8306126f121ae1ed37068a81b1687aff9ce66ab9d12` |

분석 수치는 population title과 각 `results/*.json`의 plan_id를 조인해 계산했다. 실패 항목은 0으로 대체하지 않고 상태와 누락으로 보존했다.

## 사람 정답 기반 precision·recall

### 정답 구성과 처리 방침

`human-gold-full-population.tsv`의 997건을 전수 사용했다. `human_relevance`는 `관련` 90건, `비관련` 901건, `판단보류` 6건이며, 전수 검토자의 표식은 모두 `interactive-user`인 1인이다. 양성은 `관련` 90건으로 정의하고, `판단보류` 6건은 음성으로 처리했다. 따라서 모델의 `uncertain` 예측도 사람 정답의 `관련`과 일치할 때만 TP로 세었다.

Top-50 precision·recall은 각 결과의 `selected=true` 50건을 대상으로 전체 양성 90건을 분모로 삼았다. 분류 자체 품질은 성공 결과만 판정 가능한 풀로 사용했다. v4는 250건 실패 중 사람 양성 15건이 포함되어 판정가능 양성이 75건이고, v6는 997건 전수 성공으로 판정가능 양성이 90건이다. 실패 건은 `비관련`으로 보정하지 않았다.

### Top-50 대비 정답

| 방법 | TP | precision | recall | 비고 |
|---|---:|---:|---:|---|
| v6 qwen | 39 | 78.0% | 43.3% | 997건 전수 성공 |
| v6 tfidf | 34 | 68.0% | 37.8% | |
| v6 bge_m3_dense | 28 | 56.0% | 31.1% | |
| v4 qwen | 47 | 94.0% | 52.2% | 실패 250건, 풀 747건 |

Top-50은 고정 예산이므로 전체 양성 90건에 대한 recall 상한은 `50/90 = 55.6%`다. v4 Qwen의 Top-50 TP는 47건이며, 실패를 제외한 가용 양성 75건을 분모로 하면 가용 양성 대비 recall은 `47/75 = 62.7%`다. 후자는 v6의 전체 모집단 recall과 같은 조건의 지표가 아니다.

### 분류 자체 품질

`relevance='relevant'`를 양성 예측으로 계산한 결과다. `relevant+uncertain` 열은 두 판정을 모두 후보로 세되, 사람 `판단보류`는 앞서 정한 방침대로 음성으로 처리했다.

| 회차 | 판정가능 양성 | `relevant` 예측 | TP | precision | recall | `relevant+uncertain` 예측 | TP | precision | recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v4 | 75 | 99 | 71 | 71.7% | 94.7% | 187 | 75 | 40.1% | 100.0% |
| v6 | 90 | 210 | 88 | 41.9% | 97.8% | 475 | 90 | 18.9% | 100.0% |

v4의 `relevant` recall 94.7%와 `relevant+uncertain` recall 100.0%는 250건 실패를 제외한 판정가능 양성 기준이다. 전체 모집단의 실패를 자동 음성으로 간주한 수치가 아니다.

### recall@k 공통 성공 풀

v4·v6 모두 성공한 plan_id 747건을 고정 비교 풀로 삼았고, 그 안의 사람 양성은 75건이다. 각 방법의 저장된 `rank` 순서를 이 747건으로 제한한 뒤 앞에서부터 k건을 취해 recall을 계산했다.

| k | v4 | v6 |
|---:|---:|---:|
| 25 | 33.3% | 29.3% |
| 50 | 62.7% | 56.0% |
| 75 | 86.7% | 76.0% |
| 100 | 94.7% | 85.3% |
| 150 | 100.0% | 98.7% |
| 300 | 100.0% | 100.0% |

재계산 기준으로 v4가 k=25·50·75·100·150에서 v6보다 높고, k=300에서는 두 회차가 모두 100.0%로 같다. 제시된 사전 수치와 대조하면 v4의 k=25·k=50, v6의 k=25가 각각 다르며, 해당 항목은 저장된 `rank`와 사람 정답으로 재계산한 위 수치를 사용했다. v4 k=50은 Top-50 TP 47건과도 일치해야 하므로 75건 분모에서 62.7%가 된다.

### v6 capability별 정밀도

v6에서 `relevance='relevant'`인 결과의 `reason`에 capability ID가 포함된 경우만 세고, 그중 사람 `관련`을 정답으로 세었다. 한 `reason`에 여러 ID가 있으면 각 ID에 각각 포함되므로 행은 서로 배타적이지 않다.

| capability | relevant 인용 | 그중 정답 | precision | 구분 |
|---|---:|---:|---:|---|
| `ai-data-analytics` | 61 | 29 | 47.5% | 기존 |
| `data-platform-integration` | 41 | 36 | 87.8% | 기존 |
| `blockchain-did-credentials` | 2 | 2 | 100.0% | 기존 |
| `public-si-lifecycle` | 37 | 26 | 70.3% | 기존 |
| `saas-cloud` | 10 | 7 | 70.0% | 기존 |
| `ontology-knowledge-graph` | 5 | 5 | 100.0% | 기존 |
| `domain-disaster-fire-safety` | 14 | 0 | 0.0% | 신규 |
| `domain-healthcare-data` | 3 | 1 | 33.3% | 신규 |
| `domain-education-credentials` | 19 | 3 | 15.8% | 신규 |
| `delivery-research-poc` | 66 | 5 | 7.6% | 신규 |

신규 4개 합계는 relevant 인용 102건 중 정답 9건으로 precision 8.8%다.

### 핵심 해석

이번 사람 정답 비교에서 capability 6개→10개 확장과 prompt v3 적용이 함께 들어간 v6의 Top-50 순위 품질은 v4보다 낮았다. Qwen `relevant` 예측은 99건에서 210건으로 늘었지만 참 양성은 71건에서 88건 증가하는 데 그쳐 precision은 71.7%에서 41.9%로 하락했다. Top-50에서도 v4 Qwen은 precision 94.0%, recall 52.2%였고 v6 Qwen은 precision 78.0%, recall 43.3%였다.

recall@k는 포화되는 k=300에서 두 회차가 같아지는 것을 제외하면 모든 k에서 v4가 우위였다. 신규 capability 4개는 relevant 인용 102건 중 정답 9건에 그쳐 희석의 주된 경로로 보이며, 특히 `delivery-research-poc`(7.6%)와 `domain-disaster-fire-safety`(0.0%)의 정밀도가 낮았다. 다만 capability별 정밀도는 모델 `reason`의 ID 인용과 사람 정답의 교차 관측이지, capability 자체의 역량 검증은 아니다.

### 참조 실행을 지표에서 제외한 이유

참조 실행 `20260824-20260826-sol200-luna797-xhigh-b100-reference-v1/results/mixed-sol-luna-xhigh.json`은 스키마가 달라 항목별 `rank`와 `selected` 필드가 없고, `selection.status`도 `not_computed`다. 따라서 이 결과에서 Top-50 지표를 직접 산출하지 않았다. 또한 정답 TSV의 `source_model`은 `gpt-5.6-luna` 797건과 `gpt-5.6-sol` 200건이며, 사람이 이 모델들의 출력을 출발점으로 검토했다. 같은 정답으로 참조 실행을 평가하면 순환 평가가 되므로 해당 실행의 precision·recall도 산출하지 않았다.

### 한계

- 표본은 2026-08-24~26 3일치 997건이고 양성은 90건 하나뿐이다. 통계적 검정력이 낮으며 다른 기간으로 일반화되지 않는다.
- `domain-disaster-fire-safety`가 0%인 것은 이 표본에 소방·재난 정보화 발주가 없고 소방공사 설계용역만 있었기 때문일 수 있다. 회사 실적상 해당 도메인 역량은 존재하므로 이 수치만으로 역량 자체를 부정하지 않는다.
- v4→v6는 capabilities, prompt, `max_output_tokens`, timeout 4가지가 함께 바뀌었다. 따라서 precision 하락을 특정 변경 하나에 귀속할 수 없다. 다만 capability별 정밀도표는 신규 축이 관여했음을 시사한다.
- 정답은 1인 검토이며 교차검증과 불일치율이 없다.
- v4는 250건 실패로 Top-50 경쟁 풀이 747건이고 v6은 997건이라 조건이 다르다. 이 비대칭이 v4에 유리하게 작용했을 수 있다.

### 후속 검증 제안

다음 회차에서는 `delivery-research-poc`와 `domain-education-credentials`의 summary를 좁히거나 제거한 조건을 재실행해 희석 경로를 확인하는 방안을 제안한다. 또한 capabilities만 6개로 되돌리고 prompt v3는 유지하는 회차를 별도로 두어 두 변경을 분리해 검증하는 방안을 제안한다. 이는 후속 실험 제안이며, 이번 결과만으로 운영 활성화나 최종 방법을 선정하지 않는다.

이번 절에는 ColBERT와 Luna 결과가 포함되어 있지 않으므로 이 결과로 두 방법의 성능을 판단하지 않는다. 사람 정답 기반 지표가 추가되었더라도 운영 활성화 및 최종 방법 선정의 결론은 내리지 않는다.
