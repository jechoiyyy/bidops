# 사전규격 엔진 검토

[RL-11 개정안](../work/groups/RL/features/RL-11-live-prespec-engine/track-start-entry.md)의 1단계 계약이다. 회사 범위는 환경에 설정한 루트랩 위키 묶음 하나다. API와 검토 영수증에는 `company_id`가 없다. 묶음은 슬러그와 `bundle_sha256`으로 식별한다. 기존 회사별 [엔진 실행](engine-runs.md)과 목업 워커를 함께 사용한다.

`GET /api/feature-flags`는 `engine_review`에 `BIDOPS_ENGINE_REVIEW_MODE` 설정값을 반환한다. Compose는 이 값과 `BIDOPS_ENGINE_ANALYSIS_ENABLED`를 web과 analysis-worker에 함께 전달한다.

| 설정 | 기본값 | 환경별 허용 값 |
|---|---|---|
| `BIDOPS_ENGINE_REVIEW_MODE` | `off` | dev·mock은 `off`, `live`, `mock_reference`를 허용한다. `mock_reference`는 `BIDOPS_REFERENCE_WORKFLOW_MODE=true`가 필요하며 mock overlay가 이 값을 설정한다. prod에는 `off`, `live`만 허용한다. |
| `BIDOPS_ENGINE_ANALYSIS_ENABLED` | `false` | 세 환경 모두 `false` 또는 `true`를 받는다. 목업 승인과 worker claim에는 두 서비스 모두 `true`가 필요하다. |

알 수 없는 검토 모드는 기동 시 오류다. prod overlay의 고정된 `BIDOPS_ENV=prod` 설정은 참조 모드와 관계없이 `mock_reference` 기동을 거부한다. 목업은 외부 호출을 0회로 고정한다. `live` 미리보기와 승인은 503 `engine_live_disabled`를 반환한다.

## REST

아래의 `…`는 `/api/pre-specs/{notice_id}/engine-review`다. 모든 POST에 UUID `request_id`와 `X-BidOps-Actor-Name`이 필요하다. 기존 비ASCII 담당자 헤더 형식을 지원한다. 추적 시작을 호출한 사전규격 클라이언트는 저장 성공 뒤 요청을 등록한다. 요청 실패 후 저장된 추적 결정에서 재시도할 수 있다.

| 메서드와 경로 | 본문 | 성공 응답 |
|---|---|---|
| GET `…` | 없음 | 200 `state, next_action, reason, request, preview, current_result, review_receipt`. 읽기만 한다 |
| POST `…/requests` | `request_id, origin` (`tracking_start\|manual`) | 201 새 요청 또는 200 기존 요청. `request, state` |
| POST `/api/pre-specs/engine-review/requests:batch` | `request_id, notice_ids` (1–200개), `origin: tracking_start` | 200 `items[{notice_id,outcome,request,reason}]`. 결과는 `requested\|already_requested\|ineligible`. 입력 순서대로 공고별 처리하며 중복 공고 ID는 한 번 처리한다 |
| POST `…/previews` | `request_id` | 200 `preview_id, manifest_sha256, created_at, expires_at, manifest` |
| POST `…/approvals` | `preview_id, manifest_sha256, request_id` | 202 `approval_id, run_id, state`. `state`는 현재 엔진 실행 상태다 |
| POST `…/dismissals` | `preview_id, request_id` | 200 `dismissal_id, request`. 해당 요청을 닫는다 |
| POST `…/acknowledgments` | `result_id`(엔진 실행 UUID), `request_id` | 200 `acknowledgment_id, result_id, request_id, acknowledged_by, acknowledged_at` |

요청 영수증은 `id, notice_id, opportunity_id, company_bundle_slug, origin, requested_by, requested_at, request_id, closed_at, closed_reason, closed_by`를 담는다. 미리보기 manifest는 공고·묶음·문서 버전과 해시, 파일명과 쪽 수, 절과 쪽 범위, primary format, 엔진 버전·digest, 회사 묶음 슬러그·digest, 선택·생략한 위키 페이지 및 발췌 글자 수, 실행 모드·정책·분할·수신 모델, 예정·잔여 호출 수를 담는다. `valid_from`도 canonical JSON에 포함한다. 동일 입력의 유효한 미리보기를 재사용하고 24시간이 지난 미승인 미리보기는 새 `request_id`로 발급할 수 있다. 새 미리보기의 유효 시작과 digest가 달라지며 이전 영수증은 보존한다.

HWP/HWPX 추출 구조의 쪽 수는 HWPX XML 구역 수다. 이 미리보기 경로에서 실제 쪽 수를 확인할 수 없어 `manifest.documents[].page_count`는 `null`이다. 실제 쪽과 대응하지 못한 절의 `page_start`와 `page_end`도 `null`이다. 현재 추출 블록에는 목차와 본문을 구별하는 `type`이나 속성이 없어 같은 이름의 제목이 절 목록에 남을 수 있다. 구역 수를 쪽 수로 기록한 기존 영수증은 보존한다. 해당 미승인 미리보기는 상태 조회에서 빠지며 승인 전에 새 `request_id`로 다시 발급해야 한다. 유효 기간 안에 이전 미리보기의 승인을 시도하면 `409 input_changed`다.

