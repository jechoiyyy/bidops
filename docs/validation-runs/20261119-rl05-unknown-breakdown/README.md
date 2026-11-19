# RL-05 unknown 447개 사유 분해 — 저장 산출물 재생 (모델 호출 없음)

2026-11-19, launch-hardening [설계고도화안](../../1118_launch-hardening/설계고도화안.md) §4 D-2. [RL-05 인수 기록](../2026-10-19-rl/RL-05/README.md)의 실제 분석 10건(정책 v11, 회사 근거 v4)에서 모델 카드 상태 447개가 전부 `unknown`이고 차단 조건 재현율이 0/7이었던 원인을, 저장된 산출물과 현재 제품 함수로 사유 코드·실패 단계별로 나눈다. D-1(결정적 대조가 차단 `gap`을 내게 하는 작업)의 표적을 정하기 위한 기록이다.

- 모델 호출 0회. 운영 web·DB 조회 0회(필요 없었다). 격리 스택 `bidops-local`은 기동하지 않았다.
- 제품 코드·정책·RL-03 대조기·기능 문서·큐는 바꾸지 않았다. 이 기록과 분석 스크립트·출력만 추가했다.
- 문서 원문·회사 값·사람 답 원문은 적지 않는다. 차단 조건은 짧은 의역으로만 적는다. 결과는 `unmeasured_reference` 실행의 진단이며 품질 근거가 아니다.

## 1. 저장 산출물의 위치와 재생 범위

| 산출물 | 위치 | 이 분석에서 |
|---|---|---|
| 실제 결과 export `final/actual.v1.json` | main checkout `.sdlc/local-runtime/rl-evaluation-20261019/` (Git 밖) | 읽음. 문서별 판정, 카드 447개의 종합 `fit_status`, unit 515개(카드 447 + 영역 segment 68)의 **대조 단계 `reason_codes`**(export가 저장값을 그대로 옮김, 재계산 없음 — `export_evaluation.py:766-798`), unit→원문 블록 대응 |
| gold `gold.v1.json`, 채점 `final/score.v1.json`, `final/receipt.json`, `selection.v1.json` | 같은 디렉터리 | 읽음. 차단 조건 7개의 원문 블록·카드 id, 카드 원문 블록(텍스트 포함), 놓친 조건 목록 |
| 회사 근거 `rootlab.source.v4.json`, 온톨로지 `ontology.v2.json` | `~/orca/fixtures/company/rootlab/` | 읽음. 그래프 스냅숏 sha와 온톨로지 canonical sha를 다시 계산해 export의 binding과 대조 |
| 추출 항목·제약별 대조 행(`card_analysis_stage`), 동결 입력(`deep_review_preview.input_snapshot`), 암호화 원 응답 | 격리 DB `bidops_rla` — docker volume `bidops-local_postgres-data` (스택 정지·2026-11-18 종료, volume 보존) | **읽지 않음.** 컨테이너를 띄워야만 읽을 수 있어 지시대로 멈췄다 |
| 운영 백업 `backups/postgres/full/*.dump` | main checkout | 운영 `bidops` DB 백업이며 `bidops_rla`가 아니다 |

재생 범위:

- **447개 전부**에 대해 unit 단위 저장 사유 코드는 정확히 재생했다(저장값 그대로).
- **제약 단위**(어느 제약이 어느 사실·코드로 끝났는지)는 위 DB가 없어 재생하지 못했다. 대신 (1) unit 원문에서 제품 함수로 결정적으로 다시 계산할 수 있는 부분(허용 사실 앵커, 개념 후보, 그래프 경로, 제약과 무관한 개념 사유)을 재구성해 저장 코드와 대조했고, (2) 차단 조건 원문 블록을 그대로 인용으로 쓴 이상적 제약을 현재 `constraint_comparison`에 넣어 보는 탐침(probe)을 했다.
- 제약 단위 재생에 필요한 것: `bidops_rla`의 `card_analysis_stage`(extract·compare 행)와 `deep_review_preview.input_snapshot`. 해당 volume에 읽기 전용 postgres를 붙이거나 `pg_dump`를 받는 일은 종료된 데모 스택을 다시 다루는 것이라 사용자 승인 대상이다.

## 2. 입력과 digest

