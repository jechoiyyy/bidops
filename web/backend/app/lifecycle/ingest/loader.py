"""Load a workflow run directory into the Step 1 SQLAlchemy schema."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError
from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..models import (
    Attachment,
    CollectedRecordIndex,
    CollectedRecordToken,
    IngestWarning,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    OrderPlanObservation,
    Run,
)
from .contracts import (
    CollectionArtifact,
    NoticeContract,
    OrderPlanArtifact,
    OrderPlanContract,
    ValidationArtifact,
    is_blank,
    model_extra_fields,
)
from ...core.generation_config import (
    GenerationConfigError,
    config_from_value,
    legacy_generation_config,
    validate_digest,
)
from ..services.opportunity_tracking import (
    RECHECK_SIGNAL_TRACKING_STATUSES,
    raise_recheck_signal,
)
from ..services.opportunity_integrity import (
    MERGE_CONFIRMATION_STRATEGY,
    MERGE_REASON_OFFICIAL_LINK,
    active_opportunity_predicate,
    apply_merge_rule,
    authoritative_link_predicate,
    merge_opportunities,
)
from ..services.opportunity_connections import parse_attachment_key
from ..services.collection_index import (
    BACKFILL_TRACKING_STATUSES,
    RECORD_KINDS,
    TRACKED_REFERENCE_STATUSES,
    IndexValues,
    chunks as _chunks,
    index_text as _index_text,
    latest_row_per_identity,
    latest_rows,
    mark_selected,
    rows_with_tokens,
    selection_stats,
    split_tokens,
    tokens_for,
    upsert_index_rows,
)
from ...core.run_id import (
    DEFAULT_TIMEZONE,
    RUN_ID_RE,
    deterministic_run_id,
    ensure_aware as _ensure_aware,
    parse_run_id,
)


EXECUTION_ID_RE = re.compile(r"^scr-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DECIMAL_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
# The survey measured the ordinary orderPlanUntyNo shape as R + two digits +
# two uppercase letters + eight digits (13 characters).  Other observed
# values are retained verbatim as unresolved input; they are never guessed
# into this shape.
ORDER_PLAN_UNTY_NO_RE = re.compile(r"^R\d{2}[A-Z]{2}\d{8}$")
# v3 산출물이 generation binding을 싣는 schema 집합. 회차 적재기는 이 값을 보고
# 산출물을 정규화하고, 판정 적재를 맡은 모듈이 같은 규칙으로 다시 읽는다.
V3_GENERATION_SCHEMAS = {
    "bidops.screening-input.v1",
    "bidops.decisions.v3",
    "bidops.screening.v3",
}
ORDER_PLAN_ARTIFACT_SCHEMA = "bidops.collected-order-plans.v1"
# The importer can display the earlier offline population artifact and the
# first draft spelling, but only ORDER_PLAN_ARTIFACT_SCHEMA is written by the
# current contract.  Compatibility here is read-only and never rewrites the
# source file.
ORDER_PLAN_ARTIFACT_SCHEMAS = {
    ORDER_PLAN_ARTIFACT_SCHEMA,
    "bidops.order-plan-population.v1",
    "bidops.order-plans.v1",
}
ORDER_PLAN_FILE = "collected-order-plans.json"
COLLECTION_FILE = "collected-notices.json"
COLLECTION_ARTIFACT_SCHEMA = "bidops.collected.v2"
#: ``validation``은 표본(`validation-set.json`)·C-1 입력(`screening-input.json`)을,
#: ``collection``은 수집 파일 전체를 색인한 뒤 선별 규칙에 맞는 레코드를 적재한다.
IngestSelection = Literal["validation", "collection"]
INGEST_SELECTIONS = ("validation", "collection")
INDEXED_INGEST_REASONS = ("tracked_backfill", "search_result")
_PRE_SPEC_SOURCE_TYPES = frozenset({"pre_spec", "prespec", "pre-spec"})
_PRE_SPEC_KEY_PREFIXES = ("pre:", "pre_spec:", "prespec:", "pre-spec:", "spec:")
NOTICE_OBSERVATION_SNAPSHOT_SCHEMA = "bidops.notice-observation-snapshot.v1"
ORDER_PLAN_OBSERVATION_SNAPSHOT_SCHEMA = "bidops.order-plan-observation-snapshot.v1"
class ObservationSnapshotConflictError(ValueError):
    """The same external identity/run pair was presented with different bytes."""


def _is_aware_iso(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


@dataclass
class IngestResult:
    """A compact result returned by the Python API and used by the CLI."""

    run_id: str
    notices: int = 0
    order_plans: int = 0
    judgments: int = 0
    reviews: int = 0
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # A v3 binding is retained in the run projection and exposed to callers
    # after legacy normalization.  It is intentionally absent for v2 runs.
    generation_config: dict[str, Any] | None = None
    generation_config_digest: str | None = None
    screening_executions: int = 0
    screening_attempts: int = 0
    screening_results: int = 0
    screening_artifacts: int = 0
    screening_feedback: int = 0
    # Collection-mode selection statistics (spec §2.2).  ``None`` for the
    # validation/screening path so its output shape is unchanged.
    selection: dict[str, Any] | None = None

    @property
    def warning_counts(self) -> dict[str, int]:
        return dict(Counter(item["level"] for item in self.warnings))

    def as_dict(self) -> dict[str, Any]:
        result = {
            "run_id": self.run_id,
            "notices": self.notices,
            "order_plans": self.order_plans,
            "judgments": self.judgments,
            "reviews": self.reviews,
            "screening_executions": self.screening_executions,
            "screening_attempts": self.screening_attempts,
            "screening_results": self.screening_results,
            "screening_artifacts": self.screening_artifacts,
            "screening_feedback": self.screening_feedback,
            "warnings": self.warnings,
            "warning_counts": self.warning_counts,
        }
        if self.generation_config is not None and self.generation_config_digest is not None:
            result["generation_config"] = self.generation_config
            result["generation_config_digest"] = self.generation_config_digest
        if self.selection is not None:
            result["selection"] = self.selection
        return result


def discover_run_dirs(data_root: Path, run_id: str | None = None) -> list[Path]:
    """Find one run or all run directories under ``data_root/runs``."""

    runs_root = data_root / "runs"
    if run_id is not None:
        target = runs_root / run_id
        return [target] if target.is_dir() else []
    if not runs_root.is_dir():
        return []
    return sorted((path for path in runs_root.iterdir() if path.is_dir()), key=lambda p: p.name)





def _parse_datetime(value: Any, timezone_name: str, *, field_name: str = "datetime") -> datetime | None:
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value, timezone_name)
    if isinstance(value, date):
        return _ensure_aware(datetime.combine(value, datetime.min.time()), timezone_name)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is not a datetime string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc
    return _ensure_aware(parsed, timezone_name)


def _parse_date(value: Any) -> date | None:
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _ensure_zone(timezone_name: Any) -> tuple[str, ZoneInfo]:
    name = timezone_name if isinstance(timezone_name, str) and timezone_name else DEFAULT_TIMEZONE
    try:
        return name, ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE, ZoneInfo(DEFAULT_TIMEZONE)


def _raw_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_unset=False)
    return value if isinstance(value, dict) else {}


def _raw_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_notice(value: Any) -> NoticeContract:
    return value if isinstance(value, NoticeContract) else NoticeContract.model_validate(value)


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = _json_load(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _normalize_v3_generation_binding(
    value: Any, artifact_name: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize a v3 binding in memory and verify its canonical digest.

    The only compatibility exception is an old v3 artifact with neither
    generation field.  A missing half is ambiguous and all supplied values
    are parsed through the shared backend GenerationConfig parser; accepting
    a digest string by itself would let a producer claim an unverified model
    budget.  The caller owns the source bytes, which are never rewritten.
    """

    if not isinstance(value, dict):
        return None, f"{artifact_name} is not an object"
    if value.get("schema_version") not in V3_GENERATION_SCHEMAS:
        return value, None
    has_config = "generation_config" in value
    has_digest = "generation_config_digest" in value
    if has_config != has_digest:
        missing = "generation_config_digest" if has_config else "generation_config"
        return None, f"{artifact_name} generation binding is partial ({missing} is missing)"

    if not has_config:
        legacy = legacy_generation_config()
        return {
            **value,
            "generation_config": legacy.canonical_value(),
            "generation_config_digest": legacy.digest(),
        }, None

    try:
        config = config_from_value(value.get("generation_config"))
        digest = validate_digest(config, value.get("generation_config_digest"))
    except (GenerationConfigError, AttributeError, TypeError):
        return None, f"{artifact_name} generation binding is invalid"
    # Keep the derived object canonical even when an equivalent mapping was
    # supplied with a different key order.  The digest remains the producer's
    # value only after parser verification above.
    normalized = {
        **value,
        "generation_config": config.canonical_value(),
        "generation_config_digest": digest,
    }
    return normalized, None


def _read_screening_input(path: Path) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Read the immutable v3 input without conflating absent and invalid.

    A present screening input is authoritative.  Falling back to a
    validation-set projection after malformed or non-canonical bytes would
    silently publish a different candidate set, so callers receive a distinct
    ``present`` bit and safe invalid reason.
    """
    if path.is_symlink():
        return True, None, "file is a symlink"
    if not path.exists():
        return False, None, None
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError):
        return True, None, "file is unreadable"
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return True, None, "JSON is invalid"
    if not isinstance(value, dict):
        return True, None, "top-level value is not an object"
    try:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return True, None, "JSON is not canonical"
    if canonical != raw:
        return True, None, "JSON is not canonical"
    normalized, generation_error = _normalize_v3_generation_binding(
        value, "screening-input.json"
    )
    if generation_error is not None or normalized is None:
        return True, None, generation_error or "generation binding is invalid"
    return True, normalized, None


def _first_generated_at(
    raws: list[dict[str, Any] | None], fallback_path: Path, timezone_name: str
) -> datetime:
    for raw in raws:
        if not raw:
            continue
        value = raw.get("generated_at")
        if not is_blank(value):
            try:
                return _parse_datetime(value, timezone_name, field_name="generated_at") or datetime.fromtimestamp(
                    fallback_path.stat().st_mtime, timezone.utc
                )
            except (OSError, ValueError):
                continue
    try:
        return datetime.fromtimestamp(fallback_path.stat().st_mtime, timezone.utc)
    except OSError:
        # A directory always has a stat in normal operation.  This final
        # branch is deterministic for callers using an unusual virtual path.
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _source_window(raws: list[dict[str, Any] | None]) -> tuple[date | None, date | None, str]:
    for raw in raws:
        if not raw or not isinstance(raw.get("source_window"), dict):
            continue
        source = raw["source_window"]
        timezone_name, _ = _ensure_zone(source.get("timezone"))
        return _parse_date(source.get("from")), _parse_date(source.get("to")), timezone_name
    return None, None, DEFAULT_TIMEZONE


def _record_warning(
    session: Session,
    run_id: str,
    level: str,
    code: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> IngestWarning:
    warning = IngestWarning(
        run_id=run_id,
        level=level,
        code=code,
        message=message,
        context_json=context,
    )
    session.add(warning)
    return warning


def _record_unknown_fields(
    session: Session,
    run_id: str,
    fields: list[str],
    source: str,
) -> None:
    for field_name in fields:
        _record_warning(
            session,
            run_id,
            "info",
            "unknown_field",
            f"알 수 없는 필드를 무시했습니다: {field_name}",
            {"file": source, "field": field_name},
        )


def _parse_decimal(value: Any, field_name: str, notice_key: str, session: Session, run_id: str) -> Decimal | None:
    if is_blank(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _record_warning(
            session,
            run_id,
            "warning",
            "invalid_number",
            f"{field_name} 값을 숫자로 변환하지 못했습니다.",
            {"notice_id": notice_key, "field": field_name, "value": str(value)},
        )
        return None


def parse_notice_key(notice_key: str) -> tuple[str | None, str | None]:
    """Parse ``bid:<bid_no>:<bid_ord>`` without making malformed ids fatal."""

    parts = notice_key.split(":") if isinstance(notice_key, str) else []
    if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
        return parts[1], parts[2]
    return None, None


def parse_order_plan_unty_no(value: Any) -> str | None:
    """Return a measured-format order-plan key, or ``None`` on parse failure.

    The two nonstandard values in the lifecycle survey must remain available
    for human review.  This helper therefore validates without rewriting or
    partially extracting arbitrary identifiers.
    """

    if is_blank(value):
        return None
    candidate = str(value).strip()
    return candidate if ORDER_PLAN_UNTY_NO_RE.fullmatch(candidate) else None


def _first_order_plan_bid_no(value: Any) -> str | None:
    """Extract one measured 13-digit bid number from a plan reference list.

    ``bidNtceNoList`` stores comma-separated 16-character values: the bid
    number followed by its three-character order.  Only that measured shape is
    accepted for evidence; an unfamiliar value remains available in the plan
    row but is not partially sliced into a relationship key.
    """

    if isinstance(value, (list, tuple)):
        tokens = [str(item).strip() for item in value if not is_blank(item)]
    elif is_blank(value):
        tokens = []
    else:
        tokens = [item.strip() for item in str(value).split(",")]
    for token in tokens:
        if len(token) == 16 and token[-3:].isdigit() and token[:-3]:
            return token[:-3]
    return None


def _notice_values(
    notice: NoticeContract,
    raw: dict[str, Any],
    timezone_name: str,
    session: Session,
    run_id: str,
) -> dict[str, Any] | None:
    notice_key = notice.notice_id
    if is_blank(notice_key):
        _record_warning(
            session,
            run_id,
            "error",
            "notice_id_missing",
            "notice_id가 없는 공고를 적재하지 않았습니다.",
            {"field": "notice_id"},
        )
        return None
    bid_no, bid_ord = parse_notice_key(str(notice_key))
    values: dict[str, Any] = {
        "notice_key": str(notice_key),
        "bid_no": bid_no,
        "bid_ord": bid_ord,
        "source_type": notice.source_type,
        "title": notice.title,
        "agency": notice.agency,
        "budget": _parse_decimal(notice.budget, "budget", str(notice_key), session, run_id),
        "estimated_price": _parse_decimal(
            notice.estimated_price, "estimated_price", str(notice_key), session, run_id
        ),
        "method": notice.method,
        "url": notice.url,
        "sample_role": notice.sample_role,
        "sample_stratum": notice.sample_stratum,
        "collection_bucket": notice.collection_bucket,
        "procurement_class_json": _json_value(notice.procurement_class),
        "region_limit_json": _json_value(notice.region_limit),
        "lifecycle_json": _lifecycle_payload(notice, raw),
        "qualification_flags_json": _qualification_flags_payload(notice),
        "focus_matches_json": _json_value(notice.focus_matches),
        "performance_matches_json": _json_value(notice.performance_matches),
        "performance_top_score": _float_or_none(notice.performance_top_score),
        "candidate_sources_json": _json_value(notice.candidate_sources),
        "unknown_fields_json": _json_value(notice.unknown_fields),
        "raw_source": notice.raw_source,
    }
    for field_name in ("published_at", "deadline_at"):
        try:
            values[field_name] = _parse_datetime(
                getattr(notice, field_name), timezone_name, field_name=field_name
            )
        except ValueError as exc:
            _record_warning(
                session,
                run_id,
                "warning",
                "invalid_datetime",
                str(exc),
                {"notice_id": str(notice_key), "field": field_name},
            )
            values[field_name] = None
    return values


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_unset=False)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _snapshot_json_value(value: Any) -> Any:
    """Return the stable JSON representation used by observation digests."""

    value = _json_value(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation snapshot datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _snapshot_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_json_value(item) for item in value]
    return value


def _observation_snapshot(
    schema_version: str,
    record_kind: str,
    record: dict[str, Any],
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "record_kind": record_kind,
        "record": _snapshot_json_value(record),
    }
    if attachments is not None:
        normalized_attachments = [
            _snapshot_json_value(item) for item in attachments
        ]
        payload["attachments"] = sorted(
            normalized_attachments,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return payload, hashlib.sha256(encoded).hexdigest()


def _check_existing_observation_snapshot(
    session: Session,
    *,
    run_id: str,
    identity_kind: str,
    identity: str,
    observation: NoticeObservation | OrderPlanObservation,
    schema_version: str,
    snapshot_jsonb: dict[str, Any],
    source_sha256: str,
) -> bool:
    """Return true for an idempotent replay and fail closed on a conflict.

    Pre-0009 observations intentionally have no snapshot.  They are retained
    as immutable legacy facts, so replay becomes a no-op with a warning rather
    than guessing a backfill from the mutable current projection.
    """

    stored = (
        observation.snapshot_schema_version,
        observation.snapshot_jsonb,
        observation.source_sha256,
    )
    if stored == (None, None, None):
        exists = session.scalar(
            select(IngestWarning.id).where(
                IngestWarning.run_id == run_id,
                IngestWarning.code == "observation_snapshot_unavailable",
                IngestWarning.context_jsonb["record_kind"].as_string() == identity_kind,
                IngestWarning.context_jsonb["identity"].as_string() == identity,
            )
        )
        if exists is None:
            _record_warning(
                session,
                run_id,
                "warning",
                "observation_snapshot_unavailable",
                "과거 관측에는 snapshot이 없어 같은 회차 재적재를 변경 없이 건너뛰었습니다.",
                {"record_kind": identity_kind, "identity": identity},
            )
        return True
    if (
        observation.snapshot_schema_version == schema_version
        and observation.source_sha256 == source_sha256
        and observation.snapshot_jsonb == snapshot_jsonb
    ):
        return True
    raise ObservationSnapshotConflictError(
        f"observation snapshot conflict: {identity_kind}={identity}, run_id={run_id}"
    )


#: Optional collected.v2 keys added after historical artifacts were frozen.  A
#: null or absent value is omitted from stored JSON and from the observation
#: snapshot so old runs keep their digest (spec §1.2).
_NULL_OMITTED_LIFECYCLE_FIELDS = ("opening_at",)
_NULL_OMITTED_QUALIFICATION_FIELDS = ("sw_industry_1468",)


def _qualification_flags_payload(notice: NoticeContract) -> dict[str, Any] | None:
    """Keep pre-spec-only flags out of notices whose artifact never set them.

    ``QualificationFlags`` materializes its defaults through ``_json_value``.
    The T-4 pre-spec fields must therefore be dropped when the source artifact
    did not supply them; otherwise every historical collected.v2 notice gains
    two ``null`` keys and its stored identity stops matching the artifact it
    came from.  This mirrors the same guard in :func:`_lifecycle_payload`.
    """

    payload = _json_value(notice.qualification_flags)
    if not isinstance(payload, dict):
        return payload
    payload = dict(payload)
    if isinstance(notice.qualification_flags, BaseModel):
        for optional_field in ("sw_business_status", "business_division"):
            if optional_field not in notice.qualification_flags.model_fields_set:
                payload.pop(optional_field, None)
    # The 1468 industry tag (spec §1.2) is stricter: it is stored only with a
    # value.  Current producers write an explicit null for every pre-spec and
    # every incomplete query, and that null must not change the digest of a
    # record whose older artifact never had the key.
    for optional_field in _NULL_OMITTED_QUALIFICATION_FIELDS:
        if payload.get(optional_field) is None:
            payload.pop(optional_field, None)
    return payload


def _lifecycle_payload(notice: NoticeContract, raw: dict[str, Any]) -> dict[str, Any] | None:
    """Keep measured linkage keys when a producer leaves them at top level."""

    base = _json_value(notice.lifecycle)
    had_lifecycle = base is not None
    payload = base
    if not isinstance(payload, dict):
        payload = {}
    else:
        payload = dict(payload)
    # ``Lifecycle`` is a compatibility model whose defaults are deliberately
    # materialized by ``_json_value``.  Do not make the optional T-11 field
    # appear as ``null`` in every historical notice: that would change the
    # identity of old collected.v2 artifacts.  An explicitly supplied null is
    # still retained because it is part of that source artifact.
    if isinstance(notice.lifecycle, BaseModel):
        for optional_field in ("order_plan_no", "bid_ntice_no_list"):
            if optional_field not in notice.lifecycle.model_fields_set:
                payload.pop(optional_field, None)
    # ``opening_at`` (spec §1.2) is kept only with a value; an explicit null
    # from a current producer and an absent key give the same stored identity.
    for optional_field in _NULL_OMITTED_LIFECYCLE_FIELDS:
        if payload.get(optional_field) is None:
            payload.pop(optional_field, None)
    for raw_key, stored_key in (
        ("orderPlanUntyNo", "order_plan_no"),
        ("order_plan_unty_no", "order_plan_no"),
        ("bfSpecRgstNo", "pre_spec_no"),
        ("bf_spec_regst_no", "pre_spec_no"),
    ):
        value = raw.get(raw_key)
        if is_blank(value) or not is_blank(payload.get(stored_key)):
            continue
        payload[stored_key] = str(value).strip()
    return payload if had_lifecycle or payload else None


def _mapping_value(value: Any) -> dict[str, Any]:
    """Expose only mapping-shaped contract data for identity extraction."""

    if isinstance(value, BaseModel):
        dumped = value.model_dump(by_alias=True, exclude_unset=False)
        return dumped if isinstance(dumped, dict) else {}
    return value if isinstance(value, dict) else {}


def _first_nonblank(mapping_values: list[Any], keys: tuple[str, ...]) -> Any:
    for value in mapping_values:
        mapping = _mapping_value(value)
        for key in keys:
            candidate = mapping.get(key)
            if not is_blank(candidate):
                return candidate
    return None


def _notice_linkage_keys(
    notice: NoticeContract,
    raw: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Read official bid linkage fields without inventing normalized values.

    Current normalized artifacts put the pre-spec number in
    ``lifecycle.pre_spec_no``.  Newer producers may retain the measured API
    spellings at the top level or as lifecycle extras, so all of those known
    spellings are accepted at this boundary.  Unknown fields remain in the
    artifact warning path and are not interpreted here.
    """

    lifecycle = notice.lifecycle
    sources: list[Any] = [
        raw,
        getattr(notice, "model_extra", None),
        lifecycle,
        getattr(lifecycle, "model_extra", None),
    ]
    # A raw_source mapping is useful for direct callers that pass the source
    # record itself.  Normal artifacts use a safe relative path string and do
    # not add another source here.
    if isinstance(notice.raw_source, dict):
        sources.append(notice.raw_source)
    order_plan_no = _first_nonblank(
        sources,
        ("orderPlanUntyNo", "order_plan_unty_no", "order_plan_no"),
    )
    pre_spec_no = _first_nonblank(
        sources,
        ("bfSpecRgstNo", "bf_spec_regst_no", "pre_spec_no"),
    )
    return (
        str(order_plan_no).strip() if not is_blank(order_plan_no) else None,
        str(pre_spec_no).strip() if not is_blank(pre_spec_no) else None,
    )


