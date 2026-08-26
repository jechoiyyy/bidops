# BidOps 아키텍처

이 문서는 현재 구현된 T14 통합 경계를 설명한다. BidOps는 공고를 수집하고 근거가 연결된 판단 초안을 만드는 의사결정 지원 도구다. 입찰 제출, 발주기관 연락, 최종 Go/No-Go, 알림·SSO, 첨부 심층 검토를 수행하지 않는다. OpenAI 폴백도 없다.

관련 계약은 [에이전트 런타임](./agent-runtime.md), [스케줄링](./scheduling.md), [모델 품질 게이트](./model-quality-gate.md), [외부 인터페이스 계약](./contracts.md), [운영 절차](./operations.md), [구현·검증 표준](./standards.md)에 있다.

## 경계와 소유권

```text
skills/* (수집·표본·병합·보고 파일 계약)
        │ subprocess / UTF-8 JSON·YAML
        ▼
FastAPI API ── SQLAlchemy/SQLite ── Alembic migrations
        │                         │
        │                         ├─ immutable policy/profile/gate bindings
        │                         └─ queue, attempts, schedules, audit
        ▼
Runtime worker ── Ollama (qwen3.8:27b, think=false)
        │
        ├─ screening-input / decisions / failures / telemetry
        └─ deterministic merge → derived run (full run only)

APScheduler (Asia/Seoul clock only) ── durable reservation ── same queue
```

- `skills/bidops-collect`, `skills/bidops-screen`, `skills/bidops-report`는 파일 계약을 소유한다. 웹 계층은 스킬 내부 함수를 import하지 않고 subprocess와 파일을 통해 호출한다.
- `web/backend/app`은 API, DB 상태, 대기열·워커, 결정적 검증·병합, 산출물 경로를 소유한다. 프론트엔드는 API만 사용하며 DB·`data/runs`·첨부 루트를 직접 읽지 않는다.
- APScheduler는 시계를 깨우고 고정된 기간을 예약하는 경계다. 판정 단계나 모델 호출을 소유하지 않는다. 수동·CLI·품질 게이트·스케줄 트리거는 모두 같은 DB FIFO로 들어간다.
- SQLite가 상태의 정본이다. 애플리케이션 시작은 `init_db()`로 현재 Alembic revision과 schema presence만 읽어 확인한다. migration, `create_all`, portal seed, policy seed는 시작 시 수행하지 않는다. fresh migrated DB에는 schedule/always-on 기본 singleton과 deterministic migration audit event가 생기며 `screening_policy`·`agency_portal`은 0행이다. seed/portal 등록은 운영자 명령/API로 별도 실행한다.

## 데이터 흐름

1. 수집기가 `data/runs/<run_id>/collected-notices.json`과 원문·경고를 만든다. 표본기는 별도로 `validation-set.json`을 만들며, 정기 판정 전체 입력을 표본으로 줄이지 않는다.
2. 오케스트레이터가 공고·기간·정책·프롬프트·프로필 식별자를 동결하여 `data/screening-executions/<execution_id>/screening-input.json`을 만든다. 스냅샷은 `bidops.screening-input.v1`이다.
3. 실행 행은 모델·정책·프롬프트·프로필 버전과 digest, 입력 digest, artifact 디렉터리를 함께 저장한다. 워커는 호출 직전에 이 바인딩과 Ollama 모델 digest를 다시 확인한다.
4. 워커는 한 번에 하나의 execution만 claim한다. 공고별 성공 판정은 `screening-decisions.json`(`bidops.decisions.v3`), 실패는 `screening-failures.json`(`bidops.screening-failures.v1`), 호출 계측은 `screening-telemetry.jsonl`(`bidops.screening-telemetry.v1`)로 기록한다.
5. 모든 공고가 성공한 full run만 새 파생 회차 디렉터리 `data/runs/<source.name>--screen-<UTC YYYYmmddHHMMSS>-<8hex>/`에 발행한다. 원 회차·원문·리뷰·파일은 수정하지 않는다. 일부 성공은 `부분 성공`으로 남고 실패 공고를 조용히 정본에 넣지 않는다. single notice와 quality sample은 experiment artifact로만 남는다.

## 불변 바인딩

### 회사 프로필

정식 경로는 `docs/reference/company-profile.md`다. 이 파일은 이 작업에서 수정하지 않는다. `current`는 실행 시점 working-tree bytes를 SHA-256으로 저장하고 `web/data/profile-snapshots/<sha256>.md`에 복사한다. 버전은 `company-profile.sha256:<64hex>`다.

비교용 `git:<40hex>`는 승인된 commit `ee621835db934ddac944f7a07a986ed0b73ecc7a`의 정식 경로만 허용한다. Git이 있으면 blob을 읽고 vendored baseline과 일치하는지 확인한다. Git executable/repository가 없을 때만 `web/backend/app/screening/baseline_company_profile.md`를 사용하며, 허용 digest `a231ab54c36031a7e72779bbca550f70561dc0c946dc5544eeb930c7c6149de2`와 일치해야 한다. mismatch는 성공 입력이 아니다.

