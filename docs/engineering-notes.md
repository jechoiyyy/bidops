# 엔지니어링 노트

## 발주계획에서 선택된 건만 저장하면 비교 실험을 재현할 수 없다

- 증상: 선별 결과의 정밀도는 보이지만 놓친 사업과 방식별 순위 차이를 다시 계산할 수 없다.
- 원인: 선택 결과만 저장하고 원본 모집단, 정책 버전, 방식별 점수와 제외 사유를 버렸다.
- 대응: 동결한 수집 회차의 전체 정규화 레코드와 source hash를 불변으로 보존한다. 키워드·ColBERT·Qwen·외부 참조 모델의 점수, 순위, 사유, 버전과 사람 정답을 별도 필드로 저장하고 같은 표본에서 재평가한다.

## 사전규격을 선택된 발주계획의 하위 단계로만 수집하면 공고를 놓친다

- 증상: 사전규격 API에는 제안요청서가 공개됐지만 대시보드에는 기회가 생기지 않는다.
- 원인: 모든 사전규격에 발주계획이 선행하거나 공식 연결된다고 가정했다.
- 대응: 사전규격은 발주계획 선택 여부와 무관하게 매일 독립 수집한다. 공식 번호로 연결할 수 없으면 새 내부 기회로 만들고, 유사도 연결은 사람 확인 전까지 후보로만 둔다.

## 월·목 수집만으로는 짧은 사전규격 공개기간을 놓칠 수 있다

- 증상: 월요일 검토 뒤 공개된 사전규격이 목요일 검토 전에 마감되거나 대응 시간이 짧아진다.
- 원인: 사람 검토 주기와 외부 원천 수집 주기를 같은 일정으로 묶었다.
- 대응: 발주계획과 사전규격 수집은 매일 실행하고, 발주계획 사람 검토 큐만 월·목에 연다. 수집 시각, 최초 발견 시각, 마감 시각을 별도로 보존한다.

## 레코드 수를 API 호출 수로 계산하면 일일 할당량을 잘못 판단한다

- 증상: 3일치 1,200건을 받는 작업이 1,200회 호출로 표시되거나, 반대로 pagination과 재시도를 무시해 한도를 넘는다.
- 원인: 한 응답의 레코드 수, 페이지 수, endpoint 수, 재시도 횟수를 구분하지 않았다.
- 대응: endpoint·조회 창·페이지별 실제 요청 수를 계측하고 응답을 회차 cache로 재사용한다. 개발계정은 일 1,000회 한도 안에서 경고 700회, 신규 호출 중지 900회를 기본 운영선으로 두고 실제 관측 후 조정한다.

## 모델이 만든 정답으로 모델을 평가하면 성능이 부풀려진다

- 증상: GPT 계열 참조 판정과 유사한 모델이 높은 점수를 받지만 사람이 중요한 사업을 놓쳤다고 판단한다.
- 원인: Sol xhigh 같은 모델 출력을 최종 정답으로 간주해 같은 계열 편향과 회사 맥락 오류를 평가에 복제했다.
- 대응: 모델 판정은 silver reference와 이견 탐색에만 사용한다. 동결 표본의 최종 relevance와 우선순위는 사람이 판정하고, 불일치는 별도 adjudication 사유로 기록한다.

## 제목 유사도로 생애주기 관계를 확정하면 다른 사업이 합쳐진다

- 증상: 비슷한 사업명의 발주계획, 사전규격, 입찰공고가 한 기회로 묶여 예산·기관·첨부가 섞인다.
- 원인: 공식 통합번호가 없는 상태에서 제목 유사도를 확정 키로 사용했다.
- 대응: 공식 식별자 관계만 자동 확정한다. 기관, 예산, 시기, 사업명 유사도는 연결 후보와 점수를 만들 뿐이며, 사람 확인 뒤에만 내부 기회 관계를 확정한다.

