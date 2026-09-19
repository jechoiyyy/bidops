"""같은 날 발주계획 회차와 공고 회차의 적재 순서가 공고 선별을 바꾸지 않는다
(`docs/0918_daily-operation/spec.md` §8 "적재 순서", S9b).

공고 선별이 읽는 발주계획 상태는 사람이 정한 추적 상태(`bid_tracked_reference`)뿐이고,
그날 들어온 발주계획에는 추적 상태가 없다. 그래서 두 트랙을 따로 돌려 어느 쪽이 먼저
적재되든 공고 회차의 선별 통계·사유·적재된 공고가 같아야 한다. 회차 디렉터리는
`test_collection_ingest`의 fixture 생성 함수로 만든다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.lifecycle import ingest_run
from app.lifecycle.models import CollectedRecordIndex, Notice, Run
from tests.lifecycle.test_collection_ingest import (
    BID_A,
    BID_B,
    BID_C,
    PLAN_A,
    PLAN_B,
    PRE_N,
    PRE_Y,
    _bid,
    _plan,
    _pre_spec,
    _session,
    _write_run,
)

PLANS_RUN = "lifecycle-20260916-plans"
NOTICES_RUN = "lifecycle-20260916-notices"


def _write_day(root: Path) -> tuple[Path, Path]:
    """같은 기준일의 두 트랙 회차. 공고가 그날 발주계획을 공식 번호로 가리킨다."""

    plans = _write_run(
        root,
        PLANS_RUN,
        plans=[
            _plan(PLAN_A, bid_ntice_no_list=f"{BID_A}000"),
            _plan(PLAN_B),
        ],
    )
    notices = _write_run(
        root,
        NOTICES_RUN,
        notices=[
            _pre_spec(PRE_Y),
            _pre_spec(PRE_N, sw="N"),
            _bid(BID_A, order_plan_no=PLAN_A),
            _bid(BID_B, pre_spec_no=PRE_Y),
            _bid(BID_C, sw_industry_1468="Y"),
        ],
    )
    return plans, notices


def _notice_outcome(tmp_path: Path, order: tuple[str, str]) -> dict[str, Any]:
    plans_dir, notices_dir = _write_day(tmp_path)
    dirs = {"plans": plans_dir, "notices": notices_dir}
    with _session() as session:
        results = {name: ingest_run(dirs[name], session, selection="collection") for name in order}
        notice_run_id = results["notices"].run_id
        return {
            "selection": results["notices"].selection,
            "stored_selection": session.get(Run, notice_run_id).counts_json["selection"],
            "reasons": {
                row.record_key: row.selection_reason
                for row in session.scalars(
                    select(CollectedRecordIndex).where(CollectedRecordIndex.run_id == notice_run_id)
                )
            },
            "loaded": sorted(session.scalars(select(Notice.notice_key))),
        }


def test_notice_selection_does_not_depend_on_ingest_order(tmp_path, empty_extensions):
    notices_first = _notice_outcome(tmp_path / "notices-first", ("notices", "plans"))
    plans_first = _notice_outcome(tmp_path / "plans-first", ("plans", "notices"))

    assert notices_first == plans_first
    # 비교가 공허하지 않다: 선별된 공고와 제외된 공고가 둘 다 있고, 그날 발주계획을
    # 가리키는 입찰공고도 추적 상태가 없으니 `bid_tracked_reference`로 뽑히지 않는다.
    assert plans_first["reasons"] == {
        f"pre:{PRE_Y}": "pre_spec_sw",
        f"pre:{PRE_N}": None,
        f"bid:{BID_A}:000": None,
        f"bid:{BID_B}:000": "bid_sw_prespec_reference",
        f"bid:{BID_C}:000": "bid_sw_industry_competitive",
    }
    assert plans_first["selection"]["bid_notice"]["selected"]["bid_tracked_reference"] == 0
    assert plans_first["loaded"] == sorted([f"pre:{PRE_Y}", f"bid:{BID_B}:000", f"bid:{BID_C}:000"])
