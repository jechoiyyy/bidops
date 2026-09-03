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
_T6_EXPORTS = {
    "ArtifactError", "ArtifactStore", "CreatedExecution", "ScreeningCreationError",
    "ScreeningWorker", "WorkerError",
}
_MOCK_EXPORTS = {
    "MOCK_MODEL_DIGEST", "MockScreeningTransport", "MockScreeningTransportError",
}
# 확장점 구현과 deep_review가 이름으로 가려 받는 seam (명세 §6.1·§6.3).
# `current_judgment`·`current_judgments`·`latest_corrected_grade`만 모듈 밖으로
# 나가며, 그 밖의 판정 ORM·service는 다른 모듈이 쓰지 못한다.
_PROJECTION_EXPORTS = {
    "CorrectedGrade",
    "JudgmentSummary",
    "ScreeningJudgmentProjection",
    "current_judgment",
    "current_judgments",
    "latest_corrected_grade",
}
_INGEST_EXPORTS = {
    "ScreeningRunIngestHook",
    "inspect_c2_directory",
    "load_order_plan_screening",
    "load_run_judgments",
}


def register_lifecycle_extensions(registry=None):
    """screening 구현으로 lifecycle 확장점을 채운다 (명세 §6).

    조립 계층이 앱 객체를 만들 때 한 번 부른다. import와 객체 생성일 뿐이며
    migration·seed·정책 활성화·모델 호출을 하지 않는다(§9).
    """

    from .ingest import ScreeningRunIngestHook
    from .projection import ScreeningJudgmentProjection

    if registry is None:
        from ..lifecycle import extension_registry

        registry = extension_registry()
    registry.register_judgment_projection(ScreeningJudgmentProjection())
    registry.register_run_ingest_hook(ScreeningRunIngestHook())
    return registry


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
    if name in _T6_EXPORTS:
        module_name = ".artifacts" if name in {"ArtifactError", "ArtifactStore"} else ".worker" if name in {"ScreeningWorker", "WorkerError"} else ".orchestrator"
        return getattr(import_module(module_name, __name__), name)
    if name in _MOCK_EXPORTS:
        return getattr(import_module(".mock_transport", __name__), name)
    if name in _PROJECTION_EXPORTS:
        return getattr(import_module(".projection", __name__), name)
    if name in _INGEST_EXPORTS:
        return getattr(import_module(".ingest", __name__), name)
    raise AttributeError(name)


__all__ = sorted(
    _POLICY_EXPORTS
    | _PROFILE_EXPORTS
    | _RUNTIME_EXPORTS
    | _T6_EXPORTS
    | _MOCK_EXPORTS
    | _PROJECTION_EXPORTS
    | _INGEST_EXPORTS
    | {"register_lifecycle_extensions"}
)
