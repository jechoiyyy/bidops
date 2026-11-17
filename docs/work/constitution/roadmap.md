# BidOps roadmap

## RL — 루트랩 실회사 기준 AX 과제

2026-10-16 확정한 신규 목표다([ADR-0073](../../tracking/decisions/0073-rootlab-real-company-ax-redefinition.md), [재정의 초안](../../1016_rootlab-redefinition/draft.md)).
화면 정본은 [RL 화면 구현 명세](../../1016_rootlab-redefinition/ui-spec.md)(시안 v26, 2026-10-16)이며 RL-00~04 spec은 이를 인용한다. 상태의 정본은 기능 status.json, 순서·직접 의존의 정본은 queue.json이다. 아래 RL-00~07은 모두 intent·spec·plan 작성과 큐 등록을 마쳤다. 새 기능은 `/sdlc:feature <ID>`로 문서화한 뒤 등록하며, 등록 전 제안은 구현 사실이 아니다.

| 기능 | 목표 | 선행 요약 | 핵심 입력 |
|---|---|---|---|
| `RL-00-company-ground-truth` | 루트랩 실회사 1곳을 `is_fictional=false`로 등록. 프로필·실적·선호·자격을 출처·상태(`confirmed`/`proposed`/`unknown`)와 함께 버전 고정. 인터뷰 답 반영 절차 | 없음 | company-profile, homepage-profile, preferences, 인터뷰 A~F |
| `RL-01-daily-briefing` | 평일 1회 브리핑 생성(반복 발주처·연차 사업 규칙 → C-2·사전규격·입찰공고 후보 → 상위 N + 이유 3줄 + 차단 조건 + 마감)과 Slack bot 전송·화면, 채택/무시 피드백 저장. 브리핑은 결정적 규칙이라 LLM 호출이 없고 **Luna 정책 발행은 RL-03** | RL-00 | 수집 파이프라인, C-2 결과, 선호·제외 조건 |
| `RL-02-opportunity-timeline` | 발주계획→사전규격→공고→정정→마감을 사업기회 하나의 타임라인으로 묶고 상태 변화 때만 알림 | RL-01 | 기존 사업기회 연결·추적 상태 |
| `RL-03-fit-verdict` | 요구사항 카드·여섯 영역 unit 추출 → 결정적 회사 대조 → 역할별 판단·종합 → 실무자 판정 5블록 화면(HP-03·04 설계를 루트랩·정책 승인 전송으로 재명세). **1차 대상은 사전규격**(입찰공고는 문서 취득 경로가 없어 후속) | RL-00·01·02 (HP-01은 완료·재사용) | HP 공통 계약 §6~8, bid-procedure 자격 항목 |
| `RL-04-proposal-draft` | 요구사항 대응표 + 사업 이해·수행 방안·유사 실적 절 초안. 출력은 PDF(1차)·HWP(후속, 변환기 결정 필요). 과거 제안서는 없으므로(E1) 제안요청서 목차·회사 근거만으로 생성 | RL-03 | 인터뷰 E, bid-procedure 제안서 목차 |
| `RL-05-gold-acceptance` | 사용자 gold 10건 대조 인수(HP-06 기준 재사용) | RL-03 | **실제 수집 사전규격 10건**(fixture 4건은 DB 공고가 아니라 attempt 불가 → RL-03 테스트용; 폴리텍은 smoke 노출로 제외) |
| `RL-06-local-llm-optimization` | 기능 완료 뒤 토큰 최적화용 로컬 LLM 검토(사용자 Q3) | RL-04 | 호출 수·토큰 계측 |
| `RL-07-verdict-ux` | 판정 탭 실무자 화면 개선(프런트엔드 1차): 주의 포인트 블록·판정 한 줄 요약·코드 "사람 확인" 묶음·검증 실패↔표 연결·회사 근거 고정 문구·쪽 미확인 열 정리·1280 배치·브리핑 판정 직행. 서버·계약 불변(2026-10-20 RL-05 실데이터 독립 UX 검토) | RL-05 | HP 계약 §8, ui-spec §4.4 |

### 구현·인수 현황 (2026-10-21)

