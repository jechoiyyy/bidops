# BidOps UI/UX 고도화 계획

- 작성일: 2026-08-31
- 전제: [UI/UX 수정 계획](./2026-08-31-ui-ux-remediation-plan.md)의 P0·P1 흐름이 실제 계약과 함께 완료되어야 한다.
- 목표: 화면 수를 늘리는 것이 아니라 담당자가 놓치지 않고, 근거를 빠르게 확인하고, 사람 결정을 감사 가능하게 남기는 의사결정 작업대로 발전시킨다.

## 0. 보관 문서 안내

> **보관본이다. 실행 진입점이 아니다.**
>
> A-00~A-20은 착수하지 않았다. 이 문서를 읽고 새로 `A-xx`를 시작하거나, 본문이 제안하는
> 신규 명세 문서(`work-item-projection-spec`, `opportunity-timeline-spec`,
> `evidence-workspace-contract-audit`, `document-operations-queue-spec`,
> `ui-event-dictionary`)를 만들지 않는다. 현재 우선순위는 `docs/PRD.md`와
> `docs/PLAN.md`의 발주계획 C-2 선별이며, 여기의 화면 확장 항목은 그 뒤에 다시
> 판단할 아이디어 목록이다.
>
> 원래 경로는 `docs/legacy/review/2026-08-31-ui-ux-advancement-plan.md`였다.


## 1. 고도화 목표

BidOps의 목표 경험은 다음 한 문장으로 정의한다.

> 담당자가 오늘 다시 봐야 할 사업기회를 빠르게 찾고, 원문 근거와 변경 이유를 확인한 뒤, 자동화가 대신할 수 없는 사람 결정을 안전하게 남긴다.

고도화의 중심은 모델 결과를 더 화려하게 보여 주는 것이 아니다. 누적되는 발주계획·사전규격·입찰공고와 사람 판단을 하나의 생애주기로 읽게 하고, 왜 지금 이 항목이 다시 나타났는지 설명하는 것이다.

## 2. 제품 원칙

### 사람 결정 우선

- 적합성 등급, 참여 준비 상태, 개요 검토, 심층 검토 의견, 추적 상태, 최종 Go/No-Go를 별도 레이어로 유지한다.
- 시스템은 재검토 근거와 누락 위험을 알려도 사람 선택을 덮어쓰지 않는다.
- 자동 입찰과 발주처 연락은 범위 밖이다.

### 근거 우선

- 중요한 숫자·요구사항·변경은 원문 locator와 document version으로 돌아갈 수 있어야 한다.
- `changed`보다 “무엇이, 어느 버전에서, 어떤 근거로 바뀌었는가”를 먼저 보여 준다.
- 근거 검증 실패는 사람 확인 대기이며 자동 보정하지 않는다.

### 불확실성 보존

- `unknown`, 아직 계산하지 않음, 계산 실패, 실제 없음, 변경 없음은 서로 다른 상태다.
- 모델 confidence 하나로 상태를 축약하지 않는다.
- 시스템이 알 수 없는 이유와 사용자가 할 수 있는 다음 행동을 함께 표시한다.

### 점진적 공개

- 목록에는 우선순위와 다음 행동만, 상세에는 판단 근거, 감사 영역에는 기술 식별자를 둔다.
- hash, internal ID, validation code는 기본 업무 언어 뒤의 보조 정보로 배치한다.
- 전문가용 밀도는 유지하되 처음 보는 담당자도 현재 단계와 다음 행동을 이해할 수 있게 한다.

### 안전한 운영

- 외부 모델 전송 승인, 첨부 안전 검사, 불변 snapshot, claimed actor 경계를 UI에서 약화하지 않는다.
- 로그인·역할 권한이 생기기 전까지 개인화나 권한이 있는 것처럼 표현하지 않는다.

## 3. 목표 정보 구조

```text
오늘 할 일
├── 새로 들어온 사업기회
├── 재검토 필요
├── 문서 준비 차단·실패
├── 심층 검토 진행·실패
└── 입찰공고 변경·최종 결정 대기
    │
    └── 사업기회 상세
        ├── 생애주기 타임라인
        │   ├── 발주계획
        │   ├── 사전규격
        │   └── 입찰공고
        ├── 사람 결정 레이어
        │   ├── 추적 상태
        │   ├── 사전규격 심층검토 의견
        │   └── 최종 Go/No-Go
        ├── 시스템 분석 레이어
        │   ├── 1차 분류
        │   ├── 사전규격 개요 검토
        │   ├── 심층 검토
        │   └── material delta
        └── 근거·문서·감사 이력
```

기존 회차 중심 화면은 수집·판정 운영과 감사에 남긴다. 일상 의사결정의 시작점은 누적 사업기회와 오늘 할 일로 옮긴다.

## 4. 성숙도 단계

| 단계 | 이름 | 사용자에게 주는 가치 | 전제 |
|---|---|---|---|
| L0 | 안전하고 연결된 흐름 | 브라우저에서 막히지 않고 끝까지 처리 | 수정 계획 P0·P1 |
| L1 | 업무 작업대 | 오늘 해야 할 일과 다음 행동이 한곳에 모임 | 상태·기한·오류 projection |
| L2 | 근거 중심 의사결정 | 결과에서 원문과 변경 근거로 빠르게 이동 | document version·locator 계약 |
| L3 | 팀 운영과 품질 개선 | 병목·누락·재작업을 측정하고 개선 | 안전한 이벤트·지표 계약 |
| L4 | 역할 기반 협업 | 담당·승인·가시 범위를 역할에 맞춤 | SSO·RBAC·감사 정책 |

