# BidOps

나라장터 발주계획 탐색부터 사전규격 검토, 입찰공고 추적까지 잇는 사내 의사결정 지원 서비스입니다.

기획·사업개발 담당자가 검토할 사업을 찾고, 제안요청서 요구사항과 회사 근거를 함께 보고, 추적 여부와 최종 입찰 참여 결정을 기록합니다. 시스템은 수집·선별·분석을 돕습니다. 발주처 연락, 추적 승인, 최종 Go/No-Go, 입찰 실행은 사람이 합니다.

## 주요 기능

| 업무 | 지원 기능 |
|---|---|
| 오늘 할 일 | 한 화면 요약, 날짜별 마감 일정, 수집 상태 |
| 사업 탐색 | 발주계획·사전규격·입찰공고 수집, 발주계획 선별(C-2)과 검토 |
| 문서 검토 | 첨부 취득·악성코드 검사, HWP/HWPX·PDF 문서 준비, 개요와 원문 근거 |
| 회사 핏 | 사전규격 개요를 회사 사업 범위 카드와 대조해 `matched`를 추천으로만 표시 |
| 분석 엔진 | 사람이 추적을 시작하거나 `분석 요청`을 누른 사전규격만, 공고별 미리보기 승인 뒤 분석 |
| 사업 추적 | 사업기회 연결, 추적·보류·종료, 활동·노트, 최종 Go/No-Go |
| 운영 관리 | 실행 상태·감사 기록, 선별 정책·품질 게이트 |

품질은 측정 중입니다. 저장된 사람 인수 결과는 카드 판정 **reject**, 제안서 초안 **partial(6절 중 4절)**입니다. 회사 핏은 사람 판정 40건 대조에서 낮게 나왔고 추천 표시로만 씁니다. 분석 엔진 결과는 `unmeasured_reference`(참조 실행·미측정)입니다. 어떤 결과도 제출본이나 자동 의사결정으로 쓰지 않습니다. 입찰 변경 비교는 저장·API·화면까지 있고 비교 계산 worker는 없습니다. 범위와 근거는 [구현·검증 현황](docs/tracking/status.md)에 있습니다.

실회사 자료(회사 프로필·실적 목록·회사소개서 등)는 저장소에 없습니다. 같은 자리의 `*.example.*` 파일은 합성 회사 예시이며 테스트가 읽습니다([설치·설정](docs/operations/setup.md) "웹의 회사자료 입력 전제").

## 구성

| 계층 | 구성 |
|---|---|
| 관리 화면 | React 19 · TypeScript · Vite · Astryx |
| API | FastAPI · SQLAlchemy · Alembic(head `0047_company_fit_mode`) |
| 데이터 | PostgreSQL 17(`bidops` schema) · 버전 관리되는 MinIO |
| 문서 처리 | ClamAV · HWP/HWPX 변환·구조화 worker |
| 수집·분석 | Python 파이프라인(`skills/`) · 분석 코어(`packages/bid-deep-engine`) · 공용 analysis-worker |
| 실행 환경 | Docker Compose 자체 호스팅 |

관리 화면은 1280~1920px 데스크톱·노트북만 지원합니다. 로그인·역할 권한·SSO가 없으므로 서비스 접근은 사내망이나 접근이 제한된 tailnet으로 한정합니다. 저장소 공개와 서비스 공개는 별개입니다.

```text
bidops/
├── docker/              Dockerfile 5개 · Compose 8개(기반·edge·prod·mock-reference·luna·slack-egress·engine-live·portfolio)
├── scripts/compose.sh   dev(기본)·mock·prod 구성 선택
├── skills/              수집(collect)·판정(screen)·보고서(report) 파이프라인
├── packages/            분석 코어(transport 없음)
├── web/backend/         API·worker·migration
├── web/frontend/        관리 화면
├── tests/, run-tests.sh 파이프라인 교차 검사
└── docs/                정본 문서(아래 표)
```

## 개발 시작

Python 3.12+, Node.js 22+, Docker Compose가 필요합니다. 개발은 `bidops-dev`(`127.0.0.1:18789`), mock은 `bidops-mock`(`127.0.0.1:18790`)이며 운영 프로젝트와 자원을 공유하지 않습니다.

```bash
make env        # 개발 전용 자격증명을 env/dev.env에 한 번 생성
make build
make init       # DB 역할·migration·MinIO 초기화(명시적으로만 실행)
make create     # 개발 컨테이너 생성
make health
```

`make up`은 이미 만든 컨테이너를 시작하고 재배포나 migration을 하지 않습니다. `make down`은 컨테이너를 멈추고 볼륨을 남깁니다. 명령 전체는 `make help`와 [호스트 절차](docs/operations/host.md)에 있습니다.

모델 없이 돌리려면 `make env BIDOPS_ENV=mock`부터 같은 순서를 `BIDOPS_ENV=mock`으로 실행합니다. 결과에는 `mock_reference` 표식이 붙습니다. 화면만 볼 때는 백엔드 없이 고정 응답으로 띄울 수 있습니다.

```bash
cd web/frontend && npm ci && npm run dev:mock   # http://127.0.0.1:5174, 운영 데이터 아님
```

회사 자료가 없으면 프로필 API는 `503 profile_snapshot_unavailable`로 막힙니다. 의도된 동작입니다.

## 검증

```bash
./run-tests.sh           # 파이프라인 단위·교차 검사
./web/run-web-tests.sh   # 격리 PostgreSQL·백엔드·프론트엔드·화면 검사
cd web/frontend && npx tsc -b && npm run test:screens
```

검증 범위와 종료 기준은 [작업 지침](AGENTS.md)과 [구현·검증 표준](docs/standards.md)을 따릅니다.

## 운영과 승인

migration, 재배포, 실제 모델 호출, 정책 활성화, 스위치 변경은 각각 실행 직전에 담당자 확인을 받습니다. 배포 전에는 DB·객체 백업과 롤백 태그를 남기고, 일상 운영에서 `docker compose down -v`나 볼륨 삭제를 쓰지 않습니다. 절차는 [운영 안내](docs/operations.md)와 [백업·복구](docs/operations/backup-restore.md)에 있습니다. 포트폴리오 시연용 스택(`docker/docker-compose.portfolio.yml`)은 운영과 분리된 별도 구성입니다.

## 문서

| 문서 | 내용 |
|---|---|
| [작업 지침](AGENTS.md) | 저장소 지도·강제 게이트·검증 기준(`CLAUDE.md`와 같음) |
| [아키텍처](docs/ARCHITECTURE.md) | 서비스 구성·데이터 흐름·보안 경계 |
| [제품 요구](docs/PRD.md) · [실행 계획](docs/PLAN.md) | 요구사항·현재 착수 경계 |
| [업무 규칙](docs/business-rules.md) · [계약](docs/contracts.md) | 상태·사람 결정·REST·파일·DB 규칙 |
| [결정 색인](docs/ADR.md) | 기술·운영 결정(상세는 `docs/tracking/decisions/`) |
| [구현·검증 현황](docs/tracking/status.md) · [문제 기록](docs/tracking/findings.md) | 확인된 상태·알려진 제약 |
| [운영 안내](docs/operations.md) | 설치·호스트·일일 실행·백업 진입점 |
| `docs/specs/` | 구현된 기능의 설계·명세·계획(날짜별 폴더) |
| `docs/validation-runs/` | 남겨 둔 실행 증거. 나머지 기록은 git 이력에 있습니다 |
