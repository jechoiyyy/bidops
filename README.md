# BidOps

**나라장터 발주계획 탐색부터 사전규격 검토, 입찰공고 추적까지 연결하는 사내 의사결정 지원 서비스입니다.**

기획·사업개발 담당자가 검토할 사업을 찾고, 제안요청서의 요구사항과 회사 근거를 함께 살펴보며, 추적 여부와 최종 입찰 참여 결정을 기록합니다. 시스템은 수집·선별·분석을 지원하고, 발주처 연락·추적 승인·최종 Go/No-Go·입찰 실행은 사람이 담당합니다.

## 주요 기능

| 업무 | 지원 기능 |
|---|---|
| 사업 탐색 | 나라장터 발주계획·사전규격·입찰공고 수집, 발주계획 선별과 검토 |
| 문서 검토 | 첨부 취득·악성코드 검사, HWP/HWPX·PDF 문서 준비, 개요와 원문 근거 확인 |
| 사업 추적 | 사업기회 연결, 추적·보류·종료 결정, 활동·노트와 최종 Go/No-Go 기록 |
| 회사 기반 분석 | 회사 근거 관리, 역할별 판정 카드, 제안서 초안 작성·검토·PDF 내보내기 |
| 운영 관리 | 실행 상태·감사 기록, 선별 정책·품질 게이트, 브리핑·Slack 연동 |

회사 기반 분석과 제안서 초안은 품질 개선 중입니다. 저장된 실제 인수 결과는 판정 **reject**, 초안 **partial(6절 중 4절 완료)**이며, 제출본이나 자동 의사결정으로 사용하지 않습니다. 입찰 변경 비교는 저장·API·화면까지 구현됐고 비교 계산 worker는 구현 전입니다. 자세한 범위와 근거는 [구현·검증 현황](docs/tracking/status.md)을 참고하세요.

## 배포 구성

| 계층 | 구성 |
|---|---|
| 관리 화면 | React 19 · TypeScript · Vite · Astryx |
| API | FastAPI · SQLAlchemy · Alembic |
| 데이터 | PostgreSQL 17 (`bidops` schema) · 버전 관리되는 MinIO |
| 문서 처리 | ClamAV · HWP/HWPX 변환·구조화 worker |
| 수집·분석 | Python 파이프라인 · 용도별 분석 worker |
| 실행 환경 | Docker Compose 기반 자체 호스팅 |

관리 화면은 **1280~1920px 데스크톱·노트북**을 지원합니다. 현재 로그인·역할 기반 권한·SSO가 없으므로 서비스 접근은 사내망 또는 접근이 제한된 tailnet으로 한정합니다. 저장소 공개와 서비스의 인터넷 공개는 별개입니다.

기반 Compose는 DB·객체 저장소를 호스트에 노출하지 않습니다. 화면은 `docker/docker-compose.edge.yml`을 함께 적용해야 열리며, 개발 기본 주소는 `http://127.0.0.1:18789`입니다. edge는 웹의 outbound 경로도 만들므로 외부 목적지 제한은 호스트 방화벽에서 관리합니다.

## 통합 개발 시작

Python 3.12+, Node.js 22+, Docker Compose가 필요합니다. 개발 기본은 `bidops-dev` / `127.0.0.1:18789`, mock은 `bidops-mock` / `:18790`입니다. 운영 `bidops` / `:18788`, 기존 데모 `bidops-local` / `:18787`과 자원을 공유하지 않습니다.

```bash
make env        # 개발 전용 자격증명을 env/dev.env에 한 번 생성
make config
make build
make init       # 명시적 DB 역할·migration·MinIO 초기화
make create     # 새 개발 컨테이너 생성
make health
make status
make logs
make test-config # 구성 선택·관련 운영 스크립트 검사
make test-engine # 엔진·adapter 검사 (PostgreSQL 변형은 별도 test URL 지정)
```

이미 만든 컨테이너를 시작할 때는 `make up`, 수정 이미지를 만들 때는 `make build`, 새 이미지로 컨테이너를 교체할 때는 `make create`를 사용합니다. `make up`은 재배포나 migration을 수행하지 않습니다. `make down`은 프로젝트 컨테이너를 중지하고 볼륨을 보존합니다. 정확한 명령·옵션은 `make help`와 [호스트 절차](docs/operations/host.md)를 확인하세요.

