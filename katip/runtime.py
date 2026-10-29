"""Explicit isolation for candidate runs, shared by config, IPC and desktop entry."""

import os
import re
import zlib


def profile():
    value = os.environ.get("KATIP_PROFILE", "")
    if value and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", value):
        raise RuntimeError("KATIP_PROFILE yalnız küçük harf, rakam ve tire içerebilir (en fazla 32 karakter).")
    return value


def app_id():
    value = profile()
    return f"katip-{value}" if value else "katip"


def ipc_port():
    value = profile()
    return 49215 if not value else 49216 + zlib.crc32(value.encode()) % 10000
