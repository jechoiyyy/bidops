"""Scratch converter protocol tests: bounded, atomic, credential-free."""

import json
import hashlib
from pathlib import Path

import pytest

from app.deep_review.document_mcp.errors import DocumentProcessingError
from app.deep_review.services import document_converter
from app.deep_review.services.document_converter import ScratchDocumentProcessor
from app.deep_review.document_protocol import ALLOWED_METADATA, ScratchProtocolError, convert_one, write_request


FIXTURE = Path(__file__).parents[1] / "fixtures" / "document_bundles" / "safe.pdf"


def clean_scan(content: bytes) -> dict[str, str]:
    return {
        "scanner": "clamav",
        "version": "clamd-instream-v1",
        "sha256": hashlib.sha256(content).hexdigest(),
        "verdict": "clean",
    }


def test_scratch_protocol_processes_structure_without_request_or_credentials(tmp_path: Path):
    request = write_request(
        tmp_path,
        request_id="11111111-1111-4111-8111-111111111111",
        content=FIXTURE.read_bytes(),
        media_type="application/pdf",
        original_filename="safe.pdf",
        options={"ocr": False, "render_pages": False},
        scan=clean_scan(FIXTURE.read_bytes()),
    )
    envelope = json.loads(request.read_text(encoding="utf-8"))
    assert set(envelope) == ALLOWED_METADATA
    assert not any(token in json.dumps(envelope).lower() for token in ("password", "secret", "token", "authorization", "credential"))
    assert convert_one(tmp_path) is True
    result = json.loads((tmp_path / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "succeeded"
    assert "original_bytes" not in result and "request_headers" not in result
    assert FIXTURE.read_bytes() not in (tmp_path / "results" / f"{request.stem}.json").read_bytes()
    assert "structure" in result and result["structure"]["source_sha256"]


def test_scratch_protocol_rejects_credential_bearing_or_traversal_envelopes(tmp_path: Path):
    request = write_request(
        tmp_path,
        request_id="22222222-2222-4222-8222-222222222222",
        content=FIXTURE.read_bytes(),
        media_type="application/pdf",
        original_filename="safe.pdf",
        scan=clean_scan(FIXTURE.read_bytes()),
    )
    envelope = json.loads(request.read_text(encoding="utf-8"))
    envelope["credential"] = "must-not-cross"
    request.write_text(json.dumps(envelope), encoding="utf-8")
    assert convert_one(tmp_path) is True
    result = json.loads((tmp_path / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert "must-not-cross" not in json.dumps(result)

    with pytest.raises(ScratchProtocolError):
        write_request(
            tmp_path,
            request_id="33333333-3333-4333-8333-333333333333",
            content=FIXTURE.read_bytes(),
            media_type="application/pdf",
            original_filename="../escape.pdf",
        )


def test_trusted_scan_verdicts_gate_production_spooling(tmp_path: Path):
    content = FIXTURE.read_bytes()
    clean = ScratchDocumentProcessor(tmp_path / "clean", clamav_checker=lambda _content: True)
    assert clean.clamav_checker(content) is True

    with pytest.raises(DocumentProcessingError, match="malware"):
        ScratchDocumentProcessor(tmp_path / "infected", clamav_checker=lambda _content: False).process(content, "application/pdf")

    def unavailable(_content: bytes) -> bool:
        raise OSError("scanner unavailable")

    with pytest.raises(DocumentProcessingError, match="malware"):
        ScratchDocumentProcessor(tmp_path / "unavailable", clamav_checker=unavailable).process(content, "application/pdf")

    request = write_request(
        tmp_path / "tamper",
        request_id="44444444-4444-4444-8444-444444444444",
        content=content,
        media_type="application/pdf",
        original_filename="safe.pdf",
        scan=clean_scan(content),
    )
    (request.parent / f"{request.stem}.bin").write_bytes(b"tampered")
    assert convert_one(tmp_path / "tamper") is True
    result = json.loads((tmp_path / "tamper" / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"


def test_result_consumer_rejects_source_hash_tamper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "result-tamper"
    real_write_request = document_converter.write_request

    def write_bad_result(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        result_path = root / "results" / f"{request.stem}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["structure"]["source_sha256"] = "0" * 64
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return request

    monkeypatch.setattr(document_converter, "write_request", write_bad_result)
    processor = ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True)
    with pytest.raises(DocumentProcessingError) as error:
        processor.process(FIXTURE.read_bytes(), "application/pdf", {"ocr": False, "render_pages": False})
    assert error.value.code == "hash_mismatch"