L4는 현재 사내망 경계와 claimed name만 있는 런타임에서 구현하지 않는다. L1~L3도 권한처럼 보이는 개인화를 먼저 만들지 않는다.

## 5. 고도화 트랙

### A. 오늘 할 일 중심의 Decision Cockpit

목표:

- 사용자가 여러 메뉴를 순회하지 않고 오늘 처리할 항목과 이유를 본다.

핵심 기능:

- `새로 유입`, `재검토 필요`, `마감 임박`, `문서 차단`, `분석 실패`, `최종 결정 대기` 작업 큐
- 각 항목에 `왜 지금 보이는가`, 마지막 사람 결정, 새로 추가된 공식 레코드, 다음 행동 표시
- 추적 상태·단계·D-day·담당 표식·오류 상태별 저장된 보기
- 업무량은 실제 0, 데이터 미적재, 계산 실패를 구분
- 카드에서 상세로 이동하고 처리 후 현재 큐의 다음 항목으로 복귀

주의:

- 우선순위 계산은 설명 가능한 결정적 규칙부터 시작한다.
- 발주계획 선별 순위는 품질 비교 실험과 사람 정답 보고서 승인 전 제품화하지 않는다.
- `종료`한 항목은 새 공식 레코드가 붙은 경우에만 재검토 큐에 다시 올리고 사람 상태는 유지한다.

완료 신호:

- 사용자는 대시보드에서 각 작업이 나타난 이유와 다음 행동을 설명할 수 있다.
- 큐에서 처리한 항목이 정의된 상태 전이에 따라 이동하며 단순 새로고침 때문에 사라지지 않는다.

### B. 사업기회 생애주기 타임라인

목표:

- 분리된 레코드 목록 대신 한 조달 건이 어떻게 변했는지 시간 순서로 이해한다.

핵심 기능:

- 발주계획·사전규격·입찰공고의 observation과 공식 연결을 시간축에 표시
- 후보 연결은 공식 연결과 다른 스타일·문구로 표시하고 사람 확인 대기로 유지
- 새 레코드, 문서 버전 변경, 개요 검토, 심층 attempt, 사람 결정, 재검토 신호를 구분
- 각 이벤트에서 당시 문서·분석·사람 기록 snapshot으로 이동
- 이벤트가 없는 구간을 “변경 없음”으로 추정하지 않음

완료 신호:

- 사용자가 현재 단계, 마지막 사람 결정, 그 뒤 새로 생긴 사실을 한 화면에서 찾는다.
- 같은 official identity가 중복 사업기회처럼 보이지 않는다.

### C. Evidence Workspace

목표:

- 분석 결과를 읽은 뒤 원문을 다시 찾는 비용을 줄인다.

핵심 기능:

- 왼쪽 원문 viewer, 가운데 추출 근거, 오른쪽 검토·결정의 3-pane 전문가 모드
- 숫자·자격·일정·평가·제출물별 evidence chip과 양방향 locator 이동
- source document/version/hash와 분석 attempt를 고정 표시
- 검증 성공, 근거 누락, locator 불일치, 사람 확인 완료를 별도 상태로 표시
- 사전규격과 입찰공고 evidence를 나란히 놓는 delta mode
- 키보드로 다음 미확인 근거 이동, 긴 문서 내 검색과 현재 위치 표시

주의:

- 원문 viewer는 허용된 객체·변환 산출물만 읽는다.
- 로컬 경로, signed URL, provider credential, 원문 전체를 로그나 analytics payload에 넣지 않는다.

완료 신호:

- 주요 분석 항목에서 원문 근거로 한 번의 명시적 행동으로 이동할 수 있다.
- 검증 실패 evidence가 성공 근거와 같은 모양으로 보이지 않는다.

### D. Material Delta 의사결정 보조

목표:

- 입찰공고가 나왔을 때 사전규격 대비 다시 읽어야 할 부분을 줄이되 최종 판단은 사람에게 남긴다.

핵심 기능:

- 범주별 `변경 있음 | 변경 없음 | 판단 불가 | 분석 실패` 요약
- 문장 수준 before/after와 양쪽 원문 locator
- 금액·기한·자격·배점 등 구조화 값은 결정적 validator 결과와 함께 표시
- 영향 메모는 “검토 포인트”로 표현하고 Go/No-Go 추천으로 가장하지 않음
- 최종 결정 전에 미확인 material change와 validation failure를 확인하는 checklist
- 과거 최종 결정과 새 결정의 이유를 append-only timeline으로 표시

완료 신호:

- 모든 material change가 기준·비교 문서 버전과 양쪽 근거를 가진다.
- `unknown`이나 failed가 0건 변경으로 집계되지 않는다.

### E. 문서 파이프라인 운영 UX

목표:

- 문서 준비 실패를 개발자 도움 없이 안전한 범위에서 분류·재개한다.

핵심 기능:

- upload, scan, convert, structure, review stage별 진행과 대기 시간
- blocked와 failed의 차이, 허용되는 복구 행동, 운영자에게 전달할 request ID
- 동일 파일 재등록, 새 document version, 새 bundle, 새 deep-review attempt의 차이를 안내
- 중복 실행을 막는 pending 상태와 멱등 request 피드백
- 부분 성공을 전체 성공처럼 보이지 않는 작업 단위 결과

주의:

- 바이러스·경로 이탈·승인 없는 외부 전송 문제는 재시도 권장보다 실행 중지와 보고를 우선한다.
- ready bundle이나 완료 attempt를 고치는 “수정” 버튼을 만들지 않는다.

