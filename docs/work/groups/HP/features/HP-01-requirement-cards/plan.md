# 요구사항 카드 inventory·쪽 상속·taxonomy v2 — plan

- 기능 ID: `HP-01-requirement-cards`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-14 (같은 날 독립 검사 지적 반영)

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/services/document_segments.py | 수정 | 카드 표 판정·파서·inventory 통합·anchor·쪽 계산·taxonomy v2·`requirement_cards`·`resolve_card_pages`·상수/규칙 hash |
| web/backend/app/deep_review/models.py | 수정 | `RequirementInventoryItem.source|card`, `DocumentSegment.page_anchor_block_keys` |
| web/backend/alembic/versions/<new>_requirement_card_columns.py | 신규 | 열 3개 추가(기본값·NULL), `_record_migration_marker()`, downgrade |
| web/backend/app/deep_review/contracts/bidops.document-segments.v1.json | 수정 | enum·`inventory_summary` 키 |
| web/backend/app/deep_review/schemas/document_bundles.py | 수정 | `TaxonomyLabel`·`SegmentMappingStatus`·summary 키 |
| web/backend/app/deep_review/cli/rebuild_segment_manifests.py, cli/__init__.py | 신규/수정 | backfill CLI(analysis-worker 자리) |
| web/backend/app/deep_review/services/document_bundles.py | 수정 | `_load_structure_payload`를 모듈 함수 `load_structure_payload`로 승격(동작 동일) |
| web/backend/tests/deep_review/test_document_segments.py | 수정 | T1~T6, T8, T9 |
| web/backend/tests/deep_review/test_document_segments_postgres.py | 신규 | T7, T10(`requires_postgres`) |
| web/backend/tests/app/test_document_bundles.py | 수정 | taxonomy_version 리터럴(T9) |
| web/frontend/src/components/deep-review/types.ts, SegmentInventoryPanel.tsx | 수정 | T12 |
| scripts/hp-card-inventory-check.py | 신규 | T11 |
| docs/contracts.md, docs/deep-review-erd.md, docs/ARCHITECTURE.md | 수정 | enum·키·열·한 줄 |
| docs/validation-runs/<날짜>-hp/HP-01/README.md | 신규 | 변환 명령·sha256·T11 결과 |

## 작업 순서

1. STEP-001 카드 표 판정·파서·경계 [complex]
   - 목표: 카드 표를 열 제목 탐지에서 제외하고 경계로 삼으며 라벨·값 카드를 inventory 항목(anchor 포함)으로 만든다. 카드 prefix는 문단 후보를 확정하지 않는다. segment anchor는 `segment_anchors` 평행 목록으로 운반한다.
   - 작업 대상: document_segments.py(`_collect_cards`, `_table_columns` 제외, `_boundaries`, `_build_inventory`, 상수·`_RULES`), test_document_segments.py.
   - 검증: T1, T2, T3, T4, T8.
2. STEP-002 저장 열·계약 스키마·pydantic [complex]
   - 목표: 새 열과 enum·키가 저장 검증·wire 검증·응답 모델을 통과한다(STEP-001과 같은 묶음에서 끝낸다).
   - 작업 대상: models.py, migration, contracts JSON, schemas/document_bundles.py, `store_manifest`/`wire_payload`, test_document_bundles.py 리터럴.
   - 검증: T9; T7의 migration·저장 부분(PG).
3. STEP-003 쪽 계산과 조회 함수 [standard]
   - 목표: segment anchor 저장과 `inherited` 계산, `requirement_cards`·`resolve_card_pages`.
   - 작업 대상: `_segment_pages`, `read_manifest_view`, `segments_view`, `requirement_cards`, `resolve_card_pages`.
   - 검증: T5; T7의 조회 부분(PG).
4. STEP-004 taxonomy v2 [standard]
   - 목표: category·접두사·키워드 매핑과 카드 label 우선 규칙.
   - 작업 대상: `_category_labels`, `_PREFIX_TAXONOMY`, `_TAXONOMY_KEYWORDS`, label 계산.
   - 검증: T6.
5. STEP-005 backfill CLI [complex]
   - 목표: 옛 구조에 현재 identity manifest를 멱등하게 만든다(analysis-worker 이미지·worker 역할에서 실행, `load_structure_payload` 승격, savepoint·errors).
   - 작업 대상: cli/rebuild_segment_manifests.py, cli/__init__.py, document_bundles.py(helper 승격), PG 테스트.
   - 검증: T10(PG).
6. STEP-006 프런트 타입·라벨 [standard]
   - 목표: 타입이 계약과 같고 패널이 새 label·상속 주석을 보인다.
   - 작업 대상: types.ts, SegmentInventoryPanel.tsx.
   - 검증: T12(`npm run build`, typecheck, 해당 패널 spec이 있으면 실행).
7. STEP-007 증거 스크립트와 문서 [standard]
   - 목표: 실제 변환 결과 5건 수치를 기록하고 contracts/erd/ARCHITECTURE를 갱신한다.
   - 작업 대상: scripts/hp-card-inventory-check.py, docs/contracts.md, docs/deep-review-erd.md, docs/ARCHITECTURE.md, validation-runs README.
   - 검증: T11, `python3 scripts/feature_status.py doctor _`.

## 위임

