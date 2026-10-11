# BidOps 아키텍처

| 항목 | 내용 |
|---|---|
| 문서 상태 | 현재 구조·계약·목표 구조를 통합한 기준 문서 |
| 기준일 | 2026-09-05 (KST) |
| 정본 | docs/ARCHITECTURE.md |
| 제품 | BidOps |
| 관련 문서 | ADR.md, PRD.md, business-rules.md, contracts.md, operations.md (모델 전송 정책은 ADR-0050 완화 항목 참조) |

## 1. 문서의 범위와 읽는 법

BidOps는 기획·사업개발 담당자가 나라장터 발주계획을 조기에 탐색하고, 사전규격 제안요청서를 검토한 뒤 입찰공고까지 추적하는 사내 의사결정 지원 시스템이다. 시스템은 후보를 수집·정리·비교하고 근거를 제시하지만, 추적 승인과 최종 입찰 Go/No-Go는 사람의 결정으로 남긴다.

이 문서는 저장소의 현재 코드, 현재 계약, 승인된 설계와 미구현 목표를 한 문서에서 연결한다. 따라서 설계된 스키마나 화면이 존재한다는 사실을 완성된 운영 기능으로 해석하지 않는다.

상태 표기는 다음과 같다.

- 현재: 저장소에 구현되어 있고 현재 실행 경로의 일부다. 전체 업무 흐름의 운영 완료를 뜻하지 않는다.
- 계약: REST·파일·DB·상태 전이가 고정되어 있다. 구현 또는 운영 승인이 남아 있을 수 있다.
- 실험: 재현 가능한 비교를 위해 실행된 경로다. 제품 품질·운영 활성화 승인을 뜻하지 않는다.
- 목표: 후속 구현 대상이다.
- 보류: 안전·품질·운영 조건이 충족될 때까지 의도적으로 비활성이다.

정확한 필드, 상태값, 경로 및 FK는 docs/contracts.md와 docs/database-guide.md를 우선하고, 결정의 이유와 대안은 docs/tracking/decisions/를 우선한다. 상세 결정 목록은 docs/ADR.md에 모아 둔다.

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
    privatevllm[승인된 사설 OpenAI-compatible vLLM]
    bidops[BidOps]

    planner -->|검색·검토·사람 결정| bidops
    operator -->|실행·승인·장애 확인| bidops
    g2b -->|발주계획·사전규격·입찰공고| bidops
    git -->|회사 프로필 기준선 검증| bidops
    bidops -->|용도별 승인 endpoint로 건별 전송| privatevllm
~~~

나라장터 자료는 외부 원문과 관측 시점을 보존한다. Git은 승인된 회사 프로필 기준선을 검증하는 입력일 뿐, 회사 역량의 자동 증명원이 아니다. 모델 endpoint는 용도(`screening`·`overview`·`deep_review`)별로 승인되고 식별자·선언 revision·prompt·profile hash와 함께 기록된다([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)).

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
    api -->|approved payload / screening purpose| vllm
    analysis -->|approved payload / overview + deep_review purpose| vllm
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
| Analysis worker | overview/deep review/C-2 실행, lease·fence·validation. 세 종류를 한 프로세스가 합성해 **모델 슬롯 1개**를 보장한다 | 무승인 외부 전송, 자동 Go/No-Go |
| Scheduler | 승인된 주기 실행을 enqueue | startup catch-up, 자동 retry, 기본 활성화 |
| PostgreSQL | 메타데이터·관계·상태·감사·정본 리뷰 | 원본 binary의 유일한 저장소 |
| MinIO | raw·attachment·문서·보고서 등 versioned object bytes | 공개 URL 제공, 임의 overwrite |
| ClamAV | quarantine 파일 악성코드 검사 | 파일 승인 판단의 유일한 근거 |

### 4.2 백엔드 모듈 경계

FastAPI backend는 하나의 배포 단위 안에서 한 방향으로만 의존하는 네 모듈과 그것을 조립하는 얇은 계층으로 나뉜다([ADR-0043](tracking/decisions/0043-screening-deep-review-module-boundary.md), [ADR-0045](tracking/decisions/0045-backend-module-layout.md)). 별도 프로세스나 별도 DB로 나누지 않는다.

