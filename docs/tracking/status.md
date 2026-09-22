# 구현·검증 현황

기준일: 2026-09-22 (운영 개요 기본은 v7; v8 예비 판단은 제품 구현·격리 검증 완료, migration 0031은 운영 적용됨, 정책 비활성)

사전규격 v4 페이지 개요·PDF 선행·회사 핏 연속 처리의 진행 계획과 단계별 인수/중단 경계는 [prespec-v4-implementation-plan.md](prespec-v4-implementation-plan.md)에 보존한다. 이 계획은 현재 회사 핏 구현·검증과 v4/PDF 후속 구현을 구분하며, 완료·운영 적용 근거를 대신하지 않는다.

`구현됨`은 코드와 계약이 존재한다는 뜻이고, `검증됨`은 기록된 명령이 해당 범위에서 통과했다는 뜻이다. Mock 결과, 과거 브랜치 결과, 현재 worktree 결과, 외부 운영 승인을 서로 대신하지 않는다.

## 사용자 요청 Luna 심층검토 (2026-09-23, 운영 적용·실자료 인수 대기)

자동 심층 시작 기본 비활성, 건별 미리보기·승인·입력 동결, codex-exec Luna/xhigh, 공용 슬롯 순차 실행, 기존 설명형 보고서·근거 화면을 구현했다. 운영 migration 0032·서비스·Luna 정책을 적용하고 실제 계정의 Luna/xhigh 연결을 확인했다. 합성 실행기·PostgreSQL 17.11·UI 두 폭 검사는 [이번 검증 기록](../validation-runs/20260922-luna-deep-review/README.md)을 따른다. 공고 실자료 보고서와 순차 처리 인수는 대기 중이다. [운영 기록](../validation-runs/20260922-luna-deep-review/live-validation.md). [진행 계획](../0922_luna-deep-review/plan.md)과 [단계별 적용 절차](../0922_luna-deep-review/apply.md)를 따른다.

## 심층검토 설명형 보고서 PoC (2026-09-22, 운영 적용·참조 검증)

- 사용자 확정 방향: A안 본문 하나, 편집된 문서형, 핵심/상세 구분과 정보 연결. [작업 정본](../0922_deep-review-improvement/plan.md).
- 새 `analysis-policy-narrative-v2`·stage/report v2는 Qwen의 입력·회사 근거 선택·부분/전체 종합·보고서 조립·REST·제품 화면을 함께 연결한다. 모든 분석 문장, 원문 연결, 미분석 상태와 실제 검증 건수를 보존한다.
- 문장별 수정·근거 선택, 명시적 의견 선택·확인 snapshot, 이전 보고서 조회와 dirty 초안 보호를 적용했다. 기존 lean-v1·저장 보고서/hash·의견은 변환하지 않는다. 새 DB migration은 없다.
- 합성 모델/문서의 worker→DB→REST 및 PostgreSQL 17.11 변형과 1280/1440 제품 화면을 확인했다. 실제 모델 품질·처리량·회사 근거 회수율 및 실무자 인수는 미측정이다.
- 사용자 적용·품질 검증 요청으로 새 정책과 승인 프로필을 PoC 참조 실행에 선택하고 web·analysis-worker를 같은 이미지로 배포했다. 회사 핏 자동 실행 false·기존 개요/C-2 설정·migration 0031을 유지했다. 전체 백업과 이전 이미지 태그를 보존했다.
- 실제 작은 문서에서 공백·축약 연도의 과도한 차단을 확인해 사용자 요청으로 완화했다. 인용 표기 차이는 고정 원문에 연결하고 같은 금액의 단위를 환산한다. 연도 확장은 문장 옆 확인 사항이다. 다른 값·조건·출처는 계속 차단한다. 회사 대조의 긴 선행 분석 분할과 호출별 로컬 UUID 결속도 반영했다.
- 실행별 원문 대조 on/off를 웹 시작/재실행에 추가하고 운영 적용했다. 기본 on, off 결과는 대조 미실시로 표시하며 출처/형식 검사는 유지한다. 실제 웹에서 off 선택→202→서버 attempt false를 확인했다.
- 실제 off 실행은 문서 분석을 완료했지만 회사 대조의 근거/주장 ID 혼용·근거 연결 누락으로 실패했다. 정상적인 선행 주장 목록을 금지하던 제약은 완화했으며, 존재하지 않는 주장 참조와 결과 형식 오류는 계속 차단한다. 실제 완성 보고서는 아직 없다.
- 두 번째 실패 응답은 새 기준으로 통과했다. 실제 새 Qwen 전체 실행의 결과와 미검증 범위는 [실제 검증 기록](../validation-runs/20260922-narrative-review/live-validation.md)에 남긴다. `unmeasured_reference`를 유지하며 사람 품질 승인을 뜻하지 않는다.

## 사업 추적·최종 Go/No-Go 목록 ↑↓ 행 이동 (2026-09-22, 구현·운영 배포 완료)

- 발주계획·사전규격의 `useRowKeyboardNavigation`을 수정 없이 재사용해 두 화면(Astryx `Table` 유지, M1c A안)의 표 첫 열 버튼에 `rowProps`를, 표 스크롤 영역에 리스너를 달았다. 경계에서 페이지를 넘기고(↓ 다음 페이지 첫 행·↑ 이전 페이지 마지막 행), 사업 추적은 저장하지 않은 입력이 있으면 기존 이탈 확인이 먼저다. `Ctrl/Cmd+Enter`는 두 화면의 주 행동이 달라 넣지 않았다. 새 migration 없음(head 0031).
- 커밋 `6bfb7fc`(main, origin push 완료 — 대기 중이던 S1~S4 등 15개 커밋 포함). 검사: `tsc -b` 통과, `opportunities.spec`·`go-no-go.spec` 79 passed(새 spec 4건 포함), fixture `large` 옵션 추가로 `--project=app` 전체 643 passed / 2 failed(기존 `admin-workspace-consistency.spec.ts:23`) / 3 skipped. Go/No-Go의 경계 넘김은 페이지 크기 500이라 검사 없이 같은 코드 경로로만 둔다.
- 운영 배포(사용자 "커밋, 푸쉬, 운영 재배포" 지시): 백업 `backups/postgres/full/bidops-before-20260922-kbnav.dump`, 롤백 태그 `before-keyboard-nav-20260922`(`61313a4`), 이미지 `bidops-web:keyboard-nav-6bfb7fc`·직전 `bidops-web:before-keyboard-nav-20260922`. compose 5개 + env 4개로 `web`만 재생성, healthy 8초, `/api/health` 200, env 플래그 2개 `true`, 운영 head `0031` 불변. 배포 후 실제 스택(읽기 전용)에서 `/go-no-go?show=all` 20행·`/opportunities?section=전체` 100행 모두 첫 행 초점 → ↓ → 둘째 행 `aria-pressed`·초점·URL `selected` 이동 확인(기본 구역 `조치 필요`는 운영 행 0건).

## 실무 화면 고도화 소형 후속 S1~S4 (2026-09-22, 구현·운영 배포 완료)

묶음 ③·④가 남긴 후속과 사용자가 실제 화면에서 찾은 문제 넷. 시안 M7 승인(`docs/0915_ui-redesign/mockups/0922_practitioner-m7/`), 결정 [ADR-0068](decisions/0068-same-state-merge-and-tracking-reset.md)(ADR-0064 결정 개정, `business-rules.md` 검토할 항목 규칙 개정).

- 들어간 패키지: S1(대시보드 `마감 임박`·`새 우선 검토` 링크가 목적지 화면에서 같은 집합을 연다 — 사업 추적이 `deadline_within_days`·`sort=deadline`, 발주계획이 `first_observed_from`을 URL로 받아 서버에 그대로 보내고 문맥 줄 `7일 이내 마감 · 해제`/`09-21 이후 첫 수집`으로 알린다; `보류 재검토`를 표에서 행으로; `AgencyFeature` 부제 슬롯으로 총괄기관·공고기관 줄을 블록 안으로)·S2(발주계획 선택 도구를 사전규격과 같은 `전체 선택(현재 페이지)`·`전체 해제`·`선택 항목 제외`·`선택 항목 추적 시작` 4개로, 사업명 굵기 통일, 사전규격 행의 `다음: …` 제거)·S3(`검토할 항목` = 기존 조건 ∧ 추적 상태 null·`미선택` — `보류`·`계속 추적`·`종료`를 고른 공고가 목록에 남던 문제, 대시보드 `pre_spec_deep_review_ready` 건수도 같은 술어)·S4(사업기회 병합에서 양쪽 다 사람이 고른 추적 상태여도 상태가 같고 재검토 신호가 없으면 병합 — 유지 쪽은 가장 오래된 행, 감사 `merged_human_states`; 막힌 경우 `사업 #NNN 미선택으로 되돌리기` 출구 — 기존 PATCH `tracking-status`, 자동 재수락 없음). 새 migration 없음(head 0031). `VerificationRequest` 타입은 ③·④ 절의 "죽은 코드" 표기가 틀렸다 — `criteria/VerificationRequestsPanel.tsx`(`/profile`)가 쓴다.
- 병합: main `f0e2dd1`(통합 브랜치 `integration/practitioner-screens-5`, 다른 세션의 미커밋 narrative 작업 31파일은 stash → 병합 → pop, 충돌 0). 게이트(통합 트리 = 병합 트리, 동일 tree `7e2a94a`): `build`·`test:contrast` 통과, `test:screens` 724 passed / 8 failed / 6 skipped — 2건은 기존 `admin-workspace-consistency.spec.ts:23`, 6건은 S3·S4로 낡아진 교차 spec의 전제(기본 정렬 첫 행 991→993, 막힘 문구, `sw_only` 기본 집합 0행)라 `59ba3bd`에서 고쳐 병합 트리에서 그 5개 파일을 다시 돌렸다(아래 수치). 백엔드 전체 PostgreSQL 2,472 passed / 17 failed / 5 skipped — 실패는 기존 `test_order_plan_list_v2` 6 + `test_auto_deep_review_start` 11(다른 세션 몫)뿐, 회귀 0. 첫 실행은 같은 `postgres:17.11` 컨테이너를 두 번째로 쓰다 `CREATE DATABASE` 뒤 유휴 세션만 남긴 채 40분 넘게 멈춰 컨테이너를 새로 만들어 다시 돌렸다(23분 52초). 픽셀 2장 교체(`1791b46`, `order-plans-list`·`pre-specs-list`, 사유: 선택 도구 4개·사전규격 행 `다음` 제거).
- 운영 배포(사용자 "main 병합, 배포까지 이어서 진행" 지시): 백업 `backups/postgres/full/bidops-before-practitioner-screens-3-20260922T122411Z.dump`, 롤백 태그 `before-practitioner-screens-3-20260922`(`61313a4`), 이미지 `bidops-web:practitioner-screens-3-f0e2dd1`(다른 세션의 미커밋 작업이 섞이지 않도록 tree가 같은 `ps-int5` 워크트리에서 빌드)·직전 `bidops-web:before-practitioner-screens-3-20260922`. compose 5개 + env 4개로 `web`만 재생성, healthy 9초, env `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`·`BIDOPS_C2_DAILY_TRIGGER_ENABLED=true`, 포트 18787, 운영 head `0031` 불변.
- 배포 후 확인(실제 스택, 읽기 전용): S3 — `workspace=actionable` total 87(배포 전 같은 날 99), 목록의 추적 상태가 전부 `미선택`, `추적 중` 9건(`계속 추적` 9)은 그대로. S1 — `/api/workload` `tracking_deadline_imminent` 6 = 링크 목적지 `/opportunities?section=전체&deadline_within_days=7&sort=deadline` 6건, 문맥 줄 `7일 이내 마감`; `/order-plans?…&first_observed_from=2026-09-21` 문맥 줄 `09-21 이후 첫 수집`(기본 필터와 함께 0건, workload 0과 일치); 대시보드 1280 가로 넘침 없음. S2 — 발주계획 도구 4개 이름·순서 일치, 사업명 굵기 600, 사전규격 행 `다음:` 0. S4는 운영 데이터에 쓰기가 필요해 실제 스택에서는 돌리지 않았다(백엔드 `test_opportunity_integrity`·`test_api_opportunities`, 프런트 `opportunities.spec`가 근거).
- 남은 것: origin push·워크트리(`ps-s1~s4`·`ps-int5`)·브랜치 정리는 요청 대기. 후속 잔여는 `test_workload_api.py` 대량 표본 느림뿐. 다른 세션 몫은 그대로(`test_auto_deep_review_start` 11건, narrative 작업 커밋).

## 실무 화면 고도화 묶음 ③·④ (2026-09-22, 구현·운영 배포 완료)

정본 `docs/0921_practitioner-screens/`, 결정 [ADR-0067](decisions/0067-dashboard-workload-keys-and-panel-contracts.md). 시안 M5·M6 승인(`docs/0915_ui-redesign/mockups/0921_practitioner-m5-m6/`, 발주계획 판정 변화 표·행 판단 근거는 제외 — 발주계획 판정은 수집 당일 1회).

