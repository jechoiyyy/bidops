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
#: RL-03 결정 B51: v6 with item isolation (evidence-class extract failures are
#: isolated per unit; synthesis is told the rejected units and cannot answer
#: "진행 가능").  Extract instruction unchanged from v6.  v1-v6 stay importable.
RL_POLICY_IDENTITY_V7 = "analysis-policy-luna-rl-v7"
#: RL-03 결정 B53: v7 with one sentence in each role instruction and the synthesis
#: evidence rule (a unit's evidence or its constraint locator+quote may be cited).
#: Item isolation as v7.  v1-v7 stay importable.
RL_POLICY_IDENTITY_V8 = "analysis-policy-luna-rl-v8"
#: RL-03 결정 B55: v8 with synthesis output contract ``bidops.practitioner-verdict.v2``
#: (``report_schema``; no blocking ids -- code computes them; code "사람 확인" rows) and
#: a synthesis instruction stating the field scopes.  Extract and role stages are
#: byte-identical to v8 (a v8 failed attempt may be resumed at synthesis).
RL_POLICY_IDENTITY_V9 = "analysis-policy-luna-rl-v9"
#: RL-05 결정 C15: v9 with selector ``card-sections-v4`` (a segment unit above
#: ``batch_max_chars`` is split at block boundaries into ``#p<n>`` parts); 결정 C16:
#: role contract v2 (``card-role-v2``, evidence ids, role item isolation) with the
#: three role instructions rewritten.  Extract/synthesis instructions and contracts
#: are byte-identical to v9.  v1-v9 stay importable.
RL_POLICY_IDENTITY_V10 = "analysis-policy-luna-rl-v10"
RL_POLICY_IDENTITIES = frozenset({
    RL_POLICY_IDENTITY, RL_POLICY_IDENTITY_V2, RL_POLICY_IDENTITY_V3, RL_POLICY_IDENTITY_V4,
    RL_POLICY_IDENTITY_V5, RL_POLICY_IDENTITY_V6, RL_POLICY_IDENTITY_V7, RL_POLICY_IDENTITY_V8,
    RL_POLICY_IDENTITY_V9, RL_POLICY_IDENTITY_V10,
})
COMPANY_POLICY_IDENTITIES = frozenset({"analysis-policy-luna-demo-v1", HP_POLICY_IDENTITY, *RL_POLICY_IDENTITIES})
#: RL-04 proposal drafting (``pipeline_version="proposal-v1"``, ``purpose="proposal"``).
#: Selected only through ``BIDOPS_PROPOSAL_POLICY_VERSION_ID``; it is neither a
#: global deep-review policy nor a company deep-review (card/narrative) policy,
#: so it deliberately stays out of ``COMPANY_POLICY_IDENTITIES``.
PROPOSAL_POLICY_IDENTITY = "proposal-policy-luna-v1"
PROPOSAL_POLICY_IDENTITIES = frozenset({PROPOSAL_POLICY_IDENTITY})

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
