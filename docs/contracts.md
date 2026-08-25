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
| `screening-input.json` | `bidops.screening-input.v1` | 판정 오케스트레이터 | 후보 전량 누락, 정규화 공고 연결 오류, 판정 모드 교차 조건 위반 |
| `validation-set.json` | `bidops.validation-set.v2` | 표본 선정 스크립트 | 감사 표본 역할/층 또는 원 공고 연결 오류 |
| `screening-decisions.json` | `bidops.decisions.v2`(기존 회차) 또는 `bidops.decisions.v3`(새 회차) | 기존: 1차 분석 에이전트, 신규: 판정 오케스트레이터 | 판정 누락, 잘못된 enum, 다섯 관점/근거/교차 조건 위반 |
| `screening-failures.json` | `bidops.screening-failures.v1` | 판정 오케스트레이터 | 공고 식별자·실패 단계·실패 종류·마지막 시도 시각·재시도 횟수 누락 |
| `screening-telemetry.jsonl` | `bidops.screening-telemetry.v1` | 판정 오케스트레이터 | 트레이스·스팬 식별자 또는 호출 계측 필드 누락 |
| `screening-results.json` | `bidops.screening.v2`(기존 회차) 또는 `bidops.screening.v3`(새 회차) | 병합 스크립트 | 판정 대상과 판정 ID 불일치, 결정적 검증 규칙 위반 |
| `review-feedback.yaml` | `bidops.feedback.v2` | 보고 스크립트의 빈 양식 또는 API 내보내기 | 알 수 없는 구조; DB 적재 후에는 DB가 정본 |

`screening-decisions.json`의 등급은 `우선 검토`, `검토 권장`, `관찰 대상`, `제외`; 준비 상태는 `확인 완료`, `부분 확인 필요`, `참여 불가 확인`, `해당 없음`이다. 각 판정에는 기술 적합성, 실적 정합성, 공공 SI 적합성, 사업성·자격 제약, 전략 부합 관점이 정확히 한 번씩 있어야 한다.

심층 분석 파일 계약은 아직 구현되지 않았다. 구현 시 문서 집합과 정책·모델·프롬프트 버전, 단계별 구조화 결과, 결정적 검증 오류, 사람 수정 이력을 각각 버전 계약으로 노출해야 하며 자유서술 Markdown만을 기계 간 정본으로 사용해서는 안 된다.

## 판정 대상 계약: `bidops.screening-input.v1`

정기 실행의 판정 대상은 `validation-set.json`이 아니라 `screening-input.json`이다. 판정 오케스트레이터는 규칙 필터를 통과한 후보를 빠짐없이 `notices[]`에 넣고, 각 항목에 `collected-notices.json`의 정규화 공고 필드를 그대로 복사한 뒤 판정 모드 필드를 추가한다. 감사 표본은 이 목록을 줄이거나 대신하지 않는다.

| 필드 | 내용 | 제약 |
|---|---|---|
| `schema_version` | `bidops.screening-input.v1` | 정확히 일치해야 한다. |
| `run_id` | 이 판정 대상 목록이 속한 현재 회차 식별자 | 회차의 불변 스냅샷과 연결한다. |
| `generated_at` | 대상 목록 생성 시각 | 시간대가 포함된 ISO 8601 값이다. |
| `source_window` | `from`, `to`, `timezone`을 가진 수집 기간 | `Asia/Seoul`을 보존한다. |
| `candidate_count` | 규칙 필터를 통과한 후보 수 | `notices[]`의 실제 건수와 일치해야 한다. |
| `notices[]` | 정규화 공고와 판정 대상 상태의 배열 | `notice_id`는 회차 안에서 유일해야 한다. |
| `notices[].judgment_mode` | 판정 방식 | `신규`, `재판정`, `승계` 중 하나다. |
| `notices[].carry_over_from` | 승계한 원 판정의 회차 | `승계`일 때 필수이며, 그 밖에는 `null`이다. |
| `notices[].rejudge_reason` | 재판정 사유 | `재판정`일 때 `정정`, `재공고`, `본공고 전환`, `담당자 요청` 중 하나이며, 그 밖에는 `null`이다. |

`notices[]`의 판정 모드 외 필드는 `bidops.collected.v2`의 공고 항목과 같은 정규화 필드 집합을 사용한다. 즉 `notice_id`, 기본 정보, `lifecycle`, `qualification_flags`, `attachments`, `focus_matches`, `performance_matches`, `candidate_sources`, `unknown_fields`, `raw_source`를 포함하며, 확인되지 않은 값은 `unknown`·`null`·값 없음으로 보존한다. 공고 원문이나 회사 프로필 전문을 이 계약에 복사하지 않는다.

판정 모드의 교차 조건은 다음과 같다.

| `judgment_mode` | 모델 호출 | `carry_over_from` | `rejudge_reason` |
|---|---|---|---|
| `신규` | 일곱 단계 호출 대상 | `null` | `null` |
| `재판정` | 일곱 단계 호출 대상 | `null` | 정정·재공고·본공고 전환·담당자 요청 중 하나 |
| `승계` | 모델 호출 없음 | 이전 완료 판정이 있는 회차 식별자 | `null` |

승계는 이전 판정의 식별자·등급·준비 상태·다섯 관점·근거·반론·확인 항목을 현재 회차의 새 불변 산출물에 복사하는 것이다. 이전 회차 파일·DB 행·리뷰를 수정하거나 현재 회차의 판정으로 소급 변경하지 않는다. 이전 판정이 현재 계약을 만족하지 않으면 승계하지 않고 `screening-failures.json`에 검증 실패로 남긴다.

