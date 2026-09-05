# 사전규격은 등급에 따라 문서 준비를 자동화하고 SW사업대상=Y는 심층 검토까지 자동 시작한다

- 상태: 채택
- 일자: 2026-09-05

## 맥락

[ADR-0031](0031-prespec-overview-review-stage.md)은 사전규격 개요 검토를 1차 분류와 심층
검토 사이의 독립 단계로 두었고, [ADR-0033](0033-prespec-overview-review-runtime-contract.md)은
승인된 사설 binding이 없으면 개요를 완료하지 않는다고 정했다. 두 결정 모두 **심층 검토
진입을 사람이 연다**고 적었다. `docs/PRD.md`의 FR-DOC-07도 "심층 검토 전 사람이 승인한다"였다.

그 문장이 실제로 막고 있던 것은 두 가지가 섞여 있었다.

1. **고비용 전량 분석을 승인 없이 돌리지 않는다** — 유지해야 하는 경계다.
2. **묶음 초안 생성과 확정 클릭을 사람이 한다** — 담당자에게 판단이 없는 반복 조작이다.
   `우선 검토` 등급이 이미 붙은 사전규격에서 담당자가 하는 일은 "안전 검사를 통과한
   현재 문서를 모아 확정" 뿐이고, 그 조건은 전부 결정적으로 확인할 수 있다.

관측 규모가 3일 약 1,200건, 1주 약 2,000건이므로 2번을 사람이 계속 누르면 등급이 붙은
건이 문서 준비 앞에서 대기만 한다.

한편 `SW사업대상=Y`인 사전규격은 회사 업무 범위 안에 있다는 발주기관의 표시가 있고
([ADR-0024](0024-prespec-collect-all-flag-sw.md)), 개요 검토가 `검토 종료`가 아닌 권고로
끝났다면 심층 검토를 시작하지 않을 이유가 남지 않는다. 그런데도 심층 검토 생성을 사람이
눌러야 하면 개요 결과를 읽고 다시 돌아와 누르는 왕복이 생긴다.

## 결정

사전규격의 문서 준비를 등급으로 자동화하고, `SW사업대상=Y`인 건에 한해 심층 검토 생성까지
자동으로 잇는다. **고비용 전량 분석을 승인 없이 여는 경계는 그대로 유지한다** — 자동으로
여는 것은 생성과 실행 대기까지이고, 그 결과를 읽고 무엇을 할지는 여전히 사람이 정한다.

### 1. 자동 문서 준비는 `우선 검토` 등급만 연다

effective grade(사람 정정 등급이 있으면 그것, 없으면 판정 등급)가 `우선 검토`인 사전규격만
자동 준비 대상이다. 그 밖의 등급과 등급 없음은 `not_applicable`이며 사유는
`grade_not_priority`다. "등급 없음"을 특정 등급으로 접지 않는다.

촉발 지점은 셋이다. 회차 적재 hook, 사람 정정으로 effective grade가 바뀐 시점, 첨부 취득
worker가 한 공고의 취득을 종결한 시점이다. 셋 다 새 확장점
`EffectiveGradeChangedHook.effective_grade_changed(session, notice_ids)` 또는 기존 회차 적재
hook 위에서 돈다. **수동 업로드로 구조가 저장된 시점은 일부러 촉발하지 않는다** — 그 경우는
사람이 직접 확정한다는 것이 이 결정의 범위 밖 규칙이기 때문이다.

자동 준비는 안전 검사를 통과한 현재 문서로 묶음 초안을 만들고, 그 초안이 자기가 만든
것일 때만 확정한다. 확정 여부는 `DocumentBundle.confirmed_by_name == "auto-preparation"`으로
읽는다. 사람이 만든 초안은 자동으로 확정하지 않는다.

등급이 나중에 내려가도 이미 만든 묶음을 되돌리지 않는다. 자동 준비는 만들기만 하고
취소하지 않는다.

### 2. 자동 준비 상태와 사유는 저장하지 않고 읽을 때 계산한다

`GET /api/pre-specs`가 공고마다 `auto_preparation_status`(비 null)와
`auto_preparation_reason`(nullable 안전 코드)을 준다. 새 열을 만들지 않는다 — 상태는 등급,
취득 행, 묶음, 개요 검토, 심층 검토 존재의 파생값이라 저장하면 곧바로 어긋난다.

상태 값은 여덟이다. `not_applicable`, `waiting_attachments`, `bundle_draft`, `bundle_ready`,
`overview_running`, `deep_review_started`, `deep_review_ready_for_click`, `blocked`.
`not_applicable`은 "자동 준비 대상이 아니다"이며 "알 수 없다"가 아니다. 자동 준비 제공자가
없는 배포에서도 같은 값이다.

사유 코드는 `grade_not_priority`, `awaiting_fetch`, `no_ready_document`,
`bundle_has_blocking_issues`, `bundle_unchanged`, `human_bundle_draft`, `processing_failed`와
문서 묶음 service가 내는 안전 코드다. 명세가 어휘를 정하지 않은 자리라 이 결정이 정한다.

이 자리는 **N+1을 금지한다.** 공고 수와 무관하게 상수 회 조회여야 한다.

### 3. `SW사업대상=Y`이고 자동 확정된 묶음이 있으면 심층 검토를 자동 시작한다

다음이 모두 성립할 때만 심층 검토를 시스템 actor로 생성한다.

- 사전규격이고 `qualification_flags_json.sw_business_status = 'Y'`
- 자동 준비가 확정한(`confirmed_by_name == "auto-preparation"`) `ready` 묶음이 있다
- 그 묶음에 대한 개요 검토가 `completed`다
- 개요 권고가 `검토 종료`가 아니다
- 개요가 본 묶음과 지금 묶음이 같다
- 같은 불변 입력의 심층 검토가 아직 없다

