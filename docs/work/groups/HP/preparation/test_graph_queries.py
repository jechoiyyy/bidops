import unittest
from graph_queries import queries

class GraphQueryTests(unittest.TestCase):
    def test_synthetic_boundaries_null_and_cycles(self):
        nodes=[dict(id='c',type='company'),dict(id='p',type='project',status='confirmed',amount_krw=100,duration_months=12),dict(id='s',type='staff_group',status='unknown',available_people=9),dict(id='q',type='qualification',status='confirmed',concept_id='qual.x',held=True),dict(id='t',type='technology',status='confirmed',concept_id='tech.x'),dict(id='m',type='qualification',status='confirmed',concept_id='qual.m',held=False)]
        edges=[dict(id='e'+str(i),from_id='c',to_id=n['id']) for i,n in enumerate(nodes[1:])]+[dict(id='cycle',from_id='p',to_id='c')]
        params=dict(company_id='c',min_amount_krw=100,min_months=12,min_people=1,qualification_concept='qual.x',technology_concept='tech.x',missing_concept='qual.m')
        result=queries(dict(nodes=nodes,edges=edges),params)
        self.assertEqual({k:len(v) for k,v in result.items()},dict(q1=1,q2=0,q3=2,q4=1,q5=1))
        nodes[1]['amount_krw']=None;nodes[-1]['status']='unknown'
        result=queries(dict(nodes=nodes,edges=edges),params)
        self.assertEqual(result['q1'],[]);self.assertEqual(result['q3'],[]);self.assertEqual(result['q5'],[])
