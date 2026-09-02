# BidOps 아키텍처

| 항목 | 내용 |
|---|---|
| 문서 상태 | 현재 구조·계약·목표 구조를 통합한 기준 문서 |
| 기준일 | 2026-09-01 (KST) |
| 정본 | docs/ARCHITECTURE.md |
| 호환 진입점 | docs/architecture.md |
| 제품 | BidOps |
| 관련 문서 | ADR.md, PRD.md, business-rules.md, contracts.md, security.md, operations.md |

## 1. 문서의 범위와 읽는 법

BidOps는 기획·사업개발 담당자가 나라장터 발주계획을 조기에 탐색하고, 사전규격 제안요청서를 검토한 뒤 입찰공고까지 추적하는 사내 의사결정 지원 시스템이다. 시스템은 후보를 수집·정리·비교하고 근거를 제시하지만, 추적 승인과 최종 입찰 Go/No-Go는 사람의 결정으로 남긴다.

이 문서는 저장소의 현재 코드, 현재 계약, 승인된 설계와 미구현 목표를 한 문서에서 연결한다. 따라서 설계된 스키마나 화면이 존재한다는 사실을 완성된 운영 기능으로 해석하지 않는다.

상태 표기는 다음과 같다.

- 현재: 저장소에 구현되어 있고 현재 실행 경로의 일부다. 전체 업무 흐름의 운영 완료를 뜻하지 않는다.
- 계약: REST·파일·DB·상태 전이가 고정되어 있다. 구현 또는 운영 승인이 남아 있을 수 있다.
- 실험: 재현 가능한 비교를 위해 실행된 경로다. 제품 품질·운영 활성화 승인을 뜻하지 않는다.
- 목표: 후속 구현 대상이다.
- 보류: 안전·품질·운영 조건이 충족될 때까지 의도적으로 비활성이다.

정확한 필드, 상태값, 경로 및 FK는 docs/contracts.md와 docs/database-guide.md를 우선하고, 결정의 이유와 대안은 docs/tracking/decisions/를 우선한다. 상세 결정 목록은 docs/ADR.md에 모아 둔다. docs/legacy/는 보관본이므로 실행 진입점이 아니다.

## 2. 설계 원칙

### 2.1 증거 우선

원문, 수집 회차, 정규화 결과, 문서 버전, 모델 입력·출력, 사람 리뷰는 서로 다른 불변 산출물이다. 어떤 판단도 원문 위치(source locator)와 연결되지 않은 숫자·요구사항·근거를 정본으로 승격하지 않는다.

### 2.2 상태의 축을 섞지 않음

다음 축은 독립적으로 저장하고 화면에서도 별도 표시한다.

| 축 | 의미 | 결정 주체 |
|---|---|---|
| 적합성 등급 | 회사 역량과 사업 기회의 적합성 | 규칙·모델의 보조 판단 + 사람 검토 |
| 참여 준비 상태 | 참여에 필요한 회사 정보와 자료의 준비 정도 | 사람 검토 |
| 심층 검토 추적 상태 | 계속 추적·보류·종료 | 사람 |
| 입찰 최종 결정 | Go 또는 No-Go | 사람 |

등급이 높다는 이유만으로 추적하거나 입찰하는 자동 전이는 없다. 검증되지 않은 회사 역량·자격·실적은 unknown 또는 null로 보존한다.

### 2.3 불변성과 재현성

수집 회차, 원본, 정규화 버전, 프로필, 정책, 프롬프트, 모델 식별자, 입력 스냅샷, 출력, 리뷰를 덮어쓰지 않는다. 수정은 새 버전·새 회차·새 시도로 기록한다. 생성 순서와 현재성 경계를 확인할 수 있도록 해시와 관계를 남긴다.

### 2.4 경계가 있는 실행

기존 Python 수집·선별·보고 파이프라인은 버전이 있는 파일 계약과 subprocess 경계로 연결한다. FastAPI와 React가 파이프라인 내부 구현이나 업무 규칙을 복제하지 않는다. 문서 변환 worker는 네트워크가 없고, 외부 모델 호출은 승인된 목적별 overlay와 건별 payload에서만 허용한다.

