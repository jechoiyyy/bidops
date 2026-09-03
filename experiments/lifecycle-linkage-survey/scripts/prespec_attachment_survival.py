"""사전규격 첨부 URL의 수명을 나이별 횡단면으로 측정한다 (D-9).

T-20의 조건부 다운로드는 "나중에 추적 대상이 되면 그때 받는다"가 전제다. 그 사이
첨부 URL이 죽으면 원문을 영영 못 받는다. 수명은 측정된 적이 없다.

새로 수집하지 않는다. T-2c 채움 곡선이 나이 3·9·17·31·60·150일 코호트의 원문 페이지를
이미 보존해 두었으므로, 그 안의 `specDocFileUrl1~5`를 오늘 호출하면 수명 곡선이 즉시
나온다. 나이 150일 URL이 오늘도 200이면 수명 문제는 사실상 없다.

이것은 횡단면이다. `20260831-order-plan-longitudinal.md`가 보였듯 횡단면과 종단은
어긋날 수 있다. 2026-09-13에 2026-08-30 표본 30건을 재호출하는 종단 점이 교차 확인이며
이 스크립트는 그 판단을 대신하지 않는다.

본문 바이트는 저장하지 않는다. sha256과 앞 16바이트 magic만 남긴다. 담당자 필드
(`ofclNm`, `ofclTelNo`)는 파생 산출물에 복사하지 않는다.

    python3 experiments/lifecycle-linkage-survey/scripts/prespec_attachment_survival.py --dry-run
    python3 experiments/lifecycle-linkage-survey/scripts/prespec_attachment_survival.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

SCHEMA_VERSION = "bidops.prespec-attachment-survival.v1"
DEFAULT_SOURCE = Path("data/experiments/lifecycle-linkage-survey/20260831-prespec-fill-curve")
DEFAULT_OUT = Path("data/experiments/prespec-attachment-survival/20260831")
URL_FIELDS = tuple(f"specDocFileUrl{index}" for index in range(1, 6))
ALLOWED_HOST = "www.g2b.go.kr"
USER_AGENT = "bidops-attachment-survival-probe/1.0"
SAMPLE_PER_AGE = 30
SEED = 20260831
PACE_SECONDS = 1.0
TIMEOUT_SECONDS = 30.0
# 첨부 실측에서 50MiB 초과는 0건이었다. 그보다 크면 읽지 않고 끊는다.
MAX_READ_BYTES = 50 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """redirect를 따르지 않는다. 실측에서 redirect는 0건이었다."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class Target:
    age_days: int
    window_from: str
    bf_spec_rgst_no: str
    file_seq: int
    url: str


def _load_manifest(source: Path) -> list[dict[str, Any]]:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    return list(manifest["windows"])


def _iter_items(source: Path, slug: str):
    for page in sorted((source / "raw" / slug).glob("*.json")):
        payload = json.loads(page.read_text(encoding="utf-8"))
        body = payload["payload"]["response"]["body"]
        for item in body.get("items") or []:
            yield item


def _targets_for_window(source: Path, window: dict[str, Any]) -> list[Target]:
    """이 나이 코호트가 가진 첨부 URL 전체를 모은다."""

    found: list[Target] = []
    for item in _iter_items(source, window["slug"]):
        registration = (item.get("bfSpecRgstNo") or "").strip()
        for index, field in enumerate(URL_FIELDS, start=1):
            url = (item.get(field) or "").strip()
            if not url:
                continue
            host = urllib.parse.urlsplit(url).netloc
            if host != ALLOWED_HOST:
                # 승인 host 밖은 호출하지 않는다. 관측되면 보고 대상이다.
                print(f"  !! 허용되지 않은 host를 건너뜀: {host}", file=sys.stderr)
                continue
            found.append(
                Target(
                    age_days=int(window["age_days"]),
                    window_from=str(window["from"]),
                    bf_spec_rgst_no=registration,
                    file_seq=index,
                    url=url,
                )
            )
    return found