- 들어간 패키지: F0(프런트 타입·mock·fixture, 사전규격 공유 mock `display_assessment`)·F1(발주계획 상세 API 연결 — 계약방법·조달방식·총괄기관·공고 게시·연결 공고번호·첫 수집·신규/계속, 행 추적 상태 칩)·F2(사전규격 수요기관 우선 표기·제외 기록, 공고 상세 `예산`/`추정가격` 분리·개찰·유사 실적 두 표)·F3(Go/No-Go 입찰 마감 열·추정가격, 사업 추적 행 예산·마감, 입찰 변경 오류 코드 접기)·H0(패널 5개 계약 표)·H1(workload 키 5→10, `deadline_within_days`·`sort=deadline`·`first_observed_from`·`human_relevance=missing`, 새 endpoint 없음)·H2(대시보드 회차 축 제거·누적 패널 5개)·H3(등급 분포·검증 지표를 `/runs` 회차 상세로, 회사 역량 확인 요청을 `/profile`로)·T1·T2(테스트 대상·fixture·옛 단언 정리). 새 migration 없음(head 0031).
- 병합: main `3c3101e`(통합 브랜치 `integration/practitioner-screens-3`, 다른 세션의 미커밋 심층 검토 narrative 작업은 stash로 보관했다 되돌려 작업 트리 그대로). 게이트(통합 트리): `build`·`test:contrast` 통과, `test:screens` 716 passed / 3 failed(기존 admin 2 + `draft.spec:63` 부하 flake 단독 통과) / 6 skipped, 백엔드 전체 PostgreSQL 2,454 passed / 17 failed(기존 `test_order_plan_list_v2` 6 + **`bda1288` 이후 `test_auto_deep_review_start` 11 — findings 기록, clean `bda1288`에서 재현**) / 5 skipped, H1 변형 45 passed. 픽셀 5장 교체(`aa4b677`).
- 운영 배포(사람 확인 뒤): 백업 `backups/postgres/full/bidops-before-practitioner-screens-2-20260922T083226Z.dump`, 롤백 태그 `before-practitioner-screens-2-20260922`(`e2252f6`), 이미지 `bidops-web:practitioner-screens-2-3c3101e`·직전 `bidops-web:before-practitioner-screens-2-20260922`. `web`만 재생성, env 플래그 2개 `true` 확인.
- 배포 후 확인(실제 스택): `/api/workload` 10키 전부 정수(null 없음 — `tracking_deadline_imminent` 6, `human_check_required` 7 = `overview_human_review` 7 + `blocking_items_open` 0, `order_plan_new_priority` 0). 목록 total과 건수 일치(임박 6, 개요 확인 필요 5+2). 대시보드 1280 캡처: 회차 선택기 없음, 마감 임박 5건 D-1·D-2 강조, 사람 확인 필요 7건. 발주계획 상세에 `계약방법` 표시.
- 남은 것(후속, `plan.md`·findings): `마감 임박` 패널 링크가 사업 추적 화면에 `deadline_within_days`를 못 넘김(그 화면이 인자 미수용), `/order-plans` 링크에 "새로" 창 없음, `보류 재검토` 표의 마지막 열이 1280 반폭에서 가로 스크롤, `AgencyFeature` 부제 슬롯(F1·F2가 형제 줄로 우회), `VerificationRequest` 타입 죽은 코드, `test_workload_api.py` 대량 표본 느림. 다른 세션 몫: `test_auto_deep_review_start` 11건, narrative 작업 커밋.

## 실무 화면 고도화 묶음 ①·② (2026-09-22, 구현·운영 배포 완료)

정본 `docs/0921_practitioner-screens/`, 결정 [ADR-0066](decisions/0066-practitioner-ops-information-boundary.md)(ADR-0062·0064 개정). 같은 기능은 같은 UI로, 실무 화면에는 판단 정보만 남기고 운영 정보는 운영 화면으로.

- 들어간 패키지: D0·B1·B2·R3·R1·U1·U2·U3·O1·R5·R4·R2·C1·C2·R6(시안 M1·M2·M3·M4·M1c 승인, `docs/0915_ui-redesign/mockups/0921_practitioner-*`). 공용 `SourceRunFilter`(상세 필터 안)·`ListPagerControls`·`TechnicalInfo`, 운영 `실행 상태 › 수집 실행`의 `발주계획 선별` 탭, 발주계획 행·상세·필터·폼의 운영 문구 제거와 실행 상태 칩 판단식 수정, 사전규격·심층 검토·Go/No-Go·셸의 기술 정보 접기, 사업 추적·Go/No-Go 공용 골격(표 유지, 14.4px), 지역 제한 `미확인` 결함 수정, 백엔드 투영(발주계획 목록 v5·상세 v4·이력 purpose, 사전규격 `demand_agency`+검색, 결정 대기열 마감·예산·마감순 정렬, 사업기회 링크 예산·마감).
- 병합: main `d28294f`(통합 브랜치 + `bda1288` 반영, ADR 번호 충돌로 0065→0066). 게이트(병합 트리): `build`·`test:contrast` 통과, `test:screens` 682 passed / 23 failed / 6 skipped — 23건 중 2건은 `admin-workspace-consistency.spec.ts:23` 기존 결함, **20건은 clean main에서도 실패하는 사전규격 계열**(`bda1288`이 `prespec-list-work`·`screen-semantics`·`document-preparation` spec을 갱신하지 않음, 그 작업 몫), 1건은 새 검사의 `grade`→`display_grade` 단언을 고쳐 통과. 픽셀 기준선 7장 교체(`ca4c679`). 백엔드 PostgreSQL 변형 103 passed.
- 운영 배포(사람 확인 뒤): 배포 전 운영 스택이 2시간 전 Docker 재시작으로 내려가 있어 먼저 복구했다(`minio-init`은 `minio/mc` 이미지 pull 거부로 건너뜀, 버킷은 볼륨에 존재). web 포트 18787을 Windows `tailscale serve`가 선점해 항목을 잠시 끄고 기동했다(재개 필요). 전체 백업 `backups/postgres/full/bidops-before-practitioner-screens-1-20260922T014222Z.dump`, 롤백 태그 `before-practitioner-screens-1-20260922`(`bda1288`), 이미지 `bidops-web:practitioner-screens-1-d28294f`·`bidops-web:rollback-92c7f32-20260922`·`bidops-migrate:before-practitioner-screens-1-20260922`. **migration 0031**(`bda1288`의 사전규격 예비 판단 스키마, 컬럼 17개·FK 2·check 4 추가, 데이터 변경 없음, downgrade 없음)을 사용자 승인 뒤 `migrate`로 적용해 운영 head `0030→0031`. 새 이미지는 head 0031을 요구해 migration 없이는 기동하지 않는다. `web`만 재생성, 컨테이너 env `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`·`BIDOPS_C2_DAILY_TRIGGER_ENABLED=true` 확인.
- 배포 후 확인(실제 스택): `/api/health` 200, `/api/order-plans` v5(1,402건, `contract_method`·`notice_posted`), `/api/order-plans/{pk}` v4(`supervising_agency_name`·`procurement_method`·`bid_ntice_no_list`·`published_at`, 이력에 `execution_purpose`·시각), 결정 대기열 16건(`deadline_at`·`budget`·`estimated_price`), 사전규격 145건(`demand_agency`). 1280 화면 5개(발주계획·`/runs`·사업 추적·Go/No-Go·사전규격)에서 `관리자 화면`·`판정 policy`·`BM25`·`저장 가능` 0, `목록 기준` 단추 표시, 발주계획 행 `모델 · 관련`·`첫 수집 09-19`·상세 `가까운 회사 역량` 확인.
- 남은 것: 묶음 ③(F0·F1·F2·F3 — 새 필드의 화면 소비자)·④(H0~H3 대시보드) 미착수. 분리한 후속(수집 확장·단계 지연)과 R5·R6 잔여는 `findings.md`·plan §1. origin push·워크트리(`~/orca/workspaces/bidops/ps-*`)·브랜치 정리는 요청 대기.

## 사전규격 개요·예비 적합성 통합 (2026-09-21, 제품 구현·격리 검증 완료, 운영 비활성)

[ADR-0065](decisions/0065-prespec-overview-preliminary-assessment.md)와 [의도·명세·계획](../0921_prespec-preliminary-assessment/plan.md)에 따라 기존 개요 run에 예비 적합성 판단을 통합했다. 불변 v8 정책은 사실 개요와 세 관심 축의 판단을 정상 호출 1회에서 만들고 서버가 등급을 계산한다. 제외·역할·문맥·수치 위험만 선택 의미검증 1회를 추가하며 형식 재시도를 포함한 상한은 3회다. 판단 또는 의미검증 실패 때 검증된 개요를 보존하고 등급은 `held`로 둔다.

- migration `0031_prespec_preliminary_assessment`는 입력 binding, 최소 프로필 snapshot, 판단·검사·의미검증 상태, 정확히 같은 입력 결과의 최초 재사용 계보를 추가한다. 구버전 행은 v1로 보존하고 downgrade로 이력을 삭제하지 않는다.
- `display_assessment`는 사람 정정 → 현재 safe 문서의 v8 판정/보류 → 기존 선별 판정 → 없음 순이다. 목록·상세·`display_grade` 필터·건수는 같은 batch projection을 쓰며 기존 effective grade와 자동화 자격은 유지한다.
- 자동화 소비자는 v8 `completed`만으로 열리지 않는다. 전체 개요 선택 의미검증의 `passed`와 `overview_full` 범위가 있어야 종전 소비 경계를 통과한다. 같은 문서의 종결 결과는 재관측이나 정책·프로필 변경만으로 자동 재실행하지 않고, 사람 재실행은 실제 평가한다.
- 검증: 영향 backend **185 passed**(후속 runner·순수 판정 **41 passed**, 선택 의미검증 저장 장애 **1 passed**), 일회용 PostgreSQL 17의 Alembic 정합성 **1 passed**, 0030→0031 기존 행·제약·재적용·downgrade 계약 **1 passed**, API shape **25 passed**(최종 projection **17 passed** 재실행), frontend build 통과, 관련 Playwright **3 passed**, 1280×800·1440×900 구조 파일 **82 passed**. 자세한 명령과 범위는 계획의 구현 검증 기록에 있다.
- 운영 DB migration, 실제 모델 호출·품질 비교, 배포, 정책 활성화는 실행하지 않았다. 기본 정책 경로는 v7이고 v8 품질은 미측정이다.

## 검색 안내 문구 삭제·발주계획 목록 바닥 줄 정리 (2026-09-21, 구현·운영 배포 완료)

사용자 결정으로 두 화면 요소를 정리했다. 기능·계약 변경은 없고 migration도 없다.

- **검색창 아래 안내 문구**(`Enter로 검색 · 띄어쓰기 무시` / `Enter로 적용 · …`)를 네 화면 모두에서 화면에 그리지 않는다. 같은 문구는 입력칸의 접근 설명(`aria-describedby`)으로 남아 보조기술에는 그대로 읽힌다. 대가로 적용 대기 신호는 시각적으로 사라진다(`docs/0921_search-ux/spec.md` §3 개정).
- **발주계획 목록 바닥 안내 줄**은 실무자에게 경고가 필요할 때만 그린다. 정렬 설명과 기본 보기 숨김 안내(`BM25 선정 제외…`)는 지웠고, 범위 줄은 판정 없음·활성 policy 판정 없음·회차 모드일 때만 보인다. 회차 모드의 ` · 측정 전용 실행`은 측정 결과를 운영 판정으로 오인하지 않게 하는 유일한 신호라 남겼다(ADR-0062 개정).
- 검증: 관련 spec(검색 UX·Go/No-Go·탐색 일관성·사전규격 목록 51건, 발주계획·대시보드 104건) 전부 통과. `npm run test:screens` **668 passed / 2 failed / 6 skipped** — 실패는 기존 `admin-workspace-consistency.spec.ts:23` 2건뿐이고 회귀 0. 픽셀 기준선 3장(`opportunities-list`·`order-plans-list`·`pre-specs-list`) 교체, 승인자 jechoi·2026-09-21.
- 운영 배포: main `e18dfa8`, web만 재생성. 백업 `bidops-before-uiux-cleanup-20260921T054137Z.dump`, 롤백 태그 `before-uiux-cleanup-20260921`(`647038f`). Alembic head `0030` 불변.
- 배포 후 확인(실제 스택, 1280·1440 × 네 화면): 보이는 안내 문구 0, 입력칸 접근 설명 `Enter로 검색 · 띄어쓰기 무시` 유지, 발주계획 평상시 바닥 줄 0, 가로 넘침 0. `deadline_scope_counts`는 배포 전과 같은 `{current:54, passed:45}`. **운영 데이터의 서버 검색**도 확인했다 — 사전규격·사업 추적에서 `시스템`과 공백을 끼운 `  시 스템  `이 같은 건수(97·231)를 돌려주고 없는 말은 0건이다. 이로써 앞 절에 남긴 "검색 UX의 사전규격 외 화면 운영 확인" 한계 중 서버 검색 두 화면은 해소됐다. 발주계획·Go/No-Go의 클라이언트 검색은 화면 로드와 접근 설명까지만 확인했다.

## 사전규격 검토할 항목의 마감 구간 (2026-09-21, 구현·운영 배포 완료)

[ADR-0064](decisions/0064-prespec-actionable-deadline-scope.md)에 따라 검토할 항목의 기본 시야를 `마감 전 + 마감 미확인`으로 좁히고, `마감 경과`를 건수와 함께 조회 도구 줄 네 번째 칸에서 1클릭으로 전환하게 했다. 마감 경과를 제외·소멸시키지 않으며 마감 미확인은 항상 기본 구간에 남는다. 질의 인자 `deadline_scope=current|passed|all`(기본 `all`)과 응답 집계 `deadline_scope_counts{current,passed}`를 더했다. 구간은 actionable workspace 술어의 일부라 `workspace_counts.actionable`에만 반영되고 나머지 세 보기의 행·건수는 바뀌지 않는다. 시간 비교는 전부 SQL이 하고 시계는 요청당 1회 고정한 값 하나다. **migration은 없다**(Alembic head `0030_prespec_review_exclusion` 그대로). 커밋·push·운영 재배포는 실행하지 않았다.

