"""Deterministic pre-specification overview preparation.

This module owns the small, fail-closed transition from a clean immutable
``DocumentStructure`` to a pre-spec overview input snapshot.  It does not
invoke a model provider.  A snapshot is either a reproducible structure cut
or an explicit ``unknown``/``failed`` record that remains available for human
review.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.model_client import (
    ModelClient,
    ModelEndpointError,
    ModelIdentity,
    ModelIdentityError,
    StructuredOutputContract,
)
from ...core.models import AuditEvent
from ..document_mcp.contracts import validate_structure
from ..models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentStructure,
    DocumentVersion,
    PRESPEC_OVERVIEW_ATTEMPT_TRANSITIONS,
    PreSpecOverviewAttempt,
    PreSpecOverviewAttemptEvent,
    PreSpecOverviewResult,
    PreSpecOverviewReview,
    PreSpecOverviewSnapshot,
)
from ...lifecycle import lock_notice
from ...lifecycle.models import Notice
from ..schemas.prespec_overview import (
    PreSpecOverviewAttemptView,
    PreSpecOverviewAttemptV2View,
    PreSpecOverviewResultPayload,
    PreSpecOverviewResultView,
    PreSpecOverviewReviewView,
    PreSpecOverviewReviewV2View,
    PreSpecOverviewReviewsResponse,
    PreSpecOverviewReviewsV2Response,
    PreSpecOverviewSnapshotView,
    PreSpecOverviewValidationStatus,
)
from . import assets


OVERVIEW_SCHEMA_VERSION = "bidops.prespec-overview-reviews.v1"
OVERVIEW_REVIEW_STATUSES = frozenset(
    {
        "awaiting_document",
        "awaiting_structure",
        "preparing",
        "awaiting_model",
        "queued",
        "running",
        "needs_human_review",
        "completed",
        "failed",
        "cancelled",
    }
)
OVERVIEW_CUT_STATUSES = frozenset({"pending", "ready", "unknown", "failed"})
OVERVIEW_ATTEMPT_STATUSES = frozenset(
    {"queued", "running", "completed", "failed", "cancelled"}
)
_PRESERVE_REVIEW_STATUSES = frozenset(
    {"queued", "running", "completed", "failed", "cancelled"}
)

# These limits are intentionally independent from the document extractor's
# much larger contract limits.  The overview stage is a bounded prefix input;
# exceeding this limit is an ``unknown`` result, never a whole-document
# fallback.
MAX_OVERVIEW_INPUT_BLOCKS = 10_000
MAX_OVERVIEW_INPUT_BYTES = 8 * 1024 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NUMBERING_ONLY = re.compile(
    r"^[\s\d\W_]+$|^[\s]*(?:[ivxlcdm]+|[가-힣])(?:[.)、·\-:]?\s*)*$",
    re.IGNORECASE,
)
_PAGE_SUFFIX = re.compile(r"(?:\s*[.·…]{2,}\s*|\s+)(\d{1,5})\s*$")
_WHITESPACE = re.compile(r"\s+")
_GENERIC_HEADINGS = frozenset(
    {
        "목차",
        "contents",
        "table of contents",
        "tableofcontents",
        "페이지",
        "page",
        "쪽",
    }
)
_HEADING_TYPES = frozenset(
    {
        "heading",
        "section_heading",
        "chapter_heading",
        "subheading",
        "title_heading",
    }
)
_TOC_TYPES = frozenset(
    {
        "toc",
        "toc_item",
        "table_of_contents",
        "contents_item",
    }
)
_TOC_ROLES = frozenset({"toc", "toc_item", "table_of_contents", "목차"})
_HEADING_ROLES = frozenset(
    {"heading", "section_heading", "chapter_heading", "subheading", "title"}
)
# T-21's heading-analysis artifact records only these exact topic labels in
# ``topics_in_order``.  The paragraph processor does not emit heading style or
# level metadata, so this allowlist is the only heading signal accepted on
# that path.  Matching is against the complete normalized paragraph; prose
# containing one of these words is not a match.
_TOPIC_HEADING_VOCABULARY = frozenset(
    {
        "과업내용",
        "사업개요",
        "사업기간",
        "사업예산",
        "일반사항",
        "제안절차",
        "추진목표",
        "추진배경",
        "용역개요",
    }
)
_PARAGRAPH_TOC_TITLES = frozenset({"목차", "차례"})
_LEADING_HEADING_BULLET = re.compile(
    r"^\s*[·•∙◦○●◉▪▫■□◆◇▶▷]\s*"
)
_LEADING_HEADING_BRACKET = re.compile(
    r"^\s*(?:[\(\[\{]\s*(?:\d+(?:\.\d+)*|[ivxlcdm]+|[가-힣])\s*[\)\]\}]|"
    r"[①-⑳⓵-⓿])\s*[.)、:：\-–—]?\s*",
    re.IGNORECASE,
)
_LEADING_HEADING_NUMBER = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*|[ivxlcdm]+|[ⅰⅱⅲⅳⅴⅵⅠⅡⅢⅣⅤⅥ]+|[가-힣])"
    r"\s*[.)、:：\-–—]\s*",
    re.IGNORECASE,
)
_LEADING_HEADING_PUNCTUATION = re.compile(
    r"^\s*[.,:;!?。．、:：\-–—/|]+\s*"
)
_WRAPPED_HEADING_OPEN = re.compile(r"^\s*[\(\[\{<「『【〔〈《]\s*")
_WRAPPED_HEADING_CLOSE = re.compile(r"\s*[\)\]\}>」』】〕〉》]\s*$")


class OverviewReviewNotFound(LookupError):
    """The requested notice does not exist as a pre-specification notice."""


class OverviewPreparationError(RuntimeError):
    """A safe, non-sensitive preparation failure."""

    def __init__(self, code: str, message: str = "개요 검토 입력을 준비할 수 없습니다") -> None:
        self.code = code
        super().__init__(message)


class OverviewAttemptError(RuntimeError):
    """Stable, non-sensitive failure from the phase-2 attempt boundary."""

    def __init__(
        self,
        code: str,
        message: str = "사전규격 개요 실행을 진행할 수 없습니다",
    ) -> None:
        self.code = code
        super().__init__(message)


class OverviewResultValidationError(OverviewAttemptError):
    """A provider payload did not satisfy the adopted strict result contract."""


class OverviewScopeError(OverviewAttemptError):
    """A requested review/snapshot/result does not share one notice scope."""


@dataclass(frozen=True)
class OverviewModelBinding:
    """The minimal model identity persisted on an attempt.

    This is metadata only.  The phase-2 implementation intentionally has no
    transport method and no endpoint field, so constructing a binding cannot
    accidentally trigger a provider call or create a hosted-model fallback.
    ``reference_only`` is the only mode available to deterministic fakes;
    callers must explicitly provide a binding before an attempt is queued.
    """

    provider: str
    model_name: str
    model_digest: str
    prompt_version: str
    reference_only: bool = False
    deployable: bool = True
    binding_digest: str | None = None
    #: policy 파일의 canonical SHA-256. 있으면 ``binding_digest`` 계산에 들어간다
    #: (명세 §6.3). 없는 binding(결정적 mock)의 digest는 그대로 둔다.
    policy_digest: str | None = None

    def __post_init__(self) -> None:
        values = (
            ("provider", self.provider, 128),
            ("model_name", self.model_name, 255),
            ("prompt_version", self.prompt_version, 128),
        )
        for name, value, max_length in values:
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
                raise OverviewAttemptError("invalid_binding")
        if not isinstance(self.model_digest, str) or not _SHA256.fullmatch(self.model_digest):
            raise OverviewAttemptError("invalid_binding")
        if self.reference_only and self.deployable:
            raise OverviewAttemptError("invalid_binding")
        if self.policy_digest is not None and not _SHA256.fullmatch(self.policy_digest):
            raise OverviewAttemptError("invalid_binding")
        material: dict[str, Any] = {
            "provider": self.provider.strip(),
            "model_name": self.model_name.strip(),
            "model_digest": self.model_digest,
            "prompt_version": self.prompt_version.strip(),
            "reference_only": bool(self.reference_only),
            "deployable": bool(self.deployable),
        }
        if self.policy_digest is not None:
            material["policy_digest"] = self.policy_digest
        digest = _sha256_hex(material)
        if self.binding_digest is not None and self.binding_digest != digest:
            raise OverviewAttemptError("invalid_binding")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "model_name", self.model_name.strip())
        object.__setattr__(self, "prompt_version", self.prompt_version.strip())
        object.__setattr__(self, "binding_digest", digest)


class OverviewPolicyError(RuntimeError):
    """개요 policy 파일을 그대로 신뢰할 수 없다 (fail closed)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OverviewPolicy:
    """개요 실행의 불변 binding 문서 (명세 §6.3).

    모델명·프롬프트 version·출력 schema·generation 설정을 코드가 아니라 이
    파일이 갖는다. 파일 전체의 canonical SHA-256이 ``digest``이고 binding에
    함께 묶인다 — 프롬프트나 schema가 한 글자 바뀌면 다른 binding이 된다.
    """

    document: Mapping[str, Any]
    digest: str

    @property
    def model_name(self) -> str:
        return str(self.document["model_name"])

    @property
    def prompt_version(self) -> str:
        return str(self.document["prompt_version"])

    @property
    def stage(self) -> str:
        return str(self.document["stages"][0]["stage"])

    @property
    def output_schema(self) -> Mapping[str, Any]:
        return self.document["output_schema"]

    @property
    def output_contract(self) -> StructuredOutputContract:
        """provider에 실어 보낼 strict 구조화 출력 계약."""

        return StructuredOutputContract(
            name="bidops_prespec_overview_result_v1",
            schema=self.output_schema,
            system_prompt=str(self.document["system_prompt"]),
        )


OVERVIEW_POLICY_PATH = (
    Path(__file__).resolve().parent.parent / "policies" / "prespec-overview-policy-v1.json"
)
OVERVIEW_POLICY_SCHEMA = "bidops.prespec-overview-policy.v1"
_REQUIRED_POLICY_KEYS = (
    "chunking",
    "generation",
    "model_endpoint_ref",
    "model_name",
    "output_schema",
    "prompt_version",
    "schema",
    "stages",
    "system_prompt",
)


