# 사전규격 회사 핏 v2(사업 범위 카드) 판정 표시와 엔진 분석 추천 — spec

- 기능 ID: `PS-01-company-fit-card`
- 근거: [intent.md](./intent.md)
- 작성일: 2026-11-27

## 큰 틀 문서와의 관계

- 인용하는 절
  - `docs/business-rules.md` "회사 핏 판정 (2026-09-08)": 등급·참여 준비·추적·Go/No-Go 불변, 새 입력은 새 attempt, 같은 입력 중복 호출 금지, 실패 입력 자동 재시도 금지, 참조 실행 경계
  - `docs/business-rules.md` 자동 심층 시작 조건(사유 코드 순서)
  - `docs/contracts/deep-review.md` "사전규격 회사 핏 계약": attempt 불변·전이·권한
  - ADR-0060 결정 7: 감사 DB 행 스위치 패턴
  - ADR-0078 결정 1: 분석 요청은 사람의 추적 시작·클릭에서만 나온다(이 파일은 main checkout에 미커밋 상태로만 있다. clone에는 없다)
  - CLAUDE.md "강제 게이트"의 참조 실행 표식
- 이 문서에서 새로 확정하는 항목: 카드 lineage 입력·현재성·대상 조건, 회사 핏 모드 스위치, 응답 v2, 목록의 회사 핏 그룹·정렬·필터, 프로필 lineage와의 공존 규칙
- 큰 틀 문서 수정이 필요한 항목. 구현 단계 STEP-008에서 고치고 `docs/ADR.md`에 ADR-0080을 올린다.
  - `business-rules.md` "회사 핏 판정"에 "카드 lineage(2026-11-27)" 문단을 더한다. 대상은 SW사업대상 전체(등급 무관)이고, 추천만 하며, 심층 자동 시작에 쓰지 않는다.
  - `contracts/deep-review.md` 회사 핏 계약을 v2 응답·v2 입력·모드 REST로 갱신한다.
  - `contracts/lifecycle-rest.md` 사전규격 목록에 `company_fit` 필드, `sort=fit`, `company_fit` 필터를 더한다.
  - `operations/prespec-reference.md`에 카드 마운트·sha·모드 켜기 절차를 적는다(각 단계 직전 승인).
  - `docs/work/constitution/roadmap.md`에 PS 절을 더한다.

## 입력·출력 계약

### C1. 사업 범위 카드 파일

- YAML 파일 하나이며 git 밖에 둔다. 측정 정본은 main checkout의 `docs/validation-runs/20261127-company-fit-probe/business-scope-card.v1.2.yaml`(미커밋)이다.
- 필수 구조. 하나라도 어기면 `card_unavailable`이다.
  - `schema_version`: `bidops.business-scope-card.`로 시작하는 문자열, 64자 이하. 이 값을 그대로 **card_version**으로 쓴다.
  - `scopes`: 비어 있지 않은 목록. 각 항목은 `id`(`scope:`로 시작, 유일)와 `name`·`summary`(비어 있지 않은 문자열)를 갖는다. `includes`·`boundary`·`keywords`·`examples`는 선택이다.
  - `policies`: 비어 있지 않은 목록. 각 항목은 `id`(`policy:`로 시작, 유일)와 `kind`·`summary`(비어 있지 않은 문자열)를 갖는다. `items`·`rules`는 선택이다.
  - 선택 필드는 YAML 값(문자열·목록·dict)을 타입 검사 없이 그대로 투영한다. 대신 투영 전체가 JSON 직렬화되고 `sanitize_for_prompt`를 통과해야 한다.
  - 그 밖의 키(`company`·`basis`·`questions`·`level` 등)는 읽지만 모델 입력에 넣지 않는다.
- **card_sha256**은 파일 bytes의 SHA-256(소문자 hex 64자)이다. 설정값 `BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256`과 다르면 `card_sha256_mismatch`이고, 읽은 내용을 쓰지 않는다.
- 회사 근거 투영 `company_facts`는 `fit_probe.py` `card_facts`와 같다. 순서는 scopes 다음 policies이고, 각각 파일 순서를 따른다.
  - scope는 `{"ref": id, "fact_key": name, "status": "confirmed", "value": {k: scope[k] for k in ("summary","includes","boundary","keywords","examples") if scope.get(k)}}`이다.
  - policy는 `{"ref": id, "fact_key": kind, "status": "confirmed", "value": {k: policy[k] for k in ("summary","items","rules") if policy.get(k)}}`이다.
  - `sanitize_for_prompt(facts) != facts`이면 `card_unavailable`이다.
- 화면 표시용 이름 `company_fact_labels`(`{ref: label}`)도 만든다. 모델에는 보내지 않는다.
  - scope는 `name`을 쓴다.
  - policy는 카드에 이름 필드가 없고 `kind`가 겹치므로(`exclude`가 둘) `company_fit_card.POLICY_LABELS`를 쓴다: `policy:no-bid` → "수행하지 않는 사업", `policy:caution` → "확인이 필요한 사업", `policy:onsite` → "상주 조건", `policy:mixed-scope` → "섞인 사업 판단". 표에 없는 id는 id 문자열 그대로 쓴다.

### C2. 카드 lineage 입력 `bidops.prespec-company-fit-input.v2`

동결 입력(`input_jsonb`)의 키는 아래로 고정한다. 모두 필수다.

| 키 | 값 |
|---|---|
| `schema_version` | `"bidops.prespec-company-fit-input.v2"` |
| `notice_id` | int |
| `overview_kind` | `"overview_run"` |
| `overview_id` | 개요 run UUID 문자열 |
| `document_version_id` | UUID 문자열 |
| `overview_sha256` | `OverviewInput.sha256` |
| `notice_facts` | `[{"ref":"notice:title","text":<공고명>,"pages":[],"block_key":null}, *OverviewInput.facts]` |
| `input_limitations` | `OverviewInput.limitations` |
| `card_version` | C1 |
| `card_sha256` | C1 |
| `company_facts` | C1 투영 |
| `company_fact_labels` | C1 표시 이름 |
| `policy_digest` | `digest(card_fit_policy(model))`. 열 `policy_digest`와 같다 |
| `model_name` | `BIDOPS_PRESPEC_COMPANY_FIT_MODEL` |
| `model_revision` | overview endpoint 선언 revision(`configured_binding`과 같다) |
| `prompt_version` | `"prespec-company-fit-v3.1"` |
| `quality_status` | `OverviewInput.quality_status` |
| `fit_policy` | `card_fit_policy(model)`: `fit_policy(model)`에서 `prompt_version`을 위 값으로, `stages`를 `[{"stage":"company_fit","instruction": INSTRUCTION_CARD_V31}]`로 바꾼 것 |

