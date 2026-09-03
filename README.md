# BidOps

기획·사업개발 담당자가 나라장터 **발주계획을 조기에 탐색**하고, **사전규격 제안요청서를 검토**한 뒤
**입찰공고까지 추적**하도록 돕는 사내 의사결정 지원 시스템이다.

관측 규모는 발주계획 3일 약 1,200건, 1주 약 2,000건이며 Python 파이프라인과 FastAPI·React 관리
화면으로 처리한다.

**자동 입찰, 발주처 연락, 추적 승인, 최종 Go/No-Go는 사람이 결정한다.** 시스템은 근거를 모아
보여줄 뿐 결정을 대신하지 않는다.

## 사람이 내리는 네 가지 결정

이 제품은 조회 도구가 아니라 사람이 네 번 결정하는 파이프라인이다. 네 결정은 서로를 대신하지
않으며, 이를 하나의 조작으로 합치는 설계는 요구사항 위반이다.

| 결정 | 내용 | 규모와 주기 | 주 화면 |
|---|---|---|---|
| 1 | 발주계획 후보 선별 | 3일 약 1,200건 · 주 2회 | 발주계획 C-2 |
| 2 | 심층 추적 승인 | 사전규격 단위 | 사전규격 |
| 3 | 공고 1차 판정과 담당자 리뷰 | 회차당 표본 약 120건 | 검토 대기열 |
| 4 | 최종 입찰 Go/No-Go | 사업기회 단위 · **되돌릴 수 없음** | 입찰 변경 비교 |

## 저장소 구조

```text
bidops/
├── AGENTS.md, CLAUDE.md        작업 진입점(내용 동일)
├── docker-compose.t7.yml       PostgreSQL·MinIO 기반 애플리케이션 스택
├── docker-compose.t7.*.yml     목적별 egress·모델 overlay
├── run-tests.sh                파이프라인 단위·교차 테스트
├── data/, reports/             불변 회차 입력과 파생 보고서
├── docs/                       계약·업무 규칙·운영 절차(아래 표 참조)
├── skills/                     수집 · 1차 판정 · 보고서 렌더링 파이프라인
└── web/
    ├── backend/                FastAPI · PostgreSQL · 객체 저장소 · worker
    └── frontend/               React 19 관리 화면
```

## 문서 지도

작업 전에 읽어야 할 순서대로다.

| 문서 | 내용 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | 작업 진입점과 강제 게이트 |
| [`docs/architecture.md`](docs/architecture.md) | 현재 구조와 목표 데이터 흐름 |
| [`docs/business-rules.md`](docs/business-rules.md) | 생애주기·선별·심층 검토 상태 규칙 |
| [`docs/contracts.md`](docs/contracts.md) | REST·파일·DB 소비자 계약 |
| [`docs/security.md`](docs/security.md) | 접근·민감정보·모델 전송·감사 정책 |
| [`docs/standards.md`](docs/standards.md) | 구현·검증 강제 기준 |
| [`docs/operations.md`](docs/operations.md) | 설치·실행·백업·복구 절차 |
| [`docs/engineering-notes.md`](docs/engineering-notes.md) | 증상별 재발 방지 지식 |
| [`docs/PRD.md`](docs/PRD.md) · [`docs/PLAN.md`](docs/PLAN.md) | 현재 착수 범위의 요구와 순서 |
| [`docs/design/`](docs/design/) | 화면 개선 요구·계획·결정과 시안 |
| [`docs/tracking/`](docs/tracking/) | 현재 상태 · 미해결 문제 · 결정 기록 |

`docs/legacy`는 완료·미채택 계획의 보관소다. **실행 진입점으로 삼지 않는다.**

## 화면을 직접 확인하기

### 1. 목 데이터로 화면만 보기 (Docker 불필요)

백엔드·DB 없이 시각 회귀와 같은 목 픽스처로 실제 화면을 띄운다. 화면 구조와 동선을 확인하는
가장 빠른 방법이다.

```bash
cd web/frontend
npm ci                                  # 최초 1회
BIDOPS_PREVIEW=1 npx playwright test tests/preview.manual.spec.ts \
  --headed --project=laptop --grep "발주계획"
```

브라우저가 열린 채 멈춘다. 직접 클릭해 보고 Playwright Inspector의 **Resume**를 누르면 끝난다.

- `--grep`으로 화면을 고른다: `발주계획` · `사전규격 목록` · `사전규격 상세` · `입찰 변경 비교` · `대시보드`
- `--project`로 폭을 고른다: `laptop`(1024×768) · `desktop`(1440×900) · `tablet` · `mobile`
- 이 harness는 `BIDOPS_PREVIEW`가 없으면 skip되므로 전체 테스트 실행과 CI에 영향을 주지 않는다

목 데이터는 화면 계약을 보여주기 위한 가상 값이며 **운영 사실이나 확인된 회사 역량이 아니다.**

### 2. 실제 스택 기동

