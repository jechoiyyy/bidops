---
name: bidops-collect
description: 나라장터 용역 공고와 사전규격을 수집·정규화하여 고재현율 BidOps 검증 표본을 만든다. BidOps 수집, 필터링, 검증 표본 준비에 사용하며, 의미 적합성이나 입찰 참여 판단은 내리지 않는다.
---

# BidOps Collect

나라장터 공식 데이터를 결정적으로 수집하고, 이후 모든 판단을 재현할 수 있을 만큼 원문 근거를 보존한다.

산출물을 만들기 전에 [워크플로 계약](../references/workflow-contract.md)을 읽는다.
후보 탐색을 위해 회사소개서 사업명 참조 파일
`../../docs/reference/company-performance-titles.tsv` (PDF 41–46페이지)도 함께 사용한다.

## 작업 순서

1. 정확한 수집 기간과 출력 디렉터리를 확정한다. 초기 검증에는 `Asia/Seoul` 기준 `2026-08-17`부터 `2026-08-23`까지(양 끝 포함)를 사용한다.
2. 저장소 루트에서 `skills/bidops-collect/scripts/collect_notices.py`를 실행한다. 출력 회차는 새 고유 경로이며 폴더를 미리 만들지 않는다. 이 스크립트는 환경 변수 또는 git-ignore된 `.env` 파일에서 `BIDOPS_G2B_API_KEY`를 읽는다. 이 키를 출력하거나 저장하지 않는다.
3. 수집 건수와 경고를 확인한다. API 원문 페이지는 실행 디렉터리 아래에 보존한다.
4. `scripts/select_validation_sample.py`를 실행해 분석 표본 최대 30건과 감사 표본 10건을 선정한다.
5. 층이 채워지지 않았거나 필드가 누락된 경우 그대로 보고한다. 데이터를 임의로 만들어내거나 채워 넣지 않는다.

```bash
python3 skills/bidops-collect/scripts/collect_notices.py \
  --from-date 2026-08-17 --to-date 2026-08-23 \
  --output-dir data/runs/20260817-20260823

python3 skills/bidops-collect/scripts/select_validation_sample.py \
  data/runs/20260817-20260823/collected-notices.json \
  --output data/runs/20260817-20260823/validation-set.json
```

입찰공고에 1468 업종 표시(`qualification_flags.sw_industry_1468`)를 남기려면 `--tag-bid-sw-industry`를 더한다. 1468 조회가 실패하거나 부분 수집이면 모든 입찰공고 값은 `null`이고 경고와 exit 1이 남으며, `--from-raw`와 함께 주면 보존된 `raw/industry1468-page-NNN.json`으로 다시 계산한다.

탐색 규칙을 바꾸는 데는 API를 새로 호출할 필요가 없다. `--from-raw SOURCE_RAW`는 원본을 읽기만 하고 별도의 새 회차에 검증 복사·정규화한다. 기존 출력 폴더(빈 폴더 포함)·symlink·허용 루트(`data/runs` 기본값) 이탈은 키 확인 전에 거부한다. 부분 수집의 경고/exit 1은 완전한 회차로 적재하지 않는다:

```bash
python3 skills/bidops-collect/scripts/collect_notices.py \
  --from-date 2026-08-17 --to-date 2026-08-23 \
  --from-raw data/runs/20260817-20260823/raw \
  --output-dir data/runs/20260817-20260823-reclassified-001
```

## 필터링 경계

후보 탐색은 서로 독립적인 두 신호의 합집합이다:

1. 정규화된 한국어/영어 핵심 개념 일치.
2. PDF 41–46페이지의 회사 수행실적과 충분히 구체적으로 유사한 사업명.

개념 일치 판정 전에 유니코드 폭, 대소문자, 문장부호, 구분자를 정규화한다. `AI Agent`, `ai-agent`, 전각 변형을 같은 개념으로 취급한다. `온톨로지`/`ontology`, `지식그래프`/`knowledge graph`, `블록체인`/`blockchain` 같은 개념의 한국어/영어 별칭을 유지한다. 짧은 영문 약어는 토큰 경계를 요구해서 `AI`가 `G-Fair`나 `KAIST` 내부에 매칭되지 않게 한다.

