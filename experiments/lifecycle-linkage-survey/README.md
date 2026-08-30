# 생애주기 연결 조사

발주계획 → 사전규격 → 입찰공고를 잇는 공식 키가 무엇이고, 한 번 수집한 레코드가
갱신될 때 다시 관측되는지를 실제 호출로 측정하는 일회성 조사다.
제품 DB·scheduler·웹과 연결하지 않으며 산출물은 증적 문서다.

측정 결과는 [`docs/validation-runs/20260828-lifecycle-linkage-survey.md`](../../docs/validation-runs/20260828-lifecycle-linkage-survey.md)에 있다.

## 경계

- 외부 호출은 `--execute`를 명시했을 때만 일어난다. 없으면 아무것도 호출하지 않고 exit 2로 끝난다.
- raw page는 불변이다. 기존 raw 디렉터리가 비어 있지 않으면 수집을 거부한다.
- 저장되는 query에는 인증키가 없다. 응답이 인증키를 반사하면 저장 전에 중단한다.
- 담당자명·연락처 필드는 채움 비율만 세고 값을 산출물에 남기지 않는다.
- 호출 수는 700회에서 경고하고 900회에서 중지한다.
- 불변 계약 유틸(`digest_json`, `write_json_new`, `load_json`)은
  `experiments/order-plan-screening/scripts/common.py`를 그대로 쓴다.

## 사용

```bash
set -a && . ./.env && set +a

# 1. 고정 실험과 같은 구간을 재조회해 갱신 여부를 본다
python3 experiments/lifecycle-linkage-survey/scripts/survey.py collect \
  --run-id <run-id> --output-dir data/experiments/lifecycle-linkage-survey/<run-id> \
  --target order_plan --from-date 2026-08-24 --to-date 2026-08-27 \
  --timeout 120 --max-attempts 3 --execute

# 2. 사전규격과 입찰공고를 최근 구간으로 수집한다
python3 experiments/lifecycle-linkage-survey/scripts/survey.py collect \
  --run-id <run-id> --output-dir data/experiments/lifecycle-linkage-survey/<run-id> \
  --target prespec --target bid --from-date 2026-08-25 --to-date 2026-08-28 \
  --timeout 120 --max-attempts 3 --execute

# 3. 저장된 raw로 조사 결과를 만든다 (외부 호출 없음)
python3 experiments/lifecycle-linkage-survey/scripts/survey.py report \
  --run-id <run-id> --raw-dir data/experiments/lifecycle-linkage-survey/<run-id>/raw \
  --output-dir data/experiments/lifecycle-linkage-survey/<run-id> \
  --baseline-raw data/experiments/order-plan-screening/<고정 실험>/raw \
  --markdown data/experiments/lifecycle-linkage-survey/<run-id>/report.md
```

`--to-date`는 반개구간의 끝이며 조회에서 제외된다.
`--baseline-raw`는 발주계획 재조회를 비교할 이전 관측이고, 고정 실험의
`bidops.order-plan-raw-page.v1` schema도 읽는다.

## 이름 매칭 probe

사전규격에서 발주계획으로 가는 공식 키가 없으므로, 사업명 부분일치 검색이 그 자리를 대신할 수
있는지 측정한다. 정답은 입찰공고에서 온다. 공고가 `orderPlanUntyNo`와 `bfSpecRgstNo`를 모두
들고 있어 수집한 공고 구간 안의 발주계획은 정답 사전규격번호를 알 수 있고, probe는 자기 추측이
아니라 그 정답에 대고 채점한다.

```bash
python3 experiments/lifecycle-linkage-survey/scripts/name_match_probe.py \
  --run-id <run-id> \
  --raw-dir data/experiments/lifecycle-linkage-survey/<run-id>/raw \
  --output-dir data/experiments/lifecycle-linkage-survey/<run-id>/name-match \
  --execute
```

정답쌍 하나마다 한 번 호출하므로 `--limit`으로 상한을 둔다.
조회 구간은 365일을 넘길 수 없다(`resultCode=07`).

## 이름 전략 probe와 캐시

`name_strategy_probe.py`는 `name_normalize.search_variants()`의 `full` →
`breaking_split` → `normalized` → `longest_fragment` → `prefix12` 사다리를 정밀한 순서로 시도한다.
각 응답은 기존 `name_match_probe.py`의 정답쌍·검색·채점 함수를 재사용하며, 처음 정답이
나온 전략만 적중 전략으로 기록한다. 기본 캐시는 `--output-dir/cache/` 아래에 공개 query와
응답만 저장하고 `serviceKey`는 저장하지 않는다. 산출물과 캐시는 모두 기존 파일을 덮어쓰지
않는다.

