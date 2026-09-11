# 사전규격 수집·개요 검토 안정화 구현 계획

작성일: 2026-09-10 · 상태: MVP 운영 반영·Qwen 초안4건 실행 완료, 모두 사람 검토 필요·최종 개요0건, OFF

시작 문서: [ADR](ADR.md) → [Requirements](Requirements.md) → [Spec](Spec.md) → [Design](Design.md)

## 채택한 실행 방향

규칙 검사와 Qwen 의미 검토를 함께 적용한다. 미검증 주장이 남으면 전체 개요를 사람 검토로 보내며, v4 중지는 대기 작업 취소와 실행 중 결과 게시 차단을 포함한다. 사실 불일치의 자동 수정은 하지 않고 형식 재생성만 한 번 허용한다. 최종 개요는 검증된 문장으로 구성한다.

먼저 불변 수집과 상태·데이터 계약을 정리하고, 검증기·worker·API·웹을 연결한다. 각 작업에서는 수정 범위에 필요한 검증만 마친 뒤 다음 작업으로 진행한다. 사설 Qwen 실사용 참조 검증은 구현 게이트 이후에 진행하고, 모든 작업과 필요한 검증을 마친 뒤 최종 리뷰를 수행한다.

## 구현·검증 범위 원칙

2026-09-10 사용자 요청에 따라 아래 원칙을 각 작업의 검사 목록보다 우선 적용한다.

- **수정한 부분만 검증한다.** 변경한 함수·상태·계약·화면과 그 변경이 직접 영향을 주는 호출부·소비자로 범위를 한정한다. 각 절의 “관련 검사”는 검사 위치를 찾는 목록이며 나열한 파일 전체를 매번 실행하라는 뜻이 아니다. 변경과 연결되지 않는 모듈·화면·모델 경로는 검사하지 않는다.
- **검증이 통과하면 다음 작업으로 넘어간다.** 이후 변경·새 실패·미해결 위험이 없으면 같은 테스트·빌드·화면 확인을 반복하지 않는다. 실패 시 원인과 변경 관련성을 먼저 확인하고, 수정 후에는 영향받은 검사만 다시 실행한다. 마지막에 앞선 검사를 일괄 재실행하지 않는다.
- **필요한 실패 방지 검사만 추가한다.** 기존 테스트·fixture·실행 도구를 우선 사용하고, 재현한 결함과 변경된 계약의 경계를 확인하는 사례를 보완한다. 구현을 그대로 따라 쓰는 테스트, 중복 사례, 별도 테스트 프레임워크·과도한 일회성 검증 도구는 만들지 않는다. 변경한 DB 제약·권한·동시성·원본 불변성·전송 경계의 검사는 유지한다.
- **기존 구조를 활용하고 필요한 만큼만 구현한다.** 네 문제의 해결과 채택한 주장 검증에 필요한 변경만 한다. 미래 확장을 위한 범용 추상화·플러그인 구조·새 scheduler·무관한 리팩터링은 추가하지 않는다. 새 테이블·서비스·설정은 기존 구조로 요구를 충족할 수 없는 구체적인 이유와 소비자가 있을 때만 도입한다. 더 단순한 구현으로 같은 계약을 보장할 수 있으면 관련 설계 문서도 함께 맞춘다.
- **검증 범위와 결과를 짧게 남긴다.** 작업마다 변경 내용·실행한 검사·결과·남은 한계를 기록한다. 문서만 바꾸면 diff와 내용만 확인하며 앱 테스트·빌드·모델 호출을 하지 않는다.

## 작업 순서와 세분화 기준

착수 확인 → 불변 수집과 호출부 → 새 계약·DB·정책 → 주장 검증과 최종 구성 → worker 복구·중지·배정 → API·웹·후속 소비자 → 변경 경계 연결 확인·문서 동기화 → 사설 Qwen 실사용 참조 검증 → 최종 리뷰 순으로 진행한다. 전환·복구 절은 배포가 필요한 시점에 적용하는 절차다.

각 작업은 **수정 범위 확인 → 구현 → 해당 변경 검증 → 완료 항목 표시**로 진행한다. 별도 phase 번호나 반복적인 계획·리뷰 단계를 추가하지 않는다. 현재 작업별 체크리스트가 세부 실행 단위다. DB 제약과 코드 소비자, worker 중지와 결과 게시처럼 선후 의존성이 있는 부분만 해당 작업 안에서 하위 체크 항목으로 명시한다. 단계 사이에 전체 리뷰를 반복하지 않고 최종 리뷰는 마지막에 모아 수행한다.

## 착수 확인

- [x] 변경 직전 `git status`, Alembic head, 가장 가까운 AGENTS와 핵심 계약을 확인한다. 기존 사용자 변경·회차·변환 작업은 보존한다.
- [x] [findings](../tracking/findings.md)의 네 합성 재현을 관련 테스트에 고정한다. 기존 실패와 이번 변경 회귀를 구분한다.
- [x] 수집기의 모든 CLI 호출부와 새 개요 결과의 모든 소비자를 `rg`로 확인한다. 특히 폴더 선생성, bool `--from-raw`, v3 전용 parser, terminal 상태 목록, DB 권한 allowlist를 목록화한다.
- [x] 새 정책의 schema·stage별 generation·주장/인용 크기·context 상한을 fixture로 고정한다. 기존 승인 context 안에서 정상/상한 초과 입력을 확인하고 호출 상한 3회와 1,200초 lease를 함께 검사한다.

완료 조건: 수정 경로·소비자·버전과 검증 표본이 정해져 있고 승인되지 않은 실행을 시작하지 않는다. 본 계획의 기술 수치는 fake 검증에서 변경 필요성이 확인되면 Spec과 함께 수정한다.

착수 확인(2026-09-10): `main`의 `b4dcd7a`에서 추적 파일 변경 없음, Alembic head는 `0024_section_candidates`였다. 미추적 `backups/`와 기존 수집 회차 6개는 보존 대상으로 제외했다. 수집 호출부는 lifecycle pipeline·screening runtime·교차 적재 검사, 개요 소비자는 page overview 조회·회사 핏·자동 준비 projection·웹 타입/상세 화면·runtime 권한 allowlist를 확인했다. 독립적인 수집, schema/정책, DB 작업은 파일 소유를 나눠 병렬 진행하며 통합과 완료 표시는 이 문서에서 관리한다. 실제 모델 전송·운영 migration·정책 활성화는 아직 수행하지 않았다.

## 불변 수집과 호출부 수정

- [x] `collect_notices.py`가 새 출력 디렉터리를 원자적으로 획득하게 하고 raw·최종 JSON을 배타적으로 쓴다. 키·HTTP보다 경로 검사가 앞서도록 한다.
- [x] `--from-raw SOURCE_RAW` 계약을 구현한다. 원본은 읽기만 하고 새 회차에 검증·복사한다. 기존 bare flag에는 새 사용법을 안내한다.
- [x] lifecycle pipeline의 출력 폴더 선생성과 symlink를 제거하고 screening runtime·예약 실행·운영 명령의 인자를 함께 수정한다. 웹 `from_raw` 입력 의미는 유지한다.
- [x] 일부 수집 실패·기존 raw 재분류·동일 출력 경로 경쟁·기존 빈 폴더·symlink 거부를 검사한다. 날짜 포함/제외 경계와 정규화 v2를 유지한다.

관련 검사: `skills/bidops-collect/tests/test_collect_notices.py`, `test_collect_order_plans.py`, `web/backend/tests/lifecycle/test_pipeline_service.py`, `tests/screening/test_scheduled_pipeline.py` 및 수집 subprocess 계약을 쓰는 API 검사. 파이프라인 파일 경계를 바꾸므로 해당 교차 파이프라인 검사도 포함한다.

완료 조건: 기존 파일 hash 유지, 경로 경쟁의 패자 HTTP 0회, 새 회차만 생성, 웹·예약 호출과 collector의 생성 책임 충돌 없음.

검증(2026-09-10): 저장소 루트의 `python3 -m unittest discover -s skills/bidops-collect/tests -p test_collect_notices.py -q` 35건, 같은 명령의 `test_collect_order_plans.py` 8건, `-s tests -p test_pipeline.py` 2건 통과. backend의 `BIDOPS_DATABASE_URL=sqlite:///:memory: BIDOPS_TEST_MODE=1 .venv/bin/python -m pytest tests/lifecycle/test_pipeline_service.py tests/screening/test_scheduled_pipeline.py tests/app/test_api_pipeline_service_t9.py -q` 22건 통과(기존 deprecation/schema warning 8개). raw 목록 접근 보강 뒤 실제 subprocess 재분류 1건만 재확인했다. 고유 검사 67건이며 초기 불변성 재현 2건의 예상 실패를 수정했다. 운영·E2E·수집 스킬·웹 README 예제와 파일 계약을 동기화했고 스킬 `quick_validate.py` 및 `git diff --check`도 통과했다. live HTTP·운영 적재는 실행하지 않았다.

추가 저장 경계: 최종 JSON 쓰기 실패가 provenance `complete=true`를 남기는 결함을 재현했다. 최종 저장 뒤 완료 provenance를 기록하고 실패 시 `complete=false`를 보존하도록 수정했다. 신규 `final_write_failure` 예상 실패 후 해당 검사와 직접 영향받은 `reclassification_copies`/`partial_http`만 3건 통과. 고유 collector 사례는 36개(수집/호출부 합계 68개)이며 원본 데이터는 변경하지 않았다.

## 새 계약·DB·정책 기반

- [x] 초안·검증 v1, 결과 v4, 조회 v2, 정책 v5, activation v2를 Spec대로 정의한다. 과거 schema parser와 명확히 분리한다.
- [x] 현재 Alembic head 다음 migration을 추가한다. attempt 상태 길이/제약/불변 트리거·activation 참조, 결과 버전, call/검증 테이블과 FK·중복 방지·불변성을 함께 구현한다. 기존 migration 파일은 수정하지 않는다.
- [x] `scripts/runtime-privileges.sql`에 table별 SELECT/INSERT 및 필요한 상태 전이 권한을 추가한다. 중지 CLI가 기존 app/worker 소유권 경계 안에서 정상 취소할 수 있는지도 검증한다.
- [x] 기존 완료·실패·참조 결과와 단일 응답 hash를 보존한다. 기존 queued/running을 새 정책으로 자동 전환하는 migration은 넣지 않는다.
- [x] 새 policy의 두 prompt·schema·호출 예산·검증기 버전을 digest에 고정하고 activation 미리보기에 양쪽 stage와 최대 호출 수를 명시한다.
- [x] 추가 요구: 5,000자 일괄 차단을 제거하고 두 단계 실제 요청·확인된 context·출력 예약·기존 payload 상한으로 허용량을 판단한다. 전체 선택 원문을 보존하고 해당 단계 전송 전 용량 초과를 기술적 미실행으로 분류한다. 두 단계 경계와 직접 호출부만 격리 검증한다.

