# 2026-11-19 C-2 Top150(v6) 배포·게이트 측정 기록

[수정안](../../specs/1118_launch-hardening/발주계획-선별-수정안.md) 2~5단계의 실행 기록이다. 사용자 승인은 2026-11-19
한 번에 받았다(병합·배포, v6 적재·후보·게이트 행, 모델 실행 8건의 게이트 측정, 채점·evaluation 대행 제출,
통과 시 활성화와 일일 스위치, v5 전송 승인의 v6 승계). cron 설치는 이 승인에 들어 있지 않다.

이 기록은 시점별 증거이며 현재 계약은 [ADR-0075](../../tracking/decisions/0075-c2-stage1-top150.md)와
[일일 운영 절차](../../operations/daily.md)가 정본이다.

## 배포

| 단계 | 한 일 |
|---|---|
| 병합 | `feat/c2-top150-policy`(`d7e9186`) → `ea9dc02`, `feat/order-plan-review-tiers-ui`(`06e4d7c`) → `cfc5942`, 문서 `576e262`. push 없음. 롤백 태그 `before-c2-top150-20261119` = `f0b6bc1` |
| 백업 | owner `pg_dump -Fc`: `backups/postgres/full/bidops-20261118T155416Z.dump`(68,928,995 B, sha256 `e3c74f23a9bd505c303a0c1bc7bf2eb9514c78b2fb0add8ec6c138a65b729594`, TABLE DATA 111, head `0042_engine_run`). 운영 `.env` 사본 `backups/env-prod-before-c2-top150-20261119`(0600). 객체 저장소는 받지 않았다(이번 변경이 건드리지 않는다) |
| 이미지 | `.env`의 `BIDOPS_IMAGE`를 `bidops:main-20261119`로 바꾸고 `BIDOPS_ENV=prod scripts/compose.sh build web`(exit 0, amd64, `07eae97c…`). 이미지 안에서 `ALLOWED_STAGE1_TOP_K`와 새 탭 문구를 확인했다. migration 없음 |
| 교체 | 실행 중·대기 판정이 없음을 확인하고 `up -d --no-deps --no-build --force-recreate web analysis-worker`. web healthy, 두 컨테이너 재시작 0 |
| 교체 뒤 확인 | `/api/health`·`/api/runs`·`/api/opportunities`·`/api/order-plan-screening/policies`·`/api/feature-flags` 200. `daily-trigger`: `effective_enabled=true`, v5, `reasons=[]`. v5 행 `policy_file_present=true`·`binding_file_present=true`. 두 컨테이너에 policy·binding v5·v6와 generation config v6 다섯 파일이 마운트됐고 `BIDOPS_C2_POLICY_PATH`·`BIDOPS_C2_BINDING_PATH`는 설정되지 않았다. 기능 플래그 `rl_analysis=false`·`prespec_overview=false` 그대로 |

## v6 적재·후보·게이트 행

- 컨테이너 안 파일 digest: policy `57366b04…08de28`, binding `ad583ce2…ded4dc`, generation config `c94b67e9…70834a`(v5와 공유).
- `python -m app.screening.c2_policy load … --created-by jechoi` → `c2-order-plan-screening-v6 draft … created`.
- `POST /policies/candidate`(base `1e6d4ef1…`) → 201 `activation_candidate`, audit `64998e4e-1f2a-47fa-9774-55f9c29f120d`.
- `POST /quality-gates` → 201 `c2gate-e23a8e1fec84413a90609b14479d4476`. gold adjudicated v3(`cbdb7adf…`, manifest
  `72d6749d…`), 측정 회차는 v5 게이트와 같은 네 개(`gate-gold-2026082{7,8,9}-plans`·`gate-gold-20260830-plans`,
  `--20260901T001247.754584Z`, 적재 경고 0), `scoring_input_sha256=6bc16721…`(v5 게이트와 같은 값),
  임계값 recall ≥ 90·precision ≥ 35·중요 누락 ≤ 3·하루 검토량 ≤ 80.
- 이 단계 뒤에도 `daily-trigger`는 v5에서 `effective_enabled=true`였다.
- binding v6의 전송 승인 문구는 v5 승인(2026-10-14)을 옮긴 것이며 사용자가 2026-11-19 승계를 승인했다.
  전송 내용·모델·경로는 v5와 같다.

## 게이트 측정

측정은 일일 실행이 없는 시간(cron 미설치, 실행 중·대기 0)에 `scripts/run-c2-gate-measurement.sh`를 cron과 같은 최소
환경·공용 lock으로 분리 실행했다(`BIDOPS_C2_GATE_ACTOR=jechoi`). pass 1은 00:59~01:19, pass 2는 01:20~01:40(KST)이다.
pass당 약 20분에는 GPU 휴지(600초 사용 뒤 300초)가 들어 있다.