모델 없는 검증은 `env/mock.env`를 별도로 준비하고 모든 명령에 `BIDOPS_ENV=mock`을 지정합니다. 비밀값·회사자료는 커밋하거나 이미지에 넣지 않습니다. 프로필 API의 `503 profile_snapshot_unavailable`은 승인 snapshot이 없는 경우의 차단 동작입니다.

분석 엔진은 `packages/bid-deep-engine`과 BidOps adapter로 연결합니다. 사전규격 상세의 새 실행은 **mock 참조**이고 기존 판정·리뷰와 별도로 저장됩니다. Claude/API/CLI/A2A·Langfuse 전송은 이식하지 않습니다. 기존 품질 실패와 파서 누락은 유지되며, 통합 성공은 품질 인수를 의미하지 않습니다. [통합 계약과 검증](docs/work/groups/RL/features/RL-09-engine-integration/plan.md)을 참고하세요.

## 운영 구성과 승인

Dockerfile 5개와 Compose 6개는 [`docker/`](docker/README.md)에서 관리합니다. 빌드 context와 bind mount의 기준은 저장소 루트이며 `.dockerignore`도 루트에 유지합니다.

Make와 운영 스크립트는 `scripts/compose.sh` 하나로 환경을 선택합니다. 기존 `scripts/mac-compose.sh`는 prod 선택 wrapper입니다. 운영은 base+edge+prod 세 파일과 기존 env 네 파일을 사용하며 모델·G2B 네트워크는 해당 서비스에만 연결합니다. Luna·Slack은 별도 선택 capability입니다. profiles는 서비스 선택에만 사용합니다.

```bash
# 운영 checkout의 읽기 전용 상태 확인
scripts/mac-compose.sh ps
```

앱은 amd64 이미지, 문서 worker는 native arm64 이미지를 사용합니다. 저장소에 portable `docker/Document.Dockerfile`을 제공합니다. 운영 project·volume 이름은 유지합니다. migration·재배포·정책 활성화·실제 모델·Slack·cron은 이번 통합에서 실행하지 않습니다.

마지막 저장된 배포는 [2026-10-19 기록](docs/validation-runs/20261019-ops-rl-rollout/README.md)입니다. 2026-11-17 읽기 전용 확인에서 운영과 데모 web은 모두 restarting/unhealthy였고 활성 BidOps cron 행은 없었습니다. 이 통합에서 복구하지 않았으며, 정상 운영 또는 새 코드 반영으로 해석하지 않습니다.

## 업데이트·백업·복구

운영 업데이트는 전체 DB·객체 백업과 롤백 태그를 확보한 뒤 진행합니다. migration, 서비스 재배포, 실제 모델 호출, 정책 활성화, cron 설치는 각각 실행 직전 담당자 확인 대상입니다.

- 기존 운영에서는 해당 환경의 Compose·env 조합을 유지합니다.
- DB dump와 객체 버전 manifest를 같은 복구 지점으로 보존합니다.
- 복구는 빈 PostgreSQL·MinIO에서 객체와 참조 hash를 검증하며 수행합니다.
- 일상 운영에서 `docker compose down -v`나 volume 삭제를 사용하지 않습니다.

상세 명령은 [백업·복구·서버 이전](docs/operations/backup-restore.md)을 참고하세요.

## 개발과 문서

코드 변경 전 [작업 지침](AGENTS.md), [구현·검증 표준](docs/standards.md), [엔지니어링 노트](docs/engineering-notes.md)를 확인하세요. 검증은 변경한 기능과 직접 영향받는 범위부터 수행합니다.

```bash
./run-tests.sh           # 파이프라인 검사
./web/run-web-tests.sh   # 격리 PostgreSQL·백엔드·프론트엔드·화면 검사
```

| 문서 | 내용 |
|---|---|
| [운영 안내](docs/operations.md) | 설치·호스트·일일 실행·연동·복구 진입점 |
| [아키텍처](docs/ARCHITECTURE.md) | 서비스 구성·데이터 흐름·보안 경계 |
| [업무 규칙](docs/business-rules.md) · [계약](docs/contracts.md) | 상태·사람 결정·REST·파일·DB 규칙 |
| [구현·검증 현황](docs/tracking/status.md) · [로드맵](docs/work/constitution/roadmap.md) | 확인된 기능·품질·남은 작업 |
| [문제 기록](docs/tracking/findings.md) | 알려진 제약·재현 조건 |
| [기존 README 보존본](docs/README-before-deployment.md) | 이번 개편 직전 문서. 본문을 보존하고 이동에 따른 상대 링크만 보정 |
