"""Load a workflow run directory into the Step 1 SQLAlchemy schema."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    Attachment,
    Counterargument,
    Evidence,
    IngestWarning,
    Judgment,
    MatchedPerformance,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    OrderPlanObservation,
    Perspective,
    Review,
    Run,
    VerificationItem,
)
from .contracts import (
    CollectionArtifact,
    DecisionArtifact,
    JudgmentContract,
    NoticeContract,
    OrderPlanArtifact,
    OrderPlanContract,
    ScreeningArtifact,
    ScreeningResultContract,
    ValidationArtifact,
    artifact_version,
    is_blank,
    missing_judgment_fields,
    model_extra_fields,
)
from ..screening.generation_config import (
    GenerationConfigError,
    config_from_value,
    legacy_generation_config,
    validate_digest,
)
from ..services.opportunity_tracking import record_recheck_signal
from ..services.prespec_attachments import parse_attachment_key, refresh_fetch_eligibility


RUN_ID_RE = re.compile(r"^(?P<directory>.+)--(?P<generated>\d{8}T\d{6}(?:\.\d{1,6})?Z)$")
EXECUTION_ID_RE = re.compile(r"^scr-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DECIMAL_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
# The survey measured the ordinary orderPlanUntyNo shape as R + two digits +
# two uppercase letters + eight digits (13 characters).  Other observed
# values are retained verbatim as unresolved input; they are never guessed
# into this shape.
ORDER_PLAN_UNTY_NO_RE = re.compile(r"^R\d{2}[A-Z]{2}\d{8}$")
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


def _is_aware_iso(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None
DEFAULT_TIMEZONE = "Asia/Seoul"


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
            "warnings": self.warnings,
            "warning_counts": self.warning_counts,
        }
        if self.generation_config is not None and self.generation_config_digest is not None:
            result["generation_config"] = self.generation_config
            result["generation_config_digest"] = self.generation_config_digest
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


def deterministic_run_id(directory_name: str, generated_at: datetime) -> str:
    """Build the ADR-009 run identity from the directory and generated time."""

    aware = _ensure_aware(generated_at, DEFAULT_TIMEZONE).astimezone(timezone.utc)
    stamp = aware.strftime("%Y%m%dT%H%M%S")
    if aware.microsecond:
        stamp += f".{aware.microsecond:06d}".rstrip("0")
    return f"{directory_name}--{stamp}Z"


def parse_run_id(run_id: str) -> tuple[str, datetime] | None:
    """Parse a generated run id; useful to callers inspecting old snapshots."""

    match = RUN_ID_RE.match(run_id)
    if not match:
        return None
    value = match.group("generated").removesuffix("Z")
    try:
        generated = datetime.strptime(value, "%Y%m%dT%H%M%S.%f" if "." in value else "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return match.group("directory"), generated.replace(tzinfo=timezone.utc)


def _ensure_aware(value: datetime, timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return value.replace(tzinfo=zone)


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


def _as_judgment(value: Any) -> JudgmentContract:
    return value if isinstance(value, JudgmentContract) else JudgmentContract.model_validate(value)


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


def _generation_binding_matches(
    value: dict[str, Any],
    expected_config: dict[str, Any] | None,
    expected_digest: str | None,
    artifact_name: str,
) -> str | None:
    if expected_config is None or expected_digest is None:
        return None
    if (
        value.get("generation_config") != expected_config
        or value.get("generation_config_digest") != expected_digest
    ):
        return f"{artifact_name} generation binding does not match its source"
    return None


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
        key = str(notice.notice_key)
        # ``skills/bidops-collect`` emits ``pre:<bfSpecRgstNo>``.  Keep the
        # other historical spellings because the backend also ingests older
        # validation artifacts, but do not treat an arbitrary notice key as a
        # pre-spec number unless it is a pre-spec source row.
        for prefix in ("pre:", "pre_spec:", "prespec:", "pre-spec:", "spec:"):
            if key.startswith(prefix) and not is_blank(key[len(prefix):]):
                return key[len(prefix):]
        if ":" not in key:
            return key
    return None


def _find_pre_spec_notice(session: Session, pre_spec_no: str) -> Notice | None:
    """Resolve a pre-spec Notice by the external registration number."""

    source_types = ("pre_spec", "prespec", "pre-spec")
    keys = tuple(
        dict.fromkeys(
            (
                pre_spec_no,
                f"pre:{pre_spec_no}",
                f"pre_spec:{pre_spec_no}",
                f"prespec:{pre_spec_no}",
                f"pre-spec:{pre_spec_no}",
                f"spec:{pre_spec_no}",
            )
        )
    )
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


def _find_order_plan_by_bid_reference(session: Session, notice: Notice) -> OrderPlan | None:
    """Resolve one plan from the measured 16-character bid reference list.

    ``bidNtceNoList`` is the plan-side official key: each comma-separated
    value is the 13-character bid number followed by its three-character
    order.  This is an exact token comparison, not a substring search.  If
    more than one plan claims the same token, no plan is selected because an
    ambiguous official reference is not safe to auto-confirm.
    """

    if is_blank(notice.bid_no) or is_blank(notice.bid_ord):
        return None
    bid_reference = f"{notice.bid_no}{notice.bid_ord}"
    matches: list[OrderPlan] = []
    for candidate in session.scalars(
        select(OrderPlan).where(OrderPlan.bid_ntice_no_list.is_not(None))
    ):
        values = {
            item.strip()
            for item in str(candidate.bid_ntice_no_list).split(",")
            if item.strip()
        }
        if bid_reference in values:
            matches.append(candidate)
            if len(matches) > 1:
                return None
    return matches[0] if matches else None


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
                select(OpportunityLink).where(
                    OpportunityLink.order_plan_id == order_plan.id
                )
            ).all()
        )
    for notice_target in tuple(
        item for item in (notice, *additional_notices) if item is not None
    ):
        links.extend(
            session.scalars(
                select(OpportunityLink).where(
                    OpportunityLink.notice_id == notice_target.id
                )
            ).all()
        )
    unique: dict[int, Opportunity] = {}
    for link in links:
        if link.opportunity is not None:
            unique[link.opportunity.id] = link.opportunity
    return list(unique.values())


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
    stage: str,
    evidence_external_no: str,
    order_plan: OrderPlan | None = None,
    notice: Notice | None = None,
    evidence_bid_no: str | None = None,
) -> int:
    """Attach all deferred links for one exact official number to a target.

    If the arriving target already belongs to another opportunity, that
    opportunity and the waiting-link opportunities are merged here.  The
    merge is safe because this function is called only with the same official
    external number; it never uses name similarity.  Every link row is moved
    or updated in place, including rejected candidate links on the merged
    opportunities.
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
    primary = _merge_opportunities(session, list(opportunities))
    if primary is None:  # pragma: no cover - every waiting link has an owner.
        raise RuntimeError("deferred official link has no opportunity")

    attached = 0
    for link in waiting:
        link.opportunity = primary
        if order_plan is not None:
            link.order_plan = order_plan
            link.notice = None
        else:
            link.notice = notice
            link.order_plan = None
        if evidence_bid_no is not None and link.evidence_bid_no is None:
            link.evidence_bid_no = evidence_bid_no
        attached += 1
    session.flush()
    for link in waiting:
        # The deferred official row is now attached to its concrete lifecycle
        # record.  The service is deliberately the only path that can write
        # the system recheck columns; it leaves human tracking fields alone.
        record_recheck_signal(session, primary, link)
    return attached


