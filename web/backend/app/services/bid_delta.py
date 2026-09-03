"""Service boundary for immutable bid-delta comparisons and human decisions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.models import AuditEvent, IdempotencyRecord
from ..deep_review.models import (
    BidDeltaAttempt,
    BidDeltaComparison,
    BidDeltaEvidence,
    BidDeltaItem,
    BidFinalDecision,
    ContentObject,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
)
from ..lifecycle.models import Notice, Opportunity, OpportunityLink
from ..schemas.bid_delta import (
    BidDeltaAttemptCreateRequest,
    BidDeltaComparisonCreateRequest,
    BidDeltaComparisonSummary,
    BidDeltaComparisonView,
    BidDeltaInputFence,
    BidDeltaWorkspaceView,
    BidFinalDecisionCreateRequest,
)
from .document_bundles import BundleServiceError, validate_actor


BID_DELTA_CATEGORIES = (
    "budget_and_economics",
    "contract_period_and_schedule",
    "eligibility",
    "joint_supply_and_subcontracting",
    "scope_and_requirements",
    "evaluation",
    "submission",
)
SUPPORTED_CATEGORY_POLICY_VERSIONS = {"bid-delta-policy.v1": BID_DELTA_CATEGORIES}

# 2026-08-31 사업개발 책임자 확인으로 확정한 v1 allowlist다.
# 내역서는 `예산·경제성`, 제출서식은 `제출` 범주의 근거가 되므로 포함한다.
# 부록·기타는 성격이 불규칙해 제외한다.
BASELINE_DOCUMENT_ROLES = ("제안요청서", "과업지시서", "내역서", "제출서식")
COMPARISON_DOCUMENT_ROLES = ("공고", "정정", "제안요청서", "과업지시서", "내역서", "제출서식")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class BidDeltaServiceError(RuntimeError):
    """A safe, stable domain error used by the bid-delta router."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        request_id: UUID | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(message)


@dataclass(frozen=True)
class _RuntimeBinding:
    provider: str
    binding: str
    binding_id: str
    digest: str