- `INSTRUCTION_CARD_V31`은 `fit_probe.py`의 `INSTRUCTION`(v3.1) 문자열을 한 글자도 바꾸지 않고 옮긴다. `SYSTEM_PROMPT`·`CONTRACT`·`APPROVED_GENERATION`은 v1과 같다. 결과 스키마는 `bidops.prespec-company-fit-result.v1` 그대로다.
- **모델에 보내는 입력**은 동결 입력에서 정확히 다음 키만 뽑은 것이다: `schema_version, notice_id, notice_facts, input_limitations, company_facts, model_name, prompt_version`. 측정 실행기와 같은 키·모양이다. 식별 문자열 두 개만 다르다.
  - `schema_version`: `…input.v2-probe` → `…input.v2`
  - `prompt_version`: `prespec-company-fit-v3.1-card-probe` → `prespec-company-fit-v3.1`
  - 프롬프트 직렬화(`build_prompt`)에 이 두 문자열이 들어가므로 프롬프트 bytes는 측정과 다르다. 제품에 `probe` 이름을 남기지 않으려고 이 차이를 받아들이고, 영향은 T14로 잰다.
- 동결 입력 전체의 UTF-8 JSON이 60000 bytes를 넘으면 그 공고는 건너뛴다(`company_fit_input_too_large`, 행을 만들지 않음). 다음 공고를 막지 않는다.
- `input_sha256 = digest(input_jsonb)`, `policy_digest = digest(card_fit_policy(model))`이다.

### C3. 결과 검증

- 기존 `validate_result`를 그대로 쓴다. 카드 근거의 status가 모두 `confirmed`이고 value가 null이 아니므로 별도 검증기를 만들지 않는다.
- 한 번 호출하고, 검증에 실패하면 같은 입력으로 한 번 다시 부른다(`_invoke_validated`). 그래도 실패하면 `needs_human_review`다. 자동 보정은 하지 않는다.

### C4. 회사 핏 모드 실효 상태

`company_fit_mode_state(session, settings)`는 `{mode, effective, reason_code, card_version, card_sha256, prompt_version, set_by, set_at}`을 돌려준다. 아래 순서로 평가하며 **첫 미충족이 `reason_code`**다. 모두 통과하면 `effective=true`, `reason_code=null`이다.

1. `company_fit_disabled`: `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=false`
2. `company_fit_reference_only`: `BIDOPS_REFERENCE_WORKFLOW_MODE=false`
3. `company_fit_model_unavailable`: `configured_binding`이 실패했거나, 그 revision이 64자 소문자 hex가 아니다(카드 행도 기존 `ck_prespec_company_fit_hashes`의 `company_id IS NULL` 갈래를 따르므로 revision 선언이 필요하다)
4. `card_unavailable`: 카드 경로가 비었거나, 읽을 수 없거나, C1 구조 위반
5. `card_sha256_mismatch`: 설정 sha가 64자 소문자 hex가 아니거나 파일 sha와 다름
6. `switch_off`: 모드 행이 없거나 최신 행이 `off`
7. `switch_bound_to_other_card`: 최신 행 `card_sha256` ≠ 현재 카드 sha
8. `switch_bound_to_other_prompt`: 최신 행 `prompt_version` ≠ `prespec-company-fit-v3.1`

- `mode`는 최신 행의 값(`off|suggest`)이고, 행이 없으면 `off`다.
- `card_version`·`card_sha256`은 조건 1~3의 결과와 상관없이 카드를 따로 읽어 채운다. 조건 4·5가 통과할 때만 값이 있고, 아니면 null이다.
- `prompt_version`은 언제나 `prespec-company-fit-v3.1`이다.
- `set_by`·`set_at`은 최신 행의 값이고, 행이 없으면 null이다.

### C5. 회사 핏 응답 `bidops.prespec-company-fit.v2`

`GET /api/pre-specs/{notice_id}/company-fit`. 지금 코드와 같은 오류 규칙을 따른다(404, 422, `_page_error`의 503 `processing_failed`). `contracts/deep-review.md`의 "500"은 기존 문서 오기이므로 STEP-008에서 503으로 고친다. 모델 호출이나 실행 생성은 없다.

- 최상위: `schema_version`, `notice_id`, `attempts[]`, `automation_enabled`, `mode`(C4 객체 전체), `engine_suggested: bool`, `auto_deep_review_reason`, `deep_review_id`.
- `automation_enabled`는 v1 정의(`BIDOPS_PRESPEC_COMPANY_FIT_ENABLED and BIDOPS_REFERENCE_WORKFLOW_MODE`)를 바꾸지 않는다. 카드 모드가 꺼져 있으면 프로필 lineage가 돌기 때문에, 이 정의가 "어느 lineage든 자동 판정이 돈다"와 같다. 카드 모드 상태는 `mode`로만 읽는다.
- 프런트엔드는 `GET /mode`를 부르지 않고 이 응답의 `mode`만 읽는다.
- `attempts`: 그 공고의 가장 최근 행(`created_at desc, id desc` 첫 행, 회사 lineage 제외)과 같은 lineage의 행만 최신순으로 최대 20개 넣는다. 행이 없으면 빈 목록이다. 그래서 모드를 끈 뒤 프로필 lineage가 새로 판정하면 화면은 프로필 판정으로 넘어간다. 목록 그룹(C6)은 언제나 카드 lineage만 본다.
- 각 attempt는 v1 `CompanyFitView`를 바탕으로 다음이 다르다.
  - `lineage: "profile"|"card"` 추가
  - `card_version`·`card_sha256` 추가(프로필 lineage는 null)
  - `profile_version_id`·`profile_sha256`은 nullable(카드 lineage는 null)
  - 나머지 필드와 재검증 규칙은 v1과 같다
