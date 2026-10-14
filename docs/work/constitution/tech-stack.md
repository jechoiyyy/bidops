# BidOps tech-stack

## 기존 기준
[아키텍처](../../ARCHITECTURE.md)·[표준](../../standards.md)·[계약](../../contracts.md)이 상세 정본이다.
Python/FastAPI/SQLAlchemy/Alembic, PostgreSQL 17, versioned MinIO, ClamAV,
React/TypeScript/TanStack Query, Astryx 0.5.2와 프로젝트 bidops 테마를 유지한다.
문서 변환기는 기존 격리 worker, 분석은 기존 합성 worker의 슬롯 1개를 사용한다.
운영 범위의 개요·회사 핏은 승인된 사설 vLLM(`qwen3.8-27B`) 설정을 유지하고 HP 범위에서는 호출하지 않는다.
심층은 승인된 codex-exec 참조 경로다. 용도별 설정·정책·승인 경계를 합치지 않는다.

## HP 목표 설계 (2026-10-14)
- **모델.** HP의 모든 모델 호출은 codex-exec `gpt-6-luna`, reasoning `high`다. runner 상수·client 상수·새 불변 정책 파일·CLI 버전을 한 기능(HP-00)에서 함께 올린다.
  LiteLLM `local-agent-main`·Qwen·Terra는 HP에서 쓰지 않는다. 기존 정책 파일과 실행 row는 바꾸지 않는다.
- **입력.** HWP/HWPX 원본을 기존 rhwp 네이티브 경로(`hwp-rhwp-native-hwpx`·`hwpx-stdlib`)로 구조화한다. PDF는 PDF 전용 첨부와 쪽 locator(`para_page_map`)에만 쓴다. 새 PDF/OCR 라이브러리는 PDF 전용 첨부가 나타날 때 도입을 판단한다.
- **구조화.** `document_segments`가 표 셀 라벨·값 카드를 inventory 항목으로 읽고(새 extractor 버전·규칙 hash), 카드 쪽은 표를 담은 문단의 대응표에서 물려받는다. taxonomy v2는 운영·유지관리 라벨과 MAR·MPR·MHR·ECR 접두사를 더한다. 기존 manifest 행은 보존한다.
- **온톨로지·회사.** `bidops.company-ontology.v1` 스키마와 PostgreSQL 노드·관계·버전 저장을 그대로 쓰고 내용만 홈페이지 도메인 버전으로 바꾼다. 회사 원본은 `fictional_scenario` 1곳이며 사용자 승인 뒤 동결한다. 스키마 확장(kind·관계 추가)은 HP-02 interview에서 정한다.
- **파이프라인.** deep_review가 소유한다. 1층 타입화 추출(카드·구간 단위, 고정 JSON 계약)과 결정적 프로필 대조, 2층 역할별 판단·종합. 호출 수 상한·구간 묶음 크기·시간 목표는 HP 공통 계약의 정책 값이다. 모델 결과는 원문 locator와 카드 ID로 결정적 검증을 통과해야 한다.
- **화면.** 기존 회사 경로(`/api/companies`, 회사 화면)에 실무자 판정 5블록을 더한다. 데스크톱 전용·테마 토큰 규칙은 유지한다.
- **그래프 DB.** 제품은 PostgreSQL 그래프 테이블을 유지한다. Neo4j는 `docs/experiments`의 비교 실험(HP-05)에서만 컨테이너로 띄우고 결과 판단 뒤 채택 여부를 정한다. Apache AGE는 비교하지 않는다.
- **격리.** `bidops-local`(`COMPOSE_PROJECT_NAME=bidops-local`) 격리 자원과 데모 브랜치 `demo/local-20261009`에서 구현·검증한다. 운영 배포는 하지 않는다.
- DB 권한은 migration이 아니라 scripts/runtime-privileges.sql이 정본이다. core에는 순수 검증/타입만 두고 도메인 import를 추가하지 않는다.

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
실제 모델 호출은 건별 승인 뒤 격리 스택에서만 하며 격리 검증을 품질 근거로 쓰지 않는다.

## SDLC
설정/큐/상태는 docs/work, CLI는 python3 scripts/feature_status.py <command> <ID> 순서다.
standard=gpt-6-luna/max, complex 및 독립 review=gpt-5.6-sol/high.
commit/merge는 manual, push/브랜치 삭제는 요청 때만 한다.
DEMO 그룹은 2026-10-14에 닫았다. 활성 run `demo05-20261012`는 사용자가 abandon한 뒤 HP run을 시작한다.

## 이전 DEMO 설계 (기록)
회사 식별·추적은 lifecycle, 프로필·그래프·회사별 분석은 deep_review가 소유한다. 새 API namespace는 /api/companies이며 기존 경로의 wire 의미는 유지한다.
멱등성은 body request_id+core IdempotencyRecord, 심층 승인은 기존 DeepReviewPreview/Approval, 핏은 worker 역할 CLI enqueue다.
Luna 승인 정책은 이미지 파일과 `_approved_policy_path` 매핑으로만 인정된다.
2026-10-09 확인한 LiteLLM 별칭 `local-agent-main`의 선언 입력 상한은 32,768 tokens였고 HP에서는 쓰지 않는다.
