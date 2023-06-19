"""Remember when each profile was last selected, so recent ones sort first."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from .profiles import home


def state_path(env: Mapping[str, str]) -> Path:
    if env.get("AWSP_STATE_DIR"):
        return Path(env["AWSP_STATE_DIR"]) / "history.json"
    base = env.get("XDG_STATE_HOME") or home(env) / ".local" / "state"
    return Path(base) / "aws-profile-switch" / "history.json"


def load(env: Mapping[str, str]) -> dict[str, float]:
    try:
        data = json.loads(state_path(env).read_text(encoding="utf-8"))
        entries = data["last_used"]
        return {str(k): float(v) for k, v in entries.items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def record(env: Mapping[str, str], name: str, timestamp: float) -> None:
    """Store the selection. Failing to write history never blocks a switch."""
    entries = load(env)
    entries[name] = timestamp
    path = state_path(env)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".history-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"last_used": entries}, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass
