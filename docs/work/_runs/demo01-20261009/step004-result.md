# STEP-004 교차 회사·호환 인수 결과

## 보완

- 회사 3사의 독립 추적, 동일 상태의 새 결정, exact replay, stale/reset, 손상된 replay snapshot fail-closed를 검사했다.
- PostgreSQL 실제 `app` role이 최초 행 경합 후 기존 current를 UPDATE하고 reset 감사를 남기는 조합을 검사했다.
- 회사 핏 행이 있어도 legacy 자동 enqueue·latest·claim·lease 회수가 NULL 회사 계보만 쓰는 사례를 추가했다.
- DEMO 공통 계약의 운영 1489 검증 오기를 미실행·DEMO-03 STEP-007 후속 Luna 게이트로 정정했다.
  핏은 `overview` 용도 LiteLLM `local-agent-main`으로 명시하고 실제 호출 직전 사람 확인·동결 검사를 유지했다.
- 핵심 정본은 DEMO-01만 별도 데모 브랜치에 구현됐고 main·운영 미반영,
  DEMO-02~05 미구현임을 명시했다.

## 검증

- 리더 단일 실행: SQLite + 일회용 PostgreSQL 17.11 + 실제 `app` role, 27 passed / 0 skipped / 18.61초.
- 로그: `docs/work/_runs/demo01-20261009/step004-tests.log`.
- 문서 doctor 6 passed, `git diff --check` passed, `source-baseline.json` 불일치 0.
- T1~T6의 구체 assertion·증거 연결은 `plan.md` 결과 표에 남겼다.

## 한계·후속

- `test_the_flag_opens_preparation_for_sw_business_without_a_grade` 1건은 main `c242850`에서도 재현된 기존 한계로 보존했다.
- main·운영 반영, 배포, migration 적용, 모델 호출은 0건이다.
- 실제 Luna 대표 1건은 DEMO-03 STEP-007, 전체 18/9건·담당자 인수는 DEMO-05에 남아 있다.
- 기존 deep-review/report/evidence ID 직접 조회·수정 경로 전수 검사는 계획대로 main 병합 전 별도 게이트다.
