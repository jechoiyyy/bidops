# 보안 정책

## 보호 대상과 신뢰 경계

보호 대상은 공고·첨부 원문, 회사 프로필과 실적, 모델 프롬프트·응답, 사람 리뷰, 정책·품질 승인, API 키, DB·MinIO·모델 자격증명, 백업과 감사 기록이다. 공개 조달 정보도 회사 판단·리뷰와 결합되면 사내 자료로 취급한다.

애플리케이션은 사내망 경계를 전제로 하며 자체 로그인·세션·사용자 계정·역할 테이블을 제공하지 않는다. 사내망 접속 허용이 실질적인 사용자 진입 통제다. `X-BidOps-Actor-Name`은 변경 주체를 기록하는 이름일 뿐 인증·권한 부여가 아니다.

PostgreSQL 17의 `bidops` 스키마와 MinIO 목적별 버킷이 운영 정본이다. SQLite와 파일 객체 저장소는 격리 테스트 또는 일회성 이관 입력에서만 허용한다. scratch는 네트워크 없는 문서 변환의 임시 전달 경계이며 정본을 보관하지 않는다.

## 사용자 진입 흐름

1. 사내망 밖의 요청은 네트워크 경계에서 차단되어 애플리케이션에 도달하지 않아야 한다.
2. 사내망 안의 요청은 별도 로그인 없이 API와 화면에 도달한다. 비밀번호 오류, 세션 만료, 계정 잠금은 애플리케이션에 해당하지 않는다.
3. 조회 요청은 사용자 이름 없이 허용한다.
4. Lean 문서·심층 검토·리포트 변경 API와 legacy 첨부·기관 포털·screening 정책 mutation은 비어 있지 않은 `X-BidOps-Actor-Name`을 요구한다. 정책 request body의 actor field는 호환 입력으로 남아 있지만 header claimed name이 감사의 기준이다. 제어문자, 예약된 `system`, 잘못된 비ASCII 인코딩은 요청 계약 오류로 거부한다.
5. 이름이 유효해도 사용자 신원을 증명하거나 더 높은 권한을 부여하지 않는다. 사칭 방지가 필요한 시점에는 사내 계정 연동을 별도 도입해야 하며 이름 헤더를 인증으로 승격하지 않는다.

사내망 경계를 통과한 모든 사람에게 같은 읽기 권한이 있다는 점이 현재 정책의 한계다. 외부망 공개, 사용자별 파일 제한, 이름만으로 관리자 행위 허용을 주장하는 배포는 금지한다.

현재 legacy 리뷰와 일부 run/subprocess 실행 mutation은 actor를 요구하지 않거나 별도 `AuditEvent`를 만들지 않는다. 이는 허용된 예외가 아니라 구현 격차다. 해당 경로를 이름·감사 경계에 편입하기 전에는 변경 행위 전체의 작성자 추적이 완전하다고 주장하지 않는다.

## 회사 프로필 조회 경계

사내망 조회자에게는 승인된 불변 프로필 snapshot의 구조화 항목과 `unknown`만 제공한다. 응답은 profile version·digest를 고정하고 승인 projection에 없는 항목을 현재 working tree에서 추가로 읽지 않는다.

프로필 원문 block, parser의 raw text, 원본 파일·filesystem `source`, working-tree `source_ref`, source line과 로컬 경로가 들어갈 수 있는 예외 문자열은 API에서 제공하지 않는다. 파싱 실패는 닫힌 안정 오류 코드 집합으로만 표현한다. `/api/profile/snapshots`는 `working_tree`의 내부 `source_ref`를 생략하고 `git_blob`일 때만 40자 commit SHA를 계보 식별자로 유지한다. `/api/profile/sections`와 `/api/profile/unknowns`는 승인된 snapshot의 version·digest와 구조화 projection, 위치 요약, 안정 오류 코드만 반환한다.

## 행위 권한

