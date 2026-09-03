"""Deterministic scorers and isolated model adapters for the experiment."""

from __future__ import annotations

import json
import http.client
import math
import os
import re
import socket
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
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


class TfidfAdapter:
    """Deterministic character n-gram TF-IDF over capabilities and plan titles."""

    def __init__(self, config: dict[str, Any]):
        if config.get("analyzer") != "char":
            raise ExperimentError("invalid_tfidf_config", "TF-IDF analyzer는 char로 고정됩니다")
        self.ngram_min = config.get("ngram_min")
        self.ngram_max = config.get("ngram_max")
        if (
            not isinstance(self.ngram_min, int)
            or isinstance(self.ngram_min, bool)
            or not isinstance(self.ngram_max, int)
            or isinstance(self.ngram_max, bool)
            or not 1 <= self.ngram_min <= self.ngram_max <= 8
        ):
            raise ExperimentError("invalid_tfidf_config", "TF-IDF n-gram 범위가 잘못됐습니다")
        if config.get("tf") != "sublinear" or config.get("idf") != "smooth":
            raise ExperimentError("invalid_tfidf_config", "TF-IDF tf/idf 계약이 잘못됐습니다")
        if config.get("normalization") != "l2" or config.get("capability_aggregation") != "max_cosine":
            raise ExperimentError("invalid_tfidf_config", "TF-IDF 정규화/집계 계약이 잘못됐습니다")

    def _features(self, value: str) -> Counter[str]:
        text = unicodedata.normalize("NFKC", _normalize_text(value))
        if not text:
            raise AdapterFailure("text_missing")
        features: Counter[str] = Counter()
        for size in range(self.ngram_min, self.ngram_max + 1):
            for index in range(max(0, len(text) - size + 1)):
                features[text[index : index + size]] += 1
        if not features:
            features[text] = 1
        return features

    @staticmethod
    def _vector(counts: Counter[str], idf: dict[str, float]) -> dict[str, float]:
        weighted = {
            feature: (1.0 + math.log(count)) * idf[feature]
            for feature, count in counts.items()
        }
        norm = math.sqrt(sum(value * value for value in weighted.values()))
        if norm <= 0 or not math.isfinite(norm):
            raise AdapterFailure("adapter_execution_failed")
        return {feature: value / norm for feature, value in weighted.items()}

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if len(left) > len(right):
            left, right = right, left
        return sum(value * right.get(feature, 0.0) for feature, value in left.items())

    def score_all(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult]:
        started = time.monotonic()
        capability_rows = capabilities.get("capabilities") or []
        if not capability_rows:
            raise AdapterFailure("capabilities_empty")
        try:
            capability_counts = [self._features(row["summary"]) for row in capability_rows]
            title_counts = [self._features(plan_text(plan)) for plan in plans]
            documents = capability_counts + title_counts
            document_frequency: Counter[str] = Counter()
            for counts in documents:
                document_frequency.update(counts.keys())
            document_count = len(documents)
            idf = {
                feature: math.log((1.0 + document_count) / (1.0 + frequency)) + 1.0
                for feature, frequency in document_frequency.items()
            }
            capability_vectors = [self._vector(counts, idf) for counts in capability_counts]
            title_vectors = [self._vector(counts, idf) for counts in title_counts]
            scored: list[tuple[float, str]] = []
            for title_vector in title_vectors:
                candidates = [
                    (
                        self._cosine(capability_vectors[index], title_vector),
                        capability_rows[index]["id"],
                    )
                    for index in range(len(capability_rows))
                ]
                scored.append(max(candidates, key=lambda item: (item[0], item[1])))
        except AdapterFailure:
            raise
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise AdapterFailure("adapter_execution_failed") from exc
        total_latency = max(0, round((time.monotonic() - started) * 1000))
        latency_parts = _split_measurement(total_latency, len(plans))
        return [
            AdapterResult(
                score=score,
                reason=f"nearest_capability:{capability_id}",
                latency_ms=int(latency_parts[index]),
                device="cpu",
            )
            for index, (score, capability_id) in enumerate(scored)
        ]


