# 구현·검증 현황

기준일: 2026-09-03

`구현됨`은 코드와 계약이 존재한다는 뜻이고, `검증됨`은 기록된 명령이 해당 범위에서 통과했다는 뜻이다. Mock 결과, 과거 브랜치 결과, 현재 worktree 결과, 외부 운영 승인을 서로 대신하지 않는다.

## 제품 방향

목표 생애주기는 `발주계획 조기 탐색 → 사전규격 RFP 선별·심층 검토 → 입찰공고 추적·변경 확인 → 사람 최종 Go/No-Go`로 정했다.

- 발주계획과 사전규격은 매일 독립 수집한다.
- 발주계획은 일반용역·기술용역 전체를 수집하고 SW사업대상을 선필터로 쓰지 않는다.
- 발주계획 사람 검토는 월요일·목요일에 수행한다.
- C-2 발주계획 1차 선별은 `BM25 Top 300 + Qwen`으로 확정했다. BM25 탈락은 Qwen 비관련 판정으로 바꾸지 않고 별도 보존한다([ADR-0037](decisions/0037-order-plan-c2-bm25-top300-qwen.md)).
- 사전규격은 일반용역·기술용역 전체를 수집하고 SW사업대상은 표시 값으로만 남긴다([ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md)). 저비용 선별 뒤 사람 승인을 거쳐 심층 검토한다.
- 심층 검토 뒤 사람은 `계속 추적|보류|종료`를 선택한다. 입찰공고가 올라오면 사전규격 대비 중요 변경을 확인하고 최종 `Go/No-Go`는 다시 사람이 결정한다.
- 자동 연결 실행과 각 단계의 수동 실행·재시도는 같은 execution, artifact, 상태 전이를 공유한다.

## 현재 구현

