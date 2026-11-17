"""Pure confirmation-request projection for REV-04.

Raw ``DataToConfirm`` items remain the audit source.  This module attaches deterministic causes,
removes only proven irrelevant requests, and projects the current actionable list without I/O.
analyze builds the raw list from the validated SynthOut; regate carries stored llm/legacy rows via
:func:`preserved_request_rows` and :func:`rebuild_raw_confirmation_data`; reports project legacy
analysis.json objects read-only via :func:`project_legacy_actions`.
"""

from __future__ import annotations

import copy
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from bid_deep_engine.analysis.gates import resolve_as_of
from bid_deep_engine.analysis.provenance import (
    canonical_hash,
    execution_ref,
    field_ref,
    gate_ref,
    notice_ref,
    score_ref,
    stage_ref,
)
from bid_deep_engine.analysis.recommend import (
    PDF_DATA_TO_CONFIRM_FIELD,
    PDF_DATA_TO_CONFIRM_WHY,
    code_data_to_confirm,
    raw_data_to_confirm,
)
from bid_deep_engine.analysis.schemas import (
    ActionCounts,
    ActionRef,
    Analysis,
    Assessment,
    ChecklistItem,
    ConfirmRequest,
    DataToConfirm,
    Evidence,
    ExcludedRequest,
    GateResult,
    Preparation,
    ReviewActions,
    RfpFacts,
    ScoreEstimate,
    Stage,
    StageState,
    SynthOut,
)
from bid_deep_engine.analysis.scoring import score_request_exclusion_reason
from bid_deep_engine.company.hints import hint_for
from bid_deep_engine.company.provenance import DECISION_LEVELS, CompanyEvidenceView

_KIND_ORDER = {"company": 0, "notice": 1, "execution": 2}
# REV-02 reasons whose fix is regenerating a stage input (missing/stale/legacy stage output).
# Gate/company/fit uncertainty is already a field request with the same affects, so it never
# becomes a separate "rerun" request (spec: code requests come from missing inputs only).
_RERUN_REASON_CODES = {
    "legacy_metadata",
    "stale_stage",
    "missing_stage",
    "empty_requirements",
    "missing_fits",
}
_SCHEDULE_PREPARATIONS = (
    ("notice_date", "공고일"),
    ("briefing", "설명회"),
    ("qna_deadline", "질의 마감"),
    ("submission_deadline", "제안서 제출 마감"),
    ("eval_date", "평가일"),
    ("kickoff", "착수일"),
)
FactsArtifact = Literal["facts.json", "analysis.json"]
ActionSource = Literal["code", "llm", "legacy"]


@dataclass(frozen=True)
class ConfirmationProjection:
    data_to_confirm: list[DataToConfirm]
    review_actions: ReviewActions


@dataclass(frozen=True)
class PreparationProjection:
    preparations: list[Preparation]
    raw_preparations: int


@dataclass(frozen=True)
class _Cause:
    source: str
    index: int
    affects: tuple[str, ...]
    completion: str


@dataclass
class _Candidate:
    raw_index: int
    item: DataToConfirm
    kind: str
    fields: list[str]
    title: str
    why: str
    affects: list[str]
    completion: str
    refs: list[ActionRef]
    causes: tuple[_Cause, ...]


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split())


def _ref_key(ref: ActionRef) -> tuple[str, str]:
    return ref.path, ref.source


def _dedup_refs(refs: Sequence[ActionRef]) -> list[ActionRef]:
    by_key = {_ref_key(ref): ref for ref in refs}
    return [by_key[key] for key in sorted(by_key)]


def _dedup_strings(values: Sequence[str]) -> list[str]:
    return sorted(dict.fromkeys(values))


def _joined(values: Sequence[str]) -> str:
    return "\n".join(dict.fromkeys(value for value in values if value))


