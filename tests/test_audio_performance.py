"""Reference-host performance checks; opt in with KATIP_RUN_PERFORMANCE=1."""
import json
import os
import threading
import time

import psutil
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from katip.audio import AudioRecorder

pytestmark = pytest.mark.skipif(os.environ.get('KATIP_RUN_PERFORMANCE') != '1',
                                reason='Reference-host performance check; set KATIP_RUN_PERFORMANCE=1')


@pytest.mark.parametrize('duration', [40, 60, 300, 600])
@pytest.mark.parametrize('rate', [16000, 44100, 48000])
def test_background_dsp_memory_and_gui_latency(duration, rate, record_property):
    app = QApplication.instance() or QApplication([])
    recorder = AudioRecorder()
    recorder._actual_rate = rate
    class Detector:
        def is_speech(self, frame, sample_rate): return True
    recorder._vad = Detector()
    pcm = b'\xe8\x03\x18\xfc' * (rate * duration // 2)
    # Warm the native resampler before defining the process baseline.
    if rate != 16000:
        recorder._resample_pcm(b'\0\0' * rate, rate)
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = [baseline]
    result, errors, ticks = [], [], []
    done = threading.Event()
    started = time.monotonic()
    def worker():
        try: result.append(recorder._encode_wav([pcm]))
        except Exception as exc: errors.append(exc)
        finally: done.set()
    thread = threading.Thread(target=worker)
    timer = QTimer()
    timer.setInterval(10)
    def tick():
        ticks.append(time.monotonic())
        peak[0] = max(peak[0], process.memory_info().rss)
        if done.is_set(): app.quit()
    timer.timeout.connect(tick)
    timer.start()
    thread.start()
    app.exec()
    timer.stop()
    thread.join(1)
    assert not errors and result
    assert len(result[0]) == duration * 32000 + 44
    intervals = sorted((b - a) * 1000 for a, b in zip(ticks, ticks[1:])) or [0]
    p95 = intervals[min(len(intervals) - 1, int(len(intervals) * .95))]
    p99 = intervals[min(len(intervals) - 1, int(len(intervals) * .99))]
    metrics = {'duration': duration, 'input_rate': rate, 'elapsed': round(time.monotonic() - started, 3),
               'extra_rss_mib': round((peak[0] - baseline) / 1024**2, 2),
               'gui_p95_ms': round(p95, 2), 'gui_p99_ms': round(p99, 2)}
    record_property('metrics', json.dumps(metrics))
    print(json.dumps(metrics))
    assert p95 < 100 and p99 < 250
    assert peak[0] - baseline <= 2 * len(pcm) + 64 * 1024**2
