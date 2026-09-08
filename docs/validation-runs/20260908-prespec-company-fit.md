# 사전규격 회사 핏 단계 구현·검증

기준일: 2026-09-08. 현재 작업 트리의 코드 검증 기록이다. 운영 DB 적용, 서비스 재시작,
실제 모델 호출, 정책 활성화, commit·push는 하지 않았다. 회사 핏 실행은 기본 비활성이며
현재는 명시적인 참조 실행만 지원한다. 이 기록은 모델 판단의 품질 승인이나 운영 완료 근거가 아니다.

## 구현한 동작

- `우선 검토`·`SW사업대상=Y`·자동 확정된 ready 묶음·동일 문서의 검증된 최신 개요와
  승인된 활성 프로필/정책을 확인한 뒤 회사 핏 입력을 고정한다.
- 최신 설명형 페이지 개요가 있으면 그 결과를 우선한다. 그 결과의 검증이 실패하면 과거
  추출형 개요로 우회하지 않는다. 페이지 개요가 없을 때는 검증된 기존 추출형 개요를 사용할 수 있다.
- `matched`·`mismatch`·`unknown`을 개요와 별도로 저장한다. 공고 근거와 승인 프로필의
  구조화 항목을 사유에 연결하며, `unknown`/`null` 회사 정보를 역량 부재로 바꾸지 않는다.
  확인된 회사 항목이 하나도 없으면 모델 호출 없이 정보 부족으로 종결한다.
- 검증된 현재 입력의 `matched`만 기존 심층 생성 서비스로 연결한다. 불일치, 정보 부족,
  실패, 검증 실패, 만료 lease, 오래된 입력, mock 품질은 자동 시작을 차단한다.
  분석의 자동 시작과 사람의 추적 승인·최종 Go/No-Go는 별개다.
- 목록의 선택 상세와 개별 상세에 판단 사유, 공고·회사 양쪽 근거, PDF 실제 페이지 또는
  기존 문서 블록 위치, 확인할 사항, 입력 버전·모델·정책·사용량과 이전 이력을 표시한다.
  실제 생성된 심층 검토는 서버의 review ID로만 연결한다.

`0020_prespec_company_fit`은 frozen input·정책 전문·digest와 결과를 보존하는 테이블,
notice/document/profile/policy 연결, 상태 전이·종결 행 불변 trigger, migration 감사 표식을
추가한다. app role은 조회만, analysis worker는 생성과 지정된 상태/결과 열 갱신만 허용한다.
raw 모델 응답은 기존 개요와 공유하는 암호화 객체 저장 함수를 사용한다. 공개 API에는
회사 원문, 파일 경로, 모델 원응답을 추가하지 않았다.

합성 analysis worker의 순서는 C-2 → 심층 → 회사 핏 → 개요다. 하나의 슬롯을 공유하고
회사 핏의 같은 입력은 자동 재시도하지 않는다. 모델 바인딩/허용 host/revision은 호출 전에
확인하며 hosted 모델로 자동 fallback하지 않는다. 정책에는 승인 generation 설정도 고정한다.

## 범위와 남은 운영 검증

이 변경은 회사 핏 단계의 실행·저장·조회·상세 표시와 자동 시작 게이트다. 기존 개요 생성
프롬프트를 `prompt-v4.md`로 전환하거나 HWP/HWPX → PDF 변환 파이프라인을 교체한 변경은
아니다. 이미 저장된 v4 페이지 개요를 사용할 수 있으며 회사 핏 단계 자체에는 새 PDF 변환이
필요하지 않다. 기존 `R26BD00271191`의 원본 개요와 참조 실행 기록을 덮어쓰지 않았다.

결정적 검증은 schema, 근거 참조, 승인 상태, 숫자 일치, 입력 버전 등을 검사한다. 문장 의미의
정확성과 회사 핏 판단 품질을 증명하지 않으므로 참조 품질 표식을 유지한다. 실제 비용 절감도
측정하지 않았다. 동일한 모집단의 핏 토큰·시간, 불일치/보류 비율과 이후 심층 사용량으로
비용을 비교해야 한다. 재시작 UI와 운영용 측정 품질 승인은 후속 범위다.

기존 결정적 mock 종단 검사는 개요 완료만으로 자동 심층을 생성하지 않는다. 종단의 보고서·사람
의견 경로를 검사할 때 기존 사람 생성 서비스를 명시적으로 사용하며 `actor_kind=human`을
단언한다. 회사 핏의 자동 생성 여부는 별도 연결 검사에서 세 판정 각각에 대해 검증한다.

## 최종 집중 검사

