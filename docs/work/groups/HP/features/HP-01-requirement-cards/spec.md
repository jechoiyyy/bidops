# 요구사항 카드 inventory·쪽 상속·taxonomy v2 — spec

- 기능 ID: `HP-01-requirement-cards`
- 근거: [intent.md](./intent.md), [HP 공통 계약](../../../../hp-contract.md) §2·3
- 작성일: 2026-10-14 (같은 날 독립 검사 1·2차 지적 반영)

## 큰 틀 문서와의 관계

- 인용하는 절: HP 공통 계약 §2(입력 정본·대응표) §3.1~3.4, contracts.md `DocumentSegmentsView`·`GET /api/document-structures/{structure_id}/segments`·세 inventory 테이블 append-only 규칙, ADR-0051, deep-review-erd.md(`document_segment_manifest`·`document_segment`·`requirement_inventory_item`).
- 이 문서에서 새로 확정하는 항목: extractor 버전·규칙 hash 구성, 카드 표 판정과 우선순위, 카드 prefix와 문단 후보의 관계, 저장 열과 anchor 운반 방식, 쪽 anchor 규칙, `requirement_cards`·backfill CLI 서명과 실행 자리, 증거 스크립트의 입력·출력, 계약 파일 변경 범위.
- 큰 틀 문서 수정이 필요한 항목(STEP-007): contracts.md의 `mapping_status` enum(`inherited`), `taxonomy_version`(`v2`), `taxonomy_labels`(`operations_maintenance`), `inventory_summary` 키 2개(필수), inventory 테이블 열 2개와 segment 열 1개, CLI `rebuild-segment-manifests`; deep-review-erd.md 열 추가; ARCHITECTURE.md 한 줄. ADR 색인은 ADR-0071 항목으로 갈음한다.

## 입력·출력 계약

### 상수

- `EXTRACTOR_VERSION = "2"`, `TAXONOMY_VERSION = "bidops.segment-taxonomy.v2"`, `SCHEMA`는 `bidops.document-segments.v1` 유지.
- `_RULES`에 `card_labels`(§3.1 사전), `card_table_rule="id_label_with_token_value"`, `card_prefix_rule="cards_only"`, `category_taxonomy`(§3.4 표), `page_anchor_rule="nearest_preceding_nonempty_paragraphs:3"`를 더한다. 규칙 hash가 바뀌므로 `EXTRACTOR_BINDING_SHA256`이 바뀐다.

### 카드 표 판정과 우선순위

- `table_cell` block을 `table_key -> {(row, column): block}`로 모은다. 셀 text는 공백 제거·casefold한 값으로 라벨을 비교한다.
- **카드 표** = requirement_id 라벨 셀이 하나 이상 있고, 그중 적어도 하나의 같은 행 오른쪽 첫 비어 있지 않은 비라벨 셀에 `_ID_TOKEN`이 있는 표.
- 카드 표는 `_table_columns`(열 제목 표 탐지)에서 제외한다(`요구사항고유번호`·`요구사항번호`·`요구사항id`가 `_ID_COLUMN_HEADERS`와 겹치므로 이 제외가 우선순위다). 카드 표는 열 제목 표와 같은 자격으로 segment 경계(`_boundaries`의 표 집합)에 들어간다.
- hwpx 변환기는 중첩 표의 행·셀을 바깥 `table_key`로 한 번 더 내고 바깥 셀 text에 안쪽 글자를 포함한다. 그래서 중첩 규칙은 두지 않는다. 같은 ID가 두 표(또는 같은 표의 중복 행)에서 나오면 둘 다 보존하고 `duplicate_ids`에 적는다(기존 규칙).

### 카드 파서 (`_collect_cards(blocks) -> list[_Card]`)

