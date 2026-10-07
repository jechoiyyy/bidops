# DEMO 공통 계약 v1.1

- 상태: **2026-10-06 사용자 계획에 따른 구현 목표. 아직 API·DB·모델 실행에 적용하지 않음.**
- 근거: [ADR-0070](../tracking/decisions/0070-multi-company-knowledge-demo.md)과 같은 날 재계획 개정.
- v1.1(2026-10-06 재계획): 2주 일정에 맞춰 핏 승인 흐름·새 분석 승인/receipt 테이블·X-Request-ID·그래프 SVG를 제거하고,
  기존 관례(body `request_id`+`IdempotencyRecord`, 기존 Luna preview/approval)를 재사용한다. 결정과 이유는 ADR-0070 개정 절이 정본이다.
- 이 문서는 DEMO-01~05가 함께 쓰는 새 계약의 정본이다. DEMO-00 Luna 선검증은 기존 단일회사 계약만 쓴다. 기존 계약은 [contracts](../contracts.md)를 따른다.
- 코드 범위: DEMO-01~05는 데모 브랜치 전용이며 운영에 배포하지 않는다. main·운영 배포 대상은 DEMO-00뿐이다.
- 모든 아래 객체는 명시한 key를 필수로 가진다. `?`는 key 생략이 아니라 nullable이다.
  별도로 optional이라고 쓴 요청만 생략 가능하다. 객체에 알 수 없는 key는 거부한다.
  UUID는 canonical UUID 문자열, hash는 lowercase hex64, 시각은 timezone 포함 RFC3339다.

## 1. 회사 문맥과 호환

`BIDOPS_DEMO_ENABLED: bool=false`는 새 회사 API와 데모 UI를 연다. false면 새 경로는 404다.
true여도 seed·migration·모델 호출을 startup에서 하지 않는다. 실제 운영에는 켜지 않는다.
false일 때 /companies 및 하위 UI 경로와 /pre-specs/{id}/company-comparison은 SPA fallback보다 앞선 서버 guard에서 HTTP 404다.
GET /api/demo-config는 항상 {enabled:bool}만 반환한다. 프런트는 이를 읽고 회사 메뉴/route를 등록한다.
demo-config route와 서버 guard는 DEMO-01이 `main.py`의 SPA fallback(`install_frontend`) 등록 전에 구현한다.
회사는 lifecycle의 `Company(id UUID PK, slug unique, name, is_fictional bool, created_at)`다.
새 등록은 UUIDv4, slug는 `^[a-z][a-z0-9-]{1,63}$`, name은 1~128자다. 이 데모 등록은 is_fictional=true만 허용한다.
회사의 활성 profile/graph는 deep_review의 `CompanyKnowledgeBinding`이 소유한다.
전역 환경변수의 active profile을 회사 문맥의 fallback으로 사용하지 않는다.

기존 DeepReview·PreSpecCompanyFitAttempt·ProfileVersion에 nullable company_id를 추가한다.
NULL은 기존 단일회사 계보다. 기존 행을 가상회사로 backfill하지 않는다.
명시적 회사 경로는 해당 회사만 읽고 기존 unscoped 경로의 최신 결과·목록·집계·worker 자동 조회는
company_id IS NULL만 읽는다. 원문 Notice/Opportunity는 공유하며 그 자체에 company_id를 붙이지 않는다.
데모 브랜치에서 강제·검사하는 기존 경로는 자동 worker·hook(company_fit_runner enqueue/claim, auto_preparation,
deep_review_hooks, analysis worker)과 unscoped 최신 결과·목록·집계 조회다. 기존 deep-review/report/evidence의
ID 직접 조회·수정·재시도 경로 전수 점검은 main 병합 전 별도 기능으로 미루며, 그 전에는 데모 브랜치를 운영에 배포하지 않는다.
회사 경로의 ID가 다른 회사 소유 또는 NULL이면 404다.
단순 화면 필터나 클라이언트 전역 값으로 이 경계를 구현하지 않는다.

기존 CompanyProfileSnapshot(screening)의 전역 프로필은 그대로 유지한다.
새 회사 프로필은 deep_review ProfileVersion의 구조화 projection을 사용한다.
기존 version 정수는 DB 전체에서 유일하게 증가하며 회사 내부 버전으로 다시 해석하지 않는다.
회사별 active binding 갱신은 CLI의 명시적 activate 작업만 허용한다. 이전 binding 이력을 보존한다.

## 2. REST 공통형과 회사·추적 API

새 경로는 기존 공통 REST 오류 envelope와 actor 헤더(`X-BidOps-Actor-Name`·`-Format`) 계약을 따른다.
멱등성은 기존 관례를 재사용한다: mutation body에 `request_id:UUID`를 필수로 받고 core `IdempotencyRecord`
(claimed_name, operation, aggregate_type, aggregate_id, request_id)로 중복을 판정한다. 같은 key·같은 request_sha256은
저장한 response_snapshot을 반환하고, 같은 key·다른 request_sha256은 기존 409 idempotency_conflict다. 새 receipt 테이블이나 X-Request-ID 헤더는 만들지 않는다.
없는 회사/타회사 소속 자원은 404, 잘못된 필드는 422, 준비 안 된 버전은 409,
외부 서비스 설정 부재는 503, 내부 오류는 안전한 processing_failed 500이다.
새 오류 code는 응답하는 router의 허용 목록(`core/api_errors.py` `API_ERROR_CODES` 또는 deep_review router 허용 목록)과
프런트 `src/lib/apiErrors.ts`에 함께 등록한다. 허용 목록에 없어 processing_failed로 바뀌는 기존 결함(`manual_request_required`)을 반복하지 않는다.

CompanyDTO = {company_id:UUID,slug:string,name:string,is_fictional:bool,created_at:timestamp}.
`GET /api/companies` → {items:CompanyDTO[],total:int,limit:int,offset:int}; limit 1..100(default 20), offset>=0(default 0), slug 오름차순.
`GET /api/companies/{company_id}` → CompanyDTO.
등록은 DEMO-02 CLI만 사용한다. 임의 회사 생성/삭제 UI는 범위 밖이다.

TrackingDTO = {company_id:UUID,opportunity_id:int,tracking_status:enum,reason:string?,
selected_by:string?,selected_at:timestamp?,revision:int}.
tracking_status = 미선택|계속 추적|보류|종료, revision>=0. 행 부재는 미선택/revision=0/metadata=null이다.
`GET /api/companies/{company_id}/opportunities/{opportunity_id}/tracking` → TrackingDTO.
`PATCH` 같은 경로의 body = {tracking_status:enum,reason:string,expected_revision:int,request_id:UUID} → TrackingDTO.
actor는 헤더, 시각은 서버에서 한 번 정한다. reason은 trim 뒤 1~2000자.
(company_id,opportunity_id) 유일 행을 잠그고 expected_revision 불일치는 기존 409 version_conflict다.
성공하면 revision+1, 동일 상태 저장도 새 결정이다. 미선택 reset은 현재 metadata를 null로 하고 감사에는 사유·actor를 보존한다.
현재 상태·append-only 결정 event·IdempotencyRecord는 같은 transaction이다.
화면은 계속 추적·보류·종료 세 상태를 모두 저장한다. 사전규격 화면은 계속 추적만 두는 2026-09-17 결정의 데모 회사 경로 한정 예외다.
이 결정은 기존 Opportunity의 tracking/recheck 필드나 다른 회사의 신호를 수정하지 않는다.
입찰 delta·사업 합치기·일괄 추적·보류 일정은 이 데모 UI에 연결하지 않는다.

## 3. 온톨로지·원본·그래프

온톨로지 원본: {schema_version:"bidops.company-ontology.v1",version:string,
concepts:[{id:string,label:string,aliases:string[],kind:capability|technology|domain|qualification}],
relations:[{type:RelationType,from_types:NodeType[],to_types:NodeType[],evidence_required:bool}]}.
동일 concept id/alias의 모호한 매핑을 거부하며 version과 canonical JSON SHA-256을 고정한다.
NodeType = company|capability|technology|domain|staff_group|project|qualification|notice|requirement|evidence.
다음 관계 집합만 허용하며 원본이 다른 조합을 선언해도 거부한다.

| RelationType | from → to | 의미 |
|---|---|---|
| has_capability | company → capability | 수행 역량 |
| uses_technology | project/capability → technology | 사용 경험/기술 |
| operates_in | company/project → domain | 업무 분야 |
| has_staff | company → staff_group | 인력군 |
| performed | company → project | 실적 |
| supports_capability | project/staff_group → capability | 관련 근거이며 충족 보증 아님 |
| holds_qualification | company → qualification | 자격 보유 주장 |
| supported_by | company/capability/technology/domain/staff_group/project/qualification/requirement → evidence | 원본 근거 |
| has_requirement | notice → requirement | 문서에서 확인한 요구 |
| requires_capability | requirement → capability | 요구 역량 |
| requires_qualification | requirement → qualification | 필수/선택 자격 요구 |

