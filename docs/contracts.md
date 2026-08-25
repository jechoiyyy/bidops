# 외부 인터페이스 계약

## 공통 REST 규약

기본 경로는 `/api`이며 현재 인증 헤더는 없다. 사내망에 접근 가능한 소비자는 모두 조회할 수 있다. JSON 요청은 `Content-Type: application/json`, 파일 등록은 `multipart/form-data`를 사용한다. 성공 응답은 Pydantic 모델의 JSON이며 파일 다운로드·YAML 내보내기는 명시된 미디어 타입을 사용한다.

오류 응답은 FastAPI 기본 형태 `{"detail": <문자열 또는 검증 오류 목록>}`다. 잘못된 요청 모델·필수 쿼리 누락은 422, 존재하지 않는 회차·공고·첨부는 404, 실행 입력 또는 파일 정책 위반은 400, 중복 실행은 409다. 현재 API는 별도 오류 코드 필드를 보장하지 않으므로 소비자는 `detail` 문구를 영구 식별자로 사용해서는 안 된다.

목록의 날짜·시간은 시간대가 포함된 ISO 8601 문자열이며 값이 확인되지 않은 필드는 `null`이다. `null`을 0이나 빈 문자열로 해석해서는 안 된다.

## 상태·회차

| 호출 | 입력 | 성공 출력 | 오류 |
|---|---|---|---|
| `GET /api/health` | 없음 | `{"status":"ok"}` | 서버 자체 장애 외 별도 업무 오류 없음 |
| `GET /api/runs` | 없음 | 최신 순 `items`와 `total` | DB 조회 실패 500 |
| `GET /api/runs/{run_id}` | 경로 실행 ID | 수집 범위, 단계, 산출물 검증, 경고 수를 포함한 회차 상세 | 회차 없음 404 |
| `GET /api/runs/{run_id}/stats` | 경로 실행 ID | 퍼널·등급·준비 상태·초점 분포, 확인 요청, 임박 마감 | 회차 없음 404 |
| `GET /api/runs/{run_id}/warnings` | 선택 `level`, `code` | 필터와 경고 `items`, `total` | 회차 없음 404 |
| `POST /api/runs/ingest` | JSON 또는 쿼리 `run_id` | 적재된 공고·판정·리뷰 수와 경고 | ID 누락 422, 안전하지 않거나 없는 디렉터리 404 |
| `POST /api/runs/{run_id}/pipeline/{stage}` | 선택 JSON/쿼리 `from_raw`; 현재 stage는 `collect`, `sample`, `report` | 202와 실행 ID·상태·시각·로그 메타데이터 | 회차 없음 404, 입력/미지원 단계 400, 실행 중 409 |
| `GET /api/runs/{run_id}/pipeline/logs` | 선택 `execution_id` | 실행 목록과 순서 있는 로그 행 | 회차 없음 404 |

## 공고·판정·이력

| 호출 | 입력 | 성공 출력 | 오류 |
|---|---|---|---|
| `GET /api/notices` | 필수 `run_id`; 선택 `grade`, `readiness`, `focus`, `sample_role`, `attachment=any|none|manual`, `q`, `sort=deadline|grade|published`, `limit=1..500`, `offset>=0` | 공고 요약 `items`, `total`, 적용 필터 | 회차 없음 404, 범위/enum 오류 422 |
| `GET /api/notices/{notice_pk}` | 공고 DB 식별자 | 기본 정보, 원문 신호, 판정 다섯 관점, 첨부, 리뷰 | 공고 없음 404 |
| `GET /api/notices/{notice_pk}/related` | 공고 DB 식별자 | 같은 회차의 차수·통합공고·사전규격 연관 공고 | 공고 없음 404 |
| `GET /api/notices/{notice_pk}/history` | 공고 DB 식별자 | 같은 안정 공고 키의 회차별 판정·수정 이력 | 공고 없음 404 |

`GET /api/notices`에서 `grade`를 생략하면 `제외` 판정은 기본적으로 빠지고 `grade=all`에서 포함된다. `attachment=any`는 첨부 유무를 제한하지 않으며 첨부가 있다는 뜻이 아니다.

## 리뷰와 검증 지표

| 호출 | 입력 | 성공 출력 | 오류 |
|---|---|---|---|
| `GET /api/reviews?run_id=...` | 필수 실행 ID | 해당 회차의 DB 정본 리뷰 목록 | 회차 없음 404 |
| `PUT /api/notices/{notice_pk}/review` | `run_id`, disposition, 시스템 판정 평가, 수정 등급·준비 상태, 취약 관점, 사유, reviewer, 확인 답변 배열 | 공고·회차 쌍의 생성/갱신된 단일 리뷰 | 회차/공고 없음 또는 불일치 404, 모델 검증 오류 422 |
| `GET /api/reviews/export?run_id=...` | 필수 실행 ID | `application/yaml`, `bidops.feedback.v2`, 모든 공고의 리뷰 행 | 회차 없음 404 |
| `GET /api/metrics/validation?run_id=...` | 필수 실행 ID | 계산 가능한 검증 지표와 계산 불가 상태 | 회차 없음 404 |

