# 미해결 문제

기준일: 2026-08-27

## 개발용 Codex 심층 검토 경로가 외부 전송 허용 범위를 넘는다

- 재현 조건: `docker-compose.t7.codex-reference.yml`로 `BIDOPS_ANALYSIS_PROVIDER=codex-exec`, reference mode, 승인 notice ID를 설정하고 심층 검토 stage를 실행한다.
- 증상: `CodexExecClient.invoke()`가 일반 vLLM과 같은 `build_prompt()`를 사용한다. stage 입력에는 구조화된 RFP 요구사항 excerpt가 들어가고 delivery stage에는 회사 profile facts·evidence가 들어가므로 hosted Codex에 전송될 수 있다.
- 영향: 공개 발주계획 메타데이터와 별도 승인된 최소 회사 역량 요약만 외부 모델에 보낸다는 확정 정책을 위반한다. 공고 allowlist와 기본 비활성은 실행 승인만 제한할 뿐 금지된 payload 종류를 제거하지 않는다.
- 지금 해결할 수 없는 이유: provider code와 Compose overlay의 삭제·재설계는 실행 경로와 기존 reference 검증을 함께 바꾸므로 별도 구현·회귀 검증이 필요하다.
- 접근 방법: 이 overlay와 `codex-exec` deep-review provider를 사용 금지 상태로 유지하고, 외부 비교 실험이 필요하면 발주계획 전용 projection·payload preview·사람 승인 경계를 별도로 구현한다. 테스트는 RFP, 첨부, profile 전문·evidence, 내부 review 필드가 payload에 들어가면 호출 전에 실패하는지 확인해야 한다.

## 런타임 이미지에 회사 프로필 자료가 포함된다

- 재현 조건: 현재 `web/Dockerfile`로 runtime image를 build한 뒤 `/app/docs/reference`와 `/app/web/backend/app/screening` 내용을 검사한다.
- 증상: `COPY docs/reference /app/docs/reference`가 `company-profile.md`와 회사 실적 제목 TSV를 복사하고, 별도 TSV copy가 이를 반복한다. `COPY web/backend/ ./`는 `baseline_company_profile.md`도 복사한다. `.dockerignore`는 reference PDF만 제외한다. Dockerfile의 회사자료 제외 주석과 실제 image 내용이 다르다.
- 영향: image registry, build cache, image export에 회사 프로필·실적 근거가 포함될 수 있어 회사자료를 image에 넣지 않는 보안 경계를 위반한다.
- 지금 해결할 수 없는 이유: baseline fallback과 profile snapshot 검증이 해당 파일에 의존하므로 단순 ignore만 추가하면 runtime·test 계약이 깨진다. profile 주입과 검증 경계를 함께 바꿔야 한다.
- 접근 방법: 일반 `docs/reference`와 backend baseline의 bulk copy를 제거하고, 허용된 공개 runtime reference만 명시적으로 복사한다. 필요한 회사 프로필 snapshot은 승인된 read-only volume·객체·secret 경계로 실행 시 주입하고 digest를 검증한다. image filesystem과 build context에 `company-profile.md`, 회사 실적 제목 TSV, `baseline_company_profile.md`가 없음을 회귀 테스트로 고정한다.

## 프로필 조회 API가 원문과 서버 경로를 노출한다

- 재현 조건: `GET /api/profile/snapshots`, `GET /api/profile/sections`, `GET /api/profile/unknowns`를 호출하거나 프로필 파일 읽기 오류를 유발한다.
- 증상: snapshots item의 working-tree `source_ref`는 내부 상대 파일 경로다. sections 응답은 filesystem `source`, `raw_blocks[].raw`, section `raw`, `source_line`을 포함한다. unknowns도 filesystem `source`를 반환하며 `parse_errors` 문자열에 원본 `OSError`의 절대 경로가 들어갈 수 있다. sections·unknowns는 현재 working tree parser 결과에 묶이고 승인된 불변 profile version·digest를 응답에 고정하지 않는다.
- 영향: 사내망 사용자 모두에게 UI에 필요한 범위를 넘는 회사 프로필 원문과 서버 배치 구조가 노출된다. 실행 중 working tree가 변하면 같은 조회 route가 다른 프로필을 반환할 수 있어 승인 snapshot 경계도 흐려진다.
- 지금 해결할 수 없는 이유: Pydantic schema, parser presenter, profile snapshot 선택, frontend type·화면을 원자적으로 전환하고 기존 client 호환성과 노출 방지 회귀를 같이 검증해야 하므로 아직 구현되지 않았다.
- 접근 방법: 기존 세 route를 운영에서 비활성화하고 `bidops.profile-projection.v1`로 교체한다. snapshots에서 `source_ref`를 제거하고, sections·unknowns는 승인 profile version·digest, 구조화 항목, `unknown`, 안정 error code만 반환한다. filesystem source, source line, raw block·text, 원문 예외를 schema·serializer·frontend type에서 제거한다. 파일 경로·원문 sentinel이 response에 없음을 통합 테스트로 고정한다.

