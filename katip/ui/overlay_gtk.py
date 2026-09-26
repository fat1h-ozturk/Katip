"""
GTK4 Layer Shell Overlay for Katip on Wayland.
Renders an ultra-smooth floating pill on the OVERLAY layer that CANNOT steal keyboard focus.
"""

import os
import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gtk, Gtk4LayerShell, Gdk, GLib

MODE_TITLES = {
    "dictation": "DİKTE",
    "chat": "CHAT",
    "email": "E-POSTA",
    "prompt": "PROMPT",
    "bullets": "NOTLAR",
}

CSS_DATA = b"""
window {
    background-color: transparent;
}
.pill-container {
    background-color: rgba(18, 18, 22, 0.94);
    border-radius: 24px;
    padding: 8px 22px;
    margin: 0px;
    transition: all 200ms ease-in-out;
}
.pill-recording {
    border: 1.5px solid #ef4444;
}
.pill-processing {
    border: 1.5px solid #3b82f6;
}
.pill-success {
    border: 1.5px solid #10b981;
}
.pill-error {
    border: 1.5px solid #f43f5e;
}
.mode-badge {
    background-color: rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: bold;
    color: #e4e4e7;
    font-family: sans-serif;
}
.status-label {
    color: #ffffff;
    font-size: 13px;
    font-weight: 500;
    font-family: sans-serif;
}
"""

class LayerOverlayApp:
    def __init__(self):
        self.app = Gtk.Application(application_id="com.talktowrite.layeroverlay")
        self.app.connect("activate", self.on_activate)
        self.hide_timer_id = 0

    def on_activate(self, app):
        self.win = Gtk.ApplicationWindow(application=app)

        # Initialize as Wayland Layer Shell surface
        Gtk4LayerShell.init_for_window(self.win)
        # OVERLAY layer guarantees it floats above all windows forever
        Gtk4LayerShell.set_layer(self.win, Gtk4LayerShell.Layer.OVERLAY)
        # KEYBOARD NONE guarantees the active text editor NEVER loses focus/cursor!
        Gtk4LayerShell.set_keyboard_mode(self.win, Gtk4LayerShell.KeyboardMode.NONE)
        # Anchor to top center
        Gtk4LayerShell.set_anchor(self.win, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_margin(self.win, Gtk4LayerShell.Edge.TOP, 35)

        # Load CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS_DATA)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.box.add_css_class("pill-container")
        self.box.add_css_class("pill-recording")

        self.mode_badge = Gtk.Label(label="DİKTE")
        self.mode_badge.add_css_class("mode-badge")
        self.box.append(self.mode_badge)

        self.status_label = Gtk.Label(label="Dinleniyor...")
        self.status_label.add_css_class("status-label")
        self.box.append(self.status_label)

        self.win.set_child(self.box)

        # Start hidden
        self.win.set_visible(False)

        # Watch stdin for commands from the main Katip process
        channel = GLib.IOChannel.unix_new(sys.stdin.fileno())
        channel.set_encoding(None)
        channel.set_flags(GLib.IOFlags.NONBLOCK)
        GLib.io_add_watch(channel, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP, self._on_stdin_data)

    def _on_stdin_data(self, channel, condition):
        if condition & GLib.IOCondition.HUP:
            self.app.quit()
            return False

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip()
                if cmd:
                    self._handle_command(cmd)
            except Exception:
                break
        return True

    def _handle_command(self, cmd: str):
        if self.hide_timer_id:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = 0

        parts = cmd.split(" ", 1)
        action = parts[0].upper()
        arg = parts[1] if len(parts) > 1 else ""

        self._clear_styles()

        if action == "RECORDING":
            mode_title = MODE_TITLES.get(arg.lower(), "DİKTE")
            self.mode_badge.set_text(mode_title)
            self.status_label.set_text("🔴 Dinleniyor...")
            self.box.add_css_class("pill-recording")
            self.win.set_visible(True)

        elif action == "PROCESSING":
            self.status_label.set_text("⚡ Dönüştürülüyor...")
            self.box.add_css_class("pill-processing")
            self.win.set_visible(True)

        elif action == "SUCCESS":
            latency = arg if arg else ""
            txt = f"✓ Yapıştırıldı! ({latency}s)" if latency else "✓ Yapıştırıldı!"
            self.status_label.set_text(txt)
            self.box.add_css_class("pill-success")
            self.win.set_visible(True)
            self.hide_timer_id = GLib.timeout_add(1600, self._auto_hide)

        elif action == "ERROR":
            msg = arg[:30] + ("..." if len(arg) > 30 else "")
            self.status_label.set_text(f"⚠️ {msg}")
            self.box.add_css_class("pill-error")
            self.win.set_visible(True)
            self.hide_timer_id = GLib.timeout_add(3200, self._auto_hide)

        elif action == "HIDE":
            self.win.set_visible(False)

        elif action == "QUIT":
            self.app.quit()

    def _clear_styles(self):
        for style in ["pill-recording", "pill-processing", "pill-success", "pill-error"]:
            self.box.remove_css_class(style)

    def _auto_hide(self):
        self.win.set_visible(False)
        self.hide_timer_id = 0
        return False

    def run(self):
        self.app.run([])

if __name__ == "__main__":
    app = LayerOverlayApp()
    app.run()
