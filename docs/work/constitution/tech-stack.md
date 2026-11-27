# BidOps tech-stack

기준일: 2026-10-21. [아키텍처](../../ARCHITECTURE.md)·[표준](../../standards.md)·[계약](../../contracts.md)이 상세 정본이다. 현재 구현과 운영 배포·품질 승인을 구분한다.

## 현재 기반

- Python/FastAPI/SQLAlchemy/Alembic, PostgreSQL 17, versioned MinIO, ClamAV.
- React/TypeScript/TanStack Query, Astryx 0.5.2와 프로젝트 `bidops` 테마. RL 시안 v26의 테마·셸과 브리핑·회사·사업기회 레코드 화면이 구현돼 있다.
- 코드 Alembic head는 `0041_proposal_draft`. 2026-10-19 운영에도 0041 적용 기록이 있다.
- HWP/HWPX 원본은 rhwp 네이티브 경로(`hwp-rhwp-native-hwpx`·`hwpx-stdlib`)로 구조화한다. PDF는 PDF 전용 첨부·쪽 locator·초안 내보내기에 사용한다. 쪽 미확인을 추정하지 않는다.
- `lifecycle`은 회사 identity·브리핑·활동/노트, `screening`은 C-1·C-2, `deep_review`는 회사 근거·문서·판정·제안서를 소유한다. 모듈 간 읽기는 확장점으로 연결한다. 분석은 기존 합성 worker 슬롯 1개를 쓴다.

## 모델·실행 환경 구분

| 범위 | transport·모델 | 경계 |
|---|---|---|
| Mac C-2 v5 | LiteLLM `local-agent-main` → Ollama `qwen3.8:27b-ctx32k` | 10월 14일 게이트 통과, 마지막 운영 확인 10월 19일 active·일일 ON |
| Mac 사전규격 개요 | 같은 LiteLLM, `prespec-overview-policy-v7-litellm-v2.json` | 참조 실행. 10월 19일 기록상 개요 플래그·상시 첨부 worker 꺼짐 |
| RL 카드 판정·제안서 | codex-exec `gpt-6-luna` / `high` | 정책 단위 승인·건별 감사, 기본 비활성, fallback 없음 |
| 기존 C-1·심층·회사 핏 | 용도별 `core/model_client.py` 경로 보존 | 사설 vLLM 설정의 존재를 Mac 운영 실행으로 해석하지 않음 |

Mac 운영은 `scripts/mac-compose.sh`의 `bidops`(18788/8188)이고 격리 검증은 `bidops-local`(18787/8187)이다. 애플리케이션 amd64·문서 worker native arm64 구분과 현재 이미지 기록은 [operations](../../operations.md)를 따른다.

