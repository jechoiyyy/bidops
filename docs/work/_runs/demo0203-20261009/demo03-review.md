# DEMO-03 독립 최종 리뷰 (2026-10-10)

- 리뷰어: 구현에 관여하지 않은 general-purpose 에이전트(읽기 전용). 대상: 기준 0d980bd → 현재 미커밋 전체 변경(tracked diff + 신규 파일, `_runs/` 제외). 기준 문서: 공통 계약 §5·§6·§8·§9·§10, DEMO-03 intent/spec/plan(T1~T8; T9는 범위 밖), 프로젝트 제약, CLAUDE.md 강제 게이트, 모듈 경계. 단계별 결과 파일의 리더 수용 결정은 "계약과 모순될 때만 지적" 기준.
- 판정: **PASS_WITH_NOTES, 차단 0.**
- 적합 확인: 회사 격리(모든 쓰기/읽기 company 필터·타회사 404, legacy 경로의 회사 행 거부·NULL 동작 불변), 외부 호출 gate(worker의 policy-scope·`approved_company_input`·audit·pinned bundle 재분할 검사, 호출 0 테스트, demo 정책 전역 활성 거부, 핏의 명시 정책 ID만), 불변성(0036 trigger/CHECK/guard·ORM 불변·GRANT 없음·권한 최소), 계약 DTO/코드/gate 순서/replay/nonce/FrozenProvenance/비교 규칙/경로 정렬·상한·coverage/slice coverage, fail-closed(미검증 결과를 결정으로 바꾸지 않음), 경계(lifecycle 공개 export만, 역방향 import 없음, 테스트 약화 없음, fake Luna가 실제 wire 계약 구현).

## 노트와 처리

| # | 내용 | 처리 |
|---|---|---|
| N1 | `sanitize_for_prompt`가 토큰 `path` 키를 제거해 `coverage.excluded_path_count_by_requirement`(핏)·`company_coverage.excluded_path_count_by_requirement`(심층 stage2)는 모델에 전달되지 않는데 프롬프트 규칙이 coverage를 언급 | STEP-004 리더 결정(provenance 전용)과 일치. `excluded_fact_keys`·`unmapped_requirement_ids`는 전달됨. contracts DEMO 절에 "sanitizer 제거, 저장·hash 전용" 기록 완료. core sanitizer whitelist는 모든 프롬프트에 영향하므로 범위 밖 → backlog(DEMO-05 전 결정) |
| N2 | 엔진 민감한 nulls last·tie-break 정렬 단언이 SQLite에서만 실행(`test_company_reads.py` ~408·495·556) | **수용·수정 완료**: 정렬·비교 테스트 3개를 `engine` 파라미터화(PG 변형 5→8). 제품 코드 변경 없음(`company_notices.py` hash 불변). PG 변형이 처음 적발한 1건은 fixture가 queued→completed로 바로 가서 0036 상태 전이 guard에 걸린 테스트 helper 오류였고 running 경유로 수정. `.nulls_last()` 제거 변이 실험에서 SQLite는 `posted_at_desc`를 못 잡고 PG가 잡음(`demo03-step005-n2-mutation.log`). 구현자 27 passed/0 skipped(`demo03-step005-n2-tests.log`), 리더 reads+e2e 50 passed/0 skipped PG(`demo03-step005-n2-leader.log`), hash 일치(`demo03-step005-n2-source-hashes.json`, step005 hash 파일의 `test_company_reads.py` 항목을 대체) |
| N3 | `CompanyScopedFitView.model_revision: str|None`은 §9 "nullable은 기존 DTO를 따른다"의 문자적 예외 | STEP-002 CHECK 완화·FrozenProvenance `model_revision:string?`에 따른 필요 결정. contracts DEMO 절에 nullable 명시 완료. DEMO-04/05는 non-null 가정 금지 |
| N4 | 핏 DTO가 `provenance.bundle_id is None` 강제 | 계약 §9/§10과 일치(핏 bundle null). 결합 주석 수준 → 기록 |
| N5 | 한 attempt의 provenance 불일치가 `/company-fit` 목록 전체를 `processing_failed`로 | §10 "보정하지 않고 processing_failed" 준수. DEMO-05 verifier 기대에 기록 |
| N6 | 회사 라우터가 예외를 code 수준 로그 없이 삼킴 | 비차단 하드닝 → backlog |
| N7 | `_check_delivery`가 비정수 `company_part_count`에 `TypeError`(여전히 fail-closed, code만 다름); coverage 내용 미검증 | backlog |
| N8 | `tracking_status=미선택` 필터는 opportunity 미연결 공고를 제외 | STEP-005 결정(tracking=null) 기록. DEMO-04 인지 필요 |
| N9 | requirement id 정렬이 문자열 순(`…:10` < `…:2`) | 결정적·계약 "오름차순" 충족. 기록 |
| N10 | enqueue CLI의 actor 오류가 `company_input_invalid` | STEP-002 docstring 기록. 이 문서에 추가 기록 |
| N11 | 핏 정책 파일이 pydantic schema 출력에 고정 → pydantic 업그레이드 시 `policy_invalid` | fail-closed. operations 주의사항 backlog |
| N12 | 현재 관계 집합에서 3 hop은 2 edge가 최대라 hop 상한·재방문 금지가 데이터로 검사되지 않음 | 계약 충족, 테스트가 인지. 기록 |
| N13 | 최신 fit/review 선택이 전체 행 로드 후 Python dedupe(1 query) | 데모 규모 적합. 운영 전환 시 `DISTINCT ON` backlog |
| N14 | legacy 경로의 회사 행 거부 code가 혼합(`preview_changed`/`approval_invalid`/`not_found`) | STEP-003 결정 기록. 균일 `not_found` 선호는 backlog |
