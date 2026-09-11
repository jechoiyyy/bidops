#!/usr/bin/env python3
"""Collect G2B service bid notices and pre-specifications without dependencies."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BID_ENDPOINT = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
    "getBidPblancListInfoServc"
)
PRESPEC_ENDPOINT = (
    "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/"
    "getPublicPrcureThngInfoServcPPSSrch"
)

PRESPEC_QUALIFICATION_FIELDS = (
    "participation_limited",
    "industry_limited",
    "information_business",
    "general_service",
    "service_division",
    "joint_contract_method",
    "performance_restricted_competition",
    "pq_evaluation",
    "technical_evaluation",
    "technical_evaluation_rate",
    "successful_bid_method",
)

PERFORMANCE_REFERENCE_PATH = (
    PROJECT_ROOT / "docs/reference/company-performance-titles.tsv"
)

PERFORMANCE_THRESHOLD = 0.58

# Canonical concepts and Korean/English aliases. Matching normalizes Unicode,
# case, punctuation, and spacing, so variants such as AI Agent, ai-agent, and
# full-width ＡＩ　Ａｇｅｎｔ resolve to the same concept.
FOCUS_CONCEPTS = {
    "AI/데이터": {
        "AI": ("인공지능", "artificial intelligence", "ai"),
        "생성형 AI": ("생성형", "생성형 ai", "generative ai", "gen ai", "genai"),
        "AI Agent": (
            "ai agent", "ai 에이전트", "인공지능 에이전트", "지능형 에이전트",
            "에이전트", "agentic ai", "autonomous agent",
        ),
        "LLM": ("llm", "large language model", "거대언어모델", "거대 언어 모델"),
        "빅데이터": ("빅데이터", "big data"),
        "데이터 분석": ("데이터 분석", "data analytics", "data analysis"),
        "데이터 플랫폼": (
            "데이터 플랫폼", "데이터플랫폼", "data platform", "data hub",
            "데이터허브", "데이터 허브", "data lake", "data warehouse",
        ),
        "데이터 구축": ("데이터 구축", "db 구축", "database 구축"),
        "데이터 표준·품질": (
            "데이터 표준", "데이터 표준화", "데이터 품질", "data quality",
            "data standardization",
        ),
        "온톨로지": (
            "온톨로지", "ontology", "ontologies", "semantic web", "시맨틱 웹",
        ),
        "지식그래프": (
            "지식그래프", "지식 그래프", "knowledge graph", "knowledge graphs",
        ),
        "머신러닝": (
            "머신러닝", "machine learning", "ml model", "학습모델", "학습 모델",
        ),
    },
    "블록체인·DID": {
        "블록체인": ("블록체인", "blockchain"),
        "DID": (
            "did", "분산신원", "분산 신원", "decentralized identity",
            "self sovereign identity", "self-sovereign identity", "ssi",
        ),
        "신원증명": (
            "신원증명", "신원 증명", "identity credential", "identity verification",
        ),
        "전자지갑": (
            "전자지갑", "전자 지갑", "digital wallet", "e wallet", "e-wallet",
        ),
        "전자증명": (
            "전자증명", "전자 증명", "verifiable credential",
            "verifiable credentials",
        ),
        "디지털배지": (
            "디지털배지", "디지털 배지", "digital badge", "digital badges",
        ),
        "스마트컨트랙트": (
            "스마트컨트랙트", "스마트 컨트랙트", "smart contract",
        ),
        "NFT": ("nft", "non fungible token", "non-fungible token"),
        "Web3": ("web3", "web 3", "web 3.0"),
        "위변조 방지": ("위변조", "tamper proof", "tamper-proof"),
    },
    "공공 SI·통합관리": {
        "정보시스템": ("정보시스템", "정보 시스템", "information system"),
        "시스템 구축": (
            "시스템 구축", "system implementation", "system integration",
        ),
        "시스템 고도화": (
            "시스템 고도화", "기능 고도화", "system enhancement",
        ),
        "통합관리": (
            "통합관리", "통합 관리", "통합관리시스템", "integrated management",
        ),
        "통합 플랫폼": ("통합 플랫폼", "통합플랫폼", "integrated platform"),
        "유지관리": ("유지관리", "유지 관리", "유지보수", "maintenance"),
        "운영 및 유지": ("운영 및 유지", "운영 유지", "운영·유지"),
        "ISP/BPR": (
            "정보화전략", "정보화 전략", "isp", "bpr",
            "information strategy planning",
        ),
        "업무·행정시스템": (
            "업무시스템", "업무 시스템", "행정시스템", "행정 시스템",
        ),
        "포털·홈페이지 구축": (
            "포털 구축", "홈페이지 구축", "웹사이트 구축", "portal development",
        ),
        "시스템 통합": ("시스템 통합", "system integration"),
        "API·서비스 연계": (
            "api 연계", "api integration", "서비스 연계",
            "application programming interface",
        ),
        "클라우드": (
            "공공 클라우드", "클라우드", "cloud", "k paas", "k-paas",
            "paas", "iaas",
        ),
        "SaaS": ("saas", "software as a service"),
        "가상화": ("가상화", "virtualization"),
        "정보보안": (
            "정보보안", "정보 보호", "정보보호", "information security",
            "cybersecurity",
        ),
        "취약점 분석": (
            "정보통신기반시설", "취약점 분석", "vulnerability assessment",
        ),
        "전산시스템": ("전산시스템", "전산 시스템"),
        "네트워크 구축": ("네트워크 구축", "network implementation"),
        "PMS": (
            "pms", "project management system", "과제관리시스템", "사업관리시스템",
        ),
        "CMS": ("cms", "content management system"),
    },
}

# Concepts that count as a signal only when the surrounding text also carries a
# digital-delivery marker. "유지보수" on its own pulls in road, boiler, and
# elevator service contracts.
CONTEXT_DEPENDENT_LABELS = {("공공 SI·통합관리", "유지관리")}

PERFORMANCE_DELIVERY_MARKERS = (
    "시스템", "플랫폼", "구축", "개발", "고도화", "유지보수", "유지관리",
    "운영", "기능개선", "개편", "연계", "정보화전략", "isp", "bpr", "db",
    "홈페이지", "웹사이트", "포털", "앱", "어플리케이션", "소프트웨어", "s/w",
    "분석서비스", "메인넷", "전자지갑", "디지털배지",
)

# A portfolio-title match must still refer to a digital deliverable. This
# prevents a shared domain word such as "빈집", "수출", or "체전" from pulling
# in construction, consulting, insurance, or event notices.
PERFORMANCE_QUERY_MARKERS = (
    "정보시스템", "관리시스템", "시스템", "플랫폼", "데이터", "db", "소프트웨어",
    "s/w", "홈페이지", "웹사이트", "포털", "앱", "어플리케이션", "정보화",
    "정보망", "전자지갑", "디지털배지", "메인넷", "블록체인", "ai", "인공지능",
    "빅데이터", "연구장비", "예약관리", "평가관리", "과제관리", "사업관리",
    "실적관리", "통계관리", "행정서비스", "온라인", "정보제공", "영상정보",
    "공급망", "자동화", "온톨로지", "ontology", "지식그래프", "knowledge graph",
)

PERFORMANCE_NOISE_FRAGMENTS = (
    "용역", "사업", "지원", "구축", "개발", "고도화", "기능개선", "기능강화",
    "유지보수", "유지관리", "운영", "시스템", "플랫폼", "서비스", "홈페이지",
    "웹사이트", "정보화전략계획", "수립", "공고", "년도", "년",
)

GENERIC_COMMON_FRAGMENTS = {
    "관리", "관리시스템", "정보시스템", "통합시스템", "통합관리", "시스템",
    "플랫폼", "유지관리", "유지보수", "기능개선", "고도화", "지원사업",
    "홈페이지", "웹사이트", "구축용역", "개발용역", "지원관리",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", required=True, type=date.fromisoformat)
    parser.add_argument("--to-date", required=True, type=date.fromisoformat)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--allowed-root", type=Path, default=PROJECT_ROOT / "data" / "runs",
        help="입력·출력 허용 루트 (기본 data/runs, 격리 실행에서만 명시적으로 변경).",
    )
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-bids", action="store_true")
    parser.add_argument("--skip-prespecs", action="store_true")
    parser.add_argument(
        "--from-raw",
        type=Path, metavar="SOURCE_RAW",
        help="기존 raw 경로를 읽어 새 --output-dir에 복사·재분류한다. 이전 bare flag는 지원하지 않는다.",
    )
    return parser.parse_args()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_service_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("BIDOPS_G2B_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "BIDOPS_G2B_API_KEY를 현재 프로세스나 bidops-agent/.env에서 찾지 못했습니다."
        )
    # data.go.kr exposes both encoded and decoded key variants. Normalize once so
    # urlencode below does not double-encode an already encoded key.
    return urllib.parse.unquote(key)


def request_json(endpoint: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    url = endpoint + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        error_payload = exc.read().decode("utf-8", errors="replace")[:800]
        error_payload = " ".join(error_payload.split())
        raise RuntimeError(
            f"G2B API HTTP 오류: {exc.code} {exc.reason}; 응답: {error_payload or '없음'}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"G2B API 연결 오류: {exc.reason}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        prefix = payload[:240].replace("\n", " ")
        raise RuntimeError(f"JSON이 아닌 API 응답을 받았습니다: {prefix}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("API 응답 최상위가 JSON 객체가 아닙니다.")
    return data


def get_body(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response", payload)
    header = response.get("header", {}) if isinstance(response, dict) else {}
    result_code = str(header.get("resultCode", "00"))
    if result_code not in {"00", "0"}:
        raise RuntimeError(
            f"G2B API 오류 {result_code}: {header.get('resultMsg', '메시지 없음')}"
        )
    body = response.get("body", {}) if isinstance(response, dict) else {}
    return body if isinstance(body, dict) else {}


def get_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        return [items]
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def first(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return value
    return None


def text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_datetime(value: Any) -> str | None:
    text = text_value(value)
    if not text:
        return None
    compact = "".join(character for character in text if character.isdigit())
    formats = {
        8: "%Y%m%d",
        12: "%Y%m%d%H%M",
        14: "%Y%m%d%H%M%S",
    }
    if len(compact) in formats:
        try:
            parsed = datetime.strptime(compact, formats[len(compact)])
            return parsed.isoformat(timespec="seconds") + "+09:00"
        except ValueError:
            pass
    return text


def normalize_for_match(value: Any) -> str:
    """Normalize case, character width, punctuation, and separators."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return " ".join(text.split())