## legacy 첨부 업로드가 악성코드 검사와 객체 격리를 우회한다

- 재현 조건: `POST /api/notices/{notice_pk}/attachments`로 허용 확장자·크기의 파일을 등록한 뒤 download endpoint를 호출한다.
- 증상: legacy attachment service는 확장자와 50MiB 한도만 확인하고 `/app/web/data/attachments`로 rename한 뒤 DB를 commit한다. MIME 판별, quarantine, ClamAV, MinIO object version·hash 없이 바로 다운로드할 수 있다. T7은 `/app/data`와 `/app/reports`만 volume으로 연결하므로 이 attachment 경로는 container 재생성 때 유실될 수도 있다. `AttachmentResponse.stored_path`는 DB 값을 그대로 내보내 notice directory와 로컬 저장 layout을 client 계약에 노출한다.
- 영향: 파일 내용이 확장자와 다르거나 악성인 첨부가 웹 process의 로컬 저장소와 사용자 download 경로로 들어가 Lean document upload의 안전 경계를 우회한다. DB row는 남고 파일만 사라지는 불일치도 생길 수 있고, path 노출은 서버 배치 구조를 외부 wire에 고정한다.
- 지금 해결할 수 없는 이유: 기존 attachment 화면·다운로드·DB row를 Lean document object lifecycle로 이전하고 기존 manual attachment 호환 정책을 정해야 한다.
- 접근 방법: 운영에서는 legacy mutation·path 조회를 비활성화한다. 장기적으로 모든 upload를 quarantine → MIME·size → ClamAV → versioned object → ready projection으로 통합하고 clean 전 download를 거부한다. `stored_path`를 response schema와 serializer에서 제거하고 우회 endpoint가 없는지 API 통합 테스트로 고정한다.

## MinIO versioning 초기화가 실패해도 stack이 계속 기동한다

- 재현 조건: MinIO에서 bucket versioning 명령이 권한·호환성 오류로 실패하는 환경에서 `scripts/minio-init.sh`를 실행한다.
- 증상: `mc version enable` 뒤 `|| true`가 모든 실패를 삼키고 실제 versioning 상태를 다시 확인하지 않는다. init service는 versioning이 꺼져 있어도 성공할 수 있다.
- 영향: DB가 object version ID를 불변 정본처럼 저장하는 전제가 깨지고 overwrite·backup·restore에서 같은 object key의 역사 bytes를 보장할 수 없다.
- 지금 해결할 수 없는 이유: bootstrap의 멱등성 처리와 실제 상태 검증, 기존 non-versioned bucket의 전환 정책을 함께 설계하고 MinIO 통합 테스트가 필요하다.
- 접근 방법: 이미 존재한다는 안전한 결과만 명시적으로 허용하고 그 밖의 오류는 실패시킨다. 각 bucket에서 versioning enabled 상태를 조회·검증한 뒤에만 init service를 성공으로 끝낸다.

## 객체 복구가 원본 version ID와 복구 대상 version ID를 혼동한다

