# 2026-11-27 포트폴리오 회사 핏 MVP 반영 (PS-01)

[PS-01](../../work/groups/PS/features/PS-01-company-fit-card/spec.md) "MVP(포트폴리오 적용) 범위"를 포트폴리오 스택(`bidops-portfolio`, 고정 시계 2026-11-27 13:00 KST)에 반영했다. 운영 스택과 모델 호출은 없다.
판정은 Claude 참조 판정이며 모델 결과도 품질 근거도 아니다(`quality_status=unmeasured_reference`, `judged_by=claude_reference`).

## 반영 내용

| 항목 | 값 |
|---|---|
| 승인 | 사용자 2026-11-27 "1번으로 진행해줘"(Claude가 이유까지 재판정), 열거한 반영 계획에 "승인, 반영 진행" |
| 소스 | 포트폴리오 줄기 `3ea6126` + `1cc5e74`(발주계획 필터) 패치 + PS-01 MVP 패치. 빌드 clone은 `bidops-portfolio-fitcard`이고 미커밋이다 |
| 이미지 | `bidops:portfolio-20261127-fitcard`(base `bidops:portfolio-base-20261127-fitcard`, `BIDOPS_PORTFOLIO_ANALYSIS=1`, `BIDOPS_PORTFOLIO_FROZEN_NOW=2026-11-27T13:00:00+09:00`, sitecustomize 층) |
| 롤백 | 이미지 `bidops:portfolio-20261127-1cc5e74-clock1127`, DB 백업 `bidops-portfolio-build/backups/portfolio/portfolio-before-fitcard-20261127.dump`(0600, TABLE DATA 112). 0044 downgrade는 카드 행이 있으면 거부되므로 백업 복원으로 되돌린다 |
| migration | `0043_company_wiki_ingest` → `0044_company_fit_card_lineage`(`migrate.sh`, 권한 재적용 포함) |
| 설정 | web에 카드를 ro로 마운트했다(`env/portfolio-private/business-scope-card.v1.2.yaml`, sha `28750478…eb22`). `BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE=suggest`이고 판정 실행기(`BIDOPS_PRESPEC_COMPANY_FIT_ENABLED`)는 꺼져 있다 |
| 판정 | [`claude_rejudge_1123_1126.json`](../20261127-company-fit-probe/results/claude_rejudge_1123_1126.json)(파일 sha `3815b782…`) 93건을 `import-company-fit-judgments`로 가져왔다. dry-run 93/0 뒤 실제 93/0이고 모두 `completed`다 |

## 재판정

- 방법: 카드 v1.2와 지시문 v3.1로 판정했다. 이전 판정을 보지 않은 Claude 작업 4개가 23~24건씩 맡았다. 결과는 제품 검증기 `validate_result`를 93/93 통과했다.
- 결과: matched 28, unknown 46, mismatch 19.
- [주간 판정](../20261127-company-fit-probe/results/week_1123_1126_claude_judgments.json)과 다른 건이 15건이다.
  - 상주 확인으로 분류했던 4건(4149·4181·4183·4188)은 matched가 됐다. 카드 규칙상 상주 장소가 적혀 있지 않으면 상주로 보지 않는다.
  - HW·NW 비중이 큰 통합유지관리 10건(4155·4174·4373·4374·6378·6393·6405·7291·7293·7310)은 mismatch에서 unknown이 됐다. 카드의 유지관리 경계와 사용자 답(HW·NW 통합유지관리 → unknown)을 따랐다. 이 중 7291·7293·7310은 11-26 gold v2와도 다르다.
  - 6386(교통AI빅데이터 융합플랫폼, 추적 중 시연 건)은 matched에서 unknown이 됐다. 추적 결정은 바꾸지 않았다.

## 확인

- 백엔드 영향 검사(release 이미지, 일회용 PostgreSQL 17.11): 352 passed, 0 failed, 0 skipped.
- 프런트엔드: `npm run build`, `test:contrast` 8/8 통과. Playwright `company-fit.spec.ts`·`pre-specs.spec.ts` 66 passed이고, CSS 수정 뒤 `company-fit.spec.ts` 14 passed.
- 포트폴리오(게이트웨이 캐시를 비운 뒤)
  - 목록 API `workspace=actionable&sort=fit`의 그룹 순서를 검증했다. 엔진 분석 추천 20건이다.
  - 상세 응답은 v2, `lineage=card`, `judged_by=claude_reference`, `is_current=true`다.
  - 1440 캡처: 목록, 분석 완료 상세 4153, 분석 없는 matched 상세 7309.
- 실행하지 않은 것: 전체 백엔드 스위트, `test:screens`(세 폭 overflow·픽셀 기준선), 실제 모델 경로(STEP-009 T14).