관련 검사: `tests/deep_review/test_prespec_v4_postgres.py`, `test_page_overview_postgres.py`, `tests/app/test_runtime_database_privileges.py`와 새 schema/ledger 검사. 임시 PostgreSQL 17에서 빈 DB 전체 migration, 이전 head에서 upgrade, 역할별 실제 권한, 원본/terminal 변경 거부·재적재 멱등성을 확인한다.

완료 조건: 새 상태와 기록이 운영 DB 계약으로 표현되고 과거 행을 새 검증 결과로 바꾸지 않는다.

DB 검증(2026-09-10): `0025_overview_claim_ledger`를 추가했다. 폐기용 PostgreSQL 17.11과 `BIDOPS_TEST_POSTGRES_URL`로 새 `test_overview_claim_ledger_postgres.py`, 기존 `test_prespec_v4_postgres.py`, `test_page_overview_postgres.py`, runtime 권한 중 claim ledger/v4 항목을 선택 실행했다. 빈 전체 migration, 0024의 완료·실패·대기·v3·단일 응답 hash 보존, FK/hash 거부, 두 세션 response/error 경쟁, app 취소/worker 기록, 검증·result·attempt·job 원자적 종료가 통과했다. 초기 SQL CASE 식·schema fixture 누락을 수정하고 해당 검사만 재실행했다(4건·5건 통과). SQLite 신규 job·이전 행·모듈 경계 묶음은 36건 통과/소유 표 누락 1건 실패였으며 두 테이블 등록 후 해당 검사 1건 통과. 마지막 draft/semantic 원응답 둘 모두 요구하는 제약 보강 뒤 completed 검사 1건만 통과 확인했다. skip·미해결 실패 없음. 운영 migration은 미실행이다.

추가 용량 계약 검증: core의 단일 요청 조립기를 실제 전송과 사전 검사에 함께 사용한다. canonical SDK 인자의 UTF-8 byte 상계 + template 예약 1,024 + 출력 예약 16,384를 확인된 context와 정책 ceiling 262,144 중 작은 값에 대조한다. stage별 user prompt 24,000자 등 기존 payload·호출 상한은 유지한다. `test_model_client.py`의 요청/identity 선택 5건, `test_prespec_overview_claim_validation.py`의 정책·5,000자 초과 전체 원문 두 단계 선택 2건이 통과했다. 최종 리뷰에서 context metadata의 누락·잘못된 타입·중복 served ID의 불일치를 다른 용도의 identity 실패로 만들지 않도록 경계를 보완한 신규 parameter 5건과 초안/의미 각각 정확히 24,000자 허용·24,001자 거부 신규 parameter 2건도 통과했다. 실제 tokenizer 측정이나 모델 품질 검증은 아니다.

## 주장 검증과 최종 구성

- [x] page/quote를 고정 텍스트의 offset/hash로 변환하는 서버 검증기를 구현한다. 중복 구절·범위 밖·다른 문서·공백 처리의 원문 대응을 검사한다.
- [x] 수치·단위·사업 주체·역할·VAT·기간 기산점·날짜·요구사항 ID를 주장과 원문에서 독립 추출해 대조한다. 확정 불가능한 관계는 실패/사람 확인 사유로 보존한다.
- [x] 분석 문장의 사실 전제와 unknown/input limitation 경계를 강제한다. 검증 밖 자유 문장으로 사실이 새어 나가지 않게 한다.
- [x] 별도 의미 검토의 전체 ID 대응·부정·조건·역할·사업 성격을 검사하고 불확실 판정을 보존한다. 원문에 삽입된 지시를 데이터로 처리한다.
- [x] 검증된 text만 최종 v4로 배치하고 검증 hash와 완전한 claim 대응을 확인한다. 형식 재생성 1회·사실 실패 즉시 종료를 구분한다.

관련 검사: 새 claim/evidence 검증 단위 검사, `tests/deep_review/test_page_overview.py`, `test_prespec_v4_runner.py`, `tests/core/test_model_client.py`. Requirements의 수치·의미·인용 사례를 fake 모델로 검사하며 실모델 품질 통과로 기록하지 않는다.

완료 조건: `6개월` 근거의 `6억원` 주장 등 고정 반례가 모두 차단되고, 의미 검토의 긍정 판정이 결정적 실패를 뒤집지 못한다. 검증 후 추가 사실 생성이 없다.

순수 검증기 검증(2026-09-10, 용량 추가 요구 전): backend `.venv/bin/pytest tests/deep_review/test_prespec_overview_claim_validation.py -q`의 최초 88건 중 87건 통과/중복 ID 오류코드 우선순위 1건 실패를 수정했다. 이후 수정 경계만 `-k`로 선택 실행: completeness/별도 semantic/상한 18건, date/analysis/semantic_preflight 23건, numeric/quantities/metadata/analysis 42건, policy/semantic/analysis 36건, parser/missing_evidence/unparseable 9건 통과. 고유 신규 사례는 95개이며 중복 실행 수를 합산하지 않는다. v3 citation/inline/schema 3건과 schema 모듈 경계 2건도 통과했다. 당시 추가/수정 경계의 실패·skip 0. 의미 판정은 fake 응답이며 Qwen 품질 증거가 아니다. 당시 5,000자·24페이지·8주장/인용 fixture에서 양쪽 prompt 24,000자 이내·무절단을 확인했다. 이후 사용자 추가 요구로 5,000자 일괄 제한은 폐기하며 새 실제 요청 예산 검증으로 대체한다. runner 호출 수·lease 결과는 아래 worker 절에 기록한다.

activation 검증: `test_prespec_v4_ops.py::test_v5_execution_requires_new_approval_and_exact_target` 1건 통과. v1 승인 재사용·호출 4회 승인·source만 있는 실행 입력을 거부하고, v2 정확한 target/input 승인과 읽기 전용 두 stage 미리보기를 확인했다. 최초 테스트의 예상 예외 종류/코드 오기를 실제 안전 계약으로 맞췄으며 제품 코드를 통과 목적으로 바꾸지 않았다.

## worker 복구·중지·배정

- [x] 두 개요 runner의 성공 binding과 일시 실패를 분리하고 clock 기반 backoff를 구현한다. 설정 불일치·일시 장애·실행 중 실패의 캐시 무효화를 구분한다.
- [x] 개요 slot 진입 시 activation과 무관하게 lease를 정리한다. 처리할 수 있는 v4가 없으면 예약 문서를 제외한 legacy를 실행하고 DB 오류는 fail closed한다.
- [x] enqueue/activation/claim/dispatch/종료에서 동일 gate 잠금·activation ID·현재성·lease 검사를 사용한다. HTTP 중에는 DB 잠금을 유지하지 않는다.
- [x] deactivation이 OFF와 미종료 attempt/job 취소를 한 번에 확정하게 한다. 취소 집계와 안전한 사유를 남기고 기존 완료를 보존한다.
- [x] 늦은 응답은 call 이력에만 기록한다. OFF→ON, 중지 직후 다음 stage, lease 만료, 다른 worker 소유 상태에서 결과 삽입과 terminal 덮어쓰기를 차단한다.
- [x] `needs_human_review`와 취소 후의 명시적 재실행은 새 attempt로 만든다. 승인 범위·policy·target을 재확인하고 자동 resume는 하지 않는다.

관련 검사: `tests/deep_review/test_prespec_overview_runner.py`, `test_prespec_v4_runner.py`, `test_prespec_v4_ops.py`, `test_prespec_v4_postgres.py`, `tests/app/test_analysis_worker_slots.py`. clock과 latch/barrier를 사용해 장애 복구·중지/게시 순서를 제어한다. PostgreSQL 두 session 이상으로 실제 잠금 경쟁을 확인하며 sleep 반복으로 통과를 기다리지 않는다.

완료 조건: 최초 identity 실패 뒤 승인 binding으로 복구, OFF 상태의 만료 정리·다른 문서 처리, 중지 확정 후 신규 dispatch 승인/결과 게시 0건, 뒤늦은 응답 provenance 보존.

운영 명령 격리 검증: v5 기본 정책 전환 뒤 `test_prespec_v4_ops.py -k 'defaults_off or activation_duplicate or frozen_target_cli or deactivation_cancels'` 5건 통과. 실제 CLI의 동결 target enqueue가 변환을 부르지 않고, 취소 뒤 새 attempt/job으로 명시적 재실행하는 것을 확인했다. exact snapshot을 재사용하는 prepare→enqueue 경계 1건도 통과했다. 같은 시각/되돌아간 clock의 OFF→ON 감사 순서 1건 통과 기록을 포함하며 운영 활성화는 하지 않았다.

worker 검증(2026-09-10, 용량 추가 요구 전): 담당 worker의 관련 core model 57건, v4 runner 27건, 기존 개요/Luna/analysis 경계 69건, ops 16건 통과. 이는 범위별 결과이며 중복 실행을 합산하지 않는다. clock backoff·설정 변경·identity 불일치, OFF lease 정리와 다른 문서 배정, 두 stage ledger·사실 실패·형식 재생성 3회·원응답 보존, lease 부족/만료·다른 소유자·취소 후 늦은 응답을 확인했다. v5에 과거 Luna binding이 승인되지 않도록 ops를 보강한 뒤 해당 기존 승인 검사 1건만 통과 확인했다.

PostgreSQL 연결 검증: 임시 PostgreSQL 17.11 harness에서 `test_prespec_v4_gate_postgres.py`의 실제 두 세션 gate 경쟁 4건을 확인했다. 최초 중지→claim 1건 통과/3건 실패에서 stage 입력 hash를 attempt 동결 hash와 혼동한 dispatch 제약 위반을 찾아 수정했다. 실패했던 `-k 'not stop_commit_before_claim'` 3건만 재실행해 통과했다. 초안/의미 HTTP 동안 트랜잭션 없음, OFF→ON 뒤 call 이력만 보존, 게시 commit이 먼저면 완료 보존·OFF 집계 0, 완료 v2 조회를 확인했다. 운영 DB는 변경하지 않았다.

