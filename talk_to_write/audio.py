"""
Audio capture engine for Talk-to-Write.
Captures 16kHz 16-bit mono PCM audio in memory and reports real-time audio volume levels.
Includes WebRTC VAD (Voice Activity Detection) silence trimming and peak audio normalization.
"""

import contextlib
import ctypes
import io
import math
import os
import struct
import sys
import threading
import time
import wave
from typing import Callable, Optional
import pyaudio

try:
    import webrtcvad
    _HAS_WEBRTC_VAD = True
except ImportError:
    _HAS_WEBRTC_VAD = False


# Suppress ALSA C-level error spam on Linux only
@contextlib.contextmanager
def no_alsa_err():
    if not sys.platform.startswith("linux"):
        yield
        return

    try:
        error_handler_func = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
        c_error_handler = error_handler_func(lambda f, l, fn, err, fmt: None)
        asound = ctypes.cdll.LoadLibrary('libasound.so.2')
        asound.snd_lib_error_set_handler(c_error_handler)
        yield
        asound.snd_lib_error_set_handler(None)
    except Exception:
        yield


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

    def __init__(self, on_level_callback: Optional[Callable[[float], None]] = None, device_index: int = -1, vad_mode: int = 2):
        self.on_level_callback = on_level_callback
        self.device_index = device_index
        self.vad_mode = vad_mode
        self._actual_rate = self.SAMPLE_RATE
        self.is_recording = False
        self._thread: Optional[threading.Thread] = None
        self._frames = []
        self._lock = threading.Lock()
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
        """Starts capturing audio in a background thread."""
        with self._lock:
            if self.is_recording:
                return
            self.is_recording = True
            self._frames = []

        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop_recording(self) -> bytes:
        """Stops capturing audio and returns the recorded WAV bytes."""
        with self._lock:
            if not self.is_recording:
                return b""
            self.is_recording = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            frames = list(self._frames)
            self._frames = []

        return self._encode_wav(frames)

    def _record_loop(self) -> None:
        try:
            pa = self._ensure_pyaudio()
            if not pa:
                return

            stream_kwargs = {
                "format": self.FORMAT,
                "channels": self.CHANNELS,
                "rate": self.SAMPLE_RATE,
                "input": True,
                "frames_per_buffer": self.CHUNK_SIZE
            }
            if self.device_index is not None and self.device_index >= 0:
                stream_kwargs["input_device_index"] = self.device_index

            self._actual_rate = self.SAMPLE_RATE
            try:
                with no_alsa_err():
                    self._stream = pa.open(**stream_kwargs)
            except Exception as e:
                print(f"[Audio] 16kHz denemesi başarısız oldu: {e}, 48kHz deneniyor...")
                stream_kwargs["rate"] = 48000
                self._actual_rate = 48000
                try:
                    with no_alsa_err():
                        self._stream = pa.open(**stream_kwargs)
                except Exception as e2:
                    print(f"[Audio] 48kHz başarısız oldu: {e2}, 44.1kHz deneniyor...")
                    stream_kwargs["rate"] = 44100
                    self._actual_rate = 44100
                    with no_alsa_err():
                        self._stream = pa.open(**stream_kwargs)

            while True:
                with self._lock:
                    if not self.is_recording:
                        break

                try:
                    data = self._stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                    with self._lock:
                        self._frames.append(data)

                    # Compute RMS audio level
                    if self.on_level_callback and data:
                        shorts = struct.unpack(f"{len(data) // 2}h", data)
                        if shorts:
                            sum_sq = sum(s * s for s in shorts)
                            rms = math.sqrt(sum_sq / len(shorts)) / 32768.0
                            # Amplify dynamic range slightly for visual punch
                            normalized = min(1.0, rms * 4.0)
                            self.on_level_callback(normalized)

                except Exception as e:
                    print(f"[Audio] Error reading chunk: {e}")
                    break

        except Exception as e:
            print(f"[Audio] Stream initialization error: {e}")
        finally:
            self._cleanup_stream()

    def _cleanup_stream(self) -> None:
        """Closes the current recording stream while keeping PyAudio warm."""
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None
        except Exception:
            pass

    def terminate(self) -> None:
        """Fully terminates PyAudio on application exit."""
        self._cleanup_stream()
        try:
            if self._pyaudio:
                self._pyaudio.terminate()
                self._pyaudio = None
        except Exception:
            pass

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


    def _trim_silence_vad(self, raw_pcm: bytes, padding_ms: int = 300) -> bytes:
        """
        Uses WebRTC VAD to trim dead silence from beginning and end of recording.
        Adds padding_ms of audio before and after speech to ensure no consonants are cut.
        Returns empty bytes if no speech was detected anywhere in the recording.
        """
        if not raw_pcm or not self._vad:
            return raw_pcm

        frame_duration_ms = 30  # WebRTC VAD supports 10, 20, or 30ms frames
        frame_size = int(self.SAMPLE_RATE * (frame_duration_ms / 1000.0) * 2)  # 960 bytes
        total_frames = len(raw_pcm) // frame_size
        if total_frames == 0:
            return raw_pcm

        speech_flags = []
        for i in range(total_frames):
            frame = raw_pcm[i * frame_size : (i + 1) * frame_size]
            try:
                is_speech = self._vad.is_speech(frame, self.SAMPLE_RATE)
            except Exception:
                is_speech = True  # In case of VAD edge cases, err on the side of speech
            speech_flags.append(is_speech)

        if not any(speech_flags):
            print("[Audio] VAD: Belirgin konuşma bayrağı bulunamadı, ham ses korunuyor.")
            return raw_pcm

        first_speech_idx = speech_flags.index(True)
        last_speech_idx = len(speech_flags) - 1 - speech_flags[::-1].index(True)

        padding_frames = int(padding_ms / frame_duration_ms)
        start_frame = max(0, first_speech_idx - padding_frames)
        end_frame = min(total_frames, last_speech_idx + 1 + padding_frames)

        start_byte = start_frame * frame_size
        end_byte = min(len(raw_pcm), end_frame * frame_size)
        trimmed = raw_pcm[start_byte:end_byte]
        
        saved_sec = (len(raw_pcm) - len(trimmed)) / (self.SAMPLE_RATE * 2)
        if saved_sec > 0.2:
            print(f"[Audio] VAD: {saved_sec:.2f}s sessizlik budandı ({len(trimmed)}/{len(raw_pcm)} bayt).")
        return trimmed

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