### 2.5 실패를 보존하고 사람에게 보냄

검증 실패, 부분 산출물, 시간 초과, 문서 변환 실패, 모델 실패를 성공으로 보정하지 않는다. 실행과 산출물의 상태를 실패로 남기고 사람 검토 또는 재시작 가능한 경로로 보낸다. 운영 장애 때 다른 외부 모델로 자동 fallback하지 않는다.

## 3. 시스템 컨텍스트

### 3.1 외부 경계

~~~mermaid
flowchart LR
    planner[기획·사업개발 담당자]
    operator[운영 담당자]
    g2b[나라장터 OpenAPI]
    git[승인 프로필 기준선 Git]
    localmodel[Ollama Qwen 모델]
    privatevllm[승인된 사설 OpenAI-compatible vLLM]
    bidops[BidOps]

    planner -->|검색·검토·사람 결정| bidops
    operator -->|실행·승인·장애 확인| bidops
    g2b -->|발주계획·사전규격·입찰공고| bidops
    git -->|회사 프로필 기준선 검증| bidops
    bidops -->|로컬 추론| localmodel
    bidops -->|승인 payload만 건별 전송| privatevllm
~~~

나라장터 자료는 외부 원문과 관측 시점을 보존한다. Git은 승인된 회사 프로필 기준선을 검증하는 입력일 뿐, 회사 역량의 자동 증명원이 아니다. 모델 endpoint는 기능별로 승인되고 식별자·revision·prompt·profile hash와 함께 기록된다.

현재 애플리케이션에는 로그인·역할 기반 권한·SSO가 없다. 사내망 접근 제한이 네트워크 경계이며, 담당자 이름은 인증이나 세밀한 권한이 아니라 감사 표식이다.

### 3.2 제품 경계

BidOps가 자동화하는 범위는 수집, 원문 보존, 정규화, 후보 선별, 첨부 안전 처리, 구조화·요약 보조, 변경 비교 및 보고서 준비다. 다음은 자동화하지 않는다.

- 발주처 연락
- 추적 승인
- 회사의 자격·실적 보증
- 최종 입찰 Go/No-Go
- 검증 실패의 자동 보정

## 4. 컨테이너 구조

~~~mermaid
flowchart TB
    browser[React 관리 화면]
    api[FastAPI API]
    pipeline[Python pipeline subprocess<br/>collect / screen / report]
    docworker[Document worker<br/>network disabled]
    analysis[Analysis worker<br/>lease + concurrency 1]
    scheduler[Scheduler<br/>default disabled]
    pg[(PostgreSQL 17<br/>bidops schema)]
    minio[(Versioned MinIO)]
    clamav[ClamAV]
    ollama[Ollama]
    vllm[Private approved vLLM]
    source[나라장터 OpenAPI]

    browser -->|REST| api
    api -->|transaction / enqueue| pg
    api -->|object metadata / signed flow| minio
    api -->|explicit command| pipeline
    pipeline -->|versioned file contract| api
    api -->|quarantine / derived objects| minio
    api -->|document bytes scan| clamav
    api -->|clean hash + scratch job| docworker
    docworker -->|structured sidecar via scratch| api
    analysis -->|lease / result / audit| pg
    analysis -->|structure / response object| minio
    analysis -->|approved local or private inference| ollama
    analysis -->|approved payload| vllm
    scheduler -->|when explicitly enabled| analysis
    source -->|purpose-specific egress| pipeline
~~~

### 4.1 구성요소 책임

