# 생애주기 구현 중간 보고 (2026-08-30)

발주계획 → 사전규격 → 입찰공고 생애주기 구현의 T-10~T-18 결과를 정리한다.
근거는 각 절이 가리키는 파일과 테스트다. 확인하지 않은 것은 `unknown`으로 남긴다.

## 한 줄 요약

**수집 → 적재 → 사업기회 연결 → 추적 상태 → 화면**까지 경로가 이어졌다.
1차 분류 모델은 여전히 미정이며 결정적 mock으로 대체하고 있다.

## 끝난 것

| ID | 한 일 | 산출물 |
|---|---|---|
| T-10 | 발주계획 적재 경로 | `bidops.collected-order-plans.v1` 계약과 loader |
| T-11 | 수집기가 발주계획번호를 싣는다 | `lifecycle.order_plan_no` (`collected.v2` 유지) |
| T-13 | 대기 참조 해소 호출 | flush 후 `resolve_order_plan_opportunity_links()` |
| T-14 | 1차 분류 결정적 mock | `MockScreeningTransport` ([ADR-0029](../tracking/decisions/0029-screening-mock-provider.md)) |
| T-15 | 발주계획 수집기 | `skills/bidops-collect/scripts/collect_order_plans.py` |
| T-16a | 추적 상태 스키마 | revision `0007_opportunity_tracking_state` |
| T-16b | 전이와 재검토 신호 | `app/services/opportunity_tracking.py` |
| T-16c | 추적 상태 REST | `PATCH /api/opportunities/{id}/tracking-status` |
| T-17 | 사업기회 조회 REST | `GET /api/opportunities`, `GET /api/opportunities/{id}` |
| T-18 | 사업기회 화면 | `/opportunities` |
| T-4 | 사전규격 정규화기 보강 | `PPSSrch` 전환, 첨부·SW대상·업무구분·공고번호 보존 |
| T-5 | 비표준 계획번호 14건 | 원문 보존 동작을 측정된 두 형태로 테스트 고정 |

테스트: backend `6 failed, 768 passed, 36 skipped` (실패 6건은 작업 전과 동일한
PostgreSQL 필요 4건 + 승인 프로필 git blob 2건), pipeline 108 passed,
frontend `tsc -b`·`vite build` 통과.

## 설계에서 지킨 경계

**사람 판정과 시스템 산출을 섞지 않는다.**
[ADR-0030](../tracking/decisions/0030-opportunity-tracking-state.md)이 `재검토 필요`를
추적 상태 enum에 넣지 않기로 했다. 사람이 고른 값(`tracking_status` 등 4개 컬럼)과
시스템 신호(`recheck_signal_at`, `recheck_signal_link_id`)가 서로 다른 컬럼에 있고,
`0007`의 CHECK가 `미선택`일 때 작성자·이유·시각이 비어 있음을 강제한다.

`test_ingest_new_official_bid_signals_closed_opportunity_without_changing_human_tracking_choice`가
실제 `ingest_run()` 두 회차로 이 불변을 증명한다. `종료`한 사업기회에 새 공고가
적재돼도 사람이 고른 네 필드가 그대로다.

**"못 찾았다"와 "없다"를 구분한다.**
[ADR-0025](../tracking/decisions/0025-prespec-link-search-unconfirmed-state.md)가 정한
`검색 미확인` 상태를 API가 그대로 내려 주고 화면이 "사전규격 없음"으로 바꾸지 않는다.

**`종료`를 기본으로 숨기지 않는다.**
목록 기본값이 `종료`를 포함한 전부다. 기본으로 안 보이는 것이 있으면 놓친 건을
사람이 확인할 방법이 없다. 이 기본값 자체를 테스트로 고정했다.

**`추적`/`신규` 매핑은 계약이 정한다.**
`docs/contracts.md`가 `first_registered_stage=order_plan → 추적`, 그 밖은 `신규`로
못 박았고 화면은 `src/lib/opportunity.ts` 한 곳에서만 변환한다.

## 생산자와 소비자를 실제로 이어 확인한 것

계약 필드명을 눈으로 맞추는 것으로는 어긋남을 못 잡는다. 두 지점에서 실제로 태웠다.

- `test_collector_artifact_round_trips_through_ingest_run` — 실제 수집기 스크립트를
  subprocess로 실행해 artifact를 만들고 `ingest_run()`으로 `OrderPlan` 행 생성까지 확인
- `test_order_plan_ingest_resolves_bid_first_waiting_reference` — 입찰공고를 1회차,
  발주계획을 2회차에 적재해도 같은 사업기회 하나에 들어감을 확인

## T-4에서 잡은 회귀

`QualificationFlags` 계약에 `sw_business_status`·`business_division`을 더하자
`test_quality_gate.py` 8건이 깨졌다. `ContractModel`의 기본값은 `_json_value`가
materialize하므로, **기존 공고 전부의 `qualification_flags_json`에 `null` 두 개가 생겨**
digest로 고정된 fixture와 저장 identity가 어긋났다.

`_lifecycle_payload`가 T-11 필드에 쓰던 것과 같은 가드를 `_qualification_flags_payload`로
만들어 해결했다. **선택 필드를 계약에 더할 때는 그 필드가 원본 artifact에 없었던 경우
저장 identity를 바꾸지 않는지 함께 확인해야 한다.**

## 첨부는 URL까지만이다

T-4는 `specDocFileUrl1~5`를 `attachments`에 **담는 것**까지다.
실제 파일을 내려받는 경로는 허용 형식·크기, 서버 생성 key, 악성코드 검사, quarantine,
객체 version 검증을 함께 갖춰야 하므로 별도 작업으로 남아 있다.
사전규격 심층 검토의 입력원은 아직 완성되지 않았다.

## 아직 못 한 것

**T-19 — 판정의 모델 계보가 API에 없다.**
[ADR-0030](../tracking/decisions/0030-opportunity-tracking-state.md)의 부수 결정이
mock 판정을 화면에 표시하기로 했으나, `Judgment`에 모델 계보가 없고
`ScreeningAttempt.model_digest`는 런타임 쪽에 있으며 judgment와 FK로 이어져 있지 않다.
**둘을 어떻게 잇는지가 결정 사항이므로 화면에 지어내 넣지 않았다.**
현재 mock 실행 판별은 DB의 `ScreeningAttempt.model_digest`로만 가능하다.

**D-5 — 1차 분류 방식이 미정이다.**
[ADR-0021](../tracking/decisions/0021-filter-experiment-before-implementation.md)의
비교 실험(키워드·ColBERT·Qwen·GPT Luna)과 사람 정답 보고서가 승인 전이다.
`docs/business-rules.md:28`에 따라 네 방식 중 어느 것도 운영 정본이 아니다.

**T-9 — PostgreSQL 실행 검증이 없다.**
`0004`~`0007` 전부 SQLite에서만 검증됐다. 배포 전 필수다.

## 남은 작업

즉시 가능: T-19(판정 모델 계보 노출), 사전규격 첨부 다운로드 경로
관측 필요: T-2b, T-2c, T-6
운영 환경 필요: T-3(HWP 변환기), T-9(PostgreSQL)
실험 승인 대기: D-5, `status.md`의 4·5번
