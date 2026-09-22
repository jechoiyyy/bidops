# BidOps 작업 지침

BidOps는 기획·사업개발 담당자가 나라장터 발주계획을 조기에 탐색하고, 사전규격 제안요청서를 검토한 뒤 입찰공고까지 추적하도록 돕는 사내 의사결정 지원 시스템이다.
관측 규모는 발주계획 3일 약 1,200건, 1주 약 2,000건이며, Python 파이프라인과 FastAPI·React 관리 화면으로 처리한다.
자동 입찰, 발주처 연락, 추적 승인, 최종 Go/No-Go는 사람이 결정한다.

## 저장소 지도

```text
bidops/
├── AGENTS.md, CLAUDE.md              작업 진입점이며 내용은 동일하다
├── docker-compose.yml                PostgreSQL·MinIO 기반 애플리케이션 스택
├── docker-compose.edge.yml           관리 화면 host publish (이 파일만 포트를 연다)
├── docker-compose.model-egress.yml   screening·overview·deep_review 모델 egress
├── docker-compose.c2-order-plan.yml  C-2 발주계획 판정 입력 마운트
├── docker-compose.prespec-attachment.yml  사전규격 첨부 G2B egress
├── docker-compose.mock-reference.yml 모델 없는 참조 실행
├── run-tests.sh                      파이프라인 단위·교차 테스트
├── data/, reports/                   불변 회차 입력과 파생 보고서
├── docs/
│   ├── ARCHITECTURE.md               현재 구조·계약·목표 데이터 흐름 (정본)
│   ├── ADR.md                        결정 통합 색인 (상세는 tracking/decisions/)
│   ├── PRD.md, PLAN.md               현재 착수 범위(발주계획 C-2 선별)의 요구와 순서
│   ├── business-rules.md             생애주기·선별·심층 검토 상태 규칙
│   ├── standards.md                  구현·검증 강제 기준
│   ├── engineering-notes.md          증상별 재발 방지 지식
│   ├── operations.md                 설치·실행·백업·복구 절차
│   ├── contracts.md                  REST·파일·DB 소비자 계약
│   ├── database-guide.md             DB 전체 해설과 설계 근거
│   ├── deep-review-erd.md            심층 검토 DB 권위 계약
│   ├── bid-delta-contract-spec.md    입찰 delta·최종 결정 OpenAPI·DB 명세
│   ├── scheduling.md                 공고 판정 스케줄러의 예약·기간·fail-closed 조건
│   ├── model-quality-gate.md         공고 판정 품질 게이트의 고정 입력과 통과 기준
│   ├── prespec-reference-run-guide.md  사전규격 참조 실행 시작 가이드 (먼저 읽는다)
│   ├── e2e-bc-acceptance.md          문서 준비(B)→심층 검토(C) 연속 인수 절차
│   ├── e2e-lifecycle-fill.md         공고·사전규격·리뷰 테이블 채우기와 화면 확인 절차
│   ├── docker-consolidation.md       t7 접두사 제거와 Compose 프로젝트·호스트 자원 정리 기록
│   ├── agent/agent-runtime.md        공고 판정 worker의 입력 동결·span·telemetry
│   ├── 0915_ui-redesign/            관리 화면 재설계 C 정본(2026-09-15 채택, 시안·plan·notes)
│   ├── 0917_opportunity-tracking/   사업 추적 연결·선별 적재·Go/No-Go 분리 정본(2026-09-17 승인, intent·spec·plan)
│   ├── 0918_daily-operation/       매일 1일치 수집·판정 운영 고도화 정본(2026-09-18 승인, 2026-09-19 main 병합·운영 배포·C-2 v4 게이트 통과와 활성화, 사람 결정 D-a~D-e 값은 plan.md §결정 표, intent·spec·plan)
│   ├── deep-review-v2/               첨부문서 분석 설계(결정적 부분만 구현, ADR-0051)와 Luna 시안 검증 계획(보류)
│   ├── rhwp-document-pipeline/       rhwp 네이티브 변환 파이프라인 작업 정본(ADR·Requirements·Design·Spec·Plan, 2026-09-10 시작)
│   ├── reference/                    회사 프로필·실적 근거자료
│   ├── validation-runs/              시점별 실행 증거
│   └── tracking/
│       ├── status.md                 구현과 검증의 현재 상태
│       ├── lifecycle-workstream.md   생애주기 구현의 결정 대기·할 일 기록
│       ├── findings.md               재현 가능한 미해결 문제
│       └── decisions/                기술·운영 결정과 대안·결과
├── skills/
│   ├── bidops-collect/AGENTS.md       수집·정규화·표본 선정
│   ├── bidops-screen/AGENTS.md        구조화 1차 판정·병합
│   └── bidops-report/AGENTS.md        결정적 HTML·피드백 렌더링
└── web/
    ├── AGENTS.md                      이미지·Compose·통합 검증
    ├── backend/AGENTS.md              API·PostgreSQL·객체·worker
    └── frontend/AGENTS.md             React 검토 화면
```