| 구성요소 | 책임 | 금지된 책임 |
|---|---|---|
| React frontend | 검색·목록·상세·리뷰·피드백·사람 결정 UI | DB 직접 접근, 파이프라인 규칙 복제 |
| FastAPI backend | 인증 경계 전 단계의 API, 입력 검증, transaction, job 제어, 안전한 projection | 모델 응답을 근거 없이 보정, 내부 경로·secret 노출 |
| Python collect | 나라장터 수집, 회차 원본·정규화 파일 생성 | 적합성·심층 검토 판정 |
| Python screen | 결정적 선별, 모델 호출 wrapper, 결과·실패 파일 생성 | 사람 승인 대행 |
| Python report | 결정적 HTML·피드백 렌더링 | 화면 전용 업무 규칙 |
| Document worker | quarantine 파일 검사·변환·구조 추출 | 네트워크 호출, 원본 덮어쓰기 |
| Analysis worker | overview/deep review/비교 실행, lease·fence·validation | 무승인 외부 전송, 자동 Go/No-Go |
| Scheduler | 승인된 주기 실행을 enqueue | startup catch-up, 자동 retry, 기본 활성화 |
| PostgreSQL | 메타데이터·관계·상태·감사·정본 리뷰 | 원본 binary의 유일한 저장소 |
| MinIO | raw·attachment·문서·보고서 등 versioned object bytes | 공개 URL 제공, 임의 overwrite |
| ClamAV | quarantine 파일 악성코드 검사 | 파일 승인 판단의 유일한 근거 |

## 5. 주요 데이터 흐름

~~~mermaid
flowchart LR
    collect[수집 회차]
    raw[불변 원본]
    norm[정규화 관측]
    opp[기회·공고 identity]
    plan[발주계획 C-2]
    prespec[사전규격]
    attach[첨부 quarantine]
    prepare[문서 준비·구조화]
    overview[개요 검토]
    deep[심층 검토]
    track[추적 상태]
    bid[입찰공고]
    delta[bid delta]
    final[Go / No-Go]
    human[사람 검토]

    collect --> raw --> norm --> opp
    opp --> plan
    opp --> prespec
    plan -->|구조화 1차 선별| human
    prespec --> attach --> prepare --> overview --> deep
    overview --> human
    deep --> human --> track
    opp --> bid --> delta --> final --> human
~~~

위 흐름은 하나의 자동 상태 머신이 아니다. 발주계획, 사전규격, 입찰공고는 각각 독립된 관측과 재수집 규칙을 가지며, 공식 식별자 관계와 제목 기반 후보 관계를 구분한다. 사전규격에서 발주계획으로 가는 공식 key가 없으면 연결을 미확인으로 보존한다.

### 5.1 수집과 identity

1. 수집 실행은 목적과 시점이 고정된 run을 만든다.
2. 원문 응답은 MinIO에 불변 객체로 저장하고 PostgreSQL에 hash·locator·상태를 기록한다.
3. 정규화는 원문을 대체하지 않고 새 version을 만든다.
4. 공식 외부 식별자로 누적 identity를 만들고, 각 수집 시점의 값은 observation으로 저장한다.
5. 동일 기회의 최신 상태는 observation을 선택하는 규칙으로 계산하며, 과거 관측을 삭제하지 않는다.

발주계획은 전체 population을 보존하고, C-2는 그 회차의 고정 표본·정책·모델 binding을 이용한다. 사전규격은 general/technical service를 수집하며 소프트웨어 여부는 필터가 아니라 라벨이다. 제목 후보는 공식 관계가 아니다.

### 5.2 발주계획 C-2 선별 흐름

~~~mermaid
flowchart LR
    input[625건 고정 입력 manifest]
    bm25[BM25 ranking<br/>Top 300]
    batch[배치 실행<br/>300 / 325]
    qwen[Qwen 분류<br/>BM25 후보만]
    result[결과·실패·telemetry]
    feedback[사람 정답·피드백]
    gate[품질 gate]
    product[제품 adapter/API/UI]

    input --> bm25 --> batch --> qwen --> result
    result --> feedback --> gate
    result --> product
    gate -. 승인 후 .-> product
~~~

현재 C-2는 실험 선택과 Phase 0 계약 검증까지 진행된 상태다. 제품 adapter, 제품 DB 적재, API/UI 연결, 운영 worker는 아직 완성된 end-to-end 흐름이 아니다. 실험 결과의 후보 비율이나 recall/precision은 운영 활성화 승인과 동일하지 않다.

Phase 0에서 고정한 산출물은 input, ranking, decisions, failures, telemetry, result, feedback 계약이다. 모든 산출물은 schema_version, run id, config/prompt/model/profile hash와 연결되어야 한다. 부분 manifest와 draft 정답은 완료된 gold set으로 승격하지 않는다.

