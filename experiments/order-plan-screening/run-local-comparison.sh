#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run-local-comparison.sh --approved-by NAME --approve-capabilities \
    --prompt-file PATH --execute-dense --execute-qwen [options]

Runs the interim order-plan comparison through deterministic TF-IDF,
Ollama BGE-M3 dense representation, and local Qwen. BGE-M3 ColBERT and
GPT Luna remain deferred, separately controlled executions.

Required:
  --approved-by NAME       Human audit marker approving company capabilities
  --approve-capabilities   Confirm the reviewed capability projection
  --prompt-file PATH       Approved prompt from review-inputs/prompts
  --execute-dense          Explicitly allow local BGE-M3 embedding calls
  --execute-qwen           Explicitly allow local Qwen inference calls

Options:
  --run-id ID              Unique immutable run ID (default: timestamped)
  --from-raw DIR           Replay immutable raw pages instead of calling G2B
  --install-model-deps     Deprecated compatibility option; no effect
  --skip-tests             Skip the fake/unit test suite
  --help                   Show this help

Environment:
  BIDOPS_OLLAMA_BASE_URL   Approved Ollama URL, e.g. http://192.168.0.139:11434
  BIDOPS_G2B_API_KEY       Required unless --from-raw is supplied
EOF
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 2
}

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
EXPERIMENT_ROOT="$PROJECT_ROOT/experiments/order-plan-screening"
APPROVED_BY=""
APPROVE_CAPABILITIES=false
PROMPT_FILE=""
RUN_ID="order-plan-local-$(date +%Y%m%d-%H%M%S)"
FROM_RAW=""
INSTALL_MODEL_DEPS=false
EXECUTE_DENSE=false
EXECUTE_QWEN=false
RUN_TESTS=true

