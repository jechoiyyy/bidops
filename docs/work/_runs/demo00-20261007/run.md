# DEMO-00 재개 기록

- 승인 범위: 기존 run `demo00-20261007`, DEMO-00-luna-preflight만. 기준 main `d12df664b27f28efab1825281567d9bf1b6f9981`.
- 배치: `/Users/temp/orca/bidops/.sdlc/worktrees/batch-demo00-20261007`.
- 기능: `/Users/temp/orca/bidops/.sdlc/worktrees/demo00-20261007-DEMO-00-luna-preflight`, 브랜치 `sdlc/demo00-20261007-DEMO-00-luna-preflight`.
- 2026-10-08 Codex에서 기존 실행 재개. 생성 당시 engine=claude 기록은 보존하며, 이번 구현과 독립 리뷰는 runtime.codex.json의 complex/review(gpt-5.6-sol high)를 사용한다. 새 run은 만들지 않는다.
- 기존 STEP-001 진단 및 STEP-002 in_progress 상태를 보존한다. 운영 원응답 재검사는 미수행이다.
- commit_policy=manual, merge_policy=manual, manual_proof=defer. 운영 적용·실제 전송은 단계별 사용자 실행/확인이 필요하다.
- STEP-002 구현: 별도 complex 에이전트. STEP-003 중 운영 runbook 준비만 별도 complex 에이전트가 수행한다. 운영 단계 완료로 표시하지 않는다.
- 검증: T1/T2/T3/T6/T7을 Luna·narrative 두 테스트 파일에서 검사하고 코드/문서 diff를 독립 리뷰한다. 로그는 이 run 폴더에 보존한다. T4/T5는 운영 환경 증거 대기다.
- 검증 환경: macOS Python 3.12.15, `/tmp/bidops-demo00-verify-venv`. Linux/amd64 wheel hash 전용 lockfile은 cffi 해시 불일치로 설치 실패했다. 저장소 lockfile을 바꾸지 않고 동일 고정 버전의 macOS 패키지를 임시 환경에 설치했다.

## 재개 결과

- STEP-002 완료, STEP-003 운영 실행 대기로 기능 phase=blocked (resume_phase=implementing). STEP-004 pending.
- 기능 worktree의 `docs/work/_runs/demo00-20261007/DEMO-00-luna-preflight.md`에 검사·한계·재개 경로를 기록했다. `implementation.diff`, `review-01.md`, `review-02.md`, 검사 로그와 입력 hash를 함께 보존한다.
- 독립 리뷰 로컬 PASS. 첫 관련 두 파일 68 passed; 코드 호환성 수정 뒤 Luna 32 passed; 리뷰 추가 테스트 10 passed. 운영 증거와 배치 최종 검증은 미완료다.
- 기능 변경은 미커밋이며 배치/main에 통합하지 않았다. 기능 worktree에서 재개해야 한다. batch에 없는 코드를 batch review hash로 승인하지 않았다.

## 사용자 명시 요청에 따른 main 운영 준비 반영

- 2026-10-08 사용자: 변경 커밋·main 반영 후 운영 적용 안내와 1489 실제 검증 진행 요청.
- 기능 커밋 `fd42fe5`를 배치에 fast-forward 통합했다. 제품·정책·테스트는 기존 검사/리뷰 hash와 동일하다. 독립 리뷰를 동일 배치 입력에 연결했다.
- 전체 기능 완료 전 로컬 검증된 배포 준비 변경만 먼저 main에 반영하는 명시 요청이다. pending proof를 바꾸지 않고 run finish/done은 호출하지 않는다. 운영 적용과 실제 전송은 단계 직전 사용자 확인이 필요하다.
- 재개 작업 디렉터리는 이 배치 workspace를 우선한다. 기능 worktree는 보존하고 더 오래된 상태를 덮어쓰지 않는다.
- 커밋 전 diff 검사에서 implementation.diff의 빈 문맥 행이 trailing whitespace로 표시됐다. 이는 보관한 unified diff 문법이며 제품 코드 공백 결함이 아니다. 해당 artifact를 제외한 변경 검사를 적용했다.