def load_overview_policy(path: Path | None = None) -> OverviewPolicy | None:
    """개요 policy 파일을 읽고 canonical digest와 함께 돌려준다.

    파일이 없으면 ``None``이다 — 그 배포에는 승인된 개요 binding이 없다는 뜻이고
    review는 ``awaiting_model``에 남는다. 파일이 있는데 계약을 어기면 추정해서
    보정하지 않고 :class:`OverviewPolicyError`로 멈춘다.
    """

    source = path or OVERVIEW_POLICY_PATH
    if not source.is_file():
        return None
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OverviewPolicyError("policy_unreadable") from exc
    if not isinstance(document, Mapping):
        raise OverviewPolicyError("policy_invalid")
    if any(key not in document for key in _REQUIRED_POLICY_KEYS):
        raise OverviewPolicyError("policy_invalid")
    if document.get("schema") != OVERVIEW_POLICY_SCHEMA:
        raise OverviewPolicyError("policy_invalid")
    stages = document.get("stages")
    if (
        not isinstance(stages, list)
        or len(stages) != 1
        or not isinstance(stages[0], Mapping)
        or not str(stages[0].get("stage", "")).strip()
        or not str(stages[0].get("instruction", "")).strip()
    ):
        raise OverviewPolicyError("policy_invalid")
    for key in ("model_name", "prompt_version", "system_prompt"):
        value = document.get(key)
        if not isinstance(value, str) or not value.strip():
            raise OverviewPolicyError("policy_invalid")
    if not isinstance(document.get("output_schema"), Mapping):
        raise OverviewPolicyError("policy_invalid")
    return OverviewPolicy(document=document, digest=_sha256_hex(document))


def _verified_overview_identity(
    policy: OverviewPolicy,
    *,
    settings: Any | None = None,
) -> ModelIdentity:
    """용도별 설정으로 client를 만들고 §6.6 identity를 확인한다.

    허용 host나 선언 revision이 없으면 `/models`도 부르지 않고 실패한다.
    """

    client = ModelClient.for_purpose(
        "overview",
        model=policy.model_name,
        output_contract=policy.output_contract,
        settings=settings,
        verify_identity=False,
    )
    return client.verify_identity()


def approved_overview_binding(
    *,
    policy: OverviewPolicy | None = None,
    identity: Any | None = None,
    settings: Any | None = None,
) -> OverviewModelBinding | None:
    """policy·선언 revision·identity가 모두 통과할 때만 binding을 낸다 (명세 §6.3).

    하나라도 없으면 ``None``이고 review는 ``awaiting_model``에 남는다. 다른
    주소나 다른 provider로 넘어가지 않으며 hosted OpenAI로 fallback하지 않는다.
    ``deployable``은 "운영 완료로 집계 가능"이라는 뜻이므로 품질을 재지 않은
    지금은 ``False``다. 그래도 완료 자체는 할 수 있다.
    """

    if policy is None:
        try:
            policy = load_overview_policy()
        except OverviewPolicyError:
            return None
        if policy is None:
            return None
    try:
        resolved = (
            identity()
            if identity is not None
            else _verified_overview_identity(policy, settings=settings)
        )
    except (ModelEndpointError, ModelIdentityError, ValueError, OSError):
        return None
    revision = getattr(resolved, "revision", None)
    served = getattr(resolved, "model", None)
    if not isinstance(revision, str) or not _SHA256.fullmatch(revision):
        return None
    if served is not None and str(served) != policy.model_name:
        return None
    return OverviewModelBinding(
        provider="openai-compatible",
        model_name=policy.model_name,
        model_digest=revision,
        prompt_version=policy.prompt_version,
        reference_only=False,
        deployable=False,
        policy_digest=policy.digest,
    )


class _CutInputError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class _Heading:
    ordinal: int
    block_key: str
    page: int
    title: str
    normalized_title: str
    level: int
    is_toc: bool


@dataclass(frozen=True)
class _CutDecision:
    cut_status: str
    strategy: str | None
    start_locator: dict[str, Any] | None
    end_locator: dict[str, Any] | None
    input_block_keys: list[str] | None
    unknown_reason_code: str | None = None