| 입력 | sha256 | 확인 |
|---|---|---|
| `final/actual.v1.json` | `e64a66944fc87b4c5b59ead01e55fa7e798bf2cf72fcd3299dd51f1a506abf07` | receipt `actual_sha256`과 같음 |
| `gold.v1.json` | `6c4ca1548c8908a0c358bb03e31bc5ac6a03364e20a425ebee0a78b8e9cd627a` | receipt·score 입력과 같음 |
| `final/score.v1.json` | `c09b020c1f02d442ad7139b23ae8f89cff85fd6fa1ef4c2634c57297ba1120b1` | — |
| `final/receipt.json` | `3c64a2094ce17fdd8f978f25fcd4b8e87ce33f413610fde1e32c5ad455134ca8` | — |
| `selection.v1.json` | `f7cb743a4688ee6abe7f2f4f14c9f1fd6a9cb3975d21beb0341b74d7869b8ac6` | receipt와 같음 |
| `rootlab.source.v4.json` | `78f525bcae479e50943e38616427f5f9852500a9164d5dd81a815ee8fd221af9` | 그래프 스냅숏 `402a9e06…4fef` = export `company_sha256` |
| `ontology.v2.json` | `7e6f4d8a51a65907460f60aedb20dd96a15ddaa0e65ff707a0dd7aa58f7f96d7` (파일) | canonical `4d0f95c2…7a15` = export `ontology_sha256` |
| 정책 v11 파일 | `8dabbbb4…` | RL-05 기록과 같음. `path_limit_per_requirement` 32를 재구성에 사용 |

제품 코드 기준은 이 브랜치의 base `ffe88fa`다. 실행 뒤 `card_compare.py`의 변경은 C25(`3efffdf`, `_atomic_coverage_incomplete`의 절 덮음 판단)뿐이고 이후 대조·앵커·허용 경로·그래프 검색 파일 변경은 없다. 탐침이 지나는 분기는 실행 당시와 같다.

## 3. 실행 명령

```bash
cd <저장소 루트>
/Users/temp/orca/bidops/.venv/bin/python docs/validation-runs/20261119-rl05-unknown-breakdown/rl05_unknown_breakdown.py \
  --eval-dir /Users/temp/orca/bidops/.sdlc/local-runtime/rl-evaluation-20261019 \
  --company-source /Users/temp/orca/fixtures/company/rootlab/rootlab.source.v4.json \
  --ontology /Users/temp/orca/fixtures/company/rootlab/ontology.v2.json \
  > docs/validation-runs/20261119-rl05-unknown-breakdown/breakdown.json
```

- 스크립트 [`rl05_unknown_breakdown.py`](rl05_unknown_breakdown.py): 표준 라이브러리 + `web/backend`의 제품 함수(읽기 전용 import: `fact_anchor_matches`·`resolve_fact_key`·`constraint_comparison`·`_scope_unverified`·`_regions`·`_concept_reasons`·`card_expected_concepts`·`match_concepts`·`search_graph_paths`·`build_graph_snapshot`). 규칙을 다시 구현하지 않는다. 새 의존성 없음.
- 입력 digest가 receipt·binding과 하나라도 다르면 `input_mismatch`로 exit 2.
- 출력 [`breakdown.json`](breakdown.json)(sha256 `76f578a2b88927b75fd82ab50f03021678318c5f7597523cf3fc8982f5d24cbd`)은 id·코드·건수만 담는다. 같은 명령 2회 출력이 바이트 단위로 같았다.

## 4. 분해 결과

### 4.1 실패 단계 (카드 447개, 배타 분류)

저장 `reason_codes`에서 가장 앞 단계 하나로 분류했다. 순서: 추출 격리 → 계약 → 확인 일치 → 사실 도달·판단 불가 → 사실 연결 없음 → 원자 조건 미완.