def compact_for_match(value: Any) -> str:
    return normalize_for_match(value).replace(" ", "")


def contains_alias(haystack: str, alias: str) -> bool:
    normalized_alias = normalize_for_match(alias)
    if not normalized_alias:
        return False
    # Prevent a short English abbreviation such as AI from matching inside an
    # unrelated English word. Korean and mixed phrases also match when spacing
    # or punctuation differs.
    if re.fullmatch(r"[0-9a-z ]+", normalized_alias):
        pattern = (
            r"(?<![0-9a-z])"
            + re.escape(normalized_alias).replace(r"\ ", r"\s+")
            + r"(?![0-9a-z])"
        )
        return re.search(pattern, haystack) is not None
    return normalized_alias.replace(" ", "") in haystack.replace(" ", "")


def has_digital_context(text: Any) -> bool:
    haystack = normalize_for_match(text)
    return any(contains_alias(haystack, marker) for marker in PERFORMANCE_QUERY_MARKERS)


def concept_labels(
    text: Any, digital_context: bool | None = None
) -> list[tuple[str, str, str]]:
    """Return (axis, label, alias) for every concept present in one text value."""
    haystack = normalize_for_match(text)
    if not haystack:
        return []
    if digital_context is None:
        digital_context = has_digital_context(text)
    found: list[tuple[str, str, str]] = []
    for axis, concepts in FOCUS_CONCEPTS.items():
        for label, aliases in concepts.items():
            if (axis, label) in CONTEXT_DEPENDENT_LABELS and not digital_context:
                continue
            for alias in aliases:
                if contains_alias(haystack, alias):
                    found.append((axis, label, alias))
                    break
    return found


