"""Passive, single-call Codex boundary. No DB, object store, queue or request logging."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLI_VERSION = "0.162.1"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "high"
TIMEOUT = 900
HEARTBEAT_TIMEOUT = 45
MAX_BYTES = 8 * 1024 * 1024


def cli_schema(value):
    """Strict-output decoding aid. Authority validation still runs in BidOps."""
    if isinstance(value, list):
        return [cli_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    # uniqueItems is not accepted by strict structured output (live T12, decision B28);
    # BidOps authority validation still enforces uniqueness after decoding.
    result = {key: cli_schema(item) for key, item in value.items()
              if key not in {"$schema", "$id", "allOf", "oneOf", "uniqueItems"}}
    if "const" in result:
        result["enum"] = [result.pop("const")]
    if result.get("type") == "object":
        properties = result.get("properties", {})
        required = result.get("required", [])
        for key in properties:
            if key not in required:
                properties[key] = {"anyOf": [properties[key], {"type": "null"}]}
        result["properties"] = properties
        result["required"] = list(properties)
        result["additionalProperties"] = False
    return result


def output_schema(authority):
    schema = deepcopy(authority)
    # Free-form locator objects cannot be decoded by strict structured output.
    # Keep the exact authority locator shapes; domain validation still checks
    # that locator_type/source_kind select the correct shape.
    if "evidence_base" not in schema.get("$defs", {}):
        return cli_schema(schema)
    schema["$defs"]["evidence_base"]["properties"]["locator"] = {
        "anyOf": [{"$ref": "#/$defs/" + name} for name in (
            "page_locator", "paragraph_locator", "table_cell_locator", "bbox_locator", "profile_fact_locator")]
    }
    schema["$defs"]["evidence"] = deepcopy(schema["$defs"]["evidence_base"])
    return cli_schema(schema)


def error_code(diagnostic):
    # --json keeps echoed prompts out of stderr. Match concrete service errors,
    # not generic words such as authentication that may appear in input text.
    text = diagnostic.lower()
    if "invalid schema" in text or "invalid_json_schema" in text:
        return "schema_invalid"
    if any(x in text for x in ("401", "unauthorized", "invalid_api_key", "token_expired", "failed to refresh", "not logged in")):
        return "authentication_failed"
    if any(x in text for x in ("model_not_found", "model_not_supported", "not supported", "403")):
        return "model_access_denied"
    return "runner_failed"


# Failure categories logged by the runner (decision B27). Only category names are
# logged; prompt, model output and raw diagnostic text never leave this process.
FAILURE_CATEGORIES = {
    "schema": ("invalid schema", "invalid_json_schema", "response_format"),
    "auth": ("401", "unauthorized", "invalid_api_key", "token_expired", "failed to refresh", "not logged in"),
    "model_access": ("model_not_found", "model_not_supported", "not supported", "403"),
    "usage_limit": ("usage limit", "usage_limit", "quota", "insufficient_quota", "billing"),
    "rate_limited": ("429", "rate limit", "rate_limit", "too many requests"),
    "context_length": ("context_length", "context length", "maximum context", "too long", "too large", "max_tokens"),
    "network": ("connection", "timed out", "timeout", "stream disconnected", "network", "dns", "unreachable"),
    "server": ("500", "502", "503", "504", "internal server error", "overloaded", "server_error"),
}


def failure_categories(diagnostic):
    text = diagnostic.lower()
    return sorted(name for name, needles in FAILURE_CATEGORIES.items() if any(n in text for n in needles))


def event_errors(stream_text):
    """Error/failure messages from codex `--json` stdout events (never agent output)."""
    found = []
    for line in stream_text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type") or (event.get("msg") or {}).get("type") or "")
        if "error" in kind or "fail" in kind:
            payload = event.get("msg") if isinstance(event.get("msg"), dict) else event
            for key in ("message", "error", "reason", "code"):
                value = payload.get(key)
                if isinstance(value, (str, int)):
                    found.append(str(value))
                elif isinstance(value, dict):
                    found.extend(str(v) for v in value.values() if isinstance(v, (str, int)))
    return "\n".join(found)


def require_cli_version(version):
    if version != 'codex-cli ' + CLI_VERSION:
        raise SystemExit('cli_version_mismatch')


def argv(schema, output, cwd):
    return ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--strict-config",
            "--model", MODEL, "-c", f'model_reasoning_effort="{REASONING_EFFORT}"',
            "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
            "-c", 'features.shell_tool=false', "-c", 'features.multi_agent=false',
            "--sandbox", "read-only", "--ephemeral", "--json", "--skip-git-repo-check",
            "--cd", str(cwd), "--output-schema", str(schema), "--output-last-message", str(output), "--color", "never", "-"]


def terminate(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def execute(prompt, alive, *, secret=Path('/run/secrets/codex_auth'), schema_path=Path('/app/stage.json')):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="luna-") as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir(mode=0o700)
        auth = home / "auth.json"
        auth.write_bytes(secret.read_bytes())
        auth.chmod(0o600)
        schema = json.loads(schema_path.read_text())
        schema_file, output = root / "schema.json", root / "output.json"
        schema_file.write_text(json.dumps(output_schema(schema)))
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "CODEX_HOME": str(home), "LANG": "C.UTF-8"}
        with (root / "input").open("wb+") as source, (root / "errors").open("wb+") as errors, \
                (root / "events").open("wb+") as events:
            source.write(prompt.encode()); source.seek(0)
            process = subprocess.Popen(argv(schema_file, output, root), stdin=source, stdout=events,
                                       stderr=errors, cwd=root, env=env, start_new_session=True)
            try:
                while process.poll() is None:
                    if not alive():
                        return {"status": "failed", "error_code": "lease_lost"}
                    if time.monotonic() - started > TIMEOUT:
                        return {"status": "failed", "error_code": "model_timeout"}
                    if errors.tell() > MAX_BYTES or events.tell() > MAX_BYTES or (output.exists() and output.stat().st_size > MAX_BYTES):
                        return {"status": "failed", "error_code": "output_truncated"}
                    time.sleep(0.1)
                if process.returncode:
                    errors.seek(0); events.seek(0)
                    diagnostic = (errors.read(MAX_BYTES).decode(errors="replace") + "\n"
                                  + event_errors(events.read(MAX_BYTES).decode(errors="replace"))).lower()
                    code = error_code(diagnostic)
                    print(json.dumps({"event": "runner.call_failed", "error_code": code,
                                      "categories": failure_categories(diagnostic),
                                      "returncode": process.returncode}), flush=True)
                    return {"status": "failed", "error_code": code}
                if not output.exists() or output.stat().st_size > MAX_BYTES:
                    return {"status": "failed", "error_code": "output_truncated"}
                raw = output.read_text()
                try:
                    json.loads(raw)
                except ValueError:
                    return {"status": "failed", "error_code": "schema_invalid", "raw_response": raw}
                return {"status": "completed", "raw_response": raw, "cli_version": CLI_VERSION,
                        "input_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "latency_ms": int((time.monotonic()-started)*1000)}
            finally:
                # Kill descendants even when the parent has already exited.
                terminate(process)


class Slot:
    def __init__(self):
        self.lock = threading.Lock()
        self.call_id = None
        self.result = None
        self.heartbeat = 0
        self.cancelled = False
        self.running = False

    def start(self, prompt, contract="deep-review-stage-v2"):
        with self.lock:
            if self.running:
                return None
            self.call_id = str(uuid.uuid4())
            self.result = None
            self.heartbeat = time.monotonic()
            self.cancelled = False
            self.running = True
            def run():
                try:
                    result = execute(prompt, lambda: not self.cancelled and time.monotonic()-self.heartbeat < HEARTBEAT_TIMEOUT,
                                     schema_path=CONTRACT_SCHEMA_PATHS[contract])
                except Exception:
                    result = {"status": "failed", "error_code": "runner_unavailable"}
                with self.lock:
                    self.result = result
                    self.running = False
                    completed_id = self.call_id
                def forget():
                    with self.lock:
                        if self.call_id == completed_id and not self.running:
                            self.result = None
                            self.call_id = None
                timer = threading.Timer(HEARTBEAT_TIMEOUT, forget)
                timer.daemon = True
                timer.start()
            threading.Thread(target=run, daemon=True).start()
            return self.call_id

slot = Slot()

# Closed contract allowlist: each name maps to one schema file baked into the
# image (Dockerfile COPY).  A request can never choose a path, schema or model.
CONTRACT_SCHEMA_PATHS = {
    "deep-review-stage-v2": Path("/app/stage.json"),
    "assumption-stage-v1": Path("/app/assumption.json"),
    "card-extract-v1": Path("/app/card-extract.json"),
    # 결정 B33 (policy v4): kind x unit branches, no concept_candidates/operator.
    "card-extract-v2": Path("/app/card-extract-v2.json"),
    "card-role-v1": Path("/app/card-role.json"),
    # 결정 C16 (policy v10): role findings cite short evidence ids (E1...) only.
    "card-role-v2": Path("/app/card-role-v2.json"),
    "card-synthesis-v1": Path("/app/card-synthesis.json"),
    # 결정 B55 (policy v9): no blocking_condition_ids; code computes them.
    "card-synthesis-v2": Path("/app/card-synthesis-v2.json"),
    # RL-04 proposal drafting: one section (bidops.proposal-section.v1) per call.
    "proposal-section-v1": Path("/app/proposal-section.json"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if self.path != '/calls' or not 0 < length <= MAX_BYTES:
                return self.reply(400, {})
            data = json.loads(self.rfile.read(length))
            if set(data) not in ({'prompt'}, {'prompt', 'contract'}) or not isinstance(data['prompt'], str) or data.get('contract', 'deep-review-stage-v2') not in CONTRACT_SCHEMA_PATHS:
                return self.reply(400, {})
            call_id = slot.start(data['prompt'], data.get('contract', 'deep-review-stage-v2'))
            self.reply(202 if call_id else 409, {'call_id': call_id})
        except Exception:
            self.reply(400, {})

    def do_GET(self):
        with slot.lock:
            if self.path != '/calls/' + str(slot.call_id):
                return self.reply(404, {})
            slot.heartbeat = time.monotonic()
            self.reply(200, slot.result or {'status': 'running'})

    def do_DELETE(self):
        with slot.lock:
            if self.path != '/calls/' + str(slot.call_id):
                return self.reply(404, {})
            slot.cancelled = True
        # Acknowledge cancellation only once the subprocess group has stopped.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with slot.lock:
                if not slot.running:
                    slot.result = None
                    slot.call_id = None
                    return self.reply(200, {})
            time.sleep(0.05)
        self.reply(503, {})


if __name__ == '__main__':
    version = subprocess.run(['codex', '--version'], capture_output=True, text=True, check=True).stdout.strip()
    require_cli_version(version)
    ThreadingHTTPServer(('0.0.0.0', 8091), Handler).serve_forever()
