# 구현·검증 현황

RL 기능·인수 증거의 기본 대조일은 2026-10-21이다. 운영과 최근 병합 상태는 2026-11-20에 Git, 운영 조회 API, 컨테이너 상태, 일일 실행 로그를 대조했다.

## 현재 요약

| 범위 | 확인된 상태 | 근거·남은 경계 |
|---|---|---|
| 코드·DB | main에 RL-00~05 구현과 엔진 통합(RL-09 mock_reference), 코드 head `0042_engine_run` | `app/core/db.py`, migration 0042, 각 기능 status.json |
| Mac 운영 | web·analysis-worker는 이미지 `bidops:main-20261120-b839367`, DB revision은 `0042_engine_run`이다. **C-2 v6(상위 150건) active·일일 ON**. 11월 20일 첫 공고 cron은 exit 0(적재 경고 440건), 발주계획 cron은 PPSSrch 발주월 범위 거부로 실패했다. 호스트 수집기 수정(`ff17936`) 뒤 11:10 재실행에서 11월 19일치 557건을 수집·적재하고 150건을 판정했다(경고 0건·감사 표본 10건·11-04~11-19 누락 없음·exit 0) | [운영 이미지 배포](../validation-runs/20261120-prespec-stage1/README.md), [C-2 Top150 배포·게이트](../validation-runs/20261119-c2-top150/README.md). v6 게이트 두 pass 통과(recall 96.3%·precision 45.6%·중요 누락 0·하루 검토량 59). 평일 실제 규모(427~627건/일)의 품질은 미측정 |
| 관리 화면(2026-11-24) | 운영 web은 `bidops:table-workbench-fe-20261124`다: 직전 web 이미지에 표 작업대 화면(ADR-0077, main `1d85c1b`)의 프런트엔드 번들만 교체했다. DB `0042_engine_run`·백엔드·worker는 그대로다 | 회사 근거 화면은 `/api/company-wiki`가 운영 백엔드에 없어 "불러오지 못했어요"로 나온다. main `c660e72`의 백엔드 변경과 migration 0043은 미검증·미배포다. 운영에서의 쓰기 동작은 눌러 보지 않았다. [배포 기록](../validation-runs/20261124-table-workbench-frontend/README.md) |
| 개요·RL·엔진 운영 스위치 | 상시 첨부 worker와 로컬 개요가 동작 중이다. RL 분석·엔진 플래그는 `false`다 | 마지막 기록상 운영 회사 근거·브리핑 미등록 |
| 사전규격 1단계 | `1aceb5e`에서 병합한 코드를 11월 20일 운영 이미지에 배포했다. 워커 권한과 LiteLLM 메타데이터 보강 뒤 실제 공고 `R26BD00303364`의 새 첨부 → 변환 → 개요 완료 → `검토할 항목`을 운영 브라우저에서 확인했다 | 시운전에서도 장문 입력 초과가 발생했다. 첫날 전체 처리율, 다음 자동 C-2 실행과의 간섭, 원문과 개요의 사람 대조는 미확인이다. [운영 절차](../operations/prespec-reference.md), [실행 기록](../validation-runs/20261120-prespec-stage1/README.md) |
| RL-00~02 | 실회사 근거·브리핑/Slack·활동/노트 구현·격리 검증 | [RL-00](../validation-runs/2026-10-16-rl/RL-00/README.md), [RL-01](../validation-runs/2026-10-16-rl/RL-01/README.md), [RL-02](../validation-runs/2026-10-16-rl/RL-02/README.md) |
| RL-03 | 카드 판정 구현, import 기본 정책 v11, 실제 실행 기록 있음 | [RL-03](../validation-runs/2026-10-17-rl/RL-03/README.md). 회사 대조 품질은 아래 RL-05 결과로 구분 |
| RL-04 | 초안·문장 수정·검토·PDF 구현. 실제 1건 `partial`(4/6절 완료) | [RL-04](../validation-runs/2026-10-17-rl/RL-04/README.md). 실적·운영 절은 식별자 참조 검증 실패, 품질 합격 아님 |
| RL-05 | 평가·사람 결정 절차 완료, **인수 reject**(10월 20일) | [RL-05](../validation-runs/2026-10-19-rl/RL-05/README.md). 판정 일치 3/10, 차단 조건 recall 0/7, 카드 일치 84/100이나 모델 카드 447개 모두 unknown |
| RL-06·07 | `review`, 각각 0/4·0/6 STEP | [로드맵](../work/constitution/roadmap.md). 최적화·판정 UX 구현 전, 대조 품질 개선과 별개 |
| RL-10 | 대조 규칙 v2(상주 장소·제외 분야 차단)와 정책 v12를 main `fda8522`에 병합했다. 배포·DB import는 대기 중이다 | 회사 근거 v4에서는 놓친 차단 7건이 그대로다. 구조화 회사 값과 승인된 gold 재측정이 남았다. [spec](../work/groups/RL/features/RL-10-compare-blockers/spec.md), [탐침 재생](../validation-runs/20261119-rl10-compare-blockers/README.md) |
| 관리 화면 UI 재구성 | 셸·패널 헤더·해요체 문구·읽기 전용 수집 기준일 API(`c5e4b6b`)와 헤더 압축·설명 줄 제거·패널 밀도 조정(`fb3b26b`)을 11월 20일 운영에 배포했다. 발주계획 검색 초안 유지 수정(`b839367`)도 포함했다 | 승인 시안과 캡처는 `docs/1119_kstyle-shell/`에 있다. [ADR-0076](decisions/0076-kstyle-panel-shell.md) |
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
