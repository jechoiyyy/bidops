# 2026-11-21 운영 웹 UI 개선 배포

19:52 KST에 로컬 main의 UI 개선 커밋 `31f8048`을 운영 웹에 배포했다. 빌드에는 해당 커밋의 별도 작업 트리를 사용했다.

| 항목 | 확인값 |
|---|---|
| 운영 웹 이미지 | `bidops:main-20261121-31f8048` (linux/amd64) |
| 이미지 digest | `sha256:09d89e9028fe30a1e434550a35102d966da9e11733d829d2f34371aef963a273` |
| DB revision | `0042_engine_run` |
| PostgreSQL 전체 백업 | `backups/postgres/full/bidops-20261121T105144Z.dump`, 114,530,953바이트, 권한 0600. pg_restore 목록에서 TABLE DATA 111개 확인 |
| 백업 SHA-256 | `4261280394e6de13c41732c97660b1ef0a8cc77c107752101254cd74b3034246` |
| 롤백 지점 | Git 태그 `before-ux-audit-20261121`, 이전 웹 이미지 `bidops:main-20261121-75921f5`, 설정 사본 `backups/env-prod-before-ux-audit-20261121` |

운영 설정에서 BIDOPS_IMAGE 한 줄을 갱신하고 web만 교체했다. 교체 전후 컨테이너 ID를 대조했다. DB, 객체 저장소, 워커의 ID는 동일했다. 웹 컨테이너가 healthy에 도달했고 운영 주소의 GET /api/health가 ok를 반환했다.

운영 브라우저에서 1280×800으로 대시보드의 적재 경고 링크가 해당 회차의 펼쳐진 경고 표로 이동하는지, 발주계획 상세 필터를 펼쳐 회차를 고를 수 있는지, 최종 결정의 빈 목록에서 사업기회로 이동하는지 확인했다. 이 확인에서는 API 쓰기 요청을 차단했다.

롤백할 때는 운영 설정의 BIDOPS_IMAGE를 이전 웹 이미지로 돌리고 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`으로 웹을 교체한다.
