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
DEMO 그룹은 2026-10-14에, HP 그룹은 2026-10-16에 닫았다. DEMO05·hp0206 run은 abandon됐고 HP00·01 run은 종료돼 main에 들어왔다. 새 그룹 RL은 main에서 시작하며 새 loop 시작 전에 active run을 CLI로 다시 확인한다.

## 이전 DEMO·HP 설계 (기록)
회사 식별·추적은 lifecycle, 프로필·그래프·회사별 분석은 deep_review가 소유한다. 새 API namespace는 /api/companies이며 기존 경로의 wire 의미는 유지한다.
멱등성은 body request_id+core IdempotencyRecord, 심층 승인은 기존 DeepReviewPreview/Approval, 핏은 worker 역할 CLI enqueue다.
Luna 승인 정책은 이미지 파일과 `_approved_policy_path` 매핑으로만 인정된다.
2026-10-09 확인한 LiteLLM 별칭 `local-agent-main`의 선언 입력 상한은 32,768 tokens였고 HP에서는 쓰지 않는다.

### 회사 v2 준비 방향(2026-10-15)
승인 typed 사실+가상 실적 담당 범위+현재 조건을 단일 원본으로 연결한 뒤 기존 노드/관계로 projection한다. HP02 spec에서 기존 strict graph+typed sidecar binding을 사용하도록 고정했다. 실제 v2 등록 파일/제품 연결은 loop 구현 대상이다. HP03은 기능 유사성·현재 조건·계약 수용 조건을 분리하고 v1/v2 hash를 혼용하지 않는다. 출처는 HP02 preparation의 실적 기반 회사 v2 재계획 절이다.
## RL 목표 설계 (2026-10-16, ADR-0073)
회사는 실회사 루트랩 1곳이며 `is_fictional=false`로 등록한다. 회사 경계·그래프 저장·회사 REST·화면(DEMO-01~04)과 요구사항 카드 inventory(HP-01)·Luna identity(HP-00)를 재사용한다.
모든 LLM 작업은 codex-exec `gpt-6-luna`/high 하나다. 공고 원문·첨부·회사 근거의 전송은 정책 파일 단위 사전 승인으로 자동화하고 건별 감사·payload 동결·allowlist·hosted fallback 금지는 유지한다. LiteLLM `local-agent-main`·Qwen·Terra는 RL에서 호출하지 않으며 로컬 LLM은 RL-06에서 토큰 최적화로만 검토한다.
브리핑 전송은 Slack bot(전용 채널, 평일 1회)이며 토큰은 env 파일로 주입하고 payload에 공고 식별자·요약·링크만 넣는다. 화면은 같은 브리핑을 읽기 전용으로 보여 준다.
**의존: `slack_sdk`(`>=3.27,<4`, `requirements.lock`은 3.45.0 hash 고정).** 호출은 core `slack.py` 전송기 하나(Web API `chat.postMessage`·`chat.update`, Socket Mode)만 하고 호출 전에 `BIDOPS_SLACK_ENABLED`·토큰·채널·허용 host(`slack.com`,`wss-primary.slack.com`)를 검사한다. 버튼 반응은 공개 endpoint 없이 Socket Mode worker(`slack-worker`, compose profile `slack`)가 받는다. 브리핑은 결정적 규칙이라 LLM을 부르지 않는다.
제안서 초안 출력은 PDF(1차)이며 HWP는 후속 결정이다(인터뷰 E2). 생성기는 요구사항 카드 ID와 회사 근거 ID를 각 문장에 남긴다.
**의존: `reportlab`(`>=5.0,<6`, `requirements.lock`은 5.0.1과 전이 의존 `pillow` 12.3.0·`charset-normalizer` 3.5.2를 linux/amd64 cp312 wheel hash로 고정, RL-04 결정 B42).** PDF 렌더는 web 프로세스 안의 순수 Python이며 `invariant=1`로 같은 입력이면 같은 바이트다. 폰트는 백엔드 이미지의 NanumGothic(저장소 폰트 파일 없음)이며 위치는 `BIDOPS_PDF_FONT_DIR`(기본 `/usr/share/fonts/truetype/nanum`)이고 없으면 내보내기가 `pdf_unavailable`이다. PDF 객체는 namespace `proposal-pdf`(버킷 `bidops-proposal-pdf`, 365일)에 둔다(결정 B48).
core에는 순수 검증/타입만 두고 도메인 import를 추가하지 않는다. 그래프 DB·시맨틱웹 엔진은 도입하지 않는다(Neo4j 실험 보류).
DB 권한은 migration이 아니라 scripts/runtime-privileges.sql이 정본이다. Luna 승인 정책은 이미지 파일과 `_approved_policy_path` 매핑으로만 인정된다.
구현·검증은 main에서 분기한 기능 브랜치와 `COMPOSE_PROJECT_NAME=bidops-local` 격리 자원에서 하고 운영 배포는 별도 전환 작업이다.

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
DEMO 그룹은 2026-10-14에, HP 그룹은 2026-10-16에 닫았다. DEMO05·hp0206 run은 abandon됐고 HP00·01 run은 종료돼 main에 들어왔다. 새 그룹 RL은 main에서 시작하며 새 loop 시작 전에 active run을 CLI로 다시 확인한다.

## 이전 DEMO·HP 설계 (기록)
회사 식별·추적은 lifecycle, 프로필·그래프·회사별 분석은 deep_review가 소유한다. 새 API namespace는 /api/companies이며 기존 경로의 wire 의미는 유지한다.
멱등성은 body request_id+core IdempotencyRecord, 심층 승인은 기존 DeepReviewPreview/Approval, 핏은 worker 역할 CLI enqueue다.
Luna 승인 정책은 이미지 파일과 `_approved_policy_path` 매핑으로만 인정된다.
2026-10-09 확인한 LiteLLM 별칭 `local-agent-main`의 선언 입력 상한은 32,768 tokens였고 HP에서는 쓰지 않는다.

### 회사 v2 준비 방향(2026-10-15)
승인 typed 사실+가상 실적 담당 범위+현재 조건을 단일 원본으로 연결한 뒤 기존 노드/관계로 projection한다. HP02 spec에서 기존 strict graph+typed sidecar binding을 사용하도록 고정했다. 실제 v2 등록 파일/제품 연결은 loop 구현 대상이다. HP03은 기능 유사성·현재 조건·계약 수용 조건을 분리하고 v1/v2 hash를 혼용하지 않는다. 출처는 HP02 preparation의 실적 기반 회사 v2 재계획 절이다.
