# HP-03 — spec

근거: intent.md, HP 공통 계약 §0·2·3·6·7, HP02 spec. 이 명세의 신규 schema는 구현 목표이며 현재 제품 계약과 구별한다.

## 동결 입력과 unit

기존 company_deep_review preview/approval/claim·FrozenProvenance 전체를 유지하고 새 policy `analysis-policy-hp-v1`에서만 HP 파이프라인을 선택한다. model=gpt-6-luna, effort=high, reference 표식과 runner identity는 HP00 그대로다. 입력 추가분: schema_version="bidops.hp-analysis-input.v1", company_sha256(HP02 basis bytes), scenario_sha256, registration_sha256, ontology_sha256, units[], batches[], missing_sections[]. 모두 필수이며 기존 provenance와 SHA 불일치 시 호출 전 실패한다. 회사 v2 sidecar의 승인 사실·범위/제외/절차도 입력에 동결하고 preview에 전송 범위를 표시한다.

unit={unit_id,source_sha256,document_version_id,structure_id,manifest_id,kind,ordinal,normalized_id,section_kinds,blocks,page_range,mapping_status}. UUID 3개는 기존 row ID, ordinal은 저장 순서의 비음수 정수, kind=card|segment, normalized_id는 card만 문자열/segment는 null. card ID=`card:<source_sha256>:<ordinal>:<normalized_id>`, segment ID=`segment:<source_sha256>:<segment_id UUID>`. 같은 hash 문서 버전 둘을 묶으면 source를1회만 선택하고 둘의 version binding은 보존한다. ID 중복은 실패하며 같은 normalized_id의 서로 다른 표는 삭제하지 않는다. blocks={block_key,text}[]는 해당 단위에 속하는 저장 구조 원문, 쪽/매핑은 HP01 계약 그대로다.

비카드 section_kinds enum=overview|schedule|budget|eligibility|evaluation|contract. 저장 구조 heading에 기존 heading 정규화 후 공백 제거, 아래 부분문자열이 있으면 해당 section으로 선택한다. 동일 heading의 후속 본문은 다음 동급/상위 heading 전까지, 기존 segment와 교집합을 취한다. 카드 소유 block/표·목차 block은 제외한다. segment에 해당 부분만 있으면 그 block 집합만 넣고 여러 범주일 때 하나의 segment unit에 범주를 중복 없이 enum 순으로 저장한다. heading 근거 없는 본문 키워드만으로 선택하지 않는다.

| section | heading 키워드 |
|---|---|
| overview | 사업개요, 과업개요, 사업목적, 추진배경 |
| schedule | 추진일정, 사업기간, 수행기간 |
| budget | 사업예산, 사업비, 소요예산, 추정가격 |
| eligibility | 입찰참가자격, 참가자격, 입찰자격 |
| evaluation | 평가기준, 평가방법, 제안서평가, 배점 |
| contract | 계약조건, 계약사항, 계약일반, 계약특수, 대금지급, 지체상금, 지식재산권 |

선택되지 않은 범주는 missing_sections로 preview/결과에 표시한다. 원문에 없다고 단정하지 않는다. 전체 후보·선택 block ID와 selector version/hash를 frozen input에 보존한다. 6범주 중 누락이 있으면 부분 분석을 허용하지만 최종 성공 발행은 막고 사람 검토 상태로 둔다.

## 단계 wire 계약

모든 객체는 아래 키 필수, 추가 키 금지, JSON number의 bool 혼용 금지. 문자열은 비어 있지 않음(배열은 빈 값 허용). hash는 lowercase64hex. `Fit=met|gap|unknown`, `Type=자격|실적|인력|기술|기능|성능SLA|보안|운영|계약|평가`.

`Evidence={source_sha256,block_key,quote}`: 선택 unit의 정확한 block에서 quote가 부분문자열이어야 한다. 임의 공백 교정·다른 block 인용 금지. ID는 같은 attempt 안에서만 참조한다.

