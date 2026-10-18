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
    # RL-03 spec "정책 행·선택": the card-v1 identity joins the company identities.
    assert luna_identity.RL_POLICY_IDENTITY == 'analysis-policy-luna-rl-v1'
    # 결정 B23: the v2 card identity (selector card-sections-v2) joins v1; the runner is unchanged.
    assert luna_identity.RL_POLICY_IDENTITY_V2 == 'analysis-policy-luna-rl-v2'
    # 결정 B30: the v3 card identity (selector card-sections-v3, extract contract) joins; runner unchanged.
    assert luna_identity.RL_POLICY_IDENTITY_V3 == 'analysis-policy-luna-rl-v3'
    # 결정 B33: the v4 card identity (extract output contract requirement-extract.v2).
    assert luna_identity.RL_POLICY_IDENTITY_V4 == 'analysis-policy-luna-rl-v4'
    # 결정 B35: v5 changes only the extract instruction (same card-extract-v2 contract; runner unchanged).
    assert luna_identity.RL_POLICY_IDENTITY_V5 == 'analysis-policy-luna-rl-v5'
    # 결정 B37: v6 changes only the extract instruction (same card-extract-v2 contract; runner unchanged).
    assert luna_identity.RL_POLICY_IDENTITY_V6 == 'analysis-policy-luna-rl-v6'
    # 결정 B51: v7 changes only the synthesis instruction (item isolation; same contracts; runner unchanged).
    assert luna_identity.RL_POLICY_IDENTITY_V7 == 'analysis-policy-luna-rl-v7'
    # 결정 B53: v8 adds one role/synthesis evidence sentence (same contracts; runner unchanged).
    assert luna_identity.RL_POLICY_IDENTITY_V8 == 'analysis-policy-luna-rl-v8'
    # 결정 B55: v9 answers synthesis contract card-synthesis-v2 (runner image gains its schema file).
    assert luna_identity.RL_POLICY_IDENTITY_V9 == 'analysis-policy-luna-rl-v9'
    assert luna_identity.COMPANY_POLICY_IDENTITIES == frozenset({
        'analysis-policy-luna-demo-v1', 'analysis-policy-luna-hp-v1', 'analysis-policy-luna-rl-v1',
        'analysis-policy-luna-rl-v2', 'analysis-policy-luna-rl-v3', 'analysis-policy-luna-rl-v4',
        'analysis-policy-luna-rl-v5', 'analysis-policy-luna-rl-v6', 'analysis-policy-luna-rl-v7',
        'analysis-policy-luna-rl-v8', 'analysis-policy-luna-rl-v9',
    })
    # RL-04 STEP-001: the proposal identity is its own set, never a company deep-review identity.
    assert luna_identity.PROPOSAL_POLICY_IDENTITY == 'proposal-policy-luna-v1'
    assert luna_identity.PROPOSAL_POLICY_IDENTITIES == frozenset({'proposal-policy-luna-v1'})
    assert not luna_identity.PROPOSAL_POLICY_IDENTITIES & luna_identity.COMPANY_POLICY_IDENTITIES
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


# --- RL-03 card-v1 runner contracts (spec "인터페이스", plan STEP-001) -------------------

