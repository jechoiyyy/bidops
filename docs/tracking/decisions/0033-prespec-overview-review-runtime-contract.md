# 사전규격 개요 검토의 절단 snapshot과 모델 attempt를 분리한다

- 상태: 채택
- 일자: 2026-08-31

## 맥락

[ADR-0031](0031-prespec-overview-review-stage.md)은 사전규격 개요 검토를 자동으로
수행하되 심층 검토와 사람의 최종 판단을 대신하지 않는 독립 단계로 정했다.
[ADR-0032](0032-prespec-overview-cutting-rule.md)은 모델 입력의 시작·종료 경계를 문서
구조로 확정하지 못하면 `unknown`으로 사람에게 보내도록 정했다.

구현에는 두 종류의 불확실성이 남아 있다. 하나는 문서 구조로 앞부분을 확정할 수
있는지이고, 다른 하나는 실제 운영에 승인된 사설 모델 binding이 있는지이다. 이를
하나의 실행 상태로 합치면 절단 실패를 모델 장애로 오해하거나, mock 결과를 운영 완료로
표시하거나, provider 부재를 hosted 모델 fallback으로 우회할 위험이 있다.

## 결정

**1. 결정적 절단 snapshot과 모델 attempt를 분리한다.**

clean `DocumentStructure`가 준비되면 현재 문서 버전에 대해 절단 snapshot을 자동으로
만든다. snapshot은 공고·문서 버전·구조·입력 hash를 고정하고 `cut_status`, `strategy`,
`start_locator`, `end_locator`, `source_sha256`를 보존한다. 같은 snapshot에 대한 모델
실행은 append-only attempt로 남기며 기존 attempt를 덮어쓰지 않는다.

절단 상태는 `pending | ready | unknown | failed`다. 시작·종료 경계가 모호하면
`cut_status=unknown`, 검토 상태 `needs_human_review`로 닫고 모델을 호출하지 않는다.
고정 block 수나 전체 문서를 fallback 입력으로 만들지 않는다.

**2. 검토 상태와 완료 조건을 명시한다.**

검토 상태는 다음 값만 사용한다.

`awaiting_document | awaiting_structure | preparing | awaiting_model | queued | running |
needs_human_review | completed | failed | cancelled`

승인된 사설 vLLM binding이 없으면 절단 snapshot까지만 만들고
`status=awaiting_model`로 둔다. 이때 결과와 `completed_at`은 `null`이며 모델 호출을
시도하지 않는다. `completed`는 승인된 binding으로 실행한 응답이 strict schema 검증,
원문 evidence locator 검증, source hash 검증을 모두 통과했을 때만 허용한다. 실패 결과를
자동 보정하거나 성공 상태로 바꾸지 않는다.

**3. 운영 모델 경계를 fail closed로 유지한다.**

제안요청서 앞부분은 승인된 로컬 또는 사설 OpenAI-compatible vLLM endpoint에만 보낼 수
있다. hosted OpenAI·Codex를 포함한 외부 provider로 자동 fallback하지 않는다. 실행은
명시적인 provider/model binding과 목적별 allowlist에 고정한다.

결정적 mock은 소비 계층과 상태 전이 검증에만 쓰는 `reference_only` 결과이며
`deployable=false`다. mock attempt는 운영 완료로 집계하지 않고 실제 모델 완료처럼
표시하지 않는다.

**4. 산출물의 의미를 개요 판단으로 제한한다.**

결과 범주는 `추진 검토 | 조건부 추진 검토 | 보류 | 검토 종료`다. `조건부 추진 검토`에는
조건과 확인 기한이 반드시 있어야 한다. 모든 결과는 절단 snapshot 안의 근거 위치와
연결하고, 입력 한계와 확인하지 못한 항목은 `unknown` 또는 `null`로 보존한다.

이 결과는 사업 내용이 회사가 수행할 만한지에 대한 개요 판단일 뿐이다. 적합성 등급,
참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go를 채우거나 대신하지 않는다.

## 대안

**절단과 모델 실행을 하나의 row·상태로 관리 — 소거했다.**

문서 구조 문제와 provider 문제의 원인이 섞이고 재실행 때 입력 계보나 과거 응답을
덮어쓸 가능성이 커진다.

**binding 부재 때 mock으로 자동 완료 — 소거했다.**

화면 개발은 빨라지지만 운영 결과처럼 보이는 거짓 완료를 만든다. mock은 명시적인
참조 모드에만 남긴다.

**절단 실패 때 전체 문서 또는 hosted 모델로 우회 — 소거했다.**

ADR-0032의 입력 범위와 보안 경계를 모두 깨며, 실패 원인을 숨긴다.

## 결과

- 구조 준비와 모델 준비 상태를 서로 독립적으로 확인하고 재시도할 수 있다.
- 승인된 사설 binding이 없는 환경에서도 절단과 화면 구현은 진행하되 거짓 결과를 만들지 않는다.
- 모든 완료 결과는 고정 입력, 승인 binding, 검증된 근거에 되짚을 수 있다.
- T-23의 REST·DB wire shape는 이 상태·계보·fail-closed 계약을 구현해야 한다.
