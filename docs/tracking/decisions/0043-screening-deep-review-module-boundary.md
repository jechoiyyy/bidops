# 선별과 심층 검토를 한 배포 단위 안의 독립 모듈로 가른다

- 상태: 채택
- 일자: 2026-09-03

## 맥락

1차 분류(선별)와 심층 검토를 각각 독립한 서비스로 두고 개별로도 사용할 수 있게 한다는
제품 목표가 있다. 이 목표가 현재 구조에서 얼마나 떨어져 있는지 2026-09-03에 실측했다.

### 두 도메인의 실제 결합도

`app/screening`, `app/services/order_plan_screening.py`, `app/workers/order_plan_screening.py`,
`app/routers/{screening,order_plans,quality_gates}.py`를 선별 쪽으로,
`app/agents`, `app/services/{deep_reviews,deep_review_validation,document_bundles}.py`,
`app/workers/{deep_review,document}.py`, `app/routers/{deep_reviews,document_bundles}.py`를
심층 쪽으로 두고 `app/models.py`의 declarative 테이블 42개를 대조했다.

| 항목 | 실측 |
|---|---|
| 선별 ↔ 심층 코드 교차 import | 0건 |
| 두 도메인이 공유하는 service 모듈 | 0개 |
| 선별 전용 테이블 | 21 |
| 심층 전용 테이블 | 21 |
| 실제 공유 테이블 | 4 |

공유 4개 중 `AuditEvent`와 `IdempotencyRecord`는 인프라 횡단 관심사다. 도메인 결합은
둘뿐이다.

- `Notice` — 두 도메인의 공통 앵커. 심층은 `notice_id`로 조회한다
  (`services/deep_reviews.py:410`, `services/document_bundles.py:82,453,669,750`).
- `Judgment` — `services/document_bundles.py:677`에서 `notice_id`로 조회하는
  **단방향 읽기 1곳.** 선별의 산출물을 심층이 읽는 지점이며, 이것이 두 도메인의
  유일한 seam이다.

첫 측정에서 `Claim`과 `Review`도 공유로 잡혔으나 docstring 안의 영어 동사였다
(`screening/queue.py:652` "Claim only the oldest queued row",
`screening/worker.py:245` "Claim, verify, process and finish one execution",
`screening/quality_gate.py:2060`의 주석 "Review"). 실제 ORM 참조가 아니므로 제외했다.
grep 기반 측정이므로 이후 재측정 시 같은 오탐에 주의한다.

### `app/agents/`의 소속

`app/agents/`(5,420줄)는 파이프라인이 아니다. `subprocess`·HTTP·모델 호출이 0건이고
SQLAlchemy `Session`에 묶여 있다. 세 슬라이스 모두 심층 검토 도메인이다.

- `agents/deep_review/agent.py:1` — "Thin DeepReviewAgent adapter over `DeepReviewService`"
- `agents/document_preparation/agent.py:1` — "DocumentPreparationAgent adapter over
  `DocumentBundleService`"
- `agents/decision/agent.py:1` — "Thin DecisionAgent adapter over the existing report
  service". 참조 테이블은 `DeepReview`, `EvidenceRef`, `FinalOpinion`, `ReportRevision`,
  `ValidationRun`, `ValidationCheck`로 전부 심층 검토 소속이다.

`commands.py`(명령 봉투) → `agent.py`(기존 Service 위 어댑터) → `projection.py`(순수 투영)
3짝은 유지할 만한 형태다. 문제는 이 묶음이 최상위에 떠 있어 이름만으로 파이프라인처럼
읽힌다는 점이고, `docs/`에 이 레이어를 설명하는 문장이 없다는 점이다.

### 목표를 막는 것

교차 의존이 이미 0인데도 "두 서비스"라고 말할 수 없는 이유는 세 가지다.

1. **`app/models.py`가 3,719줄 단일 파일에 42개 테이블을 담는다.** 선별 21·심층 21·공유 4가
   한 파일에 섞여 있어 어느 모듈도 자기 테이블을 소유하지 못한다. 가장 큰 병목이다.
