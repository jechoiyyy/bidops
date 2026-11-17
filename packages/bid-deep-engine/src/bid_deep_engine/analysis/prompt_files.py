"""프롬프트 파일 바이트 읽기(input_hash·prompt_hashes·REV-02 prompts 지문의 원천).

외부 클라이언트(anthropic·httpx)·설정·tracing에 의존하지 않는다. report·regate가 단계 지문을
검증할 때 이 모듈만 import하므로 LLM 클라이언트를 import 수준에서도 끌어오지 않는다(배치 리뷰 A2).
"""

from pathlib import Path

import bid_deep_engine.analysis

PROMPTS_DIR = Path(bid_deep_engine.analysis.__file__).parent / "prompts"


def prompt_bytes(name: str) -> bytes:
    """프롬프트 파일 바이트(input_hash·prompt_hashes의 원천)."""
    return (PROMPTS_DIR / name).read_bytes()
