"""Draft query-expression comparison on a normalized OFFLINE graph export.

No connection or loading code. Typed numeric fields are proposed projection fields,
not assumed to exist in product rows. None never satisfies a constraint.
The current product recall baseline is separately search_graph_paths; this helper
is a proposed supplemental query suite, not a replacement of its five relations.
"""
from collections import deque


def paths(graph, start, end=None):
    nodes={n['id']:n for n in graph['nodes']}
    adjacency={}
    for e in graph['edges']:adjacency.setdefault(e['from_id'],[]).append(e)
    queue=deque([([start],[])])
    while queue:
        ns,es=queue.popleft()
        if es and (end is None or ns[-1]==end):yield ns,es
        if len(es)==3:continue
        for e in adjacency.get(ns[-1],[]):
            if e['to_id'] not in ns and e['to_id'] in nodes:
                queue.append((ns+[e['to_id']],es+[e['id']]))


def queries(graph, params):
    ns={n['id']:n for n in graph['nodes']}
    company=params['company_id']
    ps=list(paths(graph,company))
    def confirmed(n):return n.get('status')=='confirmed'
    def lower(n,k,v):return type(n.get(k)) in (int,float) and n[k]>=v
    def selected(predicate):return [{'node_ids':n,'edge_ids':e} for n,e in ps if predicate(ns[n[-1]])]
    q1=selected(lambda n:confirmed(n) and n['type']=='project' and lower(n,'amount_krw',params['min_amount_krw']) and lower(n,'duration_months',params['min_months']))
    q2=selected(lambda n:confirmed(n) and n['type']=='staff_group' and lower(n,'available_people',params['min_people']))
    qual=selected(lambda n:confirmed(n) and n['type']=='qualification' and n.get('concept_id')==params['qualification_concept'] and n.get('held') is True)
    q3=q1+qual if q1 and qual else []
    q4=selected(lambda n:confirmed(n) and n['type']=='technology' and n.get('concept_id')==params['technology_concept'])
    # Positive evidence of absence only; no path is not evidence of a gap.
    q5=selected(lambda n:confirmed(n) and n.get('held') is False and n.get('concept_id')==params['missing_concept'])
    return {'q1':q1,'q2':q2,'q3':q3,'q4':q4,'q5':q5}
