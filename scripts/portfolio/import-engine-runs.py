"""Portfolio only: import finished engine-eval runs as read-only engine_run rows.

Host side (default): reads an engine-eval directory, picks per case the newest
``runs/<label>/<case>/r<n>`` that has ``outcome.json`` with an analysis and a usable status,
packs those results into one JSONL file, copies it with this script into the portfolio web
container and runs the apply step there. Nothing is invented: ``analysis`` is the run's
``analysis.json`` as written by the harness (engine ``Analysis`` + ``source_evidence``).

Container side (``--apply``): for each record, resolves the single real company's active
knowledge binding, freezes the eval input in the shape ``engine_runs.create`` uses (plus the
company/profile/graph ids and hashes), and writes one ``engine_run`` through the guard's own
transitions (queued -> running -> completed|partial). quality_status is
``unmeasured_reference`` (참조 실행·미측정); the portfolio DB check constraint was widened
for that value. No WorkJob is created, so no worker ever picks these rows up.

Idempotent: a case whose eval input sha256 is already imported for the company/notice is
skipped. The request_id is a uuid5 of (label, case, eval input sha256), so a replay with the
same input also hits the unique request constraint.

    python3 scripts/portfolio/import-engine-runs.py \
        --eval-dir /Users/temp/orca/bidops/.sdlc/local-runtime/portfolio-engine-20261124/eval \
        [--label live1] [--container bidops-portfolio-web-1] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc  # host python may be 3.9 (no datetime.UTC)

ACTOR = "루트랩 실무자(에이전트)"
STATUS_MAP = {"ok": "completed", "cached": "completed", "completed": "completed", "partial": "partial"}
RUN_DIR = re.compile(r"r([0-9]+)")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def collect(eval_dir: Path, label: str):
    cases = json.loads((eval_dir / "cases.json").read_text(encoding="utf-8"))["cases"]
    manifest = json.loads((eval_dir / "runs" / label / "manifest.json").read_text(encoding="utf-8"))
    inputs_dir = eval_dir / manifest.get("inputs", "inputs-v2")
    records, pending, skipped = [], [], []
    for case in cases:
        case_id = case["case_id"]
        case_dir = eval_dir / "runs" / label / case_id
        runs = sorted(
            (int(m.group(1)), p) for p in (case_dir.iterdir() if case_dir.is_dir() else [])
            if p.is_dir() and (m := RUN_DIR.fullmatch(p.name))
        )
        chosen = None
        last_unusable = None
        for number, run_dir in reversed(runs):
            outcome_path = run_dir / "outcome.json"
            if not outcome_path.is_file():
                continue  # abandoned or still running
            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
            status = STATUS_MAP.get(outcome.get("status"))
            if status and outcome.get("analysis") and (run_dir / "analysis.json").is_file():
                chosen = (number, run_dir, outcome, status)
                break
            last_unusable = {"case_id": case_id, "run": number, "status": outcome.get("status"),
                             "cause_class": outcome.get("cause_class")}
        if chosen is None:
            (skipped if last_unusable else pending).append(last_unusable or {"case_id": case_id, "runs": len(runs)})
            continue
        number, run_dir, outcome, status = chosen
        input_bytes = (inputs_dir / f"{case_id}.input.json").read_bytes()
        input_sha = _sha_bytes(input_bytes)
        if outcome.get("input_sha256") not in (None, input_sha):
            skipped.append({"case_id": case_id, "run": number, "status": "input_sha_mismatch"})
            continue
        finished = datetime.fromtimestamp((run_dir / "outcome.json").stat().st_mtime, UTC)
        started = finished - timedelta(seconds=float(outcome.get("seconds") or 0))
        records.append({
            "case_id": case_id, "notice_id": case["notice_id"], "bundle_id": case["bundle_id"],
            "label": label, "run": number, "status": status, "outcome_status": outcome.get("status"),
            "input": json.loads(input_bytes), "eval_input_sha256": input_sha,
            "analysis": json.loads((run_dir / "analysis.json").read_text(encoding="utf-8")),
            "warnings": list(outcome.get("warnings") or []),
            "engine_sha256": outcome.get("engine_sha256") or manifest.get("engine_sha256"),
            "provenance": {
                "source": "engine-eval", "label": label, "case_id": case_id, "run": f"r{number}",
                "run_mode": manifest.get("mode"), "model": manifest.get("model"),
                "reasoning_effort": manifest.get("reasoning_effort"), "passes": manifest.get("passes"),
                "eval_input_sha256": input_sha, "outcome_status": outcome.get("status"),
                "calls": outcome.get("calls"), "seconds": outcome.get("seconds"),
                "requirements": outcome.get("requirements"),
            },
            "started_at": started.isoformat(), "completed_at": finished.isoformat(),
        })
    return records, pending, skipped


def host_main(args) -> int:
    records, pending, skipped = collect(Path(args.eval_dir), args.label)
    print(json.dumps({"ready": [f"{r['case_id']}/r{r['run']}:{r['status']}" for r in records],
                      "pending": [p["case_id"] for p in pending], "skipped": skipped}, ensure_ascii=False), flush=True)
    if args.dry_run or not records:
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        payload_path = handle.name
    # The result transitions need the worker role (app may only INSERT engine_run). The worker
    # password is read from the portfolio stack env and handed over in a 0600 env file only.
    password = None
    for line in Path(args.stack_env).read_text(encoding="utf-8").splitlines():
        if line.startswith("BIDOPS_WORKER_PASSWORD="):
            password = line.split("=", 1)[1].strip().strip("\"'")
    if not password:
        raise SystemExit("worker password not found in the stack env")
    env_fd, env_path = tempfile.mkstemp(suffix=".env")
    with os.fdopen(env_fd, "w") as handle:
        handle.write("BIDOPS_PORTFOLIO_WORKER_DATABASE_URL=postgresql+psycopg://worker:"
                     f"{quote(password, safe='')}@postgres:5432/bidops\n")
    try:
        os.chmod(payload_path, 0o644)
        for src, dst in ((payload_path, "/tmp/portfolio-engine-runs.jsonl"), (__file__, "/tmp/portfolio-import-engine-runs.py")):
            subprocess.run(["docker", "cp", src, f"{args.container}:{dst}"], check=True)
        done = subprocess.run(
            ["docker", "exec", "--env-file", env_path, "-w", "/app/web/backend", args.container, "python",
             "/tmp/portfolio-import-engine-runs.py", "--apply", "/tmp/portfolio-engine-runs.jsonl", "--actor", args.actor],
            check=False,
        )
        subprocess.run(["docker", "exec", "-u", "0", args.container, "rm", "-f", "/tmp/portfolio-engine-runs.jsonl",
                        "/tmp/portfolio-import-engine-runs.py"], check=False)
        return done.returncode
    finally:
        os.unlink(payload_path)
        os.unlink(env_path)


def apply_main(path: str, actor: str) -> int:
    import uuid

    sys.path.insert(0, os.getcwd())  # run with -w /app/web/backend; the script itself sits in /tmp

    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.core.model_binding import canonical_json_bytes
    from app.core.models import AuditEvent
    from app.deep_review.models import DocumentBundle, EngineRun
    from app.deep_review.services.company_analysis_input import resolve_company_knowledge_context
    from app.deep_review.services.engine_runs import ENGINE_VERSION, engine_digest, package_root
    from app.lifecycle.models import Company

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    WorkerSession = sessionmaker(create_engine(os.environ["BIDOPS_PORTFOLIO_WORKER_DATABASE_URL"],
                                               connect_args={"options": "-c search_path=bidops,public"}))
    # The eval harness hashes the engine tree with NUL separators, the web with ":". Store the
    # web digest only when the eval digest of this image's own engine tree equals the run's.
    root = package_root()
    eval_style = hashlib.sha256()
    for item in sorted(q for q in root.rglob("*") if q.is_file() and q.suffix in {".py", ".md"}):
        eval_style.update(item.relative_to(root).as_posix().encode("utf-8") + b"\0")
        eval_style.update(hashlib.sha256(item.read_bytes()).hexdigest().encode("ascii") + b"\n")
    image_eval_digest, image_web_digest = eval_style.hexdigest(), engine_digest()
    namespace = uuid.UUID("5d0f0c1e-7a8e-4e55-9a51-3c2b8f0c2024")
    results = {"imported": [], "already_imported": [], "rejected": []}
    with SessionLocal() as session:
        companies = session.scalars(select(Company).where(Company.is_fictional.is_(False))).all()
        if len(companies) != 1:
            raise SystemExit("expected exactly one real company")
        context = resolve_company_knowledge_context(session, companies[0].id)
        company_id = companies[0].id
        profile_id, profile_sha = context.profile.id, context.profile.profile_sha256
        graph_id, graph_sha = context.graph.id, context.graph.graph_sha256
        session.commit()
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            notice_id, bundle_id = int(record["notice_id"]), uuid.UUID(record["bundle_id"])
            existing = session.scalars(
                select(EngineRun).where(EngineRun.company_id == company_id, EngineRun.notice_id == notice_id)
            ).all()
            # Same eval input analysed by a different engine tree (e.g. live2 after the 2026-11-24
            # engine fix) is a new run; only the same input *and* engine is a replay.
            if any(((row.result_payload or {}).get("portfolio_import") or {}).get("eval_input_sha256")
                   == record["eval_input_sha256"]
                   and ((row.result_payload or {}).get("portfolio_import") or {}).get("eval_engine_sha256")
                   == record["engine_sha256"] for row in existing):
                results["already_imported"].append(record["case_id"])
                continue
            bundle = session.get(DocumentBundle, bundle_id)
            if bundle is None or bundle.notice_id != notice_id or bundle.status != "ready":
                results["rejected"].append({"case_id": record["case_id"], "reason": "bundle_not_ready_or_mismatch"})
                continue
            source = record["input"]
            frozen = {
                "schema_version": source["schema_version"],
                "engine_version": ENGINE_VERSION,
                "engine_sha256": image_web_digest if record["engine_sha256"] == image_eval_digest else record["engine_sha256"],
                "mode": source["mode"],  # the frozen eval input says mock_reference; the run mode is in provenance
                "slug": source["slug"],
                "title": source["title"],
                "company_id": str(company_id),
                "company_name": source["company_name"],
                "profile_version_id": str(profile_id),
                "profile_sha256": profile_sha,
                "graph_version_id": str(graph_id),
                "graph_sha256": graph_sha,
                "notice_id": notice_id,
                "bundle_id": str(bundle_id),
                "documents": source["documents"],
                "primary_format": source["primary_format"],
                "blocks": source["blocks"],
                "company_bundle": source["company_bundle"],
                "evaluation": source.get("evaluation"),
            }
            result = {
                "schema_version": "bidops.engine-output.v1",
                "engine_version": ENGINE_VERSION,
                "quality_status": "unmeasured_reference",
                "status": record["status"],
                "error_code": None,
                "warnings": record["warnings"],
                "analysis": record["analysis"],
                "artifacts": {},
                "portfolio_import": {**record["provenance"], "eval_engine_sha256": record["engine_sha256"],
                                     "engine_tree_matches_image": record["engine_sha256"] == image_eval_digest},
            }
            request_id = uuid.uuid5(namespace, f"{record['label']}:{record['case_id']}:{record['eval_input_sha256']}")
            started = datetime.fromisoformat(record["started_at"])
            completed = datetime.fromisoformat(record["completed_at"])
            input_sha256 = hashlib.sha256(canonical_json_bytes(frozen)).hexdigest()
            result_sha256 = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
            try:
                # 1) app role: the queued envelope (or resume an earlier half-finished import).
                row = session.scalar(select(EngineRun).where(EngineRun.request_id == request_id))
                if row is None:
                    row = EngineRun(
                        id=uuid.uuid4(), request_id=request_id, company_id=company_id, notice_id=notice_id,
                        bundle_id=bundle_id, profile_version_id=profile_id, engine_version=ENGINE_VERSION,
                        quality_status="unmeasured_reference", status="queued", input_sha256=input_sha256,
                        input_payload=frozen, created_by_name=actor, created_at=started,
                    )
                    session.add(row)
                    session.commit()
                elif row.input_sha256 != input_sha256:
                    raise RuntimeError("request_id_input_conflict")
                run_id = row.id
                session.expunge_all()
                # 2) worker role: the guard's own transitions queued -> running -> completed|partial.
                with WorkerSession() as work:
                    row = work.get(EngineRun, run_id)
                    if row.status == "queued":
                        row.status, row.started_at = "running", started
                        work.flush()
                    if row.status == "running":
                        row.result_payload = result
                        row.result_sha256 = result_sha256
                        row.status, row.completed_at = record["status"], completed
                        work.add(AuditEvent(
                            actor_kind="human", claimed_name=actor, action="engine_run.portfolio_imported",
                            aggregate_type="engine_run", aggregate_id=str(run_id),
                            safe_metadata={"quality_status": "unmeasured_reference", "status": record["status"],
                                           "input_sha256": input_sha256, "result_sha256": result_sha256,
                                           "eval_input_sha256": record["eval_input_sha256"],
                                           "eval_run": f"{record['label']}/{record['case_id']}/r{record['run']}"},
                            request_id=str(request_id),
                        ))
                    work.commit()
            except Exception as error:  # report the class only; payloads carry source text
                session.rollback()
                results["rejected"].append({"case_id": record["case_id"], "reason": type(error).__name__,
                                            "detail": str(getattr(error, "orig", error)).splitlines()[0][:160]})
                continue
            results["imported"].append({"case_id": record["case_id"], "run": f"r{record['run']}",
                                        "status": record["status"], "engine_run_id": str(run_id)})
    print(json.dumps(results, ensure_ascii=False))
    return 1 if results["rejected"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-dir")
    parser.add_argument("--label", default="live1")
    parser.add_argument("--container", default="bidops-portfolio-web-1")
    parser.add_argument("--actor", default=ACTOR)
    parser.add_argument("--stack-env", default="/Users/temp/orca/bidops-portfolio-demo/env/portfolio-private/stack.env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply")
    args = parser.parse_args()
    if args.apply:
        return apply_main(args.apply, args.actor)
    if not args.eval_dir:
        parser.error("--eval-dir is required")
    return host_main(args)


if __name__ == "__main__":
    sys.exit(main())
