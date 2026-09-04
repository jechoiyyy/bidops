# BidOps Admin 웹

나라장터 공고 수집·선별·첨부 심층 검토 결과를 담당자가 확인하고 리뷰를 기록하는 관리 화면입니다.
화면은 REST API와 저장된 산출물을 사용하며, 확인되지 않은 판정 값이나 회사 역량을 브라우저에서
새로 만들거나 보정하지 않습니다. 최종 참여 판단은 담당자가 합니다.

- 백엔드: FastAPI · SQLAlchemy 2.x · Pydantic v2 · PostgreSQL 17
- 프론트엔드: Vite 6 · React 19 · TypeScript · Tailwind v4 · TanStack Query v5 · React Router v7
- live 정본: PostgreSQL 17의 `bidops` schema
- SQLite: 격리 테스트와 일회성 migration input에만 사용
- 현재 운영 기준: `docs/ARCHITECTURE.md`, `docs/business-rules.md`, `docs/security.md`, `docs/contracts.md`, `docs/operations.md`, `docs/standards.md`

## 현재 T7 runtime 실행

운영·통합 확인은 반드시 별도 Compose 프로젝트 이름과 `docker-compose.t7.yml`을 사용합니다. 비밀값은
`.env`에 직접 기록하거나 Git에 넣지 말고 외부 secret 주입 절차를 따릅니다.

```bash
cp .env.example .env
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml build
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml up -d postgres minio clamav
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 ./scripts/init-runtime.sh
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  up -d web document-worker analysis-worker
curl -fsS http://127.0.0.1:18787/api/health
```

앱 시작은 migration·`create_all`·policy/portal seed를 수행하지 않습니다. `init-runtime.sh`가 만든
PostgreSQL migration과 object-store 초기화가 먼저 완료되어야 하며, policy seed와 always-on 전환은
담당자가 별도로 승인·실행합니다. 일상 운영에서 `docker compose down -v`를 사용하거나 main worktree의
Compose·volume을 공유하지 않습니다.

## 개발 실행

호스트 개발에는 Python 3.12+, Node.js 22+, npm 10+이 필요합니다. 백엔드는 승인된
PostgreSQL 17 인스턴스와 현재 운영 경로를 사용해야 하며, SQLite URL로 실행하지 않습니다.
통합 환경의 DB·object store 준비와 seed 순서는 [운영 절차](../docs/operations.md)를 따릅니다.

화면 코드를 고치면서 확인할 때는 백엔드와 프론트엔드 개발 서버를 함께 띄웁니다. 프론트엔드 개발
서버가 `/api` 요청을 8787 포트 백엔드로 프록시합니다.

```bash
# 의존성 준비
cd web/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8787

# 별도 터미널
cd web/frontend
npm ci
npm run dev
```

이때는 `http://localhost:5173` 을 엽니다. 저장하면 화면이 바로 갱신됩니다.

## 산출물 적재

`data/runs/<회차>/` 아래 파일을 읽어 live canonical PostgreSQL에 넣습니다. 같은 회차를 두 번 적재해도
행이 중복되지 않습니다. SQLite 적재는 격리 테스트나 일회성 migration input에서만 허용됩니다.

```bash
cd web/backend
.venv/bin/python -m app.lifecycle.ingest.cli --run 20260817-20260823   # 회차 하나
.venv/bin/python -m app.lifecycle.ingest.cli --all                     # 발견된 모든 회차
```

적재 순서는 `validation-set.json` → `screening-results.json` → `collected-notices.json` 이며, 마지막으로 `reports/<회차>/review-feedback.yaml` 에서 값이 채워진 항목만 초기 리뷰로 가져옵니다.

계약을 어긴 산출물은 거부하지 않고 **경고로 기록**한 뒤 있는 만큼 적재합니다. 누락된 값을 임의로 채우지는 않습니다. 기록된 경고는 수집 실행 화면의 산출물 검증 영역에 그대로 나타납니다.

## 화면 둘러보기

사이드바는 네 그룹, 열 개 항목입니다. 처음 확인할 때는 아래 순서를 권합니다.

| 순서 | 화면 | 무엇을 보면 되는가 |
|---|---|---|
| 1 | 대시보드 | 파이프라인의 건강도. 수집·후보·우선 검토·1차 필터 누락 네 지표와 검증 통과 기준 다섯 항목. **미달 항목을 숨기지 않는 것**이 이 화면의 핵심입니다 |
| 2 | 검토 대기열 | 담당자가 가장 오래 머무는 화면. 왼쪽에서 공고를 고르면 오른쪽에 판정 근거가 펼쳐지고, 하단 고정 바에서 리뷰를 저장하면 다음 공고로 넘어갑니다 |
| 3 | 공고 판정 이력 | 같은 화면의 데이터에 시간 축을 더한 것. 생애주기 타임라인, 회차별 판정 변화, 같은 사업의 다른 차수 |
| 4 | 첨부 확보 | 나라장터에 첨부가 없는 공고 목록. 기관 조달시스템 검색 주소를 만들고 내려받은 파일을 등록합니다 |
| 5 | 수집 실행 | 파이프라인 단계 실행과 로그, 산출물 검증 결과 |
| 6 | 회사 프로필 · 검증 지표 | 판정이 근거로 삼는 회사 정보와 통과 기준의 계산 근거 |

