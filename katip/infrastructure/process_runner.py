"""Bounded command execution, cancellation and child-process cleanup."""

import os
import signal
import subprocess
import sys
import time

from .http_transport import current_job
from ..domain.errors import ProviderError

MAX_OUTPUT = 4 * 1024 * 1024


def clean_environment():
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
        else:
            env.pop("LD_LIBRARY_PATH", None)
        env.pop("QT_PLUGIN_PATH", None)
        env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
        env.pop("LD_PRELOAD", None)
    return env


def _windows_job(pid):
    import ctypes as c
    from ctypes import wintypes as w

    class Basic(c.Structure):
        _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                    ("min_working", c.c_size_t), ("max_working", c.c_size_t), ("active", w.DWORD),
                    ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

    class Extended(c.Structure):
        _fields_ = [("basic", Basic), ("io", c.c_uint64 * 6), ("process_memory", c.c_size_t),
                    ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]

    kernel = c.windll.kernel32
    kernel.CreateJobObjectW.restype = c.c_void_p
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.OpenProcess.restype = c.c_void_p
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.SetInformationJobObject.argtypes = [c.c_void_p, c.c_int, c.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [c.c_void_p, c.c_void_p]
    kernel.CloseHandle.argtypes = [c.c_void_p]
    job = kernel.CreateJobObjectW(None, None)
    process = kernel.OpenProcess(0x0100 | 0x0001 | 0x0400, False, pid)
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not process or not kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, process):
        if process:
            kernel.CloseHandle(process)
        if job:
            kernel.CloseHandle(job)
        raise ProviderError("PROCESS_ISOLATION", "formatter", "CLI alt süreçleri güvenle izole edilemedi.")
    kernel.CloseHandle(process)
    return lambda: kernel.CloseHandle(job)


def run_process(cmd, *, capture_output=True, text=True, encoding="utf-8", timeout=90,
                creationflags=0, env=None, input=None):
    from PySide6.QtCore import QProcess, QProcessEnvironment
    process = QProcess()
    qenv = QProcessEnvironment()
    for key, value in (env or clean_environment()).items():
        qenv.insert(key, value)
    process.setProcessEnvironment(qenv)
    if os.name == "posix":
        process.setUnixProcessParameters(QProcess.UnixProcessFlag.CreateNewSession)
    process.start(str(cmd[0]), [str(part) for part in cmd[1:]])
    job = current_job()
    started = time.monotonic()
    output, errors = bytearray(), bytearray()
    pid = 0
    close_job = None

    def cleanup():
        if pid and os.name == "posix":
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if close_job:
            close_job()
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(1000)

    try:
        if not process.waitForStarted(3000):
            raise FileNotFoundError("CLI executable unavailable")
        pid = process.processId()
        if os.name == "nt":
            close_job = _windows_job(pid)
        if input is not None:
            process.write(input.encode(encoding) if isinstance(input, str) else input)
        process.closeWriteChannel()
        while process.state() != QProcess.ProcessState.NotRunning:
            if job:
                job.check()
            if time.monotonic() - started >= timeout:
                # Do not attach the command/prompt to a public timeout exception.
                raise subprocess.TimeoutExpired("katip-cli", timeout)
            process.waitForReadyRead(25)
            output.extend(bytes(process.readAllStandardOutput()))
            errors.extend(bytes(process.readAllStandardError()))
            if len(output) + len(errors) > MAX_OUTPUT:
                raise ProviderError("CLI_OUTPUT_LIMIT", "formatter", "CLI çıktısı yerel sınırı aştı; ham metin korundu.")
        output.extend(bytes(process.readAllStandardOutput()))
        errors.extend(bytes(process.readAllStandardError()))
        if len(output) + len(errors) > MAX_OUTPUT:
            raise ProviderError("CLI_OUTPUT_LIMIT", "formatter", "CLI çıktısı yerel sınırı aştı; ham metin korundu.")
        return subprocess.CompletedProcess("katip-cli", process.exitCode(),
            output.decode(encoding, "replace"), errors.decode(encoding, "replace"))
    finally:
        cleanup()
