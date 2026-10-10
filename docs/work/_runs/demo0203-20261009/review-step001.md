# STEP-001 중간 독립 검토

- 검토자: `knowledge_review`, 지정 `gpt-5.6-sol` / high, 구현·검사 실행에 관여하지 않음.
- 대상: 초기 STEP-001 동결본, `step001-source-hashes.json`, 리더 `step001-tests.log` 60 passed.
- 판정: FAIL, 차단 3건. 완료/품질 통과로 기록하지 않는다.

1. 원본 회사 slug/name 검증이 lifecycle 등록보다 느슨하여 dry-run 성공 뒤 같은 입력의 등록이 실패할 수 있다. 동일한 identity 규칙을 적용하고 경계 입력을 검사한다.
2. enum에 배열/객체를 주면 일부 set membership에서 TypeError로 이탈한다. 잘못된 JSON을 안전한 도메인 검증 오류로 반환해야 한다.
3. frozen 결과의 중첩 값이 변경 가능하여 snapshot에 원본 hash와 다른 사실이 결합될 수 있다. 깊은 불변성 또는 원본 재검증·대조로 막고 변조 입력을 검사한다.

리더가 세 지적을 수용하여 원 구현자에게 수정 위임했다. 초기 통과 기록은 보존하며 수정 후 영향 검사·독립 차이 검토로 해소 여부를 판단한다. 최종 실행 증거에는 명령·종료 코드·skip·source hash를 연결한다.
