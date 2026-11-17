# 분석 엔진 통합 검증 — 2026-11-17

통합 브랜치 `integration/deep-agent-baseline`, worktree `/Users/temp/orca/bidops-integration`.
기준 BidOps `539bb8b4020394fa6020933627e31a6ac55b7537`, 원본 엔진 `7ad9283d8e8a405074374d12c5f0a13ccb8e5b1f`.
사용자 변경 71개의 원본 보존 해시 대조는 불일치 0이며, 원본 엔진의 tracked 변경 8개도 수정하지 않았다. 가져온 코드와 제외한 로컬 변경은 패키지 `UPSTREAM.json`에 기록했다.

**로컬 mock 개발 기준선의 대표 흐름을 통과했다. 실제 모델 품질 인수·운영 배포·활성화는 수행하지 않았다.**

## 대표 흐름과 저장 증거

합성 HWPX → 기존 bounded extractor/구조 검증 → versioned MinIO·PostgreSQL 17.11 → 일반 사전규격 화면의 POST 202 → 실제 공용 analysis worker → 새 결과 저장/GET → 화면·새로고침을 확인했다.

- 호스트 API/UI 서버 + 실제 PostgreSQL/MinIO: 1280×800·1440×900 두 건 통과. [객체 검증 receipts](receipts.json), [노트북](engine-laptop.png), [데스크톱](engine-desktop.png).
- 최종 **통합 Compose** `bidops-dev:18789`: 실제 app/worker 역할과 수정 이미지로 두 폭 모두 통과(22.6초). `.sdlc/dev-browser-actor-fixed.log`.
- Compose의 최종 두 실행은 각 run 전용 object key와 고정 MinIO version을 읽어 SHA-256·JSON을 DB 결과와 대조했다. [Compose receipts](compose-receipts.json).
- [Compose 노트북](engine-compose-laptop.png), [Compose 데스크톱](engine-compose-desktop.png)을 직접 확인했다. 데스크톱 캡처는 저장 결과를 읽기 전용으로 다시 열어 목록과 상세가 모두 partial인 상태를 담았다.
- UNKNOWN·null/abstain·partial/mock_reference, 원문 인용·입력/회사/엔진 계보와 현재성을 유지한다. 추적 선택·사람 Go/No-Go를 수정하지 않는다.

## 실행한 검사

| 검사 | 결과 | 로컬 로그 |
|---|---|---|
| 원본 synthetic 단위·schema·gates + adapter |512 passed; 마지막 adapter 변경 3 passed | `.sdlc/engine-package-tests.log`, `engine-adapter-delta.log` |
| API/큐/DB migration/권한/모듈 경계 |111 통과 후 발견한 7개 실패 수정; 영향 검사 18 passed, 1 intentional SQLite PG-guard skip. PostgreSQL 변형 실행 | `.sdlc/backend-final-tests.log`, `backend-delta-tests.log` |
| Make/Compose/일일 스크립트 |149 passed; 종료 동작 변경 회귀 2 passed | `.sdlc/make-test-config.log`, `make-down-delta.log` |
| 최종 UI 의미·상태·현재성·입력 보존 |9 passed(16.7초), production build 통과, 대비 8 passed | `.sdlc/frontend-actor-tests.log`, `frontend-actor-build.log`, `frontend-contrast.log` |
| 실제 격리 API/worker/화면 |호스트 2 passed + 최종 Compose 2 passed | `.sdlc/engine-e2e/browser-representative.log`, `dev-browser-actor-fixed.log` |
| 이미지 |native arm64 문서·amd64 web·MinIO 초기화 빌드 통과. 문서 network-none --once 통과 | `.sdlc/document-build.log`, `document-entrypoint.log`, `web-build.log`, `minio-init-build.log` |
| 독립 소스·증거 리뷰 |수정 delta와 실제 결과 대조 | [review](review.md) |

최종 web container와 image ID는 `89568076d340c71c920d5662077b0910e8e5d5dec261fc42b9db325342356c3a`로 일치했다(linux/amd64). 엔진 fingerprint는 이미지·입력·현재 소스 모두 `5aa39cf1e3d87caf2925776ce4bf9d08e48f55d95d0df8b6f227b97345460eba`다. frontend stage는 `$BUILDPLATFORM`에서 dist만 만들며 Node/node_modules는 runtime으로 복사하지 않는다.

