# 회사 근거 개요 요약 대시보드 — 운영·포트폴리오 반영 (2026-11-25)

사용자가 시안 3개 중 A(요약 대시보드)를 골라 구현과 운영·포트폴리오 반영을 요청했다("A안으로 구현하고 운영, 포폴에 적용해줘"). 화면 하나의 프런트엔드 변경이며 API·DB·worker 변경은 없다.

| 항목 | 값 |
|---|---|
| 코드 | `00513dc`(origin/main `c30534d` 위 1개 커밋, 브랜치 `feat/company-overview-dashboard`, 클론 `/Users/temp/orca/bidops-company-overview`). 2026-11-26 사용자 요청으로 main에 fast-forward 병합·push |
| 화면 | `WikiOverview.tsx`(새 파일, `WikiViews.tsx`에서 옮김)·`profileOverview.ts`(묶음 규칙)·`company-wiki.css` `.wiki-ov*` |
| 내용 | 회사 정보 줄과 프로필 값 확인 수준 막대, 카드(근거 자료 범위·매출액·기술 인력·지역별 상주, 값이 있을 때만), 등록·인증 타일(경로 앞 두 마디가 같은 값을 한 칸에, 묶음 이름은 이름표 공통 앞부분), 결격 사유, 입찰 방침, 사업 분야·자체 솔루션, 기술·경험, 최근 넣은 실적, 접힌 `프로필 값 전체 보기`(구역별 표와 확인 수준의 뜻). 빈 문자열 값은 `값 없음`으로 읽는다 |
| 검사 | `tsc -b`; Playwright app `company-wiki.spec.ts`(13, 개요 검사 갱신 + 묶음·카드 검사 추가)·`company-ground-truth`·`company-wiki-ingest`·`common-interactions`·`company-workspace` 합계 65 통과; 세 폭 `overflow.spec.ts` 회사 위키 3 통과; `test:contrast` 8 통과; 실제 데이터(포트폴리오 API)로 1280·1440·1920 가로 넘침 없음 |
| 운영 web | `bidops:main-20261125-00513dc`(클린 `git archive` 트리, `docker build --platform linux/amd64 -f docker/Dockerfile`). `.env` `BIDOPS_IMAGE` 교체 후 `up -d --no-deps --no-build --force-recreate web`. analysis-worker는 `main-20261125-5e8f7a1` 그대로(백엔드 코드 동일, 재생성 시 새 이미지로 바뀜) |
| 운영 백업·되돌리기 | `backups/postgres/full/bidops-20261125T143926Z.dump`(`run --rm --no-deps ro-backup`, postgres 재생성 없음). 되돌리기: `.env` `BIDOPS_IMAGE=bidops:before-company-overview-20261125-web`(= `main-20261125-5e8f7a1`) 후 web 재생성 |
| 포트폴리오 web | `bidops:portfolio-20261125-3ea6126` = `portfolio/deploy-20261125`(`1a0adcc`, 병합 클론) + 같은 변경 cherry-pick `3ea6126`(브랜치 `portfolio/company-overview-20261125`). `BIDOPS_PORTFOLIO_ANALYSIS=1`·`BIDOPS_PORTFOLIO_FROZEN_NOW=2026-11-24T13:35:00+09:00` 기반 이미지 `bidops:portfolio-base-20261125-3ea6126` + `web-frozen-clock.Dockerfile` 층. `bidops-portfolio-build`에서 `docker/portfolio/compose up -d --no-deps --no-build --force-recreate web` |
| 포트폴리오 되돌리기 | `BIDOPS_PORTFOLIO_IMAGE=bidops:portfolio-before-company-overview-20261125`(= `portfolio-20261125-brand`)로 같은 명령 |
| 반영 확인 | 두 web healthy. 운영 `127.0.0.1:18788/company`·공개 포트폴리오 `/company?view=overview`를 세 폭에서 열어 새 개요 확인. 404 두 건(`/api/company-wiki/ingests` 넣기 꺼짐, 운영 `/api/company` 회사 미등록)은 변경 전과 같은 응답. 포트폴리오 번들 구성(JS 85개, 분석 화면 포함)과 4186 분석 화면 정상 |

운영 checkout(`/Users/temp/orca/bidops`)은 다른 작업의 미커밋 변경 때문에 pull하지 않았다. 시안 파일과 실제 데이터 캡처는 회사 값이 들어 있어 공개 저장소에 넣지 않았다(`bidops-portfolio-build/docs/1125_company-overview/mockups/`, 미추적).
