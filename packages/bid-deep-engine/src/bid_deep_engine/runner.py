"""Versioned stdin/stdout boundary: deterministic mock transport and the framed live mode.

The upstream normalizer, three-pass pipeline, gates, scoring, quote verification,
and readiness logic execute unchanged. No upstream live transport is packaged: in
`--live-ipc` mode every model call leaves this process only as a frame to the BidOps
supervisor (`live.ipc`), which owns the network request and the key (ADR-0081).

Input v1 projects BidOps company facts; input v2 carries the engine's own company files
and knowledge tree, which are loaded and used as upstream does (`adapter.company_inputs`).
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from .analysis.pipeline import run_notice
from .analysis.llm import CallRecord, ParseResult, LlmCallError
from .analysis.pricing import TokenUsage
from .analysis.schemas import (
    RfpFacts,
    EligibilityRule,
    Project,
    Evidence,
    MatchOut,
    RequirementFitOut,
    SynthOut,
    Profitability,
)
from .adapter import (
    INPUT_V1,
    INPUT_V2,
    INPUT_V3,
    EngineError,
    company_inputs,
    project_company,
    source_evidence,
    raw_blocks,
)
from .company.knowledge import prepare_knowledge
from .company.provenance import CompanyEvidenceView
from .company.schema import CompanyProfile, Company
from .ingest.models import Block, RawDoc, RawMeta, NoticeBundle
from .ingest.normalize import build
from .live import ipc as live_ipc, responses as live_responses

VERSION = "bid-deep-engine.v1"
MAX_INPUT = 8 * 1024 * 1024
# Every error_code this process can emit. The consumer rejects any other value.
ERROR_CODES = frozenset(
    {
        "engine_live_not_approved",
        "structure_unavailable",
        "invalid_table_coordinates",
        "table_too_large",
        "input_too_large",
        "engine_input_invalid",
        "engine_pipeline_failed",
        "company_bundle_invalid",
    }
)
LIVE_MODE = "live"
# Upper bound of calls for one notice with the single strategy: extract, units (+1 repair), match,
# synth. Without a work-unit map the units stage does not run.
PLANNED_CALLS_WITH_UNITS = 5
PLANNED_CALLS_WITHOUT_UNITS = 3


@dataclass(frozen=True)
class MockRule:
    """One scripted eligibility rule: an exact source quote the mock reports under `code`.

    `section_id` pins the section the mock cites; otherwise it cites the first section
    whose text contains the quote. A quote absent from the document yields no rule.
    """

    code: str
    quote: str
    section_id: str | None = None


class MockTransport:
    """No generated facts: unknown qualifications, fits and numeric fields stay unknown.

    By default the mock infers no eligibility rule at all. Tests that need the real gate
    path pass explicit `MockRule`s; nothing in product code keys on a document sentence.
    """

    run_id = "mock_reference"
    phase = "analyze"
    fallbacks = False

    def __init__(self, rfp, rules=()):
        self.rfp = rfp
        self.rules = tuple(rules)

    def count_tokens(self, **kwargs):
        return 1

    def _eligibility(self):
        found = []
        for rule in self.rules:
            sections = [
                s
                for s in self.rfp.sections
                if rule.quote in s.text
                and (rule.section_id is None or s.id == rule.section_id)
            ]
            if sections:
                found.append(
                    EligibilityRule(
                        code=rule.code,
                        text=rule.quote,
                        evidence=Evidence(quote=rule.quote, section_id=sections[0].id),
                    )
                )
        return found

    def parse(self, output_model, *, purpose, **kwargs):
        if purpose == "extract":
            section = next((s for s in self.rfp.sections if s.text.strip()), None)
            quote = section.text.strip().splitlines()[-1][:100] if section else ""
            value = RfpFacts(
                eligibility=self._eligibility(),
                project=Project(
                    evidence=[Evidence(quote=quote, section_id=section.id)]
                    if quote
                    else []
                ),
            )
        elif purpose == "units":
            value = output_model(assignments=[])
        elif purpose == "match":
            value = MatchOut(
                fits=[
                    RequirementFitOut(
                        req_id=r.id,
                        fit="UNKNOWN",
                        rationale="모의 응답: 적합성 미측정",
                        evidence=Evidence(
                            quote=r.details[:100] or r.name, section_id=r.section_id
                        ),
                    )
                    for r in self.rfp.requirements
                ]
            )
        elif purpose == "synth":
            value = SynthOut(
                profitability=Profitability(note="모의 응답: 사업성 미측정"),
                summary="모의 참조 실행입니다. 실제 분석 품질과 참여 판단은 미측정입니다.",
            )
        else:
            raise LlmCallError("unsupported_mock_stage")
        value = output_model.model_validate(value.model_dump(mode="json"))
        record = CallRecord(
            at=datetime.now(UTC).isoformat(),
            purpose=purpose,
            model="mock_reference",
            served_model="mock_reference",
            price_model=None,
            cost_basis="exact",
            stop_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_5m=0,
            cache_creation_1h=0,
            input_tokens_counted=0,
            estimate_usd=0,
            cost_usd=0,
            duration_ms=0,
        )
        return ParseResult(value, TokenUsage(), "mock_reference", "end_turn", record)


def engine_company_input_hash(profile):
    """The company fingerprint the engine's readiness recomputes for this profile.

    `pipeline` wraps a bare profile in `CompanyEvidenceView(profile)` and compares every
    stage stamp with `CompanyEvidenceView.company_input_hash`. Passing any other value
    (for example BidOps' `profile_sha256`) marks every fresh stage stale.
    """
    if isinstance(profile, CompanyEvidenceView):
        # Input v2 already carries the provenance sidecar; its own fingerprint applies.
        return profile.company_input_hash
    return CompanyEvidenceView(profile).company_input_hash


def document_from_blocks(payload):
    """Normalize structured input without running analysis or accessing company data."""
    blocks, tables = raw_blocks(payload)
    if not blocks or not any(b.text.strip() for b in blocks):
        raise EngineError("structure_unavailable")
    fmt = payload["primary_format"]
    raw = RawDoc(
        slug=payload["slug"],
        format=fmt,
        source_paths=[],
        blocks=blocks,
        tables=tables,
        meta=RawMeta(
            chars=sum(len(b.text) for b in blocks),
            digits=sum(sum(c.isdigit() for c in b.text) for b in blocks),
            paragraphs=len(blocks),
            tables=len(tables),
            extractor="rhwp"
            if fmt == "hwp"
            else "hwpx-lxml"
            if fmt == "hwpx"
            else "pypdf",
            extractor_version="bidops-structure.v1",
        ),
    )
    bundle = NoticeBundle(
        slug=payload["slug"],
        title=payload["title"],
        manifest_matched=False,
        files=[],
        primary_format=fmt,
        status="degraded",
        created_at=datetime.now(UTC).isoformat(),
        warnings=["structure_projection_partial"],
    )
    return bundle, build(bundle, raw, None)


def _pipeline(payload, client_for, *, model, transport):
    """Run the upstream pipeline once with `client_for(rfp)`; returns (company, rfp, result, artifacts)."""
    bundle, rfp = document_from_blocks(payload)
    client = client_for(rfp)
    with tempfile.TemporaryDirectory(prefix="bid-deep-engine-") as folder:
        root = Path(folder)
        # v1: the BidOps profile stays frozen in the payload and only the conservative
        # projection reaches the engine. v2/v3: the bundled company files are used as they are.
        company = company_inputs(payload, root)
        source = root / "rfp.json"
        output = root / "analysis"
        source.write_text(rfp.model_dump_json(), encoding="utf-8")
        # The facts stage fingerprints rfp.json together with the bundle.json beside
        # it (`provenance.rfp_input_payload`); without it the facts stamp is dropped
        # and readiness reports the stage as unknown legacy metadata.
        (root / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
        result = run_notice(
            source,
            output,
            client_factory=lambda: client,
            profile=company.profile,
            model=model,
            strategy="single",
            effort="high",
            passes=("extract", "match", "synth"),
            force=True,
            company_input_hash=engine_company_input_hash(company.profile),
            knowledge=company.knowledge,
            portfolio_texts=company.portfolio_texts,
            run_id=payload["slug"],
            transport=transport,
        )
        artifacts = {p.name: json.loads(p.read_text()) for p in output.glob("*.json")}
    analysis = artifacts.get("analysis.json")
    if analysis is not None:
        analysis["source_evidence"] = source_evidence(analysis, payload, sections=rfp.sections)
        analysis["company_projection"] = company.record
    return company, rfp, result, artifacts


def execute(payload, *, mock_rules=()):
    """Run the pipeline once. `mock_rules` is for tests only; `main` never passes it."""
    if (
        payload.get("schema_version") not in (INPUT_V1, INPUT_V2, INPUT_V3)
        or payload.get("mode") != "mock_reference"
    ):
        raise EngineError("engine_live_not_approved")
    company, _, result, artifacts = _pipeline(
        payload, lambda rfp: MockTransport(rfp, mock_rules), model="mock_reference", transport="mock_reference",
    )
    failed = result.status == "failed"
    return {
        "schema_version": "bidops.engine-output.v1",
        "engine_version": VERSION,
        "quality_status": "mock_reference",
        "status": "failed" if failed else "partial",
        "error_code": "engine_pipeline_failed" if failed else None,
        # Exception class name only; the upstream reason text may quote the source.
        "error_class": type(result.cause).__name__
        if failed and result.cause is not None
        else None,
        "warnings": [
            "mock_reference_not_quality_evidence",
            *(
                []
                if company.record["complete"]
                else ["company_profile_projection_incomplete"]
            ),
            "structure_projection_partial",
            *result.warnings,
        ],
        "analysis": artifacts.get("analysis.json"),
        "artifacts": artifacts,
    }


def execute_live(payload, reader, writer):
    """Live run over frames (ADR-0081). Only wiki-scoped input v3 with `mode=live` is accepted."""
    if payload.get("schema_version") != INPUT_V3 or payload.get("mode") != LIVE_MODE:
        raise EngineError("engine_live_not_approved")
    client = live_ipc.FrameTransport(reader, writer, run_id=payload["slug"])
    company, _, result, artifacts = _pipeline(
        payload, lambda rfp: client, model=live_responses.MODEL, transport=live_responses.TRANSPORT,
    )
    analysis = artifacts.get("analysis.json")
    failed = result.status == "failed" or analysis is None
    return {
        "schema_version": "bidops.engine-output.v1",
        "engine_version": VERSION,
        "quality_status": "unmeasured_reference",
        "status": "failed" if failed else "completed",
        "error_code": "engine_pipeline_failed" if failed else None,
        "error_class": type(result.cause).__name__
        if failed and result.cause is not None
        else None,
        "warnings": [
            *([] if company.record["complete"] else ["company_profile_projection_incomplete"]),
            "structure_projection_partial",
            *result.warnings,
        ],
        "analysis": analysis,
        "artifacts": artifacts,
        "calls": client.seq,
    }


def plan_live(payload):
    """Planned call bound and the exact first request of a live run, without any model call."""
    plan = live_ipc.FirstRequestPlan()
    company, rfp, _, _ = _pipeline(
        payload, lambda rfp: plan, model=live_responses.MODEL, transport=live_responses.TRANSPORT,
    )
    if plan.first is None or plan.first_purpose != "extract":
        raise EngineError("engine_pipeline_failed")
    units = bool(rfp.requirements) and company.knowledge is not None and _has_work_unit_map(company.knowledge)
    return {
        "planned_calls": PLANNED_CALLS_WITH_UNITS if units else PLANNED_CALLS_WITHOUT_UNITS,
        "first_request_sha256": live_responses.body_sha256(plan.first),
        "first_request_chars": len(live_responses.canonical(plan.first).decode("utf-8")),
        "wire_version": live_responses.WIRE_VERSION,
        "transport": live_responses.TRANSPORT,
        "model": live_responses.MODEL,
        "reasoning_effort": live_responses.EFFORT,
        "endpoint": live_responses.RESPONSES_URL,
    }


def _has_work_unit_map(knowledge):
    from .analysis.workunits import parse_work_unit_map

    return parse_work_unit_map(knowledge) is not None


def preview(payload):
    """Return local input metadata using the engine's loader and selection pipeline.

    For `mode=live` the preview also carries the live plan (`plan_live`), so the approval binds the
    exact first request and the call bound before anything is sent.
    """
    if payload.get("schema_version") != INPUT_V3 or payload.get("mode") not in ("mock_reference", LIVE_MODE):
        raise EngineError("engine_live_not_approved")
    with tempfile.TemporaryDirectory(prefix="bid-deep-engine-preview-") as folder:
        company = company_inputs(payload, Path(folder))
        sections = []
        pages = []
        skipped = []
        chars = 0
        if "blocks" in payload:
            _, rfp = document_from_blocks(payload)
            sections = [
                section.model_dump(include={"id", "heading", "page_start", "page_end"})
                for section in rfp.sections
            ]
            if company.knowledge is not None:
                selection, rendered = prepare_knowledge(rfp, company.knowledge)
                pages, skipped, chars = selection.pages, selection.skipped, len(rendered)
        result = {
            "schema_version": "bidops.engine-preview.v1",
            "company_name": company.profile.profile.company.name,
            "sections": sections,
            "wiki_pages": pages,
            "wiki_pages_skipped": skipped,
            "wiki_chars": chars,
        }
    if payload.get("mode") == LIVE_MODE and "blocks" in payload:
        result["live"] = plan_live(payload)
    return result


def failure(code, error_class=None):
    """A failed envelope that carries only a defined code and an exception class name."""
    return {
        "schema_version": "bidops.engine-output.v1",
        "engine_version": VERSION,
        "quality_status": "mock_reference",
        "status": "failed",
        "error_code": code,
        "error_class": error_class,
        "warnings": [],
        "analysis": None,
        "artifacts": {},
    }


def _live_main():
    """`--live-ipc`: payload is the first stdin line; frames follow on the same pipes.

    The original stdout descriptor is kept for frames and fd 1 is pointed at stderr, so nothing
    the pipeline prints can be mistaken for a frame.
    """
    frames_out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    reader = sys.stdin
    try:
        line = reader.readline(MAX_INPUT + 1)
        if len(line) > MAX_INPUT:
            raise EngineError("input_too_large")
        try:
            payload = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EngineError("engine_input_invalid") from None
        if not isinstance(payload, dict):
            raise EngineError("engine_input_invalid")
        result = execute_live(payload, reader, frames_out)
    except EngineError as exc:
        code = exc.code if exc.code in ERROR_CODES else "engine_pipeline_failed"
        result = {**failure(code, type(exc).__name__), "quality_status": "unmeasured_reference"}
    except Exception as exc:
        result = {**failure("engine_pipeline_failed", type(exc).__name__), "quality_status": "unmeasured_reference"}
    frames_out.write(json.dumps({"frame": "result", "output": result}, ensure_ascii=False) + "\n")
    frames_out.flush()


def main():
    # Source/model contents, exception messages and local paths are never emitted.
    if sys.argv[1:] == ["--live-ipc"]:
        _live_main()
        return
    try:
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(data) > MAX_INPUT:
            raise EngineError("input_too_large")
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EngineError("engine_input_invalid") from None
        if not isinstance(payload, dict):
            raise EngineError("engine_input_invalid")
        result = preview(payload) if sys.argv[1:] == ["--preview"] else execute(payload)
    except EngineError as exc:
        code = exc.code if exc.code in ERROR_CODES else "engine_pipeline_failed"
        result = failure(code, type(exc).__name__)
    except Exception as exc:
        result = failure("engine_pipeline_failed", type(exc).__name__)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
