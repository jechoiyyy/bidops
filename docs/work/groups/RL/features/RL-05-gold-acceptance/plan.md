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

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 중간 | standard | 기존 도구 이관, 계약 닫힘 |
| STEP-002 | M | 높음 | complex | 시각·holdout 불변식, 상태 필터 |
| STEP-003 | S | 낮음 | standard | 절차 |
| STEP-004 | M | 높음 | complex | 사람 참여·실제 호출 경계·결과 해석 |
| STEP-005 | S | 낮음 | standard | 문서 |

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
