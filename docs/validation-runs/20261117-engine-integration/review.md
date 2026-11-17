# RL-09 독립 리뷰

판정: **PASS — mock 통합 개발 기준선. 미해결 차단 0건.**

최종 추가 검증까지 종결했다. 문서 묶음 `null→ready` 전환으로 입력 중인 actor가 사라지던 결함은 수정 전 실패를 재현한 뒤 수정했다. 수정 소스 리뷰·host 관련 검사 9건·frontend build·대비 검사 8건과, 수정 image의 실제 Compose 대표 두 폭 2건이 통과했다. **mock 개발 기준선의 최종 판정은 PASS, 미해결 차단 0건이다.** 초기 기동 지연·worker 경고와 기존 품질 reject는 후속으로 유지하며 이 판정이 운영 활성화나 실제 모델 품질 인수를 뜻하지 않는다.

2026-11-17, 구현에 참여하지 않은 별도 컨텍스트에서 소스와 리더 실행 증거를 대조했다. 테스트·모델 호출·운영 변경은 실행하지 않았다. 엔진·Compose 담당자의 최종 소스 동결을 각각 확인했다. 기준은 RL-09 intent/spec/plan이며, 초기 사용자 변경 71개와 삭제 문서는 `.sdlc/integration-preservation.json`으로 구분했다. 실제 분석 품질이나 운영 활성화에 대한 합격 판정이 아니다.

## 확인한 계약

- 최종 UPSTREAM manifest 41개 원본 source/test 해시가 원본 checkout과 일치한다. 원본 그대로 또는 namespace만 바꾸었다고 선언한 제품 파일 37개도 내용 대조가 일치한다. 실제 normalizer·3단계 pipeline·gates·scoring·인용 검증·readiness를 실행하며, 원본 Claude transport·fallback·telemetry·SQLite 작업 큐·A2A/chat 운영 구조를 가져오지 않는다.
- 요청은 회사·공고·준비 완료 묶음의 식별자만 받는다. 기존 회사 binding과 고정 버전 구조 객체의 hash·소속을 검사하고 원본 순서·table·profile/graph·엔진 hash를 동결한다. 기존 WorkJob과 공용 worker 슬롯을 사용한다. 입력·완료 결과의 PostgreSQL 불변성, lease fence, versioned MinIO 결과 저장, 안전한 실패 상태를 확인했다.
- live 요청은 queue 생성 전에 거부한다. 모든 실행은 mock_reference이며 완료 후 partial/failed만 게시한다. unknown/null·미완료 projection·현재성·사람 추적/최종 결정 구분을 보존한다. 원문 경로·하위 프로세스 stderr·자격증명을 오류로 반환하지 않는다.
- 실제 회사 경로의 API/UI 연결, 동일 요청 receipt 재시도, 저장된 이력, 과거 입력 표시와 원문 근거 표시를 확인했다. 대표 실제 API 화면의 laptop 캡처도 직접 읽었다.
- 공통 selector의 dev/mock/prod project·기본 port·volume 분리, 명시적 초기화, 서비스별 egress·secret 경계, network 없는 native 문서 worker와 현재 계약 문서의 일치를 확인했다.

## 검토 중 해소한 사항

- 구조 block_key 정렬로 원문 순서가 바뀌던 경로를 고정 버전 구조 payload 순서와 table 변환으로 교체했다.
- 실제 회사 engine collection을 기존 demo middleware가 막던 문제를 정확한 경로 예외와 full-app 회귀로 수정했다.
- 0042 migration audit ID의 재업그레이드 충돌을 매 upgrade의 새 UUID로 수정해 과거 감사를 유지했다. 누락된 table inventory와 기존 공개 회사 조회에 대한 잘못된 테스트 기대도 수정했다.
- 오래된 Compose 설치 명령과 새 selector의 불일치, UI의 현재성 누락, 계약 색인 연결을 수정했다. selector 후행 전역 flag는 현재 CLI에서 거부됨을 담당자가 안전한 render로 확인했고 추가 방어도 반영했다.

## 대조한 실행 증거

