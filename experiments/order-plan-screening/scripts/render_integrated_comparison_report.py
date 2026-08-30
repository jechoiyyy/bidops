#!/usr/bin/env python3
"""Render a self-contained Sol/Luna-reference and local-method comparison report."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any


METHODS = (
    ("qwen", "Qwen"),
    ("tfidf", "TF-IDF"),
    ("bge_m3_dense", "Dense (BGE-M3)"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-result", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--reference-report", type=Path, required=True)
    parser.add_argument("--comparison-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object가 아닙니다: {path.name}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def indicator(value: str) -> str:
    css = {
        "포함": "hit",
        "미포함": "miss",
        "출력 실패": "failed",
    }[value]
    return f'<span class="pill {css}">{escape(value)}</span>'


def validate_inputs(
    reference: dict[str, Any],
    population: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> None:
    population_ids = [row["plan_id"] for row in population["items"]]
    if len(population_ids) != len(set(population_ids)):
        raise ValueError("population plan_id가 중복됐습니다")
    if reference.get("source_run_id") != population.get("run_id"):
        raise ValueError("reference source run과 population run이 다릅니다")
    expected_hash = population.get("population_sha256")
    if reference.get("input_sha256") != expected_hash:
        raise ValueError("reference와 population hash가 다릅니다")
    reference_ids = [row["plan_id"] for row in reference["items"]]
    if reference_ids != population_ids:
        raise ValueError("reference와 population의 plan_id 순서가 다릅니다")
    for method, _label in METHODS:
        result = results[method]
        if result.get("run_id") != population.get("run_id"):
            raise ValueError(f"{method} run과 population run이 다릅니다")
        if result.get("input_sha256") != expected_hash:
            raise ValueError(f"{method}와 population hash가 다릅니다")
        if [row["plan_id"] for row in result["items"]] != population_ids:
            raise ValueError(f"{method}와 population의 plan_id 순서가 다릅니다")
        selected = [row for row in result["items"] if row.get("selected") is True]
        if len(selected) != 50:
            raise ValueError(f"{method} selected가 50건이 아닙니다")


def render(
    reference: dict[str, Any],
    population: dict[str, Any],
    results: dict[str, dict[str, Any]],
    reference_report: str,
    comparison_report: str,
    reference_report_sha: str,
    comparison_report_sha: str,
) -> str:
    successful_reference = [row for row in reference["items"] if row["status"] == "success"]
    if len(successful_reference) < 50:
        raise ValueError("reference 성공 결과가 Top 50을 만들기에 부족합니다")
    ranked_reference = sorted(
        successful_reference,
        key=lambda row: (-float(row["score"]), row["plan_id"]),
    )
    reference_top = ranked_reference[:50]
    reference_ids = {row["plan_id"] for row in reference_top}
    cutoff = float(reference_top[-1]["score"])
    cutoff_ties = [row for row in ranked_reference if float(row["score"]) == cutoff]
    selected_ids = {
        method: {row["plan_id"] for row in results[method]["items"] if row.get("selected") is True}
        for method, _label in METHODS
    }
    overlap_counts = {
        method: len(reference_ids & selected_ids[method])
        for method, _label in METHODS
    }
    result_by_id = {
        method: {row["plan_id"]: row for row in results[method]["items"]}
        for method, _label in METHODS
    }
    title_by_id = {row["plan_id"]: row["title"] for row in population["items"]}
    reference_model_counts: dict[str, int] = {}
    for row in reference_top:
        model = row["model"]
        reference_model_counts[model] = reference_model_counts.get(model, 0) + 1

    method_rows = []
    for method, label in METHODS:
        overlap = reference_ids & selected_ids[method]
        missing = reference_ids - selected_ids[method]
        failed = sum(result_by_id[method][plan_id]["status"] == "failed" for plan_id in reference_ids)
        ranked_out = len(missing) - failed
        method_rows.append(
            f"<tr><th>{escape(label)}</th><td><strong>{len(overlap)} / 50</strong></td>"
            f"<td>{len(overlap) * 2}%</td><td>{len(missing)}</td><td>{failed}</td><td>{ranked_out}</td></tr>"
        )

    detail_rows = []
    for rank, row in enumerate(reference_top, start=1):
        plan_id = row["plan_id"]
        states: dict[str, str] = {}
        for method, _label in METHODS:
            local = result_by_id[method][plan_id]
            if local["status"] == "failed":
                states[method] = "출력 실패"
            elif plan_id in selected_ids[method]:
                states[method] = "포함"
            else:
                states[method] = "미포함"
        detail_rows.append(
            f"<tr><td>{rank}</td><td><code>{escape(plan_id)}</code></td>"
            f"<td class=\"title\">{escape(title_by_id[plan_id])}</td>"
            f"<td>{escape(row['model'].replace('gpt-5.6-', '').title())}</td>"
            f"<td>{float(row['score']):.2f}</td>"
            f"<td>{indicator(states['tfidf'])}</td>"
            f"<td>{indicator(states['bge_m3_dense'])}</td>"
            f"<td>{indicator(states['qwen'])}</td></tr>"
        )

    tie_rows = []
    chosen_id = reference_top[-1]["plan_id"]
    for row in cutoff_ties:
        tie_rows.append(
            f"<tr><td><code>{escape(row['plan_id'])}</code></td>"
            f"<td class=\"title\">{escape(title_by_id[row['plan_id']])}</td>"
            f"<td>{'Top 50 포함' if row['plan_id'] == chosen_id else '경계 동점 제외'}</td></tr>"
        )

    model_summary = " · ".join(
        f"{escape(model.replace('gpt-5.6-', '').title())} {count}건"
        for model, count in sorted(reference_model_counts.items())
    )
    source_created = (
        f"기준 결과 {escape(reference.get('created_at', '값 없음'))} · "
        f"비교 실행 {escape(results['qwen'].get('created_at', '값 없음'))}"
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; frame-src 'self';">
<title>BidOps 발주계획 통합 비교 보고서</title>
<style>
:root{{--ink:#172033;--muted:#667085;--line:#d8dee9;--paper:#fff;--panel:#f7f9fc;--accent:#2457d6;--ok:#087443;--bad:#b42318;--warn:#9a6700}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#e9eef5;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;line-height:1.58}}
main{{width:min(1500px,calc(100% - 32px));margin:24px auto 56px;background:var(--paper);padding:clamp(22px,4vw,52px);border:1px solid var(--line);border-radius:18px;box-shadow:0 14px 36px #14224217}}
h1,h2,h3{{line-height:1.25}}h1{{margin:0 0 8px;font-size:clamp(28px,4vw,44px)}}h2{{margin-top:48px;border-bottom:2px solid #11264d;padding-bottom:10px}}h3{{margin:22px 0 10px}}.subtitle,.note{{color:var(--muted)}}
.warning{{margin:20px 0;padding:16px 18px;border-left:5px solid #e0a100;background:#fff8e6}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:20px 0}}.card{{border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--panel)}}.card strong{{display:block;font-size:27px}}.card span{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{border:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}}th{{background:#edf2f8}}.table-scroll{{overflow:auto}}.title{{min-width:310px;white-space:normal}}code{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;word-break:break-all}}
.pill{{display:inline-block;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:700;white-space:nowrap}}.hit{{color:var(--ok);background:#e7f6ee}}.miss{{color:#475467;background:#eef2f6}}.failed{{color:var(--bad);background:#feeceb}}
details{{margin:18px 0;border:1px solid var(--line);border-radius:12px;padding:14px;background:var(--panel)}}summary{{cursor:pointer;font-weight:700;font-size:17px}}iframe{{display:block;width:100%;height:1050px;margin-top:14px;border:1px solid var(--line);border-radius:8px;background:white}}.hash{{font-size:11px;word-break:break-all}}
nav{{margin:22px 0;padding:14px 18px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}}nav a{{color:var(--accent);margin-right:18px;white-space:nowrap}}footer{{margin-top:44px;color:var(--muted);font-size:13px}}
@media(max-width:760px){{main{{width:100%;margin:0;border-radius:0}}iframe{{height:850px}}}}@media print{{body{{background:white}}main{{width:100%;margin:0;border:0;box-shadow:none}}iframe{{height:1100px}}}}
</style></head><body><main>
<header><h1>발주계획 선별 통합 비교 보고서</h1>
<p class="subtitle">Sol·Luna 혼합 silver reference와 TF-IDF·Dense·Qwen 실행 비교 · 동결 모집단 {len(population['items']):,}건</p>
<p class="note">{source_created}</p></header>
<div class="warning"><strong>해석 경계:</strong> Sol·Luna 판정은 사람이 확정한 정답이 아니며 서로 다른 모집단 구간을 처리했다. 아래 Top 50 평가는 사용자가 요청한 예시 가정으로, 모델 선택이나 운영 활성화의 품질 게이트를 대신하지 않는다.</div>
<nav><a href="#overlap">Top 50 교집합</a><a href="#items">기준 50건 상세</a><a href="#sources">통합 원본 보고서</a></nav>

<section id="overlap"><h2>1. Sol·Luna Top 50 가정 비교</h2>
<div class="cards"><div class="card"><strong>{overlap_counts['qwen']} / 50</strong><span>Qwen 포함 · {overlap_counts['qwen'] * 2}%</span></div><div class="card"><strong>{overlap_counts['tfidf']} / 50</strong><span>TF-IDF 포함 · {overlap_counts['tfidf'] * 2}%</span></div><div class="card"><strong>{overlap_counts['bge_m3_dense']} / 50</strong><span>Dense 포함 · {overlap_counts['bge_m3_dense'] * 2}%</span></div><div class="card"><strong>{sum(result_by_id['qwen'][plan_id]['status'] == 'failed' for plan_id in reference_ids)}건</strong><span>기준 Top 50 중 Qwen 출력 실패</span></div></div>
<div class="table-scroll"><table><thead><tr><th>방법</th><th>기준 Top 50 포함</th><th>포함률</th><th>미포함</th><th>출력 실패</th><th>유효 출력이지만 순위 밖</th></tr></thead><tbody>{''.join(method_rows)}</tbody></table></div>
<p><strong>포함 건수 기준:</strong> Qwen {overlap_counts['qwen']}건 &gt; TF-IDF {overlap_counts['tfidf']}건 &gt; Dense {overlap_counts['bge_m3_dense']}건.</p>
<p class="note">각 방법 자체의 Top 50과 임시 기준 Top 50의 plan_id 교집합만 계산했다. 점수 크기와 순위 차이는 비교하지 않았다. Qwen 32건은 250건의 truncated_output 영향을 포함한 관측값이다.</p>

<h3>임시 기준 Top 50 생성 규칙</h3>
<ul><li>Sol 200건과 Luna 797건의 성공 결과를 합친 뒤 score 내림차순, plan_id 오름차순으로 정렬했다.</li><li>50위 경계 점수는 {cutoff:.2f}이고 같은 점수는 {len(cutoff_ties)}건이다. 이 중 plan_id가 가장 앞선 1건을 포함했다.</li><li>기준 Top 50의 모델 구성은 {model_summary}이다.</li><li>원본 혼합 결과의 selection 상태는 <code>{escape(reference['selection']['status'])}</code>이다. 즉 이 Top 50은 원본 결과가 공식 산출한 선택 집합이 아니라 본 보고서가 분석용으로 만든 파생 집합이다.</li></ul>
<details><summary>50위 경계 동점 {len(cutoff_ties)}건 보기</summary><div class="table-scroll"><table><thead><tr><th>plan_id</th><th>사업명</th><th>처리</th></tr></thead><tbody>{''.join(tie_rows)}</tbody></table></div></details>
</section>

<section id="items"><h2>2. 임시 기준 Top 50 상세</h2>
<p class="note">포함은 해당 방법의 자체 Top 50에 같은 plan_id가 있다는 뜻이다. 출력 실패는 Qwen이 그 항목을 포함한 25건 배치 전체를 완료하지 못했다는 뜻이다.</p>
<div class="table-scroll"><table><thead><tr><th>기준 순위</th><th>plan_id</th><th>사업명</th><th>기준 모델</th><th>기준 점수</th><th>TF-IDF</th><th>Dense</th><th>Qwen</th></tr></thead><tbody>{''.join(detail_rows)}</tbody></table></div>
</section>

<section id="sources"><h2>3. 두 원본 보고서 통합 열람</h2>
<p class="note">두 보고서 전문을 이 파일 안에 내장했다. 기존 실행 보고서는 수정하지 않았으며 아래 영역은 각각 독립 스크롤된다.</p>
<details open><summary>Sol·Luna xhigh 분류 실행 보고서</summary><p class="hash">내장 원본 SHA-256: <code>{reference_report_sha}</code></p><iframe title="Sol Luna reference report" sandbox="allow-scripts" srcdoc="{html.escape(reference_report, quote=True)}"></iframe></details>
<details><summary>TF-IDF·Dense·Qwen 상세 의사결정 보고서</summary><p class="hash">내장 원본 SHA-256: <code>{comparison_report_sha}</code></p><iframe title="Local methods decision report" sandbox="allow-scripts" srcdoc="{html.escape(comparison_report, quote=True)}"></iframe></details>
</section>
<footer>동결 입력과 기존 결과 JSON을 변경하지 않은 결정적 파생 보고서 · 사람 정답 승인 전 silver reference only</footer>
</main></body></html>"""


def main() -> int:
    args = parse_args()
    reference = load_json(args.reference_result)
    population = load_json(args.population)
    results = {
        method: load_json(args.results_dir / f"{method}.json")
        for method, _label in METHODS
    }
    validate_inputs(reference, population, results)
    output = render(
        reference,
        population,
        results,
        args.reference_report.read_text(encoding="utf-8"),
        args.comparison_report.read_text(encoding="utf-8"),
        sha256(args.reference_report),
        sha256(args.comparison_report),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