## 대형 단일 Qwen 호출이 끝나지 않거나 숫자를 틀린다

- 증상: 약 81페이지 HWP 입력이 11만 토큰을 넘고, 사고 출력이 길이 제한에 걸리거나 요구사항·하드게이트 수가 원문과 달라진다.
- 원인: 문서 구조화, 전 영역 판단, 보고서 작성, 자기검증을 한 호출에 맡겼다. 자연어 자기검증은 결정적 검사가 아니다.
- 대응: 문서 구조화 → 자격 → 요구사항 묶음 → 평가 → 위험 → 종합으로 분할하고 제한된 JSON으로 받는다. ID, 배점, 금액, 기간은 코드로 원문과 대조한다.

## 소방예방정보시스템 사례의 요구사항 수가 54와 55로 갈린다

- 증상: 모델은 54개라고 쓰지만 HWPX 구조의 유일한 요구사항 ID는 55개다.
- 원인: 긴 표의 행·페이지 경계를 병합하거나 하나를 누락했고, 직접 텍스트 파싱에서 `COR-006`, `555.2`, `Requirement` 같은 내용도 잘렸다.
- 대응: 요구사항 표를 ID 기준으로 추출해 유일 개수·중복·누락을 먼저 계산한다. 해당 회귀 사례는 55개를 기대하는 검증 픽스처로 유지한다.

## HWP 텍스트 파서와 HWPX 변환 결과가 다르다

- 증상: HWP 직접 파싱에서 문장, 표 셀, 요구사항 ID가 빠지지만 HWPX 변환본에는 남아 있다.
- 원인: HWP 바이너리 스트림과 레이아웃 병합을 직접 파서가 모두 보존하지 못한다.
- 대응: 원본 HWP 보존 → 헤드리스 HWPX 변환 → 구조 추출 순서를 사용한다. 변환기 버전과 hash를 기록하고 표 수뿐 아니라 알려진 ID와 절단 문구를 대조한다.

## 값 없음과 0을 합치면 운영 지표가 뒤집힌다

- 증상: 원본 파일이 없는 회차, 리뷰가 없는 회차, 분모가 없는 지표가 0건 또는 0%로 보인다.
- 원인: 측정 불가와 실제 측정값 0을 같은 값으로 저장했다.
- 대응: 입력이 없으면 값과 사유를 `null`로 반환한다. UI는 빈 상태와 `계산 불가`를 표시하고 0으로 보정하지 않는다.

## 과거 부분 산출물은 보이지만 경고가 필요하다

- 증상: 관점·반론·확인 항목이 부족한 과거 판정이 화면에 표시된다.
- 원인: 엄격한 현재 생산 계약을 과거 표시 계층에도 적용하면 기존 리뷰를 전혀 열 수 없다.
- 대응: 식별자·등급·준비 상태가 없으면 판정을 거부한다. 그 밖의 필드는 존재하는 값만 적재하고 누락 경고를 API와 UI에 남긴다.

## 리뷰 파일과 DB가 다르면 DB가 정본이다

- 증상: `review-feedback.yaml`을 직접 바꿔도 적재된 리뷰가 바뀌지 않는다.
- 원인: 리뷰 정본이 PostgreSQL로 이동했고 YAML은 초기 가져오기와 호환 내보내기만 담당한다.
- 대응: 리뷰는 API로 수정하고 필요할 때 새 YAML을 내보낸다. 재적재가 기존 DB 리뷰를 덮어쓰지 않는지 확인한다.

## 프론트엔드 빌드가 없어도 백엔드는 기동된다

- 증상: `/api/health`는 정상인데 화면 경로는 프론트엔드 부재 503을 반환한다.
- 원인: FastAPI는 `web/frontend/dist/index.html`이 있을 때만 SPA를 마운트한다.
- 대응: API 상태와 `dist/index.html` 존재를 따로 확인한다. 프론트엔드를 production build한 뒤 화면을 다시 검사한다.