- `.sdlc/engine-package-tests.log`: 원본 synthetic 회귀 512 passed. 이후 adapter 변경은 `.sdlc/engine-adapter-delta.log`의 3 passed로 검사했다.
- `.sdlc/backend-final-tests.log`의 첫 통합 검사에서 111 passed와 7개 실패를 확인했다. 실패 경로 수정 후 `.sdlc/backend-delta-tests.log`: 18 passed, 1 skipped. skip은 SQLite에서 적용할 수 없는 PostgreSQL guard이며 PostgreSQL 변형은 실행됐다. 바뀌지 않은 경로의 앞선 통과 결과를 재사용했으며 전체를 새로 검사했다고 표시하지 않는다.
- `.sdlc/make-test-config.log`: selector·배포 계약·관련 일일 스크립트 149 passed.
- `.sdlc/frontend-final-tests.log`: 6 passed. `.sdlc/frontend-final-build.log`: production build 성공.
- `.sdlc/engine-e2e/browser-representative.log`: 실제 PostgreSQL 17.11·MinIO·API·공용 worker·production UI에서 1280×800/1440×900 두 시나리오 passed. 합성 HWPX 원문과 기존 bounded extractor를 거쳐 POST 202→partial UNKNOWN·저장·재조회·새로고침을 확인했다. 초기 route/빈 fixture 실패는 최종 증거로 사용하지 않았다.
- `.sdlc/document-build.log`: native arm64 문서 image build_exit=0. 리더의 network-none 문서 entrypoint smoke도 exit 0이다. `.sdlc/web-build.log`: app image build_exit=0.
- `.sdlc/image-engine-digest.log`와 `.sdlc/source-engine-digest.log`: image의 network-none import smoke exit 0, 현재 소스와 엔진 digest `5aa39cf1e3d87caf2925776ce4bf9d08e48f55d95d0df8b6f227b97345460eba` 일치. 최종 diff whitespace 검사도 통과했다.

## 후속 범위와 한계

회사 profile projection은 명시적으로 불완전하며 기존 파서 누락·RL-05 품질 reject는 해결하지 않았다. 실제 Luna 전송·품질 재측정·정책/운영 활성화에는 별도 작업과 기존 승인 경계가 필요하다. 대표 fixture의 준비 단계는 antivirus와 native rendering을 우회하므로 해당 기능의 인수 증거가 아니다. Compose render와 image smoke를 운영 복구·volume 보존 검증으로 확대 해석하지 않는다.

추가 Compose 최초 설치 smoke는 host의 Docker 기본 address pool 소진을 개발 전용 명시 subnet으로 해결한 뒤 `make init/create/up/health`까지 통과했다. 중간 Compose 브라우저 검사는 loading/새로고침 대기에서 실패했고, 대기 시간을 늘려 합격으로 표시하지 않았다. 이후 필수 notice 응답 동기화와 별도로 확인된 actor 재마운트 결함 수정 후, 최종 수정 image에서 두 폭 모두 통과했다. 중간 실패를 처음부터 통과한 것으로 고치지 않는다. 최종 통과도 초기 기동 60초 초과·간헐 지연·worker 경고의 원인 해결 근거로 확대하지 않는다.

## 종료 동작 수정의 추가 리뷰

최초 `make down`의 `compose stop`은 비활성 profile의 개발 analysis-worker를 남겼다(`.sdlc/dev-down.log`). 리더가 수정한 Makefile의 down recipe 5줄만 추가 검토했다. **이 수정의 소스 판정도 PASS, 차단 0건이다.**

같은 `scripts/compose-env.sh`로 환경/project를 선택하고 dev/mock의 운영·데모 project 사용을 계속 거부한다. `docker ps`는 정확한 Compose project label 값으로 실행 중인 컨테이너 ID만 가져온다. 반환된 Docker ID만 중지하므로 profile과 orphan 서비스도 포함하면서 다른 project를 대상으로 넓히지 않는다. 컨테이너·network·volume 삭제는 없고 실행 중인 대상이 없으면 성공하는 기존 stop 의미를 유지한다. `.sdlc/dev-down-final.log`는 앞선 명령이 남긴 대상의 `docker stop` 완료를 기록한다. 최종 잔존 컨테이너 확인은 리더의 실행 기록을 따른다. 이 변경으로 기존 제품 테스트·image·화면 검사를 다시 시작할 필요는 없다.

## 상세 대기 안내·migration 안내의 추가 리뷰

최종 추가 요청의 두 소스 delta만 읽었다. **이 delta의 소스 판정도 PASS, 차단 0건이다.**