| 단계 | 판정 근거 코드 | 카드 | 비율 |
|---|---|---:|---:|
| S1 추출 항목 격리 | `extract_rejected` (B51, 대조 안 함) | 39 | 8.7% |
| S2 계약 유형 고정 unknown | `contract_unaccepted` (모델 `type=계약`) | 42 | 9.4% |
| S3 확인 사실과 일치한 제약 있음 | `confirmed_match` + 다른 원자 unknown | 2 | 0.4% |
| S4 회사 사실에 닿았으나 판단 불가 | `unsupported_comparison`(이번 실행은 이것만; `scope_unverified`·`proposed_fact`는 segment에만 있음) | 25 | 5.6% |
| S5 회사 사실 연결 없음 | `unmapped` (+`incomplete_unit`) | 228 | 51.0% |
| S6 원자 조건 미완만 | `incomplete_unit`만 | 111 | 24.8% |
| 합계 | | 447 | |

`confirmed_contradiction`(gap)·`unknown_fact`·`partial_path`는 515 unit 어디에도 없다. 대조 단계가 `gap`을 낸 unit이 0개이므로, 차단 조건 0건은 종합 단계가 아니라 **대조 단계에서 이미 정해졌다**.

### 4.2 사유 코드 (중복 집계)

| 코드 | 카드 447 중 | unit 515 중 | 내는 위치 (`ffe88fa`) |
|---|---:|---:|---|
| `incomplete_unit` | 361 | 418 | `card_compare.py:627-632` (모델 `unknowns`, 원문 원자 누락 판정, 원자 없음) |
| `unmapped` | 280 | 318 | 제약: `card_compare.py:276-278`(`resolve_fact_key` None) / 개념: `card_compare.py:418-421` |
| `contract_unaccepted` | 42 | 54 | `card_compare.py:629-630` |
| `extract_rejected` | 39 | 48 | `card_compare.py:70-76`, 격리 B51 |
| `unsupported_comparison` | 32 | 45 | `card_compare.py:274-275`(operator unknown), `282-283`(kind 불일치), `_confirmed_comparison` 각 분기 |
| `proposed_fact` | 0 | 7 | `card_compare.py:285-286` (`qual:credit_rating` proposed, segment만) |
| `scope_unverified` | 0 | 3 | `card_compare.py:291-292`, `192`, `215`, `242` |
| `confirmed_match` | 2 | 3 | `card_compare.py:184` 등 |

카드 코드 조합 상위: `unmapped + incomplete_unit` 191, `incomplete_unit` 111, `extract_rejected` 39, `unmapped` 37, `unmapped + contract_unaccepted + incomplete_unit` 20, `unmapped + unsupported_comparison + incomplete_unit` 17 (전체는 `breakdown.json` `cards_by_code_combination`).

### 4.3 주제(제약 유형)별

주제는 카드 원문에 대조 allowlist 앵커(`CARD_FACT_ANCHORS`)가 있는지로 정했다(제품 어휘). allowlist에 없는 주제 둘은 **분석용 어휘 표식**(제품 규칙 아님: `실적` / `하드웨어·HW·H/W·전산장비·부품`)으로 셌다. 한 카드가 여러 주제에 들어갈 수 있다.

| 주제 | 카드 | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 회사 사실 주제 없음 | 315 | 24 | 29 | 0 | 19 | 154 | 89 |
| 인력 규모(`staff:total`·`staff:design_publishing`) | 48 | 5 | 3 | 0 | 1 | 32 | 7 |
| [어휘] HW·장비 유지관리 | 40 | 3 | 5 | 1 | 3 | 22 | 6 |
| 상주 인력·장소(`staff:onsite`) | 27 | 4 | 0 | 2 | 0 | 17 | 4 |
| [어휘] 수행 실적 | 25 | 1 | 4 | 0 | 1 | 12 | 7 |
| 자격·인증(`qual:*`, 지점 제외) | 20 | 1 | 2 | 0 | 1 | 12 | 4 |
| 공동수급·하도급 | 16 | 3 | 1 | 1 | 0 | 8 | 3 |
| 사업 금액(`pref:solo_cap`) | 6 | 2 | 0 | 0 | 0 | 3 | 1 |
| 소재지·지역제한(`qual:branch`) | 3 | 1 | 0 | 0 | 0 | 2 | 0 |