def focus_signals(fields: Sequence[tuple[str, str, Any]]) -> list[dict[str, str]]:
    """Match concepts field by field so every signal keeps its provenance.

    `fields` holds (api_field_name, field_kind, value). Matching each field on
    its own also removes the cross-boundary matches a joined haystack produced,
    where the tail of one field and the head of the next formed a phrase that
    appears in neither.
    """
    digital_context = any(
        has_digital_context(value) for _, _, value in fields if value
    )
    signals: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for field_name, field_kind, value in fields:
        if not value:
            continue
        for axis, label, alias in concept_labels(value, digital_context):
            key = (axis, label, field_name)
            if key in seen:
                continue
            seen.add(key)
            signals.append({
                "axis": axis,
                "label": label,
                "matched_field": field_name,
                "matched_text": alias,
                "field_kind": field_kind,
            })
    return signals


def signal_axes(signals: Iterable[dict[str, str]]) -> set[str]:
    return {signal["axis"] for signal in signals}


@functools.lru_cache(maxsize=1)
def load_performance_references() -> tuple[dict[str, Any], ...]:
    references: list[dict[str, Any]] = []
    for raw_line in PERFORMANCE_REFERENCE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        page, title = line.split("\t", 1)
        normalized = normalize_for_match(title)
        if concept_labels(title) or any(
            contains_alias(normalized, marker)
            for marker in PERFORMANCE_DELIVERY_MARKERS
        ):
            core = performance_core(title)
            references.append({
                "page": int(page),
                "project_name": title,
                "core": core,
                "ngrams": character_ngrams(core),
            })
    return tuple(references)


