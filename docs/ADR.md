# BidOps 아키텍처 결정 기록

| 항목 | 내용 |
|---|---|
| 문서 상태 | 현재 결정 기준선·통합 색인 |
| 기준일 | 2026-09-21 |
| 범위 | 수집, 선별, 사전규격 검토, 심층 검토, 입찰공고 추적, 운영·보안 |
| 상세 결정 정본 | [`docs/tracking/decisions/`](tracking/decisions/)의 ADR-0001~0038·0042~0045·0049~0051·0053~0054·0056~0068, ADR-0039~0041·0046~0048·0055(구 `docs/design/ADR.md`, git 이력에서 확인) |
| 함께 읽을 문서 | [`PRD.md`](PRD.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`contracts.md`](contracts.md) |

이 문서는 여러 시점에 작성된 결정 기록을 현재 관점에서 읽기 위한 통합 ADR이다. 각 결정의
배경·대안·결과를 이 문서에 복사해 두지 않고 상세 ADR로 연결한다. 이 문서의 요약과 상세 ADR이
충돌하면 상세 ADR의 상태와 이후에 채택된 ADR을 따른다.

## 1. 문서 권위와 결정 읽는 법

결정·요구사항·구현 사실을 다음 순서로 해석한다.

1. 루트 [`AGENTS.md`](../AGENTS.md)와 `CLAUDE.md`의 강제 게이트와 현재 런타임 사실
2. 현재 업무·계약·운영·표준 문서: [`business-rules.md`](business-rules.md),
   [`contracts.md`](contracts.md), [`operations.md`](operations.md),
   [`standards.md`](standards.md) — 모델 전송 정책은 ADR-0050 완화 항목 참조
3. 이 문서가 색인하는 채택 ADR의 상세 내용
4. [`tracking/status.md`](tracking/status.md), [`lifecycle-workstream.md`](tracking/lifecycle-workstream.md)의
   현재 구현·진행 요약
5. [`validation-runs/`](validation-runs/)와 실험 디렉터리의 날짜별 실행 증거

과거 계획·목업·인수인계 문서는 저장소에 보관하지 않는다. 그 안의 SQLite 운영안, 초기 phase 번호,
R-xx/A-xx 작업 지시, 과거 API 경로는 현재 실행 진입점이 아니며, 결정이 바뀐 이유를 확인해야
하면 `대체됨` ADR과 git 이력을 본다.

### 결정 상태

- `채택`: 현재 설계의 근거다. 단, 구현 완료나 운영 승인을 뜻하지 않는다.
- `채택 — 계약만`: wire·DB·상태 경계는 고정했지만 제품 구현 또는 운영 활성화는 별도다.
- `대체됨`: 당시 선택과 결과를 보존하지만 현재 설계에 적용하지 않는다.
- `제안`: 사람의 명시적 결정 전에는 구현 근거로 사용하지 않는다.

다음 ADR이 이전 ADR의 범위를 명시적으로 좁히거나 대체하면, 이전 기록을 삭제·수정하지 않고
새 결정의 효력을 우선한다. 모든 재실행·정정은 기존 결정·산출물·리뷰를 덮어쓰지 않는다.

## 2. 현재 결정의 공통 불변식

### 2.1 사람의 판단 축은 서로 대신하지 않는다

다음 값은 각각 별도의 필드·전이·감사를 가진다.

| 축 | 의미 | 다른 축으로 대체할 수 없는 이유 |
|---|---|---|
| 발주계획 relevance | 조기 탐색 후보인가 | 회사 적합성·자격·참여 결정이 아님 |
| 적합성 등급 | 회사와 사업의 전략·기술 적합성 | 입찰 자격 확인을 대신하지 않음 |
| 참여 준비 상태 | 자격·제약 확인 정도 | 등급이 높아도 미확인일 수 있음 |
| 사전규격 개요 결과 | RFP 앞부분 기반의 저비용 사업내용 판단 | 심층 자격·추적 승인을 대신하지 않음 |
| 추적 상태 | 사람이 사업기회를 계속 볼지 선택 | 최종 입찰 참여 결정이 아님 |
| 심층 `final_opinion` | 특정 리포트에 대한 사람 의견 | 입찰공고 시점 Go/No-Go가 아님 |
| 최종 Go/No-Go | 입찰공고와 변경 조건을 본 사람의 최종 결정 | 모델·추적 상태·개요 결과가 만들 수 없음 |

`unknown`, `null`, 값 없음, 계산 불가, 실패, 중단, 탈락은 서로 다른 상태다. 모델이나
적재기가 이를 0, 빈 문자열, `false`, `not_relevant`, 성공으로 보정하지 않는다.

### 2.2 불변성·근거·감사

- 원문, 정규화 결과, 회차, 관측, 문서 버전·구조, bundle, profile·policy, 모델 binding,
  결과, 리포트, 사람 리뷰와 결정은 생성 후 제자리에서 덮어쓰지 않는다.
- 변경은 새 version·revision·execution·attempt 또는 새 파생 산출물로 표현하고 부모와
  source hash를 남긴다.
- 모델이 만든 사실·숫자·요구사항·판정은 원문 문서나 정규화 원본의 검증 가능한 locator와
  연결한다. 결정적 검증 실패는 사람 검토로 보내며 자동 보정하지 않는다.
- API·로그·감사에는 회사자료 전문, 원문·프롬프트·모델 응답·자격증명·내부 경로·객체 key를
  넣지 않는다. API는 명명된 Pydantic projection과 안정 오류만 반환한다.

### 2.3 파이프라인과 웹의 경계

`skills/bidops-collect`, `skills/bidops-screen`, `skills/bidops-report`는 versioned file
계약과 subprocess로 연결한다. FastAPI가 내부 함수를 가져오거나 웹에 업무 규칙을 복제하지
않는다. 생성자는 현재 계약을 엄격하게 지키고, 과거 산출물 importer는 핵심 식별자·판정을
추정하지 않는 범위에서만 경고를 남기며 관대하게 읽는다.

## 3. 채택 결정 색인

아래 표는 2026-09-05 현재의 결정 목록이다. 상세 배경·대안·결과는 각 링크가 정본이다.

