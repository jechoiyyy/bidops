# 루트랩 회사 근거 등록·버전 고정 — intent

- 기능 ID: `RL-00-company-ground-truth`
- 상위 항목: roadmap §RL 표 1행, ADR-0073 결정 1·6, [ui-spec §4.6](../../../../../1016_rootlab-redefinition/ui-spec.md)
- 크기: L — lifecycle 등록 service·deep_review 회사 지식 import·profile v2 계약·프런트 `/company` 화면·문서 4종을 건드리고 DEMO 공통 계약의 가상회사 전제(§1·§3·§4)를 수정한다. 외부 호출 없음.
- 작성일: 2026-10-16 (같은 날 미해결 질문 3건 사용자 답 반영)

## 문제

루트랩의 회사 근거(회사소개서 프로필·홈페이지 프로필·선호·제약·인터뷰 A~F)는 markdown 4개에 흩어져 있고 DB에 회사 행이 없다. 현재 회사 등록 CLI와 계약은 `is_fictional=true`·`origin=fictional_scenario`만 받으므로 실회사를 등록할 수 없다. 회사 행과 활성 그래프 버전이 없으면 RL-01 브리핑의 반복 발주처 규칙과 RL-03 판정의 대조가 모두 `unknown`에 머문다.

## 기대 결과

- CLI 한 번으로 루트랩을 `is_fictional=false`로 등록하고, 사실 노드마다 출처(회사소개서·홈페이지·사용자 인터뷰·에이전트 제안)와 상태(`confirmed`/`proposed`/`unknown`)를 가진 회사 지식 버전을 만들어 활성화한다. 원본 파일은 저장소 밖 fixture 디렉터리에 두고 bytes hash로 버전을 고정한다.
- 화면 `/company`(ui-spec §4.6)에서 확인됨·추정값·확인 필요 상태별로 자격 서류·실적·인력·선호·제외 조건·제안서 자료를 보고, "지금 확인하면 판정이 바뀌는 것" 블록에서 `proposed`·`unknown` 항목을 본다.
- 인터뷰 답이 추가되면 원본 파일을 고쳐 다시 import하고 activate한다(새 버전, 이전 버전 불변). 절차는 operations.md에 한 절로 적는다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| 루트랩 등록 | `python -m app.deep_review.cli import-company-knowledge --ontology <file> --company <rootlab.json> --actor <name>` 뒤 `activate-company-knowledge` | `GET /api/company` 200·`is_fictional=false`(가상 행은 남아 있어도 됨); `GET /api/companies/{id}/profile`의 facts에 §8 항목이 상태·origin과 함께 있고 활성화 뒤 조회가 200이다 |
| 가상회사 거부 유지 | 같은 CLI에 `is_fictional=true` 회사 파일 | RL 모드(`BIDOPS_DEMO_ENABLED=false`)에서 거부 code로 exit 2 |
| 확인 필요 보기 | `/company` | 좌측 숫자 3(확인됨·확인 필요·곧 만료)과 "지금 확인하면 판정이 바뀌는 것" 목록이 profile의 `proposed`·`unknown` 수와 같다. 모델명·정책 id·인터뷰 번호 문자열이 DOM에 없다 |
| 추정값 확정 반영 | 원본 JSON의 status를 `confirmed`로 고쳐 재import·activate | 새 graph_version_id, 이전 버전 조회 가능(`?graph_version_id=`), 화면 "마지막 저장 날짜" 갱신 |
| 상주 지역 사실 | profile facts | `staff_group` 상주 가능 지역 = 대구만(C4)이 confirmed로 있고 "대구 외 3명"은 없다 |

## 선행·후속 기능

- 선행: 없음.
- 후속: `RL-01-daily-briefing`(반복 발주처·선호·제외 조건 읽기), `RL-03-fit-verdict`(회사 사실 대조), `RL-04-proposal-draft`(유사 실적·회사 소개 절).

