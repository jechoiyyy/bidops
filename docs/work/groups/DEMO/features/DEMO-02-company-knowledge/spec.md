# 온톨로지와 가상회사 지식그래프 — spec

- 기능 ID: `DEMO-02-company-knowledge`
- 작성일: 2026-10-06 (같은 날 재계획 개정)
- 근거: [intent](intent.md), [공통 계약](../../../../demo-contract.md) §3·4·8
- 상태: 구현 목표. 현재 제품 계약과 구별한다. 별도 데모 브랜치와 `bidops-local` 격리 구현이며 main 병합·운영 전환은 별도다.

## 큰 틀 문서와의 관계

ADR-0070 및 기존 정본의 DEMO 목표 절을 구체화한다.
공통 계약 §3·4·8의 필드·필수/nullable·enum 전체·식별/유일성·실패 규칙은 이 spec의 일부다.
기존 단일회사 wire·불변성은 유지한다. 계약 변경은 관련 기능/정본에 함께 반영한다.

§7 중 합성회사 작성 기준만 이 기능에 적용한다. 실제 공고 corpus·18개 핏·9개 보고서 인수는 DEMO-05 소유다.

## 입력·출력 계약 및 저장

공통 §3의 정확한 NodeType/RelationType/허용 끝점/출처 enum을 schema로 구현한다.
KnowledgeOntologyVersion·CompanyKnowledgeVersion·Node·Edge·Source·Binding과 binding event는 deep_review 소유다.
같은 graph version 내 FK, company/profile/graph 소속 FK, source/profile/graph digest를 함께 검증한다.
회사마다 주력 capability 3개·기술 3개·인력군 2개·실적 3개·자격 미확인 1개·명시적 비주력 영역 1개 이상을 쓴다.
이 개수는 설명 충분성을 위한 tunable이며 모델 품질 임계값은 아니다.
세 회사는 비슷한 인력 총규모로 창작하고 분야별 구성을 달리한다. 정확한 숫자는 가상 설정으로 표시하고 결과 보기 전에 동결한다.
공공 업무/데이터AI/클라우드 운영이라는 사용자 선택을 보존하며 실제 회사자료에서 실적·인력을 복사하지 않는다.
원본과 온톨로지는 Claude가 초안을 쓰고 사용자가 승인한다. 승인 기록(승인자·시각·각 source_sha256)을 증거 디렉터리에 남기기 전에는 등록하지 않으며,
작성자는 초안 작성 중 데모 후보 공고(data/runs의 사전규격)를 열람하지 않는다. 승인 후 공고 선정 전에 동결한다.
공고 선정 뒤 별칭 1회 보강(공통 §7)은 DEMO-05가 수행하며, 이 기능의 validator는 개념 집합이 같고 aliases만 다른 새 ontology version을 허용한다.
온톨로지 validator는 한글 1자 alias를 거부한다(공통 §5 어휘 일치 규칙).
qualification·인력 미확인 정보는 unknown/null이고 명시적 미보유와 다르다.
unknown에는 존재하지 않는 근거를 생성하지 않는다. fictional_scenario 표식은 projection/모델 payload에도 보존한다.
원본 저장·다시 읽기 hash 검증 후 profile v2와 graph snapshot을 같은 등록에서 만들고 전체 transaction을 commit한다.
실패하면 이번 요청의 임시 객체만 정리하며 다른 버전은 수정하지 않는다.
active binding은 회사마다 하나이고 새 binding event를 append한다. import는 자동 활성화하지 않는다.
같은 원본·ontology 재등록은 동일 version이다. CLI가 lifecycle 공개 service로 회사 identity를 등록한다.
새 프로필 v2 소비를 추가하며 기존 v1의 고정 source_file(`docs/reference/company-profile.md`)/원본 version 검증을 완화하지 않는다.
CLI는 데모 환경에서 일회성 컨테이너에 `/run/demo-fixtures`로 read-only 마운트한 원본을 읽는다(공통 §10). 상주 서비스·이미지에는 넣지 않는다.
새 테이블 권한은 `scripts/runtime-privileges.sql`에 등록한다.

## 인터페이스·상태·실패

공통 계약 §3·4·8의 endpoint/CLI/DTO를 사용한다.
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
| T1 | 관계/끝점/노드 중복/cycle/한글 1자 alias | 허용 밖 거부·탐색은 종료 | 단위 |
| T2 | 가상/unknown/수치 | origin 보존·가짜 근거 없음·음수/available>total 거부 | 단위 |
| T3 | 멱등/객체 실패 | 동일 입력 동일 버전·불완전 binding 없음 | PG/객체 |
| T4 | 활성화/과거/타회사 | 이전 버전 보존·타회사 조회 404/FK 차단 | PG/API |
| T5 | dry-run/새 CLI 프로세스 | 무쓰기·lifecycle 공개 등록/확장점 동일 | CLI |
| T6 | projection/절단 | 원본 사실/인용 일치·경로 미노출·truncation 정확 | API |
| T7 | v1/최소 권한 | 기존 객체 version 검사 보존·무단 update/delete 차단·runtime-privileges.sql 기대값 일치 | 회귀/PG |
| T8 | 별칭만 다른 ontology | 개념·relations 동일하면 새 version 허용, 개념 추가·삭제·kind 변경은 거부 | 단위 |

## 컨벤션 반영 항목

새 회사 경로·origin·graph/version identity는 공통 계약, 상태 분리는 business-rules,
DB·외부 호출은 해당 정본의 DEMO 절에 반영한다. 구현 목표를 현재 동작으로 표시하지 않는다.