추가 안전 경계: malformed 응답의 원문 저장 실패/미수신에도 형식 재생성을 진행하는 문제와 일반 예외 문구가 실패 사유로 노출되는 문제를 합성 3건으로 재현했다(실제 회사자료/비밀 노출 아님). 원문 보존 성공 시에만 형식 재생성을 허용하고 실패 코드는 고정 형식으로 제한했다. 해당 수정의 결과 증거는 용량 추가 요구의 직접 runner 검사와 함께 기록한다. 최종 구성의 PDF 텍스트/표 배치 추정 금지 제한사항 보존 검사 1건도 통과했다.

추가 runner 검증: `test_prespec_v4_runner.py -k 'capacity_failure or semantic_capacity or legacy_input_limits_use_capacity'` 6건, 위 원응답 저장/형식 재생성/안전 오류/호출 3회 경계 선택 11건, 정상 v5·identity 복구 선택 2건이 통과했다. 초안 또는 실제 의미 요청이 예산을 넘으면 해당 단계 dispatch/HTTP 전에 `failed/input_capacity_exceeded`로 닫고 앞선 응답 이력은 보존한다. `test_prespec_v4_gate_postgres.py`에 추가한 용량 초과 1건도 임시 PostgreSQL에서 통과했다(기존 gate 경쟁 4건은 재실행하지 않음). attempt/job 원자적 failed, call/verification/result 0건을 확인했다. py_compile·정책 JSON 파싱도 통과했다.

## API·웹·후속 소비자 연결

- [x] v2 조회와 attempt 기준 PDF 경로를 추가하고 notice/document/attempt 범위, clean/version/hash, 안전한 오류 응답을 검사한다. v1의 업그레이드 필요 응답을 구현한다.
- [x] 웹 타입과 호출부를 v2로 옮긴다. 현재 완료·검증 실패 진단·이력의 렌더링을 구분하고 정확한 PDF 페이지 링크를 연결한다.
- [x] 입력 범위 확인 대기와 주장 검증 대기를 구분한다. 현재 취소·실패·stale이면 과거 성공으로 대체하지 않는다. v3·Luna 결과에 과거 기준·미측정 표식을 유지한다.
- [x] 추가 요구: 용량 초과 미실행을 내용 검증 실패와 구분해 사유·후속 조치를 표시하고 API/화면의 해당 경계만 검증한다.
- [x] 회사 핏 입력 추출 등 소비자를 버전별 parser로 바꾸고 새 결과의 검증/hash를 대조한다. 회사 핏·심층 자동 시작을 새로 활성화하지 않는다.

관련 검사: `tests/deep_review/test_page_overview.py`, `test_page_overview_postgres.py`, `test_company_fit.py`, `test_auto_preparation.py`의 영향 경로, frontend production build와 `web/frontend/tests/page-overview.spec.ts`의 의미/구조 검사. 변경한 개요 화면은 1280×800·1440×900에서 확인한다. 발주계획 화면은 공유 UI/API 영향이 확인된 경우에만 추가한다.

완료 조건: 원응답·경로·비밀 노출 없이 실패 주장과 근거를 확인할 수 있고, 후속 분석이 실패한 최신 개요를 과거 성공으로 대체하지 않는다.

검증(2026-09-10): backend `test_page_overview_claims.py`의 안전한 실패 진단/업그레이드 차단/PDF 소속·비밀 오류, 최신 악성 scan 거부, 완료 v4 reader·회사 핏·검증과 다른 본문 거부 3건을 수정 경계별로 실행해 통과했다. 기존 page overview와 회사 핏 현재 상태 선택 묶음 21건, 추가 cancelled/needs_human_review 소비 차단 2건도 통과했다. 초반 fixture의 policy 속성 참조 오류는 `.document` 계약으로 수정했다. frontend `npm run build` 및 `npx playwright test --project=app tests/page-overview.spec.ts` 12건 통과(1280×800·1440×900 포함). 이후 필수 current 누락 차단·target-only 입력 범위 대기 문구·근거 링크 문구를 보강하고 build 및 `-g 'v2 missing current|current claim verification'` 2건만 통과 확인했다. 최종 화면 고유 사례 13개이며 기존 chunk 크기/NO_COLOR warning 외 실패·skip 없음. 운영 웹 배포/실모델 결과 확인은 미실행이다.

추가 소비 경계: 기존 `test_api_pre_specs_projection.py`와 `test_company_fit.py`의 목록 집계·자동 준비 상태 사례에 cancelled/needs_human_review를 넣고 해당 새 parameter 4건만 실행해 통과했다. 목록 집계·상세 자동 준비가 과거 completed로 표시하지 않으며 새 정책/자동 시작을 활성화하지 않는다.

용량 표시 검증: 기존 failed/reason_code를 그대로 활용한 API 신규 1건과 용량 미실행 화면 2건(1280×800·1440×900)이 통과했다. context 확인 불가도 설명하고 해당 요청만 미실행임을 명확히 하는 최종 문구 보강 후 production build 및 `PW_PORT=4289 npx playwright test --project=app tests/page-overview.spec.ts -g 'input capacity failure explains'` 2건만 재확인했다. 개요 화면 고유 사례는 15개다. 최초 기본 포트의 화면 검사 준비가 대기해 해당 프로세스만 중단하고 격리 preview 포트를 사용했다. 제품 검사 실패는 없었으며 기존 chunk 크기/NO_COLOR warning은 남는다.

최종 리뷰의 직접 소비자 수정: 범위 확인 조회의 `object_store(namespaces=(), read_namespaces=("structure",))`는 실제 구조 저장소 client를 만들지 못했다. v1/v2의 pending→사람 확인→confirmed 경계를 기존 fixture의 역할 인자 검사로 보강해 2건 실패를 재현하고, 구조 읽기 namespace만 명시했다. 같은 선택 검사 2건 통과(11건 deselected). source 권한·사람 확인의 실행 금지 계약은 바꾸지 않았다.

## 변경 경계 연결 확인·문서 동기화

- [x] 앞선 검사에서 아직 확인하지 못한 변경 경계가 있는지 확인한다. 누락된 경우에만 수집기↔호출부, 새 개요 실행↔DB↔API/웹 등 해당 연결을 최소 표본으로 검사한다. 변경하지 않은 판정·문서 준비는 기존 fixture나 동결 산출물을 재사용하며 전체 파이프라인을 새로 실행하지 않는다.
- [x] 각 작업에서 확보한 통과 범위·실패·skip을 모아 기록한다. 이미 확인한 연결과 통과한 검사를 반복하지 않는다. 새로운 회귀가 발견되면 변경과의 관련성을 확인한 뒤 필요한 경로만 추가 검사한다.
- [x] `docs/contracts.md`, `business-rules.md`, `security.md`, `operations.md`, `prespec-reference-run-guide.md`, `tracking/status.md`를 구현과 함께 갱신한다. schema·재시도·중지·새 회차 명령의 설명이 서로 일치해야 한다.
- [x] 네 findings는 재현 회귀와 수정 검증을 연결한 뒤 해결 상태를 기록한다. 코드 작성만으로 해결 처리하지 않는다.

전체 앱 재빌드·전체 스위트·실모델 재호출을 최종 확인의 기본 절차로 두지 않는다. 배포 이미지 확인이 필요하면 기존 검사로 확인하지 못한 환경 차이와 수정 경로만 확인한다.

## 사설 Qwen 실사용 참조 검증

다음은 구현 이후의 실행 절차다. 이 계획 채택은 특정 payload 전송·운영 migration·정책 활성화를 대신하지 않는다. 필요한 승인 정보는 아래 준비물을 완성한 뒤 실행 직전에 확인한다.

- [x] 실행 날짜·새 회차 경로·대상 notice/document/target ID·페이지 범위·원본 hash를 고정한 소규모 sample manifest를 준비한다. 정상·예산/기간 혼동 가능·조건/부정·근거 부족 사례를 포함하고 이미 있는 이력을 덮지 않는다.
  - [x] 추가 요구: 길이 때문에 제외했던 35·142번의 고정 원문 전체를 두 단계 요청 예산으로 재평가한다. 실제 의미 payload는 초안 이후 확정되므로 사전 예산과 실제 요청 직전 검사를 구분한다.
- [x] 실사용 검증도 변경한 수집·개요 구간과 직접 영향받는 웹 조회로 한정한다. 변경하지 않은 C-2·C-1·변환 경로는 기존 동결 입력·결과를 활용하며 검증을 위해 재실행하지 않는다. 기존 결과를 재사용한 구간과 이번에 실행한 구간을 구분해 기록한다.
- [x] 승인 endpoint의 served ID `qwen3.8-27B`, 목적별 allowlist, 선언 revision 64자 hex, 새 정책/activation digest, 초안·의미 양쪽 payload 미리보기와 호출 상한을 준비한다. 값은 운영 환경에서 확인하고 문서에 실제 비밀을 적지 않는다.
- [x] 이번 검증 결과는 실제 실행한 수정 구간으로 한정해 보고한다. 추후 C-2를 포함한 전체 흐름 실행을 별도로 요청받으면 선별 품질·실행 승인 게이트를 확인하며, 이번 부분 검증을 그 실행의 성공 근거로 대신하지 않는다.
- [x] 임시 환경 검증 후 운영 변경에 필요한 백업 manifest·migration 절차·이미지/worker 역할과 egress overlay를 준비했다. startup 자동 migration·scheduler 활성화는 추가하지 않았으며 이번 host 조회 생략 예외는 아래에 별도 기록한다.
  - [x] 기존 백업 dump hash와 현재 배포/역할/egress를 읽기 전용 확인하고 승인 후 절차를 고정한다.
  - [x] 후속 요청의 호출 전 준비: 새 versioned 객체 백업·manifest와 검증 코드 이미지/모델 연결 없는 읽기 전용 one-shot 점검 구성을 만든다.
  - [x] 사용자 승인 뒤 ro_backup의 sequence SELECT만 복구하고 새 0024 DB 백업을 완료한다. 이전 0023 백업·0 B 실패 파일은 보존하고 대체 사용하지 않는다.
  - [x] 서비스 중지 후 0025/runtime 권한과 호환 web 이미지를 적용하고 DB·API·기존 데이터 보존을 확인한다. 문서 worker는 기존 이미지·컨테이너·설정을 유지한다.
  - [x] 승인된0910 표본4건의 실제 생성용 one-shot worker를 기존 이미지·최소 역할과 고정 model egress IP로 기동한다. 추가 host 체인 조회는 사용자의 명시적 이번 실행 예외로 생략했으며 방화벽 전체 검증 통과로 표시하지 않는다.
