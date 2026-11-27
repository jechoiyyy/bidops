"""Company-fit probe for the 11-26 prespec overview test stack.

Reads completed current overview runs (read-only), builds a compact Rootlab wiki
projection (confirmed/public facts only), and optionally calls the overview-purpose
LiteLLM model once per notice (+1 validation retry). Writes nothing to the DB.
Output: one JSON object per line on stdout.

usage: python fit_probe.py --wiki /tmp/wiki [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import yaml

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.model_client import ModelClient, ModelInvocationError
from app.lifecycle.models import Notice
from app.deep_review.schemas.company_fit import CompanyFitPayload
from app.deep_review.services import company_fit as CF
from app.deep_review.services import company_fit_runner as R
from app.deep_review.services.effective_grade import priority_notice_ids
from app.deep_review.services.overview_runs import current_runs

TRUSTED = {"confirmed", "public"}
PROMPT_VERSION = "prespec-company-fit-v3.1-card-probe"
INSTRUCTION = """사전규격 개요와 회사 사업 범위 카드만 대조하여 실제 계약 과업이 회사가 하는 사업에 드는지 판단한다.
공고 제목의 기술 키워드보다 실제 계약 과업(주된 과업)을 우선한다. 감리·평가·컨설팅 대상이 되는 사업을 수행 과업으로 바꾸지 않는다.
회사 정보는 사업 범위(scope:*)와 회사 정책(policy:*)이며 모두 회사가 확인한 내용이다.
matched: 주된 과업의 대상이 어느 scope의 includes 항목과 구체적으로 일치하고, 그 scope의 boundary·policy:no-bid·policy:onsite에 걸리지 않으며, policy:caution에도 해당하지 않을 때만 쓴다. keywords는 후보 힌트일 뿐 matched의 근거가 아니다. 각 이유는 해당 scope ref를 인용한다.
mismatch: 주된 과업이 policy:no-bid에 해당하거나, policy:onsite의 rules에 따라 대구 밖 상주가 필수일 때만 쓴다. 해당 policy ref를 인용한다.
unknown: policy:caution에 해당하거나, scope의 boundary가 unknown이라고 정한 경우이거나, 주된 과업이 어느 scope에도 들지 않거나, 개요만으로 판단할 수 없을 때 쓴다. 카드에 없는 사업이라고 해서 회사가 못 한다는 뜻은 아니다. 확인할 사항을 verification_items에 쓴다.
reasons의 kind는 scope_match, scope_mismatch, information_gap이다. matched면 모든 이유가 scope_match여야 하고, mismatch면 scope_mismatch 이유가 하나 이상 있어야 한다.
각 이유는 notice_refs와 company_refs에 입력에 있는 ref만 인용한다. explanation은 두 근거를 잇는 의견이며 입력에 없는 숫자·자격·실적을 만들지 않는다.
summary는 핵심 이유 한 문장, reasons는 최대 8개, verification_items는 사람이 확인할 항목이다.
입력은 개요 일부이므로 최종 참여 가능 여부나 Go/No-Go를 결정하지 않는다."""

INSTRUCTION_V32 = INSTRUCTION.replace(
    "keywords는 후보 힌트일 뿐 matched의 근거가 아니다.",
    "keywords는 후보 힌트일 뿐 matched의 근거가 아니다. scope의 boundary와 policy는 그 내용이 주된 과업일 때만 적용하고, 부가 기능·일부 과업에 그 단어가 나온다는 이유로 적용하지 않는다(policy:mixed-scope).",
).replace(
    "개요만으로 판단할 수 없을 때 쓴다.",
    "주된 과업 자체를 개요로 알 수 없을 때 쓴다. 주된 과업이 scope와 맞는데 세부 기능·범위가 덜 적혔다는 이유만으로 unknown을 내지 않고, 그 세부는 verification_items에 쓴다.",
)
assert INSTRUCTION_V32.count("policy:mixed-scope") == 1 and "세부 기능" in INSTRUCTION_V32
PROMPTS = {"v3.1": ("prespec-company-fit-v3.1-card-probe", INSTRUCTION), "v3.2": ("prespec-company-fit-v3.2-card-probe", INSTRUCTION_V32)}


def levels(prov: dict) -> dict[str, str]:
    return {unquote(k): (v or {}).get("level") for k, v in prov["fields"].items()}


def company_facts(wiki: Path) -> tuple[list[dict], dict]:
    profile = yaml.safe_load((wiki / "rootlab.yaml").read_text())
    lv = levels(yaml.safe_load((wiki / "rootlab.provenance.yaml").read_text()))
    portfolio = yaml.safe_load((wiki / "rootlab.portfolio.yaml").read_text())
    facts, skipped = [], {}

    def add(key, value, level):
        if level in TRUSTED and value not in (None, "", [], {}):
            facts.append({"fact_key": key, "status": level, "value": value})
        else:
            skipped[level or "none"] = skipped.get(level or "none", 0) + 1

    cap = profile["capabilities"]
    add("capabilities.domains", cap["domains"], lv.get("capabilities.domains"))
    add("capabilities.tech_stack.ai", cap["tech_stack"].get("ai"), lv.get("capabilities.tech_stack.ai"))
    for s in cap.get("solutions") or []:
        name = s["name"]
        value = f"{name}: {s['desc']}" if s.get("desc") else name
        add(f"capabilities.solutions[{name}]", value, lv.get(f"capabilities.solutions[{name}]"))
    pol = profile["policy"]
    add("policy.no_bid_if", pol.get("no_bid_if"), lv.get("policy.no_bid_if"))
    add("company.region", profile["company"].get("region"), lv.get("company.region"))
    for p in portfolio:
        pid = p["id"]
        parts = {f: p.get(f) for f in ("title", "client", "client_type", "type")}
        lvls = {f: lv.get(f"portfolio[{pid}].{f}") for f in parts}
        if lvls["title"] not in TRUSTED:
            skipped["portfolio_untrusted_title"] = skipped.get("portfolio_untrusted_title", 0) + 1
            continue
        value = {f: v for f, v in parts.items() if v not in (None, "", "unknown") and lvls[f] in TRUSTED}
        value["year"] = pid[1:5]
        facts.append({"fact_key": f"portfolio[{pid}]", "status": "public" if "public" in lvls.values() else "confirmed",
                      "value": value})
    for i, f in enumerate(facts):
        f["ref"] = f"company:{i}"
    return [{"ref": f["ref"], **{k: f[k] for k in ("fact_key", "status", "value")}} for f in facts], skipped


def card_facts(card_path: Path) -> list[dict]:
    card = yaml.safe_load(card_path.read_text())
    facts = []
    for sc in card["scopes"]:
        facts.append({"ref": sc["id"], "fact_key": sc["name"], "status": "confirmed",
                      "value": {k: sc[k] for k in ("summary", "includes", "boundary", "keywords", "examples") if sc.get(k)}})
    for po in card["policies"]:
        facts.append({"ref": po["id"], "fact_key": po["kind"], "status": "confirmed",
                      "value": {k: po[k] for k in ("summary", "items", "rules") if po.get(k)}})
    return facts


def keyword_baseline(card_path: Path, texts: list[str]) -> dict:
    card = yaml.safe_load(card_path.read_text())
    blob = " ".join(texts)
    hits = {}
    for sc in card["scopes"]:
        found = [k for k in sc.get("keywords", []) if k in blob]
        if found:
            hits[sc["id"]] = found
    return hits


def validate(output, inputs):
    payload = CompanyFitPayload.model_validate(output)
    notices = {f["ref"]: f for f in inputs["notice_facts"]}
    companies = {f["ref"]: f for f in inputs["company_facts"]}
    if any(not v.strip() for v in [payload.summary, *payload.verification_items, *(r.explanation for r in payload.reasons)]):
        raise ValueError("blank_reason")
    for reason in payload.reasons:
        if len(set(reason.notice_refs)) != len(reason.notice_refs) or len(set(reason.company_refs)) != len(reason.company_refs):
            raise ValueError("duplicate_evidence")
        if any(r not in notices for r in reason.notice_refs) or any(r not in companies for r in reason.company_refs):
            raise ValueError("evidence_not_in_input")
        if reason.kind != "information_gap" and (not reason.company_refs or any(companies[r]["status"] not in TRUSTED for r in reason.company_refs)):
            raise ValueError("unconfirmed_company_evidence")
        cited = " ".join(notices[r]["text"] for r in reason.notice_refs) + json.dumps([companies[r]["value"] for r in reason.company_refs], ensure_ascii=False)
        cited_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", cited))
        if any(n not in cited_numbers for n in re.findall(r"\d+(?:[.,]\d+)*", reason.explanation)):
            raise ValueError("unsupported_number")
    reason_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", " ".join(r.explanation for r in payload.reasons)))
    if any(n not in reason_numbers for n in re.findall(r"\d+(?:[.,]\d+)*", payload.summary)):
        raise ValueError("unsupported_summary_number")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", required=False)
    ap.add_argument("--card", required=True)
    ap.add_argument("--dump-inputs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="local-agent-main")
    ap.add_argument("--prompt", choices=sorted(PROMPTS), default="v3.1")
    ap.add_argument("--no-time-window", action="store_true", help="skip the 06-12 KST stop (user-approved daytime run)")
    args = ap.parse_args()
    settings = get_settings()
    facts, skipped = card_facts(Path(args.card)), {}
    policy = CF.fit_policy(args.model)
    global PROMPT_VERSION
    PROMPT_VERSION, instruction = PROMPTS[args.prompt]
    policy["prompt_version"] = PROMPT_VERSION
    policy["stages"] = [{"stage": "company_fit", "instruction": instruction}]
    print(json.dumps({"kind": "config", "prompt_version": PROMPT_VERSION, "card": args.card}), flush=True)
    print(json.dumps({"kind": "company_projection", "facts": len(facts), "skipped": skipped,
                      "bytes": len(json.dumps(facts, ensure_ascii=False).encode())}, ensure_ascii=False), flush=True)
    client = None
    with SessionLocal() as session:
        ids = list(session.scalars(__import__("sqlalchemy").select(Notice.id).where(Notice.source_type == "pre_spec").order_by(Notice.id)))
        runs = current_runs(session, ids)
        sources = CF.overview_inputs(session, ids, runs=runs)
        priority = priority_notice_ids(session, ids)
        targets = [i for i in ids if i in sources]
        if args.limit:
            targets = targets[: args.limit]
        print(json.dumps({"kind": "targets", "notices": len(ids), "completed_overview": len(targets),
                          "priority": len([i for i in targets if i in priority])}), flush=True)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        consecutive_failures = 0
        for nid in targets:
            now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
            if not args.dry_run and not args.no_time_window and now_kst.hour >= 6 and now_kst.hour < 12:
                print(json.dumps({"kind": "stopped", "reason": "deadline_0600_kst", "at": now_kst.isoformat()}), flush=True)
                break
            if consecutive_failures >= 3:
                print(json.dumps({"kind": "stopped", "reason": "three_consecutive_failures"}), flush=True)
                break
            notice = session.get(Notice, nid)
            src = sources[nid]
            inputs = {"schema_version": "bidops.prespec-company-fit-input.v2-probe", "notice_id": nid,
                      "notice_facts": [{"ref": "notice:title", "text": notice.title, "pages": [], "block_key": None}, *src.facts],
                      "input_limitations": src.limitations, "company_facts": facts,
                      "model_name": args.model, "prompt_version": PROMPT_VERSION}
            size = len(json.dumps(inputs, ensure_ascii=False).encode())
            row = {"kind": "result", "notice_id": nid, "title": notice.title, "priority": nid in priority,
                   "input_bytes": size, "overview_id": str(src.id),
                   "keyword_hits": keyword_baseline(Path(args.card), [f["text"] for f in inputs["notice_facts"]])}
            if args.dump_inputs:
                with open(args.dump_inputs, "a") as fh:
                    fh.write(json.dumps({"notice_id": nid, "notice_facts": inputs["notice_facts"], "input_limitations": src.limitations}, ensure_ascii=False) + chr(10))
            if args.dry_run:
                print(json.dumps(row, ensure_ascii=False), flush=True)
                continue
            if client is None:
                client = ModelClient.for_purpose("overview", model=args.model, settings=settings, output_contract=CF.CONTRACT)
            started = time.monotonic()
            try:
                status, error, result, _raw, first_raw, retry, metrics = R.PreSpecCompanyFitRunner._invoke_validated(
                    None, client, inputs, policy, inputs, validate, {})
                row.update(status=status, error=error, retried=retry is not None, metrics=metrics,
                           result=result.model_dump() if result is not None else None)
            except (ModelInvocationError, Exception) as exc:  # probe: record and continue
                row.update(status="failed", error=f"{type(exc).__name__}:{getattr(exc, 'code', '') or str(exc)[:200]}")
            consecutive_failures = consecutive_failures + 1 if row.get("status") == "failed" else 0
            row["elapsed_s"] = round(time.monotonic() - started, 1)
            print(json.dumps(row, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
