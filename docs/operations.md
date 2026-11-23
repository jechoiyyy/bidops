# 운영 절차

## 마지막 운영 확인과 현재 코드 (2026-11-20 배포)

운영 상태의 마지막 확인 근거는 [2026-11-20 사전규격 1단계 운영 이미지 배포 기록](validation-runs/20261120-prespec-stage1/README.md)이다. 운영은 Mac에서만 한다(2026-11-18 사용자 결정).

- 운영 작업 트리 `/Users/temp/orca/bidops`(main checkout, `.env`가 운영 값), Compose 프로젝트 `bidops`. web·analysis-worker는 main `b839367`의 이미지 `bidops:main-20261120-b839367`로 실행 중이며 문서 worker는 `bidops:document-arm64-main-20261118`을 쓴다. DB head는 `0042_engine_run`이다. 직전 앱 이미지 `bidops:main-20261119`의 롤백 태그는 `before-prespec-stage1-20261120`이다.
- C-2 v6 active·일일 스위치 ON, `/api/health` 200 확인. analysis-worker·postgres·minio·clamav·document-worker는 `unless-stopped`다. 일일 cron은 공고 06:30·발주계획 07:00으로 설치했다. 11월 20일 공고는 종료 코드 0이었고 해당 회차에 적재 경고 440건이 남았다. 발주계획은 수집기 수정 뒤 수동 재실행에서 11월 19일치 557건을 수집하고 상위 150건을 판정했다. 사전규격 1단계 코드와 첨부 worker 조회 권한을 적용했고 로컬 개요는 활성화했다. 실제 공고 1건의 첨부부터 검토 목록까지 [시운전](validation-runs/20261120-prespec-stage1/README.md)에서 확인했다.
- RL 분석은 `BIDOPS_RL_ANALYSIS_ENABLED=false`. 운영 회사 근거·브리핑 미등록이며 코드·스키마 배포가 기능 활성화나 모델 전송 승인은 아니다.
- RL import 기본 정책 v11 코드가 운영 이미지에 들어갔으나 RL 분석은 꺼져 있다. 10월 20일 실제 v11 분석과 인수 reject는 격리 `bidops-local` 기록이며 운영 품질 근거가 아니다. 새 엔진 경로(`engine_run`)는 mock_reference 계약이며 운영 활성화가 아니다.
- 아래 일반 설치 명령·WSL2 v4 이력·격리 RL 실행 절차를 구분한다. Mac 운영 조합은 main checkout에서 `BIDOPS_ENV=prod scripts/compose.sh` (`mac-compose.sh`는 호환 진입점), RL·Slack 추가 활성화는 해당 절의 승인·설정 절차를 따른다.

2026-11-17 조회의 운영·데모 web restarting은 10-28 host 재시작 뒤 restart 정책 `no`인 postgres 등이 올라오지 않은 결과였고, 2026-11-18 배포에서 운영을 다시 올렸다.

## 운영 기준선

- 운영 정본은 PostgreSQL 17의 `bidops` schema와 버전 관리가 켜진 MinIO 객체 저장소다.
- Compose와 Dockerfile은 `docker/`에 모은다. `scripts/compose.sh`는 `--project-directory`를 저장소 루트로 고정하므로 build context·bind mount·env·secret 상대 경로가 유지된다. 파일을 직접 조합하지 않고 Make 또는 선택기를 사용한다.
- `docker/docker-compose.yml`이 웹, DB, 객체 저장소, 악성코드 검사, 문서 worker, 분석 worker, 첨부 worker의 기준 배포 파일이다.
- 모든 Compose 명령에는 전용 `COMPOSE_PROJECT_NAME`을 사용한다. 다른 worktree의 컨테이너와 volume을 중지하거나 삭제하지 않는다.
- 일상 운영에서 `docker compose down -v`, volume 삭제, 원본 객체 삭제를 사용하지 않는다.
- legacy notice attachment의 id 기반 다운로드 호환 사본은 `/app/web/data/attachments`에 있다. 같은 부모의 `/app/web/data/profile-snapshots`는 승인 프로필 projection이 읽는 artifact이므로 Compose named volume `web-data`가 `/app/web/data` 전체를 보존한다. 업로드는 quarantine·ClamAV 검사 후에만 등록된다.

## 절차 찾기

| 작업 | 문서 |
|---|---|
| 호스트·Compose와 일상 실행 | [host](operations/host.md) |
| 설치·설정·모듈 | [setup](operations/setup.md) |
| 일일 수집·C-2 운영 | [daily](operations/daily.md) |
| 회사 위키 실적 넣기 | [활성화 절차 초안](operations/company-wiki-ingest.md) |
| 사전규격 참조 실행 | [prespec-reference](operations/prespec-reference.md) |
| 백업·복구·서버 이전 | [backup-restore](operations/backup-restore.md) |
| 루트랩 회사 근거·판정·제안서·평가 | [rl](operations/rl.md) |

환경 선택은 [호스트 절차](operations/host.md)의 `scripts/compose.sh` 하나가 정본이다. 기본은 격리 dev이며 운영은 `BIDOPS_ENV=prod`로 명시한다. WSL2 v4와 개별 참조 실행의 명령은 해당 환경의 기록이며 Mac 운영에 그대로 적용하지 않는다.

## 종료된 데모의 경계

HP·DEMO 그룹은 종료했다. 재사용 코드의 계약은 [HP](work/hp-contract.md)·[DEMO](work/demo-contract.md), 현재 기능은 [RL 로드맵](work/constitution/roadmap.md)을 따른다. 과거 3사 데모의 등록·전환 기록은 [DEMO-03 증거](validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md)에 있으며 당시 미배포·준비 단계는 현재 할 일이 아니다. 격리 스택과 운영의 secret·볼륨·정책 승인을 공유하지 않는다.
