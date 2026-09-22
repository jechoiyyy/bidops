# 설명형 심층검토 PoC 검증 — 2026-09-22

제품 코드와 합성 입력의 연결 검증이다. 실제 발주 문서·회사자료·Qwen 응답의 품질 근거가 아니다.

이 기록은 최초 격리 검증 시점의 증거다. 이후 사용자 요청으로 수행한 운영 적용·실제
Qwen 호출·검증 강도 조정은 [실제 검증 기록](live-validation.md)을 따른다.

- 모델·객체 저장소 경계는 fixture, worker·입력 분할·검증·DB·보고서/근거 GET·수정본 POST는 제품 경로다.
- PostgreSQL 17.11 일회용 컨테이너와 임시 migration DB에서 같은 생성·조회·수정 경로를 확인했다. 운영 DB는 사용하지 않았다.
- frontend의 `tests/fixtures/narrative-report.json`은 backend `tests/app/test_narrative_review.py`가 worker 실행과 실제 REST 응답을 통해 출력한 합성 fixture다. 테스트에서 `BIDOPS_NARRATIVE_FIXTURE=<파일>`을 지정해 재생성한다.
- production build, 1280×800/1440×900 본문 전량·목차·관계 링크·원문 패널·Escape 초점 복귀·확대·집중 읽기·가로 넘침·테마 토큰·브라우저 오류를 확인했다. 새 수정본 도착 중 편집 보존과 재분석 실패 후 이전 결과의 새 브라우저 조회도 통과했다.

## 실행 범위와 결과

| 범위 | 실행·결과 |
|---|---|
| 기존 report/worker 호환 | `tests/deep_review/test_reports.py tests/app/test_deep_reviews.py`: 102 passed |
| 새 v2·계약·모듈 경계 | 관련 파일만 선택 실행. PostgreSQL fixture 부모 FK 삽입 순서를 바로잡은 뒤 v2/worker 83 passed, v2/경계 44 passed |
| 최종 backend 변경 | `test_narrative_review.py test_reports.py test_deep_review_contracts.py`: 61 passed, 1건의 숫자 검사 fixture에 bundle/structure context가 빠져 실패. 제품 코드 변경 없이 fixture context를 보완한 해당 검사 1 passed. 숫자 검사는 SQL 비의존이며 PostgreSQL 생성/저장/REST 변형은 통과한 61건에 포함됨 |
| UI | 기존 심층 페이지 22개와 신규 3개. 변경된 조회 시점·명시적 의견 선택에 맞춰 기존 검사를 수정하고 영향 사례만 재검사. 마지막 신규 3개 모두 passed. 기존 관련 실패도 해당 사례 재검사로 해소 |
| 빌드·변경 확인 | TypeScript strict 및 Vite production build 통과, `git diff --check` 통과. 기존 large-chunk 안내와 Pydantic `schema` 이름 경고는 남음 |

backend는 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`로 실행했다. PostgreSQL 변형은
`BIDOPS_TEST_POSTGRES_URL`로 일회용 서버를 명시했다. frontend는 다른 작업의 서버를
사용하지 않도록 `PW_PORT=4187 PW_OUT_DIR=/tmp/bidops-narrative-build`로 분리했다.
첫 서버 자동 탐지 지연 후 같은 빌드 디렉터리의 preview를 직접 띄워 확인했다.
통과한 무변경 경로는 반복하지 않고 실패/변경 경로만 재실행했다.

## 화면 증거

- [1280px 본문·원문 연결](evidence-1280.png), [1440px 본문·원문 연결](evidence-1440.png)
- [1280px 집중 읽기](report-1280.png), [1440px 집중 읽기](report-1440.png)

모두 신규 제품 컴포넌트가 위 합성 REST fixture를 표시한 Playwright 캡처다.
기존 `0922_deep-review-improvement/prototype`의 정적 HTML 시안 캡처와 구별한다.

## 남은 한계

이 격리 검증만으로는 실제 Qwen의 의미적 누락/예외·숫자 단위와 관계·회사 근거 회수율, 55개 요구사항
규모, 실무자 판단 충분성·소요 시간, 새 문서/프로필/정책의 현재성 자동 판별은 미검증 또는
후속 범위다. 이 시점에는 새 정책 등록·활성화·운영 배포 전이었다. v1 정책 SHA-256은
`ade63ebfafa2eec424bbb456dea1b5b21da0980eac6c484853612e37dda422e8`로 유지되며
새 정책은 `d97e5294ded62453c4bd75bb44a3ebbe182e24b04565e36444c8b0eecf69879a`다.