| ADR | 결정 | 상태 | 현재 효력 |
|---|---|---|---|
| [0001](tracking/decisions/0001-artifact-boundary.md) | 기존 스크립트를 기준선으로 유지하고 산출물로 연결 | 채택 | 웹과 파이프라인의 기본 경계 |
| [0002](tracking/decisions/0002-sqlite-wal.md) | 운영 저장소로 SQLite WAL 사용 | 대체됨 | 운영은 ADR-0020의 PostgreSQL·MinIO를 사용 |
| [0003](tracking/decisions/0003-strict-producer-tolerant-importer.md) | 생성자는 엄격하게, 과거 산출물 적재기는 경고 허용 | 채택 | 생산·적재의 오류 처리 기준 |
| [0004](tracking/decisions/0004-admin-visual-density.md) | 관리자 화면의 여유형 RootLab 시각 체계 | 채택 | 토큰·상태 라벨·접근성 기준 |
| [0005](tracking/decisions/0005-hybrid-attachment-acquisition.md) | 첨부 확보를 기관 링크와 수동 등록의 혼합으로 구성 | 채택 | 기관 자동 요청 대신 링크+수동 등록 |
| [0006](tracking/decisions/0006-db-review-canonical.md) | 리뷰 정본은 DB, YAML은 호환 내보내기 | 채택 | PostgreSQL이 리뷰 정본 |
| [0007](tracking/decisions/0007-immutable-runs.md) | 회차를 불변 스냅샷으로 보존 | 채택 | 재실행은 새 ID |
| [0008](tracking/decisions/0008-versioned-user-policy.md) | 정책을 사용자 편집 가능한 불변 버전으로 관리 | 채택 | 실행 시작 시 policy pinning |
| [0009](tracking/decisions/0009-name-attribution-intranet.md) | 초기 작성자 식별은 이름 입력, 파일별 권한 분리는 생략 | 채택 | 현재 사내망·claimed name 경계; 인증 아님 |
| [0010](tracking/decisions/0010-hwpx-canonical-input.md) | HWP는 헤드리스 변환한 HWPX를 분석 정본으로 사용 | 채택 | HWP 원본 보존, HWPX 구조 분석 |
| [0011](tracking/decisions/0011-local-qwen-openai-fallback.md) | Qwen 우선, OpenAI는 검증 실패 후 건별 승인 보조 경로 | 대체됨 | 현재 hosted 자동 fallback 금지 |
| [0012](tracking/decisions/0012-human-governed-feedback.md) | 피드백은 변경 제안을 만들고 사람이 새 정책을 승인 | 채택 | 자동 학습·자동 정책 변경 금지 |
| [0013](tracking/decisions/0013-screening-orchestrator-boundary.md) | 판정 단계만 애플리케이션 오케스트레이터로 전환 | 채택 | 수집·보고는 결정적 스크립트 유지 |
| [0014](tracking/decisions/0014-in-process-scheduler.md) | 정기 실행은 웹 프로세스 내부 스케줄러로 구동 | 채택 | 설계는 채택, 기본 비활성 |
| [0015](tracking/decisions/0015-versioned-screening-policy.md) | 판정 기준은 불변 정책 버전을 정본으로 관리 | 채택 | 정책·프롬프트·검증 기준 pinning |
| [0016](tracking/decisions/0016-daily-run-rejudgment.md) | 일간 회차와 제한된 재판정 | 채택 | 변화가 확인된 경우에만 새 판정 |
| [0017](tracking/decisions/0017-human-enabled-quality-gate.md) | 품질 게이트 통과 후 담당자가 상시 운영을 활성화 | 채택 | 코드 완성과 운영 활성화 분리 |
| [0018](tracking/decisions/0018-partial-artifact-on-screening-failure.md) | 판정 실패 건은 제외하고 회차를 부분 산출물로 표시 | 채택 | 성공·부분 성공·실패 분리 |
| [0019](tracking/decisions/0019-screening-input-contract.md) | 판정 대상은 새 입력 계약으로 정의하고 병합기 수용 버전만 확장 | 채택 | 공고 판정 계약과 의미 혼합 금지 |
| [0020](tracking/decisions/0020-postgresql-minio-canonical.md) | PostgreSQL과 versioned MinIO를 운영 정본으로 사용 | 채택 | SQLite는 격리 테스트·일회성 이관만 |
| [0021](tracking/decisions/0021-filter-experiment-before-implementation.md) | 발주계획 선별은 비교 실험 후 구현 | 채택 | 동일 모집단·사람 정답·전체 보존 |
| [0022](tracking/decisions/0022-plan-prespec-centered-lifecycle.md) | 발주계획과 사전규격을 중심으로 기회 생애주기를 구성 | 채택 | 독립 수집과 단계별 사람 gate |
| [0023](tracking/decisions/0023-company-profile-minimal-projection.md) | 회사 프로필 조회는 승인된 최소 projection만 제공 | 채택 | 원문·경로·raw 제외 |
| [0024](tracking/decisions/0024-prespec-collect-all-flag-sw.md) | 사전규격은 전량 수집하고 SW사업대상 여부는 표시 값으로 관리 | 채택 | 업무구분만 수집 범위, SW flag는 필터·표시 |
| [0025](tracking/decisions/0025-prespec-link-search-unconfirmed-state.md) | 사전규격 후보 연결은 전략을 표시하고 못 찾은 건은 미확인으로 유지 | 채택 | 검색 미확인을 부재로 표시하지 않음 |
| [0026](tracking/decisions/0026-cumulative-external-identity-schema.md) | 공고는 외부 식별자로 누적하고 회차는 관측 이력으로 강등 | 채택 | 누적 현재값+회차 observation |
| [0027](tracking/decisions/0027-order-plan-requery-window.md) | 발주계획은 최근 21일 구간을 매일 재조회 | 폐기(0061 대체) | 21일 근거가 종단 관측에서 재현되지 않았고 일 단위 수집으로 재관측이 필요 없어짐; 발주계획→입찰공고 연결은 입찰공고 측 `orderPlanUntyNo`만 |
| [0028](tracking/decisions/0028-bid-first-opportunity-registration.md) | 입찰공고에서 처음 등장한 사업도 기회로 등록 | 채택 | 첫 단계가 bid인 기회 허용 |
| [0029](tracking/decisions/0029-screening-mock-provider.md) | 1차 분류는 결정적 mock 제공자로 소비 계층을 먼저 구현 | 채택 | mock은 reference-only |
| [0030](tracking/decisions/0030-opportunity-tracking-state.md) | 추적 상태는 모든 사업기회가 갖고 사람 선택과 시스템 신호를 분리 | 채택 | `미선택·계속 추적·보류·종료` |
| [0031](tracking/decisions/0031-prespec-overview-review-stage.md) | 사전규격 개요 검토를 1차 분류와 심층 검토 사이 독립 단계로 둠 | 채택 | RFP 앞부분의 저비용 판단; 심층 진입의 "사람 승인" 문장은 [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)가 좁힘 |
| [0032](tracking/decisions/0032-prespec-overview-cutting-rule.md) | 사전규격 개요 검토 앞부분은 문서 구조에 따라 자르고 모호하면 사람 검토로 보냄 | 채택 | 고정 block 수 fallback 금지 |
| [0033](tracking/decisions/0033-prespec-overview-review-runtime-contract.md) | 개요 검토 절단 snapshot과 모델 attempt를 분리하고 사설 binding 없이는 완료하지 않음 | 채택 | `awaiting_model`·mock 비배포; 진입의 "사람 승인"은 [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md), 참조 실행 표식은 [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md); attempt/target 런타임은 2026-09-11 폐기 — MVP 개요 재작성으로 대체, 상세는 git 이력 71b9954 |
| [0034](tracking/decisions/0034-bid-delta-final-decision.md) | 입찰 delta와 최종 사람 결정을 불변 비교와 append-only 기록으로 분리 | 채택 — 계약/구현 경계 | worker·운영 활성화는 별도 |
| [0035](tracking/decisions/0035-prespec-overview-attempt-result-lifecycle.md) | 개요 모델 attempt의 상태 전이와 검증 결과를 분리 | 채택 | result/event와 안전한 v2 projection |
| [0036](tracking/decisions/0036-judgment-model-lineage-source.md) | 판정의 모델 계보는 revision→execution 경로를 정본으로 함 | 채택 | legacy 계보는 `unknown` |
| [0037](tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md) | C-2 발주계획 선별은 BM25 Top 300 뒤 Qwen으로 확정 | 채택 | 현재 선택; 운영 활성화와 별개 |
| [0038](tracking/decisions/0038-order-plan-c2-phase0-contracts.md) | C-2 Phase 0 전용 파일·REST·DB 계약과 상태 경계 고정 | 채택 — 계약만 | 제품 adapter·DB·실행은 후속 phase; binding `status` 허용값과 파일 상태성 필드의 게이트 제외는 [0060](tracking/decisions/0060-c2-policy-db-row-authority.md)이 개정 |
| 0039(git 이력 docs/design/ADR.md, 삭제됨) | Astryx 디자인 시스템 채택과 승인 범위 | 채택 | 고정 빌드 산출물; 테마는 0048이 개정; 화면 이행은 후속 단계 |
| 0040(git 이력 docs/design/ADR.md, 삭제됨) | 레이아웃 소유권과 화면 단위 이행 | 채택 | 레이아웃은 프로젝트 소유; 화면별 이행 |
| 0041(git 이력 docs/design/ADR.md, 삭제됨) | 정보구조와 판정 동선 | 채택 | 회차·누적 축과 같은 화면 판정 입력을 유지; 결정 1·2·4는 0046가 개정 |
| [0042](tracking/decisions/0042-c2-model-revision-declared-at-deployment.md) | C-2 모델 revision은 배포 시점 선언으로 1회 대조 | 채택 | vLLM이 revision을 노출하지 않음; 응답 값은 있으면 대조; [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)이 판정·개요·심층으로 확장 |
| [0043](tracking/decisions/0043-screening-deep-review-module-boundary.md) | 선별과 심층 검토를 한 배포 단위 안의 독립 모듈로 분리 | 채택 | 구조 경계만 고정; 배포 단위·운영 활성화는 불변; [0045](tracking/decisions/0045-backend-module-layout.md)가 네 모듈로 보강 |
| [0044](tracking/decisions/0044-c2-stage2-matches-the-measured-method.md) | C-2 stage 2를 측정된 방법과 일치시킴 | 채택 | item_id payload·strict schema·승인 generation config; binding v2 |
| [0045](tracking/decisions/0045-backend-module-layout.md) | 백엔드를 core·lifecycle·screening·deep_review 네 모듈과 조립 계층으로 배치 | 채택 | ADR-0043 보강; lifecycle 확장점·`BIDOPS_MODULES`·경계 강제 테스트; REST 표면 불변. core의 모델 transport 이름은 [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)이 `model_client`로, 확장점은 [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)가 다섯째로 갱신 |
| 0046(git 이력 docs/design/ADR.md, 삭제됨) | 사업 추적 중심 정보구조와 추적 결정의 위치 | 채택 | 사이드바 16→7, 검토 대기열→사업 추적; 결정 1은 발주계획의 추적 결정 |
| 0047(git 이력 docs/design/ADR.md, 삭제됨) | 데스크톱·노트북 전용 지원 폭 | 채택 | 1280~1920px만 지원; 검증 viewport 두 폭 |
| 0048(git 이력 docs/design/ADR.md, 삭제됨) | 무드보드 기반 색 팔레트와 테마 소유권 | 채택 · 2026-10-16 개정 | 화면은 토큰만 읽고 `--color-*`를 재정의하지 않음(유지). 2026-10-16 ADR-0073 개정으로 라이트 값을 RL 시안 v26 팔레트(흰 바탕·회색 사이드바 `#F8F8F9`·강조 `#1D7B4E`·시안 의미색)로 교체하고 무드보드 파생 남색 사이드바·회녹 canvas·`#587A2B`를 폐기함. 사이드바 면 등은 `brand.css` `--bo-*` 프로젝트 토큰 |
| [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md) | 사전규격 문서 준비를 등급으로 자동화하고 `SW사업대상=Y`는 심층 검토까지 자동 시작 | 채택 | FR-DOC-07·ADR-0031·0033의 "사람 승인"을 이 규칙으로 대체; 고비용 전량 분석의 승인 경계는 유지 |
| [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md) | 모델 호출을 하나의 OpenAI 호환 client와 용도별 설정으로 통일 | 채택 | C-1·개요·심층이 `core/model_client`를 씀; 용도별 endpoint·선언 revision·참조 실행 표식; 이전 로컬 provider 경로 제거; MVP 기간에는 §5 "ADR-0050 모델 호출 게이트의 MVP 기간 완화"로 일부 완화됨 |
| [0051](tracking/decisions/0051-deep-review-v2-deterministic-subset.md) | deep-review-v2의 결정적 부분만 채택 | 채택 — 부분 채택 | segment manifest·요구사항 inventory·검증 연결만 구현. 역할별 모델 분석과 Luna 평가는 보류 |
| [0053](tracking/decisions/0053-decision-workload-read-contracts.md) | 결정 대기 조회와 모듈 소유 집계 계약 | 채택 | 신규 GET 세 개(`/api/workload`·기회별 심층 검토 목록·입찰 결정 큐), 업무 집계는 모듈 제공자 소유, DB migration 없음 |
| [0054](tracking/decisions/0054-prespec-overview-mvp-rewrite.md) | 사전규격 개요 실행 스택 철거·MVP 재작성 | 채택 | v3·legacy v4·v5(activation·call ledger·verification) 폐기, `prespec_overview_run`(0026) 단일 테이블과 `bidops.prespec-overview.v1`로 재작성; 첨부·준비·변환·snapshot·결정적 검증 함수는 유지 |
| 0055(git 이력 docs/design/ADR.md, 삭제됨) | 사전규격 담당자 브리핑 우선 배치 | 채택 | 행 등급 글자·업무 필터, 상세 판정 사유·본공고·첨부, 범위 확정 알림·문서 준비 조건부 토글·실행 정보 후순위. 백엔드 계약 무변경 |
| [0056](tracking/decisions/0056-company-fit-in-overview-run.md) | 회사 핏을 개요 run 2단계 호출로 통합 | 폐기(0057 대체) | 별도 큐·runner·플래그 3개·worker 슬롯을 폐지하고 개요 run 검증 통과 직후 1회 호출로 흡수; 후보 0건 문제 해소 |
| [0057](tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md) | 개요 검토를 앞부분 요약 3섹션으로 좁히고 회사 적합성은 심층 검토 1단계로 | 부분 채택(결정 4 보류) | 목차 우선 범위 선택, important_conditions·reviewer_analysis·unknowns 제거, 자동 심층 게이트에서 회사 핏 제거, 검증 완화 4항목 |
| [0058](tracking/decisions/0058-final-decision-basis-separated-from-comparison.md) | 최종 Go/No-Go 결정 근거를 모델 문서 비교와 분리 | 채택 | 근거 `comparison`·`notice_conditions` 중 하나(migration 0028), 공고 조건 요약·결정 endpoint, 근거별 현재성 단일 규칙; [0034](tracking/decisions/0034-bid-delta-final-decision.md) §5를 비교 근거에 한정, 비교 worker는 보류 |
| [0059](tracking/decisions/0059-full-collection-selective-ingest-and-index-search.md) | 발주계획·사전규격·입찰공고는 전량 수집하고 추적·SW 관련 레코드만 적재 | 채택 | 입찰공고 선별 사유 3종(추적 참조·SW 사전규격 참조·1468 경쟁입찰), 1468은 수집 필터가 아니라 표시로만 사용(실측: SW 사전규격 계보 입찰공고의 29%가 1468 밖), 제외 레코드는 수집 색인(migration 0027)에 보존; 결정 1의 수집 창(21일 재조회·3일 창)은 [0061](tracking/decisions/0061-daily-collection-window.md)이 개정 |
| [0060](tracking/decisions/0060-c2-policy-db-row-authority.md) | C-2 policy의 활성 정본은 DB 행이고 파일의 상태성 필드는 발행 시점 스냅샷 | 채택 — 계약만 | blocker는 런타임 계산, 임계값 정본은 DB 게이트 행(migration 0029); binding `status` 허용값 확대와 `blocked`∧`execution_allowed` 거부([0038](tracking/decisions/0038-order-plan-c2-phase0-contracts.md) 부분 개정); 전송 승인 단위는 binding 튜플; 일일 스크립트 actor는 cron 설치자의 옵트인(`X-BidOps-Trigger`); 게이트는 후보 상태의 측정 전용 실행(`product_rerun`만 활성화를 연다); 일일 자동 실행은 환경 cap + 버전에 묶인 DB 스위치 |
| [0061](tracking/decisions/0061-daily-collection-window.md) | 발주계획은 전일 하루, 공고는 기준일 포함 4일 창으로 수집 | 채택 | [0027](tracking/decisions/0027-order-plan-requery-window.md) 폐기·[0059](tracking/decisions/0059-full-collection-selective-ingest-and-index-search.md) 결정 1 개정; 한 발주계획 = 한 회차 = 한 운영 실행; 공고 4일 창은 사전규격 공개 지연(`rgstDt` 조회·`rcptDt` 공개, 늦은 색인 측정 4일 창 누락 0) 때문; 트랙 분리·적재 순서 고정 해제(테스트로 확인할 추론); 대가는 추적 중 발주계획 변경 미관측, 공고 회차 창과 scheduler 1일 창의 불일치(C-1 자동화 선행조건) |
| [0062](tracking/decisions/0062-explore-workspace-structure-unification.md) | 발주계획·사전규격 탐색 화면의 구조를 하나로 맞춤 | 채택 | 사전규격 기준, 페이저 위치·로딩 골격 유지·sticky 상세 머리 셋은 발주계획 방식을 공용으로; 발주기관 강조 블록 공용화; 수집 회차 선택을 필터 아래 줄로; 목록 폭 리사이저 제거(기능 손실 승인); 데이터 계층 불변; 재설계 C spec §2.4를 넘는 결정; UI 변경은 시안 승인 뒤 구현. `수집 회차 선택` 행은 [0065](tracking/decisions/0066-practitioner-ops-information-boundary.md)가 개정(공용 `SourceRunFilter`로 통일해 `상세 필터` 안으로, 옵션에서 run_id 제외, `/runs` `이 회차 보기` 링크 진입, 실행 상태 표시는 최근 실행에 문제가 있을 때만) |
| [0063](tracking/decisions/0063-order-plan-bulk-tracking-end.md) | 발주계획 일괄 추적 종료를 연다 | 채택 | 숨김 기준은 추적 종료로 통일(새 "확인함" 필드 없음); `bulk-end` 신설·`bulk-start` v1 불변·`preview` 공유; 미선택 owner만, 소유 사업기회 없으면 만들지 않음; 한 요청 200건(PoC 값); 일괄 보류는 계속 비목표; migration 없음 |
| [0065](tracking/decisions/0065-prespec-overview-preliminary-assessment.md) | 사전규격 개요와 예비 적합성 판단을 한 실행에서 생성 | 채택 — 제품 구현, 운영 비활성 | 정상 1회·위험 시 의미검증 1회·형식 재시도 포함 최대 3회; 서버 등급 계산과 보류; `display_assessment`는 사람 정정 우선; 기존 effective grade·자동화 검증 경계 유지; migration 0031과 v8 정책은 품질 비교·별도 승인 전 활성화하지 않음 |
| [0064](tracking/decisions/0064-prespec-actionable-deadline-scope.md) | 사전규격 검토할 항목의 기본 시야를 마감 구간으로 나눈다 | 채택 | 마감 경과는 제외·소멸하지 않고 기본 시야만 `마감 전+미확인`으로 한정, `마감 경과`는 건수와 함께 1클릭 전환; 마감 미확인은 항상 기본 구간(unknown 보존); 새 인자 `deadline_scope`와 `deadline_scope_counts`, 기존 `deadline_status`는 불변; 구간은 actionable 술어 한 곳에만(검토 제외 가드가 먼저); migration 없음. 결정 7의 도구 줄 순서는 [0065](tracking/decisions/0066-practitioner-ops-information-boundary.md)가 개정(`수집 회차` 칸이 빠져 `상세 필터 토글 → 검색 → 추가 조회 조건`, ADR-0066 구현 시 적용) |
| [0066](tracking/decisions/0066-practitioner-ops-information-boundary.md) | 실무 화면과 운영 화면의 정보 경계를 처분 규칙으로 정한다 | 채택 | 문구·값을 삭제/조건부/이동/한글화/유지 5종으로 하나씩 처분; 식별자·해시는 줄이지 않되 운영 화면·접힌 기술 정보로 옮길 수 있음(`glossary.ts:14` 개정); 모르는 코드는 그대로 통과; 뜻이 다른 빈 값(미제공·미확인·계산 불가·0)은 합치지 않음; 지우면 안 되는 경고 7+4종; 운영 수신처(`/runs`의 `발주계획 선별` 탭)를 먼저 만들고 나서 실무 화면에서 뺌; 대시보드는 실무자 화면(회차 선택 없이 완결); [0062](tracking/decisions/0062-explore-workspace-structure-unification.md)·[0064](tracking/decisions/0064-prespec-actionable-deadline-scope.md) 결정 7·`0918_daily-operation/spec.md` §7 '행 표시' 개정; migration 없음 |
| [0067](tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md) | 실무자 대시보드의 누적 업무 키와 패널 계약 | 채택 | 패널마다 건수 키 하나와 목록 호출 하나를 짝지음(건수 = 그 목록의 `total`, 화면이 다시 세지 않음); 새 endpoint 없이 query 인자 셋(`/api/opportunities`·`/api/pre-specs`의 `deadline_within_days`, `/api/order-plans`의 `first_observed_from`)과 정렬 값 하나(`sort=deadline`); `deadline_within_days`는 추적 대상(`계속 추적`·`보류`)을 함께 좁힘(`hold_review` 선례); 서버는 대표 마감을 고르지 않고 링크 단위 판정 + 사업 반환; `사람 확인 필요`의 두 출처를 합치지 않고 합계 키는 하나라도 null이면 null; 창 상한은 KST 일자로 끊음; `WorkloadKey` 다섯 → 열(세는 키 넷과 합계 하나를 더함); migration·새 저장 상태 없음; [0053](tracking/decisions/0053-decision-workload-read-contracts.md) 확장 |
| [0068](tracking/decisions/0068-same-state-merge-and-tracking-reset.md) | 병합 막힘의 출구 두 갈래 — 같은 상태끼리 병합, 화면에 `미선택으로 되돌리기` | 채택 | `\|H\|≥2`여도 H의 추적 상태가 전부 같고 재검토 신호가 없으면 병합(사람 수락·자동 병합 공통); 유지 쪽은 H 중 가장 오래된 것(`created_at`, 동률이면 `id`)이고 그 상태·사유·선택자·시각은 불변; 병합된 결정은 행에 그대로 남고 사람 병합 감사에 `merged_human_states[]`로도 적음; 신호가 있으면 상태가 같아도 거부; 409 details에 `recheck_signal_at` 추가(추가형); 화면은 막힘 안내와 추적 결정 카드에 `미선택으로 되돌리기`(기존 PATCH, 사유·담당자 필수)를 두고 수락을 자동 재시도하지 않음; 추적 상태 드롭다운은 여전히 `미선택`을 고를 수 없음; migration 없음; [0028](tracking/decisions/0028-bid-first-opportunity-registration.md)·`business-rules.md` 병합 규칙·`0917_opportunity-tracking/spec.md` §3.2·§3.3 개정 |