## 영향 범위

- 모듈·컴포넌트: `core/company_ontology.py`(enum·value strict 검증), `deep_review/services/input_versions.py`(읽기 검증), `lifecycle/services/company_context.py` `register_company`, `deep_review/cli/import_company_knowledge.py`·`services/company_knowledge.py`, `schemas/company_knowledge.py`, `main.py` 가드, `lifecycle/routers/companies.py`, deep_review workload 확장점, 프런트 `pages/CompanyPage`(신규, `/company`), `companyApi.ts`·`KnowledgeGraph.tsx`, 사이드바 "회사 근거" 건수.
- 큰 틀 문서의 절: demo-contract §1(가상 전용 등록)·§3(origin enum, is_fictional:true 고정)·§4(profile v2 origin), hp-contract §1·§5(회사 설정), contracts.md 회사 REST, business-rules.md(사실 상태 3축), ui-spec §4.6.
- 데이터·저장소: 기존 회사 지식 테이블 재사용. 새 열 없음이 목표(enum은 JSON payload 값). fixture `~/orca/fixtures/company/rootlab/*.json`(저장소 밖).
- 외부 서비스·호출: 없음(모델 호출 없음).

## 제약

- (공통) feature.json constraints: 원문 불변·계보, `unknown` 보존(부족 승격 금지), 운영 변경 사람 확인, 모델 전송 정책, 테마 토큰만 읽기, 데스크톱 전용, DB 권한은 `scripts/runtime-privileges.sql`.
- (기능별) 사본 파일(증명서 PDF 등)은 저장하지 않고 파일명·발급일·유효기간만 값으로 둔다(ui-spec §4.6). `proposed`는 차단 조건·판정 근거로 쓰지 않는다(ADR-0073 결정 6). 인터뷰 세부 미입력(A1~A4 "자격 있음")은 `confirmed_exists`가 아니라 value에 보유 사실만 두고 세부는 `unknown` 하위 사실로 분리한다.

## 범위 밖

화면에서 값을 직접 편집·저장하는 기능(사용자 결정: 읽기 전용), 영향 공고 열(RL-03이 채움), 제안서 자산·운영 값의 그래프 저장(설정 성격, RL-01·RL-04), `company_reads`·`company_analysis` 라우터의 실회사 개방(RL-03), `company_knowledge_retrieval`·`company_fit_policy`의 `proposed` 처리(RL-03), 그래프 편집 UI, Neo4j, 다회사.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 실회사 등록 | demo-contract §1·§3 "is_fictional=true만 허용", origin `fictional_scenario` 고정 | ADR-0073 결정 1 `is_fictional=false`, origin은 확인 출처 | ADR-0073 우선. spec에서 demo-contract §1·§3·§4를 개정하고 decision_log에 한 줄 남긴다 |
| 사실 상태 집합 | demo-contract §3 `confirmed\|inferred\|unknown` | 프로필·선호 문서 `confirmed\|proposed\|unknown`(+`confirmed_exists`) | 미해결 질문 1 |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 1. 노드 status에 `proposed`를 넷째 값으로 추가할지, 기존 `inferred`를 그 뜻으로 쓸지 | spec 작성 전 | 2026-10-16 사용자: **`proposed` 추가**. `inferred`는 모델 추론용으로 남긴다. "자격 있음·세부 미입력"은 status가 아니라 value 구조 `{held:true, detail:null}`로 표현한다 |
| 2. origin enum | spec 작성 전 | 사용자가 추천값 수용: `company_brochure`·`homepage`·`user_interview`·`agent_proposal` 추가, 기존 세 값 유지(ADR-0073 결정 1의 출처 목록) |
| 3. `/company` 화면의 "맞음·수정" 저장 포함 여부 | spec 작성 전 | 2026-10-16 사용자: **읽기 전용 + CLI 재등록**. 화면 저장(새 버전 발행 REST)은 RL-00 뒤 별도 기능 |
