# run rla-20261016 — RL 배치 A (RL-00·01·02)

- 승인: 2026-10-16 사용자 `/sdlc:loop` 메시지(배치 A 승인 범위, 다시 묻지 않음). commit_policy=manual, merge_policy=manual, manual_proof=defer.
- 기준: `main` c93da20 (`docs(rl): RL-00~06 기능 명세와 SDLC 실행 큐 추가`)
- 배치 브랜치·worktree: `sdlc/batch-rla-20261016` · `.sdlc/worktrees/batch-rla-20261016`
- 시작 전 조치: 사용자 미추적 회차 2개(`data/runs/hp03-polytech-prespec-20261012-20261015T131653Z/`, `data/runs/lifecycle-20261012-plans/`)를 깨끗한 트리 검사 때문에 `.git/info/exclude`에 추가(기존 로컬 회차 제외 선례와 같음). 파일은 그대로다.

## 격리·지킬 것(사용자 지시)

- 실행은 `bidops-local`(COMPOSE_PROJECT_NAME=bidops-local)과 일회용 `postgres:17.11`만. 운영 `bidops` 스택·DB·cron·origin push 금지.
- 외부 호출 없음(LLM 없음). Slack 실제 발송(RL-01 T12)은 토큰 준비 전 skipped, 가짜 서버 검사까지.
- 검증은 plan "증명" 절 명령만, 통과 뒤 반복 금지. 숨기는 수정 금지.
- Playwright는 `vite preview --host 127.0.0.1`.

## 정지 조건

같은 단계 재시도 1회 뒤 실패 · test_module_boundaries / test_runtime_database_privileges / alembic drift 실패 · spec에 없는 테이블·REST·설정 키 필요 · 회사 파일에 문서 밖 사실 필요(unknown으로 두고 보고) · 외부 전송 필요.

## 실행 환경

- Python venv(이 세션 scratchpad, uv 3.12, `requirements.txt` 범위 설치 — `requirements.lock`은 linux/amd64 hash라 mac에서 불가)
- PG 검사: scratchpad `run_pg_pytest.py`(tests.postgres.temporary_postgres_server 래퍼)

## 기능 worktree

| 기능 | 브랜치 | 경로 | 기준 SHA |
|---|---|---|---|
| RL-00-company-ground-truth | `sdlc/rla-20261016-RL-00-company-ground-truth` | `.sdlc/worktrees/rla-20261016-RL-00-company-ground-truth` | c93da20 |
| RL-01-daily-briefing | `sdlc/rla-20261016-RL-01-daily-briefing` | `.sdlc/worktrees/rla-20261016-RL-01-daily-briefing` | df02b33 |
| RL-02-opportunity-timeline | `sdlc/rla-20261016-RL-02-opportunity-timeline` | `.sdlc/worktrees/rla-20261016-RL-02-opportunity-timeline` | 5e2e119 |

## 진행 기록

- RL-00: 단계 7/7 done, proof 전부 pass(real_data_run 비적용), phase validating, `run _ ready` 통과(2026-10-17). **커밋 대기**(commit_policy=manual) — 사용자가 기능 브랜치에 커밋한 뒤 배치에 no-ff 통합하고 RL-01 시작. 상세 `RL-00-company-ground-truth.md`(기능 worktree).
- 사용자 결정(run 중): ① bidops-local 검증은 새 DB `bidops_rla`(기존 `bidops` DB는 HP-03 migration 0039로 이력 분기) ② RL-00 demo-on 리다이렉트 spec대로 적용.
- bidops-local 자원: DB `bidops_rla`(head 0037, 루트랩 활성 graph 3437d2fc…), 이미지 `bidops-local:rla-20261016-rl00`, volume `bidops-local_rla-web-data`·`bidops-local_rla-pipeline-data`, overlay scratchpad `rla-local.yml`(서비스 `rla-migrate`·`rla-web`, egress 없음). 컨테이너는 검사 뒤 제거.
- 2026-10-17: 사용자 "커밋도 진행해주고 계속해줘" → RL-00 커밋 a4f6ee5, 배치 통합 bd1d2f7. 커밋 뒤 snapshot 표식 변화로 proof 재기록 f6e5f1b → df02b33.
- RL-01: 8/8 done, proof pass, validating, ready, 커밋 e64a585·0b90753, 배치 통합 5e2e119. 지역 제외 보류(spec accept), 루트랩 파일 v2, T12 bidops_rla 감독 시운전(--send 제외).
- 2026-10-17 사용자 지시: 이후 선택은 권장안으로 진행하고 `decisions.md`에 기록.
- RL-02: phase implementing. STEP-003·005(노트·마감 알림) opus, STEP-006 화면 sonnet 병렬.
- RL-02: 7/7 done, 최종 리뷰 BLOCKING(대표 연결) 결정 #18·#21로 해소(spec accept), 커밋 b20b5f5·559921a, 배치 통합 26c3b42.

## 배치 최종 검증 (2026-10-17, 배치 HEAD 26c3b42)

- 세 기능 plan 증명 명령 합집합을 최종 코드에서 1회: tests 498 passed·121 skipped(PG)·2 deselect(main c93da20에서도 실패), postgres:17.11 312 passed(test_module_boundaries·test_runtime_database_privileges·test_alembic_autogenerate 포함), frontend build·contrast 8/8·Playwright 150 + company-layout 20, doctor exit 0. 로그 `logs/BATCH-*`.
- RL-00·01 proof를 배치 로그로 재연결(RL-02 통합으로 stale), RL-02는 기능 브랜치 증거가 배치 코드와 같음.
- 독립 리뷰: 기능별(RL-00·01) + RL-02/배치 최종 1회, `run _ review` 기록.
- 실제 스택: bidops-local `bidops_rla`(head 0039)에서 RL-00 등록, RL-01 T12(--send 제외), RL-02 활동·노트·화면 확인. `rla-web` 127.0.0.1:18797 유지 중(검토용, 이미지 rl02).
- 결정 기록: `decisions.md` #1~#21.
- 기존 무관 실패: backend test_api_opportunities 2건·test_postgres_harness 1건·test_daily_lifecycle_script 18건(macOS), frontend design-shell 2·admin-workspace-consistency 2·route-context 12, bid-delta request_id flaky 1.

## main 반영 전 확인 항목

1. 커밋 범위: 배치 `sdlc/batch-rla-20261016`(c93da20..HEAD) — RL-00·01·02 기능 커밋·merge와 run 기록. ff-only로 main에 반영된다.
2. main 작업 트리: 미추적 회차 2개는 `.git/info/exclude`로 가려져 있다(파일은 그대로). 반영 뒤 원하면 exclude 줄을 지운다.
3. 운영 영향: migration 0038·0039, 새 compose profile `slack`·overlay, 새 설정 키(`BIDOPS_COMPANY_EXPIRY_WARNING_DAYS`, `BIDOPS_BRIEFING_POLICY_PATH`, `BIDOPS_SLACK_*`). 운영 배포·migration·cron·Slack 토큰은 별도 승인(이번 범위 밖).
4. Rootlab fixture는 Git 밖(`~/orca/fixtures/company/rootlab/`, v1·v2). 운영 등록은 operations.md "회사 근거 갱신"대로 별도 승인.
5. 미증명: 실제 Slack 전송·Socket Mode, 마감 알림 실제 스택. backlog는 decisions #8·#9·#10·#16·#17·#20.