@dataclass(frozen=True)
class _DocumentSelection:
    document: DocumentVersion | None
    has_current_documents: bool
    ambiguous: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_hex(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _digest_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and _SHA256.fullmatch(value) else None


def _normalise_heading_text(value: object, *, toc: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    if toc:
        # TOC page numbers and leader dots are layout metadata, not heading
        # identity.  This only removes a suffix when an explicit TOC marker
        # already established that the block is a TOC entry.
        text = _PAGE_SUFFIX.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip().casefold()
    # Numbering is useful for humans but does not by itself establish a
    # heading match.  Remove it only after checking that the remaining title
    # contains meaningful text.
    # These are formatting prefixes observed in T-21 (arabic, roman, hangul,
    # bracketed, and circle/bullet numbering).  The title itself must still
    # equal a closed vocabulary item; this is not a substring or prose match.
    text = _LEADING_HEADING_BULLET.sub("", text)
    text = _LEADING_HEADING_BRACKET.sub("", text)
    text = _LEADING_HEADING_NUMBER.sub("", text)
    text = re.sub(r"^\s*\d+(?:\.\d+)*\s+", "", text)
    text = _LEADING_HEADING_PUNCTUATION.sub("", text)
    text = _WRAPPED_HEADING_OPEN.sub("", text)
    text = _WRAPPED_HEADING_CLOSE.sub("", text)
    return text.strip(" .·…\t")


def _meaningful_heading(text: object, *, toc: bool = False) -> bool:
    if not isinstance(text, str):
        return False
    raw = unicodedata.normalize("NFKC", text).strip()
    if not raw or _NUMBERING_ONLY.fullmatch(raw):
        return False
    normalized = _normalise_heading_text(raw, toc=toc)
    if not normalized or normalized in _GENERIC_HEADINGS:
        return False
    # A heading needs at least two alphanumeric/Hangul characters.  This
    # rejects punctuation and numbering-only blocks without guessing from
    # arbitrary paragraph prose.
    meaningful_chars = [char for char in normalized if char.isalnum() or "가" <= char <= "힣"]
    return len(meaningful_chars) >= 2


def _as_int(value: object, default: int = 1) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 1:
        return value
    return default


def _heading_info(block: Mapping[str, Any], ordinal: int) -> _Heading | None:
    attrs = block.get("attributes")
    if not isinstance(attrs, Mapping):
        attrs = {}
    block_type = str(block.get("type") or "").casefold()
    role = str(attrs.get("role") or attrs.get("section_role") or "").casefold()
    toc_marker = (
        block_type in _TOC_TYPES
        or role in _TOC_ROLES
        or attrs.get("is_toc") is True
        or attrs.get("toc") is True
    )
    heading_marker = (
        block_type in _HEADING_TYPES
        or block_type in _TOC_TYPES
        or role in _HEADING_ROLES
        or role in _TOC_ROLES
        or attrs.get("is_heading") is True
        or attrs.get("heading") is True
        or isinstance(attrs.get("heading_level"), int)
    )
    if not heading_marker:
        return None
    text = attrs.get("heading_text") or attrs.get("title") or block.get("text")
    if not _meaningful_heading(text, toc=toc_marker):
        return None
    normalized = _normalise_heading_text(text, toc=toc_marker)
    if not normalized:
        return None
    level = _as_int(attrs.get("heading_level"), _as_int(attrs.get("level"), 1))
    return _Heading(
        ordinal=ordinal,
        block_key=str(block.get("block_key")),
        page=_as_int(block.get("page")),
        title=str(text).strip(),
        normalized_title=normalized,
        level=level,
        is_toc=toc_marker,
    )


def _paragraph_heading_info(
    block: Mapping[str, Any],
    ordinal: int,
    *,
    is_toc: bool = False,
) -> _Heading | None:
    """Recognize the bounded DocumentProcessor paragraph shape.

    HWPX extraction intentionally emits paragraphs with only a stable
    ``paragraph_key`` (and some processors add ``source``), not synthetic
    heading metadata.  Do not infer a heading from sentence punctuation,
    numbering, or position: a complete exact vocabulary match is required.
    ``is_toc`` is supplied only after an explicit ``목차``/``차례`` marker has
    established a contiguous TOC entry region.
    """

    if str(block.get("type") or "").casefold() != "paragraph":
        return None
    attrs = block.get("attributes")
    if not isinstance(attrs, Mapping):
        return None
    # The real processors expose at least one stable provenance attribute.
    # Requiring it keeps ordinary test/body paragraphs from becoming headings
    # solely because their text happens to equal a vocabulary item.
    paragraph_key = attrs.get("paragraph_key")
    source = attrs.get("source")
    if not (
        isinstance(paragraph_key, str)
        and paragraph_key.strip()
        or isinstance(source, str)
        and source.strip()
    ):
        return None
    explicit_toc = (
        attrs.get("is_toc") is True
        or attrs.get("toc") is True
        or str(attrs.get("role") or attrs.get("section_role") or "").casefold()
        in _TOC_ROLES
        or str(source or "").casefold() in _TOC_ROLES
    )
    text = block.get("text")
    if not isinstance(text, str) or not _meaningful_heading(
        text, toc=is_toc or explicit_toc
    ):
        return None
    normalized = _normalise_heading_text(text, toc=is_toc or explicit_toc)
    if normalized not in _TOPIC_HEADING_VOCABULARY:
        return None
    block_key = block.get("block_key")
    if not isinstance(block_key, str) or not block_key.strip():
        return None
    return _Heading(
        ordinal=ordinal,
        block_key=block_key.strip(),
        page=_as_int(block.get("page")),
        title=text.strip(),
        normalized_title=normalized,
        level=1,
        is_toc=is_toc or explicit_toc,
    )


def _paragraph_toc_indices(
    blocks: Sequence[Mapping[str, Any]],
) -> tuple[set[int], bool]:
    """Return paragraph indexes in the explicitly marked TOC entry run.

    T-21 found that leader dots are not stable after extraction; the only
    accepted marker is a paragraph whose complete text is ``목차`` or
    ``차례``.  Entries are accepted only in the immediately following
    contiguous run of exact topic paragraphs (blank paragraphs before the
    run are harmless).  A second marker is ambiguous and disables this
    inferred TOC region rather than guessing which one is authoritative.
    """

    markers: list[int] = []
    for ordinal, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        if str(block.get("type") or "").casefold() != "paragraph":
            continue
        attrs = block.get("attributes")
        if not isinstance(attrs, Mapping):
            continue
        if not (
            isinstance(attrs.get("paragraph_key"), str)
            and attrs.get("paragraph_key", "").strip()
            or isinstance(attrs.get("source"), str)
            and attrs.get("source", "").strip()
        ):
            continue
        text = block.get("text")
        if isinstance(text, str) and _normalise_heading_text(text) in _PARAGRAPH_TOC_TITLES:
            markers.append(ordinal)
    if len(markers) != 1:
        return set(), len(markers) > 1

    marker = markers[0]
    indices: set[int] = set()
    seen_topics: set[str] = set()
    started = False
    for ordinal in range(marker + 1, len(blocks)):
        block = blocks[ordinal]
        if not isinstance(block, Mapping):
            break
        topic = _paragraph_heading_info(block, ordinal, is_toc=True)
        if topic is not None:
            # A topic repeated without an explicit TOC marker is the first
            # reliable body duplicate.  End the TOC run before it so the
            # duplicate can be matched by ``_toc_cut``.  Treat a duplicate
            # inside an explicitly marked TOC as ambiguous instead of
            # silently selecting one.
            if topic.normalized_title in seen_topics:
                break
            indices.add(ordinal)
            seen_topics.add(topic.normalized_title)
            started = True
            continue
        text = block.get("text")
        if not started and (not isinstance(text, str) or not text.strip()):
            continue
        # Once a nonblank non-topic paragraph appears, the TOC run has ended.
        # This deliberately does not scan the whole document for text matches.
        break
    return indices, False


def _paragraph_headings(
    blocks: Sequence[Mapping[str, Any]],
) -> tuple[list[_Heading], bool]:
    toc_indices, toc_ambiguous = _paragraph_toc_indices(blocks)
    headings: list[_Heading] = []
    for ordinal, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        heading = _paragraph_heading_info(
            block,
            ordinal,
            is_toc=ordinal in toc_indices,
        )
        if heading is not None:
            headings.append(heading)
    return headings, toc_ambiguous


def _locator(heading: _Heading) -> dict[str, Any]:
    return {
        "block_key": heading.block_key,
        "page": heading.page,
        "ordinal": heading.ordinal,
    }


def _next_boundary(headings: Sequence[_Heading], start: _Heading) -> _Heading | None:
    # A section ends at the next heading at the same or a higher level.  A
    # nested heading is part of the selected prefix, not its boundary.
    for heading in headings:
        if heading.ordinal > start.ordinal and heading.level <= start.level:
            return heading
    return None


def _decision_from_range(
    blocks: Sequence[Mapping[str, Any]],
    start: _Heading,
    end: _Heading | None,
    *,
    strategy: str,
) -> _CutDecision:
    if end is None:
        return _CutDecision(
            cut_status="unknown",
            strategy=strategy,
            start_locator=_locator(start),
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="no_end_heading",
        )
    if end.ordinal <= start.ordinal:
        return _CutDecision(
            cut_status="unknown",
            strategy=strategy,
            start_locator=_locator(start),
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="ambiguous_boundary",
        )
    keys = [str(item.get("block_key")) for item in blocks[start.ordinal : end.ordinal]]
    if not keys or any(not key or key == "None" for key in keys):
        return _CutDecision(
            cut_status="unknown",
            strategy=strategy,
            start_locator=_locator(start),
            end_locator=_locator(end),
            input_block_keys=None,
            unknown_reason_code="invalid_boundary",
        )
    return _CutDecision(
        cut_status="ready",
        strategy=strategy,
        start_locator=_locator(start),
        end_locator=_locator(end),
        input_block_keys=keys,
    )


def _toc_target_key(block: Mapping[str, Any]) -> str | None:
    attrs = block.get("attributes")
    if not isinstance(attrs, Mapping):
        return None
    for key in ("target_block_key", "body_block_key", "linked_block_key"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _toc_cut(
    blocks: Sequence[Mapping[str, Any]],
    headings: Sequence[_Heading],
) -> _CutDecision | None:
    toc_entries = [heading for heading in headings if heading.is_toc]
    if not toc_entries:
        return None
    body = [heading for heading in headings if not heading.is_toc]
    if not body:
        return None
    body_by_key = {heading.block_key: heading for heading in body}
    for entry in toc_entries:
        target_key = _toc_target_key(blocks[entry.ordinal])
        if target_key is not None:
            candidate = body_by_key.get(target_key)
            if candidate is None or candidate.normalized_title != entry.normalized_title:
                return _CutDecision(
                    cut_status="unknown",
                    strategy="toc_body_match",
                    start_locator=None,
                    end_locator=None,
                    input_block_keys=None,
                    unknown_reason_code="toc_mismatch",
                )
            start = candidate
        else:
            matches = [heading for heading in body if heading.normalized_title == entry.normalized_title]
            if len(matches) > 1:
                return _CutDecision(
                    cut_status="unknown",
                    strategy="toc_body_match",
                    start_locator=None,
                    end_locator=None,
                    input_block_keys=None,
                    unknown_reason_code="toc_ambiguous",
                )
            if not matches:
                continue
            start = matches[0]
        end = _next_boundary(body, start)
        return _decision_from_range(blocks, start, end, strategy="toc_body_match")
    return None


def deterministic_prefix_cut(payload: Mapping[str, Any]) -> _CutDecision:
    """Return a deterministic TOC/body or topic-heading prefix decision.

    The function consumes only structure metadata.  It deliberately does not
    infer headings from arbitrary paragraph text, use a fixed block count, or
    treat the entire document as a fallback range.
    """

    if not isinstance(payload, Mapping):
        return _CutDecision(
            cut_status="unknown",
            strategy=None,
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="invalid_structure",
        )
    warnings = payload.get("warnings")
    if warnings is not None and (
        not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings)
    ):
        return _CutDecision(
            cut_status="unknown",
            strategy=None,
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="invalid_structure",
        )
    if warnings:
        return _CutDecision(
            cut_status="unknown",
            strategy=None,
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="structure_warning",
        )
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return _CutDecision(
            cut_status="unknown",
            strategy=None,
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="invalid_structure",
        )
    try:
        encoded_size = len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        encoded_size = MAX_OVERVIEW_INPUT_BYTES + 1
    if len(blocks) > MAX_OVERVIEW_INPUT_BLOCKS or encoded_size > MAX_OVERVIEW_INPUT_BYTES:
        return _CutDecision(
            cut_status="unknown",
            strategy=None,
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="input_limit",
        )
    headings = [
        heading
        for ordinal, block in enumerate(blocks)
        if isinstance(block, Mapping)
        for heading in [_heading_info(block, ordinal)]
        if heading is not None
    ]
    # Existing structure producers may provide explicit heading metadata.  The
    # canonical DocumentProcessor generally does not, so only when that path
    # yields no headings do we activate the bounded paragraph adapter below.
    # Keeping the paths separate avoids treating an arbitrary synthetic block
    # as a paragraph boundary (or vice versa).
    paragraph_toc_ambiguous = False
    if not headings:
        headings, paragraph_toc_ambiguous = _paragraph_headings(blocks)
    if paragraph_toc_ambiguous:
        return _CutDecision(
            cut_status="unknown",
            strategy="toc_body_match",
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="toc_ambiguous",
        )
    toc_result = _toc_cut(blocks, headings)
    if toc_result is not None:
        return toc_result
    body = [heading for heading in headings if not heading.is_toc]
    if not body:
        return _CutDecision(
            cut_status="unknown",
            strategy=None,
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code="no_topic_heading",
        )
    return _decision_from_range(
        blocks,
        body[0],
        _next_boundary(body, body[0]),
        strategy="topic_heading",
    )


def _latest_scan_clean(session: Session, content_id: UUID) -> bool:
    scan = session.scalar(
        select(ContentScan)
        .where(ContentScan.content_object_id == content_id)
        .order_by(ContentScan.scanned_at.desc(), ContentScan.id.desc())
        .limit(1)
    )
    return scan is not None and scan.status == "clean"


def _latest_location(
    session: Session,
    content_id: UUID,
    namespace: str,
) -> ContentObjectLocation | None:
    return session.scalar(
        select(ContentObjectLocation)
        .where(
            ContentObjectLocation.content_object_id == content_id,
            ContentObjectLocation.namespace_key == namespace,
            ContentObjectLocation.status == "verified",
            ContentObjectLocation.purged_at.is_(None),
        )
        .order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc())
        .limit(1)
    )


def _load_structure_payload(
    session: Session,
    document: DocumentVersion,
    structure: DocumentStructure,
    *,
    root: Path | None,
    verify_source_bytes: bool = True,
) -> Mapping[str, Any]:
    if document.notice_id <= 0 or structure.document_version_id != document.id:
        raise _CutInputError("lineage_mismatch")
    if document.safety_status != "safe" or structure.validation_status != "ready":
        raise _CutInputError("structure_not_clean")
    source = session.get(ContentObject, document.content_object_id)
    payload_object = session.get(ContentObject, structure.payload_content_object_id)
    if (
        source is None
        or payload_object is None
        or not _SHA256.fullmatch(source.sha256 or "")
        or source.sha256 != structure.source_sha256
        or payload_object.sha256 != structure.payload_sha256
        or not _latest_scan_clean(session, source.id)
    ):
        raise _CutInputError("hash_mismatch")

    # Source bytes are re-read from its verified purpose namespace.  This
    # guards against a stale ContentObject row being treated as proof of the
    # current object-store contents.
    source_location = _latest_location(session, source.id, "source")
    if source_location is None:
        raise _CutInputError("source_location_missing")
    if verify_source_bytes:
        try:
            source_bytes, source_metadata = assets.read_object(
                "source", source_location.object_key, root=root
            )
        except assets.AssetError as exc:
            raise _CutInputError("source_unavailable") from exc
        if (
            len(source_bytes) != source.size_bytes
            or hashlib.sha256(source_bytes).hexdigest() != source.sha256
            or (source_location.etag is not None and source_location.etag != source_metadata.etag)
            or (
                source_location.object_version_id is not None
                and source_location.object_version_id != source_metadata.object_version_id
            )
        ):
            raise _CutInputError("hash_mismatch")

    structure_location = _latest_location(session, payload_object.id, "structure")
    if structure_location is None:
        raise _CutInputError("structure_location_missing")
    try:
        raw, metadata = assets.read_object(
            "structure", structure_location.object_key, root=root
        )
        payload_digest = hashlib.sha256(raw).hexdigest()
        if (
            len(raw) != payload_object.size_bytes
            or payload_digest != structure.payload_sha256
            or (structure_location.etag is not None and structure_location.etag != metadata.etag)
            or (
                structure_location.object_version_id is not None
                and structure_location.object_version_id != metadata.object_version_id
            )
        ):
            raise _CutInputError("hash_mismatch")
        payload_value = json.loads(raw.decode("utf-8"))
    except _CutInputError:
        raise
    except (assets.AssetError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise _CutInputError("structure_unavailable") from exc
    if not isinstance(payload_value, Mapping):
        raise _CutInputError("invalid_structure")
    if (
        payload_value.get("document_version_id") != str(document.id)
        or payload_value.get("structure_id") != str(structure.id)
        or payload_value.get("source_sha256") != source.sha256
    ):
        raise _CutInputError("lineage_mismatch")
    try:
        return validate_structure(payload_value)
    except Exception as exc:
        raise _CutInputError("invalid_structure") from exc


def _filename_document_candidate(original_filename: object) -> bool:
    """Match the Korean RFP filename label, allowing formatting whitespace."""

    if not isinstance(original_filename, str):
        return False
    value = unicodedata.normalize("NFKC", original_filename).casefold()
    compact = _WHITESPACE.sub("", value)
    return "제안요청서" in compact


def _current_document(
    session: Session,
    notice_id: int,
) -> _DocumentSelection:
    documents = session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.notice_id == notice_id, DocumentVersion.is_current.is_(True))
        .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
    ).all()
    if not documents:
        return _DocumentSelection(document=None, has_current_documents=False)

    # Filename is the selection criterion regardless of stored role. Never
    # substitute a task specification or a role-only designation for a missing
    # Korean RFP filename, or break ties using upload time or extension.
    filename_candidates = [
        item
        for item in documents
        if _filename_document_candidate(item.original_filename)
    ]
    if len(filename_candidates) == 1:
        return _DocumentSelection(document=filename_candidates[0], has_current_documents=True)
    if len(filename_candidates) > 1:
        return _DocumentSelection(
            document=None,
            has_current_documents=True,
            ambiguous=True,
        )
    # Current attachments exist but none has the required filename. This is a human-review state,
    # not permission to retain a previous snapshot or guess the newest row.
    return _DocumentSelection(document=None, has_current_documents=True)


