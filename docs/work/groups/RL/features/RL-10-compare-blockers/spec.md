# 명세 — 결정적 대조 규칙 v2 (상주 장소·제외 분야 차단)

## 큰 틀 문서와의 관계

RL-03 카드 판정의 결정적 대조(`card_compare`)에 규칙 집합 `card-compare-v2`를 더한다. 정책 `analysis-policy-luna-rl-v12`만 v2를 고르고 v1~v11은 지금 규칙(`card-compare-v1`)을 그대로 쓴다. 업무 규칙은 [business-rules.md "RL 자동 분석과 판정 상태"](../../../../../business-rules.md#rl-자동-분석과-판정-상태-rl-03-2026-10-17), 계약은 [contracts/rl.md](../../../../../contracts/rl.md#카드-기반-참여-판정-rl-03-2026-10-17)의 "대조 규칙 v2" 항목과 회사 근거 노드 표다. 결과는 계속 `unmeasured_reference`다.

이 기능은 RL-03의 개정이 아니라 새 기능으로 둔다. 설계고도화안 D-1이 "새 기능 문서·정책 버전"을 요구했고, RL-03은 `validating`(12/12)·RL-05 reject 기록이 묶여 있어 그 계보를 다시 열지 않는다. RL-05 STEP-009가 정책 v11을 RL-03 코드에 더한 방식과 같이, 코드는 RL-03 모듈을 고치되 기록은 이 기능이 소유한다.

## 규칙 (`card-compare-v2`)

v1의 모든 규칙 위에 아래만 더한다. 모델 호출은 없고 회사 값은 아래 허용 경로로만 읽는다.

### 상주 장소 (결정 E3)

- **대상.** 인용(`quote`)에 상주 앵커가 있는 제약(`비상주` 제외). `staff:onsite`·`kind=text`로 연결된 제약은 이 비교가 결과다. 다른 제약(인원 수, 앵커가 둘 이상이라 연결되지 않은 text 등)은 이 비교가 `gap`일 때만 그 결과를 바꾼다.
- **필요 지역.** 인용이 든 원문 블록에서 인용과 겹치는 절(줄바꿈·`○`·`※`·`;`·문장 끝·` - `·`1)`/`가)` 경계) 중 상주 앵커가 있는 절의 지명을 시·도로 바꾼다. 다른 절의 지명은 쓰지 않는다. 블록을 모르면 인용 자체가 문맥이다.
- **지명 표.** `web/backend/app/deep_review/policies/card-compare-places-kr-v1.json`(sha256 `03cb66d0…b227`, 코드가 고정, 바뀐 파일은 읽지 않고 `card_compare_invalid`). 17개 시·도의 정식·약칭과 그 아래 시·군·자치구 226개(2026-07-01 인천 개편과 이전 이름 포함)만 담는다. 기관명·건물명은 없다. `원주시청`·`수원시 지정장소`는 이름 뒤가 자유라 잡히고, 왼쪽은 한글이 아니어야 한다(`이동해 시스템` 아님). 접미 없는 시·도(`서울`)는 끝·비한글·조사(`에 의 내 와 과 및 지 권`) 앞에서만, `경기`는 `경기도`로만 잡는다. `…시` 뒤 `키 켜 킨 킬 킴 간`(`상주시켜야`), `…구` 뒤 `간 조 축 현 매 성 입 분 역 속 독`은 지명이 아니다. 두 시·도에 있는 이름(`중구`·`동구`·`서구`·`남구`·`북구`·`강서구`·`고성군`·`광주시`)은 모호해 아무것도 정하지 않는다.
- **결과.**
  - `staff:onsite.region`이 `proposed` → `proposed_fact`, 그 밖의 미확인·null → `unknown_fact`.
  - 상주 절에 지명이 없거나, 모호한 이름만 있는 절이 있으면 → `place_unresolved`(`unknown`).
  - 필요 지역 ⊆ `staff:onsite.region`의 시·도 → `met`(`confirmed_match`).
  - 아니면 `pref:onsite_cap.value.params.onsite_regions`를 읽는다. `proposed` → `proposed_fact`, 미확인·null(회사 근거 v4가 여기) → `unknown_fact`. 값이 표의 이름 하나하나를 `,`·`/`·`·`로 이은 문자열이 아니면(`대구 일대`, `중구`) → `unsupported_comparison`.
  - 필요 지역과 `onsite_regions`의 교집합이 없음 → **`gap`(`confirmed_contradiction`)**, `fact_ids=[staff:onsite, pref:onsite_cap]`(동결 사실에 있는 것만), 두 사실의 confirmed 근거를 인용한다.
  - 일부만 겹침 → `scope_unverified`.
- 역할·범위 어휘(`기술자`·`PM`·`최근` 등)는 장소 비교를 막지 않는다. 장소는 역할과 무관하다. 인원 수 비교의 역할 어휘 규칙(v1)은 그대로다.

### 제외 분야 (결정 E2)

- **대상 사실.** `excl:<kind>`이고 `kind`가 `hardware` 또는 `election`, confirmed `excluded=true`, confirmed `requirement_terms`(비어 있지 않은 문자열 목록)가 있는 것만. `proposed`·`unknown`·용어 없음·키와 kind 불일치는 읽지도 연결하지도 않는다. `design_only`·`staffing_only`는 이름 그대로 사업 단위("단독"·"만")라 요구사항 하나로 판단할 수 없고, `region`·`amount_floor`는 업무 분야가 아니라 제외한다.
- **연결.** 인용에 그 용어(NFKC·공백 제거·대문자)가 있을 때만. 용어는 회사 근거에서만 오고 코드에 별칭이 없다.
- **결과.** 인용과 겹치는 원문 절을 `및`·`그리고`·`,`·`、`로 나눈 부분 모두에 용어가 있으면 **`gap`**(`fact_ids=[excl:…]`), 하나라도 없으면 `exclusion_partial`(`unknown`). 모델이 인용을 줄여도 원문 절 전체로 판단한다. 제외 분야에 닿은 제약은 `met`이 될 수 없다(`exclusion_partial`이 v1 결과를 덮는다). unit 원문에 용어가 있는데 어떤 제약 인용에도 없으면 `incomplete_unit`이다.
- 용어 선택이 과잉 차단의 통제 수단이다. 같은 재생에서 회사 근거 v4의 `keywords`를 그대로 용어로 쓰면 `하드웨어 보안 토큰`(인증 수단 목록)·`정보통신공사업법`(법령 이름)이 `gap`이 됐다([재생 기록](../../../../../validation-runs/20261119-rl10-compare-blockers/README.md) 4절). `requirement_terms`는 짧은 명사가 아니라 그 분야 작업을 가리키는 구로 사람이 정한다.

### 계약 유형과 `gap`의 순서 (결정 E4)

v2에서는 `confirmed_contradiction`이 있으면 요구사항 유형이 `계약`이어도 `gap`이다. `계약` unit은 여전히 `met`이 되지 않고 `contract_unaccepted`도 그대로 붙는다. business-rules의 "`부족`은 confirmed 사실이 요구를 부정할 때만"을 그대로 따르고, "계약 조건은 unknown"은 수락 여부라는 사람의 결정을 대조가 대신하지 않게 하려는 규칙이지 확인된 수행 불가를 숨기는 규칙이 아니다. v1(정책 v11 이하)은 지금처럼 계약 검사가 먼저다.

### reason code

`place_unresolved`·`exclusion_partial`(둘 다 `unknown`)을 더한다. 순서는 `scope_unverified` 다음, `contract_unaccepted` 앞이다. v1 검증기는 이 둘을 거부한다. `bidops.proposal-input.v1` enum도 같은 두 값을 더한다(읽기 소비자 확장, 기존 입력은 그대로 통과).

## 회사 값 (사람 확인 대상)

코드는 아래 구조화 값만 읽고 설명 문장을 해석하지 않는다. 회사 근거 v4에는 둘 다 없다.

| 값 | 모양 | 뜻 | v4 상태 |
|---|---|---|---|
| `pref:onsite_cap.value.params.onsite_regions` | 문자열. 지명 표의 시·도 이름을 `,`로 이은 것(예: `"대구"`, `"대구, 세종"`) | 회사가 상주를 받아들이는 시·도 **전체** 목록 | 없음. 설명 문장 "상주 가능 지역은 대구만"이 있으나 구조화 값이 아니다 |
| `excl:hardware.value.requirement_terms` (`excl:election`도 같음) | 비어 있지 않은 문자열 목록, 각 항목 공백 제거 2자 이상, 정규화 뒤 중복 없음 | 요구사항이 이 용어로만 이루어지면 제외 분야 | 없음. `keywords`는 브리핑 공고 제외용(RL-01)이며 대조는 읽지 않는다 |

`requirement_terms`는 회사 근거 노드 계약의 추가 허용 키다(`company_ontology._DOMAIN_RL_KEYS`, `excluded=true`·`kind ∈ {hardware, election}`일 때만, 아니면 `node_value_invalid`). 기존 파일·그래프 스냅숏 sha는 바뀌지 않는다. 값을 정하는 것은 사람이고 새 회사 근거 버전 import·activate로만 들어간다(이 기능은 값을 만들지 않았다).

## 정책 v12와 버전 (결정 E1)

- `analysis-policy-luna-rl-v12.json`(sha256 `bc2acf84…0d4b`) = v11 바이트에서 `policy_identity`만 바꾼 파일. 지시문·계약·selector·packing·execution이 같아 runner 이미지 변경이 없다. 대조 규칙은 identity로 고른다(`card_analysis.BLOCKER_COMPARE_POLICY_IDENTITIES`). 정책 키 집합은 닫혀 있어(`input_versions._require_card_policy`) 규칙 버전을 파일 안에 적을 수 없다.
- 새 버전이 필요한 근거: 종합만 다시 실행은 저장된 compare 행을 같은 입력으로 다시 계산해 바이트가 같아야 재사용한다(`card_analysis.py:1499-1508`). v11 의미를 바꾸면 저장된 v11 attempt의 재실행이 `resume_source_invalid`가 되고 RL-05 결과 재현도 깨진다. 그래서 v11은 v1 규칙에 고정하고 v11 ↔ v12는 resume 계보가 아니다(`resume_lineage_valid`).
- 새 import 기본 경로(`DEFAULT_RL_ANALYSIS_POLICY_PATH`)는 지금까지의 관례대로 v12다. 선택 행·승인은 DB 행 기준이라 이 기본값이 운영 실행을 바꾸지 않는다. v11 행을 계속 쓰는 환경은 `BIDOPS_RL_ANALYSIS_POLICY_PATH`로 v11 파일을 지정한다(승인 CLI 대조). DB import·활성화·승인은 하지 않았다.

## 결정적 검사의 위치 (D-1 "Luna 호출 앞단")

- 지금 구조: 배치마다 추출(Luna) 직후 대조가 돌고(`card_analysis.py:1551`), 역할 3개·종합(Luna)은 모든 배치 대조 뒤에 돈다(`:1573`). 대조는 역할·종합 호출 **앞**이고 그 성공과 무관하다. 다만 대조 입력은 추출이 만든 제약이라 추출 성공에는 묶여 있다. 격리된 항목은 `extract_rejected` 고정 행이다(결정 B51).
- 추출과도 독립시키려면 동결 원문 블록에서 직접 차단 후보를 계산해 저장해야 하는데, (1) 단계 이름이 DB 제약 `ck_card_analysis_stage_name`(`extract|compare|role|synthesis`, `models.py:2526`)으로 닫혀 있어 새 단계 행은 migration이 필요하고, (2) 차단 조건은 "필수(`mandatory`, 추출 값) ∧ gap" 대조 행으로 계산되므로(결정 B55) 추출 없는 후보를 차단 조건에 넣는 규칙과 종합 계약을 새로 정해야 한다. 재설계라 이번에 하지 않았다.
- 가장 작은 후속: 단계 `precheck`(배치 키) 추가 migration → 첫 추출 호출 전에 동결 unit 블록의 상주 절·제외 용어 절에 같은 `_onsite_location`·`_exclusion_comparison`을 적용해 저장 → 종합 입력·판정 화면에 "결정적 차단 후보"로 보이되 차단 조건 계산(필수 판정)은 사람 확인 또는 별도 결정으로 정한다. 정책 버전·계약 개정이 함께 필요하다.

## 결정과 이유

| ID | 결정 | 대안과 기각 이유 |
|---|---|---|
| E1 | 규칙 집합 v2를 새 정책 v12(identity)로 고른다. v11은 v1 고정 | v11 의미를 조용히 바꾸기: resume 재계산·RL-05 재현이 깨진다. 정책 파일에 규칙 버전 키 추가: 정책 schema가 닫혀 있어 계약 변경이 더 크다 |
| E2 | 제외 분야는 회사 근거의 새 키 `requirement_terms`로만 연결하고 `hardware`·`election`만 허용 | v4 `keywords` 재사용: 뜻이 사업 단위 표식이고 재생에서 법령 이름·인증 수단이 차단됐다. 온톨로지 별칭: 개념 후보·추출 payload까지 바뀌고 `domain` 노드는 그래프 경로 대상이 아니다. 코드 별칭: 강제 게이트 위반 |
| E3 | 상주 장소는 행정구역 표(버전 고정 파일)로만 시·도를 정하고, `gap`은 사람이 확인한 상주 가능 지역 전체 목록(`params.onsite_regions`)과 겹치지 않을 때만 | `staff:onsite.region` 하나로 배타 판단: 그 값은 상주 인력의 소재일 뿐 "그 밖 불가"가 아니다. 설명 문장 해석: 회사 사실 추정. 기관 소재지 표: 이전·분원이 많아 결정적이지 않다 |
| E4 | v2에서는 확인된 모순이 계약 유형보다 먼저 `gap`을 정한다 | 계약 우선 유지: D-2에서 284956 B7의 계약 영역 unit이 모순을 숨겼다 |
| E5 | 결정적 사전 검사(추출 전)는 이번에 하지 않는다 | 단계 행 migration과 차단 조건 규칙 재정의가 필요한 재설계 |

## 테스트 케이스

`web/backend/tests/deep_review/test_card_compare_blockers.py`(각 사례에 v1 결과를 함께 고정):

- 지명 표 고정 sha, 행정구역만 잡음, 동사·보통명사·띄어쓰기·도로명 거부, 모호 이름 → 아무것도 정하지 않음, 바뀐 표 → `card_compare_invalid`.
- 상주: 역할어가 있어도 대구 밖 → v1 `scope_unverified`, v2 `gap`(두 사실 근거 인용) / v4 모양(구조화 값 없음) → `unknown_fact` / 미확인·제안 사실 4조합 → `unknown` / 지명 없음·기관명·모호·`상주시켜야` → `place_unresolved` / 대구 → `met` / 대구+경북 → `scope_unverified` / 형식이 틀린 지역 목록 → `unsupported_comparison` / 같은 절 밖 인용의 지명은 쓰고 다른 절 지명은 쓰지 않음 / 인원 수·앵커 둘 제약도 모순이면 `gap`, 아니면 v1 결과 / 계약 유형도 v2는 `gap`, `met`은 아님.
- 제외: 용어로만 이루어진 요구 → `gap`(근거 인용) / 일부·인용 축소 → `exclusion_partial` / 용어 없음·제안·`design_only`·`excluded=false`·키-kind 불일치 → 연결 없음 / 제외 분야에 닿은 인원 수 제약은 `met` 아님 / 인용되지 않은 용어 → `incomplete_unit`.
- 검증기: 계약 gap과 새 code는 v2에서만 통과, 모르는 규칙 이름 거부.
- 회사 근거 모양: `requirement_terms` 허용·거부 조건.
- 정책: v12 고정 sha·v11과 identity만 다름·식별 집합·resume 계보·import(`tests/app/test_company_luna_policy.py`), mock v12 실행 완료와 저장 compare 행의 v2 재계산 일치·v11 실패 attempt의 v12 resume 거부(`tests/app/test_card_analysis_postgres.py`, PostgreSQL).
- 재생: RL-05 놓친 차단 7개 탐침과 전 블록 과잉 차단 스캔([기록](../../../../../validation-runs/20261119-rl10-compare-blockers/README.md)).

## 증명되지 않은 것

- 종단 판정 품질. 역할·종합은 모델이고, 같은 gold(`gold.v1.json`) 재측정은 Luna 전송이라 사용자 승인 대상이다.
- 실제 추출이 상주 앵커와 장소를 같은 제약·절에 담는지. 탐침은 원문 블록 전체를 인용으로 쓴 이상적 제약이다. 놓친 상주 장소 제약이 실제로 어디서 멈췄는지는 `bidops_rla` 제약 단위 행이 있어야 안다(D-2 1절).
- 회사 근거 v4 그대로는 운영 결과가 바뀌지 않는다(상주 `unknown_fact`, 제외 분야 연결 없음).