- Backend: 일회용 `postgres:17.11`과 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`로 사전규격·검색·사업 추적·발주계획 7개 파일을 실행해 **127 passed / 0 failed**. 변경 전 같은 범위의 기준선은 125 passed / 0 failed이므로 새 사례 2건이 늘고 회귀는 0이다. 새 사례는 마감 미확인 보존, 구간별 분할, 다른 세 탭 건수 불변, 검토 제외와의 결합, 페이지 경계, `deadline_status`와의 AND, 422를 고정한다.
- Frontend: `npx tsc -b && npm run build` 통과. `npm run test:screens` **667 passed / 3 failed / 6 skipped**. 변경 전 기준선은 665 / 3 / 6이며 회귀는 0이다 — 실패 3건 중 `admin-workspace-consistency.spec.ts:23`의 1280·1440 2건은 `/runs`의 `.rs-detail-foot`이 없어 나는 기존 실패이고(그 테스트만 `installRunStatusMock`을 설치하지 않는다, main과 코드 동일), `bid-delta.spec.ts`의 1건은 단독 재실행에서 41 passed로 통과한 부하 flake다(직전 실행에서는 같은 파일의 다른 사례가 실패해 실패 지점이 옮겨 다닌다). 기준선에서 실패하던 `list-selection.spec.ts` LS-S1은 검색 키 정규화 계약에 맞게 기대값을 고쳐 회복했다.
- 폭: 1280×800·1440×900에서 조회 도구 줄의 직계 자식 4개가 같은 `top`을 가져 한 줄을 유지하고 가로 넘침이 0인 것을 측정으로 확인했다.

- 픽셀 기준선 교체(게이트 아님): `opportunities-list`·`order-plans-list`·`pre-specs-list` 3장. **사유** — 조회 도구·검색 UX 통일이 세 화면의 필터 영역을 보기 탭 줄 + 조회 도구 줄 2행으로 재편했고, 사전규격은 그 도구 줄에 마감 구간 컨트롤이 하나 더 들어왔다. 나머지 5장은 변경 없이 통과했다. **승인자** jechoi, **승인 시각** 2026-09-21. 교체 전 `pre-specs-list`의 새 이미지를 직접 확인했다(도구 줄이 1440에서 한 줄을 유지하고 구간 칩이 마지막 칸에 온다).

- 운영 배포(2026-09-21, 사람 확인 뒤 실행): main `61e492e`를 web 이미지에 담아 `web`만 재생성했다. 이 배포에는 검토 제외 PoC·조회 도구/검색 UX 통일·마감 구간 세 변경이 함께 실렸다(세 기능이 같은 화면·같은 파일을 공유해 배포를 한 번으로 묶었다). 전체 백업 `backups/postgres/full/bidops-before-prespec-deadline-scope-20260921T050531Z.dump`, 롤백 태그 `before-prespec-deadline-scope-20260921`(병합 직전 `7115281`). **migration 없음** — 운영 DB `alembic_version`은 배포 전후 모두 `0030_prespec_review_exclusion`이다. compose 5개 + env 4개(`--profile prespec`)로 렌더한 포트 18787과 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`·`BIDOPS_C2_DAILY_TRIGGER_ENABLED=true`를 재생성 뒤 컨테이너 env로 다시 확인했다.
- 배포 후 확인: `/api/health` 200. `GET /api/pre-specs?workspace=actionable`이 total 99와 `deadline_scope_counts {current:54, passed:45}`를, `deadline_scope=current`가 total 54, `=passed`가 total 45를 돌려준다 — 두 칸의 합이 구간 미적용 actionable과 같고, 세 호출에서 집계가 동일하며, `workspace_counts.actionable`이 활성 구간을 따른다. 같은 시점에 `deadline_status=open|passed|unknown`은 54/45/0으로 **구간과 정확히 일치**한다. 실제 화면은 1280×800·1440×900에서 조회 도구 줄의 직계 자식 4개가 같은 `top`을 가져 한 줄을 유지하고 가로 넘침이 0이며, 칩이 `마감 전·미확인 54`·`마감 경과 45`, 검토할 항목 탭이 54로 서로 맞는다.
- 수치 주석: 같은 날 오전(배포 전, 옛 코드) 같은 조회는 55/44였다. 두 방식이 배포 뒤 같은 시점에 정확히 일치하므로 술어 불일치가 아니라 그 사이 actionable 구성이 1건 움직인 것이다. `auto_preparation_status`는 첨부·문서 묶음 상태에서 조회 시점에 파생되는 값이라 워커가 도는 동안 바뀔 수 있다. 어느 공고가 움직였는지는 특정하지 못했고(마감을 넘긴 검토할 항목 0건, 그 사이 생성된 개요 run 0건) 계약 검증이 통과해 더 추적하지 않았다.

검증 한계: 이번 배포에 함께 실린 조회 도구·검색 UX 통일은 운영 데이터에서 네 화면의 검색을 실제로 돌려 보지 않았다. 사전규격 화면은 위와 같이 확인했으나 발주계획·사업 추적·최종 Go/No-Go의 검색은 배포 후 확인이 남아 있다.

## 목록 조회 도구·검색 UX 통일 (2026-09-21, 구현·운영 배포 완료 — 배포 기록은 위 마감 구간 절)

[의도·명세·계획](../0921_search-ux/plan.md)에 따라 발주계획·사전규격·사업 추적·최종 Go/No-Go의 검색 도구를 보기 탭 아래 왼쪽에 배치하고 Enter 적용, raw `q` 보존, Unicode 공백 제거·ASCII 대소문자 비교, 검색만 지우기, 동등 query의 선택·페이지 보존을 연결했다. 사전규격·사업 추적·독립 발주계획 API는 페이지 분할 전 서버 검색을 하며 Go/No-Go는 받은 행만 검색한다. DB migration은 없다. 다른 미커밋 작업은 보존했고 commit·push·운영 재배포는 실행하지 않았다.

- Backend: 일회용 PostgreSQL 17과 SQLite로 `test_search.py` 및 관련 사전규격·사업 추적·발주계획 API 영향 사례를 실행했다. 최초 60건 중 59건 통과, 1건은 새 발주계획 검사 fixture의 기관명이 두 행에 같아서 기대 건수가 틀렸다. fixture만 고친 뒤 해당 사례 1건을 재실행해 통과했다. PostgreSQL SQL 검색과 Python 비교값의 공백·ASCII·literal parity 사례가 포함됐다. 운영 DB·모델 호출은 사용하지 않았다.
- Frontend: `npm run build` 통과. Playwright `--project=app`의 `search-ux.spec.ts`, `order-plans.spec.ts`, `pre-specs.spec.ts`, `opportunities.spec.ts`, `go-no-go.spec.ts` 관련 190건 중 최초 188건 통과, 2건은 새 비교 규칙에 따른 기대값과 strict locator 오류였다. 이 2건의 기대값·locator 수정 후 둘 다 통과했다. 추가한 동등 검색·IME/키보드 삭제·직접 invalid URL 2건과 TypeScript 비교값 계약 1건도 각각 통과했다. Mock API는 미처리 요청을 404로 막으며 실제 운영 API로 보내지 않았다.
- 구조: Playwright `overflow.spec.ts --grep '\[search-ux\]'`에서 1280×800·1440×900의 네 화면 8건 통과. 데이터가 표시된 각 화면의 전체 캡처를 직접 확인했다. `design-shell.spec.ts`의 관련 셸·제목·폭 검사 4건 통과, 폭 조건이 다른 2건은 의도된 skip이다. 캡처는 해당 Playwright 실행의 `web/frontend/test-results/`에 생성되는 일시 산출물이다.

검증 한계: 프런트 화면 검사는 계약 기반 mock 환경이며 운영 스택·실제 데이터에서의 검색 조회와 배포 후 health 확인은 수행하지 않았다. 배포는 별도 실행 직전 사람 확인과 백업 절차가 필요하다.

## 사전규격 검토 제외·복원 (2026-09-21, 구현·격리 검증·운영 배포 완료)

단건·선택 묶음 제외, 전체 이력 단건 복원, 팀 공통 상태·변경 정보·원자적 감사 저장을 구현했다.
검토할 항목·최근 수집에서 제외하고 추적 중·전체 이력·상세에는 표식을 둔다. 추적·등급·리뷰·
자동 처리 자격·대시보드 집계는 유지한다. 200건 한도, 실패 입력/선택 보존, 명시적 재시도,
선택 해제·다음/이전 행 초점·빈 마지막 페이지 보정·미저장 추적 입력 보호를 연결했다.
계약은 [contracts.md](../contracts.md), 적용 순서는 [operations.md](../operations.md)에 있다.

검증 범위(같은 소스의 통과 결과를 재사용하며 수정 후 영향 사례만 재실행):

- `tests/app/test_pre_spec_review_exclusions.py`: 50개 사례(SQLite/PostgreSQL 포함) 통과.
  필수값·중복·다른 대상·1~200건·trim 한도, 미변경 보존, 감사 실패 전체 롤백, 재관측 유지,
  추적 예외/사람 확인/심층 대기 제외·건수·페이지, 동시 역순 요청을 검사했다.
  일회용 `postgres:17.11` + `BIDOPS_TEST_POSTGRES_URL` 사용. 신규 DB와 실제 0029 열 형태의
  기존 DB → `0030_prespec_review_exclusion`, app 역할 실제 변경·감사 쓰기도 통과했다.
