# RL-10 대조 규칙 v2 — 차단 조건 탐침 재생 (모델 호출 없음)

2026-11-19, launch-hardening [설계고도화안](../../1118_launch-hardening/설계고도화안.md) §4 D-1, 기능 [RL-10](../../work/groups/RL/features/RL-10-compare-blockers/spec.md). [D-2 분해](../20261119-rl05-unknown-breakdown/README.md)의 탐침(gold 차단 조건 원문 블록을 인용 그대로 쓴 이상적 제약)을 대조 규칙 v1·v2로 다시 돌렸다.

- 모델 호출 0회. 운영 web·DB 조회 0회. `bidops-local`은 기동하지 않았다. 정책·회사 근거를 어느 DB에도 import하지 않았다.
- 문서 원문·회사 값은 적지 않는다. 결과는 진단이며 품질 근거가 아니다(`unmeasured_reference`).
- `fixture_f1`·`fixture_f2`는 **테스트 fixture**다. 사람이 확인한 회사 사실이 아니며 제안값도 아니다.

## 1. 입력과 실행

| 입력 | sha256 |
|---|---|
| RL-05 `final/actual.v1.json` | `e64a6694…abf07` (receipt와 같음) |
| `gold.v1.json` | `6c4ca154…627a` |
| `final/score.v1.json` | `c09b020c…20b1` |
| `rootlab.source.v4.json` | `78f525bc…1af9` (그래프 스냅숏 `402a9e06…4fef` = export `company_sha256`) |
| `ontology.v2.json` | `7e6f4d8a…96d7` |
| 지명 표 `card-compare-places-kr-v1.json` | `03cb66d0…b227` |

```bash
cd <저장소 루트>
/Users/temp/orca/bidops/.venv/bin/python docs/validation-runs/20261119-rl10-compare-blockers/rl10_blocker_probes.py \
  --eval-dir /Users/temp/orca/bidops/.sdlc/local-runtime/rl-evaluation-20261019 \
  --company-source /Users/temp/orca/fixtures/company/rootlab/rootlab.source.v4.json \
  --ontology /Users/temp/orca/fixtures/company/rootlab/ontology.v2.json > probes.json
```

- 입력 digest가 하나라도 다르면 `input_mismatch`로 exit 2. 2회 실행 출력이 바이트 단위로 같았다([`probes.json`](probes.json) sha256 `c0fa0a8c…9657`).
- 네 변형: `v1_source_v4`(정책 v11 이하 규칙, 회사 근거 v4 그대로 — RL-05 조건), `v2_source_v4`(정책 v12 규칙, v4 그대로), `v2_fixture_f1`(v4 + `pref:onsite_cap.params.onsite_regions="대구"` + `excl:hardware.requirement_terms` = v4의 그 사실 `keywords` 그대로), `v2_fixture_f2`(F1 + 예시 용어 4개 `HW`·`전산장비`·`예비장비`·`예비부품`). fixture 원본도 제품 파서(`parse_company_knowledge_source`, 새 `requirement_terms` 모양 포함)를 통과했다.
- 탐침은 D-2와 같은 방식이되 덮는 카드의 **모든** 블록을 썼다(D-2는 앵커·어휘 표식이 있는 블록만, 55건). 7개 조건 286건.

## 2. 놓친 차단 7개 — 조건 단위 (탐침 중 하나라도 `gap`이면 gap)

| 공고·조건 | 요구(의역) | v1·v4 (RL-05) | v2·v4 | v2·F1 | v2·F2 | v2·v4에서 멈춘 code |
|---|---|---|---|---|---|---|
| 283840 B6 | 원주시청 내 상주 | 없음 | 없음 | **gap** | **gap** | `unknown_fact`(상주 가능 지역 구조화 값 없음) |
| 284019 B6 | 발주자 지정 장소 상주 | 없음 | 없음 | 없음 | 없음 | `place_unresolved`(장소가 "통일부 요청"·"지정 장소"뿐) |
| 284080 B5 | 수원시청 내 상주 | 없음 | 없음 | **gap** | **gap** | `unknown_fact` |
| 284941 B6 | 수원시 지정장소 상주 | 없음 | 없음 | **gap** | **gap** | `unknown_fact` |
| 284956 B7 | 강원특별자치도 지정 장소 상주 | 없음 | 없음 | **gap** | **gap** | `unknown_fact` |
| 284827 B9 | HW 유지관리·예비장비 (제외 분야) | 없음 | 없음 | 없음 | **gap** | 연결 없음(`requirement_terms` 없음) |
| 284956 B9 | 하드웨어 및 상용 SW 유지관리 (제외 분야) | 없음 | 없음 | 없음 | 없음 | 연결 없음. F1·F2는 `exclusion_partial`(SW 부분이 제외 분야 밖) |
| 합계 | | 0/7 | 0/7 | 4/7 | 5/7 | |

- 회사 근거 v4 그대로는 v2도 0/7이다. 상주 5개 중 4개는 장소를 정했지만 "그 밖 불가"를 말하는 구조화 값이 없어 `unknown_fact`, 1개는 장소 자체를 정할 수 없다. 제외 분야 2개는 대조가 읽을 용어가 없다.
- F1에서 상주 4개가 `gap`이 된 탐침: 283840(MHR-2 셀·문단, text·count), 284080(MHR-1 셀·문단 1-316 — v1에서는 `공동수급`과 앵커가 겹쳐 `unmapped`, 문단 1-863), 284941(MHR-2 셀·문단), 284956(문단 2-88). 근거 사실은 `staff:onsite`·`pref:onsite_cap`.
- 284956 B7의 덮는 영역 unit은 모델이 `계약`으로 분류했다(D-2 a3). 그 unit에 이 모순이 있으면 v1은 `unknown`, v2는 `gap`이다(`contract_unit_fit_with_condition_gap`).
- 284827 B9는 F2의 예시 용어로만 `gap`(제목 셀 4건: 전산장비 유지관리·예비장비 확보 계열). 본문 셀은 다른 업무 절이 섞여 `exclusion_partial`이다.

