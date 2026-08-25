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


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in _POLICY_EXPORTS:
        return getattr(import_module(".policy", __name__), name)
    if name in _PROFILE_EXPORTS:
        return getattr(import_module(".profile_snapshot", __name__), name)
    raise AttributeError(name)


__all__ = sorted(_POLICY_EXPORTS | _PROFILE_EXPORTS)
