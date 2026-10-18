"""RL-04 per-section frozen input, Luna transfer payload and its guard (spec "생성 입력·정책·호출").

One ``bidops.proposal-input.v1`` object is frozen per section run.  It is read
only from the completed RL-03 card-v1 verdict attempt (spec "입력 읽기 경로"):

* units: the approved preview ``input_snapshot.card_analysis.units``, verbatim;
* unit type (기술·기능·…) and Compare: the validated ``card_analysis_stage``
  ``extract``/``compare`` rows;
* verdict and checklist: the HP-04 projection of the ``synthesis`` row
  (``verdict_view.completed_card_attempt`` -- the verdict view's own code).

Section selection (spec "절과 목차 대응"; ``SECTION_TOC`` is the §5 heading list):

=================  =====================================================  ==========================
section            units                                                  company facts
=================  =====================================================  ==========================
overview           segment units with an overview/schedule/budget area   none
track_record       none                                                   ``project:*``, ``cert:*``
strategy           units whose extract type is 기술·기능·보안              facts their compares reference
requirements       every card unit                                        facts their compares reference
operations_sla     units whose extract type is 운영·성능SLA·보안·계약       facts their compares reference
organization       none                                                   ``staff:*``
=================  =====================================================  ==========================

``compares`` are the Compare rows of the selected units.  Company facts follow
2026-10-17 interview D2: ``confirmed`` facts carry ``{fact_key, type, label,
value}`` (value without prompt-sensitive metadata keys, as RL-03 sends it);
``proposed``/``unknown`` facts are ``missing_facts`` ``{fact_key, status}``
only -- never a value or label.  Notes, operational ids and model/policy
identity never enter the input's transfer part.

The Luna payload is exactly the eight keys of ``PROPOSAL_TRANSFER_KEYS``; the
identity/operational keys stay in the frozen input only (``input_sha256``
target).  ``check_proposal_transfer_payload`` recomputes every part from the
verdict sources and fails closed with ``company_input_invalid`` (the RL-03
payload guard code) before any call.

Nothing here writes, enqueues or calls a model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ...core.model_binding import canonical_json_bytes
from ...core.model_client import sanitize_for_prompt
from ..contracts import SchemaValidationError, load_schema, validate_payload
from ..schemas.card_analysis import (
    CardAnalysisInput,
    CardRequirementCompare,
    CardRequirementExtract,
)
from .company_analysis_input import (
    CARD_FORBIDDEN_TRANSFER_KEYS,
    CARD_WITHHELD_FACT_KEYS,
    COMPANY_ANALYSIS_INPUT_V2_KEYS,
    COMPANY_ANALYSIS_INPUT_V2_SCHEMA,
    _without_prompt_sensitive_keys,
)
from .input_versions import PROPOSAL_PROMPT_MAX_CHARACTERS, PROPOSAL_SECTION_KEYS, canonical_json_hash
from .luna_identity import MODEL, REASONING_EFFORT


KST = ZoneInfo("Asia/Seoul")
PROPOSAL_INPUT_SCHEMA_VERSION = "bidops.proposal-input.v1"
#: Contract short name of ``bidops.proposal-input.v1.json``.
_INPUT_CONTRACT = "proposal-input"
#: The only keys of the Luna payload (spec; 2026-10-17 interview D2).
PROPOSAL_TRANSFER_KEYS = (
    "section_key", "notice_meta", "units", "compares", "verdict", "company_facts", "missing_facts",
    "toc_reference",
)
#: Frozen-only identity/operational keys (never sent).
PROPOSAL_IDENTITY_KEYS = (
    "schema_version", "purpose", "execution_nonce", "draft_id", "opportunity_id", "notice_id",
    "verdict_attempt_id", "verdict_input_sha256", "company_binding", "policy_sha256", "model_name",
    "reasoning_effort",
)
NOTICE_META_KEYS = ("title", "agency", "deadline_at", "method", "estimated_price")
COMPANY_FACT_KEYS = frozenset({"fact_key", "type", "label", "value"})
MISSING_FACT_KEYS = frozenset({"fact_key", "status"})
MISSING_FACT_STATUSES = frozenset({"proposed", "unknown"})
#: §5 heading(s) each section answers (spec "절과 목차 대응", bid-procedure §5).
SECTION_TOC: dict[str, tuple[str, ...]] = {
    "overview": ("Ⅰ 제안개요: 배경·목적·범위·특징·기대효과",),
    "track_record": ("Ⅱ-3 사업수행 실적", "Ⅱ-4 주요사업·기술"),
    "strategy": ("Ⅲ-1 수행 전략", "Ⅲ-5 제약(접근성·호환성·표준프레임워크)"),
    "requirements": ("Ⅲ-2 기능 요구사항별 수행 방안",),
    "operations_sla": ("Ⅲ-3 운영·유지관리", "Ⅲ-4 보안", "Ⅴ 지원"),
    "organization": ("Ⅳ-2 수행조직(인력 수치 제외)", "Ⅳ-3 보고·산출물"),
}
_OVERVIEW_AREAS = frozenset({"overview", "schedule", "budget"})
_UNIT_TYPES_BY_SECTION: dict[str, frozenset[str]] = {
    "strategy": frozenset({"기술", "기능", "보안"}),
    "operations_sla": frozenset({"운영", "성능SLA", "보안", "계약"}),
}
_FACT_PREFIXES_BY_SECTION: dict[str, tuple[str, ...]] = {
    "track_record": ("project:", "cert:"),
    "organization": ("staff:",),
}
_COMPARE_FACT_SECTIONS = frozenset({"strategy", "requirements", "operations_sla"})
#: RL-03 forbidden keys plus the RL-04 frozen-only identity keys.
PROPOSAL_FORBIDDEN_TRANSFER_KEYS = CARD_FORBIDDEN_TRANSFER_KEYS | frozenset({
    "draft_id", "opportunity_id", "verdict_attempt_id", "verdict_input_sha256", "section_id", "purpose",
})
#: Frozen card-input identity values that never appear in a payload (RL-03 list).
_FROZEN_FORBIDDEN_VALUE_KEYS = (
    "policy_version_id", "policy_sha256", "generation_config_sha256", "graph_version_id",
    "graph_sha256", "profile_version_id", "profile_sha256", "ontology_sha256", "company_id",
    "execution_nonce", "target_review_id", "bundle_id", "model_name", "model_revision",
)
_MIN_WITHHELD_TEXT = 4
_COMPANY_FACT_MARKERS = frozenset({"status", "origin", "label", "type", "profile_evidence_id"})


class ProposalInputError(ValueError):
    """Stable, source-free code: ``verdict_required`` | ``company_input_invalid`` |
    ``input_budget_exceeded`` | ``processing_failed``."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _invalid() -> ProposalInputError:
    return ProposalInputError("company_input_invalid")