class BM25Adapter:
    """Deterministic character n-gram BM25 over capabilities and plan titles.

    ADR-0021 개정이 채택한 arm이다. 제목은 중앙값 30자라 term frequency 포화(k1)와
    문서 길이 정규화(b)가 거의 작동하지 않는다. 그래서 이 arm은 사실상 IDF 가중
    단어 겹침이며, 지배적 실패는 어휘 불일치다. 그 실패를 dense arm이 복구하는지가
    이 실험의 측정 대상이다.

    토큰화는 문자 n-gram으로 고정했다. TfidfAdapter와 같은 토큰화를 써야 두 arm의
    차이가 순수하게 가중 방식 차이로 드러나고, 외부 사전 의존성과 `데이터플랫폼`
    대 `데이터 플랫폼` 띄어쓰기 문제를 함께 피한다.

    질의는 capability summary, 문서는 발주계획 제목이다. capability를 하나로 합치면
    신호가 희석되므로 각각 조회하고 max를 취한다(ADR-0021 개정의 제약).
    """

    def __init__(self, config: dict[str, Any]):
        if config.get("analyzer") != "char":
            raise ExperimentError("invalid_bm25_config", "BM25 analyzer는 char로 고정됩니다")
        self.ngram_min = config.get("ngram_min")
        self.ngram_max = config.get("ngram_max")
        if (
            not isinstance(self.ngram_min, int)
            or isinstance(self.ngram_min, bool)
            or not isinstance(self.ngram_max, int)
            or isinstance(self.ngram_max, bool)
            or not 1 <= self.ngram_min <= self.ngram_max <= 8
        ):
            raise ExperimentError("invalid_bm25_config", "BM25 n-gram 범위가 잘못됐습니다")
        self.k1 = config.get("k1")
        self.b = config.get("b")
        if (
            not isinstance(self.k1, (int, float))
            or isinstance(self.k1, bool)
            or not isinstance(self.b, (int, float))
            or isinstance(self.b, bool)
            or not 0.0 <= float(self.k1) <= 5.0
            or not 0.0 <= float(self.b) <= 1.0
        ):
            raise ExperimentError("invalid_bm25_config", "BM25 k1/b 범위가 잘못됐습니다")
        self.k1 = float(self.k1)
        self.b = float(self.b)
        if config.get("query_term_frequency") != "binary":
            raise ExperimentError("invalid_bm25_config", "BM25 질의 term 계약이 잘못됐습니다")
        if config.get("capability_aggregation") != "max_bm25":
            raise ExperimentError("invalid_bm25_config", "BM25 집계 계약이 잘못됐습니다")

    def _features(self, value: str) -> Counter[str]:
        text = unicodedata.normalize("NFKC", _normalize_text(value))
        if not text:
            raise AdapterFailure("text_missing")
        features: Counter[str] = Counter()
        for size in range(self.ngram_min, self.ngram_max + 1):
            for index in range(max(0, len(text) - size + 1)):
                features[text[index : index + size]] += 1
        if not features:
            features[text] = 1
        return features

    def _score(
        self,
        query_terms: Sequence[str],
        document: Counter[str],
        document_length: int,
        average_length: float,
        idf: dict[str, float],
    ) -> float:
        if average_length <= 0:
            raise AdapterFailure("adapter_execution_failed")
        denominator_length = self.k1 * (1.0 - self.b + self.b * (document_length / average_length))
        total = 0.0
        for term in query_terms:
            frequency = document.get(term)
            if not frequency:
                continue
            total += idf[term] * (frequency * (self.k1 + 1.0)) / (frequency + denominator_length)
        if not math.isfinite(total):
            raise AdapterFailure("adapter_execution_failed")
        return total

    def score_all(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult]:
        started = time.monotonic()
        capability_rows = capabilities.get("capabilities") or []
        if not capability_rows:
            raise AdapterFailure("capabilities_empty")
        try:
            # 문서 모음은 발주계획 제목이다. IDF도 이 모음에서만 계산한다.
            title_counts = [self._features(plan_text(plan)) for plan in plans]
            lengths = [sum(counts.values()) for counts in title_counts]
            average_length = sum(lengths) / len(lengths) if lengths else 0.0
            document_frequency: Counter[str] = Counter()
            for counts in title_counts:
                document_frequency.update(counts.keys())
            document_count = len(title_counts)
            idf = {
                feature: math.log(
                    1.0 + (document_count - frequency + 0.5) / (frequency + 0.5)
                )
                for feature, frequency in document_frequency.items()
            }
            # 질의 term은 중복을 세지 않는다. capability summary가 제목보다 훨씬
            # 길어 질의 TF를 그대로 쓰면 긴 요약이 일방적으로 유리해진다.
            capability_terms = [
                sorted(term for term in self._features(row["summary"]) if term in idf)
                for row in capability_rows
            ]
            scored: list[tuple[float, str]] = []
            for index, counts in enumerate(title_counts):
                candidates = [
                    (
                        self._score(
                            capability_terms[position],
                            counts,
                            lengths[index],
                            average_length,
                            idf,
                        ),
                        capability_rows[position]["id"],
                    )
                    for position in range(len(capability_rows))
                ]
                scored.append(max(candidates, key=lambda item: (item[0], item[1])))
        except AdapterFailure:
            raise
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
            raise AdapterFailure("adapter_execution_failed") from exc
        total_latency = max(0, round((time.monotonic() - started) * 1000))
        latency_parts = _split_measurement(total_latency, len(plans))
        return [
            AdapterResult(
                score=score,
                reason=f"nearest_capability:{capability_id}",
                latency_ms=int(latency_parts[index]),
                device="cpu",
            )
            for index, (score, capability_id) in enumerate(scored)
        ]


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


