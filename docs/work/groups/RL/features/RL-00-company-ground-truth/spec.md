# 루트랩 회사 근거 등록·버전 고정 — spec

- 기능 ID: `RL-00-company-ground-truth`
- 근거: [intent.md](./intent.md), DEMO 공통 계약 §1·§3·§4·§8(재사용 코드의 계약), ADR-0073 결정 1·6, [ui-spec §4.6](../../../../../1016_rootlab-redefinition/ui-spec.md), [company-profile §8](../../../../../reference/company-profile.md), [company-preferences](../../../../../reference/company-preferences.md)
- 작성일: 2026-10-16 (같은 날 독립 검사 1차 20건·2차 12건 반영; 3차 검사는 돌리지 않음)

## 큰 틀 문서와의 관계

- 인용하는 절: DEMO 계약 §1(회사 행·binding 소유), §2(REST 공통형·`GET /api/companies`), §3(온톨로지·회사 파일·Node/Edge·SourceRef), §4(import/activate CLI·profile v2·profile view·knowledge-graph view), §8(저장·fingerprint·오류 code); HP 계약 §4(온톨로지 v1 51 concept); contracts.md 공통 REST 규칙; business-rules.md "용어와 판단 단계"; ui-spec §1.4(`/company` 라우트)·§3(공통 컴포넌트)·§4.6(회사 근거 화면)·§5(검증).
- 이 문서에서 새로 확정하는 항목: 실회사 등록 조건, `proposed` 상태와 새 origin 값, 보유·세부 분리 value 구조, 루트랩 회사 파일의 노드 구성 규칙, 단일 회사 조회 REST, 회사 근거 화면의 상태 매핑·집계, 재등록 절차.
- 큰 틀 문서 수정이 필요한 항목(STEP-007에서 반영, ADR.md에 한 줄): DEMO 계약 §1 "is_fictional=true만 허용" → RL 개정(실회사 1곳 허용, 가상회사는 `BIDOPS_DEMO_ENABLED=true`에서만), §3 Node.status·origin enum 확장과 "회사 파일 `is_fictional:true`" 고정 해제, §4 profile v2 `origin:"fictional_scenario"` 고정 해제·FactV2.origin 확장, profile-view·evidence-view origin 확장; contracts.md 회사 REST 절에 `GET /api/company` 추가; business-rules.md에 사실 상태 네 값과 화면 이름 대응.

## 입력·출력 계약

### 등록 조건

- `register_company`는 `is_fictional=false`를 받는다. **실회사는 DB 전체에서 1곳**이다: 이미 `is_fictional=false` 행이 있고 slug가 다르면 `real_company_exists`(새 오류 code, HTTP 미노출·CLI exit 2)로 거부한다. 감사 `safe_metadata.is_fictional`은 요청값을 그대로 적는다(현재 `True` 고정은 결함이며 함께 고친다).
- 가상회사(`is_fictional=true`) 등록은 `BIDOPS_DEMO_ENABLED=true`일 때만 허용한다. 검사는 `prepare_company_knowledge`(deep_review service, 설정을 읽을 수 있음) 단계에서 하므로 `--dry-run`도 같은 결과(`fictional_requires_demo`, exit 2)다. `company_fictional_required` 코드는 폐기하고 `is_fictional`이 bool이 아니면 `source_invalid`다. 기존 DEMO·HP 가상회사 행은 삭제하지 않는다.
- 회사 경로 가드(`main.py` 미들웨어 `_is_demo_only_path`, 경로 문자열 기준)는 demo off에서 다음 **method+경로만** 통과시킨다: `GET /api/companies`, `GET /api/companies/{id}`, `GET /api/companies/{id}/profile`, `GET /api/companies/{id}/knowledge-graph`, `GET /api/companies/{id}/profile-evidence/{eid}`, `GET /api/company`. `PATCH /api/companies/{id}/opportunities/{oid}/tracking`(데모 회사별 추적), `company_reads_router`·`company_analysis_router`(회사별 사전규격·심층·Luna 전송 POST), SPA `/companies/*`, `company-comparison`은 demo off에서 계속 404다(RL-03이 실회사 분석 경로를 열 때 다시 정한다). SPA `/companies/:id/profile → /company` 리다이렉트는 프런트 라우트에만 두며 demo off의 직접 URL 진입은 미들웨어 404 그대로다. 서비스 쪽 demo gate(`company_deep_review._gate_company`·`company_projection`·`company_fit`)는 손대지 않는다.

