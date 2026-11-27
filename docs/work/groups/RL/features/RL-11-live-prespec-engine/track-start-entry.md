# 개정안: 분석 진입을 사람의 추적 시작에 묶는다

[사용자 목표](intent.md) · [최종 흐름 명세](spec.md) · [실행 계획](plan.md) · [상세 화면 설계](detail-layout.md) · [결정 기록 ADR-0078](../../../../../tracking/decisions/0078-engine-review-on-tracking-start.md)

2026-11-24 사용자 결정 둘: "B로 진행해보자"(분석 진입), "루트랩 wiki로만 진행"(회사 입력). [최종 흐름 명세](spec.md)의 **분석 대상이 정해지는 방식**과 **회사를 식별하는 방식**만 바꾼다. 전송 미리보기·건별 승인·감사·호출 상한·원문 검증·결과 확인·사람 인수는 명세 그대로다. 이 문서와 명세가 다르면 진입 조건에 한해 이 문서가 우선한다. 구현 전 설계이며 실제 모델 전송과 운영 활성화의 근거가 아니다.

## 1. 무엇이 바뀌나

| 항목 | 명세(2026-11-20) | 개정 |
|---|---|---|
| 분석 대상 | 시스템이 고른다: SW=Y 또는 우선 검토 자격이면서 계속 추적·보류이거나 의견 마감 전·미추적인 공고를 자동으로 승인 대기에 올린다 | **사람이 고른 공고만.** 사전규격에서 추적을 시작하거나, 이미 추적 중인 사전규격에서 `분석 요청`을 눌렀을 때만 분석 요청이 생긴다 |
| 미추적 공고 | 마감 전이면 자동 후보 | 후보가 아니다. 개요까지만 자동이다 |
| 승인 대기에 오르는 시점 | 준비가 끝나면 자동으로 미리보기 생성 | 분석 요청이 있고 원문 준비가 끝난 공고만. 미리보기는 담당자가 전송 자료를 열 때 만든다 |
| 개요 완료 여부 | 정상 후보는 개요 완료가 조건(실패 시 긴급 우회 규칙) | 조건이 아니다. 사람이 요청한 공고는 개요 상태와 무관하게 원문 준비만 본다. 개요 우회 규칙(명세 "실패와 복구" 마지막 행)은 쓰지 않는다 |
| 회사 | BidOps에 등록한 회사(`company`)와 활성 회사 근거 바인딩이 있어야 실행을 만들 수 있고 API는 회사 범위(`/api/companies/{company_id}/…`)다 | **루트랩 위키 묶음 하나가 회사다.** 설정된 회사 자료 묶음(`BIDOPS_ENGINE_COMPANY_BUNDLE_DIR`·`_SLUG`, 운영은 `rootlab`)만 쓴다. 회사 등록·바인딩을 요구하지 않고 API에 회사 ID가 없다 |
| 2026-11-19 결정 "추적 결정은 추적만 정한다" | 유지 | **바꾼다**: 사전규격의 추적 시작은 분석 **요청**을 함께 올린다. 외부 전송 **승인**은 여전히 별도 행동이다 |

그대로인 것: 추적 상태·최종 Go/No-Go는 사람이 정하고 분석 결과가 바꾸지 않는다. 승인 전 외부 전송 0건. 한 공고의 동결 입력 한 건에 대한 건별 승인. RL 정책 자동 승인으로 대체 불가. 호출 상한(시운전: KST 하루 1개 공고·하루 8회·공고 누적 8회). 결과는 사람 인수 전까지 `unmeasured_reference`.

**이렇게 정한 이유.** 실제 실행은 한 건에 220~365초·누적 입력 170만~250만 토큰이고(2026-11-23 시험) 원문과 회사 자료가 외부 모델로 나간다. RL-05는 reject, 2026-11-23 시험에서도 사람이 "진행 어려움"으로 본 공고를 엔진이 조건부 진행으로 낸 사례가 있다. 개요는 하루 30~80건 완료되지만 추적 중인 사전규격 사업은 8건이다(2026-11-24 운영 조회). 사람이 이미 볼 가치가 있다고 고른 건으로 물량을 묶는다.

