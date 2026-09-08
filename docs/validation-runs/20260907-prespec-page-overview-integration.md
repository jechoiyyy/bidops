# 사전규격 PDF 개요 저장·API·화면 연결 검증

2026-09-07. 프롬프트 v4 / 출력 `bidops.prespec-overview-page-review.v3` 유지.
이번 작업의 추가 모델 호출은 0회다. 운영 DB migration·적재·서비스 교체는 실행하지 않았다.

## 구현 범위

- `prespec_page_overview` append-only JSONB 저장, Alembic 0019, 명시적 runtime 권한.
  기존 권고 결과/리뷰/추적/자동 심층 검토는 변경하지 않는다.
- frozen 입력과 policy/prompt/source/PDF hash 검증, PDF 페이지 텍스트 대조,
  정확한 PDF bytes 스캔, 버전 고정 source·structure 객체 저장, 재적재 멱등성.
- `GET /api/pre-specs/{notice_id}/overview-pages`와 review별 PDF 조회.
  파일·객체 키 대신 API에서 스캔/버전/해시/크기를 검증한 PDF만 반환한다.
- 목록+상세 및 별도 상세 화면에서 사업 개요·주요 과업·규모/일정·조건·검토 포인트·
  미확인 사항을 표시한다. 기존 권고 기록은 아래에 구분해 남긴다.
- 새 producer/적재기는 같은 `pdf-page-evidence.v2`를 사용한다. 정확히 일치하는
  문장 끝 페이지 표기만 메타데이터로 분리한다. 과거 frozen code/output/outcome은 보존한다.

## 실행 증거

모든 DB 테스트는 전용 PostgreSQL 17.11 컨테이너의 무작위 임시 DB 또는 격리 SQLite에서
수행했다. 테스트용 PDF scanner/filesystem 객체 저장소는 운영 ClamAV/MinIO 검증으로
간주하지 않는다. 이 차이는 아래 실제 입력 검사에도 적용된다.

| 검사 | 결과 |
|---|---|
| 새 저장·PDF·검증기, 기존 결과와 권한, PostgreSQL 제약 초기 검사 | 28 passed |
| 모듈 경계·공개 이름·CLI 및 기존 개요/runner 회귀 | 112 passed |
| 저장·migration·mapper·권한 재검사 | 46 passed |
| 새/기존 사전규격 화면 | 38 passed |
| 마지막 UI build 및 새 화면 재검사 | build 성공, 3 passed |
| 프롬프트 schema 일치 포함 producer validator | 9 passed |
| `npm run test:contrast` | 실패 0 |
| `COMPOSE_PROJECT_NAME=bidops-verify docker compose -f docker-compose.yml build` | 성공 |
| Compose config / `git diff --check` | 통과 |

backend 전체 검사 최초 결과는 **1532 passed / 19 failed / 5 skipped**였다.
추가 migration에 필요한 `ALEMBIC_HEAD`, ORM FK `ondelete`, 테이블 소유 목록·개수·그룹을
수정하고 실패 19개와 새 저장 검사 11개를 다시 실행했다. **28 passed / 2 failed**이며,
남은 2개는 이번에 수정하지 않은 기존 projection protocol의 미구현 메서드다.
전체 검사를 다시 전부 통과한 것으로 기록하지 않는다.

화면 전체 게이트는 **337 passed / 11 failed / 4 skipped**다. 남은 실패는 기존 화면의
명칭·회차 기대값과 중복 상태 문구 선택자이며 새 PDF 개요 테스트는 통과했다.
관련 이슈는 `docs/tracking/findings.md`의 같은 날짜 항목에 기록했다.

## RCMS 실제 입력 재사용

notice 614의 기존 frozen 입력/출력을 사용했다. PDF 100페이지 중 3–6페이지가 입력이다.
`import-page-overview --check-only`로 policy/prompt/source/PDF와 실제 페이지 텍스트 대조를
확인했다. 격리 SQLite에 동일 notice/document identity를 만들고 실제 출력 그대로 적재한 뒤:

- 원출력 JSON 동등성 및 digest 보존 확인.
- 재적재 시 같은 ID, 추가 행 없음 확인.
- API 응답의 payload가 원출력과 같음을 확인.
- PDF API가 입력 PDF와 정확히 같은 bytes를 반환함을 확인.
- 기존 `prespec_overview_review` 행을 만들지 않음 확인.
- 새 근거 검사는 passed, 원실행 상태는 failed 유지.
- 참조 실행/품질 미측정 상태 유지.

실제 API 응답과 화면 캡처는 비공개 `.dryforge/page-overview-integration/`에 보관한다.
실제 UI 확인에서는 공고 메타데이터를 운영 API에서 GET으로 읽고 새 요약 API만 격리
응답으로 연결했다. 1440×900과 1280×800에서 초기 화면·과업 영역을 확인했다.
이를 운영 DB에 적재된 결과나 배포 완료로 간주하지 않는다.

## 실행 명령

backend 디렉터리에서 임시 PostgreSQL maintenance URL을 `BIDOPS_TEST_POSTGRES_URL`에
지정하고 `pytest tests -q`, 관련 test 파일, 실패 node ID 재검사를 실행했다.
frontend에서는 `npm run build`, `npm run test:screens`, `npm run test:contrast`,
`npx playwright test page-overview.spec.ts pre-specs.spec.ts --project=app --workers=2`를 실행했다.

운영 반영은 `docs/operations.md`의 백업·서비스 중지·migration 확인 절차 후 0019와
runtime 권한을 적용하고, worker 역할의 `import-page-overview`로 실제 1건을 적재하는
별도 단계다. 기존 worker 정책 활성화나 모델 재호출은 필요하지 않다.
