# BidOps 실행 계획

기준일: 2026-11-28. 현재 목표는 [mission](work/constitution/mission.md)의 루트랩 실회사 AX 과제다. 기능 명세·상태는 `docs/work/groups/RL/features/*`, 순서·직접 의존은 `docs/work/queue.json`이 정본이다. 이 문서는 현재 착수 경계와 근거를 연결하며 별도 실행 큐를 만들지 않는다.

## 현재 기준선

| 범위 | 확인된 결과 | 근거 |
|---|---|---|
| C-2 제품화·일일 실행 | 제품 adapter·DB·API·worker·화면·정책·품질 게이트 구현. v4는 WSL2 이력, v5는 retired, Mac 운영은 v6 | [일일 운영 결정](specs/0918_daily-operation/plan.md), [ADR-0072](tracking/decisions/0072-c2-mac-litellm-ollama.md) |
| C-2 v6 품질 | 2026-11-19 두 pass 게이트 통과. recall 96.3%, precision 45.6%, 중요 누락 0, 하루 검토량 59 | [C-2 Top150 기록](validation-runs/20261119-c2-top150/README.md). PoC 기준이며 새 정책에 승계하지 않음. v5 측정은 git 이력(`docs/validation-runs/20261014-c2-mac-v5-gate/README.md`) |
| RL-00~02 | 회사 근거·브리핑/Slack·타임라인 구현·격리 검증 | [현황](tracking/status.md), 각 기능 status.json |
| RL-03 | 카드 추출·회사 대조·역할 판단·종합·화면 구현. RL-10의 정책 v12(대조 규칙 v2)는 main에 병합됐고 운영 DB import 기록은 없다 | 실제 실행(`docs/validation-runs/2026-10-17-rl/RL-03/README.md`, git 이력), `app/core/config.py` |
| RL-04 | 제안서 6절·수정·검토·PDF 구현. 실제 1건은 partial(4/6절 완료) | 초안 실행(`docs/validation-runs/2026-10-17-rl/RL-04/README.md`, git 이력) |
| RL-05 | 평가·사람 결정 완료, 인수 reject | [인수 결과](validation-runs/2026-10-19-rl/RL-05/README.md): 판정 일치 3/10, 차단 조건 recall 0/7 |
| 엔진·회사 핏 | RL-11 1~3단계(추적 시작·`분석 요청`·공고별 미리보기 승인, ADR-0078), 엔진 live(Responses API, ADR-0081), 회사 핏 감사 모드(카드 v1.2 + v3.1 + 로컬 Qwen, ADR-0080), migration 0045~0047 | [엔진 live·회사 핏 운영 배포](validation-runs/20261127-engine-live-prod/README.md), [회사 핏 측정](validation-runs/20261127-company-fit-probe/README.md) |
| 운영 배포 | 11월 27일 `bidops:main-20261127-d812377`·DB 0047. C-2 v6 active·일일 ON, 개요 ON, 회사 핏 `suggest`(11-27 21:15 KST 이후 수집분만), 엔진 live 시운전 상한 하루 1건·8회·$1, RL 분석 false. 상시 운영은 필요 없다고 사용자가 결정했고 cron 제거 예정 | 같은 운영 배포 기록. 운영은 Mac 전용 |

기존 C-2 Phase 0~5의 완료된 구현 계획·과거 실패 기준선은 git 이력에서 찾는다. C-2 계약과 결정은 [contracts](contracts.md), [ADR-0037](tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md), [ADR-0060](tracking/decisions/0060-c2-policy-db-row-authority.md), [ADR-0061](tracking/decisions/0061-daily-collection-window.md)에 유지한다. 기존의 P5-0 회귀 수정·gold 승인 대기를 현재 착수점으로 반복하지 않는다.

## 등록된 다음 작업

먼저 다음 읽기 전용 명령으로 상태를 확인한다.

```bash
python3 scripts/feature_status.py queue _ show
python3 scripts/feature_status.py doctor _
```

