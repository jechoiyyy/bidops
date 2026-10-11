# BidOps roadmap

## DEMO — 가상 SI 3사 의사결정 데모

2026-10-06 확정한 신규 목표다. 기존 C-2·운영·생애주기 기록은 기존 문서에 보존한다.
상태의 정본은 기능 status.json, 순서·직접 의존의 정본은 queue.json이다. 아래 표는 제품 항목의 연결이다.

| 기능 | 목표 | 상세 |
|---|---|---|
| `DEMO-00-luna-preflight` | 로컬 실제 자료·문서·LiteLLM 개요 준비 판정과 Luna 게이트 이관 | [intent](../groups/DEMO/features/DEMO-00-luna-preflight/intent.md) |
| `DEMO-01-company-context` | 회사별 상태 분리 | [intent](../groups/DEMO/features/DEMO-01-company-context/intent.md) |
| `DEMO-02-company-knowledge` | 온톨로지·3사 지식그래프 | [intent](../groups/DEMO/features/DEMO-02-company-knowledge/intent.md) |
| `DEMO-03-grounded-analysis` | 그래프 근거 기반 모델 분석 | [intent](../groups/DEMO/features/DEMO-03-grounded-analysis/intent.md) |
| `DEMO-04-review-workspace` | 회사 전환·탐색·비교·결정 | [intent](../groups/DEMO/features/DEMO-04-review-workspace/intent.md) |
| `DEMO-05-demo-acceptance` | 실제 예제와 인수 | [intent](../groups/DEMO/features/DEMO-05-demo-acceptance/intent.md) |

### 2026-10-09 재계획 순서

기존 목표일은 확정 일정으로 사용하지 않는다. 아래는 2026-10-09 로컬 증거를 반영한 실행 순서이며 완료 사실은 각 기능 status와 실제 증거로만 판단한다.

| 구간 | 내용 | 사람 입력·확인 |
|---|---|---|
| 완료 증거 정리 | DEMO-00의 기존 STEP-001/002 이력 보존, `bidops-local` 3일 수집·notice 179 문서 준비·LiteLLM 개요 증거 판정 | 개요 참조 실행을 Luna 심층 품질로 승격하지 않음 |
| 다음 | DEMO-01·DEMO-02 회사 경계와 온톨로지·가상회사 구현 | 가상회사 초안 사용자 승인 후 동결 |
| 이후 | DEMO-03 회사 핏·그래프 근거·Luna 심층 연결 | 2026-10-11 재계획: 실제 `bidops-local` 준비(0036·3사·정책·flag·runner)와 호출 전 fail-closed 확인까지가 DEMO-03 게이트. 대표 1건 실제 Luna 심층은 DEMO-05로 이관(공고 179 inventory 불일치 findings). DEMO-04는 fake 종단·실제 스택 준비 증거를 입력으로 진행 |
| 이후 | DEMO-04 회사 전환·탐색·비교·결정 화면 | 실제 심층 결과와 fake 화면 검증을 구분 |
| 최종 | DEMO-05 3일 수집 corpus에서 6건 동결·핏 18·대표 3건 → 목표 9건·인수 | LiteLLM 개요/핏과 Luna 심층을 별도 호출·증거로 기록 |

보고서 호출 수는 원문 단위 수의 약 2배이고 호출당 5~6분이다. 슬롯이 하나라 순차 실행되며, 마감은 정책 값(v4 5시간)이다.
대표 1건×3사로 최소 기준을 먼저 확보한다. 운영 1489 실행은 이 순서의 선행조건이 아니며, v4 운영 전환이 필요할 때 별도 승인 작업으로 수행한다.

## 후속 범위

C-2 다회사 선별·입찰 delta·Go/No-Go·외부 공개·편집/자동 추출 UI·시맨틱웹 연계는 DEMO 이후 별도 기능화한다.
이번 큐에는 등록하지 않으며 완료 예정이나 구현 사실로 적지 않는다.
