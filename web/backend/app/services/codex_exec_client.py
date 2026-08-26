"""Development-only Codex CLI adapter for deep-review stage generation.

The adapter deliberately exposes the same bounded ``invoke`` surface as the
local vLLM client.  Codex receives only the already-sanitized prompt on stdin,
runs in an isolated read-only directory without tools, and cannot write the
source store or database.  The authoritative deep-review validator remains
outside this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from .vllm_client import (
    APPROVED_RETRIES,
    APPROVED_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    STAGE_RESPONSE_SCHEMA,
    InvocationResult,
    VllmInvocationError,
    build_prompt,
)


class CodexExecInvocationError(VllmInvocationError):
    """Safe provider error compatible with the deep-review orchestrator."""


def _add_explicit_scalar_types(value: Any) -> None:
    """Add scalar ``type`` keywords required by Codex strict schemas."""

    if isinstance(value, dict):
        if "type" not in value and "const" in value:
            constant = value["const"]
            value["type"] = "null" if constant is None else "boolean" if isinstance(constant, bool) else "integer" if isinstance(constant, int) else "number" if isinstance(constant, float) else "string"
        if "type" not in value and isinstance(value.get("enum"), list) and value["enum"]:
            kinds: list[str] = []
            for item in value["enum"]:
                kind = "null" if item is None else "boolean" if isinstance(item, bool) else "integer" if isinstance(item, int) else "number" if isinstance(item, float) else "string"
                if kind not in kinds:
                    kinds.append(kind)
            value["type"] = kinds[0] if len(kinds) == 1 else kinds
        for child in value.values():
            _add_explicit_scalar_types(child)
    elif isinstance(value, list):
        for child in value:
            _add_explicit_scalar_types(child)


def _codex_stage_schema() -> dict[str, Any]:
    """Return a strict transport schema accepted by Codex structured output.

    The canonical evidence schema uses a discriminator plus several exact
    locator shapes.  Codex strict output requires a closed object, so the
    transport carries a nullable superset.  ``_canonicalize_locators`` drops
    the unused null fields before the authoritative schema validates facts.
    """

    schema = deepcopy(STAGE_RESPONSE_SCHEMA)
    locator = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "page", "block_key", "paragraph_key", "text_start", "text_end",
            "table_key", "row", "column", "bbox", "fact_key",
        ],
        "properties": {
            "page": {"type": ["integer", "null"], "minimum": 1},
            "block_key": {"type": ["string", "null"]},
            "paragraph_key": {"type": ["string", "null"]},
            "text_start": {"type": ["integer", "null"], "minimum": 0},
            "text_end": {"type": ["integer", "null"], "minimum": 0},
            "table_key": {"type": ["string", "null"]},
            "row": {"type": ["integer", "null"], "minimum": 0},
            "column": {"type": ["integer", "null"], "minimum": 0},
            "bbox": {
                "type": ["array", "null"], "minItems": 4, "maxItems": 4,
                "items": {"type": "number"},
            },
            "fact_key": {"type": ["string", "null"]},
        },
    }
    schema["$defs"]["evidence"]["properties"]["locator"] = deepcopy(locator)
    schema["$defs"]["evidence_base"]["properties"]["locator"] = deepcopy(locator)
    for field_name in ("claims", "evidence", "unknowns", "warnings"):
        schema["properties"][field_name]["maxItems"] = 8
    schema["$defs"]["claim"]["properties"]["premise_claim_ids"]["maxItems"] = 8
    schema["$defs"]["claim"]["properties"]["evidence_ids"]["maxItems"] = 8
    _add_explicit_scalar_types(schema)
    return schema


CODEX_STAGE_RESPONSE_SCHEMA = _codex_stage_schema()
_LOCATOR_KEYS = {
    "page": ("page",),
    "paragraph": ("page", "block_key", "paragraph_key", "text_start", "text_end"),
    "table_cell": ("page", "block_key", "table_key", "row", "column"),
    "bbox": ("page", "block_key", "bbox"),
    "profile_fact": ("fact_key",),
}
_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "CODEX_HOME", "CODEX_API_KEY", "OPENAI_API_KEY",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "LANG", "LC_ALL", "TERM",
})
_DISABLED_FEATURES = (
    "shell_tool", "code_mode_host", "hooks", "apps", "browser_use",
    "computer_use", "multi_agent", "plugins", "image_generation",
)


def _canonicalize_locators(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(payload))
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        return result
    for item in evidence:
        if not isinstance(item, dict):
            continue
        locator_type = item.get("locator_type")
        locator = item.get("locator")
        keys = _LOCATOR_KEYS.get(locator_type)
        if keys is None or not isinstance(locator, Mapping):
            continue
        item["locator"] = {key: locator.get(key) for key in keys}
    return result


def _safe_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Pass process/auth essentials only; never inherit BidOps secrets."""

    return {key: value for key, value in source.items() if key in _ENV_ALLOWLIST}


def _usage_from_jsonl(raw: str) -> tuple[int | None, int | None]:
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping) or event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, Mapping):
            continue
        input_value = usage.get("input_tokens")
        output_value = usage.get("output_tokens")
        prompt_tokens = input_value if isinstance(input_value, int) else prompt_tokens
        output_tokens = output_value if isinstance(output_value, int) else output_tokens
    return prompt_tokens, output_tokens