## 2. 용어

| 말 | 뜻 | 누가 |
|---|---|---|
| 분석 요청 | "이 사전규격을 분석해 달라"는 기록. 아무것도 전송하지 않는다 | 사람(추적 시작 또는 `분석 요청`) |
| 전송 자료(미리보기) | 보낼 문서 범위·회사 자료 묶음 digest·고른 위키 페이지·수신 모델·예정 호출 수를 동결해 보여 주는 화면 | 서버가 만들고 사람이 읽는다 |
| 전송 승인 | 그 미리보기 한 건을 보내도 된다는 영수증 | 사람, 공고마다 |
| 분석 실행 | 승인된 입력으로 공용 슬롯에서 도는 작업 | worker |
| 결과 확인 | 결과를 읽었다는 영수증. 추적 결정과 별개다 | 사람 |

## 3. 담당자가 겪는 흐름

| 상황 | 화면 | 사람이 하는 일 | 시스템이 하는 일 |
|---|---|---|---|
| 미추적 사전규격을 읽고 추적하기로 함 | 사전규격 상세·목록 미리보기의 결정 띠 | `추적 시작하기` 한 번 | 추적 상태 저장(기존 API) → 이어서 분석 요청 등록. 띠가 다음 상태로 바뀐다 |
| 원문이 아직 준비되지 않음 (마감 지난 미추적 건이 대표적) | 결정 띠: `분석 준비 중` + 남은 일(첨부 취득·변환) | 없음 | 요청이 열려 있는 공고를 첨부 취득·문서 준비 대상으로 처리 |
| 원문 준비 끝 | 결정 띠 주 행동이 `전송 자료 확인`. 오늘 할 일의 `분석 승인 대기` 건수에 포함 | `전송 자료 확인`을 열어 범위를 읽고 `승인`(또는 `이번엔 보내지 않음`) | 미리보기 동결, 승인 영수증과 실행을 한 트랜잭션에 생성 |
| 분석 중 | 결정 띠: `분석 중` | 없음 | 단계 실행·검증·게시 |
| 결과 도착 | 분석 결과 화면. 오늘 할 일의 `결과 확인` 건수에 포함 | 차단·미확인·대응표를 원문과 대조하고 `계속 추적`·`보류`·`종료` 중 선택(사유 입력은 기존 그대로). 읽음만 남길 수도 있다 | 결과 확인 영수증, 추적 결정은 기존 감사 API |
| 준비할 수 없음 (원본 없음·암호화·회사 자료 묶음 오류) | 결정 띠: `분석할 수 없어요` + 이유 한 줄 + 할 일 | 원본 보완 등 | 요청은 열린 채 둔다. 조건이 풀리면 다시 승인 대기 |
| 이미 추적 중인 사업에 사전규격이 들어옴 (발주계획에서 추적 시작한 경우) | 결정 띠 보조 행동 `분석 요청` | `분석 요청` | 같은 요청 등록. 이후 같다 |
| 여러 건을 한 번에 추적 시작 | 일괄 추적 시작 대화상자 | 확인 | 추적을 시작한 공고마다 분석 요청만 등록. **일괄로는 승인하지 않는다** |

같은 화면에서 두 번 누른다(추적 시작 → 전송 자료 확인·승인). 추적 시작 단추에 전송 승인을 합치지 않는 이유는 승인 대상이 동결된 입력 한 건이어야 하는데 누르는 시점에는 원문이 준비되지 않은 경우가 많기 때문이다.

## 4. 규칙