| 범위 | 실행 | 결과 |
|---|---|---|
| 회사 핏 계약·worker·API·자동 시작, 설정·모듈 경계 | backend에서 `.venv/bin/python -m pytest tests/deep_review/test_company_fit.py tests/app/test_runtime_contract.py tests/app/test_analysis_worker_slots.py tests/app/test_module_boundaries.py -q --tb=short` | 74 passed |
| 실제 PostgreSQL 17 migration·권한·불변 제약 | 아래 격리 PostgreSQL 명령 | 44 passed |
| 기존 자동 준비·심층 생성·개요 worker·종단 연결 회귀 | 관련 backend 집중 실행 | 75 passed, 기존 Protocol 2 failed |
| 회사 핏·페이지 개요·사전규격 화면 | frontend에서 `npx playwright test tests/company-fit.spec.ts tests/page-overview.spec.ts tests/pre-specs.spec.ts --project=app` | 56 passed |
| 긴 사유·키보드·누락 사유·검증 실패 추가 확인 | `npx playwright test tests/company-fit.spec.ts --project=app` | 4 passed |
| 테마 대비 | `npm run test:contrast` | 9 passed |
| TypeScript strict·production build | `npm run build` (Playwright 준비 단계에서도 실행) | 통과 |
| Compose 설정·실제 이미지 | `docker compose -f docker-compose.yml config --quiet`; `docker compose -p bidops-verify -f docker-compose.yml build` | 통과; 운영 컨테이너 재생성 없음 |
| 변경 무결성 | `git diff --check`; `cmp AGENTS.md CLAUDE.md` | 통과 |

화면 fixture는 합성 회사 정보만 사용했다. 회사 핏 두 상세를 1280×800과 1440×900에서 검사해
가로 넘침, 긴 사유, 근거 URL, 참조 품질 표식, 입력 토큰 null과 출력 토큰 0의 구분을 확인했다.
별도 사전규격 회귀는 기존 추적 저장·실패 시 입력 보존도 검사한다. 픽셀 기준선은 변경하지 않았다.

PostgreSQL 집중 검사는 운영 URL을 사용하지 않도록 저장소의 임시 서버 도구로 실행했다.
선택한 PostgreSQL 테스트만 단독 실행하면 서버 미지정으로 skip되므로 아래처럼 명시적으로
임시 서버를 만든다. 생성한 DB와 컨테이너는 context 종료 때 제거한다.

```bash
cd web/backend
.venv/bin/python - <<'PY'
import os
import subprocess
import sys
from tests.postgres import temporary_postgres_server
with temporary_postgres_server() as maintenance:
    env = dict(os.environ, BIDOPS_TEST_POSTGRES_URL=maintenance)
    result = subprocess.run([
        sys.executable, '-m', 'pytest',
        'tests/deep_review/test_company_fit_postgres.py',
        'tests/app/test_runtime_database_privileges.py',
        'tests/app/test_db_migrations.py', '-q', '--tb=short', '-rs'
    ], env=env)
raise SystemExit(result.returncode)
PY
```

## 전체 회귀의 한계

전체 backend `.venv/bin/python -m pytest -q --tb=short`는 중간 상태에서
1,556 passed·18 failed·5 skipped였다. migration의 새 테이블/감사 표식과 worker의 활성 입력
설정을 기존 검사에 반영한 뒤 실패 항목을 재실행했다. 15개가 통과했고 남은 3개 중
worker 설정 검사는 최종 74개 집중 검사에서 통과했다. 나머지 2개는 이미 기록된
[lifecycle Protocol 계약 공백](../tracking/findings.md#lifecycle-projection의-protocol-요구-메서드와-구현-불일치)이다.
최종 수정 후 전체 backend를 다시 한 번 모두 통과시킨 기록은 없다.

전체 frontend `npm run test:screens`는 463 passed·10 failed·6 skipped다. 실패는 회사 핏을
표시하지 않는 화면의 아래 검사다. 기존 ERP 변경 후의 검증 기록과 함께 해석하며,
이번 작업에서 다른 화면의 구현이나 기대값을 고쳐 통과시킨 것으로 처리하지 않았다.

- `common-interactions.spec.ts` 3개: UC-02 중복 상태 문구, 회차 축 화면명, 흡수한 옛 경로.
- `route-context.spec.ts` 5개: queue 목록·상세, reviews, SPA 링크, queue 상단 경로.
- `screen-semantics.spec.ts` 2개: 마감·감사 경로 쿼리, 평가 수치 누락 검사.
  마지막 검사는 판정 기준 화면의 `.crit-stat-line`이 2개라 strict locator가 실패한다.
  업무별 구역을 한정하는 기존 화면/검사의 조정이 필요하며 회사 핏 변경 경로 밖이다.

화면 skip 6개는 기존 desktop 전용 shell 조건과 `CRITERIA_SHOTS` 미설정 캡처 검사다.
backend skip은 전체 실행에서 5개가 보고됐으며 별도 서비스/컨테이너 조건부 검사다.
skip을 통과로 집계하지 않는다. 이 상태는 **전체 배포 게이트 통과가 아니다.**

작업 중 로그는 `/tmp/bidops-company-fit-code-final.log`, `...-pg-final.log`,
`...-ui-final.log`, `...-ui-edge-final.log`, `...-backend-final.log`, `...-failed-recheck.log`,
`...-all-screens.log`, `...-image-final.log`에 남겼다. `/tmp` 로그와 화면 캡처는 임시 산출물이며
이 문서가 검증 범위·결과를 보존한다.
