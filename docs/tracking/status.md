# 구현·검증 현황

기준일: 2026-08-31

`구현됨`은 코드와 계약이 존재한다는 뜻이고, `검증됨`은 기록된 명령이 해당 범위에서 통과했다는 뜻이다. Mock 결과, 과거 브랜치 결과, 현재 worktree 결과, 외부 운영 승인을 서로 대신하지 않는다.

## 제품 방향

목표 생애주기는 `발주계획 조기 탐색 → 사전규격 RFP 선별·심층 검토 → 입찰공고 추적·변경 확인 → 사람 최종 Go/No-Go`로 정했다.

- 발주계획과 사전규격은 매일 독립 수집한다.
- 발주계획은 일반용역·기술용역 전체를 수집하고 SW사업대상을 선필터로 쓰지 않는다.
- 발주계획 사람 검토는 월요일·목요일에 수행한다.
- 사전규격은 일반용역·기술용역 전체를 수집하고 SW사업대상은 표시 값으로만 남긴다([ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md)). 저비용 선별 뒤 사람 승인을 거쳐 심층 검토한다.
- 심층 검토 뒤 사람은 `계속 추적|보류|종료`를 선택한다. 입찰공고가 올라오면 사전규격 대비 중요 변경을 확인하고 최종 `Go/No-Go`는 다시 사람이 결정한다.
- 자동 연결 실행과 각 단계의 수동 실행·재시도는 같은 execution, artifact, 상태 전이를 공유한다.

## 현재 구현