| 기능 | 저장된 `status.json` phase | 해석 |
|---|---|---|
| RL-00~02 | `done` | 회사 근거·브리핑·활동 피드 구현 및 격리 검증 기록 있음 |
| RL-03 | `done` | 카드 판정 구현·실제 실행 기록 있음. 품질 합격은 아님 |
| RL-04 | `done` | 초안·PDF 구현. 실제 1건은 `partial`(4/6절 완료) |
| RL-05 | `done` | 평가·사람 결정 절차 완료. **인수 결과 `reject`** |
| RL-06 | `review` (0/4) | 로컬 모델 최적화 명세, 구현 전 |
| RL-07 | `review` (0/6) | 판정 화면 개선 명세, 구현 전 |

`queue _ show`는 완료 증거를 현재 입력과 대조해 유효 단계를 계산한다. 갱신 전 조회에서 HP-00·01, RL-00~02·04는 `validating`, RL-03·05는 `done`이었다. 문서 변경으로 증거 hash가 달라질 수 있으므로 다음 실행 직전에 다시 조회한다. 상태 파일의 `done`만으로 선행 게이트를 우회하거나 제품 검증을 재실행한 것으로 적지 않는다.

### 다음 실행 경계

1. 실행 큐와 [RL-07 선행 증거 재사용 기록](../_runs/rl07-preflight-20261020/evidence-reuse.md)을 대조한다. 제품 소스가 같으면 기존 증거와 문서 변경의 영향을 확인하고 필요한 기록만 갱신한다.
2. RL-07은 판정 탭의 설명·표시·탐색을 고치는 프런트엔드 범위다. 회사 대조의 `gap` 누락은 해결하지 않는다.
3. [RL-05 인수 실패](../../validation-runs/2026-10-19-rl/RL-05/README.md)의 후속은 대조 개념 매핑·회사 사실 범위를 보완한 뒤 같은 gold로 재측정하는 것이다. [findings](../../tracking/findings.md)에 남기며 새 구현 범위·승인은 별도 기능 문서로 정한다.
4. RL-06은 큐의 RL-04·03·05 선행 조건과 인수 실패의 영향을 확인한 뒤 착수한다. 현재 RL의 승인 모델을 로컬 모델로 바꾼 상태가 아니다.
5. 운영 코드·DB 반영과 RL 기능 활성화는 별개다. 마지막 [운영 반영 기록](../../validation-runs/20261019-ops-rl-rollout/README.md)은 RL 분석 false·운영 회사 근거/브리핑 미등록이며, 실제 전송·Slack·cron은 별도 승인 경계다.

## 후속 범위

입찰 delta worker·Go/No-Go 고도화, 외부 공개·SSO, 그래프 DB 도입, OCR, C-2 다회사·정책 변경은 RL 이후 별도 기능화한다. 이번 큐에 등록하지 않으며 완료 예정이나 구현 사실로 적지 않는다.

## HP — 홈페이지 전문 가상 1사 (2026-10-14 ~ 2026-10-16, 종료)

[ADR-0071](../../tracking/decisions/0071-homepage-single-company-deep-review.md)·[HP 공통 계약](../hp-contract.md)이 기록이다. HP-00·01은 구현·검증 기록이 있고 main에 들어왔다. HP-02~06은 2026-10-16에 `blocked`로 두고 큐에서 뺐으며 run `hp0206-20261015`는 abandon했다. HP-03·04·06의 설계는 RL-03·05가 루트랩 기준으로 다시 쓴다.

| 기능 | 상태 | 상세 |
|---|---|---|
| `HP-00-luna-model-identity` | 구현·검증, 재사용 | [intent](../groups/HP/features/HP-00-luna-model-identity/intent.md) |
| `HP-01-requirement-cards` | 구현·검증, 재사용 | [intent](../groups/HP/features/HP-01-requirement-cards/intent.md) |
| `HP-02` ~ `HP-06` | 폐기(blocked) | [HP 공통 계약](../hp-contract.md) |

## DEMO — 가상 SI 3사 (2026-10-06 ~ 2026-10-14, 종료)

[ADR-0070](../../tracking/decisions/0070-multi-company-knowledge-demo.md)·[DEMO 공통 계약](../demo-contract.md)이 기록이다. DEMO-00~04 코드(회사 경계·그래프·화면)는 RL이 재사용하고 DEMO-05는 중단했다.

## 2026-11-17 통합 개발 기준선

사용자 요청으로 `RL-09-engine-integration`을 추가한다. 기존 품질 reject를 보존하며 분석 엔진과 제품 실행 흐름을 연결한다. 운영 전환은 포함하지 않는다.
