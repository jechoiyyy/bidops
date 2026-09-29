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

CLI_VERSION = "0.155.1"
MODEL = "gpt-5.6-luna"
TIMEOUT = 900
HEARTBEAT_TIMEOUT = 45
MAX_BYTES = 8 * 1024 * 1024


def cli_schema(value):
    """Strict-output decoding aid. Authority validation still runs in BidOps."""
    if isinstance(value, list):
        return [cli_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: cli_schema(item) for key, item in value.items() if key not in {"$schema", "$id", "allOf", "oneOf"}}
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


def argv(schema, output, cwd):
    return ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--strict-config",
            "--model", MODEL, "-c", 'model_reasoning_effort="xhigh"',
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
        with (root / "input").open("wb+") as source, (root / "errors").open("wb+") as errors:
            source.write(prompt.encode()); source.seek(0)
            process = subprocess.Popen(argv(schema_file, output, root), stdin=source, stdout=subprocess.DEVNULL,
                                       stderr=errors, cwd=root, env=env, start_new_session=True)
            try:
                while process.poll() is None:
                    if not alive():
                        return {"status": "failed", "error_code": "lease_lost"}
                    if time.monotonic() - started > TIMEOUT:
                        return {"status": "failed", "error_code": "model_timeout"}
                    if errors.tell() > MAX_BYTES or (output.exists() and output.stat().st_size > MAX_BYTES):
                        return {"status": "failed", "error_code": "output_truncated"}
                    time.sleep(0.1)
                if process.returncode:
                    errors.seek(0)
                    diagnostic = errors.read(MAX_BYTES).decode(errors="replace").lower()
                    code = error_code(diagnostic)
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
                                     schema_path=Path("/app/assumption.json" if contract == "assumption-stage-v1" else "/app/stage.json"))
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
            if set(data) not in ({'prompt'}, {'prompt', 'contract'}) or not isinstance(data['prompt'], str) or data.get('contract', 'deep-review-stage-v2') not in {'deep-review-stage-v2', 'assumption-stage-v1'}:
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
    if version != 'codex-cli ' + CLI_VERSION:
        raise SystemExit('cli_version_mismatch')
    ThreadingHTTPServer(('0.0.0.0', 8091), Handler).serve_forever()
