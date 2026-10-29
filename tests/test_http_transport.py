"""Real loopback HTTP exercises multipart, cancellation and absolute deadlines."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests
from PySide6.QtWidgets import QApplication

from katip.application.session import Job
from katip.infrastructure.http_transport import HttpSession, execution_scope

_request = HttpSession.request


@pytest.fixture
def server(monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    observed = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            observed.append((self.path, dict(self.headers), body))
            if self.path == '/slow':
                time.sleep(.25)
            if self.path == '/disconnect':
                self.close_connection = True
                return
            status = int(self.path.rsplit('/', 1)[-1]) if self.path.startswith('/status/') else (429 if self.path == '/rate' else 200)
            self.send_response(status)
            payload = b'x' * 1024 if self.path == '/large' else b'{"text":"okay"}'
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            try:
                if self.path == '/drip':
                    for byte in b'{"text":"okay"}':
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(.02)
                    return
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError): pass
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(HttpSession, 'request', _request)
    yield SimpleNamespace(url=f'http://127.0.0.1:{httpd.server_port}', observed=observed, qapp=qapp)
    httpd.shutdown()
    httpd.server_close()
    thread.join(1)


def run_request(server, path='/', job=None, **kwargs):
    result = []
    def worker():
        try:
            with execution_scope(job):
                result.append(HttpSession().post(server.url + path, **kwargs))
        except Exception as exc:
            result.append(exc)
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(2)
    assert not thread.is_alive(), 'HTTP worker exceeded its deadline'
    return result[0]


def test_json_and_status_are_real_wire_contracts(server):
    response = run_request(server, '/rate', json={'language': 'tr'})
    assert response.status_code == 429
    assert response.json() == {'text': 'okay'}
    assert json.loads(server.observed[0][2]) == {'language': 'tr'}


def test_multipart_transfers_audio_and_form_fields(server):
    response = run_request(server, data={'model': 'whisper'},
                           files={'file': ('audio.wav', b'RIFF-sample', 'audio/wav')})
    assert response.status_code == 200
    _, headers, body = server.observed[0]
    assert headers['Content-Type'].startswith('multipart/form-data; boundary=')
    assert b'RIFF-sample' in body and b'whisper' in body


def test_stage_deadline_aborts_a_live_request(server):
    response = run_request(server, '/slow', json={}, timeout=.05)
    assert isinstance(response, requests.Timeout)


def test_cancel_aborts_in_flight_request(server):
    job = Job({})
    timer = threading.Timer(.05, job.cancelled.set)
    timer.start()
    try:
        response = run_request(server, '/slow', job=job, json={})
    finally:
        timer.join(1)
    assert isinstance(response, RuntimeError) and 'CANCELLED' in str(response)


@pytest.mark.parametrize('status', [401, 403, 404, 413, 429, 500, 503])
def test_http_status_is_not_hidden_by_qt_network_error(server, status):
    response = run_request(server, f'/status/{status}', json={})
    assert response.status_code == status


def test_continuous_response_bytes_cannot_extend_absolute_deadline(server):
    started = time.monotonic()
    response = run_request(server, '/drip', json={}, timeout=.08)
    assert isinstance(response, requests.Timeout)
    assert time.monotonic() - started < .5


def test_connection_closed_before_headers_is_a_safe_connection_error(server):
    response = run_request(server, '/disconnect', json={}, timeout=.5)
    assert isinstance(response, requests.ConnectionError)


def test_plain_body_and_oversized_response_are_bounded(server, monkeypatch):
    response = run_request(server, data=b'raw-body')
    assert response.status_code == 200 and server.observed[-1][2] == b'raw-body'
    monkeypatch.setattr('katip.infrastructure.http_transport.MAX_RESPONSE_BYTES', 128)
    response = run_request(server, '/large', json={})
    assert isinstance(response, requests.RequestException)


def test_transport_refuses_to_block_gui_thread(server):
    with pytest.raises(RuntimeError, match='background worker'):
        HttpSession().post(server.url, json={})


@pytest.mark.parametrize('path, kwargs, code, status', [
    ('/status/500', {'json': {}}, 'OK', 500),
    ('/slow', {'json': {}, 'timeout': .05}, 'NETWORK_TIMEOUT', 0),
    ('/disconnect', {'json': {}, 'timeout': .5}, 'NETWORK_CONNECTION', 0),
])
def test_each_request_logs_stage_timing_and_outcome_without_content(server, path, kwargs, code, status):
    from katip.diagnostics import Diagnostics
    job = Job({})
    job.diagnostics = Diagnostics()
    run_request(server, path, job=job, **kwargs)
    started, finished = job.diagnostics.snapshot()
    assert started['event'] == 'http_started' and started['host'] == '127.0.0.1'
    assert started['request_bytes'] == 2
    assert finished['event'] == 'http_finished' and finished['code'] == code
    assert finished['http_status'] == status and finished['duration_ms'] >= 0
    assert 'network_error' in finished and 'okay' not in json.dumps(job.diagnostics.snapshot())


def test_request_log_names_cancellation_and_upload_size(server, monkeypatch):
    from katip.diagnostics import Diagnostics
    job = Job({})
    job.diagnostics = Diagnostics()
    timer = threading.Timer(.05, job.cancelled.set)
    timer.start()
    try:
        run_request(server, '/slow', job=job, data={'model': 'whisper'},
                    files={'file': ('audio.wav', b'RIFF-sample', 'audio/wav')})
    finally:
        timer.join(1)
    started, finished = job.diagnostics.snapshot()
    assert started['request_bytes'] == len(b'RIFF-sample')
    assert finished['code'] == 'CANCELLED'
    monkeypatch.setattr('katip.infrastructure.http_transport.MAX_RESPONSE_BYTES', 128)
    job = Job({})
    job.diagnostics = Diagnostics()
    run_request(server, '/large', job=job, json={})
    assert job.diagnostics.snapshot()[-1]['code'] == 'RESPONSE_TOO_LARGE'
