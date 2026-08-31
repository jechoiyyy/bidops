# BidOps UI/UX 수정 계획

- 작성일: 2026-08-31
- 대상: `web/frontend`와 화면이 소비하는 REST 계약
- 목적: 현재 화면을 `발주계획 조기 탐색 → 사전규격 개요 검토 → 문서 준비 → 심층 검토 → 입찰공고 변경 비교 → 사람 Go/No-Go` 업무 흐름으로 연결한다.
- 후속 계획: [UI/UX 고도화 계획](./2026-08-31-ui-ux-advancement-plan.md)

이 문서는 2026-08-31 코드·문서·브라우저 점검과 mock API 기반 사용 시나리오 검증 결과를 구현 가능한 작업 단위로 정리한다. 실제 운영 API를 호출하거나 외부 모델에 자료를 보내지 않았다.

## 0. 콜드 세션 실행 계약

이 문서는 새 세션의 **실행 진입점**이다. 세션은 이 파일을 처음부터 끝까지 읽고, 아래 절차로 한 개 작업 명령만 수행한다. 계획 전체를 한 세션에 구현하지 않는다.

- 작업 루트: `/home/jechoi/projects/bidops`
- `pwd`가 작업 루트와 다르면 파일을 읽거나 수정하기 전에 해당 경로로 이동한다.

### 0.1 작업 명령 선택

