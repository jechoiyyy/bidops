# 운영 절차

## 마지막 운영 확인과 현재 코드 (2026-10-21 문서 대조)

운영 상태의 마지막 확인 근거는 [2026-10-19 Mac RL 반영 기록](validation-runs/20261019-ops-rl-rollout/README.md)이다. 이번 갱신에서는 서버 상태를 재조회하지 않았다.

- 운영 작업 트리 `/Users/temp/orca/bidops-c2mac`, compose 프로젝트 `bidops`, main `b8005ef`, 이미지 `bidops:rl-20261019`·문서 worker `bidops:document-arm64-rl-20261019`, DB head `0041_proposal_draft`.
- C-2 v5 active·일일 스위치 ON, `/api/health` 200 확인. 개요 플래그·상시 첨부 worker는 꺼진 상태를 유지했다.
- RL 분석은 `BIDOPS_RL_ANALYSIS_ENABLED=false`. 운영 회사 근거·브리핑 미등록이며 코드·스키마 배포가 기능 활성화나 모델 전송 승인은 아니다.
- 현재 main의 RL import 기본 정책은 v11이다. 10월 20일 실제 v11 분석과 인수 reject는 격리 `bidops-local` 기록이며 운영 배포 사실로 옮겨 적지 않는다.
- 아래 일반 설치 명령·WSL2 v4 이력·격리 RL 실행 절차를 구분한다. Mac 운영 조합은 `scripts/mac-compose.sh`, RL·Slack 추가 활성화는 해당 절의 승인·설정 절차를 따른다.

## 운영 기준선

- 운영 정본은 PostgreSQL 17의 `bidops` schema와 버전 관리가 켜진 MinIO 객체 저장소다.
- `docker-compose.yml`이 웹, DB, 객체 저장소, 악성코드 검사, 문서 worker, 분석 worker, 첨부 worker의 기준 배포 파일이다.
- 모든 Compose 명령에는 전용 `COMPOSE_PROJECT_NAME`을 사용한다. 다른 worktree의 컨테이너와 volume을 중지하거나 삭제하지 않는다.
- 일상 운영에서 `docker compose down -v`, volume 삭제, 원본 객체 삭제를 사용하지 않는다.
- legacy notice attachment의 id 기반 다운로드 호환 사본은 `/app/web/data/attachments`에 있다. 같은 부모의 `/app/web/data/profile-snapshots`는 승인 프로필 projection이 읽는 artifact이므로 Compose named volume `web-data`가 `/app/web/data` 전체를 보존한다. 업로드는 quarantine·ClamAV 검사 후에만 등록된다.

## 절차 찾기

| 작업 | 문서 |
|---|---|
| 호스트·Compose와 일상 실행 | [host](operations/host.md) |
| 설치·설정·모듈 | [setup](operations/setup.md) |
| 일일 수집·C-2 운영 | [daily](operations/daily.md) |
| 사전규격 참조 실행 | [prespec-reference](operations/prespec-reference.md) |
| 백업·복구·서버 이전 | [backup-restore](operations/backup-restore.md) |
| 루트랩 회사 근거·판정·제안서·평가 | [rl](operations/rl.md) |

Mac 운영은 [호스트 절차](operations/host.md)의 `scripts/mac-compose.sh` 조합이 정본이다. WSL2 v4와 개별 참조 실행의 명령은 해당 환경의 기록이며 Mac 운영에 그대로 적용하지 않는다.

## 종료된 데모의 경계

HP·DEMO 그룹은 종료했다. 재사용 코드의 계약은 [HP](work/hp-contract.md)·[DEMO](work/demo-contract.md), 현재 기능은 [RL 로드맵](work/constitution/roadmap.md)을 따른다. 과거 3사 데모의 등록·전환 기록은 [DEMO-03 증거](validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md)에 있으며 당시 미배포·준비 단계는 현재 할 일이 아니다. 격리 스택과 운영의 secret·볼륨·정책 승인을 공유하지 않는다.
