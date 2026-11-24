# 2026-11-25 업무 근거 지도 엔진·분석 화면 — main 병합, 운영·포트폴리오 반영

사용자 요청("포폴과 운영에 반영해줘 / 메인에 병합도 하고 푸쉬도 진행해")으로 진행한 기록이다.

## main

| 항목 | 값 |
|---|---|
| 병합 | `21a2a84` — 통합 브랜치 `portfolio/analysis-redesign-integration`(포트폴리오 full-cycle 커밋 4개, 분석 화면 재구성, page-text endpoint, 1·2단계 엔진, 라벨) |
| 추가 | `5e8f7a1` — 요구사항 ID 형식·단일 항목 표 추출 수정. 2026-11-24 17:13부터 운영 이미지 `bidops:main-20261124-engine-coverage`로 돌던 `bidops-engine-reqfix` 클론의 미커밋 코드(운영 이미지 백엔드·엔진 426개 파일이 그 작업 트리와 같음을 해시로 확인). main 배포가 이 수정을 되돌리지 않도록 함께 넣었다. |
| push | origin `f64fa1d..5e8f7a1` fast-forward. 병합은 깨끗한 클론 `/Users/temp/orca/bidops-merge-20261125`에서 했다. |
| main checkout | 갱신하지 않았다(origin보다 뒤). 다른 작업의 미커밋 변경 8개 파일(ADR.md, PageOverviewSection, api.ts, types.ts, PreSpecDetailPage 등)이 병합 내용과 겹친다. 그 작업을 커밋·정리한 뒤 `git pull --ff-only`. 운영 compose 파일·cron 스크립트는 병합으로 운영 동작이 바뀌지 않는다(`compose.sh` 변경은 `bidops-portfolio` 프로젝트 전용). |

검사(병합 트리): 엔진 + `test_overview_api`·`test_engine_runs`·`test_company_wiki*` 1,658 통과·1 skip(PostgreSQL 보호), 릴리스 이미지 + 임시 PostgreSQL 17.11. 프런트 빌드·포트폴리오 빌드·대비 8·단위 3 통과. 화면 게이트(app + 세 폭) 1,090 통과·21 skip·1 실패 — `order-plan-policies.spec.ts:265`는 main `f64fa1d`에서도 같은 실패(기존).

## 운영

| 항목 | 값 |
|---|---|
| 이미지 | `bidops:main-20261125-5e8f7a1`(깨끗한 클론, `--platform linux/amd64 -f docker/Dockerfile`). 운영 빌드에는 분석 화면 코드가 없다(번들 검사 0). |
| 교체 | web + analysis-worker(`.env` `BIDOPS_IMAGE`, `up -d --no-deps --no-build --force-recreate web analysis-worker`). 교체 시 진행 중 작업 0, 일일 cron(06:31·07:07)은 끝난 뒤. 첨부 worker·문서 worker 그대로. |
| DB | migration 없음(head `0043_company_wiki_ingest`). 백업 `backups/postgres/full/bidops-20261124T231317Z.dump`(`run --rm --no-deps ro-backup`, postgres 재생성 없음). |
| 되돌리기 | `.env` `BIDOPS_IMAGE=bidops:before-reanalysis-deploy-20261125-web` 후 web 재생성, analysis-worker는 `bidops:before-reanalysis-deploy-20261125-worker`. |
| 확인 | 운영 API 200, 운영 4186 page-text 200, web 예외 0, 세 폭 6개 화면 가로 넘침 0. 화면의 404 3건(`company_not_registered`·`briefing_not_found`·`company_wiki_ingest_disabled`)은 운영의 원래 상태. |

운영은 엔진 경로가 `mock_reference`이고 live 전송은 계속 fail closed다. 코드 배포를 기능 활성화나 품질 합격으로 적지 않는다.

## 포트폴리오(:8194)

| 항목 | 값 |
|---|---|
| 코드 | 브랜치 `portfolio/deploy-20261125`(병합 클론, push 안 함) = main `5e8f7a1` + 포트폴리오 전용 커밋(`ea53b14c` 계열: 시계 고정·스냅숏 안내·배너 제거) + 포트폴리오 세션의 미커밋 분석 화면 개선(`40a2bf1`: 참가 자격 이름, 개요 묶음, 결과 로더) + 가져오기 사례 제외 옵션(`34017b2`) |
| 이미지 | `bidops:portfolio-20261125-40a2bf1`(`BIDOPS_PORTFOLIO_ANALYSIS=1`, `BIDOPS_PORTFOLIO_FROZEN_NOW=2026-11-24T13:35:00+09:00`, `web-frozen-clock.Dockerfile` 층) |
| 교체 | `bidops-portfolio-build`에서 `BIDOPS_PORTFOLIO_IMAGE=… docker/portfolio/compose up -d --no-deps --no-build --force-recreate web`. 되돌리기 이미지 `bidops:portfolio-before-reanalysis-20261125`(= `portfolio-20261124-gate-labels`). |
| 분석 결과 | `live2` 46건 중 40건 가져옴. 6건(N3229·N3268·N3271·N4150·N4154·N4165)은 기존 요구사항 추출 수정 분석보다 요구사항을 적게 찾아(예: N3271 116→0) 제외하고 기존 분석을 유지. 가져오기 전 백업 `bidops-portfolio-build/backups/portfolio/portfolio-before-live2-import-20261125.dump`. |
| 확인 | 엔진 분석이 있는 52개 화면 오류·`0쪽은` 문장·`[[실적코드]]`·가로 넘침 0, 지도 기준 안내 28개, 4186 충족 21·부분 31·미확인 0, 스냅숏 시계 유지. |

## 남은 일

- 최종 엔진(`5e8f7a1`, 2단계 + 요구사항 추출 수정)으로 46건 재분석(`live3`) — 승인 대기. 제외한 6건과 나머지의 엔진을 하나로 맞추는 일이다.
- GAP 근거 검사기가 `[[people.…]]`·줄인 프로필 경로를 놓치는 헛경고(상주 제약 5건).
- 포트폴리오 브랜치의 기존 화면 검사 실패 7건(포트폴리오 세션이 상세 배치를 바꾸며 갱신하지 않은 검사, 배포되어 있던 트리에서도 같음).