@dataclass(frozen=True)
class _InputSnapshot:
    link: OpportunityLink
    notice: Notice
    bundle: DocumentBundle
    item: DocumentBundleItem
    document: DocumentVersion
    structure: DocumentStructure


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.isoformat() if isinstance(item, (datetime, date)) else str(item),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _jsonable(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _error(
    code: str,
    message: str,
    *,
    status_code: int,
    request_id: UUID | None = None,
) -> BidDeltaServiceError:
    return BidDeltaServiceError(code, message, status_code=status_code, request_id=request_id)


def _safe_error_code(value: object) -> str:
    if isinstance(value, str) and _SAFE_ERROR_CODE.fullmatch(value):
        return value
    return "processing_failed"


def _is_authoritative(link: OpportunityLink) -> bool:
    return bool(
        link.notice_id is not None
        and (
            (link.link_type == "official" and link.status == "확정")
            or (
                link.link_type == "candidate"
                and link.status == "사람 확인 완료"
                and link.human_decision == "accepted"
            )
        )
    )


def _request_hash(payload: Any) -> str:
    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    return _sha256(value)


def _validate_internal_url(
    value: object,
    *,
    provider: str,
    allowed_hosts: object = None,
) -> str | None:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        return None
    normalized_host = hostname.casefold().rstrip(".")
    allowed = set()
    if isinstance(allowed_hosts, str):
        allowed = {item.strip().casefold().rstrip(".") for item in allowed_hosts.split(",") if item.strip()}
    elif isinstance(allowed_hosts, Sequence):
        allowed = {str(item).strip().casefold().rstrip(".") for item in allowed_hosts if str(item).strip()}
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        address = None
    is_private_literal = bool(address is not None and (address.is_private or address.is_loopback))
    if normalized_host not in _LOCAL_HOSTS and not is_private_literal and normalized_host not in allowed:
        return None
    if provider == "vllm" and parsed.path.rstrip("/") != "/v1":
        return None
    if provider == "ollama" and parsed.path not in {"", "/"}:
        return None
    return value.rstrip("/")


def resolve_runtime_binding() -> _RuntimeBinding:
    """Resolve an approved internal binding without making a network call."""

    try:
        settings = get_settings()
        provider = getattr(settings, "analysis_provider", None)
        if provider == "vllm":
            base_url = _validate_internal_url(
                getattr(settings, "vllm_base_url", None),
                provider="vllm",
                allowed_hosts=getattr(settings, "vllm_allowed_hosts", ""),
            )
            model = getattr(settings, "vllm_model", None)
        elif provider == "ollama":
            base_url = _validate_internal_url(
                getattr(settings, "model_base_url", None),
                provider="ollama",
            )
            model = getattr(settings, "model_name", None)
        else:
            base_url = None
            model = None
        if base_url is None or not isinstance(model, str) or not model.strip() or any(
            character.isspace() for character in model
        ):
            raise ValueError("unapproved runtime binding")
        binding = f"{provider}|{base_url}|{model}"
        return _RuntimeBinding(
            provider=str(provider),
            binding=binding,
            binding_id=f"bid-delta:{provider}:{model}",
            digest=hashlib.sha256(binding.encode("utf-8")).hexdigest(),
        )
    except Exception as exc:
        raise _error(
            "bid_delta_service_unavailable",
            "입찰 delta 서비스를 사용할 수 없습니다",
            status_code=503,
        ) from exc


def _ref_from_snapshot(snapshot: _InputSnapshot) -> dict[str, Any]:
    item = snapshot.item
    document = snapshot.document
    structure = snapshot.structure
    return {
        "opportunity_link_id": snapshot.link.id,
        "notice_id": snapshot.notice.id,
        "notice_source_type": snapshot.notice.source_type,
        "notice_external_id": snapshot.notice.notice_key,
        "bid_ordinal": snapshot.notice.bid_ord,
        "published_at": snapshot.notice.published_at,
        "bundle_id": snapshot.bundle.id,
        "bundle_revision": snapshot.bundle.revision,
        "bundle_version": snapshot.bundle.version,
        "document_version_id": document.id,
        "document_version_version": item.document_version_version,
        "document_role": item.role_at_confirmation,
        "structure_id": item.structure_id_at_confirmation,
        "source_sha256": item.content_sha256,
        "structure_payload_sha256": item.structure_payload_sha256,
        "effective_date": item.effective_date_at_confirmation,
    }


def _stored_snapshot(session: Session, comparison: BidDeltaComparison, side: str) -> _InputSnapshot:
    prefix = "baseline" if side == "baseline" else "comparison"
    link_id = getattr(comparison, f"{prefix}_link_id")
    notice_id = getattr(comparison, f"{prefix}_notice_id")
    bundle_id = getattr(comparison, f"{prefix}_bundle_id")
    document_id = getattr(comparison, f"{prefix}_document_version_id")
    structure_id = getattr(comparison, f"{prefix}_structure_id")
    link = session.get(OpportunityLink, link_id)
    notice = session.get(Notice, notice_id)
    bundle = session.get(DocumentBundle, bundle_id)
    document = session.get(DocumentVersion, document_id)
    structure = session.get(DocumentStructure, structure_id)
    item = session.scalar(
        select(DocumentBundleItem).where(
            DocumentBundleItem.bundle_id == bundle_id,
            DocumentBundleItem.document_version_id == document_id,
            DocumentBundleItem.structure_id_at_confirmation == structure_id,
        )
    )
    if any(value is None for value in (link, notice, bundle, item, document, structure)):
        raise _error(
            "bid_delta_projection_unavailable",
            "입찰 delta 조회를 사용할 수 없습니다",
            status_code=503,
        )
    assert link is not None and notice is not None and bundle is not None
    assert item is not None and document is not None and structure is not None
    if (
        link.opportunity_id != comparison.opportunity_id
        or link.notice_id != notice.id
        or bundle.notice_id != notice.id
        or bundle.revision != getattr(comparison, f"{prefix}_bundle_revision")
        or bundle.version != getattr(comparison, f"{prefix}_bundle_version")
        or document.notice_id != notice.id
        or document.version != getattr(comparison, f"{prefix}_document_version_version")
        or structure.document_version_id != document.id
        or structure.source_sha256 != getattr(comparison, f"{prefix}_source_sha256")
        or structure.payload_sha256 != getattr(comparison, f"{prefix}_structure_payload_sha256")
        or item.document_version_version != getattr(comparison, f"{prefix}_document_version_version")
        or item.content_sha256 != getattr(comparison, f"{prefix}_source_sha256")
        or item.structure_payload_sha256 != getattr(comparison, f"{prefix}_structure_payload_sha256")
    ):
        raise _error(
            "bid_delta_projection_unavailable",
            "입찰 delta 조회를 사용할 수 없습니다",
            status_code=503,
        )
    return _InputSnapshot(link, notice, bundle, item, document, structure)


def _candidate_snapshot(
    session: Session,
    link: OpportunityLink,
    notice: Notice,
    roles: tuple[str, ...],
) -> list[_InputSnapshot]:
    bundle = session.scalar(
        select(DocumentBundle)
        .where(DocumentBundle.notice_id == notice.id, DocumentBundle.status == "ready")
        .order_by(DocumentBundle.revision.desc(), DocumentBundle.version.desc(), DocumentBundle.id.desc())
        .limit(1)
    )
    if bundle is None:
        return []
    items = session.scalars(
        select(DocumentBundleItem)
        .where(
            DocumentBundleItem.bundle_id == bundle.id,
            DocumentBundleItem.role_at_confirmation.in_(roles),
            DocumentBundleItem.safety_status_at_confirmation == "safe",
        )
        .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
    ).all()
    candidates: list[_InputSnapshot] = []
    for item in items:
        document = session.get(DocumentVersion, item.document_version_id)
        structure = session.get(DocumentStructure, item.structure_id_at_confirmation)
        if document is None or structure is None:
            continue
        if document.safety_status != "safe" or structure.validation_status != "ready":
            continue
        if (
            document.notice_id != notice.id
            or structure.document_version_id != document.id
            or document.version != item.document_version_version
            or structure.source_sha256 != item.content_sha256
            or structure.payload_sha256 != item.structure_payload_sha256
        ):
            continue
        content = session.get(ContentObject, document.content_object_id)
        if content is None or content.sha256 != item.content_sha256:
            continue
        candidates.append(_InputSnapshot(link, notice, bundle, item, document, structure))
    return candidates


def _candidate_sort_key(snapshot: _InputSnapshot) -> tuple[Any, ...]:
    notice = snapshot.notice
    published = notice.published_at
    if published is None:
        published_key = (0, datetime.min.replace(tzinfo=UTC))
    else:
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        published_key = (1, published)
    ordinal = notice.bid_ord
    if ordinal is not None and ordinal.isdecimal():
        ordinal_key = (0, int(ordinal), ordinal)
    else:
        ordinal_key = (1, 0, ordinal or "")
    return (
        published_key,
        ordinal_key,
        snapshot.bundle.revision,
        snapshot.item.document_version_version,
        str(snapshot.document.id),
        snapshot.item.ordinal,
    )


def _item_view(session: Session, item: BidDeltaItem) -> dict[str, Any]:
    evidence = session.scalars(
        select(BidDeltaEvidence)
        .where(BidDeltaEvidence.item_id == item.id)
        .order_by(BidDeltaEvidence.side.asc(), BidDeltaEvidence.ordinal.asc(), BidDeltaEvidence.id.asc())
    ).all()
    return {
        "id": item.id,
        "ordinal": item.ordinal,
        "category": item.category,
        "result_status": item.result_status,
        "materiality": item.materiality,
        "before_value": item.before_value,
        "after_value": item.after_value,
        "summary": item.summary,
        "baseline_evidence": [row for row in (_evidence_view(entry) for entry in evidence) if row["side"] == "baseline"],
        "comparison_evidence": [row for row in (_evidence_view(entry) for entry in evidence) if row["side"] == "comparison"],
        "error_code": item.error_code,
    }


def _evidence_view(evidence: BidDeltaEvidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "side": evidence.side,
        "document_version_id": evidence.document_version_id,
        "structure_id": evidence.structure_id,
        "source_sha256": evidence.source_sha256,
        "locator_type": evidence.locator_type,
        "locator": evidence.locator,
        "quote": evidence.quote,
        "verification_status": evidence.verification_status,
    }


def _attempt_view(attempt: BidDeltaAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "sequence": attempt.sequence,
        "status": attempt.status,
        "started_at": attempt.started_at,
        "completed_at": attempt.completed_at,
        "last_error_code": attempt.last_error_code,
    }


class BidDeltaService:
    """Own all bid-delta locks, state transitions, idempotency, and audit."""

    def _idempotent(
        self,
        session: Session,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        actor: str,
        request_id: UUID,
        request_hash: str,
    ) -> dict[str, Any] | None:
        row = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.aggregate_type == aggregate_type,
                IdempotencyRecord.aggregate_id == aggregate_id,
                IdempotencyRecord.claimed_name == actor,
                IdempotencyRecord.request_id == request_id,
            )
        )
        if row is None:
            return None
        if row.request_sha256 != request_hash:
            raise _error(
                "idempotency_conflict",
                "같은 request_id가 다른 요청에 사용되었습니다",
                status_code=409,
                request_id=request_id,
            )
        return dict(row.response_snapshot) if isinstance(row.response_snapshot, Mapping) else None

    @staticmethod
    def _actor(actor: str | None, actor_format: str | None, request_id: UUID | None = None) -> str:
        try:
            return validate_actor(actor, actor_format)
        except BundleServiceError as exc:
            raise _error(exc.code, exc.message, status_code=exc.status_code, request_id=request_id) from exc

    @staticmethod
    def _opportunity(session: Session, opportunity_id: int, *, lock: bool = True) -> Opportunity:
        query = select(Opportunity).where(Opportunity.id == opportunity_id)
        if lock:
            query = query.with_for_update()
        opportunity = session.scalar(query)
        if opportunity is None:
            raise _error("opportunity_not_found", "사업기회를 찾을 수 없습니다", status_code=404)
        if opportunity.merged_into_opportunity_id is not None:
            raise _error("opportunity_merged", "병합된 사업기회는 사용할 수 없습니다", status_code=409)
        return opportunity

    @staticmethod
    def _lock_row(session: Session, model: Any, identifier: Any) -> Any | None:
        return session.scalar(select(model).where(model.id == identifier).with_for_update())

    def _load_input(
        self,
        session: Session,
        opportunity_id: int,
        fence: BidDeltaInputFence,
        *,
        side: str,
        request_id: UUID,
    ) -> _InputSnapshot:
        link = self._lock_row(session, OpportunityLink, fence.opportunity_link_id)
        if link is None:
            raise _error("bid_delta_input_not_found", "비교 입력을 찾을 수 없습니다", status_code=404, request_id=request_id)
        if link.opportunity_id != opportunity_id:
            raise _error("bid_delta_input_scope_conflict", "비교 입력의 사업기회 범위가 다릅니다", status_code=409, request_id=request_id)
        notice = self._lock_row(session, Notice, fence.notice_id)
        if notice is None:
            raise _error("bid_delta_input_not_found", "비교 입력을 찾을 수 없습니다", status_code=404, request_id=request_id)
        bundle = self._lock_row(session, DocumentBundle, fence.bundle_id)
        document = self._lock_row(session, DocumentVersion, fence.document_version_id)
        structure = self._lock_row(session, DocumentStructure, fence.structure_id)
        item = session.scalar(
            select(DocumentBundleItem)
            .where(
                DocumentBundleItem.bundle_id == fence.bundle_id,
                DocumentBundleItem.document_version_id == fence.document_version_id,
                DocumentBundleItem.structure_id_at_confirmation == fence.structure_id,
            )
            .with_for_update()
        )
        if any(value is None for value in (bundle, document, structure, item)):
            raise _error("bid_delta_input_not_found", "비교 입력을 찾을 수 없습니다", status_code=404, request_id=request_id)
        assert bundle is not None and document is not None and structure is not None and item is not None
        if (
            link.notice_id != fence.notice_id
            or bundle.notice_id != notice.id
            or document.notice_id != notice.id
            or structure.document_version_id != document.id
            or item.structure_id_at_confirmation != fence.structure_id
            or bundle.revision != fence.bundle_revision
            or bundle.version != fence.bundle_version
            or document.version != fence.document_version_version
            or item.document_version_version != fence.document_version_version
            or item.content_sha256 != fence.source_sha256
            or item.structure_payload_sha256 != fence.structure_payload_sha256
            or structure.source_sha256 != fence.source_sha256
            or structure.payload_sha256 != fence.structure_payload_sha256
        ):
            raise _error(
                "bid_delta_input_version_conflict",
                "비교 문서 버전이 변경되었습니다",
                status_code=409,
                request_id=request_id,
            )
        content = session.get(ContentObject, document.content_object_id)
        if content is None or content.sha256 != fence.source_sha256:
            raise _error(
                "bid_delta_input_version_conflict",
                "비교 문서 버전이 변경되었습니다",
                status_code=409,
                request_id=request_id,
            )
        if not _is_authoritative(link):
            raise _error(
                "bid_delta_input_not_authoritative",
                "비교 입력 연결이 authoritative 상태가 아닙니다",
                status_code=409,
                request_id=request_id,
            )
        if side == "baseline":
            if notice.source_type != "pre_spec" or item.role_at_confirmation not in BASELINE_DOCUMENT_ROLES:
                raise _error(
                    "bid_delta_baseline_type_invalid",
                    "baseline 입력 형식이 올바르지 않습니다",
                    status_code=422,
                    request_id=request_id,
                )
        elif notice.source_type != "bid_notice" or item.role_at_confirmation not in COMPARISON_DOCUMENT_ROLES:
            raise _error(
                "bid_delta_comparison_type_invalid",
                "comparison 입력 형식이 올바르지 않습니다",
                status_code=422,
                request_id=request_id,
            )
        if (
            bundle.status != "ready"
            or item.safety_status_at_confirmation != "safe"
            or document.safety_status != "safe"
            or structure.validation_status != "ready"
        ):
            raise _error(
                "bid_delta_input_not_ready",
                "비교 입력이 아직 준비되지 않았습니다",
                status_code=409,
                request_id=request_id,
            )
        return _InputSnapshot(link, notice, bundle, item, document, structure)

    def workspace(self, session: Session, opportunity_id: int) -> dict[str, Any]:
        opportunity = self._opportunity(session, opportunity_id, lock=False)
        links = session.scalars(
            select(OpportunityLink)
            .where(OpportunityLink.opportunity_id == opportunity.id)
            .order_by(OpportunityLink.id.asc())
        ).all()
        baseline_candidates: list[_InputSnapshot] = []
        comparison_candidates: list[_InputSnapshot] = []
        for link in links:
            if not _is_authoritative(link) or link.notice_id is None:
                continue
            notice = session.get(Notice, link.notice_id)
            if notice is None:
                continue
            if notice.source_type == "pre_spec":
                baseline_candidates.extend(_candidate_snapshot(session, link, notice, BASELINE_DOCUMENT_ROLES))
            elif notice.source_type == "bid_notice":
                comparison_candidates.extend(_candidate_snapshot(session, link, notice, COMPARISON_DOCUMENT_ROLES))
        baseline_candidates.sort(key=_candidate_sort_key)
        comparison_candidates.sort(key=_candidate_sort_key)

        comparisons = session.scalars(
            select(BidDeltaComparison)
            .where(BidDeltaComparison.opportunity_id == opportunity.id)
            .order_by(BidDeltaComparison.sequence.asc())
        ).all()
        decisions = session.scalars(
            select(BidFinalDecision)
            .where(BidFinalDecision.opportunity_id == opportunity.id)
            .order_by(BidFinalDecision.sequence.asc())
        ).all()
        latest_decision = None
        decision_currentness = "unknown"
        currentness_reasons = ["no_final_decision"]
        if decisions:
            latest_decision = decisions[-1]
            latest_comparison = session.get(BidDeltaComparison, latest_decision.comparison_id)
            if latest_comparison is None:
                raise _error("bid_delta_projection_unavailable", "입찰 delta 조회를 사용할 수 없습니다", status_code=503)
            decision_currentness, currentness_reasons = self._currentness(session, latest_comparison)
        comparison_views = [self._comparison_summary(session, row) for row in comparisons]
        latest_view = self._decision_view(latest_decision, decision_currentness, currentness_reasons) if latest_decision else None
        return _jsonable(
            BidDeltaWorkspaceView(
                schema_version="bidops.bid-delta-workspace.v1",
                opportunity_id=opportunity.id,
                baseline_candidates=[_ref_from_snapshot(item) for item in baseline_candidates],
                comparison_candidates=[_ref_from_snapshot(item) for item in comparison_candidates],
                comparisons=comparison_views,
                latest_final_decision=latest_view,
                decision_currentness=decision_currentness,
                currentness_reasons=currentness_reasons,
                generated_at=_now(),
            ).model_dump(mode="json")
        )

    def _comparison_summary(self, session: Session, comparison: BidDeltaComparison) -> dict[str, Any]:
        baseline = _stored_snapshot(session, comparison, "baseline")
        compared = _stored_snapshot(session, comparison, "comparison")
        return BidDeltaComparisonSummary(
            id=comparison.id,
            sequence=comparison.sequence,
            version=comparison.version,
            category_policy_version=comparison.category_policy_version,
            calculation_status=comparison.calculation_status,
            result_status=comparison.result_status,
            materiality=comparison.materiality,
            baseline=_ref_from_snapshot(baseline),
            comparison=_ref_from_snapshot(compared),
            result_sha256=comparison.result_sha256,
            created_at=comparison.created_at,
            started_at=comparison.started_at,
            completed_at=comparison.completed_at,
        ).model_dump(mode="json")

    def comparison_view(self, session: Session, comparison_id: UUID, opportunity_id: int) -> dict[str, Any]:
        self._opportunity(session, opportunity_id, lock=False)
        comparison = session.get(BidDeltaComparison, comparison_id)
        if comparison is None:
            raise _error("bid_delta_comparison_not_found", "비교를 찾을 수 없습니다", status_code=404)
        if comparison.opportunity_id != opportunity_id:
            raise _error("bid_delta_comparison_scope_conflict", "비교의 사업기회 범위가 다릅니다", status_code=409)
        return self._comparison_view(session, comparison)

    def _comparison_view(self, session: Session, comparison: BidDeltaComparison) -> dict[str, Any]:
        baseline = _stored_snapshot(session, comparison, "baseline")
        compared = _stored_snapshot(session, comparison, "comparison")
        attempts = session.scalars(
            select(BidDeltaAttempt)
            .where(BidDeltaAttempt.comparison_id == comparison.id)
            .order_by(BidDeltaAttempt.sequence.asc())
        ).all()
        items: list[dict[str, Any]] = []
        if comparison.current_attempt_id is not None:
            current_items = session.scalars(
                select(BidDeltaItem)
                .where(
                    BidDeltaItem.comparison_id == comparison.id,
                    BidDeltaItem.attempt_id == comparison.current_attempt_id,
                )
                .order_by(BidDeltaItem.ordinal.asc(), BidDeltaItem.category.asc())
            ).all()
            items = [_item_view(session, item) for item in current_items]
        final_decisions = session.scalars(
            select(BidFinalDecision)
            .where(BidFinalDecision.comparison_id == comparison.id)
            .order_by(BidFinalDecision.sequence.asc())
        ).all()
        currentness, reasons = self._currentness(session, comparison) if final_decisions else ("unknown", ["no_final_decision"])
        final_views = [self._decision_view(row, currentness, reasons) for row in final_decisions]
        latest = final_views[-1] if final_views else None
        return _jsonable(
            BidDeltaComparisonView(
                schema_version="bidops.bid-delta-comparison.v1",
                id=comparison.id,
                opportunity_id=comparison.opportunity_id,
                sequence=comparison.sequence,
                version=comparison.version,
                category_policy_version=comparison.category_policy_version,
                calculation_status=comparison.calculation_status,
                result_status=comparison.result_status,
                materiality=comparison.materiality,
                baseline=_ref_from_snapshot(baseline),
                comparison=_ref_from_snapshot(compared),
                items=items,
                attempts=[_attempt_view(attempt) for attempt in attempts],
                result_sha256=comparison.result_sha256,
                last_error_code=comparison.last_error_code,
                created_at=comparison.created_at,
                started_at=comparison.started_at,
                completed_at=comparison.completed_at,
                final_decisions=final_views,
                latest_final_decision=latest,
                decision_currentness=currentness,
                currentness_reasons=reasons,
            ).model_dump(mode="json")
        )

    @staticmethod
    def _decision_view(
        decision: BidFinalDecision | None,
        currentness: str,
        reasons: list[str],
    ) -> dict[str, Any] | None:
        if decision is None:
            return None
        return {
            "schema_version": "bidops.bid-final-decision.v1",
            "id": decision.id,
            "opportunity_id": decision.opportunity_id,
            "sequence": decision.sequence,
            "comparison_id": decision.comparison_id,
            "comparison_version": decision.comparison_version,
            "result_sha256": decision.result_sha256,
            "baseline_document_version_id": decision.baseline_document_version_id,
            "comparison_document_version_id": decision.comparison_document_version_id,
            "supersedes_final_decision_id": decision.supersedes_final_decision_id,
            "decision": decision.decision,
            "reason": decision.reason,
            "claimed_name": decision.claimed_name,
            "request_id": decision.request_id,
            "created_at": decision.created_at,
            "currentness": currentness,
            "currentness_reasons": reasons,
        }

    def _currentness(self, session: Session, comparison: BidDeltaComparison) -> tuple[str, list[str]]:
        comparison_notice = session.get(Notice, comparison.comparison_notice_id)
        if comparison_notice is None or comparison_notice.published_at is None:
            return "unknown", ["ordering_unknown"]
        comparison_published = comparison_notice.published_at
        if comparison_published.tzinfo is None:
            comparison_published = comparison_published.replace(tzinfo=UTC)
        links = session.scalars(
            select(OpportunityLink).where(
                OpportunityLink.opportunity_id == comparison.opportunity_id,
                OpportunityLink.notice_id.is_not(None),
            )
        ).all()
        for link in links:
            if not _is_authoritative(link) or link.notice_id is None:
                continue
            notice = session.get(Notice, link.notice_id)
            if notice is None or notice.source_type != "bid_notice":
                continue
            if notice.published_at is None:
                return "unknown", ["ordering_unknown"]
            published = notice.published_at
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            if notice.id != comparison.comparison_notice_id and published > comparison_published:
                return "stale", ["newer_bid_notice"]

        if self._has_newer_ready_document(session, comparison, "baseline") or self._has_newer_ready_document(session, comparison, "comparison"):
            return "stale", ["newer_ready_document_version"]
        return "current", []

    @staticmethod
    def _has_newer_ready_document(session: Session, comparison: BidDeltaComparison, side: str) -> bool:
        prefix = "baseline" if side == "baseline" else "comparison"
        notice_id = getattr(comparison, f"{prefix}_notice_id")
        captured_revision = getattr(comparison, f"{prefix}_bundle_revision")
        captured_bundle_version = getattr(comparison, f"{prefix}_bundle_version")
        captured_document_id = getattr(comparison, f"{prefix}_document_version_id")
        captured_document_version = getattr(comparison, f"{prefix}_document_version_version")
        roles = BASELINE_DOCUMENT_ROLES if side == "baseline" else COMPARISON_DOCUMENT_ROLES
        rows = session.execute(
            select(DocumentBundle, DocumentBundleItem, DocumentVersion, DocumentStructure)
            .join(DocumentBundleItem, DocumentBundleItem.bundle_id == DocumentBundle.id)
            .join(DocumentVersion, DocumentVersion.id == DocumentBundleItem.document_version_id)
            .join(DocumentStructure, DocumentStructure.id == DocumentBundleItem.structure_id_at_confirmation)
            .where(
                DocumentBundle.notice_id == notice_id,
                DocumentBundle.status == "ready",
                DocumentBundleItem.role_at_confirmation.in_(roles),
                DocumentBundleItem.safety_status_at_confirmation == "safe",
                DocumentVersion.safety_status == "safe",
                DocumentStructure.validation_status == "ready",
            )
        ).all()
        for bundle, item, document, structure in rows:
            if structure.source_sha256 != item.content_sha256 or structure.payload_sha256 != item.structure_payload_sha256:
                continue
            if (bundle.revision, bundle.version) > (captured_revision, captured_bundle_version):
                return True
            if document.id != captured_document_id and document.version > captured_document_version:
                return True
        return False

    def create_comparison(
        self,
        session: Session,
        opportunity_id: int,
        payload: BidDeltaComparisonCreateRequest,
        actor: str | None,
        actor_format: str | None = None,
    ) -> dict[str, Any]:
        claimed_name = self._actor(actor, actor_format, payload.request_id)
        request_hash = _request_hash(payload)
        try:
            opportunity = self._opportunity(session, opportunity_id)
            duplicate = self._idempotent(
                session,
                operation="bid_delta_comparison",
                aggregate_type="opportunity",
                aggregate_id=str(opportunity.id),
                actor=claimed_name,
                request_id=payload.request_id,
                request_hash=request_hash,
            )
            if duplicate is not None:
                session.commit()
                return duplicate
            if payload.category_policy_version not in SUPPORTED_CATEGORY_POLICY_VERSIONS:
                raise _error(
                    "bid_delta_category_policy_invalid",
                    "지원하지 않는 category policy입니다",
                    status_code=422,
                    request_id=payload.request_id,
                )
            baseline = self._load_input(session, opportunity.id, payload.baseline, side="baseline", request_id=payload.request_id)
            compared = self._load_input(session, opportunity.id, payload.comparison, side="comparison", request_id=payload.request_id)
            if baseline.document.id == compared.document.id:
                raise _error("bid_delta_same_input", "baseline과 comparison 입력이 같습니다", status_code=422, request_id=payload.request_id)
            binding = resolve_runtime_binding()
            sequence = int(
                session.scalar(
                    select(func.max(BidDeltaComparison.sequence)).where(BidDeltaComparison.opportunity_id == opportunity.id)
                )
                or 0
            ) + 1
            comparison = BidDeltaComparison(
                id=uuid4(),
                opportunity_id=opportunity.id,
                sequence=sequence,
                version=1,
                category_policy_version=payload.category_policy_version,
                baseline_link_id=baseline.link.id,
                baseline_notice_id=baseline.notice.id,
                baseline_bundle_id=baseline.bundle.id,
                baseline_bundle_revision=baseline.bundle.revision,
                baseline_bundle_version=baseline.bundle.version,
                baseline_document_version_id=baseline.document.id,
                baseline_document_version_version=baseline.item.document_version_version,
                baseline_structure_id=baseline.item.structure_id_at_confirmation,
                baseline_source_sha256=baseline.item.content_sha256,
                baseline_structure_payload_sha256=baseline.item.structure_payload_sha256,
                comparison_link_id=compared.link.id,
                comparison_notice_id=compared.notice.id,
                comparison_bundle_id=compared.bundle.id,
                comparison_bundle_revision=compared.bundle.revision,
                comparison_bundle_version=compared.bundle.version,
                comparison_document_version_id=compared.document.id,
                comparison_document_version_version=compared.item.document_version_version,
                comparison_structure_id=compared.item.structure_id_at_confirmation,
                comparison_source_sha256=compared.item.content_sha256,
                comparison_structure_payload_sha256=compared.item.structure_payload_sha256,
                calculation_status="pending",
                result_status=None,
                materiality="unknown",
                current_attempt_id=None,
                result_sha256=None,
                last_error_code=None,
                created_by_name=claimed_name,
                created_at=_now(),
                started_at=None,
                completed_at=None,
            )
            session.add(comparison)
            session.flush()
            attempt = BidDeltaAttempt(
                id=uuid4(),
                comparison_id=comparison.id,
                sequence=1,
                status="queued",
                lease_fence=0,
                requested_by_name=claimed_name,
                runtime_binding_id=binding.binding_id,
                runtime_binding_digest=binding.digest,
                created_at=_now(),
            )
            session.add(attempt)
            session.flush()
            comparison.current_attempt_id = attempt.id
            session.flush()
            response = self._comparison_view(session, comparison)
            session.add(
                AuditEvent(
                    actor_kind="human",
                    claimed_name=claimed_name,
                    action="bid_delta.comparison_requested",
                    aggregate_type="bid_delta_comparison",
                    aggregate_id=str(comparison.id),
                    request_id=str(payload.request_id),
                    safe_metadata={
                        "comparison_id": str(comparison.id),
                        "opportunity_id": opportunity.id,
                        "baseline_document_version_id": str(baseline.document.id),
                        "baseline_structure_id": str(baseline.structure.id),
                        "comparison_document_version_id": str(compared.document.id),
                        "comparison_structure_id": str(compared.structure.id),
                        "category_policy_version": payload.category_policy_version,
                    },
                )
            )
            session.add(
                IdempotencyRecord(
                    operation="bid_delta_comparison",
                    aggregate_type="opportunity",
                    aggregate_id=str(opportunity.id),
                    claimed_name=claimed_name,
                    request_id=payload.request_id,
                    request_sha256=request_hash,
                    response_status=202,
                    response_snapshot=response,
                )
            )
            session.commit()
            return response
        except BidDeltaServiceError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            duplicate = self._idempotent(
                session,
                operation="bid_delta_comparison",
                aggregate_type="opportunity",
                aggregate_id=str(opportunity_id),
                actor=claimed_name,
                request_id=payload.request_id,
                request_hash=request_hash,
            )
            if duplicate is not None:
                session.commit()
                return duplicate
            raise _error("bid_delta_input_version_conflict", "비교 입력이 동시에 변경되었습니다", status_code=409, request_id=payload.request_id) from exc
        except Exception as exc:
            session.rollback()
            raise _error("processing_failed", "입찰 delta 작업을 완료할 수 없습니다", status_code=500, request_id=payload.request_id) from exc

    def retry_attempt(
        self,
        session: Session,
        opportunity_id: int,
        comparison_id: UUID,
        payload: BidDeltaAttemptCreateRequest,
        actor: str | None,
        actor_format: str | None = None,
    ) -> dict[str, Any]:
        claimed_name = self._actor(actor, actor_format, payload.request_id)
        request_hash = _request_hash(payload)
        try:
            opportunity = self._opportunity(session, opportunity_id)
            comparison = session.scalar(
                select(BidDeltaComparison)
                .where(BidDeltaComparison.id == comparison_id)
                .with_for_update()
            )
            if comparison is None:
                raise _error("bid_delta_comparison_not_found", "비교를 찾을 수 없습니다", status_code=404, request_id=payload.request_id)
            if comparison.opportunity_id != opportunity.id:
                raise _error("bid_delta_comparison_scope_conflict", "비교의 사업기회 범위가 다릅니다", status_code=409, request_id=payload.request_id)
            duplicate = self._idempotent(
                session,
                operation="bid_delta_retry",
                aggregate_type="bid_delta_comparison",
                aggregate_id=str(comparison.id),
                actor=claimed_name,
                request_id=payload.request_id,
                request_hash=request_hash,
            )
            if duplicate is not None:
                session.commit()
                return duplicate
            if comparison.calculation_status != "failed":
                raise _error("bid_delta_comparison_not_retryable", "실패한 비교만 재시도할 수 있습니다", status_code=409, request_id=payload.request_id)
            if comparison.version != payload.expected_comparison_version:
                raise _error("bid_delta_version_conflict", "비교 버전이 변경되었습니다", status_code=409, request_id=payload.request_id)
            active = session.scalar(
                select(BidDeltaAttempt)
                .where(
                    BidDeltaAttempt.comparison_id == comparison.id,
                    BidDeltaAttempt.status.in_(("queued", "running")),
                )
                .limit(1)
            )
            if active is not None:
                raise _error("active_attempt_exists", "이미 실행 중인 attempt가 있습니다", status_code=409, request_id=payload.request_id)
            binding = resolve_runtime_binding()
            sequence = int(
                session.scalar(
                    select(func.max(BidDeltaAttempt.sequence)).where(BidDeltaAttempt.comparison_id == comparison.id)
                )
                or 0
            ) + 1
            attempt = BidDeltaAttempt(
                id=uuid4(),
                comparison_id=comparison.id,
                sequence=sequence,
                status="queued",
                lease_fence=0,
                requested_by_name=claimed_name,
                runtime_binding_id=binding.binding_id,
                runtime_binding_digest=binding.digest,
                created_at=_now(),
            )
            session.add(attempt)
            comparison.calculation_status = "pending"
            comparison.result_status = None
            comparison.materiality = "unknown"
            comparison.current_attempt_id = attempt.id
            comparison.result_sha256 = None
            comparison.last_error_code = None
            comparison.started_at = None
            comparison.completed_at = None
            comparison.version += 1
            session.flush()
            response = self._comparison_view(session, comparison)
            session.add(
                AuditEvent(
                    actor_kind="human",
                    claimed_name=claimed_name,
                    action="bid_delta.retry_requested",
                    aggregate_type="bid_delta_comparison",
                    aggregate_id=str(comparison.id),
                    request_id=str(payload.request_id),
                    safe_metadata={"comparison_id": str(comparison.id), "attempt_id": str(attempt.id), "sequence": attempt.sequence},
                )
            )
            session.add(
                IdempotencyRecord(
                    operation="bid_delta_retry",
                    aggregate_type="bid_delta_comparison",
                    aggregate_id=str(comparison.id),
                    claimed_name=claimed_name,
                    request_id=payload.request_id,
                    request_sha256=request_hash,
                    response_status=202,
                    response_snapshot=response,
                )
            )
            session.commit()
            return response
        except BidDeltaServiceError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise _error("active_attempt_exists", "동시에 다른 attempt가 생성되었습니다", status_code=409, request_id=payload.request_id) from exc
        except Exception as exc:
            session.rollback()
            raise _error("processing_failed", "입찰 delta 작업을 완료할 수 없습니다", status_code=500, request_id=payload.request_id) from exc

    def start_attempt(self, session: Session, attempt_id: UUID, lease_fence: int) -> BidDeltaAttempt:
        try:
            attempt = session.scalar(select(BidDeltaAttempt).where(BidDeltaAttempt.id == attempt_id).with_for_update())
            if attempt is None:
                raise _error("bid_delta_attempt_not_found", "attempt를 찾을 수 없습니다", status_code=404)
            if attempt.lease_fence != lease_fence or attempt.status != "queued":
                raise _error("bid_delta_attempt_fence_conflict", "attempt lease fence가 변경되었습니다", status_code=409)
            comparison = session.scalar(select(BidDeltaComparison).where(BidDeltaComparison.id == attempt.comparison_id).with_for_update())
            if comparison is None or comparison.current_attempt_id != attempt.id or comparison.calculation_status != "pending":
                raise _error("bid_delta_attempt_fence_conflict", "attempt 입력 상태가 변경되었습니다", status_code=409)
            now = _now()
            attempt.status = "running"
            attempt.started_at = now
            comparison.calculation_status = "running"
            comparison.started_at = now
            session.add(
                AuditEvent(
                    actor_kind="system",
                    claimed_name=None,
                    action="bid_delta.attempt_started",
                    aggregate_type="bid_delta_attempt",
                    aggregate_id=str(attempt.id),
                    request_id=None,
                    safe_metadata={"comparison_id": str(comparison.id), "attempt_id": str(attempt.id), "sequence": attempt.sequence, "lease_fence": lease_fence},
                )
            )
            session.commit()
            return attempt
        except BidDeltaServiceError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise _error("processing_failed", "입찰 delta 작업을 완료할 수 없습니다", status_code=500) from exc

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        if hasattr(value, "__dict__"):
            return vars(value)
        raise ValueError("item must be a mapping")

    @staticmethod
    def _evidence_rows(raw: Mapping[str, Any], side: str) -> list[Mapping[str, Any]]:
        direct = raw.get(f"{side}_evidence")
        if direct is not None:
            if isinstance(direct, (str, bytes, Mapping)) or not isinstance(direct, Sequence):
                raise _error("bid_delta_evidence_invalid", "evidence가 올바르지 않습니다", status_code=422)
            try:
                return [BidDeltaService._mapping(item) for item in direct]
            except (TypeError, ValueError) as exc:
                raise _error("bid_delta_evidence_invalid", "evidence가 올바르지 않습니다", status_code=422) from exc
        shared = raw.get("evidence")
        if shared is None:
            return []
        if isinstance(shared, (str, bytes, Mapping)) or not isinstance(shared, Sequence):
            raise _error("bid_delta_evidence_invalid", "evidence가 올바르지 않습니다", status_code=422)
        rows: list[Mapping[str, Any]] = []
        try:
            for item in shared:
                mapped = BidDeltaService._mapping(item)
                if mapped.get("side") == side:
                    rows.append(mapped)
        except (TypeError, ValueError) as exc:
            raise _error("bid_delta_evidence_invalid", "evidence가 올바르지 않습니다", status_code=422) from exc
        return rows

    def complete_attempt(self, session: Session, attempt_id: UUID, items: Sequence[Any]) -> BidDeltaComparison:
        try:
            items = list(items)
            attempt = session.scalar(select(BidDeltaAttempt).where(BidDeltaAttempt.id == attempt_id).with_for_update())
            if attempt is None:
                raise _error("bid_delta_attempt_not_found", "attempt를 찾을 수 없습니다", status_code=404)
            comparison = session.scalar(select(BidDeltaComparison).where(BidDeltaComparison.id == attempt.comparison_id).with_for_update())
            if comparison is None or comparison.current_attempt_id != attempt.id or attempt.status != "running" or comparison.calculation_status != "running":
                raise _error("bid_delta_attempt_fence_conflict", "attempt 입력 상태가 변경되었습니다", status_code=409)
            binding = resolve_runtime_binding()
            if attempt.runtime_binding_id != binding.binding_id or attempt.runtime_binding_digest != binding.digest:
                raise _error("bid_delta_service_unavailable", "입찰 delta 서비스를 사용할 수 없습니다", status_code=503)
            try:
                raw_items = [self._mapping(item) for item in items]
            except (TypeError, ValueError) as exc:
                raise _error("bid_delta_item_invalid", "item이 올바르지 않습니다", status_code=422) from exc
            categories = [item.get("category") for item in raw_items]
            if len(categories) != len(BID_DELTA_CATEGORIES) or not all(isinstance(category, str) for category in categories) or set(categories) != set(BID_DELTA_CATEGORIES):
                raise _error("bid_delta_categories_invalid", "모든 category가 정확히 한 번 필요합니다", status_code=422)
            normalized: list[tuple[Mapping[str, Any], str, int]] = []
            seen_ordinals: set[int] = set()
            for raw in raw_items:
                category = raw.get("category")
                if not isinstance(category, str) or category not in BID_DELTA_CATEGORIES:
                    raise _error("bid_delta_categories_invalid", "모든 category가 정확히 한 번 필요합니다", status_code=422)
                ordinal = raw.get("ordinal", BID_DELTA_CATEGORIES.index(category) + 1)
                if not isinstance(ordinal, int) or ordinal < 1 or ordinal in seen_ordinals:
                    raise _error("bid_delta_categories_invalid", "category ordinal이 올바르지 않습니다", status_code=422)
                seen_ordinals.add(ordinal)
                result_status = raw.get("result_status")
                materiality = raw.get("materiality")
                if result_status not in {"changed", "unchanged", "unknown", "failed"}:
                    raise _error("bid_delta_item_invalid", "item 결과가 올바르지 않습니다", status_code=422)
                if materiality not in {"material", "non_material", "unknown"}:
                    raise _error("bid_delta_item_invalid", "item materiality가 올바르지 않습니다", status_code=422)
                if result_status == "unchanged" and materiality != "non_material":
                    raise _error("bid_delta_item_invalid", "item materiality가 올바르지 않습니다", status_code=422)
                if result_status in {"unknown", "failed"} and (materiality != "unknown" or not str(raw.get("error_code") or "").strip()):
                    raise _error("bid_delta_item_invalid", "불확실한 item에는 안전한 error code가 필요합니다", status_code=422)
                if result_status in {"changed", "unchanged"} and raw.get("error_code") is not None:
                    raise _error("bid_delta_item_invalid", "성공 item에는 error code가 없어야 합니다", status_code=422)
                if result_status in {"unknown", "failed"} and not _SAFE_ERROR_CODE.fullmatch(str(raw.get("error_code"))):
                    raise _error("bid_delta_item_invalid", "item error code가 올바르지 않습니다", status_code=422)
                normalized.append((raw, result_status, ordinal))
            if len(seen_ordinals) != len(BID_DELTA_CATEGORIES):
                raise _error("bid_delta_categories_invalid", "category ordinal이 올바르지 않습니다", status_code=422)

            baseline_fence = {
                "document_version_id": comparison.baseline_document_version_id,
                "structure_id": comparison.baseline_structure_id,
                "source_sha256": comparison.baseline_source_sha256,
            }
            comparison_fence = {
                "document_version_id": comparison.comparison_document_version_id,
                "structure_id": comparison.comparison_structure_id,
                "source_sha256": comparison.comparison_source_sha256,
            }
            for raw, result_status, ordinal in normalized:
                if result_status in {"changed", "unchanged"}:
                    for side, fence in (("baseline", baseline_fence), ("comparison", comparison_fence)):
                        evidence = self._evidence_rows(raw, side)
                        if not any(
                            row.get("verification_status") == "verified"
                            and str(row.get("document_version_id")) == str(fence["document_version_id"])
                            and str(row.get("structure_id")) == str(fence["structure_id"])
                            and row.get("source_sha256") == fence["source_sha256"]
                            for row in evidence
                        ):
                            raise _error("bid_delta_evidence_invalid", "완료 item에 양쪽 verified evidence가 필요합니다", status_code=422)

            created_items: list[BidDeltaItem] = []
            for raw, result_status, ordinal in normalized:
                item = BidDeltaItem(
                    id=uuid4(),
                    comparison_id=comparison.id,
                    attempt_id=attempt.id,
                    category=str(raw["category"]),
                    ordinal=ordinal,
                    result_status=result_status,
                    materiality=str(raw["materiality"]),
                    before_value=raw.get("before_value"),
                    after_value=raw.get("after_value"),
                    summary=raw.get("summary"),
                    error_code=raw.get("error_code"),
                    created_at=_now(),
                )
                session.add(item)
                created_items.append(item)
            session.flush()
            for (raw, _result_status, _ordinal), item in zip(normalized, created_items):
                for side in ("baseline", "comparison"):
                    for evidence_index, row in enumerate(self._evidence_rows(raw, side), start=1):
                        try:
                            document_id = UUID(str(row.get("document_version_id")))
                            structure_id = UUID(str(row.get("structure_id")))
                        except (TypeError, ValueError, AttributeError) as exc:
                            raise _error("bid_delta_evidence_invalid", "evidence가 올바르지 않습니다", status_code=422) from exc
                        source_sha256 = row.get("source_sha256")
                        locator_type = row.get("locator_type")
                        locator = row.get("locator")
                        verification_status = row.get("verification_status")
                        if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256) or not isinstance(locator, Mapping) or locator_type not in {"page", "paragraph", "table_cell", "bbox"} or verification_status not in {"verified", "missing", "mismatch"}:
                            raise _error("bid_delta_evidence_invalid", "evidence가 올바르지 않습니다", status_code=422)
                        session.add(
                            BidDeltaEvidence(
                                id=uuid4(),
                                item_id=item.id,
                                side=side,
                                ordinal=evidence_index,
                                document_version_id=document_id,
                                structure_id=structure_id,
                                source_sha256=source_sha256,
                                locator_type=locator_type,
                                locator=dict(locator),
                                quote=row.get("quote"),
                                verification_status=verification_status,
                                created_at=_now(),
                            )
                        )
            session.flush()
            result_statuses = [item.result_status for item in created_items]
            overall_result = "unknown" if any(status in {"unknown", "failed"} for status in result_statuses) else "changed" if "changed" in result_statuses else "unchanged"
            if overall_result == "unchanged":
                overall_materiality = "non_material"
            elif overall_result == "unknown":
                overall_materiality = "unknown"
            elif any(item.materiality == "material" for item in created_items):
                overall_materiality = "material"
            elif any(item.materiality == "unknown" for item in created_items):
                overall_materiality = "unknown"
            else:
                overall_materiality = "non_material"
            projection = [
                {
                    "category": item.category,
                    "ordinal": item.ordinal,
                    "result_status": item.result_status,
                    "materiality": item.materiality,
                    "before_value": item.before_value,
                    "after_value": item.after_value,
                    "summary": item.summary,
                    "error_code": item.error_code,
                }
                for item in sorted(created_items, key=lambda row: BID_DELTA_CATEGORIES.index(row.category))
            ]
            result_digest = _sha256(projection)
            now = _now()
            attempt.status = "completed"
            attempt.completed_at = now
            attempt.last_error_code = None
            comparison.calculation_status = "completed"
            comparison.result_status = overall_result
            comparison.materiality = overall_materiality
            comparison.result_sha256 = result_digest
            comparison.last_error_code = None
            comparison.completed_at = now
            counts = {category: dict(Counter(item.result_status for item in created_items if item.category == category)) for category in BID_DELTA_CATEGORIES}
            session.add(
                AuditEvent(
                    actor_kind="system",
                    claimed_name=None,
                    action="bid_delta.comparison_completed",
                    aggregate_type="bid_delta_comparison",
                    aggregate_id=str(comparison.id),
                    request_id=None,
                    safe_metadata={
                        "comparison_id": str(comparison.id),
                        "result_status": overall_result,
                        "materiality": overall_materiality,
                        "category_status_counts": counts,
                        "result_sha256": result_digest,
                        "runtime_binding_id": attempt.runtime_binding_id,
                        "runtime_binding_digest": attempt.runtime_binding_digest,
                    },
                )
            )
            session.commit()
            return comparison
        except BidDeltaServiceError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise _error("processing_failed", "입찰 delta 작업을 완료할 수 없습니다", status_code=500) from exc

    def fail_attempt(self, session: Session, attempt_id: UUID, error_code: str) -> BidDeltaComparison:
        try:
            attempt = session.scalar(select(BidDeltaAttempt).where(BidDeltaAttempt.id == attempt_id).with_for_update())
            if attempt is None:
                raise _error("bid_delta_attempt_not_found", "attempt를 찾을 수 없습니다", status_code=404)
            comparison = session.scalar(select(BidDeltaComparison).where(BidDeltaComparison.id == attempt.comparison_id).with_for_update())
            if comparison is None or comparison.current_attempt_id != attempt.id:
                raise _error("bid_delta_attempt_fence_conflict", "attempt 입력 상태가 변경되었습니다", status_code=409)
            if attempt.status not in {"queued", "running"}:
                raise _error("bid_delta_attempt_fence_conflict", "terminal attempt는 다시 실패 처리할 수 없습니다", status_code=409)
            safe_code = _safe_error_code(error_code)
            now = _now()
            attempt.status = "failed"
            attempt.completed_at = now
            attempt.last_error_code = safe_code
            comparison.calculation_status = "failed"
            comparison.result_status = "failed"
            comparison.materiality = "unknown"
            comparison.result_sha256 = None
            comparison.last_error_code = safe_code
            comparison.completed_at = now
            session.add(
                AuditEvent(
                    actor_kind="system",
                    claimed_name=None,
                    action="bid_delta.comparison_failed",
                    aggregate_type="bid_delta_comparison",
                    aggregate_id=str(comparison.id),
                    request_id=None,
                    safe_metadata={"comparison_id": str(comparison.id), "attempt_id": str(attempt.id), "error_code": safe_code},
                )
            )
            session.commit()
            return comparison
        except BidDeltaServiceError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise _error("processing_failed", "입찰 delta 작업을 완료할 수 없습니다", status_code=500) from exc

    def record_final_decision(
        self,
        session: Session,
        opportunity_id: int,
        comparison_id: UUID,
        payload: BidFinalDecisionCreateRequest,
        actor: str | None,
        actor_format: str | None = None,
    ) -> dict[str, Any]:
        claimed_name = self._actor(actor, actor_format, payload.request_id)
        if not payload.reason.strip():
            raise _error("final_decision_reason_required", "최종 결정 사유가 필요합니다", status_code=400, request_id=payload.request_id)
        if payload.decision not in {"go", "no_go"}:
            raise _error("final_decision_value_invalid", "최종 결정 값이 올바르지 않습니다", status_code=422, request_id=payload.request_id)
        request_hash = _request_hash(payload)
        try:
            opportunity = self._opportunity(session, opportunity_id)
            comparison = session.scalar(select(BidDeltaComparison).where(BidDeltaComparison.id == comparison_id).with_for_update())
            if comparison is None:
                raise _error("bid_delta_comparison_not_found", "비교를 찾을 수 없습니다", status_code=404, request_id=payload.request_id)
            if comparison.opportunity_id != opportunity.id:
                raise _error("bid_delta_comparison_scope_conflict", "비교의 사업기회 범위가 다릅니다", status_code=409, request_id=payload.request_id)
            duplicate = self._idempotent(
                session,
                operation="bid_final_decision",
                aggregate_type="opportunity",
                aggregate_id=str(opportunity.id),
                actor=claimed_name,
                request_id=payload.request_id,
                request_hash=request_hash,
            )
            if duplicate is not None:
                session.commit()
                return duplicate
            if comparison.calculation_status != "completed" or comparison.result_status == "failed":
                raise _error("bid_delta_comparison_not_completed", "완료된 비교만 최종 결정할 수 있습니다", status_code=409, request_id=payload.request_id)
            if comparison.version != payload.expected_comparison_version:
                raise _error("bid_delta_version_conflict", "비교 버전이 변경되었습니다", status_code=409, request_id=payload.request_id)
            if comparison.result_sha256 != payload.expected_result_sha256:
                raise _error("bid_delta_result_digest_conflict", "비교 결과 digest가 변경되었습니다", status_code=409, request_id=payload.request_id)
            if payload.baseline_document_version_id != comparison.baseline_document_version_id or payload.comparison_document_version_id != comparison.comparison_document_version_id:
                raise _error("final_decision_input_fence_invalid", "최종 결정 입력 fence가 비교와 다릅니다", status_code=422, request_id=payload.request_id)
            currentness, reasons = self._currentness(session, comparison)
            if currentness == "stale":
                raise _error("bid_delta_comparison_stale", "새로운 비교 입력이 있어 재검토가 필요합니다", status_code=409, request_id=payload.request_id)
            if currentness == "unknown":
                raise _error("bid_delta_currentness_unavailable", "비교 현재성을 확인할 수 없습니다", status_code=503, request_id=payload.request_id)
            latest = session.scalar(
                select(BidFinalDecision)
                .where(BidFinalDecision.opportunity_id == opportunity.id)
                .order_by(BidFinalDecision.sequence.desc(), BidFinalDecision.id.desc())
                .with_for_update()
                .limit(1)
            )
            if payload.supersedes_final_decision_id is not None and session.get(BidFinalDecision, payload.supersedes_final_decision_id) is None:
                raise _error("final_decision_not_found", "앞선 최종 결정을 찾을 수 없습니다", status_code=404, request_id=payload.request_id)
            if (latest is None and payload.supersedes_final_decision_id is not None) or (latest is not None and payload.supersedes_final_decision_id != latest.id):
                raise _error("final_decision_supersession_conflict", "최종 결정의 supersession 대상이 변경되었습니다", status_code=409, request_id=payload.request_id)
            sequence = int(
                session.scalar(select(func.max(BidFinalDecision.sequence)).where(BidFinalDecision.opportunity_id == opportunity.id)) or 0
            ) + 1
            decision = BidFinalDecision(
                id=uuid4(),
                opportunity_id=opportunity.id,
                sequence=sequence,
                comparison_id=comparison.id,
                comparison_version=comparison.version,
                result_sha256=comparison.result_sha256,
                baseline_document_version_id=comparison.baseline_document_version_id,
                comparison_document_version_id=comparison.comparison_document_version_id,
                supersedes_final_decision_id=payload.supersedes_final_decision_id,
                decision=payload.decision,
                reason=payload.reason,
                claimed_name=claimed_name,
                request_id=payload.request_id,
                created_at=_now(),
            )
            session.add(decision)
            session.flush()
            response = _jsonable(self._decision_view(decision, currentness, reasons))
            session.add(
                AuditEvent(
                    actor_kind="human",
                    claimed_name=claimed_name,
                    action="bid_final_decision.recorded",
                    aggregate_type="bid_final_decision",
                    aggregate_id=str(decision.id),
                    request_id=str(payload.request_id),
                    safe_metadata={
                        "decision_id": str(decision.id),
                        "opportunity_id": opportunity.id,
                        "comparison_id": str(comparison.id),
                        "sequence": decision.sequence,
                        "decision": decision.decision,
                        "supersedes_final_decision_id": str(decision.supersedes_final_decision_id) if decision.supersedes_final_decision_id else None,
                    },
                )
            )
            session.add(
                IdempotencyRecord(
                    operation="bid_final_decision",
                    aggregate_type="opportunity",
                    aggregate_id=str(opportunity.id),
                    claimed_name=claimed_name,
                    request_id=payload.request_id,
                    request_sha256=request_hash,
                    response_status=201,
                    response_snapshot=response,
                )
            )
            session.commit()
            return response
        except BidDeltaServiceError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            duplicate = self._idempotent(
                session,
                operation="bid_final_decision",
                aggregate_type="opportunity",
                aggregate_id=str(opportunity_id),
                actor=claimed_name,
                request_id=payload.request_id,
                request_hash=request_hash,
            )
            if duplicate is not None:
                session.commit()
                return duplicate
            raise _error("final_decision_supersession_conflict", "동시에 다른 최종 결정이 생성되었습니다", status_code=409, request_id=payload.request_id) from exc
        except Exception as exc:
            session.rollback()
            raise _error("processing_failed", "최종 결정을 기록할 수 없습니다", status_code=500, request_id=payload.request_id) from exc


__all__ = [
    "BASELINE_DOCUMENT_ROLES",
    "BID_DELTA_CATEGORIES",
    "COMPARISON_DOCUMENT_ROLES",
    "SUPPORTED_CATEGORY_POLICY_VERSIONS",
    "BidDeltaService",
    "BidDeltaServiceError",
    "resolve_runtime_binding",
]
