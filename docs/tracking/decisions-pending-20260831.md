# 결정 대기 목록 (2026-08-31 기준)

이 파일은 **사람이 정해야 진행되는 것만** 모은다. 근거는 각 항목이 가리키는 문서가 정본이다.
정하고 나면 해당 ADR이나 `lifecycle-workstream.md`로 옮기고 여기서는 지운다.

정렬은 막고 있는 범위가 넓은 순서다.

---

## 해소된 항목 (2026-08-31)

D-5부터 D-11까지 전부 결정했다. 아래 각 절은 결정의 근거로 남기며, 결정 내용은 이 표가
정본이다. 실행이 끝나면 해당 절을 지운다.

| 항목 | 결정 | 정본 |
|---|---|---|
| D-5 1차 분류 방식 실험 | 승인. arm을 BM25 · 한국어 dense · RRF 하이브리드 셋으로 교체하고 ColBERT는 뺀다. LLM arm은 비용 대비 가치로 보류하되 사람 정답은 공유 보존한다 | [ADR-0021 개정](decisions/0021-filter-experiment-before-implementation.md) |
| D-6 판정 모델 계보 (T-19) | `JudgmentRevision → ScreeningExecution`을 정본으로 하고 스키마는 바꾸지 않는다 | [ADR-0036](decisions/0036-judgment-model-lineage-source.md) |
| D-7 G2B egress 방화벽 | **승인 절차만 먼저 올린다.** overlay 실제 적용은 D-9 수명 결과를 보고 결정한다 | 아래 D-7 절 |
| D-8 21일 재조회 범위 | **종단 관측을 계속 쌓는다.** 2026-09-08(나이 15일)·09-14(나이 21일)을 받는다. 범위 변경 자체는 그 뒤에 판단한다 | 아래 D-8 절 |
| D-9 첨부 URL 수명 | **횡단면 측정 완료(2026-08-31). 나이 3~150일 180/180 생존, 100%.** 09-13 종단 확인만 남았다 | [validation-run](../validation-runs/20260831-prespec-attachment-survival.md) |
| D-10 원문 보존 정책 | **현행 유지.** 사전규격 첨부에만 별도 보존 기간을 만들지 않는다 | `security.md` |
| D-11 PostgreSQL 테스트 | **필수로 만든다.** `run-web-tests.sh`/CI에서 PostgreSQL 실행을 강제한다 | 아래 D-11 절 |

같은 세션에서 입찰 delta의 문서 role allowlist, 범주 정책 v1, 내부망 binding도
확정했다. [ADR-0034의 확정값 절](decisions/0034-bid-delta-final-decision.md)이 정본이다.

---

## D-7. `www.g2b.go.kr` egress 방화벽 승인 (T-20 배포 조건)

- 근거: [`security.md`](../security.md)의 "네트워크와 HTTP",
  [첨부 실측](../validation-runs/20260830-prespec-attachment-probe.md)

**정해야 할 것**: 사전규격 첨부를 실제로 내려받으려면 host 방화벽에서
`www.g2b.go.kr:443`을 허용해야 한다. 수집 OpenAPI(`apis.data.go.kr`)와 **다른 host**라
기존 허용 범위에 없다.

**이미 준비된 것**: 기본 compose의 격리는 그대로 두고 overlay에서만 여는 구조
(`docker-compose.t7.screening.yml`·`remote-vllm.yml`과 같은 형태)로 구현한다.
`BIDOPS_G2B_ATTACHMENT_ENABLED`의 기본값은 `false`이고 allowlist가 비면 connector가
만들어지지 않는다(fail-closed).

**결정 전까지의 동작**: 기능은 있지만 꺼져 있다. 다운로드 큐는 쌓이고 실행되지 않는다.

---

## D-8. ADR-0027의 21일 재조회 범위를 유지할 것인가

- 근거: [종단 관측](../validation-runs/20260831-order-plan-longitudinal.md),
  [findings.md](findings.md)
- 상태: **근거가 확인되지 않았다.** 아직 판단할 데이터가 부족하다.

**측정된 것**: 같은 997건이 5일 동안 채움률 45.6% → 46.6%로 1 포인트 올랐다.
같은 나이(6일)의 횡단면 점은 67.8%다. 21 포인트 차이다.
[fill-curve](../validation-runs/20260829-order-plan-fill-curve.md)가 미리
"어긋나면 종단이 정본"이라고 정해 두었으므로 종단이 우선한다.

**함의**: [ADR-0027](decisions/0027-order-plan-requery-window.md)의 21일은 횡단면의
"15~17일 평탄화"에서 나왔다. 실제 코호트가 훨씬 느리게 채워진다면 21일 창은 짧고
공고 전환을 놓친다.

**지금 정할 필요는 없다.** 종단 점이 세 개뿐이다. 나이 15일·21일 근처
(**2026-09-08**, **2026-09-14** 무렵) 관측이 나오면 판단할 수 있다.
그때까지 재조회 범위를 바꾸지 않는다.

**정해야 할 것**: 그 관측을 계속 쌓을지, 그리고 결과에 따라 재조회 범위를 늘릴지.
범위 확대는 수집 비용과 API 일일 한도에 직접 영향을 준다.

---

## D-9. 첨부 URL의 수명을 측정할 것인가