@dataclass(frozen=True)
class VerdictSources:
    """Validated reads of one completed card-v1 verdict attempt (spec "입력 읽기 경로")."""

    attempt_id: UUID
    notice_id: int
    #: The approved preview ``input_snapshot`` (``bidops.company-analysis-input.v2``).
    frozen: Mapping[str, Any]
    #: ``deep_review_preview.input_sha256`` of that snapshot.
    verdict_input_sha256: str
    #: Extract ``type`` per unit id (units without an extract row have none).
    unit_types: Mapping[str, str]
    #: Compare row (JSON) per unit id.
    compares: Mapping[str, dict[str, Any]]
    #: ``{verdict, reason, checklist}`` of the HP-04 synthesis projection.
    verdict: Mapping[str, Any]


def _frozen_card_input(frozen: Any) -> Mapping[str, Any]:
    if (
        not isinstance(frozen, Mapping)
        or frozen.get("schema_version") != COMPANY_ANALYSIS_INPUT_V2_SCHEMA
        or set(frozen) != COMPANY_ANALYSIS_INPUT_V2_KEYS
        or not isinstance(frozen.get("card_analysis"), Mapping)
    ):
        raise _invalid()
    return frozen


def verdict_sources(
    *,
    attempt_id: UUID,
    notice_id: int,
    frozen: Mapping[str, Any],
    verdict_input_sha256: str,
    extract_payloads: Sequence[Mapping[str, Any]],
    compare_payloads: Sequence[Mapping[str, Any]],
    verdict: Mapping[str, Any],
) -> VerdictSources:
    """Build sources from already-read rows (strict DTO validation; no DB)."""

    frozen = _frozen_card_input(frozen)
    try:
        CardAnalysisInput.model_validate(frozen["card_analysis"])
        extract_items = [item for payload in extract_payloads
                         for item in CardRequirementExtract.model_validate(payload).items]
        compare_items = [item for payload in compare_payloads
                         for item in CardRequirementCompare.model_validate(payload).items]
    except (TypeError, ValueError):
        raise _invalid() from None
    projected = {key: deepcopy(verdict.get(key)) for key in ("verdict", "reason", "checklist")}
    return _sources(attempt_id, notice_id, frozen, verdict_input_sha256, extract_items, compare_items, projected)


