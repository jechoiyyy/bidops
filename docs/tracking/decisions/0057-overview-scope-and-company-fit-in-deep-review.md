# 개요 검토는 앞부분 요약 3섹션으로 좁히고 회사 적합성은 심층 검토의 1단계로 옮긴다

- 상태: 부분 채택 — 결정 1~3 구현, 결정 4 보류(2026-09-16 담당자 지시)
- 일자: 2026-09-16

## 맥락

2026-09-16 운영 복구 뒤 실행한 표본 5건([기록](../../validation-runs/2026-09-16-overview-recovery.md))에서
개요 검토의 두 문제가 드러났다.

1. **범위 선택이 앞부분 개요를 놓친다.** 다섯 문서 모두 2쪽에 쪽번호가 달린 목차가 있고 첫
   항목이 `사업개요`류인데, 선택기는 목차 쪽을 버리고 본문의 `Ⅰ. 제목` 한 줄 패턴만 찾는다.
   4건이 fallback(1쪽부터 상한)으로 갔고, 805번은 본문 장 표식이 `Ⅰ`과 ` 사업 개요` 두 줄로
   갈라져 있어 70쪽 제안서 작성 양식의 목차가 첫 장으로 잡혀 74~98쪽(보안관리)을 골랐다.
   [ADR-0032](0032-prespec-overview-cutting-rule.md)가 1순위로 정한 "목차→본문 대응"은 MVP
   선택기에 구현되지 않았다.
2. **개요가 심층 검토의 일을 겸한다.** 결과 계약에 `important_conditions`(참여 자격·제약·평가·
   보안), `reviewer_analysis`, `unknowns`가 들어 있어 주장 수가 12개 상한까지 늘고, 의미 검토
   응답이 상한을 채우려다 계약을 어겨 3건이 실패했다.

담당자는 개요 검토의 목표를 "공고 앞부분(사업개요·제안개요·과업개요 등 같은 뜻의 헤더)에
있는 목적·내용·기간·금액을 읽고 요약하는 것"으로 다시 정했다. 참여 조건, 요구사항 대비 회사
과업·역량 부합, 회사 적합성, 위험·미확인 사항처럼 문서 전체를 봐야 하는 것은 심층 검토다.

## 결정

**1. 개요 결과 계약은 세 섹션이다.** `business_overview`(사업명·목적·배경·추진 방법),
`main_tasks`(과업 내용·산출물), `budget_and_period`(금액·기간·기산점). `important_conditions`·
`reviewer_analysis`·`unknowns`는 개요 계약에서 뺀다. 정책은 `prespec-overview-policy-v7`,
결과 스키마는 `bidops.prespec-overview-claims.v2`다. 예산·기간이 선택 범위에 없으면 해당 섹션은
빈 배열이며 서버가 경고 `section_empty:<section>`을 남긴다. "미확인" 판정은 개요가 내리지 않는다.

**2. 범위 선택은 목차 우선이다.** 앞 5쪽에서 "제목 … 쪽번호" 항목이 4개 이상인 쪽을 목차로
읽고, 첫 장(또는 개요 키워드 장)의 인쇄 쪽번호를 본문에서 제목 문자열 대조로 물리 쪽에 정렬해
시작·끝을 정한다. 목차가 없을 때만 본문 heading 탐색을 쓴다. 본문 heading은 로마숫자 단독 줄과
다음 비공백 줄의 제목을 하나로 합쳐 인식하고, `제안서 작성 안내`류 장 이후의 장은 후보에서
제외한다. 목차로 확정한 범위에는 `range_too_small` 최소 크기 규칙을 적용하지 않는다. 경계를
못 정하면 ADR-0032대로 사람 검토로 보내되, MVP 기간의 fallback(1쪽~상한)은 유지한다.

**3. 검증 규칙은 다음만 완화한다.** 주장의 인용 하나가 대조에 실패해도 검증된 인용이 1개
이상 남으면 주장을 유지하고 실패한 인용만 빼며 `evidence_dropped`를 경고로 남긴다. 인용 조각
경계에 `…`·`...`를 더한다. 의미 검토 입력에 기대 ID 목록과 개수를 명시하고 응답 스키마의
`maxItems`를 그 run의 실제 개수로 맞춘다. 의미 검토 응답에 기대 ID가 모두 정확히 한 번씩
있으면 그 외 항목은 무시하고 `semantic_extra_ids`를 경고로 남긴다. 누락·중복은 계속 실패다.
자동 보정은 없으며 결과 문장은 여전히 인용 대조와 의미 검토를 통과한 것만 남는다.

**4. 회사 적합성은 심층 검토의 1단계다. (보류)** 2026-09-16 담당자가 자동 심층 검토 변경을 진행하지 않기로 했다. 구현은 브랜치 `feat/company-fit-deep-stage`(c888a86)·`feat/company-fit-deep-stage-docs`(6878819)에 보존하고 main에 병합하지 않았다. 현재 자동 심층 시작 조건과 회사 핏 게이트는 [ADR-0049](0049-prespec-auto-preparation-and-auto-deep-review.md) 그대로다. 아래는 보류된 결정의 원문이다. 자동 심층 검토 시작 조건에서 회사 핏 사유
(`company_fit_*`)를 제거한다. 사전규격이 `SW사업대상=Y`이고 자동 확정 `ready` 묶음이 있고 최신
개요 run이 `completed`이며 같은 불변 입력의 심층 검토가 없으면 시스템이 심층 검토를 만든다.
심층 검토가 만들어지면 기존 회사 핏 runner(`prespec_company_fit_attempt`)를 그 심층 검토의
첫 단계로 큐에 넣고 결과를 보고서 화면의 회사 적합성 영역에 표시한다. `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED`·
`BIDOPS_REFERENCE_WORKFLOW_MODE` 게이트는 이 runner 실행 조건으로만 남는다. 심층 검토 정책의
3단계 구성과 attempt 테이블은 바꾸지 않는다(최소 범위).

## 대안 (소거)

- 회사 핏을 개요 run의 2단계 호출로 흡수([ADR-0056](0056-company-fit-in-overview-run.md)) — 개요를
  앞부분 요약으로 좁힌 결정 1과 충돌하므로 폐기한다.
- 4섹션 유지 + 선택기만 수정 — 실패 3건의 원인인 주장 수 상한 압박이 그대로 남는다.
- 심층 정책을 4단계로 재정의하고 attempt 테이블을 폐기 — 계약·ERD 변경이 커서 별도 결정으로 미룬다.

## 결과

- 갱신 대상: [ADR-0049](0049-prespec-auto-preparation-and-auto-deep-review.md) §3 사유 순서,
  [ADR-0054](0054-prespec-overview-mvp-rewrite.md) run 계약, `docs/contracts.md` 개요 MVP 절,
  `docs/business-rules.md`의 개요 검토 상태·자동 심층 시작·회사 핏 절, `docs/deep-review-erd.md` §8.5.
- 코드: `overview_range.py`(선택기), `prespec-overview-policy-v7.json`·`schemas/prespec_overview_claims.py`·
  `prespec_overview_claim_validation.py`·`prespec_overview_claim_policy.py`(계약·검증),
  `auto_preparation.py`·`company_fit_runner.py`(게이트·1단계 호출), 프런트 개요·심층 검토 섹션.
- 이 결정은 모델 품질을 측정하지 않았고 운영 활성화 근거를 만들지 않는다. 표본 5건 재실행으로
  전후를 비교한다.
