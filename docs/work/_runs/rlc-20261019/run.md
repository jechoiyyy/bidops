# run rlc-20261019 — RL-05 gold 10건 대조 인수

- 승인: 2026-10-19 사용자 "운영 반영해주고, 필요한 부분들 준비하고 RL-05 시작해" → 계획 A(운영 반영)·B(RL-05 준비) 일괄 승인("A+B 일괄 승인 (권장)"), 표본 구성 "실제 수집 10건 (권장)". commit은 사용자 요청 방식대로 진행하고 main 반영(merge)은 별도 확인.
- 기준: main `ff8aa84`(C-2 Mac 병합 `b8005ef`, 운영 반영 기록 `ece3b08`, RL-00~04 증거 재연결 `cec9d94`·`ff8aa84`).
- 선택 결정은 권장안으로 진행하고 `decisions.md`에 기록(사용자 지시 2026-10-17).

## 범위와 정지

- 이번 승인 범위(B2·B3): STEP-001 gold 도구, STEP-002 export CLI, STEP-005 문서, STEP-003 준비(후보 목록·원본 연결 방식). 외부 호출 없음.
- **사람 단계에서 정지:** 10건 선정(STEP-003), 모델 출력 전 gold 작성, RL-03 실제 Luna 분석 10건(별도 승인), 최종 인수 decision.
- 격리: bidops-local `bidops_rla`·일회용 postgres:17.11. 운영 DB는 후보 목록 조회(REST 읽기)만. cron·origin push 없음.
- 회사 근거 §G(G1~G6)는 사용자 답변 대기 — 미확인 값은 unknown 유지.

## 기능 worktree

| 기능 | 브랜치 | 경로 |
|---|---|---|
| RL-05-gold-acceptance | `sdlc/rlc-20261019-RL-05-gold-acceptance` | `.sdlc/worktrees/rlc-20261019-RL-05-gold-acceptance` |

## 진행 기록

- 착수 전(main): C-2 병합으로 RL-00~04 증거 stale → plan 증명 합집합 1회 재실행·재연결(`docs/work/_runs/reverify-20261019/logs/`, tests 748·PG 301+27·api_guard 252·Playwright 194·doctor 0). RL-03·04 real_data_run은 RL 경로 무관 확인 뒤 2026-10-18 사용자 확인 결과를 재연결(C2).
- RL-05 STEP-001·002: 구현자 위임(standard/complex) → 리더 검증 rl-gold 50 passed, export·경계·트리거 PG 83 passed(skip 0). spec 정정 C7(사용자 승인)·accept-spec. 기능 커밋 `81084a4`.
- RL-05 STEP-003: 사용자 선정 10건(C6) 중 #56은 카드 0개라 #15로 교체(C8). bidops_rla에 `lifecycle-20261014-notices` 적재, 운영 객체 백업 원본(sha 일치) `attach-local-original` 13건, holdout 13행, RL review 0. Git 밖 `rl-evaluation-20261019/`에 selection·cards·blank gold·작성지(`worksheet/`). 모델 호출 0.
- 다음(사람): gold 작성(작성지) → gold-check → RL-03 실제 분석 10건(별도 승인) → export·alignment·score → 인수 결정. 회사 근거 §G를 먼저 반영하려면 gold 작성 전에 해야 함(binding sha가 바뀌면 selection·양식 재생성).
- 2026-10-19~20 회사 근거 §G: v3(G1·G3·G4·G2 나라장터 계약 7건)·v4(정보통신공사업) 등록·활성화(bidops_rla), selection·blank gold 재생성(C10·C12). Mac 재부팅으로 운영·격리 스택 재기동(사용자 확인).
- gold: Claude 초안 → 사용자 확인(C13), 차단 조건 gap만(C11), 확정 `gold.v1.json` 2026-10-20T07:02:40+09:00(sha `6c4ca154…`), RL review 0 상태에서 작성.
- 실제 분석(C14 승인): v9 승인 하루 15건 재승인(`517a762c…`), 요청 10건 중 3건 `input_budget_exceeded`(영역 unit 12,061·29,949·12,963자) → STEP-006(C15). 7건 중 4건 실패(역할 근거 키 오류 3, 추출 unit 누락 1) → 정지 조건으로 worker 정지, 원 응답 복호화 진단(호출 없음) → STEP-007(C16). v9 호출 합계: transfer 5건·원 응답 41건.
- 2026-10-20 v10(STEP-006·007, C15·C16) 전환: 정책 행 `a2fb9368…`, 승인 `9cfbd62a…`(15) → runner 인증 파일 누락으로 3건 authentication_failed(C17) → 승인 `691d0712…`(18, C18). 10건 결과: 완료 4(R26BD00284019·284697·284941·284956), 실패 6(종합 인용 축약 3·역할 caution 1 → STEP-008 C19, 역할 unit_id sha 축약 1·추출 텍스트 조건 비축자 26% 1 → STEP-009 v11 C20). 오늘 상한 18 소진, worker 정지.
- STEP-008 커밋 `eb8a8e9`. STEP-009(v11) 구현 중. 다음: v11 등록·승인(18/일) → 10건 v11 재분석(KST 다음 날).
