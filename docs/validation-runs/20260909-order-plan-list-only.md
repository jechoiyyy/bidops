# 발주계획 별도 상세페이지 제거

2026-09-09 사용자 요청으로 standalone `OrderPlanDetailPage`를 제거했다.
검토목록의 오른쪽 상세 패널, 추적 결정, 사람 판단 수정과 현재 실행의 수정본 이력을 사용한다.
사업 추적의 발주계획 링크는 `?selected=<pk>`로 열고, 기존 `/order-plans/:pk`도 목록으로 연결한다.
회차가 없는 링크는 API의 관측 회차로 해석한다. 가려진 항목은 필터를 해제하고 해당 페이지로
이동하며, 없는 항목은 다른 행으로 대체하지 않는다. 백엔드·데이터·판정 계약은 바꾸지 않았다.

## 검증

- production build 및 TypeScript 검사 통과, 색 대비 9개 통과.
- `PW_PORT=4299 PW_OUT_DIR=/tmp/bidops-plan-list-build/dist npm run test:screens -- --workers=4`:
  498개 통과, 5개 skip, 2개 실패.
  수정본 이력 primitive 부재는 목록 대화상자로 기능을 옮겨 해결했다.
  평가 수치 누락 검사의 탭 전환 시점 실패는 해당 검사 3회 재실행에서 모두 통과했다.
- 최종 수정 뒤 order-plans·review-primitives·common-interactions 세 spec: 69개 통과,
  기존 마감 경로의 sort 값 검사 1개 실패. 이 검사는 단독 3회 모두 통과했다.
  최종 이력 표시와 발주계획 연결·저장·키보드 검사는 통과했다.
- 실제 서버의 데이터를 읽은 1280×800·1440×900 검사에서 기존 주소와 직접 선택 링크가
  정확한 항목으로 연결됨을 확인했다. 기본 필터에 가려진 항목과 offset=1000 항목도 확인했다.
- 링크 초기화 중 주소 갱신 전에 로컬 초기화 상태를 해제하면 첫 행 선택 effect가 이전
  URL로 덮어쓰는 문제를 실제 데이터로 재현했다. 수정한 URL이 반영된 뒤 초기화를 끝내도록
  보정하고 재검증했다.
- 픽셀 기준 이미지는 변경하지 않았다. 전체 스위트를 최종 수정 후 모두 통과했다고
  주장하지 않으며, 위 전체 실행과 최종 관련 검사 범위를 구분한다.

## 배포

`bidops-plan-list-only:20260909`로 web만 재생성했다. 기존 환경변수·mount·network·port를
보존했다. 실행 로그와 rollback 설정은
`/home/jechoi/.local/state/bidops/deployments/plan-list-only-7apwm0v0/`에 보관한다.

최종 clean build의 71개 파일은 검사에 사용한 빌드의 동일 파일과 바이트가 일치했다.
재배포 뒤 HTTP 응답 hash도 모두 일치했고 health는 healthy다. 삭제한 상세페이지의
lazy chunk는 최종 산출물에 없다.