실제 데이터 흐름까지 확인할 때 쓴다. Docker Engine과 Compose가 필요하다.
전체 절차와 전제 조건은 [`docs/operations.md`](docs/operations.md)가 정본이며, 아래는 요약이다.

```bash
cp .env.example .env                    # 실제 비밀은 secret manager에서 주입한다
export COMPOSE_PROJECT_NAME=bidops-deep-review-t7
docker compose -f docker-compose.t7.yml build
docker compose -f docker-compose.t7.yml up -d postgres minio clamav
./scripts/init-runtime.sh               # DB 역할·migration·MinIO 버킷 초기화
docker compose -f docker-compose.t7.yml up -d web document-worker analysis-worker
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
```

외부 모델 없이 전체 흐름을 보려면 결정적 목 provider overlay를 얹는다.

```bash
docker compose -f docker-compose.t7.yml \
  -f docker-compose.t7.mock-reference.yml up -d
```

기동 전 확인할 것.

- `.env`의 `BIDOPS_UID`·`BIDOPS_GID`를 0이 아닌 host 계정과 맞춘다
- PostgreSQL 5개 역할과 MinIO 자격증명의 비밀번호를 서로 다르게 설정한다
- 회사자료 3개 파일이 regular file로 존재해야 한다(없으면 Docker가 디렉터리를 만들어 비정상 실패한다)

```bash
test -f docs/reference/company-profile.md
test -f docs/reference/company-performance-titles.tsv
test -f web/backend/app/screening/baseline_company_profile.md
```

앱 startup은 migration·seed·정책 활성화·모델 호출을 **하지 않는다.** 스케줄러와 상시 운영은
기본 비활성이다. 프로필 화면은 승인된 snapshot이 있어야 열리므로 신규 배포에서는 회차 판정을
한 번 실행한 뒤에 사용한다.

## 검증

세 스위트를 모두 host에서 돌린다.

```bash
./run-tests.sh                          # 파이프라인 단위·교차
cd web/backend && .venv/bin/python -m pytest tests/ -q
cd web/frontend && npx tsc -b && npm run build && npm run test:visual
```

주의할 점 셋.

- `pytest tests/<파일>`처럼 개별 파일만 지정하면 PostgreSQL harness가 뜨지 않아 postgres 테스트가
  **조용히 skip된다.** 반드시 디렉터리 전체를 지정한다.
- `npm run test:visual`은 visual spec만이 아니라 **전체 Playwright spec**을 돌린다.
- 부하 의존 flake가 양쪽에 있고 프론트엔드는 실패 지점이 실행마다 옮겨 다닌다. 전체 실행의 실패는
  **단독 재실행과 전체 재실행으로 확인한 뒤에만** 회귀로 판단한다. 단
  `strict mode violation`은 타이밍이 아니라 DOM 사실이므로 flake가 아니다.

## 기여할 때 지켜야 하는 것

[`CLAUDE.md`](CLAUDE.md)의 강제 게이트가 정본이며 요약하면 다음과 같다.

- 확인되지 않은 회사 역량·자격·실적과 공고 사실을 추정하지 않는다. `unknown`과 `null`은 검증 대기
  상태로 **보존한다.** 빈칸이나 `0`으로 바꾸지 않는다
- 적합성 등급, 참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go가 서로를 대신하지 않는다
- 모델의 숫자·요구사항·근거는 원문 위치와 연결하고 결정적 검증을 통과시킨다. 실패는 사람 검토로
  보내며 자동 보정하지 않는다
- 기존 파이프라인은 subprocess·버전 파일 계약으로 연결한다. 웹에서 업무 규칙을 복제하지 않는다
- 외부 모델은 승인된 payload만 건별 전송한다. 운영 장애 때 hosted OpenAI로 자동 fallback하지 않는다

첨부 원문의 허용 경로 이탈, API 키·회사자료의 로그·응답 노출, 승인 없는 외부 모델 전송, 회차 원본
덮어쓰기, 원문과 다른 모델 근거의 검증 통과를 발견하면 **관련 실행을 중지하고 즉시 보고한다.**
지금 범위에서 해결할 수 없는 구조 문제는 [`docs/tracking/findings.md`](docs/tracking/findings.md)에
재현 조건·영향·후속 방향과 함께 기록한다.

## 현재 상태

- PostgreSQL 17 `bidops` schema와 versioned MinIO가 운영 정본이다. SQLite는 격리 테스트와 일회성
  이전 입력에만 쓴다
- 현재 애플리케이션에는 **로그인·역할 기반 권한이 없다.** 사내망 접근 제한이 경계이고 담당자 이름은
  감사 표식일 뿐 인증이 아니다
- 발주계획·사전규격 중심 신규 흐름, 준비·실패 재시작 화면, 입찰 delta 추적, SSO, 알림은 아직 구현 전이다
- 구현과 검증의 현재 상태는 [`docs/tracking/status.md`](docs/tracking/status.md)를 본다
