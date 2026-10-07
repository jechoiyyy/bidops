# BidOps roadmap

## DEMO — 가상 SI 3사 의사결정 데모

2026-10-06 확정한 신규 목표다. 기존 C-2·운영·생애주기 기록은 기존 문서에 보존한다.
상태의 정본은 기능 status.json, 순서·직접 의존의 정본은 queue.json이다. 아래 표는 제품 항목의 연결이다.

| 기능 | 목표 | 상세 |
|---|---|---|
| `DEMO-00-luna-preflight` | 운영 1489 Luna v4 선검증(main·운영 배포) | [intent](../groups/DEMO/features/DEMO-00-luna-preflight/intent.md) |
| `DEMO-01-company-context` | 회사별 상태 분리 | [intent](../groups/DEMO/features/DEMO-01-company-context/intent.md) |
| `DEMO-02-company-knowledge` | 온톨로지·3사 지식그래프 | [intent](../groups/DEMO/features/DEMO-02-company-knowledge/intent.md) |
| `DEMO-03-grounded-analysis` | 그래프 근거 기반 모델 분석 | [intent](../groups/DEMO/features/DEMO-03-grounded-analysis/intent.md) |
| `DEMO-04-review-workspace` | 회사 전환·탐색·비교·결정 | [intent](../groups/DEMO/features/DEMO-04-review-workspace/intent.md) |
| `DEMO-05-demo-acceptance` | 실제 예제와 인수 | [intent](../groups/DEMO/features/DEMO-05-demo-acceptance/intent.md) |

### 2026-10-06 재계획 일정

목표 2026-10-20(날짜 미정, 2주 안쪽). 아래는 영업일 기준 계획이며 완료 사실이 아니다.

| 구간 | 내용 | 사람 입력·확인 |
|---|---|---|
| 1~2일 | DEMO-00 원인 분류·v4·운영 적용·1489 실행 | 배포·import·env·전송 각 단계 확인, 1489 승인, 진행 판정 |
| 1~3일(병행) | DEMO-02 STEP-003 가상회사·온톨로지 초안 | 사용자 승인 후 동결 |
| 3~5일 | DEMO-01·DEMO-02 | - |
| 5~7일 | DEMO-03 | - |
| 6~8일 | DEMO-04 | - |
| 7~10일 | DEMO-05 환경·표본·별칭 보강·핏 18·대표 3건 → 나머지 6건·인수 | 로컬 LLM 엔드포인트, env/demo.env, 심층 9건 승인, 보고서 인수 |

보고서 호출 수는 원문 단위 수의 약 2배이고 호출당 5~6분이다. 1489(19단위) 선검증은 약 3.5시간 이상, 8단위 이하 공고는 약 1.5시간이다.
슬롯이 하나라 순차 실행되며, 마감은 정책 값(v4 5시간)이다. 대표 3건으로 최소 기준을 먼저 확보한다.
DEMO-02 STEP-003의 초안 작성은 큐 순서와 별도로 DEMO-00 대기 중에 먼저 할 수 있는 문서 작업이다(등록·동결은 큐 순서대로).

## 후속 범위

C-2 다회사 선별·입찰 delta·Go/No-Go·외부 공개·편집/자동 추출 UI·시맨틱웹 연계는 DEMO 이후 별도 기능화한다.
이번 큐에는 등록하지 않으며 완료 예정이나 구현 사실로 적지 않는다.
