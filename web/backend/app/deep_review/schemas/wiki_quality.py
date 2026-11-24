"""Human-reviewed answers and observed page reads for a fixed wiki snapshot."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
PageId = Annotated[str, Field(pattern=r"^(category|capability|portfolio|rule|glossary)/[A-Za-z0-9][A-Za-z0-9-]*$")]
Text = Annotated[str, Field(min_length=1)]
Count = Annotated[int, Field(strict=True, ge=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Citation(Record):
    page: PageId
    quote: Text
    supports_claim: bool


class Claim(Record):
    text: Text
    grounded: bool
    citations: list[Citation]


class Case(Record):
    id: Text
    question: Text
    expected_answer: Text
    answer: Text
    answerable: bool
    abstained: bool
    correct: bool
    reviewer_note: Text
    claims: list[Claim]
    required_groups: list[Annotated[list[PageId], Field(min_length=1)]]
    relevant_pages: list[PageId] = []
    # Null means no complete trace. Repeated successful reads remain separate.
    read_pages: list[PageId] | None
    tool_calls: Count | None
    tokens: Count | None
    duration_ms: Count | None = None
    judge_correct: bool | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.read_pages is not None and self.tool_calls is not None and self.tool_calls < len(self.read_pages):
            raise ValueError("tool count smaller than number of reads")
        return self


class Evaluation(Record):
    schema_version: Literal["bidops.wiki-evaluation.v1"]
    bundle_sha256: Digest
    work_units_sha256: Digest | None
    dataset_version: Text
    model_version: Text
    judge_version: Text | None = None
    rubric_version: Text
    reviewer: Text
    reviewed_on: date
    cases: Annotated[list[Case], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case")
        if any(case.judge_correct is not None for case in self.cases) and not self.judge_version:
            raise ValueError("judge version required")
        return self


class Metric(Record):
    group: Literal["answer", "diagnostic"] = "answer"
    label: str
    numerator: int
    denominator: int


class Quality(Record):
    bundle_sha256: Digest
    work_units_sha256: Digest | None
    status: Literal["unmeasured", "stale", "reviewed"]
    evaluation: Evaluation | None = None
    metrics: list[Metric] = []
