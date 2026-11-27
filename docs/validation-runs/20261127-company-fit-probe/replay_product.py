"""PS-01 STEP-009 / T14: replay the 11-26 measurement through the product's company-fit runner.

Runs inside a one-off analysis-worker container of the isolated `bidops-prespec1126` stack (worker DB
role, LiteLLM `local-agent-main` → local Qwen), never against production. The stack's own
analysis-worker must be stopped first so its slot does not claim the same rows. The card mode must be
recorded as `suggest` with `set-company-fit-mode` (web container) beforehand.

    python /run/replay/replay_product.py --out /run/replay/product_v3.1.jsonl [--max-runs 40]

It repeats `PreSpecCompanyFitRunner(clock=2026-11-27 10:30 KST).run_once` until it returns False (or
three consecutive attempts fail, or `--max-runs`), then writes one `score_gold.py` result line per
card-lineage attempt. Only identifiers, decisions and summaries are written; no raw model text.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.deep_review.models import PreSpecCompanyFitAttempt
from app.deep_review.services.company_fit import card_mode_state
from app.deep_review.services.company_fit_runner import PreSpecCompanyFitRunner
from app.lifecycle.models import Notice

CLOCK = datetime(2026, 11, 27, 1, 30, tzinfo=UTC)  # 10:30 KST, the measurement time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-runs", type=int, default=40)
    args = parser.parse_args()
    init_db()
    settings = get_settings()
    with SessionLocal() as session:
        state = card_mode_state(settings, session)
        if not state["effective"]:
            print(f"card mode not effective: {state['reason_code']}", file=sys.stderr)
            return 2
        runner = PreSpecCompanyFitRunner(settings=settings, clock=lambda: CLOCK)
        runs, failures, started = 0, 0, time.monotonic()
        while runs < args.max_runs:
            before = time.monotonic()
            if not runner.run_once(session, "replay-product"):
                break
            runs += 1
            latest = session.scalars(select(PreSpecCompanyFitAttempt)
                                     .where(PreSpecCompanyFitAttempt.card_sha256.is_not(None))
                                     .order_by(PreSpecCompanyFitAttempt.completed_at.desc().nulls_last())
                                     .limit(1)).first()
            failures = failures + 1 if latest is not None and latest.status == "failed" else 0
            print(json.dumps({"run": runs, "seconds": round(time.monotonic() - before, 1),
                              "status": latest.status if latest else None}), flush=True)
            if failures >= 3:
                print("three consecutive failures, stopping", file=sys.stderr)
                break
        rows = session.scalars(select(PreSpecCompanyFitAttempt)
                               .where(PreSpecCompanyFitAttempt.card_sha256 == state["card_sha256"])
                               .order_by(PreSpecCompanyFitAttempt.notice_id)).all()
        with open(args.out, "w", encoding="utf-8") as out:
            out.write(json.dumps({"kind": "config", "prompt_version": state["prompt_version"],
                                  "card_sha256": state["card_sha256"], "clock": CLOCK.isoformat(),
                                  "runner": "PreSpecCompanyFitRunner"}, ensure_ascii=False) + "\n")
            for row in rows:
                notice = session.get(Notice, row.notice_id)
                result = row.result_jsonb or None
                elapsed = None if row.latency_ms is None else row.latency_ms / 1000
                out.write(json.dumps({
                    "kind": "result", "notice_id": row.notice_id, "title": notice.title if notice else None,
                    "status": row.status, "error": row.error_code,
                    "result": {"decision": result["decision"], "summary": result["summary"]} if result else None,
                    "elapsed_s": elapsed, "retried": None,
                }, ensure_ascii=False) + "\n")
        print(json.dumps({"runs": runs, "rows": len(rows), "minutes": round((time.monotonic() - started) / 60, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
