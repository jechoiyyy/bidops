#!/usr/bin/env python3
"""아트보드를 브라우저에서 볼 수 있는 단독 HTML로 바꾼다.

캔버스 런타임이 처리하는 <x-dc>·<helmet> 래퍼를 벗기고
<helmet> 안의 <style>을 <head>로 옮긴다. 렌더 결과는 캔버스와 같다.
"""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).parent
OUT = HERE / "_preview"


def main():
    OUT.mkdir(exist_ok=True)
    boards = json.loads((HERE / "canvas.json").read_text(encoding="utf-8"))["artboards"]
    for b in boards:
        src = (HERE / b["file"]).read_text(encoding="utf-8")
        style = re.search(r"<helmet>\s*<style>(.*?)</style>\s*</helmet>", src, re.S).group(1)
        body = re.search(r"</helmet>(.*?)</x-dc>", src, re.S).group(1)
        html = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{b['file']}</title><style>{style}</style></head>"
            f"<body>{body}</body></html>"
        )
        (OUT / b["file"].replace(".dc.html", ".html")).write_text(html, encoding="utf-8")
        print(f"{b['file']} -> _preview/  ({b['w']}x{b['h']})")


if __name__ == "__main__":
    main()
