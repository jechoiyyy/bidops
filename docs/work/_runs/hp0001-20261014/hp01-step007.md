# HP-01 STEP-007 결과

- **범위:** 증거 CLI와 계약·문서 갱신.
- **입력 변환:** [`hp01-conversion.json`](./hp01-conversion.json)에 기록된 2026-10-14 격리 worker 결과 5건을 재사용했다. 변환 재실행과 모델 호출은 없었다.
- **증거 출력:** 2026-10-15 기록한 [`cards.json`](../../../validation-runs/2026-10-14-hp/HP-01/cards.json). 명령과 출처는 [검증 README](../../../validation-runs/2026-10-14-hp/HP-01/README.md)에 있다.

제품 함수 `build_manifest_payload`와 `resolve_card_pages`로 카드 198건을 확인했다. 직접 쪽 매핑 0건, 상속 88건, `unavailable` 110건이다. 따라서 쪽 가용성 목표 198/198은 달성하지 못했다. PDF 10표본에서는 상속 쪽 6건이 카드 위치와 일치했고, 미가용 4건은 확인되지 않았다. 이 표본으로 전체 카드의 정확도를 주장하지 않는다. `school` PDF 13쪽 겹침은 기존 `docs/tracking/findings.md` 기록을 참조한다.

최초 합성 CLI 검사는 제품의 `coverage_gap:0-0` 경고를 기대값에서 빠뜨려 2개 통과·1개 실패했다. 기대값을 경고 보존으로 고친 뒤 root가 실패 선택자만 다시 실행해 통과시켰다([`hp01-step007-script-fixed.log`](./hp01-step007-script-fixed.log)). 변경되지 않은 나머지 2개 통과 결과는 동일 소스이므로 재사용했다. 이 작업 agent는 pytest나 build를 실행하지 않았다.

변경 경로: `scripts/hp-card-inventory-check.py`, `web/backend/tests/app/test_hp_card_inventory_script.py`, `docs/contracts.md`, `docs/deep-review-erd.md`, `docs/ARCHITECTURE.md`, `docs/work/hp-contract.md`, HP-01 `intent.md`의 함수 서명, 검증 README와 JSON 결과, 이 결과 기록. 상태·queue·배포·migration·backfill·운영 조작은 변경하거나 실행하지 않았다.