def _stored_pre_spec_number(notice: Notice) -> str | None:
    """Find a pre-spec external number already stored on a Notice."""

    lifecycle = notice.lifecycle_json if isinstance(notice.lifecycle_json, dict) else {}
    for key in ("pre_spec_no", "bfSpecRgstNo", "bf_spec_regst_no"):
        value = lifecycle.get(key)
        if not is_blank(value):
            return str(value).strip()
    if isinstance(notice.raw_source, dict):
        for key in ("bfSpecRgstNo", "bf_spec_regst_no", "pre_spec_no"):
            value = notice.raw_source.get(key)
            if not is_blank(value):
                return str(value).strip()
    if notice.source_type in {"pre_spec", "prespec", "pre-spec"}:
        # ``skills/bidops-collect`` emits ``pre:<bfSpecRgstNo>``.  Keep the
        # other historical spellings because the backend also ingests older
        # validation artifacts, but do not treat an arbitrary notice key as a
        # pre-spec number unless it is a pre-spec source row.
        return _pre_spec_number_from_key(str(notice.notice_key))
    return None


def _pre_spec_number_from_key(key: str) -> str | None:
    """Read a pre-spec number from a pre-spec row's own notice key."""

    for prefix in _PRE_SPEC_KEY_PREFIXES:
        if key.startswith(prefix) and not is_blank(key[len(prefix):]):
            return key[len(prefix):]
    if ":" not in key:
        return key
    return None


def _pre_spec_notice_keys(pre_spec_no: str) -> tuple[str, ...]:
    """Every notice-key spelling a pre-spec with this number may be stored as."""

    return tuple(
        dict.fromkeys((pre_spec_no, *(f"{prefix}{pre_spec_no}" for prefix in _PRE_SPEC_KEY_PREFIXES)))
    )


def _find_pre_spec_notice(session: Session, pre_spec_no: str) -> Notice | None:
    """Resolve a pre-spec Notice by the external registration number."""

    source_types = ("pre_spec", "prespec", "pre-spec")
    keys = _pre_spec_notice_keys(pre_spec_no)
    direct = session.scalar(
        select(Notice).where(
            Notice.source_type.in_(source_types),
            Notice.notice_key.in_(keys),
        )
    )
    if direct is not None:
        return direct
    for candidate in session.scalars(
        select(Notice).where(Notice.source_type.in_(source_types))
    ):
        if _stored_pre_spec_number(candidate) == pre_spec_no:
            return candidate
    return None


def _unindexed_record(record_kind: str, record_key: Any) -> ColumnElement[bool]:
    """SQL predicate: no collection-index row describes this stored record.

    Records loaded before the collection index existed (or through the
    validation path) have no index rows; their stored reference lists are the
    only source of their tokens.
    """

    return ~(
        select(CollectedRecordIndex.id)
        .where(
            CollectedRecordIndex.record_kind == record_kind,
            CollectedRecordIndex.record_key == record_key,
        )
        .exists()
    )


def _plans_claiming_bid_reference(
    session: Session,
    bid_no: str,
    bid_reference: str,
) -> set[str]:
    """Order-plan numbers whose ``bidNtceNoList`` contains the exact token.

    Indexed plans are found through ``collected_record_token``.  A stored plan
    without index rows is narrowed in SQL by a substring of the bid number
    and then compared token by token; plans are never scanned in Python.
    """

    numbers = set(
        session.scalars(
            select(CollectedRecordIndex.record_key)
            .join(
                CollectedRecordToken,
                CollectedRecordToken.index_id == CollectedRecordIndex.id,
            )
            .where(
                CollectedRecordIndex.record_kind == "order_plan",
                CollectedRecordToken.token == bid_reference,
            )
            .distinct()
        )
    )
    for plan_no, stored in session.execute(
        select(OrderPlan.order_plan_unty_no, OrderPlan.bid_ntice_no_list).where(
            OrderPlan.bid_ntice_no_list.contains(bid_no, autoescape=True),
            _unindexed_record("order_plan", OrderPlan.order_plan_unty_no),
        )
    ):
        if bid_reference in split_tokens(stored)[0]:
            numbers.add(plan_no)
    return numbers


def _find_order_plan_by_bid_reference(
    session: Session,
    notice: Notice,
    run_id: str | None = None,
) -> OrderPlan | None:
    """Resolve one plan from the measured 16-character bid reference list.

    ``bidNtceNoList`` is the plan-side official key: each comma-separated
    value is the 13-character bid number followed by its three-character
    order.  This is an exact token comparison, not a substring search.  If
    more than one plan claims the same token, no plan is selected because an
    ambiguous official reference is not safe to auto-confirm.
    """

    if is_blank(notice.bid_no) or is_blank(notice.bid_ord):
        return None
    bid_no = str(notice.bid_no)
    bid_reference = f"{bid_no}{notice.bid_ord}"
    numbers = _plans_claiming_bid_reference(session, bid_no, bid_reference)
    if len(numbers) > 1:
        if run_id is not None:
            _record_linkage_warning(
                session,
                run_id,
                notice=notice,
                target_type="order_plan",
                external_key=bid_reference,
                code="opportunity_link_reference_ambiguous",
                reason="ambiguous",
            )
        return None
    if not numbers:
        return None
    (number,) = numbers
    return session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == number))


def _pre_specs_claiming_bid_no(session: Session, bid_no: str) -> dict[str, Notice | None]:
    """Pre-spec numbers whose ``bidNtceNoList`` names ``bid_no`` exactly.

    A pre-spec token is the 13-character bid number alone.  Index tokens cover
    collected pre-specs, including ones not loaded into the database (mapped
    to ``None``); a stored pre-spec without index rows is narrowed in SQL by
    its serialized lifecycle text and then compared token by token.
    """

    claims: dict[str, Notice | None] = {}
    for record_key, number in session.execute(
        select(CollectedRecordIndex.record_key, CollectedRecordIndex.bf_spec_rgst_no)
        .join(
            CollectedRecordToken,
            CollectedRecordToken.index_id == CollectedRecordIndex.id,
        )
        .where(
            CollectedRecordIndex.record_kind == "pre_spec",
            CollectedRecordToken.token == bid_no,
        )
        .distinct()
    ):
        identity = number or _pre_spec_number_from_key(record_key) or record_key
        if claims.get(identity) is None:
            claims[identity] = session.scalar(
                select(Notice).where(
                    Notice.source_type.in_(tuple(sorted(_PRE_SPEC_SOURCE_TYPES))),
                    Notice.notice_key.in_(
                        tuple({record_key, *_pre_spec_notice_keys(identity)})
                    ),
                )
            )
    for stored in session.scalars(
        select(Notice).where(
            Notice.source_type.in_(tuple(sorted(_PRE_SPEC_SOURCE_TYPES))),
            cast(Notice.lifecycle_json, String).contains(bid_no, autoescape=True),
            _unindexed_record("pre_spec", Notice.notice_key),
        )
    ):
        lifecycle = stored.lifecycle_json if isinstance(stored.lifecycle_json, dict) else {}
        if bid_no in split_tokens(lifecycle.get("bid_ntice_no_list"))[0]:
            identity = _stored_pre_spec_number(stored) or stored.notice_key
            claims[identity] = stored
    return claims


def _find_pre_spec_by_bid_token(
    session: Session,
    run_id: str | None,
    notice: Notice,
) -> tuple[Notice, str] | None:
    """Resolve the one stored pre-spec whose token list names this bid number."""

    if is_blank(notice.bid_no):
        return None
    bid_no = str(notice.bid_no)
    claims = _pre_specs_claiming_bid_no(session, bid_no)
    if len(claims) > 1:
        if run_id is not None:
            _record_linkage_warning(
                session,
                run_id,
                notice=notice,
                target_type="pre_spec",
                external_key=bid_no,
                code="opportunity_link_reference_ambiguous",
                reason="ambiguous",
            )
        return None
    if not claims:
        return None
    ((number, pre_spec),) = claims.items()
    return (pre_spec, number) if pre_spec is not None else None


def _record_linkage_warning(
    session: Session,
    run_id: str,
    *,
    notice: Notice,
    target_type: str,
    external_key: str,
    code: str,
    reason: str,
) -> None:
    """Record a safe, non-PII unresolved official-link fact."""

    _record_warning(
        session,
        run_id,
        "warning",
        code,
        f"공식 생애주기 연결 대상을 확인하지 못했습니다: {target_type}",
        {
            "notice_id": notice.notice_key,
            "target_type": target_type,
            "external_key": external_key,
            "resolution": reason,
            "requires_human_review": True,
        },
    )


def _target_opportunities(
    session: Session,
    *,
    order_plan: OrderPlan | None = None,
    notice: Notice | None = None,
    additional_notices: tuple[Notice, ...] = (),
) -> list[Opportunity]:
    links: list[OpportunityLink] = []
    if order_plan is not None:
        links.extend(
            session.scalars(
                select(OpportunityLink)
                .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
                .where(
                    OpportunityLink.order_plan_id == order_plan.id,
                    authoritative_link_predicate(OpportunityLink),
                    active_opportunity_predicate(Opportunity),
                )
            ).all()
        )
    for notice_target in tuple(
        item for item in (notice, *additional_notices) if item is not None
    ):
        links.extend(
            session.scalars(
                select(OpportunityLink)
                .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
                .where(
                    OpportunityLink.notice_id == notice_target.id,
                    authoritative_link_predicate(OpportunityLink),
                    active_opportunity_predicate(Opportunity),
                )
            ).all()
        )
    unique: dict[int, Opportunity] = {}
    for link in links:
        if link.opportunity is not None:
            unique[link.opportunity.id] = link.opportunity
    return list(unique.values())


def _record_owner_link(
    session: Session,
    record: Notice | OrderPlan,
) -> OpportunityLink | None:
    """The authoritative link that makes an active opportunity own ``record``."""

    if record.id is None:
        session.flush()
    statement = (
        select(OpportunityLink)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
        )
        .order_by(OpportunityLink.id)
        .limit(1)
    )
    if isinstance(record, OrderPlan):
        statement = statement.where(OpportunityLink.order_plan_id == record.id)
    else:
        statement = statement.where(OpportunityLink.notice_id == record.id)
    return session.scalar(statement)


@dataclass
class _Arrival:
    """One lifecycle record being linked, and the merges refused on the way.

    Every automatic merge while linking the record uses the spec §3.2 rule.
    A refusal (two or more opportunities with human state) is collected here
    instead of rolling anything back; :func:`_finish_arrival` turns it into
    ``merge_confirmation`` candidates once the record has its final owner.
    """

    record: Notice | OrderPlan
    own_stage: str
    previous_owner_id: int | None
    held_ids: set[int] = field(default_factory=set)

    @property
    def refused(self) -> bool:
        return bool(self.held_ids)


def _begin_arrival(
    session: Session,
    record: Notice | OrderPlan,
    *,
    own_stage: str,
) -> _Arrival:
    owner = _record_owner_link(session, record)
    return _Arrival(
        record=record,
        own_stage=own_stage,
        previous_owner_id=owner.opportunity_id if owner is not None else None,
    )


def _merge_for_arrival(
    session: Session,
    opportunities: Iterable[Opportunity],
    arrival: _Arrival,
) -> Opportunity | None:
    """Merge by the shared rule; a refusal is recorded and returns ``None``."""

    outcome = apply_merge_rule(
        session,
        list(opportunities),
        reason=MERGE_REASON_OFFICIAL_LINK,
    )
    if outcome.refused:
        arrival.held_ids.update(int(item.id) for item in outcome.held)
        return None
    return outcome.primary


def _active_root(session: Session, opportunity_id: int) -> Opportunity | None:
    current = session.get(Opportunity, opportunity_id)
    seen: set[int] = set()
    while current is not None and current.merged_into_opportunity_id is not None:
        if current.id in seen:  # pragma: no cover - the CHECK forbids self merge.
            return None
        seen.add(current.id)
        current = session.get(Opportunity, current.merged_into_opportunity_id)
    return current


def _ensure_merge_confirmation_candidate(
    session: Session,
    opportunity: Opportunity,
    record: Notice | OrderPlan,
) -> bool:
    """Ask a person whether ``opportunity`` and the record's owner are one business.

    A pending or rejected candidate with the same owner and target already
    carries that question or its answer, so none is added.
    """

    is_plan = isinstance(record, OrderPlan)
    target_column = OpportunityLink.order_plan_id if is_plan else OpportunityLink.notice_id
    existing = session.scalar(
        select(OpportunityLink.id)
        .where(
            OpportunityLink.opportunity_id == opportunity.id,
            OpportunityLink.link_type == "candidate",
            target_column == record.id,
            or_(
                OpportunityLink.status == "후보 확인 대기",
                OpportunityLink.human_decision == "rejected",
            ),
        )
        .limit(1)
    )
    if existing is not None:
        return False
    session.add(
        OpportunityLink(
            opportunity_id=opportunity.id,
            order_plan_id=record.id if is_plan else None,
            notice_id=None if is_plan else record.id,
            stage="order_plan" if is_plan else "notice",
            link_type="candidate",
            status="후보 확인 대기",
            search_strategy=MERGE_CONFIRMATION_STRATEGY,
        )
    )
    session.flush()
    return True


def _finish_arrival(
    session: Session,
    arrival: _Arrival,
    *,
    run_id: str | None,
) -> None:
    """Resolve refused merges and the recheck signal for one linked record.

    - A refused merge leaves the record on its own opportunity.  Every other
      opportunity with human state gets a ``merge_confirmation`` candidate
      targeting the record, and one warning is recorded for the arrival.
    - When automatic linking or merging moved the record into an opportunity
      that did not own it before, that opportunity's recheck signal is raised
      with the record's official link (spec §3.2, §6.1).
    """

    owner_link = _record_owner_link(session, arrival.record)
    if owner_link is None:  # pragma: no cover - every linking path assigns one owner.
        raise RuntimeError("lifecycle record has no owning opportunity")
    owner = owner_link.opportunity
    if arrival.refused:
        held: dict[int, Opportunity] = {}
        for opportunity_id in sorted(arrival.held_ids):
            root = _active_root(session, opportunity_id)
            if root is not None and root.id != owner.id:
                held[root.id] = root
        created = sum(
            _ensure_merge_confirmation_candidate(session, opportunity, arrival.record)
            for opportunity in held.values()
        )
        if run_id is not None:
            identity = (
                {"order_plan_no": arrival.record.order_plan_unty_no}
                if isinstance(arrival.record, OrderPlan)
                else {"notice_id": arrival.record.notice_key}
            )
            _record_warning(
                session,
                run_id,
                "warning",
                "opportunity_merge_confirmation_required",
                "사람 추적 선택 또는 재검토 신호가 있는 사업기회가 둘 이상이라 자동 병합하지 않고 병합 확인 후보를 만들었습니다.",
                {
                    **identity,
                    "owner_opportunity_id": owner.id,
                    "held_opportunity_ids": sorted(arrival.held_ids),
                    "created_candidate_count": created,
                    "requires_human_review": True,
                },
            )
    if (
        owner.id != arrival.previous_owner_id
        and owner.tracking_status in RECHECK_SIGNAL_TRACKING_STATUSES
        and owner_link.link_type == "official"
        and owner_link.status == "확정"
    ):
        # The service is deliberately the only path that writes the system
        # recheck columns; it leaves human tracking fields alone.
        raise_recheck_signal(session, owner, owner_link)


