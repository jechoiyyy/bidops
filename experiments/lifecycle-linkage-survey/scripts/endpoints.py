#!/usr/bin/env python3
"""Endpoint registry for the lifecycle linkage survey.

Each entry fixes one G2B OpenAPI endpoint, the public query it is called with,
and the record key used to join observations across repeated collections.  The
query builders never receive the service key; `survey.py` adds it immediately
before the request and keeps it out of every stored artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Callable


KST = timezone(timedelta(hours=9))

# The order-plan endpoint requires an order-month range in addition to the
# publication window.  These are the widest documented values so this second
# dimension cannot silently narrow the population, matching the frozen
# experiment query in experiments/order-plan-screening/scripts/collect.py.
ORDER_SCOPE_FROM_MONTH = "200412"
ORDER_SCOPE_TO_MONTH = "999912"


@dataclass(frozen=True)
class Endpoint:
    target: str
    endpoint_id: str
    url: str
    record_key: str
    query_builder: Callable[[date, date, int, int], dict[str, str]]
    description: str


def _order_plan_query(from_date: date, to_date: date, page: int, rows: int) -> dict[str, str]:
    # `to_date` is exclusive; the API takes an inclusive minute, so step back one
    # minute exactly as the frozen experiment does.
    inclusive_end = datetime.combine(to_date, datetime_time.min) - timedelta(minutes=1)
    return {
        "pageNo": str(page),
        "numOfRows": str(rows),
        "type": "json",
        "orderBgnYm": ORDER_SCOPE_FROM_MONTH,
        "orderEndYm": ORDER_SCOPE_TO_MONTH,
        "inqryBgnDt": from_date.strftime("%Y%m%d0000"),
        "inqryEndDt": inclusive_end.strftime("%Y%m%d%H%M"),
    }


def _notice_query(from_date: date, to_date: date, page: int, rows: int) -> dict[str, str]:
    # `inqryDiv` selects the lookup mode, it is not an optional filter:
    #   1 = by receipt datetime (requires the window; capped at 365 days)
    #   2 = by pre-specification registration number (no window)
    #   3 = by reference number (no window)
    # This builder is the window sweep, so it always uses mode 1.  Additional
    # conditions such as `prdctClsfcNoNm` and `swBizObjYn` layer on top of it.
    inclusive_end = datetime.combine(to_date, datetime_time.min) - timedelta(minutes=1)
    return {
        "pageNo": str(page),
        "numOfRows": str(rows),
        "type": "json",
        "inqryDiv": "1",
        "inqryBgnDt": from_date.strftime("%Y%m%d0000"),
        "inqryEndDt": inclusive_end.strftime("%Y%m%d%H%M"),
    }


ENDPOINTS: dict[str, Endpoint] = {
    "order_plan": Endpoint(
        target="order_plan",
        # Identical to the frozen experiment so a re-collection of the same
        # window is directly comparable with its immutable raw pages.
        endpoint_id="g2b_order_plan_service_pps_search_v1",
        url=(
            "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/"
            "getOrderPlanSttusListServcPPSSrch"
        ),
        record_key="orderPlanUntyNo",
        query_builder=_order_plan_query,
        description="용역 발주계획 현황",
    ),
    "prespec": Endpoint(
        target="prespec",
        endpoint_id="g2b_prespec_service_v1",
        url=(
            "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/"
            "getPublicPrcureThngInfoServc"
        ),
        record_key="bfSpecRgstNo",
        query_builder=_notice_query,
        description="용역 사전규격 공개",
    ),
    "prespec_search": Endpoint(
        target="prespec_search",
        # A second pre-specification service that documents a search-condition
        # list including SW scope, reference number, and the related
        # specification document files.  Surveyed alongside `prespec` to see
        # whether it carries an order-plan key the plain list does not.
        # HrcspSsstndrdInfoService splits by business division: Thng(물품),
        # Servc(용역), Cnstwk(공사), Frgcpt(외자), each with a plain and a
        # PPSSrch operation.  All eight return the same shape and none of them
        # carries an order-plan key.  BidOps only needs the 용역 pair.
        endpoint_id="g2b_prespec_pps_search_service_v1",
        url=(
            "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/"
            "getPublicPrcureThngInfoServcPPSSrch"
        ),
        record_key="bfSpecRgstNo",
        query_builder=_notice_query,
        description="용역 사전규격 검색조건 조회",
    ),
    "bid": Endpoint(
        target="bid",
        endpoint_id="g2b_bid_public_info_service_v1",
        url=(
            "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
            "getBidPblancListInfoServc"
        ),
        record_key="bidNtceNo",
        query_builder=_notice_query,
        description="용역 입찰공고",
    ),
}


__all__ = ["ENDPOINTS", "Endpoint", "KST", "ORDER_SCOPE_FROM_MONTH", "ORDER_SCOPE_TO_MONTH"]
