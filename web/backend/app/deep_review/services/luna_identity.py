"""Fixed identity for the shared codex-exec Luna runner."""

from collections.abc import Mapping

PROVIDER = "codex-exec"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "high"
CLI_VERSION = "0.162.1"
HP_POLICY_IDENTITY = "analysis-policy-luna-hp-v1"
COMPANY_POLICY_IDENTITIES = frozenset({"analysis-policy-luna-demo-v1", HP_POLICY_IDENTITY})

LEGACY_MODELS = frozenset({"gpt-5.6-luna"})
LEGACY_EFFORTS = frozenset({"xhigh"})
ALLOWED_MODELS = frozenset({MODEL}) | LEGACY_MODELS
ALLOWED_EFFORTS = frozenset({REASONING_EFFORT}) | LEGACY_EFFORTS


def matches_runtime(model_name, reasoning_effort) -> bool:
    return model_name == MODEL and reasoning_effort == REASONING_EFFORT


def policy_reasoning_effort(policy) -> str | None:
    """Read an immutable policy row's effort without replacing legacy values."""

    rules = getattr(policy, "validation_rules", None)
    if not isinstance(rules, Mapping):
        return None
    snapshot = rules.get("policy_snapshot")
    source = snapshot if isinstance(snapshot, Mapping) else rules
    generation = source.get("generation")
    value = generation.get("reasoning_effort") if isinstance(generation, Mapping) else None
    return value if isinstance(value, str) else None
