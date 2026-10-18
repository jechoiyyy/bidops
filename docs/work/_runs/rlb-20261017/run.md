# run rlb-20261017 — RL 배치 B (RL-03·04)

- 승인: 2026-10-17 사용자("1. merge해줘 2. 승인할게 3. RL-03,04를 진행하기 위한 것들을 정리해서 인터뷰형식으로…") + 인터뷰 기록 `docs/work/groups/RL/batch-b-interview.md`(전송 범위·상한·정지 조건). commit_policy=manual이나 사용자가 이전 run에서 기능 커밋·배치 통합을 요청했으므로 같은 방식으로 진행하고 main 반영은 별도 확인.
- 기준: main `9c61fe1` + 인터뷰·spec 개정 커밋.
- 선택 결정은 권장안으로 진행하고 `decisions.md`에 기록(사용자 지시 2026-10-17).

## 격리·지킬 것

- bidops-local 안 DB `bidops_rla`와 서비스 `rla-*`(overlay `.sdlc/local-runtime/rla-20261016/`), 일회용 postgres:17.11. 운영 `bidops` 스택·DB·cron·origin push 금지. 기존 bidops-local web·runner·`bidops` DB 덮어쓰지 않음.
- 실제 Luna 호출: RL-03 T12(폴리텍 1건, 재시도 1) + RL-04 T11(초안 1건)뿐. 자동 트리거는 실제 스택에서 꺼짐. 실제 호출·정책 승인 CLI·runner 재배포 직전에 짧게 알림.
- 정지 조건: 인터뷰 기록 "정지 조건" 절.

## 기능 worktree

| 기능 | 브랜치 | 경로 |
|---|---|---|
| RL-03-fit-verdict | `sdlc/rlb-20261017-RL-03-fit-verdict` | `.sdlc/worktrees/rlb-20261017-RL-03-fit-verdict` |
| RL-04-proposal-draft | `sdlc/rlb-20261017-RL-04-proposal-draft` | `.sdlc/worktrees/rlb-20261017-RL-04-proposal-draft` |

## 진행 기록

- RL-03: STEP-001~010 done, validating. 기능 커밋 `c70b299`, 배치 통합 `dc133b6`(no-ff, 충돌 없음). 증명 docs·tests·postgres·frontend·api_guard pass, **real_data_run pending**(실제 Luna T12 1~7차 판정 미획득, 사용자 결정 B37 옵션 B). 상세 `RL-03-fit-verdict.md`, 결정 B1~B39.
- 실제 호출 범위 변경: 인터뷰 D10(1건+재시도 1) 뒤 사용자 추가 승인 B29·B32·B33·B35로 attempt 4~7 실행, 모델 호출 합계 8회. B37 이후 `bidops_rla` 활성 전송 승인 없음, runner 정지. 이번 배치에서 실제 호출 없음 → RL-04 T11(실제 초안) 보류.
- 설정: `proof.real_data_run.dependency_gate=false`(B38) — RL-04 구현은 진행, `run finish`·main 병합은 두 기능 real_data_run이 막음.
- RL-04 착수 전: RL-00·RL-02 증거가 RL-03 코드·B38 설정으로 stale → 배치 HEAD에서 재검증해 다시 연결(B40, `9ae53ec`).
- RL-04: STEP-001~009 done, validating. 기능 커밋 `d0130ed`, 배치 통합 `adc00b8`(no-ff, 충돌 없음). 증명 docs·tests(206)·postgres(122)·frontend(102)·api_guard(52) pass, **real_data_run pending**(T11 실제 초안은 RL-03 실제 판정이 없어 보류). T10 mock 전 경로는 bidops-local `bidops_rla_t11`에서 통과. 사용자 결정 B48(PDF namespace `proposal-pdf`와 설정 키 2개). 상세 `RL-04-proposal-draft.md`, 결정 B40~B50.

## 배치 최종 검증 (2026-10-18, 배치 HEAD `adc00b8`)

- RL-03 자동 증명을 배치 최종 코드에서 한 번 다시 실행해 연결: tests 293·postgres 162·frontend 192(7 spec)·api_guard 57 pass, doctor 0. RL-04 증명은 통합 전 기능 브랜치 트리와 배치 트리가 같아 그대로 유효.
- 최종 독립 리뷰: B50(RL-04 + 배치 전체 diff). 차단 2(검토 뒤 재생성, 기록) 해소, 비차단은 백로그.
- `check`: RL-03·RL-04 모두 **real_data_run: pending**만 남음 → `run finish`·main 병합 불가(merge_policy manual). 완료로 표시하지 않음.
- main 반영 전 확인 항목: (1) RL-03 실제 판정 — 항목 단위 실패 설계(findings) 뒤 사용자 승인 하에 재시도 (2) RL-04 실제 초안 1건 (3) **운영 env에 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY` 추가와 minio-init 재실행**(compose `:?`, B49) (4) migration head `0041_proposal_draft` 운영 반영은 백업·롤백 태그 뒤 사람 확인.
- 격리 스택 최종 상태: `bidops_rla` 활성 전송 승인 없음, runner·analysis worker 정지, rla-web은 rl04 이미지로 `bidops_rla_t11`(mock) 연결. bidops-local MinIO에 `bidops-proposal-pdf` 추가.