공고에 열린 요청은 하나다. 같은 `lifecycle_json.pre_spec_no`로 저장된 행이 여러 개면 게시 시각이 가장 최근인 행을 쓰고, 시각이 같거나 모두 없으면 가장 큰 공고 ID를 쓴다. 동일 명령의 `request_id` 재전송은 같은 영수증을 참조한다. 이미 열린 요청 또는 승인된 미리보기에는 다른 `request_id`를 보내도 기존 영수증을 참조한다. 승인과 실행·작업 등록은 같은 트랜잭션에서 저장한다. 일괄 요청은 요청만 등록한다. 승인 직전에 서버가 원본과 미리보기의 해시, 만료, 추적 상태를 다시 확인한다.

`current_result`는 [EngineRunView](engine-runs.md)다. `stale`에서는 이전 입력 결과를 함께 반환할 수 있다. `review_receipt`는 현재 결과의 읽음 영수증이다. 해당 데이터가 없는 필드는 `null`이다.

## 상태와 업무량

| 상태 | 조건 | `next_action` |
|---|---|---|
| `not_requested` | 열린 요청 없음 | 자격이 있는 계속 추적 공고는 `request`, 그 외 `null` |
| `preparing` | 열린 요청이 있고 문서 준비가 진행 중 | `null` |
| `blocked` | 입력이나 실행을 확인해야 함 | `resolve_exception` |
| `awaiting_approval` | 열린 요청에 미리보기 발급 가능 | 계속 추적이면 `approve`, 보류이면 `null` |
| `queued\|running` | 승인된 현재 입력의 실행이 대기·실행 중 | `null` |
| `result_ready` | 현재 입력에 결과가 있고 읽음 영수증 없음 | `review_result` |
| `acknowledged` | 현재 입력 결과에 읽음 영수증 있음 | `null` |
| `stale` | 이전 실행의 입력이 바뀌었거나 현재성을 확인할 수 없음 | 자격이 있는 계속 추적 공고는 `request`, 그 외 `null` |

추적이 종료 또는 미선택이면 조회에서 요청을 닫힌 상태로 해석한다. 다음 요청·미리보기·승인 명령이 닫힘을 기록한다. 종료 뒤 다시 추적하더라도 이전 요청을 복구하지 않는다. `보류`에는 요청을 유지한다. GET, 분석 요청·승인·실행·읽음은 추적 상태나 최종 Go/No-Go를 바꾸지 않는다. 열린 요청은 첨부 취득과 문서 준비 자격을 추가한다. 개요 enqueue는 기존 자격 계산을 사용한다.

`GET /api/workload`의 `items`에 `engine_approval_pending`, `engine_result_pending`을 추가한다. 각각 `approve`, `review_result`인 공고를 센다. 기능이 꺼져 있으면 `count: null`이다.

## 오류와 저장

오류는 엔진 실행 API의 `{error:{code,message,details}}` envelope를 따른다. 명령 거부 시 `details.reason`을 확인한다. 건너뛰기·읽음 명령의 `input_changed`에는 `details.current`로 새 상세를 제공한다. 본문 형태나 값 검증 실패는 422다.

| HTTP | 코드 |
|---|---|
| 400 | `actor_name_required`, `actor_name_invalid` |
| 404 | `not_found` |
| 409 | `tracking_required`, `notice_not_latest`, `review_excluded`, `request_required`, `company_bundle_unavailable`, `company_bundle_invalid`, `documents_pending`, `original_hwp_required`, `unsafe_document`, `structure_unavailable`, `preview_expired`, `input_changed`, `idempotency_conflict`, 요청 등록의 `engine_disabled`(목업 실행 스위치 꺼짐) |
| 422 | `input_too_large`, 잘못된 본문 |
| 503 | `engine_disabled`, `engine_live_disabled`, `engine_unavailable` |

조회 `reason`의 어휘는 `tracking_required`, `documents_pending`, `original_hwp_required`, `unsafe_document`, `structure_unavailable`, `company_bundle_unavailable`, `company_bundle_invalid`, `engine_disabled`, `engine_live_disabled`, `budget_exhausted`, `input_changed`다. `off`의 조회는 `not_requested`와 `engine_disabled`를 반환한다.

`0045_engine_review`는 `engine_review_request`, `engine_review_preview`, `engine_review_approval`, `engine_review_acknowledgment`를 추가한다. 미리보기·승인·읽음 영수증은 불변이다. 요청은 `tracking_ended\|dismissed\|superseded` 사유로 한 번 닫을 수 있다. 건너뛰기 영수증은 닫힘과 해당 감사 이벤트를 참조한다. 감사는 `engine_review.requested`, `.preview_created`, `.approved`, `.dismissed`, `.closed`, `.acknowledged`이며 담당자, 식별자, 안전한 메타데이터를 저장한다.
