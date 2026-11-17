# 실행 계획

## 작업 순서

1. STEP-001 실행 구성 단순화 [complex]
   - Compose/Make/운영 스크립트·문서. 구성 렌더 및 선택/네트워크 계약 검사.
2. STEP-002 분석 패키지와 제품 adapter [complex]
   - 원본 revision 추적·큐·저장·API. 엔진/실패/unknown/승인 경계 pytest와 PostgreSQL 변형.
3. STEP-003 관리 화면과 대표 통합 검증 [complex]
   - API 소비 UI·격리 공고 1건. production build·1280/1440 화면·실제 API 연결.
4. STEP-004 독립 리뷰와 검증 정리 [complex]
   - 변경 소스·검사 결과 대조, 차단 수정, 잔여 품질 문제 명시.

## 실행 제약 및 예외

사용자가 현재 Astra/high 구현 + 사용 가능한 별도 독립 리뷰를 승인했다. 기존 runtime.codex.json의 unavailable gpt-5.6-sol 대신 이번 작업만 해당 설정을 사용한다. 기존 RL-07 active run·공통 runtime 설정은 수정하지 않는다. 사용자가 요구한 별도 worktree를 수동 생성했으며 기존 active run을 덮는 run start/finish는 실행하지 않는다. commit/merge 금지에 따라 검토 가능한 미커밋 변경으로 남긴다. 상태 도구의 기존 active run 충돌 때문에 phase는 review에 유지한다.

## 결과

패키지·버전 adapter·기존 큐/worker·불변 저장·API·관리 화면과 공통 Compose 선택기를 구현했다. 합성 HWPX 한 공고의 호스트 격리 E2E와 최종 실제 Compose E2E가 각각 두 폭 모두 통과했다. 새 폼의 입력 손실은 old-code 회귀 실패를 먼저 확인하고 수정했으며, UI 9건·대비 8건·최종 이미지 빌드를 통과했다.

검사별 결과·원본 실패·초기 실패의 분류·잔여 한계는 [검증 기록](../../../../../validation-runs/20261117-engine-integration/README.md)에 모았다. 실제 모델 품질 인수와 운영 배포/활성화는 수행하지 않았다. 기능 상태는 기존 RL-07 active run을 보존하기 위해 review에 남기되, 로컬 구현·검증 근거를 steps/proof에 기록한다.

다음 우선순위는 회사·문서 projection 완성 및 승인 Luna transport, 원본 요구사항 누락 수정과 별도 품질 재측정, 초기 기동 지연/유휴 worker 경고의 안전한 계측이다. 채팅·A2A·독립 CLI는 실제 제품 소비자를 정한 뒤 별도로 판단한다.

### 직접 확인한 출발 상태

- BidOps main `539bb8b4020394fa6020933627e31a6ac55b7537`; origin `git@github.com:jechoiyyy/bidops.git`. 71개 사용자 변경/추가/삭제를 통합 worktree에 동일하게 보존했다. 보존 해시는 `.sdlc/integration-preservation.json`(로컬)에 있다.
- 원본 `docs/showcase` `7ad9283d8e8a405074374d12c5f0a13ccb8e5b1f`; tracked 변경 8개, 그 중 제품 코드는 `analysis/claude_cli.py`, 회귀는 `tests/test_claude_cli.py`. untracked 평가/포트폴리오/산출물은 통째로 가져오지 않는다.
- 원본 저장은 RFP/facts/fits/analysis JSON 및 SQLite tasks/A2A이다. 모델은 Claude direct/gateway/CLI이며 direct fallback과 별도 Langfuse 관측 경로가 있다. BidOps의 RL Luna 승인·감사와 같지 않다.
- Make는 project bidops + base/edge, Mac script는 6개 Compose + env 4개. 루트 Compose 11개 확인. read-only Docker 목록에서 bidops와 bidops-local web 존재 확인. 현재 사용자 crontab의 활성 BidOps 행은 0개이다. 운영 상태/DB/정책의 최신성을 이 조사로 주장하지 않는다.
- 원본 기록의 reject 5/10, strict blockers 0/7과 요구사항 0건 2개를 확인했다. 현재 원본에서 `.venv/bin/python -m pytest docs/work/_runs/rl05-reeval-20261104/test_input_diagnostics.py -q --tb=no` 실행 결과는 **2 failed**(0.07s). 알려진 미수정 제품 결함이며 통합 성공으로 승격하지 않는다.
- 기존 RL-07 active run 때문에 도구가 RL-09 implementing 전이를 거부했다. 기존 run 보존을 우선하며 상태는 review에 남아 있다. 실제 작업 진행은 이 plan과 변경 소스로 확인한다. run/완료 기록 문제로 제품 구현을 중단하거나 기존 run을 덮지 않는다.
- 호스트 Python3.12 설치에서 linux/amd64 전용 lock의 wheel hash가 Mac native와 달라 설치가 거부됐다. 운영 lock은 그대로 유지하고 격리 `.venv`에 동일 버전의 native wheel을 설치했다. 이 환경 검증과 컨테이너 lock 검증은 구분한다.

