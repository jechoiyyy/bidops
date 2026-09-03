"""Immutable inputs and active-version resolution for deep review.

This module is deliberately the only place where a deep review resolves its
profile, policy, grade, and ready bundle.  Once a review is created, callers
use the returned plain snapshots; they must not project live attachments or
document versions again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID, uuid4

import yaml

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.model_binding import MODEL_ENDPOINT_REF, MODEL_NAME, canonical_json_bytes
from ..models import (
    AnalysisPolicyVersion,
    ContentObject,
    ContentObjectLocation,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    ProfileEvidence,
    ProfileVersion,
)
from ...lifecycle.models import Notice, NoticeObservation
from ...screening import current_judgment, latest_corrected_grade
from . import assets
from .deep_review_validation import validate_structure
from ...core.company_profile import ParsedItem, parse_profile, profile_path, walk_sections


CANONICAL_POLICY_FILE = Path(__file__).resolve().parents[1] / "policies" / "analysis-policy-lean-v1.json"
PROFILE_SOURCE_FILE = "docs/reference/company-profile.md"
POLICY_SCHEMA = "bidops.analysis-policy.v1"
STAGES = (
    "requirements_and_evaluation",
    "delivery_risk_economics",
    "synthesis_and_validation",
)
_YAML_FENCE_LINE = re.compile(r"^\s*```\s*(?:yaml|yml)\s*$", re.IGNORECASE)
_CLOSE_FENCE_LINE = re.compile(r"^\s*```\s*$")


class InputVersionError(ValueError):
    """A safe, stable error while resolving immutable analysis inputs."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def canonical_json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_uuid(value: str | UUID | None, *, name: str) -> UUID:
    if value is None or not str(value).strip():
        raise InputVersionError("service_unavailable", f"{name} active 설정이 없습니다")
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise InputVersionError("service_unavailable", f"{name} active 설정이 올바르지 않습니다") from exc


def _safe_created_by(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    if not clean or len(clean) > 128 or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in clean):
        raise InputVersionError("actor_name_invalid", "생성자 이름이 올바르지 않습니다")
    return clean


def active_version_ids(environ: Mapping[str, str] | None = None) -> tuple[UUID, UUID]:
    """Read active IDs directly from deployment environment only."""

    env = os.environ if environ is None else environ
    return (
        _as_uuid(env.get("BIDOPS_ACTIVE_PROFILE_VERSION_ID"), name="profile"),
        _as_uuid(env.get("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID"), name="analysis policy"),
    )


def _quality_metadata(rules: Mapping[str, Any]) -> tuple[str | None, float | None, float | None, float | None]:
    """Extract recorded activation measurements from compatible DB payloads."""

    candidates: list[Mapping[str, Any]] = [rules]
    for key in ("validation_metadata", "quality", "activation"):
        child = rules.get(key)
        if isinstance(child, Mapping):
            candidates.insert(0, child)
    def pick(*keys: str) -> Any:
        for candidate in candidates:
            for key in keys:
                if key in candidate:
                    return candidate[key]
        return None
    def number(*keys: str) -> float | None:
        value = pick(*keys)
        if value is None:
            return None
        # bool is an int subclass, but is never a quality measurement.
        if isinstance(value, bool):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None

    sample_hash = pick("sample_hash", "sample_sha256", "validation_sample_hash")
    return (
        str(sample_hash) if sample_hash is not None else None,
        number("required_item_recall", "recall"),
        number("human_agreement", "agreement"),
        number("unsupported_false_positive_rate", "unsupported_false_positive", "false_positive_rate"),
    )


