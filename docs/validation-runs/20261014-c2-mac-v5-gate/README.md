# C-2 v5 Mac 이전·품질 게이트·활성화 — 2026-10-14

결정: [ADR-0072](../../tracking/decisions/0072-c2-mac-litellm-ollama.md). 사람 승인: jechoi 일괄 승인
(계획 전체·프롬프트 v5·평가 제출·활성화·일일 스위치 대행·따라잡기 10-07~10-13).

## 배포

| 항목 | 값 |
|---|---|
| checkout | `/Users/temp/orca/bidops-c2mac`, 브랜치 `feat/c2-litellm-mac`(base `c242850`, 미커밋) |
| compose | `scripts/mac-compose.sh`, 프로젝트 `bidops`, web `127.0.0.1:18788`, tailnet `:8188` |
| 이미지 | `bidops:c2mac-20261014`(게이트 측정) → `bidops:c2mac-20261014b`(활성화 뒤, LiteLLM host가 generation config 승인 목록 안인지 대조 추가) |
| migration | 빈 DB에서 head까지(migrate 서비스 exit 0) |
| 모델 | LiteLLM `local-agent-main` → Ollama `qwen3.8:27b-ctx32k` Q4_K_M, digest `41a558fc459a96edbf0500938edc7d3ddaceedde727d1e7faa8ec4fbc9eb8772` |
| preflight | `scripts/c2-mac-model-preflight.sh` ok (별칭 경로·digest 3중 대조·컨테이너 TLS), completion 없음 |

## 발행 파일

| 파일 | sha256 |
|---|---|
| prompt `order-plan-batch-relevance-v5`(gitignore 본문) | `461f9664061e03da4e40dec1a09b6f7250794c1f96abd796ab0c4571370dcf85` |
| generation config v6 | `c94b67e9b4c4b0ffc4da6ee240bd201932415319a706f5990dbb35cdd170834a` |
| policy `c2-order-plan-screening-v5` | `1e6d4ef1414c61c1d04d0fec491e85380ab0227d1a6a43cec86b8c3bed887465` |
| binding v5 | `2e77505efd6ae87bc670fa6b04b72302b28da972d2d0e6fda3f200d77ff844e1` |
| review-inputs manifest | `3f0bd170a439f8c96716b668a6431c3ed62aa43b118958f60f019115fcc4e58c` |

## 게이트

- gate `c2gate-ab196f52c8c0408b8498269006884e98`, gold adjudicated v3(`cbdb7adf…`, manifest `72d6749d…`),
  측정 회차 `gate-gold-2026082{7,8,9}-plans`·`gate-gold-20260830-plans`(`--20260901T001247.754584Z`, 적재 경고 0),
  `scoring_input_sha256=6bc16721…`, 임계값 recall ≥ 90·precision ≥ 35·중요 누락 ≤ 3·하루 검토량 ≤ 80.
- pass 1 attempt 1: 0827 실행 `e8937fd4`가 `부분 성공` — batch-0010이 LiteLLM `provider_http_error`로
  2회 실패(88초·1초). 측정 스크립트 규칙대로 멈췄다. 원인은 Ollama 로그가 10-02 이후 없어 확인하지 못했다.
- pass 1 attempt 2: `d011ef17`·`a287c596`·`1a92741d`·`c6423011` 모두 `성공`.
- pass 2: `921d147e`·`416cbf7d`·`436480f1`·`87f21fab` 모두 `성공`.
- 배치 처리 시간: 25건 배치당 약 110~150초(입력 약 1,600 token, 출력 약 1,900 token). 300건 회차 약 26분.

| pass | recall % | precision % | 중요 누락 | 하루 최대 검토량 |
|---|---:|---:|---:|---:|
| 1 | 100.0 | 40.30 | 0 | 71 |
| 2 | 100.0 | 39.71 | 0 | 73 |
| 나쁜 쪽 | 100.0 | 39.71 | 0 | 73 |

두 pass 일치율 99.68%(623/625). 게시일별: 0827 gold 양성 28·후보 71~73, 0828 25·62, 0829 0·0, 0830 1·1.
artifact `reports/c2-gate-v5/gate-artifact.json`(`23178002a17e6572df4de4c00ec8f2edf63755e168ea49e31a6bfbaec0c5b3cd`),
경고 0. evaluation `c2gateeval-282966d3381741e79ba305c6cddfd22a` result `통과`.

## 활성화·스위치

- 후보 지정 audit `39ca1266…`, 활성화 `2026-10-14T12:59:58Z` audit `5f6b8cd2…`, 이전 active 없음.
- `env/c2.env` `BIDOPS_C2_DAILY_TRIGGER_ENABLED=true` 뒤 web·analysis-worker 재생성, 컨테이너 env 확인.
- 스위치 ON `2026-10-14T13:00:18Z` audit `f6d8ecc4…`, `GET /daily-trigger` → `effective_enabled:true`, v5.

## 이 기록이 증명하지 않는 것

- v4(vLLM 원본 weight)와의 동등성. v5 수치는 Q4 Ollama 빌드의 측정값이며 v4 수치를 승계하지 않는다.
- 임계값·감사 표본은 v4와 같은 PoC 값이다. 운영 전환 때 다시 정한다.
- 일일 무인 실행의 안정성. LiteLLM 일시 오류는 측정 중 한 번 실제로 났다.

## 따라잡기 10-07~10-13 (감독 시운전)

cron과 같은 명령(`env -i`, gnubin+OrbStack PATH, `flock`, `timeout`)으로
`run-daily-lifecycle.sh --track order-plans --from-date 2026-10-07 --to-date 2026-10-13`을 한 번
돌렸다. exit 0, 7일 모두 적재 경고 0·C-2 `성공`·실패 배치 0. 10-12는 10-13에 받은 수집본을 재사용했다.
**cron은 설치하지 않았다**(2026-10-14 사용자 결정). 일일 스위치는 켜져 있으나 스크립트를 돌릴
때만 의미가 있다.

| 게시일 | 모집단 | BM25 선택 | 관련 | 불확실 | 검토 후보 | 실패 |
|---|---:|---:|---:|---:|---:|---:|
| 10-07 | 434 | 300 | 41 | 43 | 84 | 0 |
| 10-08 | 479 | 300 | 40 | 62 | 102 | 0 |
| 10-09 | 28 | 28 | 2 | 4 | 6 | 0 |
| 10-10 | 21 | 21 | 3 | 2 | 5 | 0 |
| 10-11 | 23 | 23 | 2 | 4 | 6 | 0 |
| 10-12 | 511 | 300 | 55 | 38 | 93 | 0 |
| 10-13 | 408 | 300 | 36 | 32 | 68 | 0 |

평일 4일 중 3일이 게이트의 하루 검토량 임계값(80)을 넘었다(84·102·93). gold 4일(8월 말)의
최대 73과 다르며, 정답이 없는 날의 검토량이라 품질 판정은 아니지만 실무 부담 근거로 함께 적는다.
감사 표본은 실행당 10건씩 뽑혔다(BM25 모집단 ≤ 300인 주말은 `not_applicable`).
