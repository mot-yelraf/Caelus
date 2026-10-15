import io
import json
import subprocess
from types import SimpleNamespace

import pytest

from caelus import gateway_recovery as recovery


@pytest.mark.parametrize('reply', [
    SimpleNamespace(returncode=1, stdout=''),
    SimpleNamespace(returncode=0, stdout='not JSON'),
    SimpleNamespace(returncode=0, stdout='[]'),
    SimpleNamespace(returncode=0, stdout='{"error": "No route to host"}'),
    SimpleNamespace(returncode=0, stdout='x' * (recovery.MAX_RESPONSE_BYTES + 1)),
])
def test_worker_failures_are_reported(monkeypatch, reply):
    monkeypatch.setattr(recovery.subprocess, 'run', lambda *args, **kwargs: reply)
    with pytest.raises((RuntimeError, ValueError)):
        recovery.request_in_fresh_process('http://gw.local', 'get_livedata_info', {})


def test_worker_uses_current_interpreter_and_a_hard_timeout(monkeypatch):
    def run(args, **kwargs):
        assert args == [recovery.sys.executable, '-m', 'caelus.gateway_recovery']
        assert kwargs['timeout'] == 8
        assert kwargs['capture_output']
        assert json.loads(kwargs['input'])['params'] == {'page': 1}
        assert (kwargs['cwd'] / 'caelus/gateway_recovery.py').is_file()
        return SimpleNamespace(returncode=0, stdout='{"payload": []}')

    monkeypatch.setattr(recovery.subprocess, 'run', run)
    assert recovery.request_in_fresh_process('http://gw.local', 'get_sensors_info', {'page': 1}) == []


def test_worker_timeout_is_propagated(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired('worker', 8)

    monkeypatch.setattr(recovery.subprocess, 'run', run)
    with pytest.raises(subprocess.TimeoutExpired):
        recovery.request_in_fresh_process('http://gw.local', 'get_livedata_info', {})


@pytest.mark.parametrize('oversized', [False, True])
def test_worker_reads_bounded_json_and_closes_response(monkeypatch, capsys, oversized):
    closed = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

        def raise_for_status(self):
            pass

        def iter_content(self, **kwargs):
            yield b'x' * (recovery.MAX_RESPONSE_BYTES + 1) if oversized else b'{"rain": []}'

    def get(url, **kwargs):
        assert url == 'http://gw.local/get_livedata_info'
        assert kwargs['timeout'] == 5
        assert kwargs['stream']
        assert not kwargs['allow_redirects']
        return Response()

    monkeypatch.setattr(recovery.requests, 'get', get)
    monkeypatch.setattr(recovery.sys, 'stdin', io.StringIO(json.dumps({
        'base_url': 'http://gw.local', 'endpoint': 'get_livedata_info', 'params': {},
    })))
    recovery.main()
    reply = json.loads(capsys.readouterr().out)
    assert closed == [True]
    if oversized:
        assert 'unexpectedly large' in reply['error']
    else:
        assert reply['payload'] == {'rain': []}


def test_worker_rejects_write_endpoints(monkeypatch, capsys):
    monkeypatch.setattr(recovery.sys, 'stdin', io.StringIO(json.dumps({
        'base_url': 'http://gw.local', 'endpoint': 'set_network_info', 'params': {},
    })))
    recovery.main()
    assert 'Unsupported' in json.loads(capsys.readouterr().out)['error']
