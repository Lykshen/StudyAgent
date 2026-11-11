"""Small JSON config in the data directory (e.g. whether phones on the LAN may connect)."""
import json
import os

from . import db

DEFAULTS = {"lan": False, "port": 8765}


def path():
    return os.path.join(db.DATA_DIR, "config.json")


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            return {**DEFAULTS, **json.load(f)}
    except Exception:
        return dict(DEFAULTS)


def save(**kw):
    c = load()
    c.update(kw)
    os.makedirs(db.DATA_DIR, exist_ok=True)
    with open(path(), "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    return c