- UI는 선택한 run ID가 있고 detail query가 pending인 동안만 상세 로딩 안내를 표시한다. 비활성 상세 query에 의한 거짓 로딩을 막으며 실행·결과·오류 의미는 바꾸지 않는다. 새 회귀는 collection 응답은 완료시키고 detail GET만 gate로 지연한다. 응답 전에는 대기 안내와 결과 부재를 확인하고, gate 해제 후 partial 결과 및 POST 부재를 확인한다. 실제 Compose 응답 지연을 해결하거나 그 원인을 증명하는 테스트로 해석하지 않는다. 실행 결과는 리더의 `.sdlc/frontend-pending-delta.log`를 따른다.
- `core/db.py`의 MIGRATION_COMMAND는 과거 raw Compose 조합 대신 공통 selector를 타는 `make BIDOPS_ENV=<dev|mock|prod> migrate` 선택 안내를 사용한다. 환경을 선택해 실행하는 명령 안내의 변경이며 migration 실행·startup·승인 동작은 바꾸지 않는다.

후속 network probe에서는 요청 완료와 reload 뒤 결과 표시가 관측됐지만, 앞선 pending HTTP 상태와 간헐 지연의 원인은 아직 확정하지 않았다. 초기 `make up`도 60초 startup 한도를 초과한 뒤 나중에 health 200이 됐다. 로딩 안내·뒤늦은 정상 응답을 지연 원인 해결이나 60초 기동 보장의 근거로 승격하지 않는다. 앞선 검증의 통과/실패 범위는 그대로 보존한다.

## 초기 필수 응답 동기화 제안 검토

적용 전 E2E fixture 제안을 검토했다. **정확한 notice GET 완료 뒤 기존 화면 assertion을 시작하는 것은 기능 검증의 정당한 초기 상태 동기화이며 기대값 완화가 아니다.** Desktop trace를 직접 읽었으며 lazy 화면 JS는 09:44:42.182부터 543ms에 200을 받았으나 `/api/notices/1` 요청은 09:44:46.030에 시작했고 테스트 종료 때 미완료였다. 문서에 5초 화면 성능 SLA는 없으며 기존 5초 assertion은 이 경우 필수 응답에 약 1초만 남겼다.

적용 조건은 goto/reload 전에 page response waiter를 등록하고, 정확한 GET·URL pathname·notice ID를 선택하며, 응답 status와 body 완료·대상 identity를 검사하는 것이다. 최종 `loadNotice` helper는 이 조건을 충족하며 기존 전체 90초·panel 5초·partial 60초와 결과·품질 기대값을 그대로 유지한다. 실패 응답을 기다림 predicate로 숨기거나 sleep/networkidle·실패 무시로 통과시키지 않는다. 이전 60초 진단 실패·간헐 지연·기동 시간 초과는 계속 미해결로 보존한다.

## 늦은 묶음 응답의 actor 손실 수정 리뷰

수정 전 실패 증거 `.sdlc/actor-before-fix.log`와 변경한 EngineAnalysisPanel·회사 상세 진입·관련 회귀만 읽었다. **수정 delta의 소스 리뷰 PASS, 미해결 소스 차단 0건이다.** 최종 host 검사와 수정 image의 실제 연결 결과는 아래와 같다.

- normal/demo 진입 모두 component key를 company/notice로 유지하고 bundle만 제외했다. 회사·공고 전환의 격리는 유지하면서 같은 공고의 늦은 bundle 응답이 actor 초안과 pending receipt를 지우지 않는다.
- pending receipt의 UUID·actor·bundleId를 함께 동결하고 재시도에는 동결 값만 사용한다. 현재 bundle이 null로 바뀌어도 기존 receipt는 재확인할 수 있으며, receipt가 없으면 준비 완료 bundle과 actor가 필요하다. backend idempotency 범위와 일치한다.
- 실제 bundle 변화만 previous-value guard로 구분해 해당 회사/공고 list와 선택 detail을 exact invalidate한다. UI 초안을 보존하는 대신 서버의 currentness 재조회가 사라지는 회귀를 막는다.
- 새 회귀는 actor 저장소를 사용할 수 없는 정상 fallback에서 늦은 bundle 도착 뒤 초안·실행 가능 상태를 확인한다. 또 lost POST 뒤 실제 문서 준비 action으로 새 draft를 만들고, current bundle이 null이어도 UUID·actor·bundle 본문이 같은 receipt를 재시도하며 list/detail을 다시 조회하는지 확인한다. 수정 전 회귀가 실패했음을 리더가 직접 재현했으므로 결함과 같은 가정을 공유하는 통과용 fake로 보지 않는다.
- 최종 frozen receipt fixture는 기존 이력과 첫 POST로 접수된 새 실행을 서로 다른 ID로 분리한다. 첫 POST의 UUID·bundle로 receipt를 고정하고 응답을 유실시키며, 바뀐 재시도 본문/actor는 409로 거부한다. 새 receipt 선택까지 검사하므로 기존 이력을 접수 응답으로 반환하던 초기 fixture의 한계를 보정했다.