- `engine_suggested`가 true인 조건은 다음이 모두 성립할 때뿐이다.
  - `attempts[0].lineage == "card"`
  - `status == "completed"`이고 재검증을 통과했다
  - `is_current == true`
  - `result.decision == "matched"`
  - C4 `effective == true`이고 `mode == "suggest"`

  `mock_reference`도 true일 수 있다. 화면이 표식으로 구분한다.

### C6. 목록 회사 핏 요약과 그룹

`PreSpecListItem.company_fit`은 다음 객체이거나 null이다. null은 프로젝션 확장이 등록되지 않았다는 뜻이다.

| 필드 | 타입 |
|---|---|
| `group` | `"matched" \| "unknown" \| "pending" \| "mismatch"` |
| `decision` | `"matched" \| "mismatch" \| "unknown" \| null` |
| `status` | `"queued" \| "running" \| "completed" \| "failed" \| "needs_human_review" \| null` |
| `is_current` | bool |
| `engine_suggested` | bool(C5와 같은 규칙) |

- `group`은 그 공고의 최신 카드 lineage attempt로 정한다.
  - attempt가 `completed`, 재검증 통과, 현재이면 `group = decision`이다.
  - 그 밖(attempt 없음·`queued`·`running`·`failed`·`needs_human_review`·stale·재검증 실패)은 `pending`이다.
  - 프로필 lineage 행은 그룹에 쓰지 않는다.
- `decision`은 최신 카드 attempt가 completed이고 재검증을 통과했을 때의 값이다(현재가 아니어도 채운다). 아니면 null이다.
- 카드 attempt가 없으면 `{group:"pending", decision:null, status:null, is_current:false, engine_suggested:false}`다.
- 요약은 기존 `prespec_status_fields`(`lifecycle/extensions.py`의 사전규격 프로젝션 Protocol)가 돌려주는 필드 dict에 키 `company_fit`으로 넣는다. 새 메서드는 만들지 않는다. 라우터는 `status_fields[notice_id].get("company_fit")`를 읽고, 없으면 null이다.

### C7. 목록 정렬·필터 (`GET /api/pre-specs`)

- `PreSpecSort`에 `"fit"`을 더한다. 값 집합은 `published|deadline|observed|fit`이다.
  - 정렬 키 순서는 그룹 순위(matched 0, unknown 1, pending 2, mismatch 3) → 기존 `deadline` 정렬식(bucket asc, 마감 전 asc, 경과 desc, null last) → `Notice.id asc`다.
- 새 질의 인자 `company_fit: "matched"|"unknown"|"pending"|"mismatch"|None`. 다른 값은 422 `company_fit is invalid`다.
  - 필터는 `auto_preparation_status` 필터(`pre_specs.py:636-640`)와 같은 자리에 둔다. 프로젝션 결과(`status_fields`)를 읽은 뒤 `filtered_ids`를 좁히므로 `items`·`total`·집계에 모두 적용된다.
- 그룹 값도 같은 `status_fields[id]["company_fit"]["group"]`에서 읽는다. lifecycle 라우터는 deep_review를 import하지 않는다.
- 확장이 없거나 키가 없으면 그 공고는 `pending`이다.
- `sort=fit`의 SQL 정렬은 그룹 순위를 `(notice_id, rank)` VALUES 목록으로 join해 쓴다. 목록에 없는 id는 rank 2다.

### C8. 모드 REST·CLI

- `GET /api/pre-specs/company-fit/mode`는 C4 객체를 돌려준다. 이 경로는 `/{notice_id}` 경로보다 먼저 등록한다.
- `POST /api/pre-specs/company-fit/mode`의 본문은 `{"mode": "off"|"suggest"|"auto_request", "reason": str|null(1~200, 공백만 불가), "request_id": UUID}`다.
  - 행위자는 공통 규칙(`docs/contracts.md` actor 절)대로 `X-BidOps-Actor-Name` 헤더에서 받아 `set_by`(128자 이하)로 기록한다. 헤더가 없거나 잘못되면 공통 actor 오류다.
  - 오류 본문은 공통 형식 `{"error":{"code","message","details"},"request_id"}`다. 아래 코드는 `error.code`, 추가 값은 `error.details`(`prerequisites_unmet`이면 `{"reason_code": …}`)에 넣는다.
  - `auto_request`는 422 `mode_not_available`이다.
  - `suggest`는 C4의 1~5가 모두 통과해야 하고, 아니면 409 `{"code":"prerequisites_unmet","reason_code":…}`다.
  - `off`는 언제나 허용한다.
  - 새 행의 `prompt_version`·`card_sha256`·`card_version`은 현재 값이다. `off` 행에서 카드가 없으면 `card_sha256`·`card_version`은 null이다.
  - 같은 `request_id`이고 `mode`·`set_by`·`reason`이 모두 같으면 200, 하나라도 다르면 409 `request_id_conflict`, 새 행이면 201이다.
  - 200·201 응답 본문은 모두 그 시점의 C4 객체다(행 자체가 아니다).
  - 감사 이벤트는 `AuditEvent(actor_kind="human", claimed_name=set_by, action="prespec_company_fit.mode", aggregate_type="prespec_company_fit_mode", aggregate_id=str(row.id), safe_metadata={mode, prompt_version, card_sha256, reason, request_id})`다. 새 행일 때만 남기고, 200 재전송에는 남기지 않는다.
