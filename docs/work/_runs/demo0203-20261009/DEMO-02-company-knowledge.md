# DEMO-02 온톨로지와 가상회사 지식그래프

- 기준 SHA: `506ac77627b6ceafab213aeda9e80ebce62e61e8` (`demo/local-20261009`, 배치 `demo0203-20261009`). 기능 브랜치 HEAD도 같은 SHA이며 모든 변경은 미커밋이다(commit_policy=manual).
- 대상: `demo/local-20261009` 전용. main·운영 통합, 실행 중인 `bidops-local` 스택 migration·재배포, 실제 3사 원본 DB 등록·활성화, 모델 호출은 수행하지 않았다.
- 리더: STEP-001~004는 Codex 리더, STEP-005와 기능 마무리는 Codex 사용량 한도(2026-10-09 17:35 KST) 이후 Claude Code 리더가 같은 기능 worktree에서 이어받았다. Claude 세션의 worktree 격리 때문에 이 worktree에서는 git 명령을 실행하지 않았고, 변경 목록·diff는 같은 기준의 배치 workspace 사본과 `diff`로 대조했다.

## 구현과 증거

| 범위 | 리더 검증 | 증거 |
|---|---|---|
| 온톨로지·원본 순수 validator, alias-only 새 version (T1·T2·T8) | 77 passed + 독립 delta 리뷰 PASS | [STEP001](step001-result.md) |
| 7개 테이블·migration 0035·원자 등록·binding·CLI·최소 권한 (T3·T4·T5·T7) | 최초 136 passed/10 failed 원인 수정 후 직접 영향 24 passed, 기존 실패 1개 기준 재현 | [STEP002](step002-result.md) |
| 3사 합성 원본·온톨로지, dry-run, 사용자 승인·동결 | 최초 승인 후 리뷰 B2로 null 명시 재발행, 엄격 validator dry-run 3개 exit0, 재승인 | [STEP003](step003-result.md), [승인 기록](../../../validation-runs/2026-10-09-company-demo/DEMO-02-company-knowledge/fixture-approval.md) |
| profile v2 strict 소비·v1 호환 (T2·T6·T7) | red 38 failed → green 78 passed/skip0 | [STEP004](step004-result.md) |
| 회사 profile·graph·evidence 읽기 REST (T4·T6) | red 20 failed → green 232 passed/skip0 | [STEP005](step005-result.md) |
| 최종 리뷰 수정 B1·B2·N2·N4 | red 25 failed → 구현자 green 307 passed/skip0 | [리뷰](review.md) |
| 프런트 오류 code `company_profile_not_ready` 등록 | Node 22 Docker `tsc -b && vite build` exit0, UI 레이아웃 변경 없음(빌드 후 파일 hash 불변) | [빌드 로그](frontend-build.log) |
| 기능 최종 코드 검사 (STEP-001~005 검사 파일 합집합) | SQLite+일회용 PG17.11 455 passed/1 failed/skip0 | [최종 로그](feature-final-tests-r2.log) |

최종 검사의 실패 1개 `tests/app/test_models.py::test_init_db_creates_all_declared_tables_and_indexes`는 기대 목록에 이 기능 이전부터 있던
`assumption_input_version`·`assumption_run`·`assumption_stage`·`deep_review_preview`·`deep_review_approval` 5개가 빠져 실패하며,
STEP-002가 기준 506ac77에서 같은 실패를 재현했다. 이 기능의 7개 테이블은 기대 목록에 반영했고 관련 없는 기존 기대값은 바꾸지 않았다.
검사 수는 실행 묶음별이며 서로 중복된다. 독립 최종 판정은 [review.md](review.md)(1회차 FAIL → 2회차 PASS_WITH_NOTES, 차단 0)다.

## 한계와 후속

- `bidops-local`의 실제 3사 등록·활성화는 공통 계약 §10 준비 단계에서 직전 사람 확인 후 수행한다. 이 기능의 검사는 격리 SQLite·일회용 PostgreSQL 결과다.
- MinIO에 이미 발행된 원본 version은 delete 금지 정책으로 보존되며 DB 참조가 없는 객체는 저장소 reconciliation 대상이다.
- 이관: worker 역할의 신규 테이블 SELECT와 evidence 목록 code-point 정렬은 DEMO-03, alias-only 판정의 쓰기 경로 연결은 DEMO-05(리뷰 N5·N1).
- 회사별 핏·Luna 심층은 DEMO-03, 회사 화면은 DEMO-04, 별칭 1회 보강·실제 인수는 DEMO-05 소유다.
