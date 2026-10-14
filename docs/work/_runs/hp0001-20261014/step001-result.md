# HP-00 STEP-001

- 구현자 gpt-6-luna / max, hp00_step001. identity 모듈·runner·client·가짜 runner 변경.
- 리더 검사: tests/deep_review/test_codex_runner.py 15 passed in 1.94s. 로그 step001-tests.log. codex CLI 0.162.1, exec --strict-config --help도 정상. 실제 모델 호출 없음.
- 회사 e2e/binding은 STEP-002/003 정책 전환 후 T9에서 통합 검증.
- 검증 환경: macOS Python 3.12.15 /tmp/bidops-hp0001-20261014-venv. Linux amd64 lock hash는 macOS wheel과 달라 저장소 lock을 유지한 채 동일 51개 버전의 macOS 패키지를 별도 환경에 설치. 운영 이미지 변경 없음.
- 일회용 PostgreSQL 17.11 bidops-hp0001-test-pg, localhost:32844. 운영 DB 사용 없음.