def _sources(
    attempt_id: UUID,
    notice_id: int,
    frozen: Mapping[str, Any],
    verdict_input_sha256: str,
    extract_items: Iterable[Any],
    compare_items: Iterable[Any],
    verdict: Mapping[str, Any],
) -> VerdictSources:
    unit_types: dict[str, str] = {}
    for item in extract_items:
        if item.unit_id in unit_types:
            raise _invalid()
        unit_types[item.unit_id] = item.type
    compares: dict[str, dict[str, Any]] = {}
    for item in compare_items:
        if item.unit_id in compares:
            raise _invalid()
        compares[item.unit_id] = item.model_dump(mode="json")
    known = {row.get("unit_id") for row in frozen["card_analysis"].get("units", []) if isinstance(row, Mapping)}
    if not set(unit_types) <= known or not set(compares) <= known:
        raise _invalid()
    if set(verdict) != {"verdict", "reason", "checklist"}:
        raise _invalid()
    return VerdictSources(
        attempt_id=attempt_id, notice_id=int(notice_id), frozen=frozen,
        verdict_input_sha256=verdict_input_sha256, unit_types=unit_types, compares=compares,
        verdict=dict(verdict),
    )


def load_verdict_sources(session: Session, attempt_id: UUID) -> VerdictSources:
    """Read the completed card-v1 attempt through the verdict view's own reader.

    ``verdict_required``: no completed card-v1 attempt with that id.
    ``processing_failed``: the stored preview/stage rows disagree (not repaired).
    """

    from .verdict_view import VerdictViewError, completed_card_attempt

    try:
        attempt = completed_card_attempt(session, attempt_id)
    except VerdictViewError as error:
        raise ProposalInputError("verdict_required" if error.code == "not_found" else "processing_failed") from None
    final = attempt.result
    verdict = {"verdict": final["verdict"], "reason": final["reason"], "checklist": deepcopy(final["checklist"])}
    return _sources(
        attempt.attempt_id, attempt.notice_id, _frozen_card_input(attempt.frozen), attempt.input_sha256,
        attempt.extract_items.values(), attempt.compare_items, verdict,
    )


# --- notice meta --------------------------------------------------------------------------


def _price_text(value: Any) -> str | None:
    if value is None:
        return None
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def notice_meta(notice: Any) -> dict[str, str | None]:
    """The five notice meta values as strings (STEP-001 contract: ``string|null``).

    ``deadline_at`` is the aware timestamp in KST ISO 8601; ``estimated_price``
    is the plain decimal (integral amounts without a fraction).
    """

    deadline = getattr(notice, "deadline_at", None)
    if isinstance(deadline, datetime):
        deadline_text: str | None = deadline.astimezone(KST).isoformat()
    else:
        deadline_text = None if deadline is None else str(deadline)

    def text(name: str) -> str | None:
        value = getattr(notice, name, None)
        return None if value is None else str(value)

    return {
        "title": text("title"), "agency": text("agency"), "deadline_at": deadline_text,
        "method": text("method"), "estimated_price": _price_text(getattr(notice, "estimated_price", None)),
    }


# --- section selection --------------------------------------------------------------------


def _require_section(section_key: Any) -> str:
    if section_key not in PROPOSAL_SECTION_KEYS:
        raise _invalid()
    return section_key