- 447개 중 **315개(70%)는 회사 사실 주제가 원문에 없다**(기능·데이터·보안 등). 이들의 `unknown`은 "회사 사실 대조 대상 아님"에 가깝고, gap을 놓친 원인과는 무관하다. D-1의 효과는 447 전체가 아니라 회사 사실 주제 카드에서 재야 한다.
- 원문에 allowlist 앵커가 있는 카드는 95개다. 그중 58개가 S5(사실 연결 없음)다. 앵커가 원문에 있는데 대조가 그 사실에 닿지 못한 것은, 모델 제약의 인용에 앵커가 없거나(추출), 인용 하나에 앵커가 둘 이상이라 연결을 거부했거나(`card_analysis.py:384-388`), 앵커가 우연히 들어간 경우(예: `디자인`은 UI 디자인 문장에도 걸린다)다. 앵커 2개 이상인 블록이 있는 카드는 그 58개 중 6개였다. 나머지 52개의 구분은 제약 단위 행이 없어 확인하지 못했다.
- "인력 규모" 48개는 대부분 넓은 앵커 `디자인`에서 온다. 수치를 인력 요건 수로 읽으면 안 된다.

### 4.4 원문 요구사항 ID 접두별

| 접두 | 카드 | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---:|---:|---:|---:|---:|---:|---:|
| SFR | 68 | 2 | 0 | 0 | 1 | 30 | 35 |
| COR | 64 | 8 | 30 | 0 | 1 | 20 | 5 |
| PMR | 53 | 4 | 9 | 0 | 6 | 18 | 16 |
| SER | 53 | 6 | 0 | 0 | 5 | 31 | 11 |
| DAR | 38 | 3 | 0 | 0 | 0 | 28 | 7 |
| PSR | 31 | 4 | 2 | 0 | 2 | 17 | 6 |
| QUR | 26 | 1 | 0 | 1 | 1 | 12 | 11 |
| MAR | 20 | 1 | 1 | 0 | 0 | 14 | 4 |
| PER | 15 | 1 | 0 | 0 | 2 | 10 | 2 |
| TER | 15 | 1 | 0 | 0 | 1 | 5 | 8 |
| WEB | 14 | 1 | 0 | 0 | 5 | 8 | 0 |
| MPR | 13 | 0 | 0 | 0 | 1 | 12 | 0 |
| SIR | 12 | 6 | 0 | 0 | 0 | 6 | 0 |
| MHR | 7 | 1 | 0 | 1 | 0 | 5 | 0 |
| CSR·INR·OPR·ECR | 18 | 0 | 0 | 0 | 0 | 12 | 6 |

계약 고정(S2) 42개 중 30개가 COR(제약사항) 카드다. 모델이 제약사항 카드를 `계약` 유형으로 분류하면 대조 결과와 상관없이 unknown이 된다(4.7·6절 a3).

### 4.5 공고별

| document_id | 카드 | gold 판정 | 모델 판정 | 차단(gold/놓침) | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| R26BD00283840 | 38 | 진행 어려움 | 조건부 진행 | 1/1 | 5 | 7 | 1 | 5 | 19 | 1 |
| R26BD00283874 | 59 | 조건부 진행 | 조건부 진행 | 0/0 | 8 | 7 | 0 | 2 | 27 | 15 |
| R26BD00283915 | 68 | 조건부 진행 | 조건부 진행 | 0/0 | 1 | 2 | 0 | 2 | 24 | 39 |
| R26BD00284019 | 37 | 진행 어려움 | 판단 불가 | 1/1 | 2 | 2 | 0 | 1 | 24 | 8 |
| R26BD00284080 | 46 | 진행 어려움 | 조건부 진행 | 1/1 | 5 | 2 | 1 | 1 | 32 | 5 |
| R26BD00284697 | 58 | 조건부 진행 | 조건부 진행 | 0/0 | 12 | 1 | 0 | 9 | 32 | 4 |
| R26BD00284717 | 46 | 조건부 진행 | 판단 불가 | 0/0 | 2 | 9 | 0 | 1 | 25 | 9 |
| R26BD00284827 | 23 | 진행 어려움 | 조건부 진행 | 1/1 | 2 | 5 | 0 | 2 | 8 | 6 |
| R26BD00284941 | 46 | 조건부 진행 | 판단 불가 | 1/1 | 1 | 3 | 0 | 1 | 27 | 14 |
| R26BD00284956 | 26 | 진행 어려움 | 판단 불가 | 2/2 | 1 | 4 | 0 | 1 | 10 | 10 |