- [x] 선택한 수정 구간에 필요한 worker의 실제 기동·설정·Qwen identity를 확인한다. C-1·문서 준비는 동결 결과를 재사용하고 회사 핏·심층 자동 실행은 열지 않았다.
- [x] 승인된0910 표본4건만 새 attempt로 실행해 호출별 binding/hash/token/latency·암호화 응답·검증/종료 상태를 보존한다. 건별 초안1회, 총4회이고 형식 재생성·semantic은0이었다. 이전35·59·142의 새 v5 실행을 했다는 뜻은 아니다.
- [ ] 사람이 모든 표본의 주장과 PDF를 대조한다. 잘못 통과한 주장, 불필요한 사람 검토, 누락, 읽기 쉬움과 실행 시간을 기록한다. 참조 결과에 `unmeasured_reference`를 유지하고 사람 판정은 별도로 저장한다.
- [ ] 동일 결과를 웹에서 두 지원 폭으로 확인한다. 완료·검증 대기·취소/실패·과거 이력·근거 페이지가 DB 상태와 맞는지 확인한다. 운영 네트워크 장애 유발 대신 격리된 fake에서 중지·복구 경쟁을 검증한 기록을 사용한다.

완료 조건: 지정 표본의 입력부터 웹 근거 확인까지 추적 가능하고 실제 호출·사람 대조 결과가 남는다. 허위 근거가 검증을 통과하면 관련 실행을 중지하고 [문제 보고 규칙](../../AGENTS.md)에 따라 보고한다. 실사용 표본 통과를 곧바로 운영 품질 승인으로 쓰지 않는다.

준비 결과(2026-09-10): [승인 대기 실행 준비물](../../.dryforge/prespec-claims-preflight-20260910-xzudaA/README.md)에 sample manifest, 세 동결 입력·두 단계/형식 보정 payload 미리보기, model binding, activation v2와 읽기 전용 preview를 보존했다. 새 정책 digest는 `0023c9af1bcdb6e14c3d7464365b70f6b7be534cb79b91e9b43269ce760d4725`다. preview의 `execution_approval_matches=true`는 artifact의 코드 일치 검사이지 사람 승인이 아니다. 문서를 보내지 않는 `/models` 조회로 served ID/revision 일치와 context 262,144를 확인했다.

| notice | 고정 PDF 쪽 | 선택 원문 글자수 | 초안 prompt 글자수 | 예시 의미 prompt 글자수 | 초안/예시 의미 총 token 상계 |
|---|---|---:|---:|---:|---:|
| 35 | 4–8 | 5,962 | 7,690 | 8,424 | 36,840 / 37,328 |
| 59 | 3–5 | 1,967 | 3,572 | 4,257 | 28,429 / 28,805 |
| 142 | 4–12 | 6,849 | 9,040 | 9,739 | 40,182 / 40,560 |

세 표본 모두 전체 원문을 포함한 준비 요청이 payload/context 예산 이내다. 의미 미리보기는 서버가 원문에서 고른 두 주장으로 만든 형태 예시이며 Qwen 응답·사람 정답·완료 개요가 아니다. 실제 의미 요청은 실제 초안 이후 다시 검사해야 한다. 35의 예산/VAT/기간·협의 조건, 59의 유지관리/조건, 142의 감리와 대상 개발사업·예산/기간 구분 및 부정/예시 일정을 검토 후보로 확인했으나 품질 통과로 기록하지 않는다. 자동 분할은 필요하지 않았고 도입하지 않았다.

이번 실제 실행은 collector의 기존 raw 재분류뿐이다. 새 회차 `data/runs/prespecs-20260831-20260902-claims-reference-20260910-xzudaa`에 673건(candidate 94/audit 579), `complete=true`, 경고 0, exit 0을 얻었다. 원본 raw 두 개의 실행 전후·복사본 SHA가 모두 일치했다. HTTP·운영 적재는 0회다. C-1과 기존 target/snapshot/PDF/page text는 재사용했고 C-2·변환·회사 핏·심층 검토는 실행하지 않았다.

운영 읽기 전용 확인: DB는 `0024_section_candidates`, web/document-worker는 `bidops-rdp-r7:20260910`, 최신 activation은 OFF(`5016643f-17fb-4c14-a5cf-3c1ded1f5e19`)다. 운영 analysis-worker는 없고 기존 web의 회사 핏 true 설정은 변경하지 않았다. 기존 백업 dump hash는 manifest와 일치하지만 revision 0023이므로 새 백업은 미완료다. 신규 배포에서는 기존 `PrespecV4OverviewRunner(legacy_runner=None)`만 쓰는 전용 one-shot을 준비하며 다른 큐를 처리할 수 있는 합성 analysis worker는 이 부분 실행에 사용하지 않는다.

남은 승인: 세 표본의 승인 원문/동적 초안·검증 인용 전송(표본당 최대 3회, 전체 최대 9회; 의미 최대 1회/표본), 새 백업 후 0025·runtime 권한 적용 및 호환 web/전용 one-shot 배포, activation v2 활성화와 실행 후 OFF. 승인자 감사표식과 서비스 중지·재개 시간이 필요하다. 실제 Qwen 생성·운영 변경·사람 PDF 대조·실결과 화면 인수는 모두 미실행이며 `unmeasured_reference`를 운영 품질 승인으로 취급하지 않는다.

후속 요청 “개요검토를 위한 qwen호출 전까지만”(2026-09-10): 모델 HTTP·activation·enqueue·모델 worker를 실행하지 않고 호출 전 준비만 진행했다. `bidops-overview-claims:20260910-precall-xzudaa` 이미지 build 성공(digest `8f383c282a4563a5307ce8a0e97825756eb151af971a7038ee008c41f2305ffc`), 이미지 내부 head 0025/UID 1000/frontend 존재·비밀/회사 baseline/준비물 미포함 확인, 최소 역할 Compose와 web image 교체 overlay 검증 완료. 새 이미지 점검은 host 검사 반복이 아니라 실제 배포 산출물 확인이었다. production build의 기존 chunk 경고 외 실패는 없다. 처음 이미지 메타 확인의 종료 출력이 회수되지 않아 해당 비네트워크 조회만 다시 확보했고 앱 검사는 재실행하지 않았다.

새 이미지의 읽기 전용 one-shot에서 실제 worker DB/structure-read 역할로 35·59·142 target/input/고정 manifest version/hash 확인이 통과했다. 이 점검은 `PGOPTIONS`와 transaction read-only, internal database/storage만, 모델 allowlist/revision 공백으로 전송을 차단하며 model runner를 시작하지 않는다. 임시 점검 스크립트의 import 경로와 PostgreSQL 권한 함수 평가 순서 오류를 수정한 뒤 해당 점검만 통과했다. 실제 모델/DB 쓰기 0, 기존 OFF 감사 ID 유지, active v4 attempt 0, 운영 DB 0024다.

새 백업 `backups/prespec-precall-20260910-HGYzGB`의 객체 복사는 966 version(source 304/structure 294/quarantine 291/model-response 77), stored-byte hash 전건 일치, manifest SHA `a9963581aa8694b5c6b1112e1979b636676c97e252e80daf9420e1acc2bcb50c`로 완료했다. DB는 기존 ro_backup 계정의 `agency_portal_id_seq` SELECT 거부로 실패(exit 1, dump 0 B)했다. 조회 결과 현재 sequence 22개 모두 SELECT가 없고 runtime 권한 정책도 table SELECT만 재부여한다. 실패 파일·기존 백업을 보존했으며 owner 우회/운영 grant/migration/웹 교체는 하지 않았다. 객체 백업만으로 완전한 복구 지점을 주장하지 않는다. 권장안은 ro_backup의 현재/향후 sequence SELECT만 복구(USAGE/UPDATE 없음)한 뒤 새 DB 백업과 명시적 서비스 중지/배포다. 운영 승인이 필요하며 [findings](../tracking/findings.md)에 기록했다. 이 결과는 준비서의 `precall-readiness.json`/`precall-check-result.json`과 백업 `manifest.json`에 남겼다.

Orca 독립 준비물 점검 callback에서 세 입력·stage payload·용량의 결속은 일치했지만 최초 준비 binding의 provider `vllm`이 표준 runner의 `openai-compatible`과 달라 호출 전에 `activation_binding_mismatch`가 나는 것을 확인했다. 제품 코드나 승인 모델은 바꾸지 않고 이전 준비본을 보존한 채 `model-binding.runtime.json`, `sample-manifest.runtime.json`, 세 `payload-preview-*.runtime.json`을 새로 만들었다. 새 binding digest `bce7895a4915c6f3d637b036326774d33abd3aa5644633ad117c35197c2e1b8f`가 표준 `approved_v4_binding`과 정확히 일치하고 실제 요청 bytes·activation artifact는 그대로임을 로컬 선택 검사 1회로 확인했다(`binding-check-result.json`). 현재 승인 대상으로는 이 runtime 준비본을 사용하며 최초 binding은 사용하지 않는다. worker 완료를 수신·해제했고 별도 전체 리뷰/앱 검사·모델 호출은 하지 않았다.

## 전환과 복구

2026-09-10 운영 승인 후 실제 적용: `runtime-privileges.sql`의 현재/미래 sequence SELECT만
ro_backup에 보완했다. 임시 PostgreSQL에서 `test_runtime_database_privileges.py` 중 정적
fail-closed 정책과 신규 backup sequence 읽기/nextval·setval 거부 선택 2건 통과. 운영에서는
migrate가 소유한 sequence 22개의 SELECT만 먼저 복구했고 새 ro_backup dump가 성공했다.
`backups/prespec-deploy-20260910-cqJZ3W/manifest.json`: 22,530,409 B, SHA
`f04fb97c528312bfe32df64b9273b17901d3793d4af597f9088e5596ff0a67d1`, custom TOC 1,073개.
기존 객체 백업 966 version에 active DB 참조 596개가 모두 있고 일반 객체 hash도 일치한다.
모델응답은 암호화 저장/평문 hash 의미가 달라 version 존재를 대조했다. 최초 로컬 비교의
namespace 중복 접두사 오류만 바로잡았으며 원본/백업을 수정하지 않았다. restore·WAL·외부
복사 검증은 미실행이다.