완료 신호:

- 사용자가 실패 유형과 가능한 다음 행동을 구분한다.
- 운영자가 안전한 request ID만으로 관련 구조화 로그를 찾을 수 있다.

### F. 팀 협업과 인수인계

목표:

- 동일 사업기회를 여러 담당자가 검토해도 결론과 남은 질문이 분리되어 남는다.

L4 전 준비 기능:

- claimed actor가 있는 결정 이력과 `다음 담당자에게 남길 확인사항`
- 근거에 연결된 review note와 해결·미해결 상태
- 업무 상태 변경 이유와 시각의 append-only 표시
- 브라우저 단일 세션에서만 사용하는 개인 초안과 서버에 남는 공식 기록을 시각적으로 분리

SSO·RBAC 후 기능:

- 실제 사용자 identity, 역할별 mutation 권한, 담당자 배정, 승인 요청
- 팀·역할별 saved view와 notification preference
- 대리 승인·권한 변경 감사

금지:

- claimed actor 이름을 실제 로그인 사용자처럼 표시하지 않는다.
- SSO 전 담당자 필터를 접근 통제나 업무 소유권으로 사용하지 않는다.

### G. 접근성·반응형·성능 기반

목표:

- 정보 밀도를 유지하면서 다양한 화면과 입력 방식에서 핵심 업무를 막지 않는다.

핵심 기능:

- semantic token, 상태 컴포넌트, focus ring, live region, dialog focus trap 표준화
- 390/768/1024/1440px의 화면별 density profile
- 모바일은 목록과 상세을 분리하고 현재 위치·목록 복귀 제공
- 표는 우선 열을 고정하고 나머지는 상세 disclosure로 이동
- route 단위 code splitting, 긴 evidence 목록 virtualize, 원문 viewer 지연 로드
- skeleton은 구조 유지에만 사용하고 실제 상태명은 숨기지 않음

완료 신호:

- 키보드만으로 주요 사용 시나리오를 완료한다.
- 텍스트·상태 대비와 target size가 승인된 접근성 기준을 통과한다.
- 성능 최적화 전후의 초기 bundle, route load, 긴 목록 반응 시간을 같은 조건에서 기록한다.

## 6. 단계별 실행 로드맵

### Horizon 0. 안전·계약·측정 기준선

선행 작업:

- 수정 계획 P0·P1 완료
- delta와 최종 결정 계약 확정
- 신규 생애주기 visual·functional test 추가
- event 이름, 상태 의미, 민감정보 제외 규칙 확정

산출물:

- 핵심 task flow별 현재 성공·실패 기준선
- route별 데이터 scope와 mutation scope 표
- UI event dictionary와 보안 검토
- 디자인 시스템 최소 계약

종료 gate:

- 브라우저만으로 UC-01~UC-05를 완료한다.
- 실제 운영 E2E를 아직 검증하지 않았다면 mock 통과와 명확히 구분한다.

### Horizon 1. Decision Cockpit과 생애주기 상세

구현 순서:

1. 오늘 할 일 projection API 또는 기존 계약의 안전한 합성 경계 정의
2. 작업 큐와 이유 설명
3. 사업기회 생애주기 타임라인
4. 목록 처리 후 다음 항목과 복귀 문맥
5. 실패·차단 운영 큐 연결

종료 gate:

- 시스템 신호와 사람 결정을 섞지 않고 큐 이동 규칙을 테스트한다.
- 종료 건 재노출, 신규 사전규격, delta 대기의 대표 fixture를 통과한다.

### Horizon 2. Evidence Workspace와 delta 비교

구현 순서:

1. document version·locator viewer 계약
2. evidence deep-link와 검증 상태
3. 사전규격/입찰공고 나란히 보기
4. 범주별 delta checklist
5. 최종 사람 결정 이력과 감사 연결

종료 gate:

- 주요 숫자·요구사항·변경이 원문에 연결된다.
- 잘못된 locator, 누락 근거, 문서 version 불일치 fixture가 fail-closed로 보인다.

### Horizon 3. 팀 운영과 품질 개선

구현 순서:

1. 안전한 UI event와 업무 병목 대시보드
2. 재작업·실패 유형 분석
3. 저장된 보기와 팀 인수인계 노트
4. SSO·RBAC 도입 결정 후 실제 담당·승인 흐름
5. 승인된 채널에 한한 notification

종료 gate:

- 지표가 원문·회사자료·민감 payload를 포함하지 않는다.
- SSO 전후 기능 경계와 권한 테스트가 문서화된다.

## 7. 측정 계획

현재 기준값을 측정하지 않았으므로 아래 수치의 목표값을 임의로 확정하지 않는다. Horizon 0에서 기준선을 만들고 담당자와 목표를 승인한다.

### 업무 효율

| 지표 | 정의 |
|---|---|
| 첫 행동까지 시간 | 오늘 할 일 진입부터 첫 유효 mutation까지 |
| 사업기회 처리 시간 | 상세 진입부터 추적 상태 또는 다음 단계 기록까지 |
| 근거 확인 시간 | 분석 항목 선택부터 대응 원문 위치 확인까지 |
| delta 검토 시간 | 비교 화면 진입부터 최종 결정 저장 또는 보류까지 |
| 화면 왕복 수 | 한 task를 완료하기 위한 route transition 수 |

### 품질과 안전

