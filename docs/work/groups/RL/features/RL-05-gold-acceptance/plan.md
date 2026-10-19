# 사용자 gold 10건 대조 인수 — plan

- 기능 ID: `RL-05-gold-acceptance`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md), HP-06 plan
- 작성일: 2026-10-16

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| scripts/rl-gold.py, tests/test_rl_gold.py(저장소 루트) | 신규 | export-cards·blank-gold·gold-check·score(HP `hp_prepare.py` 함수 복사, binding 교체, worktree 검사 완화, criteria는 HP 경로 참조) |
| web/backend/app/deep_review/cli/export_evaluation.py, cli/__init__.py | 신규/수정 | `--cards`(구조·page map 추출)·`--actual`(selection 유도·시각·holdout 검사·alignment→prediction·receipt) |
| web/backend/app/deep_review/cli/drain_verdict_queue.py | 수정 | `--hold --reason gold_holdout` |
| web/backend/tests/app/test_export_evaluation.py | 신규 | T2 |
| docs/model-quality-gate.md, operations.md, work/hp-contract.md(§9 주석: company_sha256=graph sha 의도적 차이), work/constitution/roadmap.md(RL-05 행), ADR.md, validation-runs/<날짜>-rl/RL-05/README.md | 수정/신규 | STEP-005 |

## 작업 순서

1. STEP-001 gold 도구 이관 [standard]
   - 목표: `rl-gold.py export-cards|blank-gold|gold-check|score`가 HP 계약과 같은 검사를 새 schema 이름·binding으로 수행(git-ignored 출력 허용).
   - 작업 대상: scripts/rl-gold.py, 테스트.
   - 검증: T1, T3, T4.
2. STEP-002 export CLI·holdout [complex]
   - 목표: `--cards` 추출, `--actual` selection 유도·정책·상태·품질 필터, 작성 시각(`deep_review.created_at`)·holdout 검사, alignment→prediction·receipt.
   - 작업 대상: export_evaluation.py, drain_verdict_queue.py 옵션(`--hold`).
   - 검증: T2.
3. STEP-003 표본 선정·holdout 등록 [standard]
   - 목표: 사용자와 실제 10건 선정(AUTO_START=false 상태에서), `selection.v1.json`, holdout 행 10개 생성(bidops-local).
   - 작업 대상: 평가 디렉터리, bidops-local.
   - 검증: `gold-check` 통과(빈 양식 구조), `verdict_request` 10행.
4. STEP-004 gold 작성·실제 실행·채점·인수 [complex]
   - 목표: 사용자 gold 10건(모델 전) → RL-03 수동 분석 10건(사람 직전 확인) → export·alignment·score → 사람 decision.
   - 작업 대상: 평가 디렉터리, acceptance.json.
   - 검증: T5.
5. STEP-005 문서 [standard]
   - 목표: 문서 4종·README.
   - 작업 대상: docs.
   - 검증: `doctor _`.

6. STEP-006 큰 영역 unit 분할(selector v4·정책 v10, 결정 C15) [complex]
   - 목표: 실제 사전규격 10건 중 3건이 영역(segment) unit 하나가 `batch_max_chars`(12,000자)를 넘어 `input_budget_exceeded`로 거부됨(12,061·12,963·29,949자). 영역 unit이 한도를 넘으면 원문 순서의 블록 경계에서 한도 이하 하위 unit으로 나눈다(자르지 않음, 블록 하나가 한도를 넘으면 기존처럼 거부). 새 selector `card-sections-v4`·불변 정책 `analysis-policy-luna-rl-v10`(v9와 selector만 다름)·RL identity 목록 v10 추가. 기존 v1~v9 행·attempt는 그대로.
   - 작업 대상: card_units.py(selector v4), policies/analysis-policy-luna-rl-v10.json, luna_identity.py, config 기본 경로, 테스트, RL-03 spec·contracts·business-rules 정정, RL-05 spec identity 목록.
   - 검증: 분할 단위 테스트(경계·순서·결정적 id·단일 블록 초과 거부·v3 동작 불변), 기존 card 테스트, PG 1건, 거부된 3건 bundle에서 읽기 전용 진단으로 v4 선택 통과 확인, 실제 분석 3건(T5, C14 승인 상한 안).

