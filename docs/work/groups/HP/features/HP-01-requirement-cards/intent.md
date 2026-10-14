# 요구사항 카드 inventory·쪽 상속·taxonomy v2 — intent

- 기능 ID: `HP-01-requirement-cards`
- 상위 항목: [HP 로드맵](../../../../constitution/roadmap.md), [HP 공통 계약](../../../../hp-contract.md) §2·3
- 크기: M — `document_segments`와 그 저장 모델·계약 스키마·테스트, backfill CLI, 프런트 타입을 바꾼다. 새 wire enum 값 하나(`inherited`)와 열 3개가 생기고 외부 호출은 없다.
- 작성일: 2026-10-14 (같은 날 독립 검사 지적 반영)

## 문제

홈페이지 제안요청서 5건의 요구사항은 라벨·값 카드(분류/고유번호/명칭/정의/세부내용…) 양식인데 기존 inventory는 "요구사항 ID"가 열 제목인 표만 읽어 198장 중 0·11·0·0·9장만 잡는다.
문단↔쪽 대응표는 text 일치로 문단(과 드물게 셀)을 매핑하므로 표 셀로 된 카드는 대부분 쪽을 받지 못한다(외교부 문서 6,150 block 중 1,339만 매핑, 전부 문단).
taxonomy에 운영·유지관리 목적과 MAR·MPR·MHR 접두사가 없어 유지관리 공고의 절반이 `needs_human_review`로 남는다.
이 셋이 비면 HP-03의 분석 단위(unit)와 HP-04의 쪽 점프가 성립하지 않는다.

## 기대 결과

구조화가 끝난 문서의 manifest에 카드가 inventory 항목으로 들어가고(`source=label_value_table`, 카드 필드·쪽 anchor 보존), segments 조회와 카드 조회가 쪽을 `inherited`(앞 문단 상속)로 돌려주며, 유지관리 segment가 `operations_maintenance`로 분류된다.
deep_review는 `requirement_cards(session, structure_id)`로 카드 목록을 읽는다. 기존 manifest 행과 열 제목 표 경로는 그대로 남고, 업그레이드 전 구조는 backfill CLI로 현재 manifest를 얻는다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| 카드 inventory | 단위 테스트: 카드 2장이 쌓인 표 payload로 `build_manifest_payload` | `inventory_items` 2건, `source=label_value_table`, category·definition·details·compliance_level·outputs·related_ids·anchor 보존, `inventory_summary.card_item_count=2` |
| 열 제목 표와 공존 | 열 제목 표와 카드 표(라벨 `요구사항고유번호`)가 한 문서에 | 카드 표는 열 제목 탐지에서 제외되고 경계가 되며, 같은 ID면 둘 다 보존·`duplicate_ids` |
| 쪽 상속 | PG 통합 테스트: 대응표 snapshot이 있는 구조의 `GET /api/document-structures/{id}/segments`와 `requirement_cards` | 카드 segment·카드 항목 `mapping_status=inherited`, `page_range.first=last=`앞 문단의 page_first; 앞에 매핑 문단이 없으면 `unavailable`; 셀이 직접 매핑되면 `mapped` |
| taxonomy v2 | 단위 테스트: category "유지관리 수행 요구사항" 카드 segment와 제목 "장애 대응 체계" segment | `taxonomy_labels=["operations_maintenance"]`, `taxonomy_version=bidops.segment-taxonomy.v2` |
| 기존 행 보존·backfill | PG 통합 테스트: v1 행이 있는 구조에 `ensure_manifest`; `rebuild-segment-manifests --structure-id` | 새 행(version 2) 추가, 기존 행 unchanged, 조회는 최신 행; CLI 재실행은 created=false |
| 검증 연결 | `inventory_context`·`observed_requirement_ids` | 카드 ID가 expected_ids에, 카드 접두사가 prefixes에 포함 |
| 계약 일치 | wire·JSON 스키마·pydantic·프런트 타입 | 새 enum·키가 네 곳에서 같다 |
| 실제 5건 증거 | 격리 worker 변환 결과 5건에 `scripts/hp-card-inventory-check.py` | 카드 27/57/31/35/48, 쪽(상속+직접 매핑) 198/198 목표, 결과 JSON을 `docs/validation-runs/<날짜>-hp/HP-01/`에 기록 |

## 선행·후속 기능

- 선행: 없음(DEMO-01~04 코드는 기준 브랜치에 이미 있다).
- 후속: HP-02-homepage-ontology-company(어휘 매핑 검토에 카드 목록 사용), HP-03-two-tier-analysis(unit 생성).

## 영향 범위

