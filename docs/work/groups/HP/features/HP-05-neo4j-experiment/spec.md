# HP-05 — spec

근거: intent.md, HP 공통 계약 §10, preparation.md의 두 측정 구분, graph-adoption-criteria.approved.v1.json. 제품 DB를 교체하는 기능이 아니다.

## 입력·출력 계약

회사 v2·ontology·질의·도구 hash를 동결한 중립 export를 새 실험 디렉터리에 만든다. `bidops.hp-graph-export.v1`={schema_version,binding,nodes,edges}; binding=아래 정확한 wire 절의 Binding, 모두64hex. graph_sha256은 nodes/edges canonical bytes의SHA, source_sha256은 source bundle canonical SHA. nodes={id,type,status,concept_id,amount_krw,duration_months,available_people,held}[], edges={id,from_id,to_id,type}[]; 기존 StableKey와 node/relation enum 사용. nullable 수치=nonnegative int|null, held=bool|null, concept_id=string|null. 사실 status=confirmed|inferred|unknown. source_refs·원문·회사 실자료·비밀은 export하지 않는다. unknown 수치는 null, 기간/가용 기준일 없는 값으로 조건을 통과시키지 않는다.

현행 비교는 실제 `company_knowledge_retrieval.search_graph_paths`와 동일 company root·5관계·direct/partial·최대3hop·정렬·path_limit을 사용한다. neutral export 외 실제 retrieval에 필요한 evidence/status/full graph는 격리 입력에 그대로 보존하고 두 엔진에 동일한 node/edge identity·status를 전달한다. 검색 path_limit은 기존 호출자가 동결한 값, excluded count도 기록한다. cap 차이로 recall 이득을 만들지 않는다.

보조 q1..q5는 기존 graph_queries.py와 graph-queries.draft.cypher의 금액·기간/인력/자격AND실적/기술경로/false근거다. PostgreSQL row에서 export한 Python 실행과 Cypher를 비교한다. 이를 SQL 자체의 표현력이나 현재 제품이 지원하는 수치 질의라고 부르지 않는다. source graph의 누락 값은 그대로 null이다. 합성 경계 자료는 검증용으로만 별도 표시한다.

채점 파일 shape는 기존 hp_prepare.py graph-score가 검사하는 형식을 그대로 사용한다. node_ids+edge_ids의 directed ordered path, query ID와 binding exact equality, 중복·foreign path는 오류. 코드의 현재 schema를 복사해 두 번째 구현을 만들지 않는다. 출력은 도구 버전/SHA·두 원시 경로·각 score·사람 평가를 묶은 manifest로 참조한다. 보고서 채택란은 null에서 시작한다.

신규 CLI `scripts/hp-graph-experiment.py export|query|report`를 계획한다. export --input <동결graph> --out <새dir>; query --engine postgres|neo4j --manifest <file> --out <새file>; report --manifest <file> --human-review <file> --out <새file>. 기존 파일 overwrite 금지, 성공0/입력오류2/실행실패1. report는 후보 조건 결과(true|false|null)만 계산하며 adoption을 작성하지 않는다.

## 실제 실행 전후 사람 단계

실행 전에 사람이 원본 그래프에서 query별 expected paths와 required paths를 작성하고 hash를 고정한다. 모델/엔진 결과를 먼저 본 경로는 독립 기대경로로 승격하지 않는다. 미작성 null 또는 분모0은 미측정이며 통과 불가. 의미·입력 동일성 검증 및 어댑터 구현은 기대경로 없이 합성 fixture로 먼저 가능하다.

Neo4j는 exact5.x image+digest를 실험 manifest에 고정한 후 별도 폐기 가능한 internal network/volume에서 실행한다. floating tag 실행 금지, 호스트 port 없음, 운영/bidops-local DB에 실험행 쓰기 없음. 정확 digest 선택은 설치 시 기술 작업이며 준비 단계에서 다운로드/실험하지 않는다. 시작 전 node/edge count·속성·방향·canonical hash 동등성을 검사한다. 실패하면 비교 중지, 양쪽 원시 결과 보존.

고정 기준: micro recall 차이≥0.10 OR 5질의중 neo4j authoring_modification_winner≥3; AND 필수경로손실0 AND explainability_degraded=false. 질의 winner=postgres|neo4j|tie|unassessed, 이유 필수. 미평가·분모0은null. 동일10개 경로 sample에서 source/관계방향/회사사실까지 추적 가능한지 사람이 비교하며 하나라도 악화하면 explainability_degraded=true. 경로10개 미만이면 전부 표시하고 표본 부족으로 후보 판정null, 임의 경로 생성 없음. 최종 채택=adopt|retain|defer|null은 사람이 이유와 함께 기록한다. 비용·AGE는 N/A. 채택해도 제품 연결은 별도 replan이다.