def _waiting_official_links(
    session: Session,
    *,
    stage: str,
    evidence_external_no: str,
) -> list[OpportunityLink]:
    """Find targetless official links by their retained external reference.

    Target IDs are intentionally absent while an upstream record is outside
    the current collection window.  The external number is the only safe
    identity available at that point, so this lookup must not be narrowed by
    a target ID or by a title/name comparison.
    """

    return session.scalars(
        select(OpportunityLink).where(
            OpportunityLink.stage == stage,
            OpportunityLink.link_type == "official",
            OpportunityLink.status == "확정",
            OpportunityLink.evidence_external_no == evidence_external_no,
            OpportunityLink.order_plan_id.is_(None),
            OpportunityLink.notice_id.is_(None),
        )
    ).all()


def _attach_waiting_official_links(
    session: Session,
    *,
    arrival: _Arrival,
    stage: str,
    evidence_external_no: str,
    order_plan: OrderPlan | None = None,
    notice: Notice | None = None,
    evidence_bid_no: str | None = None,
) -> int:
    """Attach all deferred links for one exact official number to a target.

    If the arriving target already belongs to another opportunity, that
    opportunity and the waiting-link opportunities are merged here by the
    shared rule.  The merge is safe because this function is called only with
    the same official external number; it never uses name similarity.  Every
    link row is moved or updated in place, including rejected candidate links
    on the merged opportunities.  A refused merge leaves every row as it was
    and is resolved by the arrival.
    """

    if (order_plan is None) == (notice is None):
        raise ValueError("exactly one deferred-link target is required")
    waiting = _waiting_official_links(
        session,
        stage=stage,
        evidence_external_no=evidence_external_no,
    )
    if not waiting:
        return 0

    opportunities = {
        link.opportunity
        for link in waiting
        if link.opportunity is not None
    }
    opportunities.update(
        _target_opportunities(
            session,
            order_plan=order_plan,
            notice=notice,
        )
    )
    primary = _merge_for_arrival(session, opportunities, arrival)
    if primary is None:
        return 0

    # The target may already have one authoritative owner, or multiple
    # targetless official references may have converged here.  The partial
    # unique index allows exactly one targetful authoritative row.  Preserve
    # every redundant deferred row as history, but attach only the oldest one
    # when the target has no existing owner.
    target_owned = bool(
        _target_opportunities(session, order_plan=order_plan, notice=notice)
    )
    attachable = None if target_owned else min(waiting, key=lambda item: item.id)
    for link in waiting:
        link.opportunity = primary
        if evidence_bid_no is not None and link.evidence_bid_no is None:
            link.evidence_bid_no = evidence_bid_no
    if attachable is not None:
        if order_plan is not None:
            attachable.order_plan = order_plan
            attachable.notice = None
        else:
            attachable.notice = notice
            attachable.order_plan = None
    session.flush()
    return 1 if attachable is not None else 0


def resolve_order_plan_opportunity_links(
    session: Session,
    order_plan: OrderPlan,
    *,
    evidence_bid_no: str | None = None,
    run_id: str | None = None,
) -> int:
    """Resolve waiting bid references when an order plan is ingested later.

    The current cumulative order-plan importer can call this after its
    canonical ``OrderPlan`` row is flushed.  Keeping the operation as a
    loader helper also lets offline/import callers resolve a plan without
    re-ingesting the originating bid notice.  When there is no waiting bid,
    or the merge with it is refused, the plan itself is still registered as an
    ``order_plan`` opportunity so every lifecycle record has exactly one
    owning opportunity.  ``run_id`` receives the merge-confirmation warning.
    """

    if evidence_bid_no is None:
        evidence_bid_no = _first_order_plan_bid_no(order_plan.bid_ntice_no_list)
    # The target primary key is part of the exact target-opportunity lookup;
    # flush a newly-added plan before querying so ``id=None`` cannot broaden a
    # SQL ``IS NULL`` predicate to unrelated deferred links.
    if order_plan.id is None:
        session.flush()
    arrival = _begin_arrival(session, order_plan, own_stage="order_plan")
    attached = _attach_waiting_official_links(
        session,
        arrival=arrival,
        stage="order_plan",
        evidence_external_no=order_plan.order_plan_unty_no,
        order_plan=order_plan,
        evidence_bid_no=evidence_bid_no,
    )
    if not _target_opportunities(session, order_plan=order_plan):
        opportunity = _ensure_opportunity(
            session,
            arrival=arrival,
            first_registered_stage="order_plan",
            order_plan=order_plan,
        )
        _ensure_official_link(
            session,
            opportunity=opportunity,
            stage="order_plan",
            order_plan=order_plan,
            evidence_external_no=order_plan.order_plan_unty_no,
            evidence_bid_no=evidence_bid_no,
        )
    _finish_arrival(session, arrival, run_id=run_id)
    return attached


def _merge_opportunities(
    session: Session,
    opportunities: list[Opportunity],
) -> Opportunity | None:
    """Compatibility entry point for the shared non-destructive merge rule."""

    return merge_opportunities(
        session,
        opportunities,
        reason=MERGE_REASON_OFFICIAL_LINK,
    )


def _ensure_opportunity(
    session: Session,
    *,
    arrival: _Arrival,
    first_registered_stage: str,
    order_plan: OrderPlan | None = None,
    notice: Notice | None = None,
    additional_notices: tuple[Notice, ...] = (),
) -> Opportunity:
    """Return the one opportunity the arriving record should belong to.

    Opportunities owning any of the given records are merged by the shared
    rule.  When the rule refuses, the arriving record keeps its current owner,
    or gets a new opportunity registered at its own stage; the refusal is
    resolved by :func:`_finish_arrival`.
    """

    owners = _target_opportunities(
        session,
        order_plan=order_plan,
        notice=notice,
        additional_notices=additional_notices,
    )
    stage = first_registered_stage
    if owners:
        primary = _merge_for_arrival(session, owners, arrival)
        if primary is not None:
            return primary
        own = _record_owner_link(session, arrival.record)
        if own is not None:
            return own.opportunity
        stage = arrival.own_stage
    opportunity = Opportunity(first_registered_stage=stage)
    session.add(opportunity)
    session.flush()
    return opportunity


def _owned_by_another_opportunity(
    session: Session,
    opportunity: Opportunity,
    *,
    order_plan: OrderPlan | None,
    notice: Notice | None,
) -> bool:
    statement = (
        select(OpportunityLink.id)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.opportunity_id != opportunity.id,
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
        )
        .limit(1)
    )
    if order_plan is not None:
        statement = statement.where(OpportunityLink.order_plan_id == order_plan.id)
    elif notice is not None:
        statement = statement.where(OpportunityLink.notice_id == notice.id)
    else:
        return False
    return session.scalar(statement) is not None


def _ensure_official_link(
    session: Session,
    *,
    opportunity: Opportunity,
    stage: str,
    order_plan: OrderPlan | None = None,
    notice: Notice | None = None,
    evidence_external_no: str,
    evidence_bid_no: str | None = None,
) -> OpportunityLink | None:
    """Insert or resolve one official link while retaining its evidence.

    Passing neither target is intentional for a deferred upstream reference.
    In that case the exact external number identifies the waiting row; the
    later target-ingest path fills the target ID without creating a new
    opportunity.  A target that another active opportunity owns is left to
    its owner (a refused merge); ``None`` is returned and nothing is written.
    Recheck signals are raised by the arrival, not per link.
    """

    if order_plan is not None and notice is not None:
        raise ValueError("an official link cannot target both plan and notice")
    if not is_blank(evidence_external_no):
        evidence_external_no = str(evidence_external_no).strip()
    if _owned_by_another_opportunity(
        session, opportunity, order_plan=order_plan, notice=notice
    ):
        return None

    # A human-accepted candidate is already authoritative ownership.  If an
    # exact official reference later arrives for that same target, promote the
    # existing row in place so reviewer history survives without creating a
    # second authoritative target link.  The decision service recognizes an
    # exact replay against this promoted row.
    target_statement = select(OpportunityLink).where(
        OpportunityLink.opportunity_id == opportunity.id,
        authoritative_link_predicate(OpportunityLink),
    )
    if order_plan is not None:
        target_statement = target_statement.where(
            OpportunityLink.order_plan_id == order_plan.id,
            OpportunityLink.notice_id.is_(None),
        )
    elif notice is not None:
        target_statement = target_statement.where(
            OpportunityLink.notice_id == notice.id,
            OpportunityLink.order_plan_id.is_(None),
        )
    else:
        target_statement = None
    if target_statement is not None:
        authoritative = session.scalar(target_statement)
        if authoritative is not None:
            if authoritative.link_type == "candidate":
                authoritative.link_type = "official"
                authoritative.status = "확정"
            authoritative.evidence_external_no = evidence_external_no
            if evidence_bid_no is not None and authoritative.evidence_bid_no is None:
                authoritative.evidence_bid_no = evidence_bid_no
            session.flush()
            return authoritative

    statement = select(OpportunityLink).where(
        OpportunityLink.opportunity_id == opportunity.id,
        OpportunityLink.stage == stage,
        OpportunityLink.link_type == "official",
        OpportunityLink.evidence_external_no == evidence_external_no,
    )
    if order_plan is not None:
        statement = statement.where(
            OpportunityLink.order_plan_id == order_plan.id,
            OpportunityLink.notice_id.is_(None),
        )
    elif notice is not None:
        statement = statement.where(
            OpportunityLink.notice_id == notice.id,
            OpportunityLink.order_plan_id.is_(None),
        )
    else:
        statement = statement.where(
            OpportunityLink.order_plan_id.is_(None),
            OpportunityLink.notice_id.is_(None),
        )
    existing = session.scalar(statement)
    if existing is not None:
        # A pre-spec may have been ingested first and created its own official
        # membership link.  A later bid carrying bfSpecRgstNo adds the ADR-
        # 0025 provenance without creating a duplicate link.  The same update
        # also resolves a targetless official link when the target is already
        # known in this opportunity.
        if order_plan is not None:
            existing.order_plan = order_plan
            existing.notice = None
        elif notice is not None:
            existing.notice = notice
            existing.order_plan = None
        if evidence_bid_no is not None and existing.evidence_bid_no is None:
            existing.evidence_bid_no = evidence_bid_no
        session.flush()
        return existing
    link = OpportunityLink(
        opportunity_id=opportunity.id,
        order_plan_id=order_plan.id if order_plan is not None else None,
        notice_id=notice.id if notice is not None else None,
        stage=stage,
        link_type="official",
        status="확정",
        evidence_external_no=evidence_external_no,
        evidence_bid_no=evidence_bid_no,
    )
    session.add(link)
    session.flush()
    return link


def _other_bid_orders(session: Session, notice: Notice) -> tuple[Notice, ...]:
    """Stored notices with the same bid number and another order (spec §3.1)."""

    if is_blank(notice.bid_no):
        return ()
    return tuple(
        session.scalars(
            select(Notice)
            .where(Notice.bid_no == notice.bid_no, Notice.id != notice.id)
            .order_by(Notice.id)
        )
    )


def _link_bids_named_by_pre_spec(
    session: Session,
    run_id: str,
    pre_spec: Notice,
    own_number: str,
    arrival: _Arrival,
) -> None:
    """Join stored bids whose number this pre-spec's token list names.

    A pre-spec token is the 13-character bid number.  Only bids without their
    own ``bfSpecRgstNo`` are joined (that key would be the authoritative one),
    and a bid number claimed by another pre-spec as well stays unlinked with
    an ambiguity warning.  Each bid number is resolved by the shared rule.
    """

    lifecycle = pre_spec.lifecycle_json if isinstance(pre_spec.lifecycle_json, dict) else {}
    tokens = sorted(set(split_tokens(lifecycle.get("bid_ntice_no_list"))[0]))
    for bid_no in tokens:
        bids = tuple(
            bid
            for bid in session.scalars(
                select(Notice)
                .where(Notice.bid_no == bid_no, Notice.id != pre_spec.id)
                .order_by(Notice.id)
            )
            if _stored_pre_spec_number(bid) is None
        )
        if not bids:
            continue
        claimers = set(_pre_specs_claiming_bid_no(session, bid_no)) | {own_number}
        if len(claimers) > 1:
            _record_linkage_warning(
                session,
                run_id,
                notice=pre_spec,
                target_type="bid_notice",
                external_key=bid_no,
                code="opportunity_link_reference_ambiguous",
                reason="ambiguous",
            )
            continue
        primary = _merge_for_arrival(
            session,
            _target_opportunities(session, notice=pre_spec, additional_notices=bids),
            arrival,
        )
        if primary is None:
            continue
        _ensure_official_link(
            session,
            opportunity=primary,
            stage="notice",
            notice=pre_spec,
            evidence_external_no=own_number,
            evidence_bid_no=bid_no,
        )


def _ensure_official_opportunity_links(
    session: Session,
    run_id: str,
    notice: Notice,
    raw: dict[str, Any],
    notice_contract: NoticeContract | None = None,
) -> None:
    """Resolve official keys on one upserted notice into cumulative links.

    Name-search candidate creation deliberately does not live here.  This
    helper only consumes official references already present in the normalized
    notice and links records that are already in the database.  Every merge
    uses the shared rule (spec §3.2); a refused merge never leaves the notice
    without an owner.
    """

    contract = notice_contract
    if contract is None:
        contract = NoticeContract(
            notice_id=notice.notice_key,
            source_type=notice.source_type,
            lifecycle=notice.lifecycle_json,
            raw_source=notice.raw_source,
        )
    source_type = (notice.source_type or "").strip().lower()
    is_pre_spec = source_type in _PRE_SPEC_SOURCE_TYPES
    arrival = _begin_arrival(
        session, notice, own_stage="pre_spec" if is_pre_spec else "bid_notice"
    )
    order_plan_raw, pre_spec_no = _notice_linkage_keys(contract, raw)
    order_plan: OrderPlan | None = None
    order_plan_reference = order_plan_raw
    if order_plan_raw is not None:
        parsed_order_plan = parse_order_plan_unty_no(order_plan_raw)
        if parsed_order_plan is None:
            # Preserve even a nonstandard observed value in the deferred link;
            # parsing failure is a fact about the value, not permission to
            # discard the official reference.
            _record_linkage_warning(
                session,
                run_id,
                notice=notice,
                target_type="order_plan",
                external_key=order_plan_raw,
                code="opportunity_link_key_parse_failed",
                reason="parse_failed",
            )
        else:
            order_plan_reference = parsed_order_plan
            order_plan = session.scalar(
                select(OrderPlan).where(
                    OrderPlan.order_plan_unty_no == parsed_order_plan
                )
            )
            if order_plan is None:
                _record_linkage_warning(
                    session,
                    run_id,
                    notice=notice,
                    target_type="order_plan",
                    external_key=parsed_order_plan,
                    code="opportunity_link_target_missing",
                    reason="target_missing",
                )
    elif not is_blank(notice.bid_no) and not is_blank(notice.bid_ord):
        # The reverse official key is useful when a plan was collected before
        # the bid and the bid payload does not repeat orderPlanUntyNo.  Only
        # exact comma-delimited tokens are accepted; an ambiguous token stays
        # unresolved rather than creating a false automatic link.
        order_plan = _find_order_plan_by_bid_reference(session, notice, run_id)
        if order_plan is not None:
            order_plan_reference = order_plan.order_plan_unty_no

    pre_spec: Notice | None = None
    # The pre-spec number that names the pre-spec link: the bid's own
    # bfSpecRgstNo, or the pre-spec whose token list names this bid number.
    pre_spec_reference: str | None = pre_spec_no
    if pre_spec_no is not None:
        pre_spec = _find_pre_spec_notice(session, pre_spec_no)
        if pre_spec is None:
            _record_linkage_warning(
                session,
                run_id,
                notice=notice,
                target_type="pre_spec",
                external_key=pre_spec_no,
                code="opportunity_link_target_missing",
                reason="target_missing",
            )
    elif not is_pre_spec:
        found = _find_pre_spec_by_bid_token(session, run_id, notice)
        if found is not None:
            pre_spec, pre_spec_reference = found

    if is_pre_spec:
        # An independently collected pre-spec is a first registration point
        # when no earlier official relation is available.  Its own external
        # identity is an official record link, not a name-search candidate.
        own_pre_spec_no = _stored_pre_spec_number(notice) or notice.notice_key
        opportunity = _ensure_opportunity(
            session,
            arrival=arrival,
            first_registered_stage="pre_spec",
            notice=notice,
        )
        _ensure_official_link(
            session,
            opportunity=opportunity,
            stage="notice",
            notice=notice,
            evidence_external_no=own_pre_spec_no,
        )
        # A bid may have arrived before this pre-spec.  Resolve that exact
        # retained bfSpecRgstNo now, preserving the bid-first opportunity.
        _attach_waiting_official_links(
            session,
            arrival=arrival,
            stage="notice",
            evidence_external_no=own_pre_spec_no,
            notice=notice,
        )
        # A bid without bfSpecRgstNo may already be stored under a bid number
        # this pre-spec's token list names.
        _link_bids_named_by_pre_spec(session, run_id, notice, own_pre_spec_no, arrival)
        _finish_arrival(session, arrival, run_id=run_id)
        return

    # A target that arrived before this bid may itself have a deferred link.
    # Resolve that link by the same official number before collecting all
    # target opportunities for the current bid.
    if order_plan is not None:
        _attach_waiting_official_links(
            session,
            arrival=arrival,
            stage="order_plan",
            evidence_external_no=order_plan.order_plan_unty_no,
            order_plan=order_plan,
            evidence_bid_no=notice.bid_no,
        )
    if pre_spec is not None:
        _attach_waiting_official_links(
            session,
            arrival=arrival,
            stage="notice",
            evidence_external_no=pre_spec_reference or pre_spec.notice_key,
            notice=pre_spec,
            evidence_bid_no=notice.bid_no,
        )

    if order_plan is not None or pre_spec is not None:
        first_stage = "order_plan" if order_plan is not None else "pre_spec"
    else:
        # ADR-0028: a bid itself is an observable lifecycle registration even
        # when its upstream reference is absent, stale, or not yet collected.
        first_stage = "bid_notice"
    opportunity = _ensure_opportunity(
        session,
        arrival=arrival,
        first_registered_stage=first_stage,
        order_plan=order_plan,
        notice=pre_spec,
        # A bid may already have a candidate relation or an independently
        # created opportunity, and another order of the same bid number is the
        # same procurement (spec §3.1).  Only these exact notices join the
        # identity lookup; no title/name similarity is used for merging.
        additional_notices=(notice, *_other_bid_orders(session, notice)),
    )

    if order_plan is not None:
        _ensure_official_link(
            session,
            opportunity=opportunity,
            stage="order_plan",
            order_plan=order_plan,
            evidence_external_no=order_plan.order_plan_unty_no,
            evidence_bid_no=notice.bid_no,
        )
    elif order_plan_reference is not None:
        _ensure_official_link(
            session,
            opportunity=opportunity,
            stage="order_plan",
            evidence_external_no=order_plan_reference,
            evidence_bid_no=notice.bid_no,
        )

    if pre_spec is not None:
        _ensure_official_link(
            session,
            opportunity=opportunity,
            stage="notice",
            notice=pre_spec,
            evidence_external_no=pre_spec_reference or pre_spec.notice_key,
            evidence_bid_no=notice.bid_no,
        )
    elif pre_spec_no is not None:
        _ensure_official_link(
            session,
            opportunity=opportunity,
            stage="notice",
            evidence_external_no=pre_spec_no,
            evidence_bid_no=notice.bid_no,
        )

    # The bid notice itself must always be represented by one targetful link,
    # including the no-reference and all-targets-missing cases.  A reference
    # on that membership link is only evidence for the bid row; unresolved
    # upstream references remain separate targetless links above.
    bid_evidence = (
        order_plan_reference
        if order_plan is not None
        else pre_spec_no
        if pre_spec_no is not None
        else notice.notice_key
    )
    _ensure_official_link(
        session,
        opportunity=opportunity,
        stage="notice",
        notice=notice,
        evidence_external_no=bid_evidence,
        evidence_bid_no=notice.bid_no,
    )
    _finish_arrival(session, arrival, run_id=run_id)


