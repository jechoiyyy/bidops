# 2026-11-27 발주계획 상세 필터 배포

발주계획 상세 필터를 사전규격과 같은 3열 배치로 바꿨다. 수집 회차는 필터를 연 뒤 조회 범위에서 바로 고를 수 있고, 다중 선택 조건은 드롭다운으로 조작한다. 변경 커밋은 `1cc5e74`다.

| 범위 | 반영 이미지 | 롤백 이미지 |
|---|---|---|
| 운영 web | `bidops:main-20261127-1cc5e74` | `bidops:before-order-plan-filters-20261127-web` |
| 포트폴리오 web | `bidops:portfolio-20261127-1cc5e74` | `bidops:portfolio-before-order-plan-filters-20261127` |

운영은 커밋의 클린 트리로 빌드했다. 포트폴리오는 기존 배포 소스 `3ea6126`에 필터 변경을 적용하고 분석 화면과 고정 시계 설정을 포함해 빌드했다. 두 환경에서 web만 교체했다. 운영 DB head는 `0043_company_wiki_ingest`이며 migration은 없었다.

운영 전체 DB 백업은 `backups/postgres/full/bidops-20261127T020726Z.dump`에 있다. 파일 권한은 0600이고 `pg_restore -l`에서 TABLE DATA 112개를 확인했다. 로컬 Git 롤백 태그 `before-order-plan-filters-20261127`는 직전 운영 web 소스 `cb93c93`을 가리킨다. 롤백 시 운영의 `BIDOPS_IMAGE` 또는 포트폴리오의 `BIDOPS_PORTFOLIO_IMAGE`에 해당 롤백 이미지를 지정하고 같은 Compose 진입점에서 web을 다시 생성한다.

두 웹의 health, 발주계획 목록 API, 회차 API가 200을 반환했다. 두 배포 주소에서 Chromium으로 회차 선택, 기본값 복원, 필터 접기를 확인했다. 포트폴리오에서는 기존 사전규격 분석 화면도 열었다.
