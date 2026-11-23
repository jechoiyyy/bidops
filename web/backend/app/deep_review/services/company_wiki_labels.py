"""Optional presentation metadata for the company's profile."""

import re
from typing import Literal

from pydantic import BaseModel, Field


class FieldLabel(BaseModel):
    label: str
    unit: Literal["krw", "percent", "people", "count"] | None = None
    values: dict[str, str] = {}


class Labels(BaseModel):
    schema_id: Literal["bidops.wiki-labels.v1"] = Field(alias="schema")
    sections: dict[str, str] = {}
    hidden: list[str] = []
    fields: dict[str, FieldLabel] = {}

    def lookup(self, path):
        if path in self.fields:
            return self.fields[path], ""
        for pattern, field in self.fields.items():
            key = wildcard_key(pattern, path)
            if key is not None:
                return field, key
        return None, ""

    def hides(self, path):
        return any(path == pattern or wildcard_key(pattern, path) is not None for pattern in self.hidden)


def wildcard_key(pattern, path):
    keys = pattern.split(".")
    parts = path.split(".")
    if len(keys) == len(parts) and "*" in keys:
        if all(key == "*" or key == part for key, part in zip(keys, parts)):
            return parts[keys.index("*")]
    return None


def display_value(value, field):
    if not field or value in (None, "unknown", ""):
        return value
    if value in field.values:
        return field.values[value]
    if field.unit == "krw" and re.fullmatch(r"-?[0-9]+", value):
        eok, remainder = divmod(abs(int(value)), 100_000_000)
        man, won = divmod(remainder, 10_000)
        chunks = [f"{n:,}{suffix}" for n, suffix in ((eok, "억"), (man, "만"), (won, "")) if n]
        return ("-" if value.startswith("-") else "") + (" ".join(chunks) or "0") + " 원"
    suffix = {"percent": "%", "people": "명", "count": "건"}.get(field.unit)
    return value + suffix if suffix and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) else value