2. **폴더가 기술 축(`routers/`·`services/`·`workers/`)으로 흩어져 있어** "이 서비스의 코드
   전부"를 한 경로로 가리킬 수 없다. `deep_review`는 5곳에 나뉘어 있다.
   반면 `app/screening/`은 이미 정책·큐·워커·프롬프트·계약을 한 폴더에 모은 수직 슬라이스다.
   같은 저장소 안에서 두 규칙이 공존한다.
3. **경계를 지키는 장치가 없다.** 현재 교차 import 0건은 규율의 결과이지 강제의 결과가
   아니다.

## 결정

선별과 심층 검토를 **하나의 배포 단위 안에서 서로를 import하지 않는 두 모듈**로 가른다.
별도 프로세스·별도 DB로 나누지 않는다.

### 1. "개별로도 사용 가능"의 정의

다음 다섯 가지를 충족하면 목표를 달성한 것으로 본다.

1. 각 모듈이 자기 테이블을 소유하고 상대 모듈을 import하지 않는다.
2. 각 모듈이 CLI로 웹 없이 단독 실행된다. `screening/cli.py`와 `cli/run_bc_e2e.py`가
   이미 그 진입점이다.
3. 상대 모듈의 라우터를 등록하지 않아도 앱이 기동한다.
4. 각 모듈의 테스트가 상대 모듈 없이 통과한다.
5. 공유 커널을 통하지 않은 교차 접근이 테스트로 차단된다.

### 2. 모듈 경계

```text
app/
├── core/          Notice, Judgment, Run, Opportunity, AuditEvent, IdempotencyRecord
│                  db.py, config.py, logging_setup.py, redaction.py
├── screening/     Screening*, OrderPlanScreening*, QualityGate*, CompanyProfileSnapshot 등 21
│                  router / service / worker / policy / queue / orchestrator / cli / contracts
├── deep_review/   DeepReview*, Claim, EvidenceRef, ValidationRun·Check, DocumentBundle*,
│                  ReportRevision*, FinalOpinion 등 21
│                  router / service / agents / worker / cli / contracts
└── main.py        두 모듈의 라우터를 조립만 한다
```

`app/agents/`는 `deep_review/agents/`로 옮긴다. 모듈 맥락 안에 놓이면 이름의 모호함이
사라지므로 `commands`/`agent`/`projection` 3짝 구조는 그대로 둔다.

### 3. seam 계약

`services/document_bundles.py:677`의 `Judgment` ORM 직접 조회를 선별 모듈이 노출하는
읽기 전용 함수 하나로 대체한다. 심층 검토는 선별의 테이블을 직접 읽지 않는다.

방향은 **선별 → 심층 단방향**이다. 선별은 심층의 어떤 것도 참조하지 않는다.
이 seam은 [ADR-0030](0030-opportunity-tracking-state.md)의 추적 상태와 별개다.
적합성 등급·참여 준비·추적 선택·최종 Go/No-Go가 서로를 대신하지 않는다는 경계는 그대로다.

### 4. 순서

각 단계는 앞 단계의 동작을 바꾸지 않는다.

1. seam 고정 — `Judgment` 직접 조회를 읽기 전용 함수로 교체.
2. 경계 강제 테스트 추가 — `screening`이 `deep_review`를 import하면 실패한다.
   교차 import가 0인 지금 넣어야 이후 이주가 안전하다.
3. `models.py` 분할 — 42개를 core 6 / screening 21 / deep_review 21로.
4. 폴더 이주 — router·service·worker·agents를 모듈 폴더로. 로직 변경 없음.
5. 단독 실행 확인 — CLI 실행과 라우터 미등록 기동.

