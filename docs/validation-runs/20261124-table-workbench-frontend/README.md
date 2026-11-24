# 표 작업대 화면(ADR-0077) 운영 배포 — 프런트엔드 번들만

2026-11-24 07:10 KST 확인. 운영 web 컨테이너에 `bidops:table-workbench-fe-20261124`(이미지 ID `sha256:79ae4b20654fd40cdd7f6cb3323636565851d4aeffad5a8ae56d752427f4e7b0`, linux/amd64)를 적용했다. 직전 운영 web 이미지 `bidops:list-review-sheets-20261123` 위에 프런트엔드 번들만 바꾼 이미지다(레이어 2개 추가, entrypoint·cmd·env·workdir 동일). 이 기록은 화면 배포 기록이며 품질·운영 활성화 근거가 아니다.

## 범위

| 항목 | 값 |
|---|---|
| 바뀐 것 | web 컨테이너의 `/app/web/frontend/dist` (main `1d85c1b`의 `web/frontend`, tree `b744f687b3cb`, 서빙 번들 `assets/index-B991YZw6.js`) |
| 바뀌지 않은 것 | 백엔드 코드(직전 이미지 그대로), DB revision `0042_engine_run`, analysis-worker·첨부 worker·document-worker·postgres·minio·clamav(컨테이너 ID 교체 전후 동일), cron, 운영 스위치 |
| 배포하지 않은 것 | main `c660e72`의 백엔드 변경과 회사 위키 넣기(migration `0043_company_wiki_ingest`·권한 SQL·MinIO 버킷·환경 값). 이 checkout에서 백엔드 검사 합격을 확인하지 못했다 |
| 사용자 결정 | 2026-11-24 "화면만 배포", "main에 커밋한 뒤 배포" |

**알려진 결과: 회사 근거 화면(`/company`)은 "회사 근거를 불러오지 못했어요"로 나온다.** 새 화면이 부르는 `/api/company-wiki`가 운영 백엔드에 없다(404). 백엔드를 배포하면 풀린다 — 같은 날 11:00 백엔드 배포로 풀렸다([기록](../20261124-company-wiki-backend/README.md)). 직전 운영 화면의 회사 근거는 옛 `/api/company`(운영에서 404, 미등록)를 읽고 있었다.

## 실행 순서

1. 07:08:54 발주계획 cron 종료(`exit=0`, 기준일 11-23 complete) 확인. 일일 실행 프로세스 0, 실행 중·대기 C-2 실행 0건을 본 뒤 시작했다.
2. 이미지 빌드(실행 중 컨테이너에 영향 없음): `git archive HEAD web/frontend`로 뽑은 커밋 상태를 `docker/Dockerfile`의 frontend 단계와 같은 방식(`node:22-alpine`, `npm ci`, `npm run build`)으로 빌드해 직전 이미지의 `dist`를 교체했다. 사용한 파일은 [`Dockerfile.frontend-only`](Dockerfile.frontend-only).
3. 전체 백업: `BIDOPS_ENV=prod scripts/compose.sh run --rm --no-deps ro-backup` → `backups/postgres/full/bidops-20261123T220952Z.dump`(126,036,414 bytes, SHA-256 `c7f8712fdda573e2795e84827cc3b8eabff5bb191e5c1180dcd144d1face5a59`, `pg_restore -l` TABLE DATA 111개). 백업 전후 postgres 컨테이너 ID·생성 시각 동일.
4. 보존 태그: 이미지 `bidops:before-table-workbench-fe-20261124`(= 직전 이미지 `f1aa15161468`), git `before-table-workbench-fe-20261124`(= `dde4155`).
5. `.env`의 `BIDOPS_IMAGE` 한 줄만 `bidops:table-workbench-fe-20261124`로 바꿨다(나머지 줄의 해시 동일). `compose.sh config`로 web 이미지가 렌더된 것을 확인.
6. 07:10:22~07:10:30 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web` → healthy.

## 확인

- 헬스: `http://127.0.0.1:18788/api/health` 200, tailnet `http://42-ax.tail0ab8c5.ts.net:8188/api/health` 200(tailnet은 TCP 전달이라 http다).
- web 로그: `Exception in thread`·`Traceback` 0건, startup complete.
- 일일 자동 실행 스위치: `GET /api/order-plan-screening/daily-trigger` → `effective_enabled: true`, `c2-order-plan-screening-v6` (변경 없음).
- 운영 화면 읽기 확인: Chromium으로 22개 주소를 1280×800·1440×900·1920×1080에서 열었다. 브라우저에서 GET 이외 요청을 차단했고 **차단된 쓰기 0건**이다. 화면 예외 0, 가로 넘침 0. 4xx/5xx는 `/api/company-wiki` 404(위 알려진 결과)와, 배포 전에도 같던 `/api/company`·`/api/briefings/latest` 404, `/api/profile/*` 503(미등록 상태)뿐이다. 캡처는 [`shots/`](shots/)(`<폭>-<화면>.png`).
- 배포 전 검사(감독 실행): 화면 검사 1,088 통과·0 실패·18 건너뜀, 테마 대비 8 통과. 단계별 기록은 [수정안 §9](../../1123_astryx-templates/plan.md).

확인하지 않은 것: 운영에서의 쓰기 동작(추적 시작·보류·종료, 최종 결정 저장, 정책 스위치)은 눌러 보지 않았다. 같은 동작은 mock 데이터의 화면 검사로만 확인했다. 다음 날 cron은 이 이미지로 적재 CLI를 띄우는데(백엔드는 직전과 같다) 실제 cron 실행은 2026-11-25 아침이 처음이다.

## 롤백

`.env`의 `BIDOPS_IMAGE`를 `bidops:list-review-sheets-20261123`으로 되돌리고 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`을 실행한다. DB는 바꾸지 않았으므로 복원할 것이 없다.