def _normalise_quality_metadata(
    *,
    sample_hash: str | None = None,
    required_item_recall: float | None = None,
    human_agreement: float | None = None,
    unsupported_false_positive_rate: float | None = None,
    validation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the immutable quality identity, rejecting partial measurements.

    The policy bytes identify the algorithm, while this four-field object
    identifies the measured activation evidence.  In particular, an old
    unmeasured row and a later measured row intentionally have different
    identities even though their canonical policy SHA-256 is the same.
    """

    source: dict[str, Any] = dict(validation_metadata or {})
    for wrapper in ("validation_metadata", "quality", "activation"):
        nested = source.get(wrapper)
        if isinstance(nested, Mapping):
            source = dict(nested)
            break
    # Accept the historical aliases at the boundary, but store one spelling.
    aliases = {
        "sample_hash": ("sample_hash", "sample_sha256", "validation_sample_hash"),
        "required_item_recall": ("required_item_recall", "recall"),
        "human_agreement": ("human_agreement", "agreement"),
        "unsupported_false_positive_rate": ("unsupported_false_positive_rate", "unsupported_false_positive", "false_positive_rate"),
    }
    values: dict[str, Any] = {
        "sample_hash": sample_hash,
        "required_item_recall": required_item_recall,
        "human_agreement": human_agreement,
        "unsupported_false_positive_rate": unsupported_false_positive_rate,
    }
    for canonical, names in aliases.items():
        if values[canonical] is not None:
            continue
        for name in names:
            if name in source:
                values[canonical] = source[name]
                break

    supplied = [value is not None for value in values.values()]
    if not any(supplied):
        return {}
    if not all(supplied):
        raise InputVersionError("invalid_request", "policy 품질 metadata는 sample sha와 세 metric을 모두 포함해야 합니다")

    digest = values["sample_hash"]
    if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower() or any(char not in "0123456789abcdef" for char in digest):
        raise InputVersionError("invalid_request", "sample sha는 lowercase hex64여야 합니다")
    normalised: dict[str, Any] = {"sample_hash": digest}
    for key in ("required_item_recall", "human_agreement", "unsupported_false_positive_rate"):
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputVersionError("invalid_request", "policy 품질 metric은 유한한 숫자여야 합니다")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0 <= numeric <= 1:
            raise InputVersionError("invalid_request", "policy 품질 metric은 0..1 범위의 유한한 숫자여야 합니다")
        normalised[key] = numeric
    return normalised


def _quality_mapping(rules: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the quality object from both legacy and current policy rows."""

    for key in ("validation_metadata", "quality", "activation"):
        value = rules.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {
        key: rules[key]
        for key in (
            "sample_hash", "sample_sha256", "validation_sample_hash",
            "required_item_recall", "recall", "human_agreement", "agreement",
            "unsupported_false_positive_rate", "unsupported_false_positive", "false_positive_rate",
        )
        if key in rules
    }


def policy_activation_valid(policy: AnalysisPolicyVersion) -> bool:
    rules = policy.validation_rules if isinstance(policy.validation_rules, Mapping) else {}
    sample_hash, recall, agreement, false_positive = _quality_metadata(rules)
    return bool(
        sample_hash
        and len(sample_hash) == 64
        and sample_hash == sample_hash.lower()
        and all(character in "0123456789abcdef" for character in sample_hash)
        and recall is not None
        and 0 <= recall <= 1
        and recall >= 0.8
        and agreement is not None
        and 0 <= agreement <= 1
        and agreement >= 0.7
        and false_positive is not None
        and 0 <= false_positive <= 1
        and false_positive <= 0.1
    )


def _policy_hash_matches(policy: AnalysisPolicyVersion) -> bool:
    rules = policy.validation_rules if isinstance(policy.validation_rules, Mapping) else {}
    validation = {key: rules[key] for key in ("max_unsupported_false_positive_rate", "min_human_agreement", "min_required_item_recall") if key in rules}
    candidate = {
        "chunking": {"max_characters": 24000, "max_requirements": 20, "merge_order": ["stage_sequence", "document_ordinal", "page", "block_order", "requirement_id", "slice_index"], "retries": 2, "timeout_seconds": 300},
        "generation": rules.get("generation"),
        "model_endpoint_ref": policy.model_endpoint_ref, "model_name": policy.model_name,
        "schema": POLICY_SCHEMA, "stages": policy.prompts, "validation": validation,
    }
    try:
        approved_raw = CANONICAL_POLICY_FILE.read_bytes()
        approved = json.loads(approved_raw.decode("utf-8"))
        approved_canonical = canonical_json_bytes(approved)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False
    # The active row must match both the immutable DB hash and the exact
    # checked-in approval bytes.  A changed policy file or a tampered row
    # therefore fails closed before any model invocation.
    if approved_raw != approved_canonical or not isinstance(approved, Mapping) or approved.get("schema") != POLICY_SCHEMA:
        return False
    digest = canonical_json_hash(candidate)
    return digest == policy.policy_sha256 == _sha256(approved_canonical)


def validate_pinned_policy(policy: AnalysisPolicyVersion, *, allow_unmeasured_reference: bool = False) -> None:
    """Validate a review's already-pinned policy without reading active env IDs."""

    if not allow_unmeasured_reference and not policy_activation_valid(policy):
        raise InputVersionError("service_unavailable", "고정된 policy 품질 metadata가 유효하지 않습니다")
    if not _policy_hash_matches(policy):
        raise InputVersionError("service_unavailable", "고정된 policy hash가 승인본과 일치하지 않습니다")
    if policy.model_endpoint_ref != MODEL_ENDPOINT_REF or policy.model_name != MODEL_NAME:
        raise InputVersionError("service_unavailable", "허용되지 않은 analysis model입니다")


def policy_quality_snapshot(policy: AnalysisPolicyVersion) -> dict[str, Any]:
    """Return canonical measured metadata for a deep-review input snapshot."""

    rules = policy.validation_rules if isinstance(policy.validation_rules, Mapping) else {}
    quality = _quality_mapping(rules)
    try:
        return _normalise_quality_metadata(validation_metadata=quality)
    except InputVersionError as exc:
        raise InputVersionError("service_unavailable", "고정된 policy 품질 metadata가 유효하지 않습니다") from exc


def resolve_active_versions(
    session: Session,
    *,
    environ: Mapping[str, str] | None = None,
    allow_unmeasured_reference: bool = False,
) -> tuple[ProfileVersion, AnalysisPolicyVersion]:
    profile_id, policy_id = active_version_ids(environ)
    profile = session.get(ProfileVersion, profile_id)
    policy = session.get(AnalysisPolicyVersion, policy_id)
    if profile is None or policy is None:
        raise InputVersionError("service_unavailable", "active profile 또는 analysis policy를 찾을 수 없습니다")
    if not allow_unmeasured_reference and not policy_activation_valid(policy):
        raise InputVersionError("service_unavailable", "품질 표본 검증을 통과하지 않은 policy입니다")
    if not _policy_hash_matches(policy):
        raise InputVersionError("service_unavailable", "active policy hash가 payload와 일치하지 않습니다")
    if not isinstance(profile.profile_payload, Mapping) or profile.profile_payload.get("source_sha256") != profile.profile_sha256:
        raise InputVersionError("service_unavailable", "active profile hash가 payload와 일치하지 않습니다")
    if policy.model_endpoint_ref != MODEL_ENDPOINT_REF or policy.model_name != MODEL_NAME:
        raise InputVersionError("service_unavailable", "허용되지 않은 analysis model입니다")
    return profile, policy


@dataclass(frozen=True)
class GradeBasis:
    grade: str | None
    run_id: str | None
    review_id: int | None
    source: str


def effective_grade_basis(session: Session, notice_id: int) -> GradeBasis:
    notice = session.get(Notice, notice_id)
    if notice is None:
        raise InputVersionError("not_found", "공고를 찾을 수 없습니다")
    # 리뷰도 판정과 마찬가지로 선별 소유다. 공고당 리뷰는 하나이므로 "가장 최근
    # 리뷰에 정정 등급이 있으면"과 "정정 등급이 있는 가장 최근 리뷰"는 같다.
    corrected = latest_corrected_grade(session, notice_id)
    if corrected is not None:
        return GradeBasis(corrected.grade, corrected.run_id, corrected.review_id, "human_review")
    latest_observation = session.scalar(
        select(NoticeObservation)
        .where(NoticeObservation.notice_id == notice_id)
        .order_by(NoticeObservation.observed_at.desc(), NoticeObservation.id.desc())
        .limit(1)
    )
    observed_run_id = latest_observation.run_id if latest_observation is not None else None
    # 판정은 선별 소유이므로 공개 seam 함수로만 읽는다(명세 §6.3).
    judgment = current_judgment(session, notice_id)
    if judgment is not None:
        return GradeBasis(judgment.grade, observed_run_id, None, "screening_judgment")
    return GradeBasis(None, observed_run_id, None, "unknown")


def _safe_fact_quote(source_text: str, item: ParsedItem) -> str | None:
    """Return the exact YAML fence containing ``item.source_line``.

    ``ParsedItem.source_line`` is the one-based opening-fence line.  Searching
    globally by the leaf key is unsafe because profile YAML commonly repeats
    keys such as ``status``.  Keeping the complete fence is conservative and
    makes the quote a byte-for-byte source substring while retaining enough
    context to resolve nested/repeated facts deterministically.
    """

    lines = source_text.splitlines(keepends=True)
    opening = item.source_line - 1
    if opening < 0 or opening >= len(lines) or not _YAML_FENCE_LINE.fullmatch(lines[opening].rstrip("\r\n")):
        return None
    closing = opening + 1
    while closing < len(lines) and not _CLOSE_FENCE_LINE.fullmatch(lines[closing].rstrip("\r\n")):
        closing += 1
    if closing >= len(lines):
        return None
    # Prefer the exact YAML mapping node for this parsed path.  This keeps a
    # large profile block bounded while still resolving repeated leaf keys by
    # their full path; the complete fence remains a conservative fallback for
    # unusual YAML constructs.
    body = "".join(lines[opening + 1:closing])
    try:
        root = yaml.compose(body)
        tokens = [token for token in item.key.split(".") if token]
        node: Any = root
        for token in tokens:
            if token.startswith("[") and token.endswith("]"):
                node = node.value[int(token[1:-1])]
                continue
            if not hasattr(node, "value") or not isinstance(node.value, list):
                raise ValueError("not a YAML mapping")
            match = next((value for key, value in node.value if getattr(key, "value", None) == token), None)
            if match is None:
                raise ValueError("fact path not found")
            node = match
        if node is not None and hasattr(node, "start_mark") and hasattr(node, "end_mark"):
            start = opening + 1 + int(node.start_mark.line)
            # YAML end_mark.line is the exclusive line offset.
            end = opening + int(node.end_mark.line)
            if 0 <= start <= end < len(lines):
                quote = "".join(lines[start:end + 1])
                if quote and quote in source_text:
                    return quote
    except (AttributeError, IndexError, TypeError, ValueError, yaml.YAMLError):
        pass
    return "".join(lines[opening:closing + 1])


def _store_profile_source(raw: bytes, digest: str) -> tuple[str, int, assets.ObjectMetadata]:
    """Store and re-read profile bytes before creating DB references.

    Profile evidence is valid only when its ContentObject points at bytes that
    were actually written and verified below the private source namespace.
    The returned object key is a server-generated value derived only from the
    verified digest; callers never accept a user-supplied path.
    """

    object_key = f"source/profile-{digest}.md"
    try:
        _destination, metadata = assets.store_named("source", object_key, raw, content_type="text/markdown")
        reread, reread_metadata = assets.read_object("source", object_key)
    except assets.AssetError as exc:
        raise InputVersionError("service_unavailable", "프로필 source location을 저장할 수 없습니다") from exc
    if len(reread) != len(raw) or _sha256(reread) != digest or metadata.etag != reread_metadata.etag:
        raise InputVersionError("service_unavailable", "프로필 source location hash 검증에 실패했습니다")
    return object_key, len(raw), reread_metadata


def _profile_payload_and_facts(source: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    raw = source.read_bytes()
    text = raw.decode("utf-8")
    parsed = parse_profile(source)
    item_pairs = [(section, item) for section in walk_sections(parsed.sections) for item in section.items]
    key_counts = Counter(item.key for _section, item in item_pairs if item.key)
    occurrence_counts: Counter[tuple[str, str]] = Counter()
    facts: list[dict[str, Any]] = []
    for section, item in item_pairs:
        quote = _safe_fact_quote(text, item)
        fact_key = item.key
        if item.key and key_counts[item.key] > 1:
            # Leaf names such as ``capability`` intentionally repeat in the
            # profile.  A source line is not an identity (adding a paragraph
            # would change every later key), so qualify the path by its stable
            # numbered section and use an ordinal within that section.
            occurrence = occurrence_counts[(section.id, item.key)]
            occurrence_counts[(section.id, item.key)] += 1
            fact_key = f"{section.id}.{item.key}[{occurrence}]"
        facts.append(
            {
                "fact_key": fact_key,
                # A parser value without a source quote is deliberately
                # downgraded to unknown rather than being promoted to a
                # synthetic fact/evidence pair.
                "status": item.status if quote and item.key else "unknown",
                "value": item.value,
                "section_id": section.id,
                "section_number": section.number,
                "locator": {"fact_key": fact_key},
                "quote": quote,
                "source_file": PROFILE_SOURCE_FILE,
            }
        )
    # Parse errors and absent blocks remain explicit unknown information; they
    # are never silently converted into a positive company fact.
    payload = {
        "schema": "bidops.company-profile.v1",
        "source_file": PROFILE_SOURCE_FILE,
        "source_sha256": _sha256(raw),
        "facts": facts,
        "parse_errors": list(parsed.parse_errors),
    }
    fact_keys = [fact.get("fact_key") for fact in facts]
    if not 1 <= len(facts) <= 256 or any(not isinstance(key, str) or not key.strip() for key in fact_keys) or len(set(fact_keys)) != len(fact_keys):
        raise InputVersionError("invalid_request", "company profile은 1~256개의 고유 stable fact key를 가져야 합니다")
    return payload, facts, raw


def import_profile_version(
    session: Session,
    source: Path | None = None,
    *,
    created_by_name: str | None = None,
    label: str = "company-profile",
) -> ProfileVersion:
    """Idempotently import the canonical Markdown profile as an immutable row."""

    created_by_name = _safe_created_by(created_by_name)
    source_path = Path(source or profile_path())
    if str(source_path).lower().startswith(("http:", "https:")):
        raise InputVersionError("invalid_request", "프로필 source는 URL일 수 없습니다")
    try:
        payload, facts, raw = _profile_payload_and_facts(source_path)
    except (OSError, UnicodeError) as exc:
        raise InputVersionError("invalid_request", "프로필 source를 읽을 수 없습니다") from exc
    digest = payload["source_sha256"]
    source_key, source_size, source_metadata = _store_profile_source(raw, digest)
    existing = session.scalar(select(ProfileVersion).where(ProfileVersion.profile_sha256 == digest).limit(1))
    if existing is not None:
        _validate_profile_snapshot(session, existing, require_verified_source=True)
        return existing
    # A nested transaction is the retry boundary.  In particular, never call
    # ``Session.rollback`` here: it would erase unrelated pending work owned by
    # the caller.  SQLAlchemy flushes caller-pending rows before opening the
    # savepoint, then confines these newly-created input rows to the savepoint.
    for _attempt in range(3):
        try:
            with session.begin_nested():
                max_version = session.scalar(select(func.max(ProfileVersion.version))) or 0
                profile = ProfileVersion(
                    id=uuid4(), version=int(max_version) + 1, label=label,
                    profile_payload=payload, profile_sha256=digest,
                    source_kind="company-profile-markdown", created_by_name=created_by_name,
                )
                session.add(profile)
                session.flush()
                content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest).limit(1))
                if content is None:
                    content = ContentObject(id=uuid4(), sha256=digest, size_bytes=source_size, detected_mime="text/markdown", retention_class="profile-source")
                    session.add(content)
                    session.flush()
                elif content.size_bytes != source_size:
                    raise InputVersionError("service_unavailable", "프로필 ContentObject size가 source bytes와 다릅니다")
                location = session.scalar(select(ContentObjectLocation).where(
                    ContentObjectLocation.content_object_id == content.id,
                    ContentObjectLocation.namespace_key == "source",
                ).limit(1))
                if location is None:
                    session.add(ContentObjectLocation(
                        id=uuid4(), content_object_id=content.id, namespace_key="source",
                        object_key=source_key, object_version_id=source_metadata.object_version_id,
                        status="verified", etag=source_metadata.etag,
                        verified_at=datetime.now(UTC),
                    ))
                for fact in facts:
                    if fact["status"] == "unknown" or not isinstance(fact.get("quote"), str) or not fact["quote"]:
                        continue
                    session.add(ProfileEvidence(
                        id=uuid4(), profile_version_id=profile.id, fact_key=fact["fact_key"],
                        content_object_id=content.id, source_sha256=digest,
                        locator_type="profile_fact", locator=fact["locator"], quote=fact["quote"],
                        confirmed_by_name=created_by_name or "system", confirmed_at=datetime.now(UTC),
                    ))
                session.flush()
            return profile
        except IntegrityError:
            # The savepoint has rolled back, but the surrounding Session
            # transaction (including caller work) remains usable.  Resolve an
            # exact immutable identity before allocating a new version.
            existing = session.scalar(select(ProfileVersion).where(ProfileVersion.profile_sha256 == digest).limit(1))
            if existing is not None:
                _validate_profile_snapshot(session, existing, require_verified_source=True)
                return existing
    raise InputVersionError("service_unavailable", "동시 profile version 생성에 실패했습니다")


