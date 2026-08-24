# BidOps Admin 웹

나라장터 입찰공고 모니터링 워크플로가 만들어 낸 산출물을 읽어, 담당자가 판정을 검토하고 리뷰를 기록하는 관리자 화면입니다. 애플리케이션은 산출물을 **읽어서 보여줄 뿐** 판정 값을 스스로 만들거나 보정하지 않습니다.

- 백엔드: FastAPI · SQLAlchemy 2.x · Pydantic v2 · SQLite(WAL)
- 프론트엔드: Vite 6 · React 19 · TypeScript · Tailwind v4 · TanStack Query v5 · React Router v7
- 설계 근거: `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ADR.md`, `docs/PLAN.md`

## 두 가지 실행 방법

| 방법 | 어떤 경우에 |
|---|---|
| **Docker Compose** | 화면을 띄워서 보기만 하면 될 때. 파이썬·Node 설치가 필요 없습니다 |
| **직접 실행** | 코드를 고치면서 확인할 때 |

## 사전 준비

| 항목 | 필요 버전 | 확인 명령 |
|---|---|---|
| Python | 3.12 이상 | `python3 --version` |
| Node.js | 22 이상 | `node --version` |
| npm | 10 이상 | `npm --version` |

Docker Compose로 실행할 때는 Docker만 있으면 되며 위 도구는 필요하지 않습니다.

아래 모든 명령은 저장소의 `bidops-agent/` 디렉토리를 기준으로 합니다.

## Docker Compose로 실행

`bidops-agent/` 에서 다음 두 명령이면 됩니다. 첫 명령은 산출물을 데이터베이스에 넣고, 두 번째가 서버를 띄웁니다.

```bash
docker compose run --rm web python -m app.ingest.cli --all
docker compose up -d
```

브라우저에서 `http://localhost:8787` 을 엽니다.

```bash
docker compose logs -f web   # 로그 보기
docker compose down          # 중지
```

구성은 다음과 같습니다.

- 이미지에는 웹 계층만 담고, 회차 산출물(`data/`)·보고서(`reports/`)·skill 스크립트(`skills/`)·회사 프로필(`docs/`)은 호스트에서 마운트합니다. 파이프라인이 만든 새 산출물이 이미지를 다시 만들지 않아도 화면에 반영됩니다
- `skills/` 와 `docs/` 는 읽기 전용으로 연결합니다. 애플리케이션이 판정 스크립트와 기준 문서를 고치지 않는다는 원칙을 파일 권한으로도 보장합니다
- 데이터베이스와 첨부 원문은 `bidops-web-data` 볼륨에 남습니다. 컨테이너를 다시 만들어도 유지되며, 지우려면 `docker compose down -v` 를 사용합니다
- 컨테이너는 호스트와 같은 사용자(기본 `1000:1000`)로 실행합니다. 파이프라인이 호스트에 만드는 파일을 그대로 지울 수 있게 하기 위한 설정이며, 사용자 번호가 다르면 `.env` 에 `BIDOPS_UID` 와 `BIDOPS_GID` 를 지정하십시오
- API 키는 `.env` 가 있으면 자동으로 전달됩니다. 없어도 기동합니다

산출물을 다시 적재해야 할 때는 서버를 띄운 채로 다음을 실행하면 됩니다.

```bash
docker compose exec web python -m app.ingest.cli --all
```

## 직접 실행

처음 실행한다면 다음 네 단계를 순서대로 따르면 됩니다. 마지막 단계가 끝나면 브라우저에서 화면을 볼 수 있습니다.

```bash
# 1. 백엔드 의존성 설치
cd web/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 산출물을 데이터베이스에 적재
.venv/bin/python -m app.ingest.cli --all

# 3. 프론트엔드 설치와 빌드
cd ../frontend
npm install
npm run build

# 4. 백엔드 단독 실행
cd ../backend
.venv/bin/uvicorn app.main:app --port 8787
```

브라우저에서 `http://localhost:8787` 을 엽니다. 프론트엔드를 빌드해 두면 백엔드 하나만 띄워도 전체 화면이 동작합니다.