def performance_core(value: Any) -> str:
    core = compact_for_match(value)
    core = re.sub(r"(?:19|20)\d{2}", "", core)
    core = re.sub(r"\d+", "", core)
    for fragment in PERFORMANCE_NOISE_FRAGMENTS:
        core = core.replace(compact_for_match(fragment), "")
    return core


def character_ngrams(value: str, size: int = 3) -> set[str]:
    return {
        value[index:index + size]
        for index in range(max(0, len(value) - size + 1))
    }


def performance_similarity_from_cores(
    left_core: str,
    left_grams: set[str],
    right_core: str,
    right_grams: set[str],
) -> tuple[float, str]:
    if len(left_core) < 4 or len(right_core) < 4:
        return 0.0, ""
    matcher = SequenceMatcher(None, left_core, right_core, autojunk=False)
    longest = matcher.find_longest_match()
    common = left_core[longest.a:longest.a + longest.size]
    gram_score = (
        2 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))
        if left_grams and right_grams
        else 0.0
    )
    containment_score = longest.size / min(len(left_core), len(right_core))
    return max(gram_score, matcher.ratio(), containment_score), common


def performance_similarity(left: Any, right: Any) -> tuple[float, str]:
    left_core = performance_core(left)
    right_core = performance_core(right)
    return performance_similarity_from_cores(
        left_core,
        character_ngrams(left_core),
        right_core,
        character_ngrams(right_core),
    )


def performance_signals(
    *values: Any, limit: int = 3
) -> tuple[list[dict[str, Any]], float]:
    """Return accepted portfolio matches and the best score that was seen.

    The best score is kept even when it stays below the threshold so that the
    sampler can audit near misses instead of drawing audit records at random.
    """
    haystack = " ".join(str(value) for value in values if value)
    if not has_digital_context(haystack):
        return [], 0.0
    haystack_core = performance_core(haystack)
    haystack_grams = character_ngrams(haystack_core)
    candidates: list[dict[str, Any]] = []
    best_score = 0.0
    for reference in load_performance_references():
        score, common = performance_similarity_from_cores(
            haystack_core,
            haystack_grams,
            reference["core"],
            reference["ngrams"],
        )
        generic = any(
            common and common in fragment
            for fragment in GENERIC_COMMON_FRAGMENTS
        )
        if len(common) < 4 or generic:
            continue
        best_score = max(best_score, score)
        if score >= PERFORMANCE_THRESHOLD:
            candidates.append({
                "project_name": reference["project_name"],
                "source_page": reference["page"],
                "similarity": round(score, 3),
                "common_fragment": common or None,
                "legal_qualification_status": "unknown",
            })
    candidates.sort(key=lambda item: (-item["similarity"], item["project_name"]))
    return candidates[:limit], round(best_score, 3)


def candidate_sources(
    signals: list[dict[str, str]], performances: list[dict[str, Any]]
) -> list[str]:
    sources = []
    if any(signal["field_kind"] == "title" for signal in signals):
        sources.append("focus_title")
    if any(signal["field_kind"] == "classification" for signal in signals):
        sources.append("focus_classification")
    if performances:
        sources.append("performance_similarity")
    return sources