1. 사용자가 `R-xx`를 지정하면 그 작업만 수행한다.
2. ID를 지정하지 않고 “수정 계획을 진행”하라고 하면 [10절](#10-콜드-세션-작업-명령)의 상태를 현재 코드와 대조한 뒤, 선행조건을 만족하는 가장 앞의 미완료 작업 하나를 선택한다.
3. 현재 코드에 부분 구현이 있으면 새로 만들지 말고 diff와 테스트를 읽어 이어서 완성한다.
4. 설계 승인이 필요한 작업은 설계 산출물까지만 만든다. 임시 API나 mock을 운영 계약처럼 연결하지 않는다.
5. 한 작업의 검증과 인계 기록까지 끝낸 뒤 세션을 종료한다. 다음 작업을 임의로 시작하지 않는다.

### 0.2 변경 전 필수 읽기

모든 세션:

1. `AGENTS.md`
2. `docs/standards.md`
3. `docs/engineering-notes.md`
4. 이 문서 전체
5. [UI/UX 고도화 계획](./2026-08-31-ui-ux-advancement-plan.md)의 0절과 제품 원칙

프런트엔드 변경:

1. `web/AGENTS.md`
2. `web/frontend/AGENTS.md`
3. `docs/business-rules.md`

REST·DB·상태 변경:

1. `web/backend/AGENTS.md`
2. `docs/contracts.md`
3. `docs/business-rules.md`
4. `docs/security.md`
5. DB·migration·배포가 포함되면 `docs/operations.md`

문서 준비·심층 검토:

1. `docs/review/phase3/plan.md`
2. `docs/review/phase3/spec.md`
3. `docs/security.md`

입찰 delta·최종 결정:

1. `docs/tracking/lifecycle-workstream.md`
2. `docs/tracking/decisions/0030-opportunity-tracking-state.md`
3. `docs/tracking/decisions/0031-prespec-overview-review-stage.md`
4. `docs/contracts.md`

링크 문서는 참고 요약이 아니라 실행 제약이다. 계획과 정본 문서가 충돌하면 정본 문서를 따르고, 이 계획의 충돌을 같은 세션에서 수정한다.

### 0.3 작업 트리 사전 점검

저장소가 깨끗하다고 가정하지 않는다. 다음을 변경 전에 실행하고 결과를 인계 기록에 남긴다.

```bash
pwd
git rev-parse --short HEAD
git status --short
git diff --stat
git diff -- <이번 작업의 대상 파일>
```

- 기존 수정과 새 파일은 사용자 작업으로 간주해 보존한다.
- 대상 파일에 기존 diff가 있으면 그 의도와 현재 테스트 상태를 먼저 파악한다.
- 기존 변경을 되돌리거나 snapshot을 일괄 갱신하거나 Git 이력을 조작하지 않는다.
- 겹치는 변경을 안전하게 보존할 수 없으면 코드를 수정하지 말고 충돌 파일과 이유를 보고한다.
- 문서에 적힌 2026-08-31 파일 상태는 점검 당시 근거일 뿐이다. 실행 시점의 코드와 `git status`가 정본이다.

### 0.4 공통 구현 경계

- 프런트는 서버 응답을 재판정하거나 누락 relation·등급·상태를 추정하지 않는다.
- `unknown`, `null`, failed, blocked를 없음·성공·변경 없음으로 바꾸지 않는다.
- 담당자 이름은 claimed actor이며 인증·권한으로 표현하지 않는다.
- 외부 모델, 실제 나라장터, 실제 첨부 URL을 테스트에서 호출하지 않는다.
- ready bundle, document version, attempt, report revision, final opinion, 최종 결정 이력을 덮어쓰지 않는다.
- mutation은 해당 계약의 actor, reason, request ID, expected version을 유지한다.
- endpoint 오류 문구로 분기하지 않고 typed status와 안정 code를 사용한다.
- UI 변경을 이유로 백엔드 계약을 조용히 확장하지 않는다. 계약 작업은 별도 작업 명령으로 수행한다.

### 0.5 공통 검증

프런트 변경의 최소 검증:

```bash
cd web/frontend
npm run build
npx playwright test <대상-spec> --project=desktop
npx playwright test <대상-spec>
```

공통 shell·반응형·fixture를 바꿨으면 추가로 실행한다.

```bash
cd web/frontend
npm run test:visual
```

백엔드 변경의 최소 검증:

```bash
cd web/backend
.venv/bin/pytest <대상-test-file>
```

DB·공통 API 계약을 바꿨으면 대상 테스트 뒤 전체 backend suite와 빈 PostgreSQL 17 migration 검증을 수행한다. 실행 환경이 없어 전체 검증을 못 하면 통과로 쓰지 않고 정확한 미실행 이유를 남긴다.

문서 검증:

```bash
git diff --check -- <변경 문서와 코드>
```

시각 snapshot은 실제 diff를 확인한 뒤 의도된 변경만 갱신한다. 기존 실패를 새 변경의 성공으로 상쇄하지 않는다.

### 0.6 즉시 중단 조건

다음 조건에서는 관련 mutation·외부 호출·구현을 중단하고 재현 근거를 보고한다.

- 첨부 허용 경로 이탈, 비밀·회사자료 노출, 승인 없는 외부 모델 전송
- 원본 회차·기존 리뷰·불변 document/attempt/decision 덮어쓰기
- 원문과 다른 근거가 검증을 통과하는 경로
- 사용자 선택이 필요한 상태 의미를 임의로 정해야만 진행 가능한 경우
- delta 또는 최종 결정 backend 계약 없이 production UI mutation을 만들어야 하는 경우
- 기존 사용자 diff를 보존할 수 없는 경우

구조적 미해결 문제는 `docs/tracking/findings.md`의 기록 규칙에 따라 재현 조건, 영향, 지금 해결할 수 없는 이유, 후속 방향을 남긴다.

### 0.7 세션 종료 보고 형식

모든 콜드 세션은 최종 응답과 이 문서 10.13절 실행 기록에 다음을 남긴다.

```text
작업 명령: R-xx
기준 HEAD: <short sha>
기존 겹침: <없음 | 파일과 보존 방법>
변경 파일: <목록>
완료 기준: <충족/미충족과 근거>
검증: <실행한 정확한 명령과 결과>
미실행 검증: <없음 | 이유>
남은 위험: <없음 | 내용>
다음 가능 작업: <R-xx | 결정/승인 필요>
```

## 1. 결론

기존 검토 대기열은 URL 기반 필터, 키보드 이동, 초안 보호, 저장 후 다음 항목 이동 등 반복 검토 업무에 필요한 기반이 좋다. 반면 신규 생애주기 화면은 개별 페이지와 일부 컴포넌트가 존재해도 서로 이어지지 않거나 읽기 전용인 구간이 있어, 담당자가 브라우저만으로 한 사업기회를 끝까지 처리할 수 없다.

수정의 우선순위는 다음과 같다.

1. 운영에 사용하면 안 되는 legacy 첨부 mutation을 화면에서 차단한다.
2. 사업기회를 정본 탐색 문맥으로 삼아 잘못된 회차 이동과 선택 유실을 없앤다.
3. 사전규격 필터·개요 검토·문서 준비의 막힌 경로를 연결한다.
4. 심층 검토의 진행·실패·재시작·의견 기록을 완결한다.
5. 입찰공고 변경 비교와 최종 사람 Go/No-Go를 감사 가능한 계약으로 구현한다.

등급, 참여 준비 상태, 사전규격 개요 검토, 심층 검토 최종 의견, 추적 상태, 최종 Go/No-Go는 서로 대신하지 않는다. `unknown`과 `null`은 확인 전 상태로 그대로 표시한다.

## 2. 점검 범위와 검증 기록

### 확인한 화면

- 대시보드와 기존 검토 대기열
- 사업기회 목록과 추적 상태 편집
- 사전규격 목록
- 공고 상세와 첨부 영역
- 문서 bundle과 심층 검토 화면
- 입찰공고 delta 비교 화면
- 전역 shell, 회차 선택기, 반응형 내비게이션

### 실행 결과

| 검증 | 결과 | 해석 |
|---|---|---|
| `npm run build` | 성공, Vite 6.4.3, 276 modules | 현재 작업 트리의 production build 가능 |
| 번들 | JS 687.40 kB, gzip 200.82 kB | 500 kB 경고가 있어 후속 분할 대상 |
| `npm run test:visual` | 184개 중 150 passed, 10 skipped, 24 failed | laptop·desktop 기준선에서 현재 sidebar 변경과 차이가 집중됨. 스냅샷 자동 갱신 금지 |
| 실제 브라우저 접근성 트리 점검 | 프런트 화면 확인, API 미연결 | 실제 데이터 E2E의 통과 근거가 아님 |
| mock API 사용 시나리오 | 사업기회·사전규격·delta 흐름 재현 | 라우팅·필터·행동 단절을 결정적으로 확인 |

새 생애주기 화면은 기존 시각 회귀 목록에서 충분히 다루지 않는다. 심층 검토 테스트도 최소 접근성·overflow 확인에 머문다.

## 3. 보존할 UX 원칙

- 데스크톱 검토 대기열의 목록–근거–판정 입력 구조
- 값 없음, 계산 불가, 실제 0을 구분하는 표현
- 색과 함께 문자를 사용하는 상태 표시
- 회차·필터를 URL에 남기는 기존 패턴
- J/K 이동, 초안 임시 저장, 브라우저 이탈 보호, 저장 후 다음 항목 이동과 되돌리기
- 담당자 이름은 감사 표식일 뿐 로그인이나 인증이 아니라는 안내
- 모델 결과보다 원문 위치와 검증 상태를 우선하는 근거 표현

## 4. 대표 사용 시나리오와 현재 판정

### UC-01. 발주계획에서 오늘 검토할 사업기회를 고른다

- 사용자: 기획·사업개발 담당자
- 시작: 대시보드의 오늘 할 일 또는 사업기회 목록
- 정상 흐름:
  1. 기본 필터로 미선택·재검토 필요 건을 본다.
  2. 사업기회를 선택해 발주계획, 연결된 사전규격·입찰공고, 사람 추적 상태를 확인한다.
  3. 이유와 담당자 이름을 남겨 `계속 추적 | 보류 | 종료 | 미선택` 중 하나를 저장한다.
  4. 새 공식 레코드가 붙은 종료 건은 `종료 · 재검토 필요`로 함께 본다.
- 현재 판정: 부분 통과
- 확인된 문제:
  - 선택이 컴포넌트 로컬 상태라 새로고침·뒤로 가기에서 사라진다.
  - 사업기회에서 사전규격·delta로 이어지는 다음 행동이 약하거나 없다.
  - 누적 데이터 화면에 전역 회차 선택기가 남아 잘못된 문맥을 암시한다.
- 완료 기준:
  - 선택 ID, 필터, 정렬이 URL로 복원된다.
  - 각 연결 레코드는 정본 상세 경로로 이동한다.
  - 시스템 재검토 신호와 사람 추적 상태가 한 필드처럼 보이지 않는다.

### UC-02. 사전규격에서 개요를 확인하고 심층 검토 여부를 정한다

- 사용자: 사업개발 담당자
- 시작: 사전규격 목록
- 정상 흐름:
  1. `SW 중심 · 추적 예외 포함` 기본 보기를 확인한다.
  2. 신규 여부, 연결된 발주계획, D-day, 개요 검토 상태를 비교한다.
  3. 구조 절단에 실패한 `unknown`은 사람 검토 대상으로 연다.
  4. 개요 검토와 별개로 심층 검토 진행 여부 또는 추적 상태를 사람이 선택한다.
- 현재 판정: 실패
- 확인된 문제:
  - 기본 `sw_only=true`를 활성 필터로 세어 빈 상태에 `필터 초기화`를 노출하지만, 이 버튼은 다시 기본값 `true`로 돌아가므로 눈에 보이는 변화가 없다.
  - `SW사업대상만`이라는 문구가 `SW사업대상=N`인 추적 예외도 남긴다는 계약과 충돌한다.
  - 목록 링크가 `/judgments/{notice_pk}`로 이동해 선택 회차에 없는 사전규격을 첫 공고로 치환할 수 있다.
  - 문서 차단·실패 개수는 보이지만 복구 행동으로 이어지지 않는다.
- 완료 기준:
  - `기본값으로`는 ADR대로 `sw_only=true`로 돌아가고, 기본 SW 보기만 적용된 빈 상태에서는 별도 `전체 사전규격 보기`가 `sw_only=false`를 보낸다.
  - 사전규격 전용 상세 경로에서 선택 항목이 다른 공고로 바뀌지 않는다.
  - 개요 검토의 입력 범위와 한계가 표시되고, `unknown`을 자동 성공으로 보정하지 않는다.

### UC-03. 안전한 문서 bundle을 준비해 심층 검토를 시작한다

- 사용자: 심층 검토 담당자
- 시작: 사전규격 상세 또는 사업기회 상세
- 정상 흐름:
  1. draft bundle을 만들고 HWP/HWPX/PDF를 등록한다.
  2. 안전 검사와 구조화 상태를 기다린다.
  3. 역할, 시행일, 대체 문서, 현재 버전을 확인한다.
  4. 차단 issue가 없고 모든 조건이 충족된 snapshot을 명시적으로 확정한다.
  5. ready bundle로 심층 검토를 시작한다.
- 현재 판정: 실패
- 확인된 문제:
  - 공고 상세는 ready bundle이 필요하다고 안내하지만, 그 bundle을 만드는 UI가 연결되지 않았다.
  - 별도의 legacy `원문 보관소`는 비영속·unsafe upload를 정상 기능처럼 노출한다.
- 완료 기준:
  - legacy upload·delete 호출 경로가 UI에서 제거되거나 명시적으로 비활성화된다.
  - bundle 생성부터 등록·분류·확정까지 브라우저에서 수행할 수 있다.
  - blocked, failed, needs_review, pending은 ready와 명확히 구분된다.
  - ready bundle과 기존 문서 버전을 덮어쓰지 않는다.

### UC-04. 심층 검토 실패를 새 attempt로 재시작한다

- 사용자: 심층 검토 담당자
- 시작: 심층 검토 화면
- 정상 흐름:
  1. queued/running 동안 제한된 주기로 진행 상태를 본다.
  2. 완료 뒤에만 machine report를 연다.
  3. 실패하면 기존 attempt의 원인과 시각을 보존한 채 새 attempt를 생성한다.
  4. evidence와 validation을 확인하고 revision과 `사전규격 심층검토 의견`을 append-only로 남긴다.
- 현재 판정: 실패
- 확인된 문제:
  - 진행 중에도 report를 즉시 요청해 정상 `review_not_ready`가 오류처럼 보일 수 있다.
  - 자동 polling, attempt 이력, 재시작 UI가 없다.
  - 의견 mutation에 필요한 담당자 이름이 행동 영역과 멀다.
  - `최종 의견`은 최종 입찰 Go/No-Go와 혼동된다.
- 완료 기준:
  - active 상태에서만 polling하고 terminal 상태에서 멈춘다.
  - 실패한 current attempt에서만 재시작이 가능하다.
  - 이전 attempt는 수정·삭제하지 않으며 새 sequence를 함께 표시한다.
  - 의견 초안 이탈 보호와 저장 성공 피드백이 있다.

### UC-05. 입찰공고 변경을 비교하고 사람이 Go/No-Go를 기록한다

- 사용자: 최종 검토 담당자
- 시작: 입찰공고가 연결된 사업기회
- 정상 흐름:
  1. 사전규격 기준 문서와 현재 입찰공고 문서의 버전을 확인한다.
  2. 자격, 요구사항, 평가, 일정, 제출물, 계약·경제성 등 승인된 범주의 material delta를 본다.
  3. 각 변경의 양쪽 원문 locator를 확인한다.
  4. `unknown`과 분석 실패를 변경 없음으로 해석하지 않는다.
  5. 담당자 이름과 이유를 남겨 최종 사람 Go/No-Go를 append-only로 기록한다.
- 현재 판정: 실패
- 확인된 문제:
  - 프런트가 호출하는 delta endpoint와 대응 백엔드 REST 계약이 확인되지 않는다.
  - 사업기회 화면에서 delta로 이동하는 경로가 없다.
  - 최종 결정 카드는 읽기 전용이며 저장 mutation이 없다.
  - 공통 상단 바가 이 화면도 `추적 상태 저장 가능`으로 잘못 설명한다.
- 완료 기준:
  - REST·DB·감사 계약을 먼저 확정한 뒤 UI를 연결한다.
  - 비교 기준 문서 버전, 계산 상태, 변경 근거를 항상 확인할 수 있다.
  - 모델이나 delta 결과가 최종 사람 결정을 자동 생성하지 않는다.

### UC-06. 이동·새로고침·작은 화면에서도 작업을 이어 간다

- 사용자: 모든 담당자
- 시작: 위 시나리오의 편집 중 상태
- 정상 흐름:
  1. 뒤로 가기나 새로고침 후 같은 항목과 필터로 돌아온다.
  2. 미저장 변경이 있으면 보호 안내를 받는다.
  3. 390/768/1024/1440px에서 핵심 행동을 키보드와 터치로 수행한다.
- 현재 판정: 부분 통과
- 확인된 문제:
  - 기존 대기열은 잘 보호되지만 사업기회 inline form과 신규 화면에는 같은 원칙이 적용되지 않았다.
  - 신규 화면의 시각 회귀 범위가 부족하다.
- 완료 기준:
  - 편집 화면에 공통 dirty-state 계약이 적용된다.
  - 주요 상태와 mutation 결과를 `role="status"`, `role="alert"`, `aria-live`로 전달한다.
  - 네 기준 viewport에서 문서 전체 가로 overflow와 한 글자 세로 줄바꿈이 없다.

## 5. 수정 작업 패키지

### P0-A. legacy 첨부 mutation 차단

범위:

- `AttachmentPanel`의 legacy upload·delete control 제거 또는 fail-closed 비활성화
- 보관소·업로드 완료로 오인되는 문구 제거
- 기존 첨부 메타데이터가 필요하면 읽기 전용 이력으로만 표시
- ready bundle 부재 안내를 안전한 문서 준비 작업대로 연결

검증:

- Playwright에서 legacy upload endpoint 요청이 0건이다.
- legacy attachment가 있어도 문서 준비 완료나 심층 검토 가능 상태로 표현되지 않는다.

### P0-B. 정본 라우팅과 페이지 문맥

권장 정본 경로:

| 목적 | 경로 |
|---|---|
| 사업기회 목록 | `/opportunities` |
| 사업기회 상세 | `/opportunities/:opportunityId` |
| 사전규격 상세 | `/pre-specs/:noticeId` |
| 심층 검토 | `/deep-reviews/:deepReviewId` |
| 입찰공고 변경 비교 | `/opportunities/:opportunityId/bid-delta` |

범위:

- 목록 선택, 필터, 정렬을 URL로 이동
- `notice.run_id`에 종속된 기존 판정 상세와 누적 opportunity·pre-spec 경로 분리
- route metadata에 `title`, `dataScope`, `editScope`, `runSelectorVisible` 정의
- 누적 화면에서는 전역 회차 선택기를 숨기고, 특정 레코드의 관측 회차는 로컬 metadata로 표시
- 뒤로 가기에서 필터·선택·스크롤 복원

검증:

- 사전규격 991을 눌렀을 때 다른 notice 29로 이동하지 않는다.
- `/opportunities/:id` 새로고침 뒤 같은 사업기회가 열린다.
- 누적 화면에서 회차를 바꿔 선택 레코드가 조용히 치환되지 않는다.

### P0-C. 사전규격 목록과 개요 검토

범위:

- 기본 필터 문구를 `SW 중심 · 추적 예외 포함`으로 변경
- ADR의 기본 활성 계약에 맞춰 URL 누락은 `sw_only=true`로 유지
- 사용자가 전체 보기를 선택했을 때만 URL에 `sw_only=false`를 명시
- `필터 초기화`를 `기본값으로`로 바꾸고 `sw_only=true`와 나머지 기본값을 일관되게 적용
- 기본 SW 보기만 적용된 빈 상태에서는 `전체 사전규격 보기`를 별도 행동으로 제공
- D-day, 신규 여부, 발주계획 연결, 개요 검토 상태, 문서 준비 상태를 분리 표시
- 차단·실패 상태에 상세 보기 또는 재처리 가능한 안전한 경로 제공
- 개요 검토 승인과 사업기회 추적 상태를 별도 control로 유지

검증:

- 기본값 복원 뒤 checkbox 활성과 `sw_only=true` 요청을, 전체 보기 뒤 checkbox 해제와 `sw_only=false` 요청을 각각 검사한다.
- `SW사업대상=N`인 추적 예외가 기본 목록에서 사라지지 않는다.
- 절단 실패 `unknown`은 사람 확인 필요로 남는다.

### P1-A. 안전한 문서 준비 작업대

범위:

- 기존 Lean API의 bundle 생성, 문서 등록, metadata patch, confirm 연결
- `업로드 → 안전 검사 → 변환·구조화 → 역할 확인 → snapshot 확정` 단계 표시
- 역할, 시행일, 대체 문서, current version 관리
- 문서별 독립 request ID와 부분 실패 표시
- 확정 전 조건과 버튼 비활성 사유를 문자로 설명
- 403 gate와 503 profile/policy fail-closed 상태를 운영 조치로 표현

검증:

- draft 생성부터 ready confirm까지 실제 payload·actor header를 Playwright에서 검사한다.
- 한 문서 실패가 전체 성공으로 보이지 않는다.
- unsafe·failed·needs_review 문서가 있으면 확정할 수 없다.

### P1-B. 심층 검토 진행·재시작·의견 UX

범위:

- review/attempt가 active일 때만 polling
- complete 뒤 report query 활성화
- attempt timeline과 current 표시
- failed current attempt에서만 새 attempt 생성
- mutation 영역 근처에 담당자 이름과 감사 안내 배치
- `revision`은 `보고서 수정본`, `final opinion`은 `사전규격 심층검토 의견`으로 표시
- evidence ID, locator, validation 같은 용어는 업무 설명을 먼저 쓰고 기술 식별자는 보조 정보로 이동
- 의견 초안 보호, 저장 성공 토스트, 오류 복구 행동 추가

검증:

- queued/running/complete/failed fixture 각각에서 요청 수와 control 상태를 검사한다.
- 재시작 뒤 기존 attempt와 새 attempt가 함께 남는다.
- report 미준비 상태가 영구 오류 화면으로 고정되지 않는다.

### P1-C. delta와 최종 Go/No-Go 수직 슬라이스

선행조건:

- delta 조회 REST 계약 확정
- 기준·비교 document version과 계산 상태 계약 확정
- 최종 사람 결정의 append-only DB·REST·감사 계약 확정
- 변경 범주와 `unknown | unchanged | changed | failed` 의미 확정

범위:

- 사업기회 상세의 입찰공고 연결 카드에 `변경 비교` CTA 추가
- 양쪽 문서 버전, 계산 시각, 전체·범주별 상태 표시
- 변경 전·후 evidence locator를 한 쌍으로 연결
- 변경 있음, 변경 없음, 판단 불가, 분석 실패를 구분
- 담당자 이름, 결정, 이유를 요구하는 최종 Go/No-Go 저장 form 추가
- 저장 이력과 현재 유효 결정을 함께 표시하되 과거 기록을 덮어쓰지 않음

검증:

- endpoint가 없는 상태에서는 mock 화면을 production 완료로 간주하지 않는다.
- `unknown`과 failed fixture에서 Go/No-Go를 자동 제안하거나 변경 없음으로 표시하지 않는다.
- 저장 request에 actor, reason, request ID, 비교 문서 버전이 포함된다.

### P2-A. 공통 상호작용과 디자인 시스템 정리

범위:

- 공통 `StatusBadge`, `EmptyState`, `MutationFeedback`, `UnsavedGuard`, `ActorField` 계약
- 페이지 제목 중복 제거와 정보 계층 정리
- 비활성 버튼에 항상 사유 제공
- 의미별 color token과 전역 `:focus-visible`
- 40–44px 주요 조작부, 작은 화면의 single-pane 전환
- route 단위 lazy loading으로 초기 JS bundle 분할

검증:

- 상태를 색만으로 구분하는 신규 UI가 없다.
- 키보드 tab 순서, focus ring, live region을 자동·수동으로 확인한다.
- 분할 전후 route별 chunk와 초기 전송량을 기록한다.

### P2-B. 회귀 테스트 확장

필수 기능 테스트:

- 사전규격 기본값 복원·전체 보기와 잘못된 공고 redirect 재현
- 사업기회 URL 선택 복원과 뒤로 가기
- legacy 첨부 mutation 차단
- 문서 bundle 전체 흐름과 부분 실패
- 심층 검토 polling·retry·append-only 이력
- delta 상태 4종과 최종 사람 결정 저장
- 미저장 초안 이탈 보호

필수 시각 상태:

- 사업기회 목록·상세
- 사전규격 목록·상세와 `unknown`
- 문서 준비 draft·processing·blocked·ready
- 심층 검토 queued·running·failed·complete
- delta unchanged·changed·unknown·failed
- 390/768/1024/1440px

기존 24개 실패 snapshot은 의도된 sidebar 변경인지 회귀인지 diff를 먼저 검토한다. 확인 없이 `--update-snapshots`로 덮지 않는다.

## 6. 구현 순서와 게이트

| 순서 | 작업 | 진입 조건 | 종료 증거 |
|---:|---|---|---|
| 1 | P0-A legacy 차단 | 없음 | legacy mutation 0건 테스트 |
| 2 | P0-B route metadata와 정본 문맥 | route 목록 합의 | redirect·복원 테스트 |
| 3 | P0-C 사전규격 버그와 개요 UX | P0-B | reset·예외 포함 테스트 |
| 4 | 사업기회 정본 상세 연결 | P0-B | 목록→상세→하위 단계 이동 |
| 5 | P1-A 문서 준비 | 기존 Lean API 확인 | bundle E2E mock + build |
| 6 | P1-B 심층 검토 | 문서 준비 또는 ready fixture | polling·retry 테스트 |
| 7 | P1-C 계약 설계 | REST·DB 결정 승인 | 계약·migration·API 테스트 |
| 8 | P1-C 화면 연결 | backend 계약 구현 | delta→결정 수직 슬라이스 |
| 9 | P2 공통화·최적화 | 주요 흐름 안정화 | 접근성·visual·bundle 기록 |

입찰공고 delta UI를 백엔드 계약보다 먼저 완성 처리하지 않는다. 발주계획 선별 방식에 영향을 주는 순위·추천 UI는 고정 3일 표본 비교 실험과 사람 정답 보고서 승인 전 구현하지 않는다.

## 7. 공통 완료 정의

작업 하나가 완료되려면 다음을 모두 만족한다.

- 업무 규칙의 서로 다른 판단 필드를 합치거나 대체하지 않는다.
- `unknown`, `null`, failed, blocked를 성공·없음·변경 없음으로 보정하지 않는다.
- mutation에 actor, reason, request ID, 대상 version 등 해당 계약의 감사 필드가 있다.
- 불변 snapshot·attempt·decision history를 덮어쓰지 않는다.
- 오류에는 원인 범주와 안전한 다음 행동이 있고 민감정보는 노출하지 않는다.
- production build와 대상 Playwright 테스트가 통과한다.
- 390/768/1024/1440px에서 overflow, focus, live feedback을 확인한다.
- 관련 계약·운영·추적 문서를 함께 갱신한다.

## 8. 범위 밖

- 자동 입찰 제출, 발주처 연락, 자동 Go/No-Go
- 승인 없는 외부 모델 전송 또는 hosted OpenAI 자동 fallback
- 앱 startup에서 migration, seed, 정책 활성화, 모델 호출
- 담당자 이름을 인증이나 권한으로 간주하는 기능
- 선별 품질 게이트 승인 전의 자동 추천·자동 우선순위 제품화
- SSO와 역할 권한 구현 자체. UI 고도화 계획에서는 선행 의존성으로만 다룬다.

## 9. 관련 문서

- [생애주기 작업 기록](../tracking/lifecycle-workstream.md)
- [사업 규칙](../business-rules.md)
- [REST·DB 계약](../contracts.md)
- [보안 정책](../security.md)
- [Phase 3 문서 준비·심층 검토 계획](./phase3/plan.md)
- [사전규격 개요 검토 ADR](../tracking/decisions/0031-prespec-overview-review-stage.md)
- [개요 절단 규칙 ADR](../tracking/decisions/0032-prespec-overview-cutting-rule.md)
- [사업기회 추적 상태 ADR](../tracking/decisions/0030-opportunity-tracking-state.md)

## 10. 콜드 세션 작업 명령

### 10.1 작업 인덱스

상태는 실행 시점의 코드와 테스트로 다시 판정한다. 문서의 체크 표시만 믿지 않는다.

| ID | 작업 | 선행조건 | 기본 상태 |
|---|---|---|---|
| R-01 | legacy 첨부 mutation 차단 | 없음 | 실행 전 재확인 |
| R-02 | route metadata와 회차 문맥 분리 | R-01과 독립 | 실행 전 재확인 |
| R-03 | 사업기회 정본 상세·URL 복원 | R-02 | 실행 전 재확인 |
| R-04 | 사전규격 기본 보기·정본 상세 | R-02 | 실행 전 재확인 |
| R-05 | 안전한 문서 준비 작업대 | R-04, Phase 3 T5 계약 | 실행 전 재확인 |
| R-06 | 심층 검토 polling·attempt 재시작 | Phase 3 T5, ready fixture | 실행 전 재확인 |
| R-07 | delta·최종 결정 계약 설계 | 관련 ADR·규칙 확인 | 미확정 계약 |
| R-08 | delta·최종 결정 backend | R-07 승인 | 진입 금지 |
| R-09 | delta·최종 결정 frontend | R-08 API | 진입 금지 |
| R-10 | 공통 interaction·접근성 | R-02~R-06 주요 흐름 안정 | 실행 전 재확인 |
| R-11 | 통합 회귀·시각 기준선·bundle 분할 | R-01~R-10 대상 범위 완료 | 실행 전 재확인 |

### 10.2 R-01 — legacy 첨부 mutation 차단

목표:

- legacy 첨부를 조회 이력 이상으로 사용하지 못하게 하고, 안전한 문서 준비 경로만 다음 행동으로 제시한다.

기본 쓰기 범위:

- `web/frontend/src/components/notice/AttachmentPanel.tsx`
- `web/frontend/src/pages/NoticeDetailPage.tsx`
- 필요한 기존 `web/frontend/src/styles/review-workspace-relaxed.css`
- 신규 또는 대상 `web/frontend/tests/lifecycle-safety.spec.ts`

구현 계약:

- `POST /api/notices/{id}/attachments`와 `DELETE /api/attachments/{id}`를 호출할 control을 제거하거나 fail-closed 비활성화한다.
- 기존 첨부가 필요하면 provenance가 있는 읽기 전용 metadata로만 표시한다.
- ready bundle이 없을 때 legacy upload를 대체 행동으로 제안하지 않는다.
- `web/frontend/src/lib/api.ts`의 미사용 client 삭제는 별도 정리다. UI 차단을 위해 계약을 임의 삭제하지 않는다.

완료 증거:

- Playwright가 legacy POST·DELETE 요청 0건을 검증한다.
- production build와 대상 spec 네 viewport가 통과한다.
- backend·DB·attachment service는 변경하지 않는다.

### 10.3 R-02 — route metadata와 회차 문맥 분리

목표:

- 누적 화면과 회차 화면의 title, edit scope, run selector를 pathname prefix 추측 없이 명시적으로 결정한다.

기본 쓰기 범위:

- `web/frontend/src/routes.tsx`
- `web/frontend/src/components/shell/AppShell.tsx`
- `web/frontend/src/components/shell/TopBar.tsx`
- 필요하면 신규 `web/frontend/src/components/shell/route-meta.ts`
- `web/frontend/tests/route-context.spec.ts`

구현 계약:

- route metadata는 최소 `title`, `dataScope`, `editScope`, `runSelectorVisible`을 가진다.
- `/opportunities`, `/pre-specs`, `/opportunities/:id/bid-delta` 같은 누적 화면은 전역 회차 선택기를 숨긴다.
- `/queue`, `/judgments`, `/runs` 등 회차 화면의 기존 `run` 보존 동작은 유지한다.
- `/opportunities/:id/bid-delta`가 `/opportunities`의 `추적 상태 저장 가능`을 상속하지 않는다.
- shell이 모든 route 진입에서 무조건 `/api/runs`에 의존할지 검토하고, 누적 화면의 실패를 회차 API 오류가 막지 않게 한다.

완료 증거:

- route별 title·edit scope·selector 유무를 table-driven Playwright로 검사한다.
- 기존 dashboard→queue 회차 보존 테스트가 통과한다.
- 신규 route를 아직 만들지 않은 후속 작업의 placeholder metadata를 production 기능처럼 노출하지 않는다.

### 10.4 R-03 — 사업기회 정본 상세·URL 복원

목표:

- 목록 선택을 URL 정본으로 바꾸고 새로고침·뒤로 가기에서 같은 사업기회와 필터 문맥을 복원한다.

기본 쓰기 범위:

- `web/frontend/src/pages/OpportunitiesPage.tsx`
- 필요하면 신규 `web/frontend/src/pages/OpportunityDetailPage.tsx`
- `web/frontend/src/routes.tsx`
- `web/frontend/src/lib/api.ts`와 `web/frontend/src/lib/types.ts`는 기존 API 소비 변경에 한함
- `web/frontend/src/styles/opportunities-relaxed.css`
- `web/frontend/tests/opportunities.spec.ts`

구현 계약:

- 정본 상세 경로는 `/opportunities/:opportunityId`다.
- 목록 query의 filter·sort·offset과 선택 ID를 URL로 복원한다.
- detail은 기존 `GET /api/opportunities/{id}`를 사용하고 relation을 프런트에서 추론하지 않는다.
- 추적 상태와 재검토 신호를 별도 영역으로 유지한다.
- inline form을 유지하면 접기·필터 변경·route 이탈의 dirty-state를 보호한다.
- 현재 작업 트리에 `OpportunitiesPage.tsx`와 스타일의 기존 diff가 있을 가능성이 높으므로 반드시 먼저 읽고 보존한다.

완료 증거:

- 목록 선택→상세→새로고침→뒤로 가기 시나리오가 통과한다.
- `미선택`, `종료 · 재검토 필요`, 후보 relation fixture를 각각 검사한다.
- mutation payload와 actor encoding의 기존 backend 계약을 바꾸지 않는다.

### 10.5 R-04 — 사전규격 기본 보기·정본 상세

목표:

- ADR-0031의 기본 SW 보기와 추적 예외를 정확히 설명하고, 선택 notice가 다른 회차 공고로 치환되지 않는 상세 경로를 만든다.

기본 쓰기 범위:

- `web/frontend/src/pages/PreSpecsPage.tsx`
- 신규 `web/frontend/src/pages/PreSpecDetailPage.tsx` 또는 같은 책임의 명시적 컴포넌트
- `web/frontend/src/routes.tsx`
- `web/frontend/src/styles/pre-specs-relaxed.css`
- `web/frontend/tests/pre-specs.spec.ts`
- fixture에 필요한 `web/frontend/tests/api-mock.ts`

구현 계약:

- 정본 상세 경로는 `/pre-specs/:noticeId`다.
- 기존 `/judgments/:noticePk`의 run 보정으로 사전규격 상세를 구현하지 않는다.
- URL 누락은 `sw_only=true`, 전체 보기는 명시적 `sw_only=false`다.
- `기본값으로`와 `전체 사전규격 보기`를 다른 행동으로 제공한다.
- 기본 보기 label은 `SW 중심 · 추적 예외 포함`이며 `SW사업대상=N` 추적 예외를 숨기지 않는다.
- `unknown`, 신규, D-day, 문서 blocked/failed를 별도 상태로 표시한다.
- 상세 API에 필요한 값이 현재 projection에 없으면 프런트에서 만들지 말고 계약 gap을 기록한다.

완료 증거:

- `sw_only=true|false`의 실제 request query를 검사한다.
- mock notice 991 선택 뒤 29로 바뀌지 않는 회귀 테스트가 통과한다.
- 추적 예외와 `unknown` fixture가 올바른 문구를 가진다.

### 10.6 R-05 — 안전한 문서 준비 작업대

목표:

- 브라우저에서 draft bundle 생성부터 upload·metadata 확인·ready confirm·심층 검토 시작까지 수행한다.

필수 추가 읽기:

- `docs/review/phase3/plan.md`의 T5·T6
- `docs/review/phase3/spec.md`의 T5·T6
- `web/backend/app/routers/document_bundles.py`
- `web/backend/app/schemas/document_bundles.py`

기본 쓰기 범위:

- 신규 `web/frontend/src/components/deep-review/DocumentPreparationPanel.tsx`
- `web/frontend/src/components/deep-review/api.ts`
- `web/frontend/src/components/deep-review/types.ts`
- R-04에서 정한 사전규격 상세 페이지
- 필요한 전용 style
- `web/frontend/tests/document-preparation.spec.ts`

구현 계약:

- 현재 API client에 create/upload/patch/confirm/retry가 부분 또는 전부 이미 있을 수 있으므로 먼저 확인하고 중복 구현하지 않는다.
- Phase 3 T6가 지정한 `NoticeDetailPage.tsx`는 작성 당시의 진입점이다. R-04가 사전규격 정본 상세를 만든 뒤에는 작업대를 그 상세에 연결하되, Phase 3의 API·actor·불변성·오류 계약은 그대로 지킨다.
- actor header, multipart boundary, request ID, expected version, confirm snapshot은 Phase 3 spec을 그대로 따른다.
- upload, scan, convert, structure, confirm 상태를 합치지 않는다.
- blocked·failed·needs_review는 ready가 아니며 비활성 이유를 문자로 표시한다.
- ready/superseded bundle과 기존 document version을 수정하지 않는다.
- 403 effective grade와 503 profile/policy 오류를 우회하지 않는다.

완료 증거:

- Phase 3 T8의 생성→upload→patch→confirm→deep review 시나리오가 통과한다.
- 비ASCII actor, 부분 upload 실패, 403, 503을 검사한다.
- backend 계약 변경이 필요해지면 구현을 멈추고 별도 계약 작업으로 분리한다.

### 10.7 R-06 — 심층 검토 polling·attempt 재시작

목표:

- 진행 중 상태를 정상 대기로 표현하고, 실패한 attempt를 보존한 채 새 attempt로 재시작한다.

필수 추가 읽기:

- `docs/review/phase3/plan.md`의 T7·T8
- `docs/review/phase3/spec.md`의 T7·T8
- `web/backend/app/routers/deep_reviews.py`

기본 쓰기 범위:

- `web/frontend/src/pages/DeepReviewPage.tsx`
- 필요한 `web/frontend/src/components/deep-review/api.ts`와 `types.ts`
- `web/frontend/src/styles/deep-review-evidence.css` 또는 전용 style
- `web/frontend/tests/deep-review.spec.ts`
- `web/frontend/tests/api-mock.ts`

구현 계약:

- queued/running에서만 제한된 interval로 review를 다시 읽고 terminal에서 멈춘다.
- report query는 complete 뒤 활성화하며 `review_not_ready`를 영구 오류로 고정하지 않는다.
- current failed attempt에서만 새 attempt control을 제공한다.
- 재시작은 append-only이며 기존 attempt와 stage를 성공 처리하거나 삭제하지 않는다.
- attempt history 전체와 current를 구분해 표시한다.
- `최종 의견`은 `사전규격 심층검토 의견`으로 표시하고 최종 Go/No-Go와 분리한다.
- 현재 작업 트리의 evidence viewer 변경을 먼저 읽고 보존한다.

완료 증거:

- queued→running→complete 응답 순서에서 polling 시작·중단과 report 요청 시점을 검사한다.
- failed→retry에서 POST 1건, 새 request ID, 이전·신규 attempt 동시 표시를 검사한다.
- 의견 draft 이탈 보호와 저장 live feedback을 검사한다.

### 10.8 R-07 — delta·최종 결정 계약 설계

목표:

- 존재하지 않는 backend endpoint를 가정하지 않고 REST·DB·감사·상태 의미를 먼저 확정한다.

작업 유형:

- **설계 전용 세션**이다. production 코드와 migration을 구현하지 않는다.

기본 쓰기 범위:

- `docs/contracts.md`
- `docs/business-rules.md`
- `docs/tracking/lifecycle-workstream.md`
- `docs/tracking/decisions/index.md`
- 신규 `docs/tracking/decisions/<next>-bid-delta-final-decision.md`
- 필요하면 별도 `docs/review/bid-delta-contract-spec.md`

필수 결정:

- 기준 pre-spec document version과 비교 bid document version의 식별·불변성
- 계산 상태 `pending | running | completed | failed`와 결과 상태 `changed | unchanged | unknown | failed`의 분리
- 승인된 delta 범주와 양쪽 evidence locator
- 동일 사업기회에 여러 입찰공고·정정 차수가 있을 때 비교 대상 선택 규칙
- 최종 결정 enum, actor, reason, request ID, compared version fence, append-only 이력
- 새 문서·새 공고 등장 뒤 이전 최종 결정의 현재성 표시와 재검토 신호
- 404/409/422/503과 안정 error code

중단 gate:

- 업무 책임자의 선택 없이는 enum·material 범위·최종 결정 현재성을 확정할 수 없으면 대안과 영향을 문서화하고 결정 요청 상태로 끝낸다.
- ADR-0034 채택 전 R-08·R-09를 시작하지 않는다. 이 gate는 2026-08-31의 R-07 결정으로
  R-08에 한해 충족됐으며, R-09는 실제 R-08 API와 typed error 검증 뒤에만 시작한다.

완료 증거:

- ADR 상태와 승인 주체가 명확하다.
- OpenAPI 수준 request/response 예시, DB 제약, 감사 event, 오류표, 테스트 matrix가 있다.
- 사람 Go/No-Go를 시스템 결과가 대신하지 못함을 계약으로 강제한다.

### 10.9 R-08 — delta·최종 결정 backend

진입 gate:

- R-07 ADR이 채택 상태이고 `docs/contracts.md` wire shape가 확정되어야 한다.

기본 쓰기 범위:

- `web/backend/app/models.py`
- 신규 또는 기존 `web/backend/app/schemas/bid_delta.py`
- 신규 또는 기존 `web/backend/app/services/bid_delta.py`
- 신규 또는 기존 `web/backend/app/routers/bid_delta.py`
- `web/backend/app/main.py`
- `web/backend/alembic/versions/<next>_*.py`
- `web/backend/tests/test_bid_delta.py`
- `web/backend/tests/test_db_migrations.py`
- 확정 계약을 반영하는 문서

구현 계약:

- router는 parsing·HTTP mapping만, 비교 상태·결정 저장·fence는 service가 소유한다.
- 최종 결정은 append-only이고 actor·reason·idempotency·compared version을 같은 transaction과 audit에 묶는다.
- `unknown`·failed를 unchanged로 집계하지 않는다.
- evidence는 승인된 projection만 반환하고 객체 key·path·signed URL을 노출하지 않는다.
- 앱 startup에서 migration·seed·delta 계산을 실행하지 않는다.

완료 증거:

- 정상과 404/409/422/503, idempotency, stale version, 동시 저장, append-only 이력 테스트가 통과한다.
- 빈 PostgreSQL 17 upgrade와 downgrade 가능 범위를 검증한다.
- 전체 backend suite 결과를 기존 baseline과 구분해 기록한다.

### 10.10 R-09 — delta·최종 결정 frontend

진입 gate:

- R-08 API와 typed error가 실제로 존재하고 대상 backend 테스트가 통과해야 한다.

기본 쓰기 범위:

- `web/frontend/src/components/bid-delta/api.ts`
- `web/frontend/src/components/bid-delta/types.ts`
- `web/frontend/src/pages/BidDeltaDecisionPage.tsx`
- `web/frontend/src/styles/bid-delta-decision.css`
- `web/frontend/src/pages/OpportunityDetailPage.tsx` 또는 R-03 정본 상세
- `web/frontend/src/routes.tsx`
- `web/frontend/tests/bid-delta.spec.ts`
- 필요한 mock fixture

구현 계약:

- 현재 untracked 또는 부분 구현된 bid-delta 파일을 먼저 읽고 보존한다.
- UI type은 R-08 응답을 그대로 표현하며 임시 `same` 등 다른 상태명을 유지하지 않는다.
- 계산 상태와 항목 결과 상태를 분리한다.
- 양쪽 document version과 evidence locator를 표시한다.
- 최종 결정 form은 actor, decision, reason을 요구하고 stale comparison 409를 안전하게 처리한다.
- 저장 전 시스템 분석과 사람 결정의 차이를 표시하며 자동 추천·자동 저장하지 않는다.

완료 증거:

- pending/running/completed/failed와 changed/unchanged/unknown/failed fixture를 검사한다.
- 사람 결정 미저장·저장·stale conflict·과거 이력 상태를 검사한다.
- 사업기회 상세→delta→저장→뒤로 가기 흐름이 통과한다.

### 10.11 R-10 — 공통 interaction·접근성

목표:

- 신규 흐름에서 반복된 상태·오류·actor·dirty-state 패턴을 하나의 UI 계약으로 정리한다.

기본 쓰기 범위:

- `web/frontend/src/components/common/`
- `web/frontend/src/components/shell/`
- `web/frontend/src/styles/theme.css`
- 대상 페이지의 중복 코드
- `web/frontend/tests/common-interactions.spec.ts`

구현 계약:

- `StatusBadge`, action 가능한 `EmptyState`, mutation feedback, unsaved guard, actor field의 역할을 명확히 한다.
- 공통화가 서로 다른 업무 상태를 하나의 enum으로 합치지 않게 한다.
- 모든 주요 control에 focus-visible, 비활성 사유, 40–44px target, live feedback을 제공한다.
- dialog는 focus trap, Esc, 취소 뒤 focus 복귀를 지킨다.
- 마케팅형 장식, gradient, glass effect를 추가하지 않는다.

완료 증거:

- 키보드만으로 UC-01~UC-05의 대상 mutation 전 단계까지 이동한다.
- 색을 제거해도 상태 문구가 남는다.
- 공통 컴포넌트 변경으로 기존 queue 초안 보호가 회귀하지 않는다.

### 10.12 R-11 — 통합 회귀·시각 기준선·bundle 분할

목표:

- 새 생애주기 화면을 결정적 fixture로 고정하고 초기 bundle 경고를 route 단위 분할로 줄인다.

기본 쓰기 범위:

- `web/frontend/tests/`
- `web/frontend/playwright.config.ts`
- `web/frontend/src/routes.tsx`
- 필요한 lazy import 경계
- 의도된 신규 snapshot

구현 계약:

- `visual.spec.ts`에 opportunity, pre-spec, document preparation, deep-review 상태, delta를 추가한다.
- 날짜, request ID, 진행 상태는 결정적 fixture로 고정한다.
- 기존 24개 snapshot 실패는 diff를 검토해 의도된 sidebar 변경과 실제 회귀를 분류한다.
- route lazy loading은 loading·error state와 SPA fallback을 유지한다.
- 번들 크기는 전후 production build 산출값을 같은 환경에서 기록한다.

완료 증거:

- 네 viewport에서 신규 기능·시각 spec이 통과한다.
- 전체 `npm run test:visual` 결과와 의도적 skip을 기록한다.
- snapshot 갱신 목록과 각 변경 이유를 인계에 남긴다.

### 10.13 실행 기록

작업을 완료한 세션만 행을 추가한다. 테스트를 실행하지 않은 부분 구현은 `완료`로 쓰지 않는다.

| 일자 | 작업 | 기준 HEAD | 결과 | 검증 | 남은 위험·다음 작업 |
|---|---|---|---|---|---|
| 2026-08-31 | R-01 | 52469dc | 완료 — legacy 첨부는 읽기 전용 이력으로만 표시하고 upload·delete control과 안전 경로 오인 문구를 제거했다. | `npm run build` 성공(282 modules); 지정 7개 spec의 4 viewport 직렬 통합 회귀 208 passed 중 `lifecycle-safety.spec.ts` 4 passed, legacy POST·DELETE 0건. | legacy backend 자체는 운영 차단 상태다. 후속 안전 첨부 통합은 별도 backend·보안 작업이다. |
| 2026-08-31 | R-02 | 52469dc | 완료 — route metadata로 누적·회차 문맥을 분리했고, ADR-0034가 제안인 동안 production bid-delta route·navigation을 제거했다. | 같은 build 성공; 통합 회귀 208 passed 중 `route-context.spec.ts` 72 passed, `common-interactions.spec.ts`에서 bid-delta navigation·요청 0건 확인. | ADR-0034 채택과 R-08 API 완료 전 bid-delta route를 복원하지 않는다. |
| 2026-08-31 | R-03 | 52469dc | 완료 — 사업기회 상세를 `/opportunities/:opportunityId` 정본 경로로 연결하고 filter·sort·offset·선택 복원과 추적 form 이탈 보호를 구현했다. | 같은 build 성공; 통합 회귀 208 passed 중 `opportunities.spec.ts` 20 passed. | 서버 relation projection을 프런트에서 보정하지 않는다. 향후 delta CTA는 R-09 이후에만 추가한다. |
| 2026-08-31 | R-04 | 52469dc | 완료 — `SW 중심 · 추적 예외 포함`, 명시적 전체 보기, `/pre-specs/:noticeId` 정본 상세, unknown·교차 notice fail-closed를 구현했다. | 같은 build 성공; 통합 회귀 208 passed 중 `pre-specs.spec.ts` 32 passed. URL 제어 checkbox의 Router render 대기를 보정한 뒤 4 viewport 모두 통과했다. | overview phase 2 실제 모델 worker·승인 binding은 별도 미구현 범위다. |
| 2026-08-31 | R-05 | 52469dc | 완료 — draft bundle 생성부터 upload·metadata patch·ready confirm·심층 검토 시작까지 안전한 문서 준비 작업대를 연결했다. | 같은 build 성공; 통합 회귀 208 passed 중 `document-preparation.spec.ts` 16 passed. actor·request ID·version snapshot, 부분 실패, 403·503 fail-closed를 확인했다. | 실제 운영 MinIO·ClamAV 권한 matrix와 legacy 첨부 통합은 여전히 운영 blocker다. |
| 2026-08-31 | R-06 | 52469dc | 완료 — active 상태 polling, 완료 뒤 report 조회, 실패 attempt append-only 재시작, 의견 live feedback·초안 보호를 구현했다. completed 직후 `409 review_not_ready`는 제한 재시도하고, 지속 409는 명시적 재조회로 넘긴다. | 같은 build 성공; 통합 회귀 208 passed 중 `deep-review.spec.ts` 40 passed. 회차 query를 보존하는 SPA 이동과 작은 화면 drawer 재개방을 포함한 이탈 보호 회귀를 보정했다. | 실제 Qwen/vLLM 품질 승인과 overview phase 2는 완료 근거가 아니다. |
| 2026-08-31 | R-07 | 52469dc | 설계 제안 완료 — exact snapshot fence, 계산/결과 상태 분리, 양쪽 evidence, append-only 사람 결정, stable error·DB·감사·테스트 matrix를 문서화했다. production route는 제거 상태다. | ADR-0034·계약 명세·정본 문서와 현재 route를 대조했고, 최종 문서 link·heading·표 형식 및 `git diff --check`를 확인했다. 코드·migration·endpoint는 만들지 않았다. | 사업개발 책임자의 enum·material 범주/임계값·currentness 결정과 보안/운영 책임자의 감사 경계 승인이 필요하다. ADR-0034 채택 전 R-08·R-09 진입 금지. |
| 2026-08-31 | R-10 | 52469dc | 완료 — StatusBadge·EmptyState·MutationFeedback·UnsavedGuard·ActorField·비활성 사유·focus/live feedback을 공통 계약으로 정리했다. | 같은 build 성공; 통합 회귀 208 passed 중 `common-interactions.spec.ts` 24 passed. UC-01~UC-05 keyboard 경로와 기존 queue 초안 보호를 확인했다. | 최종 시각 snapshot 승인과 route 단위 bundle 분할은 R-11 범위로 남는다. |
| 2026-08-31 | R-07 결정 | d323781 | ADR-0034 채택 — A1 `go\|no_go`, B1 7개 범주와 보수적 material v1, C1 strict, 회사 내부망 모델, safe audit allowlist를 확정했다. | ADR·계약·업무 규칙·결정 index·lifecycle·계획 문서 정합성 및 `git diff --check` 확인 | R-08 backend 진입 가능; R-09는 실제 R-08 API·typed error 검증 뒤에만 진입 |
| 2026-08-31 | R-08 | 84bbcc5 | 완료 — `bid_delta_comparison`·`bid_delta_attempt`·`bid_delta_item`·`bid_delta_evidence`·`bid_final_decision` 5개 table, revision `0015`, PostgreSQL append-only trigger와 SQLite ORM 미러, 5개 endpoint·schema·service를 구현했다. 비교 계산 worker와 모델 호출은 만들지 않았고, 내부 binding을 확인할 수 없으면 503으로 fail closed한다. | 백엔드 전체 `1032 passed, 5 skipped`(1건 실패는 닫힌 table 집합 assertion으로, `BID_DELTA_TABLES` 추가·`63→68` 갱신 뒤 `test_deep_review_migrations.py` 17 passed). 빈 PostgreSQL 17 `upgrade head`, `0014↔0015` 왕복, trigger 거부, `alembic check` 드리프트 0건, `test_bid_delta_models.py` 8 passed, `test_bid_delta_postgres.py` 5 passed, `test_bid_delta_api.py` 15 passed. | 계산 worker·모델 binding 실행과 운영 활성화는 별도 작업이다. baseline/bid role allowlist는 v1 기본값이며 업무 책임자 확인이 남았다. |
| 2026-08-31 | R-09 | 84bbcc5 | 완료 — 임시 `same`·단일 계산 상태 시안을 폐기하고 R-08 응답을 그대로 표현하는 type으로 교체했다. 후보 exact fence 선택, 계산/결과 상태 분리 표시, 양쪽 evidence 쌍, attempt 이력, 실패 재시도, append-only Go/No-Go form과 typed 409·503 처리, currentness 문자 표시, 이탈 보호를 구현했고 R-02가 제거한 bid-delta route를 metadata와 함께 복원했다. | `npx tsc -b` 통과, `npm run build` 285 modules 성공; `bid-delta`·`route-context`·`common-interactions`·`opportunities` 4 viewport `192 passed`. | 계산 worker가 없어 `pending`·`running`은 정상 대기로만 표시한다. 시각 snapshot은 R-11 범위다. |
| 2026-08-31 | R-11 (A) | 84bbcc5 | 완료 — route 단위 `React.lazy`와 `LazyRouteBoundary`(role=status 로딩, 오류 시 재시도 가능한 EmptyState)로 초기 bundle을 분할했다. route metadata는 lazy 경계 밖에 유지해 TopBar 문맥이 chunk 로딩과 무관하다. | `npx tsc -b` 통과; production build 초기 JS **758.53 kB(gzip 217.63) → 358.80 kB(gzip 113.07)**, 500 kB 경고 해소, asset 전량 `/assets/` 유지로 SPA fallback 보존. 기능 spec 9개 4 viewport `306 passed, 10 skipped`. | 시각 기준선은 R-11 (B)에 남았다. |
| 2026-08-31 | R-11 (B) | 84bbcc5 | 완료 — 사업기회·사전규격·문서 준비·심층 검토·입찰 delta의 17개 상태를 4 viewport 시각 회귀에 추가해 신규 snapshot 68개를 만들었다. 기존 48개 중 44개는 R-03·R-04 sidebar 항목 추가와 R-10 공통 컴포넌트라는 의도된 변경으로 분류해 갱신했고(`reviews`·`runs`의 mobile/tablet 4개는 통과해 갱신하지 않았다), diff를 직접 대조해 수치·상태·`계산 불가` 표현이 보존됐음을 확인했다. 위임 산출물의 제품 CSS 덮어쓰기·`waitForTimeout` flake 우회는 제거했다. | `npm run test:visual` **2회 연속 598 passed, 10 skipped, 0 failed**(10 skip은 `draft.spec.ts`의 wide-screen 전용). snapshot 전용 116개도 mask·restyling 없이 2회 연속 통과해 결정성을 확인했다. `npx tsc -b`·`npm run build` 성공, `./run-tests.sh` OK. | 신규 fixture는 `FIXED_TIME`·고정 UUID/hash를 쓰고 polling 응답을 동일 상태로 고정했다. 실제 모델·worker 산출물의 시각 기준선은 아직 없다. |
| 2026-08-31 | 회귀 수정 | 84bbcc5 | R-06 심층 검토 화면의 실제 반응형 회귀를 수정했다. `DeepReviewPage`의 단일 컬럼 grid 5곳이 `grid-template-columns` 없이 암묵적 `auto`(max-content) track을 써서, 완료 보고서의 넓은 표가 390px viewport를 754px로 밀어냈다(mobile 382px·tablet 4px 초과). `minmax(0, 1fr)`로 고쳤다. | 4 viewport 116개 overflow 검사 전부 통과. | 같은 패턴의 인라인 grid를 추가할 때 track 미지정을 반복하지 않도록 주의한다. |

현재 상태: R-01~R-11을 모두 완료했다. 초기 JS 500 kB 경고는 route 분할로 해소했고
(758.53 kB → 358.80 kB, gzip 217.63 → 113.07 kB), 시각 기준선은 신규 68개 생성과 기존 44개
갱신으로 정리했다.

남은 blocker는 코드가 아니라 운영·업무 승인이다.

- **입찰 delta 계산 worker와 내부 모델 binding 실행이 없다.** 비교 생성은 `pending`
  comparison과 `queued` attempt만 만들고 계산은 일어나지 않는다. 화면도 그 사실을 문자로
  안내한다. 운영 활성화는 이 worker 구현과 별도 결정 뒤의 일이다.
- baseline/bid document role allowlist(`제안요청서`·`과업지시서` / `공고`·`정정`·
  `제안요청서`·`과업지시서`)는 v1 기본값이며 사업개발 책임자 확인이 필요하다.
- 실제 모델 산출물이 들어간 심층 검토·delta 화면의 시각 기준선은 아직 없다.

### 10.14 콜드 세션 시작 지시문

새 세션에는 다음 한 문장과 작업 ID만 전달해도 된다.

```text
`docs/review/2026-08-31-ui-ux-remediation-plan.md`를 처음부터 끝까지 읽고 R-xx를 실행하라. 0절의 필수 문서·작업 트리 보호·중단 조건을 지키고, 허용 범위를 넓히지 말며, 검증과 10.13 실행 기록까지 완료하라.
```
