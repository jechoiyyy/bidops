import json, hashlib, subprocess, re, difflib, pathlib
UP = "/Users/temp/orca/projects/bid-deep-agent"
PKG = pathlib.Path("/Users/temp/orca/bidops/packages/bid-deep-engine")
meta = json.loads((PKG/"UPSTREAM.json").read_text())
c = meta["commit"]
def vpath(p):
    if p.startswith("src/bidops/"): return PKG/"src/bid_deep_engine"/p[len("src/bidops/"):]
    if p.startswith("tests/"): return PKG/"engine_tests"/p[len("tests/"):]
seen=set()
for f in meta["files"]:
    p=f["path"]
    dup = p in seen; seen.add(p)
    up = subprocess.run(["git","-C",UP,"show",f"{c}:{p}"],capture_output=True).stdout
    wt = (pathlib.Path(UP)/p).read_bytes()
    vp = vpath(p); v = vp.read_bytes() if vp.exists() else b""
    hu=hashlib.sha256(up).hexdigest(); hv=hashlib.sha256(v).hexdigest()
    claim=f["sha256"]
    norm = re.sub(rb"\bbidops\b(?=[.\s])", b"bid_deep_engine", up)
    norm = norm.replace(b"from tests.", b"from engine_tests.").replace(b"import tests.", b"import engine_tests.")
    same = norm==v
    nd = 0 if same else sum(1 for l in difflib.unified_diff(norm.decode().splitlines(), v.decode().splitlines(), lineterm="", n=0) if l[:1] in "+-" and not l.startswith(("+++","---")))
    print(f"{p:50s} claim==upstream:{claim==hu} claim==vendored:{claim==hv} wt==commit:{wt==up} normalized_identical:{same} difflines:{nd} {'DUP' if dup else ''}")
