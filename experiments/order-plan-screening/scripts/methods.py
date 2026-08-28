"""Deterministic scorers and isolated model adapters for the experiment."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from common import ExperimentError, fixed_batches, model_batch_payload


def model_batch_output_schema(batch_count: int) -> dict[str, Any]:
    if batch_count < 1:
        raise ExperimentError("invalid_batch_size", "모델 batch에는 한 건 이상이 필요합니다")
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "minItems": batch_count,
                "maxItems": batch_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "item_id": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": batch_count - 1,
                        },
                        "relevance": {
                            "type": "string",
                            "enum": ["relevant", "not_relevant", "uncertain"],
                        },
                        "score": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                    },
                    "required": ["item_id", "relevance", "score", "reason"],
                },
            },
        },
        "required": ["items"],
    }


@dataclass
class AdapterResult:
    score: float
    reason: str
    latency_ms: int
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    device: str | None = None
    relevance: str | None = None
    evidence_fields: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AdapterFailure(RuntimeError):
    def __init__(self, error_code: str, latency_ms: int | None = None):
        super().__init__(error_code)
        self.error_code = error_code
        self.latency_ms = latency_ms


def _normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    return re.sub(r"\s+", " ", text).strip()


def _validated_reason(value: Any, latency_ms: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
        raise AdapterFailure("malformed_response", latency_ms)
    return " ".join(value.strip().split())


def _split_measurement(value: int | None, count: int) -> list[int | None]:
    if value is None:
        return [None] * count
    quotient, remainder = divmod(value, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


def validate_model_batch_output(
    value: Any,
    latency_ms: int,
    expected_count: int,
    usage: dict[str, Any] | None = None,
) -> list[AdapterResult]:
    if not isinstance(value, dict) or set(value) != {"items"}:
        raise AdapterFailure("malformed_response", latency_ms)
    items = value["items"]
    if not isinstance(items, list) or len(items) != expected_count:
        raise AdapterFailure("malformed_response", latency_ms)
    by_id: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"item_id", "relevance", "score", "reason"}:
            raise AdapterFailure("malformed_response", latency_ms)
        item_id = item["item_id"]
        if (
            not isinstance(item_id, int)
            or isinstance(item_id, bool)
            or not 0 <= item_id < expected_count
            or item_id in by_id
        ):
            raise AdapterFailure("malformed_response", latency_ms)
        if item["relevance"] not in {"relevant", "not_relevant", "uncertain"}:
            raise AdapterFailure("malformed_response", latency_ms)
        score = item["score"]
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not 0 <= float(score) <= 1
        ):
            raise AdapterFailure("malformed_response", latency_ms)
        _validated_reason(item["reason"], latency_ms)
        by_id[item_id] = item
    if set(by_id) != set(range(expected_count)):
        raise AdapterFailure("population_coverage_mismatch", latency_ms)
    if usage is None:
        usage = {}
    elif not isinstance(usage, dict):
        raise AdapterFailure("malformed_response", latency_ms)
    input_details = (
        usage.get("input_tokens_details")
        or usage.get("prompt_tokens_details")
        or {}
    )
    if not isinstance(input_details, dict):
        raise AdapterFailure("malformed_response", latency_ms)
    input_parts = _split_measurement(
        _nullable_nonnegative_int(_first_not_none(usage.get("input_tokens"), usage.get("prompt_tokens"))),
        expected_count,
    )
    cached_parts = _split_measurement(
        _nullable_nonnegative_int(
            _first_not_none(input_details.get("cached_tokens"), usage.get("cached_input_tokens"))
        ),
        expected_count,
    )
    output_parts = _split_measurement(
        _nullable_nonnegative_int(
            _first_not_none(usage.get("output_tokens"), usage.get("completion_tokens"))
        ),
        expected_count,
    )
    latency_parts = _split_measurement(latency_ms, expected_count)
    results: list[AdapterResult] = []
    for item_id in range(expected_count):
        item = by_id[item_id]
        results.append(
            AdapterResult(
                score=float(item["score"]),
                reason=_validated_reason(item["reason"], latency_ms),
                latency_ms=int(latency_parts[item_id]),
                input_tokens=input_parts[item_id],
                cached_input_tokens=cached_parts[item_id],
                output_tokens=output_parts[item_id],
                relevance=item["relevance"],
                evidence_fields=["title"],
            )
        )
    return results


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _nullable_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def run_fixed_model_batches(
    plans: Sequence[dict[str, Any]],
    batch_size: int,
    score_batch: Callable[[Sequence[dict[str, Any]]], list[AdapterResult]],
) -> list[AdapterResult | AdapterFailure]:
    """Execute every fixed batch once and contain failures to that batch."""

    outcomes: list[AdapterResult | AdapterFailure] = []
    for batch in fixed_batches(plans, batch_size):
        try:
            results = score_batch(batch)
            if len(results) != len(batch) or not all(
                isinstance(result, AdapterResult) for result in results
            ):
                raise AdapterFailure("population_coverage_mismatch")
            outcomes.extend(results)
        except AdapterFailure as exc:
            latency_parts = _split_measurement(exc.latency_ms, len(batch))
            outcomes.extend(
                AdapterFailure(exc.error_code, latency_parts[index])
                for index in range(len(batch))
            )
    return outcomes


class KeywordAdapter:
    def __init__(self, config: dict[str, Any]):
        self.positive_rules = self._validate_rules(config.get("positive_rules"), positive=True)
        self.negative_rules = self._validate_rules(config.get("negative_rules"), positive=False)

    @staticmethod
    def _validate_rules(value: Any, positive: bool) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ExperimentError("invalid_keyword_rules", "keyword rules는 배열이어야 합니다")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, rule in enumerate(value):
            if not isinstance(rule, dict) or set(rule) != {"id", "fields", "terms", "weight"}:
                raise ExperimentError("invalid_keyword_rules", f"keyword rule[{index}] 형식이 잘못됐습니다")
            rule_id = rule["id"]
            fields = rule["fields"]
            terms = rule["terms"]
            weight = rule["weight"]
            if not isinstance(rule_id, str) or not rule_id or rule_id in seen:
                raise ExperimentError("invalid_keyword_rules", "keyword rule id가 비었거나 중복됐습니다")
            if fields != ["title"]:
                raise ExperimentError("invalid_keyword_rules", f"keyword rule {rule_id} fields는 title 하나여야 합니다")
            if not isinstance(terms, list) or not terms or not all(isinstance(v, str) and v for v in terms):
                raise ExperimentError("invalid_keyword_rules", f"keyword rule {rule_id} terms가 잘못됐습니다")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or float(weight) <= 0:
                raise ExperimentError("invalid_keyword_rules", f"keyword rule {rule_id} weight가 잘못됐습니다")
            seen.add(rule_id)
            result.append(
                {
                    "id": rule_id,
                    "fields": fields,
                    "terms": [_normalize_text(term) for term in terms],
                    "weight": float(weight) if positive else -float(weight),
                }
            )
        return result

    def score(self, plan: dict[str, Any], _capabilities: dict[str, Any]) -> AdapterResult:
        started = time.monotonic()
        hits: list[str] = []
        score = 0.0
        for rule in self.positive_rules + self.negative_rules:
            for field_name in rule["fields"]:
                if field_name not in plan:
                    raise AdapterFailure("keyword_field_missing")
                haystack = _normalize_text(plan[field_name])
                if any(term in haystack for term in rule["terms"]):
                    score += rule["weight"]
                    hits.append(f"{rule['id']}@{field_name}")
                    break
        latency = max(0, round((time.monotonic() - started) * 1000))
        reason = "matched:" + ",".join(hits) if hits else "no_rule_match"
        return AdapterResult(score=score, reason=reason, latency_ms=latency, device="cpu")


class BGEM3ColBERTAdapter:
    """Use the official FlagEmbedding late-interaction score at a fixed model revision."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def score_all(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult]:
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
            from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AdapterFailure("adapter_dependency_missing") from exc
        capability_rows = capabilities.get("capabilities") or []
        if not capability_rows:
            raise AdapterFailure("capabilities_empty")
        model_name = self.config["model_name"]
        revision = self.config["model_revision"]
        device = self.config.get("device", "cpu")
        devices = [device] if device != "cpu" else None
        started = time.monotonic()
        try:
            model_path = snapshot_download(repo_id=model_name, revision=revision)
            model = BGEM3FlagModel(
                model_path,
                use_fp16=bool(self.config.get("use_fp16", False)),
                devices=devices,
            )
            query_texts = [row["summary"] for row in capability_rows]
            passage_texts = [plan_text(plan) for plan in plans]
            encode_options = {
                "batch_size": int(self.config.get("batch_size", 12)),
                "max_length": int(self.config.get("max_length", 512)),
                "return_dense": False,
                "return_sparse": False,
                "return_colbert_vecs": True,
            }
            query_vectors = model.encode(query_texts, **encode_options)["colbert_vecs"]
            passage_vectors = model.encode(passage_texts, **encode_options)["colbert_vecs"]
            scored: list[tuple[float, str]] = []
            for passage_vector in passage_vectors:
                candidates = [
                    (
                        float((query_vector @ passage_vector.T).max(axis=1).mean()),
                        capability_rows[index]["id"],
                    )
                    for index, query_vector in enumerate(query_vectors)
                ]
                scored.append(max(candidates, key=lambda item: (item[0], item[1])))
        except AdapterFailure:
            raise
        except Exception as exc:
            raise AdapterFailure("adapter_execution_failed") from exc
        total_latency = max(0, round((time.monotonic() - started) * 1000))
        per_item = round(total_latency / len(plans)) if plans else 0
        return [
            AdapterResult(
                score=score,
                reason=f"nearest_capability:{capability_id}",
                latency_ms=per_item,
                device=device,
            )
            for score, capability_id in scored
        ]