- CLI: `python -m app.deep_review.cli set-company-fit-mode --mode off|suggest --actor <name> [--reason <text>] [--request-id <uuid>]`. `--actor`가 `set_by`다.
  - REST와 같은 서비스 함수를 부른다.
  - `--request-id`를 빼면 실행마다 `uuid4()`를 새로 만든다(멱등 없음).
  - **web 컨테이너**(app DB 역할)에서 실행한다. 모드 테이블 INSERT는 app 역할만 갖는다.
  - 종료 코드는 0 성공, 2 입력·전제 거부(사유를 stderr 한 줄로), 1 내부 오류다.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED` | bool | false | | 기존. 카드 lineage의 env cap이기도 하다 |
| `BIDOPS_PRESPEC_COMPANY_FIT_MODEL` | str | null | 공백 없는 이름 | 기존. 측정값 `local-agent-main` |
| `BIDOPS_REFERENCE_WORKFLOW_MODE` | bool | false | | 기존. 카드 lineage도 이 값이 true여야 한다 |
| `BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH` | str | `""` | 컨테이너 안 절대 경로 | 신규. prod compose는 host 경로 `BIDOPS_PRESPEC_COMPANY_FIT_CARD_HOST_PATH`를 web·analysis-worker의 `/run/company-fit/business-scope-card.yaml`에 ro로 붙인다. host 경로가 없으면 `/dev/null`을 붙여 `card_unavailable`가 된다 |
| `BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256` | str | `""` | 64자 소문자 hex | 신규 |
| 동결 입력 상한 | int | 60000 bytes | | 기존 값과 같다. `tunable` |
| 카드 enqueue 순서 | | 마감 임박순(기존 deadline 정렬식) → notice id | | `tunable` |
| 한 poll당 enqueue | int | 1 | | 기존 프로필 lineage와 같다. `tunable` |

## 상태 값과 실패 처리

- attempt status는 기존 enum `queued|running|completed|failed|needs_human_review`, quality_status는 `unmeasured_reference|mock_reference`다. 새 값은 없다.
- error_code는 기존 `lease_expired`·`inputs_changed`·`company_fit_execution_failed`를 쓰고, 검증 실패는 기존 retry 코드를 따른다.
- 카드 lineage enqueue는 C4 `effective=true`일 때만 한다. 대상 조건은 모두 만족해야 한다.
  - `Notice.source_type="pre_spec"`
  - `sw_business_notice_ids`에 든다(C-1 등급은 보지 않는다)
  - `auto_processing_notice_ids(now)`에 든다
  - `overview_inputs`에 있다(현재 개요 run `completed` + `automation_completed_result` 통과 + 현재·safe·사람 검토 아님 문서)
  - 같은 `input_sha256`의 카드 lineage 행이 없다. 실패·만료 행도 같은 입력이면 다시 만들지 않는다(자동 재시도 금지)
- claim은 카드 lineage 행이 C4 `effective`일 때만 한다. 꺼져 있으면 queued 행은 그대로 둔다.
  - claim 직전 현재성(C9)을 다시 보고, 어긋나면 `failed`/`inputs_changed`다.
- **카드 경로는 프로필 경로의 예외와 분리한다.**
  - 카드 enqueue는 자기 `try`에서 돈다.
  - 프로필 `_enqueue_one`이 실패해 `legacy_enabled=False`가 되면 claim에서 **프로필 lineage 행만**(`company_id IS NULL AND card_sha256 IS NULL`) 뺀다. 카드 행은 C4 effective면 claim한다. 운영처럼 활성 프로필·정책이 없는 환경이 이 경우다.
  - C4가 effective인 동안에는 `_enqueue_one`을 부르지 않고, 이미 queued인 프로필 lineage 행도 claim하지 않는다. 그 행은 queued로 남고, 모드를 끄면 기존 규칙대로 처리된다.
  - 카드 enqueue 순서의 마감 정렬식은 lifecycle 라우터의 private `_deadline_sort_expression`을 lifecycle 공개 함수 `pre_spec_deadline_sort_expression(now)`로 옮겨서 쓴다. `pre_spec_deadline_passed_expression`과 같은 자리이고, 라우터도 이 함수를 쓴다. deep_review → lifecycle 방향이라 의존 규칙에 맞다.
  - 카드 attempt 감사 metadata는 기존 프로필 키에 `lineage:"card"`·`card_version`·`card_sha256`을 더한다.
  - `run_once` 맨 앞의 `prespec_company_fit_enabled`·`reference_workflow_mode` 검사는 그대로 둔다(C4 1·2와 같다).
  - `current_flags`는 `company_id`·`card_sha256`으로 세 갈래로 나눠, 카드 행은 C9로 판정한다.
- 카드 lineage 완료 뒤 `maybe_auto_start_deep_review`를 부르지 않는다.
- **공존 규칙.**
  - C4가 effective인 동안 프로필 lineage의 자동 enqueue(`_enqueue_one`)를 하지 않는다. 기존 프로필 lineage 행은 남고 읽을 수 있다.
  - 프로필 lineage 질의(`latest_attempts`·`gate_reasons`·기존 입력 집합·claim 분기·`company_fit_view`의 프로필 쪽)는 `card_sha256 IS NULL`인 행만 본다.
  - C4가 effective인 동안 `gate_reasons`는 우선 검토 여부와 상관없이 모든 공고에 새 사유 `company_fit_suggest_only`를 돌려준다. 순서상 `company_fit_disabled`·`company_fit_reference_only` 다음이다. 그래서 회사 핏을 통한 심층 자동 시작은 일어나지 않는다.

### C9. 카드 lineage 현재성

다음이 모두 같을 때만 현재다.

- `overview_inputs`의 현재 개요 id·sha256
- 현재 카드 sha(C4 조건 4·5 통과 시)와 `card_sha256` 열
- `prompt_version == "prespec-company-fit-v3.1"`
- `model_name`·`model_revision` == `configured_binding`
- `policy_digest == digest(card_fit_policy(model))`
- `digest(input_jsonb) == input_sha256`

카드를 읽을 수 없으면 모든 카드 행은 현재가 아니다.

## 저장

migration `0044_company_fit_card_lineage`를 둔다(이전 head `0043_company_wiki_ingest`).

1. `prespec_company_fit_attempt`
   - 열 추가: `card_version VARCHAR(64) NULL`, `card_sha256 VARCHAR(64) NULL`
   - `profile_version_id`를 NULL 허용으로 바꾼다. `deep_policy_version_id`는 0036에서 이미 NULL 허용이다.
   - 기존 `ck_prespec_company_fit_policy_scope`를 지우고, 아래 식으로 같은 이름의 check를 다시 만든다.
     ```sql
     (company_id IS NULL AND card_sha256 IS NULL
        AND profile_version_id IS NOT NULL AND deep_policy_version_id IS NOT NULL
        AND company_fit_policy_version_id IS NULL AND card_version IS NULL)
     OR (company_id IS NULL AND card_sha256 IS NOT NULL
        AND card_version IS NOT NULL AND length(card_sha256) = 64
        AND profile_version_id IS NULL AND deep_policy_version_id IS NULL
        AND company_fit_policy_version_id IS NULL AND graph_version_id IS NULL)
     OR (company_id IS NOT NULL AND card_sha256 IS NULL AND card_version IS NULL
        AND deep_policy_version_id IS NULL AND company_fit_policy_version_id IS NOT NULL)
     ```
     hex 여부는 trigger에서 `card_sha256 ~ '^[0-9a-f]{64}$'`로 본다. SQLite dual check는 기존 `dual()` 방식을 따른다.
   - insert guard trigger의 `company_id IS NULL` 분기를 `card_sha256 IS NULL`(기존 v1 검사 그대로)과 `card_sha256 IS NOT NULL`(새 카드 분기)로 나눈다. 카드 분기에서 하나라도 어기면 `RAISE EXCEPTION 'company fit card input scope rejected'`다.
     - `input_jsonb->>'schema_version' = 'bidops.prespec-company-fit-input.v2'`
     - 입력의 `notice_id`, `document_version_id`, `overview_id`(= 열 `overview_run_id`), `card_version`, `card_sha256`, `model_name`, `model_revision`, `quality_status`, `policy_digest`가 같은 이름의 열과 같다. attempt 테이블에는 `prompt_version` 열이 없으므로 입력의 `prompt_version`은 상수 `'prespec-company-fit-v3.1'`과 비교한다.
     - `card_sha256`이 hex 64자다
   - 불변·전이·삭제 금지 규칙은 그대로다
   - downgrade는 카드 lineage 행이 하나라도 있으면 거부한다(기존 종결 이력 거부와 같은 방식)
2. 새 테이블 `prespec_company_fit_mode`(append-only)
   - 열: `id UUID PK`, `mode VARCHAR(16) NOT NULL CHECK (mode IN ('off','suggest'))`, `prompt_version VARCHAR(64) NOT NULL`, `card_version VARCHAR(64) NULL`, `card_sha256 VARCHAR(64) NULL`(64자 hex), `reason VARCHAR(200) NULL`, `set_by VARCHAR(128) NOT NULL`, `set_at TIMESTAMPTZ NOT NULL`, `request_id UUID NOT NULL UNIQUE`
   - check(SQLite는 기존 `dual()`): `mode='suggest'`이면 card 두 열이 NOT NULL이다. `card_sha256`은 NULL이거나 64자 소문자 hex다(C-2 일일 스위치의 `length = 64 AND NOT GLOB '*[^0-9a-f]*'` 식과 같다). `length(trim(set_by)) > 0`, `length(trim(prompt_version)) > 0`, `reason IS NULL OR length(trim(reason)) > 0`.
   - `set_at`은 서비스의 앱 clock 값을 넣는다(테스트에서 주입 가능).
   - 인덱스 `(set_at, id)`. 최신 행은 `set_at desc, id desc` 첫 행이다
   - UPDATE·DELETE 거부 trigger
   - downgrade는 카드 attempt 행이 없을 때만 허용하고, 모드 테이블은 행과 함께 지운다(모드 행은 설정 기록이며 판정 이력이 아니다. 감사 이벤트는 남는다)
3. `scripts/runtime-privileges.sql`: `prespec_company_fit_mode`는 app 역할 SELECT·INSERT, worker 역할 SELECT다. attempt 테이블은 테이블 단위 INSERT 권한이 이미 있으므로 새 열 때문에 바꿀 것이 없다. 종결 전 UPDATE 열 목록(`GRANT UPDATE (…)`)에는 card 열을 넣지 않는다(동결 값). migration에 GRANT를 쓰지 않는다.
4. ORM `deep_review/models.py`를 같은 정의로 고치고, SQLite 테스트용 dual check를 따른다.

## 인터페이스(CLI·UI·API)

- API: C5·C7·C8.
- CLI: C8 `set-company-fit-mode`. `deep_review/cli/__init__.py`의 하위 명령 목록과 docstring에 더한다.
- 화면
  - `CompanyFitSection`(compact·전체)
    - 카드 lineage 근거의 `company_refs`를 attempt의 `company_fact_labels[ref]`(C1)로 보여 준다. value JSON은 보이지 않는다. 그래서 C5 각 attempt에 `company_fact_labels: dict[str,str]|null`(프로필 lineage는 null)을 더한다.
    - 품질 표식은 공용 `qualityStatus.ts` 라벨을 그대로 쓴다(`unmeasured_reference` → `참조 실행 · 품질 미측정`, `mock_reference` → `mock 참조`).
    - `engine_suggested`이면 "엔진 분석 추천: 회사 사업 범위와 맞는 사업입니다. 분석 요청은 담당자가 정합니다."를 보여 준다. 버튼이나 링크는 두지 않는다.
    - 기술 정보(`CompanyFitExecutionSection`)에 모드(`꺼짐`/`추천`)·실효 여부·사유 코드·카드 버전·프롬프트 버전을 읽기 전용으로 보여 준다.
    - 상세 배치 규칙(`relevanceVisible`)은 바꾸지 않는다.
  - 목록 `PreSpecListRow`에 "회사 핏" 열을 더한다. 라벨은 matched 부합, unknown 판단 보류, pending 판정 전, mismatch 불일치이고, 상태 표시는 Token/StatusDot 규칙을 따른다. 1280 폭에서 기존 열이 잘리지 않아야 한다.
  - 목록 미리보기 `PreSpecListDetailPane`에 판정 라벨 한 줄과, `engine_suggested`이면 "엔진 분석 추천"을 보여 준다.
  - 고급 필터에 회사 핏(전체·부합·판단 보류·판정 전·불일치)을 더한다. URL 질의 `company_fit`이다.
  - `SORT_OPTIONS`에 `{value:"fit", label:"회사 핏순"}`을 더하고 `WORKSPACES.actionable.defaultSort="fit"`으로 바꾼다. 다른 탭 기본값은 그대로다.
  - `PreSpecsPage`의 기본 보기 판정(`isDefaultView`, `:345-348`)은 두 가지를 고친다. `sort === "deadline"` 대신 workspace 기본 정렬과 비교하고, `company_fit` 필터가 없다는 조건을 더한다.
  - 목록 복원 질의 목록 `preSpecSelectionReview.ts` `LIST_PARAMS`에 `company_fit`을 더한다. `deadline_scope`가 빠진 것은 기존 공백이며 이번에 고치지 않는다.
  - 선택 검토 순서(`listSelection.ts`)
    - `PreSpecSelectionSortMetadata`에 선택 키 `company_fit_group`(C6 group 값)을 더한다. `isPreSpecSelectionSortMetadata`는 `last_observed_at`처럼 이 키가 있어도 없어도 받는다.
    - `comparePreSpecMetadata`·`sortPreSpecMetadata`는 `fit`을 받아 그룹 순위(키 없음 = pending) → `compareDeadlineTimestamp` → id 순으로 비교한다.
    - `PreSpecsPage`가 메타데이터를 만드는 세 곳(전체 선택 `:363`, 로드 반영 `:376`, 행 체크 toggle `:1023` 근처)에 모두 항목의 `company_fit.group`을 넣는다. 예전에 저장된 선택은 그대로 유효하다.
  - `preSpecAutoPreparation.ts` 사유 문구에 `company_fit_suggest_only` → "회사 핏은 추천만 하며 심층 검토를 자동으로 시작하지 않습니다"를 더한다.
- mock: `tests/api-mock.ts`·`scripts/mock-api.ts`에 Referer 질의 `?fit=matched|unknown|mismatch|pending`을 더한다.
  - 상세 응답은 v2 카드 lineage attempt이고 `mode.effective=true`, `mode.mode="suggest"`다. `matched`·`unknown`·`mismatch`는 completed attempt, `pending`은 `status="running"` attempt 하나(결과 없음)다.
  - 목록 fixture 항목들은 네 그룹을 모두 포함하고 `sort=fit`·`company_fit` 질의에 맞게 응답한다.
  - 기존 기본 fixture(`attempts: []`, `automation_enabled:false`)는 `?fit` 없을 때 유지하되 v2 모양으로 바꾼다.
- 외부 호출 보호 장치는 셋이다.
  - 모델 호출은 `company_fit_runner.run_once`의 카드 분기에서만 일어나고, 직전에 C4 `effective`와 C9 현재성을 확인한다.
  - `ModelClient.for_purpose("overview", …)`의 허용 host·revision 검사(기존)를 거친다.
  - `verify_identity()`의 model·revision이 동결 입력과 같아야 한다(기존 `model_binding_changed`).

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 새 그룹 PS로 등록 | RL 그룹 제약이 Luna 전용인데 이 기능은 LiteLLM·Qwen을 쓴다(사용자 결정 2026-11-27) | RL-12 + 제약 예외 |
| 범위는 판정 표시 + matched 추천(suggest), 엔진 요청은 사람 | 사용자 결정. ADR-0078 결정 1·4를 유지한다 | 추천 + 엔진 요청 연결(ADR 개정·RL-11 선행 필요) |
| 대상은 개요 통과 SW사업대상 전체, C-1 등급 무관 | 사용자 결정. 측정 조건과 같다 | 우선 검토 한정 |
| `검토할 항목` 기본 정렬은 matched → unknown → pending → mismatch, 그룹 안은 마감 임박순 | 사용자가 순서 권고를 받아 계획 승인. matched가 비싼 엔진 신호다. mismatch는 측정에서 gold unknown을 mismatch로 낸 오류(4·37번)가 있어 숨기지 않고 아래로만 내린다. 판정 전은 mismatch 아래에 묻히지 않게 한다 | 마감 임박순 유지 + 필터만, mismatch 숨김 |
| 카드는 git 밖에 두고 버전·sha로 고정 | 카드는 회사 자료이고 원격 저장소는 공개다(측정 기록). 커밋 여부는 사용자 몫이다 | 이미지에 포함 |
| 카드 근거 status는 모두 `confirmed`, 검증기 재사용 | 측정 입력과 프롬프트 문구("모두 회사가 확인한 내용이다")를 그대로 재현한다. 카드 머리글이 사용자 확인을 카드 문안에 대한 것으로 정의한다 | 카드 level을 status로 매핑(측정과 입력이 달라짐) |
| 모델 입력 키를 측정 실행기와 같게 둔다 | 측정 결과를 제품에서 재현하는 것이 목적이다 | 동결 입력 전체 전송 |
| 피드백 제외 | 사용자 결정 2026-11-27 | 사람 판정 3값, 맞음/아님 |
| 모드 변경은 REST·CLI만, 화면은 읽기 | 사용자 결정. 운영 변경은 직전 확인 대상이다 | 관리 화면 토글 |
| 모드는 감사 DB 행(append-only, prompt·card sha 바인딩) | 측정 README 개선 방안 5와 ADR-0060 결정 7 패턴 | env 값 하나 |
| 카드 모드 실효 중 프로필 lineage 자동 enqueue 정지, 응답은 카드 행 우선 | 같은 공고에 입력이 다른 두 판정이 생기면 화면이 모순된다. 사용자가 카드 기준을 택했다 | 두 lineage 동시 실행 |
| 카드 lineage는 심층 자동 시작에 쓰지 않고 `company_fit_suggest_only` 사유를 낸다 | suggest는 추천만 한다(사용자 결정). 사유가 없으면 화면이 "회사 핏 대기"로 잘못 말한다 | 기존 gate에 카드 matched 연결 |
| 모델 입력의 `schema_version`·`prompt_version` 문자열은 제품 이름을 쓴다 | 제품에 측정용 `probe` 이름을 남기지 않는다. 키·값 모양은 같고, 영향은 T14로 잰다 | 측정 문자열 그대로 사용 |
| `automation_enabled`는 v1 정의를 유지한다 | 카드 모드가 꺼지면 프로필 lineage가 돌기 때문에 v1 정의가 그대로 맞다. 바꾸면 프로필 lineage 표시·폴링이 달라진다(intent 범위 밖) | C4 effective로 대체 |
| 정책 표시 이름은 코드 상수 `POLICY_LABELS`로 동결 입력에 넣는다 | 카드 v1.2 policy에 이름 필드가 없고 `kind`가 겹친다. 측정 카드는 고치지 않는다 | `kind` 표시, 카드에 name 추가 |
| 응답 schema를 v2로 올린다 | `profile_version_id` 등이 nullable로 바뀌는 타입 변경이다. 프런트엔드가 schema_version을 엄격 비교한다 | v1에 필드 추가 |
| 판정 2회 일치·policy 인용 결정적 검사 | N/A — 측정 README 개선 방안 3·4는 이번 범위 밖(intent 범위 밖) | |
| 카드 `questions`·`level`의 화면 표시 | N/A — 측정 입력에 없었고 이번 화면 요구에도 없다 | |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | 합성 카드 로드. 정상 / sha 불일치 / scope id 중복 / `policies` 빈 목록 / policy `summary` 빈 문자열 / 경로 빈 값 | 정상이면 C1 투영이 `fit_probe.card_facts` 규칙과 같은 값(키 순서 포함)이다. 기대값은 테스트 안의 literal로 둔다(release 이미지에는 `docs/`가 없다). 나머지는 `card_sha256_mismatch`·`card_unavailable`이다 | 단위 |
| T2 | 동결 입력 생성 | 키 집합이 C2와 정확히 같다. 모델 입력 키가 7개다. `company_fact_labels`는 scope `name`과 `POLICY_LABELS`를 따른다. 입력 `policy_digest`가 열 값과 같다. `fit_policy.stages[0].instruction`의 UTF-8 sha256이 측정 `fit_probe.INSTRUCTION`의 sha256(구현 시 한 번 계산해 테스트 상수로 고정)과 같다. 60000 bytes 초과는 건너뛰고 다음 공고를 enqueue한다 | 단위 |
| T3 | 모드 실효 순서 | C4의 1~8 조건을 하나씩 깨면 해당 `reason_code`가 나온다. 앞 조건이 우선한다. revision이 비어 있으면 3이다. 조건 1~3에서 막혀도 카드가 정상이면 `card_sha256`이 채워진다. 모두 통과하면 effective다 | 단위 |
| T4 | 모드 POST | `suggest`는 201과 행 하나·감사 이벤트 하나다. 같은 request_id 재전송은 200이고 행은 그대로 하나다. 다른 본문은 409다. `auto_request`는 422다. 전제 미충족 `suggest`는 409 `prerequisites_unmet`이다. `off`는 카드가 없어도 201이다. CLI 종료 코드는 0/2다 | 통합 |
| T5 | enqueue 대상 | SW=Y·개요 passed·마감 전 공고는 행이 생긴다. 우선 검토가 아닌 공고도 생긴다. 다음은 생기지 않는다: 마감 경과 미추적, SW=N, 개요 failed·needs_human_review, 같은 입력의 failed 행이 이미 있음. 마감 경과여도 추적 중이면 생긴다. 모드가 off면 아무것도 생기지 않는다 | 통합 |
| T6 | 실행(가짜 모델) | 활성 프로필·정책이 없어 프로필 `_enqueue_one`이 실패하는 환경에서도 카드 행이 enqueue·claim된다. matched 응답은 `completed`다. 첫 응답이 검증에 실패하면 1회 재호출하고, 재호출도 실패하면 `needs_human_review`다. `maybe_auto_start_deep_review`는 불리지 않는다(심층 검토 행 0). 모델 입력 키는 C2 7개다 | 통합 |
| T7 | 현재성 | 개요 새 run, 카드 sha 변경, 모델 revision 변경 각각에서 `is_current=false`다. claim 시 어긋나면 `failed`/`inputs_changed`다 | 통합 |
| T8 | 공존 | 카드 모드 실효 중에는 프로필 lineage 행이 enqueue되지 않는다. 우선 검토 공고의 `gate_reasons`는 `company_fit_suggest_only`다. 모드 off에서는 기존 프로필 lineage 테스트가 그대로 통과한다 | 통합 |
| T9 | 회사 핏 응답 v2 | 카드 행이 있으면 카드 행만 최신순이다. `automation_enabled`는 v1 정의와 같다(카드 모드 off·env on이면 true). `engine_suggested`는 C5 조건에서만 true이고, mode off·stale·mismatch에서는 false다. 프로필 lineage만 있으면 `lineage="profile"`이고 card 필드는 null이다 | 통합 |
| T10 | 목록 `sort=fit`·필터 | 네 그룹과 마감 전·경과·null 마감을 섞은 공고로 순서가 C7과 같은지 본다. `limit` 경계를 넘는 두 페이지도 이어진다. `company_fit=pending`은 attempt 없음·running·failed·stale을 포함하고 `total`과 일치한다. 잘못된 값은 422다. 확장이 없으면 모두 pending이다 | 통합 |
| T11 | migration·제약(PostgreSQL 17.11) | upgrade 뒤 세 lineage 행이 각각 들어간다. lineage 규칙을 어긴 행, v2 입력 schema와 카드 열이 다른 행, 모드 행 UPDATE·DELETE는 거부된다. 카드 행이 있으면 downgrade를 거부한다. 권한 테스트(`test_runtime_database_privileges`)가 통과한다 | 통합(PostgreSQL) |
| T12 | 상세 화면(mock) | `?fit=matched`에서 판정·이유·카드 범위·정책 이름(`company_fact_labels`)·`참조 실행 · 품질 미측정`·"엔진 분석 추천"이 보인다. unknown·mismatch에서는 추천이 없다. pending에서는 판정·이유 없이 진행 상태만 보인다. 기술 정보에 모드 읽기 표시가 있다. 1280·1440·1920 | 화면(Playwright) |
| T13 | 목록 화면(mock) | `검토할 항목` 기본 정렬이 `회사 핏순`이고, 회사 핏 열 라벨 네 가지가 보인다. 필터를 바꾸면 URL에 `company_fit`이 붙고, 상세에 갔다 돌아와도 유지된다. 회사 핏순에서 선택 검토 순서가 목록 순서와 같다. 예전 형식의 저장 선택도 그대로 읽힌다. `마감 임박순`으로 바꿀 수 있다. 1280에서 열이 잘리지 않는다 | 화면(Playwright) |
| T14 | 측정 재현(U6) | 승인 뒤 11-26 격리 스택에서 제품 실행기(`PreSpecCompanyFitRunner(clock=…)`로 측정 시점 2026-11-27 10:30 KST를 주입해 대상 조건 평가)로 22건을 판정한다. 그 시점에도 대상에서 빠지는 건은 건수와 id를 적는다. 그 뒤 `score_gold.py`로 채점한다. 결과와 실행 조건을 validation-runs에 기록하고 품질 합격으로 적지 않는다 | 외부 의존(로컬 모델, 사람 승인) |

## 컨벤션 반영 항목

- 새 그룹 `PS`(사전규격 운영)와 ID 형식 `PS-NN-slug`. roadmap에 절을 더한다.
- 새 사유 코드 `company_fit_suggest_only`. `business-rules.md` 자동 시작 사유 목록과 `contracts/prespec-overview.md` 사유 순서 문단에 올린다.

## MVP(포트폴리오 적용) 범위 — 2026-11-27 사용자 결정

포트폴리오 스택(`bidops-portfolio`, 고정 시계 2026-11-27 13:00 KST)에 먼저 적용하는 MVP다. 위 계약과 다른 점만 적는다. 나머지는 위 계약 그대로 구현한다. 운영 적용 때 빠진 부분(모드 테이블·REST·CLI)을 원래 범위대로 붙인다.

1. **모드 테이블·`/mode` REST·`set-company-fit-mode` CLI는 만들지 않는다.** 대신 env `BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE=off|suggest`(기본 `off`, 다른 값은 설정 오류)를 쓴다.
   - C4 조건 6은 "env 값이 `off`"이고 사유 코드는 `switch_off`다. 조건 7·8은 없다.
   - C4 객체의 키는 `{mode, effective, reason_code, card_version, card_sha256, prompt_version}`이다(`set_by`·`set_at` 없음).
   - migration 0044는 attempt 테이블 변경만 한다. `prespec_company_fit_mode` 테이블은 없다.
2. **판정 주체 표식.** 동결 입력에 모델로 보내지 않는 키 `judged_by: "model" | "claude_reference"`를 더한다.
   - 실행기가 만든 행은 `"model"`이다.
   - 가져오기 도구로 넣은 행은 `"claude_reference"`이고, `model_name="claude-reference-judgment"`, `model_revision`은 판정 묶음 파일의 sha256이다.
   - C5 attempt에 `judged_by`를 노출한다.
   - 화면은 `claude_reference`이면 품질 표식 옆에 "Claude 판정 · 참조"를 보여 모델 결과와 구분한다.
   - insert guard 카드 분기는 `judged_by`가 두 값 중 하나인지만 본다.
3. **현재성(C9)에서 모델 binding 비교를 뺀다.**
   - 표시용 현재성은 개요 id·sha, 카드 sha, `prompt_version`, `policy_digest`(입력에 동결된 모델 이름 기준으로 다시 계산), 입력 digest만 본다.
   - 모델 binding(`configured_binding`·`verify_identity`)은 실행기가 claim·호출할 때 계속 확인한다.
4. **`engine_suggested` 조건**은 다음이 모두 성립할 때다.
   - C5의 attempt 조건(카드 lineage, completed, 재검증 통과, 현재, matched)
   - env `BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE=suggest`

   실행기 실효(`mode.effective`)는 요구하지 않는다. 포트폴리오는 실행기를 켜지 않고 가져온 결과만 보여 주기 때문이다.
5. **가져오기 도구** `python -m app.deep_review.cli import-company-fit-judgments --file <json> --actor <name> [--dry-run]`
   - 입력 파일: `{"judged_by":"claude_reference","card_sha256":…,"rows":[{"notice_id":int,"result":<bidops.prespec-company-fit-result.v1>}]}`
   - 공고마다 다음을 한다.
     1. 현재 DB 기준으로 `frozen_card_input`을 만든다(`judged_by`·`model_name`·`model_revision`은 위 값).
     2. 결과를 `validate_result`로 검증한다.
     3. 같은 `input_sha256` 행이 없으면 `queued`로 넣고, 같은 transaction에서 `running` → `completed`로 전이한다(trigger 전이 규칙을 따른다).
     4. 감사 이벤트를 남긴다.
   - 개요 입력이 없거나 검증에 실패한 공고는 건너뛰고 사유를 출력한다.
   - 이미 있는 입력이면 건너뛴다(멱등).
   - 카드 파일 sha가 설정값이나 파일의 `card_sha256`과 다르면 전체를 거부한다.
   - worker DB 역할로 실행한다.
   - 종료 코드는 0(전부 처리 또는 건너뜀), 2(입력·카드 거부), 1(내부 오류)이다.
6. 포트폴리오 반영(이미지 교체, migration, 가져오기, gateway 캐시 비우기)은 **실행 직전 사용자 확인**을 받는다. 다른 세션이 관리하는 포트폴리오 빌드(시계 고정 패치)와 겹치지 않게 조율한다.
