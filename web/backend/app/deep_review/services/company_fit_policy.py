"""Immutable DEMO company-fit policies (``bidops.company-fit-policy.v2``/``v3``).

Demo contract §9: the payload pins the existing fit policy structure plus the
LiteLLM alias ``local-agent-main`` and an optional declared revision (``null``
when the deployment declares none -- never a guessed upstream value).  The
approved policies are canonical JSON files shipped in the image; import
compares the given bytes with those files and stores an append-only
``CompanyFitPolicyVersion`` row.  Import never activates anything: the company
path selects a row only through ``BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID``.

2026-10-11 amendment (STEP-008): ``v3`` is ``v2`` plus a required
``chunking.source_characters`` -- the splitter setting with which a fit links
overview rows to the bundle's source units (``company-fit-demo-v3.json``,
6000, the demo Luna narrative setting so fit and deep unit ids agree).  ``v2``
files/rows stay valid history: importable, readable, and an attempt already
frozen on a v2 row still runs with it.  A **new enqueue** only accepts a v3
row (``resolve_company_fit_enqueue_policy``); a selected v2 row is
``analysis_policy_unavailable``.

Loader rules (``validate_company_fit_policy``), all failing with
``policy_invalid``: exact key set; ``schema_version`` v2 or v3; ``model_name``
non-empty without whitespace; ``model_revision`` null or 64 lowercase hex; the
approved generation; a single ``company_fit`` stage; ``prompt_output_contract``
equal to the code's v2 result schema; ``chunking`` with exactly
``max_characters``, ``path_limit_per_requirement``, ``profile_characters``
(positive ints), ``retries`` (0..approved) and the approved ``timeout_seconds``
-- plus, for v3 only, a positive int ``source_characters`` (no default).  The
``path_limit_per_requirement``/``source_characters`` checks are here because
the model client's chunking check ignores unknown keys (contract §9).
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.config import get_settings
from ...core.model_binding import canonical_json_bytes
from ...core.model_client import APPROVED_GENERATION, APPROVED_RETRIES, APPROVED_TIMEOUT_SECONDS
from ...core.models import AuditEvent
from ..models import CompanyFitPolicyVersion
from ..schemas.company_fit import CompanyFitPayloadV2
from .input_versions import canonical_json_hash


POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"
DEMO_POLICY_V2_FILE = POLICY_DIR / "company-fit-demo-v2.json"
DEMO_POLICY_V3_FILE = POLICY_DIR / "company-fit-demo-v3.json"
#: The policy file a new enqueue can use (v3). v2 is kept, importable history.
DEMO_POLICY_FILE = DEMO_POLICY_V3_FILE
#: Files shipped in the image whose exact bytes may be imported.
APPROVED_POLICY_FILES: tuple[Path, ...] = (DEMO_POLICY_V2_FILE, DEMO_POLICY_V3_FILE)

COMPANY_FIT_POLICY_SCHEMA_V2 = "bidops.company-fit-policy.v2"
COMPANY_FIT_POLICY_SCHEMA_V3 = "bidops.company-fit-policy.v3"
#: The schema a new enqueue requires (contract §9, 2026-10-11).
COMPANY_FIT_POLICY_SCHEMA = COMPANY_FIT_POLICY_SCHEMA_V3
COMPANY_FIT_STAGE = "company_fit"
DEMO_PROMPT_VERSION = "prespec-company-fit-demo-v2"
DEMO_MODEL_NAME = "local-agent-main"
#: v3 split size: equal to ``analysis-policy-luna-demo-v1`` ``chunking.source_characters``.
DEMO_SOURCE_CHARACTERS = 6000
POLICY_KEYS = frozenset({
    "schema_version", "model_name", "model_revision", "prompt_version", "generation",
    "stages", "system_prompt", "prompt_output_contract", "chunking",
})
CHUNKING_KEYS_V2 = frozenset({
    "max_characters", "path_limit_per_requirement", "profile_characters", "retries", "timeout_seconds",
})
CHUNKING_KEYS_V3 = CHUNKING_KEYS_V2 | {"source_characters"}
#: Exact ``chunking`` key set per accepted schema; any other schema is invalid.
CHUNKING_KEYS_BY_SCHEMA: Mapping[str, frozenset[str]] = {
    COMPANY_FIT_POLICY_SCHEMA_V2: CHUNKING_KEYS_V2,
    COMPANY_FIT_POLICY_SCHEMA_V3: CHUNKING_KEYS_V3,
}
_HEX64 = re.compile(r"[0-9a-f]{64}")

#: Added to the v1 fit instruction. Graph paths are retrieval, never fulfilment.
GRAPH_INSTRUCTION = """이 입력에서 notice_refs는 requirements[].id만, company_refs는 profile_facts[].fact_key만 인용한다.
graph_paths는 요구사항의 개념과 회사 지식그래프 노드를 잇는 검색 결과일 뿐 역량 보유·자격 충족·실적 인정 판정이 아니다.
relation=direct는 회사 역량·자격 노드와 직접 연결, partial은 실적·인력 노드가 역량을 뒷받침하는 연결, unmapped는 연결을 찾지 못했다는 뜻이며 미보유나 부적합을 뜻하지 않는다.
각 이유의 graph_path_indexes에는 그 이유가 근거로 쓴 graph_paths의 0부터 시작하는 위치 번호를 적는다. 그 이유의 notice_refs에 있는 요구사항의 경로만 중복 없이 적고, 쓰지 않았으면 빈 배열로 둔다.
경로만으로 scope_match나 scope_mismatch를 만들지 않는다. 경로가 가리키는 회사 사실 중 status=confirmed인 것을 company_refs로 인용해야 한다.
capability의 scope=non_core는 명시적 비주력이며 그것만으로 수행 불가나 미보유를 추론하지 않는다. unknown 사실, coverage.unmapped_requirement_ids, coverage.excluded_fact_keys는 입력의 한계이며 부적합 근거가 아니다.
회사 정보는 가상 시나리오(origin=fictional_scenario)이며 실제 회사의 실적·자격으로 바꾸어 말하지 않는다."""
GRAPH_SYSTEM_PROMPT = "회사 지식그래프 경로는 검색 결과이며 충족 판정이 아니다."


class CompanyFitPolicyError(ValueError):
    """A static, safe code for a rejected or unavailable company-fit policy."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_demo_policy_payload(schema_version: str = COMPANY_FIT_POLICY_SCHEMA_V3) -> dict[str, Any]:
    """The approved demo policy, derived from the v1 fit policy (``company_fit.fit_policy``).

    Used to write ``company-fit-demo-v2.json`` / ``company-fit-demo-v3.json``
    and by tests; runtime reads the stored row, never this builder.  v3 is v2
    with its own ``schema_version`` and ``chunking.source_characters``.
    """

    from .company_fit import INSTRUCTION, SYSTEM_PROMPT

    if schema_version not in CHUNKING_KEYS_BY_SCHEMA:
        raise ValueError("unknown company-fit policy schema")
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "model_name": DEMO_MODEL_NAME,
        "model_revision": None,
        "prompt_version": DEMO_PROMPT_VERSION,
        "generation": dict(APPROVED_GENERATION),
        "stages": [{"stage": COMPANY_FIT_STAGE, "instruction": f"{INSTRUCTION}\n{GRAPH_INSTRUCTION}"}],
        "system_prompt": f"{SYSTEM_PROMPT} {GRAPH_SYSTEM_PROMPT}",
        "prompt_output_contract": CompanyFitPayloadV2.model_json_schema(),
        "chunking": {
            # Whole-prompt cap for the single fit call (same order as the overview cap).
            "max_characters": 120000,
            "path_limit_per_requirement": 32,
            # Profile fact budget (``profile_size``); unknown/qualification facts are always kept.
            "profile_characters": 12000,
            "retries": 0,
            "timeout_seconds": APPROVED_TIMEOUT_SECONDS,
        },
    }
    if schema_version == COMPANY_FIT_POLICY_SCHEMA_V3:
        # Splitter size for the overview rows' source units (DeepReviewService._requirements).
        payload["chunking"]["source_characters"] = DEMO_SOURCE_CHARACTERS
    return payload


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_company_fit_policy(payload: Any) -> dict[str, Any]:
    """Strictly validate one v2 or v3 payload and return a deep copy."""

    def invalid() -> CompanyFitPolicyError:
        return CompanyFitPolicyError("policy_invalid")

    if not isinstance(payload, Mapping) or set(payload) != POLICY_KEYS:
        raise invalid()
    schema = payload["schema_version"]
    if not isinstance(schema, str) or schema not in CHUNKING_KEYS_BY_SCHEMA:
        raise invalid()
    model = payload["model_name"]
    if not isinstance(model, str) or not model or len(model) > 255 or any(char.isspace() for char in model):
        raise invalid()
    revision = payload["model_revision"]
    if revision is not None and (not isinstance(revision, str) or _HEX64.fullmatch(revision) is None):
        raise invalid()
    prompt_version = payload["prompt_version"]
    if not isinstance(prompt_version, str) or not prompt_version.strip() or len(prompt_version) > 128:
        raise invalid()
    if payload["generation"] != APPROVED_GENERATION:
        raise invalid()
    stages = payload["stages"]
    if (
        not isinstance(stages, list)
        or len(stages) != 1
        or not isinstance(stages[0], Mapping)
        or set(stages[0]) != {"stage", "instruction"}
        or stages[0]["stage"] != COMPANY_FIT_STAGE
        or not isinstance(stages[0]["instruction"], str)
        or not stages[0]["instruction"].strip()
    ):
        raise invalid()
    if not isinstance(payload["system_prompt"], str) or not payload["system_prompt"].strip():
        raise invalid()
    if payload["prompt_output_contract"] != CompanyFitPayloadV2.model_json_schema():
        raise invalid()
    chunking = payload["chunking"]
    if not isinstance(chunking, Mapping) or set(chunking) != CHUNKING_KEYS_BY_SCHEMA[schema]:
        raise invalid()
    positive = ["max_characters", "path_limit_per_requirement", "profile_characters"]
    if schema == COMPANY_FIT_POLICY_SCHEMA_V3:
        positive.append("source_characters")
    for key in positive:
        if not _positive_int(chunking[key]):
            raise invalid()
    retries = chunking["retries"]
    if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= APPROVED_RETRIES:
        raise invalid()
    timeout = chunking["timeout_seconds"]
    if not _positive_int(timeout) or timeout != APPROVED_TIMEOUT_SECONDS:
        raise invalid()
    return deepcopy(dict(payload))