회사 파일 = {schema_version:"bidops.company-knowledge-source.v1",company:{slug,name,is_fictional:true},
scenario_version:string,ontology_version:string,ontology_sha256:hash,nodes:Node[],edges:Edge[]}.
Node = {id:string,type:NodeType,label:string,concept_id:string?,status:confirmed|inferred|unknown,
origin:fictional_scenario|public_document|model_inference,value:JSON?,source_refs:SourceRef[]}.
Edge = {id:string,type:RelationType,from_id:string,to_id:string,status:confirmed|inferred|unknown,
origin:fictional_scenario|public_document|model_inference,source_refs:SourceRef[]}.
SourceRef = {source_id:"self",locator:{json_pointer:string},quote:string}.
입력 SourceRef에는 source_sha256 key를 허용하지 않는다. 원본 bytes를 먼저 hash하고 저장 projection에서만 source_sha256을 추가한다.
그 projection을 입력 파일에 되쓰지 않는다. 입력은 UTF-8 JSON이며 YAML은 v1 CLI에서 받지 않는다.
회사 원본에는 company 1개와 회사 사실 노드만 허용한다. notice/requirement/public_document/model_inference는
등록 파일에서 거부하며 분석 결과 overlay에서만 사용한다. evidence 노드는 원본의 사실 위치를 가리킨다.
노드/관계 id는 각 집합 내 고유한 stable key(`^[a-z][a-z0-9_.:-]{0,127}$`)다.
unknown의 value=null/source_refs=[]; 다른 사실 노드는 source_ref가 정확히 1개, 관계는 1개 이상 필요하다. 관계 source_ref는 존재하는 non-unknown 노드의 동일 source_ref를 재사용한다.
인용은 지정된 원본 위치와 대조한다. evidence 노드는 다른 evidence를 근거로 요구하지 않는다.
JSON value는 아래 열거한 구조화 타입만 허용한다. 자유 prompt/경로/secret 필드는 받지 않는다.

노드 value의 타입은 company/domain/technology/qualification은 문자열 또는 null,
capability는 {scope:core|non_core,description:string} 또는 null,
staff_group은 {role:string,total:int?,available:int?,as_of:date?},
project는 {role:string,scope:string,amount_krw:int?,started_on:date?,ended_on:date?},
evidence는 {fact_key:string}, notice는 {notice_id:int}, requirement는 {text:string,mandatory:bool?}다.
available<=total(둘 다 있을 때), 금액·인원 음수 금지. unknown 값을 숫자 0으로 보정하지 않는다.
qualification 문자열은 "보유" 또는 "미보유"처럼 명시된 시나리오 값을 보존하며 unknown과 구분한다.

저장: KnowledgeOntologyVersion, CompanyKnowledgeVersion, CompanyKnowledgeNode,
CompanyKnowledgeEdge, CompanyKnowledgeSource, CompanyKnowledgeBinding 및 binding event.
버전은 UUID, graph version은 company_id·ontology_id·원본 hash·snapshot hash를 포함한다.
노드 PK=(graph_version_id,node_id), 관계 양끝은 같은 graph version FK로 묶는다.
등록은 전체 transaction이며 원본 저장 hash 검증 뒤 commit. 원본 재등록은 동일 company/ontology/source hash면 같은 버전.
같은 slug의 내용 변경은 새 버전이며 회사 identity는 유지한다. name 변경은 이 데모에서 company_identity_conflict로 거부한다. 기존 profile/graph는 덮지 않는다.

## 4. 프로필 projection·CLI·그래프 조회

`python -m app.deep_review.cli import-company-knowledge --ontology <file> --company <file> --actor <name> [--dry-run]`
→ {company_id:UUID?,profile_version_id:UUID?,graph_version_id:UUID?,ontology_version:string?,
source_sha256:hash?,graph_sha256:hash?,created:bool,activated:false,errors:string[]}.
dry-run은 DB/객체/모델 쓰기 없이 검사하며 ID는 null, created=false다.
`activate-company-knowledge --company-id <uuid> --graph-version-id <uuid> --actor <name>`는
같은 회사 profile/graph binding을 원자적으로 활성화하고 이전 binding 감사 이력을 남긴다.
회사의 최초 생성은 lifecycle 공개 service를 부르며 deep_review가 lifecycle 테이블을 직접 쓰지 않는다.
가상 자료는 운영 경로·image로 복사하지 않고 외부 fixture 디렉터리에서 명시적으로 등록한다.

각 non-evidence 회사 노드의 id를 profile fact_key로 투영한다. unknown은 evidence 0개, confirmed/inferred는 동일 source locator/hash로 ProfileEvidence 정확히 1개를 만든다.
관계는 별도 graph 입력이며 임의 문자열 facts로 중복 생성하지 않는다.
기존 프로필 파서의 고정 source_file 검증을 우회하지 않는다. 새 bidops.company-profile.v2를 추가해
company_id, origin, graph_version_id, ontology_version을 포함하고 기존 v1 소비를 그대로 유지한다.
가상 confirmed 사실의 의미는 "시나리오 확정"이며 전송 payload에도 origin을 보존한다.

`GET /api/companies/{company_id}/profile` → {schema_version:"bidops.company-profile-view.v1",
company:CompanyDTO,profile_version_id:UUID,profile_sha256:hash,graph_version_id:UUID,
graph_sha256:hash,ontology_version:string,facts:[{fact_key:string,label:string,status:confirmed|inferred|unknown,
origin:fictional_scenario,value:JSON?,evidence_ids:UUID[]}]}.
미등록은 409 company_profile_not_ready. optional query graph_version_id로 과거 버전을 조회할 수 있다.
`GET /api/companies/{company_id}/knowledge-graph?graph_version_id=&root_node_id=&depth=&limit=`
→ {schema_version:"bidops.company-knowledge-graph.v1",company_id:UUID,graph_version_id:UUID,
graph_sha256:hash,ontology_version:string,nodes:PublicNode[],edges:PublicEdge[],truncated:bool,omitted_node_count:int}.
PublicNode={id,type,label,concept_id,status,origin,value,evidence_ids:UUID[]}, PublicEdge={id,type,from_id,to_id,status,origin,evidence_ids:UUID[]}.
공통 이름의 타입은 §3 Node/Edge와 같지만 source_refs는 공개형에 존재하지 않는다. evidence_ids는 등록시 만든 해당 버전 ProfileEvidence를 가리킨다.
evidence 노드와 관계는 source_ref가 가리키는 non-unknown fact의 evidence_id를 사용한다. unknown은 빈 배열이다.
depth 1..3(default 2), limit 1..500(default 200), root 생략은 company 노드.
양방향 BFS 후 거리/id 순서, 노드 절단 후 양끝이 남은 edge만 반환한다.
omitted_node_count는 root에서 depth 이내 도달 가능한 노드 수 minus 반환 노드 수다. truncated는 이 수>0이다.
방문한 노드는 다시 큐에 넣지 않아 cycle에도 종료한다. truncation은 분석 누락의 증명이 아니다.
회사 근거 전용 GET /api/companies/{company_id}/profile-evidence/{evidence_id}는
{evidence_id,profile_version_id,fact_key,origin,quote,source_sha256}를 반환하며 원본 전문/경로는 반환하지 않는다.

## 5. 분석 입력·실행·현재성

문서 구조와 회사 비의존 v7 개요를 공유한다. 기존 v8 회사 의존 판정을 공통 개요로 재사용하지 않는다.
DEMO의 회사 적합성 정본은 v2 회사 핏 결과다. 기존 C-1의 grade/정정/참여 준비를 가상회사에 복사하지 않는다.
핏 enum과 실행 상태는 기존 company-fit 계약을 유지한다. DTO는 기존 값을 response.result 아래 보존한다.

