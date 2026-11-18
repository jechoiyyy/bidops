# 2026-11-18 Mac 운영 스택 main checkout 이전과 main 배포 (`4425744`)

- 승인: 2026-11-18 사용자 결정 "mac에서만 운영을 진행할거야"를 받아 데모 종료·`.env` 운영 전환과 "경로 이전 + main 배포"를 고른 뒤, 계획 P1~P8을 일괄 승인했다. 모델 completion 호출, cron, origin push, C-2 정책·스위치 변경은 범위 밖이다.
- 대상: compose 프로젝트 `bidops`. 작업 트리를 `/Users/temp/orca/bidops-c2mac`(`feat/c2-litellm-mac`, `b8005ef`)에서 main checkout `/Users/temp/orca/bidops`(`4425744`)로 옮겼다. volume(`bidops_*`)은 그대로 이어 받았다.

## 반영 전 상태

| 항목 | 값 |
|---|---|
| 운영 | 10-28 이후 정지. postgres·minio·clamav·worker는 restart 정책 `no`라 host/OrbStack 재시작 뒤 올라오지 않았다. web(`unless-stopped`)만 `postgres` 이름 해석 실패로 1,683회 재시작 중이었다 |
| 코드·이미지 | `b8005ef`, `bidops:rl-20261019`(amd64)·`bidops:document-arm64-rl-20261019`(arm64) — 롤백용으로 보존 |
| Alembic | `0041_proposal_draft` |
| C-2 | `c2-order-plan-screening-v5`(`1e6d4ef1…`) 활성, 일일 스위치 ON |
| 데모 | `bidops-local`(`:18787`)은 main checkout의 `.env`를 썼고 web만 재시작 반복 |

## 단계와 결과

| 단계 | 결과 |
|---|---|
| P1 데모 종료 | `bidops-local-web-1` stop. 나머지 데모 컨테이너는 이미 정지 상태였다. volume·이미지는 보존했다. 데모 `.env`는 `backups/env-demo-local-20261118`(0600)에 보관 |
| P2 백업 | 운영 postgres만 기동해 owner `pg_dump -Fc`를 받았다: `backups/postgres/full/bidops-20261117T160126Z.dump`(59,819,676 B, sha256 `80692093e8dec6669f6953a22658de786ddd6fc2294d4b80fb60d7d1fe08034c`, `pg_restore --list` TABLE DATA 110 = 테이블 110). MinIO는 정지한 뒤 volume 전체를 cold tar로 받았다: `backups/objects/minio-data-before-ops-main-20261118.tar`(1,784,123,904 B, sha256 `ba73689cb5b94d2199de573618eb7555118c920212d8886a9e844487e9503df6`, 항목 7,602). 운영 env 4개 사본은 `backups/env-before-ops-main-20261118/`(0700/0600). 롤백 태그 `before-ops-main-20261118` = `b8005ef`(로컬 태그) |
| P3 이전 | c2mac의 `.env`·`env/{model,c2,prespec-attachment}.env`를 main으로 복사했다(대상에 같은 이름의 파일 없음). `backups/`와 `data/runs`의 gitignore 회차 파일 69개는 `rsync --ignore-existing`으로 옮겼고, 이후 diff에서 누락·불일치 0건이었다. C-2 승인 입력(`review-inputs/company`·`prompts`)은 원래 main 경로에 있었으며 c2mac 사본과 같았다. `.env`의 이미지 태그만 `bidops:main-20261118`·`bidops:document-arm64-main-20261118`로 바꿨다 |
| P4 이미지 | `BIDOPS_ENV=prod make build`는 실패했다. bootstrap 대상(postgres-init·migrate)이 arm64로 빌드돼 `argon2-cffi-bindings` aarch64 wheel의 hash가 lock과 맞지 않았다(findings). 이 실패 때문에 web 빌드도 취소됐다. 두 서비스는 web과 같은 이미지 태그를 쓰므로 `scripts/compose.sh build web`으로 amd64 app 이미지(`3fb99764…`)를 만들었다. 문서 worker는 arm64(`cb387aa4…`, rhwp 포함)다. 오프라인 컨테이너에서 `import app.main`과 0042 revision 포함을 확인했다 |
| P5 리허설 | 일회용 `postgres:17.11`(amd64, `--network none`, 새 임의 비밀번호)에서 진행했다. postgres-init → schema drop → dump 복원(exit 0, 0041) → 새 이미지 `migrate.sh`로 0041→0042를 통과했다. `alembic check`는 `PGOPTIONS='-c search_path=public'`로 실행해 "No new upgrade operations detected"를 받았다(빈 DB에서 migrate한 대조군도 같다). 행 수는 `engine_run` 0행 추가와 `screening_audit_event` 36→37(migration 표식) 말고는 110개 테이블 모두 같았다. 일회용 컨테이너·비밀번호 파일은 삭제했다 |
| P6 교체 | main에서 `BIDOPS_ENV=prod scripts/compose.sh run --rm --no-deps migrate`(exit 0, `0041→0042_engine_run`)를 실행했다. 이어 `up -d --no-deps --no-build --force-recreate --scale document-worker=2 postgres minio clamav web document-worker`로 교체했다. analysis-worker·prespec-attachment-worker는 기동하지 않았다 |
| P7 확인 | `/api/health` 200, web healthy·재시작 0. Alembic `0042_engine_run`. daily-trigger는 반영 전과 같다(v5 `1e6d4ef1…`, switch ON, reasons 없음). `/api/runs`·`/api/opportunities`·`/api/order-plan-screening/policies` 200. 행 수는 리허설과 같은 차이만 있다. 모든 컨테이너의 compose working_dir와 web bind source가 `/Users/temp/orca/bidops`다. completion 없는 preflight(LiteLLM 별칭 경로, Ollama digest `41a558fc…` = 선언 = binding = generation config, 컨테이너에서 `/v1/models` 도달)는 ok다. analysis-worker가 꺼져 있어 3단계만 web 컨테이너로 바꾼 사본으로 실행했다. 5분 로그에 오류 없음 |
| P8 정리 | `git worktree remove /Users/temp/orca/bidops-c2mac`(남은 gitignore 파일은 모두 main에 사본 있음), `git branch -d feat/c2-litellm-mac`(`b8005ef`, main에 포함). 원격 브랜치는 건드리지 않았다 |

