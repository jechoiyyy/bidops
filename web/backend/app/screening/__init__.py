"""Qwen 기반 판정 실행 경계와 불변 입력 저장소.

screening은 core와 lifecycle 공개 이름만 import하고 deep_review를 알지 못한다
(명세 §4). 이 `__init__`이 screening의 **공개 표면**이다. 조립 계층은 여기 있는
이름만 쓰고, deep_review는 §6.3이 정한 읽기 전용 seam 함수
(`current_judgment`·`current_judgments`·`latest_corrected_grade`)만 쓴다.

이름은 lifecycle과 같은 방식으로 **지연 해석**한다. 패키지 초기화가 아무것도
import하지 않으므로 `python -m app.screening.cli` 같은 진입점이 모듈 전체를 지고
시작하지 않고, router 인스턴스를 공개 이름으로 올려도 import 순환이 생기지
않는다. 공개 이름과 동작은 그대로다.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

#: 공개 이름 → (구현 모듈, 그 모듈 안의 이름).
_EXPORTS: dict[str, tuple[str, str]] = {
    # --- 판정 정책 (policy.py) --------------------------------------------
    "PolicyActivationError": (".policy", "PolicyActivationError"),
    "PolicyConflict": (".policy", "PolicyConflict"),
    "PolicyRepository": (".policy", "PolicyRepository"),
    "activate_policy": (".policy", "activate_policy"),
    "canonical_policy_bytes": (".policy", "canonical_policy_bytes"),
    "create_policy": (".policy", "create_policy"),
    "designate_policy_candidate": (".policy", "designate_policy_candidate"),
    "policy_content_digest": (".policy", "policy_content_digest"),
    "seed_policy": (".policy", "seed_policy"),
    # --- 회사 프로필 스냅샷 (profile_snapshot.py) ---------------------------
    "BASELINE_COMMIT": (".profile_snapshot", "BASELINE_COMMIT"),
    "PROFILE_SOURCE_PATH": (".profile_snapshot", "PROFILE_SOURCE_PATH"),
    "ProfileSnapshotError": (".profile_snapshot", "ProfileSnapshotError"),
    "ProfileSnapshotRepository": (".profile_snapshot", "ProfileSnapshotRepository"),
    "create_profile_snapshot": (".profile_snapshot", "create_profile_snapshot"),
    "read_profile_snapshot": (".profile_snapshot", "read_profile_snapshot"),
    # --- 모델 계약 검증 (contracts.py) --------------------------------------
    "CallMetadata": (".contracts", "CallMetadata"),
    "ContractViolation": (".contracts", "ContractViolation"),
    "validate_counterargument": (".contracts", "validate_counterargument"),
    "validate_judgment": (".contracts", "validate_judgment"),
    "validate_perspective": (".contracts", "validate_perspective"),
    # --- 모델 클라이언트와 실행 (ollama.py) ---------------------------------
    "ModelInspectionError": (".ollama", "ModelInspectionError"),
    "OllamaCallError": (".ollama", "OllamaCallError"),
    "OllamaClient": (".ollama", "OllamaClient"),
    "ScreeningOrchestrator": (".ollama", "ScreeningOrchestrator"),
    "ScreeningRunResult": (".ollama", "ScreeningRunResult"),
    # --- 프롬프트 조립 (prompts.py) -----------------------------------------
    "assemble_counterargument_prompt": (".prompts", "assemble_counterargument_prompt"),
    "assemble_perspective_prompt": (".prompts", "assemble_perspective_prompt"),
    "assemble_synthesis_prompt": (".prompts", "assemble_synthesis_prompt"),
    "project_notice_for_prompt": (".prompts", "project_notice_for_prompt"),
    "schema_for_stage": (".prompts", "schema_for_stage"),
    # --- 실행 생성·산출물·worker -------------------------------------------
    "ArtifactError": (".artifacts", "ArtifactError"),
    "ArtifactStore": (".artifacts", "ArtifactStore"),
    "CreatedExecution": (".orchestrator", "CreatedExecution"),
    "ScreeningCreationError": (".orchestrator", "ScreeningCreationError"),
    "ScreeningWorker": (".worker", "ScreeningWorker"),
    "WorkerError": (".worker", "WorkerError"),
    # --- 참조 워크플로 전용 합성 transport (mock_transport.py) --------------
    "MOCK_MODEL_DIGEST": (".mock_transport", "MOCK_MODEL_DIGEST"),
    "MockScreeningTransport": (".mock_transport", "MockScreeningTransport"),
    "MockScreeningTransportError": (".mock_transport", "MockScreeningTransportError"),
    # --- 확장점 구현과 deep_review가 이름으로 가려 받는 seam (§6.1·§6.3) ----
    # `current_judgment`·`current_judgments`·`latest_corrected_grade`만 모듈
    # 밖으로 나가며, 그 밖의 판정 ORM·service는 다른 모듈이 쓰지 못한다.
    "CorrectedGrade": (".projection", "CorrectedGrade"),
    "JudgmentSummary": (".projection", "JudgmentSummary"),
    "ScreeningJudgmentProjection": (".projection", "ScreeningJudgmentProjection"),
    "current_judgment": (".projection", "current_judgment"),
    "current_judgments": (".projection", "current_judgments"),
    "latest_corrected_grade": (".projection", "latest_corrected_grade"),
    # --- 회차 적재 hook (ingest.py) ----------------------------------------
    "ScreeningRunIngestHook": (".ingest", "ScreeningRunIngestHook"),
    "inspect_c2_directory": (".ingest", "inspect_c2_directory"),
    "load_order_plan_screening": (".ingest", "load_order_plan_screening"),
    "load_run_judgments": (".ingest", "load_run_judgments"),
    # --- 개정 payload 계약 (services/{revisions,reviews}.py) ----------------
    # 일회성 SQLite 이전 도구가 legacy 개정 행을 지금의 payload 계약으로 다시
    # 쓸 때 쓴다. 같은 정규화를 복제하지 않으려고 screening이 공개한다.
    "JUDGMENT_PAYLOAD_SCHEMA": (".services.revisions", "JUDGMENT_PAYLOAD_SCHEMA"),
    "REVIEW_PAYLOAD_SCHEMA": (".services.revisions", "REVIEW_PAYLOAD_SCHEMA"),
    "canonical_payload_and_hash": (".services.revisions", "canonical_payload_and_hash"),
    "review_revision_payload": (".services.reviews", "review_revision_payload"),
    # --- 조립 계층이 등록하는 router 인스턴스 (routers/*.py) ---------------
    # `notice_reviews_router`와 `screening_run_router`는 다른 모듈의 경로
    # 접두사(`/api/notices`, `/api/runs`)를 쓰지만 제공 모듈은 screening이다
    # (§5.3). screening을 끄면 그 경로도 404다.
    "notice_reviews_router": (".routers.reviews", "notice_router"),
    "order_plans_router": (".routers.order_plans", "router"),
    "policies_router": (".routers.policies", "router"),
    "profile_router": (".routers.profile", "router"),
    "quality_gates_router": (".routers.quality_gates", "router"),
    "reviews_router": (".routers.reviews", "router"),
    "schedule_router": (".routers.schedule", "router"),
    "screening_router": (".routers.screening", "router"),
    "screening_run_router": (".routers.screening", "run_router"),
    # --- in-process runtime (runtime.py) -----------------------------------
    "RuntimePipelineBridge": (".runtime", "RuntimePipelineBridge"),
    "ScreeningRuntime": (".runtime", "ScreeningRuntime"),
    "build_runtime": (".runtime", "build_runtime"),
    # --- 별도 worker 프로세스가 쓰는 C-2 실행기 (workers/order_plan.py) -----
    # 조립 계층의 합성 analysis worker가 C-2 claim을 먼저 시도할 때 쓴다.
    "C2ScreeningWorker": (".workers.order_plan", "C2ScreeningWorker"),
}


#: registry에 자기 등록을 표시하는 키. lifecycle은 이 문자열의 의미를 해석하지
#: 않고 "같은 등록자인가"만 본다. 같은 키로 다시 등록하면 제자리 교체이므로
#: `create_app()`을 한 프로세스에서 두 번 불러도 hook이 두 번 붙지 않는다.
EXTENSION_OWNER = __name__


def register_lifecycle_extensions(registry=None):
    """screening 구현으로 lifecycle 확장점을 채운다 (명세 §6).

    조립 계층이 앱 객체를 만들 때 부른다. import와 객체 생성일 뿐이며
    migration·seed·정책 활성화·모델 호출을 하지 않는다(§9). 같은 registry에 두 번
    불러도 결과가 같다 — 등록은 `EXTENSION_OWNER` 키로 제자리 교체된다.
    """

    from .ingest import ScreeningRunIngestHook
    from .projection import ScreeningJudgmentProjection

    if registry is None:
        from ..lifecycle import extension_registry

        registry = extension_registry()
    registry.register_judgment_projection(
        ScreeningJudgmentProjection(), owner=EXTENSION_OWNER
    )
    registry.register_run_ingest_hook(ScreeningRunIngestHook(), owner=EXTENSION_OWNER)
    return registry


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    # 한 번 푼 이름은 모듈에 심어 다음부터 `__getattr__`을 거치지 않게 한다.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = sorted(set(_EXPORTS) | {"register_lifecycle_extensions"})


if TYPE_CHECKING:  # pragma: no cover - 정적 분석용 이름 노출
    from .runtime import RuntimePipelineBridge, ScreeningRuntime, build_runtime
    from .workers.order_plan import C2ScreeningWorker
