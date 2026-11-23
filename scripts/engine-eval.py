#!/usr/bin/env python3
"""Evaluate the vendored analysis engine against a fixed human gold set (outside the product).

Precedent: ``scripts/score-c2-gate.py`` and ``scripts/rl-gold.py``. This tool never touches a
database, object storage or the product's run tables, and it does not change the engine
runner, which keeps failing closed for anything but ``mock_reference``. It imports the engine
package from ``--engine-src`` (default: this checkout) so two engine trees can be measured
with the same frozen inputs (A/B).

Everything it reads and writes lives in one evaluation directory outside Git:

    cases.json                      case list (see ``prepare``)
    structure/<name>.json           BidOps document structure of each original
    gold/<case_id>.gold.v1.json     human-confirmed answer key (``bidops.engine-eval-gold.v1``)
    inputs/<case_id>.input.json     frozen ``bidops.engine-input.v1`` envelope (written once)
    runs/<label>/<case_id>/r<n>/    one engine run: artifacts, call ledger, prompts, responses
    scores/<label>.score.v1.json    scoring result

Commands
    prepare   build the frozen inputs (company evidence frozen per case, see ``_freeze_company``)
    plan      print, per case, the calls a live run would make and their sizes; calls no model
    run       run the engine; ``--mode mock`` calls no model, ``--mode live`` needs ``--approval``
    score     compare one label's runs with the gold

Live runs send the RFP text and the frozen company evidence to codex-exec ``gpt-6-luna``/high,
the single RL model identity. They fail closed unless an approval file names the model, the
cases and a call cap, and the cap counts every call already recorded in the evaluation
directory. Prompts and responses are written mode 0600 inside the run directory and nowhere
else; stdout carries only identifiers, counts and hashes.

Run with Python 3.12 and the engine's dependencies, for example:

    uv run --python 3.12 --with 'pydantic>=2.7,<3' --with 'PyYAML>=6,<7' \
        scripts/engine-eval.py run --eval-dir <dir> --label base --mode mock
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ENGINE_SRC = REPO / "packages" / "bid-deep-engine" / "src"
MODEL = "gpt-6-luna"
EFFORT = "high"
INPUT_SCHEMA = "bidops.engine-input.v1"
GOLD_SCHEMA = "bidops.engine-eval-gold.v1"
SCORE_SCHEMA = "bidops.engine-eval-score.v1"
APPROVAL_SCHEMA = "bidops.engine-eval-approval.v1"
CALL_TIMEOUT_SECONDS = 1800
PASSES = ("extract", "match", "synth")


class EvalError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_private(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def engine_digest(src: Path) -> str:
    """One hash over every packaged Python and prompt file: the A/B identity of an engine tree."""
    digest = hashlib.sha256()
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.suffix in {".py", ".md"})
    if not files:
        raise EvalError(f"engine source not found: {src}")
    for path in files:
        digest.update(path.relative_to(src).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha(path.read_bytes()).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------- prepare


def _freeze_company(source: dict, case: dict) -> tuple[dict, list[dict], list[str]]:
    """Company evidence as of the case, in the shape the product hands the engine.

    Mirrors ``company_knowledge._profile_v2_payload`` (one fact per non-evidence node) and the
    graph node list. Project nodes whose ``value.year`` is at or after
    ``drop_project_year_from`` and the ids in ``drop_node_ids`` are removed so the case's own
    contract, and work won after the notice, cannot leak into the input.
    """
    year_from = case.get("drop_project_year_from")
    drop_ids = set(case.get("drop_node_ids", []))
    kept, dropped = [], []
    for node in source["nodes"]:
        value = node.get("value")
        year = value.get("year") if isinstance(value, dict) else None
        if node["id"] in drop_ids or (
            node.get("type") == "project" and year_from is not None and isinstance(year, int) and year >= year_from
        ):
            dropped.append(node["id"])
            continue
        kept.append(node)
    facts = []
    for node in sorted(kept, key=lambda item: item["id"]):
        if node.get("type") == "evidence":
            continue
        refs = node.get("source_refs") or []
        quote = "" if node.get("status") == "unknown" or not refs else refs[0].get("quote", "")
        facts.append(
            {
                "fact_key": node["id"],
                "status": node.get("status"),
                "value": node.get("value"),
                "section_id": node.get("type"),
                "section_number": None,
                "locator": {"fact_key": node["id"]},
                "quote": quote,
                "origin": node.get("origin"),
            }
        )
    payload = {"schema": "bidops.company-profile.v2", "facts": facts, "parse_errors": []}
    return payload, kept, sorted(dropped)


_PORTFOLIO_LINK = re.compile(r"\[\[(P\d{4}-\d{2})(?:\|[^\]]*)?\]\]")


def _freeze_bundle(bundle: dict, case: dict) -> tuple[dict, list[str]]:
    """The original company files and wiki as of the case (input v2).

    A portfolio item is removed when its title is the case's own notice, when its known
    ``period.start`` is after ``as_of``, or when its id year is at or after
    ``drop_project_year_from``. Removed items leave the portfolio file, the provenance
    sidecar and the wiki: their pages are dropped, wiki lines that carry a removed item's
    title or its shortened name are deleted, and remaining mentions of a removed id are taken
    out of the wiki and of profile comments. Sentences that other pages derived from those
    bids without naming them cannot be found this way; that residue is recorded with the input.
    """
    import yaml  # noqa: PLC0415 - only this command needs it

    profile = yaml.safe_load(bundle["files"][bundle["profile_file"]])
    portfolio_name = profile["portfolio_file"]
    provenance_name = profile.get("provenance_file")
    year_from = case.get("drop_project_year_from")
    as_of = case.get("as_of")

    def squash(text) -> str:
        return "".join(str(text).split())

    def short_key(text) -> str:
        """The name people use when they shorten a title: leading year dropped, first distinctive words."""
        words = [w for w in str(text).split() if not re.fullmatch(r"(?:19|20)\d{2}년?(?:[~·-](?:19|20)?\d{2,4}년?)?", w)]
        key = ""
        for word in words:
            key += word
            if len(key) >= 5:
                break
        return key if len(key) >= 5 else ""

    title = squash(case["title"])
    kept, dropped, titles = [], [], []
    for item in yaml.safe_load(bundle["files"][portfolio_name]) or []:
        start = str((item.get("period") or {}).get("start", "unknown"))
        late = as_of is not None and start != "unknown" and start[:10] > as_of[: len(start[:10])]
        if squash(item.get("title", "")) == title or late or (year_from is not None and int(item["id"][1:5]) >= year_from):
            dropped.append(item["id"])
            titles.append(squash(item.get("title", "")))
        else:
            kept.append(item)
    files = dict(bundle["files"])
    files[portfolio_name] = yaml.safe_dump(kept, allow_unicode=True, sort_keys=False)
    if provenance_name and provenance_name in files:
        sidecar = yaml.safe_load(files[provenance_name])
        sidecar["fields"] = {
            key: value
            for key, value in sidecar.get("fields", {}).items()
            if not any(key.startswith(f"portfolio[{pid}]") for pid in dropped)
        }
        files[provenance_name] = yaml.safe_dump(sidecar, allow_unicode=True, sort_keys=False)
    gone = set(dropped)
    names = [t for t in titles if len(t) >= 8]
    # Shortened names ("2024 맞춤배움길"): a removed item's short key deletes the line outright
    # when no kept item shares it; when a kept item shares it (an earlier year of the same
    # service) only lines that also carry a removed item's year go.
    kept_keys = {short_key(item.get("title", "")) for item in kept}
    dropped_items = [i for i in yaml.safe_load(bundle["files"][portfolio_name]) or [] if i["id"] in gone]
    solo_keys = {k for k in (short_key(i.get("title", "")) for i in dropped_items) if k and k not in kept_keys}
    shared = {}
    for item in dropped_items:
        key = short_key(item.get("title", ""))
        if key and key in kept_keys:
            years = set(re.findall(r"(?:19|20)\d{2}", str(item.get("title", "")))) | {item["id"][1:5]}
            shared.setdefault(key, set()).update(years)
    mention = re.compile(r"\s*[·,]?\s*(?:\[\[)?(P\d{4}-\d{2})(?:\|[^\]]*)?(?:\]\])?")

    def strip_ids(text: str) -> str:
        text = mention.sub(lambda m: "" if m[1] in gone else m[0], text)
        text = text.replace("``", "")
        return re.sub(r":\s*·\s*", ": ", text)

    def leaks(line: str) -> bool:
        flat = squash(line)
        if any(name in flat for name in names) or any(key in flat for key in solo_keys):
            return True
        return any(key in flat and any(year in line for year in years) for key, years in shared.items())

    pages = {}
    for rel, text in bundle["knowledge"].items():
        if rel.startswith("portfolio/") and rel[len("portfolio/") : -len(".md")] in gone:
            continue
        in_front, fences, lines = False, 0, []
        for line in text.split("\n"):
            if line.strip() == "---" and fences < 2:
                fences += 1
                in_front = fences == 1
                lines.append(line)
                continue
            if not in_front and leaks(line):
                continue
            lines.append(strip_ids(line))
        pages[rel] = "\n".join(lines)
    # Profile comments may name removed items; values are left alone so the YAML stays valid.
    profile_lines = []
    for line in files[bundle["profile_file"]].split("\n"):
        head, sep, comment = line.partition(" #")
        profile_lines.append(head + sep + strip_ids(comment) if sep else line)
    files[bundle["profile_file"]] = "\n".join(profile_lines)
    return {"profile_file": bundle["profile_file"], "files": files, "knowledge": pages}, dropped


def cmd_prepare(args) -> int:
    root = Path(args.eval_dir)
    config = _read_json(root / "cases.json")
    if args.input_version == "v2":
        out_dir = args.inputs if args.inputs != "inputs" else "inputs-v2"
        return _prepare_v2(root, config, Path(args.engine_src).resolve(), out_dir)
    source_path = Path(config["company_source"])
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    for case in config["cases"]:
        out = root / "inputs" / f"{case['case_id']}.input.json"
        if out.exists():
            print(f"{case['case_id']} exists sha256={_sha(out.read_bytes())[:16]} (kept)")
            continue
        structure_path = root / case["structure"]
        structure_bytes = structure_path.read_bytes()
        structure = json.loads(structure_bytes)
        document_id = structure["document_version_id"]
        blocks = [
            {
                "document_version_id": document_id,
                "block_key": b["block_key"],
                "text": b["text"],
                "page": b["page"],
                "type": b["type"],
                "attributes": b["attributes"],
            }
            for b in structure["blocks"]
        ]
        profile_payload, nodes, dropped = _freeze_company(source, case)
        frozen = {
            "schema_version": INPUT_SCHEMA,
            "mode": "mock_reference",
            "slug": case["case_id"],
            "title": case["title"],
            "company_name": source["company"]["name"],
            "profile_sha256": _sha(_canonical(profile_payload)),
            "profile_payload": profile_payload,
            "graph_nodes": nodes,
            "documents": [
                {
                    "document_version_id": document_id,
                    "source_sha256": structure["source_sha256"],
                    "structure_sha256": _sha(structure_bytes),
                }
            ],
            "primary_format": case.get("primary_format", "hwp"),
            "blocks": blocks,
            "evaluation": {
                "case_id": case["case_id"],
                "as_of": case.get("as_of"),
                "company_source_sha256": _sha(source_bytes),
                "dropped_company_nodes": dropped,
            },
        }
        data = json.dumps(frozen, ensure_ascii=False).encode("utf-8")
        _write_private(out, data, exclusive=True)
        print(
            f"{case['case_id']} written sha256={_sha(data)[:16]} blocks={len(blocks)} "
            f"facts={len(profile_payload['facts'])} dropped_company_nodes={len(dropped)}"
        )
    return 0


def _prepare_v2(root: Path, config: dict, engine_src: Path, out_dir: str) -> int:
    """``inputs-v2/<case>.input.json``: the v1 document part with the frozen company bundle."""
    sys.path.insert(0, str(engine_src))
    from bid_deep_engine import adapter  # noqa: PLC0415

    where = config["company_bundle"]
    source = adapter.read_company_bundle(where["dir"], where["slug"])
    for case in config["cases"]:
        out = root / out_dir / f"{case['case_id']}.input.json"
        if out.exists():
            print(f"{case['case_id']} exists sha256={_sha(out.read_bytes())[:16]} (kept)")
            continue
        base = _read_json(root / "inputs" / f"{case['case_id']}.input.json")
        bundle, dropped = _freeze_bundle(source, case)
        bundle["bundle_sha256"] = adapter.company_bundle_sha256(bundle)
        frozen = {k: v for k, v in base.items() if k not in ("profile_payload", "graph_nodes", "evaluation")}
        frozen["schema_version"] = "bidops.engine-input.v2"
        frozen["company_bundle"] = bundle
        frozen["evaluation"] = {
            "case_id": case["case_id"],
            "as_of": case.get("as_of"),
            "company_bundle_source_sha256": source["bundle_sha256"],
            "dropped_portfolio_ids": dropped,
            "freeze_limit": "wiki text derived from the dropped bids in other pages is not rewritten",
        }
        with tempfile.TemporaryDirectory(prefix="engine-eval-") as folder:
            company = adapter.company_inputs(frozen, folder)  # the frozen bundle must still load
        _write_private(out, json.dumps(frozen, ensure_ascii=False).encode("utf-8"), exclusive=True)
        print(
            f"{case['case_id']} written sha256={_sha(out.read_bytes())[:16]} "
            f"dropped_portfolio={len(dropped)} pages={len(bundle['knowledge'])} "
            f"knowledge_hash={company.record['knowledge_hash'][:16]}"
        )
    return 0


# ---------------------------------------------------------------- engine access


def _load_engine(src: Path):
    sys.path.insert(0, str(src))
    import bid_deep_engine.runner as runner  # noqa: PLC0415
    from bid_deep_engine.analysis import llm, pipeline  # noqa: PLC0415
    from bid_deep_engine.analysis.pricing import TokenUsage  # noqa: PLC0415

    return runner, llm, pipeline, TokenUsage


def _json_object_text(text: str) -> str | None:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else None


class _CallBudget:
    """Counts model calls across the whole evaluation directory against the approved cap."""

    def __init__(self, root: Path, approval: dict):
        self.root = root
        self.cap = approval["max_calls"]

    def used(self) -> int:
        return sum(1 for _ in self.root.glob("runs/*/*/r*/calls/*.call.json"))

    def take(self) -> None:
        if self.used() >= self.cap:
            raise EvalError("approved call cap reached")


class RecordingTransport:
    """Shared call bookkeeping. Subclasses implement ``_complete(prompt) -> str``."""

    phase = "analyze"
    fallbacks = False

    def __init__(self, llm, token_usage, run_dir: Path, *, dry: bool = False):
        self._llm = llm
        self._usage = token_usage
        self.run_dir = run_dir
        self.run_id = run_dir.name
        self.dry = dry
        self.index = 0

    def count_tokens(self, **kwargs) -> int:
        return sum(len(str(v)) for v in kwargs.values()) // 2

    def _complete(self, prompt: str) -> str:
        raise NotImplementedError

    def _before_call(self) -> None:
        """Refuse before anything about the call is written."""

    def served_model(self) -> str:
        return MODEL

    def parse(self, output_model, *, purpose, system, document, instruction, slug, **kwargs):
        schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False)
        prompt = (
            f"{system}\n\n# 문서\n\n{document}\n\n# 지시\n\n{instruction}\n\n# 출력 형식\n\n"
            f"아래 JSON Schema를 따르는 JSON 객체 하나만 출력한다. 설명, 머리말, 코드 펜스를 붙이지 않는다.\n\n{schema}\n"
        )
        self._before_call()
        self.index += 1
        stem = f"{self.index:02d}-{purpose}"
        calls = self.run_dir / "calls"
        _write_private(calls / f"{stem}.prompt.txt", prompt.encode("utf-8"))
        started = time.monotonic()
        try:
            text = self._complete(prompt)
        except EvalError:
            raise
        except Exception as exc:  # transport failure: nothing was received
            self._ledger(stem, purpose, prompt, None, "call_failed", started, type(exc).__name__)
            raise self._llm.LlmCallError(f"transport failed: {type(exc).__name__}") from None
        _write_private(calls / f"{stem}.response.txt", text.encode("utf-8"))
        record = self._record(purpose, started)
        body = _json_object_text(text)
        if body is None:
            self._ledger(stem, purpose, prompt, text, "no_json", started, None)
            raise self._llm.LlmOutputError(
                slug, purpose, record=record,
                failure=self._llm.OutputFailure(
                    response_text=text or None, json_text=None, validation_errors=[], error_count=0,
                    kind="no_json" if text else "no_text",
                ),
            )
        try:
            value = output_model.model_validate_json(body)
        except Exception as exc:
            errors = getattr(exc, "errors", lambda: [])()
            self._ledger(stem, purpose, prompt, text, "schema_invalid", started, None, len(errors))
            raise self._llm.LlmOutputError(
                slug, purpose, record=record,
                failure=self._llm.OutputFailure(
                    response_text=text, json_text=body,
                    validation_errors=[
                        {"loc": ".".join(str(p) for p in e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
                        for e in errors[:20]
                    ],
                    error_count=len(errors), kind="validation",
                ),
            ) from None
        self._ledger(stem, purpose, prompt, text, "ok", started, None)
        return self._llm.ParseResult(value, self._usage(), self.served_model(), "end_turn", record)

    def _record(self, purpose, started):
        return self._llm.CallRecord(
            at=datetime.now(UTC).isoformat(timespec="seconds"), purpose=purpose, model=MODEL,
            served_model=self.served_model(), price_model=None, cost_basis="subscription",
            stop_reason="end_turn", input_tokens=0, output_tokens=0, cache_read_input_tokens=0,
            cache_creation_5m=0, cache_creation_1h=0, input_tokens_counted=0, estimate_usd=None,
            cost_usd=0.0, duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _ledger(self, stem, purpose, prompt, response, outcome, started, error_class, error_count=None):
        entry = {
            "purpose": purpose,
            "outcome": outcome,
            "served_model": self.served_model(),
            "prompt_chars": len(prompt),
            "prompt_sha256": _sha(prompt.encode("utf-8")),
            "response_chars": None if response is None else len(response),
            "response_sha256": None if response is None else _sha(response.encode("utf-8")),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error_class": error_class,
            "validation_error_count": error_count,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _write_private(self.run_dir / "calls" / f"{stem}.call.json", json.dumps(entry, indent=1).encode("utf-8"))


WIKI_SEARCH_HEADER = """[작업 방식 — 먼저 읽는다]
이 작업 폴더의 `knowledge/`에 회사 위키가 파일로 있다. 아래 지시문에 `## 회사 지식(발췌)`가 있으면, 답하기 전에 반드시 셸 명령으로 위키를 찾아 읽는다.
- 먼저 `cat knowledge/INDEX.md`와 해당 공고 유형의 `knowledge/categories/*.md`를 읽는다.
- 평가 대상 요구사항을 비슷한 것끼리 묶고, 묶음마다 핵심어로 `grep -rl "핵심어" knowledge/portfolio knowledge/capabilities`를 돌린 뒤 나온 페이지의 `수행한 요구 범위`·`기술 환경` 절을 읽는다. 검색은 묶음 수만큼, 적어도 열 번 이상 한다.
- 프로필의 실적 제목만 보고 판정하지 않는다. 판정 근거는 실제로 읽은 페이지에서 찾는다.
- 지시문에 회사 지식 항목이 없으면(추출 단계) 위키를 읽지 않는다.