## RL 구현과 승인 계약 (ADR-0073)
회사는 실회사 루트랩 1곳이며 `is_fictional=false`로 등록한다. 회사 경계·그래프 저장·회사 REST·화면(DEMO-01~04)과 요구사항 카드 inventory(HP-01)·Luna identity(HP-00)를 재사용한다.
모든 LLM 작업은 codex-exec `gpt-6-luna`/high 하나다. 공고 원문·첨부·회사 근거의 전송은 정책 파일 단위 사전 승인으로 자동화하고 건별 감사·payload 동결·allowlist·hosted fallback 금지는 유지한다. LiteLLM `local-agent-main`·Qwen·Terra는 RL에서 호출하지 않으며 로컬 LLM은 RL-06에서 토큰 최적화로만 검토한다.
브리핑 전송은 Slack bot(전용 채널, 평일 1회)이며 토큰은 env 파일로 주입하고 payload에 공고 식별자·요약·링크만 넣는다. 화면은 같은 브리핑을 보여 주며 채택·무시 반응은 별도 개인 기록으로 저장한다.
**의존: `slack_sdk`(`>=3.27,<4`, `requirements.lock`은 3.45.0 hash 고정).** 호출은 core `slack.py` 전송기 하나(Web API `chat.postMessage`·`chat.update`, Socket Mode)만 하고 호출 전에 `BIDOPS_SLACK_ENABLED`·토큰·채널·허용 host(`slack.com`,`wss-primary.slack.com`)를 검사한다. 버튼 반응은 공개 endpoint 없이 Socket Mode worker(`slack-worker`, compose profile `slack`)가 받는다. 브리핑은 결정적 규칙이라 LLM을 부르지 않는다.
제안서 초안 출력은 PDF(1차)이며 HWP는 후속 결정이다(인터뷰 E2). 생성기는 요구사항 카드 ID와 회사 근거 ID를 각 문장에 남긴다.
**의존: `reportlab`(`>=5.0,<6`, `requirements.lock`은 5.0.1과 전이 의존 `pillow` 12.3.0·`charset-normalizer` 3.5.2를 linux/amd64 cp312 wheel hash로 고정, RL-04 결정 B42).** PDF 렌더는 web 프로세스 안의 순수 Python이며 `invariant=1`로 같은 입력이면 같은 바이트다. 폰트는 백엔드 이미지의 NanumGothic(저장소 폰트 파일 없음)이며 위치는 `BIDOPS_PDF_FONT_DIR`(기본 `/usr/share/fonts/truetype/nanum`)이고 없으면 내보내기가 `pdf_unavailable`이다. PDF 객체는 namespace `proposal-pdf`(버킷 `bidops-proposal-pdf`, 365일)에 둔다(결정 B48).
core에는 순수 검증/타입만 두고 도메인 import를 추가하지 않는다. 그래프 DB·시맨틱웹 엔진은 도입하지 않는다(Neo4j 실험 보류).
DB 권한은 migration이 아니라 scripts/runtime-privileges.sql이 정본이다. Luna 승인 정책은 이미지 파일과 `_approved_policy_path` 매핑으로만 인정된다.
RL-00~05 코드는 main에 통합됐다. 운영에는 2026-10-19 기준 코드·스키마만 반영했고 RL 분석은 비활성이다. 이후 v11 분석과 gold 인수는 격리 스택 증거다. [RL-05 인수](../../validation-runs/2026-10-19-rl/RL-05/README.md)는 reject, RL-04 실제 초안(`docs/validation-runs/2026-10-17-rl/RL-04/README.md`, git 이력)은 partial이다.

카드 판정 import 기본 파일은 `analysis-policy-luna-rl-v12.json`(v11과 모델 계약이 같고 결정적 대조 규칙 `card-compare-v2`를 고른다, RL-10), selector는 `card-sections-v4`, 역할·종합 출력 계약은 v3이다. 실행 정책은 import된 행과 환경의 정책 ID가 고르며 기본 파일 변경이 활성화를 뜻하지 않는다.

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
RL 자동 전송은 승인된 정책·scope·상한 안에서만 허용한다. 실제 검증 실행과 운영 활성화는 사람 확인 경계를 따르며 격리 검증을 품질 합격으로 쓰지 않는다.

## SDLC
설정/큐/상태는 docs/work, CLI는 python3 scripts/feature_status.py <command> <ID> 순서다.
standard=gpt-6-luna/max, complex 및 독립 review=gpt-5.6-sol/high.
commit/merge는 manual, push/브랜치 삭제는 요청 때만 한다.
DEMO 그룹은 2026-10-14에, HP 그룹은 2026-10-16에 닫았다. RL-00~05의 구현·평가 기록은 main에 있으며 새 loop 시작 전 실행 큐·active run·증거 현재성을 CLI로 다시 확인한다.

## 종료된 설계의 참조 범위

DEMO 가상 3사와 HP 가상 1사 신규 작업은 종료됐다. 회사 경계·그래프 저장(DEMO-01~04), 카드 inventory(HP-01), Luna identity(HP-00)는 RL이 재사용한다. [DEMO 공통 계약](../demo-contract.md)과 [HP 공통 계약](../hp-contract.md)은 재사용 코드의 계약 기록이며 가상회사 등록·Neo4j 실험 계획을 현재 작업으로 실행하지 않는다.