`docs/validation-runs`는 시점별 실행 증거이며 현재 코드와 위 핵심 문서의 계약을 대체하지 않는다. 완료·미채택 계획, 과거 리뷰·목업, 인수인계 문서는 저장소에 보관하지 않으며 필요하면 git 이력에서 찾는다. 과거의 `R-xx`·`A-xx`·phase·T-번호 체계는 종료됐고 새 작업에 다시 쓰지 않는다. 외부 의존성은 나라장터 OpenAPI, PostgreSQL 17, MinIO, ClamAV, 승인된 사설 OpenAI-compatible vLLM(`qwen3.8-27B`), 문서 변환기, 승인 프로필 기준선 검증용 Git, Astryx 디자인 시스템(`@astryxdesign/core@0.5.2`, `@astryxdesign/cli@0.5.2`, 테마 아이콘 레지스트리가 요구하는 `lucide-react@1.39.0`)이다.
Astryx의 "레이아웃도 컴포넌트로만, `<div>` 금지" 규칙은 ADR-0040에 따라 이 저장소에 적용하지 않으며 레이아웃은 프로젝트가 소유한다.
화면의 색은 무드보드(git 이력 `docs/design/moodborad.jpg`, 삭제됨)에서 파생한 프로젝트 소유 테마 `bidops`가 정본이며(ADR-0048), 화면은 테마 토큰만 읽고 `:root`나 화면 CSS에서 `--color-*`를 재정의하지 않는다. 성공·실패·경고 의미색은 무드보드가 정하지 않는다.

## 작업 전 확인

- 모든 변경 전에 `docs/standards.md`, `docs/engineering-notes.md`, 변경 경로에서 가장 가까운 `AGENTS.md`를 읽는다.
- 상태·등급·참여 준비·사람 판정 필드를 바꾸면 `docs/business-rules.md`를, JSON/YAML/REST/DB 계약을 바꾸면 `docs/contracts.md`를 확인한다.
- DB·적재·회차를 바꾸면 원본 불변성, 부분 산출물 경고, DB 정본 리뷰, Alembic 경계를 확인한다.
- 첨부·변환·다운로드·모델 전송·로그를 바꾸면 경로 격리, 최소 권한, 감사, 건별 외부 전송 승인(모델 전송 정책은 ADR-0050 완화 항목 참조)을 확인한다.
- 배포·일정·모델·backup을 바꾸면 `docs/operations.md`의 현재 실행 명령과 fail-closed 기본값을 확인한다.
- 발주계획 선별 제품 구현은 고정 3일 표본의 키워드·ColBERT·Qwen·GPT Luna 비교 실험과 사람 정답 보고서가 승인된 뒤 시작한다.

## 검증 범위와 종료 기준

- 검증은 변경한 기능과 직접 영향받는 경로부터 수행한다. 작은 문구·스타일·단일 화면 변경에 전체 스위트, 전체 이미지 재빌드, 전 화면 재검사를 관성적으로 실행하지 않는다.
- 전체 검사는 공통 기반·여러 모듈의 계약 변경, 관련 검사에서 확인된 광범위한 회귀, 사용자의 명시적 요청처럼 구체적인 근거가 있을 때만 수행한다. 실행 전에 그 이유를 짧게 설명한다.
- 관련 검사가 통과하면 검증을 종료한다. 이후 코드 변경이나 새로운 실패·미해결 위험이 없으면 같은 빌드·테스트·화면 확인을 반복하지 않는다. 수정 후에는 영향받은 검사만 다시 실행한다.
- 실패하면 먼저 원인과 변경 관련성을 확인한다. 통과 결과를 얻기 위한 반복 실행이나 근거 없는 ‘3회 연속 통과’ 검사를 하지 않는다. 무관한 기존 실패는 사실대로 보고하고 작업 범위를 불필요하게 넓히지 않는다.
- 문서만 바꾼 경우에는 변경 내용과 diff를 확인하며 앱 빌드·화면 테스트·배포는 하지 않는다. 검증을 위해 일회성 도구·테스트 인프라·장문의 기록을 과도하게 추가하지 않는다.
- 검증 실행 범위는 이 절을 우선한다. `docs/standards.md`와 하위 `AGENTS.md`의 명령 목록은 매 작업마다 전부 실행하라는 뜻이 아니다. 해당 변경에 필요한 계약·보안·데이터 불변성 검사는 유지하고, 실행한 범위와 남은 한계를 정확히 보고한다.

