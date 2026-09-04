"""Deterministic quality-gate calculations.

The quality gate deliberately lives outside the model/runtime worker.  This
module accepts already materialised v3 judgments and returns JSON-safe values;
it never repairs a judgment, invents a denominator, or rounds a value before
comparing it with a threshold.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .artifacts import canonical_bytes
from .contracts import ContractViolation, PERSPECTIVE_NAMES, two_axis_mixing, validate_judgment
from ..core.config import get_settings
from ..core.generation_config import GenerationConfigError, config_from_value, legacy_generation_config, validate_digest


VALID_GRADES = frozenset({"우선 검토", "검토 권장", "관찰 대상", "제외"})
VALID_ASSESSMENTS = frozenset({"적합", "부분 적합", "부적합", "확인 불가"})
MIXING_GRADES = frozenset({"관찰 대상", "제외"})
VALID_REVIEW_VALUES = frozenset({"동의", "근거 부족", "판단 보류"})
_JUDGMENT_CORE_KEYS = frozenset({
    "notice_id", "grade", "readiness", "primary_focus", "exclusion_category", "summary", "next_action",
    "perspectives", "matched_performances", "counterarguments", "counterargument_resolutions", "verification_items",
})
_JUDGMENT_METADATA_KEYS = frozenset({
    "judgment_mode", "model_name", "model_digest", "prompt_version", "policy_version",
    "company_profile_version", "company_profile_digest", "judged_in_run", "recorded_in_run",
    "carried_over", "rejudge_reason", "two_axis_mixing_flag", "two_axis_mixing_label",
})
_DECISIONS_KEYS = frozenset({
    "schema_version", "execution_id", "run_id", "generated_at", "screening_basis",
    "model_name", "model_digest", "prompt_version", "policy_version",
    "company_profile_version", "company_profile_digest", "judgments",
    "generation_config", "generation_config_digest",
})
_EXECUTION_ID_RE = re.compile(r"^scr-[0-9a-f]{32}$")
SCREENING_BASIS = "회차에 고정된 정규화 공고와 회사 프로필·정책 버전"


class QualityMetricError(ValueError):
    """An input cannot be evaluated without making up data."""


def judgment_digest(judgment: Mapping[str, Any]) -> str:
    """Return the canonical digest bound to a pass-A review.

    The caller must pass the complete judgment object, including ``notice_id``.
    This is intentionally the same canonical JSON rule used by artifacts.
    """

    if not isinstance(judgment, Mapping):
        raise QualityMetricError("judgment must be an object")
    return hashlib.sha256(canonical_bytes(dict(judgment))).hexdigest()


def frozen_input_digest(input_value: Mapping[str, Any]) -> str:
    """Digest the frozen combination while ignoring execution identity.

    ``screening-input.v1`` binds its own execution ID and creation timestamp,
    so two independent queue rows cannot have byte-identical input files. For
    A/B equivalence we compare the frozen combination (all input fields except
    those per-execution identities) and expose this helper for callers/tests
    that need that exact semantic identity.
    """

    if not isinstance(input_value, Mapping):
        raise QualityMetricError("input must be an object")
    value = dict(input_value)
    value.pop("execution_id", None)
    value.pop("generated_at", None)
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    exact = (Decimal(numerator) / Decimal(denominator)) * Decimal(100)
    return float(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _exact_percent(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return ((Decimal(numerator) / Decimal(denominator)) * Decimal(100))


def ratio(
    numerator: int,
    denominator: int,
    *,
    status: str = "측정 완료",
) -> dict[str, Any]:
    """Build the shared metric object with an unrounded threshold value."""

    if type(numerator) is not int or type(denominator) is not int:
        raise QualityMetricError("metric counts must be integers")
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise QualityMetricError("metric counts are invalid")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": _percent(numerator, denominator),
        "status": status,
    }


def _judgment_map(
    pass_value: Any,
    *,
    pass_name: str,
    strict: bool = True,
    notices: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, str]]]:
    """Return only complete, in-sample-eligible judgment objects.

    Pass A/B outputs are model-bound decisions.v3 objects.  A handful of
    fields (grade and five assessments) is not sufficient for any quality
    denominator: accepting it would make a malformed worker response look
    like a valid sample.  The shared deterministic validator is intentionally
    used here so this boundary stays identical to the worker boundary.

    The Claude artifact is an older comparison baseline, so it uses the
    legacy shape check and never becomes an input to a Qwen denominator.
    """

    def issue(notice_id: Any, reason: str) -> dict[str, str]:
        return {"notice_id": str(notice_id) if isinstance(notice_id, str) else "", "pass": pass_name, "reason": reason}

    if not isinstance(pass_value, Mapping):
        return {}, [issue("", "decisions_not_object")]
    if strict:
        # Keep the pure metric helper compatible with pre-0005 fixture
        # artifacts. The quality-gate service performs the stricter frozen
        # input/decision binding before this helper is called.
        if set(pass_value) == _DECISIONS_KEYS - {"generation_config", "generation_config_digest"}:
            legacy = legacy_generation_config()
            pass_value = {**pass_value, "generation_config": legacy.canonical_value(), "generation_config_digest": legacy.digest()}
        if set(pass_value) != _DECISIONS_KEYS:
            return {}, [issue("", "decisions_top_level_invalid")]
        if pass_value.get("schema_version") != "bidops.decisions.v3":
            return {}, [issue("", "decisions_schema_invalid")]
        for key in ("execution_id", "run_id", "generated_at", "screening_basis", "model_name", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest"):
            if not isinstance(pass_value.get(key), str) or not pass_value[key].strip():
                return {}, [issue("", f"decisions_{key}_invalid")]
        if pass_value["screening_basis"] != SCREENING_BASIS:
            return {}, [issue("", "decisions_screening_basis_invalid")]
        for key in ("model_digest", "company_profile_digest"):
            if not isinstance(pass_value.get(key), str) or len(pass_value[key]) != 64 or any(char not in "0123456789abcdef" for char in pass_value[key]):
                return {}, [issue("", f"decisions_{key}_invalid")]
        if pass_value["company_profile_version"] != f"company-profile.sha256:{pass_value['company_profile_digest']}":
            return {}, [issue("", "decisions_profile_identity_invalid")]
        try:
            generation_config = config_from_value(pass_value.get("generation_config"))
            if validate_digest(generation_config, pass_value.get("generation_config_digest")) != generation_config.digest():
                return {}, [issue("", "decisions_generation_config_invalid")]
        except GenerationConfigError:
            return {}, [issue("", "decisions_generation_config_invalid")]
        if not _EXECUTION_ID_RE.fullmatch(pass_value["execution_id"]):
            return {}, [issue("", "decisions_execution_id_invalid")]
        try:
            generated = datetime.fromisoformat(pass_value["generated_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return {}, [issue("", "decisions_generated_at_invalid")]
        if generated.tzinfo is None or generated.utcoffset() is None:
            return {}, [issue("", "decisions_generated_at_invalid")]
    judgments = pass_value.get("judgments")
    if not isinstance(judgments, list):
        return {}, [issue("", "judgments_missing")]
    result: dict[str, Mapping[str, Any]] = {}
    reasons: list[dict[str, str]] = []
    seen_notice_ids: set[str] = set()
    for item in judgments:
        if not isinstance(item, Mapping):
            reasons.append(issue("", "invalid_judgment_structure"))
            continue
        notice_id = item.get("notice_id")
        if not isinstance(notice_id, str) or not notice_id.strip():
            reasons.append(issue("", "invalid_notice_id"))
            continue
        if notice_id in seen_notice_ids:
            # A duplicate identity makes the whole notice ambiguous.  Do not
            # retain the first object and accidentally count it as valid.
            result.pop(notice_id, None)
            reasons.append(issue(notice_id, "duplicate_notice_id"))
            continue
        seen_notice_ids.add(notice_id)
        if strict:
            try:
                # The worker stores the validated v3 core together with its
                # immutable provenance and deterministic two-axis fields.
                # Validate both portions; never accept a partial synthesis.
                if set(item) != _JUDGMENT_CORE_KEYS | _JUDGMENT_METADATA_KEYS:
                    raise ContractViolation("judgment.v3 exact object keys contract failed")
                core = {key: item[key] for key in _JUDGMENT_CORE_KEYS}
                validate_judgment(core, notice=(notices or {}).get(notice_id, {"notice_id": notice_id}))
                for key in ("model_name", "prompt_version", "policy_version", "company_profile_version", "judged_in_run", "recorded_in_run"):
                    if not isinstance(item[key], str) or not item[key].strip():
                        raise ContractViolation(f"{key} must be a nonblank string")
                for key in ("model_digest", "company_profile_digest"):
                    if not isinstance(item[key], str) or len(item[key]) != 64 or any(char not in "0123456789abcdef" for char in item[key]):
                        raise ContractViolation(f"{key} must be a digest")
                if item["company_profile_version"] != f"company-profile.sha256:{item['company_profile_digest']}":
                    raise ContractViolation("company profile identity does not match digest")
                # 승인된 모델명은 `BIDOPS_VLLM_SCREENING_MODEL`이 정한다.
                # 코드에 박으면 배포가 모델을 바꿀 때 이 게이트가 정상 산출물을
                # 거부하게 된다.
                if item["model_name"] != get_settings().vllm_screening_model:
                    raise ContractViolation("model identity is invalid")
                if item["judgment_mode"] not in {"신규", "재판정", "승계"} or type(item["carried_over"]) is not bool:
                    raise ContractViolation("judgment provenance is invalid")
                if item["rejudge_reason"] is not None and (not isinstance(item["rejudge_reason"], str) or not item["rejudge_reason"].strip()):
                    raise ContractViolation("rejudge reason is invalid")
                if item["judgment_mode"] == "신규" and (item["carried_over"] or item["rejudge_reason"] is not None):
                    raise ContractViolation("new judgment provenance is invalid")
                if item["judgment_mode"] == "재판정" and (item["carried_over"] or item["rejudge_reason"] not in {"정정", "재공고", "본공고 전환", "담당자 요청"}):
                    raise ContractViolation("rejudged judgment provenance is invalid")
                if item["judgment_mode"] == "승계" and (not item["carried_over"] or item["rejudge_reason"] is not None):
                    raise ContractViolation("carried judgment provenance is invalid")
                expected_mix = two_axis_mixing(item["perspectives"], item["grade"])
                if item["two_axis_mixing_flag"] is not expected_mix.flag or item["two_axis_mixing_label"] != expected_mix.label:
                    raise ContractViolation("two-axis mixing metadata is invalid")
            except ContractViolation as exc:
                reason = str(exc).split(":", 1)[0].strip().lower().replace(" ", "_")
                reasons.append(issue(notice_id, f"invalid_judgment:{reason}"))
                continue
        else:
            if item.get("grade") not in VALID_GRADES:
                reasons.append(issue(notice_id, "grade_invalid"))
                continue
            perspectives = item.get("perspectives")
            if not isinstance(perspectives, list) or len(perspectives) != 5:
                reasons.append(issue(notice_id, "perspectives_invalid"))
                continue
            by_name: dict[str, Mapping[str, Any]] = {}
            valid = True
            for perspective in perspectives:
                if not isinstance(perspective, Mapping) or perspective.get("name") not in PERSPECTIVE_NAMES:
                    valid = False
                    break
                name = str(perspective["name"])
                if name in by_name or perspective.get("assessment") not in VALID_ASSESSMENTS:
                    valid = False
                    break
                by_name[name] = perspective
            if not valid or set(by_name) != set(PERSPECTIVE_NAMES):
                reasons.append(issue(notice_id, "perspectives_invalid"))
                continue
        result[notice_id] = item
    return result, reasons


def _metric_status_for_count(denominator: int, *, minimum: int | None = None) -> str:
    if denominator == 0:
        return "계산 불가"
    if minimum is not None and denominator < minimum:
        return "계산 불가(소표본)"
    return "측정 완료"


def _with_threshold(
    metric: dict[str, Any],
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    min_count: int | None = None,
) -> dict[str, Any]:
    denominator = metric["denominator"]
    exact = _exact_percent(metric["numerator"], denominator)
    if denominator == 0 or (min_count is not None and denominator < min_count) or exact is None:
        metric["status"] = "계산 불가" if denominator == 0 else "계산 불가(소표본)"
    elif (minimum is not None and exact < minimum) or (maximum is not None and exact > maximum):
        metric["status"] = "미달"
    else:
        metric["status"] = "통과"
    return metric


def _review_rows(
    reviews: Sequence[Mapping[str, Any]] | None,
    pass_a: Mapping[str, Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[dict[str, str]], int]:
    valid: list[Mapping[str, Any]] = []
    excluded: list[dict[str, str]] = []
    holds = 0
    seen_pairs: set[tuple[str, str]] = set()
    for review in reviews or ():
        if not isinstance(review, Mapping):
            excluded.append({"notice_id": "", "pass": "review", "reason": "review_invalid"})
            continue
        notice_id = review.get("notice_id")
        value = review.get("evidence_judgment")
        if not isinstance(notice_id, str) or notice_id not in pass_a:
            excluded.append({"notice_id": str(notice_id or ""), "pass": "review", "reason": "notice_not_in_pass_a"})
            continue
        pair = (notice_id, str(review.get("reviewer") or ""))
        if pair in seen_pairs:
            excluded.append({"notice_id": notice_id, "pass": "review", "reason": "duplicate_review"})
            continue
        seen_pairs.add(pair)
        if value not in VALID_REVIEW_VALUES:
            excluded.append({"notice_id": notice_id, "pass": "review", "reason": "review_value_invalid"})
            continue
        expected = judgment_digest(pass_a[notice_id])
        if review.get("decision_digest") != expected:
            excluded.append({"notice_id": notice_id, "pass": "review", "reason": "decision_digest_mismatch"})
            continue
        if value == "판단 보류":
            holds += 1
            continue
        valid.append(review)
    return valid, excluded, holds


def _pass_metrics(
    values: Mapping[str, Mapping[str, Any]],
    *,
    sample_ids: Sequence[str],
) -> dict[str, Any]:
    denominator = len(sample_ids)
    valid_ids = [notice_id for notice_id in sample_ids if notice_id in values]
    valid_count = len(valid_ids)
    priority = sum(values[notice_id].get("grade") == "우선 검토" for notice_id in valid_ids)
    discrimination = ratio(priority, valid_count, status=_metric_status_for_count(valid_count, minimum=10))
    return {"valid_count": valid_count, "discrimination": discrimination}


def calculate_metrics(
    pass_a: Mapping[str, Any],
    pass_b: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any] | None = None,
    reviews: Sequence[Mapping[str, Any]] | None = None,
    sample_ids: Sequence[str] | None = None,
    expected_sample_count: int = 40,
    input_a: Mapping[str, Any] | None = None,
    input_b: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate every authoritative metric in spec 5.11.

    ``sample_ids`` is normally the ordered validation-set identity.  Passing
    fewer or duplicate IDs is treated as an input-structure error and is
    represented in ``excluded_notices`` rather than silently changing the
    fixed denominator.
    """

    raw_ids = list(sample_ids or [])
    excluded: list[dict[str, str]] = []
    ids: list[str] = []
    seen_ids: set[str] = set()
    for value in raw_ids:
        if not isinstance(value, str) or not value.strip():
            excluded.append({"notice_id": "", "pass": "A", "reason": "invalid_sample_notice_id"})
            excluded.append({"notice_id": "", "pass": "B", "reason": "invalid_sample_notice_id"})
            continue
        if value in seen_ids:
            excluded.append({"notice_id": value, "pass": "A", "reason": "duplicate_sample_notice_id"})
            excluded.append({"notice_id": value, "pass": "B", "reason": "duplicate_sample_notice_id"})
            continue
        seen_ids.add(value)
        ids.append(value)
    if len(raw_ids) != expected_sample_count or len(ids) != expected_sample_count:
        # Keep the fixed denominator.  The service turns this explicit
        # identity failure into 보류 once execution/review prerequisites are
        # otherwise complete.
        excluded.append({"notice_id": "", "pass": "A", "reason": "sample_correspondence_invalid"})
        excluded.append({"notice_id": "", "pass": "B", "reason": "sample_correspondence_invalid"})

    def input_notices(value: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
        if not isinstance(value, Mapping) or not isinstance(value.get("notices"), list):
            return {}
        return {
            item["notice_id"]: item
            for item in value["notices"]
            if isinstance(item, Mapping) and isinstance(item.get("notice_id"), str) and item["notice_id"].strip()
        }

    a, a_reasons = _judgment_map(pass_a, pass_name="A", notices=input_notices(input_a))
    b, b_reasons = _judgment_map(pass_b, pass_name="B", notices=input_notices(input_b))
    excluded.extend(a_reasons)
    excluded.extend(b_reasons)
    for values, pass_name in ((a, "A"), (b, "B")):
        for notice_id in values:
            if notice_id not in seen_ids:
                excluded.append({"notice_id": notice_id, "pass": pass_name, "reason": "out_of_sample"})
        valid_or_failed = {row["notice_id"] for row in excluded if row["pass"] == pass_name and row["notice_id"]}
        for notice_id in ids:
            if notice_id not in values and notice_id not in valid_or_failed:
                excluded.append({"notice_id": notice_id, "pass": pass_name, "reason": "missing_judgment"})
    if baseline is not None:
        baseline_map, baseline_reasons = _judgment_map(baseline, pass_name="review", strict=False)
        for reason in baseline_reasons:
            excluded.append({**reason, "reason": f"baseline_{reason['reason']}"})
        for notice_id in baseline_map:
            if notice_id not in seen_ids:
                excluded.append({"notice_id": notice_id, "pass": "review", "reason": "baseline_out_of_sample"})
        baseline_failed = {row["notice_id"] for row in excluded if row["pass"] == "review" and row["notice_id"]}
        for notice_id in ids:
            if notice_id not in baseline_map and notice_id not in baseline_failed:
                excluded.append({"notice_id": notice_id, "pass": "review", "reason": "baseline_missing_judgment"})
    else:
        baseline_map = {}

    grade_matches = sum(
        notice_id in a and notice_id in b and a[notice_id].get("grade") == b[notice_id].get("grade")
        for notice_id in ids
    )
    grade = _with_threshold(ratio(grade_matches, expected_sample_count), minimum=Decimal(80))

    perspective: dict[str, dict[str, Any]] = {}
    mismatch_counts: Counter[str] = Counter()
    total_mismatch = 0
    for name in PERSPECTIVE_NAMES:
        matches = 0
        mismatches = 0
        for notice_id in ids:
            left = a.get(notice_id, {}).get("perspectives", []) if notice_id in a else []
            right = b.get(notice_id, {}).get("perspectives", []) if notice_id in b else []
            left_map = {p.get("name"): p for p in left if isinstance(p, Mapping)}
            right_map = {p.get("name"): p for p in right if isinstance(p, Mapping)}
            if left_map.get(name, {}).get("assessment") == right_map.get(name, {}).get("assessment") and name in left_map and name in right_map:
                matches += 1
            else:
                mismatches += 1
        perspective[name] = ratio(matches, expected_sample_count)
        perspective[name]["mismatch_count"] = mismatches
        mismatch_counts[name] = mismatches
        total_mismatch += mismatches
    concentration = ratio(max(mismatch_counts.values(), default=0), total_mismatch)
    if total_mismatch == 0:
        concentration["percent"] = 0.0
        concentration["status"] = "통과"
    else:
        concentration["status"] = "통과" if _exact_percent(concentration["numerator"], concentration["denominator"]) <= Decimal(50) else "미달"

    a_metrics = _pass_metrics(a, sample_ids=ids)
    b_metrics = _pass_metrics(b, sample_ids=ids)
    a_disc = _with_threshold(a_metrics["discrimination"], minimum=Decimal(10), maximum=Decimal(25), min_count=10)
    b_disc = _with_threshold(b_metrics["discrimination"], minimum=Decimal(10), maximum=Decimal(25), min_count=10)

    valid_reviews, review_excluded, hold_count = _review_rows(reviews, a)
    excluded.extend(review_excluded)
    reviewers_by_notice = {str(row.get("notice_id")) for row in valid_reviews}
    agreement_count = sum(row.get("evidence_judgment") == "동의" for row in valid_reviews)
    insufficient_count = sum(row.get("evidence_judgment") == "근거 부족" for row in valid_reviews)
    evidence = {
        "numerator": agreement_count,
        "denominator": len(valid_reviews),
        "percent": _percent(agreement_count, len(valid_reviews)),
        "agreement": _with_threshold(ratio(agreement_count, len(valid_reviews)), minimum=Decimal(70), min_count=10),
        "insufficient": _with_threshold(ratio(insufficient_count, len(valid_reviews)), maximum=Decimal(10), min_count=10),
        "valid_review_count": len(valid_reviews),
        "distinct_notice_review_count": len(reviewers_by_notice),
        "judgment_hold_count": hold_count,
        "status": "통과" if len(valid_reviews) >= 10 and len(reviewers_by_notice) >= 10 and agreement_count * 100 >= len(valid_reviews) * 70 and insufficient_count * 100 <= len(valid_reviews) * 10 else ("계산 불가" if len(valid_reviews) < 10 or len(reviewers_by_notice) < 10 else "미달"),
    }
    if evidence["status"] == "계산 불가" and (len(valid_reviews) < 10 or len(reviewers_by_notice) < 10):
        evidence["status"] = "계산 불가(리뷰 부족)"

    def split_metric(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        split = 0
        valid_count = 0
        for notice_id in ids:
            judgment = values.get(notice_id)
            if judgment is None:
                continue
            valid_count += 1
            assessments = [p.get("assessment") for p in judgment.get("perspectives", []) if isinstance(p, Mapping)]
            if len(assessments) == 5 and len(set(assessments)) >= 2:
                split += 1
        return _with_threshold(ratio(split, valid_count), minimum=Decimal(40), min_count=1)

    def info_metric(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        items = [
            item
            for notice_id in ids
            for item in values.get(notice_id, {}).get("verification_items", [])
            if isinstance(item, Mapping)
        ]
        if not items:
            return {"numerator": 0, "denominator": 0, "percent": None, "status": "해당 없음"}
        return ratio(sum(item.get("requires_attachment") is True for item in items), len(items))

    def mixing_metric(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        eligible = 0
        mixed = 0
        for notice_id in ids:
            judgment = values.get(notice_id)
            if judgment is None:
                continue
            perspective_values = {p.get("name"): p for p in judgment.get("perspectives", []) if isinstance(p, Mapping)}
            qualification = perspective_values.get("사업성·자격 제약", {})
            if qualification.get("assessment") in VALID_ASSESSMENTS and judgment.get("grade") in VALID_GRADES:
                eligible += 1
                mixed += qualification.get("assessment") == "확인 불가" and judgment.get("grade") in MIXING_GRADES
        return ratio(mixed, eligible, status="계산 불가" if eligible == 0 else "측정 완료")

    def reflection_metric(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        total = 0
        reflected = 0
        for notice_id in ids:
            judgment = values.get(notice_id)
            if judgment is None:
                continue
            counters = judgment.get("counterarguments", [])
            resolutions = judgment.get("counterargument_resolutions", [])
            if not isinstance(counters, list):
                continue
            for index, text in enumerate(counters):
                total += 1
                resolution = resolutions[index] if isinstance(resolutions, list) and index < len(resolutions) else None
                if (
                    isinstance(text, str)
                    and text.strip()
                    and isinstance(resolution, Mapping)
                    and resolution.get("counterargument") == text
                    and resolution.get("status") in {"수용", "기각", "추가 확인"}
                    and isinstance(resolution.get("reflection"), str)
                    and resolution["reflection"].strip()
                ):
                    reflected += 1
        return ratio(reflected, total, status="계산 불가" if total == 0 else "측정 완료")

    if baseline_map:
        aligned = [notice_id for notice_id in ids if notice_id in a and notice_id in baseline_map]
        claude_grade = ratio(sum(a[i].get("grade") == baseline_map[i].get("grade") for i in aligned), len(aligned))
        claude_perspective = {}
        for name in PERSPECTIVE_NAMES:
            matches = 0
            for notice_id in aligned:
                am = {p.get("name"): p for p in a[notice_id].get("perspectives", []) if isinstance(p, Mapping)}
                bm = {p.get("name"): p for p in baseline_map[notice_id].get("perspectives", []) if isinstance(p, Mapping)}
                matches += am.get(name, {}).get("assessment") == bm.get(name, {}).get("assessment")
            claude_perspective[name] = ratio(matches, len(aligned))
    else:
        claude_grade = ratio(0, 0, status="계산 불가")
        claude_perspective = {name: ratio(0, 0, status="계산 불가") for name in PERSPECTIVE_NAMES}

    return {
        "sample_count": expected_sample_count,
        "paired_valid_count": sum(notice_id in a and notice_id in b for notice_id in ids),
        "excluded_notices": excluded,
        "grade_reproducibility": grade,
        "perspective_reproducibility": perspective,
        "perspective_mismatch_concentration": concentration,
        "discrimination": {"pass_a": a_disc, "pass_b": b_disc},
        "evidence_validity": evidence,
        "information_sufficiency": {"pass_a": info_metric(a), "pass_b": info_metric(b)},
        "perspective_split": {"pass_a": split_metric(a), "pass_b": split_metric(b)},
        "two_axis_mixing": {"pass_a": mixing_metric(a), "pass_b": mixing_metric(b)},
        "counterargument_reflection": {"pass_a": reflection_metric(a), "pass_b": reflection_metric(b)},
        "claude_alignment": {
            "numerator": claude_grade["numerator"],
            "denominator": claude_grade["denominator"],
            "percent": claude_grade["percent"],
            "status": "측정 완료" if claude_grade["denominator"] else "계산 불가",
            "grade": claude_grade,
            "perspectives": claude_perspective,
        },
    }


def required_metrics_pass(metrics: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Apply the exact required-metric precedence after calculation."""

    reasons: list[str] = []
    required = [metrics.get("grade_reproducibility"), metrics.get("perspective_mismatch_concentration")]
    required.extend((metrics.get("discrimination") or {}).get(key) for key in ("pass_a", "pass_b"))
    required.extend((metrics.get("perspective_split") or {}).get(key) for key in ("pass_a", "pass_b"))
    evidence = metrics.get("evidence_validity") or {}
    required.extend((evidence.get(key) for key in ("agreement", "insufficient")))
    for metric in required:
        if not isinstance(metric, Mapping):
            reasons.append("required_metric_missing")
            continue
        status = metric.get("status")
        if status in {"계산 불가", "계산 불가(소표본)", "계산 불가(리뷰 부족)"}:
            reasons.append("required_metric_unmeasurable")
        elif status == "미달":
            reasons.append("required_metric_below_threshold")
    return not reasons, reasons


# Naming aliases used by callers that treat the module as a calculator.
compute_metrics = calculate_metrics
calculate_quality_metrics = calculate_metrics
evaluate_required_metrics = required_metrics_pass


__all__ = [
    "QualityMetricError",
    "calculate_metrics",
    "calculate_quality_metrics",
    "compute_metrics",
    "evaluate_required_metrics",
    "frozen_input_digest",
    "judgment_digest",
    "ratio",
    "required_metrics_pass",
]
