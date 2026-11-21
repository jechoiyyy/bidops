# 2026-11-21 분석 엔진 패키지 동기화 배포 기록

분석 엔진 패키지(`packages/bid-deep-engine`)를 원본 `bid-deep-agent`의 커밋 `f69f8cfc08a9059747ec8278c65b77c6194dc8d1`로 맞추고, 사전규격 상세 분석 완료 화면(mock 빌드 전용)이 새 필드를 읽게 한 변경을 운영에 반영한 기록이다. DB migration·정책·기능 스위치 변경은 없다. 엔진 경로는 `mock_reference` 그대로이고 live 전송 승인은 없다. 코드 배포는 기능 활성화나 품질 합격이 아니다.

## 운영에서 달라지는 것

화면과 동작에서 달라지는 것은 없다. 운영은 엔진 스위치가 꺼져 있고(`engine_analysis:false`) 분석 완료 화면은 운영 번들에 들어가지 않는다. 이미지 안의 엔진 패키지만 새 원본 커밋으로 바뀌었다.

## 승인

- 2026-11-21 사용자(jechoi): 작업 브랜치 커밋 뒤 "병합해주고 운영에 반영도 해줘". origin 푸시는 요청받지 않아 이 작업에서는 실행하지 않았다(아래 소스 행 참조).

## 반영 내용

| 항목 | 값 |
|---|---|
| 소스 | main `ce99c82`(작업 브랜치 `feat/engine-sync-f69f8cf`를 fast-forward 병합: `fa90d70` 엔진 패키지 동기화, `ce99c82` 분석 완료 화면). `scripts/` 변경 없음. origin/main은 18:31 KST에 `ce99c82`로 갱신돼 있었다(로컬 reflog `update by push`). 이 배포 작업이 실행한 푸시가 아니며 누가 올렸는지는 확인하지 못했다. 이 기록 커밋은 올리지 않았다 |
| 엔진 패키지 | 원본 `7ad9283` → `f69f8cf` 사이에 바뀐 파일 15개(소스 11·테스트 4)를 교체하고 `UPSTREAM.json`의 `commit`과 원본 바이트 해시 15개를 갱신했다. 해시는 원본 저장소의 `git show f69f8cf:<path>`에서 계산했다. 더해진 필드는 `Evidence.block_locations`·`block_location_status`, `RequirementFit.mandatory`, `ConfirmRequest.purpose`·`availability`이며 기존 필드는 그대로다 |
| 백엔드 | 변경 없음. `analysis`를 선별·검증하지 않고 그대로 저장·반환한다(`web/backend/app/deep_review/services/engine_runs.py`) |
| 화면 | 분석 완료 화면(mock 빌드 전용): 추적 판단용 회사 확인(`purpose=decision`)을 접지 않고 보이고, 확인 시점(`availability`)·원문에 표기된 필수/선택(`mandatory`)·쪽 없는 인용의 원문 블록 위치를 표시한다. 새 필드가 없는 응답은 전과 같다 |
| 이미지 | `bidops:main-20261121-ce99c82`(linux/amd64, `sha256:b6f5f2d541d698da3c0e9a494b06790f6748b8f4b3889da4857ce1f8c0170b69`). 커밋된 내용만으로 깨끗한 작업 트리에서 빌드했다 |
| 교체한 서비스 | `web`, `analysis-worker`, `prespec-attachment-worker`(`up -d --no-deps --no-build --force-recreate`, 18:30 KST). postgres·minio·clamav·document-worker는 건드리지 않았다 |
| 설정 | `.env`의 `BIDOPS_IMAGE` 한 줄만 바꿨다(사본과 대조해 다른 줄 동일) |
| DB | migration 없음(이번 변경에 migration 파일이 없다. head `0042_engine_run` 그대로) |
| 백업 | `backups/postgres/full/bidops-20261121T092944Z.dump`(114,530,953 B, SHA-256 `3864cd6c00be8ed8f547f25aaac671e9d7bb96bad5cf75c2e95e05b1d2b8e287`, `pg_restore -l` TABLE DATA 111개). 파일이 0644로 만들어져 0600으로 고쳤다. 외부 보존 위치로의 복사는 하지 않았다 |
| 롤백 지점 | Git 태그 `before-engine-sync-20261121`(`b60dc98`, 직전 이미지 `bidops:main-20261121-1ade4c5`), 설정 사본 `backups/env-prod-before-engine-sync-20261121`(0600). 되돌릴 때는 `BIDOPS_IMAGE`를 복구하고 같은 세 서비스를 다시 만든다 |