## 4. 주제별 결정 요약

### 4.1 원천 수집·식별자·생애주기

발주계획, 사전규격, 입찰공고는 매일 독립적으로 관측한다. `order_plan`과 `notice`는 외부
식별자별 누적 현재값이고 `*_observation`은 회차별 원문 snapshot이다. 발주계획은
`orderPlanUntyNo`, 공고는 `notice_key`를 identity로 사용한다. 공식 연결이 없는 사전규격은
사업명 검색 후보를 만들 수 있지만 사람 확인 전까지 확정 관계가 아니다.

- 사전규격은 일반용역·기술용역 전체를 수집한다. `swBizObjYn`은 원문 그대로 저장하고
  표시·필터에만 사용한다.
- `검색 미확인`은 “사전규격 없음”이 아니다. 마지막 검색 시각과 시도한 전략을 보존한다.
- 공식 통합번호가 없는 관계는 candidate link로 둔다. authoritative ownership은 공식 확정
  또는 사람이 수락한 후보만 갖는다.
- 발주공고에서 처음 발견한 사업도 새 opportunity로 등록한다. 종료한 기회를 삭제하거나
  유사 제목을 같은 사업으로 자동 병합하지 않는다.
- 발주계획은 전일(KST) 하루 창, 공고(사전규격·입찰공고)는 기준일 포함 4일 창 `[기준일−3일, 기준일]`로
  수집한다(ADR-0061). 공고 겹침은 사전규격이 등록일로 조회되지만 접수일부터 공개돼 1~3일 늦게 보이는 건 때문이다.
  발주계획 21일 재조회(ADR-0027)는 폐기했다 — 21일 근거가 종단 관측에서 재현되지 않았고, 겹치지 않는 세 회차 사이
  통합번호 재등장이 0건이었다. 발주계획 → 입찰공고 연결은 입찰공고 측 `orderPlanUntyNo`로만 확정하며,
  추적 중 발주계획의 변경은 관측하지 않는다(후속 과제). 공고 회차 창(4일)이 scheduler 일일 예약 창(1일)과
  달라 C-1 자동화 때 겹친 공고의 중복 판정을 먼저 풀어야 한다.

