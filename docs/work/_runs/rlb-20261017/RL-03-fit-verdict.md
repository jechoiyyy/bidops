# RL-03-fit-verdict 실행 기록 (run rlb-20261017)

- 기능 worktree: `.sdlc/worktrees/rlb-20261017-RL-03-fit-verdict`, 브랜치 `sdlc/rlb-20261017-RL-03-fit-verdict`, 기준 `36f2b1a`.
- 단계: STEP-001~010 done. 상태 validating(최종 done은 배치 통합·real_data_run 뒤).
- 결정: B1~B39(`decisions.md`). 사용자 결정: B15(로컬 원본 CLI), B29·B32·B33·B35(실제 호출 추가 승인), B37(옵션 B: 실제 증명 pending으로 마무리).

## 증명

| 키 | 결과 | 근거 |
|---|---|---|
| docs | pass | `logs/RL-03-proof-docs.log`(doctor 0) + 독립 리뷰 B39(코드 차단 0, 문서 차단 4 수정) |
| tests | pass | `logs/RL-03-proof-tests.log` 284 passed(16 skip = PG 변형) |
| postgres | pass | `logs/RL-03-proof-postgres.log` 156 passed(postgres:17.11) |
| frontend | pass | `logs/RL-03-proof-frontend.log` build 0 + Playwright 52 passed |
| api_guard | pass | `logs/RL-03-proof-api-guard.log` 57 passed(PG, skip 0) |
| real_data_run | **pending** | `docs/validation-runs/2026-10-17-rl/RL-03/README.md` T12 1~7차, findings 항목 |

## 실제 Luna(T12) 요약

| 차수 | 정책 | 결과 | 원인 → 조치 |
|---|---|---|---|
| 1 | v2 | processing_failed(전송 0) | runner 주소 → B25 |
| 2 | v2 | runner_failed | 진단 은폐 → B27 |
| 3 | v2 | card_extract_invalid | `uniqueItems` 거부 → B28 |
| 4 | v2 | card_extract_invalid | 검증 계약 미전달·목차 unit → B30(v3) |
| 5 | v3 | card_extract_invalid | 제약 1개 kind×unit → B33(v4·추출 계약 v2) |
| 6 | v4 | batch 0 통과, batch 1 실패 | 잘린 인용 + 조용한 eq 발견 → B35·B36(v5) |
| 7 | v5 | card_extract_invalid | 기간 계산(모델) + 검증기 결함 2 → B37(v6, 실제 호출 없음) |

## 남은 위험

- 실제 판정 미획득: 제약 하나가 판정 전체를 실패시키는 구조(항목 단위 실패 설계가 다음 과제).
- 백로그: 시간 단위 부재, `약` 부분 문자열 표지, T9 fixture CI 강제, runner 출력 크기 검사, `test_auto_preparation` findings 확인(`decisions.md` 백로그 절).
- 기존 실패(main에서도 동일): `test_auto_preparation` 13, HWP 변환 macOS 환경 실패 등 — 이번 변경과 무관.