### 검증 지연·중복 리뷰 재발 방지

- **검증 항목은 처음에 묶는다.** 요구사항별로 입력·기대 결과·검사 명령·증거 위치를 기존 작업 목록에 짧게 연결한다. 단위/API 검사가 실제 UI 연결까지 증명하지는 않는다. 페이지 경계·시간대·마이크로초·null처럼 함께 작동해야 하는 조건은 대표 통합 사례에 처음부터 포함한다. 별도 계획서나 장문 보고서를 늘리지 않는다.
- **추가 요청은 구체적인 차이만 받는다.** 리뷰어는 미검증 요구사항, 기존 증거로 부족한 이유, 정확한 입력·기대 결과를 한 번에 제출한다. 리더는 이를 수용하거나 근거를 들어 기각하고 기록한다. 이미 받은 조건을 반복해서 요청하거나, 수용만 하고 실행하지 않은 채 같은 대화를 되풀이하지 않는다.
- **검사 실행자는 하나다.** 리더가 관련 검사를 실행하고 리뷰어는 동일한 소스와 결과를 읽는다. 명시적으로 요구된 리뷰 외에 역할·승인 단계를 관성적으로 추가하지 않는다. 결과는 차단 문제·근거·판정 중심으로 짧게 받으며, 대기 시간이 길어지면 실제 진행과 범위 이탈부터 확인한다. 느리다는 이유만으로 같은 작업을 새로 띄우지 않는다.
- **수정 후에는 차이만 재검토한다.** 같은 검토 회차의 지적을 합쳐 고친 뒤 변경 경로와 직접 영향받는 검사만 재실행한다. 변경되지 않은 경로는 소스 동일성과 기존 증거를 대조해 재사용하며 현재 변경을 검사한 것처럼 적지 않는다. 테스트 기대값·증거 형식만 수정했다면 제품 전체 재빌드·전수 리뷰를 다시 시작하지 않는다. 새 구체적 회귀가 있으면 그 영향 범위만 확장한다.
- **실패를 숨기는 수정을 하지 않는다.** 제품 결함, fixture·assertion 오류, 실행 환경 장애를 먼저 구분한다. `.first()`나 강제 클릭으로 중복 폼·포인터 차단을 숨기지 않는다. 동일 프레임 중복 제출처럼 합성 이벤트가 필요한 검사는 그 목적을 명시하고 실제 사용자 조작 검사와 분리한다.
- **실행 환경을 짧게 확인한다.** 브라우저 검사 전에 서버 응답, 빌드 대상, mock/live 모드와 필요한 API 응답을 확인한다. mock의 미처리 요청이 꺼진 백엔드나 운영 API로 빠지지 않게 한다. 연결 실패를 제품 실패로 섞거나 긴 전체 검사 timeout으로 대신 진단하지 않는다.
- **증거를 처음부터 올바르게 수집한다.** 캡처는 필요한 데이터와 대상 상태를 기다린 뒤 찍고 직접 확인한다. loading shell은 로딩 상태만 증명하며 완성 화면의 근거로 쓰지 않는다. 자동화 기록은 실제 실행에서 생성하고 경로·형식 계약은 초기에 확인한다. 완료 직전에 필드를 추측해 반복 변환하거나 다른 시나리오의 이미지로 빠진 행동 증거를 대신하지 않는다.
- **제품 검증과 완료 기록을 구분한다.** 워크플로 도구의 `complete` 출력만으로 전체 요구사항 충족을 판단하지 않는다. 하위 문제 처리 전후에 원래 목표·남은 항목·최종 검증 근거가 보존되는지 확인한다. 기록 형식 오류는 도구·기록 범위에서 해결하며, 이를 이유로 제품 테스트·리뷰나 새 목표를 반복 생성하지 않는다. 필수 게이트는 생략하지 않는다.
- **종료 뒤 중복 알림으로 재개하지 않는다.** 작업 ID·검토 회차로 이미 반영한 결과와 지연 도착 알림을 구분한다. 새 실패·미해결 문제가 없으면 재검사나 반복 완료 보고를 하지 않는다. 검사용으로 직접 띄운 프로세스만 종료하되, 사용자가 계속 확인하도록 요청한 미리보기 서버는 유지하고 주소·mock 여부를 알린다.

