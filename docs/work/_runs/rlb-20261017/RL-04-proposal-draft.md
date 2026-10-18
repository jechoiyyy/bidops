# RL-04-proposal-draft 실행 기록 (run rlb-20261017)

- 기능 worktree: `.sdlc/worktrees/rlb-20261017-RL-04-proposal-draft`, 브랜치 `sdlc/rlb-20261017-RL-04-proposal-draft`, 기준 배치 `dc133b6`(RL-03 통합 후).
- 착수 전: 배치 A에서 done인 RL-00·RL-02 증거가 RL-03 코드·B38 설정으로 stale → 배치 HEAD에서 재검증해 다시 연결(B40, 커밋 `9ae53ec`).
- 단계: STEP-001~009 done. 상태 validating(최종 done은 배치 통합·real_data_run 뒤).
- 결정: B40~B50(`decisions.md`). 사용자 결정: B48(PDF 객체 namespace `proposal-pdf`와 설정 키 2개 추가).

## 증명

| 키 | 결과 | 근거 |
|---|---|---|
| docs | pass | `logs/RL-04-proof-docs.log`(doctor 0) + 독립 리뷰 B50(차단 2 해소) |
| tests | pass | `logs/RL-04-proof-tests.log` 206 passed(33 skip = PG 변형 32 + 컨테이너 전용 1) |
| postgres | pass | `logs/RL-04-proof-postgres.log` 122 passed(postgres:17.11) |
| frontend | pass | `logs/RL-04-proof-frontend.log` build 0 + Playwright 102 passed + contrast 0 |
| api_guard | pass | `logs/RL-04-proof-api-guard.log` 52 passed(PG, skip 0) |
| real_data_run | **pending** | `docs/validation-runs/2026-10-17-rl/RL-04/README.md` — T11 실제 초안은 RL-03 실제 판정이 없어 보류(B37) |

## 격리 스택 mock 경로(T10)

`bidops_rla_t11`, 이미지 `bidops-local:rlb-20261017-rl04`: 초안 `38fc8ce5…` 6절 completed, 카드 27/27 연결, 문장 143·placeholder 12, 편집 → 6절 검토 → ready, export 두 번 같은 `1e874282…`(PDF 16쪽, `bidops-proposal-pdf` 저장), 재편집 뒤 새 export. 전송 감사 0, cap 사용 0, `mock_reference`. bidops-local MinIO에 `bidops-proposal-pdf` 버킷·사용자·정책·365일 보관을 추가(기존 버킷·사용자 무변경).

## 남은 위험

- 실제 초안 미생성(T11): RL-03 실제 판정이 먼저 필요하며, 그 전에 항목 단위 실패 설계(findings)가 선행 과제.
- **운영 반영 전제(B49):** main 병합 뒤 운영 스택을 다시 올리기 전에 운영 env에 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`를 넣고 minio-init을 다시 실행해야 한다(compose `:?`). 운영 변경은 사람 확인 대상.
- 백로그: 금지 패턴 확장(만원·천만원·"N명의 인력을 투입"), placeholder 금지 내용 검사, 현재가 아닌 판정 허용, PDF 표지 공고 메타의 overlay 포함, CI 부재, 죽은 품질 배지(`decisions.md` 백로그 절).
- 기존 실패(배치 HEAD에서도 동일): `test_api_opportunities` 2, `test_postgres_harness::test_profile_target_runs_without_docker` 1.
