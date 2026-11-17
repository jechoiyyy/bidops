"""unknown 필드의 확인처 사전(FIELD_HINTS)과 조회(hint_for).

확인처 문구는 프로필 템플릿의 `# 확인처:`·설명 주석 내용이다(YAML 주석은 파싱하지 않는다).
사람인 추정치 같은 비공식 값은 넣지 않는다. `company/schema.md`의 확인처 열은 같은 내용이다.
"""

import re

from bid_deep_engine.company.provenance import parse_canonical_path

DEFAULT_HINT = "company/schema.md 참고"

# 키 = 점 경로. 목록 인덱스는 `[*]`(예: `portfolio[*].amount_krw`).
FIELD_HINTS: dict[str, str] = {
    "company.region": "지역제한 판정용 (시·도)",
    "company.founded": "사내벤처 분사 창업 (창업기업 7년 특례 기준일)",
    "company.incorporated": "법인등기상 설립일 (창업기업 확인 시 필요)",
    "company.employees": "정규직 수",
    "registrations.g2b": "나라장터 > 입찰참가자격등록증",
    "registrations.g2b.industry_codes": (
        "나라장터 > 입찰참가자격등록증 (1468 = 소프트웨어사업자/컴퓨터관련서비스사업)"
    ),
    "registrations.g2b.other_codes": (
        "나라장터 > 입찰참가자격등록증 (엔지니어링, 산업디자인 등 등록 업종코드)"
    ),
    "registrations.sw_business_report": "한국소프트웨어산업협회 SW사업자 신고확인서",
    "registrations.sme_certificate": "중소기업현황정보시스템(sminfo) 중소기업확인서",
    "registrations.direct_production": "공공구매종합정보망(smpp) 직접생산확인증명서",
    "registrations.web_accessibility_certs": "웹접근성 품질인증 마크 획득 사이트 목록",
    "registrations.egov_framework_inspection_reports": (
        "전자정부표준프레임워크 적용점검결과서 (표준프레임워크센터 발급)"
    ),
    "registrations.credit_rating": "신용평가사(나이스/이크레더블 등) 기업신용평가등급확인서",
    "registrations.gs_cert": "GS인증 보유 제품 목록",
    "registrations.other_certs": "그 밖의 인증·지정 보유 목록 (ISMS 등 인증서 원본, 유효기간)",
    "registrations.tax_delinquency": "국세·지방세 체납 여부",
    "registrations.insolvency": "부도·파산·회생절차 해당 여부 (법인등기부등본·신용평가사 기업정보)",
    "registrations.wage_arrears_listed": "고용부 체불사업주 명단 공개 여부",
    "registrations.aa_noncompliance_listed": "적극적 고용개선조치 미이행 공표 여부",
    "registrations.patents": "등록 특허 수 (사이트 기준)",
    "registrations.copyrights": "프로그램 저작권 등록 수",
    "people.headcount_by_grade": "소프트웨어기술자 등급 기준 (경력 확인서)",
    "people.roles": "직군별 인원 (상주 요건 판정용)",
    "people.roles.pm_capable": "PM 가능(고급 이상 + 기획 경험) 인원",
    "people.roles.web_designer_5y_plus": "5년 이상 경력 디자이너 상주 요구 판정용",
    "people.trainings": "SW보안약점진단원·SW테스트전문가 교육 이수 인원",
    "people.trainings.sw_security_diagnostician": "SW보안약점진단원 교육 이수 인원",
    "people.trainings.sw_test_expert": "SW테스트전문가 교육 이수 인원",
    "people.certifications": "보유 자격증별 인원 (예: 정보처리기사, PMP, 정보보안기사)",
    "people.onsite_capacity": "상주 가능 지역·인원",
    "capabilities.tech_stack": "보유 기술 스택 (확인 후 수정)",
    "capabilities.cms_experience": "상용 CMS 유지보수 판정용 CMS 경험 목록",
    "capabilities.commercial_sw_experience": "상용 SW 운영 경험 목록",
    "capabilities.egov_framework_experience": "전자정부표준프레임워크 적용 사업 경험",
    "policy": "Go/No-Go 판단 기준 (담당자 정책)",
    "policy.min_contract_amount_krw": "Go/No-Go 판단 기준 (담당자 정책): 이 금액 미만은 NO_GO 권고",
    "policy.seoul_resident_ok": "Go/No-Go 판단 기준 (담당자 정책): 서울 상주 사업 수용 여부",
    "policy.default_bid_mode": (
        "Go/No-Go 판단 기준 (담당자 정책): 기본 입찰 형태(solo=단독, consortium=공동수급)"
        " — 공동수급 조건부 조항 판정용"
    ),
    "portfolio[*].title": "실적증명서·계약서의 사업명",
    "portfolio[*].client": "실적증명서·계약서의 발주기관",
    "portfolio[*].domain": "사업 분야(실적증명서·과업지시서 기준)",
    "portfolio[*].completed": "실적증명서의 준공·완료일",
    "portfolio[*].period": "실적증명서의 수행 기간",
    "portfolio[*].amount_krw": "실적증명서 금액 (남양주 실적비율 계산에 필수)",
    "portfolio[*].evidence": "실적증명서/계약서 보유 여부 또는 URL",
    "portfolio[*].web_accessibility_cert": "해당 사이트 웹접근성 인증 획득 여부",
    "portfolio[*].egov_framework": "전자정부표준프레임워크 적용 여부",
    "portfolio[*].type": (
        "사업 유형(구축|고도화|유지관리|운영|개발|컨설팅|물품) — 실적 키워드의 구축·유지관리 대조용"
    ),
}

_INDEX_RE = re.compile(r"\[[^\]]*\]")


def hint_for(path: str) -> str:
    """todo 경로의 확인처. 항상 비어 있지 않은 문자열(없으면 DEFAULT_HINT).

    경로의 `[...]`를 모두 `[*]`로 바꾼 뒤, 단계마다 ① 후보 그대로 ② 끝이 `[*]`면 그것을 뗀 형태를
    조회하고, 둘 다 없으면 마지막 점 세그먼트를 떼어 반복한다(X36).
    """
    candidate = _INDEX_RE.sub("[*]", path)
    if "%" in path:
        try:
            decoded = parse_canonical_path(path)
        except ValueError:
            pass
        else:
            canonical_pattern = ".".join(
                field + ("[*]" if identifier is not None else "") for field, identifier in decoded
            )
            hint = _lookup_hint(canonical_pattern)
            if hint is not None:
                return hint
    return _lookup_hint(candidate) or DEFAULT_HINT


def _lookup_hint(candidate: str) -> str | None:
    while candidate:
        for key in (candidate, candidate.removesuffix("[*]")):
            hint = FIELD_HINTS.get(key, "").strip()
            if hint:
                return hint
        candidate = candidate.rpartition(".")[0]
    return None
