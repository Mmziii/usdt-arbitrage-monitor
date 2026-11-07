import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def test_port_precedence_and_dotenv(tmp_path, monkeypatch):
    from app import __main__ as entry
    calls = []
    monkeypatch.chdir(tmp_path)
    (tmp_path/'.env').write_text('PORT=8765\n')
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.setattr(entry.uvicorn, 'run', lambda *a, **kw: calls.append(kw))
    entry.main([])
    assert calls[-1]['port'] == 8765
    monkeypatch.setenv('PORT', '8766')
    entry.main([])
    assert calls[-1]['port'] == 8766
    entry.main(['--port', '8767'])
    assert calls[-1]['port'] == 8767


def test_actual_server_on_another_port(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update(PORT=str(port), DATABASE_PATH=str(tmp_path/'test.db'), PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    process = subprocess.Popen([sys.executable, '-m', 'app'], cwd=tmp_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/overview', timeout=.2) as response:
                    assert response.status == 200
                    assert 'دیدبان'.encode() in response.read()
                    break
            except OSError:
                if process.poll() is not None:
                    raise AssertionError('server exited before listening')
                time.sleep(.1)
        else:
            raise AssertionError('server did not listen')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
