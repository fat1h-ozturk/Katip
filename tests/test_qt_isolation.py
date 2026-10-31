"""Qt objects one test leaves behind must never be destroyed by a later test's worker thread."""
from pathlib import Path
import shutil
import subprocess
import sys

# Automatic GC is off in the child session, so only the shared conftest guard can free
# the cycle; otherwise a later worker thread could free it whenever it next allocates.
_SESSION = '''
import gc
import threading

from PySide6.QtWidgets import QApplication, QWidget

gc.disable()
destroyed_in = []


class Holder:
    pass


def test_leaves_cyclic_native_widget():
    app = QApplication.instance() or QApplication([])
    holder = Holder()
    holder.widget = QWidget()
    holder.self = holder
    holder.widget.destroyed.connect(lambda *_: destroyed_in.append(threading.current_thread().name))
    holder.widget.show()
    app.processEvents()


def test_next_test_starts_without_previous_qt_garbage():
    assert destroyed_in == ["MainThread"]
'''


def test_qt_garbage_is_freed_on_gui_thread_before_next_test(tmp_path):
    shutil.copy(Path(__file__).with_name("conftest.py"), tmp_path / "conftest.py")
    (tmp_path / "test_session.py").write_text(_SESSION, encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_session.py"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
