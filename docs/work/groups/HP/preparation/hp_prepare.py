#!/usr/bin/env python3
"""Offline DRAFT preparation; no DB/network/model, no acceptance decisions.

Run with the repository backend environment. Outputs are exclusive-create 0600.
Raw cards and blind human worksheets must be written outside Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / 'web/backend'))
VERDICTS = {'진행 가능', '조건부 진행', '진행 어려움', '판단 불가'}
STATES = {'met', 'gap', 'unknown'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def read(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('duplicate_json_key')
            result[k] = v
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(canonical(value) + b'\n')


def unique_rows(rows, key):
    if not isinstance(rows, list):
        raise ValueError('rows_required')
    result = {}
    for r in rows:
        k = r[key]
        if not isinstance(k, str) or not k or k in result:
            raise ValueError('invalid_or_duplicate_id')
        result[k] = r
    return result


def outside_git(path):
    if Path(path).resolve().is_relative_to(ROOT):
        raise ValueError('raw_output_must_be_outside_worktree')


def source_file(directory, name):
    path = directory / name
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError('source_path_outside_input')
    return path


def export_cards(directory):
    directory = Path(directory)
    sources = unique_rows(read(source_file(directory, 'sources.json')), 'name')
    docs = []
    for name, src in sorted(sources.items()):
        source_docs, all_cards = [], []
        for item in [src, *src.get('companions', [])]:
            source_doc, cards = export_source(directory, item)
            source_docs.append(source_doc)
            all_cards.extend(cards)
        unique_rows(source_docs, 'source_sha256')
        unique_rows(all_cards, 'unit_id')
        docs.append({'document_id': name, 'source_sha256': src['source_sha256'],
                     'source_documents': source_docs, 'sources_sha256': source_binding(source_docs),
                     'cards': all_cards})
    return {'schema_version': 'bidops.hp-preparation-cards.v2', 'status': 'draft', 'documents': docs}


def export_source(directory, src):
    from app.deep_review.services.document_segments import build_manifest_payload, resolve_card_pages
    name = src['name']
    source_path = source_file(directory, src['file'])
    if digest(source_path.read_bytes()) != src['source_sha256']:
        raise ValueError('source_hash_mismatch')
    sp = source_file(directory, f'{name}.structure.json')
    mp = source_file(directory, f'{name}.para_page_map.json')
    s, m = read(sp), read(mp)
    if s['source_sha256'] != src['source_sha256']:
        raise ValueError('structure_source_mismatch')
    cards = resolve_card_pages(build_manifest_payload(s), m)
    rows = []
    for c in cards:
        table = c['card']['table_key']
        blocks = [b for b in s['blocks'] if b.get('attributes', {}).get('table_key') == table]
        rows.append({**c, 'unit_id': f"card:{src['source_sha256']}:{c['ordinal']}:{c['normalized_id']}",
                     'blocks': [{'block_key': b['block_key'], 'text': b.get('text', '')} for b in blocks]})
    unique_rows(rows, 'unit_id')
    doc = {'source_sha256': src['source_sha256'],
           'structure_sha256': digest(sp.read_bytes()), 'page_map_sha256': digest(mp.read_bytes()),
           'blocks': [{'unit_id': f"block:{src['source_sha256']}:{b['block_key']}",
                       'block_key': b['block_key'], 'text': b['text']}
                      for b in s['blocks'] if b.get('text', '').strip()]}
    unique_rows(doc['blocks'], 'unit_id')
    return doc, rows


def source_binding(documents):
    return digest(canonical(sorted([{k: d[k] for k in
        ('source_sha256', 'structure_sha256', 'page_map_sha256')} for d in documents],
        key=lambda d: d['source_sha256'])))


def source_universe(document):
    sources = unique_rows(document['source_documents'], 'source_sha256')
    if document['source_sha256'] not in sources or document['sources_sha256'] != source_binding(list(sources.values())):
        raise ValueError('source_set_binding_mismatch')
    blocks = []
    for sha, src in sources.items():
        for key in ('source_sha256', 'structure_sha256', 'page_map_sha256'):
            hash_value(src[key])
        for block in src['blocks']:
            if block['unit_id'] != f"block:{sha}:{block['block_key']}" or not block.get('text'):
                raise ValueError('source_block_invalid')
            blocks.append(block)
    block_ids = set(unique_rows(blocks, 'unit_id'))
    cards = set(unique_rows(document['source_cards'], 'unit_id'))
    for card in cards:
        if len(card.split(':')) < 4 or card.split(':')[0] != 'card' or card.split(':')[1] not in sources:
            raise ValueError('card_source_invalid')
    return cards, cards | block_ids


def coverage(pack, ontology):
    from app.core.company_ontology import parse_ontology
    from app.deep_review.services.company_knowledge_retrieval import match_concepts
    parsed = parse_ontology(canonical(ontology))
    rows = []
    for d in pack['documents']:
        for c in d['cards']:
            evidence = []
            for b in c['blocks']:
                for concept in match_concepts(b['text'], parsed):
                    evidence.append({'concept_id': concept, 'block_key': b['block_key'], 'quote': b['text']})
            rows.append({'document_id': d['document_id'], 'source_sha256': c['unit_id'].split(':')[1],
                         'unit_id': c['unit_id'], 'card_id': c['normalized_id'], 'title': c['title'],
                         'page_range': c['page_range'], 'mapping_status': c['mapping_status'],
                         'concept_ids': sorted({e['concept_id'] for e in evidence}), 'evidence': evidence})
    matched = sum(bool(r['concept_ids']) for r in rows)
    return {'schema_version': 'bidops.hp-preparation-coverage.v1', 'status': 'draft_unapproved',
            'ontology_sha256': digest(canonical(ontology)), 'card_count': len(rows), 'matched_cards': matched,
            'candidate_coverage': matched / len(rows) if rows else None, 'rows': rows}


def blank_gold(pack):
    # Whitelist source-only fields. Never copy coverage, concept suggestions or model outputs.
    docs = []
    for d in pack['documents']:
        docs.append({'document_id': d['document_id'], 'source_sha256': d['source_sha256'],
                     'sources_sha256': d['sources_sha256'],
                     'source_documents': [{**{k: src[k] for k in ('source_sha256', 'structure_sha256', 'page_map_sha256')},
                                           'blocks': [{k: b[k] for k in ('unit_id', 'block_key', 'text')} for b in src['blocks']]}
                                          for src in d['source_documents']],
                     'verdict': None, 'blocking_conditions': None, 'met': None, 'gap': None,
                     'cautions': None, 'card_states': [],
                     'source_cards': [{k: c[k] for k in ('unit_id', 'raw_id', 'title', 'card', 'blocks',
                                                        'locator', 'page_range', 'mapping_status')} for c in d['cards']]})
    return {'schema_version': 'bidops.hp-human-gold-preparation.v3', 'status': 'blank',
            'annotator': None, 'authored_at': None, 'written_before_model_output': None,
            'company_sha256': None, 'ontology_sha256': None, 'documents': docs}


def id_list(value):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value) or len(set(value)) != len(value):
        raise ValueError('invalid_id_list')
    return set(value)


def hash_value(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('hash_required')


def check_gold(gold, expected_documents=10):
    if gold.get('schema_version') != 'bidops.hp-human-gold-preparation.v3' or gold.get('status') != 'human_completed':
        raise ValueError('human_gold_incomplete')
    if not gold.get('annotator') or not gold.get('authored_at') or gold.get('written_before_model_output') is not True:
        raise ValueError('human_provenance_required')
    for k in ('company_sha256', 'ontology_sha256'):
        hash_value(gold.get(k))
    docs = unique_rows(gold['documents'], 'document_id')
    if len(docs) != expected_documents:
        raise ValueError('document_count_mismatch')
    for d in docs.values():
        hash_value(d['source_sha256'])
        if d['verdict'] not in VERDICTS or not isinstance(d['cautions'], list):
            raise ValueError('human_fields_incomplete')
        card_ids, universe = source_universe(d)
        for k in ('met', 'gap'):
            ids = id_list(d[k])
            if not ids <= universe:
                raise ValueError('source_ids_required')
        if set(d['met']) & set(d['gap']):
            raise ValueError('contradictory_gold')
        # Conditions are human-assigned stable IDs; text-only matching needs adjudication.
        conditions = unique_rows(d['blocking_conditions'], 'condition_id')
        for c in conditions.values():
            if not c.get('text') or not id_list(c['source_unit_ids']) or not set(c['source_unit_ids']) <= universe:
                raise ValueError('condition_evidence_required')
        states = unique_rows(d['card_states'], 'unit_id')
        if len(states) != 10 or not set(states) <= card_ids or any(r['status'] not in STATES for r in states.values()):
            raise ValueError('ten_card_states_required')
        for k in ('met', 'gap'):
            if any(i in states and states[i]['status'] != k for i in d[k]):
                raise ValueError('contradictory_card_state')
    return docs


def ratio(n, d):
    return {'numerator': n, 'denominator': d, 'value': n/d if d else None}


def candidate_checks(rows):
    criteria_path = Path(__file__).with_name('acceptance-criteria.approved.v1.json')
    criteria = read(criteria_path)
    def aggregate(field):
        return ratio(sum(r[field]['numerator'] for r in rows),
                     sum(r[field]['denominator'] for r in rows))
    blocking = aggregate('blocking_recall')
    cards = aggregate('card_accuracy')
    correct = sum(r['verdict_correct'] for r in rows)
    def verdict(value):
        return 'pass' if value else 'fail'
    def minimum(metric, threshold):
        return 'unmeasured' if metric['value'] is None else verdict(metric['value'] >= threshold)
    checks = {
        'document_count': verdict(len(rows) == criteria['document_count']),
        'verdict_correct': verdict(correct >= criteria['verdict_correct_min']),
        'blocking_recall': minimum(blocking, criteria['blocking_recall_min']),
        'card_accuracy': minimum(cards, criteria['card_accuracy_min']),
        # A model or the scorer must never author this human adjudication.
        'critical_false_met': 'pending_human_review',
    }
    return {'criteria_sha256': digest(criteria_path.read_bytes()),
            'checks': checks, 'blocking_recall_micro': blocking,
            'card_accuracy_micro': cards, 'verdict_correct': correct,
            'critical_false_met_count': None,
            'critical_false_met_max': criteria['critical_false_met_max'],
            'status': 'numeric_criteria_failed' if 'fail' in checks.values() else 'pending_human_review',
            'acceptance': 'not_decided'}


def score(gold, prediction, expected_documents=10):
    gs = check_gold(gold, expected_documents)
    ps = unique_rows(prediction['documents'], 'document_id')
    if set(gs) != set(ps) or any(gold[k] != prediction.get(k) for k in ('company_sha256', 'ontology_sha256')):
        raise ValueError('prediction_binding_mismatch')
    out = []
    for key, g in gs.items():
        p = ps[key]
        if p['source_sha256'] != g['source_sha256'] or p.get('sources_sha256') != g['sources_sha256'] or p['verdict'] not in VERDICTS:
            raise ValueError('prediction_source_or_verdict_invalid')
        card_ids, universe = source_universe(g)
        for field in ('met', 'gap'):
            if not id_list(p[field]) <= universe:
                raise ValueError('prediction_source_ids_required')
        if set(p['met']) & set(p['gap']):
            raise ValueError('contradictory_prediction')
        states = unique_rows(p['card_states'], 'unit_id')
        if not set(states) <= card_ids or any(v['status'] not in STATES for v in states.values()):
            raise ValueError('prediction_card_invalid')
        sample = {r['unit_id']: r['status'] for r in g['card_states']}
        if not set(sample) <= set(states):
            raise ValueError('prediction_card_missing')
        expected = set(unique_rows(g['blocking_conditions'], 'condition_id'))
        found = id_list(p['blocking_condition_ids'])
        differences = [i for i, s in sample.items() if states[i]['status'] != s]
        out.append({'document_id': key, 'verdict_correct': g['verdict'] == p['verdict'],
                    'blocking_recall': ratio(len(expected & found), len(expected)),
                    'met_reference_precision': ratio(len(set(g['met']) & set(p['met'])), len(p['met'])),
                    'gap_reference_precision': ratio(len(set(g['gap']) & set(p['gap'])), len(p['gap'])),
                    'unmatched_met_need_human_adjudication': sorted(set(p['met'])-set(g['met'])),
                    'unmatched_gap_need_human_adjudication': sorted(set(p['gap'])-set(g['gap'])),
                    'card_accuracy': ratio(len(sample)-len(differences), len(sample)),
                    'card_mismatches': differences, 'missing_conditions': sorted(expected-found),
                    'unmatched_conditions_need_human_adjudication': sorted(found-expected)})
    return {'schema_version': 'bidops.hp-preparation-score.v4', 'acceptance': 'not_decided',
            'candidate_assessment': candidate_checks(out),
            'verdict_accuracy': ratio(sum(r['verdict_correct'] for r in out), len(out)), 'documents': out,
            'note': 'variable-length reference overlap only; unmatched items and free-text conditions need human adjudication; no automatic acceptance'}


def path_set(rows):
    keys = []
    for p in rows:
        nodes, edges = p['node_ids'], p['edge_ids']
        if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes or len(nodes) != len(edges)+1 or len(edges)>3:
            raise ValueError('invalid_path')
        if len(set(nodes)) != len(nodes) or any(not isinstance(x,str) or not x for x in nodes+edges):
            raise ValueError('invalid_path')
        keys.append((tuple(nodes), tuple(edges)))
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate_path')
    return set(keys)


def graph_score(expected, actual):
    if expected.get('binding') != actual.get('binding') or not expected.get('binding'):
        raise ValueError('graph_binding_mismatch')
    es, found = unique_rows(expected['queries'], 'id'), unique_rows(actual['queries'], 'id')
    if set(es) != set(found):
        raise ValueError('query_set_mismatch')
    rows = []
    for k,e in es.items():
        a = path_set(found[k]['paths'])
        if e['paths'] is None:
            rows.append({'id': k, 'recall': None, 'status': 'unscored_human_paths_missing'})
        else:
            wanted = path_set(e['paths'])
            rows.append({'id': k, 'recall': ratio(len(wanted&a), len(wanted)),
                         'missing': sorted(wanted-a), 'extra': sorted(a-wanted)})
    return {'schema_version': 'bidops.hp-graph-preparation-score.v1', 'adoption': 'not_decided', 'queries': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['export','coverage','blank-gold','gold-check','score','graph-score'])
    p.add_argument('inputs', nargs='+')
    p.add_argument('--out', required=True)
    a = p.parse_args()
    try:
        if a.action in {'export','coverage','blank-gold'}:
            outside_git(a.out)
        expected = 2 if a.action in {'coverage','score','graph-score'} else 1
        if len(a.inputs) != expected:
            raise ValueError('input_count')
        if a.action == 'export': result = export_cards(a.inputs[0])
        elif a.action == 'coverage': result = coverage(read(a.inputs[0]), read(a.inputs[1]))
        elif a.action == 'blank-gold': result = blank_gold(read(a.inputs[0]))
        elif a.action == 'gold-check':
            check_gold(read(a.inputs[0])); result = {'schema_version':'bidops.hp-gold-check.v2','structurally_valid':True,'acceptance':'not_decided'}
        elif a.action == 'score': result = score(read(a.inputs[0]), read(a.inputs[1]))
        else: result = graph_score(read(a.inputs[0]), read(a.inputs[1]))
        result['input_sha256'] = [digest(Path(x).read_bytes()) if Path(x).is_file() else None for x in a.inputs]
        result['tool_sha256'] = digest(Path(__file__).read_bytes())
        if a.action in {'score','graph-score'}:
            binding = {'inputs':result['input_sha256'],'tool':result['tool_sha256']}
            if a.action == 'score':
                binding['criteria'] = result['candidate_assessment']['criteria_sha256']
            result['scoring_input_sha256'] = digest(canonical(binding))
        write(a.out, result)
        print(json.dumps({'status':'prepared','action':a.action}))
        return 0
    except Exception:
        # Never echo source text, credentials or malformed input values.
        print('hp-prepare: invalid/incomplete input or output already exists', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