| 지표 | 정의 |
|---|---|
| 미저장 유실 재현 건수 | 테스트·지원 기록에서 초안이 안내 없이 사라진 건수 |
| 잘못된 정본 이동 | 선택 notice/opportunity가 다른 정본으로 치환된 건수 |
| unknown 오표현 | unknown/failed가 없음·성공·변경 없음으로 보인 건수 |
| 근거 도달률 | 근거가 필요한 결과 중 유효 locator로 원문 이동 가능한 비율 |
| 감사 완결률 | mutation에 actor·reason·request ID·version이 모두 있는 비율 |

### 운영 안정성

| 지표 | 정의 |
|---|---|
| 단계별 대기 시간 | upload/scan/convert/structure/analysis 각 단계의 elapsed time |
| 사용자 재시도율 | 동일 실패에서 사용자가 반복 mutation한 비율 |
| 복구 성공률 | 허용된 재시작 뒤 terminal success에 도달한 비율 |
| 오류 분류 불가율 | 안전한 오류 code나 다음 행동이 없는 실패 비율 |

analytics에는 원문, 회사자료, 검색어 전문, 담당자 메모 전문, signed URL, API key, 로컬 경로를 넣지 않는다. ID도 정책상 승인된 내부 식별자만 사용한다.

## 8. 사용자 검증 계획

### 참여자와 과업

최소 역할은 다음 세 가지로 나눈다. 실제 인원과 표본 수는 운영 담당자가 승인한다.

- 매일 발주계획·사전규격을 훑는 사업개발 담당자
- 문서와 근거를 깊게 확인하는 심층 검토 담당자
- 최종 입찰 참여 판단을 남기는 책임자

과업:

1. 새 발주계획에서 추적 대상을 고르고 이유를 남긴다.
2. `SW사업대상=N` 추적 예외 사전규격을 찾아 개요 검토 상태를 설명한다.
3. 차단 문서가 섞인 bundle에서 가능한 다음 행동을 고른다.
4. 실패한 심층 검토를 새 attempt로 재시작하고 과거 이력을 찾는다.
5. `unknown` delta가 있는 입찰공고에서 최종 결정을 보류하고 이유를 남긴다.
6. 종료 뒤 새 공식 레코드가 붙은 사업기회를 재검토한다.

관찰 항목:

- 현재 단계와 다음 행동을 말로 설명하는가
- 시스템 판단과 사람 결정을 구분하는가
- 원문 근거를 찾는 데 어디서 멈추는가
- disabled 상태의 이유를 이해하는가
- 뒤로 가기·새로고침 뒤 작업 문맥을 복구하는가

인터뷰 결과는 화면 선호가 아니라 과업 성공, 오류, 망설임, 잘못된 해석을 중심으로 기록한다.

## 9. 실험과 의사결정 gate

| 주제 | 먼저 필요한 근거 | 승인 전 금지 |
|---|---|---|
| 발주계획 추천·랭킹 | 고정 3일 표본의 키워드·ColBERT·Qwen·GPT Luna 비교와 사람 정답 보고서 | 추천 점수 제품화, 자동 추적 상태 |
| delta 범주·material 기준 | REST·DB 계약, gold fixture, 결정적 validator | 최종 Go/No-Go 자동 추천 |
| 개인화 작업 큐 | SSO·RBAC 결정과 접근 정책 | claimed name 기반 권한·비공개 보기 |
| 알림 | 승인 채널, 수신 대상, 민감정보 최소 payload | 외부 채널 자동 전송 |
| UI analytics | event dictionary와 보안 검토 | 원문·회사자료·메모 전문 수집 |

## 10. 기술·계약 의존성

### 프런트 단독으로 가능한 범위

- route metadata와 URL 상태
- 공통 상태·feedback·dirty guard
- 기존 API를 사용하는 문서 준비와 deep-review retry
- 접근성·반응형·lazy loading
- mock 기반 use-case와 visual test

### 백엔드 계약이 먼저 필요한 범위

- 오늘 할 일의 누적 projection과 stable pagination
- material delta 조회와 계산 상태
- 최종 Go/No-Go append-only 저장·이력
- evidence locator deep-link에 필요한 안전한 projection
- 팀 saved view·담당·승인 workflow
- 측정 event의 저장·보존·열람 정책

### 운영·보안 결정이 먼저 필요한 범위

- SSO·역할 기반 권한
- 외부 알림
- 개인별 업무 배정
- 실제 모델·원문 payload가 포함되는 기능

## 11. 릴리스 전략

- 화면별 대규모 교체보다 `오늘 할 일 → 사업기회 → 다음 단계`의 수직 슬라이스로 배포한다.
- 신규 계약은 additive하게 도입하고 기존 소비자를 한 번에 깨지 않는다.
- 읽기 projection을 먼저 검증한 뒤 mutation을 연다.
- production control은 backend endpoint와 감사 테스트가 없으면 비활성 또는 명시적 준비 중으로 남긴다.
- 시각 snapshot은 의도된 diff를 검토한 뒤에만 갱신한다.
- 장애 시 hosted OpenAI fallback, 자동 상태 보정, 기존 기록 덮어쓰기로 복구하지 않는다.

## 12. 고도화 완료 정의

고도화 기능은 다음을 모두 만족해야 완료다.

- 실제 사용자 과업과 연결되고, 왜 필요한지 측정 지표가 있다.
- 현재 단계, 정본 데이터 범위, 편집 가능한 사람 기록이 명확하다.
- 모든 중요 결과가 source version과 locator 또는 명시적 `unknown`을 가진다.
- 사람 결정과 시스템 신호가 데이터와 화면 모두에서 분리된다.
- 불변 기록과 감사 경계를 보존한다.
- API·DB·보안 의존성이 문서화되고 테스트된다.
- 키보드, 작은 화면, 오류·빈 상태·장시간 진행 상태를 포함한 회귀 테스트가 있다.
- 운영 근거가 없는 목표 수치나 모델 품질을 달성했다고 표현하지 않는다.

