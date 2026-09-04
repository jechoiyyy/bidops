# 입찰공고·사전규격·리뷰 종단 채우기 절차

기준일: 2026-09-04

이 절차는 현재 실행 중인 애플리케이션 스택(Compose 프로젝트 `bidops`)에서 `notice`(입찰공고·사전규격), `judgment`(모델 1차 판정),
`review`(사람 검토) 테이블을 채우고, 그 데이터가 관리 화면까지 렌더링되는지 확인하는 순서다.
발주계획 종단 실행(`docs/validation-runs/20260902-order-plan-c2-phases2-4.md`)과 같은 스택에서
이어서 수행한다.

## 2026-09-04 확인 상태

프론트엔드 → 백엔드 → PostgreSQL 연결은 확인됐다. 확인 방법과 결과는 다음과 같다.

- web 컨테이너 하나가 React 빌드 결과와 FastAPI를 같은 프로세스에서 서빙하고, DB URL은 Compose 내부 `postgres` 서비스를 가리킨다.
- headless 브라우저로 대시보드·`/order-plans`·`/opportunities`·`/runs`를 열었을 때 `/api/*` 요청 17종이 모두 200으로 응답했고 콘솔 오류는 없었다.
- 화면의 사업기회 #1040 제목과 발주계획 C-2 "검토 대상 156건"이 DB의 `order_plan`·`order_plan_screening_result` 값과 일치했다.

| 테이블 | API total | DB count |
|---|---|---|
| `order_plan` | 1,040 | 1,040 |
| `opportunity` | 1,040 | 1,040 |
| `run` | 2 | 2 |
| `notice`(공고·사전규격) | 0 | 0 |
| `judgment`, `review` | 0 | 0 |

## 먼저 알아야 할 구조

- **사전규격은 별도 테이블이 아니다.** `notice` 테이블에 `source_type=pre_spec`으로 저장되고
  `/api/pre-specs`가 거기서 읽는다. `pre_spec`은 `first_registered_stage`의 값일 뿐이다.
- **"리뷰"는 두 테이블이다.** `judgment`는 모델 1차 판정이고 회차 산출물
  `screening-results.json`에서 적재된다. `review`는 사람이 화면에서 저장한 검토이며
  `/api/notices/{notice_pk}/review`로만 생성된다.
- **적재 입력은 회차 디렉터리의 파일 계약이다.** `app.lifecycle.ingest.cli --run <회차>`가
  `validation-set.json`, `screening-input.json`, `collected-notices.json`,
  `screening-results.json`, `screening-decisions.json`, `collected-order-plans.json` 중 있는 것을 읽는다.
- **web 컨테이너에는 나라장터 API 키가 없다.** 호스트 `.env`의 `BIDOPS_G2B_API_KEY`로 수집기를
  호스트에서 실행하고, 결과 디렉터리만 `pipeline-data` volume으로 복사한다.
- **모델 판정은 현재 스택에서 돌지 않는다.** web의 `BIDOPS_OLLAMA_BASE_URL`이 127.0.0.1이다.
  새 회차에 판정을 붙이려면 `docker-compose.mock-reference.yml`로 web·analysis-worker를
  재기동해야 하며, mock 판정은 화면 흐름 확인용이지 품질 근거가 아니다.

## 실행 순서

컨테이너 이름은 Compose 프로젝트 `bidops` 기준이다. 2026-09-04에 `bidops-e2e-t7` 프로젝트의 volume을
복제해 이 이름으로 재기동했고, 발주계획 1,040건과 C-2 실행 결과는 그대로 보존됐다(`docs/docker-consolidation.md`).

### 1. 기존 공고 회차 적재 (모델·외부망 불필요)

호스트 `data/runs/20260817-20260823`에 공고 40건(`validation-set.json`)과 모델 판정 40건
(`screening-results.json`, `screening-decisions.json`)이 이미 있다. 사전규격은 없다.