## 원본 엔진 쪽 작업과 인계

- 원본 수정은 Codex 세션이 `bid-deep-agent`의 로컬 브랜치 `fix/prespec-analysis-output`(`f69f8cf`)에 했다. 성남 건을 저장된 응답으로 재실행해 정확한 원문 블록이 있는 근거 0/59 → 59/59, 읽을 수 있는 제목의 확인 요청 5/63 → 63/63을 보고했다(BidOps에서 다시 돌려 보지 않았다). 물리 쪽 번호(대조할 PDF 없음)와 필수 여부(원문 표에 표기 없음)는 0건 그대로다.
- 동기화 대상 15개는 Codex의 답과 두 커밋의 직접 대조(`git diff --name-only`: 19개 변경, 그중 vendored 15개)가 일치했다. 교체한 파일이 원본 바이트를 재현하는지는 패키지의 manifest 검사가 확인한다.

## 배포 전 확인

- 실행 중인 일일 스크립트 없음, analysis-worker·첨부 worker 최근 30분 로그 0줄.
- 엔진 패키지 `engine_tests` 전체 1,497 통과(manifest 해시 대조 포함).
- 백엔드 `tests/deep_review/test_engine_runs.py`·`tests/app/test_engine_runs_api.py`를 일회용 `postgres:17.11`로 실행해 45 통과·1 건너뜀(`PostgreSQL guard`).
- 화면 `prespec-analysis-view.spec.ts` 9건 통과(새 검사 2건 포함, mock 개발 서버). 운영 빌드 통과, 빌드 결과와 이미지 안 번들에 분석 화면 표지 0건.
- 백엔드·화면 검사는 작업 폴더가 한 번 지워지기 전의 사본에서 돌렸다. 같은 절차로 다시 만든 사본에서는 패키지 검사와 운영 빌드만 다시 돌렸다.

## 배포 후 확인 (18:31 KST, GET만 사용)

| 확인 | 결과 |
|---|---|
| 컨테이너 | 세 서비스 모두 새 이미지, `restart=unless-stopped`, web `healthy`, 세 컨테이너 오류 로그 0줄 |
| postgres | 컨테이너 id와 생성 시각(`2026-11-21T06:46:09Z`)이 백업·교체 전후로 같다(백업은 `run --rm --no-deps ro-backup`). web 로그에 스레드 예외 없음 |
| `GET /api/health` | `{"status":"ok"}` |
| `GET /api/feature-flags` | `rl_analysis:false, prespec_overview:true, engine_analysis:false` (배포 전과 같음) |
| `GET /api/order-plan-screening/daily-trigger` | `effective_enabled:true`, `c2-order-plan-screening-v6`, 스위치 ON (배포 전과 같음) |
| 이미지 안의 엔진 패키지 | `UPSTREAM.json` `commit` = `f69f8cfc…`, `__pycache__` 없음 |
| `/pre-specs/3235` 화면 | 첨부 실제 파일명 2건 표시, 주 버튼 1개, 가로 넘침 없음, 분석 화면 없음, 페이지 오류 없음 |
| 다른 화면 | 사전규격 목록·대시보드가 열린다 |
| tailnet | `http://100.88.161.54:8188/pre-specs/3235` 200 (이 Mac에서 확인) |

## 남은 한계

- 엔진 스위치가 꺼져 있어 운영에서 새 패키지로 엔진 실행을 돌려 보지 않았다. mock 참조 실행 경로의 검사만 통과했다.
- 실제 엔진 결과가 분석 완료 화면으로 들어오는 연결(live 실행 승인, 회사 근거 등록, 화면 공개)은 RL-11 범위로 남아 있다.
- 교체 뒤 워커가 실제 작업을 처리하는 것은 확인하지 않았다(대기 작업 없음). 2026-11-22 아침 cron(06:30·07:00) 로그에서 확인한다.
- 원본 저장소의 `f69f8cf`는 로컬 브랜치에만 있다. 원본에서 병합·푸시되기 전에 브랜치가 지워지면 `UPSTREAM.json`의 커밋을 원본에서 찾을 수 없게 된다.
