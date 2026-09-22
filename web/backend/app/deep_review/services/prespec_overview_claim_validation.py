"""Pure evidence/claim gates and deterministic publication of the overview result.

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
    CHECKS_SCHEMA, FACT_SECTIONS, RESULT_SCHEMA, VALIDATOR_VERSION, ClaimCheck,
    ClaimEvidence, DeterministicCheck, OverviewClaimChecks, OverviewClaimsDraft,
    OverviewResultPayload, OverviewSemanticResponse, Quantity, SemanticCheck,
    VerifiedEvidence,
)
from .prespec_overview_claim_policy import FORMAT_RETRY_CODES, LIMITS, canonical_json, canonical_sha256


#: 인용 자체는 성립하지만 대조가 어긋난 관찰. 사람이 원문과 함께 확인할
#: 값이며 결정적 검사를 실패로 만들지 않는다 (MVP 계약, 2026-09-11). 인용
#: 대응·페이지 범위·중복 id·analysis 참조만 실패로 남는다.
#:
#: `required_fact_missing`(섹션 배정 쏠림)과 `evidence_fragment_match`(2단
#: 편집 쪽의 조각 대조)는 2026-09-11 운영 첫 실행 결과로 경고가 됐다. 주장이
#: 0개인 것은 여전히 사람 검토이며 run이 `claims_empty`로 닫는다.
#: `evidence_dropped`와 `semantic_extra_ids`는 ADR-0057 결정 3이 더한 경고다.
#: 앞은 인용 둘 중 하나만 대조에 실패해 그 인용만 뺐다는 뜻이고, 뒤는 의미
#: 검토 응답에 기대 밖 ID가 섞였으나 기대 ID는 모두 한 번씩 있었다는 뜻이다.
WARNING_REASON_CODES = frozenset({
    "required_fact_missing",
    "evidence_fragment_match",
    "evidence_dropped",
    "semantic_extra_ids",
    "quantity_mismatch",
    "quantity_metadata_mismatch",
    "quantity_relation_ambiguous",
    "quantity_unit_missing",
    "date_mismatch",
    "requirement_id_mismatch",
    "latin_term_mismatch",
})


def _split_reasons(codes: set[str]) -> tuple[list[str], list[str]]:
    """실패 코드와 경고 코드를 나눈다. 순서는 결정적이다."""

    return (
        sorted(code for code in codes if code not in WARNING_REASON_CODES),
        sorted(code for code in codes if code in WARNING_REASON_CODES),
    )


class ClaimDraftError(ValueError):
    """Safe parser classification; never embeds the model's text in errors."""

    def __init__(self, code: str):
        self.code = code
        self.retryable = code in FORMAT_RETRY_CODES
        super().__init__(code)


class SemanticResponseError(ValueError):
    """의미 검토 응답을 받을 수 없는 이유. run의 `reason_codes`에 그대로 남는다.

    `semantic_schema_invalid`(스키마·상한 위반), `semantic_missing_ids`(기대
    주장 판정 누락), `semantic_duplicate_ids`(같은 주장에 두 판정)로 나뉜다.
    기대 밖 ID는 실패가 아니라 경고 `semantic_extra_ids`다 (ADR-0057 결정 3).
    """

    def __init__(self, code: str = "semantic_response_invalid"):
        self.code = code
        super().__init__(code)


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
        validator_version=VALIDATOR_VERSION, checks=[],
        reason_codes=[error.code], overall="needs_human_review",
    )


def _space_map(text: str) -> tuple[str, list[int]]:
    offsets = [i for i, char in enumerate(text) if not char.isspace()]
    return "".join(text[i] for i in offsets), offsets


#: 인용을 자르는 경계: 생략 기호, 줄바꿈, 리스트 표식 바로 앞. 2단(두 열)
#: 편집 쪽의 텍스트는 좌·우 열을 **줄 단위로 번갈아** 내보내므로 한 열에서
#: 뽑은 인용은 원문에서 연속하지 않는다.
#:
#: 앞의 두 갈래(`…`·`...`·개행)는 **먹는** 경계다 — 생략 기호와 개행은 원문의
#: 그 자리에 없으므로 조각에 남기면 대조가 깨진다. 리스트 표식은 폭 0으로
#: 잘라 뒤 조각에 남겨 대조에 쓴다 (ADR-0057 결정 3이 생략 기호를 더했다).
_FRAGMENT_BOUNDARY = re.compile(
    r"…+|\.{3,}|\n|(?:^|(?<=\s))(?=(?:[가나다라마바사아자차카타파하]|\d{1,2})\s*[.)]\s|[○●□■◇◆▶▷•·]|-\s)"
)
#: 이보다 짧은 조각(공백 제거 기준)은 혼자서는 한 곳을 가리키지 못한다.
_MIN_FRAGMENT_CHARS = 6