| pass | 게시일 | 모집단 | 모델 판정 | 관련 | 불확실 | 검토 후보 | 실행 id | 상태 |
|---|---|---:|---:|---:|---:|---:|---|---|
| 1 | 08-27 | 308 | 150 | 23 | 36 | 59 | `97c4ef64-3591-443f-b51e-22716dff831a` | 성공(404초) |
| 1 | 08-28 | 290 | 150 | 22 | 32 | 54 | `84a32270-93cd-4484-af21-09072685b9a3` | 성공(424초) |
| 1 | 08-29 | 9 | 9 | 0 | 0 | 0 | `ac684c8c-480b-4fac-a061-0d5780eb81c2` | 성공(17초) |
| 1 | 08-30 | 18 | 18 | 1 | 0 | 1 | `3b1f31f6-8e81-4349-a332-ef97215f5af6` | 성공(36초) |
| 2 | 08-27 | 308 | 150 | — | — | 59 | `809a95f8-4484-44c4-9ee0-b864f91ff221` | 성공 |
| 2 | 08-28 | 290 | 150 | — | — | 54 | `4a096c99-b32b-41bd-a3d7-b31d11cb15eb` | 성공 |
| 2 | 08-29 | 9 | 9 | — | — | 0 | `fee21e07-aa8a-43a2-ab67-0852298ef499` | 성공 |
| 2 | 08-30 | 18 | 18 | — | — | 1 | `552e8447-8c0b-46a9-8779-a5ec1144ed51` | 성공 |

pass 2의 관련·불확실 건수는 따로 읽지 않았다(검토 후보 수는 채점 요약의 값이다). 판정 실패는 pass 1 네 실행 모두 0이다.

채점(`scripts/score-c2-gate.py`, 제품 밖, `--expect-scoring-input-sha256 6bc16721…` 일치, 경고 0):

| | recall | precision | 중요 누락 | 하루 최대 검토량 |
|---|---:|---:|---:|---:|
| 임계 | ≥ 90 | ≥ 35 | ≤ 3 | ≤ 80 |
| pass 1 | 96.2963 | 45.614 | 0 | 59 |
| pass 2 | 96.2963 | 45.614 | 0 | 59 |
| v5(2026-10-14, 나쁜 쪽) | 100 | 39.7059 | 0 | 73 |

- 두 pass 판정 일치 625/625. gold 양성 54건 중 52건을 잡았고 놓친 2건은 08-27·08-28 각 1건이며 둘 다 `높음`이 아니다.
  수정안이 v5 결과에서 계산한 예측값(96.3%·45.6%·59건·중요 누락 0)과 같다.
- artifact `reports/c2-gate-v6/gate-artifact.json`(sha256 `739767c4a01e5a0f33193a67fe89f579f43b95578ea5eeaca399497a49cf1272`),
  요약 `gate-summary.md`, 제출 body `gate-evaluation-body.json`, pass 1 결과 dump `pass1-results.json`.
- evaluation `c2gateeval-5f2a6b6dbcf444b9b3d18a3ba7ebbdd8` result `통과`(제출자 `jechoi`, 사용자 승인에 따른 대행).
- 실행 스크립트 실수: 처음 묶음 스크립트가 측정 스크립트의 stdout(진행 줄 + 마지막 JSON 줄)을 통째로 JSON으로 읽어
  pass 1 뒤 결과 저장 단계에서 exit 2로 멈췄다. 측정 실행에는 영향이 없었고, 마지막 줄만 읽도록 고쳐 pass 1 dump를
  받은 뒤 pass 2를 따로 시작했다(`pass1.log`·`pass2.log`가 원래 stdout이다).

## 활성화

- `POST /policies/c2-order-plan-screening-v6/activate` → 200 `active`·`passed`, `previous_active_policy_version=c2-order-plan-screening-v5`,
  `activated_at=2026-11-18T16:40:45Z`(KST 11-19 01:40). v5는 같은 transaction에서 `retired`가 됐다.
- 직후 `daily-trigger`: `effective_enabled=false`, `reasons=["switch_bound_to_other_version"]`(예상한 상태).
- `POST /daily-trigger`(v6, enabled) → 201, audit `b25bc2d0-a3f0-49d9-bc38-827f380837ac`. 다시 읽은 값:
  `effective_enabled=true`, `policy_version=c2-order-plan-screening-v6`, `reasons=[]`.
- 누적 목록 범위는 `activated_policy_versions=[v5, v6]`라 11-04~11-17의 v5 판정 7,827건이 그대로 보인다.