def resolve_order_plan_opportunity_links(
    session: Session,
    order_plan: OrderPlan,
    *,
    evidence_bid_no: str | None = None,
) -> int:
    """Resolve waiting bid references when an order plan is ingested later.

    The current cumulative order-plan importer can call this after its
    canonical ``OrderPlan`` row is flushed.  Keeping the operation as a
    loader helper also lets offline/import callers resolve a plan without
    re-ingesting the originating bid notice.  When there is no waiting bid,
    the plan itself is still registered as an ``order_plan`` opportunity so
    every lifecycle record has exactly one owning opportunity.
    """

    if evidence_bid_no is None:
        evidence_bid_no = _first_order_plan_bid_no(order_plan.bid_ntice_no_list)
    # The target primary key is part of the exact target-opportunity lookup;
    # flush a newly-added plan before querying so ``id=None`` cannot broaden a
    # SQL ``IS NULL`` predicate to unrelated deferred links.
    if order_plan.id is None:
        session.flush()
    attached = _attach_waiting_official_links(
        session,
        stage="order_plan",
        evidence_external_no=order_plan.order_plan_unty_no,
        order_plan=order_plan,
        evidence_bid_no=evidence_bid_no,
    )
    if not _target_opportunities(session, order_plan=order_plan):
        opportunity = _ensure_opportunity(
            session,
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
    return attached


def _merge_opportunities(
    session: Session,
    opportunities: list[Opportunity],
) -> Opportunity | None:
    if not opportunities:
        return None
    # ``created_at`` is the closest persisted representation of first
    # registration when two independently-created opportunities are joined by
    # a later official bid key.  Preserve every link, including rejected
    # candidates, while moving the secondary rows to the retained identity.
    primary = min(
        opportunities,
        key=lambda item: (
            item.created_at or datetime.max.replace(tzinfo=timezone.utc),
            item.id,
        ),
    )
    moved_official_links: list[OpportunityLink] = []
    for secondary in opportunities:
        if secondary is primary:
            continue
        for link in list(secondary.links):
            # A targetless deferred link is signaled by the attachment path
            # after its target is filled.  Targetful official links that move
            # to an ended primary are already newly attached to the merged
            # result and are handled here.
            if (
                link.link_type == "official"
                and (link.order_plan_id is not None or link.notice_id is not None)
            ):
                moved_official_links.append(link)
            link.opportunity = primary
        session.delete(secondary)
    session.flush()
    if primary.tracking_status == "종료":
        for link in sorted(
            moved_official_links,
            key=lambda item: (
                item.created_at or datetime.min.replace(tzinfo=timezone.utc),
                item.id or 0,
            ),
        ):
            record_recheck_signal(session, primary, link)
    return primary


def _ensure_opportunity(
    session: Session,
    *,
    first_registered_stage: str,
    order_plan: OrderPlan | None = None,
    notice: Notice | None = None,
    additional_notices: tuple[Notice, ...] = (),
) -> Opportunity:
    existing = _merge_opportunities(
        session,
        _target_opportunities(
            session,
            order_plan=order_plan,
            notice=notice,
            additional_notices=additional_notices,
        ),
    )
    if existing is not None:
        return existing
    opportunity = Opportunity(first_registered_stage=first_registered_stage)
    session.add(opportunity)
    session.flush()
    return opportunity


def _ensure_official_link(
    session: Session,
    *,
    opportunity: Opportunity,
    stage: str,
    order_plan: OrderPlan | None = None,
    notice: Notice | None = None,
    evidence_external_no: str,
    evidence_bid_no: str | None = None,
) -> OpportunityLink:
    """Insert or resolve one official link while retaining its evidence.

    Passing neither target is intentional for a deferred upstream reference.
    In that case the exact external number identifies the waiting row; the
    later target-ingest path fills the target ID without creating a new
    opportunity.
    """

    if order_plan is not None and notice is not None:
        raise ValueError("an official link cannot target both plan and notice")
    if not is_blank(evidence_external_no):
        evidence_external_no = str(evidence_external_no).strip()

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
        was_targetless = existing.order_plan_id is None and existing.notice_id is None
        if order_plan is not None:
            existing.order_plan = order_plan
            existing.notice = None
        elif notice is not None:
            existing.notice = notice
            existing.order_plan = None
        if evidence_bid_no is not None and existing.evidence_bid_no is None:
            existing.evidence_bid_no = evidence_bid_no
        if was_targetless and (order_plan is not None or notice is not None):
            session.flush()
            record_recheck_signal(session, opportunity, existing)
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
    record_recheck_signal(session, opportunity, link)
    return link


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
    notice and links records that are already in the database.
    """

    contract = notice_contract
    if contract is None:
        contract = NoticeContract(
            notice_id=notice.notice_key,
            source_type=notice.source_type,
            lifecycle=notice.lifecycle_json,
            raw_source=notice.raw_source,
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
        order_plan = _find_order_plan_by_bid_reference(session, notice)
        if order_plan is not None:
            order_plan_reference = order_plan.order_plan_unty_no

    pre_spec: Notice | None = None
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

    source_type = (notice.source_type or "").strip().lower()
    is_pre_spec = source_type in {"pre_spec", "prespec", "pre-spec"}
    if is_pre_spec:
        # An independently collected pre-spec is a first registration point
        # when no earlier official relation is available.  Its own external
        # identity is an official record link, not a name-search candidate.
        own_pre_spec_no = _stored_pre_spec_number(notice) or notice.notice_key
        opportunity = _ensure_opportunity(
            session,
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
            stage="notice",
            evidence_external_no=own_pre_spec_no,
            notice=notice,
        )
        return

    # A target that arrived before this bid may itself have a deferred link.
    # Resolve that link by the same official number before collecting all
    # target opportunities for the current bid.
    if order_plan is not None:
        _attach_waiting_official_links(
            session,
            stage="order_plan",
            evidence_external_no=order_plan.order_plan_unty_no,
            order_plan=order_plan,
            evidence_bid_no=notice.bid_no,
        )
    if pre_spec is not None:
        _attach_waiting_official_links(
            session,
            stage="notice",
            evidence_external_no=pre_spec_no or pre_spec.notice_key,
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
        first_registered_stage=first_stage,
        order_plan=order_plan,
        notice=pre_spec,
        # A bid may already have a candidate relation or an independently
        # created opportunity.  Include only this exact notice in the identity
        # lookup; no title/name similarity is used for merging.
        additional_notices=(notice,),
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
        pre_spec_reference = pre_spec_no or pre_spec.notice_key
        _ensure_official_link(
            session,
            opportunity=opportunity,
            stage="notice",
            notice=pre_spec,
            evidence_external_no=pre_spec_reference,
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
    existing = session.scalar(
        select(Notice).where(Notice.notice_key == notice_key)
    )
    is_new = existing is None
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
    _upsert_attachments(session, existing, raw.get("attachments"))
    # Flush the canonical row before looking up its observation.  The same
    # external key is shared across runs; the observation, not a second Notice
    # row, records this run's sighting and field changes.
    session.flush()
    run = session.get(Run, run_id)
    if run is None:  # pragma: no cover - _upsert_run creates this boundary.
        raise ValueError(f"run not found while observing notice: {run_id}")
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
            )
        )
    elif changed_fields:
        prior = observation.changed_fields_json
        prior_fields = prior if isinstance(prior, list) else []
        observation.changed_fields_json = sorted(set(prior_fields) | set(changed_fields))
    # SessionFactory deliberately disables autoflush.  Flush the association
    # here so a malformed artifact containing the same notice key twice cannot
    # create two pending observation rows for the same notice/run pair.
    session.flush()
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
    existing = session.scalar(
        select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no)
    )
    is_new = existing is None
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
    run = session.get(Run, run_id)
    if run is None:  # pragma: no cover - _upsert_run creates this boundary.
        raise ValueError(f"run not found while observing order plan: {run_id}")
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
            )
        )
    elif changed_fields:
        prior = observation.changed_fields_json
        prior_fields = prior if isinstance(prior, list) else []
        observation.changed_fields_json = sorted(set(prior_fields) | set(changed_fields))
    session.flush()
    resolve_order_plan_opportunity_links(
        session,
        existing,
        evidence_bid_no=_first_order_plan_bid_no(existing.bid_ntice_no_list),
    )
    return existing


def _attachment_key(raw: dict[str, Any]) -> tuple[Any, Any]:
    return raw.get("name"), raw.get("url")


def _upsert_attachments(session: Session, notice: Notice, raw_attachments: Any) -> None:
    if not isinstance(raw_attachments, list):
        return
    existing = {_attachment_key({"name": item.name, "url": item.url}): item for item in notice.attachments}
    seen: set[tuple[Any, Any]] = set()
    for raw in raw_attachments:
        if not isinstance(raw, dict):
            continue
        key = _attachment_key(raw)
        seen.add(key)
        item = existing.get(key)
        if item is None:
            item = Attachment(notice=notice, origin="g2b")
            session.add(item)
        item.name = raw.get("name")
        item.url = raw.get("url")
        item.origin = raw.get("origin") or item.origin or "g2b"
        item.file_ext = raw.get("file_ext")
        item.size_bytes = raw.get("size_bytes")
        item.stored_path = raw.get("stored_path")
        item.extract_status = raw.get("extract_status")
        if notice.source_type == "pre_spec":
            # The collector contract remains the immutable {name, url} pair.
            # Only the exact, measured G2B URL shape becomes provenance; every
            # other shape is deliberately ineligible for provider fetching.
            attachment_key = parse_attachment_key(item.source_url)
            if attachment_key is None:
                item.source_system = None
                item.source_attachment_key = None
            else:
                item.source_system = "g2b"
                item.source_attachment_key = attachment_key
    for key, item in existing.items():
        if key not in seen:
            session.delete(item)


def _clear_judgment(session: Session, judgment: Judgment) -> None:
    """Replace child rows on re-ingest without changing the judgment identity."""

    for perspective in list(judgment.perspectives):
        for evidence in list(perspective.evidence):
            session.delete(evidence)
        session.delete(perspective)
    for child in list(judgment.counterarguments):
        session.delete(child)
    for child in list(judgment.verification_items):
        session.delete(child)
    for child in list(judgment.matched_performances):
        session.delete(child)
    session.flush()


def _load_judgment(
    session: Session,
    run_id: str,
    notice: Notice,
    judgment: JudgmentContract,
    raw: dict[str, Any],
    schema_version: str,
    source_file: str,
) -> Judgment | None:
    judgment_notice_id = raw.get("notice_id") or notice.notice_key
    missing = missing_judgment_fields(judgment, judgment_notice_id)
    if missing:
        _record_warning(
            session,
            run_id,
            "error",
            "judgment_required_field_missing",
            "필수 판정 필드가 없어 해당 판정을 적재하지 않았습니다.",
            {"notice_id": notice.notice_key, "fields": missing, "file": source_file},
        )
        return None

    extra_fields = model_extra_fields(judgment, "judgment")
    _record_unknown_fields(session, run_id, extra_fields, source_file)

    perspectives = _raw_list(raw.get("perspectives"))
    counterarguments = _raw_list(raw.get("counterarguments"))
    verification_items = _raw_list(raw.get("verification_items"))
    if len(perspectives) < 5:
        _record_warning(
            session,
            run_id,
            "warning",
            "perspectives_below_contract",
            f"관점이 계약 기준보다 적습니다: {len(perspectives)}개",
            {
                "notice_id": notice.notice_key,
                "actual_count": len(perspectives),
                "schema_version": schema_version,
            },
        )
    if not counterarguments:
        _record_warning(
            session,
            run_id,
            "warning",
            "counterarguments_missing",
            "반론이 없어 빈 목록으로 적재했습니다.",
            {"notice_id": notice.notice_key, "schema_version": schema_version},
        )
    if not verification_items:
        _record_warning(
            session,
            run_id,
            "warning",
            "verification_items_missing",
            "확인 항목이 없어 빈 목록으로 적재했습니다.",
            {"notice_id": notice.notice_key, "schema_version": schema_version},
        )

    current = notice.judgment
    if current is None:
        current = Judgment(notice=notice)
        session.add(current)
    else:
        _clear_judgment(session, current)
    current.schema_version = schema_version
    current.grade = judgment.grade
    current.readiness = judgment.readiness
    current.primary_focus = judgment.primary_focus
    current.exclusion_category = judgment.exclusion_category
    current.summary = judgment.summary
    current.next_action = judgment.next_action

    for position, raw_perspective in enumerate(perspectives, start=1):
        if not isinstance(raw_perspective, dict):
            _record_warning(
                session,
                run_id,
                "warning",
                "perspective_invalid",
                "관점 항목이 객체가 아니어서 건너뛰었습니다.",
                {"notice_id": notice.notice_key, "position": position},
            )
            continue
        perspective_model = raw_perspective
        perspective = Perspective(
            judgment=current,
            position=raw_perspective.get("position", position),
            name=raw_perspective.get("name"),
            assessment=raw_perspective.get("assessment"),
            reason=raw_perspective.get("reason"),
        )
        session.add(perspective)
        _record_unknown_fields(
            session,
            run_id,
            model_extra_fields(
                # Re-validation makes nested unknown fields visible even when
                # the parent union selected a raw mapping.
                _model_or_none(perspective_model, "perspective"),
                "perspective",
            ),
            source_file,
        )
        for raw_evidence in _raw_list(raw_perspective.get("evidence")):
            if not isinstance(raw_evidence, dict):
                continue
            evidence = Evidence(
                perspective=perspective,
                source=raw_evidence.get("source"),
                status=raw_evidence.get("status"),
                fact=raw_evidence.get("fact"),
            )
            session.add(evidence)
            _record_unknown_fields(
                session,
                run_id,
                _model_extra_from_raw(raw_evidence, {"source", "status", "fact"}, "perspective.evidence"),
                source_file,
            )

    for position, raw_counterargument in enumerate(counterarguments, start=1):
        if isinstance(raw_counterargument, str):
            text = raw_counterargument
            counter_position = position
        elif isinstance(raw_counterargument, dict):
            text = raw_counterargument.get("text")
            counter_position = raw_counterargument.get("position", position)
            _record_unknown_fields(
                session,
                run_id,
                _model_extra_from_raw(raw_counterargument, {"position", "text"}, "judgment.counterarguments"),
                source_file,
            )
        else:
            text = None
            counter_position = position
        session.add(
            Counterargument(judgment=current, position=counter_position, text=text)
        )

    for raw_item in verification_items:
        if not isinstance(raw_item, dict):
            continue
        session.add(
            VerificationItem(
                judgment=current,
                item=raw_item.get("item"),
                why=raw_item.get("why"),
                blocking=bool(raw_item.get("blocking", False)),
                status=raw_item.get("status"),
            )
        )
        _record_unknown_fields(
            session,
            run_id,
            _model_extra_from_raw(
                raw_item, {"item", "why", "blocking", "status"}, "judgment.verification_items"
            ),
            source_file,
        )

    for raw_performance in _raw_list(raw.get("matched_performances")):
        if not isinstance(raw_performance, dict):
            continue
        session.add(
            MatchedPerformance(
                judgment=current,
                name=raw_performance.get("name") or raw_performance.get("project_name"),
                match_reason=raw_performance.get("match_reason"),
                mismatch_or_limit=raw_performance.get("mismatch_or_limit"),
                source=raw_performance.get("source") or raw_performance.get("source_page"),
                status=raw_performance.get("status") or raw_performance.get("legal_qualification_status"),
            )
        )
        _record_unknown_fields(
            session,
            run_id,
            _model_extra_from_raw(
                raw_performance,
                {
                    "name",
                    "project_name",
                    "match_reason",
                    "mismatch_or_limit",
                    "source",
                    "source_page",
                    "similarity",
                    "common_fragment",
                    "status",
                    "legal_qualification_status",
                },
                "judgment.matched_performances",
            ),
            source_file,
        )
    return current


def _model_or_none(raw: Any, kind: str) -> BaseModel:
    from .contracts import PerspectiveContract

    if kind == "perspective":
        return PerspectiveContract.model_validate(raw)
    return PerspectiveContract.model_validate(raw)


def _model_extra_from_raw(raw: dict[str, Any], known: set[str], prefix: str) -> list[str]:
    return [f"{prefix}.{key}" for key in raw if key not in known]


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
    expected_keys = set(_SCREENING_COMMON_NOTICE_KEYS) | {"judgment_mode", "carry_over_from", "rejudge_reason"}
    seen: set[str] = set()
    for notice in notices:
        if not isinstance(notice, dict) or set(notice) != expected_keys:
            return "notice fields are not exact"
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
            "lifecycle": {"pre_spec_no", "re_notice", "changed_at", "change_reason", "unified_notice_no", "previous_failed_notice_no"},
        }
        for key, keys in nested.items():
            actual_keys = set(common[key]) if isinstance(common[key], dict) else set()
            allowed_keys = keys | {"order_plan_no"} if key == "lifecycle" else keys
            if (
                not isinstance(common[key], dict)
                or (actual_keys != keys and actual_keys != allowed_keys)
            ):
                return "notice nested fields are not exact"
            if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in common[key].values() if key != "region_limit" or value != common[key].get("joint_contract_regions")):
                return "notice nested string is invalid"
        qualification = common["qualification_flags"]
        qualification_keys = {"participation_limited", "industry_limited", "information_business", "general_service", "service_division", "joint_contract_method", "performance_restricted_competition", "pq_evaluation", "technical_evaluation", "technical_evaluation_rate", "successful_bid_method"}
        if not isinstance(qualification, dict) or (qualification and set(qualification) != qualification_keys):
            return "qualification flags are invalid"
        if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in qualification.values()):
            return "qualification flags are invalid"
        lifecycle_changed = common["lifecycle"].get("changed_at")
        if lifecycle_changed is not None and not _is_aware_iso(lifecycle_changed):
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


_DECISIONS_V3_KEYS = {
    "schema_version", "execution_id", "run_id", "generated_at", "screening_basis",
    "model_name", "model_digest", "prompt_version", "policy_version",
    "company_profile_version", "company_profile_digest", "judgments",
    "generation_config", "generation_config_digest",
}
_SCREENING_V3_KEYS = {
    "schema_version", "execution_id", "generated_at", "screening_basis",
    "source_window", "model_name", "model_digest", "prompt_version",
    "policy_version", "company_profile_version", "company_profile_digest",
    "generation_config", "generation_config_digest", "candidate_count",
    "result_count", "failure_count", "partial_artifact", "failure_artifact",
    "results",
}


def _v3_generation_artifact_error(
    raw: Any, artifact_name: str, expected_keys: set[str]
) -> str | None:
    """Validate top-level v3 identity and the generation binding.

    Nested judgment validation remains deliberately owned by the producer
    merge contract; ingest still refuses an artifact whose frozen generation
    metadata is malformed or cannot be bound to its sibling artifact.
    """

    if not isinstance(raw, dict):
        return f"{artifact_name} top-level value is not an object"
    missing_keys = expected_keys - set(raw)
    if missing_keys:
        return f"{artifact_name} top-level fields are missing"
    if raw.get("schema_version") not in V3_GENERATION_SCHEMAS:
        return f"{artifact_name} schema version is invalid"
    if not isinstance(raw.get("execution_id"), str) or EXECUTION_ID_RE.fullmatch(raw["execution_id"]) is None:
        return f"{artifact_name} execution id is invalid"
    for key in ("run_id", "prompt_version", "policy_version", "company_profile_version"):
        if key in raw and (not isinstance(raw.get(key), str) or not raw[key].strip()):
            return f"{artifact_name} identity field is invalid"
    run_id = raw.get("run_id")
    if isinstance(run_id, str) and ("/" in run_id or "\\" in run_id or Path(run_id).name != run_id):
        return f"{artifact_name} run identity is unsafe"
    generated = raw.get("generated_at")
    if not _is_aware_iso(generated):
        return f"{artifact_name} generated_at is invalid"
    profile_digest = raw.get("company_profile_digest")
    if not isinstance(profile_digest, str) or SHA256_RE.fullmatch(profile_digest) is None:
        return f"{artifact_name} profile digest is invalid"
    if raw.get("company_profile_version") != f"company-profile.sha256:{profile_digest}":
        return f"{artifact_name} profile identity is invalid"
    if not isinstance(raw.get("model_name"), str) or not raw["model_name"].strip():
        return f"{artifact_name} model name is invalid"
    if not isinstance(raw.get("model_digest"), str) or SHA256_RE.fullmatch(raw["model_digest"]) is None:
        return f"{artifact_name} model digest is invalid"
    try:
        config = config_from_value(raw.get("generation_config"))
        validate_digest(config, raw.get("generation_config_digest"))
    except (GenerationConfigError, AttributeError, TypeError):
        return f"{artifact_name} generation binding is invalid"
    if raw.get("generation_config") != config.canonical_value():
        return f"{artifact_name} generation config is not canonical"
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
    input_keys = set(_SCREENING_COMMON_NOTICE_KEYS) | {"judgment_mode", "carry_over_from", "rejudge_reason"}
    for index, raw_notice in enumerate(notices_raw):
        if not isinstance(raw_notice, dict) or set(raw_notice) != input_keys:
            return {}
        notice_model = NoticeContract.model_validate({key: raw_notice[key] for key in _SCREENING_COMMON_NOTICE_KEYS})
        item = _upsert_notice(session, run_id, notice_model, {key: raw_notice[key] for key in _SCREENING_COMMON_NOTICE_KEYS}, timezone_name)
        if item is not None:
            notices[item.notice_key] = item
    session.flush()
    return notices


def _remove_judgments_without_screening(session: Session, notices: dict[str, Notice]) -> None:
    # ``Notice`` is cumulative as of ADR-0026.  Before that cutover this
    # helper removed the current run's projection when screening output was
    # absent or invalid; the same operation now destroys a prior run's only
    # canonical Judgment.  A failed or incomplete observation must not erase
    # the database-authoritative result that is already attached to the
    # external notice identity.  The warning at the caller still records that
    # this run produced no new judgment.
    return None


def _load_screening_results(
    session: Session,
    run_id: str,
    notices: dict[str, Notice],
    raw: dict[str, Any],
    source_file: str,
    schema_version: str,
    *,
    expected_generation_config: dict[str, Any] | None = None,
    expected_generation_digest: str | None = None,
) -> int:
    if raw.get("schema_version") == "bidops.screening.v3":
        generation_error = _v3_generation_artifact_error(
            raw, "screening-results.json", _SCREENING_V3_KEYS
        )
        if generation_error is None:
            generation_error = _generation_binding_matches(
                raw,
                expected_generation_config,
                expected_generation_digest,
                "screening-results.json",
            )
        if generation_error is not None:
            _record_warning(
                session,
                run_id,
                "error",
                "screening_results_invalid",
                "screening-results.json generation 계약을 해석하지 못했습니다.",
                {"file": source_file, "reason": generation_error},
            )
            _remove_judgments_without_screening(session, notices)
            return 0
    try:
        artifact = ScreeningArtifact.model_validate(raw)
    except ValidationError as exc:
        _record_warning(
            session,
            run_id,
            "error",
            "screening_results_invalid",
            "screening-results.json 계약을 해석하지 못했습니다.",
            {"file": source_file, "error": str(exc)},
        )
        _remove_judgments_without_screening(session, notices)
        return 0
    _record_unknown_fields(session, run_id, _artifact_unknown_fields(raw, artifact), source_file)
    raw_results = raw.get("results")
    if not isinstance(raw_results, list):
        _record_warning(
            session,
            run_id,
            "error",
            "screening_results_missing",
            "screening-results.json에 results 목록이 없습니다.",
            {"file": source_file},
        )
        _remove_judgments_without_screening(session, notices)
        return 0

    loaded_ids: set[str] = set()
    loaded = 0
    for index, raw_result in enumerate(raw_results):
        if not isinstance(raw_result, dict):
            _record_warning(
                session,
                run_id,
                "error",
                "screening_result_invalid",
                "판정 결과 항목이 객체가 아니어서 건너뛰었습니다.",
                {"file": source_file, "index": index},
            )
            continue
        try:
            result_model = ScreeningResultContract.model_validate(raw_result)
            _record_unknown_fields(
                session,
                run_id,
                _model_extra_from_raw(raw_result, {"notice", "judgment"}, f"result[{index}]"),
                source_file,
            )
            if isinstance(raw_result.get("notice"), dict):
                screening_notice_model = NoticeContract.model_validate(raw_result["notice"])
                _record_unknown_fields(
                    session,
                    run_id,
                    model_extra_fields(screening_notice_model, f"result[{index}].notice"),
                    source_file,
                )
        except ValidationError as exc:
            _record_warning(
                session,
                run_id,
                "warning",
                "screening_result_invalid",
                "screening 결과의 중첩 필드를 모두 해석하지 못했지만 판정 적재를 계속합니다.",
                {"file": source_file, "index": index, "error": str(exc)},
            )
        raw_notice = raw_result.get("notice")
        raw_judgment = raw_result.get("judgment")
        notice_id = raw_notice.get("notice_id") if isinstance(raw_notice, dict) else None
        if is_blank(notice_id) and isinstance(raw_judgment, dict):
            notice_id = raw_judgment.get("notice_id")
        if is_blank(notice_id):
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_required_field_missing",
                "notice_id가 없어 해당 판정을 적재하지 않았습니다.",
                {"file": source_file, "index": index, "fields": ["notice_id"]},
            )
            continue
        notice = notices.get(str(notice_id))
        if notice is None:
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_notice_not_found",
                "검증 표본에 없는 공고의 판정을 적재하지 않았습니다.",
                {"notice_id": str(notice_id), "file": source_file},
            )
            continue
        if not isinstance(raw_judgment, dict):
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_missing",
                "판정 객체가 없어 해당 판정을 적재하지 않았습니다.",
                {"notice_id": str(notice_id), "file": source_file},
            )
            continue
        try:
            judgment_model = _as_judgment(raw_judgment)
        except ValidationError as exc:
            _record_warning(
                session,
                run_id,
                "error",
                "judgment_invalid",
                "판정 항목 계약을 해석하지 못해 건너뛰었습니다.",
                {"notice_id": str(notice_id), "file": source_file, "error": str(exc)},
            )
            continue
        judgment = _load_judgment(
            session,
            run_id,
            notice,
            judgment_model,
            raw_judgment,
            schema_version,
            source_file,
        )
        if judgment is not None:
            loaded += 1
            loaded_ids.add(notice.notice_key)

    for notice_key, notice in notices.items():
        if notice_key not in loaded_ids and notice.judgment is not None:
            session.delete(notice.judgment)
    session.flush()
    return loaded


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


def _feedback_path(run_directory: Path, reports_root: Path | None) -> Path:
    root = reports_root if reports_root is not None else run_directory.parent.parent / "reports"
    return root / run_directory.name / "review-feedback.yaml"


def _load_feedback(
    session: Session,
    run: Run,
    notices: dict[str, Notice],
    run_directory: Path,
    reports_root: Path | None,
) -> int:
    from .feedback import load_feedback

    return load_feedback(session, run, notices, _feedback_path(run_directory, reports_root))


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


def _refresh_prespec_attachment_eligibility(session: Session, run_id: str) -> None:
    """Re-evaluate this run's pre-spec attachments without breaking ingest."""

    notice_ids = list(
        session.scalars(
            select(Notice.id)
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(
                NoticeObservation.run_id == run_id,
                Notice.source_type == "pre_spec",
            )
            .distinct()
        ).all()
    )
    if not notice_ids:
        return
    try:
        # Keep a failed refresh inside a savepoint so an IntegrityError or
        # dialect issue cannot roll back the surrounding ingest transaction.
        with session.begin_nested():
            refresh_fetch_eligibility(session, notice_ids=notice_ids)
    except Exception:
        _record_warning(
            session,
            run_id,
            "warning",
            "attachment_eligibility_refresh_failed",
            "사전규격 첨부 자격 재평가를 완료하지 못했습니다.",
            {"notice_count": len(notice_ids)},
        )


def _update_counts(session: Session, run: Run) -> tuple[int, int, int]:
    notices = int(
        session.scalar(
            select(func.count(func.distinct(Notice.id)))
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(NoticeObservation.run_id == run.id)
        )
        or 0
    )
    judgments = int(
        session.scalar(
            select(func.count(func.distinct(Judgment.id)))
            .join(Notice, Judgment.notice_pk == Notice.id)
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(NoticeObservation.run_id == run.id)
        )
        or 0
    )
    reviews = int(
        session.scalar(
            select(func.count(func.distinct(Review.id)))
            .join(Notice, Review.notice_pk == Notice.id)
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
    return notices, judgments, reviews


def _persist_generation_metadata(
    run: Run,
    *artifacts: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Keep the normalized v3 binding in the run projection.

    ``Run`` predates generation binding and its JSON counts projection is the
    compatibility storage available without changing the DB model.  The
    public counts schema ignores these metadata keys, while re-ingest and
    callers that need a round-trip binding can recover the exact object and
    digest.  v2 artifacts intentionally leave this untouched.
    """

    config: dict[str, Any] | None = None
    digest: str | None = None
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("schema_version") not in V3_GENERATION_SCHEMAS:
            continue
        candidate = artifact.get("generation_config")
        candidate_digest = artifact.get("generation_config_digest")
        if isinstance(candidate, dict) and isinstance(candidate_digest, str):
            if config is None:
                config, digest = candidate, candidate_digest
            elif config != candidate or digest != candidate_digest:
                # Cross-artifact mismatch is handled by the strict loader;
                # never store a mixed binding under an apparently valid run.
                _clear_generation_metadata(run)
                return None, None
    if config is not None and digest is not None:
        # A later DB revision may provide dedicated immutable columns.  Use
        # them when present; the current Run model falls back to its JSON
        # projection so this compatibility layer remains migration-neutral.
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
    else:
        _clear_generation_metadata(run)
    return config, digest


def _clear_generation_metadata(run: Run) -> None:
    current = run.counts_json if isinstance(run.counts_json, dict) else {}
    if "generation_config" in current or "generation_config_digest" in current:
        run.counts_json = {
            key: value
            for key, value in current.items()
            if key not in {"generation_config", "generation_config_digest"}
        }


def ingest_run(
    run_directory: str | Path,
    session: Session | None = None,
    *,
    reports_root: str | Path | None = None,
) -> IngestResult:
    """Ingest one run directory.

    Errors in an individual judgment are recorded and do not prevent the
    other notices from becoming visible.  The only file-level hard stop is a
    missing or unreadable validation set, as required by ADR-003.
    """

    owns_session = session is None
    if owns_session:
        from ..db import SessionFactory

        session = SessionFactory()
    assert session is not None
    directory = Path(run_directory).resolve()
    reports_path = Path(reports_root) if reports_root is not None else None
    validation_path = directory / "validation-set.json"
    screening_input_path = directory / "screening-input.json"
    screening_path = directory / "screening-results.json"
    decisions_path = directory / "screening-decisions.json"
    collection_path = directory / "collected-notices.json"
    order_plan_path = directory / ORDER_PLAN_FILE

    validation_raw = _read_optional_json(validation_path)
    screening_input_present, screening_input_raw, screening_input_invalid = _read_screening_input(screening_input_path)
    screening_raw = _read_optional_json(screening_path)
    decisions_raw = _read_optional_json(decisions_path)
    collection_raw = _read_optional_json(collection_path)
    order_plan_raw = _read_optional_json(order_plan_path)
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
        order_plans_count = 0
        if order_plan_raw is not None:
            order_plans_count = _load_order_plans(
                session,
                run_id,
                order_plan_raw,
                timezone_name,
                str(order_plan_path),
            )
        decisions_generation_invalid = False
        screening_generation_invalid = False
        if isinstance(decisions_raw, dict) and decisions_raw.get("schema_version") in V3_GENERATION_SCHEMAS:
            decisions_raw, generation_error = _normalize_v3_generation_binding(
                decisions_raw, "screening-decisions.json"
            )
            if generation_error is not None or decisions_raw is None:
                decisions_generation_invalid = True
                _record_warning(
                    session,
                    run_id,
                    "error",
                    "decisions_invalid",
                    "screening-decisions.json generation 계약을 해석하지 못했습니다.",
                    {"file": str(decisions_path), "reason": generation_error or "invalid"},
                )
                decisions_raw = None
        if isinstance(screening_raw, dict) and screening_raw.get("schema_version") in V3_GENERATION_SCHEMAS:
            screening_raw, generation_error = _normalize_v3_generation_binding(
                screening_raw, "screening-results.json"
            )
            if generation_error is not None or screening_raw is None:
                screening_generation_invalid = True
                _record_warning(
                    session,
                    run_id,
                    "error",
                    "screening_results_invalid",
                    "screening-results.json generation 계약을 해석하지 못했습니다.",
                    {"file": str(screening_path), "reason": generation_error or "invalid"},
                )
                screening_raw = None
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
        elif validation_raw is None and not screening_input_present:
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
            _refresh_prespec_attachment_eligibility(session, run_id)
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
                session, run_id, screening_input_raw, timezone_name, str(screening_input_path)
            )
        elif validation_raw is not None:
            notices = _load_validation_notices(
                session, run_id, validation_raw, timezone_name, str(validation_path)
            )
        if not notices and validation_raw is not None and not isinstance(validation_raw.get("notices"), list) and not isinstance(screening_input_raw, dict):
            # The detailed warning was recorded above; this branch only keeps
            # the stop behavior explicit for callers reading the code.
            _update_counts(session, run)
            _refresh_prespec_attachment_eligibility(session, run_id)
            session.commit()
            warnings = _warning_dicts(session, run_id)
            return IngestResult(
                run_id=run_id,
                order_plans=order_plans_count,
                warnings=warnings,
            )

        decisions_schema = None
        if decisions_raw is not None:
            try:
                if decisions_raw.get("schema_version") == "bidops.decisions.v3":
                    generation_error = _v3_generation_artifact_error(
                        decisions_raw, "screening-decisions.json", _DECISIONS_V3_KEYS
                    )
                    input_config = (
                        screening_input_raw.get("generation_config")
                        if isinstance(screening_input_raw, dict)
                        else None
                    )
                    input_digest = (
                        screening_input_raw.get("generation_config_digest")
                        if isinstance(screening_input_raw, dict)
                        else None
                    )
                    if generation_error is None:
                        generation_error = _generation_binding_matches(
                            decisions_raw,
                            input_config,
                            input_digest,
                            "screening-decisions.json",
                        )
                    if generation_error is not None:
                        decisions_generation_invalid = True
                        _record_warning(
                            session,
                            run_id,
                            "error",
                            "decisions_invalid",
                            "screening-decisions.json generation 계약을 해석하지 못했습니다.",
                            {"file": str(decisions_path), "reason": generation_error},
                        )
                        decisions_raw = None
                        raise ValueError("invalid v3 generation binding")
                decisions_model = DecisionArtifact.model_validate(decisions_raw)
                _record_unknown_fields(
                    session,
                    run_id,
                    _artifact_unknown_fields(decisions_raw, decisions_model),
                    str(decisions_path),
                )
                decisions_schema = artifact_version(decisions_model) or decisions_raw.get("schema_version")
            except ValidationError as exc:
                _record_warning(
                    session,
                    run_id,
                    "error",
                    "decisions_invalid",
                    "screening-decisions.json 계약을 해석하지 못했습니다.",
                    {"file": str(decisions_path), "error": str(exc)},
                )
            except ValueError:
                # The safe generation-specific warning was already recorded.
                pass
        if decisions_schema == "bidops.decisions.v1":
            _record_warning(
                session,
                run_id,
                "warning",
                "decisions_schema_gap",
                "계약 v2가 요구되지만 decisions.v1 산출물을 적재했습니다.",
                {"actual": decisions_schema, "expected": "bidops.decisions.v2"},
            )
        if screening_raw is None:
            _record_warning(
                session,
                run_id,
                "warning",
                "screening_results_missing",
                "screening-results.json이 없어 공고만 적재했습니다.",
                {"file": str(screening_path)},
            )
            _remove_judgments_without_screening(session, notices)
            judgments_count = 0
        else:
            screening_schema = screening_raw.get("schema_version")
            inferred_schema = {
                "bidops.screening.v1": "bidops.decisions.v1",
                "bidops.screening.v2": "bidops.decisions.v2",
            }.get(screening_schema, screening_schema or "unknown")
            result_schema = decisions_schema or inferred_schema
            if decisions_generation_invalid:
                # A v3 result without a trustworthy sibling decision artifact
                # is not a safe projection, even when its nested rows happen
                # to contain usable grade/readiness fields.
                _record_warning(
                    session,
                    run_id,
                    "error",
                    "screening_results_invalid",
                    "screening-decisions.json generation binding이 유효하지 않아 판정을 적재하지 않았습니다.",
                    {"file": str(screening_path), "reason": "decisions generation binding is invalid"},
                )
                _remove_judgments_without_screening(session, notices)
                judgments_count = 0
            else:
                expected_config = None
                expected_digest = None
                for source in (screening_input_raw, decisions_raw):
                    if isinstance(source, dict) and source.get("schema_version") in V3_GENERATION_SCHEMAS:
                        expected_config = source.get("generation_config")
                        expected_digest = source.get("generation_config_digest")
                        break
                judgments_count = _load_screening_results(
                    session,
                    run_id,
                    notices,
                    screening_raw,
                    str(screening_path),
                    result_schema,
                    expected_generation_config=expected_config,
                    expected_generation_digest=expected_digest,
                )

        if collection_raw is not None:
            _load_collection_stats(session, run_id, collection_raw, str(collection_path), run)
        if screening_input_invalid is not None or decisions_generation_invalid or screening_generation_invalid:
            _clear_generation_metadata(run)
            generation_config_result, generation_digest_result = None, None
        else:
            generation_config_result, generation_digest_result = _persist_generation_metadata(
                run, screening_input_raw, decisions_raw, screening_raw
            )
        review_count = _load_feedback(session, run, notices, directory, reports_path)
        _refresh_prespec_attachment_eligibility(session, run_id)
        notices_count, judgments_count, review_count = _update_counts(session, run)
        session.commit()
        warnings = _warning_dicts(session, run_id)
        return IngestResult(
            run_id=run_id,
            notices=notices_count,
            order_plans=order_plans_count,
            judgments=judgments_count,
            reviews=review_count,
            generation_config=generation_config_result,
            generation_config_digest=generation_digest_result,
            warnings=warnings,
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
