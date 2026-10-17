"""Fixed identity for the shared codex-exec Luna runner."""

from collections.abc import Mapping

PROVIDER = "codex-exec"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "high"
CLI_VERSION = "0.162.1"
HP_POLICY_IDENTITY = "analysis-policy-luna-hp-v1"
#: RL-03 real-company card analysis (``pipeline_version="card-v1"``).  Selected
#: only through ``BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID``; never a global policy.
RL_POLICY_IDENTITY = "analysis-policy-luna-rl-v1"
#: RL-03 결정 B23: same ``card-v1`` pipeline with selector ``card-sections-v2``
#: (symbol/PUA bullet headings) and missing sections recorded instead of
#: stopping before synthesis.  v1 stays importable and keeps its behaviour.
RL_POLICY_IDENTITY_V2 = "analysis-policy-luna-rl-v2"
#: RL-03 결정 B30: v2 with selector ``card-sections-v3`` (TOC entries without page
#: numbers and title-only units excluded), the explicit extract validation
#: contract and per-unit ``expected_concepts`` in the extract payload.  v1/v2
#: stay importable and keep their behaviour.
RL_POLICY_IDENTITY_V3 = "analysis-policy-luna-rl-v3"
#: RL-03 결정 B33: v3 selector with the extract output contract
#: ``bidops.requirement-extract.v2`` (model omits concept_candidates/operator,
#: code derives them; kind x unit in the output schema).  v1-v3 stay importable.
RL_POLICY_IDENTITY_V4 = "analysis-policy-luna-rl-v4"
#: RL-03 결정 B35: v4 with the extract instruction quoting each number with its
#: unit and attached comparator (분·초·글자·시간·간격 → text).  v1-v4 stay importable.
RL_POLICY_IDENTITY_V5 = "analysis-policy-luna-rl-v5"
#: RL-03 결정 B37: v5 with the extract instruction requiring a numeric quote to be
#: unique in its block (extend left) and date ranges as text (no computed numbers).
RL_POLICY_IDENTITY_V6 = "analysis-policy-luna-rl-v6"
RL_POLICY_IDENTITIES = frozenset({
    RL_POLICY_IDENTITY, RL_POLICY_IDENTITY_V2, RL_POLICY_IDENTITY_V3, RL_POLICY_IDENTITY_V4,
    RL_POLICY_IDENTITY_V5, RL_POLICY_IDENTITY_V6,
})
COMPANY_POLICY_IDENTITIES = frozenset({"analysis-policy-luna-demo-v1", HP_POLICY_IDENTITY, *RL_POLICY_IDENTITIES})

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
