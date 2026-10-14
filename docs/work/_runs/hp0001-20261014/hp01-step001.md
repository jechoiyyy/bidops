# HP-01 STEP-001 결과

- 시작 기준: `fba715332e70e0994e2296a8899acf8270f5bd6b` (작업 중 HP-00 배치 통합으로 HEAD `daf520186bc4381bf64837bba24eeabee9cbc20a`)
- 구현: 라벨·값 카드 판정/파서, 카드 표의 열 제목 경로 제외와 segment 경계 편입, 기존·카드 inventory 원문 순서 병합, 중복 ID/두 경로 prefix 요약, 카드·segment의 가까운 앞 비어 있지 않은 문단 3개 anchor, extractor v2 규칙 hash.
- 직접 검사: `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false /tmp/bidops-hp0001-20261014-venv/bin/python -m pytest tests/deep_review/test_document_segments.py -q -k 'label_value_cards or card_label_variants or card_table_is_not or tokenless_card or card_ids_and_prefixes'` → `5 passed, 26 deselected`.
- 구문 검사: `/tmp/bidops-hp0001-20261014-venv/bin/python -m py_compile web/backend/app/deep_review/services/document_segments.py web/backend/tests/deep_review/test_document_segments.py` → 통과.
- 예상 차단: `test_wire_payload_satisfies_the_published_contract`는 STEP-002 전 JSON 계약이 새 필수 요약 키 `card_item_count`·`label_value_table_count`를 `additionalProperties`로 거부한다. 임시 스키마 우회는 하지 않았다.
- 변경: `web/backend/app/deep_review/services/document_segments.py`, `web/backend/tests/deep_review/test_document_segments.py`.
