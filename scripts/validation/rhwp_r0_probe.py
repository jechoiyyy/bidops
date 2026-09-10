import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


RHWP = Path("/app/web/backend/app/deep_review/document_mcp/vendor/rhwp/bin/rhwp")
INPUT = Path("/input")
OUTPUT = Path("/out")
SAMPLES = (
    ("notice-142", "notice-142.hwpx", False),
    ("notice-10-rfp", "notice-10-rfp.hwp", True),
    ("notice-10-sow", "notice-10-sow.hwp", True),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numeric_pids() -> list[int]:
    return [int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit()]


def status(pid: int) -> tuple[int, int]:
    try:
        fields = {}
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            key, _, value = line.partition(":")
            fields[key] = value.strip()
        return int(fields.get("VmRSS", "0 kB").split()[0]), int(fields.get("PPid", "0"))
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        return 0, -1


def descendants(root: int, pids: list[int]) -> set[int]:
    parents = {pid: status(pid)[1] for pid in pids}
    selected = {root}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in selected and pid not in selected:
                selected.add(pid)
                changed = True
    return selected


def run_limited(command: list[str], stdout_path: Path, stderr_path: Path) -> dict:
    started = time.perf_counter()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=stdout_path.parent)
        max_rss_kib = 0
        max_tree_pids = 0
        max_container_pids = 0
        while process.poll() is None:
            pids = numeric_pids()
            tree = descendants(process.pid, pids)
            rss = sum(status(pid)[0] for pid in tree)
            max_rss_kib = max(max_rss_kib, rss)
            max_tree_pids = max(max_tree_pids, len(tree))
            max_container_pids = max(max_container_pids, len(pids))
            time.sleep(0.01)
        elapsed = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(f"command_failed:{command[1]}:{process.returncode}")
    return {
        "seconds": round(elapsed, 3),
        "max_rss_kib": max_rss_kib,
        "max_tree_pids": max_tree_pids,
        "max_container_pids": max_container_pids,
        "stdout_bytes": stdout_path.stat().st_size,
    }


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError("manifest_not_object")
    return value


def item_metrics(document: dict) -> dict:
    kinds: dict[str, int] = {}
    para_indexes: set[tuple[int, int]] = set()
    pages = document.get("pages", [])
    for page in pages:
        section = int(page.get("section", 0))
        for column in page.get("columns", []):
            for item in column.get("items", []):
                kind = str(item.get("kind"))
                kinds[kind] = kinds.get(kind, 0) + 1
                if isinstance(item.get("paraIndex"), int) and not item.get("isEndnote", False):
                    para_indexes.add((section, item["paraIndex"]))
    return {
        "item_count": sum(kinds.values()),
        "item_kinds": dict(sorted(kinds.items())),
        "unique_body_para_indexes": len(para_indexes),
    }


def main() -> None:
    report = {
        "schema": "bidops.rhwp-r0-baseline-metrics.v1",
        "image": "bidops-rdp-r0:20260910",
        "limits": {"network": "none", "uid_gid": "1000:1000", "memory_bytes": 1073741824, "pids": 128, "cap_drop": "ALL", "no_new_privileges": True},
        "samples": [],
    }
    for label, filename, needs_hwpx in SAMPLES:
        source = INPUT / filename
        sample = {"sample": label, "input_bytes": source.stat().st_size, "input_sha256": sha256(source), "runs": []}
        for run_number in (1, 2):
            run_dir = OUTPUT / label / f"run-{run_number}"
            run_dir.mkdir(parents=True, exist_ok=True)
            run = {"run": run_number, "commands": {}}
            if needs_hwpx:
                converted = run_dir / "converted.hwpx"
                manifest_path = run_dir / "export-hwpx.json"
                metrics = run_limited(
                    [str(RHWP), "export-hwpx", str(source), str(converted), "--verify", "--verify-pages", "--json"],
                    manifest_path,
                    run_dir / "export-hwpx.stderr",
                )
                manifest = read_json(manifest_path)
                metrics.update({
                    "artifact_bytes": converted.stat().st_size,
                    "artifact_sha256": sha256(converted),
                    "verify_identical": manifest.get("verify", {}).get("identical"),
                    "verify_diff_count": manifest.get("verify", {}).get("diffCount"),
                    "verify_pages_identical": manifest.get("verifyPages", {}).get("identical"),
                    "verify_pages_before": manifest.get("verifyPages", {}).get("before"),
                    "verify_pages_after": manifest.get("verifyPages", {}).get("after"),
                })
                run["commands"]["export_hwpx"] = metrics

            pdf = run_dir / "output.pdf"
            pdf_manifest_path = run_dir / "export-pdf.json"
            pdf_metrics = run_limited(
                [str(RHWP), "export-pdf", str(source), "-o", str(pdf), "--backend", "svg", "--fallback-serif", "NanumMyeongjo", "--fallback-sans", "NanumGothic", "--fallback-mono", "NanumGothicCoding", "--json"],
                pdf_manifest_path,
                run_dir / "export-pdf.stderr",
            )
            pdf_manifest = read_json(pdf_manifest_path)
            pdfinfo = subprocess.run(["pdfinfo", str(pdf)], check=True, capture_output=True, text=True).stdout
            pdfinfo_pages = int(next(line.split(":", 1)[1] for line in pdfinfo.splitlines() if line.startswith("Pages:")))
            pdf_metrics.update({
                "artifact_bytes": pdf.stat().st_size,
                "artifact_sha256": sha256(pdf),
                "page_count": pdf_manifest.get("pageCount"),
                "rendered_count": pdf_manifest.get("renderedCount"),
                "pdfinfo_pages": pdfinfo_pages,
            })
            run["commands"]["export_pdf"] = pdf_metrics

            text_path = run_dir / "export-text.json"
            text_metrics = run_limited(
                [str(RHWP), "export-text", str(source), "--json"],
                text_path,
                run_dir / "export-text.stderr",
            )
            text_manifest = read_json(text_path)
            text_metrics.update({
                "stdout_sha256": sha256(text_path),
                "page_count": text_manifest.get("pageCount"),
                "pages_length": len(text_manifest.get("pages", [])),
                "omitted_count": text_manifest.get("omittedCount"),
                "truncated": text_manifest.get("truncated", False),
            })
            run["commands"]["export_text"] = text_metrics

            pages_path = run_dir / "dump-pages.json"
            pages_metrics = run_limited(
                [str(RHWP), "dump-pages", str(source), "--json"],
                pages_path,
                run_dir / "dump-pages.stderr",
            )
            pages_manifest = read_json(pages_path)
            pages_metrics.update({
                "stdout_sha256": sha256(pages_path),
                "page_count": pages_manifest.get("pageCount"),
                "pages_length": len(pages_manifest.get("pages", [])),
                **item_metrics(pages_manifest),
            })
            run["commands"]["dump_pages"] = pages_metrics
            run["total_seconds"] = round(sum(item["seconds"] for item in run["commands"].values()), 3)
            sample["runs"].append(run)

        first, second = sample["runs"]
        compared = ["export_pdf", "export_text", "dump_pages"] + (["export_hwpx"] if needs_hwpx else [])
        determinism = {}
        for command in compared:
            key = "artifact_sha256" if command in {"export_pdf", "export_hwpx"} else "stdout_sha256"
            determinism[command] = first["commands"][command][key] == second["commands"][command][key]
        sample["determinism"] = determinism
        report["samples"].append(sample)
    json.dump(report, sys.stdout, ensure_ascii=True, sort_keys=True, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