컨테이너의 `git` wrapper는 이 정확한 `git -C /app show ee621835db934ddac944f7a07a986ed0b73ecc7a:bidops-agent/docs/reference/company-profile.md` 요청을 vendored bytes로 응답하고 나머지는 실제 Git에 위임한다.

### 정책·프롬프트·모델

정책 body와 prompt는 저장 시 새 immutable version을 만든다. 실행은 policy version, prompt version, model name/version·digest를 저장하며 완료 회차의 참조를 바꾸지 않는다. 기본 모델은 정확히 `qwen3.8:27b`다. Ollama `/api/tags`에서 실행 시 확인한 model digest(64 lowercase hex)가 실행에 묶인다. `think=false`, `stream=false`를 사용하며 BF16·OpenAI 대체 경로는 없다.

정책 상태는 `draft`, `activation_candidate`, `active`이고 active는 최대 하나다. 기본 seed는 `python -m app.screening.policy seed-default --created-by system-bootstrap`을 운영자가 실행할 때만 만들어진다. 시작·migration·container entrypoint는 policy/portal seed를 하지 않는다.

### 품질 게이트

게이트는 고정 40건으로 A/B 두 번을 독립 실행한다. 비교 목적은 역사적 Git 프로필만, 운영 승인 목적은 current snapshot만 허용한다. 게이트가 pass여도 정책 activation과 always-on을 자동 수행하지 않는다. 자세한 분리 규칙은 [모델 품질 게이트](./model-quality-gate.md)를 따른다.

## 실행 슬롯과 상태

`screening_execution.queue_no`가 모든 `cli_single`, `manual_run`, `quality_gate`, `schedule` 작업의 FIFO 순서를 정한다. SQLite `BEGIN IMMEDIATE` claim과 `active_slot=1` partial unique index가 마지막 경쟁을 막고, `BIDOPS_SCREEN_MAX_CONCURRENCY=1`은 고정이다. 실행 중 heartbeat가 기본 60초보다 오래되면 시작·claim 때 `중단됨`/`process_interrupted`로 회수하며 자동 재개하지 않는다.

실행의 주요 상태는 `대기`, `실행 중`, `중지 요청`, `성공`, `부분 성공`, `실패`, `중단됨`이다. stop 요청은 대기 행을 즉시 중단하고 실행 중 행은 현재 blocking HTTP 호출이 끝난 뒤 중단한다. 성공 공고는 실패 공고와 분리해 보존하고, 중단 실행은 발행하지 않는다. 상세한 7-span 및 재시도 규칙은 [에이전트 런타임](./agent-runtime.md)에 있다.

## 스케줄과 상시 운영

APScheduler 3.11 계열은 in-process clock이다. 시간대는 `Asia/Seoul`, 초기 기본 시각은 daily `02:00`, weekly Monday `06:00`이다. durable `schedule_reservation`이 기간별 승자를 한 번만 정하고, duplicate reservation은 `건너뜀` 실행과 audit를 남긴다. 재기동 catch-up은 예약 누락 기간만 오래된 순서로 보충하며 기존 실패·부분 성공을 자동 재시도하지 않는다.

스케줄러 등록은 `BIDOPS_SCHEDULER_ENABLED=true`일 때만 한다. worker는 이 값과 관계없이 시작한다. 상시 운영은 환경 cap, DB `always_on_state.enabled`, active policy, 최신 passing `operational_approval`의 정확한 model/profile/current binding을 모두 만족해야 한다. 환경·DB 스위치는 기본 false다. T14/T15는 operator direction 없이 activation이나 always-on을 수행하지 않는다. [스케줄링](./scheduling.md)에 catch-up·복구·감사 규칙을 정리했다.

## 저장·보안 경계

- SQLite는 WAL과 foreign keys를 켠다. 현재 head는 `0005_generation_config_binding`이며 앱은 자동 migrate하지 않는다. backup manifest를 보존한 명시적 migrate와 `db-verify`를 운영자가 수행한다.
- artifact 경로는 알려진 파일명, symlink 거부, root escape 검사를 통과해야 한다. API는 내부 저장 경로를 조합하게 하지 않고 허용된 artifact endpoint만 노출한다.
- `.env`, API key, Ollama credential, 원문 첨부와 run data를 image·Git에 넣지 않는다. web container는 root로 실행하지 않고 UID/GID bind mount 권한을 검사한다.
- Docker Python runtime은 `web/backend/requirements.lock`의 exact transitive pins만 설치한다. visual은 remote Google Fonts를 차단하고 image local fonts로 고정한다.
- 모델 prompt/response body는 오류·audit/log에 기록하지 않는다. telemetry에는 trace/span과 호출 메타데이터만 둔다.
- health는 `GET /api/health`의 내부 lightweight 응답이며 Ollama나 외부 수집 API를 확인하지 않는다.

운영자의 중지→backup→명시적 migrate→verify→seed→web health→단 한 번의 live smoke 순서는 [운영 절차](./operations.md)에 고정되어 있다.
