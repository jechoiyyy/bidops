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

기반 Compose는 DB·객체 저장소를 호스트에 노출하지 않습니다. 화면은 `docker-compose.edge.yml`을 함께 적용해야 열리며, 기본 주소는 `http://127.0.0.1:18787`입니다. edge는 웹의 outbound 경로도 만들므로 외부 목적지 제한은 호스트 방화벽에서 관리합니다.

## 신규 설치

아래는 **새 Linux amd64 환경의 기본 웹·문서 처리 스택** 설치 순서입니다. 기존 운영 환경의 재배포에는 [운영 절차](docs/operations.md)를 사용하세요. Apple silicon에서는 별도 이미지 구성이 필요하므로 [Mac 운영 호스트](docs/operations/host.md#mac-운영-호스트-2026-10-14)를 먼저 확인하세요.

### 1. 소스와 설정 준비

Docker Engine과 Docker Compose를 준비하고 저장소를 내려받습니다. 호스트에서 개발·검증할 경우 Python 3.12+, Node.js 22+, npm 10+도 필요합니다.

```bash
git clone https://github.com/jechoiyyy/bidops.git
cd bidops
cp .env.example .env
```

기동 전에 `.env`의 예시 값을 실제 배포 값으로 바꿉니다.

- `BIDOPS_UID`·`BIDOPS_GID`: 실행 계정의 `id -u`·`id -g`와 일치하는 0이 아닌 값
- PostgreSQL: owner·migrate·app·worker·backup 역할별 서로 다른 비밀번호
- MinIO: root 및 용도별 access key·secret key
- 모델 응답 암호화: 키와 키 참조 값
- 화면: `BIDOPS_WEB_BIND_HOST=127.0.0.1`, `BIDOPS_WEB_PORT=18787` (충돌하면 포트 변경)

비밀값은 배포 환경에서 주입하며 `.env`와 `env/*.env`는 커밋하지 않습니다. 상세 설정은 [설치·설정 안내](docs/operations/setup.md)에 있습니다.

### 2. 승인된 회사자료 준비

웹 서비스는 아래 파일을 호스트에서 읽기 전용으로 마운트합니다. 회사자료는 런타임 이미지에 포함되지 않으며, 공개 소스만으로 배포 준비가 완료되지는 않습니다. 배포 담당자가 승인된 자료와 기준선을 별도로 준비해야 합니다.

```bash
test -f docs/reference/company-profile.md && test -r docs/reference/company-profile.md
test -f docs/reference/company-performance-titles.tsv && test -r docs/reference/company-performance-titles.tsv
test -f web/backend/app/screening/baseline_company_profile.md && test -r web/backend/app/screening/baseline_company_profile.md
```

세 검사 중 하나라도 실패하면 자료를 준비한 뒤 진행합니다. 빈 파일로 대신하지 않습니다. 프로필 기준선은 SHA-256 검증을 따릅니다.

### 3. 이미지 빌드와 저장소 초기화

기존 스택과 겹치지 않는 전용 Compose 프로젝트 이름을 지정합니다. 아래 이름은 새 설치용 예시이며, 이후 명령에도 같은 값을 유지합니다.

```bash
export COMPOSE_PROJECT_NAME=bidops-deploy

docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d postgres minio clamav

# DB 역할 → Alembic migration → MinIO 버킷·권한 초기화
./scripts/init-runtime.sh
```

앱 시작은 migration·seed·정책 활성화를 수행하지 않습니다. 초기화를 완료한 뒤 웹을 시작합니다.

### 4. 서비스 시작과 확인

```bash
docker compose -f docker-compose.yml -f docker-compose.edge.yml \
  up -d web document-worker

docker compose -f docker-compose.yml -f docker-compose.edge.yml ps
curl --fail http://127.0.0.1:18787/api/health
```

브라우저에서 `http://127.0.0.1:18787`을 엽니다. `.env`에서 포트를 변경했다면 확인 주소도 바꿉니다. API health와 함께 실제 화면이 열리는지 확인하세요.

새 설치에는 수집 회차·판정·리뷰가 없습니다. 승인된 프로필 snapshot이 없을 때 프로필 API가 `503 profile_snapshot_unavailable`을 반환하는 것은 정상적인 차단 동작입니다. 수집·적재·프로필 및 정책 준비는 [설치 안내](docs/operations/setup.md)와 [일일 운영](docs/operations/daily.md)을 따릅니다.

## 분석·연동 활성화

기본 설치 이후 필요한 경로를 따로 설정합니다. 모델·회사자료 전송과 정책 활성화는 각 경로의 승인·감사 절차를 거칩니다.

| 목적 | 추가 구성 | 절차 |
|---|---|---|
| 공고 판정·개요·심층 분석 | `docker-compose.model-egress.yml`, `env/model.env`, `analysis-worker` | [모델·worker 설정](docs/operations/setup.md) |
| C-2 발주계획 선별 | model-egress + `docker-compose.c2-order-plan.yml`, 승인 입력·정책·품질 게이트 | [C-2 일일 운영](docs/operations/daily.md) |
| 사전규격 첨부 취득 | `docker-compose.prespec-attachment.yml`, `env/prespec-attachment.env`, 첨부 worker | [사전규격 실행](docs/operations/prespec-reference.md) |
| 회사 기반 판정·제안서 | RL 설정·회사 근거·승인 정책·전용 실행 환경 | [RL 운영](docs/operations/rl.md) |
| Slack 브리핑·반응 | `docker-compose.slack-egress.yml`, `env/slack.env` | [RL·Slack 운영](docs/operations/rl.md) |
| 모델 없는 흐름 검증 | `docker-compose.mock-reference.yml` (화면 접근에는 edge도 필요) | [참조 실행 가이드](docs/prespec-reference-run-guide.md) |

`--env-file`을 쓰면 공통 `.env`와 해당 overlay의 환경 파일을 함께 넘깁니다. 스케줄러·심층 자동 시작·RL 분석·Slack은 기본 비활성이며, 모델 장애 때 외부 hosted 모델로 자동 전환하지 않습니다. mock·참조 실행은 품질 합격이나 운영 활성화 근거가 아닙니다.

## 기존 Mac 운영

기존 Mac 운영은 **운영 checkout의 `scripts/mac-compose.sh`**가 Compose 파일 6개·환경 파일 4개·`prespec` profile을 고정합니다. 프로젝트 이름은 `bidops`, 웹은 loopback `18788`, tailnet은 `8188`이며 신규 설치 예시와 구분합니다.

```bash
# 운영 checkout에서 읽기 전용 상태 확인
scripts/mac-compose.sh ps
curl --fail http://127.0.0.1:18788/api/health
```

앱은 amd64 이미지, 문서 worker는 별도 native arm64 이미지를 사용합니다. 이미지 준비·교체·migration은 [Mac 호스트 절차](docs/operations/host.md#mac-운영-호스트-2026-10-14)를 따릅니다.

마지막 저장된 운영 확인은 [2026-10-19 배포 기록](docs/validation-runs/20261019-ops-rl-rollout/README.md)입니다. 당시 C-2 v5 active·일일 스위치 ON, 개요·상시 첨부 worker·RL 분석은 꺼져 있었습니다. 일일 스위치 ON은 cron 설치를 뜻하지 않으며, Mac cron은 설치하지 않은 상태로 기록돼 있습니다. 이후 코드 변경이 운영에 반영됐다고 추정하지 않습니다.

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