## 강제 게이트

- 확인되지 않은 회사 역량·자격·실적과 공고 사실을 추정하지 않는다. `unknown`과 `null`은 검증 대기 상태로 보존한다.
- 적합성 등급, 참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go를 서로 대신하지 않는다.
- 모델의 숫자·요구사항·근거는 원문 위치와 연결하고 결정적 검증을 통과시킨다. 실패 결과는 사람 검토로 보내며 자동 보정하지 않는다.
- 기존 파이프라인은 subprocess·버전 파일 계약으로 연결한다. 웹에서 내부 구현을 가져오거나 같은 업무 규칙을 복제하지 않는다.
- 외부 모델은 승인된 payload만 건별 전송한다. 운영 장애 때 hosted OpenAI로 자동 fallback하지 않는다.
- 모델 호출은 용도(`screening`·`overview`·`deep_review`)별 설정으로 나간다. MVP 기간에는 허용 host·선언 revision을 비워 둬도 그 용도는 호출한다(ADR-0050 §5 완화); 값이 있으면 허용 host 목록·64자 hex 여부를 그대로 검사해 어긋나면 **호출 전에** fail closed한다.
- 참조 실행 결과(`quality_status=unmeasured_reference|mock_reference`)를 운영 완료·품질 근거·정책 활성화 근거로 적지 않는다. 표식 없음(`null`)을 미측정이나 측정으로 승격시키지 않는다.

## 사용자 요청 기반 Luna 심층검토 (ADR-0069)

- 심층 자동 시작은 `BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false`가 기본이다. 수집·문서 준비·개요 자동화는 유지한다.
- 사전규격 상세에서 전송 미리보기와 건별 승인 후 기존 공용 슬롯으로 Luna 참조 분석을 요청한다. `BIDOPS_LUNA_DEEP_REVIEW_ENABLED`·참조 모드·새 불변 정책이 필요하다.
- 실제 적용·자료 전송은 각 단계 직전 사람 확인 대상이며 격리 검증을 실제 모델 품질 근거로 쓰지 않는다. 상세는 `docs/0922_luna-deep-review/plan.md`·`apply.md`.

## 현재 런타임 사실