```bash
# --execute가 있을 때만 외부 호출이 허용된다.
python3 experiments/lifecycle-linkage-survey/scripts/name_strategy_probe.py \
  --run-id <run-id> \
  --raw-dir data/experiments/lifecycle-linkage-survey/<run-id>/raw \
  --output-dir data/experiments/lifecycle-linkage-survey/<run-id>/name-strategy \
  --only-missed data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/name-match/name-match-probe.json \
  --execute

# 명시적 실행 게이트는 유지하면서 캐시만 재생한다. 캐시 미스는 실패 attempt로 남는다.
python3 experiments/lifecycle-linkage-survey/scripts/name_strategy_probe.py \
  --run-id <run-id> \
  --raw-dir data/experiments/lifecycle-linkage-survey/<run-id>/raw \
  --output-dir data/experiments/lifecycle-linkage-survey/<run-id>/name-strategy \
  --offline --execute
```

## 이름 정규화 오프라인 분석

`offline_name_analysis.py`는 G2B를 호출하지 않고 동결 raw와 기존 name-match probe만 읽어
정규화 충돌 위험, 기존 실패쌍의 전략별 질의·길이, 로컬 raw에서 비교 가능한 정답쌍을
측정한다. 기본 경로는 이번 동결 회차이며, 실행 결과는 `name-strategy/` 아래의
`offline-analysis-v4.json`과 `offline-analysis-v4.md`에 새로 생성된다. v4는 원문 `full`
대조군, 각 전략의 full 대비 충돌 증가분, 실측된 다섯 파손 문자를 겨냥한
`breaking_split`, 원문 기준 `prefix12`, 파손 문자로 설명되지 않는 실패 목록을 포함한다.
v3 산출물은 비교용으로 보존한다.

```bash
python3 experiments/lifecycle-linkage-survey/scripts/offline_name_analysis.py \
  --raw-dir data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/raw \
  --baseline-probe data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/name-match/name-match-probe.json \
  --output-dir data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/name-strategy
```

## 동일 이름 검색 원인 격리 probe

`search_isolation_probe.py`는 기본 사례에 대해 전체 이름, 순수 토큰, 공백 포함 토큰,
가운뎃점 조각, 괄호 조각, `%20` 인코딩 전체 이름을 순서대로 한 번씩 검색한다. 기본
출력 디렉터리는 `data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/search-isolation/`이며
각 응답은 `raw/` 아래에 불변 파일로 남고 결과 요약은
`search-isolation-probe.json`에 기록된다. 실제 실행 시에는 `BIDOPS_G2B_API_KEY` 환경변수가
주입된 셸에서만 `--execute`를 사용한다.

```bash
python3 experiments/lifecycle-linkage-survey/scripts/search_isolation_probe.py \
  --execute

# 다른 사례를 조사할 때
python3 experiments/lifecycle-linkage-survey/scripts/search_isolation_probe.py \
  --name '사업명 문자열' \
  --expected-spec-no R26BD00000000 \
  --from-date 2026-01-01 \
  --to-date 2026-08-29 \
  --execute
```

### 결과 해석

`expected_found=true`는 해당 단일 응답 페이지의 반환 항목에 기대 사전규격 번호가
포함됐다는 뜻이다. `result_count=0`은 그 질의의 결과가 없다는 뜻이다. `result_count>0`
인데 `expected_found=false`이면 결과 후보가 기대 번호가 아니거나 기대 항목이 첫 페이지
밖에 있을 수 있으므로, 그 한 번의 응답만으로 미등록을 결론 내리지 않는다.

| 변형 | 관측 | 해석 |
|---|---|---|
| 1. 전체 이름 + `+` | `expected_found=true` | 이 사례에서는 기본 실패가 재현되지 않음. `false`·0건이면 문제를 재현한 대조군이며 원인 층은 아직 미분리. |
| 2. `디지털새싹` 토큰 | `true` | 구간 내 레코드와 순수 토큰 부분일치를 지지; 전체 이름의 특수문자·길이 문제가 유력. `false`이면 토큰 색인·구간·레코드 자체를 아직 배제할 수 없음. |
| 3. `2026 디지털새싹` | #2와 비교 | #2는 `true`, #3만 `false`이면 공백 포함 질의 처리를 의심. 둘이 같은 결과이면 공백 단독 가설은 약화됨. |
| 4. `개발·제작` | `true` | 가운뎃점 포함 부분일치가 동작. #2가 `true`인데 이것만 `false`이면 가운뎃점 처리를 의심. |
| 5. `용역(하반기)` | `true` | 괄호 포함 부분일치가 동작. 다른 변형은 적중하고 이것만 `false`이면 괄호 처리를 의심. |
| 6. 전체 이름 + `%20` | #1과 비교 | #1 `false`·#6 `true`이면 `+`/`%20` 인코딩 차이가 원인 후보. 결과가 같으면 인코딩 방식 단독 원인은 약화됨. |

