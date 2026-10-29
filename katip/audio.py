"""
Audio capture engine for Katip.
Captures 16kHz 16-bit mono PCM audio in memory and reports real-time audio volume levels.
Includes WebRTC VAD (Voice Activity Detection) silence trimming and peak audio normalization.
"""

from array import array
import contextlib
import ctypes
import io
import math
import sys
import threading
import wave
from .diagnostics import Diagnostics
from .domain.errors import CaptureError
from typing import Callable, Optional
import pyaudio

try:
    import webrtcvad
    _HAS_WEBRTC_VAD = True
except ImportError:
    _HAS_WEBRTC_VAD = False


# ASVS 15.4.1: ALSA owns one process-global error callback.
_ALSA_LOCK = threading.RLock()


# Suppress ALSA C-level error spam on Linux only
@contextlib.contextmanager
def no_alsa_err():
    if not sys.platform.startswith("linux"):
        yield
        return

    with _ALSA_LOCK:
        asound = None
        try:
            error_handler_func = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
            c_error_handler = error_handler_func(lambda f, l, fn, err, fmt: None)
            asound = ctypes.cdll.LoadLibrary("libasound.so.2")
            asound.snd_lib_error_set_handler(c_error_handler)
        except Exception:
            asound = None
        try:
            yield
        finally:
            if asound is not None:
                asound.snd_lib_error_set_handler(None)


def get_input_devices() -> list:
    """Returns available audio input devices for configuration."""
    devices = []
    pa = None
    try:
        with no_alsa_err():
            pa = pyaudio.PyAudio()
            default_index = -1
            try:
                def_info = pa.get_default_input_device_info()
                default_index = def_info.get("index", -1)
            except Exception:
                pass

            for i in range(pa.get_device_count()):
                try:
                    info = pa.get_device_info_by_index(i)
                    # Filter for input devices on primary host API (MME on Windows, ALSA on Linux)
                    if info.get("maxInputChannels", 0) > 0 and info.get("hostApi") == 0:
                        devices.append({
                            "index": i,
                            "name": info.get("name"),
                            "is_default": (i == default_index)
                        })
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if pa is not None:
            with contextlib.suppress(Exception):
                pa.terminate()
    return devices