| 영역 | 구현 상태 | 검증 상태 |
|---|---|---|
| 기존 나라장터 공고 수집·정규화·표본 | 구현됨 | 파이프라인 단위·교차 테스트의 과거 64건 통과 기록 있음 |
| 다섯 관점·반론·종합 1차 판정 | 구현됨 | fake 테스트와 단일 live Qwen 성공·중단 기록 있음; 40건 운영 품질 승인은 없음 |
| 결정적 HTML·피드백 YAML | 구현됨 | 파이프라인 테스트에 포함됨 |
| FastAPI 회차·공고·리뷰·프로필·지표 | 구현됨 | 통합 backend 검증에서 대부분 통과, 환경 기준선 2건 실패가 남음 |
| 프로필 조회 projection | 현재 snapshots·sections·unknowns가 source path/reference, raw block·raw text, 가공되지 않은 parse error를 노출할 수 있음 | 운영 사용 차단; 승인된 구조화 항목·unknown 전용 v1 projection 미구현 |
| legacy notice 첨부 | 로컬 upload·download는 구현됐으나 scan·quarantine·MinIO와 영속 volume을 우회하고 `stored_path`를 API에 노출 | 운영 사용 차단; 안전 경계 검증 없음 |
| legacy mutation actor·감사 | 리뷰·첨부·포털·run 실행 일부가 actor·audit 없이 변경 가능 | 채택된 attribution 경계 미충족 |
| PostgreSQL 17·Alembic | 공유 worktree head `0015_bid_delta_final_decision`; T-23 revision `0014_prespec_overview_attempt_result` | T-23은 임시 PostgreSQL 17에서 `0014`까지 구조 제약·overview 상태 전이 trigger 1개와 role allowlist를 검증했다. 별도 `0015`의 검증으로 재사용하지 않는다 |
| 누적 관측·첨부 보존 | 신규 observation의 결정적 snapshot/hash와 provider 첨부 retire/revive 구현됨 | 같은 회차 exact replay no-op, 다른 bytes rollback, legacy `null` 보존, 수집에서 사라진 첨부 비삭제 회귀 통과 |
| opportunity authoritative 소유권·병합 | 공식 확정 또는 사람 수락 후보만 active 소유권을 가지며 secondary row를 삭제하지 않는 merge lineage 구현됨 | focused SQLite/API/loader 회귀와 PostgreSQL 17 migration·제약 검증 통과; 추적 선택·recheck 충돌은 자동 병합하지 않음 |
| 판정·사람 리뷰 revision | 현재 projection과 분리된 notice별 append-only 이력, execution·승계 parent·exact judgment pin 구현됨 | replay no-op/conflict rollback, 부분 실패 projection 보존, YAML/SQLite legacy `null` lineage, PostgreSQL 불변 trigger 검증 통과 |
| MinIO·ClamAV·문서 격리 | 구현됨 | Mock T7 E2E 통과; 실제 운영 권한 matrix는 미검증 |
| document bundle·준비 API | 7개 Lean API와 attachment version/current·bundle ordinal DB 제약 구현됨 | backend 테스트, PostgreSQL migration/preflight/autogenerate, Mock E2E 통과 |
| 3단계 심층 검토·보고서·근거 API | 7개 Lean API 구현됨 | deterministic Mock provider E2E 통과; 실제 Qwen 품질 승인은 없음 |
| React 관리자 화면 | 기존 공고·판정·ready bundle 이후 심층 검토 구현됨 | production build와 visual 통과 기록 있음 |
| 문서 준비·실패 attempt 재시작 화면 | typed frontend API·type 변경은 worktree에 있으나 화면과 연결은 미구현 | 화면 검증 없음 |
| T-23 사전규격 overview phase 2 기반 | immutable result/event, 제한된 attempt lifecycle service, safe v2 projection 구현됨; 실제 model transport·worker는 미구현 | SQLite 46 passed·1 PostgreSQL-only skipped, PostgreSQL 17 집중 9 passed, production build 282 modules |
| T7 stack 조립 | PostgreSQL, MinIO, ClamAV, web, document worker, analysis worker, 일부 영속 volume, 목적별 egress overlay 구현됨 | 개발 stack health와 Ollama endpoint 도달 기록은 있으나 보안·복구 blocker로 운영 배포 불가 |
| 구조화 안전 로그 | 기반과 주요 worker·queue·scheduler 계측 구현 중인 worktree 변경 | 신규 단위 테스트 일부 통과 기록, 현재 전체 worktree green 아님 |
| 개발용 hosted Codex 심층 검토 reference | 기본 비활성·notice allowlist 경로가 구현돼 있으나 허용 payload 정책과 충돌 | 사용 금지 blocker; RFP·회사 profile 전송 차단 검증 없음 |
| runtime image 회사자료 제외 | Dockerfile 주석은 제외를 주장하지만 실제 copy가 profile 파일을 포함 | blocker; image 내용 회귀 검증 없음 |
| backup·object-first restore script | 초안은 있으나 target version mapping과 active manifest 계약이 불완전 | 정적 결함이 있어 복구 가능 상태가 아니며 실제 훈련도 없음 |

T-23 `0014` 검증 경계의 PostgreSQL application schema는 legacy 13개, 심층 검토 25개,
판정 runtime 12개, 누적 identity 5개, 첨부 fetch 1개, 판정·리뷰 revision 2개, 사전규격
overview 5개로 총 63개 table이다. `0015`가 더한 입찰 delta 5개는 이 수치와 T-23 검증
증거에 포함하지 않는다. 그 5개를 합친 현재 head `0015_bid_delta_final_decision`의 application
schema는 68개이며, 별도로 빈 PostgreSQL 17 `upgrade head`와 `0014↔0015` 왕복을 검증했다.
입찰 delta는 저장·REST·화면까지 있으나 비교를 실제로 계산하는 worker와 모델 binding 실행이
없어 운영 활성화 상태가 아니다. SQLite는 격리 테스트와 일회성 이전 입력에만 남아 있다.

## 기록된 검증 증거

### 현재 통합 소스 기준

