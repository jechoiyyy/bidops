# 생애주기 결정·조사 색인

2026-10-21 정리. 이 문서는 결정·조사 근거를 연결한다. 신규 작업은 [RL 로드맵](../work/constitution/roadmap.md)과 `feature_status.py queue _ show`, 현재 구현·인수는 [status](status.md), 미해결 재현은 [findings](findings.md)를 따른다. 과거 T/D 번호의 실행 목록은 종료했고 다시 사용하지 않는다.

## 결정 완료

| 결정 | 근거 |
|---|---|
| 생애주기를 발주계획·사전규격 중심으로 구성하고 opportunity ID로 묶는다 | [ADR-0022](decisions/0022-plan-prespec-centered-lifecycle.md) |
| 사전규격은 발주계획 선택 여부와 무관하게 **전량 독립 수집**한다 | [ADR-0022](decisions/0022-plan-prespec-centered-lifecycle.md) 대안 절 |
| 공식 통합번호 관계만 자동 확정하고 유사도 관계는 사람 확인 대기 후보로 남긴다 | [ADR-0022](decisions/0022-plan-prespec-centered-lifecycle.md) |
| 발주계획 선별 방식은 비교 실험 승인 후 구현한다 | [ADR-0021](decisions/0021-filter-experiment-before-implementation.md) |
| C-2 발주계획 1차 선별은 BM25 상위 300건을 Qwen으로 판정하고 `relevant|uncertain`을 검토 후보로 유지한다 | [ADR-0037](decisions/0037-order-plan-c2-bm25-top300-qwen.md) |
| 화면은 회차 종속이 아니라 **누적**으로 간다 | 2026-08-28 합의. ADR 미작성 |
| 사전규격 목록에서 `추적`(발주계획부터 추적하던 건)과 `신규`(사전규격에서 처음 등장)를 구분하고, 화면 라벨이 아니라 데이터에 남는 값으로 둔다 | 2026-08-28 합의. ADR 미작성 |
| 캘린더·입찰일정·알림은 후속 아이디어로만 유지한다 | 2026-08-28 합의 |
| 사전규격은 `swBizObjYn`으로 걸러 내지 않고 전량 수집하며 SW 여부는 표시 값으로 둔다 | [ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md) |
| T-1b는 원인 격리 6회부터 한다 | 2026-08-28 합의 |
| 이름 검색은 네 전략을 모두 쓰고 후보에 전략을 표시한다. 못 찾은 건은 `검색 미확인`으로 남기고 "사전규격 없음"으로 표시하지 않는다 | [ADR-0025](decisions/0025-prespec-link-search-unconfirmed-state.md) |
| 공고를 외부 식별자로 누적하고 회차를 관측 이력으로 강등한다. 발주계획은 `notice`가 아니라 별도 테이블 | [ADR-0026](decisions/0026-cumulative-external-identity-schema.md) |
| ~~발주계획은 최근 21일 구간을 매일 재조회한다. `chgDt`는 갱신 신호로 쓰지 않는다~~ 2026-09-18 폐기 — 발주계획은 기준일(전일) 하루 창으로 수집하고 재조회하지 않는다. 공고는 기준일 포함 4일 창(사전규격 공개 지연) | [ADR-0061](decisions/0061-daily-collection-window.md)(ADR-0027 대체) |
| 입찰공고에서 처음 등장한 사업도 기회로 등록한다. 해소 안 된 공식 참조번호는 링크에 보존한다 | [ADR-0028](decisions/0028-bid-first-opportunity-registration.md) |
| 1차 분류 소비 계층의 결정적 mock은 실제 C-2 adapter가 연결될 때까지 유지하며 운영 결과로 보지 않는다 | [ADR-0029](decisions/0029-screening-mock-provider.md), [ADR-0037](decisions/0037-order-plan-c2-bm25-top300-qwen.md) |
| 모든 사업기회가 추적 상태를 갖고 기본값은 `미선택`이다. 사람 선택과 시스템 재검토 신호를 분리한다 | [ADR-0030](decisions/0030-opportunity-tracking-state.md) |
| 개요 검토 앞부분은 본문과 대응하는 목차, 아니면 의미 있는 주제 소제목으로 자른다. 번호만으로 자르지 않고 모호하면 `unknown`·사람 검토, 전략·`start_locator`·`end_locator`·`source_sha256`를 보존하며 고정 block 수·전체 문서 자동 투입을 금지한다 | [ADR-0032](decisions/0032-prespec-overview-cutting-rule.md) |
| 입찰 delta는 exact snapshot과 7개 범주로 비교하고 최종 결정은 `go\|no_go` append-only 사람 기록으로 둔다. 실질 변경은 보수적으로 material, 새 authoritative 입력은 strict stale, 내부망 모델과 safe audit allowlist만 사용한다 | [ADR-0034](decisions/0034-bid-delta-final-decision.md) |

## 조사 근거

- [생애주기 연결 조사](../validation-runs/20260828-lifecycle-linkage-survey.md): 공식 연결 키·검색 후보 경계.
- [발주계획 종단 관측](../validation-runs/20260831-order-plan-longitudinal.md): 횡단면 채움률을 재조회 효과로 단정하지 않는 근거. 일일 창은 ADR-0061이 대체했다.
- [사전규격 채움률](../validation-runs/20260831-prespec-fill-curve.md), [첨부 생존](../validation-runs/20260831-prespec-attachment-survival.md), [문서 구조](../validation-runs/20260831-prespec-rfp-structure.md): 당시 표본의 관측이며 현재 전체 모집단 보장이 아니다.

## 이전 작업 기록

완료·소거된 작업 목록과 당시 스키마·운영 상태는 `git show b5a61e4:docs/tracking/lifecycle-workstream.md`에서 찾는다. 현재의 미구현 범위는 입찰 delta 계산 worker·첨부 실패 재시작 UI 등을 [status](status.md)에서 확인한다. `운영 데이터 없음`, `normalizer가 첨부를 비움` 같은 8월의 관측을 현재 사실로 사용하지 않는다.