1. requirement_id 라벨이 있는 행을 오름차순으로 세워 카드 경계를 만든다. 시작 행 = 그 행 위쪽에서 가장 가까운 category 라벨 행(없으면 requirement_id 행), 끝 행 = 다음 requirement_id 라벨 행 직전(없으면 표의 마지막 행).
2. 범위 안 각 행에서 라벨 셀을 찾고 값은 같은 행에서 그 오른쪽의 첫 비어 있지 않은 비라벨 셀 text다(열 번호 순). 같은 필드가 두 번 나오면 첫 값을 쓴다.
3. requirement_id 값에 `_ID_TOKEN`이 없으면 그 카드는 만들지 않는다(경고 없음). 있으면 `raw_id`=값, `normalized_id`=`_normalize_id`.
4. 카드 locator는 requirement_id 라벨 행의 첫 셀(column 최소)이며 `kind="table_cell"`. `first_cell_block_key`는 그 표에서 ordinal이 가장 작은 셀의 block_key.
5. 필수 필드(category·title·definition·details)가 비면 `card_warnings`에 `missing:<field>`를 넣고 카드는 만든다. `related_ids`는 `related_raw`에서 `_ID_TOKEN`으로 읽어 정규화·정렬·중복 제거한다. 값은 원문 그대로 보존한다.
6. `page_anchor_block_keys` = 그 표의 첫 block(`table` block)보다 앞에 있는, text가 비어 있지 않은 `paragraph` block 중 가장 가까운 3개의 block_key(가까운 순). 없으면 빈 배열.

### 카드 prefix와 기존 후보 경로

- 카드는 그 자체로 항목이 되며 기존 `_confirm_prefixes`를 거치지 않는다. **카드 prefix는 문단 경로 후보를 확정하지 않는다.** 본문의 "SFR-001 참조" 같은 문단 언급은 그 prefix가 기존 규칙(열 제목 표 또는 `_MIN_LEADING_OCCURRENCES`)으로 확정된 경우에만 기존처럼 항목이 된다.
- `_build_inventory`는 기존 경로 항목(기존 규칙 그대로)과 카드 항목을 원문 ordinal 순으로 합친다. `inventory_summary.prefixes`는 두 경로의 합집합이다. `ambiguous_items`는 기존 경로 규칙 그대로다.

### 항목 계약과 저장

- 항목(`bidops.requirement-card.v1`, 공통 계약 §3.2)에 `page_anchor_block_keys: string[]`를 `card` 안에 더한다. 열 제목 경로 항목은 `source="column_header_table"`, `card=null`.
- `inventory_summary`에 `card_item_count`(int, 필수), `label_value_table_count`(int, 필수)를 더한다. JSON 스키마·pydantic·TS 모두 필수다(`_manifest_for_structure`가 현재 identity 행만 고르므로 v1 행은 조회에 나오지 않는다). `expected_ids`·`prefixes`·`duplicate_ids`는 두 경로의 합집합. `inventory_empty`는 두 경로 모두 0건일 때만.
- segment anchor 운반: `build_manifest_payload`는 `payload_sha256`을 계산한 **뒤** `segment_titles`와 같은 방식으로 평행 목록 `segment_anchors: list[list[str]]`(segment 순서, 각 segment 첫 block보다 앞의 비어 있지 않은 문단 3개)를 붙인다. `wire_payload`가 `inventory_items`·`segment_titles`와 함께 `segment_anchors`를 뗀다. `store_manifest`가 segment 행마다 `page_anchor_block_keys`에 저장한다. anchor는 `payload_sha256`에 들어가지 않고(`page_range`와 같은 취급) 규칙 hash가 규칙을 고정한다.

### 쪽 계산 (읽기 시점)

- `_segment_pages(source_block_keys, block_pages, anchor_block_keys) -> {page_range, mapping_status}`:
  1. `block_pages is None` → `unavailable`.
  2. `source_block_keys` 중 매핑된 키가 하나라도 있으면 기존 규칙(`mapped|partial`, min/max). 대응표가 셀을 직접 매핑한 경우도 여기에 든다.
  3. 아니면 `anchor_block_keys` 순서대로 첫 매핑된 키의 `page_first`를 `p`로 하여 `inherited`, `page_range={first:p,last:p}`.
  4. 아니면 `unavailable`·`null`.