리뷰 PUT은 확인 답변 배열을 매번 전체 교체한다. 일부만 보내면 보내지 않은 기존 답변은 삭제된다. 리뷰 정본은 DB이며 YAML은 호환 내보내기다.

## 첨부와 기관 포털

| 호출 | 입력 | 성공 출력 | 오류 |
|---|---|---|---|
| `GET /api/notices/{notice_pk}/attachments` | 공고 DB 식별자 | 확보 상태, 매칭 포털, 검색 URL, 절차, 첨부 목록 | 공고 없음 404 |
| `POST /api/notices/{notice_pk}/attachments` | multipart의 `files` 배열 또는 `file`; HWP/HWPX/PDF, 각 50MB 이하 | 갱신된 첨부 확보 절차 | 공고 없음 404, 파일 없음/정책 위반 400 |
| `DELETE /api/attachments/{attachment_id}` | 첨부 DB 식별자 | 204 본문 없음 | 첨부 없음 404, 제공 첨부 403, 안전하지 않은 저장 경로 500 |
| `GET /api/attachments/queue?run_id=...` | 필수 실행 ID | 첨부 없는 공고와 포털 검색 정보 | 회차 없음 404 |
| `GET /api/attachments/{attachment_id}/download` | 첨부 DB 식별자 | PDF는 `application/pdf`, 그 외 `application/octet-stream` 파일 스트림 | 메타데이터/파일 없음 또는 경로 오류 404 |
| `GET /api/portals` | 없음 | 활성 우선 기관 포털 목록 | DB 오류 500 |
| `POST /api/portals` | 기관 매칭 문자열, 시스템명, 검색 URL 템플릿, 활성 여부, 비고 | 201과 생성 포털 | 필수 문자열 누락 422 |
| `PATCH /api/portals/{portal_id}` | 변경할 필드만 포함 | 갱신 포털 | 포털 없음 404, 필수 문자열 공백 422 |

서버의 `stored_path`는 내부 메타데이터이며 소비자는 이를 다운로드 경로로 조합하지 않고 응답의 API URL을 사용한다. 나라장터 제공 첨부는 삭제할 수 없다.

## 회사 프로필

| 호출 | 입력 | 성공 출력 | 오류 |
|---|---|---|---|
| `GET /api/profile/sections` | 없음 | 프로필 절 트리, 상태별 수, 파싱 오류와 보존 원문 | 프로필 읽기 실패 500 |
| `GET /api/profile/unknowns` | 없음 | `unknown` 항목, 공고 근거 언급 수 또는 `unavailable`, 파싱 오류 | 프로필 읽기 실패 500 |

프로필 파서가 구조화하지 못한 블록은 버리지 않고 원문과 오류를 반환한다. 공고 근거 DB 조회가 실패하면 언급 수는 0이 아니라 `null`과 `unavailable`이다.

## 파이프라인 파일 계약

모든 파일은 UTF-8이며 시간대는 `Asia/Seoul` 문맥을 보존한다.

| 파일 | 스키마 | 생성자 | 소비자 실패 조건 |
|---|---|---|---|
| `collected-notices.json` | `bidops.collected.v2` | 수집 스크립트 | 스키마 버전·안정 ID·공고 배열 구조 오류 |
| `validation-set.json` | `bidops.validation-set.v2` | 표본 선정 스크립트 | 표본 역할/층 또는 원 공고 연결 오류 |
| `screening-decisions.json` | `bidops.decisions.v2` | 1차 분석 에이전트 | 판정 누락, 잘못된 enum, 다섯 관점/근거/교차 조건 위반 |
| `screening-results.json` | `bidops.screening.v2` | 병합 스크립트 | 표본과 판정 ID 불일치 |
| `review-feedback.yaml` | `bidops.feedback.v2` | 보고 스크립트의 빈 양식 또는 API 내보내기 | 알 수 없는 구조; DB 적재 후에는 DB가 정본 |

`screening-decisions.json`의 등급은 `우선 검토`, `검토 권장`, `관찰 대상`, `제외`; 준비 상태는 `확인 완료`, `부분 확인 필요`, `참여 불가 확인`, `해당 없음`이다. 각 판정에는 기술 적합성, 실적 정합성, 공공 SI 적합성, 사업성·자격 제약, 전략 부합 관점이 정확히 한 번씩 있어야 한다.

심층 분석 파일 계약은 아직 구현되지 않았다. 구현 시 문서 집합과 정책·모델·프롬프트 버전, 단계별 구조화 결과, 결정적 검증 오류, 사람 수정 이력을 각각 버전 계약으로 노출해야 하며 자유서술 Markdown만을 기계 간 정본으로 사용해서는 안 된다.
