"""Regression coverage for the KDE Wayland overlay's no-focus rule."""

import re
import subprocess
from unittest.mock import Mock

import pytest

from katip import kde


@pytest.fixture
def kconfig(monkeypatch, tmp_path):
    monkeypatch.setattr(kde.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(kde, "_tools", lambda: ("reader", "writer"))
    values = {
        ("General", "rules"): "personal-rule,another-rule",
        ("personal-rule", "Description"): "Kişisel pencere ayarı",
        ("personal-rule", "acceptfocus"): "true",
    }
    writes = []

    def run(args):
        assert args[args.index("--file") + 1] == str(tmp_path / "kwinrulesrc")
        group = args[args.index("--group") + 1]
        key = args[args.index("--key") + 1]
        if args[0] == "reader":
            return subprocess.CompletedProcess(args, 0, values.get((group, key), ""), "")
        writes.append((group, key, args[-1]))
        values[group, key] = args[-1]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(kde, "_run", run)
    reload = Mock()
    monkeypatch.setattr(kde, "_reload_kwin", reload)
    return values, writes, reload


def test_installs_rule_without_losing_other_rules(kconfig):
    values, writes, reload = kconfig
    assert kde.ensure_overlay_rule()
    assert values["General", "rules"].split(",") == [
        "KatipOverlay", "personal-rule", "another-rule"
    ]
    assert values["personal-rule", "Description"] == "Kişisel pencere ayarı"
    assert values["personal-rule", "acceptfocus"] == "true"
    assert values["KatipOverlay", "acceptfocus"] == "false"
    assert values["KatipOverlay", "above"] == "true"
    assert writes[-1][:2] == ("General", "rules")
    reload.assert_called_once()


def test_rule_matches_packaged_title_but_not_dialogs(kconfig):
    values, _, _ = kconfig
    assert kde.ensure_overlay_rule()
    pattern = values["KatipOverlay", "title"]
    assert re.fullmatch(pattern, "Katip Recording Overlay")
    assert re.fullmatch(pattern, "Katip Recording Overlay — Kâtip")
    assert not re.fullmatch(pattern, "Kâtip Ayarları")
    assert not re.fullmatch(pattern, "Kâtip — Son Sonuç")
    assert values["KatipOverlay", "wmclass"] == "katip"
    assert values["KatipOverlay", "titlematch"] == "3"


def test_migrates_old_exact_title_rule_and_is_idempotent(kconfig):
    values, writes, reload = kconfig
    values["General", "rules"] += ",KatipOverlay"
    values["KatipOverlay", "title"] = "Katip Recording Overlay"
    values["KatipOverlay", "titlematch"] = "1"
    assert kde.ensure_overlay_rule()
    count = len(writes)
    assert kde.ensure_overlay_rule()
    assert len(writes) == count
    assert values["General", "rules"].count("KatipOverlay") == 1
    reload.assert_called_once()


def test_preserves_legacy_numbered_rules(kconfig):
    values, _, _ = kconfig
    values["General", "rules"] = ""
    values["General", "count"] = "2"
    values["1", "Description"] = "Legacy personal rule"
    assert kde.ensure_overlay_rule()
    assert values["General", "rules"] == "KatipOverlay,1,2"
    assert values["1", "Description"] == "Legacy personal rule"


def test_preserves_newer_order_format(kconfig):
    values, _, _ = kconfig
    values["General", "Order"] = "personal-rule,another-rule"
    values.pop(("General", "rules"))
    assert kde.ensure_overlay_rule()
    assert values["General", "Order"] == "KatipOverlay,personal-rule,another-rule"
    assert ("General", "rules") not in values


@pytest.mark.parametrize("session,desktop", [("x11", "KDE"), ("wayland", "GNOME")])
def test_other_desktops_are_untouched(kconfig, monkeypatch, session, desktop):
    _, writes, reload = kconfig
    monkeypatch.setenv("XDG_SESSION_TYPE", session)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    assert kde.ensure_overlay_rule()
    assert not writes
    reload.assert_not_called()


def test_failed_write_does_not_register_partial_rule(kconfig, monkeypatch):
    values, _, reload = kconfig
    run = kde._run

    def fail_write(args):
        if args[0] == "writer" and args[args.index("--key") + 1] == "acceptfocus":
            raise subprocess.CalledProcessError(1, "writer")
        return run(args)

    monkeypatch.setattr(kde, "_run", fail_write)
    assert not kde.ensure_overlay_rule()
    assert values["General", "rules"] == "personal-rule,another-rule"
    reload.assert_not_called()


def test_missing_tools_are_reported_without_crashing(kconfig, monkeypatch, capsys):
    _, writes, reload = kconfig
    monkeypatch.setattr(kde, "_tools", lambda: None)
    assert not kde.ensure_overlay_rule()
    assert "config tools missing" in capsys.readouterr().out
    assert not writes
    reload.assert_not_called()


def test_frozen_application_does_not_leak_qt_libraries(monkeypatch):
    monkeypatch.setattr(kde.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI/bundled")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/system/libs")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/tmp/_MEI/plugins")
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "/tmp/_MEI/platforms")
    run = Mock()
    monkeypatch.setattr(kde.subprocess, "run", run)
    kde._run(["writer"])
    env = run.call_args.kwargs["env"]
    assert env["LD_LIBRARY_PATH"] == "/system/libs"
    assert "QT_PLUGIN_PATH" not in env
    assert "QT_QPA_PLATFORM_PLUGIN_PATH" not in env
