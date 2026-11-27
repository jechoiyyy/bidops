# 운영 절차

## 현재 운영 상태 (2026-11-27 배포, 2026-11-28 정리)

근거는 [엔진 live·회사 핏 운영 배포 기록](validation-runs/20261127-engine-live-prod/README.md)과 [C-2 Top150 기록](validation-runs/20261119-c2-top150/README.md)이다. 운영은 Mac 한 대에서만 한다(2026-11-18 사용자 결정).

- 운영 작업 트리 `/Users/temp/orca/bidops`(main checkout, `.env`가 운영 값), Compose 프로젝트 `bidops`. web·analysis-worker·첨부 worker는 main에서 직접 빌드한 `bidops:main-20261127-d812377`이고 DB head는 `0047_company_fit_mode`다. 직전 상태로 돌아가는 백업·env 사본·이미지 태그와 순서는 위 기록의 "되돌리기"에 있다. 0047은 모드 행이 남으면 downgrade를 거부하므로 그때는 백업 복원이 길이다.
- 회사 자료(`docs/reference/company-*.md`·실적 tsv·회사소개서 PDF·`web/backend/app/screening/baseline_company_profile.md`)는 Git에 없고 운영 checkout에만 로컬 사본으로 있다. Compose bind mount 경로는 그대로다. 이 파일들을 지운 커밋을 처음 pull할 때는 [설치·설정](operations/setup.md) "웹의 회사자료 입력 전제"대로 사본을 먼저 옮겨 두고 되돌린다.
- C-2 v6 active·일일 스위치 ON. 로컬 개요 ON. 회사 핏 `suggest` ON이며 2026-11-27 21:15 KST 이후 처음 수집된 공고만 판정한다(`BIDOPS_PRESPEC_COMPANY_FIT_CARD_OBSERVED_FROM`). 끄기는 `set-company-fit-mode --mode off`(행은 지우지 않는다).
- 엔진 live ON(`BIDOPS_COMPOSE_FEATURES=engine-live`, 키 secret은 analysis-worker에만). 시운전 상한은 하루 1건·8회·$1, 공고당 8회다. 첫 감독 실행 1건이 `completed`·`unmeasured_reference`로 끝났고 사용자가 "맞아"로 판정했다. 1건이라 품질 근거가 아니며 상한 상향은 별도 결정이다.
- RL 분석은 `BIDOPS_RL_ANALYSIS_ENABLED=false`, 운영 회사 근거·브리핑 미등록이다. 코드·스키마 배포가 기능 활성화나 모델 전송 승인은 아니다.
- 사용자가 상시 운영이 필요 없다고 결정했다(2026-11-27). **cron 제거 예정**이다. 공고 06:30·발주계획 07:00 두 줄(`scripts/cron-daily-track.sh`)은 사용자가 지울 때까지 남는다. 제거 뒤 일일 실행은 [daily](operations/daily.md)의 수동 명령으로 한다.
- Mac 운영 조합은 main checkout에서 `BIDOPS_ENV=prod scripts/compose.sh`(`mac-compose.sh`는 호환 진입점)다. 아래 일반 설치 명령·WSL2 v4 이력·격리 RL 실행 절차를 구분한다.

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

HP·DEMO 그룹은 종료했다. 재사용 코드의 계약은 [HP](work/hp-contract.md)·[DEMO](work/demo-contract.md), 현재 기능은 [RL 로드맵](work/constitution/roadmap.md)을 따른다. 과거 3사 데모의 등록·전환 기록은 DEMO-03 증거(`docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md`, git 이력)에 있으며 당시 미배포·준비 단계는 현재 할 일이 아니다. 격리 스택과 운영의 secret·볼륨·정책 승인을 공유하지 않는다.
