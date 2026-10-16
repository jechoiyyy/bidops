# BidOps roadmap

## RL — 루트랩 실회사 기준 AX 과제

2026-10-16 확정한 신규 목표다([ADR-0073](../../tracking/decisions/0073-rootlab-real-company-ax-redefinition.md), [재정의 초안](../../1016_rootlab-redefinition/draft.md)).
화면 정본은 [RL 화면 구현 명세](../../1016_rootlab-redefinition/ui-spec.md)(시안 v26, 2026-10-16)이며 RL-00~04 spec은 이를 인용한다. 상태의 정본은 기능 status.json, 순서·직접 의존의 정본은 queue.json이다. 아래는 기능 후보이며 **각 기능은 `/sdlc:feature <ID>`로 intent·spec·plan을 쓴 뒤 큐에 등록한다. 등록 전 행은 계획이지 기능이 아니다.**

| 기능 후보 | 목표 | 선행 | 핵심 입력 |
|---|---|---|---|
| `RL-00-company-ground-truth` | 루트랩 실회사 1곳을 `is_fictional=false`로 등록. 프로필·실적·선호·자격을 출처·상태(`confirmed`/`proposed`/`unknown`)와 함께 버전 고정. 인터뷰 답 반영 절차 | 없음 | company-profile, homepage-profile, preferences, 인터뷰 A~F |
| `RL-01-daily-briefing` | 평일 1회 브리핑 생성(반복 발주처·연차 사업 규칙 → C-2·사전규격·입찰공고 후보 → 상위 N + 이유 3줄 + 차단 조건 + 마감)과 Slack bot 전송·화면, 채택/무시 피드백 저장 | RL-00 | 수집 파이프라인, C-2 결과, 선호·제외 조건 |
| `RL-02-opportunity-timeline` | 발주계획→사전규격→공고→정정→마감을 사업기회 하나의 타임라인으로 묶고 상태 변화 때만 알림 | RL-01 | 기존 사업기회 연결·추적 상태 |
| `RL-03-fit-verdict` | 요구사항 카드·여섯 영역 unit 추출 → 결정적 회사 대조 → 역할별 판단·종합 → 실무자 판정 5블록 화면(HP-03·04 설계를 루트랩·정책 승인 전송으로 재명세). **1차 대상은 사전규격**(입찰공고는 문서 취득 경로가 없어 후속) | RL-00·01·02 (HP-01은 완료·재사용) | HP 공통 계약 §6~8, bid-procedure 자격 항목 |
| `RL-04-proposal-draft` | 요구사항 대응표 + 사업 이해·수행 방안·유사 실적 절 초안. 출력은 PDF(1차)·HWP(후속, 변환기 결정 필요). 과거 제안서는 없으므로(E1) 제안요청서 목차·회사 근거만으로 생성 | RL-03 | 인터뷰 E, bid-procedure 제안서 목차 |
| `RL-05-gold-acceptance` | 사용자 gold 10건 대조 인수(HP-06 기준 재사용) | RL-03 | **실제 수집 사전규격 10건**(fixture 4건은 DB 공고가 아니라 attempt 불가 → RL-03 테스트용; 폴리텍은 smoke 노출로 제외) |
| `RL-06-local-llm-optimization` | 기능 완료 뒤 토큰 최적화용 로컬 LLM 검토(사용자 Q3) | RL-04 | 호출 수·토큰 계측 |

### 다음 실행 순서 (2026-10-16)

1. 사용자가 [인터뷰](../../1016_rootlab-redefinition/company-interview.md)를 채운다(RL-00 입력). 비어 있어도 RL-00 명세는 시작할 수 있고 값은 `unknown`으로 등록한다.
2. `/sdlc:feature RL-00-company-ground-truth` → `RL-01-daily-briefing` 순으로 문서화하고 `/sdlc:loop`로 구현한다. 실행·검증은 `bidops-local` 격리 자원, 브랜치는 main에서 분기한다.
3. Luna 정책 승인 전송(ADR-0073 결정 5)의 정책 파일·승인 기록은 **RL-03에서** 발행한다(RL-01 브리핑은 결정적 규칙이라 LLM 호출이 없다). 실제 호출은 직전 사람 확인 대상이다.
4. 2026-10-16 RL-00~06 intent·spec·plan 작성·독립 검사·큐 등록 완료(`queue _ show`). 구현은 `/sdlc:loop`로 시작하며 배치 승인은 그때 받는다.

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