```json
{
  "schema_version": "bidops.screening-input.v1",
  "run_id": "20260825-20260825",
  "generated_at": "2026-08-25T02:01:00+09:00",
  "source_window": {"from": "2026-08-24", "to": "2026-08-24", "timezone": "Asia/Seoul"},
  "candidate_count": 2,
  "notices": [
    {
      "notice_id": "bid:example:000",
      "source_type": "bid_notice",
      "title": "정규화된 공고 제목",
      "agency": "확인된 발주기관",
      "lifecycle": {},
      "unknown_fields": [],
      "judgment_mode": "신규",
      "carry_over_from": null,
      "rejudge_reason": null
    },
    {
      "notice_id": "bid:example:001",
      "source_type": "bid_notice",
      "title": "정규화된 공고 제목",
      "agency": "확인된 발주기관",
      "lifecycle": {},
      "unknown_fields": [],
      "judgment_mode": "승계",
      "carry_over_from": "20260824-20260824",
      "rejudge_reason": null
    }
  ]
}
```

위 JSON의 공고 값은 구조를 보이는 예시이며 실제 공고 사실을 채우는 예시가 아니다. `unknown` 상태를 확정값으로 바꾸지 않는다.

## 감사 표본 계약의 역할

`bidops.validation-set.v2`와 `select_validation_sample.py`는 새 판정 대상 선정 계약이 아니다. 정기 실행은 `bidops.screening-input.v1`의 후보 전량을 판정하고, `validation-set.v2`는 품질 게이트가 1차 필터의 누락과 층별 편향을 감사하기 위한 표본만 만든다.

| 구분 | `bidops.screening-input.v1` | `bidops.validation-set.v2` |
|---|---|---|
| 목적 | 규칙 필터 통과 후보 전량의 판정 입력 | 품질 게이트용 감사 표본 추출 |
| 작성 주체 | 판정 오케스트레이터 | `select_validation_sample.py` |
| 정기 판정 대기열 포함 | 포함 | 제외 |
| 스키마 변경 | 신규 계약 | 기존 스키마를 변경하지 않음 |
| 감사 표본의 `sample_role` | 사용하지 않음 | `audit`이며 기존 `analysis`·`audit` enum은 보존 |

기존 `validation-set.v2` 파일과 그 안의 기존 `analysis` 표본은 과거 회차의 의미를 소급해 `audit`로 바꾸지 않는다. 새 정기 실행에서 생성되는 `validation-set.v2`는 감사 표본으로만 사용한다. 감사 결과 누락으로 확인된 공고를 같은 회차 판정 대기열에 소급 추가하지 않으며, 감사 표본은 검토 대기열에도 올리지 않는다.

## 판정 산출물 계약: `bidops.decisions.v3`

`screening-decisions.json`의 새 회차 기준 스키마는 `bidops.decisions.v3`이다. 다섯 관점, 근거, 반론, 확인 항목, 등급·참여 준비 상태의 기존 의미와 허용 값은 `bidops.decisions.v2`에서 이어받는다. `bidops.decisions.v2`의 의미를 소급 변경하지 않으며, 이미 생성된 v2 파일은 v2 계약으로만 해석한다.

기존 필수 필드 외에 v3 판정 항목은 다음의 역추적·승계 필드를 가진다.

| 필드 | 내용 | 제약 |
|---|---|---|
| `model_name` | 판정 생성에 사용한 모델 이름 | 신규·재판정은 호출 설정과 일치해야 하며, 승계는 원 판정 값을 보존한다. |
| `model_version` | 실행 시 확인한 모델 버전·해시 등 식별 정보 | 확인되지 않으면 추정하지 않고 `unknown` 또는 `null`로 둔다. |
| `prompt_version` | 적용한 관점·반론·종합 프롬프트의 불변 버전 | 회차와 함께 고정한다. |
| `policy_version` | 정책 저장소의 불변 버전 | 활성 정책을 제자리에서 수정하지 않는다. |
| `judged_in_run` | 이 판정이 처음 만들어진 회차 | 현재 회차가 아니라 최초 생성 회차 식별자다. 승계해도 바꾸지 않는다. |
| `recorded_in_run` | 이 판정 항목을 현재 파일에 기록한 회차 | 현재 `screening-input.v1`의 `run_id`와 일치한다. |
| `carried_over` | 현재 회차에서 모델을 다시 호출하지 않고 승계했는지 여부 | 불리언이다. 승계면 `true`, 신규·재판정이면 `false`다. |
| `rejudge_reason` | 재판정 사유 | 재판정일 때만 `정정`, `재공고`, `본공고 전환`, `담당자 요청` 중 하나이고 나머지는 `null`이다. |
| `two_axis_mixing_flag` | 두 축 혼입 조건에 해당하는지 결정적으로 표시 | `사업성·자격 제약` 관점이 `확인 불가`이고 종합 등급이 `관찰 대상` 또는 `제외`이면 `true`다. |
| `two_axis_mixing_label` | 혼입 판정의 사람 검토 표시 | `two_axis_mixing_flag`가 `true`이면 `확인 요망`, 아니면 `null`이다. |