근거: ADR-0022, ADR-0024~0028, ADR-0059·0061 및 [`20260828-lifecycle-linkage-survey.md`](validation-runs/20260828-lifecycle-linkage-survey.md).

### 4.2 적합성·판정·피드백

공고의 다섯 관점 판정은 `screening.v2/v3`와 별도 execution 계보를 갖는다. 관점마다 고유
근거가 있어야 하며 회사 프로필의 `unknown`을 외부 상식이나 모델 추론으로 확정하지 않는다.
리뷰는 DB가 정본이고 YAML은 호환 입출력이다. 판정 계보는
`JudgmentRevision → ScreeningExecution`을 따른다.

품질 피드백은 자동으로 프롬프트·가중치·정책을 바꾸지 않는다. 사람 gold와 결정 변경 제안이
있어야 새 policy version을 만들고, quality gate를 통과한 뒤 운영자가 명시적으로 활성화한다.

### 4.3 첨부·문서·심층 검토

첨부는 나라장터 제공분과 기관 포털 수동 등록분을 구분한다. 모든 bytes는 quarantine에
먼저 저장하고 확장자·MIME/magic·구조·ClamAV·SHA-256 검증을 통과해야 source object가 된다.
HWP 원본은 보존하지만 분석에는 검증된 HWPX 변환 구조를 사용한다. 문서 버전과 구조는
bundle confirm 시점에 pinning한다.