def _approved(raw: bytes) -> bool:
    for path in APPROVED_POLICY_FILES:
        try:
            if path.read_bytes() == raw:
                return True
        except OSError:
            continue
    return False


def load_company_fit_policy_file(path: Path) -> tuple[dict[str, Any], bytes, str]:
    """Read canonical policy bytes and match them to an approved image file."""

    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise CompanyFitPolicyError("policy_invalid") from None
    if not isinstance(value, Mapping):
        raise CompanyFitPolicyError("policy_invalid")
    try:
        canonical = canonical_json_bytes(value)
    except (TypeError, ValueError):
        raise CompanyFitPolicyError("policy_invalid") from None
    if raw != canonical:
        raise CompanyFitPolicyError("policy_invalid")
    payload = validate_company_fit_policy(value)
    if not _approved(raw):
        raise CompanyFitPolicyError("policy_unapproved")
    return payload, raw, canonical_json_hash(payload)


@dataclass(frozen=True)
class CompanyFitPolicyImport:
    policy_version_id: UUID
    sha256: str
    created: bool


def import_company_fit_policy(session: Session, path: Path, *, actor: str) -> CompanyFitPolicyImport:
    """Idempotently store an approved policy. The caller owns the transaction."""

    try:
        actor = validate_actor(actor)
    except BundleServiceError:
        raise CompanyFitPolicyError("actor_invalid") from None
    payload, _raw, digest = load_company_fit_policy_file(path)

    def existing() -> CompanyFitPolicyVersion | None:
        return session.scalar(select(CompanyFitPolicyVersion).where(CompanyFitPolicyVersion.sha256 == digest))

    row = existing()
    created = False
    if row is None:
        candidate = CompanyFitPolicyVersion(id=uuid4(), sha256=digest, payload=payload)
        try:
            with session.begin_nested():
                session.add(candidate)
                session.flush()
            row, created = candidate, True
        except IntegrityError:
            row = existing()
            if row is None:
                raise CompanyFitPolicyError("storage_failed") from None
    if row.payload != payload or canonical_json_hash(row.payload) != row.sha256:
        raise CompanyFitPolicyError("storage_failed")
    session.add(AuditEvent(
        actor_kind="human", claimed_name=actor, action="company_fit_policy.import",
        aggregate_type="company_fit_policy_version", aggregate_id=str(row.id),
        safe_metadata={"sha256": row.sha256, "created": created,
                       "schema_version": payload["schema_version"]},
    ))
    session.flush()
    return CompanyFitPolicyImport(policy_version_id=row.id, sha256=row.sha256, created=created)