def _request_id(kind: str, fields: Sequence[str], affects: Sequence[str], title: str) -> str:
    canonical_fields = _dedup_strings(fields)
    canonical_affects = _dedup_strings(affects)
    payload = {
        "schema_version": 1,
        "kind": kind,
        "fields": canonical_fields,
        "affects": canonical_affects,
        "fallback_title": (
            _normalized_text(title) if not canonical_fields and not canonical_affects else None
        ),
    }
    return "confirm-" + canonical_hash(payload)


def _normalized_optional(value: str | None) -> str | None:
    return None if value is None else _normalized_text(value)


def _preparation_key(
    kind: str,
    title: str,
    due: str | None,
    copies: str | None,
    stage: str | None,
    condition: str | None,
) -> tuple[str, str, str | None, str | None, str | None, str | None]:
    return (
        kind,
        _normalized_text(title),
        _normalized_optional(due),
        _normalized_optional(copies),
        _normalized_optional(stage),
        _normalized_optional(condition),
    )


def _preparation_id(
    kind: str,
    title: str,
    due: str | None,
    copies: str | None,
    stage: str | None,
    condition: str | None,
) -> str:
    payload = {
        "schema_version": 1,
        "kind": kind,
        "title": _normalized_text(title),
        "due": _normalized_optional(due),
        "copies": _normalized_optional(copies),
        "stage": _normalized_optional(stage),
        "condition": _normalized_optional(condition),
    }
    return "prep-" + canonical_hash(payload)


def _evidence_identity(evidence: Evidence) -> tuple[Any, ...]:
    """Compare source evidence conservatively while ignoring resolver-owned locations."""
    raw = evidence.model_dump(mode="json", exclude={"locations", "location_status"})
    return tuple(raw[name] for name in raw)


@dataclass(frozen=True)
class _FactsPreparation:
    key: tuple[str, str, str | None, str | None, str | None, str | None]
    title: str
    due: str | None
    evidence: frozenset[tuple[Any, ...]]


def build_preparation_projection(
    facts: RfpFacts,
    checklist: Sequence[ChecklistItem],
    *,
    facts_artifact: FactsArtifact,
    checklist_source: ActionSource,
) -> PreparationProjection:
    """Build canonical document, schedule, and execution preparations without I/O.

    Facts are authoritative.  A checklist row links to a facts item only when title, due, and
    evidence identify exactly one raw facts candidate; ambiguity remains a separate proposal.
    """
    preparations: dict[
        tuple[str, str, str | None, str | None, str | None, str | None], Preparation
    ] = {}
    facts_candidates: list[_FactsPreparation] = []

    def add(
        kind: Literal["document", "schedule", "execution"],
        title: str,
        due: str | None,
        copies: str | None,
        stage: str | None,
        condition: str | None,
        ref: ActionRef,
    ) -> tuple[str, str, str | None, str | None, str | None, str | None]:
        key = _preparation_key(kind, title, due, copies, stage, condition)
        current = preparations.get(key)
        if current is None:
            preparations[key] = Preparation(
                id=_preparation_id(kind, title, due, copies, stage, condition),
                kind=kind,
                title=title,
                due=due,
                copies=copies,
                stage=stage,
                condition=condition,
                refs=[ref],
            )
        else:
            current.refs = _dedup_refs([*current.refs, ref])
        return key

    for index, document in enumerate(facts.submission_docs):
        ref = ActionRef(source="code", path=f"{facts_artifact}#/facts/submission_docs/{index}")
        key = add(
            "document",
            document.name,
            document.due,
            document.copies,
            document.stage,
            document.condition,
            ref,
        )
        facts_candidates.append(
            _FactsPreparation(
                key=key,
                title=document.name,
                due=document.due,
                evidence=frozenset({_evidence_identity(document.evidence)}),
            )
        )

    for field, title in _SCHEDULE_PREPARATIONS:
        due = getattr(facts.schedule, field)
        if due is None or not due.strip():
            continue
        ref = ActionRef(source="code", path=f"{facts_artifact}#/facts/schedule/{field}")
        key = add("schedule", title, due, None, None, None, ref)
        facts_candidates.append(
            _FactsPreparation(
                key=key,
                title=title,
                due=due,
                evidence=frozenset(_evidence_identity(item) for item in facts.schedule.evidence),
            )
        )

    for index, item in enumerate(checklist):
        ref = ActionRef(source=checklist_source, path=f"analysis.json#/checklist/{index}")
        source_key = None if item.source is None else _evidence_identity(item.source)
        matches = [
            candidate
            for candidate in facts_candidates
            if source_key is not None
            and source_key in candidate.evidence
            and _normalized_text(item.item) == _normalized_text(candidate.title)
            and _normalized_optional(item.due) == _normalized_optional(candidate.due)
        ]
        if len(matches) == 1:
            target = preparations[matches[0].key]
            target.refs = _dedup_refs([*target.refs, ref])
            continue
        add("execution", item.item, item.due, None, None, None, ref)

    raw_count = (
        len(facts.submission_docs)
        + len(checklist)
        + sum(
            1
            for field, _ in _SCHEDULE_PREPARATIONS
            if (value := getattr(facts.schedule, field)) is not None and bool(value.strip())
        )
    )
    return PreparationProjection(
        preparations=[item.model_copy(deep=True) for item in preparations.values()],
        raw_preparations=raw_count,
    )