각 API 필드는 개별적으로 매칭하고 모든 신호의 출처를 기록한다. 한 필드의 끝부분과 다음 필드의 시작 부분을 이어붙여 개념을 만들어서는 안 된다.

수행실적 유사도는 탐색 신호이지, 신규 공고가 같은 범위를 가진다는 증거가 아니다. 디지털 산출물 맥락을 요구하고, 시스템, 플랫폼, 유지보수, 사업관리 같은 일반 단어만으로 발생한 매칭은 억제한다. 최상위 일치 사업명, 출처 페이지, 유사도 값, 법적 자격 인정 상태를 공고에 보존한다. 이 자격 상태는 항상 `unknown`으로 남는다.

두 신호 중 어느 것도 없는 레코드는 확정 제외 집합이 아니라 감사 표본군에 속한다. 모호한 레코드는 의미 판정을 위해 남겨 둔다. 이번 검증에서는 예산, 지역, 회사 자격, 미확인 부정 키워드로 필터링하지 않는다.

세 개의 동등한 우선순위 축은 `AI/데이터`, `블록체인·DID`, `공공 SI·통합관리`이다.

## 신호 출처

조달 분류 라벨(`pubPrcrmntLrgClsfcNm`, `pubPrcrmntMidClsfcNm`, `pubPrcrmntClsfcNm`)은 발주기관이 모든 용역 공고에 일괄 부여한다. 탐색에는 유용하지만 개별 공고의 범위를 증명하는 근거는 아니다. 판정 단계가 제목에서 나온 개념과 분류 라벨을 다른 무게로 평가할 수 있도록 모든 신호에 `field_kind`를 기록하고, 분류만으로 탐색된 표본 건수를 보고한다.

## 이후 단계가 의존하는 필드

현재 검증에서 필터링에 쓰지 않더라도 다음 API 값은 정규화된 레코드에 보존한다. 이 값들은 판정 단계가 확인 항목으로 다시 물어야 할 질문에 미리 답하며, 설계가 의존하는 생애주기 정보를 담고 있다.

| 필드 | 목적 |
|---|---|
| `rgnLmtBidLocplcJdgmBssNm`, `jntcontrctDutyRgnNm1..3` | 지역 제한과 지역의무공동도급 조건 |
| `pubPrcrmnt*ClsfcNm` | 과업 성격 구분. 첨부 문서 없이도 행사·연구·감리를 분리할 수 있다 |
| `bfSpecRgstNo` | 사전규격에서 본공고로 이어지는 연결 고리 |
| `reNtceYn`, `befBidBbancNo`, `chgDt`, `chgNtceRsn` | 재공고와 정정 이력 추적 |
| `arsltCmptYn`, `pqEvalYn`, `tpEvalYn`, `techAbltEvlRt` | 실적제한경쟁과 기술평가 여부 |

`rgnLmtBidLocplcJdgmBssNm`이 비어 있다는 사실은 지역 제한이 없다는 뜻이 아니다. 값이 없으면 `API 미표기`로 다루고 확인 항목으로 넘긴다.

## 표본 선정

작은 검증 표본을 선정할 때는 분석 레코드를 세 축과 네 번째 층인 `수행실적 유사` 탐색층 사이에서 순환시킨다. 수행실적 유사도만으로 탐색된 표본 건수를 보고한다.

감사 표본은 1차 필터가 놓친 레코드를 찾기 위한 것이므로 무작위로 뽑지 않는다. 세 층을 순환시킨다:

1. `분류 근접`: 조달 분류는 디지털 산출물을 나타내지만 탐색에는 실패한 경우.
2. `실적 유사 근접`: 수행실적 유사도가 채택 임계값 바로 아래인 경우.
3. `무작위`: 그 외 나머지.

무관한 공고 2천여 건에서 균등하게 뽑은 10건으로는 재현율을 측정할 수 없다. 목표를 정한 층 구성이라면 가능하다.
