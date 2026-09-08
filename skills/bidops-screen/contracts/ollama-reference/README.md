# Ollama 참조 적재 검증 프로필

기존 Phase 0 catalog의 9개 파일과 고정 SHA-256은 변경하지 않는다.
이 디렉터리는 같은 C-2 파일/DB envelope를 사용하는 **별도 참조 적재 프로필**이다.
기존 vLLM 품질 검증을 통과했다는 뜻이 아니며 Phase 0 활성화 도구의 입력이 아니다.

- `approved_private_ollama` / `qwen3.8:27b`만 허용한다.
- 정책은 `activation_candidate`, 품질은 `not_measured`, 활성화는 차단 상태다.
- 모델 digest·생성 설정·승인 프롬프트·회사 역량 해시를 별도로 결속한다.
- plan payload는 제목, 회사 payload는 `profile_version`과 `capabilities`다.
- 데이터 디렉터리의 `validation-profiles.json`이 적용한 프로필과 해시를 명시한다.
- 원 실행 manifest와 응답은 보존하고, 사후 포장 정보는 `reference-provenance.json`에
  기록한다. 과거 선택 실험의 evidence는 Ollama 품질 근거로 사용하지 않는다.

소비자는 `app/screening/c2_contracts.py`와 `app/screening/ingest.py`다.
운영 `create_execution`의 active/passed 게이트와 vLLM transport는 유지한다.
