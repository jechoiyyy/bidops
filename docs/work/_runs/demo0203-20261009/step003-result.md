# STEP-003 초안 검증 (승인 대기)

- ontology v1과 세 회사 원본, 사람이 읽는 README 초안 작성. 실제 후보 공고·회사자료를 읽지 않은 standard 프로필 작성자.
- `step003-dry-run.log`: 세 새 CLI 프로세스 모두 exit0, errors=[], created=false, activated=false. 원본 source_sha256과 반환값 일치.
- 리더 wrapper는 임시 디렉터리에 아무 항목도 없어야 한다는 과도한 보조 조건 때문에 exit1이었다. 남은 항목은 빈 `data` 디렉터리 하나이며, 기존 core/db.py:35의 import-time mkdir다. DB 파일·첨부 디렉터리·객체 파일은 생기지 않았다. 실제 CLI 실패가 아니므로 제품이나 검사 기대값을 고치지 않았고 중복 실행하지 않았다.
- `step003-approval-request.json`에 승인 대기 원본 파일 hash·ontology canonical hash·항목 수를 기록했다. 세 회사 모두 50명, unknown은 null/근거0으로 보존.
- `.dockerignore`에서 fixture 폴더 제외. 로컬 .git/info/exclude도 fixture를 무시하므로 이후 승인된 파일만 명시적으로 Git에 추가해야 한다.
- 미등록·미동결·사용자 승인 대기. STEP 완료나 기능 완료 proof가 아니다.

## 승인 후 상태

2026-10-09 사용자의 “현재 초안 승인”에 따라 요청 manifest와4개 원본 hash를 대조해 모두 일치 확인. `docs/validation-runs/2026-10-09-company-demo/DEMO-02-company-knowledge/fixture-approval.md`에 승인자·기록시각·hash 보존. 원본 JSON 변경 없이 동결하고 STEP-003 완료. 실제 DB 등록·서버 적용·모델 호출 없음.

## 재발행·재승인 (2026-10-09, 기능 최종 리뷰 B2)

- 최초 승인본은 인력군·실적 value의 nullable key를 생략해 공통 계약 §3과 어긋났다. 사용자 결정 “원본에 null 명시”에 따라 회사마다 null key 13개만 추가해 재발행했다(사실·인용·수치·노드 순서·JSON pointer·ontology 불변, 독립 리뷰어 diff 확인).
- 엄격 validator dry-run 3개 exit0/errors=[] (`step003-reissue-dry-run.log`), 이전 승인본 바이트는 `source_invalid`(exit2). 재승인 요청 hash는 `step003-reapproval-request.json`.
- 사용자 재승인(2026-10-09T19:06:02+09:00)을 승인 기록의 재승인 절에 남겼다. 실제 DB 등록은 하지 않았다.