def _demand_agency_value(notice: NoticeContract) -> str | None:
    value = notice.demand_agency
    if is_blank(value):
        return None
    return str(value).strip()


def _float_or_none(value: Any) -> float | None:
    if is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _upsert_notice(
    session: Session,
    run_id: str,
    notice: NoticeContract,
    raw: dict[str, Any],
    timezone_name: str,
) -> Notice | None:
    values = _notice_values(notice, raw, timezone_name, session, run_id)
    if values is None:
        return None
    notice_key = values.pop("notice_key")
    normalized_attachments = _normalized_attachment_payloads(
        notice,
        raw.get("attachments"),
    )
    snapshot, snapshot_sha256 = _observation_snapshot(
        NOTICE_OBSERVATION_SNAPSHOT_SCHEMA,
        "notice",
        {"notice_key": notice_key, **values},
        attachments=(
            [_attachment_snapshot_payload(item) for item in normalized_attachments]
            if normalized_attachments is not None
            else None
        ),
    )
    # ``demand_agency`` is a projection column only.  It stays out of the
    # observation snapshot: the C-1 screening input (screening-input.v1) keeps
    # its closed notice key set, so including the value would make the same
    # run's screening replay conflict with its collection ingest.  It is
    # written only when the artifact supplied the key, so an input that never
    # carried it cannot erase a value another artifact observed.
    demand_agency_supplied = "demand_agency" in notice.model_fields_set
    demand_agency = _demand_agency_value(notice) if demand_agency_supplied else None
    existing = session.scalar(
        select(Notice).where(Notice.notice_key == notice_key)
    )
    is_new = existing is None
    run = session.get(Run, run_id)
    if run is None:  # pragma: no cover - _upsert_run creates this boundary.
        raise ValueError(f"run not found while observing notice: {run_id}")
    if existing is not None:
        observation = session.scalar(
            select(NoticeObservation).where(
                NoticeObservation.notice_id == existing.id,
                NoticeObservation.run_id == run_id,
            )
        )
        if observation is not None and _check_existing_observation_snapshot(
            session,
            run_id=run_id,
            identity_kind="notice",
            identity=notice_key,
            observation=observation,
            schema_version=NOTICE_OBSERVATION_SNAPSHOT_SCHEMA,
            snapshot_jsonb=snapshot,
            source_sha256=snapshot_sha256,
        ):
            # A same-run replay is otherwise a no-op.  The one exception fills
            # a still-empty demand agency from the same observed record, e.g.
            # when the screening projection of this run was loaded first.
            if demand_agency is not None and existing.demand_agency is None:
                existing.demand_agency = demand_agency
            return existing
    if existing is None:
        existing = Notice(notice_key=notice_key)
        session.add(existing)
    changed_fields = [
        field_name
        for field_name, value in values.items()
        if not is_new and getattr(existing, field_name) != value
    ]
    for key, value in values.items():
        setattr(existing, key, value)
    if demand_agency_supplied:
        if not is_new and existing.demand_agency != demand_agency:
            changed_fields.append("demand_agency")
        existing.demand_agency = demand_agency
    _upsert_attachments(
        session,
        existing,
        raw.get("attachments"),
        observed_at=_ensure_aware(run.generated_at, timezone_name),
        normalized_attachments=normalized_attachments,
    )
    # Flush the canonical row before looking up its observation.  The same
    # external key is shared across runs; the observation, not a second Notice
    # row, records this run's sighting and field changes.
    session.flush()
    observation = session.scalar(
        select(NoticeObservation).where(
            NoticeObservation.notice_id == existing.id,
            NoticeObservation.run_id == run_id,
        )
    )
    if observation is None:
        session.add(
            NoticeObservation(
                notice_id=existing.id,
                run_id=run_id,
                observed_at=_ensure_aware(run.generated_at, timezone_name),
                changed_fields_json=sorted(changed_fields),
                snapshot_schema_version=NOTICE_OBSERVATION_SNAPSHOT_SCHEMA,
                snapshot_jsonb=snapshot,
                source_sha256=snapshot_sha256,
            )
        )
    else:  # pragma: no cover - the existing observation returned above.
        raise ObservationSnapshotConflictError(
            f"unexpected notice observation race: notice={notice_key}, run_id={run_id}"
        )
    # SessionFactory deliberately disables autoflush.  Flush the association
    # here so a malformed artifact containing the same notice key twice cannot
    # create two pending observation rows for the same notice/run pair.
    session.flush()
    # A merge refused by the shared rule never rolls these writes back: the
    # notice keeps (or gets) its own opportunity and people are asked through
    # merge-confirmation candidates (spec §3.2).
    _ensure_official_opportunity_links(
        session,
        run_id,
        existing,
        raw,
        notice,
    )
    return existing


_ORDER_PLAN_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "order_plan_unty_no": (
        "order_plan_unty_no", "plan_id", "orderPlanUntyNo", "order_plan_no",
    ),
    "title": ("title", "business_name", "biz_nm", "bizNm"),
    "agency_code": ("agency_code", "orderInsttCd"),
    "agency_name": ("agency_name", "orderInsttNm"),
    "supervising_agency_name": (
        "supervising_agency_name", "totlmngInsttNm",
    ),
    "business_division": ("business_division", "bsnsDivNm"),
    "business_division_code": ("business_division_code", "bsnsDivCd"),
    "service_type": ("service_type", "bsnsTyNm"),
    "service_type_code": ("service_type_code", "bsnsTyCd"),
    "budget_amount": ("budget_amount", "budget", "sumOrderAmt"),
    "contract_amount": ("contract_amount", "orderContrctAmt"),
    "planned_order_year": ("planned_order_year", "order_year", "orderYear"),
    "planned_order_month": ("planned_order_month", "order_month"),
    "procurement_method": ("procurement_method", "prcrmntMethd"),
    "contract_method": ("contract_method", "cntrctMthdNm"),
    "sw_business_status": ("sw_business_status", "swBizObjYn"),
    "published_at": ("published_at", "nticeDt"),
    "changed_at": ("changed_at", "chgDt"),
    "bid_ntice_no_list": ("bid_ntice_no_list", "bidNtceNoList"),
    # ``ntceNticeYn`` is the measured G2B spelling.  Keep the historical
    # ``nticeNticeYn`` typo as a read-only compatibility alias.
    "notice_posted": ("notice_posted", "ntceNticeYn", "nticeNticeYn"),
    "rcrit_rgst_no": ("rcrit_rgst_no", "rcritRgstNo"),
    "source_url": ("source_url", "official_url", "orderPlanDtlUrl"),
    "first_discovered_at": ("first_discovered_at",),
    "last_discovered_at": ("last_discovered_at",),
    "source_sha256": ("source_sha256",),
    "unknown_fields": ("unknown_fields",),
    "raw_source": ("raw_source", "raw_record"),
}
_ORDER_PLAN_KNOWN_KEYS = frozenset(
    key
    for aliases in _ORDER_PLAN_FIELD_ALIASES.values()
    for key in aliases
) | {"source", "raw_ref"}
_ORDER_PLAN_SOURCE_HASH_KEYS = ("source_sha256", "source_hash")
_ORDER_PLAN_UNPROJECTED_KEYS = (
    "sw_business_status", "swBizObjYn", "rcrit_rgst_no", "rcritRgstNo",
)


def _plan_first_value(raw: dict[str, Any], *keys: str) -> Any:
    """Return the first nonblank plan value, retaining explicit blank state."""

    for key in keys:
        if key in raw and not is_blank(raw[key]):
            return raw[key]
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def _plan_has_value(raw: dict[str, Any], *keys: str) -> bool:
    return any(key in raw for key in keys)


def _plan_text(raw: dict[str, Any], *keys: str) -> str | None:
    value = _plan_first_value(raw, *keys)
    if is_blank(value):
        return None
    return str(value).strip()


def _parse_order_plan_datetime(
    value: Any,
    timezone_name: str,
    *,
    field_name: str,
) -> datetime | None:
    """Parse normalized ISO values and the measured G2B compact timestamps."""

    if is_blank(value):
        return None
    try:
        return _parse_datetime(value, timezone_name, field_name=field_name)
    except ValueError:
        if isinstance(value, str):
            for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M"):
                try:
                    return _ensure_aware(
                        datetime.strptime(value.strip(), fmt), timezone_name
                    )
                except ValueError:
                    continue
        raise


def _order_plan_datetime(
    raw: dict[str, Any],
    aliases: tuple[str, ...],
    field_name: str,
    plan_no: str,
    timezone_name: str,
    session: Session,
    run_id: str,
    invalid_fields: set[str],
) -> datetime | None:
    value = _plan_first_value(raw, *aliases)
    if is_blank(value):
        return None
    try:
        return _parse_order_plan_datetime(
            value, timezone_name, field_name=field_name
        )
    except ValueError as exc:
        invalid_fields.add(field_name)
        _record_warning(
            session,
            run_id,
            "warning",
            "invalid_datetime",
            f"{field_name} 값을 날짜로 변환하지 못했습니다.",
            {"order_plan_no": plan_no, "field": field_name},
        )
        return None


def _order_plan_decimal(
    raw: dict[str, Any],
    aliases: tuple[str, ...],
    field_name: str,
    plan_no: str,
    session: Session,
    run_id: str,
    invalid_fields: set[str],
) -> Decimal | None:
    value = _plan_first_value(raw, *aliases)
    if is_blank(value):
        return None
    try:
        parsed = Decimal(str(value).replace(",", ""))
        if not parsed.is_finite():
            raise InvalidOperation
        return parsed
    except (InvalidOperation, ValueError):
        invalid_fields.add(field_name)
        _record_warning(
            session,
            run_id,
            "warning",
            "invalid_number",
            f"{field_name} 값을 숫자로 변환하지 못했습니다.",
            {"order_plan_no": plan_no, "field": field_name},
        )
        return None


def _safe_order_plan_source_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    path = Path(value)
    if path.is_absolute() or value.startswith("/"):
        return False
    parts = value.split("/")
    return bool(parts) and all(
        part not in {"", ".", ".."} and ":" not in part for part in parts
    )


def _order_plan_raw_source(raw: dict[str, Any]) -> Any:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    value = _plan_first_value(raw, "raw_source", "raw_record")
    if value is None and not is_blank(source.get("raw_ref")):
        value = source.get("raw_ref")
    if value is None and "raw_ref" in raw:
        value = raw.get("raw_ref")

    unprojected = {
        key: raw[key]
        for key in _ORDER_PLAN_UNPROJECTED_KEYS
        if key in raw
    }
    if not unprojected:
        return value
    if isinstance(value, dict):
        payload = dict(value)
    elif value is None:
        payload = {}
    else:
        payload = {"raw_ref": value}
    payload["unprojected_fields"] = unprojected
    return payload


def _safe_order_plan_raw_source(value: Any) -> bool:
    """Validate path-shaped plan provenance without rejecting raw JSON payloads."""

    if isinstance(value, str):
        return _safe_order_plan_source_ref(value)
    if isinstance(value, dict) and "raw_ref" in value:
        return _safe_order_plan_source_ref(value["raw_ref"])
    return True


def _order_plan_values(
    raw: dict[str, Any],
    timezone_name: str,
    session: Session,
    run_id: str,
) -> tuple[dict[str, Any] | None, set[str], set[str]]:
    plan_no = _plan_text(raw, *_ORDER_PLAN_FIELD_ALIASES["order_plan_unty_no"])
    if plan_no is None:
        _record_warning(
            session,
            run_id,
            "error",
            "order_plan_id_missing",
            "공식 발주계획번호가 없어 해당 발주계획을 적재하지 않았습니다.",
            {"field": "order_plan_unty_no"},
        )
        return None, set(), set()

    invalid_fields: set[str] = set()
    provided_fields = {
        "unknown_fields_json" if field_name == "unknown_fields" else field_name
        for field_name, aliases in _ORDER_PLAN_FIELD_ALIASES.items()
        if _plan_has_value(raw, *aliases)
    }

    planned_year = _plan_text(
        raw, *_ORDER_PLAN_FIELD_ALIASES["planned_order_year"]
    )
    if planned_year is not None and (
        len(planned_year) != 4 or not planned_year.isdigit()
    ):
        invalid_fields.add("planned_order_year")
        _record_warning(
            session,
            run_id,
            "warning",
            "invalid_order_plan_date",
            "planned_order_year 값을 해석하지 못했습니다.",
            {"order_plan_no": plan_no, "field": "planned_order_year"},
        )
        planned_year = None

    direct_month = _plan_text(
        raw, *_ORDER_PLAN_FIELD_ALIASES["planned_order_month"]
    )
    planned_month = direct_month
    if planned_month is None:
        raw_month = _plan_text(raw, "orderMnth")
        if planned_year is not None and raw_month is not None:
            candidate = f"{planned_year}-{raw_month.zfill(2)}"
            if re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", candidate):
                planned_month = candidate
            else:
                invalid_fields.add("planned_order_month")
        if _plan_has_value(raw, "orderMnth"):
            provided_fields.add("planned_order_month")
    elif not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", planned_month):
        invalid_fields.add("planned_order_month")
        _record_warning(
            session,
            run_id,
            "warning",
            "invalid_order_plan_date",
            "planned_order_month 값을 해석하지 못했습니다.",
            {"order_plan_no": plan_no, "field": "planned_order_month"},
        )
        planned_month = None

    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    source_hash_value = _plan_first_value(
        raw, *_ORDER_PLAN_FIELD_ALIASES["source_sha256"]
    )
    if is_blank(source_hash_value):
        source_hash_value = _plan_first_value(source, *_ORDER_PLAN_SOURCE_HASH_KEYS)
        if not is_blank(source_hash_value):
            provided_fields.add("source_sha256")
    if is_blank(source_hash_value):
        source_hash = None
        _record_warning(
            session,
            run_id,
            "warning",
            "order_plan_source_hash_missing",
            "발주계획 원문 source hash가 없어 확인이 필요합니다.",
            {"order_plan_no": plan_no, "field": "source_sha256"},
        )
    elif not isinstance(source_hash_value, str) or SHA256_RE.fullmatch(source_hash_value) is None:
        source_hash = None
        invalid_fields.add("source_sha256")
        _record_warning(
            session,
            run_id,
            "warning",
            "invalid_source_hash",
            "발주계획 source hash가 lowercase SHA-256 형식이 아닙니다.",
            {"order_plan_no": plan_no, "field": "source_sha256"},
        )
    else:
        source_hash = source_hash_value

    unknown_value = raw.get("unknown_fields")
    if unknown_value is not None and not isinstance(unknown_value, list):
        invalid_fields.add("unknown_fields_json")
        _record_warning(
            session,
            run_id,
            "warning",
            "order_plan_unknown_fields_invalid",
            "발주계획 unknown_fields가 배열이 아니어서 보존하지 못했습니다.",
            {"order_plan_no": plan_no, "field": "unknown_fields"},
        )
        unknown_value = None

    raw_source = _order_plan_raw_source(raw)
    if not _safe_order_plan_raw_source(raw_source):
        invalid_fields.add("raw_source")
        _record_warning(
            session,
            run_id,
            "warning",
            "order_plan_raw_source_unsafe",
            "발주계획 raw_source가 안전한 상대 경로가 아니어서 저장하지 않았습니다.",
            {"order_plan_no": plan_no, "field": "raw_source"},
        )
        raw_source = None

    values = {
        "order_plan_unty_no": plan_no,
        "title": _plan_text(raw, *_ORDER_PLAN_FIELD_ALIASES["title"]),
        "agency_code": _plan_text(raw, *_ORDER_PLAN_FIELD_ALIASES["agency_code"]),
        "agency_name": _plan_text(raw, *_ORDER_PLAN_FIELD_ALIASES["agency_name"]),
        "supervising_agency_name": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["supervising_agency_name"]
        ),
        "business_division": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["business_division"]
        ),
        "business_division_code": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["business_division_code"]
        ),
        "service_type": _plan_text(raw, *_ORDER_PLAN_FIELD_ALIASES["service_type"]),
        "service_type_code": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["service_type_code"]
        ),
        "budget_amount": _order_plan_decimal(
            raw,
            _ORDER_PLAN_FIELD_ALIASES["budget_amount"],
            "budget_amount",
            plan_no,
            session,
            run_id,
            invalid_fields,
        ),
        "contract_amount": _order_plan_decimal(
            raw,
            _ORDER_PLAN_FIELD_ALIASES["contract_amount"],
            "contract_amount",
            plan_no,
            session,
            run_id,
            invalid_fields,
        ),
        "planned_order_year": planned_year,
        "planned_order_month": planned_month,
        "procurement_method": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["procurement_method"]
        ),
        "contract_method": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["contract_method"]
        ),
        "published_at": _order_plan_datetime(
            raw,
            _ORDER_PLAN_FIELD_ALIASES["published_at"],
            "published_at",
            plan_no,
            timezone_name,
            session,
            run_id,
            invalid_fields,
        ),
        "changed_at": _order_plan_datetime(
            raw,
            _ORDER_PLAN_FIELD_ALIASES["changed_at"],
            "changed_at",
            plan_no,
            timezone_name,
            session,
            run_id,
            invalid_fields,
        ),
        "bid_ntice_no_list": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["bid_ntice_no_list"]
        ),
        "notice_posted": _plan_text(
            raw, *_ORDER_PLAN_FIELD_ALIASES["notice_posted"]
        ),
        "source_url": _plan_text(raw, *_ORDER_PLAN_FIELD_ALIASES["source_url"]),
        "first_discovered_at": _order_plan_datetime(
            raw,
            _ORDER_PLAN_FIELD_ALIASES["first_discovered_at"],
            "first_discovered_at",
            plan_no,
            timezone_name,
            session,
            run_id,
            invalid_fields,
        ),
        "last_discovered_at": _order_plan_datetime(
            raw,
            _ORDER_PLAN_FIELD_ALIASES["last_discovered_at"],
            "last_discovered_at",
            plan_no,
            timezone_name,
            session,
            run_id,
            invalid_fields,
        ),
        "source_sha256": source_hash,
        "unknown_fields_json": _json_value(unknown_value),
        "raw_source": raw_source,
    }
    # ``source.source_sha256`` and a source raw_ref are contract fields even
    # though their values are nested in the compatibility population shape.
    if not _plan_has_value(raw, "raw_source", "raw_record") and not is_blank(source.get("raw_ref")):
        provided_fields.add("raw_source")
    if not _plan_has_value(raw, "unknown_fields"):
        provided_fields.discard("unknown_fields_json")
    return values, provided_fields, invalid_fields