## 문자 관용도 probe

`search_isolation_probe.py --char-tolerance`는 로컬 prespec raw에 실제 등장하는 대상
문자별로 짧은 본 질의와 해당 문자만 제거한 대조군을 한 쌍씩 만든다. `&`, `~`, `/`,
`’`, `‘`, `_`, `『`, `』`, 그리고 가운뎃점·불릿 계열을 대상으로
하며, 없는 문자는 건너뛴다. 각 문자에 대해 probe/control을 한 쌍으로 수행하며 기본
상한은 24회다. 실제 호출 결과는 `control`이 적중하고
본 질의가 0건일 때만 해당 문자의 검색 파손 후보로 기록한다. 그 밖의 결과는
`unknown`으로 남긴다.

기본 출력 디렉터리는 기존 6회 probe와 같지만 산출물은
`char-tolerance-probe.json`, raw는 `raw/char-tolerance/` 아래에 별도로 생성되어
기존 파일을 덮어쓰지 않는다. 기본 상한은 24회이며, 필요한 호출 수가 상한을 넘으면
첫 호출 전에 실패한다.

```bash
python3 experiments/lifecycle-linkage-survey/scripts/search_isolation_probe.py \
  --char-tolerance \
  --raw-dir data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/raw \
  --output-dir data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/search-isolation \
  --max-requests 24 \
  --execute
```

`name_normalize.py`에서 현재 확정된 검색 파손 문자는 `·`(U+00B7), `&`(U+0026),
`‘`(U+2018), `’`(U+2019), `•`(U+2022) 다섯 가지다. 앞의 U+00B7은 6회
격리 probe로, 나머지 네 문자는 24회 관용도 probe로 확인했다. `・`(U+30FB),
`‧`(U+2027), `․`(U+2024)는 관용도 probe에서 무해로 확인했으며, `∙`(U+2219)은
로컬 raw에 없어 `unknown`으로 남긴다.

## 발주계획 채움률 횡단면 곡선

`plan_fill_curve.py`는 나이가 다른 발주계획 게시 구간을 각각 한 번 조회해
`게시 후 경과일수 → bidNtceNoList 채움률` 곡선을 만든다. 기본 구간은
2026-08-24~26, 08-10~12, 07-27~29, 07-01~03, 06-01~03, 04-01~03의 6개이며,
`--window FROM:TO`를 반복해 구간 목록을 바꿀 수 있다. 종료일은 포함해서 적고,
스크립트가 기존 `order_plan` endpoint의 반개구간 query로 변환한다. 나이는 조회일과
포함된 구간 종료일 사이의 달력일수로 계산한다.

```bash
# 수집은 BIDOPS_G2B_API_KEY 환경변수가 주입된 셸에서 사람이 승인해 실행한다.
set -a && . ./.env && set +a
python3 experiments/lifecycle-linkage-survey/scripts/plan_fill_curve.py \
  --output-dir data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/plan-fill-curve \
  --max-requests 40 \
  --execute

# 사용자 지정 구간
python3 experiments/lifecycle-linkage-survey/scripts/plan_fill_curve.py \
  --window 2026-08-24:2026-08-26 \
  --window 2026-08-10:2026-08-12 \
  --output-dir data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/plan-fill-curve-custom \
  --execute

# 저장된 raw만으로 재계산; 네트워크와 --execute가 필요 없다.
python3 experiments/lifecycle-linkage-survey/scripts/plan_fill_curve.py \
  --from-raw data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/plan-fill-curve/raw \
  --output-dir data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/plan-fill-curve-replay
```

구간별 원문 page는 `raw/window-*`에 불변으로 저장되고, 결과는
`plan-fill-curve.json`과 `plan-fill-curve.md`에 기록된다. JSON/Markdown에는 담당자명·전화 등
개인정보를 복사하지 않는다. 이 곡선은 서로 다른 구간의 횡단면 비교이므로 계절성·연도별
발주 패턴 차이가 섞이며, 같은 계획을 반복 관측한 종단 결론이 아니다. 두 결과가 어긋나면
2026-08-24~26 구간을 계속 재조회해 쌓는 종단 측정을 정본으로 삼는다.

## 검증

```bash
cd experiments/lifecycle-linkage-survey && \
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_*.py" -t tests
```

테스트는 전부 네트워크 없이 돈다. 인증키 비저장, payload hash, raw 덮어쓰기 거부,
담당자 정보 비인용, 응답에 없는 키와 빈 키의 구분, 고정 실험 query와의 동일성을 확인한다.
