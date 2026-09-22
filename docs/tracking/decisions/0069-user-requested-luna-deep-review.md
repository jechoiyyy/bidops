# ADR-0069 사용자 요청 기반 Luna 심층검토

- 채택: 2026-09-22 사용자 구현 요청. 구현·격리 검증: 2026-09-23.
- 운영 적용·실제 자료 전송은 별도 직전 승인 전까지 미실행.
- 정본: [목적](../../0922_luna-deep-review/intent.md), [명세](../../0922_luna-deep-review/spec.md), [계획](../../0922_luna-deep-review/plan.md).

수집·문서 준비·개요 자동화는 유지하고 심층 자동 시작은
`BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false`를 기본으로 한다. 공통 자동 시작
함수와 직접 system actor 생성 경로가 모두 검사한다. Luna 정책은 system actor로
실행할 수 없다. 수동 대기는 개요 실패가 아니다.

`analysis-policy-luna-v1.json`은 기존 Qwen 정책을 바꾸지 않고 narrative stage/report v2,
`codex-exec` / `gpt-5.6-luna` / `xhigh`, CLI 0.155.1, 호출 900초·검토 7200초,
자동 재호출 없음, `unmeasured_reference`를 고정한다.

사전규격 상세의 원천 입력 미리보기는 문서 묶음·구조·회사 프로필·정책·inventory·
원문 대조 설정·완료된 개요 ID를 동결한다. 제출은 해당 미리보기 해시와 현재 입력을
재검증하고 새 attempt에 승인자·시각·request ID를 append한다. 모델 호출 때는 승인된
스냅숏과 동일 실행에서 검증된 선행 결과만 쓴다. 담당자 이름은 인증이 아니다.

기존 합성 worker만 큐를 소비한다. 내부 HTTP 실행기는 단일 호출만 처리하며 별도
큐·DB·MinIO 접근이 없다. worker는 폴링 전에 살아 있는 lease를 갱신하고 소유권을
잃으면 취소한다. 실행기는 heartbeat가 45초 끊기면 프로세스 그룹을 종료한다.
만료된 Luna 작업은 실패로 닫고 자동 resume하지 않는다. Qwen fallback은 없다.

별도 `docker-compose.luna.yml`로 worker↔runner 내부망과 runner 외부망을 추가한다.
호스트 홈·저장소·DB 자격증명을 마운트하지 않는다. 전용 auth.json secret만 읽어
임시 CODEX_HOME에 복사하며 사용자 설정·rules를 배제한다. read-only sandbox,
ephemeral, 고정 argv, stdin, 권위 schema에서 파생한 출력 schema를 사용한다.
원응답은 worker의 기존 암호화 저장 경로로 보존하고 일반 로그에는 남기지 않는다.

이 경로에 한해 승인된 RFP와 회사 근거의 외부 전송을 허용한다. 기존의 포괄 금지보다
이 사용자 승인 예외가 우선한다. 이는 실제 건별 승인이나 실제 모델 접근 검증을
대체하지 않는다. 전용 목록·일괄 요청·입찰공고·독립 병렬 worker는 제외한다.