- 재현 조건: `backup-objects.sh`로 version별 backup을 만든 뒤 빈 MinIO에 `restore.sh`를 실행하고 `verify-active-hashes.sh`로 검사한다.
- 증상: backup manifest는 source version ID를 기록하지만 local file을 target에 `mc cp`하면 새 target version ID가 생긴다. restore는 새 ID를 기록하지 않고 verifier는 source version ID로 target object를 조회한다. `ACTIVE_HASH_MANIFEST`를 DB active reference에서 생성·완전성 검사하는 경로도 없다.
- 영향: 정상 복구도 version lookup에서 실패하거나, 수동 manifest가 일부 active object를 빠뜨려도 DB 연결만 확인한 채 복구 검증이 끝날 수 있다. object-first 복구 완료를 주장할 수 없다.
- 지금 해결할 수 없는 이유: target version mapping, DB object reference 재결합 여부, active manifest 생성 계약을 함께 결정해야 한다.
- 접근 방법: restore 때 source version → target version mapping과 stored-byte hash를 기록하고 DB가 가리키는 모든 active object를 query해 manifest와 일대일 대조한다. verifier는 target version ID와 hash를 검사하며 누락·추가·중복을 모두 실패시킨다.

## 분석 worker DB 역할이 모든 업무 table을 수정할 수 있다

- 재현 조건: migration 뒤 PostgreSQL에서 `worker` role의 table privilege를 조회한다.
- 증상: `scripts/migrate.sh`가 현재와 미래의 `bidops` 모든 table에 `SELECT, INSERT, UPDATE, DELETE`를 부여한다.
- 영향: 분석 worker 자격증명이 탈취되거나 코드가 오동작하면 사람 리뷰·최종 의견·정책·감사 등 worker 책임 밖의 row도 수정할 수 있어 최소 권한과 사람 결정 경계가 DB에서 강제되지 않는다.
- 지금 해결할 수 없는 이유: worker가 실제로 읽고 쓰는 table·sequence와 stored operation을 확정해 migration grant를 세분화해야 한다.
- 접근 방법: analysis claim·stage·report 전이에 필요한 table과 operation만 allowlist로 grant하고 사람 의견·review·policy·audit의 직접 DML을 revoke한다. future default 전체 DML을 제거하고 allow/deny matrix를 PostgreSQL 통합 테스트로 고정한다.

## PostgreSQL과 MinIO 관리 port가 모든 host interface에 publish된다

- 재현 조건: 기본 `docker-compose.t7.yml`을 기동하고 host의 listen address를 확인한다.
- 증상: PostgreSQL, MinIO API, MinIO console port mapping에 host IP가 없어 Docker가 기본적으로 모든 host interface에 bind할 수 있다.
- 영향: Compose internal network와 무관하게 LAN에서 DB·객체 저장소 port에 직접 접근할 수 있어 애플리케이션 API만 사용하는 접근 경계를 우회한다. 실제 노출 범위가 host firewall 상태에 의존한다.
- 지금 해결할 수 없는 이유: 운영자가 host에서 DB·MinIO 관리 접근을 필요로 하는지와 reverse proxy·방화벽 경계를 확정해야 한다.
- 접근 방법: 기본 template은 `127.0.0.1`에만 bind하거나 내부 전용으로 port publish를 제거한다. 원격 관리가 필요하면 별도 opt-in overlay와 source allowlist를 사용하고 LAN 외부에서 연결 거부를 검증한다.

## legacy mutation 일부가 담당자 이름과 감사 기록 없이 실행된다

- 재현 조건: legacy review upsert, attachment upload·delete, agency portal create·patch, run ingest·subprocess 실행 endpoint를 호출한다.
- 증상: 해당 경로는 `X-BidOps-Actor-Name`을 요구하지 않거나 reviewer가 optional이고, 작업별 `AuditEvent`를 같은 transaction에 남기지 않는다. Lean 문서·심층 검토와 screening control 계열만 별도 actor·audit 경계를 가진다.
- 영향: 사내 사용자가 변경·승인할 때 이름을 남긴다는 채택 결정이 API 전체에서 성립하지 않으며 누가 첨부를 지우거나 포털·리뷰·회차를 바꿨는지 일관되게 추적할 수 없다.
- 지금 해결할 수 없는 이유: 기존 frontend와 pipeline client의 request 계약을 함께 바꾸고 과거 actor 없는 기록의 표시 정책을 정해야 한다.
- 접근 방법: 모든 사람 mutation에 공통 actor parser와 safe audit service를 적용하고 mutation 결과와 같은 transaction에서 event를 기록한다. 과거 row는 actor를 추정하지 않고 `unknown`으로 남기며 기존 client를 명시적 계약 version으로 전환한다.