## Docker 산출물 파일 소유자가 달라진다

- 증상: 컨테이너가 만든 파일을 호스트 사용자가 수정하지 못한다.
- 원인: 컨테이너 UID/GID와 호스트 계정이 다르다.
- 대응: 호스트 `id -u`, `id -g`를 비밀이 아닌 런타임 설정에 반영하고 0이 아닌지 검사한다. 새 산출물 소유권을 확인한다.

## 하위 프로세스 로그에 자격증명이 섞일 수 있다

- 증상: 환경변수나 `serviceKey`가 수집 로그, DB, API 오류에 남는다.
- 원인: 외부 오류와 stderr를 그대로 보존하거나 키 실제 값을 알기 전에 문자열만 필터링했다.
- 대응: 알려진 키 이름, 쿼리 문자열, 실제 주입값을 저장 전에 제거한다. 성공·실패 경로에서 실제 비밀값이 로그와 응답에 없는지 검사한다.

## 실제 screening 설명은 짧은 enum이 아니다

- 증상: 과거 회차 적재 중 `screening_basis` 길이 초과로 전체 transaction이 실패한다.
- 원인: 사람이 읽는 설명을 `varchar(64)` 코드값처럼 저장했다.
- 대응: `screening_basis`는 `TEXT`로 보존하고 절단하지 않는다. 깨끗한 PostgreSQL에서 같은 회차를 두 번 적재해 원문 길이와 멱등성을 확인한다.

## 읽기 전용 worker가 쓰기 자격증명을 고르면 권한 경계가 무너진다

- 증상: structure 읽기 client가 write credential을 선택한다.
- 원인: 일반 자격증명을 read credential의 fallback으로 사용했다.
- 대응: read namespace는 전용 read key만 사용하고 없으면 fail closed한다. client 생성 테스트에서 선택된 key namespace를 확인한다.

## 최신 bundle 확인과 document 수정은 같은 잠금 구간이어야 한다

- 증상: 최신 bundle 확인 직후 새 bundle이 생겨 오래된 lineage에 document 변경이 붙는다.
- 원인: 조회와 patch transaction 사이에 경쟁 구간이 있다.
- 대응: 같은 service transaction에서 notice → 최신 bundle → document 순서로 잠그고 ref ID, version, hash를 다시 검증한다. stale command는 `version_conflict`로 거부한다.

## 비ASCII 담당자 헤더 인코딩이 기존 ASCII 이름을 바꾸면 안 된다

- 증상: 한글 이름을 보낼 수 없거나 prefix처럼 보이는 ASCII 이름이 다른 값으로 복원된다.
- 원인: HTTP header 제약을 우회하는 in-band prefix를 무조건 해석했다.
- 대응: 비ASCII 이름만 명시적 UTF-8 percent 형식 헤더와 함께 보낸다. 서버는 형식 헤더가 있을 때만 복원하고 malformed·제어문자 입력은 거부한다.

## 컨테이너에서 만든 venv는 호스트에서 실행되지 않을 수 있다

- 증상: 컨테이너의 `web/backend/.venv`를 호스트 테스트가 실행하지 못한다.
- 원인: venv의 Python 링크가 컨테이너 절대 경로를 가리킨다.
- 대응: host 검증 venv는 host Python 3.12로 만든다. 컨테이너 검증은 이미지 내부 Python을 사용하고 bind mount에 venv를 만들지 않는다.

## 운영 Compose에서 파이프라인 디렉터리가 영속화되지 않으면 재시작 후 이력이 끊긴다

- 증상: 컨테이너 재생성 뒤 DB 레코드는 남지만 연결된 run·report 파일을 찾지 못한다.
- 원인: 애플리케이션 파일 경로가 임시 container filesystem에만 있다.
- 대응: 운영 전용 volume 또는 객체 저장 계약을 각 경로에 명시하고, 재시작·백업·복구 검증에서 DB 참조와 hash를 대조한다.

