# 프론트엔드 모듈 작업 규칙

## 책임

이 모듈은 React 관리자 화면, REST client와 TypeScript API model, 목록·상세 검토 상태, 실행 진행·실패 표현을 소유한다. 판정 계산, DB·파일 접근, model 호출, 알림 발송은 수행하지 않는다.

## 데이터 경계

- 서버 응답을 브라우저에서 재판정하거나 누락된 등급, 준비 상태, 지표, relation을 계산하지 않는다.
- DB, run 디렉터리, 첨부·객체 경로를 직접 읽지 않는다. 조회와 다운로드는 API URL만 사용한다.
- API error의 human message를 안정 code처럼 분기하지 않는다. endpoint 계열의 typed error shape와 code를 사용한다.
- 모델 provider를 브라우저에서 직접 호출하거나 key, profile, prompt를 bundle에 넣지 않는다.
- 프로필 화면은 API의 승인된 구조화 항목·`unknown`만 사용한다. filesystem source, source line, raw block·raw text, parser 예외을 type이나 UI에 추가하지 않는다.
- 회사 근거 화면은 `/api/company-wiki`가 주는 위키 페이지 본문과 프로필 값을 그대로 보여 주며, 마크다운을 HTML로 주입하지 않는다.
- TypeScript strict를 유지하고 API payload를 `any`로 우회하지 않는다.

## 상태 표현

- `값 없음`, `미확인`, `계산 불가`, 실제 0을 서로 다르게 표시한다.
- 실행의 품질 표식(`quality_status`)은 네 상태다. `측정 통과`·`참조 실행 · 품질 미측정`·`mock 참조`·`표식 없음`(값이 `null`). **참조 실행과 mock을 운영 완료처럼 보이게 하지 않고, `표식 없음`을 미측정이나 측정으로 바꾸지 않는다.** 이 셋은 성공도 실패도 아니므로 성공·실패 의미색을 쓰지 않는다.
- 사전규격의 `grade`가 `null`이면 `판정 없음`이고 출처는 `등급 출처 · 판정|정정|없음`으로 따로 적는다. 등급 없음을 특정 등급으로 접지 않는다. (2026-11-19부터 사전규격 화면은 등급을 그리지 않는다 — 다른 화면에서 등급을 보일 때의 규칙이다.)
- `auto_preparation_reason`은 서버가 정한 안전 코드다. 화면에 문장이 있는 코드만 번역하고 **모르는 코드는 그대로 보여 준다.** 임의로 다른 사유로 바꾸거나 숨기지 않는다.
- 적합성 등급, 참여 준비 상태, 추적 선택, 최종 Go/No-Go를 별도 필드·라벨·action으로 표시한다.
- 성공, 부분 성공, 실패, 중단, 사람 검토 대기를 서로 구분하고 failure artifact나 재시작 가능 여부를 숨기지 않는다.
- 색만으로 등급, deadline, 차단, delta를 전달하지 않고 문자·아이콘·구조적 표시를 함께 제공한다.
- 담당자 이름은 저장 전에 요구할 수 있지만 로그인이나 신원 인증으로 표현하지 않는다.
- 외부 모델 실행은 미리보기·대상 모델·건별 승인 없이 시작하지 않는다. 사전규격 화면의 기존 심층 검토·사용자 요청 Luna(ADR-0069) 진입점은 2026-11-19에 내려갔다 — 회사 데모 경로에 남은 요청 화면만 승인된 문서·회사 근거와 같은 실행의 검증 결과를 전송한다. 입력이나 원문 대조 설정을 바꾸면 기존 미리보기 승인을 폐기한다. 담당자 이름은 감사 표식이다.

## 검토 흐름

- 목록 필터는 URL과 동기화하고 선택한 항목, 상세 scroll, 저장 후 이동을 예측 가능하게 유지한다.
- 발주계획·사전규격 목록은 active 행과 checked 집합을 분리한다. 행 클릭·Enter·↑↓는
  active만 바꾸고, native checkbox 또는 활성 행의 plain Space만 checked를 한 번 토글한다.
  각 목록은 서로 다른 `sessionStorage` key를 사용해 페이지 이동·새로고침·같은 탭 상세
  왕복에서 선택을 복원하며, 탭·계정 간 동기화나 localStorage를 사용하지 않는다.
- 적용된 의미 필터(검색 적용값 포함)가 바뀌면 selection generation을 올리고 선택을
  비운다. offset·정렬 변경·query refetch·페이지 경계는 선택을 유지한다. 사전규격 상세
  재진입 때만 현재 탭이 마지막으로 관측한 정렬 metadata로 새 순서를 만들며, 게시·마감
  timestamp는 timezone offset과 microsecond를 보존하고 null/PK tie-break를 적용한다.