## 3. 탐침 code 합계 (286건)

| code | v1·v4 | v2·v4 | v2·F1 | v2·F2 |
|---|---:|---:|---:|---:|
| `confirmed_contradiction` (gap) | 0 | 0 | 12 | 16 |
| `confirmed_match` | 5 | 5 | 5 | 1 |
| `exclusion_partial` | — | 0 | 9 | 21 |
| `place_unresolved` | — | 10 | 7 | 5 |
| `scope_unverified` | 11 | 4 | 0 | 0 |
| `unknown_fact` | 0 | 6 | 0 | 0 |
| `unsupported_comparison` | 9 | 0 | 0 | 0 |
| `unmapped` | 261 | 261 | 253 | 243 |

v1의 `unsupported_comparison` 9(시·군 이름을 몰라서)와 역할어 `scope_unverified`는 v2에서 장소 판단(`place_unresolved`·`unknown_fact`·gap)으로 바뀌었다. F2의 `confirmed_match` 감소는 제외 용어가 닿은 인원 수 일치가 `exclusion_partial`로 내려간 것이다(설계대로).

## 4. 과잉 차단 스캔 (10건 전 원문 블록에 같은 탐침)

블록 하나를 이상적 제약으로 볼 때 `gap`이 나오는 블록 수. "안"은 gold 차단 조건이 인용한 블록, "밖"은 그 밖이다.

| 공고 | gold 판정·차단 | 상주 gap 안/밖 (F1) | 제외 gap 안/밖 (F1) | 제외 gap 안/밖 (F2) |
|---|---|---|---|---|
| 283840 | 진행 어려움·1 | 2/0 | 0/2 | 0/2 |
| 283874 | 조건부 진행·0 | 0/0 | 0/1 | 0/3 |
| 283915 | 조건부 진행·0 | 0/0 | 0/1 | 0/3 |
| 284019 | 진행 어려움·1 | 0/0 | 0/1 | 0/3 |
| 284080 | 진행 어려움·1 | 3/2 | 0/1 | 0/2 |
| 284697 | 조건부 진행·0 | 0/0 | 0/2 | 0/2 |
| 284717 | 조건부 진행·0 | 0/0 | 0/1 | 0/4 |
| 284827 | 진행 어려움·1 | 0/0 | 0/0 | 4/20 |
| 284941 | 조건부 진행·1 | 2/0 | 0/1 | 0/2 |
| 284956 | 진행 어려움·2 | 1/0 | 0/4 | 0/5 |

- **상주 장소 규칙은 gold 상주 차단이 있는 공고에서만 gap을 냈다.** 밖의 2블록(284080)은 같은 공고의 같은 수원 상주 요구가 반복된 블록이다. 상주 차단이 없는 6건에서는 0이다.
- **v4 `keywords`를 그대로 용어로 쓰면(F1) 과잉 차단이다.** 거의 모든 공고에 있는 보안 서약 표의 `하드웨어 보안 토큰`(인증 수단 항목)과 `정보통신공사업법`·`정보통신공사협회`(법령·기관 이름, 용어 `통신공사`)가 gap이 됐다. 짧은 명사 용어(F2의 `HW`·`전산장비`)는 정의 문장·보안 관리 문장·사업명에도 걸린다(284827 밖 20, 284717 `전산 장비․매체 보안 관리`).
- 이 스캔은 모든 블록을 제약으로 본 상한이다. 실제로는 모델이 추출한 제약만 대조한다. 그래도 `requirement_terms`는 그 분야 작업을 가리키는 구(예: "…유지관리", "…확보" 형태)로 사람이 고르고, 이 스캔을 다시 돌려 밖의 gap을 확인한 뒤 등록해야 한다.

## 5. 실행한 검사

| 명령 | 결과 |
|---|---|
| 위 1절 스크립트 2회 | exit 0, 입력 검사 6개 true, 출력 동일 |
| 옛 코드(base `81f29c7`의 `web/backend`를 `git archive`로 푼 사본)에서 옛 공개 API만 쓰는 임시 검사 4건(역할어 있는 상주 장소·장소 든 인원 수·계약 유형·제외 분야가 `gap`이어야 함) | **4 failed**(`scope_unverified`·`met`·`contract_unaccepted`·`unmapped`). 임시 파일이며 커밋하지 않았다 |
| 새 테스트 `tests/deep_review/test_card_compare_blockers.py` | 기능 plan의 검사 결과 참조 |

## 6. 한계

- 탐침은 손으로 만든 이상적 제약이다. 실제 추출이 상주 앵커를 인용에 담고 장소를 같은 절에 두는지는 모른다(D-2 1절: 제약 단위 행은 `bidops_rla`에만 있다).
- 표본 10건·회사 1곳·대부분 유지관리 용역. 상주 과잉 차단 0은 이 표본의 관찰이다.
- 종단 판정(역할·종합)은 모델이다. 같은 gold 재측정은 Luna 전송이라 사용자 승인 대상이며 실행하지 않았다.
