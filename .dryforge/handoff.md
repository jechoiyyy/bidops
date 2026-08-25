# 실행 인계: 첨부문서 심층 검토 Lean v1

> 상태: Lean v1 최종 승인·동결 — 구현 미착수, `dryforge go` 미실행
> 출발 commit: `3e076156b44d5e13a12fbf14dc733075fb8b8ab3`

## 문서 우선순위

1. `.dryforge/spec.md`: 제품·API·상태 계약
2. `docs/deep-review-erd.md`: DB 컬럼·제약·이관·삭제 계약
3. `.dryforge/plan.md`: 7개 구현 작업과 파일 소유권
4. 기존 코드/docs: 보존할 현재 계약

네 문서가 충돌하면 임의 구현하지 않고 권위 문서를 함께 수정한 뒤 승인받는다.

## 작업 위치

- worktree: `/home/jechoi/orca/workspaces/side/bidops-deep-review`
- project: `/home/jechoi/orca/workspaces/side/bidops-deep-review/bidops-agent`
- branch: `bidops-deep-review`
- 메인 `/home/jechoi/projects/side`의 사용자 변경은 읽기 전용 참고만 허용한다.
- 현재 worktree 밖의 파일을 복사·수정·삭제·정리하지 않는다.

## 최종 승인·go 직전 기준선 (2026-08-25)

- 사용자 최종 승인 완료. 승인 기준선 ID는 `bidops-deep-review-lean-v1-2026-08-25`다.
- 승인 당시 base commit은 `3e076156b44d5e13a12fbf14dc733075fb8b8ab3`이며, 최종 설계
  기준선 commit은 이 인계 파일을 추가한 `docs(bidops): freeze lean deep-review design`이다.
- 충돌 marker와 unmerged index는 없다. 승인 대상은 이 파일, `.dryforge/spec.md`,
  `.dryforge/plan.md`, `docs/deep-review-erd.md`, `docs/deep-review-cold-session-handoff.md`뿐이다.
- `./run-tests.sh`: 64 passed.
- backend: 현재 worktree를 복사한 별도 Docker image에서 37 passed, 1 skipped. skip은 실제 회차
  산출물이 이 worktree에 없기 때문이고, Starlette/httpx deprecation warning 1건이 있다.
- frontend: `npm ci`, production build와 Docker image 내부 build 통과.
- 호스트 `python3-venv`/ensurepip가 없어 `./web/run-web-tests.sh`는 pytest 시작 전 중단된다.
  이는 코드 실패가 아니며 Docker 격리 실행으로 backend와 frontend를 각각 검증했다.
- Docker 29.7.2/Compose 5.5.0은 사용 가능하다. 실행 중인 `bidops-agent-web-1`은 메인
  worktree 소유라 조회만 했고 컨테이너·volume을 변경하지 않았다.
- 호스트와 현재 container 목록에는 PostgreSQL 17, MinIO, ClamAV, Ollama가 없다. 이는 확정
  설계의 미결정 사항이 아니라 T1/T2/T3/T5/T7이 현재 worktree 전용 compose와 고정 version을
  추가한 뒤 수행할 integration prerequisite다.
- 현재 worktree `web/data/`에는 이관 원본이 없다. 메인 worktree DB를 read-only로만 검사한
  결과 `PRAGMA quick_check=ok`, legacy 13개 table/총 789행이며 attachment 149행은 모두
  G2B URL-only, 저장 원문 0개, size 미상이다. 메인 DB나 첨부를 복사하지 않았다.
- T1 이관은 메인 live DB를 직접 읽지 않고 사용자가 지정한 SQLite backup API snapshot으로
  수행한다. URL-only provider 원문은 T3 allowlist connector의 취득·quarantine·검사 없이는
  ready로 전환할 수 없다.

## Lean v1 확정안