- 일괄 추적은 기존 단건 PATCH를 반복 호출하지 않는다. preview 후 공통 actor/reason을
  확인하고, 서버가 잠금 뒤 미선택 owner만 계속 추적으로 전환한다. 계속 추적·보류·종료는
  상태별 제외다. 일괄 추적 종료(ADR-0063)는 같은 흐름·같은 다이얼로그(`mode="end"`)로 미선택
  owner만 종료로 전환하고 한 요청은 200건까지다(`ORDER_PLAN_BULK_END_MAX_SELECTION`, 화면이
  먼저 막는다). 저장한 대기 요청에는 작업 종류(`action`)를 함께 묶어 같은 request ID가 다른
  endpoint로 가지 않게 하며, 열린 창의 mode보다 저장된 action이 이긴다. bulk에는
  hold/select-all을 추가하지 않는다. 최종 receipt가
  확인되지 않으면 같은 request ID로 확인하고, 사람이 실패 항목을 확인한 뒤 실패 plan만
  새 request ID로 재시도한다. 성공 receipt가 단건 초안이나 active 이동을 바꾸지 않는다.
- 상세 순회는 opaque `selection_review` token으로 고정하고 route notice ID를 기준으로
  위치·건수·양끝 disabled를 계산한다. navigation shell은 본문 loading·404·5xx·
  source/projection 오류에도 남기며 오류 항목을 자동으로 건너뛰거나 선택에서 삭제하지
  않는다. retry는 같은 항목에 머물고 목록 복귀 URL은 list filter/sort/offset만 보존한다.
- `sessionStorage` read/write 실패는 복원 가능하다고 표시하지 않는다. bulk 전송과 선택
  순회 시작을 막고 원인·단건 경로를 안내하되, 기존 단건 상세와 단건 tracking PATCH는
  계속 사용할 수 있게 한다.
- 사전규격 목록의 등급·개요 상태·추적 결정·자동 준비·업무 보기는 모두 서버가 페이지
  분할 전에 적용한다. 브라우저에서 이미 받은 페이지만 좁히지 않는다. 보기 건수는
  활성 보기 조건만 제외한 나머지 필터 기준이며 목록 total은 활성 보기까지 포함한다.
  허용값 밖의 UI 필터는 전체로 복원하며 의미 필터가 바뀌면 offset과 선택을 초기화한다.
  기본 진입은 검토할 항목이고 회차는 보조 필터다. 실패·취소 개요와 멈춘 문서 준비는 `확인 필요` 보기다(2026-11-19). 사전규격 화면은 등급을 그리지 않는다. 최근 수집은 한국 시간 관측일을
  기준으로 하며, 개요 미시작과 실제 실행 대기는 구분한다.
- 사전규격 목록도 발주계획과 같이 ↑↓로 행을 옮기고(경계에서 페이지를 넘긴다)
  `Ctrl/Cmd+Enter`로 상세 검토를 열며, 저장하지 않은 추적 입력이 있으면 이탈 확인이 먼저다.
  행 컴포넌트는 `useRowKeyboardNavigation`의 `rowProps`(`data-row-key`·roving `tabIndex`)를
  **그대로 행 요소까지 내려야** 한다. 내리지 않으면 선택만 움직이고 초점은 조용히 멈춰 있는다.
- 사전규격 상세의 자동 준비 단계·문서 준비 패널·처리 이력·기술 정보는 맨 아래 접힌 `처리 상태·기술 정보` 한 구역
  안에 있다(2026-11-21). 기본 열림은 `lib/preSpecProcessDefaultOpen.ts` 하나가 정하며 문제가 있으면 열린다. 문서 준비
  패널은 상태 요약 한 줄과 `문서 준비 열기/닫기` 토글이고 기본값은 `lib/documentPanelDefaultOpen.ts`가 정한다.
  Astryx `Collapsible`을 쓰지 않는다 — `display:none`으로 감추면 패널 조작과 폴링이 막힌다.
- 사전규격 상세 본문 구역은 사실 줄 → 사업 개요와 주요 과업 → (값이 있을 때만) 회사 관련성 참고 → 원문·첨부 →
  처리 상태·기술 정보 순이다. 발주계획 후보 구역은 후보가 1건 이상일 때만 보인다. 꺼진 기능 안내(RL 분석·회사
  적합성)는 처리 상태·기술 정보 안에서 보인다. 주장마다 쪽 링크를 붙이고 주장별 원문 위치 목록은 두지 않는다.
- 사전규격 상세 본문·패널 헤더 안쪽·하단 띠 안쪽은 읽기 폭 1040px로 패널 가운데에 둔다. route metadata
  `detailReadingWidth`가 `.app-content[data-reading-width="detail"]`을 달며 다른 화면에는 쓰지 않는다(ADR-0076 결정 13).
