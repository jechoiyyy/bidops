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

- 재현 조건과 증상: 운영 수집에서 사전규격 API를 호출하려 할 때 이용 승인이 없으면 입찰공고 전 단계의 사업을 안정적으로 가져올 수 없다.
- 영향: 조기 탐지 범위가 입찰공고 중심으로 좁아지고 준비 시간이 짧아진다.
- 지금 해결할 수 없는 이유: 공공데이터포털 계정의 이용 신청·승인은 저장소 밖의 행정 작업이다.
- 접근 방법: 운영 계정에서 해당 API 활용 신청 상태를 확인하고 승인 후 제한된 기간 수집으로 필드·쿼터를 검증한다.

## 이름 입력은 신원을 보장하지 않음

- 재현 조건과 증상: 사내망 사용자가 다른 사람의 이름을 입력해도 시스템이 구분할 수 없다.
- 영향: 리뷰·정책 승인·외부 전송 감사 기록의 작성자 신뢰도가 네트워크 접근 통제 수준에 머문다.
- 지금 해결할 수 없는 이유: 초기 운영은 이름 입력만 사용하기로 합의했으며 내부 계정 또는 SSO 연동 정보가 없다.
- 접근 방법: 사용자 수와 책임 추적 요구가 커지면 이름 필드를 내부 계정 ID에 매핑하고 SSO 로그인·세션 만료·권한 회수를 도입한다.

## OpenAI 외부 전송의 조직 정책이 미정임

- 재현 조건과 증상: 로컬 Qwen 검증 실패 공고를 OpenAI로 보조 분석하려 해도 어떤 첨부·회사자료를 외부로 보낼 수 있는지 조직 승인이 없다.
- 영향: 보조 경로를 안전하게 운영 활성화할 수 없으며 실패 결과는 사람 검토로만 처리해야 한다.
- 지금 해결할 수 없는 이유: 데이터 분류와 외부 처리자 사용 승인은 저장소 밖의 조직 결정이다.
- 접근 방법: 전송 허용 문서 유형, 최소화 규칙, 보존 정책, 키 소유자와 감사 요구를 합의한 뒤 기본 비활성·건별 승인으로 제한한다.

## 심층 분석 품질 기준선이 사례 하나에 치우침

- 재현 조건과 증상: 현재 구조적 오류가 자세히 확인된 사례는 2025년 소방예방정보시스템 고도화 RFP 중심이며 다른 발주기관·문서 형식에 대한 요구사항 회수율과 사람 일치율이 없다.
- 영향: 이 사례에 맞춘 프롬프트·검증기가 다른 사업 유형에서 누락이나 과잉 경고를 만들 수 있다.
- 지금 해결할 수 없는 이유: 완료 사업 1~2개의 추가 첨부와 담당자 기준 답안이 아직 준비되지 않았다.
- 접근 방법: 공공 SI와 AI/데이터 또는 블록체인 축에서 서로 다른 문서 구조의 완료 사례를 추가하고 요구사항·자격·배점·위험의 기준 답안을 만든다.

## 1차 판정 프롬프트 응답 시간이 실측되지 않음

- 재현 조건과 증상: `qwen3.8:27b`의 1차 판정 프롬프트별 호출 시간과 전체 회차 처리 시간이 아직 측정되지 않았다. 파일럿의 심층 검토 측정에서 회차 처리 시간이 두 시간 안팎일 것으로 추정했을 뿐, 프롬프트와 호출 구조가 다른 1차 판정의 응답 시간 실측값은 아니다.
- 영향: 다음 날 02:00 실행 시각과 판정 시간 예산이 실제 처리량을 충족하는지 확인할 수 없으며, 측정되지 않은 시간을 운영 보장값으로 사용할 수 없다.
- 지금 해결할 수 없는 이유: 판정 에이전트가 아직 애플리케이션에 연결되지 않아 고정된 입력 표본에서 다섯 관점·반론·종합 호출, 동시성, 재시도, 타임아웃을 포함한 실제 계측을 수행하지 못했다.
- 접근 방법: 고정 표본과 동일한 모델·프롬프트·정책 버전으로 호출별 시작·종료 시각과 전체 회차 시간을 계측하고, 성공·타임아웃·잘린 출력·재시도 결과를 구분해 기록한다. 대표 회차를 반복 측정한 뒤 02:00 실행 창과 운영 시간 예산을 다시 정한다.

## 등급 재현성이 실측되지 않음

- 재현 조건과 증상: 같은 공고 입력에 같은 `qwen3.8:27b` 모델·프롬프트·정책 버전을 반복 적용해 최종 등급 일치율을 계산한 실행이 아직 없어 재현성이 `계산 불가` 상태다.
- 영향: 새 모델·프롬프트·정책 버전을 품질 게이트 통과 후보로 판단할 수 없고, 재현성 미측정 상태에서 정기 실행을 상시 활성화할 수 없다.
- 지금 해결할 수 없는 이유: 품질 게이트의 다섯 기준 가운데 등급 재현성은 원문 위치·숫자·요구사항을 결정적으로 검사하는 프롬프트나 검증기만으로 보장하기 어려운 유일한 항목이다. 같은 고정 입력의 반복 실행 자체가 필요하다.
- 접근 방법: 고정 표본 40건에 동일한 입력·모델·프롬프트·정책 버전으로 두 번 실행하고, 다섯 관점별 판단과 최종 `grade`의 일치율을 각각 계산한다. 최종 등급 일치율 80% 기준과 불일치 집중 여부를 함께 확인하며, 측정 전에는 통과로 처리하지 않는다.

## 관측 도구 도입 여부가 미정임

- 재현 조건과 증상: 판정 호출과 회차 실행의 계측 기록은 트레이스·스팬 구조로 남기도록 했지만, 전용 관측 도구를 도입할지 관리 화면에서 직접 조회할지는 결정되지 않았다.
- 영향: 실제 운영 전 호출 지연, 재시도, 실패 공고, 부분 성공 회차를 어떤 화면과 검색 방식으로 관찰·알림할지 확정할 수 없다.
- 지금 해결할 수 없는 이유: 판정 에이전트가 실제로 실행되지 않아 트레이스·스팬의 건수, 보존 기간, 조회량과 운영 담당자의 관측 요구를 측정할 수 없다. 사내 자료가 프롬프트에 들어가므로 외부 관측 서비스는 대상이 아니다.
- 접근 방법: 우선 회차·공고·호출 식별자와 시작·종료·상태·실패 사유를 트레이스·스팬 구조로 내부에 보존하고 파일럿 운영에서 조회·보존 요구를 확인한다. 실제 기록량과 보안 조건을 바탕으로 자체 화면과 자체 호스팅 전용 도구를 비교한 뒤 도입 여부를 정한다.
