# 백업·복구·서버 이전

[전체 운영 절차](../operations.md). 기준일: 2026-10-21. 명령은 별도 표시가 없으면 저장소 루트에서 실행한다. 운영 변경·실제 전송은 단계별 승인 범위를 따른다.

## 백업

PostgreSQL 백업은 현재 Compose 계약상 host의 `./backups/postgres`에 쓴다. 실행 뒤 dump를 승인된 외부 보존 위치로 복사하고 보존 위치의 접근권한과 hash를 기록한다.

```bash
COMPOSE_PROJECT_NAME=bidops docker compose \
  -f docker-compose.yml --profile backup run --rm ro-backup
```

`scripts/backup-postgres.sh`는 timestamp가 붙은 custom-format dump를 만들고 기존 백업을 삭제하지 않는다. 4시간 RPO가 필요하면 이 스크립트와 별도로 WAL 보관을 구성하고 복구 시험으로 확인한다.

`ro_backup`은 table뿐 아니라 현재/향후 `migrate` 소유 sequence의 SELECT도 필요하다.
runtime 권한 정책은 이를 읽기 전용으로 부여하며 USAGE/UPDATE는 부여하지 않는다.
sequence 접근 거부로 종료한 dump는 0 B일 수 있으므로 성공 백업으로 사용하지 않는다.
승인된 최소 권한 복구 뒤 새 경로에 백업하고 exit·크기·SHA-256·`pg_restore --list`를
확인한다. 목록 읽기 성공은 실제 restore 시험이나 WAL/RPO 충족의 증거는 아니다.

객체 백업은 네 개의 MinIO 버킷에서 모든 version을 버전별 파일로 복사하고
`OBJECT_BACKUP_DIR/object-versions.tsv`를 만든다. manifest의 각 행은 헤더 없이
`namespace/object_name<TAB>source_version_id<TAB>sha256` 형식이다. `sha256`은 source와
백업 파일의 stored bytes가 같은지 복사 직후 다시 확인한 값이다. 실행 환경에 `mc`,
`MINIO_ALIAS`, `OBJECT_BACKUP_DIR`를 제공한다. object key에 공백과 괄호가 있어도 TSV
필드와 version-qualified 파일명으로 보존한다.

```bash
./scripts/backup-objects.sh
```

DB dump와 객체 manifest는 같은 복구 지점을 식별할 수 있게 함께 보존한다. 암호화 key reference와 실제 key의 백업 정책은 분리하고 접근을 감사한다.

## 복구

복구는 기존 운영 대상 위가 아니라 빈 PostgreSQL과 빈 MinIO 대상에서 수행한다. 네 개 대상
버킷은 versioning이 켜져 있어야 한다. restore는 source version ID를 target에 그대로
재사용한다고 가정하지 않고, 각 `mc cp` 직후 target version ID를 조회한다. 복사 전 백업
파일의 stored-byte hash도 manifest와 대조한다.

`restore.sh`가 만드는 산출물은 다음과 같다.

- `OBJECT_BACKUP_DIR/object-version-mapping.tsv`: 헤더 없는
  `namespace/object_name<TAB>source_version_id<TAB>target_version_id<TAB>sha256` mapping.
  백업 manifest의 source ID와 복구 대상에서 새로 발급된 target ID를 함께 보존한다.
- `ACTIVE_HASH_MANIFEST`: `pg_restore` 뒤
  `scripts/generate-active-hash-manifest.sh`가 복구 DB의 active object reference에서
  원자적으로 다시 만든 manifest다. 수동으로 일부 object를 적은 파일을 준비하지 않는다.

복구 순서는 객체 복사·백업 hash 확인 → DB restore → DB active manifest 생성 → target
version ID·namespace별 무결성 및 active 집합 일대일 검증이다. 다섯 버킷 모두 백업·복구 대상이다. source·structure·quarantine·proposal-pdf는
target version의 stored-byte hash까지 대조한다. model-response는 암호화된 응답 envelope를
저장하고 DB의 `ContentObject.sha256`에는 plaintext hash만 기록하므로, 내용 hash는 대조하지
않고 target version에서 object 존재와 version만 확인한다. verifier는 mapping과 target의
모든 복구 version을 대조하며, DB active object의 누락·추가·중복과 target object의
누락·추가·중복을 실패시킨다.

1. 복구 대상과 네트워크를 격리한다.
2. `OBJECT_BACKUP_DIR`, `RESTORE_MINIO_ALIAS`로 버전별 객체를 먼저 복사하고 target ID mapping을 남긴다.
3. `DUMP_FILE`을 빈 PostgreSQL에 `pg_restore`한다.
4. `ACTIVE_HASH_MANIFEST`를 복구 DB의 `bidops.content_object_location`과
   `bidops.content_object`에서 생성한다.
5. mapping의 target version ID로 active object의 hash와 DB active 집합을 대조한다.
6. FK, Alembic head, 핵심 row 수, active document·model response 참조를 검사한다.
7. API read-only smoke와 대표 보고서 재현을 확인한 뒤에만 전환 여부를 사람이 결정한다.

```bash
OBJECT_BACKUP_DIR=/approved/objects \
DUMP_FILE=/approved/db.dump \
ACTIVE_HASH_MANIFEST=/approved/active-hashes.tsv \
RESTORE_MINIO_ALIAS=restore \
BIDOPS_DATABASE_URL='postgresql+psycopg://...' \
BIDOPS_DATABASE_HOST=restore-db \
BIDOPS_DATABASE_PORT=5432 \
BIDOPS_DATABASE_NAME=bidops \
BIDOPS_DATABASE_USER=restore-user \
BIDOPS_DATABASE_PASSWORD='injected-secret' \
./scripts/restore.sh
```