## 테스트 케이스

| ID | 입력 | 기대 결과 |
|---|---|---|
| T1 | duplicate ID·foreign edge·unknown/null·cycle | 입력거부/유한3hop·null 미통과 |
| T2 | 실제 retrieval와 Neo4j 동일fixture | 방향·정렬·cap·excluded 포함 동등성, legacy 경로 보존 |
| T3 | q1..q5 숫자경계·q3중복·q4기술·q5false | 두 엔진 의미 일치, distinct는 adapter에서 명시 |
| T4 | 기대경로미작성·binding mismatch·분모0 | 거부 또는 미측정, 자동채택 없음 |
| T5 | recall0.10·winner3·필수손실1·설명악화 | OR/AND 경계 정확, 미평가false로 보정 금지 |
| T6 | 사람 동결 뒤 실제비교·평가 | 원시결과/hash/명령/종료코드/사람판단 보존 |

실제 T6 및 사람 설명평가 전까지 기능 완료·Neo4j 채택으로 기록하지 않는다. 준비 완료와 실험 완료는 별개다.

## 비교 artifact의 정확한 wire (독립 리뷰 보완)

아래 모든 키는 필수이며 nullable만 null 허용, 추가 키 금지다. Hash=64hex, Path={node_ids:string[],edge_ids:string[]}로 node수=edge수+1, simple directed path1..3hop. node/edge ID는 export에 존재하고 방향과 일치해야 한다. 기존 graph-score의 최소 shape는 유지하고 새 experiment CLI에서 이 엄격한 검증을 앞에 둔다.

- `bidops.hp-graph-requirements.v1`={schema_version,company_sha256,ontology_sha256,selection_sha256,documents}. documents={document_id,sources_sha256,requirements:[{unit_id,concept_ids:string[]}]}[]. selected10사업 전부를 포함하고 concept는 카드/선택 원문에서 match_concepts로 결정적으로 얻는다. 원문은 파일에 넣지 않는다. 미매핑 concept_ids=[] 보존. gold의 답/판정은 읽지 않는다. 공통계약의 gold10은 동일 선정10건의 의미이며 독립 정답 작성과 그래프 질의 입력을 결합하지 않는다.
- `Binding`={company_sha256,ontology_sha256,graph_sha256,source_sha256,parameters_sha256,requirements_sha256,selection_sha256}. export와 아래 모든 binding은 동일 객체다. source_sha256은 document_id 순 정렬한 {document_id,sources_sha256}[] canonical SHA.
- `Expected`={schema_version:"bidops.hp-graph-expected.v1",binding,annotator,authored_at,queries}. queries={id,paths:Path[]|null,required_paths:Path[]|null}[]. 현행 recall query ID는 `recall:<document_id>:<unit_id>:<concept_id>`; 보조 query ID는 q1..q5. required_paths는 paths의 부분집합. path null은 미작성, []는 확인된 없음이다. actor/시각은 사람이 작성할 때 채우며 이전까지 null이다. 실제 query 실행 전에 전부 작성·유효성 확인·hash 동결 필요.
- `Actual`={schema_version:"bidops.hp-graph-actual.v1",binding,engine:postgres|neo4j,queries,tool_sha256,manifest_sha256,exit_code}. queries={id,paths:Path[],excluded_count:nonnegative int}[]이며 ID집합은 Expected와 동일하다. 같은 query를 각 엔진에서 실행한다. node/edge/status 동일성·direction·hop·cap 검사 실패 시 score를 생성하지 않는다. tool_sha256은 CLI와 graph_queries/Cypher 파일별 hash 목록 canonical SHA. exit_code=0만 채점한다.
- `HumanReview`={schema_version:"bidops.hp-graph-human-review.v3",binding,expected_sha256,postgres_actual_sha256,neo4j_actual_sha256,annotator,authored_at,queries,explanation_samples,adoption,reason}. queries는 정확히 q1..q5의 {id,authoring_modification_winner:postgres|neo4j|tie|unassessed,reason:string|null}. explanation_samples는 실행 전에 고른 동일10개 {sample_id,path:Path,postgres_traceable:bool|null,neo4j_traceable:bool|null,degraded:bool|null,reason:string|null}; traceable은 원본 가상사실·관계방향·source 식별자를 모두 추적할 수 있다는 사람 판정이다. adoption=adopt|retain|defer|null, reason/actor/시각 null은 미작성. 기존 blank.v2는 보존하고 새 빈 v3를 구현한다. 샘플10개 미만은 문서 앞의 미측정 규칙 유지.
- `Manifest`={schema_version:"bidops.hp-graph-experiment.v1",binding,graph_file,export_file,requirements_file,expected_file,criteria_file,tool_files,parameters,neo4j}. *_file은 {path:허용 실험root 상대경로,sha256:Hash}; tool_files는 같은 객체[]로 repo 상대경로만 허용하며 shell로 해석하지 않는다. parameters={company_id:StableKey,min_amount_krw:int,min_months:int,min_people:int,qualification_concept:string,technology_concept:string,missing_concept:string,path_limit_per_requirement:positive int,max_hops:3,recall_relations:string[]}. 앞 질의 값은 실행 전 원본 조건에 맞춰 고정, 이후 변경은 새 manifest다. recall_relations는 현행5관계 그대로이고 q1..q5와 혼합하지 않는다. neo4j={image:string,digest:"sha256:"+64hex,project_name:string,network_internal:true,publish_ports:false}. expected와 파라미터를 바꾸면 새 버전이다.
- `Report`={schema_version:"bidops.hp-graph-comparison.v1",binding,manifest_sha256,expected_sha256,postgres_actual_sha256,neo4j_actual_sha256,human_review_sha256,criteria_sha256,postgres_score,neo4j_score,recall_delta:number|null,neo4j_wins:int|null,required_path_losses:int|null,explainability_degraded:bool|null,candidate:bool|null,adoption:null}. postgres_score/neo4j_score는 각각 {score:기존 graph-score 결과 전체,missing_required_baseline:[{query_id,path:Path}]}다. recall_delta는 recall: 접두 query만 micro 집계; 보조 q1..q5 recall을 합치지 않는다. required_path_losses는 required 집합 중 PostgreSQL에서 발견되고 Neo4j에서 빠진 path 수이며, 기존필수미발견은 missing_required_baseline에 query ID와 함께 기록하고 보호조건 판정을null로 둔다. 집계 키는 (query ID,node_ids,edge_ids)다. 후보 OR는 3값 논리(true OR null=true, false OR null=null), 보호조건 중 하나 미평가면 candidate=null, 하나라도 실패면false. 사람 adoption은 HumanReview에만 있고 Report는 자동채택하지 않는다.

