"""Qwen 기반 판정 실행 경계와 불변 입력 저장소."""

from importlib import import_module

_POLICY_EXPORTS = {
    "PolicyActivationError",
    "PolicyConflict",
    "PolicyRepository",
    "activate_policy",
    "canonical_policy_bytes",
    "create_policy",
    "designate_policy_candidate",
    "policy_content_digest",
    "seed_policy",
}
_PROFILE_EXPORTS = {
    "BASELINE_COMMIT",
    "PROFILE_SOURCE_PATH",
    "ProfileSnapshotError",
    "ProfileSnapshotRepository",
    "create_profile_snapshot",
    "read_profile_snapshot",
}
_RUNTIME_EXPORTS = {
    "CallMetadata",
    "ContractViolation",
    "ModelInspectionError",
    "OllamaCallError",
    "OllamaClient",
    "ScreeningOrchestrator",
    "ScreeningRunResult",
    "assemble_counterargument_prompt",
    "assemble_perspective_prompt",
    "assemble_synthesis_prompt",
    "project_notice_for_prompt",
    "schema_for_stage",
    "validate_counterargument",
    "validate_judgment",
    "validate_perspective",
}


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in _POLICY_EXPORTS:
        return getattr(import_module(".policy", __name__), name)
    if name in _PROFILE_EXPORTS:
        return getattr(import_module(".profile_snapshot", __name__), name)
    if name in _RUNTIME_EXPORTS:
        module_name = ".contracts" if name in {
            "CallMetadata", "ContractViolation", "validate_counterargument",
            "validate_judgment", "validate_perspective",
        } else ".ollama" if name in {
            "ModelInspectionError", "OllamaCallError", "OllamaClient",
            "ScreeningOrchestrator", "ScreeningRunResult",
        } else ".prompts"
        return getattr(import_module(module_name, __name__), name)
    raise AttributeError(name)


__all__ = sorted(_POLICY_EXPORTS | _PROFILE_EXPORTS | _RUNTIME_EXPORTS)