### 5.3 첨부와 문서 준비

~~~mermaid
flowchart LR
    url[허용된 원문 URL]
    quarantine[quarantine object]
    scan[ClamAV scan]
    convert[networkless conversion]
    version[document version]
    structure[TOC·heading·page locator]
    bundle[review bundle snapshot]
    human[실패·모호성 사람 검토]

    url --> quarantine --> scan
    scan -->|clean| convert --> version --> structure --> bundle
    scan -->|failed| human
    convert -->|failed / unsupported| human
~~~

허용 확장자와 크기는 현재 계약인 HWP/HWPX/PDF 및 50 MiB 한도를 따른다. redirect·임의 URL·symlink·경로 이탈을 허용하지 않는다. 원본 attachment와 파생 문서는 서로 다른 object와 version으로 기록한다.

문서 구조는 목차와 의미 있는 heading을 기준으로 절단한다. 구조가 모호하면 더 공격적으로 자르거나 내용을 추정하지 않고 unknown 또는 사람 검토로 보낸다. review bundle은 특정 document version과 cut snapshot을 고정하여 뒤늦은 원문 변경이 리뷰를 바꾸지 않게 한다.

### 5.4 개요·심층 검토

~~~mermaid
flowchart LR
    bundle[document bundle]
    profile[profile projection]
    policy[review policy]
    prompt[prompt revision]
    model[approved model execution]
    attempt[attempt]
    stages[3 analysis stages]
    claims[claims + source locators]
    report[deterministic report]
    validate[deterministic validation]
    opinion[human opinion]

    bundle --> attempt
    profile --> attempt
    policy --> attempt
    prompt --> attempt
    model --> attempt
    attempt --> stages --> claims --> report --> validate
    validate -->|pass| opinion
    validate -->|fail| opinion
~~~

개요 검토는 1차 분류와 심층 검토 사이의 별도 단계다. 심층 검토 실행은 bundle, 최소 회사 프로필 projection, 활성 policy, prompt revision, model revision을 binding한다. 모델은 판단을 보조하지만, 모든 claim은 source locator와 연결하고 검증기 실패를 사람 검토로 보낸다.

모델 lineage는 judgment revision의 recording execution이 어느 screening execution에서 생성되었는지 추적할 수 있어야 한다. legacy import처럼 lineage를 확인할 수 없는 값은 unknown으로 기록한다.

프로필 revision의 source가 current이면 working-tree snapshot으로, git:<40hex>이면 승인된 역사
commit으로 해석한다. 실행 생성 시 경로·bytes·digest를 검증하고, 승인 commit이나 digest를
확인할 수 없으면 모델 호출 전에 실패한다. 프로필 전문은 입력 계약에 복사하지 않고 최소
projection과 revision identity만 binding한다.

### 5.5 입찰 delta와 최종 결정

~~~mermaid
flowchart LR
    old[older exact snapshot]
    new[newer exact snapshot]
    fence[identity + source + collected_at + content hash]
    calc[delta calculation]
    item[7 categories of delta items]
    evidence[before/after locators]
    decision[append-only Go / No-Go]
    human[사람]

    old --> fence
    new --> fence
    fence --> calc --> item --> evidence --> human --> decision
~~~

비교는 latest 두 개를 임의로 고르는 방식이 아니라 exact snapshot fence로 고정한다. 계산 상태와 결과를 구분하며, 계산 실패·비교 불가·unknown은 변경 없음으로 축약하지 않는다. delta item은 이전·이후 locator와 계산 상태를 보유하고, 최종 결정은 append-only 이벤트로 남긴다.

## 6. 논리 데이터 모델과 lineage

### 6.1 PostgreSQL과 MinIO의 역할

PostgreSQL 17의 bidops schema가 운영 메타데이터·관계·상태·감사·리뷰의 정본이다. MinIO는 raw, attachment, document, report와 같은 binary/object bytes를 versioning으로 보존한다. DB row가 object hash·namespace·version과 연결되지 않으면 산출물을 완전한 정본으로 취급하지 않는다.