def _current_structure(
    session: Session,
    document: DocumentVersion,
) -> DocumentStructure | None:
    structures = session.scalars(
        select(DocumentStructure)
        .where(DocumentStructure.document_version_id == document.id)
        .order_by(DocumentStructure.created_at.desc(), DocumentStructure.id.desc())
    ).all()
    return next((item for item in structures if item.validation_status == "ready"), None)


def _set_review_state(
    review: PreSpecOverviewReview,
    *,
    status: str,
    current_snapshot: PreSpecOverviewSnapshot | None = None,
    clear_current_snapshot: bool = False,
) -> None:
    review.status = status
    review.result = None
    review.completed_at = None
    if (
        current_snapshot is not None
        or clear_current_snapshot
        or status in {"awaiting_document", "awaiting_structure"}
    ):
        review.current_snapshot = current_snapshot
    review.updated_at = _now()


def _snapshot_for_input(
    session: Session,
    *,
    review_id: UUID,
    document: DocumentVersion,
    structure: DocumentStructure,
    source_sha256: str,
    payload_sha256: str,
) -> PreSpecOverviewSnapshot | None:
    return session.scalar(
        select(PreSpecOverviewSnapshot)
        .where(
            PreSpecOverviewSnapshot.review_id == review_id,
            PreSpecOverviewSnapshot.document_version_id == document.id,
            PreSpecOverviewSnapshot.structure_id == structure.id,
            PreSpecOverviewSnapshot.source_sha256 == source_sha256,
            PreSpecOverviewSnapshot.payload_sha256 == payload_sha256,
        )
        .order_by(PreSpecOverviewSnapshot.created_at.desc(), PreSpecOverviewSnapshot.id.desc())
        .limit(1)
    )


def prepare_overview_review(
    session: Session,
    notice_id: int,
    *,
    root: Path | None = None,
) -> PreSpecOverviewReview:
    """Materialize or reuse one notice's current overview review state.

    The caller owns the surrounding transaction.  No commit is performed so
    safe T-20 promotion can roll back every write if this preparation fails.
    """

    notice = lock_notice(session, int(notice_id))
    if notice is None or notice.source_type != "pre_spec":
        raise OverviewReviewNotFound

    review = session.scalar(
        select(PreSpecOverviewReview)
        .where(PreSpecOverviewReview.notice_id == notice.id)
        .with_for_update()
    )
    if review is None:
        review = PreSpecOverviewReview(
            id=uuid4(), notice_id=notice.id, status="awaiting_document"
        )
        session.add(review)
        session.flush()

    selection = _current_document(session, notice.id)
    document = selection.document
    if not selection.has_current_documents:
        _set_review_state(review, status="awaiting_document")
        session.flush()
        return review
    if selection.ambiguous or document is None:
        _set_review_state(
            review,
            status="needs_human_review",
            clear_current_snapshot=True,
        )
        session.flush()
        return review
    if document.safety_status != "safe":
        _set_review_state(review, status="awaiting_structure")
        session.flush()
        return review

    structure = _current_structure(session, document)
    if structure is None:
        _set_review_state(review, status="awaiting_structure")
        session.flush()
        return review

    previous_snapshot_id = review.current_snapshot_id
    previous_status = review.status
    previous_result = review.result
    previous_completed_at = review.completed_at
    _set_review_state(review, status="preparing")
    session.flush()
    try:
        payload = _load_structure_payload(session, document, structure, root=root)
        decision = deterministic_prefix_cut(payload)
    except _CutInputError as error:
        decision = _CutDecision(
            cut_status="unknown",
            strategy=None,
            start_locator=None,
            end_locator=None,
            input_block_keys=None,
            unknown_reason_code=error.reason_code,
        )

    snapshot = _snapshot_for_input(
        session,
        review_id=review.id,
        document=document,
        structure=structure,
        source_sha256=structure.source_sha256,
        payload_sha256=structure.payload_sha256,
    )
    if snapshot is not None and (
        snapshot.cut_status != decision.cut_status
        or snapshot.strategy != decision.strategy
        or snapshot.start_locator != decision.start_locator
        or snapshot.end_locator != decision.end_locator
        or snapshot.input_block_keys != decision.input_block_keys
        or snapshot.unknown_reason_code != decision.unknown_reason_code
    ):
        # Snapshot identity is unique for these immutable input hashes. Keep
        # that history, but detach it from the current decision when a fresh
        # integrity/cut check disagrees; never reopen a model request from it.
        _set_review_state(review, status="needs_human_review", clear_current_snapshot=True)
        if previous_snapshot_id is not None or previous_status != "needs_human_review":
            session.add(AuditEvent(
                actor_kind="system", claimed_name="prespec-overview",
                action="prespec_overview.reverification_failed",
                aggregate_type="prespec_overview_review", aggregate_id=str(review.id),
                safe_metadata={"reason_code": decision.unknown_reason_code or "cut_decision_changed", "snapshot_id": str(snapshot.id)},
            ))
        session.flush()
        return review
    if snapshot is None:
        snapshot = PreSpecOverviewSnapshot(
            id=uuid4(),
            review_id=review.id,
            notice_id=notice.id,
            document_version_id=document.id,
            structure_id=structure.id,
            source_sha256=structure.source_sha256,
            payload_sha256=structure.payload_sha256,
            cut_status=decision.cut_status,
            strategy=decision.strategy,
            start_locator=decision.start_locator,
            end_locator=decision.end_locator,
            input_block_keys=decision.input_block_keys,
            unknown_reason_code=decision.unknown_reason_code,
        )
        session.add(snapshot)
        session.flush()

    review.current_snapshot = snapshot
    # Repeated auto-preparation for the same immutable input must not rewind a
    # model lifecycle that another worker has already advanced.  A changed
    # structure/hash gets a new snapshot and intentionally starts a new stage;
    # a cut decision changing from ready to unknown also reopens human review.
    preserve_existing = (
        previous_snapshot_id == snapshot.id
        and previous_status in _PRESERVE_REVIEW_STATUSES
        and snapshot.cut_status == decision.cut_status
    )
    if preserve_existing:
        review.status = previous_status
        review.result = previous_result
        review.completed_at = previous_completed_at
        review.updated_at = _now()
    else:
        _set_review_state(
            review,
            status="awaiting_model" if snapshot.cut_status == "ready" else "needs_human_review",
            current_snapshot=snapshot,
        )
    session.flush()
    return review


def _attempt_view(attempt: PreSpecOverviewAttempt) -> PreSpecOverviewAttemptView:
    # Result JSON, provider prompt metadata, and model response objects are
    # intentionally excluded from the read contract.
    return PreSpecOverviewAttemptView(
        id=attempt.id,
        snapshot_id=attempt.snapshot_id,
        sequence=attempt.sequence,
        status=attempt.status,
        reference_only=attempt.reference_only,
        deployable=attempt.deployable,
        created_at=attempt.created_at,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
    )