class BoundHTTPConnection(http.client.HTTPConnection):
    """HTTP connection bound to one approved interface before connect()."""

    def __init__(self, host: str, interface: str, **kwargs: Any):
        super().__init__(host, **kwargs)
        self.interface = interface
        self._create_connection = self._create_bound_connection

    def _create_bound_connection(
        self,
        address: tuple[str, int],
        timeout: float | object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        if not hasattr(socket, "SO_BINDTODEVICE"):
            raise OSError("SO_BINDTODEVICE is unavailable")
        last_error: OSError | None = None
        for family, socktype, protocol, _canonname, sockaddr in socket.getaddrinfo(
            address[0], address[1], 0, socket.SOCK_STREAM
        ):
            sock: socket.socket | None = None
            try:
                sock = socket.socket(family, socktype, protocol)
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_BINDTODEVICE,
                    self.interface.encode("ascii") + b"\0",
                )
                if source_address:
                    sock.bind(source_address)
                sock.connect(sockaddr)
                return sock
            except OSError as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
        if last_error is not None:
            raise last_error
        raise OSError("no address available")


class BoundHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, interface: str):
        super().__init__()
        self.interface = interface

    def http_open(self, request):  # type: ignore[no-untyped-def]
        return self.do_open(
            lambda host, **kwargs: BoundHTTPConnection(
                host, interface=self.interface, **kwargs
            ),
            request,
        )


class SafeJsonHttpClient:
    def __init__(self, timeout: int, bind_interface: str | None = None):
        if timeout < 1:
            raise ExperimentError("invalid_http_config", "model timeout은 1 이상이어야 합니다")
        self.timeout = timeout
        handlers: list[Any] = [urllib.request.ProxyHandler({}), NoRedirect()]
        if bind_interface:
            handlers.append(BoundHTTPHandler(bind_interface))
        self.opener = urllib.request.build_opener(*handlers)

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