"""
WIKI_SEARCH_FOOTER = """
[다시 확인] 회사 지식 항목이 있는 작업이면 `knowledge/`를 실제로 검색해 읽은 뒤에 답한다. 마지막 메시지는 JSON 객체 하나뿐이어야 한다.
"""


class CodexLunaTransport(RecordingTransport):
    """codex-exec ``gpt-6-luna``/high in an empty read-only working directory."""

    def __init__(self, llm, token_usage, run_dir, *, codex_bin: str, budget: _CallBudget, workspace_pages=None):
        super().__init__(llm, token_usage, run_dir)
        self.codex_bin = codex_bin
        self.budget = budget
        # With --wiki-workspace the case's frozen wiki pages are placed in the read-only
        # working directory as knowledge/<rel>, so the model can search them itself.
        self.workspace_pages = workspace_pages
        self.trace_path: Path | None = None

    def _before_call(self) -> None:
        self.budget.take()

    def _complete(self, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="engine-eval-codex-") as folder:
            out = Path(folder) / "last-message.txt"
            for rel, text in (self.workspace_pages or {}).items():
                page = Path(folder) / "knowledge" / rel
                page.parent.mkdir(parents=True, exist_ok=True)
                page.write_text(text, encoding="utf-8")
            command = [
                self.codex_bin, "exec", "-m", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"',
                "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "-C", folder,
                "-o", str(out),
            ]
            if self.workspace_pages:
                # Search mode: the model must look the wiki up itself, and the event stream is
                # kept (private, in the run directory) to count the commands it really ran.
                prompt = WIKI_SEARCH_HEADER + prompt + WIKI_SEARCH_FOOTER
                command.append("--json")
            command.append("-")
            done = subprocess.run(  # noqa: S603 - fixed argv, prompt on stdin
                command, input=prompt.encode("utf-8"), stdout=subprocess.PIPE if self.workspace_pages else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=CALL_TIMEOUT_SECONDS, check=False,
            )
            if self.workspace_pages:
                trace = self.run_dir / "calls" / f"{self.index:02d}.trace.jsonl"
                _write_private(trace, done.stdout or b"")
            if done.returncode != 0 or not out.exists():
                raise RuntimeError("codex_exec_failed")
            return out.read_text(encoding="utf-8")


def _mock_client(runner, rfp):
    return runner.MockTransport(rfp)


def _run_engine(engine, payload: dict, run_dir: Path, client_for):
    """The body of ``runner.execute`` with a caller-supplied client. The runner is not changed."""
    runner, llm, pipeline, token_usage = engine
    blocks, tables = runner.raw_blocks(payload)
    fmt = payload["primary_format"]
    raw = runner.RawDoc(
        slug=payload["slug"], format=fmt, source_paths=[], blocks=blocks, tables=tables,
        meta=runner.RawMeta(
            chars=sum(len(b.text) for b in blocks),
            digits=sum(sum(c.isdigit() for c in b.text) for b in blocks),
            paragraphs=len(blocks), tables=len(tables),
            extractor="rhwp" if fmt == "hwp" else "hwpx-lxml" if fmt == "hwpx" else "pypdf",
            extractor_version="bidops-structure.v1",
        ),
    )
    bundle = runner.NoticeBundle(
        slug=payload["slug"], title=payload["title"], manifest_matched=False, files=[],
        primary_format=fmt, status="degraded", created_at=datetime.now(UTC).isoformat(),
        warnings=["structure_projection_partial"],
    )
    rfp = runner.build(bundle, raw, None)
    client = client_for(rfp)
    work = run_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    extra = {}
    if hasattr(runner, "company_inputs"):
        company = runner.company_inputs(payload, work)
        profile, company_hash, record = company.profile, company.company_input_hash, company.record
        extra = {"knowledge": company.knowledge, "portfolio_texts": company.portfolio_texts}
    else:  # engine trees from before input v2
        profile, projected = runner.project_company(payload)
        company_hash = runner.engine_company_input_hash(profile)
        record = {"mapped_fields": projected, "complete": False}
    source = work / "rfp.json"
    output = work / "analysis"
    _write_private(source, rfp.model_dump_json().encode("utf-8"))
    _write_private(work / "bundle.json", bundle.model_dump_json().encode("utf-8"))
    result = pipeline.run_notice(
        source, output, client_factory=lambda: client, profile=profile, model=getattr(client, "model_name", MODEL),
        strategy="single", effort=EFFORT, passes=PASSES, force=True, company_input_hash=company_hash,
        run_id=payload["slug"], transport=getattr(client, "transport_name", "engine_eval"), **extra,
    )
    analysis_path = output / "analysis.json"
    analysis = _read_json(analysis_path) if analysis_path.exists() else None
    if analysis is not None:
        analysis["source_evidence"] = runner.source_evidence(analysis, payload, sections=rfp.sections)
        _write_private(run_dir / "analysis.json", json.dumps(analysis, ensure_ascii=False).encode("utf-8"))
    return {
        "status": result.status,
        "cause_class": type(result.cause).__name__ if getattr(result, "cause", None) is not None else None,
        "warnings": list(result.warnings),
        "requirements": len(rfp.requirements),
        "sections": len(rfp.sections),
        "company_mapped_fields": sum(len(m["fields"]) for m in record["mapped_fields"]),
        "company_source": record.get("source", "projection"),
        "knowledge": (analysis or {}).get("knowledge"),
        "analysis": analysis is not None,
    }


def _check_approval(path: Path | None, cases: list[str]) -> dict:
    if path is None:
        raise EvalError("live mode requires --approval")
    approval = _read_json(path)
    if (
        approval.get("schema") != APPROVAL_SCHEMA
        or approval.get("model") != MODEL
        or approval.get("reasoning_effort") != EFFORT
        or not approval.get("approved_by")
        or not approval.get("approved_at")
        or type(approval.get("max_calls")) is not int
        or approval["max_calls"] < 1
    ):
        raise EvalError("approval file is not valid for this model identity")
    missing = [c for c in cases if c not in approval.get("cases", [])]
    if missing:
        raise EvalError(f"cases not covered by the approval: {', '.join(missing)}")
    return approval


def _selected_cases(root: Path, wanted: list[str] | None) -> list[str]:
    known = [c["case_id"] for c in _read_json(root / "cases.json")["cases"]]
    if wanted:
        unknown = [c for c in wanted if c not in known]
        if unknown:
            raise EvalError(f"unknown case: {', '.join(unknown)}")
        return wanted
    return known


def cmd_run(args) -> int:
    root = Path(args.eval_dir)
    src = Path(args.engine_src).resolve()
    cases = _selected_cases(root, args.cases)
    digest = engine_digest(src)
    label_dir = root / "runs" / args.label
    manifest_path = label_dir / "manifest.json"
    manifest = {
        "label": args.label, "mode": args.mode, "inputs": args.inputs, "wiki_workspace": bool(args.wiki_workspace), "engine_src": str(src), "engine_sha256": digest,
        "model": MODEL if args.mode == "live" else "mock_reference", "reasoning_effort": EFFORT,
        "strategy": "single", "passes": list(PASSES),
    }
    if manifest_path.exists():
        previous = _read_json(manifest_path)
        if any(previous.get(k) != manifest[k] for k in ("mode", "engine_sha256", "model", "inputs") if k in previous):
            raise EvalError("label already used with another engine tree or mode; choose a new label")
    else:
        _write_private(manifest_path, json.dumps(manifest, indent=1).encode("utf-8"))
    budget = None
    if args.mode == "live":
        approval = _check_approval(Path(args.approval) if args.approval else None, cases)
        budget = _CallBudget(root, approval)
        print(f"approval by={approval['approved_by']} cap={approval['max_calls']} used={budget.used()}")
    engine = _load_engine(src)
    runner, llm, _, token_usage = engine
    failed = 0
    for case_id in cases:
        input_path = root / args.inputs / f"{case_id}.input.json"
        input_bytes = input_path.read_bytes()
        payload = json.loads(input_bytes)
        for _ in range(args.repeat):
            number = 1
            while (label_dir / case_id / f"r{number}").exists():
                number += 1
            run_dir = label_dir / case_id / f"r{number}"
            run_dir.mkdir(parents=True)
            if args.mode == "mock":
                client_for = lambda rfp: _mock_client(runner, rfp)  # noqa: E731
            else:
                client_for = lambda rfp, d=run_dir: CodexLunaTransport(  # noqa: E731
                    llm, token_usage, d, codex_bin=args.codex_bin, budget=budget,
                    workspace_pages=(payload.get("company_bundle") or {}).get("knowledge") if args.wiki_workspace else None,
                )
            started = time.monotonic()
            try:
                outcome = _run_engine(engine, payload, run_dir, client_for)
            except EvalError as exc:
                # The approved cap ran out mid-run: record the stopped run, then stop everything.
                stopped = {"case_id": case_id, "run": number, "status": "stopped", "cause_class": str(exc),
                           "calls": len(list((run_dir / "calls").glob("*.call.json")))}
                _write_private(run_dir / "outcome.json", json.dumps(stopped, ensure_ascii=False, indent=1).encode("utf-8"))
                raise
            except Exception as exc:
                outcome = {"status": "error", "cause_class": type(exc).__name__, "analysis": False}
            outcome.update(
                {"case_id": case_id, "run": number, "input_sha256": _sha(input_bytes), "engine_sha256": digest,
                 "mode": args.mode, "seconds": round(time.monotonic() - started, 1),
                 "calls": len(list((run_dir / "calls").glob("*.call.json")))}
            )
            _write_private(run_dir / "outcome.json", json.dumps(outcome, ensure_ascii=False, indent=1).encode("utf-8"))
            failed += outcome["status"] in {"failed", "error"}
            print(json.dumps({k: outcome.get(k) for k in ("case_id", "run", "status", "cause_class", "requirements", "calls", "seconds")}, ensure_ascii=False))
    return 1 if failed else 0


class _PlanTransport(RecordingTransport):
    """Records the first call's size and stops; later passes depend on a real answer."""

    def _complete(self, prompt: str) -> str:
        raise RuntimeError("plan_only")


