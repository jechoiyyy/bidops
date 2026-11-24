"""Offline page-read tool for a single wiki QA evaluation, over JSON lines."""

import argparse
import json
from io import StringIO
from pathlib import Path
import sys

from pydantic import TypeAdapter

from ..schemas.wiki_quality import PageId
from ..services.company_wiki import CompanyWiki, WikiError
from ..services.wiki_quality import versions


def record(wiki, case_id, source, replies, trace):
    snapshot = versions(wiki)
    reads = []
    calls = 0
    events = []
    for line in source:
        request = json.loads(line)
        if request.get("tool") == "finish":
            if not isinstance(request.get("answer"), str) or not request["answer"].strip():
                raise ValueError("answer required")
            json.dump(dict(**snapshot, case_id=case_id, read_pages=reads, tool_calls=calls,
                           events=events, answer=request["answer"]), trace, ensure_ascii=False)
            trace.write("\n")
            return
        if request.get("tool") != "Read":
            raise ValueError("expected Read or finish")
        page = TypeAdapter(PageId).validate_python(request["page"])
        calls += 1
        try:
            body = wiki.page(*page.split("/")).body
        except WikiError as exc:
            result = {"error": exc.code}
        else:
            result = {"body": body}
            reads.append(page)
        events.append({"page": page, "success": "body" in result})
        print(json.dumps(result, ensure_ascii=False), file=replies, flush=True)
    raise ValueError("trace ended before finish")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    wiki = CompanyWiki()
    # Keep incomplete sessions out of the completed trace set.
    completed = StringIO()
    record(wiki, args.case_id, sys.stdin, sys.stdout, completed)
    with args.trace.open("x", encoding="utf-8") as output:
        output.write(completed.getvalue())


if __name__ == "__main__":
    main()
