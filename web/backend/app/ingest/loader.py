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
    ScreeningArtifact,
    ScreeningResultContract,
    ValidationArtifact,
    artifact_version,
    is_blank,
    missing_judgment_fields,
    model_extra_fields,
)


RUN_ID_RE = re.compile(r"^(?P<directory>.+)--(?P<generated>\d{8}T\d{6}(?:\.\d{1,6})?Z)$")
EXECUTION_ID_RE = re.compile(r"^scr-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DECIMAL_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


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
    judgments: int = 0
    reviews: int = 0
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def warning_counts(self) -> dict[str, int]:
        return dict(Counter(item["level"] for item in self.warnings))

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "notices": self.notices,
            "judgments": self.judgments,
            "reviews": self.reviews,
            "warnings": self.warnings,
            "warning_counts": self.warning_counts,
        }


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
        "lifecycle_json": _json_value(notice.lifecycle),
        "qualification_flags_json": _json_value(notice.qualification_flags),
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
        select(Notice).where(Notice.run_id == run_id, Notice.notice_key == notice_key)
    )
    if existing is None:
        existing = Notice(run_id=run_id, notice_key=notice_key)
        session.add(existing)
    for key, value in values.items():
        setattr(existing, key, value)
    _upsert_attachments(session, existing, raw.get("attachments"))
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
    "candidate_count", "notices",
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
            if not isinstance(common[key], dict) or set(common[key]) != keys:
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
    for notice in notices.values():
        if notice.judgment is not None:
            session.delete(notice.judgment)
    session.flush()


def _load_screening_results(
    session: Session,
    run_id: str,
    notices: dict[str, Notice],
    raw: dict[str, Any],
    source_file: str,
    schema_version: str,
) -> int:
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


def _update_counts(session: Session, run: Run) -> tuple[int, int, int]:
    notices = int(session.scalar(select(func.count(Notice.id)).where(Notice.run_id == run.id)) or 0)
    judgments = int(
        session.scalar(
            select(func.count(Judgment.id)).join(Notice, Judgment.notice_pk == Notice.id).where(Notice.run_id == run.id)
        )
        or 0
    )
    reviews = int(session.scalar(select(func.count(Review.id)).where(Review.run_id == run.id)) or 0)
    current = run.counts_json if isinstance(run.counts_json, dict) else {}
    run.counts_json = {**current, "notices": notices, "judgments": judgments, "reviews": reviews}
    return notices, judgments, reviews


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

    validation_raw = _read_optional_json(validation_path)
    screening_input_raw = _read_optional_json(screening_input_path)
    screening_raw = _read_optional_json(screening_path)
    decisions_raw = _read_optional_json(decisions_path)
    collection_raw = _read_optional_json(collection_path)
    metadata_raws = [screening_raw, decisions_raw, screening_input_raw, validation_raw, collection_raw]
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
        if validation_raw is None and screening_input_raw is None:
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
            _update_counts(session, run)
            session.commit()
            warnings = _warning_dicts(session, run_id)
            return IngestResult(run_id=run_id, warnings=warnings)

        # A frozen screening input is the identity authority for a v3
        # execution.  The validation set remains an immutable source artifact
        # but is not allowed to add sample-only Notice rows to the published
        # replacement.  Historical runs without screening-input retain the
        # validation-set projection.
        if screening_input_raw is not None:
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
            session.commit()
            warnings = _warning_dicts(session, run_id)
            return IngestResult(run_id=run_id, warnings=warnings)

        decisions_schema = None
        if decisions_raw is not None:
            try:
                decisions_model = DecisionArtifact.model_validate(decisions_raw)
                _record_unknown_fields(
                    session,
                    run_id,
                    _artifact_unknown_fields(decisions_raw, decisions_model),
                    str(decisions_path),
                )
                decisions_schema = artifact_version(decisions_model)
            except ValidationError as exc:
                _record_warning(
                    session,
                    run_id,
                    "error",
                    "decisions_invalid",
                    "screening-decisions.json 계약을 해석하지 못했습니다.",
                    {"file": str(decisions_path), "error": str(exc)},
                )
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
            judgments_count = _load_screening_results(
                session,
                run_id,
                notices,
                screening_raw,
                str(screening_path),
                result_schema,
            )

        if collection_raw is not None:
            _load_collection_stats(session, run_id, collection_raw, str(collection_path), run)
        review_count = _load_feedback(session, run, notices, directory, reports_path)
        notices_count, judgments_count, review_count = _update_counts(session, run)
        session.commit()
        warnings = _warning_dicts(session, run_id)
        return IngestResult(
            run_id=run_id,
            notices=notices_count,
            judgments=judgments_count,
            reviews=review_count,
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
