"""
Verdict Builder
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Assembles rich Verdict instances from matched patterns, computing dynamic template
interpolations and standardizing risk summaries.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from engine.models import CommandContext, RiskLevel, Verdict
from engine.parser.command_parser import ParsedCommand

_URL_RE = re.compile(r"https?://[^\s'\"]+")
_DEVICE_RE = re.compile(r"/dev/(?:sd|hd|nvme|vd|xvd|loop|mmcblk)[a-zA-Z0-9_-]*")
_PATH_RE = re.compile(r"/(?:[a-zA-Z0-9_.-]+/)*[a-zA-Z0-9_.-]+")


class VerdictBuilder:
    """Helper class to interpolate pattern templates and construct unified Verdicts."""

    @classmethod
    def render_template(
        cls,
        template: str,
        parsed: ParsedCommand,
        ctx: Optional[CommandContext] = None,
    ) -> str:
        """Interpolate dynamic variables in pattern templates."""
        if not template:
            return ""

        context_vars = cls.extract_context_vars(parsed, ctx)

        def _replace_var(match: re.Match) -> str:
            var_name = match.group(1)
            val = context_vars.get(var_name)
            if val is not None and str(val).strip():
                return str(val)
            # Default fallbacks for clean rendering if variable not resolved
            defaults = {
                "path": parsed.arguments[0] if parsed.arguments else "/path/to/target",
                "target": parsed.arguments[0] if parsed.arguments else "target",
                "device": "/dev/sdX",
                "url": "https://example.com/script.sh",
                "script_name": "script.sh",
                "user": ctx.user if ctx else "user",
                "username": ctx.user if ctx else "user",
                "target_host": "remote_host",
            }
            return defaults.get(var_name, match.group(0))

        return re.sub(r"\{(\w+)\}", _replace_var, template)

    @classmethod
    def extract_context_vars(
        cls,
        parsed: ParsedCommand,
        ctx: Optional[CommandContext] = None,
    ) -> dict[str, str]:
        """Extract structured placeholder variables from command context."""
        vars_map: dict[str, str] = {}
        raw = parsed.raw

        # User context
        user = ctx.user if ctx else parsed.user or "user"
        vars_map["user"] = user
        vars_map["username"] = user

        # Extract URL
        url_match = _URL_RE.search(raw)
        if url_match:
            url_str = url_match.group(0)
            vars_map["url"] = url_str
            parsed_url = urlparse(url_str)
            path_part = parsed_url.path.strip("/")
            vars_map["script_name"] = path_part.split("/")[-1] if path_part else "script.sh"
            vars_map["target_host"] = parsed_url.hostname or "remote_host"

        # Extract device node
        dev_match = _DEVICE_RE.search(raw)
        if dev_match:
            vars_map["device"] = dev_match.group(0)

        # Extract target path
        target_path = None
        if parsed.arguments:
            for arg in parsed.arguments:
                if arg.startswith("/") or arg.startswith("~") or arg.startswith("./"):
                    target_path = arg
                    break
            if not target_path and parsed.arguments:
                target_path = parsed.arguments[-1]

        if not target_path:
            path_match = _PATH_RE.search(raw)
            if path_match:
                target_path = path_match.group(0)

        if target_path:
            vars_map["path"] = target_path
            vars_map["target"] = target_path

        vars_map["command"] = parsed.base_command or parsed.raw

        return vars_map

    @classmethod
    def build_verdict(
        cls,
        risk_level: RiskLevel,
        confidence: float,
        reasoning: str,
        impact_summary: str,
        matched_pattern: Optional[str] = None,
        safer_alternative: Optional[str] = None,
        safer_alternative_explanation: Optional[str] = None,
        tier_used: str = "rule_engine",
        latency_ms: float = 0.0,
    ) -> Verdict:
        """Create a validated Verdict instance with clamped confidence."""
        clamped_confidence = max(0.0, min(1.0, float(confidence)))
        return Verdict(
            risk_level=risk_level,
            confidence=round(clamped_confidence, 3),
            matched_pattern=matched_pattern,
            reasoning=reasoning.strip(),
            impact_summary=impact_summary.strip(),
            safer_alternative=safer_alternative.strip() if safer_alternative else None,
            safer_alternative_explanation=safer_alternative_explanation.strip() if safer_alternative_explanation else None,
            tier_used=tier_used,
            latency_ms=round(latency_ms, 2),
        )