`judged_in_run`은 불리언이 아니라 최초 판정 회차 식별자 문자열이다. `carried_over`가 `false`인 신규·재판정에서는 `judged_in_run`과 `recorded_in_run`이 같고, `carried_over`가 `true`인 승계에서는 두 값이 다르다. 승계 판정의 모델·모델 버전·프롬프트·정책 정보도 원 판정의 값을 보존하며, 현재 회차에서 호출한 것처럼 기록하지 않는다.

v3의 `judgment_mode`는 같은 항목의 `screening-input.v1` 값과 일치해야 한다. `신규`·`재판정`·`승계`는 각각 `carried_over`의 `false`·`false`·`true`와 대응하고, `재판정`일 때만 `rejudge_reason`을 채운다. 이 메타데이터 교차 검사는 병합기가 등급을 보정하는 규칙이 아니라 오케스트레이터의 계약 검증이다.

`two_axis_mixing_flag`와 `two_axis_mixing_label`은 결정적 검출기가 붙이는 표시다. 표시가 `true`여도 실패 목록으로 이동시키지 않고 판정과 결과에 남긴다. 표시를 이유로 등급·참여 준비 상태를 자동 변경하거나 재시도하지 않으며, 담당자 검토와 회차별 혼입 지표의 분자·분모에 사용한다.

```json
{
  "schema_version": "bidops.decisions.v3",
  "run_id": "20260825-20260825",
  "screening_basis": "회차에 고정된 정규화 공고와 회사 프로필·정책 버전",
  "judgments": [
    {
      "notice_id": "bid:example:000",
      "judgment_mode": "신규",
      "model_name": "qwen3.8:27b",
      "model_version": "확인된 모델 식별 정보",
      "prompt_version": "screening-prompt.v1",
      "policy_version": "screening-policy.v1.20260825",
      "judged_in_run": "20260825-20260825",
      "recorded_in_run": "20260825-20260825",
      "carried_over": false,
      "rejudge_reason": null,
      "two_axis_mixing_flag": false,
      "two_axis_mixing_label": null,
      "grade": "검토 권장",
      "readiness": "부분 확인 필요",
      "primary_focus": "공공 SI·통합관리",
      "exclusion_category": null,
      "summary": "다섯 관점과 근거에 연결된 종합 판정",
      "perspectives": [],
      "matched_performances": [],
      "counterarguments": [],
      "verification_items": [],
      "next_action": "담당자가 확인할 다음 조치"
    }
  ]
}
```

이 예시는 필드 구조만 보인다. `perspectives[]`, `counterarguments[]`, `verification_items[]`를 빈 배열로 제출해도 된다는 뜻이 아니며, 기존 결정적 검증 규칙은 그대로 적용한다.

## 판정 실패 목록 계약: `bidops.screening-failures.v1`

판정 실패 목록은 `screening-failures.json`으로 별도 보존한다. 실패한 공고는 `screening-decisions.json`과 병합 입력에서 제외하고 사람 검토 대기로 표시한다. 실패 한 건 이상으로 유효 결과가 남은 회차는 `partial_artifact: true`인 부분 산출물로 남긴다.

| 필드 | 내용 | 허용 값·조건 |
|---|---|---|
| `schema_version` | `bidops.screening-failures.v1` | 정확히 일치해야 한다. |
| `run_id` | 실패가 발생한 현재 회차 | 현재 판정 대상 목록과 연결한다. |
| `generated_at` | 실패 목록 생성 시각 | 시간대 포함 값이다. |
| `failures[]` | 공고별 최종 실패 항목 | 같은 회차·공고·최종 실패 단계에 대해 식별 가능해야 한다. |
| `notice_id` | 실패한 공고 식별자 | 판정 대상 목록의 안정 ID여야 한다. |
| `failed_stage` | 실패한 단계 | `기술 적합성`, `실적 정합성`, `공공 SI 적합성`, `사업성·자격 제약`, `전략 부합`, `반론 검토`, `종합 판정`, `병합·검증` 중 하나다. |
| `failure_type` | 실패 종류 | `timeout`, `truncated_output`, `schema_violation`, `evidence_missing`, `counterargument_repetition` 중 하나다. |
| `last_attempt_at` | 마지막 시도 시각 | 시간대가 포함된 ISO 8601 값이다. |
| `retry_count` | 최초 시도 뒤 재시도한 횟수 | 0 이상의 정수이며 시도 횟수를 성공으로 보이게 만들지 않는다. |
| `status` | 공고의 후속 상태 | `사람 검토 대기`로 고정한다. |
| `failure_context` | 특수한 검증 맥락 | 승계 검증 실패일 때만 `carried_over_validation`, 그 밖에는 `null`이다. `failure_type`의 허용 값은 늘리지 않는다. |
| `trace_id`, `span_id` | 호출 계측 기록 연결자 | 호출 계측이 없는 병합·검증 실패에서는 `null`일 수 있다. |

실패 종류의 값은 `docs/agent-runtime.md` 6절의 표와 일치시킨다. 타임아웃은 `timeout`, 잘린 출력은 `truncated_output`, 스키마 위반은 `schema_violation`, 근거 누락은 `evidence_missing`, 반론 상투구 반복은 `counterargument_repetition`으로 기록한다. 승계 판정이 현재 계약 검증에 실패한 경우에는 실패 종류를 새로 만들지 않고 `failed_stage: 병합·검증`, `failure_type: schema_violation`, `failure_context: carried_over_validation`으로 남긴다.