- 근거: [첨부 실측](../validation-runs/20260830-prespec-attachment-probe.md)의 "측정하지 않은 것"

**문제**: T-20의 조건부 다운로드는 "나중에 추적 대상이 되면 그때 받는다"가 전제다.
그 사이 첨부 URL이 죽으면 원문을 영영 못 받는다. **수명은 측정된 적이 없다.**

**측정 방법**: 2026-08-30에 받은 30건 표본의 URL을 2주 뒤(**2026-09-13** 무렵)
다시 호출해 응답률과 sha256 동일성을 본다. 호출 30회다.

**미루면 잃는 것**: 표본이 오래될수록 "URL이 죽었다"와 "원래 없었다"를 구분하기 어렵다.
지금 정하지 않아도 되지만 9월 중순이 지나면 이 표본으로는 못 잰다.

---

## D-10. 다운로드한 원문의 보존 정책 (확인만 필요)

- 근거: [`security.md`](../security.md)의 "문서·객체 안전"

**현재 규칙**: "source, structure, quarantine 원문은 일상 삭제하지 않는다."
이 규칙대로면 추적 상태가 나중에 `종료`로 바뀌어도 받아 둔 문서는 남는다.

**권고**: 이대로 둔다. 사전규격 첨부에만 별도 보존 기간을 새로 만드는 것이
기존 규칙을 흔들고 삭제 사고 위험을 만든다. 규모도 작다 —
`swBizObjYn=Y` 조건 기준 **약 12.6MB/일, 4.6GB/년**
([사전규격 채움 곡선](../validation-runs/20260831-prespec-fill-curve.md)의
비율과 첨부 실측의 평균 411KB로 계산).

**정해야 할 것**: 이 권고를 받아들일지, 아니면 별도 보존 기간을 둘지.

---

## D-11. PostgreSQL 테스트를 필수로 만들 것인가

- 근거: [findings.md](findings.md)의 "PostgreSQL 전용 테스트가 스키마 변경 뒤에도 갱신되지 않고 skip됐다"

**문제**: `tests/postgres.py`의 `requires_postgres`는 `BIDOPS_TEST_POSTGRES_URL`이 없으면
조용히 skip한다. 그래서 `0004`가 `notice.run_id`를 없앴을 때 그 컬럼에 insert하던
PostgreSQL 테스트 9건이 깨지지 않고 계속 초록이었다. 2026-08-31에 처음 실행해서 발견했다.
같은 실행에서 **배포를 완전히 막고 있던 Alembic 결함**도 나왔다.

**선택지**

1. `web/run-web-tests.sh`나 CI에서 PostgreSQL 실행을 필수로 만든다 — 같은 종류의 결함이
   다시 잠복하지 않는다. 대신 로컬 개발에 Docker가 필요해진다.
2. 현행 유지하고 스키마를 바꾼 작업만 수동으로 PostgreSQL 테스트를 돌린다 —
   `engineering-notes.md`에 절차를 적어 두었다. 사람이 잊으면 같은 일이 반복된다.

**권고**: 1번. 이번에 나온 두 결함 모두 SQLite에서는 보이지 않았고 둘 다 배포에 직결됐다.

---

# 결정이 필요 없는 진행 중인 것

참고용이다. 여기 있는 항목은 답을 기다리지 않는다.

| 항목 | 상태 |
|---|---|
| T-20a 취득 경계 (파일명 파서·connector·설정) | **완료·검증됨** |
| legacy 첨부 `QuarantinedAsset` 인자 어긋남 수정 | **완료·검증됨** |
| T-9 PostgreSQL 마이그레이션 검증 | **완료** (배포 차단 결함 1건 수정) |
| T-2c 사전규격 채움 곡선 | **완료** |
| T-2b 종단 관측 3번째 점 | **완료** — D-8로 이어짐 |
| T-3 HWP 변환기 확인 | **완료** (외부 의존성이 아니었다) |
| T-21 제안요청서 구조 측정 | **완료** — ADR-0032로 결정 완료 |
| T-20b 큐·자격 판정·worker·적재 | **완료·검증됨** (PostgreSQL `0008` upgrade/downgrade 포함) |
| T-24 사전규격 목록 REST·화면 | **완료·검증됨** |
| T-23 phase 2 결과·attempt 계약 | **결정·DB/API 기반 구현 완료** — [ADR-0035](decisions/0035-prespec-overview-attempt-result-lifecycle.md), 실제 모델 실행은 binding 필요 |

T-23 phase 1은 [ADR-0033](decisions/0033-prespec-overview-review-runtime-contract.md)으로
완료했고 phase 2 계약과 DB/API 기반은
[ADR-0035](decisions/0035-prespec-overview-attempt-result-lifecycle.md)에 따라 구현했다. 실제
모델 adapter·worker 실행은 승인된 사설 binding이 필요하지만 D-14 사람 결정을 더 기다리지는
않는다. 아래 표에는 실제로 사람 결정을 기다리는 작업만 남긴다.

| 결정을 기다리는 작업 | 무엇을 기다리나 |
|---|---|
| T-20 운영 활성화 | D-7 (방화벽 승인) |
| T-2b 종단 관측 계속 | D-8. 2026-09-08·09-14 무렵이 결정적 |
| 첨부 URL 수명 측정 | D-9. 2026-09-13이 지나면 이번 표본으로 못 잰다 |
