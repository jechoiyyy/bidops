import json,unittest
from pathlib import Path
from validate import validate,PageReview
SCHEMA=json.loads(Path(__file__).with_name('policy.json').read_text())['output_schema']
class EvidenceTests(unittest.TestCase):
 def setUp(self):
  self.r={'model_input':{'blocks':[{'pdf_page':3,'text':'사업금액 153,000,000원\n기간 6개월\n사업개요 ISMP'},{'pdf_page':4,'text':'과업범위 전환 완료'}]}}
  fact=lambda:{'text':'사업개요','evidence_pages':[3]}
  self.o={'schema_version':'bidops.prespec-overview-page-review.v3','business_overview':[fact()],'main_tasks':[fact()],'budget_and_period':[],'important_conditions':[],'reviewer_analysis':['역량 확인 필요'],'unknowns':[],'input_limitations':['참조 PDF']}
 def test_policy_schema_matches_validator(self):
  actual=PageReview.model_json_schema()
  def norm(v):
   if isinstance(v,list):return [norm(x) for x in v]
   if not isinstance(v,dict):return v
   if '$ref' in v:return norm(actual['$defs'][v['$ref'].split('/')[-1]])
   return {k:norm(x) for k,x in v.items() if k not in ['title','$defs'] and not (k=='minItems' and x==0)}
  self.assertEqual(norm(SCHEMA),norm(actual))
 def test_long_narrative_allowed(self):
  self.o['business_overview'][0]['text']='사업개요 설명.\n'*500
  self.assertEqual(validate(self.o,self.r,SCHEMA),[])
 def test_printed_page_not_a_pdf_page(self):
  self.o['business_overview'][0]['evidence_pages']=[1]
  self.assertIn('pdf_locator_mismatch',validate(self.o,self.r,SCHEMA))
 def test_multiple_pages_supported(self):
  self.o['business_overview'][0]['evidence_pages']=[3,4]
  self.assertEqual(validate(self.o,self.r,SCHEMA),[])
 def test_fact_number_requires_its_cited_page(self):
  self.o['business_overview'][0]={'text':'기간은 6개월','evidence_pages':[4]}
  self.assertIn('fact_number_not_on_cited_pages',validate(self.o,self.r,SCHEMA))
 def test_missing_evidence_rejected(self):
  self.o['main_tasks'][0]['evidence_pages']=[]
  self.assertIn('schema_invalid',validate(self.o,self.r,SCHEMA))
 def test_unsupported_acronym_expansion_rejected(self):
  self.o['main_tasks'][0]['text']='ISMP Implementation Strategy Master Plan'
  self.assertIn('latin_term_not_on_cited_pages',validate(self.o,self.r,SCHEMA))
 def test_budget_not_contract_amount(self):
  self.o['budget_and_period']=[{'text':'계약금액 153,000,000원','evidence_pages':[3]}]
  self.assertIn('budget_mislabelled_as_contract_amount',validate(self.o,self.r,SCHEMA))
 def test_boolean_page_rejected(self):
  self.o['main_tasks'][0]['evidence_pages']=[True]
  self.assertIn('schema_invalid',validate(self.o,self.r,SCHEMA))
if __name__=='__main__':unittest.main()
