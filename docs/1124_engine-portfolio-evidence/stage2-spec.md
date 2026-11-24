# 2단계 구현 지시서 — 업무 근거 지도로 근거 연결과 `수행 기록 없음` 판정 (2026-11-24)

먼저 읽을 것: `AGENTS.md`, `docs/standards.md`, `docs/engineering-notes.md`, `docs/1124_engine-portfolio-evidence/design.md`(배경·1단계·2단계 설계), `packages/bid-deep-engine/UPSTREAM.json`과 `engine_tests/test_manifest.py`(원본 대비 차이 기록 규칙), `packages/bid-deep-engine/src/bid_deep_engine/wiki_tools.py`(`INGEST_PROMPT_HEAD`, `taxonomy_text`, `validate_mapping`, `build_repair_prompt`), `analysis/pipeline.py`(`_NoticeRun.knowledge_for`, `match`, `synth`), `analysis/prompts/match.md`, `company/knowledge.py`(1단계 발췌가 이미 들어 있다), `runner.py`(`MockTransport`), `scripts/engine-eval.py`(평가 도구).

사용자 결정(2026-11-24): 위키 실적 목록을 회사 수행 기록의 전부로 본다. 업무 근거 지도 기준 "기록 없음"은 `GAP`(수행 기록 없음)이다. 지도 범위는 **(b)** — 판정 근거에 "지도에 있는 실적 n건 기준"을 밝힌다.

## 1. 업무 근거 지도 읽기 — 새 모듈 `analysis/workunits.py` (authored)

엔진 입력 묶음에는 `.md` 페이지만 들어온다(`work-units.json`은 없다). 지식 트리의 업무 근거 페이지(`kind: capability`, slug가 `work-`로 시작하고 `work-units`가 아닌 것)에서 지도를 복원한다. 페이지 형식(실제 예: `company-bundle/rootlab/capabilities/work-performance.md`):

```
## 범위
- <주제 범위 문장>
- 전체 지도: [[work-units]]
## 업무 단위별 근거
### <단위 제목>
- 단위 id: `<topic>.<unit>`
- 범위: <covers 문장>[ 다른 단위: <not 문장>]
- [[P2020-01]] SFR-003
- [[P2021-02]] SFR-003, PER-001, DAR-001
```

- `parse_work_unit_map(knowledge) -> WorkUnitMap | None`: 주제(slug·제목·범위), 단위(id·제목·범위), 근거(`(project, req_id)` 목록)를 결정적으로 읽는다. 업무 근거 페이지가 하나도 없으면 `None`.
- **근거는 지식 트리에 portfolio 페이지가 있는 실적만 남긴다.** 평가 입력은 공고 연도 이후 실적 페이지를 빼지만 업무 근거 페이지 본문은 그대로라 빠진 실적을 가리키는 줄이 남는다(누수). 남은 실적 수를 `basis_projects`로 둔다.
- 근거가 모두 걸러진 단위는 "근거 없음 단위"로 남긴다(분류에는 쓰되 그 단위만으로는 FULL 근거가 되지 않는다).
- 분류표 텍스트는 `wiki_tools.taxonomy_text`와 같은 모양으로 만든다(주제 줄 + `- id | 제목 | 범위`).

## 2. 공고 요구사항 분류 호출 (모델 1회 + 수정 1회 상한)