새 입력 CompanyAnalysisInput = {schema_version:"bidops.company-analysis-input.v1",purpose:company_fit|deep_review,
execution_nonce:UUID,target_review_id:UUID?,company_id:UUID,profile_version_id:UUID,profile_sha256:hash,graph_version_id:UUID,graph_sha256:hash,
ontology_version:string,ontology_sha256:hash,notice_id:int,document_version_ids:UUID[],bundle_id:UUID?,
overview_run_id:UUID,overview_sha256:hash,policy_version_id:UUID,policy_sha256:hash,
model_name:string,model_revision:string?,generation_config_sha256:hash,
requirements:Requirement[],profile_facts:ProfileFactInput[],profile_evidence:ProfileEvidenceInput[],
graph_nodes:PublicNode[],graph_edges:PublicEdge[],graph_paths:GraphPath[],
coverage:{included_requirement_ids:string[],unmapped_requirement_ids:string[],excluded_fact_keys:string[],
excluded_path_count_by_requirement:[{requirement_id:string,count:int}]}}.
ProfileFactInput={fact_key:string,status:confirmed|inferred|unknown,origin:fictional_scenario,value:JSON?,
quote:string,locator:{fact_key:string}}. value는 §3의 노드별 타입이며 unknown quote=""이다.
ProfileEvidenceInput={profile_evidence_id:UUID,profile_version_id:UUID,fact_key:string,source_sha256:hash,
locator_type:"profile_fact",locator:{fact_key:string},quote:string,origin:fictional_scenario}.
Requirement={id:string,text:string,concept_ids:string[],mandatory:bool?,
source_units:SourceUnit[],document_requirement_ids:string[]}.
SourceUnit은 narrative 입력의 원문 unit과 같은 필드 집합: {requirement_id:string,document_version_id:UUID,
structure_id:UUID,source_sha256:hash,document_ordinal:int,page:int,block_order:int,
locator_type:"page",locator:{page:int},text:string,document_requirement_ids:string[]}이며 페이지는 1부터 시작한다.
문서는 bundle ordinal/document_version_id 순, 페이지는 오름차순, block은 원본 순이다.
기존 분할기 `DeepReviewService._requirements`(narrative 설정 그대로)를 재사용하며 출력 순서·필드를 바꾸지 않는다.
원문 hash와 locator를 동결 payload에 포함하여 stage v2 출력이 그대로 참조하게 한다.
원문 단위 id는 기존 분할기가 만드는 requirement_id(`req-{ordinal}-{page}-{block}-{hash10}`)를 그대로 쓴다. 기존 형식을 바꾸지 않는다.
document_version_id·structure_id·source_sha256이 없는 fallback unit이 생기면 회사 입력 생성은 company_input_invalid로 실패하며 unit을 지어내지 않는다.
개요 요구 id는 `overview:{overview_run_id}:{section}:{index}`(index 0부터)다.
핏 Requirement.id는 개요 ref, 심층 Requirement.id는 source_unit.requirement_id다.
문서 원래 requirement 번호와 inventory.requirement_ids는 document_requirement_ids에 원문 그대로 보존한다.
서로 다른 namespace를 한 ID로 매핑하지 않는다. inventory에서 번호가 없으면 빈 배열이다.
개요의 페이지·인용을 해당 structure의 원문 unit에 연결하며 SourceUnit의 식별자는 결정적이다.
모델 출력 document EvidenceRef UUID는 기존 검증·저장 단계에서 생성되므로 사전 입력에 가짜 evidence FK를 만들지 않는다.
GraphPath={requirement_id:string,node_ids:string[],edge_ids:string[],profile_evidence_ids:UUID[],relation:direct|partial|unmapped}.
direct는 요구 concept과 회사의 core/non_core capability 또는 qualification이 직접 연결됨,
partial은 그 concept에 supports_capability로 연결된 실적/인력 근거 경로,
unmapped는 node_ids/edge_ids/profile_evidence_ids가 빈 목록이다. 이는 역량 충족 판정이 아니다.
graph_nodes/edges에는 경로 해석에 필요한 type/label/value/status/origin을 싣고 evidence_ids를 근거 목록과 결속한다.

공유 사전규격 근거 문장과 문서 unit은 위의 구분된 식별자로 연결한다. 용어 정규화는 Unicode NFKC/casefold/연속 공백 압축이다.
정규화 뒤 한글을 포함한 label/alias(2자 이상)는 부분 문자열로 일치시켜 조사·복합어를 허용한다.
한글이 없는 label/alias(영문·숫자)는 앞뒤 문자가 영문·숫자가 아닌 경계에서만 일치시킨다(예: "ai"가 "mail"에 걸리지 않음).
한글 1자 alias는 온톨로지 등록에서 거부한다. 일치 규칙은 결정적이며 형태소 분석기를 쓰지 않는다.
한 요구에 여러 concept을 보존하며 자동 유사어 확장·임베딩 점수·회사별 임의 가중치는 넣지 않는다.
각 concept에서 해당 회사 has_capability/holds_qualification과 supports_capability 근거를 3 hop까지 탐색한다.
반복 노드는 재방문하지 않는다. 필수 자격과 unknown 사실은 어휘 일치 여부와 무관하게 입력에 포함한다.
단일 slice 예산은 새 정책에 명시하고 기존 narrative 예산에서 시작한다(tunable).
초과는 요구사항 단위 분할/후속 회사 대조 slice로 처리하고 source 하나가 예산을 넘으면 기존 안전 오류로 실패한다.
누락 항목은 coverage에 남기며 요구사항 자체를 잘라 성공시키지 않는다.

모델은 제공된 ref만 인용한다. 후보 연결/해석은 결과로만 보존하고 회사 graph로 승격하지 않는다.
핏 생성은 사설 overview 설정, 심층은 codex-exec Luna/xhigh와 새 불변 demo 정책을 사용한다.
새 demo 정책은 DEMO-00이 운영 1489번으로 검증한 `analysis-policy-luna-v4`에 회사·그래프 입력 설명만 더한다.
v4와 demo 정책은 모두 기존 v2의 정상 검증 계약을 기반으로 하며 v3 검증 off를 상속하지 않는다.
승인 정책은 이미지에 포함된 파일과 `_approved_policy_path` 매핑으로만 인정되므로 새 파일마다 매핑과 테스트를 함께 추가한다.
매핑은 정책 내용(검증 flag)으로 v1~v3를 고르므로 v4·demo 정책은 고유 식별 필드를 두고 그 필드를 먼저 검사한다(필드 이름은 DEMO-00 STEP-002가 정한다).
demo 정책은 v4의 정책 마감(`execution.review_timeout_seconds`, 18000)과 slice 1회 교정 재요청(`execution.validation_repair_attempts`=1)을 그대로 상속한다.
출력 ID와 입력 considered ID의 역할을 프롬프트에 분리하고 필수 근거 FK/인용/숫자/coverage 검사를 유지한다.
기존 선택적 related_claim 경고 규칙은 그대로 가능하나 필수 evidence/전제 실패를 경고로 낮추지 않는다.

모든 모델 호출은 동결 입력에 연결한다. 핏은 승인된 사설 vLLM만 쓰므로(기존 핏도 건별 승인 없음) 건별 미리보기·승인 없이
§9의 CLI `enqueue-company-fit`으로 회사·공고별 attempt를 등록하고, 입력은 enqueue transaction에서 동결한다.
외부 전송인 심층은 기존 Luna preview/approve(DeepReviewPreview·DeepReviewApproval)에 company_id를 더해 재사용한다.
공용 슬롯 밖의 worker는 만들지 않는다. GET은 모델 호출을 만들지 않는다.
실패 재요청은 핏은 새 enqueue, 심층은 새 preview/승인/attempt이며 자동 재호출·fallback하지 않는다.
현재성은 회사 active binding + 문서/bundle/개요 + 정책/model/generation 전체가 같은지로 판정한다.
새 binding으로 재분석하기 전에는 과거 결과를 is_current=false로 보여 주고 다른 회사 결과로 채우지 않는다.
실행 중 버전 변경은 이미 승인된 실행을 변경하지 않는다.

## 6. 회사별 분석 REST와 비교

base=/api/companies/{company_id}; 각 endpoint는 기존 service에 명시적 회사 context를 전달한다.
- GET base/pre-specs: {schema_version:"bidops.company-pre-spec-list.v1",items:CompanyNotice[],total,limit,offset}.
  CompanyNotice={notice_id:int,opportunity_id:int?,title:string?,posted_at:timestamp?,
  deadline_at:timestamp?,fit:CompanyFitSummary?,review:CompanyReviewSummary?,tracking:TrackingDTO?}.
  opportunity 미연결이면 tracking=null. query q/limit/offset는 기존 목록 검색 규칙, 추가 fit=matched|mismatch|unknown,
  tracking_status는 §2 enum, sort=posted_at_desc(default)|deadline_asc, null은 뒤·notice_id DESC tie-break.
  fit 필터는 현재 completed 결과만, 오류/미판정은 필터 없음에서 볼 수 있다. 서버가 pagination 전에 적용한다.
  모집단은 DB에 적재된 SW사업대상=Y 사전규격 전체다. 데모 환경은 manifest 6건만 적재하므로(§10) 목록도 그 6건이다.
- GET base/pre-specs/{notice_id}: 같은 CompanyNotice + {overview_run_id:UUID?,bundle_id:UUID?,
  document_version_ids:UUID[],company_id:UUID}; 원문 상세는 기존 공통 공고 API를 읽는다.
- GET base/pre-specs/{notice_id}/company-fit → {company_id,notice_id,attempts:CompanyFitView[]}.
  CompanyFitView는 `schemas/company_fit.py`의 기존 CompanyFitView + {company_id,graph_version_id,graph_sha256,ontology_version,
  input_sha256,paths:GraphPath[]}다. 결과 schema만 bidops.prespec-company-fit-result.v2로 올리고 reasons에
  graph_path_indexes:int[]를 추가한다. 기존 kind/decision/ref 필드는 유지한다.