### 회사 파일 `bidops.company-knowledge-source.v1` 확장

검증 코드의 위치: status·origin 집합(`FACT_STATUSES`·`ORIGINS`), 노드·관계 origin 고정, `is_fictional is not True → company_fictional_required`, 노드 value strict 타입은 모두 `web/backend/app/core/company_ontology.py`에 있고, 읽기 쪽 고정(profile v2 origin·status 3값·노드/관계 origin, **그리고 `not company.is_fictional` 거부**)은 `deep_review/services/input_versions.py`에 있다. 읽기 쪽의 `is_fictional` 검사는 제거한다(실회사 허용). 두 파일을 함께 바꾸지 않으면 import가 `source_invalid`이거나 활성화 뒤 `/profile`이 `processing_failed`가 된다.

- `company.is_fictional: bool`(true 고정 해제). `scenario_version`은 실회사에서 `source_version`으로 읽되 키 이름은 유지한다(값 예: `rootlab-2026-10-16`).
- `Node.status`·`Edge.status` = `confirmed | proposed | inferred | unknown`. `proposed` = 에이전트 제안값, 사람 미확인. `proposed`는 `confirmed`와 같은 source_ref 규칙(정확히 1개)을 따른다.
- `Node.origin`·`Edge.origin` = `fictional_scenario | public_document | model_inference | company_brochure | homepage | user_interview | agent_proposal`. 실회사 파일에서 `fictional_scenario`는 거부, 가상회사 파일에서 새 네 값은 거부한다. `model_inference`·`public_document`는 등록 파일에서 계속 거부(분석 overlay 전용).
- status·origin 조합 규칙: `proposed`는 origin `agent_proposal`만, `user_interview`는 `confirmed`·`unknown`만, `company_brochure`·`homepage`는 `confirmed`만. 어긋나면 `source_invalid`.
- 보유·세부 분리: "보유는 확인, 세부 미입력"인 사실은 노드 하나에 `value={"held": true, "detail": null}`로 두고, 세부 값(세부품명·유효기간 등)은 **별도 노드** `status=unknown`(`value=null`, `source_refs=[]`)로 둔다. 하나의 노드에 두 상태를 섞지 않는다. 세부 값이 확인되면 그 unknown 노드를 `confirmed`로 바꾸고 value를 채운다(새 버전).
- SourceRef는 기존 `{source_id:"self", locator:{json_pointer}, quote}` 그대로다. 출처 문서의 쪽·URL은 파일에 넣지 않고 validation-runs README에 적는다(`source_note` 필드는 두지 않는다).

#### 노드 value 스키마 확장 (타입별, strict object = 적힌 키 전부 필수, `?`는 null 허용)

| NodeType | 기존 | RL-00 확장 |
|---|---|---|
| company·technology | string \| null | 변경 없음 |
| domain | string \| null | 추가 허용: `{tier: 1\|2\|3\|null, keywords: string[], excluded: bool, kind: hardware\|staffing_only\|design_only\|election\|region\|amount_floor\|null}` (`excluded=true`면 `kind` 필수) |
| qualification | string \| null | 추가 허용: `{held: bool, detail: string?, valid_until: date?, issued_on: date?, file_name: string?}` — 사본 파일은 저장하지 않고 파일명만 |
| capability | `{scope, description}` | `{scope: core\|non_core, description: string, params: object?}`; `params`는 평면 객체(값 int\|string\|bool), `pref:*` 수치 조건(`krw`·`min_krw`·`max_krw`·`count`·`months`)이 여기 들어간다 |
| staff_group | `{role, total?, available?, as_of?}` | `{role, total?, available?, as_of?, region: string?, grade: string?}` — 상주 가능 지역은 `region="대구"` |
| project | `{role, scope, amount_krw?, started_on?, ended_on?}` | `role`·`scope`를 null 허용으로 넓히고 `agency: string?`, `year: int?` 추가. 홈페이지 실적은 `label`=사업명, `agency`, `year`만 채우고 나머지 null |
| evidence·notice·requirement | 기존 | 변경 없음 |

기존 가상회사 파일(DEMO·HP)은 기존 형태 그대로 통과해야 한다(추가 허용이지 대체가 아님). 두 검사기(`core/company_ontology.py`·`input_versions.py`)의 허용 집합을 같이 바꾼다.

### 루트랩 회사 파일 구성 규칙 (fixture `~/orca/fixtures/company/rootlab/`)

