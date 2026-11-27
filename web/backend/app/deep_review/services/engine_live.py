"""Live engine supervisor (ADR-0081): the only place a live engine request leaves BidOps.

The analysis worker calls `run` for a queued run whose frozen input says `mode=live`. The run was
created by a human approval of a live preview (ADR-0078); the database refuses a live run without
one. The supervisor starts `bid_deep_engine.runner --live-ipc` with no credentials, writes the
frozen input as one line and then handles one frame per engine call:

1. the frame is checked against the wire contract (`engine_live_wire.CallSequence`): fixed model,
   effort, store flag and cache options, stage order, one shared document, and for the first call
   the exact request hash bound in the approved preview;
2. under a database advisory lock the KST-day and per-notice budgets are checked and an
   `engine_call` row is written as `reserved`, while the job lease is renewed; nothing is sent if
   that commit fails;
3. the request goes to the fixed OpenAI Responses endpoint with the key from the worker's secret
   file (no proxy, no redirect, no retry);
4. the outcome is written to the row; if that commit fails no further request is sent.

A request whose outcome is unknown (timeout after sending, connection lost) keeps its slot and is
never resent. Logs carry identifiers, codes and counts only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from ...core.config import get_settings
from ...core.model_binding import canonical_json_bytes
from ..models import EngineCall, EngineReviewApproval, EngineReviewPreview, EngineRun, WorkJob
from . import engine_live_wire as wire

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
LEASE_MARGIN_SECONDS = 120
BUDGET_LOCK_KEY = 0x0B1D0E9C  # one advisory lock for every live budget decision
COUNTED_STATES = ("reserved", "completed", "http_error", "incomplete", "transport_error", "outcome_unknown")
UNKNOWN_COST_STATES = ("reserved", "outcome_unknown")
SUPERVISOR_CODES = frozenset({
    "engine_live_key_unavailable", "engine_live_not_approved", "engine_live_deadline",
    "engine_live_process_failed", "engine_live_output_invalid", "engine_live_lease_lost",
    "engine_live_audit_failed", "budget_exhausted", "http_error", "response_incomplete",
    "outcome_unknown", "frame_invalid", "frame_order_invalid", "frame_body_invalid",
    "frame_document_changed", "input_changed", "request_too_large", "planned_calls_exceeded",
})


class LiveRunError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class HttpFailure(Exception):
    """The endpoint answered with an HTTP error status (the request reached it)."""

    def __init__(self, status: int, body: bytes):
        super().__init__(status)
        self.status = status
        self.body = body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib hook
        return None


def post_responses(url: str, body: bytes, api_key: str, timeout: int) -> tuple[int, bytes]:
    """One POST, no proxy (environment proxies are ignored), no redirect, no retry."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        raise HttpFailure(error.code, error.read() or b"") from None


def read_key(path: str) -> str:
    """Key from the worker's secret file: a plain key or JSON with `OPENAI_API_KEY`."""
    file = Path(path)
    try:
        raw = file.read_text(encoding="utf-8").strip()
    except OSError:
        raise LiveRunError("engine_live_key_unavailable") from None
    if raw.startswith("{"):
        try:
            raw = str(json.loads(raw).get("OPENAI_API_KEY") or "").strip()
        except ValueError:
            raw = ""
    if not raw:
        raise LiveRunError("engine_live_key_unavailable")
    return raw


def endpoint() -> str:
    settings = get_settings()
    configured = settings.engine_live_responses_url
    if configured and settings.deployment_environment == "prod":
        raise LiveRunError("engine_live_not_approved")
    return configured or wire.RESPONSES_URL


def kst_today(now: datetime) -> "datetime.date":
    return now.astimezone(KST).date()


@dataclass(frozen=True)
class Caps:
    daily_notices: int
    daily_calls: int
    notice_calls: int
    daily_usd: float
    unknown_call_usd: float

    @classmethod
    def from_settings(cls):
        s = get_settings()
        return cls(s.engine_live_daily_notice_cap, s.engine_live_daily_call_cap,
                   s.engine_live_notice_call_cap, s.engine_live_daily_usd_cap, s.engine_live_unknown_call_usd)