- 회사 핏 실행은 REST가 아니라 §9 CLI `enqueue-company-fit`이다. 회사 핏 생성용 POST endpoint와 승인 화면은 없다.
- POST base/pre-specs/{notice_id}/deep-review-previews, body={bundle_id:UUID,source_verification_enabled:true,
  review_id:UUID? (optional)} → CompanyDeepReviewPreviewDTO.
- POST base/pre-specs/{notice_id}/deep-reviews, body={preview_id:UUID,source_verification_enabled:true,request_id:UUID,bundle_id:UUID}
  → 202 CompanyReviewView. body는 기존 Luna 생성 body와 같다.
- GET base/deep-reviews/{review_id} → CompanyReviewView; POST 같은 경로/attempts body={preview_id,source_verification_enabled:true,request_id} → 202 기존AttemptView.
- GET base/deep-reviews/{review_id}/report → 기존 ReportView를 보존하는 {schema_version:"bidops.company-report-view.v1",company_id:UUID,graph_version_id:UUID,graph_sha256:hash,
  ontology_version:string,profile_version_id:UUID,view:ReportView}; 근거는 base/deep-reviews/{review_id}/evidence/{evidence_id}에서 기존 EvidenceView로 조회한다.

CompanyDeepReviewPreviewDTO=기존 Luna preview 응답({preview_id,input_sha256,provider,model,reasoning_effort,quality_status,
source_verification_enabled,input}) + {company_id:UUID,profile_version_id:UUID,graph_version_id:UUID,graph_sha256:hash,ontology_version:string}이며
input은 CompanyAnalysisInput(purpose=deep_review)이다. quality_status는 unmeasured_reference다.
input은 명시적 전송 승인 화면에만 제공하며 일반 GET이나 로그에 노출하지 않는다.
CompanyReviewView=기존DeepReviewView + {company_id,profile_version_id,graph_version_id,graph_sha256,ontology_version,input_sha256,is_current:bool}.
CompanyFitSummary={attempt_id:UUID,status:queued|running|completed|failed|needs_human_review,
decision:matched|mismatch|unknown|null,summary:string?,is_current:bool}.
CompanyReviewSummary={review_id:UUID,status:queued|running|completed|failed,is_current:bool}.

심층 preview·승인은 기존 Luna 규칙을 그대로 따른다: 신규 preview는 매번 새 UUID, 승인은 DeepReviewApproval의
preview/attempt unique로 1회만 허용, 같은 request_id 재요청은 최초 응답, 다른 request_id로 이미 사용한 preview는 409 preview_used,
승인 시 다시 만든 입력과 hash가 다르면 409 preview_changed. 승인 시 회사/공고/문서/graph를 재검증한다.
미리보기 실패 시 저장된 모델 작업은 없어야 한다. 회사 핏 미일치/미확인은 심층 수동 요청 금지 사유가 아니다.
회사 경로의 자격은 SW사업대상=Y, ready bundle, completed v7 개요, 활성 회사 binding·정책과 외부 승인 조건이다.
C-1 `우선 검토` 등급은 요구하지 않는다. 그 등급은 실제 회사 프로필로 만든 판정이므로 가상회사 자격에 섞지 않으며,
기존 단일회사 핏의 grade_not_priority 규칙은 NULL 계보 경로에만 남는다.

`GET /api/pre-specs/{notice_id}/company-comparison` → {schema_version:"bidops.company-comparison.v1",
notice_id:int,document_version_ids:UUID[],items:[{company:CompanyDTO,fit:CompanyFitSummary?,
review:CompanyReviewSummary?,tracking:TrackingDTO?,graph_version_id:UUID?,
comparison_status:comparable|stale|missing|different_input}]}.
§7의 세 slug만 대상으로 slug 오름차순이다. 추가 회사는 비교 모집단에 넣지 않는다.
fit/review 각각 created_at DESC, UUID DESC의 최신 생성 실행을 선택한다. 최신이 실패/대기여도 과거 completed로 fallback하지 않는다.
공통 current 문서 버전 집합과 존재하는 fit/review 중 하나라도 다르면 different_input,
그 외 하나라도 is_current=false면 stale, 그 외 둘 중 하나라도 없으면 missing, 나머지 comparable이다.
우선순위는 different_input > stale > missing > comparable이며 각 실행 status는 그대로 별도 표시한다.
미완료 상태는 summary.status에 별도로 표시한다. 회사 순위나 종합 점수를 브라우저가 만들지 않는다.

## 7. 시연 표본·품질·범위

세 slug=demo-public-si|demo-data-ai|demo-cloud-si, 이름=데모 업무SI|데모 데이터AI|데모 클라우드SI.
비슷한 규모·서로 다른 전문 영역으로 작성하며 정확한 가상 수치는 fixture 작성자의 창작값으로 표시한다.
각 회사는 주력역량·기술·인력군·실적의 역할/과업·자격 미확인·명시된 비주력 영역을 포함한다.
실적은 실제 회사 자료에서 복사하지 않는다. 수치 설정은 공고 결과를 보기 전에 고정한다.
작성 절차: Claude가 3사 원본과 온톨로지 초안을 쓰고 사용자가 승인한 뒤 공고 선정 전에 동결한다.
승인 기록(승인자·시각·각 원본 source_sha256)은 DEMO-02 증거 디렉터리에 남기며, 승인 전 원본은 등록하지 않는다.
온톨로지 개념(id·kind·relations)과 회사 사실 노드·관계는 공고 선정 전에 동결한다. 공고 선정 뒤 별칭(aliases)만 1회 보강할 수 있다.
보강은 개념 추가·삭제·kind 변경 없이 새 ontology version으로 발행하고, 회사 원본은 ontology_version/ontology_sha256 두 필드만 바꿔
재등록한다(새 source/profile/graph 버전). 추가한 별칭과 사유를 DEMO-05 증거에 diff로 남긴다.

표본 manifest `bidops.demo-corpus.v1`={schema_version,version:string,created_at:timestamp,
companies:[{company_id:UUID,profile_version_id:UUID,profile_sha256:hash,graph_version_id:UUID,graph_sha256:hash,ontology_version:string,ontology_sha256:hash}],
notices:[{notice_id:int,notice_key:string,domain:public_si|data_ai|cloud_ops,source_run_id:string,source_sha256:hash,
documents:[{document_version_id:UUID,source_sha256:hash}],overview_run_id:UUID,overview_sha256:hash,bundle_id:UUID,deep_review:bool}],
bindings:[{purpose:company_fit|deep_review,policy_version_id:UUID,policy_sha256:hash,model_name:string,
model_revision:string?,generation_config_sha256:hash}],expected_fit_count:18,expected_report_count:9,
first_deep_review_notice_id:int}.
first_deep_review_notice_id는 deep_review=true인 notice 중 하나이며 최소 시연 기준의 대표 공고다.
회사 id와 slug 대응은 §7 고정 3사로 제한하고 company_id/notice_id/notice_key/document_version_id는 각 집합에서 유일하다.
documents는 document_version_id 오름차순이며 ID/hash를 한 객체로 묶는다. bindings는 purpose마다 정확히 1개다.

분야별 2건, deep_review=true는 분야별 1건, 동일 6건×3사의 적합성·대표 3건×3사의 심층검토다.
최근 수집한 사전규격 중 SW=Y·G2B에서 첨부를 지금 다시 받을 수 있음·해당 분야 과업 명시·공개 원문 위치 확인 순으로 고른다.
첨부를 받지 못한 공고는 표본에서 빼고 같은 기준의 다음 후보로 바꾼다. 운영 MinIO 사본을 수동 업로드해 채우지 않는다.
보고서 시간 때문에 원문 단위 수(기존 분할기 기준)가 적은 공고를 우선한다. deep_review=true 3건은 8개 이하를 목표로 하고 넘으면 사유를 manifest 증거에 남긴다.
부족한 자료는 추가 수집 후 새 불변 manifest로 만들며 사례를 임의 가상 공고로 바꾸지 않는다.
문서나 프로필이 바뀌면 manifest 새 버전이며 옛 결과 수를 새 인수에 더하지 않는다.

실제 성공 증거는 execution/attempt/report ID, 회사·입력 hash, model/policy, 종료 상태,
검증 요약, 사용량/시간(null 보존), 화면 캡처, 담당자 확인 항목이다. 원문/secret/원응답은 일반 증거 로그에 쓰지 않는다.
참조 표식 unmeasured_reference는 유지한다. 검증 성공도 운영 정책 품질 gate 통과를 뜻하지 않는다.
최소 첫 대표 1건×3사 완료 후 나머지 2건×3사를 실행한다. 사용자 승인 없이 모델 자동 반복 호출하지 않는다.

