# DEMO-00 로컬 구현 결과

- 기준/현재 HEAD: `d12df664b27f28efab1825281567d9bf1b6f9981` (미커밋).
- workspace: `/Users/temp/orca/bidops/.sdlc/worktrees/demo00-20261007-DEMO-00-luna-preflight`.
- 변경: v4 불변 정책, 승인 identity 매핑, 정책 마감, 단계 1/2 slice당 교정 1회, 원응답 암호화 보존, 호출 기록·보고서 warning, 회귀 검사, 계약·운영 runbook.
- v4 SHA: `51b1723051e92299ef53e650f9faf851c8e6777fe75c59b814639d38be887877`.
- 검증 명령: Python 3.12.15 임시 venv에서 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`와 일회용 PostgreSQL 17.11 maintenance URL을 지정했다. 기존 `tests.postgres.temporary_postgres_server`가 검사용 컨테이너 생성·정리를 맡았다.
- 첫 검사 `pytest tests/app/test_luna_deep_review.py tests/app/test_narrative_review.py -q`: 68 passed, 0 skipped. 마지막 코드 수정이 실행 중 들어가 후속 검사로 보완했다.
- 최종 코드 `pytest tests/app/test_luna_deep_review.py -q`: 32 passed, 0 skipped. 소스 전후 hash 일치. narrative 증거는 변경되지 않은 경로에만 재사용한다.
- 리뷰 후 테스트만 추가/확장: `pytest tests/app/test_luna_deep_review.py -k 'repairs_one_invalid_slice or projects_optional_related_claim or schema_invalid_repairs_once or policy_review_deadline' -q`: 10 passed, 29 deselected, 0 skipped. 제품 hash 불변. 개별 실행 건수를 합쳐 한 번의 전수 검사처럼 표시하지 않는다.
- 기존 schema-field/Starlette 경고 9건. Linux/amd64 lockfile wheel hash는 macOS와 달라 같은 고정 버전의 native wheel로 검사했다. 런타임 이미지 빌드 검증은 미수행.
- 독립 리뷰: `review-01.md` fail → 고정 해시 및 테스트 차이 보완 → `review-02.md` 로컬 범위 pass. 범위 확장 없음.
- 운영 원응답은 로컬에 없으므로 과거 응답 형태의 합성 회귀를 사용했다. 실제 모델 품질 증거가 아니다.
- STEP-003 실제 적용, STEP-004 실제 1489 및 사용자 판정 대기. 커밋·병합·push·운영 변경·외부 모델 전송 없음.
- 재개: 이 workspace에서 `$sdlc:sdlc-loop`. runbook을 따라 운영 호스트에서 각 단계 직전 확인 후 실행한 증거를 받는다. 수동 커밋/병합 정책 유지.
- 배치에 통합되지 않은 기능 worktree 증거이므로 `run _ review`의 배치 snapshot에 잘못 연결하지 않았다. 배치 최종 검증·리뷰·finish는 미완료이며 이 기록으로 대체하지 않는다.

## 사용자 요청에 따른 운영 준비 반영

- 2026-10-08 사용자가 "변경을 커밋하고 main에 반영해줘. 2번을 진행하는 방법을 알려줘. 3번도 이어서 진행해줘"라고 명시 요청했다.
- 로컬 검증·독립 리뷰를 통과한 STEP-002 변경을 운영 선검증 준비를 위해 먼저 커밋·main 반영한다. 이는 전체 기능 완료 또는 운영 증거 통과가 아니다.
- 이 명시 요청을 일반 loop의 기능 전체 완료 후 병합 순서보다 우선한다. `run finish`로 pending 운영 proof를 통과시키거나 done으로 기록하지 않는다.
- 반영 직전 제품·정책·테스트 hash가 기존 최종 검사 기록과 동일함을 확인했다. 새 코드 변경이 없어 검사·독립 리뷰를 반복하지 않는다.
- 배포, policy import, 활성 ID/토글 변경, 실제 1489 payload 전송은 운영 호스트에서 각 단계 직전 확인 후 진행한다. main 반영은 이 승인을 대신하지 않는다. origin push와 브랜치 삭제는 요청 범위에 없다.