읽는 방법에서 한 가지만 기억하시면 됩니다. **`계산 불가`와 `0`은 다릅니다.** 값이 없어서 계산할 수 없는 항목은 게이지를 비워 두고 사유 문장을 함께 보여 줍니다. 0으로 채워 나쁜 값처럼 보이게 하지 않습니다. `값 없음`, `미확인` 도 같은 이유로 빈칸 대신 명시합니다.

## 파이프라인 실행

수집 실행 화면에서 세 단계를 실행할 수 있습니다.

| 단계 | 하는 일 | 준비물 |
|---|---|---|
| `collect` | 공고를 수집하고 정규화합니다 | 실전 수집에는 API 키가 필요합니다. `--from-raw` 재분류는 보존된 원문만으로 동작합니다 |
| `sample` | 검증 표본을 선정합니다 | 같은 회차의 `collected-notices.json` |
| `report` | HTML 보고서를 생성합니다 | 같은 회차의 `screening-results.json` |

**판정 단계는 화면에서 실행하지 않습니다.** 판정은 에이전트가 `screening-decisions.json` 을 직접 작성해야 하는 작업이라, 화면에는 대기 상태로만 표시됩니다. 파일이 갱신되면 적재기가 인식합니다.

실행은 원본을 덮어쓰지 않고 새 회차 디렉토리를 만듭니다. 이전 회차의 판정은 그대로 보존되며, 재현성 지표를 계산하려면 두 회차가 모두 필요하기 때문입니다.

## 설정

`bidops-agent/.env` 에서 읽습니다. 이 파일은 `.gitignore` 대상이며 값이 API 응답이나 실행 로그에 나타나지 않습니다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `BIDOPS_G2B_API_KEY` | 없음 | 나라장터 API 키. 실전 수집에만 필요합니다 |
| `BIDOPS_ROOT` | 프로젝트 루트 | 프로젝트 루트. 컨테이너에서는 `/app` |
| `BIDOPS_DATA_DIR` | runtime별 경로 | 회차 산출물·runtime 데이터 경로 |
| `BIDOPS_ATTACHMENTS_DIR` | runtime별 경로 | 첨부 원문 보관 경로 |
| `BIDOPS_DATABASE_URL` | 기본값 없음 | live 실행은 PostgreSQL 17 URL 필수 |
| `BIDOPS_REVIEWER` | 빈 값 | 리뷰 저장 시 기본 작성자 이름 |

runtime 데이터·첨부·비밀값은 저장소에 넣지 않습니다. `.env`는 `.gitignore` 대상이며, 실제 보관 경로와
PostgreSQL/object-store 자격 증명은 [운영 절차](../docs/operations.md)의 격리 구성을 따릅니다.

## 테스트

저장소 전체와 웹 계층의 기본 검증 진입점은 다음과 같습니다.

```bash
./run-tests.sh
./web/run-web-tests.sh
```

`web/run-web-tests.sh`는 임시 PostgreSQL을 준비해 migration과 backend pytest, frontend production
build, 네 폭의 Playwright 화면 스냅샷 회귀를 차례로 수행합니다. 화면만 따로 볼 때는
`cd web/frontend && npm run test:visual`을 사용합니다. Playwright는 브라우저 번들이 이미 설치되어
있어야 하며, 없으면 자체 안내 문구와 함께 실패합니다.

## 문제가 생기면

| 증상 | 원인과 해결 |
|---|---|
| 회차 선택기가 비어 있다 | 현재 runtime의 PostgreSQL에 적재가 되었는지 확인하고 `.venv/bin/python -m app.lifecycle.ingest.cli --all`을 실행하십시오 |
| `빌드된 프론트엔드가 없습니다` 라는 503 응답이 온다 | `web/frontend` 에서 `npm run build` 를 실행하십시오. 빌드 산출물이 없어도 백엔드 기동 자체는 실패하지 않습니다 |
| Docker 실행에서 화면이 비어 있다 | T7 runtime의 health, migration, PostgreSQL 적재 상태와 API 응답을 순서대로 확인하십시오 |
| Docker가 만든 파일을 지울 수 없다 | 컨테이너 사용자 번호가 호스트와 다릅니다. `id -u` 와 `id -g` 를 확인해 `.env` 에 `BIDOPS_UID`·`BIDOPS_GID` 를 지정하고 다시 띄우십시오 |
| 직접 실행에서 `ensurepip is not available` 이 나온다 | 시스템에 `python3-venv` 가 없습니다. `sudo apt install python3.12-venv` 로 설치하거나 Docker 실행을 쓰십시오 |
| 8787 포트가 이미 쓰이고 있다 | `--port` 로 다른 번호를 지정하십시오. 개발 실행에서는 `web/frontend/vite.config.ts` 의 프록시 대상도 함께 바꿔야 합니다 |
| 대시보드 수집 건수가 값 없음으로 나온다 | 해당 회차에 `collected-notices.json` 이 없습니다. 이 파일과 원문 페이지는 용량 때문에 저장소에서 제외되므로, 새로 클론한 환경에서는 정상입니다. 값을 채우려면 API 키를 넣고 수집을 다시 실행하십시오 |
| 첨부 업로드가 거부된다 | HWP·HWPX·PDF 만 허용하며 상한은 50MB 입니다. 거부 사유는 화면에 그대로 표시됩니다 |
| 나라장터 첨부가 삭제되지 않는다 | 의도된 동작입니다. 직접 등록한 파일(`manual`)만 삭제할 수 있습니다 |