## 운영 화면 확인 (읽기 전용, 1440×900)

- 발주계획 탭: `관련 696`·`불확실 668`·`모델 미판정 2,838`·`전체 7,827`. 목록 머리말은 각각
  `필수 검토 · 모델이 관련으로 판단 · 추적 미선택`, `훑어보기 · 모델이 판단을 보류 · 추적 미선택`,
  `모델이 판정하지 않은 건 · 1차 순위순`이다. `모델 미판정` 행에 `1차 순위 N위`·`가까운 역량`·`판정 실패` 표시가 보인다.
- 대시보드 일일 수집 줄: `필수 검토 48건(관련) · 훑어보기 59건(불확실)`, 발주계획 타일 `필수 696건 · 훑어보기 668건 · 새로 517`.
- 캡처: `/Users/temp/orca/bidops-captures/20261119-top150/`(저장소 밖).
- 따라잡기로 넣은 14일 치는 첫 수집일이 모두 11-18이라 `불확실`·`모델 미판정`의 "수집일 최신" 정렬이 이 묶음 안에서는
  날짜를 가르지 못하고 1차 순위순으로만 섞인다. 매일 수집이 시작되면 날짜별로 갈린다.

## v6 첫 일일 실행 (2026-11-19 10:46~10:55 KST, 기준일 11-18)

cron이 없어 설치할 줄과 같은 명령(`scripts/cron-daily-track.sh order-plans`, 이어서 `notices`)을 cron과 같은 최소 환경
(`env -i HOME=… PATH=/usr/bin:/bin`, floor `2026-11-04`, actor `jechoi`)에서 분리 실행했다. 사용자가 2026-11-19 진행을 승인했다.

| 트랙 | 결과 |
|---|---|
| 발주계획 | 수집 621건 → 실행 `8e51e70b-7219-48c4-b3d7-4dd78b3a4fc3` `성공`(v6, operational). 1단계 선정 150·탈락 471, 관련 49·불확실 35·무관 66, 판정 실패 0, 검토 후보 84. 실행 시간 352초. 감사 표본 10건. `no gap … 2026-11-04..2026-11-18`, 10:54:18 `exit=0` |
| 공고 | 수집·적재, `no gap`, 10:55:27 `exit=0`. 모델 호출 없음. 사업기회 연결 키 parse 경고는 앞선 14일과 같은 종류다 |

- 확인된 것: 모집단이 150건을 넘는 날 `stage1_selected_count=150`, 6배치, 약 6분(v5 평일 300건 판정의 절반 규모).
- 검토 후보 84건은 PoC 임계 80을 넘는다. `관련` 49건만 필수 검토로 보는 화면 구분이 전제다.
- **감사 표본은 151~175위 근접 창에서 뽑히지 않았다.** 10건의 1단계 순위는 194·301·353·382·506·521·582·601·608·617이고
  stratum은 전부 `classification_proximity`다. v5의 11-17 실행도 10건 모두 같은 stratum(325~544위)이었다. 추출이
  stratum 우선순위순이라 첫 stratum이 상한 10건을 다 채우고 순위 근접 stratum까지 차례가 오지 않는다. v6로 바뀐 것은
  근접 창의 위치뿐이라 이 양상은 이번 변경과 무관하지만, "150위 바로 밖을 감사 표본으로 지켜본다"는 수정안 §8의 전제는
  이 규모에서 성립하지 않는다. stratum별 몫을 두는 것은 policy 값 변경이라 새 버전·승인이 필요하다(후속).

## 한계

- gold는 8월 4일치 625건(관련 54건)이다. 평일 운영 규모(하루 427~627건)에서의 사람 채점은 없다.
- 화면은 격리 spec과 위 운영 화면 읽기 전용 확인까지다. 사람이 실제로 검토해 본 기록은 없다.
- 운영에서 `관련`+`불확실`은 상위 150으로도 하루 평균 약 82건으로 추정된다(v5 14일 결과에서 계산). 80건 아래라는 값은 gold 규모(290~308건/일)의 것이다.
- cron은 설치되어 있지 않다. analysis-worker restart 정책은 `no` 그대로다.

## 되돌리기

- 이미지·코드: `.env`의 `BIDOPS_IMAGE`를 `bidops:main-20261118d`로 되돌리고
  `up -d --no-deps --no-build --force-recreate web analysis-worker`. 코드는 태그 `before-c2-top150-20261119`.
  옛 이미지는 `top_k=150` 실행을 `binding_mismatch`로 거부한다.
- 스키마 변경이 없어 DB 복원은 필요 없다. v6 정책 행·게이트 행·측정 실행은 흔적으로 남긴다.