```text
web/backend/app/
├── core/          db, config, logging_setup, redaction, sql_dialect, constants, db_admin,
│                  generation_config, run_id, api_errors, object_store, clamav,
│                  model_client(용도별 통일 transport), company_profile, model_binding,
│                  schema_base, health
│                  models 2개 (audit_event, idempotency_record)
├── lifecycle/     회차 적재와 기회 identity, 공고·발주계획·사전규격·첨부 메타
│                  api, extensions, ingest/, routers/, services/, schemas/, runtime
│                  models 10개
├── screening/     C-1 공고 판정과 C-2 발주계획 선별
│                  orchestrator/queue/worker/policy/projection/ingest, routers/, services/,
│                  schemas/, workers/order_plan, cli/, runtime
│                  models 28개
├── deep_review/   문서 준비, 사전규격 개요 검토, 심층 검토, 입찰 delta·최종 결정
│                  services/, routers/, workers/, agents/, document_mcp/, contracts/,
│                  policies/, schemas/, cli/, runtime
│                  models 37개
└── main.py, runtime.py, workers/analysis.py, migrations/, alembic/   ← 조립 계층
```

의존은 한 방향으로만 흐른다.

| import 하는 쪽 | 허용 대상 | 금지 |
|---|---|---|
| core | 표준 라이브러리, 외부 패키지 | 모든 도메인 모듈, 조립 계층 |
| lifecycle | core | screening, deep_review, 조립 계층 |
| screening | core, lifecycle 공개 이름 | deep_review, 조립 계층 |
| deep_review | core, lifecycle 공개 이름, screening 공개 이름 중 읽기 전용 seam 함수 | screening 내부 ORM·service, 조립 계층 |
| 조립 계층 | 네 모듈 공개 이름 (+ `alembic/env.py`·migration revision·`app/migrations/import_sqlite.py`는 각 모듈의 `models`) | 모듈 내부 |

- lifecycle의 모델 클래스는 공개 이름이다. screening·deep_review는 `Notice`·`Run`·`OrderPlan`·`Opportunity`·`Attachment` 등을 ORM으로 읽고 join하되, **쓰기와 잠금**은 lifecycle 공개 함수(`ingest_run`, `lock_notice`, `register_manual_attachment` 등)로만 한다.
- deep_review는 screening의 내부를 보지 않는다. `current_judgment`·`current_judgments`·`latest_corrected_grade`·`latest_corrected_grades` **네** 읽기 전용 seam 함수만 쓰며, 그 seam은 함수 안에서 지연 import한다. 넷째(`latest_corrected_grades`)는 `latest_corrected_grade`의 batch 짝이며 2026-09-05에 담당자가 승인했다 — 회차 적재 hot path와 사전규격 목록이 공고 수와 무관한 상수 회 조회를 요구하는데, 건별 seam만으로는 N+1 금지와 동시에 성립하지 않기 때문이다.
- ORM relationship도 import다. lifecycle 모델은 다른 모듈 모델로 향하는 relationship을 갖지 않으며, 관계는 소유 모듈이 자기 모델에서 단방향으로 선언한다. 첨부 삭제 시 `attachment_fetch` 행 제거는 ORM cascade가 아니라 DB FK `ondelete=CASCADE`가 맡는다.

역방향이 필요한 자리는 **lifecycle이 정의한 확장점**으로 뒤집는다. lifecycle은 screening과 deep_review의 존재를 알지 못하고 `app/lifecycle/extensions.py`의 프로세스 전역 registry에 무엇이 등록됐는지만 본다.

| 확장점 | 종류 | 구현 | 제공자가 없을 때 |
|---|---|---|---|
| 공고 판정 | 읽기 projection | screening | 등급·준비·focus 필드가 `null`, 분포·지표는 빈 값. 등급 필터·`sort=grade`는 지원하지 않음 |
| 사전규격 개요·문서 준비 상태 | 읽기 projection | deep_review | 개요 상태 `null`, 문서 상태 건수 0 |
| 회차 적재됨 | 이벤트 hook | screening, deep_review | no-op, 건수 0, 건너뛰었음을 경고로 남김 |
| 추적 결정 변경됨 | 이벤트 hook | deep_review | no-op |
| effective grade 변경됨 | 이벤트 hook | deep_review | no-op. 첨부 취득 자격 재계산과 자동 문서 준비가 일어나지 않는다 |

확장점 등록은 `main.py`가 앱 객체를 조립하는 시점에 한다. lifespan이나 runtime이 아니다 — runtime을 만들지 않는 격리 API 테스트에서도 projection이 있어야 하기 때문이다. 등록은 import와 객체 생성뿐이며 migration·seed·정책 활성화·모델 호출을 하지 않는다.

