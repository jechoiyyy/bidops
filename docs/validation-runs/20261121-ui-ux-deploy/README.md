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

## 승인한 전체 레이아웃과 목록 제목 정렬

22:47 KST에 [승인한 화면 적용 기준](../../1119_kstyle-shell/approved-layout.md)을 운영 웹에 배포했다. 사업기회와 최종 Go/No-Go의 목록 제목과 보조 문구는 공통 목록 머리에서 세로 중앙 정렬한다. 발주계획과 사전규격은 공통 선택 도구와 사유를 입력하지 않는 단건 추적 시작을 제공한다.

| 항목 | 확인값 |
|---|---|
| 운영 웹 이미지 | `bidops:approved-ui-20261121-bb0365c935dc` (linux/amd64), `sha256:63349eb601563a6d28707816ecc77a0dbeb6256dc89cf2c1f1bf02c6bb839e01` |
| 빌드 입력 | Git `7c7375b` 아카이브에 승인된 프론트엔드·추적 API 변경만 적용. 재현 패치 `backups/approved-ui-20261121-bb0365c935dc.patch`의 SHA-256 `bb0365c935dcf5f23768a7ca1ad1a215fac153862d1df59b12bcc1e0d882f611` |
| PostgreSQL 전체 백업 | `backups/postgres/full/bidops-20261121T134651Z.dump`, 권한 0600, 114,531,823바이트, pg_restore 목록 TABLE DATA 111개 |
| 백업 SHA-256 | `7f5e05d487806ddb3a6b31d7004df3a29c13c5232dbced0025b2ce9f1918e8a5` |
| 롤백 지점 | Git 태그 `before-approved-ui-20261121-bb0365c935dc`, 직전 웹 이미지 `bidops:main-20261121-294be33`, 설정 사본 `backups/env-prod-before-approved-ui-20261121-bb0365c935dc` |

웹만 교체했다. 컨테이너 healthy, tailnet GET /api/health ok, DB revision `0042_engine_run`을 확인했다. DB, MinIO와 워커의 컨테이너 ID는 같았다. migration은 실행하지 않았다. 롤백은 운영 설정의 BIDOPS_IMAGE를 이전 웹 이미지로 되돌린 뒤 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`으로 실행한다.

운영 tailnet에서 발주계획·사전규격·사업기회·최종 Go/No-Go를 1280×800, 1440×900, 1920×1080으로 확인했다. 12개 조합에서 목록 폭 56%, 가로 넘침 0px, 목록 머리와 문구 중심 차이 최대 0.51px였다. 1920×1080에서는 발주계획과 사전규격의 전체 선택·해제도 확인했다. 운영 검증 중 API 쓰기는 차단했다. 운영 OpenAPI에서 추적 사유 선택값과 사전규격 일괄 시작 경로를 확인했다. 격리 Playwright 10건과 추적 API 4건이 통과했다.

## 발주계획 100건 페이지 조회

23:22 KST에 [발주계획 검토 화면의 페이지 조회](../../contracts/c2.md#발주계획-검토-화면의-페이지-조회)를 운영 웹에 배포했다. 기존 레이아웃 이미지의 소스에 발주계획 페이지 조회와 관련된 프론트엔드·API 파일만 덮어 빌드했다.

| 항목 | 확인값 |
|---|---|
| 운영 웹 이미지 | `bidops:order-plan-paging-20261121-605d8e52b5d5` (linux/amd64), `sha256:70614a68892d0e9caa18bcfc87c0a0923d878033815e2e87c4f765050fcf101c` |
| 재현용 소스 | 이전 릴리스 입력 위에 `backups/order-plan-paging-20261121-605d8e52b5d5-source.tar.gz` 적용. SHA-256 `605d8e52b5d53b01760149bd7b71ffed4fa154216cbc6f68c2eb63c59d4e934c` |
| PostgreSQL 전체 백업 | `backups/postgres/full/bidops-20261121T142132Z.dump`, 권한 0600, 114,531,823바이트, pg_restore 목록 TABLE DATA 111개 |
| 백업 SHA-256 | `0a994cac1724777c966876c0edd4faaaac087a4feb315890fa1d77b4ae0ad286` |
| 롤백 지점 | Git·Docker 태그 `before-order-plan-paging-20261121-605d8e52b5d5`, 직전 이미지 `bidops:approved-ui-20261121-bb0365c935dc`, 설정 사본 `backups/env-prod-before-order-plan-paging-20261121-605d8e52b5d5` |

운영 웹만 교체했다. web healthy, tailnet GET /api/health ok, DB revision `0042_engine_run`을 확인했다. DB, MinIO, 워커의 컨테이너 ID는 배포 전후 같았다. 롤백은 운영 설정의 BIDOPS_IMAGE를 직전 웹 이미지로 되돌린 뒤 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`으로 실행한다.

