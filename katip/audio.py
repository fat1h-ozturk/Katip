"""
Audio capture engine for Katip.
Captures 16kHz 16-bit mono PCM audio in memory and reports real-time audio volume levels.
Includes WebRTC VAD (Voice Activity Detection) silence trimming and peak audio normalization.
"""

import contextlib
import ctypes
import io
import math
import struct
import sys
import threading
import wave
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
            pa.terminate()
    except Exception:
        pass
    return devices


class AudioRecorder:
    """Manages audio capture with real-time level metering, warm device caching, and VAD."""

    SAMPLE_RATE = 16000
    CHANNELS = 1
    CHUNK_SIZE = 1024
    FORMAT = pyaudio.paInt16

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
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._terminated = False
        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._vad = webrtcvad.Vad(self.vad_mode) if _HAS_WEBRTC_VAD else None
        # Warm-up PyAudio once on initialization to eliminate ALSA probe latency
        self._ensure_pyaudio()

    def _ensure_pyaudio(self) -> Optional[pyaudio.PyAudio]:
        """Ensures PyAudio instance is warm and ready without device re-probing."""
        if self._pyaudio is None:
            try:
                with no_alsa_err():
                    self._pyaudio = pyaudio.PyAudio()
            except Exception as e:
                print(f"[Audio] PyAudio init error: {e}")
        return self._pyaudio

    def start_recording(self) -> None:
        """Start only after the previous capture worker has fully exited."""
        with self._lock:
            if self.is_recording:
                return
            # ASVS 15.4.1: never reuse recording state while a driver call is pending.
            if self._terminated or (self._thread and self._thread.is_alive()):
                raise RuntimeError("Mikrofon henüz kapanmadı; lütfen tekrar deneyin.")
            if self._frames:
                raise RuntimeError("Önceki ses kaydı henüz alınmadı.")
            self.is_recording = True
            self.last_error = ""
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._record_loop, args=(self._stop,), daemon=True)
            self._thread.start()

    @property
    def has_pending_audio(self) -> bool:
        """Include a timed-out worker and undrained frames in recovery checks."""
        with self._lock:
            return bool(self._frames or (self._thread and self._thread.is_alive()))

    def stop_recording(self) -> bytes:
        """Stop and drain audio, including frames retained after a capture error."""
        with self._lock:
            self.is_recording = False
            self._stop.set()
            worker = self._thread
        if worker and worker is not threading.current_thread():
            worker.join(timeout=2.0)
            if worker.is_alive():
                raise RuntimeError("Mikrofon durdurulamadı; kayıt korunuyor. Lütfen tekrar deneyin.")
        with self._lock:
            # Clear only after successful encoding, so failures preserve the recording.
            audio = self._encode_wav(self._frames)
            self._frames = []
        return audio

    def _record_loop(self, stop: threading.Event) -> None:
        stream = None
        error = None
        try:
            pa = self._ensure_pyaudio()
            if pa is None:
                raise RuntimeError("Mikrofon başlatılamadı.")
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
            while not stop.is_set():
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                with self._lock:
                    self._frames.append(data)
                if self.on_level_callback and data:
                    self.on_level_callback(min(1.0, self._compute_rms(data) * 4.0))
        except Exception:
            if not stop.is_set():
                error = "Mikrofon kaydı kesildi. Mikrofon bağlantısını ve izinlerini kontrol edin."
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
        """Simple decimation/resampling for STT fallback support."""
        if in_rate == out_rate or not raw_bytes:
            return raw_bytes
        
        count = len(raw_bytes) // 2
        try:
            samples = struct.unpack(f"<{count}h", raw_bytes)
            # Basic nearest-neighbor / drop decimation
            ratio = in_rate / out_rate
            out_samples = []
            for i in range(int(count / ratio)):
                idx = int(i * ratio)
                if idx < count:
                    out_samples.append(samples[idx])
            return struct.pack(f"<{len(out_samples)}h", *out_samples)
        except Exception as e:
            print(f"[Audio] Downsampling error: {e}")
            return raw_bytes

    def _process_dsp(self, raw_pcm: bytes, padding_ms: int = 300) -> bytes:
        """
        Applies Noise Gating (silencing non-speech frames) and 
        Automatic Gain Control (AGC) on speech blocks.
        """
        if not raw_pcm or not self._vad:
            return self._normalize_pcm(raw_pcm)

        frame_duration_ms = 30
        frame_size = int(self.SAMPLE_RATE * (frame_duration_ms / 1000.0) * 2)
        total_frames = len(raw_pcm) // frame_size
        if total_frames == 0:
            return raw_pcm

        speech_flags = []
        for i in range(total_frames):
            frame = raw_pcm[i * frame_size : (i + 1) * frame_size]
            try:
                is_speech = self._vad.is_speech(frame, self.SAMPLE_RATE)
            except Exception:
                is_speech = True
            speech_flags.append(is_speech)

        if not any(speech_flags):
            print("[Audio] VAD: Belirgin konuşma bayrağı bulunamadı, sessizlik atlanıyor.")
            return b""

        # Noise Gating: Zero out silence that is far from speech
        padding_frames = int(padding_ms / frame_duration_ms)
        gated_frames = []
        
        # Keep track of first and last speech to trim edges
        first_speech = speech_flags.index(True)
        last_speech = len(speech_flags) - 1 - speech_flags[::-1].index(True)
        
        # We only care about the segment between first_speech-padding and last_speech+padding
        start_frame = max(0, first_speech - padding_frames)
        end_frame = min(total_frames, last_speech + 1 + padding_frames)
        
        active_speech_samples = []
        zero_frame = b"\x00" * frame_size

        for i in range(start_frame, end_frame):
            frame = raw_pcm[i * frame_size : (i + 1) * frame_size]
            
            # Check if this frame is within padding distance of ANY speech frame
            # To be efficient, just check the local window
            local_start = max(0, i - padding_frames)
            local_end = min(total_frames, i + padding_frames + 1)
            is_near_speech = any(speech_flags[local_start:local_end])
            
            if is_near_speech:
                gated_frames.append(frame)
                active_speech_samples.extend(struct.unpack(f"<{len(frame)//2}h", frame))
            else:
                gated_frames.append(zero_frame)

        gated_pcm = b"".join(gated_frames)
        
        # Automatic Gain Control (AGC) - calculate gain based on active speech only, not silence
        target_peak = 24000
        if active_speech_samples:
            peak = max(abs(s) for s in active_speech_samples)
            if peak > 20 and peak < target_peak:
                gain = min(12.0, target_peak / peak)
                count = len(gated_pcm) // 2
                samples = struct.unpack(f"<{count}h", gated_pcm)
                norm_samples = [max(-32768, min(32767, int(s * gain))) for s in samples]
                gated_pcm = struct.pack(f"<{count}h", *norm_samples)
                print(f"[Audio] AGC uygulandı: Peak={peak}, Gain={gain:.2f}x")

        return gated_pcm


    def _compute_rms(self, raw_bytes: bytes) -> float:
        """Computes Root Mean Square (RMS) audio level of PCM data (0.0 to 1.0)."""
        if not raw_bytes:
            return 0.0
        count = len(raw_bytes) // 2
        try:
            samples = struct.unpack(f"<{count}h", raw_bytes)
            if not samples:
                return 0.0
            sum_sq = sum(s * s for s in samples)
            return math.sqrt(sum_sq / len(samples)) / 32768.0
        except Exception:
            return 0.0

    def _normalize_pcm(self, raw_bytes: bytes, target_peak: int = 24000) -> bytes:
        """Normalizes audio volume so quiet microphones are loud and clear for STT models."""
        if not raw_bytes:
            return raw_bytes
        count = len(raw_bytes) // 2
        try:
            samples = struct.unpack(f"<{count}h", raw_bytes)
            peak = max(abs(s) for s in samples) if samples else 0
            if peak > 20 and peak < target_peak:
                # Limit max gain to 12.0x for very quiet mics
                gain = min(12.0, target_peak / peak)
                norm_samples = [max(-32768, min(32767, int(s * gain))) for s in samples]
                return struct.pack(f"<{count}h", *norm_samples)
        except Exception:
            pass
        return raw_bytes

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
