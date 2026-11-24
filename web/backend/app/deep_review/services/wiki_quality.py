"""Project an explicitly reviewed evaluation. Never execute a model on a GET."""

from hashlib import sha256

from ..schemas.wiki_quality import Evaluation, Metric, Quality
from .company_wiki import WikiError


def versions(wiki):
    units = wiki.side_file("work-units.json")
    return dict(bundle_sha256=wiki.digest, work_units_sha256=(
        sha256(units.encode()).hexdigest() if units is not None else None
    ))


def quality(wiki):
    current = versions(wiki)
    if (wiki.root / "answer-evaluation.json").is_symlink():
        raise WikiError()
    raw = wiki.side_file("answer-evaluation.json")
    if raw is None:
        return Quality(status="unmeasured", **current)
    report = Evaluation.model_validate_json(raw)
    if any(getattr(report, key) != value for key, value in current.items()):
        return Quality(status="stale", **current)

    cases = report.cases
    claims = [claim for case in cases for claim in case.claims]
    citations = [cite for claim in claims for cite in claim.citations]
    # A human checks meaning. A quote also has to occur on the cited page.
    bodies = {}
    for cite in citations:
        if cite.page is None:
            cite.supports_claim = False
            continue
        if cite.page not in bodies:
            try:
                bodies[cite.page] = wiki._page(*cite.page.split("/")).body
            except WikiError as exc:
                if exc.status != 404:
                    raise
                bodies[cite.page] = ""
        cite.supports_claim = cite.supports_claim and cite.quote in bodies[cite.page]

    def metric(label, values, group="answer"):
        values = list(values)
        return Metric(group=group, label=label, numerator=sum(values), denominator=len(values))

    traced = [case for case in cases if case.read_pages is not None]
    hits, relevant_reads = [], []
    for case in traced:
        reads = set(case.read_pages)
        relevant = set(case.relevant_pages)
        for group in case.required_groups:
            hits.append(bool(reads.intersection(group)))
            relevant.update(group)
        relevant_reads.extend(page in relevant for page in reads)

    metrics = [
        metric("기대 결론과 일치", (c.correct for c in cases)),
        metric("인용이 주장을 뒷받침", (c.supports_claim for c in citations)),
        metric("인용으로 뒷받침한 주장", (any(c.supports_claim for c in claim.citations) for claim in claims)),
        metric("근거 없는 단정", (not c.grounded for c in claims)),
        metric("자료 부족 시 답변 보류", (c.abstained for c in cases if not c.answerable)),
        metric("답이 있는데 보류", (c.abstained for c in cases if c.answerable)),
        metric("읽기 기록이 있는 질문", (c.read_pages is not None for c in cases), "diagnostic"),
        metric("필수 근거 열람률 (Recall)", hits, "diagnostic"),
        metric("열람 페이지 관련도 (Precision)", relevant_reads, "diagnostic"),
        metric("채점 모델과 사람 일치", (c.judge_correct == c.correct for c in cases if c.judge_correct is not None), "diagnostic"),
    ]
    return Quality(status="reviewed", evaluation=report, metrics=metrics, **current)
