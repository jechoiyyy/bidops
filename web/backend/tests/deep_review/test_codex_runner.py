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
from app.core.model_client import ModelInvocationError

RUNNER = Path(__file__).resolve().parents[3] / 'codex-runner' / 'runner.py'
spec = importlib.util.spec_from_file_location('bidops_codex_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_fixed_argv_and_schema():
    args = runner.argv(Path('/tmp/schema'), Path('/tmp/out'), Path('/tmp/work'))
    assert '--ignore-user-config' in args and '--ignore-rules' in args and '--ephemeral' in args
    assert args[args.index('--model')+1] == 'gpt-5.6-luna'
    assert 'model_reasoning_effort="xhigh"' in args
    assert args[args.index('--sandbox')+1] == 'read-only'
    assert 'resume' not in args and 'shell' not in args
    # Compare with installed CLI help without sending input or reading auth.
    help_text = subprocess.run(['codex','exec','--help'], capture_output=True, text=True, check=True).stdout
    for flag in ('--ignore-user-config','--ignore-rules','--ephemeral','--output-schema','--skip-git-repo-check'):
        assert flag in help_text


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
