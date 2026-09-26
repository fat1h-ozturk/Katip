"""
CLI and Desktop entry point for Talk-to-Write.
"""

import argparse
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .app import TalkToWriteApp
from .desktop import (
    attach_windows_console,
    detach_windows_console,
    ensure_desktop_installed,
    get_project_root,
    install_desktop_entry,
    is_autostart_enabled,
    is_desktop_installed,
    purge_all,
    set_autostart,
    uninstall_desktop_entry,
)
from .hotkey import (
    is_instance_running,
    notify_running_instance,
    open_running_settings,
    send_ipc_start,
    send_ipc_stop,
    send_ipc_toggle,
)

def main():
    if len(sys.argv) > 1:
        attach_windows_console()

    parser = argparse.ArgumentParser(
        prog="talk-to-write",
        description="Talk-to-Write: Ultra-fast AI voice dictation desktop assistant."
    )
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="Send toggle trigger to running Talk-to-Write instance."
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start recording on running instance (push-to-talk press)."
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop recording on running instance (push-to-talk release)."
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open settings window on running instance."
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Register Talk-to-Write into OS Application Menu and install icons."
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove Talk-to-Write from OS Application Menu and remove icons."
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Completely purge Talk-to-Write shortcuts, autostart, and configuration data."
    )
    parser.add_argument(
        "--autostart",
        choices=["on", "off", "status"],
        help="Configure or check autostart on system boot."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check status of running instance, desktop integration, and autostart."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Talk-to-Write {__version__}"
    )

    args, unknown = parser.parse_known_args()

    # 1. Handle --install
    if args.install:
        success = install_desktop_entry()
        if success:
            print("[Talk-to-Write] ✓ Uygulama menüsüne başarıyla kaydedildi!")
            print("  Artık Başlat / Uygulama Arama menüsünden 'Talk-to-Write' yazarak açabilirsiniz.")
            sys.exit(0)
        else:
            print("[Talk-to-Write] ✗ Uygulama menüsüne kaydedilemedi.")
            sys.exit(1)

    # 2. Handle --purge
    if args.purge:
        success = purge_all(remove_config=True)
        if success:
            print("[Talk-to-Write] ✓ Uygulama menüsü, başlangıç kayıtları ve ayarlar tamamen temizlendi.")
            sys.exit(0)
        else:
            print("[Talk-to-Write] ✗ Tam temizleme sırasında hata oluştu.")
            sys.exit(1)

    # 3. Handle --uninstall
    if args.uninstall:
        success = uninstall_desktop_entry()
        if success:
            print("[Talk-to-Write] ✓ Uygulama menüsü kayıtları temizlendi.")
            sys.exit(0)
        else:
            print("[Talk-to-Write] ✗ Kaldırma sırasında hata oluştu.")
            sys.exit(1)

    # 3. Handle --autostart
    if args.autostart:
        if args.autostart == "status":
            enabled = is_autostart_enabled()
            print(f"[Talk-to-Write] Başlangıçta çalıştırma (Autostart): {'Açık ✓' if enabled else 'Kapalı ✗'}")
            sys.exit(0)
        else:
            enable = args.autostart == "on"
            set_autostart(enable)
            print(f"[Talk-to-Write] Başlangıçta çalıştırma {'açıldı ✓' if enable else 'kapatıldı ✗'}.")
            sys.exit(0)

    # 4. Handle --status
    if args.status:
        running = is_instance_running()
        desktop = is_desktop_installed()
        autostart = is_autostart_enabled()
        print("Talk-to-Write Sistem Durumu:")
        print(f"  • Çalışma durumu: {'Çalışıyor (Arka Planda) ✓' if running else 'Kapalı ✗'}")
        print(f"  • Uygulama Menüsü: {'Kayıtlı ✓' if desktop else 'Kayıtlı Değil ✗'}")
        print(f"  • Otomatik Başlatma (Autostart): {'Açık ✓' if autostart else 'Kapalı ✗'}")
        sys.exit(0)

    # 5. Handle --toggle, --start, --stop
    if args.toggle:
        success = send_ipc_toggle()
        if success:
            print("[Talk-to-Write] Kayıt durumu değiştirildi (Toggle sinyali iletildi).")
            sys.exit(0)
        else:
            print("[Talk-to-Write] Çalışan bir Talk-to-Write uygulaması bulunamadı. Lütfen önce uygulamayı başlatın.")
            sys.exit(1)

    if args.start:
        success = send_ipc_start()
        if success:
            print("[Talk-to-Write] Kayıt başlatıldı (Start sinyali iletildi).")
            sys.exit(0)
        else:
            print("[Talk-to-Write] Çalışan bir Talk-to-Write uygulaması bulunamadı.")
            sys.exit(1)

    if args.stop:
        success = send_ipc_stop()
        if success:
            print("[Talk-to-Write] Kayıt durduruldu (Stop sinyali iletildi).")
            sys.exit(0)
        else:
            print("[Talk-to-Write] Çalışan bir Talk-to-Write uygulaması bulunamadı.")
            sys.exit(1)

    # 6. Handle --settings
    if args.settings:
        success = open_running_settings()
        if success:
            print("[Talk-to-Write] Ayarlar penceresi açıldı.")
            sys.exit(0)
        else:
            print("[Talk-to-Write] Çalışan uygulama bulunamadı, ayarlar açılamıyor.")
            sys.exit(1)

    # 7. Single-Instance Guard
    # If already running, bring up settings window to show the user it's alive, notify and exit
    if is_instance_running():
        open_running_settings()
        notify_running_instance()
        print("[Talk-to-Write] Talk-to-Write zaten arka planda çalışıyor. Ayarlar penceresi açıldı.")
        print("  Dikteyi başlatmak için kısayolunuzu (Ctrl+Alt+Space) veya '--toggle' komutunu kullanabilirsiniz.")
        sys.exit(0)

    # Detach any console window on Windows so GUI runs silently in the background
    detach_windows_console()

    # Auto-register desktop entry on first GUI run
    ensure_desktop_installed()

    # Launch GUI Application
    q_app = QApplication(sys.argv)
    q_app.setApplicationName("Talk-to-Write")
    q_app.setApplicationDisplayName("Talk-to-Write")
    q_app.setQuitOnLastWindowClosed(False)

    # Set application icon
    icon_svg = get_project_root() / "assets" / "talk-to-write.svg"
    icon_png = get_project_root() / "assets" / "talk-to-write-256.png"
    if icon_svg.exists():
        q_app.setWindowIcon(QIcon(str(icon_svg)))
    elif icon_png.exists():
        q_app.setWindowIcon(QIcon(str(icon_png)))

    app = TalkToWriteApp(q_app)

    print("=" * 60)
    print(f"🎙️  Talk-to-Write v{__version__} Başlatıldı!")
    print("📌  Kısayol: Ctrl+Alt+Space (veya 'talk-to-write --toggle')")
    print("⚙️  Sistem çekmecesi (System Tray) üzerinden ayarlara ulaşabilirsiniz.")
    print("=" * 60)

    sys.exit(q_app.exec())

if __name__ == "__main__":
    main()
