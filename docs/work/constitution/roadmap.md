# BidOps roadmap

## HP — 홈페이지 전문 가상 1사 심층 검토 재정의

2026-10-14 확정한 신규 목표다([ADR-0071](../../tracking/decisions/0071-homepage-single-company-deep-review.md), [HP 공통 계약](../hp-contract.md)).
상태의 정본은 기능 status.json, 순서·직접 의존의 정본은 queue.json이다. 아래 표는 제품 항목의 연결이다.

| 기능 | 목표 | 선행 | 상세 |
|---|---|---|---|
| `HP-00-luna-model-identity` | codex-exec 모델을 `gpt-6-luna`/high로 전환하는 새 불변 정책·runner·client·화면 표식 | 없음 | [intent](../groups/HP/features/HP-00-luna-model-identity/intent.md) |
| `HP-01-requirement-cards` | HWP 구조화 결과에서 요구사항 카드 inventory·쪽 상속·taxonomy v2 | 없음 | [intent](../groups/HP/features/HP-01-requirement-cards/intent.md) |
| `HP-02-homepage-ontology-company` | 홈페이지 온톨로지 어휘·가상회사 1곳 원본 (사용자 공동 설계·승인·동결) | HP-01 | [intent](../groups/HP/features/HP-02-homepage-ontology-company/intent.md) |
| `HP-03-two-tier-analysis` | 카드 단위 타입화 추출 → 결정적 대조 → 역할별 판단·종합 파이프라인 | HP-00, HP-02 | [intent](../groups/HP/features/HP-03-two-tier-analysis/intent.md) |
| `HP-04-practitioner-verdict` | 실무자 판정 5블록 화면과 REST | HP-03 | [intent](../groups/HP/features/HP-04-practitioner-verdict/intent.md) |
| `HP-05-neo4j-experiment` | PostgreSQL 그래프 대 Neo4j 비교 실험(경로 recall·질의 표현력·설명 가능성) | HP-02 | [intent](../groups/HP/features/HP-05-neo4j-experiment/intent.md) |
| `HP-06-gold-acceptance` | 사용자 gold 10건 대조 인수와 수치 기록 | HP-04 | [intent](../groups/HP/features/HP-06-gold-acceptance/intent.md) |

### 실행 순서 (2026-10-14)

| 구간 | 내용 | 사람 입력·확인 |
|---|---|---|
| 1 | HP-00·HP-01을 한 배치로 구현. HP-01은 모델 호출 없음. HP-00은 코드·정책이며 격리 스택 smoke 1건만 건별 승인 대상(승인 없으면 pending) | 문서 commit, run 시작 승인, DEMO-05 run abandon, smoke 승인 |
| 2 | HP-02 온톨로지 공동 설계: 카드 198장 어휘 후보 → 분류 → concept id/alias → 가상회사 초안 → 승인 → 동결 | 어휘·분류·회사 초안 검토 |
| 2' | 사용자가 gold 10건을 작성한다(형식 승인됨). HP-02~04와 병행하며 모델 출력 전에 끝낸다 | gold 작성 |
| 3 | HP-03 파이프라인 구현. 첫 실제 호출(모델 smoke → 대표 1건)은 건별 승인 | 전송 승인 |
| 3' | HP-05 Neo4j 실험을 HP-02 동결 뒤 HP-03과 병행 | 채택 조건 숫자 확정 |
| 4 | HP-04 화면 → HP-06 gold 대조 인수 | 인수 |

호출 수·시간 목표는 공통 계약 §7의 정책 값이다. 슬롯은 하나라 순차 실행된다.

## 후속 범위

C-2 다회사 선별·입찰 delta·Go/No-Go·외부 공개·편집/자동 추출 UI·시맨틱웹 연계·OCR은 HP 이후 별도 기능화한다.
이번 큐에는 등록하지 않으며 완료 예정이나 구현 사실로 적지 않는다.

## DEMO — 가상 SI 3사 의사결정 데모 (2026-10-06 ~ 2026-10-14, 종료)

[ADR-0070](../../tracking/decisions/0070-multi-company-knowledge-demo.md)과 [DEMO 공통 계약](../demo-contract.md)이 기록이다.
DEMO-00~03은 validating, DEMO-04는 done으로 기록이 남아 있고 DEMO-05는 2026-10-14에 중단했다(run `demo05-20261012` abandon은 사용자 결정).
DEMO 기능의 미완료 증거를 HP 완료로 적지 않으며, HP는 DEMO-01~04 코드를 기준 브랜치 `demo/local-20261009`에서 재사용한다.

| 기능 | 목표 | 상세 |
|---|---|---|
| `DEMO-00-luna-preflight` | 로컬 실제 자료·문서·LiteLLM 개요 준비 판정과 Luna 게이트 이관 | [intent](../groups/DEMO/features/DEMO-00-luna-preflight/intent.md) |
| `DEMO-01-company-context` | 회사별 상태 분리 | [intent](../groups/DEMO/features/DEMO-01-company-context/intent.md) |
| `DEMO-02-company-knowledge` | 온톨로지·3사 지식그래프 | [intent](../groups/DEMO/features/DEMO-02-company-knowledge/intent.md) |
| `DEMO-03-grounded-analysis` | 그래프 근거 기반 모델 분석 | [intent](../groups/DEMO/features/DEMO-03-grounded-analysis/intent.md) |
| `DEMO-04-review-workspace` | 회사 전환·탐색·비교·결정 | [intent](../groups/DEMO/features/DEMO-04-review-workspace/intent.md) |
| `DEMO-05-demo-acceptance` | 실제 예제와 인수 (중단) | [intent](../groups/DEMO/features/DEMO-05-demo-acceptance/intent.md) |
