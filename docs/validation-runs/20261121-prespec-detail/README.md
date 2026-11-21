# 2026-11-21 사전규격 상세 재구성 배포 기록

사전규격 상세 화면 재구성(ADR-0076 결정 13, 시안·기획 [`docs/1121_prespec-detail/`](../../1121_prespec-detail/README.md))을 운영에 반영한 기록이다. 프런트 변경만 있고 DB migration·정책·기능 스위치 변경은 없다. 코드 배포는 기능 활성화나 품질 합격이 아니다.

## 승인

- 2026-11-21 사용자(jechoi): 시안 승인 → "최종 완료되면 푸쉬해주고, 운영에도 적용해줘" → 실행 직전 확인에서 "main 전체 푸시", "web과 워커 모두 교체" 선택.

## 반영 내용

| 항목 | 값 |
|---|---|
| 소스 | main `620c343` (`363b3c5` 구현, `0803aaf` 문서, `620c343` 시안·기획). origin 푸시 `4425744..620c343`(커밋 92개, 이전에 올리지 않은 89개 포함) |
| 이미지 | `bidops:main-20261121-620c343`(linux/amd64, `sha256:6ef8694f8837ca0fce21635555f5ce73725757bfb7316aafcb2e24920832d908`). 커밋된 내용만으로 빌드했다(깨끗한 작업 트리 `/Users/temp/orca/bidops-wt-prespec-detail`에서 `docker build --platform linux/amd64 -f docker/Dockerfile`). 운영 checkout의 미커밋 `scripts/runtime-privileges.sql`은 넣지 않았고, 직전 운영 이미지도 커밋본이었음을 대조로 확인했다 |
| 교체한 서비스 | `web`, `analysis-worker`, `prespec-attachment-worker` (`up -d --no-deps --no-build --force-recreate`, 15:48 KST). postgres·minio·clamav·document-worker는 이 명령으로 건드리지 않았다 |
| 설정 | `.env`의 `BIDOPS_IMAGE` 한 줄만 바꿨다(다른 줄은 사본과 대조해 동일) |
| DB | migration 없음(head `0042_engine_run` 그대로) |
| 백업 | `backups/postgres/full/bidops-20261121T064615Z.dump`(114,530,953 B, mode 0600, SHA-256 `836f7f0b7178d6d9a89c29809de8ad0a315d0e3da7247c333d232cc36ec31be5`, `pg_restore -l` TABLE DATA 111개). 외부 보존 위치로의 복사는 하지 않았다 |
| 롤백 지점 | Git 태그 `before-prespec-detail-20261121`(`b839367`, 직전 이미지 `bidops:main-20261120-b839367`), 설정 사본 `backups/env-prod-before-prespec-detail-20261121`(0600). 되돌릴 때는 `BIDOPS_IMAGE`를 복구하고 같은 세 서비스를 다시 만든다 |

## 배포 중 일어난 일 (계획에 없던 것)

- **백업 명령이 DB 컨테이너를 다시 만들었다.** 15:46:09 KST `scripts/compose.sh run --rm ro-backup`이 의존 서비스 `bidops-postgres-1`을 재생성했다. 정상 종료 뒤 약 1초 만에 접속 가능했고 데이터 volume은 그대로다. 원인은 확인하지 못했다(설정 차이로 인한 compose의 의존 서비스 재생성으로 추정).
- **그 순간 web의 선별 큐 스레드가 죽었다.** `Exception in thread bidops-screening-worker`(`QueueDatabaseError`). 이 스레드는 다시 뜨는 경로가 없다. analysis-worker와 첨부 worker는 `job_failed`를 한 줄씩 남기고 계속 돌았다. 약 3분 뒤 web을 새 이미지로 교체하면서 스레드가 다시 떴고, 교체 뒤 세 컨테이너의 오류 로그는 0줄이다.
- 재현 조건과 후속 방향은 [findings](../../tracking/findings/operations.md#백업-실행이-db-컨테이너를-다시-만들고-db가-끊기면-web의-선별-큐-스레드가-죽은-채-남는다-2026-11-21-미해결)에 남겼다.

## 배포 전 확인

- 실행 중인 일일 스크립트 없음, analysis-worker·첨부 worker 최근 60분 로그 0줄, 사전규격 앞 200건에 개요 대기·실행 중 상태 없음.
- 프런트 검사(리더 실행): `npm run build` 통과, `test:contrast` 8건 통과, 화면 검사 전체 948 통과·10 실패·16 건너뜀. 실패 10건은 변경 전 `b839367`에서도 같은 10건이 실패한다. `mock-review-prototype.spec.ts`는 수집 단계에서 깨져(변경 전부터) 실행에서 뺐다. 상세는 시안·기획 문서의 "구현과 검증" 절.

## 배포 후 확인 (15:49 KST, GET만 사용)

| 확인 | 결과 |
|---|---|
| 컨테이너 | 세 서비스 모두 새 이미지, `restart=unless-stopped`, web `healthy` |
| `GET /api/health` | `{"status":"ok"}` |
| `GET /api/feature-flags` | `rl_analysis:false, prespec_overview:true, engine_analysis:false` (배포 전과 같음) |
| `GET /api/order-plan-screening/daily-trigger` | `effective_enabled:true`, `c2-order-plan-screening-v6`, 스위치 ON (배포 전과 같음) |
| 이미지 안의 번들 | 분석 화면 문자열 0건, 새 화면 표식(`page-footer`·`ps-decision-bar`) 있음 |
| `/pre-specs/3753` 화면 | 구역: 사실 줄 → 사업 개요와 주요 과업 → 원문·첨부 1건 → 처리 상태·기술 정보(닫힘). 본문 1,268px(배포 전 5,494px), 개요 시작 303px, 개요 문장 10개 중 1440에서 7개·1280에서 5개가 첫 화면, 주 버튼 1개, 가로 넘침 없음, 분석 화면 없음. 캡처 [`pre-spec-3753-1440.png`](pre-spec-3753-1440.png), [`pre-spec-3753-1280.png`](pre-spec-3753-1280.png) |
| 다른 화면 | 사전규격 목록·발주계획·사업기회·대시보드가 열리고 하단 슬롯 높이 0, 페이지 오류 없음 |
| tailnet | `http://100.88.161.54:8188/pre-specs/3753` 200 (이 Mac에서 확인) |

## 남은 한계

- 하단 결정 띠에서 실제 추적 결정을 저장해 보지 않았다(운영 데이터에 쓰기를 하지 않음). 저장 동작은 mock fixture 검사로만 확인했다.
- 캡처한 브라우저에는 담당자 이름이 없어 띠가 "사이드바에서 이름 입력하기"를 보이는 91px 상태였다. 이름이 있을 때의 73px 상태는 mock에서만 확인했다.
- 분석 완료 화면은 mock 빌드 전용이라 운영에서 확인할 대상이 아니다.
- 교체 뒤 워커가 실제 작업을 처리하는 것은 확인하지 않았다(대기 중인 작업이 없었다). 2026-11-22 아침 cron(06:30·07:00) 로그에서 확인한다.
- 픽셀 기준선은 갱신하지 않았다.