- 출력 모델 `WorkUnitAssignmentsOut`: `{"assignments": [{"req_id": str, "units": [str], "uncovered": [str]}]}`. `uncovered`는 그 요구사항에서 어느 단위에도 들지 않는 업무를 짧은 구절로(없으면 빈 배열).
- 지시문은 `wiki_tools.INGEST_PROMPT_HEAD`의 분류 기준 1~4를 그대로 쓰고, 5번(새 단위 제안) 대신 "어느 단위에도 맞지 않는 업무는 `uncovered`에 짧은 구절로 적는다. 새 단위를 만들지 않는다. 실무자가 같은 일이라고 부를 기존 단위가 있으면 그것을 고른다."로 바꾼다. 하드웨어 규칙(4번)도 유지. 대상은 이 공고의 요구사항이다(과거 수주 사업이 아니다). 새 프롬프트 파일 `analysis/prompts/units.md`에 두고 `prompt_bytes`·`prompt_set_hash` 체계에 넣는다.
- 입력: 분류표 + 공고 요구사항(`id`, `name`, `definition`, `details` 앞 1,500자).
- 호출: `self.client.parse(WorkUnitAssignmentsOut, purpose="units", system=..., document=..., instruction=..., slug=...)` — 다른 pass와 같은 인터페이스. 호출 기록은 `self.calls`에 넣는다.
- 검사: 요구사항 id 목록이 공고 순서대로 정확히 한 번씩, 단위 id는 지도에 있는 것만. 실패하면 `wiki_tools.build_repair_prompt`와 같은 방식으로 1회 수정 요청. 그래도 실패하거나 호출이 실패(`LlmCallError`·`LlmOutputError`·`LlmTruncated`·`LlmRefusal`)하면 **분류 없이 진행**(fail closed: 1단계 동작 그대로, GAP을 만들지 않는다)하고 경고 `units: classification unavailable: <안전한 사유 코드>`를 남긴다. 과금된 호출 기록은 남긴다.
- 요구사항이 0건이거나 지도가 `None`이면 호출하지 않는다.

## 3. 결정적 연결 — 관련 실적·발췌를 지도로 정한다

- 분류가 있으면 관련 실적 = 이 공고 요구사항이 가리킨 단위들의 근거 실적을, 서로 다른 `(요구사항, 단위)` 근거 수 내림차순(동점은 slug)으로 상위 `PORTFOLIO_TOP_K`. 단어 겹침 순위(`relevant_portfolio`)를 대신한다.
- 발췌 = 그 실적의 근거 `req_id`가 목록에서 `- <REQ_ID> `로 시작하는 줄. 상한은 1단계 `PORTFOLIO_EXCERPT_CHARS`, 넘치면 근거 수가 많은 줄부터. 발췌 안내 문장은 "원문 목록 N줄 가운데 업무 근거 지도가 이번 공고와 연결한 n줄만 옮겼다. 옮기지 않은 줄도 수행한 범위다."
- `company/knowledge.py`의 `select_pages`에 `related_override: list[str] | None`, `excerpt_override: dict[str, list[int]] | None`를 더해 위 결과를 받는다. 없으면 1단계 그대로.
- `_NoticeRun.knowledge_for`: 분류 → 연결 → 선택 순으로 공고당 한 번 계산하고 match·synth가 같은 값을 쓴다.

## 4. 매칭 입력과 판정 규칙

- 프롬프트용 회사 근거 텍스트 끝에 절을 붙인다:

```
## 요구사항별 업무 근거(업무 근거 지도, 실적 <basis_projects>건 기준)
- SFR-001: <단위 제목>(<단위 id>) ← [[P2023-07]] SFR-012, [[P2020-01]] DAR-002 / 단위에 들지 않는 부분: <uncovered…>
- SFR-002: 어느 업무 단위에도 해당하지 않음 — <uncovered…>
```

- `analysis/prompts/match.md`에 규칙을 더한다(이 절이 있을 때만 적용, 없으면 지금 규칙 그대로):
  - 요구사항의 모든 업무가 단위에 들고 단위마다 근거 실적이 있으면 `FULL`. 근거 실적이 여러 건이면 합쳐 판단하고 모두 `evidence_portfolio_ids`에 넣고 rationale에 [[실적 ID]]로 적는다. 세부 차이(수치·기간·도구·서식)는 낮추는 이유가 아니다.
  - 일부 업무만 단위에 들면(`단위에 들지 않는 부분` 있음) `PARTIAL`, `gap_action`은 그 부분.
  - "어느 업무 단위에도 해당하지 않음"이면 `GAP`. rationale은 "업무 근거 지도(실적 n건 기준)의 어느 업무 단위에도 해당하는 수행 기록이 없다"로 시작하고 해당 없는 업무를 적는다.
  - 근거 없음 단위만 있으면 `UNKNOWN`.
  - 하드웨어 범위 규칙, 상주·자격 규칙, 프로필 `unknown` 규칙은 지금과 같다(지도 규칙이 프로필 부정값 GAP을 막지 않는다).
