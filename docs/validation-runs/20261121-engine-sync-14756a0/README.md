# 2026-11-21 분석 엔진 패키지 재동기화(14756a0) 배포 기록

분석 엔진 패키지(`packages/bid-deep-engine`)를 원본 `bid-deep-agent`의 커밋 `14756a011bc0af5164f564328dbad4334a54466b`로 다시 맞추고, 사전규격 상세 분석 완료 화면(mock 빌드 전용)이 새 필드를 읽게 한 변경을 운영에 반영한 기록이다. DB migration·정책·기능 스위치 변경은 없다. 엔진 경로는 `mock_reference` 그대로이고 live 전송 승인은 없다. 코드 배포는 기능 활성화나 품질 합격이 아니다.

## 운영에서 달라지는 것

화면과 동작에서 달라지는 것은 없다. 운영은 엔진 스위치가 꺼져 있고(`engine_analysis:false`) 분석 완료 화면은 운영 번들에 들어가지 않는다. 이미지 안의 엔진 패키지만 새 원본 커밋으로 바뀌었다.

## 승인

- 2026-11-21 사용자(jechoi): 실사용 테스트에서 드러난 문제 1~4번을 엔진에서 고치고 "필수 여부는 완전히 제거하자" → 반영 뒤 "1번 2번 둘다 진행해줘"(커밋·main 병합·운영 반영, 3235 재분석).

## 배포 당시의 브랜치와 후속 main 병합

- 배포한 커밋은 작업 브랜치 `feat/engine-sync-14756a0`의 `2d47d42`다(main `acaea68` 위에 `bb95fe1` 엔진 패키지, `2d47d42` 화면). 배포 당시에는 main 병합 전이었다.
- 이유: main checkout에 다른 세션의 미커밋 수정 65개 파일이 있고 그중 2개(`web/frontend/src/styles/pre-spec-analysis.css`, `web/frontend/tests/prespec-analysis-view.spec.ts`)가 이 변경과 겹쳐 fast-forward가 거부됐다. 그 수정은 건드리지 않았다(stash·되돌리기 없음). 두 파일의 그쪽 수정(3줄)은 이 브랜치 위에 충돌 없이 얹힌다(`git apply --check`로 확인).
- 그래서 이미지 꼬리표를 `main-…`이 아니라 `engine-sync-…`로 붙였다. 내용은 그 시점 main의 커밋 전부 + 위 두 커밋이다.
- 후속 확인에서 로컬 main을 배포 기록 커밋 `e5e20a8`까지 fast-forward했다. 겹치는 두 파일의 미커밋 변경은 병합 뒤 바이트 단위로 복원을 확인했다. web과 두 워커에서 배포 기록의 이미지 digest가 일치했고 운영 `GET /api/health`가 ok를 반환했다. 운영 컨테이너의 JS에서도 A안의 종합 권고 문구와 mock 화면 표지가 0건이었다.

## 반영 내용

| 항목 | 값 |
|---|---|
| 엔진 패키지 | 원본 `f69f8cf` → `14756a0` 사이에 바뀐 vendored 파일 17개 교체, 새 원본 모듈 `analysis/output_quality.py` 추가, `UPSTREAM.json`의 `commit`·원본 바이트 해시 갱신. 해시는 원본 저장소의 `git show 14756a0:<path>`에서 계산했다 |
| 엔진 변경 요지 | 표 행 형식 인용을 그 요구사항 표 안에서 칸 단위로 대조(글자가 다른 인용은 실패 유지, 자동 교정 없음), `RequirementFit.name`·`definition`·`instance_key` 추가, `Analysis.requirement_counts`·`language_warnings` 추가, `RequirementFit.mandatory` 삭제 |
| 화면 | 분석 완료 화면(mock 빌드 전용): 요구사항 표가 이름을 보이고(인용문은 근거 패널), 분석 기준 줄에 "원문 요구사항 n건 중 m건 분석", 요약 위에 한자·외국어 혼입 경고 건수. 필수·선택 표시는 지웠다. 새 필드가 없는 응답은 전과 같다 |
| 이미지 | `bidops:engine-sync-20261121-2d47d42`(linux/amd64, `sha256:e3eae84e511a3779250aa80356d7557ea406fc6186c0814c3e11333ff951f98e`). 커밋된 내용만으로 빌드했다(미리보기 전용 설정 파일은 빌드 동안 작업 폴더 밖으로 옮겼다) |
| 교체한 서비스 | `web`, `analysis-worker`, `prespec-attachment-worker`(`up -d --no-deps --no-build --force-recreate`, 20:30 KST). 직전에는 web이 `main-20261121-31f8048`, 워커 둘이 `main-20261121-af2c303`이었다 |
| 설정 | `.env`의 `BIDOPS_IMAGE` 한 줄만 바꿨다(사본과 대조해 다른 줄 동일) |
| DB | migration 없음 |
| 백업 | `backups/postgres/full/bidops-20261121T112646Z.dump`(114,530,953 B, 0600, SHA-256 `91357f75f56e1f4d315517664007ad6d80bd745c17d46382c44229792e81a218`, TABLE DATA 111개). `run --rm --no-deps ro-backup`으로 실행했고 postgres 컨테이너 id·생성 시각이 전후로 같다 |
| 롤백 지점 | Git 태그 `before-engine-sync-14756a0-20261121`(`acaea68`), 설정 사본 `backups/env-prod-before-engine-sync-14756a0-20261121`(0600, `BIDOPS_IMAGE=bidops:main-20261121-31f8048`). 되돌릴 때는 `BIDOPS_IMAGE`를 복구하고 같은 세 서비스를 다시 만든다(워커는 직전에 `af2c303`이었다) |

