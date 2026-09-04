# 생애주기 구현 작업 기록

`발주계획 조기 탐색 → 사전규격 심층 검토 → 입찰공고 추적` 흐름을 구현하는 동안의 살아 있는 기록이다.
확정된 사실, 아직 정하지 못한 결정, 해야 할 일과 끝낸 일을 한곳에 모은다.

갱신 규칙:

- 결정이 확정되면 `decisions/`에 ADR을 만들고 여기서는 **결정 완료**로 옮겨 링크만 남긴다.
- 항목을 지울 때는 삭제하지 않고 **소거한 항목**으로 옮기고 이유를 적는다.
- 측정으로 확인한 것만 사실로 적는다. 확인하지 않은 것은 `unknown`으로 남기고 추정하지 않는다.
- 이 파일은 요약이다. 근거는 `validation-runs/`, 미해결 문제는 `findings.md`, 확정 결정은 `decisions/`가 정본이다.

최종 갱신: 2026-09-01

---

## 확정된 사실

측정 근거는 [`validation-runs/20260828-lifecycle-linkage-survey.md`](../validation-runs/20260828-lifecycle-linkage-survey.md)에 있다. 다시 조사할 필요가 없다.

| 사실 | 근거 |
|---|---|
| 사전규격 첨부 URL은 최소 150일 살아 있다. 나이 3~150일 각 30개 **180/180 HTTP 200**이고 본문도 실제 파일이다 | 2026-08-31 [survival](../validation-runs/20260831-prespec-attachment-survival.md) |
| 첨부의 **8.3%가 허용 확장자(hwp/hwpx/pdf) 밖**이다. zip 9, xlsx 5, xls 1 | 같은 측정 180건 |
| 발주계획 갱신은 **원 구간 재조회**로 감지된다. 997건 유지, 22건 갱신, `nticeDt` 불변 | 고정 실험 대비 4일 후 재조회 |
| 발주계획 → 입찰공고는 `bidNtceNoList`. 16자리 = 공고번호 13 + 차수 3 | 482개 중 326개 조인 확인 |
| 입찰공고 → 발주계획은 `orderPlanUntyNo` (76.7%), → 사전규격은 `bfSpecRgstNo` (56.3%) | 1,628건 |
| **사전규격 → 발주계획 공식 키는 없다** | 8 오퍼레이션 × 3 조회모드 전수 확인 |
| 사업명 검색이 유일한 대체 경로. 전략 사다리로 **재현율 87.4%**(76/87) | 정답쌍 87건 채점 |
| 사전규격에 `swBizObjYn`·`bsnsDivNm`·`specDocFileUrl1~5`·`bidNtceNoList`가 있다 | 650건 |
| 규격서 첨부는 인증 없이 받아지고 실제 내용이 **과업지시서**(hwp)다 | 5건 표본 다운로드 |
| 첨부 형식(hwp/hwpx/pdf)이 기존 허용 확장자와 일치한다 | `app/deep_review/services/attachments.py:20` |
| `inqryDiv`는 조회 모드 선택자다. 1=접수일시(구간 필수·365일 상한), 2=등록번호, 3=참조번호 | 모드별 실측 |
| 사전규격 서비스는 물품·용역·공사·외자 × 기본·PPSSrch = 8 오퍼레이션 | 직접 호출 |
| `notice`는 이미 다형적이다. `source_type`으로 `bid_notice`·`pre_spec`을 담고 하위 8개 테이블이 **대리키 `notice.id`**를 참조한다 | `web/backend/app/lifecycle/models.py:96` |
| 회차 종속은 `notice.run_id`·`uq_notice_run_key`·`review.run_id`·`uq_review_notice_run` 네 곳이다. 하위 8개 테이블은 무관하다 | 같은 파일 |
| 운영 데이터가 없다. Alembic 3개(0001 baseline), `web/data/` 비어 있음 | 2026-08-28 확인 |
| 공식/후보 경계가 DB CHECK로 강제된다. `link_type='candidate'`는 `status='확정'`이 될 수 없다 | `0005_opportunity_links` |
| 대상 없는 링크는 `official`이고 참조번호가 있을 때만 허용된다. 후보는 대상 없이 존재할 수 없다 | `0006_bid_first_opportunity_registration` |
| `pre_spec` 정규화기는 `attachments`를 `[]`로 비우고 `swBizObjYn`·`bsnsDivNm`은 담을 자리가 없다 | `collect_notices.py:657` |
| **`bidNtceNoList` 채움률은 게시 후 15~17일에서 평평해진다.** 3일 45.8% → 9일 77.1% → 17일 85.0% → 148일 86.3% | [fill-curve](../validation-runs/20260829-order-plan-fill-curve.md), 호출 22회 |
| `chgDt`는 게시 직후에만 찍힌다(p99 2.2일, 비율 8% 고정). **갱신 감지 신호로 못 쓴다** | 같은 측정 |
| **종단 재조회가 횡단면 곡선을 재현하지 못한다.** 같은 997건이 5일간 45.6%→46.6%인데 같은 나이의 횡단면 점은 67.8%다 | [longitudinal](../validation-runs/20260831-order-plan-longitudinal.md), 관측 3점 |
| 횡단면 구간들은 폭이 같아도 건수가 28~997로 흔들려 비교 가능한 코호트가 아니다. 기울기가 나이 효과인지 코호트 차이인지 `unknown` | 같은 측정 |
| 9건이 `bidNtceNoList`를 얻는 동안 `chgDt` 보유 수는 78로 불변. **같은 레코드 추적으로 직접 확인** | 같은 측정 |
| **사전규격의 `bidNtceNoList`는 약 31일에 평평해진다.** 3일 5.5% → 9일 66.9% → 17일 77.8% → 31일 84.3% → 150일 90.0% | [prespec fill-curve](../validation-runs/20260831-prespec-fill-curve.md), 횡단면 6점 |
| 사전규격은 발주계획보다 늦게 채워진다. 3일 시점 5.5% 대 45.8% | 같은 측정 |
| 사전규격의 `chgDt`는 모든 나이에서 90~94%다. **너무 흔해서** 갱신 신호로 못 쓴다 | 같은 측정 |
| `swBizObjYn=Y`는 7.8~10.5%, 첨부 URL 보유는 88~91%로 여섯 코호트에서 안정적이다 | 같은 측정 |
| 제안요청서에 **목차가 있는 문서는 32%뿐이다.** 첫 주제 소제목이 `사업개요`인 것은 58%, 아무 주제 소제목도 못 찾는 문서가 14%다 | [rfp-structure](../validation-runs/20260831-prespec-rfp-structure.md), 65건 |
| `과업내용` 절이 없는 제안요청서가 34%다. 첫 소제목 위치는 p50 32 / p90 49 / 최대 211 block으로 흩어진다 | 같은 측정 |
| **문서 파이프라인 측정은 컨테이너에서 해야 한다.** host에는 poppler가 없어 PDF 16건 중 15건이 부당하게 `malformed_pdf`가 된다 | 같은 측정 |
| 첨부는 `Content-Disposition`의 **percent-encoded UTF-8**로만 파일명이 온다. RFC 5987 `filename*` 0건. 평균 411KB, 최대 3.0MB | [attachment probe](../validation-runs/20260830-prespec-attachment-probe.md), 30건 |
| `Content-Type`으로 hwp/hwpx를 구분할 수 없다(둘 다 `application/octet-stream`). 30건 중 2건(6.7%)은 정책상 차단된다 | 같은 측정 |
| `ntceNticeYn=Y` 비율은 `bidNtceNoList` 채움률과 모든 구간에서 일치한다 | 같은 측정 |
| 채움률 상한이 약 85%인 이유(취소·연기·수의계약 전환 비율)는 `unknown` | 같은 측정 |
| 이름 검색 실패 29건 중 최소 1건은 **이름이 완전히 동일한데도** 0건이다 (`R26DD20853714` ↔ `R26BD00267196`, 코드포인트까지 일치, 구간 안) | 2026-08-28 오프라인 대조 |
| 가운뎃점은 한 글자가 아니다. `·`(U+00B7) 72, `・`(U+30FB) 3, `․`(U+2024) 3, `‧`(U+2027) 2 | 발주계획 997건 문자 분포 |
| 정답쌍 87건의 정답 사전규격 중 3일치 로컬 수집에 있는 것은 17건뿐이다 (실패 29건 중에는 2건) | 사전규격이 공고보다 먼저 등록되기 때문 |
| **정규화는 오탐 위험을 늘리지 않는다.** 충돌 그룹이 원문 8·1과 정규화 후 8·1로 동일하다 (발주계획 997 / 사전규격 650) | 2026-08-28 오프라인 분석 |
| 반면 `longest_fragment`는 충돌 +19·+12, `prefix12`는 +55·+30을 만든다 | 같은 분석 |
| 원문 8건의 충돌은 정규화 탓이 아니라 **제목이 같은 중복 발주계획**이다 | 충돌 사례 전수 확인 |
| 서버 부분일치는 `사전규격이름 CONTAINS 질의` 방향이다. 사전규격에 `(… 재게시)` 접미가 붙어도 적중한다 | 로컬 17쌍 중 근로복지공단 2건 |
| **가운뎃점(U+00B7)이 들어간 질의는 사전규격 검색에서 0건이 된다.** 공백·괄호·인코딩은 무해하다 | 한 차원씩 격리한 6회 호출 |
| 가운뎃점은 실패 29건 중 8건에 있고 적중 58건에는 0건이다. 나머지 21건의 원인은 `unknown` | 전체 표본 문자 대조 |
| **검색을 깨뜨리는 문자는 다섯이다: `·`U+00B7 `&`U+0026 `‘`U+2018 `’`U+2019 `•`U+2022** | 문자 관용도 24회 |
| `・`U+30FB·`‧`U+2027·`․`U+2024는 **무해하다.** 가운뎃점 5종을 같은 부류로 본 추정은 틀렸다 | 같은 측정 |
| `~` `/` `_` `『』`도 무해하다. `∙`U+2219는 표본이 없어 `unknown` | 같은 측정 |
| 파손 문자 5종은 실패 29건 중 9건에 있고 적중 58건에는 0건이다. **남은 20건은 `unknown`** | 정답쌍 대조 |
| `breaking_split`의 한계: 구분자가 파손 문자 **뒤**에 있으면 조각이 그 구분을 잃는다. `… 생활폐기물 수집·운반 대행용역(N권역)` 8건이 한 질의로 합쳐진다 | `offline-analysis-v4.md` |
| `breaking_split`은 9번 시도해 6번 맞히고 **오탐 0**이다. `normalized`도 오탐 0 | 사다리 73회 |
| `longest_fragment`·`prefix12`는 각 1건씩 오탐을 만든다. 기존 "오탐 0"은 더 이상 사다리 전체에 성립하지 않는다 | 같은 측정 |
| 못 찾은 11건(12.6%)은 사전규격 쪽 이름이 실제로 다르다. 이름 검색으로 더 회수할 방법은 안 보인다 | 같은 측정 |
| 깨지는 문자에서만 쪼개는 `dot_split`은 충돌이 1·1로 원문 수준이다 (`longest_fragment`는 27·13, `prefix12`는 63·31) | `offline-analysis-v3.md` |
| C-2 Phase 0 전용 file·REST·DB·상태 계약과 immutable binding을 고정했다. 현재 validator 결과는 `valid_but_blocked`이며 C-1은 human 22·draft 603·잔여 87이다 | [ADR-0038](decisions/0038-order-plan-c2-phase0-contracts.md), `validate_order_plan_phase0.py` |

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
| 발주계획은 최근 21일 구간을 매일 재조회한다. `chgDt`는 갱신 신호로 쓰지 않는다 | [ADR-0027](decisions/0027-order-plan-requery-window.md) |
| 입찰공고에서 처음 등장한 사업도 기회로 등록한다. 해소 안 된 공식 참조번호는 링크에 보존한다 | [ADR-0028](decisions/0028-bid-first-opportunity-registration.md) |
| 1차 분류 소비 계층의 결정적 mock은 실제 C-2 adapter가 연결될 때까지 유지하며 운영 결과로 보지 않는다 | [ADR-0029](decisions/0029-screening-mock-provider.md), [ADR-0037](decisions/0037-order-plan-c2-bm25-top300-qwen.md) |
| 모든 사업기회가 추적 상태를 갖고 기본값은 `미선택`이다. 사람 선택과 시스템 재검토 신호를 분리한다 | [ADR-0030](decisions/0030-opportunity-tracking-state.md) |
| 개요 검토 앞부분은 본문과 대응하는 목차, 아니면 의미 있는 주제 소제목으로 자른다. 번호만으로 자르지 않고 모호하면 `unknown`·사람 검토, 전략·`start_locator`·`end_locator`·`source_sha256`를 보존하며 고정 block 수·전체 문서 자동 투입을 금지한다 | [ADR-0032](decisions/0032-prespec-overview-cutting-rule.md) |
| 입찰 delta는 exact snapshot과 7개 범주로 비교하고 최종 결정은 `go\|no_go` append-only 사람 기록으로 둔다. 실질 변경은 보수적으로 material, 새 authoritative 입력은 strict stale, 내부망 모델과 safe audit allowlist만 사용한다 | [ADR-0034](decisions/0034-bid-delta-final-decision.md) |

