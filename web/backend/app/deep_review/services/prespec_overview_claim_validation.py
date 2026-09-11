"""Pure evidence/claim gates and deterministic publication for page review v4.

No inference engine, model transport, DB, or source-object access lives here.
Unknown numeric relations fail closed; semantic judgments never override them.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from ..schemas.prespec_overview_claims import (
    CHECKS_SCHEMA, FACT_SECTIONS, VALIDATOR_VERSION, AnalysisCheck, ClaimCheck,
    ClaimEvidence, DeterministicCheck, OverviewClaimChecks, OverviewClaimsDraft,
    OverviewSemanticResponse, PageOverviewPayloadV4, Quantity, SemanticCheck,
    UnknownCheck, VerifiedEvidence,
)
from .prespec_overview_claim_policy import FORMAT_RETRY_CODES, LIMITS, canonical_json, canonical_sha256


class ClaimDraftError(ValueError):
    """Safe parser classification; never embeds the model's text in errors."""

    def __init__(self, code: str):
        self.code = code
        self.retryable = code in FORMAT_RETRY_CODES
        super().__init__(code)


class SemanticResponseError(ValueError):
    code = "semantic_response_invalid"

    def __init__(self):
        super().__init__(self.code)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClaimDraftError("duplicate_json_key")
        result[key] = value
    return result


def parse_claims_draft(raw: object) -> OverviewClaimsDraft:
    if isinstance(raw, OverviewClaimsDraft):
        raw = raw.model_dump(mode="json")
    if isinstance(raw, (str, bytes)):
        if len(raw) > LIMITS["max_response_chars"]:
            raise ClaimDraftError("output_limit_exceeded")
        try:
            raw = json.loads(raw, object_pairs_hook=_reject_duplicate_keys,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError) as error:
            if isinstance(error, ClaimDraftError):
                raise
            raise ClaimDraftError("json_invalid") from None
    if not isinstance(raw, dict):
        raise ClaimDraftError("top_level_invalid")
    try:
        result = OverviewClaimsDraft.model_validate(raw)
    except ValidationError as error:
        errors = error.errors(include_input=False, include_url=False)
        # A missing evidence/quantity or required fact is not permission for the
        # model to repair its factual answer, even alongside a format error.
        factual_fields = {"claims", "evidence", "quantities", "supporting_claim_ids", "quote", "page", "text"}
        if any(e["type"] == "missing" and any(k in factual_fields for k in e["loc"]) for e in errors):
            raise ClaimDraftError("fact_structure_missing") from None
        if any(e["type"] in {"too_long", "string_too_long"} for e in errors):
            raise ClaimDraftError("output_limit_exceeded") from None
        if any(e["type"] in {"greater_than_equal", "less_than", "string_too_short", "string_pattern_mismatch", "literal_error"} for e in errors):
            raise ClaimDraftError("fact_schema_invalid") from None
        types = {e["type"] for e in errors}
        if types <= {"extra_forbidden"}:
            raise ClaimDraftError("extra_field_forbidden") from None
        if types <= {"missing"}:
            raise ClaimDraftError("required_field_missing") from None
        if types <= {"string_type", "int_type", "list_type", "dict_type", "model_type"}:
            raise ClaimDraftError("field_type_invalid") from None
        raise ClaimDraftError("fact_schema_invalid") from None
    if len(canonical_json(result)) > LIMITS["max_draft_chars"]:
        raise ClaimDraftError("output_limit_exceeded")
    return result


def draft_failure_checks(
    raw: object, error: ClaimDraftError, *, attempt_id: UUID, input_sha256: str,
    policy_digest: str, binding_digest: str,
) -> OverviewClaimChecks:
    """Record an unparseable factual failure without exposing unchecked quotes.

    The original response remains in the encrypted call ledger. No replacement
    draft, evidence, or factual sentence is invented for this failure record.
    """
    if error.retryable or error.code not in {"fact_structure_missing", "fact_schema_invalid", "output_limit_exceeded", "duplicate_json_key"}:
        raise ValueError("draft_error_not_factual")
    if isinstance(raw, (str, bytes)):
        # Preserve a malformed/ambiguous response's exact identity, not a JSON
        # parser's last-key-wins interpretation of duplicate fields.
        raw_digest = hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()
    else:
        raw_digest = canonical_sha256(raw)
    return OverviewClaimChecks(
        schema_version=CHECKS_SCHEMA, attempt_id=attempt_id, draft_sha256=raw_digest,
        input_sha256=input_sha256, policy_digest=policy_digest, binding_digest=binding_digest,
        validator_version=VALIDATOR_VERSION, checks=[], analysis_checks=[], unknown_checks=[],
        analysis=[], unknowns=[], reason_codes=[error.code], overall="needs_human_review",
    )