def _safe_locator(value: object) -> dict[str, Any] | None:
    """Project only the opaque locator tuple allowed on the wire.

    The DB check deliberately validates only JSON object shape so future
    internal fields can be retained without a destructive migration.  Never
    pass those arbitrary fields through this API projection: object keys,
    paths, and other storage metadata are server-side only.
    """

    if not isinstance(value, Mapping):
        return None
    block_key = value.get("block_key")
    page = value.get("page")
    ordinal = value.get("ordinal")
    if (
        not isinstance(block_key, str)
        or not block_key.strip()
        or "/" in block_key
        or "\\" in block_key
        or isinstance(page, bool)
        or not isinstance(page, int)
        or page < 1
        or isinstance(ordinal, bool)
        or not isinstance(ordinal, int)
        or ordinal < 0
    ):
        return None
    return {"block_key": block_key, "page": page, "ordinal": ordinal}


def _snapshot_view(snapshot: PreSpecOverviewSnapshot) -> PreSpecOverviewSnapshotView:
    return PreSpecOverviewSnapshotView(
        id=snapshot.id,
        document_version_id=snapshot.document_version_id,
        structure_id=snapshot.structure_id,
        source_sha256=snapshot.source_sha256,
        payload_sha256=snapshot.payload_sha256,
        cut_status=snapshot.cut_status,
        strategy=snapshot.strategy,
        start_locator=_safe_locator(snapshot.start_locator),
        end_locator=_safe_locator(snapshot.end_locator),
        created_at=snapshot.created_at,
    )


def _review_view(
    review: PreSpecOverviewReview,
    attempts: Sequence[PreSpecOverviewAttempt],
) -> PreSpecOverviewReviewView:
    return PreSpecOverviewReviewView(
        id=review.id,
        notice_id=review.notice_id,
        status=review.status,
        result=review.result,
        completed_at=review.completed_at,
        current_snapshot=(
            _snapshot_view(review.current_snapshot)
            if review.current_snapshot is not None
            else None
        ),
        attempts=[_attempt_view(item) for item in attempts],
    )


def get_overview_reviews(
    session: Session,
    notice_id: int,
    *,
    root: Path | None = None,
) -> PreSpecOverviewReviewsResponse:
    """Ensure the current state exists, commit it, and project safe metadata."""

    try:
        review = prepare_overview_review(session, notice_id, root=root)
        session.commit()
        # Reload after commit so a newly assigned current_snapshot and its
        # append-only attempts are projected from the durable rows.
        review = session.scalar(
            select(PreSpecOverviewReview).where(PreSpecOverviewReview.id == review.id)
        )
        if review is None:  # pragma: no cover - protected by the just-committed row
            raise OverviewPreparationError("not_found")
        snapshots = session.scalars(
            select(PreSpecOverviewSnapshot)
            .where(PreSpecOverviewSnapshot.review_id == review.id)
            .order_by(PreSpecOverviewSnapshot.created_at.asc(), PreSpecOverviewSnapshot.id.asc())
        ).all()
        snapshot_ids = [item.id for item in snapshots]
        attempts = (
            session.scalars(
                select(PreSpecOverviewAttempt)
                .where(PreSpecOverviewAttempt.snapshot_id.in_(snapshot_ids))
                .order_by(PreSpecOverviewAttempt.created_at.asc(), PreSpecOverviewAttempt.sequence.asc())
            ).all()
            if snapshot_ids
            else []
        )
        return PreSpecOverviewReviewsResponse(
            schema_version=OVERVIEW_SCHEMA_VERSION,
            notice_id=int(notice_id),
            reviews=[_review_view(review, attempts)],
        )
    except (OverviewReviewNotFound, OverviewPreparationError):
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise OverviewPreparationError("processing_failed") from exc


def overview_input_digest(snapshot: PreSpecOverviewSnapshot) -> str:
    """Hash the complete immutable input scope used by a phase-2 attempt."""

    return _sha256_hex(
        {
            "review_id": str(snapshot.review_id),
            "document_version_id": str(snapshot.document_version_id),
            "structure_id": str(snapshot.structure_id),
            "source_sha256": snapshot.source_sha256,
            "payload_sha256": snapshot.payload_sha256,
            "cut_status": snapshot.cut_status,
            "strategy": snapshot.strategy,
            "start_locator": snapshot.start_locator,
            "end_locator": snapshot.end_locator,
            "input_block_keys": snapshot.input_block_keys,
        }
    )


def _validate_snapshot_range(snapshot: PreSpecOverviewSnapshot) -> tuple[list[str], int, int]:
    if snapshot.cut_status != "ready":
        raise OverviewResultValidationError("snapshot_not_ready")
    block_keys = snapshot.input_block_keys
    start = snapshot.start_locator
    end = snapshot.end_locator
    if not isinstance(block_keys, list) or not block_keys:
        raise OverviewResultValidationError("evidence_out_of_scope")
    if not all(isinstance(item, str) and item.strip() for item in block_keys):
        raise OverviewResultValidationError("evidence_out_of_scope")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        raise OverviewResultValidationError("evidence_out_of_scope")
    for locator in (start, end):
        block_key = locator.get("block_key")
        page = locator.get("page")
        ordinal = locator.get("ordinal")
        if (
            not isinstance(block_key, str)
            or not block_key.strip()
            or "/" in block_key
            or "\\" in block_key
            or isinstance(page, bool)
            or not isinstance(page, int)
            or page < 1
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 0
        ):
            raise OverviewResultValidationError("evidence_out_of_scope")
    start_ordinal = start.get("ordinal")
    end_ordinal = end.get("ordinal")
    start_key = start.get("block_key")
    if (
        isinstance(start_ordinal, bool)
        or not isinstance(start_ordinal, int)
        or isinstance(end_ordinal, bool)
        or not isinstance(end_ordinal, int)
        or start_ordinal < 0
        or end_ordinal <= start_ordinal
        or end_ordinal - start_ordinal != len(block_keys)
        or block_keys[0] != start_key
    ):
        raise OverviewResultValidationError("evidence_out_of_scope")
    return block_keys, start_ordinal, end_ordinal


def validate_overview_result(
    payload: Mapping[str, Any] | PreSpecOverviewResultPayload,
    snapshot: PreSpecOverviewSnapshot,
) -> tuple[PreSpecOverviewResultPayload, str]:
    """Validate and digest a provider/fake result without making network calls."""

    try:
        result = (
            payload
            if isinstance(payload, PreSpecOverviewResultPayload)
            else PreSpecOverviewResultPayload.model_validate(payload)
        )
    except ValidationError as exc:
        # Never return Pydantic paths or provider content as an API detail.
        raise OverviewResultValidationError("validation_failed") from exc
    block_keys, start_ordinal, end_ordinal = _validate_snapshot_range(snapshot)
    for item in result.evidence:
        locator = item.locator
        if locator.ordinal < start_ordinal or locator.ordinal >= end_ordinal:
            raise OverviewResultValidationError("evidence_out_of_scope")
        relative_ordinal = locator.ordinal - start_ordinal
        if (
            relative_ordinal < 0
            or relative_ordinal >= len(block_keys)
            or block_keys[relative_ordinal] != locator.block_key
        ):
            raise OverviewResultValidationError("evidence_out_of_scope")
    digest = _sha256_hex(result.model_dump(mode="json", exclude_none=False))
    return result, digest


def _overview_scope(
    session: Session,
    attempt: PreSpecOverviewAttempt,
    *,
    notice_id: int | None = None,
) -> tuple[PreSpecOverviewReview, PreSpecOverviewSnapshot, Notice]:
    if attempt.review_id is None:
        raise OverviewScopeError("scope_mismatch")
    review = session.scalar(
        select(PreSpecOverviewReview)
        .where(PreSpecOverviewReview.id == attempt.review_id)
        .with_for_update()
    )
    snapshot = session.scalar(
        select(PreSpecOverviewSnapshot)
        .where(PreSpecOverviewSnapshot.id == attempt.snapshot_id)
    )
    if review is None or snapshot is None:
        raise OverviewScopeError("scope_mismatch")
    notice = session.scalar(select(Notice).where(Notice.id == review.notice_id))
    if (
        notice is None
        or notice.source_type != "pre_spec"
        or snapshot.review_id != review.id
        or snapshot.notice_id != review.notice_id
        or (notice_id is not None and int(notice_id) != review.notice_id)
    ):
        raise OverviewScopeError("scope_mismatch")
    return review, snapshot, notice


def _require_phase2_attempt(
    attempt: PreSpecOverviewAttempt, *, for_completion: bool = False
) -> None:
    """보존된 phase-1 행과 mock 참조 실행의 완료를 막는다.

    품질을 아직 재지 않은 **실제** 모델 실행(``reference_only=false``,
    ``deployable=false``)은 완료할 수 있다(명세 §6.3). ``deployable``의 뜻은
    "운영 완료로 집계 가능"이지 "완료 가능"이 아니다. 완료를 막는 축은
    ``reference_only`` 하나이며 DB CHECK
    ``ck_prespec_overview_attempt_completed_binding``과 같은 규칙이다.
    """

    if (
        attempt.review_id is None
        or attempt.input_sha256 is None
        or attempt.binding_digest is None
    ):
        raise OverviewAttemptError("legacy_attempt_frozen")
    if for_completion and attempt.reference_only is not False:
        raise OverviewAttemptError("completion_requires_deployable_binding")


def overview_quality_status(attempt: PreSpecOverviewAttempt) -> str:
    """attempt의 품질 표식 (명세 §8).

    ``reference_only``인 결정적 mock은 ``mock_reference``, 실제 모델의 품질
    미측정 실행은 ``unmeasured_reference``다. 둘 다 운영 완료 집계에 넣지 않는다.
    """

    return "mock_reference" if attempt.reference_only else "unmeasured_reference"