```json
{
  "schema_version": "bidops.screening-failures.v1",
  "run_id": "20260825-20260825",
  "generated_at": "2026-08-25T04:12:00+09:00",
  "failures": [
    {
      "notice_id": "bid:example:002",
      "failed_stage": "종합 판정",
      "failure_type": "truncated_output",
      "last_attempt_at": "2026-08-25T04:11:58+09:00",
      "retry_count": 1,
      "status": "사람 검토 대기",
      "failure_context": null,
      "trace_id": "trace-식별자",
      "span_id": "span-식별자"
    }
  ]
}
```

실패 목록에는 원문·회사 프로필 전문, API 키, 모델 호출 원문을 복사하지 않는다. 실패 상세가 필요하면 `trace_id`·`span_id`로 계측 기록을 연결한다. 허용되지 않은 실패를 성공 결과나 자동 등급으로 바꾸지 않는다.

## 병합 입력·출력과 버전 범위

현재 `skills/bidops-screen/scripts/build_screening_results.py`의 `merge()`는 입력 최상위 `schema_version`을 `bidops.validation-set.v2`와 정확히 비교하고, 판정 입력을 `bidops.decisions.v2`와 정확히 비교한다. 다르면 `SystemExit`로 중단한다. 이 동작은 현재 기준선으로 기록한다.

결정 0019에 근거한 예외는 이 기준선의 **수용 스키마 버전 범위만 넓히는 것**이다. 새 정기 실행의 입력 경계에는 `bidops.screening-input.v1`과 `bidops.decisions.v3`을 추가하고, 기존 회차 호환을 위해 `bidops.validation-set.v2`와 `bidops.decisions.v2`를 제한적으로 계속 읽을 수 있게 한다. 새 후보 전량 판정에 `validation-set.v2`를 사용하지 않는다는 역할 구분은 유지한다.

| 구분 | 바꾸는 부분 | 바꾸지 않는 부분 |
|---|---|---|
| 입력 수용 | `screening-input.v1` 판정 대상과 `decisions.v3` 판정을 새 입력으로 수용한다. 기존 v2 입력은 과거 산출물 호환 경로로만 수용한다. | 입력에 없는 공고나 판정을 만들어 채우지 않는다. |
| 버전 분기 | 스키마 버전별로 같은 구조 검증 경계에 연결하고 새 판정 입력의 출력은 `bidops.screening.v3`으로 쓴다. | `bidops.decisions.v2`와 `bidops.screening.v2`의 의미를 소급 변경하거나 과거 파일을 재작성하지 않는다. |
| 판정 내용 검사 | v3의 역추적·승계·혼입 표시를 보존한다. 모드와 메타데이터의 교차 검사는 판정 오케스트레이터의 입력·출력 계약에서 수행한다. | 다섯 관점, 근거, 반론, 확인 항목, 등급·준비 상태 및 그 교차 조건의 검사 규칙은 바꾸지 않는다. |
| 실패 처리 | 실패 목록에 있는 공고를 병합 대상에서 제외하고 부분 여부·실패 건수를 결과에 기록한다. | 실패 결과를 빈 값·추정값·자동 등급으로 보정하지 않는다. |
| 실행 경계 | 새 파일 계약을 별도 프로세스 호출과 명시적 어댑터로 연결한다. | 기존 스크립트를 웹 계층으로 복제하거나 내부 함수처럼 import하지 않는다. |

병합기는 다섯 관점의 정확한 구성과 각 관점의 근거, 반론, 확인 항목, 등급·참여 준비 상태를 결정적으로 검사한다. 승계 판정에도 신규·재판정과 같은 검사를 적용한다. 두 축 혼입 표시가 `true`인 판정은 이 검사에서 실패로 취급하지 않는다.

수용 조합은 다음처럼 고정한다. 서로 다른 세대의 입력을 자동으로 짝짓거나 v2 파일을 v3으로 재작성하지 않는다.

| 판정 대상 입력 | 판정 입력 | 병합 결과 |
|---|---|---|
| `bidops.screening-input.v1` | `bidops.decisions.v3` | `bidops.screening.v3` |
| `bidops.validation-set.v2`(과거 회차 호환) | `bidops.decisions.v2`(과거 회차 호환) | `bidops.screening.v2` |

이 표에 없는 버전 조합은 입력 계약 위반으로 중단한다.

## 병합 결과 계약: `bidops.screening.v3`

새 판정 대상과 v3 판정을 병합한 결과의 최상위 필드는 다음과 같다.

| 필드 | 내용 |
|---|---|
| `schema_version` | `bidops.screening.v3` |
| `run_id` | 결과가 속한 현재 회차 |
| `generated_at` | 병합 결과 생성 시각 |
| `screening_basis` | 판정에 사용한 정보 범위 |
| `source_window` | 입력 회차의 수집 기간 |
| `candidate_count` | `screening-input.v1`의 후보 전량 |
| `result_count` | 결정적 검증을 통과해 `results[]`에 들어간 건수 |
| `partial_artifact` | 일부 판정 실패 등으로 후보 전량이 결과에 들어가지 않았는지 여부 |
| `failure_count` | `screening-failures.json`의 이 회차 실패 건수 |
| `failure_artifact` | 실패 목록의 계약과 파일을 가리키는 객체. 실패 목록이 없으면 `null` |
| `results[]` | 정규화 공고와 검증된 판정의 결합 결과 |