1층 schema_version="bidops.requirement-extract.v1", items=Extract[]만 반환한다. Extract={unit_id,type,normalized_requirement,mandatory,constraints,concept_candidates,unknowns,evidence}. mandatory=boolean|null. concept_candidates={concept_id:string|null,alias_text:string}[], unknowns=string[], evidence=Evidence[] (최소1). constraints={kind,value,unit,operator,fact_key,quote,locator}[]; kind=amount|duration|count|date|percentage|boolean|text, operator=eq|gte|lte|unknown, fact_key=HP02 retained_facts의 id|null, locator={source_sha256,block_key}. value는 amount/duration/count/percentage에 유한 number, date에 YYYY-MM-DD, boolean에 bool, text에 string. unit=KRW|person|month|day|year|percent|null. 의미가 모호하면 operator=unknown,fact_key=null로 보존한다. 하나의 constraint는 원문 한 조건이며 복합 문장은 분리한다. 각 batch의 unit ID 집합은 입력과 정확히1회 일치해야 한다.

검증기는 source quote·숫자·단위·operator의 원문 표현(이상/이하/동일)을 검사하고 의미가 불명확한 비교는 unknown만 허용한다. KRW의 원/천원/백만원/억원 정확 환산, 비율 %만 허용한다. 월↔일, 연↔일 변환·상대 날짜 계산은 하지 않는다. 시간 단위 불명/종료일 포함 범위는 unknown이다. concept ID는 동결 ontology에 속하고 alias_text가 원문에 있으며 match_concepts가 같은 concept를 반환해야 한다. 임의 semantic mapping은 unknown으로 남긴다.

코드 대조 schema_version="bidops.requirement-compare.v1", items=Compare[].
Compare={unit_id,fit_status,constraint_results,evidence_ids,reason_codes}; constraint_results={constraint_index,status,fact_ids,path_ids,reason_code}[], evidence_ids는 회사 근거 UUID[], path_ids는 동결 retrieval 경로의 순서 index 정수[], fact_ids는 retained fact id 또는 graph node ID[]. reason_code/reason_codes enum=confirmed_match|confirmed_contradiction|unknown_fact|partial_path|unmapped|unsupported_comparison|scope_unverified|contract_unaccepted|incomplete_unit.

- 단어 매칭·경로 발견은 충족 증거 그 자체가 아니다. 모든 원자 조건과 명시 기능 범위가 confirmed·direct 근거로 충족되고 누락/unknown이 없어야 met. 하나라도 confirmed 반대 사실이면 gap, 나머지는 unknown. 부분 충족을 전체 met로 올리지 않는다. conflicting confirmed 사실은 unknown으로 보내고 reason=scope_unverified.
- fact_key는 수치/자격의 의미 일치 allowlist만 사용: 인원총수→headcount, 연매출→annual_revenue, 홈페이지실적건수→homepage_project_count, 최대단일실적금액→largest_homepage_project_amount, 상주인원→onsite_available_people, ISMS→isms_held, 다국어실적→multilingual_homepage_project_experience, Oracle경험→oracle_experience, 직접생산확인→direct_production_valid_scope, 24시간대응→around_clock_response. 원문에 의미 anchor가 없으면 연결 거부/unknown. 나머지 retained facts는 기능 범위 설명 근거로만 쓴다. 최근3년·회계연도·자격 유효기간 등 추가 조건이 있으면 날짜 미지정 때문에 전체 충족을 보장하지 않는다.
- 상주3명 요구 vs 최대2명은 gap. 2명이하라도 특정 역할/현재 가용 기준일 요구가 있으면 unknown. 총18명을 상주18명으로 쓰지 않는다. ISMS-P를 ISMS와 혼동하지 않는다. 다국어 실적 false는 역량 false가 아니다. 프로젝트 supports_capability partial 경로만 있으면 unknown; HP02의 승인된 직접 기능 범위를 함께 대조한다.
- 표준절차는 절차 보유만 지지한다. 손해배상/무상기간/추가비용/기한·부수/권리귀속/상주설비/SLA 수용은 별도 사람 입력이 없으므로 unknown이다. 문장 동등성을 결정적으로 증명할 수 없으면 unknown 유지.