- 파일: `ontology.v2.json`(HP 온톨로지 v1을 바탕으로 qualification 9·domain 분야 8·제외 7·반복 발주처 12·선호 조건 capability 5 등 **약 40개 concept**를 더해 `version="bidops.company-ontology.rl-v2"`로 발행; domain·capability·qualification 노드는 unknown이라도 concept_id 필수), `rootlab.source.v1.json`.
- id 규칙(`STABLE_KEY_RE`는 ASCII): concept id `rl.<kind>.<nn>`(kind=qualification|domain|capability, nn 두 자리 순번; label은 한글), 노드 id는 ASCII slug만 — `project:<year>-<nn>`(홈페이지 표 순서, 같은 사업명의 연차는 연도로 구분), `pref:agency:<nn>`, `pref:domain:<nn>`, `excl:<kind>`, `qual:<slug>`(아래 RL-03 allowlist와 같은 이름: `procurement_1468`·`direct_production`·`sme_certificate`·`sw_business`·`credit_rating`·`branch`·`infosec_cert`·`social_enterprise`·`sanction_free`·`staff_certifications`), `staff:<slug>`. 한글 이름은 `label`에만 둔다.
- 출처→origin 대응: 홈페이지 프로필 행 → `homepage`; 인터뷰 §8의 confirmed·unknown → `user_interview`(**모든 unknown 노드의 origin은 `user_interview`로 고정**); preferences의 confirmed(사용자 확인) → `user_interview`; proposed(신용등급 등) → `agent_proposal`; 회사소개서에서만 확인된 사실(인증·특허·조직) → `company_brochure`.
- company 노드 1개(`company:rootlab`, slug `rootlab`, name `㈜루트랩`). 노드 id 접두: `qual:`·`cert:`·`staff:`·`project:`·`pref:`·`excl:`·`ev:`. 지역 사실은 `staff_group.value.region`과 qualification `qual:branch`(지점 문자열)로 표현하고 `region` NodeType은 만들지 않는다.
- 자격(§8.1) 9행 → qualification 노드 9개(보유 사실 `confirmed`/`proposed`) + 세부 unknown 노드(세부품명·유효기간·갱신일·인증 종류·지점 등기 형태). 신용등급은 `proposed`/`agent_proposal`.
- 인력(§8.3): staff_group 노드 `staff:dev`(total 20)·`staff:planning`(15)·`staff:design_publishing`(5)·`staff:onsite`(`role="onsite"`, `available=6`, `region="대구"`)·`staff:pm`(unknown)·`staff:grade_distribution`(unknown). 자격증 전원 보유(종류 미입력)는 qualification `qual:staff_certifications` `{held:true, detail:null}`.
- 실적: 홈페이지 프로필 57건 중 사업명·기관·연도가 있는 행만 project 노드(`origin=homepage`, `confirmed`, value `{role:null, scope:null, amount_krw:null, started_on:null, ended_on:null, agency, year}`). 홈페이지에 없는 역할·범위·금액은 지어내지 않는다. `performed`·`operates_in` 관계는 표에서 읽히는 것만. 실적증명 발급 가능 목록(§8.2)은 `project:certified_list` unknown 노드.
- 선호·제외(preferences §1~§4 confirmed): `pref:domain:*` domain 노드(`{tier, keywords, excluded:false, kind:null}`), `excl:*` domain 노드(`{tier:null, keywords, excluded:true, kind}`), 금액·동시 수행·상주 상한·선호 기간은 `pref:*` capability 노드(`scope=core`, `params`에 수치) — id와 `params` 키 고정: `pref:amount_floor`{krw}, `pref:amount_range`{min_krw,max_krw}, `pref:solo_cap`{krw}, `pref:consortium`{over_krw, over_onsite_count}, `pref:concurrent_cap`{count, onsite_count}, `pref:onsite_cap`{count}, `pref:duration`{min_months,max_months}, `pref:subcontract`{allowed:bool, max_ratio_percent}; `excl:amount_floor` domain 노드는 키워드 없는 표식일 뿐 값은 `pref:amount_floor`에서 읽는다(RL-01), 반복 발주처는 `pref:agency:*` domain 노드(`keywords=[기관명]`, `tier=null`). 마진·투찰률(D7)은 `pref:margin` unknown 노드.
- 제안서 자산·운영(§8.4: 과거 제안서 없음·형식·Slack·브리핑 시각)은 회사 그래프에 넣지 않는다(해당 NodeType 없음). 값은 RL-01·RL-04 spec이 설정으로 가진다. 화면의 "제안서 자료" 내비 항목은 비활성이다.
- 노드 수 상한 256(profile v2 규칙 유지). 넘으면 project 노드를 최근 연도부터 채우고 나머지는 README에 적는다.