def _upsert_order_plan(
    session: Session,
    run_id: str,
    raw: dict[str, Any],
    timezone_name: str,
) -> OrderPlan | None:
    """Upsert one plan, append its observation, then resolve deferred links."""

    values, provided_fields, invalid_fields = _order_plan_values(
        raw, timezone_name, session, run_id
    )
    if values is None:
        return None
    plan_no = values["order_plan_unty_no"]
    snapshot, snapshot_sha256 = _observation_snapshot(
        ORDER_PLAN_OBSERVATION_SNAPSHOT_SCHEMA,
        "order_plan",
        values,
    )
    existing = session.scalar(
        select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no)
    )
    is_new = existing is None
    run = session.get(Run, run_id)
    if run is None:  # pragma: no cover - _upsert_run creates this boundary.
        raise ValueError(f"run not found while observing order plan: {run_id}")
    if existing is not None:
        observation = session.scalar(
            select(OrderPlanObservation).where(
                OrderPlanObservation.order_plan_id == existing.id,
                OrderPlanObservation.run_id == run_id,
            )
        )
        if observation is not None and _check_existing_observation_snapshot(
            session,
            run_id=run_id,
            identity_kind="order_plan",
            identity=plan_no,
            observation=observation,
            schema_version=ORDER_PLAN_OBSERVATION_SNAPSHOT_SCHEMA,
            snapshot_jsonb=snapshot,
            source_sha256=snapshot_sha256,
        ):
            return existing
    if existing is None:
        existing = OrderPlan(order_plan_unty_no=plan_no)
        session.add(existing)

    updates: dict[str, Any] = {}
    for field_name, value in values.items():
        if field_name == "order_plan_unty_no":
            continue
        if is_new or (
            field_name in provided_fields
            and field_name not in invalid_fields
            and value is not None
        ):
            updates[field_name] = value

    if not is_new:
        # Discovery bounds are cumulative facts.  A partial or blank later
        # artifact must not erase a previously observed bound.
        incoming_first = updates.get("first_discovered_at")
        if incoming_first is not None:
            current_first = existing.first_discovered_at
            updates["first_discovered_at"] = (
                incoming_first
                if current_first is None
                else min(current_first, incoming_first)
            )
        incoming_last = updates.get("last_discovered_at")
        if incoming_last is not None:
            current_last = existing.last_discovered_at
            updates["last_discovered_at"] = (
                incoming_last
                if current_last is None
                else max(current_last, incoming_last)
            )

    changed_fields = [
        field_name
        for field_name, value in updates.items()
        if not is_new and getattr(existing, field_name) != value
    ]
    for field_name, value in updates.items():
        setattr(existing, field_name, value)

    # The canonical row must exist before either observation or relationship
    # lookup.  This is the T-13 boundary: the resolver below is the production
    # call that turns a bid-first waiting link into a targetful plan link.
    session.flush()
    observation = session.scalar(
        select(OrderPlanObservation).where(
            OrderPlanObservation.order_plan_id == existing.id,
            OrderPlanObservation.run_id == run_id,
        )
    )
    if observation is None:
        session.add(
            OrderPlanObservation(
                order_plan_id=existing.id,
                run_id=run_id,
                observed_at=_ensure_aware(run.generated_at, timezone_name),
                changed_fields_json=sorted(changed_fields),
                snapshot_schema_version=ORDER_PLAN_OBSERVATION_SNAPSHOT_SCHEMA,
                snapshot_jsonb=snapshot,
                source_sha256=snapshot_sha256,
            )
        )
    else:  # pragma: no cover - the existing observation returned above.
        raise ObservationSnapshotConflictError(
            f"unexpected order-plan observation race: plan={plan_no}, run_id={run_id}"
        )
    session.flush()
    resolve_order_plan_opportunity_links(
        session,
        existing,
        evidence_bid_no=_first_order_plan_bid_no(existing.bid_ntice_no_list),
        run_id=run_id,
    )
    return existing


def _normalized_attachment_payloads(
    notice: NoticeContract,
    raw_attachments: Any,
) -> list[dict[str, Any]] | None:
    """Normalize a collector attachment list without trusting provenance hints.

    The current producer contract is the immutable ``{name, url}`` pair.  A
    provider identity is derived only from the measured pre-spec G2B URL; raw
    provenance hints are accepted solely when they exactly match that URL.
    """

    if not isinstance(raw_attachments, list):
        return None
    normalized: list[dict[str, Any]] = []
    by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    source_type = (notice.source_type or "").strip().lower()
    is_pre_spec = source_type in {"pre_spec", "prespec", "pre-spec"}
    for raw in raw_attachments:
        if not isinstance(raw, dict):
            continue
        source_url = raw.get("source_url", raw.get("url"))
        measured_key = parse_attachment_key(source_url) if is_pre_spec else None
        source_system = "g2b" if measured_key is not None else None
        source_attachment_key = measured_key
        hinted_system = raw.get("source_system")
        hinted_key = raw.get("source_attachment_key")
        if hinted_system is not None or hinted_key is not None:
            if (
                hinted_system != "g2b"
                or not isinstance(hinted_key, str)
                or not hinted_key
                or measured_key != hinted_key
            ):
                raise ObservationSnapshotConflictError(
                    "attachment provenance conflicts with the measured G2B URL"
                )
            # Explicit normalized provenance is the primary identity, but it
            # is accepted only after the source URL independently proves the
            # same measured provider key.
            source_system = hinted_system
            source_attachment_key = hinted_key
        item = {
            "name": raw.get("name"),
            "source_url": source_url,
            "origin": raw.get("origin") or "g2b",
            "file_ext": raw.get("file_ext"),
            "size_bytes": raw.get("size_bytes"),
            "legacy_stored_path": raw.get("stored_path", raw.get("legacy_stored_path")),
            "extract_status": raw.get("extract_status"),
            "source_system": source_system,
            "source_attachment_key": source_attachment_key,
        }
        identity = (
            ("provider", source_system, source_attachment_key)
            if source_attachment_key is not None
            else ("legacy", item["name"], item["source_url"])
        )
        previous = by_identity.get(identity)
        if previous is not None:
            if previous != item:
                raise ObservationSnapshotConflictError(
                    "duplicate attachment identity has conflicting metadata"
                )
            continue
        by_identity[identity] = item
        normalized.append(item)
    return normalized


