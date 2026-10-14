# HP-01 STEP-003

- `_segment_pages`가 대상 block 직접 매핑을 우선하고, 없으면 저장된 anchor의 첫 매핑 page를 상속한다. `read_manifest_view`는 저장된 segment anchor를 사용한다.
- 공개 순수 함수 `resolve_card_pages`와 DB 기반 `requirement_cards`를 추가했다. 카드 조회는 현재 identity manifest의 `label_value_table` 행만 ordinal 순으로 읽고 구조 payload는 다시 읽지 않는다. 대응표는 `segments_view`와 같은 고정 version·hash·schema 검증을 거친다.
- T5 단위 실행 명령:

  ```bash
  cd web/backend && /tmp/bidops-hp0001-20261014-venv/bin/python -m pytest \
    tests/deep_review/test_document_segments.py::test_segments_are_unavailable_without_a_para_page_map \
    tests/deep_review/test_document_segments.py::test_para_page_map_yields_mapped_partial_and_inherited_segments \
    tests/deep_review/test_document_segments.py::test_segment_pages_prefers_direct_mapping_over_anchors \
    tests/deep_review/test_document_segments.py::test_requirement_cards_returns_empty_without_current_manifest \
    tests/deep_review/test_document_segments.py::test_resolve_card_pages_uses_only_card_locator_and_nearest_anchor \
    tests/deep_review/test_document_segments.py::test_para_page_map_hash_mismatch_fails_closed -q
  ```

- T7 PostgreSQL 실행 명령:

  ```bash
  cd web/backend && /tmp/bidops-hp0001-20261014-venv/bin/python -m pytest \
    tests/deep_review/test_document_segments_postgres.py::test_pg_0037_preserves_existing_rows_and_round_trips_when_no_new_data \
    tests/deep_review/test_document_segments_postgres.py::test_pg_store_manifest_persists_card_source_card_json_and_parallel_anchors \
    tests/deep_review/test_document_segments_postgres.py::test_pg_current_manifest_reads_inherited_segments_and_requirement_cards \
    tests/deep_review/test_document_segments_postgres.py::test_pg_requirement_cards_fails_closed_when_page_map_hash_is_tampered -q
  ```

  PostgreSQL command requires the prepared disposable server in `BIDOPS_TEST_POSTGRES_URL`.
- 테스트 실행은 리더가 통합 실행하므로 이 단계에서는 실행하지 않았다.
