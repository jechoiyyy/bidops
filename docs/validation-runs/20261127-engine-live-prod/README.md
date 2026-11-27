# 2026-11-27 엔진 live·회사 핏 모드 코드 운영 배포와 STEP-009 재현

사용자 승인(2026-11-27): "1. 승인 2. 승인 3. 승인"(STEP-009 격리 재현, 운영 반영 P1~P8 묶음, main merge·push). P4는 STEP-009 결과를 보고 "켜고 관찰 시작", P5 키는 "별도 project 키를 만들어 줌"으로 다시 정했다.
**코드 배포와 회사 핏 suggest 켜짐을 품질 합격으로 적지 않는다.** 엔진 live는 아직 꺼져 있다.

## 소스와 이미지

| 항목 | 값 |
|---|---|
| main | `83c5af7`(origin/main fast-forward, `feat/engine-live-responses` 8 commit: RL-11 1~3단계 이식, 엔진 live(ADR-0081), 회사 핏 감사 모드(ADR-0080), migration 0045~0047) |
| 운영 소스 | 로컬 브랜치 `release/engine-live-20261127`(`536e1f9`, 복제본 `bidops-final-1127`, push 안 함) = `83c5af7` + 오늘 할 일 화면 cherry-pick 2건(`feaafd3`·`2ce0d7b`과 같은 변경, main 미병합) + 그 화면에 맞춘 engine-review 시험 1건. 직전 운영에 오늘 할 일 화면이 있었기 때문이다. 충돌은 `DashboardPage.tsx` 하나였고 RL-11의 분석 건수 2개를 새 화면의 `함께 볼 것`에 넣었다(서버가 null을 주면 숨김) |
| 이미지 | `bidops:release-20261127-536e1f9`(linux/amd64, `sha256:70fc78f8…`, `git archive` 트리에서 `docker build --platform linux/amd64 -f docker/Dockerfile`) |
| 검증 | 릴리스 트리 `tsc -b` 통과. Playwright `dashboard`·`engine-review`·`screen-semantics` 90개 중 87개 통과 뒤 실패 3개 처리: engine-review 2개는 옛 대시보드 DOM을 보던 시험이라 새 화면 기준으로 고쳤고(7b 추가), 다시 돌린 `dashboard`+`engine-review` 73개 통과. `평가 수치 누락` 1개는 병렬 실행에서만 실패했고 단독으로는 main·릴리스 둘 다 통과(원인 기록은 남지 않음). backend는 main과 같다(cherry-pick은 frontend·docs만) |

## STEP-009 — 회사 핏 제품 경로 재현 (격리 스택 `bidops-prespec1126`)

- 스택 이미지를 같은 릴리스 이미지로 바꾸고 DB를 `0043` → `0047`로 올렸다(직전 `pg_dump` 보관). 카드 v1.2(`28750478…eb22`)를 ro로 붙이고 `set-company-fit-mode --mode suggest`로 모드 행을 남긴 뒤, 스택의 analysis-worker를 멈추고 일회용 worker 컨테이너에서 [`replay_product.py`](../20261127-company-fit-probe/replay_product.py)(시계 2026-11-27 10:30 KST)를 돌렸다. 로컬 Qwen(`local-agent-main`) 22회, 19.2분, 실패 0·재시도 0.
- 채점: [`score_gold.py`](../20261127-company-fit-probe/score_gold.py), gold v2. 결과 사본 [`product_v3.1_step009.jsonl`](../20261127-company-fit-probe/results/product_v3.1_step009.jsonl).

| 실행 | gold 일치 | matched 정밀도 | matched 재현율 | 분포 |
|---|---|---|---|---|
| probe(카드 v1.2 + v3.1, 측정 실행기) | 17/22 | 5/5 | 5/6 | matched 5·unknown 9·mismatch 8 |
| **제품 경로(STEP-009)** | **14/22** | **3/3** | **3/6** | matched 3·unknown 12·mismatch 7 |

- 제품 경로가 더 보수적이다. 바뀐 것은 #9·#22(matched → unknown)와 #30(mismatch → unknown)이다. #9는 probe에서도 프롬프트 판마다 흔들렸다. 틀린 추천(정답이 matched가 아닌데 matched)은 0건이다. 차이의 원인은 확인하지 않았다(probe와 다른 점: schema·prompt version 문자열, 재시도 없음, 단일 표본).
- 재현 뒤 격리 스택의 모드는 `off`로 되돌렸고 analysis-worker는 새 이미지로 다시 띄웠다.

## 운영 반영

