"""대본대로 답하는 OpenAI 호환 fake transport. 소켓을 열지 않는다."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any


DECLARED_REVISION = "a" * 64

#: `BIDOPS_VLLM_SCREENING_MODEL`의 기본값. 제품 코드가 아니라 테스트가 쓰는
#: 기대값이며, 설정 기본값과 어긋나면 어댑터 테스트가 그 사실을 먼저 잡는다.
APPROVED_MODEL = "qwen3.8-27B"


def completion(
    value: object,
    *,
    model: str = APPROVED_MODEL,
    finish_reason: str = "stop",
    raw: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """OpenAI chat completion 응답 한 건을 만든다."""

    content = json.dumps(value, ensure_ascii=False) if raw is None else raw
    return {
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        **extra,
    }


class FakeScreeningTransport:
    """`models()`와 `create()`만 갖는 최소 경계.

    대본 항목은 mapping, 예외 인스턴스, 또는 잡아 둔 요청을 받아 그 둘 중
    하나를 돌려주는 callable이다. fake가 일부러 작아서 평범한 테스트가 실수로
    live 호출을 하지 못한다.
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        *,
        model: str = APPROVED_MODEL,
        model_revision: str = DECLARED_REVISION,
        models_document: Mapping[str, Any] | BaseException | Callable[[], Any] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.model = model
        self.model_revision = model_revision
        self.models_document: Any = (
            models_document
            if models_document is not None
            else {"data": [{"id": model, "object": "model"}]}
        )
        self.requests: list[dict[str, Any]] = []
        self.models_calls = 0

    @property
    def generate_requests(self) -> list[dict[str, Any]]:
        return list(self.requests)

    def queue(self, *items: Any) -> None:
        self.responses.extend(items)

    def models(self) -> Mapping[str, Any]:
        self.models_calls += 1
        result = self.models_document() if callable(self.models_document) else self.models_document
        if isinstance(result, BaseException):
            raise result
        if not isinstance(result, Mapping):
            raise AssertionError("fake models document must be a mapping or exception")
        return dict(result)

    def create(self, **request: Any) -> Mapping[str, Any]:
        self.requests.append(dict(request))
        if not self.responses:
            raise AssertionError("fake completion script is exhausted")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(dict(request))
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, Mapping):
            raise AssertionError("fake response must be a mapping or exception")
        return dict(item)


__all__ = ["APPROVED_MODEL", "DECLARED_REVISION", "FakeScreeningTransport", "completion"]
