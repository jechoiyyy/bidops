# HP-00 STEP-003

- 구현자 gpt-5.6-sol/high hp00_step003. preview/create/retry/claim 모델 guard, 정책 기반 표식과 legacy 조회, 가정 분석 정책 binding 추가.
- 리더 검증 backend-tests.log: plan의 7개 backend 파일, PostgreSQL 17.11 변형 포함 156 passed / 4 failed / skip 없음. 실패는 legacy v1/v2 실행 fixture 3건 및 v4를 잘못 사용한 회사 경계 fixture 1건.
- 제품 코드 변경 없이 현재 v5 fixture로 전환. legacy strict validator 검증은 직접 validator 사례로 유지. backend-fixture-fix.log: 4 passed, 62 deselected. 기존 strict parameter 두 개를 현재 실행 하나+legacy validator 하나로 유지해 총 사례 수 동일.
- 최종 증거는 첫 실행 통과 156개와 변경 사례 4개 통과의 합이다. 변경되지 않은 통과 경로를 재실행한 것으로 쓰지 않는다.
- input 내부 policy_binding은 기존 가정 분석에 정책 FK가 없어 고정 정책 검증을 충족하기 위한 최소 참조. spec에 반영하고 accept-spec 기록.
- 실제 모델 호출·정책 import·배포 없음.