개요 검토는 RFP 앞부분의 결정적 cut snapshot과 모델 attempt를 분리한다. 구조가 모호하면
`needs_human_review`, 승인 모델 binding이 없으면 `awaiting_model`이다. 심층 검토는
`requirements_and_evaluation` → `delivery_risk_economics` → `synthesis_and_validation`의
세 stage로 제한된 slice를 분석하며, claim·숫자·요구사항은 evidence locator 검증 뒤에만
report가 된다.

### 4.4 입찰 delta와 사람 최종 결정

사전규격과 입찰공고의 비교는 정확한 양쪽 document bundle·version·structure·hash fence를
요청으로 받아 저장한다. 서버가 `latest`를 추정하지 않는다. 7개 material 범주와
`changed|unchanged|unknown|failed` 상태를 사용하며, 계산 실패·근거 부족을 변경 없음으로
축약하지 않는다.

최종 입찰 결정은 `go|no_go`만 갖는 사람의 append-only 기록이다. `추적 상태`, 개요·심층
검토 결과, delta 결과가 자동으로 final decision을 만들거나 갱신하지 않는다. 새 authoritative
공고·정정·ready comparison이 생기면 과거 결정 row는 보존하고 currentness만 `stale` 또는
`unknown`으로 투영한다. 상세 wire·DB 계약은 [`bid-delta-contract-spec.md`](bid-delta-contract-spec.md)다.

### 4.5 모델·외부 전송·운영

- 승인된 사설 OpenAI 호환 vLLM만 용도별 binding으로 사용한다. C-1 공고 판정·사전규격 개요
  검토·심층 검토는 `app/core/model_client.py` 하나를 쓰고 용도(`screening`·`overview`·
  `deep_review`)마다 자기 endpoint·자격증명·선언 revision을 가진다([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)).
  허용 host 목록에 없는 host나 64자 hex가 아닌 선언 revision이면 그 용도는 호출 전에 fail
  closed한다. 두 값이 **비어 있는** 경우는 MVP 기간 동안 통과시킨다(§5의 완화 항목).
- hosted OpenAI·Codex로 자동 fallback하지 않는다. 외부 실험도 공개 발주계획 metadata와
  승인된 최소 회사 역량 projection만, payload preview·건별 승인을 거쳐 전송한다.
- 실행 입력에는 source run, policy, profile, prompt, model, generation config와 digest를
  고정한다. 실행마다 정확한 모델명·revision·digest를 기록한다.
- 활성 worker는 FIFO·slot 1·concurrency 1이다. lease fence가 바뀐 stale worker는 결과를
  commit할 수 없다.
- 앱 startup은 migration, seed, policy activation, 수집, 모델 호출을 하지 않는다. scheduler와
  always-on은 기본 비활성이다.

### 4.6 저장·권한·복구·화면

운영 정본은 PostgreSQL 17 `bidops` schema와 versioned MinIO다. PostgreSQL은 상태·관계·해시·
감사·권한 경계를, MinIO는 원문·구조·격리본·암호화 모델 응답을 담당한다. DB role은 migration,
app, worker, read-only backup으로 분리한다. 문서 worker는 `network_mode: none`이며 scratch만
사용한다.

