"""One-time, file-backed Luna reference execution for the v4 runner.

This is an operator seam for an explicitly authorised reference run.  It is
not a second model transport: the response is produced outside the service,
then this module verifies the frozen policy, exact model input and exact
prompt before handing the bytes to :class:`PrespecV4OverviewRunner`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy.orm import Session

from ...core.model_client import (
    MAX_RESPONSE_BYTES,
    InvocationResult,
    ModelInvocationError,
    build_prompt,
)
from ...core.models import AuditEvent
from .prespec_v4_runner import (
    V4ModelBinding,
    V4OverviewPolicy,
    V4_POLICY_PATH,
    V4_LUNA_REFERENCE_MODEL,
    V4_LUNA_REFERENCE_PROVIDER,
)


LUNA_REFERENCE_SCHEMA = "bidops.prespec-v4-luna-reference.v1"
MAX_REFERENCE_ENVELOPE_BYTES = 24 * 1024 * 1024
MAX_REFERENCE_TASK_BYTES = 512
MAX_REFERENCE_PROVENANCE_BYTES = 16 * 1024
# ``build_prompt`` bounds the UTF-8 string at 24,000 characters.  Korean
# input can occupy four bytes per character; use that existing bound's byte
# envelope rather than introducing a smaller byte limit that rejects a valid
# frozen prompt.
MAX_PROMPT_BYTES = 4 * 24_000
_HEX64 = frozenset("0123456789abcdef")


class LunaReferenceError(ValueError):
    """Safe, stable validation failure for the one-time reference seam."""

    def __init__(self, code: str) -> None:
        self.code = str(code or "luna_reference_invalid")[:64]
        super().__init__(self.code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise LunaReferenceError("reference_json_invalid") from error


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256(_canonical(value))


def _hex_digest(value: Any, code: str = "reference_hash_invalid") -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX64 for char in value):
        raise LunaReferenceError(code)
    return value


def _read_envelope(path: Path) -> bytes:
    if not path.is_absolute() or path.is_symlink():
        raise LunaReferenceError("reference_path_invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise LunaReferenceError("reference_unreadable") from error
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            raise LunaReferenceError("reference_path_invalid")
        data = os.read(fd, MAX_REFERENCE_ENVELOPE_BYTES + 1)
    except LunaReferenceError:
        raise
    except OSError as error:
        raise LunaReferenceError("reference_unreadable") from error
    finally:
        os.close(fd)
    if len(data) > MAX_REFERENCE_ENVELOPE_BYTES:
        raise LunaReferenceError("reference_size_limit")
    return data


def _read_record_sibling(record_path: Path, name: str, *, limit: int) -> bytes:
    """Read only a fixed sibling named by the Luna generation record."""

    if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
        raise LunaReferenceError("reference_path_invalid")
    parent = record_path.parent
    child = parent / name
    if child.is_symlink():
        raise LunaReferenceError("reference_path_invalid")
    try:
        if child.resolve(strict=True).parent != parent.resolve(strict=True):
            raise LunaReferenceError("reference_path_invalid")
    except (OSError, RuntimeError) as error:
        raise LunaReferenceError("reference_path_invalid") from error
    data = _read_envelope(child)
    if len(data) > limit:
        raise LunaReferenceError("reference_size_limit")
    return data


def _decode_bytes(value: Any, *, code: str, limit: int) -> bytes:
    if not isinstance(value, str):
        raise LunaReferenceError(code)
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError, binascii.Error) as error:
        raise LunaReferenceError(code) from error
    if len(decoded) > limit:
        raise LunaReferenceError(code)
    return decoded


def _bounded_mapping(value: Any, *, code: str, limit: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LunaReferenceError(code)
    encoded = _canonical(dict(value))
    if len(encoded) > limit:
        raise LunaReferenceError(code)
    return json.loads(encoded.decode("utf-8"))


@dataclass(frozen=True)
class LunaReferenceResponse:
    """Validated immutable envelope supplied by the Luna reference agent."""

    binding: V4ModelBinding
    manifest_sha256: str
    agent_task: str
    effort: str
    weight_revision: None
    provenance: Mapping[str, Any]
    input_bytes: bytes
    prompt_bytes: bytes
    raw_response: bytes
    structured_output: Mapping[str, Any]

    @property
    def input_sha256(self) -> str:
        return _sha256(self.input_bytes)

    @property
    def prompt_sha256(self) -> str:
        return _sha256(self.prompt_bytes)

    @property
    def output_sha256(self) -> str:
        return _sha256(self.raw_response)

    def audit_metadata(self, *, attempt_id: Any) -> dict[str, Any]:
        """Return hashes/provenance only; never put prompt or source text in audit."""

        return {
            "schema": LUNA_REFERENCE_SCHEMA,
            "attempt_id": str(attempt_id),
            "provider": V4_LUNA_REFERENCE_PROVIDER,
            "model_name": V4_LUNA_REFERENCE_MODEL,
            "model_digest_kind": "reference_execution_manifest_sha256",
            "model_digest": self.binding.model_digest,
            "weight_revision": None,
            "effort": self.effort,
            "agent_task": self.agent_task,
            "source_provider": self.provenance.get("source_provider"),
            "record_schema": self.provenance.get("record_schema"),
            "sample_key": self.provenance.get("sample_key"),
            "sample_manifest_sha256": self.provenance.get("sample_manifest_sha256"),
            "policy_digest": self.binding.policy_digest,
            "prompt_version": self.binding.prompt_version,
            "input_sha256": self.input_sha256,
            "input_size_bytes": len(self.input_bytes),
            "prompt_sha256": self.prompt_sha256,
            "prompt_size_bytes": len(self.prompt_bytes),
            "output_sha256": self.output_sha256,
            "output_size_bytes": len(self.raw_response),
            "manifest_sha256": self.manifest_sha256,
            "provenance_sha256": _sha256_json(self.provenance),
            "quality_status": "unmeasured_reference",
        }


def load_luna_reference_response(path: Path, *, policy: V4OverviewPolicy) -> LunaReferenceResponse:
    """Load and validate one bounded Luna response envelope."""

    try:
        document = json.loads(_read_envelope(path))
    except LunaReferenceError:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise LunaReferenceError("reference_json_invalid") from error
    if not isinstance(document, Mapping) or document.get("schema") != LUNA_REFERENCE_SCHEMA:
        raise LunaReferenceError("reference_schema_invalid")

    agent = _bounded_mapping(document.get("agent"), code="reference_agent_invalid", limit=MAX_REFERENCE_TASK_BYTES)
    if (
        agent.get("provider") != V4_LUNA_REFERENCE_PROVIDER
        or agent.get("model_name") != V4_LUNA_REFERENCE_MODEL
        or agent.get("effort") != "max"
        or agent.get("weight_revision") is not None
    ):
        raise LunaReferenceError("reference_model_invalid")
    agent_task = agent.get("agent_task")
    if not isinstance(agent_task, str) or not agent_task.strip() or len(agent_task.encode("utf-8")) > MAX_REFERENCE_TASK_BYTES:
        raise LunaReferenceError("reference_agent_invalid")
    provenance = _bounded_mapping(document.get("provenance"), code="reference_provenance_invalid", limit=MAX_REFERENCE_PROVENANCE_BYTES)
    if provenance.get("actual_model") != V4_LUNA_REFERENCE_MODEL or provenance.get("effort") != "max" or provenance.get("weight_revision") is not None:
        raise LunaReferenceError("reference_provenance_invalid")

    policy_meta = _bounded_mapping(document.get("policy"), code="reference_policy_invalid", limit=8 * 1024)
    if (
        policy_meta.get("digest") != policy.digest
        or policy_meta.get("prompt_version") != policy.prompt_version
        or policy_meta.get("stage") != "prespec_overview"
    ):
        raise LunaReferenceError("reference_policy_mismatch")

    input_bytes = _decode_bytes(document.get("input_base64"), code="reference_input_invalid", limit=8 * 1024 * 1024)
    prompt_bytes = _decode_bytes(document.get("prompt_base64"), code="reference_prompt_invalid", limit=MAX_PROMPT_BYTES)
    raw_response = _decode_bytes(document.get("output_base64"), code="reference_output_invalid", limit=MAX_RESPONSE_BYTES)
    if _sha256(input_bytes) != _hex_digest(document.get("input_sha256")):
        raise LunaReferenceError("reference_input_hash_mismatch")
    if _sha256(prompt_bytes) != _hex_digest(document.get("prompt_sha256")):
        raise LunaReferenceError("reference_prompt_hash_mismatch")
    if _sha256(raw_response) != _hex_digest(document.get("output_sha256")):
        raise LunaReferenceError("reference_output_hash_mismatch")
    try:
        structured = json.loads(raw_response)
    except (UnicodeDecodeError, ValueError) as error:
        raise LunaReferenceError("reference_output_invalid") from error
    if not isinstance(structured, Mapping):
        raise LunaReferenceError("reference_output_invalid")
    manifest = {
        "schema": LUNA_REFERENCE_SCHEMA,
        "agent": {
            "provider": V4_LUNA_REFERENCE_PROVIDER,
            "model_name": V4_LUNA_REFERENCE_MODEL,
            "effort": "max",
            "weight_revision": None,
            "agent_task": agent_task.strip(),
        },
        "policy": dict(policy_meta),
        "input_sha256": _sha256(input_bytes),
        "input_size_bytes": len(input_bytes),
        "prompt_sha256": _sha256(prompt_bytes),
        "prompt_size_bytes": len(prompt_bytes),
        "output_sha256": _sha256(raw_response),
        "output_size_bytes": len(raw_response),
        "provenance": provenance,
    }
    manifest_sha256 = _sha256_json(manifest)
    declared_manifest = _hex_digest(document.get("manifest_sha256"), "reference_manifest_invalid")
    if declared_manifest != manifest_sha256:
        raise LunaReferenceError("reference_manifest_mismatch")
    try:
        binding = V4ModelBinding(
            provider=V4_LUNA_REFERENCE_PROVIDER,
            model_name=V4_LUNA_REFERENCE_MODEL,
            model_digest=manifest_sha256,
            prompt_version=policy.prompt_version,
            policy_digest=policy.digest,
            reference_only=True,
            deployable=False,
        )
    except (TypeError, ValueError) as error:
        raise LunaReferenceError("reference_binding_invalid") from error
    return LunaReferenceResponse(
        binding=binding,
        manifest_sha256=manifest_sha256,
        agent_task=agent_task.strip(),
        effort="max",
        weight_revision=None,
        provenance=provenance,
        input_bytes=input_bytes,
        prompt_bytes=prompt_bytes,
        raw_response=raw_response,
        structured_output=dict(structured),
    )


def load_luna_generation_sample(
    path: Path,
    *,
    sample_key: str,
    policy: V4OverviewPolicy,
) -> LunaReferenceResponse:
    """Adapt the immutable Luna generation record used for the three samples.

    The record contains fixed sibling input/output JSON files.  Their exact
    bytes remain the model evidence; this adapter only derives the prompt from
    the frozen input and checks the recorded prompt/output hashes.
    """

    record_bytes = _read_envelope(path)
    try:
        record = json.loads(record_bytes)
    except (UnicodeDecodeError, ValueError) as error:
        raise LunaReferenceError("reference_json_invalid") from error
    if not isinstance(record, Mapping) or record.get("record_schema") != "bidops.luna-reference-generation.v1":
        raise LunaReferenceError("reference_schema_invalid")
    if not isinstance(sample_key, str) or not sample_key.isdigit() or int(sample_key) < 1:
        raise LunaReferenceError("reference_sample_invalid")
    samples = record.get("samples")
    sample = samples.get(sample_key) if isinstance(samples, Mapping) else None
    if not isinstance(sample, Mapping):
        raise LunaReferenceError("reference_sample_missing")
    actual_model = record.get("actualmodel")
    effort = record.get("effort")
    weight_revision = record.get("opaqueweightsrevision")
    agent_task = record.get("agenttask")
    provider = record.get("provider")
    if (
        actual_model != V4_LUNA_REFERENCE_MODEL
        or effort != "max"
        or weight_revision is not None
        or not isinstance(agent_task, str)
        or not agent_task.strip()
        or len(agent_task.encode("utf-8")) > MAX_REFERENCE_TASK_BYTES
        or not isinstance(provider, str)
        or not provider.strip()
    ):
        raise LunaReferenceError("reference_model_invalid")
    policy_meta = record.get("policy")
    if not isinstance(policy_meta, Mapping):
        raise LunaReferenceError("reference_policy_invalid")
    policy_file_sha = _sha256(V4_POLICY_PATH.read_bytes())
    if (
        policy_meta.get("sha256") != policy_file_sha
        or policy_meta.get("model_name") != policy.model_name
        or policy_meta.get("prompt_version") != policy.prompt_version
        or policy_meta.get("stage") != "prespec_overview"
    ):
        raise LunaReferenceError("reference_policy_mismatch")

    input_path = sample.get("input_path")
    output_path = sample.get("output_path")
    if not isinstance(input_path, str) or not isinstance(output_path, str):
        raise LunaReferenceError("reference_path_invalid")
    input_path = Path(input_path)
    output_path = Path(output_path)
    try:
        record_parent = path.parent.resolve(strict=True)
        if (
            not input_path.is_absolute()
            or not output_path.is_absolute()
            or input_path.parent.resolve(strict=True) != record_parent
            or output_path.parent.resolve(strict=True) != record_parent
        ):
            raise LunaReferenceError("reference_path_invalid")
    except (OSError, RuntimeError) as error:
        raise LunaReferenceError("reference_path_invalid") from error
    input_name = input_path.name
    output_name = output_path.name
    if input_name != f"sample-{sample_key}-input.json" or output_name != f"sample-{sample_key}-output.json":
        raise LunaReferenceError("reference_path_invalid")
    input_bytes = _read_record_sibling(path, input_name, limit=8 * 1024 * 1024)
    raw_response = _read_record_sibling(path, output_name, limit=MAX_RESPONSE_BYTES)
    if (
        len(input_bytes) != sample.get("input_bytes")
        or len(raw_response) != sample.get("output_bytes")
        or _sha256(input_bytes) != sample.get("input_slice_sha256")
        or _sha256(raw_response) != sample.get("output_sha256")
    ):
        raise LunaReferenceError("reference_sample_hash_mismatch")
    try:
        input_slice = json.loads(input_bytes)
        structured = json.loads(raw_response)
    except (UnicodeDecodeError, ValueError) as error:
        raise LunaReferenceError("reference_sample_json_invalid") from error
    if not isinstance(input_slice, Mapping) or not isinstance(structured, Mapping):
        raise LunaReferenceError("reference_sample_json_invalid")
    if _canonical(input_slice) != input_bytes:
        raise LunaReferenceError("reference_input_not_canonical")
    try:
        prompt_bytes = build_prompt("prespec_overview", input_slice, policy.document).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise LunaReferenceError("reference_prompt_invalid") from error
    if (
        len(prompt_bytes) != sample.get("prompt_bytes")
        or _sha256(prompt_bytes) != sample.get("prompt_sha256")
    ):
        raise LunaReferenceError("reference_prompt_hash_mismatch")
    reference_prompt = record.get("reference_prompt")
    if not isinstance(reference_prompt, Mapping):
        raise LunaReferenceError("reference_provenance_invalid")
    provenance = {
        "record_schema": record["record_schema"],
        "record_sha256": _sha256(record_bytes),
        "sample_key": sample_key,
        "source_provider": provider,
        "actual_model": actual_model,
        "effort": effort,
        "weight_revision": None,
        "agent_task": agent_task.strip(),
        "pages": sample.get("pages"),
        "selector_input_sha256": sample.get("selector_input_sha256"),
        "selector_status": sample.get("selector_status"),
        "selector_strategy": sample.get("selector_strategy"),
        "reference_prompt": {
            "policy_sha256": reference_prompt.get("policy_sha256"),
            "prompt_sha256": reference_prompt.get("prompt_sha256"),
        },
    }
    provenance = _bounded_mapping(provenance, code="reference_provenance_invalid", limit=MAX_REFERENCE_PROVENANCE_BYTES)
    manifest = {
        "schema": LUNA_REFERENCE_SCHEMA,
        "record_schema": record["record_schema"],
        "record_sha256": _sha256(record_bytes),
        "sample_key": sample_key,
        "agent": {
            "provider": provider,
            "model_name": actual_model,
            "effort": effort,
            "weight_revision": None,
            "agent_task": agent_task.strip(),
        },
        "policy": {
            "file_sha256": policy_file_sha,
            "digest": policy.digest,
            "prompt_version": policy.prompt_version,
            "stage": "prespec_overview",
        },
        "input_sha256": _sha256(input_bytes),
        "input_size_bytes": len(input_bytes),
        "prompt_sha256": _sha256(prompt_bytes),
        "prompt_size_bytes": len(prompt_bytes),
        "output_sha256": _sha256(raw_response),
        "output_size_bytes": len(raw_response),
        "provenance": provenance,
    }
    sample_manifest_sha256 = _sha256_json(manifest)
    # The generation record is the single immutable execution manifest shared
    # by the three explicitly selected samples.  Use its digest for the model
    # binding so one activation can safely enqueue all three samples; retain
    # the per-sample manifest digest in the audit metadata above.
    manifest_sha256 = _sha256(record_bytes)
    provenance["sample_manifest_sha256"] = sample_manifest_sha256
    try:
        binding = V4ModelBinding(
            provider=V4_LUNA_REFERENCE_PROVIDER,
            model_name=V4_LUNA_REFERENCE_MODEL,
            model_digest=manifest_sha256,
            prompt_version=policy.prompt_version,
            policy_digest=policy.digest,
            reference_only=True,
            deployable=False,
        )
    except (TypeError, ValueError) as error:
        raise LunaReferenceError("reference_binding_invalid") from error
    return LunaReferenceResponse(
        binding=binding,
        manifest_sha256=manifest_sha256,
        agent_task=agent_task.strip(),
        effort="max",
        weight_revision=None,
        provenance=provenance,
        input_bytes=input_bytes,
        prompt_bytes=prompt_bytes,
        raw_response=raw_response,
        structured_output=dict(structured),
    )


class LunaReferenceClient:
    """Injectable client that replays one already-produced Luna response."""

    def __init__(self, response: LunaReferenceResponse) -> None:
        self.response = response
        self.calls = 0

    def invoke(self, stage: str, input_slice: Mapping[str, Any], policy: Mapping[str, Any]) -> InvocationResult:
        self.calls += 1
        if stage != "prespec_overview" or policy.get("prompt_version") != self.response.binding.prompt_version:
            raise ModelInvocationError("reference_policy_mismatch", ())
        try:
            input_bytes = _canonical(dict(input_slice))
            prompt_bytes = build_prompt(stage, input_slice, policy).encode("utf-8")
        except (TypeError, ValueError, LunaReferenceError) as error:
            raise ModelInvocationError("reference_input_invalid", ()) from error
        if input_bytes != self.response.input_bytes:
            raise ModelInvocationError("reference_input_mismatch", ())
        if prompt_bytes != self.response.prompt_bytes:
            raise ModelInvocationError("reference_prompt_mismatch", ())
        return InvocationResult(
            structured_output=self.response.structured_output,
            raw_response=self.response.raw_response,
            input_sha256=self.response.prompt_sha256,
            output_sha256=self.response.output_sha256,
            prompt_tokens=None,
            output_tokens=None,
            latency_ms=0,
            attempts=(),
            provider=V4_LUNA_REFERENCE_PROVIDER,
            model=V4_LUNA_REFERENCE_MODEL,
        )


def record_luna_reference_audit(session: Session, *, attempt_id: Any, response: LunaReferenceResponse) -> None:
    session.add(
        AuditEvent(
            actor_kind="system",
            claimed_name=None,
            action="prespec_v4.luna_reference",
            aggregate_type="prespec_v4_attempt",
            aggregate_id=str(attempt_id),
            safe_metadata=response.audit_metadata(attempt_id=attempt_id),
        )
    )


__all__ = [
    "LUNA_REFERENCE_SCHEMA",
    "LunaReferenceClient",
    "LunaReferenceError",
    "LunaReferenceResponse",
    "load_luna_generation_sample",
    "load_luna_reference_response",
    "record_luna_reference_audit",
]