def _matches(normalized: str, needle: str) -> list[int]:
    # Count overlaps too: ambiguity must not depend on Python's str.count.
    return [m.start() for m in re.finditer(f"(?={re.escape(needle)})", normalized)]


def _fragments(quote: str) -> list[str]:
    """인용을 줄·리스트 표식 경계로 자른다. 짧은 조각은 앞 조각에 붙인다."""

    pieces: list[str] = []
    position = 0
    for match in _FRAGMENT_BOUNDARY.finditer(quote):
        pieces.append(quote[position:match.start()])
        # 폭 0 경계(리스트 표식)는 `end == start`이므로 표식이 뒤 조각에 남고,
        # 생략 기호·개행은 `end > start`라 조각에서 빠진다.
        position = max(position, match.end())
    pieces.append(quote[position:])
    fragments: list[str] = []
    for piece in pieces:
        compact, _ = _space_map(piece)
        if not compact:
            continue
        if fragments and len(compact) < _MIN_FRAGMENT_CHARS:
            fragments[-1] += piece
        else:
            fragments.append(piece)
    return fragments


def _fragment_span(normalized: str, quote: str) -> tuple[int, int]:
    """조각 대조. 조각마다 정확히 1곳이고 시작이 커지는 순서일 때만 통과한다.

    조각이 하나뿐이면 연속 대조와 같은 질문이므로 다시 묻지 않는다. 순서가
    어긋나면 같은 낱말이 다른 문맥에서 우연히 맞은 것으로 보고 닫는다.
    """

    fragments = _fragments(quote)
    if len(fragments) < 2:
        raise ValueError("quote_not_found")
    spans: list[tuple[int, int]] = []
    for fragment in fragments:
        compact, _ = _space_map(fragment)
        found = _matches(normalized, compact)
        if not found:
            raise ValueError("quote_not_found")
        if len(found) != 1:
            raise ValueError("quote_ambiguous")
        spans.append((found[0], found[0] + len(compact)))
    if any(later[0] <= earlier[0] for earlier, later in zip(spans, spans[1:])):
        raise ValueError("quote_not_found")
    return spans[0][0], spans[-1][1]


def verify_evidence(evidence: ClaimEvidence, pages: dict[int, str]) -> VerifiedEvidence:
    return verify_evidence_span(evidence, pages)[0]


def verify_evidence_span(evidence: ClaimEvidence, pages: dict[int, str]) -> tuple[VerifiedEvidence, bool]:
    """검증된 근거와 "조각 대조로 통과했는가"를 함께 돌려준다.

    NFKC 정규화는 하지 않는다. 원문 offset을 그대로 보존하는 쪽이 먼저다.
    """

    if evidence.page not in pages:
        raise ValueError("page_out_of_range")
    page = pages[evidence.page]
    normalized, offsets = _space_map(page)
    quote, _ = _space_map(evidence.quote)
    if not quote:
        raise ValueError("quote_empty")
    matches = _matches(normalized, quote)
    fragment_match = False
    if len(matches) == 1:
        first, last = matches[0], matches[0] + len(quote)
    elif matches:
        raise ValueError("quote_ambiguous")
    else:
        first, last = _fragment_span(normalized, evidence.quote)
        fragment_match = True
    start = offsets[first]
    end = offsets[last - 1] + 1
    if end - start > 2000:
        raise ValueError("input_limit_exceeded")
    return VerifiedEvidence(
        page=evidence.page, quote=page[start:end], start_char=start, end_char=end,
        page_text_sha256=hashlib.sha256(page.encode("utf-8")).hexdigest(),
    ), fragment_match


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


#: 인용 하나가 이 사유로 어긋났을 때만 그 인용을 빼고 주장을 살린다. 페이지
#: 범위 밖·빈 인용처럼 구조가 깨진 근거는 뺄 대상이 아니다.
_DROPPABLE_EVIDENCE_REASONS = frozenset({"quote_not_found", "quote_ambiguous"})


