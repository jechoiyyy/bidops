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
| `BIDOPS_OLLAMA_ENDPOINT` | `http://192.168.0.139:11434` | 사내 Ollama HTTP 엔드포인트다. 환경별 주소는 이 변수로 주입한다. |
| `BIDOPS_OLLAMA_MODEL` | `qwen3.8:27b` | 1차 판정에 사용할 모델 이름이다. |
| `BIDOPS_OLLAMA_FORMAT` | `json` | 응답 형식을 `json`으로 고정한다. JSON 외 안내문이 섞인 응답은 성공으로 인정하지 않는다. |
| `BIDOPS_OLLAMA_TEMPERATURE` | `0` | 결정적 기준선의 생성 온도다. 변경 필요성은 품질 게이트에서 별도 측정한다. |
| `BIDOPS_OLLAMA_TIMEOUT_SECONDS` | 1차 판정 실측 후 확정 | 호출별 시간 제한이다. 실제 응답 분포를 측정하기 전에는 운영 확정값으로 쓰지 않는다. |
| `BIDOPS_OLLAMA_CONTEXT_SIZE` | 1차 판정 실측 후 확정 | 관점별 입력 묶음의 최대 토큰과 모델 한계를 측정해 정한다. 회사 프로필 전문을 넣지 않는 전제에서 산정한다. |
| `BIDOPS_OLLAMA_MAX_OUTPUT_TOKENS` | 1차 판정 실측 후 확정 | 관점·반론·종합의 제한 JSON이 완결되는 호출별 출력 상한이다. 파일럿의 가정값을 운영 확정값으로 복사하지 않는다. |
| `BIDOPS_OLLAMA_KEEP_ALIVE` | 1차 판정 실측 후 확정 | 회차 실행 창 동안 모델이 내려가지 않도록 설정하는 유지 시간이다. 설정 후 모델 적재가 발생한 호출 비율을 측정한다. |
| `BIDOPS_OLLAMA_THINK` | `false` | 내부 추론 사용 여부다. `false`로 고정하며 `true`가 주입되면 설정 오류로 사람 검토 대기 처리한다. |
| `BIDOPS_SCREEN_MAX_CONCURRENCY` | `1` | 단일 Ollama 인스턴스의 최대 동시 호출 수다. 양의 정수로 설정하며 증가는 1차 판정 실측 뒤 결정한다. |
| `BIDOPS_SCHEDULER_ENABLED` | `false` | 웹 프로세스 기동 시 일간·주간 예약을 등록할지 결정한다. |
| `BIDOPS_SCHEDULE_DAILY_TIME` | `02:00` | 다음 날 실행할 전일 회차의 기본 시각이다. 설정으로 조정할 수 있다. |
| `BIDOPS_SCHEDULE_WEEKLY_TIME` | `06:00` | 월요일에 전 주 누계를 만드는 기본 시각이다. 설정으로 조정할 수 있다. |
| `BIDOPS_PRESPEC_ENABLED` | `false` | 사전규격 API 호출 여부다. 권한 확보 뒤 담당자 승인 절차에서 `true` 적용 여부를 결정한다. |

이번 설계로 Ollama와 스케줄 실행 설정의 환경변수 계약을 위 표에 반영했다. HWPX 변환기와 OpenAI 활성화·키, 정책 저장 위치에 대한 운영 설정은 아직 코드 계약이 없으므로 구현 시 `BIDOPS_` 접두사와 비밀 분리 규칙에 맞춰 추가한다.

## 상시 운영 개시

상시 운영 스위치는 품질 게이트와 담당자 승인 전까지 `BIDOPS_SCHEDULER_ENABLED=false`로 둔다. 다음 순서를 모두 마친 뒤에만 예약 실행을 켠다.

1. 공공데이터포털에서 사전규격 API 활용 권한을 신청하고 승인 여부를 확인한다. 권한이 없는 동안에는 `BIDOPS_PRESPEC_ENABLED=false`로 둔다. 이 상태에서도 본공고 수집은 계속할 수 있어야 하며, 사전규격 권한 부족을 회차 전체 실패로 만들지 않는다.
2. `BIDOPS_OLLAMA_ENDPOINT`에 연결하고 `BIDOPS_OLLAMA_MODEL`이 응답하는지 확인한다. 응답 형식은 `json`, 온도는 기준선 `0`, 내부 추론은 `BIDOPS_OLLAMA_THINK=false`인지 함께 확인한다. 연결 실패를 OpenAI 호출로 자동 대체하지 않는다.
3. 현재 모델·프롬프트·정책 버전과 고정 표본으로 품질 게이트를 측정한다. 최종 등급 재현성은 80% 이상이어야 하며 다섯 관점별 일치율도 기록하고 불일치가 어느 한 관점에 절반을 넘게 몰리지 않아야 한다. 유효 판정 대상이 10건 이상이면 변별력은 10~25% 구간이어야 하며, 10건 미만이면 `계산 불가(소표본)`으로 기록한다. 유효 담당자 리뷰는 10건 이상이어야 하며 `동의` 70% 이상과 `근거 부족` 10% 이하를 모두 충족해야 한다. 관점 분할은 40% 이상이어야 한다. 정보 충분성도 정량화해야 하며 별도 합격 수치가 없는 항목을 통과값으로 바꾸지 않는다. 두 축 혼입 검출 결과는 사람 검토로 보내고 등급을 자동 보정하지 않는다. 필요한 값이 미측정·`계산 불가`이거나 임계값을 충족하지 못하면 운영을 켜지 않는다.
4. 담당자가 게이트 결과, 모델·프롬프트·정책 버전과 운영 설정을 화면에서 확인하고 상시 운영을 명시적으로 승인한다. 승인 뒤 `BIDOPS_SCHEDULER_ENABLED=true`를 적용하며, 사전규격 권한이 승인된 경우에만 `BIDOPS_PRESPEC_ENABLED=true`를 적용한다. 권한이 아직 없으면 사전규격 스위치는 `false`로 남긴다. 이 승인은 입찰 참여나 최종 Go/No-Go 결정을 대신하지 않는다.

