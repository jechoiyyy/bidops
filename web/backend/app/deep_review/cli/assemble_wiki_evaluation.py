"""Join frozen human annotations to completed evaluation traces by question ID."""

import argparse
import json
from pathlib import Path

from ..schemas.wiki_quality import Evaluation


def assemble(annotations, traces):
    by_id = {trace["case_id"]: trace for trace in traces}
    cases = annotations["cases"]
    if len(by_id) != len(traces) or set(by_id) != {case["id"] for case in cases}:
        raise ValueError("one trace per reviewed case required")
    joined = []
    for case in cases:
        trace = by_id[case["id"]]
        for key in ("bundle_sha256", "work_units_sha256"):
            if trace[key] != annotations[key]:
                raise ValueError("snapshot mismatch")
        if trace["answer"] != case["answer"]:
            raise ValueError("reviewed answer differs from recorded answer")
        joined.append({**case, "read_pages": trace["read_pages"], "tool_calls": trace["tool_calls"]})
    return Evaluation.model_validate({**annotations, "cases": joined})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("trace", type=Path, nargs="+")
    args = parser.parse_args()
    result = assemble(json.loads(args.annotations.read_text(encoding="utf-8")),
                      [json.loads(path.read_text(encoding="utf-8")) for path in args.trace])
    with args.output.open("x", encoding="utf-8") as output:
        output.write(result.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