21:36:06 KST에 web/문서 worker 2개를 중지하고 0025·runtime 권한을 migrate 역할로 적용했다.
초기 웹 기동에서 `app/core/db.py`의 기대 head가 0024로 남은 누락을 발견했다. 0025로
동기화하고 기존 `test_integration_t14.py::test_migrated_database_is_at_head_before_lifespan`
및 `test_db_migrations.py::test_alembic_reports_exactly_one_head` 2건을 임시 PostgreSQL로
통과 확인했다. 앞서 harness 없이 선택한 2건은 skip이므로 통과 근거에서 제외한다.
수정된 backend 이미지만 다시 만들었고 frontend build/dependency 단계는 cache 재사용했다.
migration 재실행·downgrade·게이트 완화는 하지 않았다.

최종 web 이미지 `bidops-overview-claims:20260910-runtime-head`의 digest는
`7d2ff95f04152520d81bba6c229251e2898ee8b05d7937da30b8d00da33723ca`이며 21:38:43 KST에
기동, healthy와 health/SPA/35·59·142 개요 v2 API 모두 200을 확인했다. 이전 배포 Compose는
읽기만 하고 image-only overlay를 사용했다. 문서 worker는 21:36:37에 동일 컨테이너·이미지·
설정·mount로 재개했다. 다른 서비스/volume은 변경하지 않았다. 백업 전→중지 시 기존 82개
table 지문이 동일하며, migration 후에도 새 nullable 열과 명시적 migration 감사 1건을
제외한 기존 행 값·리뷰·결과·품질 표식은 모두 동일하다. 새 call/verification 0건, v4 active
attempt 0건, 기존 OFF 감사 ID 유지, Qwen HTTP 0회다. 35/59의 API completed는 기존 v3
이력이며 새 주장 검증 성공이 아니다. [배포 증거](../../.dryforge/prespec-deploy-20260910-SBh1rl/deployment-result.json)에
범위와 지문을 보존했다. 이전 단락들의 0024/승인 대기는 당시 기록이며 이 후속 결과가 현재다.

추가 요청의 0910 신규 회차:

- [x] 2026-09-10 하루(양 끝 포함, Asia/Seoul)를 새 경로로 실제 수집한다.
- [x] 개요 대상 cohort 19건을 확정하고 메타데이터를 적재한다. 기존 등급·리뷰와 전체 수집 원문을 보존한다.
- [x] 승인된 19건의 첨부27개를 제한된 worker에서 취득·검사한다. 완료23/차단4를 그대로 보존했다.
- [x] 안전한 RFP15개의 PDF/target 준비를 각1회 수행하고 결과를 구분한다. snapshot9개·range ready5/사람 확인4·변환 실패6이다.
- [x] ready5개를 호출 전 검사한다. 749·761만 양쪽 payload 준비 완료, 753 용량 초과, 744·759 manifest 계약 오류이며 새 준비 실패3건을 DB/API에도 기록했다.
- [ ] 최초 제외4건·범위 확인4건·변환 실패6건·manifest 오류2건·용량 초과1건의 후속 조치를 완료한다. MVP 배포·실패6건 core 재준비는 완료했으며 최신 수동 범위11건·문서/안전4건과 모델 검토는 남아 있다.
  - [x] MVP 보완: rhwp `outline`·전체/반환 후보 개수 계약을 수용하고 보조 후보 문제와 필수 PDF·페이지 텍스트 무결성 실패를 분리한다. 관련 producer/consumer만 검증한다.
  - [x] MVP 보완: 일부 공백 페이지는 번호·원문·해시 그대로 허용하되 근거로 인정하지 않고, 전체 공백 입력은 차단한다. runner/주장 검사 직접 경계를 검증한다.
  - [x] 위 차단 원인 수정 후 후보 존재 여부와 무관한 수동 쪽 범위 선택·안전한 준비 PDF 열람을 연결한다. 범위 확정은 새 target/감사만 만들고 실행·내용 검증과 분리한다.
  - [x] 753의 같은 줄 복수 장 제목은 모호함으로 보내고 정당한 범위를 사람이 확인하게 한다. 기존 고정 입력을 재평가하되 24,000자 정책 상한·모델 context를 구분하고 절단·요약·분할하지 않는다.
    - [ ] 751·753·756·758·760의 정당한 시작/끝 쪽을 사람이 확인하여 새 target을 만들고 그 입력의 두 단계 용량을 평가한다. 현재 원문을 짧게 잘라 통과시키지 않는다.
  - [x] 752의 안전한 대체 문서 명시 선택 계약과 750·757의 안전한 오류 분류를 확인한다. 자동 선택 확대·안전 검사 우회는 하지 않는다.
    - [ ] 752의 source/document ID 고정 명시 선택 계약·담당자 선택을 승인받는다. 750·757은 상세 안전 원인이 불명확한 차단을 유지한다.
  - [x] 수정 web/document-worker 배포와 변환 실패6건(743·745·746·747·754·755)만 기존 source로 재준비하는 운영 범위를 승인받아 실행한다. 새 수집·정상9건 재변환은 하지 않는다.
    - [x] 실제 재준비에서 754·755의 `제안개요` 작성 양식 오선택을 확인해 기존 모호성 경고/수동 확인으로 보완한다. 기존 target을 보존하고 변경한 selector·조회 경계만 검증·배포한다.
    - [x] 문서 교차검토에서 발견한 후보 없는 정상 core의 scratch 전달 누락을 생산자·소비자·기존 nullable snapshot/cache까지 연결한다. 경고 없는 누락·핵심 hash 훼손·JSON null 후보를 거부하는 직접 경계만 검증하고 배포한다.
    - [ ] 추가 수동 대상743·745·746·747·754·755의 정당한 범위를 담당자가 PDF로 확인한다. 후보 일부 반환·양식의 짧은 입력을 검토 준비 완료로 세지 않는다.
  - [x] 0910 고정 입력의 준비 가능 건수·모델 실행 건수·내용 검증 통과 건수를 별도로 기록하고 문서 동기화 후 이번 diff의 최종 리뷰를 마친다. 추가 운영 실행은 기존 승인 범위를 넘어 수행하지 않는다.
- [x] 고정한 신규 대상4건의 양쪽 payload·binding·activation 승인 후 Qwen 실행과 결과 확인을 수행한다. 네 건 모두 결정적 검사에서 사람 검토로 종료했으며 의미 검토·최종 게시 성공은 미확인이다.
  - [x] 후속 사용자 요청 “검증된 문서로 Qwen 실행 돌려봐”를 준비4건(744·749·759·761)의 고정 입력·v5 binding·최대12회 참조 실행 승인으로 기록한다. 현재 네 target의 안전한 원문/PDF/manifest·선택 페이지 무결성과 current/ready를 읽기 전용 재확인한다.
  - [x] 사용자가 추가 관리자 체인 조회를 이번 기능 실행에서 생략하도록 명시한 뒤 실제 identity/context 검사 → 네 target 순차 실행 → OFF 복귀 → 호출·검증·API/실패 PDF 확인을 수행한다. 기존 방화벽을 변경하지 않았으며 host 정책 전체는 미확인으로 남긴다.

2026-09-11 실제 Qwen 결과: 사용자의 추가 조회 생략 지시를 이번4건 참조 실행의 예외로
기록하고09:08:31–09:13:04 KST에 기존 v5 runner를 최소 worker 역할로 실행했다.
served 모델명·선언 revision binding 검사와 context262,144 확인, **입력 준비4·실제 모델 실행4·내용 검증 통과0**다.
초안4회 모두 응답했고 결정적 검사에서 전부 needs_human_review여서 semantic0·형식
재생성0·최종 결과0이다. 정책·원문·호출 상한은 바꾸지 않았다.

| 대상 | 결정적 주장 통과/실패 | 주요 진단 |
|---|---|---|
| 744 | 4/4 | main_tasks 섹션 누락, 수치 metadata·단위·관계 |
| 749 | 4/4 | main_tasks 누락, 수치 및 미확인 사유/회사 대조 범위 |
| 759 | 5/3 | 수치·단위, 미검증 분석 전제, 미확인 사유/회사 대조 범위 |
| 761 | 2/6 | main_tasks 누락, 수치·관계·날짜 |

이는 검증기의 진단이며 실제 사실 오류와 과탐을 사람 대조로 분리한 결과는 아니다.
원문 입력→Qwen 초안→검증 실패 저장/조회까지 작동했지만 **검증된 최종 개요까지의
실사용 완주에는 성공하지 못했다.** 사람 대조·의미/성공 게시 실사용은 미완료로 남긴다.
다음 판단 대상은 초안의 section/quantity/unknown 계약과 결정적 규칙의 실제 원문 적합성이다.
사실 자동 수정·검사 우회·추가 모델 호출로 통과시키지 않았다.

ON11ada018-0546-4ab1-aece-15678343f6d0 → OFFa6e96d1b-9c8a-40b6-87f7-d1e177c21222,
active0·취소0이다. 생성4(승인 최대12), identity5, tokenize0이며 prompt/output token은
9,324/8,482다. 네 v2 API/current·검증 진단200, 실패 attempt PDF4개200·승인 SHA 일치·
private,no-store를 확인했다. 기존10테이블 기존 행 지문이 동일하고 신규 attempt/job/
verification/암호화 응답각4·call 이벤트8만 추가했다. 개요8·사람 리뷰140·원본188은 보존했다.
새 migration/build/배포/재수집/재변환/C-1/C-2/회사 핏/심층 실행은 없었다. 기존 화면·중지
경쟁 검사는 재사용했고 실제 브라우저 두 폭 검사는 반복하지 않았다. 지문 helper의 최초
created_at 없는 테이블 조회 오류만 수정해 해당 read-only 점검을 완료했으며 제품 코드
수정은 없었다. 상세 호출·DB·API 증거는 [이번 실행 기록](../../.dryforge/prespec-qwen-0911-mHF0bO/README.md)에 있다.

실행 결과 최종 리뷰: Sol medium의 rhwp 다섯 문서 완료 이벤트를 받아 최신4건 실행/0건
통과와 과거0건 이력을 대조했다. 메인은 DB/ledger/API의 상태·최종 결과 부재·참조 표식·
원본 불변성과 종료 OFF를 확인했다. 실제 OFF 중간 취소를 재현한 것으로 읽힐 수 있는
문서 표현만 결정적 검사 중단과 구분해 보정했다. 관련 문서 diff/링크만 확인했고 추가
모델·앱 테스트·빌드·화면 실행은 하지 않았다. 제품 코드·정책 수정과 commit/push는 없다.
최종 diff 공백 검사는 통과했다. 관련 문서 상대 링크111개 확인 중 Spec의
`../security.md`1개는 실패했다. 읽었던 `docs/security.md`가 이번 실행 작업 중 별도 삭제
상태로 바뀐 것을 git에서 확인했으며 원인을 추정하거나 사용자 변경을 복원하지 않았다.
이 링크는 미해결로 남기며 모델 실행 실패나 문서 전체 검증 통과로 표현하지 않는다.