- RL-07 판정 UX: `review`, 0/6 STEP. 주의 포인트·판정 요약·사람 확인 항목·근거 연결·1280 배치·브리핑 진입 개선. [기능 계획](work/groups/RL/features/RL-07-verdict-ux/plan.md) 범위이며 회사 대조 알고리즘은 바꾸지 않는다.
- RL-06 로컬 LLM 최적화: `review`, 0/4 STEP. RL-04·03·05 의존과 품질 인수 실패를 확인한 뒤 착수한다. 모델 교체나 운영 전송은 이 문서 갱신으로 승인되지 않는다.
- RL-11 실제 사전규격 엔진: 추적 시작 진입·미리보기 승인·live 전송은 main과 운영에 있다. 남은 것은 품질 측정(사람 채점 표본)과 상한 상향 결정이다. [명세와 계획](work/groups/RL/features/RL-11-live-prespec-engine/plan.md)의 현재 상태는 실행 큐에서 확인한다.
- 회사 핏(PS-01): 사용자 사람 판정 40건 대조에서 낮게 나왔다(11-26 12/22, 처음 보는 11-25 8/18·`matched` 정밀도 1/4). 수동 추천 모드를 유지하고, 사람 판정이 더 쌓인 뒤 카드 v1.3과 `auto_request` 전환을 다시 잰다.
- 큐의 유효 단계는 저장된 `phase=done`과 다를 수 있다. `queue _ show`가 현재 입력에 대한 증거를 검사하기 때문이다. 옛 run 기록(`docs/work/_runs/`)은 git 이력에 있으며, 소스 동일성과 변경 범위에 맞춰 증거를 재사용한다. 문서 수정만으로 제품 테스트·실제 호출을 반복하지 않는다.

## 인수 실패와 후속 명세가 필요한 작업

| 문제 | 확인된 입력·결과 | 후속 경계 |
|---|---|---|
| 카드 판정의 회사 대조 범위 | 실제 사전규격 10건, v11 완료 10건. 모델 차단 unit 0, 카드 447개 전부 unknown | 원문 요구와 confirmed 회사 사실의 개념 연결·범위를 보완한 뒤 같은 gold 재측정. 새 명세·정책/계약 변경과 전송 승인을 별도로 정함 |
| 제안서 식별자 참조 | 실제 1건의 track_record·operations_sla 절이 `proposal_section_invalid` | 긴 unit/fact 식별자의 출력 계약 개선 후보. 실패 응답을 보정해 성공으로 만들지 않음 |
| 운영 RL 전환 | 코드·스키마는 배포했지만 회사 근거·브리핑 미등록, 분석 false | 실회사 등록·승인 정책·runner·브리핑/Slack 설정·감독 검증·활성화를 각각 구체화 |
| 입찰 delta·첨부 실패 복구 | delta 저장/REST/화면은 존재, 계산 worker 없음. 첨부 실패·묶음 failed 재시작 UI 없음 | RL 이후 별도 기능화. 현재 미구현 사실 유지 |

문제의 재현·영향은 [findings](tracking/findings.md), 제품 요구는 [PRD](PRD.md), 전송·기동·백업·복구는 [operations](operations.md)를 따른다. 인수 실패를 화면 개선이나 로컬 모델 최적화 완료로 해소한 것으로 기록하지 않는다.

## 검증과 종료 기준

| 변경 범위 | 확인할 것 | 증거 위치 |
|---|---|---|
| 이번 문서 정합성 | 소스·상태·운영/실제 실행 기록 대조, 분리 본문 보존·삭제 참조·링크·diff, doctor | 변경 문서와 기존 validation-runs 링크. 앱 빌드·테스트·배포 없음 |
| RL-07 | 해당 plan의 화면 동작·의미·1280×800/1440×900 구조, build·대비 | 기능 plan·status의 proof |
| 회사 대조 후속 | 원문 locator·confirmed/unknown 보존·차단 조건, 같은 gold 지표와 사람 결정 | 새 기능의 검증 계획과 불변 평가 산출물 |
| 운영 전환 | 백업·롤백·migration·환경 플래그·실제 API·감독 실행 | 승인받은 배포 기록 |

관련 검사가 통과하면 종료한다. 미검증 항목·실패·skip은 숨기지 않고, 작업 완료·모델 처리 완료·품질 인수·운영 활성화를 구분한다. commit·merge·push와 운영 변경은 현재 세션의 명시적 승인 범위를 따른다.
