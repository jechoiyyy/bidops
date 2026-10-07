# BidOps tech-stack

## 기존 기준
[아키텍처](../../ARCHITECTURE.md)·[표준](../../standards.md)·[계약](../../contracts.md)이 상세 정본이다.
Python/FastAPI/SQLAlchemy/Alembic, PostgreSQL 17, versioned MinIO, ClamAV,
React/TypeScript/TanStack Query, Astryx 0.5.2와 프로젝트 bidops 테마를 유지한다.
문서 변환기는 기존 격리 worker, 분석은 기존 합성 worker의 슬롯 1개를 사용한다.
개요·회사 핏은 승인 사설 vLLM, 심층은 승인된 Luna codex-exec 참조 경로다.

## DEMO 목표 설계
회사 식별·추적은 lifecycle, 프로필·그래프·회사별 분석은 deep_review가 소유한다.
core에는 순수 검증/타입만 두고 도메인 import를 추가하지 않는다.
PostgreSQL 노드·관계·버전과 기존 근거 저장소를 연결한다. 그래프 DB/시맨틱웹 엔진은 도입하지 않는다.
기존 공고/문서 구조와 v7 회사 비의존 개요는 공유하고 회사에 의존하는 상태만 분리한다.
새 API namespace는 /api/companies이며 기존 경로의 wire 의미는 유지한다.
2026-10-06 재계획: 멱등성은 body request_id+core IdempotencyRecord, 심층 승인은 기존 DeepReviewPreview/Approval, 핏은 worker 역할 CLI enqueue다.
DB 권한은 migration이 아니라 scripts/runtime-privileges.sql이 정본이다. Luna 승인 정책은 이미지 파일과 `_approved_policy_path` 매핑으로만 인정된다.
DEMO-00만 main·운영 배포 대상이고 DEMO-01~05는 데모 브랜치 전용이다. 격리 데모의 로컬 LLM은 운영과 같은 qwen3.8-27B를 사용자가 제공하는 엔드포인트로 쓰고,
Codex 인증은 운영과 같은 계정 파일을 운영 Luna와 겹치지 않게 순차로 쓴다.

## 강제 기준과 실행용 복사
feature.json constraints는 AGENTS.md, standards, business-rules, contracts, operations,
backend/frontend AGENTS의 실행용 요약이다. 전체 규칙과 충돌하면 원문이 우선이다.
각 기능 intent에 이 설정과 docs/work/source-baseline.json의 원본 hash를 연결한다.
가상 설정 여부는 확실성 상태와 별도 축이다. 프로필/그래프의 원본은 동일 버전에서 파생한다.
사내망/claimed name 경계를 유지하며 새로운 인증 기능을 암시하지 않는다.

## 검증·실행
문서 작업: doctor·링크·STEP/테스트 대응·diff. 앱 빌드나 제품 테스트를 실행하지 않는다.
제품 작업: 각 plan의 직접 영향 검사, PostgreSQL 변형은 임시 postgres:17.11,
BIDOPS_TEST_POSTGRES_URL과 BIDOPS_PRESPEC_OVERVIEW_ENABLED=false를 명시한다.
UI는 production build와 해당 화면의 1280×800·1440×900 의미/구조 검사.
명령이 비어 있는 proof는 자동 통과가 아니다. 해당 plan의 명령/수동 증거가 필요하다.
별도 lint 도구는 미채택이므로 가짜 lint 성공 항목을 만들지 않는다.

## SDLC
설정/큐/상태는 docs/work, CLI는 python3 scripts/feature_status.py <command> <ID> 순서다.
standard=gpt-6-luna/max, complex 및 독립 review=gpt-5.6-sol/high.
commit/merge는 manual, push/브랜치 삭제는 요청 때만 한다. 구현 배치는 별도 loop에서 시작한다.
