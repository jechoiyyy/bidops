# 운영 절차

## 전제 조건

프로젝트 루트는 `bidops-agent/`다. Docker 방식은 Docker Engine과 Compose가 필요하다. 직접 실행은 Python 3.12 이상, `python3-venv`, Node.js 22 이상, npm 10 이상이 필요하다. 실전 나라장터 수집에만 공공데이터포털에서 발급된 API 키가 필요하다.

## Docker로 처음 실행

다음 순서를 지킨다. 적재 전에 서버를 올려도 화면은 뜨지만 목록이 비어 있다.

```bash
cd /path/to/bidops-agent
cp .env.example .env
# 실전 수집을 할 때만 .env의 BIDOPS_G2B_API_KEY를 입력한다.
docker compose run --rm web python -m app.ingest.cli --all
docker compose up -d
```

`http://localhost:8787`에서 화면을 열고 `http://localhost:8787/api/health`가 `{"status":"ok"}`를 반환하는지 확인한다. 적재된 회차가 없다면 회차 선택기는 비어 있는 것이 정상이다.

```bash
docker compose logs -f web
docker compose down
```

볼륨까지 삭제하는 `docker compose down -v`는 SQLite와 수동 첨부를 지우므로 백업·복구가 확인된 경우에만 사용한다.

## 직접 개발 실행

```bash
cd /path/to/bidops-agent/web/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.ingest.cli --all

cd ../frontend
npm install
npm run build

cd ../backend
.venv/bin/uvicorn app.main:app --port 8787
```

프론트엔드를 수정할 때는 백엔드와 Vite를 서로 다른 터미널에서 실행한다.

```bash
cd /path/to/bidops-agent/web/backend
.venv/bin/uvicorn app.main:app --reload --port 8787
```

```bash
cd /path/to/bidops-agent/web/frontend
npm run dev
```

개발 화면은 `http://localhost:5173`이며 `/api` 요청은 8787 포트로 전달된다.

## 산출물 적재와 파이프라인

```bash
cd /path/to/bidops-agent/web/backend
.venv/bin/python -m app.ingest.cli --run 20260817-20260823
.venv/bin/python -m app.ingest.cli --all
```

적재 순서는 `validation-set.json`, `screening-results.json`, `collected-notices.json`, 값이 있는 `review-feedback.yaml`이다. 같은 회차를 다시 적재해도 중복 행을 만들지 않아야 하며 경고는 수집 실행 화면에서 확인한다.

웹 화면은 현재 `collect`, `sample`, `report`를 실행한다. `collect` 실전 실행에는 API 키가 필요하고 `--from-raw`는 보존된 원문이 필요하다. 1차 Qwen 판정과 첨부 심층 분석은 목표 기능이며 구현 완료 전에는 기존 skill 실행과 생성된 파일 적재 절차를 사용한다.

## 검증

```bash
cd /path/to/bidops-agent
./run-tests.sh
./web/run-web-tests.sh
```

첫 명령은 각 skill과 교차 파이프라인의 `unittest`를 실행한다. 두 번째는 백엔드 `pytest`와 프론트엔드 타입 검사·빌드를 실행한다. 화면 구조 또는 검토 흐름을 바꾼 경우 다음도 실행한다.

```bash
cd /path/to/bidops-agent/web/frontend
npm run test:visual
```

Docker 환경에서는 다음으로 대체할 수 있다.

```bash
docker compose build
docker compose run --rm web pytest -q
```

## 환경 설정

| 이름 | 기본값 | 유효 범위와 역할 |
|---|---|---|
| `BIDOPS_G2B_API_KEY` | 없음 | 실전 나라장터 수집 요청에만 사용한다. 미설정이어도 웹 조회와 기존 산출물 적재는 가능하다. |
| `BIDOPS_ROOT` | 프로젝트 루트 | `data`, `reports`, `skills`, `docs`, 프론트엔드 빌드 위치의 기준 경로다. 컨테이너에서는 `/app`이다. |
| `BIDOPS_DATA_DIR` | `web/data` | SQLite와 런타임 데이터의 상위 경로다. 쓰기 가능한 로컬/볼륨 경로여야 한다. |
| `BIDOPS_ATTACHMENTS_DIR` | `<data>/attachments` | 수동 첨부 원문 보관 경로다. 웹 프로세스만 쓰고 정적 파일 서버로 직접 공개하지 않는다. |
| `BIDOPS_DATABASE_URL` | `<data>/bidops.db` SQLite URL | DB 연결을 덮어쓴다. 현재 운영 전제는 SQLite WAL이다. |
| `BIDOPS_REVIEWER` | 빈 값 | 기존 리뷰의 기본 작성자 호환값이다. 사용자 이름 입력 기능이 구현되면 요청의 이름이 우선한다. |
| `BIDOPS_UID`, `BIDOPS_GID` | `1000`, `1000` | Docker 프로세스의 호스트 파일 소유자를 맞춘다. |

Ollama 주소·모델, HWPX 변환기, OpenAI 활성화·키, 정책 저장 위치에 대한 운영 설정은 아직 코드 계약이 없으므로 구현 시 `BIDOPS_` 접두사와 비밀 분리 규칙에 맞춰 추가한다.

## 백업과 복구

초기 보존 기간은 제한하지 않는다. 최소한 SQLite, 수동 첨부 디렉터리, `data/runs`, `reports`, 활성·과거 정책 버전을 같은 시점의 묶음으로 정기 백업한다. SQLite는 실행 중 파일 복사 대신 SQLite 백업 API 또는 서비스를 중지한 뒤 복사해야 한다. Docker named volume을 사용할 때는 볼륨 내부 DB와 첨부를 모두 포함한다.

복구 검증은 운영본이 아닌 별도 경로에서 수행한다.

1. 백업을 빈 데이터 경로에 복원한다.
2. 복원 경로를 `BIDOPS_DATA_DIR`과 프로젝트 루트 설정으로 가리킨다.
3. API를 기동해 회차 수, 임의 리뷰, 수동 첨부 다운로드, 정책 버전을 확인한다.
4. YAML 내보내기를 실행하고 DB 리뷰와 건수를 대조한다.

백업 주기와 외부 보관 위치는 사내 운영 환경이 정해질 때 확정해야 한다.

## 장애 확인

| 증상 | 확인과 조치 |
|---|---|
| 화면은 503, API health는 정상 | `web/frontend`에서 `npm run build` 후 `dist/index.html` 존재를 확인한다. |
| 회차가 비어 있음 | `python -m app.ingest.cli --all` 실행 여부와 `data/runs` 위치를 확인한다. |
| 수집 건수가 값 없음 | `collected-notices.json` 부재 여부를 확인한다. 필요하면 API 키로 수집한다. |
| 첨부 업로드 거부 | HWP/HWPX/PDF, 50MB 이하인지 확인한다. 우회 확장자로 바꾸지 않는다. |
| Docker 파일 삭제 불가 | 호스트 UID/GID를 `.env`에 설정하고 컨테이너를 재생성한다. |
| 8787 포트 충돌 | 백엔드 포트를 바꾸고 개발 모드라면 Vite 프록시 대상도 함께 바꾼다. |
