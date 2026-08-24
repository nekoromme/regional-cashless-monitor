"""重複通知を防ぐ状態JSONの安全な読み書き。"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path


EMPTY_STATE = {
    "version": 1,
    "armed": False,
    "baseline_at": None,
    "campaigns": {},
    "source_health": {},
}


def load_state(path: Path) -> dict:
    if not path.exists():
        return deepcopy(EMPTY_STATE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"状態ファイルを読み込めません: {path}: {exc}") from exc

    if data.get("version") != 1 or not isinstance(data.get("campaigns"), dict):
        raise RuntimeError(f"状態ファイルの形式が不正です: {path}")
    data.setdefault("armed", False)
    data.setdefault("baseline_at", None)
    data.setdefault("source_health", {})
    return data


def save_state(path: Path, state: dict) -> None:
    """書込途中の停止でJSONが壊れないよう、一時ファイルから置換する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
