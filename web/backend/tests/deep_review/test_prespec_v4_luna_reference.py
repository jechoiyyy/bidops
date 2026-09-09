"""One-time Luna reference envelope and v4 runner seam."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.deep_review.models import PrespecV4Attempt
from app.deep_review.services.prespec_v4_ops import activate_v4
from app.deep_review.services.prespec_v4_runner import (
    PrespecV4OverviewRunner,
    V4_LUNA_REFERENCE_MODEL,
    V4_LUNA_REFERENCE_PROVIDER,
    _model_input,
    _load_manifest,
    enqueue_v4_attempt,
    load_v4_policy,
)
from app.deep_review.services.prespec_v4_luna_reference import (
    LunaReferenceClient,
    _canonical,
    _sha256,
    _sha256_json,
    load_luna_reference_response,
    record_luna_reference_audit,
)

from .test_prespec_v4_runner import _RawStore, _activate_for_target, _payload, _ready_target


def test_luna_reference_uses_exact_prompt_and_current_projection(tmp_path, monkeypatch):
    engine, session, store, target = _ready_target(tmp_path)
    policy = load_v4_policy()
    manifest, pages = _load_manifest(session, store, target)
    input_slice = _model_input(manifest, pages)
    from app.core.model_client import build_prompt

    input_bytes = _canonical(input_slice)
    prompt_bytes = build_prompt("prespec_overview", input_slice, policy.document).encode("utf-8")
    raw_output = json.dumps(_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    provenance = {
        "actual_model": V4_LUNA_REFERENCE_MODEL,
        "effort": "max",
        "weight_revision": None,
        "agent_task": "prespec-v4-luna-reference-test",
    }
    agent_task = "prespec-v4-luna-reference-test"
    manifest_material = {
        "schema": "bidops.prespec-v4-luna-reference.v1",
        "agent": {
            "provider": V4_LUNA_REFERENCE_PROVIDER,
            "model_name": V4_LUNA_REFERENCE_MODEL,
            "effort": "max",
            "weight_revision": None,
            "agent_task": agent_task,
        },
        "policy": {"digest": policy.digest, "prompt_version": policy.prompt_version, "stage": "prespec_overview"},
        "input_sha256": _sha256(input_bytes),
        "input_size_bytes": len(input_bytes),
        "prompt_sha256": _sha256(prompt_bytes),
        "prompt_size_bytes": len(prompt_bytes),
        "output_sha256": _sha256(raw_output),
        "output_size_bytes": len(raw_output),
        "provenance": provenance,
    }
    envelope = {
        "schema": "bidops.prespec-v4-luna-reference.v1",
        "agent": {
            "provider": V4_LUNA_REFERENCE_PROVIDER,
            "model_name": V4_LUNA_REFERENCE_MODEL,
            "effort": "max",
            "weight_revision": None,
            "agent_task": agent_task,
        },
        "policy": manifest_material["policy"],
        "input_base64": base64.b64encode(input_bytes).decode("ascii"),
        "input_sha256": _sha256(input_bytes),
        "prompt_base64": base64.b64encode(prompt_bytes).decode("ascii"),
        "prompt_sha256": _sha256(prompt_bytes),
        "output_base64": base64.b64encode(raw_output).decode("ascii"),
        "output_sha256": _sha256(raw_output),
        "provenance": provenance,
        "manifest_sha256": _sha256_json(manifest_material),
    }
    response_path = tmp_path / "luna-response.json"
    response_path.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    response = load_luna_reference_response(response_path, policy=policy)
    _activate_for_target(
        session,
        target,
        response.binding,
    )
    attempt = enqueue_v4_attempt(session, target_id=target.id, binding=response.binding)
    assert attempt is not None
    session.commit()
    record_luna_reference_audit(session, attempt_id=attempt.id, response=response)
    session.commit()

    monkeypatch.setattr(
        "app.deep_review.services.prespec_v4_runner.resolve_model_endpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(__import__("app.core.model_client", fromlist=["ModelEndpointError"]).ModelEndpointError("qwen unavailable")),
    )
    run = PrespecV4OverviewRunner(
        client=LunaReferenceClient(response),
        binding=response.binding,
        policy=policy,
        raw_response_store=_RawStore(),
        object_store=store,
    ).run_once(session, "luna-reference-test")
    assert run.status == "completed"
    row = session.scalar(select(PrespecV4Attempt).where(PrespecV4Attempt.id == attempt.id))
    assert row is not None and row.provider == V4_LUNA_REFERENCE_PROVIDER and row.model_name == V4_LUNA_REFERENCE_MODEL
    assert row.model_digest == response.manifest_sha256 and row.quality_status == "unmeasured_reference"
    from app.deep_review.services.prespec_v4_runner import current_v4_projection

    current = current_v4_projection(session, target.notice_id)
    assert current is not None and current["status"] == "completed" and current["result_id"] is not None
    session.close()
    engine.dispose()