- 구조 payload를 읽기 시점에 다시 읽지 않는다. anchor는 build 시점에 저장한 값이다.
- `resolve_card_pages(payload, page_map) -> list[dict]`(공개, 순수 함수): manifest payload의 카드 항목에 위 규칙으로 `page_range`·`mapping_status`를 붙인다. 증거 스크립트와 `requirement_cards`가 함께 쓴다.
- `requirement_cards(session, structure_id, store) -> list[dict]`(`store` 필수): 최신 manifest(`_manifest_for_structure`)의 `label_value_table` 항목을 ordinal 순으로 돌려주며, 대응표는 `segments_view`와 같은 경로로 읽고 같은 fail-closed(`SegmentViewError`)다. manifest가 없으면 빈 목록. 구조 존재·unsafe 여부는 호출자(HP-03)가 `structure_is_readable`로 먼저 검사한다.

### taxonomy v2

- `_category_labels(category_text) -> set[str]`: 공백 제거 뒤 접미 "요구사항"을 떼고 §3.4 표의 키와 정확히 일치하면 label 하나. 아니면 빈 집합.
- segment label = 그 segment 카드들의 category label 합집합. 카드가 없으면 기존 `_keyword_labels | _prefix_labels`. 카드 label이 있으면 제목 키워드 label과 달라도 카드 label을 쓰고 충돌로 보지 않는다. 기존 키워드·접두사 간 충돌 규칙은 유지.
- `_PREFIX_TAXONOMY`에 `ECR→technical_functional`, `STR→quality_security_constraints`, `MAR/MPR/MHR→operations_maintenance`, `_TAXONOMY_KEYWORDS["operations_maintenance"]=("유지관리","유지보수","운영","장애","서비스수준","상주")`를 더한다.

### backfill CLI

- `python -m app.deep_review.cli rebuild-segment-manifests (--structure-id <uuid> | --all) [--dry-run]` → 구조별 `{structure_id, created: bool, manifest_id: uuid|null, errors: string[]}` JSON 줄.
- 실행 자리: **analysis-worker 이미지·worker 역할**(DB와 객체 저장소 env를 모두 가진 서비스; `enqueue-company-fit`과 같은 자리). document-worker는 DB·MinIO 접근이 없다.
- 구조 payload 읽기: `DocumentBundleService._load_structure_payload`를 모듈 함수 `load_structure_payload(session, structure, store, *, allow_unsafe=False)`로 승격해(동작 동일: location 조회·sha256/size/etag/version 검증·lineage 대조·`validate_structure`) CLI와 service가 같이 쓴다. `allow_unsafe=False` 고정.
- 생성 판정: 현재 identity의 manifest가 있으면(`_manifest_for_structure`) `created=false`. 없으면 CLI 자신의 savepoint 안에서 `store_manifest`를 부르고 예외를 `errors[]`에 담는다(`ensure_manifest`는 예외를 삼키므로 쓰지 않는다). 기존 행은 건드리지 않는다.
- `--all`은 `DocumentStructure.validation_status == "ready"`인 구조만 돈다. exit 0 성공, 2 입력 오류(없는 id·인수), 1 처리 오류(기존 CLI 규칙).

### 증거 스크립트 `scripts/hp-card-inventory-check.py`

- 입력: `--structure <json> --page-map <json>` 쌍을 반복하거나 `--dir <디렉터리>`(파일명 `<name>.structure.json`·`<name>.para_page_map.json`; 이 이름은 이 스크립트의 규약이며 README가 생성 명령을 적는다).
- 동작: `build_manifest_payload`와 `resolve_card_pages`를 호출한다. DB·네트워크·저장 없음. `PYTHONPATH=web/backend`로 실행(`scripts/transfer-preview.py` 선례).
- 출력: 문서별 `{name, card_count, inherited_page_count, mapped_page_count, unavailable_count, prefixes, categories, duplicate_ids, warnings}`를 stdout과 `--out` 파일에 JSON으로 쓴다. 제품 코드가 정본이며 scratchpad 수치(27/57/31/35/48, 198/198)와 다르면(예: 중첩 표 중복) 차이를 README에 적는다.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| anchor 개수 | int | 3 | 규칙 hash에 포함 | `tunable`이 아니라 규칙 상수 |

## 상태 값과 실패 처리

