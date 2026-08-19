"""
Pattern Loader — Owner: Praveen (OliveishPraveen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Loads, validates, normalizes, and caches patterns from rules/dangerous_patterns.toml.
Provides hot-reloading capabilities for runtime pattern updates without service restart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import toml
import structlog

log = structlog.get_logger()

_DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "rules" / "dangerous_patterns.toml"
_REQUIRED_KEYS = {"name", "tier", "risk_level", "reasoning_template", "impact_template"}


class PatternLoader:
    """Loads and validates pattern definitions from the TOML pattern library."""

    def __init__(self, default_path: Path = _DEFAULT_RULES_PATH) -> None:
        self._default_path = default_path
        self._cached_patterns: Optional[list[dict[str, Any]]] = None
        self._last_loaded_path: Optional[Path] = None

    async def load(self, path: Optional[Path] = None, force_reload: bool = False) -> list[dict[str, Any]]:
        """Asynchronously load and return the list of pattern dicts."""
        return self.load_sync(path=path, force_reload=force_reload)

    def load_sync(self, path: Optional[Path] = None, force_reload: bool = False) -> list[dict[str, Any]]:
        """Synchronously load and return the list of pattern dicts from TOML."""
        target_path = path or self._default_path

        if not force_reload and self._cached_patterns is not None and self._last_loaded_path == target_path:
            return self._cached_patterns

        if not target_path.exists():
            log.error("pattern_library_missing", path=str(target_path))
            raise FileNotFoundError(f"Pattern library not found at: {target_path}")

        try:
            data = toml.load(target_path)
        except Exception as e:
            log.error("pattern_library_parse_error", path=str(target_path), error=str(e))
            raise ValueError(f"Failed to parse TOML pattern library at {target_path}: {e}") from e

        raw_patterns = data.get("patterns", [])
        validated = self._validate_and_normalize(raw_patterns, source=str(target_path))

        self._cached_patterns = validated
        self._last_loaded_path = target_path
        log.info("patterns_loaded_successfully", count=len(validated), path=str(target_path))
        return self._cached_patterns

    def reload(self, path: Optional[Path] = None) -> list[dict[str, Any]]:
        """Force a fresh reload of the pattern library."""
        return self.load_sync(path=path, force_reload=True)

    def _validate_and_normalize(self, patterns: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
        """Validate required fields and normalize types for pattern entries."""
        validated: list[dict[str, Any]] = []

        for idx, p in enumerate(patterns):
            name = p.get("name", f"pattern_{idx}")
            missing = _REQUIRED_KEYS - p.keys()
            if missing:
                err_msg = f"Pattern '{name}' (entry #{idx} in {source}) missing required keys: {sorted(missing)}"
                log.error("invalid_pattern_schema", name=name, missing=list(missing))
                raise ValueError(err_msg)

            # Normalize values
            normalized = dict(p)
            normalized["tier"] = int(p.get("tier", 1))
            normalized["risk_level"] = str(p.get("risk_level", "HIGH")).upper()
            normalized["commands"] = list(p.get("commands", []))
            normalized["regex"] = str(p.get("regex", "")) if p.get("regex") else None
            normalized["reasoning_template"] = str(p.get("reasoning_template", "")).strip()
            normalized["impact_template"] = str(p.get("impact_template", "")).strip()
            normalized["safer_alternative"] = str(p.get("safer_alternative", "")).strip() if p.get("safer_alternative") else None
            normalized["safer_explanation"] = str(p.get("safer_explanation", "")).strip() if p.get("safer_explanation") else None
            normalized["category"] = str(p.get("category", "general")).strip().lower()

            validated.append(normalized)

        return validated