def _verified_profile_source(session: Session, evidence_rows: Sequence[ProfileEvidence]) -> str | None:
    """Read the verified profile source used by evidence, if available."""

    if not evidence_rows:
        return None
    content_ids = {row.content_object_id for row in evidence_rows}
    if len(content_ids) != 1:
        return None
    content = session.get(ContentObject, next(iter(content_ids)))
    if content is None:
        return None
    location = session.scalar(select(ContentObjectLocation).where(
        ContentObjectLocation.content_object_id == content.id,
        ContentObjectLocation.namespace_key == "source",
        ContentObjectLocation.status == "verified",
    ).order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc()).limit(1))
    if location is None or not isinstance(location.object_key, str) or not location.object_key or location.object_key.startswith(("/", "\\")):
        return None
    try:
        raw, metadata = assets.read_object("source", location.object_key)
    except (assets.AssetError, OSError, ValueError):
        return None
    if len(raw) != content.size_bytes or _sha256(raw) != content.sha256 or location.etag != metadata.etag or location.object_version_id != metadata.object_version_id:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _validate_profile_snapshot(
    session: Session,
    profile: ProfileVersion,
    *,
    require_verified_source: bool = False,
) -> None:
    """Fail closed when any pinned fact/evidence pair is incomplete or altered.

    The import path has private ``source`` credentials and re-verifies the
    original Markdown bytes.  The analysis worker intentionally has only
    structure-read credentials, so its runtime check validates the immutable
    fact/evidence pairs and their content-object lineage without treating the
    inaccessible source namespace as evidence tampering.
    """

    payload = profile.profile_payload if isinstance(profile.profile_payload, Mapping) else None
    if payload is None or payload.get("schema") != "bidops.company-profile.v1" or payload.get("source_file") != PROFILE_SOURCE_FILE or payload.get("source_sha256") != profile.profile_sha256:
        raise InputVersionError("service_unavailable", "active profile hash가 payload와 일치하지 않습니다")
    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise InputVersionError("service_unavailable", "active profile facts가 올바르지 않습니다")
    fact_keys = [fact.get("fact_key") for fact in facts if isinstance(fact, Mapping)]
    if not 1 <= len(facts) <= 256 or len(fact_keys) != len(facts) or any(not isinstance(key, str) or not key.strip() for key in fact_keys) or len(set(fact_keys)) != len(fact_keys):
        raise InputVersionError("service_unavailable", "profile facts는 1~256개의 고유 stable key여야 합니다")
    evidence_rows = session.scalars(select(ProfileEvidence).where(ProfileEvidence.profile_version_id == profile.id)).all()
    by_fact: dict[str, list[ProfileEvidence]] = {}
    for row in evidence_rows:
        if not isinstance(row.fact_key, str) or not row.fact_key.strip() or row.fact_key not in fact_keys:
            raise InputVersionError("service_unavailable", "profile evidence fact key가 profile payload와 일치하지 않습니다")
        by_fact.setdefault(row.fact_key, []).append(row)
        content = session.get(ContentObject, row.content_object_id)
        if row.source_sha256 != profile.profile_sha256 or content is None or content.sha256 != profile.profile_sha256 or row.locator_type != "profile_fact" or not isinstance(row.locator, Mapping) or dict(row.locator) != {"fact_key": row.fact_key} or not isinstance(row.quote, str) or not row.quote:
            raise InputVersionError("service_unavailable", "profile evidence 계보가 올바르지 않습니다")
    source_text = _verified_profile_source(session, evidence_rows)
    if require_verified_source and source_text is None:
        raise InputVersionError("service_unavailable", "profile 원문을 검증할 수 없습니다")
    for index, fact in enumerate(facts):
        if not isinstance(fact, Mapping) or not isinstance(fact.get("fact_key"), str):
            raise InputVersionError("service_unavailable", f"profile fact {index}가 올바르지 않습니다")
        if fact.get("status") not in {"confirmed", "inferred", "unknown"}:
            raise InputVersionError("service_unavailable", "profile fact status가 올바르지 않습니다")
        if not isinstance(fact.get("quote"), str) or not fact["quote"] or (source_text is not None and fact["quote"] not in source_text):
            raise InputVersionError("service_unavailable", "profile fact quote가 원문 substring이 아닙니다")
        matches = by_fact.get(fact["fact_key"], [])
        if fact.get("status") == "unknown":
            if matches:
                raise InputVersionError("service_unavailable", "unknown profile fact에는 evidence를 둘 수 없습니다")
            continue
        if len(matches) != 1:
            raise InputVersionError("service_unavailable", "모든 non-unknown profile fact는 정확히 하나의 evidence가 필요합니다")
        row = matches[0]
        if fact.get("quote") != row.quote or not isinstance(fact.get("quote"), str) or (source_text is not None and row.quote not in source_text):
            raise InputVersionError("service_unavailable", "profile evidence quote가 원문 substring이 아닙니다")
        if fact.get("locator") != row.locator:
            raise InputVersionError("service_unavailable", "profile evidence locator가 fact와 일치하지 않습니다")