1. **분석 요청은 사람의 행동에서만 생긴다.** 적재·등급 변경·개요 완료·연결 수락·cron은 요청을 만들지 않는다.
2. **추적 시작이 요청을 올리는 범위.** 사전규격 화면의 추적 시작(단건: 상세 결정 띠와 목록 미리보기, 일괄: 사전규격 목록의 일괄 추적 시작)에서 `미선택 → 계속 추적`이 저장된 직후 그 사전규격에 요청을 등록한다. 발주계획·사업기회·입찰공고 화면의 추적 시작은 요청을 만들지 않는다.
3. **요청 자격.** 대상이 현재(latest) 사전규격이고, 권위 연결된 사업의 추적 상태가 `계속 추적`이며, 검토 제외가 아니고, 엔진 분석 스위치가 켜져 있고, 회사 자료 묶음이 설정돼 읽을 수 있다. SW사업대상·C-1 등급·개요 완료는 조건이 아니다.
4. **공고당 열린 요청은 하나.** 다시 누르면 같은 요청을 돌려준다(요청 ID 재전송은 같은 영수증, 다른 요청 ID는 기존 요청 참조).
5. **요청이 열린 사전규격은 첨부 취득·문서 준비 대상이다.** 기존 세 조건(SW사업대상, 추적 중인 발주계획 연결, 우선 검토 등급)에 더한다. 개요 자동 enqueue 자격은 바꾸지 않는다.
6. **미리보기는 사람이 열 때 만든다.** 요청이 있고 원문 준비(ready 묶음·구조·HWP/HWPX 원본·안전 검사)와 회사 자료 묶음 검사가 통과한 때에만 만들 수 있다. 만든 뒤 24시간 유효하다. 입력(문서 버전·회사 묶음 digest·정책·엔진·분할)이 달라지면 무효다.
7. **승인은 공고마다, 이름을 밝힌 사람이, 동결된 미리보기 한 건에 한다.** 승인 직전 추적 상태가 `계속 추적`이 아니면 409로 거부한다. 일괄 승인은 없다.
8. **요청이 닫히는 때.** 사업의 추적이 `종료` 또는 `미선택`이 되면 닫힌다(승인 전이면 실행 없이, 실행 중이면 명세의 정정·무효화 규칙을 따른다). `보류`는 요청을 닫지 않지만 승인할 수 없다. 담당자가 `이번엔 보내지 않음`을 고르면 그 입력에 대한 요청만 닫히고, 다시 `분석 요청`으로 열 수 있다.
9. **분석은 결정을 대신하지 않는다.** 요청·승인·실행·결과·결과 확인 어느 것도 추적 상태나 최종 Go/No-Go를 바꾸지 않는다.
10. **실패는 숨기지 않는다.** 추적 시작은 저장됐는데 요청 등록이 실패하면 화면에 그 사실과 `분석 요청` 재시도를 보인다. 추적 저장을 되돌리지 않는다.
11. **꺼져 있으면 지금과 같다.** 새 설정 `BIDOPS_ENGINE_REVIEW_MODE`는 `off`(기본)·`mock_reference`·`live` 셋 중 하나다. `off`이면 요청·미리보기·승인 명령은 503 `engine_disabled`, 조회는 `state: not_requested`·`reason: engine_disabled`이고 화면은 2026-11-21 재구성 그대로(추적 시작만)다. 운영은 live 경로가 인수될 때까지 `off`다. `/api/feature-flags`에 `engine_review`(같은 세 값)를 더한다.
12. **live는 따로 연다.** `mock_reference`이면 승인은 기존 `mock_reference` 엔진 실행을 만든다(개발·mock 환경 전용이며 기존 `BIDOPS_ENGINE_ANALYSIS_ENABLED`도 켜져 있어야 한다). `live`는 전송 정책·호출 상한이 모두 설정된 환경에서만 실제 Luna 전송으로 이어진다. 4단계 구현 전에는 `live`로 설정해도 미리보기·승인이 503 `engine_live_disabled`로 닫힌다. mock 결과를 운영 화면에 내지 않기 위해 운영에서 `mock_reference`를 쓰지 않는다.

## 5. 서버가 계산하는 상태