## 원본 엔진 쪽 작업

- 원본 수정은 Codex 세션이 했다(`fix/prespec-analysis-output` 브랜치, `f69f8cf` 위에 `14756a0`). 쓰기 권한이 작업 폴더로 제한돼 커밋을 번들로 남겼고, 그 번들을 원본 저장소의 같은 브랜치로 가져왔다. 원본에서 병합·푸시되기 전에 그 브랜치가 지워지면 `UPSTREAM.json`의 커밋을 찾을 수 없다.
- Codex 보고: 원본 전체 테스트 4,474 통과·33 건너뜀·6 실패(같은 6건이 부모 커밋에서도 실패). BidOps에서 다시 돌려 보지 않았다.

## 검사

- 엔진 패키지 `engine_tests` 전체 1,497 통과(manifest 해시 대조 포함).
- 백엔드 `tests/deep_review/test_engine_runs.py`·`tests/app/test_engine_runs_api.py`를 일회용 `postgres:17.11`로 실행해 45 통과·1 건너뜀(`PostgreSQL guard`).
- 화면 `prespec-analysis-view.spec.ts` 9건 통과(mock 개발 서버). 운영 빌드 통과, 빌드 결과와 이미지 안 번들에 분석 화면 표지 0건.

## 배포 후 확인 (20:30 KST, GET만 사용)

| 확인 | 결과 |
|---|---|
| 컨테이너 | 세 서비스 모두 새 이미지, `restart=unless-stopped`, web `healthy`, 오류 로그 0줄 |
| `GET /api/health` | `{"status":"ok"}` |
| `GET /api/feature-flags` | `rl_analysis:false, prespec_overview:true, engine_analysis:false` (배포 전과 같음) |
| `GET /api/order-plan-screening/daily-trigger` | `effective_enabled:true`, `c2-order-plan-screening-v6`, 스위치 ON (배포 전과 같음) |
| 이미지 안의 엔진 패키지 | `UPSTREAM.json` `commit` = `14756a01…`, `output_quality.py` 있음, `__pycache__` 없음 |
| 화면 | `/pre-specs/3753`·사전규격 목록·발주계획·대시보드가 열리고 분석 화면 없음, 페이지 오류 없음 |
| tailnet | `http://100.88.161.54:8188/pre-specs/3753` 200 (이 Mac에서 확인) |

## 이 변경의 근거가 된 실사용 테스트

- 사전규격 3건(notice 3753·3235·3750)의 제안요청서를 나라장터 공개 첨부에서 받아 독립 실행 엔진(`bid-deep-agent`, 회사 자료 `company/rootlab.yaml`)으로 분석했다. 모델은 엔진 설정대로 Mistral Large(로컬 LiteLLM 경유, 외부 전송)이고, 3753은 Mistral Medium으로도 돌려 비교했다. 사용자가 범위·대상·외부 전송을 고른 뒤 실행했다.
- 결과와 로그: `bid-deep-agent/out/_prespec-live-20261121/`(BidOps 저장소 밖). 비용은 Large 3건 2.22달러, Medium 1건 0.78달러.
- 결과는 측정 게이트를 거치지 않은 참조 실행이며 품질 근거가 아니다. 운영 DB에는 아무것도 쓰지 않았다(미리보기는 운영 web을 GET으로만 읽고 쓰기 요청을 막았다).

## 남은 한계

- 엔진 스위치가 꺼져 있어 운영에서 새 패키지로 엔진 실행을 돌려 보지 않았다.
- 한자·외국어 혼입은 감지·경고만 한다. 해당 단계를 다시 요청해 줄어드는지는 확인하지 않았다.
- 실제 엔진 결과가 분석 완료 화면으로 들어오는 연결(live 실행 승인, 회사 근거 등록, 화면 공개)은 RL-11 범위로 남아 있다.
- 루트 `CLAUDE.md`·`AGENTS.md`의 현재 운영 이미지 문장은 고치지 않았다(main checkout에 다른 세션의 미커밋 수정이 있다).
- 교체 뒤 워커가 실제 작업을 처리하는 것은 확인하지 않았다(대기 작업 없음). 2026-11-22 아침 cron(06:30·07:00) 로그에서 확인한다.
