# STEP-002 결과

- 구현: ontology/source/version/node/edge/binding/event 7개 테이블, migration0035, exact object version 재읽기, 원자 profile v2/graph 등록, 멱등 활성화와 append-only 감사, 최소권한, JSON CLI.
- 최소 v2 projection 생성은 원자 등록을 위해 이 단계에서 구현했으며 strict 소비·v1 호환 검증은 STEP-004에 남는다.
- 수정: 신규 JSONB CHECK를 dialect별 한정해 기존 JSON 변환 보존; Location 선행 flush; 0035 migration 감사 marker; isolated filesystem의 요청별 rollback/중첩 transaction cleanup. MinIO 발행 version은 삭제하지 않고 reconciliation 대상으로 보존한다.
- 검증: `step002-migration-diagnostic3.log` fresh PostgreSQL17.11 upgrade head exit0. `step002-scoped-jsonb-tests.log` 최초 suite 136passed/10failed/skip0, 실패 9개 Location FK + 1개 감사 marker. 실패 기록은 보존했다.
- 수정 후 직접 영향 검사 `step002-registration-fixes.log`: 등록/CLI/감사 marker 24passed, skip0. 추가 `test_models::test_init_db_creates_all_declared_tables_and_indexes` 1failed는 아래 기존 실패로 확인했다.
- 기존 실패 재현: 기준 demo/local-20261009 HEAD506ac77의 web/backend에서 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false /tmp/bidops-demo00-verify-venv/bin/python -m pytest tests/app/test_models.py::test_init_db_creates_all_declared_tables_and_indexes -q` 실행. exit1, 1failed 0.53s. 기대 목록에 기존 assumption_input_version/assumption_run/assumption_stage/deep_review_preview/deep_review_approval 5개가 빠져 현재와 동일하게 실패했다. 이번 기능의 7개 테이블은 기대 목록에 반영했으며 관련 없는 기존 기대값은 바꾸지 않았다.
- 실행 범위: isolated SQLite 및 일회용 PostgreSQL. 실제 회사 원본 등록·모델 호출·실행 중 스택 migration 없음.
- 별도 전체 기능 독립 리뷰는 STEP-005 뒤 수행한다. 이 기록은 기능 완료 proof가 아니다.
