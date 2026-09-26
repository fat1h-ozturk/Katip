"""
Procedural sound effect feedback for Katip.
Generates pleasant acoustic chimes for start, stop, success, and error states.
"""

import io
import math
import os
import shutil
import struct
import subprocess
import sys
import threading
import wave
from typing import Dict

class SoundPlayer:
    """Plays non-blocking pleasant UI sounds using PipeWire / ALSA."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._cache: Dict[str, bytes] = {}
        self._has_pw_play = sys.platform.startswith("linux") and (shutil.which("pw-play") is not None)
        self._has_aplay = sys.platform.startswith("linux") and (shutil.which("aplay") is not None)
        self._has_afplay = sys.platform == "darwin" and (shutil.which("afplay") is not None)
        self._init_sounds()

    def _init_sounds(self) -> None:
        """Pre-renders short sine-wave chimes."""
        self._cache["start"] = self._synthesize_sweep(520, 780, 0.07, 0.25)
        self._cache["stop"] = self._synthesize_sweep(780, 520, 0.07, 0.25)
        self._cache["success"] = self._synthesize_chord([523, 659, 784], 0.12, 0.2)
        self._cache["error"] = self._synthesize_sweep(320, 200, 0.12, 0.25)

    def _synthesize_sweep(self, f_start: float, f_end: float, duration: float, volume: float) -> bytes:
        sample_rate = 44100
        n_samples = int(sample_rate * duration)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                # Linear frequency sweep
                freq = f_start + (f_end - f_start) * (i / n_samples)
                # Cosine envelope to prevent clicks
                env = math.sin(math.pi * i / n_samples)
                sample = int(32767 * volume * env * math.sin(2 * math.pi * freq * t))
                data.extend(struct.pack("<h", max(-32767, min(32767, sample))))
            wf.writeframes(data)
        return buf.getvalue()

    def _synthesize_chord(self, freqs: list, duration: float, volume: float) -> bytes:
        sample_rate = 44100
        n_samples = int(sample_rate * duration)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                env = math.sin(math.pi * i / n_samples)
                combined = sum(math.sin(2 * math.pi * f * t) for f in freqs) / len(freqs)
                sample = int(32767 * volume * env * combined)
                data.extend(struct.pack("<h", max(-32767, min(32767, sample))))
            wf.writeframes(data)
        return buf.getvalue()

    def play(self, sound_name: str) -> None:
        """Plays the specified sound asynchronously."""
        if not self.enabled:
            return

        wav_data = self._cache.get(sound_name)
        if not wav_data:
            return

        threading.Thread(target=self._play_bytes, args=(wav_data,), daemon=True).start()

    def _play_bytes(self, wav_data: bytes) -> None:
        # 1. Windows: Native winsound API
        if sys.platform.startswith("win"):
            try:
                import winsound
                winsound.PlaySound(wav_data, winsound.SND_MEMORY)
                return
            except Exception as e:
                pass

        # 2. macOS: Built-in afplay
        if sys.platform == "darwin":
            try:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(wav_data)
                    tmp_path = f.name
                subprocess.run(["afplay", tmp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                return
            except Exception:
                pass

        # 3. Linux: pw-play or aplay
        try:
            if self._has_pw_play:
                subprocess.run(["pw-play", "-"], input=wav_data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif self._has_aplay:
                subprocess.run(["aplay", "-q", "-"], input=wav_data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
