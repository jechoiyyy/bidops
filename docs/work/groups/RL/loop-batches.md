# RL 배치 실행 계획과 시작 프롬프트 (2026-10-16)

큐 순서·의존은 `docs/work/queue.json`, 상태는 각 `status.json`이 정본이다. 이 문서는 `/sdlc:loop`를 띄울 때 붙여 넣는 승인 범위와 정지 조건의 기록이다.

## 배치

| 배치 | 기능 | 사람 확인이 필요한 지점 | 격리 자원 |
|---|---|---|---|
| A | RL-00 → RL-01 → RL-02 | 없음(LLM 호출 없음). RL-01 T12 Slack 실제 발송만 테스트 채널·토큰 준비 뒤 사람 확인 | `COMPOSE_PROJECT_NAME=bidops-local`, 일회용 `postgres:17.11`, Playwright `vite preview --host 127.0.0.1` |
| B | RL-03 → RL-04 | 정책 승인 CLI 실행, 실제 Luna 1건씩(RL-03 T12·RL-04 T11) 직전 확인 | 위 + codex-runner |
| C | RL-05 → RL-06 | gold 10건 작성(모델 전), 인수 decision | 위 |

배치 A 전 사용자 준비: 없음(인터뷰 G1~G6 답은 RL-00 STEP-004 회사 파일에 들어가며, 비어 있으면 `unknown`으로 등록한다).

## 시작 전 체크

1. 트리가 깨끗해야 한다(loop §1.4). 미커밋 변경을 두 커밋으로 나눈다(아래 명령).
2. `python3 scripts/feature_status.py run _ show` → `{}`(활성 run 없음).
3. `python3 scripts/feature_status.py doctor _` 통과, `check-plan` 7개 "plan 일치".
4. `bidops-local` 스택이 떠 있지 않아도 배치 A의 단위·PG 검사는 돈다(PG는 일회용 컨테이너). RL-00 STEP-006·RL-01 STEP-008은 bidops-local이 필요하다.

```bash
# 1) 테마·셸 적용(앞선 작업)
git add web/frontend docs/ADR.md docs/tracking/status.md docs/tracking/decisions/0073-rootlab-real-company-ax-redefinition.md docs/1016_rootlab-redefinition docs/reference
git commit -m "feat(frontend): RL 시안 테마 토큰 교체와 공통 셸 적용 (ADR-0048 개정)"
# 2) RL 명세·큐
git add AGENTS.md CLAUDE.md docs/work docs/reference/company-homepage-profile.md docs/reference/company-preferences.md
git commit -m "docs(rl): RL-00~06 기능 명세와 SDLC 실행 큐 추가"
```
(`data/runs/*` 미추적 디렉터리는 커밋하지 않는다.)

## 시작 프롬프트 — 배치 A

```
/sdlc:loop RL-00-company-ground-truth,RL-01-daily-briefing,RL-02-opportunity-timeline

배치 A 승인 범위: 위 세 기능을 큐 순서대로 한 run에서 구현·통합·검증한다. 이 메시지를 범위 승인으로 쓰고 다시 묻지 않는다.

지킬 것
- 정본: 각 기능의 intent·spec·plan(docs/work/groups/RL/features/*). spec과 코드가 다르면 spec 우선, spec 자체를 바꿔야 하면 멈추고 묻는다.
- 격리: 모든 실행은 bidops-local(COMPOSE_PROJECT_NAME=bidops-local)과 일회용 postgres:17.11. 운영 compose·운영 DB·cron·origin push 금지.
- 외부 호출 없음(배치 A에 LLM 호출 없음). Slack 실제 발송(RL-01 T12)은 토큰이 준비되기 전엔 skipped로 두고 가짜 서버 검사까지만 한다.
- 커밋·병합은 수동(commit_policy=manual). 기능별 구현이 끝나면 커밋 메시지 초안만 보여 준다.
- 검증은 plan "증명" 절의 명령만. 통과 뒤 반복 실행 금지. 실패는 원인·변경 관련성부터 보고하고 숨기는 수정(.first()·강제 클릭·기대값 완화) 금지.
- Playwright는 vite preview --host 127.0.0.1 로 띄운다(IPv6 timeout 이슈).

정지 조건(여기서 멈추고 보고)
- 어느 기능이든 같은 단계 재시도 1회 뒤에도 검증 실패.
- 모듈 경계(test_module_boundaries)·권한(test_runtime_database_privileges)·alembic drift 검사 실패.
- spec에 없는 테이블·REST·설정 키가 필요해질 때.
- 회사 파일(RL-00 STEP-004)에 문서에 없는 사실을 넣어야 할 때 — 지어내지 말고 unknown으로 두고 목록을 보고.
- 외부 전송이 필요해 보일 때.

보고 형식
- 기능마다: 끝난 단계, 실행한 검증 명령과 결과, 바꾼 계약(contracts/business-rules/ui-spec diff 요약), 남은 수동 proof, 커밋 메시지 초안.
- 배치 끝: run 상태, 통합 브랜치, 기준 브랜치 반영 전 확인 항목.
```

## 시작 프롬프트 — 배치 B·C(배치 A가 main에 반영된 뒤)

배치 B는 `RL-03-fit-verdict,RL-04-proposal-draft`, 배치 C는 `RL-05-gold-acceptance,RL-06-local-llm-optimization`로 같은 틀을 쓰되 다음을 더한다.
- B: 정책 승인 CLI(`approve-transfer-policy`)와 실제 Luna 호출(RL-03 T12 폴리텍 1건, RL-04 T11 1건)은 각각 직전에 사람 확인을 받는다. `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED`는 배치 C의 gold 선정이 끝날 때까지 false.
- C: gold 10건은 사용자가 모델 출력 전에 쓴다. 도구가 만든 `acceptance.json`의 decision은 null이며 사람이 채운다. 채점 전까지 RL-05는 validating.