def create_overview_attempt(
    session: Session,
    notice_id: int,
    review_id: UUID,
    snapshot_id: UUID,
    *,
    binding: OverviewModelBinding | None = None,
) -> PreSpecOverviewAttempt | None:
    """Queue one explicitly bound attempt, or retain ``awaiting_model``.

    ``binding=None`` is the production-safe path in the current deployment:
    it creates no attempt and performs no transport/model operation.
    """

    notice = lock_notice(session, int(notice_id))
    review = session.scalar(
        select(PreSpecOverviewReview)
        .where(PreSpecOverviewReview.id == review_id)
        .with_for_update()
    )
    snapshot = session.scalar(
        select(PreSpecOverviewSnapshot)
        .where(PreSpecOverviewSnapshot.id == snapshot_id)
    )
    if (
        notice is None
        or notice.source_type != "pre_spec"
        or review is None
        or review.notice_id != notice.id
        or snapshot is None
        or snapshot.review_id != review.id
        or snapshot.notice_id != notice.id
    ):
        raise OverviewScopeError("scope_mismatch")
    if snapshot.cut_status != "ready":
        raise OverviewAttemptError("snapshot_not_ready")

    existing = session.scalars(
        select(PreSpecOverviewAttempt)
        .where(PreSpecOverviewAttempt.snapshot_id == snapshot.id)
        .order_by(PreSpecOverviewAttempt.sequence.desc())
        .with_for_update()
    ).all()
    if binding is None:
        if (
            not existing
            and review.status not in {"completed", "failed", "cancelled"}
        ):
            review.status = "awaiting_model"
            review.result = None
            review.completed_at = None
            review.current_snapshot_id = snapshot.id
            review.updated_at = _now()
            session.flush()
        return None
    phase2_existing = [
        item
        for item in existing
        if item.review_id is not None
        and item.input_sha256 is not None
        and item.binding_digest is not None
    ]
    if any(item.status in {"queued", "running"} for item in phase2_existing):
        raise OverviewAttemptError("active_attempt_exists")

    attempt = PreSpecOverviewAttempt(
        id=uuid4(),
        review_id=review.id,
        snapshot_id=snapshot.id,
        sequence=(existing[0].sequence + 1) if existing else 1,
        status="queued",
        reference_only=binding.reference_only,
        deployable=binding.deployable,
        provider=binding.provider,
        model_name=binding.model_name,
        model_digest=binding.model_digest,
        prompt_version=binding.prompt_version,
        input_sha256=overview_input_digest(snapshot),
        binding_digest=binding.binding_digest,
    )
    session.add(attempt)
    review.current_snapshot_id = snapshot.id
    review.status = "queued"
    review.result = None
    review.completed_at = None
    review.updated_at = _now()
    session.flush()
    return attempt