def normalize_bid(record: dict[str, Any], raw_source: str) -> dict[str, Any]:
    number = text_value(first(record, "bidNtceNo", "bidPblancNo")) or "unknown"
    order = text_value(first(record, "bidNtceOrd", "bidPblancOrd")) or "00"
    title = text_value(first(record, "bidNtceNm", "bidPblancNm", "ntceNm"))
    agency = text_value(first(record, "dminsttNm", "ntceInsttNm", "orderInsttNm"))
    method = text_value(first(record, "cntrctCnclsMthdNm", "bidMethdNm"))
    signals = focus_signals((
        ("bidNtceNm", "title", title),
        ("pubPrcrmntLrgClsfcNm", "classification", record.get("pubPrcrmntLrgClsfcNm")),
        ("pubPrcrmntMidClsfcNm", "classification", record.get("pubPrcrmntMidClsfcNm")),
        ("pubPrcrmntClsfcNm", "classification", record.get("pubPrcrmntClsfcNm")),
        ("srvceDivNm", "other", record.get("srvceDivNm")),
        ("purchsObjPrdctList", "other", record.get("purchsObjPrdctList")),
    ))
    # Project-name similarity intentionally compares titles, not broad API
    # classification labels that can create spurious portfolio matches.
    matched_performances, best_performance_score = performance_signals(title)
    attachments = []
    for index in range(1, 11):
        attachment_url = text_value(record.get(f"ntceSpecDocUrl{index}"))
        if attachment_url:
            attachments.append({
                "name": text_value(record.get(f"ntceSpecFileNm{index}")) or f"첨부 {index}",
                "url": attachment_url,
            })
    standard_notice_url = text_value(record.get("stdNtceDocUrl"))
    if standard_notice_url:
        attachments.append({"name": "표준공고서", "url": standard_notice_url})
    unknown = [
        name
        for name, value in {
            "title": title,
            "agency": agency,
            "published_at": first(record, "bidNtceDt", "bidNtceDate"),
            "deadline_at": first(record, "bidClseDt", "bidClseDate"),
            "budget": first(record, "asignBdgtAmt", "presmptPrce", "bsisAmount"),
        }.items()
        if value in (None, "")
    ]
    sources = candidate_sources(signals, matched_performances)
    return {
        "notice_id": f"bid:{number}:{order}",
        "source_type": "bid_notice",
        "title": title,
        "agency": agency,
        "published_at": normalize_datetime(first(record, "bidNtceDt", "bidNtceDate")),
        "deadline_at": normalize_datetime(first(record, "bidClseDt", "bidClseDate")),
        "budget": first(record, "asignBdgtAmt", "presmptPrce", "bsisAmount"),
        "estimated_price": first(record, "presmptPrce"),
        "method": method,
        "url": text_value(first(record, "bidNtceDtlUrl", "bidNtceUrl")),
        "procurement_class": {
            "large": text_value(record.get("pubPrcrmntLrgClsfcNm")),
            "middle": text_value(record.get("pubPrcrmntMidClsfcNm")),
            "detail": text_value(record.get("pubPrcrmntClsfcNm")),
            "code": text_value(record.get("pubPrcrmntClsfcNo")),
        },
        "region_limit": {
            # The list operation carries the regional judgement basis, not a
            # plain region name. An empty basis is not proof of "no limit".
            "basis": text_value(record.get("rgnLmtBidLocplcJdgmBssNm")),
            "joint_contract_regions": [
                value
                for value in (
                    text_value(record.get(f"jntcontrctDutyRgnNm{index}"))
                    for index in (1, 2, 3)
                )
                if value
            ],
            "joint_contract_rate": text_value(record.get("rgnDutyJntcontrctRt")),
            "regional_joint_contract_limit": text_value(
                record.get("cmmnSpldmdCorpRgnLmtYn")
            ),
        },
        "lifecycle": {
            "pre_spec_no": text_value(record.get("bfSpecRgstNo")),
            # The bid response carries the official upstream plan identity.
            # It is optional in collected.v2 so historical artifacts remain
            # valid while newer rows can resolve the cumulative plan link.
            "order_plan_no": text_value(record.get("orderPlanUntyNo")),
            "re_notice": text_value(record.get("reNtceYn")),
            "changed_at": normalize_datetime(record.get("chgDt")),
            "change_reason": text_value(record.get("chgNtceRsn")),
            "unified_notice_no": text_value(record.get("untyNtceNo")),
            "previous_failed_notice_no": text_value(record.get("befBidBbancNo")),
        },
        "attachments": attachments,
        "qualification_flags": {
            "participation_limited": text_value(record.get("bidPrtcptLmtYn")),
            "industry_limited": text_value(record.get("indstrytyLmtYn")),
            "information_business": text_value(record.get("infoBizYn")),
            "general_service": text_value(record.get("ppswGnrlSrvceYn")),
            "service_division": text_value(record.get("srvceDivNm")),
            "joint_contract_method": text_value(record.get("cmmnSpldmdMethdNm")),
            "performance_restricted_competition": text_value(record.get("arsltCmptYn")),
            "pq_evaluation": text_value(record.get("pqEvalYn")),
            "technical_evaluation": text_value(record.get("tpEvalYn")),
            "technical_evaluation_rate": text_value(record.get("techAbltEvlRt")),
            "successful_bid_method": text_value(record.get("sucsfbidMthdNm")),
        },
        "focus_matches": signals,
        "performance_matches": matched_performances,
        "performance_top_score": best_performance_score,
        "candidate_sources": sources,
        "collection_bucket": "candidate_pool" if sources else "audit_pool",
        "unknown_fields": unknown,
        "raw_source": raw_source,
    }


