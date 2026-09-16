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

## P5 운영 반영 (08:15~08:20 UTC, main 68a1c83)

- 병합: `integ/prespec-recovery`를 main에 fast-forward. main 작업 트리의 미커밋 중복 변경(docs/design 삭제 5개·findings.md 9/15 항목)은 브랜치 커밋이 같은 내용을 담아 버렸다.
- 이미지: `bidops-web`·`bidops-analysis-worker`·`bidops-prespec-attachment-worker`·`bidops-migrate` `:latest`를 main 68a1c83로 빌드(웹 `127f4946…`, analysis `5b5fecb7…`, attachment `a1776f85…`).
- 백업: `ro-backup` → `backups/postgres/full/bidops-20260916T081546Z.dump`(9.6 MB, SHA-256 앞 16자 `6c1ed085908f365c`, `pg_restore --list` TABLE DATA 76개). restore 시험은 하지 않았다.
- migrate: Alembic head `0026_overview_mvp` 유지, `runtime-privileges.sql` 재적용 COMMIT. worker 역할에 `document_bundle`·`document_bundle_item`·`idempotency_record`·`work_job` INSERT와 열 한정 UPDATE가 실효 권한으로 확인됐다. DELETE 없음.
- 재생성: web·analysis-worker(개요 플래그 ON)·prespec-attachment-worker를 표준 compose 4종(base·edge·model-egress·prespec-attachment)으로 `--no-deps --no-build --force-recreate`. attachment worker는 9/11 배포 json 대신 표준 compose로 돌아왔다(네트워크 database·prespec-egress·scanning·storage).
- 확인: `/api/health` 200, 세 컨테이너 재기동 뒤 3분간 오류·42501 없음, `close-overview-run` CLI 존재, 상한 초과 활성 job 0건. document-worker 2개는 손대지 않았다.
- 하지 않은 것: 개요 대기열 재투입(취소 33건은 그대로), 모델 호출, 첨부 재수집.

## 개요 재설계 반영 뒤 표본 5건 재실행 (12:54~13:00 UTC, main ac92c2a)

ADR-0057 결정 1~3(목차 우선 범위 선택·결과 3섹션·검증 완화)을 병합·배포한 뒤 같은 5건을 다시 실행했다.
결정 4(회사 핏의 심층 검토 1단계 이동·자동 심층 게이트 변경)는 담당자 지시로 보류해 배포하지 않았다.
배포 전 백업 `backups/postgres/full/bidops-20260916T125324Z.dump`(SHA-256 앞 16자 `6ebbc44e58d2fa2d`).
web·analysis-worker·prespec-attachment-worker만 재생성했고 migration·권한 변경은 없다. 로드된 정책은
`bidops.prespec-overview-policy.v7`(digest 앞 12자 `1dd717d36642`).

토큰은 이번부터 run의 `raw_response_refs`에 provider usage가 그대로 저장된다.

| notice | 오전 결과 | 재실행 결과 | 범위 | 초안 입력/출력 tok | 의미 입력/출력 tok | 소요 | 절(개요/과업/예산기간) |
|---|---|---|---|---|---|---|---|
| 780 | failed, fallback 1~24 | **completed** | auto 3~6 | 2,580 / 1,922 | 5,498 / 439 | 1.2분 | 4/5/3 |
| 781 | completed, fallback 1~60 | completed | **fallback 1~60** | 26,913 / 2,072 | 30,111 / 206 | 1.6분 | 3/4/4 |
| 785 | failed, fallback 1~60 | **completed** | auto 3 | 1,100 / 1,600 | 3,582 / 371 | 0.9분 | 3/4/3 |
| 805 | completed, auto 74~98(오선택) | completed | **auto 4~6** | 1,823 / 1,890 | 5,074 / 223 | 1.0분 | 5/5/2 |
| 833 | failed, fallback 1~60 | **completed** | auto 3~5 | 1,471 / 1,209 | 3,103 / 303 | 0.7분 | 4/2/2 |

- 완료 2/5 → **5/5**. 입력 토큰 합계는 오전 약 223k에서 약 81k로 줄었고, 자동 범위로 간 4건은 run당 입력이 1만 토큰 미만이다.
- `semantic_extra_ids`·`evidence_dropped` 경고는 이번 5건에서 나오지 않았다. 남은 경고는 수치 메타데이터 계열(`quantity_*`)과 780의 조각 대조뿐이다.
- 심층 검토 0건·회사 핏 attempt 0건을 재확인했다(자동 심층 검토는 시작되지 않았다).
- **남은 결함 1건:** 781은 rhwp 절 후보가 잘려(`section_candidates_incomplete`) 운영 경로가 `candidates_complete=False`를 넘기고, 그 값이 목차 전략까지 건너뛰게 해 fallback으로 갔다. 목차 전략은 절 후보를 쓰지 않으므로 이 조건과 분리해야 한다(브랜치 `fix/overview-toc-ignores-candidates`에서 수정 중).
- 결과는 `unmeasured_reference`이며 품질 측정·운영 활성화 근거가 아니다.
