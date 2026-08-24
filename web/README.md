# BidOps Admin 웹

## 설치

백엔드와 프론트엔드 의존성을 각각 설치합니다.

```bash
cd web/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd ../frontend
npm install
```

## 개발 실행

프론트엔드 개발 서버는 `/api`를 8787 포트 백엔드로 프록시합니다.

```bash
# 터미널 1
cd web/backend
.venv/bin/uvicorn app.main:app --reload --port 8787

# 터미널 2
cd web/frontend
npm run dev
```

개발 화면은 `http://localhost:5173`에서 엽니다.

## 산출물 적재

저장소의 `data/runs` 아래 회차를 SQLite에 적재합니다. `--all`은 발견된 모든 회차를 적재합니다.

```bash
cd web/backend
.venv/bin/python -m app.ingest.cli --run 20260817-20260823
# 또는
.venv/bin/python -m app.ingest.cli --all
```

기본 데이터베이스는 `web/data/bidops.db`이며, `BIDOPS_DATABASE_URL` 등 환경 변수로 경로를 바꿀 수 있습니다. `.env`의 비밀 값은 API 응답에 포함되지 않습니다.

## 운영 형태 실행

프론트엔드를 먼저 빌드하면 FastAPI가 빌드 산출물을 정적으로 서빙합니다. `/api`가 아닌 클라이언트 경로는 `index.html`로 폴백합니다.

```bash
cd web/frontend
npm run build

cd ../backend
.venv/bin/uvicorn app.main:app --port 8787
```

`http://localhost:8787`에서 전체 관리자 화면을 엽니다. `dist`가 없더라도 백엔드는 기동하며, 화면 요청에는 빌드가 필요하다는 503 응답을 반환합니다.

## 테스트

웹 계층 백엔드 테스트와 프론트엔드 타입 검사·빌드를 한 번에 실행합니다.

```bash
./web/run-web-tests.sh
```

저장소 루트의 `run-tests.sh`는 기존 파이프라인 테스트 진입점이므로 웹 테스트 스크립트에서 변경하지 않습니다.