## 현재 보고서 renderer가 screening v3를 처리하지 못한다

- 재현 조건: `bidops.screening.v3`의 `screening-results.json`을 현재 report stage 또는 `render_report.py`에 전달한다.
- 증상: current screening runtime은 v3를 만들고 적재기는 v3를 받지만 report renderer는 `bidops.screening.v2`만 허용해 즉시 종료한다.
- 영향: 새 판정 실행의 결과를 기존 HTML·feedback 흐름으로 연결할 수 없고 자동 pipeline에서 판정과 보고 사이가 끊긴다.
- 지금 해결할 수 없는 이유: v3의 partial/failure·execution binding을 HTML과 feedback에 어떻게 표시할지 소비자 계약과 회귀 기준이 필요하다.
- 접근 방법: v2 의미를 바꾸지 않은 채 renderer에 명시적 v3 adapter를 추가하고 부분 성공·failure artifact·승계 provenance를 표시한다. v2와 v3 fixture의 결정성을 각각 검증한다.

## 승인된 프로필 기준선 commit이 현재 저장소 history에 없다

- 재현 조건: 현재 source checkout에서 backend 전체 테스트를 실행하면 `test_baseline_git_snapshot_and_source_validation`과 `test_vendored_baseline_equals_git_show_in_a_source_checkout`가 실패한다.
- 증상: `git cat-file -e ee621835db934ddac944f7a07a986ed0b73ecc7a`가 해당 commit을 찾지 못한다.
- 영향: backend 결과가 741 passed, 5 skipped, 2 failed에 머물러 현재 저장소 기준 전체 green을 주장할 수 없다. 운영 profile bytes 검증도 저장소 이력과 vendored 기준선 중 어느 쪽이 권위인지 불명확하다.
- 지금 해결할 수 없는 이유: 승인 baseline은 선행 저장소 history에서 만들어졌고, 어떤 commit을 현재 저장소에 보존할지 또는 새 기준선을 승인할지는 이력 소유자와 업무 담당자의 확인이 필요하다.
- 접근 방법: 승인된 profile bytes와 source commit을 다시 확인한 뒤, 현재 저장소가 그 commit을 보유하게 하거나 새 immutable baseline과 digest를 승인한다. source checkout과 container fallback 테스트가 같은 bytes를 확인해야 한다.

## 문서 준비와 실패 심층 검토 재시작을 화면에서 완료할 수 없다

- 재현 조건: ready document bundle이 없는 공고를 브라우저에서 열거나 deep-review attempt가 실패한 상태를 연다.
- 증상: 조회와 ready bundle 이후 심층 검토 화면은 있지만 bundle 생성·문서 upload·metadata 수정·확정, 실패 attempt의 새 attempt 생성 action이 없다.
- 영향: 담당자는 curl 또는 CLI를 사용해야 하므로 목표 업무 흐름이 화면에서 끊기고, actor·idempotency·상태 fence를 잘못 다룰 가능성이 커진다.
- 지금 해결할 수 없는 이유: backend 계약은 준비됐지만 frontend Phase 3 구현과 browser 회귀 검증이 별도 코드 작업으로 남아 있다.
- 접근 방법: typed Lean API client, document preparation panel, terminal failure 전용 retry, polling, 403/503 상태 표현을 구현하고 fake API browser 흐름과 좁은 viewport를 검증한다.

## 개발계정 일일 1,000회 한도의 실제 여유가 측정되지 않았다

- 재현 조건: 발주계획·사전규격을 3일 window로 page 끝까지 수집하고 endpoint·page·retry별 실제 요청 수를 집계한다.
- 증상: 알려진 것은 약 1,200개 발주계획과 약 40개 SW 사전규격이라는 레코드 규모뿐이며, 페이지 크기·endpoint 분할·정정 조회·재시도를 포함한 호출 수 기록은 없다.
- 영향: 일 1,000회가 초기 실험에 충분하다는 추정은 가능하지만 scheduler를 안전하게 활성화하거나 운영 증액량을 산정할 근거는 부족하다.
- 지금 해결할 수 없는 이유: 신규 수집기와 quota telemetry가 아직 없고 실제 개발계정 응답의 pagination을 관측하지 않았다.
- 접근 방법: 동결 3일 실험에서 실제 HTTP 요청을 endpoint·page·retry별로 기록하고 cache hit를 분리한다. 700회 경고, 900회 신규 요청 중지로 시작한 뒤 관측치를 이용해 운영계정 활용사례와 증액량을 정한다.

