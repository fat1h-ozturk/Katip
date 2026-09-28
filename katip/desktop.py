"""
Cross-Platform Desktop Integration & Autostart Manager for Katip.
Handles application menu entry (.desktop, Start Menu shortcut), icon registration,
and autostart-on-login configuration.
"""

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

def get_project_root() -> Path:
    """Returns the absolute root directory of the katip project."""
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def get_launcher_path() -> Path:
    """Finds the primary executable or shell launcher."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    root = get_project_root()
    if sys.platform.startswith("win"):
        bat_launcher = root / "bin" / "katip.bat"
        if bat_launcher.exists():
            return bat_launcher.resolve()
        return Path(sys.executable).resolve()
    else:
        bash_launcher = root / "bin" / "katip"
        if bash_launcher.exists():
            return bash_launcher.resolve()
        # Fallback to current python interpreter
        return Path(sys.executable).resolve()

# --- LINUX INTEGRATION ---

def _get_linux_desktop_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "applications" / "katip.desktop"

def _get_linux_autostart_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "autostart" / "katip.desktop"

def _install_linux_icons() -> None:
    """Installs SVG and PNG icons to user's ~/.local/share/icons/hicolor directory."""
    root = get_project_root()
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    hicolor_dir = data_home / "icons" / "hicolor"

    # 1. Scalable SVG
    svg_source = root / "assets" / "katip.svg"
    if svg_source.exists():
        target_dir = hicolor_dir / "scalable" / "apps"
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg_source, target_dir / "katip.svg")

    # 2. Raster PNGs (64, 128, 256)
    for size in (64, 128, 256):
        png_source = root / "assets" / f"katip-{size}.png"
        if png_source.exists():
            target_dir = hicolor_dir / f"{size}x{size}" / "apps"
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(png_source, target_dir / "katip.png")

    # Refresh icon cache if gtk-update-icon-cache is present
    if shutil.which("gtk-update-icon-cache"):
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-q", "-t", "-f", str(hicolor_dir)],
                capture_output=True,
                check=False
            )
        except Exception:
            pass

def _uninstall_linux_icons() -> None:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    hicolor_dir = data_home / "icons" / "hicolor"
    
    for icon_name in ("katip", "talk-to-write"):
        svg_target = hicolor_dir / "scalable" / "apps" / f"{icon_name}.svg"
        if svg_target.exists():
            svg_target.unlink()

        for size in (64, 128, 256):
            png_target = hicolor_dir / f"{size}x{size}" / "apps" / f"{icon_name}.png"
            if png_target.exists():
                png_target.unlink()

def _refresh_linux_desktop_database() -> None:
    """Updates desktop database and KDE sycoca cache so changes appear instantly."""
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    apps_dir = data_home / "applications"

    if shutil.which("update-desktop-database"):
        try:
            subprocess.run(["update-desktop-database", str(apps_dir)], capture_output=True, check=False)
        except Exception:
            pass

    # KDE Plasma 6 & 5 sycoca cache
    for kbuild in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(kbuild):
            try:
                subprocess.run([kbuild], capture_output=True, check=False)
                break
            except Exception:
                pass