- segment `mapping_status`: `mapped|partial|inherited|unavailable`. `status`: 기존 `classified|needs_human_review`.
- 카드 경고 `missing:<field>`(항목 `card_warnings`). 기존 manifest 경고 유지.
- 저장 검증(`validate_document_segments`)·pydantic(`DocumentSegmentsView`)·JSON 스키마는 새 enum·키를 알아야 한다. 알기 전에는 `ensure_manifest`가 검증 오류를 삼켜 manifest가 생기지 않으므로 STEP-002가 STEP-001과 같은 단계 묶음에서 끝나야 한다.
- 대응표 읽기·hash·schema 실패는 기존대로 `SegmentViewError`→500 `processing_failed`.
- 업그레이드 전에 변환된 구조는 현재 identity의 manifest가 없어 `/segments` 404·`inventory_context.manifest_count=0`(기존 동작)이며 backfill CLI로 메운다.

## 저장

- Alembic migration 1개: `requirement_inventory_item.source TEXT NOT NULL DEFAULT 'column_header_table'`, `requirement_inventory_item.card JSONB NULL`, `document_segment.page_anchor_block_keys JSONB NULL`. 기존 행은 기본값/NULL로 남고 수정하지 않는다(append-only는 ORM 리스너이며 DDL과 충돌하지 않음). 0034~0036 관례대로 `_record_migration_marker()`로 db.migration 표식을 남긴다. `scripts/runtime-privileges.sql` 변경 없음(세 테이블은 테이블 단위 SELECT/INSERT). migration head 단일 유지.
- `DocumentSegmentManifest` 새 행(extractor version 2). 기존 행 변경 없음.

## 인터페이스(CLI·UI·API)

