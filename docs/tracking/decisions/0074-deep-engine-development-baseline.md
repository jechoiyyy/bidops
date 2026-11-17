# ADR-0074 분석 엔진을 BidOps 개발 기준선에 통합

2026-11-17 사용자 통합 요청에 따른 구현 결정. 품질 인수·운영 활성화 결정은 아니다.

## 결정

BidOps가 수집·공고 identity·회사 근거·사람 결정·PostgreSQL·MinIO·공용 작업 슬롯을 계속 소유한다. bid-deep-agent의 분석 로직은 `packages/bid-deep-engine`으로 가져와 버전 adapter로 연결한다. 별도 SQLite task store·CLI/A2A/chat 서버와 원본 회사 파일 정본은 이식하지 않는다. 제품 소비자는 기존 사전규격 관리 화면이다.

원본의 Claude direct/gateway/CLI·fallback 및 Langfuse 전송은 현재 RL의 Luna/high·사전 정책 승인·건별 감사와 다르다. 이번 adapter는 mock_reference 실행을 명시적으로 제공하며 live 선택을 fail closed한다. 원본 transport를 감춘 채 기존 승인으로 호출하지 않는다. 제품 모델 변경이나 새 승인 정책 발행은 이 결정에 포함하지 않는다.

새 분석은 공고·묶음·회사 입력과 엔진 revision을 고정하고 별도 실행/결과로 남긴다. 기존 분석·사람 리뷰·최종 결정을 덮지 않는다. 원본의 abstain/null/unknown, 실패·부분 결과를 보존한다. 실제 분석 품질은 기존 reject와 미측정 상태를 유지한다.

Compose는 서비스 선택과 네트워크 권한을 분리한다. 개발 기본 project는 운영 `bidops`, 기존 데모 `bidops-local`과 다르며 운영 volume 이름을 바꾸지 않는다. Make/운영 스크립트는 공통 selector를 사용한다. 초기화·migration은 별도 명령이다. Mac 문서 worker는 native arm64 제약을 유지한다.

## 근거와 대안

두 저장소를 서버째 결합하면 SQLite/DB 큐·회사 정본·전송 승인이 이중화된다. 원본을 subprocess CLI로 무조건 호출하면 source transport와 로그·비용·observability 전송이 함께 따라온다. 따라서 분석 코어만 분리하고 저장/실행 책임은 제품 adapter에 둔다.

기존 모든 품질 문제를 먼저 해결하는 방법은 사용자가 지정한 개발 기준선 우선 목표와 다르다. 요구사항 누락·회사 정책의 차단 의미와 품질 재측정은 후속으로 유지한다.

## 검증과 한계

[RL-09 계획](../../work/groups/RL/features/RL-09-engine-integration/plan.md)의 입력·기대 결과·증거를 따른다. mock 결과는 연결만 검증하며 Luna 품질·모델 전송·운영 활성화를 입증하지 않는다. 운영 web의 기존 restarting/unhealthy 상태는 복구 범위에 포함하지 않는다.