## 13. 권장 착수 순서

1. 수정 계획의 legacy 차단과 정본 라우팅
2. 사전규격 개요·문서 준비·심층 검토의 수직 흐름
3. delta·최종 결정 계약과 화면
4. Horizon 0 기준선 측정
5. Decision Cockpit과 생애주기 타임라인
6. Evidence Workspace와 delta 근거 비교
7. 운영 지표와 팀 인수인계
8. SSO·RBAC 승인 후 역할 기반 협업과 알림

이 순서를 건너뛰고 dashboard 추천이나 개인화를 먼저 만들면 아직 연결되지 않은 핵심 흐름과 인증 부재를 가리게 된다.

## 14. 콜드 세션 작업 명령

### 14.1 작업 인덱스

| ID | 작업 | 유형 | 선행조건 | 기본 상태 |
|---|---|---|---|---|
| A-00 | L0 준비도 감사와 UX 기준선 | 검증·문서 | 의존 R 작업 확인 | 항상 첫 재확인 |
| A-01 | 오늘 할 일 projection 계약 | 설계 | A-00 | 미착수 |
| A-02 | 오늘 할 일 backend | 구현 | A-01 채택 | 진입 금지 |
| A-03 | Decision Cockpit frontend | 구현 | A-02 | 진입 금지 |
| A-04 | 생애주기 event projection 계약 | 설계 | A-00, R-03·R-09 | 미착수 |
| A-05 | 생애주기 event backend | 구현 | A-04 채택 | 진입 금지 |
| A-06 | 생애주기 timeline frontend | 구현 | A-05 | 진입 금지 |
| A-07 | evidence deep-link·viewer 계약 감사 | 설계 | R-05·R-06·R-09 | 미착수 |
| A-08 | evidence projection backend 보강 | 구현 | A-07에서 필요 판정·채택 | 진입 금지 |
| A-09 | Evidence Workspace frontend | 구현 | A-07, 필요 시 A-08 | 진입 금지 |
| A-10 | 문서 파이프라인 운영 큐 계약 | 설계 | R-05·R-06 | 미착수 |
| A-11 | 문서 운영 큐 backend | 구현 | A-10 채택 | 진입 금지 |
| A-12 | 문서 운영 UX frontend | 구현 | A-11 | 진입 금지 |
| A-13 | UI 측정 event·보존 계약 | 설계 | A-00, 보안 검토 | 미착수 |
| A-14 | 안전한 측정 backend | 구현 | A-13 채택 | 진입 금지 |
| A-15 | 업무 품질 dashboard frontend | 구현 | A-14 | 진입 금지 |
| A-16 | 접근성·성능 고도화 | 구현·검증 | 주요 화면 안정화 | 미착수 |
| A-17 | 협업·SSO·RBAC·알림 경계 | 설계 | 운영 결정 | 결정 대기 |

### 14.2 A-00 — L0 준비도 감사와 UX 기준선

목표:

- 고도화가 핵심 흐름의 미완성을 가리지 않도록 현재 HEAD의 실제 준비도를 기록한다.

기본 쓰기 범위:

- 신규 `docs/validation-runs/<YYYYMMDD>-ui-ux-l0-baseline.md`
- 필요하면 이 문서 14.20절
- 코드 변경 금지

확인 항목:

- 수정 계획 R-01~R-09의 현재 코드·테스트·실행 기록
- UC-01~UC-05가 브라우저만으로 완료되는지
- delta backend와 최종 결정 mutation의 실제 존재 여부
- 신규 lifecycle 화면의 Playwright와 네 viewport coverage
- production build bundle과 기존 테스트 실패
- 운영 stack 미기동, mock, 실제 E2E를 서로 다른 증거로 구분

검증:

- `npm run build`
- 관련 lifecycle Playwright spec
- 필요하면 backend 대상 API test
- 전체 visual은 기준선 비용과 현재 실패를 기록할 필요가 있을 때 실행

종료 gate:

- 누락된 R 작업이 있으면 다음 작업을 해당 R ID로 지정하고 A-01 이후에 진입하지 않는다.
- 실제 사용자 시간·성공률 자료가 없으면 `unknown`으로 기록한다.

### 14.3 A-01 — 오늘 할 일 projection 계약

목표:

- dashboard가 여러 endpoint를 임의 결합하지 않도록 누적 작업 항목의 안전한 읽기 계약을 설계한다.

작업 유형:

- 설계 전용

기본 쓰기 범위:

- `docs/contracts.md`
- `docs/business-rules.md`는 새 의미가 합의된 경우만
- `docs/tracking/decisions/index.md`
- 신규 `docs/tracking/decisions/<next>-work-item-projection.md`
- 필요하면 `docs/legacy/review/work-item-projection-spec.md`

필수 결정:

- reason code: 신규 유입, 종료 후 재검토, 마감 임박, 문서 차단, 분석 실패, 최종 결정 대기
- 하나의 사업기회가 여러 reason을 가질 때 표시·정렬·중복 제거
- `as_of`, stable cursor, page size, total 의미
- 사람 추적 상태와 시스템 reason의 분리
- D-day의 시간대·null·마감 지남 의미
- explainable deterministic sort와 tie-breaker
- SSO 전 actor·assignee projection의 제한
- 404/409/422/503과 부분 projection 실패