def _attachment_snapshot_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Exclude the legacy local path from the immutable observation payload."""

    return {
        key: value
        for key, value in item.items()
        if key != "legacy_stored_path"
    }


def _max_observed_at(current: datetime | None, observed_at: datetime) -> datetime:
    if current is None:
        return observed_at
    return max(current, observed_at)


def _upsert_attachments(
    session: Session,
    notice: Notice,
    raw_attachments: Any,
    *,
    observed_at: datetime | None = None,
    normalized_attachments: list[dict[str, Any]] | None = None,
) -> None:
    normalized = (
        normalized_attachments
        if normalized_attachments is not None
        else _normalized_attachment_payloads(
            NoticeContract(notice_id=notice.notice_key, source_type=notice.source_type),
            raw_attachments,
        )
    )
    if normalized is None:
        return
    observed = observed_at or datetime.now(timezone.utc)
    existing_provider = {
        (item.source_system, item.source_attachment_key): item
        for item in notice.attachments
        if item.source_system is not None and item.source_attachment_key is not None
    }
    existing_legacy = {
        (item.name, item.source_url): item
        for item in notice.attachments
        if item.origin == "g2b" or item.source_system is not None
    }
    seen_object_ids: set[int] = set()
    for raw in normalized:
        provider_identity = (raw["source_system"], raw["source_attachment_key"])
        item = (
            existing_provider.get(provider_identity)
            if raw["source_attachment_key"] is not None
            else None
        )
        if item is None:
            item = existing_legacy.get((raw["name"], raw["source_url"]))
        if item is None:
            item = Attachment(notice=notice, origin="g2b")
            session.add(item)
        item.name = raw["name"]
        item.source_url = raw["source_url"]
        item.origin = raw["origin"] or item.origin or "g2b"
        item.file_ext = raw["file_ext"]
        item.size_bytes = raw["size_bytes"]
        item.legacy_stored_path = raw["legacy_stored_path"]
        item.extract_status = raw["extract_status"]
        item.source_system = raw["source_system"]
        item.source_attachment_key = raw["source_attachment_key"]
        item.last_seen_at = _max_observed_at(item.last_seen_at, observed)
        if item.retired_at is None or observed >= item.retired_at:
            item.retired_at = None
            item.retired_reason = None
            item.retired_by_name = None
        seen_object_ids.add(id(item))

    for item in notice.attachments:
        if id(item) in seen_object_ids:
            continue
        managed_by_collection = item.origin == "g2b" or item.source_system is not None
        if not managed_by_collection:
            continue
        if item.last_seen_at is not None and observed < item.last_seen_at:
            continue
        if item.retired_at is None:
            item.retired_at = observed
            item.retired_reason = "not_seen_in_source"
            item.retired_by_name = None


def _artifact_unknown_fields(raw: dict[str, Any], model: BaseModel) -> list[str]:
    # The model traversal catches top-level and typed nested extras.  The raw
    # pass retains aliases and makes the top-level behavior explicit.
    return sorted(
        set(model_extra_fields(model))
        | {key for key in raw if key not in type(model).model_fields}
    )


def _upsert_run(
    session: Session,
    run_id: str,
    run_directory: Path,
    window_from: date | None,
    window_to: date | None,
    timezone_name: str,
    generated_at: datetime,
    screening_basis: str | None,
) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        run = Run(
            id=run_id,
            window_from=window_from,
            window_to=window_to,
            timezone=timezone_name,
            generated_at=_ensure_aware(generated_at, timezone_name),
            screening_basis=screening_basis,
            status="active",
        )
        session.add(run)
        session.flush()
        prefix = f"{run_directory.name}--"
        previous_runs = session.scalars(select(Run)).all()
        for previous in previous_runs:
            if (
                previous.id != run_id
                and previous.id.startswith(prefix)
                and previous.status != "superseded"
            ):
                previous.status = "superseded"
                previous.superseded_by = run_id
    else:
        # Snapshot identity is already fixed.  Refresh descriptive metadata,
        # but never alter generated_at or the identity that reviews reference.
        run.window_from = window_from
        run.window_to = window_to
        run.timezone = timezone_name
        run.screening_basis = screening_basis
    session.execute(delete(IngestWarning).where(IngestWarning.run_id == run_id))
    session.flush()
    return run


def _load_validation_notices(
    session: Session,
    run_id: str,
    raw: dict[str, Any],
    timezone_name: str,
    source_file: str,
) -> dict[str, Notice]:
    try:
        artifact = ValidationArtifact.model_validate(raw)
    except ValidationError as exc:
        _record_warning(
            session,
            run_id,
            "error",
            "validation_invalid",
            "validation-set.json 계약을 해석하지 못했습니다.",
            {"file": source_file, "error": str(exc)},
        )
        return {}
    _record_unknown_fields(session, run_id, _artifact_unknown_fields(raw, artifact), source_file)
    notices_raw = raw.get("notices")
    if not isinstance(notices_raw, list):
        _record_warning(
            session,
            run_id,
            "error",
            "validation_notices_missing",
            "validation-set.json에 notices 목록이 없습니다.",
            {"file": source_file},
        )
        return {}
    notices: dict[str, Notice] = {}
    for index, raw_notice in enumerate(notices_raw):
        if not isinstance(raw_notice, dict):
            _record_warning(
                session,
                run_id,
                "error",
                "notice_invalid",
                "공고 항목이 객체가 아니어서 건너뛰었습니다.",
                {"file": source_file, "index": index},
            )
            continue
        try:
            notice_model = NoticeContract.model_validate(raw_notice)
        except ValidationError as exc:
            _record_warning(
                session,
                run_id,
                "error",
                "notice_invalid",
                "공고 항목 계약을 해석하지 못해 건너뛰었습니다.",
                {"file": source_file, "index": index, "error": str(exc)},
            )
            continue
        _record_unknown_fields(
            session,
            run_id,
            model_extra_fields(notice_model, "notice"),
            source_file,
        )
        item = _upsert_notice(session, run_id, notice_model, raw_notice, timezone_name)
        if item is not None:
            notices[item.notice_key] = item
    session.flush()
    return notices


_SCREENING_COMMON_NOTICE_KEYS = (
    "notice_id", "source_type", "title", "agency", "method", "url",
    "collection_bucket", "published_at", "deadline_at", "budget",
    "estimated_price", "procurement_class", "region_limit", "lifecycle",
    "qualification_flags", "attachments", "focus_matches", "performance_matches",
    "performance_top_score", "candidate_sources", "unknown_fields", "sample_stratum",
    "sample_role", "raw_source",
)
#: Optional top-level notice keys a screening input may carry beyond the fixed
#: projection.  The backend orchestrator does not write them; the skills-side
#: validator accepts them, so the importer accepts them too (spec §1.2).
_SCREENING_OPTIONAL_NOTICE_KEYS = frozenset({"demand_agency"})
_SCREENING_JUDGMENT_INPUT_KEYS = frozenset({"judgment_mode", "carry_over_from", "rejudge_reason"})
_SCREENING_LIFECYCLE_KEYS = frozenset({
    "pre_spec_no", "re_notice", "changed_at", "change_reason", "unified_notice_no",
    "previous_failed_notice_no",
})
_SCREENING_OPTIONAL_LIFECYCLE_KEYS = frozenset({"order_plan_no", "bid_ntice_no_list", "opening_at"})
_SCREENING_QUALIFICATION_KEYS = frozenset({
    "participation_limited", "industry_limited", "information_business", "general_service",
    "service_division", "joint_contract_method", "performance_restricted_competition",
    "pq_evaluation", "technical_evaluation", "technical_evaluation_rate", "successful_bid_method",
})
_SCREENING_OPTIONAL_QUALIFICATION_KEYS = frozenset({
    "sw_business_status", "business_division", "sw_industry_1468",
})
_SW_INDUSTRY_1468_VALUES = frozenset({"Y", "N"})


def _screening_notice_keys_valid(notice: Any) -> bool:
    """Fixed input keys are required; only the declared optional keys may be added."""

    if not isinstance(notice, dict):
        return False
    required = set(_SCREENING_COMMON_NOTICE_KEYS) | _SCREENING_JUDGMENT_INPUT_KEYS
    return required <= set(notice) <= required | _SCREENING_OPTIONAL_NOTICE_KEYS


_SCREENING_INPUT_KEYS = {
    "schema_version", "execution_id", "run_id", "generated_at", "source_window",
    "policy_version", "prompt_version", "company_profile_version", "company_profile_digest",
    "candidate_count", "notices", "generation_config", "generation_config_digest",
}


def _screening_input_error(raw: Any) -> str | None:
    """Return a safe reason when a v3 input is not a closed artifact contract."""
    if not isinstance(raw, dict) or set(raw) != _SCREENING_INPUT_KEYS:
        return "top-level fields are not exact"
    if raw.get("schema_version") != "bidops.screening-input.v1":
        return "schema version is invalid"
    if not isinstance(raw.get("execution_id"), str) or EXECUTION_ID_RE.fullmatch(raw["execution_id"]) is None:
        return "execution id is invalid"
    for key in ("run_id", "policy_version", "prompt_version", "company_profile_version"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            return "identity field is invalid"
    if "/" in raw["run_id"] or "\\" in raw["run_id"] or Path(raw["run_id"]).name != raw["run_id"]:
        return "run identity is unsafe"
    digest = raw.get("company_profile_digest")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None or raw.get("company_profile_version") != f"company-profile.sha256:{digest}":
        return "profile identity is invalid"
    try:
        generation_config = config_from_value(raw.get("generation_config"))
        validate_digest(generation_config, raw.get("generation_config_digest"))
    except (GenerationConfigError, AttributeError):
        return "generation config is invalid"
    generated = raw.get("generated_at")
    if not isinstance(generated, str):
        return "generated_at is invalid"
    try:
        parsed_generated = datetime.fromisoformat(generated[:-1] + "+00:00" if generated.endswith("Z") else generated)
    except ValueError:
        return "generated_at is invalid"
    if parsed_generated.tzinfo is None or parsed_generated.utcoffset() is None:
        return "generated_at is not timezone-aware"
    window = raw.get("source_window")
    if not isinstance(window, dict) or set(window) != {"from", "to", "timezone"} or window.get("timezone") != DEFAULT_TIMEZONE:
        return "source window is invalid"
    try:
        window_from = date.fromisoformat(window["from"])
        window_to = date.fromisoformat(window["to"])
    except (TypeError, ValueError):
        return "source window dates are invalid"
    if window_from > window_to:
        return "source window is reversed"
    notices = raw.get("notices")
    if not isinstance(notices, list) or type(raw.get("candidate_count")) is not int or raw["candidate_count"] < 0 or raw["candidate_count"] != len(notices):
        return "candidate count is invalid"
    seen: set[str] = set()
    for notice in notices:
        if not _screening_notice_keys_valid(notice):
            return "notice fields are not exact"
        demand_agency = notice.get("demand_agency")
        if demand_agency is not None and (not isinstance(demand_agency, str) or not demand_agency.strip()):
            return "notice string is invalid"
        notice_id = notice.get("notice_id")
        if not isinstance(notice_id, str) or not notice_id.strip() or notice_id in seen:
            return "notice identity is duplicated or invalid"
        seen.add(notice_id)
        common = {key: notice[key] for key in _SCREENING_COMMON_NOTICE_KEYS}
        if (not isinstance(common["source_type"], str) or common["source_type"] not in {"bid_notice", "pre_spec"} or
                not isinstance(common["collection_bucket"], str) or common["collection_bucket"] not in {"candidate_pool", "audit_pool"}):
            return "notice enum is invalid"
        for key in ("title", "agency", "method", "url"):
            if common[key] is not None and (not isinstance(common[key], str) or not common[key].strip()):
                return "notice string is invalid"
        for key in ("published_at", "deadline_at"):
            if common[key] is not None:
                if not isinstance(common[key], str):
                    return "notice timestamp is invalid"
                try:
                    parsed = datetime.fromisoformat(common[key][:-1] + "+00:00" if common[key].endswith("Z") else common[key])
                except ValueError:
                    return "notice timestamp is invalid"
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    return "notice timestamp is not timezone-aware"
        for key in ("budget", "estimated_price"):
            if common[key] is not None and (not isinstance(common[key], str) or DECIMAL_RE.fullmatch(common[key]) is None):
                return "notice decimal is invalid"
        if not isinstance(common["candidate_sources"], list) or any(not isinstance(item, str) or not item.strip() for item in common["candidate_sources"]):
            return "candidate_sources is invalid"
        if not isinstance(common["unknown_fields"], list) or any(not isinstance(item, str) or not item.strip() for item in common["unknown_fields"]):
            return "unknown_fields is invalid"
        if common["performance_top_score"] is not None and (not isinstance(common["performance_top_score"], (int, float)) or isinstance(common["performance_top_score"], bool) or not math.isfinite(float(common["performance_top_score"]))):
            return "performance score is invalid"
        raw_source = common["raw_source"]
        if not isinstance(raw_source, str) or not raw_source or raw_source.startswith("/") or "\\" in raw_source or any(part in {"", ".", ".."} or ":" in part for part in raw_source.split("/")):
            return "raw_source is unsafe"
        nested = {
            "procurement_class": {"large", "middle", "detail", "code"},
            "region_limit": {"basis", "joint_contract_regions", "joint_contract_rate", "regional_joint_contract_limit"},
            "lifecycle": set(_SCREENING_LIFECYCLE_KEYS),
        }
        for key, keys in nested.items():
            actual_keys = set(common[key]) if isinstance(common[key], dict) else set()
            allowed_keys = keys | _SCREENING_OPTIONAL_LIFECYCLE_KEYS if key == "lifecycle" else keys
            if (
                not isinstance(common[key], dict)
                or not keys <= actual_keys <= allowed_keys
            ):
                return "notice nested fields are not exact"
            if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in common[key].values() if key != "region_limit" or value != common[key].get("joint_contract_regions")):
                return "notice nested string is invalid"
        qualification = common["qualification_flags"]
        if not isinstance(qualification, dict) or (
            qualification
            and not _SCREENING_QUALIFICATION_KEYS
            <= set(qualification)
            <= _SCREENING_QUALIFICATION_KEYS | _SCREENING_OPTIONAL_QUALIFICATION_KEYS
        ):
            return "qualification flags are invalid"
        if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in qualification.values()):
            return "qualification flags are invalid"
        if qualification.get("sw_industry_1468") not in _SW_INDUSTRY_1468_VALUES | {None}:
            return "qualification flags are invalid"
        for lifecycle_timestamp in ("changed_at", "opening_at"):
            value = common["lifecycle"].get(lifecycle_timestamp)
            if value is not None and not _is_aware_iso(value):
                return "lifecycle timestamp is invalid"
        if common["sample_role"] is not None and common["sample_role"] not in {"analysis", "audit"}:
            return "sample role is invalid"
        if common["sample_stratum"] is not None and common["sample_stratum"] not in {"AI/데이터", "블록체인·DID", "공공 SI·통합관리", "수행실적 유사", "분류 근접", "실적 유사 근접", "무작위"}:
            return "sample stratum is invalid"
        if not isinstance(common["region_limit"]["joint_contract_regions"], list) or any(not isinstance(item, str) or not item.strip() for item in common["region_limit"]["joint_contract_regions"]):
            return "region list is invalid"
        if not isinstance(common["attachments"], list) or any(not isinstance(item, dict) or set(item) != {"name", "url"} or any(not isinstance(item[key], str) or not item[key].strip() for key in ("name", "url")) for item in common["attachments"]):
            return "attachments are invalid"
        focus_keys = {"axis", "label", "matched_field", "matched_text", "field_kind"}
        if not isinstance(common["focus_matches"], list) or any(not isinstance(item, dict) or set(item) != focus_keys or item.get("field_kind") not in {"title", "classification", "other"} or any(not isinstance(item[key], str) or not item[key].strip() for key in ("axis", "label", "matched_field", "matched_text")) for item in common["focus_matches"]):
            return "focus matches are invalid"
        performance_keys = {"project_name", "source_page", "similarity", "common_fragment", "legal_qualification_status"}
        for item in common["performance_matches"] if isinstance(common["performance_matches"], list) else ():
            if not isinstance(item, dict) or set(item) != performance_keys:
                return "performance matches are invalid"
            page = item.get("source_page")
            if not isinstance(item.get("project_name"), str) or not item["project_name"].strip() or (not isinstance(page, int) and not (isinstance(page, str) and page.strip())) or isinstance(page, bool) or (isinstance(page, int) and page < 0) or not isinstance(item.get("similarity"), (int, float)) or isinstance(item.get("similarity"), bool) or not math.isfinite(float(item["similarity"])) or not isinstance(item.get("legal_qualification_status"), str) or not item["legal_qualification_status"].strip() or (item.get("common_fragment") is not None and (not isinstance(item["common_fragment"], str) or not item["common_fragment"].strip())):
                return "performance matches are invalid"
        if not isinstance(common["performance_matches"], list):
            return "performance matches are invalid"
        mode = notice["judgment_mode"]
        if mode not in {"신규", "재판정", "승계"}:
            return "judgment mode is invalid"
        if mode == "신규" and (notice["carry_over_from"] is not None or notice["rejudge_reason"] is not None):
            return "new judgment cross-fields are invalid"
        if mode == "재판정" and (notice["carry_over_from"] is not None or notice["rejudge_reason"] not in {"정정", "재공고", "본공고 전환", "담당자 요청"}):
            return "rejudgment cross-fields are invalid"
        if mode == "승계" and (not isinstance(notice["carry_over_from"], str) or not notice["carry_over_from"].strip() or notice["rejudge_reason"] is not None):
            return "carry-over cross-fields are invalid"
        try:
            NoticeContract.model_validate(common)
        except ValidationError:
            return "notice contract is invalid"
    return None


def _load_screening_input_notices(
    session: Session,
    run_id: str,
    raw: dict[str, Any],
    timezone_name: str,
    source_file: str,
) -> dict[str, Notice]:
    """Load v3 input notices into the DB projection without changing input bytes.

    A validation set is intentionally a sample, while a screening input is
    the immutable identity authority for a full/quality execution.  This
    helper is used only when the v1 screening input exists;
    historical v1/v2 ingest paths remain validation-set authoritative.
    """
    if raw.get("schema_version") != "bidops.screening-input.v1":
        _record_warning(
            session, run_id, "error", "screening_input_invalid",
            "screening-input.json schema_version이 지원되지 않습니다.",
            {"file": source_file, "reason": "unsupported schema version"},
        )
        return {}
    invalid_reason = _screening_input_error(raw)
    if invalid_reason is not None:
        _record_warning(
            session, run_id, "error", "screening_input_invalid",
            "screening-input.json 계약을 해석하지 못했습니다.", {"file": source_file, "reason": invalid_reason},
        )
        return {}
    if not isinstance(raw, dict):
        return {}
    notices_raw = raw.get("notices")
    if not isinstance(notices_raw, list):
        return {}
    notices: dict[str, Notice] = {}
    for index, raw_notice in enumerate(notices_raw):
        if not _screening_notice_keys_valid(raw_notice):
            return {}
        common = {key: raw_notice[key] for key in _SCREENING_COMMON_NOTICE_KEYS}
        # An optional key the input carried is passed through unchanged; the
        # observation snapshot does not depend on it (see `_upsert_notice`).
        common.update(
            {key: raw_notice[key] for key in sorted(_SCREENING_OPTIONAL_NOTICE_KEYS) if key in raw_notice}
        )
        notice_model = NoticeContract.model_validate(common)
        item = _upsert_notice(session, run_id, notice_model, common, timezone_name)
        if item is not None:
            notices[item.notice_key] = item
    session.flush()
    return notices


def _load_collection_stats(
    session: Session,
    run_id: str,
    raw: dict[str, Any],
    source_file: str,
    run: Run,
) -> None:
    try:
        artifact = CollectionArtifact.model_validate({**raw, "notices": []})
    except ValidationError as exc:
        _record_warning(
            session,
            run_id,
            "warning",
            "collected_notices_invalid",
            "collected-notices.json의 메타데이터를 해석하지 못했습니다.",
            {"file": source_file, "error": str(exc)},
        )
        return
    _record_unknown_fields(session, run_id, _artifact_unknown_fields(raw, artifact), source_file)
    # The validation set is the immutable screen snapshot.  Collection data is
    # deliberately kept as statistics here; loading all 2,546 source notices
    # would violate the Step 2 completion criterion of 40 notices.
    counts = raw.get("counts")
    if isinstance(counts, dict):
        current = run.counts_json if isinstance(run.counts_json, dict) else {}
        run.counts_json = {**current, "collection": counts}


def _order_plan_items(raw: dict[str, Any]) -> tuple[list[Any] | None, str | None]:
    """Return plan rows from the canonical field or known older spellings."""

    for key in ("order_plans", "plans", "items"):
        value = raw.get(key)
        if isinstance(value, list):
            return value, key
    return None, None


def _order_plan_artifact_unknown_fields(
    raw: dict[str, Any], artifact: OrderPlanArtifact
) -> list[str]:
    """Ignore known aliases while retaining genuine artifact drift warnings."""

    unknown = _artifact_unknown_fields(raw, artifact)
    compatibility_prefixes = ("order_plans[", "plans[", "items[")
    return [
        field
        for field in unknown
        if not (
            field.startswith(compatibility_prefixes)
            and field.rsplit(".", 1)[-1] in _ORDER_PLAN_KNOWN_KEYS
        )
    ]


def _load_order_plans(
    session: Session,
    run_id: str,
    raw: dict[str, Any],
    timezone_name: str,
    source_file: str,
) -> int:
    """Load the independent cumulative order-plan artifact.

    This path intentionally does not pass plans through ``Notice``.  It keeps
    the full normalized plan artifact and its raw reference separate from the
    notice collection contract, then creates one observation per plan/run.
    """

    try:
        artifact = OrderPlanArtifact.model_validate(raw)
    except ValidationError as exc:
        _record_warning(
            session,
            run_id,
            "error",
            "order_plans_invalid",
            f"{ORDER_PLAN_FILE} 계약을 해석하지 못했습니다.",
            {"file": source_file, "error": str(exc)},
        )
        return 0
    _record_unknown_fields(
        session,
        run_id,
        _order_plan_artifact_unknown_fields(raw, artifact),
        source_file,
    )
    if raw.get("schema_version") not in ORDER_PLAN_ARTIFACT_SCHEMAS:
        _record_warning(
            session,
            run_id,
            "error",
            "order_plans_invalid",
            f"{ORDER_PLAN_FILE} schema_version이 지원되지 않습니다.",
            {"file": source_file, "schema_version": raw.get("schema_version")},
        )
        return 0

    plan_rows, rows_key = _order_plan_items(raw)
    if plan_rows is None:
        _record_warning(
            session,
            run_id,
            "error",
            "order_plans_missing",
            f"{ORDER_PLAN_FILE}에 발주계획 목록이 없습니다.",
            {"file": source_file, "expected_field": "order_plans"},
        )
        return 0
    if rows_key != "order_plans":
        _record_warning(
            session,
            run_id,
            "info",
            "order_plans_legacy_field",
            f"{ORDER_PLAN_FILE}의 호환 목록 필드를 읽었습니다.",
            {"file": source_file, "field": rows_key},
        )

    counts = raw.get("counts")
    if isinstance(counts, dict):
        declared = counts.get("total")
        if declared is None:
            declared = counts.get("order_plans", counts.get("plans"))
        if type(declared) is int and declared != len(plan_rows):
            _record_warning(
                session,
                run_id,
                "warning",
                "order_plans_count_mismatch",
                f"{ORDER_PLAN_FILE} counts와 목록 길이가 다릅니다.",
                {"file": source_file, "declared": declared, "actual": len(plan_rows)},
            )

    loaded = 0
    seen: set[str] = set()
    for index, raw_plan in enumerate(plan_rows):
        if not isinstance(raw_plan, dict):
            _record_warning(
                session,
                run_id,
                "error",
                "order_plan_invalid",
                "발주계획 항목이 객체가 아니어서 건너뛰었습니다.",
                {"file": source_file, "index": index},
            )
            continue
        try:
            OrderPlanContract.model_validate(raw_plan)
        except ValidationError as exc:
            _record_warning(
                session,
                run_id,
                "error",
                "order_plan_invalid",
                "발주계획 항목 계약을 해석하지 못해 건너뛰었습니다.",
                {"file": source_file, "index": index, "error": str(exc)},
            )
            continue
        _record_unknown_fields(
            session,
            run_id,
            [
                f"order_plan[{index}].{key}"
                for key in raw_plan
                if key not in _ORDER_PLAN_KNOWN_KEYS
            ],
            source_file,
        )
        plan_no = _plan_text(
            raw_plan, *_ORDER_PLAN_FIELD_ALIASES["order_plan_unty_no"]
        )
        if plan_no is not None and plan_no in seen:
            _record_warning(
                session,
                run_id,
                "error",
                "order_plan_duplicate",
                "같은 발주계획번호가 한 artifact에 중복되어 뒤 항목을 건너뛰었습니다.",
                {"file": source_file, "index": index, "order_plan_no": plan_no},
            )
            continue
        if plan_no is not None:
            seen.add(plan_no)
        item = _upsert_order_plan(session, run_id, raw_plan, timezone_name)
        if item is not None:
            loaded += 1
    session.flush()
    return loaded


# ---------------------------------------------------------------------------
# 수집 색인과 선별 적재 (spec §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CollectedNotice:
    """One valid collected notice with the values its index row was built from."""

    values: IndexValues
    contract: NoticeContract
    raw: dict[str, Any]


@dataclass
class _TrackedKeys:
    """Official keys owned by active opportunities in the requested states.

    A deferred (targetless) official link is an authoritative ownership claim
    on its external number, so its evidence number counts as a key as well.
    """

    order_plan_nos: set[str] = field(default_factory=set)
    pre_spec_nos: set[str] = field(default_factory=set)
    bid_nos: set[str] = field(default_factory=set)
    order_plan_tokens: set[str] = field(default_factory=set)
    pre_spec_tokens: set[str] = field(default_factory=set)

    def references_bid(self, values: IndexValues) -> bool:
        """Decision 1 ①: the bid's official key points at a tracked record."""

        if values.order_plan_unty_no is not None and values.order_plan_unty_no in self.order_plan_nos:
            return True
        if values.bf_spec_rgst_no is not None and values.bf_spec_rgst_no in self.pre_spec_nos:
            return True
        if values.bid_no is None:
            return False
        # A plan token is the 13-character bid number plus its order; a
        # pre-spec token is the bid number alone.  Both compare exactly.
        if values.bid_ord is not None and f"{values.bid_no}{values.bid_ord}" in self.order_plan_tokens:
            return True
        return values.bid_no in self.pre_spec_tokens


@dataclass
class IndexedIngestResult:
    """What one indexed-record load did.  ``notices`` is keyed by index row id."""

    loaded: Counter[str] = field(default_factory=Counter)
    unavailable: int = 0
    notices: dict[int, Notice] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "loaded": dict(sorted(self.loaded.items())),
            "unavailable": self.unavailable,
        }


def _collection_record_kind(source_type: Any) -> str | None:
    value = source_type.strip().lower() if isinstance(source_type, str) else ""
    if value in _PRE_SPEC_SOURCE_TYPES:
        return "pre_spec"
    if value == "bid_notice":
        return "bid_notice"
    return None


def _notice_index_values(
    notice: NoticeContract,
    raw: dict[str, Any],
    timezone_name: str,
) -> tuple[IndexValues | None, tuple[str, ...]]:
    """Build index values from a collected notice without inventing a value."""

    record_kind = _collection_record_kind(notice.source_type)
    record_key = _index_text(notice.notice_id)
    if record_kind is None or record_key is None:
        return None, ()
    order_plan_no, pre_spec_no = _notice_linkage_keys(notice, raw)
    lifecycle = _mapping_value(notice.lifecycle)
    flags = _mapping_value(notice.qualification_flags)
    bid_no: str | None = None
    bid_ord: str | None = None
    tokens: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    if record_kind == "pre_spec":
        pre_spec_no = pre_spec_no or _pre_spec_number_from_key(record_key)
        tokens, rejected = split_tokens(lifecycle.get("bid_ntice_no_list"))
    else:
        bid_no, bid_ord = parse_notice_key(record_key)
    try:
        published_at = _parse_datetime(notice.published_at, timezone_name, field_name="published_at")
    except ValueError:
        # The loader records invalid_datetime when the record is loaded; an
        # unparsable value is simply absent from the search index.
        published_at = None
    return (
        IndexValues(
            record_kind=record_kind,
            record_key=record_key,
            title=_index_text(notice.title),
            agency=_index_text(notice.agency),
            demand_agency=_index_text(notice.demand_agency),
            order_plan_unty_no=order_plan_no,
            bf_spec_rgst_no=pre_spec_no,
            bid_no=bid_no,
            bid_ord=bid_ord,
            sw_business_status=_index_text(flags.get("sw_business_status")),
            sw_industry_1468=_index_text(flags.get("sw_industry_1468")),
            contract_method=_index_text(notice.method),
            published_at=published_at,
            tokens=tokens,
        ),
        rejected,
    )


def _order_plan_index_values(
    raw_plan: dict[str, Any],
    timezone_name: str,
) -> tuple[IndexValues | None, tuple[str, ...]]:
    plan_no = _plan_text(raw_plan, *_ORDER_PLAN_FIELD_ALIASES["order_plan_unty_no"])
    if plan_no is None:
        return None, ()
    try:
        published_at = _parse_order_plan_datetime(
            _plan_first_value(raw_plan, *_ORDER_PLAN_FIELD_ALIASES["published_at"]),
            timezone_name,
            field_name="published_at",
        )
    except ValueError:
        published_at = None
    tokens, rejected = split_tokens(
        _plan_first_value(raw_plan, *_ORDER_PLAN_FIELD_ALIASES["bid_ntice_no_list"])
    )
    return (
        IndexValues(
            record_kind="order_plan",
            record_key=plan_no,
            title=_plan_text(raw_plan, *_ORDER_PLAN_FIELD_ALIASES["title"]),
            agency=_plan_text(raw_plan, *_ORDER_PLAN_FIELD_ALIASES["agency_name"]),
            order_plan_unty_no=plan_no,
            sw_business_status=_plan_text(raw_plan, *_ORDER_PLAN_FIELD_ALIASES["sw_business_status"]),
            contract_method=_plan_text(raw_plan, *_ORDER_PLAN_FIELD_ALIASES["contract_method"]),
            published_at=published_at,
            tokens=tokens,
        ),
        rejected,
    )


def _record_unindexed_tokens(
    session: Session,
    run_id: str,
    values: IndexValues,
    rejected: tuple[str, ...],
) -> None:
    if not rejected:
        return
    _record_warning(
        session,
        run_id,
        "warning",
        "collection_token_unindexed",
        "bidNtceNoList 토큰이 색인 길이를 넘어 색인하지 않았습니다. 회차 원문에는 그대로 남아 있습니다.",
        {
            "record_kind": values.record_kind,
            "record_key": values.record_key,
            "token_count": len(rejected),
        },
    )