def budget_snapshot(session, *, notice_id: int, today, run_id=None, caps: Caps | None = None) -> dict:
    """Used and remaining live budget for KST `today` and `notice_id` (read-only)."""
    caps = caps or Caps.from_settings()
    calls_today = session.scalar(select(func.count()).select_from(EngineCall).where(
        EngineCall.kst_date == today, EngineCall.state.in_(COUNTED_STATES))) or 0
    notices_today = set(session.scalars(select(EngineCall.notice_id).where(EngineCall.kst_date == today)).all())
    notice_calls = session.scalar(select(func.count()).select_from(EngineCall).where(
        EngineCall.notice_id == notice_id, EngineCall.state.in_(COUNTED_STATES))) or 0
    recorded = session.scalar(select(func.coalesce(func.sum(EngineCall.usd), 0)).where(
        EngineCall.kst_date == today, EngineCall.usd.is_not(None))) or 0
    unknown = session.scalar(select(func.count()).select_from(EngineCall).where(
        EngineCall.kst_date == today, EngineCall.usd.is_(None), EngineCall.state.in_(UNKNOWN_COST_STATES))) or 0
    spent = float(recorded) + unknown * caps.unknown_call_usd
    this_run_today = run_id is not None and session.scalar(select(func.count()).select_from(EngineCall).where(
        EngineCall.engine_run_id == run_id, EngineCall.kst_date == today)) > 0
    notices_used = len(notices_today) if (notice_id in notices_today or this_run_today) else len(notices_today) + 1
    return {
        "kst_date": today.isoformat(),
        "calls_today": calls_today,
        "notices_today": len(notices_today),
        "notice_calls": notice_calls,
        "usd_today": round(spent, 6),
        "remaining_calls_today": max(caps.daily_calls - calls_today, 0),
        "remaining_notice_calls": max(caps.notice_calls - notice_calls, 0),
        "remaining_usd_today": round(max(caps.daily_usd - spent, 0.0), 6),
        "notice_allowed_today": notices_used <= caps.daily_notices,
        "caps": {"daily_notices": caps.daily_notices, "daily_calls": caps.daily_calls,
                 "notice_calls": caps.notice_calls, "daily_usd": caps.daily_usd},
    }


def _lock_budget(session):
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": BUDGET_LOCK_KEY})


class _Lines:
    """Reads the runner's frame pipe on a thread so the supervisor can enforce its deadline."""

    def __init__(self, stream):
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        self._thread.start()

    def _pump(self, stream):
        try:
            while True:
                line = stream.readline(wire.MAX_FRAME_BYTES + 1)
                self._queue.put(line)
                if not line:
                    return
        except Exception:  # noqa: BLE001 - the pipe closed under us
            self._queue.put(b"")

    def next(self, timeout: float) -> bytes:
        try:
            return self._queue.get(timeout=max(timeout, 0.001))
        except queue.Empty:
            raise LiveRunError("engine_live_deadline") from None