화면은 아래 값을 표시만 한다. `GET /api/pre-specs/{notice_id}/engine-review`가 `state`, `next_action`, `reason`, `request`, `preview`, `current_result`, `review_receipt`를 준다. 조회는 쓰기·enqueue·전송 0건이다.

| state | 뜻 | next_action | 결정 띠 |
|---|---|---|---|
| `not_requested` | 요청 없음 | 추적 중이면 `request`, 아니면 null | (미추적) `추적 시작하기` / (추적 중) 보조 `분석 요청` |
| `preparing` | 요청 있음, 원문 준비 중 | null | `분석 준비 중` + 남은 일 |
| `blocked` | 요청 있음, 준비 불가 | `resolve_exception` | `분석할 수 없어요` + 이유 |
| `awaiting_approval` | 요청 있음, 미리보기 가능 | `approve` | 주 행동 `전송 자료 확인` |
| `queued` / `running` | 승인됨 | null | `분석 대기` / `분석 중` |
| `result_ready` | 현재 입력의 결과가 있고 읽음 영수증 없음 | `review_result` | 결과 화면 + `계속 추적`·`보류`·`종료` |
| `acknowledged` | 읽음 영수증 있음 | null | 결과 화면, 추적 결정은 사업 추적에서 |
| `stale` | 결과가 이전 입력 기준 | 추적 중이면 `request` | "이전 입력 기준" 표시 + 보조 `분석 요청` |

`reason`은 닫힌 code다: `tracking_required`, `documents_pending`, `original_hwp_required`, `unsafe_document`, `structure_unavailable`, `company_bundle_unavailable`, `company_bundle_invalid`, `engine_disabled`, `engine_live_disabled`, `budget_exhausted`, `input_changed`. 화면 문구는 code에서 만든다.

## 6. API와 저장

추적 API(`PATCH /api/opportunities/{id}/tracking-status`, `POST /api/opportunities/pre-spec-tracking/bulk-start`)는 **바꾸지 않는다.** lifecycle 모듈은 deep_review를 부를 수 없고(모듈 방향), 기존 추적 결정 훅은 담당자·요청 ID를 받지 못하고 실패를 삼킨다. 그래서 요청 등록은 deep_review의 독립 명령으로 두고, 사전규격 화면이 추적 저장 성공 뒤 이어서 부른다.

아래 표에서 `…`는 `/api/pre-specs/{notice_id}`다. 명세의 승인·건너뛰기·읽음 계약은 본문만 그대로 쓰고 경로에서 회사 ID를 뺀다.

| 계약 | 요청·응답 | 규칙 |
|---|---|---|
| `GET /api/pre-specs/{notice_id}/engine-review` | 위 5절 | 읽기 전용 |
| `POST …/engine-review/requests` | `{request_id, origin: "tracking_start" \| "manual"}` + 담당자 헤더 → 200/201 요청 영수증과 현재 `state` | 4절 3·4번. 자격 미달은 409 + `reason` |
| `POST /api/pre-specs/engine-review/requests:batch` | `{request_id, notice_ids[1..200], origin: "tracking_start"}` → 공고별 `requested \| already_requested \| ineligible(reason)` | 한 건의 실패가 나머지를 막지 않는다. 승인은 만들지 않는다 |
| `POST …/engine-review/previews` | `{request_id}` → `preview_id, manifest_sha256, expires_at`, 문서·절/쪽, 회사 묶음 digest, 고른 위키 페이지와 글자 수, 수신 모델, 예정 호출 수와 남은 상한 | 4절 6번. 같은 입력이면 유효한 기존 미리보기를 돌려준다 |
| `POST …/engine-review/approvals` | 명세 그대로 (`preview_id, manifest_sha256, request_id`) | 명세 + 4절 7·12번 |
| `POST …/engine-review/dismissals`, `/acknowledgments` | 명세 그대로 | `dismissals`는 요청을 닫는다 |
| `GET /api/workload` | `engine_approval_pending`, `engine_result_pending` 두 건수 추가 | `off`이면 두 값은 `null`이다(0과 구별) |

