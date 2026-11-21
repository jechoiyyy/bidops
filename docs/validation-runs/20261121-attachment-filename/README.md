# 2026-11-21 첨부 실제 파일명 표시 배포 기록

사전규격 상세 '원문·첨부' 표가 `첨부 1`·`첨부 2` 대신 서버가 아는 실제 파일명을 보이게 한 변경을 운영에 반영한 기록이다. 백엔드 응답 필드 추가와 화면 표시 변경이며 DB migration·정책·기능 스위치 변경은 없다. 코드 배포는 기능 활성화나 품질 합격이 아니다.

## 배경

- 나라장터 사전규격 API는 첨부를 주소(`specDocFileUrl1~5`)로만 주고 파일명 필드가 없다. 수집기가 순번으로 `첨부 N`을 채운다(`skills/bidops-collect/scripts/collect_notices.py`).
- 실제 파일명은 원문을 내려받을 때 응답 헤더에서 얻어 문서 version(`document_version.original_filename`)에 남는다. 화면은 첨부 행의 `name`만 읽어 자리표시자가 그대로 나왔다(이번 상세 재구성 전부터 같았다).

## 승인

- 2026-11-21 사용자(jechoi): "서버랑 백엔드에서는 파일 명을 알고 있을 때는 파일명을 표시할 수 있도록 해줘" → 구현 뒤 운영 반영 계획(커밋·병합·푸시 → 백업·롤백 태그 → 이미지 빌드·세 서비스 교체 → 확인·기록)을 한 번에 제시 → "운영 반영계획 진행해줘".

## 반영 내용

| 항목 | 값 |
|---|---|
| 소스 | main `1ade4c5`(작업 브랜치 `fix/prespec-attachment-filename`을 fast-forward 병합, origin 푸시 `28812d5..1ade4c5`). `scripts/` 변경 없음 |
| 변경 | `AttachmentResponse.acquired_file`(`{filename, file_ext?, size_bytes?}` 또는 `null`) 추가. 짝은 `document_version.attachment_id`의 현재 version이고 순번·주소·이름으로 추정하지 않는다. 첨부 행의 `name`·`file_ext`·`size_bytes`는 바꾸지 않는다. 화면은 `acquired_file`이 있으면 그 값을, 없으면 목록 값과 "미확인"을 보인다. 계약은 `docs/contracts.md` |
| 이미지 | `bidops:main-20261121-1ade4c5`(linux/amd64, `sha256:debf1fea7e7c4b51a217aaf31d214b427015711f3d346f01b9b94ae9f7e278d7`). 커밋된 내용만으로 깨끗한 작업 트리에서 빌드했다 |
| 교체한 서비스 | `web`, `analysis-worker`, `prespec-attachment-worker`(`up -d --no-deps --no-build --force-recreate`, 17:32 KST). 워커 동작은 바뀌지 않았고 이미지를 하나로 맞추려고 함께 교체했다. postgres·minio·clamav·document-worker는 건드리지 않았다 |
| 설정 | `.env`의 `BIDOPS_IMAGE` 한 줄만 바꿨다(사본과 대조해 다른 줄 동일) |
| DB | migration 없음(head `0042_engine_run` 그대로) |
| 백업 | `backups/postgres/full/bidops-20261121T083104Z.dump`(114,530,953 B, mode 0600, SHA-256 `f354b1870cb002a49de73139609d2e16f923504438e0e46673a34670fb94f603`, `pg_restore -l` TABLE DATA 111개). 외부 보존 위치로의 복사는 하지 않았다 |
| 롤백 지점 | Git 태그 `before-attachment-filename-20261121`(`28812d5`, 직전 이미지 `bidops:main-20261121-620c343`), 설정 사본 `backups/env-prod-before-attachment-filename-20261121`(0600). 되돌릴 때는 `BIDOPS_IMAGE`를 복구하고 같은 세 서비스를 다시 만든다 |

## 백업 절차 보완 확인