def cmd_plan(args) -> int:
    root = Path(args.eval_dir)
    src = Path(args.engine_src).resolve()
    engine = _load_engine(src)
    runner, llm, _, token_usage = engine
    print(f"engine_sha256={engine_digest(src)[:16]} model={MODEL} effort={EFFORT}")
    for case_id in _selected_cases(root, args.cases):
        payload = _read_json(root / args.inputs / f"{case_id}.input.json")
        with tempfile.TemporaryDirectory(prefix="engine-eval-plan-") as folder:
            run_dir = Path(folder) / "r0"
            run_dir.mkdir()
            outcome = _run_engine(engine, payload, run_dir, lambda rfp, d=run_dir: _PlanTransport(llm, token_usage, d))
            call = next(iter(sorted((run_dir / "calls").glob("*.call.json"))), None)
            first = _read_json(call)["prompt_chars"] if call else None
        company = len(_canonical(payload.get("profile_payload") or payload.get("company_bundle")))
        print(
            f"{case_id}: requirements={outcome.get('requirements')} first_call_prompt_chars={first} "
            f"frozen_company_chars={company} calls_per_run=3 (extract, match, synth; single strategy)"
        )
    return 0


# ---------------------------------------------------------------- score


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _rate(hit: int, total: int):
    return None if total == 0 else round(hit / total, 4)


