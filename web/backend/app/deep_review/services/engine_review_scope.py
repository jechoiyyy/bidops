"""Scope shared by review commands, attachment claims and document preparation."""

from sqlalchemy import String, and_, cast, false, or_, select
from sqlalchemy.orm import aliased

from ...core.config import get_settings
from ...core.models import AuditEvent
from ...lifecycle import active_opportunity_predicate, authoritative_link_predicate
from ...lifecycle.models import Notice, Opportunity, OpportunityLink
from ..models import EngineReviewRequest

TRACKING = "계속 추적"
TRACKING_ACTIVE_STATUSES = (TRACKING, "보류")
TRACKING_ENDED_STATUSES = ("종료", "미선택")


def latest_pre_spec():
    """A registration can have legacy duplicate keys. Distinct registrations stay separate."""
    other = aliased(Notice)
    number = Notice.lifecycle_json["pre_spec_no"].as_string()
    return ~select(other.id).where(
        other.source_type == "pre_spec",
        number.is_not(None),
        number != "",
        other.lifecycle_json["pre_spec_no"].as_string() == number,
        or_(
            other.published_at > Notice.published_at,
            and_(other.published_at.is_not(None), Notice.published_at.is_(None)),
            and_(other.published_at.is_not_distinct_from(Notice.published_at), other.id > Notice.id),
        ),
    ).exists()


def tracking_ended_since(opportunity_id, requested_at):
    """Use the durable tracking decision, including an end followed by a restart."""
    return select(AuditEvent.id).where(
        AuditEvent.aggregate_type == "opportunity",
        AuditEvent.aggregate_id == cast(opportunity_id, String),
        AuditEvent.action == "opportunity.tracking_status.changed",
        AuditEvent.created_at > requested_at,
        AuditEvent.safe_metadata["tracking_status"].as_string().in_(TRACKING_ENDED_STATUSES),
    ).exists()


def _enabled(settings):
    return (
        getattr(settings, "engine_review_mode", "off") != "off"
        and getattr(settings, "engine_analysis_enabled", False)
        and bool(settings.engine_company_bundle_slug)
    )


def open_review_request_predicate(notice_id):
    settings = get_settings()
    if not _enabled(settings):
        return false()
    link, owner = aliased(OpportunityLink), aliased(Opportunity)
    request = (
        select(EngineReviewRequest.id)
        .join(link, link.notice_id == EngineReviewRequest.notice_id)
        .join(owner, owner.id == link.opportunity_id)
        .where(
            EngineReviewRequest.notice_id == notice_id,
            EngineReviewRequest.closed_at.is_(None),
            EngineReviewRequest.company_bundle_slug == settings.engine_company_bundle_slug,
            owner.id == EngineReviewRequest.opportunity_id,
            owner.tracking_status.in_(TRACKING_ACTIVE_STATUSES),
            link.stage == "notice",
            authoritative_link_predicate(link),
            active_opportunity_predicate(owner),
            ~tracking_ended_since(EngineReviewRequest.opportunity_id, EngineReviewRequest.requested_at),
        ).exists()
    )
    return and_(Notice.review_exclusion_status != "excluded", latest_pre_spec(), request)


def open_review_notice_ids(session, notice_ids):
    if not notice_ids or not _enabled(get_settings()):
        return frozenset()
    return frozenset(session.scalars(select(Notice.id).where(
        Notice.id.in_(notice_ids), open_review_request_predicate(Notice.id),
    )))