def _cause_queues(
    gates: Sequence[GateResult],
    scores: Sequence[ScoreEstimate],
    reasons: Sequence[Mapping[str, Any]],
    *,
    numeric_facts_unconfirmed: bool = False,
) -> dict[tuple[str, str, str], list[_Cause]]:
    causes: dict[tuple[str, str, str], list[_Cause]] = defaultdict(list)
    if numeric_facts_unconfirmed:
        # Same code row as recommend.code_data_to_confirm; affects equal the uncaused inference
        # so the semantic ID does not depend on whether the row was recognised as code.
        causes[(PDF_DATA_TO_CONFIRM_FIELD, PDF_DATA_TO_CONFIRM_WHY, "code")].append(
            _Cause(
                source="pdf",
                index=0,
                affects=(execution_ref(_display_title(PDF_DATA_TO_CONFIRM_FIELD, "")),),
                completion=PDF_DATA_TO_CONFIRM_WHY,
            )
        )
    for gate in gates:
        for field in gate.unknown_fields:
            why = f"게이트 {gate.code} 판정에 필요"
            # gate.action describes the representative (first) field only; other fields of a
            # multi-field gate keep their own field-level source hint.
            completion = (
                gate.action or hint_for(field)
                if field == gate.unknown_fields[0]
                else hint_for(field)
            )
            causes[(field, why, "code")].append(
                _Cause(
                    source="gate",
                    index=0,
                    affects=(gate_ref(gate.code, gate.rule_hash), field_ref(field)),
                    completion=completion,
                )
            )
    for index, score in enumerate(scores):
        for field in score.unknown_inputs:
            why = f"정량점수 '{score.item}' 추정에 필요"
            causes[(field, why, "code")].append(
                _Cause(
                    source="score",
                    index=index,
                    affects=(score_ref(index), field_ref(field)),
                    completion=hint_for(field),
                )
            )
    for index, reason in enumerate(reasons):
        stage = reason.get("stage")
        message = reason.get("message")
        if (
            not _actionable_reason(reason)
            or not isinstance(stage, str)
            or not isinstance(message, str)
        ):
            continue
        refs = tuple(
            sorted(
                dict.fromkeys(str(ref) for ref in reason.get("refs", []) if isinstance(ref, str))
            )
        ) or (stage_ref(stage),)  # type: ignore[arg-type]
        causes[("", message, "code")].append(
            _Cause(
                source="readiness",
                index=index,
                affects=refs,
                completion=f"분석 단계 재실행: {stage}",
            )
        )
    return causes