def _score_run(gold: dict, analysis: dict | None, rfp: dict | None) -> dict:
    """One run against one gold. Rates are ``None`` when the denominator is zero."""
    result: dict = {"analysis_present": analysis is not None}
    gold_reqs = {r["req_id"]: r for r in gold["requirements"]}
    engine_reqs = {r["id"] for r in (rfp or {}).get("requirements", [])}
    found = sorted(set(gold_reqs) & engine_reqs)
    result["requirement_extraction"] = {
        "gold": len(gold_reqs), "engine": len(engine_reqs), "matched": len(found),
        "recall": _rate(len(found), len(gold_reqs)), "precision": _rate(len(found), len(engine_reqs)),
        "missed": sorted(set(gold_reqs) - engine_reqs), "extra": sorted(engine_reqs - set(gold_reqs)),
    }
    fits = {f["req_id"]: f for f in (analysis or {}).get("fits", [])}
    decided = [r for r in gold_reqs.values() if r["expected_fit"] != "UNKNOWN"]
    confusion: dict[str, int] = {}
    agree = agree_decided = false_full = engine_unknown = 0
    for req in gold_reqs.values():
        fit = (fits.get(req["req_id"]) or {}).get("fit", "MISSING")
        confusion[f"{req['expected_fit']}>{fit}"] = confusion.get(f"{req['expected_fit']}>{fit}", 0) + 1
        agree += fit == req["expected_fit"]
        engine_unknown += fit in {"UNKNOWN", "MISSING"}
        if req["expected_fit"] != "UNKNOWN":
            agree_decided += fit == req["expected_fit"]
        if fit == "FULL" and req["expected_fit"] in {"GAP", "UNKNOWN"}:
            false_full += 1
    result["requirement_fit"] = {
        "agreement": _rate(agree, len(gold_reqs)),
        "agreement_on_gold_decided": _rate(agree_decided, len(decided)),
        "gold_decided": len(decided),
        "engine_unknown_or_missing": engine_unknown,
        "full_without_gold_support": false_full,
        "confusion_gold>engine": dict(sorted(confusion.items())),
    }
    gates = (analysis or {}).get("gates", [])
    by_code: dict[str, list[dict]] = {}
    for gate in gates:
        by_code.setdefault(gate.get("code"), []).append(gate)
    status_of = {"met": "PASS", "not_met": "FAIL", "unknown": "UNKNOWN"}
    hit = verdict_ok = blockers = blockers_caught = 0
    rows = []
    for item in gold["eligibility"]:
        candidates = by_code.get(item["code"], [])
        quote = _norm(item["quote"])
        chosen = next(
            (g for g in candidates if quote and (quote in _norm(json.dumps(g, ensure_ascii=False)) )), None
        ) or (candidates[0] if candidates else None)
        verdict = chosen.get("verdict") if chosen else None
        hit += chosen is not None
        expected = status_of[item["company_status"]]
        ok = verdict == expected or (expected == "UNKNOWN" and verdict == "RISK")
        verdict_ok += bool(chosen) and ok
        if item.get("blocking"):
            blockers += 1
            blockers_caught += verdict == "FAIL"
        rows.append({"id": item["id"], "code": item["code"], "gold": expected, "engine": verdict})
    result["eligibility"] = {
        "gold": len(gold["eligibility"]), "found": hit, "recall": _rate(hit, len(gold["eligibility"])),
        "verdict_agreement": _rate(verdict_ok, len(gold["eligibility"])),
        "gold_blockers": blockers, "blockers_caught": blockers_caught,
        "blocker_recall": _rate(blockers_caught, blockers),
        "engine_fail_without_gold_blocker": sum(
            1 for g in gates if g.get("verdict") == "FAIL"
        ) - blockers_caught,
        "rows": rows,
    }
    evidence = (analysis or {}).get("source_evidence", [])
    paths = {e.get("evidence_path") for e in evidence}
    result["evidence"] = {
        "located_quotes": len(paths),
        "exact": len({e.get("evidence_path") for e in evidence if e.get("location_status") == "exact"}),
        "ambiguous": len({e.get("evidence_path") for e in evidence if e.get("location_status") == "ambiguous"}),
    }
    decision = ((analysis or {}).get("recommendation") or {}).get("decision")
    result["decision"] = {
        "gold": gold["decision"]["expected"], "engine": decision,
        "agree": decision == gold["decision"]["expected"],
    }
    return result