def _space_map(text: str) -> tuple[str, list[int]]:
    offsets = [i for i, char in enumerate(text) if not char.isspace()]
    return "".join(text[i] for i in offsets), offsets


def verify_evidence(evidence: ClaimEvidence, pages: dict[int, str]) -> VerifiedEvidence:
    if evidence.page not in pages:
        raise ValueError("page_out_of_range")
    page = pages[evidence.page]
    normalized, offsets = _space_map(page)
    quote, _ = _space_map(evidence.quote)
    if not quote:
        raise ValueError("quote_empty")
    # Count overlaps too: ambiguity must not depend on Python's str.count.
    matches = [m.start() for m in re.finditer(f"(?={re.escape(quote)})", normalized)]
    if not matches:
        raise ValueError("quote_not_found")
    if len(matches) != 1:
        raise ValueError("quote_ambiguous")
    start = offsets[matches[0]]
    end = offsets[matches[0] + len(quote) - 1] + 1
    if end - start > 2000:
        raise ValueError("input_limit_exceeded")
    return VerifiedEvidence(page=evidence.page, quote=page[start:end], start_char=start,
                            end_char=end, page_text_sha256=hashlib.sha256(page.encode("utf-8")).hexdigest())


_NUMBER = r"[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_QUANTITY = re.compile(rf"(?P<value>{_NUMBER})\s*(?P<unit>천만원|백만원|억원|만원|천원|원|개월|년|일|주|명|개|건|식|%)")
_DATE = re.compile(r"(?<!\d)(?:(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?|(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일)")
_DATE_ROLE = re.compile(r"시작일|종료일|계약일|착수일|납품일|제출일|마감일|공고일|개찰일|등록일")
_ID = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2,12}[-_]\d+(?:[-_]\d+)*(?![A-Za-z0-9])")
_ROLE = re.compile(r"계약금액|사업예산|사업금액|사업비|예산|수행기간|사업기간|기간|인원|수량|비율|배점")
_MONEY = {"원": Decimal(1), "천원": Decimal(1000), "만원": Decimal(10000), "백만원": Decimal(1000000), "천만원": Decimal(10000000), "억원": Decimal(100000000)}
_BASIS = {"계약일": "contract_date", "착수일": "start_date", "납품일": "delivery_date"}


def _subject(text: str) -> str:
    text = re.sub(r"\s+", "", text).strip(" :·,-()")
    return re.sub(r"(?:의|은|는|이|가)$", "", text)


def _numeric_key(value: Decimal, unit: str) -> tuple[Decimal, str]:
    # Decimal's default 28-digit context would silently round long integers.
    with localcontext() as context:
        context.prec = max(64, len(value.as_tuple().digits) + 12)
        if unit in _MONEY:
            return value * _MONEY[unit], "원"
        # Only exact fixed-unit equivalence, never calendar date arithmetic.
        if unit == "년":
            return value * 12, "개월"
        if unit == "주":
            return value * 7, "일"
        return value, unit


@dataclass(frozen=True)
class ExtractedQuantity:
    subject: str
    role: str
    value: Decimal
    unit: str
    currency: str | None
    vat: str | None
    period_basis: str | None

    def key(self) -> tuple:
        return self.subject, self.role, *_numeric_key(self.value, self.unit), self.currency, self.vat, self.period_basis