def _generate_desktop_entry_content() -> str:
    launcher = get_launcher_path()
    project_root = get_project_root()
    return f"""[Desktop Entry]
Name=Katip
GenericName=Sesli Dikte Asistanı
GenericName[en]=Voice Dictation Assistant
Comment=Wispr Flow & SuperWhisper alternatifi ultra hızlı sesli dikte
Comment[en]=Ultra-fast AI voice dictation desktop assistant
Exec="{launcher}" %U
Path={project_root}
Icon=katip
Terminal=false
Type=Application
Categories=Utility;AudioVideo;
Keywords=dictation;dikte;speech;whisper;gemini;stt;voice;ses;yazma;ai;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""

# --- WINDOWS INTEGRATION ---

def _get_windows_programs_dir() -> Optional[Path]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

def _get_windows_startup_dir() -> Optional[Path]:
    programs = _get_windows_programs_dir()
    if not programs:
        return None
    return programs / "Startup"

def _get_windows_desktop_dir() -> Optional[Path]:
    userprofile = os.environ.get("USERPROFILE")
    if not userprofile:
        return None
    desktop = Path(userprofile) / "Desktop"
    if desktop.exists():
        return desktop
    return None

def attach_windows_console() -> None:
    """
    On Windows, attaches to the parent console if invoked with CLI arguments
    from cmd or PowerShell, so output (help, install, status) is visible.
    """
    if not sys.platform.startswith("win"):
        return

    try:
        import ctypes
        # ATTACH_PARENT_PROCESS = -1
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8")
    except Exception:
        pass

def detach_windows_console() -> None:
    """
    On Windows, detaches and hides any console window attached to this process.
    Guarantees that even if launched via python.exe, cmd.exe, or a batch file,
    the terminal window closes immediately and the application runs silently
    in the background.
    """
    if not sys.platform.startswith("win"):
        return

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            # 0 = SW_HIDE: immediately hide the console window
            user32.ShowWindow(hwnd, 0)
            # Detach this process from the console
            kernel32.FreeConsole()

        # Safely redirect standard streams to a log file in config directory
        try:
            from .config import get_config_dir
            log_dir = get_config_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = open(log_dir / "app.log", "a", encoding="utf-8")
            sys.stdout = log_file
            sys.stderr = log_file
        except Exception:
            pass
    except Exception:
        pass

def _ensure_windows_ico() -> Optional[Path]:
    """Ensures a Windows .ico icon exists in assets/ directory."""
    root = get_project_root()
    ico_path = root / "assets" / "katip.ico"
    if ico_path.exists():
        return ico_path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    png_path = root / "assets" / "katip-256.png"
    if png_path.exists():
        try:
            from PySide6.QtGui import QImage
            img = QImage(str(png_path))
            if not img.isNull():
                img.save(str(ico_path))
                return ico_path
        except Exception:
            pass
    return None

def _get_windows_gui_launcher() -> tuple[Path, str]:
    """
    Returns (target, arguments) for launching Katip
    silently without a console window on Windows.
    Prefers pythonw.exe so no terminal/command prompt window ever appears.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve(), ""

    root = get_project_root()
    # 1. Check if GUI executable exists (compiled by pip gui-scripts)
    gui_exe = root / ".venv" / "Scripts" / "katip-gui.exe"
    if gui_exe.exists():
        return gui_exe.resolve(), ""

    # 2. Prefer pythonw.exe in project .venv
    venv_pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.exists():
        return venv_pythonw.resolve(), "-m katip"

    # 3. Check current interpreter's pythonw.exe
    curr_pythonw = Path(sys.executable).parent / "pythonw.exe"
    if curr_pythonw.exists():
        return curr_pythonw.resolve(), "-m katip"

    # 4. Fallback to bat launcher
    bat_launcher = root / "bin" / "katip.bat"
    if bat_launcher.exists():
        return bat_launcher.resolve(), ""

    return Path(sys.executable).resolve(), "-m katip"

def _create_windows_shortcut(
    target: Path,
    shortcut_path: Path,
    arguments: str = "",
    working_dir: Optional[Path] = None,
    icon_path: Optional[Path] = None,
    description: str = "Katip"
) -> bool:
    """Creates a Windows .lnk shortcut using PowerShell."""
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    if shortcut_path.exists():
        try:
            shortcut_path.unlink()
        except Exception:
            pass
    w_dir = working_dir if working_dir else target.parent
    ps_lines = [
        "$ws = New-Object -ComObject WScript.Shell;",
        f"$s = $ws.CreateShortcut('{str(shortcut_path)}');",
        f"$s.TargetPath = '{str(target)}';",
        f"$s.WorkingDirectory = '{str(w_dir)}';",
        f"$s.Arguments = '{arguments}';",
        f"$s.Description = '{description}';",
    ]
    if icon_path and icon_path.exists():
        ps_lines.append(f"$s.IconLocation = '{str(icon_path)}';")
    ps_lines.append("$s.Save()")
    ps_command = " ".join(ps_lines)
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False

# --- MACOS INTEGRATION ---

def _get_mac_app_path() -> Path:
    return Path.home() / "Applications" / "Katip.app"

def _get_mac_launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.talktowrite.app.plist"