def plan_text(plan: dict[str, Any]) -> str:
    title = plan.get("title")
    if not isinstance(title, str) or not title.strip():
        raise AdapterFailure("title_missing")
    return title


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class SafeJsonHttpClient:
    def __init__(self, timeout: int):
        if timeout < 1:
            raise ExperimentError("invalid_http_config", "model timeout은 1 이상이어야 합니다")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[dict[str, Any], int]:
        started = time.monotonic()
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=encoded,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8", errors="strict")
            document = json.loads(payload)
        except urllib.error.HTTPError as exc:
            latency = max(0, round((time.monotonic() - started) * 1000))
            raise AdapterFailure(f"model_http_{exc.code}", latency) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            latency = max(0, round((time.monotonic() - started) * 1000))
            reason = getattr(exc, "reason", None)
            code = "timeout" if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) else "model_unavailable"
            raise AdapterFailure(code, latency) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            latency = max(0, round((time.monotonic() - started) * 1000))
            raise AdapterFailure("malformed_response", latency) from exc
        latency = max(0, round((time.monotonic() - started) * 1000))
        if not isinstance(document, dict):
            raise AdapterFailure("malformed_response", latency)
        return document, latency

    def get(self, url: str, headers: dict[str, str]) -> tuple[dict[str, Any], int]:
        started = time.monotonic()
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", **headers},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8", errors="strict")
            document = json.loads(payload)
        except urllib.error.HTTPError as exc:
            latency = max(0, round((time.monotonic() - started) * 1000))
            raise AdapterFailure(f"model_http_{exc.code}", latency) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            latency = max(0, round((time.monotonic() - started) * 1000))
            reason = getattr(exc, "reason", None)
            code = "timeout" if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) else "model_unavailable"
            raise AdapterFailure(code, latency) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            latency = max(0, round((time.monotonic() - started) * 1000))
            raise AdapterFailure("malformed_response", latency) from exc
        latency = max(0, round((time.monotonic() - started) * 1000))
        if not isinstance(document, dict):
            raise AdapterFailure("malformed_response", latency)
        return document, latency


def validate_local_base_url(
    value: str,
    allowed_hosts: Iterable[str],
    api_style: str = "openai_compatible",
) -> str:
    parsed = urllib.parse.urlsplit(value)
    expected_paths = {"", "/"} if api_style == "ollama_native" else {"/v1", "/v1/"}
    if (
        api_style not in {"ollama_native", "openai_compatible"}
        or parsed.scheme not in {"http", "https"}
        or parsed.hostname not in set(allowed_hosts)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in expected_paths
    ):
        raise ExperimentError("model_endpoint_rejected", "Qwen base URL이 승인된 endpoint 계약과 다릅니다")
    return value.rstrip("/")


class QwenAdapter:
    def __init__(self, config: dict[str, Any], prompt: str):
        env_name = config.get("base_url_env")
        if not isinstance(env_name, str) or not env_name:
            raise ExperimentError("model_endpoint_missing", "Qwen base URL 환경변수 이름이 없습니다")
        base_url = os.environ.get(env_name, "").strip()
        if not base_url:
            raise ExperimentError("model_endpoint_missing", f"{env_name}가 필요합니다")
        self.api_style = config.get("api_style", "ollama_native")
        validated_base = validate_local_base_url(
            base_url, config.get("allowed_hosts") or [], self.api_style
        )
        self.url = (
            validated_base + "/api/chat"
            if self.api_style == "ollama_native"
            else validated_base + "/chat/completions"
        )
        self.tags_url = validated_base + "/api/tags" if self.api_style == "ollama_native" else None
        self.model_name = config["model_name"]
        self.model_revision = config["model_revision"]
        self.prompt = prompt
        self.client = SafeJsonHttpClient(int(config.get("timeout_seconds", 120)))
        self.batch_size = int(config["batch_size"])
        self.max_output_tokens = int(config.get("max_output_tokens", 4096))
        self.think = config.get("think", "high")
        self.revision_env = config.get("revision_env")
        self._revision_verified = False

    def verify_model_revision(self) -> None:
        if self._revision_verified:
            return
        if self.api_style == "ollama_native":
            response, latency = self.client.get(str(self.tags_url), {})
            models = response.get("models")
            if not isinstance(models, list):
                raise AdapterFailure("model_revision_unverifiable", latency)
            matches = [
                row
                for row in models
                if isinstance(row, dict)
                and self.model_name in {row.get("name"), row.get("model")}
            ]
            if len(matches) != 1 or matches[0].get("digest") != self.model_revision:
                raise AdapterFailure("model_revision_mismatch", latency)
        else:
            if not isinstance(self.revision_env, str) or not self.revision_env:
                raise AdapterFailure("model_revision_unverifiable")
            deployed_revision = os.environ.get(self.revision_env, "").strip()
            if deployed_revision != self.model_revision:
                raise AdapterFailure("model_revision_mismatch")
        self._revision_verified = True

    def prepare(self) -> None:
        self.verify_model_revision()

    def _score_batch(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult]:
        payload = model_batch_payload(plans, capabilities)
        output_schema = model_batch_output_schema(len(plans))
        messages = [
            {"role": "system", "content": self.prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            },
        ]
        if self.api_style == "ollama_native":
            body = {
                "model": self.model_name,
                "messages": messages,
                "stream": False,
                "format": output_schema,
                "think": self.think,
                "options": {"temperature": 0, "num_predict": self.max_output_tokens},
            }
        else:
            body = {
                "model": self.model_name,
                "messages": messages,
                "stream": False,
                "temperature": 0,
                "max_tokens": self.max_output_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "order_plan_relevance",
                        "strict": True,
                        "schema": output_schema,
                    },
                },
            }
        headers: dict[str, str] = {}
        key = os.environ.get("BIDOPS_QWEN_API_KEY", "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        response, latency = self.client.post(self.url, body, headers)
        try:
            if self.api_style == "ollama_native":
                if response.get("done") is not True:
                    raise AdapterFailure("model_failed", latency)
                if response.get("done_reason") == "length":
                    raise AdapterFailure("truncated_output", latency)
                content = response["message"]["content"]
                usage = {
                    "input_tokens": response.get("prompt_eval_count"),
                    "output_tokens": response.get("eval_count"),
                }
            else:
                choice = response["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise AdapterFailure("truncated_output", latency)
                if choice.get("finish_reason") not in {None, "stop"}:
                    raise AdapterFailure("model_failed", latency)
                content = choice["message"]["content"]
                usage = response.get("usage")
            output = json.loads(content)
        except AdapterFailure:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AdapterFailure("malformed_response", latency) from exc
        return validate_model_batch_output(output, latency, len(plans), usage)

    def score_many(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult | AdapterFailure]:
        self.verify_model_revision()
        return run_fixed_model_batches(
            plans,
            self.batch_size,
            lambda batch: self._score_batch(batch, capabilities),
        )


class LunaAdapter:
    API_URL = "https://api.openai.com/v1/responses"

    def __init__(self, config: dict[str, Any], prompt: str):
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ExperimentError("openai_api_key_missing", "OPENAI_API_KEY가 필요합니다")
        self.key = key
        # The approval and run binding target the exact API model identifier,
        # not a mutable family alias.
        self.model_name = config["model_revision"]
        self.reasoning_effort = config["reasoning_effort"]
        self.prompt = prompt
        self.client = SafeJsonHttpClient(int(config.get("timeout_seconds", 180)))
        self.batch_size = int(config["batch_size"])
        self.max_output_tokens = int(config.get("max_output_tokens", 8192))

    def _score_batch(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult]:
        payload = model_batch_payload(plans, capabilities)
        body = {
            "model": self.model_name,
            "instructions": self.prompt,
            "input": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "order_plan_relevance",
                    "strict": True,
                    "schema": model_batch_output_schema(len(plans)),
                }
            },
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        response, latency = self.client.post(
            self.API_URL, body, {"Authorization": f"Bearer {self.key}"}
        )
        if response.get("status") == "incomplete":
            raise AdapterFailure("truncated_output", latency)
        if response.get("status") != "completed":
            raise AdapterFailure("model_failed", latency)
        texts: list[str] = []
        for output_item in response.get("output") or []:
            if not isinstance(output_item, dict) or output_item.get("type") != "message":
                continue
            for content in output_item.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    texts.append(str(content.get("text") or ""))
        try:
            output = json.loads("".join(texts))
        except json.JSONDecodeError as exc:
            raise AdapterFailure("malformed_response", latency) from exc
        return validate_model_batch_output(output, latency, len(plans), response.get("usage"))

    def score_many(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult | AdapterFailure]:
        return run_fixed_model_batches(
            plans,
            self.batch_size,
            lambda batch: self._score_batch(batch, capabilities),
        )


class FakeAdapter:
    """Test-only adapter that never opens a network connection."""

    def __init__(
        self,
        scores: dict[str, float] | None = None,
        failures: dict[str, str] | None = None,
        malformed_ids: set[str] | None = None,
    ):
        self.scores = scores or {}
        self.failures = failures or {}
        self.malformed_ids = malformed_ids or set()
        self.calls: list[str] = []

    def score(self, plan: dict[str, Any], _capabilities: dict[str, Any]) -> AdapterResult:
        plan_id = plan["plan_id"]
        self.calls.append(plan_id)
        if plan_id in self.failures:
            raise AdapterFailure(self.failures[plan_id], 1)
        if plan_id in self.malformed_ids:
            raise AdapterFailure("malformed_response", 1)
        return AdapterResult(
            score=float(self.scores.get(plan_id, 0.5)),
            reason="fake",
            latency_ms=1,
            input_tokens=1,
            output_tokens=1,
            device="fake",
        )