7. STEP-007 역할 근거 짧은 번호·역할/추출 항목 격리(정책 v10, 결정 C16) [complex]
   - 목표: v9 실제 7건 중 4건 실패 원인(역할 근거 키 (sha·block·quote) 옮겨 쓰기 오류 3건 — 인용 축약·sha 오기·다른 unit 근거, 추출 묶음 unit 누락 1건 `extract_unit_coverage`)을 v10에서 제거. (a) 역할 출력 계약 v2: 역할 입력의 unit별 근거에 짧은 번호(E1…)를 붙이고 모델은 번호만 인용, 코드가 원 근거로 되돌림. (b) 역할 항목 격리: 근거 번호가 그 unit 목록에 없는 finding은 assessment unknown·"검증 실패 — 사람 확인" 표시로 격리(자동 보정 없음), 잘못된 caution은 버리고 기록, 역할은 계속; 격리 비율 한도는 B51과 같은 25%. (c) 추출 unit 누락: repair 뒤에도 빠진 unit은 attempt 실패 대신 rejected_units(규칙 `extract_unit_missing`)로 격리, 기존 25% 한도·판정 상한 그대로. 정책 v10 하나에 STEP-006과 함께 넣는다(v10은 아직 발행·등록 전).
   - 작업 대상: card_roles.py·card_analysis.py·schemas·contracts(role v2), runner contract map, mock client, 정책 v10(역할 계약 지시), verdict_view(격리 표시), 프런트(격리 표시가 기존 extract 격리 표시를 재사용하는지), RL-03 spec·contracts·business-rules.
   - 검증: 단위(번호 매핑·잘못된 번호·다른 unit 번호·격리 한도·누락 unit 격리·v9 동작 불변), T11 mock, PG, 실제 10건(T5).

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 중간 | standard | 기존 도구 이관, 계약 닫힘 |
| STEP-002 | M | 높음 | complex | 시각·holdout 불변식, 상태 필터 |
| STEP-003 | S | 낮음 | standard | 절차 |
| STEP-004 | M | 높음 | complex | 사람 참여·실제 호출 경계·결과 해석 |
| STEP-005 | S | 낮음 | standard | 문서 |
| STEP-006 | M | 높음 | complex | selector·정책 버전 불변식, 실제 분석 영향 |
| STEP-007 | M | 높음 | complex | 출력 계약·격리 의미 변경 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| gold가 모델 출력 뒤 작성됨 | `gold_after_model` | export 거부, 표본 교체 |
| 실제 수집 10건이 모이지 않음 | 선정 가능 공고 < 10 | 기간을 늘려 기다린다(fixture로 대체하지 않음) |
| 홀드아웃 공고가 자동 분석됨 | `holdout_violated` | STEP-003을 RL-03 자동 트리거 활성화 전에 |
| 분모 0을 통과로 읽음 | metrics null | 미측정 고정(criteria) |
| 문서화 완료를 인수로 표시 | status done | 사람 decision 전 `validating` |

## 증명

- docs: `doctor _`, 문서 diff.
- tests: `pytest tests/test_rl_gold.py web/backend/tests/app/test_export_evaluation.py`.
- postgres: export CLI PG 변형 1건(attempt·stage fixture).
- frontend: 비적용.
- api_guard: 비적용(외부 호출·회사 자원 접근 없음; export는 읽기 전용).
- real_data_run: T5 — gold 10·attempt 10·metrics·사람 decision 파일 sha를 README에 기록.

## 결과

구현 후 작성한다.
