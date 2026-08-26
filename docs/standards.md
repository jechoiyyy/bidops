# 구현·검증 표준

이 표준은 현재 구현과 CI가 지켜야 할 불변식을 적는다. 새 기능의 추측이나 운영 승인 기록을 코드 상수로 대체하지 않는다.

## 경계와 데이터

- `skills/bidops-collect`, `bidops-screen`, `bidops-report`는 subprocess/file contract 경계다. 웹이 내부 skill module을 import하거나 같은 동작을 복제하지 않는다.
- 모든 JSON에는 명시적 `schema_version`이 있다. 의미를 바꾸면 새 schema version을 만들고 기존 파일을 소급 변경하지 않는다.
- `screening-input.v1`, `decisions.v3`, failures/telemetry는 execution ID·run/window·policy/prompt/model/profile identity를 역추적할 수 있어야 한다.
- 승계는 `carried_over=true`와 최초 `judged_in_run`/현재 `recorded_in_run`을 보존한다. 승계를 신규 호출처럼 기록하거나 missing binding을 추정하지 않는다.
- 모델/검증기는 `unknown`, `null`, `계산 불가`, `값 없음`을 확정값·0·빈 문자열로 치환하지 않는다. deterministic validator는 grade/readiness를 보정하지 않는다.

## 모델·근거·품질

- 모델은 정확히 `qwen3.8:27b`, Ollama digest를 execution에 묶고 `think=false`, `stream=false`를 사용한다. OpenAI/BF16 fallback은 없다.
- 신규·재판정은 다섯 unique perspective + counterargument + synthesis의 7 span을 호출한다. 승계는 model call 없이 carry-over validation을 한다.
- timeout/truncated/schema/evidence/repetition은 최대 2 attempts bounded retry 후 실패 목록과 사람 검토 상태로 남긴다. 잘린 response를 이어 붙여 성공으로 만들지 않는다.
- 근거는 source/status/fact와 검증 가능한 위치를 가져야 하며, 모델의 자기검증 문장을 근거로 삼지 않는다.
- fixed quality gate는 40건 A/B다. `model_comparison`과 `operational_approval`의 profile source를 섞지 않고, pass만으로 activation하지 않는다. threshold는 [모델 품질 게이트](./model-quality-gate.md)와 동일하다.

## 불변성·보안

- profile/policy/prompt/model/input/artifact binding은 실행 생성 뒤 바꾸지 않는다. profile `current`는 bytes snapshot, 역사 비교는 승인된 Git commit과 vendored digest를 검증한다.
- DB는 SQLite WAL/foreign keys와 Alembic head를 사용한다. 앱 start/container entrypoint는 migrate, `create_all`, seed를 하지 않는다. migration은 중지된 서비스, retained backup manifest, explicit confirm으로만 수행한다.
- FIFO는 queue_no 오름차순, active slot과 max concurrency는 1이다. heartbeat stale recovery는 중단으로 끝나며 자동 resume/재시작을 만들지 않는다.
- artifact는 known filename, symlink/path escape 검사 후에만 읽고 쓰며 API는 내부 저장 경로를 조합하지 않는다.
- API key, `.env`, Ollama credential, 원문 첨부, run data, prompt/response body를 image/Git/log/audit에 넣지 않는다. 오류·audit에는 안전한 상태·원인 요약만 둔다.
- `BIDOPS_SCHEDULER_ENABLED=false`와 DB always-on false를 기본으로 하고, gate pass·seed·startup이 activation/always-on을 자동 수행하지 않는다.

## API·UI·파일

- FastAPI 요청/응답은 명명된 Pydantic schema를 사용하고 상태/오류를 임의 dict로 새로 만들지 않는다. 422(계약), 404(존재), 409(상태/중복/활성화), 503(preflight) 의미를 보존한다.
- 프론트엔드는 API만 사용하고 SQLite·`data/runs`·첨부 루트를 읽지 않는다. TypeScript strict build와 lockfile 기반 설치를 통과해야 한다.
- 파일은 UTF-8과 schema version을 사용한다. full run publish는 새 파생 디렉터리에만 쓰고 원 run/review/files를 수정하지 않는다. partial/failed/stopped 결과를 성공으로 숨기지 않는다.

## 검증 명령

소스/가짜 모델 테스트는 live endpoint·API key 없이 실행한다.

```bash
./run-tests.sh
./web/run-web-tests.sh
```

`web/run-web-tests.sh`는 private temporary DB에서 `alembic upgrade head`, backend pytest, frontend production build를 수행해야 한다. DB migration 검증은 실제 운영 DB가 아닌 복사본에서 한다. visual은 `cd web/frontend && npm run test:visual`이며 host browser prerequisite가 없으면 [운영 절차](./operations.md)의 Playwright image command를 사용한다. Docker image는 `docker compose build`로 확인한다.

CI는 fake-only다. live Ollama는 `BIDOPS_LIVE_OLLAMA_TEST=true`와 operator가 명시한 단일 CLI command/marker가 모두 있을 때만 실행할 수 있다. marker alone은 실행 허가가 아니며, T14/T15는 operator direction 없이 live smoke·policy activation·always-on을 하지 않는다.

검증 출력·상태는 [tracking/status](./tracking/status.md)에 실제로 통과한 범위만 기록한다. 결과·ID·수치를 생성해 채우지 않는다.