## host에서 백엔드 테스트를 돌리는 실행기가 저장소 안에 없다

- 증상: `python3 -m pytest`가 `No module named pytest`로 끝난다.
- 원인: 시스템 Python에는 개발 의존성이 없고 저장소에 host용 venv를 두지 않는다.
- 대응: host 검증용 venv를 만들어 `requirements.txt` 전체를 설치하고 그 절대 경로로 실행한다.
  `openai`, `minio`, `psycopg`, `cryptography`가 빠지면 18개 test module이 수집 단계에서
  `ImportError`로 죽는다. 부분 설치된 venv를 재사용하지 말 것.

## 백엔드 전체 스위트는 4분 넘게 걸리고 멈춘 것처럼 보인다

- 증상: `TestClient`를 쓰는 test module 구간에서 출력이 오래 없어 hang으로 보인다.
- 원인: 전체 스위트가 800개 가까운 테스트를 돌고 그중 API 구간이 느리다.
- 대응: 4분 30초까지는 기다린다. 위임한 에이전트가 "hang"이라고 보고해도 그대로 믿지 말고
  직접 한 번 돌려 확인한다. 지난 다섯 번의 위임에서 전부 정상 종료했다.
  **위임 결과는 전체 스위트 요약 줄로만 확인한다.**

## 프론트엔드 빌드가 rollup native 모듈 누락으로 깨진다

- 증상: `npm run build`가 `rollup/dist/native.js`에서 `MODULE_NOT_FOUND`로 실패한다.
  `npx tsc -b`는 통과한다.
- 원인: npm의 optional dependency 설치 버그로 플랫폼별 rollup 바이너리가 빠진다.
- 대응: `npm install @rollup/rollup-linux-x64-gnu --no-save`로 복구한다.
  타입 오류와 구분해야 하므로 `tsc -b`와 `npm run build`를 따로 돌린다.

## 선택 필드를 계약 모델에 더하면 기존 레코드의 저장 identity가 바뀐다

- 증상: 관계없는 `test_quality_gate.py` 여러 건이 "fixed quality run is invalid"로 깨진다.
- 원인: `ContractModel`의 기본값을 `_json_value`가 materialize하므로, 원본 artifact에 없던
  선택 필드가 모든 레코드의 저장 JSON에 `null`로 나타난다. digest로 고정된 fixture와 어긋난다.
- 대응: `_lifecycle_payload`·`_qualification_flags_payload`처럼 `model_fields_set`에 없는
  선택 필드를 저장 직전에 제거한다. 계약에 선택 필드를 더할 때마다 이 가드가 필요한지 확인한다.

## SQLite에서 통과한 마이그레이션이 PostgreSQL에서 전부 롤백된다

- 증상: `alembic upgrade head`가 중간 revision에서 `StringDataRightTruncation`으로 끝나고
  `alembic_version` table조차 만들어지지 않는다. 테스트 스위트는 전부 통과한다.
- 원인: PostgreSQL은 `VARCHAR(n)` 길이를 강제하고 SQLite는 무시한다. Alembic은 자기
  version table을 `VARCHAR(32)`로 만드는데 서술적인 revision 식별자가 그보다 길었다.
  PostgreSQL DDL이 트랜잭션이므로 한 revision의 실패가 실행 전체를 되돌린다.
- 대응: 길이를 강제하지 않는 dialect에서 통과했다는 것을 정본 저장소의 근거로 쓰지 않는다.
  스키마를 바꾸는 작업은 disposable PostgreSQL에서 `upgrade head`와 단계별 `downgrade`를
  실제로 돌려 확인한다. Docker가 있으면 `postgres:17` 컨테이너 하나로 충분하다.

## PostgreSQL 전용 테스트는 변수를 안 주면 조용히 skip된다