def extract_quantities(text: str) -> tuple[list[ExtractedQuantity], set[str]]:
    """Conservative explicit relations, independently applied to claim and quote.

    Table columns, omitted subjects/units and unresolved role attachment are
    rejected, rather than assigned the nearest coincidentally matching number.
    """
    errors: set[str] = set()
    quantities: list[ExtractedQuantity] = []
    masked = list(text)
    for pattern in (_DATE, _ID):
        for match in pattern.finditer(text):
            masked[match.start():match.end()] = " " * (match.end() - match.start())
    numeric_text = "".join(masked)
    matches = list(_QUANTITY.finditer(numeric_text))
    for match in matches:
        # Punctuation separates assertions; commas inside numbers do not.
        prefix = text[:match.start()]
        boundaries = list(re.finditer(r"[;\n。]|(?<!\d)[.]|[.](?!\d)|,(?!\d)", prefix))
        clause_start = boundaries[-1].end() if boundaries else 0
        prefix = text[clause_start:match.start()]
        following = text[match.end():]
        boundary = re.search(r"[;\n。]|(?<!\d)[.]|[.](?!\d)|,(?!\d)", following)
        following = following[:boundary.start()] if boundary else following
        roles = list(_ROLE.finditer(prefix))
        unit = match["unit"]
        role = "budget" if unit in _MONEY else "period" if unit in {"년", "개월", "일", "주"} else "percentage" if unit == "%" else "count"
        subject = ""
        if roles:
            label = roles[-1]
            explicit_role = "contract_amount" if label[0] == "계약금액" else "budget" if label[0] in {"사업예산", "사업금액", "사업비", "예산"} else "period" if "기간" in label[0] else "percentage" if label[0] in {"비율", "배점"} else "count"
            if role != explicit_role and not (role == "budget" and explicit_role == "contract_amount"):
                errors.add("quantity_relation_ambiguous")
            role = explicit_role
            subject = _subject(prefix[:label.start()])
            if len(roles) > 1 or re.search(r"\d|[|\t]", prefix[:label.start()]):
                errors.add("quantity_relation_ambiguous")
        elif role in {"period", "count", "percentage"}:
            # Explicit subject immediately preceding the value (no table guess).
            subject_prefix = re.split(r"계약일|착수일|납품일", prefix)[0]
            subject = _subject(subject_prefix)
        if not subject or len(subject) > 100 or re.search(r"[|\t]", prefix + following):
            errors.add("quantity_relation_ambiguous")
        context = prefix + following
        vat_labels = set(re.findall(r"(?:VAT|부가세|부가가치세)\s*([가-힣]+)", context, re.I))
        vat = None
        if vat_labels:
            normalized = {"included" if v.startswith("포함") else "excluded" if v.startswith(("제외", "별도")) else "ambiguous" for v in vat_labels}
            if len(normalized) != 1 or "ambiguous" in normalized:
                errors.add("quantity_relation_ambiguous")
            else:
                vat = next(iter(normalized))
        bases = {value for label, value in _BASIS.items() if label in context}
        if len(bases) > 1:
            errors.add("quantity_relation_ambiguous")
        quantities.append(ExtractedQuantity(
            subject=subject, role=role, value=Decimal(match["value"].replace(",", "").replace("−", "-")), unit=unit,
            currency="KRW" if unit in _MONEY else None, vat=vat if unit in _MONEY else None,
            period_basis=next(iter(bases)) if len(bases) == 1 and role == "period" else None,
        ))
        masked[match.start():match.end()] = " " * (match.end() - match.start())
    if re.search(r"\d", "".join(masked)):
        errors.add("quantity_unit_missing")
    return quantities, errors


def _metadata_key(quantity: Quantity) -> tuple:
    return ExtractedQuantity(
        _subject(quantity.subject), quantity.role, Decimal(quantity.value_decimal), quantity.unit,
        quantity.currency, quantity.vat, quantity.period_basis,
    ).key()


def _dates(text: str) -> Counter:
    values = []
    for match in _DATE.finditer(text):
        parts = match.groups()[:3] if match[1] else match.groups()[3:]
        prefix = re.split(r"[.;,\n]", text[:match.start()])[-1]
        labels = list(_DATE_ROLE.finditer(prefix))
        role = labels[-1][0] if labels else "unlabelled"
        subject = _subject(prefix[:labels[-1].start()]) if labels else ""
        try:
            values.append((date(*(int(value) for value in parts)).isoformat(), role, subject))
        except ValueError:
            values.append(("invalid_date", role, subject))
    return Counter(values)


def _literal_checks(text: str, source: str) -> set[str]:
    errors: set[str] = set()
    if _dates(text) - _dates(source) or any(key[0] == "invalid_date" for key in _dates(text)):
        errors.add("date_mismatch")
    if Counter(_ID.findall(text)) - Counter(_ID.findall(source)):
        errors.add("requirement_id_mismatch")
    source_folded = re.sub(r"\s+", "", source).casefold()
    if any(word.casefold() not in source_folded for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)):
        errors.add("latin_term_mismatch")
    return errors