def normalize_prespec(record: dict[str, Any], raw_source: str) -> dict[str, Any]:
    number = text_value(
        first(record, "bfSpecRgstNo", "publicPrcureThngNo", "prcrmntReqNo")
    ) or "unknown"
    # The business name carries the scope. The product classification label is
    # only a fallback, and the assigned budget is never descriptive text.
    title = text_value(first(record, "bfSpecNm", "prdctNm", "bizNm", "prdctClsfcNoNm"))
    agency = text_value(first(record, "orderInsttNm", "rlDminsttNm", "dminsttNm"))
    description = text_value(first(record, "prdctDtlDesc", "refNo"))
    classification = text_value(record.get("prdctClsfcNoNm"))
    signals = focus_signals((
        ("bfSpecNm", "title", title),
        ("prdctDtlDesc", "other", description),
        ("prdctClsfcNoNm", "classification", classification),
    ))
    matched_performances, best_performance_score = performance_signals(title)
    attachments = [
        {"name": f"첨부 {index}", "url": url}
        for index in range(1, 6)
        if (url := text_value(record.get(f"specDocFileUrl{index}")))
    ]
    sw_business_status = text_value(record.get("swBizObjYn"))
    business_division = text_value(record.get("bsnsDivNm"))
    bid_ntice_no_list = text_value(record.get("bidNtceNoList"))
    unknown = [
        name
        for name, value in {
            "title": title,
            "agency": agency,
            "published_at": first(record, "rgstDt", "rcptDt", "opninRgstDt"),
            "deadline_at": first(record, "opninRgstClseDt", "opninRgstClseDate"),
            "budget": first(record, "asignBdgtAmt", "sumOrderAmt"),
        }.items()
        if value in (None, "")
    ]
    if not attachments:
        # The source has no URL to turn into an attachment.  Keep the empty
        # array as the canonical type, but make the missing evidence explicit.
        unknown.append("attachments")
    if sw_business_status is None:
        unknown.append("qualification_flags.sw_business_status")
    if business_division is None:
        unknown.append("qualification_flags.business_division")
    if "bidNtceNoList" not in record:
        unknown.append("lifecycle.bid_ntice_no_list")
    sources = candidate_sources(signals, matched_performances)
    return {
        "notice_id": f"pre:{number}",
        "source_type": "pre_spec",
        "title": title,
        "agency": agency,
        "published_at": normalize_datetime(first(record, "rgstDt", "rcptDt", "opninRgstDt")),
        "deadline_at": normalize_datetime(
            first(record, "opninRgstClseDt", "opninRgstClseDate")
        ),
        "budget": first(record, "asignBdgtAmt", "sumOrderAmt"),
        "estimated_price": None,
        "method": None,
        # PPSSrch exposes document URLs only as specDocFileUrl1..5.  There is
        # no notice-detail URL in this response, so do not read legacy or
        # speculative fields into this slot.
        "url": None,
        "procurement_class": {
            "large": None,
            "middle": None,
            "detail": classification,
            "code": text_value(record.get("prdctClsfcNo")),
        },
        "region_limit": {
            "basis": None,
            "joint_contract_regions": [],
            "joint_contract_rate": None,
            "regional_joint_contract_limit": None,
        },
        "lifecycle": {
            "pre_spec_no": number,
            "re_notice": None,
            "changed_at": normalize_datetime(record.get("chgDt")),
            "change_reason": text_value(record.get("chgNtceRsn")),
            "unified_notice_no": None,
            "previous_failed_notice_no": None,
            "bid_ntice_no_list": bid_ntice_no_list,
        },
        "attachments": attachments,
        "qualification_flags": {
            **{field: None for field in PRESPEC_QUALIFICATION_FIELDS},
            "sw_business_status": sw_business_status,
            "business_division": business_division,
        },
        "focus_matches": signals,
        "performance_matches": matched_performances,
        "performance_top_score": best_performance_score,
        "candidate_sources": sources,
        "collection_bucket": "candidate_pool" if sources else "audit_pool",
        "unknown_fields": unknown,
        "raw_source": raw_source,
    }


def normalizer_for(source: str):
    return normalize_bid if source == "bid" else normalize_prespec


