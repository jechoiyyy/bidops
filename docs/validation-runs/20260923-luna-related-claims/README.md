# Luna 보조 연결 경고 — 2026-09-23

- 변경: 새 Luna v2 정책에서 범위 밖 related_claim_ids만 제외하고 경고. 원본 응답과 기존 정책 보존.
- 저장된 1489 응답의 후보 코드 재검증: 첫 조각 통과, 제외 1건. 원응답 유지, 모델 호출 없음. 전체 보고서 성공 증거는 아니다.
- 일회용 postgres:17.11, BIDOPS_TEST_POSTGRES_URL 지정, BIDOPS_PRESPEC_OVERVIEW_ENABLED=false.
  `pytest tests/app/test_luna_deep_review.py tests/app/test_narrative_review.py -q`: 55 passed, skip 0.
- 후속 수정본 경고 보존 assertion 추가 뒤 `pytest .../test_luna_deep_review.py -q -k optional_relation`: 3 passed, 16 deselected.
- 가짜 실행기 기반: 승인→실행→경고→보고서 저장, 구 정책 실패, 필수 전제/근거/인용/coverage/종합 차단. 실제 모델 정확성 증거가 아니다.
- `build web analysis-worker` 성공. 새 migration 없음(head 0032 유지).
- 화면·운영 적용·실제 재실행: 진행 중.

- 화면: DB 생성 합성 fixture로 1280×800·1440×900, 경고/본문/근거 버튼/참조 표식/넘침 0 확인, 2 passed.
  최초 실행은 테스트 JSON import attribute 누락으로 실패; 테스트만 수정해 재실행. 제품 재빌드 반복 없음.
- 백업: DB 43,365,918 bytes, sha256 c63542744ddfd505c7309956a1e586962c03adcf9b215ce3bffd21d81702988b, pg_restore --list 통과.
  객체 1,363 versions 원본/복사본 hash 대조. 최소 컨테이너에 awk가 없어 첫 백업 중단 후 셸 read로 해시 첫 필드만 추출하는 임시 스크립트로 새 경로에 완료.
- 정책 SHA-256: d9477dba24459f6154607539ba423aa503cac1104aa375a42c9fba9fe0449ac1.

- 객체 host 복사 후 1,363개 hash 재확인 완료. 롤백 태그 `before-luna-relations-20260923`.
  기존 이미지/환경은 저장소 밖 접근 제한 디렉터리 `~/.local/state/bidops/luna-relations-20260923/`에 보존.
- 두 폭 캡처를 직접 확인했다. 후속 사용자 승인으로 아래 코드 재배포를 수행했다.

## 운영 코드 재배포

사용자 “운영 재배포 진행해” 승인 후 web·analysis-worker를 준비한 이미지로 교체했다.
교체 전 후보 이미지와 검사한 네 서비스 소스의 hash 일치, 전체 work_job 활성 0건 확인.
수집 공용 flock 안에서 `up -d --no-deps --no-build --force-recreate web analysis-worker` 실행 성공.
health 정상, 두 컨테이너 running, 1489 상세 200, 기존 실패 review GET 200/failed 보존.
head 0032 유지, 심층 자동 시작 false·개요 true·Luna true·참조 모드 true 유지.
현재 활성 정책은 v1. v2 정책 등록/활성 설정/모델 호출은 아직 수행하지 않았다.
이미지·시각은 [배포 기록](deployment.json).

## v2 정책 활성화와 실제 실행

사용자가 v2 등록/활성화 및 1489 즉시 실행을 요청했다. import CLI로 v2 정책
`c0f37202-3a19-447f-a13c-3b5b8a83133a`를 등록하고 기존 회사 프로필을 재사용했다.
env/luna.env active policy 변경 후 web·analysis-worker 재생성, 두 서비스의 v2 ID와 health 확인.
심층 자동 시작 false 유지. 운영 DB를 SQL로 수정하지 않았다.
실제 상세에서 새 미리보기·전송 승인을 제출해 202 queued 확인. 원문 대조 on·Luna/xhigh.
기존 v1 실패 검토를 덮지 않고 새 검토 생성. ID/hash는 [실행 기록](live-1489-run.json).
요청 후 캡처는 중복 제목 선택자로 실패했으나 승인 제출은 성공; 재제출 없이 조회만 수행했다.
최종 결과는 아래와 같이 실패이며 성공 보고서나 의미 품질을 증명하지 않는다.

### v2 실제 실행 종결

- 시작 2026-09-23 10:14:06 KST, 종료 10:20:21 KST(약 6분 15초).
- 첫 조각 Luna 응답: claims 30, evidence 23. 원응답 암호화 보존·복호화 hash 대조 완료.
- 입력 verified_claims 0개인데 considered_claim_ids에 이번 응답의 로컬 claim ID 30개를 반환.
  `narrative:considered_claim_out_of_slice`로 첫 단계 실패.
- v2 보조 연결 제외 0건. 이번 응답에는 앞선 related_claim_ids 오류가 없었다.
  후속 필수 검증을 완화하지 않았으며 회사 대조·종합은 호출하지 않았다.
- report API 409, 완성 보고서 없음. 실제 UI 두 폭에서 실패 상태·가로 넘침 0 확인.
- 자동 재호출/정책 재수정/fallback 없음. v2 정책 활성 상태 유지.
- 최초 캡처의 region role 지정 오류는 label로 수정해 조회만 재실행했다. 승인 요청은 1회다.

후속은 considered_claim_ids가 출력 내 자체 주장 목록이 아니라 입력 verified_claims의
검토 목록임을 프롬프트에 명시하는 별도 변경이다. 이번 범위에서 자동으로 비우거나 새 모델 호출을 하지 않았다.