현재 인증·역할 권한은 없고 사내망이 접근 경계다. `X-BidOps-Actor-Name`은 claimed name을
감사에 남기는 표식이지 인증·권한 부여가 아니다. 프론트엔드는 API만 사용하며 상태는 색이
아닌 문자·설명과 함께 표시한다. `계산 불가`를 0으로 표시하지 않는다.

## 5. 충돌·대체 결정의 해석

### SQLite 운영안과 PostgreSQL 운영안

ADR-0002와 초기 계획 문서의 SQLite WAL은 초기 단일 사용자 가정에 대한 역사 기록이다.
심층 검토의 다중 worker lease, 객체 version, 중앙 감사·복구 요구가 추가되면서 ADR-0020이
운영 정본을 PostgreSQL 17과 versioned MinIO로 대체했다. SQLite는 격리 테스트와 일회성 이관
입력에만 남긴다.

### OpenAI 보조 fallback과 현재 모델 경계

ADR-0011의 당시 Qwen 우선·OpenAI 보조안은 대체되었다. 현재는 오류가 외부 전송 동의가
아니며, 승인된 local/private binding이 없으면 `awaiting_model` 또는 안전한 실패로 닫는다.

### ADR-0050 모델 호출 게이트의 MVP 기간 완화(2026-09-11)

결정: 실사용 검증(MVP) 기간 동안 모델 호출 경로의 "값 없음" 게이트를 뺀다.
(1) 허용 host 목록이 비면 host 제한 없이 통과한다. (2) 선언 revision이 비면 통과하고
`ModelEndpoint`에 빈 값으로 기록한다. (3) base URL은 http·https 둘 다 받고 host는 임의
호스트명·IP를, 포트는 scheme 기본값을 허용한다. (4) 선언 revision이 없으면 서버가 보고한
revision과 대조하지 않고 identity 결과에 기록만 한다. (5) 서버가 `max_model_len`을 내지
않으면 `context_unverified` 표식만 세우고 문맥 초과 판정을 하지 않는다.

근거: 대상 자료가 공개 발주·사전규격 자료이고, 지금 필요한 것은 배포 증언 절차보다 실사용
검증이다. 값 없음으로 전 용도가 멈추면 검증 자체가 시작되지 않는다.

결과: 값이 주어지면 기존 검사는 그대로 강제한다 — 허용 host 목록에 없는 host, 64자가 아닌
선언 revision, `/v1`이 아닌 경로, userinfo·query·fragment는 여전히 호출 전에 실패한다.
`model_not_served`, 4 MiB 응답 상한, identity backoff, sanitize, 300초 timeout, SDK retries 0은
바뀌지 않는다. 완화한 게이트의 복원 시점은 MVP 종료 후 별도 결정으로 정한다. ADR-0050 본문은
그대로 유지하며 이 항목이 그 일부를 완화한다.

### ADR-0021 실험 arm과 ADR-0037 C-2 선택

ADR-0021은 “운영 제품 전에 동일 모집단과 사람 정답으로 비교한다”는 원칙을 유지한다. 그
안의 2026-08-31 arm 교체(BM25·한국어 dense·RRF)는 실험 설계의 중간 결정이다. 이후 별도
625건 C-2 비교에서 사람 결정으로 `BM25 Top 300 + Qwen`을 채택한 ADR-0037이 현재 C-2
제품 방식의 직접 근거다. 따라서 ADR-0021의 실험 arm과 ADR-0037의 제품 방식을 같은 단계의
활성 정책으로 읽지 않는다.

## 6. 현재 실행·승인 게이트

아키텍처 결정은 대부분 닫혔지만, 다음은 “결정 대기”가 아니라 구현·운영 승인 게이트다.

| 게이트 | 현재 상태 | 성공 조건 |
|---|---|---|
| C-2 Phase 0 | 계약 고정, `valid_but_blocked` | 제품 adapter·DB·API·worker 구현 후 별도 승인 |
| C-2 품질 gold | 실험별 corpus가 다름 | C-2 625건 manifest의 사람 adjudication·감사 표본·threshold 확정 |
| C-2 외부 transport | `execution_allowed=false` | binding 튜플(policy·binding·model digest·allowlist) 단위 private vLLM 전송 승인([0060](tracking/decisions/0060-c2-policy-db-row-authority.md)), payload·binding digest 일치 |
| 개요 검토 model worker | v7 운영 기준선 유지. v8 예비 판단 제품 구현·격리 검증 완료([0065](tracking/decisions/0065-prespec-overview-preliminary-assessment.md)); migration 0031·배포·정책 활성화 전 | 고정 원문과 사람 gold로 현행/v8 품질 비교, migration·동일 image/mount·백업/rollback 확인, 단계별 운영 승인. 참조·mock·미측정 결과는 활성화 근거가 아니다 |
| 입찰 delta | schema·REST·화면 계약과 migration 존재, 계산 worker 미완료 | exact pair 기반 계산·근거 검증·Go/No-Go 연속 E2E |
| 심층 품질 | Mock E2E, 단일 live 기록, 참조 실행 모드 결과는 모두 품질 승인이 아님 | immutable model artifact, 대표 HWP/PDF, 사람 gold로 gate 측정 |
| deep-review-v2 역할별 분석 | 결정적 segment·요구사항 inventory만 구현([ADR-0051](tracking/decisions/0051-deep-review-v2-deterministic-subset.md)) | 외부 전송 1회성 예외 승인과 역할별 출력 계약 확정 |
| 운영 복구 | script와 격리 검증 존재 | 실제 secret·MinIO 권한·egress·backup/restore 훈련 |
| 접근 제어 | 사내망·claimed name만 사용 | 외부 노출 전 SSO subject·역할·권한 회수 설계 |
| pipeline renderer | `screening.v3` adapter 필요 | v2/v3·partial/failure·provenance 결정성 회귀 |
| audit 완전성 | 일부 legacy mutation은 구현 격차 | 모든 mutation의 actor·audit transaction 편입 |

주의할 점은 실험 corpus를 섞지 않는 것이다. 997건 비교 자료에는 별도의 사람 gold 기록이
있지만, C-2 Phase 0 binding이 참조하는 625건 운영 준비 corpus는 `22 human / 603 draft /
87 remaining` 상태로 기록되어 있다. 어느 쪽도 다른 쪽의 승인 상태를 자동으로 대체하지 않는다.

## 7. 새 결정 추가 규칙

새로운 상태·필드·외부 전송·DB 관계·모델 binding·운영 자동화를 추가할 때는 다음을 함께
기록한다.

1. 현재 계약과 영향받는 사용자·worker·저장소를 명시한다.
2. 기존 ADR을 유지·대체·확장하는지 적고, 대체라면 이전 결정은 삭제하지 않는다.
3. `unknown`과 실패를 성공으로 바꾸지 않는 상태 전이를 고정한다.
4. 원문 locator, input/output hash, actor·request ID·감사 범위를 정한다.
5. migration·권한·백업·복구·API version과 검증 명령을 함께 제시한다.
6. 실제 운영 승인 전에는 `draft`, `candidate`, `blocked` 또는 `not enabled`를 명확히 유지한다.

상세 결정은 이 문서에 장문으로 복제하지 말고 `docs/tracking/decisions/NNNN-*.md`에 추가한
뒤 이 색인과 관련 정본(`business-rules.md`, `contracts.md`, `operations.md`)의
링크를 갱신한다.

