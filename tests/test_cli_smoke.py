"""Version/status entry points must not start the GUI or touch production state."""
import os
import subprocess
import sys


def test_version_does_not_import_gui_or_audio_engines(tmp_path):
    code = '''import sys, runpy
class Block:
 def find_spec(self, fullname, path=None, target=None):
  if fullname in ('katip.app', 'pyaudio', 'PySide6'):
   raise AssertionError('GUI engine loaded for --version')
sys.meta_path.insert(0, Block())
sys.argv = ['katip', '--version']
runpy.run_module('katip', run_name='__main__')
'''
    env = dict(os.environ, KATIP_PROFILE='ci-smoke', XDG_CONFIG_HOME=str(tmp_path))
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('Katip ')
    assert not list(tmp_path.iterdir())


def test_candidate_status_cannot_control_production_instance(tmp_path):
    env = dict(os.environ, KATIP_PROFILE='ci-smoke', XDG_CONFIG_HOME=str(tmp_path))
    result = subprocess.run([sys.executable, '-m', 'katip', '--status'], env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0
    assert 'Kapalı' in result.stdout
    assert not list(tmp_path.iterdir())