| 단계 | 작업량(S/M/L) | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 표 경계·우선순위·중복 ID 불변식 |
| STEP-002 | M | 높음 | complex | migration·append-only·세 계층 검증 일치 |
| STEP-003 | S | 중간 | standard | 규칙이 닫혔고 `_segment_pages` 패턴 존재 |
| STEP-004 | S | 낮음 | standard | 표 매핑과 상수 |
| STEP-005 | M | 높음 | complex | 객체 저장소 hash 검증·멱등·역할 경계 |
| STEP-006 | S | 낮음 | standard | 타입·문구 |
| STEP-007 | S | 낮음 | standard | 스크립트·문서 |

## 검사 명령과 증거

```sh
cd web/backend
python -m pytest tests/deep_review/test_document_segments.py tests/app/test_document_bundles.py -q
# PostgreSQL 변형: 일회용 postgres:17.11, BIDOPS_TEST_POSTGRES_URL, BIDOPS_PRESPEC_OVERVIEW_ENABLED=false
python -m pytest tests/deep_review/test_document_segments_postgres.py -q
alembic heads   # 단일 head
cd ../frontend && npm run build
PYTHONPATH=web/backend python3 scripts/hp-card-inventory-check.py --dir <변환 결과 디렉터리> --out docs/validation-runs/<날짜>-hp/HP-01/cards.json
python3 scripts/feature_status.py doctor _
```

변환 결과 5건은 격리 document worker에서 `/Users/temp/orca/fixtures/RFP/`의 HWP/HWPX를 `process_document(..., prepare_pdf=True)`로 만든다(README에 `docker exec` 명령과 산출 sha256 기록). 저장소에 공고 원문·구조 JSON을 커밋하지 않는다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 저장 검증·pydantic·JSON 스키마 중 하나만 올려 manifest가 조용히 안 생김 | `ensure_manifest` 뒤 manifest 없음, 로그 경고 | STEP-001·002를 한 묶음으로, T9를 먼저 실패시킨 뒤 통과 |
| 라벨 변형이 fixture 밖 공고에서 더 많음 | 실제 수집 문서에서 `card_item_count=0` | 사전은 규칙 hash에 포함; 새 변형은 새 extractor 버전 |
| anchor 문단이 다른 쪽에 있음(표 앞 긴 빈 문단·그림) | 상속 쪽이 PDF 쪽과 다름 | T11 결과를 PDF 렌더로 표본 확인(문서당 2장), 틀리면 anchor 개수·규칙 조정 뒤 새 버전 |
| 옛 구조가 404로 보임 | 업그레이드 뒤 `/segments` 404 | backfill CLI 실행(사용자 확인), README에 대상 수 기록 |
| migration이 append-only 규칙과 충돌 | 기존 행 UPDATE | 열 추가만, 기본값으로 채움, downgrade는 열 제거 |

## 증명

- docs: HP 공통 계약 §3·contracts.md·erd·intent/spec/plan 일치, `doctor _`, diff.
- tests: T1~T6·T8·T9 pytest 로그(exit code).
- postgres: T7·T10 로그(`BIDOPS_TEST_POSTGRES_URL`), `alembic heads` 단일.
- frontend: T12 build·typecheck 로그.
- api_guard: N/A — 외부 호출·회사 자원 접근 변경 없음(backfill CLI는 내부 저장소만 읽는다).
- real_data_run: N/A — 모델 실행 없음(T11은 tests 증거에 포함).

## 결과

STEP-001~007 구현과 직접 영향 검사를 완료했다. 세부 명령·초기 실패·수정 후 증거는 `docs/work/_runs/hp0001-20261014/hp01-*.log`와 단계 결과 파일에 있다. 단위·PostgreSQL migration/CLI 실제 subprocess·타입/build·1280/1440 화면 의미/구조를 검증했다. 초기 PG 저장 테스트는 카드가 아닌 앞 문단 segment를 골랐고 정확한 segment ID로 수정했다. Linux `/proc` 전용 변환 검사는 macOS에서 실패했으나 동일 소스를 Linux 이미지에서 통과했다. MinIO 전용 기존 fixture 1건은 준비되지 않아 skip했으며 실제 객체 읽기는 격리 backfill·API에서 별도 검증했다.

T11 실제 5건 카드 수는 목표 198장과 일치한다. 쪽은 직접0/상속88/미확인110으로 198/198 목표 미달이다. 가까운 3개 anchor 규칙을 바꾸거나 미확인을 추정으로 채우지 않았다. PDF10표본은 상속6건 위치일치·미확인4건; school13쪽의 다른 카드 텍스트 겹침은 findings에 남겼다. 입력/변환 hash·출력은 validation README와 run 증거에 연결했다.

2026-10-15 KST 사용자 일괄 승인으로 bidops-local 전체 DB·객체164버전을 백업한 뒤0037 migration, notice79의 기존구조1건 backfill·멱등재실행·앱이미지교체·실제 REST200을 확인했다. 기존행 변경0, 새manifest1/segment105/card35. 기본 홈페이지 사전규격4건 중 나머지3건은 구조없음. 원문·프로필·정책은 보존됐고 추가모델호출은 없다. 자세한 증거는 `hp01-deployment.md`; 독립 최종 리뷰와 배치 통합 기록은 loop 결과에서 관리한다.