def validate_claims_deterministically(
    draft: OverviewClaimsDraft, pages: dict[int, str], *, attempt_id: UUID,
    input_sha256: str, policy_digest: str, binding_digest: str,
) -> OverviewClaimChecks:
    draft = parse_claims_draft(draft)
    global_errors: set[str] = set()
    if not pages or len(pages) > LIMITS["max_pages"] or sum(len(t) for t in pages.values()) > LIMITS["max_page_text_chars"]:
        # 동결 입력이 상한을 넘은 것은 주장의 문제가 아니라 실행 자체가 성립하지
        # 않는다는 뜻이다. 검사 결과로 접지 않고 올려서 run을 닫게 한다.
        raise ValueError("input_limit_exceeded")
    if not all(any(c.section == section for c in draft.claims) for section in FACT_SECTIONS[:2]):
        global_errors.add("required_fact_missing")
    ids = [claim.id for claim in draft.claims]
    if len(set(ids)) != len(ids):
        global_errors.add("duplicate_id")
    checks = []
    for claim in draft.claims:
        errors: set[str] = set()
        verified = []
        indexed: dict[int, VerifiedEvidence] = {}
        evidence_errors: dict[int, str] = {}
        if not claim.text.strip():
            errors.add("fact_empty")
        if not claim.evidence:
            errors.add("evidence_missing")
        for i, evidence in enumerate(claim.evidence):
            try:
                item, fragment_match = verify_evidence_span(evidence, pages)
                indexed[i] = item
                verified.append(item)
                if fragment_match:
                    errors.add("evidence_fragment_match")
            except ValueError as error:
                evidence_errors[i] = str(error)
        # 인용이 둘이고 하나만 대조에 실패하면 **그 인용만** 빼고 주장은 남긴다
        # (ADR-0057 결정 3). 검증된 인용이 하나도 없으면 종전대로 실패다.
        if (len(claim.evidence) == 2 and len(evidence_errors) == 1 and verified
                and set(evidence_errors.values()) <= _DROPPABLE_EVIDENCE_REASONS):
            errors.add("evidence_dropped")
        else:
            errors.update(evidence_errors.values())
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
        failures, warnings = _split_reasons(errors)
        checks.append(ClaimCheck(
            claim_id=claim.id, section=claim.section, text=claim.text,
            deterministic=DeterministicCheck(status="failed" if failures else "passed", reason_codes=failures, verified_evidence=verified),
            semantic=SemanticCheck(status="not_run", reason_codes=[]),
            warnings=warnings,
        ))
    global_failures, global_warnings = _split_reasons(global_errors)
    return OverviewClaimChecks(
        schema_version=CHECKS_SCHEMA, attempt_id=attempt_id, draft_sha256=canonical_sha256(draft),
        input_sha256=input_sha256, policy_digest=policy_digest, binding_digest=binding_digest,
        validator_version=VALIDATOR_VERSION, checks=checks,
        reason_codes=global_failures,
        warnings=sorted({
            *global_warnings,
            *(code for row in checks for code in row.warnings),
        }),
        overall="needs_human_review",
    )


@dataclass(frozen=True)
class PassingSubset:
    """결정적 검사를 통과한 주장만 남긴 계산용 부분집합 (저장 계약이 아니다)."""

    draft: OverviewClaimsDraft
    checks: OverviewClaimChecks
    dropped_claim_ids: tuple[str, ...]


def drop_failed_claims(draft: OverviewClaimsDraft, checks: OverviewClaimChecks) -> PassingSubset:
    """실패한 주장을 빼고 나머지로 계속 갈 수 있는 부분집합을 만든다.

    12개 중 1~2개만 인용이 어긋난 run을 통째로 사람 검토로 보내지 않기 위한
    규칙이다(2026-09-11 결정). 호출자가 원래 draft·checks를 그대로 저장하고,
    이 결과는 의미 검토·구성 입력으로만 쓴다. 통과 주장 수의 하한(절반)은
    호출자가 판단한다.
    """

    failed = {row.claim_id for row in checks.checks if row.deterministic.status != "passed"}
    if not failed:
        return PassingSubset(draft, checks, ())
    subset_draft = OverviewClaimsDraft.model_validate({
        **draft.model_dump(mode="python"),
        "claims": [c.model_dump(mode="python") for c in draft.claims if c.id not in failed],
    })
    data = checks.model_dump(mode="python")
    data["checks"] = [row for row in data["checks"] if row["claim_id"] not in failed]
    data["draft_sha256"] = canonical_sha256(subset_draft)
    return PassingSubset(
        subset_draft, OverviewClaimChecks.model_validate(data), tuple(sorted(failed)),
    )


def merge_semantic_checks(checks: OverviewClaimChecks, reviewed: OverviewClaimChecks) -> OverviewClaimChecks:
    """부분집합의 의미 판정을 전체 검사 결과에 id로 되붙인다.

    저장되는 `checks_json`은 제외된 주장까지 담은 전체가 정본이며, 그래서
    `failed_claims` 투영이 계속 그 한 곳에서 계산된다. 제외가 하나라도 있으면
    전체의 `overall`은 통과가 아니다.
    """

    if [row.claim_id for row in checks.checks] == [row.claim_id for row in reviewed.checks]:
        # 제외된 주장이 없으면 부분집합이 곧 전체다. 판정 결과를 그대로 쓴다.
        return reviewed
    semantic = {row.claim_id: row.semantic for row in reviewed.checks}
    data = checks.model_dump(mode="python")
    for row in data["checks"]:
        found = semantic.get(row["claim_id"])
        if found is not None:
            row["semantic"] = found.model_dump(mode="python")
    data["warnings"] = sorted({*checks.warnings, *reviewed.warnings})
    data["overall"] = "needs_human_review"
    return OverviewClaimChecks.model_validate(data)


