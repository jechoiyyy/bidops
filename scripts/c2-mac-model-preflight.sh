#!/usr/bin/env bash
# Mac C-2 모델 경계 건식 확인 (ADR-0072). 모델 호출(completion)은 하지 않는다.
#   1) LiteLLM 별칭이 로컬 Ollama의 승인 모델로만 가는지 (/model/info)
#   2) Ollama 태그 digest = 선언 revision = binding·generation config digest
#   3) analysis-worker 컨테이너에서 LiteLLM /v1/models 에 TLS로 닿는지
# 하나라도 어긋나면 비0으로 끝난다.
set -euo pipefail
cd "$(dirname "$0")/.."

alias_name="$(jq -r .request_model experiments/order-plan-screening/config/order-plan-screening-generation-config.v6.json)"
upstream="$(jq -r .upstream_model experiments/order-plan-screening/config/order-plan-screening-generation-config.v6.json)"
gen_revision="$(jq -r .model_revision experiments/order-plan-screening/config/order-plan-screening-generation-config.v6.json)"
binding_digest="$(jq -r .stage2_binding.model_digest experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v5.json)"
declared="$(awk -F= '$1=="BIDOPS_VLLM_MODEL_REVISION"{print $2}' env/model.env)"
api_key="$(awk -F= '$1=="BIDOPS_VLLM_API_KEY"{print $2}' env/model.env)"

fail() { echo "preflight FAIL: $*" >&2; exit 1; }

route="$(curl -fsS -m 10 -H "Authorization: Bearer ${api_key}" http://127.0.0.1:4000/v1/model/info \
  | jq -c --arg a "${alias_name}" '[.data[] | select(.model_name == $a) | {model: .litellm_params.model, api_base: .litellm_params.api_base}]')"
[[ "${route}" == "[{\"model\":\"openai/${upstream}\",\"api_base\":\"http://127.0.0.1:11434/v1\"}]" ]] \
  || fail "LiteLLM alias ${alias_name} routes to ${route}"

ollama_digest="$(curl -fsS -m 10 http://127.0.0.1:11434/api/tags \
  | jq -r --arg m "${upstream}" '.models[] | select(.name == $m) | .digest')"
for value in "${gen_revision}" "${binding_digest}" "${declared}"; do
  [[ "${value}" == "${ollama_digest}" ]] || fail "digest mismatch: ollama=${ollama_digest} value=${value}"
done

scripts/mac-compose.sh exec -T analysis-worker python -c '
import os, httpx
r = httpx.get(os.environ["BIDOPS_VLLM_BASE_URL"] + "/models", trust_env=False, follow_redirects=False, timeout=10,
              headers={"Authorization": "Bearer " + os.environ["BIDOPS_VLLM_API_KEY"]})
ids = [m["id"] for m in r.json().get("data", [])]
assert r.status_code == 200 and "'"${alias_name}"'" in ids, (r.status_code, ids)
' || fail "analysis-worker cannot reach LiteLLM over TLS"

echo "preflight ok: alias=${alias_name} upstream=${upstream} digest=${ollama_digest:0:12}…"