def validate_claims_deterministically(
    draft: OverviewClaimsDraft, pages: dict[int, str], *, attempt_id: UUID,
    input_sha256: str, policy_digest: str, binding_digest: str,
    company_comparison_performed: bool = False,
) -> OverviewClaimChecks:
    draft = parse_claims_draft(draft)
    global_errors: set[str] = set()
    if not pages or len(pages) > LIMITS["max_pages"] or sum(len(t) for t in pages.values()) > LIMITS["max_page_text_chars"]:
        global_errors.add("input_limit_exceeded")
    if not all(any(c.section == section for c in draft.claims) for section in FACT_SECTIONS[:2]):
        global_errors.add("required_fact_missing")
    ids = [item.id for item in [*draft.claims, *draft.analysis, *draft.unknowns]]
    if len(set(ids)) != len(ids):
        global_errors.add("duplicate_id")
    checks = []
    for claim in draft.claims:
        errors: set[str] = set()
        verified = []
        indexed: dict[int, VerifiedEvidence] = {}
        if not claim.text.strip():
            errors.add("fact_empty")
        if not claim.evidence:
            errors.add("evidence_missing")
        for i, evidence in enumerate(claim.evidence):
            try:
                item = verify_evidence(evidence, pages)
                indexed[i] = item
                verified.append(item)
            except ValueError as error:
                errors.add(str(error))
        source = "\n".join(e.quote for e in verified)
        errors.update(_literal_checks(claim.text, source))
        extracted, quantity_errors = extract_quantities(claim.text)
        errors.update(quantity_errors)
        claim_keys = Counter(q.key() for q in extracted)
        metadata_keys = Counter(_metadata_key(q) for q in claim.quantities)
        if claim_keys != metadata_keys:
            errors.add("quantity_metadata_mismatch")
        source_keys: Counter = Counter()
        for evidence in verified:
            source_quantities, source_errors = extract_quantities(evidence.quote)
            if extracted:
                errors.update(source_errors)
            source_keys.update(q.key() for q in source_quantities)
        if claim_keys - source_keys:
            errors.add("quantity_mismatch")
        for quantity in claim.quantities:
            if quantity.evidence_index not in indexed:
                errors.add("quantity_metadata_mismatch")
                continue
            selected, selected_errors = extract_quantities(indexed[quantity.evidence_index].quote)
            errors.update(selected_errors)
            if _metadata_key(quantity) not in {q.key() for q in selected}:
                errors.add("quantity_metadata_mismatch")
        checks.append(ClaimCheck(
            claim_id=claim.id, section=claim.section, text=claim.text,
            deterministic=DeterministicCheck(status="failed" if errors else "passed", reason_codes=sorted(errors), verified_evidence=verified),
            semantic=SemanticCheck(status="not_run", reason_codes=[]),
        ))
    by_id = {claim.id: claim for claim in draft.claims}
    analysis_checks = []
    for analysis in draft.analysis:
        reasons = []
        if not analysis.text.strip() or not analysis.supporting_claim_ids or len(set(analysis.supporting_claim_ids)) != len(analysis.supporting_claim_ids) or set(analysis.supporting_claim_ids) - set(by_id):
            global_errors.add("analysis_reference_missing")
            reasons.append("analysis_premise_unverified")
        else:
            source = "\n".join(by_id[key].text for key in analysis.supporting_claim_ids)
            # Exact numeric spellings preserve dates, IDs and decimal precision.
            # New numbers in opinions cannot hide behind a supported judgment.
            if Counter(re.findall(_NUMBER, analysis.text)) - Counter(re.findall(_NUMBER, source)) or _literal_checks(analysis.text, source):
                global_errors.add("analysis_premise_unverified")
                reasons.append("analysis_premise_unverified")
            aq, _ = extract_quantities(analysis.text)
            sq, _ = extract_quantities(source)
            if Counter(_numeric_key(q.value, q.unit) for q in aq) - Counter(_numeric_key(q.value, q.unit) for q in sq):
                global_errors.add("analysis_premise_unverified")
                if not reasons:
                    reasons.append("analysis_premise_unverified")
        analysis_checks.append(AnalysisCheck(analysis_id=analysis.id, status="not_run", reason_codes=reasons))
    unknown_checks = []
    for unknown in draft.unknowns:
        reasons = []
        company = unknown.topic == "company_comparison"
        not_performed = unknown.reason_code == "company_comparison_not_performed"
        if company != not_performed:
            global_errors.add("unknown_reason_mismatch")
            reasons.append("company_comparison_scope_mismatch")
        elif company and company_comparison_performed:
            global_errors.add("company_comparison_scope_mismatch")
            reasons.append("company_comparison_scope_mismatch")
        unknown_checks.append(UnknownCheck(unknown_id=unknown.id, status="not_run", reason_codes=reasons))
    return OverviewClaimChecks(
        schema_version=CHECKS_SCHEMA, attempt_id=attempt_id, draft_sha256=canonical_sha256(draft),
        input_sha256=input_sha256, policy_digest=policy_digest, binding_digest=binding_digest,
        validator_version=VALIDATOR_VERSION, checks=checks, analysis_checks=analysis_checks,
        unknown_checks=unknown_checks, analysis=draft.analysis, unknowns=draft.unknowns,
        reason_codes=sorted(global_errors), overall="needs_human_review",
    )


