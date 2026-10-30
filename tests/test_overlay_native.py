"""Exercise native bindings: mocked painters cannot detect singleton refcount corruption."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


RENDER_PROBE = textwrap.dedent("""
    import sys
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from katip.ui.pill import FloatingPill

    app = QApplication([])
    pill = FloatingPill()
    pill.show_recording('dictation')
    pill._anim_timer.stop()
    app.processEvents()
    image = QImage(pill.size(), QImage.Format.Format_ARGB32_Premultiplied)

    # Warm fonts, overload dispatch and lazy Qt state before measuring.
    for frame in range(20):
        pill.render(image)
    before = sys.getrefcount(None)
    # At 60 FPS this is a minute of the real overlay, accelerated without audio,
    # network, display server or wall-clock sleeps. 6.12.0 aborts well before this.
    for frame in range(3600):
        pill.set_audio_level((frame % 100) / 100)
        pill._on_tick()
        pill.render(image)
    after = sys.getrefcount(None)
    assert after >= before - 32, (before, after)
    for state in ('processing', 'success', 'error', 'hidden'):
        pill.state = state
        for frame in range(100):
            pill._on_tick()
            pill.render(image)
    pill.close()
    print('rendered 3600 recording frames and 400 status frames', flush=True)
""")


def test_minute_of_native_overlay_rendering_preserves_python_singletons():
    # A native abort must fail this test without killing the rest of pytest.
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", KATIP_PROFILE="overlay-test")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", RENDER_PROBE],
        cwd=Path(__file__).resolve().parents[1],
        env=env, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rendered 3600 recording frames and 400 status frames" in result.stdout