목표와 최소 시연 기준을 구분한다. 목표(overall pass)는 핏 18건·보고서 9건과 9건 인수다.
최소 시연 기준(demo_ready)은 핏 18건과 first_deep_review_notice_id의 3사 보고서 3건 완료·인수다.
demo_ready만 충족하면 나머지 보고서는 실패·미실행 기록과 함께 시연하며, 이를 9건 완료나 overall pass로 적지 않는다.


## 8. 등록·저장·fingerprint 상세

공개 lifecycle service `register_company(session, *, slug:str, name:str, is_fictional:bool, actor:str) -> CompanyRegistration`
의 반환은 {company_id:UUID,created:bool}다. caller가 transaction을 소유하고 service는 flush만 한다.
동일 slug/name/is_fictional은 멱등, 다른 name/is_fictional은 409 company_identity_conflict다.
동시 동일 등록은 unique 충돌 후 savepoint에서 기존 행을 검증한다. Company.name은 v1에서 수정하지 않는다.

CompanyTrackingEvent={id:UUID PK,company_id:UUID FK,opportunity_id:int FK,revision:int,
previous_status:TrackingStatus,new_status:TrackingStatus,reason:string,actor:string,request_id:UUID,created_at:timestamp}.
(company_id,opportunity_id,revision) UNIQUE, revision>=1, 양쪽 상태는 §2 enum, 모두 NOT NULL이다.
tracking 멱등성은 core IdempotencyRecord를 쓴다: operation="company_tracking.set", aggregate_type="company_opportunity_tracking",
aggregate_id="{company_id}:{opportunity_id}", claimed_name=decoded actor, request_id=body request_id, response_snapshot=TrackingDTO.
별도 receipt 테이블은 만들지 않는다. 키에 actor가 들어가므로 같은 request_id라도 actor가 다르면 다른 요청이다(기존 관례).
canonical JSON은 ensure_ascii=false, sort_keys=true, separators=(',',':'), allow_nan=false의 UTF-8이다.
request_sha256={operation,company_id,opportunity_id,tracking_status,trimmed_reason,expected_revision,decoded_actor}의 canonical hash다.
재생 전에 저장 snapshot을 strict TrackingDTO로 검사하고 회사·opportunity가 요청과 다르면 processing_failed(500)이며 DB를 바꾸지 않는다.
event는 append-only이며 actor 문자열은 일반 로그에 출력하지 않는다.

ProfileVersion: 기존 version UNIQUE 유지, UNIQUE(id,company_id)를 추가한다.
DeepReview: legacy company_id IS NULL에서 (notice_id,bundle_id,profile_version_id,policy_version_id) partial UNIQUE,
DEMO-01의 non-NULL에서는 (company_id,notice_id,bundle_id,profile_version_id,policy_version_id) partial UNIQUE.
DEMO-03부터 non-NULL 키 끝에 graph_version_id를 추가한다. 기존 id PK와 profile_version_id 단일 FK는 유지한다.
PreSpecCompanyFitAttempt: 기존 input_sha256 UNIQUE를 유지한다. 새 입력은 회사와 execution_nonce를 포함하며 기존 input_jsonb에 저장한다.
정책 FK는 purpose별로 정확히 하나다: 기존 deep_policy_version_id(analysis_policy_version)를 nullable로 바꾸고 새 nullable company_fit_policy_version_id
(CompanyFitPolicyVersion)를 더한다. CHECK: company_id IS NULL이면 deep_policy_version_id NOT NULL·company_fit_policy_version_id NULL,
company_id NOT NULL이면 그 반대다. 기존 행은 그대로 첫 조건을 만족한다.
FrozenProvenance 저장 열: 핏 attempt와 DeepReviewPreview에 nullable provenance_jsonb를 더하고 company_id NOT NULL 행에서는 NOT NULL을 CHECK로 강제한다.
DeepReviewPreview·DeepReviewApproval(DEMO-03): nullable company_id를 추가한다. 회사 preview로 만든 review/attempt는 같은 company_id여야 하며
service가 검사하고 PG 검사로 증명한다. NULL preview는 기존 Luna 경로 그대로다.
review/fit에는 (profile_version_id,company_id) → ProfileVersion(id,company_id) composite FK(MATCH SIMPLE)를 둔다.
NULL의 MATCH SIMPLE 우회는 PG trigger가 profile.company_id IS NOT DISTINCT FROM row.company_id인지 검사해 차단한다.
SQLite 테스트에는 같은 service 불변식을 적용하고 PG 검사가 DB 강제를 증명한다.
새 테이블·열의 app/worker/ro_backup 권한은 migration이 아니라 `scripts/runtime-privileges.sql`에 추가하고
`tests/app/test_runtime_database_privileges.py`로 검사한다. 추가하지 않으면 새 테이블은 app·worker가 접근할 수 없다.
deep_review가 새 lifecycle 공개 파일(예: `lifecycle/schemas/companies.py`)을 import하면 `tests/app/boundary_map.py`의 lifecycle 공개 표면을 함께 갱신한다.

KnowledgeOntologyVersion={id:UUID PK,version:string UNIQUE,sha256:hash UNIQUE,payload:Ontology,created_at:timestamp}.
동일 version/digest는 재사용하고 동일 version/다른 digest는 ontology_version_conflict로 거부한다.
version을 포함한 canonical payload hash이므로 다른 version의 동일 digest는 허용하지 않는다.
CompanyKnowledgeSource={id:UUID PK,company_id:UUID FK,source_sha256:hash,size_bytes:int,
content_object_id:UUID FK,content_location_id:UUID FK,created_at:timestamp}; UNIQUE(company_id,source_sha256), UNIQUE(id,company_id).
content_location_id는 `ContentObjectLocation`을 가리킨다. ContentObject·ContentObjectLocation의 고정 object version·hash를 그대로 사용한다. size_bytes>0, 원문은 UTF-8 JSON이다.
CompanyKnowledgeVersion={id:UUID PK,company_id:UUID FK,ontology_id:UUID FK,source_id:UUID FK,
profile_version_id:UUID FK,source_sha256:hash,graph_sha256:hash,snapshot:JSON,created_at:timestamp}.
UNIQUE(company_id,ontology_id,source_sha256), UNIQUE(id,company_id,profile_version_id).
Version의 (profile_version_id,company_id) → ProfileVersion(id,company_id),
(source_id,company_id) → CompanyKnowledgeSource(id,company_id) composite FK를 강제한다. 모두 NOT NULL이며 타회사 조합을 DB에서 거부한다.
CompanyKnowledgeNode={graph_version_id:UUID FK,node_id:string,payload:Node}; PK=(graph_version_id,node_id).
CompanyKnowledgeEdge={graph_version_id:UUID FK,edge_id:string,from_id:string,to_id:string,payload:Edge}; PK=(graph_version_id,edge_id),
끝점 composite FK=(graph_version_id,from_id/to_id) → node PK. 저장 payload의 id/끝점은 열 값과 같아야 한다.
CompanyKnowledgeBinding={company_id:UUID PK/FK,graph_version_id:UUID,profile_version_id:UUID,revision:int,updated_at:timestamp,actor:string}.
(graph_version_id,company_id,profile_version_id) composite FK → graph version. revision>=1.
CompanyKnowledgeBindingEvent={id:UUID PK,company_id:UUID FK,revision:int,graph_version_id:UUID,profile_version_id:UUID,
previous_graph_version_id:UUID?,actor:string,created_at:timestamp}; UNIQUE(company_id,revision), graph/profile 소속 FK 동일.
모든 위 필드는 ? 외 NOT NULL이다. version/source/node/edge/event는 append-only, binding pointer만 갱신할 수 있다.
같은 binding 재활성화는 멱등으로 revision/event를 늘리지 않는다. 회사 잠금으로 활성화 경합을 직렬화한다.

source_sha256과 profile_sha256은 입력 원본 bytes의 SHA-256이다. 입력 SourceRef에 hash를 넣지 않는다.
ontology는 canonical JSON hash. graph_sha256은 아래 snapshot의 canonical JSON hash다:
{schema_version:"bidops.company-knowledge-snapshot.v1",company_slug,ontology_version,ontology_sha256,
source_sha256,nodes:StoredNode[],edges:StoredEdge[]}. StoredNode/StoredEdge는 입력 Node/Edge의 source_refs만
StoredSourceRef={source_id:"self",source_sha256:hash,locator:{json_pointer:string},quote:string}로 확장한 내부형이다.
nodes/edges는 id 오름차순, source_refs는 json_pointer/quote 순서다.
DB UUID/created_at/active binding/ProfileEvidence UUID는 graph hash에 넣지 않는다.
원본 bytes가 다르면 의미가 같아도 새 source/profile/graph 버전이다. DB UUID는 원본 hash 재현에 관여하지 않는다.