`deep_review/agents/`는 파이프라인이 아니라 **어댑터 층**이다. `commands.py`(명령 봉투) → `agent.py`(기존 Service 위의 얇은 어댑터) → `projection.py`(순수 투영) 3짝으로 구성되며 `subprocess`·HTTP·모델 호출을 하지 않고 SQLAlchemy `Session`에 묶인다. skill 파이프라인과 이름이 겹쳐 보이지만 경계가 다르다([ADR-0001](tracking/decisions/0001-artifact-boundary.md)).

기동할 모듈은 `BIDOPS_MODULES`(쉼표 구분, 기본값 세 도메인 모듈 전부)로 고른다. core는 항상 포함되므로 `/api/health`는 어떤 조합에도 있다. **의존은 import만, 등록은 지정 모듈만** — 지정 모듈이 의존하는 모듈의 `models`·seam은 import되어 동작하지만 router·runtime·확장점 등록은 지정 모듈에만 한다. 알 수 없는 이름이나 빈 값은 기동 실패다. 운영은 셋 다 등록하며, 모듈 선택은 개발·검증용 기동 옵션이다.

경계는 규율이 아니라 `web/backend/tests/app/test_module_boundaries.py`의 다섯 검사가 강제한다. 다섯째는 형제 모듈이 lifecycle 테이블에 직접 insert·update·delete하거나 `with_for_update()`로 잠그는 자리를 잡는다 — 모델 클래스가 공개 이름이라 import 방향만 보는 검사로는 읽기와 구분되지 않기 때문이다. 허용 목록은 줄어드는 방향만 허용하고, 목록에 있는데 더 이상 위반이 아닌 항목이 남아 있어도 실패한다.

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

### 5.1a 일일 수집 → 선별 적재 → 연결·병합 → 후보 (2026-09-17)

~~~mermaid
flowchart LR
    daily[일일 수집<br/>전일 기준·트랙별<br/>발주계획 1일 / 사전규격·입찰 4일]
    index[수집 색인<br/>전량, 선별 무관]
    select{선별 규칙}
    ingest[사업기회 적재]
    link[공식 키 연결]
    merge{사람 상태 보유 H}
    candidate[사람 확인 후보]
    search[찾아보기/추적 보충]

    daily --> index
    index --> select
    select -->|추적·SW 관련만| ingest
    select -.제외.-> index
    ingest --> link
    link --> merge
    merge -->|0 또는 1| ingest
    merge -->|2 이상| candidate
    index -.나중에 검색.-> search --> ingest
~~~

발주계획·사전규격·입찰공고를 매일 전량 수집해 회차 파일로 보관하고, 모든 수집 레코드를 검색
전용 **수집 색인**(`collected_record_index`)에 한 행씩 남긴다. 그중 추적·SW 관련 레코드만
사업기회로 적재한다(선별 사유 10종, [ADR-0059](tracking/decisions/0059-full-collection-selective-ingest-and-index-search.md)).
1468(소프트웨어사업자) 업종 조회는 수집 필터가 아니라 표시로만 쓴다 — 실측으로 SW 사전규격을
잇는 입찰공고의 29%가 1468 밖임을 확인했다.