판정이 맞은 3건(283874·283915·284697)은 gold도 "조건부 진행"이고 차단 조건이 없는 건이다. 차단 조건이 있는 6건은 모두 틀렸다.

### 4.6 `unmapped`의 출처 (격리 아닌 unit 467개)

| 출처 | unit | 근거 |
|---|---:|---|
| 개념 후보가 `unmapped`를 냄(재구성으로 예측) | 248 | 원문 개념(`홈페이지` 103, `DB` 78, `장애대응` 45, `개인정보보호` 30, …)에 회사 그래프의 허용 사실로 가는 direct 경로가 없다 |
| 개념으로 설명 안 됨 → 제약의 `resolve_fact_key`가 None | 70 | 인용에 허용 앵커가 없거나 둘 이상 (`card_analysis.py:384-388`) |

개념 `unmapped`는 met을 막을 뿐 gap을 막지는 않는다(gap은 제약 하나의 `confirmed_contradiction`만 있으면 된다 — `card_compare.py:494-495`). gap 0의 직접 원인이 아니다.

### 4.7 재구성의 일관성

- 개념 사유 재구성은 격리 아닌 unit 467개 중 **457개가 저장 코드와 모순 없다**. 10개는 재구성이 `unmapped`를 예측했는데 저장 코드에 없다. 10개 모두 R26BD00284019 한 건에 몰려 있어 그 문서의 동결 unit 블록이 gold 카드 블록과 다를 가능성이 있으나, 동결 입력을 읽지 못해 확인하지 못했다.
- `partial_path` 예측 0 = 저장 0(회사 source v4에 `supports_capability` 관계가 없다).
- 개념 후보 표현 불가(`company_input_invalid`) 0건.

## 5. 놓친 차단 조건 7개 추적

| 공고·조건 | 요구(의역) | 회사 확인 사실 | 덮은 unit / 어떤 unit에도 없는 원문 블록 | 저장 코드(덮은 카드) | 결정 단계 |
|---|---|---|---|---|---|
| 283840 B6 | 원주시청 내 기술인력 상주 | `staff:onsite`·`pref:onsite_cap` confirmed | MHR-2·QUR-2 / 문단 2 | MHR-2 `unmapped, incomplete_unit`; QUR-2 `unmapped, incomplete_unit, confirmed_match` | a1 |
| 284019 B6 | 발주자 지정 장소에 2명 이상 상주 | 같음 | PMR-1·MAR-6 / 표 셀 2 | 둘 다 `unmapped, incomplete_unit` | a1, a4 |
| 284080 B5 | 수원시청 내 1명 상주 | 같음 | MHR-1 / 문단 2 | `unmapped, incomplete_unit, confirmed_match` | a1, a4 |
| 284941 B6 | 수원시 지정장소 상주 | 같음 | MHR-2 / 문단 3 | `unmapped, incomplete_unit` | a1 |
| 284956 B7 | 강원특별자치도 지정 장소에 2명 이상 상주 | 같음 | PMR-4·MAR-2·segment(계약) / 문단 2 | 카드 둘 `unmapped, incomplete_unit`; segment `unmapped, unsupported_comparison, contract_unaccepted, incomplete_unit` | a1, a3 |
| 284827 B9 | 사무기기 HW 유지관리·부품·예비장비 (제외 분야 HW) | `excl:hardware` confirmed | COR-1·MAR-2 / 없음 | COR-1 `unmapped, unsupported_comparison, incomplete_unit`; MAR-2 `unmapped, incomplete_unit` | a2 |
| 284956 B9 | 보안·네트워크 장비 HW 유지관리 (제외 분야 HW) | 같음 | MAR-2 / 없음 | `unmapped, incomplete_unit` | a2 |

공통: 7개 조건 모두 덮는 unit이 하나 이상 있었다(원문 선택이 유일 원인인 경우 없음). 다만 5개 조건은 gold가 든 원문 블록 일부(합계 11개)가 `card-sections-v4` 선택 영역 밖이라 모델에 가지 않았다.