- 기존 `test_api_pre_specs.py`·`test_api_pre_specs_workspaces.py`·`test_api_pre_specs_projection.py`,
  `test_alembic_autogenerate.py`, 단일 head·runtime head·migration 감사 표식 검사 통과.
  projection의 2개 초기 실패는 로컬 `.env`의 개요 자동 실행 설정 유입이었다. 변경 전 코드에서도
  enabled=true일 때 같은 실패를 재현했고 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`로 전제를
  고정해 projection 15개가 통과했다. 제품의 자동 분석 자격은 수정하지 않았다.
- `test_module_boundaries.py`와 영향 권한 정적 검사 통과. 운영 DB·모델 호출 없음.
- `npm run build` 통과. Playwright `pre-specs.spec.ts`·`prespec-list-work.spec.ts`·
  `prespec-exclusions.spec.ts`의 관련 의미 검사 77개 통과(mock API).
  `overflow.spec.ts`의 사전규격 목록·상세·추적 폼·제외 창 8개 통과(1280×800, 1440×900).
  마지막 변경은 페이지 이동 처리이며 영향 사례만 재검사했다. 두 확인 창 캡처를 직접 확인했다.

운영 적용(2026-09-21 07:39 KST): 사용자가 migration 진행과 재배포를 모두 명시적으로 승인했다.
일일 수집 두 트랙 완료를 확인하고 공용 daily lock을 보유한 채 웹·첨부 워커를 중지했다.
분석 워커에는 SIGTERM을 보내 진행 중 개요 1건이 completed가 된 뒤 exit 0으로 종료되는 것을
확인했다. 기존 Git 및 서비스별 이미지 롤백 태그는 `before-prespec-review-exclusion-20260921`이다.

- DB 백업: `backups/postgres/full/bidops-20260920T223643Z.dump`(26,076,838 bytes),
  SHA-256 `39191099eb3b065ca0b3e7b28c19f2c75e82eb954c88d46b3ecf6ecaec73a1a7`.
  `pg_restore --list` 성공. 같은 이름의 `.manifest.json`에 이미지·revision·객체 manifest hash를 기록했다.
- 객체 백업: `backups/objects/prespec-review-exclusion-20260921/`의 852개 버전(약 593 MiB).
  기존 `backup-objects.sh`로 버전별 복사와 원본/백업 SHA-256 대조를 완료했다. ops 이미지의
  pinned mc 다운로드가 거절되어 운영 MinIO의 동일 버전 `RELEASE.2025-08-13T08-35-41Z` 바이너리를
  임시 백업 컨테이너에 마운트했다. 이번 백업은 로컬 보존이며 외부 위치 복사·실제 복원 시험은 하지 않았다.
- 운영 Compose 5개 파일·env 4개·prespec profile로 `run --rm --no-deps migrate` 성공.
  head `0030_prespec_review_exclusion`, 기존 notice 840건 included/변경 정보 null 확인.
  새 네 열의 UPDATE는 app=true·worker=false임을 확인했다.
- 새 이미지 `77ba2061f537`로 web·analysis-worker·prespec-attachment-worker를 교체했다.
  웹 기동 때 WSL/Tailscale의 18787 포트 충돌이 있어 해당 전달만 해제→기동→원상 복원했다.
  web healthy, 두 worker running, 기존 자동 실행·개요·GPU 600/300 설정 유지 확인.
- 운영 읽기 검사: health=ok, `/pre-specs`=200, 전체 이력 total=145와 새 네 필드,
  actionable+excluded total=0, 빈 제외 요청 422를 확인했다. daily-trigger는 기존 v4의
  effective_enabled=true를 유지한다. 실제 공고의 제외/복원 저장은 운영 데이터에 실행하지 않았다.

배포는 현재 미커밋 소스로 빌드했으며 commit·push는 하지 않았다. 배포 뒤 daily lock을 해제했다.

## 탐색 화면 구조 통일·발주계획 일괄 추적 종료 (2026-09-20, main 병합·운영 web 배포)

결정은 [ADR-0062](decisions/0062-explore-workspace-structure-unification.md)·[ADR-0063](decisions/0063-order-plan-bulk-tracking-end.md),
승인 시안은 `docs/0915_ui-redesign/mockups/0920_explore-unify/`다. 브랜치 둘을 2026-09-20에 main으로 병합했고(`af4ca2c`) 같은 날
운영 web만 새 이미지로 교체했다.

배포 기록(2026-09-20 22:38 KST, 사용자 요청): 롤백 태그 `before-explore-unify-bulk-end-20260920`, 전체 백업
`backups/postgres/full/bidops-20260920T133747Z.dump`(25.7MB), migration 없음(head `0029_c2_quality_gate` 그대로), compose 파일 5개 +
env 파일 4개 + `--profile prespec`로 `build web` → `up -d --no-deps --no-build --force-recreate web`. 교체 뒤 healthy·포트
`127.0.0.1:18787`·플래그 5개(`BIDOPS_C2_EXECUTION_ALLOWED`·`C2_DAILY_TRIGGER_ENABLED`·`PRESPEC_OVERVIEW_ENABLED`=true,
GPU 600/300)가 그대로 렌더된 것과 `GET /api/order-plan-screening/daily-trigger`의 `effective_enabled=true`(v4)를 확인했다.
worker 컨테이너는 건드리지 않았다.

실제 스택 확인(운영 데이터를 바꾸지 않는 범위): `POST …/bulk-end`에 빈 body → 422(route 존재, 쓰기 없음), `bulk-start` 동일 422,
실제 `미선택` 계획 3건으로 읽기 전용 `preview` → `eligible_plan_count=3`, 운영 화면 1280×800에서 `선택 항목 추적 시작`·
`선택 항목 추적 종료` 단추·필터 아래 줄 `수집 회차`·리사이저 없음·두 화면의 발주기관 블록·목록 안쪽 페이저를 DOM으로 확인.
일괄 종료의 실제 저장은 2026-09-20 22:42 KST에 담당자가 운영 화면에서 1회 실행해 확인했다(사람 보고 + 서버 상태 대조):
web 접근 로그에 `preview` 200 → `POST …/bulk-end` 200, `GET /api/order-plans?tracking_status=종료` 7건이 모두 같은
담당자·같은 사유로 13:42:34.588~.630Z의 한 transaction에 기록됐고, `미선택` 총수가 1,387 → 1,380으로 7 줄었으며,
그중 한 owner의 `tracking-decisions`에 `미선택 → 종료` 감사 이력이 있다. 이 경로는 **검증됨**이다.

| 브랜치 | 내용 | 상태 |
|---|---|---|
| `feat/order-plan-bulk-end-backend` | `POST /api/opportunities/order-plan-tracking/bulk-end`(서비스·스키마·router·테스트), ADR 2건, business-rules·contracts·findings·이 문서 | 구현됨·검증됨(TestClient/서비스 수준) |
| `feat/explore-unify-frontend` | 발주계획 행·상세 pane 파일 분리, 공용 primitive(`AgencyFeature`·`SelectionToolbar`·`ListColumns`·`ListPager`), 두 화면 구조 통일, 일괄 종료 창·툴바·종료 뒤 목록, 승인 시안 원본, `web/frontend/AGENTS.md`·`decisions.md` | 구현됨·검증됨(mock 화면 수준) |

검증(리더 실행):

- 백엔드: 일회용 `postgres:17.11` + `BIDOPS_TEST_POSTGRES_URL`로 `tests/lifecycle/test_order_plan_bulk_end.py`·
  `test_order_plan_bulk_tracking.py`·`tests/app/test_api_order_plan_bulk_tracking.py`·`test_module_boundaries.py` →
  **138 passed · skip 0**. 기존 bulk-start 단언은 고치지 않았고 start의 canonical hash·receipt id가 변경 전후로 같음을
  고정값으로 단언한다. migration 없음(Alembic head 0029 그대로).
- 프런트 최종 트리(`45aef25`): `npm run build` + `test:screens`(app·layout-laptop·layout-desktop) 1회 →
  **640 passed · 4 failed · 6 skipped**. 실패 4건은 모두 이 변경의 회귀가 아니다 —
  `admin-workspace-consistency.spec.ts:23` 2건과 `common-interactions.spec.ts:266` 1건은 수정 없는 main에서도 똑같이
  실패하고(findings), `draft.spec.ts:63` 1건은 단독 재실행에서 3 passed인 부하 flake다.
- 접근성 실측(1280×800, 화면 축소 0.9 뒤): 선택 툴바 단추 높이 25.19px, 사전규격 sticky 상세 머리와 본문 컨트롤 겹침
  0%(머리가 스크롤 컨테이너의 형제), 새·이동 단추 포커스 링 2px. 행 체크박스는 14.39px로 24px에 못 미친다(findings, 결정 대기).

검증되지 않은 것:

- 실제 스택에서 확인하지 않은 가장자리: 200건 초과 차단, 같은 request ID 재전송(receipt replay), 저장된 대기 요청 복구,
  소유 사업기회 없는 계획의 실패 항목. 이들은 PostgreSQL 테스트와 mock 화면 검사로만 증명돼 있다.
- 픽셀 기준선 7장은 2026-09-20 사용자 승인으로 교체했다(`dd5da1d`). 5장(dashboard·criteria·opportunities-list·
  deep-review-complete·bid-delta-changed)의 사유는 `acdf0d9`(사이드바 나라장터 바로가기)가 기준선을 갱신하지 않은 것이고 —
  수정 없는 main에서도 같은 7장이 달랐다 — `order-plans-list`·`pre-specs-list` 2장의 사유는 ADR-0062와 그 사이드바 링크다.
  같은 커밋에서 `common-interactions.spec.ts`의 "사이드바는 7항목"을 주 메뉴 항목만 세도록 고쳤다.

시안과 달라진 곳은 `docs/0915_ui-redesign/decisions.md`의 같은 날짜 항목에 있다.

## 일일 운영 고도화 (2026-09-18, 2026-09-19 main 병합·운영 배포)

[일일 운영 고도화 계획](../0918_daily-operation/plan.md)의 웨이브 1~5를 구현했다. 통합 브랜치는
`feat/do-integration`이고 2026-09-19 `main`에 병합했다. 같은 날 운영에 배포했다 — 백업 뒤 격리 리허설을
거쳐 migration `0027`~`0029`를 적용했고(운영 head `0029_c2_quality_gate`), web·analysis-worker·
prespec-attachment-worker를 새 이미지로 재생성했으며(이전 이미지는 `before-do-20260919` 태그), 테스트 SQL 활성 행 v2를
retire CLI로 내렸다. **C-2 실행·일일 자동 실행·cron은 켜지 않았다**(`BIDOPS_C2_EXECUTION_ALLOWED=false`,
`BIDOPS_C2_DAILY_TRIGGER_ENABLED=false`, 활성 policy 없음).

구현된 것: migration `0029`(신규 테이블 4개 — 품질 게이트·evaluation·감사 표본·일일 자동 실행
스위치 — 와 실행 행 `purpose` 컬럼), policy 파일 적재 CLI(`app/screening/c2_policy.py`), C-2
policy REST·활성화(런타임 blocker 계산·후보 지정), 일일 자동 실행 스위치(4중 기본-닫힘), 품질
게이트 저장소·REST·판정 규칙(게시일별 채점, 두 pass 중 나쁜 쪽 값), 감사 표본 산출(상한
N건·층 3종·`pending_human_approval`/`not_applicable`), 판정의 누적 투영(policy 교체 뒤에도
과거 판정이 남는 v4), 실행 게이트 수정(`X-BidOps-Trigger` 헤더·`purpose`·측정 전용 실행 경로·
파일 status 검사 제거), 참조 적재가 policy 행을 활성으로 만드는 우회 차단(ADR-0060), 개요 run
중복 방지(결정 28 — 완료·확인대기 run이 있으면 같은 문서·policy digest의 자동 재관측이 새 개요
run을 만들지 않음), GPU 휴지(연속 가동 시간 기준, 기본 꺼짐), 일일 스크립트의 트랙 분리·전일
기준·회차 조회·`-retryN`·단계별 따라잡기·C-2 실행 연결(`scripts/run-daily-lifecycle.sh`·
`scripts/run-daily-c2.sh`·`scripts/c2-execution-common.sh`), 게이트 측정 스크립트
(`scripts/run-c2-gate-measurement.sh`), gold 게시일별 분할 도구
(`skills/bidops-collect/scripts/split_order_plan_run_by_day.py`), C-2 활성화 화면(기준 화면의
`발주계획 선별 정책` 탭, `/order-plan-policies`), 발주계획 화면의 누적 기본·판정 policy 버전·
첫 관측일 표시·자동 실행 꺼짐 배너.

결정 28(공고 수집 창을 기준일 포함 4일로 — 사전규격이 등록일 `rgstDt`로 조회되고 접수일
`rcptDt`부터 공개돼 1일 창이면 영구 누락이 생긴다는 늦은 색인 측정에 근거, [M0 기록](../validation-runs/20260918-late-indexing.md))도
이번 웨이브에서 반영했다.

아직 못 켜는 것은 [`plan.md` §4](../0918_daily-operation/plan.md)의 표가 정본이다 — 발주계획
트랙 자체, C-2 실행, 게이트 `통과` 판정, policy 활성화, 감사 표본 실제 draw, 무인 일일 운영은
모두 v3 policy·binding 발행([`plan.md` S3b](../0918_daily-operation/plan.md))과 아래 사람 결정
값을 기다린다.

### S3b — v4 policy·binding·generation config v5 발행 (2026-09-19, 미배포)

D-c·D-d 값이 2026-09-19에 나와 먼저 v3 두 파일을 발행했으나, **v3로는 제품 실행이 되지 않았다** —
게이트 측정 pass 1에서 워커가 모델 호출 전에 `binding_mismatch`로 실패했다. 동결된
`generation-config.json`(= generation config **v4**)의 `model_revision`이 `6ae70ca3…`인데 v3
binding의 `model_digest`는 `5fa804ff…`였고, 워커가 그 둘을 대조한다
(`workers/order_plan.py:383-391`). `model_digest`를 바꾸려면 generation config를 함께 새로
발행해야 한다([findings](findings.md)).

그래서 generation config **v5**와 policy·binding **v4**를 발행했다. 운영 DB의
`c2-order-plan-screening-v3` 행(candidate, 게이트 `c2gate-203ab7a5…`)은 버전+digest가
immutable이라 재사용할 수 없어 그대로 남는다. v2·v3 파일과 generation config v4는 bytes 불변이다.
**값은 전부 PoC용이며 운영 전환 때 다시 정한다**(승인자 `jechoi`, 승인 시각
`2026-09-19T08:05:23+00:00`, 파일의 `decision_note`에도 남겼다).

- `experiments/order-plan-screening/config/order-plan-screening-generation-config.v5.json`
  (sha256 `82ced6035d95313f889cd32cc3b5b414b98334f5f090745f0cedb0564804a405`) — v4에서
  `model_revision`(→ `5fa804ff…`)과 `method_version`(→
  `vllm-qwen-order-plan-batch-nonthinking-v5`) 둘만 다르다. 다른 값·키 순서·서식은 그대로다.

- `experiments/order-plan-screening/config/order-plan-screening-policy.v4.json`
  (`policy_version=c2-order-plan-screening-v4`, sha256
  `c5abe3e3fbd3a628486e8a3ee05ce009ac488c9b9df8e83a0f0c22cd6d877461`) — `audit_sample`:
  `enabled=true`, `max_per_execution=10`, `review_cadence="weekly_mon_thu"`(월·목),
  층 배분은 우선순위 소진 그대로, `strata_rules`는
  `classification_proximity={field: contract_method, values: [제한경쟁, 일반경쟁]}`·
  `performance_similarity_proximity={rank_window: 25}`. `replacement: none`의 범위는 한 draw(하루)
  안이며 이는 구현이 이미 그렇게 동작한다 — 파일에 키를 새로 만들지 않았다.
  `quality_gate.targets`는 **`null`**이다 — 임계값 정본은 DB 게이트 행이다(ADR-0060 §2).
  `quality_gate`의 gold 스냅샷은 adjudicated **v3** 기준이다(`queue_human_adjudicated`, manifest
  `72d6749d…`, artifact `cbdb7adf…`, 사람 확정 109·초안 516·잔여 0).

  층 정의 값의 근거(gold v3 625건·관련 54건, `contract_method`별):

  | `contract_method` | 전체 | 관련 | 관련율 | 층 |
  |---|---:|---:|---:|---|
  | 제한경쟁 | 330 | 37 | 11.21% | `classification_proximity` |
  | 일반경쟁 | 122 | 13 | 10.66% | `classification_proximity` |
  | 수의계약 | 161 | 4 | 2.48% | — |
  | 지명경쟁 | 12 | 0 | 0.00% | — |

  층에 들어가는 두 값이 모집단의 72.3%(452건)에 관련 건의 **92.6%**(50/54)를 담고, 층 안 관련율
  11.06%가 층 밖 2.31%의 4.8배다(전체 기준선 8.64%). `rank_window: 25`는 게시일별 BM25 재계산에서
  탈락이 0·8·23·38·79건이던 6일 관측을 근거로 골랐다 — 상한 10건의 2.5배라 늘 채울 수 있고,
  탈락이 많은 날에도 `uniform_hash` 층에 꼬리를 남긴다.
- `…-phase0-binding.v4.json`(`status=approved`, sha256
  `682cb16dd2ac5ed622386a6cea42891633659f2d8073c3bcb6e1af419087790c`) — `external_transport`:
  `execution_allowed=true`, `approval_scope="per_binding"`,
  `approval_required_per_execution=false`, `approved_by="jechoi"`. 호출 대상 allowlist는 v2와 같이
  `endpoint_source: runtime_secret_and_literal_allowlist`로 두고 실제 host는 파일에 넣지 않는다.
  `stage2_binding.model_digest`는 2026-09-11·09-15 서버가 보고한 revision
  `5fa804ff0ecc0de9167f8b63127c42e1d421a9451662922ace8622d0b01b824e`이다(v2의 `6ae70ca3…`와 다르다).
  `gold` 절도 adjudicated v3 경로·digest·건수로 맞췄다.

`docker-compose.yml`(web·analysis-worker)의 마운트 세 줄과 `app/core/config.py`의 기본 경로
셋이 v4·v5를 가리킨다. **운영 반영은 아직이다** — 컨테이너 재생성, 적재 CLI 실행,
`BIDOPS_C2_EXECUTION_ALLOWED`, 활성화는 하지 않았다.

검증(발행 전, 실행 없이): 임시 SQLite 적재에서 행이 `draft`·`active_slot=NULL`로 생기고 digest가
파일 bytes와 일치하며 남는 blocker는 `quality_gate_missing` 하나다(마운트가 없으면
`policy_file_missing`이 하나 더). **서비스가 동결하는 것과 같은 6개 파일 묶음**
(`policy.json`·`binding.json`·`capabilities.json`·`prompt.txt`·`generation-config.json`·
`screening-input.json`)을 임시 디렉터리에 만들어 워커의 `_load_binding_inputs`와 `_load_ranking`
(실제 BM25 CLI subprocess)을 호출해 `binding_mismatch` 없이 통과하는 것을 확인했고, 같은 묶음에서
generation config만 v4로 되돌리면 `binding_mismatch`가 재현된다. `OrderPlanVllmAdapter`도 운영
env 값(`BIDOPS_VLLM_BASE_URL=http://192.168.0.139:58765/v1`,
`BIDOPS_VLLM_ALLOWED_HOSTS=192.168.0.139`, `BIDOPS_VLLM_MODEL_REVISION=5fa804ff…`)으로 생성만
해 보고 호출은 하지 않았다 — 통과한다. adapter가 generation config에서 읽는 것은
`max_output_tokens`·`timeout_seconds`·`chat_template_kwargs` 셋뿐이고,
`base_url_env`·`revision_env`·`allowed_hosts`·`allowed_bind_interfaces`·`bind_interface_env`는
제품 경로가 읽지 않는 실험 harness 서술 필드다(값 자체는 운영 설정과 어긋나지 않는다).

남은 사람 결정([`plan.md` §3](../0918_daily-operation/plan.md)): **D-a**만 열려 있다 —
2026-09-19에 확인 큐 87건을 사람이 전수 확정해 gold adjudicated **v3**(관련 54·비관련 571)가
됐지만 **큐 밖 516건은 여전히 초안 라벨이다**. 큐 밖 무작위 표본 크기와 "승인된 사람 gold" 최종
승인이 남았다. **D-b**(임계값 4개)는 값이 나왔으나 들어가는 자리가 DB 게이트 행이라 게이트 생성
때 기록한다. **D-c·D-d**는 위 v3 발행으로 닫혔고 D-d의 `BIDOPS_C2_EXECUTION_ALLOWED`와
방화벽·egress 승인만 남았다. **D-e**도 2026-09-19에 값이 나왔다(PoC용) — 활성화는 jechoi가 관리
화면에서 직접, 운영시작일은 게이트 통과·활성화 다음 날부터 매 달력일, cron은 공고 트랙 07:00·
발주계획 트랙 07:30(KST) 두 줄, 트리거를 켜기 전 확인 항목은 게이트 측정 2회(제품 경로 8실행)의
요청 수·소요시간·실패 분포로 갈음한다. 값이 없으면 관련 기능은 fail closed로 동작한다(정상).

