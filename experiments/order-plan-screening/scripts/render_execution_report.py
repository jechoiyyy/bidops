#!/usr/bin/env python3
"""Render a self-contained interim HTML report without claiming model quality."""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from common import (
    ExperimentError,
    load_json,
    load_run_population,
    validate_method_result,
    validate_result_run_binding,
)


KST = timezone(timedelta(hours=9))
DEFAULT_METHODS = ("tfidf", "bge_m3_dense", "qwen")
METHOD_LABELS = {
    "tfidf": "TF-IDF",
    "bge_m3_dense": "BGE-M3 dense",
    "qwen": "Qwen3.8:27B",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--methods", nargs="+", default=list(DEFAULT_METHODS))
    return parser.parse_args()


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def duration(value: Any) -> str:
    if value is None:
        return "미측정"
    milliseconds = int(value)
    if milliseconds < 1000:
        return f"{milliseconds:,} ms"
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:,.2f}초"
    return f"{int(seconds // 60):,}분 {seconds % 60:04.1f}초"


def score_value(value: Any) -> str:
    return "—" if value is None else f"{float(value):.6f}"


def selected_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (row for row in result["items"] if row["selected"]),
        key=lambda row: row["rank"],
    )


def selected_ids(result: dict[str, Any]) -> set[str]:
    return {row["plan_id"] for row in result["items"] if row["selected"]}


def jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    return None if not union else len(left & right) / len(union)


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def render_method_summary(method: str, result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    successful_scores = [
        float(row["score"]) for row in result["items"] if row["status"] == "success"
    ]
    p50 = percentile(successful_scores, 0.5)
    p90 = percentile(successful_scores, 0.9)
    error_counts = Counter(
        row["error_code"] for row in result["items"] if row["status"] == "failed"
    )
    errors = (
        "없음"
        if not error_counts
        else ", ".join(f"{escape(code)} {count:,}건" for code, count in sorted(error_counts.items()))
    )
    batching = result["batching"]
    batching_text = (
        "해당 없음"
        if batching is None
        else f"{batching['batch_size']:,}건 × {batching['batch_count']:,} batch"
    )
    return f"""
      <article class="method-card">
        <div class="method-title"><h3>{escape(METHOD_LABELS.get(method, method))}</h3><span class="status {escape(result['status'])}">{escape(result['status'])}</span></div>
        <dl>
          <div><dt>성공 / 실패</dt><dd>{metrics['success_count']:,} / {metrics['failure_count']:,}</dd></div>
          <div><dt>Top 선택</dt><dd>{metrics['selected_count']:,}</dd></div>
          <div><dt>실제 총 소요</dt><dd>{escape(duration(metrics.get('elapsed_ms')))}</dd></div>
          <div><dt>HTTP·계산 지연 합</dt><dd>{escape(duration(metrics.get('total_latency_ms')))}</dd></div>
          <div><dt>batch</dt><dd>{escape(batching_text)}</dd></div>
          <div><dt>점수 중앙값 / P90</dt><dd>{score_value(p50)} / {score_value(p90)}</dd></div>
          <div><dt>장치</dt><dd>{escape(metrics.get('device') or '미측정')}</dd></div>
          <div><dt>오류</dt><dd>{errors}</dd></div>
        </dl>
      </article>
    """


def render_overlap(methods: Sequence[str], results: dict[str, dict[str, Any]]) -> str:
    selections = {method: selected_ids(results[method]) for method in methods}
    headers = "".join(f"<th>{escape(METHOD_LABELS.get(method, method))}</th>" for method in methods)
    rows: list[str] = []
    for left in methods:
        cells = []
        for right in methods:
            value = jaccard(selections[left], selections[right])
            cells.append(f"<td>{'—' if value is None else f'{value:.3f}'}</td>")
        rows.append(
            f"<tr><th>{escape(METHOD_LABELS.get(left, left))}</th>{''.join(cells)}</tr>"
        )
    return f"<table><thead><tr><th>Top 50 Jaccard</th>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def render_qwen_distribution(result: dict[str, Any] | None) -> str:
    if result is None:
        return "<p>Qwen 결과 없음</p>"
    counts = Counter(
        row["relevance"] for row in result["items"] if row["status"] == "success"
    )
    labels = (
        ("relevant", "관련"),
        ("uncertain", "판단보류"),
        ("not_relevant", "비관련"),
    )
    return "<div class=\"distribution\">" + "".join(
        f"<div><strong>{counts.get(value, 0):,}</strong><span>{label}</span></div>"
        for value, label in labels
    ) + "</div>"


def render_top_table(
    method: str,
    result: dict[str, Any],
    population_by_id: dict[str, dict[str, Any]],
) -> str:
    rows: list[str] = []
    for row in selected_rows(result):
        plan = population_by_id[row["plan_id"]]
        relevance = row["relevance"] or "—"
        rows.append(
            "<tr>"
            f"<td>{row['rank']}</td>"
            f"<td class=\"title-cell\">{escape(plan['title'])}</td>"
            f"<td>{score_value(row['score'])}</td>"
            f"<td>{escape(relevance)}</td>"
            f"<td>{escape(row['reason'])}</td>"
            "</tr>"
        )
    return f"""
      <section class="top-list">
        <h3>{escape(METHOD_LABELS.get(method, method))} Top 50</h3>
        <div class="table-scroll">
          <table>
            <thead><tr><th>순위</th><th>사업명</th><th>방법 내 점수</th><th>판정</th><th>근거</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
      </section>
    """


def render_report(
    run: dict[str, Any],
    population: dict[str, Any],
    methods: Sequence[str],
    results: dict[str, dict[str, Any]],
) -> str:
    population_by_id = {row["plan_id"]: row for row in population["items"]}
    generated_at = datetime.now(KST).isoformat(timespec="seconds")
    summaries = "".join(render_method_summary(method, results[method]) for method in methods)
    top_tables = "".join(
        render_top_table(method, results[method], population_by_id) for method in methods
    )
    qwen = results.get("qwen")
    model_rows = "".join(
        "<tr>"
        f"<td>{escape(METHOD_LABELS.get(method, method))}</td>"
        f"<td>{escape(results[method]['method_version'])}</td>"
        f"<td>{escape(results[method]['model']['name'] or '해당 없음')}</td>"
        f"<td class=\"hash\">{escape(results[method]['model']['revision'] or '해당 없음')}</td>"
        f"<td class=\"hash\">{escape(results[method]['prompt']['sha256'] or '해당 없음')}</td>"
        "</tr>"
        for method in methods
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
  <title>발주계획 임시 선별 실행 보고서 · {escape(run['run_id'])}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172033; --muted:#667085; --line:#d8dee9; --panel:#f7f9fc; --accent:#2457d6; --warn:#9a6700; --ok:#087443; --bad:#b42318; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#eef2f7; color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif; line-height:1.55; }}
    main {{ width:min(1400px,calc(100% - 32px)); margin:24px auto 56px; background:white; padding:clamp(22px,4vw,52px); border:1px solid var(--line); border-radius:16px; box-shadow:0 12px 32px rgba(20,34,66,.08); }}
    h1,h2,h3 {{ line-height:1.25; }} h1 {{ margin:0 0 8px; font-size:clamp(26px,4vw,42px); }} h2 {{ margin-top:44px; border-bottom:2px solid var(--ink); padding-bottom:10px; }}
    .subtitle,.note {{ color:var(--muted); }} .warning {{ margin:24px 0; padding:16px 18px; border-left:5px solid #e0a100; background:#fff8e6; }}
    .facts,.methods {{ display:grid; gap:14px; }} .facts {{ grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); margin:24px 0; }}
    .fact,.method-card {{ border:1px solid var(--line); border-radius:12px; padding:16px; background:var(--panel); }} .fact strong {{ display:block; font-size:24px; }} .fact span {{ color:var(--muted); }}
    .flow {{ display:grid; grid-template-columns:repeat(7,minmax(110px,1fr)); align-items:stretch; gap:8px; overflow-x:auto; padding:8px 0; }}
    .flow div {{ min-width:110px; padding:13px 10px; border:1px solid #b8c7e7; background:#f3f7ff; border-radius:10px; text-align:center; }} .flow .arrow {{ min-width:24px; border:0; background:none; display:grid; place-items:center; color:var(--accent); font-size:22px; }}
    .methods {{ grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); }} .method-title {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }} .method-title h3 {{ margin:0; }}
    .status {{ font-size:12px; border-radius:999px; padding:4px 8px; background:#e8edf5; }} .status.success {{ color:var(--ok); background:#e7f6ee; }} .status.failed {{ color:var(--bad); background:#feeceb; }} .status.partial_failure {{ color:var(--warn); background:#fff3d6; }}
    dl {{ margin:14px 0 0; }} dl div {{ display:flex; justify-content:space-between; gap:18px; border-top:1px solid var(--line); padding:8px 0; }} dt {{ color:var(--muted); }} dd {{ margin:0; text-align:right; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }} th,td {{ border:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; }} th {{ background:#f1f4f9; }} td:not(.title-cell):not(.hash) {{ white-space:nowrap; }} .hash {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; word-break:break-all; font-size:12px; }}
    .table-scroll {{ overflow-x:auto; }} .top-list {{ margin:28px 0; }} .distribution {{ display:flex; gap:12px; flex-wrap:wrap; }} .distribution div {{ min-width:150px; padding:16px; border:1px solid var(--line); border-radius:10px; }} .distribution strong,.distribution span {{ display:block; }} .distribution strong {{ font-size:24px; }}
    code {{ background:#eef2f7; padding:2px 5px; border-radius:4px; }} footer {{ margin-top:44px; color:var(--muted); font-size:13px; }}
    @media (max-width:760px) {{ main {{ width:100%; margin:0; border-radius:0; }} .flow {{ grid-template-columns:1fr; }} .flow .arrow {{ transform:rotate(90deg); }} }}
  </style>
</head>
<body><main>
  <header>
    <h1>발주계획 임시 선별 실행 보고서</h1>
    <p class="subtitle">실행 ID <code>{escape(run['run_id'])}</code> · 생성 {escape(generated_at)}</p>
  </header>

  <div class="warning"><strong>판정 범위:</strong> 이 보고서는 TF-IDF, BGE-M3 dense, Qwen의 실행 상태와 후보 차이를 정리한 임시 보고서다. 사람 정답과 ColBERT 결과가 없으므로 precision·recall·최종 우승·운영 정책 활성화를 판단하지 않는다.</div>

  <section class="facts">
    <div class="fact"><strong>{len(population['items']):,}건</strong><span>고정 3일 모집단</span></div>
    <div class="fact"><strong>{run['collection']['page_count']:,} page</strong><span>불변 raw</span></div>
    <div class="fact"><strong>{len(methods)}개</strong><span>이번 실행 방법</span></div>
    <div class="fact"><strong>Top {run['selection']['top_k']}</strong><span>방법별 검토 후보</span></div>
  </section>

  <h2>요청부터 모델 직전까지의 흐름</h2>
  <div class="flow" aria-label="데이터 처리 흐름">
    <div>나라장터<br>3일 API 요청</div><div class="arrow">→</div>
    <div>raw page<br>응답·query·hash</div><div class="arrow">→</div>
    <div>완전성 검증<br>page·count·기간</div><div class="arrow">→</div>
    <div>population<br>null·source 보존</div>
  </div>
  <div class="flow" aria-label="방법별 입력 흐름">
    <div>plan에서<br><strong>title만 projection</strong></div><div class="arrow">+</div>
    <div>승인된<br>company capabilities</div><div class="arrow">→</div>
    <div>TF-IDF<br>로컬 문자 2~5-gram</div><div class="arrow">/</div>
    <div>BGE dense<br>Ollama embedding</div><div class="arrow">/</div>
    <div>Qwen<br>25건 고정 batch</div>
  </div>
  <p class="note">기관·예산·계약 방식·원문 ID는 모집단에 보존하지만 이번 세 방법의 비교 입력에는 사용하지 않는다. Dense 전송은 capability summary 문자열과 title 문자열뿐이며, Qwen 전송은 승인 역량 projection과 batch-local item_id·title뿐이다.</p>

  <h2>방법별 실행 결과</h2>
  <section class="methods">{summaries}</section>

  <h2>Qwen 구조화 판정 분포</h2>
  {render_qwen_distribution(qwen)}
  <p class="note">Qwen 출력은 <code>relevant | uncertain | not_relevant</code>, 0~1 점수, 짧은 이유다. 이는 사람 판정이나 확률이 아니다.</p>

  <h2>Top 50 후보 중복</h2>
  {render_overlap(methods, results)}
  <p class="note">Jaccard는 두 Top 50 교집합 크기를 합집합 크기로 나눈 값이다. 점수 자체는 방법마다 의미가 달라 서로 직접 비교하지 않는다.</p>

  <h2>고정 버전과 모델 binding</h2>
  <div class="table-scroll"><table><thead><tr><th>방법</th><th>method version</th><th>model</th><th>revision/digest</th><th>prompt hash</th></tr></thead><tbody>{model_rows}</tbody></table></div>
  <p class="note">회사 역량 본문과 prompt 본문은 보고서에 포함하지 않고 실행 artifact에 고정된 hash로만 추적한다.</p>

  <h2>방법별 Top 50</h2>
  {top_tables}

  <h2>후속 게이트</h2>
  <ol>
    <li>별도 GPU 환경에서 고정 revision BGE-M3 ColBERT 실행</li>
    <li>방법별 Top 후보 합집합과 감사 표본에 대한 사람 relevance·우선순위 작성</li>
    <li>precision@50, 중요 누락, 상대 회수율, 비용·시간을 함께 비교</li>
    <li>승인 전에는 어떤 방법도 운영 선별 정책으로 활성화하지 않음</li>
  </ol>

  <footer>population SHA-256: <span class="hash">{escape(population['population_sha256'])}</span><br>methods config SHA-256: <span class="hash">{escape(run['config']['methods_sha256'])}</span></footer>
</main></body></html>
"""


def main() -> int:
    args = parse_args()
    try:
        run_dir = args.run_dir.resolve()
        run, population = load_run_population(run_dir)
        methods = tuple(args.methods)
        if not methods or len(methods) != len(set(methods)):
            raise ExperimentError("method_set_mismatch", "보고서 방법이 비었거나 중복됐습니다")
        results: dict[str, dict[str, Any]] = {}
        for method in methods:
            result = validate_method_result(
                load_json(run_dir / "results" / f"{method}.json"),
                population,
                method,
                run["selection"]["top_k"],
            )
            validate_result_run_binding(result, run)
            results[method] = result
        requested_output_dir = args.output_dir
        if requested_output_dir.is_symlink():
            raise ExperimentError("report_path_rejected", "보고서 디렉터리 symlink는 허용하지 않습니다")
        output_dir = requested_output_dir.resolve()
        output = output_dir / "report.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(render_report(run, population, methods, results))
        except FileExistsError as exc:
            raise ExperimentError("artifact_exists", "기존 report.html을 덮어쓸 수 없습니다") from exc
        print(
            json.dumps(
                {
                    "status": "complete",
                    "run_id": run["run_id"],
                    "population_count": len(population["items"]),
                    "methods": list(methods),
                    "report": str(output),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except ExperimentError as exc:
        print(
            json.dumps({"status": "failed", "error_code": exc.code}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
