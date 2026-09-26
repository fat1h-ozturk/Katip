"""
Controller for the Wayland Layer Shell Overlay.
Launches and communicates with the GTK4 layer shell overlay process.
"""

import os
import subprocess
import sys
from typing import Optional

class LayerOverlayController:
    """Manages the lifecycle and IPC commands to the Wayland Layer Shell overlay."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.current_mode = "dictation"
        self._start_overlay()

    def _start_overlay(self) -> None:
        """Starts the GTK4 layer shell overlay process."""
        env = dict(os.environ)
        layer_so = "/usr/lib64/libgtk4-layer-shell.so.0"
        if os.path.exists(layer_so):
            cur_preload = env.get("LD_PRELOAD", "")
            env["LD_PRELOAD"] = f"{layer_so}:{cur_preload}" if cur_preload else layer_so

        cmd = [sys.executable, "-m", "katip.ui.overlay_gtk"]
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                text=True,
                bufsize=1
            )
        except Exception as e:
            print(f"[Overlay] Failed to start layer shell overlay: {e}")
            self.process = None

    def _send_cmd(self, cmd: str) -> None:
        if not self.process or self.process.poll() is not None:
            self._start_overlay()

        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(f"{cmd}\n")
                self.process.stdin.flush()
            except Exception:
                pass

    def show_recording(self, mode: str) -> None:
        self.current_mode = mode
        self._send_cmd(f"RECORDING {mode}")

    def show_processing(self) -> None:
        self._send_cmd("PROCESSING")

    def show_success(self, latency: float = 0.0) -> None:
        self._send_cmd(f"SUCCESS {latency}")

    def show_error(self, message: str) -> None:
        self._send_cmd(f"ERROR {message}")

    def hide_pill(self) -> None:
        self._send_cmd("HIDE")

    def set_mode(self, mode: str) -> None:
        self.current_mode = mode

    def set_audio_level(self, level: float) -> None:
        # Audio level metering can be passed or ignored by layer pill
        pass

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                self._send_cmd("QUIT")
                self.process.terminate()
            except Exception:
                pass
            self.process = None
