# 통합 계약

- BidOps HEAD 539bb8b4020394fa6020933627e31a6ac55b7537와 사용자 작업 71개를 새 worktree에 보존한다.
- 원본 엔진 HEAD 7ad9283d8e8a405074374d12c5f0a13ccb8e5b1f. 가져오는 파일마다 해시·로컬 변경 범위를 남긴다. 비밀·회사 원문·실행 산출물은 복사하지 않는다.
- 분석 책임은 분리된 패키지와 버전 adapter. SQLite 작업 큐, 독립 CLI/A2A/chat 운영 구조는 이식하지 않는다.
- 공고/회사/큐 정본은 BidOps. 분석마다 새 실행과 입력·엔진 revision·결과 계보를 보존한다.
- 기존 unknown/null/partial/failed와 사람 추적·최종 결정은 보존한다. mock_reference는 품질 합격이 아니다.
- 원본 Claude direct/gateway/CLI·fallback은 RL Luna/high 정책과 충돌한다. 원본 transport를 활성화하지 않는다. 실제 전송은 금지하며 승인되지 않은 live 선택은 호출 전에 거부한다.
- 개발 기본은 운영 bidops 및 기존 데모 bidops-local과 별도 project/port/volume. 서비스별 network·secret 경계와 Mac arm64 문서 worker 제약은 보존한다.
- Make와 운영 스크립트의 설정 선택은 하나로 통합한다. 초기화·migration·배포는 별도 명령이다.

| 검사 | 입력 | 기대 | 증거 |
|---|---|---|---|
| 엔진/adapter | 합성 공고·기록 응답·실패/unknown | 원문 검증, 상태 보존, 전송 없음 | 관련 pytest |
| 제품 연결 | 격리 PostgreSQL/객체 저장·공고 1건 | 접수→worker→저장→API→화면 | 통합 로그·화면 캡처 |
| Compose | dev/mock/prod 렌더 | 자원 분리·서비스 egress 유지 | 설정 계약 검사 |
| 기존 경로 | 영향 모듈 회귀 | 기존 계약 보존 | 관련 pytest/build |
| 입력 중 묶음 갱신 | 늦은 ready 응답, 저장 실패 환경, 응답 유실 뒤 새 draft | actor 초안 유지, 동일 request/actor/bundle 재확인, 현재성 재조회 | engine-analysis.spec.ts; old 코드 실패 후 수정 검증 |

구체 API와 패키지 계약은 [엔진 실행 계약](../../../../../contracts/engine-runs.md)에 고정했다.