## 실패의 분류와 수정

- 제품: 새 migration 감사 ID 형식/재적용 충돌, 실제 앱 demo middleware의 새 API 차단, table inventory를 수정하고 PostgreSQL 포함 영향 검사를 통과했다. 기존 감사 행과 제약을 유지했다.
- 제품: 늦은 문서 묶음 GET이 폼 key를 바꿔 **입력 도중 actor DOM을 교체**했다. trace로 확인하고 저장 불가 환경의 old-code 회귀 1 failed를 먼저 확인했다(`actor-before-fix.log`). 회사/공고 단위 key, frozen request/actor/bundle 재시도, bundle 변경 현재성 재조회로 수정했다. 새 draft 생성 후 동일 receipt 재확인까지 최종 9건에서 검사했다.
- 검사 환경/fixture: preview의 localhost IPv6와 검사 IPv4 bind 불일치를 수정했다. 실제 notice GET이 lazy 파일 뒤에 시작하므로, 정확한 GET의 200·본문·notice ID 완료를 기다린 다음 기존 UI assertion을 적용했다. 독립 리뷰를 거쳤으며 전체 90초·panel 5초·partial 60초 제한과 품질/결과 기대값은 바꾸지 않았다.
- 초기 Compose 실패(`dev-browser-complete.log`, `dev-browser-final-image.log`, `dev-browser-synchronized.log`)를 보존한다. 최초 임의 timeout 증가·trace 비활성 진단은 인수 근거가 아니며 최종 검사에는 남기지 않았다. 최종 성공은 위 제품 수정·명시적 상태 동기화 후의 별도 실행이다.
- 환경: Docker 기본 address pool 소진 때문에 최초 init이 실패했다. 기존 32개 network나 daemon 설정을 변경하지 않고 host route/network와 겹치지 않는 `10.253.240.0/20` 중 개발 network별 `/24`만 생성했다. 이후 `make init/create/up/health`를 통과했다.
- `make down`이 profile worker를 남기던 문제를 정확한 project label의 전체 실행 컨테이너 중지로 고쳤다. 컨테이너·network·volume 삭제는 없다.

## 유지한 한계와 후속

원본 엔진 평가 reject 5/10·엄격 차단 0/7과 요구사항 0건 문서 2개를 유지한다. 원본 진단 테스트는 현재도 2 failed다. BidOps의 별도 RL-05 기록(3/10·0/7)과 혼합하거나 통합 성공으로 승격하지 않는다.

실제 Luna 승인 transport, 전체 회사/문서 projection, 원본 파서 누락과 품질 재측정은 후속이다. HWPX 추출은 기존 실제 코드지만 이 fixture는 바이러스 검사·native PDF 렌더링을 우회하므로 그 단계의 인수 근거가 아니다. CLI/A2A/chat·원본 SQLite task DB·Claude fallback/telemetry는 이식하지 않았다.

초기 host 고부하(load average 약 90/132/112), 재기동 60초 초과 뒤 health 정상화, 초기 유휴 worker의 `worker.job_failed`는 원인 미확정으로 [진단 기록](../../tracking/findings/operations.md#2026-11-17-통합-개발-compose의-응답-대기와-worker-경고)에 남긴다. 최종 기능 검사가 통과해도 운영 성능/안정성 문제를 해소 처리하지 않는다.

호스트 Python은 linux/amd64 wheel lock과 달라 격리 venv에 동일 버전 native wheel을 사용했다. 운영 lock의 hash 검사는 유지했으며 실제 컨테이너 빌드로 별도 검증했다.

운영/데모 web은 최초 읽기 전용 조회부터 restarting/unhealthy였고 활성 BidOps cron은 0행이었다. 이번 작업은 운영 복구·정책 재확인이 아니다. 실제 모델·Slack·운영 변경·cron·commit/merge/push는 없다. 검증용 서버와 개발 컨테이너는 종료하고 volume·데이터·이미지·env는 보존한다. 이 checkout에서 `make up`으로 개발 컨테이너를 다시 시작할 수 있다.