현재 Alembic head는 0015_bid_delta_final_decision이며, SQLite는 격리 테스트와 일회성 이전 입력에만 사용한다. 운영 애플리케이션이 startup에서 SQLite로 fallback하거나 create_all로 스키마를 만들지 않는다.

### 6.2 도메인 그룹

현재 DB guide 기준 68개 table은 다음 영역으로 묶인다.

| 영역 | 수량 | 주요 책임 |
|---|---:|---|
| collection / opportunity | 7 | 수집 회차, 원문 관측, 기회 identity |
| screening / review | 11 | 선별 정책·실행·판정·리뷰 |
| attachment | 3 | 첨부 메타데이터·수명·안전 상태 |
| document | 8 | object·scan·변환·버전·구조·bundle |
| overview | 5 | 개요 실행·결과·이벤트 |
| deep review | 17 | claim·evidence·report·validation·opinion |
| execution / quality / schedule | 12 | job·lease·quality gate·활성화·스케줄 |
| delta / final | 5 | snapshot pair·delta·최종 결정 |
| 합계 | 68 | Alembic head 기준 |

세부 table·column·FK·삭제 정책은 docs/database-guide.md와 docs/deep-review-erd.md의 계약을 사용한다. 이 문서의 그룹화는 탐색용이며 schema 정의를 복제하지 않는다.

### 6.3 불변 lineage

~~~mermaid
flowchart TD
    run[collection run]
    raw[raw object + hash]
    normalized[normalized version]
    observation[observation]
    profile[profile revision]
    policy[policy revision]
    prompt[prompt revision]
    model[model revision]
    input[input snapshot]
    execution[execution]
    output[output artifact]
    review[human review]

    run --> raw --> normalized --> observation
    profile --> input
    policy --> input
    prompt --> input
    model --> execution
    input --> execution --> output --> review
~~~

다음 변경은 기존 행·객체를 갱신하지 않고 새 lineage를 만든다.

- 재수집: 새 run과 observation
- 원문 변환: 새 document version
- 정책·프로필·prompt·model 변경: 새 revision
- 재실행: 새 execution과 attempt
- 사람 수정: 새 review event 또는 judgment revision
- 보고서 갱신: 새 report artifact

## 7. 실행 모델과 상태 경계

### 7.1 실행 단위

모든 장시간 작업은 작업 종류와 run/execution id를 가진다. worker는 DB lease를 획득하고 lease expiry, worker token, fence를 검증한다. 같은 논리 실행을 중복 처리해도 idempotency key와 unique constraint가 결과 중복을 막아야 한다.

기본 분석 동시성은 1이다. 큐는 FIFO와 active slot을 사용하고, stale running 작업은 자동으로 성공 처리하거나 무한 재개하지 않는다. 재시작은 새 attempt 또는 명시적 재시작 요청으로 기록한다.

### 7.2 스케줄러

스케줄러와 always-on은 기본 비활성이다. 실효 활성화는 다음 조건을 모두 만족해야 한다.

1. 환경 설정이 명시적으로 enabled다.
2. DB의 always-on 설정이 enabled다.
3. 유효한 active policy가 있다.
4. 정확히 같은 binding에 대한 운영 승인과 quality gate가 통과됐다.

앱 startup은 migration, seed, policy activation, model call을 수행하지 않는다. startup catch-up, 자동 retry, 장애 시 hosted OpenAI fallback도 수행하지 않는다. 실제 운영 활성화 전에는 secret·egress allow/deny·방화벽·backup/restore 훈련을 검증해야 한다.

### 7.3 대표 상태

상태는 도메인별로 별도 namespace를 가진다. 예를 들어 실행 상태의 failed는 적합성 등급이나 최종 no_go가 아니다.

| 영역 | 예시 상태 | 의미 |
|---|---|---|
| C-2 실행 | planned, running, completed, failed, valid_but_blocked | 계약 검증·실행·품질 gate 상태 |
| delta 계산 | pending, running, completed, failed | 계산 lifecycle |
| delta 결과 | changed, unchanged, unknown, failed | 비교 결과 |
| 추적 | 계속 추적, 보류, 종료 | 사람의 추적 결정 |
| 최종 결정 | go, no_go | 사람의 입찰 결정 |

