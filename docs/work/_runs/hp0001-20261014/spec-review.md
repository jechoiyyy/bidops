# 실행 전 명세 검토

- 독립 reviewer: gpt-5.6-sol / high, hp_spec_review. 기준 fba715332e70e0994e2296a8899acf8270f5bd6b.
- HP-00: v5가 v4 identity를 상속하면 canonical import 불가. policy_identity=v5를 포함한 4키 변경과 identity map 등록으로 spec/plan 정정, accept-spec 기록. 추가 차단 없음.
- HP-01: intent의 requirement_cards 서명에 store 누락. 구현은 spec/plan의 (session, structure_id, store)를 따른다. resolve_card_pages 직접 매핑은 item.locator.block_key, 상속 후보는 card.page_anchor_block_keys로 fixture/주석에 고정한다. 비차단.
- 실제 모델, 스택 교체, 정책 import·선택, backfill은 별도 직전 확인.
