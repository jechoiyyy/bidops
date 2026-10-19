# C-2 발주계획 선별을 Mac의 LiteLLM·Ollama로 옮긴다

- 상태: 채택
- 일자: 2026-10-14
- 결정자: jechoi (일괄 승인: 계획 전체·프롬프트 v5·평가 제출·활성화·일일 스위치 대행·따라잡기 범위)

## 맥락

2026-10-14 WSL2 운영 호스트가 종료되고 운영을 Mac(42-ax, Apple M4 Max)으로 옮겼다.
v4 C-2 묶음([ADR-0037](0037-order-plan-c2-bm25-top300-qwen.md)·
[ADR-0044](0044-c2-stage2-matches-the-measured-method.md))은 다음 셋을 해시로 고정했는데
셋 다 Mac에 없다.

- 승인 사설 vLLM `http://192.168.0.139:58765/v1`(eth1, digest `5fa804ff…`) — Mac에서 닿지 않는다.
- 승인 프롬프트 `order-plan-batch-relevance-v3`(`639f…`) — 회사자료라 gitignore였고 본문이
  WSL2와 함께 사라졌다. 저장소에도 백업에도 없다.
- 운영 DB·MinIO(활성 v4 행·게이트 통과 기록·9-28까지 이력) — 이전한 백업이 없다.

Mac에는 LiteLLM 별칭 `local-agent-main`이 로컬 Ollama `qwen3.8:27b-ctx32k`
(Q4_K_M, 27.3B, manifest digest `41a558fc…`, 입력 32k)로 연결돼 있다. 계약에는 이미
`(approved_private_ollama, qwen3.8:27b)` 조합이 BM25 단계와 적재기에 있었다.

## 결정

1. C-2 v5 묶음을 새로 발행한다. v4 이하 파일은 고치지 않는다.
   - 프롬프트 `order-plan-batch-relevance-v5`(`461f9664…`): 사업명·회사 역량만 근거로 하는
     3분류 지시. 본문은 계속 gitignore이며 manifest에는 digest만 둔다. v3은 manifest에서
     `retired`로 내렸다.
   - generation config v6(`litellm-ollama-qwen-order-plan-batch-nonthinking-v6`):
     `api_dialect=litellm`, `request_model=local-agent-main`, `reasoning_effort=none`,
     `max_output_tokens=8192`, `timeout_seconds=600`, `allowed_hosts=[42-ax.tail0ab8c5.ts.net]`.
   - policy `c2-order-plan-screening-v5`·binding v5: provider `approved_private_ollama`,
     model `qwen3.8:27b`, digest `41a558fc…`. BM25 top 300·회사 역량 v1·감사 표본·게이트
     임계값(recall ≥ 90%, precision ≥ 35%, 중요 누락 ≤ 3, 하루 검토량 ≤ 80)은 v4와 같다.
     파일의 `policy_status`는 발행 스냅숏 `activation_candidate`이고 활성 정본은 DB 행이다
     ([ADR-0060](0060-c2-policy-db-row-authority.md)).
2. C-2 adapter는 generation config의 `api_dialect`로 전송 방식을 고른다.
   - `vllm`(기본): 지금까지와 같다 — literal IP 허용 목록, `chat_template_kwargs`.
   - `litellm`: 정확한 소문자 hostname 허용 목록 + https + 명시 포트 + `/v1`. 요청 모델은
     LiteLLM 별칭이고 응답 `model`도 그 별칭이어야 한다. Ollama upstream은
     `chat_template_kwargs.enable_thinking`을 무시하므로 `reasoning_effort=none`만 보낸다
     (DEMO-05 개요 실측과 2026-10-14 합성 2건 호출에서 thinking 없이 `stop` 확인).
   - 어느 쪽이든 배포 선언 revision(`BIDOPS_VLLM_MODEL_REVISION`) = binding digest를
     호출 전에 대조한다([ADR-0042](0042-c2-model-revision-declared-at-deployment.md)).
     Ollama는 digest를 노출하므로 `scripts/c2-mac-model-preflight.sh`가 `/api/tags` digest,
     LiteLLM `/model/info`의 별칭 경로(`openai/qwen3.8:27b-ctx32k` → `127.0.0.1:11434`),
     컨테이너의 TLS 도달을 completion 없이 확인한다.
