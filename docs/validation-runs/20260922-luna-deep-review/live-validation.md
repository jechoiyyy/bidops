# Luna 운영 적용·실제 연결 확인 — 2026-09-23

사용자의 운영 배포·커밋 및 현재 로그인된 Codex 계정 사용 요청에 따라 진행했다.
공고 선택·전송 확인은 별도로 받고 있으며 이 기록 시점에는 실자료 심층검토를 시작하지 않았다.

## 적용과 백업

- migration 0031 → `0032_luna_deep_review`, 신규 불변 preview/approval 표와 권한 적용.
- web·analysis-worker·prespec-attachment-worker 교체, 독립 codex-runner 배포.
- Luna 정책 `7948d520-b7b0-432b-8ca3-8cee70cea194`, 기존 승인 profile
  `d970500a-e30c-46cf-85e0-7e9a9e854f2b` 사용. 정책 원본/hash는 변경하지 않았다.
- Luna 요청 true·참조 모드 true·심층 자동 시작 false·공용 슬롯 1.
  개요 true·C-2 일일 실행 true 유지. 기존 queued/running 0건 확인.
- 운영 수집 공용 flock을 잡고 교체 후 해제했다. cron 내용은 변경하지 않았다.
- DB 전체 dump 26,583,454 bytes, pg_restore --list 통과. 객체 1,102 versions를
  원본/복사본 대조하고 host 복사 후 다시 SHA-256으로 확인했다.
- 롤백 태그 `before-luna-deep-review-20260923`, 기존 서비스별 이미지·환경 파일을 보존했다.
  [배포 식별자·백업 해시](deployment.json). 외부 보존 위치 복사·복원 시험은 이번에 하지 않았다.
- auth.json만 저장소 밖의 접근 제한 디렉터리에 분리했다. 인증 내용·프롬프트·회사자료는
  이 기록에 포함하지 않는다. env/luna.env는 gitignore다.

## 실제 모델 연결

공고·회사자료가 없는 짧은 schema 응답 요청으로 현재 계정의 Luna/xhigh 접근을 확인했다.
수정 후 CLI 0.155.1, 7,850ms, completed. 이는 실제 모델 연결 확인이고 내용 품질 검증은 아니다.

처음에는 CLI용 schema의 자유형 locator가 strict output에 거부됐다. 실행기가 echo된
입력의 authentication 단어까지 오류로 분류한 결함도 있었다. locator를 권위 schema의
다섯 형태로 제한하고 --json으로 입력 echo를 제거했으며 구체적 서비스 오류로만 분류한다.
권위 schema·근거 검증은 그대로다. 자동 fallback이나 제품 자동 retry를 추가하지 않았다.

배포 전 런타임 head 상수 누락도 수정했다. 별도 PostgreSQL 17.11에서 빈 migration과
실제 기동 검사, 단일 head 검사 2 passed. runner 회귀 10 passed 후 새 구조 검사에 없는
라이브러리를 가져온 테스트 오류를 제거하고 해당 1 passed. 운영 이미지 빌드 통과.

## 미완료 인수

1430번은 기존 문서 준비 이력은 있지만 개요 완료가 없어 409 review_not_ready로 거부됐다.
조건을 우회하지 않았다. 개요 완료+확정 묶음 공고를 다시 제시하고 실제 건별 전송 확인을
기다리고 있다. 아직 공고 보고서 생성·근거·실제 두 건 순차 실행·개요 처리 재개를 증명하지 않는다.
runner는 전용 egress network를 사용한다. 도메인별 host firewall allowlist는 적용·검증하지 않았다.

운영 UI 1280×800·1440×900에서 문서 준비 열기→Luna 미리보기 버튼과 가로 넘침 0을 확인했다. 첫 검사에는 토글 로딩 전에 존재 여부를 검사한 대기 조건 오류가 있어, 토글을 기다린 뒤 클릭하도록 고쳤다. 자동 시작 안내 문구 두 곳도 수정해 운영 웹을 갱신했다. 실제 승인 제출·보고서 화면 증거는 아니다.