profile v2 payload 전체 = {schema:"bidops.company-profile.v2",company_id:UUID,origin:"fictional_scenario",
source_sha256:hash,graph_version_id:UUID,ontology_version:string,facts:FactV2[],parse_errors:[]}.
FactV2={fact_key:string,status:confirmed|inferred|unknown,value:NodeValue?,section_id:NodeType,
section_number:null,locator:{fact_key:string},quote:string,origin:"fictional_scenario"}.
source_file key는 v2에서 금지한다. fact는 non-evidence node마다 1개, node id 오름차순, 총 1..256개다.
unknown은 quote=""·value=null·ProfileEvidence 0개; 나머지는 source_ref 정확히 1개로 ProfileEvidence 정확히 1개.
non-evidence 사실 노드의 SourceRef.json_pointer는 그 노드의 /value 또는 /value 하위 scalar를 가리키며 quote는 그 scalar의 실제 문자열이다.
숫자/bool 인용은 JSON 표기와 같아야 한다. JSON escape는 parse 뒤 scalar 값으로 대조하며 임의 정규화하지 않는다.
관계/evidence 노드는 이미 존재하는 사실의 source_ref만 참조한다. 가짜 evidence row를 만들지 않는다.
ProfileEvidence locator_type=profile_fact, locator={fact_key}, source hash는 원본 hash다. 내부 source pointer 대응은 graph snapshot에 보존한다.
v1 validator와 v2 validator는 schema별로 분기하고 어느 쪽도 다른 source 형태로 자동 fallback하지 않는다.

capability/technology/domain/qualification의 concept_id는 해당 kind concept의 필수 id, 그 외 노드는 null이다.
NFKC/casefold/공백 압축 후 label/alias는 concept 전체에서 유일해야 하며 같은 concept 내부 중복도 거부한다.
relations는 §3의 11개 type 전부를 정확히 선언한다. source/target 집합은 표와 같아야 하며 evidence_required=true로 고정한다.
unknown 관계만 source_refs=[] 예외이며 모델에 미확인으로 전달한다. 관계의 두 노드는 해당 ontology와 같은 snapshot에 속한다.
capability.value.scope=non_core가 명시적 비주력이다. 이것만으로 미보유·자격 미충족을 추론하지 않는다.

import CLI created는 새 graph version 생성 여부다(ontology/company/profile 동반 생성 여부와 별개).
dry-run의 ID들은 null; errors=[]이면 exit0, 유효성/내용 충돌은 exit2, 저장/의존 실패는 exit1이다.
실패 JSON은 동일 key 집합을 유지하고 알 수 없는 hash/ID/ontology_version은 null, created=false, activated=false다.
stdout은 결과 JSON 하나, stderr는 안전한 code만 사용한다. argparse 문법 오류는 stderr/exit2다.
activate 출력={company_id:UUID?,graph_version_id:UUID?,profile_version_id:UUID?,revision:int?,changed:bool,errors:string[]}.
성공 시 모든 ID/revision은 non-null이다. 실패 시 company/graph ID는 유효한 UUID 요청값만 유지하고 파싱 실패는 null, 모르는 profile/revision은 null. errors는 안전 code 배열, exit 규칙은 import와 같다.
등록 오류 code는 source_invalid|ontology_invalid|ontology_version_conflict|company_identity_conflict|source_unavailable|storage_failed.
활성 오류 code는 company_not_found|graph_not_found|graph_company_mismatch|profile_invalid|storage_failed다.

## 9. 정책·분석 요청의 정확한 실행 계약

새 설정 BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID와 BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID는 UUID 또는 빈 값(default)이다.
web과 analysis-worker에 같은 값을 명시 주입한다. 기존 전역 active policy를 대신 읽지 않는다.
핏은 신규 CompanyFitPolicyVersion(id UUID PK,sha256 hash UNIQUE,payload JSON,created_at timestamp)이며
기존 fit_policy/model/revision/generation을 고정한 bidops.company-fit-policy.v2를 저장한다.
이 payload 전체는 {schema_version,model_name,model_revision,prompt_version,generation,stages,system_prompt,
prompt_output_contract,chunking}이다. schema_version은 bidops.company-fit-policy.v2다. model_revision은 기존 코드 함수
`fit_policy(model)`(company_fit.py)에 없는 새 키이며(기존에는 동결 입력에만 있음) 운영과 같은 qwen3.8-27B 선언 revision을 고정한다.
나머지 키는 기존 fit_policy의 구조와 타입을 따른다.
심층은 기존 AnalysisPolicyVersion에 analysis-policy-luna-demo-v1(DEMO-00 v4 기반)을 import하고 demo 설정 ID로 선택한다.
CLI `import-company-fit-policy --policy <file> --actor <name>`는 {policy_version_id:UUID?,sha256:hash?,created:bool,errors:string[]}를 반환한다.
같은 canonical hash 재등록은 기존 ID, 새 hash는 새 row. exit0/2/1·stdout 규칙은 §8과 같고 import는 활성화하지 않는다.
모든 새 policy는 reference 전용이며 기존 운영 policy 활성화/gate를 변경하지 않는다.
CompanyAnalysisInput.policy_version_id/sha256는 purpose별 해당 테이블의 identity다. DB는 purpose에 따라 정확한 FK 열을 사용한다.
model_revision은 Luna처럼 선언 revision이 없으면 null이며 추정하지 않는다.

#### 회사 핏 enqueue CLI

`python -m app.deep_review.cli enqueue-company-fit --company-id <uuid> --notice-id <int> --actor <name> [--dry-run]`
→ {company_id:UUID?,notice_id:int?,attempt_id:UUID?,input_sha256:hash?,created:bool,errors:string[]}.
analysis-worker 이미지와 worker DB 역할로 실행한다(기존 핏 attempt INSERT는 worker 전용 권한이며 app 역할에 열지 않는다).
한 번에 attempt 1개를 queued로 만든다. 입력 CompanyAnalysisInput(purpose=company_fit)은 이 transaction에서 만들어 attempt에 동결하며,
execution_nonce=attempt id이므로 같은 자료의 재실행도 새 input_sha256이 된다(기존 input_sha256 UNIQUE 유지). target_review_id/bundle_id=null.
dry-run은 쓰기 없이 gate와 입력 생성만 검사하고 ID·hash는 null이다. exit0/2/1·stdout/stderr 규칙은 §8과 같다.
gate 오류 code는 company_not_found|company_profile_not_ready|company_input_invalid|analysis_policy_unavailable|model_binding_invalid|
overview_not_completed|effective_grade_ineligible(SW사업대상≠Y)|company_fit_disabled|active_attempt_exists(같은 회사·공고에 queued/running 존재)다.
claim은 기존 공용 슬롯·lease·실패 종결 규칙을 그대로 쓴다. 기존 runner의 claim은 company_id 유무로 입력 구성기를 분기하며,
기존 자동 enqueue(`_enqueue_one`)는 company_id IS NULL 행만 만든다. 자동 resume·재호출은 없다.

#### 심층 preview·승인 (기존 Luna 재사용)

DeepReviewPreview·DeepReviewApproval·DeepReview·attempt는 기존 테이블에 company_id를 더해 쓴다(§8). 새 preview/request/approval/receipt 테이블은 없다.
회사 preview의 input은 CompanyAnalysisInput(purpose=deep_review)이며 execution_nonce=preview id, bundle_id 필수,
승인 때 기존 `check()`가 입력을 다시 만들 때는 저장된 preview id를 nonce로 그대로 쓴다(새 nonce로 만들면 항상 preview_changed가 된다),
재시도일 때만 target_review_id=기존 review UUID다. 같은 source의 새 preview라도 nonce가 달라 새 input hash가 된다.
승인·생성·감사·enqueue는 기존 Luna service와 같은 transaction 규칙이며 worker의 approval_invalid 검사는 회사 preview에도 그대로 적용한다.
심층 생성에서 동일 company/notice/bundle/profile/graph/policy lineage의 review가 이미 있으면 409 review_exists,
preview 미소비. 재실행은 target_review_id가 고정된 새 preview와 /attempts를 사용한다.
활성 attempt가 있으면 409 active_attempt_exists. 같은 request_id replay는 이 상태 검사보다 먼저 처리한다.