1. 유효 등급 `우선 검토` 공고만 심층 검토 대상이다.
2. 담당자의 문서 준비 완료 확인 전에는 분석을 시작하지 않는다.
3. ready bundle item은 content/structure hash와 출처·역할·날짜·대체·최신본·safety를 고정한
   immutable snapshot이다.
4. 새 파일·정정 파일은 새 document version, bundle, deep review를 만들고 과거 결과를 보존한다.
5. PostgreSQL 17 database/schema `bidops`가 정본이고 SQLite는 일회성 이관 원본이다.
6. 기존 SQLite 13개 테이블/모든 컬럼/integer PK/reviewer snapshot을 전량 보존하고
   `migration_staging` reconciliation 후 sequence를 보정한다.
7. 신규 테이블은 document 8, knowledge 3, analysis 11, ops 3으로 총 25개다.
8. 이름 입력은 `claimed_name` snapshot 문자열이다. v1에 actor 테이블이 없고 이름은 인증·권한이 아니다.
9. HWP 원본은 보존하고 격리된 headless 변환기로 HWPX로 바꾼다. HWPX/PDF/image는 제한형
   격리 처리기에서 구조화하고 전체 JSON을 정본으로 저장한다.
10. upload는 quarantine에서 시작하며 MIME/magic/archive/PDF/ClamAV를 모두 통과해야 source로 간다.
    bytes가 없는 provider 첨부는 source-system별 allowlist connector만 취득하고 임의 URL fetch는 없다.
11. v1에는 수동 malware release가 없다. 검사 불가·불확실은 계속 quarantine이다.
12. OCR 오류는 unknown 또는 정정 파일 재업로드로 처리하고 인앱 text correction을 만들지 않는다.
13. profile/policy는 server import CLI가 immutable version을 만들고 active ID는 배포 설정에서 고정한다.
    v1 심층 분석 기준은 사용자 편집 대상이 아니며, 향후 UI 편집은 저장마다 새 version을 만든다.
14. profile evidence는 v1에서 안전한 업로드 파일만 허용하고 URL capture는 없다.
15. Qwen 분석은 요구·평가 / 수행·위험·경제성 / 종합·검증의 3개 업무 stage다. stage 안에서는
    문서·요구사항별 bounded invocation과 결정적 병합을 사용하며 전체 원문 단일 prompt는 금지한다.
16. deep review와 attempt를 분리하고 active attempt/job partial unique와 lease fence를 사용한다.
17. fence는 조건부 SQL로 강제하고 전용 stored function·복잡한 table별 DML revoke는 만들지 않는다.
18. document evidence는 ready bundle, profile evidence는 pinned profile version 범위를 복합 FK로 강제한다.
19. fact는 evidence, calculation은 식·입력 근거, inference는 premise·근거가 필수다.
20. 최초 machine 결과와 사람 수정은 모두 완전한 immutable report revision JSON이다.
21. delta overlay, 별도 machine report/edit table과 validation join matrix는 만들지 않는다.
22. factual revision은 evidence/reason과 재검증이 필요하다.
23. final opinion은 시스템 권고와 분리하고 validation run/status snapshot을 고정한다.
    시스템 권고는 `추진 검토|조건부 추진 검토|보류|검토 종료`, 사람 의견은
    `추진|조건부 추진|보류|검토 종료`다.
24. FK는 RESTRICT가 기본이고 판정 내부 detail/verification answer만 제한 CASCADE,
    attachment 보조 FK만 SET NULL이다.