- [ADR-0069 사용자 요청 기반 Luna 심층검토](tracking/decisions/0069-user-requested-luna-deep-review.md): 건별 미리보기·승인·동결 입력, 공용 슬롯, 참조 표식, 기본 자동 시작 비활성.

- [ADR-0070 가상 SI 3사·지식그래프 기반 사내 데모](tracking/decisions/0070-multi-company-knowledge-demo.md): 목표 설계 채택, 회사별 결과·추적 분리, 불변 그래프 근거, 실제 6건/18건/9건 인수. DEMO-01~04는 데모 브랜치에 구현(main·운영 미반영, DEMO-04는 frontend만 바꾸고 mock 화면으로만 검증), DEMO-05는 구현 전. 2026-10-09 개정: `bidops-local`·실제 3일 수집·LiteLLM 개요를 준비 기준으로 채택하고 실제 Luna 심층은 DEMO-03/05 인수 게이트로 유지. 2026-10-11 재계획: DEMO-03은 실제 격리 스택 준비와 호출 전 fail-closed 확인까지로 닫고, 대표 1건 실제 Luna 심층은 DEMO-05로 이관(유일한 준비 공고 179가 기존 inventory 불일치 findings로 호출 전 거부).

- [ADR-0071 홈페이지 전문 가상 1사 기준 심층 검토 재정의](tracking/decisions/0071-homepage-single-company-deep-review.md): 2026-10-14 가상 SI 3사 데모를 홈페이지 구축·운영·유지보수 전문 가상 1사로 전환. HWP/HWPX 원본 정본, 요구사항 카드 inventory, codex-exec `gpt-6-luna`/high 단일 모델(LiteLLM·Terra 제외), 2층 분석, 5블록 실무자 화면, gold 10건, Neo4j 비교 실험(AGE 제외). DEMO 그룹 종료, HP 그룹 HP-00~06.

- ADR-0071 후속 결정(2026-10-15): [HP 공통 계약](work/hp-contract.md) §1·4·5·6·7·11에 업무별 concept 분리 원칙·가상회사 기본 설정·카드+여섯 문서 영역·40분 목표/60분 강제 종료·실패 시 부분 보존과 사람 검토를 반영. 제품 구현·정책 적용·최종 인수 완료를 뜻하지 않는다.

