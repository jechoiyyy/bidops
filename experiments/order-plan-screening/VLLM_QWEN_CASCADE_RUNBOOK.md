# Qwen 1차 분류 및 prefilter cascade 실행서

이 문서는 실행 준비와 C-2 선택 binding을 고정한다. 현재 대상은 사설 vLLM
`http://192.168.0.139:58765/v1`, served model 기대값은 `qwen3.8-27B`다.
명령을 실행하기 전 서버 운영자가 제공한 64자 model artifact digest가 필요하다.
`/v1/models`의 served ID만으로 weight revision을 추정하지 않는다.

고정 입력은 2026-08-27 00:00부터 2026-08-31 00:00 미만 KST의 625건이다.
평가 reference v2는 관련 59건, 비관련 566건이며 label provenance는 사람 확정 22건,
초안 603건이다. cutoff 300은 기존 C-2 검토량 기준이며 이 reference로 튜닝하지 않았다.
2026-09-01에 `BM25 Top 300 + Qwen`을 C-2 방식으로 확정했다
([ADR-0037](../../docs/tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md)).

## 1. 환경과 methods 설정

```bash
python3 experiments/order-plan-screening/scripts/validate_review_inputs.py

export BIDOPS_QWEN_BASE_URL=http://192.168.0.139:58765/v1
export BIDOPS_QWEN_MODEL_REVISION='<서버 운영자가 제공한 64자 artifact digest>'
export BIDOPS_QWEN_BIND_INTERFACE=eth1
# 인증이 켜진 서버에서만 실제 key를 별도 환경으로 주입한다.
# export BIDOPS_QWEN_API_KEY='<approved secret>'

python3 experiments/order-plan-screening/scripts/prepare_vllm_qwen_config.py \
  --base-config experiments/order-plan-screening/config/methods.json \
  --prompt-file experiments/order-plan-screening/review-inputs/prompts/order-plan-batch-relevance-v3-approved.txt \
  --model-name 'qwen3.8-27B' \
  --model-revision "$BIDOPS_QWEN_MODEL_REVISION" \
  --out .dryforge/order-plan-screening/20260827-20260830-qwen-vllm-v3/config/methods.json
```

실행 전 `/v1/models`의 served ID가 `qwen3.8-27B`인지 확인한다. client도 각 응답의
`model` 값이 다르면 `served_model_mismatch`로 해당 batch를 실패 처리한다.

## 2. 전수 direct 회차 준비와 실행

```bash
python3 experiments/order-plan-screening/scripts/prepare_collected_run.py \
  --run-id 20260827-20260830-qwen-direct-v3 \
  --output-dir data/experiments/order-plan-screening/20260827-20260830-qwen-direct-v3 \
  --collected data/runs/order-plans-20260827-20260830-retry1/collected-order-plans.json \
  --methods-config .dryforge/order-plan-screening/20260827-20260830-qwen-vllm-v3/config/methods.json

python3 experiments/order-plan-screening/scripts/run_methods.py \
  --run-dir data/experiments/order-plan-screening/20260827-20260830-qwen-direct-v3 \
  --method qwen \
  --prompt-file experiments/order-plan-screening/review-inputs/prompts/order-plan-batch-relevance-v3-approved.txt \
  --methods-config .dryforge/order-plan-screening/20260827-20260830-qwen-vllm-v3/config/methods.json
```

625건은 25건씩 25개 고정 batch다. 회사 역량 6개와 제목만 전송하며 batch 실패를
재시도·분할·타 모델 대체하지 않는다.

## 3. 선택된 BM25 Top 300 cascade 준비와 실행

```bash
python3 experiments/order-plan-screening/scripts/prepare_qwen_cascade.py \
  --source-run-dir data/experiments/order-plan-screening/20260827-20260830-qwen-direct-v3 \
  --run-id 20260827-20260830-bm25-qwen300-v3 \
  --output-dir data/experiments/order-plan-screening/20260827-20260830-bm25-qwen300-v3 \
  --method bm25 --top-k 300 \
  --methods-config .dryforge/order-plan-screening/20260827-20260830-qwen-vllm-v3/config/methods.json

python3 experiments/order-plan-screening/scripts/run_methods.py \
  --run-dir data/experiments/order-plan-screening/20260827-20260830-bm25-qwen300-v3 \
  --method qwen \
  --prompt-file experiments/order-plan-screening/review-inputs/prompts/order-plan-batch-relevance-v3-approved.txt \
  --methods-config .dryforge/order-plan-screening/20260827-20260830-qwen-vllm-v3/config/methods.json
```

300건은 12개 고정 batch다. 탈락 325건은 Qwen의 `not_relevant` 판정으로 위장하지
않고 `stage1 filtered_out`으로 보존한다.

## 4. Dense 및 RRF Top 300 cascade

성공한 동일 전수 모집단 BGE-M3 dense 결과가 있을 때만 아래 두 회차를 만든다.
현재 기록된 dense endpoint 실패 결과는 입력으로 사용할 수 없다.

```bash
python3 experiments/order-plan-screening/scripts/prepare_qwen_cascade.py \
  --source-run-dir <성공한-dense-source-run> \
  --run-id 20260827-20260830-dense-qwen300-v1 \
  --output-dir data/experiments/order-plan-screening/20260827-20260830-dense-qwen300-v1 \
  --method dense --top-k 300 --dense-result <성공한-bge_m3_dense.json> \
  --methods-config .dryforge/order-plan-screening/20260827-20260830-qwen-vllm-v3/config/methods.json

python3 experiments/order-plan-screening/scripts/prepare_qwen_cascade.py \
  --source-run-dir <성공한-dense-source-run> \
  --run-id 20260827-20260830-rrf-qwen300-v1 \
  --output-dir data/experiments/order-plan-screening/20260827-20260830-rrf-qwen300-v1 \
  --method hybrid_rrf --top-k 300 --dense-result <성공한-bge_m3_dense.json> \
  --methods-config .dryforge/order-plan-screening/20260827-20260830-qwen-vllm-v3/config/methods.json
```

각 cascade에서 생성된 population에 대해 3절과 같은 `run_methods.py --method qwen`
명령을 실행한다.

## 5. 채점

```bash
python3 experiments/order-plan-screening/scripts/score_qwen_reference.py \
  --run-dir data/experiments/order-plan-screening/20260827-20260830-qwen-direct-v3 \
  --reference data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2/review/gold-adjudicated-full-population.tsv

python3 experiments/order-plan-screening/scripts/score_qwen_cascade_reference.py \
  --source-run-dir data/experiments/order-plan-screening/20260827-20260830-qwen-direct-v3 \
  --cascade-run-dir data/experiments/order-plan-screening/20260827-20260830-bm25-qwen300-v3 \
  --reference data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2/review/gold-adjudicated-full-population.tsv
```

채점은 `relevant` 단독과 `relevant + uncertain` 검토 유지 기준을 분리한다. cascade는
전체 625건을 분모로 삼고, 1단계 누락과 Qwen 누락을 별도 목록으로 남긴다. 결과를
운영 활성화 근거로 사용할 때는 아직 초안인 603건의 사람 확인과 별도 품질 gate가 필요하다.
