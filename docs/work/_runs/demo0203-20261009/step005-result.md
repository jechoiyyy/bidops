# STEP-005 결과

- 2026-10-09 Codex 리더가 사용량 한도로 멈춘 뒤 Claude Code 리더가 이어서 진행했다. 지정 complex 구현자(`sdlc:implementer-opus`)가 구현하고 리더가 diff·검사를 직접 확인했다.
- 구현: 공통 계약 §4의 `GET /api/companies/{company_id}/profile`, `/knowledge-graph`, `/profile-evidence/{evidence_id}`. deep_review router(`company_knowledge_router`)가 제공하고 strict DTO(`schemas/company_knowledge.py`)로 직렬화한다. 조회 service는 쓰기·잠금·원본 bytes 읽기가 없고 `validate_profile_snapshot`(원본 재읽기 없음)으로 동결 계보를 검증한 뒤에만 응답한다.
- 버전 해석: graph_version_id 생략 시 binding, binding 없으면 409 `company_profile_not_ready`. 지정 시 같은 회사 graph만 허용하고 없거나 타회사면 404 `not_found`. 계보·hash·identity 불일치는 보정하지 않고 500 `processing_failed`.
- 그래프: 양방향 BFS(방문 노드 재삽입 없음), depth 1..3(기본 2)·limit 1..500(기본 200), (거리,id) 정렬 후 절단, 양끝이 남은 edge만, omitted_node_count=depth 내 도달 수−반환 수. 공개형에는 source_refs·json_pointer·object key가 없다. evidence 노드·관계는 재사용한 사실 source ref의 ProfileEvidence id, unknown은 빈 배열.
- 근거: 회사 소속 v2 profile의 evidence만 반환하며 legacy NULL·타회사 evidence는 404.
- 경계: `BIDOPS_DEMO_ENABLED=false`이면 기존 demo guard가 세 경로를 검증 전에 404로 막는다. `boundary_map`의 lifecycle 공개 표면에 `schemas/companies.py`(CompanyDTO 재사용, 계약 §8)를 추가했다. 새 오류 code `company_profile_not_ready`를 router 허용 목록과 `web/frontend/src/lib/apiErrors.ts`에 함께 등록했다.
- 리더 red: `step005-before.log` 20 failed/2 passed/skip0, exit1(2개는 기존 demo guard가 이미 만족하는 404 검사). 기록 당시 경로는 `tests/deep_review/test_company_knowledge_api.py`였고, deep_review 테스트가 `app.main`을 import할 수 없다는 모듈 경계 검사에 따라 조립 통합 위치인 `tests/app/test_company_knowledge_api.py`로 옮겼다.
- 리더 green: `step005-leader.log` 232 passed, skip0, exit0. 일회용 postgres:17.11(harness `temporary_postgres_server`)과 SQLite 두 변형. 구현자 실행 `step005-tests.log`(189 passed)·`step005-route-assembly.log`(43 passed)는 같은 소스의 보조 기록이다.
- 한계: 프런트 `apiErrors.ts` 변경의 production build는 기능 마무리 frontend proof에서 Node 22 Docker로 확인한다. 소스 hash는 `step005-source-hashes.json`. 실제 회사 원본 DB 등록·실행 중 스택·모델 호출은 없다.
