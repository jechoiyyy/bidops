"""Small dependency-free JSON Schema subset used by the deep-review boundary."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


class SchemaError(ValueError):
    """Raised when a schema itself is not supported or is malformed."""


class SchemaValidationError(ValueError):
    """Raised when a payload violates a contract schema."""

    def __init__(self, message: str, *, path: str = "$") -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": _is_number(value) and math.isfinite(value),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _valid_rfc3339_datetime(value: str) -> bool:
    """Return whether *value* is a real, timezone-aware RFC 3339 timestamp.

    The wire schemas retain their strict seconds-and-offset regex, while this
    semantic check rejects impossible calendar/time values such as February
    30th, hour 25, or an offset outside the RFC 3339 range.
    """

    if re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        value,
    ) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_rfc3339_date(value: str) -> bool:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _resolve(ref: str, root: Mapping[str, Any]) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise SchemaError(f"only local refs are supported: {ref}")
    current: Any = root
    for component in ref[2:].split("/"):
        component = component.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or component not in current:
            raise SchemaError(f"unresolved ref: {ref}")
        current = current[component]
    if not isinstance(current, Mapping):
        raise SchemaError(f"ref does not resolve to an object: {ref}")
    return current


def validate_json_schema(value: Any, schema: Mapping[str, Any], *, path: str = "$", _root: Mapping[str, Any] | None = None) -> None:
    """Validate the contract subset used here.

    This intentionally handles the standard structural keywords used by the
    five schemas (including local ``$ref``, ``oneOf`` and ``if/then``).  The
    service validator handles graph and cross-payload semantics.
    """

    root = _root or schema
    if "$ref" in schema:
        validate_json_schema(value, _resolve(str(schema["$ref"]), root), path=path, _root=root)
        return
    if "allOf" in schema:
        for index, branch in enumerate(schema["allOf"]):
            validate_json_schema(value, branch, path=path, _root=root)
    if "anyOf" in schema or "oneOf" in schema:
        key = "anyOf" if "anyOf" in schema else "oneOf"
        successes = 0
        errors: list[str] = []
        for branch in schema[key]:
            try:
                validate_json_schema(value, branch, path=path, _root=root)
            except SchemaValidationError as exc:
                errors.append(str(exc))
            else:
                successes += 1
        required_successes = 1 if key == "anyOf" else 1
        if successes < required_successes or (key == "oneOf" and successes != 1):
            raise SchemaValidationError(f"must satisfy exactly one contract branch ({'; '.join(errors)})", path=path)
    if "not" in schema:
        try:
            validate_json_schema(value, schema["not"], path=path, _root=root)
        except SchemaValidationError:
            pass
        else:
            raise SchemaValidationError("must not satisfy the excluded schema", path=path)
    if "const" in schema and value != schema["const"]:
        raise SchemaValidationError(f"must equal {schema['const']!r}", path=path)
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"must be one of {schema['enum']!r}", path=path)
    if "type" in schema:
        expected = schema["type"]
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, item) for item in expected_types):
            raise SchemaValidationError(f"must be {expected_types!r}", path=path)
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaValidationError("is shorter than minLength", path=path)
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaValidationError("is longer than maxLength", path=path)
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise SchemaValidationError("does not match pattern", path=path)
        if schema.get("format") == "date-time" and not _valid_rfc3339_datetime(value):
            raise SchemaValidationError("must be a valid timezone-aware RFC 3339 date-time", path=path)
        if schema.get("format") == "date" and not _valid_rfc3339_date(value):
            raise SchemaValidationError("must be a valid RFC 3339 full-date", path=path)
    if _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError("is below minimum", path=path)
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise SchemaValidationError("is not above exclusiveMinimum", path=path)
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError("is above maximum", path=path)
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise SchemaValidationError("is not below exclusiveMaximum", path=path)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaValidationError("has too few items", path=path)
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaValidationError("has too many items", path=path)
        if schema.get("uniqueItems"):
            fingerprints = [repr(item) for item in value]
            if len(fingerprints) != len(set(fingerprints)):
                raise SchemaValidationError("items must be unique", path=path)
        if "items" in schema:
            for index, item in enumerate(value):
                validate_json_schema(item, schema["items"], path=f"{path}[{index}]", _root=root)
    if isinstance(value, Mapping):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise SchemaValidationError(f"missing required field(s): {', '.join(missing)}", path=path)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise SchemaValidationError(f"additional properties are not allowed: {', '.join(extras)}", path=path)
        for key, child_schema in properties.items():
            if key in value:
                validate_json_schema(value[key], child_schema, path=f"{path}.{key}", _root=root)
        if isinstance(schema.get("additionalProperties"), Mapping):
            for key, child in value.items():
                if key not in properties:
                    validate_json_schema(child, schema["additionalProperties"], path=f"{path}.{key}", _root=root)
        for condition in schema.get("allOf", []):
            if isinstance(condition, Mapping) and "if" in condition:
                try:
                    validate_json_schema(value, condition["if"], path=path, _root=root)
                except SchemaValidationError:
                    if "else" in condition:
                        validate_json_schema(value, condition["else"], path=path, _root=root)
                else:
                    if "then" in condition:
                        validate_json_schema(value, condition["then"], path=path, _root=root)