def load_canonical_policy(path: Path | None = None) -> tuple[dict[str, Any], bytes, str]:
    policy_path = Path(path or CANONICAL_POLICY_FILE)
    try:
        raw = policy_path.read_bytes()
        policy = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputVersionError("invalid_request", "canonical analysis policy를 읽을 수 없습니다") from exc
    if not isinstance(policy, Mapping) or policy.get("schema") != POLICY_SCHEMA:
        raise InputVersionError("invalid_request", "canonical analysis policy schema가 올바르지 않습니다")
    canonical = canonical_json_bytes(policy)
    if raw != canonical:
        raise InputVersionError("invalid_request", "canonical analysis policy bytes가 승인본과 다릅니다")
    if policy_path.resolve() != CANONICAL_POLICY_FILE.resolve():
        try:
            approved = json.loads(CANONICAL_POLICY_FILE.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InputVersionError("invalid_request", "승인된 analysis policy를 읽을 수 없습니다") from exc
        if policy != approved:
            raise InputVersionError("invalid_request", "승인되지 않은 analysis policy입니다")
    return dict(policy), canonical, _sha256(canonical)


def import_policy_version(
    session: Session,
    policy_path: Path | None = None,
    *,
    created_by_name: str | None = None,
    label: str = "analysis-policy-lean-v1",
    sample_hash: str | None = None,
    sample_sha256: str | None = None,
    required_item_recall: float | None = None,
    human_agreement: float | None = None,
    unsupported_false_positive_rate: float | None = None,
    validation_metadata: Mapping[str, Any] | None = None,
) -> AnalysisPolicyVersion:
    """Idempotently import the byte-canonical policy.

    Quality measurements are recorded in the DB payload, not appended to the
    approved policy file.  This keeps the policy file hash stable while making
    activation fail closed until a measured sample is supplied.
    """

    created_by_name = _safe_created_by(created_by_name)
    policy, canonical, digest = load_canonical_policy(policy_path)
    rules = dict(policy["validation"])
    rules["generation"] = dict(policy["generation"])
    if sample_hash is not None and sample_sha256 is not None and sample_hash != sample_sha256:
        raise InputVersionError("invalid_request", "sample sha alias 값이 서로 다릅니다")
    quality = _normalise_quality_metadata(
        sample_hash=sample_hash if sample_hash is not None else sample_sha256,
        required_item_recall=required_item_recall,
        human_agreement=human_agreement,
        unsupported_false_positive_rate=unsupported_false_positive_rate,
        validation_metadata=validation_metadata,
    )
    if quality:
        rules["validation_metadata"] = quality
    # Do not use policy_sha256 as the idempotency key: the same canonical
    # policy can have an old unmeasured row and a later measured row.
    identity = canonical_json_hash({"policy_sha256": digest, "quality": quality})
    same_bytes = session.scalars(select(AnalysisPolicyVersion).where(AnalysisPolicyVersion.policy_sha256 == digest).order_by(AnalysisPolicyVersion.version.desc())).all()
    # Policy identity is canonical policy bytes *and* normalized quality
    # metadata.  An unmeasured seed and a measured seed are therefore distinct
    # immutable rows in either insertion order; only the exact same identity
    # replays.
    for existing in same_bytes:
        existing_rules = existing.validation_rules if isinstance(existing.validation_rules, Mapping) else {}
        existing_quality = _normalise_quality_metadata(validation_metadata=_quality_mapping(existing_rules))
        if canonical_json_hash({"policy_sha256": digest, "quality": existing_quality}) == identity:
            return existing
    # Version allocation is application-side for portability.  Retry only the
    # allocation race inside a savepoint; every row remains immutable and a
    # matching row is returned without any UPDATE or outer transaction reset.
    for _attempt in range(3):
        try:
            with session.begin_nested():
                max_version = session.scalar(select(func.max(AnalysisPolicyVersion.version))) or 0
                row = AnalysisPolicyVersion(
                    id=uuid4(), version=int(max_version) + 1, label=label,
                    model_endpoint_ref=policy["model_endpoint_ref"], model_name=policy["model_name"],
                    prompts=policy["stages"], validation_rules=rules,
                    policy_sha256=digest, created_by_name=created_by_name,
                )
                session.add(row)
                session.flush()
            return row
        except IntegrityError:
            # The savepoint is rolled back automatically.  The caller's
            # pending rows and surrounding transaction remain intact.
            for existing in session.scalars(select(AnalysisPolicyVersion).where(AnalysisPolicyVersion.policy_sha256 == digest)).all():
                existing_rules = existing.validation_rules if isinstance(existing.validation_rules, Mapping) else {}
                existing_quality = _normalise_quality_metadata(validation_metadata=_quality_mapping(existing_rules))
                if canonical_json_hash({"policy_sha256": digest, "quality": existing_quality}) == identity:
                    return existing
            # A different quality identity may have won the same version;
            # retry with the newly observed maximum instead of overwriting it.
    raise InputVersionError("service_unavailable", "동시 policy version 생성에 실패했습니다")


def profile_context(session: Session, profile: ProfileVersion) -> dict[str, Any]:
    _validate_profile_snapshot(session, profile)
    evidence_rows = session.scalars(select(ProfileEvidence).where(ProfileEvidence.profile_version_id == profile.id).order_by(ProfileEvidence.fact_key.asc(), ProfileEvidence.id.asc())).all()
    evidence = [
        {
            "profile_evidence_id": str(row.id), "profile_version_id": str(profile.id),
            "fact_key": row.fact_key, "source_sha256": row.source_sha256,
            "locator_type": row.locator_type, "locator": row.locator, "quote": row.quote,
        }
        for row in evidence_rows
    ]
    payload = dict(profile.profile_payload) if isinstance(profile.profile_payload, Mapping) else {}
    payload.pop("source_file", None)
    facts = [
        {key: value for key, value in fact.items() if key not in {"source_file", "source_path", "source_url"}}
        for fact in payload.get("facts", [])
        if isinstance(fact, Mapping)
    ]
    return {"profile_version_id": str(profile.id), "profile_sha256": profile.profile_sha256, "facts": facts, "evidence": evidence}


def _structure_payload(session: Session, item: DocumentBundleItem, structure: DocumentStructure) -> Mapping[str, Any]:
    """Load a confirmed structure object without projecting live documents."""

    location = session.scalar(select(ContentObjectLocation).where(
        ContentObjectLocation.content_object_id == structure.payload_content_object_id,
        ContentObjectLocation.namespace_key == "structure", ContentObjectLocation.status == "verified",
    ).order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc()).limit(1))
    payload_object = session.get(ContentObject, structure.payload_content_object_id)
    if location is None or payload_object is None or payload_object.sha256 != structure.payload_sha256:
        raise InputVersionError("structure_unavailable", "문서 구조 snapshot을 읽을 수 없습니다")
    try:
        raw, metadata = assets.read_object("structure", location.object_key)
        if len(raw) != payload_object.size_bytes or hashlib.sha256(raw).hexdigest() != structure.payload_sha256 or location.etag != metadata.etag or location.object_version_id != metadata.object_version_id:
            raise ValueError("hash")
        payload = json.loads(raw.decode("utf-8"))
    except (assets.AssetError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise InputVersionError("structure_unavailable", "문서 구조 snapshot을 읽을 수 없습니다") from exc
    if not isinstance(payload, Mapping) or payload.get("document_version_id") != str(item.document_version_id) or payload.get("structure_id") != str(item.structure_id_at_confirmation) or payload.get("source_sha256") != item.content_sha256:
        raise InputVersionError("structure_unavailable", "문서 구조 snapshot 계보가 일치하지 않습니다")
    try:
        return validate_structure(payload)
    except Exception as exc:
        raise InputVersionError("structure_unavailable", "문서 구조 snapshot 검증에 실패했습니다") from exc


def bundle_context(
    session: Session,
    bundle_id: UUID,
    *,
    structure_loader: Callable[[Session, DocumentStructure], Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    """Read only ready bundle items and their confirmation-time structures."""

    bundle = session.get(DocumentBundle, bundle_id)
    if bundle is None:
        raise InputVersionError("not_found", "document bundle을 찾을 수 없습니다")
    if bundle.status != "ready":
        raise InputVersionError("bundle_not_ready", "ready bundle만 심층 분석할 수 있습니다")
    items = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == bundle.id).order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())).all()
    if not items:
        raise InputVersionError("bundle_not_ready", "ready bundle snapshot이 비어 있습니다")
    structures: dict[str, Mapping[str, Any]] = {}
    documents: list[dict[str, Any]] = []
    for item in items:
        structure = session.get(DocumentStructure, item.structure_id_at_confirmation)
        if structure is None or structure.validation_status != "ready" or item.safety_status_at_confirmation != "safe":
            raise InputVersionError("bundle_not_ready", "ready bundle snapshot의 문서 구조가 안전하지 않습니다")
        # The bundle is an immutable confirmation snapshot.  A live structure
        # projection with a matching ID is not sufficient: all three identity
        # values must still equal what was confirmed for this item.
        if (
            structure.document_version_id != item.document_version_id
            or structure.source_sha256 != item.content_sha256
            or structure.payload_sha256 != item.structure_payload_sha256
        ):
            raise InputVersionError("structure_unavailable", "document structure가 ready bundle snapshot과 일치하지 않습니다")
        payload = structure_loader(session, structure) if structure_loader else _structure_payload(session, item, structure)
        # Injected loaders are test/storage adapters, not a schema bypass.  A
        # blocks-only mapping cannot establish the closed structure contract or
        # its immutable document/structure/source identity.
        if not isinstance(payload, Mapping):
            raise InputVersionError("structure_unavailable", "document structure payload가 올바르지 않습니다")
        if (
            payload.get("schema") != "bidops.document-structure.v1"
            or payload.get("structure_id") != str(item.structure_id_at_confirmation)
            or payload.get("document_version_id") != str(item.document_version_id)
            or payload.get("source_sha256") != item.content_sha256
        ):
            raise InputVersionError("structure_unavailable", "document structure snapshot 계보가 일치하지 않습니다")
        try:
            payload = validate_structure(payload)
        except Exception as exc:
            raise InputVersionError("structure_unavailable", "document structure snapshot 검증에 실패했습니다") from exc
        structure_id = str(item.structure_id_at_confirmation)
        structures[structure_id] = dict(payload)
        # Deliberately omit original filenames, provider URLs, and every live
        # DocumentVersion/Attachment projection from the model input context.
        documents.append({
            "document_version_id": str(item.document_version_id),
            "document_version_version": item.document_version_version,
            "ordinal": item.ordinal,
            "content_sha256": item.content_sha256,
            "detected_mime": item.detected_mime,
            "size_bytes": item.size_bytes,
            "role_at_confirmation": item.role_at_confirmation,
            "effective_date_at_confirmation": item.effective_date_at_confirmation.isoformat() if item.effective_date_at_confirmation else None,
            "replaces_id_at_confirmation": str(item.replaces_id_at_confirmation) if item.replaces_id_at_confirmation else None,
            "is_current_at_confirmation": item.is_current_at_confirmation,
            "safety_status_at_confirmation": item.safety_status_at_confirmation,
            "structure_id_at_confirmation": structure_id,
            "structure_payload_sha256": item.structure_payload_sha256,
        })
    context = {
        "schema": "bidops.document-bundle.v1", "bundle_id": str(bundle.id),
        "notice_id": bundle.notice_id, "revision": bundle.revision, "version": bundle.version,
        "status": bundle.status, "documents": documents,
        "issues": bundle.issues_snapshot if isinstance(bundle.issues_snapshot, list) else [],
        "confirmed_by": bundle.confirmed_by_name, "confirmed_at": bundle.confirmed_at.isoformat() if bundle.confirmed_at else None,
        "created_at": bundle.created_at.isoformat(),
    }
    return context, structures


__all__ = [
    "CANONICAL_POLICY_FILE", "MODEL_ENDPOINT_REF", "MODEL_NAME", "POLICY_SCHEMA", "PROFILE_SOURCE_FILE", "STAGES",
    "GradeBasis", "InputVersionError", "active_version_ids", "bundle_context", "canonical_json_bytes", "canonical_json_hash",
    "effective_grade_basis", "import_policy_version", "import_profile_version", "load_canonical_policy", "policy_activation_valid",
    "profile_context", "resolve_active_versions", "validate_pinned_policy", "policy_quality_snapshot",
]
