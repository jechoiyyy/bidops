"""Synthetic-only tool checks. These are never human gold or acceptance evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('hp_prepare', Path(__file__).with_name('hp_prepare.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def synthetic():
    ids = [f"card:{'a'*64}:{i}:SFR-{i}" for i in range(10)]
    doc = {'document_id':'synthetic-only','source_sha256':'a'*64,'verdict':'판단 불가',
           'blocking_conditions':[], 'met':ids[:5],'gap':ids[5:],'cautions':[],
           'source_cards':[{'unit_id':i} for i in ids],
           'card_states':[{'unit_id':i,'status':'met' if n<5 else 'gap'} for n,i in enumerate(ids)]}
    doc['source_documents']=[{'source_sha256':'a'*64,'structure_sha256':'d'*64,'page_map_sha256':'e'*64,'blocks':[]}]
    doc['sources_sha256']=m.source_binding(doc['source_documents'])
    g = {'schema_version':'bidops.hp-human-gold-preparation.v3','status':'human_completed',
         'annotator':'SYNTHETIC-TEST-NOT-HUMAN','authored_at':'synthetic', 'written_before_model_output':True,
         'company_sha256':'b'*64,'ontology_sha256':'c'*64,'documents':[doc]}
    p = {'company_sha256':'b'*64,'ontology_sha256':'c'*64,'documents':[copy.deepcopy(doc)]}
    p['documents'][0]['blocking_condition_ids']=[]
    return g,p


class PrepareTests(unittest.TestCase):
    def test_coverage_keeps_companion_source_hash(self):
        ontology=m.read(Path(__file__).with_name('ontology.candidates.draft.v3.json'))
        card={'unit_id':'card:'+'f'*64+':1:SFR-1','normalized_id':'SFR-1','title':'synthetic',
              'page_range':None,'mapping_status':'unavailable','blocks':[{'block_key':'p1','text':'Java'}]}
        result=m.coverage({'documents':[{'document_id':'synthetic','source_sha256':'a'*64,'cards':[card]}]},ontology)
        self.assertEqual(result['rows'][0]['source_sha256'],'f'*64)
        self.assertEqual(result['rows'][0]['concept_ids'],['tech.java'])
    def test_companion_noncard_evidence_and_binding(self):
        g,p=synthetic();d=g['documents'][0]
        block={'unit_id':'block:'+'f'*64+':paragraph-1','block_key':'paragraph-1','text':'synthetic qualification only'}
        d['source_documents'].append({'source_sha256':'f'*64,'structure_sha256':'1'*64,'page_map_sha256':'2'*64,'blocks':[block]})
        d['sources_sha256']=m.source_binding(d['source_documents'])
        d['blocking_conditions']=[{'condition_id':'synthetic-condition','text':'synthetic only','source_unit_ids':[block['unit_id']]}]
        d['met']=[block['unit_id']];d['gap']=[]
        pd=p['documents'][0];pd['sources_sha256']=d['sources_sha256'];pd['met']=d['met'];pd['gap']=[]
        pd['blocking_condition_ids']=['synthetic-condition']
        result=m.score(g,p,1)
        self.assertEqual(result['documents'][0]['blocking_recall']['value'],1)
        pd['sources_sha256']='0'*64
        with self.assertRaises(ValueError):m.score(g,p,1)
        d['card_states'][0]['unit_id']=block['unit_id']
        with self.assertRaises(ValueError):m.check_gold(g,1)
    def test_tampered_source_set_and_foreign_block_rejected(self):
        g,p=synthetic();d=g['documents'][0]
        d['source_documents'][0]['structure_sha256']='f'*64
        with self.assertRaises(ValueError):m.check_gold(g,1)
        g,p=synthetic();d=g['documents'][0]
        d['source_documents'][0]['blocks']=[{'unit_id':'block:'+'f'*64+':x','block_key':'x','text':'synthetic'}]
        with self.assertRaises(ValueError):m.check_gold(g,1)
    def test_legacy_single_source_gold_rejected(self):
        g,p=synthetic();g['schema_version']='bidops.hp-human-gold-preparation.v2'
        with self.assertRaises(ValueError):m.check_gold(g,1)
    def test_input_path_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'input';root.mkdir()
            outside=Path(d)/'outside';outside.write_text('private')
            (root/'link').symlink_to(outside)
            for name in ('../outside','link'):
                with self.assertRaises(ValueError):m.source_file(root,name)
    def test_variable_count_and_empty_confirmed_lists(self):
        g,p=synthetic()
        g['documents'][0]['met']=['card:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:0:SFR-0']
        g['documents'][0]['gap']=[]
        p['documents'][0]['met']=['card:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:0:SFR-0','card:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:1:SFR-1']
        p['documents'][0]['gap']=[]
        result=m.score(g,p,1)['documents'][0]
        self.assertEqual(result['met_reference_precision']['denominator'],2)
        self.assertEqual(result['met_reference_precision']['value'],0.5)
        self.assertIsNone(result['gap_reference_precision']['value'])
        self.assertEqual(result['unmatched_met_need_human_adjudication'],['card:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:1:SFR-1'])
    def test_unwritten_lists_and_legacy_schema_rejected(self):
        for field in ('met','gap'):
            g,p=synthetic();g['documents'][0][field]=None
            with self.assertRaises(ValueError):m.check_gold(g,1)
        g,p=synthetic();g['schema_version']='bidops.hp-human-gold-preparation.v1'
        with self.assertRaises(ValueError):m.check_gold(g,1)
    def test_variable_lists_still_reject_duplicates_and_foreign_ids(self):
        for values in (['card:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:0:SFR-0','card:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:0:SFR-0'],['foreign']):
            g,p=synthetic();g['documents'][0]['met']=values
            with self.assertRaises(ValueError):m.check_gold(g,1)
        g,p=synthetic();p['documents'][0]['gap']=['card:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:0:SFR-0']
        with self.assertRaises(ValueError):m.score(g,p,1)
    def test_approved_threshold_boundaries_and_human_review_pending(self):
        rows=[{'verdict_correct':i<8,'blocking_recall':m.ratio(4,5),
               'card_accuracy':m.ratio(7,10)} for i in range(10)]
        result=m.candidate_checks(rows)
        for key in ('document_count','verdict_correct','blocking_recall','card_accuracy'):
            self.assertEqual(result['checks'][key],'pass')
        self.assertEqual(result['checks']['critical_false_met'],'pending_human_review')
        self.assertIsNone(result['critical_false_met_count'])
        self.assertEqual(result['acceptance'],'not_decided')
        rows[0]['verdict_correct']=False
        rows[0]['blocking_recall']=m.ratio(3,5)
        rows[0]['card_accuracy']=m.ratio(6,10)
        result=m.candidate_checks(rows)
        for key in ('verdict_correct','blocking_recall','card_accuracy'):
            self.assertEqual(result['checks'][key],'fail')
    def test_no_blocking_conditions_is_unmeasured_not_pass(self):
        rows=[{'verdict_correct':True,'blocking_recall':m.ratio(0,0),
               'card_accuracy':m.ratio(10,10)} for _ in range(10)]
        self.assertEqual(m.candidate_checks(rows)['checks']['blocking_recall'],'unmeasured')
    def test_five_documents_cannot_meet_ten_document_criteria(self):
        rows=[{'verdict_correct':True,'blocking_recall':m.ratio(1,1),
               'card_accuracy':m.ratio(10,10)} for _ in range(5)]
        self.assertEqual(m.candidate_checks(rows)['checks']['document_count'],'fail')
    def test_blank_is_not_gold(self):
        with self.assertRaises(ValueError): m.check_gold({'status':'blank'})
    def test_source_binding_rejected(self):
        g,p=synthetic();p['documents'][0]['source_sha256']='d'*64
        with self.assertRaises(ValueError):m.score(g,p,1)
    def test_no_automatic_acceptance_and_null_denominator(self):
        g,p=synthetic();s=m.score(g,p,1)
        self.assertEqual(s['acceptance'],'not_decided')
        self.assertIsNone(s['documents'][0]['blocking_recall']['value'])
        self.assertEqual(s['verdict_accuracy']['value'],1)
    def test_missing_duplicate_or_unknown_card_rejected(self):
        for action in ('missing','duplicate','unknown'):
            g,p=synthetic(); rows=p['documents'][0]['card_states']
            if action=='missing':rows.pop()
            elif action=='duplicate':rows.append(rows[0])
            else:rows[0]['unit_id']='not-in-source'
            with self.assertRaises(ValueError):m.score(g,p,1)
    def test_wrong_state_measured(self):
        g,p=synthetic();p['documents'][0]['card_states'][0]['status']='unknown'
        self.assertEqual(m.score(g,p,1)['documents'][0]['card_accuracy']['value'],0.9)
    def test_contradictory_gold(self):
        g,p=synthetic();g['documents'][0]['card_states'][0]['status']='gap'
        with self.assertRaises(ValueError):m.check_gold(g,1)
    def test_gold_requires_ten_documents_in_cli(self):
        with self.assertRaises(ValueError):m.check_gold(synthetic()[0])
    def test_output_is_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'o.json';m.write(p,{'v':1})
            with self.assertRaises(FileExistsError):m.write(p,{'v':2})
            self.assertEqual(m.read(p),{'v':1})
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
    def test_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'o';p.write_text('{"x":1,"x":2}')
            with self.assertRaises(ValueError):m.read(p)
    def test_graph_unscored_and_duplicate_rejected(self):
        e={'binding':{'graph_sha256':'a'*64},'queries':[{'id':'q','paths':None}]}
        a={'binding':e['binding'],'queries':[{'id':'q','paths':[]}]}
        self.assertIsNone(m.graph_score(e,a)['queries'][0]['recall'])
        path={'node_ids':['c','n'],'edge_ids':['e']}
        a['queries'][0]['paths']=[path,path]
        with self.assertRaises(ValueError):m.graph_score(e,a)
    def test_graph_expected_recall(self):
        path={'node_ids':['c','n'],'edge_ids':['e']}
        e={'binding':{'graph_sha256':'a'*64},'queries':[{'id':'q','paths':[path]}]}
        a={'binding':e['binding'],'queries':[{'id':'q','paths':[]}]}
        self.assertEqual(m.graph_score(e,a)['queries'][0]['recall']['value'],0)
    def test_blind_sheet_discards_suggestions(self):
        card=dict(unit_id='x',raw_id='SFR-1',title='source',card={},blocks=[],locator={},page_range=None,mapping_status='unavailable',model_answer='secret',concept_ids=['suggestion'])
        g,_=synthetic();d=g['documents'][0];d['cards']=[card]
        d['source_documents'][0]['model_answer']='secret'
        s=m.blank_gold({'documents':[d]})
        self.assertNotIn('secret',json.dumps(s));self.assertNotIn('suggestion',json.dumps(s))
        self.assertIsNone(s['documents'][0]['verdict'])


if __name__=='__main__':unittest.main()