**실제 실행에서 멈춘 곳(저장 코드).** 덮은 카드 어디에도 `staff:onsite`에 대한 사실 단계 사유(`unsupported_comparison`·`scope_unverified`·`confirmed_contradiction`)가 없다. 있는 것은 두 카드의 `confirmed_match`뿐이고, 탐침상 인원 수 제약이 회사 상주 가능 인원 이하라 충족된 것으로 보인다(제약 단위 행이 없어 단정하지 않음). 즉 상주 **장소** 제약은 대조에서 사실에 닿지 않았다 — 추출이 `상주`를 인용에 담지 않았거나, 인용에 앵커가 여럿이었거나, 제약을 내지 않았다. 이 셋의 구분은 제약 단위 행이 필요하다.

**이상적 추출이었어도 멈추는 곳(탐침).** 차단 조건 원문 블록을 인용 그대로 쓴 제약을 현재 `constraint_comparison`에 넣었다. 7개 조건의 탐침 55건(284956 MAR-2 블록은 B7·B9에 중복 포함) 중 `gap`은 0건이다.

| 탐침 결과 | 건 | 멈춘 코드 |
|---|---:|---|
| `staff:onsite` text → `unsupported_comparison` | 9 | `card_compare.py:189-191` — 인용·값에서 시·도 이름을 못 찾음(`원주시청`·`수원시청`·`지정 장소`). `_REGIONS`는 17개 시·도만 안다(`108-114`) |
| `staff:onsite` text → `scope_unverified`(역할·범위 어휘 규칙) | 6 | `card_compare.py:291-292` → `140-146` — 인용에 `기술자` 등 역할어가 있으면 지역 비교 전에 멈춤 |
| `staff:onsite` text → `scope_unverified`(지역 불일치) | 1 | `card_compare.py:192` — 284956 문단 2-88은 `강원`을 찾았으나 회사 상주 지역에 포함되지 않으면 `gap`이 아니라 `scope_unverified`. **상주 지역 분기에는 gap 경로가 없다** |
| `staff:onsite` count → `confirmed_match` | 5 | `card_compare.py:172-184` — 요구 인원 ≤ 회사 상주 가능 인원 |
| `staff:onsite` count → `scope_unverified`(역할어) | 4 | `card_compare.py:291-292` |
| 앵커 없음·앵커 여럿 → `unmapped` | 30 | `card_compare.py:276-278` ← `card_analysis.py:384-388`. 상주 블록 중 `공동수급`·`디자인`과 같이 든 셀(284019 표 25 r3, 284080 문단 1-316·MHR-1 r4, 283840 인원 수)과 HW 블록 전부 |

**HW 제외 분야(2개)에 gap 경로가 없는 이유.**

1. 대조 allowlist에 `excl:*`가 없다(`company_analysis_input.py:454-477`) → HW 문장 제약은 앵커가 없어 `unmapped`(`card_compare.py:276-278`).
2. 개념 경로도 막혀 있다: `excl:hardware`의 개념 `rl.domain.09`는 label이 39자 문장이고 별칭이 0개라 `match_concepts`(label/alias 부분 문자열, `company_knowledge_retrieval.py:169-190`)에 원문이 걸리지 않는다. 걸려도 `domain` 노드는 direct·partial 경로의 대상이 아니다(`company_knowledge_retrieval.py:440-450`) → `_concept_reasons`는 `unmapped`(`card_compare.py:418-421`).
3. 그런데 회사 근거 v4의 `excl:hardware`는 confirmed이고 value에 `keywords` 목록이 있다. 대조가 이 값을 읽지 않을 뿐이다.

**gold 카드 상태가 unknown이 아닌 16개(채점 표본 100 중).** gap 11개(상주 8, HW 2, 284697 WEB-12 1)와 met 5개다. met 5개 중 4개는 S6(`incomplete_unit`만)이고 1개는 S2(계약)다. gap 11개는 S5 7·S3 2(상주 인원 수 일치)·S4 2(284697 WEB-12, 284827 COR-1)다.

## 6. D-1이 겨냥할 원인

놓친 차단 7개와 관련 카드 수로 순위를 매겼다. "설명"은 그 원인이 고쳐지지 않으면 결과가 바뀌지 않는다는 뜻이며, 고치면 맞힌다는 뜻이 아니다(역할·종합 단계는 모델이다).

### (a) 모델 호출 없이 고칠 수 있는 결정적 대조 공백

