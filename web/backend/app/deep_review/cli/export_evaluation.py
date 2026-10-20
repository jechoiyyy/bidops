"""``export-evaluation``: read-only RL-05 gold acceptance export (cards pack / actual).

``python -m app.deep_review.cli export-evaluation (--cards | --actual) --selection <file>
[--gold <file> --condition-alignment <file>] --out <dir>``

RL-05 spec "루트랩 재명세 차이" adopts the HP-06 contract ("actual·차단 조건 대응
계약") with the Rootlab binding.  Nothing here writes to the database, the object
store, a model or the network: the session is rolled back (and set ``READ ONLY`` on
PostgreSQL) and only new files under ``--out`` are created.

Selection (``bidops.rl-evaluation-selection.v1``): every document entry
``{document_id, notice_id, opportunity_id, source_sha256, structure_id, manifest_id,
title, agency}`` must agree with the database -- the notice is a pre-spec whose
authoritative opportunity is ``opportunity_id``, the structure is ``ready``, belongs
to that notice and carries ``source_sha256``, the manifest belongs to that structure
-- otherwise ``selection_mismatch``.  ``document_id`` becomes a file name, so it is
limited to ``[A-Za-z0-9][A-Za-z0-9._-]{0,127}``.  The document count is not fixed
here (``scripts/rl-gold.py`` enforces 10).

``--cards`` writes the cards pack consumed by ``scripts/rl-gold.py export-cards``:

* ``<document_id>.structure.json`` -- the stored ``DocumentStructure`` payload bytes
  verbatim (``sha256(file) == payload_sha256``; the verified ``structure`` location);
* ``<document_id>.para_page_map.json`` -- the page map bytes of the newest
  ``prespec_v4_pdf_snapshot`` of that structure that has one, verbatim
  (``sha256(file) == para_page_map_sha256``).  **Absent** when no snapshot has a page
  map: the file's absence is the ``null`` ``page_map_sha256``.

No other pack file is written.  The selection's ``company_sha256``/``ontology_sha256``
must be the registered real company's active graph sha and its ontology sha
(``binding_mismatch``).

``--actual`` derives one attempt per document from the selection (no attempts
manifest): among the attempts of company reviews of that notice that have an
approval, the eligible ones have an RL policy identity (``RL_POLICY_IDENTITIES``),
``status=completed`` and ``quality_status=unmeasured_reference``; the newest by
``DeepReviewApproval.approved_at`` (then attempt id, the verdict view order) is
scored.  None → ``missing_attempt``.  The others are only counted per reason
(``policy``·``status``·``quality_status``) in the summary, never scored.
``quality_status`` is the product rule ``quality_status_for_review`` (the review's
creation audit), the value the verdict view shows -- the frozen preview
``provenance_jsonb`` (``FrozenProvenance``) has no quality field.  The scored
attempt's frozen units must all come from the selected source/structure/manifest
(``selection_mismatch``) and its frozen graph/ontology sha must be the selection's
(``binding_mismatch``).  A stored row that disagrees is ``processing_failed``
(the verdict view checks) -- never repaired.

Independence (only with ``--gold``; HP-06 makes ``--gold`` and
``--condition-alignment`` a pair): for each selected notice, an *early* RL review is
a company review with an RL policy identity (any status or quality) whose
``deep_review.created_at`` is not after the gold ``authored_at`` (ISO-8601 with an
offset).  An early review whose first attempt was started by a manual verdict
request (``verdict_request.reason=manual``) means a person ran the model before the
gold was finished → ``gold_after_model``.  Any other early review (automatic start,
the holdout did not hold) → ``holdout_violated``, which wins over ``gold_after_model``.

Outputs (exclusive create, mode 0600, canonical JSON + newline; created files are
removed again if a later write fails):

* without gold/alignment: ``actual.v1.json`` (``bidops.rl-evaluation-actual.v1``,
  HP-06 keys) only -- the input of the human alignment;
* with both: ``actual.v1.json``, ``prediction.v1.json`` (exactly the scorer keys
  ``{company_sha256, ontology_sha256, documents}``) and ``receipt.json``
  (``bidops.rl-evaluation-export-receipt.v1``).  The alignment must name the sha of
  this gold file and of the (deterministic) actual bytes of this run.

An output path inside the git worktree is refused unless git ignores it
(``output_not_ignored``; ``.sdlc/local-runtime/`` is in ``.git/info/exclude``), and
an existing target file is ``output_exists``.

Output: one JSON summary (ids, counts, sha256 -- never document text).  Exit 0 on
success; exit 2 with ``{"error": code}`` for ``usage`` | ``invalid_selection`` |
``invalid_gold`` | ``invalid_alignment`` | ``selection_mismatch`` | ``binding_mismatch``
| ``missing_attempt`` | ``gold_after_model`` | ``holdout_violated`` | ``output_exists``
| ``output_not_ignored``; exit 1 with ``processing_failed`` | ``storage_failed``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...core.db import SessionLocal, init_db
from ...lifecycle.models import Notice
from ..document_mcp.contracts import validate_para_page_map
from ..models import (
    AnalysisPolicyVersion,
    CompanyKnowledgeBinding,
    CompanyKnowledgeVersion,
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentSegmentManifest,
    DocumentStructure,
    DocumentVersion,
    KnowledgeOntologyVersion,
    VerdictRequest,
)
from ..services import assets
from ..services.deep_reviews import quality_status_for_reviews
from ..services.document_segments import latest_para_page_map_snapshot
from ..services.luna_identity import RL_POLICY_IDENTITIES, policy_reasoning_effort
from ..services.transfer_policy import policy_identity_of
from ..services.verdict_trigger import notice_opportunity_id, real_company
from ..services.verdict_view import VerdictViewError, completed_card_attempt

PROG = "python -m app.deep_review.cli export-evaluation"
TOOL_PATH = Path(__file__).resolve()

SCHEMA_SELECTION = "bidops.rl-evaluation-selection.v1"
SCHEMA_GOLD = "bidops.rl-human-gold.v1"
SCHEMA_ALIGNMENT = "bidops.rl-condition-alignment.v1"
SCHEMA_ACTUAL = "bidops.rl-evaluation-actual.v1"
SCHEMA_RECEIPT = "bidops.rl-evaluation-export-receipt.v1"

STRUCTURE_SUFFIX = ".structure.json"
PAGE_MAP_SUFFIX = ".para_page_map.json"
ACTUAL_FILE = "actual.v1.json"
PREDICTION_FILE = "prediction.v1.json"
RECEIPT_FILE = "receipt.json"
#: The scorer's false-positive marker; a gold condition ID may not start with it.
UNMATCHED_PREFIX = "unmatched:"
SCORED_QUALITY = "unmeasured_reference"
MANUAL_REASON = "manual"

_DOCUMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ALIGNMENT_KEYS = {"schema_version", "gold_sha256", "actual_sha256", "annotator", "authored_at", "documents"}

#: Exit 1 codes (storage/stored-row failures); every other code exits 2.
_SERVICE_CODES = frozenset({"processing_failed", "storage_failed"})


class ExportError(Exception):
    """One stable export code; the message never carries document text or paths."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> ExportError:
    return ExportError(code)