### 저장 projection

- profile v2 payload `origin`(최상위) = `"real_company"`(실회사) 또는 `"fictional_scenario"`. FactV2.origin = 노드 origin 그대로. `FactV2.status`에 `proposed` 추가. `ProfileVersion.source_kind`는 기존 값 `company-knowledge-json-v2` **그대로**(멱등 재등록·snapshot 검증이 이 값을 비교한다) 두고 실회사 구분은 payload `origin`으로만 한다. v1 소비 경로는 바꾸지 않는다.
- graph snapshot·hash 규칙(§8)은 동일. 새 enum 값은 canonical JSON에 그대로 들어간다.
- ProfileEvidence는 `confirmed`·`proposed` 모두 1개(`confirmed_by_name`은 CLI actor, 뜻은 "등록자"). 화면·판정은 status로 구분하므로 proposed evidence를 확인 근거로 쓰지 않는다(RL-03 규칙).

### REST

- `GET /api/company` → `CompanyContextView = {schema_version:"bidops.company-context.v1", company: CompanyDTO, expiry_warning_days: int, active_graph_version: {graph_version_id: UUID, created_at: ts} | null}`(키 전체, 추가 금지). **deep_review `company_knowledge_router`가 소유**한다(활성 binding은 deep_review 테이블이고 lifecycle→deep_review import는 ADR-0045 경계 검사가 막는다; prefix `/api/company`를 같은 router 모듈에 추가). 실회사 행이 없으면 404 `company_not_registered`(deep_review 라우터 허용 목록 + 프런트 `apiErrors.ts`; lifecycle `API_ERROR_CODES`는 손대지 않는다). 사이드바 워크스페이스 이름·`/company` 상단바 "마지막 저장 날짜"(`active_graph_version.created_at`)가 쓴다.
- `GET /api/companies/{id}/profile` 응답 `CompanyProfileFact.origin`·`status`를 위 enum으로 넓힌다. `GET …/profile-evidence/{id}` origin도 같다. 다른 키는 그대로.
- 화면의 상태 3 수치와 "확인이 필요한 것" 목록은 화면이 facts로 센다. 사이드바 "회사 근거" pill은 ADR-0067 규칙대로 `GET /api/workload` 키만 읽으므로 키 `company_attention`(실회사 활성 그래프의 `proposed`+`unknown` 비evidence 노드 수; 실회사 없으면 `null`/`provider_absent`)을 추가한다. 키 어휘는 lifecycle 소유: `schemas/workload.py` `WorkloadKey` Literal·`services/workload.py` `_WORKLOAD_KEYS` 순서 끝에 추가, 값은 deep_review 확장점 제공자가 센다. 프런트 `lib/api.ts`·`lib/types.ts`·`tests/api-mock.ts WORKLOAD_KEYS`를 같이 갱신한다. ADR-0067의 "건수 키 = 목록 호출 total" 짝 규칙의 예외(짝 목록 REST 없음, 화면이 facts로 셈)를 contracts.md workload 절에 한 줄 적는다.

### 화면 `/company` (ui-spec §4.6, 읽기 전용)

