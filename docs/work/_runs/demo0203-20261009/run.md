# DEMO-02~03 실행

- 승인: 사용자 2026-10-09 `loop로 03까지 진행해봐`.
- 대상: DEMO-02-company-knowledge → DEMO-03-grounded-analysis. 기준 `demo/local-20261009` / `506ac77`.
- 배치: `.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/batch-demo0203-20261009`.
- DEMO-02: `.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/demo0203-20261009-DEMO-02-company-knowledge`.
- 기존 수동 commit/merge 정책 유지. 사용자 요청에 따른 검증 결과의 데모 브랜치 반영 범위만 계속하며 main/push/운영 배포는 포함하지 않는다.
- 단계별 지정 프로필 구현자, 리더 단일 검사, 별도 지정 리뷰 프로필을 사용한다. SQLite 격리 및 일회용 PostgreSQL 17.11로 직접 영향 경로를 검증한다.
- 회사 합성 원본은 후보 공고를 보지 않고 작성한 뒤 사용자 승인과 hash를 기록해야 동결/등록한다. 실제 자료 전송·모델 호출은 구체적인 미리보기와 범위 승인 후에만 한다.
- DEMO-03 실제 Luna 대표 인수는 구현 검사와 별도 필수 게이트다. 기존 LiteLLM 개요를 대체 증거로 사용하지 않는다.

## 2026-10-09 진행

- DEMO-02 기능 worktree에서 STEP-001·002 검증 완료. STEP-003의 가상회사3사와 ontology 초안은 CLI dry-run 통과, 사용자 승인 요청 중이다.
- 승인 대상은 기능 worktree의 `docs/demo-fixtures/README.md`와 `_runs/demo0203-20261009/step003-approval-request.json`에 결속했다. 승인 전 미등록·미동결이다.
- STEP-004·005, 기능 독립 최종 리뷰, DEMO-03은 아직 시작하지 않았다. 배치/기준 브랜치 통합도 아직 하지 않았다.
- 운영 및 실행 중 로컬 스택 migration/실제 모델 전송 없음. 관련 기존 test_models 테이블 목록 실패는 기준506ac77에서도 재현해 기능 결과 기록에 남겼다.

- 사용자 “현재 초안 승인” 수신: DEMO-02 기능 worktree의 승인 대상4개 원본 hash 일치 확인, `docs/validation-runs/2026-10-09-company-demo/DEMO-02-company-knowledge/fixture-approval.md` 기록. STEP003 완료/원본 동결, STEP004 구현 시작. 실제 DB 등록·배포·모델 호출은 아직 없음.

## 2026-10-10 DEMO-02 배치 통합

- 사용자 커밋 `3500aef`(기능 브랜치 `sdlc/demo0203-20261009-DEMO-02-company-knowledge`). `run _ ready --feature DEMO-02-company-knowledge` 통과(2026-10-10T16:34:56 기록) 확인 뒤 사용자 `이어서 진행` 요청으로 배치에 no-ff 병합 `0d980bd`. 충돌 없음. 기준 브랜치 `demo/local-20261009`에는 아직 반영하지 않았다(merge_policy=manual).
- 병합 뒤 배치에서 `run _ ready` 재확인 통과, doctor 6 features. DEMO-00·01은 status.json phase=done이나 DEMO-02 소스가 프로젝트 스냅샷 hash를 바꿔 `check`가 stale(입력 변경)로 표시한다. 이 run 범위 밖이며 §4 최종 검증에서 처리 여부를 기록한다.
- 배치 worktree의 `run.json`·`run.md`는 이전 배치와 같이 미추적 상태로 둔다(수동 커밋 정책).
- 다음: DEMO-03 기능 worktree `.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/demo0203-20261009-DEMO-03-grounded-analysis` (브랜치 `sdlc/demo0203-20261009-DEMO-03-grounded-analysis`, 기준 배치 HEAD `0d980bd`).

## 2026-10-11 DEMO-03 배치 통합과 §4 최종 검증

- 기능 브랜치 커밋: `7a110ce`(DEMO-03 구현), `a9105c7`(배치 최종 검증 증거·stale 문구 정리, 사용자 커밋). 사용자 `이어서 진행` 요청으로 배치에 no-ff 병합 `441f5c0`. 충돌 없음. 병합 HEAD tree `76df522c`가 기능 브랜치 tree와 같다. 기준 `demo/local-20261009`는 `506ac77`에서 움직이지 않았다.
- §4 검증은 병합 전 같은 tree의 기능 worktree에서 수행했고 tree 동일성으로 재사용한다. 상세는 `DEMO-03-grounded-analysis.md` §"배치 §4 최종 검증".
  - DEMO-02 9파일 최종 코드 재실행: 일회용 PostgreSQL 17.11, 308 passed, skip 0 (`batch-demo02-final-tests.log`).
  - DEMO-03 리더 검사 510 passed, skip 0 (`demo03-final-leader.log`). 병합 뒤 변경은 Markdown뿐이다.
  - 배치 독립 리뷰(Claude 읽기 전용): PASS_WITH_NOTES, 차단 0 (`batch-review.md`). backlog 노트는 DEMO-03 결과 파일 §한계와 후속.
  - DEMO-02 spec_hash 변화는 공유 입력뿐이라 `run _ accept-spec`으로 기록했다.
- 병합 뒤 배치에서 `check` 두 기능 충족, `run _ ready` 두 기능 통과(2026-10-11).
- 실제 Luna 대표 1건(T9)은 2026-10-11 사용자 결정으로 DEMO-05로 이관했다. DEMO-03 `real_data_run`은 비적용이며 실제 모델 품질이나 실제 Luna 완료를 주장하지 않는다.
- **차단: Codex 독립 리뷰.** run engine=codex라 `run _ finish`는 review 프로필(`gpt-5.6-sol`/high)로 기록된 `run _ review`를 요구한다. 2026-10-11 시도는 사용량 한도로 실패했다(재시도 가능 2026-10-14 13:23). Claude 리뷰를 그 모델로 기록하지 않는다.
- 재개 순서:
  1. 한도 해제 뒤 배치 worktree에서 `batch-codex-review.prompt.md`로 Codex 리뷰를 실행한다. 프롬프트의 "`7a110ce` + 미커밋 문서 수정" 문장은 "배치 HEAD `441f5c0`(`git diff 506ac77`)"로 읽게 한 줄 보정해 전달한다.
  2. `run _ review --evidence <보고서> --model gpt-5.6-sol --effort high --independent --result pass|fail`.
  3. `run _ finish` → 병합 대기(merge_policy=manual). 기준 반영은 사용자 요청 시 `run _ finish --merge`.
