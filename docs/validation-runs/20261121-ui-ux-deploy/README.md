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

## 사전규격 목록 하단 후속 배포

운영 웹만 main `689f41a` 이미지 `bidops:main-20261121-689f41a`로 교체했다. 신규 미선택 건의 고정 영역에서 추적 상태와 입찰 참여 안내 반복을 제거하고, 다음 행동은 왼쪽, 검토 제외와 상세 진입은 오른쪽에 모았다. 승계 기록은 사유를 펼쳐 확인할 수 있다. 두 워커의 컨테이너 ID는 배포 전후 동일했다.

| 브라우저 뷰포트 | 운영 교체 전 하단 높이 | 교체 후 | 가로 넘침 |
|---|---:|---:|---:|
| 1920×1080 | 278px | 144px | 0px |
| 1440×900 | 278px | 144px | 0px |
| 1280×800 | 298px | 144px | 0px |

전체 이력에서 처음 선택된 동일 상태의 항목을 운영 GET으로 열어 footer의 offsetHeight와 scrollWidth − clientWidth를 측정했다. 관련 Playwright 검사 10건 통과, 운영 web healthy, /api/health ok, DB revision `0042_engine_run`(SELECT), tailnet 목록 URL 200을 확인했다.

- 이미지 ID `sha256:b387b514b04a9bae8be896fe2bdb7686c43db2281df622fe6b13f910da97b633`.
- 전체 백업 `backups/postgres/full/bidops-20261121T114034Z.dump`(0600, 114530953바이트, SHA-256 `968956a81c6859b2b05d46927e0b95548fa71f8717667300e8be59824fa7995f`, TABLE DATA 111개).
- 롤백 태그 `before-prespec-footer-689f41a`. 직전 이미지 `bidops:engine-sync-20261121-2d47d42`와 설정 사본 `backups/env-prod-before-prespec-footer-689f41a`를 보존했다. 롤백은 BIDOPS_IMAGE를 직전 값으로 복구한 뒤 web만 교체한다.

## 네 레코드 화면 밀도 변경 배포

승인된 main 커밋 `a8a2f75`의 Git 아카이브로 linux/amd64 이미지를 빌드하고 운영 web만 교체했다. 이미지 `bidops:main-20261121-a8a2f75`, ID `sha256:d58c1cb8d61d421f3f550554efb639f6bc0db18848751ecebd311644fd5f1621`. web healthy, 내부와 tailnet의 GET /api/health ok. 분석·첨부 워커의 컨테이너 ID는 교체 전후 동일하다. DB revision은 `0042_engine_run`이고 migration은 없었다.

운영 tailnet 주소에서 발주계획·사전규격 전체 이력·사업기회·최종 Go/No-Go를 1920×1080, 1440×900, 1280×800으로 열었다. 12개 조합 모두 문서 가로 넘침 0px. 두 선택 목록 모두 초기 선택 0건에서 전체 선택·해제가 보이고 해제는 비활성이었다. 각 해상도의 선택 버튼은 32px, 도구줄은 40px, 사전규격 하단은 68px였다. 기본 데스크톱에서 두 목록의 전체 선택·해제를 직접 실행했다. 검증 브라우저는 GET 이외의 API 요청을 차단했다.

전체 DB 백업 `backups/postgres/full/bidops-20261121T120325Z.dump`(0600, 114530953바이트, SHA-256 `8f8a79393492eab71c663642be4e32e8facb66ab2cebc3588fd5c734a3e1c3ba`, TABLE DATA 111개). 직전 코드 태그 `before-record-compact-a8a2f75`, 설정 사본 `backups/env-prod-before-record-compact-a8a2f75`. 롤백 시 BIDOPS_IMAGE를 `bidops:main-20261121-689f41a`로 복구하고 web만 교체한다.

## 사전규격 선택 검토 자동 이동과 일괄 추적 시작

원격 main의 기능 커밋 `294be33`을 Git 아카이브로 빌드해 운영 web을 `bidops:main-20261121-294be33`으로 교체했다. 컨테이너 healthy, tailnet GET /api/health ok, 새 일괄 추적 POST 경로 등록과 DB revision `0042_engine_run`을 확인했다. 운영 데이터 쓰기는 검증에서 차단했다. 1920×1080, 1440×900, 1280×800에서 실제 목록의 공고 두 건을 선택하고 일괄 추적 창 열기·취소와 선택 검토 첫 상세 진입을 확인했다. 저장·재시도·다음 공고 이동은 격리 테스트에서 확인했다.

배포 전 전체 백업은 `backups/postgres/full/bidops-20261121T121616Z.dump`이며 권한 0600, SHA-256 `8dae89866c1dbfd75c3f2f3463b6b7794729e43614c8bf3daa061fc8ded9fa62`, pg_restore 목록 TABLE DATA 111개다. 롤백 태그는 `before-prespec-bulk-294be33`, 설정 사본은 `backups/env-prod-before-prespec-bulk-294be33`이다. 롤백할 때는 BIDOPS_IMAGE를 직전 웹 이미지 `bidops:main-20261121-a8a2f75`로 되돌리고 web만 교체한다.