- PostgreSQL 17의 `bidops` schema와 versioned MinIO가 운영 정본이다. SQLite는 격리 테스트와 일회성 이전 입력에만 사용한다.
- `docker-compose.yml`이 애플리케이션 스택이다. 기본 network는 내부망이며 외부 호출은 목적별 overlay를 명시한 경우에만 연다.
- 관리 화면은 **데스크톱·노트북 전용**이다. 지원 폭은 1280~1920px이며 모바일·태블릿 레이아웃과 터치 전용 조작을 만들지 않는다. 1280px 미만은 가로 스크롤을 허용하고 별도 레이아웃으로 전환하지 않는다(ADR-0047). 화면 검증 viewport는 laptop 1280x800과 desktop 1440x900 두 폭이다.
- 현재 애플리케이션에는 로그인·역할 기반 권한이 없다. 사내망 접근 제한이 경계이고 담당자 이름은 감사 표식일 뿐 인증이 아니다.
- 스케줄러와 always-on은 기본 비활성이다. 앱 startup은 migration, seed, 정책 활성화, 모델 호출을 수행하지 않는다.
- 사전규격은 등급이 `우선 검토`이면 문서 준비를 자동으로 진행한다. `BIDOPS_PRESPEC_OVERVIEW_ENABLED`가 켜져 있으면 ready 묶음에서 개요 run을 자동 enqueue하고, 개요 run이 `completed`이고 `SW사업대상=Y`이며 현재 회사 핏 `matched`인 게이트를 지나야 심층 검토를 자동 시작한다. 이 자동 시작은 `BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=true`일 때만 허용하며 새 기본값은 false다(ADR-0049·ADR-0054, 2026-09-08 회사 핏 게이트 추가, 2026-09-11 개요 스택 재작성). 회사 핏은 기본 비활성이고 현재는 명시적으로 켠 참조 실행만 지원한다. 자동으로 여는 것은 분석의 시작뿐이며 추적 승인과 최종 Go/No-Go는 사람이 결정한다.
- C-1 공고 판정·사전규격 개요·심층 검토는 `app/core/model_client.py` 하나를 용도별 설정으로 부른다. C-2 발주계획 어댑터와 사용자 승인 Luna `codex-exec`만 별도 transport다.
- 일일 수집은 `scripts/run-daily-lifecycle.sh --track notices|order-plans`로 트랙마다 따로 실행하며 기준일은 전일(KST)이 기본이고 공고는 4일 창·발주계획은 1일 창이다. 발주계획 트랙은 C-2 활성화와 일일 자동 실행(환경 cap `BIDOPS_C2_DAILY_TRIGGER_ENABLED` + 활성 policy 버전에 묶인 DB 스위치)이 켜지기 전에는 수집조차 하지 않는다([ADR-0060](docs/tracking/decisions/0060-c2-policy-db-row-authority.md)·[ADR-0061](docs/tracking/decisions/0061-daily-collection-window.md)).
- C-2 policy 활성 정본은 DB 행이다. 활성화와 일일 자동 실행 스위치는 관리 화면 `/order-plan-policies` 탭에서 다루고, 품질 게이트는 제품 경로를 그대로 타는 측정 전용 실행 2회와 게시일별 채점으로 판정한다. 2026-09-19에 `c2-order-plan-screening-v4`가 gold adjudicated v3 기준 게이트(recall ≥ 0.90·precision ≥ 0.35·중요 누락 ≤ 3·하루 검토량 ≤ 80, 두 pass 모두)를 통과해 활성화됐고 일일 자동 실행 스위치도 켜져 있다. 이 임계값·감사 표본 값(실행당 상한 10건, 월·목 검토)·전송 승인(binding 단위)은 **PoC용 결정**이며 운영 전환 때 다시 정한다(값과 근거는 `docs/0918_daily-operation/plan.md` 결정 표 D-a~D-e). 측정 여유가 작다(precision 36.7%, 하루 최대 검토량 79건)는 점을 품질 근거로 인용할 때 함께 적는다. v3 policy는 generation config revision 불일치로 한 번도 실행되지 못한 채 남은 행이며 되살리지 않는다.
- GPU 휴지(`BIDOPS_GPU_BUSY_LIMIT_SECONDS`·`BIDOPS_GPU_REST_SECONDS`)는 기본값이 둘 다 0(꺼짐)이며 값을 주지 않으면 기존 워커 동작과 같다. 운영은 `env/c2.env`에서 600초 사용·300초 휴지로 켜 두었고, 휴지는 작업 사이에서만 들어간다.
- 첨부 취득 실패·묶음 failed 재시작 화면, 입찰 delta 계산 worker, deep-review-v2 역할별 모델 분석, SSO, 알림은 아직 구현 전이다. 문서 준비 화면과 개요 run 실행기·REST·화면은 구현돼 있다. 입찰 delta는 저장·REST·화면까지 있으나 비교를 실제로 계산하는 worker가 없어 `bid_delta_comparison`이 `pending`에 머문다.

## 운영 변경·배포 시 유의

2026-09-19 PoC 배포·게이트·시운전에서 실제로 걸린 것만 적는다. 절차 전문은 `docs/operations.md`, 증상별 기록은 `docs/engineering-notes.md`가 정본이다.

