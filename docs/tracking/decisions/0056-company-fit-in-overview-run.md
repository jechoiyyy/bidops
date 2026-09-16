# 회사 핏을 개요 run 2단계 호출로 통합

- 상태: 폐기 (2026-09-16, [ADR-0057](0057-overview-scope-and-company-fit-in-deep-review.md)가 대체)
- 일자: 2026-09-16

## 맥락

회사 핏은 `prespec_company_fit_attempt` 별도 큐·runner·플래그(`BIDOPS_PRESPEC_COMPANY_FIT_ENABLED`,
`BIDOPS_REFERENCE_WORKFLOW_MODE`, 모델명)·analysis worker 슬롯을 갖고, 후보는 등급
`우선 검토`만이라 운영에서 0건이다(2026-09-16). 개요 run은 `SW사업대상=Y`로 완화돼 있다.

## 결정

회사 핏을 개요 run(`prespec_overview_run`)의 2단계 호출로 통합한다. 개요 초안이 결정적
검증·의미 검토를 통과한 직후, 검증된 사실(`_run_facts`의 business_overview·main_tasks·
budget_and_period·important_conditions)과 승인 프로필 구조화 항목으로 1회 호출하고,
결과·`profile_version_id`·검증 상태(`matched|mismatch|unknown|needs_human_review`)를 run에
저장한다. 자격은 개요와 동일. `auto_start_reason`의 회사 핏 사유는 run 필드에서 읽는다.
핏 실패는 개요 결과를 되돌리지 않는다.

## 대안 (소거)

같은 프롬프트 하나로 두 출력을 내는 방식은 검증 전 초안 위에 핏이 서게 되고 실패 주장
연동 규칙이 필요해 기각했다. 별도 큐를 유지하는 방식은 플래그·후보 0건 문제가 그대로
남아 기각했다.

## 결과

갱신 대상: ADR-0049 §3 사유 순서, ADR-0054 run 계약, `docs/contracts.md` 개요 MVP 절,
`docs/business-rules.md` 회사 핏 절·자동 심층 조건.

삭제 대상: `prespec_company_fit_attempt`·`company_fit_runner`·플래그 3개·worker 슬롯.

구현 범위와 일정은 이 ADR에 적지 않는다.
