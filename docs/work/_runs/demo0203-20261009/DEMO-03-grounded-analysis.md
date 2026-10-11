# DEMO-03 그래프 근거 기반 모델 분석

- 기준 SHA: `0d980bd` (배치 `sdlc/batch-demo0203-20261009`, DEMO-02 통합 직후). 기능 브랜치 `sdlc/demo0203-20261009-DEMO-03-grounded-analysis` HEAD도 같은 SHA이며 모든 변경은 미커밋이다(commit_policy=manual).
- 대상: 데모 브랜치 전용. main·운영 통합과 실제 모델 호출은 수행하지 않았다. STEP-001~006 구현 중에는 `bidops-local`을 바꾸지 않았고, 스택 재배포·0036 migration·3사 등록·정책 import는 2026-10-11 STEP-007에서 단계별 사용자 승인 후 수행했다.
- 리더: Claude Code 리더가 STEP-001~006을 sdlc:implementer-opus에 단계별 위임하고 매 단계 일회용 PostgreSQL 17.11에서 독립 재실행·hash 대조로 검증했다. 상태는 리더만 변경했다.

## 구현과 증거

| 단계 | 범위 | 리더 검증 | 증거 |
|---|---|---|---|
| STEP-001 | 순수 그래프 검색·concept 매핑·3 hop 경로·상한·coverage·slice (T1) | 153 passed exit0, hash 일치 | [결과](demo03-step001-result.md) |
| STEP-002 | migration 0036·fit 정책 v2·`import-company-fit-policy`/`enqueue-company-fit` CLI·동결 입력/FrozenProvenance·runner 회사 분기 (T2 핏·T4 핏·T8) | 515 passed/1 failed(DEMO-02 잔존 head 고정 단언 → 체인 head 검사로 교체 후 12 passed) exit0, hash 일치 | [결과](demo03-step002-result.md) |
| STEP-003 | 회사 Luna preview/승인/생성/재시도·현재성·worker `approved_company_input` (T2 심층·T3·T6) | 625 passed/0 skipped exit0, hash 일치 | [결과](demo03-step003-result.md) |
| STEP-004 | `analysis-policy-luna-demo-v1`(sha256 `9cb6254e…c3b0`)·identity 매핑·회사 slice 빌더/검증 (T4 입력·T5) | 542 passed/0 skipped exit0, hash·정책 sha·v4 diff 확인 | [결과](demo03-step004-result.md) |
| STEP-005 | 회사별 GET 6개·비교·FrozenProvenance GET·legacy reader 거부 (T6 API·T7) | 661 passed/0 skipped exit0, hash·import 방향 확인 | [결과](demo03-step005-result.md) |
| STEP-006 | 공용 슬롯 claim 분기·fake Luna 종단·legacy writer/CLI/정책 분리·누락 수정 2건(선택 사실 slice 배치, 핏 문서 집합 동결) (T2~T8) | 751 passed/0 skipped exit0, hash 일치 | [결과](demo03-step006-result.md), [최종 로그](demo03-step006-leader.log) |
| 독립 최종 리뷰 | 기준 0d980bd→전체 변경 vs 계약·spec·제약 | PASS_WITH_NOTES, 차단 0; N2(PG 정렬 변형) 수정 반영 | [리뷰](demo03-review.md) |
| STEP-007 | 실제 격리 스택 준비·호출 전 게이트 확인 (T9 재정의, 2026-10-11) | 사용자 단계별 승인 4회로 `bidops-local`에 백업·롤백 태그·이미지 `demo03-20261011`·0036 migration·3사 import/activate·demo 정책 2건·`env/demo.env`·web/analysis-worker 교체·codex-runner 적용. 공고 179 회사 미리보기 3사 모두 409 `company_input_invalid`(모델 호출 0) — 기존 findings inventory 불일치 재현. 사용자 결정으로 원안 T9(실제 Luna 대표 1건)는 DEMO-05로 이관 | [증거](../../../validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md), [진행 기록](demo03-step007-result.md), `demo03-step007-*.log` |