def _coverage(actual: list[str], expected: list[str]) -> bool:
    return len(actual) == len(set(actual)) and set(actual) == set(expected) and len(actual) == len(expected)


def _verify_draft_binding(draft: OverviewClaimsDraft, checks: OverviewClaimChecks) -> None:
    if checks.draft_sha256 != canonical_sha256(draft) or not _coverage([c.claim_id for c in checks.checks], [c.id for c in draft.claims]) or not _coverage(
        [c.analysis_id for c in checks.analysis_checks], [c.id for c in draft.analysis]
    ) or not _coverage([c.unknown_id for c in checks.unknown_checks], [c.id for c in draft.unknowns]):
        raise ValueError("verification_binding_mismatch")
    by_id = {claim.id: claim for claim in draft.claims}
    if any(row.text != by_id[row.claim_id].text or row.section != by_id[row.claim_id].section for row in checks.checks) or checks.analysis != draft.analysis or checks.unknowns != draft.unknowns:
        raise ValueError("verification_binding_mismatch")


def apply_semantic_review(
    draft: OverviewClaimsDraft, checks: OverviewClaimChecks, response: object,
) -> OverviewClaimChecks:
    if checks.reason_codes or not checks.checks or any(c.deterministic.status != "passed" for c in checks.checks):
        raise ValueError("deterministic_checks_failed")
    _verify_draft_binding(draft, checks)
    try:
        if isinstance(response, OverviewSemanticResponse):
            response = response.model_dump(mode="json")
        if isinstance(response, (str, bytes)):
            if len(response) > LIMITS["max_response_chars"]:
                raise ValueError
            response = json.loads(response, object_pairs_hook=_reject_duplicate_keys)
        if len(canonical_json(response)) > LIMITS["max_response_chars"]:
            raise ValueError
        parsed = OverviewSemanticResponse.model_validate(response)
    except (ValueError, TypeError):
        raise SemanticResponseError() from None
    if not _coverage([c.claim_id for c in parsed.checks], [c.id for c in draft.claims]) or not _coverage(
        [c.analysis_id for c in parsed.analysis_checks], [c.id for c in draft.analysis]
    ) or not _coverage([c.unknown_id for c in parsed.unknown_checks], [c.id for c in draft.unknowns]):
        raise SemanticResponseError()
    semantic_by_id = {c.claim_id: c for c in parsed.checks}
    result = checks.model_dump(mode="python")
    for row in result["checks"]:
        semantic = semantic_by_id[row["claim_id"]]
        row["semantic"] = {"status": semantic.status, "reason_codes": semantic.reason_codes}
    result["analysis_checks"] = [row.model_dump() for row in parsed.analysis_checks]
    result["unknown_checks"] = [row.model_dump() for row in parsed.unknown_checks]
    all_passed = all(c.status == "supported" for c in [*parsed.checks, *parsed.analysis_checks, *parsed.unknown_checks])
    result["overall"] = "passed" if all_passed else "needs_human_review"
    return OverviewClaimChecks.model_validate(result)


_TOPICS = {"budget": "예산", "period": "사업 기간", "eligibility": "참여 자격", "scope": "과업 범위", "schedule": "일정"}


