# HP-01 격리 배포·backfill 검증

2026-10-15 KST, 사용자 부재 중 일괄 실행 승인(`session-authorization.md`)에 따라 `bidops-local`에만 적용했다. main·별도 `bidops` 운영 프로젝트·origin은 변경하지 않았다. runner는 기존 HP-00 이미지를 유지했다.

- 롤백: Git `before-hp01-20261015` → HP-00 `582f06d`; 이전 앱 이미지 `bidops-local:before-hp01-20261015`(HP-00 이미지와 동일). 새 앱은 `bidops-local:hp01-20261014`, image ID `sha256:1b0e5878849b40a810f17fb1315dea0eece43a59b6c813156a27c30882fda0db`.
- 동일 복구 지점: `hp01-backup.json`에 전체 DB dump 경로·SHA256·pg_restore 목록 결과 및 객체 164개 버전/210,361,810 bytes/버킷별 수·manifest hash가 있다. source/stored hash 검증과 리더의 파일 hash 재확인이 모두 일치했다. 실제 restore 시험이나 WAL/RPO 증거는 아니다.
- 기존 9개 Compose 파일과 4개 env 파일을 그대로 사용하고 `.sdlc/local-runtime/hp01-20261014/hp01.env`(0600)의 앱 이미지 override만 추가했다. 안전한 argv는 같은 Git 외부 디렉터리의 `compose-argv.json`에 있으며 `compose.py`가 그대로 실행한다. 비밀값은 기록하지 않았다.
- `stop web analysis-worker` 후 backup profile의 `ro-backup`, ops profile의 기존 검증 backup helper를 실행했다. 처음 `compose run --no-build`는 지원되지 않는 인수라 실행 전에 거부됐으며, `--no-build`를 제거하고 이미 존재하는 이미지로 실행했다. 실패/성공 로그는 Git 외부 runtime 디렉터리에 보존했다.
- `run --rm --no-deps migrate`: `0036_company_analysis` → `0037_requirement_card_columns`, exit 0. 기존 `migrate.sh`의 runtime privilege 정책 적용을 사용했다. 앱 시작 migration은 없다.
- backfill: analysis-worker 이미지·worker 역할에서 `python -m app.deep_review.cli rebuild-segment-manifests --structure-id f25729bf-e39f-4624-a17c-bcbeaa023888`을 dry-run → 생성 → 멱등 재실행 순으로 실행했다. 모두 exit 0; dry-run manifest null, 생성 ID `f2bbaa5c-b074-48f9-9c89-2b79b573dde2`, 재실행 같은 ID/created=false. 각 로그는 `hp01-backfill-*.log`.
- 범위는 intent 기본 홈페이지 사전규격 79·116·129·156이다. 기존 ready 구조가 있는 79만 처리했다. 나머지 3건은 구조가 없으며 수집/변환을 새로 시작하지 않았다(`hp01-backfill-scope.json`).
- `up -d --no-deps --no-build --force-recreate web analysis-worker`: exit 0. `hp01-runtime.json`은 웹 healthy와 두 앱/runner의 환경 hash·네트워크·마운트 동일성을 확인한다. runner 이미지도 그대로다.
- `hp01-row-preservation.json`: 기존 structure18/manifest18/segment1531/inventory48/profile7/policy3 행의 이전 필드는 모두 동일하다. 새 manifest1/segment105/inventory35만 추가됐다. 새 열은 비교 투영에서 제외했고, migration PG 테스트에서 기존 행 default/NULL 보존도 확인했다.
- `hp01-live-validation.json`: DB head0037, `/`·`/api/health`·실제 `/segments` HTTP200, taxonomy v2, 카드35(상속13/미확인22), active job0. 이 DB 원문 SHA는 5개 파일 T11과 별도 입력이다. 직접 product `requirement_cards` 조회와 실제 REST를 사용했으며 raw 카드 본문은 기록하지 않았다.

배포 전후 새 모델 호출은 없고 정책/프로필/기존 원문·manifest는 불변이다. 새 카드/anchor 데이터가 생긴 뒤 migration downgrade는 손실 방지를 위해 거부한다. 복구가 필요하면 보존 이미지·전체 DB/객체 복구 지점을 함께 사용하며, 이 작업에서는 복구를 실행하지 않았다.