## 결정 대기

현재 신규 아키텍처 결정 대기는 없다. 2026-08-31의 결정 대기 목록(D-5~D-11)은 모두 결정이
끝나 저장소에서 제거했다. 확정 결정은 [`../ADR.md`](../ADR.md)와 `decisions/`의 상세 ADR을 따른다.
D-7·D-8·D-9 등 실행·관측·운영 승인 항목은 이 문서, `status.md`, `findings.md`에서 관리한다.

## 해야 할 일

| ID | 할 일 | 상태 | 비고 |
|---|---|---|---|
| T-1a | 검색어 정규화·전략 사다리 구현과 오프라인 측정 | 완료 | 테스트 36개 통과. `name-strategy/offline-analysis-v2.md` |
| T-1b | 격리 6 + 관용도 24 + 사다리 73 = **103회 완료**. 재현율 80.5% → 87.4% | 완료 | D-4 근거 제공 |
| T-2 | 채움 곡선 횡단면 측정 | 완료 | [fill-curve](../validation-runs/20260829-order-plan-fill-curve.md). D-3 근거 확보 |
| T-2b | 같은 구간 종단 관측점 쌓기 | **진행 중 — 횡단면과 어긋났다** | 3번째 점 확보(2026-08-31). 같은 997건이 5일 동안 45.6% → 46.6%로 **1 포인트**만 올랐다. 같은 나이(6일)의 횡단면 점은 67.8%로 **21 포인트 차이**다. 미리 정한 규칙대로 종단이 정본이므로 **ADR-0027의 21일 근거가 확인되지 않았다.** 점이 3개뿐이라 21일이 틀렸다고 단정할 수는 없다. 나이 15·21일 근처(9월 8일·14일 무렵) 관측이 결정적이다. [validation-run](../validation-runs/20260831-order-plan-longitudinal.md) |
| T-2c | 사전규격에도 같은 채움 곡선 측정 | 완료 | 나이 3·9·17·31·60·150일 횡단면 6점. `bidNtceNoList`는 3일 5.5% → 9일 66.9% → 31일 84.3%로 **약 31일에 평평해진다**(발주계획 15~17일보다 늦다). `chgDt`는 모든 나이에서 90~94%라 갱신 신호로 못 쓴다 — 발주계획과 결론은 같고 이유는 반대다. `swBizObjYn=Y` 7.8~10.5%, 첨부 URL 보유 88~91%로 안정적이다. [validation-run](../validation-runs/20260831-prespec-fill-curve.md) |
| T-3 | 문서 변환기가 HWP를 처리하는지 확인 | 완료 | **외부 의존성이 아니었다.** 변환기는 `app/document_mcp/vendor/rhwp`로 저장소에 벤더링돼 있고 Node로 실행된다. host(Node v22.23.2)에서 `tests/fixtures/documents/labor_template.hwp`(OLE CFB, 25,600B)를 처리해 page 1 · block 71을 경고 없이 추출했다. extractor는 `hwp-rhwp-hwpx` v1(upstream `96a2633f`). **남은 미확인**: 실제 과업지시서·제안요청서처럼 표와 목차가 많은 문서에서의 품질은 T-21에서 본다 |
| T-4 | 사전규격 정규화기 보강 (endpoint 전환, 첨부·SW대상·업무구분·공고번호) | 완료 | `PPSSrch`로 전환하고 `specDocFileUrl1~5`를 `attachments`로, `swBizObjYn`·`bsnsDivNm`을 `qualification_flags`로, `bidNtceNoList`를 `lifecycle`로 옮겼다. 응답에 없는 필드를 읽던 `url` 경로는 제거하고 `None`으로 둔다. 누락은 `unknown_fields`로 남긴다. **`swBizObjYn` 필터는 얹지 않았다** ([ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md)). 첨부 실제 다운로드는 별도 작업 |
| T-5 | 입찰공고의 비표준 `orderPlanUntyNo` 14건(0.9%) 파싱 예외 처리 | 완료 | T-10에서 이미 구현돼 있었다. `parse_order_plan_unty_no()`가 형식을 추측해 부분 추출하지 않고, 실패 시 원문이 `evidence_external_no`로 링크에 보존된다. `test_nonstandard_order_plan_number_is_preserved_not_treated_as_absent`가 측정된 두 형태로 이 동작을 고정한다 |
| T-6 | 발주계획에 사전규격번호가 채워지는 필드가 있는지 장기 관측 | 진행 중 | 3번째 관측(2026-08-31)에서도 `rcritRgstNo` **0/997**이다. 누적 갱신 31건(22+9) 중 어느 것도 이 필드를 채우지 않았다. 응답 59개 필드 중 `bfSpecRgstNo`·`refNo`는 **아예 존재하지 않는다**. 용역 레코드에서 항상 비어 있는 필드가 26개다. 지금까지의 관측으로는 발주계획 응답에 사전규격을 잇는 필드가 없다 |
| T-7 | 외부 식별자 누적 스키마와 Alembic 마이그레이션 구현 | 완료 | revision `0004_cumulative_external_identity`. 711 passed / 실패는 baseline과 동일한 6건 |
| T-8 | `opportunity`·`opportunity_link` 스키마와 공식 키 연결 경로 | 완료 | revision `0005_opportunity_links`. 722 passed / 실패는 baseline과 동일한 6건 |
| T-9 | PostgreSQL 17에서 `0004` upgrade/downgrade·trigger·제약조건 실행 검증 | 완료 | host의 Docker로 일회용 PostgreSQL 17을 띄워 실행했다. **`alembic upgrade head`가 애초에 동작하지 않았다** — Alembic이 version table을 `VARCHAR(32)`로 만드는데 revision 식별자 2개가 그보다 길어 `0004`에서 전체 롤백됐다. `env.py`가 table을 `VARCHAR(64)`로 먼저 만들도록 고쳤다. 이후 `0001`→`0007` 적용, `0007`→`0003` 단계별 downgrade, head 재적용이 모두 통과한다(`0002` downgrade는 의도된 차단). 제약조건·trigger가 실제로 거부하는 것도 확인했다. 저장소에 있던 PostgreSQL 테스트도 처음 실행해 `test_db_migrations` 17건, `test_models_runtime` 13건(스키마 변경 뒤 갱신 안 된 seed 1곳 수정), `test_integration_t14` 8건이 통과한다. [validation-run](../validation-runs/20260831-postgresql-migration-verification.md) |
| T-10 | `OrderPlan` 적재 경로 구현 | 완료 | `collected-order-plans.json` / `bidops.collected-order-plans.v1`을 loader가 읽어 공식 계획번호 upsert·관측 이력을 만든다. 실측 `orderPlanUntyNo`, `bidNtceNoList`, `ntceNticeYn`, `rcritRgstNo`, `chgDt`를 계약에 반영했다 |
| T-11 | 수집기 정규화에 `orderPlanUntyNo`를 실어 producer 계약을 잇는다 | 완료 | `lifecycle.order_plan_no`로 optional v2 projection을 추가했다. 공고의 기존 생애주기 필드 의미를 바꾸지 않아 v2를 유지하고, 전체 계획은 별도 v1 계약으로 분리했다 |
| T-12 | 입찰공고 최초 등록 기회와 대기 참조 해소 | 완료 | revision `0006_bid_first_opportunity_registration`. [ADR-0028](decisions/0028-bid-first-opportunity-registration.md) |
| T-13 | `OrderPlan` 적재 호출부에서 `resolve_order_plan_opportunity_links()`를 flush 후 호출 | 완료 | `_upsert_order_plan()`이 canonical row와 observation을 flush한 뒤 resolver를 호출한다. `test_order_plan_ingest_resolves_bid_first_waiting_reference`가 bid-first 대기 참조의 동일 opportunity 해소를 검증한다 |
| T-14 | 1차 분류 결정적 mock 제공자 (`MockScreeningTransport`) | 완료 | `Transport` 계층 주입. 검증·재시도·telemetry는 실제 경로가 돈다. [ADR-0029](decisions/0029-screening-mock-provider.md) |
| T-15 | 발주계획 수집기 (`collected-order-plans.json` 생산자) | 완료 | `skills/bidops-collect/scripts/collect_order_plans.py`가 실측 PPSSrch query·raw 보존·21일/명시 창·범위 metadata·재정규화·호출/페이지 상한을 제공한다. 수집기 단위 테스트와 backend `ingest_run()` 왕복 테스트를 통과시킨다 |
| T-16a | 추적 상태 스키마와 제약 | 완료 | revision `0007_opportunity_tracking_state`. `tracking_status` 기본 `미선택` + CHECK 3종. 재검토 신호는 `recheck_signal_at`·`recheck_signal_link_id` 쌍으로 사람 선택과 분리 |
| T-16b | 추적 상태 전이와 재검토 신호 발생 | 완료 | `app/services/opportunity_tracking.py`. loader의 대기 링크 해소·공식 링크 생성·병합 4곳에 신호를 걸었다. `test_ingest_new_official_bid_signals_closed_opportunity_without_changing_human_tracking_choice`가 실제 `ingest_run()` 두 회차로 사람 선택 4개 필드 불변을 증명한다 |
| T-16c | 추적 상태 REST API | 완료 | `GET /api/opportunities/{opportunity_id}`와 `PATCH /api/opportunities/{opportunity_id}/tracking-status`; actor 헤더·409/404/422·감사 이벤트 계약 반영 |
| T-17 | 사업기회 조회 API | 완료 | `GET /api/opportunities`; 종료 포함 기본 목록, 추적 상태·최초 등록 단계 필터, 연결 레코드 요약·단건 전체 link 노출 |
| T-18 | 사업기회 화면 (`추적`/`신규` 구분, 추적 상태 선택) | 완료 | `/opportunities` 새 페이지. `종료` 기본 노출, 재검토 신호와 근거 링크 표시, `검색 미확인`을 "없음"으로 표시하지 않음. `추적`/`신규` 매핑은 `src/lib/opportunity.ts` 한 곳에서만 계약대로 변환 |
| T-19 | 판정의 모델 계보를 API에 노출 (mock 표시의 선행 조건) | 결정 완료·구현 대기 | **경로는 이미 있었다.** `Judgment` → `JudgmentRevision.recording_execution_id` → FK → `ScreeningExecution`이 `model_name`·`model_digest`·`prompt_version`을 갖는다. `ck_judgment_revision_source_lineage`가 `runtime`·`carry_over`는 계보 필수, `legacy_import`는 `NULL` 필수로 강제하므로 추정 여지가 없다. `ScreeningAttempt.notice_id`는 `String(255)` 외부 공고번호라 애초에 join 대상이 아니다. [ADR-0036](decisions/0036-judgment-model-lineage-source.md)이 이 경로를 정본으로 채택했다. 스키마 변경 없이 projection과 화면만 남았다 |
| T-20 | 사전규격 첨부 조건부 취득·적재 (quarantine → ClamAV → content object → bundle 없는 DocumentVersion·structure) | 완료 | 메타데이터는 전량 수집하고 `SW사업대상=Y` 또는 추적 중 발주계획 연결만 재평가 큐에 넣는다. strict G2B provenance, lease worker, 안전한 오류 분류, source 승격 전 스캔, version 멱등성을 구현했다. clean inspect 결과는 document bundle 경로와 같은 canonical helper로 `DocumentStructure`·`DocumentBlock`에 저장한다. 다운로드는 backend `prespec-attachment-worker`가 전담하며 egress는 명시적 overlay로만 연다. **스캔 통과 전에는 변환·파싱·제공하지 않으며**, 구조 저장 실패는 부분 `DocumentVersion`을 남기지 않고 rollback 후 실패 전이한다 (`security.md:56`) |
| T-21 | 제안요청서 소제목·목차 분포 측정 | 완료 | 실제 문서 120건 수집·추출. 제안요청서·과업지시서 65건에서 **목차 보유 32%**, 첫 주제 소제목이 `사업개요`인 것 58%, **주제 소제목을 하나도 못 찾는 문서 14%**, `과업내용` 절 보유 66%. 번호 체계 최빈이 아라비아 62%. 첫 소제목 위치 p50 32 / p90 49 / 최대 211 block. **단일 규칙으로는 어떤 것을 골라도 최소 3분의 1이 사람에게 간다.** [validation-run](../validation-runs/20260831-prespec-rfp-structure.md) |
| T-22 | 앞부분 잘라내기 규칙 확정 | 완료 | [ADR-0032](decisions/0032-prespec-overview-cutting-rule.md). 본문과 대응하는 목차 또는 의미 있는 주제 소제목을 쓰고, 모호하면 `unknown`으로 사람에게 보낸다 |
| T-23 | `사전규격 개요 검토` 구현 | 진행 중 (phase 1 + phase 2 기반 완료, 실제 모델 실행 대기) | [ADR-0031](decisions/0031-prespec-overview-review-stage.md), [ADR-0032](decisions/0032-prespec-overview-cutting-rule.md), [ADR-0033](decisions/0033-prespec-overview-review-runtime-contract.md), [ADR-0035](decisions/0035-prespec-overview-attempt-result-lifecycle.md). clean RFP 선택·절단 snapshot·자동 준비·조회 API·상세 화면과 phase 2 immutable result/event·제한된 lifecycle service·safe v2 projection을 구현했다. DB는 구조 제약·runtime 권한·상태 전이 trigger 하나만 사용한다. 실제 모델 adapter·worker와 승인된 사설 binding은 아직 남았다 |
| T-24 | 사전규격 화면의 SW사업대상 기본 필터와 `신규` 표시 | 완료 | 누적 `GET /api/pre-specs`와 `/pre-specs` 화면을 구현했다. 기본 SW 필터, 추적 예외(`SW사업대상=N` 포함), `추적`·`신규` 데이터 값, 문서 취득 상태 집계와 안전한 빈 상태를 제공한다. 전용 테스트 11건 |