def policy_row_payload(row: CompanyFitPolicyVersion | None) -> dict[str, Any] | None:
    """The validated payload of an untampered row, or ``None``."""

    if row is None or not isinstance(row.payload, Mapping):
        return None
    try:
        if canonical_json_hash(row.payload) != row.sha256:
            return None
        return validate_company_fit_policy(row.payload)
    except (CompanyFitPolicyError, TypeError, ValueError):
        return None


def resolve_company_fit_policy(session: Session, settings: Any = None) -> tuple[CompanyFitPolicyVersion, dict[str, Any]]:
    """The explicitly configured demo fit policy (v2 or v3), or ``analysis_policy_unavailable``.

    Used for currentness and by the runner's eligibility check, so an attempt
    frozen on a v2 row keeps running while that row is the selected one.  A
    new enqueue uses ``resolve_company_fit_enqueue_policy``.
    """

    settings = settings or get_settings()
    policy_id = getattr(settings, "demo_company_fit_policy_version_id", None)
    if policy_id is None:
        raise CompanyFitPolicyError("analysis_policy_unavailable")
    row = session.get(CompanyFitPolicyVersion, policy_id)
    payload = policy_row_payload(row)
    if row is None or payload is None:
        raise CompanyFitPolicyError("analysis_policy_unavailable")
    return row, payload


