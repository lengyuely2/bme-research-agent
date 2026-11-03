"""BME boundary + actual local workflow; all fixtures synthetic, no cloud calls."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import config
from caelo_core.agent.permissions import PermissionGate
from caelo_core.agent.session import AgentSession
from caelo_core.agent.workspace import Workspace
from caelo_core.bme.controller import Controller, definitions, public_error
from caelo_core.bme.engine.safety import SafetyError
from caelo_core.providers.errors import ErrorCategory, ProviderError


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data = tmp_path / 'app' / 'data'
    data.mkdir(parents=True)
    original = config.DATA_DIR
    for name in ('CONFIG_FILE', 'SETTINGS_FILE', 'AUTH_FILE', 'CHATS_FILE',
                 'PERMISSIONS_FILE', 'HISTORY_DB_FILE', 'HISTORY_DIR', 'PROJECT_DOCS_DIR',
                 'MCP_FILE', 'COMMANDS_FILE', 'HOOKS_FILE', 'AUDIT_LOG_FILE', 'SKILLS_DIR',
                 'SUBAGENTS_FILE', 'WORKTREES_DIR', 'PACKAGES_FILE', 'TEMPLATES_DIR'):
        value = getattr(config, name, None)
        if isinstance(value, Path):
            monkeypatch.setattr(config, name, data / value.name)
    monkeypatch.setattr(config, 'DATA_DIR', data)
    for key in ('OPENAI_API_KEY', 'XAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    # Unexpected cloud/network access is a test failure.
    import requests
    monkeypatch.setattr(requests.Session, 'request', lambda *a, **k: pytest.fail('Unexpected network access'))
    controller = Controller()
    source = tmp_path / 'experiment'
    source.mkdir()
    (source / 'notes.txt').write_text('Synthetic experimental notes. No patient data.', encoding='utf-8')
    controller.select_source(source)
    yield controller, source
    controller.close()


def session(controller, approvals=None, llm=None):
    events = []
    s = AgentSession(Workspace(str(controller.workspace.source)), PermissionGate(),
                     llm or (lambda *a, **k: {'role': 'assistant', 'content': 'done'}),
                     lambda: 'non-secret-test-marker', 'https://api.openai.com/v1',
                     events.append, lambda *a: approvals.append(a) or 'accept' if approvals is not None else 'reject',
                     bme_provider=lambda: controller, provider_id_provider=lambda: 'openai')
    return s, events


def tool_call(s, name, args, mode='bypass'):
    s._mode = mode
    s._handle_tool_call({'id': 'c1', 'function': {'name': name, 'arguments': json.dumps(args)}}, lambda: False)
    return s.history[-1]['content']


@pytest.mark.parametrize('mode', ['ask', 'plan', 'accept-edits', 'bypass'])
def test_hallucinated_tools_cannot_bypass_boundary(isolated, mode):
    c, source = isolated
    before = (source / 'notes.txt').read_bytes()
    s, events = session(c)
    advertised = {t['function']['name'] for t in s._all_tools()}
    assert 'run_command' not in advertised and 'bme_inspect_table' in advertised
    for name, args in [
        ('write_file', {'path': 'notes.txt', 'content': 'overwritten'}),
        ('edit_file', {'path': 'notes.txt', 'old_string': 'Synthetic', 'new_string': 'wrong'}),
        ('run_command', {'command': 'python -c "raise SystemExit(9)"'}),
        ('delegate', {'tasks': []}), ('web_fetch', {'url': 'https://example.org'}),
        ('mcp__thirdparty', {}), ('lsp', {'action': 'hover', 'path': 'notes.txt'}),
    ]:
        assert tool_call(s, name, args, mode).startswith('Error:')
    assert (source / 'notes.txt').read_bytes() == before
    assert sorted(p.name for p in source.iterdir()) == ['notes.txt']


def test_loop_inspects_then_returns_result_and_persists_no_key(isolated):
    c, source = isolated
    calls = []
    def llm(key, base, messages, model, temperature, tools, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'read1', 'function': {'name': 'bme_read_document', 'arguments': '{"file":"notes.txt"}'}}]}
        assert 'Synthetic experimental notes' in messages[-1]['content']
        kwargs['on_text']('Read the synthetic notes.')
        return {'role': 'assistant', 'content': 'Read the synthetic notes.'}
    s, events = session(c, llm=llm)
    s.run_turn('Read notes.txt', 'account-model')
    assert len(calls) == 2
    assert any(e['type'] == 'assistant_done' for e in events)
    assert not any(e['type'] == 'approval_request' for e in events)
    from caelo_core.agent import sessions
    sessions.save(id='test1', cwd=str(source), history=s.history, model='account-model', provider='openai')
    loaded = sessions.load('test1')
    assert loaded['history'][-1]['content'] == 'Read the synthetic notes.'
    assert 'non-secret-test-marker' not in sessions.session_path('test1').read_text(encoding='utf-8')


def test_plot_roundtrip_stats_exclusions_unique_outputs(isolated):
    c, source = isolated
    sample = c.workspace.samples / 'biosensor_demo.csv'
    digest = hashlib.sha256(sample.read_bytes()).hexdigest()
    r = c.call('bme_inspect_table', {'file': 'samples/biosensor_demo.csv'})
    assert r['profile']['rows'] == 15
    plan = r['suggested_plan']
    assert 'raw_rows' not in r
    review = c.call('bme_review_chart', {'dataset_id': r['dataset_id'], 'plan': plan})
    assert review['used'] == 15 and review['excluded'] == 0
    assert len(review['summary']) == 5
    assert all(row['n'] == 3 for row in review['summary'])
    blank = review['summary'][0]
    assert blank['mean'] == pytest.approx(0.04)
    assert blank['sd'] == pytest.approx(0.01)
    with pytest.raises(SafetyError):
        c.call('bme_review_chart', {'dataset_id': r['dataset_id'], 'plan': {**plan, 'exclude_rows': '1'}})
    a = c.call('bme_export_chart', {'review_id': review['review_id']})
    b = c.call('bme_export_chart', {'review_id': review['review_id']})
    assert a['png'] != b['png']
    with zipfile.ZipFile(a['result_zip']) as z:
        assert any(n.endswith('.svg') for n in z.namelist())
        assert any(n.endswith('.json') for n in z.namelist())
    assert Path(a['png']).read_bytes().startswith(b'\x89PNG')
    assert hashlib.sha256(sample.read_bytes()).hexdigest() == digest
    assert (source / 'notes.txt').read_text().startswith('Synthetic')


def test_only_generated_outputs_need_approval_even_bypass(isolated):
    c, _ = isolated
    s, _ = session(c)
    assert tool_call(s, 'bme_save_draft', {'text': 'demo', 'extension': 'py'}).startswith('Error:')
    assert not list(c.output.glob('draft-*'))
    approved = []
    s, _ = session(c, approved)
    value = json.loads(tool_call(s, 'bme_save_draft', {'text': 'raise Exception("never run")', 'extension': 'py'}))
    assert value['executed'] is False and len(approved) == 1
    assert Path(value['path']).exists()
    assert tool_call(s, 'bme_save_draft', {'text': 'demo', 'extension': 'py'}, 'plan').startswith('Error:')


def test_path_overlap_traversal_hardlink_and_scope_change(isolated, tmp_path):
    c, source = isolated
    for path in ['../notes.txt', str(source / 'notes.txt'), 'C:\\Windows\\win.ini']:
        with pytest.raises(SafetyError):
            c.call('bme_read_document', {'file': path})
    with pytest.raises(SafetyError):
        c.select_source(c.output.parent)
    (source / 'alias.txt').hardlink_to(source / 'notes.txt')
    with pytest.raises(SafetyError):
        c.call('bme_read_document', {'file': 'alias.txt'})
    c.begin_turn()
    with pytest.raises(SafetyError): c.select_source(source)
    with pytest.raises(SafetyError): c.begin_turn()
    c.end_turn()
    c.select_source(source)


def test_pdf_and_restartable_monitor(isolated):
    c, _ = isolated
    doc = c.call('bme_read_document', {'file': 'samples/paper_demo.pdf', 'page': 1})
    assert doc['citation'].endswith('P001]') and doc['pages'] == 2
    img = c.call('bme_paper_page', {'file': 'samples/paper_demo.pdf', 'page': 2})
    assert img['_image'].startswith(b'\x89PNG')
    for _ in range(2):
        assert c.call('bme_start_image_monitor', {})['running']
        c.workspace.stop_monitor()
        assert not c.workspace.monitor_thread.is_alive()
    assert c.call('bme_image_monitor_events', {}) == {'running': False, 'events': []}


def test_router_auth_and_native_bypass_routes_absent(isolated):
    from caelo_core.server import create_app
    app = create_app(token='test-token')
    with TestClient(app) as client:
        assert client.get('/bme/status').status_code == 401
        client.headers['Authorization'] = 'Bearer test-token'
        assert client.get('/bme/status').status_code == 200
        assert client.get('/bme/models').json() == {'models': [], 'configured': False}
        for path in ['/fs/write', '/terminal', '/git/commit', '/mcp', '/hooks', '/packages', '/agent/undo']:
            assert client.post(path, json={}).status_code == 404
        assert client.post('/bme/tool', json={'name': 'run_command', 'arguments': {}}).status_code == 400
        assert client.post('/bme/tool', json={'name': 'bme_list_sources', 'arguments': {}, 'extra': 1}).status_code == 422
        r = client.post('/bme/tool', json={'name': 'bme_inspect_table', 'arguments': {'file': 'samples/biosensor_demo.csv'}}).json()
        review = client.post('/bme/tool', json={'name': 'bme_review_chart', 'arguments': {'dataset_id': r['dataset_id'], 'plan': r['suggested_plan']}}).json()
        assert client.get('/bme/preview/' + review['review_id']).json()['image_uri'].startswith('data:image/png;base64,')
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/agent/stream?token=wrong'):
                pass


def test_websocket_account_model_responses_tools_history(isolated, monkeypatch):
    from caelo_core.server import create_app
    from caelo_core.providers.openai.tools import OpenAIAgentTools
    import requests
    c, source = isolated
    wire = []
    marker = 'synthetic-not-a-real-api-key'
    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_lines(self, **kwargs):
            result = ({'type': 'function_call', 'call_id': 'wirecall1', 'name': 'bme_read_document',
                       'arguments': '{"file":"notes.txt"}'} if len(wire) == 1 else
                      {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Synthetic evidence read.'}]})
            yield ('data: ' + json.dumps({'type': 'response.completed', 'response': {
                'output': [result], 'usage': {'input_tokens': 100, 'output_tokens': 10}}})).encode()
    def post(url, **kwargs):
        assert url == 'https://api.openai.com/v1/responses'
        payload = kwargs['json']; wire.append(payload)
        assert payload['store'] is False and payload['model'] == 'gpt-account-new-id'
        assert all(t['name'].startswith('bme_') or t['name'] == 'update_plan' for t in payload['tools'])
        if len(wire) == 2:
            outputs = [x for x in payload['input'] if x.get('type') == 'function_call_output']
            assert outputs and 'Synthetic experimental notes' in outputs[0]['output']
        return Response(payload)
    monkeypatch.setattr(requests, 'post', post)
    app = create_app(token='test-token')
    with TestClient(app) as client:
        backend = app.state.backend
        class Provider:
            agent = OpenAIAgentTools(lambda: marker)
            def available_model_ids(self): return ('gpt-account-new-id',)
        monkeypatch.setattr(backend, 'get_provider', lambda _: Provider())
        monkeypatch.setattr(backend, 'get_openai_api_key', lambda: marker)
        with client.websocket_connect('/agent/stream?token=test-token') as ws:
            assert ws.receive_json()['type'] == 'session'
            ws.send_json({'type': 'workspace', 'path': str(source)})
            assert ws.receive_json()['type'] == 'workspace'
            ws.send_json({'type': 'message', 'provider': 'openai', 'model': 'gpt-account-new-id', 'text': 'Read notes.txt'})
            events = []
            while True:
                e = ws.receive_json(); events.append(e)
                if e['type'] == 'done': break
            assert not any(e['type'] == 'error' for e in events), events
            assert any(e['type'] == 'tool_result' and e['ok'] for e in events)
            assert any(e['type'] == 'assistant_done' and e['content'] == 'Synthetic evidence read.' for e in events)
        assert len(wire) == 2
        saved = list((config.DATA_DIR / 'sessions').glob('*.json'))
        assert len(saved) == 1 and marker not in saved[0].read_text(encoding='utf-8')


def test_safe_errors_keep_diagnosis_without_request_secrets():
    err = ProviderError('raw API key must never appear', provider='openai', category=ErrorCategory.QUOTA,
                        code='insufficient_quota', status_code=429)
    result = public_error(err)
    assert 'balance' in result and '429' in result and 'insufficient_quota' in result
    assert 'raw API key' not in result


def test_manual_balance_validated_persisted_and_never_inferred(isolated):
    from caelo_core.bme.billing import Balance, read_balance, save_balance
    from pydantic import ValidationError
    assert read_balance()['amount'] is None
    first = save_balance(Balance(amount=12.34, currency='USD'))
    assert first['source'] == 'manual' and first['recorded_at']
    assert read_balance()['amount'] == 12.34
    for bad in [-1, float('nan'), float('inf'), 1_000_001]:
        with pytest.raises(ValidationError): Balance(amount=bad)
    assert read_balance()['amount'] == 12.34
    save_balance(Balance(amount=None))
    assert read_balance()['amount'] is None


def test_image_monitor_delivers_stable_metadata_without_network(isolated):
    import time
    from PIL import Image
    c, source = isolated
    c.call('bme_start_image_monitor', {})
    Image.new('RGB', (16, 16), 'green').save(source / 'synthetic-new-image.png')
    deadline, events = time.monotonic() + 7, []
    while time.monotonic() < deadline and not events:
        time.sleep(0.2)
        events = c.call('bme_image_monitor_events', {})['events']
    assert len(events) == 1 and events[0]['name'] == 'synthetic-new-image.png'
    assert set(events[0]) == {'name', 'bytes', 'mtime_ns'}
    assert not c.call('bme_image_monitor_events', {})['events']
