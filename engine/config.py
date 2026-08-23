"""Config loader"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import toml

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "default_config.toml"
_USER_CONFIG_PATH    = Path.home() / ".intent_engine" / "config" / "config.toml"


def get_config() -> dict[str, Any]:
    """
    Load config with user overrides on top of defaults.
    User config at ~/.intent_engine/config/config.toml takes priority.
    """
    config = toml.load(_DEFAULT_CONFIG_PATH)
    if _USER_CONFIG_PATH.exists():
        user_cfg = toml.load(_USER_CONFIG_PATH)
        _deep_merge(config, user_cfg)
    return config


def _deep_merge(base: dict, override: dict) -> None:
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