25. idempotency는 재실행 피해가 있는 핵심 async mutation에만 적용하고 v1에서 자동 purge하지 않는다.
26. 정본 데이터는 자동 삭제하지 않고 범용 retention purge/hold control plane을 만들지 않는다.
27. raw model response bytes만 암호화 bucket lifecycle로 90일 보존한다.
28. Langfuse는 단계 2 선택 사항이며 v1 배포 필수가 아니다.
29. RPO 4시간/RTO 8시간, daily full+WAL, 최소 4시간 object copy를 독립 장애 도메인에 둔다.
30. backup 보존은 daily 14일/weekly 8주/monthly 6개월이며 앱 DB에 backup control table을 만들지 않는다.
31. object→PostgreSQL→active hash 검증 순서로 production 전 및 분기별 restore drill을 수행한다.
32. 초기 용량은 PostgreSQL 4 vCPU/16 GiB/200 GiB, MinIO usable 1 TiB와 월 약 96만 block 가정이다.
33. 보고서는 필수 section과 자격·요구사항·평가 matrix, 수행 계획·경제성 시나리오, 한 화면
    decision card를 포함하고 위험 심각도는 `차단|중대|보통|낮음`이다.
34. policy active 지정 전 고정 표본에서 재현율 80%, 사람 판정 일치율 70%, 근거 부족 오판율
    10% 이하를 검증한다.
35. ready bundle은 모든 non-retired attachment를 포함해야 한다. provider 원문 취득 실패·누락은
    대체 파일 등록 또는 근거 있는 retirement 전까지 blocking issue다.

## 단계 2로 연기

- Langfuse self-host stack
- profile/policy CRUD·activation UI/API
- URL capture/SSRF fetcher
- 수동 malware release
- 인앱 OCR correction
- cross-review compare/import
- 범용 retention purge/hold
- backup checkpoint/restore drill DB table
- SSO identity/attribution link
- 전문검색/vector/partitioning/table-cell projection

이 항목은 별도 사용자 승인 없이 선구현하지 않는다.

## 구현 중 바꾸면 안 되는 경계

- content hash와 document version을 합치지 않는다.
- ready bundle을 live document projection으로 대체하지 않는다.
- 분석 stage에서 문서 변환/OCR을 다시 하지 않는다.
- bundle/profile 밖 evidence를 허용하지 않는다.
- 모델 output을 schema·결정적 검증 없이 report로 완료하지 않는다.
- validation 실패 label을 사람 의견으로 제거하지 않는다.
- 새 분석에 이전 사람 revision/opinion을 자동 승계하지 않는다.
- quarantine object를 viewer/Qwen에 노출하지 않는다.
- PostgreSQL 쓰기 개방 뒤 SQLite로 단순 rollback하지 않는다.
- claimed name을 인증·권한·실제 동일인으로 표현하지 않는다.
- 메인 worktree 사용자 파일을 덮어쓰지 않는다.

## 시작 전 확인

- `git status --short`, conflict, 기준 commit과 worktree 경계를 기록한다.
- 2026-08-25 최종 승인과 기준선 commit을 확인한다. 이 인계 시점에는 구현·`dryforge go`가
  아직 실행되지 않았다.
- PostgreSQL 17 개발 인스턴스와 SQLite read-only backup을 확인한다.
- legacy column/file manifest와 capacity report를 만든다.
- MinIO 목적별 bucket/credential과 ClamAV/Ollama 가용성을 확인한다.
- 현재 backend/frontend test baseline을 기록한다.

## 실행 순서

1. T1 PostgreSQL/이관, T2 문서 처리기를 병렬 시작한다.
2. T1 뒤 T4 schema/validator, T1+T2 뒤 T3 asset/bundle을 진행한다.
3. T1+T3+T4 뒤 T5 Qwen 분석을 진행한다.
4. T5 뒤 T6 report API/UI를 진행한다.
5. T7이 공용 등록·배포·문서·전체 회귀를 단독 통합한다.

## 완료 보고

각 task는 변경 파일, 구현 계약, 테스트 결과, 환경 의존 실패, 남은 위험과 다음 입력을 남긴다.
최종 완료는 준비 완료 공고에서 안전 검사→ready→3단계 분석→원문 근거→full revision 재검증→
최종 의견→새 file의 새 계보까지 브라우저에서 재현될 때만 인정한다.