역할 schema_version="bidops.verdict-role.v1", role,unit_findings,cautions,evidence_refs 필수. role=eligibility_economics|technical_fit|operations_risk. unit_findings={unit_id,assessment:Fit,reason,evidence_refs:Evidence[]}[], cautions={unit_id,text,evidence_refs:Evidence[]}[], evidence_refs=Evidence[]. eligibility_economics에는 자격/실적/인력/계약/평가, technical_fit에는 기술/기능/성능SLA/보안, operations_risk에는 인력/성능SLA/보안/운영/계약을 전달한다. 소속 unit 전체를 정확히1회 반환한다. 역할은 frozen Compare를 입력으로 받지만 수정하지 못한다. 역할별 판단 차이는 코드가 `{unit_id,roles:[role...],assessments:[Fit...]}`로 conflicts를 계산해 보존한다.

종합 모델 schema_version="bidops.practitioner-verdict.v1", verdict,reason,blocking_condition_ids,cautions,next_actions 필수. verdict=진행 가능|조건부 진행|진행 어려움|판단 불가. blocking_condition_ids는 gap이면서 mandatory=true인 unit ID의 부분집합(누락은 caution); caution은 역할과 같은 구조; next_actions={unit_id,owner:string|null,action,evidence_refs:Evidence[]}[]. owner는 입력에 없는 사람 이름을 만들지 않는다. 종합 입력은 역할3결과만 받는다. 출력 ID/근거는 역할에 존재해야 하며 compare를 덮지 않는다. 체크리스트/매트릭스/conflicts는 코드가 원본 Compare·role로 조립한다. mandatory gap을 진행 가능으로 종합하면 validation 실패; 미해결 조건이 있는데 무조건 진행 가능으로 출력해도 실패한다. 판정은 최종 Go/No-Go가 아니다.

## 설정·상태·저장

새 불변 policy 키: batch_size=8(1..8), batch_max_chars=12000(1..12000), repair_attempts=1(0..1)는 tunable. source 순서 고정 greedy packing, 원문 Unicode 문자수 합계로 상한 계산. 단일 unit 초과 시 자르지 않고 preview 409 input_budget_exceeded. 실제 prompt/context 상한도 기존 runner 검사로 이중 차단한다. 정상 호출은 B+4, schema syntax repair가 있는 최악은 2*(B+4); 근거·숫자 오류는 repair하지 않는다. repair도 같은 전체 3600초 예산·승인 payload 안에서만 가능하다.

review_timeout_seconds=3600, target_seconds=2400은 사용자 확정. claim 이후 단조 시계로 측정(대기시간 제외), 잔여시간을 각 호출 timeout에 적용한다. 강제 종료 뒤 새 호출·늦은 응답 저장 금지. mock과 실제 모델 결과를 구분한다.

기존 attempt status=queued|running|completed|failed|superseded, review status=queued|running|completed|failed를 바꾸지 않는다. 검증 실패/timeout은 failed + 안전 error_code, 조회용 availability만 needs_human_review로 투영한다. 재시도는 기존 경로의 새 attempt이며 자동 재개 없음.

새 `hp_analysis_stage` 테이블: id UUID PK, attempt_id FK 기존 attempt, stage extract|compare|role|synthesis, stage_key TEXT(batch ordinal 십진문자열/role명/final), input_sha256/result_sha256 CHAR64, payload JSONB, created_at timestamptz; UNIQUE(attempt_id,stage,stage_key). 검증 완료된 결과만 insert하며 UPDATE/DELETE 권한 없음, compare key는 extract batch key와 동일. 실패 원문은 기존 암호화 객체 저장소·안전 오류로 처리한다. HP stage row는 기존 narrative StageName을 확장해 억지 노출하지 않는다. migration은 당시 단일 head 후속, grants·ALEMBIC_HEAD·schema·runner contract 동시 변경. 기존 보고서 row 불변.