CONTRACTS_DIR = RUNNER.parents[1] / 'backend/app/deep_review/contracts'
CARD_CONTRACT_FILES = {
    'card-extract-v1': 'bidops.requirement-extract.v1.json',
    # 결정 B33: policy v4 extract output (no concept_candidates/operator, kind x unit branches).
    'card-extract-v2': 'bidops.requirement-extract.v2.json',
    'card-role-v1': 'bidops.verdict-role.v1.json',
    'card-synthesis-v1': 'bidops.practitioner-verdict.v1.json',
    # 결정 B55: policy v9 synthesis output (no blocking_condition_ids; code computes them).
    'card-synthesis-v2': 'bidops.practitioner-verdict.v2.json',
}
#: RL-04 STEP-001 (spec "인터페이스"): the proposal section runner contract.
PROPOSAL_CONTRACT_FILES = {
    'proposal-section-v1': 'bidops.proposal-section.v1.json',
}
SHA = 'a' * 64
EVIDENCE = {'source_sha256': SHA, 'block_key': 'b1', 'quote': '상주 인력 3명'}
CARD_OUTPUTS = {
    'card-extract-v1': {'schema_version': 'bidops.requirement-extract.v1', 'items': [{
        'unit_id': 'card:%s:0:SFR-001' % SHA, 'type': '인력', 'normalized_requirement': '상주 인력 3명 이상',
        'mandatory': True, 'constraints': [{
            'kind': 'count', 'value': 3, 'unit': 'person', 'operator': 'gte', 'fact_key': 'staff:onsite',
            'quote': '상주 인력 3명', 'locator': {'source_sha256': SHA, 'block_key': 'b1'}}],
        'concept_candidates': [], 'unknowns': [], 'evidence': [EVIDENCE]}]},
    'card-extract-v2': {'schema_version': 'bidops.requirement-extract.v2', 'items': [{
        'unit_id': 'card:%s:0:SFR-001' % SHA, 'type': '인력', 'normalized_requirement': '상주 인력 3명 이상',
        'mandatory': True, 'constraints': [{
            'kind': 'count', 'value': 3, 'unit': 'person', 'fact_key': None,
            'quote': '상주 인력 3명', 'locator': {'source_sha256': SHA, 'block_key': 'b1'}}],
        'unknowns': [], 'evidence': [EVIDENCE]}]},
    'card-role-v1': {'schema_version': 'bidops.verdict-role.v1', 'role': 'operations_risk',
                     'unit_findings': [{'unit_id': 'u1', 'assessment': 'unknown', 'reason': '확인 필요',
                                        'evidence_refs': [EVIDENCE]}],
                     'cautions': [], 'evidence_refs': [EVIDENCE]},
    'card-synthesis-v1': {'schema_version': 'bidops.practitioner-verdict.v1', 'verdict': '판단 불가',
                          'reason': '확인 필요 항목이 남아 있다.', 'blocking_condition_ids': [], 'cautions': [],
                          'next_actions': [{'unit_id': 'u1', 'owner': None, 'action': '상주 인력 확인',
                                            'evidence_refs': [EVIDENCE]}]},
    'card-synthesis-v2': {'schema_version': 'bidops.practitioner-verdict.v2', 'verdict': '판단 불가',
                          'reason': '확인 필요 항목이 남아 있다.', 'cautions': [],
                          'next_actions': [{'unit_id': 'u1', 'owner': None, 'action': '상주 인력 확인',
                                            'evidence_refs': [EVIDENCE]}]},
}


def test_card_contracts_map_to_fixed_image_schema_files():
    assert runner.CONTRACT_SCHEMA_PATHS == {
        'deep-review-stage-v2': Path('/app/stage.json'),
        'assumption-stage-v1': Path('/app/assumption.json'),
        'card-extract-v1': Path('/app/card-extract.json'),
        'card-extract-v2': Path('/app/card-extract-v2.json'),
        'card-role-v1': Path('/app/card-role.json'),
        'card-synthesis-v1': Path('/app/card-synthesis.json'),
        'card-synthesis-v2': Path('/app/card-synthesis-v2.json'),
        # RL-04 STEP-001: the proposal section contract (5th registration place = this map).
        'proposal-section-v1': Path('/app/proposal-section.json'),
    }
    # Every image path is COPYed from exactly the authority contract file.
    dockerfile = (RUNNER.parent / 'Dockerfile').read_text()
    copies = {}
    for line in dockerfile.splitlines():
        if line.startswith('COPY web/backend/app/deep_review/contracts/'):
            _copy, source, target = line.split()
            copies[target] = Path(source).name
    expected = {'/app/stage.json': 'bidops.deep-review-stage.v2.json',
                '/app/assumption.json': 'bidops.assumption-stage.v1.json'}
    expected.update({str(runner.CONTRACT_SCHEMA_PATHS[name]): filename
                     for name, filename in {**CARD_CONTRACT_FILES, **PROPOSAL_CONTRACT_FILES}.items()})
    assert copies == expected
    # The client allowlist is the same closed set and validates with the same files.
    from app.deep_review import contracts
    from app.deep_review.services.luna_client import CONTRACT_SCHEMAS
    assert set(CONTRACT_SCHEMAS) == set(runner.CONTRACT_SCHEMA_PATHS)
    assert CONTRACT_SCHEMAS['deep-review-stage-v2'] == 'deep-review-stage-v2'
    assert CONTRACT_SCHEMAS['assumption-stage-v1'] is None
    for name, filename in {**CARD_CONTRACT_FILES, **PROPOSAL_CONTRACT_FILES}.items():
        assert contracts.SCHEMA_FILES[CONTRACT_SCHEMAS[name]] == filename
        assert (CONTRACTS_DIR / filename).is_file()
    assert contracts.SCHEMA_FILES['card-analysis-input'] == 'bidops.card-analysis-input.v1.json'
    assert CONTRACT_SCHEMAS['proposal-section-v1'] == 'proposal-section'
    assert contracts.SCHEMA_FILES['proposal-input'] == 'bidops.proposal-input.v1.json'


