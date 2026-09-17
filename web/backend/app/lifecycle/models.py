"""lifecycle이 소유하는 선언적 모델 (명세 §5.1의 10개 테이블 + 수집 색인 2개).

회차, 공고, 발주계획, 관측, 기회와 기회 연결, 첨부 메타, 기관 포털, 적재
경고가 여기 있다. lifecycle 모델은 다른 모듈의 모델로 향하는 ``relationship``을
갖지 않는다. 관계는 소유 모듈이 자기 모델에서 단방향으로 선언하므로,
screening·deep_review를 import하지 않아도 mapper 구성이 성공한다 (명세 §4).

이 파일의 모델 클래스는 lifecycle의 **공개 이름**이다. screening·deep_review는
여기서 ``Notice``·``Run``·``OrderPlan``을 가져다 읽고 join해도 되지만, 쓰기와
잠금은 ``app.lifecycle``이 공개한 함수로만 한다.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    column,
    event,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session as OrmSession, mapped_column, relationship, synonym

from ..core.db import Base
from ..core.models import AwareDateTime, JSONB_COMPAT, _fk, utc_now
from ..core.sql_dialect import dual


# ---------------------------------------------------------------------------
# 회차·공고·발주계획 원본 투영 (legacy 13개 중 lifecycle 몫, 원본 컬럼 전부 보존)
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "run"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul", nullable=False)
    generated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    # Legacy workflow artifacts store a human-readable explanation here, not a
    # short enum.  Preserve it verbatim during PostgreSQL cutover.
    screening_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(_fk("run.id", ondelete="SET NULL"), nullable=True)
    counts_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB_COMPAT, nullable=True)

    # A Run is an observation context, not the owner of a cumulative Notice.
    # The secondary relationship is intentionally not delete-orphan: deleting
    # a run removes its observation rows, but never the canonical notice.
    notices: Mapped[list["Notice"]] = relationship(
        "Notice",
        secondary="notice_observation",
        back_populates="runs",
        passive_deletes=True,
        overlaps="notice_observations,observations",
    )
    notice_observations: Mapped[list["NoticeObservation"]] = relationship(
        back_populates="run", passive_deletes="all", overlaps="notices,runs"
    )
    order_plans: Mapped[list["OrderPlan"]] = relationship(
        "OrderPlan",
        secondary="order_plan_observation",
        back_populates="runs",
        passive_deletes=True,
        overlaps="order_plan_observations,observations",
    )
    order_plan_observations: Mapped[list["OrderPlanObservation"]] = relationship(
        back_populates="run", passive_deletes="all", overlaps="order_plans,runs"
    )
    warnings: Mapped[list["IngestWarning"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


    # 판정·리뷰·revision 은 선별 모듈의 테이블이다. lifecycle 모델은 다른 모듈의
    # 모델로 향하는 relationship 을 갖지 않으며, 관계는 소유 모듈이 자기 모델에서
    # 단방향으로 선언한다(명세 §4). 회차 범위의 판정·리뷰는 선별이 공개하는
    # projection·seam 으로 읽는다.


class Notice(Base):
    __tablename__ = "notice"
    __table_args__ = (
        Index("ix_notice_collection_sample", "collection_bucket", "sample_role"),
        Index("ix_notice_notice_key", "notice_key"),
        Index("ix_notice_deadline_at", "deadline_at"),
        UniqueConstraint("notice_key", name="uq_notice_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_key: Mapped[str] = mapped_column(String(255), nullable=False)
    bid_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bid_ord: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 사전규격 원문 ``rlDminsttNm``(수요기관). 사전규격 ``agency``는 발주기관이고
    # 입찰공고 ``agency``는 이미 수요기관이라 입찰공고에서는 항상 비어 있다.
    # 관측 snapshot에는 넣지 않는다(적재기 ``_upsert_notice`` 참고).
    demand_agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    estimated_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample_stratum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    collection_bucket: Mapped[str | None] = mapped_column(String(64), nullable=True)
    procurement_class_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    region_limit_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    lifecycle_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    qualification_flags_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    focus_matches_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    performance_matches_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    performance_top_score: Mapped[float | None] = mapped_column(nullable=True)
    candidate_sources_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    unknown_fields_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    raw_source: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)

    observations: Mapped[list["NoticeObservation"]] = relationship(
        back_populates="notice", cascade="all, delete-orphan", overlaps="runs,notices"
    )
    runs: Mapped[list["Run"]] = relationship(
        "Run",
        secondary="notice_observation",
        back_populates="notices",
        passive_deletes="all",
        overlaps="observations,notice_observations,run",
    )

    # These two properties are a narrow construction-time compatibility
    # boundary for legacy isolated tests/import callers.  They do not map a
    # database column.  ``before_flush`` below turns ``run_id=...`` into an
    # observation when the referenced Run exists; all application queries use
    # NoticeObservation instead.
    @property
    def run(self) -> "Run | None":
        runs = self.runs
        if runs:
            return runs[0]
        return self.__dict__.get("_legacy_run")

    @run.setter
    def run(self, value: "Run | None") -> None:
        self.__dict__["_legacy_run"] = value
        if value is not None:
            runs = self.runs
            if value not in runs:
                runs.append(value)

    @property
    def run_id(self) -> str | None:
        run = self.run
        if run is not None:
            return run.id
        return self.__dict__.get("_legacy_run_id")

    @run_id.setter
    def run_id(self, value: str | None) -> None:
        self.__dict__["_legacy_run_id"] = value

    @property
    def first_observed_at(self) -> datetime | None:
        return min((item.observed_at for item in self.observations), default=None)

    @property
    def last_observed_at(self) -> datetime | None:
        return max((item.observed_at for item in self.observations), default=None)

    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="notice", cascade="all, delete-orphan"
    )
    # 판정·리뷰·revision(선별)과 개요 검토(심층 검토)는 각각 그 모듈이 소유하므로
    # 여기서 역방향 relationship 을 갖지 않는다(§4). 공고가 지워질 때의 정리는 ORM
    # cascade 가 아니라 각 테이블의 FK ``ondelete="CASCADE"`` 가 맡는다.
    opportunity_links: Mapped[list["OpportunityLink"]] = relationship(
        back_populates="notice", passive_deletes=True
    )


class NoticeObservation(Base):
    """One immutable observation of a cumulative external notice identity."""

    __tablename__ = "notice_observation"
    __table_args__ = (
        UniqueConstraint("notice_id", "run_id", name="uq_notice_observation_notice_run"),
        Index("ix_notice_observation_run", "run_id"),
        Index("ix_notice_observation_notice", "notice_id"),
        CheckConstraint(
            "((snapshot_schema_version IS NULL AND snapshot_jsonb IS NULL AND source_sha256 IS NULL) OR "
            "(snapshot_schema_version IS NOT NULL AND length(trim(snapshot_schema_version)) > 0 "
            "AND snapshot_jsonb IS NOT NULL AND source_sha256 IS NOT NULL))",
            name="ck_notice_observation_snapshot_pair",
        ),
        CheckConstraint(
            dual(
                "source_sha256 IS NULL OR (length(source_sha256) = 64 "
                "AND source_sha256 NOT GLOB '*[^0-9a-f]*')"
            ),
            name="ck_notice_observation_source_sha256",
        ),
        CheckConstraint(
            dual(
                "snapshot_jsonb IS NULL OR "
                "(json_valid(snapshot_jsonb) AND json_type(snapshot_jsonb) = 'object')"
            ),
            name="ck_notice_observation_snapshot_object",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str] = mapped_column(_fk("run.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    changed_fields_json: Mapped[list[str] | dict[str, Any]] = mapped_column(
        JSONB_COMPAT, default=list, server_default=text("'[]'"), nullable=False
    )
    snapshot_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    notice: Mapped["Notice"] = relationship(
        back_populates="observations", overlaps="runs,notices"
    )
    run: Mapped["Run"] = relationship(
        back_populates="notice_observations", overlaps="runs,notices"
    )


class OrderPlan(Base):
    """Cumulative identity projection for an external order-plan number.

    The columns below are the fields selected by the measured order-plan
    normalizer.  Contact fields and the remaining response payload stay in
    ``raw_source``/``unknown_fields_json`` rather than becoming guessed
    schema.
    """

    __tablename__ = "order_plan"
    __table_args__ = (
        UniqueConstraint("order_plan_unty_no", name="uq_order_plan_unty_no"),
        Index("ix_order_plan_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_plan_unty_no: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    agency_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supervising_agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_division: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_division_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    service_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    planned_order_year: Mapped[str | None] = mapped_column(String(4), nullable=True)
    planned_order_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    procurement_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contract_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    bid_ntice_no_list: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_posted: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_discovered_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    last_discovered_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unknown_fields_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    raw_source: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)

    # Names used by the offline normalizer remain available without creating
    # duplicate physical columns.
    plan_id = synonym("order_plan_unty_no")
    business_name = synonym("title")
    biz_nm = synonym("title")
    bidNtceNoList = synonym("bid_ntice_no_list")
    ntceNticeYn = synonym("notice_posted")
    # Retain the earlier misspelling as a read-only compatibility alias.
    nticeNticeYn = synonym("notice_posted")

    observations: Mapped[list["OrderPlanObservation"]] = relationship(
        back_populates="order_plan", cascade="all, delete-orphan", overlaps="runs,notices"
    )
    runs: Mapped[list["Run"]] = relationship(
        "Run",
        secondary="order_plan_observation",
        back_populates="order_plans",
        passive_deletes="all",
        overlaps="observations,order_plan_observations,run",
    )
    opportunity_links: Mapped[list["OpportunityLink"]] = relationship(
        back_populates="order_plan", passive_deletes=True
    )


class OrderPlanObservation(Base):
    """A run-scoped observation of one cumulative order plan."""

    __tablename__ = "order_plan_observation"
    __table_args__ = (
        UniqueConstraint("order_plan_id", "run_id", name="uq_order_plan_observation_plan_run"),
        Index("ix_order_plan_observation_run", "run_id"),
        Index("ix_order_plan_observation_plan", "order_plan_id"),
        CheckConstraint(
            "((snapshot_schema_version IS NULL AND snapshot_jsonb IS NULL AND source_sha256 IS NULL) OR "
            "(snapshot_schema_version IS NOT NULL AND length(trim(snapshot_schema_version)) > 0 "
            "AND snapshot_jsonb IS NOT NULL AND source_sha256 IS NOT NULL))",
            name="ck_order_plan_observation_snapshot_pair",
        ),
        CheckConstraint(
            dual(
                "source_sha256 IS NULL OR (length(source_sha256) = 64 "
                "AND source_sha256 NOT GLOB '*[^0-9a-f]*')"
            ),
            name="ck_order_plan_observation_source_sha256",
        ),
        CheckConstraint(
            dual(
                "snapshot_jsonb IS NULL OR "
                "(json_valid(snapshot_jsonb) AND json_type(snapshot_jsonb) = 'object')"
            ),
            name="ck_order_plan_observation_snapshot_object",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_plan_id: Mapped[int] = mapped_column(_fk("order_plan.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str] = mapped_column(_fk("run.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    changed_fields_json: Mapped[list[str] | dict[str, Any]] = mapped_column(
        JSONB_COMPAT, default=list, server_default=text("'[]'"), nullable=False
    )
    snapshot_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    order_plan: Mapped["OrderPlan"] = relationship(
        back_populates="observations", overlaps="runs,order_plans"
    )
    run: Mapped["Run"] = relationship(
        back_populates="order_plan_observations", overlaps="runs,order_plans"
    )


class Opportunity(Base):
    """Internal identity joining records from the procurement lifecycle.

    ``first_registered_stage`` is deliberately a stored fact rather than a
    UI-derived label.  It records whether this opportunity entered BidOps
    from an order plan, an independently collected pre-specification, or a
    bid notice observed before either upstream record.
    """

    __tablename__ = "opportunity"
    __table_args__ = (
        CheckConstraint(
            "first_registered_stage IN ('order_plan', 'pre_spec', 'bid_notice')",
            name="ck_opportunity_first_registered_stage",
        ),
        CheckConstraint(
            "tracking_status IN ('미선택', '계속 추적', '보류', '종료')",
            name="ck_opportunity_tracking_status",
        ),
        CheckConstraint(
            "((tracking_status = '미선택' AND tracking_selected_by IS NULL "
            "AND tracking_reason IS NULL AND tracking_selected_at IS NULL) OR "
            "(tracking_status <> '미선택' AND tracking_selected_by IS NOT NULL "
            "AND length(trim(tracking_selected_by)) > 0 "
            "AND tracking_selected_at IS NOT NULL))",
            name="ck_opportunity_tracking_metadata",
        ),
        CheckConstraint(
            "(recheck_signal_at IS NULL AND recheck_signal_link_id IS NULL) OR "
            "(recheck_signal_at IS NOT NULL AND recheck_signal_link_id IS NOT NULL)",
            name="ck_opportunity_recheck_signal_pair",
        ),
        CheckConstraint(
            "((merged_into_opportunity_id IS NULL AND merged_at IS NULL "
            "AND merge_reason IS NULL) OR "
            "(merged_into_opportunity_id IS NOT NULL AND merged_at IS NOT NULL "
            "AND merge_reason IS NOT NULL AND length(trim(merge_reason)) > 0))",
            name="ck_opportunity_merge_metadata",
        ),
        CheckConstraint(
            "merged_into_opportunity_id IS NULL OR merged_into_opportunity_id <> id",
            name="ck_opportunity_not_merged_into_self",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_registered_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    # This is a human selection only.  ``미선택`` means that nobody has made
    # a tracking choice yet; it is not the same as 관심 없음 or 미추적, and
    # it must not be inferred from grade or readiness.
    tracking_status: Mapped[str] = mapped_column(
        String(32), default="미선택", server_default=text("'미선택'"), nullable=False
    )
    tracking_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracking_selected_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tracking_selected_at: Mapped[datetime | None] = mapped_column(
        AwareDateTime(), nullable=True
    )
    # A recheck signal is system-produced state kept apart from the human
    # tracking choice.  Its link FK lets consumers walk to the exact official
    # lifecycle record that caused the signal.
    recheck_signal_at: Mapped[datetime | None] = mapped_column(
        AwareDateTime(), nullable=True
    )
    recheck_signal_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunity_link.id", ondelete="RESTRICT"), nullable=True
    )
    merged_into_opportunity_id: Mapped[int | None] = mapped_column(
        _fk("opportunity.id", ondelete="RESTRICT"), nullable=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    merge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    # These aliases keep the stored fact explicit while making the lifecycle
    # terminology used by ADR-0022 easy to consume without extra columns.
    origin_stage = synonym("first_registered_stage")
    first_seen_stage = synonym("first_registered_stage")
    links: Mapped[list["OpportunityLink"]] = relationship(
        back_populates="opportunity",
        cascade="all, delete-orphan",
        foreign_keys="OpportunityLink.opportunity_id",
    )
    recheck_signal_link: Mapped["OpportunityLink | None"] = relationship(
        "OpportunityLink",
        foreign_keys=[recheck_signal_link_id],
        uselist=False,
        overlaps="links,opportunity",
    )
    merged_into_opportunity: Mapped["Opportunity | None"] = relationship(
        "Opportunity",
        remote_side=[id],
        foreign_keys=[merged_into_opportunity_id],
        back_populates="merged_opportunities",
    )
    merged_opportunities: Mapped[list["Opportunity"]] = relationship(
        "Opportunity",
        foreign_keys=[merged_into_opportunity_id],
        back_populates="merged_into_opportunity",
    )


class OpportunityLink(Base):
    """A durable relation or search state for one lifecycle record.

    A link points to either an ``order_plan`` or a ``notice``.  A
    ``검색 미확인`` row intentionally has neither target: it records a search
    attempt, not a claim that a target record exists.  An official link may
    also have no target while retaining a non-empty external reference; that
    is a deferred upstream record, not an absence claim.  Candidate rows
    remain addressable after a human rejection, satisfying the record-
    retention rule.
    """

    __tablename__ = "opportunity_link"
    __table_args__ = (
        Index("ix_opportunity_link_opportunity", "opportunity_id"),
        Index("ix_opportunity_link_order_plan", "order_plan_id"),
        Index("ix_opportunity_link_notice", "notice_id"),
        Index(
            "uq_opportunity_link_authoritative_order_plan",
            "order_plan_id",
            unique=True,
            postgresql_where=text(
                "order_plan_id IS NOT NULL AND "
                "((link_type = 'official' AND status = '확정') OR "
                "(link_type = 'candidate' AND status = '사람 확인 완료' "
                "AND human_decision = 'accepted'))"
            ),
            sqlite_where=text(
                "order_plan_id IS NOT NULL AND "
                "((link_type = 'official' AND status = '확정') OR "
                "(link_type = 'candidate' AND status = '사람 확인 완료' "
                "AND human_decision = 'accepted'))"
            ),
        ),
        Index(
            "uq_opportunity_link_authoritative_notice",
            "notice_id",
            unique=True,
            postgresql_where=text(
                "notice_id IS NOT NULL AND "
                "((link_type = 'official' AND status = '확정') OR "
                "(link_type = 'candidate' AND status = '사람 확인 완료' "
                "AND human_decision = 'accepted'))"
            ),
            sqlite_where=text(
                "notice_id IS NOT NULL AND "
                "((link_type = 'official' AND status = '확정') OR "
                "(link_type = 'candidate' AND status = '사람 확인 완료' "
                "AND human_decision = 'accepted'))"
            ),
        ),
        CheckConstraint(
            "stage IN ('order_plan', 'notice')",
            name="ck_opportunity_link_stage",
        ),
        CheckConstraint(
            "link_type IN ('official', 'candidate')",
            name="ck_opportunity_link_type",
        ),
        CheckConstraint(
            "status IN ('확정', '후보 확인 대기', '사람 확인 완료', '검색 미확인', "
            "'사람 확인 병합')",
            name="ck_opportunity_link_status",
        ),
        CheckConstraint(
            "search_strategy IS NULL OR search_strategy IN "
            "('full', 'breaking_split', 'normalized', 'longest_fragment', 'prefix12', "
            "'merge_confirmation')",
            name="ck_opportunity_link_search_strategy",
        ),
        CheckConstraint(
            "search_target_kind IS NULL OR search_target_kind IN ('pre_spec', 'bid_notice')",
            name="ck_opportunity_link_search_target_kind",
        ),
        CheckConstraint(
            "link_type <> 'official' OR status = '확정'",
            name="ck_opportunity_link_official_status",
        ),
        CheckConstraint(
            "link_type <> 'official' OR "
            "(evidence_external_no IS NOT NULL AND length(trim(evidence_external_no)) > 0)",
            name="ck_opportunity_link_official_evidence",
        ),
        CheckConstraint(
            "link_type <> 'candidate' OR status <> '확정'",
            name="ck_opportunity_link_candidate_not_confirmed",
        ),
        CheckConstraint(
            "status = '검색 미확인' OR "
            "(link_type = 'official' AND evidence_external_no IS NOT NULL "
            "AND length(trim(evidence_external_no)) > 0 "
            "AND order_plan_id IS NULL AND notice_id IS NULL) OR "
            "((order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
            "(order_plan_id IS NULL AND notice_id IS NOT NULL))",
            name="ck_opportunity_link_one_target",
        ),
        CheckConstraint(
            "status = '검색 미확인' OR "
            "(link_type = 'official' AND evidence_external_no IS NOT NULL "
            "AND length(trim(evidence_external_no)) > 0 "
            "AND order_plan_id IS NULL AND notice_id IS NULL) OR "
            "(stage = 'order_plan' AND order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
            "(stage = 'notice' AND order_plan_id IS NULL AND notice_id IS NOT NULL)",
            name="ck_opportunity_link_stage_target",
        ),
        CheckConstraint(
            "((status = '검색 미확인' AND order_plan_id IS NULL AND notice_id IS NULL) OR "
            "(status <> '검색 미확인' AND "
            "((order_plan_id IS NOT NULL OR notice_id IS NOT NULL) OR "
            "(link_type = 'official' AND evidence_external_no IS NOT NULL "
            "AND length(trim(evidence_external_no)) > 0 "
            "AND order_plan_id IS NULL AND notice_id IS NULL))))",
            name="ck_opportunity_link_unconfirmed_without_target",
        ),
        CheckConstraint(
            "status <> '검색 미확인' OR (stage = 'notice' AND link_type = 'candidate')",
            name="ck_opportunity_link_search_unconfirmed_kind",
        ),
        CheckConstraint(
            "human_decision IS NULL OR human_decision IN ('accepted', 'rejected')",
            name="ck_opportunity_link_human_decision",
        ),
        CheckConstraint(
            "status <> '사람 확인 완료' OR "
            "(human_decision IS NOT NULL AND reviewer_name IS NOT NULL "
            "AND length(trim(reviewer_name)) > 0 AND reviewed_at IS NOT NULL "
            "AND review_reason IS NOT NULL AND length(trim(review_reason)) > 0)",
            name="ck_opportunity_link_human_review_metadata",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        _fk("opportunity.id", ondelete="CASCADE"), nullable=False
    )
    order_plan_id: Mapped[int | None] = mapped_column(
        _fk("order_plan.id", ondelete="SET NULL"), nullable=True
    )
    notice_id: Mapped[int | None] = mapped_column(
        _fk("notice.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    link_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_external_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ADR-0025 names the bid notice as the provenance for a confirmed
    # pre-specification link.  Keep that provenance separately from the
    # external key that actually matched (for example bfSpecRgstNo).
    evidence_bid_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ``검색 미확인`` 행이 어느 찾아보기(사전규격·입찰공고)의 결과인지 구분한다
    # (spec §4.3). 다른 행에서는 비어 있다.
    search_target_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    agency_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_searched_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    attempted_strategies_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    human_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    # Names in ADR-0025 and in the search-probe artifacts remain available as
    # aliases, without introducing duplicate physical columns.
    relation_type = synonym("link_type")
    evidence_number = synonym("evidence_external_no")
    evidence_notice_no = synonym("evidence_bid_no")
    strategy = synonym("search_strategy")
    agency_name_match = synonym("agency_match")
    attempted_strategies = synonym("attempted_strategies_json")
    reviewer = synonym("reviewer_name")
    review_reason_text = synonym("review_reason")
    opportunity: Mapped["Opportunity"] = relationship(
        back_populates="links", foreign_keys=[opportunity_id]
    )
    order_plan: Mapped["OrderPlan | None"] = relationship(back_populates="opportunity_links")
    notice: Mapped["Notice | None"] = relationship(back_populates="opportunity_links")


@event.listens_for(OrmSession, "before_flush")
def _materialize_legacy_notice_run_ids(session: OrmSession, _flush_context: Any, _instances: Any) -> None:
    """Convert old ``Notice(run_id=...)`` test fixtures into observations.

    This compatibility hook exists only for callers that construct the old
    model shape directly.  It is deliberately not a persistence column and
    cannot make a notice belong to a run unless that Run is present.
    """

    for notice in tuple(session.new):
        if not isinstance(notice, Notice):
            continue
        legacy_run_id = notice.__dict__.get("_legacy_run_id")
        if not legacy_run_id:
            continue
        run = next(
            (candidate for candidate in session.new if isinstance(candidate, Run) and candidate.id == legacy_run_id),
            None,
        )
        if run is None:
            run = session.get(Run, legacy_run_id)
        if run is not None:
            existing = session.scalar(
                select(Notice).where(Notice.notice_key == notice.notice_key)
            )
            if existing is not None and existing is not notice:
                # Old direct-construction callers used a fresh Notice object
                # for every run.  Fold that object into the cumulative row so
                # the compatibility boundary cannot manufacture a duplicate
                # external identity.
                session.expunge(notice)
                existing.run = run
                notice.__dict__.pop("_legacy_run_id", None)
                continue
            notice.run = run
            notice.__dict__.pop("_legacy_run_id", None)


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (
        Index(
            "uq_attachment_notice_source_key",
            "notice_id",
            "source_system",
            "source_attachment_key",
            unique=True,
            postgresql_where=column("source_attachment_key").is_not(None),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_ext: Mapped[str | None] = mapped_column(String(16), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_stored_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extract_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_attachment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    retired_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retired_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    notice_pk = synonym("notice_id")
    url = synonym("source_url")
    stored_path = synonym("legacy_stored_path")
    notice: Mapped["Notice"] = relationship(back_populates="attachments")


class AgencyPortal(Base):
    __tablename__ = "agency_portal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    system_name: Mapped[str] = mapped_column(String(255), nullable=False)
    search_url_template: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollectedRecordIndex(Base):
    """수집 회차의 레코드 한 건을 가리키는 검색용 색인 (spec §2.1).

    선별 적재 여부와 무관하게 수집된 발주계획·사전규격·입찰공고마다 회차당 한 행을
    남긴다. 사업기회나 공고가 아니며 원문도 아니다 — 원문은 회차 파일에 그대로
    있고, 적재가 필요하면 ``run_id``의 회차 파일에서 같은 레코드를 다시 읽는다.
    ``selection_reason``이 비어 있으면 그 회차 적재에서 제외된 레코드다(제외는
    경고가 아니다). ``null`` 값은 추정으로 채우지 않는다.
    """

    __tablename__ = "collected_record_index"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "record_kind", "record_key",
            name="uq_collected_record_index_run_kind_key",
        ),
        CheckConstraint(
            "record_kind IN ('order_plan', 'pre_spec', 'bid_notice')",
            name="ck_collected_record_index_record_kind",
        ),
        CheckConstraint(
            "selection_reason IS NULL OR selection_reason IN ("
            "'order_plan_all', 'pre_spec_sw', 'pre_spec_referenced', "
            "'bid_same_notice_no', 'bid_tracked_reference', "
            "'bid_sw_prespec_reference', 'bid_sw_industry_competitive', "
            "'tracked_backfill', 'search_result')",
            name="ck_collected_record_index_selection_reason",
        ),
        Index("ix_collected_record_index_kind_key", "record_kind", "record_key"),
        Index("ix_collected_record_index_order_plan_unty_no", "order_plan_unty_no"),
        Index("ix_collected_record_index_bf_spec_rgst_no", "bf_spec_rgst_no"),
        Index("ix_collected_record_index_bid_no", "bid_no"),
        Index("ix_collected_record_index_kind_title", "record_kind", "title_normalized"),
        Index("ix_collected_record_index_agency", "agency"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True
    )
    run_id: Mapped[str] = mapped_column(_fk("run.id", ondelete="CASCADE"), nullable=False)
    record_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    demand_agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_plan_unty_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bf_spec_rgst_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bid_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bid_ord: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sw_business_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sw_industry_1468: Mapped[str | None] = mapped_column(String(16), nullable=True)
    contract_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    selection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingested_notice_id: Mapped[int | None] = mapped_column(
        _fk("notice.id", ondelete="SET NULL"), nullable=True
    )
    ingested_order_plan_id: Mapped[int | None] = mapped_column(
        _fk("order_plan.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    tokens: Mapped[list["CollectedRecordToken"]] = relationship(
        back_populates="index_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CollectedRecordToken.id",
    )


class CollectedRecordToken(Base):
    """발주계획·사전규격 ``bidNtceNoList``의 토큰 한 개 (spec §2.1).

    발주계획 토큰은 공고번호 13자+차수 3자, 사전규격 토큰은 공고번호 13자로
    관측됐다. 모양을 고치거나 잘라 내지 않고 원문 토큰 그대로 둔다. 배열 열 대신
    행으로 두어 SQLite·PostgreSQL 모두 인덱스로 조회한다.
    """

    __tablename__ = "collected_record_token"
    __table_args__ = (
        Index("ix_collected_record_token_token", "token"),
        Index("ix_collected_record_token_index", "index_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True
    )
    index_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        _fk("collected_record_index.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(32), nullable=False)

    index_row: Mapped["CollectedRecordIndex"] = relationship(back_populates="tokens")


class IngestWarning(Base):
    __tablename__ = "ingest_warning"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(_fk("run.id", ondelete="CASCADE"), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    context_json = synonym("context_jsonb")
    run: Mapped["Run"] = relationship(back_populates="warnings")


# Added by the cumulative lifecycle-identity migrations.  Keeping these out
# of the legacy/Lean v1 tuples prevents an older revision from creating them
# before its upgrade has established the observation and opportunity links.
OPPORTUNITY_TABLES = ("opportunity", "opportunity_link")
# ``0027_collection_index_and_linkage``가 만든다. 선별 적재의 검색 색인이다.
COLLECTION_INDEX_TABLES = ("collected_record_index", "collected_record_token")


IDENTITY_TABLES = (
    "notice_observation", "order_plan", "order_plan_observation",
    *OPPORTUNITY_TABLES,
    *COLLECTION_INDEX_TABLES,
)


# ``0001_lean_v1_postgresql``이 만드는 13개 legacy 투영 중 lifecycle 몫이다.
# 나머지 8개는 screening이 ``SCREENING_LEGACY_TABLES``로 갖고 있고, 합집합은
# 그 revision과 테스트가 조립한다 (명세 §5.1).
LIFECYCLE_LEGACY_TABLES = (
    "run", "notice", "attachment", "agency_portal", "ingest_warning",
)


# R-08 composite foreign keys need these exact target scopes.  They are
# appended here so the existing lifecycle model declarations remain untouched.
OpportunityLink.__table__.append_constraint(
    UniqueConstraint("id", "opportunity_id", name="uq_opportunity_link_opportunity_scope")
)
OpportunityLink.__table__.append_constraint(
    UniqueConstraint("id", "notice_id", name="uq_opportunity_link_notice_scope")
)