def _collection_order_plan_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Plan rows of an artifact that `_load_order_plans` would read at all."""

    if raw.get("schema_version") not in ORDER_PLAN_ARTIFACT_SCHEMAS:
        return []
    try:
        OrderPlanArtifact.model_validate(raw)
    except ValidationError:
        return []
    rows, _key = _order_plan_items(raw)
    return [row for row in rows or [] if isinstance(row, dict)]


def _collection_notice_records(
    session: Session,
    run_id: str,
    raw: dict[str, Any],
    source_file: str,
    timezone_name: str,
) -> list[_CollectedNotice]:
    """Parse every collected notice; invalid rows are warned and skipped."""

    try:
        CollectionArtifact.model_validate({**raw, "notices": []})
    except ValidationError:
        # `_load_collection_stats` has already recorded the metadata warning.
        return []
    if raw.get("schema_version") != COLLECTION_ARTIFACT_SCHEMA:
        _record_warning(
            session,
            run_id,
            "error",
            "collected_notices_invalid",
            f"{COLLECTION_FILE} schema_version이 지원되지 않아 공고를 적재하지 않았습니다.",
            {"file": source_file, "schema_version": raw.get("schema_version")},
        )
        return []
    notices_raw = raw.get("notices")
    if not isinstance(notices_raw, list):
        _record_warning(
            session,
            run_id,
            "error",
            "collected_notices_missing",
            f"{COLLECTION_FILE}에 notices 목록이 없습니다.",
            {"file": source_file},
        )
        return []
    records: list[_CollectedNotice] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_notice in enumerate(notices_raw):
        if not isinstance(raw_notice, dict):
            _record_warning(
                session, run_id, "error", "notice_invalid",
                "공고 항목이 객체가 아니어서 건너뛰었습니다.",
                {"file": source_file, "index": index},
            )
            continue
        try:
            notice_model = NoticeContract.model_validate(raw_notice)
        except ValidationError as exc:
            _record_warning(
                session, run_id, "error", "notice_invalid",
                "공고 항목 계약을 해석하지 못해 건너뛰었습니다.",
                {"file": source_file, "index": index, "error": str(exc)},
            )
            continue
        _record_unknown_fields(
            session, run_id, model_extra_fields(notice_model, "notice"), source_file
        )
        values, rejected = _notice_index_values(notice_model, raw_notice, timezone_name)
        if values is None:
            if is_blank(notice_model.notice_id):
                _record_warning(
                    session, run_id, "error", "notice_id_missing",
                    "notice_id가 없는 공고를 적재하지 않았습니다.",
                    {"file": source_file, "index": index, "field": "notice_id"},
                )
            else:
                _record_warning(
                    session, run_id, "warning", "collection_record_kind_unknown",
                    "source_type을 색인 원천으로 해석하지 못해 건너뛰었습니다.",
                    {"file": source_file, "index": index, "source_type": notice_model.source_type},
                )
            continue
        if values.identity in seen:
            _record_warning(
                session, run_id, "error", "collection_notice_duplicate",
                "같은 notice_id가 한 수집 파일에 중복되어 뒤 항목을 건너뛰었습니다.",
                {"file": source_file, "index": index, "notice_id": values.record_key},
            )
            continue
        seen.add(values.identity)
        _record_unindexed_tokens(session, run_id, values, rejected)
        records.append(_CollectedNotice(values=values, contract=notice_model, raw=raw_notice))
    return records


def _collection_path_for_run(runs_root: Path | None, run_id: str) -> Path | None:
    """The collected-notices file of a run directory, or ``None`` if unsafe."""

    if runs_root is None:
        return None
    parsed = parse_run_id(run_id)
    name = parsed[0] if parsed else run_id.split("--", 1)[0]
    if not name or name in {".", ".."} or "\\" in name or Path(name).name != name:
        return None
    directory = runs_root / name
    path = directory / COLLECTION_FILE
    if directory.is_symlink() or path.is_symlink():
        return None
    return path


class _IndexedRecordLoader:
    """Load index rows through `_upsert_notice` from their own run files.

    The observation is recorded against the run the record was collected in,
    so its snapshot and ``observed_at`` describe that run's immutable bytes.
    Rows of the run being ingested reuse the records already parsed in memory.
    """

    def __init__(
        self,
        session: Session,
        *,
        runs_root: Path | None,
        current_run_id: str | None = None,
        current_records: dict[str, _CollectedNotice] | None = None,
    ) -> None:
        self.session = session
        self.runs_root = runs_root
        self.current_run_id = current_run_id
        self.current_records = current_records or {}
        self.result = IndexedIngestResult()
        self._files: dict[str, dict[str, dict[str, Any]] | None] = {}
        self._touched_runs: set[str] = set()

    def _run_records(self, run_id: str) -> dict[str, dict[str, Any]] | None:
        if run_id not in self._files:
            path = _collection_path_for_run(self.runs_root, run_id)
            raw = _read_optional_json(path) if path is not None else None
            mapping: dict[str, dict[str, Any]] | None = None
            if raw is not None and raw.get("schema_version") == COLLECTION_ARTIFACT_SCHEMA:
                notices = raw.get("notices")
                if isinstance(notices, list):
                    mapping = {}
                    for item in notices:
                        key = _index_text(item.get("notice_id")) if isinstance(item, dict) else None
                        if key is not None:
                            mapping.setdefault(key, item)
            self._files[run_id] = mapping
        return self._files[run_id]

    def _unavailable(self, row: CollectedRecordIndex) -> None:
        self.result.unavailable += 1
        _record_warning(
            self.session,
            self.current_run_id or row.run_id,
            "warning",
            "collection_record_unavailable",
            "색인이 가리키는 수집 레코드를 회차 파일에서 읽지 못해 적재하지 않았습니다.",
            {
                "run_id": row.run_id,
                "record_kind": row.record_kind,
                "record_key": row.record_key,
            },
        )

    def _record(self, row: CollectedRecordIndex) -> tuple[NoticeContract, dict[str, Any]] | None:
        if row.run_id == self.current_run_id:
            current = self.current_records.get(row.record_key)
            if current is not None and current.values.record_kind == row.record_kind:
                return current.contract, current.raw
        records = self._run_records(row.run_id)
        raw = records.get(row.record_key) if records is not None else None
        if raw is None:
            return None
        try:
            contract = NoticeContract.model_validate(raw)
        except ValidationError:
            return None
        if _collection_record_kind(contract.source_type) != row.record_kind:
            return None
        return contract, raw

    def load(self, row: CollectedRecordIndex, reason: str) -> Notice | None:
        record = self._record(row)
        if record is None:
            self._unavailable(row)
            return None
        contract, raw = record
        run = self.session.get(Run, row.run_id)
        timezone_name, _zone = _ensure_zone(run.timezone if run is not None else None)
        item = _upsert_notice(self.session, row.run_id, contract, raw, timezone_name)
        if item is None:
            return None
        self.session.flush()
        mark_selected(row, reason, notice_id=item.id)
        self.result.loaded[reason] += 1
        self.result.notices[row.id] = item
        if row.run_id != self.current_run_id:
            self._touched_runs.add(row.run_id)
        return item

    def load_bid(
        self,
        row: CollectedRecordIndex,
        reason: str,
        pre_spec_rows: dict[str, CollectedRecordIndex] | None = None,
    ) -> Notice | None:
        """Load a referenced, not-yet-loaded pre-spec first, then the bid."""

        number = row.bf_spec_rgst_no
        if number is not None and _find_pre_spec_notice(self.session, number) is None:
            if pre_spec_rows is None:
                pre_spec_rows = latest_rows(
                    self.session, "pre_spec", CollectedRecordIndex.bf_spec_rgst_no, [number]
                )
            referenced = pre_spec_rows.get(number)
            if referenced is not None:
                self.load(referenced, "pre_spec_referenced")
        return self.load(row, reason)

    def refresh_touched_runs(self) -> None:
        """Keep the notice count of an earlier run that received an observation."""

        for run_id in sorted(self._touched_runs):
            run = self.session.get(Run, run_id)
            if run is None:  # pragma: no cover - an index row always has its run.
                continue
            current = run.counts_json if isinstance(run.counts_json, dict) else {}
            run.counts_json = {**current, "notices": _observed_notice_count(self.session, run_id)}


def _observed_notice_count(session: Session, run_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(func.distinct(Notice.id)))
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(NoticeObservation.run_id == run_id)
        )
        or 0
    )


def _tracked_reference_keys(
    session: Session,
    statuses: Iterable[str],
    *,
    opportunity_ids: Iterable[int] | None = None,
) -> _TrackedKeys:
    """Collect official keys of records owned by active, tracked opportunities."""

    keys = _TrackedKeys()
    statement = (
        select(OpportunityLink, OrderPlan, Notice)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .outerjoin(OrderPlan, OrderPlan.id == OpportunityLink.order_plan_id)
        .outerjoin(Notice, Notice.id == OpportunityLink.notice_id)
        .where(
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
            Opportunity.tracking_status.in_(tuple(statuses)),
        )
    )
    if opportunity_ids is not None:
        statement = statement.where(Opportunity.id.in_(sorted(set(opportunity_ids))))
    for link, plan, notice in session.execute(statement).tuples():
        if plan is not None:
            keys.order_plan_nos.add(plan.order_plan_unty_no)
            keys.order_plan_tokens.update(split_tokens(plan.bid_ntice_no_list)[0])
        elif notice is not None:
            if (notice.source_type or "").strip().lower() in _PRE_SPEC_SOURCE_TYPES:
                number = _stored_pre_spec_number(notice)
                if number is not None:
                    keys.pre_spec_nos.add(number)
                lifecycle = notice.lifecycle_json if isinstance(notice.lifecycle_json, dict) else {}
                keys.pre_spec_tokens.update(split_tokens(lifecycle.get("bid_ntice_no_list"))[0])
            elif not is_blank(notice.bid_no):
                keys.bid_nos.add(str(notice.bid_no))
        elif link.link_type == "official" and not is_blank(link.evidence_external_no):
            reference = str(link.evidence_external_no).strip()
            if link.stage == "order_plan":
                keys.order_plan_nos.add(reference)
            else:
                keys.pre_spec_nos.add(reference)
    keys.order_plan_tokens.update(
        tokens_for(session, "order_plan", CollectedRecordIndex.record_key, keys.order_plan_nos)
    )
    keys.pre_spec_tokens.update(
        tokens_for(session, "pre_spec", CollectedRecordIndex.bf_spec_rgst_no, keys.pre_spec_nos)
    )
    return keys


def _existing_bid_numbers(session: Session, bid_nos: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for batch in _chunks(sorted(set(bid_nos))):
        found.update(
            session.scalars(select(Notice.bid_no).where(Notice.bid_no.in_(batch)).distinct())
        )
    return found


def _sw_pre_spec_numbers_in_db(session: Session, numbers: Iterable[str]) -> set[str]:
    """Pre-spec numbers whose stored Notice projection says SW사업대상 Y."""

    by_key: dict[str, str] = {}
    for number in sorted(set(numbers)):
        for key in _pre_spec_notice_keys(number):
            by_key.setdefault(key, number)
    found: set[str] = set()
    for batch in _chunks(sorted(by_key)):
        for notice in session.scalars(
            select(Notice).where(
                Notice.source_type.in_(tuple(sorted(_PRE_SPEC_SOURCE_TYPES))),
                Notice.notice_key.in_(batch),
            )
        ):
            flags = notice.qualification_flags_json
            if isinstance(flags, dict) and flags.get("sw_business_status") == "Y":
                found.add(by_key[notice.notice_key])
    return found


def _stored_pre_spec_record_keys(
    session: Session,
    values: Iterable[IndexValues],
) -> set[str]:
    """Record keys of collected pre-specs whose Notice is already stored."""

    by_key: dict[str, str] = {}
    for item in values:
        by_key.setdefault(item.record_key, item.record_key)
        if item.bf_spec_rgst_no is not None:
            for key in _pre_spec_notice_keys(item.bf_spec_rgst_no):
                by_key.setdefault(key, item.record_key)
    found: set[str] = set()
    for batch in _chunks(sorted(by_key)):
        for key in session.scalars(
            select(Notice.notice_key).where(
                Notice.source_type.in_(tuple(sorted(_PRE_SPEC_SOURCE_TYPES))),
                Notice.notice_key.in_(batch),
            )
        ):
            found.add(by_key[key])
    return found


def _sw_industry_competitive(values: IndexValues) -> bool:
    """Decision 1 ③: 1468 tag Y on a competitive bid.  Null never matches."""

    method = values.contract_method
    return values.sw_industry_1468 == "Y" and method is not None and "수의" not in method


def _load_collection_run(
    session: Session,
    run: Run,
    directory: Path,
    *,
    order_plan_raw: dict[str, Any] | None,
    order_plan_path: Path,
    collection_raw: dict[str, Any] | None,
    collection_path: Path,
    timezone_name: str,
) -> tuple[int, dict[str, Any]]:
    """Index a whole run and load the selected records (spec §2.2).

    Order plans → pre-specs → bids.  A row that already carries a selection
    reason keeps it and is replayed through the same idempotent loader, so a
    re-run of the same run is a no-op.  Every other row is evaluated once;
    the first matching reason wins and a null condition value never matches.
    """

    run_id = run.id
    order_plans_count = 0
    if order_plan_raw is None and collection_raw is None:
        _record_warning(
            session,
            run_id,
            "error",
            "collection_missing",
            "수집 파일이 없어 선별 적재를 하지 않았습니다.",
            {"files": [ORDER_PLAN_FILE, COLLECTION_FILE]},
        )

    if order_plan_raw is not None:
        plan_values: list[IndexValues] = []
        for raw_plan in _collection_order_plan_rows(order_plan_raw):
            values, rejected = _order_plan_index_values(raw_plan, timezone_name)
            if values is None:
                continue
            _record_unindexed_tokens(session, run_id, values, rejected)
            plan_values.append(values)
        plan_rows = upsert_index_rows(session, run_id, plan_values)
        order_plans_count = _load_order_plans(
            session, run_id, order_plan_raw, timezone_name, str(order_plan_path)
        )
        # A Result has ``keys()``, so ``dict(result)`` would treat it as a mapping.
        observed_plans = {
            plan_no: plan_id
            for plan_no, plan_id in session.execute(
                select(OrderPlan.order_plan_unty_no, OrderPlan.id)
                .join(OrderPlanObservation, OrderPlanObservation.order_plan_id == OrderPlan.id)
                .where(OrderPlanObservation.run_id == run_id)
            )
        }
        for (kind, key), row in plan_rows.items():
            if kind == "order_plan" and key in observed_plans:
                mark_selected(row, "order_plan_all", order_plan_id=observed_plans[key])

    if collection_raw is not None:
        _load_collection_stats(session, run_id, collection_raw, str(collection_path), run)
        records = _collection_notice_records(
            session, run_id, collection_raw, str(collection_path), timezone_name
        )
        rows = upsert_index_rows(session, run_id, [record.values for record in records])
        loader = _IndexedRecordLoader(
            session,
            runs_root=directory.parent,
            current_run_id=run_id,
            current_records={record.values.record_key: record for record in records},
        )

        pre_specs = [record for record in records if record.values.record_kind == "pre_spec"]
        known_pre_specs = _stored_pre_spec_record_keys(
            session, (record.values for record in pre_specs)
        )
        for record in pre_specs:
            row = rows[record.values.identity]
            reason = row.selection_reason
            if reason is None and record.values.sw_business_status == "Y":
                reason = "pre_spec_sw"
            elif reason is None and record.values.record_key in known_pre_specs:
                # A pre-spec already in the database is refreshed from every
                # later observation, whatever first selected it.
                reason = "pre_spec_known"
            if reason is not None:
                loader.load(row, reason)

        bids = [record for record in records if record.values.record_kind == "bid_notice"]
        if bids:
            existing_bid_nos = _existing_bid_numbers(
                session, (record.values.bid_no for record in bids if record.values.bid_no)
            )
            tracked = _tracked_reference_keys(session, TRACKED_REFERENCE_STATUSES)
            referenced_numbers = {
                record.values.bf_spec_rgst_no for record in bids if record.values.bf_spec_rgst_no
            }
            pre_spec_rows = latest_rows(
                session, "pre_spec", CollectedRecordIndex.bf_spec_rgst_no, referenced_numbers
            )
            sw_pre_specs = {
                number for number, row in pre_spec_rows.items() if row.sw_business_status == "Y"
            } | _sw_pre_spec_numbers_in_db(session, referenced_numbers)

            # Rules ①–③ do not depend on load order.  ``bid_same_notice_no``
            # then sees the database before this stage (any order of the bid
            # number, so a bid already loaded is re-observed in a later run)
            # plus every other order of the same bid number that ①–③ selected
            # in this run, so the outcome does not depend on the file order.
            static_reasons: dict[str, str | None] = {}
            selected_orders: dict[str, set[str]] = {}
            for record in bids:
                values = record.values
                if tracked.references_bid(values):
                    reason = "bid_tracked_reference"
                elif values.bf_spec_rgst_no is not None and values.bf_spec_rgst_no in sw_pre_specs:
                    reason = "bid_sw_prespec_reference"
                elif _sw_industry_competitive(values):
                    reason = "bid_sw_industry_competitive"
                else:
                    reason = None
                static_reasons[values.record_key] = reason
                if reason is not None and values.bid_no is not None:
                    selected_orders.setdefault(values.bid_no, set()).add(values.record_key)

            for record in bids:
                values = record.values
                row = rows[values.identity]
                reason = row.selection_reason
                if reason is None:
                    same_number = values.bid_no is not None and (
                        values.bid_no in existing_bid_nos
                        or bool(selected_orders.get(values.bid_no, set()) - {values.record_key})
                    )
                    reason = "bid_same_notice_no" if same_number else static_reasons[values.record_key]
                if reason is not None:
                    loader.load_bid(row, reason, pre_spec_rows)
        loader.refresh_touched_runs()

    return order_plans_count, selection_stats(session, run_id)


def ingest_indexed_records(
    session: Session,
    rows: Iterable[CollectedRecordIndex],
    *,
    reason: str,
    runs_root: str | Path,
) -> IndexedIngestResult:
    """Load index rows from their run files through the ordinary notice path.

    Used by tracked backfill (``tracked_backfill``) and by search
    (``search_result``).  Pre-specs load before bids; a bid whose
    ``bfSpecRgstNo`` names a pre-spec that is only in the index loads that
    pre-spec first as ``pre_spec_referenced``.  Order plans are always loaded
    in full with their run and are refused here.  The caller owns commit.
    """

    if reason not in INDEXED_INGEST_REASONS:
        raise ValueError(f"indexed ingest reason must be one of {INDEXED_INGEST_REASONS}")
    ordered = sorted(
        rows,
        key=lambda row: (RECORD_KINDS.index(row.record_kind), row.record_key, row.run_id),
    )
    if any(row.record_kind == "order_plan" for row in ordered):
        raise ValueError("order plans are loaded in full with their run, not from the index")
    loader = _IndexedRecordLoader(session, runs_root=Path(runs_root))
    for row in ordered:
        if row.record_kind == "bid_notice":
            loader.load_bid(row, reason)
        else:
            loader.load(row, reason)
    loader.refresh_touched_runs()
    session.flush()
    return loader.result


def _tracked_backfill_rows(
    session: Session,
    *,
    opportunity_ids: Iterable[int] | None = None,
) -> list[CollectedRecordIndex]:
    """Newest un-ingested index rows referencing a tracked opportunity (spec §5)."""

    keys = _tracked_reference_keys(
        session, BACKFILL_TRACKING_STATUSES, opportunity_ids=opportunity_ids
    )
    candidates: list[CollectedRecordIndex] = []

    def rows_where(record_kind: str, column: Any, values: Iterable[str]) -> list[CollectedRecordIndex]:
        found: list[CollectedRecordIndex] = []
        for batch in _chunks(sorted({value for value in values if value})):
            found.extend(
                session.scalars(
                    select(CollectedRecordIndex).where(
                        CollectedRecordIndex.record_kind == record_kind,
                        column.in_(batch),
                    )
                )
            )
        return found

    candidates.extend(rows_where("bid_notice", CollectedRecordIndex.order_plan_unty_no, keys.order_plan_nos))
    candidates.extend(rows_where("bid_notice", CollectedRecordIndex.bf_spec_rgst_no, keys.pre_spec_nos))
    candidates.extend(
        rows_where("bid_notice", CollectedRecordIndex.bid_no, keys.bid_nos | keys.pre_spec_tokens)
    )
    # A plan token is bid number + order.  The three-character tail is removed
    # only to narrow the query; the match itself is the exact full token.
    candidates.extend(
        row
        for row in rows_where(
            "bid_notice",
            CollectedRecordIndex.bid_no,
            {token[:-3] for token in keys.order_plan_tokens if len(token) > 3},
        )
        if row.bid_ord is not None and f"{row.bid_no}{row.bid_ord}" in keys.order_plan_tokens
    )
    candidates.extend(rows_where("pre_spec", CollectedRecordIndex.bf_spec_rgst_no, keys.pre_spec_nos))
    candidates.extend(rows_with_tokens(session, "pre_spec", keys.bid_nos))

    latest = latest_row_per_identity(session, candidates)
    existing_keys: set[str] = set()
    for batch in _chunks(sorted({row.record_key for row in latest})):
        existing_keys.update(session.scalars(select(Notice.notice_key).where(Notice.notice_key.in_(batch))))
    result: list[CollectedRecordIndex] = []
    for row in latest:
        if row.record_key in existing_keys:
            continue
        if (
            row.record_kind == "pre_spec"
            and row.bf_spec_rgst_no is not None
            and _find_pre_spec_notice(session, row.bf_spec_rgst_no) is not None
        ):
            continue
        result.append(row)
    return result


def tracked_backfill(
    session: Session,
    *,
    runs_root: str | Path,
    opportunity_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Load index-only records referenced by 계속 추적·보류 opportunities (spec §5).

    Repeats until a pass finds no new candidate, because a loaded bid adds its
    own bid number as a key.  Each record identity is attempted at most once,
    so an unreadable run file cannot loop.  The caller owns commit.
    """

    ids = None if opportunity_ids is None else sorted(set(opportunity_ids))
    attempted: set[tuple[str, str]] = set()
    loaded: Counter[str] = Counter()
    unavailable = 0
    passes = 0
    while True:
        rows = [
            row
            for row in _tracked_backfill_rows(session, opportunity_ids=ids)
            if (row.record_kind, row.record_key) not in attempted
        ]
        if not rows:
            break
        passes += 1
        attempted.update((row.record_kind, row.record_key) for row in rows)
        result = ingest_indexed_records(
            session, rows, reason="tracked_backfill", runs_root=runs_root
        )
        loaded.update(result.loaded)
        unavailable += result.unavailable
    return {
        "passes": passes,
        "candidates": len(attempted),
        "loaded": dict(sorted(loaded.items())),
        "unavailable": unavailable,
    }