| 운영 확인 | 첫 목록 표시 | 목록 API | 응답 크기 |
|---|---:|---:|---:|
| 기본 보기 · 1280×800 | 1,805ms. 추가 두 측정에서 864ms·842ms | 1회 | 122,266B |
| 전체 보기 · 1440×900 | 859ms | 1회 | 121,404B |
| 검색 · 1920×1080 | 836ms | 1회 | 121,395B |

전체 9,536건 중 첫 페이지 100건을 표시했다. 다음 페이지에서 `101–200 / 9,536` 및 추가 호출 1회(`offset=100`), 처음 선택한 100건의 유지와 해제, ↑로 이전 페이지 마지막 행의 선택과 초점 이동을 확인했다. 운영 확인 브라우저에서 API 쓰기는 0건이었다.

## 실무자 라이프사이클 메뉴 재구성

23:45 KST에 사이드바를 `오늘 할 일 → 탐색 → 사업기회`로 재구성해 운영 웹에 배포했다. 최종 Go/No-Go는 사업기회 아래의 대기열에서 열고, `추적 중`·`마감 임박`은 사업기회 목록의 보기로 옮겼다. 회사 근거·판정 기준·실행 상태는 `관리`에 모았다. 사업기회 상세에서 공고 조건 검토와 최종 결정 재검토를 열고 같은 사업기회로 돌아올 수 있다. 대시보드에는 마감·최종 결정 대기를 우선 배치했고, 브리핑 응답이 있는 환경에서는 추천과 추적 변화 및 반응 이력 진입점을 보여 준다.

| 항목 | 확인값 |
|---|---|
| 운영 웹 이미지 | `bidops:lifecycle-navigation-20261121-4ec57ff0ca36` (linux/amd64), `sha256:f6ee2f9db6056e258cf2d69afbf76816888774f01a06c4418a830bbe17ff200e` |
| 재현용 소스 | 직전 운영 웹의 프론트엔드 입력에 `backups/lifecycle-navigation-20261121-4ec57ff0ca36-frontend-source.tar.gz`를 프론트엔드 디렉터리 기준으로 적용. SHA-256 `4ec57ff0ca360bd440571c98f853fd2215da1ef614c51ba7a296fca1f507427f`. 직전 운영 이미지에서 정적 프론트엔드 빌드 디렉터리를 교체했다. |
| PostgreSQL 전체 백업 | `backups/postgres/full/bidops-20261121T144135Z.dump` (0600, 114,531,823바이트, pg_restore 목록 TABLE DATA 111개), SHA-256 `a2c1202f7fb841f7ab4df5732c2e043bcd1afca4dcaa2302ab24d5edcccba4c9` |
| 롤백 지점 | Git·Docker 태그 `before-lifecycle-navigation-20261121-4ec57ff0ca36`, 직전 웹 이미지 `bidops:order-plan-paging-20261121-605d8e52b5d5`, 설정 사본 `backups/env-prod-before-lifecycle-navigation-20261121-4ec57ff0ca36` |