- 증상: 스키마를 바꿔도 관련 테스트가 깨지지 않는다. 나중에 실행해 보면 오래전에 없어진
  컬럼에 insert하고 있다.
- 원인: `tests/postgres.py`의 `requires_postgres`가 `BIDOPS_TEST_POSTGRES_URL` 없이는
  skip한다. skip은 초록으로 보이고 스위트 요약의 `skipped` 숫자는 잘 읽히지 않는다.
- 대응: 스키마를 바꾸면 그 변수를 주고 PostgreSQL 테스트를 한 번 돌린다.
  `pytest -q`의 `skipped` 개수가 늘어나거나 그대로인 것을 통과의 근거로 삼지 않는다.

## host에서 PDF가 전부 "손상된 문서"로 거부된다

- 증상: `DocumentProcessor.process()`가 정상 PDF에 `malformed_pdf`를 낸다. 같은 파일이
  컨테이너 안에서는 통과한다.
- 원인: 표준 PDF 파서가 실패하면 poppler로 fallback하는데, `pdftotext`·`pdfinfo`가 없으면
  fallback 자체가 `malformed_pdf`를 던진다(`processor.py:447-449`). `poppler-utils`는
  런타임 이미지에만 설치된다(`web/Dockerfile:48`).
- 대응: 문서 파이프라인을 측정할 때는 host가 아니라 런타임 이미지 안에서 돌린다.
  `docker run --rm --network none -v <표본>:/data -w /app/web/backend <web 이미지> python …`
  로 충분하다. host 결과로 "이 문서는 처리 못 한다"고 결론 내리지 않는다.
  HWP 변환기(Node + 벤더링된 rhwp)는 반대로 host에서도 동작하므로 형식마다 다르다.

## codex 위임이 조용히 아무 일도 하지 않거나 반쪽만 고친다

세 가지 방식으로 실패했고 셋 다 증상이 "성공한 것처럼 보인다"였다.

- **셸만 반환하고 프로세스는 계속 돈다**: `codex exec … &`처럼 배경으로 돌리면 래퍼가
  즉시 종료 코드 0을 돌려준다. 죽은 줄 알고 다시 띄우면 **두 프로세스가 같은 파일을
  동시에 고친다.** 실제로 한 번 겪었고 나중 프로세스가 앞선 프로세스의 편집을
  "이미 되어 있다"고 읽었다. 대응: `&`를 쓰지 말고, 재실행 전에 `pgrep -af "codex exec"`로
  살아 있는지 확인한다.
- **작업 디렉터리가 sandbox 범위를 정한다**: `sandbox_mode="workspace-write"`는 실행 시점의
  cwd를 기준으로 쓰기를 허용한다. 하위 디렉터리에서 띄우면 저장소 루트의 문서와 다른
  모듈을 고치지 못하고 중단한다. 셸 작업 디렉터리는 호출 사이에 유지되므로
  **실행 직전에 `pwd`로 확인한다.**
- **전체 스위트를 "환경 문제"로 단정한다**: 세 번의 위임 모두 `TestClient.__enter__`가
  정체한다며 uvloop로 우회하거나 요약 줄 없이 끝냈다. 직접 돌리면 기본 asyncio에서
  4분대에 정상 종료했다. **위임 결과의 스위트 요약 줄은 직접 돌려 확인한다.**

공통 대응은 하나다. 완료 보고를 근거로 쓰지 말고 전체 스위트와 바뀐 파일을 직접 본다.


## 이름만으로 고른 locator는 화면이 자라면 조용히 다른 것을 누른다

- 증상: Playwright가 `strict mode violation: getByRole('alert') resolved to 2 elements`로
  실패한다. 부하가 높을 때만 나오는 것처럼 보여 flake로 넘기기 쉽다.