- ADR-0071 화면 후속 결정(2026-10-15): [HP 공통 계약 §8](work/hp-contract.md#8-실무자-판정-화면-확정-구성-세부는-hp-04)의 다섯 영역·부족/미확인/충족 정렬·원문 쪽 불확실성 표시·DEMO 데이터 보존 및 가상 온웹서비스만 표시를 사용자 승인. 구현·화면 검증은 별도다.

- ADR-0071 사람 정답 작성 결정(2026-10-15): [HP 공통 계약 §9](work/hp-contract.md#9-gold-10건-작성-방식-확정-점수-결정-대기-hp-06)에서 회사·용어 동결 후 모델 결과 전 작성, 5건부터 최종10건, 충족/부족 각각5개 강제 폐기, 불일치 사람 검토를 승인. 통과 점수·정답·인수 결과는 미확정.

- ADR-0071 초기 데모 품질 기준 확정(2026-10-15): [HP 계약 §9](work/hp-contract.md#9-gold-10건-작성-방식품질-기준-확정-hp-06), 종합8/10·차단조건recall80%·카드일치70%·명백한 필수자격 미충족의 충족 오판0건. 비일치·중대한 오류는 사람 검토, 최종 인수 별도. 운영 품질 보증 아님.

- ADR-0071 Neo4j 실험 기준 확정(2026-10-15): [HP 계약 §10](work/hp-contract.md#10-neo4j-비교-실험-확정-기준-hp-05), 경로발견율10%p 개선 또는5질의 중3개 작성·수정 우위, 필수경로 손실0·설명 비열화가 채택 후보 조건. 비용·AGE 제외, 최종 도입은 실제 결과 후 사람 결정.

- ADR-0071 회사 기준 v2 방향 승인(2026-10-15): [HP02 재계획](work/groups/HP/features/HP-02-homepage-ontology-company/preparation.md#실적-기반-회사-v2-재계획--2026-10-15). 가상 실적의 명시 담당 범위→역량 도출, 현재 자격/인력/SLA와 계약 조건 분리. 평가 외3원문 참고, 구체 수행 가정은 초안. v1 불변 보존·새 기준의 사람 정답/제품 구현 미완료.

- ADR-0071 회사 v2 담당 범위 확정(2026-10-15): 사용자 “확정해”로 [세 가상 실적·표준 절차](work/groups/HP/preparation/company.experience.approved.v2.json) 승인. 기존 미확인 인력/자격/SLA·계약 조건 유지. [v2 입력](work/groups/HP/preparation/review-inputs.frozen.v2.json)은 모델 보조 검토 자료이며 독립 gold나 제품 완료가 아니다.

- 2026-10-15 HP pre-loop: 승인 회사 v2·온톨로지와 HP02~06 intent/spec/plan 정합화. source 포함 unit ID, typed sidecar binding, 단계 결과·REST·사람 평가 경계를 문서화. 기술 조정값은 사용자 위임으로 고정, 제품 구현·실제 실험은 시작하지 않음.
- 2026-10-15 HP 명세 독립 리뷰 반영: 승인 입력 v2/preview 결속, 그래프 expected/required/actual/human/report 계약, gold 조건 ID의 사람 대응표를 명시. 기존 실제실험 필수 요구에 맞춰 HP05 real_data_run을 필수 수동 proof로 정합화; 제품 수용 기준 완화 없음.

- ADR-0073 루트랩 실회사 기준 AX 과제 재정의(2026-10-16): 가상회사 전제 폐기, G1 브리핑·G2 판정·G3 제안서 초안, Luna 정책 승인 자동 전송, 회사 근거 데이터가 핵심 성공 요인. HP run abandon·HP-02~06 blocked, 새 그룹 `RL`. [상세](tracking/decisions/0073-rootlab-real-company-ax-redefinition.md)
- ADR-0048 개정(2026-10-16): 라이트 테마 값을 RL 시안 v26 팔레트로 교체하고 셸(사이드바 240px·상단바 44px·`/briefing` 자리)을 시안 그대로 적용. 상세는 ADR-0073 개정 절과 `docs/1016_rootlab-redefinition/ui-spec.md` §2.
- ADR-0073 하위 명세 결정(2026-10-16, RL-00~06 intent·spec·plan): 사실 status `proposed` 추가·origin 7값(실회사 등록, DEMO 계약 §1·§3·§4 개정 예정), 브리핑은 결정적 규칙(LLM 없음), Slack Socket Mode, 회사 근거 화면 읽기 전용(파일이 정본), RL-03 1차 대상은 사전규격·전송은 정책 단위 승인 + 자동 preview/approval(worker INSERT 5개), 제안서 PDF는 ReportLab + 이미지 NanumGothic, gold 표본은 실제 수집 10건, RL-06은 계측·검토만. 상세는 `docs/work/groups/RL/features/*/spec.md` "결정과 이유". 큰 틀 문서 개정은 각 기능의 문서 단계에서 실행한다.
- ADR-0073 RL-00 회사 근거 결정(2026-10-16): 실회사 루트랩 1곳을 DB 전체에서 1곳으로 등록(`real_company_exists`)하고 가상회사는 `BIDOPS_DEMO_ENABLED=true`에서만 허용, 사실 status `proposed`(에이전트 제안·사람 미확인)와 origin 7값 추가, 회사 근거 화면은 읽기 전용(회사 파일이 정본), `GET /api/company`·workload `company_attention` 추가. [DEMO 공통 계약](work/demo-contract.md#rl-개정-2026-10-16-rl-00-adr-0073) §1·§3·§4 RL 개정으로 반영했다. ADR-0048 추가 개정: 추정값 pill만 blue ramp 사용(`bidopsTheme.ts` 주석 갱신, 연차 추적 pill 제외). 구현과 `bidops-local`(별도 DB `bidops_rla`) 격리 등록·활성화는 RL-00 run에서 끝났고 운영 반영은 아직이다.
- ADR-0073 RL-01 브리핑 결정(2026-10-17): 후보 선별·점수·이유·차단 조건은 결정적 규칙(LLM 없음, 규칙 파일 `briefing-policy-v1.json`은 버전+sha256 고정 immutable), 회사 사실은 `confirmed`만 읽고 발주계획은 반복 발주처 ∧ 유사 실적만, Slack은 Socket Mode(공개 endpoint 없음)·전송은 `core/slack.py` 하나·기본 꺼짐, 화면·Slack 반응은 개인 기록이며 추적 상태·Go/No-Go를 바꾸지 않음, 지역 제외는 보류(수집 데이터에 참가 가능 지역 이름이 없음, 사용자 결정 2026-10-17; `excl:region.keywords` 루트랩 v2 = 대구·세종은 값만 보존). `briefing_pending` workload 키·REST 4개·테이블 3개 추가. [계약](contracts.md#브리핑-rl-01-2026-10-17)·[규칙](business-rules.md#브리핑-추천반응-rl-01-2026-10-17)·[운영](operations.md). 구현과 `--send` 없는 감독 시운전(bidops-local `bidops_rla`)은 RL-01 run에서 했고, 실제 Slack 전송·운영 반영은 아직이다.
- ADR-0073 RL-02 사업기회 레코드 결정(2026-10-17): 활동 피드는 저장하지 않고 권위 연결·관측·감사·반응·노트에서 파생(시스템 처리 이벤트 없음, 판정·초안 사건은 hook `opportunity_activity_items`), 단계 바 6단계에서 개찰·계약은 데이터가 없으면 `unknown`(추정 금지), 노트·다음 행동은 append-only 테이블 `opportunity_note`(web은 `UPDATE (done_at, done_by)` 열만, DELETE 없음)이고 본문은 어떤 모델 입력에도 넣지 않음, 마감 D-3·D-1 알림은 RL-01 `tracked_change` 사유(규칙 파일 `briefing-policy-v2.json`, v1 보존), 단독 상세 route를 레코드 화면으로 교체하고 목록 pane 상세는 유지. 리더 권장안 9건은 `docs/work/_runs/rla-20261016/decisions.md` #9~#17(추천 0건 날·주말 알림 한계는 backlog). REST 3개·테이블 1개·확장점 1개 추가. [계약](contracts.md#레코드-활동-피드노트-rl-02-2026-10-17)·[규칙](business-rules.md#사업기회-레코드-단계-바활동-피드-rl-02-2026-10-17). 구현은 RL-02 run에서 끝났고 검증은 단위·mock Playwright·일회용 PostgreSQL 테스트 범위이며 실제 스택 시운전·운영 반영은 아직이다.
- ADR-0073 RL-03 카드 판정 결정(2026-10-17, ADR-0050·0069의 건별 승인을 정책 단위로 완화한 실행): 사전규격만 대상(입찰공고는 후속), **개요 비의존(D1)** — `card-v1`은 개요 gate를 생략하고 SW=Y ∧ ready 묶음으로 자격을 보며 동결 `overview_*`는 null, **전송 범위(D2)** — `confirmed` 사실 전부(값 포함)와 공고 원문 unit만 보내고 `proposed`·`unknown`은 `{fact_key, status}`만, 노트·운영 정보·모델/정책 id는 제외(역할·종합은 대조가 참조한 사실만, B10·B11), 전송은 `transfer_policy_approval`(행 canonical sha·scope·일일 상한, append-only) + 건별 감사 `analysis.transfer.sent`이고 자동 경로는 worker INSERT 5개로 `system:transfer-policy` preview/approval을 만든다. `proposed`·`unknown`은 근거도 `부족`도 아닌 `unknown`(`proposed_fact`), 역할은 대조를 넘지 못하고 실패는 사람 검토(자동 보정·재시도 없음). 자동 시작은 브리핑 추천 ∧ ready ∧ SW=Y ∧ 승인·상한, 상한 초과는 다음 브리핑 직후 큐 처리(자동 따라잡기 없음, 동시성은 advisory lock — B8). 리더 권장안 B1~B14는 `docs/work/_runs/rlb-20261017/decisions.md`(`verdict_request` 열 단위 UPDATE B1, 정책 행 `card` 키·`anyOf` B3, view 가산 키 B4, 브리핑 hook 한 확장점·drain 의미 B13, `notice_id` nullable B14 등). Slack 스레드는 가짜 서버까지(D5). 구현·mock 검증은 격리 스택이고 실제 Luna 1건(T12)·운영 반영은 pending이며 결과는 `unmeasured_reference`다. [계약](contracts.md#카드-기반-참여-판정-rl-03-2026-10-17)·[규칙](business-rules.md#rl-자동-분석과-판정-상태-rl-03-2026-10-17)·[운영](operations.md)·[인터뷰](work/groups/RL/batch-b-interview.md).
- ADR-0073 RL-04 제안서 초안 결정(2026-10-18, RL-03 정책 단위 전송 승인의 용도 확장): 완료된 RL-03 카드 판정 하나를 입력으로 bid-procedure §5에 대응한 여섯 절 초안·요구사항 대응표·PDF(HWP 후속)를 만든다. Luna 호출은 절당 1회(+schema repair 1회, contract `proposal-section-v1`, 정책 `proposal-policy-luna-v1`·승인 `purposes=["proposal"]` 별도 행, 하루 상한 = 초안 수·절 재생성 1/6, mock 계보 제외), 전송 payload는 8키이고 회사 사실은 `confirmed`만 값과 함께·`proposed`/`unknown`은 `{fact_key, status}`만(D2), 출처 없는 문장 금지·가격/투입 인원/일정 숫자는 공고 쪽 출처 인용만 예외(B43)·요구사항 수행방안은 카드 unit 누락 0, 검증 실패는 절 `failed`·사람 검토(자동 보정 없음), 초안 정착 상태 completed/partial/failed·superseded(B45), 문장 수정은 append-only overlay, PDF는 ReportLab `invariant=1`+이미지 NanumGothic(저장소 폰트 없음, D9)·namespace `proposal-pdf` 365일(키 2개 추가는 사용자 승인 B48·B49). migration `0041_proposal_draft`(테이블 4)·REST 8·활동 hook `draft_prepared`. 리더 권장안 B41~B49는 `docs/work/_runs/rlb-20261017/decisions.md`. 구현·mock 검증은 격리 스택이고 실제 Luna 초안 1건(T11)은 RL-03 실제 판정이 없어 pending, 운영 반영은 아직이다. [계약](contracts.md#제안서-초안-rl-04-2026-10-18)·[규칙](business-rules.md#제안서-초안-rl-04-2026-10-18)·[운영](operations.md#rl-제안서-초안-운영-rl-04-2026-10-18).
