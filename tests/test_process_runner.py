"""Execute real isolated child processes without API, device or clipboard access."""
import subprocess
import sys
import time
import psutil
import threading

import pytest
from katip.application.session import Job
from katip.infrastructure.http_transport import execution_scope
from katip.infrastructure.process_runner import run_process


def test_process_utf8_output():
    # ASCII source avoids macOS argv normalization; the child writes UTF-8 even
    # when Windows uses a legacy code page for redirected Python output.
    source = 'import sys; sys.stdout.buffer.write("Türkçe ıİş".encode("utf-8"))'
    result = run_process([sys.executable, '-c', source.encode('ascii', 'backslashreplace').decode('ascii')], timeout=2)
    assert result.returncode == 0 and result.stdout.strip() == 'Türkçe ıİş'


def test_missing_executable():
    with pytest.raises(FileNotFoundError):
        run_process(['/no-such-katip-command'], timeout=.1)


def test_timeout_cleans_up_grandchild(tmp_path):
    pidfile = tmp_path / 'pid'
    source = ('import subprocess,sys,time; '
              'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
              'open(sys.argv[1],"w").write(str(p.pid));time.sleep(60)')
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, '-c', source, str(pidfile)], timeout=2)
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return
        except psutil.NoSuchProcess:
            return
        time.sleep(.01)
    pytest.fail('CLI descendant survived timeout cleanup')


def test_cancel_process():
    job = Job({})
    timer = threading.Timer(.1, job.cancelled.set)
    timer.start()
    try:
        with execution_scope(job), pytest.raises(RuntimeError, match='CANCELLED'):
            run_process([sys.executable, '-c', 'import time;time.sleep(60)'], timeout=2)
    finally:
        timer.join(1)