최종 검사(2026-10-11, 재계획 문서 반영 후 최종 코드): plan "검사 명령과 증거" 8개 파일 + 회사 테스트 8개 파일을 일회용 PostgreSQL 17.11에서 재실행 → **510 passed, 0 skipped, exit 0**(`demo03-final-leader.log`). `doctor _` 정상(`demo03-final-doctor.log`). tests·postgres·api_guard proof의 증거다.
검사 수는 실행 묶음별이며 서로 중복된다. 모든 리더 로그는 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`와 `tests.postgres.temporary_postgres_server`(일회용 postgres:17.11)로 실행했고 skip 0이다.
기준에서도 실패하는 무관 항목(test_auto_preparation ×11 — ADR-0069 자동 시작 기본 false, hwp fetch fixture)은 범위 밖으로 사실대로 남긴다.

## 문서

`docs/contracts.md`·`docs/ARCHITECTURE.md`·`docs/business-rules.md`·`docs/deep-review-erd.md`의 "가상 SI 3사 데모 계약" 절에 DEMO-03 단락(CLI·REST·오류 code·정책·worker 분기·legacy 분리·schema·권한·sanitizer 제거 필드)을 추가했다. `doctor _` 정상, `check-plan` 일치.

## 리더 결정(계약 침묵 구간, 단계 결과 파일에 상세)

`model_revision` CHECK 완화(회사 행 NULL 허용), 핏 `profile_characters` 12000·심층 8000, `global_path_index`·`excluded_path_count_by_requirement`는 sanitizer로 모델 미노출(provenance 전용), 설정 gate는 replay보다 앞, `version_conflict` 409 재사용, lifecycle 공개 함수가 확장점, 핏 documents=공고 현재 문서 집합(개요 문서 포함), 승인 후 bundle 교체는 worker가 호출 전 `bundle_not_ready`로 fail-closed, EvidenceRef 등에 회사 열 미추가(`deep_review_id` 계보).

## 상태와 커밋 대기 (2026-10-11)

- status: STEP-001~007 done, proofs docs/tests/postgres/api_guard=pass, frontend·real_data_run=not_applicable, phase=validating. `check` 필수 검증 충족, `run _ ready --feature DEMO-03-grounded-analysis` 통과(배치 통합 가능). `run _ accept-spec`으로 2026-10-11 spec 재정의 기록.
- commit_policy=manual: 사용자가 기능 변경을 `7a110ce`로 커밋했다. 이후 loop는 ExitWorktree(keep) → 배치 통합 → §4 배치 검증 → `run _ finish`(merge 대기)로 진행한다.
- 배치 worktree의 `run.md`는 이 세션(기능 worktree 고정)에서 갱신하지 못했다. 배치 통합 단계에서 이 파일의 내용을 옮긴다.

## 배치 §4 최종 검증 (2026-10-11, 기능 worktree에서 선행)

기능 커밋 `7a110ce`의 부모가 배치 HEAD `0d980bd`이고 기준 `demo/local-20261009`가 `506ac77`에서 움직이지 않았다. 따라서 no-ff 병합 결과 트리는 이 worktree 트리와 같고, 배치 검증을 병합 전에 이 트리에서 수행했다. 이 세션은 기능 worktree에 고정돼 배치 worktree에서 git을 실행할 수 없다.

- DEMO-02 검사 9파일을 최종 코드에서 1회 재실행했다. 일회용 PostgreSQL 17.11, 308 passed, 0 skipped, exit 0 (`batch-demo02-final-tests.log`).
- 배치 독립 리뷰(Claude 읽기 전용 subagent, 506ac77→7a110ce)는 PASS_WITH_NOTES, 차단 0이다(`batch-review.md`). 정본 문서의 stale 문구 7건을 Markdown 8줄로 고쳤다.
- 두 기능 proof를 재기록했다. DEMO-02는 새 검사 로그, DEMO-03은 Markdown만 바뀌어 기존 510 passed 로그를 재사용했다. 두 기능 모두 `check` 충족, `run _ ready` 통과.
- DEMO-02 spec_hash는 공유 입력(roadmap DEMO-03 행, feature.json real_data_run 범위)만 바뀌어 `run _ accept-spec`으로 기록했다.
- **차단: Codex 독립 리뷰.** run engine이 codex라 `run _ finish`는 `runtime.codex.json`의 review 프로필(`gpt-5.6-sol`/high)로 기록된 `run _ review`를 요구한다. 2026-10-11 시도가 Codex 사용량 한도로 실패했다(`batch-codex-review-attempt1-usage-limit.events.jsonl`, 재시도 가능 2026-10-14 13:23). Claude 리뷰를 그 모델로 기록하지 않았다. 프롬프트는 `batch-codex-review.prompt.md`에 보존했다.

배치 worktree에서 남은 순서(사용자 커밋 뒤):

1. 이 worktree의 문서 수정·증거·proof 재기록을 기능 브랜치에 커밋한다.
2. 배치 worktree에서 Claude를 시작해 `git merge --no-ff sdlc/demo0203-20261009-DEMO-03-grounded-analysis` 후 HEAD tree가 기능 브랜치 tree와 같은지 확인한다.
3. 배치에서 `check` 두 기능을 다시 확인하고 run.md에 이 절을 옮긴다.
4. Codex 한도 해제 뒤 같은 프롬프트로 리뷰를 실행해 `run _ review --evidence <보고서> --model gpt-5.6-sol --effort high --independent --result pass|fail`로 기록한다.
5. `run _ finish` → 병합 대기(merge_policy=manual). 기준 반영은 사용자 요청 시 `run _ finish --merge`.

## 한계와 후속

- 실제 Luna 대표 1건(원안 T9)은 수행하지 못했다. 격리 스택 준비는 끝났지만(`bidops-local` web·analysis-worker가 `demo03-20261011`, codex-runner 기동, 3사 활성, demo 정책 ID 주입) 유일한 준비 공고 179가 문서 inventory 불일치(findings 2026-09-22 항목)로 미리보기 단계에서 fail-closed됐다. 2026-10-11 사용자 결정으로 T9를 DEMO-05로 이관했고 `real_data_run` proof는 DEMO-03 비적용이다. 스택은 demo flag·Luna enable 상태로 남아 있으며 실제 호출은 DEMO-05에서 건별 승인한다.
- 본 기능 변경에 `scratch` 산출물(compose overlay 2개·wrapper·진단 스크립트)은 `docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/compose/`에 보존했다. `docker-compose.demo.yml`·`prepare-company-demo.sh` 정식화는 DEMO-05.
- fake runner는 `running` 상태를 돌리지 않아 LunaClient polling loop는 실제 실행에서 처음 검사된다.
- 어휘 미일치로 실제 공고의 요구가 대부분 `unmapped`가 될 가능성(별칭 1회 보강은 DEMO-05).
- backlog(리뷰 노트): sanitizer whitelist 결정(N1), 회사 라우터 code 로그(N6), `_check_delivery` TypeError code화·coverage 내용 검증(N7), pydantic schema 고정 운영 주의(N11), `DISTINCT ON`(N13), legacy 거부 code 균일화(N14), `close_deep_review --list-active` 회사 행 노출.
- 전체 18핏/9보고서·담당자 인수·prepare/verify 스크립트는 DEMO-05, 화면은 DEMO-04 소유다.