def _decode_filename(disposition: str | None) -> tuple[str | None, str | None]:
    """`filename=` 값이 percent-encoding된 비표준 형태다. 명시적으로 디코드한다."""

    if not disposition:
        return None, None
    marker = "filename="
    start = disposition.find(marker)
    if start < 0:
        return None, None
    raw = disposition[start + len(marker) :].strip().rstrip(";").strip('"')
    try:
        return raw, urllib.parse.unquote(raw, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return raw, None


def _probe(target: Target, opener: urllib.request.OpenerDirector) -> dict[str, Any]:
    record: dict[str, Any] = {
        "age_days": target.age_days,
        "window_from": target.window_from,
        "bfSpecRgstNo": target.bf_spec_rgst_no,
        "fileSeq": target.file_seq,
    }
    request = urllib.request.Request(target.url, headers={"User-Agent": USER_AGENT})
    started = time.monotonic()
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_READ_BYTES + 1)
            truncated = len(body) > MAX_READ_BYTES
            if truncated:
                body = body[:MAX_READ_BYTES]
            raw_name, decoded_name = _decode_filename(response.headers.get("Content-Disposition"))
            record.update(
                {
                    "alive": True,
                    "http_status": int(response.status),
                    "redirected": False,
                    "content_type": response.headers.get("Content-Type"),
                    "content_length_header": response.headers.get("Content-Length"),
                    "bytes_read": len(body),
                    "over_max_read": truncated,
                    "filename_percent_encoded": raw_name,
                    "filename_utf8_decoded": decoded_name,
                    "magic_hex_16": body[:16].hex(),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
    except urllib.error.HTTPError as exc:
        # redirect도 여기로 온다. 따르지 않고 상태만 남긴다.
        record.update(
            {
                "alive": False,
                "http_status": int(exc.code),
                "redirected": 300 <= exc.code < 400,
                "error_kind": "http_status",
                "location": exc.headers.get("Location") if exc.headers else None,
            }
        )
    except Exception as exc:  # 네트워크·TLS·timeout을 형태만 남긴다
        record.update(
            {
                "alive": False,
                "http_status": None,
                "error_kind": type(exc).__name__,
                "error_summary": str(exc)[:200],
            }
        )
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return record


def _summarise(items: list[dict[str, Any]], windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_age: dict[int, list[dict[str, Any]]] = {}
    for record in items:
        by_age.setdefault(record["age_days"], []).append(record)

    rows: list[dict[str, Any]] = []
    for window in windows:
        age = int(window["age_days"])
        records = by_age.get(age, [])
        if not records:
            continue
        alive = [record for record in records if record.get("alive")]
        statuses: dict[str, int] = {}
        for record in records:
            key = str(record.get("http_status") or record.get("error_kind") or "unknown")
            statuses[key] = statuses.get(key, 0) + 1
        rows.append(
            {
                "age_days": age,
                "window_from": window["from"],
                "window_to_exclusive": window["to_exclusive"],
                "probed": len(records),
                "alive": len(alive),
                "alive_rate": round(len(alive) / len(records), 4),
                "status_counts": statuses,
                "median_bytes": (
                    sorted(record["bytes_read"] for record in alive)[len(alive) // 2] if alive else None
                ),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample", type=int, default=SAMPLE_PER_AGE)
    parser.add_argument("--pace-seconds", type=float, default=PACE_SECONDS)
    parser.add_argument("--dry-run", action="store_true", help="표본만 뽑고 호출하지 않는다")
    args = parser.parse_args()

    windows = _load_manifest(args.source)
    rng = random.Random(SEED)
    population: dict[int, int] = {}
    sampled: list[Target] = []
    for window in windows:
        targets = _targets_for_window(args.source, window)
        population[int(window["age_days"])] = len(targets)
        size = min(args.sample, len(targets))
        sampled.extend(rng.sample(targets, size))
        print(f"나이 {window['age_days']:>3}일  URL {len(targets):>5}개 → 표본 {size}개")

    print(f"\n총 호출 대상 {len(sampled)}개, 간격 {args.pace_seconds}초")
    if args.dry_run:
        print("--dry-run이므로 호출하지 않는다.")
        return 0

    opener = urllib.request.build_opener(_NoRedirect)
    items: list[dict[str, Any]] = []
    for index, target in enumerate(sampled, start=1):
        if index > 1:
            time.sleep(args.pace_seconds)
        record = _probe(target, opener)
        items.append(record)
        mark = "OK" if record.get("alive") else "XX"
        print(
            f"[{index:>3}/{len(sampled)}] {mark} age={target.age_days:>3} "
            f"{target.bf_spec_rgst_no} seq={target.file_seq} "
            f"status={record.get('http_status')} bytes={record.get('bytes_read')}"
        )

    summary = _summarise(items, windows)
    args.out.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": SCHEMA_VERSION,
        "collected_at": "2026-08-31",
        "design": "cross-sectional",
        "source": str(args.source),
        "population_urls_by_age": population,
        "sample": {"size_per_age": args.sample, "method": f"random.Random({SEED}).sample"},
        "note": "본문 바이트는 저장하지 않는다. sha256과 앞 16바이트 magic만 남긴다.",
        "summary": summary,
        "items": items,
    }
    destination = args.out / "survival.json"
    destination.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    print("\n나이별 생존율")
    for row in summary:
        print(
            f"  {row['age_days']:>3}일  {row['alive']:>2}/{row['probed']:<2} "
            f"= {row['alive_rate'] * 100:5.1f}%   {row['status_counts']}"
        )
    print(f"\n기록: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
