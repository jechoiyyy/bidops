"""Deterministic checks against physical PDF pages. Never mutates model output."""
import re
from pydantic import ValidationError
from ..schemas.page_overview import PageOverviewPayload

VALIDATOR_VERSION = "pdf-page-evidence.v2"
FACT_SECTIONS = ("business_overview", "main_tasks", "budget_and_period", "important_conditions")
# Only a complete trailing citation is metadata. Arbitrary parentheses remain facts.
CITATION = re.compile(r"\s*\((PDF\s*\d+\s*페이지(?:\s*[·,]\s*PDF\s*\d+\s*페이지)*|PDF\s*\d+(?:\s*[,·]\s*\d+)*\s*페이지)\)\s*$")


def fold_space(text: str) -> str:
    return re.sub(r"\s+", "", text)


def fact_text(text: str, pages: list[int]) -> tuple[str, bool]:
    citation = CITATION.search(text)
    if not citation:
        return text, True
    cited = {int(n) for n in re.findall(r"\d+", citation.group(1))}
    if cited != set(pages):
        return text, False
    return text[:citation.start()], True


def validate_page_overview(output: object, pages: dict[int, str]) -> list[str]:
    try:
        payload = PageOverviewPayload.model_validate(output)
    except ValidationError:
        return ["schema_invalid"]
    errors: set[str] = set()
    for section in FACT_SECTIONS:
        for fact in getattr(payload, section):
            if any(n not in pages for n in fact.evidence_pages):
                errors.add("pdf_locator_mismatch")
                continue
            text, valid_citation = fact_text(fact.text, fact.evidence_pages)
            if not text.strip():
                errors.add("fact_empty")
            if not valid_citation:
                errors.add("pdf_inline_locator_mismatch")
            source = fold_space(" ".join(pages[n] for n in fact.evidence_pages))
            numbers = lambda s: {str(int(n)) for n in re.findall(r"\d+", fold_space(s).replace(",", ""))}
            if numbers(text) - numbers(source):
                errors.add("fact_number_not_on_cited_pages")
            for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text):
                if fold_space(word).lower() not in source.lower():
                    errors.add("latin_term_not_on_cited_pages")
            if "계약금액" in fold_space(text) and "계약금액" not in source:
                errors.add("budget_mislabelled_as_contract_amount")
    return sorted(errors)