리더가 최종 fixture 소스에 실행한 결과를 직접 읽었다. `.sdlc/frontend-actor-tests.log`는 **9 passed (16.7s)**이며 기존 6건·상세 pending·actor 보존·동결 receipt 재시도를 포함한다. `.sdlc/frontend-actor-build.log`의 production build는 통과했고 기존 chunk 크기 안내만 남았다. `.sdlc/frontend-contrast.log`는 **8 passed, 0 failed**다. 리뷰어는 이 검사를 중복 실행하지 않았다.

이 수정은 actor 재마운트 결함을 대상으로 한다. 앞서 기록한 초기 응답 지연·기동 시간 초과의 원인 해결을 주장하지 않는다. 이전 검증 중 변경되지 않은 backend·engine·Compose 경로의 증거는 재사용한다.

## 최종 Compose 연결 증거와 종결

- `.sdlc/web-build.log`의 수정 app image build는 exit 0이다. image 식별자는 `sha256:89568076d340c71c920d5662077b0910e8e5d5dec261fc42b9db325342356c3a`이며 리더가 실제 web의 image ID와 일치함을 확인했다(linux/amd64). `.sdlc/final-image-smoke.log`는 현재 frontend asset과 engine import/digest 일치를 확인한다.
- `.sdlc/dev-browser-actor-fixed.log`: 실제 개발 Compose의 API·app 역할·공용 worker를 거친 **1280×800/1440×900 두 시나리오 2 passed (22.6s; 각각 11.7s/8.5s)**다. POST 202→저장된 partial/mock_reference·UNKNOWN 결과→reload 결과를 동일한 기대값으로 검사했다. 실행 전 필수 notice 본문만 동기화했으며 timeout이나 품질 조건은 늘리지 않았다.
- 리더가 실제 web의 app 역할로 두 실행의 run 전용 MinIO object_key와 고정 version을 읽고 bytes SHA-256·JSON을 PostgreSQL 결과 hash/payload와 대조했다. 결과 receipt는 `docs/validation-runs/20261117-engine-integration/compose-receipts.json`이다. 두 run은 `fcfbf970-a836-45f6-8de1-3143d291f9d1`, `29258f63-ec49-4223-8a91-37914960805e`이며 둘 다 partial/mock_reference, 동일 engine digest를 보존한다.
- `engine-compose-laptop.png`와 `engine-compose-desktop.png`를 리뷰어도 직접 읽었다. 두 폭 모두 loading shell이 아닌 저장된 결과·mock 표식·판정 유보·UNKNOWN을 표시한다. desktop 캡처는 저장 조회 뒤 partial 실행 이력이 표시된 read-only 상태다.

**최종 판정: mock 통합 개발 기준선 PASS. 이 범위의 미해결 차단은 없다.** 초기 60초 기동 지연과 유휴 worker 경고의 원인은 후속 finding으로 남으며, 원본 모델 품질 reject와 미완료 회사/문서 projection, 실제 모델 승인·품질 측정·운영 활성화는 이번 합격 범위에 포함하지 않는다.


## 2026-11-18 Docker 배치 후 공개 전 독립 검토

사용자가 승인한 대체 리뷰 모델 `gpt-6.1-sol` / high의 별도 컨텍스트가 root project-directory, Dockerfile 5개 COPY·Compose 6개 연결, 현재 운영 문서와 새 Git 후보를 읽었다. **새 차단 0건, 이동 delta PASS**. 기존 `make test-config` 154 passed·runner COPY 1 passed·5개 구성 동등성 증거를 재사용했고 검사를 중복 실행하지 않았다. 새 파일에서 자격증명·회사 원문·DB·env·raw 실행 로그를 발견하지 않았으며 PNG 4개는 합성 검증 화면이다.

비차단 문서 지적 1건(`docs/engineering-notes.md`의 삭제된 Mac overlay 참조)은 현재 edge/prod와 host 운영 문서로 수정했다. 기존 품질 reject·기동 지연·worker 경고는 계속 제한 사항이며 운영 활성화나 실제 모델 품질 합격을 주장하지 않는다.
