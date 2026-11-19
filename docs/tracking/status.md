# 구현·검증 현황

기준일: 2026-10-21. 현재 소스·기능 상태·저장된 실행 증거를 대조했다. 운영은 마지막 확인 기록인 2026-10-19를 기준으로 하며 이번 문서 갱신에서 서버 상태·모델을 재실행하지 않았다.

## 현재 요약

| 범위 | 확인된 상태 | 근거·남은 경계 |
|---|---|---|
| 코드·DB | main에 RL-00~05 구현과 엔진 통합(RL-09 mock_reference), 코드 head `0042_engine_run` | `app/core/db.py`, migration 0042, 각 기능 status.json |
| Mac 운영 | 11월 19일 main `cfc5942`·0042·이미지 `main-20261119` 배포, **C-2 v6(상위 150건) active·일일 ON**(게이트 두 pass 통과: recall 96.3%·precision 45.6%·중요 누락 0·하루 검토량 59, v5 retired), analysis-worker 기동(restart `no`). 발주계획 11-04~11-17은 v5, 11-18은 v6로 C-2 판정(11-18: 621건 중 150건 판정, 관련 49·불확실 35), 공고 11-04~11-18 수집·적재. cron 11-19 설치(공고 06:30·발주계획 07:00, 첫 cron 실행은 11-20), analysis-worker `unless-stopped` | [C-2 Top150 배포·게이트](../validation-runs/20261119-c2-top150/README.md), [일일 트랙 보강 배포·따라잡기](../validation-runs/20261118-launch-hardening-deploy/README.md), [checkout 이전](../validation-runs/20261118-ops-main-move/README.md). 평일 실제 규모(427~627건/일)의 C-2 품질은 미측정. 이후 main 변경이 운영에도 배포됐다고 추정하지 않음 |
| 개요·RL 운영 스위치 | 마지막 기록상 개요·상시 첨부 worker 꺼짐, RL 분석 false | 운영 회사 근거·브리핑 미등록. 코드 배포는 RL 활성화가 아님 |
| 사전규격 1단계 | 브랜치 `feat/prespec-stage-phase1`(2026-11-19, 미병합·미배포): 자동 처리 범위(마감 전·미확인 또는 추적 중), `검토할 항목`·`확인 필요` 술어와 workload 키 `pre_spec_actionable`·`pre_spec_needs_check`, 다음 행동 `개요 확인`·`개요 확인 필요`, 기존 심층 검토·C-1 등급의 화면 제거, compose 정책 경로 공유. 격리 테스트(PostgreSQL 변형 포함)·화면 spec | [수정안](../1118_launch-hardening/사전규격-단계-수정안.md) §9. 상시 첨부 worker → 개요 경로는 실제 스택에서 증명 전, 개요 플래그·첨부 worker는 운영에서 꺼진 채(켜기는 [절차](../operations/prespec-reference.md) 승인 대상) |
| RL-00~02 | 실회사 근거·브리핑/Slack·활동/노트 구현·격리 검증 | [RL-00](../validation-runs/2026-10-16-rl/RL-00/README.md), [RL-01](../validation-runs/2026-10-16-rl/RL-01/README.md), [RL-02](../validation-runs/2026-10-16-rl/RL-02/README.md) |
| RL-03 | 카드 판정 구현, import 기본 정책 v11, 실제 실행 기록 있음 | [RL-03](../validation-runs/2026-10-17-rl/RL-03/README.md). 회사 대조 품질은 아래 RL-05 결과로 구분 |
| RL-04 | 초안·문장 수정·검토·PDF 구현. 실제 1건 `partial`(4/6절 완료) | [RL-04](../validation-runs/2026-10-17-rl/RL-04/README.md). 실적·운영 절은 식별자 참조 검증 실패, 품질 합격 아님 |
| RL-05 | 평가·사람 결정 절차 완료, **인수 reject**(10월 20일) | [RL-05](../validation-runs/2026-10-19-rl/RL-05/README.md). 판정 일치 3/10, 차단 조건 recall 0/7, 카드 일치 84/100이나 모델 카드 447개 모두 unknown |
| RL-06·07 | `review`, 각각 0/4·0/6 STEP | [로드맵](../work/constitution/roadmap.md). 최적화·판정 UX 구현 전, 대조 품질 개선과 별개 |
| RL-10 | 대조 규칙 v2(상주 장소·제외 분야 차단)·정책 v12 구현, 브랜치 `feat/rl03-compare-blockers`(2026-11-19, 미병합·미배포·DB import 없음) | [spec](../work/groups/RL/features/RL-10-compare-blockers/spec.md), [탐침 재생](../validation-runs/20261119-rl10-compare-blockers/README.md). 회사 근거 v4 그대로는 놓친 차단 0/7 그대로 — 구조화 회사 값 확인과 gold 재측정(승인 대상) 전이며 품질 근거 아님 |
| 미구현 | 입찰 delta 계산 worker, 첨부 실패·묶음 failed 재시작 화면, 인증/SSO | 문서 준비·Slack 경로·최종 결정 저장/REST까지 미구현인 것으로 확대하지 않음 |