while (($#)); do
  case "$1" in
    --approved-by)
      (($# >= 2)) || fail "--approved-by 값이 필요합니다"
      APPROVED_BY=$2
      shift 2
      ;;
    --prompt-file)
      (($# >= 2)) || fail "--prompt-file 경로가 필요합니다"
      PROMPT_FILE=$2
      shift 2
      ;;
    --approve-capabilities)
      APPROVE_CAPABILITIES=true
      shift
      ;;
    --run-id)
      (($# >= 2)) || fail "--run-id 값이 필요합니다"
      RUN_ID=$2
      shift 2
      ;;
    --from-raw)
      (($# >= 2)) || fail "--from-raw 경로가 필요합니다"
      FROM_RAW=$2
      shift 2
      ;;
    --install-model-deps)
      INSTALL_MODEL_DEPS=true
      shift
      ;;
    --execute-dense)
      EXECUTE_DENSE=true
      shift
      ;;
    --execute-qwen)
      EXECUTE_QWEN=true
      shift
      ;;
    --skip-tests)
      RUN_TESTS=false
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "알 수 없는 인자: $1"
      ;;
  esac
done

[[ -n "$APPROVED_BY" ]] || fail "--approved-by가 필요합니다"
[[ "$APPROVE_CAPABILITIES" == true ]] \
  || fail "회사 역량 검토 후 --approve-capabilities를 명시해야 합니다"
[[ "$APPROVED_BY" != *$'\n'* && "$APPROVED_BY" != *$'\r'* ]] \
  || fail "--approved-by에 줄바꿈을 사용할 수 없습니다"
[[ -n "$PROMPT_FILE" ]] || fail "--prompt-file이 필요합니다"
[[ -f "$PROMPT_FILE" && ! -L "$PROMPT_FILE" ]] \
  || fail "prompt는 symlink가 아닌 일반 파일이어야 합니다"
[[ -s "$PROMPT_FILE" ]] || fail "prompt 파일이 비어 있습니다"
[[ "$RUN_ID" != *"/"* && "$RUN_ID" != *"\\"* && "$RUN_ID" != *".."* ]] \
  || fail "안전하지 않은 run ID입니다"
[[ -n "${BIDOPS_OLLAMA_BASE_URL:-}" ]] \
  || fail "BIDOPS_OLLAMA_BASE_URL을 설정해야 합니다"
[[ "$EXECUTE_DENSE" == true ]] \
  || fail "BGE-M3 dense 호출에는 --execute-dense 명시가 필요합니다"
[[ "$EXECUTE_QWEN" == true ]] \
  || fail "Qwen 호출에는 --execute-qwen 명시가 필요합니다"

if [[ -n "$FROM_RAW" ]]; then
  FROM_RAW=$(cd "$FROM_RAW" 2>/dev/null && pwd -P) \
    || fail "--from-raw 디렉터리를 읽을 수 없습니다"
else
  [[ -n "${BIDOPS_G2B_API_KEY:-}" ]] \
    || fail "신규 수집에는 BIDOPS_G2B_API_KEY가 필요합니다"
fi

PROMPT_FILE=$(cd "$(dirname "$PROMPT_FILE")" && pwd -P)/$(basename "$PROMPT_FILE")
RUN_DIR="$PROJECT_ROOT/data/experiments/order-plan-screening/$RUN_ID"
CONFIG_DIR="$PROJECT_ROOT/.dryforge/order-plan-screening/$RUN_ID/config"
CAPABILITIES_FILE="$CONFIG_DIR/company-capabilities.json"
METHODS_FILE="$CONFIG_DIR/methods.json"
REPORT_DIR="$PROJECT_ROOT/reports/order-plan-screening/$RUN_ID"

[[ ! -e "$RUN_DIR" ]] || fail "run 디렉터리가 이미 존재합니다: $RUN_DIR"
[[ ! -e "$CONFIG_DIR" ]] || fail "승인 설정 디렉터리가 이미 존재합니다: $CONFIG_DIR"
[[ ! -e "$REPORT_DIR" && ! -L "$REPORT_DIR" ]] \
  || fail "보고서 디렉터리가 이미 존재합니다: $REPORT_DIR"

umask 077

printf '%s\n' '[0/8] validate review-input manifest and active hashes'
PYTHONDONTWRITEBYTECODE=1 python3 \
  "$EXPERIMENT_ROOT/scripts/validate_review_inputs.py"

if [[ "$RUN_TESTS" == true ]]; then
  printf '%s\n' '[1/8] fake/unit tests'
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s "$EXPERIMENT_ROOT/tests" -p 'test_*.py' -v
else
  printf '%s\n' '[1/8] fake/unit tests skipped by operator'
fi

PYTHON_BIN=python3
printf '%s\n' '[2/8] standard-library TF-IDF and Ollama dense adapters'
if [[ "$INSTALL_MODEL_DEPS" == true ]]; then
  printf '%s\n' '  note: --install-model-deps is deprecated and ignored for this interim run'
fi

printf '%s\n' '[3/8] bind approved capabilities, prompt, and method config'
mkdir -p "$CONFIG_DIR"
APPROVED_BY_VALUE="$APPROVED_BY" \
PROMPT_FILE_VALUE="$PROMPT_FILE" \
CAPABILITIES_OUTPUT="$CAPABILITIES_FILE" \
METHODS_OUTPUT="$METHODS_FILE" \
EXPERIMENT_ROOT_VALUE="$EXPERIMENT_ROOT" \
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$EXPERIMENT_ROOT/scripts" \
"$PYTHON_BIN" - <<'PY'
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import (
    capabilities_projection,
    digest_json,
    load_json,
    load_methods_config,
    sha256_file,
    write_json_new,
)

root = Path(os.environ["EXPERIMENT_ROOT_VALUE"])
capabilities = load_json(
    root / "review-inputs/company/company-capabilities-v1-approved.json"
)
projection = capabilities_projection(capabilities, require_approved=False)
if capabilities.get("summary_sha256") != digest_json(projection):
    raise SystemExit("company capability projection hash mismatch")
capabilities["approval_status"] = "approved"
capabilities["approved_by"] = os.environ["APPROVED_BY_VALUE"]
capabilities["approved_at"] = datetime.now(
    timezone(timedelta(hours=9))
).isoformat()

methods = load_methods_config(root / "config/methods.json")
prompt_hash = sha256_file(Path(os.environ["PROMPT_FILE_VALUE"]))
methods["methods"]["qwen"]["prompt_sha256"] = prompt_hash
methods["methods"]["luna"]["prompt_sha256"] = prompt_hash

write_json_new(Path(os.environ["CAPABILITIES_OUTPUT"]), capabilities)
write_json_new(Path(os.environ["METHODS_OUTPUT"]), methods)
PY

printf '%s\n' '[4/8] collect or replay immutable population'
COLLECT_ARGS=(
  "$EXPERIMENT_ROOT/scripts/collect.py"
  --run-id "$RUN_ID"
  --output-dir "$RUN_DIR"
  --timeout 60
  --max-attempts 3
  --company-capabilities "$CAPABILITIES_FILE"
  --methods-config "$METHODS_FILE"
)
if [[ -n "$FROM_RAW" ]]; then
  COLLECT_ARGS+=(--from-raw "$FROM_RAW")
fi
"$PYTHON_BIN" "${COLLECT_ARGS[@]}"

run_method() {
  local method=$1
  shift
  printf '%s\n' "  readiness: $method"
  "$PYTHON_BIN" "$EXPERIMENT_ROOT/scripts/run_methods.py" \
    --run-dir "$RUN_DIR" \
    --method "$method" \
    --check-ready \
    --company-capabilities "$CAPABILITIES_FILE" \
    --methods-config "$METHODS_FILE" \
    "$@"
  printf '%s\n' "  execute: $method"
  "$PYTHON_BIN" "$EXPERIMENT_ROOT/scripts/run_methods.py" \
    --run-dir "$RUN_DIR" \
    --method "$method" \
    --company-capabilities "$CAPABILITIES_FILE" \
    --methods-config "$METHODS_FILE" \
    "$@"
}

printf '%s\n' '[5/8] deterministic TF-IDF'
run_method tfidf

printf '%s\n' '[6/8] Ollama BGE-M3 dense representation'
run_method bge_m3_dense

printf '%s\n' '[7/8] local Qwen fixed batches'
run_method qwen --prompt-file "$PROMPT_FILE"

printf '%s\n' '[8/8] interim HTML execution report'
"$PYTHON_BIN" "$EXPERIMENT_ROOT/scripts/render_execution_report.py" \
  --run-dir "$RUN_DIR" \
  --output-dir "$REPORT_DIR" \
  --methods tfidf bge_m3_dense qwen
"$PYTHON_BIN" "$EXPERIMENT_ROOT/scripts/render_decision_report.py" \
  --run-dir "$RUN_DIR" \
  --output-dir "$REPORT_DIR" \
  --methods tfidf bge_m3_dense qwen

PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
print("\nmethod summary")
for method in ("tfidf", "bge_m3_dense", "qwen"):
    result = json.loads((run_dir / "results" / f"{method}.json").read_text())
    metrics = result["metrics"]
    print(
        f"{method}: status={result['status']} "
        f"success={metrics['success_count']} failed={metrics['failure_count']} "
        f"elapsed_ms={metrics['elapsed_ms']}"
    )
print(f"run_dir={run_dir}")
print(f"report={run_dir.parents[3] / 'reports' / 'order-plan-screening' / run_dir.name / 'report.html'}")
print(f"decision_report={run_dir.parents[3] / 'reports' / 'order-plan-screening' / run_dir.name / 'decision-report.html'}")
PY