신규 error_code=input_budget_exceeded|hp_source_selection_incomplete|hp_extract_invalid|hp_compare_invalid|hp_role_invalid|hp_synthesis_invalid|hp_review_timeout. 기존 binding/소유권/서비스 오류는 기존 code를 유지한다. raw prompt·회사원문·경로는 오류/로그에 넣지 않는다.

## 테스트 케이스

| ID | 입력 | 기대 결과 |
|---|---|---|
| T1 | 문서/표 중복 ID·카드/목차·6heading·누락범주 | unit 고유, block 중복배제, 선택근거 동결·누락 표시 |
| T2 | 8장/12000 경계·한장초과·repair | 결정적 batch, 초과 호출0, 호출 상한 준수 |
| T3 | 외부block/숫자/alias/ID중복·누락 | stage 거부·자동교정 없음 |
| T4 | 2억원=200백만원·2/3명·unknown/false·scope/계약 | 정확한 비교만 허용, 부분전체승격 금지 |
| T5 | 역할 overlap·충돌·mandatory gap 종합 | 입력 allowlist, 충돌 보존, 허위 진행가능 거부 |
| T6 | PostgreSQL 새 DB·중복 insert·권한·기존버전 | migration/head 일치·append-only·legacy 보존 |
| T7 | preview 뒤 회사/정책/문서 변경·중복claim·다른회사 | 호출 전 fence·404/409·슬롯1 |
| T8 | 2400/3600초·종료 후 늦은 응답·재시도 | 목표시간과 실패 구분·부분보존·새attempt |
| T9 | mock 전체와 실패·실제 동결 대표1건 | mock은 연결만; 실제는 단계·근거·시간 증거, 실패는 완료 불가 |

실제 모델 smoke는 별도 전송 binding 승인 경계다. 독립 gold 표본의 미노출을 침해하지 않도록 이미 노출된 폴리텍을 대표 smoke로 사용한다. 승인 범위 밖 호출은 pending으로 남긴다.

## 승인 wire와 호환 경계 (독립 리뷰 보완)

HP는 기존 flat CompanyAnalysisInput을 **새 버전 v2로 확장**한다. legacy v1은 변경하지 않는다. v2의 최상위 키는 다음 목록 전부이며 추가 키 금지다:

```
schema_version, purpose, execution_nonce, target_review_id, company_id,
profile_version_id, profile_sha256, graph_version_id, graph_sha256,
ontology_version, ontology_sha256, notice_id, document_version_ids, bundle_id,
overview_run_id, overview_sha256, policy_version_id, policy_sha256,
model_name, model_revision, generation_config_sha256,
requirements, profile_facts, profile_evidence, graph_nodes, graph_edges,
graph_paths, coverage, hp_analysis
```

schema_version="bidops.company-analysis-input.v2", purpose="deep_review". hp_analysis 외 나머지 필드 타입/nullable/정렬은 기존 `COMPANY_ANALYSIS_INPUT_KEYS` 및 DEMO §5 그대로이고 requirements의 id는 이번 frozen unit_id다. model_revision=null 허용은 기존 정책 규칙 그대로다. profile/graph retrieval은 기존 함수로 같은 동결 회사에서 생성하며 unit 요구사항과 path index를 연결한다. 준비 단계 retrieval은 원문 결정적 concept로 만들고, 1층 추출의 concept는 그 집합/원문 매핑과 일치해야 한다.

hp_analysis는 이 문서 앞의 추가 입력을 다음 **완전한 키 집합**으로 중첩한다: {schema_version:"bidops.hp-analysis-input.v1",company_sha256,scenario_sha256,registration_sha256,ontology_sha256,units,batches,missing_sections,selector,company_basis}. batches={batch_index:nonnegative int,unit_ids:string[],source_characters:nonnegative int}[], index는0부터 연속, 순서/ID coverage는 정확히1회. selector={version:"hp-sections-v1",sha256:Hash,candidate_blocks:[{source_sha256,block_key}],selected_blocks:[{source_sha256,block_key,section_kinds}]}; 두 배열은 source hash/원문 순서, 중복 없음. selector SHA는 이 spec의 범주/키워드·heading/제외 규칙을 구현한 canonical 정책 객체의 SHA다.

