# 실무자 판정 5블록 화면과 REST — intent (초안, interview 전)

- 기능 ID: `HP-04-practitioner-verdict`
- 상위 항목: [HP 로드맵](../../../../constitution/roadmap.md), [HP 공통 계약](../../../../hp-contract.md) §8
- 크기: M — 새 REST 1개와 화면 1개(기존 회사 상세 안의 탭), mock fixture, 두 폭 검사. 외부 호출 없음.
- 작성일: 2026-10-14 (초안; D3·D6을 닫은 뒤 spec으로 간다)

## 문제

현재 회사 화면은 narrative 보고서 reader를 보여 준다. 실무자가 묻는 것은 "참여 가능한가, 무엇이 막는가, 무엇을 확인해야 하는가"이고 카드 단위 충족/부족/미확인과 원문 쪽으로의 점프가 필요하다.

## 기대 결과

회사별 사전규격 상세에 판정 탭이 생겨 다섯 블록(판정 카드 / 조건 체크리스트 / 요구사항 매트릭스 / 주의 포인트 / 다음 행동)을 한 화면에 보이고, 매트릭스의 카드를 누르면 원문 쪽으로 이동한다. 화면은 추적 승인·Go/No-Go를 저장하지 않는다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| 판정 조회 | `GET /api/companies/{company_id}/pre-specs/{notice_id}/verdict`(경로명 D6) | 종합 결과·체크리스트·매트릭스·주의·다음 행동·참조 표식·정책 identity |
| 화면 | `/companies/{id}/pre-specs/{notice}` 판정 탭 | 다섯 블록, 판정 enum과 참조 표식, 차단 조건 수 |
| 매트릭스 조작 | type·status 필터, 카드 클릭 | 필터 결과 수 일치, 클릭 시 `/pages/{page}`로 이동(상속 쪽은 "상속"으로 표시) |
| 미확인·실패 | unknown 항목, 실패한 분석 | unknown은 부족으로 보이지 않음; 실패는 사유와 사람 검토 안내 |
| 두 폭 검사 | Playwright 1280×800·1440×900 | 의미·구조 검사 통과, 가로 스크롤 규칙(ADR-0047) 유지 |
| mock | `tests/api-mock.ts`·`dev:mock` | fixture로 다섯 블록 상태 전부(진행 가능/조건부/어려움/판단 불가/실패) 재현 |

## 선행·후속 기능

- 선행: HP-03-two-tier-analysis.
- 후속: HP-06-gold-acceptance.

## 영향 범위

- 모듈·컴포넌트: frontend 회사 사전규격 상세(새 탭·컴포넌트), `companyApi.ts`, api-mock, backend verdict router·schema(HP-03 저장 결과의 조회).
- 큰 틀 문서의 절: HP 공통 계약 §8·11(D3·D6), contracts.md(새 GET), 0915 UI 정본(데스크톱 전용·테마 토큰).
- 데이터·저장소: 없음(조회만).
- 외부 서비스·호출: 없음.

## 제약

- (공통) feature.json constraints 전체를 따른다(HP-00 intent와 같은 목록).
- (기능별) Astryx 컴포넌트·테마 토큰만 사용, `:root` 색 재정의 금지, 데스크톱 전용. 판정은 보조 의견 표식과 함께 보인다.

## 범위 밖

판정 편집·주석, 알림, 여러 회사 비교(폐기), narrative reader 변경.

## 출처 간 차이

없음.

## 미해결 질문 (interview 항목)

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| D3 화면이 보이는 회사(DEMO 3사 row 처리) | spec 작성 전 | 제안: 활성 회사 목록 설정으로 HP 회사만 |
| D6 REST 경로·응답 키 | spec 작성 전 | 제안 `/pre-specs/{notice_id}/verdict` |
| 역할 간 충돌을 주의 포인트 안에 둘지 별도 블록으로 둘지 | spec 작성 전 | 제안: 주의 포인트 안에 "의견 불일치" 소제목 |
| 매트릭스 기본 정렬(카드 ID 순 vs 상태 순) | spec 작성 전 | 제안: 상태(gap→unknown→met) 뒤 카드 ID |
