# HP-05 비교 준비 (실험 미실행)

사용자 결정대로 비교 기준은 경로 recall·질의 표현력·설명 가능성 세 가지다. **운영 비용과 Apache AGE는 제외**한다. 공통 계약 §10의 “운영 비용 수용” 문장은 기존 결정과 충돌하는 잔여 문구이며 실험 기준으로 쓰지 않는다. 별도의 채택 결정을 대신 만들지 않고 다음 정본 정리 때 제거한다.

준비물: [Python 질의](../../preparation/graph_queries.py), [Cypher 5 질의](../../preparation/graph-queries.draft.cypher), [사람 평가 빈 양식](../../preparation/graph-human-review.blank.json), [경로 채점기 graph-score](../../preparation/hp_prepare.py). Python의 숫자 경계·null·unknown·cycle은 합성 자료에서만 검사했다. Cypher는 실행하지 않았다. Neo4j 이미지를 받거나 컨테이너를 띄우지 않았다.

두 가지 측정을 섞지 않는다.

1. **현행 제품 recall**: 동일 동결 회사 그래프·요구 concept를 `company_knowledge_retrieval.search_graph_paths`에 입력. 현행은 company에서 has_capability/holds_qualification/performed/has_staff/supports_capability 다섯 관계, directed simple path 최대3hop, direct/partial만 인정한다. path_limit·excluded count를 기록한다. Neo4j도 동일 관계·종점·순서·cap으로 맞춰 측정해야 하며 그 어댑터는 최종 동결 뒤 구현/검증한다. 기술 관계 uses_technology는 현재 recall 경로가 아니다.
2. **보조 질의 표현력**: 준비한 5개 쌍은 typed 가상 그래프 export 위에서 같은 directed simple path 최대3hop을 조회한다. q1 금액·기간 실적, q2 가용 인력, q3 자격 AND 실적(두 경로 집합 합집합), q4 기술 경로, q5 confirmed false 사실 역추적. 이는 현행 제품 BFS의 수치 대조 기능이 이미 있다는 뜻이 아니다. 기존 PostgreSQL 그래프 row에서 중립 export 후 Python으로 질의하는 쪽과 같은 export의 Neo4j Cypher를 비교한다. SQL 재귀 질의를 새 제품 기능으로 추가하지 않는다.

제안 projection: node `{id,type,status,concept_id,amount_krw,duration_months,available_people,held}` / edge `{id,from_id,to_id,type}`. 원문·프롬프트·회사 실자료 제외. 값이 없으면 null; unknown 값으로 조건을 통과시키지 않는다. 금액 통화·기간 기준·인력 가용 기준일은 export binding에 고정한다. q5는 confirmed false만 반환하며 no path를 미보유로 바꾸지 않는다.

실험 절차(아직 실행 불가):

1. D1/D2/D8 및 문서10건·요구concept·사람 기대경로를 먼저 확정한다. 후보 경로를 보여 주고 정답을 쓰는 방식은 recall 정답을 오염시킬 수 있어, 원본 그래프를 보고 기대경로를 먼저 작성하는 안을 추천한다.
2. 가상 자료 export·ontology/company/source hashes·질의 params·도구 sha·Neo4j5 정확 버전+digest를 manifest에 고정한다. 현재 `neo4j:5-community` floating tag를 실행 명령으로 사용하지 않는다.
3. 폐기 가능한 별도 DB/볼륨·internal network에서 양쪽 적재. 기존 bidops-local DB에 실험 테이블을 쓰지 않는다. 노드·edge ID/속성/방향/개수·canonical hash 동일성부터 확인한다.
4. 위 현행 recall와 보조질의를 분리 실행하고 raw 경로·종료코드·잘림 수를 저장한다. q3 중복 결과는 정규화 단계에서 명시적으로 DISTINCT; 채점기에 중복이 들어오면 오류로 거부한다.
5. `hp_prepare.py graph-score expected.json actual.json --out score.<engine>.json`. 두 입력 binding 동일 필수, query ID 집합 동일 필수, 경로는 node_ids와 edge_ids 순서까지 일치해야 한다. 미작성 paths=null은 미채점, 빈 기대집합은 분모0/null. 누락경로·추가경로·recall을 보존하며 자동 채택하지 않는다.
6. 같은10경로에 대해 설명의 근거 추적 가능성·판단에 필요한 누락 정보를 사람이 평가한다. 5질의의 가독성·변경 용이성도 사람 점수와 이유로 남긴다. 운영 비용 점수는 받지 않는다.
7. 사전 기준으로 유지/채택/보류를 사람이 결정한다. 채택이면 replan으로 제품 연결 범위를 따로 만든다.

D8 추천: “2경로/10건”은 분모가 모호하므로 기대경로 전체의 micro recall 개선 ≥0.10(제안)·기존 필수경로 회귀0, 또는 5질의 중3개 이상에서 사전 정의한 가독성/변경용이성 우위를 채택 후보 조건으로 삼고 설명 가능성 열화가 없어야 한다. 대안은 recall 차이가 없더라도 질의 표현력만으로 채택 후보를 만드는 것(주관 평가 비중 증가). 숫자·가중·최종 채택은 모두 미확정. 실행 결과를 보고 임계값을 고치지 않는다.

구문 조사: [Neo4j variable-length paths](https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-paths/)와 [PostgreSQL17 WITH](https://www.postgresql.org/docs/17/queries-with.html)를 확인했다. 초안은 Neo4j5 호환 legacy `*1..3` 표기를 사용하며 실제 고정 버전에서 실행 검증이 남아 있다. 문서 조회가 DB 엔진 동등성의 증거는 아니다.