저장(새 migration 하나, 모두 `bidops` schema, 불변 영수증은 trigger로 UPDATE·DELETE 차단):

| 테이블 | 핵심 열 | 제약 |
|---|---|---|
| `engine_review_request` | notice_id, opportunity_id, company_bundle_slug, origin, requested_by, requested_at, request_id, closed_at, closed_reason(`tracking_ended`·`dismissed`·`superseded`), closed_by | request_id UNIQUE. notice_id에 `closed_at IS NULL`인 행 하나 |
| `engine_review_preview` | request 참조, bundle_id, manifest(jsonb), manifest_sha256, mode(`mock_reference`·`live`), planned_calls, created_by, created_at, expires_at | 불변. (request, manifest_sha256) UNIQUE |
| `engine_review_approval` | preview 참조, approved_by, approved_at, request_id, engine_run_id(mock) / live run 참조(2단계에서 추가) | 불변. preview당 하나, request_id UNIQUE |
| `engine_review_acknowledgment` | 결과(run) 참조, acknowledged_by, acknowledged_at, request_id | 불변 |

**회사 등록 없이 도는 엔진 실행.** 기존 `engine_run`은 `company_id`·`profile_version_id`가 필수이고 입력에 BidOps 회사 바인딩을 싣는다. 이를 다음처럼 넓힌다. 기존 회사 범위 API(`/api/companies/{company_id}/notices/{notice_id}/engine-runs`)와 v1·v2 입력은 그대로 둔다.

- 입력 `bidops.engine-input.v3`: v2에서 BidOps 바인딩 필드(`company_id`·`profile_version_id`·`profile_sha256`·`graph_version_id`·`graph_sha256`)를 뺀 것. 회사는 `company_bundle`(슬러그·`bundle_sha256`)로만 식별하고 회사명은 묶음의 프로필 파일에서 읽는다. 엔진 패키지의 runner·adapter가 v3를 v2와 같은 경로로 받는다.
- `engine_run`: `company_id`·`profile_version_id`를 NULL 허용으로 바꾸고 `company_bundle_slug`·`company_bundle_sha256` 열을 더한다. CHECK: 둘 중 한 쪽(등록 회사 또는 묶음)은 반드시 있다.
- 현재성: v3 실행은 현재 묶음의 `bundle_sha256`이 실행에 고정한 값과 다르면 `stale`이다(위키를 고치면 이전 결과는 이전 입력 기준이 된다). 묶음을 읽을 수 없으면 `unknown`.
- 응답(`EngineRunView`)의 `company_id`·`profile_version_id`·`profile_sha256`·`graph_*`는 v3에서 `null`이고 `company_bundle_slug`·`company_bundle_sha256`을 더한다.

감사: `engine_review.requested`, `.preview_created`, `.approved`, `.dismissed`, `.closed`, `.acknowledged` (`AuditEvent`, 사람 actor, 안전한 metadata만). 권한은 `scripts/runtime-privileges.sql`에 app INSERT/SELECT, worker SELECT로 더한다. 계약 문서는 `docs/contracts/engine-review.md`를 새로 만든다.

## 7. 화면