@pytest.mark.parametrize('name', sorted({**CARD_CONTRACT_FILES, **PROPOSAL_CONTRACT_FILES}))
def test_card_output_schema_stays_strict_and_typed(name):
    authority = json.loads((CONTRACTS_DIR / {**CARD_CONTRACT_FILES, **PROPOSAL_CONTRACT_FILES}[name]).read_text())
    schema = runner.output_schema(authority)
    assert schema == runner.cli_schema(authority)

    def check(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert set(node['required']) == set(node['properties'])
                assert node['additionalProperties'] is False
                for child in node['properties'].values():
                    # cli_schema drops oneOf; every property must stay typed.
                    assert {'type', '$ref', 'anyOf', 'enum'} & set(child), child
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(schema)


def _handler_post(body):
    import io
    replies = []
    handler = runner.Handler.__new__(runner.Handler)
    raw = json.dumps(body).encode()
    handler.path = '/calls'
    handler.headers = {'Content-Length': str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    handler.reply = lambda code, data: replies.append((code, data))
    handler.do_POST()
    return replies


def test_runner_http_accepts_only_allowlisted_contracts(monkeypatch):
    started = []
    monkeypatch.setattr(runner.slot, 'start', lambda prompt, contract: started.append(contract) or 'call-1')
    for contract in ('/tmp/arbitrary.json', 'hp-extract-v1', 'card-extract-v3', 'CARD-ROLE-V1'):
        assert _handler_post({'prompt': 'synthetic-only', 'contract': contract}) == [(400, {})]
    assert _handler_post({'prompt': 'synthetic-only', 'contract': 'card-role-v1', 'schema': '/tmp/x'}) == [(400, {})]
    assert started == []
    for contract in sorted(CARD_CONTRACT_FILES):
        assert _handler_post({'prompt': 'synthetic-only', 'contract': contract}) == [(202, {'call_id': 'call-1'})]
    assert _handler_post({'prompt': 'synthetic-only'}) == [(202, {'call_id': 'call-1'})]
    assert started == [*sorted(CARD_CONTRACT_FILES), 'deep-review-stage-v2']


@pytest.mark.parametrize('name', sorted(CARD_CONTRACT_FILES))
def test_runner_slot_executes_the_card_contract_schema(monkeypatch, name):
    seen = []
    monkeypatch.setattr(runner, 'execute', lambda prompt, alive, *, schema_path: seen.append(schema_path) or {'status': 'failed', 'error_code': 'runner_failed'})
    slot = runner.Slot()
    assert slot.start('synthetic-only', name)
    deadline = time.monotonic() + 5
    while slot.running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == [runner.CONTRACT_SCHEMA_PATHS[name]]


def _card_client(prompt, raw_response, seen):
    import hashlib
    from uuid import uuid4
    call_id = str(uuid4())

    def transport(request):
        if request.method == 'POST':
            seen.append(json.loads(request.content))
            return httpx.Response(202, json={'call_id': call_id})
        if request.method == 'DELETE':
            return httpx.Response(200, json={})
        return httpx.Response(200, json={'status': 'completed', 'raw_response': raw_response,
                                         'cli_version': luna_identity.CLI_VERSION,
                                         'input_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                                         'latency_ms': 1})
    return LunaClient('http://codex-runner:8091', lambda: None, time.monotonic() + 60,
                      transport=httpx.MockTransport(transport))


@pytest.mark.parametrize('name', sorted(CARD_CONTRACT_FILES))
def test_client_sends_card_contract_and_validates_its_schema(name):
    prompt = 'synthetic-only'
    seen = []
    client = _card_client(prompt, json.dumps(CARD_OUTPUTS[name], ensure_ascii=False), seen)
    try:
        result = client.invoke_prompt(prompt, contract=name)
        assert seen == [{'prompt': prompt, 'contract': name}]
        assert result.structured_output == CARD_OUTPUTS[name]
        assert result.model == luna_identity.MODEL and result.provider == luna_identity.PROVIDER
    finally:
        client.close()
    # An extra key or a missing required key is schema_invalid; nothing is repaired.
    for broken in ({**CARD_OUTPUTS[name], 'extra': 1},
                   {key: value for key, value in CARD_OUTPUTS[name].items() if key != 'schema_version'}):
        client = _card_client(prompt, json.dumps(broken, ensure_ascii=False), [])
        try:
            with pytest.raises(ModelInvocationError) as error:
                client.invoke_prompt(prompt, contract=name)
            assert error.value.code == 'schema_invalid'
        finally:
            client.close()


def test_extract_schema_rejects_bool_as_number_and_unknown_unit():
    from app.deep_review.contracts import SchemaValidationError, validate_payload
    base = CARD_OUTPUTS['card-extract-v1']
    assert validate_payload(base, 'requirement-extract') == base
    for patch in ({'unit': 'won'}, {'operator': 'gt'}, {'kind': 'ratio'}, {'value': None}, {'value': ''}):
        broken = json.loads(json.dumps(base))
        broken['items'][0]['constraints'][0].update(patch)
        with pytest.raises(SchemaValidationError):
            validate_payload(broken, 'requirement-extract')
    flag = json.loads(json.dumps(base))
    flag['items'][0]['constraints'][0].update({'kind': 'boolean', 'value': True, 'unit': None})
    assert validate_payload(flag, 'requirement-extract') == flag
    no_evidence = json.loads(json.dumps(base))
    no_evidence['items'][0]['evidence'] = []
    with pytest.raises(SchemaValidationError):
        validate_payload(no_evidence, 'requirement-extract')


def test_client_rejects_arbitrary_contract_and_oversized_card_prompt_before_any_call():
    calls = []
    client = LunaClient('http://codex-runner:8091', lambda: None, time.monotonic() + 30,
                        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500)))
    try:
        for contract, prompt in (('/tmp/arbitrary.json', 'x'), ('hp-extract-v1', 'x'),
                                 ('card-extract-v1', 'x' * 100001)):
            with pytest.raises(ModelInvocationError) as error:
                client.invoke_prompt(prompt, contract=contract)
            assert error.value.code == 'prompt_rejected'
        assert calls == []
    finally:
        client.close()


def test_b27_failure_categories_and_json_event_errors():
    """결정 B27: `--json` errors arrive on stdout; the runner classifies them and logs only category names."""

    events = "\n".join([
        '{"type":"thread.started","thread_id":"x"}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"secret model output 429"}}',
        '{"type":"error","message":"You have hit your usage limit. Try again later."}',
        '{"type":"turn.failed","error":{"message":"stream disconnected before completion"}}',
        'not json',
    ])
    extracted = runner.event_errors(events)
    assert "usage limit" in extracted and "stream disconnected" in extracted
    assert "secret model output" not in extracted  # agent output is never scanned
    assert runner.failure_categories(extracted) == ["network", "usage_limit"]
    assert runner.error_code(extracted) == "runner_failed"
    assert runner.error_code(runner.event_errors('{"type":"error","message":"401 Unauthorized"}')) == "authentication_failed"
    assert runner.failure_categories("") == []


def test_b28_card_output_schemas_use_only_live_proven_keywords():
    """결정 B28: the decoded card schemas may use only keywords already accepted live (deep-review-stage-v2 set)."""

    import json as _json
    from pathlib import Path as _Path

    keywords = {
        'type', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'anyOf', '$ref', '$defs',
        'pattern', 'minLength', 'maxLength', 'minimum', 'maximum', 'minItems', 'maxItems', 'title',
    }
    vocabulary = keywords | {'const', 'oneOf', 'allOf', 'not', 'format', 'uniqueItems', 'prefixItems', 'contains',
                             'minProperties', 'maxProperties', 'patternProperties', 'propertyNames', 'if', 'then',
                             'else', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'dependentRequired'}

    def used(node, found, in_props=False):
        if isinstance(node, dict):
            for key, value in node.items():
                if not in_props and key in vocabulary:
                    found.add(key)
                used(value, found, in_props=(key in ('properties', '$defs')) and not in_props)
        elif isinstance(node, list):
            for item in node:
                used(item, found)

    contracts = _Path(__file__).resolve().parents[2] / 'app' / 'deep_review' / 'contracts'
    # RL-04 STEP-001: the proposal section schema is decoded by the same strict runner.
    for name in ('bidops.requirement-extract.v1.json', 'bidops.requirement-extract.v2.json',
                 'bidops.verdict-role.v1.json', 'bidops.practitioner-verdict.v1.json',
                 'bidops.practitioner-verdict.v2.json', 'bidops.proposal-section.v1.json'):
        found: set[str] = set()
        used(runner.output_schema(_json.loads((contracts / name).read_text())), found)
        assert found <= keywords, (name, sorted(found - keywords))


def test_b33_extract_v2_output_schema_keeps_strict_kind_unit_branches():
    """결정 B33: the runner decodes card-extract-v2 with one strict branch per constraint kind."""

    authority = json.loads((CONTRACTS_DIR / 'bidops.requirement-extract.v2.json').read_text())
    schema = runner.output_schema(authority)
    branches = schema['$defs']['constraint']['anyOf']
    assert [branch['$ref'] for branch in branches] == [
        '#/$defs/%s_constraint' % kind for kind in ('amount', 'duration', 'count', 'percentage', 'date', 'boolean', 'text')]
    units = {}
    for kind in ('amount', 'duration', 'count', 'percentage', 'date', 'boolean', 'text'):
        branch = schema['$defs']['%s_constraint' % kind]
        assert branch['additionalProperties'] is False
        assert set(branch['required']) == set(branch['properties']) == {
            'kind', 'value', 'unit', 'fact_key', 'quote', 'locator'}
        assert branch['properties']['kind'] == {'type': 'string', 'enum': [kind]}
        assert branch['properties']['fact_key'] == {'type': 'null'}
        units[kind] = branch['properties']['unit']
    assert units['count'] == {'type': ['string', 'null'], 'enum': ['person', None]}
    assert units['amount']['enum'] == ['KRW'] and units['date'] == {'type': 'null'}
    assert schema['$defs']['date_constraint']['properties']['value']['pattern'] == '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    item = schema['$defs']['extract']['properties']
    assert 'concept_candidates' not in item
    assert 'operator' not in schema['$defs']['text_constraint']['properties']
    assert schema['properties']['schema_version'] == {'enum': ['bidops.requirement-extract.v2']}
    # the client validates the same authority file and rejects count+day as schema_invalid (repairable)
    from app.deep_review.services.luna_client import CONTRACT_SCHEMAS
    assert CONTRACT_SCHEMAS['card-extract-v2'] == 'requirement-extract-v2'
    broken = json.loads(json.dumps(CARD_OUTPUTS['card-extract-v2']))
    broken['items'][0]['constraints'][0].update({'unit': 'day'})
    client = _card_client('synthetic-only', json.dumps(broken, ensure_ascii=False), [])
    try:
        with pytest.raises(ModelInvocationError) as error:
            client.invoke_prompt('synthetic-only', contract='card-extract-v2')
        assert error.value.code == 'schema_invalid'
    finally:
        client.close()


# --- RL-04 proposal-section-v1 runner contract (spec "문장 계약"·"입력 예산", STEP-001) ----------

PROPOSAL_SECTION = {
    'section_key': 'requirements', 'title': '요구사항 수행방안',
    'paragraphs': [{
        'paragraph_id': 'p1', 'heading': None,
        'sentences': [
            {'sentence_id': '3f1c2a4e-8b7d-4c1e-9a2b-5d6e7f8a9b0c', 'text': '상주 인력 요구에 맞춰 운영 조직을 둔다.',
             'kind': 'statement', 'placeholder_hint': None,
             'sources': [{'kind': 'requirement_unit', 'ref': 'card:%s:0:SFR-001' % SHA, 'quote': '상주 인력 3명'}]},
            {'sentence_id': '0a9b8c7d-6e5f-4a3b-8c1d-2e3f4a5b6c7d', 'text': '[투입 인력 수]',
             'kind': 'placeholder', 'placeholder_hint': '투입 인력 수', 'sources': []},
        ],
    }],
    'requirement_links': [{'unit_id': 'card:%s:0:SFR-001' % SHA, 'paragraph_id': 'p1'}],
}


def test_proposal_section_output_schema_is_strict_and_has_no_kind_conditions():
    """Strict decoding: closed objects, all keys required, nullables as type arrays; kind rules live in code."""

    authority = json.loads((CONTRACTS_DIR / 'bidops.proposal-section.v1.json').read_text())
    schema = runner.output_schema(authority)
    # cli_schema changes nothing but $schema/$id: the authority is already strict-shaped.
    assert schema == {key: value for key, value in authority.items() if key not in ('$schema', '$id')}
    assert schema['required'] == ['section_key', 'title', 'paragraphs', 'requirement_links']
    assert schema['$defs']['section_key']['enum'] == [
        'overview', 'track_record', 'strategy', 'requirements', 'operations_sla', 'organization']
    sentence = schema['$defs']['sentence']
    assert sentence['required'] == ['sentence_id', 'text', 'kind', 'sources', 'placeholder_hint']
    assert sentence['properties']['text'] == {'type': 'string', 'minLength': 1, 'maxLength': 400}
    assert sentence['properties']['kind']['enum'] == ['statement', 'placeholder', 'proposed_figure']
    assert sentence['properties']['placeholder_hint']['type'] == ['string', 'null']
    assert schema['$defs']['paragraph']['properties']['heading']['type'] == ['string', 'null']
    assert schema['$defs']['source']['properties']['kind']['enum'] == [
        'requirement_unit', 'company_fact', 'notice_meta']
    assert schema['$defs']['uuid']['pattern'].startswith('^[0-9a-fA-F]{8}-')
    # No conditional branches anywhere (spec: runner strips oneOf/conditions, proposal_validation decides).
    text = json.dumps(authority)
    for keyword in ('"oneOf"', '"allOf"', '"anyOf"', '"if"', '"then"', '"const"', '"uniqueItems"'):
        assert keyword not in text, keyword


def test_runner_accepts_and_executes_the_proposal_contract(monkeypatch):
    started = []
    monkeypatch.setattr(runner.slot, 'start', lambda prompt, contract: started.append(contract) or 'call-1')
    assert _handler_post({'prompt': 'synthetic-only', 'contract': 'proposal-section-v1'}) == [(202, {'call_id': 'call-1'})]
    for contract in ('proposal-section-v2', 'proposal-v1', 'PROPOSAL-SECTION-V1'):
        assert _handler_post({'prompt': 'synthetic-only', 'contract': contract}) == [(400, {})]
    assert started == ['proposal-section-v1']
    seen = []
    monkeypatch.setattr(runner, 'execute', lambda prompt, alive, *, schema_path: seen.append(schema_path) or {'status': 'failed', 'error_code': 'runner_failed'})
    slot = runner.Slot()
    assert slot.start('synthetic-only', 'proposal-section-v1')
    deadline = time.monotonic() + 5
    while slot.running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == [Path('/app/proposal-section.json')]


def test_client_sends_proposal_contract_and_validates_only_the_section_shape():
    prompt = 'synthetic-only'
    seen = []
    client = _card_client(prompt, json.dumps(PROPOSAL_SECTION, ensure_ascii=False), seen)
    try:
        result = client.invoke_prompt(prompt, contract='proposal-section-v1')
        assert seen == [{'prompt': prompt, 'contract': 'proposal-section-v1'}]
        assert result.structured_output == PROPOSAL_SECTION
    finally:
        client.close()
    sentence = ('paragraphs', 0, 'sentences', 0)

    def mutated(path, key, value):
        broken = json.loads(json.dumps(PROPOSAL_SECTION))
        node = broken
        for step in path:
            node = node[step]
        if value is KeyError:
            del node[key]
        else:
            node[key] = value
        return broken

    for broken in (
        {**PROPOSAL_SECTION, 'schema_version': 'x'},
        {key: value for key, value in PROPOSAL_SECTION.items() if key != 'requirement_links'},
        {**PROPOSAL_SECTION, 'section_key': 'pricing'},
        {**PROPOSAL_SECTION, 'paragraphs': []},
        mutated(sentence, 'text', '가' * 401),
        mutated(sentence, 'text', ''),
        mutated(sentence, 'kind', 'claim'),
        mutated(sentence, 'sentence_id', 's1'),
        mutated(sentence, 'placeholder_hint', KeyError),
        mutated(sentence, 'extra', 1),
        mutated(('paragraphs', 0, 'sentences', 0, 'sources', 0), 'kind', 'profile_fact'),
    ):
        client = _card_client(prompt, json.dumps(broken, ensure_ascii=False), [])
        try:
            with pytest.raises(ModelInvocationError) as error:
                client.invoke_prompt(prompt, contract='proposal-section-v1')
            assert error.value.code == 'schema_invalid'
        finally:
            client.close()
    # Kind-conditional rules are not schema rules: a statement without sources and a
    # placeholder with sources both decode; proposal_validation.py (STEP-004) rejects them.
    for loose in (mutated(sentence, 'sources', []),
                  mutated(('paragraphs', 0, 'sentences', 1), 'sources',
                          [{'kind': 'notice_meta', 'ref': 'title', 'quote': '사업'}])):
        client = _card_client(prompt, json.dumps(loose, ensure_ascii=False), [])
        try:
            assert client.invoke_prompt(prompt, contract='proposal-section-v1').structured_output == loose
        finally:
            client.close()


def test_proposal_prompt_limit_is_120000_characters_and_other_limits_are_unchanged():
    from app.deep_review.services import luna_client
    assert luna_client.PROMPT_MAX_CHARS == {'assumption-stage-v1': 160000, 'proposal-section-v1': 120000}
    assert luna_client.DEFAULT_PROMPT_MAX_CHARS == 100000
    calls = []
    client = LunaClient('http://codex-runner:8091', lambda: None, time.monotonic() + 30,
                        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500)))
    try:
        for contract, size in (('proposal-section-v1', 120001), ('card-role-v1', 100001),
                               ('deep-review-stage-v2', 100001), ('assumption-stage-v1', 160001)):
            with pytest.raises(ModelInvocationError) as error:
                client.invoke_prompt('x' * size, contract=contract)
            assert error.value.code == 'prompt_rejected'
        assert calls == []
        # Exactly at the limit the proposal prompt is sent (the fake runner then fails).
        with pytest.raises(ModelInvocationError) as error:
            client.invoke_prompt('x' * 120000, contract='proposal-section-v1')
        assert error.value.code == 'runner_unavailable'
        assert len(calls) == 1 and json.loads(calls[0].content)['contract'] == 'proposal-section-v1'
    finally:
        client.close()


