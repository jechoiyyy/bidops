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
    ids = [f'synthetic:{i}' for i in range(10)]
    doc = {'document_id':'synthetic-only','source_sha256':'a'*64,'verdict':'판단 불가',
           'blocking_conditions':[], 'met':ids[:5],'gap':ids[5:],'cautions':[],
           'source_cards':[{'unit_id':i} for i in ids],
           'card_states':[{'unit_id':i,'status':'met' if n<5 else 'gap'} for n,i in enumerate(ids)]}
    g = {'schema_version':'bidops.hp-human-gold-preparation.v1','status':'human_completed',
         'annotator':'SYNTHETIC-TEST-NOT-HUMAN','authored_at':'synthetic', 'written_before_model_output':True,
         'company_sha256':'b'*64,'ontology_sha256':'c'*64,'documents':[doc]}
    p = {'company_sha256':'b'*64,'ontology_sha256':'c'*64,'documents':[copy.deepcopy(doc)]}
    p['documents'][0]['blocking_condition_ids']=[]
    return g,p


class PrepareTests(unittest.TestCase):
    def test_input_path_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'input';root.mkdir()
            outside=Path(d)/'outside';outside.write_text('private')
            (root/'link').symlink_to(outside)
            for name in ('../outside','link'):
                with self.assertRaises(ValueError):m.source_file(root,name)
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
        s=m.blank_gold({'documents':[dict(document_id='x',source_sha256='a'*64,cards=[card])]})
        self.assertNotIn('secret',json.dumps(s));self.assertNotIn('suggestion',json.dumps(s))
        self.assertIsNone(s['documents'][0]['verdict'])


if __name__=='__main__':unittest.main()