기존 결함 두 건은 이번 웨이브의 변경과 무관하며 `main` 6191f35에서도 재현한다 —
`tests/deep_review/test_auto_preparation.py::test_the_flag_opens_preparation_for_sw_business_without_a_grade`,
`web/frontend/tests/admin-workspace-consistency.spec.ts:23`(1280×800·1440×900, `/runs`).

최종 게이트(2026-09-18, 통합 트리 bc7e338에서 1회): 백엔드 `pytest tests/` 2340 passed·5 skipped·2 failed — 실패 2건은 `test_module_boundaries.py`(새 `gpu_rest.py`의 모듈 배정·`screening→workers` import)로 e80ab21에서 `app/core/gpu_rest.py`로 옮겨 고쳤고 영향 파일 4개 55 passed; 파이프라인 `./run-tests.sh` 통과; 프런트 `tsc -b --force`·build 통과, `test:screens`(app·layout 2종) 631 passed·6 skipped·3 failed — `admin-workspace-consistency.spec.ts:23` 2건은 main 6191f35에서도 실패하는 기존 결함(`/runs`의 `.rs-detail-foot`), `bid-delta.spec.ts:508` 1건은 부하 중 단독 재실행에서도 실패했으나 부하가 낮을 때 단독 1회 통과(main에서도 통과) — 초안 수정과 재조회가 겹치는 부하 의존 flake로 판정. 기존 결함 `test_auto_preparation.py::test_the_flag_opens_preparation_for_sw_business_without_a_grade`는 단독 실행에서만 실패하고 전체 실행에서는 통과했다. S14 문서 병합(e2ec733) 뒤 코드 변경 없음.

병합 전 후속 수정(2026-09-19): 누적 모드 `scope.policy_versions`를 범위에 실행이 실제로 있는 버전으로 좁히고(대시보드 `no_completed_execution`과 함께 간다) `activated_policy_versions`를 더해 화면의 실행 상태 표시 범위를 활성화 이력으로 가른다 — 활성화된 적 없는 policy의 참조 실행을 "최근 운영 실행"으로 적지 않는다. 교체 없는 retire CLI(`python -m app.screening.c2_policy retire`, 사유를 담은 `c2.policy_retired` AuditEvent)를 더했고, 발주계획 선택 fingerprint에 추적 축을 정식으로 넣었다. ADR-0060·0061은 2026-09-19 사용자 승인을 받았다. 검사(병합 트리, 영향 범위만): 일회용 PostgreSQL 17에서 `test_order_plan_list_v2.py` 26 passed·skip 0, `test_c2_policy_retire.py`·`test_workload_projection.py` 통과; 프런트 `tsc -b`, `order-plans`·`dashboard`·`list-selection`·`order-plan-policies` spec 121 passed; pixel 8장 중 `order-plans-list`·`criteria` 2장을 승인받아 교체했다(나머지 6장 통과). 전체 스위트는 다시 돌리지 않았다. 운영 DB의 테스트 SQL 활성 행 `c2-order-plan-screening-v2`는 2026-09-19 배포 때 retire CLI로 내렸다([findings](findings.md)).

PoC 후속(2026-09-19, 브랜치 `feat/poc-ingest-cli-hooks`, 미병합): 게이트 측정 pass 1이 첫 회차에서
`409 source_run_incomplete`로 멈춘 원인을 고쳤다. 적재 CLI 프로세스에 lifecycle 확장점이 등록돼
있지 않아 CLI로 적재한 모든 회차에 `judgment_ingest_skipped` 경고가 남았고, C-2 실행 생성은 그
경고 하나로 회차를 거부한다 — 일일 발주계획 트랙도 같은 이유로 매일 막혔다. CLI가 이제
`BIDOPS_MODULES` 선택대로 web 프로세스와 같은 확장점을 등록한 뒤 적재하며(2026-09-11의 deep_review
첨부 자격 hook 누락 finding도 같은 수정으로 닫혔다), C-2 거부 사유는 서버 로그에 남는다(응답 계약은
그대로). 검사는 새 인터프리터로 적재하고 같은 DB에서 C-2 source run 검사를 부르는 통합 1건
(`tests/app/test_ingest_cli_extensions.py`)과 영향 파일의 기존 검사만 돌렸다. [findings](findings.md)

PoC 개시(2026-09-19): `c2-order-plan-screening-v4`가 게이트 `c2gate-9b40807f6d554473abd5087b2c6c5ca4`를
evaluation `c2gateeval-154ffbb1a6ff4c87ba43a2bd7f578181`로 통과했고(두 pass 동일 — recall 100%,
precision 36.7%, 중요 누락 0, 하루 최대 검토량 79, 일치율 100%; 여유가 작다) jechoi가 관리 화면에서
활성화했다(20:26 KST). 일일 자동 실행 스위치도 화면에서 켰다(21:53 KST, 사유 "PoC 일일 운영 개시").
독립 검증이 찾은 차단 결함(일일 스크립트가 C-2에 디렉터리 이름을 회차 id로 보내 매일 409)은
`b1f0013`에서 고쳤다. cron 설치 전 **감독 시운전 1회**를 cron과 같은 명령(`env -i`·`flock`·`timeout`)으로
돌렸다 — 회차 `lifecycle-20260918-plans`(271건, 적재 경고 0) → 정규 id 조회 → 운영 실행
`550b940f-3d65-41b0-8e5b-e31528f027c8` `성공`(약 8분, 관련 18·불확실 40·비관련 213, 실패 0, 사람 검토 58) →
감사 표본은 `not_applicable`(모집단 271 ≤ top_k 300이라 1단계 탈락이 없다), 종료 코드 0. 일일 경로가
운영에서 끝까지 돈 첫 사례다. 그 뒤 cron 두 줄을 설치했다(공고 07:00·발주계획 07:30 KST, 공용 lock
`~/.local/state/bidops/daily.lock`, 로그 `~/.local/state/bidops/logs/daily-{notices,plans}.log`, 설치본
`~/.local/state/bidops/crontab.bidops`). **공고 트랙은 운영에서 아직 한 번도 돌지 않았다** — 첫 무인 실행은
2026-09-20 07:00이고 4일 창의 첨부→변환→개요 연쇄 규모는 미실측이라 첫 2~3일 로그·경고·상태 분포를 본다.

첫 무인 실행 관측(2026-09-20 일, 기준일 09-19): cron 두 줄이 07:00·07:30에 떴고 둘 다 `complete`로 끝났다.
공고 트랙 `lifecycle-20260919-notices`는 4일 창(09-16~09-19) 2,329건 수집·적재(사전규격 669 중 87, 입찰 1,660)에
약 1분, 이어진 첨부 취득은 07:00~07:17에 `완료` 108·`차단` 12(형식·안전성 사유)로 끝났다. 적재 경고 155건은
`opportunity_link_target_missing` 154(입찰공고가 가리키는 발주계획이 DB에 없음 — 발주계획 누적이 이틀치뿐이라
예상된 것)와 `screening_results_missing` 1(C-1은 운영에 쓰지 않는다, 결정 27)이다. C-1 등급이 없으므로 문서 묶음·
개요 run은 그날 새로 생기지 않았다(**다음 날 관측으로 정정** — 연쇄는 하루 늦게 온다, 아래 09-21 단락). 발주계획 트랙 `lifecycle-20260919-plans`는 lock 대기 없이 07:30에 시작해 토요일분 16건을
경고 0으로 적재하고 운영 실행 `f181030b-7776-4301-8917-3ee5203eb428`이 28초 만에 `성공`(16건 전부 비관련, 사람
검토 0)했다. 데이터가 있는 평일분 무인 실행은 2026-09-22(화) 아침이 처음이다.

둘째 날(2026-09-21 월, 기준일 09-20): 두 트랙 모두 `complete`. 공고 4일 창 1,551건(사전규격 71 선별, 경고 101 —
전날과 같은 구성), 발주계획 일요일분 8건·경고 0·실행 `0603b811-2224-4bf7-8529-91b2f1f54dc3` 16초 `성공`(전부 비관련).
**전날 "공고 트랙은 모델을 부르지 않는다"는 관측은 하루짜리 착시였다** — 09-20에 취득한 첨부 108건이 09-21 아침에
문서 묶음 61건(ready 53)이 되면서 개요 run 51건이 enqueue됐고, 07:02~08:49에 모델 호출 97회로 처리됐다(완료 48,
`pdf_preparation_failed:conversion_required` 2, `claims_empty` 1). **연쇄는 하루 지연으로 온다.** 개요 건당 평균
102초(최대 146초), 분석 워커 단일 슬롯 점유는 약 1시간 45분이지만 C-2는 그 사이에 끼어들어 07:32에 대기 없이
끝났다 — 단일 슬롯 직렬이 발주계획 판정을 밀어내지는 않는다. 평일분(발주계획 약 300건·GPU 8~10분)이 개요 큐와
겹치는 것은 2026-09-22(화) 아침이 처음이다.

## 사업 추적 연결·선별 적재·Go/No-Go 분리 (2026-09-17, main 병합 7249ae9·2026-09-19 운영 배포)

[사업 추적 연결·조치 고도화 계획](../0917_opportunity-tracking/plan.md)의 P0~P5를 구현했다 —
전량 수집·선별 적재·수집 색인(migration `0027`), 공식 키 병합 규칙 확장과 후보 대조·찾아보기,
재검토 신호 확장과 확인 처리, `조치 필요`·`신규 입찰공고` 구역과 보류 14일 재검토, Go/No-Go
결정 근거 분리(migration `0028`, [ADR-0058](decisions/0058-final-decision-basis-separated-from-comparison.md)·[ADR-0059](decisions/0059-full-collection-selective-ingest-and-index-search.md)),
일일 수집·적재 스크립트(`scripts/run-daily-lifecycle.sh`), 관련 화면 갱신을 갖는다. 백엔드는
`feat/ot-integration`(P0~P5-F0, `feat/ot-p1-1`·`-p1-2`·`-p1-3`·`-p2a-backend`·`-p2a-collect`·
`-p2b`·`-p2c`·`-p3`·`-p4`·`-p5-f0`를 통합) 브랜치에 있고, 화면은 `feat/ot-p5-f1`(사업 추적)·
`-p5-f2`(대시보드)·`-p5-f3`(Go/No-Go)·`-p5-f4`(사전규격 후보) 브랜치에서 만들어 `main`에 병합했다
(7249ae9, 픽셀 기준선 6191f35).

- 운영 DB에는 2026-09-19 일일 운영 고도화와 함께 배포했다(migration `0027`·`0028` 포함). `scripts/run-daily-lifecycle.sh`의 cron은 2026-09-19 밤 감독 시운전 뒤
  사용자 확인을 받아 설치했다(위 "PoC 개시" 단락).
- 프런트 픽셀 기준선은 승인받아 교체했다(main 6191f35).
- 대표 통합 테스트(`tests/app/test_tracking_lifecycle_flow.py`)와 단계별 게이트는 각 phase
  브랜치·`feat/ot-integration`에서 실행했다. 전체 트리 1회 게이트·최종 병합 결정은 아직
  남아 있다.
- 문서(`docs/0917_opportunity-tracking/`, 본 문서 갱신 포함)는 `feat/ot-p6-docs`에 있다.

## 사전규격 누적 탐색과 비교 서버 (2026-09-16)

- 검토할 항목·최근 수집·추적 중·전체 이력, 서버 페이지 이전 필터와 집계,
  관측 기간·회차 선택, 서버 다음 행동 안내를 구현했다. 원본·리뷰·추적 결정은 변경하지 않았다.
- API 관련 47개 검사와 프론트 관련 94개 검사(목록·선택·의미·두 지원 폭)가 통과했다.
  최초 실패는 원인을 수정한 뒤 영향받는 검사만 재실행했다. 실제 DB 확인은 조회만 수행했다.
- `bidops-web:luna-max`의 `web-comparison`을 18887에 별도 기동했다.
  기존 18787의 `bidops-web-1` 컨테이너 ID와 정상 상태를 유지했다.
  두 서비스는 같은 운영 DB를 사용하므로 사용자가 저장한 결정은 양쪽에 반영된다.
  Tailscale TCP 18887 전달을 추가하고 기존 18787·5173 전달을 보존했다.
  로컬 두 서버 health는 정상이며 같은 호스트의 tailnet hairpin 실패로 원격 기기 접속은 미검증이다.
- 실제 화면의 네 보기 조회 건수는 확인 시점에 9·59·1·59건이고 중복 공고는 없었다.
  기본 보기의 등급 필터 조작도 `workspace=actionable`을 유지했다.
- 1280×800·1440×900에서 전역 zoom은 1, 목록 폭은 각각 389.28125·450.078125px로
  기존 서버와 동일했다. 상세 줄바꿈·고정 바닥, 회차 드롭다운을 확인했다.
  로컬 비교 캡처는 `/tmp/bidops-prespec-before-{1280,1440}.png`와
  `/tmp/bidops-prespec-after-{1280,1440}.png`이며 영구 증거 경로는 아니다.
- 사용자 승인 후 같은 검증 이미지(`235e1d4b816f`)를 기존 `web`의 18787에 승격했다.
  기존 환경변수·네트워크·볼륨을 유지하고 웹만 재생성했으며 health 정상과 Tailscale
  18787 전달 복원을 확인했다. 이전 이미지는 `bidops-web:before-prespec-workspaces`로 보존했다.
  비교 서버 18887은 유지한다. 재빌드·migration·수집·모델 호출은 수행하지 않았다.

## 목록 다중 선택·일괄 추적·선택 상세 순회 (2026-09-13)

- 발주계획·사전규격의 체크 선택은 active 행과 독립이며 같은 탭에서 페이지·새로고침·상세
  복귀에 유지된다. 실제 필터 변경은 선택 generation을 바꾸고, 정렬 변경은 체크를 유지한다.
- 발주계획 일괄 추적은 preview와 사람 확인 뒤 `미선택` owner만 변경한다.
  기존 `IdempotencyRecord`의 JSON receipt로 같은 요청 결과를 재현하며,
  응답 유실·gateway 오류는 같은 UUID·payload로 수동 확인한다. 단건 결정·감사는 별도 경로다.
