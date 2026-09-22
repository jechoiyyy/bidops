"""Single-call adapter; the synthesis worker retains queue and lease ownership."""
import hashlib
import json
import time
from urllib.parse import urlsplit

import httpx

from ...core.model_client import InvocationResult, ModelInvocationError, build_prompt
from ..contracts import validate_payload, SchemaValidationError

SAFE_ERRORS = frozenset({'lease_lost', 'model_timeout', 'output_truncated', 'schema_invalid',
                         'authentication_failed', 'model_access_denied', 'runner_failed', 'runner_unavailable'})


class LunaClient:
    provider_name = 'codex-exec'
    model = 'gpt-5.6-luna'

    def __init__(self, endpoint, heartbeat, deadline, *, transport=None):
        address = urlsplit(endpoint)
        if address.scheme != 'http' or address.hostname != 'codex-runner' or address.port != 8091 or address.path or address.query or address.username:
            raise ValueError('invalid internal runner endpoint')
        self.http = httpx.Client(base_url=endpoint, timeout=10, transport=transport, trust_env=False)
        self.heartbeat = heartbeat
        self.deadline = deadline

    def close(self):
        self.http.close()

    def invoke(self, stage, input_slice, policy, *, profile=None, prior_stages=()):
        prompt = build_prompt(stage, input_slice, policy, profile=profile, prior_stages=prior_stages, max_chars=100000)
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        call_id = None
        try:
            self.heartbeat()
            if time.monotonic() >= self.deadline:
                raise ModelInvocationError('review_timeout', ())
            response = self.http.post('/calls', json={'prompt': prompt})
            response.raise_for_status()
            from uuid import UUID
            call_id = str(UUID(response.json()['call_id']))
            while True:
                self.heartbeat()
                if time.monotonic() >= self.deadline:
                    raise ModelInvocationError('review_timeout', ())
                response = self.http.get('/calls/' + call_id)
                response.raise_for_status()
                data = response.json()
                if data['status'] != 'running':
                    break
                time.sleep(5)
            if data['status'] != 'completed':
                code = data.get('error_code')
                raise ModelInvocationError(code if code in SAFE_ERRORS else 'runner_failed', (), data.get('raw_response', '').encode())
            if data.get('cli_version') != '0.155.1' or data.get('input_sha256') != digest:
                raise ModelInvocationError('runner_identity_mismatch', ())
            raw = data['raw_response'].encode()
            try:
                output = validate_payload(json.loads(raw), "deep-review-stage-v2")
            except (ValueError, SchemaValidationError) as error:
                raise ModelInvocationError("schema_invalid", (), raw) from error
            # CLI strict schema emits nullable optional keys. They are valid in
            # the authority schema only when that schema permits null; no repair.
            output_digest = hashlib.sha256(raw).hexdigest()
            return InvocationResult(output, raw, digest, output_digest, None, None, data['latency_ms'],
                                    ({'status': 'succeeded', 'provider': self.provider_name, 'model': self.model,
                                      'cli_version': '0.155.1', 'reasoning_effort': 'xhigh'},), self.provider_name, self.model)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise ModelInvocationError('runner_unavailable', ()) from error
        finally:
            if call_id:
                try:
                    self.http.delete('/calls/' + call_id).raise_for_status()
                except httpx.HTTPError:
                    # Keep the shared slot until the disconnected runner watchdog
                    # has killed its subprocess (45 seconds plus margin).
                    time.sleep(46)
