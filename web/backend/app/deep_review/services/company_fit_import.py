"""Claude 참조 판정을 카드 lineage attempt로 가져온다 (PS-01 spec "MVP 범위" 5).

포트폴리오 스택은 실행기를 켜지 않고 가져온 결과만 보여 준다. 그래서 판정 묶음
파일의 행마다 **현재 DB 기준**으로 카드 동결 입력을 만들고(``judged_by``는
``claude_reference``, ``model_name``은 ``claude-reference-judgment``, ``model_revision``은
묶음 파일의 sha256), 결과를 기존 결정적 검증기로 통과시킨 뒤 같은 transaction에서
``queued → running → completed``로 전이한다(insert guard·전이 trigger를 그대로 따른다).

* 개요 입력이 없거나 입력이 너무 크거나 결과 검증에 실패한 공고는 건너뛰고 사유를 남긴다.
* 같은 ``input_sha256`` 행이 이미 있으면 건너뛴다(멱등).
* 카드를 쓸 수 없거나 묶음의 ``card_sha256``이 현재 카드와 다르면 전체를 거부한다.

모델은 부르지 않는다. 감사 이벤트는 가져온 행마다 하나이며 신원·hash·코드만 담는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any, Callable, Mapping
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.config import get_settings
from ...core.models import AuditEvent
from ..models import PreSpecCompanyFitAttempt
from .company_fit import (
    CLAUDE_REFERENCE_MODEL_NAME,
    JUDGED_BY_CLAUDE_REFERENCE,
    digest,
    frozen_card_input,
    overview_inputs,
    validate_result,
)
from .company_fit_card import BusinessScopeCardError, load_business_scope_card

IMPORT_SCHEMA_KEYS = frozenset({"judged_by", "card_sha256", "rows"})
_LEASE_OWNER = "company-fit-import"


class CompanyFitImportError(ValueError):
    """묶음 전체를 거부한다. ``code``는 안전한 정적 코드다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class CompanyFitImportResult:
    file_sha256: str
    card_sha256: str
    imported: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"file_sha256": self.file_sha256, "card_sha256": self.card_sha256,
                "imported": self.imported, "skipped": self.skipped}


def parse_judgment_bundle(raw: bytes) -> tuple[dict[str, Any], str]:
    """묶음 파일 bytes → ``(payload, sha256)``. 모양이 틀리면 ``input_invalid``다."""

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise CompanyFitImportError("input_invalid") from None
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or not IMPORT_SCHEMA_KEYS <= set(payload)
        or payload.get("judged_by") != JUDGED_BY_CLAUDE_REFERENCE
        or not isinstance(payload.get("card_sha256"), str)
        or not isinstance(rows, list)
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("notice_id"), int)
            or isinstance(row.get("notice_id"), bool)
            or row["notice_id"] < 1
            or not isinstance(row.get("result"), dict)
            for row in rows
        )
    ):
        raise CompanyFitImportError("input_invalid")
    return payload, hashlib.sha256(raw).hexdigest()


def import_company_fit_judgments(
    session: Session,
    payload: Mapping[str, Any],
    *,
    file_sha256: str,
    actor: str,
    dry_run: bool = False,
    settings=None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CompanyFitImportResult:
    """행마다 검증하고 가져온다. 호출자가 transaction 경계를 정하지 않아도 행마다 commit한다.

    ``dry_run``이면 같은 검사를 하고 아무것도 쓰지 않는다(끝에 rollback).
    """

    settings = settings or get_settings()
    try:
        actor = validate_actor(actor)
    except BundleServiceError:
        raise CompanyFitImportError("actor_invalid") from None
    try:
        card = load_business_scope_card(settings)
    except BusinessScopeCardError as error:
        raise CompanyFitImportError(error.code) from None
    if payload["card_sha256"] != card.card_sha256:
        raise CompanyFitImportError("card_sha256_mismatch")
    from ...lifecycle import lock_notice

    out = CompanyFitImportResult(file_sha256=file_sha256, card_sha256=card.card_sha256)
    seen: set[str] = set()
    for item in payload["rows"]:
        notice_id = int(item["notice_id"])
        source = overview_inputs(session, [notice_id]).get(notice_id)
        if source is None:
            out.skipped.append({"notice_id": notice_id, "reason": "overview_not_completed"})
            continue
        try:
            inputs = frozen_card_input(
                session, notice_id, source, card, model_name=CLAUDE_REFERENCE_MODEL_NAME,
                model_revision=file_sha256, judged_by=JUDGED_BY_CLAUDE_REFERENCE,
            )
        except (ValueError, TypeError) as error:
            reason = str(error) if str(error) == "company_fit_input_too_large" else "input_unavailable"
            out.skipped.append({"notice_id": notice_id, "reason": reason})
            continue
        try:
            result = validate_result(item["result"], inputs)
        except (ValidationError, ValueError, TypeError):
            out.skipped.append({"notice_id": notice_id, "reason": "result_invalid"})
            continue
        input_hash = digest(inputs)
        if input_hash in seen or session.scalar(
            select(PreSpecCompanyFitAttempt.id).where(PreSpecCompanyFitAttempt.input_sha256 == input_hash)
        ):
            out.skipped.append({"notice_id": notice_id, "reason": "already_imported"})
            continue
        seen.add(input_hash)
        if dry_run:
            out.imported.append({"notice_id": notice_id, "attempt_id": None, "input_sha256": input_hash,
                                 "decision": result.decision})
            continue
        lock_notice(session, notice_id)
        now = clock()
        row = PreSpecCompanyFitAttempt(
            id=uuid4(), company_id=None, notice_id=notice_id, document_version_id=source.document_id,
            overview_run_id=source.id, profile_version_id=None, deep_policy_version_id=None,
            card_version=card.card_version, card_sha256=card.card_sha256,
            input_jsonb=inputs, input_sha256=input_hash, policy_digest=inputs["policy_digest"],
            model_name=inputs["model_name"], model_revision=inputs["model_revision"],
            quality_status=source.quality_status, status="queued", created_at=now,
        )
        session.add(row)
        session.flush()
        row.status, row.lease_owner, row.lease_expires_at = "running", _LEASE_OWNER, now + timedelta(seconds=600)
        session.flush()
        row.result_jsonb = result.model_dump(mode="json")
        row.result_sha256 = digest(row.result_jsonb)
        row.status, row.lease_owner, row.lease_expires_at, row.completed_at = "completed", None, None, now
        session.flush()
        from .company_fit_runner import attempt_audit_metadata

        session.add(AuditEvent(
            actor_kind="human", claimed_name=actor, action="prespec_company_fit.attempt",
            aggregate_type="prespec_company_fit_attempt", aggregate_id=str(row.id),
            safe_metadata={**attempt_audit_metadata(row), "source": "import",
                           "judgment_file_sha256": file_sha256},
        ))
        session.commit()
        out.imported.append({"notice_id": notice_id, "attempt_id": str(row.id), "input_sha256": input_hash,
                             "decision": result.decision})
    if dry_run:
        session.rollback()
    return out


__all__ = [
    "CompanyFitImportError",
    "CompanyFitImportResult",
    "import_company_fit_judgments",
    "parse_judgment_bundle",
]
