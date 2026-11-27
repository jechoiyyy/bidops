import json, sys
g = json.load(open('company_fit_gold_1126.v2.json'))
L = {l['notice_id']: l for l in g['labels']}
def load(p):
    out = {}
    for line in open(p):
        r = json.loads(line)
        if r.get('kind') == 'result':
            out[r['notice_id']] = r
    return out
for p in sys.argv[1:]:
    R = load(p)
    dec = {n: (r.get('result') or {}).get('decision', r.get('status')) for n, r in R.items()}
    ok = [n for n in L if dec.get(n) in L[n].get('accept', [L[n]['decision']])]
    pm = [n for n in dec if dec[n] == 'matched']; gm = [n for n in L if L[n]['decision'] == 'matched']
    tp = [n for n in pm if n in gm]
    tally = {}
    for d in dec.values(): tally[d] = tally.get(d, 0) + 1
    el = [r.get('elapsed_s', 0) for r in R.values()]
    print(f"== {p}: n={len(R)} {tally} exact={len(ok)}/22 matched precision={len(tp)}/{len(pm)} recall={len(tp)}/{len(gm)} retried={sum(bool(r.get('retried')) for r in R.values())} status={[ (n,r['status']) for n,r in R.items() if r['status']!='completed']} total_min={sum(el)/60:.1f}")
    for n in sorted(L):
        if n not in ok:
            s = (R.get(n, {}).get('result') or {}).get('summary', R.get(n, {}).get('error'))
            print(f"  #{n} model={dec.get(n)} gold={L[n].get('accept', L[n]['decision'])} | {s}")