def _install_mac_app() -> bool:
    """Creates a native AppleScript .app launcher in ~/Applications."""
    try:
        app_dir = _get_mac_app_path()
        app_dir.parent.mkdir(parents=True, exist_ok=True)
        launcher = get_launcher_path()

        log_path = Path.home() / "Library" / "Logs" / "Katip.log"
        access_check = f"/usr/bin/test -x {shlex.quote(str(launcher))}"
        shell_command = (
            f"nohup {shlex.quote(str(launcher))} >> {shlex.quote(str(log_path))} "
            "2>&1 < /dev/null &"
        )
        applescript_access_check = access_check.replace("\\", "\\\\").replace('"', '\\"')
        applescript_command = shell_command.replace("\\", "\\\\").replace('"', '\\"')
        applescript_source = (
            "on run\n"
            "    try\n"
            f'        do shell script "{applescript_access_check}"\n'
            "    on error errorMessage\n"
            '        display dialog "macOS, Katip\'in Belgeler klasöründeki program dosyalarına erişmesini engelledi. Sistem Ayarları > Gizlilik ve Güvenlik > Dosyalar ve Klasörler bölümünde Katip için Belgeler klasörü erişimini açın ve tekrar deneyin. Ayrıntı: " & errorMessage buttons {"Tamam"} default button "Tamam"\n'
            "        return\n"
            "    end try\n"
            f'    do shell script "{applescript_command}"\n'
            "end run\n"
        )

        with tempfile.TemporaryDirectory(prefix="katip-app-", dir=app_dir.parent) as temp_dir:
            temp_root = Path(temp_dir)
            source_file = temp_root / "Katip.applescript"
            built_app = temp_root / "Katip.app"
            source_file.write_text(applescript_source, encoding="utf-8")
            result = subprocess.run(
                ["/usr/bin/osacompile", "-o", str(built_app), str(source_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(detail or "osacompile failed")

            info_plist = built_app / "Contents" / "Info.plist"
            with info_plist.open("rb") as plist_file:
                metadata = plistlib.load(plist_file)
            metadata.update({
                "CFBundleIdentifier": "com.talktowrite.app",
                "CFBundleName": "Katip",
                "CFBundleDisplayName": "Katip",
                "LSUIElement": True,
                "LSArchitecturePriority": ["arm64", "x86_64"],
                "CFBundleIconFile": "Katip.icns",
                "NSDocumentsFolderUsageDescription": (
                    "Katip, klonladığınız proje klasöründeki uygulama dosyalarını "
                    "başlatmak için Belgeler klasörüne erişir."
                ),
            })
            # osacompile sets this to its stock "applet" asset-catalog icon.
            # Keep the explicit .icns file as the only bundle icon source.
            metadata.pop("CFBundleIconName", None)

            icon_source = get_project_root() / "assets" / "katip-256.png"
            icon_target = built_app / "Contents" / "Resources" / "Katip.icns"
            if not icon_source.exists():
                raise FileNotFoundError(f"macOS app icon not found: {icon_source}")
            icon_result = subprocess.run(
                ["/usr/bin/sips", "-s", "format", "icns", str(icon_source), "--out", str(icon_target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if icon_result.returncode != 0:
                detail = (icon_result.stderr or icon_result.stdout).strip()
                raise RuntimeError(detail or "Could not create macOS app icon")
            stock_icon = icon_target.with_name("applet.icns")
            if stock_icon.exists():
                stock_icon.unlink()

            with info_plist.open("wb") as plist_file:
                plistlib.dump(metadata, plist_file)

            backup_dir = app_dir.with_name(f"{app_dir.name}.old")
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            if app_dir.exists():
                app_dir.rename(backup_dir)
            try:
                shutil.move(str(built_app), str(app_dir))
            except Exception:
                if backup_dir.exists() and not app_dir.exists():
                    backup_dir.rename(app_dir)
                raise
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
        return True
    except Exception as e:
        print(f"[Desktop] Error installing macOS app: {e}")
        return False

def _uninstall_mac_app() -> bool:
    try:
        app_dir = _get_mac_app_path()
        if app_dir.exists():
            shutil.rmtree(app_dir, ignore_errors=True)
        return True
    except Exception as e:
        print(f"[Desktop] Error removing macOS app: {e}")
        return False


# --- PUBLIC API ---

def is_desktop_installed() -> bool:
    """Checks if the application is registered in the OS application launcher."""
    if sys.platform.startswith("win"):
        programs = _get_windows_programs_dir()
        if not programs:
            return False
        return (programs / "Katip.lnk").exists()
    elif sys.platform.startswith("darwin"):
        return _get_mac_app_path().exists()
    else:
        return _get_linux_desktop_path().exists()

def is_autostart_enabled() -> bool:
    """Checks if Katip is configured to start on user login."""
    if sys.platform.startswith("win"):
        startup = _get_windows_startup_dir()
        if not startup:
            return False
        return (startup / "Katip.lnk").exists()
    elif sys.platform.startswith("darwin"):
        return _get_mac_launch_agent_path().exists()
    else:
        return _get_linux_autostart_path().exists()

def install_desktop_entry() -> bool:
    """
    Registers Katip with the OS Application Menu / Search.
    Linux: ~/.local/share/applications/katip.desktop & icon themes.
    Windows: Start Menu Programs shortcut.
    macOS: ~/Applications/Katip.app bundle.
    """
    try:
        if sys.platform.startswith("win"):
            programs = _get_windows_programs_dir()
            if not programs:
                return False
            launcher, args = _get_windows_gui_launcher()
            root = get_project_root()
            ico = _ensure_windows_ico()
            res = _create_windows_shortcut(
                launcher,
                programs / "Katip.lnk",
                arguments=args,
                working_dir=root,
                icon_path=ico,
                description="Katip: Sesli Dikte Asistanı"
            )
            # Also create a shortcut on user's Desktop for convenient 1-click access
            desktop_dir = _get_windows_desktop_dir()
            if desktop_dir:
                try:
                    _create_windows_shortcut(
                        launcher,
                        desktop_dir / "Katip.lnk",
                        arguments=args,
                        working_dir=root,
                        icon_path=ico,
                        description="Katip: Sesli Dikte Asistanı"
                    )
                except Exception:
                    pass
            return res
        elif sys.platform.startswith("darwin"):
            return _install_mac_app()
        else:
            # 1. Install icons
            _install_linux_icons()

            # 2. Write .desktop file
            dest_file = _get_linux_desktop_path()
            # Clean up legacy talk-to-write.desktop if present
            legacy_file = dest_file.parent / "talk-to-write.desktop"
            if legacy_file.exists():
                legacy_file.unlink()
            legacy_autostart = _get_linux_autostart_path().parent / "talk-to-write.desktop"
            if legacy_autostart.exists():
                legacy_autostart.unlink()
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_text(_generate_desktop_entry_content(), encoding="utf-8")
            dest_file.chmod(0o755)

            # 3. Refresh desktop databases
            _refresh_linux_desktop_database()
            return True
    except Exception as e:
        print(f"[Desktop] Error installing desktop entry: {e}")
        return False

def uninstall_desktop_entry() -> bool:
    """Removes Katip from the OS Application Menu / Search."""
    try:
        if sys.platform.startswith("win"):
            programs = _get_windows_programs_dir()
            if programs and (programs / "Katip.lnk").exists():
                (programs / "Katip.lnk").unlink()
            desktop_dir = _get_windows_desktop_dir()
            if desktop_dir and (desktop_dir / "Katip.lnk").exists():
                (desktop_dir / "Katip.lnk").unlink()
            return True
        elif sys.platform.startswith("darwin"):
            return _uninstall_mac_app()
        else:
            dest_file = _get_linux_desktop_path()
            if dest_file.exists():
                dest_file.unlink()
            legacy_file = dest_file.parent / "talk-to-write.desktop"
            if legacy_file.exists():
                legacy_file.unlink()
            _uninstall_linux_icons()
            _refresh_linux_desktop_database()
            return True
    except Exception as e:
        print(f"[Desktop] Error uninstalling desktop entry: {e}")
        return False

def set_autostart(enable: bool) -> bool:
    """Enables or disables autostart on system login."""
    try:
        if sys.platform.startswith("win"):
            startup = _get_windows_startup_dir()
            if not startup:
                return False
            lnk_path = startup / "Katip.lnk"
            if enable:
                launcher, args = _get_windows_gui_launcher()
                root = get_project_root()
                ico = _ensure_windows_ico()
                return _create_windows_shortcut(
                    launcher,
                    lnk_path,
                    arguments=args,
                    working_dir=root,
                    icon_path=ico,
                    description="Katip: Sesli Dikte Asistanı"
                )
            else:
                if lnk_path.exists():
                    lnk_path.unlink()
                return True
        elif sys.platform.startswith("darwin"):
            plist_path = _get_mac_launch_agent_path()
            if enable:
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                launcher = get_launcher_path()
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.talktowrite.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>{launcher}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
                plist_path.write_text(plist_content, encoding="utf-8")
            else:
                if plist_path.exists():
                    plist_path.unlink()
            return True
        else:
            autostart_file = _get_linux_autostart_path()
            if enable:
                autostart_file.parent.mkdir(parents=True, exist_ok=True)
                autostart_file.write_text(_generate_desktop_entry_content(), encoding="utf-8")
                autostart_file.chmod(0o755)
            else:
                if autostart_file.exists():
                    autostart_file.unlink()
            return True
    except Exception as e:
        print(f"[Desktop] Error updating autostart: {e}")
        return False

def ensure_desktop_installed() -> None:
    """
    Checks if desktop entry is installed; if not, automatically registers it.
    This ensures that when a user runs the app, it immediately becomes discoverable
    in their Application Search / Start Menu.
    """
    # ASVS 5.3.2: do not persist a launcher path derived from a temporary DMG mount.
    # The packaged macOS app is installed by dragging it into Applications.
    if sys.platform.startswith("darwin") and getattr(sys, "frozen", False):
        return

    if not is_desktop_installed():
        print("[Desktop] İlk çalıştırma algılandı: Katip uygulama menüsüne kaydediliyor...")
        install_desktop_entry()

def purge_all(remove_config: bool = True) -> bool:
    """
    Completely removes all system integration, autostart entries,
    and optionally the user configuration directory.
    """
    success = uninstall_desktop_entry()
    set_autostart(False)
    if remove_config:
        try:
            from .config import get_config_dir
            cfg = get_config_dir()
            if cfg.exists():
                shutil.rmtree(cfg, ignore_errors=True)
        except Exception as e:
            print(f"[Desktop] Error removing config dir: {e}")
            success = False
    return success
