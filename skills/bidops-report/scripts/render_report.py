#!/usr/bin/env python3
"""Render BidOps screening JSON as static Korean HTML reports.

The renderer only presents what the screening JSON already states. It never
derives a grade, a reason, or a category from the notice text, because a value
invented here would be indistinguishable from an agent's judgment in the report.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


CSS = """
:root{--ink:#172033;--muted:#667085;--line:#e5e9f0;--paper:#fff;--bg:#f4f6f9;
--primary:#175cd3;--warn:#b54708;--danger:#b42318;--ok:#027a48}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:Inter,Pretendard,"Noto Sans KR",system-ui,sans-serif;line-height:1.55}
main{max-width:1120px;margin:0 auto;padding:36px 24px 72px}.top{display:flex;gap:20px;
justify-content:space-between;align-items:flex-start;margin-bottom:24px}.eyebrow{font-size:12px;
font-weight:800;letter-spacing:.08em;color:var(--primary);text-transform:uppercase}h1{margin:6px 0 4px;
font-size:30px}h2{font-size:20px;margin:34px 0 14px}h3{font-size:16px;margin:0 0 7px}
.muted{color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.stat,.panel,.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;
box-shadow:0 2px 8px rgba(16,24,40,.04)}.stat{padding:16px}.stat b{display:block;font-size:27px}
.panel{padding:20px}.queue{display:grid;gap:12px}.card{padding:18px}.row{display:flex;gap:12px;
justify-content:space-between;align-items:flex-start}.chips{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0}
.chip{font-size:12px;font-weight:700;border-radius:999px;padding:4px 9px;background:#eef4ff;color:#3538cd}
.chip.verify{background:#fff4e5;color:var(--warn)}.chip.pre{background:#ecfdf3;color:var(--ok)}
.chip.audit{background:#f2f4f7;color:#475467}.chip.miss{background:#fee4e2;color:var(--danger)}
.fold{margin-top:18px;border:1px solid var(--line);
border-radius:14px;background:var(--paper)}.fold summary{cursor:pointer;padding:17px 20px;font-weight:800;
list-style:none}.fold summary::-webkit-details-marker{display:none}.fold summary:after{content:'＋';float:right;
color:var(--muted)}.fold[open] summary:after{content:'－'}.fold-body{padding:0 18px 18px}
.reason-stats{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 18px}.reason{padding:7px 10px;
border-radius:9px;background:#f2f4f7;color:#475467;font-size:13px;font-weight:700}
.grade{font-weight:800;color:var(--primary)}.grade.제외{color:var(--danger)}a{color:var(--primary);
text-decoration:none}a:hover{text-decoration:underline}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.facts{display:grid;grid-template-columns:150px 1fr;margin:0}.facts dt,.facts dd{padding:9px 0;
border-bottom:1px solid var(--line)}.facts dt{color:var(--muted)}.facts dd{margin:0;font-weight:600}
.item{padding:13px 0;border-bottom:1px solid var(--line)}.item:last-child{border-bottom:0}
.evidence{margin:7px 0 0;padding-left:20px;color:var(--muted)}.action{border-left:4px solid var(--primary)}
.back{display:inline-block;margin-bottom:18px}.signal{font-size:13px;color:var(--muted)}
@media(max-width:760px){.stats,.grid{grid-template-columns:1fr 1fr}
.top{display:block}.facts{grid-template-columns:1fr}.facts dd{padding-top:0}.row{display:block}}
"""

FIELD_KIND_LABELS = {
    "title": "공고명",
    "classification": "분류명",
    "other": "기타 필드",
}

QUEUE_ORDER = {"우선 검토": 0, "검토 권장": 1, "관찰 대상": 2}


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def safe_name(notice_id: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", notice_id).strip("-")
    return value or "notice"


def safe_url(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text.lower().startswith(("http://", "https://")) else None


def detail_file_names(results: list[dict[str, Any]]) -> dict[str, str]:
    """Give every notice its own file even when identifiers normalize alike."""
    names: dict[str, str] = {}
    used: set[str] = set()
    for index, result in enumerate(results, start=1):
        identifier = str(result.get("notice", {}).get("notice_id", f"notice-{index}"))
        base = safe_name(identifier)
        candidate = f"{base}.html"
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}.html"
            suffix += 1
        used.add(candidate)
        names[identifier] = candidate
    return names


def remove_stale_details(detail_dir: Path, written: set[str]) -> list[str]:
    """Delete detail pages from earlier runs so the folder matches the input.

    Only `.html` files inside the renderer's own output folder are removed. A
    page left behind would keep presenting a judgment that no longer exists.
    """
    removed = []
    for path in sorted(detail_dir.glob("*.html")):
        if path.name not in written:
            path.unlink()
            removed.append(path.name)
    return removed


def page(title: str, content: str) -> str:
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>{content}</main></body></html>"
    )


def is_audit(result: dict[str, Any]) -> bool:
    return result.get("notice", {}).get("sample_role") == "audit"


def grade_of(result: dict[str, Any]) -> str:
    return result.get("judgment", {}).get("grade", "미정")


def exclusion_category(result: dict[str, Any]) -> str:
    """Report the recorded reason, or say plainly that none was recorded."""
    category = result.get("judgment", {}).get("exclusion_category")
    return str(category) if category else "사유 미기재"


def partition_results(
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    queue = [
        item for item in results if not is_audit(item) and grade_of(item) != "제외"
    ]
    excluded = [
        item for item in results if not is_audit(item) and grade_of(item) == "제외"
    ]
    audits = [item for item in results if is_audit(item)]
    queue.sort(
        key=lambda item: (
            QUEUE_ORDER.get(grade_of(item), 9),
            item.get("notice", {}).get("deadline_at") or "9999",
        )
    )
    return queue, excluded, audits


def audit_miss_count(results: list[dict[str, Any]]) -> int:
    """Audit records that screening did not exclude are first-filter misses."""
    return sum(1 for item in results if is_audit(item) and grade_of(item) != "제외")


def weekly_statistics(results: list[dict[str, Any]]) -> list[tuple[str, int]]:
    queue, excluded, _ = partition_results(results)
    grades = Counter(grade_of(item) for item in queue)
    return [
        ("검토 대기열", len(queue)),
        ("우선 검토", grades["우선 검토"]),
        ("검토 권장", grades["검토 권장"]),
        ("제외", len(excluded)),
        ("감사 표본 회수", audit_miss_count(results)),
    ]


def chips_for(result: dict[str, Any]) -> str:
    notice = result.get("notice", {})
    judgment = result.get("judgment", {})
    chips = [f"<span class='chip'>{e(judgment.get('readiness', '미정'))}</span>"]
    if notice.get("source_type") == "pre_spec":
        chips.append("<span class='chip pre'>사전규격</span>")
    if (notice.get("lifecycle") or {}).get("pre_spec_no"):
        chips.append("<span class='chip pre'>사전규격 연계</span>")
    if (notice.get("lifecycle") or {}).get("re_notice") == "Y":
        chips.append("<span class='chip'>재공고</span>")
    if (notice.get("lifecycle") or {}).get("change_reason"):
        chips.append("<span class='chip'>정정 이력</span>")
    if is_audit(result):
        label = f"필터 감사 · {notice.get('sample_stratum', '무작위')}"
        chips.append(f"<span class='chip audit'>{e(label)}</span>")
        if grade_of(result) != "제외":
            chips.append("<span class='chip miss'>1차 필터 누락</span>")
    verifications = judgment.get("verification_items", []) or []
    if verifications:
        blocking = sum(bool(item.get("blocking")) for item in verifications)
        label = f"확인 {len(verifications)}건" + (f" · 필수 {blocking}" if blocking else "")
        chips.append(f"<span class='chip verify'>{e(label)}</span>")
    primary = judgment.get("primary_focus")
    if primary and primary != "해당 없음":
        chips.append(f"<span class='chip'>{e(primary)}</span>")
    return "".join(chips)


def render_card(result: dict[str, Any], detail_names: dict[str, str]) -> str:
    notice = result.get("notice", {})
    judgment = result.get("judgment", {})
    identifier = str(notice.get("notice_id", ""))
    link = detail_names.get(identifier, "")
    return (
        "<article class='card'>"
        "<div class='row'><div>"
        f"<div class='grade {e(judgment.get('grade'))}'>{e(judgment.get('grade', '미정'))}</div>"
        f"<h3><a href='details/{e(link)}'>{e(notice.get('title', '제목 없음'))}</a></h3>"
        f"<div class='muted'>{e(notice.get('agency') or '기관 미상')}</div></div>"
        f"<div class='muted'>마감 {e(notice.get('deadline_at') or '확인 필요')}</div></div>"
        f"<div class='chips'>{chips_for(result)}</div>"
        f"<div>{e(judgment.get('summary', '요약 없음'))}</div>"
        f"<div class='muted'>다음 조치 · {e(judgment.get('next_action', '확인 필요'))}</div>"
        "</article>"
    )


def render_weekly(data: dict[str, Any], detail_names: dict[str, str]) -> str:
    results = data.get("results", [])
    queue, excluded, audits = partition_results(results)
    window = data.get("source_window", {})
    stat_html = "".join(
        f"<div class='stat'><span class='muted'>{e(label)}</span><b>{value}</b></div>"
        for label, value in weekly_statistics(results)
    )
    reason_counts = Counter(exclusion_category(item) for item in excluded)
    reason_html = "".join(
        f"<span class='reason'>{e(reason)} {count}건</span>"
        for reason, count in reason_counts.most_common()
    )
    misses = audit_miss_count(results)
    audit_note = (
        f"감사 표본 {len(audits)}건 가운데 {misses}건이 1차 필터 누락으로 확인됐습니다."
        if misses
        else f"감사 표본 {len(audits)}건은 모두 제외 판정이었습니다."
    )
    content = (
        "<header class='top'><div><div class='eyebrow'>BidOps weekly monitoring</div>"
        "<h1>주간 사업기회 모니터링</h1>"
        f"<div class='muted'>{e(window.get('from'))} ~ {e(window.get('to'))}</div></div>"
        "<div class='muted'>등급과 참여 준비 상태를 분리해 표시합니다.</div></header>"
        f"<section class='stats'>{stat_html}</section><h2>검토 대기열</h2>"
        f"<section class='queue'>"
        f"{''.join(render_card(item, detail_names) for item in queue) or '<div class=panel>검토 결과가 없습니다.</div>'}"
        "</section>"
        "<h2>제외 및 필터 감사</h2>"
        f"<div class='reason-stats'>{reason_html or '<span class=reason>제외 없음</span>'}</div>"
        f"<div class='muted'>{e(audit_note)}</div>"
        f"<details class='fold'><summary>의미 판정에서 제외 {len(excluded)}건</summary>"
        f"<div class='fold-body queue'>"
        f"{''.join(render_card(item, detail_names) for item in excluded) or '<div class=muted>해당 없음</div>'}"
        "</div></details>"
        f"<details class='fold'><summary>필터 감사 표본 {len(audits)}건 · 누락 {misses}건</summary>"
        f"<div class='fold-body queue'>"
        f"{''.join(render_card(item, detail_names) for item in audits) or '<div class=muted>해당 없음</div>'}"
        "</div></details>"
    )
    return page("BidOps 주간 모니터링", content)


def render_list(items: list[Any], empty: str, renderer) -> str:
    if not items:
        return f"<div class='muted'>{e(empty)}</div>"
    return "".join(renderer(item) for item in items)


def region_text(notice: dict[str, Any]) -> str:
    region = notice.get("region_limit") or {}
    basis = region.get("basis")
    regions = region.get("joint_contract_regions") or []
    if not basis and not regions:
        return "API 미표기"
    parts = [basis] if basis else []
    if regions:
        rate = region.get("joint_contract_rate")
        joined = ", ".join(regions)
        parts.append(f"지역의무공동도급 {joined}" + (f" {rate}%" if rate else ""))
    return " · ".join(parts)


def classification_text(notice: dict[str, Any]) -> str:
    values = [
        (notice.get("procurement_class") or {}).get(key)
        for key in ("large", "middle", "detail")
    ]
    joined = " > ".join(value for value in values if value)
    return joined or "확인 필요"


def render_signals(notice: dict[str, Any]) -> str:
    signals = notice.get("focus_matches") or []
    if not signals:
        return "<div class='muted'>개념 일치 신호 없음</div>"
    return "".join(
        "<div class='item'>"
        f"<b>{e(signal.get('label'))}</b> <span class='muted'>{e(signal.get('axis'))}</span>"
        f"<div class='signal'>{e(FIELD_KIND_LABELS.get(signal.get('field_kind'), '기타 필드'))}"
        f" · {e(signal.get('matched_field'))} · 일치 문자열 {e(signal.get('matched_text'))}</div>"
        "</div>"
        for signal in signals
    )


def render_detail(result: dict[str, Any]) -> str:
    notice = result.get("notice", {})
    judgment = result.get("judgment", {})
    lifecycle = notice.get("lifecycle") or {}
    facts = [
        ("기관", notice.get("agency")),
        ("구분", notice.get("source_type")),
        ("게시", notice.get("published_at")),
        ("마감", notice.get("deadline_at")),
        ("예산", notice.get("budget")),
        ("방식", notice.get("method")),
        ("조달 분류", classification_text(notice)),
        ("지역 제한", region_text(notice)),
        ("사전규격번호", lifecycle.get("pre_spec_no")),
        ("정정 사유", lifecycle.get("change_reason")),
    ]
    fact_html = "".join(
        f"<dt>{e(key)}</dt><dd>{e(value or '확인 필요')}</dd>" for key, value in facts
    )

    def perspective(item: dict[str, Any]) -> str:
        evidence = render_list(
            item.get("evidence", []) or [], "근거 없음",
            lambda ev: (
                f"<li>{e(ev.get('fact'))} "
                f"<small>({e(ev.get('source'))}, {e(ev.get('status'))})</small></li>"
            ),
        )
        return (
            "<div class='item'><div class='row'>"
            f"<h3>{e(item.get('name'))}</h3><b>{e(item.get('assessment'))}</b></div>"
            f"<div>{e(item.get('reason'))}</div><ul class='evidence'>{evidence}</ul></div>"
        )

    def performance(item: dict[str, Any]) -> str:
        return (
            f"<div class='item'><h3>{e(item.get('name'))}</h3>"
            f"<div>{e(item.get('match_reason'))}</div>"
            f"<div class='muted'>차이 · {e(item.get('mismatch_or_limit', '확인 필요'))}</div>"
            f"<div class='muted'>출처 · {e(item.get('source'))} "
            f"(입찰 실적 인정 {e(item.get('status', 'unknown'))})</div></div>"
        )

    def verification(item: dict[str, Any]) -> str:
        label = "참여 필수" if item.get("blocking") else "보완 확인"
        return (
            f"<div class='item'><span class='chip verify'>{label}</span> "
            f"<b>{e(item.get('item'))}</b><div>{e(item.get('why'))}</div>"
            f"<div class='muted'>상태 · {e(item.get('status', '미확인'))}</div></div>"
        )

    url = safe_url(notice.get("url"))
    source_link = f"<a href='{e(url)}'>원문 링크</a>" if url else "원문 링크 없음"
    category = judgment.get("exclusion_category")
    category_html = (
        f"<div class='muted'>제외 사유 구분 · {e(category)}</div>" if category else ""
    )
    content = (
        "<a class='back' href='../weekly-monitoring.html'>← 주간 보고서</a>"
        "<header class='top'><div><div class='eyebrow'>BidOps opportunity detail</div>"
        f"<h1>{e(notice.get('title', '제목 없음'))}</h1>"
        f"<div class='muted'>{e(notice.get('notice_id'))} · {source_link}</div></div>"
        f"<div><div class='grade {e(judgment.get('grade'))}'>{e(judgment.get('grade', '미정'))}</div>"
        f"<div class='chips'>{chips_for(result)}</div></div></header>"
        "<section class='grid'><div class='panel'><h2>종합 권고</h2>"
        f"<p>{e(judgment.get('summary', '요약 없음'))}</p>{category_html}"
        f"<div class='panel action'><b>다음 조치</b><div>{e(judgment.get('next_action', '확인 필요'))}</div></div></div>"
        f"<div class='panel'><h2>공고 정보</h2><dl class='facts'>{fact_html}</dl></div></section>"
        "<h2>관점별 판단</h2><section class='panel'>"
        f"{render_list(judgment.get('perspectives', []) or [], '관점별 결과 없음', perspective)}</section>"
        "<section class='grid'><div><h2>연결 수행실적</h2><div class='panel'>"
        f"{render_list(judgment.get('matched_performances', []) or [], '연결 실적 없음', performance)}</div></div>"
        "<div><h2>확인 항목</h2><div class='panel'>"
        f"{render_list(judgment.get('verification_items', []) or [], '추가 확인 항목 없음', verification)}</div></div></section>"
        "<h2>반론 검토</h2><section class='panel'>"
        f"{render_list(judgment.get('counterarguments', []) or [], '반론 없음', lambda x: '<div class=item>' + e(x if isinstance(x, str) else x.get('reason')) + '</div>')}</section>"
        "<h2>1차 검색 신호</h2><section class='panel'>"
        f"{render_signals(notice)}</section>"
    )
    return page(str(notice.get("title", "공고 분석")), content)


def yaml_scalar(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_feedback(results: list[dict[str, Any]]) -> str:
    lines = ["schema_version: bidops.feedback.v2", "reviews:"]
    for result in results:
        notice_id = result.get("notice", {}).get("notice_id", "")
        lines.extend([
            f"  - notice_id: {yaml_scalar(notice_id)}",
            "    disposition: null  # 심층 검토 진행 | 관찰 | 제외",
            "    system_judgment_review: null  # 동의 | 등급 수정 | 근거 부족",
            "    corrected_grade: null",
            "    corrected_readiness: null",
            "    weakest_perspective: null  # 근거가 가장 부족했던 관점 이름",
            '    reason: ""',
            "    verification_answers: []",
        ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if data.get("schema_version") != "bidops.screening.v2":
        raise SystemExit(
            f"지원하지 않는 판정 결과 스키마입니다: {data.get('schema_version')}"
        )
    results = data.get("results", [])
    if not isinstance(results, list):
        raise SystemExit("results는 배열이어야 합니다.")

    output_dir = args.output_dir.resolve()
    detail_dir = output_dir / "details"
    detail_dir.mkdir(parents=True, exist_ok=True)
    names = detail_file_names(results)
    for result in results:
        identifier = str(result.get("notice", {}).get("notice_id", ""))
        (detail_dir / names[identifier]).write_text(
            render_detail(result), encoding="utf-8"
        )

    removed = remove_stale_details(detail_dir, set(names.values()))

    (output_dir / "weekly-monitoring.html").write_text(
        render_weekly(data, names), encoding="utf-8"
    )
    (output_dir / "review-feedback.yaml").write_text(
        render_feedback(results), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "details": len(results),
                "removed_stale_details": len(removed),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
