# C-2 품질 게이트 채점 요약 (도구 초안)

- artifact: `reports/c2-gate-v6/gate-artifact.json`
- artifact sha256: `739767c4a01e5a0f33193a67fe89f579f43b95578ea5eeaca399497a49cf1272`
- gate_id: c2gate-e23a8e1fec84413a90609b14479d4476
- gold: `data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v3/review/gold-adjudicated-full-population.tsv` sha256 `cbdb7adf060dab8136ee391e46100a41dfa444e0b5b86f27f18a69f912f16aa9` (queue_human_adjudicated)
- gold 모집단 625건 / 양성 54건 / 중요(높음) 25건 / 양성 중 draft 라벨 0건

## pass별 지표

| pass | recall % | precision % | 중요 누락 | 하루 최대 검토량 | 실행 전부 성공 |
|---|---:|---:|---:|---:|---|
| pass_1 | 96.2963 | 45.614 | 0 | 59 | 예 |
| pass_2 | 96.2963 | 45.614 | 0 | 59 | 예 |
| 나쁜 쪽 | 96.2963 | 45.614 | 0 | 59 | — |

두 pass 판정 일치율: 100.0% (625/625, 불일치 0건)
참고(창 전체 pool, 나쁜 쪽): recall 96.2963% / precision 45.614% / 중요 누락 0 / 검토 후보 114건
  └ 게시일별 결과를 창 전체로 pool한 값이다. ADR-0037의 단일 625건 batch와는 batch 구성이 달라 직접 비교값이 아니다.

scoring_input_sha256: `6bc167210fe2be8a048cf0ded22814ac6459739d8bb6eb4ceb08c3b3f510a563`

## 게시일별 분해

| pass | 게시일 | 모집단 | gold 양성 | 검토 후보 | TP | FP | FN | 중요 누락 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| pass_1 | 2026-08-27 | 308 | 28 | 59 | 27 | 32 | 1 | 0 |
| pass_1 | 2026-08-28 | 290 | 25 | 54 | 24 | 30 | 1 | 0 |
| pass_1 | 2026-08-29 | 9 | 0 | 0 | 0 | 0 | 0 | 0 |
| pass_1 | 2026-08-30 | 18 | 1 | 1 | 1 | 0 | 0 | 0 |
| pass_2 | 2026-08-27 | 308 | 28 | 59 | 27 | 32 | 1 | 0 |
| pass_2 | 2026-08-28 | 290 | 25 | 54 | 24 | 30 | 1 | 0 |
| pass_2 | 2026-08-29 | 9 | 0 | 0 | 0 | 0 | 0 | 0 |
| pass_2 | 2026-08-30 | 18 | 1 | 1 | 1 | 0 | 0 | 0 |

도구는 계산만 한다. 사람이 이 값을 확인한 뒤 evaluations POST로 기록한다.
