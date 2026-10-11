# 배치 demo0203-20261009 최종 독립 리뷰 (2026-10-11)

- 범위: 승인 기준 `506ac77` → DEMO-03 구현 커밋 `7a110ce`(tree `c57721646e7370b465c615188fad4cb9090ee4dc`). 이 리뷰는 아래 노트에 따른 문서 수정(`a9105c7`)과 그 이후 수정 **이전**의 트리를 대상으로 했다. 최종 배치 트리의 문서 일치는 이 리뷰가 아니라 Codex 독립 리뷰(`batch-codex-review*.md`)가 판정한다.
- 기능별 독립 리뷰(DEMO-02 `review.md`, DEMO-03 `demo03-review.md`)는 재수행하지 않고, 두 리뷰가 보지 못한 배치 수준 차이만 검토했다. 리뷰어는 구현에 관여하지 않은 읽기 전용 subagent다.
- 판정: **PASS_WITH_NOTES, 차단 0**.

## 확인 결과

1. DEMO-03이 DEMO-02 표면을 깨지 않는다. 0035 불변, 0036 `down_revision=0035_company_knowledge`·`ALEMBIC_HEAD` 갱신, 고정 head 단언은 단일 체인 head 검사로 교체, 0036에 GRANT 없음. DEMO-02 라우터·schema·`apiErrors.ts` 미변경, 경로 충돌 없음. `company_knowledge.py`는 helper 분리와 공개 graph 함수 추가이며 근거 매핑 동일(T2·T6 유지). worker 지식 테이블 SELECT는 DEMO-02 plan이 DEMO-03에 넘긴 항목이고 binding_event 제외·쓰기 거부 검사가 강화됐다. code-point 정렬 인계는 retrieval의 Python 재정렬로 해소됐다. `policy_identity` null 정책 거부는 배포 정책 파일에 null이 없어 강화만 된다.
2. 공통 제약 충족: 새 테이블·열 `runtime-privileges.sql` 등록, 0036 불변 trigger, lifecycle→deep_review import 없음, `company_fit_policy_version` append-only, demo 정책의 전역 활성 거부, `bidops-local` overlay 외 main·운영 compose/script 변경 없음.
3. 실제 모델 품질·실제 Luna 완료 주장 없음. DEMO-03 `real_data_run` N/A, T9는 DEMO-05 spec/intent가 인수.
4. `docs/validation-runs`·`docs/work/_runs`에 키·토큰·auth.json 내용 없음. 절대 경로는 worktree·scratchpad 경로뿐이다.

## Codex 독립 리뷰 1회차 FAIL과 처리 (2026-10-11)

배치 HEAD `441f5c0`(tree `76df522c`)에 대한 Codex `gpt-5.6-sol`/high 리뷰가 FAIL, 차단 3건을 냈다(배치 worktree `batch-codex-review.md`). 세 건 모두 소스에서 사실로 확인했고 제품 코드 결함은 없었다.

| 차단 | 처리 |
|---|---|
| DEMO-03 intent 사용자 흐름 표·재계획 문단, spec 범위 문단, 공통 계약 §Luna 문단이 실제 Luna 완료를 DEMO-03·DEMO-04 게이트로 요구 | 2026-10-11 사용자 결정(T9→DEMO-05)에 맞춰 문구 정합화. DEMO-03 spec_hash 변경은 `run _ accept-spec`으로 기록 |
| business-rules·contracts DEMO-02 단락의 "DEMO-03~05 미구현", operations 절 제목 "구현 전" | 수정. 같은 패턴 전수 검색으로 PRD·PLAN 절 제목도 함께 수정 |
| 이 파일의 범위 문장이 최종 트리를 대상으로 했다고 기록 | 위 범위 문장을 실제 대상(`7a110ce`)으로 정정 |

## 노트와 처리

| 노트 | 처리 |
|---|---|
| operations.md·ARCHITECTURE.md DEMO-02 단락이 3사 등록·활성화를 미수행으로 적음 | 수정: STEP-007 수행 사실로 갱신 |
| deep-review-erd.md DEMO-02 단락의 "DEMO-03 미구현" | 수정: 아래 DEMO-03 단락 참조로 갱신 |
| ADR.md ADR-0070 색인 "구현 전" | 수정: DEMO-01~03 데모 브랜치 구현, DEMO-04~05 구현 전 |
| `_runs/.../DEMO-03-grounded-analysis.md` 대상 줄, DEMO-03 plan 결과 마지막 줄의 `bidops-local` 미반영 문구 | 수정: STEP-007 적용 사실과 일치 |
| validation-run README "미실행 사유"의 STEP-007 in_progress | 수정: 2026-10-11 적용·종결로 갱신 |
| contracts.md "실제 Luna 대표 1건(STEP-007)" 표현 | 수정: 원안 T9, DEMO-05 이관, STEP-007 범위 명시 |
| DEMO-02 단위 검사 2파일이 DEMO-03 실행 묶음에 없음 | 해소: 배치 최종 코드에서 DEMO-02 검사 9파일 재실행 308 passed, skip 0, exit 0 (`batch-demo02-final-tests.log`) |
| demo web이 운영 `docs/reference/company-profile.md` bind mount 유지(공통 계약 §10 편차, 기록됨) | 미채택: 기록된 편차, compose 정식화는 DEMO-05 |
| `compose/demo03-compose.sh`가 scratchpad 경로를 고정 | 미채택: 증거 보존 파일, 정식 스크립트는 DEMO-05 |
| frontend `apiErrors.ts`에 DEMO-03 오류 code 미등록 | 미채택: 화면은 DEMO-04 소유 |
