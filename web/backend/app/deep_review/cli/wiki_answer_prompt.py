"""Render the citation instructions used for file-based wiki QA evaluations."""

import argparse

from pydantic import TypeAdapter

from ..schemas.wiki_quality import PageId


def answer_prompt(question: str, pages: list[str]) -> str:
    allowed = TypeAdapter(list[PageId]).validate_python(pages)
    return (
        "다음 질문에 한국어로 간결하게 답하세요. 허용된 공개 자료 중 필요한 파일만 "
        "한 번에 하나씩 cat 경로 명령으로 읽으세요. 다른 명령·자료·인터넷 사용 금지. "
        "증빙이 부족하면 명확히 보류하세요. 결과는 JSON 객체로 출력하세요. "
        "answer는 실무자가 읽을 답변입니다. 각 사실 뒤에 [읽은 페이지 경로 · 원문 절 제목]을 붙이세요. "
        "claims 배열에는 사실별 text와 citations 배열을 넣으세요. 각 인용의 page에는 "
        "허용 목록에 있는 정확한 경로만, section에는 원문 마크다운 제목에서 # 표시를 뺀 절 이름만, "
        "quote에는 그 절에서 주장을 뒷받침하는 원문 문구를 그대로 넣으세요. "
        "제목이 없는 본문 앞부분만 section을 null로 둡니다. "
        "‘개요’처럼 절 이름만으로 문서를 지정하지 마세요.\n허용된 경로: "
        + ", ".join(allowed) + "\n질문: " + question.strip()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("pages", nargs="+")
    args = parser.parse_args()
    print(answer_prompt(args.question, args.pages))


if __name__ == "__main__":
    main()
