# STEP-001 결과

- 구현: 순수 온톨로지·합성회사 원본 validator, raw/canonical SHA-256, JSON Pointer 인용 대조, 결정적 graph snapshot, aliases-only revision 판정.
- 독립 검토 수정: 회사 identity를 lifecycle 등록과 같은 공용 순수 규칙으로 통일하고, 비문자 enum 입력을 안전 오류로 닫았으며, snapshot 전에 raw bytes 재검증·전체 정합성 대조를 추가했다.
- 범위: `app/core/company_ontology.py`, 합성 단위 fixture, 공용 identity helper를 소비하는 `app/lifecycle/services/company_context.py`. DB·CLI·API wire·실제 회사 원본·후보 공고·모델 호출은 다루지 않음.
- 실패 우선 증거: `step001-before.log` — 제품 모듈 부재로 collection 실패.
- 최초 검증 명령: `/tmp/bidops-demo00-verify-venv/bin/python -m pytest tests/core/test_company_ontology.py tests/app/test_module_boundaries.py -q`; `step001-tests.log`, exit 0, skip 0, 60 passed, 3.87s.
- 수정 검증 명령: `/tmp/bidops-demo00-verify-venv/bin/python -m pytest tests/core/test_company_ontology.py tests/app/test_module_boundaries.py tests/app/test_company_context.py::test_register_company_is_flush_only_idempotent_and_identity_checked[sqlite] -q`; `step001-review-fixes.log`, exit 0, skip 0, 77 passed, 4.98s.
- 소스 결속: 초기 독립 검토 입력은 `step001-source-hashes.json`에 보존했다. 수정 검증 대상 3개 파일의 SHA-256은 `step001-fixed-source-hashes.json`이며, 이후 한 파일이라도 바뀌면 위 수정 검증·리뷰 증거는 stale이다.
- 다음 소비 경계: `parse_ontology`, `parse_company_knowledge_source`, `build_graph_snapshot`, `validate_alias_only_revision`.
