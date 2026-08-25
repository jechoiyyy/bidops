"""A scripted Ollama transport; it never opens a socket."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class FakeOllamaTransport:
    """Capture requests and return scripted ``/api/tags``/``/api/generate`` values.

    A script item may be a mapping response, an exception instance, or a
    callable receiving the captured request and returning either.  The fake is
    intentionally small so ordinary tests cannot accidentally make a live
    network call.
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        *,
        model: str = "qwen3.8:27b",
        digest: str = "a" * 64,
        inspect_response: Mapping[str, Any] | BaseException | Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.model = model
        self.digest = digest
        self.inspect_response: Any = inspect_response if inspect_response is not None else {
            "models": [{"name": model, "model": model, "digest": digest}]
        }
        self.requests: list[dict[str, Any]] = []

    @property
    def generate_requests(self) -> list[dict[str, Any]]:
        return [item for item in self.requests if item["path"] == "/api/generate"]

    def queue(self, *items: Any) -> None:
        self.responses.extend(items)

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        request = {"method": method, "path": path, "payload": None if payload is None else dict(payload), "timeout": timeout}
        self.requests.append(request)
        if path == "/api/tags":
            result = self.inspect_response(request) if callable(self.inspect_response) else self.inspect_response
            if isinstance(result, BaseException):
                raise result
            if not isinstance(result, Mapping):
                raise AssertionError("fake inspect response must be a mapping or exception")
            return dict(result)
        if path != "/api/generate":
            raise AssertionError(f"unexpected fake Ollama path: {path}")
        if not self.responses:
            raise AssertionError("fake Ollama generate script is exhausted")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(request)
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, Mapping):
            raise AssertionError("fake response must be a mapping or exception")
        return dict(item)


__all__ = ["FakeOllamaTransport"]