def resolve_company_fit_enqueue_policy(
    session: Session, settings: Any = None
) -> tuple[CompanyFitPolicyVersion, dict[str, Any]]:
    """The configured policy for a **new** enqueue: v3 only (contract §9, 2026-10-11).

    A selected v2 row has no ``chunking.source_characters`` to build source
    units with, so it is ``analysis_policy_unavailable`` (never a default size).
    """

    row, payload = resolve_company_fit_policy(session, settings)
    if payload["schema_version"] != COMPANY_FIT_POLICY_SCHEMA_V3:
        raise CompanyFitPolicyError("analysis_policy_unavailable")
    return row, payload


__all__ = [
    "APPROVED_POLICY_FILES",
    "CHUNKING_KEYS_BY_SCHEMA",
    "COMPANY_FIT_POLICY_SCHEMA",
    "COMPANY_FIT_POLICY_SCHEMA_V2",
    "COMPANY_FIT_POLICY_SCHEMA_V3",
    "COMPANY_FIT_STAGE",
    "CompanyFitPolicyError",
    "CompanyFitPolicyImport",
    "DEMO_POLICY_FILE",
    "DEMO_POLICY_V2_FILE",
    "DEMO_POLICY_V3_FILE",
    "DEMO_SOURCE_CHARACTERS",
    "build_demo_policy_payload",
    "import_company_fit_policy",
    "load_company_fit_policy_file",
    "policy_row_payload",
    "resolve_company_fit_enqueue_policy",
    "resolve_company_fit_policy",
    "validate_company_fit_policy",
]
