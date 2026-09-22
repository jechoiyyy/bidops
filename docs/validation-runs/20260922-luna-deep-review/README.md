# 사용자 요청 Luna 격리 검증

실행일 2026-09-23. 아래는 최초 격리 검증 기록이며, 후속 운영 적용·실제 모델 연결은 [운영 기록](live-validation.md)을 따른다. 현재 작업 트리에서 새로 실행했다. 선행 설명형 보고서 작업의
과거 결과를 재사용하지 않았다. 기존 사용자 변경·데이터는 보존했다.

## 실행 환경과 결과

- backend `.venv`, 기본 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`.
- 일회용 `postgres:17.11`, `bidops-luna-verify-pg`, host port 41897.
  `BIDOPS_TEST_POSTGRES_URL`로 해당 인스턴스를 연결했다. 운영 DB를 사용하지 않았다.
- `pytest -q tests/app/test_luna_deep_review.py tests/deep_review/test_codex_runner.py`:
  23 passed. 신규 migration/직전 head 승격·불변 승인·동시 요청 PostgreSQL 변형 포함.
- 추가 HTTP 어댑터 경유 합성 3단계 실행: 1 passed. 승인 후 mock 설정 변경 차단:
  1 passed. 후자는 서비스가 실패를 저장한 뒤 예외를 전달하는 계약에 맞게 assertion을 수정했다.
- runtime privileges 및 기존 합성 공용 슬롯 관련 검사: 6 passed.
- 관련 auto-start·Agent·기존 심층 경로 재검사: 59 passed / 1 failed였으며,
  실패한 늦은 lease 응답 수락을 수정한 뒤 해당 사례 1 passed.
- Luna·runner·사전규격 projection 묶음: 38 passed / 2 failed. 두 실패는 자동 시작
  기본 비활성인데 옛 자동 reason을 기대한 fixture였다. 해당 사례를 명시적으로
  auto-enabled로 바꾸고 2 passed. 제품 기본값을 되돌리지 않았다.
- `npm run build`: 통과. 번들 크기 경고가 남는다.
- `PW_PORT=4192 playwright test --project=app tests/luna-deep-review.spec.ts
  tests/deep-review.spec.ts tests/narrative-report.spec.ts`: 31 passed.
- 최종 설정 변경/preview bounded 영역 수정 후 Luna + document-preparation: 7 passed.
- 변경된 사전규격 의미 검사(`screen-semantics`, grep `사전규격|클릭 대기`): 5 passed.
- runner Docker 이미지 빌드 성공. 네트워크 없는 컨테이너에서 CLI 0.155.1 확인.
  운영 Compose 5개+Luna overlay의 합성 환경 렌더링 및 내부망/egress/volume/port
  격리 검사 통과. 운영 서비스는 시작하거나 교체하지 않았다.
- `git diff --check` 통과. Pydantic `schema` 필드 shadow 경고가 남는다.

## 검증 범위

합성 입력에서 승인 누락·설정 변경·다른 공고·동시/중복 제출·재실행·원천 동결,
3단계 검증과 보고서·근거 저장, 이전 보고서 보존, 인증/모델 접근 오류·schema/근거
오류·timeout·lease 상실·늦은 응답 차단을 검사했다. 실행기는 실제 CLI 도움말의
argv와 대조하고 가짜 subprocess를 실행해 env·임시 파일·프로세스 정리를 검사했다.
통신 단절 시 원격 watchdog 종료까지 공용 슬롯 반환을 지연한다.

UI는 이번 backend 실행이 생성한 합성 보고서/preview/evidence fixture를 사용했다.
1280×800과 1440×900에서 미리보기→승인→보고서→원문 근거와 가로 넘침을 검사했다.
첨부 PNG는 1280×800 실행에서 수집한 미리보기·보고서·근거 화면이다.
Playwright가 API를 가로챘으므로 실제 웹·worker·runner 전체 연결의 증거는 아니다.

## 남은 실제 인수

Codex 인증·Luna 모델 접근·실제 자료 전송은 하지 않았다. runner의 실제 모델 호출
시 도구 제한 동작과 호스트 firewall allowlist, 실제 스택 두 건 순차 실행과 개요
처리 재개, 실제 문서에 대한 사람 품질 검토는 미검증이다. 결과는 계속
`unmeasured_reference`이며 품질 측정 완료로 취급하지 않는다.

운영 migration·재배포·정책 적용·실제 표본은 각각 직전 사람 확인 후
[적용 절차](../../0922_luna-deep-review/apply.md)를 따른다. commit/push는 하지 않았다.
