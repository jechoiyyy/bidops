# BidOps 아키텍처 결정 기록

| 항목 | 내용 |
|---|---|
| 문서 상태 | 현재 결정 기준선·통합 색인 |
| 기준일 | 2026-09-05 |
| 범위 | 수집, 선별, 사전규격 검토, 심층 검토, 입찰공고 추적, 운영·보안 |
| 상세 결정 정본 | [`docs/tracking/decisions/`](tracking/decisions/)의 ADR-0001~0038·0042~0045·0049~0051, [`docs/design/ADR.md`](design/ADR.md)의 ADR-0039~0041·0046~0048 |
| 함께 읽을 문서 | [`PRD.md`](PRD.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`contracts.md`](contracts.md) |

이 문서는 여러 시점에 작성된 결정 기록을 현재 관점에서 읽기 위한 통합 ADR이다. 각 결정의
배경·대안·결과를 이 문서에 복사해 두지 않고 상세 ADR로 연결한다. 이 문서의 요약과 상세 ADR이
충돌하면 상세 ADR의 상태와 이후에 채택된 ADR을 따른다.

## 1. 문서 권위와 결정 읽는 법

결정·요구사항·구현 사실을 다음 순서로 해석한다.

1. 루트 [`AGENTS.md`](../AGENTS.md)와 `CLAUDE.md`의 강제 게이트와 현재 런타임 사실
2. 현재 업무·보안·계약·운영·표준 문서: [`business-rules.md`](business-rules.md),
   [`security.md`](security.md), [`contracts.md`](contracts.md), [`operations.md`](operations.md),
   [`standards.md`](standards.md)
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
| [0027](tracking/decisions/0027-order-plan-requery-window.md) | 발주계획은 최근 21일 구간을 매일 재조회 | 채택 | 종단 관측으로 후속 재평가 |
| [0028](tracking/decisions/0028-bid-first-opportunity-registration.md) | 입찰공고에서 처음 등장한 사업도 기회로 등록 | 채택 | 첫 단계가 bid인 기회 허용 |
| [0029](tracking/decisions/0029-screening-mock-provider.md) | 1차 분류는 결정적 mock 제공자로 소비 계층을 먼저 구현 | 채택 | mock은 reference-only |
| [0030](tracking/decisions/0030-opportunity-tracking-state.md) | 추적 상태는 모든 사업기회가 갖고 사람 선택과 시스템 신호를 분리 | 채택 | `미선택·계속 추적·보류·종료` |
| [0031](tracking/decisions/0031-prespec-overview-review-stage.md) | 사전규격 개요 검토를 1차 분류와 심층 검토 사이 독립 단계로 둠 | 채택 | RFP 앞부분의 저비용 판단; 심층 진입의 "사람 승인" 문장은 [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)가 좁힘 |
| [0032](tracking/decisions/0032-prespec-overview-cutting-rule.md) | 사전규격 개요 검토 앞부분은 문서 구조에 따라 자르고 모호하면 사람 검토로 보냄 | 채택 | 고정 block 수 fallback 금지 |
| [0033](tracking/decisions/0033-prespec-overview-review-runtime-contract.md) | 개요 검토 절단 snapshot과 모델 attempt를 분리하고 사설 binding 없이는 완료하지 않음 | 채택 | `awaiting_model`·mock 비배포; 진입의 "사람 승인"은 [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md), 참조 실행 표식은 [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md) |
| [0034](tracking/decisions/0034-bid-delta-final-decision.md) | 입찰 delta와 최종 사람 결정을 불변 비교와 append-only 기록으로 분리 | 채택 — 계약/구현 경계 | worker·운영 활성화는 별도 |
| [0035](tracking/decisions/0035-prespec-overview-attempt-result-lifecycle.md) | 개요 모델 attempt의 상태 전이와 검증 결과를 분리 | 채택 | result/event와 안전한 v2 projection |
| [0036](tracking/decisions/0036-judgment-model-lineage-source.md) | 판정의 모델 계보는 revision→execution 경로를 정본으로 함 | 채택 | legacy 계보는 `unknown` |
| [0037](tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md) | C-2 발주계획 선별은 BM25 Top 300 뒤 Qwen으로 확정 | 채택 | 현재 선택; 운영 활성화와 별개 |
| [0038](tracking/decisions/0038-order-plan-c2-phase0-contracts.md) | C-2 Phase 0 전용 파일·REST·DB 계약과 상태 경계 고정 | 채택 — 계약만 | 제품 adapter·DB·실행은 후속 phase |
| [0039](design/ADR.md#adr-0039-astryx-디자인-시스템-채택과-승인-범위) | Astryx 디자인 시스템 채택과 승인 범위 | 채택 | 고정 빌드 산출물; 테마는 0048이 개정; 화면 이행은 후속 단계 |
| [0040](design/ADR.md#adr-0040-레이아웃-소유권과-화면-단위-이행) | 레이아웃 소유권과 화면 단위 이행 | 채택 | 레이아웃은 프로젝트 소유; 화면별 이행 |
| [0041](design/ADR.md#adr-0041-정보구조와-판정-동선) | 정보구조와 판정 동선 | 채택 | 회차·누적 축과 같은 화면 판정 입력을 유지; 결정 1·2·4는 0046가 개정 |
| [0042](tracking/decisions/0042-c2-model-revision-declared-at-deployment.md) | C-2 모델 revision은 배포 시점 선언으로 1회 대조 | 채택 | vLLM이 revision을 노출하지 않음; 응답 값은 있으면 대조; [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)이 판정·개요·심층으로 확장 |
| [0043](tracking/decisions/0043-screening-deep-review-module-boundary.md) | 선별과 심층 검토를 한 배포 단위 안의 독립 모듈로 분리 | 채택 | 구조 경계만 고정; 배포 단위·운영 활성화는 불변; [0045](tracking/decisions/0045-backend-module-layout.md)가 네 모듈로 보강 |
| [0044](tracking/decisions/0044-c2-stage2-matches-the-measured-method.md) | C-2 stage 2를 측정된 방법과 일치시킴 | 채택 | item_id payload·strict schema·승인 generation config; binding v2 |
| [0045](tracking/decisions/0045-backend-module-layout.md) | 백엔드를 core·lifecycle·screening·deep_review 네 모듈과 조립 계층으로 배치 | 채택 | ADR-0043 보강; lifecycle 확장점·`BIDOPS_MODULES`·경계 강제 테스트; REST 표면 불변. core의 모델 transport 이름은 [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)이 `model_client`로, 확장점은 [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)가 다섯째로 갱신 |
| [0046](design/ADR.md#adr-0046-사업-추적-중심-정보구조와-추적-결정의-위치) | 사업 추적 중심 정보구조와 추적 결정의 위치 | 채택 | 사이드바 16→7, 검토 대기열→사업 추적; 결정 1은 발주계획의 추적 결정 |
| [0047](design/ADR.md#adr-0047-데스크톱노트북-전용-지원-폭) | 데스크톱·노트북 전용 지원 폭 | 채택 | 1280~1920px만 지원; 검증 viewport 두 폭 |
| [0048](design/ADR.md#adr-0048-무드보드-기반-색-팔레트와-테마-소유권) | 무드보드 기반 색 팔레트와 테마 소유권 | 채택 | 무드보드 5색 anchor에서 파생한 `bidops` 테마; 화면은 토큰만 읽고 `--color-*`를 재정의하지 않음; 의미색은 무드보드가 정하지 않음 |
| [0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md) | 사전규격 문서 준비를 등급으로 자동화하고 `SW사업대상=Y`는 심층 검토까지 자동 시작 | 채택 | FR-DOC-07·ADR-0031·0033의 "사람 승인"을 이 규칙으로 대체; 고비용 전량 분석의 승인 경계는 유지 |
| [0050](tracking/decisions/0050-unified-openai-compatible-model-client.md) | 모델 호출을 하나의 OpenAI 호환 client와 용도별 설정으로 통일 | 채택 | C-1·개요·심층이 `core/model_client`를 씀; 용도별 endpoint·선언 revision·참조 실행 표식; 이전 로컬 provider 경로 제거 |
| [0051](tracking/decisions/0051-deep-review-v2-deterministic-subset.md) | deep-review-v2의 결정적 부분만 채택 | 채택 — 부분 채택 | segment manifest·요구사항 inventory·검증 연결만 구현. 역할별 모델 분석과 Luna 평가는 보류 |

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
- 발주계획 최근 21일 재조회는 현재 유지하되 2026-09-08·09-14 부근의 종단 관측 뒤 범위를
  재평가한다. 관측 전에는 변경을 추정하지 않는다.

근거: ADR-0022, ADR-0024~0028 및 [`20260828-lifecycle-linkage-survey.md`](validation-runs/20260828-lifecycle-linkage-survey.md).

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
  허용 host가 비었거나 선언 revision이 64자 hex가 아니면 그 용도는 호출 전에 fail closed한다.
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
| C-2 외부 transport | `execution_allowed=false` | 실행별 private vLLM 전송 승인, allowlist·payload preview·binding 일치 |
| 개요 검토 model worker | 기반 API·화면·attempt 저장에 더해 모델 실행 worker와 통일 client 연결까지 구현. 실행 결과는 `quality_status=unmeasured_reference\|mock_reference` | 승인된 사설 vLLM artifact와 사람 gold로 측정한 품질. 참조 실행 결과는 활성화 근거가 아니다 |
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
뒤 이 색인과 관련 정본(`business-rules.md`, `contracts.md`, `security.md`, `operations.md`)의
링크를 갱신한다.