| 검증 | 기록된 결과 | 해석 |
|---|---|---|
| frontend `npm run build` | 성공, Vite 6.4.3, 282 modules | 현재 통합 UI production build |
| T-23 사전규격 상세 Playwright | 32 passed | 네 viewport에서 정본 ID, unknown, 교차 ID fail-closed, 안전 오류를 검증 |
| frontend visual update·비갱신 | 각각 184개 중 174 passed, 10 intentional skipped | 네 viewport의 통합 UI 기준선 |
| backend pytest 초기 통합 리뷰 | 733 passed, 5 skipped, 2 failed | 실패 2건은 현재 Git history에 승인 baseline blob이 없는 환경 문제 |
| Phase 0–2 변경 후 backend | 741 passed, 5 skipped, 같은 2 failed | 로깅·Compose 변경 뒤 통과 수 증가, 전체 green은 아님 |
| MVP DB 보완 후 backend + PostgreSQL 17 | 948 passed, 5 skipped, 6 failed | DB·migration·revision·권한 회귀는 통과. 실패는 T14 전용 환경변수/격리 DB 미설정 4건과 승인 baseline Git blob 부재 2건 |
| MVP DB 최종 집중 회귀 + PostgreSQL 17 | 155 passed | fresh `0001→0013`, downgrade-upgrade, preflight, revision, 문서 무결성, overview 최소권한, Alembic autogenerate를 교차 검증 |
| T-23 최종 집중 회귀 + PostgreSQL 17 | 85 passed | overview 권한·절단·계보·migration·문서 무결성을 최종 변경 뒤 실제 role로 재검증 |
| T-23 phase 2 DB-light 집중 회귀 | SQLite 46 passed·1 PostgreSQL-only skipped; PostgreSQL 17 9 passed | result/event·상태 전이 service·v2 projection·runtime privilege와 단일 상태 간선 trigger를 검증; 전체 backend green을 뜻하지 않음 |
| T14/profile harness 최종 backend + PostgreSQL 17 | 992 passed, 5 skipped, 6 warnings | 최소 환경에서 임시 PG17·fresh DB·Alembic head를 자동 구성. T14 4건은 해결됐고 profile 2건은 승인 Git blob 부재를 fail-closed로 검증 |
| T7 stack V2 | services healthy, `/api/health` 성공, 구조화 worker log 관측, 승인 Ollama endpoint 도달 | 기동·관측·network 경계 검증; 실제 판정 품질 검증 아님 |
| static diff check | 당시 통합 UI 변경에서 성공 | 이후 worktree 변경의 전체 검증으로 재사용하지 않음 |

최근 끝까지 완주한 backend 전체 suite는 1033 passed, 5 skipped, 6 warnings이며
실패 0건이다(2026-08-31, 연속 2회 확인).
저장소 `.env`를 상속하지 않은 최소 환경에서 일회용 PostgreSQL 17 server, random DB,
Alembic head, 임시 data·attachments 경로를 pytest 수집 전에 구성했고 종료 후 소유
container가 남지 않음을 확인했다. skip 5건은 별도 MinIO가 필요한 4건과 target
container 경로에만 적용하는 installed-set 1건이다.

승인 profile baseline commit `ee621835db934ddac944f7a07a986ed0b73ecc7a`는 현재 Git object
DB에 없다. 다만 byte-identical 파일이 `web/backend/app/screening/baseline_company_profile.md`로
벤더링돼 있고 `BASELINE_PROFILE_SHA256`으로 검증되므로 `test_profile_snapshot*` 14건은
모두 통과한다. 2026-08-31 결정에서 이 상태를 그대로 두기로 했다. 이 commit은
`model_comparison` 품질 gate 전용 역사 anchor이며 운영과 무관하다 —
`operational_approval`은 `profile_source = "current"`를 요구하고 런타임의
`snapshot_current()`는 현재 `docs/reference/company-profile.md`
(sha256 `96731dd5f77d…`)를 읽는다. 두 경로는 의도적으로 분리돼 있다.

### 보존된 과거 증거