- 원인: 두 가지가 겹친다. (1) 화면에 같은 이름·같은 role의 요소가 하나 더 생겼다.
  `getByRole("alert")`는 화면에 alert가 하나뿐이라는 가정이고, `getByRole("link", {name})`도
  사이드바와 본문이 같은 이름을 쓰면 깨진다. (2) **통과하던 실행이 오히려 잘못된 것이다.**
  lazy chunk가 아직 안 그려졌거나 query가 아직 안 끝난 순간을 눌러 요소가 하나뿐이었을 뿐이다.
  즉 초록이던 동안 그 테스트는 자기가 검사한다고 적어 둔 상태를 검사하지 않고 있었다.
- 대응: 부하 탓으로 넘기기 전에 **단독으로 그 파일만 돌려 본다.** 2026-09-01에 이 방식으로
  `document-preparation.spec.ts:349`가 flake가 아니라 결정적 실패임을 확인했다. 원인은
  `mockDocumentPreparation`에 `/api/pre-specs`가 없어 추적 결정 구역이 늘 오류 alert를
  띄우고 있던 것이었다. 고칠 때는 둘 다 한다 — locator를 의미 있는 컨테이너로 좁히고
  (`page.locator(".mutation-feedback")`), 화면이 조회하는 경로를 fixture에 빠짐없이 넣어
  검사 대상이 정의된 상태에서 돌게 한다.
- 재발 방지: 화면에 새 구역을 붙이면 그 구역이 부르는 API를 **기존 spec의 fixture에도**
  넣는다. 새 구역만 보는 fixture(`mockDocumentPreparationVisual`)에 넣는 것으로는 부족하다.

## 전체 스위트가 초록인데 `python -m` 진입점은 순환 import로 죽는다

- 증상: `pytest tests/` 는 통과하는데 `python -m app.screening.cli --help` 가
  `ImportError: cannot import name 'IngestResult' from partially initialized module
  'app.ingest.loader' (most likely due to a circular import)` 로 끝난다.
- 원인: 패키지 `__init__.py` 가 import 시점에 자기 하위 모듈을 끌어오면, 그 하위 모듈을
  거쳐 다시 패키지로 돌아오는 순환이 생긴다. 2026-09-04 이주에서
  `app/ingest/loader.py` → `app.lifecycle.models` → `app/lifecycle/__init__.py` →
  `app/lifecycle/api.py` → `app.ingest.loader` 가 그랬다. **pytest 는 이 결함을 가린다.**
  conftest 가 앱을 먼저 세우면서 패키지가 다른 순서로 초기화되기 때문에 순환이 드러나지
  않는다. 단독 진입점은 그 순서를 거치지 않으므로 죽는다.
- 대응: 모듈 패키지의 `__init__.py` 가 import 시점에 **아무것도 끌어오지 않게** 한다.
  `{공개 이름: (모듈, 속성)}` 표를 두고 모듈 `__getattr__` 로 처음 접근할 때 해석한다
  (`app/lifecycle/__init__.py` 참고). 공개 이름 목록과 사용법은 그대로 유지된다.
- 재발 방지: 진입점은 **새 인터프리터에서 `python -m <진입점> --help` 를 실제로 실행하는**
  테스트로 지킨다(`tests/app/test_module_cli_entrypoints.py`). `main` 을 직접 import 해서
  부르는 테스트는 같은 이유로 이 부류를 못 잡는다.

## `pytest tests/<하위 디렉터리>` 만 지정해도 PostgreSQL harness 가 뜨지 않는다

- 증상: `pytest tests/app -q` 가 T14 관련 4건 실패로 끝난다. 같은 파일을 직접 지정한
  `pytest tests/app/test_integration_t14.py -q` 는 8건 전부 통과한다.
- 원인: `tests/postgres.py` 의 `postgres_harness_requested` 는 `tests/` 디렉터리 전체,
  명시적 `BIDOPS_TEST_POSTGRES_URL`, 또는 그 파일을 이름으로 지정한 경우에만 폐기 가능한
  PostgreSQL 17 을 띄운다. 하위 디렉터리 선택은 그 조건에 걸리지 않는다.
  위의 "조용히 skip 된다" 항목과 같은 뿌리이고, 이쪽은 skip 이 아니라 **실패**로 나타난다.
