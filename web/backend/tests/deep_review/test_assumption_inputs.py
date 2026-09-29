"""User-approved sensitivity cases; no model or production data access."""
from decimal import Decimal, getcontext

from app.deep_review.services.assumption_inputs import economics, scenario


def test_twelve_cases_and_independent_expected_balances():
    value = economics()
    assert value["monthly_total_won"] == "3000000"
    assert sum(map(Decimal, value["monthly_costs_won"].values())) == Decimal("3000000")
    rows = value["rows"]
    assert len(rows) == len({row["id"] for row in rows}) == 12
    assert {(r["months"], r["price_ratio"], r["support_cost_won"]) for r in rows} == {
        (months, ratio, support) for months in (3, 6, 12)
        for ratio in ("0.9", "1.0") for support in ("4000000", "8000000")}
    # Independently worked figures in KRW, in the published matrix order.
    assert [r["assumed_balance_won"] for r in rows] == [
        "13799849", "9799849", "16999832", "12999832",
        "4799849", "799849", "7999832", "3999832",
        "-13200151", "-17200151", "-10000168", "-14000168",
    ]
    assert all(r["sensitivity_only"] == (r["months"] != 3) for r in rows)
    assert value["balance_label"] == "가정상 잔액"


def test_fixed_context_and_fresh_snapshots():
    old = getcontext().prec
    try:
        getcontext().prec = 6
        first = scenario()
        getcontext().prec = 28
        assert first == scenario()
    finally:
        getcontext().prec = old
    first["assumptions"][0]["kind"] = "fact"
    first["economics"]["rows"].clear()
    current = scenario()
    assert current["assumptions"][0]["kind"] == "assumption"
    assert current["assumptions"][-1]["kind"] == "unknown"
    assert len(current["economics"]["rows"]) == 12
    assert current["settings"]["model"] == "gpt-5.6-luna"
    assert current["settings"]["reasoning_effort"] == "xhigh"