def build_overview_model_input(
    session: Session,
    snapshot: PreSpecOverviewSnapshot,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """모델 경계로 보낼 block만 고정 snapshot 범위에서 뽑는다 (명세 §6.3).

    ``input_block_keys`` 범위의 block text·page·ordinal·block_key만 나간다.
    object key·경로·자격증명·회사 프로필은 이 경계를 넘지 않는다.
    """

    block_keys, start_ordinal, end_ordinal = _validate_snapshot_range(snapshot)
    document = session.get(DocumentVersion, snapshot.document_version_id)
    structure = session.get(DocumentStructure, snapshot.structure_id)
    if document is None or structure is None:
        raise OverviewAttemptError("input_unavailable")
    if (
        structure.source_sha256 != snapshot.source_sha256
        or structure.payload_sha256 != snapshot.payload_sha256
    ):
        raise OverviewAttemptError("input_hash_mismatch")
    try:
        # Preparation already verified source bytes before freezing this
        # snapshot. The analysis worker owns structure-read credentials only;
        # recheck its immutable lineage, clean scan and structure bytes here.
        payload = _load_structure_payload(session, document, structure, root=root, verify_source_bytes=False)
    except _CutInputError as error:
        raise OverviewAttemptError(error.reason_code) from error
    blocks = payload.get("blocks")
    if not isinstance(blocks, list) or end_ordinal > len(blocks):
        raise OverviewAttemptError("input_out_of_range")
    selected: list[dict[str, Any]] = []
    for ordinal in range(start_ordinal, end_ordinal):
        block = blocks[ordinal]
        if not isinstance(block, Mapping):
            raise OverviewAttemptError("input_out_of_range")
        block_key = block.get("block_key")
        page = block.get("page")
        text = block.get("text")
        if (
            not isinstance(block_key, str)
            or block_key != block_keys[ordinal - start_ordinal]
            or isinstance(page, bool)
            or not isinstance(page, int)
            or page < 1
            or not isinstance(text, str)
        ):
            raise OverviewAttemptError("input_out_of_range")
        selected.append(
            {
                "block_key": block_key,
                "page": page,
                "ordinal": ordinal,
                "text": text,
            }
        )
    if not selected:
        raise OverviewAttemptError("input_out_of_range")
    # 경계 있는 입력만 모델로 보낸다. 상한을 넘으면 잘라서 보내지 않고 실패한다 —
    # 자른 입력의 결과를 완전한 판단으로 발행할 수 없기 때문이다.
    if len(selected) > MAX_OVERVIEW_INPUT_BLOCKS:
        raise OverviewAttemptError("input_too_large")
    if sum(len(item["text"].encode("utf-8")) for item in selected) > MAX_OVERVIEW_INPUT_BYTES:
        raise OverviewAttemptError("input_too_large")
    return selected


def select_overview_enqueue_candidate(
    session: Session,
) -> tuple[PreSpecOverviewReview, PreSpecOverviewSnapshot] | None:
    """큐에 넣을 수 있는 review·snapshot 한 쌍을 고른다. 모델을 부르지 않는다.

    이 조회가 큐 유입 조건 자체다. runner는 **승인된 binding을 해석하기 전에**
    이것으로 "이번 poll에 할 일이 있는가"를 판정한다 — 할 일이 없는데 policy를
    읽고 `/models`를 부르면 idle worker가 poll마다 모델 서버를 두드린다.
    """

    active = (
        select(PreSpecOverviewAttempt.id)
        .where(
            PreSpecOverviewAttempt.snapshot_id == PreSpecOverviewSnapshot.id,
            PreSpecOverviewAttempt.review_id.is_not(None),
            PreSpecOverviewAttempt.status.in_(("queued", "running")),
        )
        .exists()
    )
    row = session.execute(
        select(PreSpecOverviewReview, PreSpecOverviewSnapshot)
        .join(
            PreSpecOverviewSnapshot,
            PreSpecOverviewSnapshot.id == PreSpecOverviewReview.current_snapshot_id,
        )
        .where(
            PreSpecOverviewReview.status == "awaiting_model",
            PreSpecOverviewSnapshot.cut_status == "ready",
            PreSpecOverviewSnapshot.review_id == PreSpecOverviewReview.id,
            ~active,
        )
        .order_by(PreSpecOverviewReview.updated_at.asc(), PreSpecOverviewReview.id.asc())
        .limit(1)
    ).first()
    if row is None:
        return None
    review, snapshot = row
    return review, snapshot


def has_claimable_overview_attempt(session: Session) -> bool:
    """claim 가능한 queued attempt가 있는지만 본다. 잠그지도 부르지도 않는다."""

    return (
        session.scalar(
            select(PreSpecOverviewAttempt.id)
            .where(
                PreSpecOverviewAttempt.status == "queued",
                PreSpecOverviewAttempt.review_id.is_not(None),
                PreSpecOverviewAttempt.input_sha256.is_not(None),
                PreSpecOverviewAttempt.binding_digest.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def enqueue_overview_attempt(
    session: Session,
    binding: OverviewModelBinding,
    *,
    candidate: tuple[PreSpecOverviewReview, PreSpecOverviewSnapshot] | None = None,
) -> PreSpecOverviewAttempt | None:
    """큐 유입: ``awaiting_model``·``cut_status=ready`` review 하나를 큐에 넣는다.

    사람 검토가 필요한 review와 ``failed``·``cancelled`` review는 건드리지 않고,
    같은 snapshot에 ``queued|running`` attempt가 있으면 새로 만들지 않는다
    (명세 §6.3). 자동 재시작이 아니라 아직 한 번도 실행되지 않은 유입이다.

    ``candidate``를 넘기면 그 쌍을 그대로 쓴다. 호출자가 이미 고른 쌍을 다시
    고르지 않기 위한 것이며, 넘기지 않으면 여기서 고른다.
    """

    selected = candidate if candidate is not None else select_overview_enqueue_candidate(session)
    if selected is None:
        return None
    review, snapshot = selected
    return create_overview_attempt(
        session,
        review.notice_id,
        review.id,
        snapshot.id,
        binding=binding,
    )


def claim_overview_attempt(
    session: Session,
    worker_id: str,
    *,
    lease_seconds: int,
    now: datetime | None = None,
) -> PreSpecOverviewAttempt | None:
    """FIFO로 queued attempt 하나를 ``running``으로 claim하고 lease를 건다.

    상태 전이·``started_at``·lease 설정을 한 transaction에서 한다. 호출자가
    commit을 소유한다.

    잠금은 ``SKIP LOCKED``다(`prespec_attachments.claim_next`와 같은 형태).
    지금은 analysis concurrency가 1이라 경쟁자가 없지만, 그냥 ``FOR UPDATE``면
    둘째 claim이 첫째의 transaction을 기다렸다가 **빈 손으로** 돌아온다 —
    없는 것과 잠긴 것이 같은 값으로 보인다. ``SKIP LOCKED``는 잠긴 행을 건너뛰고
    다음 queued attempt로 나아간다.
    """

    if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id.strip()) > 255:
        raise OverviewAttemptError("invalid_actor")
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or lease_seconds <= 0:
        raise OverviewAttemptError("invalid_lease")
    when = now or _now()
    attempt = session.scalars(
        select(PreSpecOverviewAttempt)
        .where(
            PreSpecOverviewAttempt.status == "queued",
            PreSpecOverviewAttempt.review_id.is_not(None),
            PreSpecOverviewAttempt.input_sha256.is_not(None),
            PreSpecOverviewAttempt.binding_digest.is_not(None),
        )
        .order_by(
            PreSpecOverviewAttempt.created_at.asc(),
            PreSpecOverviewAttempt.sequence.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if attempt is None:
        return None
    claimed = transition_overview_attempt(
        session,
        attempt.id,
        "running",
        actor_id=worker_id.strip(),
        reason_code="claimed",
        occurred_at=when,
    )
    claimed.lease_owner = worker_id.strip()
    claimed.lease_expires_at = when + timedelta(seconds=lease_seconds)
    session.flush()
    return claimed


def release_overview_lease(attempt: PreSpecOverviewAttempt) -> None:
    """종료된 attempt의 lease를 비운다. 자동 재시작은 하지 않는다."""

    attempt.lease_owner = None
    attempt.lease_expires_at = None


def expire_overview_leases(
    session: Session,
    *,
    now: datetime | None = None,
    actor_id: str = "overview-worker",
) -> list[UUID]:
    """만료된 ``running`` attempt를 ``failed``(``lease_expired``)로 닫는다.

    자동 재시작은 없다. review는 ``failed``로 남고 사람이 다시 시작한다.
    """

    when = now or _now()
    expired = session.scalars(
        select(PreSpecOverviewAttempt)
        .where(
            PreSpecOverviewAttempt.status == "running",
            PreSpecOverviewAttempt.review_id.is_not(None),
            PreSpecOverviewAttempt.lease_expires_at.is_not(None),
            PreSpecOverviewAttempt.lease_expires_at <= when,
        )
        .order_by(PreSpecOverviewAttempt.created_at.asc())
        .with_for_update()
    ).all()
    closed: list[UUID] = []
    for attempt in expired:
        transition_overview_attempt(
            session,
            attempt.id,
            "failed",
            actor_id=actor_id,
            reason_code="lease_expired",
            occurred_at=when,
        )
        release_overview_lease(attempt)
        closed.append(attempt.id)
    if closed:
        session.flush()
    return closed


def transition_overview_attempt(
    session: Session,
    attempt_id: UUID,
    to_status: str,
    *,
    actor_id: str,
    reason_code: str,
    actor_kind: str = "worker",
    request_id: str | None = None,
    trace_id: str | None = None,
    occurred_at: datetime | None = None,
    result_id: UUID | None = None,
) -> PreSpecOverviewAttempt:
    """Append an audit event and advance exactly one allowed lifecycle edge."""

    attempt = session.scalar(
        select(PreSpecOverviewAttempt)
        .where(PreSpecOverviewAttempt.id == attempt_id)
        .with_for_update()
    )
    if attempt is None:
        raise OverviewAttemptError("not_found")
    _require_phase2_attempt(attempt, for_completion=to_status == "completed")
    previous = attempt.status
    if (previous, to_status) not in PRESPEC_OVERVIEW_ATTEMPT_TRANSITIONS:
        raise OverviewAttemptError("invalid_transition")
    if (
        actor_kind not in {"worker", "human", "system"}
        or not isinstance(actor_id, str)
        or not actor_id.strip()
        or len(actor_id.strip()) > 128
    ):
        raise OverviewAttemptError("invalid_actor")
    if not isinstance(reason_code, str) or not reason_code.strip() or len(reason_code.strip()) > 64:
        raise OverviewAttemptError("invalid_reason")
    if (
        request_id is not None
        and (not isinstance(request_id, str) or len(request_id) > 255)
    ) or (
        trace_id is not None
        and (not isinstance(trace_id, str) or len(trace_id) > 255)
    ):
        raise OverviewAttemptError("invalid_request")
    when = occurred_at or _now()
    if when.tzinfo is None or when.utcoffset() is None:
        raise OverviewAttemptError("invalid_timestamp")
    if when < attempt.created_at:
        raise OverviewAttemptError("invalid_timestamp")

    # Lock and validate the complete scope before staging the event.  The
    # database intentionally does not couple event inserts to attempt status;
    # this service call is the transaction boundary that keeps the event,
    # attempt, and current review update together.
    review, snapshot, _notice = _overview_scope(session, attempt)
    result: PreSpecOverviewResult | None = None
    if to_status == "completed":
        if result_id is None:
            raise OverviewAttemptError("result_required")
        result = session.scalar(
            select(PreSpecOverviewResult)
            .where(
                PreSpecOverviewResult.id == result_id,
                PreSpecOverviewResult.attempt_id == attempt.id,
            )
        )
        if result is None:
            raise OverviewAttemptError("result_not_found")
        if (
            result.review_id != attempt.review_id
            or result.snapshot_id != attempt.snapshot_id
            or result.binding_digest != attempt.binding_digest
            or result.source_sha256 != snapshot.source_sha256
            or result.validation_status != "passed"
        ):
            raise OverviewScopeError("scope_mismatch")
        if not isinstance(result.payload_jsonb, Mapping):
            raise OverviewScopeError("scope_mismatch")
        if attempt.started_at is None or when < attempt.started_at:
            raise OverviewAttemptError("invalid_timestamp")
    elif result_id is not None:
        raise OverviewAttemptError("result_forbidden")
    elif to_status in {"failed", "cancelled"}:
        if previous == "queued" and attempt.started_at is not None:
            raise OverviewAttemptError("invalid_timestamp")
        if previous == "running" and attempt.started_at is None:
            raise OverviewAttemptError("invalid_timestamp")
        if when < (attempt.started_at or attempt.created_at):
            raise OverviewAttemptError("invalid_timestamp")

    next_sequence = int(
        session.scalar(
            select(func.coalesce(func.max(PreSpecOverviewAttemptEvent.event_sequence), 0) + 1).where(
                PreSpecOverviewAttemptEvent.attempt_id == attempt.id
            )
        )
        or 1
    )
    event_row = PreSpecOverviewAttemptEvent(
        id=uuid4(),
        attempt_id=attempt.id,
        event_sequence=next_sequence,
        from_status=previous,
        to_status=to_status,
        occurred_at=when,
        actor_kind=actor_kind,
        actor_id=actor_id.strip(),
        request_id=request_id,
        trace_id=trace_id,
        reason_code=reason_code.strip(),
    )
    session.add(event_row)
    attempt.status = to_status
    if to_status == "running":
        attempt.started_at = when
        attempt.completed_at = None
        attempt.result_id = None
    elif to_status == "completed":
        assert attempt.started_at is not None
        attempt.completed_at = when
        attempt.result_id = result_id
        release_overview_lease(attempt)
    else:
        attempt.completed_at = when
        attempt.result_id = None
        # 종료된 attempt는 lease를 들고 있지 않는다. 자동 재시작이 없으므로
        # 비워 두는 것이 만료 회수 대상과 실행 중을 가르는 유일한 표식이다.
        release_overview_lease(attempt)
    if review.current_snapshot_id == attempt.snapshot_id:
        review.status = to_status
        review.updated_at = _now()
        if to_status == "completed":
            # The scope and object-shape checks above run before any row is
            # staged, so this read cannot turn a successful attempt update
            # into a partial review update.
            assert result is not None
            review.result = result.payload_jsonb.get("recommendation")
            review.completed_at = when
        else:
            review.result = None
            review.completed_at = None

    # One flush lets PostgreSQL enforce all row/FK/CHECK constraints after
    # the service has staged the event and the corresponding lifecycle state.
    session.flush()
    return attempt


def record_overview_result(
    session: Session,
    attempt_id: UUID,
    payload: Mapping[str, Any] | PreSpecOverviewResultPayload,
) -> PreSpecOverviewResult:
    """Validate and insert the single immutable result for a running attempt."""

    attempt = session.scalar(
        select(PreSpecOverviewAttempt)
        .where(PreSpecOverviewAttempt.id == attempt_id)
        .with_for_update()
    )
    if attempt is None:
        raise OverviewAttemptError("not_found")
    _require_phase2_attempt(attempt)
    if attempt.status != "running":
        raise OverviewAttemptError("result_requires_running")
    review, snapshot, _notice = _overview_scope(session, attempt)
    if attempt.input_sha256 != overview_input_digest(snapshot) or attempt.binding_digest is None:
        raise OverviewScopeError("scope_mismatch")
    existing = session.scalar(
        select(PreSpecOverviewResult).where(PreSpecOverviewResult.attempt_id == attempt.id)
    )
    result_payload, payload_digest = validate_overview_result(payload, snapshot)
    if existing is not None:
        if (
            existing.review_id != review.id
            or existing.snapshot_id != snapshot.id
            or existing.binding_digest != attempt.binding_digest
            or existing.source_sha256 != snapshot.source_sha256
            or existing.validation_status != "passed"
        ):
            raise OverviewScopeError("scope_mismatch")
        if existing.payload_sha256 != payload_digest:
            raise OverviewAttemptError("result_conflict")
        return existing
    result = PreSpecOverviewResult(
        id=uuid4(),
        attempt_id=attempt.id,
        review_id=review.id,
        snapshot_id=snapshot.id,
        schema_version=result_payload.schema_version,
        payload_jsonb=result_payload.model_dump(mode="json", exclude_none=False),
        payload_sha256=payload_digest,
        source_sha256=snapshot.source_sha256,
        binding_digest=attempt.binding_digest,
        validation_status="passed",
    )
    session.add(result)
    session.flush()
    return result


def complete_overview_attempt(
    session: Session,
    attempt_id: UUID,
    payload: Mapping[str, Any] | PreSpecOverviewResultPayload,
    *,
    actor_id: str = "overview-worker",
    reason_code: str = "completed",
    request_id: str | None = None,
    trace_id: str | None = None,
) -> PreSpecOverviewAttempt:
    """Record a validated result and close the attempt as completed.

    Validation failures are durably closed as ``failed`` before the safe
    validation exception is re-raised to the caller.  No raw provider detail
    is retained or exposed.
    """

    attempt = session.scalar(
        select(PreSpecOverviewAttempt)
        .where(PreSpecOverviewAttempt.id == attempt_id)
        .with_for_update()
    )
    if attempt is None:
        raise OverviewAttemptError("not_found")
    _require_phase2_attempt(attempt, for_completion=True)

    try:
        result = record_overview_result(session, attempt_id, payload)
        return transition_overview_attempt(
            session,
            attempt_id,
            "completed",
            actor_id=actor_id,
            reason_code=reason_code,
            request_id=request_id,
            trace_id=trace_id,
            result_id=result.id,
        )
    except (OverviewResultValidationError, OverviewScopeError) as exc:
        attempt = session.scalar(
            select(PreSpecOverviewAttempt).where(PreSpecOverviewAttempt.id == attempt_id)
        )
        if attempt is not None and attempt.status == "running":
            transition_overview_attempt(
                session,
                attempt_id,
                "failed",
                actor_id=actor_id,
                reason_code=exc.code,
                request_id=request_id,
                trace_id=trace_id,
            )
        raise


def fail_overview_attempt(
    session: Session,
    attempt_id: UUID,
    *,
    actor_id: str = "overview-worker",
    reason_code: str = "failed",
    request_id: str | None = None,
    trace_id: str | None = None,
) -> PreSpecOverviewAttempt:
    return transition_overview_attempt(
        session,
        attempt_id,
        "failed",
        actor_id=actor_id,
        reason_code=reason_code,
        request_id=request_id,
        trace_id=trace_id,
    )


def fail_overview_review(
    session: Session,
    review_id: UUID,
) -> PreSpecOverviewReview | None:
    """attempt를 만들지 못한 review를 ``failed``로 닫는다 (명세 §6.3).

    큐 유입이 거부되면 attempt row 자체가 없어 ``fail_overview_attempt``로
    닫을 수 없다. 그런데 유입 후보는 ``updated_at ASC``로 뽑히므로, 같은
    review를 닫지 않으면 다음 poll이 또 그 review를 집어 개요 슬롯이 영구히
    막힌다. 이 함수는 그 고리를 끊는 것이 전부다 — 자동 재시작은 하지 않고
    사람이 다시 시작한다. 이미 종료된 review는 건드리지 않는다.

    review row에는 사유 열이 없다. 분류는 호출자가 남기는 감사 이벤트가 갖고,
    여기서 만들어 넣지 않는다.
    """

    review = session.scalar(
        select(PreSpecOverviewReview)
        .where(PreSpecOverviewReview.id == review_id)
        .with_for_update()
    )
    if review is None or review.status in {"completed", "failed", "cancelled"}:
        return review
    _set_review_state(review, status="failed")
    session.flush()
    return review


def cancel_overview_attempt(
    session: Session,
    attempt_id: UUID,
    *,
    actor_id: str = "overview-worker",
    reason_code: str = "cancelled",
    request_id: str | None = None,
    trace_id: str | None = None,
) -> PreSpecOverviewAttempt:
    return transition_overview_attempt(
        session,
        attempt_id,
        "cancelled",
        actor_id=actor_id,
        reason_code=reason_code,
        request_id=request_id,
        trace_id=trace_id,
    )


def _v2_result(
    result_row: PreSpecOverviewResult,
    snapshot: PreSpecOverviewSnapshot,
) -> tuple[PreSpecOverviewResultView, str]:
    if result_row.source_sha256 != snapshot.source_sha256:
        raise OverviewScopeError("scope_mismatch")
    try:
        payload, digest = validate_overview_result(result_row.payload_jsonb, snapshot)
    except OverviewAttemptError as exc:
        raise OverviewScopeError("scope_mismatch") from exc
    if result_row.payload_sha256 != digest or result_row.validation_status != "passed":
        raise OverviewScopeError("scope_mismatch")
    return PreSpecOverviewResultView.model_validate(payload.model_dump(mode="json")), digest


def get_overview_reviews_v2(
    session: Session,
    notice_id: int,
    *,
    root: Path | None = None,
) -> PreSpecOverviewReviewsV2Response:
    """Commit deterministic preparation and return only the safe v2 projection."""

    try:
        review = prepare_overview_review(session, notice_id, root=root)
        session.commit()
        review = session.scalar(
            select(PreSpecOverviewReview).where(PreSpecOverviewReview.id == review.id)
        )
        if review is None or review.notice_id != int(notice_id):
            raise OverviewScopeError("scope_mismatch")
        snapshots = session.scalars(
            select(PreSpecOverviewSnapshot)
            .where(PreSpecOverviewSnapshot.review_id == review.id)
            .order_by(PreSpecOverviewSnapshot.created_at.asc(), PreSpecOverviewSnapshot.id.asc())
        ).all()
        snapshot_map = {item.id: item for item in snapshots}
        attempts = (
            session.scalars(
                select(PreSpecOverviewAttempt)
                .where(PreSpecOverviewAttempt.snapshot_id.in_(list(snapshot_map)))
                .order_by(PreSpecOverviewAttempt.created_at.asc(), PreSpecOverviewAttempt.sequence.asc())
            ).all()
            if snapshot_map
            else []
        )
        result_rows = (
            session.scalars(
                select(PreSpecOverviewResult).where(
                    PreSpecOverviewResult.attempt_id.in_([item.id for item in attempts])
                )
            ).all()
            if attempts
            else []
        )
        results_by_attempt = {item.attempt_id: item for item in result_rows}
        attempt_views: list[PreSpecOverviewAttemptV2View] = []
        safe_results: dict[UUID, PreSpecOverviewResultView] = {}
        for attempt in attempts:
            snapshot = snapshot_map.get(attempt.snapshot_id)
            if (
                snapshot is None
                or attempt.review_id != review.id
                or snapshot.review_id != review.id
                or snapshot.notice_id != review.notice_id
                or attempt.input_sha256 != overview_input_digest(snapshot)
            ):
                raise OverviewScopeError("scope_mismatch")
            result_row = results_by_attempt.get(attempt.id)
            if (attempt.status == "completed") != (result_row is not None and attempt.result_id == result_row.id):
                raise OverviewScopeError("scope_mismatch")
            result_digest = None
            if result_row is not None:
                safe_result, result_digest = _v2_result(result_row, snapshot)
                safe_results[attempt.id] = safe_result
                if attempt.binding_digest != result_row.binding_digest:
                    raise OverviewScopeError("scope_mismatch")
            validation_status: PreSpecOverviewValidationStatus
            if attempt.status == "completed":
                validation_status = "passed"
            elif attempt.status == "failed":
                validation_status = "failed"
            else:
                validation_status = "pending"
            attempt_views.append(
                PreSpecOverviewAttemptV2View(
                    id=attempt.id,
                    snapshot_id=attempt.snapshot_id,
                    sequence=attempt.sequence,
                    status=attempt.status,
                    reference_only=attempt.reference_only,
                    deployable=attempt.deployable,
                    quality_status=overview_quality_status(attempt),
                    validation_status=validation_status,
                    result_digest=result_digest,
                    binding_digest=attempt.binding_digest,
                    created_at=attempt.created_at,
                    started_at=attempt.started_at,
                    completed_at=attempt.completed_at,
                )
            )

        current_snapshot = snapshot_map.get(review.current_snapshot_id)
        if review.current_snapshot_id is not None and current_snapshot is None:
            raise OverviewScopeError("scope_mismatch")
        current_attempt = next(
            (
                item
                for item in reversed(attempts)
                if current_snapshot is not None
                and item.snapshot_id == current_snapshot.id
                and item.status == "completed"
            ),
            None,
        )
        latest_current_attempt = next(
            (
                item
                for item in reversed(attempts)
                if current_snapshot is not None and item.snapshot_id == current_snapshot.id
            ),
            None,
        )
        safe_result = safe_results.get(current_attempt.id) if current_attempt else None
        current_result_row = results_by_attempt.get(current_attempt.id) if current_attempt else None
        if review.status == "completed":
            if safe_result is None or current_result_row is None or review.result != safe_result.recommendation:
                raise OverviewScopeError("scope_mismatch")
        elif review.result is not None or review.completed_at is not None:
            raise OverviewScopeError("scope_mismatch")
        review_validation: PreSpecOverviewValidationStatus
        if review.status == "completed":
            review_validation = "passed"
        elif review.status == "failed":
            review_validation = "failed"
        else:
            review_validation = "pending"
        binding_digest = (
            current_result_row.binding_digest
            if current_result_row is not None
            else (
                latest_current_attempt.binding_digest
                if latest_current_attempt is not None
                else None
            )
        )
        current_view = _snapshot_view(current_snapshot) if current_snapshot is not None else None
        # review의 품질 표식은 현재 snapshot의 마지막 attempt에서 온다.
        # attempt가 없으면 아직 표식이 없다는 뜻이므로 ``null``이다.
        review_quality = (
            overview_quality_status(latest_current_attempt)
            if latest_current_attempt is not None
            else None
        )
        review_view = PreSpecOverviewReviewV2View(
            id=review.id,
            notice_id=review.notice_id,
            status=review.status,
            quality_status=review_quality,
            result=safe_result,
            result_digest=(current_result_row.payload_sha256 if current_result_row is not None else None),
            binding_digest=binding_digest,
            validation_status=review_validation,
            completed_at=review.completed_at,
            current_snapshot=current_view,
            attempts=attempt_views,
        )
        return PreSpecOverviewReviewsV2Response(
            schema_version="bidops.prespec-overview-reviews.v2",
            notice_id=int(notice_id),
            reviews=[review_view],
        )
    except (OverviewReviewNotFound, OverviewPreparationError, OverviewAttemptError):
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise OverviewPreparationError("processing_failed") from exc


__all__ = [
    "MAX_OVERVIEW_INPUT_BLOCKS",
    "MAX_OVERVIEW_INPUT_BYTES",
    "OVERVIEW_POLICY_PATH",
    "OVERVIEW_POLICY_SCHEMA",
    "OVERVIEW_SCHEMA_VERSION",
    "OverviewPreparationError",
    "OverviewAttemptError",
    "OverviewModelBinding",
    "OverviewPolicy",
    "OverviewPolicyError",
    "OverviewResultValidationError",
    "OverviewScopeError",
    "approved_overview_binding",
    "build_overview_model_input",
    "cancel_overview_attempt",
    "claim_overview_attempt",
    "complete_overview_attempt",
    "create_overview_attempt",
    "OverviewReviewNotFound",
    "deterministic_prefix_cut",
    "enqueue_overview_attempt",
    "expire_overview_leases",
    "fail_overview_attempt",
    "get_overview_reviews",
    "get_overview_reviews_v2",
    "load_overview_policy",
    "overview_input_digest",
    "overview_quality_status",
    "prepare_overview_review",
    "record_overview_result",
    "release_overview_lease",
    "transition_overview_attempt",
    "validate_overview_result",
]