- 결정적 검증: 판정이 `GAP`인데 지도 절이 그 요구사항을 "해당하지 않음"으로 표시하지 않았고 프로필 부정값 근거도 없으면 경고 `match: gap without work-unit or profile basis (<req_id>)`를 남긴다(자동 보정하지 않는다).

## 5. 산출물·계약

- `Analysis`에 선택 필드 `work_units: WorkUnitSummary | None = None`: `{"basis_projects": int, "status": "classified"|"unavailable", "reason": str|None, "assignments": [{"req_id","units","uncovered","evidence_projects"}]}`. None이면 JSON에 쓰지 않는다(1단계 `portfolio_excerpts`와 같은 방식, `engineering-notes.md` "선택 필드를 계약 모델에 더하면…" 참고). 계약 테스트(`test_analysis_schemas.py`, 필드 순서 테스트)는 의도한 확장만 반영해 갱신한다.
- 단계 스탬프: `fits` 단계 입력에 `"work_units": <분류 출력 정규화 해시 또는 null>`을 더한다. 프롬프트 해시에 `units.md` 포함.
- `MockTransport.parse`: `purpose == "units"`면 `assignments=[]`을 돌려준다 → 검사 실패 → 분류 없이 진행(모의 실행이 GAP을 만들지 않음을 테스트로 고정).
- `scripts/engine-eval.py`: `plan`이 지도가 있는 입력에서 호출 수를 4(+수정 1)로 보이게 한다. `PASSES`·승인 규칙은 그대로.
- `UPSTREAM.json`: 새 파일은 `authored_files`(sha256), 바뀐 원본 파일은 `local_replacements`로 기록하고 `notes`에 한 문장. `test_manifest.py` 통과.

## 6. 테스트 (엔진 `engine_tests/`에 추가)

- 지도 파싱: 실제 형식 fixture로 주제·단위·근거, 빠진 실적 근거 제거, 근거 없음 단위, 지도 없음 → None.
- 분류 검사: id 누락·순서·미지 단위 → 수정 요청 1회 → 실패 시 unavailable·경고·GAP 없음.
- 연결: 관련 실적 순위(근거 수·동점 slug), 발췌가 근거 `req_id` 줄만, 상한.
- 프롬프트 절 렌더링(해당 없음·부분·여러 실적).
- 파이프라인: 가짜 client로 units→match→synth 순서, 호출 기록, 스탬프 입력, `analysis.json`의 `work_units`, mock 실행 GAP 0.
- 실행: `docker run --rm --platform linux/amd64 --network none -v <repo>:/repo -w /repo -e BIDOPS_PRESPEC_OVERVIEW_ENABLED=false -e BIDOPS_DATABASE_URL=sqlite:// -e PYTHONPATH=/repo/web/backend:/repo/packages/bid-deep-engine/src -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python bidops:prespec-redesign-20261124 -m pytest -q -p no:cacheprovider packages/bid-deep-engine/engine_tests web/backend/tests/deep_review/test_engine_runs.py` (sandbox에서 docker가 막히면 host `uv run --python 3.12 --with pydantic --with PyYAML --with pytest`로 `packages/bid-deep-engine/engine_tests`만, PYTHONPATH는 `packages/bid-deep-engine/src`).

## 7. 하지 않을 것

- 모델 실호출(live) 금지. 평가 실행·승인 파일 생성 금지.
- 위키 파일·`work-units.json`·회사 근거 화면·`wiki_tools` 동작 변경 금지.
- 프런트엔드 변경 금지(화면 라벨은 별도 작업).
- commit 금지.