| 순위 | 원인 | 놓친 차단 | 관련 카드 | 코드 |
|---|---|---:|---|---|
| a1 | 상주 **장소** 대조가 gap을 낼 수 없다: 시·도 17개만 인식(시·군·구·기관명 없음), 다른 지역이면 `scope_unverified`, 역할어가 있으면 지역 비교 전 `scope_unverified`. 회사의 "상주 가능 지역 한정" 사실은 `pref:onsite_cap`의 설명 문장에만 있고 구조화 값(`params`)에는 인원 수만 있으며, `pref:onsite_cap`은 allowlist 밖이다 | 5/7 | 상주 주제 27, gold gap 8 | `card_compare.py:108-114`·`185-192`·`140-146`·`291-292`, `company_analysis_input.py:454-477` |
| a2 | 제외 분야(`excl:*`)가 대조에 없다: allowlist 없음, `domain` 노드는 경로 대상 아님, 개념 label이 문장형·별칭 0. confirmed `keywords`는 있으나 읽지 않음 | 2/7 | [어휘] HW 40(상한 아님·어휘 표식), gold gap 2 | `company_analysis_input.py:454-477`, `company_knowledge_retrieval.py:440-450`, `card_compare.py:418-421` |
| a3 | `계약` 유형이면 모순이 있어도 unknown: `_expected_fit`이 계약 검사를 gap 검사보다 먼저 한다 | 1/7(284956 B7의 segment) | S2 42(COR 30) | `card_compare.py:492-495` |
| a4 | 인용 하나에 앵커가 둘 이상이면 연결 거부. `디자인`처럼 넓은 앵커가 `상주`와 겹쳐 상주 제약을 `unmapped`로 만든다 | 2/7(284019·284080, 같은 원인 a1과 겹침) | 앵커 카드 95 중 13 | `card_analysis.py:299-314`·`384-388` |
| a5 | 값 경로 불일치(이번 실행에서는 미발현): 직접생산 품명은 `qual:direct_production:items`, 정보보호 인증 종류는 `qual:infosec_cert:kind`에 confirmed로 있으나 대조는 부모 노드의 null `detail`을 읽어 `unknown_fact`가 된다 | 0/7 | 0(이번 실행에서 이 경로에 닿은 제약 없음) | `company_analysis_input.py:461-469`, `card_compare.py:206-228` |

a1·a2의 회사 쪽 값은 이미 confirmed다. 다만 a1을 결정적으로 쓰려면 `pref:onsite_cap` 설명 문장의 지역 한정을 구조화 값으로 옮긴 새 회사 근거 버전이 필요하다. 이것은 새 사실이 아니라 기존 confirmed 사실의 표현 변경이지만, 설명 문장을 "그 지역 외 상주 불가"로 읽는 해석은 사람 확인을 받아야 한다. `excl:region`의 `keywords`와 `excluded` 값의 뜻(허용 지역인지 제외 지역인지)도 문장만으로 분명하지 않아 같은 확인 대상이다.

### (b) 회사 사실 부재·미확인 (인터뷰 필요, 코드로 해결 불가)

- 놓친 차단 7개 중 **0개**. 관련 회사 사실(`staff:onsite`·`pref:onsite_cap`·`excl:hardware`)은 모두 confirmed다.
- 저장 코드에서 이 부류는 `proposed_fact` 7 unit(전부 segment, `qual:credit_rating` proposed)뿐이고 `unknown_fact`는 0이다.
- D-1 뒤 대조가 더 많은 사실에 닿으면 드러날 unknown 노드: `qual:*:valid_until`류 유효기간, `staff:grade_distribution`(기술 등급 분포), `staff:dispatch_partner`, `qual:gs_certification`, `qual:startup_certificate`, `pref:margin`, 미확인 실적 3건. 이들을 코드에서 채우거나 추정하지 않는다.

### (c) 추출·모델 출력 문제