실제 실행 기록은 위 manifest/actual/report와 함께 `feature.json.experiments_dir`의 날짜별 markdown에 가설→사전기준→실행명령/종료코드→결과→사람판단을 남긴다. 원시 graph/회사자료는 Git 밖이다.

## 실행 소유권과 수동 완료 게이트

`scripts/hp-graph-experiment.py`가 launch/query/cleanup을 소유한다. 추가 subcommand `launch --manifest <file> --runtime-dir <새dir>`는 digest로 고정한 Neo4j image, 별도 project_name의 internal Docker network/volume을 만들고 호스트 port를 publish하지 않는다. query는 같은 network의 일회용 adapter 컨테이너에서 Bolt `neo4j:7687`에 접속한다. credential은 runtime-dir의0600 파일(디렉터리0700), manifest/argv/stdout/Git에 넣지 않고 read-only secret mount로 양쪽에 전달한다. launch receipt에는 생성한 container/network/volume ID와 manifest SHA만 기록한다. `cleanup --receipt <file>`은 그 receipt에 열거된 자원만 제거하고 bidops-local/bidops/main 자원은 거부한다. credential 파일도 해당 runtime-dir에서만 삭제한다. 임의 Docker 전체 prune 금지. query 실패에도 결과·safe error/exit code는 보존한다.

신규 runtime 이미지 `tools/hp-graph-experiment/Dockerfile`과 고정 requirements.lock이 adapter를 포함한다. PostgreSQL 비교는 운영 DB 접속이 아니라 동결 graph를 읽는 현재 제품 BFS를 일회용 환경에서 실행한다. Neo4j 외 외부 egress 없음. image tag/digest·driver 정확 버전 선택은 구현 때 manifest/lock에 고정하는 기술 작업이며 지금 다운로드하지 않는다.

HP05에도 real_data_run 수동 proof를 적용한다. 실제 동일입력 비교 T6·사람 설명/질의 평가·최종 adopt/retain/defer 기록 전에는 done 불가, 도구 완료까지만 validating이다. 사람 결론이 retain/defer여도 실험 수행·기록이 완결됐다면 기능 완료 가능하고 제품 채택은 별도다.