3. worker는 stage2 `(provider, model)`이 승인 두 쌍 중 하나이고 policy와 binding의
   provider가 같을 때만 실행한다.
4. Mac 배포는 `docker-compose.mac.yml` overlay와 `scripts/mac-compose.sh`로 한다. 프로젝트
   `bidops`, web `127.0.0.1:18788`(tailnet `:8188`), 애플리케이션 이미지는 vendored rhwp
   때문에 linux/amd64다. 데모 `bidops-local`(`:18787`)과 volume·network를 공유하지 않는다.
5. v5는 v4의 게이트 통과를 승계하지 않는다. 같은 gold adjudicated v3와 같은 게시일별
   4회차로 제품 경로 측정 2회를 다시 하고 통과해야 활성화한다.

## 결과

- 모델 호출이 Mac 밖으로 나가지 않는다(LiteLLM·Ollama 모두 로컬). tailnet 이름은 TLS
  검증용이며 트래픽은 같은 호스트로 돌아온다.
- Q4 양자화 Ollama 빌드는 v4가 측정한 vLLM 원본과 다른 weight다. v4의 precision 여유
  (36.7%)가 그대로라는 근거는 없고 v5 게이트 결과만 근거로 쓴다.
- `BM25` 스크립트의 Ollama 가드는 발행 스냅숏(`activation_candidate`·`not_measured`·
  `blocked`)만 본다. 활성 여부는 DB 행이 정하므로 v5가 활성화돼도 가드는 그대로 통과한다.
  "Ollama 결과는 참조용"이라는 이전 운영 관례는 이 결정으로 v5 binding에 한해 대체된다.
- 승인 입력 본문이 한 호스트에만 있다가 사라진 일이 반복되지 않게, 프롬프트·회사 역량
  승인본은 Mac 운영 checkout의 `review-inputs/`와 운영 실행 디렉터리(pipeline-data volume)에
  남고, 백업 절차에 포함한다([findings](../findings.md)).

## 대안

- **승인 vLLM 서버를 Mac에서 닿게 열기**: 서버가 WSL2 망과 함께 사라졌고 v3 프롬프트도
  없어 v4를 그대로 쓸 수 없다.
- **codex(Luna)**: 하루 약 500건 × 25건 묶음 호출을 외부로 보내는 새 transport와 전송 승인이
  필요하다. 사용자가 LiteLLM을 선택했다.
- **Ollama를 직접 호출**: LiteLLM 별칭을 거치면 다른 서비스와 같은 모델 운영 지점을 쓴다.
  사용자가 `local-agent-main`을 지정했다.

## 추가 결정: 사전규격을 개요 검토까지 같은 LiteLLM으로 돌린다 (2026-10-15)

- 사용자가 사전규격 트랙을 **개요 검토까지만** 돌리기로 했다. 심층 자동 시작·회사 핏은 끄고
  active profile/policy ID를 비워 둔다. C-1 판정은 돌리지 않으며 개요 플래그의
  `SW사업대상=Y` 자격으로 첨부 취득·묶음·개요가 열린다.
- 개요는 C-2와 같은 LiteLLM `local-agent-main`(digest `41a558fc…`)을 overview 용도 설정으로
  부른다. 데모 브랜치(DEMO-05)에서 만든 `litellm` 전용 실행 프로필(호출 900초·출력 예약 8192,
  `reasoning_effort=none`)과 정책 `prespec-overview-policy-v7-litellm-v2.json`(`0e69ae43…`)을 같은
  바이트로 운영 브랜치에 옮겼다. 표준 프로필(300초/16384)과 v7·v8·litellm-v1 파일은 그대로다.
- 결과에는 `quality_status=unmeasured_reference`가 붙는다. 개요 품질을 측정한 근거는 없다.
- 애플리케이션 이미지는 amd64(Rosetta)로 두되 문서 worker만 native arm64로 돌린다. 자식
  `RLIMIT_DATA` 512MiB가 Rosetta와 충돌하기 때문이며 제품 한도는 바꾸지 않는다.
- Mac에는 host 방화벽 egress 제한이 없다. 첨부 host 제한은 앱의 허용 목록(`www.g2b.go.kr`)만
  건다. 운영 절차가 전제한 이중 경계 중 하나가 빠진 상태다.
