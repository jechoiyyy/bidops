# 회사 전환·그래프·비교·추적 화면 — spec

- 기능 ID: `DEMO-04-review-workspace`
- 작성일: 2026-10-06 (같은 날 재계획 개정)
- 근거: [intent](intent.md), [공통 계약](../../../../demo-contract.md) §1·2·4·6·9
- 상태: 구현 목표. 현재 제품 계약과 구별한다. 데모 브랜치 전용이며 운영에 배포하지 않는다.

## 큰 틀 문서와의 관계

ADR-0070 및 기존 정본의 DEMO 목표 절을 구체화한다.
공통 계약 §1·2·4·6·9의 필드·필수/nullable·enum 전체·식별/유일성·실패 규칙은 이 spec의 일부다.
기존 단일회사 wire·불변성은 유지한다. 계약 변경은 관련 기능/정본에 함께 반영한다.

## 입력·출력 계약 및 저장

GET /api/demo-config의 enabled로 회사 route를 등록한다. 비활성 회사 URL 직접 접근의 서버 HTTP 404와 demo-config route는 DEMO-01이 구현하고 이 기능은 소비만 한다.
공개 그래프는 PublicNode/PublicEdge의 evidence_ids를 사용한다. 회사 핏은 CompanyFitView 확장, 보고서는 wrapper.view의 기존 ReportView를 reader에 전달한다.
UI 경로는 /companies/{company_id}/pre-specs, 같은 prefix의 /pre-specs/{notice_id}, /profile, /deep-reviews/{review_id}.
회사 핏은 CLI로 실행하므로 핏 생성·승인 화면은 없고 결과·사유·경로만 보여 준다.
심층 전송 미리보기·승인은 기존 `LunaRequest`를 회사 endpoint adapter로 재사용한다(같은 body·request_id 규칙).
비교는 /pre-specs/{notice_id}/company-comparison이다. 최초 데모 진입은 회사 선택이며 기본 회사를 몰래 확정하지 않는다.
query key는 company_id/resource/필터/버전으로 구분하고 원문 데이터만 company-independent key를 공유한다.
선택/상세 순회 sessionStorage도 company_id별로 분리한다. 새로고침·뒤로가기에서 URL이 정본이다.
시작한 mutation은 당시 회사로 끝나며 전환 후 화면을 잘못 무효화하거나 응답을 덮지 않는다.
미저장 추적 입력이 있으면 회사 전환 전 취소/버리기 확인을 받는다. 다른 회사에 자동 저장하지 않는다.
409 version_conflict는 서버 최신값과 사용자 초안을 함께 보존하고 자동 overwrite하지 않는다. 409 idempotency_conflict는 재전송 충돌로 안내한다.
추적 컨트롤은 회사 경로에서 계속 추적·보류·종료를 모두 제공한다. 기존 사전규격 화면의 계속 추적 단일 선택은 바꾸지 않는다(2026-09-17 결정의 데모 한정 예외).
mutation마다 새 request_id(UUID)를 만들고 재시도에는 같은 값을 쓴다.
matched=부합, mismatch=불일치, unknown=미확인, null=판정 없음. C-1 grade를 가상회사 판정으로 복사하지 않는다.
graph는 관계 목록(노드 유형별 묶음과 관계 행)으로 구현한다. SVG 시각화는 데모 이후로 미룬다. 선택한 노드를 중심으로 연결을 펼친다.
노드·관계 click/Enter→근거 패널→닫기 후 초점 복귀, depth/limit·절단·loading/empty/error를 지원한다.
관계/판정/순위를 브라우저가 생성하지 않는다. 사실/가상 설정/모델 해석/미확인을 문자로 구분한다.
기존 보고서 본문·근거 reader(`NarrativeReportReader`)·목록 프리미티브를 재사용한다. Astryx CLI로 실제 props/layout을 확인한 뒤 구현한다.
새 오류 code는 `src/lib/apiErrors.ts`에 등록한다. 새 회사 endpoint의 Playwright mock은 `tests/api-mock.ts`(및 `scripts/mock-api.ts`)에 추가한다.
mock 미등록 경로는 404 "고정 응답 없음"이므로 등록 누락을 제품 실패로 보고하지 않는다.
회사의 profile 편집, 그래프 SVG·drag 편집, 회사 핏 실행 화면, 모바일, 별도 요약 보고서 생성은 범위 밖이다.

## 인터페이스·상태·실패

공통 계약 §1·2·4·6·9의 endpoint/CLI/DTO를 사용한다.
unknown/null·준비 전·stale·실패·참조 표식을 성공/부적합으로 변환하지 않는다.
쓰기/전송 전에 회사·version·hash를 검사한다. 원문 경로·secret·모델 본문을 일반 응답/로그에 노출하지 않는다.

## 설정 키와 기본값

| 키 | 기본값 | 허용/적용 | 근거 |
|---|---|---|---|
| BIDOPS_DEMO_ENABLED | false | bool; 격리 데모에서 명시 활성 | 운영 경계 |
| BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED | false | 기존 bool | 사람 요청 분석 |
| graph depth/limit | 2/200 | 공통 §4, tunable | bounded 조회 |
| 가상 수치 | 원본에 명시 | DEMO-02에서 창작·분석 전 동결, tunable | 실제 사실로 오인 금지 |

## 결정과 이유

| 결정 | 근거 | 적용하지 않는 대안 |
|---|---|---|
| 회사/입력 버전 명시 | 사용자 전환·비교 선택 | 전역 프로필 교체 |
| 단일 원본에서 근거 생성 | 불변성·그래프 분석 활용 요구 | 프로필/그래프 별도 편집 |
| 실제 인수 분리 | 실제 결과 선택·기존 Luna 실패 이력 | mock을 실제 성공으로 집계 |
| 외부 그래프 서비스 | N/A — 업무 온톨로지·기존 PostgreSQL 사용 | RDF/OWL·별도 DB |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | A→B→A/새로고침/뒤로/복수 탭 | 회사별 URL/cache/선택/결정·mutation 유지 | Playwright |
| T2 | 관계 목록/근거/닫기 | 키보드 동작·가상 표식·초점 복귀·절단 안내 | Playwright |
| T3 | 비교 stale/missing/different_input/실패 | 서버 상태 그대로·순위/보정값 없음 | Playwright |
| T4 | 세 상태 저장/409/이탈 취소 | 계속 추적·보류·종료 저장·성공 뒤 갱신·version_conflict 초안 보존·취소 시 회사 유지 | Playwright |
| T5 | 심층 preview/승인/실행중 전환 | 단순 조회 호출 0·승인 1회·변경시 재승인·핏 승인 UI 없음 | Playwright |
| T6 | 1280/1440·긴 한글·HTTP origin | overflow 0·로딩을 완료로 표시 안 함·안전 UUID | 구조/통합 |
| T7 | 생산 빌드/legacy | tsc/build·기존 route/보고서 회귀 통과 | 빌드/회귀 |

## 컨벤션 반영 항목

새 회사 경로·origin·graph/version identity는 공통 계약, 상태 분리는 business-rules,
DB·외부 호출은 해당 정본의 DEMO 절에 반영한다. 구현 목표를 현재 동작으로 표시하지 않는다.