- `GET /api/document-structures/{structure_id}/segments`: shape 동일, `taxonomy_version`·`taxonomy_labels`·`mapping_status`·`inventory_summary` 값 집합 확장. `contracts/bidops.document-segments.v1.json`과 `schemas/document_bundles.py`의 enum·키를 함께 올린다(`additionalProperties:false` 유지).
- 새 서비스 함수 `requirement_cards`, 공개 함수 `resolve_card_pages`, `load_structure_payload`. 새 CLI `rebuild-segment-manifests`. 새 스크립트 `scripts/hp-card-inventory-check.py`.
- 프런트 `deep-review/types.ts`의 `TaxonomyLabel`·`SegmentMappingStatus`·`RequirementInventorySummary`와 `SegmentInventoryPanel.tsx` 라벨 사전(`operations_maintenance`→"운영·유지관리", `inherited`→"앞 문단 쪽 상속" 주석)을 갱신한다.

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 카드 필드를 `requirement_inventory_item` 열로 저장 | 항목은 JSON이 아니라 행이다(독립 검사 1차). 조회 함수가 DB만 읽어야 한다 | 새 테이블 / manifest JSON에 넣기 |
| 쪽 anchor를 build 시점에 저장, `segment_titles`와 같은 평행 목록으로 운반 | 읽기 시점에 구조 payload를 다시 읽지 않는다. segment 객체에 넣으면 스키마 `additionalProperties:false`에 걸린다(독립 검사 2차) | 읽기 시점 payload 로드 / segment 객체 확장 |
| 매핑된 키가 있으면 `mapped|partial` 우선 | 대응표가 셀을 직접 매핑할 수 있다. 상속은 추정이므로 직접 매핑보다 낮다 | 항상 상속 |
| 카드 prefix는 문단 후보를 확정하지 않는다 | 본문 참조 문장이 항목·중복 ID가 되어 `requirement_inventory` 검증을 흔든다(독립 검사 2차) | 카드 prefix로 문단 후보 확정 |
| 카드 표를 열 제목 탐지에서 제외하고 경계로 삼는다 | 라벨이 `_ID_COLUMN_HEADERS`와 겹쳐 이중 탐지·경계 불일치가 생긴다(독립 검사 1차) | 두 탐지 병행 |
| 중첩 표 규칙 없음 | 변환기가 평탄화한다(`document_mcp/hwpx.py`) | `nested_table_unparsed` 경고 |
| backfill CLI를 analysis-worker 자리에서 | DB와 객체 저장소를 둘 다 가진 worker 역할 서비스가 그것뿐이다(독립 검사 2차) | document-worker(접근 없음) |
| `_load_structure_payload`를 모듈 함수로 승격 | private 메서드를 CLI가 부르지 않는다 | 로직 복제 |
| 카드 prefix는 확정 prefix | 카드 양식 자체가 근거; 1장짜리 접두사(ECR·STR·MAR) 보존 | `_MIN_LEADING_OCCURRENCES` 적용 |
| 카드 category label이 제목 키워드보다 우선 | 원문 분류가 제목 추정보다 근거가 세다 | 충돌로 `needs_human_review` |
| wire schema v1 유지 | 필드 제거·의미 변경 없음 | `bidops.document-segments.v2` |
| 증거 스크립트는 저장소 밖 변환 결과를 읽는다 | 공고 원문·구조 JSON을 저장소에 넣지 않는다 | fixture 커밋 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | 카드 2장이 쌓인 표(응락·산출·관련 혼합) | 항목 2건, 필드 보존, `related_ids` 정규화, anchor 3개, `card_item_count=2`, `label_value_table_count=1` | 단위 |
| T2 | 라벨 변형(고유번호/요구사항번호/세부설명/산출물)·필수 필드 누락 | 변형 인식, `missing:definition` 경고, 카드 생성 | 단위 |
| T3 | `요구사항고유번호` 라벨 카드 표와 열 제목 표 공존, 본문의 카드 prefix 언급 | 카드 표는 열 제목 탐지에서 제외·경계가 됨, 두 경로 `source` 구분, 같은 ID면 `duplicate_ids`, 본문 언급은 항목이 아님 | 단위 |
| T4 | ID 토큰 없는 카드, 같은 ID가 두 카드 표에 | 미생성 / 둘 다 보존·`duplicate_ids` | 단위 |
| T5 | 쪽 계산: 매핑 문단 뒤 표 / 매핑 문단 앞 표 / 셀 직접 매핑 / 일부 매핑 segment; `resolve_card_pages` | `inherited` / `unavailable` / `mapped` 우선 / 기존 `partial` | 단위 |
| T6 | taxonomy v2: category 7종, MAR/MPR/MHR/ECR/STR, 제목 키워드 `장애 대응`, 카드 label 우선 | 기대 label, `taxonomy_version=v2` | 단위 |
| T7 | PG: migration 열 3개·표식·v1 행이 있는 구조에 `ensure_manifest`·`segments_view`·`requirement_cards` | 새 행 추가(anchor 저장)·기존 행 불변·최신 행 조회·`inherited` 응답·카드 목록 | PG 통합(기존 `tests/postgres.migrated_engine()`·`requires_postgres` marker 사용) |
| T8 | `inventory_context`·`observed_requirement_ids` | 카드 ID·prefix 포함, 관측 수 일치 | 단위 |
| T9 | wire·JSON 스키마·pydantic 계약(`test_wire_payload_satisfies_the_published_contract`, `test_document_bundles.py`의 taxonomy_version 리터럴), `segment_anchors`가 wire에 없음 | 새 enum·키 통과, `additionalProperties:false` 유지 | 단위/API |
| T10 | backfill CLI: dry-run / 생성 / 재실행 / 없는 id / 객체 hash 불일치 | 쓰기 없음 / created / created=false / exit 2 / errors에 기록·행 없음 | PG 통합 |
| T11 | 증거 스크립트를 실제 변환 결과 5건에 실행 | 카드·쪽 수치 JSON 기록(목표 27/57/31/35/48, 상속+직접 매핑 198/198; 차이는 README) | 명령(저장소 밖 입력) |
| T12 | 프런트 타입·라벨 사전 | `npm run build`(tsc 포함) 통과, 패널이 새 label·상속 주석을 보인다 | frontend |

## 컨벤션 반영 항목

`mapping_status=inherited`, `taxonomy_version=bidops.segment-taxonomy.v2`, `operations_maintenance`, `inventory_summary.card_item_count|label_value_table_count`(필수), 열 `requirement_inventory_item.source|card`, `document_segment.page_anchor_block_keys`, CLI `rebuild-segment-manifests`(analysis-worker) → contracts.md·deep-review-erd.md.