`partial_artifact`는 판정·병합 산출물의 완전성 표시이며, 스케줄 전체의 `부분 성공` 상태와 동일한 필드가 아니다. 사전규격 권한 경고나 보고서 생성 실패처럼 회차 전체의 상태를 바꾸는 사유는 실행 이력의 상태와 경고에 남긴다. 판정 실패가 하나라도 유효 결과와 함께 남으면 `partial_artifact: true`, `failure_count`는 실패 목록 건수로 기록한다. 모든 후보가 검증을 통과하면 `partial_artifact: false`, `failure_count: 0`, `failure_artifact: null`이다. 전역 병합·검증 실패로 정본 결과를 만들 수 없으면 `screening.v3`을 성공 결과로 만들지 않는다. 아래 수량은 구조 예시이며 실제 값은 회차별 후보·결과·실패 목록에서 측정한다.

```json
{
  "schema_version": "bidops.screening.v3",
  "run_id": "20260825-20260825",
  "generated_at": "2026-08-25T04:15:00+09:00",
  "screening_basis": "회차에 고정된 정규화 공고와 정책 버전",
  "source_window": {"from": "2026-08-24", "to": "2026-08-24", "timezone": "Asia/Seoul"},
  "candidate_count": 60,
  "result_count": 59,
  "partial_artifact": true,
  "failure_count": 1,
  "failure_artifact": {
    "schema_version": "bidops.screening-failures.v1",
    "file": "screening-failures.json"
  },
  "results": []
}
```

예시의 `results[]`는 구조를 줄여 표시한 것이며, 실제 파일에서는 검증을 통과한 각 공고의 `notice`와 `judgment`를 모두 보존한다. `candidate_count`, `result_count`, `failure_count`는 누락 건을 0으로 숨기지 않도록 함께 기록한다.

## 호출 계측 기록 계약: `bidops.screening-telemetry.v1`

호출 계측은 `screening-telemetry.jsonl`에 호출 스팬 하나를 한 줄의 JSON으로 기록한다. 공고 하나가 하나의 `trace_id`를 가지며, 관점 다섯 번·반론·종합 호출은 각각 별도 스팬이다. 재시도는 같은 트레이스 아래 새 시도 스팬으로 남기고 앞선 실패 스팬을 삭제하지 않는다. 승계 판정은 모델을 호출하지 않으므로 모델 호출 스팬을 만들지 않는다.

| 필드 | 내용 |
|---|---|
| `schema_version` | `bidops.screening-telemetry.v1` |
| `trace_id` | 공고 단위 트레이스 식별자 |
| `span_id` | 호출·시도 단위 스팬 식별자 |
| `parent_span_id` | 상위 스팬 식별자. 없으면 `null` |
| `run_id` | 현재 회차 식별자 |
| `notice_id` | 공고 식별자 |
| `stage` | 다섯 관점, `반론 검토`, `종합 판정` 중 호출 단계 |
| `attempt` | 같은 회차·공고·단계의 시도 번호. 최초 시도는 1이다. |
| `status` | `success` 또는 `failure` |
| `done_reason` | Ollama 응답의 종료 사유. 응답이 없으면 `null` |
| `prompt_eval_count` | 입력 토큰 수. Ollama 응답 값을 그대로 보존 |
| `eval_count` | 출력 토큰 수. Ollama 응답 값을 그대로 보존 |
| `prompt_eval_duration` | 입력 처리 시간. Ollama 응답 값을 그대로 보존 |
| `eval_duration` | 생성 시간. Ollama 응답 값을 그대로 보존 |
| `load_duration` | 모델 적재 시간. Ollama 응답 값을 그대로 보존 |
| `model_name`, `model_version` | 호출 모델과 확인된 버전 |
| `prompt_version`, `policy_version` | 호출에 고정한 불변 버전 |
| `recorded_at` | 계측 기록 시각. 시간대 포함 값 |

토큰 수와 시간은 Ollama가 반환한 값을 다시 계산해 대체하지 않는다. 응답이 없는 실패에서는 알 수 없는 값을 `unknown` 또는 `null`로 남긴다. 계측은 성공한 호출도 기록하며, `done_reason`, `prompt_eval_count`, `eval_count`, `prompt_eval_duration`, `eval_duration`, `load_duration`을 관측 가능한 범위에서 함께 보존한다.

```json
{
  "schema_version": "bidops.screening-telemetry.v1",
  "trace_id": "trace-식별자",
  "span_id": "span-식별자",
  "parent_span_id": null,
  "run_id": "20260825-20260825",
  "notice_id": "bid:example:000",
  "stage": "기술 적합성",
  "attempt": 1,
  "status": "success",
  "done_reason": "stop",
  "prompt_eval_count": 3000,
  "eval_count": 400,
  "prompt_eval_duration": 0,
  "eval_duration": 0,
  "load_duration": 0,
  "model_name": "qwen3.8:27b",
  "model_version": "확인된 모델 식별 정보",
  "prompt_version": "screening-prompt.v1",
  "policy_version": "screening-policy.v1.20260825",
  "recorded_at": "2026-08-25T02:04:00+09:00"
}
```

위 호출 계측 수량은 필드 위치를 설명하기 위한 예시이며 실제 회차에서 확인한 값이 아니다. 토큰 수와 시간의 `0`은 Ollama가 반환한 값일 때만 의미가 있으며, 측정하지 못한 값을 0으로 채우지 않는다. 이 기록은 관측·성능·실패 원인 분석 목적이며, 판정의 정본이 아니다. 등급·준비 상태·근거·승계 여부의 정본은 검증된 `bidops.decisions.v3`와 `bidops.screening.v3`이다. 계측 기록에 회사 자료 전문, 원문 전체, API 키를 넣지 않는다.