class AudioRecorder:
    """Manages audio capture with real-time level metering, warm device caching, and VAD."""

    SAMPLE_RATE = 16000
    CHANNELS = 1
    CHUNK_SIZE = 1024
    FORMAT = pyaudio.paInt16
    MAX_SECONDS = 600
    MAX_BYTES = 64 * 1024 * 1024
    PROGRESS_SECONDS = 5

    def __init__(self, on_level_callback: Optional[Callable[[float], None]] = None, device_index: int = -1, vad_mode: int = 2,
                 on_error_callback: Optional[Callable[[str], None]] = None):
        self.on_error_callback = on_error_callback
        self.on_level_callback = on_level_callback
        self.device_index = device_index
        self.vad_mode = vad_mode
        self._actual_rate = self.SAMPLE_RATE
        self.is_recording = False
        self.last_error = ""
        self._thread: Optional[threading.Thread] = None
        self._frames = []
        self._capture_pcm = b""
        self._captured_bytes = 0
        self.diagnostics = Diagnostics()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._terminated = False
        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._vad = webrtcvad.Vad(self.vad_mode) if _HAS_WEBRTC_VAD else None
        # The capture worker initializes PortAudio; GUI construction never probes a device.

    def _ensure_pyaudio(self) -> Optional[pyaudio.PyAudio]:
        """Ensures PyAudio instance is warm and ready without device re-probing."""
        if self._pyaudio is None:
            try:
                with no_alsa_err():
                    self._pyaudio = pyaudio.PyAudio()
            except Exception:
                self.diagnostics.event("failed", stage="capture", code="CAPTURE_INITIALIZATION")
        return self._pyaudio

    def start_recording(self) -> None:
        """Start only after the previous capture worker has fully exited."""
        with self._lock:
            if self.is_recording:
                return
            # ASVS 15.4.1: never reuse recording state while a driver call is pending.
            if self._terminated or (self._thread and self._thread.is_alive()):
                raise CaptureError("Mikrofon henüz kapanmadı; lütfen tekrar deneyin.")
            if self._frames or self._capture_pcm:
                raise CaptureError("Önceki ses kaydı henüz alınmadı.")
            self.is_recording = True
            self.last_error = ""
            self._captured_bytes = 0
            self.diagnostics.event("recording_started", stage="capture")
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._record_loop, args=(self._stop,), daemon=True)
            self._thread.start()

    @property
    def is_capturing(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    @property
    def has_pending_audio(self) -> bool:
        """Include a timed-out worker and undrained frames in recovery checks."""
        with self._lock:
            return bool(self._frames or self._capture_pcm or (self._thread and self._thread.is_alive()))

    def stop_recording(self) -> bytes:
        """Stop and drain audio, including frames retained after a capture error."""
        with self._lock:
            self.is_recording = False
            self._stop.set()
            worker = self._thread
        self.diagnostics.event("drain_started", stage="capture")
        if worker and worker is not threading.current_thread():
            worker.join(timeout=2.0)
            if worker.is_alive():
                self.diagnostics.event("failed", stage="capture", code="CAPTURE_DRAIN_TIMEOUT",
                                       audio_bytes=self._captured_bytes, sample_rate=self._actual_rate)
                raise CaptureError("[CAPTURE_DRAIN_TIMEOUT] Mikrofon durdurulamadı; kayıt korunuyor. Lütfen tekrar deneyin.")
        with self._lock:
            if not self._frames:
                return b""
            self._capture_pcm = b"".join(self._frames)
            self._frames = []
            pcm = self._capture_pcm
        self.diagnostics.event("capture_stopped", stage="capture", audio_bytes=len(pcm),
                               sample_rate=self._actual_rate)
        if self.last_error:
            return self._wav(pcm, self._actual_rate)
        self.diagnostics.event("preprocessing_started", stage="preprocessing")
        audio = self._encode_wav([pcm])
        self.diagnostics.event("preprocessing_finished", stage="preprocessing", audio_bytes=len(audio))
        if not audio:
            raise CaptureError("[VAD_REJECTED] Ses filtresi konuşma bulamadı; ham kayıt korunuyor. Sesi kaydedebilir veya filtresiz yeniden deneyebilirsiniz.")
        return audio

    def raw_wav(self) -> bytes:
        """Export the original samples at their actual sample rate, without DSP."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise CaptureError("Mikrofon henüz kapanmadı; kayıt korunuyor.")
            pcm = self._capture_pcm or b"".join(self._frames)
        return self._wav(pcm, self._actual_rate) if pcm else b""

    def discard_audio(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise CaptureError("Mikrofon henüz kapanmadı; kayıt korunuyor.")
            self._frames = []
            self._capture_pcm = b""
            self._captured_bytes = 0

    def retry_audio(self, filtered=True) -> bytes:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise CaptureError("Mikrofon henüz kapanmadı; kayıt korunuyor.")
            pcm = self._capture_pcm or b"".join(self._frames)
        if filtered:
            return self._encode_wav([pcm])
        return self._wav(self._resample_pcm(pcm, self._actual_rate), self.SAMPLE_RATE) if pcm else b""

    @staticmethod
    def _wav(pcm, rate):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    def _record_loop(self, stop: threading.Event) -> None:
        stream = None
        error = None
        try:
            pa = self._ensure_pyaudio()
            if pa is None:
                raise CaptureError("Mikrofon başlatılamadı.")
            stream_kwargs = {
                "format": self.FORMAT, "channels": self.CHANNELS,
                "input": True, "frames_per_buffer": self.CHUNK_SIZE,
            }
            if self.device_index is not None and self.device_index >= 0:
                stream_kwargs["input_device_index"] = self.device_index
            for rate in (self.SAMPLE_RATE, 48000, 44100):
                if stop.is_set():
                    return
                try:
                    with no_alsa_err():
                        stream = pa.open(rate=rate, **stream_kwargs)
                    self._actual_rate = rate
                    break
                except Exception:
                    if rate == 44100:
                        raise
            self._stream = stream
            self.diagnostics.event("stream_opened", stage="capture", sample_rate=self._actual_rate)
            # Periodic progress shows when capture stopped advancing, even if the process dies later.
            progress_step = self.PROGRESS_SECONDS * self._actual_rate * 2
            next_progress = progress_step
            while not stop.is_set():
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                with self._lock:
                    limit = min(self.MAX_BYTES, self.MAX_SECONDS * self._actual_rate * 2)
                    remaining = max(0, limit - self._captured_bytes)
                    kept = data[:remaining - remaining % 2]
                    if kept:
                        self._frames.append(kept)
                        self._captured_bytes += len(kept)
                    reached_limit = self._captured_bytes >= limit
                    captured = self._captured_bytes
                if captured >= next_progress:
                    next_progress += progress_step
                    self.diagnostics.event("capture_progress", stage="capture", audio_bytes=captured,
                                           sample_rate=self._actual_rate)
                if reached_limit:
                    error = "[CAPTURE_LIMIT] Kayıt 10 dakika veya 64 MiB sınırına ulaştı; alınan ses korunuyor."
                    self.diagnostics.event("failed", stage="capture", code="CAPTURE_LIMIT",
                                           audio_bytes=captured, sample_rate=self._actual_rate)
                    break
                if self.on_level_callback and data:
                    self.on_level_callback(min(1.0, self._compute_rms(data) * 4.0))
        except Exception as exc:
            if not stop.is_set():
                code = "CAPTURE_DEVICE_LOST" if isinstance(exc, OSError) and getattr(exc, "errno", None) in (-9985, -9996, 19) else "CAPTURE_READ_ERROR"
                self.diagnostics.event("failed", stage="capture", code=code,
                                       exception_type=type(exc).__name__, errno=getattr(exc, "errno", 0) or 0,
                                       audio_bytes=self._captured_bytes, sample_rate=self._actual_rate)
                error = f"[{code}] Mikrofon kaydı kesildi; alınan ses korunuyor. Mikrofon bağlantısını ve izinlerini kontrol edin."
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass
            with self._lock:
                self._stream = None
                self.is_recording = False
                self.last_error = error or ""
                terminate = self._terminated
            if terminate:
                self._terminate_pyaudio()
            if error and self.on_error_callback:
                self.on_error_callback(error)

    def _terminate_pyaudio(self) -> None:
        with self._lock:
            pa, self._pyaudio = self._pyaudio, None
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    def terminate(self) -> None:
        """Ask the worker to close its own stream before terminating PortAudio."""
        with self._lock:
            self._terminated = True
            self.is_recording = False
            self._stop.set()
            worker = self._thread
        if worker and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        # A blocked driver retains ownership; its finally block performs cleanup.
        if not worker or not worker.is_alive():
            self._terminate_pyaudio()

    def _resample_pcm(self, raw_bytes: bytes, in_rate: int, out_rate: int = 16000) -> bytes:
        if in_rate == out_rate or not raw_bytes:
            return raw_bytes
        # soxr applies anti-alias filtering; never label unconverted samples as 16 kHz.
        try:
            import numpy as np
            import soxr
            samples = np.frombuffer(raw_bytes, dtype="<i2")
            return soxr.resample(samples, in_rate, out_rate, quality="HQ").astype("<i2").tobytes()
        except Exception:
            raise CaptureError("[RESAMPLE_FAILED] Ses dönüştürülemedi; ham kayıt korunuyor.") from None

    @staticmethod
    def _samples(data):
        values = array("h")
        values.frombytes(data)
        if sys.byteorder != "little":
            values.byteswap()
        return values

    def _process_dsp(self, raw_pcm: bytes, padding_ms: int = 300) -> bytes:
        if not raw_pcm or not self._vad:
            return self._normalize_pcm(raw_pcm)
        frame_size = self.SAMPLE_RATE * 30 // 1000 * 2
        # Pad only for the detector; retain the original final partial frame.
        frame_count = (len(raw_pcm) + frame_size - 1) // frame_size
        flags = []
        for i in range(frame_count):
            frame = raw_pcm[i * frame_size:(i + 1) * frame_size]
            try:
                flags.append(self._vad.is_speech(frame.ljust(frame_size, b"\0"), self.SAMPLE_RATE))
            except Exception:
                flags.append(True)
        if not any(flags):
            return b""
        padding = padding_ms // 30
        first = max(0, flags.index(True) - padding)
        last = min(frame_count, len(flags) - flags[::-1].index(True) + padding)
        output = bytearray()
        for i in range(first, last):
            frame = raw_pcm[i * frame_size:(i + 1) * frame_size]
            near = any(flags[max(0, i - padding):min(frame_count, i + padding + 1)])
            output.extend(frame if near else b"\0" * len(frame))
        return self._normalize_pcm(bytes(output))

    def _compute_rms(self, raw_bytes: bytes) -> float:
        count = len(raw_bytes) // 2
        if not count:
            return 0.0
        total = 0
        for offset in range(0, count * 2, 8192):
            values = self._samples(raw_bytes[offset:min(offset + 8192, count * 2)])
            total += sum(value * value for value in values)
        return math.sqrt(total / count) / 32768.0

    def _normalize_pcm(self, raw_bytes: bytes, target_peak: int = 24000) -> bytes:
        peak = 0
        for offset in range(0, len(raw_bytes), 8192):
            values = self._samples(raw_bytes[offset:offset + 8192])
            peak = max(peak, max((abs(value) for value in values), default=0))
        if not 20 < peak < target_peak:
            return raw_bytes
        gain = min(12.0, target_peak / peak)
        output = bytearray()
        for offset in range(0, len(raw_bytes), 8192):
            values = self._samples(raw_bytes[offset:offset + 8192])
            scaled = array("h", (max(-32768, min(32767, int(value * gain))) for value in values))
            if sys.byteorder != "little":
                scaled.byteswap()
            output.extend(scaled.tobytes())
        return bytes(output)

    def _encode_wav(self, frames: list) -> bytes:
        """
        Trims silence via VAD, checks minimum RMS noise floor,
        normalizes peak speech volume, and encodes into RIFF WAV.
        """
        if not frames:
            return b""

        raw_pcm = b"".join(frames)
        if len(raw_pcm) < 3200:  # < 0.1s
            return b""

        # 0. Resample to 16kHz if fallback was used
        if getattr(self, "_actual_rate", self.SAMPLE_RATE) != self.SAMPLE_RATE:
            raw_pcm = self._resample_pcm(raw_pcm, self._actual_rate, self.SAMPLE_RATE)

        # 1 & 3. DSP Pipeline: Noise Gating + AGC
        normalized_pcm = self._process_dsp(raw_pcm)

        if not normalized_pcm:
            return b""

        # 2. RMS-based noise floor check
        rms = self._compute_rms(normalized_pcm)
        if rms < 0.0001:
            print(f"[Audio] RMS {rms:.5f} mutlak sessizlik, atlanıyor.")
            return b""

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(normalized_pcm)

        return buf.getvalue()
