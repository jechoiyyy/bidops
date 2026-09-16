# 2026-09-16 사전규격 개요 파이프라인 운영 복구와 표본 5건 실행

계획: `~/.claude/plans/plan-wild-sphinx.md` P0·P6. 코드 변경 없음. 운영 컨테이너 재생성과 DB 조회만 수행했다.

## 착수 시점 사실 (06:29 UTC)

- analysis worker 환경 `BIDOPS_VLLM_BASE_URL=http://192.0.2.10:8000/v1`(TEST-NET-1 자리표시자). worker 안 TCP connect timeout.
- `prespec_overview_run`: completed 8(전부 9/11) · needs_human_review 14 · failed 67 · cancelled 29 · queued 38 · running 1(`a66f43e9…`, notice 778, job `dae6a8e6…` attempt_count 205, max_attempts 3).
- 회사 핏 attempt 0, 심층 검토 0, 마지막 완료 2026-09-11 07:10 UTC.

## 조치

| 시각(UTC) | 조치 | 확인 |
|---|---|---|
| 06:5x | `env/model.env` `BIDOPS_VLLM_BASE_URL=http://192.168.0.139:58765/v1`, `ALLOWED_HOSTS=192.168.0.139` (gitignore, 로컬만) | grep |
| 06:57:17 | analysis-worker 재생성, 플래그 OFF (표준 compose 3종, `--no-deps --no-build --force-recreate`) | queued 38 → `cancelled/overview_disabled` |
| 07:00:42 | analysis-worker 재생성, 플래그 ON. 이미지 `sha256:82ad345c25d3…` | env 확인 |
| 07:0x | worker 안에서 `resolve_model_endpoint("overview")` + `verify_identity()` | `ModelIdentity(model='qwen3.8-27B', revision='', max_model_len=262144)` |
| 07:0x | `enqueue-overview` ×5 | 아래 표 |

멈춰 있던 run(notice 778)은 옛 worker의 lease(07:15:43 UTC 만료) 뒤 새 worker의 `_expire_leases`가 `failed/lease_expired`로 닫는다. 재투입하지 않았다.

## 표본 5건 선정 근거

취소된 38건의 큐 순서 앞쪽에서 범위 선택 경로가 섞이도록 골랐다. 이전 실패는 전부 9/11 환경 문제(clamav·converter)다.

| notice | 사전규격 | 첨부 | 이전 run |
|---|---|---|---|
| 780 | R26BD00273599 AI 기반 파쇄암 입도 분포 분석… (계속 추적 중) | hwp+pdf | fallback → needs_human_review |
| 781 | R26BD00273462 부동산거래관리시스템 기능고도화 감리 | hwp | fallback → needs_human_review |
| 785 | R26BD00273848 2027년 물공급운영시스템 유지관리 | hwpx | 환경 실패만 |
| 805 | R26BD00273869 2027년 정보시스템 통합 유지관리 | hwpx | auto → needs_human_review |
| 833 | R26BD00273676 KEIT RCMS 통합감리 및 개인정보 영향평가 | hwp+hwpx | auto → needs_human_review |

## 결과 (07:01~07:13 UTC, 5건 모두 종결)

| notice | 결과 | 범위 | 호출 | 초안 입력/출력 tok | 의미 검토 입력/출력 tok | 소요 |
|---|---|---|---|---|---|---|
| 780 | failed `semantic_response_invalid` | fallback 1~24쪽 | 2 | 9,683 / 3,124 | 13,693 / 802 | 2.0분 |
| 781 | **completed** | fallback 1~60쪽 | 2 | 26,964 / 3,479 | 31,541 / 386 | 2.3분 |
| 785 | failed `semantic_response_invalid` | fallback 1~60쪽 | 2 | 28,733 / 3,807 | 32,456 / 767 | 2.6분 |
| 805 | **completed** | auto 74~98쪽 | 2 | 10,896 / 3,204 | 15,797 / 691 | 2.2분 |
| 833 | failed `semantic_response_invalid` | fallback 1~60쪽 | 2 | 24,907 / 3,582 | 28,396 / 361 | 2.9분 |

토큰은 run이 저장하지 않아(브랜치 `feat/overview-claim-guard`가 저장하도록 고침) 같은 함수로 프롬프트를
재구성해 vLLM `/tokenize`(chat template 적용)로 계산한 값이다. 실제 usage와 수십 토큰 차이가 있을 수 있다.
합계 입력 약 223k·출력 약 20k 토큰. 모델 호출 timeout·identity 오류·42501은 없었다.

### 실패 3건의 공통 원인: 의미 검토 응답이 `checks`를 상한 12개로 채운다

