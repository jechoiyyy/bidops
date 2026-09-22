"""Lossless editorial projection. All analysis comes from validated claims."""
from collections.abc import Mapping, Sequence
from typing import Any

SECTIONS = {
    "assessment": "먼저 알아야 할 판단", "scope": "사업 목적과 과업",
    "company_fit": "회사 근거와 부족한 자료", "delivery": "수행에 영향을 주는 조건",
    "evaluation": "평가와 제안 준비", "contract_economics": "계약과 경제성",
    "actions": "확인할 일", "decision_conditions": "판단 갱신 조건",
}
CLAIM_METADATA = ("report_section", "narrative_role", "topic_key", "source_unit_ids", "requirement_ids", "related_claim_ids", "is_key_point")


def render(identity: Mapping[str, Any], claims: list[dict[str, Any]], stages: Sequence[Mapping[str, Any]], *, unknowns: list[str], recommendation: str, status: str, limitations: Sequence[str]) -> dict[str, Any]:
    sections = []
    for key, title in SECTIONS.items():
        selected = [row for row in claims if row["report_section"] == key]
        sections.append({"section_key": key, "title": title, "status": "available" if selected else "not_analyzed", "blocks": [
            {"block_id": f"claim-{row['claim_id']}", "type": "paragraph", "title": row["category"], "body": row["body"],
             "claim_ids": [row["claim_id"]], "rows": [], **{field: row[field] for field in ("narrative_role", "topic_key", "is_key_point")}}
            for row in selected
        ]})
    coverage: dict[str, dict[str, Any]] = {}
    for stage in stages:
        for row in stage.get("coverage", []):
            current = coverage.setdefault(row["source_unit_id"], {**row, "claim_ids": [], "reason": None})
            current["claim_ids"].extend(row["claim_ids"])
            if row["status"] == "needs_review":
                current.update(status="needs_review", reason=row["reason"])
    limits = list(dict.fromkeys([*limitations, "회사 대조는 원문과 관련된 승인 프로필 항목을 선택해 수행했습니다. 선택되지 않은 자료나 없는 근거는 역량 미달을 뜻하지 않습니다."]))
    if any(row["status"] == "needs_review" for row in coverage.values()):
        limits.append("일부 원문 구간은 충분히 분석되지 않아 담당자의 원문 확인이 필요합니다.")
    return {**identity, "schema": "bidops.deep-review-report.v2", "generator_version": "narrative-v2",
            "sections": sections, "claims": claims, "unknowns": unknowns, "system_recommendation": recommendation,
            "validation_summary": {"status": status, "failed": int(status == "failed"), "warnings": 0, "passed": 0},
            "coverage": list(coverage.values()), "analysis_limitations": limits}
