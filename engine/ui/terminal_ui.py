"""
Terminal UI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Minimalist charcoal/monochrome confirmation prompt.
No harsh red — uses ANSI 256-color greys and subtle accents.
Writes an audit entry to ~/.intent_engine/logs/audit.jsonl
for every user decision.

Usage (from shell hook):
  user_action=$(echo "$response" | python3 -m engine.ui.terminal_ui)
"""

from __future__ import annotations

import json
import os
import sys

from engine.audit import log_decision

# ─── ANSI 256-color palette (charcoal/monochrome) ─────────────────────────────
R   = "\033[0m"               # reset
B   = "\033[1m"               # bold
D   = "\033[2m"               # dim

# Grey scale (256-color)
G1  = "\033[38;5;235m"        # darkest charcoal (borders)
G2  = "\033[38;5;241m"        # dark grey
G3  = "\033[38;5;246m"        # mid grey
G4  = "\033[38;5;250m"        # light grey
G5  = "\033[38;5;255m"        # near-white (important text)

# Subtle risk accents (muted, not garish)
A_CRITICAL = "\033[38;5;174m"  # muted rose
A_HIGH     = "\033[38;5;215m"  # soft amber
A_MEDIUM   = "\033[38;5;222m"  # pale gold
A_LOW      = "\033[38;5;110m"  # slate blue
A_SAFE     = "\033[38;5;108m"  # sage green

RISK_ACCENT = {
    "CRITICAL": A_CRITICAL,
    "HIGH":     A_HIGH,
    "MEDIUM":   A_MEDIUM,
    "LOW":      A_LOW,
    "SAFE":     A_SAFE,
}

RISK_GLYPH = {
    "CRITICAL": "◈",
    "HIGH":     "◆",
    "MEDIUM":   "◇",
    "LOW":      "○",
    "SAFE":     "●",
}

RISK_BAR = {
    "CRITICAL": "▰▰▰▰▰▰▰▰▰▰",
    "HIGH":     "▰▰▰▰▰▰▰▰▱▱",
    "MEDIUM":   "▰▰▰▰▰▰▱▱▱▱",
    "LOW":      "▰▰▰▱▱▱▱▱▱▱",
    "SAFE":     "▰▱▱▱▱▱▱▱▱▱",
}

W = 58   # box inner width (visible chars)


def _rule(char: str = "─") -> str:
    return G1 + "  " + char * W + R


def _line(label: str, value: str, accent: str = "") -> str:
    label_part = f"{G3}{label}{G4}"
    value_part = f"{accent}{value}{R}"
    return f"  {G1}│{R}  {label_part}  {value_part}"


def _wrap(text: str, width: int = 48) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def render_prompt(response: dict) -> str:
    v       = response.get("verdict", {})
    risk    = v.get("risk_level", "UNKNOWN")
    conf    = v.get("confidence", 0.0)
    intent  = v.get("intent", "")          # Semantic intent from LLM (PDF Section 3)
    impact  = v.get("impact_summary", "Unknown impact.")
    reason  = v.get("reasoning", "")
    safer   = v.get("safer_alternative")
    safer_x = v.get("safer_alternative_explanation", "")
    accent  = RISK_ACCENT.get(risk, G4)
    glyph   = RISK_GLYPH.get(risk, "◇")
    bar     = RISK_BAR.get(risk, "▱▱▱▱▱▱▱▱▱▱")

    err = sys.stderr
    err.write("\n")

    # ── Header ─────────────────────────────────────────────────────────────────
    err.write(_rule("─") + "\n")
    header = f"  {accent}{B}{glyph}  INTENT ENGINE{R}{G3}  ·  {R}{accent}{B}{risk}{R}{G3}  ·  {conf:.0%} confidence{R}"
    err.write(header + "\n")
    err.write(_rule("─") + "\n")

    # ── Risk bar ───────────────────────────────────────────────────────────────
    err.write(f"  {G1}│{R}  {G3}risk{R}    {accent}{bar}{R}  {G4}{risk}{R}\n")

    # ── Intent (from LLM semantic reasoning — PDF Section 3) ─────────────────
    if intent:
        intent_lines = _wrap(intent, 46)
        for i, line in enumerate(intent_lines[:2]):
            label = f"{G3}intent{R}" if i == 0 else "      "
            err.write(f"  {G1}│{R}  {label}  {G5}{line}{R}\n")

    # ── Impact ─────────────────────────────────────────────────────────────────
    impact_lines = _wrap(impact, 46)
    for i, line in enumerate(impact_lines):
        label = f"{G3}impact{R}" if i == 0 else "      "
        err.write(f"  {G1}│{R}  {label}  {G5}{line}{R}\n")

    # ── Reasoning ──────────────────────────────────────────────────────────────
    if reason:
        reason_lines = _wrap(reason, 46)
        for i, line in enumerate(reason_lines[:3]):
            label = f"{G3}why{R}   " if i == 0 else "       "
            err.write(f"  {G1}│{R}  {label}  {G4}{line}{R}\n")

    # ── Safer alternative ─────────────────────────────────────────────────────
    if safer:
        err.write(_rule("╌") + "\n")
        err.write(f"  {G1}│{R}  {G3}safer{R}   {accent}{B}{safer}{R}\n")
        if safer_x:
            for line in _wrap(safer_x, 46)[:2]:
                err.write(f"  {G1}│{R}           {G3}{line}{R}\n")

    # ── Actions ────────────────────────────────────────────────────────────────
    err.write(_rule("─") + "\n")
    if safer:
        actions = f"{G4}[y]{R} {G3}execute{R}    {G4}[n]{R} {G3}abort{R}    {G4}[s]{R} {G3}use safer{R}"
    else:
        actions = f"{G4}[y]{R} {G3}execute{R}    {G4}[n]{R} {G3}abort{R}"
    err.write(f"  {G1}│{R}  {actions}\n")
    err.write(_rule("─") + "\n")

    # ── Input ──────────────────────────────────────────────────────────────────
    try:
        tty = open("/dev/tty", "r")
        err.write(f"\n  {G3}choice:{R} {G4}")
        err.flush()
        choice = tty.readline().strip().lower()
        err.write(R)
        tty.close()
    except (OSError, EOFError, KeyboardInterrupt):
        err.write(f"\n{G2}  aborted.{R}\n")
        choice = "n"

    err.write("\n")

    if choice == "y":
        action = "EXECUTE"
    elif choice == "s" and safer:
        action = "USE_SAFER"
    else:
        action = "ABORT"

    # ── Write audit entry ────────────────────────────────────────────────────
    ctx = response.get("context", {})
    log_decision(
        command    = ctx.get("command", ""),
        risk_level = risk,
        confidence = conf,
        pattern    = v.get("matched_pattern"),
        tier       = v.get("tier_used", ""),
        action     = action,
        user       = ctx.get("user", os.environ.get("USER", "")),
        cwd        = ctx.get("cwd", ""),
        session_id = response.get("session_id", ""),
        latency_ms = v.get("latency_ms", 0.0),
    )

    return action


def main() -> None:
    try:
        raw = sys.stdin.read()
        response = json.loads(raw)
    except Exception:
        sys.stderr.write(f"{G2}  Intent Engine: failed to parse response.{R}\n")
        print("ABORT")
        sys.exit(1)

    action = render_prompt(response)
    print(action)


if __name__ == "__main__":
    main()
