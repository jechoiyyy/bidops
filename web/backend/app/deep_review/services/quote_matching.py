"""Resolve presentation-only quote differences back to unchanged source bytes."""
from collections.abc import Mapping, Sequence

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‛": "'", "“": '"', "”": '"', "„": '"'})


def _character(char: str) -> str:
    if "\uff01" <= char <= "\uff5e":
        char = chr(ord(char) - 0xfee0)
    return char.translate(_QUOTES)


def _spacing(char: str) -> bool:
    return char.isspace() or char in "\u200b\ufeff"


def _index(text: str) -> tuple[str, list[int]]:
    chars, positions = [], []
    index = 0
    while index < len(text):
        char = text[index]
        if _spacing(char):
            end = index + 1
            while end < len(text) and _spacing(text[end]):
                end += 1
            previous = chars[-1] if chars else ""
            following = _character(text[end]) if end < len(text) else ""
            # Never turn two numbers or identifiers into one token.
            if previous.isascii() and previous.isalnum() and following.isascii() and following.isalnum():
                chars.append(" "); positions.append(index)
            index = end
            continue
        chars.append(_character(char)); positions.append(index)
        index += 1
    return "".join(chars), positions


def source_quote(quote: str, texts: Sequence[str]) -> str | None:
    """Match within a pinned block/page span; retain words, negation and values."""
    if not quote.strip():
        return None
    if any(quote in text for text in texts):
        return quote
    target, _ = _index(quote)
    if not target:
        return None
    candidates = []
    for text in texts:
        normalized, positions = _index(text)
        start = 0
        while (found := normalized.find(target, start)) >= 0:
            candidates.append(text[positions[found]:positions[found + len(target) - 1] + 1])
            start = found + len(target)
    # Repeated identical source spans are harmless at a pinned page locator.
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None


def page_texts(blocks: Sequence[Mapping]) -> list[str]:
    """Original blocks plus their contiguous page text, in pinned source order.

    Callers must scope blocks to one page first. This uses the same newline
    separator as model input excerpts; no nonblank block may be skipped.
    """
    texts = [row["text"] for row in blocks if isinstance(row.get("text"), str) and row["text"].strip()]
    return [*texts, "\n".join(texts)] if len(texts) > 1 else texts