def readiness_data_to_confirm(
    reasons: Sequence[Mapping[str, Any]],
) -> list[DataToConfirm]:
    """Turn REV-02 missing/stale/legacy stage reasons into raw code-owned rerun requests.

    Only reasons fixed by regenerating a stage qualify; see ``_RERUN_REASON_CODES``.
    """
    result: list[DataToConfirm] = []
    for reason in reasons:
        if (
            not _actionable_reason(reason)
            or not isinstance(reason.get("stage"), str)
            or not isinstance(reason.get("message"), str)
        ):
            continue
        result.append(DataToConfirm(field="", why=str(reason["message"]), origin="code"))
    return result


def _actionable_reason(reason: Mapping[str, Any]) -> bool:
    return reason.get("code") in _RERUN_REASON_CODES


def _dedup_exact_rows(candidates: Sequence[DataToConfirm]) -> list[DataToConfirm]:
    """Collapse only rows whose field/why/origin are all identical; keep the first."""
    seen: set[tuple[str, str, str]] = set()
    result: list[DataToConfirm] = []
    for item in candidates:
        identity = (item.field, item.why, item.origin)
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def build_raw_confirmation_data(
    gates: Sequence[GateResult],
    scores: Sequence[ScoreEstimate],
    synth: SynthOut,
    reasons: Sequence[Mapping[str, Any]],
    *,
    numeric_facts_unconfirmed: bool,
) -> list[DataToConfirm]:
    """Build the uncollapsed source list that STEP-002 producers will persist."""
    candidates = raw_data_to_confirm(
        gates,
        scores,
        synth,
        numeric_facts_unconfirmed=numeric_facts_unconfirmed,
    )
    candidates.extend(readiness_data_to_confirm(reasons))
    return _dedup_exact_rows(candidates)


def preserved_request_rows(
    previous: Sequence[DataToConfirm],
    code_generated: Sequence[DataToConfirm],
) -> list[DataToConfirm]:
    """Select the stored rows that regate must carry over, in their original order.

    ``origin=code`` rows are always replaced by the latest code generation.  A ``legacy`` row is
    replaced only when its field *and* why exactly equal a code generator row (its cause is that
    code rule).  Every other llm/legacy row is kept, including a different reason for a field
    that a code row also asks about.  Inputs are not mutated.
    """
    code_keys = {(item.field, item.why) for item in code_generated}
    kept: list[DataToConfirm] = []
    for item in previous:
        if item.origin == "code":
            continue
        if item.origin == "legacy" and (item.field, item.why) in code_keys:
            continue
        kept.append(item.model_copy(deep=True))
    return kept


def rebuild_raw_confirmation_data(
    gates: Sequence[GateResult],
    scores: Sequence[ScoreEstimate],
    preserved: Sequence[DataToConfirm],
    reasons: Sequence[Mapping[str, Any]],
    *,
    numeric_facts_unconfirmed: bool,
) -> list[DataToConfirm]:
    """regate raw list: fresh code rows, carried llm/legacy rows as stored, fresh readiness rows.

    The order matches :func:`build_raw_confirmation_data` and preserved rows keep their origin.
    """
    candidates = code_data_to_confirm(
        gates, scores, numeric_facts_unconfirmed=numeric_facts_unconfirmed
    )
    candidates.extend(item.model_copy(deep=True) for item in preserved)
    candidates.extend(readiness_data_to_confirm(reasons))
    return _dedup_exact_rows(candidates)


def stored_checklist_source(review_actions: ReviewActions | None) -> Literal["llm", "legacy"]:
    """Checklist provenance as saved in an earlier projection; anything unclear is legacy."""
    if review_actions is None:
        return "legacy"
    sources = {
        ref.source
        for item in review_actions.preparations
        for ref in item.refs
        if ref.path.startswith("analysis.json#/checklist/")
    }
    return "llm" if sources == {"llm"} else "legacy"