## 8. 서비스·파일·API 경계

### 8.1 HTTP 경계

FastAPI는 검증된 request를 service와 repository transaction으로 전달하고, 응답에는 허용된 projection만 포함한다. 내부 파일 경로, MinIO credential, API key, raw secret, 모델 원문 응답을 반환하지 않는다.

현재 API는 runs, notices, pre_specs, opportunities, reviews, metrics, attachments, portals, profile, screening, quality_gates, policies, schedule, document_bundles, deep_reviews, bid_delta, reports 영역의 router를 가진다. 모든 router가 완전한 업무 flow를 제공한다는 뜻은 아니며, 상태 문서의 구현·운영 구분을 함께 확인한다.

C-2가 제품화될 때의 namespace는 docs/contracts.md의 /api/order-plans 및 /api/order-plan-screening 계약을 따른다. C-2 실험 스크립트의 파일 output을 기존 screening REST의 임의 payload로 변환하지 않고, Phase 0 계약의 adapter를 둔다.

### 8.2 파일 계약 경계

수집·선별·보고 skill은 역할을 넘지 않는다.

| 단계 | 입력 | 출력 |
|---|---|---|
| collect | API 응답·회차 설정 | raw/normalized manifest와 검증 결과 |
| screen | versioned input·policy·profile projection | ranking, decisions, failures, telemetry, result |
| report | 승인된 구조화 결과·feedback | 결정적 HTML 및 feedback artifact |

파일은 schema_version을 포함하고 producer는 엄격하게 쓴다. importer는 알려진 legacy를 명시적으로 변환할 수 있지만 원문 의미를 추정해 조용히 수정하지 않는다.

### 8.3 Frontend 경계

React는 FastAPI REST API의 consumer다. DB·MinIO·worker·모델 endpoint에 직접 접근하지 않는다. 긴 작업은 execution/job 상태를 polling하거나 명시적 refresh로 표시하고, partial·failed·unknown을 completed나 negative로 바꾸어 표시하지 않는다.

화면은 적합성 등급, 참여 준비, 심층 검토 추적, 최종 Go/No-Go를 별도 action과 별도 label로 제공한다. 담당자 이름 입력은 actor attribution이며 로그인이나 authorization을 대체하지 않는다.

## 9. 보안과 개인정보 경계

### 9.1 첨부 처리

첨부는 먼저 quarantine namespace에 저장하고 경로·크기·확장자·symlink·namespace를 검사한 뒤 ClamAV 결과를 기록한다. clean 파일만 networkless document worker로 전달한다. 허용되지 않은 URL, redirect, 경로 이탈과 원본 overwrite는 실패로 처리한다.

### 9.2 모델 전송

외부 모델에는 execution별로 승인된 최소 payload만 보낸다. payload와 binding은 목적·모델·prompt·profile hash와 감사 추적 가능해야 한다. API key, 회사 원문자료, 전체 raw attachment, 내부 경로, 불필요한 profile 데이터와 응답 본문을 로그·Git·API 응답에 남기지 않는다.

로컬 Ollama와 승인된 사설 vLLM은 기능별 model binding을 가진다. 모델 장애가 발생해도 hosted OpenAI로 자동 전환하지 않는다. 원격 overlay와 egress는 필요한 서비스에만 명시적으로 연다.

### 9.3 접근과 보존

현재는 사내망 접근 제한이 기본 경계이고 세밀한 역할 권한은 미구현이다. 앱·worker·migration·read-only backup 역할을 분리하고, backup은 object first 후 DB와 hash를 함께 보존한다. 목표 RPO는 4시간, RTO는 8시간이지만 실제 restore 훈련과 운영 권한 검증이 완료되기 전까지 달성으로 표시하지 않는다.

## 10. 배포 구조

### 10.1 T7 애플리케이션 스택

운영 기준 compose는 docker-compose.t7.yml이다. 기본 network는 내부망이며 외부 호출은 목적별 overlay를 명시한 경우에만 열 수 있다.

