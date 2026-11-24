# 2026-11-24 오늘 할 일 일일 수집 여백 · 사이드바 최종 Go/No-Go 아이콘 운영 반영

사용자 요청("운영에도 반영해줘")으로 프론트엔드 두 파일만 바꿔 운영 web을 교체한 기록이다.

| 항목 | 값 |
|---|---|
| 코드 | main `70df62a` (운영 직전 `a7af6f4` 대비 `Sidebar.tsx`·`dashboard-erp.css` 두 파일만 다름) |
| 이미지 | `bidops:main-20261124-70df62a` (깨끗한 클론에서 `docker build --platform linux/amd64 -f docker/Dockerfile`) |
| 교체 | web만 (`up -d --no-deps --no-build --force-recreate web`). analysis-worker·첨부 worker는 `bidops:main-20261124-ab08343` 그대로 |
| DB | 변경 없음 (migration 없음). 배포 전 백업 `backups/postgres/full/bidops-20261124T052847Z.dump` |
| 되돌리기 | `.env` `BIDOPS_IMAGE=bidops:wiki-citations-a7af6f4`(태그 `bidops:before-gonogo-icon-20261124`) 후 web 재생성 |

## 변경

- `.dash-page .daily-collection`: 공통 규칙(`panel-density.css`)이 이 묶음을 옅은 채움 블록으로 바꾸는데 대시보드 규칙이 좌우 안쪽 여백을 0으로 둬서 글자가 채움 가장자리에 붙었다. 안쪽 여백 `var(--spacing-2) var(--spacing-4)`를 준다.
- 사이드바 하위 항목 `최종 Go/No-Go`에 상단 바와 같은 ClipboardCheck 모양 아이콘을 넣었다. 들여쓰기는 그대로다.

## 확인

- `tsc --noEmit` 통과.
- 운영(127.0.0.1:18788) 1280·1440·1920에서 `daily-collection` 계산 padding `8px 16px`, Go/No-Go 메뉴 svg 1개, 포트폴리오 전용 안내(`.sidebar-snapshot`) 0개 — 3/3 통과, 1440 캡처 직접 확인.
- 화면 변경 배포이며 기능 활성화나 품질 판정과 무관하다.
