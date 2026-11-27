# 2026-11-27 회사 핏 v2 코드 운영 배포 (기능 꺼짐)

PS-01 MVP 코드(`6b4b19a`)를 운영에 배포했다. 사용자 결정은 "코드만 배포, 회사 핏 꺼둠"이다.
카드 파일은 붙이지 않았고 `BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE`도 설정하지 않았다(기본 `off`). 운영 DB에는 판정을 넣지 않았다.
**코드 배포를 기능 활성화나 품질 합격으로 적지 않는다.**

| 항목 | 값 |
|---|---|
| 승인 | 사용자 2026-11-27 "커밋푸쉬하고, 포폴/운영에 배포해줘", 범위 질문에 "코드만 배포, 회사 핏 꺼둠" |
| 소스 | `6b4b19a`(origin/main) 위에 `feat/today-c2`의 `71aff8b`·`7fc035b`(오늘 할 일 화면, 다른 세션 작업, main 미병합)를 cherry-pick했다(로컬 `feaafd3`·`2ce0d7b`). 직전 운영 web에 이미 오늘 할 일 화면이 있었기 때문이다. 릴리스 트리는 `bidops-release-fitcard`의 `release/fitcard-today-20261127`이고 push하지 않았다 |
| 이미지 | `bidops:main-20261127-2ce0d7b`(linux/amd64). web·analysis-worker·prespec-attachment-worker를 함께 교체했다. 세 직전 이미지(`71aff8b`·`5e8f7a1`·`ab08343`)는 모두 시작할 때 DB head `0043`을 요구하므로 함께 바꿨다 |
| DB | `BIDOPS_ENV=prod scripts/compose.sh run --rm --no-deps migrate` exit 0. `0043_company_wiki_ingest` → `0044_company_fit_card_lineage` |
| 백업 | `backups/postgres/full/bidops-20261127T043707Z.dump`(`run --rm --no-deps ro-backup`, 0600, TABLE DATA 112). postgres 컨테이너 Created는 그대로다 |
| 롤백 | `.env` 사본 `backups/env-prod-before-fitcard-20261127`. 이미지 태그 `bidops:before-fitcard-20261127-web`·`-worker`·`-attachment`, git 태그 `before-fitcard-20261127`(`65a82d5`). 카드 행이 없으므로 0044 downgrade가 가능하다 |
| 확인 | health 200, 대시보드 200. 세 컨테이너 2분간 오류·예외 로그 0줄. `GET /api/pre-specs?workspace=actionable&sort=fit`는 200이고 모든 행이 `pending`이다. `GET /api/pre-specs/{id}/company-fit`는 v2이며 `mode=off`, `reason_code=company_fit_disabled`, `engine_suggested=false`다 |

## 남은 것

- 운영에서 켜려면 PS-01 원래 범위의 감사 모드 스위치(테이블·REST·CLI), STEP-009 실제 모델 재현, 카드 마운트, 그리고 각 단계 직전 승인이 필요하다.
- main checkout(`/Users/temp/orca/bidops`)의 로컬 `main`은 아직 `65a82d5`다. origin/main은 `6b4b19a`다. checkout에 다른 사람의 미커밋 작업이 있고 그중 4개 파일(`api.ts`·`types.ts`·`lifecycle-rest.md`·`queue.json`)이 이번 변경과 겹쳐서 당겨오지 않았다.
- `feat/today-c2`는 main에 병합되지 않았다. 운영 소스에는 cherry-pick 사본으로 들어 있다.