공식 키(발주계획 통합번호·사전규격 등록번호·공고번호+차수, 양방향)로 연결되는 자동 병합은
관련 사업기회 중 **사람 상태 보유**(`tracking_status ≠ 미선택` 또는 `recheck_signal_at`)가
1개 이하일 때만 수행하고, 유지 쪽의 사람 선택은 바꾸지 않는다. 2개 이상이면 병합하지 않고
`병합 확인` 후보를 만들어 도착 레코드가 고아로 남지 않게 한다. 후보 수락도 같은 규칙을 쓴다.
SW=Y 사전규격 적재 시 기관·이름이 일치하는 발주계획을 자동 대조하고, 그 밖의 연결은 담당자가
찾아보기로 보관 색인을 검색한다(모델 호출 없음). 상세는
[spec.md](0917_opportunity-tracking/spec.md), [business-rules.md](business-rules.md#전량-수집과-선별-적재2026-09-17)가
정본이다.

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

구조를 저장하는 같은 시점에 결정적 **segment manifest**와 **요구사항 inventory**를 만든다([ADR-0051](tracking/decisions/0051-deep-review-v2-deterministic-subset.md)). append-only이며 identity 키는 `(structure_id, taxonomy_version, extractor_binding_sha256)`다. 규칙이 바뀌면 `rules_sha256`이 바뀌어 새 row가 되고 기존 row를 덮지 않는다. 분류 출처는 `deterministic` 고정, `confidence`는 항상 `null`이며 못 정한 경계는 `needs_human_review`다. 읽기 계약은 `GET /api/document-structures/{structure_id}/segments`이고 응답에 원문 text가 없다. **이 변경 전에 만들어진 구조에는 manifest가 없고 조회가 404다** — `document_block`에 ordinal이 없어 사후 재구성이 불가능하다.

적합성 등급이 `우선 검토`인 사전규격은 이 준비를 자동으로 진행한다([ADR-0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)). 자동 준비는 자기가 만든 초안만 확정하고(`confirmed_by_name == "auto-preparation"`) 사람이 만든 초안은 건드리지 않으며, 등급이 내려가도 이미 만든 묶음을 되돌리지 않는다. 촉발은 회차 적재 hook, effective grade 변경 hook, 첨부 취득 종결 셋이다.

### 5.4 개요·회사 핏·심층 검토

개요 run은 v7의 앞부분 사실 요약과 v8의 사실 요약+예비 판단을 같은 `prespec_overview_run`·analysis-worker slot에서 처리한다([ADR-0065](tracking/decisions/0065-prespec-overview-preliminary-assessment.md)). 로컬 LiteLLM 참조 실행은 v7의 schema·generation·검증·한도를 그대로 둔 별도 불변 정책을 경로로 명시 선택하며 기본 v7을 바꾸지 않는다. v8의 정상 경로는 `원문 범위 + 동등한 관심 축 + 승인된 최소 프로필 → 통합 생성 1회 → 결정적 근거 검사 → 서버 등급 계산`이다. 제외·역할/문맥·수치 위험이 있을 때만 개요 전체와 판단을 의미검증 1회 더 한다. 사실 결과와 판단 결과를 분리해 판단 실패가 유효한 개요를 숨기지 않는다.

읽기 경계도 둘이다. 화면은 lifecycle의 batch `display_assessment` projection으로 사람 정정, 현재 문서의 새 판정/보류, 기존 선별 등급을 우선순위대로 보여 준다. 회사 핏과 자동 시작은 effective grade와 `automation_completed_result`를 계속 사용하며, v8 run은 개요 전체 의미검증 범위가 통과한 경우에만 이 경계로 들어간다. 프런트는 등급을 다시 계산하지 않는다. 기본 정책 경로는 v7이며 v8 정책·migration이 코드에 있다는 사실은 운영 활성화를 뜻하지 않는다.

회사 핏은 검증된 개요 문장과 승인 회사 프로필의 구조화 항목을 짧게 대조한다. `prespec_company_fit_attempt`가 입력/정책 원문·해시·불변 버전과 사유·결과·사용량을 보존한다. 원응답 저장은 개요와 공유하는 암호화 저장 함수를 쓴다. 기존 overview 용도의 모델 설정을 사용하며 회사 핏 모델명은 별도 설정으로 고정한다. 최신 페이지 개요가 있으면 먼저 쓰고 검증 실패는 과거 추출형 개요로 우회하지 않는다. 최신 입력이 없으면 과거 판정을 현재의 자동 시작에 쓰지 않는다. 기본 비활성이며 현재는 명시적인 참조 실행만 지원한다. 자세한 상태·품질 경계는 business-rules와 contracts의 회사 핏 절을 따른다.


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

개요 검토와 심층 검토는 `app/core/model_client.py` 하나를 각각 `overview`·`deep_review` 용도로 묶어 부른다([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)). client는 생성 시점이 아니라 **실행 시점**(`run_claim`)에 용도로 묶이므로 생성은 성공하고 설정 실패는 실행에서 fail closed로 난다. 개요 attempt의 lease는 모듈 상수 1,200초이고 환경변수로 열지 않는다. 합성 analysis worker는 네 종류를 C-2 → 심층 → 회사 핏 → 개요 순서로 하나만 claim한다 — 개요 전용 진입점은 없다.

`SW사업대상=Y`이고 자동 확정된 `ready` 묶음의 개요가 `completed`이며 권고가 `검토 종료`가 아니며 현재 회사 핏 판정이 `matched`이고 활성화/품질 경계를 충족하면, 심층 검토를 시스템 actor로 자동 생성한다(감사 action `deep_review.auto_create`). 생성은 사람 경로와 같은 함수를 쓰고 `actor_kind`만 다르다.

모든 실행은 품질 표식 `quality_status`를 남긴다. `measured`는 측정값이 활성화 게이트를 통과했다는 뜻이고 `unmeasured_reference`·`mock_reference`는 참조 실행이며 표식이 없으면 `null`이다. 참조 실행 결과를 운영 완료·품질 근거·활성화 근거로 집계하지 않는다.

개요 원응답은 `ContentObject`와 `ContentObjectLocation('model-response')`로 암호화 저장되며 attempt와의 직접 FK는 없다. 대조는 감사 이벤트의 `response_sha256`으로 한다.

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

**결정 근거 분리 (2026-09-17, [ADR-0058](tracking/decisions/0058-final-decision-basis-separated-from-comparison.md)).**
비교를 계산하는 worker가 아직 없으므로, `bid_final_decision.basis_kind`가 위 비교 fence
(`comparison`) 또는 모델 호출 없이 수집기가 정규화한 **입찰공고 조건**(`notice_conditions`)
중 하나를 가리키게 해 비교 없이도 결정을 기록할 수 있게 했다. 공고 조건 근거는 authoritative
입찰공고를 차수 순으로 나열하고 차수 간 변경·사전규격 대비를 결정적으로 계산하며, 담당자가
확인한 정확한 공고·관측에 fence를 건다. 두 근거는 같은 append-only·supersession·현재성 규칙을
공유한다. 상세는 [spec.md §9](0917_opportunity-tracking/spec.md#9-최종-gono-go)가 정본이다.

## 6. 논리 데이터 모델과 lineage

### 6.1 PostgreSQL과 MinIO의 역할

PostgreSQL 17의 bidops schema가 운영 메타데이터·관계·상태·감사·리뷰의 정본이다. MinIO는 raw, attachment, document, report와 같은 binary/object bytes를 versioning으로 보존한다. DB row가 object hash·namespace·version과 연결되지 않으면 산출물을 완전한 정본으로 취급하지 않는다.

현재 코드의 Alembic head는 `0020_prespec_company_fit`이며 운영 DB 적용 여부와 구분한다. SQLite는 격리 테스트와 일회성 이전 입력에만 사용한다. 운영 애플리케이션이 startup에서 SQLite로 fallback하거나 create_all로 스키마를 만들지 않는다.

### 6.2 도메인 그룹

현재 DB guide의 업무 사전 기준 73개 table은 다음 영역으로 묶인다.

| 영역 | 수량 | 주요 책임 |
|---|---:|---|
| collection / opportunity | 7 | 수집 회차, 원문 관측, 기회 identity |
| screening / review | 11 | 선별 정책·실행·판정·리뷰 |
| attachment | 3 | 첨부 메타데이터·수명·안전 상태 |
| document | 8 | object·scan·변환·버전·구조·bundle |
| document segment / inventory | 3 | segment manifest·segment·요구사항 inventory 항목 |
| overview / company fit | 7 | 개요 실행·결과·이벤트, PDF 개요, 회사 핏 이력 |
| deep review | 17 | claim·evidence·report·validation·opinion |
| execution / quality / schedule | 12 | job·lease·quality gate·활성화·스케줄 |
| delta / final | 5 | snapshot pair·delta·최종 결정 |
| 합계 | 73 | 업무 사전 기준 |

업무 사전 기준 73개와 ORM `Base.metadata` 기준 79개는 세는 대상이 다르다. 후자에는 문서 사전이 별도 영역으로 세지 않는 표가 함께 들어 있다. 모듈 소유 기준은 core 2 + lifecycle 10 + screening 28 + deep_review 39이다.

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

승인된 사설 OpenAI 호환 모델 연결은 용도(`screening`·`overview`·`deep_review`)별 endpoint·자격증명·선언 revision을 가진다([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)). 기본 vLLM 외의 LiteLLM은 dialect와 불변 정책을 해당 용도에서 명시 선택하고, 승인된 별칭과 metadata의 양의 문맥 한도를 본문 전송 전에 확인한다. MVP 완화 기간에는 허용 host와 선언 revision을 비워 둘 수 있고, 값이 있으면 허용 host 일치와 64자 hex revision 및 metadata 일치를 **모델 본문 전송 전에** 검사한다. 한 용도의 실패는 다른 용도로 새지 않으며 모델 장애가 발생해도 hosted OpenAI로 자동 전환하지 않는다. 원격 overlay와 egress는 필요한 서비스에만 명시적으로 연다.

### 9.3 접근과 보존

현재는 사내망 접근 제한이 기본 경계이고 세밀한 역할 권한은 미구현이다. 앱·worker·migration·read-only backup 역할을 분리하고, backup은 object first 후 DB와 hash를 함께 보존한다. 목표 RPO는 4시간, RTO는 8시간이지만 실제 restore 훈련과 운영 권한 검증이 완료되기 전까지 달성으로 표시하지 않는다.

## 10. 배포 구조

### 10.1 애플리케이션 스택

운영 기준 compose는 docker-compose.yml이다. 기본 network는 내부망이며 외부 호출은 목적별 overlay를 명시한 경우에만 열 수 있다.

| 영역 | 역할 |
|---|---|
| PostgreSQL 17 | 운영 DB |
| MinIO | versioned object store |
| ClamAV | attachment scan |
| web/backend | FastAPI와 정적·관리 API |
| document-worker | 문서 변환·구조화, network disabled |
| analysis-worker | lease 기반 분석, 기본 concurrency 1 |
| init/migrate/minio-init | 명시적 초기화·migration·bucket 정책 |
| overlays | edge(화면 publish), model-egress(모델 egress), c2-order-plan(C-2 입력), prespec-attachment(G2B egress), mock-reference |

host에 열리는 것은 관리 화면 하나이며 `docker-compose.edge.yml`이 그 publish를 소유한다. 기본값은 loopback이고 PostgreSQL·MinIO는 internal network에만 있다. 운영 secret은 환경·secret 파일 계약을 사용하며 이미지·Git·로그에 넣지 않는다.

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
| 개요 검토 | DB/API/UI·계약에 더해 모델 실행 worker와 통일 client 연결까지 존재. 실행 결과는 참조 실행 표식이 붙는다 | 승인 artifact와 사람 gold로 측정한 quality gate |
| 심층 검토 | ERD·계약·worker 구조, 결정적 segment·요구사항 inventory 검증 존재 | 실 corpus/gold, 역할별 분석, 운영 승인 |
| 사전규격 자동 준비·자동 심층 시작 | 등급 기반 자동 묶음과 `SW사업대상=Y` 자동 생성 존재 | 자동 생성된 검토의 실행 경로 결함 해소(findings), 운영 관측 |
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
4. 외부 전송이면 ADR-0050 완화 항목과 payload·egress·감사 검토를 통과한다.
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
- 운영: docs/operations.md
- 표준: docs/standards.md
- 재발 방지 지식: docs/engineering-notes.md
- 현재 상태: docs/tracking/status.md
- 결정 상세: docs/tracking/decisions/
- 미해결 findings: docs/tracking/findings.md
- 공고 판정 런타임: docs/agent/agent-runtime.md, docs/scheduling.md, docs/model-quality-gate.md, docs/e2e-bc-acceptance.md
- 화면 개선: docs/0915_ui-redesign/(재설계 C 정본), docs/design/mockups/(사전규격 검토 시안 참고자료)

### 사용자 요청 Luna 심층검토 (ADR-0069)

사전규격 UI → 미리보기 REST → append-only 입력/승인 → 기존 DeepReview/WorkJob →
합성 worker → 내부 codex-runner → 권위 stage/근거 검증 → 암호화 원응답·설명형 보고서다.
별도 큐 소비자를 만들지 않으며 기존 vLLM transport와 이력은 유지한다.
심층 자동 시작은 기본 off, Luna 요청도 별도 enabled·reference 설정이 필요하다.
runner는 DB·MinIO·저장소 없이 전용 인증 secret만 사용한다.
[계약](contracts.md#사용자-요청-기반-luna-심층검토-adr-0069)과
[적용 절차](0922_luna-deep-review/apply.md)를 따른다.

### 별도 가정 분석 경로 (2026-09-23, 운영 적용 전)

1489번의 확정 문서·회사 프로필에 사용자 가정을 분리한 불변 입력을 승인한 후,
합성 worker가 C-2 → 심층검토 → 가정 분석 → 회사 핏 → 개요 순서로 한 작업만 실행한다.
가정 분석은 기존 Codex runner에 허용 목록 계약 `assumption-stage-v1`을 선택해
세 요청을 보내며 기존 심층검토 계약은 그대로다. 완성/부분 결과와 근거 레지스트리는
별도 REST를 통해 A안 React reader가 읽는다. [작업 정본](0923_assumption-analysis/intent.md).


## 가상 SI 3사 데모 계약 (2026-10-09, DEMO-01·02 데모 브랜치 구현; 2026-10-10 DEMO-03 구현, 실제 Luna 대표 1건은 2026-10-11 DEMO-05로 이관)

회사 identity·추적은 lifecycle, 버전 프로필·지식그래프·회사별 분석은 deep_review가 소유한다. 원문과 v7 개요는 공유하고 결과는 회사 문맥으로 분리한다.
DEMO-01은 별도 데모 브랜치에서 lifecycle 회사 identity·독립 추적과 deep_review의 nullable 회사 계보,
legacy NULL 조회·worker 경계까지 구현했다. Notice·Opportunity 원문은 공유 소유를 유지한다.
DEMO-02는 같은 데모 브랜치에서 core의 순수 온톨로지·원본 validator와 deep_review 소유의 불변 온톨로지·원본·graph version·node·edge·binding·binding event(migration `0035`),
원본 hash에 묶인 profile v2·ProfileEvidence 단일 등록, 명시적 activate CLI, 회사별 profile·knowledge-graph·profile-evidence 읽기 REST를 구현했다.
main·운영에는 미반영이다. `bidops-local`의 승인된 3사 원본 등록·활성화(공통 계약 §10 준비 단계)는 DEMO-03 STEP-007에서 수행했고, 회사별 비교 UI와 실제 인수는 DEMO-04~05 범위다.
DEMO-03(2026-10-10)은 deep_review에 회사별 분석 경로를 추가했다. 순수 `company_knowledge_retrieval`(용어 정규화·concept 매핑·3 hop 경로 검색·경로 상한·필수 사실·coverage·slice), `company_analysis_input`(CompanyAnalysisInput·FrozenProvenance builder, 공고 ready bundle 문서 집합), `company_source_units`(심층·핏 공용 분할기 unit과 inventory 엄격 일치),
`company_fit_policy`(v2 이력·v3 `source_characters`, 새 enqueue는 v3만)·`company_fit`(enqueue CLI, 2026-10-11부터 ready bundle 필수·개요 행 evidence page의 분할기 unit 연결, v2 결과 검증)·`company_fit_runner` 회사 분기(동결 입력과 저장된 정책 행만, `overview` 용도 LiteLLM `local-agent-main`, 심층 자동 시작 없음), `company_deep_review`(회사 preview/승인/생성/재시도·현재성), `company_slices`(stage별 회사 slice·검증), `company_projection`(회사 읽기·비교 projection), 라우터 `company_analysis`(쓰기)·`company_reads`(읽기·비교).
회사 심층은 기존 DeepReviewPreview/Approval/DeepReview에 `company_id`·`graph_version_id`·`provenance_jsonb`를 더해 재사용하고 기존 공용 analysis-worker 슬롯이 `BIDOPS_DEMO_ENABLED`일 때만 회사 job을 claim한다. worker는 승인 preview의 동결 입력만 쓰며(`approved_company_input`: 승인·preview·review 회사 일치, 계보·hash·nonce 일치, 생성 audit 회사 키, pinned bundle 재분할 일치) 어긋나면 `approval_invalid`로 호출 0, 회사 행↔demo 정책 identity 불일치는 `company_policy_invalid`다.
lifecycle은 공개 함수 `company_pre_spec_notices`·`company_tracking_views`만 제공하고 deep_review를 import하지 않는다. migration은 `0036_company_analysis` 하나(`company_fit_policy_version` 신설, 핏 attempt 정책 FK 분리·`graph_version_id`·`provenance_jsonb`·동결 입력 일치 insert guard, deep_review graph 계보·불변 trigger, preview/approval 회사 열)이며 권한은 `scripts/runtime-privileges.sql`(worker는 지식 테이블 SELECT만, binding_event 제외)에 있다. 실제 Luna 대표 1건과 운영·main 반영은 미수행이다.
[ADR-0070](tracking/decisions/0070-multi-company-knowledge-demo.md) · [공통 계약](work/demo-contract.md) · [기능 로드맵](work/constitution/roadmap.md).