class CodexExecClient:
    """Invoke Codex as an explicitly approved, tool-free reference provider."""

    provider_name = "codex-exec-reference"

    def __init__(
        self,
        *,
        enabled: bool = False,
        binary: str = "codex",
        model: str = "gpt-5.6-sol",
        reasoning_effort: str = "high",
        approved_notice_ids: Sequence[int] = (),
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not binary or Path(binary).name != binary and not Path(binary).is_absolute():
            raise ValueError("Codex executable must be a command name or absolute path")
        if not model or reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("Codex model configuration is invalid")
        self.enabled = bool(enabled)
        self.binary = binary
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.approved_notice_ids = frozenset(int(value) for value in approved_notice_ids)
        self._runner = runner
        self._environment = _safe_environment(environment if environment is not None else os.environ)

    def require_notice_approval(self, notice_id: int) -> None:
        if not self.enabled:
            raise CodexExecInvocationError("external_provider_disabled", ())
        if int(notice_id) not in self.approved_notice_ids:
            raise CodexExecInvocationError("external_provider_notice_not_approved", ())

    def _command(self, schema_path: Path, output_path: Path) -> list[str]:
        command = [
            self.binary, "exec", "--ephemeral", "--sandbox", "read-only",
            "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
        ]
        for feature in _DISABLED_FEATURES:
            command.extend(("--disable", feature))
        command.extend((
            "--model", self.model,
            "--config", f'model_reasoning_effort="{self.reasoning_effort}"',
            "--json", "--output-schema", str(schema_path),
            "--output-last-message", str(output_path), "-",
        ))
        return command

    def invoke(
        self,
        stage: str,
        input_slice: Mapping[str, Any],
        policy: Mapping[str, Any],
        *,
        profile: Mapping[str, Any] | None = None,
        prior_stages: Sequence[Mapping[str, Any]] = (),
    ) -> InvocationResult:
        notice_id = input_slice.get("notice_id")
        if not isinstance(notice_id, int) or isinstance(notice_id, bool):
            raise CodexExecInvocationError("external_provider_notice_not_approved", ())
        self.require_notice_approval(notice_id)
        chunking = policy.get("chunking") if isinstance(policy.get("chunking"), Mapping) else {}
        try:
            timeout_seconds = int(chunking.get("timeout_seconds", APPROVED_TIMEOUT_SECONDS))
            retries = int(chunking.get("retries", APPROVED_RETRIES))
        except (TypeError, ValueError):
            raise CodexExecInvocationError("policy_invalid", ()) from None
        if timeout_seconds != APPROVED_TIMEOUT_SECONDS or not 0 <= retries <= APPROVED_RETRIES:
            raise CodexExecInvocationError("policy_invalid", ())
        prompt = build_prompt(stage, input_slice, policy, profile=profile, prior_stages=prior_stages)
        input_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        observations: list[dict[str, Any]] = []
        for index in range(retries + 1):
            started = time.monotonic()
            try:
                with tempfile.TemporaryDirectory(prefix="bidops-codex-exec-") as scratch:
                    scratch_path = Path(scratch)
                    schema_path = scratch_path / "stage-schema.json"
                    output_path = scratch_path / "stage-output.json"
                    schema_path.write_text(json.dumps(CODEX_STAGE_RESPONSE_SCHEMA, ensure_ascii=False), encoding="utf-8")
                    completed = self._runner(
                        self._command(schema_path, output_path), input=prompt, text=True,
                        capture_output=True, cwd=scratch, env=dict(self._environment),
                        timeout=timeout_seconds, check=False,
                    )
                    if completed.returncode != 0:
                        raise OSError("provider_error")
                    if not output_path.is_file():
                        raise EOFError("truncated_json")
                    raw = output_path.read_bytes()
                    if not raw or len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError("response_too_large" if raw else "truncated_json")
                    structured = json.loads(raw.decode("utf-8"))
                    if not isinstance(structured, Mapping):
                        raise ValueError("malformed_json")
                    structured = _canonicalize_locators(structured)
                    canonical_raw = json.dumps(structured, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    if len(canonical_raw) > MAX_RESPONSE_BYTES:
                        raise ValueError("response_too_large")
                    prompt_tokens, output_tokens = _usage_from_jsonl(completed.stdout or "")
                elapsed = int((time.monotonic() - started) * 1000)
                observations.append({"retry_index": index, "status": "succeeded", "latency_ms": elapsed})
                return InvocationResult(
                    structured_output=structured, raw_response=canonical_raw,
                    input_sha256=input_hash,
                    output_sha256=hashlib.sha256(canonical_raw).hexdigest(),
                    prompt_tokens=prompt_tokens, output_tokens=output_tokens,
                    latency_ms=elapsed, attempts=tuple(observations),
                    provider=self.provider_name, model=self.model,
                )
            except subprocess.TimeoutExpired:
                code = "timeout"
            except EOFError:
                code = "truncated_json"
            except json.JSONDecodeError:
                code = "truncated_json"
            except UnicodeDecodeError:
                code = "malformed_json"
            except FileNotFoundError:
                code = "provider_unavailable"
            except OSError:
                code = "provider_error"
            except ValueError as error:
                code = str(error) if str(error) in {"response_too_large", "truncated_json"} else "malformed_json"
            except Exception:
                code = "provider_error"
            elapsed = int((time.monotonic() - started) * 1000)
            observations.append({"retry_index": index, "status": "failed", "error_code": code, "latency_ms": elapsed})
        raise CodexExecInvocationError(str(observations[-1]["error_code"]), observations)


__all__ = [
    "CODEX_STAGE_RESPONSE_SCHEMA", "CodexExecClient", "CodexExecInvocationError",
]