def _warning_dicts(session: Session, run_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(IngestWarning).where(IngestWarning.run_id == run_id).order_by(IngestWarning.id)
    ).all()
    return [
        {
            "id": row.id,
            "level": row.level,
            "code": row.code,
            "message": row.message,
            "context": row.context_json,
        }
        for row in rows
    ]


def _run_ingested_hooks(
    session: Session,
    run_id: str,
    directory: Path,
    *,
    reports_root: Path | None = None,
) -> RunIngestCounts:
    """회차 적재됨 hook을 등록 순서대로 부르고 건수를 돌려준다 (명세 §6.2).

    lifecycle은 어느 모듈이 무엇을 하는지 알지 못한다. hook은 같은 session에서
    동기적으로 돌고 자기 실패를 savepoint 안에 가둔 뒤 경고로 돌려주므로, 회차
    적재 transaction은 영향을 받지 않는다. 돌려받은 경고는 회차 경고로 남겨
    API 응답에서 기존과 같은 자리에 보인다.
    """

    # `app.lifecycle`은 `api`를 거쳐 이 파일을 import하므로 registry는 호출
    # 시점에 가져온다(순환 import 회피). 같은 모듈 안의 import다.
    from ..extensions import extension_registry

    counts = extension_registry().run_ingested(
        session, run_id, directory, reports_root=reports_root
    )
    for warning in counts.warnings:
        _record_warning(
            session,
            run_id,
            str(warning.get("level", "warning")),
            str(warning["code"]),
            str(warning["message"]),
            warning.get("context"),
        )
    return counts


def _update_counts(session: Session, run: Run, *, judgments: int = 0, reviews: int = 0) -> int:
    """회차 projection의 건수를 갱신하고 공고 수를 돌려준다.

    공고·발주계획은 lifecycle이 직접 센다. 판정·리뷰 건수는 회차 적재 hook이
    돌려준 값이며, 제공자가 없으면 0이다(§6.2) — 그 자리를 lifecycle이 판정
    테이블을 세어 채우면 없는 모듈의 결과를 아는 셈이 된다.
    """

    notices = int(
        session.scalar(
            select(func.count(func.distinct(Notice.id)))
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(NoticeObservation.run_id == run.id)
        )
        or 0
    )
    current = run.counts_json if isinstance(run.counts_json, dict) else {}
    order_plans = int(
        session.scalar(
            select(func.count(func.distinct(OrderPlan.id)))
            .join(
                OrderPlanObservation,
                OrderPlanObservation.order_plan_id == OrderPlan.id,
            )
            .where(OrderPlanObservation.run_id == run.id)
        )
        or 0
    )
    run.counts_json = {
        **current,
        "notices": notices,
        "order_plans": order_plans,
        "judgments": judgments,
        "reviews": reviews,
    }
    return notices


def _clear_generation_metadata(run: Run) -> None:
    current = run.counts_json if isinstance(run.counts_json, dict) else {}
    if "generation_config" in current or "generation_config_digest" in current:
        run.counts_json = {
            key: value
            for key, value in current.items()
            if key not in {"generation_config", "generation_config_digest"}
        }



def _store_generation_metadata(
    run: Run,
    config: dict[str, Any] | None,
    digest: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """정규화된 v3 binding을 회차 projection에 남긴다.

    `Run`은 generation binding보다 먼저 생긴 모델이고 그 JSON counts projection이
    DB 모델을 바꾸지 않고 쓸 수 있는 호환 저장소다. 공개 counts schema는 이
    메타데이터 키를 무시하며, 재적재와 왕복 binding이 필요한 호출부는 정확한
    객체와 digest를 되찾을 수 있다. **어느 산출물이 유효한 binding인지는 판정
    산출물의 계약이므로 회차 적재 hook이 판단하고**, 여기서는 그 결과를 저장하거나
    지우기만 한다. v2 회차는 값이 없으므로 그대로 지워진다.
    """

    if config is None or digest is None:
        _clear_generation_metadata(run)
        return None, None
    # 뒤의 DB revision이 전용 불변 컬럼을 줄 수 있다. 있으면 쓰고, 현재 Run
    # 모델은 JSON projection으로 되돌아가 migration 중립을 유지한다.
    if hasattr(run, "generation_config_json"):
        run.generation_config_json = config
    if hasattr(run, "generation_config_digest"):
        run.generation_config_digest = digest
    current = run.counts_json if isinstance(run.counts_json, dict) else {}
    run.counts_json = {
        **current,
        "generation_config": config,
        "generation_config_digest": digest,
    }
    return config, digest


def _complete_run_ingest(
    session: Session,
    run: Run,
    directory: Path,
    *,
    extensions: Any,
    reports_path: Path | None,
    order_plans_count: int,
    selection: dict[str, Any] | None = None,
) -> IngestResult:
    """Run the ingest hooks, refresh counts, and commit one loaded run."""

    from ..extensions import RunIngestCounts

    run_id = run.id
    # 공고·발주계획·첨부 메타 적재가 끝났다. 판정·리뷰는 여기서부터 hook의
    # 몫이며 같은 session·같은 transaction에서 동기적으로 실행된다.
    if extensions.run_ingest_hook_count == 0:
        _record_warning(
            session,
            run_id,
            "warning",
            "judgment_ingest_skipped",
            "판정 적재를 제공하는 모듈이 없어 공고까지만 적재했습니다.",
            {"run_id": run_id},
        )
        hook_counts = RunIngestCounts()
    else:
        hook_counts = _run_ingested_hooks(
            session, run_id, directory, reports_root=reports_path
        )
    generation_config_result, generation_digest_result = _store_generation_metadata(
        run, hook_counts.generation_config, hook_counts.generation_config_digest
    )
    notices_count = _update_counts(
        session, run, judgments=hook_counts.judgments, reviews=hook_counts.reviews
    )
    session.commit()
    warnings = _warning_dicts(session, run_id)
    return IngestResult(
        run_id=run_id,
        notices=notices_count,
        order_plans=order_plans_count,
        judgments=hook_counts.judgments,
        reviews=hook_counts.reviews,
        generation_config=generation_config_result,
        generation_config_digest=generation_digest_result,
        warnings=warnings,
        selection=selection,
    )


def ingest_run(
    run_directory: str | Path,
    session: Session | None = None,
    *,
    reports_root: str | Path | None = None,
    policy_path: str | Path | None = None,
    binding_path: str | Path | None = None,
    selection: IngestSelection = "validation",
) -> IngestResult:
    """Ingest one run directory.

    공고·발주계획·첨부 메타까지가 lifecycle의 몫이다. 판정·리뷰와 C-2 선별 결과는
    등록된 회차 적재 hook이 **같은 transaction 안에서** 이어서 적재하고, 응답의
    판정 관련 건수는 그 hook이 돌려준 값으로 채운다(명세 §6.2). 등록된 hook이
    없으면 그 건수는 0이고 경고 한 줄이 남는다.

    ``selection``이 무엇을 공고로 적재할지 정한다.

    - ``"validation"``(기본): 검증 표본(`validation-set.json`)이나 C-1 입력
      (`screening-input.json`)의 공고만 적재한다. 유일한 파일 단위 중단은 검증
      표본을 읽지 못하는 경우다(ADR-003). 발주계획은 전량 적재한다.
    - ``"collection"``: 표본이 없어도 오류가 아니다. `collected-order-plans.json`·
      `collected-notices.json`의 **모든** 레코드를 수집 색인에 한 행씩 남기고,
      spec §2.2 선별 규칙(발주계획 전량 → SW사업대상 사전규격 → 추적·SW 관련
      입찰공고)에 맞는 레코드만 같은 `_upsert_notice` 경로로 적재한다. 원천별
      수집·사유별 선별·제외 건수는 `IngestResult.selection`과
      `run.counts_json["selection"]`에 남는다. 같은 회차 재실행은 색인 unique와 관측
      snapshot 검사로 no-op이다.

    개별 공고의 오류는 기록하되 다른 공고의 적재를 막지 않는다.
    """

    # lifecycle 공개 표면(`app.lifecycle`)은 이 파일을 다시 import하므로 모듈
    # 최상단에서 가져오면 순환이 된다. 확장점 모듈만 함수 안에서 가져온다.
    from ..extensions import extension_registry

    if selection not in INGEST_SELECTIONS:
        raise ValueError(f"selection must be one of {INGEST_SELECTIONS}")
    owns_session = session is None
    if owns_session:
        from ...core.db import SessionFactory

        session = SessionFactory()
    assert session is not None
    extensions = extension_registry()
    directory = Path(run_directory).resolve()
    reports_path = Path(reports_root) if reports_root is not None else None
    validation_path = directory / "validation-set.json"
    screening_input_path = directory / "screening-input.json"
    collection_path = directory / COLLECTION_FILE
    order_plan_path = directory / ORDER_PLAN_FILE

    validation_raw = _read_optional_json(validation_path)
    screening_input_present, screening_input_raw, screening_input_invalid = _read_screening_input(
        screening_input_path
    )
    screening_raw = _read_optional_json(directory / "screening-results.json")
    decisions_raw = _read_optional_json(directory / "screening-decisions.json")
    collection_raw = _read_optional_json(collection_path)
    order_plan_raw = _read_optional_json(order_plan_path)
    order_plan_only = (
        order_plan_raw is not None
        and validation_raw is None
        and screening_input_raw is None
        and collection_raw is None
    )
    metadata_raws = [
        screening_raw,
        decisions_raw,
        screening_input_raw,
        validation_raw,
        collection_raw,
        order_plan_raw,
    ]
    window_from, window_to, timezone_name = _source_window(metadata_raws)
    generated_at = _first_generated_at(
        metadata_raws,
        validation_path if validation_path.exists() else directory,
        timezone_name,
    )
    screening_basis = None
    for raw in metadata_raws:
        if raw and not is_blank(raw.get("screening_basis")):
            screening_basis = raw["screening_basis"]
            break
    run_id = deterministic_run_id(directory.name, generated_at)

    try:
        # 공고를 읽기 전에 디렉터리를 등록된 hook에 보여 준다. 어느 hook이 "이건
        # 내 전용 결과이며 source run은 X"라고 답하면 Run 확인만 한 뒤 그 hook의
        # 적재를 부르고 공고 적재를 건너뛴다. 감지 규칙은 그 모듈 안에 있으므로,
        # 제공자가 없으면 같은 디렉터리가 일반 회차로 처리된다(§6.2).
        claim = extensions.claim_run_directory(directory)
        if claim is not None:
            if session.get(Run, claim.source_run_id) is None and claim.source_run_id == run_id:
                _upsert_run(
                    session,
                    run_id,
                    directory,
                    window_from,
                    window_to,
                    timezone_name,
                    generated_at,
                    screening_basis,
                )
            counts = claim.load(
                session,
                directory,
                policy_path=Path(policy_path) if policy_path is not None else None,
                binding_path=Path(binding_path) if binding_path is not None else None,
            )
            session.commit()
            return IngestResult(
                run_id=claim.source_run_id,
                order_plans=counts.order_plans,
                screening_executions=counts.screening_executions,
                screening_attempts=counts.screening_attempts,
                screening_results=counts.screening_results,
                screening_artifacts=counts.screening_artifacts,
                screening_feedback=counts.screening_feedback,
            )

        run = _upsert_run(
            session,
            run_id,
            directory,
            window_from,
            window_to,
            timezone_name,
            generated_at,
            screening_basis,
        )
        if selection == "collection":
            order_plans_count, selection_counts = _load_collection_run(
                session,
                run,
                directory,
                order_plan_raw=order_plan_raw,
                order_plan_path=order_plan_path,
                collection_raw=collection_raw,
                collection_path=collection_path,
                timezone_name=timezone_name,
            )
            current = run.counts_json if isinstance(run.counts_json, dict) else {}
            run.counts_json = {**current, "selection": selection_counts}
            return _complete_run_ingest(
                session,
                run,
                directory,
                extensions=extensions,
                reports_path=reports_path,
                order_plans_count=order_plans_count,
                selection=selection_counts,
            )
        order_plans_count = 0
        if order_plan_raw is not None:
            order_plans_count = _load_order_plans(
                session,
                run_id,
                order_plan_raw,
                timezone_name,
                str(order_plan_path),
            )
        if screening_input_present and screening_input_invalid is not None:
            _record_warning(
                session,
                run_id,
                "error",
                "screening_input_invalid",
                "screening-input.json을 읽거나 canonical 계약으로 검증하지 못했습니다.",
                {"file": str(screening_input_path), "reason": screening_input_invalid},
            )
            # A present-but-invalid v3 input is a hard projection boundary;
            # do not let validation-set data repopulate its candidate rows.
            notices: dict[str, Notice] = {}
        elif (
            validation_raw is None
            and not screening_input_present
            and not order_plan_only
        ):
            _record_warning(
                session,
                run_id,
                "error",
                "validation_missing",
                "validation-set.json이 없어 회차 적재를 중단했습니다.",
                {"file": str(validation_path)},
            )
            # A collect-only execution is still a useful, visible snapshot.
            # Keep its collection totals even though the 40-notice screen
            # snapshot cannot be loaded until the sample stage runs.
            if collection_raw is not None:
                _load_collection_stats(session, run_id, collection_raw, str(collection_path), run)
            _run_ingested_hooks(session, run_id, directory)
            _update_counts(session, run)
            session.commit()
            warnings = _warning_dicts(session, run_id)
            return IngestResult(
                run_id=run_id,
                order_plans=order_plans_count,
                warnings=warnings,
            )

        # A frozen screening input is the identity authority for a v3
        # execution.  The validation set remains an immutable source artifact
        # but is not allowed to add sample-only Notice rows to the published
        # replacement.  Historical runs without screening-input retain the
        # validation-set projection.
        if screening_input_present and screening_input_invalid is not None:
            # Already recorded above.  Keep the projection empty and avoid
            # parsing validation-set notices as a fallback.
            notices = {}
        elif screening_input_raw is not None:
            notices = _load_screening_input_notices(
                session,
                run_id,
                screening_input_raw,
                timezone_name,
                str(screening_input_path),
            )
        elif validation_raw is not None:
            notices = _load_validation_notices(
                session, run_id, validation_raw, timezone_name, str(validation_path)
            )
        else:
            notices = {}
        if (
            not notices
            and validation_raw is not None
            and not isinstance(validation_raw.get("notices"), list)
            and not isinstance(screening_input_raw, dict)
        ):
            # The detailed warning was recorded above; this branch only keeps
            # the stop behavior explicit for callers reading the code.
            _update_counts(session, run)
            _run_ingested_hooks(session, run_id, directory)
            session.commit()
            warnings = _warning_dicts(session, run_id)
            return IngestResult(
                run_id=run_id,
                order_plans=order_plans_count,
                warnings=warnings,
            )

        if collection_raw is not None:
            _load_collection_stats(session, run_id, collection_raw, str(collection_path), run)

        return _complete_run_ingest(
            session,
            run,
            directory,
            extensions=extensions,
            reports_path=reports_path,
            order_plans_count=order_plans_count,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


# Friendly aliases for callers that prefer the noun used in the plan.
load_run = ingest_run
RunLoader = ingest_run
