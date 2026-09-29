"""Versioned scenario inputs and exact, server-owned sensitivity calculations.

These values are user assumptions, never a mutation of the company profile.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, localcontext

SCHEMA = "bidops.assumption-analysis.v1"
VERSION = "1489-assumptions-v1"
MODEL = "gpt-5.6-luna"
EFFORT = "xhigh"
ASSUMPTIONS = (
    {"id": "assumption-qualification", "kind": "assumption", "text": "미확인 필수 참가 증빙이 유효하다고 가정한다."},
    {"id": "assumption-staff", "kind": "assumption", "text": "담당 인력과 백업 인력을 확보했다고 가정한다."},
    {"id": "assumption-response", "kind": "assumption", "text": "근무시간 외 90분 내 현장 도착 체계를 확보했다고 가정한다."},
    {"id": "unknown-support", "kind": "unknown", "text": "부품·제조사 지원 확보 여부는 미확인이다."},
)
MONTHLY_COSTS = {"pm": "400000", "primary": "1400000", "backup": "600000", "on_call": "600000"}


def economics() -> dict:
    """Round only each displayed amount; never use rounded revenue in balance."""
    with localcontext() as context:
        context.prec = 40
        budget = Decimal("35199815")
        monthly = sum(Decimal(value) for value in MONTHLY_COSTS.values())
        def won(value):
            return str(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        rows = []
        for months in (3, 6, 12):
            for ratio in (Decimal("0.9"), Decimal("1.0")):
                for support in (Decimal("4000000"), Decimal("8000000")):
                    revenue = budget / Decimal("1.1") * ratio
                    cost = monthly * months + Decimal("2000000") + support
                    rows.append({
                        "id": f"economics-{months}-{int(ratio * 100)}-{support}",
                        "months": months, "price_ratio": str(ratio), "support_cost_won": won(support),
                        "revenue_ex_vat_won": won(revenue), "cost_won": won(cost),
                        "assumed_balance_won": won(revenue - cost),
                        "sensitivity_only": months in (6, 12),
                    })
    return {"schema_version": "bidops.assumption-economics.v1", "budget_inc_vat_won": "35199815",
            "vat_divisor": "1.1", "monthly_costs_won": dict(MONTHLY_COSTS),
            "monthly_total_won": "3000000", "initial_cost_won": "2000000",
            "revenue_formula": "35199815 / 1.1 * price_ratio",
            "cost_formula": "3000000 * months + 2000000 + support_cost_won",
            "rounding": "Decimal precision=40; display whole KRW ROUND_HALF_UP; no intermediate rounding",
            "balance_label": "가정상 잔액", "rows": rows}


def scenario() -> dict:
    return {"schema_version": SCHEMA, "version": VERSION, "notice_id": 1489,
            "assumptions": deepcopy(list(ASSUMPTIONS)), "economics": economics(),
            "settings": {"provider": "codex-exec", "model": MODEL, "reasoning_effort": EFFORT,
                         "quality_status": "unmeasured_reference", "contains_assumptions": True}}
