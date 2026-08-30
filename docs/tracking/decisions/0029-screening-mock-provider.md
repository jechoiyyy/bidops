# 1차 분류는 결정적 mock 제공자로 소비 계층을 먼저 구현한다

- 상태: 채택
- 일자: 2026-08-29

## 맥락

[ADR-0021](0021-filter-experiment-before-implementation.md)과 `CLAUDE.md`의 강제 게이트는
발주계획 선별 방식 확정을 비교 실험(키워드·ColBERT·Qwen·GPT Luna)과 사람 정답 보고서 승인
뒤로 미룬다. 아직 그 승인이 나지 않았다.

그런데 판정을 **소비하는 쪽**은 그 결정과 무관하다. 검토 화면, 심층 검토 추적 선택,
사업기회 상태 전이는 모두 판정 결과가 있어야 만들 수 있는데, 그 결과의 모양은
`app/screening/contracts.py`가 모델과 독립적으로 이미 고정했다.

- `PERSPECTIVE_NAMES` 5개 관점이 정확히 한 번씩
- `GRADES`, `READINESS`, `FOCUS_AXES`, `EXCLUSION_CATEGORIES`, `EVIDENCE_STATUSES`
- `validate_perspective` / `validate_counterargument` / `validate_judgment`
- `docs/business-rules.md`의 교차 규칙 — `제외` 등급의 readiness 제약,
  blocking 미확인 항목이 남은 채로 readiness가 `확인 완료`가 될 수 없다는 규칙

어떤 모델을 쓰든 이 검증을 통과해야 한다. 따라서 계약 모양의 결정적 데이터만 있으면
소비 계층을 지금 구현하고 검증할 수 있다.

심층 검토 쪽에는 이미 같은 선례가 있다. `app/services/mock_analysis_client.py`
(`MOCK_MODEL_NAME = "bidops-deterministic-mock-v1"`)와
`analysis_provider="mock"` + `reference_workflow_mode` 게이트다.

## 결정

**1. `Transport` 계층에 결정적 mock을 둔다.**

`app/screening/mock_transport.py`의 `MockScreeningTransport`가
`app/screening/ollama.py:45`의 `Transport` Protocol을 구현한다.
`OllamaClient(settings=..., transport=MockScreeningTransport())`로 주입하며
`OllamaClient`와 `ScreeningOrchestrator`의 기존 로직은 수정하지 않았다.

**2. 단계 판별은 `payload["format"]`의 required 키 집합으로 한다.**

프롬프트 텍스트 추측을 쓰지 않는다. 종합 단계는 프롬프트에 박힌 canonical JSON에서
`notice_id`를 엄격히 추출하고, 추출에 실패하면 `MockScreeningTransportError`를 던진다.
조용한 기본값으로 넘어가지 않는다.

**3. mock 산출물은 스스로를 mock이라고 밝힌다.**

`matched_performances`의 `status`는 `unknown`으로 고정하고 `name`·`source`·
`match_reason`·`summary`·`next_action` 문자열 자체에 `모의`, `실제 아님`이 드러난다.
화면에 그대로 렌더링돼도 사람이 실적 근거로 오인할 수 없다.
`CLAUDE.md`의 "확인되지 않은 회사 역량·자격·실적을 추정하지 않는다"를 mock도 지킨다.

**4. telemetry에서 실제 모델과 구별된다.**

`/api/tags` 응답과 생성 envelope의 digest가 mock 전용 상수 `MOCK_MODEL_DIGEST`다.
저장된 `ScreeningAttempt.model_digest`만 보고 mock 실행을 판별할 수 있다.
`model_name`은 `OllamaClient.__init__`이 허용 모델만 받으므로 구별에 쓸 수 없다.

**5. 명시적으로 켜야만 쓰인다.**

`BIDOPS_SCREENING_PROVIDER`(`ollama` 기본값 / `mock`)를 추가하고,
`mock`인데 `reference_workflow_mode`가 아니면 `Settings` 검증이 거부한다.
`analysis_provider`와 같은 형태다. 설정을 건드리지 않은 기존 배포의 동작은 바뀌지 않는다.

**6. 실패 경로를 만들 수 있다.**

`failure_mode`로 `schema_violation`, `evidence_missing`, `malformed_json`,
`truncated_output`, `notice_id_mismatch`를 낸다. 계약 위반이 자동 보정되지 않고
재시도 상한 뒤 `OllamaCallError`로 전파되는지를 시험하기 위한 것이다.

## 대안

**클라이언트 계층 mock (`OllamaClient` 자체를 대체) — 소거했다.**

`generate()`가 `notice_id`를 인자로 받으므로 프롬프트에서 추출할 필요가 없어 더 간단하다.
그러나 그 경로는 재시도 정책, `validate_*` 3종, `CallMetadata` telemetry,
`add_two_axis_metadata`를 **모두 건너뛴다.** 그러면 소비 계층이 받는 판정이 실제
검증을 통과한 것이라는 보장이 사라진다. mock을 쓰는 목적이 소비 계층을 신뢰할 수 있게
검증하는 것이므로, 검증 경로를 건너뛰는 이음매는 목적과 어긋난다.

**기존 `FakeOllamaTransport`(`tests/fakes/ollama.py`) 확장 — 소거했다.**

응답을 하나씩 대본으로 넣는 테스트 fake다. 단위 테스트에는 적합하지만 40건 회차를
태울 수 없다. 확장하면 두 용도가 한 클래스에 섞여 기존 테스트의 엄격함이 흐려진다.
별도 모듈로 두고 `FakeOllamaTransport`는 그대로 두었다.

**mock을 테스트 전용으로만 두기 — 소거했다.**

`app/` 밖에 두면 compose override로 전체 스택을 모델 없이 기동할 수 없다.
운영 코드에 두되 설정 게이트와 digest 표식으로 오용을 막는 쪽을 택했다.

## 결과

- 1차 분류 판정을 소비하는 화면·추적 선택·상태 전이를 모델 결정 전에 구현하고 검증할 수 있다.
- 실험이 끝나 모델이 정해지면 바꾸는 것은 transport 주입 한 곳이다. 소비 계층은 그대로다.
- mock은 키워드·ColBERT·Qwen·Luna 중 어느 것도 아니므로 `docs/business-rules.md:28`이
  금지한 "실험 전 운영 정본 취급" 대상이 될 수 없다. 이 ADR은 선별 방식을 정하지 않는다.
- 결합: 종합 단계의 notice 추출은 정책 template이 `notice_json={notice_json}` 형태로
  쓰는 것에 의존한다. `app/screening/seed_policy.json`의 일곱 template이 모두 그렇고
  테스트가 `load_policy_file()`로 실제 파일을 쓴다. template을 바꾸면 mock은 조용히
  틀린 값을 쓰지 않고 `MockScreeningTransportError`로 즉시 실패한다.
- 위험: mock 판정이 화면에 남은 채로 사람이 실제 판단으로 오인할 수 있다.
  digest 표식과 자기표시 문자열이 그 방어선이다. **화면 구현 시 mock 실행 여부를
  사람이 볼 수 있게 표시할지를 별도로 정해야 한다.**