| 영역 | 구현 상태 | 검증 상태 |
|---|---|---|
| 기존 나라장터 공고 수집·정규화·표본 | 구현됨 | 파이프라인 단위·교차 테스트의 과거 64건 통과 기록 있음 |
| 발주계획 C-2 선별 방식 | `BM25 Top 300 + Qwen`으로 선택 완료; Phase 0 policy·binding·전용 schema·read-only validator 구현, 제품 adapter·DB·API는 미구현 | validator가 source 625건, approved input digest, historical evidence와 C-1 partial gold(22 human / 603 draft / 87 remaining)를 대조하고 `valid_but_blocked` 반환; 실행·활성화는 불가([ADR-0038](decisions/0038-order-plan-c2-phase0-contracts.md)) |
| 다섯 관점·반론·종합 1차 판정 | 구현됨 | fake 테스트와 단일 live Qwen 성공·중단 기록 있음; 40건 운영 품질 승인은 없음 |
| 결정적 HTML·피드백 YAML | 구현됨 | 파이프라인 테스트에 포함됨 |
| FastAPI 회차·공고·리뷰·프로필·지표 | 구현됨 | 전체 backend suite `1046 passed, 5 skipped, 0 failed` |
| 프로필 조회 projection | 세 route가 승인된 불변 snapshot의 version·digest에 고정되고 구조화 항목·unknown만 반환함. filesystem source, raw block·raw text, source line, 가공되지 않은 parse error를 닫힌 안정 오류 코드로 대체하고 snapshot이 없으면 503으로 fail closed함([ADR-0023](decisions/0023-company-profile-minimal-projection.md)) | 해결; 실제 프로필 문자열 sentinel 회귀 테스트, backend `1041 passed, 5 skipped, 0 failed`, visual `598 passed, 10 skipped, 0 failed` |
| legacy notice 첨부 | quarantine→MIME/구조·ClamAV 검사→source object 승격 후 `safe` 파일만 legacy Attachment로 등록하고, API `stored_path` 제거 및 `/app/web/data` 전체를 덮는 `web-data` named volume 적용 | A-2 회귀 통과; backend `1041 passed, 5 skipped, 0 failed`; Compose `COMPOSE_OK` |
| legacy mutation actor·감사 | 첨부 upload/delete, 기관 포털 create/update, 정책 create/candidate/activate에 actor header 검증과 append-only `AuditEvent` 적용 | A-4 회귀 통과; backend `1041 passed, 5 skipped, 0 failed`; frontend tsc/build 통과, visual `598 passed, 10 skipped, 0 failed` |
| PostgreSQL 17·Alembic | 공유 worktree head `0015_bid_delta_final_decision`; T-23 revision `0014_prespec_overview_attempt_result` | T-23은 임시 PostgreSQL 17에서 `0014`까지 구조 제약·overview 상태 전이 trigger 1개와 role allowlist를 검증했다. 별도 `0015`의 검증으로 재사용하지 않는다 |
| 누적 관측·첨부 보존 | 신규 observation의 결정적 snapshot/hash와 provider 첨부 retire/revive 구현됨 | 같은 회차 exact replay no-op, 다른 bytes rollback, legacy `null` 보존, 수집에서 사라진 첨부 비삭제 회귀 통과 |
| opportunity authoritative 소유권·병합 | 공식 확정 또는 사람 수락 후보만 active 소유권을 가지며 secondary row를 삭제하지 않는 merge lineage 구현됨 | focused SQLite/API/loader 회귀와 PostgreSQL 17 migration·제약 검증 통과; 추적 선택·recheck 충돌은 자동 병합하지 않음 |
| 판정·사람 리뷰 revision | 현재 projection과 분리된 notice별 append-only 이력, execution·승계 parent·exact judgment pin 구현됨 | replay no-op/conflict rollback, 부분 실패 projection 보존, YAML/SQLite legacy `null` lineage, PostgreSQL 불변 trigger 검증 통과 |
| MinIO·ClamAV·문서 격리 | 구현됨 | Mock T7 E2E 통과; 실제 운영 권한 matrix는 미검증 |
| document bundle·준비 API | 7개 Lean API와 attachment version/current·bundle ordinal DB 제약 구현됨 | backend 테스트, PostgreSQL migration/preflight/autogenerate, Mock E2E 통과 |
| 3단계 심층 검토·보고서·근거 API | 7개 Lean API 구현됨 | deterministic Mock provider E2E 통과; 실제 Qwen 품질 승인은 없음 |
| React 관리자 화면 | 기존 공고·판정·ready bundle 이후 심층 검토 구현됨 | tsc·production build 통과; 전체 visual `646 passed, 10 skipped, 0 failed` |
| 화면 시안 기준 B-F | 공통 review primitive, C-2 발주계획 split 화면, 사전규격 상태 그룹·선택 상세, 정보구조·dashboard 동선, 상세·심층검토 공통 skeleton을 구현함. 적합성·준비·추적·Go/No-Go 상태는 각각 유지함 | 독립검증에서 build 통과, PreSpecs mobile/tablet `54 passed`, DeepReview desktop `10 passed`, `git diff --check` 통과. 14개 승인 PNG·manifest·crop 기반 design suite는 없어 전체 시각 게이트가 차단됨([findings.md](findings.md)) |
| 무드보드 색 팔레트 · 단계 A | **팔레트 승인 + 단계 A 완료(2026-09-04).** 무드보드 `docs/design/moodborad.jpg`의 5색 anchor를 프로젝트 소유 테마 `bidops`로 옮기고 적합성 등급 4단을 slate 농도 ramp로 정의하기로 결정함([ADR-0047](../design/ADR.md#adr-0047-무드보드-기반-색-팔레트와-테마-소유권), [design/PRD.md](../design/PRD.md) §4.1) | 앱이 `bidops` 테마(무드보드 팔레트)로 돈다. `src/themes/bidops/`(171 token overrides + `grade-ramp.css`), `scripts/check-contrast.test.mjs`, `tests/design-shell.spec.ts`를 추가했고 AppShell·페이지 10곳의 scope와 `main.tsx` import를 옮겼다. `theme.css`의 `@theme`이 `:root`로 방출돼 Astryx 테마를 이기던 토큰 4개를 제거하고 shadcn `--color-accent`를 `--color-shadcn-accent`로 옮겼다([engineering-notes.md](../engineering-notes.md)). 지원 폭을 1280~1920px로 좁히고 검증 viewport를 laptop 1280×800·desktop 1440×900 두 폭으로 고정했다(ADR-0046). `--color-nav-text` 중복 정의를 없애고 사이드바 본문을 `--color-on-dark`로 통일했다. 충돌 토큰은 미이행 화면 가드 없이 **전역 적용**하기로 결정했다(2026-09-04). **검증:** 대비 6 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped(1280·1440·1920px 오버플로 포함), 전체 Playwright 370 passed·75 failed·3 skipped. 실패 75건은 `visual.spec` 스냅샷 73건(팔레트 변경에 따른 예상 실패 — 승인 없이 덮어쓰지 않는다)과 `order-plans.spec.ts:287` 2건(390px 전제의 기존 실패, 팔레트와 무관). **남은 것:** 시안 렌더 입력 교체와 v2 기준 이미지는 [design/PLAN.md](../design/PLAN.md) §0-4 통과 뒤다. 그때까지 앱은 승인된 시각 기준선 없이 새 팔레트로 돈다. 팔레트 적용은 [design/PLAN.md](../design/PLAN.md) §0-4(생성기 복원 대조) 통과 뒤에만 시작한다 |
| 공통 화면 primitive · 단계 B | **완료(2026-09-04).** 결정 액션 배치 두 형태, 접힌 보조 입력 영역과 append-only revision 이력, 등급 4단 한 벌, 좁은 폭 전환 제거 ([design/PLAN.md](../design/PLAN.md) 단계 B) | `ReviewDecisionBar`(분할 화면 pane 바닥)·`ReviewSecondaryInput`(접힌 보조 입력)·`ReviewRevisionHistory`(append-only)를 `ReviewPrimitives.tsx`에 추가했다. 단독 상세는 기존 `StickyDecisionHeader`를 계속 쓰고 한 화면에서 두 배치를 섞지 않는다. `SplitWorkspace`의 `mobileView`와 `review-primitives.css`·`order-plans.css`의 좁은 폭 분기를 없애 세 화면(`OrderPlansPage`·`QueuePage`·`PreSpecsPage`)이 어느 폭에서도 두 pane을 유지한다(ADR-0046). `.badge-grade-*`·`.rail-grade-*`가 `grade-ramp.css`의 `--bo-grade-*`를 읽고, 쓰이지 않던 두 번째 등급 스케일(`.c2l-grade-tag`)을 지웠다. 390px를 전제하던 `order-plans.spec.ts:287`·`pre-specs.spec.ts:520`은 지원 폭 기준의 반대 불변식(두 pane 유지, 제자리 pane 교체, 페이지 이동 없음)으로 다시 썼다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `review-primitives.spec.ts` 16 passed, 전체 Playwright 382 passed·74 failed·2 skipped(단계 A 기준선 371·75·4). 실패 74건에 **새 실패는 없다** — 73건은 단계 A에서 이어진 `visual.spec.ts`(팔레트 스냅샷 72 + `/queue` 1280px 오버플로 1, 단계 B 변경을 되돌려도 같은 값), 1건은 `visual.spec.ts:257` flake(단독 실행 통과)다. **남은 것:** `OrderPlansPage`의 접힌 보조 입력은 아직 `defaultIsOpen`이다. 단계 C가 추적 결정을 pane 바닥의 결정으로 들이면 시안의 접힌 기본값으로 되돌린다 |
| 발주계획 추적 결정 계약 · 단계 C 선행 | **요청안 작성, 백엔드 파트 검토 대기(2026-09-04).** ADR-0045 결정 4가 추적 결정을 발주계획 화면의 결정 1로 채택했으나 그것을 읽을·쓸 REST 경로가 없다 | [`order-plan-tracking-contract-request.md`](../design/order-plan-tracking-contract-request.md)로 요청안을 보냈다. 조사 결과 **새 table은 필요하지 않을 가능성이 높다** — 소유 사업기회와 `stage='order_plan'` official 링크를 `ingest/loader.py`가 이미 만들고, 상태 4값(`미선택`·`계속 추적`·`보류`·`종료`)과 append-only `AuditEvent`도 이미 있다. 없는 것은 (a) 발주계획 목록·상세 응답이 그 상태를 싣지 않는 것과 (b) 발주계획 식별자로 쓸 경로가 없는 것 둘이다. **묻는 것 5가지**는 요청안 §8에 있다(v2 schema 여부, 전용 endpoint 대 기존 PATCH, `opportunity_not_found` 409, `AuditEvent` 투영 대 전용 table, 사유 자유문자열 대 고정 집합). **검증 없음** — 제안이고 채택이 아니다. 단계 C 화면은 요청안 §7의 규칙(adapter 한 곳, 낙관적 갱신 금지, `계약 미구현`을 `미선택`으로 바꾸지 않음, fixture는 구현 근거가 아님) 아래 먼저 만들고, 계약이 구현·검증되기 전에는 단계 C를 완료로 적지 않는다 |
| 발주계획 화면 · 단계 C | **화면 작업 완료, 단계는 미완료(2026-09-04).** 추적 결정을 상세 pane 바닥의 결정 액션으로 만들고 사람 판단 수정을 접힌 별도 영역으로 분리했다 ([design/PLAN.md](../design/PLAN.md) 단계 C) | `추적 시작`·`보류`·`추적 종료`·`이번 건 넘기기`가 pane 바닥에 있고 선택 즉시 다음 건으로 이동한다. 사람 판단 수정은 접힌 채로 `새 revision 저장`을 스스로 소유하며 두 결정의 mutation·경로·요청이 모두 다르다. 저장된 뷰를 segmented control로 바꿨고(축별 다중 선택과 AND/OR·URL 계약은 유지), 상단 요약 한 줄과 `실행 상세` 진입점, 목록 머리글의 조합 의미와 바닥의 숨김 고지, `실행 기록` 탭 이름을 시안에 맞췄다. 추적 상태의 세 값(`계약 미구현`·`사업기회 미연결`·`미선택`)을 서로 바꾸지 않는다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `order-plans`+`review-primitives` 52 passed, 전체 Playwright 391 passed·73 failed·2 skipped. 실패 73건은 단계 A에서 이어진 `visual.spec.ts` 그대로이며 **새 실패는 없다**. 단계 C에서 결정 액션 바가 상세 pane 전체를 덮던 flex 회귀를 잡아 고쳤고 바 높이를 테스트로 고정했다. **미완료 사유:** 완료 게이트 2·3(두 결정이 서로를 덮지 않는다)은 서버가 있어야 판정한다. 저장 경로는 아직 요청안이며 fixture는 구현 근거가 아니다 |
| 사전규격 화면 · 단계 D | **완료(2026-09-04).** 추적 상태를 묻는 자리를 하나로 제한하고 신규 건에만 결합 조작을 준다 ([design/PLAN.md](../design/PLAN.md) 단계 D, ADR-0045 결정 6) | 발주계획에서 승계한 건(`origin='추적'`이고 추적 상태가 `미선택`이 아님)은 결정 form 자체를 그리지 않고 `계속 추적 · 발주계획에서 승계` 배지만 남긴다. `보류`·`추적 종료`를 두 사전규격 화면에서 없앴다 — `TRACKING_DECISION_STATUSES`가 `계속 추적` 하나가 됐고 그 둘은 사업 추적에서만 고른다는 문구를 남긴다. 신규 건에만 `추적 시작하고 심층 검토`를 한 조작으로 주되 **기록은 둘이다** — 추적 시작만 저장하고 심층 검토 실행 승인은 상세로 보낸다(`createDeepReview`가 ready 문서 묶음을 요구하므로 한 요청으로 합치면 존재할 수 없는 심층 검토를 만든다). 승계 건이 막다른 카드가 되지 않도록 상세 pane에 `심층 검토 실행 →` 진입점을 두었다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `pre-specs.spec.ts` 29 passed, 전체 Playwright 394 passed·74 failed·2 skipped. 실패는 단계 A에서 이어진 `visual.spec.ts` 73건 + flake 1건(`common-interactions.spec.ts:337`, 단독 실행 통과)이며 **새 실패는 없다** |
| 문서 준비·실패 attempt 재시작 화면 | typed frontend API·type 변경은 worktree에 있으나 화면과 연결은 미구현 | 화면 검증 없음 |
| T-23 사전규격 overview phase 2 기반 | immutable result/event, 제한된 attempt lifecycle service, safe v2 projection 구현됨; 실제 model transport·worker는 미구현 | SQLite 46 passed·1 PostgreSQL-only skipped, PostgreSQL 17 집중 9 passed, production build 282 modules |
| 사전규격 개요 검토 화면 | v2 결과 projection이 화면에 연결됨. 권고·검증 상태·요약·조건과 기한·미확인·근거·입력 한계를 판단 순서로 내고 계보는 접어 둔다. 근거 locator는 `GET /document-structures/{id}/pages/{page}`로 원문을 열어 앞뒤 블록과 함께 강조하며, `block_key`가 원문에 없으면 보정하지 않고 사람 검토로 보낸다. `verification_action`이 없는 unknown과 `validation_status != passed`는 각각 표식과 경고로 구분한다 | 2026-09-01, 커밋 `56aeb0d`·`77700a5`. Playwright `630 passed, 10 skipped, 0 failed`, tsc·build 통과 |
| 사전규격 심층 추적 결정 동선 | 개요를 읽은 화면에서 계속 추적·보류·종료를 기록한다. `GET /pre-specs`에 `notice_pk` 필터를 더해 `opportunity_id`·`tracking_status`·첨부 집계를 한 응답으로 읽는다(`notice_pk`가 있으면 `sw_only`를 적용하지 않는다. `source_type = 'pre_spec'`은 항상 적용된다). 담당자 이름과 사유가 모두 필수이며 개요 권고를 추적 상태로 자동 반영하지 않는다 | 2026-09-01, 커밋 `26cdab4`. backend `1046 passed, 5 skipped, 0 failed`, Playwright `646 passed, 10 skipped, 0 failed` |
| T7 stack 조립 | PostgreSQL, MinIO, ClamAV, web, document worker, analysis worker, 일부 영속 volume, 목적별 egress overlay 구현됨 | 개발 stack health와 Ollama endpoint 도달 기록은 있으나 보안·복구 blocker로 운영 배포 불가 |
| 구조화 안전 로그 | 기반과 주요 worker·queue·scheduler 계측 구현 중인 worktree 변경 | 신규 단위 테스트 일부 통과 기록, 현재 전체 worktree green 아님 |
| 개발용 hosted Codex 심층 검토 reference | 기본 비활성·notice allowlist에 더해 닫힌 payload allowlist를 두고, 회사 profile·prior stage 결과·승인되지 않은 입력 필드가 있으면 prompt 생성과 subprocess 이전에 `external_provider_payload_not_approved`로 fail-closed한다 | 해결; 차단 시 runner 미호출을 단언하는 회귀 테스트가 있고 backend `1041 passed, 5 skipped, 0 failed` |
| runtime image 회사자료 제외 | current profile·회사 실적 제목 TSV·vendored baseline을 build context와 runtime image에서 제외하고, `web`에만 read-only host bind mount로 주입하도록 경계를 고정함 | 해결; runtime contract `11 passed`, profile snapshot keyword `14 passed`, 실제 image build/run/find, `COMPOSE_OK`, backend `1041 passed, 5 skipped, 0 failed` |
| backup·object-first restore script | restore가 source→target version mapping을 기록하고 backup hash를 실제로 검증하며, active manifest를 `content_object_location`에서 생성해 복구된 집합과 일대일 대조함. 암호화 model-response는 `ContentObject.sha256`이 plaintext라 stored-byte 비교 대신 존재·target version만 검사함 | 해결; disposable MinIO 2개와 PostgreSQL 17로 정상 복구 exit 0, 손상 backup·미복구 active object·복구 후 삭제 세 경우 exit 1 확인 |

T-23 `0014` 검증 경계의 PostgreSQL application schema는 legacy 13개, 심층 검토 25개,
판정 runtime 12개, 누적 identity 5개, 첨부 fetch 1개, 판정·리뷰 revision 2개, 사전규격
overview 5개로 총 63개 table이다. `0015`가 더한 입찰 delta 5개는 이 수치와 T-23 검증
증거에 포함하지 않는다. 그 5개를 합친 현재 head `0015_bid_delta_final_decision`의 application
schema는 68개이며, 별도로 빈 PostgreSQL 17 `upgrade head`와 `0014↔0015` 왕복을 검증했다.
입찰 delta는 저장·REST·화면까지 있으나 비교를 실제로 계산하는 worker와 모델 binding 실행이
없어 운영 활성화 상태가 아니다. SQLite는 격리 테스트와 일회성 이전 입력에만 남아 있다.

## 기록된 검증 증거

### 현재 통합 소스 기준

| 검증 | 기록된 결과 | 해석 |
|---|---|---|
| frontend `npm run build` | 성공, Vite 6.4.3, 282 modules | 현재 통합 UI production build |
| T-23 사전규격 상세 Playwright | 32 passed | 네 viewport에서 정본 ID, unknown, 교차 ID fail-closed, 안전 오류를 검증 |
| frontend visual update·비갱신 | 각각 184개 중 174 passed, 10 intentional skipped | 네 viewport의 통합 UI 기준선 |
| backend pytest 초기 통합 리뷰 | 733 passed, 5 skipped, 2 failed | 실패 2건은 현재 Git history에 승인 baseline blob이 없는 환경 문제 |
| Phase 0–2 변경 후 backend | 741 passed, 5 skipped, 같은 2 failed | 로깅·Compose 변경 뒤 통과 수 증가, 전체 green은 아님 |
| MVP DB 보완 후 backend + PostgreSQL 17 | 948 passed, 5 skipped, 6 failed | DB·migration·revision·권한 회귀는 통과. 실패는 T14 전용 환경변수/격리 DB 미설정 4건과 승인 baseline Git blob 부재 2건 |
| MVP DB 최종 집중 회귀 + PostgreSQL 17 | 155 passed | fresh `0001→0013`, downgrade-upgrade, preflight, revision, 문서 무결성, overview 최소권한, Alembic autogenerate를 교차 검증 |
| T-23 최종 집중 회귀 + PostgreSQL 17 | 85 passed | overview 권한·절단·계보·migration·문서 무결성을 최종 변경 뒤 실제 role로 재검증 |
| T-23 phase 2 DB-light 집중 회귀 | SQLite 46 passed·1 PostgreSQL-only skipped; PostgreSQL 17 9 passed | result/event·상태 전이 service·v2 projection·runtime privilege와 단일 상태 간선 trigger를 검증; 전체 backend green을 뜻하지 않음 |
| T14/profile harness 최종 backend + PostgreSQL 17 | 992 passed, 5 skipped, 6 warnings | 최소 환경에서 임시 PG17·fresh DB·Alembic head를 자동 구성. T14 4건은 해결됐고 profile 2건은 승인 Git blob 부재를 fail-closed로 검증 |
| T7 stack V2 | services healthy, `/api/health` 성공, 구조화 worker log 관측, 승인 Ollama endpoint 도달 | 기동·관측·network 경계 검증; 실제 판정 품질 검증 아님 |
| static diff check | 당시 통합 UI 변경에서 성공 | 이후 worktree 변경의 전체 검증으로 재사용하지 않음 |

최근 끝까지 완주한 backend 전체 suite는 1046 passed, 5 skipped, 6 warnings이며
실패 0건이다(2026-09-01).
저장소 `.env`를 상속하지 않은 최소 환경에서 일회용 PostgreSQL 17 server, random DB,
Alembic head, 임시 data·attachments 경로를 pytest 수집 전에 구성했고 종료 후 소유
container가 남지 않음을 확인했다. skip 5건은 별도 MinIO가 필요한 4건과 target
container 경로에만 적용하는 installed-set 1건이다.

승인 profile baseline commit `ee621835db934ddac944f7a07a986ed0b73ecc7a`는 현재 Git object
DB에 없다. 다만 byte-identical 파일이 `web/backend/app/screening/baseline_company_profile.md`로
벤더링돼 있고 `BASELINE_PROFILE_SHA256`으로 검증되므로 `test_profile_snapshot*` 14건은
모두 통과한다. 2026-08-31 결정에서 이 상태를 그대로 두기로 했다. 이 commit은
`model_comparison` 품질 gate 전용 역사 anchor이며 운영과 무관하다 —
`operational_approval`은 `profile_source = "current"`를 요구하고 런타임의
`snapshot_current()`는 현재 `docs/reference/company-profile.md`
(sha256 `96731dd5f77d…`)를 읽는다. 두 경로는 의도적으로 분리돼 있다.

### 2026-09-03 화면 시안 B-F 독립검증

- 별도 Orchestration 작업자가 파일을 수정하지 않는 조건으로 현재 worktree를 재검증했다.
- `cd web/frontend && npm run build`: TypeScript strict build와 Vite production bundle 통과.
- `npx playwright test tests/pre-specs.spec.ts --project=mobile --project=tablet`: `54 passed`(각 27건, 390×844·768×1024).
- `npx playwright test tests/deep-review.spec.ts --project=desktop`: `10 passed`(1440×900).
- `ReviewBar.tsx`의 보조 selector 3개는 공통 `ReviewFilterSelector`의 clear 계약과 `null → ""` 복원을 사용하며, `DeepReviewPage.tsx`의 인라인 style·hex·px 검색은 0건이다. `git diff --check`도 통과했다.
- `npm run test:design`: `5 passed, 3 skipped`. 현재 스위트는 공통 light/neutral shell smoke만 검증하고, PLAN이 요구하는 14-artboard 승인 PNG·manifest·fixture/viewport/crop 비교를 수행하지 않으므로 전체 완료로 기록하지 않는다.

### 보존된 과거 증거

- 기존 pipeline 테스트는 collect 28, report 13, screen 21, root 2로 총 64개가 통과했다. 현재 변경 전체의 통과로 간주하지 않는다.
- Deep Review Mock T7 E2E는 PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web에서 `passed=true`였다. 외부 모델 호출은 없었고 Qwen 품질 근거가 아니다.
- 실제 Ollama 단일 판정은 한 번 실패한 뒤 generation binding을 고정한 재실행에서 7개 logical stage, 8 attempts, v3 judgment 1건으로 성공했다. 별도 stop 실행도 중단 artifact를 보존했다. 40건 A/B와 운영 activation을 뜻하지 않는다.
- 사설 vLLM 후보는 제한된 구조화 입력에서 호출·validator 통과 기록이 있으나 server image와 model artifact digest가 아직 immutable하게 고정되지 않았다.

## 진행 중 작업 기록

발주계획·사전규격·입찰공고 생애주기 구현의 확정 사실, 대기 중인 결정, 할 일과 끝낸 일은
[`lifecycle-workstream.md`](lifecycle-workstream.md)에서 갱신한다. 아래 순서의 6~10번이 그 범위다.

## 다음 작업 순서

우선순위 순이다. 상세와 착수 조건은 [`../PLAN.md`](../PLAN.md)의 C-2 단계와
[`lifecycle-workstream.md`](lifecycle-workstream.md), 현재 상태는 이 파일과
[`findings.md`](findings.md)가 정본이다.

1. **사람 몫 — 지금 던져두면 병렬로 돈다.** C-2 방식 선택은 완료했다. 기존 997건 실험의 gold 재판정 9건 확인, 별도 C-2 625건 gold의 잔여 87건 확인, D-7 방화벽 승인 상신이 남아 있다.
2. **테스트 harness.** MinIO versioning fail-open과 host-wide DB·MinIO port publish는 2026-09-01에 닫았고 **알려진 운영 배포 blocker는 0이다.** `web/run-web-tests.sh`는 2026-08-31부터 있고(`84bbcc5`) 임시 PostgreSQL 17에서 backend pytest와 frontend build를 돌린다. 2026-09-01에 Playwright visual 회귀를 같은 진입점에 넣어 화면 검증이 문서에만 있는 게이트로 남지 않게 했다. **남은 것은 CI다.** 개별 파일만 지정해 pytest를 직접 치면 postgres 테스트가 여전히 조용히 skip되며, 이 저장소는 같은 부류 결함에 두 번 데였다.
3. **껍데기를 실제로 도는 기능으로.** 입찰 delta 계산 worker와 모델 adapter, T-23 사전규격 개요 model adapter·worker, 문서 준비·실패 attempt 재시작 화면, T-19 판정 모델 계보 projection. 전부 결정이 끝나 막는 것이 없다. **사전규격 개요는 2026-09-01에 화면 몫을 끝냈으므로 남은 것은 worker다.** worker가 없는 동안 실데이터는 대부분 `awaiting_model`에 머물며, 화면은 승인된 모델 binding이 없어 실행되지 않는 상태임을 알린다.
4. **판정을 믿을 수 있게.** 실제 model artifact digest·대표 HWP/PDF gold·사람 판정으로 Qwen·vLLM 품질 gate 2건을 측정하고, screening v3를 보고서 renderer에 명시적으로 연결한다.
5. **선별 제품 — C-2 선택 완료.** BM25 Top 300→Qwen threshold·감사 표본 정책 확정 → 전체 발주계획 원본과 방식별 결과를 저장하는 불변 수집 회차·DB 계약 → 내부 opportunity와 plan·pre-spec·bid 공식 관계 및 사람 확인 대기 relation 후보 → 사전규격 독립 일일 수집·저비용 1차선별·사람 승인 gate 연결 → `계속 추적|보류|종료`, 입찰공고 발견, 사전규격 대비 material delta, 최종 사람 Go/No-Go.
6. **이후 범위.** 실제 secret·MinIO allow/deny·egress firewall·backup/restore를 운영 환경에서 검증하고, 개발계정 API 요청 수를 실측해 증액 근거를 준비하며, SSO·역할 권한과 dashboard·외부 알림을 설계한다.

2026-09-01에 C-2 방식 선택을 완료했다. 사람 확인이 남은 항목은 기존 997건 실험의 gold 재판정 9건, 별도 C-2 625건 gold의 잔여 87건, D-7 방화벽 승인이다.
2026-09-01에 운영 배포 blocker A-1~A-6 여섯 건을 전부 해소했다.
D-8 종단 관측은 2026-09-08·09-13·09-14에 계속 받는다.

위 단계 전에는 hosted OpenAI 자동 fallback, scheduler·always-on 자동 활성화, 자동 입찰 제출, 발주처 연락, 모델의 최종 참여 결정을 추가하지 않는다.
