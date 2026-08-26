# 미해결 문제

기준일: 2026-08-27

## T7 실제 격리 Mock E2E는 통과했지만 Qwen 품질 증적은 아님

- 2026-08-27 새 격리 Compose project에서 PostgreSQL, MinIO, ClamAV, document worker 2개,
  analysis worker, web을 사용해 Agent 연속 E2E를 실행했다.
- provider/model은 `mock-analysis` / `bidops-deterministic-mock-v1`이고 결과는
  `bidops.t7-e2e-result.v1`, `passed=true`였다. 외부 OpenAI/Codex/Qwen 호출은 0건이며 종료
  queued/running WorkJob도 0건이었다.
- 종료 후 격리 container, network, volume을 정리했다. 상세 두 날짜 증적과 ID는
  [`docs/mock-workflow-e2e-result.md`](../mock-workflow-e2e-result.md)에 보존한다.
- `mock_quality.evaluated=false`이므로 이 결과를 Qwen 품질 gate, 실제 사업 판단, 배포 승인으로
  재사용할 수 없다.

## 원격 vLLM 연결은 확인됐지만 배포 artifact가 immutable하게 고정되지 않음

- 확인됨: private literal-IP의 OpenAI-compatible `/v1`, served ID `qwen3.8-27B`, `/v1/models`와 실제 Chat Completions SDK 호출이 성공했다.
- 실제 스모크: thinking+단순 JSON은 84.36초가 걸렸고, thinking+권위 structured output은 120초 timeout 및 재시험에서 schema 불일치가 확인됐다. 같은 schema를 non-thinking으로 실행하면 빈 stage는 5.94초에 identity/validator를 통과했다.
- 실제 요구사항 1건: non-thinking candidate가 25.29초, prompt 531/completion 853 tokens에 supported claim 2개와 유효 evidence 1개를 만들고 권위 validator를 통과했다. 이 결과로 non-thinking·temperature 0.7·top_p 0.8·top_k 20·seed 0을 candidate policy에 고정했다.
- 남은 값: 서버 Compose의 `vllm/vllm-openai:latest`를 image digest로 바꾸고 `Qwen/Qwen3.8-27B`의 immutable Hugging Face revision 또는 로컬 artifact digest를 제공해야 한다.
- 현재 경계: plain HTTP private endpoint, optional API key, redirect/proxy 없음만 지원한다. IP는 `BIDOPS_VLLM_ALLOWED_HOSTS`와 정확히 일치해야 한다. analysis worker의 `model-egress`도 host firewall에서 해당 IP/port 하나로 제한해야 한다.

## runtime model artifact digest를 worker가 직접 대조하지 않음

- 증상: policy와 client는 `qwen3.8-27B` 이름을 고정하고 응답 model ID를 대조하지만, `/v1/models` 응답 자체에는 model weight digest가 없다.
- 영향: 같은 tag가 다른 bytes를 가리키면 사전·사후 운영 대조를 누락했을 때 승인 모델과 실행 모델이 달라질 수 있다.
- 현재 통제: 인수 절차에서 서버 운영자가 제공한 image/model digest를 quality manifest와 사람이 대조한다.
- 후속 선택: startup preflight가 신뢰할 수 있는 배포 manifest 또는 model gateway의 digest를 강제하도록 서버 계약을 확장한다.

## 실제 품질 corpus와 사람 gold가 저장소에 없음

- `fire_prevention_55.json`은 기대 ID만 포함하며 해당 55개 요구사항 원문은 없다.
- `labor_template.hwp`, `safe.pdf`는 문서 변환·안전성 fixture이지 모델 품질 corpus가 아니다.
- 실제 대표 HWP/PDF, source SHA, 모델 출력, gold item mapping, claim별 사람 판정이 있어야 0.80/0.70/0.10 gate를 측정할 수 있다.
- scorer는 준비됐지만 Qwen 호출이나 사람 adjudication을 대신하지 않는다.

## 실제 Qwen B→C 서비스 인수와 품질 승인은 아직 없음

- 위 T7 결과는 Mock 경로의 실제 서비스 E2E이며, remote vLLM/Qwen을 사용한 `bc-result.json`은 아직 없다.
- 실제 대표 HWP/PDF, immutable model/image digest, 55개 gold mapping과 사람 판정이 없어
  `0.80/0.70/0.10` quality gate를 측정할 수 없다.
- 실제 timeout·잘린 JSON·provider 실패의 재시도는 unit test로 검증됐지만 승인 endpoint에서의 fault-injection 증적은 없다.

## SQLite 이관·복구 훈련용 외부 입력이 없음

- 운영 DB를 건드리지 않는 SQLite 백업 복사본과 빈 pre-prod PostgreSQL target이 필요하다.
- 13개 table row/PK/FK, 리뷰·첨부 metadata, sequence, 실패 후 재실행, cutover 이후 SQLite write 차단의 실제 기록이 아직 없다.
- object backup과 PostgreSQL dump도 제공되지 않아 object→DB→active hash 복구와 RPO 4시간/RTO 8시간 달성을 주장할 수 없다.

## 운영 secret·권한·방화벽 검증이 없음

- `.env.example`은 placeholder뿐이며 실제 secret manager 주입 결과가 없다.
- 목적별 MinIO credential 정책은 코드·bootstrap에 있지만 실제 bucket 권한의 allow/deny matrix를 실행하지 않았다.
- remote model egress firewall, container artifact UID/GID, backup 책임자·보관 위치가 실제 환경에서 확인되지 않았다.

## frontend 시각 기준선이 font 환경에 민감함

- 기능 테스트와 build는 통과 상태지만 28개 image snapshot이 한글 font 차이로 흔들린다.
- Playwright image와 font를 고정한 뒤 같은 환경에서 재생성하고 사람이 변경 이미지를 승인해야 한다.

## 단계 B 준비와 retry 제어 UI가 완결되지 않음

- 현재 UI는 ready bundle을 선택해 review를 시작하고 report/revision/final opinion을 볼 수 있다.
- document bundle 준비 전체 과정, 진행 polling, 실패 attempt 재시작은 운영자용 API/CLI가 담당하며 화면에서 완전히 이어지지 않는다.
- E2E API 인수에는 차단 요인이 아니지만 Lean v1 운영 UX 범위로 별도 결정이 필요하다.

## 사전규격 API 운영 권한이 확인되지 않음

- 운영 계정 승인이 없으면 입찰공고 전 단계의 사전규격을 안정적으로 수집할 수 없다.
- 저장소 밖의 공공데이터포털 이용 승인 후 제한 기간 수집으로 field와 quota를 검증해야 한다.