- **결정 띠**(`TrackingDecisionControl`, 사전규격 상세와 목록 미리보기가 같이 쓴다): 스위치가 켜져 있으면 5절의 `state`에 따라 왼쪽 상태 문구와 주 행동 하나를 바꾼다. 주 버튼은 한 화면에 하나다. `추적 시작하기` 아래에 "추적을 시작하면 분석 요청이 함께 올라가요. 자료 전송은 확인한 뒤 따로 승인해요." 한 줄을 둔다.
- **전송 자료 확인**: Astryx `Dialog`. 보낼 문서와 범위, 회사 자료(묶음 digest·고른 위키 페이지 목록·글자 수), 수신 모델, 예정 호출 수와 오늘 남은 상한, 유효 시각. 행동은 `승인`(주), `이번엔 보내지 않음`, 닫기. 담당자 이름은 사이드바 값 하나를 쓴다(`requestActorInput`).
- **일괄 추적 시작 대화상자**: 문구에 "추적을 시작한 공고에 분석 요청을 올려요. 전송은 공고마다 따로 승인해요."를 더하고, 결과 요약에 `분석 요청 N건 · 요청 못 함 M건(이유)`를 더한다.
- **분석 결과 화면**: 지금은 mock 빌드에만 들어간다(`BIDOPS_REVIEW_MOCK`). 운영 번들에 넣고 실행 시점의 `/api/feature-flags.engine_review`(`off`가 아닐 때)로 가린다. 결과가 `mock_reference`·`unmeasured_reference`이면 그 표식을 그대로 보인다(성공·실패 색 금지).
- **오늘 할 일**: `분석 승인 대기`, `결과 확인` 두 건수. 누르면 사전규격 목록의 같은 조건 보기로 간다.
- 색·배치는 ADR-0077의 공용 틀(`DecisionBar`, `StatusMark`, `FlowSteps`)과 `bidops` 테마 토큰만 쓴다. 세 폭(1280·1440·1920)에서 결정 띠 높이 계약을 지킨다.

## 8. 구현 단계

각 단계는 앞 단계가 감독 검증을 통과한 뒤 시작한다. 작업은 운영 checkout이 아닌 별도 복제본의 브랜치에서 하고, 운영 적용·실제 전송은 그때마다 사람 확인을 받는다.

| 단계 | 내용 | 외부 전송 | 검증 |
|---|---|---|---|
| 1. 진입과 승인 흐름 | 5·6절의 상태 계산, 요청·미리보기·승인·읽음·닫힘, 첨부 취득 자격(4절 5번), workload 건수, 계약 문서. 승인은 기존 `mock_reference` 실행을 만든다. live 요청은 `engine_live_disabled` | 0 | 단위·API·PostgreSQL 변형: 4절 규칙마다 한 사례 이상, 중복 요청·동시 승인 두 건·만료·입력 변경·추적 종료 후 승인. 운영 이미지 런타임의 전체 스위트를 [기준선](../../../../../validation-runs/20261124-company-wiki-backend/README.md)과 대조 |
| 2. 화면 | 7절. mock API fixture는 1단계의 실제 응답에서 만든다 | 0 | Playwright: 상태 8가지의 결정 띠, 추적 시작 → 요청 → 승인 → 결과 → 추적 결정, 요청 실패 시 재시도, 일괄 요약, 스위치 off일 때 기존 화면과 동일. 세 폭 |
| 3. 격리 스택 종단 | mock 환경(`BIDOPS_ENV=mock`)에서 실제 HWP 원문으로 추적 시작부터 mock 결과까지 한 번 | 0 | 감독 시운전 1회 기록 |
| 4. live 실행 | 명세 "Luna 연결과 실행"·"저장과 상세 응답 경계": 단계 IPC, 엔진용 Luna 계약, 단계 lease, 호출별 감사, KST 호출 예산, C-2 양보 | 0 (호출을 세는 대역) | 명세 T2·T3와 흐름 인수 시나리오 |
| 5. 감독 시운전·비교·인수 | 명세 "비교와 사람 인수" | **건별 승인 뒤에만** | 사람 채점, 합격 기준은 명세 그대로 |

이 개정으로 [실행 계획](plan.md)의 STEP-001 가운데 "승인 후보 projection"과 처리 순서(명세 "연결과 처리 순서" 3~5번)는 구현하지 않는다. 사람이 요청한 건만 대상이라 자동 후보 정렬이 필요 없다. 승인 대기 목록의 정렬은 의견 마감 오름차순(null 마지막), 요청 시각 순이다.

## 9. 선행 조건과 한계

