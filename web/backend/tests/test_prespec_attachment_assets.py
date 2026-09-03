"""T-20a provider attachment acquisition boundary tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from urllib.parse import quote_from_bytes
from urllib.request import HTTPCookieProcessor

import pytest

from app.core.config import Settings
from app.services import assets
from app.services.document_bundles import API_ERROR_CODES, stable_api_error


def test_measured_g2b_filename_header_decodes_percent_encoded_utf8() -> None:
    header = "attachment;filename=%EC%A0%9C%EC%95%88%EC%9A%94%EC%B2%AD%EC%84%9C.hwp;"

    assert assets.parse_content_disposition_filename(header) == "제안요청서.hwp"


def test_measured_filename_preserves_spaces_brackets_parentheses_and_middle_dots() -> None:
    filename = "[과업지시서 및 제안요청서] 한국해양과학기술원 해양위성센터 전산장비 통합유지보수_.hwp"
    with_punctuation = f"{filename[:-4]} · ㆍ (부록) [v1].hwp"
    header = f"attachment;filename={quote_from_bytes(with_punctuation.encode('utf-8'))};"

    assert assets.parse_content_disposition_filename(header) == with_punctuation


def test_rfc5987_filename_star_is_preferred_and_decoded() -> None:
    header = "attachment; filename=wrong.pdf; filename*=UTF-8''%EA%B3%B5%EA%B3%A0%EC%84%9C.pdf;"

    assert assets.parse_content_disposition_filename(header) == "공고서.pdf"


def test_unsupported_rfc5987_charset_falls_back_to_filename() -> None:
    header = "attachment; filename*=EUC-KR''%B0%F8%B0%ED%BC%AD.pdf; filename=fallback.pdf;"

    assert assets.parse_content_disposition_filename(header) == "fallback.pdf"


@pytest.mark.parametrize("value", ["%B0%F8%B0%ED%BC%AD.pdf", "%FF.pdf"])
def test_non_utf8_or_invalid_percent_encoding_is_not_guessed(value: str) -> None:
    header = f"attachment;filename={value};"

    assert assets.parse_content_disposition_filename(header) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("attachment;filename=../../etc/passwd;", "passwd"),
        (r"attachment;filename=C:\\x\\y.hwp;", "y.hwp"),
        ("attachment;filename=%2E%2E%2Fetc%2Frequest.pdf;", "request.pdf"),
    ],
)
def test_filename_path_components_are_removed(header: str, expected: str) -> None:
    assert assets.parse_content_disposition_filename(header) == expected


@pytest.mark.parametrize("value", ["bad\x00.pdf", "bad\x1f.pdf", "bad\x7f.pdf", "bad\x80.pdf", "bad\x9f.pdf"])
def test_filename_controls_and_nul_are_rejected(value: str) -> None:
    assert assets.parse_content_disposition_filename(f"attachment;filename={value};") is None


def test_filename_length_is_limited_without_checking_extension() -> None:
    assert assets.parse_content_disposition_filename("attachment;filename=readme;") == "readme"
    assert assets.parse_content_disposition_filename(f"attachment;filename={'a' * 256};") is None


def test_missing_header_or_filename_parameter_returns_none() -> None:
    assert assets.parse_content_disposition_filename(None) is None
    assert assets.parse_content_disposition_filename("") is None
    assert assets.parse_content_disposition_filename("attachment;") is None


class StubConnector:
    source_system = "g2b"

    def __init__(self, response: assets.ProviderResponse) -> None:
        self.response = response

    def fetch(self, _url: str) -> assets.ProviderResponse:
        return self.response


def test_acquire_uses_connector_suggested_filename_when_caller_omits_one(tmp_path: Path) -> None:
    connector = StubConnector(assets.ProviderResponse(b"provider bytes", "https://files.example.test/actual", "suggested.pdf"))

    asset = assets.acquire_provider_attachment(
        source_system="g2b",
        source_url="https://files.example.test/download",
        connectors={"g2b": connector},  # type: ignore[dict-item]
        root=tmp_path,
    )

    assert asset.filename == "suggested.pdf"


def test_acquire_prefers_explicit_filename_over_connector_suggestion(tmp_path: Path) -> None:
    connector = StubConnector(assets.ProviderResponse(b"provider bytes", "https://files.example.test/actual", "suggested.pdf"))

    asset = assets.acquire_provider_attachment(
        source_system="g2b",
        source_url="https://files.example.test/download",
        filename="explicit.pdf",
        connectors={"g2b": connector},  # type: ignore[dict-item]
        root=tmp_path,
    )

    assert asset.filename == "explicit.pdf"


@pytest.mark.parametrize(
    "response",
    [
        assets.ProviderResponse(b"provider bytes", "https://files.example.test/actual", "입찰서식.docx"),
        assets.ProviderResponse(b"provider bytes", "https://files.example.test/actual", None),
    ],
)
def test_acquire_rejects_unsupported_or_missing_filename_as_terminal_error(tmp_path: Path, response: assets.ProviderResponse) -> None:
    connector = StubConnector(response)

    with pytest.raises(assets.AssetError) as error:
        assets.acquire_provider_attachment(
            source_system="g2b",
            source_url="https://files.example.test/download",
            connectors={"g2b": connector},  # type: ignore[dict-item]
            root=tmp_path,
        )

    assert error.value.code == "unsupported_extension"


def test_unsupported_extension_is_internal_and_maps_to_existing_api_error() -> None:
    assert "unsupported_extension" not in API_ERROR_CODES
    code, message = stable_api_error("unsupported_extension")

    assert code == "unsafe_document"
    assert message == "문서 안전 검사를 통과하지 못했습니다"


def test_g2b_attachment_connectors_fail_closed_without_enablement_or_hosts() -> None:
    assert assets.g2b_attachment_connectors(Settings(g2b_attachment_enabled=False, g2b_attachment_allowed_hosts="g2b.example")) == {}
    assert assets.g2b_attachment_connectors(Settings(g2b_attachment_enabled=True, g2b_attachment_allowed_hosts="")) == {}


def test_g2b_attachment_connectors_use_only_configured_hosts_and_timeout() -> None:
    settings = Settings(
        g2b_attachment_enabled=True,
        g2b_attachment_allowed_hosts=" g2b.example, files.example ",
        g2b_attachment_timeout_seconds=12.5,
    )

    connectors = assets.g2b_attachment_connectors(settings)

    assert set(connectors) == {"g2b"}
    assert connectors["g2b"].allowed_hosts == frozenset({"g2b.example", "files.example"})
    assert connectors["g2b"].timeout_seconds == 12.5


class FakeNativeResponse:
    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        self._read = False
        self.headers = headers

    def __enter__(self) -> "FakeNativeResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def geturl(self) -> str:
        return "https://files.example.test/final"

    def read(self, _size: int) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body


def test_native_connector_extracts_header_filename_and_does_not_retain_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"provider bytes"
    requests: list[object] = []
    handler_sets: list[tuple[object, ...]] = []

    class FakeOpener:
        def open(self, request: object, timeout: float) -> FakeNativeResponse:
            assert timeout > 0
            requests.append(request)
            return FakeNativeResponse(
                body,
                {
                    "Content-Length": str(len(body)),
                    "Content-Disposition": "attachment;filename=%EC%A0%9C%EC%95%88%EC%9A%94%EC%B2%AD%EC%84%9C.hwp;",
                    "Set-Cookie": "session=must-not-persist",
                },
            )

    def fake_build_opener(*handlers: object) -> FakeOpener:
        handler_sets.append(handlers)
        return FakeOpener()

    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    monkeypatch.setattr(assets, "build_opener", fake_build_opener)
    connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}))

    first = connector.fetch("https://files.example.test/request")
    second = connector.fetch("https://files.example.test/request")

    assert first.body == body
    assert first.final_url == "https://files.example.test/final"
    assert first.suggested_filename == "제안요청서.hwp"
    assert second.suggested_filename == first.suggested_filename
    assert len(requests) == 2
    assert all("cookie" not in {str(key).casefold() for key in request.headers} for request in requests)  # type: ignore[attr-defined]
    assert all(not any(isinstance(handler, HTTPCookieProcessor) for handler in handlers) for handlers in handler_sets)


def test_provider_response_is_frozen() -> None:
    response = assets.ProviderResponse(b"body", "https://files.example.test/final")

    with pytest.raises(FrozenInstanceError):
        response.body = b"changed"  # type: ignore[misc]
