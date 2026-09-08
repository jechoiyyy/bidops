# 사전규격 상세: 왼쪽 정보·오른쪽 추적 결정

2026-09-08 사용자가 고정 상세 헤더와 떨어진 입력 위치를 정정했다. 지정한 로컬 시장 상세
`http://localhost:5173/markets/kbo-2026-08-01-ssg-kia`를 읽기 전용으로 확인한 뒤 같은 배치로
직접 구현·반영했다. 기존 ERP 팔레트·셸·공고 내용·업무 규칙은 유지한다.

## 변경

- 왼쪽 열에 일반 흐름의 공고 헤더 → 기본 정보 2×2 → 개요·근거 → 문서 준비 → 진행·이력·연결.
- 오른쪽 360px 패널에 현재 추적 상태, 계속 추적 선택, 사유, 담당자와 저장 버튼을 함께 배치.
  헤더는 스크롤과 함께 사라지고 이 패널만 sticky다. 높이가 커지면 입력 영역만 스크롤하고
  저장 버튼은 패널 바닥에 남는다. 두 열 간격은 16px이며 기관은 제목 아래 16px/600을 유지한다.
- 기존 `TrackingDecisionControl`과 저장 조건을 재사용한다. 헤더의 저장·입력으로 이동 버튼과
  그 동선을 제거했다. 원문/구역 이동 중 초안을 유지하고 저장 후 기존 캐시 갱신·초기화를 따른다.
- notice가 바뀌면 입력 컴포넌트도 바뀌도록 notice ID를 key로 둔다. 미저장 이동 보호, 승계 건의
  읽기 전용 상태, 미연결 저장 차단, null/0·품질 표식·검증 경고를 보존한다.

## 검증

| 검사 | 결과 |
|---|---|
| 검증 소스 `npm run build -- --outDir dist-decision-rail` | TypeScript strict·production build 통과 |
| 작업 트리 TypeScript `--noEmit` (임시 tsbuildinfo 사용) | 통과 |
| `npm run test:contrast` | 9 passed |
| `PW_PORT=4193 PW_OUT_DIR=dist-decision-rail npm run test:screens -- pre-specs.spec.ts --grep 'ERP 상세\|오른쪽에서\|스크롤 없이' --workers=2` | 8 passed |
| `PW_PORT=4193 PW_OUT_DIR=dist-decision-rail npm run test:screens -- --workers=4` | **448 passed, 10 failed, 6 skipped** (4.7분) |
| 두 지원 폭의 시각·동작 | 1280×800·1440×900. 헤더가 사라진 상태에서 입력·저장 가능, 구역 이동 중 초안 보존 및 실제 mock PATCH 성공 확인. 관련 상태 캡처 12개 |
| 실제 API 읽기 | 반영 전후 각 8개 화면. 공고 151·570과 문서·스크롤 하단 확인. 브라우저 예외·쓰기 요청·가로 넘침 없음 |

전체 미통과 10개는 [직전 검증](20260908-prespec-detail-erp-ui.md)과 같다. 공통 상호작용 3개,
회차/경로 맥락 5개, 마감 쿼리 의미 검사 1개, 별도로 작업 중인 미반영 목록 제목 굵기 검사 1개다.
이번 변경으로 새 실패는 생기지 않았으며 전체 통과로 기록하지 않는다. 시안 이미지를 자동
기준선으로 덮어쓰지 않았다.

## 반영·재현

- 2026-09-08 02:19:17 UTC, `bidops-web-1`의 정적 frontend를 반영했다. 주소는
  `http://localhost:18787/pre-specs/151`. 컨테이너·이미지·환경·DB·worker는 그대로이며 health는 healthy다.
- 번들 SHA-256: `2958026b0c2ec5357704ac7a5d1539030e6f605557ac933da70344cd49b9c51c`.
  반영 전 HTML 해시를 검사하고 staging 후 교체 직전에도 대조해 다른 UI 변경을 덮지 않도록 했다.
- 직전 검증 frontend source에 상세 TSX·전용 CSS·관련 검사 세 경로만 적용했다. 작업 트리의
  기존 `PageOverviewSection` import·렌더링은 보존하고 배포 사본에서만 제외한다. 미반영
  backend·API·목록 수정은 이번 UI에 섞지 않는다.
- HTML·소스·번들·로그·캡처·복구 사본은 저장소 밖
  `/home/jechoi/design-previews/bidops-prespec-decision-rail-20260908/`에 보관한다.
  HTML은 가상 데이터의 정적 시각 기준이며 실제 API 결과·품질 근거가 아니다.
- 검증용 4193 서버는 종료한다. 참고 서비스 5173과 사용자 시안 서버는 건드리지 않는다.
  현재 컨테이너 재시작은 UI를 유지하며 컨테이너 재생성은 검증 소스 재빌드 또는 번들 반영이 필요하다.
  commit·push는 수행하지 않았다.