- **회사는 루트랩 위키 묶음 하나다.** 운영에 등록된 회사는 없고(2026-11-24 조회 `company` 0행) 등록을 요구하지 않는다. 운영 web·analysis-worker에는 `./wiki`의 `rootlab` 묶음이 이미 붙어 있다. 다른 회사를 쓰려면 묶음과 슬러그를 바꾸는 운영 변경이 필요하고, 여러 회사를 동시에 다루는 것은 범위 밖이다. RL 카드·브리핑·C-2는 이 개정과 무관하게 각자의 회사 근거를 쓴다.
- **실제 분석 경로가 없다.** 엔진 패키지에는 모델을 부르는 코드가 없고 `engine_run`은 `mock_reference`만 저장한다. 1~3단계가 끝나도 운영에서 얻는 것은 화면 흐름뿐이다.
- **호출 수와 입력 크기.** 패키지 실행은 `single`(3회 호출)로 고정돼 있고 명세의 장문 예시는 12회 계획이다. 2026-11-23 시험의 대조 프롬프트는 50만 자에 이른 변형이 있어 명세의 호출당 16,000토큰 권장과 맞지 않는다. 4단계에서 분할 방식을 정하기 전에는 시운전 대상을 8회 안에 끝나는 공고로 한정한다.
- **품질은 측정되지 않았다.** RL-05 reject와 2026-11-23 시험의 불일치 사례가 그대로다. 결과를 운영 기본 표시로 쓰는 것은 5단계의 사람 인수 뒤다.
- **담당자 이름은 인증이 아니다.** 승인 영수증의 이름은 감사 표식이다(현재 애플리케이션에 로그인·권한이 없다).

## 10. 검토하고 택하지 않은 것

| 안 | 택하지 않은 이유 |
|---|---|
| 개요 완료 뒤 조건부 자동 실행 | 건별 승인을 정책 단위 사전 승인으로 바꿔야 하고, 인수되지 않은 결과가 하루 수십 건 화면에 오른다. 품질 측정 뒤 다시 본다. 그때 첫 후보는 "이미 추적 중인 사업의 사전규격" |
| 완전 수동(분석 요청 단추만) | 추적하기로 한 건은 거의 모두 분석 대상이라 한 번 더 누르게 할 이유가 없다. 다만 이미 추적 중인 사업의 사전규격을 위해 `분석 요청` 단추는 둔다 |
| 추적 시작 단추에 전송 승인까지 합치기 | 누르는 시점에 동결할 입력이 없는 경우가 많고, 일괄 추적 시작이 일괄 전송 승인이 된다 |
| 추적 결정 훅에서 서버가 요청 생성 | 훅은 담당자·요청 ID를 받지 못하고 실패를 삼키며 모든 상태 변경에 불린다. 훅 계약을 넓히면 lifecycle과 모든 구현체를 바꿔야 한다. 화면이 두 명령을 잇는 쪽이 실패가 보이고 추적 API를 건드리지 않는다. 다른 클라이언트가 추적만 저장하면 요청이 없는 상태가 되는데, 그때는 `분석 요청` 단추로 연다 |
| 엔진 실행 전에 루트랩을 BidOps 회사로 등록 | 사용자 결정으로 회사 입력은 루트랩 위키뿐이다. 등록 회사의 프로필·그래프 바인딩은 엔진 입력에 쓰이지 않으면서 운영 선행 작업만 만든다 |
| 일괄 추적 시작에서는 요청을 만들지 않기 | "사전규격에서 추적을 시작하면 분석을 요청한다"가 단건과 일괄에서 달라진다. 요청은 전송이 아니고 승인은 건별이라 일괄로 올려도 비용이 생기지 않는다 |

## 11. 같이 고칠 문서 (구현 단계에서)

`AGENTS.md`·`CLAUDE.md`의 사전규격 런타임 문단, `web/frontend/AGENTS.md`의 "추적 결정은 추적만" 항목, `docs/business-rules.md`의 사전규격 수집과 심층 추적 절, `docs/contracts/engine-runs.md`(입력 v3·nullable 필드·새 계약 연결), `docs/operations/prespec-reference.md`(스위치와 회사 등록 선행). [최종 흐름 명세](spec.md)는 머리말에 이 개정을 연결하고 본문은 이력으로 둔다.