- 계약에 없는 값을 화면이 채우지 않는다. 보고서의 segment 패널은 묶음에서 문서들의 `structure_id`를 얻을 endpoint가 없어 **선택된 근거가 가리키는 문서 하나**만 보여 주며, 그 사실을 문장으로 적는다. segment에는 wire 상 제목이 없으므로(원문 text를 싣지 않기로 한 결정의 결과) ordinal·taxonomy label·요구사항 id·`block_key`·page 링크만 보이고 제목이 없는 이유를 적는다.
- 자동 연결 실행과 단계별 수동 실행은 같은 execution 상태 컴포넌트를 사용한다. 별도 상태 의미를 복제하지 않는다.
- 문서 준비 화면은 upload, scan, convert, structure, bundle confirm을 구분하고 실패 stage와 안전한 retry action을 보여야 한다.
- 심층 검토 실패 재시작은 기존 attempt를 덮지 않으며 새 attempt가 생긴다는 점을 확인시킨다.
- 향후 opportunity 화면은 plan, pre-spec, bid의 공식 연결과 사람 확인 대기 후보를 시각적으로 구분한다.
- 사전규격 보고서 뒤 `계속 추적|보류|종료`와 입찰공고 뒤 최종 `Go/No-Go`를 같은 버튼 집합으로 재사용하지 않는다. 사전규격 상세의 하단 결정 띠는 분석 전에는 `추적 시작`만 두고, 분석 결과를 보여 주는 화면(mock 빌드 전용)에서만 세 상태를 고른다(`docs/business-rules.md`).
- 사업 추적·최종 Go/No-Go 목록도 같은 `useRowKeyboardNavigation`으로 ↑↓ 행 이동을 갖는다
  (경계에서 페이지를 넘긴다). 두 화면은 Astryx `Table`을 그대로 쓰므로 `rowProps`는 표의
  **첫 열 버튼**(`.opportunity-row-business`·`.gng-row`)이 받고 키 리스너는 표의 스크롤
  영역(`.opportunity-table-scroll`·`.gng-table-scroll`)이 진다. 사업 추적은 저장하지 않은
  입력이 있으면 이탈 확인이 먼저다. 두 화면에 `Ctrl/Cmd+Enter` 단축키는 없다.
- 발주계획 목록은 ↑↓로 행을 옮기고(경계에서 페이지를 넘긴다) `Ctrl/Cmd+Enter`로 추적을 시작한다. 준비되지 않았으면 저장하지 않고 무엇이 빠졌는지 안내한다. `직전 사유 다시 쓰기`는 사유 입력을 채워 줄 뿐이며, 드롭다운은 여전히 빈 값에서 시작하고 저장에 성공하면 초기화한다(사유를 자동으로 채워 저장하지 않는다).

## UI 패턴

- TanStack Query로 서버 상태를 조회하고 mutation 성공 뒤 영향 query만 무효화한다.
- 색은 `bidops` 테마(무드보드 파생, ADR-0048 → ADR-0073·ADR-0076 개정)가 정본이다. 화면은 토큰만 읽고 `:root`나 화면 CSS에서 `--color-*`를 재정의하지 않는다. 유일한 예외는 `styles/shell-relaxed.css`의 이행용 token bridge이며 새 색 값을 만들지 않는다. 색을 바꾸려면 `src/themes/bidops/bidopsTheme.ts`를 고치고 `astryx theme build`를 다시 돌린다.
- 셸(ADR-0076, 2026-11-19): 바탕 위 흰 패널 한 장이고 화면 제목은 패널 헤더가 그린다. 화면은 `usePageHeader`
  (`components/shell/PageHeaderContext.tsx`)로 화면 이름·문장형 제목·설명(·상태 표식·사실 줄)을 **문자열로만** 올리고,
  액션은 `PageHeaderActions`, 보기 탭·검색 줄은 `PageHeaderTabs` portal로, 패널 아래 결정 입력은 `PageFooterBar` portal(셸의 고정 슬롯 `#page-footer`)로 보낸다. 슬롯이 비면 자리를 차지하지 않는다. **슬롯은 추적 결정 전용이며 개요 범위 확정 같은 다른 할 일을 넣지 않는다.** 페이지에 `<h1>`이나 제목 줄을 다시
  두지 않는다. 설명에는 고정 설명·주의 문구를 넣지 않고 그 순간의 데이터를 말하는 문장만 넣는다(2026-11-20 사용자
  요청, ADR-0076 결정 12 — 경계 문장은 본문 결정 영역의 보조 문구가 진다). 문장의 숫자는 이미 받은 값(목록 total·탭 건수)으로만 만들고, 없으면 숫자 없는 문장을 쓴다. 목록|상세
  화면은 route metadata `canvas: "flush"`로 패널 끝까지 채우고 목록은 38%다.
