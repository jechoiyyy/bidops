"""Frozen, minimized user prompts for the seven screening calls."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import re
from typing import Any, Final, Mapping

from .contracts import (
    ContractViolation,
    PERSPECTIVE_NAMES,
    canonical_json,
)


class PromptAssemblyError(ValueError):
    """A policy template or its explicitly allowed inputs is invalid."""


# Unicode identifiers catch accidental Korean/Unicode placeholders while
# literal JSON examples (whose first character is a quote) remain untouched.
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{([^\W\d]\w*)\}", re.UNICODE)
_PERSPECTIVE_PLACEHOLDERS: Final[frozenset[str]] = frozenset(
    {"notice_json", "company_profile_sections_json"}
)
_COUNTER_PLACEHOLDERS: Final[frozenset[str]] = frozenset({"notice_json", "perspectives_json"})
_SYNTHESIS_PLACEHOLDERS: Final[frozenset[str]] = frozenset(
    {"notice_json", "perspectives_json", "counterarguments_json"}
)

# This is intentionally narrower than the persisted normalized notice.  In
# particular, raw_source may contain credentials or arbitrary source pages and
# is never sent to a model.  Extra caller keys are never copied.
NOTICE_PROMPT_FIELDS: Final[tuple[str, ...]] = (
    "notice_id", "source_type", "title", "agency", "method", "url",
    "collection_bucket", "published_at", "deadline_at", "budget", "estimated_price",
    "procurement_class", "region_limit", "lifecycle", "qualification_flags", "attachments",
    "focus_matches", "performance_matches", "performance_top_score", "candidate_sources",
    "unknown_fields", "sample_stratum", "sample_role",
)


@dataclass(frozen=True)
class StagePrompt:
    stage: str
    user_message: str
    schema_name: str
    input_fields: tuple[str, ...]
    profile_sections: tuple[str, ...]


def _policy_mapping(policy: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(policy, Mapping):
        return policy
    # ScreeningPolicy is intentionally consumed as a read-only snapshot.  No
    # ORM state is modified and no profile body is read here.
    attrs = (
        "perspective_prompts",
        "perspective_prompts_json",
        "counterargument_prompt",
        "counterargument_prompt_json",
        "synthesis_prompt",
        "synthesis_prompt_json",
    )
    result: dict[str, Any] = {}
    for key in attrs:
        if hasattr(policy, key):
            value = getattr(policy, key)
            result[key.removesuffix("_json")] = value
    if "perspective_prompts" not in result and "perspective_prompts_json" in result:
        result["perspective_prompts"] = result.pop("perspective_prompts_json")
    return result


def _canonical(value: Any, label: str) -> str:
    try:
        return canonical_json(value)
    except ContractViolation as exc:
        raise PromptAssemblyError(f"{label} cannot be canonical JSON") from exc


def _selected_mapping(value: Any, allowed: list[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromptAssemblyError(f"{label} must be an object keyed by sections")
    # Preserve values exactly.  A new mapping is made so replacing template
    # placeholders can never mutate the caller's notice or profile.
    return {key: value[key] for key in allowed if key in value}


def project_notice_for_prompt(notice: Mapping[str, Any]) -> dict[str, Any]:
    """Project a normalized notice without raw source or caller extras."""

    if not isinstance(notice, Mapping):
        raise PromptAssemblyError("notice must be an object")
    return {key: notice[key] for key in NOTICE_PROMPT_FIELDS if key in notice}


def _fill_template(template: Any, values: Mapping[str, Any], required: frozenset[str], *, label: str) -> str:
    if not isinstance(template, str) or not template.strip():
        raise PromptAssemblyError(f"{label} template is blank")
    found = _PLACEHOLDER_RE.findall(template)
    found_set = set(found)
    unknown = found_set - set(required)
    missing = set(required) - found_set
    if unknown or missing:
        suffix = []
        if unknown:
            suffix.append("unknown placeholders: " + ",".join(sorted(unknown)))
        if missing:
            suffix.append("missing placeholders: " + ",".join(sorted(missing)))
        raise PromptAssemblyError(f"{label} template placeholder contract failed ({'; '.join(suffix)})")
    if any(found.count(name) != 1 for name in required):
        raise PromptAssemblyError(f"{label} template must contain each placeholder exactly once")

    def replace(match: re.Match[str]) -> str:
        # A single pass over the original template is essential: canonical
        # input values may themselves contain placeholder-looking text, which
        # must remain data and never be interpreted as another field.
        name = match.group(1)
        return _canonical(values[name], name)

    return _PLACEHOLDER_RE.sub(replace, template)


def _perspective_definition(policy: Mapping[str, Any], perspective_name: str) -> Mapping[str, Any]:
    if perspective_name not in PERSPECTIVE_NAMES:
        raise PromptAssemblyError("unknown perspective name")
    perspectives = policy.get("perspective_prompts")
    if not isinstance(perspectives, Mapping) or perspective_name not in perspectives:
        raise PromptAssemblyError("policy does not contain the exact perspective")
    definition = perspectives[perspective_name]
    if not isinstance(definition, Mapping):
        raise PromptAssemblyError("perspective policy definition is invalid")
    return definition


def assemble_perspective_prompt(
    policy: Mapping[str, Any] | Any,
    perspective_name: str,
    notice: Mapping[str, Any],
    profile_sections: Mapping[str, Any],
) -> StagePrompt:
    """Assemble a perspective prompt using only policy-listed fields/sections."""

    if not isinstance(notice, Mapping):
        raise PromptAssemblyError("notice must be an object")
    if not isinstance(profile_sections, Mapping):
        raise PromptAssemblyError("profile_sections must be an object")
    body = _policy_mapping(policy)
    definition = _perspective_definition(body, perspective_name)
    fields = definition.get("input_fields")
    sections = definition.get("profile_sections")
    if (
        not isinstance(fields, list)
        or any(not isinstance(field, str) or not field.strip() for field in fields)
        or len(set(fields)) != len(fields)
        or not isinstance(sections, list)
        or any(not isinstance(section, str) or not section.strip() for section in sections)
        or len(set(sections)) != len(sections)
        or any(field not in NOTICE_PROMPT_FIELDS for field in fields)
    ):
        raise PromptAssemblyError("policy perspective input allow-list is invalid")
    selected_notice = _selected_mapping(notice, fields, label="notice")
    selected_profile = _selected_mapping(profile_sections, sections, label="profile_sections")
    user_message = _fill_template(
        definition.get("template"),
        {"notice_json": selected_notice, "company_profile_sections_json": selected_profile},
        _PERSPECTIVE_PLACEHOLDERS,
        label=perspective_name,
    )
    if definition.get("output_schema") != "perspective.v1":
        raise PromptAssemblyError("perspective output schema is not perspective.v1")
    return StagePrompt(
        stage=perspective_name,
        user_message=user_message,
        schema_name="perspective.v1",
        input_fields=tuple(fields),
        profile_sections=tuple(sections),
    )


def assemble_counterargument_prompt(
    policy: Mapping[str, Any] | Any,
    notice: Mapping[str, Any],
    perspectives: list[Mapping[str, Any]],
) -> StagePrompt:
    """Assemble the counterargument from exactly notice plus five outputs."""

    body = _policy_mapping(policy)
    definition = body.get("counterargument_prompt")
    if not isinstance(definition, Mapping):
        raise PromptAssemblyError("counterargument policy definition is invalid")
    if definition.get("input_fields") != ["perspectives", "notice"]:
        raise PromptAssemblyError("counterargument allow-list is invalid")
    if definition.get("output_schema") != "counterargument.v1":
        raise PromptAssemblyError("counterargument output schema is invalid")
    if not isinstance(notice, Mapping) or not isinstance(perspectives, list) or len(perspectives) != 5:
        raise PromptAssemblyError("counterargument requires one notice and five perspectives")
    user_message = _fill_template(
        definition.get("template"),
        {"notice_json": project_notice_for_prompt(notice), "perspectives_json": list(perspectives)},
        _COUNTER_PLACEHOLDERS,
        label="counterargument",
    )
    return StagePrompt("반론 검토", user_message, "counterargument.v1", ("notice", "perspectives"), ())


def assemble_synthesis_prompt(
    policy: Mapping[str, Any] | Any,
    notice: Mapping[str, Any],
    perspectives: list[Mapping[str, Any]],
    counterarguments: Mapping[str, Any],
) -> StagePrompt:
    """Assemble synthesis from notice, all perspectives, and counterarguments."""

    body = _policy_mapping(policy)
    definition = body.get("synthesis_prompt")
    if not isinstance(definition, Mapping):
        raise PromptAssemblyError("synthesis policy definition is invalid")
    if definition.get("input_fields") != ["notice", "perspectives", "counterarguments"]:
        raise PromptAssemblyError("synthesis allow-list is invalid")
    if definition.get("output_schema") != "judgment.v3":
        raise PromptAssemblyError("synthesis output schema is invalid")
    if not isinstance(notice, Mapping) or not isinstance(perspectives, list) or len(perspectives) != 5:
        raise PromptAssemblyError("synthesis requires one notice and five perspectives")
    if not isinstance(counterarguments, Mapping):
        raise PromptAssemblyError("synthesis requires counterarguments")
    user_message = _fill_template(
        definition.get("template"),
        {
            "notice_json": project_notice_for_prompt(notice),
            "perspectives_json": list(perspectives),
            "counterarguments_json": dict(counterarguments),
        },
        _SYNTHESIS_PLACEHOLDERS,
        label="synthesis",
    )
    return StagePrompt("종합 판정", user_message, "judgment.v3", ("notice", "perspectives", "counterarguments"), ())


# A compact JSON-schema vocabulary is sent to Ollama's ``format`` field.
# additionalProperties=false is important: the model boundary must not
# silently accept fields which the downstream v3 assembler cannot persist.
PERSPECTIVE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "assessment", "reason", "evidence"],
    "properties": {
        "name": {"type": "string", "enum": list(PERSPECTIVE_NAMES)},
        "assessment": {"type": "string", "enum": ["적합", "부분 적합", "부적합", "확인 불가"]},
        "reason": {"type": "string", "minLength": 10},
        "evidence": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source", "status", "fact"],
                "properties": {
                    "source": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": ["confirmed", "inferred", "unknown"]},
                    "fact": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}
COUNTERARGUMENT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["counterarguments"],
    "properties": {"counterarguments": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}},
}
JUDGMENT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "notice_id", "grade", "readiness", "primary_focus", "exclusion_category", "summary",
        "perspectives", "matched_performances", "counterarguments", "counterargument_resolutions",
        "verification_items", "next_action",
    ],
    "properties": {
        "notice_id": {"type": "string", "minLength": 1},
        "grade": {"type": "string", "enum": ["우선 검토", "검토 권장", "관찰 대상", "제외"]},
        "readiness": {"type": "string", "enum": ["확인 완료", "부분 확인 필요", "참여 불가 확인", "해당 없음"]},
        "primary_focus": {"type": "string", "enum": ["AI/데이터", "블록체인·DID", "공공 SI·통합관리", "해당 없음"]},
        "exclusion_category": {
            "type": ["string", "null"],
            "enum": [
                None, "도메인 불일치", "시설·현장 용역", "공사·인프라", "행사·교육·홍보",
                "연구·조사", "감리·평가", "물품·임차", "자격 미달", "취소·종료", "기타 비관련",
            ],
        },
        "summary": {"type": "string", "minLength": 1},
        "perspectives": {"type": "array", "minItems": 5, "maxItems": 5, "items": PERSPECTIVE_SCHEMA},
        "matched_performances": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "match_reason", "mismatch_or_limit", "source", "status"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "match_reason": {"type": "string", "minLength": 1},
                    "mismatch_or_limit": {"type": "string", "minLength": 1},
                    "source": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": ["confirmed", "inferred", "unknown"]},
                },
            },
        },
        "counterarguments": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        "counterargument_resolutions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["counterargument", "status", "reflection"],
                "properties": {
                    "counterargument": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": ["수용", "기각", "추가 확인"]},
                    "reflection": {"type": "string", "minLength": 1},
                },
            },
        },
        "verification_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "why", "blocking", "status", "requires_attachment"],
                "properties": {
                    "item": {"type": "string", "minLength": 1},
                    "why": {"type": "string", "minLength": 1},
                    "blocking": {"type": "boolean"},
                    "status": {"type": "string", "enum": ["미확인", "확인 완료"]},
                    "requires_attachment": {"type": "boolean"},
                },
            },
        },
        "next_action": {"type": "string", "minLength": 1},
    },
}

SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "perspective.v1": PERSPECTIVE_SCHEMA,
    "counterargument.v1": COUNTERARGUMENT_SCHEMA,
    "judgment.v3": JUDGMENT_SCHEMA,
}


def schema_for_stage(stage: str) -> dict[str, Any]:
    """Return a strict schema, pinning each perspective to its own name."""

    if stage in PERSPECTIVE_NAMES:
        schema = deepcopy(PERSPECTIVE_SCHEMA)
        schema["properties"]["name"] = {"type": "string", "enum": [stage]}
        return schema
    try:
        return deepcopy(SCHEMAS[stage])
    except KeyError as exc:
        raise PromptAssemblyError("unknown model output stage") from exc


__all__ = [
    "COUNTERARGUMENT_SCHEMA", "JUDGMENT_SCHEMA", "PERSPECTIVE_SCHEMA", "PromptAssemblyError",
    "NOTICE_PROMPT_FIELDS", "SCHEMAS", "StagePrompt", "assemble_counterargument_prompt",
    "assemble_perspective_prompt", "assemble_synthesis_prompt", "project_notice_for_prompt",
    "schema_for_stage",
]