- 기존 pipeline 테스트는 collect 28, report 13, screen 21, root 2로 총 64개가 통과했다. 현재 변경 전체의 통과로 간주하지 않는다.
- Deep Review Mock T7 E2E는 PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web에서 `passed=true`였다. 외부 모델 호출은 없었고 Qwen 품질 근거가 아니다.
- 실제 Ollama 단일 판정은 한 번 실패한 뒤 generation binding을 고정한 재실행에서 7개 logical stage, 8 attempts, v3 judgment 1건으로 성공했다. 별도 stop 실행도 중단 artifact를 보존했다. 40건 A/B와 운영 activation을 뜻하지 않는다.
- 사설 vLLM 후보는 제한된 구조화 입력에서 호출·validator 통과 기록이 있으나 server image와 model artifact digest가 아직 immutable하게 고정되지 않았다.

## 진행 중 작업 기록

발주계획·사전규격·입찰공고 생애주기 구현의 확정 사실, 대기 중인 결정, 할 일과 끝낸 일은
[`lifecycle-workstream.md`](lifecycle-workstream.md)에서 갱신한다. 아래 순서의 6~10번이 그 범위다.

## 다음 작업 순서

1. hosted Codex deep-review reference, runtime image의 회사자료 포함, profile 원문·경로 API 노출, legacy unsafe·비영속 첨부 upload을 차단한다.
2. MinIO versioning fail-open, host-wide DB·MinIO port publish, 불완전 객체 복구, legacy mutation actor·audit gap을 수정하고 보안·복구 통합 검증을 한다.
3. screening v3를 보고서 renderer에 명시적으로 연결한다.
4. 고정 3일 발주계획 모집단으로 BM25, 한국어 dense bi-encoder, 두 결과의 RRF 하이브리드 비교 실험을 실행하고 사람이 최종 정답을 판정한다([ADR-0021 개정](decisions/0021-filter-experiment-before-implementation.md)). 착수 전에 PostgreSQL·객체 backup과 빈 대상 restore를 한 번 검증한다.
5. 방식별 recall, precision, 검토량, 중요 누락, 순위 품질, 비용, 지연, 재현성을 보고서로 남기고 운영 방식·threshold를 선택한다. 단독 arm이 놓친 건을 하이브리드가 복구하는지를 채택 근거로 삼는다.
6. 전체 발주계획 원본과 방식별 결과를 저장하는 불변 수집 회차·DB 계약을 구현한다.
7. 내부 opportunity와 plan·pre-spec·bid 공식 관계, 사람 확인 대기 relation 후보를 구현한다.
8. 사전규격 독립 일일 수집, 저비용 1차선별, 사람 심층 검토 승인 gate를 연결한다.
9. document preparation 화면과 실패 deep-review attempt 재시작 화면을 완성한다.
10. `계속 추적|보류|종료`, 입찰공고 발견, 사전규격 대비 material delta, 최종 사람 Go/No-Go를 구현한다.
11. 개발계정 API 요청 수를 실측하고 운영계정 활용사례·증액 근거를 준비한다.
12. 실제 model artifact digest, 대표 HWP/PDF gold, 사람 판정으로 Qwen·vLLM 품질 gate를 측정한다.
13. 실제 secret, MinIO allow/deny, egress firewall, PostgreSQL·객체 backup과 빈 대상 restore를 운영 환경에서 검증한다.
14. 이후 범위로 SSO·역할 권한과 dashboard·외부 알림을 설계한다.

2026-08-31에 D-5~D-11을 전부 결정했으므로 사람 결정을 기다리는 항목은 없다. 위 순서에
앞서 오늘 할 수 있는 것이 셋 있다 — D-9 첨부 URL 수명 횡단면 측정(보존된 나이 6구간
raw에서 각 30개, 180 GET), D-11 PostgreSQL 테스트 필수화, D-7 방화벽 승인 절차 상신이다.
D-8 종단 관측은 2026-09-08·09-14에 계속 받는다.

위 단계 전에는 hosted OpenAI 자동 fallback, scheduler·always-on 자동 활성화, 자동 입찰 제출, 발주처 연락, 모델의 최종 참여 결정을 추가하지 않는다.