PROPOSAL_INPUT = {
    'schema_version': 'bidops.proposal-input.v1', 'purpose': 'proposal',
    'execution_nonce': '3f1c2a4e-8b7d-4c1e-9a2b-5d6e7f8a9b0c', 'draft_id': '0a9b8c7d-6e5f-4a3b-8c1d-2e3f4a5b6c7d',
    'opportunity_id': 7, 'notice_id': 11, 'verdict_attempt_id': '1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e',
    'verdict_input_sha256': SHA,
    'company_binding': {'graph_version_id': '2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f', 'graph_sha256': SHA,
                        'profile_version_id': '3d4e5f6a-7b8c-4d9e-8f0a-1b2c3d4e5f6a', 'profile_sha256': SHA,
                        'ontology_version': 'rootlab-v2', 'ontology_sha256': SHA},
    'policy_sha256': SHA, 'model_name': 'gpt-6-luna', 'reasoning_effort': 'high', 'section_key': 'organization',
    'notice_meta': {'title': '홈페이지 고도화', 'agency': '한국폴리텍대학', 'deadline_at': None, 'method': None,
                    'estimated_price': '134700000.00'},
    'units': [{'unit_id': 'card:%s:0:SFR-001' % SHA, 'source_sha256': SHA,
               'document_version_id': '4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b',
               'structure_id': '5f6a7b8c-9d0e-4f1a-8b2c-3d4e5f6a7b8c',
               'manifest_id': '6a7b8c9d-0e1f-4a2b-9c3d-4e5f6a7b8c9d', 'kind': 'card', 'ordinal': 0,
               'normalized_id': 'SFR-001', 'section_kinds': [], 'blocks': [{'block_key': 'b1', 'text': '상주 인력 3명'}],
               'page_range': {'first': 3, 'last': 3}, 'mapping_status': 'mapped'}],
    'compares': [{'unit_id': 'card:%s:0:SFR-001' % SHA, 'fit_status': 'unknown', 'constraint_results': [
        {'constraint_index': 0, 'status': 'unknown', 'fact_ids': ['staff:onsite'], 'path_ids': [],
         'reason_code': 'proposed_fact'}], 'evidence_ids': [], 'reason_codes': ['proposed_fact']}],
    'verdict': {'verdict': '조건부 진행', 'reason': '상주 인력 확인 필요',
                'checklist': [{'key': 'staffing_onsite', 'status': 'unknown', 'evidence_refs': [EVIDENCE]}]},
    'company_facts': [{'fact_key': 'staff:design_publishing', 'type': 'staff', 'label': '디자인·퍼블리싱',
                       'value': {'available': 5, 'role': '디자인', 'total': None}}],
    'missing_facts': [{'fact_key': 'qual:credit_rating', 'status': 'proposed'}],
    'toc_reference': ['Ⅳ-2 수행조직', 'Ⅳ-3 보고·산출물'],
}