- **운영 변경은 직전에 사람 확인을 받는다.** 재배포, migration, 실제 모델 호출, policy 활성화·retire, cron 설치가 해당한다. 앞 단계의 승인은 다음 단계로 이어지지 않는다. 사람이 "화면에서 했다"고 한 조작은 다음 단계 전에 서버 상태(예: `GET /api/order-plan-screening/daily-trigger`)로 확인한다 — 확인 창을 끝까지 제출하지 않으면 기록이 남지 않는다.
- **운영 DB 행을 SQL로 고치지 않는다.** 활성화·retire·스위치·게이트·evaluation은 감사 기록이 남는 화면·REST·CLI(`python -m app.screening.c2_policy ...`)로만 바꾼다(ADR-0060).
- **policy·binding·generation config 파일은 버전+sha256으로 고정된 immutable 파일이다.** 값 하나라도 바꾸려면 새 버전을 발행하고 compose 마운트와 `app/core/config.py` 기본 경로를 함께 올린다. 실패한 옛 버전의 행·게이트·실행은 흔적으로 남긴다.
- **발행 전에 워커 검증을 건식으로 통과시킨다.** binding `model_digest` = generation config `model_revision` = 서버 선언 revision(`BIDOPS_VLLM_MODEL_REVISION`)이 모두 같아야 한다. 어긋나면 워커가 `binding_mismatch`로 실행을 거부하고, 그때는 재발행 말고 길이 없다.
- **운영 compose는 파일 5개 + env 파일 4개 조합이다**(`.env`·`env/model.env`·`env/prespec-attachment.env`·`env/c2.env`, 기반+edge+model-egress+prespec-attachment+c2-order-plan, `--profile prespec`, `COMPOSE_PROJECT_NAME=bidops`). 서비스 교체는 `up -d --no-deps --no-build --force-recreate <services>`로 하고, 올린 뒤 `docker compose config`나 컨테이너 env로 플래그가 실제로 렌더됐는지 본다. `env/*.env`는 gitignore라 새 환경에서는 직접 만들어야 한다. 셸 주입에 기대는 값은 env 파일로 옮긴다.
- **배포 전에 전체 백업과 롤백 태그를 남긴다**(`backups/postgres/full/`, `before-<작업>-<날짜>` 태그). migration head를 배포 기록에 적는다.
- **회차 Run의 기본키는 `<디렉터리>--<generated_at>Z`다.** `GET /api/runs/{id}`만 디렉터리 이름을 풀어 주고 C-2 API는 정규 id만 받는다. 스크립트·도구는 적재 뒤 web에서 정규 id를 받아 쓰고, 한 디렉터리에 Run 행이 둘 이상이면 추정하지 않고 멈춘다.
- **적재 경고가 하나라도 있으면 그 회차의 C-2 실행은 409 `source_run_incomplete`로 막힌다.** 적재 직후 `GET /api/runs/<회차>/warnings`를 본다. 적재 CLI와 web은 같은 lifecycle 확장점을 등록해야 한다 — 진입점을 새로 만들면 `BIDOPS_MODULES` 확장점 등록을 같이 넣는다.
- **host에서 도는 `scripts/*.sh` 변경은 컨테이너 재배포가 필요 없다.** 대신 cron과 같은 깨끗한 환경(`env -i HOME=… PATH=…`)에서 `--dry-run`과 실제 web 조회를 한 번 돌려 본다.
- **cron은 `flock`(두 트랙 공용 lock)과 `timeout`을 붙여 설치하고, 설치 전에 같은 명령으로 감독 시운전을 한 번 한다.** 자동 따라잡기는 없다 — 빠진 날은 `--date`·`--from-date/--to-date`로 사람이 메운다. `대기`로 굳은 실행은 제품 워커가 복구하지 않는다(findings).
- **10분을 넘는 실행은 분리해서 돌린다**(`setsid nohup … > log; echo exit=$? >> log`). 로그를 감시하되 진행·실패·종료 코드를 모두 잡는 필터를 쓴다. 조용함은 성공이 아니다.
- **origin push와 브랜치 삭제는 요청이 있을 때만 한다.**

## 테스트 방향

