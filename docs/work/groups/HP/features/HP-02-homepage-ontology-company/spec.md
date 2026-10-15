# HP-02 — spec

근거: intent.md, HP 공통 계약 §1·4·5, DEMO 계약 §3·4·8. 승인 회사 v2의 가상 담당 범위만 제품 데이터로 옮긴다. 스키마 kind·관계 확장 없음.

## 입력·출력과 저장

정본 입력은 preparation의 ontology.approved.v1.json, company.experience.approved.v2.json, company.evaluation-basis.v2.json이다. 첫 파일은 기존 ontology parser canonical SHA, 나머지는 파일 bytes SHA로 검사한다. v1·draft 파일은 입력으로 선택하지 않는다.

신규 `docs/hp-fixtures/companies/hp-onweb.v2.json`은 기존 `bidops.company-knowledge-source.v1`의 정확한 키·형식을 따른다(검증기 `app/core/company_ontology.py`). company={name:"가상 온웹서비스",slug:"hp-onweb",is_fictional:true}, scenario_version="hp-onweb-v2", ontology_version="homepage-ontology-v1". ontology 파일은 승인 파일을 그대로 읽으며 복제하지 않는다. 노드/관계 status=confirmed|inferred|unknown, origin=fictional_scenario. 모든 non-null 사실은 유효한 self JSON pointer·quote를 갖는다. unknown은 null이며 false와 구별한다.

- v1 등록의 company.onweb, 14 retained_facts 의미와 기존 node ID는 보존한다. company 노드 설명만 승인 v2의 실적명·담당 범위에 맞춘다. 인원18·매출18억원·3년3건·최대2억원은 회사 전체 사실이며 어느 개별 실적에도 배분하지 않는다.
- project.build/project.improve/project.operate: type=project, concept_id=null, confirmed. value의 필수 키 role/scope/amount_krw/started_on/ended_on 중 마지막3개는 null, role은 승인 원본 role 그대로, scope는 delivered_scope 배열의 순서를 유지해 `"; "`(세미콜론+공백)으로 join한 문자열이다. project의 self 근거는 `/nodes/<실제배열index>/value/role`과 `/nodes/<index>/value/scope` 두 pointer, quote는 각각 해당 문자열 전체로 고정한다. 배열 정렬·요약·중복제거는 하지 않는다. company.onweb→project에는 `performed`, 프로젝트→그 원본 capability_concept_ids의 concept에는 `supports_capability`를 넣는다. 참고 공고 source hash/인용은 수행 근거로 등록하지 않는다.
- 승인된 capability 목록의 기존 concept node는 재사용한다. 없으면 `fact.<concept_id>` ID, type=capability, value={scope:"non_core",description:승인 담당 범위}로 만든다. 기존 core3는 유지한다. non_core는 추가 기능 경험이라는 표시이며 부재/불능이 아니다. 관계 ID는 `edge.<from_id>.<relation>.<to_id>`. 승인된 기능 경험에 company→capability `has_capability`를 추가하되 scope 제한을 description·평가 sidecar로 함께 보존한다. 명시 제외·인증·SLA·현재 자격까지 확대하지 않는다.
- ISMS false는 기존 qualification 문자열과 typed retained_fact의 false를 함께 보존한다. holds_qualification으로 미보유를 보유처럼 연결하지 않는다. 미보유/unknown 대조는 HP03 typed 사실에서 한다.
- graph schema가 표현하지 못하는 typed 수치·제외 범위·절차·현재 조건은 승인 시나리오 원본을 불변 sidecar로 읽는다. 새 `docs/hp-fixtures/companies/hp-onweb.binding.v2.json`: schema_version="bidops.hp-company-registration-binding.v1", company_slug, company_sha256(평가 basis 파일 SHA), scenario_sha256, ontology_sha256(canonical), registration_sha256(등록 파일 bytes), scenario_file, registration_file, basis_file 모두 필수. 상대 경로는 허용 fixture/preparation root 안에서만 해석한다. 등록을 이유로 기존 basis의 pending/null을 소급 수정하지 않는다.
- HP03가 이 binding+DB graph/profile SHA를 모두 동결한다. 파일/DB source mismatch는 실패한다. v1 source를 v2로 오인하지 않는다.

등록은 기존 `python -m app.deep_review.cli import-company-knowledge --ontology <승인파일> --company <v2파일> --actor <담당자> --dry-run`과 동일 CLI의 실제 등록, activate-company-knowledge를 사용한다. 옵션/출력/기대 revision은 기존 DEMO §4를 유지한다. 새 DB schema나 임의 SQL 수정은 없다. 회사·온톨로지 기존 row는 보존하고 멱등성/감사 확인 뒤 bidops-local만 활성화한다.

## 매핑·설정·실패

기존 match_concepts의 NFKC/casefold·어휘 일치와 3hop 검색을 유지한다. 51concept·4kind·11관계 고정. coverage는 선택10사례 11파일 541카드를 대상으로 준비 도구로 산출한다. 매핑률은 기술 지표로 보고하며 80%는 승인되지 않은 옛 제안이므로 통과 조건으로 쓰지 않는다. unmapped를 임의 alias로 채우지 않는다. 새로운 업무 결정을 요구하는 alias 변경은 새 버전 검토다. 새 환경 설정 없음.

## 테스트 케이스

| ID | 입력/검사 | 기대 결과 |
|---|---|---|
| T1 | 승인 ontology·v2 projection parser 및 파일 변조 | 승인 hash·51개 일치, 중복/잘못된 pointer/변조 거부 |
| T2 | 14사실·3실적·범위 제외·표준절차 대조 | 값/단위/status 보존, 날짜·개별금액 null, 공고 수행 주장 없음 |
| T3 | isolated PostgreSQL CLI 등록·재등록·활성화 | 멱등·감사·기존3사/버전 불변, 다른 회사 graph 활성화 거부 |
| T4 | 프로필/그래프 조회 및 source sidecar 결속 | 안전한 API 형태, 내부 경로/원문 비노출, basis/source 불일치 실패 |
| T5 | 선택10사례 coverage | 541카드·11source, 매핑/미매핑 모두 보고, 기존 원본 hash 불변 |

결정 이유: 사용자가 실적에서 기능 역량을 도출하되 현재 조건·전체 공고 충족과 분리하도록 승인했다. typed sidecar는 기존 strict graph 스키마를 억지 확장하지 않고 이 의미를 보존한다. 운영 등록·모델 호출·회사 편집 UI는 N/A.