## 이번 범위가 아닌 것

- **입찰공고 전체 문서 분석**: 사전규격에서 추적하기로 한 건을 입찰공고까지 추적하고 그 시점에
  문서 전체를 분석하는 것은 후속 고도화다. R-07 계약 채택에 이어 R-08에서 DB·REST를,
  R-09에서 화면을 구현했으나, **실제 문서를 비교해 delta를 계산하는 worker와 모델 binding
  실행은 여전히 미구현이다.** 비교 생성은 `pending` 상태만 만들고 계산은 일어나지 않는다
  ([ADR-0031](decisions/0031-prespec-overview-review-stage.md),
  [ADR-0034](decisions/0034-bid-delta-final-decision.md)).

## 완료한 일

| 일자 | 한 일 | 산출물 |
|---|---|---|
| 2026-08-28 | 세 API 생애주기 연결 조사. 갱신 재관측, 필드, 키 형식, 조인 검증 | [validation-run](../validation-runs/20260828-lifecycle-linkage-survey.md), `experiments/lifecycle-linkage-survey/` |
| 2026-08-28 | 사업명 이름 매칭 정확도 측정 (정답쌍 87건, 재현율 80.5%·오탐 0) | `name-match/name-match-probe.json` |
| 2026-08-28 | 사전규격 서비스 오퍼레이션 8개와 `inqryDiv` 조회 모드 계약 확정 | validation-run D절 |
| 2026-08-28 | 규격서 첨부 URL 실제 다운로드 확인 (과업지시서 hwp) | validation-run |
| 2026-08-28 | 사전규격 정규화기 결함 기록 | [findings.md](findings.md) |
| 2026-08-28 | 이름 매칭 실패 29건 오프라인 대조. 동일 이름 실패 사례와 가운뎃점 4종 확인 | 이 파일 확정된 사실 절 |
| 2026-08-28 | D-1 확정. 문서 3곳(ARCHITECTURE.md의 사전규격·문서 준비 절, status.md, business-rules.md)을 결정에 맞춰 정정 | [ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md) |
| 2026-08-28 | T-1a 완료. 정규화기·전략 사다리·오프라인 분석 구현 (codex `gpt-5.6-luna` 위임, 검수 후 대조군 보강) | `experiments/lifecycle-linkage-survey/scripts/name_normalize.py` 등, 테스트 36개 |
| 2026-08-28 | 이름 검색 실패 원인 격리 6회. 가운뎃점 확정, 공백·괄호·인코딩 배제 | [validation-run](../validation-runs/20260828-lifecycle-linkage-survey.md) 실패 원인 격리 절, `search-isolation/` |
| 2026-08-28 | `dot_split` 전략과 문자 관용도 probe 구현 (codex 위임). 테스트 46개 | `offline-analysis-v3.md`, `search_isolation_probe.py --char-tolerance` |
| 2026-08-28 | 문자 관용도 24회 측정. 파손 문자 5종 확정, 가운뎃점 동류 추정 반증 | [validation-run](../validation-runs/20260828-lifecycle-linkage-survey.md) 문자 관용도 절, `char-tolerance-probe.json` |
| 2026-08-28 | `dot_split`을 `breaking_split`으로 확장 (파손 문자 5종 전부). 테스트 53개 | `offline-analysis-v4.md` |
| 2026-08-28 | 전략 사다리 재측정 73회. 실패 29건 중 18건 회수, 전체 재현율 87.4% | [validation-run](../validation-runs/20260828-lifecycle-linkage-survey.md) 사다리 절, `ladder-v1/` |
| 2026-08-28 | D-4 확정. 사전규격 연결 상태 4종과 후보 전략 표시 | [ADR-0025](decisions/0025-prespec-link-search-unconfirmed-state.md) |
| 2026-08-28 | D-2 확정. 현재 스키마의 회차 종속 지점과 하위 FK 영향 범위 조사 후 결정 | [ADR-0026](decisions/0026-cumulative-external-identity-schema.md) |
| 2026-08-29 | 채움 곡선 횡단면 측정 22회. 15~17일 평탄화 확인, `chgDt` 신호 불가 판정 | [fill-curve](../validation-runs/20260829-order-plan-fill-curve.md) |
| 2026-08-29 | D-3 확정. 재조회 범위 21일·주기 매일 | [ADR-0027](decisions/0027-order-plan-requery-window.md) |
| 2026-08-29 | T-7 완료(codex 위임). 36곳을 조회/집계로 분류해 정리, 집계는 관측 join으로 전환 | `0004_cumulative_external_identity` |
| 2026-08-29 | `.env`의 컨테이너 전용 키 제거. 스위트 25분 초과 → 3분 36초, 실패 12 → 6 | [findings.md](findings.md) |
| 2026-08-29 | T-8 완료(codex 위임). 사업기회·연결 스키마, 공식/후보 경계를 DB 제약으로 강제 | `0005_opportunity_links` |
| 2026-08-29 | ADR-0028 채택과 구현. 입찰공고 최초 등록 기회, 대기 참조번호 보존과 해소 | [ADR-0028](decisions/0028-bid-first-opportunity-registration.md), `0006` |
| 2026-08-29 | 백엔드 `.venv` 구성(sudo 없이 `--without-pip` + get-pip). `.env`의 컨테이너 전용 경로 3개 제거 | `web/backend/.venv`, `.env`·`.env.example` |
| 2026-08-31 | T-20a 완료(codex 위임 후 직접 검수). 첨부 파일명 취득 경계 — percent-encoded UTF-8 파서, `ProviderResponse`, 확장자 allowlist 밖을 재시도 불가 종료 상태로 구분, 기본 비활성 g2b connector | `assets.py`, `test_prespec_attachment_assets.py` 17건 |
| 2026-08-31 | T-20b 완료. strict G2B provenance, 조건부 자격 재평가 큐, lease-fenced backend worker, quarantine/ClamAV/source 계보, bundle 없는 provider `DocumentVersion`, 재수집 멱등성과 안전한 retry/blocked/failed 전이를 구현 | `0008_prespec_attachment_fetch`, `prespec_attachments.py`, `prespec_attachment.py`, `docker-compose.t7.prespec-attachment.yml`, `test_prespec_attachment_fetch.py` |
| 2026-08-31 | legacy 첨부 `QuarantinedAsset` 위치 인자 어긋남 수정. `object_key`가 `source_system` 자리에 들어가 비-filesystem store에서 격리 원문을 읽지 못하던 결함. dataclass를 `kw_only`로 바꿔 재발을 구조적으로 차단 | `assets.py`, `test_legacy_attachment_provenance.py` 4건 |
| 2026-08-31 | T-3 완료. HWP 변환기가 외부 의존성이 아니라 저장소 벤더링임을 확인하고 host에서 실제 추출 검증 | `app/document_mcp/vendor/rhwp` |
| 2026-08-31 | T-24 완료(codex 위임 후 직접 검수). 누적 `GET /api/pre-specs`와 `/pre-specs` 화면. 추적 예외 판정을 `_tracked_order_plan_conditions()` 한 곳으로 모아 목록과 첨부 자격이 같은 조건을 공유하게 했다. 쿼리 수를 세는 N+1 회귀 테스트 포함. `tsc -b`·`vite build` 통과 | `routers/pre_specs.py`, `PreSpecsPage.tsx`, `test_api_pre_specs.py` 11건 |
| 2026-08-31 | T-20b 완료(codex 위임 후 직접 검수). 조건부 취득 큐·자격 재평가·lease worker·bundle 없는 `DocumentVersion` 적재, egress overlay. **PostgreSQL에서 `0008` upgrade·downgrade·제약조건 7종을 직접 실행 검증했다**(codex는 Docker 권한으로 못 함) | `0008_prespec_attachment_fetch`, `prespec_attachments.py`, `test_prespec_attachment_fetch.py` 25건 |
| 2026-08-31 | T-23 선행 결함 수정(Luna Max `/fast` 위임 후 직접 검수). T-20 clean inspect 결과를 공용 canonical helper로 source/payload hash와 연결해 `DocumentStructure`·`DocumentBlock`으로 저장한다. scan 실패는 구조를 만들지 않고, 구조 저장 실패는 DB·객체 부분 산출물을 rollback한 뒤 안전한 실패 상태로 전이한다 | `document_structures.py`, `document_bundles.py`, `prespec_attachments.py`, 관련 테스트 98 passed·1 MinIO skip |
| 2026-08-31 | T-21 완료. 실제 제안요청서 120건 수집·구조 추출·소제목 분포 측정. T-22의 근거 확보 | [validation-run](../validation-runs/20260831-prespec-rfp-structure.md), `data/experiments/prespec-rfp-structure/` |
| 2026-08-31 | D-12/T-22 확정. 본문과 대응하는 목차 또는 의미 있는 주제 소제목으로 자르고, 번호만으로 자르지 않으며, 경계가 모호하면 `unknown`·사람 검토로 보낸다. 전략·start/end locator·source hash를 보존하고 고정 block 수·전체 문서 자동 투입을 금지 | [ADR-0032](decisions/0032-prespec-overview-cutting-rule.md) |
| 2026-08-31 | T-23 실행 계약 확정. 절단 snapshot과 append-only 모델 attempt를 분리하고, 승인된 사설 vLLM binding이 없으면 `awaiting_model`·결과/완료 시각 `null`, 모호한 절단은 모델 호출 없이 사람 검토로 보낸다. mock은 참조 전용이며 hosted fallback을 금지한다 | [ADR-0033](decisions/0033-prespec-overview-review-runtime-contract.md) |
| 2026-08-31 | T-23 phase 1 완료(Luna Max `/fast` 위임 후 직접 검수). 보수적 RFP 선택, 실제 processor paragraph의 9개 exact topic 절단, immutable snapshot·복합 계보 제약, 자동 준비, safe GET, 상세 화면의 unknown/null·교차 notice ID fail-closed를 구현했다. PostgreSQL 17 집중 회귀 85 passed, Playwright 32 passed, production build 282 modules | `0012_prespec_overview_review`, `prespec_overview.py`, `/api/pre-specs/{notice_id}/overview-reviews`, `PreSpecDetailPage.tsx` |
| 2026-08-31 | D-14/T-23 phase 2 계약 확정. attempt 입력·binding은 불변, 상태·시각·result 참조만 제한적으로 전이하고 모든 전이는 append-only event로 감사한다. 검증 결과는 strict schema의 immutable row로 한 번만 기록하며 안전한 API에는 검증 결과와 binding digest만 노출한다 | [ADR-0035](decisions/0035-prespec-overview-attempt-result-lifecycle.md) |
| 2026-08-31 | T-23 phase 2 DB-light 기반 완료(Luna Max `/fast` 위임 후 직접 검수). `0014`의 FK·UNIQUE·CHECK와 단일 상태 간선 trigger, runtime 최소 권한, event·attempt·review를 한 transaction으로 묶는 service, immutable result/event와 safe v2 API를 구현했다. 추가 교차 table trigger와 중복 ORM policy는 두지 않았다. SQLite 46 passed·1 PostgreSQL-only skipped, PostgreSQL 17 집중 9 passed, production build 282 modules | `0014_prespec_overview_attempt_result`, `prespec_overview.py`, `/api/pre-specs/{notice_id}/overview-reviews/v2` |
| 2026-08-31 | T-24 완료. 누적 사전규격 REST·화면, SW 기본 필터·추적 예외·`추적`/`신규` 표시·첨부 취득 상태 집계와 회귀 테스트 구현 | `/api/pre-specs`, `/pre-specs`, `test_api_pre_specs.py` 11건 |
| 2026-08-31 | T-2b 3번째 종단 관측점. 횡단면 곡선과 21 포인트 어긋남을 확인하고 ADR-0027 근거를 재검토 대상으로 올림 | [validation-run](../validation-runs/20260831-order-plan-longitudinal.md) |
| 2026-08-31 | T-2c 완료. 사전규격 채움 곡선 횡단면 6점 측정. 평탄화 시점과 `chgDt` 사용 불가를 확인 | [validation-run](../validation-runs/20260831-prespec-fill-curve.md), `scripts/prespec_fill_curve.py` |
| 2026-08-30 | 사전규격 첨부 응답 30건 실측. 파일명 인코딩·확장자 분포·크기 확보, T-20 취득 경계 설계 근거 | [validation-run](../validation-runs/20260830-prespec-attachment-probe.md), `data/experiments/prespec-attachment-probe/` |
| 2026-08-31 | T-9 완료. 일회용 PostgreSQL 17에서 배포를 막고 있던 Alembic version 컬럼 결함을 찾아 고치고, `0001`~`0007` upgrade·downgrade·제약조건·trigger를 실행 검증했다. 저장소의 PostgreSQL 테스트를 처음 돌려 `0004` 이후 갱신되지 않은 테스트 seed도 고쳤다 | [validation-run](../validation-runs/20260831-postgresql-migration-verification.md), `alembic/env.py`, `test_db_migrations.py` |
| 2026-08-29 | T-10/T-11/T-13 완료. 발주계획 독립 artifact 적재·관측, 공고의 `orderPlanUntyNo` 투영, flush 후 대기 링크 해소 연결 | `collected-order-plans.json` / `bidops.collected-order-plans.v1`, `loader.py`, `test_order_plan_ingest_resolves_bid_first_waiting_reference` |
| 2026-09-01 | C-2 Phase 0 계약 구현. 정책·binding·전용 artifact schema, 불변 입력/raw hash validator, REST·DB 명세와 활성화 blocker를 고정 | [ADR-0038](decisions/0038-order-plan-c2-phase0-contracts.md), `skills/bidops-screen/contracts/`, `validate_order_plan_phase0.py`; focused validator tests 및 skill suite 통과 |

