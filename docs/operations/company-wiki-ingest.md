# 회사 위키 실적 넣기 활성화 절차 초안

대상은 등록된 실적의 요구사항을 분류하는 오프라인 참조 실행이다. 결과는 `mock_reference`이며 운영 활성화·모델 품질 인수의 근거가 아니다. 기본 설정에서 두 스위치는 false이고 사본 경로는 비어 있다.

1. **Migration 직전 사람 확인.** 기존 버전의 전체 백업과 롤백 태그를 준비하고 서비스를 중지한다. 배포 대상에서 migrate 자격으로 `alembic upgrade 0043_company_wiki_ingest`를 실행하고 `bidops.alembic_version`을 확인한다. 실행 기록이 있는 0043의 downgrade는 차단된다.
2. **권한 적용 직전 사람 확인.** migrate 자격으로 `psql -v ON_ERROR_STOP=1 -f /app/scripts/runtime-privileges.sql`을 실행한다. 서버·DB·자격은 기존 운영 설정을 사용한다. 공용 `scripts/migrate.sh`는 두 단계를 연속 실행하므로 각 단계 승인을 따로 받을 때는 위 명령을 분리한다.
3. **설정 변경과 버킷 준비 직전 각각 사람 확인.** 선택한 Compose 환경 파일에 `BIDOPS_ENGINE_COMPANY_BUNDLE_SLUG`, 전용 `BIDOPS_COMPANY_WIKI_INGEST_ACCESS_KEY`·`BIDOPS_COMPANY_WIKI_INGEST_SECRET_KEY`를 설정한다. 같은 환경의 기존 `minio-init`으로 `bidops-company-wiki-ingest` 버킷의 versioning과 전용 정책을 준비한다. 웹과 worker에는 원본 버전 단위 정리를 위한 이 버킷의 자격만 추가된다. 호스트의 `./wiki`에는 회사 YAML 세 파일과 위키 트리가 있어야 한다. `./backups/company-wiki`는 worker가 쓸 수 있어야 한다.
4. **활성화·재기동 직전 각각 사람 확인.** `BIDOPS_COMPANY_WIKI_INGEST_ENABLED=true`로 접수·분류를 열고, 참조 결과 반영까지 승인된 경우에만 `BIDOPS_COMPANY_WIKI_INGEST_APPLY_REFERENCE_ENABLED=true`, `BIDOPS_COMPANY_WIKI_BACKUP_DIR=/app/company-wiki-backups`를 설정한다. 같은 이미지·설정으로 web과 analysis-worker를 다시 만들고 ClamAV·document-worker의 가동을 확인한다. web의 회사 묶음 마운트는 ro, analysis-worker의 묶음·사본 마운트는 rw다. 목록 GET과 승인 전 상세의 `apply_allowed`로 설정을 확인한다. 분석 worker는 기존 공용 슬롯 하나를 사용한다.

반영 전에 worker가 UTC 시각과 run ID 앞 8자리로 사본을 만든다. 사본에는 해당 회사의 YAML 세 파일, 전체 위키 트리와 곁 파일이 들어 있다. 반영 명령 실패와 오래 멈춘 반영은 이 사본으로 복구한다. 복구가 막혀 `applying`이 남으면 원래 회사 묶음과 사본 마운트·권한을 먼저 복원한다. 같은 실행의 분류·반영을 재개하지 않는다. 회사 폴더·slug를 바꾸기 전에는 진행 중인 실행을 마쳐야 한다.

기능을 끄면 worker가 중단 복구를 포함한 모든 claim을 멈춘다. 정상적으로 끌 때는 진행 중인 반영의 종결을 먼저 확인한다. 호스트 사본은 회사 원문이므로 위키와 같은 접근 범위에서 보관한다. [API 계약](../contracts/company-wiki.md)