경로 검색은 requirement id 오름차순, relation direct→partial→unmapped, hop 수→node ID tuple→edge ID tuple 순이다.
같은 (requirement_id,node_ids,edge_ids)를 dedupe한다. 요구당 상한 32경로(tunable)이며 두 목적 정책 모두 chunking.path_limit_per_requirement에 저장한다.
이 양의 정수 키는 canonical policy SHA-256에 포함한다. 현재 핏 chunking 검사(`model_client.py`)는 허용 목록 없이 추가 키를 무시하므로,
두 demo 정책의 loader가 이 키의 존재·양의 정수 여부를 직접 검사한다.
초과 경로는 결정적으로 제한하며
초과분은 정렬 뒤 자르고 coverage.excluded_path_count_by_requirement에 {requirement_id,count} 배열로 기록한다.
coverage에 이 필드는 필수다. included_requirement_ids는 전체 requirements id 집합,
unmapped_requirement_ids는 그 중 concept/회사 연결을 찾지 못한 부분집합이다. 서로 배타 partition이 아니다.
excluded_fact_keys는 예산으로 못 실은 사실만이며 미검색 사실을 부적합으로 해석하지 않는다.
graph_path_indexes는 frozen input.graph_paths의 0-based index, 중복/범위 밖/타 requirement 참조는 검증 실패다.
slice에는 global_path_index와 해당 경로/노드/관계를 함께 전달해 재정렬하지 않는다.
각 source_unit은 최소 한 slice에 포함되고 합병은 unit ID의 합집합·중복 없이 coverage를 검사한다.
누락이 있으면 completed 보고서를 만들지 않는다. 전체 입력은 승인(심층)·enqueue(핏) 전에 생성·동결하며 worker가 새 source를 추가하지 않는다.

ReportView는 schemas/reports.py의 {deep_review_id,current_revision_id,report,validation,history,final_opinion}을 그대로 유지한다.
report는 schema=bidops.deep-review-report.v2인 NarrativeReport다. 새 wrapper의 view가 이것을 담고 UI reader에는 view를 전달한다.
CompanyFitView 기반 필드는 schemas/company_fit.py의 id,notice_id,status,result,error_code,is_current,overview_kind,
overview_id,document_version_id,overview_sha256,profile_version_id,profile_sha256,policy_digest,model_name,model_revision,
prompt_version,quality_status,notice_facts,company_facts,created_at,completed_at,prompt_tokens,output_tokens,latency_ms다.
명시적으로 열거한 새 fields만 추가하며 schema/nullable은 기존 DTO를 따른다.

### 오류와 gate

공통 422(validation)·404(not_found)·409(idempotency_conflict/version_conflict/preview_changed/preview_used)·500(processing_failed)를 유지한다.
회사 경로는 DEMO_ENABLED=false→404다. REFERENCE_WORKFLOW_MODE=false→503 reference_mode_required는
새 심층 실행의 preview/create/retry에만 적용한다. GET 목록/상세/비교/report는 이 flag와 무관하게 과거 결과 조회를 허용한다.
심층 preview/create/retry는 LUNA_DEEP_REVIEW_ENABLED=true 필요(아니면 503 luna_disabled)다. 기존 NULL 계보 Luna 경로의 service_unavailable 응답은 바꾸지 않는다.
회사 binding 부재 409 company_profile_not_ready, hash/소속 불일치 409 company_input_invalid,
policy 설정/등록 부재 503 analysis_policy_unavailable, model 설정 오류 503 model_binding_invalid,
개요 미완료 409 overview_not_completed, SW사업대상≠Y 403 effective_grade_ineligible을 사용한다.
회사 경로의 effective_grade_ineligible은 SW사업대상만 보는 판정이며 기존 effective_grade 함수(우선 검토 포함)를 재사용하지 않는다.
심층 추가: bundle ready 아님 409 bundle_not_ready, 동일 review 생성 409 review_exists, 활성 attempt 재시도 409 active_attempt_exists.
ID가 타회사 소속이면 404 not_found다. 핏 gate 오류는 REST가 아니라 enqueue CLI의 errors로 보고한다.
조회는 입력 준비 오류 때문에 과거 결과를 숨기지 않는다. 결과가 없는 report는 기존 409 review_not_ready를 사용한다.
이 목록 외 안정 error code가 필요하면 공통 계약과 해당 DTO 테스트를 함께 변경하며 오류 message로 분기하지 않는다.


## 10. 격리 환경·도구·실제 인수 계약

Compose 명령의 파일 순서는 docker-compose.yml → docker-compose.edge.yml → docker-compose.model-egress.yml
→ docker-compose.prespec-attachment.yml → docker-compose.luna.yml → docker-compose.demo.yml이다.
COMPOSE_PROJECT_NAME=bidops-demo, --profile prespec --profile luna, --env-file env/demo.env를 사용한다.
BIDOPS_WEB_BIND_HOST=127.0.0.1, BIDOPS_WEB_PORT=28787(default, tunable)이며 점유돼 있으면 실패하고 운영 포트를 재사용하지 않는다.
DB/MinIO는 host publish하지 않고 프로젝트별 volume을 사용한다. 운영 경로 bind mount를 demo overlay에서 제거/교체한다.
교체는 Compose v2.24+ `!override`로 web·analysis-worker의 volumes를 다시 선언한다(설치 버전 v5.1.2, 저장소는 `!reset` 사용 전례가 있다).
전체 렌더 config에서 기존 회사 프로필 read-only mount와 운영 pipeline mount도 남아 있지 않음을 검사한다.
가상회사·온톨로지 원본은 이미지에 넣지 않고(Dockerfile은 docs를 복사하지 않는다) 일회성 CLI 컨테이너에
`docs/demo-fixtures`를 `/run/demo-fixtures`로 read-only 마운트해 넘긴다. 상주 서비스에는 마운트하지 않는다.
env/demo.env는 Git 밖에서 사람이 제공한다. BIDOPS_CODEX_AUTH_FILE은 운영과 같은 계정의 인증 파일을 지정한다(2026-10-06 사용자 결정).
같은 인증을 쓰므로 데모 Luna 실행은 운영 Luna 실행과 겹치지 않게 순차로 하고, 데모 실행 시각과 review ID를 증거에 남긴다.
codex-runner만 secret mount를 받는다. MinIO/DB secret은 데모용이며 값은 문서/로그에 넣지 않는다.
사설 모델은 운영과 같은 qwen3.8-27B이고 엔드포인트는 사용자가 따로 제공한다. 엔드포인트가 env/demo.env에 들어오기 전에는
preflight가 model_endpoint_missing으로 blocked를 보고하며 개요·핏을 실행하지 않는다. 선언 revision은 운영 값과 같아야 한다.
BIDOPS_DEMO_ENABLED=true, REFERENCE_WORKFLOW_MODE=true, 두 purpose의 demo policy IDs를 별도 명시하고
DEEP_REVIEW_AUTO_START_ENABLED=false·scheduler/always-on/C-2 daily trigger=false를 실제 컨테이너 설정으로 확인한다.
문서 준비 자동화가 manifest 6건에 걸리도록 BIDOPS_PRESPEC_OVERVIEW_ENABLED=true(SW사업대상=Y 자동 준비·개요 자동 enqueue의 전제),
BIDOPS_G2B_ATTACHMENT_ENABLED=true와 G2B 허용 host를 둔다. 적재가 6건뿐이므로 자동 첨부 취득·개요 호출도 6건(재시도 별도)에만 걸린다.
Luna/회사 핏 enable과 policy ID 주입은 별도의 명시적 단계다. prepare가 이를 활성화하지 않는다.
실제 원문·manifest·인수 기록이 들어가는 `data/demo/`는 `.gitignore`에 추가한다. Git 대상은 schema와 순수 합성 원본(`docs/demo-fixtures`)뿐이다.

`./scripts/prepare-company-demo.sh --stage preflight|storage|migrate|companies|notices --env-file env/demo.env [--apply]`
- default stage=preflight, default dry-run. cwd와 무관하게 script 위치에서 repo root를 찾는다.
- preflight: 파일/secret 존재·프로젝트/포트·config/승인 경계 검사만 한다. --apply여도 쓰기 없음.
- storage: 이번 project에 한해 기존 객체 초기화 도구로 버전 저장소·최소 권한 준비. migration/모델 호출 없음.
- migrate: 기존 Alembic으로 demo DB만 변경. 사전 preflight와 작업 직전 사람 확인/빈 DB 또는 백업 증거 필요.
- companies: 사용자 승인 기록이 있는 3개 고정 합성회사 import만 한다. 활성화·정책 등록·공고 적재·모델 실행은 하지 않는다.
- notices: manifest 후보 6건만 담은 데모 전용 회차 디렉터리를 원 수집 회차에서 파생해 데모 volume에 만들고 기존 ingest CLI로 적재한다.
  원 회차 디렉터리는 수정하지 않는다. 적재 뒤 `GET /api/runs/<회차>/warnings`가 0건이어야 completed이며, 경고가 있으면 blocked다.
  적재가 첨부 취득·문서 준비·개요를 자동으로 시작하므로 엔드포인트가 없으면 preflight와 같은 이유로 blocked다.