- 추가 read-only inspect: 운영/데모 web 둘 다 `restarting`, health `unhealthy`. 운영은 bidops-c2mac의 6-file 조합·18788, 데모는 과거 여러 worktree의 11-file 조합·18787로 생성됐다. 로그/비밀 env는 출력하지 않았다. 현재 정상 운영으로 간주하지 않으며 이번 변경과 무관한 기존 상태로 보존한다.

### 후속: Docker 파일 배치(2026-11-18)

- 입력: 공통 선택기의 dev/mock/prod 및 dev/prod+Luna·Slack, 5개 구성의 모든 서비스(bootstrap/ops 포함). 기대: Dockerfile 경로 외 project·port·volume·network·secret·mount·플랫폼 동일. 합성 env와 `config --no-env-resolution` 전후 비교로 검사하며 실제 비밀 env나 모델을 읽지 않는다.
- 입력: 저장소 외부 및 docker 디렉터리에서 선택기 호출. 기대: 루트 build context·상대 경로 유지. `make test-config`의 구성 선택·런타임 계약 및 runner COPY 계약 검사로 확인한다.
- Dockerfile 5개·Compose 6개를 `docker/`에 모으며 root `.dockerignore`, runner 소스, env, scripts 경로는 유지한다. 이미지 내부 `/app/docker-compose.yml` snapshot 경로도 유지한다. 운영 재생성·전체 이미지 재빌드·품질 재측정은 이 경로 이동에 포함하지 않는다.
- 결과: 5개 합성 구성의 전체 서비스 렌더가 Dockerfile 경로 외 동일했다. `make test-config` **154 passed**(37.42s), runner 이미지 schema COPY 계약 **1 passed**(0.47s), `make config`와 `git diff --check` 통과. 원래 checkout의 보존 대상 71개 해시/삭제 상태도 동일하다. 이번 이동 후 전체 이미지 빌드·UI E2E는 재실행하지 않았으며 앞선 통합 검증과 구분한다.

### Git 반영 및 작업 공간 정리 승인(2026-11-18)

사용자가 commit·기존 origin push·main 병합과 나머지 worktree/브랜치 정리를 명시적으로 요청했다. 초기 commit/merge 금지의 후속 승인이다. 원래 main의 문서 정리 변경은 별도 커밋으로 보존하고 검증한 통합 트리를 main에 반영한다. RL-07 미커밋 구현과 main 밖 HP 커밋은 이번 제품 기준선에 섞지 않고 권한 제한 로컬 아카이브(tar·Git bundle)로 보존한다. 운영 `bidops-c2mac`은 컨테이너 bind source이므로 경로·worktree를 유지한다. 실제 모델·Slack·운영 재생성·migration은 승인 범위에 없다.

추가 독립 리뷰는 Docker 이동 및 새 Git 후보에 한정해 차단 0건이다([리뷰](../../../../../validation-runs/20261117-engine-integration/review.md)). 이미 통과한 제품 검사는 재실행하지 않는다. Git 반영과 SDLC 자동 run 완료·품질 인수·운영 배포는 별개로 기록한다.

반영 결과: 기존 사용자 문서 보존 `653dcf6`, 통합 구현 `00d7e59`, main 병합 `4657dfe`를 기존 origin/main에 push했다. 병합 전체 트리는 검증된 통합 커밋의 트리와 동일하다. 이후 기본 개발 경로는 `/Users/temp/orca/bidops`다. 통합/RL-07 worktree 3개와 로컬 브랜치 7개를 정리했고, 미완료 RL-07 전체 파일·main 밖 HP 커밋은 `/Users/temp/orca/bidops-worktree-archive/20261118-004032`의 hash 검증 tar와 Git bundle로 보존했다. RL-07 run은 도구로 abandoned 처리했으며 기능 완료로 표시하지 않았다. 운영 bind source인 `bidops-c2mac`과 그 브랜치, 다른 원격 브랜치는 유지했다.

개발 env·격리 Python·검증 로그를 main 경로로 옮기고 개발 web/analysis 컨테이너의 bind 경로만 재생성했다. 컨테이너 시작·migration·운영 변경은 없었다. 경로 이전 후 `make config`, 격리 Python import와 필수 증거 검사 통과. RL-09의 기존 review phase는 자동 run 완료 기록과 구분해 유지한다. 실제 모델 품질 인수·운영 배포는 계속 미완료다.
