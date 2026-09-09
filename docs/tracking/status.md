# 구현·검증 현황

기준일: 2026-09-09 (v4 explicit reference 운영 상태와 실제 UI 인수 대기)

사전규격 v4 페이지 개요·PDF 선행·회사 핏 연속 처리의 진행 계획과 단계별 인수/중단 경계는 [prespec-v4-implementation-plan.md](prespec-v4-implementation-plan.md)에 보존한다. 이 계획은 현재 회사 핏 구현·검증과 v4/PDF 후속 구현을 구분하며, 완료·운영 적용 근거를 대신하지 않는다.

`구현됨`은 코드와 계약이 존재한다는 뜻이고, `검증됨`은 기록된 명령이 해당 범위에서 통과했다는 뜻이다. Mock 결과, 과거 브랜치 결과, 현재 worktree 결과, 외부 운영 승인을 서로 대신하지 않는다.

## 사전규격 v4 최신 운영 상태 (2026-09-09)

- 명시 sample activation은 OFF이다. `AuditEvent` `07c1d75a-c36a-48c7-9de5-a7efa1e741c7`가 `reference_samples_complete_with_142_unverified` 사유를 남긴다. 142·35·59 모두 grade는 `None`이며 automatic priority/auto-deep를 우회하거나 강제하지 않았다. 사람 결정은 변경하지 않았다.
- notice 35 개요는 result `a28a188b-0638-4dbb-b867-ea5a12c6c168`로 completed/current다. 회사 핏은 attempt `bb2d93f4-1915-4e72-a4f5-f647d8860a5e`, `completed/current/unknown`, raw SHA-256 `c147828b4efa9423d7af2ac138705e8d775a5a8c674a543275fb35dfc276d822`이며 API가 Luna reference 첫 응답과 exact 일치한다.
- notice 59 개요는 result `04d6182f-f073-450a-b8be-30f141db9f02`로 completed/current다. 회사 핏은 attempt `4af5b488-59c2-445e-8cf3-4a33baad44be`, `needs_human_review/current`, result는 `null`, raw SHA-256 `67b292a7ca012a7995f7a98d7be11d972fd97e72b603cf5e17552cb272254f11`이다. `unsupported_number` 사유로 index 0의 선택 근거에 24시간이 없어졌고, 암호화 raw를 보존했으며 보정·재시도하지 않았다.
- notice 142 PDF는 반복 timeout 뒤 `unverified`다. offline Luna JSON은 참조 입력으로만 보존하며 성공 PDF/current로 승격하지 않았다. 35/59 실제 UI는 사업명 검색·목록/상세·독립 상세·refresh/reentry, 1280×800·1440×900, API 본문·제한사항·prompt/result ID·PDF hash/link까지 통과했다. 35 `unknown` 근거와 59 `needs_human_review` 오류·안전 문구·판정 본문 비노출도 확인했다. 결과는 `.dryforge/prespec-v4-luna-20260909/ui-acceptance-result.json`과 script에 보존한다. 142 PDF와 automatic deep는 미검증이다.
- `localhost:18887/pre-specs/35`와 `/pre-specs/59`는 배포 확인 경로다. 18787 bind 실패는 기록된 운영 제약이다. `overview-actual`은 중지했고 `prespec-actual`은 원래 `sleep infinity`로 복원했다. document-worker 두 개는 `bidops-v4-luna-reference:20260909-final`, 1 GiB 조건으로 복원됐다.
- persistent reference artifacts는 `.dryforge/prespec-v4-luna-20260909/{overview-generation,company-fit-input-35-59,company-fit-generation-35-59}`에 두며 credentials를 포함하지 않는다. 실제 UI acceptance 결과는 `ui-acceptance-result.json`과 script에 보존했고, 전체 v4 계획 완료를 주장하지 않는다.

## 제품 방향

목표 생애주기는 `발주계획 조기 탐색 → 사전규격 RFP 선별·심층 검토 → 입찰공고 추적·변경 확인 → 사람 최종 Go/No-Go`로 정했다.

- 발주계획과 사전규격은 매일 독립 수집한다.
- 발주계획은 일반용역·기술용역 전체를 수집하고 SW사업대상을 선필터로 쓰지 않는다.
- 발주계획 사람 검토는 월요일·목요일에 수행한다.
- C-2 발주계획 1차 선별은 `BM25 Top 300 + Qwen`으로 확정했다. BM25 탈락은 Qwen 비관련 판정으로 바꾸지 않고 별도 보존한다([ADR-0037](decisions/0037-order-plan-c2-bm25-top300-qwen.md)).
- 사전규격은 일반용역·기술용역 전체를 수집하고 SW사업대상으로 수집 범위를 줄이지 않는다([ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md)). 자동 심층 분석은 별도 조건과 회사 핏 게이트를 충족할 때 시작하며, 추적 승인과 최종 입찰 결정은 사람이 한다. 회사 핏을 이용한 자동 시작은 현재 참조 실행 전용이다.
- 심층 검토 뒤 사람은 `계속 추적|보류|종료`를 선택한다. 입찰공고가 올라오면 사전규격 대비 중요 변경을 확인하고 최종 `Go/No-Go`는 다시 사람이 결정한다.
- 자동 연결 실행과 각 단계의 수동 실행·재시도는 같은 execution, artifact, 상태 전이를 공유한다.

## 현재 구현

