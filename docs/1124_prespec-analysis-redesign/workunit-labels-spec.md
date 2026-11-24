# 분석 화면: 2단계 엔진(업무 근거 지도) 결과 표시 — 구현 지시서 (2026-11-25)

먼저 읽을 것: `AGENTS.md`, `docs/standards.md`, `web/frontend/AGENTS.md`, `docs/1124_prespec-analysis-redesign/design.md`(분석 화면 설계), `docs/1124_engine-portfolio-evidence/design.md`·`stage2-spec.md`(엔진 2단계), 엔진 산출물 모델 `packages/bid-deep-engine/src/bid_deep_engine/analysis/schemas.py`(`Analysis.work_units`, `WorkUnitSummary`)와 `company/knowledge.py`(`KnowledgeSelection.portfolio_excerpts`).

## 배경
엔진이 공고 요구사항을 업무 근거 지도로 분류하고(`analysis.work_units`), 어느 업무 단위에도 들지 않는 요구사항은 `GAP`(수행 기록 없음, 지도 실적 n건 기준)으로 판정한다. 프로필 부정값(예: 상주 지역)으로 나온 `GAP`도 여전히 있다. 화면은 두 `GAP`과 `UNKNOWN`을 구분해 말해야 한다. 값은 응답에 있는 것만 쓰고 지어내지 않는다.

## 데이터
- `engineApi.ts`의 `EngineAnalysis`에 선택 필드 추가: `work_units?: { basis_projects: number; status: "classified" | "unavailable"; reason: string | null; assignments: { req_id: string; units: string[]; uncovered: string[]; evidence_projects: string[] }[] } | null`, `knowledge.portfolio_excerpts?: Record<string, number[]>`. 실제 응답 모양은 schemas.py에서 확인하고 다르면 그쪽을 따른다. 옛 응답(필드 없음)도 그대로 그린다.
- 요구사항 행과 `work_units.assignments`는 `req_id`로 잇는다(같은 번호가 여러 번이면 순서대로, 못 이으면 연결 없음으로 둔다).

## 표시 규칙
1. 대응 표식(목록·상세·필터 칩)은 지금처럼 짧게(`부족`·`미확인`…) 둔다. 상세의 대응 표식 옆과 목록 행의 `title`에 뜻을 붙인다:
   - `GAP`이고 연결된 행이 `units` 비어 있음 ∧ `uncovered` 있음: `수행 기록 없음 · 업무 근거 지도 실적 {basis_projects}건 기준`.
   - 그 밖의 `GAP`: `회사 정보에서 확인된 제약`.
   - `UNKNOWN`: `판단 자료 없음`.
2. 요구사항 상세에 `업무 근거` 블록(work_units가 `classified`일 때): 분류된 업무 단위 id 목록, 근거 실적(이름은 기존 회사 근거 실적 이름 변환을 그대로 쓰고 코드는 보조 표기), `단위에 들지 않는 부분`(`uncovered`). 행이 없으면 블록을 그리지 않는다.
3. 요구사항 구역의 회사 근거 안내 문장:
   - `work_units.status === "classified"`: "요구사항마다 업무 근거 지도(실적 {basis_projects}건 기준)로 근거 실적을 연결했어요. 지도에 없는 실적은 판단에 들어가지 않았어요."
   - 그 밖에 `knowledge.skipped`가 0건: "회사 근거 위키 {n}쪽과 관련 실적 {m}건을 읽었어요. ‘회사 근거 없음’이 실적이 없다는 뜻은 아니에요."(m = 읽은 실적 페이지 수)
   - `knowledge.skipped` 1건 이상: 지금 문장 그대로(빠진 페이지 이름).
   - "0쪽은 분석 분량 제한으로 빠졌어요" 같은 문장을 만들지 않는다.
4. 원문·처리 정보에 항목 `업무 근거 지도`: classified면 "요구사항 {k}건을 업무 단위로 분류했어요(지도 실적 {basis_projects}건 기준). 어느 단위에도 들지 않은 요구사항 {g}건은 ‘수행 기록 없음’으로 판정될 수 있어요."; unavailable이면 "분류하지 못했어요({reason 코드 그대로}). 이 분석의 ‘부족’은 회사 정보에서 확인된 제약에서만 나와요."; 필드가 없으면 항목을 그리지 않는다. `엔진이 본 회사 자료` 문장도 3번과 같은 규칙으로 0쪽 문장을 만들지 않는다.
5. 해요체, 색만으로 구분하지 않는다, 테마 토큰만 쓴다(기존 규칙).

## 검사
- `npm run build`, `BIDOPS_PORTFOLIO_ANALYSIS=1 npm run build -- --outDir dist-portfolio`.
- `tests/fixtures/engine-analysis.ts`에 work_units 있는 변형을 더하고 `tests/prespec-analysis-view.spec.ts`에 위 1~4 검사를 추가(옛 응답 변형도 유지). Playwright는 sandbox에서 Chromium이 뜨지 않으면 돌리지 말고 그 사실을 보고한다(리더가 돌린다).
- commit하지 않는다. 엔진·백엔드 파일은 바꾸지 않는다.