아래 사전 점검·관리자 조회 대기·배포 기록은 실제 Qwen 실행 전 시점의 이력이다.

2026-09-11 후속 Qwen 실행 점검: 입력 준비4건은 위 read-only 재확인에서 모두 통과했다.
기존 양쪽 payload preview와 C-1/C-2·변환 결과는 재사용했으며 정책·binding·호출 상한을
바꾸지 않았다. 예정 모델 worker source172.30.0.2에서 Qwen192.168.0.139:58765뿐 아니라
불허 외부1.1.1.1:443도 TCP 연결되어 **모델 호출 전에 중단**했다. 앞선 첨부용 방화벽
규칙(source172.19.0.2)은 이 경로에 적용되지 않는다. 관리자 인증이 없어 우회하지 않고
정확한 모델 worker만 제한하는 스크립트를 준비해 구문/비관리자 거부를 확인했다.
DB 쓰기·activation·enqueue·Qwen HTTP는0, OFF 유지다. 현재 입력 준비 가능4·실제 모델
실행0·내용 검증 통과0이며 실제 의미 payload는 실제 초안 뒤 재검사해야 한다.
[승인·고정 입력·통신 점검·재개 조건](../../.dryforge/prespec-qwen-0911-mHF0bO/README.md).

후속 관리자 실행은 `dedicated_chain_exists_inspect_before_reuse`로 규칙 변경 전에
중단됐다. 동일 source의 TCP 재확인에서는 Qwen 연결 성공·이전 불허 외부 연결 거부로
바뀌었다. 기존 체인을 삭제/수정하지 않았고, sudo 조회 인증이 없어 전용 체인 내용과
DOCKER-USER/INPUT 연결 규칙의 읽기 전용 확인을 요청했다. 모델 HTTP·activation·enqueue0,
실행 항목은 미완료다. TCP 거부만으로 방화벽 정책 전체의 검증 완료를 주장하지 않는다.

2026-09-11 배포 후 실제 결과: 사용자의 후속 “진행해주고” 승인으로 web·document-worker2만
image-only overlay로 교체했다. DB head0025, 환경변수·network·mount·UID·pids128/1GiB는
그대로다. 최초 `bidops-prespec-mvp:20260911`에서 08:04:11–08:06:29 KST에 기존 실패6건을
각1회 처리해 **core6/6 성공**했다. source-only ON `4d2a321d-ff3c-4545-b746-4ea35f8d7f3e`,
종료 OFF `fe91c298-aceb-47b2-95e9-7560edc04be1`이며 모델 실행 activation/enqueue는0이다.
내부 DB/storage/scanning만 연결한 비root/read-only one-shot과 network-none 문서 worker를
썼다. Qwen `/models`·tokenize·생성 HTTP, 새 call/verification/result, active attempt는 모두0이다.

| 대상 | 실제 core/후보 결과 | 현재 입력 준비 판단 |
|---|---|---|
| 743·745 | 각각 PDF24쪽, outline5/5 | `scope_heading_missing`, 수동 범위 |
| 746·747 | PDF67/111쪽, 후보 전체67/111 중 각50개 반환 | `section_candidates_incomplete`, 수동 쪽 범위 |
| 754·755 | PDF72/45쪽, outline28/28·1/1 | 자동 target은 ready였으나 49쪽124자/30쪽145자가 제안 작성 양식이므로 수동 범위 |

754·755는 `Ⅰ. 제안개요` 아래 제안사가 작성할 목적/범위 설명을 선택했다. 해당 명시 장
제목만 `ambiguous_scope_boundary`로 보내는 최소 가드를 추가했다. 기존 두 target과
선택 원문은 보존하며 expanded 조회가 경고·can_confirm=true를 표시한다. 정당한 범위를
사람이 확인하기 전까지 두 건을 입력 준비 완료나 실행 승인 대상으로 넣지 않는다.
selector2 parameter·기존 ready의 경고/불변성1·정상 사업개요 회귀1을 확인했다. 최초 새
fixture3건은 쪽 번호가1부터 연속이어야 하는 계약을 빠뜨려 실패했고 fixture만 수정해
해당3건 통과, 정상 회귀1건은 재실행하지 않았다. 후속 이미지는 backend만 바뀌어 frontend
build/dependency cache를 재사용했고 새 화면 스위트·전체 스위트·정상 문서 재변환은 하지 않았다.

범위 가드 이미지는 `bidops-prespec-mvp:20260911-scope`, digest
`16150cf6300fbaad1ea396653941d5bd51b55c5f478802a64f0afdbd6c92aa6c`이며 08:11 KST에
web·worker2 반영했다. web healthy, 실제 selector SHA==작업 코드 SHA, 754·755 v2
경고/직접 선택 및 target PDF200·exact SHA·private/no-store·nosniff·CSP sandbox를 확인했다.
처음 배포의 health/SPA/753 경고와 743·746 후보 상태 API도200이었다. 추가변환은0이다.

Sol medium 문서 교차검토는 native 내부의 후보 부재 허용이 scratch 생산자·소비자까지
연결되지 않은 누락을 찾았다. `section_candidates_unavailable` 경고와 명시적 null
descriptor를 연결해 기존 nullable snapshot/cache를 활용했다. HWP/HWPX 전달·저장·cache2,
경고 누락/핵심 hash 거부3, 기존 정상 roundtrip2 **7 passed**. 최종 diff 리뷰에서 실제
후보 파일의 JSON `null`이 같은 부재로 처리되는 사례를 재현(1 failed)하고 조건1줄 수정 후
새 거부1+영향 정상 roundtrip2 **3 passed**였다. 고유 scratch 사례는8건이며 중복 합산하지 않는다.
core 검증과 존재하는 후보의 schema/canonical/hash 검사는 유지한다. 이 보완의 최종 이미지는
`bidops-prespec-mvp:20260911-advisory-final`, digest
`223019128c101ea131d855256c950d06f0edda393281556656c1cea1e4c72d9f`, 08:28:50/52 KST에
worker2·web 배포 완료다. 3서비스 모두 기존 대비 image만 다르고 protocol/native/selector
SHA 일치·web healthy·head0025·OFF·call/verification/active attempt0을 확인했다.
성공6건 재변환과 기존 화면/API/전체 검사 반복은 하지 않았다. 중간 이미지 이력도 실행 기록에 보존했다.

기존14 snapshot/14 target/16 attempt/8개요/140리뷰/188 document/516 content object/
709 location의 **모든 기존 행 MD5가 동일**하다. 새 snapshot6·target6·object/location각34만
append했다. 원본 bytes/version/hash와 새6건 PDF/page-text 개별 hash·clean 연결을 검증했다.
보존한 기존 실패 attempt는 여전히 개요 상태에 보일 수 있으며, 최신 변환/범위는 별도
`range_review`에서 확인한다. 이를 실패 이력 삭제나 검토 성공 상태로 바꾸지 않았다.

현재19건은 **입력 준비 가능4**(744·749·759·761), **범위 확인11**(743·745·746·747·751·753·
754·755·756·758·760), **문서/안전4**(748·750·752·757)다. 안전한 PDF는 기존9+신규6=15건,
실제 모델 실행0·내용 검증 통과0이다. 이전4건 payload와 C-1/C-2/정상9 변환은 재사용했다.
754의 초안/형식/예시 의미 요청 bytes6622/6961/6987은 예산 안이지만 범위 부적격이다.
755는 초안/형식6663/7002 bytes만 준비됐고 의미 예시는 조건에 맞는 원문 줄이 없어 pending이다.
둘 모두 승인 후보에 추가하지 않았다. 24,000자 정책·과거 확인 context262,144·출력16384/
chat1024 예약·호출 상한은 그대로며 실제 의미 검토 입력은 여전히 실제 초안 이후 검사한다.
실행/고정 입력/불변성/최종 환경 증거는
[이번 배포·재준비 기록](../../.dryforge/prespec-mvp-deploy-20260911-OIBy24/README.md)에 모았다.
이번 승인 범위 최종 리뷰 완료: Sol medium의 rhwp 다섯 문서 완료 callback을 받아 실제
diff·실행 증거와 대조하고 작업트리에 통합했다. core/보조 전달, 상태와 현재성, 불변성,
중지 후 게시 fence와 미검증 주장 게시 금지의 기존 검증을 재사용했다. 리뷰 수정은 앞서
기록한 scratch 경계와 문서의 용량 식·검증 시점·역사 표기에 한정했다. 새 테이블·scheduler·
범용 선택기는 없으며 미실행 모델/사람 결정 항목은 미완료로 남겼다. 문서 diff·상대 링크를
확인했고 전체 스위트/화면/파이프라인 재검사는 하지 않았다. 기존 회차·사용자 변경·문서 이동과
옛 결과·사람 리뷰·참조 품질 표식을 보존했으며 commit/push는 하지 않았다.
아래는 배포 전 시점 기록이며 삭제하지 않는다.

2026-09-11 MVP 배포 전 결과(아래 9월 10일 기록을 대체 삭제하지 않음): native 보조 후보와 core 분리,
outline/부분 반환 v2, 공백 쪽 보존, 후보와 무관한 직접 쪽 선택·준비 target PDF 조회를
worktree에 구현했다. 기존 rhwp commit `cac9b4f7cc743535cd7c00fe4f286abd67e7145b`과 원본·
기존 snapshot/실패/사람 리뷰는 보존했다. 새 운영 migration·배포·재수집·재변환·activation·
enqueue·Qwen HTTP는 0이다. 독립 구현과 Sol medium 계약 검토를 Orca callback으로 받아
공유 작업트리에 통합했고, 별도 commit/merge로 사용자 변경을 덮지 않았다.

검증은 native parser/processor 소유 사례 88건과 native snapshot 호환 34건, v2 sidecar
직접 전달 사례, 신규 공백/근거 사례4건을 통과했다. 공백 worker가 두 파일을 넓게 선택한
최초 실행은 135통과/1실패였고, 실패는 기존 real ModelClient fixture의 context metadata
누락이었다. 해당 fixture에 가짜 확인 context만 주입하고 그1건만 통과시켰다. 제품 정책이나
실제 identity 확인을 우회하지 않았다. 추가 API/범위 선택6건, 안전한 target PDF5건,
원본/PDF 최신 scan·stale 문서 거부3건, v1 outline 업그레이드/자동 ready 확인도 통과했다.
scan fixture의 필수 scanner_version/safe_result 누락은 fixture만 수정해 실패2건만 확인했다.
부분 후보 준비→기존 core cache 재사용→반환 개수/대기 target 연결1건도 통과했다.