2번 단계를 건너뛰면 화면은 뜨지만 모든 목록이 비어 있습니다. 회차 선택기에 아무것도 나오지 않는다면 적재를 먼저 실행하십시오.

## 화면 수정 중이라면: 개발 실행

화면 코드를 고치면서 확인할 때는 두 서버를 함께 띄웁니다. 프론트엔드 개발 서버가 `/api` 요청을 8787 포트 백엔드로 프록시합니다.

```bash
# 터미널 1
cd web/backend
.venv/bin/uvicorn app.main:app --reload --port 8787

# 터미널 2
cd web/frontend
npm run dev
```

이때는 `http://localhost:5173` 을 엽니다. 저장하면 화면이 바로 갱신됩니다.

## 산출물 적재

`data/runs/<회차>/` 아래 파일을 읽어 SQLite에 넣습니다. 같은 회차를 두 번 적재해도 행이 중복되지 않습니다.

```bash
cd web/backend
.venv/bin/python -m app.ingest.cli --run 20260817-20260823   # 회차 하나
.venv/bin/python -m app.ingest.cli --all                     # 발견된 모든 회차
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
| `BIDOPS_ROOT` | `bidops-agent/` | 프로젝트 루트 |
| `BIDOPS_DATA_DIR` | `web/data/` | 데이터베이스와 첨부 보관 위치 |
| `BIDOPS_ATTACHMENTS_DIR` | `web/data/attachments/` | 첨부 원문 보관 경로 |
| `BIDOPS_DATABASE_URL` | `sqlite:///web/data/bidops.db` | 데이터베이스 주소 |
| `BIDOPS_REVIEWER` | 빈 값 | 리뷰 저장 시 기본 작성자 이름 |

`web/data/` 는 통째로 `.gitignore` 대상입니다. 데이터베이스는 산출물에서 언제든 다시 만들 수 있고, 첨부 원문은 저장소에 두지 않습니다.

## 테스트

```bash
./web/run-web-tests.sh
```

백엔드 pytest와 프론트엔드 타입 검사·빌드를 함께 실행합니다. 저장소 루트의 `run-tests.sh` 는 기존 파이프라인 테스트 진입점이며 이 스크립트가 건드리지 않습니다.

## 문제가 생기면

| 증상 | 원인과 해결 |
|---|---|
| 회차 선택기가 비어 있다 | 적재를 실행하지 않았습니다. `.venv/bin/python -m app.ingest.cli --all` |
| `빌드된 프론트엔드가 없습니다` 라는 503 응답이 온다 | `web/frontend` 에서 `npm run build` 를 실행하십시오. 빌드 산출물이 없어도 백엔드 기동 자체는 실패하지 않습니다 |
| Docker 실행에서 화면이 비어 있다 | 적재를 하지 않았습니다. `docker compose run --rm web python -m app.ingest.cli --all` |
| Docker가 만든 파일을 지울 수 없다 | 컨테이너 사용자 번호가 호스트와 다릅니다. `id -u` 와 `id -g` 를 확인해 `.env` 에 `BIDOPS_UID`·`BIDOPS_GID` 를 지정하고 다시 띄우십시오 |
| 8787 포트가 이미 쓰이고 있다 | `--port` 로 다른 번호를 지정하십시오. 개발 실행에서는 `web/frontend/vite.config.ts` 의 프록시 대상도 함께 바꿔야 합니다 |
| 대시보드 수집 건수가 값 없음으로 나온다 | 해당 회차에 `collected-notices.json` 이 없습니다. 이 파일은 `.gitignore` 대상이라 없을 수 있으며, `--from-raw` 재분류로 다시 만들 수 있습니다 |
| 첨부 업로드가 거부된다 | HWP·HWPX·PDF 만 허용하며 상한은 50MB 입니다. 거부 사유는 화면에 그대로 표시됩니다 |
| 나라장터 첨부가 삭제되지 않는다 | 의도된 동작입니다. 직접 등록한 파일(`manual`)만 삭제할 수 있습니다 |