| 영역 | 역할 |
|---|---|
| PostgreSQL 17 | 운영 DB |
| MinIO | versioned object store |
| ClamAV | attachment scan |
| web/backend | FastAPI와 정적·관리 API |
| document-worker | 문서 변환·구조화, network disabled |
| analysis-worker | lease 기반 분석, 기본 concurrency 1 |
| init/migrate/minio-init | 명시적 초기화·migration·bucket 정책 |
| overlays | screening, remote-vllm, attachment, mock/reference 등 목적별 egress |

관리 포트는 기본 loopback binding이다. 운영 secret은 환경·secret 파일 계약을 사용하며 이미지·Git·로그에 넣지 않는다. root docker-compose.yml은 SQLite 기반 일회성 ops 입력·격리 테스트용으로 운영 정본을 대체하지 않는다.

### 10.2 시작과 종료

일반적인 시작 순서는 PostgreSQL/MinIO/ClamAV 준비, 명시적 init/migrate, web와 필요한 worker 기동이다. 앱 startup에 migration이나 policy activation을 숨기지 않는다. graceful shutdown은 실행을 새로 claim하지 않고 현재 lease와 partial 결과를 보존한다.

### 10.3 백업과 복구

백업은 MinIO object와 PostgreSQL metadata를 같은 기준 시점의 hash로 연결한다.

1. versioned object와 manifest를 먼저 백업한다.
2. PostgreSQL dump와 schema/migration 정보를 백업한다.
3. 복구 후 object hash, DB FK, lineage, currentness fence를 검증한다.
4. 불일치는 성공으로 표시하지 않고 복구 실패·사람 조치 대상으로 남긴다.

## 11. 현재 상태와 목표 상태

| 영역 | 현재 상태 | 목표·다음 경계 |
|---|---|---|
| 수집·정규화 | 기존 Python pipeline과 회차·원문·정규화 흐름 존재 | 운영 secret·egress·복구 훈련과 함께 지속 검증 |
| PostgreSQL/MinIO | 운영 정본과 Alembic head 존재 | migration·backup·restore 절차의 실제 검증 |
| FastAPI/React | 기본 관리 API·화면과 여러 router 존재 | 준비·실패 재시작·모든 lifecycle action의 end-to-end 연결 |
| 첨부·문서 | 안전 경계와 worker 설계·일부 구현 존재 | 실제 다양한 HWP/HWPX/PDF corpus, 변환 실패 UI, 재시작 |
| 개요 검토 | DB/API/UI 기반과 계약 존재 | 승인 model transport·worker·quality gate |
| 심층 검토 | ERD·계약·worker 구조 존재 | 실 corpus/gold, claim/evidence 검증, 운영 승인 |
| C-2 선별 | 실험 선택 BM25 Top 300 + Qwen, Phase 0 contract validator | 제품 adapter·DB/API/UI·worker·human gold·quality gate |
| 입찰 delta | schema/API/UI/migration 계약과 일부 구현 존재 | 계산 worker, exact snapshot 비교, 운영 검증 |
| 최종 결정 | append-only 계약 | 사람 action과 감사·권한 경계의 운영 구현 |
| 스케줄링 | 설계는 있으나 기본 비활성 | quality/operational approval 후 제한적 활성화 |
| 인증·SSO·알림 | 미구현 | 별도 보안·운영 결정과 migration 필요 |

“구현됨”은 코드나 schema가 존재한다는 뜻이고 “운영 가능”은 품질·보안·운영 gate까지 통과했다는 뜻이다. 현재 C-2, 모델 worker, delta 계산, backup/restore 훈련은 전자와 후자를 혼동하지 않는다.

## 12. 품질·관측·장애 대응

### 12.1 검증 경로

각 산출물은 입력 hash, producer version, schema_version, run/execution id를 가진다. 모델 기반 결과는 다음 순서로 검증한다.

1. 구조와 필수 필드 검증
2. source locator와 원문 존재 검증
3. 숫자·날짜·요구사항의 결정적 검증
4. claim 간 충돌·누락·범위 검증
5. 실패·모호성의 사람 review 전환

validator 실패는 결과를 자동 보정하지 않는다. report renderer는 승인된 구조화 결과를 결정적으로 렌더링하며 모델에게 HTML이나 최종 판정을 맡기지 않는다.