def _display_title(field: str, why: str) -> str:
    """Shown title of a raw row; execution ReferenceIDs hash this same title (REV-02 grammar)."""
    return field.strip() or why


def _classify(
    item: DataToConfirm,
    company: CompanyEvidenceView,
) -> tuple[str, list[str], list[str]]:
    field = item.field.strip()
    try:
        company.get(field)
    except ValueError:
        pass
    else:
        return "company", [field], [field_ref(field)]
    if field.startswith("facts#"):
        pointer = field.removeprefix("facts#")
        try:
            ref = notice_ref(pointer)
        except ValueError:
            pass
        else:
            return "notice", [field], [ref]
    return "execution", [], [execution_ref(_display_title(item.field, item.why))]


def _candidate(
    raw_index: int,
    item: DataToConfirm,
    company: CompanyEvidenceView,
    causes: Sequence[_Cause],
    *,
    raw_field: str,
) -> _Candidate:
    kind, fields, inferred_affects = _classify(item, company)
    affects = (
        [affect for cause in causes for affect in cause.affects] if causes else inferred_affects
    )
    completion = (
        _joined([cause.completion for cause in causes])
        if causes
        else hint_for(fields[0])
        if kind == "company" and fields
        else item.why
    )
    title = _display_title(item.field, item.why)
    return _Candidate(
        raw_index=raw_index,
        item=item,
        kind=kind,
        fields=fields,
        title=title,
        why=item.why,
        affects=_dedup_strings(affects),
        completion=completion,
        refs=[ActionRef(source=item.origin, path=f"analysis.json#/{raw_field}/{raw_index}")],
        causes=tuple(causes),
    )


def _current_narrative(
    candidate: _Candidate, stage_states: Mapping[Stage, StageState] | None
) -> bool:
    """Whether a raw row may become a current request.

    An ``origin=code`` row was generated from a cause (gate unknown field, score unknown input,
    pdf flag, or a REV-02 rerun reason) and is valid only while that cause exists.  Without a
    matching current cause it is not inferred as an execution request: it stays in the raw list
    only, exactly like stale free-form narrative (no exclusion reason, not counted as excluded).
    Gate/score/pdf causes come from the same stored analysis that produced the row, so in practice
    only rerun rows whose REV-02 reason disappeared at read time take this path.
    """
    if candidate.item.origin == "code":
        return bool(candidate.causes)
    if candidate.causes or candidate.kind != "execution":
        return True
    return stage_states is None or stage_states.get("synth") == "current"


def _blocking(
    affects: Sequence[str], assessment: Assessment | None, reasons: Sequence[Mapping[str, Any]]
) -> bool:
    if assessment is None or assessment.state != "abstain":
        return False
    reason_refs = {
        str(ref) for reason in reasons for ref in reason.get("refs", []) if isinstance(ref, str)
    }
    return bool(set(affects) & reason_refs)


