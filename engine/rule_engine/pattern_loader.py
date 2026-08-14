"""
Pattern Loader — Owner: Praveen
Loads, validates, and caches patterns from rules/dangerous_patterns.toml
"""

from __future__ import annotations

from pathlib import Path

import toml

_RULES_PATH = Path(__file__).parent.parent.parent / "rules" / "dangerous_patterns.toml"


class PatternLoader:
    """Loads pattern definitions from the TOML pattern library."""

    async def load(self, path: Path = _RULES_PATH) -> list[dict]:
        """Load and return the list of pattern dicts from the TOML file."""
        if not path.exists():
            raise FileNotFoundError(f"Pattern library not found: {path}")
        data = toml.load(path)
        patterns = data.get("patterns", [])
        self._validate(patterns)
        return patterns

    def _validate(self, patterns: list[dict]) -> None:
        required_keys = {"name", "tier", "risk_level", "reasoning_template", "impact_template"}
        for p in patterns:
            missing = required_keys - p.keys()
            if missing:
                raise ValueError(f"Pattern '{p.get('name', '?')}' missing keys: {missing}")