def test_proposal_input_contract_is_closed_and_missing_facts_carry_no_value():
    from app.deep_review.contracts import SchemaValidationError, validate_payload
    assert validate_payload(PROPOSAL_INPUT, 'proposal-input') == PROPOSAL_INPUT
    schema = json.loads((CONTRACTS_DIR / 'bidops.proposal-input.v1.json').read_text())
    # spec "생성 입력·정책·호출": the full frozen key set (input_sha256 target).
    assert set(schema['required']) == set(schema['properties']) == set(PROPOSAL_INPUT) == {
        'schema_version', 'purpose', 'execution_nonce', 'draft_id', 'opportunity_id', 'notice_id',
        'verdict_attempt_id', 'verdict_input_sha256', 'company_binding', 'policy_sha256', 'model_name',
        'reasoning_effort', 'section_key', 'notice_meta', 'units', 'compares', 'verdict', 'company_facts',
        'missing_facts', 'toc_reference'}
    assert schema['$defs']['missing_fact']['required'] == ['fact_key', 'status']
    for patch in (
        {'missing_facts': [{'fact_key': 'qual:credit_rating', 'status': 'proposed', 'value': 'BBB0'}]},
        {'missing_facts': [{'fact_key': 'qual:credit_rating', 'status': 'proposed', 'label': '신용등급'}]},
        {'missing_facts': [{'fact_key': 'qual:credit_rating', 'status': 'confirmed'}]},
        {'company_facts': [{'fact_key': 'x', 'type': 'staff', 'label': 'x', 'value': 1, 'status': 'confirmed'}]},
        {'purpose': 'deep_review'},
        {'section_key': 'pricing'},
        {'notes': '노트 본문'},
        {'notice_meta': {**PROPOSAL_INPUT['notice_meta'], 'demand_agency': 'x'}},
        {'toc_reference': []},
    ):
        with pytest.raises(SchemaValidationError):
            validate_payload({**PROPOSAL_INPUT, **patch}, 'proposal-input')