def build_confirmation_projection(
    *,
    facts: RfpFacts,
    gates: Sequence[GateResult],
    scores: Sequence[ScoreEstimate],
    raw_data_to_confirm: Sequence[DataToConfirm],
    company: CompanyEvidenceView,
    assessment: Assessment | None,
    reasons: Sequence[Mapping[str, Any]],
    as_of: date,
    stage_states: Mapping[Stage, StageState] | None = None,
    raw_field: str = "raw_data_to_confirm",
    preparations: Sequence[Preparation] = (),
    raw_preparations: int = 0,
    numeric_facts_unconfirmed: bool = False,
) -> ConfirmationProjection:
    """Project raw requests into current requests and explicit exclusions.

    Stale/unknown free-form execution text is omitted from current requests but remains in the raw
    list.  It is not assigned an unsupported exclusion reason and is not counted as excluded.  The
    same applies to an ``origin=code`` row whose cause is absent from the current inputs (e.g. a
    stage rerun row saved by regate whose stage is current again when a report reads it).
    """
    causes = _cause_queues(
        gates, scores, reasons, numeric_facts_unconfirmed=numeric_facts_unconfirmed
    )
    candidates: list[_Candidate] = []
    exclusions: list[ExcludedRequest] = []
    excluded_indexes: set[int] = set()
    active_indexes: set[int] = set()

    for raw_index, original in enumerate(raw_data_to_confirm):
        item = original.model_copy(deep=True)
        matched_causes = causes.get((item.field, item.why, item.origin), [])
        if not matched_causes and item.origin == "legacy":
            # A legacy row with the exact code generator text has a determinable code cause.
            matched_causes = causes.get((item.field, item.why, "code"), [])
        candidate = _candidate(raw_index, item, company, matched_causes, raw_field=raw_field)
        if not _current_narrative(candidate, stage_states):
            continue

        reason: str | None = None
        cause_reasons: list[str | None] = []
        for cause in candidate.causes:
            cause_reason: str | None = None
            if cause.source == "score" and cause.index < len(scores):
                quantitative = facts.evaluation.quantitative
                if cause.index < len(quantitative):
                    cause_reason = score_request_exclusion_reason(
                        facts,
                        quantitative[cause.index],
                        scores[cause.index],
                        company,
                        item.field,
                        as_of=as_of,
                    )
            cause_reasons.append(cause_reason)
        if candidate.causes and all(cause_reasons) and len(set(cause_reasons)) == 1:
            reason = cause_reasons[0]
        # confirmed exclusion needs proof that the request asks exactly the stored value: a code
        # cause (gate/score asks this canonical field).  Free-form llm/legacy text is never
        # matched by wording; staffing/subcontract/cost questions stay requests.  Demo values are
        # used like confirmed ones (2026-10-25), so they are excluded with the same reason; their
        # replacement is tracked in the company data todo list instead.
        if reason is None and candidate.kind == "company" and candidate.fields and candidate.causes:
            if company.get(candidate.fields[0])["effective_level"] in DECISION_LEVELS:
                reason = "confirmed"

        if reason is not None:
            exclusions.append(
                ExcludedRequest(
                    field=item.field.strip(),
                    refs=candidate.refs,
                    reason=reason,  # type: ignore[arg-type]
                )
            )
            excluded_indexes.add(raw_index)
            continue
        candidates.append(candidate)
        active_indexes.add(raw_index)

    grouped: dict[tuple[str, tuple[str, ...], tuple[str, ...], str | None], list[_Candidate]] = {}
    group_order: list[tuple[str, tuple[str, ...], tuple[str, ...], str | None]] = []
    for candidate in candidates:
        fields = tuple(_dedup_strings(candidate.fields))
        affects = tuple(_dedup_strings(candidate.affects))
        fallback = _normalized_text(candidate.title) if not fields and not affects else None
        key = (candidate.kind, fields, affects, fallback)
        if key not in grouped:
            grouped[key] = []
            group_order.append(key)
        grouped[key].append(candidate)

    requests_with_order: list[tuple[int, ConfirmRequest]] = []
    for key in group_order:
        members = grouped[key]
        first = members[0]
        fields = _dedup_strings([field for member in members for field in member.fields])
        affects = _dedup_strings([ref for member in members for ref in member.affects])
        request = ConfirmRequest(
            id=_request_id(first.kind, fields, affects, first.title),
            kind=first.kind,  # type: ignore[arg-type]
            fields=fields,
            title=first.title,
            why=_joined([member.why for member in members]),
            affects=affects,
            blocking=_blocking(affects, assessment, reasons),
            completion=_joined([member.completion for member in members]),
            refs=_dedup_refs([ref for member in members for ref in member.refs]),
        )
        requests_with_order.append((min(member.raw_index for member in members), request))

    requests_with_order.sort(
        key=lambda pair: (not pair[1].blocking, _KIND_ORDER[pair[1].kind], pair[0])
    )
    requests = [request for _, request in requests_with_order]

    merged_exclusions: dict[tuple[str, str], list[ActionRef]] = defaultdict(list)
    for excluded in exclusions:
        merged_exclusions[(excluded.field, excluded.reason)].extend(excluded.refs)
    excluded = [
        ExcludedRequest(field=field, reason=reason, refs=_dedup_refs(refs))  # type: ignore[arg-type]
        for (field, reason), refs in merged_exclusions.items()
    ]

    seen_active: set[tuple[str, str, str]] = set()
    active: list[DataToConfirm] = []
    for index, item in enumerate(raw_data_to_confirm):
        if index not in active_indexes:
            continue
        identity = (item.field, item.why, item.origin)
        if identity in seen_active:
            continue
        seen_active.add(identity)
        active.append(item.model_copy(deep=True))

    review_actions = ReviewActions(
        requests=requests,
        preparations=[item.model_copy(deep=True) for item in preparations],
        excluded=excluded,
        counts=ActionCounts(
            raw_requests=len(raw_data_to_confirm),
            active_requests=len(requests),
            excluded_requests=len(excluded_indexes),
            raw_preparations=raw_preparations,
            unique_preparations=len(preparations),
        ),
    )
    return ConfirmationProjection(data_to_confirm=active, review_actions=review_actions)


