# PDF·회사 핏 참조 인수 경계

2026-10-21 정리. 2026-09-09 v4 구현 계획에서 여전히 필요한 적용·중단 조건만 옮겼다. 당시 단계 목록은 현재 실행 큐가 아니며 `git show b5a61e4:docs/tracking/prespec-v4-implementation-plan.md`에서 찾는다.

현재 PDF snapshot·회사 핏 계약은 [문서·심층 검토](deep-review.md), 실행은 [참조 절차](../operations/prespec-reference.md), 신규 기능은 [RL 로드맵](../work/constitution/roadmap.md)을 따른다. RL 카드 판정은 개요·회사 핏 자동 게이트를 사용하지 않는다.

## 마지막 v4 인수의 범위

[PDF 선행](../validation-runs/20260908-prespec-pdf-preflight.md)·[회사 핏](../validation-runs/20260908-prespec-company-fit.md)에서 35·59의 연결을 확인했으나 142의 PDF 준비와 실제 matched → 심층 자동 시작은 미검증으로 남았다. 이후 변환 변경은 [2026-09-10 기록](../validation-runs/2026-09-10-rhwp-pipeline.md)과 [문제 색인](../tracking/findings.md)을 함께 읽는다. 9월 표본 상태를 현재 운영 상태로 승계하지 않는다.

## 적용·중단 경계

적용은 `PDF 선행 검증 통과 → 격리 통합 검증 → 대상 manifest/policy/model binding/권한/migration/backup 준비 → 표본 제한 배포 → 실제 인수 → 신규 참조 자동 처리 기준 동결` 순서로만 진행한다. 기본 off 상태에서는 신규 예약·호출·후속 단계가 시작되지 않고 진행 결과는 보존한다.

다음 경우 즉시 해당 실행을 중단하고 `docs/tracking/findings.md`에 재현 조건·영향·후속 방향을 남긴다.

- 허용 경로 이탈, symlink, 부분 파일, privileged/host 파일 접근, PDF 페이지 대응 불가가 발생하면 즉시 해당 실행을 중단한다. 일반 변환 실패·빈 텍스트는 attempt의 안전 실패 사유로 보존하고 자동 후속 실행을 막는다.
- 원문·PDF·모델 입력 hash 결속 실패, schema/근거/금액 역할 검증 실패를 성공으로 저장하려는 경로.
- 승인되지 않은 host/revision/profile/document가 모델 payload에 포함되거나 hosted fallback이 시도되는 경우.
- 기존 원문·리뷰·결과를 덮어쓰거나, 범위 밖 공고·동일 content hash를 신규 대상/예약으로 잡는 경우.
- PG migration/권한/불변 trigger가 기존 데이터를 보존하지 못하는 경우.

일반 변환·입력·검증 실패는 해당 attempt의 안전 오류와 재현 명령으로 기록한다.
`docs/tracking/findings.md`에는 보안 경계 또는 구조 계약을 깨는 재현만 추가한다.

운영 DB migration, 서비스 재시작, 실제 사설 모델 호출, 정책 활성화는 대상·입력·설정·호출 범위·복구 계획을 먼저 준비하고, 기존 사용자 세션에 이미 부여된 승인 범위와 저장소 보안·운영 규칙을 따른다. 별도 승인 체계를 추가하지 않으며, 승인 범위를 벗어나는 실행은 수행하지 않고 조건을 기록한다. 코드·mock·참조 실행만으로 운영 완료를 보고하지 않는다.
