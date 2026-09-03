# 판정의 모델 계보는 revision → execution 경로를 정본으로 한다

- 상태: 채택
- 일자: 2026-08-31

## 맥락

[ADR-0030](0030-opportunity-tracking-state.md)의 부수 결정이 "mock 판정임을 화면에
표시한다"고 정했으나 표시할 값에 도달하는 경로를 찾지 못해 T-19가 대기 상태로 남아
있었다. `lifecycle-workstream.md`의 T-19는 `Judgment`에 모델 계보가 없고
`ScreeningAttempt.model_digest`가 판정과 FK로 이어져 있지 않다고 적었다.

재확인 결과 경로는 이미 존재한다.

```
Judgment ──> JudgmentRevision.recording_execution_id ──FK──> ScreeningExecution.execution_id
                                                                  ├─ model_name
                                                                  ├─ model_digest
                                                                  ├─ prompt_version / policy_version
                                                                  └─ company_profile_version / digest
```

`ck_judgment_revision_source_lineage`가 `source_kind`에 따라 계보를 강제한다.
`runtime`과 `carry_over`는 `recording_execution_id`가 반드시 있어야 하고
`legacy_import`는 반드시 `NULL`이어야 한다. 계보가 있으면 확실히 있고 없으면 확실히
없으므로 추정으로 메울 여지가 없다.

`ScreeningAttempt.notice_id`는 `String(255)` 외부 공고번호이고 `notice.id` 대리키와
join되지 않는다. 계보의 정본 후보는 attempt가 아니라 execution이다.

## 결정

`JudgmentRevision → ScreeningExecution` 경로를 모델 계보의 유일한 정본으로 한다.
판정 조회 API가 최신 revision을 따라가 `model_name`, `model_digest`, `prompt_version`을
projection으로 노출한다. `legacy_import` 판정은 `unknown`으로 남긴다.

스키마는 바꾸지 않는다. migration 없이 API와 화면만 추가한다.

## 대안

`Judgment`에 계보 컬럼을 직접 추가하면 조회가 한 번에 끝나지만, 같은 사실이 두 곳에
존재해 어느 쪽이 정본인지 다시 문제가 된다. 동기화가 어긋나면 화면이 틀린 모델을
보여 주므로 기각했다.

계보 노출을 계속 미루는 안은 [ADR-0029](0029-screening-mock-provider.md)의 결정적 mock이
운영 판정과 화면에서 구분되지 않는 상태를 유지하므로 기각했다.

## 결과

T-19의 대기 사유가 해소된다. `legacy_import` 판정에는 계보가 없으므로 화면은 그 사실을
`unknown`으로 표시하고 "mock이 아니다"로 해석하지 않는다.