def cmd_score(args) -> int:
    root = Path(args.eval_dir)
    label_dir = root / "runs" / args.label
    manifest = _read_json(label_dir / "manifest.json")
    cases = {}
    for case_id in _selected_cases(root, args.cases):
        gold_path = root / "gold" / f"{case_id}.gold.{args.gold_version}.json"
        gold_bytes = gold_path.read_bytes()
        gold = json.loads(gold_bytes)
        if gold.get("schema") != GOLD_SCHEMA:
            raise EvalError(f"{case_id}: unexpected gold schema")
        if gold.get("status") != "confirmed" and not args.allow_draft_gold:
            raise EvalError(f"{case_id}: gold is not confirmed by a person (use --allow-draft-gold for a trial score)")
        runs = []
        for run_dir in sorted((label_dir / case_id).glob("r*"), key=lambda p: int(p.name[1:])):
            analysis_path = run_dir / "analysis.json"
            rfp_path = run_dir / "work" / "rfp.json"
            scored = _score_run(
                gold,
                _read_json(analysis_path) if analysis_path.exists() else None,
                _read_json(rfp_path) if rfp_path.exists() else None,
            )
            scored["run"] = run_dir.name
            scored["outcome"] = _read_json(run_dir / "outcome.json").get("status")
            runs.append(scored)
        cases[case_id] = {"gold_sha256": _sha(gold_bytes), "gold_status": gold.get("status"), "runs": runs}
    report = {
        "schema": SCORE_SCHEMA, "label": args.label, "manifest": manifest,
        "tool_sha256": _sha(Path(__file__).read_bytes()), "cases": cases,
        "decision": None,
    }
    out = root / "scores" / f"{args.label}.score.v1.json"
    _write_private(out, json.dumps(report, ensure_ascii=False, indent=1).encode("utf-8"))
    for case_id, case in cases.items():
        for run in case["runs"]:
            print(json.dumps({
                "case": case_id, "run": run["run"], "outcome": run["outcome"],
                "req_recall": run["requirement_extraction"]["recall"],
                "fit_agreement": run["requirement_fit"]["agreement"],
                "fit_agreement_decided": run["requirement_fit"]["agreement_on_gold_decided"],
                "engine_unknown": run["requirement_fit"]["engine_unknown_or_missing"],
                "elig_recall": run["eligibility"]["recall"],
                "elig_verdict_agreement": run["eligibility"]["verdict_agreement"],
                "blocker_recall": run["eligibility"]["blocker_recall"],
                "decision": f"{run['decision']['gold']}>{run['decision']['engine']}",
            }, ensure_ascii=False))
    print(f"written {out.name} sha256={_sha(out.read_bytes())[:16]}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, engine=True):
        p.add_argument("--eval-dir", required=True)
        p.add_argument("--cases", nargs="*")
        p.add_argument("--inputs", default="inputs", help="input folder under the eval dir (inputs or inputs-v2)")
        if engine:
            p.add_argument("--engine-src", default=str(DEFAULT_ENGINE_SRC))

    prepare = sub.add_parser("prepare")
    common(prepare)
    prepare.add_argument("--input-version", choices=("v1", "v2"), default="v1")
    common(sub.add_parser("plan"))
    run = sub.add_parser("run")
    common(run)
    run.add_argument("--label", required=True)
    run.add_argument("--mode", choices=("mock", "live"), required=True)
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--approval")
    run.add_argument("--codex-bin", default="codex")
    run.add_argument("--wiki-workspace", action="store_true", help="put the case's frozen wiki in the model's read-only working directory")
    score = sub.add_parser("score")
    common(score, engine=False)
    score.add_argument("--label", required=True)
    score.add_argument("--allow-draft-gold", action="store_true")
    score.add_argument("--gold-version", default="v1", help="answer key file version: gold/<case>.gold.<version>.json")
    args = parser.parse_args(argv)
    try:
        return {"prepare": cmd_prepare, "plan": cmd_plan, "run": cmd_run, "score": cmd_score}[args.command](args)
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
