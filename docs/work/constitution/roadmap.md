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

### 다음 실행 순서 (2026-10-15)

HP00·01 구현/검증/통합은 완료 기록이 있다. 다음 순서는 HP02 → HP03 → HP04 → HP05 → HP06이며 직접 의존은 위 표 그대로다. HP05 도구는 HP02 이후 독립적으로 준비할 수 있다.

- HP02의 회사 v2·온톨로지 설정은 승인됐다. 다음 loop는 등록 projection·격리 등록을 구현한다.
- HP03의 실제 대표1건과 HP04 실제 조회는 mock 검증과 구분한다. 기존 승인 범위·건별 전송 binding을 유지한다.
- HP05는 도구 구현 뒤 사람 기대/필수 경로가 작성되어야 실제 비교한다. 후보 기준은 확정됐고 최종 채택은 사람 판단이다.
- HP06의 독립 gold는 아직 작성 전이다. 폴리텍 모델 노출을 고려해 미노출 평가자 또는 별도 holdout을 정해야 한다. 현재 공동 검토는 assisted review다.
- 문서·도구 준비를 구현·실험·사람 인수 완료로 쓰지 않는다. 현재 요청은 loop 시작 전 준비이며 새 run을 시작하지 않는다.

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
