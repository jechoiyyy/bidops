"""Deterministic diagnostics for text displayed in Analysis."""

import re
from collections.abc import Iterator

from bid_deep_engine.analysis.schemas import Analysis, LanguageWarning, RequirementCounts
from bid_deep_engine.ingest.models import RfpDocument

_HAN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\U00020000-\U0002fa1f\U00030000-\U000323af]+"
)


# Standalone lowercase prose such as "budgets". Exclude IDs, paths and acronyms.
_ENGLISH = re.compile(r"(?<!\S)[a-z]{3,}(?=\s|[.,;!?](?:\s|$)|$)")


def _strings(value: object, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _strings(child, f"{path}[{index}]")


def annotate_output(analysis: Analysis, doc: RfpDocument, company_text: str) -> None:
    # Counts refer to normalized source occurrences and the actual match output coverage.
    detail_count = sum(t.kind == "requirement_detail" for t in doc.tables)
    keys = {r.key for r in doc.requirements}
    analysis.requirement_counts = RequirementCounts(
        source_found=detail_count or len(doc.requirements),
        source_expected=doc.source_quality.requirements_expected,
        analysis_input=len(keys.intersection(f.key for f in analysis.fits)),
    )
    corpus = doc.full_text + "\n" + company_text
    english_source = set(re.findall(r"[a-z]+", corpus.lower()))
    upstream = {
        "extract": analysis.facts.model_dump_json(),
        "match": "\n".join(f.model_dump_json() for f in analysis.fits),
        "synth": analysis.synth_output.model_dump_json() if analysis.synth_output else "",
    }
    analysis.language_warnings = []
    for group, stage in (
        ("gates", "extract"),
        ("fits", "match"),
        ("risks", "synth"),
        ("recommendation", None),
        ("review_actions", None),
    ):
        value = analysis.model_dump(mode="json", include={group})[group]
        for path, sentence in _strings(value, group):
            unknown = list(
                dict.fromkeys(term for term in _HAN.findall(sentence) if term not in corpus)
            )
            if re.search(r"[가-힣]", sentence):
                unknown.extend(
                    dict.fromkeys(w for w in _ENGLISH.findall(sentence) if w not in english_source)
                )
            if unknown:
                retry = stage
                if stage is None:
                    candidates = [
                        p for p, text in upstream.items() if all(term in text for term in unknown)
                    ]
                    retry = candidates[0] if len(candidates) == 1 else None
                analysis.language_warnings.append(
                    LanguageWarning(path=path, terms=unknown, retry_pass=retry)
                )