RequestField = Literal["raw_data_to_confirm", "data_to_confirm"]
_REQUEST_ROWS = TypeAdapter(list[DataToConfirm])
_ACTION_FIELDS = ("raw_data_to_confirm", "review_actions")


@dataclass(frozen=True)
class LegacyActionsProjection:
    """Read-only actions view of a stored analysis.json (REV-05 report input).

    ``review_actions``/``data_to_confirm`` are ``None`` when the request source list cannot be
    projected faithfully; ``request_items`` then still carries the original JSON rows so a report
    can show them next to ``warnings``.  ``stored_review_actions`` is the saved value when it
    validates (for comparison only; it is never trusted over the projection).
    """

    review_actions: ReviewActions | None
    data_to_confirm: list[DataToConfirm] | None
    request_field: RequestField
    request_items: list[Any]
    stored_review_actions: ReviewActions | None
    warnings: list[str]


def _ref_index(path: str, field: RequestField) -> int | None:
    prefix = f"analysis.json#/{field}/"
    if not path.startswith(prefix):
        return None
    tail = path.removeprefix(prefix)
    return int(tail) if tail.isdigit() else None


def _stored_consistency_warnings(
    stored: ReviewActions, request_field: RequestField, request_count: int
) -> list[str]:
    warnings: list[str] = []
    counts = stored.counts
    if counts.raw_requests != request_count:
        warnings.append(f"review_actions: counts.raw_requests does not match {request_field}")
    if counts.active_requests != len(stored.requests):
        warnings.append("review_actions: counts.active_requests does not match requests")
    if counts.excluded_requests > counts.raw_requests:
        warnings.append("review_actions: counts.excluded_requests exceeds raw_requests")
    if counts.unique_preparations != len(stored.preparations):
        warnings.append("review_actions: counts.unique_preparations does not match preparations")
    refs = [
        ref.path
        for group in (stored.requests, stored.excluded)
        for item in group
        for ref in item.refs
    ]
    indexes = [_ref_index(path, request_field) for path in refs]
    if any(index is None or index >= request_count for index in indexes):
        warnings.append(f"review_actions: refs point outside {request_field}")
    return warnings