def relative_raw_path(raw_path: Path) -> str:
    try:
        return str(raw_path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(raw_path)


def checked_path(path: Path, allowed_root: Path) -> Path:
    """Check the lexical boundary before resolving or following any component."""
    if ".." in path.parts or ".." in allowed_root.parts or "\\" in str(path) or "\\" in str(allowed_root):
        raise RuntimeError("collection_path_invalid")
    path, allowed_root = path.absolute(), allowed_root.absolute()
    if not path.is_relative_to(allowed_root) or path == allowed_root:
        raise RuntimeError("collection_path_outside_root")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RuntimeError("collection_symlink_forbidden")
    return path


@contextmanager
def directory_fd(path: Path, *, create: bool = False):
    """Anchor each filesystem operation without following parent symlinks."""
    path = path.absolute()
    if ".." in path.parts or "\\" in str(path):
        raise RuntimeError("collection_path_invalid")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    except OSError as exc:
        raise RuntimeError("collection_directory_invalid") from exc
    finally:
        os.close(descriptor)


def claim_directory(path: Path) -> None:
    with directory_fd(path.parent, create=True) as parent:
        try:
            os.mkdir(path.name, dir_fd=parent)
        except FileExistsError as exc:
            raise RuntimeError("기존 회차 디렉터리를 덮어쓸 수 없습니다: collection_exists") from exc


def write_bytes_new(path: Path, data: bytes) -> None:
    with directory_fd(path.parent) as parent:
        def opener(name, flags):
            return os.open(name, flags | os.O_NOFOLLOW, dir_fd=parent)
        try:
            with open(path.name, "xb", opener=opener) as stream:
                stream.write(data)
        except FileExistsError as exc:
            raise RuntimeError("collection_file_exists") from exc


def write_json_new(path: Path, payload: dict[str, Any]) -> None:
    # Serialization must succeed before opening an immutable artifact.
    data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    write_bytes_new(path, data)


def read_regular_bytes(path: Path) -> bytes:
    with directory_fd(path.parent) as parent:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise RuntimeError("collection_raw_not_regular")
            return stream.read()


def raw_pages(raw_dir: Path) -> list[Path]:
    with directory_fd(raw_dir) as directory:
        pages = [raw_dir / name for name in sorted(os.listdir(directory))]
        for page in pages:
            if not re.fullmatch(r"(?:bid|prespec)-page-[0-9]{3}\.json", page.name):
                raise RuntimeError("collection_raw_name_invalid")
            if not stat.S_ISREG(os.stat(page.name, dir_fd=directory, follow_symlinks=False).st_mode):
                raise RuntimeError("collection_raw_not_regular")
    return pages


def raw_payload(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data)
        response = payload.get("response", payload)
        body = response.get("body")
        if not isinstance(body, dict):
            raise ValueError
        total = body.get("totalCount")
        if isinstance(total, bool) or int(total) < 0 or str(int(total)) != str(total):
            raise ValueError
        items = body.get("items", [])
        if items in (None, ""):
            items = []
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError
        get_body(payload)
        return payload
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise RuntimeError("collection_raw_invalid") from exc


def copy_raw_pages(source: Path, target: Path) -> None:
    for page in raw_pages(source):
        data = read_regular_bytes(page)
        raw_payload(data)
        destination = target / page.name
        write_bytes_new(destination, data)
        if hashlib.sha256(read_regular_bytes(destination)).digest() != hashlib.sha256(data).digest():
            raise RuntimeError("collection_raw_hash_mismatch")


def collect_source(
    *, source: str, endpoint: str, service_key: str, from_date: date,
    to_date: date, rows: int, timeout: int, raw_dir: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    page = 1
    normalizer = normalizer_for(source)
    while True:
        raw_path = raw_dir / f"{source}-page-{page:03d}.json"
        if os.path.lexists(raw_path):
            raise RuntimeError("collection_file_exists")
        params = {
            "serviceKey": service_key,
            "pageNo": page,
            "numOfRows": rows,
            "type": "json",
            "inqryDiv": "1",
            "inqryBgnDt": from_date.strftime("%Y%m%d") + "0000",
            "inqryEndDt": to_date.strftime("%Y%m%d") + "2359",
        }
        payload = request_json(endpoint, params, timeout)
        write_json_new(raw_path, payload)
        body = get_body(payload)
        items = get_items(body)
        raw_source = relative_raw_path(raw_path)
        records.extend(normalizer(item, raw_source) for item in items)

        total = int(body.get("totalCount", len(records)) or 0)
        if not items or len(records) >= total:
            if len(records) < total:
                warnings.append(f"{source}: 원문 페이지가 전체 건수보다 적어 부분 수집입니다.")
            break
        page += 1
        if page > 100:
            warnings.append(f"{source}: 안전 상한 100페이지에서 중단했습니다.")
            break
    return records, warnings


def reclassify_source(*, source: str, raw_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Re-normalize preserved API pages without calling the API again."""
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    pages = [page for page in raw_pages(raw_dir) if page.name.startswith(f"{source}-")]
    if not pages:
        warnings.append(f"{source}: 재분류할 원문 페이지가 없습니다.")
        return records, warnings
    normalizer = normalizer_for(source)
    totals: set[int] = set()
    for page_no, raw_path in enumerate(pages, 1):
        if raw_path.name != f"{source}-page-{page_no:03d}.json":
            warnings.append(f"{source}: 원문 페이지 번호가 연속되지 않아 부분 수집입니다.")
        payload = raw_payload(read_regular_bytes(raw_path))
        body = get_body(payload)
        totals.add(int(body["totalCount"]))
        items = get_items(body)
        raw_source = relative_raw_path(raw_path)
        records.extend(normalizer(item, raw_source) for item in items)
    if totals != {len(records)}:
        warnings.append(f"{source}: 원문 전체 건수와 재분류 건수가 달라 부분 수집입니다.")
    return records, warnings


def main() -> int:
    args = parse_args()
    if args.from_date > args.to_date:
        raise SystemExit("--from-date는 --to-date보다 늦을 수 없습니다.")
    if args.skip_bids and args.skip_prespecs:
        raise SystemExit("본공고와 사전규격을 동시에 건너뛸 수 없습니다.")

    if args.rows < 1 or args.timeout < 1:
        raise SystemExit("--rows와 --timeout은 양수여야 합니다.")
    output_dir = checked_path(args.output_dir, args.allowed_root)
    if os.path.lexists(output_dir):
        raise RuntimeError("기존 회차 디렉터리를 덮어쓸 수 없습니다: collection_exists")
    source_raw = None
    if args.from_raw is not None:
        source_raw = checked_path(args.from_raw, args.allowed_root)
        if not source_raw.is_dir() or output_dir.is_relative_to(source_raw):
            raise RuntimeError("collection_raw_directory_invalid")
        raw_pages(source_raw)
    claim_directory(output_dir)
    raw_dir = output_dir / "raw"
    claim_directory(raw_dir)

    notices: list[dict[str, Any]] = []
    warnings: list[str] = []
    plan = (
        ("bid", BID_ENDPOINT, args.skip_bids),
        ("prespec", PRESPEC_ENDPOINT, args.skip_prespecs),
    )
    source_window = {
        "from": args.from_date.isoformat(), "to": args.to_date.isoformat(),
        "timezone": "Asia/Seoul",
    }

    def record_provenance(*, complete: bool) -> None:
        write_json_new(output_dir / "collection-provenance.json", {
            "schema_version": "bidops.collection-provenance.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_raw": str(source_raw.relative_to(args.allowed_root.absolute())) if source_raw else None,
            "source_window": source_window,
            "options": {"rows": args.rows, "timeout": args.timeout,
                        "skip_bids": args.skip_bids, "skip_prespecs": args.skip_prespecs},
            "sources": [{"source": source, "endpoint": endpoint}
                        for source, endpoint, skip in plan if not skip],
            "complete": complete,
            "warnings": warnings,
            "raw_pages": [{"path": f"raw/{page.name}",
                           "source_path": f"{source_raw.relative_to(args.allowed_root.absolute())}/{page.name}" if source_raw else None,
                           "sha256": hashlib.sha256(read_regular_bytes(page)).hexdigest()}
                          for page in raw_pages(raw_dir)],
        })

    try:
        if source_raw is not None:
            copy_raw_pages(source_raw, raw_dir)
        service_key = "" if source_raw is not None else get_service_key()
        for source, endpoint, skip in plan:
            if skip:
                continue
            if source_raw is not None:
                batch, batch_warnings = reclassify_source(source=source, raw_dir=raw_dir)
            else:
                batch, batch_warnings = collect_source(
                    source=source, endpoint=endpoint, service_key=service_key,
                    from_date=args.from_date, to_date=args.to_date, rows=args.rows,
                    timeout=args.timeout, raw_dir=raw_dir,
                )
            notices.extend(batch)
            warnings.extend(batch_warnings)
    except (RuntimeError, OSError, ValueError):
        record_provenance(complete=False)
        raise

    deduplicated = {notice["notice_id"]: notice for notice in notices}
    ordered = sorted(
        deduplicated.values(),
        key=lambda notice: (notice.get("published_at") or "", notice["notice_id"]),
    )
    candidate_count = sum(item["collection_bucket"] == "candidate_pool" for item in ordered)
    result = {
        "schema_version": "bidops.collected.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_window": source_window,
        "counts": {
            "total": len(ordered),
            "candidate_pool": candidate_count,
            "audit_pool": len(ordered) - candidate_count,
        },
        "warnings": warnings,
        "notices": ordered,
    }
    output_path = output_dir / "collected-notices.json"
    try:
        write_json_new(output_path, result)
    except (RuntimeError, OSError, ValueError):
        record_provenance(complete=False)
        raise
    record_provenance(complete=not warnings)
    print(json.dumps({"output": output_path.name, **result["counts"], "complete": not warnings}, ensure_ascii=False))
    return 1 if warnings else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError):
        # HTTP errors and OS exceptions can include credentials or internal paths.
        print("collection_failed: 새 회차 경로·원문·부분 수집 상태를 확인하세요.", file=sys.stderr)
        raise SystemExit(1)
