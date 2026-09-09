# 승인 ERP 판정 기준·실행 상태 구현 검증

검증일: 2026-09-08. 사용자 승인일: 2026-09-07.

승인된 `bidops-criteria-runstatus-erp-20260907` HTML·원본 TSX/CSS·상태별 캡처로
판정 기준(회사 프로필·판정 정책·품질 게이트·검증 지표)과 실행 상태(수집 실행·첨부 확보·
상시 운영·산출물 감사 로그)를 구현했다. 실제 업무 값은 기존 API로 읽는다.
기존 생성·리뷰·후보 지정·활성화·중단·예약·포털 등록 계약을 유지한다.

## 위임과 통합 범위

- `claude -p --model claude-opus-5 --effort high` 두 프로세스에 파일 소유 범위를 나누어
  병렬 위임했다. 실제 모델의 init 응답도 확인했다.
- 판정 기준 세션: `8bfe748d-4b59-44f3-953d-9f7e9cda2167`.
- 실행 상태 세션: `42fd3bda-5cc0-4223-82b6-eb4e6dbd2c2b`.
- 같은 세션을 이어 사용해 검토 사항을 수정했다. 실행 상태 작업의 반복 전체 검사는 부모가
  중단하고 남은 시안 차이로 범위를 좁혔다. 최종 전체 검사는 통합 담당자가 수행했다.
- 통합 담당자는 공통 프레임·테스트·두 관리 화면의 한국어 카탈로그 범위를 조정하고,
  오류가 0건처럼 보이던 프로필 상태, 확인창의 대상 고정, 포털 대화상자의 테마를 확인했다.
- 작업 시작 때 이미 변경되거나 추가된 122개 파일의 SHA-256을 보존했다. 기존 API·type·
  사전규격 개요 작업 등 frontend 8개 파일은 배포용 빌드에 포함하지 않았다.
- 배포 입력은 `6c607f577c06fbaa4491969ca051c208ed4ade8f`의 frontend에 이번 변경 54개
  경로만 적용한 임시 복사본이다. TypeScript 캐시는 해당 복사본에 격리했다.

## 검증 결과

| 검사 | 결과 |
|---|---|
| `npm run build -- --outDir dist-admin-verify` | TypeScript strict·Vite production build 통과 |
| `npm run test:contrast` | 9 passed |
| `PW_PORT=4192 PW_OUT_DIR=dist-admin-verify npm run test:screens -- --workers=4` | **423 passed, 11 failed, 6 skipped** |
| 위 전체 실행 중 두 화면 전용·통합 검사 | `criteria.spec.ts` 46, `run-status.spec.ts` 39, `admin-workspace-consistency.spec.ts` 4: **89 passed** |
| 전체 검사 이후 첨부 안내 문구 변경 | API 계약이라는 표현을 사용자 안내로 변경. 재빌드와 해당 첨부 검사 1 passed |
| 시안 대조 | 1280×800·1440×900, 8개 탭의 최종 캡처 16개·실측 통과 |
| 확인창·오류 상태 추가 확인 | 상시 운영 확인창 테마·본문 14px·제목 20px·하단 버튼 가시성, 프로필 파싱 실패의 건수 미확인 |
| 반영 후 실제 API 읽기 | 8개 탭×두 폭 16개 화면: HTTP 200, API 실패·브라우저 예외·가로 넘침 없음. 쓰기 요청 없음 |

시안에서 임시 도구 모음 40px만 제외했다. 실제 탭 37px, 요약 줄 49px,
하단 액션 57px, 목록 제목 15px/600, 하단 버튼 14px를 맞췄다. 목록·상세 비율은
38:62이고 본문 스크롤이 하단 액션을 밀어내지 않는다. 실행 상태는 수집 회차 완료와
판정 실행 상태를 구분하며, 처리 건수 네 항목은 1280 첫 화면에서 모두 보인다.

확인창 동작과 mutation 검사는 가로챈 합성 API로 수행했다. 실제 정책 활성화·실행 시작·중단·
예약·포털 등록·DB migration·모델 호출을 수행한 증거가 아니다.

## 전체 검사에서 남은 기존 실패

직전 네 ERP 화면의 검증 기록에서 알려진 11개 항목과 테스트 이름을 대조해 일치함을 확인했다.
새 두 관리 화면의 실패는 없으며 전체 화면 게이트가 green이라는 뜻은 아니다.

- `common-interactions.spec.ts`: UC-02 상태 문구, 대시보드 회차 선택기, 사이드바 밖 회차 축,
  흡수한 옛 경로: 4개.
- `route-context.spec.ts`: dashboard·queue list·queue detail·reviews 맥락, SPA 내부 link,
  queue detail 상단 경로: 6개.
- `screen-semantics.spec.ts`: 흡수한 마감·감사 경로의 쿼리 보존: 1개.

## 실제 API의 한계

C-1 `ScreeningExecutionResponse`·`RunSummary`에는 `quality_status`가 없어 **품질 표식 미제공**으로
표시한다. 측정 통과·참조 실행·mock 참조 어느 상태로도 추정하지 않는다. 실행 목록은 최근
50건 조회 범위를 밝히며, 검증 지표의 회차별 이력은 최근 5개와 명시적으로 선택한 회차를 읽는다.
첨부 큐에 없는 문서 종류, 산출물에 없는 크기·생성 시각, 프로필에 없는 절 설명을 만들지 않았다.

## 서버 반영과 보관

- 서비스: `http://100.123.160.59:18787/criteria`, `/run-status`.
- 승인 시안: `http://100.123.160.59:4189/criteria.html`, `/run-status.html` 유지.
- 기존 `bidops-web-1`에 검증된 정적 자산을 먼저 복사하고 HTML 진입점을 원자적으로 교체했다.
  기존 자산과 복구용 사본을 보존했다. 컨테이너·이미지·환경변수·DB·worker는 변경하지 않았다.
- bundle SHA-256: `4cd4be3a33a8a0bb039596d6e56466d8797015d7ae8e162aed8614322c55b3ec`.
- 결과·최종 source manifest·빌드·테스트 로그·시안/구현 캡처·복구용 정적 파일은
  `/home/jechoi/design-previews/bidops-admin-ui-implementation-20260908/`에 보관한다.
- 현재 컨테이너의 재시작은 정적 파일을 유지한다. 컨테이너를 재생성할 때는 해당 소스를
  빌드하거나 검증된 bundle을 다시 반영해야 한다. 새 commit·push는 수행하지 않았다.