def spawn_runner(package_root: Path) -> subprocess.Popen:
    # No inherited credentials, proxies or shell. stderr may quote source text and is discarded.
    return subprocess.Popen(
        [sys.executable, "-m", "bid_deep_engine.runner", "--live-ipc"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={"PATH": os.defpath, "PYTHONPATH": str(package_root), "PYTHONIOENCODING": "utf-8",
             "PYTHONDONTWRITEBYTECODE": "1"},
    )


class Supervisor:
    def __init__(self, session, *, run_id, job_id, fence, worker_id, notice_id, manifest,
                 post=post_responses, clock=None, caps: Caps | None = None):
        settings = get_settings()
        self.session = session
        self.run_id = run_id
        self.job_id = job_id
        self.fence = fence
        self.worker_id = worker_id
        self.notice_id = notice_id
        self.manifest = manifest
        self.post = post
        self.clock = clock or (lambda: datetime.now(UTC))
        self.caps = caps or Caps.from_settings()
        self.call_timeout = settings.engine_live_call_timeout_seconds
        self.max_tokens = settings.engine_live_max_request_tokens
        self.planned_calls = min(int(manifest["planned_calls"]), self.caps.notice_calls)
        self.sequence = wire.CallSequence(first_request_sha256=manifest["live"]["first_request_sha256"])
        self.aborted: str | None = None
        self.calls = 0
        self.usd = 0.0

    # -- database steps (each its own short transaction) -------------------------------------

    def _job_is_ours(self, now):
        job = self.session.scalar(select(WorkJob).where(WorkJob.id == self.job_id).with_for_update())
        return job is not None and job.status == "running" and job.lease_owner == self.worker_id \
            and job.lease_fence == self.fence and job.lease_expires_at is not None \
            and job.lease_expires_at > now, job

    def reserve(self, seq, purpose, raw) -> EngineCall:
        now = self.clock()
        try:
            _lock_budget(self.session)
            ours, job = self._job_is_ours(now)
            if not ours:
                raise LiveRunError("engine_live_lease_lost")
            if seq > self.planned_calls:
                raise LiveRunError("planned_calls_exceeded")
            today = kst_today(now)
            budget = budget_snapshot(self.session, notice_id=self.notice_id, today=today,
                                     run_id=self.run_id, caps=self.caps)
            if (budget["remaining_calls_today"] <= 0 or budget["remaining_notice_calls"] <= 0
                    or budget["remaining_usd_today"] <= 0 or not budget["notice_allowed_today"]):
                raise LiveRunError("budget_exhausted")
            call = EngineCall(
                id=uuid4(), engine_run_id=self.run_id, notice_id=self.notice_id, seq=seq, purpose=purpose,
                transport=wire.TRANSPORT, model=wire.MODEL, kst_date=today, state="reserved",
                request_sha256=hashlib.sha256(raw).hexdigest(), request_bytes=len(raw),
                worker_id=self.worker_id, lease_fence=self.fence, reserved_at=now,
            )
            self.session.add(call)
            job.lease_expires_at = now + timedelta(seconds=self.call_timeout + LEASE_MARGIN_SECONDS)
            self.session.commit()
            return call
        except LiveRunError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise LiveRunError("engine_live_audit_failed") from None

    def finish(self, call_id, *, state, http_status=None, response=None, raw=None, duration_ms=None,
               error_class=None):
        try:
            call = self.session.get(EngineCall, call_id)
            call.state = state
            call.finished_at = self.clock()
            call.http_status = http_status
            call.duration_ms = duration_ms
            call.error_class = error_class
            if raw is not None:
                call.response_sha256 = hashlib.sha256(raw).hexdigest()
            if response is not None:
                call.response_status = str(response.get("status"))[:32]
                served = response.get("model")
                call.served_model = served[:64] if isinstance(served, str) else None
                counts = wire.usage(response)
                if counts is not None:
                    call.input_tokens = counts["input_tokens"]
                    call.cached_input_tokens = counts["cached_input_tokens"]
                    call.cache_write_input_tokens = counts["cache_write_input_tokens"]
                    call.output_tokens = counts["output_tokens"]
                    call.reasoning_output_tokens = counts["reasoning_output_tokens"]
                    cost = wire.usd(counts)
                    call.usd = Decimal(f"{cost:.6f}")
                    self.usd += cost
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise LiveRunError("engine_live_audit_failed") from None

    # -- one call ------------------------------------------------------------------------

    def handle(self, frame, *, url, api_key):
        """Returns the reply frame for one call frame. Sets `aborted` on the first refusal."""
        seq = frame.get("seq") if isinstance(frame, dict) else None
        if self.aborted:
            return {"frame": "abort", "seq": seq, "code": self.aborted}
        try:
            seq, purpose, body, raw = self.sequence.check(frame)
        except wire.WireRefusal as refusal:
            self.aborted = refusal.code
            return {"frame": "abort", "seq": seq, "code": refusal.code}
        if wire.estimated_tokens(body) > self.max_tokens:
            self.aborted = "request_too_large"
            return {"frame": "abort", "seq": seq, "code": self.aborted}
        try:
            call = self.reserve(seq, purpose, raw)
        except LiveRunError as error:
            self.aborted = error.code
            return {"frame": "abort", "seq": seq, "code": error.code}
        self.calls += 1
        started = time.monotonic()
        try:
            status, received = self.post(url, raw, api_key, self.call_timeout)
        except HttpFailure as failure:
            self.finish(call.id, state="http_error", http_status=failure.status,
                        duration_ms=int((time.monotonic() - started) * 1000), error_class="HttpFailure")
            self.aborted = "http_error"
            return {"frame": "abort", "seq": seq, "code": self.aborted}
        except Exception as error:  # noqa: BLE001 - after sending, the outcome is unknown
            self.finish(call.id, state="outcome_unknown",
                        duration_ms=int((time.monotonic() - started) * 1000), error_class=type(error).__name__[:64])
            self.aborted = "outcome_unknown"
            return {"frame": "abort", "seq": seq, "code": self.aborted}
        duration = int((time.monotonic() - started) * 1000)
        try:
            response = json.loads(received)
            if not isinstance(response, dict):
                raise ValueError
        except ValueError:
            self.finish(call.id, state="outcome_unknown", http_status=status, raw=received,
                        duration_ms=duration, error_class="ResponseNotJson")
            self.aborted = "outcome_unknown"
            return {"frame": "abort", "seq": seq, "code": self.aborted}
        completed = response.get("status") == "completed"
        self.finish(call.id, state="completed" if completed else "incomplete", http_status=status,
                    response=response, raw=received, duration_ms=duration)
        if not completed:
            self.aborted = "response_incomplete"
            return {"frame": "abort", "seq": seq, "code": self.aborted}
        return {"frame": "response", "seq": seq, "body": response, "duration_ms": duration}


def approved_manifest(session, run_id) -> dict:
    preview = session.scalar(
        select(EngineReviewPreview).join(EngineReviewApproval, EngineReviewApproval.preview_id == EngineReviewPreview.id)
        .where(EngineReviewApproval.engine_run_id == run_id, EngineReviewPreview.mode == "live")
    )
    if preview is None or not isinstance(preview.manifest.get("live"), dict):
        raise LiveRunError("engine_live_not_approved")
    return preview.manifest


def check_frozen_against_manifest(frozen, manifest):
    live = manifest["live"]
    if (frozen.get("mode") != "live" or frozen.get("engine_sha256") != manifest.get("engine_sha256")
            or live.get("transport") != wire.TRANSPORT or live.get("model") != wire.MODEL
            or live.get("reasoning_effort") != wire.EFFORT or live.get("wire_version") != wire.WIRE_VERSION
            or live.get("endpoint") != wire.RESPONSES_URL):
        raise LiveRunError("engine_live_not_approved")


def run(session, *, run_id, job_id, fence, worker_id, frozen, package_root, post=post_responses,
        spawn=spawn_runner, clock=None, caps: Caps | None = None) -> dict:
    """Run one approved live analysis. Returns the engine output with a `live` summary."""
    settings = get_settings()
    manifest = approved_manifest(session, run_id)
    check_frozen_against_manifest(frozen, manifest)
    run_row = session.get(EngineRun, run_id)
    notice_id = run_row.notice_id
    session.commit()
    url = endpoint()
    api_key = read_key(settings.engine_live_key_file)
    supervisor = Supervisor(session, run_id=run_id, job_id=job_id, fence=fence, worker_id=worker_id,
                            notice_id=notice_id, manifest=manifest, post=post, clock=clock, caps=caps)
    deadline = time.monotonic() + settings.engine_live_run_deadline_seconds
    process = spawn(package_root)
    lines = _Lines(process.stdout)
    output = None
    try:
        process.stdin.write(canonical_json_bytes(frozen) + b"\n")
        process.stdin.flush()
        while True:
            line = lines.next(deadline - time.monotonic())
            if not line or len(line) > wire.MAX_FRAME_BYTES:
                raise LiveRunError("engine_live_process_failed")
            try:
                frame = json.loads(line)
            except ValueError:
                raise LiveRunError("engine_live_output_invalid") from None
            if isinstance(frame, dict) and frame.get("frame") == "result":
                output = frame.get("output")
                break
            reply = supervisor.handle(frame, url=url, api_key=api_key)
            process.stdin.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            process.stdin.flush()
            if supervisor.aborted in {"engine_live_lease_lost", "engine_live_audit_failed"}:
                raise LiveRunError(supervisor.aborted)
    except (BrokenPipeError, OSError):
        raise LiveRunError("engine_live_process_failed") from None
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if not isinstance(output, dict):
        raise LiveRunError("engine_live_output_invalid")
    if supervisor.aborted:
        # The runner turns an abort into a failed pipeline; the supervisor's code is more precise.
        output = {**output, "status": "failed", "error_code": supervisor.aborted, "analysis": None}
    output["live"] = {
        "transport": wire.TRANSPORT, "model": wire.MODEL, "reasoning_effort": wire.EFFORT,
        "calls": supervisor.calls, "usd": round(supervisor.usd, 6), "price_source": wire.PRICE_SOURCE,
    }
    return output


def close_reserved_calls(session, run_id) -> int:
    """After a lost lease, any still-reserved request has an unknown outcome (never resent)."""
    rows = session.scalars(select(EngineCall).where(EngineCall.engine_run_id == run_id,
                                                    EngineCall.state == "reserved")).all()
    now = datetime.now(UTC)
    for row in rows:
        row.state = "outcome_unknown"
        row.finished_at = now
        row.error_class = "LeaseExpired"
    return len(rows)