| 원인 | 규모 | 놓친 차단과의 관계 |
|---|---|---|
| 추출 항목 격리(`extract_rejected`) | 카드 39(8.7%) | 7개 조건의 덮은 unit 중 격리는 없다 |
| 원자 조건 미완(`incomplete_unit`) | 카드 361 | met을 막는다. gap은 막지 않는다(`card_compare.py:494-495`가 먼저) |
| 원문에 앵커가 있는데 사실에 닿지 못함(S5, 앵커 다중 블록 없음) | 카드 52 | 상주 장소 제약이 사실에 닿지 않은 것이 여기에 해당한다. 그러나 탐침상 닿았어도 a1에서 멈추므로 7개 결과를 결정하지 않았다 |
| 제약 `unmapped`(개념으로 설명 안 됨) | unit 70 | a4와 추출 누락이 섞여 있어 제약 단위 행 없이는 나눌 수 없다 |
| 모델의 `계약` 유형 분류 | 카드 42 | a3과 결합해 gap을 억제할 수 있다 |

### 순서 제안

1. a1(상주 장소)과 a2(제외 분야)를 한 기능으로: allowlist·값 경로·규칙(충돌 시 `gap`)과 그 규칙이 읽을 회사 값의 구조화를 함께 한다. 이 둘이 놓친 차단 7개 전부를 설명한다.
2. a3(계약 우선순위)·a4(넓은 앵커·다중 앵커)는 a1·a2의 gap이 실제로 나오게 하는 조건이라 같은 변경에서 다룬다.
3. (c) 추출 쪽은 D-1의 결정적 검사 결과를 본 뒤 판단한다. 위치를 확정하려면 `bidops_rla`의 제약 단위 행이 필요하다.

## 7. 수정이 필요한 것 (이번에 고치지 않음)

- `card_compare._confirmed_comparison`의 상주 지역 분기(`185-192`)·`qual:branch` 비본점 분기(`242`)는 gap을 낼 수 없다. 시·군·구·기관 → 시·도 매핑이 없다(`_REGIONS`).
- 지역 탐지는 카드 전체가 아니라 상주 절 안에서만 해야 한다. 예: 284019 MAR-6은 카드 원문에 다른 맥락의 `광주`(기관 소재지 괄호)가 있어 카드 전체 `_regions`가 `광주`를 돌려준다.
- `CARD_COMPARE_FACT_PATHS`에 `excl:*`·`pref:onsite_cap` 없음. 직접생산 품명·정보보호 인증 종류는 부모 노드의 null 경로를 읽는다(a5).
- 온톨로지 `rl.domain.09~14`·`rl.capability.03` label이 문장형이고 별칭이 없어 원문 일치가 사실상 불가능하다. `domain` 노드는 그래프 경로 대상이 아니다.
- `_expected_fit`의 계약 우선 처리(`492-493`)가 gap을 가린다.
- 앵커 `디자인`이 넓어 인력·상주 제약의 연결을 깨뜨린다.
- 차단 조건 원문 블록 11개가 selector 영역 밖이다(덮는 카드가 따로 있어 이번 결과를 결정하지는 않았다).

## 8. 한계

- 표본: 공고 10건, 실회사 1곳. gold 판정은 "진행 어려움" 5·"조건부 진행" 5의 두 종류뿐이고 "진행 가능"이 없다. 대부분 유지관리 용역이다.
- 제약 단위 원인은 재생하지 못했다(1절). unit 단위 저장 코드만 정확하고, 제약·개념 단위 귀속은 원문 기반 재구성(467 중 10 불일치)과 탐침이다.
- 탐침은 블록 전체를 인용으로 쓴 손으로 만든 이상적 제약이며 모델 답이 아니다. 모델 인용은 더 짧을 수 있다.
- 재생은 고친 대조기가 종단에서 무엇을 낼지 보여 주지 못한다. 역할·종합 단계는 모델이고, 같은 gold 재측정은 전송 승인 대상이다.
- 분석용 어휘 표식(실적·HW)은 건수 감을 잡기 위한 것이며 제품 규칙이나 요건 수가 아니다.
- 결과는 `unmeasured_reference`이며 품질·운영 전환 근거가 아니다.

## 9. 실행한 검사

| 명령 | 결과 |
|---|---|
| 위 3절 스크립트 (2회) | exit 0, 입력 검사 6개 모두 true, 두 출력 sha256 동일 |
| `cd web/backend && python -m pytest -q tests/deep_review/test_card_compare.py` | 10 passed (제품 코드 변경 없음; import한 대조 함수의 현재 동작 확인용) |

PostgreSQL 테스트·Playwright·운영 조회는 실행하지 않았다(제품 코드 변경 없음).
