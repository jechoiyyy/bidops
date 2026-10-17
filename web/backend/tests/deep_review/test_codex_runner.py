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
    assert luna_identity.COMPANY_POLICY_IDENTITIES == frozenset({
        'analysis-policy-luna-demo-v1', 'analysis-policy-luna-hp-v1', 'analysis-policy-luna-rl-v1',
        'analysis-policy-luna-rl-v2', 'analysis-policy-luna-rl-v3', 'analysis-policy-luna-rl-v4',
        'analysis-policy-luna-rl-v5', 'analysis-policy-luna-rl-v6',
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


# --- RL-03 card-v1 runner contracts (spec "인터페이스", plan STEP-001) -------------------

CONTRACTS_DIR = RUNNER.parents[1] / 'backend/app/deep_review/contracts'
CARD_CONTRACT_FILES = {
    'card-extract-v1': 'bidops.requirement-extract.v1.json',
    # 결정 B33: policy v4 extract output (no concept_candidates/operator, kind x unit branches).
    'card-extract-v2': 'bidops.requirement-extract.v2.json',
    'card-role-v1': 'bidops.verdict-role.v1.json',
    'card-synthesis-v1': 'bidops.practitioner-verdict.v1.json',
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
}


def test_card_contracts_map_to_fixed_image_schema_files():
    assert runner.CONTRACT_SCHEMA_PATHS == {
        'deep-review-stage-v2': Path('/app/stage.json'),
        'assumption-stage-v1': Path('/app/assumption.json'),
        'card-extract-v1': Path('/app/card-extract.json'),
        'card-extract-v2': Path('/app/card-extract-v2.json'),
        'card-role-v1': Path('/app/card-role.json'),
        'card-synthesis-v1': Path('/app/card-synthesis.json'),
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
                     for name, filename in CARD_CONTRACT_FILES.items()})
    assert copies == expected
    # The client allowlist is the same closed set and validates with the same files.
    from app.deep_review import contracts
    from app.deep_review.services.luna_client import CONTRACT_SCHEMAS
    assert set(CONTRACT_SCHEMAS) == set(runner.CONTRACT_SCHEMA_PATHS)
    assert CONTRACT_SCHEMAS['deep-review-stage-v2'] == 'deep-review-stage-v2'
    assert CONTRACT_SCHEMAS['assumption-stage-v1'] is None
    for name, filename in CARD_CONTRACT_FILES.items():
        assert contracts.SCHEMA_FILES[CONTRACT_SCHEMAS[name]] == filename
        assert (CONTRACTS_DIR / filename).is_file()
    assert contracts.SCHEMA_FILES['card-analysis-input'] == 'bidops.card-analysis-input.v1.json'


@pytest.mark.parametrize('name', sorted(CARD_CONTRACT_FILES))
def test_card_output_schema_stays_strict_and_typed(name):
    authority = json.loads((CONTRACTS_DIR / CARD_CONTRACT_FILES[name]).read_text())
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
    for name in ('bidops.requirement-extract.v1.json', 'bidops.requirement-extract.v2.json',
                 'bidops.verdict-role.v1.json', 'bidops.practitioner-verdict.v1.json'):
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