임시 PostgreSQL 두 세션의 새 범위 확정↔옛 target enqueue 및 queued/running 거부3건이
통과했다. 통합 리뷰에서 입력 확정에 불필요한 전역 실행 gate를 제거하고 enqueue와 기존
notice 행 잠금을 공유하도록 단순화했으며 해당 경쟁1건만 다시 통과시켰다. 또한 새 범위 뒤
이전 completed가 API current/회사 핏에 남는 결함을 수정하고 API·이력·후속 소비·원본 결과
불변성을 묶은1건을 통과했다(`test_new_manual_range_keeps_old_verified_result_in_history_not_current`).
중지/게시 로직은 이번에 바꾸지 않아 기존 PostgreSQL 중지·늦은 응답 증거를 재사용했다.

| 0910 대상 | 이번 판정 | 실제로 확인한 구간 |
|---|---|---|
| 744·749·759·761 (4건) | 입력 준비 가능, 내용 검증 미실행 | 744·759만 기존 version/hash/PDF와 전체 선택 입력을 읽기 전용 재확인하고 offline 두 단계 요청 준비. 749·761 준비 결과는 재사용 |
| 743·745·746·747·754·755 (6건) | 계약 차단 원인 코드 해결, 실제 준비 미확인 | 정상 outline/전체·반환 개수 parser·core 분리·소비 계약 격리 검사. 전체 PDF 재변환은 하지 않음 |
| 751·753·756·758·760 (5건) | 담당자 범위 확인 필요 | 753의 전체 고정 page text/PDF hash 확인, 새 선택기 ambiguous_scope_boundary·수동 확정 가능. 기존 2–18쪽/65,141자·용량 실패 그대로 보존 |
| 748·750·752·757 (4건) | 안전한 검토 문서 미선택/차단 유지 | 752의 명시 선택 계약 미연결, 750·757 포괄 오류의 상세 원인 불명확 확인. 안전 검사 우회 없음 |

새 744의 3–9쪽 전체 3,549자(9쪽 공백8자), 759의 4–8쪽 전체 2,171자(8쪽 공백9자)를
보존했다. 초안/형식 재생성/예시 의미 요청 bytes는 각각 14,773/15,112/15,047 및
11,063/11,402/11,527, 출력·chat 예약을 더한 token 상계는 32,181/32,520/32,455 및
28,471/28,810/28,935다. 기존 policy v5 digest·binding과 과거 확인 context262,144를 썼다.
이번 `/models`·tokenize도0이며 의미 preview는 실제 초안/검증 결과가 아니다. 새 semantic
요청은 실제 초안 이후 다시 검사한다. 24,000자는 모델 한도가 아닌 정책 상한으로 유지했다.
35·59·142의 앞선 고정 입력 용량, C-1/C-2/정상 변환 결과는 재실행하지 않았다.

읽기 전용 전후 DB 지문(`md5(string_agg(to_jsonb(t)::text,'|' ORDER BY id))`)은 개요8건
`d9f8cd062b2e4af6cde0e35d1cb927c1`, 이전 notice<743 attempt7건
`cbca1e3bff7d1b85fa91af619a9e3652`, 개요 리뷰140건
`15ea91ce5b70175bb59170068ba6087d`로 동일하다. 새 결과/call/verification·active attempt는0,
OFF 감사 `e898cbe3-a50c-4a1a-a9e3-477ef277b758`도 그대로다. 운영 DB는0025이고 기존 web/
문서 worker 이미지는 변경하지 않았다. 위4건은 수정 코드의 **준비 가능**이지 운영의 기존
failed 행을 성공으로 바꾼 것이 아니다. 상세 고정 입력·offline preview는
[기존 0910 준비서의 MVP 기록](../../.dryforge/prespec-0910-preparation-3vfrYK/README.md)에 연결한다.

화면 직접 검증: 후보 기본 선택/직접 쪽 전환, 후보 없음, 부분 후보, 자동 ready+용량 실패,
안전/active 저장 차단, 확정 요약을 검사했다. 첫 production build 뒤 6통과/1실패는 Astryx
ToggleButtonGroup이 자식 disabled를 덮는 동작 때문이었다. 부분 목록에는 후보 선택 버튼을
만들지 않는 최소 수정 후 영향1건과 해당 선택7건이 통과했다. 최종 리뷰에서는 같은 target의
completed 개요 옆에서도 “내용 미검증”을 고정 표시하던 문구를 중립적으로 고치고 그
공존1건을 추가했다. 변경 뒤 production build1회와 기존 영향7건+공존1건 **8통과/0실패/
0skip**, 1280×800·1440×900을 확인했다. 최초 anchored grep의 no-tests 오류는 선택식만
고쳐 재빌드 없이 검사했다. 마지막 명령은 `PW_PORT=4187
PW_OUT_DIR=/tmp/bidops-ui-range-review-866c64c npx playwright test --project=app
page-overview.spec.ts --grep '<MVP 범위 선택 7개 이름|completed overview alongside the latest range target does not claim content is unverified>'`이며 파일의 해당8개 사례만 실행했다.
운영 화면/실제 모델 결과 검증이 아닌 격리 API fixture 화면이다. 기존 chunk/라이브러리
경고는 남으며 전체 스위트·전체 화면·전체 파이프라인은 실행하지 않았다.

MVP 최종 리뷰 완료: core와 보조 실패의 분리, 새 sidecar/REST/웹 상태·후속 현재성,
원본과 이전 결과/사람 리뷰 불변성, 미검증 게시 금지·OFF 늦은 응답 차단의 기존 게이트,
정책24,000자와 실제 context의 구분을 최종 diff와 위 증거로 대조했다. 리뷰 수정은
notice 잠금 단순화1건, 새 범위 뒤 이전 완료/검증 진단·회사 핏 재사용 차단1건, 화면 중립
문구/공존1건에 한정해 검증했다. 새 범위에는 이전 verification을 현재 진단으로 붙이지
않으며 원래 검증/결과는 이력에 남는다. 새 테이블·scheduler·옵션·범용 범위 선택기는 없다.
4건의 `activation-mvp-pending-model-approval.json`을 새로 만들고 기존 loader preview로
계약 일치/activation_performed=false를 확인했다. 정상8회/최대12회(의미 최대4회)라는
준비 상한일 뿐 **승인/실행은0**이다. 배포·6건 재준비·사람 쪽 선택·752 계약·전송 승인이
미완료이므로 상위 후속/실사용 체크는 완료 처리하지 않는다.

`python3 skills/bidops-collect/scripts/collect_notices.py --from-date 2026-09-10 --to-date 2026-09-10 --skip-bids --timeout 300 --output-dir data/runs/prespecs-20260910-claims-reference-sbh1rl`
exit 0: 21:40:13 KST 기준 225건(candidate 32/audit 193), 원문 1페이지·HTTP 1회·경고 0·
complete=true다. 당일 종료 전 시점 snapshot이므로 9월 10일 최종 전건 수로 단정하지 않는다.
SW=Y 20건 중 19건에 첨부가 있다. 새 건은 C-1/변환 동결 결과가 없고 기존 35/59/142 승인과
target을 재사용할 수 없다. 임의 등급 보정으로 자동 경로를 열지 않으며, 명시적 개요 대상
선택·원문 준비·정확한 payload 승인이 필요하다. 최초 수집 시점에는 신규 DB 적재·첨부/모델 호출이 0회였으며 후속 19건 적재 결과는 아래에 별도로 기록한다.
정확한 20건 목록과 첨부 있는 19건의 [대상 제안](../../.dryforge/prespec-deploy-20260910-SBh1rl/README.md)을
준비했다. 전건이 준비될 때 정상38회/최대57회(각 attempt3회·의미1회)이며 호출 상한 변경은
아니다. 목록/예상 상한만으로 source/target·실제 두 단계 payload 승인을 대신하지 않는다.
Orca 읽기 전용 worker의 완료 callback도 날짜 경계·전송 승인·명시 표본 경로를 확인했고
settled worker 해제 처리 후 결과를 반영했다.

후속 “진행해”: 위 첨부 있는 19건의 원문/PDF 준비를 승인받아 기존 회차에 새
`validation-set.v2`만 추가했다(analysis10/audit9, 첨부27). 전체225건과 raw/provenance
3파일 SHA는 동일하고 새 표본 파일의 로컬/web SHA도 일치한다. 표준 앱 조립+ingest
1회로 DB notice743–761을 적재하고 첨부 대기27개를 생성했다. DB run ID는
`prespecs-20260910-claims-reference-sbh1rl--20260910T124013.29682Z`다. C-1 결과가 없어
`screening_results_missing` 경고1건이며 judgment/review/screening 생성0건이다.
API에서 새19건의 SW=Y·등급null·추적미선택·개요null·첨부대기 합계27을 확인했다.

첨부 다운로드 전 `sudo -n iptables -S DOCKER-USER`가 관리자 인증 필요로 실패했다.
기존 egress network나 9월7일 특정 worker IP용 스크립트만으로 현재 방화벽을 검증했다고
간주하지 않는다. 관리자가 실제 worker source에서 `www.g2b.go.kr`의 현재
`211.42.74.250:443`만 외부 허용되는지 확인할 때까지 다운로드를 보류한다.
권한/방화벽/서비스 변경은 하지 않았다. 신규 source/PDF/target과 두 단계 실제 입력 용량
검사는 미실행이고 모델 HTTP0, activation OFF, active v4 attempt0, call ledger/verification0다.
[이번 준비 증거·19건 목록·재개 조건](../../.dryforge/prespec-0910-preparation-3vfrYK/README.md)을
남겼다. 이번 새 표본에 기존35·59·142 입력/용량 결과를 대입하지 않으며 제품 코드 변경이나
전체 테스트/빌드/화면 재검사는 하지 않았다.

신규 준비 최종 점검: 정확한 승인19건과 적재/API19건·첨부27개, 원문/복사본 hash,
OFF/미실행 증거를 대조하고 `git diff --check`를 통과했다. Orca 읽기 전용 독립 검토의
source-only/실행 target 분리와 동적 semantic·형식 correction 승인 범위를 재개 조건에
반영했다. 원문 취득 전이므로 신규 payload·용량 통과나 품질/전체 작업 완료를 주장하지 않는다.