- 라우트 `/company`(기본 `?group=attention`; ui-spec §1.4 enum에 `attention`을 추가한다). 기존 `/profile`은 설정 메뉴의 판정 기준 화면으로 **남긴다**(ui-spec §1.4의 "`/profile` 리다이렉트" 문구는 삭제). `/companies/:id/profile → /company` 리다이렉트는 demo on 라우트에만 둔다. 사이드바 "회사 근거" 링크를 `/profile`에서 `/company`로 바꾼다.
- 상태 이름 대응: `confirmed`→확인됨(success), `proposed`→추정값(**blue ramp** `--color-background-blue`/`--color-text-blue`, 테마에 이미 있음; ui-spec §7-2를 이 값으로 닫고 `bidopsTheme.ts` 28행 "상태 표시에는 blue 계열을 쓰지 않는다" 주석과 ADR-0048 개정 줄을 "추정값 pill만 blue"로 고친다), `unknown`→확인 필요(warning), `inferred`→표시 안 함(RL-00 파일에 없음). "곧 만료" = qualification value `valid_until`이 있고 `expiry_warning_days` 이내. §8 데이터에는 유효기간이 0건이므로 RL-00 결과 수치는 0이며 계산 규칙만 구현한다.
- 그룹 매핑(`?group=`): `attention`="확인이 필요한 것"(`proposed` ∪ `unknown`), `qualification`→자격 서류, `performance`→실적(project), `staff`→인력(staff_group), `preference`→선호·제외 조건(domain·`pref:`·`excl:` capability), `proposal-assets`→제안서 자료(비활성, 빈 상태 "RL-04에서 채웁니다"). 영향 공고 열은 RL-03 전까지 그리지 않는다(빈 열 금지).
- 행동 버튼("맞음"·"수정"·"입력")은 **그리지 않는다**(읽기 전용 결정). 대신 각 행에 fact_key를 복사하는 ghost 버튼 하나와 상단 안내 한 줄 "값 수정은 회사 파일을 고쳐 다시 등록합니다(설정 › 도움말)".
- 상단바: "회사 근거" + "㈜루트랩 · 마지막 저장 날짜"(graph version created_at). 액션 "이전 버전"은 `?graph_version_id=` 선택 드롭다운(binding event 목록은 REST가 없으므로 현재 버전만 보여 주고 드롭다운은 후속). 저장(주) 버튼은 그리지 않는다.
- 운영 정보 금지 검사(ui-spec §5): DOM에 graph_sha256·profile_version_id·`unmeasured_reference`·인터뷰 번호(`A1`~`G6` 패턴) 문자열이 없어야 한다.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| `BIDOPS_DEMO_ENABLED` | bool | false | | 가상회사 등록·선택기·비교 UI만 통제. 회사 REST는 항상 켜짐 |
| `BIDOPS_COMPANY_EXPIRY_WARNING_DAYS` | int | 60 | 1..365 | "곧 만료" 기준, `CompanyContextView.expiry_warning_days`로 전달. `tunable` |

## 상태 값과 실패 처리

- 사실 status: `confirmed | proposed | inferred | unknown`(enum 전체). origin: 위 7값.
- CLI 오류 code(§8 집합 + 추가): `source_invalid | ontology_invalid | ontology_version_conflict | company_identity_conflict | real_company_exists | fictional_requires_demo | source_unavailable | storage_failed`. exit 규칙은 §8 그대로이며 `real_company_exists`·`fictional_requires_demo`는 import service의 `BundleServiceError` 매핑(현재 `company_identity_conflict` 외 전부 `source_invalid`로 접음)과 CLI `_exit_for` exit 2 목록에 함께 넣는다. `company_fictional_required`는 폐기한다.
- REST 추가 code: `company_not_registered`(404). deep_review 라우터 허용 목록과 `src/lib/apiErrors.ts`에 함께 등록.

## 저장

- 새 테이블·열 없음. `ProfileVersion.source_kind`는 기존 값 유지. 권한 변경 없음. migration 없음.
- fixture 디렉터리와 등록 결과(ID·sha256)는 `docs/validation-runs/<날짜>-rl/RL-00/README.md`에 기록한다(원본 파일은 Git 밖).

## 인터페이스(CLI·UI·API)