운영 웹 컨테이너만 교체했다. web healthy, `GET /api/health` 200, DB revision `0042_engine_run`과 DB·MinIO·워커 컨테이너 ID 보존을 확인했다. 롤백은 운영 설정의 BIDOPS_IMAGE를 직전 웹 이미지로 되돌린 뒤 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`으로 실행한다.

`npm run build`와 변경 경로의 Playwright 검사 17건을 통과했다. 운영 tailnet에서 1280×800·1440×900·1920×1080으로 오늘 할 일과 사업기회 보기 전환을 확인했고, 실제 사업기회의 공고 조건·최종 결정 화면에 진입해 원래 사업기회로 돌아왔다. 운영 브리핑은 미등록 응답(404)과 추천 영역의 미노출을 확인했고, 등록된 브리핑의 추천·반응 이력은 mock에서 검증했다. 운영 확인 중 API 쓰기와 브라우저 예외는 각각 0건이었다.

넓은 화면 회귀 실행에서는 409건 통과, 2건 skip, 43건 실패가 나왔다. 그중 변경된 메뉴·보기·상세 링크의 검사 3건은 새 동작과 검증 코드의 차이를 반영해 통과했다. 나머지 40건은 교체 전 운영 이미지의 정적 빌드에서도 재현됐다.

## 2026-11-22 연결 공고 보기 이동 수정

00:11 KST에 `연결 공고 보기`를 누르면 `사업 흐름` 탭의 `연결된 공고` 목록으로 이동하고 제목에 초점이 가도록 수정했다. 직전 운영 이미지의 프론트엔드 입력에서 `src/components/opportunities/OpportunityDetail.tsx`만 교체해 빌드했다.

| 항목 | 확인값 |
|---|---|
| 운영 웹 이미지 | `bidops:linked-notice-jump-20261122-d03ba5e6d69d` (linux/amd64), `sha256:16f754d60663047a2ac24608bb55e4fbdc608fd68a318bce5f7ac52624627cbb` |
| 재현용 소스 | `backups/linked-notice-jump-20261122-d03ba5e6d69d-frontend-source.tar.gz`, SHA-256 `d03ba5e6d69d4121e85a509a11c8448b6cc6b2e2081f40f376da4b936b5e8766` |
| PostgreSQL 전체 백업 | `backups/postgres/full/bidops-20261121T151033Z.dump` (0600, 114,533,900바이트, pg_restore 목록 TABLE DATA 111개), SHA-256 `5c3334c291ada1df50a6e88b4c6a7402f667420df64fe8f4523ef51d35f3e74d` |
| 롤백 지점 | Git·Docker 태그 `before-linked-notice-jump-20261122-d03ba5e6d69d`, 직전 웹 이미지 `bidops:lifecycle-navigation-20261121-4ec57ff0ca36`, 설정 사본 `backups/env-prod-before-linked-notice-jump-20261122-d03ba5e6d69d` |

웹만 교체하고 `/api/health` 200, DB revision `0042_engine_run`과 DB·MinIO·워커의 컨테이너 ID 보존을 확인했다. 롤백은 BIDOPS_IMAGE를 직전 웹 이미지로 되돌린 뒤 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`으로 실행한다.

변경 경로의 Playwright 검사 2건이 통과했다. 운영에서는 1280×800·1440×900에서 목록으로 스크롤했고, 목록 제목이 이미 화면에 들어오는 1920×1080에서는 위치를 유지한 채 초점을 옮겼다. 같은 탭과 다른 탭에서 모두 확인했다. 별도 최종 Go/No-Go 점검에서는 운영 사례의 대기열에서 공고 조건·결정 입력까지 읽기 전용으로 확인했고, 모의 환경의 결정 저장·정정 충돌·재검토 검사 6건이 통과했다. 운영 검증의 API 쓰기와 브라우저 예외는 각각 0건이었다.

## 발주계획·사전규격 일괄 추적 시작 사유 선택화

2026-11-22 01:10 KST, 직전 웹 이미지 `bidops:linked-notice-jump-20261122-d03ba5e6d69d`를 기준으로 이번 변경을 적용한 `bidops:bulk-start-20261122-e1ebfebf2b3d`로 운영 웹을 교체했다. 웹 healthy, `/api/health` 정상, DB revision `0042_engine_run`과 DB·MinIO·워커 컨테이너 ID 보존을 확인했다.

운영 브라우저에서 두 목록의 항목을 각각 선택해 담당자 입력 후 사유 없이 확인 단추가 활성화되는 것을 확인하고 취소했다. 운영 API 쓰기는 0건이며 발주계획 대상 미리보기만 호출했다. 운영 OpenAPI에서 두 시작 요청의 사유는 선택이고 발주계획 종료 요청의 사유는 필수다. 상태·감사 저장과 재시도 영수증은 배포 전 격리 테스트로 검증했다.