```bash
docker compose -p bidops -f docker-compose.yml \
  cp data/runs/20260817-20260823 web:/app/data/runs/
docker compose -p bidops -f docker-compose.yml \
  exec web python -m app.lifecycle.ingest.cli --run 20260817-20260823
```

기대 결과: `run` +1, `notice` 40, `judgment` 40. `/api/runs/20260817-20260823/warnings`에
차단 경고가 없어야 한다. 부분 산출물 경고가 있으면 원인을 적고 다음 단계로 넘어가지 않는다.

### 2. 화면 확인 1차

- `/runs`에 새 회차가 보인다.
- `/queue`, `/judgments`를 `?run=20260817-20260823`으로 열면 40건이 렌더링된다.
- DB의 `notice.title` 몇 건을 화면 문자열과 대조한다.

확인은 `web/frontend`에서 Playwright chromium을 headless로 띄워 `/api/*` 응답 코드와 본문
텍스트를 수집하는 방식이 재현 가능하다. viewport는 1440x900을 쓴다.

### 3. 사람 검토 1건 저장으로 `review` 채우기

`/judgments/:noticePk` 화면에서 검토 의견을 저장한다. 같은 동작이 `/api/notices/{notice_pk}/review`다.

기대 결과: `review` 1, `review_revision` 1. `/api/notices/{notice_pk}/revision-history`와 화면의
검토 이력에 같은 내용이 보인다.

회차 디렉터리에 `review-feedback.yaml`을 넣고 재적재하는 일괄 경로도 있지만, 화면 연결 확인이
목적이면 UI 저장이 더 직접적이다.

### 4. 사전규격 회차 새로 수집 (호스트에서, API 키 사용)

이 단계는 나라장터 OpenAPI를 호출한다. 날짜 범위와 키 사용은 담당자가 정한다.

```bash
python3 skills/bidops-collect/scripts/collect_notices.py \
  --from-date <YYYY-MM-DD> --to-date <YYYY-MM-DD> \
  --output-dir data/runs/<회차> --timeout 300
```

- 기본 timeout 30초는 발주계획 수집 때처럼 부족할 가능성이 크다. 300초로 시작한다.
- 결과는 `collected-notices.json` 하나에 입찰공고와 사전규격이 함께 들어간다.
  사전규격만 필요하면 `--skip-bids`를 준다.
- 원문 페이지는 `<회차>/raw/`에 보존되므로 재분류는 `--from-raw`로 API 호출 없이 반복한다.

### 5. 새 회차 적재와 화면 확인 2차

1단계와 같은 cp·ingest를 새 회차에 반복한다.

- `/api/pre-specs` total과 DB의 `notice where source_type='pre_spec'` 건수가 같다.
- `/pre-specs` 화면에 사전규격 제목이 보인다.
- `/opportunities`에서 "신규 · 사전규격에서 처음 등장" 필터가 새 기회를 보여준다.

### 6. (선택) 새 회차에 모델 판정 붙이기

`/runs` 화면의 표본 선정과 판정 실행을 쓰려면 mock 판정 overlay로 재기동한다.

```bash
docker compose -p bidops \
  -f docker-compose.yml -f docker-compose.mock-reference.yml \
  up -d web analysis-worker
```

- mock 판정의 `model_digest`는 `MOCK_MODEL_DIGEST` 상수로 남는다. 실제 모델 산출과 구별하는 기준이다.
- 사전규격 첨부 다운로드는 별도 allowlist overlay와 host firewall 승인이 필요하므로 이 절차의 범위에서 제외한다.

## 합격 조건

- 1·3·5단계 뒤 각각 API total과 DB count가 일치한다.
- 화면에서 읽은 제목·건수가 DB 값과 같고, 브라우저 콘솔 오류가 없다.
- 적재 경고에 차단 등급이 없다. 있으면 `docs/tracking/findings.md`에 재현 조건과 함께 기록한다.
- 결과 증거는 `docs/validation-runs/<날짜>-lifecycle-fill.md`에 남긴다.