## 정책 버전 계약: `bidops.screening-policy.v1`

정책 저장소는 다섯 관점의 프롬프트와 후보 선정 기준·임계값을 하나의 불변 정책 버전으로 묶는다. 저장은 새 버전을 만드는 동작이며, 활성 버전을 제자리에서 수정하지 않는다. 활성화 이후 회차에는 해당 정책 버전 식별자만 적용하고, 완료 회차의 정책 참조를 바꾸지 않는다.

| 필드 | 내용 |
|---|---|
| `schema_version` | `bidops.screening-policy.v1` |
| `policy_version` | 불변 정책 버전 식별자 |
| `status` | `draft`, `activation_candidate`, `active` 중 하나 |
| `created_at`, `created_by` | 저장 시각과 저장 담당자 |
| `prompt_version` | 이 정책에 묶인 전체 프롬프트 버전 |
| `perspective_prompts` | 아래 다섯 관점 이름을 키로 하는 프롬프트 객체 |
| `counterargument_prompt`, `synthesis_prompt` | 반론·종합 호출의 프롬프트와 출력 계약 |
| `candidate_selection` | 후보 전량을 만드는 규칙의 불변 버전과 신호별 조건 |
| `thresholds` | 품질 게이트·병합 검증·후보 선정에 적용하는 임계값 구조 |

`perspective_prompts`는 다음 다섯 키를 정확히 한 번씩 가진다. 각 객체에는 `prompt_version`, 템플릿 본문, 허용 입력 필드 목록, 출력 스키마 식별자, 근거 위치 요구사항을 둔다. 실제 회사 자료나 공고 원문은 정책 버전에 넣지 않는다.

| 키 | 프롬프트가 답하는 관점 |
|---|---|
| `기술 적합성` | 요구 기술과 수행 역할을 회사가 보유하는지 |
| `실적 정합성` | 수행실적이 과업과 실제로 대응하는지 |
| `공공 SI 적합성` | 구축·고도화·운영·통합·ISP/BPR 중 어디에 해당하는지 |
| `사업성·자격 제약` | 예산·지역·업종·실적·참여 형태가 제약하는지 |
| `전략 부합` | 우선 축과 신규 진출 방향에 부합하는지 |

`candidate_selection`은 `rules_version`과 다음 신호의 조건 객체를 가진다. 신호의 값과 임계값은 저장 시 확인된 정책 값으로 채우며, 확인되지 않은 값을 임의의 0·빈 문자열·통과값으로 저장하지 않는다.

| 구조 | 내용 |
|---|---|
| `focus_title` | 공고 제목에 나타난 우선 축 신호와 사용 필드 |
| `focus_classification` | 조달 분류 라벨 신호와 제목 신호와 구분하는 조건 |
| `performance_similarity` | `performance_top_score` 등 탐색 신호와 후보화 임계값 |
| `include_conditions` | 위 신호와 규칙 필터를 후보 전량에 적용하는 결합 조건 |
| `unknown_handling` | 확인 불가 값을 후보 제외나 확정 자격으로 바꾸지 않는 처리 |

`thresholds`는 이름을 고정한 중첩 객체로 저장한다. 현재 확정된 품질 게이트 기준은 다음과 같이 표현하며, 정보 충분성에는 별도 합격 수치를 만들지 않는다.

```json
{
  "schema_version": "bidops.screening-policy.v1",
  "policy_version": "screening-policy.v1.20260825",
  "status": "activation_candidate",
  "created_at": "2026-08-25T01:00:00+09:00",
  "created_by": "담당자 식별자",
  "prompt_version": "screening-prompt.v1",
  "perspective_prompts": {
    "기술 적합성": {"prompt_version": "screening-prompt.v1", "template": "불변 템플릿", "input_fields": [], "output_schema": "perspective.v1", "evidence_location_required": true},
    "실적 정합성": {"prompt_version": "screening-prompt.v1", "template": "불변 템플릿", "input_fields": [], "output_schema": "perspective.v1", "evidence_location_required": true},
    "공공 SI 적합성": {"prompt_version": "screening-prompt.v1", "template": "불변 템플릿", "input_fields": [], "output_schema": "perspective.v1", "evidence_location_required": true},
    "사업성·자격 제약": {"prompt_version": "screening-prompt.v1", "template": "불변 템플릿", "input_fields": [], "output_schema": "perspective.v1", "evidence_location_required": true},
    "전략 부합": {"prompt_version": "screening-prompt.v1", "template": "불변 템플릿", "input_fields": [], "output_schema": "perspective.v1", "evidence_location_required": true}
  },
  "candidate_selection": {
    "rules_version": "후보 선정 규칙의 불변 버전",
    "focus_title": {"enabled": true, "source_fields": ["title"]},
    "focus_classification": {"enabled": true, "source_fields": ["procurement_class"]},
    "performance_similarity": {"enabled": true, "source_fields": ["performance_top_score"], "threshold": "정책에 저장된 확인값"},
    "include_conditions": [],
    "unknown_handling": "unknown을 제외·확정 자격으로 치환하지 않음"
  },
  "thresholds": {
    "quality_gate": {
      "reproducibility_grade_min_pct": 80,
      "reviewer_agreement_min_pct": 70,
      "evidence_missing_max_pct": 10,
      "perspective_split_min_pct": 40,
      "discrimination_min_pct": 10,
      "discrimination_max_pct": 25,
      "audit_sample_size": 10,
      "information_sufficiency_pass_pct": null
    },
    "validation": {"counterargument_repetition_max_pct": 40}
  },
  "counterargument_prompt": {"prompt_version": "screening-prompt.v1", "template": "불변 템플릿", "output_schema": "counterargument.v1"},
  "synthesis_prompt": {"prompt_version": "screening-prompt.v1", "template": "불변 템플릿", "output_schema": "judgment.v3"}
}
```