- 전체 백업 `backups/postgres/full/bidops-20261121T160951Z.dump` (0600, SHA-256 `08cfb9090559ecc0a05b0f2da2ce7e6e509f6d3905097387f57723f36ffd3b4c`, TABLE DATA 111개).
- 직전 릴리스 입력에 적용할 변경 소스 `backups/bulk-start-20261122-e1ebfebf2b3d-source.tar.gz` (SHA-256 `e1ebfebf2b3d08b99c22c36e2ffe29db01a20655428c8cf4b3b6f9e88add3e06`).
- 롤백용 Git·Docker 태그 `before-bulk-start-20261122-e1ebfebf2b3d`, 설정 사본 `backups/env-prod-before-bulk-start-20261122-e1ebfebf2b3d`. 롤백 시 `BIDOPS_IMAGE`를 직전 웹 이미지로 복구하고 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`을 실행한다.

## 2026-11-22 최종 Go/No-Go 공고 조건과 검토 대기열

01:31 KST에 운영 웹을 `bidops:gng-conditions-20261122-4a03096c8495`로 교체했다. 직전 운영 웹 `bidops:bulk-start-20261122-e1ebfebf2b3d`에 Go/No-Go·대시보드의 배포 대상 파일을 적용했다. 웹 healthy, tailnet의 `GET /api/health` 정상, DB revision `0042_engine_run`과 DB·MinIO·워커 컨테이너 ID 보존을 확인했다.

운영 API에서 대시보드와 대기열의 검토 대상이 2건으로 일치하고, 사업명·발주기관 검색과 상태별 집계가 동작함을 확인했다. 운영 브라우저에서 1280×800·1440×900·1920×1080으로 대시보드, 목록 미리보기, 공고 조건과 결정 입력을 확인했다. 1440×900에서는 초안이 있는 상태에서 이탈 확인을 열고 계속 편집을 눌러 입력이 유지되는지 확인했다. 검증은 읽기 전용으로 진행했다. 확인한 운영 공고는 단일 차수였으며, 복수 차수의 변경 표시는 격리 환경에서 검증했다.

- 이미지 ID `sha256:e08babfe68c08256f9b1c740159267ca484ba9b907ebe52d1fcbf5b0ef6c9f95` (linux/amd64).
- 변경 소스 `backups/gng-conditions-20261122-4a03096c8495-source.tar.gz` (SHA-256 `4a03096c8495e0807897d7593ec17fa4fc29dba4305219a26b89e1b7fb0f581a`).
- PostgreSQL 전체 백업 `backups/postgres/full/bidops-20261121T163059Z.dump` (0600, 114,533,900바이트, `pg_restore --list`에서 TABLE DATA 111개, SHA-256 `52a902e32074f3bc190ad4fcd4454634fe18ff1a63b7107aa85d0c1e5ae9a621`).
- 롤백용 Git·Docker 태그 `before-gng-conditions-20261122-4a03096c8495`와 설정 사본 `backups/env-prod-before-gng-conditions-20261122-4a03096c8495`를 보존했다. 롤백은 `BIDOPS_IMAGE`를 직전 웹 이미지로 돌린 뒤 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`으로 실행한다.

## 2026-11-22 판정 기준과 회사 근거 화면 개선

02:03 KST에 직전 운영 웹 `bidops:gng-conditions-20261122-4a03096c8495`의 프론트엔드 입력에 이번 화면 변경을 적용해 `bidops:criteria-tracks-20261122-6ff81a5c3a33`로 교체했다. 웹 healthy, tailnet의 `GET /api/health` 정상, DB revision `0042_engine_run`과 DB·MinIO·워커의 컨테이너 ID 보존을 확인했다.

운영 브라우저에서 1280×800·1440×900·1920×1080으로 판정 기준 기본 화면의 활성 C-2 v6, 자동 실행 상태와 최근 성공 실행, C-1 승인 사본 미등록 안내, 회사 근거 미등록 안내를 검증했다. C-2 기본 진입의 C-1 조회는 0건이었다. 1440×900에서는 사본 등록 상태 다시 확인, C-1 정책 탭 이동, 최종 Go/No-Go 미리보기도 확인했다. 운영 검증은 읽기 전용이었다.

- 이미지 ID `sha256:d1d156e20cb7fbca71b29e8d58c49098c4814f6f94ad0bd3ea13885e21694491` (linux/amd64).
- 변경 소스 `backups/criteria-tracks-20261122-6ff81a5c3a33-frontend-source.tar.gz`를 직전 프론트엔드 디렉터리 기준으로 적용했다. SHA-256은 `6ff81a5c3a33e8f0fc36a13abd71b27fff8c2b66609cd5198f92555dea876343`이다.
- PostgreSQL 전체 백업 `backups/postgres/full/bidops-20261121T170159Z.dump` (0600, 114,533,900바이트, `pg_restore --list`에서 TABLE DATA 111개, SHA-256 `cc127479ded46c49380aa115de2872859d7b9b54c1caf0481740ca08f5a81aee`).
- 롤백용 Git·Docker 태그 `before-criteria-tracks-20261122-6ff81a5c3a33`와 설정 사본 `backups/env-prod-before-criteria-tracks-20261122-6ff81a5c3a33`를 보존했다. 롤백은 `BIDOPS_IMAGE`를 직전 웹 이미지로 돌린 뒤 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps --no-build --force-recreate --wait web`으로 실행한다.
