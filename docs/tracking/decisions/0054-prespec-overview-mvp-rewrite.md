# 사전규격 개요 실행 스택 철거·MVP 재작성

- 상태: 채택
- 일자: 2026-09-11

## 맥락

사전규격 개요 검토는 세 세대의 계약이 순서대로 쌓였다. v3 권고형 개요, legacy v4 단일
호출 개요, 그리고 2026-09-10 `docs/0910_prespec-workflow-hardening/`가 설계한 v5 주장
검증 스택(activation v2·call ledger·verification 테이블)이다. 세 세대 모두 실사용 모델
호출 이력이 없고, `quality_status=unmeasured_reference|mock_reference` 표식을 벗어난 적이
없다. v5는 격리 검증까지는 마쳤지만 실사용 초안 4건 전부가 사람 검토로 떨어졌고, 다음
세대가 다시 새 정책·테이블을 얹는 대신 이번에는 세대를 하나로 접기로 했다.

## 결정

v3·legacy v4·v5(activation·call ledger·verification)를 폐기하고 `prespec_overview_run`
단일 테이블과 `bidops.prespec-overview.v1` 계약으로 다시 쓴다. 새 계약 정본은
`docs/contracts.md`의 "사전규격 개요 검토 (MVP, 2026-09-11)" 절이다. 첨부 취득·묶음·자동
준비·문서 변환(document_mcp)·PDF/쪽 텍스트 스냅샷(`prespec_v4_pdf_snapshot`, migration
0021/0023/0024)과 주장 결정적 검증 함수는 그대로 유지한다. MVP 실행 기간에는 모델 호출
게이트를 완화하고(ADR-0050 §5 완화 항목), 건별 전송 승인·cohort activation을 없애고,
`BIDOPS_PRESPEC_OVERVIEW_ENABLED` 플래그 하나로 자동 enqueue한다.

## 사유

- 세대 공존: v3 응답과 v4/v5 응답이 같은 화면·계약 문서에 동시에 실려 어느 것이 정본인지
  코드를 봐야만 알 수 있었다.
- 실사용 이력 없음: 세 세대 모두 참조 실행 표식을 벗어난 운영 승인 근거가 없다. 다음
  세대를 얹기 전에 실행 가능한 형태로 접는 편이 새 계약을 검증하기 쉽다.
- 과잉 계약: activation ID·call ledger·verification 테이블·v2/v3/v4 응답 projection이
  분리되어 있었지만, 실제로 필요한 것은 run 하나의 상태·범위·결과·경고뿐이었다.

## 결과

- 유지: 첨부·묶음·자동 준비·document_mcp 변환·PDF/쪽 텍스트 스냅샷·주장 결정적 검증 함수.
- 삭제: `prespec_overview_verification`, `prespec_overview_call_event`,
  `prespec_v4_attempt`, `prespec_v4_target`, `prespec_page_overview`,
  `prespec_overview_attempt_event`, `prespec_overview_result`, `prespec_overview_attempt`,
  `prespec_overview_snapshot`, `prespec_overview_review`와 그 REST 계약
  (`bidops.prespec-overview-reviews.v1/v2`, `bidops.prespec-overview-pages.v1/v2`,
  `bidops.prespec-overview-page-review.v3/v4`, `bidops.prespec-overview-claim-checks.v1`,
  `bidops.prespec-overview-policy.v1/v4/v5`, `bidops.prespec-v4-activation.v1/v2`,
  `bidops.prespec-overview-range-view.v2`), v4 cohort ops CLI, Luna 명시 참조 실행 절차.
  `docs/0910_prespec-workflow-hardening/`는 저장소에서 삭제하고 git 이력(71b9954)에서
  찾는다.
- 신규: `prespec_overview_run`(migration 0026) 단일 테이블, `GET/POST
  /api/pre-specs/{notice_id}/overview*` 세 endpoint, `prespec-overview-policy-v6.json`.
- 회사 핏(`prespec_company_fit_attempt`)의 `page_overview_id`·`overview_result_id`는
  `overview_run_id`로 바꾼다.
- 상세 wire·DB 계약은 `docs/contracts.md`, ERD는 `docs/deep-review-erd.md` §8.5,
  실행 순서는 `docs/business-rules.md`의 "사전규격 개요 검토 상태 (MVP)" 절을 정본으로 한다.