- 모듈·컴포넌트: `web/backend/app/deep_review/services/document_segments.py`, `models.py`, Alembic migration, `contracts/bidops.document-segments.v1.json`, `schemas/document_bundles.py`, 새 CLI `rebuild-segment-manifests`, 테스트, 프런트 `deep-review/types.ts`·`SegmentInventoryPanel.tsx`, `scripts/hp-card-inventory-check.py`.
- 큰 틀 문서의 절: HP 공통 계약 §2·3, contracts.md `DocumentSegmentsView`·inventory 테이블, deep-review-erd.md, ARCHITECTURE deep-review-v2 결정적 부분집합(ADR-0051 확장).
- 데이터·저장소: `requirement_inventory_item.source|card`, `document_segment.page_anchor_block_keys` 열 추가(migration 1개, 기존 행 불변), `DocumentSegmentManifest` 새 행. 권한 변경 없음.
- 외부 서비스·호출: 없음.

## 제약

- (공통) 원문·프로필·정책·모델 입력과 결과·사람 리뷰는 불변/append-only로 보존한다.
- (공통) unknown/null·적합성·참여 준비·추적·Go/No-Go를 서로 대신하지 않는다.
- (공통) 외부 모델은 승인 payload만 건별 전송하며 전역 fallback과 자동 추적 결정을 금지한다.
- (공통) PostgreSQL 17·versioned MinIO·합성 analysis worker의 슬롯 1개와 모듈 의존 방향을 유지한다.
- (공통) 문서 변경은 diff/문서 검사만, 제품 변경은 직접 영향 검사만 실행하고 성공 후 반복하지 않는다.
- (공통) 운영 변경·실제 모델 호출은 직전 확인 대상이며 문서화 승인을 실행 승인으로 사용하지 않는다.
- (공통) HP 기능은 데모 브랜치 demo/local-20261009와 bidops-local 격리 자원에서만 구현·검증하며 main 병합·운영 전환은 별도 작업이다(ADR-0071).
- (공통) HP의 모델 호출은 codex-exec gpt-6-luna/high 하나다. LiteLLM local-agent-main·Qwen·Terra를 쓰지 않고, 기존 정책 파일·실행 row는 바꾸지 않는다(ADR-0071).
- (공통) HWP/HWPX 원본이 입력 정본이며 PDF는 PDF 전용 첨부와 쪽 locator에만 쓴다. OCR은 범위 밖이다(ADR-0071).
- (공통) 새 DB 테이블·열 권한은 scripts/runtime-privileges.sql에 등록하고 migration에 GRANT를 쓰지 않는다.
- (공통) 사용자 요청 없이 commit·merge·push·브랜치 삭제하지 않는다.
- (기능별) 카드 값은 원문 그대로 보존하고 요약·정규화하지 않는다(ID 정규화만). 쪽은 대응표에서만 오며 대응표가 없으면 쪽을 만들어 내지 않는다. 상속은 직접 매핑보다 낮은 상태로 구분해 보인다.
- (기능별) 기존 `bidops.document-segments.v1` wire 필드를 제거하거나 뜻을 바꾸지 않는다. 추가는 enum 값 `inherited`, label `operations_maintenance`, `inventory_summary` 키 둘뿐이다.
- 기준 출처/hash: [source-baseline](../../../../source-baseline.json). 실행용 복사: [feature.json](../../../../feature.json)의 constraints/constraint_sources.

## 범위 밖

- 카드 조회 REST(HP-04가 화면 요구에 맞춰 정한다), PDF 전용 첨부·OCR(공통 계약 D9), 열 제목 표 경로의 규칙 변경, 묶음 재시작 화면.
- 모델 호출·분석 unit 생성(HP-03).

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 쪽의 출처 | contracts.md: 대응표의 매핑된 키만으로 계산, 셀은 대개 `unavailable` | 2026-10-14 검증: 앞 문단에서 상속하면 198/198 | 상속을 새 enum `inherited`로 추가하되 직접 매핑이 있으면 그것을 우선 |
| 대응표 범위 | HP 공통 계약 §2 초안 "문단 block만 매핑" | 코드(`para_page_map.py`)는 text 일치로 셀도 매핑 가능 | 계약 문구를 "문단과 text가 유일하게 일치하는 셀"로 고침(이번 replan에서 수정) |
| taxonomy | v1 4개 label | 유지관리 공고 카드의 절반이 유지관리 분류 | v2 label 추가, v1 규칙은 유지 |
| 저장 | spec 초안 "migration 없음" | inventory 항목은 열 5개 행 | 열 3개 추가 migration |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 실제 5건 증거 디렉터리 이름 | 구현 중 | 실행일 기준 `docs/validation-runs/<YYYY-MM-DD>-hp/HP-01/` |
| backfill을 `bidops-local`의 어느 구조에 돌릴지(179건 전부 vs 홈페이지 4건) | 구현 중(STEP-005 뒤) | 사용자 확인; 기본은 홈페이지 사전규격 4건 |
