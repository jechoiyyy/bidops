# PostgreSQL과 versioned MinIO를 운영 정본으로 사용

- 상태: 채택
- 일자: 2026-08-27

## 맥락

초기 SQLite WAL 결정은 소수 사용자의 단일 호스트 리뷰를 전제로 했다. 심층 검토에는 여러 worker의 job lease, append-only 보고서·감사, 문서 원본·구조·암호화 모델 응답의 버전 관리, DB와 객체의 일관된 복구가 필요해졌다. SQLite 파일과 host 첨부 경로만으로는 이 경계를 안전하게 운영하기 어렵다.

## 결정

운영 정본은 PostgreSQL 17의 `bidops` schema와 versioning이 켜진 MinIO로 한다. 관계, 상태, 리뷰, 정책, 실행, 감사는 PostgreSQL에 저장하고 원문, 문서 구조, quarantine, 암호화 모델 응답은 목적별 MinIO namespace에 저장한다. DB에는 객체 version, hash, 암호화 key reference를 연결한다.

SQLite는 격리 테스트와 일회성 이전 입력에만 허용한다. 앱은 SQLite URL로 기동하지 않으며 startup이 migration이나 seed를 수행하지 않는다. 복구는 빈 대상에 객체를 먼저 복구하고 DB를 복구한 뒤 active hash를 검증한다.

## 대안

SQLite WAL을 계속 사용하면 단일 파일 운영은 단순하지만 다중 worker claim, 중앙 감사, 객체 version과의 복구 경계를 DB 밖의 관례에 의존하게 되어 기각했다.

PostgreSQL에 첨부와 모델 응답 bytes까지 넣는 방법은 transaction 경계는 단순하지만 대형 파일, versioned 원본, 목적별 자격증명, 격리 worker의 최소 권한 운영이 어려워 기각했다.

파일과 객체만 정본으로 두는 방법은 리뷰 동시 수정, 상태 fence, idempotency, 관계 조회를 안정적으로 제공하기 어려워 기각했다.

## 결과

배포에는 PostgreSQL 역할 분리, Alembic, MinIO 버킷·정책·versioning, ClamAV, DB와 객체의 짝을 맞춘 backup이 필요하다. `create_all`, 자동 seed, `down -v`는 운영 경로에 포함되지 않는다. 리뷰가 DB 정본이라는 기존 결정은 유지되며 저장 엔진만 PostgreSQL로 바뀐다.
