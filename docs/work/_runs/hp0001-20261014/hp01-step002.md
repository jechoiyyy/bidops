# HP-01 STEP-002 결과

## 변경

- `requirement_inventory_item.source`(`column_header_table` 기본값, NOT NULL)와 nullable JSONB `card`, `document_segment.page_anchor_block_keys`를 ORM과 revision `0037_requirement_card_columns`에 추가했다.
- source enum, source/card 짝, JSON object/array shape를 SQL CHECK로 고정했다. 기존 행은 UPDATE 없이 default/NULL로 보존한다.
- migration marker, 구 데이터만 있을 때의 downgrade/marker 정리, 새 카드·anchor 데이터가 있을 때의 손실 방지 downgrade 거부를 구현했다.
- runtime `ALEMBIC_HEAD`와 기존 head assertion을 `0037_requirement_card_columns`로 동기화했다. 체인은 `0036_company_analysis -> 0037_requirement_card_columns` 한 갈래다.
- `store_manifest`가 STEP-001의 평행 `segment_anchors`를 strict zip으로 저장하고 inventory `source/card`도 보존하도록 연결했다. `wire_payload`는 세 저장 전용 extra(`inventory_items`, `segment_titles`, `segment_anchors`)를 제거한다.
- document-segments JSON Schema와 Pydantic에 `inherited`, `operations_maintenance`, 필수 summary 키 `card_item_count|label_value_table_count`를 추가했다.
- 저장 검증은 taxonomy binding 일치, mapping status/page range 짝, inherited 단일 쪽, summary count 관계를 함께 검사한다.

## 리더 실행 검사

```sh
cd /Users/temp/orca/bidops/.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/hp0001-20261014-HP-01-requirement-cards/web/backend
BIDOPS_TEST_POSTGRES_URL='postgresql+psycopg://postgres:hp01-test-only@127.0.0.1:32845/bidops_test' \
  /tmp/bidops-hp0001-20261014-venv/bin/python -m pytest \
  tests/deep_review/test_document_segments.py::test_wire_payload_satisfies_the_published_contract \
  tests/deep_review/test_document_segments_postgres.py \
  tests/app/test_document_bundles.py::test_segments_endpoint_returns_the_manifest_without_source_text \
  tests/app/test_company_analysis.py::test_pg_0036_constraints_triggers_and_policy_immutability -q
/tmp/bidops-hp0001-20261014-venv/bin/python -m alembic heads
```

검사 케이스는 T9의 JSON Schema/Pydantic/저장 validator 일치, 저장 전용 extra 비노출, 새 enum 허용과 summary 필수성, T7의 0036 기존 행 upgrade 보존·marker·빈 downgrade/re-upgrade, 카드/anchor PostgreSQL 저장·멱등성·데이터가 있는 downgrade 거부를 포함한다.

## 미완료 경계

- `TAXONOMY_VERSION` 실제 `bidops.segment-taxonomy.v2` 전환과 endpoint literal 변경은 STEP-004 범위로 남겼다. 계약 layer만 `operations_maintenance`를 미리 허용한다.
- anchor를 사용한 `inherited` 쪽 계산과 `requirement_cards` 조회는 STEP-003 범위다.
- 이 STEP에서는 지침에 따라 pytest, PostgreSQL migration, Alembic 명령을 실행하지 않았다.