- 대응: 판정 기준으로 삼는 실행은 `tests/` 디렉터리 전체를 지정하거나
  `BIDOPS_TEST_POSTGRES_URL` 을 준다. 하위 디렉터리만 돌린 결과를 회귀 판단의 근거로
  쓰지 않는다. 모듈 격리 검증처럼 폴더를 지정해야 하는 경우에는
  `web/backend/scripts/verify_module_isolation.sh` 처럼 스크립트가 직접 PostgreSQL 을
  띄우고 skip 건수와 사유를 조합마다 출력하게 한다.

## Tailwind `@theme`의 토큰이 Astryx 테마를 조용히 이긴다

- 증상: `astryx theme build`로 테마 색을 바꿔도 앱에서 일부 색만 바뀌지 않는다. 테두리가 계속 이전 팔레트 색이고, 상태 배지의 성공·경고·실패 색이 테마 값과 다르다. 빌드된 테마 CSS를 열어 보면 값은 제대로 들어 있다.
- 원인: Tailwind 4의 `@theme { }` 블록은 값을 **`:root`에 방출**한다. Astryx 테마는 `@layer astryx-theme` 안의 `@scope([data-astryx-theme="…"])`에 있다. CSS cascade 에서 **unlayered 선언이 어떤 layer 보다도 강하므로**, 이름이 같은 토큰은 selector 특이성이나 scope 근접성과 무관하게 항상 `:root` 쪽이 이긴다. 2026-09-04 기준 `--color-border`·`--color-success`·`--color-warning`·`--color-error`·`--color-accent` 다섯 개가 겹쳐 있었다.
- 대응: 디자인 시스템 토큰과 이름이 겹치는 legacy 토큰을 `@theme`에서 없애고 테마가 소유하게 한다. 의미가 다른데 이름만 같은 것(shadcn의 hover 표면 `--color-accent`)은 접두사를 붙여 옮긴다(`--color-shadcn-accent`). 이행 중 legacy 이름이 필요하면 `:root`가 아니라 **테마 scope 안의 단일 bridge**에서 `var(--color-*)`로 잇고 새 색 값을 만들지 않는다. 회귀는 계산된 토큰 값을 읽는 테스트로 막는다(`tests/design-shell.spec.ts`). 빌드된 CSS만 검사하는 대비 테스트는 이 문제를 잡지 못한다 — 런타임 cascade 를 보지 않기 때문이다.

## 자동 경로가 만든 row 를 뒤 단계가 사람용 action 이름으로만 찾는다

- 증상: SW=Y 사전규격에서 심층 검토가 자동으로 생성되기는 하는데 실행이 503
  `deep review 입력 snapshot이 없습니다` 로 닫히고, 사람이 재시도하면 500 이 난다.
  생성 자체는 성공하므로 화면에는 "심층 검토 자동 시작됨" 으로 보인다.
- 원인: 자동 생성이 감사 action `deep_review.auto_create` 를 남기는데, 생성 감사를
  되찾는 쪽(`run_claim` 의 snapshot 조회, `create_attempt` 의 correlation, 보고서·결정
  projection 의 lineage) 이 `action == "deep_review.create"` 를 문자열로 고정하고
  있었다. 여덟 군데였고, 그중 두 곳만 고치면 나머지 여섯이 그대로 남는다.
- 대응: "이 리뷰를 만든 감사" 를 찾는 조회는 전부 `app/core/constants.py` 의
  `DEEP_REVIEW_CREATION_ACTIONS` 를 쓴다. 사람 action 을 **일부러** 가리키는 자리(오류
  메시지의 field 이름 등)만 문자열로 남기고 그 이유를 주석에 적는다.