위 구조의 `threshold`와 템플릿은 설명용 자리이며 측정되지 않은 운영값을 확정값으로 주장하지 않는다. 정책 활성화에는 품질 게이트 결과와 담당자의 명시적 활성화가 필요하다. 게이트가 미측정·계산 불가·미달이면 활성화하지 않고 기존 활성 정책을 유지한다.

## 정기 실행·운영·정책 REST 확장 계약

아래 경로는 스케줄 설정·실행 이력·상시 운영 스위치·정책 버전을 관리 화면이 조회하고 수정하기 위한 명명된 모델 계약이다. 기본 경로·오류 형태·시간대·`null` 처리 규칙은 공통 REST 규약을 따른다. 실제 구현은 이 계약에 맞춰 별도 작업으로 연결하며, 스케줄러는 입찰 제출·발주처 연락·최종 참여 결정을 호출하지 않는다.

| 호출 | 요청 모델 | 성공 응답 모델 | 오류 |
|---|---|---|---|
| `GET /api/schedule/settings` | 없음 | `ScheduleSettingsResponse` | 설정 조회 실패 500 |
| `PATCH /api/schedule/settings` | `ScheduleSettingsUpdateRequest` | `ScheduleSettingsResponse` | 시간 형식 오류 422, 저장 실패 400 |
| `GET /api/schedule/executions` | `ScheduleExecutionQuery` | `ScheduleExecutionListResponse` | 범위·상태 오류 422 |
| `GET /api/schedule/always-on` | 없음 | `AlwaysOnSwitchResponse` | 스위치 조회 실패 500 |
| `PUT /api/schedule/always-on` | `AlwaysOnSwitchUpdateRequest` | `AlwaysOnSwitchResponse` | 게이트 미달·미측정 409, 요청 오류 422 |
| `GET /api/policies` | `PolicyVersionQuery` | `PolicyVersionListResponse` | 상태 오류 422 |
| `GET /api/policies/{policy_version}` | 경로 정책 버전 | `PolicyVersionResponse` | 정책 버전 없음 404 |
| `POST /api/policies` | `PolicyVersionCreateRequest` | `PolicyVersionResponse` | 구조 오류 422, 같은 불변 버전 409 |
| `POST /api/policies/{policy_version}/activate` | `PolicyActivationRequest` | `PolicyActivationResponse` | 정책 없음 404, 게이트 미달·미측정 409 |

### 스케줄 설정 모델

`ScheduleSettingsResponse`는 다음 필드를 가진다. 상시 운영 여부는 이 모델에서 수정하지 않고 `AlwaysOnSwitchResponse`로 분리한다.

| 필드 | 내용 |
|---|---|
| `timezone` | `Asia/Seoul` 고정 시간대 |
| `daily_time` | 일간 작업 시각. 기본 `02:00` |
| `weekly_time` | 주간 누계 시각. 기본 `06:00` |
| `prespec_enabled` | 사전규격 API 호출 설정. 기본 `false` |
| `updated_at`, `updated_by` | 마지막 변경 시각과 담당자 |

`ScheduleSettingsUpdateRequest`는 `daily_time`, `weekly_time`, `prespec_enabled` 중 변경할 필드만 가진다. 시간은 `HH:MM`이며 서버 로컬 시간으로 해석하지 않는다. `timezone`과 상시 운영 스위치는 요청으로 바꿀 수 없다.

```json
{
  "timezone": "Asia/Seoul",
  "daily_time": "02:00",
  "weekly_time": "06:00",
  "prespec_enabled": false,
  "updated_at": "2026-08-25T00:30:00+09:00",
  "updated_by": "담당자 식별자"
}
```

### 실행 이력 모델

`ScheduleExecutionQuery`는 `from`, `to`, `status`, `limit`, `offset`을 가진다. `status`는 정기 실행의 여섯 상태 중 하나이며, 날짜 범위는 `Asia/Seoul` 기준이다. `GET /api/schedule/executions`는 이 조건으로 예약·실행 이력을 최신 순으로 반환한다. `ScheduleExecutionListResponse`는 `items: ScheduleExecutionSummary[]`, `total`, `limit`, `offset`을 가진다. `ScheduleExecutionSummary`의 `status`는 `예약`, `실행 중`, `성공`, `부분 성공`, `실패`, `건너뜀` 중 하나다.