- **가짜 서버는 실제 계약에서 파생한다.** 스크립트 테스트의 가짜 web·가짜 모델 서버를 고치거나 새로 만들 때는 실제 서비스 응답을 한 번 확인해 맞추고, **옛 코드가 그 가짜에서 실패하는 것**을 먼저 본다. 가짜가 결함과 같은 가정을 품으면 테스트 전체가 결함을 굳힌다(디렉터리 이름을 `source_run_id`로 받아 주던 가짜 web이 그랬다).
- **가짜로는 증명되지 않는 경로를 구분해 적는다.** 생성(202)→폴링→후속 호출처럼 여러 서비스를 가로지르는 경로는 실제 스택에서 한 번 돌기 전까지 "검증됨"이라고 쓰지 않는다. 운영 자동화는 감독 시운전 1회가 그 증거다.
- **응답 shape를 바꾸면 PostgreSQL 변형까지 돌린다.** 개별 파일만 지정하면 PostgreSQL 테스트가 skip되므로, 일회용 `postgres:17.11` 컨테이너와 `BIDOPS_TEST_POSTGRES_URL`로 해당 파일을 돌린다. strict dict 기대값은 postgres 전용 테스트에만 있을 수 있다.
- **같은 기능의 진입점이 여럿이면 진입점마다 검사한다.** CLI·web·worker가 같은 확장점·설정을 읽는지 진입점별 테스트를 둔다(`tests/app/test_ingest_cli_extensions.py`).
- **위임 결과는 리더가 영향 범위 검사를 직접 돌려 받는다.** 작업자의 "통과" 보고에는 skip된 변형이 빠져 있을 수 있다.
- **운영 자동화(cron·스케줄러)를 켜기 전에는 독립 검증을 거친다.** 구현에 관여하지 않은 컨텍스트가 코드·스크립트·실제 환경을 읽고 차단/주의로 나눠 보고하며, 차단이 0이 된 뒤에 설치한다.
- **품질 게이트 채점은 제품 밖에서 한다.** `scripts/score-c2-gate.py`가 gold·manifest·측정 실행 id·도구 sha256으로 `scoring_input_sha256`을 고정하고, 사람이 evaluation을 제출한다. gold를 고치면 새 adjudicated 버전 디렉터리를 만들고 옛 버전은 그대로 둔다.

## 문제 보고

첨부 원문의 허용 경로 이탈, API 키·회사자료의 로그나 응답 노출, 승인 없는 외부 모델 전송, 회차 원본 또는 기존 리뷰 덮어쓰기, 원문과 다른 모델 근거의 검증 통과를 발견하면 관련 실행을 중지하고 즉시 보고한다. 현재 범위에서 해결할 수 없는 구조 문제는 재현 조건, 영향, 지금 해결할 수 없는 이유, 후속 방향을 `docs/tracking/findings.md`에 기록한다.

<!-- ASTRYX:START -->
Astryx v0.5.2 · 90+ components
CLI: run every command as `npx @astryxdesign/cli <cmd>` (shown below as `astryx ...`).

SETUP (once, in your app entry e.g. main.tsx) — without these, components render unstyled:
  import "@astryxdesign/core/reset.css";
  import "@astryxdesign/core/astryx.css";

WORKFLOW — discover, don't guess. Before writing UI:
1. `astryx build "<idea>"` — START HERE: returns a kit (closest [page] + [block]s + [component]s). No args = full playbook.
2. `astryx template <name> [--skeleton]` — scaffold the [page]/[block]s it named, or study their layout. Templates are reference code.
3. `astryx component <Name>` — props + examples for every component you use.

RULES:
- No <div> — components do all layout/spacing, page frame included.
- Frame first: read `astryx docs layout` before writing any page or screen — page frame, region widths, breakpoint behavior.
- Dense data = rows (Table, List/Item), never Card-wrapped list items; Card is for standalone widgets. Status = StatusDot/Token; Badge = counts only.
- Custom styling: component props first; else style/className with tokens — var(--color-*|--spacing-*|--radius-*). No raw hex/px. (No StyleX/Tailwind compiler here — don't use xstyle/utility classes.)
- Tokens for every value (`astryx docs tokens`). Brand/accent belongs in the theme (`astryx theme list` / `theme add <slug>`, or `astryx theme template` for a custom one) — never override --color-* in :root.
- SELF-CHECK before you finish: re-read the file and replace any raw <div>/<span> layout, imported .css/@apply, or hardcoded value (#hex, 16px) with the component or a token (var(--color-*|--spacing-*|…)). If unsure a component/prop exists, run `astryx component <Name>` / `astryx search "<thing>"`; don't hand-roll CSS.

MORE CLI:
  search "<query>"   find any component / hook / doc / template / block
  component --list   90+ components by category
  template --list    page + block recipes
  docs <topic>       browser-support, cli-integrations, color, elevation, getting-started, icons, illustrations, internationalization, layout, migration, motion, principles, shape, spacing, styling-libraries, styling, theme, tokens, typography, working-with-ai
  swizzle <Name>     eject component source for deep customization
  upgrade --apply    run after any @astryxdesign/core bump
<!-- ASTRYX:END -->
