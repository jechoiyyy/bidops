# 분석 엔진 통합 개발 기준선

2026-11-17 사용자 요청. 품질 실패 해결보다 하나의 checkout에서 제품 연결을 먼저 만든다.
BidOps의 공고 identity·회사 정본·PostgreSQL·MinIO·공용 worker·사람 결정을 유지한다.

| 유즈케이스 | 실행 | 확인 |
|---|---|---|
| 개발 시작 | make help/config/build/up | 운영·데모와 project/port/volume 분리 |
| 공고 분석 | 상세 API 접수 → 공용 worker → 결과 API → 관리 화면 | mock 표식·원본 계보·unknown 보존 |
| 실패 확인 | 부분/실패 응답 | 기존 리뷰 불변, 실패가 성공으로 바뀌지 않음 |

선행: 기존 main의 제품 기반 재사용. 기존 RL-05 품질 합격은 이 통합의 선행이 아니며 reject를 보존한다.
후속: 파서 누락·회사 정책 차단 의미·품질 재측정·승인된 live 전송 계약.
실제 모델·Slack·운영 변경은 범위 밖이다. 초기 요청에서 제외했던 commit·main 병합·기존 origin push·worktree/브랜치 정리는 2026-11-18 후속 사용자 요청으로 승인됐다. 미완료 작업은 복구 가능하게 보존하고 운영 마운트 경로는 유지한다.
