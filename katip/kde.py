"""Keep the Qt recording indicator visible without activating it on KWin."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from .runtime import app_id, profile
from .infrastructure.process_runner import clean_environment

OVERLAY_TITLE = "Katip Recording Overlay"
_RULE_GROUP = "KatipOverlay" if app_id() == "katip" else "KatipOverlay-" + app_id()
_RULE = {
    "Description": "Katip recording indicator: preserve editor focus",
    "title": r"^Katip Recording Overlay( — .*)?$",
    "titlematch": "3",  # Regular expression, including Qt's display-name suffix.
    "wmclass": app_id(),
    "wmclassmatch": "1",
    "acceptfocus": "false",
    "acceptfocusrule": "2",  # Force; Qt's no-focus hint is insufficient on KWin.
    "above": "true",
    "aboverule": "2",
}


def _tools():
    for version in ("6", "5"):
        reader = shutil.which(f"kreadconfig{version}")
        writer = shutil.which(f"kwriteconfig{version}")
        if reader and writer:
            return reader, writer
    return None


def _run(args):
    # Frozen Qt libraries must not leak into the system's KDE tools.
    env = clean_environment()
    return subprocess.run(args, capture_output=True, text=True, check=True,
                          timeout=3, env=env)


def _reload_kwin():
    from PySide6.QtDBus import QDBusConnection, QDBusMessage

    message = QDBusMessage.createMethodCall(
        "org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure"
    )
    if not QDBusConnection.sessionBus().send(message):
        raise RuntimeError("KWin configuration reload could not be sent")


def ensure_overlay_rule() -> bool:
    """Install our narrowly matched user rule before the Qt overlay is shown.

    KConfig tools preserve unrelated rules and KDE-specific escaping. This is
    needed for the Qt fallback on KDE Wayland, not the layer-shell overlay.
    """
    if profile():
        return False  # Candidate runs never edit production compositor rules.
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    if (not sys.platform.startswith("linux")
            or os.environ.get("XDG_SESSION_TYPE") != "wayland"
            or "KDE" not in desktops):
        return True
    tools = _tools()
    if not tools:
        print("[Overlay] KDE config tools missing; cannot install the no-focus rule.")
        return False
    reader, writer = tools
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kwinrulesrc"

    def read(group, key):
        return _run([reader, "--file", str(config), "--group", group,
                     "--key", key, "--default", ""]).stdout.strip()

    def write(group, key, value):
        _run([writer, "--file", str(config), "--group", group,
              "--key", key, value])

    try:
        config.parent.mkdir(parents=True, exist_ok=True)
        changed = False
        for key, value in _RULE.items():
            if read(_RULE_GROUP, key) != value:
                write(_RULE_GROUP, key, value)
                changed = True
        # Register only after every property is written. Never replace other
        # rules, and do not append a duplicate each time Katip starts.
        order = read("General", "Order")
        order_key = "Order" if order else "rules"
        rules = [rule for rule in (order or read("General", "rules")).split(",") if rule]
        if not rules:
            # Older KWin configurations identify their rules as [1], [2], ...
            # until the first explicit list is saved. Preserve those too.
            count = int(read("General", "count") or "0")
            rules = [str(index) for index in range(1, count + 1)]
        # KWin uses the first matching rule for each property. Put our narrow
        # overlay rule before broad personal rules, keeping their relative order.
        ordered_rules = [_RULE_GROUP] + [rule for rule in rules if rule != _RULE_GROUP]
        if ordered_rules != rules:
            write("General", order_key, ",".join(ordered_rules))
            changed = True
        if changed:
            _reload_kwin()
        return True
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, ImportError) as error:
        print(f"[Overlay] Could not configure the KDE no-focus rule: {error}")
        return False