암호화 원응답을 복호화해 기대 ID와 대조한 결과다.

| notice | 결정적 검사 탈락 | 기대 `checks` ID 수 | 응답 ID 수 | 끼어든 ID |
|---|---|---|---|---|
| 780 | C11, A03 | 11 | 12 | A01 |
| 785 | c9·c10·c11, a3 | 9 | 12 | a1, a2, a4 |
| 833 | C04·C08·C12, A03·A04 | 9 | 12 | A01, A02, U01 |

세 응답 모두 JSON·스키마는 통과하고 `_coverage`(응답 ID 집합 = 살아남은 주장 ID 집합)에서
`SemanticResponseError`가 난다. 프롬프트·지시문·시스템 프롬프트 어디에도 "12개"를 요구하는 문장은 없고
정책 v6 `stages[1].output_schema.properties.checks.maxItems=12`만 있다. 즉 모델이 배열 상한을 목표 개수로
읽고 분석·미확인 ID로 채운다. 결정적 검사에서 주장이 탈락해 기대 수가 12 미만이 된 run만 실패했고,
탈락이 없던 781·805(`warnings_json`에 `claims_dropped` 없음)는 통과했다.

현재 코드는 이를 `failed/semantic_response_invalid`로만 남기고 coverage 불일치라는 세부 사유를 기록하지
않으며, `max_semantic_calls=1`이라 보정 재호출도 없다. 후속 결정 후보: (a) 의미 단계 입력에 기대 ID 목록과
개수를 명시하고 스키마 `maxItems`를 그 run의 실제 주장 수로 동적으로 맞춘다, (b) coverage 불일치를
`needs_human_review/semantic_coverage_mismatch`로 구분해 기록한다, (c) 의미 검토에 1회 보정 재호출을 허용한다.
어느 것도 이번 범위에서 바꾸지 않았다.

### 멈춰 있던 run(notice 778)

옛 worker의 lease(07:15:43 UTC)가 만료된 뒤 새 worker의 `_expire_leases`가 07:15:44 UTC에 run `failed/lease_expired`, job `failed/lease_expired`(attempt_count 219)로 닫았다. 재투입하지 않았다. 07:17 UTC 기준 활성 run 0건.

## 화면 확인 (18787, 1440×900, Playwright DOM + 캡처, 07:2x UTC)

| notice | 화면 | 확인 내용 |
|---|---|---|
| 781 | `/pre-specs/781` | 개요 섹션에 사업 개요·주요 과업 주장과 주장별 `PDF n페이지 ↗` 링크, "참조 실행 · 품질 미측정 · 운영 승인 아님" 표식. fallback 범위라 "개요 입력 범위 확정 필요 · 확정하기" 카드가 함께 보인다(설계대로) |
| 805 | `/pre-specs/805` | 문서 근거 표에 c1~ 주장과 `PDF 75페이지 ↗` 링크, "전체 근거 PDF 열기" |
| 780 | `/pre-specs/780` | "실패 · 모델 실행 또는 결과 검증이 실패했습니다. 실패 결과를 권고로 보정하지 않습니다.", 회사 적합성 "자동 판정 비활성" |

세 화면 모두 loading shell이 아닌 완성 상태였다. 캡처는 세션 scratchpad에만 두었고 영구 증거 경로가 아니다.

## 게이트 (통합 트리 `integ/prespec-recovery` = main 10cb5be + P1 a58487f + P3 05dcc40·7aedfee·d90980a + P2 bdd2548·2b91bf4)

- `./run-tests.sh`: exit 0.
- backend `pytest tests/ -q`(PostgreSQL harness 포함, 19분): **2017 passed, 27 failed, 21 errors, 5 skipped**. 실패·오류 48건은
  전부 `tests/screening`(46)과 `tests/app/test_order_plan_{screening_api,tracking_independence}.py`(2)이며 원인은 워크트리에
  gitignore된 `experiments/order-plan-screening/review-inputs/{company,prompts}`가 없어서 난 `FileNotFoundError`다(같은 테스트가
  main 작업 트리에서는 통과). 두 디렉터리를 main으로 symlink한 뒤 그 48건이 든 부분집합만 재실행: **423 passed, 14 skipped**
  (PostgreSQL 전용 skip) → 일회용 `postgres:17.11`에 `BIDOPS_TEST_POSTGRES_URL`을 주고 같은 부분집합 재실행: **437 passed, 0 skipped, 0 failed**(컨테이너 제거).
  변경과 무관한 기존 실패는 이번 전체 실행에서 0건이었다(memory 기준선의 기존 실패 4건은 재현되지 않음).