- 재발 방지: 사람 경로와 자동 경로가 같은 표에 다른 action 으로 쓰는 기능을 더할 때는
  "자동으로 만든 것을 끝까지 실행시키는" 테스트를 하나 둔다. action 상수만 단언하는
  테스트는 이 결함을 잡지 못한다 — 실제로 잡지 못했다.

## 목록 응답에 다른 모듈의 값을 실으면 seam 의 단수 함수가 N+1 을 만든다

- 증상: 사전규격 목록에 등급을 실었더니 목록 쿼리 수가 건수에 비례해 늘었다.
- 원인: `deep_review` 가 쓸 수 있는 `screening` seam 에 사람 정정 등급을 읽는 함수가
  단건(`latest_corrected_grade`) 밖에 없었다. 목록 200 건이면 조회가 200 번이다.
- 대응: `current_judgments` 가 `current_judgment` 의 batch 짝인 것과 같은 모양으로
  `latest_corrected_grades` 를 더하고, 단건 쪽이 batch 를 부르게 했다. 이름이 늘었지
  방향·읽기 전용·함수 안 import 는 그대로이고 경계 허용 목록은 늘지 않았다.
- 재발 방지: 쿼리 수 상한만 단언하는 테스트는 약하다. **건수를 바꿔 가며 쿼리 수가
  같은지** 를 단언한다(9건과 21건). 상한은 보조 장치다.
- 같은 뿌리: 회차 적재 hook 이 공고를 건별로 돌면 회차당 1,200~2,000 건이라 쿼리도
  savepoint 도 그만큼 열린다. PostgreSQL 은 한 transaction 의 subtransaction 이 64 개를
  넘어가면 급격히 느려진다. 후보를 먼저 batch 로 걸러 내고, 할 일이 없는 공고에는
  savepoint 를 열지 않는다.

## 공용 프롬프트 조립기가 한 도메인의 출력 계약을 코드에 박고 있다

- 증상: 개요 검토 프롬프트 안에 "deep_review_id·attempt_id·stage 를 그대로 복사하라",
  "claim 8 개까지" 같은 심층 검토용 지시가 섞여 나간다. 강제되는 응답 모양은 policy 의
  `output_schema` 라 검증은 통과하므로 테스트로는 드러나지 않는다.
- 원인: `core` 의 `build_prompt` 가 `output_contract` 블록을
  `bidops.deep-review-stage.v1` 로 고정하고 있었다. core 는 어느 도메인 계약도 몰라야
  한다는 원칙과 어긋난다.
- 대응: policy 가 `prompt_output_contract` 를 선언하면 그것을 쓰고, 선언이 없으면 기존
  블록을 쓴다. 선언이 없는 기존 policy 는 프롬프트 바이트가 그대로라 digest 가 바뀌지
  않는다.
- 재발 방지: 모델에 실제로 나가는 프롬프트를 한 번은 눈으로 본다. schema 검증이
  통과한다고 프롬프트가 맞는 것은 아니다.

## 회차 원본 밖의 gitignore 된 입력이 worktree 에는 없다

- 증상: worktree 에서 `pytest tests/app` 을 돌리면 `FileNotFoundError` 로 34 건이 한꺼번에
  깨진다. 같은 명령이 주 checkout 에서는 전부 통과한다.
- 원인: `experiments/order-plan-screening/review-inputs/{company,prompts}` 가 회사자료라
  gitignore 돼 있어 `git worktree add` 로 만든 트리에는 존재하지 않는다.
- 대응: worktree 를 만들 때 그 디렉터리를 주 checkout 에서 복사해 넣는다. gitignore 는
  그대로라 커밋될 수 없다. 같은 이유로 `.env` 도 없어서 `docker compose build` 가 변수
  보간 단계에서 멈춘다 — `--env-file` 로 주 checkout 의 `.env` 를 준다.