- 각 --apply는 그 stage 하나만 수행한다. 기존 도구의 멱등성을 유지하며 사용자 소유 자원을 삭제하지 않는다.
stdout={schema_version:"bidops.demo-prepare.v1",stage:enum,mode:dry_run|apply,project:"bidops-demo",
status:ready|completed|blocked|failed,checks:[{code:string,passed:bool}],errors:string[]}.
exit0=ready/completed, exit2=입력/준비 차단, exit1=실행 실패. stderr는 안전 code만, argparse 문법 오류는 exit2.
새 stack 시작/교체는 별도 승인된 compose up, 정책 import/ID 설정, 회사 activate, 공개 원본 적재도 기존 명시 CLI 단계다.
이 작업 순서와 정확한 project/env/file 조합을 operations에 기록하고 단계별 증거를 남긴다.

`python3 scripts/verify-company-demo.py --manifest <file> --base-url <url> --acceptance-dir <directory>`는
repo root에서 실행한다. 호출은 GET만 사용한다. --acceptance-dir 생략 시 기술 상태만 검사하고 overall=pending_human이다.
선택 단위는 (company_id,notice_id,purpose) 27개 셀이다. 같은 입력의 재시도 횟수는 셀 수를 늘리지 않는다.
각 셀은 §6 최신 생성 실행을 사용하고 그 review의 최신 attempt를 검사한다.
manifest의 profile/graph/ontology/documents/overview/policy/model/generation을 FrozenProvenance로 대조한다.
company_fit은 bundle_id=null이어야 하고 deep_review만 manifest.bundle_id와 일치해야 한다.
핏은 completed·non-null valid v2 result, 심층은 completed 3단계·현재 completed report·필수 검증 통과가 필요하다.
과거 completed·stale·검증 off·mock은 카운트하지 않는다. 각 성공은 unmeasured_reference로 표시한다.
결과={schema_version:"bidops.demo-verification.v1",manifest_sha256:hash,
expected:{fit:18,report:9},actual:{fit:int,report:int},technical_status:pass|fail,
human_status:pass|pending|fail,overall:pass|fail|pending_human,demo_ready:bool,
cells:[{company_id:UUID,notice_id:int,purpose:company_fit|deep_review,review_id:UUID?,
attempt_id:UUID?,report_revision_id:UUID?,status:pass|fail,errors:VerificationCode[]}]}.
VerificationCode=missing|not_completed|input_mismatch|stale|validation_failed|mock_reference|quality_marker_missing|api_unavailable|human_rejected|human_pending.
review_id는 deep_review 셀에서 공개 CompanyReviewView.id이며 fit에서는 null이다. attempt_id는 fit의 CompanyFitView.id 또는 심층 최신 AttemptView.id다. 아직 없으면 null이며 내부 request ID를 추측하지 않는다.
demo_ready는 핏 18셀 pass와 first_deep_review_notice_id의 deep_review 3셀 pass(인수 accepted=true 포함)일 때만 true다.
demo_ready=true여도 overall은 위 규칙대로 계산하며 exit code는 overall만 따른다.
JSON key는 항상 존재한다. 읽기/manifest 오류 exit2, 기술/사람 fail exit1, pending_human exit3, 전체 pass만 exit0이다.

사람 인수 정본은 data/demo/acceptance/{manifest_sha256}/{review_id}/{revision:04d}.json이다.
외부 승인/인수 CLI가 append-only O_EXCL로 새 revision만 생성하며 기존 파일을 고치지 않는다.
`python3 scripts/record-company-demo-acceptance.py --manifest <file> --record <file> --output-root data/demo/acceptance`
는 아래 strict 입력을 검사하고 다음 revision 파일을 배타 생성한다. API/model 호출 없이 로컬 인수 기록만 쓴다.
stdout={path:string,revision:int,sha256:hash}, exit0 성공·exit2 유효성/동시 생성 충돌·exit1 IO 실패다.
인수 입력={schema_version:"bidops.demo-human-acceptance.v1",manifest_sha256:hash,review_id:UUID,
report_revision_id:UUID,company_id:UUID,notice_id:int,actor:string,checked_at:timestamp,
checks:{scope:Check,company_evidence:Check,gaps:Check,unknowns:Check,next_actions:Check},accepted:bool,notes:string}.
Check={result:pass|fail|not_applicable,reason:string}; not_applicable/fail은 reason 필수, 나머지는 빈 문자열 허용.
accepted=true는 모든 check가 pass 또는 사유 있는 not_applicable일 때만 허용한다.
verifier는 현재 manifest/review/report_revision에 맞는 가장 큰 인수 revision을 사용하고 없으면 pending이다.
전체 완료는 기술 18/9와 심층보고서 9건 전부 accepted=true. accepted=false가 있으면 fail이다.
인수 담당자(actor)는 사용자 본인이다(2026-10-06 결정).
후속 인수에서 수정할 수 있으나 과거 불합격 기록은 남긴다.

실제 UI 인수는 첫 대표 opportunity에서 3사 각각 한 번의 tracking 저장·새로고침·상호 독립 확인을 포함한다.
저장할 상태와 사유는 담당자가 정한다. 세 회사에 같은 상태를 골라도 서버 저장 소속이 다름을 확인한다.
스크린샷은 loaded report/evidence/비교/결정 완료를 기다려 1280×800·1440×900에서 수집한다.
새 live Playwright config는 BIDOPS_DEMO_BASE_URL이 필수이고 webServer·mock route·fallback이 없다.
실제 분석 요청은 승인된 담당자 조작으로 수행하고 live spec은 준비된 결과 조회와 명시한 tracking 시연만 한다.
인수 파일의 9건 체크는 별도 담당자 기록이며 화면 캡처가 이를 대신하지 않는다.

### 조회용 동결 계보

FrozenProvenance={input_sha256:hash,purpose:company_fit|deep_review,company_id:UUID,
profile_version_id:UUID,profile_sha256:hash,graph_version_id:UUID,graph_sha256:hash,
ontology_version:string,ontology_sha256:hash,documents:[{document_version_id:UUID,source_sha256:hash}],
overview_run_id:UUID,overview_sha256:hash,bundle_id:UUID?,policy_version_id:UUID,policy_sha256:hash,
model_name:string,model_revision:string?,generation_config_sha256:hash}.
CompanyFitView와 CompanyReviewView에 provenance:FrozenProvenance를 필수 추가한다.
동결한 CompanyAnalysisInput/원본 버전 identity로 저장·조회하며 현재 설정으로 재구성하지 않는다.
documents는 document_version_id 순이며 모델 원문/secret/payload는 노출하지 않는다.
DEMO-03이 저장/GET을 구현하고 DEMO-04가 DTO를 소비하며 DEMO-05 verifier가 비교한다.
FrozenProvenance는 동결 transaction(핏은 enqueue, 심층은 preview)에서 문서 ID/hash를 immutable DocumentVersion에서 읽어 정렬한 뒤
전체 객체를 별도 불변 JSON snapshot으로 저장한다(핏은 attempt, 심층은 DeepReviewPreview). input_sha256은 동결한 CompanyAnalysisInput의 hash다.
심층은 승인 시 현재성과 hash를 검증하고 해당 snapshot을 attempt의 승인 preview와 결속한다.
replay 응답과 이후 GET은 동일 snapshot을 직렬화하며 문서 목록/hash를 조회 시점에 재조립하지 않는다.
CompanyFitView는 그 view.id인 fit attempt의 동결 snapshot이 원천이다. queued attempt에도 snapshot이 있다.
CompanyReviewView는 current_attempt.id의 승인 preview가 원천이다. 회사 review 생성은 최초 attempt 생성과 원자적이므로
회사 view의 current_attempt는 항상 non-null이며 재시도 생성 시 새 sequence의 attempt로 원자적으로 바뀐다.
과거 request_id replay는 기존 Luna replay 규칙대로 그 요청이 만든 attempt의 snapshot/응답을 그대로 반환하고 최신 GET으로 바꾸지 않는다.
verifier의 심층 attempt_id는 GET current_attempt.id와 같아야 한다. 현재 보고서도 그 attempt의 결과여야 하며
과거 완료 보고서를 새 queued/failed attempt의 성공으로 합산하지 않는다.
view와 provenance에 중복된 모든 identity/hash 필드는 같아야 한다(company_id,profile_version_id,profile_sha256,
graph_version_id,graph_sha256,ontology_version,input_sha256 및 양쪽에 존재하는 기타 동일 이름 필드).
서버 serializer/DTO 검증과 T6/T7이 이 불변식을 강제한다. 불일치하면 정상 응답으로 보정하지 않고 processing_failed로 거부한다.


live config의 tracking mutation은 demo-laptop project에서만 실행하고 demo-desktop은 read-only 구조·캡처만 수행한다.
테스트는 project.name으로 mutation case를 명시 skip하고, 두 project를 직렬로 실행하여 laptop 저장 뒤 desktop이 확인한다.
두 폭에서 반복 저장하여 사람 결정을 추가하지 않는다.