같은 날 앞선 배포에서 `compose.sh run --rm ro-backup`이 postgres 컨테이너를 재생성했다([findings](../../tracking/findings/operations.md)). 이번에는 `BIDOPS_ENV=prod scripts/compose.sh run --rm --no-deps ro-backup`으로 실행했다. 백업은 정상 종료했고, postgres 컨테이너의 id와 생성 시각(`2026-11-21T06:46:09Z`)이 실행 전후로 같으며 web 로그에 스레드 예외가 없다. 한 번의 관측이며 재생성 원인 자체는 여전히 확인하지 못했다.

## 배포 전 확인

- 실행 중인 일일 스크립트 없음, analysis-worker·첨부 worker 최근 30분 로그 0줄.
- 백엔드: 영향받는 테스트 12개 파일을 일회용 `postgres:17.11`로 실행해 167 통과·2 실패. 실패 2건(`tests/deep_review/test_prespec_e2e.py`)은 변경 전 main `28812d5`에서도 같은 2건이 실패한다.
- 화면: `prespec-briefing.spec.ts`·`prespec-detail-layout.spec.ts` 16건 중 15 통과. 실패 1건(운영 번들에 분석 화면이 없는지 검사)은 빌드 출력 경로를 절대 경로로 준 실행 환경 문제이며, 같은 표지를 빌드 결과와 이미지 안 번들에서 직접 찾아 0건임을 확인했다.

## 배포 후 확인 (17:33 KST, GET만 사용)

| 확인 | 결과 |
|---|---|
| 컨테이너 | 세 서비스 모두 새 이미지, `restart=unless-stopped`, web `healthy`, 세 컨테이너 오류 로그 0줄 |
| `GET /api/health` | `{"status":"ok"}` |
| `GET /api/feature-flags` | `rl_analysis:false, prespec_overview:true, engine_analysis:false` (배포 전과 같음) |
| `GET /api/order-plan-screening/daily-trigger` | `effective_enabled:true`, `c2-order-plan-screening-v6`, 스위치 ON (배포 전과 같음) |
| `GET /api/notices/3235` | 첨부 9788 `name="첨부 1"` → `제안요청서(온(On)시스템 고도화 및 유지보수).hwpx`·HWPX·1,518,854 B, 첨부 9789 `name="첨부 2"` → `의견서(사전규격공개).hwpx`·HWPX·25,559 B |
| `GET /api/notices/3753` | 첨부 11548 `name="첨부 1"` → `제안요청서.hwpx`·HWPX·1,505,550 B |
| `/pre-specs/3235`·`/pre-specs/3753` 화면 | 표에 실제 파일명과 `HWPX · 크기`가 나온다. 주 버튼 1개, 가로 넘침 없음, 페이지 오류 없음. 캡처 [`pre-spec-3235-1440.png`](pre-spec-3235-1440.png) |
| 다른 화면 | 사전규격 목록·대시보드가 열린다 |
| tailnet | `http://100.88.161.54:8188/pre-specs/3235` 200 (이 Mac에서 확인) |

## 남은 한계

- 아직 원문을 내려받지 않은 첨부는 계속 `첨부 N`·"확장자 미확인 · 크기 미확인"이다(운영에서 그런 건의 화면은 따로 열어 보지 않았고 mock 검사로 확인했다).
- 표의 `다운로드` 링크는 나라장터에서 받은 원문에 대해 404다(`/api/attachments/{id}/download`는 수동 등록 파일 위치만 본다). 이번 변경 전부터 있던 문제이고 고치지 않았다. `원본 열기`는 나라장터 주소로 간다.
- 입찰공고 상세의 첨부 이력 패널은 바꾸지 않았다(입찰공고는 API가 파일명을 준다).
- 교체 뒤 워커가 실제 작업을 처리하는 것은 확인하지 않았다(대기 작업 없음). 2026-11-22 아침 cron(06:30·07:00) 로그에서 확인한다.