| 주체 | 허용 행위 | 조건 | 명시적으로 금지되는 행위 |
|---|---|---|---|
| 사내망 조회자 | 회차·공고·판정·리포트·운영 상태, 승인된 프로필 최소 projection 조회, 허용된 첨부 다운로드 | 사내망 경계 통과 | DB·MinIO 직접 접근, 내부 경로 조합, 프로필·모델응답 원문·자격증명 조회 |
| 이름을 제시한 사내 사용자 | 리뷰, 문서 묶음 확인, 심층검토 요청, 리포트 수정·최종 의견, 정책 후보·운영 스위치 요청 | 해당 API가 이름과 상태 전이 조건을 모두 검증 | 이름만으로 신원이 확인됐다고 표시, 과거 결과 수정, 품질 조건을 우회한 활성화 |
| 운영자 | 외부 secret 주입, DB migration, 정책 seed, 백업·복구, 승인된 모델 연결 | 서비스 중지·백업·명시 확인 등 각 명령의 사전 조건 충족 | 애플리케이션 시작에 관리 작업 숨기기, 운영 volume 삭제, 검증 없는 복구 성공 처리 |
| FastAPI `app` 역할 | 업무 API에 필요한 DB DML과 source/structure/quarantine 객체 접근 | 목적별 DB·MinIO 자격증명 | DDL, model-response 읽기, 임의 버킷 접근 |
| 분석 worker | 작업 claim, 구조 읽기, 암호화된 model-response 쓰기, 리포트 전이 | 고정 lease와 동시성 1 | source·quarantine 접근, 임의 네트워크, 사람 의견 변경 |
| 문서 변환 worker | 동일 해시의 원자적 scratch 요청을 구조화 | `network_mode: none`, 자격증명 없음 | DB·MinIO·인터넷 접근, 사용자 경로 신뢰, scratch 밖 쓰기 |
| 스케줄러·시스템 작업 | 예약·상태·안전한 감사 기록 | 환경 cap, DB 스위치, 유효 정책·품질 승인 | 정책 자동 활성화, 최종 참여 결정, 과거 실행 재작성 |
| 사설 vLLM | 승인된 구조화 입력 처리 | 허용된 단일 주소·모델·전송 경계 | 객체 키·경로·자격증명 수신, redirect·환경 proxy 사용 |
| 실험용 Luna·Sol | 공개 발주계획과 승인된 회사 역량 요약 처리 | 실행 전 사람이 실제 전송 내용을 확인 | 회사 프로필 원문, 실적 원문, 제안요청서·첨부, 리뷰, 모델 원응답 수신 |

## 비밀과 자격증명 수명주기

- API 키, DB 비밀번호, MinIO access/secret key, 모델 API 키, 모델응답 암호화 키는 외부 secret 관리자가 생성하고 `.env.example`의 자리표시자를 실제 값으로 대체해 주입한다. 애플리케이션이 비밀을 생성하거나 DB에 평문 보관하지 않는다.
- 실제 비밀은 Git, 이미지, API 응답, 로그, 감사 상세, URL, 프롬프트에 넣지 않는다. Pydantic secret 형식과 로그 마스킹은 노출 방지의 보조 수단이며 저장 허가가 아니다.
- 목적별 MinIO 자격증명과 PostgreSQL의 `owner`, `migrate`, `app`, `worker`, `ro_backup` 역할을 분리한다. 읽기 전용 namespace가 쓰기 자격증명으로 fallback하면 기동 또는 요청을 실패시킨다.
- PostgreSQL runtime 권한은 migration 뒤 `scripts/runtime-privileges.sql`의 table·operation allowlist로 다시 적용한다. `app`은 API·수집·orchestration 상태와 append-only 감사·사람 결정 생성만, `worker`는 attachment/deep-review lease·stage·artifact 결과와 append-only 감사·machine revision 생성만 쓴다. 사람 리뷰·최종 의견·revision·감사·불변 source/profile/policy row에는 역할별로 필요한 INSERT 또는 제한된 column UPDATE만 두고 broad UPDATE/DELETE를 주지 않는다. 새 table은 `app`·`worker` DML을 자동 상속하지 않으며 검토 뒤 allowlist에 추가한다.
- 회전은 외부 secret에서 새 값을 발급하고 대상 서비스의 환경을 교체한 뒤 컨테이너를 재생성하는 방식이다. 새 자격증명으로 health·허용 작업을 확인한 후 이전 값을 폐기한다. 애플리케이션 안에 오래된 값을 계속 허용하는 유예 목록을 두지 않는다.
- 유출 의심, 담당자 변경, 제공자 키 폐기, 암호화 키 교체가 발생하면 해당 값을 즉시 취소하고 영향을 받은 실행·객체·로그 범위를 감사한다. 고정 주기와 조직별 승인자는 외부 secret 운영 정책이 정하며 이 애플리케이션이 임의의 기간을 만들지 않는다.
- 암호화 키를 폐기하기 전에는 보존 대상 모델응답의 재암호화 또는 의도된 비가역 폐기를 운영자가 확인해야 한다. 키만 삭제해 보존 정책을 우연히 깨뜨려서는 안 된다.

## 문서·객체 안전

- 승인된 업로드는 HWP, HWPX, PDF와 50MiB 이하만 허용한다. 확장자·감지 형식 불일치, 경로 이탈, 역슬래시·`..`, 심볼릭 링크, 서버 루트 밖 경로는 거부한다.
- 사용자 파일명은 표시 metadata로만 보존하고 저장 키와 다운로드 이름은 서버가 생성한다. 응답에 내부 object key나 파일 경로를 노출하지 않는다.
- 원문은 quarantine에 먼저 저장하고 ClamAV clean 판정과 동일 SHA-256이 결합된 요청만 변환한다. scanner 오류·timeout·미확인은 clean이 아니다.
- source, structure, quarantine 원문은 일상 삭제하지 않는다. 수동 첨부 삭제가 허용되는 기존 API도 서버 생성 경로와 `origin=manual`을 모두 확인한다.
- 모델에는 근거 연결에 필요한 불변 문서·구조 식별자와 source SHA만 전달한다. object key, 로컬 경로, 자격증명, 원문 저장 위치는 전달하지 않는다.
- 모델 원응답은 application encryption을 적용해 model-response 버킷에 쓰며 별도 reasoning 필드는 보존하지 않는다. 검증된 구조 결과만 업무 API가 소비한다.

