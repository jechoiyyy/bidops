# 구현·검증 현황

기준일: 2026-11-28. RL 기능·인수 증거의 대조일은 2026-10-21이고, 운영과 main은 2026-11-27 배포·시운전 기록과 Git으로 대조했다. 이 파일은 남겨 둔 기록만 링크한다. 그 밖의 실행 기록은 git 이력에 있다.

## 현재 요약

| 범위 | 확인된 상태 | 근거·남은 경계 |
|---|---|---|
| 코드·DB | main에 RL-00~05, 엔진 통합(RL-09), RL-11 1~3단계(추적 시작·`분석 요청`·공고별 미리보기 승인, ADR-0078), 엔진 live(ADR-0081), 회사 핏 감사 모드(ADR-0080, PS-01), 오늘 할 일 화면·포트폴리오 화면 개선이 있다. migration head `0047_company_fit_mode`(0045 `engine_review`·0046 `engine_live`·0047 모드 행) | 각 기능 status.json, [엔진 live·회사 핏 운영 배포](../validation-runs/20261127-engine-live-prod/README.md) |
| Mac 운영 | web·analysis-worker·첨부 worker는 `bidops:main-20261127-d812377`(main에서 빌드), DB `0047`. health·화면·사전규격·workload·수집 상태 200, 오류 로그 0줄을 교체 직후 확인했다 | 같은 기록. 백업·롤백 태그와 되돌리기 절차도 거기에 있다 |
| C-2 발주계획 | `c2-order-plan-screening-v6` active·일일 스위치 ON. 게이트 두 pass 통과(recall 96.3%·precision 45.6%·중요 누락 0·하루 검토량 59) | [C-2 Top150 배포·게이트](../validation-runs/20261119-c2-top150/README.md). 평일 실제 규모(427~627건/일)와 상위 150 밖은 미측정 |
| 회사 핏 | 카드 v1.2 + 프롬프트 v3.1 + 로컬 Qwen. 운영 모드 `suggest`, 2026-11-27 21:15 KST 이후 처음 수집된 공고만 판정한다. 그 전에 기존 공고 8건이 판정돼 감사 기록으로 남았다 | 품질은 아래 "품질" 행. `matched`는 추천 표시로만 쓴다 |
| 엔진 live | ON. 시운전 상한 하루 1건·8회·$1, 공고당 8회. 첫 감독 실행 1건(#4153): 호출 4회 모두 HTTP 200, $0.0562, `completed`·`unmeasured_reference`, 요구사항 57건. 사용자 판정 "맞아", 읽음 처리 | [운영 배포 기록](../validation-runs/20261127-engine-live-prod/README.md) P5~P8, [격리 시험(외부 전송 0)](../validation-runs/20261127-engine-live-trial/README.md), [토큰·비용 실측](../validation-runs/20261126-luna-token-cost/README.md). **1건 판정이라 품질 측정·인수가 아니다** |
| 상시 운영 | 사용자가 상시 운영이 필요 없다고 결정했다(2026-11-27). cron 제거 예정이며 공고 06:30·발주계획 07:00 두 줄은 아직 있다 | 제거는 사용자가 한다. 제거 전까지 운영 checkout의 `scripts/` 변경은 다음 날 실행을 바꾼다 |
| 회사 근거·관리 화면(2026-11-24) | 회사 위키를 읽는 회사 근거 화면과 표 작업대 화면(ADR-0077)이 운영에 있다. 실적 넣기 스위치는 꺼져 있다 | [백엔드 검증·배포](../validation-runs/20261124-company-wiki-backend/README.md). 당시 전체 스위트는 4,258 통과·190 실패였고 실패 목록이 같은 폴더에 있다 |
| RL-00~02 | 실회사 근거·브리핑/Slack·활동/노트 구현·격리 검증 | 기록은 git 이력(`docs/validation-runs/2026-10-16-rl/`). 운영 회사 근거·브리핑은 미등록 |
| RL-03 | 카드 판정 구현. RL 분석은 운영에서 꺼져 있다 | 기록은 git 이력(`docs/validation-runs/2026-10-17-rl/RL-03/README.md`). 회사 대조 품질은 RL-05 결과로 본다 |
| RL-04 | 초안·문장 수정·검토·PDF 구현. 실제 1건 `partial`(4/6절 완료) | 기록은 git 이력(`docs/validation-runs/2026-10-17-rl/RL-04/README.md`). 품질 합격 아님 |
| RL-05 | 평가·사람 결정 절차 완료, **인수 reject**(10월 20일) | [RL-05](../validation-runs/2026-10-19-rl/RL-05/README.md). 판정 일치 3/10, 차단 조건 recall 0/7, 모델 카드 447개 모두 unknown |
| RL-06·07 | `review`, 각각 0/4·0/6 STEP | 구현 전 |
| RL-10 | 대조 규칙 v2와 정책 v12를 main에 병합했다(`fda8522`). 정책 v12의 운영 DB import 기록은 없다 | 놓친 차단 7건은 회사 근거 v4에서 그대로다. [spec](../work/groups/RL/features/RL-10-compare-blockers/spec.md) |
| 미구현 | 입찰 delta 계산 worker, 첨부 실패·묶음 failed 재시작 화면, 인증/SSO | 문서 준비·Slack 경로·최종 결정 저장/REST까지 미구현으로 넓히지 않는다 |

### 품질

| 대상 | 결과 | 해석 |
|---|---|---|
| 회사 핏 | 사용자가 직접 판정한 40건 대조. 11-26 22건 12/22(카드 v1.2 + v3.1), 카드 작성 때 보지 않은 11-25 18건 8/18·`matched` 정밀도 1/4 | 낮다. 추천 표시로만 쓰고 자동 분석 요청에 쓰지 않는다. 이 대조의 상세 기록은 아직 저장소에 커밋되지 않았다. Claude 판정을 일괄 채택한 gold v2 기준 수치(17/22, 제품 경로 14/22)는 사람 기준으로 성립하지 않는다 |
| 엔진 | 운영 1건 사용자 판정 "맞아" | 미측정 |
| RL 카드 판정·제안서 | RL-05 reject, RL-04 partial | 그대로 |
| C-2 v6 | gold v3 게이트 통과 | PoC 임계값 기준이다. 실제 하루 규모는 미측정 |

### 상태 파일과 큐의 해석

RL-00~05의 저장된 phase는 `done`이다. `feature_status.py queue _ show`는 현재 source/spec hash와 완료 증거를 검사하므로 저장된 phase와 다르게 `validating`을 표시할 수 있다. HP-00·01과 RL-00~05는 CLI의 유효 상태가 `validating`이다. 문서 변경 뒤의 유효 상태는 CLI로 다시 확인한다. 이 문서 정리는 상태·큐·proof를 수정하지 않았다. status.json이 가리키는 옛 실행 기록 일부는 삭제돼 git 이력에만 있다.

`done`은 작업 절차 완료이고 인수 합격과 같지 않다. RL-05의 `real_data_run=pass`는 실제 평가·사람 결정이 수행됐다는 증거이며, 그 결정은 **reject**다. 후속은 [findings](findings.md)의 대조 범위 문제와 [실행 계획](../PLAN.md)을 따른다.

## 다음 작업과 미검증 범위

- 회사 핏: 사람 판정을 더 모은 뒤 카드 v1.3과 자동 요청 전환을 다시 잰다. `auto_request`는 구현·승인 전이다.
- 엔진: 상한 상향과 다음 시운전은 각각 사용자 결정이다. 품질 측정은 사람 채점 표본을 정한 뒤 한다.
- cron 제거: 사용자가 한다. 제거 뒤 일일 수집·C-2 판정은 사람이 필요할 때 수동으로 돌린다.
- RL 회사 대조: 실제 gold의 차단 조건을 놓치는 문제를 명세·규칙·근거 연결부터 보완한다. [문제 색인](findings.md).
- RL-06·07: [실행 계획](../PLAN.md)과 기능 큐의 의존·검토 조건을 따른다.
- 첨부 변환·자동 준비·개요 경로의 미해결 문제는 [findings](findings.md)에 최종 관측일과 함께 남긴다. 과거 관측을 현재 재현으로 보지 않는다.

## 시점별 증거

저장소에 남긴 기록은 다음 일곱 개다.

| 범위 | 기록 |
|---|---|
| RL-05 인수 | [2026-10-19](../validation-runs/2026-10-19-rl/RL-05/README.md) |
| C-2 v6 배포·게이트 | [2026-11-19](../validation-runs/20261119-c2-top150/README.md) |
| 백엔드 검증 환경·회사 근거 배포 | [2026-11-24](../validation-runs/20261124-company-wiki-backend/README.md) |
| Luna 토큰·비용 실측 | [2026-11-26](../validation-runs/20261126-luna-token-cost/README.md) |
| 회사 핏 측정 | [2026-11-27](../validation-runs/20261127-company-fit-probe/README.md) |
| 엔진 live 격리 시험 | [2026-11-27](../validation-runs/20261127-engine-live-trial/README.md) |
| 엔진 live·회사 핏 운영 배포 | [2026-11-27](../validation-runs/20261127-engine-live-prod/README.md) |

과거 변경 일지·배포 기록·검사 수치는 git 이력에서 찾는다. 과거 코드·mock·참조 실행 결과는 현재 제품 인수나 정책 활성화 근거로 승계하지 않는다.