def project_legacy_actions(
    analysis: Mapping[str, Any],
    *,
    company: CompanyEvidenceView | None,
    assessment: Assessment | None,
    reasons: Sequence[Mapping[str, Any]],
    stage_states: Mapping[Stage, StageState],
    today: date | None = None,
    facts_artifact: FactsArtifact = "analysis.json",
) -> LegacyActionsProjection:
    """Project stored request/preparation sources with the same pure builders, without I/O.

    ``analysis`` is the analysis.json object as read (it is deep-copied, never mutated).  The
    request source is ``raw_data_to_confirm`` when present, otherwise legacy ``data_to_confirm``.
    Stored gates/scores are used as-is; a ``rule_hash=null`` gate maps to ``stage:gates``.
    ``assessment``/``reasons``/``stage_states`` are the current REV-02 read model
    (``build_review``); a synth state other than ``current`` keeps llm/legacy execution text out of
    current requests.  ``facts_artifact`` should be ``"facts.json"`` only when that file exists
    and holds the same facts as ``analysis["facts"]`` (otherwise its indexes point elsewhere).

    Malformed input never raises and is never dropped silently: the result carries a warning and
    the original rows.  Warnings contain only field names and exception class names.
    """
    warnings: list[str] = []
    source: dict[str, Any] = copy.deepcopy(dict(analysis))
    raw_present = source.get("raw_data_to_confirm") is not None
    request_field: RequestField = "raw_data_to_confirm" if raw_present else "data_to_confirm"
    original_rows = source.get(request_field)
    request_items: list[Any] = (
        copy.deepcopy(original_rows)
        if isinstance(original_rows, list)
        else []
        if original_rows is None
        else [copy.deepcopy(original_rows)]
    )

    def unavailable(message: str) -> LegacyActionsProjection:
        warnings.append(message)
        return LegacyActionsProjection(
            review_actions=None,
            data_to_confirm=None,
            request_field=request_field,
            request_items=request_items,
            stored_review_actions=stored,
            warnings=warnings,
        )

    stored: ReviewActions | None = None
    if source.get("review_actions") is not None:
        try:
            stored = ReviewActions.model_validate(source["review_actions"])
        except ValidationError as exc:
            warnings.append(
                f"review_actions: malformed ({type(exc).__name__}); projected from source lists"
            )

    # Stage stamps do not feed the projection; a malformed legacy stamp must not hide actions.
    base = {key: value for key, value in source.items() if key not in (*_ACTION_FIELDS, "stages")}
    try:
        parsed = Analysis.model_validate(base)
    except ValidationError as exc:
        return unavailable(
            f"analysis.json: malformed ({type(exc).__name__}); showing original lists"
        )

    if raw_present:
        try:
            rows = _REQUEST_ROWS.validate_python(source["raw_data_to_confirm"])
        except ValidationError as exc:
            return unavailable(
                f"raw_data_to_confirm: malformed ({type(exc).__name__}); showing original list"
            )
    else:
        rows = parsed.data_to_confirm
    if company is None:
        return unavailable("company profile unavailable; showing original list")

    preparations = build_preparation_projection(
        parsed.facts,
        parsed.checklist,
        facts_artifact=facts_artifact,
        checklist_source=stored_checklist_source(stored),
    )
    as_of, _ = resolve_as_of(parsed.facts, today)
    projection = build_confirmation_projection(
        facts=parsed.facts,
        gates=parsed.gates,
        scores=parsed.scores,
        raw_data_to_confirm=rows,
        company=company,
        assessment=assessment,
        reasons=reasons,
        as_of=as_of,
        stage_states=stage_states,
        raw_field=request_field,
        preparations=preparations.preparations,
        raw_preparations=preparations.raw_preparations,
        numeric_facts_unconfirmed=parsed.numeric_facts_unconfirmed,
    )
    if stored is not None:
        warnings.extend(_stored_consistency_warnings(stored, request_field, len(rows)))
    return LegacyActionsProjection(
        review_actions=projection.review_actions,
        data_to_confirm=projection.data_to_confirm,
        request_field=request_field,
        request_items=request_items,
        stored_review_actions=stored,
        warnings=warnings,
    )