하나라도 어긋나면 각각의 사유 코드로 남긴다. `not_sw_business`,
`bundle_not_auto_ready`, `overview_not_completed`, `overview_recommendation_closed`,
`overview_bundle_mismatch`, `deep_review_exists`, `service_unavailable`, `processing_failed`.
평가 순서는 위 목록 순서이며 첫 일치가 이긴다. 사람이 확정한 `ready` 묶음은 자동 시작
대상이 아니고 사람 클릭으로 남는다.

생성은 사람 경로와 **같은 함수**를 쓴다. `DeepReviewService.create_review`가 keyword-only
`actor_kind`("human"|"system")를 받고, 시스템 경로는 감사 action
`deep_review.auto_create`를 남긴다. `safe_metadata` 모양은 `deep_review.create`와 같다.
request ID는 `uuid5(notice, bundle, profile, policy)`로 결정적이라 같은 조건의 재촉발이
새 review를 만들지 않는다.

자동 시작은 추적 상태를 바꾸지 않는다. 사업기회는 `미선택` 그대로다.

### 4. 자동 경로도 감사에 남는다

- `document_bundle.create`·`document_bundle.confirm`은 `actor_kind=system`,
  `claimed_name=auto-preparation`, `safe_metadata`의 `trigger=priority_grade`,
  `trigger_run_id`, `trigger_review_id`를 실을 수 있다.
- 자동 확정만 남기는 별도 action `document_bundle.auto_confirm`이 있다.
- 자동 심층 시작은 `deep_review.auto_create`다.

`claimed_name`은 인증이 아니라 감사 표식이라는 [ADR-0009](0009-name-attribution-intranet.md)의
경계를 그대로 따른다. `auto-preparation`은 사람 이름이 아니라 **자동 경로의 표식**이다.

### 5. 자동 준비의 실패는 촉발한 작업을 무효로 만들지 않는다

자동 준비와 자동 시작은 파생 작업이다. 어떤 실패도 회차 적재나 리뷰 저장으로 예외를
올리지 않고 안전 코드로만 남는다. 재시도는 다음 촉발 시점에만 한다.

## FR-DOC-07·ADR-0031·ADR-0033의 "사람 승인" 문장 대체

세 문서의 "심층 검토 전 사람이 승인한다"는 이 결정으로 다음과 같이 좁힌다.

| 이전 문장 | 이 결정 이후 |
|---|---|
| 심층 검토 시작은 사람이 승인한다 | `우선 검토` 등급의 자동 준비와 `SW사업대상=Y`의 자동 시작은 시스템이 연다. 그 밖의 모든 진입은 사람 클릭이다 |
| 승인 전에는 전체 첨부를 고비용 분석에 투입하지 않는다 | **유지한다.** 자동 시작도 등급·SW 표시·개요 완료·권고를 모두 통과한 건에만 열리고, 결과 해석과 추적·최종 결정은 사람이 한다 |
| 사람이 묶음을 확정한다 | 자동 준비가 만든 초안만 자동 확정한다. 사람이 만든 초안은 사람이 확정한다 |

이 결정은 적합성 등급, 참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go 중 어느
것도 자동으로 만들지 않는다. 자동으로 여는 것은 **분석의 시작**뿐이다.

## 대안과 기각 이유

- **모든 등급에 자동 준비를 연다** — 관측 규모에서 대부분이 `우선 검토`가 아니고, 첨부
  취득 자격도 없는 건까지 묶음을 만들면 저장소와 감사가 의미 없이 늘어난다.
- **자동 준비 상태를 열로 저장한다** — 등급·취득·묶음·개요·심층의 파생값이라 어느 하나가
  바뀔 때마다 갱신 경로를 다섯 곳에 만들어야 하고, 놓치면 화면이 틀린 상태를 확신 있게
  보여 준다. 읽을 때 상수 회 조회로 계산하는 편이 정확하다.
- **자동 시작을 `SW사업대상` 없이 등급만으로 연다** — 등급은 회사 적합성이고 `SW사업대상`은
  발주기관의 사업 성격 표시다. 둘을 하나로 접으면 [ADR-0024](0024-prespec-collect-all-flag-sw.md)가
  분리해 둔 축이 다시 섞인다.
- **자동 시작에 별도 생성 함수를 둔다** — 사람 경로와 다른 함수를 쓰면 입력 동결·품질
  표식·감사 metadata가 두 벌이 된다. `actor_kind`만 다르게 받는 편이 계보가 하나로 남는다.

## 결과

- 등급이 붙은 사전규격이 첨부 취득 → 묶음 확정 → 개요 검토까지 사람 조작 없이 간다.
- `SW사업대상=Y`는 심층 검토 실행 대기까지 간다. 화면은 `심층 검토 자동 시작됨`으로 보인다.
- 자동으로 열리지 않은 건은 화면이 **왜 열리지 않았는지**를 사유 코드로 말한다.
  `심층 검토 클릭 대기`에 사유가 붙으면 그것이 사람이 눌러야 하는 이유다.
- 자동 경로가 만든 산출물은 감사에서 사람 경로와 구분된다. 구분되면서도 **같은 경로로
  실행된다** — 생성 감사를 찾는 자리는 두 action을 모두 보고, 그 표는
  `app/core/constants.py`의 `DEEP_REVIEW_CREATION_ACTIONS` 한 벌이다.

## 남은 공백

- 자동 준비 hook과 첨부 취득 worker가 동시에 돌면 같은 문서 집합으로 묶음 revision이 둘
  생길 수 있다. worker끼리는 concurrency 1로 배제된다. 같은 findings에 기록했다.
