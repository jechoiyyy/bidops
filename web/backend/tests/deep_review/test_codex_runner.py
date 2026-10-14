"""Synthetic subprocess and HTTP boundary; never authenticates or calls a model."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest

from app.deep_review.services.luna_client import LunaClient
from app.deep_review.services import luna_identity
from app.core.model_client import ModelInvocationError

RUNNER = Path(__file__).resolve().parents[3] / 'codex-runner' / 'runner.py'
spec = importlib.util.spec_from_file_location('bidops_codex_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_fixed_argv_and_schema():
    args = runner.argv(Path('/tmp/schema'), Path('/tmp/out'), Path('/tmp/work'))
    assert '--ignore-user-config' in args and '--ignore-rules' in args and '--ephemeral' in args
    assert luna_identity.PROVIDER == 'codex-exec'
    assert runner.MODEL == luna_identity.MODEL == 'gpt-6-luna'
    assert runner.REASONING_EFFORT == luna_identity.REASONING_EFFORT == 'high'
    assert runner.CLI_VERSION == luna_identity.CLI_VERSION == '0.162.1'
    assert luna_identity.HP_POLICY_IDENTITY == 'analysis-policy-luna-hp-v1'
    assert luna_identity.COMPANY_POLICY_IDENTITIES == frozenset({
        'analysis-policy-luna-demo-v1', 'analysis-policy-luna-hp-v1',
    })
    assert luna_identity.ALLOWED_MODELS == frozenset({'gpt-6-luna', 'gpt-5.6-luna'})
    assert luna_identity.ALLOWED_EFFORTS == frozenset({'high', 'xhigh'})
    assert luna_identity.matches_runtime('gpt-6-luna', 'high')
    assert not luna_identity.matches_runtime('gpt-5.6-luna', 'xhigh')
    assert args[args.index('--model')+1] == luna_identity.MODEL
    assert f'model_reasoning_effort="{luna_identity.REASONING_EFFORT}"' in args
    assert args[args.index('--sandbox')+1] == 'read-only'
    assert 'resume' not in args and 'shell' not in args
    # Compare with installed CLI help without sending input or reading auth.
    help_text = subprocess.run(['codex','exec','--help'], capture_output=True, text=True, check=True).stdout
    for flag in ('--ignore-user-config','--ignore-rules','--ephemeral','--output-schema','--skip-git-repo-check'):
        assert flag in help_text


def test_runner_rejects_a_different_codex_cli_version():
    assert runner.require_cli_version('codex-cli ' + luna_identity.CLI_VERSION) is None
    with pytest.raises(SystemExit, match='cli_version_mismatch'):
        runner.require_cli_version('codex-cli 0.155.1')


@pytest.mark.parametrize(('cli_version', 'accepted'), [('0.162.1', True), ('0.155.1', False)])
def test_client_requires_the_current_runner_identity(cli_version, accepted):
    import hashlib
    from uuid import uuid4

    prompt = 'synthetic-only'
    call_id = str(uuid4())
    methods = []

    def transport(request):
        methods.append(request.method)
        if request.method == 'POST':
            return httpx.Response(202, json={'call_id': call_id})
        if request.method == 'DELETE':
            return httpx.Response(200, json={})
        return httpx.Response(200, json={
            'status': 'completed', 'raw_response': '{"sections":[]}',
            'cli_version': cli_version, 'input_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'latency_ms': 1,
        })

    client = LunaClient('http://codex-runner:8091', lambda: None, time.monotonic() + 60,
                        transport=httpx.MockTransport(transport))
    try:
        if accepted:
            result = client.invoke_prompt(prompt, contract='assumption-stage-v1')
            assert result.model == luna_identity.MODEL
            assert result.provider == luna_identity.PROVIDER
            assert result.attempts == ({
                'status': 'succeeded', 'provider': luna_identity.PROVIDER, 'model': luna_identity.MODEL,
                'cli_version': luna_identity.CLI_VERSION, 'reasoning_effort': luna_identity.REASONING_EFFORT,
            },)
        else:
            with pytest.raises(ModelInvocationError) as error:
                client.invoke_prompt(prompt, contract='assumption-stage-v1')
            assert error.value.code == 'runner_identity_mismatch'
        assert methods == ['POST', 'GET', 'DELETE']
    finally:
        client.close()


@pytest.mark.parametrize('mode,expected', [('success','completed'),('auth','authentication_failed'),('model','model_access_denied'),('bad','schema_invalid'),('timeout','model_timeout'),('lease','lease_lost')])
def test_process_isolation_and_cleanup(tmp_path, monkeypatch, mode, expected):
    secret = tmp_path/'auth'; secret.write_text('{"synthetic":"secret"}')
    schema = RUNNER.parents[1]/'backend/app/deep_review/contracts/bidops.deep-review-stage.v2.json'
    seen = []
    original = runner.subprocess.Popen
    def fake(args, **kwargs):
        seen.append((args, kwargs))
        assert set(kwargs['env']) == {'HOME','CODEX_HOME','PATH','LANG'}
        assert Path(kwargs['env']['CODEX_HOME'],'auth.json').read_text() == secret.read_text()
        assert kwargs['start_new_session'] is True
        target = args[args.index('--output-last-message')+1]
        code = "import pathlib,sys,time; "
        if mode in {'timeout','lease'}: code += 'time.sleep(20)'
        elif mode in {'auth','model'}: code += f"sys.stderr.write({('401 authentication' if mode=='auth' else 'model_not_found')!r});sys.exit(1)"
        else: code += f"pathlib.Path({target!r}).write_text({('not-json' if mode=='bad' else '{}')!r})"
        return original([sys.executable,'-c',code], **kwargs)
    monkeypatch.setattr(runner.subprocess,'Popen',fake)
    monkeypatch.setattr(runner,'TIMEOUT',0.15)
    result = runner.execute('synthetic-only', lambda: mode != 'lease', secret=secret, schema_path=schema)
    assert result.get('error_code',result['status']) == expected
    assert not Path(seen[0][1]['cwd']).exists()
    assert 'secret' not in json.dumps(result)


def test_http_lease_loss_cancels_without_fallback():
    requests=[]; ticks=[]
    def transport(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(202 if request.method=='POST' else 200, json={'call_id':'00000000-0000-4000-8000-000000000001'})
    def heartbeat():
        ticks.append(1)
        if len(ticks)>1: raise RuntimeError('fence_lost')
    client=LunaClient('http://codex-runner:8091',heartbeat,time.monotonic()+30,transport=httpx.MockTransport(transport))
    with pytest.raises(RuntimeError,match='fence_lost'):
        client.invoke('synthesis_and_validation',{}, {'stages':[]})
    assert [x[0] for x in requests]==['POST','DELETE']
    client.close()


def test_transport_failure_waits_for_remote_watchdog(monkeypatch):
    sleeps=[]
    monkeypatch.setattr('app.deep_review.services.luna_client.time.sleep', sleeps.append)
    def transport(request):
        if request.method=='POST':
            return httpx.Response(202,json={'call_id':'00000000-0000-4000-8000-000000000001'})
        raise httpx.ConnectError('synthetic outage')
    client=LunaClient('http://codex-runner:8091',lambda:None,time.monotonic()+30,transport=httpx.MockTransport(transport))
    with pytest.raises(ModelInvocationError) as error:
        client.invoke('synthesis_and_validation',{}, {'stages':[]})
    assert error.value.code=='runner_unavailable'
    assert sleeps==[46]
    client.close()


def test_strict_locator_schema_keeps_authority_shapes():
    authority = json.loads((RUNNER.parents[1]/'backend/app/deep_review/contracts/bidops.deep-review-stage.v2.json').read_text())
    schema = runner.output_schema(authority)
    locator = schema['$defs']['evidence']['properties']['locator']
    assert len(locator['anyOf']) == 5
    assert '--json' in runner.argv(Path('/tmp/s'), Path('/tmp/o'), Path('/tmp/w'))
    def check(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert set(node['required']) == set(node['properties'])
                assert node['additionalProperties'] is False
            for value in node.values(): check(value)
        elif isinstance(node, list):
            for value in node: check(value)
    check(schema)


def test_schema_error_is_not_classified_from_prompt_words():
    assert runner.error_code('Authentication smoke test. ERROR: Invalid schema for response_format') == 'schema_invalid'
    assert runner.error_code('authentication diagnostic') == 'runner_failed'


def test_assumption_contract_uses_fixed_schema_and_same_model(monkeypatch):
    import hashlib
    from uuid import uuid4
    schema_path = RUNNER.parents[1] / 'backend/app/deep_review/contracts/bidops.assumption-stage.v1.json'
    authority = json.loads(schema_path.read_text())
    assert runner.output_schema(authority) == runner.cli_schema(authority)
    prompt = 'synthetic-only'
    call_id = str(uuid4())
    seen = []
    def transport(request):
        if request.method == 'POST':
            seen.append(json.loads(request.content))
            return httpx.Response(202, json={'call_id': call_id})
        if request.method == 'DELETE':
            return httpx.Response(200, json={})
        return httpx.Response(200, json={'status':'completed','raw_response':'{"sections":[]}',
            'cli_version':luna_identity.CLI_VERSION,'input_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'latency_ms':1})
    client=LunaClient('http://codex-runner:8091',lambda:None,time.monotonic()+60,transport=httpx.MockTransport(transport))
    try:
        result=client.invoke_prompt(prompt,contract='assumption-stage-v1')
        assert seen == [{'prompt':prompt,'contract':'assumption-stage-v1'}]
        assert result.model == luna_identity.MODEL
        assert result.structured_output == {'sections':[]}
    finally:
        client.close()