### 상태 파일과 큐의 해석

RL-00~05의 저장된 phase는 `done`이다. `feature_status.py queue _ show`는 현재 source/spec hash와 완료 증거를 검사하므로 저장된 phase와 다르게 `validating`을 표시할 수 있다. 2026-10-21 문서 대조에서 HP-00·01과 RL-00~05는 CLI의 유효 상태가 `validating`이다. 문서 변경 뒤의 유효 상태는 CLI로 다시 확인한다. 이번 작업은 상태·큐·proof를 수정하거나 과거 검사를 새로 통과한 것으로 기록하지 않는다.

`done`은 작업 절차 완료이고 인수 합격과 같지 않다. RL-05의 `real_data_run=pass`는 실제 평가·사람 결정이 수행됐다는 증거이며, 그 결정은 **reject**다. 후속은 [findings](findings.md)의 대조 범위 문제와 [실행 계획](../PLAN.md)을 따른다.

## 다음 작업과 미검증 범위

- RL 회사 대조: 실제 gold의 차단 조건을 놓치는 문제를 명세·규칙·근거 연결부터 보완한다. [문제 색인](findings.md), [온톨로지 조사](../research/2026-10-20-bidops-ontology-assessment.md).
- RL-06·07: [실행 계획](../PLAN.md)과 기능 큐의 의존·검토 조건을 따른다. 문서 갱신은 착수 승인·인수 합격을 대신하지 않는다.
- 운영 전환: 회사 근거 등록·브리핑/Slack·정책 승인·실제 전송은 [RL 운영 절차](../operations/rl.md)에서 각각 확인한다.
- 첨부 변환·자동 준비·기존 개요 경로의 미해결 문제는 [findings](findings.md)에 최종 관측일과 함께 남긴다. 과거 관측을 현재 재현으로 간주하지 않는다.

## 시점별 증거

| 범위 | 실행 기록 |
|---|---|
| Mac 이전·C-2 v5 측정 | [2026-10-14](../validation-runs/20261014-c2-mac-v5-gate/README.md) |
| RL 운영 배포 | [2026-10-19](../validation-runs/20261019-ops-rl-rollout/README.md), main 이전 [2026-11-18](../validation-runs/20261118-ops-main-move/README.md) |
| RL 기능·실제 인수 | 위 현재 요약의 RL-00~05 링크 |
| 과거 PDF·회사 핏의 제한된 참조 인수 | [PDF 선행](../validation-runs/20260908-prespec-pdf-preflight.md), [회사 핏](../validation-runs/20260908-prespec-company-fit.md) |
| 나머지 실행 | [validation-runs](../validation-runs/)의 날짜·환경·입력·결과를 함께 확인 |

과거 변경 일지·당시 미배포 목록·검사 수치는 이 파일의 git 이력에서 찾는다. 정리 전 기준은 `git show b5a61e4:docs/tracking/status.md`다. 과거 코드·mock·참조 실행 결과는 현재 제품 인수나 정책 활성화 근거로 승계하지 않는다.
