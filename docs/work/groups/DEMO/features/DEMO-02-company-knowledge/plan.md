# 온톨로지와 가상회사 지식그래프 — plan

- 기능 ID: `DEMO-02-company-knowledge`
- 작성일: 2026-10-06
- 근거: [intent](intent.md), [spec](spec.md)

## 변경 파일

경로는 저장소 루트 기준. `<next>` migration은 구현 시 실제 단일 head의 후속 번호로 생성한다.
번호를 선점하지 않으며 core/db.py의 runtime head와 `scripts/runtime-privileges.sql` 권한을 함께 갱신한다(migration에 GRANT를 쓰지 않는다).
기준은 별도 데모 브랜치와 `bidops-local` 격리 자원이다. main이나 운영에 반영하지 않는다.

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/core/company_ontology.py | 신규 | 순수 타입/관계 검증 |
| web/backend/tests/core/test_company_ontology.py | 신규 | STEP-001 순수 온톨로지·원본 계약 T1·T2·T8 |
| web/backend/app/deep_review/models.py | 수정 | graph/version/binding |
| web/backend/app/deep_review/services/company_knowledge.py | 신규 | 등록·projection·활성화·조회 |
| web/backend/app/deep_review/services/input_versions.py | 수정 | profile v2·v1 호환 |
| web/backend/app/deep_review/cli/company_knowledge.py | 신규 | dry-run/import/activate |
| web/backend/app/deep_review/cli/__init__.py | 수정 | 명령 조립 |
| web/backend/app/deep_review/routers/company_knowledge.py | 신규 | 읽기 API |
| web/backend/app/deep_review/schemas/company_knowledge.py | 신규 | DTO |
| web/backend/app/main.py | 수정 | router 등록 |
| web/backend/alembic/versions/0035_company_knowledge.py | 신규 | 테이블·FK·head·감사 marker(권한은 runtime-privileges.sql) |
| web/backend/alembic/versions/0001_lean_v1_postgresql.py | 수정 | historical metadata에서 신규 location 복합 unique 제외 |
| web/backend/app/lifecycle/services/company_context.py | 수정 | STEP-001과 회사 identity 검증 공유 |
| web/backend/tests/app/{boundary_map,test_db_migrations,test_deep_review_migrations,test_mapper_isolation,test_models,test_module_cli_entrypoints}.py | 수정 | 신규 테이블·head·CLI 폐쇄 목록 정합 |
| docs/demo-fixtures/ontology.v1.json | 신규 | concept/alias/관계 |
| docs/demo-fixtures/companies/*.v1.json | 신규 | 순수 합성회사 자료 3개 |
| web/backend/tests/deep_review/test_company_knowledge.py | 신규 | 등록·검증·API |
| web/backend/tests/app/test_company_knowledge_cli.py | 신규 | 새 프로세스 CLI/PG |
| web/backend/app/deep_review/__init__.py | 수정 | 공개 등록/조회 facade |
| web/backend/app/core/db.py | 수정 | runtime head |
| .dockerignore | 수정 | 합성 원본 docs/demo-fixtures를 이미지 빌드 context에서 제외 |
| scripts/runtime-privileges.sql | 수정 | graph/version/source/binding 테이블 권한 |
| web/backend/tests/app/test_runtime_database_privileges.py | 수정 | 새 권한 기대값 |
| docs/validation-runs/<actual-date>-company-demo/DEMO-02-company-knowledge/fixture-approval.md | 신규 | 사용자 승인 기록(승인자·시각·source_sha256) |

## 작업 순서

1. STEP-001 온톨로지·원본 검증 [complex]
   - 목표: 온톨로지·원본 검증의 수용 조건을 충족한다.
   - 작업 대상: 타입/관계·hash/locator 순수 validator·별칭만 다른 ontology version 판정.
   - 검증: spec T1,T2,T8; 아래 명령과 해당 단계 증거.
2. STEP-002 불변 등록·binding·CLI [complex]
   - 목표: 불변 등록·binding·CLI의 수용 조건을 충족한다.
   - 작업 대상: DB/객체·dry-run·activate·실패 transaction·runtime-privileges.sql.
   - 검증: spec T3,T4,T5,T7; 아래 명령과 해당 단계 증거.
3. STEP-003 세 회사 합성 원본 [standard]
   - 목표: 세 회사 합성 원본과 온톨로지 초안을 쓰고 사용자 승인 후 동결한다.
   - 작업 대상: 전문분야·실적·인력·미확인·비주력 작성, 온톨로지 개념·별칭 초안, dry-run, 사용자 승인 기록. 후보 공고는 열람하지 않는다.
   - 검증: spec T1,T2,T5,T8; dry-run errors=[]와 승인 기록(사람 단계이며 승인 전에는 STEP 완료가 아니다).
4. STEP-004 프로필·근거 projection [complex]
   - 목표: 프로필·근거 projection의 수용 조건을 충족한다.
   - 작업 대상: 단일 source의 v2 facts/evidence·v1 호환.
   - 검증: spec T2,T6,T7; 아래 명령과 해당 단계 증거.
5. STEP-005 읽기 API와 버전 탐색 [complex]
   - 목표: 읽기 API와 버전 탐색의 수용 조건을 충족한다.
   - 작업 대상: profile/graph/evidence·절단·소속 검사.
   - 검증: spec T4,T6; 아래 명령과 해당 단계 증거.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-002 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-003 | M | 중간 | standard | 확정 계약과 기존 패턴 적용 |
| STEP-004 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-005 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |

## 검사 명령과 증거

아래는 구현 후 실행할 명령이다. 신규 테스트는 아직 없으며 통과를 주장하지 않는다.

```sh
cd web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false python3 -m pytest tests/deep_review/test_company_knowledge.py tests/app/test_company_knowledge_cli.py tests/screening/test_profile_snapshot.py tests/app/test_module_boundaries.py tests/app/test_alembic_autogenerate.py tests/app/test_runtime_database_privileges.py -q
```

PostgreSQL 대상은 일회용 postgres:17.11과 BIDOPS_TEST_POSTGRES_URL을 사용한다.
운영 DB를 연결하지 않는다. backend 기본 검사에는 BIDOPS_PRESPEC_OVERVIEW_ENABLED=false를 명시한다.
overview=true가 필요한 사례만 fixture에서 설정한다.
실제 로그/exit code/skip/수동 증거는 `docs/validation-runs/<actual-date>-company-demo/DEMO-02-company-knowledge/`에 남긴다.
선행 검사 결과를 현재 변경의 검사로 적지 않는다. 변경 뒤 영향받은 검사만 재실행한다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 프로필/그래프 이중 정본 | 같은 binding의 사실/hash 불일치 | 단일 등록 파생 경계 수정·기존 버전 보존 |
| 공고에 맞춘 회사 설정 | 승인 전 초안에 후보 공고 어휘·과업이 그대로 등장 | 초안 작성 중 후보 공고 열람 금지, 사용자 승인 게이트 |
| 사용자 승인 대기 | STEP-003이 사람 단계에서 멈춤 | 구현과 dry-run을 먼저 끝내고 초안·hash를 한 번에 승인받음 |
| 범위 확장 | 후속 구현/운영 호출을 현재 완료로 표시 | 기능별 수용 조건과 실제 증거를 분리 |

## 증명

- docs: 공통 계약·정본·3문서 일치, 지정 모델 독립 리뷰, diff/링크/STEP 검사.
- tests: 모든 spec T ID를 위 STEP과 assertion에 연결해 명령/결과/skip 기록.
- postgres: DB/API shape 변경 시 임시 PG 검사+head/권한; 아니면 N/A 이유 기록.
- frontend: UI 변경 시 build+두 폭 의미/구조; 아니면 N/A 이유 기록.
- api_guard: 회사 소속/모델 경계 변경 시 승인·hash·호출 0 검사; 아니면 N/A 이유 기록.
- real_data_run: DEMO-05에서 실제 18/9건·담당자 인수; 다른 기능은 N/A(소유 DEMO-05).

## 결과

2026-10-09 STEP-001~005 구현·리더 검증과 기능 최종 독립 리뷰(1회차 FAIL → 수정 → 2회차 PASS_WITH_NOTES, 차단 0)를 마쳤다. proof 기록·커밋·배치 통합이 남으며 커밋·병합은 수동 정책이다.
STEP-005부터는 Codex 리더의 사용량 한도로 Claude Code 리더가 이어받았다(같은 run·기능 worktree, git 명령 없이 진행). 기능 기록은 `_runs/demo0203-20261009/DEMO-02-company-knowledge.md`.

- STEP-001: validator·identity·변조 차단, 리더 77passed 및 지정 독립 delta 리뷰 PASS. `_runs/demo0203-20261009/step001-result.md`.
- STEP-002: 7테이블/0035·원자 등록·binding·CLI·최소 권한. fresh PG migration 통과. 최초 관련 검사 136passed/10failed에서 확인한 Location insert 순서·감사 marker를 수정했고 직접 영향 검사 24passed. 추가 table 목록 검사의 기존 실패 1개는 기준506ac77에서도 재현했다. `_runs/demo0203-20261009/step002-result.md`에 명령·한계를 연결했다.
- STEP-003: `docs/demo-fixtures/README.md`와 원본4개 작성, CLI dry-run3개 모두 exit0/errors=[]/미등록. 2026-10-09 사용자 “현재 초안 승인” 후 동결했으나, 최종 리뷰 B2(값 객체 nullable key 생략이 공통 계약 §3 위반)에 대한 사용자 결정으로 회사 원본 3개에 null을 명시해 재발행했다(사실·인용·노드 순서·ontology 불변). 같은 날 사용자가 재발행 hash를 재승인했고 `docs/validation-runs/2026-10-09-company-demo/DEMO-02-company-knowledge/fixture-approval.md`에 최초 승인(superseded)과 재승인을 기록했다. 실제 DB 등록은 하지 않았다.
- STEP-004: v1/v2 strict profile consumer와 계보·hash·unknown 근거 검증. 리더 red 38failed → green 78passed/skip0(SQLite+PG). `_runs/demo0203-20261009/step004-result.md`.
- STEP-005: 회사 profile·knowledge-graph·profile-evidence 읽기 REST, binding/과거 버전/타회사 404, BFS 절단, 경로 미노출. 리더 red 20failed → green 232passed/skip0(SQLite+일회용 PG17.11). `_runs/demo0203-20261009/step005-result.md`.
- 최종 리뷰 수정: B1(등록 후 소비 불가 3경로: 다중 ref 행 순서·unknown evidence·PG collation), B2(값 객체 정확 key), N2(ontology version 길이), N4(T3 최초 객체 실패·T5 감사) 반영. red 25failed → 리더 최종 455passed/1failed(기존 실패)/skip0. `_runs/demo0203-20261009/review.md`.
- 프런트 오류 code 등록(`company_profile_not_ready`)은 Node 22 Docker production build exit0. `_runs/demo0203-20261009/frontend-build.log`.
- MinIO는 기존 delete 금지 정책을 보존하며 실패 시 발행 version이 남을 수 있다. isolated filesystem의 요청 임시 파일만 rollback/중첩 transaction 종료 시 정리한다.
- 이관: worker 역할의 신규 테이블 SELECT·evidence 목록 code-point 정렬은 DEMO-03, alias-only 판정의 쓰기 경로 연결은 DEMO-05.
- 미커밋 기능 worktree에 보존했고 main/실행 중 스택/실제 모델에는 적용하지 않았다. `bidops-local` 실제 3사 등록·활성화는 공통 계약 §10 준비 단계에 남는다.
