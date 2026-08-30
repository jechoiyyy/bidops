#!/usr/bin/env python3
"""Render a self-contained detailed decision report from immutable results."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence

from common import (
    ExperimentError,
    load_json,
    load_run_population,
    validate_method_result,
    validate_result_run_binding,
)
from render_execution_report import duration, escape, percentile, score_value


KST = timezone(timedelta(hours=9))
DEFAULT_METHODS = ("tfidf", "bge_m3_dense", "qwen")
METHOD_LABELS = {
    "tfidf": "TF-IDF",
    "bge_m3_dense": "BGE-M3 dense",
    "qwen": "Qwen3.8:27B",
}
RELEVANCE_LABELS = {
    "relevant": "관련",
    "uncertain": "판단보류",
    "not_relevant": "비관련",
}
OUTPUT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.html")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--output-name", default="decision-report.html")
    parser.add_argument("--methods", nargs="+", default=list(DEFAULT_METHODS))
    return parser.parse_args()


def percent(numerator: int, denominator: int) -> str:
    return "계산 불가" if denominator == 0 else f"{numerator / denominator * 100:.1f}%"


def throughput(count: int, elapsed_ms: int | None) -> str:
    if not elapsed_ms:
        return "계산 불가"
    per_second = count * 1000 / elapsed_ms
    return (
        f"{per_second:,.2f}건/초"
        if per_second >= 1
        else f"{per_second * 60:,.2f}건/분"
    )


def successful_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in result["items"] if row["status"] == "success"]


def top_rows(result: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    return sorted(
        (
            row
            for row in successful_rows(result)
            if isinstance(row.get("rank"), int) and row["rank"] <= limit
        ),
        key=lambda row: row["rank"],
    )


def top_ids(result: dict[str, Any], limit: int) -> set[str]:
    return {row["plan_id"] for row in top_rows(result, limit)}


def jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    return None if not union else len(left & right) / len(union)


def rank_correlation(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[float | None, int]:
    left_ranks = {row["plan_id"]: float(row["rank"]) for row in successful_rows(left)}
    right_ranks = {row["plan_id"]: float(row["rank"]) for row in successful_rows(right)}
    common = sorted(set(left_ranks) & set(right_ranks))
    if len(common) < 2:
        return None, len(common)
    xs = [left_ranks[plan_id] for plan_id in common]
    ys = [right_ranks[plan_id] for plan_id in common]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs)
        * sum((y - mean_y) ** 2 for y in ys)
    )
    return (None if denominator == 0 else numerator / denominator), len(common)


def collection_elapsed_ms(run: dict[str, Any]) -> int | None:
    collection = run.get("collection") or {}
    first = collection.get("first_collected_at")
    last = collection.get("last_collected_at")
    if not isinstance(first, str) or not isinstance(last, str):
        return None
    try:
        elapsed = datetime.fromisoformat(last) - datetime.fromisoformat(first)
    except ValueError:
        return None
    return max(0, round(elapsed.total_seconds() * 1000))


def render_data_quality(run: dict[str, Any], population: dict[str, Any]) -> str:
    items = population["items"]
    divisions = Counter(row.get("business_division") or "unknown" for row in items)
    unknowns = Counter(
        field
        for row in items
        for field in row.get("unknown_fields", [])
        if isinstance(field, str)
    )
    division_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{count:,}</td><td>{percent(count, len(items))}</td></tr>"
        for name, count in sorted(divisions.items())
    )
    unknown_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{count:,}</td><td>{percent(count, len(items))}</td><td>{'차단' if name == 'title' else '현재 입력 아님'}</td></tr>"
        for name, count in sorted(unknowns.items(), key=lambda item: (-item[1], item[0]))
    ) or '<tr><td colspan="4">unknown field 없음</td></tr>'
    window = run.get("query_window") or {}
    collection = run.get("collection") or {}
    page_count = int(collection.get("page_count") or 0)
    request_count = int(collection.get("request_count") or 0)
    return f"""
      <div class="split">
        <article class="panel"><h3>수집 완전성</h3><dl>
          <div><dt>게시 구간</dt><dd class="wrap">{escape(window.get('from') or '미기록')} 이상<br>{escape(window.get('to_exclusive') or '미기록')} 미만</dd></div>
          <div><dt>raw page / API 요청</dt><dd>{page_count:,} / {request_count:,}</dd></div>
          <div><dt>추가 요청</dt><dd>{max(0, request_count - page_count):,}회</dd></div>
          <div><dt>수집 벽시계</dt><dd>{escape(duration(collection_elapsed_ms(run)))}</dd></div>
          <div><dt>모집단</dt><dd>{len(items):,}건</dd></div>
          <div><dt>완전성 표시</dt><dd>{'통과' if collection.get('complete') is True else '미확인'}</dd></div>
        </dl></article>
        <article class="panel"><h3>업무구분 구성</h3><table><thead><tr><th>구분</th><th>건수</th><th>비율</th></tr></thead><tbody>{division_rows}</tbody></table></article>
      </div>
      <h3>정규화 unknown 현황</h3>
      <div class="table-scroll"><table><thead><tr><th>필드</th><th>unknown 건수</th><th>비율</th><th>이번 비교 영향</th></tr></thead><tbody>{unknown_rows}</tbody></table></div>
      <p class="note">unknown은 값을 추정하지 않고 보존한 상태다. 이번 세 방법은 title만 읽으므로 비-title unknown은 현재 점수에 영향을 주지 않는다.</p>
    """


def render_method_cards(
    methods: Sequence[str], results: dict[str, dict[str, Any]]
) -> str:
    cards: list[str] = []
    for method in methods:
        result = results[method]
        metrics = result["metrics"]
        scores = [float(row["score"]) for row in successful_rows(result)]
        errors = Counter(row["error_code"] for row in result["items"] if row["status"] == "failed")
        error_text = ", ".join(f"{code} {count:,}건" for code, count in sorted(errors.items())) or "없음"
        batching = result.get("batching")
        batch_text = "해당 없음" if not batching else f"{batching['batch_size']}건 × {batching['batch_count']} batch"
        cards.append(f"""
          <article class="method-card"><div class="method-title"><h3>{escape(METHOD_LABELS.get(method, method))}</h3><span class="status {escape(result['status'])}">{escape(result['status'])}</span></div><dl>
            <div><dt>성공 / 실패</dt><dd>{metrics['success_count']:,} / {metrics['failure_count']:,}</dd></div>
            <div><dt>coverage</dt><dd>{percent(metrics['success_count'], metrics['population_count'])}</dd></div>
            <div><dt>실제 총 소요</dt><dd>{escape(duration(metrics.get('elapsed_ms')))}</dd></div>
            <div><dt>처리량</dt><dd>{escape(throughput(metrics['population_count'], metrics.get('elapsed_ms')))}</dd></div>
            <div><dt>batch</dt><dd>{escape(batch_text)}</dd></div>
            <div><dt>점수 P10 / 중앙 / P90</dt><dd>{score_value(percentile(scores, .1))} / {score_value(percentile(scores, .5))} / {score_value(percentile(scores, .9))}</dd></div>
            <div><dt>오류</dt><dd class="wrap">{escape(error_text)}</dd></div>
          </dl></article>
        """)
    return "".join(cards)


def render_score_table(
    methods: Sequence[str], results: dict[str, dict[str, Any]]
) -> str:
    rows: list[str] = []
    for method in methods:
        values = [float(row["score"]) for row in successful_rows(results[method])]
        rows.append(
            f"<tr><td>{escape(METHOD_LABELS.get(method, method))}</td><td>{len(values):,}</td>"
            f"<td>{score_value(min(values) if values else None)}</td><td>{score_value(percentile(values, .1))}</td>"
            f"<td>{score_value(percentile(values, .5))}</td><td>{score_value(percentile(values, .9))}</td>"
            f"<td>{score_value(max(values) if values else None)}</td></tr>"
        )
    return f'<div class="table-scroll"><table><thead><tr><th>방법</th><th>유효 건수</th><th>최소</th><th>P10</th><th>중앙값</th><th>P90</th><th>최대</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def render_capability_table(
    methods: Sequence[str], results: dict[str, dict[str, Any]], top_k: int
) -> str:
    supported = [method for method in methods if method in {"tfidf", "bge_m3_dense"}]
    counts: dict[str, tuple[Counter[str], Counter[str]]] = {}
    capability_ids: set[str] = set()
    for method in supported:
        all_counts: Counter[str] = Counter()
        top_counts: Counter[str] = Counter()
        for row in successful_rows(results[method]):
            reason = row.get("reason")
            if not isinstance(reason, str) or not reason.startswith("nearest_capability:"):
                continue
            capability_id = reason.split(":", 1)[1]
            all_counts[capability_id] += 1
            if row["rank"] <= top_k:
                top_counts[capability_id] += 1
            capability_ids.add(capability_id)
        counts[method] = all_counts, top_counts
    if not capability_ids:
        return '<p class="note">capability attribution을 계산할 수 없다.</p>'
    headers = "".join(
        f"<th>{escape(METHOD_LABELS[method])} 전체</th><th>{escape(METHOD_LABELS[method])} Top {top_k}</th>"
        for method in supported
    )
    rows = "".join(
        "<tr>" + f"<td>{escape(capability_id)}</td>" + "".join(
            f"<td>{counts[method][0][capability_id]:,}</td><td>{counts[method][1][capability_id]:,}</td>"
            for method in supported
        ) + "</tr>"
        for capability_id in sorted(capability_ids)
    )
    return f'<div class="table-scroll"><table><thead><tr><th>capability ID</th>{headers}</tr></thead><tbody>{rows}</tbody></table></div><p class="note">회사 역량 본문은 표시하지 않고 승인 projection의 안정 ID만 사용한다. 한 역량으로 쏠리면 요약 범위·중복·표현 편향을 검토해야 한다.</p>'


def render_overlap(
    methods: Sequence[str], results: dict[str, dict[str, Any]], top_k: int
) -> str:
    pair_rows: list[str] = []
    correlation_rows: list[str] = []
    limits = sorted({min(10, top_k), min(25, top_k), top_k})
    for left_index, left in enumerate(methods):
        for right in methods[left_index + 1 :]:
            for limit in limits:
                left_ids = top_ids(results[left], limit)
                right_ids = top_ids(results[right], limit)
                value = jaccard(left_ids, right_ids)
                pair_rows.append(
                    f"<tr><td>{escape(METHOD_LABELS[left])} ↔ {escape(METHOD_LABELS[right])}</td><td>Top {limit}</td>"
                    f"<td>{len(left_ids & right_ids):,}</td><td>{len(left_ids | right_ids):,}</td><td>{'—' if value is None else f'{value:.3f}'}</td></tr>"
                )
            correlation, common_count = rank_correlation(results[left], results[right])
            correlation_rows.append(
                f"<tr><td>{escape(METHOD_LABELS[left])} ↔ {escape(METHOD_LABELS[right])}</td><td>{common_count:,}</td><td>{'—' if correlation is None else f'{correlation:.3f}'}</td></tr>"
            )
    composition = ""
    if len(methods) == 3:
        selections = {method: top_ids(results[method], top_k) for method in methods}
        union = set().union(*selections.values())
        triple = set.intersection(*selections.values())
        only = {
            method: selections[method] - set().union(*(selections[other] for other in methods if other != method))
            for method in methods
        }
        composition = '<section class="facts compact">' + "".join(
            (
                f'<div class="fact"><strong>{len(union):,}건</strong><span>세 방법 합집합</span></div>',
                f'<div class="fact"><strong>{len(triple):,}건</strong><span>세 방법 공통</span></div>',
                *(f'<div class="fact"><strong>{len(only[method]):,}건</strong><span>{escape(METHOD_LABELS[method])}만 발견</span></div>' for method in methods),
            )
        ) + "</section>"
    return f"""
      {composition}
      <div class="split"><div><h3>Top-K 교집합</h3><div class="table-scroll"><table><thead><tr><th>방법 쌍</th><th>범위</th><th>교집합</th><th>합집합</th><th>Jaccard</th></tr></thead><tbody>{''.join(pair_rows)}</tbody></table></div></div>
      <div><h3>전체 유효 순위 상관</h3><table><thead><tr><th>방법 쌍</th><th>공통 유효 건수</th><th>순위 상관</th></tr></thead><tbody>{''.join(correlation_rows)}</tbody></table><p class="note">저장된 결정적 rank의 Pearson 상관이다. 점수 단위의 동등성이나 품질 우열을 뜻하지 않는다.</p></div></div>
    """


def qwen_batches(result: dict[str, Any]) -> list[dict[str, Any]]:
    batching = result.get("batching")
    if not isinstance(batching, dict):
        return []
    size = int(batching["batch_size"])
    batches: list[dict[str, Any]] = []
    for offset in range(0, len(result["items"]), size):
        rows = result["items"][offset : offset + size]
        successes = [row for row in rows if row["status"] == "success"]
        failures = [row for row in rows if row["status"] == "failed"]
        batches.append(
            {
                "number": offset // size + 1,
                "count": len(rows),
                "status": "success" if not failures else "failed" if not successes else "partial_failure",
                "success": len(successes),
                "failure": len(failures),
                "latency": sum(row["latency_ms"] or 0 for row in rows),
                "input": sum(row["input_tokens"] or 0 for row in rows),
                "output": sum(row["output_tokens"] or 0 for row in rows),
                "errors": Counter(row["error_code"] for row in failures),
            }
        )
    return batches


def render_qwen(result: dict[str, Any] | None, top_k: int) -> str:
    if result is None:
        return '<p class="note">Qwen 결과 없음</p>'
    metrics = result["metrics"]
    successes = successful_rows(result)
    failures = [row for row in result["items"] if row["status"] == "failed"]
    relevance = Counter(row["relevance"] for row in successes)
    top_relevance = Counter(row["relevance"] for row in top_rows(result, top_k))
    errors = Counter(row["error_code"] for row in failures)
    batches = qwen_batches(result)
    batch_rows = "".join(
        f"<tr><td>{batch['number']}</td><td>{batch['count']}</td><td><span class=\"status {escape(batch['status'])}\">{escape(batch['status'])}</span></td>"
        f"<td>{batch['success']} / {batch['failure']}</td><td>{escape(duration(batch['latency']))}</td><td>{batch['input']:,} / {batch['output']:,}</td>"
        f"<td class=\"wrap\">{escape(', '.join(f'{code} {count}건' for code, count in sorted(batch['errors'].items())) or '없음')}</td></tr>"
        for batch in batches
    )
    distribution = "".join(
        f'<div class="fact"><strong>{relevance.get(key, 0):,}건</strong><span>{label} · 성공건의 {percent(relevance.get(key, 0), len(successes))}</span></div>'
        for key, label in RELEVANCE_LABELS.items()
    )
    error_text = ", ".join(f"{code} {count:,}건" for code, count in sorted(errors.items())) or "없음"
    top_text = ", ".join(
        f"{RELEVANCE_LABELS.get(key, key)} {count}건" for key, count in sorted(top_relevance.items())
    )
    if errors and set(errors) == {"truncated_output"}:
        interpretation = (
            "실패가 모두 truncated_output인 것은 출력 길이 한계가 실제 병목임을 뜻한다. "
            "다만 현재 artifact만으로 batch 크기, reasoning 길이, 출력 상한 중 단일 원인을 "
            "확정할 수 없어 한 변수씩 바꾼 새 실행이 필요하다."
        )
    else:
        interpretation = (
            "실패 유형이 하나로 수렴하지 않았다. 오류 유형별 재현 run을 분리하고, "
            "검증기를 우회하거나 실패 응답을 자동 보정하지 않아야 한다."
        )
    return f"""
      <section class="facts compact">{distribution}</section>
      <div class="split"><article class="panel"><h3>coverage와 오류</h3><dl>
        <div><dt>성공 coverage</dt><dd>{metrics['success_count']:,}/{metrics['population_count']:,} ({percent(metrics['success_count'], metrics['population_count'])})</dd></div>
        <div><dt>실패 batch</dt><dd>{sum(batch['status'] != 'success' for batch in batches):,}/{len(batches):,}</dd></div>
        <div><dt>오류</dt><dd class="wrap">{escape(error_text)}</dd></div>
        <div><dt>Top {top_k} 판정 구성</dt><dd class="wrap">{escape(top_text)}</dd></div>
      </dl></article><article class="panel"><h3>기록된 token과 시간</h3><dl>
        <div><dt>input</dt><dd>{metrics.get('input_tokens') or 0:,}</dd></div><div><dt>cached input</dt><dd>{metrics.get('cached_input_tokens') or 0:,}</dd></div>
        <div><dt>output</dt><dd>{metrics.get('output_tokens') or 0:,}</dd></div><div><dt>전체 벽시계</dt><dd>{escape(duration(metrics.get('elapsed_ms')))}</dd></div>
      </dl><p class="note">실패 행 token은 null이므로 합계는 전체 사용량의 하한이다.</p></article></div>
      <div class="callout danger"><strong>원인 해석:</strong> {escape(interpretation)}</div>
      <details><summary>Qwen {len(batches):,}개 batch 상세 보기</summary><div class="table-scroll"><table><thead><tr><th>batch</th><th>건수</th><th>상태</th><th>성공/실패</th><th>지연</th><th>input/output token</th><th>오류</th></tr></thead><tbody>{batch_rows}</tbody></table></div><p class="note">현재 producer가 population 순서로 result item을 기록한다는 실행 사실과 고정 batch 크기로 재구성한 파생 표다.</p></details>
    """


def projected_elapsed(result: dict[str, Any], target: int) -> tuple[int, int | None]:
    elapsed = int(result["metrics"]["elapsed_ms"])
    batching = result.get("batching")
    if isinstance(batching, dict):
        target_batches = math.ceil(target / int(batching["batch_size"]))
        return round(elapsed / int(batching["batch_count"]) * target_batches), target_batches
    current = int(result["metrics"]["population_count"])
    return round(elapsed / current * target), None


def render_projection(
    methods: Sequence[str], results: dict[str, dict[str, Any]], current_count: int
) -> str:
    rows: list[str] = []
    for method in methods:
        for target in (current_count, 1200, 2000):
            elapsed, batch_count = projected_elapsed(results[method], target)
            rows.append(
                f"<tr><td>{escape(METHOD_LABELS[method])}</td><td>{target:,}건{' (실측)' if target == current_count else ' (추정)'}</td>"
                f"<td>{'—' if batch_count is None else f'{batch_count:,}'}</td><td>{escape(duration(elapsed))}</td></tr>"
            )
    return f'<div class="table-scroll"><table><thead><tr><th>방법</th><th>규모</th><th>batch 수</th><th>소요시간</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div><p class="note">추정치는 현재 평균 batch 시간 또는 건당 시간을 선형 적용한 용량 계획값이다. 서버 경합, cold load, 제목·출력 길이를 반영하지 않으므로 SLA가 아니다.</p>'


def render_top_tables(
    methods: Sequence[str], results: dict[str, dict[str, Any]], population: dict[str, Any]
) -> str:
    by_id = {row["plan_id"]: row for row in population["items"]}
    sections: list[str] = []
    for method in methods:
        rows = "".join(
            f"<tr><td>{row['rank']}</td><td class=\"wrap\">{escape(by_id[row['plan_id']]['title'])}</td><td>{score_value(row['score'])}</td>"
            f"<td>{escape(RELEVANCE_LABELS.get(row['relevance'], row['relevance'] or '—'))}</td><td class=\"wrap\">{escape(row['reason'])}</td></tr>"
            for row in top_rows(results[method], results[method]["top_k"])
        )
        sections.append(
            f'<details><summary>{escape(METHOD_LABELS[method])} Top {results[method]["top_k"]}</summary><div class="table-scroll"><table><thead><tr><th>순위</th><th>사업명</th><th>점수</th><th>판정</th><th>근거</th></tr></thead><tbody>{rows}</tbody></table></div></details>'
        )
    return "".join(sections)


def render_bindings(methods: Sequence[str], results: dict[str, dict[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td>{escape(METHOD_LABELS[method])}</td><td>{escape(results[method]['method_version'])}</td>"
        f"<td>{escape(results[method]['model']['name'] or '해당 없음')}</td><td class=\"hash\">{escape(results[method]['model']['revision'] or '해당 없음')}</td>"
        f"<td class=\"hash\">{escape(results[method]['config_sha256'])}</td><td class=\"hash\">{escape(results[method]['prompt']['sha256'] or '해당 없음')}</td></tr>"
        for method in methods
    )
    return f'<div class="table-scroll"><table><thead><tr><th>방법</th><th>method version</th><th>model</th><th>revision/digest</th><th>method config hash</th><th>prompt hash</th></tr></thead><tbody>{rows}</tbody></table></div>'


def render_report(
    run: dict[str, Any],
    population: dict[str, Any],
    methods: Sequence[str],
    results: dict[str, dict[str, Any]],
) -> str:
    generated_at = datetime.now(KST).isoformat(timespec="seconds")
    top_k = int(run["selection"]["top_k"])
    qwen = results.get("qwen")
    qwen_failures = qwen["metrics"]["failure_count"] if qwen else 0
    union_count = 0
    staged_text = "계산 불가"
    if "tfidf" in results and "bge_m3_dense" in results:
        first_stage = top_ids(results["tfidf"], top_k) | top_ids(results["bge_m3_dense"], top_k)
        union_count = len(first_stage)
        if qwen and qwen.get("batching"):
            batches = math.ceil(union_count / qwen["batching"]["batch_size"])
            average_batch = qwen["metrics"]["elapsed_ms"] / qwen["batching"]["batch_count"]
            staged_text = f"{union_count}건, {batches} batch, 현재 평균 기준 약 {duration(round(average_batch * batches))}"
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>발주계획 선별 상세 의사결정 보고서 · {escape(run['run_id'])}</title>
<style>
:root{{--ink:#172033;--muted:#667085;--line:#d8dee9;--panel:#f7f9fc;--accent:#2457d6;--ok:#087443;--bad:#b42318;--warn:#9a6700}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#e9eef5;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;line-height:1.58}}main{{width:min(1480px,calc(100% - 32px));margin:24px auto 56px;background:#fff;padding:clamp(22px,4vw,56px);border:1px solid var(--line);border-radius:18px;box-shadow:0 14px 36px #14224217}}h1,h2,h3{{line-height:1.25}}h1{{margin:0 0 8px;font-size:clamp(28px,4vw,44px)}}h2{{margin-top:52px;border-bottom:2px solid #11264d;padding-bottom:10px}}a{{color:var(--accent)}}.subtitle,.note{{color:var(--muted)}}.lede{{font-size:18px;max-width:1050px}}nav{{margin:24px 0;padding:16px 20px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}}nav ol{{columns:2}}.callout{{margin:20px 0;padding:16px 18px;border-left:5px solid var(--accent);background:#f1f6ff}}.warning{{border-color:#e0a100;background:#fff8e6}}.danger{{border-color:var(--bad);background:#fff1f0}}.success-callout{{border-color:var(--ok);background:#edf9f2}}.facts,.methods,.split{{display:grid;gap:14px}}.facts{{grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin:20px 0}}.compact{{grid-template-columns:repeat(auto-fit,minmax(155px,1fr))}}.methods{{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}}.split{{grid-template-columns:repeat(auto-fit,minmax(360px,1fr));align-items:start}}.fact,.method-card,.panel{{border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--panel)}}.fact strong{{display:block;font-size:25px}}.fact span{{color:var(--muted)}}.method-title{{display:flex;align-items:center;justify-content:space-between;gap:12px}}.method-title h3,.panel h3{{margin:0 0 10px}}.status{{display:inline-block;font-size:12px;border-radius:999px;padding:4px 8px;background:#e8edf5}}.status.success,.gate-pass{{color:var(--ok);background:#e7f6ee}}.status.failed,.gate-fail{{color:var(--bad);background:#feeceb}}.status.partial_failure,.gate-hold{{color:var(--warn);background:#fff3d6}}dl{{margin:12px 0 0}}dl div{{display:flex;justify-content:space-between;gap:18px;border-top:1px solid var(--line);padding:8px 0}}dt{{color:var(--muted)}}dd{{margin:0;text-align:right}}.flow{{display:flex;align-items:stretch;gap:8px;overflow-x:auto;padding:8px 0}}.flow div{{min-width:150px;padding:14px 10px;border:1px solid #b8c7e7;background:#f3f7ff;border-radius:10px;text-align:center}}.flow .arrow{{min-width:28px;border:0;background:none;display:grid;place-items:center;color:var(--accent);font-size:22px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{border:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}}th{{background:#edf2f8}}td:not(.wrap):not(.hash){{white-space:nowrap}}.wrap{{white-space:normal}}.hash{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;word-break:break-all;font-size:12px}}.table-scroll{{overflow-x:auto}}details{{margin:16px 0;border:1px solid var(--line);border-radius:10px;padding:12px}}summary{{cursor:pointer;font-weight:700}}details[open] summary{{margin-bottom:12px}}li{{margin:8px 0}}code{{background:#eef2f7;padding:2px 5px;border-radius:4px}}footer{{margin-top:52px;color:var(--muted);font-size:13px}}@media(max-width:760px){{main{{width:100%;margin:0;border-radius:0}}nav ol{{columns:1}}.split{{grid-template-columns:1fr}}.flow{{flex-direction:column}}.flow .arrow{{transform:rotate(90deg)}}}}@media print{{body{{background:#fff}}main{{width:100%;margin:0;border:0;box-shadow:none}}nav{{display:none}}}}
</style></head><body><main>
<header><h1>발주계획 선별 상세 의사결정 보고서</h1><p class="subtitle">실행 ID <code>{escape(run['run_id'])}</code> · 파생 보고서 생성 {escape(generated_at)}</p><p class="lede">사업명만으로 “우리 회사가 검토해볼 만한가”를 빠르게 거르는 발주계획 단계에서 TF-IDF, BGE-M3 dense representation, Qwen을 같은 {len(population['items']):,}건에 적용한 실행·운영 분석이다.</p></header>
<div class="callout warning"><strong>결론의 경계:</strong> 사람 정답, ColBERT, Luna가 없고 Qwen은 {qwen_failures:,}건이 실패했다. 따라서 구현·운영 방향을 좁히는 자료이며 precision·recall, 최종 우승, 정책 활성화, Go/No-Go를 결정하지 않는다.</div>
<nav><strong>목차</strong><ol><li><a href="#summary">의사결정 요약</a></li><li><a href="#data">데이터 품질</a></li><li><a href="#flow">전송·처리·출력</a></li><li><a href="#execution">실행 성능</a></li><li><a href="#candidates">후보 차이</a></li><li><a href="#qwen">Qwen 실패</a></li><li><a href="#scale">규모별 예상시간</a></li><li><a href="#decision">고도화·게이트</a></li><li><a href="#top">Top 후보</a></li><li><a href="#binding">재현성·보안</a></li></ol></nav>

<section id="summary"><h2>1. 의사결정 요약</h2><section class="facts"><div class="fact"><strong>{len(population['items']):,}건</strong><span>동결 모집단</span></div><div class="fact"><strong>{escape(duration(results['tfidf']['metrics']['elapsed_ms']))}</strong><span>TF-IDF 전수</span></div><div class="fact"><strong>{escape(duration(results['bge_m3_dense']['metrics']['elapsed_ms']))}</strong><span>dense 전수</span></div><div class="fact"><strong>{escape(duration(qwen['metrics']['elapsed_ms'])) if qwen else '미측정'}</strong><span>Qwen 전수 시도</span></div><div class="fact"><strong>{percent(qwen['metrics']['success_count'], qwen['metrics']['population_count']) if qwen else '미측정'}</strong><span>Qwen coverage</span></div></section>
<div class="split"><article class="panel"><h3>지금 말할 수 있는 것</h3><ul><li>TF-IDF와 dense는 전 모집단을 실패 없이 처리해 후보 생성기의 실행 가능성을 확인했다.</li><li>dense는 의미 기반 전수 점수를 {escape(duration(results['bge_m3_dense']['metrics']['elapsed_ms']))}에 만들었다.</li><li>Qwen 전수 판정은 {escape(duration(qwen['metrics']['elapsed_ms'])) if qwen else '미측정'}이 걸리고 coverage가 불완전해 현 설정 그대로는 준비되지 않았다.</li><li>방법별 Top 후보가 달라 사람 정답 없이 하나를 제거하면 고유 후보를 잃을 수 있다.</li></ul></article><article class="panel"><h3>아직 말할 수 없는 것</h3><ul><li>어느 방법의 precision@50이 높은지, 중요한 사업을 덜 놓치는지 알 수 없다.</li><li>Qwen 실패 건이 순위에서 빠져 현재 Qwen Top 50은 편향될 수 있다.</li><li>한 회차·한 번 실행이므로 일별 구성 변화와 성능 분산을 알 수 없다.</li><li>title-only 외 조건을 추가할 때의 효과는 새 방법 버전으로 검증해야 한다.</li></ul></article></div>
<div class="callout success-callout"><strong>중간 엔지니어링 권고:</strong> 품질 우승자를 정하지 않고 TF-IDF와 dense를 사람 라벨 후보 생성용으로 함께 유지한다. Qwen은 truncation을 해결한 100% coverage 새 run에서 평가하며 운영 정책을 자동 활성화하지 않는다.</div></section>

<section id="data"><h2>2. 모집단과 데이터 품질</h2>{render_data_quality(run, population)}</section>
<section id="flow"><h2>3. API 요청부터 모델 출력까지</h2><div class="flow"><div>나라장터<br>3일 API</div><div class="arrow">→</div><div>raw page<br>query·응답·hash</div><div class="arrow">→</div><div>완전성 검증<br>기간·건수·ID</div><div class="arrow">→</div><div>population<br>null·source 보존</div></div><div class="flow"><div>plan에서<br><strong>title만 projection</strong></div><div class="arrow">+</div><div>승인된<br>company capabilities</div><div class="arrow">→</div><div>TF-IDF<br>로컬</div><div class="arrow">/</div><div>BGE dense<br>128건 embedding</div><div class="arrow">/</div><div>Qwen<br>25건 판정</div></div>
<div class="table-scroll"><table><thead><tr><th>방법</th><th>입력</th><th>처리</th><th>저장 출력</th></tr></thead><tbody><tr><td>TF-IDF</td><td>로컬 title + 승인 capability summary</td><td>문자 2~5-gram TF-IDF, 최대 cosine</td><td>score, rank, nearest capability ID</td></tr><tr><td>BGE-M3 dense</td><td>Ollama에 capability summary와 title 문자열만</td><td>capability 1회, title 128건 batch embedding; 로컬 L2·최대 cosine</td><td>score, rank, nearest capability ID</td></tr><tr><td>Qwen</td><td>승인 capability projection + batch-local item_id + title</td><td>25건 batch, strict 구조 검증, plan_id 로컬 재결합</td><td>relevance, 0..1 score, reason 또는 오류 코드</td></tr></tbody></table></div><p class="note">기관·예산·계약 방식·원문 ID는 population에만 보존한다. prompt·회사 역량 본문·모델 원응답·reasoning은 보고서에 포함하지 않는다.</p></section>

<section id="execution"><h2>4. 실행 성능과 점수</h2><section class="methods">{render_method_cards(methods, results)}</section><h3>점수 분포</h3>{render_score_table(methods, results)}<p class="note">TF-IDF·dense cosine과 Qwen 점수는 같은 확률이 아니다. 각 방법 내부 rank에만 쓴다.</p><h3>capability 귀속 분포</h3>{render_capability_table(methods, results, top_k)}</section>
<section id="candidates"><h2>5. 후보 중복과 고유 발견</h2>{render_overlap(methods, results, top_k)}<div class="callout warning"><strong>해석:</strong> 고유 후보는 좋은 후보라는 뜻이 아니다. 사람 relevance·우선순위 라벨로 유효 발견과 노이즈를 구분해야 한다.</div></section>
<section id="qwen"><h2>6. Qwen 판정과 실패 분석</h2>{render_qwen(qwen, top_k)}</section>
<section id="scale"><h2>7. 1,200·2,000건 예상시간</h2>{render_projection(methods, results, len(population['items']))}</section>

<section id="decision"><h2>8. 고도화 대안과 의사결정 게이트</h2><h3>대안 비교</h3><div class="table-scroll"><table><thead><tr><th>대안</th><th>장점</th><th>현재 위험</th><th>다음 검증</th></tr></thead><tbody>
<tr><td>TF-IDF 단독</td><td>가장 빠르고 결정적, 모델 서버 불필요</td><td>동의어·의미 유사 사업 누락 가능</td><td>사람 precision@50·감사 표본</td></tr><tr><td>dense 단독</td><td>의미 유사성을 짧은 시간에 전수 계산</td><td>점수 미보정, capability 문구 편향</td><td>TF-IDF 고유 관련 후보 누락 확인</td></tr><tr><td>TF-IDF∪dense</td><td>서로의 고유 후보 보존</td><td>검토량 증가, 합집합 노이즈 미측정</td><td>블라인드 사람 라벨</td></tr><tr><td>Qwen 전수</td><td>관련성·점수·짧은 이유 구조화</td><td>{qwen_failures:,}건 truncation과 긴 시간</td><td>batch/출력/reasoning 한 변수씩 실험</td></tr><tr><td>저비용 후보 → Qwen</td><td>{escape(staged_text)}</td><td>1단계 누락 회복 불가, 비교 범위 변경</td><td>별도 fifth-method로 사람 라벨 비교</td></tr><tr><td>ColBERT</td><td>token-level late interaction</td><td>환경·시간·메모리 미측정</td><td>동일 997건·고정 revision 실행</td></tr></tbody></table></div>
<h3>권장 실행 순서</h3><ol><li><strong>Qwen coverage 복구:</strong> 같은 raw·prompt·digest에서 batch 크기, 출력 상한, reasoning을 한 번에 하나만 바꾼 새 run을 만든다. smoke는 별도 ID로 1~2 batch만 실행한다.</li><li><strong>안전한 진행 계측:</strong> 본문 없이 batch 번호·상태·latency·token·done reason·오류 코드만 기록한다. 긴 실행은 불변 batch shard와 최종 manifest로 구분하되 자동 fallback하지 않는다.</li><li><strong>ColBERT 실행:</strong> 같은 title/capability와 997건에서 fixed revision으로 실행한다.</li><li><strong>사람 정답:</strong> 모든 방법이 전수 coverage를 가진 뒤 Top {top_k} 합집합과 합집합 밖 결정적 감사 50건을 블라인드 검토한다. 현재 TF-IDF∪dense는 {union_count}건이지만 새 전체 방법 결과로 다시 산출한다.</li><li><strong>지표:</strong> precision@50, 관련·높음, 고유 관련 발견, 감사 표본 관련, 상대 회수율, 시간·실패율을 함께 본다. 전체 recall은 계산하지 않는다.</li><li><strong>승인:</strong> 고정 표본·사람 정답·재현 지표·담당자 승인 전 정책을 활성화하지 않는다.</li></ol>
<h3>현재 게이트</h3><table><thead><tr><th>게이트</th><th>상태</th><th>근거</th><th>결정</th></tr></thead><tbody><tr><td>수집 완전성</td><td class="gate-pass">충족</td><td>{len(population['items']):,}건, raw {run['collection']['page_count']} page</td><td>재사용 가능</td></tr><tr><td>최소 payload</td><td class="gate-pass">충족</td><td>title 하나</td><td>현 범위 유지</td></tr><tr><td>TF-IDF coverage</td><td class="gate-pass">충족</td><td>{results['tfidf']['metrics']['success_count']:,}/{len(population['items']):,}</td><td>사람 평가 후보</td></tr><tr><td>dense coverage</td><td class="gate-pass">충족</td><td>{results['bge_m3_dense']['metrics']['success_count']:,}/{len(population['items']):,}</td><td>사람 평가 후보</td></tr><tr><td>Qwen coverage</td><td class="gate-fail">미달</td><td>{qwen['metrics']['success_count'] if qwen else 0:,}/{len(population['items']):,}</td><td>새 run 필요</td></tr><tr><td>사람 정답</td><td class="gate-hold">미측정</td><td>labels 없음</td><td>우열 보류</td></tr><tr><td>ColBERT</td><td class="gate-hold">미실행</td><td>환경 준비 대기</td><td>정식 비교 미완료</td></tr><tr><td>운영 활성화</td><td class="gate-fail">차단</td><td>품질 승인 미완료</td><td>자동 활성화 금지</td></tr></tbody></table></section>

<section id="top"><h2>9. Top 후보 상세</h2><p class="note">후보 검토용이며 점수만으로 참여를 결정하지 않는다. Qwen Top 후보는 실패 {qwen_failures:,}건을 제외한 순위다.</p>{render_top_tables(methods, results, population)}</section>
<section id="binding"><h2>10. 재현성·보안 binding</h2>{render_bindings(methods, results)}<ul><li>population과 results는 같은 SHA-256과 전체 plan_id coverage를 검증했다.</li><li>Ollama 모델은 exact digest를 확인하고 자동 fallback하지 않는다.</li><li>API key, prompt 본문, capability 본문, 모델 원응답·reasoning은 포함하지 않는다.</li><li>HTML은 외부 script·font·image 없는 자체완결 파생 산출물이다.</li></ul></section>
<footer>population SHA-256: <span class="hash">{escape(population['population_sha256'])}</span><br>raw input SHA-256: <span class="hash">{escape(run['input_sha256'])}</span><br>methods config SHA-256: <span class="hash">{escape(run['config']['methods_sha256'])}</span><br>company capability projection SHA-256: <span class="hash">{escape(run['model_payload']['company_capabilities_sha256'])}</span></footer>
</main></body></html>"""


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
        if not OUTPUT_NAME_PATTERN.fullmatch(args.output_name):
            raise ExperimentError("report_path_rejected", "보고서 파일명은 안전한 .html 이름이어야 합니다")
        requested_output_dir = args.output_dir
        if requested_output_dir.is_symlink():
            raise ExperimentError("report_path_rejected", "보고서 디렉터리 symlink는 허용하지 않습니다")
        output = requested_output_dir.resolve() / args.output_name
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(render_report(run, population, methods, results))
        except FileExistsError as exc:
            raise ExperimentError("artifact_exists", f"기존 {args.output_name}을 덮어쓸 수 없습니다") from exc
        except OSError as exc:
            raise ExperimentError("artifact_write_failed", "상세 보고서를 쓸 수 없습니다") from exc
        print(json.dumps({"status": "complete", "run_id": run["run_id"], "population_count": len(population["items"]), "methods": list(methods), "report": str(output)}, ensure_ascii=False))
        return 0
    except ExperimentError as exc:
        print(json.dumps({"status": "failed", "error_code": exc.code}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
