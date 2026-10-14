# HP-01 STEP-005 결과 — segment manifest backfill CLI

`python -m app.deep_review.cli rebuild-segment-manifests (--structure-id <uuid> | --all) [--dry-run]`을 추가했다. 출력은 구조마다 `structure_id`, `created`, `manifest_id`, `errors`만 담은 JSONL이며, 성공 0·입력 오류 2·처리 오류 1로 종료한다. `--all`은 `validation_status=ready`인 구조만 생성 시각·ID 순으로 처리한다.

`DocumentBundleService._load_structure_payload`의 검증을 모듈 함수 `load_structure_payload(session, structure, store, *, allow_unsafe=False)`로 승격했다. 서비스와 CLI가 같은 함수로 source/structure location의 고정 object version·etag·크기·SHA-256, 최신 clean scan, 문서·구조·payload 계보, `validate_structure`를 검사한다. 서비스의 `allow_unsafe=True` 내부 경로는 기존 의미를 유지하고, CLI는 `False`로 고정한다.

CLI는 현재 taxonomy/extractor identity manifest가 있으면 객체를 다시 읽거나 행을 쓰지 않고 `created=false`와 기존 ID를 반환한다. 없으면 구조별 savepoint 안에서 `store_manifest`를 직접 호출한다. `ensure_manifest`의 예외 삼키기 경로는 사용하지 않는다. 한 구조가 실패하면 `processing_failed`만 기록하고 다른 구조의 성공 savepoint를 보존한다. dry-run은 payload 검증까지만 하고 transaction을 rollback한다. 원본 객체와 기존 manifest를 UPDATE/DELETE하는 경로는 없다.

T10 PostgreSQL 검사는 다음을 포함한다.

- 실제 새 interpreter의 모듈 진입점과 CLI help dispatch
- runtime privilege policy의 worker 권한을 상속한 일회용 로그인으로 실제 CLI 프로세스 실행
- dry-run 무쓰기, 생성, 같은 manifest ID의 멱등 재실행
- 없는 UUID의 `not_found`/exit 2
- structure 객체 hash/version 불일치의 `structure_unavailable`/exit 1과 manifest 미생성
- 한 구조의 저장 예외 뒤 형제 구조 manifest가 남는 savepoint 보존
- `--all`에서 ready가 아닌 구조 제외

리더 실행 명령:

```sh
cd /Users/temp/orca/bidops/.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/hp0001-20261014-HP-01-requirement-cards/web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false \
BIDOPS_TEST_POSTGRES_URL='postgresql+psycopg://postgres:hp01-test-only@127.0.0.1:32845/bidops_test' \
  /tmp/bidops-hp0001-20261014-venv/bin/python -m pytest \
  tests/deep_review/test_document_segments_postgres.py::test_pg_rebuild_segment_manifests_cli_dry_run_create_repeat_missing_and_hash_mismatch \
  tests/deep_review/test_document_segments_postgres.py::test_pg_rebuild_all_preserves_successful_sibling_savepoint \
  tests/app/test_module_cli_entrypoints.py -q
```

이 단계에서는 지침대로 pytest와 실제 backfill을 실행하지 않았다. Python AST parse와 `git diff --check`만 통과했다.

실제 backfill 범위는 `hp01-backfill-scope.json`에 별도로 확인됐다. 홈페이지 기본 사전규격 79·116·129·156 중 기존 ready 구조는 notice 79의 `f25729bf-e39f-4624-a17c-bcbeaa023888` 한 건이며, 나머지 세 건은 구조가 없다. 이 CLI 구현은 범용 `--all` 계약을 유지하며, 해당 한 건의 실제 실행과 전후 불변성 확인은 리더의 후속 격리 배포 단계다.