def _coverage(actual: list[str], expected: list[str]) -> bool:
    return len(actual) == len(set(actual)) and set(actual) == set(expected) and len(actual) == len(expected)


def _verify_draft_binding(draft: OverviewClaimsDraft, checks: OverviewClaimChecks) -> None:
    if checks.draft_sha256 != canonical_sha256(draft) or not _coverage(
        [c.claim_id for c in checks.checks], [c.id for c in draft.claims]
    ):
        raise ValueError("verification_binding_mismatch")
    by_id = {claim.id: claim for claim in draft.claims}
    if any(row.text != by_id[row.claim_id].text or row.section != by_id[row.claim_id].section for row in checks.checks):
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
        raise SemanticResponseError("semantic_schema_invalid") from None
    # 기대 주장 ID가 모두 **정확히 한 번씩** 있으면 그 밖의 항목은 무시하고
    # 경고만 남긴다 (ADR-0057 결정 3). 누락·중복은 그대로 실패다 — 판정이
    # 없는 주장을 통과로 올리거나 두 판정 중 하나를 골라서는 안 된다.
    expected = [claim.id for claim in draft.claims]
    seen = Counter(row.claim_id for row in parsed.checks)
    if any(seen[claim_id] == 0 for claim_id in expected):
        raise SemanticResponseError("semantic_missing_ids")
    if any(seen[claim_id] > 1 for claim_id in expected):
        raise SemanticResponseError("semantic_duplicate_ids")
    semantic_by_id = {c.claim_id: c for c in parsed.checks if c.claim_id in set(expected)}
    result = checks.model_dump(mode="python")
    for row in result["checks"]:
        semantic = semantic_by_id[row["claim_id"]]
        row["semantic"] = {"status": semantic.status, "reason_codes": semantic.reason_codes}
    if len(seen) > len(expected):
        result["warnings"] = sorted({*checks.warnings, "semantic_extra_ids"})
    all_passed = all(semantic_by_id[claim_id].status == "supported" for claim_id in expected)
    result["overall"] = "passed" if all_passed else "needs_human_review"
    return OverviewClaimChecks.model_validate(result)


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
) -> OverviewResultPayload:
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
    return OverviewResultPayload(
        schema_version=RESULT_SCHEMA, **result,
        input_limitations=input_limitations, verification_id=verification_id,
        verification_sha256=canonical_sha256(checks),
    )


def compose_deterministic_page_overview(
    draft: OverviewClaimsDraft, checks: OverviewClaimChecks, *, verification_id: UUID,
    input_limitations: list[str],
) -> OverviewResultPayload:
    """Compose a v8 screen result without claiming semantic verification passed."""

    _verify_draft_binding(draft, checks)
    checks = OverviewClaimChecks.model_validate(checks.model_dump(mode="python"))
    if (
        checks.reason_codes
        or not checks.checks
        or any(row.deterministic.status != "passed" for row in checks.checks)
    ):
        raise ValueError("deterministic_verification_not_passed")
    by_id = {row.claim_id: row for row in checks.checks}
    result: dict[str, Any] = {section: [] for section in FACT_SECTIONS}
    for claim in draft.claims:
        result[claim.section].append({
            "claim_id": claim.id,
            "text": claim.text,
            "evidence": by_id[claim.id].deterministic.verified_evidence,
        })
    return OverviewResultPayload(
        schema_version=RESULT_SCHEMA,
        **result,
        input_limitations=input_limitations,
        verification_id=verification_id,
        verification_sha256=canonical_sha256(checks),
    )


def empty_sections(payload: OverviewResultPayload) -> list[str]:
    """비어 있는 절의 경고 코드. 예산·기간이 선택 범위에 없으면 남는다."""

    return [f"section_empty:{section}" for section in FACT_SECTIONS if not getattr(payload, section)]


def verify_composed_page_overview(
    payload: OverviewResultPayload, draft: OverviewClaimsDraft, checks: OverviewClaimChecks,
) -> bool:
    """Downstream gate: match the entire deterministic composition and digest."""
    try:
        expected = compose_page_overview(draft, checks, verification_id=payload.verification_id, input_limitations=payload.input_limitations)
        return expected.model_dump(mode="json") == payload.model_dump(mode="json")
    except ValueError:
        return False


def validate_composed_page_overview(payload: object, checks: object) -> list[str]:
    """Recheck the persisted facts without the model draft.

    Storage/currentness callers additionally bind verification_id, attempt and
    input/model/policy hashes to their append-only rows and frozen snapshot.
    """
    try:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        if hasattr(checks, "model_dump"):
            checks = checks.model_dump(mode="json")
        payload = OverviewResultPayload.model_validate_json(canonical_json(payload))
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
    return []