host에 `mc`·`pg_restore`·`psql`이 없으면 동일한 변수를 주입한 승인된 ops image에서
`bash /opt/bidops/scripts/restore.sh`를 실행한다. `BIDOPS_DATABASE_URL`은 실행 계약 식별자로
함께 주입하고, 실제 명령은 `BIDOPS_DATABASE_HOST`·`PORT`·`NAME`·`USER`와
`BIDOPS_DATABASE_PASSWORD`를 사용한다. `RESTORE_MINIO_ALIAS`는 네 개 target bucket에
접근할 수 있는 `mc` alias여야 한다. 복구 중 source object, 기존 백업 파일, DB row를
삭제하지 않으며, target이 비어 있지 않거나 versioning이 꺼져 있으면 검증 실패로 끝난다.

## 서버 이전용 전체 폴더

`scripts/transfer.py`는 현재 실행 이미지, PostgreSQL 논리 dump·역할, 중지 상태의 MinIO
전체 볼륨, 앱 데이터 볼륨, 미커밋 소스와 호스트 입력을 한 폴더로 보존한다. 기존 버전별
객체 복구와 달리 MinIO 물리 볼륨을 같은 이미지로 복원하므로 객체 version ID가 유지된다.
사용자가 선택한 **평문 보관** 방식이며 환경 파일·회사자료·인증 파일·복호화 키를 포함한다.
생성 위치는 Git에서 제외된 `backups/transfer/`로 제한한다. 과거 백업 묶음은 포함하지 않는다.

```bash
# 준비: 서비스 변경 없이 현재 이미지 8종 등의 실제 구성을 보존한다.
python3 scripts/transfer.py prepare --project bidops \
  --bundle "$PWD/backups/transfer/<UTC시각>"

# 사람의 중단 승인 후 실행. 설치된 모든 일일 cron의 flock 파일을 지정한다.
python3 scripts/transfer.py capture --bundle "$PWD/backups/transfer/<UTC시각>" \
  --lock-file "$HOME/.local/state/bidops/daily.lock" --confirmed-stop

python3 scripts/transfer.py verify --bundle "$PWD/backups/transfer/<UTC시각>"
```

`prepare` 뒤 실행 컨테이너·이미지·running 상태가 바뀌면 새 폴더로 준비한다. capture는
공용 lock 획득과 실행 중 DB 작업 검사를 통과한 뒤 web·worker를 중지한다. DB dump와 객체
기준 검사를 수행하고 MinIO를 중지해 볼륨을 복사한다. 원래 실행 중이던 컨테이너만 재시작한다.
이미 중지된 analysis-worker는 켜지 않으며 crontab도 설치·수정하지 않는다. 실패나 SIGTERM 때도
재시작을 시도한다. SIGKILL·호스트 장애 때는 `manifest/resume-containers.json`의 ID를 확인해
MinIO부터 역순으로 재시작하고 health를 확인한다. 미완료 폴더 위 재실행은 하지 않는다.

완료 표식은 `manifest/snapshot.json`의 `state=captured`와 `manifest/files.json`이다.
후자는 정확한 파일 집합·크기·SHA-256을 검증한다. source의 Git bundle은 기존 이력을,
source 파일 사본과 변경 목록은 미커밋 작업을 보존한다. 호스트 입력은 `inputs/host/`,
실제 bind mount 입력은 `inputs/binds/`에 있으며 Docker 앱 데이터 볼륨과 자동 병합하지 않는다.

새 Linux 서버는 Python 3.12+, Docker Engine·Compose v2와 동일 CPU 아키텍처가 필요하다.
이전 폴더 안의 도구를 사용하며 새 대상 프로젝트·디렉터리·볼륨만 허용한다.

```bash
python3 /path/to/transfer/transfer.py restore --bundle /path/to/transfer \
  --project bidops-restored --target /path/to/new-restore --port 18789
```

이 명령은 저장된 이미지와 역할로 빈 DB에 dump를 복원하고 MinIO·앱 볼륨을 복원한다.
migration·minio-init은 실행하지 않는다. DB 전체 행 수·Alembic revision과 전체 객체 버전·해시,
active 참조 및 모델 응답 복호화 결과를 원본 기준과 비교한다. 원본의 누락 객체는
`manifest/objects.json`의 `issues`로 보존하며 복원 성공으로 고쳐 쓰지 않는다.

열람 모드는 localhost에만 열고 별도 worker를 기동하지 않는다. `transfer-preview.py`는 기존
앱의 DB revision·MinIO 기동 검사를 유지하며 runtime.start를 호출하지 않아 내장 판정 워커의
stale 복구와 자동 실행을 막는다. HTTP 변경 요청은 405이고 DB transaction도 read-only다.
policy 상태와 데이터는 변경하지 않는다. 이 모드는 운영 수집·분석 재개나 공개 서비스가 아니다.
모델 egress·실제 전송·일정 재설치는 별도 운영 전환 절차를 따른다.

검증은 `python3 -m unittest discover -s tests -p test_transfer.py -v`와 격리 실제 복원으로 한다.
파일 해시 통과만으로 복원 검증을 대신하지 않는다. 복원 대상의 `validation.json` 이후에도
대표 목록·첨부·개요·심층 보고서·프로필 API와 화면 열람을 확인해 증거를 보존한다.
