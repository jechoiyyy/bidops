#!/usr/bin/env python3
"""Score one C-2 quality gate measurement against the human gold sample.

This is a tool outside the product (docs/0918_daily-operation/spec.md §4.3:
"코드가 채점하지 않는다. 사람이 만든 gate artifact에서 읽어 기록한다"). It reads
the results of the measurement executions produced by
``scripts/run-c2-gate-measurement.sh``, compares them with the adjudicated gold
TSV, and writes a gate artifact draft plus the body a person can paste into
``POST /api/order-plan-screening/quality-gates/{gate_id}/evaluations``.

It never posts anything, never touches the product database and never writes to
the gold file. A person reads the artifact and decides whether to submit it.

Scoring rule (spec §4.2, docs/contracts.md "품질 게이트 REST"):

* predicted positive = 검토 후보 = ``stage1_status == "selected"`` and
  ``qwen_relevance in {"relevant", "uncertain"}`` — the same set the dashboard
  counts as ``order_plan_pending`` and the order-plan screen shows by default
  (docs/contracts.md:371, web/frontend/src/pages/OrderPlansPage.tsx:154).
* gold positive = ``effective_relevance == "관련"``.
* 중요 누락 (important missed) = gold positive with
  ``effective_priority == "높음"`` that is not a predicted positive. The "높음"
  axis follows experiments/order-plan-screening/scripts/compare.py:88-91.
* recall / precision / important_missed are summed over the published days of a
  pass; review_load is the **maximum** of the per-day 검토 후보 counts (one day's
  workload). A zero denominator stays ``null`` and never becomes a pass.

Inputs come from the REST read surface (``--api``) or from an offline dump
(``--results-json``), so the tool runs with no network in tests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterable


TOOL_NAME = "scripts/score-c2-gate.py"
TOOL_VERSION = "score-c2-gate.v1"
ARTIFACT_SCHEMA_VERSION = "bidops.order-plan-quality-gate-artifact.v1"
RESULTS_SCHEMA_VERSION = "bidops.order-plan-gate-scoring-results.v1"
EVALUATION_SCHEMA_VERSION = "order-plan-quality-evaluation-create-request.v1"

KST = timezone(timedelta(hours=9))

GOLD_POSITIVE = "관련"
GOLD_RELEVANCE_VALUES = {"관련", "비관련"}
GOLD_PRIORITY_VALUES = {"높음", "보통", "낮음", "해당없음"}
IMPORTANT_PRIORITY = "높음"
GOLD_REQUIRED_COLUMNS = {
    "plan_id",
    "published_at",
    "effective_relevance",
    "effective_priority",
    "label_source",
}

REVIEW_CANDIDATE_STAGE1 = "selected"
REVIEW_CANDIDATE_RELEVANCE = frozenset({"relevant", "uncertain"})
DEGRADED_STAGE1 = frozenset({"failed", "rejected"})
DEGRADED_STAGE2 = frozenset({"failed", "rejected", "unknown"})

EXECUTION_SUCCESS_STATUS = "성공"
GATE_RUN_ID_PATTERN = re.compile(r"^gate-gold-(\d{8})-plans$")
GATE_ID_PATTERN = re.compile(r"^c2gate-[0-9a-f]{32}$")
# uuid5 namespace for the evaluation request_id. Fixed so that re-running the
# tool on the same (gate, artifact) always suggests the same request_id and a
# repeated POST replays the original 201 instead of writing a second revision.
# Value: uuid5(NAMESPACE_URL, "urn:bidops:c2-gate-evaluation").
EVALUATION_REQUEST_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:bidops:c2-gate-evaluation")

PCT_DECIMALS = 4
HTTP_TIMEOUT_SECONDS = 30
PAGE_LIMIT = 500


class ScoringError(Exception):
    """A condition that must stop the scoring instead of being guessed away."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical artifact bytes: sorted keys, UTF-8, two-space indent, final newline."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-score-c2-gate-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.rename(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def round_pct(value: float | None) -> float | None:
    """Round to the 4 decimals the wire contract and Numeric(7,4) column allow."""
    if value is None:
        return None
    quantized = Decimal(repr(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    return float(quantized)


def ratio_pct(numerator: int, denominator: int) -> float | None:
    """`null` when the denominator is 0 — 계산 불가를 0이나 통과로 바꾸지 않는다."""
    if denominator <= 0:
        return None
    return round_pct(numerator * 100.0 / denominator)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScoringError("duplicate_json_key", f"JSON에 중복 key가 있습니다: {key}")
        result[key] = value
    return result


def read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except ScoringError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScoringError("invalid_json", f"JSON을 읽을 수 없습니다: {path}") from exc


# --------------------------------------------------------------------------
# gold
# --------------------------------------------------------------------------


class Gold:
    def __init__(
        self,
        path: Path,
        rows: dict[str, dict[str, str]],
        days: dict[str, date],
        manifest_path: Path | None,
        manifest: dict[str, Any] | None,
    ) -> None:
        self.path = path
        self.rows = rows
        self.days = days
        self.manifest_path = manifest_path
        self.manifest = manifest
        self.sha256 = sha256_file(path)
        self._summary: dict[str, Any] | None = None

    @property
    def plan_ids(self) -> set[str]:
        return set(self.rows)

    def is_positive(self, plan_id: str) -> bool:
        return self.rows[plan_id]["effective_relevance"] == GOLD_POSITIVE

    def is_important(self, plan_id: str) -> bool:
        return (
            self.is_positive(plan_id)
            and self.rows[plan_id]["effective_priority"] == IMPORTANT_PRIORITY
        )

    def published_days(self) -> list[date]:
        return sorted(set(self.days.values()))

    def summary(self) -> dict[str, Any]:
        if self._summary is not None:
            return self._summary
        positives = [plan_id for plan_id in self.rows if self.is_positive(plan_id)]
        draft_positives = sorted(
            plan_id for plan_id in positives if self.rows[plan_id]["label_source"] == "draft"
        )
        by_day: dict[str, dict[str, int]] = {}
        for plan_id, day in self.days.items():
            bucket = by_day.setdefault(day.isoformat(), {"population": 0, "gold_positive": 0, "important": 0})
            bucket["population"] += 1
            if self.is_positive(plan_id):
                bucket["gold_positive"] += 1
            if self.is_important(plan_id):
                bucket["important"] += 1
        self._summary = {
            "path": str(self.path),
            "sha256": self.sha256,
            "manifest_path": str(self.manifest_path) if self.manifest_path is not None else None,
            "manifest_sha256": (
                sha256_file(self.manifest_path) if self.manifest_path is not None else None
            ),
            "manifest_status": (self.manifest or {}).get("status"),
            "population_count": len(self.rows),
            "gold_positive_count": len(positives),
            "gold_important_count": sum(1 for plan_id in positives if self.is_important(plan_id)),
            "draft_labelled_positive_count": len(draft_positives),
            "draft_labelled_positive_plan_ids": draft_positives,
            "label_source_counts": dict(
                sorted(Counter(row["label_source"] for row in self.rows.values()).items())
            ),
            "published_days": [day.isoformat() for day in self.published_days()],
            "by_published_day": dict(sorted(by_day.items())),
        }
        return self._summary


def parse_published_day(value: str, plan_id: str) -> date:
    text = (value or "").strip()
    if not text:
        raise ScoringError("gold_invalid", f"published_at이 비었습니다: {plan_id}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScoringError("gold_invalid", f"published_at 형식이 잘못됐습니다: {plan_id} {text}") from exc
    if parsed.tzinfo is None:
        raise ScoringError("gold_invalid", f"published_at에 timezone이 없습니다: {plan_id} {text}")
    return parsed.astimezone(KST).date()


def load_gold(path: Path, manifest_path: Path | None) -> Gold:
    try:
        handle = path.open(encoding="utf-8", newline="")
    except OSError as exc:
        raise ScoringError("gold_unreadable", f"gold 파일을 읽을 수 없습니다: {path}") from exc
    rows: dict[str, dict[str, str]] = {}
    days: dict[str, date] = {}
    with handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or not GOLD_REQUIRED_COLUMNS <= set(reader.fieldnames):
            missing = sorted(GOLD_REQUIRED_COLUMNS - set(reader.fieldnames or []))
            raise ScoringError("gold_invalid", f"gold 열이 없습니다: {', '.join(missing)}")
        for row in reader:
            plan_id = (row.get("plan_id") or "").strip()
            if not plan_id:
                raise ScoringError("gold_invalid", "gold plan_id가 비었습니다")
            if plan_id in rows:
                raise ScoringError("gold_invalid", f"gold plan_id가 중복입니다: {plan_id}")
            relevance = (row.get("effective_relevance") or "").strip()
            priority = (row.get("effective_priority") or "").strip()
            if relevance not in GOLD_RELEVANCE_VALUES:
                raise ScoringError(
                    "gold_invalid", f"effective_relevance 값이 잘못됐습니다: {plan_id} {relevance!r}"
                )
            if priority not in GOLD_PRIORITY_VALUES:
                raise ScoringError(
                    "gold_invalid", f"effective_priority 값이 잘못됐습니다: {plan_id} {priority!r}"
                )
            rows[plan_id] = {
                "effective_relevance": relevance,
                "effective_priority": priority,
                "label_source": (row.get("label_source") or "").strip(),
            }
            days[plan_id] = parse_published_day(row.get("published_at", ""), plan_id)
    if not rows:
        raise ScoringError("gold_invalid", "gold에 행이 없습니다")

    manifest: dict[str, Any] | None = None
    resolved_manifest = manifest_path
    if resolved_manifest is None:
        sibling = path.parent / "manifest.json"
        if sibling.is_file():
            resolved_manifest = sibling
    if resolved_manifest is not None:
        loaded = read_json_file(resolved_manifest)
        if not isinstance(loaded, dict):
            raise ScoringError("gold_invalid", f"gold manifest가 object가 아닙니다: {resolved_manifest}")
        manifest = loaded
    return Gold(path, rows, days, resolved_manifest, manifest)


# --------------------------------------------------------------------------
# execution results
# --------------------------------------------------------------------------


class ExecutionResults:
    """One measurement execution: its binding facts plus one row per plan."""

    def __init__(self, raw: dict[str, Any], origin: str) -> None:
        self.origin = origin
        self.execution_id = _require_str(raw, "execution_id", origin)
        self.source_run_id = _require_str(raw, "source_run_id", origin)
        self.status = raw.get("status")
        self.purpose = raw.get("purpose")
        self.policy_version = raw.get("policy_version")
        self.policy_sha256 = raw.get("policy_sha256")
        self.binding_sha256 = raw.get("binding_sha256")
        self.population_count = raw.get("population_count")
        items = raw.get("items")
        if not isinstance(items, list) or not items:
            raise ScoringError("results_invalid", f"items가 비었습니다: {origin} {self.execution_id}")
        self.items: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ScoringError("results_invalid", f"item이 object가 아닙니다: {origin}")
            plan_id = str(item.get("plan_id") or item.get("order_plan_unty_no") or "").strip()
            if not plan_id:
                raise ScoringError("results_invalid", f"item에 plan_id가 없습니다: {origin}")
            if plan_id in self.items:
                raise ScoringError(
                    "results_invalid",
                    f"한 실행에 같은 plan_id가 두 번 있습니다: {self.execution_id} {plan_id}",
                )
            self.items[plan_id] = {
                "stage1_status": item.get("stage1_status"),
                "stage2_status": item.get("stage2_status"),
                "qwen_relevance": item.get("qwen_relevance"),
            }

    @property
    def plan_ids(self) -> set[str]:
        return set(self.items)

    def is_review_candidate(self, plan_id: str) -> bool:
        row = self.items[plan_id]
        return (
            row["stage1_status"] == REVIEW_CANDIDATE_STAGE1
            and row["qwen_relevance"] in REVIEW_CANDIDATE_RELEVANCE
        )

    def degraded_counts(self) -> dict[str, int]:
        stage1_degraded = sum(
            1 for row in self.items.values() if row["stage1_status"] in DEGRADED_STAGE1
        )
        stage2_degraded = sum(
            1
            for row in self.items.values()
            if row["stage1_status"] == REVIEW_CANDIDATE_STAGE1
            and row["stage2_status"] in DEGRADED_STAGE2
        )
        missing_result = sum(1 for row in self.items.values() if row["stage1_status"] is None)
        return {
            "stage1_failed_or_rejected": stage1_degraded,
            "stage2_failed_rejected_or_unknown": stage2_degraded,
            "no_result_row": missing_result,
        }

    def to_dump(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "source_run_id": self.source_run_id,
            "status": self.status,
            "purpose": self.purpose,
            "policy_version": self.policy_version,
            "policy_sha256": self.policy_sha256,
            "binding_sha256": self.binding_sha256,
            "population_count": self.population_count,
            "items": [
                {"plan_id": plan_id, **self.items[plan_id]} for plan_id in sorted(self.items)
            ],
        }


def _require_str(raw: dict[str, Any], key: str, origin: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScoringError("results_invalid", f"{key}가 없습니다: {origin}")
    return value.strip()


def load_results_dumps(paths: Iterable[Path]) -> dict[str, ExecutionResults]:
    loaded: dict[str, ExecutionResults] = {}
    for path in paths:
        payload = read_json_file(path)
        if isinstance(payload, dict):
            executions = payload.get("executions")
        else:
            executions = payload
        if not isinstance(executions, list):
            raise ScoringError("results_invalid", f"executions 목록이 없습니다: {path}")
        for raw in executions:
            if not isinstance(raw, dict):
                raise ScoringError("results_invalid", f"execution이 object가 아닙니다: {path}")
            result = ExecutionResults(raw, origin=str(path))
            if result.execution_id in loaded:
                raise ScoringError(
                    "results_invalid",
                    f"같은 execution_id가 두 dump에 있습니다: {result.execution_id}",
                )
            loaded[result.execution_id] = result
    return loaded


# --------------------------------------------------------------------------
# REST read surface
# --------------------------------------------------------------------------


class ApiClient:
    """Read-only client. Only GET is implemented — this tool never writes."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise ScoringError("api_error", f"GET {path} → HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ScoringError("api_unreachable", f"GET {path} 실패: {exc.reason}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ScoringError("api_error", f"GET {path} 응답이 JSON이 아닙니다") from exc


def fetch_execution_results(client: ApiClient, execution_id: str) -> ExecutionResults:
    """Read one measurement execution and the per-plan rows it produced.

    The list endpoint has no `execution_id` filter: `GET /api/order-plans` in
    회차 모드 answers with **the latest completed execution of that source run**
    (services/order_plan_screening.py:1110-1113). So the rows of pass 1 are only
    reachable until pass 2 of the same run finishes. The tool refuses to score
    the wrong execution's rows and tells the person to use --dump-results after
    each pass (or --results-json for an earlier dump).
    """
    detail = client.get(f"/api/order-plan-screening/executions/{execution_id}")
    if not isinstance(detail, dict) or "source_run_id" not in detail:
        raise ScoringError("api_error", f"execution 응답 형식이 아닙니다: {execution_id}")
    source_run_id = detail["source_run_id"]

    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = client.get(
            "/api/order-plans",
            {"source_run_id": source_run_id, "limit": PAGE_LIMIT, "offset": offset},
        )
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ScoringError("api_error", f"order-plans 응답 형식이 아닙니다: {source_run_id}")
        scope = page.get("scope") or {}
        if scope.get("mode") != "run":
            raise ScoringError(
                "api_scope_missing",
                f"{source_run_id}에 완료된 실행이 없어 회차 모드로 읽을 수 없습니다",
            )
        if str(scope.get("execution_id")) != execution_id:
            raise ScoringError(
                "execution_not_latest",
                (
                    f"{source_run_id}의 최신 완료 실행은 {scope.get('execution_id')}이며 "
                    f"{execution_id}의 결과는 REST로 읽을 수 없습니다. pass마다 --dump-results로 "
                    "결과를 받아 두고 --results-json으로 채점한다"
                ),
            )
        items.extend(page["items"])
        total = int(page.get("total") or 0)
        offset += PAGE_LIMIT
        if offset >= total or not page["items"]:
            break

    raw = {
        "execution_id": execution_id,
        "source_run_id": source_run_id,
        "status": detail.get("status"),
        "purpose": detail.get("purpose"),
        "policy_version": detail.get("policy_version"),
        "policy_sha256": detail.get("policy_sha256"),
        "binding_sha256": detail.get("binding_sha256"),
        "population_count": detail.get("population_count"),
        "items": items,
    }
    return ExecutionResults(raw, origin=f"api:{client.base_url}")


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def assign_published_day(gold: Gold, execution: ExecutionResults) -> date:
    unknown = sorted(execution.plan_ids - gold.plan_ids)
    if unknown:
        raise ScoringError(
            "population_mismatch",
            f"gold에 없는 plan이 실행 {execution.execution_id}에 있습니다: {', '.join(unknown[:5])}"
            + (f" 외 {len(unknown) - 5}건" if len(unknown) > 5 else ""),
        )
    days = {gold.days[plan_id] for plan_id in execution.plan_ids}
    if len(days) != 1:
        raise ScoringError(
            "execution_mixes_published_days",
            f"실행 {execution.execution_id}의 모집단이 게시일 {len(days)}개에 걸쳐 있습니다",
        )
    day = days.pop()
    match = GATE_RUN_ID_PATTERN.match(execution.source_run_id)
    if match and match.group(1) != f"{day:%Y%m%d}":
        raise ScoringError(
            "run_id_day_mismatch",
            f"회차 {execution.source_run_id}의 모집단 게시일은 {day.isoformat()}입니다",
        )
    return day


def score_pass(
    gold: Gold, executions: list[ExecutionResults], warnings: list[dict[str, str]], label: str
) -> dict[str, Any]:
    by_day: dict[date, ExecutionResults] = {}
    for execution in executions:
        day = assign_published_day(gold, execution)
        if day in by_day:
            raise ScoringError(
                "duplicate_published_day",
                f"{label}: 게시일 {day.isoformat()}에 실행이 두 개입니다 "
                f"({by_day[day].execution_id}, {execution.execution_id})",
            )
        by_day[day] = execution

    covered = set().union(*(execution.plan_ids for execution in executions))
    missing = sorted(gold.plan_ids - covered)
    if missing:
        raise ScoringError(
            "population_mismatch",
            f"{label}: gold의 plan {len(missing)}건이 실행 모집단에 없습니다: "
            + ", ".join(missing[:5]),
        )

    # bundle identity: every execution of a pass must carry the same policy and
    # binding digest (spec §4.2 "같은 묶음"). A dump without them cannot be checked.
    digests = {
        (execution.policy_version, execution.policy_sha256, execution.binding_sha256)
        for execution in executions
    }
    if len(digests) > 1:
        raise ScoringError(
            "bundle_mismatch",
            f"{label}: 실행들의 policy·binding digest가 서로 다릅니다",
        )
    if any(value is None for value in next(iter(digests))):
        warnings.append(
            {
                "code": "bundle_digest_unknown",
                "message": f"{label}: policy·binding digest가 없어 같은 묶음인지 확인하지 못했습니다",
            }
        )

    day_rows: dict[str, Any] = {}
    totals = {
        "population": 0,
        "gold_positive": 0,
        "predicted_positive": 0,
        "true_positive": 0,
        "false_positive": 0,
        "false_negative": 0,
        "important_missed": 0,
    }
    review_loads: list[int] = []
    for day in sorted(by_day):
        execution = by_day[day]
        if execution.status != EXECUTION_SUCCESS_STATUS:
            warnings.append(
                {
                    "code": "execution_not_successful",
                    "message": (
                        f"{label}: 실행 {execution.execution_id}({day.isoformat()})의 상태가 "
                        f"{execution.status!r}입니다. 측정값은 계산했지만 판정은 사람이 본다"
                    ),
                }
            )
        if execution.purpose is not None and execution.purpose != "gate_measurement":
            warnings.append(
                {
                    "code": "execution_not_gate_measurement",
                    "message": (
                        f"{label}: 실행 {execution.execution_id}의 purpose가 "
                        f"{execution.purpose!r}입니다(측정 전용 실행이 아닙니다)"
                    ),
                }
            )
        degraded = execution.degraded_counts()
        if any(degraded.values()):
            warnings.append(
                {
                    "code": "degraded_rows",
                    "message": (
                        f"{label}: 실행 {execution.execution_id}에 판정을 내지 못한 행이 있습니다 "
                        f"({json.dumps(degraded, ensure_ascii=False, sort_keys=True)}). "
                        "이 행은 예측 음성으로 셌다"
                    ),
                }
            )

        predicted = {plan_id for plan_id in execution.plan_ids if execution.is_review_candidate(plan_id)}
        positives = {plan_id for plan_id in execution.plan_ids if gold.is_positive(plan_id)}
        true_positive = sorted(predicted & positives)
        false_negative = sorted(positives - predicted)
        false_positive = sorted(predicted - positives)
        important_missed = sorted(plan_id for plan_id in false_negative if gold.is_important(plan_id))

        totals["population"] += len(execution.plan_ids)
        totals["gold_positive"] += len(positives)
        totals["predicted_positive"] += len(predicted)
        totals["true_positive"] += len(true_positive)
        totals["false_positive"] += len(false_positive)
        totals["false_negative"] += len(false_negative)
        totals["important_missed"] += len(important_missed)
        review_loads.append(len(predicted))

        day_rows[day.isoformat()] = {
            "execution_id": execution.execution_id,
            "source_run_id": execution.source_run_id,
            "execution_status": execution.status,
            "population": len(execution.plan_ids),
            "gold_positive": len(positives),
            "review_candidates": len(predicted),
            "true_positive": len(true_positive),
            "false_positive": len(false_positive),
            "false_negative": len(false_negative),
            "false_negative_plan_ids": false_negative,
            "important_missed": len(important_missed),
            "important_missed_plan_ids": important_missed,
            "degraded_counts": degraded,
        }

    metrics = {
        "recall_pct": ratio_pct(totals["true_positive"], totals["gold_positive"]),
        "precision_pct": ratio_pct(totals["true_positive"], totals["predicted_positive"]),
        "important_missed": totals["important_missed"],
        "review_load": max(review_loads) if review_loads else None,
    }
    # 4일치 일괄 참고값: the same per-day results pooled over the whole window,
    # so review_load is the window total (ADR-0037's "사람 검토 후보 127건"),
    # not the per-day maximum. It is a reference, not the pass rule (spec §4.2).
    reference_full_window = {
        "recall_pct": metrics["recall_pct"],
        "precision_pct": metrics["precision_pct"],
        "important_missed": totals["important_missed"],
        "review_load": totals["predicted_positive"],
    }
    return {
        "executions": [
            {
                "execution_id": by_day[day].execution_id,
                "source_run_id": by_day[day].source_run_id,
                "published_day": day.isoformat(),
                "status": by_day[day].status,
                "purpose": by_day[day].purpose,
                "policy_version": by_day[day].policy_version,
                "policy_sha256": by_day[day].policy_sha256,
                "binding_sha256": by_day[day].binding_sha256,
                "population_count": by_day[day].population_count,
                "origin": by_day[day].origin,
            }
            for day in sorted(by_day)
        ],
        "metrics": metrics,
        "totals": totals,
        "reference_full_window": reference_full_window,
        "by_published_day": day_rows,
        "all_successful": all(
            execution.status == EXECUTION_SUCCESS_STATUS for execution in executions
        ),
    }


def prediction_map(executions: list[ExecutionResults]) -> dict[str, bool]:
    predictions: dict[str, bool] = {}
    for execution in executions:
        for plan_id in execution.plan_ids:
            predictions[plan_id] = execution.is_review_candidate(plan_id)
    return predictions


def score_agreement(
    pass_1: list[ExecutionResults], pass_2: list[ExecutionResults]
) -> dict[str, Any]:
    """건별 예측 양성 여부가 같은 비율 (spec §4.2, 임계값은 두지 않는다)."""
    first = prediction_map(pass_1)
    second = prediction_map(pass_2)
    shared = sorted(set(first) & set(second))
    disagreements = [plan_id for plan_id in shared if first[plan_id] != second[plan_id]]
    return {
        "compared_count": len(shared),
        "agreement_count": len(shared) - len(disagreements),
        "agreement_pct": ratio_pct(len(shared) - len(disagreements), len(shared)),
        "disagreement_count": len(disagreements),
        "disagreement_plan_ids": disagreements,
    }


def worse_side(first: dict[str, Any], second: dict[str, Any] | None) -> dict[str, Any]:
    """recall·precision은 작은 값, 누락·검토량은 큰 값 (docs/contracts.md:1319)."""
    if second is None:
        return dict(first)

    def smaller(key: str) -> Any:
        values = [first.get(key), second.get(key)]
        return None if any(value is None for value in values) else min(values)

    def larger(key: str) -> Any:
        values = [first.get(key), second.get(key)]
        return None if any(value is None for value in values) else max(values)

    return {
        "recall_pct": smaller("recall_pct"),
        "precision_pct": smaller("precision_pct"),
        "important_missed": larger("important_missed"),
        "review_load": larger("review_load"),
    }


# --------------------------------------------------------------------------
# artifact and report
# --------------------------------------------------------------------------


def build_artifact(
    *,
    gold: Gold,
    gate_id: str | None,
    pass_1: dict[str, Any],
    pass_2: dict[str, Any] | None,
    agreement: dict[str, Any] | None,
    warnings: list[dict[str, str]],
    tool_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "producer": TOOL_NAME,
        "created_at": datetime.now(KST).isoformat(),
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION, "sha256": tool_sha256},
        "gate_id": gate_id,
        "scoring_rule": {
            "predicted_positive": "stage1_status == 'selected' AND qwen_relevance IN ('relevant','uncertain')",
            "gold_positive": "effective_relevance == '관련'",
            "important_missed": "gold_positive AND effective_priority == '높음' AND NOT predicted_positive",
            "scoring_unit": "per_published_day",
            "aggregation": "recall·precision·important_missed는 게시일 합산, review_load는 게시일별 최댓값",
            "zero_denominator": "null (계산 불가를 통과로 바꾸지 않는다)",
            "reference_full_window": "같은 게시일별 결과를 4일 전체로 합산한 참고값. review_load는 창 전체 합계",
            "source": "docs/0918_daily-operation/spec.md §4.2, docs/contracts.md '품질 게이트 REST'",
        },
        "gold": gold.summary(),
        "passes": {"pass_1": pass_1, "pass_2": pass_2},
        "agreement": agreement,
        "measured_worse_side": worse_side(
            pass_1["metrics"], pass_2["metrics"] if pass_2 is not None else None
        ),
        "reference_full_window_worse_side": worse_side(
            pass_1["reference_full_window"],
            pass_2["reference_full_window"] if pass_2 is not None else None,
        ),
        "warnings": sorted(warnings, key=lambda item: (item["code"], item["message"])),
        "note": (
            "이 파일은 도구가 만든 gate artifact 초안이다. 사람이 값을 확인한 뒤에만 "
            "POST /api/order-plan-screening/quality-gates/{gate_id}/evaluations로 제출한다. "
            "도구는 어떤 것도 POST하지 않는다."
        ),
    }


def build_evaluation_body(
    *,
    gate_id: str | None,
    artifact: dict[str, Any],
    artifact_sha256: str,
    pass_1_ids: list[str],
    pass_2_ids: list[str] | None,
) -> dict[str, Any]:
    pass_1 = artifact["passes"]["pass_1"]
    pass_2 = artifact["passes"]["pass_2"]
    seed = f"{gate_id or 'unknown-gate'}|{artifact_sha256}"
    # 경고를 그대로 reasons로 옮긴다. 사람이 제출 전에 지우거나 더할 수 있다.
    reasons = [f"{warning['code']}: {warning['message']}"[:500] for warning in artifact["warnings"]]
    body: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "producer": "human-review-client",
        "consumer": "quality-gate-api",
        "request_id": str(uuid.uuid5(EVALUATION_REQUEST_NAMESPACE, seed)),
        "artifact_sha256": artifact_sha256,
        "pass_execution_ids": {
            "pass_1": pass_1_ids,
            "pass_2": pass_2_ids,
        },
        "pass_metrics": {
            "pass_1": pass_1["metrics"],
            "pass_2": pass_2["metrics"] if pass_2 is not None else None,
        },
        "agreement_pct": (artifact["agreement"] or {}).get("agreement_pct"),
        "reference_full_window": artifact["reference_full_window_worse_side"],
        "reasons": reasons[:20],
    }
    return body


def render_summary(artifact: dict[str, Any], artifact_path: Path, artifact_sha256: str) -> str:
    lines: list[str] = []
    gold = artifact["gold"]
    lines.append("# C-2 품질 게이트 채점 요약 (도구 초안)")
    lines.append("")
    lines.append(f"- artifact: `{artifact_path}`")
    lines.append(f"- artifact sha256: `{artifact_sha256}`")
    lines.append(f"- gate_id: {artifact['gate_id'] or '(주지 않음)'}")
    lines.append(f"- gold: `{gold['path']}` sha256 `{gold['sha256']}` ({gold['manifest_status'] or '상태 미상'})")
    lines.append(
        f"- gold 모집단 {gold['population_count']}건 / 양성 {gold['gold_positive_count']}건 "
        f"/ 중요(높음) {gold['gold_important_count']}건 / 양성 중 draft 라벨 "
        f"{gold['draft_labelled_positive_count']}건"
    )
    lines.append("")
    lines.append("## pass별 지표")
    lines.append("")
    lines.append("| pass | recall % | precision % | 중요 누락 | 하루 최대 검토량 | 실행 전부 성공 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for key in ("pass_1", "pass_2"):
        block = artifact["passes"][key]
        if block is None:
            lines.append(f"| {key} | — | — | — | — | (없음) |")
            continue
        metrics = block["metrics"]
        lines.append(
            f"| {key} | {_fmt(metrics['recall_pct'])} | {_fmt(metrics['precision_pct'])} | "
            f"{_fmt(metrics['important_missed'])} | {_fmt(metrics['review_load'])} | "
            f"{'예' if block['all_successful'] else '아니오'} |"
        )
    worse = artifact["measured_worse_side"]
    lines.append(
        f"| 나쁜 쪽 | {_fmt(worse['recall_pct'])} | {_fmt(worse['precision_pct'])} | "
        f"{_fmt(worse['important_missed'])} | {_fmt(worse['review_load'])} | — |"
    )
    lines.append("")
    agreement = artifact["agreement"]
    if agreement is not None:
        lines.append(
            f"두 pass 판정 일치율: {_fmt(agreement['agreement_pct'])}% "
            f"({agreement['agreement_count']}/{agreement['compared_count']}, "
            f"불일치 {agreement['disagreement_count']}건)"
        )
    else:
        lines.append("두 pass 판정 일치율: 계산 불가(pass 2 없음)")
    reference = artifact["reference_full_window_worse_side"]
    lines.append(
        f"참고(4일 일괄): recall {_fmt(reference['recall_pct'])}% / precision "
        f"{_fmt(reference['precision_pct'])}% / 중요 누락 {_fmt(reference['important_missed'])} / "
        f"검토 후보 {_fmt(reference['review_load'])}건"
    )
    lines.append("")
    lines.append("## 게시일별 분해")
    lines.append("")
    lines.append("| pass | 게시일 | 모집단 | gold 양성 | 검토 후보 | TP | FP | FN | 중요 누락 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("pass_1", "pass_2"):
        block = artifact["passes"][key]
        if block is None:
            continue
        for day, row in block["by_published_day"].items():
            lines.append(
                f"| {key} | {day} | {row['population']} | {row['gold_positive']} | "
                f"{row['review_candidates']} | {row['true_positive']} | {row['false_positive']} | "
                f"{row['false_negative']} | {row['important_missed']} |"
            )
    lines.append("")
    if artifact["warnings"]:
        lines.append("## 경고")
        lines.append("")
        for warning in artifact["warnings"]:
            lines.append(f"- `{warning['code']}` {warning['message']}")
        lines.append("")
    lines.append(
        "도구는 계산만 한다. 사람이 이 값을 확인한 뒤 evaluations POST로 기록한다."
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    return "null" if value is None else str(value)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scripts/score-c2-gate.py",
        description=(
            "C-2 품질 게이트 측정 실행을 gold와 대조해 gate artifact 초안과 evaluations POST "
            "body 예시를 만든다. 아무것도 POST하지 않는다."
        ),
    )
    parser.add_argument("--gold", required=True, type=Path, help="gold TSV 경로")
    parser.add_argument(
        "--gold-manifest",
        type=Path,
        default=None,
        help="gold manifest.json 경로 (기본값: gold 파일 옆 manifest.json)",
    )
    parser.add_argument(
        "--pass1", nargs="+", required=True, metavar="EXECUTION_ID", help="pass 1의 실행 id 목록"
    )
    parser.add_argument(
        "--pass2", nargs="+", default=None, metavar="EXECUTION_ID", help="pass 2의 실행 id 목록"
    )
    parser.add_argument("--gate-id", default=None, help="c2gate-<32 hex>. 주면 artifact와 POST 예시에 넣는다")
    parser.add_argument("--api", default=None, help="web base URL. 예: http://127.0.0.1:18787")
    parser.add_argument(
        "--results-json",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="오프라인 결과 dump. 여러 번 줄 수 있다. 여기 있는 실행은 --api로 읽지 않는다",
    )
    parser.add_argument("--out", required=True, type=Path, help="gate artifact JSON을 쓸 경로")
    parser.add_argument("--summary-out", type=Path, default=None, help="사람이 읽는 요약 .md 경로")
    parser.add_argument("--body-out", type=Path, default=None, help="evaluations POST body 예시 경로")
    parser.add_argument(
        "--dump-results",
        type=Path,
        default=None,
        help="읽은 결과를 --results-json 형식으로 저장한다(pass 1을 뒤에 다시 채점하려면 필요)",
    )
    return parser.parse_args(argv)


def collect_executions(
    ids: list[str],
    dumps: dict[str, ExecutionResults],
    client: ApiClient | None,
    warnings: list[dict[str, str]],
) -> list[ExecutionResults]:
    executions: list[ExecutionResults] = []
    seen: set[str] = set()
    for execution_id in ids:
        if execution_id in seen:
            raise ScoringError("duplicate_execution_id", f"실행 id가 중복됐습니다: {execution_id}")
        seen.add(execution_id)
        if execution_id in dumps:
            executions.append(dumps[execution_id])
            continue
        if client is None:
            raise ScoringError(
                "results_missing",
                f"{execution_id}의 결과가 없습니다. --results-json에 넣거나 --api를 주십시오",
            )
        executions.append(fetch_execution_results(client, execution_id))
    return executions


def validate_uuid(value: str) -> str:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise ScoringError("invalid_execution_id", f"실행 id가 UUID가 아닙니다: {value}") from exc
    return value


def run(args: argparse.Namespace) -> int:
    if args.gate_id is not None and not GATE_ID_PATTERN.match(args.gate_id):
        raise ScoringError("invalid_gate_id", f"--gate-id는 c2gate-<32 hex>입니다: {args.gate_id}")
    pass_1_ids = [validate_uuid(value) for value in args.pass1]
    pass_2_ids = [validate_uuid(value) for value in args.pass2] if args.pass2 else None
    if pass_2_ids is not None and set(pass_1_ids) & set(pass_2_ids):
        raise ScoringError("duplicate_execution_id", "pass 1과 pass 2가 같은 실행을 가리킵니다")

    warnings: list[dict[str, str]] = []
    gold = load_gold(args.gold, args.gold_manifest)
    dumps = load_results_dumps(args.results_json)
    client = ApiClient(args.api) if args.api else None

    pass_1_executions = collect_executions(pass_1_ids, dumps, client, warnings)
    pass_2_executions = (
        collect_executions(pass_2_ids, dumps, client, warnings) if pass_2_ids is not None else None
    )

    if args.dump_results is not None:
        everything = list(pass_1_executions) + list(pass_2_executions or [])
        atomic_write_bytes(
            args.dump_results,
            canonical_json_bytes(
                {
                    "schema_version": RESULTS_SCHEMA_VERSION,
                    "executions": [
                        execution.to_dump()
                        for execution in sorted(everything, key=lambda item: item.execution_id)
                    ],
                }
            ),
        )

    if pass_2_executions is None:
        warnings.append(
            {
                "code": "pass_2_missing",
                "message": "pass 2가 없습니다. 게이트는 같은 묶음 두 pass가 모두 통과해야 통과다(보류)",
            }
        )
    if gold.summary()["draft_labelled_positive_count"]:
        warnings.append(
            {
                "code": "gold_draft_positive",
                "message": (
                    f"gold 양성 중 {gold.summary()['draft_labelled_positive_count']}건이 "
                    "label_source=draft다. 사람이 확정 여부를 판단한다"
                ),
            }
        )

    pass_1 = score_pass(gold, pass_1_executions, warnings, "pass 1")
    pass_2 = (
        score_pass(gold, pass_2_executions, warnings, "pass 2")
        if pass_2_executions is not None
        else None
    )
    agreement = (
        score_agreement(pass_1_executions, pass_2_executions)
        if pass_2_executions is not None
        else None
    )

    artifact = build_artifact(
        gold=gold,
        gate_id=args.gate_id,
        pass_1=pass_1,
        pass_2=pass_2,
        agreement=agreement,
        warnings=warnings,
        tool_sha256=sha256_file(Path(__file__).resolve()),
    )
    payload = canonical_json_bytes(artifact)
    atomic_write_bytes(args.out, payload)
    artifact_sha256 = hashlib.sha256(payload).hexdigest()

    body = build_evaluation_body(
        gate_id=args.gate_id,
        artifact=artifact,
        artifact_sha256=artifact_sha256,
        pass_1_ids=pass_1_ids,
        pass_2_ids=pass_2_ids,
    )
    if args.body_out is not None:
        atomic_write_bytes(args.body_out, canonical_json_bytes(body))

    summary = render_summary(artifact, args.out, artifact_sha256)
    if args.summary_out is not None:
        atomic_write_bytes(args.summary_out, summary.encode("utf-8"))
    sys.stdout.write(summary)
    sys.stdout.write("\n")
    sys.stdout.write(
        f"POST /api/order-plan-screening/quality-gates/{args.gate_id or '<gate_id>'}/evaluations\n"
    )
    sys.stdout.write(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    for warning in artifact["warnings"]:
        sys.stderr.write(f"warning: {warning['code']}: {warning['message']}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except ScoringError as error:
        sys.stderr.write(f"error: {error.code}: {error.message}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