- 패널 안에 그림자 카드·카드 속 카드·밑줄 탭·옛 강조색(초록 띠) 상자를 새로 두지 않는다. 구분은 여백, 옅은 선
  (`--bo-line-soft`), fill 채움(`--color-background-muted`)으로 한다. 선택 행은 fill 채움이고 브랜드 옅은 채움은 `추적 중`
  같은 상태 표식 전용이다. 마감·단계·건수는 표식이 아니라 글자, 숫자는 먹색, 화면당 주 버튼 하나. 재구성 화면의 글자·조작
  높이는 `--bo-k-*` 단(typography.css)을 쓴다. 사용자 문구는 해요체이되 값 없음/미확인/계산 불가/0과 사람 결정 경계의 뜻은
  바꾸지 않는다.
- 담당자 이름은 사이드바 담당자 칸과 같은 한 값(`bidops.actorName`, `useRememberedActorName`)을 쓴다. 화면별로 따로 기억하지
  않는다. 감사 표식이며 인증이 아니다. 브리핑·발주계획 결정 영역과 사전규격 상세 하단 결정 띠(2026-11-21)는 입력 칸을 두지 않고, 이름이 비면 안내와 함께
  `requestActorInput()`으로 사이드바 칸을 열어 초점을 옮긴다(저장 전 이름 요구는 그대로, 2026-11-20).
- 패널 헤더의 수집 상태는 `CollectionStatus`(`GET /api/daily-collection-status`)만 쓴다. 기준일·상태를 화면에서 다시 계산하지
  않고, `complete`만 "수집 완료"다. 나머지는 사실대로 쓰고 실행 상태 링크를 단다. 조회 실패는 숨기지 않는다.
- 패널 본문 글자·조작 크기는 `styles/panel-density.css`가 옛 단 토큰(`--bo-type-*`, Astryx `--font-size-*`·`--size-element-*`)을
  k 단으로 다시 가리켜 맞춘다(ADR-0076 결정 11). 새 화면 CSS는 12px·28~32px 단추·패널 안 테두리 상자를 새로 만들지 않고
  `--bo-k-*`를 직접 쓴다.
- 사용자 문구(화면·대화상자·토스트·빈 상태·오류 안내)는 해요체다. 제목은 마침표 없이, 본문은 마침표로 끝낸다. 서버가 준
  문자열·계약 값·감사 기록에 저장되는 값은 바꾸지 않는다(2026-11-20 일괄 전환).
- Tailwind `@theme`에 디자인 시스템과 이름이 겹치는 `--color-*`를 추가하지 않는다. `@theme`은 `:root`로 방출돼 `@layer astryx-theme`을 이기므로 테마 값이 조용히 무시된다([engineering-notes.md](../../docs/engineering-notes.md)).
- 공고 목록과 상세 정보 밀도를 유지한다. 마케팅식 큰 여백, 장식 아이콘, gradient, glass effect를 사용하지 않는다.
- 긴 한글 제목, 표의 긴 요구사항, keyboard focus, empty/loading/error 상태를 설계한다.
  디자인 검수는 기본 `1920x1080`, 작은 데스크톱 `1440x900`, 최소 노트북 `1280x800`에서 하며, 제품 폭은 1280~1920px이다. 모바일·
  태블릿 레이아웃을 만들지 않는다(ADR-0047). 1280px 미만은 가로 스크롤로 둔다.

## 검증

```bash
cd web/frontend
npm run build              # tsc -b + vite build
npm run test:contrast      # 테마 대비 게이트 (ADR-0048)
npm run test:screens       # 화면 게이트 — 의미(한 폭) + 구조(세 폭)
npm run test:design        # 셸 구조·색·치수만 따로
npm run test:pixel         # 기준 이미지 대조 — 게이트 아님
```

TypeScript strict, production bundle, 기본 필터, null/0 표시, 부분 실패, review 저장과 다음 이동, API 오류, empty/loading, 긴 한글, keyboard focus를 확인한다. 외부 font network 없이 결과가 재현되어야 한다.

화면 검사는 의미·구조·픽셀 세 층이고 층마다 실패의 뜻이 다르다. 표와 각 층의 규칙은 [`docs/standards.md`](../../docs/standards.md)의 "화면 검사의 세 층"에 있다. **게이트는 `test:screens`까지이고 픽셀 층은 게이트가 아니다.** 픽셀이 깨졌다는 것은 "화면이 틀렸다"가 아니라 "지난 기준선과 달라졌다"는 뜻이므로, 의도한 변경이면 `npm run test:pixel:update`로 갈아 끼우고 **사유·영향 화면·승인자를 기록에 남긴다.**
