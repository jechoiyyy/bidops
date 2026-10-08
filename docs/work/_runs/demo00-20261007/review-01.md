# 독립 리뷰 1차 — 2026-10-08

- reviewer: 별도 agent `review`, gpt-5.6-sol / high, read-only.
- 입력: 기준 `d12df664b27f28efab1825281567d9bf1b6f9981`부터 기능 worktree 전체 변경(신규 policy/runbook 포함).
- 범위: STEP-002 구현 및 STEP-003 runbook 준비. 운영 결과·배치 통합 완료 리뷰가 아니다.
- 판정: fail. 제품 코드 차단 결함 없음, runbook 차단 1건.

## 지적과 처리

1. runbook은 host에서 계산한 SHA를 그대로 image/import 기준으로 쓴다. 수정 파일도 자기 일관 해시로 통과하므로 승인된 digest `51b1723051e92299ef53e650f9faf851c8e6777fe75c59b814639d38be887877`와 먼저 대조해야 한다. **수용**, 고정 기대값과 host/image/import 비교를 보완한다.
2. T2 v4 service에서 과거 invalid related_claim/considered_claim 응답 형태가 미검증이다. 전자는 projection+warning, 후자는 1회 교정+동일 검증을 확인해야 한다. **수용**, 테스트 추가.
3. T6 `ModelInvocationError(schema_invalid, raw_response=...)`의 교정 성공/재실패 및 두 원응답 보존이 미검증이다. **수용**, 테스트 추가.
4. T7 v1/v2/v3 각각 7200 deadline 전달이 미검증이다. **수용**, 기존 v4 deadline 검사를 확장한다.
5. 첫 68 passed 이후 metadata 호환성 수정의 최종 증거가 필요하다. **수용**, 수정된 Luna 파일 검사는 32 passed, 0 skipped, 소스 전후 hash 일치로 완료했다. 추가 테스트는 차이만 다시 실행한다.

코드 검토로 v1~v3 불변, 필수 검증 유지, 1·2단계만 최대 1회 교정, 암호화 원응답 보존, 호출 metadata 및 report warning을 확인했다. 미검증 운영 단계는 그대로 대기한다. 리뷰 권고로 제품 범위를 늘리지 않는다.