# --- small helpers -------------------------------------------------------------------


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _file_bytes(value: Any) -> bytes:
    return _canonical(value) + b"\n"


def _read_json(path: Path, code: str) -> tuple[Any, bytes]:
    def unique(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique), raw
    except (OSError, UnicodeError, ValueError):
        raise _fail(code) from None


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso_with_offset(value: Any, code: str) -> datetime:
    """ISO-8601 date-time carrying a UTC offset (the ``rl-gold.py`` rule); naive is refused."""

    if not isinstance(value, str) or not value:
        raise _fail(code)
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise _fail(code) from None
    if "T" not in normalized.upper() or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fail(code)
    return parsed


def _id_list(value: Any, code: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise _fail(code)
    return list(value)


def _uuid(value: Any, code: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise _fail(code) from None


def sources_sha256(structure_sha256: str, page_map_sha256: str | None) -> str:
    """``scripts/rl-gold.py source_binding`` for the one structure of a selection document."""

    pairs = [{"structure_sha256": structure_sha256, "page_map_sha256": page_map_sha256}]
    pairs.sort(key=lambda pair: (pair["structure_sha256"], pair["page_map_sha256"] or ""))
    return _digest(_canonical(pairs))


# --- output paths ----------------------------------------------------------------------


def _worktree_root() -> Path | None:
    """The git worktree holding this module (``None`` in an image without a checkout)."""

    for parent in TOOL_PATH.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _output_allowed(path: Path) -> None:
    """Refuse an output inside the worktree unless git ignores it (the ``rl-gold.py`` rule)."""

    root = _worktree_root()
    if root is None:
        return
    target = Path(os.path.realpath(path))
    real_root = Path(os.path.realpath(root))
    try:
        relative = target.relative_to(real_root)
    except ValueError:
        return
    try:
        # rc 0 = ignored; 1 = not ignored; anything else (inside .git, no git) fails closed.
        result = subprocess.run(
            ["git", "-C", str(real_root), "check-ignore", "-q", "--", str(relative)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        raise _fail("output_not_ignored") from None
    if result.returncode != 0:
        raise _fail("output_not_ignored")


def _prepare_outputs(directory: Path, names: Sequence[str]) -> list[Path]:
    paths = [directory / name for name in names]
    for path in paths:
        _output_allowed(path)
        if path.exists() or path.is_symlink():
            raise _fail("output_exists")
    return paths


def _write_all(directory: Path, files: Sequence[tuple[str, bytes]]) -> None:
    """Exclusive-create every file (0600); a failure removes the files this call created."""

    created: list[Path] = []
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, data in files:
            path = directory / name
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise _fail("output_exists") from None
            created.append(path)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


# --- selection --------------------------------------------------------------------------


def parse_selection(selection: Any) -> list[dict[str, Any]]:
    """Validated selection documents (``invalid_selection``), in document_id order."""

    if not isinstance(selection, dict) or selection.get("schema_version") != SCHEMA_SELECTION:
        raise _fail("invalid_selection")
    if not _is_sha(selection.get("company_sha256")) or not _is_sha(selection.get("ontology_sha256")):
        raise _fail("invalid_selection")
    if not _non_empty(selection.get("selected_on")):
        raise _fail("invalid_selection")
    rows = selection.get("documents")
    if not isinstance(rows, list) or not rows:
        raise _fail("invalid_selection")
    documents: dict[str, dict[str, Any]] = {}
    notices: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise _fail("invalid_selection")
        document_id = row.get("document_id")
        if not isinstance(document_id, str) or _DOCUMENT_ID.fullmatch(document_id) is None:
            raise _fail("invalid_selection")
        if document_id in documents:
            raise _fail("invalid_selection")
        notice_id, opportunity_id = row.get("notice_id"), row.get("opportunity_id")
        if not _is_int(notice_id) or notice_id < 1 or notice_id in notices:
            raise _fail("invalid_selection")
        if not _is_int(opportunity_id) or opportunity_id < 1:
            raise _fail("invalid_selection")
        if not _is_sha(row.get("source_sha256")):
            raise _fail("invalid_selection")
        structure_id = _uuid(row.get("structure_id"), "invalid_selection")
        manifest_id = _uuid(row.get("manifest_id"), "invalid_selection")
        if not isinstance(row.get("title"), str) or not isinstance(row.get("agency"), str):
            raise _fail("invalid_selection")
        notices.add(notice_id)
        documents[document_id] = {
            "document_id": document_id, "notice_id": notice_id, "opportunity_id": opportunity_id,
            "source_sha256": row["source_sha256"], "structure_id": structure_id, "manifest_id": manifest_id,
        }
    return [documents[key] for key in sorted(documents)]


def _check_document(session: Session, document: Mapping[str, Any]) -> DocumentStructure:
    """The selection entry agrees with the database (``selection_mismatch``)."""

    notice = session.get(Notice, document["notice_id"])
    if notice is None or notice.source_type != "pre_spec":
        raise _fail("selection_mismatch")
    if notice_opportunity_id(session, notice.id) != document["opportunity_id"]:
        raise _fail("selection_mismatch")
    structure = session.get(DocumentStructure, document["structure_id"])
    version = session.get(DocumentVersion, structure.document_version_id) if structure is not None else None
    if (
        structure is None or version is None
        or structure.validation_status != "ready"
        or structure.source_sha256 != document["source_sha256"]
        or version.notice_id != notice.id
    ):
        raise _fail("selection_mismatch")
    manifest = session.get(DocumentSegmentManifest, document["manifest_id"])
    if manifest is None or manifest.structure_id != structure.id or manifest.source_sha256 != structure.source_sha256:
        raise _fail("selection_mismatch")
    return structure


# --- verified object bytes ---------------------------------------------------------------


def _object_bytes(
    session: Session,
    *,
    content_object_id: UUID | None,
    location: ContentObjectLocation | None,
    expected_sha256: str | None,
) -> bytes:
    """Bytes of one pinned ``structure`` object version whose sha/size/etag still match."""

    content = session.get(ContentObject, content_object_id) if content_object_id is not None else None
    if (
        content is None or location is None or not expected_sha256
        or location.content_object_id != content.id
        or location.namespace_key != "structure"
        or location.status != "verified"
        or location.purged_at is not None
        or not location.object_version_id
        or content.sha256 != expected_sha256
    ):
        raise _fail("processing_failed")
    try:
        data, metadata = assets.read_object(
            "structure", location.object_key, max_bytes=max(content.size_bytes, 1),
            version_id=location.object_version_id,
        )
    except assets.AssetError:
        raise _fail("storage_failed") from None
    if (
        metadata.object_version_id != location.object_version_id
        or (location.etag is not None and metadata.etag != location.etag)
        or len(data) != content.size_bytes
        or _digest(data) != expected_sha256
    ):
        raise _fail("processing_failed")
    return data


def _structure_bytes(session: Session, structure: DocumentStructure) -> bytes:
    location = session.scalar(
        select(ContentObjectLocation)
        .where(
            ContentObjectLocation.content_object_id == structure.payload_content_object_id,
            ContentObjectLocation.namespace_key == "structure",
            ContentObjectLocation.status == "verified",
        )
        .order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc())
        .limit(1)
    )
    data = _object_bytes(
        session, content_object_id=structure.payload_content_object_id, location=location,
        expected_sha256=structure.payload_sha256,
    )
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise _fail("processing_failed") from None
    if (
        not isinstance(payload, dict)
        or payload.get("source_sha256") != structure.source_sha256
        or payload.get("structure_id") != str(structure.id)
        or not isinstance(payload.get("blocks"), list)
    ):
        raise _fail("processing_failed")
    return data


def _page_map(session: Session, structure: DocumentStructure) -> tuple[bytes | None, str | None]:
    """``(bytes, sha256)`` of the newest snapshot page map of the structure, or ``(None, None)``."""

    snapshot = latest_para_page_map_snapshot(session, structure.id)
    if snapshot is None:
        return None, None
    location = (
        session.get(ContentObjectLocation, snapshot.para_page_map_location_id)
        if snapshot.para_page_map_location_id is not None else None
    )
    data = _object_bytes(
        session, content_object_id=snapshot.para_page_map_content_object_id, location=location,
        expected_sha256=snapshot.para_page_map_sha256,
    )
    try:
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("page_map_not_object")
        validate_para_page_map(payload)
    except Exception:  # noqa: BLE001 - any unreadable page map fails closed
        raise _fail("processing_failed") from None
    return data, snapshot.para_page_map_sha256


def _page_map_sha256(session: Session, structure: DocumentStructure) -> str | None:
    snapshot = latest_para_page_map_snapshot(session, structure.id)
    return snapshot.para_page_map_sha256 if snapshot is not None else None


# --- --cards ------------------------------------------------------------------------------


def _check_active_binding(session: Session, selection: Mapping[str, Any]) -> None:
    company = real_company(session)
    binding = session.get(CompanyKnowledgeBinding, company.id) if company is not None else None
    graph = session.get(CompanyKnowledgeVersion, binding.graph_version_id) if binding is not None else None
    ontology = session.get(KnowledgeOntologyVersion, graph.ontology_id) if graph is not None else None
    if (
        ontology is None
        or graph.graph_sha256 != selection["company_sha256"]
        or ontology.sha256 != selection["ontology_sha256"]
    ):
        raise _fail("binding_mismatch")


def export_cards(session: Session, selection: Mapping[str, Any]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Pack files ``[(name, bytes)]`` and the document ids without a page map."""

    documents = parse_selection(selection)
    _check_active_binding(session, selection)
    files: list[tuple[str, bytes]] = []
    without_page_map: list[str] = []
    for document in documents:
        structure = _check_document(session, document)
        files.append((f"{document['document_id']}{STRUCTURE_SUFFIX}", _structure_bytes(session, structure)))
        page_map, _sha = _page_map(session, structure)
        if page_map is None:
            without_page_map.append(document["document_id"])
        else:
            files.append((f"{document['document_id']}{PAGE_MAP_SUFFIX}", page_map))
    return files, without_page_map


# --- gold and alignment ----------------------------------------------------------------------


def parse_gold(gold: Any, selection: Mapping[str, Any], documents: Sequence[Mapping[str, Any]]) -> tuple[datetime, dict[str, dict[str, set[str]]]]:
    """``(authored_at, {document_id: {condition_id: source_unit_ids}})`` of a completed gold."""

    if (
        not isinstance(gold, dict)
        or gold.get("schema_version") != SCHEMA_GOLD
        or gold.get("status") != "human_completed"
        or not _non_empty(gold.get("annotator"))
        or gold.get("written_before_model_output") is not True
    ):
        raise _fail("invalid_gold")
    authored_at = _iso_with_offset(gold.get("authored_at"), "invalid_gold")
    if not _is_sha(gold.get("company_sha256")) or not _is_sha(gold.get("ontology_sha256")):
        raise _fail("invalid_gold")
    if any(gold[key] != selection[key] for key in ("company_sha256", "ontology_sha256")):
        raise _fail("selection_mismatch")
    rows = gold.get("documents")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise _fail("invalid_gold")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        document_id = row.get("document_id")
        if not isinstance(document_id, str) or document_id in by_id:
            raise _fail("invalid_gold")
        by_id[document_id] = row
    selected = {document["document_id"]: document for document in documents}
    if set(by_id) != set(selected):
        raise _fail("selection_mismatch")
    conditions: dict[str, dict[str, set[str]]] = {}
    for document_id, row in by_id.items():
        if row.get("source_sha256") != selected[document_id]["source_sha256"]:
            raise _fail("selection_mismatch")
        if not _is_sha(row.get("sources_sha256")):
            raise _fail("invalid_gold")
        # Unwritten ``null`` is not a confirmed-empty ``[]``.
        blocking = row.get("blocking_conditions")
        if not isinstance(blocking, list):
            raise _fail("invalid_gold")
        found: dict[str, set[str]] = {}
        for condition in blocking:
            if not isinstance(condition, dict):
                raise _fail("invalid_gold")
            condition_id = condition.get("condition_id")
            if (
                not isinstance(condition_id, str) or not condition_id
                or condition_id in found or condition_id.startswith(UNMATCHED_PREFIX)
            ):
                raise _fail("invalid_gold")
            source_ids = _id_list(condition.get("source_unit_ids"), "invalid_gold")
            if not source_ids:
                raise _fail("invalid_gold")
            found[condition_id] = set(source_ids)
        conditions[document_id] = found
    return authored_at, conditions


def apply_alignment(
    alignment: Any,
    *,
    gold_sha256: str,
    actual_sha256: str,
    actual_documents: Sequence[Mapping[str, Any]],
    gold_conditions: Mapping[str, Mapping[str, set[str]]],
) -> dict[str, list[str]]:
    """``{document_id: blocking_condition_ids}`` from a validated human alignment (HP-06)."""

    if (
        not isinstance(alignment, dict)
        or set(alignment) != _ALIGNMENT_KEYS
        or alignment["schema_version"] != SCHEMA_ALIGNMENT
        or alignment["gold_sha256"] != gold_sha256
        or alignment["actual_sha256"] != actual_sha256
        or not _non_empty(alignment["annotator"])
    ):
        raise _fail("invalid_alignment")
    _iso_with_offset(alignment["authored_at"], "invalid_alignment")
    rows = alignment["documents"]
    if not isinstance(rows, list):
        raise _fail("invalid_alignment")
    by_id: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"document_id", "mappings"}:
            raise _fail("invalid_alignment")
        if not isinstance(row["document_id"], str) or row["document_id"] in by_id:
            raise _fail("invalid_alignment")
        by_id[row["document_id"]] = row["mappings"]
    actual = {document["document_id"]: document for document in actual_documents}
    if set(by_id) != set(actual):
        raise _fail("invalid_alignment")
    result: dict[str, list[str]] = {}
    for document_id, document in actual.items():
        mappings = by_id[document_id]
        if not isinstance(mappings, list):
            raise _fail("invalid_alignment")
        sources = {row["unit_id"]: set(row["source_unit_ids"]) for row in document["unit_sources"]}
        conditions = gold_conditions[document_id]
        seen: list[str] = []
        gold_ids: set[str] = set()
        unmatched: set[str] = set()
        for mapping in mappings:
            if not isinstance(mapping, dict) or set(mapping) != {"model_unit_id", "gold_condition_ids", "reason"}:
                raise _fail("invalid_alignment")
            unit_id = mapping["model_unit_id"]
            if not isinstance(unit_id, str) or not _non_empty(mapping["reason"]):
                raise _fail("invalid_alignment")
            seen.append(unit_id)
            linked = _id_list(mapping["gold_condition_ids"], "invalid_alignment")
            for condition_id in linked:
                # The gold condition exists in this document and shares at least one
                # source unit with the model unit; overlap alone never links anything.
                if condition_id not in conditions or not (conditions[condition_id] & sources.get(unit_id, set())):
                    raise _fail("invalid_alignment")
            if linked:
                gold_ids.update(linked)
            else:
                unmatched.add(f"{UNMATCHED_PREFIX}{unit_id}")
        # Every model blocking unit exactly once; a missing mapping is unwritten.
        if sorted(seen) != sorted(document["blocking_units"]) or len(seen) != len(set(seen)):
            raise _fail("invalid_alignment")
        result[document_id] = sorted(gold_ids | unmatched)
    return result


# --- --actual -------------------------------------------------------------------------------


def _rl_reviews(session: Session, notice_id: int) -> list[tuple[DeepReview, str | None]]:
    """Company reviews of the notice with an RL policy identity (any status), with that identity."""

    rows = session.execute(
        select(DeepReview, AnalysisPolicyVersion)
        .join(AnalysisPolicyVersion, AnalysisPolicyVersion.id == DeepReview.policy_version_id)
        .where(DeepReview.notice_id == int(notice_id), DeepReview.company_id.is_not(None))
    ).all()
    return [(review, policy_identity_of(policy)) for review, policy in rows]


def check_independence(session: Session, notice_id: int, authored_at: datetime) -> str | None:
    """``holdout_violated`` | ``gold_after_model`` | ``None`` for one selected notice."""

    early = [
        review for review, identity in _rl_reviews(session, notice_id)
        if identity in RL_POLICY_IDENTITIES and not authored_at < _aware(review.created_at)
    ]
    if not early:
        return None
    manual = set(session.scalars(select(VerdictRequest.started_attempt_id).where(
        VerdictRequest.notice_id == int(notice_id),
        VerdictRequest.reason == MANUAL_REASON,
        VerdictRequest.started_attempt_id.is_not(None),
    )).all())
    for review in early:
        first = session.scalar(
            select(DeepReviewAttempt.id)
            .where(DeepReviewAttempt.deep_review_id == review.id)
            .order_by(DeepReviewAttempt.sequence.asc())
            .limit(1)
        )
        if first is None or first not in manual:
            return "holdout_violated"
    return "gold_after_model"


def select_attempt(session: Session, notice_id: int) -> tuple[DeepReviewAttempt | None, dict[str, int]]:
    """The scored attempt of the notice (or None) and the excluded attempt counts per reason."""

    reviews = _rl_reviews(session, notice_id)
    identities = {review.id: identity for review, identity in reviews}
    quality = quality_status_for_reviews(session, list(identities))
    excluded = {"policy": 0, "status": 0, "quality_status": 0}
    if not identities:
        return None, excluded
    rows = session.execute(
        select(DeepReviewAttempt, DeepReviewApproval.approved_at)
        .join(DeepReviewApproval, DeepReviewApproval.attempt_id == DeepReviewAttempt.id)
        .where(DeepReviewAttempt.deep_review_id.in_(list(identities)))
    ).all()
    eligible: list[tuple[datetime, str, DeepReviewAttempt]] = []
    for attempt, approved_at in rows:
        if identities[attempt.deep_review_id] not in RL_POLICY_IDENTITIES:
            excluded["policy"] += 1
        elif attempt.status != "completed":
            excluded["status"] += 1
        elif quality.get(attempt.deep_review_id) != SCORED_QUALITY:
            excluded["quality_status"] += 1
        else:
            eligible.append((_aware(approved_at), str(attempt.id), attempt))
    if not eligible:
        return None, excluded
    return max(eligible, key=lambda row: (row[0], row[1]))[2], excluded


def _actual_document(
    session: Session,
    document: Mapping[str, Any],
    structure: DocumentStructure,
    attempt: DeepReviewAttempt,
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    """HP-06 actual row of the scored attempt (stored values, never recomputed)."""

    try:
        completed = completed_card_attempt(session, attempt.id)
    except VerdictViewError:
        raise _fail("processing_failed") from None
    review = session.get(DeepReview, attempt.deep_review_id)
    policy = session.get(AnalysisPolicyVersion, review.policy_version_id) if review is not None else None
    preview = session.scalar(
        select(DeepReviewPreview)
        .join(DeepReviewApproval, DeepReviewApproval.preview_id == DeepReviewPreview.id)
        .where(DeepReviewApproval.attempt_id == attempt.id)
    )
    provenance = preview.provenance_jsonb if preview is not None else None
    if policy is None or not isinstance(provenance, Mapping):
        raise _fail("processing_failed")
    card = completed.card
    expected_source = (document["source_sha256"], document["structure_id"], document["manifest_id"])
    if not card.units or {(unit.source_sha256, unit.structure_id, unit.manifest_id) for unit in card.units} != {expected_source}:
        raise _fail("selection_mismatch")
    if (
        provenance.get("graph_sha256") != selection["company_sha256"]
        or provenance.get("ontology_sha256") != selection["ontology_sha256"]
    ):
        raise _fail("binding_mismatch")

    result = completed.result
    matrix = {row["unit_id"]: row for row in result["matrix"]}
    compare = {item.unit_id: item for item in completed.compare_items}
    unit_sources: list[dict[str, Any]] = []
    content_ids: dict[str, list[str]] = {}
    for unit in card.units:
        if unit.kind == "card":
            owned, with_text = [unit.unit_id], [unit.unit_id]
        else:
            owned = [f"block:{unit.source_sha256}:{block.block_key}" for block in unit.blocks]
            # The gold universe has only blocks with text (rl-gold.py export-cards).
            with_text = [
                f"block:{unit.source_sha256}:{block.block_key}" for block in unit.blocks if block.text.strip()
            ]
        unit_sources.append({"unit_id": unit.unit_id, "source_unit_ids": owned})
        content_ids[unit.unit_id] = with_text

    def referenced(status: str) -> list[str]:
        ids: list[str] = []
        for unit in card.units:
            if matrix[unit.unit_id]["fit_status"] == status:
                ids.extend(item for item in content_ids[unit.unit_id] if item not in ids)
        return ids

    decisions = []
    for unit in card.units:
        extract = completed.extract_items.get(unit.unit_id)
        compared = compare.get(unit.unit_id)
        decisions.append({
            "unit_id": unit.unit_id,
            "normalized_requirement": extract.normalized_requirement if extract is not None else None,
            "mandatory": extract.mandatory if extract is not None else None,
            "fit_status": matrix[unit.unit_id]["fit_status"],
            "reason_codes": list(compared.reason_codes) if compared is not None else [],
            "evidence_refs": [ref.model_dump(mode="json") for ref in extract.evidence] if extract is not None else [],
        })
    payload = policy.validation_rules.get("policy_snapshot") if isinstance(policy.validation_rules, Mapping) else None
    execution = payload.get("execution") if isinstance(payload, Mapping) else None
    return {
        "document_id": document["document_id"],
        "source_sha256": document["source_sha256"],
        "sources_sha256": sources_sha256(structure.payload_sha256, _page_map_sha256(session, structure)),
        "attempt_id": str(attempt.id),
        "policy_id": policy_identity_of(policy),
        "policy_sha256": provenance.get("policy_sha256"),
        "model": provenance.get("model_name"),
        "reasoning_effort": policy_reasoning_effort(policy),
        "cli_version": execution.get("cli_version") if isinstance(execution, Mapping) else None,
        "quality_status": SCORED_QUALITY,
        "status": attempt.status,
        "verdict": result["verdict"],
        "met": referenced("met"),
        "gap": referenced("gap"),
        "card_states": [
            {"unit_id": unit.unit_id, "status": matrix[unit.unit_id]["fit_status"]}
            for unit in card.units if unit.kind == "card"
        ],
        "blocking_units": list(result["blocking_condition_ids"]),
        "unit_sources": unit_sources,
        "unit_decisions": decisions,
    }


def export_actual(
    session: Session,
    selection: Mapping[str, Any],
    selection_raw: bytes,
    *,
    gold: Any = None,
    gold_raw: bytes | None = None,
    alignment: Any = None,
    alignment_raw: bytes | None = None,
) -> tuple[list[tuple[str, bytes]], dict[str, Any]]:
    """Output files and the safe summary of ``--actual``."""

    documents = parse_selection(selection)
    structures = {document["document_id"]: _check_document(session, document) for document in documents}
    with_gold = gold is not None
    gold_conditions: dict[str, dict[str, set[str]]] = {}
    if with_gold:
        authored_at, gold_conditions = parse_gold(gold, selection, documents)
        verdicts = [check_independence(session, document["notice_id"], authored_at) for document in documents]
        for code in ("holdout_violated", "gold_after_model"):
            if code in verdicts:
                raise _fail(code)
    chosen: dict[str, DeepReviewAttempt] = {}
    excluded: dict[str, dict[str, int]] = {}
    for document in documents:
        attempt, counts = select_attempt(session, document["notice_id"])
        excluded[document["document_id"]] = counts
        if attempt is None:
            raise _fail("missing_attempt")
        chosen[document["document_id"]] = attempt
    rows = [
        _actual_document(session, document, structures[document["document_id"]], chosen[document["document_id"]],
                         selection)
        for document in documents
    ]
    if with_gold:
        # The gold was written against the cards pack of the same structures/page maps.
        gold_sources = {item["document_id"]: item["sources_sha256"] for item in gold["documents"]}
        if any(row["sources_sha256"] != gold_sources[row["document_id"]] for row in rows):
            raise _fail("binding_mismatch")
    tool_sha256 = _digest(TOOL_PATH.read_bytes())
    selection_sha256 = _digest(selection_raw)
    actual = {
        "schema_version": SCHEMA_ACTUAL,
        "company_sha256": selection["company_sha256"],
        "ontology_sha256": selection["ontology_sha256"],
        "selection_sha256": selection_sha256,
        "documents": rows,
        "export_tool_sha256": tool_sha256,
    }
    actual_bytes = _file_bytes(actual)
    actual_sha256 = _digest(actual_bytes)
    files: list[tuple[str, bytes]] = [(ACTUAL_FILE, actual_bytes)]
    summary: dict[str, Any] = {
        "mode": "actual", "documents": len(rows), "independence_checked": with_gold,
        "attempt_ids": {row["document_id"]: row["attempt_id"] for row in rows},
        "excluded_attempts": excluded, "actual_sha256": actual_sha256,
        "prediction_sha256": None, "receipt_sha256": None,
    }
    if not with_gold:
        return files, summary
    assert gold_raw is not None and alignment_raw is not None
    gold_sha256 = _digest(gold_raw)
    blocking = apply_alignment(
        alignment, gold_sha256=gold_sha256, actual_sha256=actual_sha256, actual_documents=rows,
        gold_conditions=gold_conditions,
    )
    prediction = {
        "company_sha256": selection["company_sha256"],
        "ontology_sha256": selection["ontology_sha256"],
        "documents": [
            {
                "document_id": row["document_id"], "source_sha256": row["source_sha256"],
                "sources_sha256": row["sources_sha256"], "verdict": row["verdict"],
                "met": row["met"], "gap": row["gap"], "card_states": row["card_states"],
                "blocking_condition_ids": blocking[row["document_id"]],
            }
            for row in rows
        ],
    }
    prediction_bytes = _file_bytes(prediction)
    receipt = {
        "schema_version": SCHEMA_RECEIPT,
        "gold_sha256": gold_sha256,
        "actual_sha256": actual_sha256,
        "alignment_sha256": _digest(alignment_raw),
        "prediction_sha256": _digest(prediction_bytes),
        "tool_sha256": tool_sha256,
        "selection_sha256": selection_sha256,
    }
    receipt_bytes = _file_bytes(receipt)
    files += [(PREDICTION_FILE, prediction_bytes), (RECEIPT_FILE, receipt_bytes)]
    summary["prediction_sha256"] = receipt["prediction_sha256"]
    summary["receipt_sha256"] = _digest(receipt_bytes)
    return files, summary


# --- CLI -------------------------------------------------------------------------------------


class _QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: ARG002 - never echo argv values
        _emit({"error": "usage"})
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = _QuietParser(prog=PROG)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cards", action="store_true")
    mode.add_argument("--actual", action="store_true")
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--gold", type=Path, default=None)
    parser.add_argument("--condition-alignment", type=Path, default=None)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _read_only(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cards and (args.gold is not None or args.condition_alignment is not None):
        parser.error("--gold/--condition-alignment are only valid with --actual")
    if (args.gold is None) != (args.condition_alignment is None):
        parser.error("--gold and --condition-alignment go together")
    try:
        selection, selection_raw = _read_json(args.selection, "invalid_selection")
        gold = gold_raw = alignment = alignment_raw = None
        if args.gold is not None:
            gold, gold_raw = _read_json(args.gold, "invalid_gold")
            alignment, alignment_raw = _read_json(args.condition_alignment, "invalid_alignment")
        init_db()
        with SessionLocal() as session:
            try:
                _read_only(session)
                if args.cards:
                    files, without_page_map = export_cards(session, selection)
                    summary = {
                        "mode": "cards",
                        "documents": sum(name.endswith(STRUCTURE_SUFFIX) for name, _data in files),
                        "without_page_map": without_page_map,
                    }
                else:
                    files, summary = export_actual(
                        session, selection, selection_raw, gold=gold, gold_raw=gold_raw,
                        alignment=alignment, alignment_raw=alignment_raw,
                    )
            finally:
                session.rollback()
        _prepare_outputs(args.out, [name for name, _data in files])
        _write_all(args.out, files)
        summary["files"] = [name for name, _data in files]
        _emit(summary)
        return 0
    except ExportError as error:
        _emit({"error": error.code})
        print(error.code, file=sys.stderr)
        return 1 if error.code in _SERVICE_CODES else 2
    except Exception:  # keep SQL, paths, settings and document text outside the CLI
        _emit({"error": "storage_failed"})
        print("storage_failed", file=sys.stderr)
        return 1


__all__ = [
    "ExportError",
    "apply_alignment",
    "build_parser",
    "check_independence",
    "export_actual",
    "export_cards",
    "main",
    "parse_gold",
    "parse_selection",
    "select_attempt",
    "sources_sha256",
]