| 필드 | 내용 |
|---|---|
| `run_key` | `YYYYMMDD-YYYYMMDD` 논리 회차 키 |
| `run_id` | 실제 불변 회차 식별자. 아직 생성되지 않았으면 `null` |
| `window_from`, `window_to` | 회차에 고정한 수집 기간 |
| `status` | 정기 실행의 여섯 상태 |
| `execution_id` | 예약을 획득한 실행 식별자 |
| `trigger` | `schedule` 또는 `manual` |
| `skip_reason` | 중복·스위치 중지·수동 충돌 등 건너뜀 사유. 해당하지 않으면 `null` |
| `started_at`, `finished_at` | 실행 시작·종료 시각. 미실행이면 `null` |
| `candidate_count`, `result_count`, `failure_count` | 후보 전량·유효 결과·판정 실패 건수. 확인되지 않으면 `null` |
| `partial_artifact` | 회차 결과가 부분 산출물인지 여부. 확인되지 않으면 `null` |
| `policy_version`, `model_name`, `model_version`, `prompt_version` | 실행에 고정한 역추적 정보 |

`run_key`에는 데이터베이스 유일 제약을 적용한다. 유일 제약에 걸린 요청은 새 회차를 시작하지 않고 `건너뜀`으로 기록하며, 기존 예약의 상태를 바꾸지 않는다. 실패·부분 성공 이력은 다음 회차와 합치거나 자동으로 성공으로 승격하지 않는다.

### 상시 운영 스위치 모델

`AlwaysOnSwitchResponse`는 `BIDOPS_SCHEDULER_ENABLED`에 해당하는 운영 상태와 게이트 연결 정보를 함께 반환한다. `AlwaysOnSwitchUpdateRequest`는 `enabled: bool`과 `confirmed_by`를 가진다.

| 필드 | 내용 |
|---|---|
| `enabled` | 상시 일간·주간 예약 등록 여부 |
| `quality_gate_status` | `통과`, `미달`, `미측정`, `보류` 중 하나 |
| `quality_gate_result_id` | 활성화 판단에 사용한 불변 게이트 결과 식별자. 없으면 `null` |
| `policy_version`, `model_name`, `model_version`, `prompt_version` | 스위치 변경 시점의 기준 버전 |
| `updated_at`, `updated_by` | 변경 시각과 담당자 |
| `rejection_reason` | `enabled: true` 요청이 거부된 사유. 정상 처리면 `null` |

`enabled: true` 요청은 품질 게이트가 필요한 값 모두를 갖추고 임계값을 충족했을 때만 성공한다. 게이트가 `계산 불가`·미측정·미달이면 409로 거부하고 이력을 남긴다. 게이트 통과는 활성화 권한을 대신하지 않으며, 담당자가 명시적으로 스위치를 켜야 한다. `enabled: false`는 예약을 `건너뜀`으로 만들며 기존 산출물과 실행 이력을 삭제하지 않는다.

```json
{
  "enabled": false,
  "quality_gate_status": "통과",
  "quality_gate_result_id": "gate-식별자",
  "policy_version": "screening-policy.v1.20260825",
  "model_name": "qwen3.8:27b",
  "model_version": "확인된 모델 식별 정보",
  "prompt_version": "screening-prompt.v1",
  "updated_at": "2026-08-25T00:45:00+09:00",
  "updated_by": "담당자 식별자",
  "rejection_reason": null
}
```

### 정책 버전 REST 모델

`PolicyVersionQuery`는 선택 필드 `status`를 가지며 `draft`, `activation_candidate`, `active` 중 하나로 정책 버전을 필터링한다.

`PolicyVersionCreateRequest`는 `policy_version`, `created_by`, `prompt_version`, `perspective_prompts`, `counterargument_prompt`, `synthesis_prompt`, `candidate_selection`, `thresholds`를 가진다. 서버는 저장 시 새 불변 버전을 만들며 동일한 `policy_version`을 덮어쓰지 않는다.

`PolicyVersionResponse`는 위 저장 필드와 `schema_version`, `status`, `created_at`, `created_by`, `activated_at`, `activated_by`, `quality_gate_result_id`를 가진다. `activated_at`, `activated_by`, `quality_gate_result_id`는 활성화 전 `null`이다. `PolicyVersionListResponse`는 `items: PolicyVersionResponse[]`, `total`, `active_policy_version`을 가진다.

`PolicyActivationRequest`는 `quality_gate_result_id`와 `confirmed_by`를 가진다. `PolicyActivationResponse`는 `policy: PolicyVersionResponse`, `previous_active_policy_version`, `activation_status`, `activated_at`을 가진다. 활성화할 정책은 게이트 결과가 참조하는 모델·프롬프트·정책 버전과 일치해야 하며, 일치하지 않거나 게이트가 미달·미측정이면 409다. 새 정책 활성화는 이전 정책과 완료 회차의 참조를 소급 변경하지 않는다.

```json
{
  "schema_version": "bidops.screening-policy.v1",
  "policy_version": "screening-policy.v1.20260825",
  "status": "active",
  "prompt_version": "screening-prompt.v1",
  "created_at": "2026-08-25T01:00:00+09:00",
  "created_by": "담당자 식별자",
  "activated_at": "2026-08-25T01:30:00+09:00",
  "activated_by": "담당자 식별자",
  "quality_gate_result_id": "gate-식별자",
  "perspective_prompts": {},
  "counterargument_prompt": {},
  "synthesis_prompt": {},
  "candidate_selection": {},
  "thresholds": {}
}
```

REST 응답은 정책 템플릿과 기준 구조를 반환할 수 있지만, API 키·회사 프로필 전문·공고 원문을 포함하지 않는다. 정책 저장·활성화·스위치 변경은 담당자와 시각, 적용 버전을 관리 이력에 남기며, 메일·메신저 등 외부 알림을 만들지 않는다.
