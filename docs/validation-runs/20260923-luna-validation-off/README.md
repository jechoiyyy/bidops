# Luna 검증 off 참조 실행 — 2026-09-23

사용자 “검증 레이어를 off 하고 진행해보자” 요청. 범위 선택 질문에 추가 답변이 없어
안내한 기본안(내용·참조 의미·누락 검증 off, 형식·승인·저장 무결성 유지)으로 구현했다.

- 새 불변 policy: analysis-policy-luna-v3.json.
- sha256: e522978f43abba93f81c1b0195c08bfce0d6a9a337203dcf26dcb10d4623fc14.
- result_checks=disabled_reference_v1. 원문·숫자 검증도 off. UI/validation warning에 검증 미실시 표시.
- 기존 v1/v2 정책·실행·원응답은 보존. migration 없음.
- 저장된 v2 실패 응답 replay: claims 30/evidence 23, 형식·저장 무결성 검사 통과. 실제 호출 아님.
- postgres:17.11 일회용 DB, BIDOPS_TEST_POSTGRES_URL 지정, BIDOPS_PRESPEC_OVERVIEW_ENABLED=false:
  `pytest tests/app/test_luna_deep_review.py tests/app/test_narrative_review.py -q`: 59 passed, skip 0.
  가짜 응답의 considered/coverage/숫자/인용 불일치 허용, hash/근거 FK 오류 차단 검사 포함.
- TypeScript strict+production build 통과. 두 화면 크기 포함 Luna/보고서 Playwright 13 passed.
  DB 생성 fixture의 미리보기·보고서에 검증 미실시 표시, 가로 넘침 0. 캡처 직접 확인.
- web·analysis-worker 이미지 빌드 완료. 원문·키·회사자료를 이미지에 추가하지 않음.
- DB 백업 43,538,443 bytes, SHA-256 62ef8c40018676ea820f3621be5f15f707e4afdb1c01a20d5b78c884b87a3017.
  pg_restore --list 통과. 실제 restore는 수행하지 않음.
- 운영 배포·v3 정책 등록/활성화·새 모델 호출은 아직 수행하지 않음.

- 객체 1366 versions 백업과 host 복사 후 전체 hash 대조 완료. 롤백 태그 `before-luna-validation-off-20260923`.

## 코드 운영 재배포

사용자 “승인할게” 확인 후 실행 중 작업 0건과 후보/소스 hash 일치 확인.
수집 공용 flock 안에서 web·analysis-worker를 준비한 이미지로 재생성했다.
health 정상, 두 서비스 running, head 0032 유지, 기존 v2 실패 review GET 정상/failed 보존.
심층 자동 시작 false·개요 true·Luna true 유지. 현재 활성 정책은 v2다.
v3 정책 등록/활성화와 새 모델 호출은 아직 수행하지 않았다.
이미지와 시각: [배포 기록](deployment.json).

## v3 정책 활성화

사용자 승인 후 import-profile-policy CLI로 v3 `8db9e566-9fd1-4589-a9c0-d96365231221` 등록.
기존 회사 프로필 사용, env/luna.env active ID 반영·두 서비스 재생성 후 실제 값과 health 확인.
심층 자동 시작 false, 개요 true 유지. DB SQL 변경 없음.
1489의 새 미리보기 준비 완료(문서 1개·기존 승인 프로필·검증 off). 실제 전송·호출은 아직 하지 않았다.

## 1489 검증 off 실제 요청

사용자 “실행해줘” 직전 승인 후 준비된 preview로 제품 REST 생성 요청, 202 확인.
새 검토 `aec000e4-782a-46ba-acc3-5aa1b9067bde`, attempt `eb3bf273-4e04-4f28-b245-b7a5ebbf9a8d`.
실제 source_verification_enabled=false, codex-exec/gpt-5.6-luna/xhigh, unmeasured_reference 확인.
두 화면 크기에서 실제 진행 화면과 가로 넘침 0 확인. 최종 완료 결과는 아직 없다.
별도 읽기 전용 감시 프로세스가 종료 상태·코드를 저장한다. 현재 기록은 요청·시작 증거다.

### 실제 실행 종결 및 지연 확인

11:16:46 KST 시작 → 12:10:27 실패(53분 41초). 원문 19조각 중 10회 응답 수신.
첫 9조각은 저장 무결성 검사 통과, 10번째에서 claim 한 개의 evidence_ids에 응답에 없는
ID 1개가 있어 `validation:dangling_evidence`로 차단. 회사 대조/종합 미호출, 완성 보고서 없음.
검증 off는 내용·의미·누락 검사에만 적용됐고 근거 FK에 필요한 존재 검사는 유지됐다.
순차 Luna/xhigh 10회 호출 구조이며 전체 경과 기준 호출당 평균 약 5분 22초다.
실패 raw aggregate에는 slice_index/raw_response/hash만 남아 개별 latency는 복원할 수 없다.
복호화 원응답 hash 대조 후 건수/오류만 확인했고 원문 본문은 실행 기록에 남기지 않았다.
후속 호출이나 자동 재시도는 하지 않았다.