def render_unknowns(draft: OverviewClaimsDraft | OverviewClaimChecks) -> list[str]:
    result = []
    for item in draft.unknowns:
        if item.topic == "company_comparison":
            result.append("회사 역량·참여 요건 대조는 수행하지 않았습니다.")
        elif item.reason_code == "ambiguous_source":
            result.append(f"검토한 입력에서 {_TOPICS[item.topic]}의 의미가 불명확하여 원문 확인이 필요합니다.")
        else:
            result.append(f"검토한 입력에서 {_TOPICS[item.topic]}을 확인하지 못했습니다.")
    return result


def build_input_limitations(
    reviewed_pages: list[int], *, pdf_page_count: int, conversion_warning_codes: list[str] = (),
) -> list[str]:
    if not reviewed_pages or len(set(reviewed_pages)) != len(reviewed_pages) or any(type(p) is not int or not 1 <= p <= pdf_page_count for p in reviewed_pages):
        raise ValueError("reviewed_pages_invalid")
    pages = ", ".join(str(p) for p in sorted(reviewed_pages))
    result = [
        f"PDF 총 {pdf_page_count}페이지 중 선택된 {pages}페이지의 입력 범위만 검토했습니다.",
        "PDF에서 추출한 텍스트만 검토했으며 표의 배치와 생략된 단위·열 관계를 추정하지 않았습니다.",
    ]
    if conversion_warning_codes:
        result.append("변환 과정에서 기록된 제한 사항이 있어 표·배치와 원문을 함께 확인해야 합니다.")
    return result


def compose_page_overview(
    draft: OverviewClaimsDraft, checks: OverviewClaimChecks, *, verification_id: UUID,
    input_limitations: list[str],
) -> PageOverviewPayloadV4:
    _verify_draft_binding(draft, checks)
    # Revalidate even when a caller used model_copy/update on an existing model.
    checks = OverviewClaimChecks.model_validate(checks.model_dump(mode="python"))
    if checks.overall != "passed":
        raise ValueError("verification_not_passed")
    by_id = {row.claim_id: row for row in checks.checks}
    result: dict[str, Any] = {section: [] for section in FACT_SECTIONS}
    for claim in draft.claims:
        result[claim.section].append({
            "claim_id": claim.id, "text": claim.text,
            "evidence": by_id[claim.id].deterministic.verified_evidence,
        })
    return PageOverviewPayloadV4(
        schema_version="bidops.prespec-overview-page-review.v4", **result,
        reviewer_analysis=draft.analysis, unknowns=render_unknowns(draft),
        input_limitations=input_limitations, verification_id=verification_id,
        verification_sha256=canonical_sha256(checks),
    )


def verify_composed_page_overview(
    payload: PageOverviewPayloadV4, draft: OverviewClaimsDraft, checks: OverviewClaimChecks,
) -> bool:
    """Downstream gate: match the entire deterministic composition and digest."""
    try:
        expected = compose_page_overview(draft, checks, verification_id=payload.verification_id, input_limitations=payload.input_limitations)
        return expected.model_dump(mode="json") == payload.model_dump(mode="json")
    except ValueError:
        return False


def validate_composed_page_overview(payload: object, checks: object) -> list[str]:
    """Recheck persisted v4 facts/analysis/unknowns without the model draft.

    Storage/currentness callers additionally bind verification_id, attempt and
    input/model/policy hashes to their append-only rows and frozen snapshot.
    """
    try:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        if hasattr(checks, "model_dump"):
            checks = checks.model_dump(mode="json")
        payload = PageOverviewPayloadV4.model_validate_json(canonical_json(payload))
        checks = OverviewClaimChecks.model_validate_json(canonical_json(checks))
    except (ValueError, TypeError):
        return ["verification_schema_invalid"]
    if checks.overall != "passed":
        return ["verification_not_passed"]
    if payload.verification_sha256 != canonical_sha256(checks):
        return ["verification_hash_mismatch"]
    for section in FACT_SECTIONS:
        expected = [
            {"claim_id": c.claim_id, "text": c.text, "evidence": [e.model_dump(mode="json") for e in c.deterministic.verified_evidence]}
            for c in checks.checks if c.section == section
        ]
        if [c.model_dump(mode="json") for c in getattr(payload, section)] != expected:
            return ["verification_content_mismatch"]
    if payload.reviewer_analysis != checks.analysis or payload.unknowns != render_unknowns(checks):
        return ["verification_content_mismatch"]
    return []