| 단계 | 결과 |
|---|---|
| P1 백업 | `backups/postgres/full/bidops-20261127T115257Z.dump`(`run --rm --no-deps ro-backup`, 0600, TABLE DATA 112, postgres 재생성 없음). `.env` 사본 `backups/env-prod-before-engine-live-20261127`, `env/model.env` 사본 `backups/env-model-before-engine-live-20261127`. 이미지 태그 `bidops:before-engine-live-20261127-web`·`-worker`·`-attachment`(= `main-20261127-2ce0d7b`), git 태그 `before-engine-live-20261127`(`2ce0d7b`, 로컬) |
| P2 migration | `.env` `BIDOPS_IMAGE`만 릴리스 이미지로 바꾸고 `run --rm --no-deps migrate`. `0044_company_fit_card_lineage` → `0047_company_fit_mode`. `engine_call`(app SELECT, worker SELECT·INSERT·결과 열 UPDATE)·`prespec_company_fit_mode`(app SELECT·INSERT, worker SELECT) 권한 확인. `runtime-privileges.sql:649`의 `no transaction in progress` 경고는 11-23부터 있던 두 번째 COMMIT이다 |
| P3 교체 | web·analysis-worker·prespec-attachment-worker `up -d --no-deps --no-build --force-recreate`. 직전 진행 중 작업 0(개요·엔진·회사 핏·C-2·work_job). health·대시보드·사전규격 목록 200, 오류 로그 0줄. 렌더된 스위치는 교체 전 컨테이너와 같다(개요 true, 나머지 false). 엔진 건수는 `engine_disabled`, 회사 핏 `company_fit_disabled` |
| P4 회사 핏 suggest | 카드 `env/company-fit/business-scope-card.v1.2.yaml`(gitignore). `.env`: `BIDOPS_REFERENCE_WORKFLOW_MODE=true`, 카드 경로·sha·상한 `suggest`. `env/model.env`: `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=true`, `BIDOPS_PRESPEC_COMPANY_FIT_MODEL=local-agent-main`. web·analysis-worker 재생성 뒤 `reason_code=switch_off` 확인, `set-company-fit-mode --mode suggest --actor jechoi` → `effective=true`(12:06:16Z). 기존 profile lineage는 운영에 active id가 없어 돌지 않는다. 참조 모드 전역 스위치의 다른 소비자(Luna·RL·제안서·자동 심층 시작)는 각자 꺼진 플래그로 막혀 있다 |
| P5~P8 | 대기. 엔진 전용 OpenAI project 키 파일을 사용자가 만든 뒤 진행한다 |

## 되돌리기

- 회사 핏만 끄기: web에서 `python -m app.deep_review.cli set-company-fit-mode --mode off --actor <이름> --reason <사유>`(행은 지우지 않는다).
- 코드 되돌리기: `.env`·`env/model.env` 사본 복원 → 세 컨테이너를 `before-engine-live-20261127-*` 이미지로 교체. 옛 이미지는 시작할 때 DB head `0044`를 요구하므로 migration downgrade가 먼저다. 0047은 모드 행이 남으면 downgrade를 거부한다(감사 이력 보존). 그때는 백업 복원이 길이다.

## 같은 날 추가 반영 (21:15~21:45 KST)

사용자 결정: "이미 수집된 것들은 다시 작업하지 말고, 이후에 수집된 것들에 대해서만 구현한대로 진행", 포트폴리오는 "운영 DB 유지 + 화면만", 하한 배포는 "배포하고 다시 켜기".

| 단계 | 결과 |
|---|---|
| 기존 공고 판정 중단 | 21:15 `set-company-fit-mode --mode off`. 그 전까지 기존 공고 8건이 판정됐다(matched 1·mismatch 4·unknown 2·진행 중이던 1건 완료). 이 8건은 감사 기록으로 남는다 |
| 수집 하한 | main `f8699c1`: `BIDOPS_PRESPEC_COMPANY_FIT_CARD_OBSERVED_FROM` 이후 첫 관측된 공고만 카드 lineage 대상. `.env`에 `2026-11-27T21:15:00+09:00`. 운영 worker 역할로 확인하니 `notice_observation` 읽기 권한이 없어 대상 조회가 실패(판정 0건으로 닫힘)했다. main `4f5182d`로 worker에 SELECT만 주고 `run --rm --no-deps migrate`(head 그대로 `0047`)로 권한을 다시 적용했다. worker 역할로 대상 261건 → 하한 뒤 0건 확인, `--mode suggest` 다시 기록(12:32:17Z), 75초 동안 새 시도 0 |
| 포트폴리오 화면 | main `d812377`: 오늘 할 일 화면(`feat/today-c2`·`feat/today-polish`), 사이드바 제품 이름만, 검증 표시 한국어만, 헤더 수집 상태에서 경고 건수 제거, 참가 자격 이름 쉬운 말·개요/과업/기간 묶음·예산 출처(포트폴리오 `40a2bf16`에서 엔진 결과 로더는 뺌). 고정 시계·스냅샷 안내·가져온 판정은 넣지 않았다 |
| 검증 | `tsc -b` 통과. Playwright 299개 중 279 통과·19 skip(mock 서버 전용)·1 실패. 실패한 `overflow.spec.ts:91`(1280px 사전규격 당일 마감·예산)은 이 작업 전 `0dda610`에서도 실패한다. mock 서버에서 `prespec-analysis-view` 19개 통과. backend 회사 핏·설정 170개, 권한 39개(PostgreSQL), compose 28개 통과 |
| 운영 이미지 | `bidops:main-20261127-d812377`(main에서 직접 빌드, 별도 release 브랜치 불필요). 세 컨테이너 교체, health·화면·사전규격·workload·수집 상태 200, 오류 로그 0줄. 제공 번들에 `함께 볼 것`·새 자격 이름이 있고 `시연용 스냅샷`은 없다. `.env` 사본 `backups/env-prod-before-fit-cutoff-20261127`·`backups/env-prod-before-portfolio-screens-20261127` |