후속 방화벽 확인/승인: 사용자의 관리자 조회로 DOCKER-USER가 비어 있고 기존 전용 체인이
없음을 확인했다. 사용자에게 전용 worker만 G2B443을 허용하는 최소 변경을 승인받았다.
고정 source `172.19.0.2`·현재 bridge/network/DNS를 검사하는 일회성 적용 스크립트를
준비하고 구문·비관리자 쓰기 전 거부를 확인했다. 기존 규칙 flush/교체·서비스 변경은 없다.
에이전트 sudo 인증은 여전히 없어 관리자 직접 적용이 필요하며 실제 적용·허용/차단 probe·
첨부 다운로드는 미실행이다. 적용 후 검증 전까지 source/PDF/target·Qwen 미완료를 유지한다.

후속 “script는 실행했어”: 사용자의 적용 보고 뒤 같은 고정 worker source `172.19.0.2`에서
credential 없는 probe를 실제 실행했다. G2B `211.42.74.250:443` TLS1.3 허용,
`1.1.1.1:443`·G2B80·host gateway18887 거부를 확인했다(HTTP/model0). 에이전트의 sudo
인증은 여전히 없으므로 host 규칙 목록을 직접 읽었다고 주장하지 않는다. 이 결과가 위 적용
대기 기록을 대체한다. 이후 동일 source의 일회성 worker 역할로 첨부27개를 한 번씩 처리했다.
완료23/차단4(747·748 각 unsupported_extension1, 750·757 각 unsafe_document1), 재시도0이다.
안전한 RFP를 선택하지 못한748·750·757과 명시 RFP가 없는752는 PDF 준비에서 제외했다.

내부 DB/storage/scanning만 연결한 app 역할 one-shot에서 승인된 RFP15개를 기존 R7
변환기로 준비했다. source-only activation `2bdb5d82-6aa5-4944-b701-602b267c2e40`,
`enqueue=false`, 종료 OFF `e898cbe3-a50c-4a1a-a9e3-477ef277b758`이다. model gate는
세 용도 모두 닫혔고 모델 key·외부망·analysis worker를 제공하지 않았다. snapshot9개 중
5개는 range ready, 751·756은 scope_heading_missing, 758·760은 scope_end_missing으로
사람 범위 확인 대기다. 743·745·746·747·754·755는 기존 R7의
`pdf_preparation_failed:section_candidates_invalid`로 실패했다. 원문은 보존했고 변환기·
이미지·worker 설정을 고치거나 안전 검사를 우회하지 않았다.

읽기 전용 원본15개 재조회에서 version/hash/size가 모두 일치했다. 최초 ready export는
744의 manifest_invalid로 중단됐다. 원문이 아니라 로컬 export의 건별 실패 수집만 보완한
뒤 나머지 입력을 확인했다. 744의9쪽(8자)·759의8쪽(9자)은 선택 경계의 공백만 있는 페이지다.
manifest와 각 page hash/byte count는 일치하지만 기존 runner가 빈 페이지를 거부하므로
호출 준비에 포함하지 않았다. 749·753·761의 manifest/PDF bytes 검증은 통과했고 동결 사본을
새 파일로 저장했다. 753은2–18쪽 전체65,141자로 source/payload 상한을 초과했다.
`input_limit_exceeded`를 기존 `failed/input_capacity_exceeded`로 기록했으며 내용 검증은
시작하지 않았다. 744·759도 기존 준비 실패 함수로 `failed/manifest_invalid`를 남겼다.
3건 모두 terminal 준비 실패일 뿐 enqueue·모델 실행이 아니며 기존 target은 불변이다.

| notice | 전체 선택 쪽/원문자 | 초안/의미 예시 prompt자 | 초안/형식 재생성/의미 예시 요청 UTF-8 bytes | 출력·chat 예약 포함 상계 |
|---:|---|---|---|---|
| 749 | 9–13 / 6,592 | 8,359 / 8,989 | 22,070 / 22,409 / 22,301 | 39,478 / 39,817 / 39,709 |
| 761 | 4–5 / 798 | 2,323 / 3,037 | 8,200 / 8,539 / 8,617 | 25,608 / 25,947 / 26,025 |

두 건은 이전 확인 context262,144·출력예약16,384·chat예약1,024 및 stage payload 상한 안이다.
이번 /models·tokenize 조회0이며 context를 새로 확인한 것은 아니다. 의미 예시는 원문에서
고른 정확한 인용으로 만든 요청 형태일 뿐 Qwen 응답·사람 정답·실제 semantic bytes 승인이
아니다. 승인된 전체 원문+실제 초안/결정적 검증 인용으로 만드는 동적 semantic과 허용 형식
correction 범위까지 승인받은 뒤 각 실제 요청을 다시 검사해야 한다. 원문 절단·요약·분할은
하지 않았다. 753을 여러 조각으로 검토하는 방식/호출 증가도 승인하지 않았다.

Orca 독립 worker가 offline preview 도구를 구현하고 기존35 fixture의 runtime 초안/형식
요청 exact 일치·전체 원문 보존을 확인했다. 완료 callback을 받아 해제 처리 후 통합했다.
최종 도구 점검에서 예외의 경로/원문 노출 방지만 보완하고 해당 거부1건을 확인했다.
새749·761 미리보기 exit0, 753은 input_limit_exceeded/exit1이며 모델HTTP0이다.
API 신규19건 모두200, 변환 실패6/범위 확인4가 일치했고 추가 준비 실패3건은 변경 후 해당
API의 failed/사유·reviews=[]·verification=null을 확인했다. 로컬 확인문이 처음에는 reviews를
items로 잘못 읽어 KeyError가 났으며 API 계약 필드만 바로잡았다. 최초 증거의 items 수는
결과 개수 근거로 사용하지 않는다. PDF 준비 직전의 개요8·이전 attempt7·개요 검토 행140개
지문은 동일하다. 최종 active attempt/job·새 결과·call/verification은 모두0이며 one-shot은
모두 종료됐다. 실제 화면 검사를 반복하지 않고 기존 용량 안내 컴포넌트와 새 API를 대조했다.
[첨부·PDF·원본·용량·후속 승인 준비물](../../.dryforge/prespec-0910-preparation-3vfrYK/README.md)을
남겼다. 기존35·59·142 용량 결과는 재사용하되 신규 표본에 대입하지 않았고 C-1/C-2·회사 핏·
심층 검토는 실행하지 않았다. 실제 Qwen은0회, 새 결과/검증ledger0이며 준비된2건의 정상4회/
최대6회 전송 승인이 남아 있다. 참조 표식은 운영 품질 승인이 아니다.

이번 후속 최종 점검은 추가된 실행 도구·문서 diff와 실제 DB/API/객체 증거만 대상으로 했다.
준비 실패를 성공으로 승격하지 않았고 source-only/모델 실행 승인 분리·OFF/큐0·이전 지문을
확인했다. `git diff --check` 통과, 이전 작업 문서 경로는 없다. 새 제품 코드·scheduler·테이블·
모델 전송은 없으며 미해결 변환6건/공백 manifest2건과 범위·용량·문서 선정 후속은 남겨 둔다.

새 쓰기를 열기 전 v4를 중지하고 기존 활성 attempt를 명시적으로 닫는다. 새 migration·worker·API·웹·정책을 호환되는 묶음으로 배포한 뒤 승인한 표본만 활성화한다. 기존 v1 activation과 v4 policy는 이력으로 읽되 새 다단계 실행을 자동 승인하지 않는다.

문제가 생기면 새 activation을 OFF로 전환하고 미종료 작업을 취소한다. DB·객체·과거 결과와 새 호출 이력은 보존한다. 데이터가 쓰인 migration을 기계적으로 downgrade하거나 이전 worker로 큐를 자동 재실행하지 않는다. 이전 reader를 사용할 경우 신규 계약에 대한 명시적 차단/조회 제한을 확인하고 수정된 reader로 복구한다.

## 모든 작업 완료 후 최종 리뷰

- [x] 구현·문서 동기화·수정 범위 검증과 실행 준비를 기준으로 최종 리뷰를 진행했다. 승인 대기인 실사용 참조 검증은 위 체크리스트에 미완료로 남기고 운영·품질 완료와 구분한다.
- [x] 최종 diff와 작업별 검증 결과를 기준으로 네 문제의 해결, 채택한 주장 검증, 상태·계약·웹 표시의 일치, 원본/이력 보존과 중지 후 게시 차단을 확인한다.
- [x] 사용하지 않는 추상화·설정·중복 로직·불필요한 테스트·범위 밖 변경이 추가되지 않았는지 확인한다.
- [x] 최종 리뷰 자체를 이유로 전체 테스트·빌드·화면 확인·모델 호출을 다시 실행하지 않는다. 리뷰에서 결함을 찾아 수정한 경우에만 해당 수정 검증과 관련 diff 재검토를 수행한다.
- [x] 최종 보고에는 변경 요약, 실행한 검증과 결과, 실사용 확인 범위, 남은 문제만 정리한다.

최종 리뷰 결과: 수집 불변성, 새 상태/ledger/조회의 일치, 검증 후 결정적 구성, 중지 이후 게시 금지와 이전 품질/사람 리뷰 보존을 위 검증과 대조했다. 공유 identity 상태·요청 조립기·단일 gate는 직접 소비자가 있고 새 scheduler/범용 검증 프레임워크는 추가하지 않았다. 원응답 저장 실패·안전 오류, context metadata 경계, 용량 문구, 범위 조회 namespace에서 발견한 문제는 해당 절의 선택 검사로만 수정 확인했다. 전체 스위트/전체 화면/전체 파이프라인 재실행은 하지 않았다. 독립 작업은 Orca worker별 파일 소유를 나눠 callback 결과를 작업트리에 통합했고 commit/push/운영 배포는 하지 않았다. 기존 회차·백업·다른 문서 이동을 보존했으며 이전 작업 문서 경로는 만들지 않았다.

문서만 수정한 뒤에는 내용·링크·diff만 확인한다. 문서 동기화를 이유로 통과한 앱 검사를 다시 실행하지 않는다.

운영 후속 최종 리뷰: 추가 diff의 sequence 최소 SELECT, runtime head0025, 실제 backup/
서비스 전환/row 지문과 API 증거를 대조했다. revision 누락 수정에만 기동 경계2건을 추가
검증했고 통과했던 ledger·화면·전체 파이프라인은 반복하지 않았다. 신규 수집 원문은 배타
회차에 보존했고 SW 후보를 등급·최종 승인으로 승격하지 않았다. 실제 Qwen/신규 target 준비와
사람 검토는 미완료로 남긴다. 별도 scheduler·테이블·제품 설정은 추가하지 않았다.