- 선택 사전규격 순서는 탭에서 마지막으로 본 시각·PK로 고정하고 opaque token으로 전달한다.
  로딩·조회 오류에도 이전/다음/목록 복귀가 남는다. 상세 record는 PK로 key를 분리한다.
- 격리 PostgreSQL 17 및 SQLite HTTP·동시성·receipt·기존 단건 계약 집중 검사와 목록 정렬
  검사를 수행했다. 브라우저에서는 교차 페이지 선택, 실제 체크박스·키보드, 저장되지 않은
  입력 취소, 같은 요청 복구, 지연 응답 격리와 1280×800·1440×900 화면을 확인했다.
  검사 중 발견한 receipt fixture·브라우저 assertion 문제는 원인을 수정해 해당 검사를 통과시켰다.
- 공통 확인창은 Astryx native dialog 한 경로로 통일했다. 다른 native dialog 위에서도
  취소 버튼을 실제 클릭할 수 있고, 취소하면 기존 입력과 포커스를 보존한다.
- 이는 현재 worktree의 합성 입력 검증이다. 운영 DB 변경·실제 사람 추적 결정·모델 전송·
  배포·정책 활성화는 수행하지 않았다. Compose·환경 기본값·DB migration은 변경하지 않았다.
  승인 계획의 최종 리뷰·완료 판정은 durable Ultragoal ledger에서 별도로 관리한다.

## 2026-09-11 오후 운영 DB 재수집과 첫 개요 run 5건

- 운영 DB를 초기화하고 재수집했다: 발주계획 482건, 사전규격 342건, 그중 `SW사업대상=Y`
  33건.
- 첨부 취득은 37건 완료·5건 차단으로 종결됐다. 문서 준비가 끝나 확정된 묶음은 28건
  ready다.
- 개요 run을 처음 5건 실행한 결과는 `needs_human_review` 4건·`input_capacity_exceeded`
  1건이다. 원인은 2단 레이아웃 인용 불일치, 목차 쪽 오선택, 60쪽 초과, 섹션 편중
  네 가지로 갈렸다.
- 후속은 `feat/p5-overview-quality` 브랜치에서 다룬다.

## 2026-09-11 BidOps MVP 배관 수리와 개요 스택 재작성

- P0(모델 게이트 완화, 첨부 plumbing, blocked projection) 브랜치 세 개를 `main`에 병합했다
  (`b0814e4`). ADR-0050 §5 "모델 호출 게이트의 MVP 기간 완화" 항목이 이 병합의 결정 근거다.
- P1(문서 정리) 진행 중: v3 권고형 개요·legacy v4 단일 호출·v5 주장 검증 스택
  (activation v2·call ledger·verification)의 계약·운영 문서를 제거하고
  `prespec_overview_run`(migration 0026) 단일 테이블 기반 MVP 개요 계약으로 재작성했다
  ([ADR-0054](decisions/0054-prespec-overview-mvp-rewrite.md)). `docs/0910_prespec-workflow-hardening/`
  폴더는 삭제했으며 상세는 git 이력(`71b9954`)에서 찾는다. 이 절의 코드(analysis worker 개요
  slot·REST·화면)는 아직 이 문서 갱신을 따라가지 못했고 후속 P2·P3에서 구현한다.

## 사전규격 화면 담당자 브리핑 재구성 (2026-09-12, 프론트 전용)

ADR-0055(git 이력 docs/design/ADR.md, 삭제됨)를 구현했다. 상세는 등급 사유(회차 판정과
사람 정정을 분리), 본공고 칩·품명 분류, 첨부 목록과 다운로드, 범위 확정 알림+왼쪽 폼,
문서 준비 요약과 조건부 토글, 검증 진단·해시의 이력 이동을 갖는다. 목록은 등급 글자 토큰,
`auto_preparation_status`(서버)·`tracking_decision=pending`(페이지 한정) 필터, 키보드 이동,
다음 작업 한 문장을 갖는다. 백엔드·수집기·REST 변경은 없다.

검증과 계획과 다르게 결정한 세 항목은 [20260912-prespec-briefing-ux.md](../validation-runs/20260912-prespec-briefing-ux.md)에
있다. 픽셀 기준선 `pre-specs-list` 갱신과 B군(원문 URL·수집 필드·메모·서버 등급 필터·
본공고 보기)은 후속으로 남았다.

## 사전규격 수집·주장 검증 안정화 (2026-09-10, 0025·웹 배포 / 0910 수집 완료)

최신 실제 결과: 사용자가 추가 방화벽 체인 조회를 이번 기능 실행에서 생략하도록 지시한 뒤,
744·749·759·761의 고정 v5 입력으로09:08–09:13 KST에 Qwen을 실행했다. 실제 모델/revision/
context262,144 일치, **입력 준비4·모델 실행4·내용 검증 통과0**이다. 초안4회 모두 응답했으나
필수 main_tasks 누락(744·749·761), 수치/단위 metadata, 분석 전제·미확인 사유의 결정적
검사에서 모두 needs_human_review로 종료했다. semantic0·형식 재생성0·최종 결과0이다.
기존10개 테이블 기존 행 지문은 같고 새 attempt/job/verification/암호화 응답각4·call 이벤트8만
추가했다. 네 v2 API와 실패 attempt PDF는200·승인 SHA 일치다. OFF
`a6e96d1b-9c8a-40b6-87f7-d1e177c21222`, active0이며 unmeasured_reference를 유지했다.
추가 migration/build/재수집/재변환·C-1/C-2·회사 핏/심층 실행은 없다. 원문·정책·검증·호출
상한은 바꾸지 않았고 host 방화벽 규칙 전체의 확인은 생략한 예외로 기록했다.
검증된 최종 개요까지의 실사용 완주·사람 대조·실제 브라우저 두 폭 확인은 아직 아니다.
[실행과 확인 결과](../../.dryforge/prespec-qwen-0911-mHF0bO/README.md). 아래는 모델 실행 전 기록이다.

2026-09-11 MVP 보완: native의 정상 outline·후보 전체/반환 개수를 수용하고 보조 digest
실패를 검증된 core와 분리했다. 공백 쪽의 원문·번호·hash 보존, 후보 유무와 무관한 수동
쪽 선택, attempt 없는 target PDF 열람, 새 범위 뒤 옛 실행/현재 결과·후속 입력 차단을
구현·격리 검증 후 운영 web·document-worker2에 반영했다. 최종 image는
`bidops-prespec-mvp:20260911-advisory-final`(digest `223019128c101ea131d855256c950d06f0edda393281556656c1cea1e4c72d9f`),
head0025·기존 환경/네트워크/권한/볼륨 그대로다. 이전 실패6건만 각1회 core 준비에 성공했다.
754·755의 제안 작성 양식 오선택도 최소 가드/기존 모호성 경고로 연결하고 기존 target을
보존했다. 교차검토에서 후보 없는 core의 scratch 전달 누락도 경고/명시적 null·기존
snapshot/cache로 연결했고, JSON null 후보와 핵심 hash 훼손은 거부한다(고유 경계8건 통과).
0910 입력 준비 가능은744·749·759·761 **4건**, 실제 Qwen 실행 **0건**,
내용 검증 통과 **0건**이다. 안전한 PDF는15건(기존9 재사용+이번6)이며 수동 범위11건,
문서 선택/안전4건은 남았다. 원본·기존 결과/사람 리뷰/실패/객체 행 지문은 동일하고
snapshot6·target6·객체/location각34만 추가했다. source-only ON/OFF1쌍 뒤 최종 OFF는
`fe91c298-aceb-47b2-95e9-7560edc04be1`이며 모델 activation/enqueue는0이다.
실제 v2 경고·직접 쪽 선택 가능 상태·PDF200/hash/안전 헤더를 확인했다. C-1/C-2·이전4건
payload·정상9건 변환·통과한 기존 검사는 재사용했다. 상세 검증과 승인 경계는 당시
"MVP 체크와 결과"(0910 안정화 Plan, 2026-09-11 개요 스택 재작성으로 폐기·git 이력 `71b9954`)를
따랐다. 아래는 이전 시점 기록이다.

당시 작업 정본은 0910 안정화 Plan(폐기, git 이력 `71b9954`)이었다. 회차/파일
배타 생성과 raw 재분류 새 경로, policy v5의 결정적 검사+별도 Qwen 의미 검토 계약,
검증 ledger/migration `0025_overview_claim_ledger`, 조회 v2·실패 근거 PDF·웹 상태·회사 핏
reader와 worker 복구·중지 fence를 구현했다. 임시 PostgreSQL의 중지/게시 경쟁 4건도 통과했다.
추가 요청인 5,000자 일괄 차단 제거·실제 두 단계 요청/context 예산과 미실행 표시도 구현했다.
두 stage의 정확한 경계값, 원문 무절단, 해당 단계 호출 전 실패, API·화면 두 폭과 실제 DB의
failed 원자 종료를 선택 검사했다. 최종 diff 리뷰의 context metadata·화면 문구·범위 조회
구조 읽기 namespace 보완도 해당 검사만 통과 확인했다. 전체 스위트는 재실행하지 않았다.

collector/호출부, 순수 검증기, 폐기용 PostgreSQL 17.11의 migration·권한·불변성, API/회사 핏,
frontend build와 개요 화면 두 지원 폭을 확인했다. 수치·명령·실패 수정 기록은 Plan에 모은다.
기존 사용자 회차 6개·백업·사람 리뷰·이전 v3/Luna 결과는 보존한다. 변경 collector로 별도 새
회차에 기존 raw 673건만 오프라인 재분류했고 원본/복사본 hash가 일치했다. 35(5,962자)·
142(6,849자)는 전체 원문을 포함한 초안 및 예시 의미 요청 모두 예산 안이다. 의미 예시는
모델 응답이 아니며 실제 초안 이후 다시 검사해야 한다. 59를 포함한 세 표본의 정확한
target/input/model/policy와 최대 9회 승인 준비물은 Plan에 연결했다.

현재 운영 DB는 사용자 승인으로 0025까지 적용했고 web은
`bidops-overview-claims:20260910-runtime-head`(digest `7d2ff95f04152520d81bba6c229251e2898ee8b05d7937da30b8d00da33723ca`)다.
백업 역할의 현재/미래 sequence SELECT만 복구해 새 DB dump(22,530,409 B)를 확보했다.
기존 객체 백업은 active 참조596개를 모두 포함하며, 기존82개 table의 값·사람 리뷰·개요·품질
표식은 새 nullable 열/명시 migration 감사1건을 제외하고 동일하다. 웹 기대 revision 누락은
수정 후 해당 PostgreSQL 기동 경계2건 통과, healthy·health/SPA/세 개요 API200을 확인했다.
문서 worker2개는 기존 R7 이미지·컨테이너·설정 그대로다. activation은 OFF이며 운영
analysis-worker와 v4 active attempt는 없다. 기존 web의 회사 핏 true 설정도 변경하지 않았다.

추가 요청의 `prespecs-20260910-claims-reference-sbh1rl` 회차를 21:40:13 KST에 실제
수집했다: 225건(후보32/감사193), HTTP1회·경고0, SW=Y20건 중 첨부 있음19건이다.
당일 종료 전 snapshot이며 [배포·수집 증거와 개요 대상 제안](../../.dryforge/prespec-deploy-20260910-SBh1rl/README.md)에
정확한 목록을 남겼다. 후속 승인으로 첨부 있는19건(analysis10/audit9)을 새 validation-set에
고정하고 DB notice743–761로 적재했다. 적재 직후 첨부27개 대기, C-1 결과 없음 경고1건이며 등급·
리뷰·모델 결과는 만들지 않았다. API19건 대조와 원문/표본 사본 hash 일치 확인 완료.
첨부/target 준비는 당시 host firewall 조회의 관리자 인증 부재로 보류했다. 당시 G2B 목적지
`211.42.74.250:443`에 대한 정확한 worker source의 규칙 확인이 필요하며 권한 우회나
방화벽/egress 변경은 하지 않았다. [신규 준비 증거](../../.dryforge/prespec-0910-preparation-3vfrYK/README.md)에
목록과 재개 조건을 남겼다. 그 시점에는 신규 원문/PDF·payload/용량 검사·전송 승인·Qwen이 미완료였다.
후속 관리자 조회에서 DOCKER-USER가 비어 있고 기존 전용 체인이 없음을 확인했으며,
사용자는 전용 worker의 최소 방화벽 추가를 승인했다. 고정 source/bridge/DNS 검사와
기존 규칙 보존을 포함한 적용 스크립트의 구문·비관리자 거부를 확인했다. 에이전트 세션의
sudo 인증이 없어 당시에는 관리자 직접 적용과 실제 통신 검증을 대기했다.
후속 사용자의 스크립트 적용 보고 뒤 동일 source172.19.0.2에서 G2B443 TLS 허용과
외부1.1.1.1:443·G2B80·host18887 차단을 확인했다. 첨부27개를 한 번씩 처리해 완료23/차단4,
안전한 RFP15개를 기존 R7에서 준비해 PDF snapshot9/범위 ready5/사람 확인4/변환 실패6을
얻었다. source-only activation 후 OFF `e898cbe3-a50c-4a1a-a9e3-477ef277b758`로 종료했다.
원본15개의 version/hash/size와 PDF 준비 직전 개요8·attempt7·개요 검토 행140개 지문은 동일하다.
호출 전 검사에서744·759는 공백 선택 페이지로 manifest_invalid, 753은 전체65,141자로
input_capacity_exceeded가 되어 기존 준비 실패 상태로 DB/API에 반영했다. 원문 절단·요약·
변환 변경·모델 전송은 없다. 749(6,592자)·761(798자)만 전체 원문의 초안/형식/의미 예시
요청 용량 준비가 끝났고 정상4회/최대6회 전송 승인 대기다. context262,144는 과거 확인값,
의미 예시는 모델 응답이 아니며 실제 초안 이후 재검사가 필요하다. 신규 준비 차단은
[findings](findings.md)에 남겼고 전체 검사는 반복하지 않았다. 상세한 건별 결과·준비물은
[이번 준비서](../../.dryforge/prespec-0910-preparation-3vfrYK/README.md)가 현재 기록이다.
이번 Qwen HTTP는0회이며 아래 과거 결과나 `unmeasured_reference`를 새 v5 품질/실행 승인으로
재사용하지 않는다. 세부 검증·운영 시각과 남은 체크는 Plan에 기록한다.