## 소거한 항목

| 항목 | 소거 이유 |
|---|---|
| 사전규격 응답에서 발주계획통합번호를 찾아 직접 연결 | 8 오퍼레이션 × 3 조회모드 전수 확인 결과 그런 필드가 없다. 이름 검색 후보 연결로 대체 |
| 사전규격 단건 상세 조회로 추가 필드 확보 | 별도 상세 operation이 없고 `inqryDiv=2` 단건 조회도 목록과 같은 23개 필드다 |
| 규격서 의견 본문을 API로 수집 | 오퍼레이션도 응답 필드도 없다. 있는 것은 의견등록 마감일시뿐이다 |
| `bfSpecRgstNo`·`refNo`가 무시되는 필터라는 기록 | 사실이 아니었다. `inqryDiv`를 1에 고정한 채 확인한 오류이며 각각 모드 2·3에서 정상 동작한다 |
| T-1을 API 호출 없이 오프라인으로 끝낼 수 있다는 계획 | 정답 사전규격이 로컬 수집에 17/87만 있어 회수율을 오프라인으로 잴 수 없다. T-1a(오프라인)와 T-1b(호출 필요)로 나눴다 |
| 이름 검색 실패 19.5%가 "표기 차이" 때문이라는 해석 | 격리 결과 최소 8건은 표기가 같아도 가운뎃점 때문에 실패한다. validation-run의 해당 서술을 정정했다 |
| `+`/`%20` 질의 인코딩이 원인이라는 가설 | 같은 문자열을 `%20`으로 보내도 0건이다 |
| 가운뎃점처럼 보이는 문자 5종이 모두 검색을 깨뜨린다는 추정 | 측정 결과 `·`(U+00B7)만 깨뜨리고 `・`·`‧`·`․`는 무해하다. 추정을 사실로 적지 않아 갈릴 수 있었다 |