company_basis={retained_facts,projects,current_conditions,standard_procedures}: 승인 v2 파일의 동명 필드를 복사하되 projects에서 reference_tender와 actual_completion_evidence는 전송하지 않는다. 나머지 project 키/값 및 배열 순서는 승인 원본 그대로다. source_refs의 source_id=self JSON pointer는 로컬 검증용으로만 쓰고 payload에서는 retained_facts의 source_refs를 제외한다. basis/source SHA는 원본 파일 hash이며 이 전송 projection의 SHA와 혼동하지 않는다. 이 필드들의 정확 키/타입은 동결 승인 JSON에서 파생한 strict schema로 고정한다. 모델에는 기존 profile_evidence와 승인 가상 범위만 제공하며 참고공고를 수행증거로 전달하지 않는다.

Preview 외부 키는 기존 CompanyDeepReviewPreviewView의 정확 집합을 유지한다: preview_id,input_sha256,provider,model,reasoning_effort,quality_status,source_verification_enabled,input,company_id,profile_version_id,graph_version_id,graph_sha256,ontology_version. `input`은 policy pipeline에 따라 v1|v2 discriminated union. 새 HP 정책은 v2만 허용, legacy 정책은 v1만 허용한다. 새 필드를 v1에 슬쩍 넣지 않는다. input_sha256은 **최상위 v2 전체 canonical JSON** SHA, execution_nonce=preview_id. preview 저장·승인·create/claim 재검사는 같은 전체 bytes를 비교한다. 바뀌면 기존 승인을 폐기한다. FrozenProvenance 키/스키마는 그대로이며 그 input_sha256이 전체 v2를 묶는다. provenance의 회사/문서/정책/ontology 값이 flat v2와 일치해야 한다. HP04는 이 provenance와 hp_analysis에서 읽고 계산해 채우지 않는다.

새 policy 파일은 `bidops.analysis-policy.v2`의 현재 전체 키 구조를 유지하고 policy_identity=analysis-policy-hp-v1, pipeline_version=card-v1, stage_schema=bidops.requirement-extract.v1, report_schema=bidops.practitioner-verdict.v1로 고정한다. chunking의 기존 keys는 유지하되 source_characters=12000,max_requirements=8,timeout_seconds=900,path_limit_per_requirement=32; 실제 packing은 추가 hp 설정 {batch_size:8,batch_max_chars:12000,repair_attempts:1,target_seconds:2400}를 사용한다. execution.review_timeout_seconds=3600,validation_repair_attempts=1. hp는 이 policy 버전에서만 추가되는 strict 키다. generation/model/CLI는 HP00 값 유지. stages는 extract, eligibility_economics, technical_fit, operations_risk, synthesis의 순서이며 각 {stage,instruction}, instruction은 본 명세의 해당 입력/출력 계약을 지시한다. prompt_output_contract/output_contract/validation에 narrative-v2의 claim/recommendation/완화 규칙을 재사용하지 않고 HP의 엄격한 단계검사를 넣는다. 정책 canonical bytes/hash를 import 때 고정하고 runtime에서 임의 수정하지 않는다. card-v1에만 별도 parser/dispatch를 두며 legacy StageName과 정책은 유지한다.

runner contract enum에 hp-extract-v1|hp-role-v1|hp-synthesis-v1을 추가해 고정 이미지 schema에만 매핑한다. 요청 임의 경로/schema/model은 허용하지 않는다. client와 runner allowlist·이미지 COPY를 함께 바꾼다. HP 합성/역할 schema는 이 문서의 schema_version으로 검증한다.

T7에 v1/v2 잘못된 policy 조합·hp_analysis 변조·preview nonce/provenance 불일치·runner 임의contract 거부를 포함한다. T6에 runtime privileges 적용 후 worker INSERT/SELECT 허용, UPDATE/DELETE·web INSERT 거부, 단일 head/lifespan을 포함한다.