## 사설 vLLM model artifact가 불변 digest로 고정되지 않았다

- 재현 조건: analysis worker preflight와 `/v1/models` 응답으로 실행 model identity를 확인한다.
- 증상: served model ID `qwen3.8-27B`는 확인할 수 있지만 weight digest가 응답에 없고 server image도 mutable tag를 사용할 수 있다.
- 영향: 같은 model name이 다른 bytes를 가리켜도 실행 당시 승인한 artifact와의 차이를 자동 검출하지 못할 수 있다.
- 지금 해결할 수 없는 이유: image digest와 model revision 또는 로컬 artifact digest는 모델 서버 운영자가 제공해야 한다.
- 접근 방법: server image digest, immutable model revision·artifact digest를 deployment manifest에 고정하고 startup preflight가 이를 quality manifest와 대조하도록 provider 계약을 확장한다.

## 실제 심층 검토 품질 corpus와 사람 gold가 부족하다

- 재현 조건: 대표 HWP/PDF에서 요구사항 recall, 사람 일치율, unsupported claim 비율을 계산하려 한다.
- 증상: 55개 요구사항 기대 ID 사례는 있으나 원문·claim별 gold mapping과 다양한 기관·문서 형식의 사람 adjudication이 충분하지 않다.
- 영향: Mock E2E와 단일 후보 호출은 실제 사업 판단 품질이나 0.80/0.70/0.10 activation 기준을 증명하지 못한다.
- 지금 해결할 수 없는 이유: 완료 사업의 사용 승인된 첨부와 담당자 기준 답안이 더 필요하다.
- 접근 방법: 공공 SI와 AI·데이터 또는 블록체인 축에서 서로 다른 HWP/PDF 사례를 선정하고 source hash, requirement·자격·배점·위험 gold, claim별 사람 판정을 만든다. 실제 immutable model로 gate를 측정한다.

## 실제 backup·권한·복구 훈련이 없다

- 재현 조건: 운영과 같은 secret·MinIO policy·firewall을 가진 격리 환경에서 PostgreSQL dump와 versioned object backup을 빈 대상에 복구한다.
- 증상: script와 Mock E2E는 있지만 실제 snapshot, object manifest, allow/deny matrix, object → DB → active hash 복구 기록이 없다.
- 영향: RPO·RTO, 최소 권한, 암호화 key 복구, container 재생성 뒤 참조 무결성을 운영 수준으로 주장할 수 없다.
- 지금 해결할 수 없는 이유: 실제 secret manager 주입, 백업 보관 위치, 운영 snapshot, 빈 pre-production target은 저장소 밖의 운영 준비가 필요하다.
- 접근 방법: 운영자가 승인한 복사본으로 역할별 DB 권한, MinIO namespace allow/deny, egress, UID/GID를 검사하고 객체를 먼저 복구한 뒤 DB와 active hash를 대조하는 훈련을 기록한다.

## 담당자 이름은 신원을 증명하지 않는다

- 재현 조건: 사내망 사용자가 mutation에서 다른 담당자의 이름을 입력한다.
- 증상: 시스템은 입력 이름을 감사에 남기지만 실제 사용자의 내부 계정과 일치하는지 확인하지 못한다.
- 영향: 리뷰, 정책 활성화, 외부 모델 전송 승인 기록의 작성자 신뢰도가 사내망 접근 통제 수준에 머문다.
- 지금 해결할 수 없는 이유: 현재는 사내망과 claimed name만 사용하기로 했고 SSO·계정·역할 정보가 연결되지 않았다.
- 접근 방법: 향후 SSO subject를 내부 계정에 매핑하고 세션 만료, 역할, 권한 회수, 기존 claimed-name 감사와의 연결 정책을 도입한다.