## 반영 뒤 상태와 남은 것

- tailnet: 운영 web은 `:8188 → 127.0.0.1:18788`이다(배포 뒤 tailnet 경유 `/api/health` 200). 종료한 데모를 가리키던 `:8187 → 18787` 연결은 사용자 요청으로 `tailscale serve --tcp=8187 off`해 지웠다. `:8197`(정지한 격리 RL 스택)은 건드리지 않았다.
- 운영 작업 트리는 `/Users/temp/orca/bidops`이고 `.env`는 운영 값이다. 개발은 `env/dev.env`(`bidops-dev`)를 쓰므로 운영 `.env`를 읽지 않는다. 데모 `bidops-local`은 종료했다.
- **analysis-worker는 정지 상태다.** C-2 실행과 preflight 원본 3단계는 이 worker가 필요하다. 일일 발주계획 트랙을 돌리기 전에 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build analysis-worker`를 사람이 확인하고 올린다. 그 전에 남아 있는 `대기` 실행을 먼저 본다.
- postgres·minio·clamav·document-worker의 restart 정책이 `no`라서 host 재시작 뒤에는 다시 수동으로 올려야 한다(10-28 정지 원인, findings).
- RL 분석·Luna·Slack은 이전처럼 꺼져 있다. 새 엔진 경로(`engine_run`)는 mock_reference 계약이며 운영 활성화가 아니다. 개요 플래그·상시 첨부 worker도 꺼진 상태를 유지했다.
- 롤백: 이 checkout에서 `.env`의 이미지 태그를 `rl-20261019` 쌍으로 되돌리고 `git worktree add ../bidops-c2mac before-ops-main-20261118`로 옛 compose를 복원한다. 스키마는 `bidops-20261117T160126Z.dump`를 빈 DB에 복원하고, 객체는 tar를 정지한 `bidops_minio-data`에 푼다. 0042는 새 테이블만 더하므로 옛 코드로 읽을 때 막힘은 예상하지 않지만 시험하지 않았다.