class OllamaDenseAdapter:
    """Score title embeddings against approved capability embeddings via Ollama."""

    def __init__(self, config: dict[str, Any]):
        env_name = config.get("base_url_env")
        if not isinstance(env_name, str) or not env_name:
            raise ExperimentError("model_endpoint_missing", "dense base URL 환경변수 이름이 없습니다")
        base_url = os.environ.get(env_name, "").strip()
        if not base_url:
            raise ExperimentError("model_endpoint_missing", f"{env_name}가 필요합니다")
        validated_base = validate_local_base_url(
            base_url, config.get("allowed_hosts") or [], "ollama_native"
        )
        self.url = validated_base + "/api/embed"
        self.tags_url = validated_base + "/api/tags"
        self.model_name = config["model_name"]
        self.model_revision = config["model_revision"]
        self.client = SafeJsonHttpClient(int(config.get("timeout_seconds", 120)))
        self.batch_size = int(config["batch_size"])
        self._revision_verified = False

    def verify_model_revision(self) -> None:
        if self._revision_verified:
            return
        response, latency = self.client.get(self.tags_url, {})
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
        self._revision_verified = True

    def prepare(self) -> None:
        self.verify_model_revision()

    @staticmethod
    def _normalize_embedding(value: Any, expected_dimension: int | None = None) -> list[float]:
        if not isinstance(value, list) or not value:
            raise AdapterFailure("malformed_response")
        if expected_dimension is not None and len(value) != expected_dimension:
            raise AdapterFailure("embedding_dimension_mismatch")
        vector: list[float] = []
        for item in value:
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                raise AdapterFailure("malformed_response")
            number = float(item)
            if not math.isfinite(number):
                raise AdapterFailure("malformed_response")
            vector.append(number)
        norm = math.sqrt(sum(item * item for item in vector))
        if norm <= 0 or not math.isfinite(norm):
            raise AdapterFailure("embedding_zero_norm")
        return [item / norm for item in vector]

    def _embed(
        self,
        texts: Sequence[str],
        expected_dimension: int | None = None,
    ) -> tuple[list[list[float]], int]:
        response, latency = self.client.post(
            self.url,
            {
                "model": self.model_name,
                "input": list(texts),
                "truncate": False,
            },
            {},
        )
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise AdapterFailure("population_coverage_mismatch", latency)
        try:
            normalized = [
                self._normalize_embedding(vector, expected_dimension)
                for vector in embeddings
            ]
        except AdapterFailure as exc:
            raise AdapterFailure(exc.error_code, latency) from exc
        dimensions = {len(vector) for vector in normalized}
        if len(dimensions) != 1:
            raise AdapterFailure("embedding_dimension_mismatch", latency)
        return normalized, latency

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=True))

    def score_many(
        self,
        plans: Sequence[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> list[AdapterResult | AdapterFailure]:
        self.verify_model_revision()
        capability_rows = capabilities.get("capabilities") or []
        if not capability_rows:
            return [AdapterFailure("capabilities_empty") for _plan in plans]
        try:
            capability_vectors, capability_latency = self._embed(
                [row["summary"] for row in capability_rows]
            )
        except (KeyError, TypeError) as exc:
            return [AdapterFailure("capabilities_invalid") for _plan in plans]
        except AdapterFailure as exc:
            latency_parts = _split_measurement(exc.latency_ms, len(plans))
            return [
                AdapterFailure(exc.error_code, latency_parts[index])
                for index in range(len(plans))
            ]
        dimension = len(capability_vectors[0])
        capability_latency_parts = _split_measurement(capability_latency, len(plans))
        outcomes: list[AdapterResult | AdapterFailure] = []
        offset = 0
        for batch in fixed_batches(plans, self.batch_size):
            try:
                title_vectors, batch_latency = self._embed(
                    [plan_text(plan) for plan in batch], dimension
                )
                batch_latency_parts = _split_measurement(batch_latency, len(batch))
                for local_index, title_vector in enumerate(title_vectors):
                    candidates = [
                        (
                            self._cosine(capability_vectors[index], title_vector),
                            capability_rows[index]["id"],
                        )
                        for index in range(len(capability_rows))
                    ]
                    score, capability_id = max(
                        candidates, key=lambda item: (item[0], item[1])
                    )
                    outcomes.append(
                        AdapterResult(
                            score=score,
                            reason=f"nearest_capability:{capability_id}",
                            latency_ms=int(capability_latency_parts[offset + local_index])
                            + int(batch_latency_parts[local_index]),
                            device="ollama",
                        )
                    )
            except AdapterFailure as exc:
                batch_latency_parts = _split_measurement(exc.latency_ms, len(batch))
                outcomes.extend(
                    AdapterFailure(
                        exc.error_code,
                        (capability_latency_parts[offset + local_index] or 0)
                        + (batch_latency_parts[local_index] or 0),
                    )
                    for local_index in range(len(batch))
                )
            offset += len(batch)
        return outcomes


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
        bind_interface = None
        bind_interface_env = config.get("bind_interface_env")
        if bind_interface_env is not None:
            if not isinstance(bind_interface_env, str) or not bind_interface_env:
                raise ExperimentError("model_interface_invalid", "interface 환경변수 이름이 잘못됐습니다")
            bind_interface = os.environ.get(bind_interface_env, "").strip() or None
            if bind_interface not in set(config.get("allowed_bind_interfaces") or []):
                raise ExperimentError("model_interface_rejected", "승인되지 않은 model interface입니다")
        self.client = SafeJsonHttpClient(
            int(config.get("timeout_seconds", 120)), bind_interface=bind_interface
        )
        self.batch_size = int(config["batch_size"])
        self.max_output_tokens = int(config.get("max_output_tokens", 4096))
        self.think = config.get("think", "high")
        self.chat_template_kwargs = config.get("chat_template_kwargs")
        if self.chat_template_kwargs is not None and (
            not isinstance(self.chat_template_kwargs, dict)
            or set(self.chat_template_kwargs) != {"enable_thinking"}
            or not isinstance(self.chat_template_kwargs["enable_thinking"], bool)
        ):
            raise ExperimentError(
                "chat_template_kwargs_invalid",
                "vLLM chat_template_kwargs는 enable_thinking boolean만 허용합니다",
            )
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
            if self.chat_template_kwargs is not None:
                body["chat_template_kwargs"] = self.chat_template_kwargs
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
                if response.get("model") != self.model_name:
                    raise AdapterFailure("served_model_mismatch", latency)
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