게이트 결과와 스위치 변경 시각은 관리 이력에 남긴다. 새 모델·프롬프트·정책 버전은 별도 측정과 게이트 통과 없이는 상시 운영에 사용하지 않는다.

## 회차 실패 확인과 재실행

실행 결과와 실패는 관리 화면에서만 확인한다. 메일·메신저 등 외부 알림을 추가하지 않는다.

1. 담당자는 회차 목록과 상세 화면에서 상태, 대상 공고 수, 유효 판정 수, 실패 수, 경고, 실패 목록, 회차의 모델·프롬프트·정책 버전을 확인한다. 실행 시각을 놓쳤거나 웹 프로세스가 내려간 경우에도 날짜별 회차를 합치지 않고 누락된 회차를 각각 확인한다.
2. 판정 실패 건은 실패 목록의 `notice_id`, 실패 단계, 실패 유형, 마지막 시도 시각과 관리 화면의 계측 기록을 대조한다. 타임아웃·잘린 출력·스키마 위반·근거 누락 등은 병합 입력에 넣지 않고 `사람 검토 대기`로 남긴다. 모델 출력이나 등급을 자동 보정하지 않으며, 승인 없는 OpenAI 호출로 바꾸지 않는다.
3. 유효한 신규 판정과 검증된 승계 판정이 남은 회차는 `부분 성공`으로 확인한다. 부분 성공 회차를 성공으로 승격하지 않고, 성공한 산출물·실패 목록·경고를 함께 보존한다. 승계 판정은 새 판정으로 표시하지 않으며, 검증에 실패한 승계 판정도 실패 목록으로 보낸다.
4. 담당자가 원인을 확인한 뒤 회차 상세 화면에서 재실행을 명시적으로 요청한다. 복구 실행은 기존 `실패`·`부분 성공` 회차를 되돌리거나 덮어쓰지 않고 새 실행·스냅샷으로 기록하며 원래 회차와의 관계를 남긴다. 실패 공고만 재실행하는 경우에도 새 호출과 계측을 남기고, 회차 전체를 재실행하는 경우에도 기존 원문·판정·리뷰를 보존한다.
5. 재실행 후 화면에서 새 상태와 누락 건수를 다시 확인한다. 결정적 검증에 실패한 결과는 성공 결과로 바꾸지 않으며, 정본 결과를 만들 수 없으면 `실패`, 일부 검증된 결과만 남으면 `부분 성공`으로 유지한다.

## 백업과 복구

초기 보존 기간은 제한하지 않는다. 매일 생성되는 `data/runs`의 일간 회차 디렉터리와 그 안의 원문·정규화·판정·실패 목록·경고·계측 기록, SQLite, 수동 첨부 디렉터리, `reports`, 활성·과거 정책 버전을 같은 시점의 묶음으로 정기 백업한다. 정책은 저장할 때 새 불변 버전을 만들므로 새 정책 버전이 누락되지 않게 함께 보관한다. SQLite는 실행 중 파일 복사 대신 SQLite 백업 API 또는 서비스를 중지한 뒤 복사해야 한다. Docker named volume을 사용할 때는 볼륨 내부 DB와 첨부를 모두 포함한다.

복구 검증은 운영본이 아닌 별도 경로에서 수행한다.

1. 백업을 빈 데이터 경로에 복원한다.
2. 복원 경로를 `BIDOPS_DATA_DIR`과 프로젝트 루트 설정으로 가리킨다.
3. API를 기동해 회차 수, 임의 리뷰, 수동 첨부 다운로드, 정책 버전을 확인한다.
4. YAML 내보내기를 실행하고 DB 리뷰와 건수를 대조한다.

일간 회차가 쌓이는 주기에 맞춰 최소 하루 한 번, 해당 회차의 적재와 보고서 생성이 끝난 뒤 백업한다. 실제 저장 용량·백업 소요 시간·복구 목표를 측정한 뒤 보존 기간, 외부 보관 위치와 전체·증분 방식은 사내 운영 환경에 맞춰 확정한다.

## 장애 확인

| 증상 | 확인과 조치 |
|---|---|
| 화면은 503, API health는 정상 | `web/frontend`에서 `npm run build` 후 `dist/index.html` 존재를 확인한다. |
| 회차가 비어 있음 | `python -m app.ingest.cli --all` 실행 여부와 `data/runs` 위치를 확인한다. |
| 수집 건수가 값 없음 | `collected-notices.json` 부재 여부를 확인한다. 필요하면 API 키로 수집한다. |
| 첨부 업로드 거부 | HWP/HWPX/PDF, 50MB 이하인지 확인한다. 우회 확장자로 바꾸지 않는다. |
| Docker 파일 삭제 불가 | 호스트 UID/GID를 `.env`에 설정하고 컨테이너를 재생성한다. |
| 8787 포트 충돌 | 백엔드 포트를 바꾸고 개발 모드라면 Vite 프록시 대상도 함께 바꾼다. |
