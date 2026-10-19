# C-2 품질 게이트 채점 요약 (도구 초안)

- artifact: `reports/c2-gate-v5/gate-artifact.json`
- artifact sha256: `23178002a17e6572df4de4c00ec8f2edf63755e168ea49e31a6bfbaec0c5b3cd`
- gate_id: c2gate-ab196f52c8c0408b8498269006884e98
- gold: `data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v3/review/gold-adjudicated-full-population.tsv` sha256 `cbdb7adf060dab8136ee391e46100a41dfa444e0b5b86f27f18a69f912f16aa9` (queue_human_adjudicated)
- gold 모집단 625건 / 양성 54건 / 중요(높음) 25건 / 양성 중 draft 라벨 0건

## pass별 지표

| pass | recall % | precision % | 중요 누락 | 하루 최대 검토량 | 실행 전부 성공 |
|---|---:|---:|---:|---:|---|
| pass_1 | 100.0 | 40.2985 | 0 | 71 | 예 |
| pass_2 | 100.0 | 39.7059 | 0 | 73 | 예 |
| 나쁜 쪽 | 100.0 | 39.7059 | 0 | 73 | — |

두 pass 판정 일치율: 99.68% (623/625, 불일치 2건)
참고(창 전체 pool, 나쁜 쪽): recall 100.0% / precision 39.7059% / 중요 누락 0 / 검토 후보 136건
  └ 게시일별 결과를 창 전체로 pool한 값이다. ADR-0037의 단일 625건 batch와는 batch 구성이 달라 직접 비교값이 아니다.

scoring_input_sha256: `6bc167210fe2be8a048cf0ded22814ac6459739d8bb6eb4ceb08c3b3f510a563`

## 게시일별 분해

| pass | 게시일 | 모집단 | gold 양성 | 검토 후보 | TP | FP | FN | 중요 누락 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| pass_1 | 2026-08-27 | 308 | 28 | 71 | 28 | 43 | 0 | 0 |
| pass_1 | 2026-08-28 | 290 | 25 | 62 | 25 | 37 | 0 | 0 |
| pass_1 | 2026-08-29 | 9 | 0 | 0 | 0 | 0 | 0 | 0 |
| pass_1 | 2026-08-30 | 18 | 1 | 1 | 1 | 0 | 0 | 0 |
| pass_2 | 2026-08-27 | 308 | 28 | 73 | 28 | 45 | 0 | 0 |
| pass_2 | 2026-08-28 | 290 | 25 | 62 | 25 | 37 | 0 | 0 |
| pass_2 | 2026-08-29 | 9 | 0 | 0 | 0 | 0 | 0 | 0 |
| pass_2 | 2026-08-30 | 18 | 1 | 1 | 1 | 0 | 0 | 0 |

도구는 계산만 한다. 사람이 이 값을 확인한 뒤 evaluations POST로 기록한다.