금지:

- 모델 score·추천 rank
- 자동 추적 상태 변경
- 사용자별 권한 또는 개인 queue 가장

완료 증거:

- request/response 예시, 상태표, 정렬 규칙, 테스트 matrix가 있다.
- ADR은 승인 전 `제안` 상태다.

### 14.4 A-02 — 오늘 할 일 backend

진입 gate:

- A-01 ADR과 wire contract가 채택되어야 한다.

기본 쓰기 범위:

- 신규 `web/backend/app/schemas/work_items.py`
- 신규 `web/backend/app/services/work_items.py`
- 신규 `web/backend/app/routers/work_items.py`
- `web/backend/app/main.py`
- `web/backend/tests/test_work_items.py`
- migration은 채택 계약상 저장 상태가 꼭 필요한 경우만

구현 계약:

- 기존 canonical opportunity·document·attempt·decision 상태를 projection하고 별도 업무 규칙을 복제하지 않는다.
- 안정 정렬·cursor·as_of를 서버가 제공한다.
- reason별 실패를 전체 성공이나 0으로 숨기지 않는다.
- 응답에 원문·메모 전문·파일명·객체 key를 넣지 않는다.
- 조회가 사람 상태를 mutation하지 않는다.

완료 증거:

- reason별 fixture, 다중 reason, stable pagination, null deadline, 종료 후 재검토를 검사한다.
- query count와 대표 데이터 규모에서의 실행 계획을 기록하되 측정하지 않은 성능을 주장하지 않는다.

### 14.5 A-03 — Decision Cockpit frontend

진입 gate:

- A-02의 실제 API와 typed 오류가 있어야 한다.

기본 쓰기 범위:

- `web/frontend/src/pages/DashboardPage.tsx` 또는 신규 `WorkItemsPage.tsx`
- 신규 `web/frontend/src/components/work-items/`
- `web/frontend/src/routes.tsx`
- 관련 dashboard style
- `web/frontend/tests/work-items.spec.ts`
- 결정적 fixture

구현 계약:

- 항목마다 `왜 지금 보이는가`, 현재 사람 상태, 새 사실, 다음 행동을 표시한다.
- reason·단계·D-day filter를 URL에 보존한다.
- 처리 뒤 다음 항목 또는 원래 queue 문맥으로 예측 가능하게 돌아간다.
- 권한·개인 배정처럼 보이는 표현을 사용하지 않는다.
- 추천 점수·자동 Go/No-Go를 추가하지 않는다.

완료 증거:

- 신규, 다중 reason, 종료 후 재검토, blocked, failed, 빈 상태, API 오류를 검사한다.
- 새로고침·뒤로 가기·390/768/1024/1440px·keyboard flow를 검사한다.

### 14.6 A-04 — 생애주기 event projection 계약

목표:

- 사업기회의 레코드·분석·사람 판단 이력을 시간축에서 안전하게 읽는 계약을 설계한다.

작업 유형:

- 설계 전용

기본 쓰기 범위:

- `docs/contracts.md`
- `docs/tracking/decisions/index.md`
- 신규 `docs/tracking/decisions/<next>-opportunity-event-projection.md`
- 필요하면 `docs/legacy/review/opportunity-timeline-spec.md`

필수 결정:

- event kind와 canonical source ID
- 관측 시각, 발생 시각, 저장 시각의 구분
- official·candidate·검색 미확인 link 표현
- review·bundle·attempt·opinion·tracking·delta·final decision snapshot reference
- actor name 공개 범위와 SSO 전 의미
- cursor, 동시 시각 tie-breaker, 삭제·정정·superseded 표현
- 사건이 없는 구간을 unchanged로 추정하지 않는 계약

완료 증거:

- 같은 사실을 새 event table에 복제할지 live projection할지 대안과 비용이 있다.
- append-only 정본을 덮어쓰지 않는 테스트 matrix가 있다.

### 14.7 A-05 — 생애주기 event backend

진입 gate:

- A-04가 채택되어야 한다.

기본 쓰기 범위:

- 신규 `web/backend/app/schemas/opportunity_events.py`
- 신규 `web/backend/app/services/opportunity_events.py`
- 기존 또는 신규 opportunity router
- `web/backend/tests/test_opportunity_events.py`
- migration은 채택 계약이 materialized event를 요구할 때만

구현 계약:

- canonical source와 event를 양방향 추적할 수 있어야 한다.
- candidate를 official로 표현하지 않는다.
- actor, reason, 원문 projection은 최소 필드만 반환한다.
- pagination 중 중복·누락이 없도록 정렬 fence를 갖는다.

완료 증거:

- 동일 timestamp, candidate→사람 확인, 종료 후 새 official link, failed→retry attempt를 검사한다.
- source record 삭제·부재·권한 오류를 안전하게 처리한다.

### 14.8 A-06 — 생애주기 timeline frontend

진입 gate:

- A-05 API가 있어야 한다.

기본 쓰기 범위:

- R-03의 사업기회 상세
- 신규 `web/frontend/src/components/opportunity-timeline/`
- 관련 style
- `web/frontend/tests/opportunity-timeline.spec.ts`

구현 계약:

- 발주계획, 사전규격, 입찰공고, 시스템 분석, 사람 결정을 같은 색·도형 하나로 축약하지 않는다.
- 현재 단계, 마지막 사람 결정, 그 뒤 새 사실을 첫 화면에서 찾게 한다.
- 각 event는 canonical detail 또는 immutable snapshot으로 이동한다.
- 기술 ID는 보조 disclosure에 둔다.

완료 증거:

- official/candidate, 새 사실 없음, retry, 과거 최종 결정, 긴 timeline과 좁은 화면을 검사한다.
- event가 없어도 “변경 없음” 문구를 만들지 않는다.

### 14.9 A-07 — evidence deep-link·viewer 계약 감사

목표:

- 기존 `/api/evidence/{id}`와 document projection이 Evidence Workspace에 충분하고 안전한지 확인한다.

작업 유형:

- 조사·설계 전용

기본 쓰기 범위:

- 신규 `docs/legacy/review/evidence-workspace-contract-audit.md`
- 변경이 필요하면 `docs/contracts.md`와 신규 ADR 제안
- 코드 변경 금지

확인 항목:

- evidence ID→document version→structure/page/block 추적 가능성
- page·block locator의 안정성과 잘못된 locator 응답
- profile evidence와 document evidence의 구분
- bid delta before/after 근거 쌍
- source hash·validation status·attempt/revision 연결
- 원문 전체, object key, signed URL, filesystem path 노출 여부
- 현재 `DeepReviewPage.tsx`의 부분 evidence viewer와 중복 가능성

종료 분기:

- 기존 API로 충분하면 A-08을 `불필요`로 기록하고 A-09로 간다.
- projection 보강이 필요하면 ADR 승인 전 A-08에 진입하지 않는다.

### 14.10 A-08 — evidence projection backend 보강

진입 gate:

- A-07이 gap을 확인했고 보강 계약이 채택되어야 한다.

기본 쓰기 범위:

- `web/backend/app/services/evidence.py`
- 관련 named schema·router
- `web/backend/tests/test_deep_reviews.py` 또는 신규 evidence API test
- `docs/contracts.md`

구현 계약:

- 승인된 안전 projection만 추가한다.
- source version/hash와 locator mismatch를 0건 결과로 숨기지 않는다.
- page/block pagination과 최대 payload를 제한한다.
- 원문·object key·signed URL·내부 path를 응답이나 오류에 넣지 않는다.

완료 증거:

- valid, missing, stale hash, malformed locator, profile/document evidence, oversized page를 검사한다.

### 14.11 A-09 — Evidence Workspace frontend

진입 gate:

- A-07에서 기존 API 충분 판정 또는 A-08 완료가 필요하다.

기본 쓰기 범위:

- 신규 `web/frontend/src/components/evidence-workspace/`
- `web/frontend/src/pages/DeepReviewPage.tsx`
- `web/frontend/src/pages/BidDeltaDecisionPage.tsx`
- 관련 style
- `web/frontend/tests/evidence-workspace.spec.ts`

구현 계약:

- 원문 projection, 선택 claim/evidence, 사람 검토를 3-pane 또는 작은 화면의 단계형 disclosure로 제공한다.
- evidence chip에서 한 번의 명시적 행동으로 locator를 연다.
- 문서 version/hash/validation은 항상 확인 가능하되 업무 설명보다 앞세우지 않는다.
- missing·mismatch·validation failed를 정상 quote와 같은 모양으로 표시하지 않는다.
- deep review와 delta가 공통 viewer를 쓰되 before/after 의미는 유지한다.

완료 증거:

- keyboard next evidence, deep-link 복원, 긴 block, missing locator, 양쪽 delta evidence를 네 viewport에서 검사한다.

### 14.12 A-10 — 문서 파이프라인 운영 큐 계약

목표:

- 개별 상세을 열기 전에 upload/scan/convert/structure/analysis의 대기·차단·실패를 찾는 누적 projection을 설계한다.

작업 유형:

- 설계 전용

기본 쓰기 범위:

- `docs/contracts.md`
- `docs/security.md`는 정책 변경이 합의된 경우만
- 신규 ADR과 `docs/legacy/review/document-operations-queue-spec.md`

필수 결정:

- stage와 terminal/active 상태
- notice·opportunity로 돌아가는 안전한 식별자
- request ID 공개 범위와 original filename 제외 여부
- retry 가능·사람 확인·즉시 중단 action
- 대기 시간의 시작점과 `unknown`
- pagination·보존기간·완료 항목 제외 규칙

금지:

- 원문명·path·provider 오류 전문 노출
- blocked 파일의 자동 재시도
- ready bundle·완료 attempt 수정

### 14.13 A-11 — 문서 운영 큐 backend

진입 gate:

- A-10 계약 채택

기본 쓰기 범위:

- 신규 named schema/service/router
- `web/backend/app/main.py`
- 신규 `web/backend/tests/test_document_operations.py`
- migration은 채택 계약이 새 상태를 요구할 때만

구현 계약:

- 기존 document/attempt 상태를 projection하고 새로운 truth를 만들지 않는다.
- 안전한 request ID와 안정 error code만 제공한다.
- 조회가 retry나 상태 보정을 실행하지 않는다.

완료 증거:

- 각 stage, 부분 실패, blocked, stale active, missing canonical record, pagination을 검사한다.

### 14.14 A-12 — 문서 운영 UX frontend

진입 gate:

- A-11 API 완료

기본 쓰기 범위:

- 신규 `web/frontend/src/pages/DocumentOperationsPage.tsx`
- 신규 `web/frontend/src/components/document-operations/`
- `web/frontend/src/routes.tsx`와 `Sidebar.tsx`
- 전용 style과 `web/frontend/tests/document-operations.spec.ts`

구현 계약:

- 단계, 경과 시간, 실패 범주, 허용 다음 행동을 표시한다.
- detail의 안전한 retry control을 재사용하고 queue에서 임의 상태 변경을 만들지 않는다.
- 바이러스·경로·외부 전송 문제는 재시도보다 중지·보고를 먼저 표시한다.
- 부분 성공을 전체 완료로 표시하지 않는다.

완료 증거:

- active, failed, blocked, needs_review, empty, stale fixture와 keyboard·좁은 화면을 검사한다.

### 14.15 A-13 — UI 측정 event·보존 계약

목표:

- 업무 개선을 측정하되 원문·회사자료·메모를 analytics로 복제하지 않는 event 계약을 설계한다.

작업 유형:

- 설계·보안 검토 전용

기본 쓰기 범위:

- 신규 ADR
- `docs/contracts.md`
- `docs/security.md`는 승인된 정책만 반영
- 신규 `docs/legacy/review/ui-event-dictionary.md`

필수 결정:

- 허용 event name과 최소 field allowlist
- session·actor 식별의 SSO 전 한계
- client time과 server time의 역할
- 중복·재전송·idempotency
- 보존기간, 접근 주체, 삭제·집계 정책
- 금지 payload와 redaction test
- 실제 사용자 과업 시간과 시스템 stage 시간의 구분

중단 gate:

- 보존기간·열람 주체·법적 또는 사내 정책 결정이 없으면 제안 상태로 끝낸다.

### 14.16 A-14 — 안전한 측정 backend

진입 gate:

- A-13 보안·계약 승인

기본 쓰기 범위:

- named event schema/service/router/model
- Alembic migration
- backend event·redaction·retention test
- 운영 문서

구현 계약:

- allowlist 외 필드는 422로 거부한다.
- 원문·메모·검색어·파일명·URL·path·credential을 저장하지 않는다.
- actor name을 인증 identity로 승격하지 않는다.
- retention은 startup side effect가 아니라 승인된 운영 절차로 실행한다.

완료 증거:

- 허용·금지 payload, replay, clock skew, retention, 권한 없는 조회, 로그 redaction을 검사한다.

### 14.17 A-15 — 업무 품질 dashboard frontend

진입 gate:

- A-14의 승인된 aggregate API와 실제 기준선 데이터가 필요하다.

기본 쓰기 범위:

- `web/frontend/src/pages/MetricsPage.tsx`
- 관련 metrics component·type·style
- `web/frontend/tests/metrics-ux.spec.ts`

구현 계약:

- 기준선 없음, 표본 부족, 실제 0, 계산 실패를 구분한다.
- 개인 순위나 성과평가로 오인되는 claimed actor 비교를 만들지 않는다.
- 업무 효율·품질·운영 안정성 지표의 정의와 관측 기간을 표시한다.
- 상관을 원인이나 모델 품질 개선으로 단정하지 않는다.

완료 증거:

- no baseline, partial period, zero, unavailable, trend fixture를 검사한다.

### 14.18 A-16 — 접근성·성능 고도화

진입 gate:

- 최적화할 주요 route와 대표 데이터 fixture가 안정화되어야 한다.

기본 쓰기 범위:

- `web/frontend/src/routes.tsx`
- 공통 UI·style
- 긴 목록·evidence component
- Playwright 접근성·성능 fixture
- `docs/validation-runs/<YYYYMMDD>-frontend-performance.md`

구현 계약:

- route lazy loading, 긴 목록 virtualization, 원문 viewer 지연 로드를 측정 뒤 적용한다.
- keyboard focus, screen-reader 상태, search/find, URL deep-link를 virtualization 때문에 깨지 않는다.
- 동일 장비·fixture의 전후 초기 JS, route load, interaction 시간을 기록한다.
- 목표 수치는 기준선과 승인 없이 임의 확정하지 않는다.

완료 증거:

- production build bundle 전후, 네 viewport visual, keyboard 시나리오가 있다.
- 성능 개선이 상태 의미·근거 접근성·오류 표현을 약화하지 않는다.

### 14.19 A-17 — 협업·SSO·RBAC·알림 경계

목표:

- claimed actor에서 실제 identity·역할 기반 workflow로 넘어가기 전에 권한·감사·알림 경계를 결정한다.

작업 유형:

- 설계 전용이며 운영 책임자·보안 책임자의 결정이 필요하다.

기본 쓰기 범위:

- 신규 ADR 또는 decision-pending 문서
- `docs/security.md`
- `docs/contracts.md`
- `docs/architecture.md`
- `docs/operations.md`

필수 결정:

- identity provider, user lifecycle, role와 mutation matrix
- 기존 claimed actor 기록의 보존·표시
- 담당 배정, 승인 요청, 대리 승인, 권한 변경 감사
- 알림 채널 allowlist, 최소 payload, 실패·재전송·해지
- 팀 saved view와 개인 preference의 소유권·삭제

금지:

- 결정 전 SSO mock을 production 인증처럼 연결
- claimed name 기반 접근 통제
- 외부 채널에 공고 원문·회사자료·내부 메모 전송

종료 gate:

- 필요한 운영 결정을 받을 때까지 구현 작업 ID를 만들지 않는다.

### 14.20 실행 기록

작업을 완료한 세션만 행을 추가한다. 설계는 제안·채택 상태를 결과에 명시한다.

| 일자 | 작업 | 기준 HEAD | 결과 | 검증·측정 | 남은 gate·다음 작업 |
|---|---|---|---|---|---|
| — | — | — | 아직 기록 없음 | — | — |

### 14.21 콜드 세션 시작 지시문
이 계획을 새 세션에 전달하는 실행 프롬프트가 여기 있었다. 착수 결정 전이므로 제거했다.
