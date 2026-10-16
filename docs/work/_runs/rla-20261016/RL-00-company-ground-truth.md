# RL-00-company-ground-truth — run rla-20261016

- 브랜치·worktree: `sdlc/rla-20261016-RL-00-company-ground-truth` · `.sdlc/worktrees/rla-20261016-RL-00-company-ground-truth`, 기준 c93da20
- 단계: 7/7 done → validating(커밋 대기, commit_policy=manual)

## 단계별

| 단계 | 담당 | 결과 |
|---|---|---|
| STEP-001 계약 enum·검증 | implementer-opus | status 4·origin 7·조합 규칙 공용 helper(두 검사기), value 확장 추가형, import 출력 +2키, `real_company_exists`·`fictional_requires_demo` exit 2 |
| STEP-002 실회사 등록·demo 분리 | implementer-opus | 실회사 1곳(PG advisory lock), 감사 is_fictional 요청값, demo off GET 6경로만 통과, `BIDOPS_COMPANY_EXPIRY_WARNING_DAYS` |
| STEP-003 `GET /api/company` | implementer-opus | deep_review 라우터(전체 경로 선언), `company_not_registered`, workload `company_attention`(끝) |
| STEP-004 회사 파일 | implementer-opus | `~/orca/fixtures/company/rootlab/` 노드 148(c126·p1·u21), 문서 밖 사실 없음(unknown 21 목록 README) |
| STEP-005 `/company` 화면 | implementer-sonnet | 읽기 전용 화면·사이드바 연결, 사용자 결정으로 demo-on 리다이렉트 + DEMO 프로필 spec 정리 |
| STEP-006 격리 등록 | 리더 | bidops-local DB `bidops_rla`: migrate·import·activate·REST 확인 |
| STEP-007 문서 | implementer-sonnet | demo-contract RL 절·hp-contract·contracts·business-rules·operations·ui-spec·ADR·theme 주석 |

## 검증(리더 실행, 로그 `logs/`)

- tests: `pytest tests/app/test_company_knowledge_cli.py tests/app/test_company_knowledge_api.py tests/app/test_company_context.py tests/deep_review/test_company_knowledge.py tests/app/test_module_boundaries.py tests/app/test_workload_api.py` → 140 passed, 85 skipped(PG 변형), exit 0 (`logs/RL-00-tests.log`)
- postgres: 일회용 postgres:17.11로 위 파일 + `test_company_context_postgres.py`·`test_runtime_database_privileges.py`·`test_alembic_autogenerate.py` → 255 passed, exit 0 (`logs/RL-00-postgres.log`)
- frontend: `npm run build && npm run test:contrast` exit 0(8/8); Playwright app `company-ground-truth`·`common-interactions`·`company-workspace` 41 passed, `company-layout`(전 프로젝트) 20 passed (`logs/RL-00-frontend-build.log`, `logs/RL-00-playwright*.log`)
- T9 dry-run·STEP-006: `docs/validation-runs/2026-10-16-rl/RL-00/README.md`
- docs: `doctor _` exit 0 (`logs/RL-00-doctor.log`), 독립 리뷰 `RL-00-review.md`

## 재시도·우려·합의

- 재시도: contrast 게이트 1회 실패(spec이 허용한 추정값 blue를 옛 규칙이 막음) → 게이트에 단일 선택자 예외, 다른 선택자·파일은 계속 실패하는지 변이 검사 후 재실행 통과.
- 사용자 합의 2건: `bidops_rla` 새 DB, demo-on 리다이렉트(spec대로).
- 기존 무관 실패: backend `test_postgres_harness.py::test_profile_target_runs_without_docker`, frontend design-shell 2·admin-workspace-consistency 2·route-context 12.
- backlog(리뷰 권고, 범위 밖): plan.md 결과 절 참조.
