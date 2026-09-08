# 사전규격 개별 상세 ERP 적용 검증

2026-09-08 사용자 요청으로 `/pre-specs/:noticeId`를 기존 ERP 화면 방향에 맞춰 직접 설계·구현했다.
별도 작업 위임 없이 진행했으며 실제 서버 반영까지 승인된 범위다.

## 구현

- 본문과 보조 열 70:30. 사업명 20px, 그 아래 발주기관 16px/600, 본문 14px·요약 15px·보조 12px.
- 고정 헤더에 공고 식별·등급·추적 상태·기존 저장 액션·구역 이동을 둔다. 예산·마감·게시·첨부는
  헤더 아래 한 줄이며 본문은 개요·근거 → 문서 준비 → 추적 입력 순서다.
- 오른쪽에 검토 진행·이력·연결을 모으고 고정 입력의 기술 식별 정보를 접어 둔다. 자동 시작
  설명은 현재 ADR-0049의 심층 검토 시작까지 반영하며 사람의 추적·최종 결정과 분리한다.
- 구역 이동은 긴 제목과 고정 헤더의 실제 높이·스크롤 컨테이너 여백을 사용한다. 목록 복귀는
  기존 URL 필터를 보존한다. 새로운 상태 전이·모델 호출·API 계약은 만들지 않았다.
- 조회 실패·정본 부재를 등급 없음·추적 미선택·묶음 없음으로 바꾸지 않는다. 참조 실행·품질
  미측정 표식, 원문 locator 검증, 실제 0과 null, 기존 추적 저장 조건을 보존한다.

## 검증 결과

| 검사 | 결과 |
|---|---|
| `npm run build -- --outDir dist-prespec-detail` | TypeScript strict·production build 통과 |
| 작업 트리 `npx tsc -p tsconfig.app.json --noEmit --incremental --tsBuildInfoFile /tmp/bidops-prespec-detail-ui-20260908/main-typecheck.tsbuildinfo` | 통과. 기존 페이지별 개요 작업도 보존된 상태 |
| `npm run test:contrast` | 9 passed |
| 신규 ERP 상세 검사 | 6 passed: 두 지원 폭·긴 제목·구역 이동·필터 복귀·부분 실패·빈 결과·오류 재조회·로딩 |
| `PW_PORT=4193 PW_OUT_DIR=dist-prespec-detail npm run test:screens -- --workers=4` | **448 passed, 10 failed, 6 skipped** (4.6분) |
| 전체 실행 중 사전규격·문서 준비 | 44 passed, 목록의 기존 글자 굵기 기대 불일치 1 failed. 개별 상세 실패 없음 |
| 시각 확인 | 기본·긴 제목·문서·이력 열림은 두 폭, 빈 결과·로딩·오류·부분 실패는 1440px: 12개 캡처 |
| 실제 API 읽기 | 1280×800·1440×900, 공고 151·570의 개요와 문서·추적 입력: 반영 전·후 각각 8개 캡처. 브라우저 예외·쓰기 요청·가로 넘침 없음 |

전체 실패 중 9개는 직전 대시보드 검증과 같은 항목이다. `common-interactions` 3개(UC-02·회차 축·흡수 경로),
`route-context` 5개(queue/reviews와 내부 이동·상단 경로), `screen-semantics` 1개(마감 쿼리 보존)다.
추가 1개는 작업 트리에 이미 있던 **사전규격 목록 제목 굵기 검사**다. 이번에 쓰는 기존 검증 번들의
목록은 제목 굵기 400이고 해당 검사는 미반영 목록 수정의 600 이상을 기대한다. 목록 구현 변경과
페이지별 개요 기능은 이번 개별 상세 배포 범위에 포함하지 않았으며 검사를 삭제하거나 기대값을
완화하지 않았다. 전체 통과로 기록하지 않는다.

## 반영과 보존

- 검증 입력은 직전 대시보드 `frontend-source.tar.gz`에 개별 상세 TSX, 전용 CSS, 상세 검사를
  적용한 별도 사본이다. TypeScript 캐시·빌드·검사 결과는 임시 작업 디렉터리에 격리했다.
- `PreSpecDetailPage.tsx`에 이미 있던 `PageOverviewSection` import·렌더링은 작업 트리에
  보존했다. 현재 런타임에 반영되지 않은 해당 기능의 두 줄은 검증·배포 사본에서만 제외했다.
  나머지 backend·API/types·목록·데이터·운영 설정의 기존 변경은 반영하지 않았다.
- 2026-09-08 01:55:26 UTC, 기존 `bidops-web-1`에 검증된 정적 frontend를 assets 먼저,
  HTML 원자 교체 순서로 반영했다. 컨테이너·이미지·환경·DB·worker는 바뀌지 않았고 health는 healthy다.
- 번들 SHA-256: `d69e423e82d4e254953577f70482fd80d925dfbdfea9054a80de5e0853c72e03`.
  접속 주소는 `http://localhost:18787/pre-specs/151`이다.
- 정적 HTML 시각 기준·TSX/CSS·검증 번들·로그·캡처·이전 UI 복구 사본은 저장소 밖
  `/home/jechoi/design-previews/bidops-prespec-detail-ui-20260908/`에 보관한다.
- 컨테이너 재시작은 이 UI를 유지한다. 재생성 시에는 검증 소스를 다시 빌드하거나 번들을 반영해야 한다.
  검증용 4193 서버는 종료하며 기존 사용자 시안 서버는 유지한다. commit·push는 수행하지 않았다.