후속 “Qwen 호출 전까지만” 준비에서는 새 고정 이미지(head 0025)와 모델 연결 없는 읽기 전용
one-shot/배포 overlay를 만들고 실제 worker 계정의 세 표본 입력 읽기를 확인했다. 객체 966
version 백업은 hash 대조까지 완료했다. DB dump는 ro_backup의 sequence SELECT 누락으로
실패(0 B)해 당시 운영 권한 복구·새 DB 백업·migration/웹 교체를 보류했다. 당시 운영은 0024/OFF,
active v4 attempt 0이며 모델 HTTP·활성화·예약·모델 worker 실행은 없었다. 상세 준비물과
실패 증거는 Plan에 연결했다. 이 후속 점검에서도 앱 테스트 전체를 재실행하지 않았다.
독립 점검에서 준비 binding의 provider 표기 불일치를 찾아 이전 준비본은 보존하고 표준 runner와
일치하는 `.runtime.json` 준비본을 새로 만들었다. 실제 모델·revision·정책·요청 bytes는 같으며
모델 호출 없이 binding 일치를 확인했다. 새 승인에는 준비서가 가리키는 runtime 파일을 쓴다.

## 사전규격 v4 최신 운영 상태 (2026-09-09)

- 명시 sample activation은 OFF이다. `AuditEvent` `07c1d75a-c36a-48c7-9de5-a7efa1e741c7`가 `reference_samples_complete_with_142_unverified` 사유를 남긴다. 142·35·59 모두 grade는 `None`이며 automatic priority/auto-deep를 우회하거나 강제하지 않았다. 사람 결정은 변경하지 않았다.
- notice 35 개요는 result `a28a188b-0638-4dbb-b867-ea5a12c6c168`로 completed/current다. 회사 핏은 attempt `bb2d93f4-1915-4e72-a4f5-f647d8860a5e`, `completed/current/unknown`, raw SHA-256 `c147828b4efa9423d7af2ac138705e8d775a5a8c674a543275fb35dfc276d822`이며 API가 Luna reference 첫 응답과 exact 일치한다.
- notice 59 개요는 result `04d6182f-f073-450a-b8be-30f141db9f02`로 completed/current다. 회사 핏은 attempt `4af5b488-59c2-445e-8cf3-4a33baad44be`, `needs_human_review/current`, result는 `null`, raw SHA-256 `67b292a7ca012a7995f7a98d7be11d972fd97e72b603cf5e17552cb272254f11`이다. `unsupported_number` 사유로 index 0의 선택 근거에 24시간이 없어졌고, 암호화 raw를 보존했으며 보정·재시도하지 않았다.
- notice 142 PDF는 반복 timeout 뒤 `unverified`다. offline Luna JSON은 참조 입력으로만 보존하며 성공 PDF/current로 승격하지 않았다. 35/59 실제 UI는 사업명 검색·목록/상세·독립 상세·refresh/reentry, 1280×800·1440×900, API 본문·제한사항·prompt/result ID·PDF hash/link까지 통과했다. 35 `unknown` 근거와 59 `needs_human_review` 오류·안전 문구·판정 본문 비노출도 확인했다. 결과는 `.dryforge/prespec-v4-luna-20260909/ui-acceptance-result.json`과 script에 보존한다. 142 PDF와 automatic deep는 미검증이다. 원인은 document-worker `pids_limit` 128과 v4 CLI 기본 출력 예산 20 MiB로 확인돼 수정(pids 512·기본 64 MiB)이 `212e5ed`로 병합됐고, 2026-09-10 worker 두 개를 pids 512로 재생성한 뒤 142의 표준 PDF snapshot `e68670e0-4bf7-4cd9-baa1-174f19e5e994`(85쪽)와 target `200e9557-d5d5-4a0f-afa8-896d44b41261`(3~13쪽)을 준비했다. activation은 즉시 OFF로 되돌렸고, Qwen endpoint가 닿지 않아 attempt·`current`·UI 인수는 여전히 미완이다([findings](findings.md#원인-확인-notice-142-표준-pdf-준비가-300초-deadline에서-종료됨-2026-09-09)).
- 2026-09-10 rhwp R6 운영 인수: 백업(DB dump·객체 960 version) 뒤 `0023_rhwp_snapshot`을 적용하고 web·document-worker 2개를 native 이미지 `bidops-rdp-r6:20260910`(Chromium·Node 없음, `fontconfig` 포함, pids 128·1 GiB)로 재생성했다. explicit_sample 활성화 `d73daa62-…` 아래 142 native snapshot `f8a42b74-8710-4cc8-90f0-9ca8ae4ed3f1`(`rhwp-svg-pdf`, 79쪽, 기존 구조 `22541eb7-…` 결속, 대응표)·target `f7c73503-8f70-47d4-a309-c9fbd9cfd122`(4~12쪽)와 59 snapshot `3aa6c47f-cd73-49dc-945c-c0c835fd4b98`(원본 PDF)·target `ec040093-227e-4708-a9ed-b7889cf901d0`(3~5쪽)을 준비하고 즉시 OFF(`5016643f-…`)로 되돌렸다. attempt는 endpoint 부재로 없다. **35는 native 준비를 보류했다** — 새 구조 blocks 1,454 ≠ 기존 1,349로 `structure_binding_mismatch`가 나고 실패 attempt가 `current`를 덮기 때문이다. `overview-pages` 35/59/142는 준비 전후 byte 동일, 142 segments는 `mapped` 35·`partial` 42, `GET /api/document-structures/22541eb7-…/pdf` 200, 두 폭 화면 오류·넘침 없음. Canvas 시절 snapshot·target·attempt는 모두 보존됐고 pids 512 worker는 이 재생성으로 128이 됐다([R6 기록](../validation-runs/2026-09-10-rhwp-pipeline.md)).
- 2026-09-10 rhwp R7 범위 선택 보조 운영 반영: `0024_section_candidates`를 적용하고 web·document-worker를 `bidops-rdp-r7:20260910`으로 재생성했다. worker는 이제 rhwp `digest --sections`로 절 후보(산출물 ⑦)를 snapshot에 결속하고, heading 선택기가 범위를 못 정하면 실패 attempt 대신 `needs_human_review` target을 남긴다. 사람은 사전규격 상세의 `개요 범위 확인` 카드에서 시작·끝을 확정해(`POST …/overview-pages/range-confirmations`) `human_confirmed` ready target을 만들고, LLM 보조는 `prespec-v4 --assist-range`로만 제안(감사 행)한다. 어느 경로도 attempt를 만들지 않는다. 기존 35/59/142 응답은 `range_review: null`이 추가된 것 외에 동일하며 R6 snapshot에는 후보가 없다(새 snapshot부터 생김). 실표본 확정 대기 target이 없어 사람 확정 흐름은 테스트로만 확인했다([R7 기록](../validation-runs/2026-09-10-rhwp-r7-range-review.md)).
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
| ERP 사전규격 개별 상세 | 2026-09-08 승인 시안 적용. 왼쪽 일반 스크롤, 오른쪽 400px 결정 패널. 공식 번호 16px·복사·수집 URL 원문 열기, 핵심 요약·확인 사항, 사유 드롭다운·기타·담당자·저장. 서버 18787 반영. 이 배치는 2026-09-09 브리핑형 재배치(헤더 상태 칩·헤더 아래 추적 결정 카드·팩트 6칸·우측 판단 열·하단 문서 준비/접힌 이력)로 대체됐다 | build·대비 9개·신규 8개·최종 집중 4개 통과. 전체 455 passed·11 failed·6 skipped 중 의도한 품질 상세 접기 검사 1개 수정 후 재통과, 기존 실패 10개 남음. 시각 19개·실제 API 반영 전후 각 8개. [검증 기록](../validation-runs/20260908-prespec-detail-ux-implementation.md) |
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
| 무드보드 색 팔레트 · 단계 A | **팔레트 승인 + 단계 A 완료(2026-09-04).** 무드보드(git 이력 `docs/design/moodborad.jpg`, 삭제됨)의 5색 anchor를 프로젝트 소유 테마 `bidops`로 옮기고 적합성 등급 4단을 slate 농도 ramp로 정의하기로 결정함(ADR-0048(git 이력 docs/design/ADR.md, 삭제됨), design/PRD.md(git 이력 docs/design/PRD.md, 삭제됨) §4.1) | 앱이 `bidops` 테마(무드보드 팔레트)로 돈다. `src/themes/bidops/`(171 token overrides + `grade-ramp.css`), `scripts/check-contrast.test.mjs`, `tests/design-shell.spec.ts`를 추가했고 AppShell·페이지 10곳의 scope와 `main.tsx` import를 옮겼다. `theme.css`의 `@theme`이 `:root`로 방출돼 Astryx 테마를 이기던 토큰 4개를 제거하고 shadcn `--color-accent`를 `--color-shadcn-accent`로 옮겼다([engineering-notes.md](../engineering-notes.md)). 지원 폭을 1280~1920px로 좁히고 검증 viewport를 laptop 1280×800·desktop 1440×900 두 폭으로 고정했다(ADR-0047). `--color-nav-text` 중복 정의를 없애고 사이드바 본문을 `--color-on-dark`로 통일했다. 충돌 토큰은 미이행 화면 가드 없이 **전역 적용**하기로 결정했다(2026-09-04). **검증:** 대비 6 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped(1280·1440·1920px 오버플로 포함), 전체 Playwright 370 passed·75 failed·3 skipped. 실패 75건은 `visual.spec` 스냅샷 73건(팔레트 변경에 따른 예상 실패 — 승인 없이 덮어쓰지 않는다)과 `order-plans.spec.ts:287` 2건(390px 전제의 기존 실패, 팔레트와 무관). **남은 것:** 시안 렌더 입력 교체와 v2 기준 이미지는 design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) §0-4 통과 뒤다. 그때까지 앱은 승인된 시각 기준선 없이 새 팔레트로 돈다. 팔레트 적용은 design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) §0-4(생성기 복원 대조) 통과 뒤에만 시작한다 |
| 공통 화면 primitive · 단계 B | **완료(2026-09-04).** 결정 액션 배치 두 형태, 접힌 보조 입력 영역과 append-only revision 이력, 등급 4단 한 벌, 좁은 폭 전환 제거 (design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) 단계 B) | `ReviewDecisionBar`(분할 화면 pane 바닥)·`ReviewSecondaryInput`(접힌 보조 입력)·`ReviewRevisionHistory`(append-only)를 `ReviewPrimitives.tsx`에 추가했다. 단독 상세는 기존 `StickyDecisionHeader`를 계속 쓰고 한 화면에서 두 배치를 섞지 않는다. `SplitWorkspace`의 `mobileView`와 `review-primitives.css`·`order-plans.css`의 좁은 폭 분기를 없애 세 화면(`OrderPlansPage`·`QueuePage`·`PreSpecsPage`)이 어느 폭에서도 두 pane을 유지한다(ADR-0047). `.badge-grade-*`·`.rail-grade-*`가 `grade-ramp.css`의 `--bo-grade-*`를 읽고, 쓰이지 않던 두 번째 등급 스케일(`.c2l-grade-tag`)을 지웠다. 390px를 전제하던 `order-plans.spec.ts:287`·`pre-specs.spec.ts:520`은 지원 폭 기준의 반대 불변식(두 pane 유지, 제자리 pane 교체, 페이지 이동 없음)으로 다시 썼다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `review-primitives.spec.ts` 16 passed, 전체 Playwright 382 passed·74 failed·2 skipped(단계 A 기준선 371·75·4). 실패 74건에 **새 실패는 없다** — 73건은 단계 A에서 이어진 `visual.spec.ts`(팔레트 스냅샷 72 + `/queue` 1280px 오버플로 1, 단계 B 변경을 되돌려도 같은 값), 1건은 `visual.spec.ts:257` flake(단독 실행 통과)다. **남은 것:** `OrderPlansPage`의 접힌 보조 입력은 아직 `defaultIsOpen`이다. 단계 C가 추적 결정을 pane 바닥의 결정으로 들이면 시안의 접힌 기본값으로 되돌린다 |
| 발주계획 추적 결정 계약 · 단계 C 선행 | **요청안 작성, 백엔드 파트 검토 대기(2026-09-04).** ADR-0046 결정 4가 추적 결정을 발주계획 화면의 결정 1로 채택했으나 그것을 읽을·쓸 REST 경로가 없다 | `order-plan-tracking-contract-request.md`(git 이력 docs/design/order-plan-tracking-contract-request.md, 삭제됨)로 요청안을 보냈다. 조사 결과 **새 table은 필요하지 않을 가능성이 높다** — 소유 사업기회와 `stage='order_plan'` official 링크를 `ingest/loader.py`가 이미 만들고, 상태 4값(`미선택`·`계속 추적`·`보류`·`종료`)과 append-only `AuditEvent`도 이미 있다. 없는 것은 (a) 발주계획 목록·상세 응답이 그 상태를 싣지 않는 것과 (b) 발주계획 식별자로 쓸 경로가 없는 것 둘이다. **묻는 것 5가지**는 요청안 §8에 있다(v2 schema 여부, 전용 endpoint 대 기존 PATCH, `opportunity_not_found` 409, `AuditEvent` 투영 대 전용 table, 사유 자유문자열 대 고정 집합). **검증 없음** — 제안이고 채택이 아니다. 단계 C 화면은 요청안 §7의 규칙(adapter 한 곳, 낙관적 갱신 금지, `계약 미구현`을 `미선택`으로 바꾸지 않음, fixture는 구현 근거가 아님) 아래 먼저 만들고, 계약이 구현·검증되기 전에는 단계 C를 완료로 적지 않는다 |
| 발주계획 화면 · 단계 C | **화면 작업 완료, 단계는 미완료(2026-09-04).** 추적 결정을 상세 pane 바닥의 결정 액션으로 만들고 사람 판단 수정을 접힌 별도 영역으로 분리했다 (design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) 단계 C) | `추적 시작`·`보류`·`추적 종료`·`이번 건 넘기기`가 pane 바닥에 있고 선택 즉시 다음 건으로 이동한다. 사람 판단 수정은 접힌 채로 `새 revision 저장`을 스스로 소유하며 두 결정의 mutation·경로·요청이 모두 다르다. 저장된 뷰를 segmented control로 바꿨고(축별 다중 선택과 AND/OR·URL 계약은 유지), 상단 요약 한 줄과 `실행 상세` 진입점, 목록 머리글의 조합 의미와 바닥의 숨김 고지, `실행 기록` 탭 이름을 시안에 맞췄다. 추적 상태의 세 값(`계약 미구현`·`사업기회 미연결`·`미선택`)을 서로 바꾸지 않는다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `order-plans`+`review-primitives` 52 passed, 전체 Playwright 391 passed·73 failed·2 skipped. 실패 73건은 단계 A에서 이어진 `visual.spec.ts` 그대로이며 **새 실패는 없다**. 단계 C에서 결정 액션 바가 상세 pane 전체를 덮던 flex 회귀를 잡아 고쳤고 바 높이를 테스트로 고정했다. **미완료 사유:** 완료 게이트 2·3(두 결정이 서로를 덮지 않는다)은 서버가 있어야 판정한다. 저장 경로는 아직 요청안이며 fixture는 구현 근거가 아니다 |
| 사전규격 화면 · 단계 D | **완료(2026-09-04).** 추적 상태를 묻는 자리를 하나로 제한하고 신규 건에만 결합 조작을 준다 (design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) 단계 D, ADR-0046 결정 6) | 발주계획에서 승계한 건(`origin='추적'`이고 추적 상태가 `미선택`이 아님)은 결정 form 자체를 그리지 않고 `계속 추적 · 발주계획에서 승계` 배지만 남긴다. `보류`·`추적 종료`를 두 사전규격 화면에서 없앴다 — `TRACKING_DECISION_STATUSES`가 `계속 추적` 하나가 됐고 그 둘은 사업 추적에서만 고른다는 문구를 남긴다. 신규 건에만 `추적 시작하고 심층 검토`를 한 조작으로 주되 **기록은 둘이다** — 추적 시작만 저장하고 심층 검토 실행 승인은 상세로 보낸다(`createDeepReview`가 ready 문서 묶음을 요구하므로 한 요청으로 합치면 존재할 수 없는 심층 검토를 만든다). 승계 건이 막다른 카드가 되지 않도록 상세 pane에 `심층 검토 실행 →` 진입점을 두었다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, `design-shell.spec.ts` 6 passed·2 skipped, `pre-specs.spec.ts` 29 passed, 전체 Playwright 394 passed·74 failed·2 skipped. 실패는 단계 A에서 이어진 `visual.spec.ts` 73건 + flake 1건(`common-interactions.spec.ts:337`, 단독 실행 통과)이며 **새 실패는 없다** |
| 정보구조와 사업 추적 · 단계 E | **완료(2026-09-04).** 사이드바를 7항목으로 줄이고 `검토 대기열`을 `사업 추적`으로 대체했다. 예외 작업 경로를 옮긴 뒤 공고 1차 판정을 읽기 전용으로 잠갔다 (design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) 단계 E, ADR-0046) | 커밋을 PLAN §6이 요구한 순서대로 셋으로 나눴다. `e7ed15f`(3-2 예외 작업 경로) → `a21a988`(읽기 전용 전환) → `ab7a53c`(대시보드·Go/No-Go·기준과 운영). 두 커밋 사이에 리뷰 저장 경로가 없던 순간이 없다. **사이드바**는 `오늘의 업무`/`탐색과 추적`/`기준과 운영` 7항목이고 회차 선택기를 갖는 사이드바 항목은 대시보드 하나다(공고 판정 이력은 사이드바 항목이 아니다). **사업 추적**은 분할 화면이 됐고 구역 판정이 `trackingSectionOf` 한 곳에서만 이뤄져 한 사업기회가 구역 넷을 통틀어 한 행으로만 나타난다. **예외 작업**은 실제 저장 경로를 갖는다 — `연결 불확실`은 서버에 이미 있던 `PATCH /opportunities/links/{id}/decision`(진입점이 없어 지금까지 쓸 수 없었다), `검증 실패`는 그 공고의 회차로 `PUT /notices/{pk}/review`에 확인 항목 답변만 실어 보내고, `근거 없음`은 화면이 해소할 수 없다는 사실을 그대로 말한다. **읽기 전용 전환**으로 검토 대기열의 리뷰 초안·localStorage·저장이 사라지고 `ReviewRecord`가 저장된 리뷰를 읽기 전용으로 보여준다. `ReviewBar.tsx`는 삭제했다. 단계 B가 미뤄 둔 `/queue` 1280px 가로 넘침 19.77px도 고쳤다(`.attachment-name`의 ellipsis가 부모의 시각 효과일 뿐 자식 span의 레이아웃 상자는 그대로 넘쳐 있었다). **검증:** 대비 7 passed, `tsc -b`·production build 통과, 전체 Playwright 410 passed·72 failed·2 skipped. 실패 72건은 **전부 팔레트 스냅샷**이며 단계 D까지 함께 실패하던 `/queue` 오버플로 1건과 flake 1건이 사라졌다. **미해결:** 사업기회 추적 이력 읽기 계약과 구역별 집계가 서버에 없어 화면이 그 한계를 표시한다([findings.md](findings.md)) |
| 상세 3종과 심층 검토 · 단계 F | **완료(2026-09-04).** 세 상세 화면을 한 골격으로 맞추고 되돌릴 수 없는 입력 form을 헤더에서 내렸다 (design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) 단계 F) | 커밋 `ec79da7`(상세 3종 골격) → `adae790`(심층 검토 보고서). **헤더에는 액션만** 남고 폼은 본문 열에 있다 — 헤더 저장 버튼이 `form` 속성으로 본문 폼을 submit하므로 전제조건이 한 곳에만 있다. 시안 `OrderPlanDetail`대로 사람 피드백 revision 이력을 레일에서 본문 열로 옮겼다(지금 저장할 값과 직전 revision을 대조해야 한다). 입찰 변경 비교 헤더가 `결정 저장`·`결정 입력으로 이동`·`비교 재계산` 셋을 갖고, 최종 Go/No-Go 폼 바로 위에 저장 조건 셋을, 범주 목록 바로 위에 비교 기준(기준 사전규격·대상 입찰공고·문서 묶음 상태·계산 시각)을 남겼다. 심층 검토 보고서는 상단 카드 4개·결정 카드 요약 표(항목·내용·근거·검증)·Validation 실패 블록(`원문에서 확인`·`새 attempt로 재시도`)·우측 열(보고서 범위·수정본 저장·이력)로 배치했다. 시안의 `참여 준비 상태` 카드는 **이 보고서 계약에 그 축이 없어** 채우지 않고 그 사실을 한 줄로 밝혔다. **검증:** 대비 7 passed, `tsc -b`·production build 통과, 전체 Playwright 420 passed·72 failed·2 skipped. 실패 72건은 전부 팔레트 스냅샷이고 그 밖의 실패는 없다. **미완료:** 완료 게이트의 `시안 기준 캡처`는 v2 기준 이미지가 없어 판정할 수 없다(design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) §0-3·0-4·0-5, [findings.md](findings.md)) |
| 화면 검사 층 분리 · 기준선 교체 | **완료(2026-09-04).** `visual.spec.ts` 한 파일이 픽셀 36 + 가로 넘침 36 + 의미 15를 섞어 담고 있어 픽셀이 깨지면 나머지 51개의 초록이 묻혔다. 세 층으로 갈랐다 — `screen-semantics.spec.ts`(의미, 1440px 한 폭) · `overflow.spec.ts`(구조, 1280·1440px) · `pixel-screens.spec.ts`(픽셀, 게이트 밖). 폭에 의존하지 않는 spec을 한 폭에서만 돌려 실행 건수가 494→260으로 줄었다. 픽셀 기준선은 대표 화면 여덟 장으로 교체했다(144장 39MB → 8장 1.1MB, 승인 기록은 [findings.md](findings.md)) | `npm run test:screens` `4 skipped, 247 passed (2.1m)`, 실패 0. `npm run test:pixel` `9 passed`, 재실행에도 동일 |
| 탐색과 추적 4화면 통일 | **구현 완료, 병합 전(2026-09-08).** 목록 4화면(발주계획·사전규격·사업 추적·최종 Go/No-Go)이 상단바 제목 모드(`h1` + 액션 portal)·공용 필터 바(`WorkspaceFilters`)·같은 프레임 값(목록 38%, 목록 머리 `8px 16px`, 상세 머리 `12px 16px`)을 쓰고, 발주계획에 목록 ↑↓ 이동·Ctrl+Enter 추적 시작·직전 사유 다시 쓰기가 생겼다 (design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨)) | 1단계(셸·공용 필터)는 메인 트리에 있고 2단계는 워크트리 브랜치 `feat/explore-wp-c`·`-wp-d`·`-wp-e`·`-wp-f`에, 교차 검사·문서는 `feat/explore-wp-g`에 있으며 **어느 것도 병합하지 않았다**(검증용 통합 커밋 `c85a495`). **게이트:** 기준선 `npm run test:screens` 464 passed·9 failed·6 skipped → 1단계 뒤 470 passed·9 failed·5 skipped로 기존 실패 9건 그대로다. **WP-G 검증:** `tsc -b` clean·production build 통과·`explore-workspace-consistency.spec.ts`(새 교차 검사)와 `admin-workspace-consistency.spec.ts` 5 passed 0 failed. `--project=pixel`은 7 failed 2 passed이며 달라진 화면은 dashboard·criteria·order-plans-list·order-plan-detail·pre-specs-list·opportunities-list·bid-delta-changed다. **픽셀 기준선은 갱신하지 않았다** — 교체는 승인 기록을 남긴 뒤에만 한다(`docs/standards.md`) |
| 통일 모델 클라이언트 | C-1 공고 판정·사전규격 개요·심층 검토가 `app/core/model_client.py` 하나를 `screening`·`overview`·`deep_review` 용도로 부른다. 용도마다 endpoint·허용 host·자격증명·선언 revision을 갖고 허용 host나 revision이 없으면 호출 전에 fail closed한다([ADR-0050](decisions/0050-unified-openai-compatible-model-client.md)). 이전 로컬 provider 설정 7개는 제거됐고 C-1 모델명이 `qwen3.8-27B`가 됐다 | 단위 테스트 범위. **live vLLM 호출은 이 저장소에서 실행하지 않았다.** C-2 발주계획 어댑터는 별도 transport로 남아 있다 |
| 참조 실행 모드와 품질 표식 | `BIDOPS_REFERENCE_WORKFLOW_MODE`가 결정적 mock과 품질 미측정 실행을 허용하고, 결과에 `quality_status=measured\|unmeasured_reference\|mock_reference\|null` 표식이 붙는다. 개요 attempt는 표식이 필수다 | 단위 테스트 범위. **참조 실행 절차는 아직 실행되지 않았다**(운영 절차의 "사전규격 심층 검토 참조 실행"). 참조 실행 결과는 운영 완료·품질 근거가 아니다 |
| 사전규격 자동 문서 준비 | effective grade가 `우선 검토`인 사전규격의 묶음 초안 생성·자동 확정, 새 확장점 `effective_grade_changed`, `GET /api/pre-specs`의 등급·자동 준비 필드 다섯([ADR-0049](decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)) | 단위 테스트 범위. 목록 쿼리 수가 건수와 무관하게 12(묶음 없음)/14(자동 확정 묶음 있음)로 일정함을 확장 테스트가 고정한다 |
| SW=Y 자동 심층 시작 | `우선 검토`·`SW사업대상=Y`·자동 확정 `ready` 묶음·검증된 개요와 현재 회사 핏 `matched`, 활성 입력·실행/품질 조건을 충족하면 시스템 actor로 심층 검토 생성(`deep_review.auto_create`). 추출형 개요의 `검토 종료` 권고는 차단한다 | 참조 실행용 게이트의 단위·연결 검사 범위. 회사 핏은 기본 비활성이므로 이 상태에서는 자동 생성도 대기한다. 자동 생성 감사를 찾는 경로는 `DEEP_REVIEW_CREATION_ACTIONS`를 사용한다([findings](findings.md)) |
| 사전규격 개요 모델 실행 worker | 통일 client를 `overview` 용도로 묶어 실행하고, 검증 실패는 재호출 없이 `failed`, transport 실패만 1+2회 재시도한다. 개요 lease는 모듈 상수 1,200초이며 합성 analysis worker가 C-2 → 심층 → 회사 핏 → 개요 순서로 하나만 claim한다 | 이번 회사 핏 변경은 fake 모델로 검증했다. 과거 실제 개요 참조 실행과 별개로 이번 작업에서는 live 호출을 하지 않았다 |
| 결정적 문서 segment·요구사항 inventory | 구조 저장 시점에 manifest·segment·inventory 항목을 append-only로 만들고 `GET /api/document-structures/{id}/segments`로 읽는다. 검증에 `requirement_inventory`·`segment_coverage` check 추가([ADR-0051](decisions/0051-deep-review-v2-deterministic-subset.md)) | 단위 테스트 범위. **이 변경 전 구조에는 manifest가 없고 조회가 404다**(사후 재구성 불가). 역할별 모델 분석과 Luna 평가는 보류 |
| 문서 준비·실패 attempt 재시작 화면 | 문서 준비 패널은 사전규격 상세에 연결됨(2026-09-16 확인). 첨부 취득 실패·묶음 failed 재시작은 미구현 | 화면 검증 없음 |
| T-23 사전규격 overview phase 2 기반 | immutable result/event, 제한된 attempt lifecycle service, safe v2 projection 구현됨; 2026-09-11 MVP 재작성으로 대체됨(ADR-0054) | SQLite 46 passed·1 PostgreSQL-only skipped, PostgreSQL 17 집중 9 passed, production build 282 modules |
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
회사 핏 구현 당시 head는 `0020_prespec_company_fit`이고 문서 업무 사전 기준 table은
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
| T-23 사전규격 상세 Playwright | 2026-09-09 축소 게이트 61 passed · 0 failed — 상세 화면 관련 spec만(pre-specs 상세·page-overview·company-fit·screen-semantics 상세·document-preparation, --project=app, PW_PORT 분리). 전체 test:screens·contrast·pixel은 돌리지 않았다(수정 범위만 검증한다는 2026-09-09 지시). | 지원 두 폭(1280×800·1440×900, ADR-0047(git 이력 docs/design/ADR.md, 삭제됨))에서 정본 ID, unknown, 교차 ID fail-closed, 안전 오류를 검증 |
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