현재 Lean document-bundle upload와 legacy notice attachment upload는 모두 quarantine에 먼저 저장하고 MIME/구조·ClamAV 검사를 통과한 `safe` 바이트만 수용한다. legacy 경로는 기존 `Attachment` 스키마를 바꾸지 않는 범위에서 source object 승격·hash/size 재검증 뒤 레거시 다운로드 호환 사본도 `attachments_dir`에 저장하며, 차단·검사 불가 파일은 등록하지 않는다. `AttachmentResponse.stored_path`는 wire에서 제거했고, 컨테이너의 호환 사본은 named volume으로 보존한다. legacy object metadata schema 이전은 별도 범위다.

## 외부 모델 전송

운영 경로는 OpenAI hosted API로 자동 전환하지 않는다. Ollama 또는 사설 vLLM 실패는 사람 검토 상태로 끝나며 실패 자체가 외부 전송 동의가 아니다.

발주계획 선별 실험에서 Luna·Sol을 사용할 때는 공개 발주계획 필드와 사람이 승인한 회사 역량 요약만 전송한다. 실행마다 모델·목적·전송 필드·건수·승인자·시각을 미리 보여 주고 승인 뒤 호출한다. 승인되지 않은 추가 필드가 있거나 회사 프로필 원문·제안요청서·첨부·리뷰가 포함되면 전체 실행을 중단한다.

향후 선택형 외부 재분석을 도입하더라도 자동 fallback으로 구현하지 않는다. 조직의 보존 지역·학습 사용·삭제·계약 정책을 먼저 확정하고 공고별 전송 미리보기와 건별 승인을 거쳐야 한다.

## 네트워크와 HTTP

- PostgreSQL, MinIO, ClamAV, scratch worker 네트워크는 Compose 내부망으로 분리한다. 문서 worker는 네트워크를 갖지 않는다.
- 원격 vLLM은 승인 환경의 별도 egress network와 host firewall에서 literal IP·port 하나만 허용한다. base URL은 허용 host와 정확한 `/v1` path를 통과해야 한다.
- 모델 SDK는 환경 proxy, redirect, 자동 재시도를 사용하지 않는다. 모델 호출 재시도는 애플리케이션의 제한된 시도 규칙으로만 수행한다.
- FastAPI는 CSP, `X-Content-Type-Options: nosniff`, no-referrer를 설정하고 `/api` 응답과 다운로드에 no-store를 적용한다. API route가 SPA fallback보다 먼저 평가되어야 한다.
- 다운로드는 서버 생성 filename과 안전한 media type을 사용한다. 첨부 응답은 `default-src 'none'`, nosniff, no-store를 유지한다.

## 로그와 감사

로그에는 event, 상태, 내부 식별자, 단계, 안전한 오류 코드, 소요시간·크기·해시처럼 허용된 metadata만 남긴다. 프롬프트, 모델응답, 회사자료, 담당자 이름, DB URL, query string, 사용자 파일 경로, 비밀번호·토큰은 DEBUG에서도 기록하지 않는다. 예외 traceback은 기본 비활성이며 활성화해도 같은 마스킹과 허용 필드 제한을 거친다.

다음 사건은 구체적인 감사 대상으로 남긴다.

- 문서 업로드·검사·격리·묶음 확인과 버전 변경
- 심층검토 생성·재시도·중지·완료·검증 실패
- 리포트 수정과 최종 의견, 검증 실패 인지 여부
- 리뷰 생성·수정과 내보내기
- 정책 생성·후보 지정·활성화, 품질 게이트 생성·평가·사람 리뷰
- 스케줄 설정·예약·중복 건너뜀·복구·상시 실행 스위치
- DB migration·seed·backup·restore·active hash 검증
- 외부 모델 실험 또는 선택형 재분석의 전송 미리보기·승인·호출 결과
- 자격증명 회전·취소와 의심 노출 조사

감사에는 원문·비밀·프롬프트를 넣지 않고 대상 식별자, 행위, 결과, 안전한 실패 분류, actor kind와 claimed name을 기록한다. 감사 기록이 있다는 이유로 claimed name을 인증된 신원으로 표현하지 않는다.

## 백업과 복구

목표는 RPO 4시간, RTO 8시간이다. PostgreSQL은 daily full과 continuous WAL, 객체 저장소는 4시간 이내 version-aware copy를 사용한다. 보존은 daily 14, weekly 8, monthly 6이다.

복구 순서는 versioned object 복원, 빈 pre-production PostgreSQL 복원, DB가 가리키는 active object hash 검증이다. 실제 운영 volume을 지우거나 `docker compose down -v`로 복구하지 않는다. 해시 검증이 실패하거나 제공된 snapshot이 없으면 복구 성공으로 기록하지 않는다.
