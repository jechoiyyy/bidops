# DEMO-02 기능 최종 독립 리뷰

- 리뷰어: runtime 설정의 독립 리뷰 agent(`general-purpose`, 구현에 관여하지 않은 컨텍스트). 읽기 전용, 테스트 실행 없음(검사 실행자는 리더 하나).
- 범위: 기준 `506ac77` → 현재 기능 worktree 전체 변경(미커밋), spec T1~T8, 공통 계약 §1~4·§8, 프로젝트 강제 제약.

## 1회차 — FAIL (차단 2)

| ID | 판정 | 내용 | 처리 |
|---|---|---|---|
| B1 | 차단·수용 | 계약상 유효한 원본이 등록·활성화되지만 소비자가 거부해 세 GET·`profile_context`가 500이 되는 경로 3개: (a) 정렬되지 않은 다중 source_ref 행/snapshot 불일치, (b) unknown evidence 노드 소비 거부, (c) PostgreSQL collation 순서와 Python 정렬의 위치 대조 | 행을 동결 snapshot에서 기록, id 기준 대조, unknown evidence 소비 허용. SQLite·PG 회귀 검사 추가 |
| B2 | 차단·수용 | 값 객체가 계약 §3 필수 key(`?`=nullable) 생략을 허용하고 승인 원본 3개가 생략에 의존 | 사용자 결정 “원본에 null 명시”: validator 정확 key 집합, 3사 원본 null 명시 재발행·재승인([승인 기록](../../../validation-runs/2026-10-09-company-demo/DEMO-02-company-knowledge/fixture-approval.md)) |
| N1 | 권고·이관 | alias-only ontology 판정이 쓰기 경로에서 호출되지 않음 | DEMO-05 별칭 1회 보강(spec “개념 불변”) 구현 시 쓰기 전 판정으로 연결한다 |
| N2 | 권고·수용 | ontology version 128자 초과가 storage_failed(exit1) | validator에서 ontology_invalid(exit2) |
| N3 | 권고·해소 | 일부 단계 검사 증거가 최종 코드보다 오래됨 | 단계 검사 파일 합집합을 최종 코드에서 리더가 재실행 |
| N4 | 권고·수용 | T3 최초 import 객체 실패, T5 새 프로세스 lifecycle 등록 단언 부재 | 검사 추가 |
| N5 | 권고·이관 | worker 역할에 신규 7개 테이블 SELECT 없음, v2 profile_context 사용 시 필요 | DEMO-03 STEP-002(worker enqueue)에서 `scripts/runtime-privileges.sql`과 권한 검사로 추가한다 |
| N6 | 권고·기존 기록 | 실패 정리 문장을 격리 filesystem 임시 파일로 좁힘 | run decision(2026-10-09T15:49)으로 이미 승인 기록 |

추가 관찰(이관): `profile_context`의 evidence 목록은 기존 v1 공용 코드에서 SQL `ORDER BY fact_key`라 DB collation에 따라 순서가 달라질 수 있다. DEMO-03에서 모델 입력 hash에 이 목록을 쓰면 code-point 정렬로 정규화한다.

## 2회차(차이 재검토) — PASS_WITH_NOTES (차단 0)

- B1·B2·N2·N4 수정이 소스와 회귀 검사로 확인됐다. B1 PG collation 사례는 `staff.a`/`staff-b`로 실제 차이를 재현한다.
- 재발행 원본은 backup 대비 null key 추가 외 바이트 변화가 없고, 현재 hash가 재승인 요청·README와 일치한다.
- 메모: 재승인 전 기능 미완료(이후 2026-10-09T19:06:02+09:00 재승인 기록), 승인 기록의 superseded 표시(반영), N1·N5 이관 위치 명시(위 표).

## 증거

- 수정 전 red: `review-fix-before.log` 25 failed/13 passed, exit1.
- 구현자 green: `review-fix-tests.log` 307 passed/skip0.
- 리더 최종: `feature-final-tests-r2.log` 455 passed/1 failed/skip0(SQLite+일회용 PG17.11). 실패 1개는 기준 506ac77에서도 재현된 `test_models::test_init_db_creates_all_declared_tables_and_indexes`(기대 목록에 기존 5개 테이블 누락).
- 원본 재발행: `step003-reissue-dry-run.log`, `step003-reapproval-request.json`.