Alembic은 단일 체인을 유지한다. `alembic/env.py:18`의 `from app import models`가 모든
declarative 테이블을 등록하는 구조이므로 import 경로만 맞추면 되고, 기존
`tests/test_alembic_autogenerate.py`가 분할 전후로 빈 diff를 확인해 준다.

## 대안과 기각 이유

- **별도 프로세스·별도 DB의 독립 서비스로 나눈다.** 기각했다. 관측 규모가 발주계획 1주
  약 2,000건으로 별도 배포 단위를 정당화하는 부하가 아니다. 현재 애플리케이션에는
  로그인·역할 권한이 없고 사내망 접근 제한이 경계이므로([ADR-0009](0009-name-attribution-intranet.md))
  서비스 간 인증을 새로 설계해야 한다. 공유 앵커가 `Notice` 하나뿐이어서 DB를 나누면
  그 하나 때문에 분산 조회·동기화가 생긴다. 미구현 흐름(재시작 화면, 입찰 delta 추적,
  SSO, 알림)이 남아 있어 지금 배포 단위를 늘리면 이후 모든 기능의 비용이 늘어난다.
  위 모듈 경계는 이 선택으로 가는 길을 막지 않는다. 필요해지면 seam이 이미 확정돼 있다.
- **`app/agents/`를 `skills/`로 옮겨 파이프라인과 합친다.** 기각했다. `skills/`의 계약은
  독립 실행 스크립트·subprocess·파일 in/out·DB 없음인데
  ([ADR-0001](0001-artifact-boundary.md)), `app/agents/`는 SQLAlchemy 세션과 ORM에 직접
  묶여 있다. 옮기려면 프로세스 경계 너머로 DB 세션을 넘겨야 하고, 그러려면 파이프라인이
  웹 DB 내부를 알게 되어 [2.3 파이프라인과 웹의 경계](../../ADR.md)를 역방향으로 위반한다.
- **현행 유지.** 기각했다. 교차 의존이 0인 상태는 지금 강제되지 않으므로 기능이 늘면
  깨진다. `models.py` 단일 파일은 모든 기능이 같은 파일을 건드리게 만들어 병합 충돌과
  리뷰 비용을 상수로 만든다.

## 결과

- 이 결정은 **구조 경계**만 정한다. 어느 모듈의 운영 활성화도 뜻하지 않는다. 선별의 상시
  운영은 [ADR-0017](0017-human-enabled-quality-gate.md)의 품질 게이트와 사람의 활성화를
  그대로 따른다.
- 모듈을 나눠도 `Notice`는 공유 테이블로 남는다. 두 모듈이 같은 행을 갱신할 수 있으므로
  `services/deep_reviews.py:410`의 `with_for_update()` 같은 잠금 경로는 이주 후에도
  유지한다.
- 선별 내부에는 C-1(공고)과 C-2(발주계획)의 모델 호출 경계가 서로 다르다는 별도 문제가
  있다. C-2는 `config.py:293,295`가 `skills/bidops-screen/scripts/`를 subprocess로
  호출하는데, C-1은 `screening/orchestrator.py:1554`에서 웹 프로세스 안의 `OllamaClient`를
  직접 만든다([ADR-0013](0013-screening-orchestrator-boundary.md)의 판정 단계 전환 결과다).
  이 불일치는 이 ADR의 범위가 아니며 `findings.md`에 남긴다.
- 운영 백엔드가 `experiments/`를 런타임 의존하는 문제(`config.py:286,288`,
  `ingest/loader.py:4199,4208`가 `experiments/order-plan-screening/config/`의 정책·binding을
  읽는다)는 이 결정과 독립이며 별도로 처리한다. 모듈 이주 시 이 경로를 그대로 옮기지
  않는다.
- `docs/ARCHITECTURE.md`에 `agents` 어댑터 레이어를 설명하는 문장이 없다. 이주와 함께
  추가한다.
- 4번의 폴더 이주는 import 경로를 광범위하게 바꾼다. 1·2번을 먼저 끝내 경계가 테스트로
  고정된 뒤에 진행한다.
