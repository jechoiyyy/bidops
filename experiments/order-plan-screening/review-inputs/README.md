# 발주계획 1차 분류 검토 입력

이 폴더는 발주계획 선별 실험에서 사용할 프롬프트와 회사 역량 요약을 사람이 한곳에서
검토하기 위한 정본 위치다. 실제 본문 파일은 사내 자료이므로 Git에서 제외하고,
`manifest.json`에는 상태와 SHA-256만 기록한다.

## 현재 실행 기준

- 회사 역량: `company/company-capabilities-v1-approved.json`
- 프롬프트: `prompts/order-plan-batch-relevance-v3-approved.txt`
- 상태 정본: `manifest.json`

`manifest.json`에서 `status`가 `approved`이고 `execution_allowed`가 `true`인 두 파일만
새 실행에 사용할 수 있다. 현재 회사 역량 v2와 negative 프롬프트 v4는 검토용 초안이며
실행에 사용할 수 없다.

본문을 확인한 뒤 다음 명령으로 active 파일의 상태와 SHA-256을 검증한다. 출력에는 본문이
포함되지 않는다.

```bash
python3 experiments/order-plan-screening/scripts/validate_review_inputs.py
```

## 변경·승인 규칙

1. 승인본을 제자리에서 수정하지 않는다. 새 version 파일을 만들어 검토한다.
2. 초안은 `status: draft`, `execution_allowed: false`로 등록한다.
3. 사람이 승인한 뒤에만 새 파일의 SHA-256과 상태를 `manifest.json`에 반영하고
   `active_company_capabilities` 또는 `active_prompt`를 전환한다.
4. 실행 전 파일 SHA-256이 manifest와 일치하는지 확인한다. 실행 artifact에는 실제 사용한
   profile/prompt/model/input digest를 별도로 고정한다.
5. 과거 실행 재현에 필요한 `.dryforge` 파일과 기존 `config/` 파일은 삭제하거나 덮어쓰지
   않는다. 새 실행만 이 폴더를 기본 입력으로 사용한다.

프롬프트와 회사 역량 본문은 일반 로그·보고서·API 응답에 넣지 않는다. 모델에는 승인된
회사 역량 최소 projection과 발주계획 제목만 전달한다.
