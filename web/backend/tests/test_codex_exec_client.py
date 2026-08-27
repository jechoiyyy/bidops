"""Security and failure-contract coverage for the reference Codex adapter."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from app.services.codex_exec_client import (
    CODEX_STAGE_RESPONSE_SCHEMA,
    CodexExecClient,
    CodexExecInvocationError,
)


def _input() -> dict[str, object]:
    return {
        "notice_id": 17,
        "deep_review_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "stage": "requirements_and_evaluation",
        "slice_index": 0,
        "requirements": [],
    }


def _policy() -> dict[str, object]:
    return {
        "chunking": {"timeout_seconds": 300, "retries": 2},
        "stages": [{"stage": "requirements_and_evaluation", "instruction": "요구사항을 추출한다."}],
    }


def _payload(input_slice: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "bidops.deep-review-stage.v1",
        "deep_review_id": input_slice["deep_review_id"],
        "attempt_id": input_slice["attempt_id"],
        "stage": "requirements_and_evaluation",
        "claims": [], "evidence": [], "unknowns": [], "warnings": [],
    }


def test_codex_exec_is_disabled_and_notice_scoped_by_default():
    with pytest.raises(CodexExecInvocationError) as disabled:
        CodexExecClient().invoke("requirements_and_evaluation", _input(), _policy())
    assert disabled.value.code == "external_provider_disabled"
    with pytest.raises(CodexExecInvocationError) as unapproved:
        CodexExecClient(enabled=True).invoke("requirements_and_evaluation", _input(), _policy())
    assert unapproved.value.code == "external_provider_notice_not_approved"


def test_codex_exec_uses_isolated_tool_free_command_and_scrubbed_environment():
    observed: dict[str, object] = {}

    def runner(command, **kwargs):
        observed.update({"command": command, **kwargs})
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(_payload(_input())), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed","usage":{"input_tokens":11,"output_tokens":7}}\n', "secret stderr")

    client = CodexExecClient(
        enabled=True,
        approved_notice_ids=(17,),
        runner=runner,
        environment={
            "PATH": "/bin", "HOME": "/safe-home", "CODEX_API_KEY": "auth",
            "BIDOPS_DATABASE_URL": "must-not-pass", "BIDOPS_SOURCE_SECRET_KEY": "must-not-pass",
        },
    )
    input_slice = _input()
    result = client.invoke("requirements_and_evaluation", input_slice, _policy())
    command = observed["command"]
    assert isinstance(command, list) and command[:2] == ["codex", "exec"]
    assert {"--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--output-schema"} <= set(command)
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command.count("--disable") >= 8 and "shell_tool" in command and "computer_use" in command
    assert observed["capture_output"] is True and observed["text"] is True and observed["check"] is False
    assert Path(str(observed["cwd"])).name.startswith("bidops-codex-exec-")
    assert observed["env"] == {"PATH": "/bin", "HOME": "/safe-home", "CODEX_API_KEY": "auth"}
    assert "must-not-pass" not in str(observed)
    assert result.provider == "codex-exec-reference" and result.model == "gpt-5.6-sol"
    assert result.prompt_tokens == 11 and result.output_tokens == 7


def test_codex_transport_locator_is_closed_then_normalized_to_canonical_shape():
    locator_schema = CODEX_STAGE_RESPONSE_SCHEMA["$defs"]["evidence"]["properties"]["locator"]
    assert locator_schema["additionalProperties"] is False
    assert set(locator_schema["required"]) == set(locator_schema["properties"])
    assert all(CODEX_STAGE_RESPONSE_SCHEMA["properties"][name]["maxItems"] == 8 for name in ("claims", "evidence", "unknowns", "warnings"))

    input_slice = _input()
    payload = _payload(input_slice)
    payload["evidence"] = [{
        "evidence_id": str(uuid4()), "source_kind": "document",
        "document_version_id": str(uuid4()), "structure_id": str(uuid4()),
        "profile_version_id": None, "profile_evidence_id": None,
        "locator_type": "page",
        "locator": {
            "page": 1, "block_key": None, "paragraph_key": None,
            "text_start": None, "text_end": None, "table_key": None,
            "row": None, "column": None, "bbox": None, "fact_key": None,
        },
        "quote": "근거", "confidence": 1.0, "source_sha256": "a" * 64,
    }]

    def runner(command, **_kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = CodexExecClient(enabled=True, approved_notice_ids=(17,), runner=runner).invoke(
        "requirements_and_evaluation", input_slice, _policy(),
    )
    assert result.structured_output["evidence"][0]["locator"] == {"page": 1}


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (subprocess.TimeoutExpired("codex", 300), "timeout"),
        (None, "truncated_json"),
    ],
)
def test_codex_timeout_and_truncated_output_retry_twice(failure, expected):
    calls = {"count": 0}

    def runner(command, **_kwargs):
        calls["count"] += 1
        if failure is not None:
            raise failure
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(CodexExecInvocationError) as raised:
        CodexExecClient(enabled=True, approved_notice_ids=(17,), runner=runner).invoke(
            "requirements_and_evaluation", _input(), _policy(),
        )
    assert raised.value.code == expected
    assert calls["count"] == 3
    assert all(set(item) <= {"retry_index", "status", "error_code", "latency_ms"} for item in raised.value.attempts)
