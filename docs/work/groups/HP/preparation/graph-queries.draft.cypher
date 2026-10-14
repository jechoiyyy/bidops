// DRAFT, NOT EXECUTED. Neo4j 5 legacy variable-length syntax; no APOC.
// Projection: (:HPNode {id,type,status,concept_id,...})-[:HP_EDGE {id,kind}]->(:HPNode)
// Each statement is separate. $parameters are frozen before any real experiment.
// All paths are directed, <=3 hops, simple-node paths; projection same as graph_queries.py.

// q1 amount and duration constrained projects
MATCH p=(c:HPNode {id:$company_id})-[:HP_EDGE*1..3]->(n:HPNode {type:'project',status:'confirmed'})
WHERE all(x IN nodes(p) WHERE single(y IN nodes(p) WHERE x=y))
 AND n.amount_krw >= $min_amount_krw AND n.duration_months >= $min_months
RETURN [x IN nodes(p)|x.id] AS node_ids, [e IN relationships(p)|e.id] AS edge_ids;

// q2 available onsite staff (availability snapshot date fixed in input binding)
MATCH p=(c:HPNode {id:$company_id})-[:HP_EDGE*1..3]->(n:HPNode {type:'staff_group',status:'confirmed'})
WHERE all(x IN nodes(p) WHERE single(y IN nodes(p) WHERE x=y)) AND n.available_people >= $min_people
RETURN [x IN nodes(p)|x.id] AS node_ids, [e IN relationships(p)|e.id] AS edge_ids;

// q3 qualifying project AND held qualification; return the union of both path sets
MATCH p=(c:HPNode {id:$company_id})-[:HP_EDGE*1..3]->(n:HPNode {type:'project',status:'confirmed'}),
 q=(c)-[:HP_EDGE*1..3]->(k:HPNode {type:'qualification',status:'confirmed'})
WHERE all(x IN nodes(p) WHERE single(y IN nodes(p) WHERE x=y))
 AND all(x IN nodes(q) WHERE single(y IN nodes(q) WHERE x=y))
 AND n.amount_krw >= $min_amount_krw AND n.duration_months >= $min_months
 AND k.concept_id=$qualification_concept AND k.held=true
UNWIND [p,q] AS r
RETURN DISTINCT [x IN nodes(r)|x.id] AS node_ids, [e IN relationships(r)|e.id] AS edge_ids;

// q4 technology path; supplementary expressiveness case, NOT current product recall semantics
MATCH p=(c:HPNode {id:$company_id})-[:HP_EDGE*1..3]->(n:HPNode {type:'technology',status:'confirmed'})
WHERE all(x IN nodes(p) WHERE single(y IN nodes(p) WHERE x=y)) AND n.concept_id=$technology_concept
RETURN [x IN nodes(p)|x.id] AS node_ids, [e IN relationships(p)|e.id] AS edge_ids;

// q5 confirmed missing fact tracing; unknown/null/no-path must never satisfy this query
MATCH p=(c:HPNode {id:$company_id})-[:HP_EDGE*1..3]->(n:HPNode {status:'confirmed'})
WHERE all(x IN nodes(p) WHERE single(y IN nodes(p) WHERE x=y))
 AND n.concept_id=$missing_concept AND n.held=false
RETURN [x IN nodes(p)|x.id] AS node_ids, [e IN relationships(p)|e.id] AS edge_ids;
