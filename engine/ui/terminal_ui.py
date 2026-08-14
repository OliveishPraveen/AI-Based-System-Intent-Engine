"""
Terminal UI — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ANSI-based confirmation prompt shown to the user when a risky command is detected.
Reads AnalyzeResponse JSON from stdin (piped by the shell hook).
Prints the user's action to stdout: EXECUTE | ABORT | EDIT | USE_SAFER

Usage (from shell hook):
  echo "$response" | python3 -m engine.ui.terminal_ui
"""

from __future__ import annotations

import json
import sys
from typing import Optional

# ─── ANSI Colors ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
DIM    = "\033[2m"

RISK_COLORS = {
    "CRITICAL": RED,
    "HIGH":     RED,
    "MEDIUM":   YELLOW,
    "LOW":      CYAN,
    "SAFE":     GREEN,
}

RISK_BARS = {
    "CRITICAL": "██████████",
    "HIGH":     "████████░░",
    "MEDIUM":   "██████░░░░",
    "LOW":      "████░░░░░░",
    "SAFE":     "██░░░░░░░░",
}


def render_prompt(response: dict) -> Optional[str]:
    """
    Render the confirmation UI and return the user's chosen action.
    Returns None if the response is malformed.
    """
    verdict = response.get("verdict", {})
    risk = verdict.get("risk_level", "UNKNOWN")
    command = response.get("verdict", {}).get("matched_pattern", "")
    # Extract original command from response if available
    raw_command = verdict.get("reasoning", "")[:80]
    impact = verdict.get("impact_summary", "Unknown impact")
    reasoning = verdict.get("reasoning", "")
    safer = verdict.get("safer_alternative")
    color = RISK_COLORS.get(risk, WHITE)
    bar = RISK_BARS.get(risk, "░░░░░░░░░░")

    print(f"\n{color}{BOLD}", end="", file=sys.stderr)
    print("╔══════════════════════════════════════════════════════════╗", file=sys.stderr)
    print(f"║  ⚠  INTENT ENGINE — {risk:<37}║", file=sys.stderr)
    print("╠══════════════════════════════════════════════════════════╣", file=sys.stderr)
    print(f"║  Risk    : {bar} {risk:<14}               ║", file=sys.stderr)
    print(f"║  Impact  : {impact[:54]:<54}  ║", file=sys.stderr)

    if reasoning:
        # Word-wrap reasoning to 54 chars
        words = reasoning.split()
        line = ""
        for word in words[:30]:  # Limit display length
            if len(line) + len(word) + 1 > 54:
                print(f"║  Detail  : {line:<54}  ║", file=sys.stderr)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            print(f"║          : {line:<54}  ║", file=sys.stderr)

    if safer:
        print("╠══════════════════════════════════════════════════════════╣", file=sys.stderr)
        print(f"║  Safer   : {safer[:54]:<54}  ║", file=sys.stderr)

    print("╠══════════════════════════════════════════════════════════╣", file=sys.stderr)
    if safer:
        print("║  [y] Execute original  [n] Abort  [e] Edit  [s] Safer   ║", file=sys.stderr)
    else:
        print("║  [y] Execute original  [n] Abort  [e] Edit              ║", file=sys.stderr)
    print("╚══════════════════════════════════════════════════════════╝", file=sys.stderr)
    print(f"{RESET}", end="", file=sys.stderr)

    # Read user input
    try:
        sys.stderr.write("Your choice: ")
        sys.stderr.flush()
        choice = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "ABORT"

    if choice == "y":
        return "EXECUTE"
    elif choice == "n" or choice == "":
        return "ABORT"
    elif choice == "e":
        return "EDIT"
    elif choice == "s" and safer:
        return "USE_SAFER"
    else:
        return "ABORT"


def main() -> None:
    """Entry point: read JSON from stdin, render prompt, print action to stdout."""
    try:
        raw = sys.stdin.read()
        response = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        print("ABORT")
        sys.exit(1)

    action = render_prompt(response)
    print(action or "ABORT")


if __name__ == "__main__":
    main()
