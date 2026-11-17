"""사용자에게 보이는 문구 사전(PF-01, PF-03). 내부 식별자(GateCode·enum 값)를 사람 말로 바꾼다.

PF-01: 참가자격 게이트(`GATE_LABELS`). PF-03: 결정·확실성·판정·적합도·확인 수준·심각도·원문
역할 라벨. 보고서·CLI·정비 목록은 라벨을 이 모듈에서만 가져온다.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

from bid_deep_engine.analysis.schemas import DecisionValue, EvalKind, Fit, GateCode, Severity, Verdict
from bid_deep_engine.ingest.models import Role

GATE_LABELS: dict[GateCode, str] = {
    "G2B_REGISTERED": "나라장터 입찰참가자격 등록",
    "INDUSTRY_CODE": "업종코드",
    "SW_BUSINESS_REPORT": "SW사업자 신고",
    "SME_CERT": "중소기업·소상공인 확인서",
    "DIRECT_PRODUCTION": "직접생산확인",
    "LARGE_CORP_EXCLUDED": "대기업 참여 제한",
    "MUTUAL_INVEST_GROUP_EXCLUDED": "상호출자제한기업집단 제한",
    "REGION_LIMIT": "지역 제한",
    "DEBARMENT": "부정당업자 제재",
    "TAX_DELINQUENCY": "국세·지방세 체납",
    "PAST_PERFORMANCE": "수행 실적",
    "REQUIRED_CERT": "필수 인증",
    "OTHER": "원문 확인이 필요한 참가자격",
    "STAFFING_CAPACITY": "투입 인력 규모",
    "ONSITE_LOCATION": "상주 근무",
    "CONSORTIUM_CONDITION": "공동수급 조건",
    "INSOLVENCY": "부도·회생",
}

# GateCode가 늘면 라벨도 함께 늘려야 한다(import 시 보장).
if set(GATE_LABELS) != set(get_args(GateCode)):
    raise RuntimeError("GATE_LABELS keys must match GateCode values")


# --- PF-03: 결론 우선 보고서 ---

# 보고서 판단의 확실성(spec PF-03 2절). "none"은 판단 없음이라 라벨이 없다.
Certainty = Literal["confirmed", "provisional", "unverified", "none"]

# 결정 값(M0-01 CLI `decide` 도움말 문구). `report.render.REC_LABELS`는 이 사전을 가리킨다.
DECISION_LABELS: dict[DecisionValue, str] = {
    "GO": "입찰 진행",
    "CONDITIONAL_GO": "조건부 진행",
    "NO_GO": "입찰 포기",
}
CERTAINTY_LABELS: dict[Certainty, str] = {
    "confirmed": "확정",
    "provisional": "잠정",
    "unverified": "잠정 · 회사 기준 미검증",
}
VERDICT_LABELS: dict[Verdict, str] = {
    "PASS": "충족",
    "FAIL": "미충족",
    "UNKNOWN": "확인 필요",
    "RISK": "위험",
}
FIT_LABELS: dict[Fit, str] = {
    "FULL": "충족",
    "PARTIAL": "부분 충족",
    "GAP": "미보유",
    "UNKNOWN": "확인 필요",
}
# 회사 값 확인 수준(REV-01 provenance 수준과 KB confidence). 표시는 `level_label`로만 한다.
LEVEL_LABELS: dict[str, str] = {
    "confirmed": "확인됨",
    "public": "공개 기록",
    "estimate": "추정",
    "demo": "데모값",
    "unknown": "확인 수준 미상",
}
SEVERITY_LABELS: dict[Severity, str] = {"H": "높음", "M": "중간", "L": "낮음"}
ROLE_LABELS: dict[Role, str] = {
    "primary": "주 원문",
    "reference": "참고",
    "pending_hwp": "hwp 변환 대기",
    "superseded": "대체됨",
    "skipped": "건너뜀",
}


def level_label(level: str) -> str:
    """확인 수준 번역(`공개 기록`). 모르는 값은 `확인 수준 미상`이고 영문 원값은 붙이지 않는다."""
    return LEVEL_LABELS.get(level, LEVEL_LABELS["unknown"])


_LEVEL_MARK = re.compile(r"\((" + "|".join(LEVEL_LABELS) + r")\)")


def translate_level_marks(text: str) -> str:
    """LLM 서술에 섞인 확인 수준 영문 표지 `(public)` 등을 한국어 라벨 `(공개 기록)`으로 바꾼다.
    담당자 화면에 영문 수준 표지를 내지 않기 위한 표시 변환이며 원문 인용에는 쓰지 않는다."""
    return _LEVEL_MARK.sub(lambda m: f"({LEVEL_LABELS[m.group(1)]})", text)


# 평가 항목 종류. PAST_PERFORMANCE·OTHER는 게이트 라벨과 같은 말이라 따로 두지 않는다.
EVAL_KIND_LABELS: dict[str, str] = {
    "CREDIT_RATING": "신용평가등급",
    "CERT_COUNT": "인증 보유 건수",
    "STAFF_TRAINING": "교육 이수 인원",
}
if set(EVAL_KIND_LABELS) != set(get_args(EvalKind)) - {"PAST_PERFORMANCE", "OTHER"}:
    raise RuntimeError("EVAL_KIND_LABELS keys must match EvalKind values")

# LLM 서술에 섞이는 내부 코드 → 담당자 말. 판정(Verdict)과 적합도(Fit)에 모두 있는 UNKNOWN은
# 두 라벨이 같아 하나로 둔다.
_CODE_LABELS: dict[str, str] = {
    **EVAL_KIND_LABELS,
    **DECISION_LABELS,
    **FIT_LABELS,
    **VERDICT_LABELS,
    **GATE_LABELS,
}
# 회사 프로필 최상위 키(`CompanyProfile` 필드). 이 키로 시작하는 점 경로만 회사 기록으로 본다
# (`notice.hwp` 같은 파일명은 건드리지 않는다).
_COMPANY_ROOTS = ("company", "registrations", "people", "capabilities", "portfolio", "policy")
_ID_EDGE = r"(?<![A-Za-z0-9_])"
_ID_EDGE_END = r"(?![A-Za-z0-9_])"
_CODE_TOKEN = re.compile(
    _ID_EDGE + "(" + "|".join(sorted(_CODE_LABELS, key=len, reverse=True)) + ")" + _ID_EDGE_END
)
_COMPANY_PATH = re.compile(
    r"(?<![A-Za-z0-9_.])(?:" + "|".join(_COMPANY_ROOTS) + r")(?:\[[^\]]*\])?"
    r"(?:\.(?:[A-Za-z0-9_%]+|[A-Za-z0-9_%가-힣]+(?=\.[A-Za-z0-9_%가-힣]))(?:\[[^\]]*\])?)+"
)
# 한글 토큰(`서울`)은 뒤에 다른 경로 토큰이 이어질 때만 경로로 본다.
# 끝에 붙은 한글은 조사(`…pm_capable는`)다.
COMPANY_RECORD_LABEL = "회사 기록"


def clean_llm_text(text: str) -> str:
    """LLM 서술을 담당자 화면용으로 정리한다(표시 변환). 확인 수준 표지(`translate_level_marks`),
    게이트 코드·평가 종류·판정·결정·적합도 영문 코드(`REGION_LIMIT` → `지역 제한`), 회사 기록 점
    경로(`policy.seoul_resident_ok` → `회사 기록`; 지우지 않고 치환한다)를 바꾼다. 영문 대문자
    토큰은 바로 뒤에 한글이 붙어도(`UNKNOWN이고`) 잡는다. 원문 인용에는 쓰지 않는다."""
    out = _COMPANY_PATH.sub(COMPANY_RECORD_LABEL, translate_level_marks(text))
    return _CODE_TOKEN.sub(lambda m: _CODE_LABELS[m.group(1)], out)


# enum이 늘면 라벨도 함께 늘려야 한다(import 시 보장).
for _labels, _enum in (
    (DECISION_LABELS, DecisionValue),
    (VERDICT_LABELS, Verdict),
    (FIT_LABELS, Fit),
    (SEVERITY_LABELS, Severity),
    (ROLE_LABELS, Role),
):
    if set(_labels) != set(get_args(_enum)):
        raise RuntimeError(f"label keys must match enum values: {sorted(_labels)}")
if set(CERTAINTY_LABELS) != set(get_args(Certainty)) - {"none"}:
    raise RuntimeError("CERTAINTY_LABELS keys must match Certainty values except none")