def section_units(sources: VerdictSources, section_key: str) -> list[dict[str, Any]]:
    """The frozen units this section answers, in frozen order (verbatim copies)."""

    section_key = _require_section(section_key)
    units = sources.frozen["card_analysis"].get("units")
    if not isinstance(units, list) or any(not isinstance(row, Mapping) for row in units):
        raise _invalid()
    if section_key == "overview":
        chosen = [row for row in units if row.get("kind") == "segment"
                  and _OVERVIEW_AREAS & set(row.get("section_kinds") or [])]
    elif section_key == "requirements":
        chosen = [row for row in units if row.get("kind") == "card"]
    elif section_key in _UNIT_TYPES_BY_SECTION:
        types = _UNIT_TYPES_BY_SECTION[section_key]
        chosen = [row for row in units if sources.unit_types.get(row.get("unit_id")) in types]
    else:
        chosen = []
    return [deepcopy(dict(row)) for row in chosen]


def section_compares(sources: VerdictSources, units: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [deepcopy(sources.compares[row["unit_id"]]) for row in units if row["unit_id"] in sources.compares]


def section_fact_keys(sources: VerdictSources, section_key: str, compares: Sequence[Mapping[str, Any]]) -> set[str]:
    """Fact keys this section may cite or must mark as missing."""

    section_key = _require_section(section_key)
    facts = sources.frozen.get("profile_facts")
    if not isinstance(facts, list):
        raise _invalid()
    keys = [row.get("fact_key") for row in facts if isinstance(row, Mapping) and isinstance(row.get("fact_key"), str)]
    if section_key in _FACT_PREFIXES_BY_SECTION:
        prefixes = _FACT_PREFIXES_BY_SECTION[section_key]
        return {key for key in keys if key.startswith(prefixes)}
    if section_key in _COMPARE_FACT_SECTIONS:
        referenced: set[str] = set()
        for compare in compares:
            for result in compare.get("constraint_results") or []:
                fact_ids = result.get("fact_ids") if isinstance(result, Mapping) else None
                if not isinstance(fact_ids, list) or any(not isinstance(key, str) for key in fact_ids):
                    raise _invalid()
                referenced.update(fact_ids)
        if not referenced <= set(keys):
            raise _invalid()
        return referenced
    return set()


def company_parts(sources: VerdictSources, fact_keys: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(company_facts, missing_facts)`` in frozen ``profile_facts`` order (D2)."""

    if isinstance(fact_keys, (str, bytes)):
        raise _invalid()
    wanted = set(fact_keys)
    nodes = {row.get("id"): row for row in sources.frozen.get("graph_nodes") or [] if isinstance(row, Mapping)}
    company_facts: list[dict[str, Any]] = []
    missing_facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fact in sources.frozen.get("profile_facts") or []:
        if not isinstance(fact, Mapping) or not isinstance(fact.get("fact_key"), str):
            raise _invalid()
        key = fact["fact_key"]
        if key not in wanted:
            continue
        seen.add(key)
        node = nodes.get(key)
        status = fact.get("status")
        if node is None or node.get("status") != status:
            raise _invalid()
        if status == "confirmed":
            if not isinstance(node.get("type"), str) or not isinstance(node.get("label"), str):
                raise _invalid()
            company_facts.append({
                "fact_key": key, "type": node["type"], "label": node["label"],
                "value": _without_prompt_sensitive_keys(fact.get("value")),
            })
        elif status in MISSING_FACT_STATUSES:
            missing_facts.append({"fact_key": key, "status": status})
        else:
            # ``inferred`` or another status has no proposal representation: fail closed.
            raise _invalid()
    if seen != wanted:
        raise _invalid()
    if sanitize_for_prompt(company_facts) != company_facts:
        raise _invalid()
    return company_facts, missing_facts


# --- frozen input and payload -------------------------------------------------------------


def build_proposal_input(
    sources: VerdictSources,
    *,
    section_key: str,
    execution_nonce: UUID,
    draft_id: UUID,
    opportunity_id: int,
    notice_id: int,
    policy_sha256: str,
    notice_meta: Mapping[str, Any],
) -> dict[str, Any]:
    """The frozen ``bidops.proposal-input.v1`` of one section run (schema-validated)."""

    section_key = _require_section(section_key)
    if int(notice_id) != sources.notice_id or set(notice_meta) != set(NOTICE_META_KEYS):
        raise _invalid()
    units = section_units(sources, section_key)
    compares = section_compares(sources, units)
    company_facts, missing_facts = company_parts(sources, section_fact_keys(sources, section_key, compares))
    value = {
        "schema_version": PROPOSAL_INPUT_SCHEMA_VERSION,
        "purpose": "proposal",
        "execution_nonce": str(execution_nonce),
        "draft_id": str(draft_id),
        "opportunity_id": int(opportunity_id),
        "notice_id": int(notice_id),
        "verdict_attempt_id": str(sources.attempt_id),
        "verdict_input_sha256": sources.verdict_input_sha256,
        "company_binding": deepcopy(dict(sources.frozen["card_analysis"].get("company_binding") or {})),
        "policy_sha256": policy_sha256,
        "model_name": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "section_key": section_key,
        "notice_meta": {key: notice_meta.get(key) for key in NOTICE_META_KEYS},
        "units": units,
        "compares": compares,
        "verdict": deepcopy(dict(sources.verdict)),
        "company_facts": company_facts,
        "missing_facts": missing_facts,
        "toc_reference": list(SECTION_TOC[section_key]),
    }
    try:
        validate_payload(value, _INPUT_CONTRACT)
    except SchemaValidationError:
        raise _invalid() from None
    return value


def proposal_input_sha256(proposal_input: Mapping[str, Any]) -> str:
    """``input_sha256`` = canonical JSON SHA-256 of the whole frozen input (differs per section)."""

    return canonical_json_hash(proposal_input)


def _withheld_texts(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if len(value) >= _MIN_WITHHELD_TEXT:
            out.append(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            out.extend(_withheld_texts(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_withheld_texts(item))
    return out


def _walk(value: Any, withheld: Mapping[str, str]) -> None:
    if isinstance(value, Mapping):
        keys = set(value)
        if keys & PROPOSAL_FORBIDDEN_TRANSFER_KEYS:
            raise _invalid()
        fact_key = value.get("fact_key")
        if isinstance(fact_key, str) and fact_key in withheld and keys & _COMPANY_FACT_MARKERS:
            if keys != CARD_WITHHELD_FACT_KEYS or value.get("status") != withheld[fact_key]:
                raise _invalid()
        for item in value.values():
            _walk(item, withheld)
    elif isinstance(value, list):
        for item in value:
            _walk(item, withheld)


def check_proposal_transfer_payload(
    payload: Any,
    proposal_input: Mapping[str, Any],
    sources: VerdictSources,
    *,
    operational_values: Sequence[Any] = (),
) -> None:
    """Strict D2 check of one section payload (RL-03 guard approach), else ``company_input_invalid``.

    Fails when: the payload keys are not exactly ``PROPOSAL_TRANSFER_KEYS``; the
    frozen input is not a valid ``bidops.proposal-input.v1`` or the payload is
    not its exact projection; any part differs from its recomputation from the
    verdict sources (units, compares, facts, verdict, §5 headings); an object
    carries a forbidden key; a non-confirmed fact appears with more than
    ``{fact_key, status}``; the sent company part is not stable under the
    prompt sanitizer; or a frozen identity value, a caller operational value
    (approval id, section id, note text, ...) or text of a non-confirmed fact
    value/quote occurs anywhere in the payload text.
    """

    if not isinstance(payload, Mapping) or set(payload) != set(PROPOSAL_TRANSFER_KEYS):
        raise _invalid()
    if not isinstance(proposal_input, Mapping):
        raise _invalid()
    schema = load_schema(_INPUT_CONTRACT)
    if set(proposal_input) != set(schema["properties"]):
        raise _invalid()
    try:
        validate_payload(proposal_input, _INPUT_CONTRACT)
    except SchemaValidationError:
        raise _invalid() from None
    if any(payload[key] != proposal_input[key] for key in PROPOSAL_TRANSFER_KEYS):
        raise _invalid()
    section_key = _require_section(payload["section_key"])
    if (
        proposal_input["verdict_attempt_id"] != str(sources.attempt_id)
        or proposal_input["verdict_input_sha256"] != sources.verdict_input_sha256
        or proposal_input["notice_id"] != sources.notice_id
        or proposal_input["company_binding"] != sources.frozen["card_analysis"].get("company_binding")
    ):
        raise _invalid()
    units = section_units(sources, section_key)
    compares = section_compares(sources, units)
    company_facts, missing_facts = company_parts(sources, section_fact_keys(sources, section_key, compares))
    if (
        payload["units"] != units
        or payload["compares"] != compares
        or payload["company_facts"] != company_facts
        or payload["missing_facts"] != missing_facts
        or payload["verdict"] != dict(sources.verdict)
        or payload["toc_reference"] != list(SECTION_TOC[section_key])
        or any(set(row) != COMPANY_FACT_KEYS for row in payload["company_facts"])
        or any(set(row) != MISSING_FACT_KEYS for row in payload["missing_facts"])
    ):
        raise _invalid()
    withheld = {
        fact["fact_key"]: fact.get("status")
        for fact in sources.frozen.get("profile_facts") or []
        if isinstance(fact, Mapping) and isinstance(fact.get("fact_key"), str) and fact.get("status") != "confirmed"
    }
    _walk(dict(payload), withheld)
    text = canonical_json_bytes(dict(payload)).decode("utf-8")
    forbidden: list[Any] = [sources.frozen.get(key) for key in _FROZEN_FORBIDDEN_VALUE_KEYS]
    forbidden.extend(proposal_input[key] for key in (
        "execution_nonce", "draft_id", "verdict_attempt_id", "verdict_input_sha256", "policy_sha256",
        "model_name",
    ))
    binding = proposal_input["company_binding"]
    forbidden.extend(binding[key] for key in (
        "graph_version_id", "graph_sha256", "profile_version_id", "profile_sha256", "ontology_sha256",
    ))
    forbidden.extend(operational_values)
    for fact in sources.frozen.get("profile_facts") or []:
        if isinstance(fact, Mapping) and fact.get("fact_key") in withheld:
            forbidden.extend(_withheld_texts(fact.get("value")))
            forbidden.extend(_withheld_texts(fact.get("quote")))
    for value in forbidden:
        if value is None:
            continue
        needle = str(value)
        if needle and needle in text:
            raise _invalid()


def proposal_transfer_payload(
    proposal_input: Mapping[str, Any],
    sources: VerdictSources,
    *,
    operational_values: Sequence[Any] = (),
) -> dict[str, Any]:
    """The checked Luna payload: exactly the eight transfer keys of the frozen input."""

    payload = {key: deepcopy(proposal_input[key]) for key in PROPOSAL_TRANSFER_KEYS if key in proposal_input}
    check_proposal_transfer_payload(payload, proposal_input, sources, operational_values=operational_values)
    return payload


def require_input_budget(prompt: Any) -> None:
    """Spec "입력 예산": a prompt over the ``proposal-section-v1`` limit (120,000 characters)
    fails the section as ``input_budget_exceeded`` before any call; it is never split."""

    if not isinstance(prompt, str) or len(prompt) > PROPOSAL_PROMPT_MAX_CHARACTERS:
        raise ProposalInputError("input_budget_exceeded")


__all__ = [
    "COMPANY_FACT_KEYS",
    "MISSING_FACT_KEYS",
    "NOTICE_META_KEYS",
    "PROPOSAL_FORBIDDEN_TRANSFER_KEYS",
    "PROPOSAL_IDENTITY_KEYS",
    "PROPOSAL_INPUT_SCHEMA_VERSION",
    "PROPOSAL_TRANSFER_KEYS",
    "SECTION_TOC",
    "ProposalInputError",
    "VerdictSources",
    "build_proposal_input",
    "check_proposal_transfer_payload",
    "company_parts",
    "load_verdict_sources",
    "notice_meta",
    "proposal_input_sha256",
    "proposal_transfer_payload",
    "require_input_budget",
    "section_compares",
    "section_fact_keys",
    "section_units",
    "verdict_sources",
]