- CLI 서명 변경 없음(`import-company-knowledge`·`activate-company-knowledge`). **import 출력 JSON(`_import_payload`, 기존 9키)에만** `is_fictional: bool|null`·`status_counts: {confirmed:int, proposed:int, inferred:int, unknown:int} | null`을 항상 더한다(실패 JSON은 null; activate 출력 6키는 그대로). 기존 테스트의 정확 키 집합 단언(`test_company_knowledge_cli.py`)과 DEMO 계약 §4 import 출력 shape를 함께 갱신한다.
- 재등록 절차(operations.md 신설 절 "회사 근거 갱신"): 파일 수정 → `--dry-run` → import → activate → `GET /api/company`·`/profile`로 확인 → README에 sha256 추가. 운영 DB 실행은 직전 사람 확인.
- 외부 호출 없음.

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| `proposed`를 넷째 status로 추가 | 사용자 결정(2026-10-16). 에이전트 제안값과 모델 추론을 한 값에 섞지 않기 위해 | `inferred` 재사용 |
| origin 네 값 추가 | ADR-0073 결정 1 "origin은 확인 출처(회사소개서·홈페이지·사용자 인터뷰)"; 제안값 출처 구분 필요 | 단일 `real_company` origin + source_note |
| 화면 읽기 전용, 파일이 정본 | 사용자 결정(2026-10-16). 버전 불변·hash 재현 규칙(§8)을 파일 기반으로 유지 | 화면 저장 REST |
| 실회사 1곳 강제 | mission "회사는 실회사 루트랩 하나" | 다회사 허용 |
| 회사 REST를 demo 플래그에서 분리 | 회사 1곳이므로 선택기 없이 항상 필요(ui-spec §1.2 "DEMO 회사 선택기는 그리지 않는다") | 새 `BIDOPS_COMPANY_ENABLED` 플래그 |
| 보유/세부를 노드 둘로 분리 | 인터뷰 A1~A4 "자격 있음" + 세부 미입력을 `unknown` 승격 없이 표현(preferences §5) | `confirmed_exists` status 추가 |
| 화면 수치는 화면이 계산, 사이드바 pill만 workload 키 | ui-spec 분모 표시 금지·단일 회사; 사이드바는 ADR-0067 규칙(workload 키만) | 서버 집계 REST 별도 |
| `source_kind` 유지, payload origin으로 구분 | 멱등 재등록·snapshot 검증이 `company-knowledge-json-v2`를 비교(독립 검사) | 새 source_kind |
| 제안서 자산·운영 값은 그래프 밖 | 해당 NodeType 없음; 설정값 성격 | NodeType 추가 |
| 영향 공고 열 보류 | 판정 결과(RL-03)가 없음 | 빈 열 표시 |
| N/A — 그래프 편집 UI | mission 범위 밖 | |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | 실회사 파일 import(dry-run·실제) → activate → `/profile`·`/knowledge-graph` 조회 | created=true, `is_fictional=false`, status_counts 일치, profile v2 origin `real_company`, FactV2 origin 보존, **활성화 뒤 두 GET이 200**(input_versions 검사기 통과) | 단위 |
| T2 | status/origin 조합 위반(`proposed`+`homepage`, 실회사+`fictional_scenario`, 가상+`user_interview`) | `source_invalid` exit 2, DB 변경 없음 | 단위 |
| T3 | 두 번째 실회사 slug import | `real_company_exists` exit 2 | 단위 |
| T4 | `BIDOPS_DEMO_ENABLED=false`에서 가상회사 import·`--dry-run` / true에서 import; `is_fictional` 비bool; 기존 DEMO·HP 가상 파일 fixture | 둘 다 `fictional_requires_demo` exit 2 / 허용; `source_invalid`; 기존 파일은 value 확장 전후 동일하게 통과(기존 `test_company_knowledge*` 전부 통과) | 단위 |
| T5 | 보유·세부 분리 노드(held true + detail unknown) | profile view에 두 fact, unknown은 evidence 0개, proposed는 1개 | 단위 |
| T6 | `GET /api/company` 미등록/등록, `/profile` enum 확장, demo off에서 `company-comparison`·`/companies` SPA·`company_reads`·`company_analysis` POST는 404 유지, workload `company_attention` | 404 code·200 strict shape(PG)·건수 일치 | 통합(PostgreSQL 포함) |
| T7 | 재등록(파일 수정 → import → activate) | 새 graph_version_id, 이전 버전 `?graph_version_id=` 조회 가능, binding revision+1 | 통합(PostgreSQL) |
| T8 | `/company` 화면: 세 수치·그룹 표·확인 필요 목록, 운영 정보 금지 문자열, 1280·1440 구조 | Playwright `--project=app` 통과, 금지 문자열 0 | 프런트 |
| T9 | 실제 fixture 파일 dry-run | 오류 0, 노드 수·status_counts를 README에 기록 | 수동(bidops-local) |

## 컨벤션 반영 항목

- status enum `proposed`, origin 7값, 노드 value 확장 표, `GET /api/company`(`bidops.company-context.v1`), workload 키 `company_attention`, 오류 code `real_company_exists`·`company_not_registered`, 온톨로지 `bidops.company-ontology.rl-v2` → contracts.md·business-rules.md·demo-contract 개정 절·ui-spec §1.4(`attention`)·§3(추정값 blue)·§4.6(읽기 전용)·§7-2 닫기.
- RL-03 입력으로 기록: `company_knowledge_retrieval.py`의 `FACT_STATUSES`와 `company_fit_policy.py` 프롬프트 문구는 `proposed`를 모른다. 실회사 binding이 활성화돼도 회사 핏·심층 경로는 demo off에서 닫혀 있으므로 RL-00에서는 바꾸지 않고 RL-03 spec이 `proposed`를 "미확인과 같은 취급(근거 아님)"으로 고정한다.
