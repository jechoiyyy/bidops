"""UPSTREAM.json lists every vendored file exactly once and matches its bytes offline.

`files` record the upstream bytes at the pinned commit, so the check undoes the declared
adaptation and compares with the recorded hash. `replaced_files` and `authored_files`
record the vendored bytes. The upstream repository is not needed.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))
# Declared excerpts cannot be reproduced from the vendored bytes alone.
EXCERPTS = {"src/bidops/analysis/llm.py"}


def _vendored(upstream_path: str) -> str:
    if upstream_path.startswith("src/bidops/"):
        return "src/bid_deep_engine/" + upstream_path[len("src/bidops/") :]
    if upstream_path.startswith("tests/"):
        return "engine_tests/" + upstream_path[len("tests/") :]
    raise AssertionError(f"unexpected upstream path {upstream_path}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _undo_import_rename(data: bytes) -> bytes:
    return (
        data.replace(b"bid_deep_engine", b"bidops")
        .replace(b"from engine_tests.", b"from tests.")
        .replace(b"import engine_tests.", b"import tests.")
    )


def _on_disk() -> list[str]:
    found = []
    for folder in ("src", "engine_tests"):
        for path in (ROOT / folder).rglob("*"):
            parts = path.relative_to(ROOT).parts
            if not path.is_file() or "__pycache__" in parts or ".pytest_cache" in parts:
                continue
            if any(part.endswith(".egg-info") for part in parts):
                continue
            found.append("/".join(parts))
    return sorted(found)


def test_every_vendored_file_is_listed_exactly_once():
    listed = (
        [_vendored(f["path"]) for f in MANIFEST["files"]]
        + [f["path"] for f in MANIFEST["replaced_files"]]
        + [f["path"] for f in MANIFEST["authored_files"]]
    )
    assert len(listed) == len(set(listed)), "duplicate manifest entry"
    assert sorted(listed) == _on_disk()


def test_upstream_entries_reproduce_the_recorded_upstream_hash():
    excerpts = set()
    for entry in MANIFEST["files"]:
        data = (ROOT / _vendored(entry["path"])).read_bytes()
        adaptation = entry["adaptation"]
        if adaptation.startswith("excerpt"):
            excerpts.add(entry["path"])
            continue
        for local, upstream in entry.get("local_replacements", []):
            assert data.count(local.encode()) == 1, (entry["path"], local)
            data = data.replace(local.encode(), upstream.encode())
        if adaptation == "none":
            restored = data
        else:
            assert adaptation == "import rename", (entry["path"], adaptation)
            restored = _undo_import_rename(data)
        assert _sha(restored) == entry["sha256"], entry["path"]
    assert excerpts == EXCERPTS


def test_replaced_and_authored_entries_record_the_vendored_bytes():
    for entry in MANIFEST["replaced_files"] + MANIFEST["authored_files"]:
        actual = _sha((ROOT / entry["path"]).read_bytes())
        assert actual == entry["sha256"], f"{entry['path']}: update sha256 to {actual}"
    for entry in MANIFEST["replaced_files"]:
        assert _vendored(entry["upstream_path"]) == entry["path"]