### 12.2 로그와 감사

로그에는 safe metadata만 남긴다. actor, run/execution, event type, status, hash, model/policy revision, error class를 기록할 수 있지만 secret·API key·원문 첨부·회사자료·전체 모델 응답·내부 object credential은 기록하지 않는다.

감사는 수집·다운로드·변환·모델 전송 승인·실행·검증·사람 피드백·추적 변경·최종 결정을 연결한다. actor 이름만으로 인증이나 권한 부여를 주장하지 않는다.

### 12.3 장애 기본값

| 장애 | 기본 처리 |
|---|---|
| 나라장터 응답 실패 | run 실패·부분 산출물 표시·재수집은 명시적 실행 |
| 첨부 URL/변환 실패 | quarantine/문서 실패 보존·사람 검토 |
| 모델 timeout/transport 오류 | attempt failed·payload/telemetry 보존·자동 fallback 금지 |
| validator 실패 | human review, 자동 보정 금지 |
| worker lease 만료 | stale 상태 확인 후 새 attempt 또는 명시적 재시작 |
| DB/object 불일치 | 복구 실패로 표시하고 정합성 복원 후 재실행 |
| scheduler 장애 | 새 작업 자동 catch-up·무한 retry 금지 |

## 13. 아키텍처 위험과 미해결 항목

현재 남은 위험은 구현 작업과 별도로 추적한다.

- 실제 deep-review corpus와 gold가 부족하여 모델 품질 gate를 닫지 못함
- C-2 운영 입력 625건 manifest의 사람 정답이 부분 상태임
- vLLM artifact digest가 immutable하다는 운영 증거가 부족함
- legacy mutation audit과 screening v3 renderer gap이 남아 있음
- 실제 backup/restore, DB 권한, egress allow/deny 검증과 훈련이 남아 있음
- 담당자 이름이 인증이 아니며 SSO/RBAC가 구현되지 않음
- document preparation/retry UI와 API quota 측정이 남아 있음

재현 조건과 영향은 docs/tracking/findings.md에서 관리한다. 해결되지 않은 구조 문제를 이 문서에서 완료로 표시하지 않는다.

## 14. 변경·확장 규칙

새 기능은 다음 순서로 아키텍처에 편입한다.

1. 업무 용어와 상태 축을 docs/business-rules.md에서 확인한다.
2. REST·파일·DB 소비자 계약을 docs/contracts.md에 먼저 고정한다.
3. 불변성·lineage·migration·object namespace를 설계한다.
4. 외부 전송이면 docs/security.md의 payload·egress·감사 검토를 통과한다.
5. 결정이 바뀌면 상세 ADR을 docs/tracking/decisions/에 추가하고 docs/ADR.md index를 갱신한다.
6. 코드·worker·UI를 기존 subprocess/API 경계에 연결한다.
7. 결정적 validator, 실패 경로, partial artifact, 재시작 경로를 검증한다.
8. 운영 변경이면 docs/operations.md와 실제 backup/restore·권한·네트워크 검증을 갱신한다.

기존 원문·회차·리뷰를 수정하는 migration은 허용하지 않는다. 기존 계약과 다른 의미가 필요하면 새 version 또는 새 namespace를 만들고 이전 계약과의 importer/compatibility 기간을 명시한다.

## 15. 참고 문서

- ADR 통합 색인: docs/ADR.md
- 제품 요구사항: docs/PRD.md
- 업무 규칙: docs/business-rules.md
- API·파일·DB 계약: docs/contracts.md
- 데이터베이스 해설: docs/database-guide.md
- 심층 검토 ERD: docs/deep-review-erd.md
- 입찰 delta·최종 결정 계약: docs/bid-delta-contract-spec.md
- 보안: docs/security.md
- 운영: docs/operations.md
- 표준: docs/standards.md
- 재발 방지 지식: docs/engineering-notes.md
- 현재 상태: docs/tracking/status.md
- 결정 상세: docs/tracking/decisions/
- 미해결 findings: docs/tracking/findings.md
- 보관 문서: docs/legacy/README.md
