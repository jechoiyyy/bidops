"""Immutable, credential-free gateway model information; no network or SDK dependencies."""

import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    alias: str
    upstream: str
    input_per_token: float = Field(ge=0)
    output_per_token: float = Field(ge=0)
    cache_read_per_token: float = Field(ge=0)
    cache_write_per_token: float | None = Field(default=None, ge=0)
    cache_write_1h_per_token: float | None = Field(default=None, ge=0)
    context_tokens: int = Field(gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supported_params: tuple[str, ...] = ()
    supports_tools: bool = False
    deployment_fingerprint: str | None = None

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class ModelCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)
    models: tuple[ModelSpec, ...]

    def resolve(self, name: str) -> ModelSpec:
        aliases = [m for m in self.models if m.alias == name]
        if len(aliases) == 1:
            return aliases[0]
        name = re.sub(r"-\d{8}$", "", name)
        aliases = [m for m in self.models if m.alias == name]
        if len(aliases) == 1:
            return aliases[0]
        matches = [m for m in self.models if name in (m.upstream, m.upstream.split("/", 1)[-1])]
        # Never assign an exact price when multiple deployments disagree.
        signatures = {json.dumps(m.model_dump(exclude={"alias"}), sort_keys=True) for m in matches}
        if matches and len(signatures) == 1:
            return matches[0]
        raise ValueError(f"unknown or ambiguous gateway model: {name}")