| 영역 | 구현 상태 | 검증 상태 |
|---|---|---|
| 사전규격 회사 핏 판정·자동 시작 게이트 | 검증된 최신 개요와 승인 프로필을 고정해 `matched/mismatch/unknown`과 양쪽 근거를 저장한다. 현재 입력의 `matched`만 기존 자동 심층 생성 경로로 연결한다. 목록 선택 상세·개별 상세에서 이유, 미확인 항목, 입력 버전, 실제 심층 생성 여부를 표시한다. **기본 비활성·명시 sample 참조 실행 전용이며 automatic deep는 활성화하지 않았다.** 2026-09-09 explicit 35는 `completed/current/unknown`, 59는 `needs_human_review/current`로 저장했고, 59의 암호화 raw를 보존했다. | [최종 상태](../validation-runs/20260909-prespec-v4-cohort-ops.md) |
| ERP 사전규격 개별 상세 | 2026-09-08 승인 시안 적용. 왼쪽 일반 스크롤, 오른쪽 400px 결정 패널. 공식 번호 16px·복사·수집 URL 원문 열기, 핵심 요약·확인 사항, 사유 드롭다운·기타·담당자·저장. 서버 18787 반영 | build·대비 9개·신규 8개·최종 집중 4개 통과. 전체 455 passed·11 failed·6 skipped 중 의도한 품질 상세 접기 검사 1개 수정 후 재통과, 기존 실패 10개 남음. 시각 19개·실제 API 반영 전후 각 8개. [검증 기록](../validation-runs/20260908-prespec-detail-ux-implementation.md) |
| 승인 ERP 대시보드 | 2026-09-08 승인 HTML·TSX/CSS를 직접 적용. 네 누적 업무 → 회차 선택 → 67:33 네 패널, 15px 공고명·기관, URL 필터·실제 API 연결. 기존 서버 18787에 frontend 반영 | build·대비 9개·최종 관련 31개 통과. 전체 443 passed·기존 실패 9·skipped 6. 두 폭 시안 대조 18개와 실제 API 읽기 화면 8개 확인. [검증 기록](../validation-runs/20260908-dashboard-erp-ui.md) |
| 승인 ERP 판정 기준·실행 상태 | 사용자 승인 HTML·원본 TSX/CSS를 기준으로 두 화면의 8개 탭 구현. 목록 38%·상세 62%, 고정 하단 액션, 기존 정책·리뷰·중단·예약·포털 계약 유지. 기존 서버 18787에 frontend만 반영 | 2026-09-08: TypeScript strict·production build, 대비 9개, 전용·통합 89개 통과. 전체 화면 423 passed·11 failed·6 skipped이며 실패 11개는 기존 항목과 동일. 두 폭 mock 캡처 16개와 실제 API 읽기 화면 16개 확인. [검증 기록](../validation-runs/20260908-admin-erp-ui.md) |
| 기존 나라장터 공고 수집·정규화·표본 | 구현됨 | 파이프라인 단위·교차 테스트의 과거 64건 통과 기록 있음 |
| 발주계획 C-2 선별 | 제품 adapter·DB·API·화면·worker까지 구현됨. binding/policy v2에서 모델 payload는 batch-local `item_id`와 `title`만 보내고 승인 generation config를 실제로 읽어 요청을 조립한다([ADR-0044](decisions/0044-c2-stage2-matches-the-measured-method.md)) | 2026-09-03 종단 실행: 수집 1,040건 → 적재(warning 0) → stage1 선정 300/탈락 740 → stage2 **300/300 완료, 실패 0건**(관련 57·비관련 144·불확실 99) → `/order-plans` 표시. 테스트 전용 policy 사본으로만 활성화했고 **품질 근거가 아니다.** validator는 v2에서도 `valid_but_blocked`이며 activation blocker 4건은 그대로 |
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
| MinIO·ClamAV·문서 격리 | 구현됨 | Mock agent E2E 통과; 실제 운영 권한 matrix는 미검증 |
| document bundle·준비 API | 7개 Lean API와 attachment version/current·bundle ordinal DB 제약 구현됨 | backend 테스트, PostgreSQL migration/preflight/autogenerate, Mock E2E 통과 |
| 3단계 심층 검토·보고서·근거 API | 7개 Lean API 구현됨 | deterministic Mock provider E2E 통과; 실제 Qwen 품질 승인은 없음 |
| React 관리자 화면 | 기존 공고·판정·ready bundle 이후 심층 검토 구현됨 | tsc·production build 통과; 전체 visual `646 passed, 10 skipped, 0 failed` |
| 화면 시안 기준 B-F | 공통 review primitive, C-2 발주계획 split 화면, 사전규격 상태 그룹·선택 상세, 정보구조·dashboard 동선, 상세·심층검토 공통 skeleton을 구현함. 적합성·준비·추적·Go/No-Go 상태는 각각 유지함 | 독립검증에서 build 통과, PreSpecs mobile/tablet `54 passed`, DeepReview desktop `10 passed`, `git diff --check` 통과. 14개 승인 PNG·manifest·crop 기반 design suite는 없어 전체 시각 게이트가 차단됨([findings.md](findings.md)) |
| 무드보드 색 팔레트 · 단계 A | **팔레트 승인 + 단계 A 완료(2026-09-04).** 무드보드 `docs/design/moodborad.jpg`의 5색 anchor를 프로젝트 소유 테마 `bidops`로 옮기고 적합성 등급 4단을 slate 농도 ramp로 정의하기로 결정함([ADR-0048](../design/ADR.md#adr-0048-무드보드-기반-색-팔레트와-테마-소유권), [design/PRD.md](../design/PRD.md) §4.1) | 앱이 `bidops` 테마(무드보드 팔레트)로 돈다. `src/themes/bidops/`(171 token overrides + `grade-ramp.css`), `scripts/check-contrast.test.mjs`, `tests/design-shell.spec.ts`를 추가했고 AppShell·페이지 10곳의 scope와 `main.tsx` import를 옮겼다. `theme.css`의 `@theme`이 `:root`로 방출돼 Astryx 테마를 이기던 토큰 4개를 제거하고 shadcn `--color-accent`를 `--color-shadcn-accent`로 옮겼다([engineering-notes.md](../engineering-notes.md)). 지원 폭을 1280~1920px로 좁히고 검증 viewport를 laptop 1280×800·desktop 1440×900 두 폭으로 고정했다(ADR-0047). `--color-nav-text` 중복 정의를 없애고 사이드바 본문을 `--color-on-dark`로 통일했다. 충돌 토큰은 미이행 화면 가드 없이 **전역 적용**하기로 결정했다(2026-09-04). **검증:** 대비 6 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped(1280·1440·1920px 오버플로 포함), 전체 Playwright 370 passed·75 failed·3 skipped. 실패 75건은 `visual.spec` 스냅샷 73건(팔레트 변경에 따른 예상 실패 — 승인 없이 덮어쓰지 않는다)과 `order-plans.spec.ts:287` 2건(390px 전제의 기존 실패, 팔레트와 무관). **남은 것:** 시안 렌더 입력 교체와 v2 기준 이미지는 [design/PLAN.md](../design/PLAN.md) §0-4 통과 뒤다. 그때까지 앱은 승인된 시각 기준선 없이 새 팔레트로 돈다. 팔레트 적용은 [design/PLAN.md](../design/PLAN.md) §0-4(생성기 복원 대조) 통과 뒤에만 시작한다 |
| 공통 화면 primitive · 단계 B | **완료(2026-09-04).** 결정 액션 배치 두 형태, 접힌 보조 입력 영역과 append-only revision 이력, 등급 4단 한 벌, 좁은 폭 전환 제거 ([design/PLAN.md](../design/PLAN.md) 단계 B) | `ReviewDecisionBar`(분할 화면 pane 바닥)·`ReviewSecondaryInput`(접힌 보조 입력)·`ReviewRevisionHistory`(append-only)를 `ReviewPrimitives.tsx`에 추가했다. 단독 상세는 기존 `StickyDecisionHeader`를 계속 쓰고 한 화면에서 두 배치를 섞지 않는다. `SplitWorkspace`의 `mobileView`와 `review-primitives.css`·`order-plans.css`의 좁은 폭 분기를 없애 세 화면(`OrderPlansPage`·`QueuePage`·`PreSpecsPage`)이 어느 폭에서도 두 pane을 유지한다(ADR-0047). `.badge-grade-*`·`.rail-grade-*`가 `grade-ramp.css`의 `--bo-grade-*`를 읽고, 쓰이지 않던 두 번째 등급 스케일(`.c2l-grade-tag`)을 지웠다. 390px를 전제하던 `order-plans.spec.ts:287`·`pre-specs.spec.ts:520`은 지원 폭 기준의 반대 불변식(두 pane 유지, 제자리 pane 교체, 페이지 이동 없음)으로 다시 썼다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `review-primitives.spec.ts` 16 passed, 전체 Playwright 382 passed·74 failed·2 skipped(단계 A 기준선 371·75·4). 실패 74건에 **새 실패는 없다** — 73건은 단계 A에서 이어진 `visual.spec.ts`(팔레트 스냅샷 72 + `/queue` 1280px 오버플로 1, 단계 B 변경을 되돌려도 같은 값), 1건은 `visual.spec.ts:257` flake(단독 실행 통과)다. **남은 것:** `OrderPlansPage`의 접힌 보조 입력은 아직 `defaultIsOpen`이다. 단계 C가 추적 결정을 pane 바닥의 결정으로 들이면 시안의 접힌 기본값으로 되돌린다 |
| 발주계획 추적 결정 계약 · 단계 C 선행 | **요청안 작성, 백엔드 파트 검토 대기(2026-09-04).** ADR-0046 결정 4가 추적 결정을 발주계획 화면의 결정 1로 채택했으나 그것을 읽을·쓸 REST 경로가 없다 | [`order-plan-tracking-contract-request.md`](../design/order-plan-tracking-contract-request.md)로 요청안을 보냈다. 조사 결과 **새 table은 필요하지 않을 가능성이 높다** — 소유 사업기회와 `stage='order_plan'` official 링크를 `ingest/loader.py`가 이미 만들고, 상태 4값(`미선택`·`계속 추적`·`보류`·`종료`)과 append-only `AuditEvent`도 이미 있다. 없는 것은 (a) 발주계획 목록·상세 응답이 그 상태를 싣지 않는 것과 (b) 발주계획 식별자로 쓸 경로가 없는 것 둘이다. **묻는 것 5가지**는 요청안 §8에 있다(v2 schema 여부, 전용 endpoint 대 기존 PATCH, `opportunity_not_found` 409, `AuditEvent` 투영 대 전용 table, 사유 자유문자열 대 고정 집합). **검증 없음** — 제안이고 채택이 아니다. 단계 C 화면은 요청안 §7의 규칙(adapter 한 곳, 낙관적 갱신 금지, `계약 미구현`을 `미선택`으로 바꾸지 않음, fixture는 구현 근거가 아님) 아래 먼저 만들고, 계약이 구현·검증되기 전에는 단계 C를 완료로 적지 않는다 |
| 발주계획 화면 · 단계 C | **화면 작업 완료, 단계는 미완료(2026-09-04).** 추적 결정을 상세 pane 바닥의 결정 액션으로 만들고 사람 판단 수정을 접힌 별도 영역으로 분리했다 ([design/PLAN.md](../design/PLAN.md) 단계 C) | `추적 시작`·`보류`·`추적 종료`·`이번 건 넘기기`가 pane 바닥에 있고 선택 즉시 다음 건으로 이동한다. 사람 판단 수정은 접힌 채로 `새 revision 저장`을 스스로 소유하며 두 결정의 mutation·경로·요청이 모두 다르다. 저장된 뷰를 segmented control로 바꿨고(축별 다중 선택과 AND/OR·URL 계약은 유지), 상단 요약 한 줄과 `실행 상세` 진입점, 목록 머리글의 조합 의미와 바닥의 숨김 고지, `실행 기록` 탭 이름을 시안에 맞췄다. 추적 상태의 세 값(`계약 미구현`·`사업기회 미연결`·`미선택`)을 서로 바꾸지 않는다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `order-plans`+`review-primitives` 52 passed, 전체 Playwright 391 passed·73 failed·2 skipped. 실패 73건은 단계 A에서 이어진 `visual.spec.ts` 그대로이며 **새 실패는 없다**. 단계 C에서 결정 액션 바가 상세 pane 전체를 덮던 flex 회귀를 잡아 고쳤고 바 높이를 테스트로 고정했다. **미완료 사유:** 완료 게이트 2·3(두 결정이 서로를 덮지 않는다)은 서버가 있어야 판정한다. 저장 경로는 아직 요청안이며 fixture는 구현 근거가 아니다 |
| 사전규격 화면 · 단계 D | **완료(2026-09-04).** 추적 상태를 묻는 자리를 하나로 제한하고 신규 건에만 결합 조작을 준다 ([design/PLAN.md](../design/PLAN.md) 단계 D, ADR-0046 결정 6) | 발주계획에서 승계한 건(`origin='추적'`이고 추적 상태가 `미선택`이 아님)은 결정 form 자체를 그리지 않고 `계속 추적 · 발주계획에서 승계` 배지만 남긴다. `보류`·`추적 종료`를 두 사전규격 화면에서 없앴다 — `TRACKING_DECISION_STATUSES`가 `계속 추적` 하나가 됐고 그 둘은 사업 추적에서만 고른다는 문구를 남긴다. 신규 건에만 `추적 시작하고 심층 검토`를 한 조작으로 주되 **기록은 둘이다** — 추적 시작만 저장하고 심층 검토 실행 승인은 상세로 보낸다(`createDeepReview`가 ready 문서 묶음을 요구하므로 한 요청으로 합치면 존재할 수 없는 심층 검토를 만든다). 승계 건이 막다른 카드가 되지 않도록 상세 pane에 `심층 검토 실행 →` 진입점을 두었다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `pre-specs.spec.ts` 29 passed, 전체 Playwright 394 passed·74 failed·2 skipped. 실패는 단계 A에서 이어진 `visual.spec.ts` 73건 + flake 1건(`common-interactions.spec.ts:337`, 단독 실행 통과)이며 **새 실패는 없다** |
| 정보구조와 사업 추적 · 단계 E | **완료(2026-09-04).** 사이드바를 7항목으로 줄이고 `검토 대기열`을 `사업 추적`으로 대체했다. 예외 작업 경로를 옮긴 뒤 공고 1차 판정을 읽기 전용으로 잠갔다 ([design/PLAN.md](../design/PLAN.md) 단계 E, ADR-0046) | 커밋을 PLAN §6이 요구한 순서대로 셋으로 나눴다. `e7ed15f`(3-2 예외 작업 경로) → `a21a988`(읽기 전용 전환) → `ab7a53c`(대시보드·Go/No-Go·기준과 운영). 두 커밋 사이에 리뷰 저장 경로가 없던 순간이 없다. **사이드바**는 `오늘의 업무`/`탐색과 추적`/`기준과 운영` 7항목이고 회차 선택기를 갖는 사이드바 항목은 대시보드 하나다(공고 판정 이력은 사이드바 항목이 아니다). **사업 추적**은 분할 화면이 됐고 구역 판정이 `trackingSectionOf` 한 곳에서만 이뤄져 한 사업기회가 구역 넷을 통틀어 한 행으로만 나타난다. **예외 작업**은 실제 저장 경로를 갖는다 — `연결 불확실`은 서버에 이미 있던 `PATCH /opportunities/links/{id}/decision`(진입점이 없어 지금까지 쓸 수 없었다), `검증 실패`는 그 공고의 회차로 `PUT /notices/{pk}/review`에 확인 항목 답변만 실어 보내고, `근거 없음`은 화면이 해소할 수 없다는 사실을 그대로 말한다. **읽기 전용 전환**으로 검토 대기열의 리뷰 초안·localStorage·저장이 사라지고 `ReviewRecord`가 저장된 리뷰를 읽기 전용으로 보여준다. `ReviewBar.tsx`는 삭제했다. 단계 B가 미뤄 둔 `/queue` 1280px 가로 넘침 19.77px도 고쳤다(`.attachment-name`의 ellipsis가 부모의 시각 효과일 뿐 자식 span의 레이아웃 상자는 그대로 넘쳐 있었다). **검증:** 대비 7 passed, `tsc -b`·production build 통과, 전체 Playwright 410 passed·72 failed·2 skipped. 실패 72건은 **전부 팔레트 스냅샷**이며 단계 D까지 함께 실패하던 `/queue` 오버플로 1건과 flake 1건이 사라졌다. **미해결:** 사업기회 추적 이력 읽기 계약과 구역별 집계가 서버에 없어 화면이 그 한계를 표시한다([findings.md](findings.md)) |
| 상세 3종과 심층 검토 · 단계 F | **완료(2026-09-04).** 세 상세 화면을 한 골격으로 맞추고 되돌릴 수 없는 입력 form을 헤더에서 내렸다 ([design/PLAN.md](../design/PLAN.md) 단계 F) | 커밋 `ec79da7`(상세 3종 골격) → `adae790`(심층 검토 보고서). **헤더에는 액션만** 남고 폼은 본문 열에 있다 — 헤더 저장 버튼이 `form` 속성으로 본문 폼을 submit하므로 전제조건이 한 곳에만 있다. 시안 `OrderPlanDetail`대로 사람 피드백 revision 이력을 레일에서 본문 열로 옮겼다(지금 저장할 값과 직전 revision을 대조해야 한다). 입찰 변경 비교 헤더가 `결정 저장`·`결정 입력으로 이동`·`비교 재계산` 셋을 갖고, 최종 Go/No-Go 폼 바로 위에 저장 조건 셋을, 범주 목록 바로 위에 비교 기준(기준 사전규격·대상 입찰공고·문서 묶음 상태·계산 시각)을 남겼다. 심층 검토 보고서는 상단 카드 4개·결정 카드 요약 표(항목·내용·근거·검증)·Validation 실패 블록(`원문에서 확인`·`새 attempt로 재시도`)·우측 열(보고서 범위·수정본 저장·이력)로 배치했다. 시안의 `참여 준비 상태` 카드는 **이 보고서 계약에 그 축이 없어** 채우지 않고 그 사실을 한 줄로 밝혔다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, 전체 Playwright 420 passed·72 failed·2 skipped. 실패 72건은 전부 팔레트 스냅샷이고 그 밖의 실패는 없다. **미완료:** 완료 게이트의 `시안 기준 캡처`는 v2 기준 이미지가 없어 판정할 수 없다([design/PLAN.md](../design/PLAN.md) §0-3·0-4·0-5, [findings.md](findings.md)) |
| 화면 검사 층 분리 · 기준선 교체 | **완료(2026-09-04).** `visual.spec.ts` 한 파일이 픽셀 36 + 가로 넘침 36 + 의미 15를 섞어 담고 있어 픽셀이 깨지면 나머지 51개의 초록이 묻혔다. 세 층으로 갈랐다 — `screen-semantics.spec.ts`(의미, 1440px 한 폭) · `overflow.spec.ts`(구조, 1280·1440px) · `pixel-screens.spec.ts`(픽셀, 게이트 밖). 폭에 의존하지 않는 spec을 한 폭에서만 돌려 실행 건수가 494→260으로 줄었다. 픽셀 기준선은 대표 화면 여덟 장으로 교체했다(144장 39MB → 8장 1.1MB, 승인 기록은 [findings.md](findings.md)) | `npm run test:screens` `4 skipped, 247 passed (2.1m)`, 실패 0. `npm run test:pixel` `9 passed`, 재실행에도 동일 |
| 탐색과 추적 4화면 통일 | **구현 완료, 병합 전(2026-09-08).** 목록 4화면(발주계획·사전규격·사업 추적·최종 Go/No-Go)이 상단바 제목 모드(`h1` + 액션 portal)·공용 필터 바(`WorkspaceFilters`)·같은 프레임 값(목록 38%, 목록 머리 `8px 16px`, 상세 머리 `12px 16px`)을 쓰고, 발주계획에 목록 ↑↓ 이동·Ctrl+Enter 추적 시작·직전 사유 다시 쓰기가 생겼다 ([design/PLAN.md](../design/PLAN.md)) | 1단계(셸·공용 필터)는 메인 트리에 있고 2단계는 워크트리 브랜치 `feat/explore-wp-c`·`-wp-d`·`-wp-e`·`-wp-f`에, 교차 검사·문서는 `feat/explore-wp-g`에 있으며 **어느 것도 병합하지 않았다**(검증용 통합 커밋 `c85a495`). **게이트:** 기준선 `npm run test:screens` 464 passed·9 failed·6 skipped → 1단계 뒤 470 passed·9 failed·5 skipped로 기존 실패 9건 그대로다. **WP-G 검증:** `tsc -b` clean·production build 통과·`explore-workspace-consistency.spec.ts`(새 교차 검사)와 `admin-workspace-consistency.spec.ts` 5 passed 0 failed. `--project=pixel`은 7 failed 2 passed이며 달라진 화면은 dashboard·criteria·order-plans-list·order-plan-detail·pre-specs-list·opportunities-list·bid-delta-changed다. **픽셀 기준선은 갱신하지 않았다** — 교체는 승인 기록을 남긴 뒤에만 한다(`docs/standards.md`) |
| 통일 모델 클라이언트 | C-1 공고 판정·사전규격 개요·심층 검토가 `app/core/model_client.py` 하나를 `screening`·`overview`·`deep_review` 용도로 부른다. 용도마다 endpoint·허용 host·자격증명·선언 revision을 갖고 허용 host나 revision이 없으면 호출 전에 fail closed한다([ADR-0050](decisions/0050-unified-openai-compatible-model-client.md)). 이전 로컬 provider 설정 7개는 제거됐고 C-1 모델명이 `qwen3.8-27B`가 됐다 | 단위 테스트 범위. **live vLLM 호출은 이 저장소에서 실행하지 않았다.** C-2 발주계획 어댑터는 별도 transport로 남아 있다 |
| 참조 실행 모드와 품질 표식 | `BIDOPS_REFERENCE_WORKFLOW_MODE`가 결정적 mock과 품질 미측정 실행을 허용하고, 결과에 `quality_status=measured\|unmeasured_reference\|mock_reference\|null` 표식이 붙는다. 개요 attempt는 표식이 필수다 | 단위 테스트 범위. **참조 실행 절차는 아직 실행되지 않았다**(운영 절차의 "사전규격 심층 검토 참조 실행"). 참조 실행 결과는 운영 완료·품질 근거가 아니다 |
| 사전규격 자동 문서 준비 | effective grade가 `우선 검토`인 사전규격의 묶음 초안 생성·자동 확정, 새 확장점 `effective_grade_changed`, `GET /api/pre-specs`의 등급·자동 준비 필드 다섯([ADR-0049](decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)) | 단위 테스트 범위. 목록 쿼리 수가 건수와 무관하게 12(묶음 없음)/14(자동 확정 묶음 있음)로 일정함을 확장 테스트가 고정한다 |
| SW=Y 자동 심층 시작 | `우선 검토`·`SW사업대상=Y`·자동 확정 `ready` 묶음·검증된 개요와 현재 회사 핏 `matched`, 활성 입력·실행/품질 조건을 충족하면 시스템 actor로 심층 검토 생성(`deep_review.auto_create`). 추출형 개요의 `검토 종료` 권고는 차단한다 | 참조 실행용 게이트의 단위·연결 검사 범위. 회사 핏은 기본 비활성이므로 이 상태에서는 자동 생성도 대기한다. 자동 생성 감사를 찾는 경로는 `DEEP_REVIEW_CREATION_ACTIONS`를 사용한다([findings](findings.md)) |
| 사전규격 개요 모델 실행 worker | 통일 client를 `overview` 용도로 묶어 실행하고, 검증 실패는 재호출 없이 `failed`, transport 실패만 1+2회 재시도한다. 개요 lease는 모듈 상수 1,200초이며 합성 analysis worker가 C-2 → 심층 → 회사 핏 → 개요 순서로 하나만 claim한다 | 이번 회사 핏 변경은 fake 모델로 검증했다. 과거 실제 개요 참조 실행과 별개로 이번 작업에서는 live 호출을 하지 않았다 |
| 결정적 문서 segment·요구사항 inventory | 구조 저장 시점에 manifest·segment·inventory 항목을 append-only로 만들고 `GET /api/document-structures/{id}/segments`로 읽는다. 검증에 `requirement_inventory`·`segment_coverage` check 추가([ADR-0051](decisions/0051-deep-review-v2-deterministic-subset.md)) | 단위 테스트 범위. **이 변경 전 구조에는 manifest가 없고 조회가 404다**(사후 재구성 불가). 역할별 모델 분석과 Luna 평가는 보류 |
| 문서 준비·실패 attempt 재시작 화면 | typed frontend API·type 변경은 worktree에 있으나 화면과 연결은 미구현 | 화면 검증 없음 |
| T-23 사전규격 overview phase 2 기반 | immutable result/event, 제한된 attempt lifecycle service, safe v2 projection 구현됨; 실제 model transport·worker는 미구현 | SQLite 46 passed·1 PostgreSQL-only skipped, PostgreSQL 17 집중 9 passed, production build 282 modules |
| 사전규격 개요 검토 화면 | v2 결과 projection이 화면에 연결됨. 권고·검증 상태·요약·조건과 기한·미확인·근거·입력 한계를 판단 순서로 내고 계보는 접어 둔다. 근거 locator는 `GET /document-structures/{id}/pages/{page}`로 원문을 열어 앞뒤 블록과 함께 강조하며, `block_key`가 원문에 없으면 보정하지 않고 사람 검토로 보낸다. `verification_action`이 없는 unknown과 `validation_status != passed`는 각각 표식과 경고로 구분한다 | 2026-09-01, 커밋 `56aeb0d`·`77700a5`. Playwright `630 passed, 10 skipped, 0 failed`, tsc·build 통과 |
| 사전규격 심층 추적 결정 동선 | 개요를 읽은 화면에서 계속 추적·보류·종료를 기록한다. `GET /pre-specs`에 `notice_pk` 필터를 더해 `opportunity_id`·`tracking_status`·첨부 집계를 한 응답으로 읽는다(`notice_pk`가 있으면 `sw_only`를 적용하지 않는다. `source_type = 'pre_spec'`은 항상 적용된다). 담당자 이름과 사유가 모두 필수이며 개요 권고를 추적 상태로 자동 반영하지 않는다 | 2026-09-01, 커밋 `26cdab4`. backend `1046 passed, 5 skipped, 0 failed`, Playwright `646 passed, 10 skipped, 0 failed` |
| 애플리케이션 stack 조립 | PostgreSQL, MinIO, ClamAV, web, document worker, analysis worker, 일부 영속 volume, 목적별 egress overlay 구현됨 | 개발 stack health와 모델 endpoint 도달 기록은 있으나 실제 secret·MinIO 권한·egress·backup/restore 훈련이 남아 있다 |
| 구조화 안전 로그 | 기반과 주요 worker·queue·scheduler 계측 구현 중인 worktree 변경 | 신규 단위 테스트 일부 통과 기록, 현재 전체 worktree green 아님 |
| 개발용 hosted Codex 심층 검토 reference | 기본 비활성·notice allowlist에 더해 닫힌 payload allowlist를 두고, 회사 profile·prior stage 결과·승인되지 않은 입력 필드가 있으면 prompt 생성과 subprocess 이전에 `external_provider_payload_not_approved`로 fail-closed한다 | 해결; 차단 시 runner 미호출을 단언하는 회귀 테스트가 있고 backend `1041 passed, 5 skipped, 0 failed` |
| runtime image 회사자료 제외 | current profile·회사 실적 제목 TSV·vendored baseline을 build context와 runtime image에서 제외하고, `web`에만 read-only host bind mount로 주입하도록 경계를 고정함 | 해결; runtime contract `11 passed`, profile snapshot keyword `14 passed`, 실제 image build/run/find, `COMPOSE_OK`, backend `1041 passed, 5 skipped, 0 failed` |
| backup·object-first restore script | restore가 source→target version mapping을 기록하고 backup hash를 실제로 검증하며, active manifest를 `content_object_location`에서 생성해 복구된 집합과 일대일 대조함. 암호화 model-response는 `ContentObject.sha256`이 plaintext라 stored-byte 비교 대신 존재·target version만 검사함 | 해결; disposable MinIO 2개와 PostgreSQL 17로 정상 복구 exit 0, 손상 backup·미복구 active object·복구 후 삭제 세 경우 exit 1 확인 |
| 백엔드 모듈 경계 | `web/backend/app/`을 core·lifecycle·screening·deep_review 네 모듈과 조립 계층(`main.py`·`runtime.py`·`workers/analysis.py`·`migrations/`)으로 나눴다. lifecycle은 선별·심층 검토를 알지 못하며 역방향은 lifecycle이 정의한 확장점(projection·hook)으로 뒤집었다. `BIDOPS_MODULES`로 등록할 모듈을 고르고 알 수 없는 이름·빈 값은 기동 실패다. codex-exec provider는 전부 지웠다([ADR-0045](decisions/0045-backend-module-layout.md)) | 2026-09-04, [단독 실행 검증 기록](../validation-runs/20260904-backend-module-layout.md). 완료 기준 여섯 조건을 각각 실제로 확인했다. backend `2 failed, 1240 passed, 5 skipped`(실패 2건은 이주 이전부터 있던 `test_screening_orchestrator` 결함), `./run-tests.sh` 145 passed, Playwright `846 passed, 14 skipped`, `docker compose -f docker-compose.yml build` 성공, 기준 6 스크립트 세 조합 PASS. REST 계약은 이주 전과 같다 |

T-23 `0014` 검증 경계의 PostgreSQL application schema는 legacy 13개, 심층 검토 25개,
판정 runtime 12개, 누적 identity 5개, 첨부 fetch 1개, 판정·리뷰 revision 2개, 사전규격
overview 5개로 총 63개 table이다. `0015`가 더한 입찰 delta 5개는 이 수치와 T-23 검증
증거에 포함하지 않는다. 그 5개를 합친 `0015_bid_delta_final_decision`의 application
schema는 68개이며, 별도로 빈 PostgreSQL 17 `upgrade head`와 `0014↔0015` 왕복을 검증했다.
현재 코드의 head는 `0020_prespec_company_fit`이고 문서 업무 사전 기준 table은
**73개**, ORM `Base.metadata` 기준은 **79개**다(모듈 소유 core 2 · lifecycle 10 ·
screening 28 · deep_review 39). 운영 DB에 이 head를 적용했다는 뜻은 아니다. 두 수는 세는 대상이 다르며 어느 쪽도 다른 쪽을 대신하지
않는다.
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
| 애플리케이션 stack V2 | services healthy, `/api/health` 성공, 구조화 worker log 관측, 승인 모델 endpoint 도달 | 기동·관측·network 경계 검증; 실제 판정 품질 검증 아님 |
| static diff check | 당시 통합 UI 변경에서 성공 | 이후 worktree 변경의 전체 검증으로 재사용하지 않음 |
| 모듈 경계 강제 테스트 | `29 passed`. 허용 목록 `cross_module_import 0`, `router_orm_access 18`, `schema_imports_model_or_service 0`, `lifecycle_relationship 0`, `lifecycle_table_write 0` | 남은 18건은 명세가 이번 범위 밖으로 둔 router 안 직접 select다. 다섯째 검사(형제 모듈의 lifecycle 테이블 직접 쓰기·잠금)는 최종 검토가 "의존 규칙 네 줄 중 쓰기·잠금 한 줄만 어떤 검사도 덮지 않는다"를 지적해 새로 넣었고, 그때 드러난 제품 코드 17곳을 모두 lifecycle 공개 함수로 옮겨 0이 됐다. 목록은 stale 항목도 실패시키므로 실제 위반과 정확히 같다 |
| 기준 6 모듈 격리 | `web/backend/scripts/verify_module_isolation.sh` 세 조합 PASS — lifecycle `75 passed`, screening `2 failed, 394 passed, 1 skipped`, deep_review `230 passed` | 형제 도메인 모듈의 `app/<module>`·`tests/<module>`을 지운 임시 복사본에서 폐기 가능한 PostgreSQL 17을 띄워 실제로 돌렸다. screening의 실패 2건은 위 기존 결함이며 skip 사유는 조합마다 출력된다 |
| 이주 전후 REST 표면 | OpenAPI 문서 diff 11줄, 전부 `tags` | 경로 74개와 메서드·파라미터·요청 본문·응답 스키마·`components`는 동일하다. `/api/health`에 `health` tag가 붙고 판정 실행 경로의 tag가 `runs`에서 `screening`으로 바뀐 것이 전부이며 둘 다 소유 변경을 반영한다. `tags`는 `contracts.md`가 계약으로 고정한 값이 아니다 |

### 2026-09-05 문서 갱신 시점의 기준선

아래 수치는 **branch head 트리에서 실제로 잰 값**이다. 앞선 문서 갱신 회차가 "코드를
바꾸지 않았으므로 이전 수치를 물려받는다"고 적어 둔 문장은 사실이 아니었다 — 그 문서
커밋 뒤에 코드와 테스트를 더한 커밋이 넷 있었다. 물려받기를 지우고 다시 쟀다.

| 검증 | 측정 결과 | 해석 |
|---|---|---|
| backend `pytest` 전체(`tests/`) | `2 failed, 1454 passed, 5 skipped` | 실패 2건은 이주 이전부터 있던 `tests/screening/test_screening_orchestrator.py`의 결함(`'실패' == '부분 성공'`)이며 이번 변경의 회귀가 아니다 |
| `./run-tests.sh` | `145 passed`, exit 0 | 파이프라인 단위·교차 |
| `scripts/verify_module_isolation.sh` | 세 조합 `전체: PASS` | 형제 모듈을 지운 임시 복사본 |
| frontend `npm run test:screens` | `256 passed, 4 skipped` | 화면 게이트(의미 한 폭 + 구조 두 폭) |
| frontend `npm run build` | exit 0 | TypeScript strict build와 Vite production bundle |
| frontend `npm run test:contrast` | exit 0 | 테마 대비 게이트(ADR-0048) |
| `docker compose -f docker-compose.yml build` | exit 0 | 애플리케이션 스택 이미지 |
| OpenAPI 경로 수 | `75 paths` | `docs/contracts.md`의 경로 표와 일치 |
| frontend `npm run test:pixel` | **돌리지 않음** | `pre-specs-list`·`deep-review-complete` 두 장이 코드와 어긋난 채 남아 있다. 게이트가 아니며 갈아 끼우지 않았다([findings](findings.md)) |

**이 표는 위 수치를 잰 시점의 트리를 말한다.** 그 뒤 최종 검토 지적을 고치며 회귀 검사를
더했으므로 backend 통과 건수는 늘어 있다. 다음 회차는 물려받지 말고 다시 재서 적는다.

**실제 vLLM 호출, 나라장터 다운로드, Compose 스택 기동은 이 작업에서 수행하지 않았다.**
운영 절차의 "사전규격 심층 검토 참조 실행"은 아직 한 번도 실행되지 않은 절차다.

최근 끝까지 완주한 backend 전체 suite는 2026-09-04 모듈 경계 이주 뒤의
`2 failed, 1240 passed, 5 skipped`이다. 실패 2건은 이주 이전부터 있던
`tests/screening/test_screening_orchestrator.py`의 결함(`'실패' == '부분 성공'`)이며
이 이주의 회귀가 아니다. 그 직전에 실패 0건으로 완주한 기록은 2026-09-01의
1046 passed, 5 skipped다.
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
- Deep Review Mock agent E2E는 PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web에서 `passed=true`였다. 외부 모델 호출은 없었고 Qwen 품질 근거가 아니다.
- 이전 로컬 provider로 돌린 단일 판정은 한 번 실패한 뒤 generation binding을 고정한 재실행에서 7개 logical stage, 8 attempts, v3 judgment 1건으로 성공했다. 별도 stop 실행도 중단 artifact를 보존했다. 40건 A/B와 운영 activation을 뜻하지 않으며, **모델 이름과 transport가 그 뒤에 바뀌었으므로(ADR-0050) 그 실행을 새 실행의 baseline으로 재사용하지 않는다.**
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
3. **껍데기를 실제로 도는 기능으로.** 사전규격 개요 model worker는 2026-09-05에 통일 client 위로 구현했다(참조 실행 단계). 남은 것은 **입찰 delta 계산 worker와 모델 adapter**, 문서 준비·실패 attempt 재시작 화면, T-19 판정 모델 계보 projection이다. 자동 생성된 심층 검토를 실행하지 못하던 결함은 2026-09-05에 해결했다([findings](findings.md)). 입찰 delta는 저장·REST·화면이 있으나 `bid_delta_comparison`이 `pending`에 머문다.
4. **판정을 믿을 수 있게.** 실제 model artifact digest·대표 HWP/PDF gold·사람 판정으로 Qwen·vLLM 품질 gate 2건을 측정하고, screening v3를 보고서 renderer에 명시적으로 연결한다.
5. **선별 제품 — C-2 선택 완료.** BM25 Top 300→Qwen threshold·감사 표본 정책 확정 → 전체 발주계획 원본과 방식별 결과를 저장하는 불변 수집 회차·DB 계약 → 내부 opportunity와 plan·pre-spec·bid 공식 관계 및 사람 확인 대기 relation 후보 → 사전규격 독립 일일 수집·저비용 1차선별·사람 승인 gate 연결 → `계속 추적|보류|종료`, 입찰공고 발견, 사전규격 대비 material delta, 최종 사람 Go/No-Go.
6. **이후 범위.** 실제 secret·MinIO allow/deny·egress firewall·backup/restore를 운영 환경에서 검증하고, 개발계정 API 요청 수를 실측해 증액 근거를 준비하며, SSO·역할 권한과 dashboard·외부 알림을 설계한다.

2026-09-01에 C-2 방식 선택을 완료했다. 사람 확인이 남은 항목은 기존 997건 실험의 gold 재판정 9건, 별도 C-2 625건 gold의 잔여 87건, D-7 방화벽 승인이다.
2026-09-01에 운영 배포 blocker A-1~A-6 여섯 건을 전부 해소했다.
D-8 종단 관측은 2026-09-08·09-13·09-14에 계속 받는다.

위 단계 전에는 hosted OpenAI 자동 fallback, scheduler·always-on 자동 활성화, 자동 입찰 제출, 발주처 연락, 모델의 최종 참여 결정을 추가하지 않는다.
