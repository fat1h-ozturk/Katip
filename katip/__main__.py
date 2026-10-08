"""
CLI and Desktop entry point for Katip.
"""

import argparse
import sys
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .app import KatipApp
from .desktop import (
    attach_windows_console,
    detach_windows_console,
    ensure_desktop_installed,
    get_assets_dir,
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
        prog="katip",
        description="Kâtip: Ultra-fast AI voice dictation desktop assistant."
    )
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="Send toggle trigger to running Katip instance."
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
        help="Register Katip into OS Application Menu and install icons."
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove Katip from OS Application Menu and remove icons."
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Completely purge Katip shortcuts, autostart, and configuration data."
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
        version=f"Katip {__version__}"
    )

    args, unknown = parser.parse_known_args()

    # 1. Handle --install
    if args.install:
        success = install_desktop_entry()
        if success:
            print("[Katip] ✓ Uygulama menüsüne başarıyla kaydedildi!")
            print("  Artık Başlat / Uygulama Arama menüsünden 'Katip' yazarak açabilirsiniz.")
            sys.exit(0)
        else:
            print("[Katip] ✗ Uygulama menüsüne kaydedilemedi.")
            sys.exit(1)

    # 2. Handle --purge
    if args.purge:
        success = purge_all(remove_config=True)
        if success:
            print("[Katip] ✓ Uygulama menüsü, başlangıç kayıtları ve ayarlar tamamen temizlendi.")
            sys.exit(0)
        else:
            print("[Katip] ✗ Tam temizleme sırasında hata oluştu.")
            sys.exit(1)

    # 3. Handle --uninstall
    if args.uninstall:
        success = uninstall_desktop_entry()
        if success:
            print("[Katip] ✓ Uygulama menüsü kayıtları temizlendi.")
            sys.exit(0)
        else:
            print("[Katip] ✗ Kaldırma sırasında hata oluştu.")
            sys.exit(1)

    # 3. Handle --autostart
    if args.autostart:
        if args.autostart == "status":
            enabled = is_autostart_enabled()
            print(f"[Katip] Başlangıçta çalıştırma (Autostart): {'Açık ✓' if enabled else 'Kapalı ✗'}")
            sys.exit(0)
        else:
            enable = args.autostart == "on"
            if not set_autostart(enable):
                print("[Katip] Başlangıç ayarı değiştirilemedi.")
                sys.exit(1)
            print(f"[Katip] Başlangıçta çalıştırma {'açıldı ✓' if enable else 'kapatıldı ✗'}.")
            sys.exit(0)

    # 4. Handle --status
    if args.status:
        running = is_instance_running()
        desktop = is_desktop_installed()
        autostart = is_autostart_enabled()
        print("Katip Sistem Durumu:")
        print(f"  • Çalışma durumu: {'Çalışıyor (Arka Planda) ✓' if running else 'Kapalı ✗'}")
        print(f"  • Uygulama Menüsü: {'Kayıtlı ✓' if desktop else 'Kayıtlı Değil ✗'}")
        print(f"  • Otomatik Başlatma (Autostart): {'Açık ✓' if autostart else 'Kapalı ✗'}")
        sys.exit(0)

    # 5. Handle --toggle, --start, --stop
    if args.toggle:
        success = send_ipc_toggle()
        if success:
            print("[Katip] Kayıt durumu değiştirildi (Toggle sinyali iletildi).")
            sys.exit(0)
        else:
            print("[Katip] Çalışan bir Katip uygulaması bulunamadı. Lütfen önce uygulamayı başlatın.")
            sys.exit(1)

    if args.start:
        success = send_ipc_start()
        if success:
            print("[Katip] Kayıt başlatıldı (Start sinyali iletildi).")
            sys.exit(0)
        else:
            print("[Katip] Çalışan bir Katip uygulaması bulunamadı.")
            sys.exit(1)

    if args.stop:
        success = send_ipc_stop()
        if success:
            print("[Katip] Kayıt durduruldu (Stop sinyali iletildi).")
            sys.exit(0)
        else:
            print("[Katip] Çalışan bir Katip uygulaması bulunamadı.")
            sys.exit(1)

    # 6. Handle --settings
    if args.settings:
        success = open_running_settings()
        if success:
            print("[Katip] Ayarlar penceresi açıldı.")
            sys.exit(0)
        else:
            print("[Katip] Çalışan uygulama bulunamadı, ayarlar açılamıyor.")
            sys.exit(1)

    # 7. Single-Instance Guard
    # If already running, bring up settings window to show the user it's alive, notify and exit
    if is_instance_running():
        open_running_settings()
        notify_running_instance()
        print("[Katip] Kâtip zaten arka planda çalışıyor. Ayarlar penceresi açıldı.")
        print("  Dikteyi başlatmak için kısayolunuzu (Ctrl+Alt+Space) veya '--toggle' komutunu kullanabilirsiniz.")
        sys.exit(0)

    # Detach any console window on Windows so GUI runs silently in the background
    detach_windows_console()

    # Auto-register desktop entry on first GUI run
    ensure_desktop_installed()

    # Launch GUI Application
    q_app = QApplication(sys.argv)
    q_app.setApplicationName("Katip")
    q_app.setApplicationDisplayName("Kâtip")
    q_app.setQuitOnLastWindowClosed(False)

    # Set application icon
    icon_svg = get_assets_dir() / "katip.svg"
    icon_png = get_assets_dir() / "katip-256.png"
    if icon_svg.exists():
        q_app.setWindowIcon(QIcon(str(icon_svg)))
    elif icon_png.exists():
        q_app.setWindowIcon(QIcon(str(icon_png)))

    try:
        app = KatipApp(q_app)
    except RuntimeError as error:
        from PySide6.QtWidgets import QMessageBox
        if is_instance_running():
            open_running_settings()
        else:
            QMessageBox.warning(None, "Kâtip Başlatılamadı", str(error))
        sys.exit(1)

    print("=" * 60)
    print(f"🎙️  Kâtip v{__version__} Başlatıldı!")
    print(f"📌  Kısayol: {app.config.get('hotkey', 'Ctrl+Alt+Space')} (veya 'katip --toggle')")
    print("⚙️  Sistem çekmecesi (System Tray) üzerinden ayarlara ulaşabilirsiniz.")
    print("=" * 60)

    sys.exit(q_app.exec())

if __name__ == "__main__":
    main()
