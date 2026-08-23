"""
Obfuscation Detector
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Pre-parse scan that fires BEFORE the main pattern matcher.
Catches commands that use encoding/eval tricks to hide their true intent.

Known evasion vectors caught:
  1. eval $(echo "..." | base64 -d)        — base64-encoded payload → shell
  2. echo "..." | base64 -d | bash         — pipe decode to shell
  3. echo "..." | xxd -r [-p] | sh         — hex-encoded payload (any flag order)
  4. eval `dangerous_cmd`                  — backtick eval / subshell eval
  5. HISTFILE=/dev/null dangerous_cmd      — history evasion
  6. python3 -c '..os.system...'           — interpreter one-liners
  7. perl -e '...exec...'                  — perl pipe-exec one-liners
"""

from __future__ import annotations

import re
from typing import Optional

from engine.models import RiskLevel, Verdict
from engine.rule_engine.verdict_builder import VerdictBuilder

# ── Compiled Tier 0 Obfuscation Patterns ──────────────────────────────────────

# 1. base64 decode piped to shell.
#    Only dangerous when the decoded output is piped to a shell interpreter.
#    `base64 -d file > output.bin` is NOT dangerous (redirected to file).
_BASE64_DECODE_RE = re.compile(
    # Pattern A: base64 -d | sh  (output piped directly to shell)
    r"base64\s+(?:-d|--decode)\s*\|"
    # Pattern B: base64 -d ... | sh  (any intermediate piping)
    r"|base64\s+(?:-d|--decode).*?\|\s*(?:sudo\s+)?(?:ba|z|k|c)?sh\b"
    # Pattern C: eval $(... base64 -d)
    r"|eval\b.*?\bbase64\s+(?:-d|--decode)",
    re.IGNORECASE | re.DOTALL,
)

# 2. eval with any command substitution that feeds a shell.
#    eval $(cmd) / eval `cmd` / eval "$(cmd)"
_EVAL_SUBSHELL_RE = re.compile(
    r"""\beval\b\s*["`$]""",
    re.IGNORECASE,
)

# 3. Hex/binary decode piped to a shell interpreter.
#    Handles: xxd -r -p | sh, xxd -p -r | sh, printf '\x41\x42' | bash
#    The xxd pattern matches -r flag anywhere in the argument list.
_HEX_DECODE_RE = re.compile(
    # xxd with -r flag (may appear as -r, -rp, etc.) piped to shell
    r"xxd\s+(?:-\S+\s+)*-\S*r\S*(?:\s+-\S+)*\s*\|\s*(?:sudo\s+)?(?:ba|z|k|c)?sh\b"
    r"|xxd\b.*?-r\b.*?\|\s*(?:sudo\s+)?(?:ba|z|k|c)?sh\b"
    # od -c piped to shell
    r"|od\s+-\S*c\S*.*?\|\s*(?:sudo\s+)?(?:ba|z|k|c)?sh\b"
    # printf with hex escape sequences piped to shell
    # In Python raw strings: \\ = one backslash in regex = matches literal backslash
    r"|printf\s+['\"](?:\\x[0-9a-fA-F]{1,2})+['\"]?\s*\|\s*(?:sudo\s+)?(?:ba|z|k|c)?sh\b",
    re.IGNORECASE,
)

# 4. HISTFILE=/dev/null — deliberate history erasure to hide what ran.
_HISTFILE_WIPE_RE = re.compile(
    r"HISTFILE\s*=\s*/dev/null",
    re.IGNORECASE,
)

# 5. Python/ruby/node one-liner used to spawn system commands (use -c flag).
#    perl uses -e flag (not -c) and has different dangerous call patterns.
_INTERPRETER_ONELINER_RE = re.compile(
    # python3/ruby/node with -c flag and dangerous function calls
    r"(?:python3?|ruby|node)\s+-c\s+['\"].*?(?:os\.system|subprocess|exec|eval|__import__)"
    # perl with -e flag and dangerous calls (exec, system, unlink, open pipe)
    r"|perl\s+-e\s+['\"].*?(?:system\s*\(|exec\s*[\"'(]|unlink\s*\(|rmdir\s*\(|open\s*\(\s*['\"]?\s*\|)",
    re.IGNORECASE | re.DOTALL,
)

# 6. declare/typeset tricks: declare -x VAR='eval $(...)' && eval $VAR
_DECLARE_EVAL_RE = re.compile(
    r"(?:declare|typeset)\s+.*=.*eval",
    re.IGNORECASE,
)


class ObfuscationDetector:
    """
    Pre-parse Tier 0 scan for encoding/eval evasion techniques.
    Called by the classifier BEFORE pattern_matcher.check_tier0().
    Returns a Verdict immediately if any evasion pattern is found, else None.
    """

    def detect(self, raw: str) -> Optional[Verdict]:
        if not raw or not raw.strip():
            return None

        s = raw.strip()

        # 1. base64 decode piped to shell
        if _BASE64_DECODE_RE.search(s):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="eval_base64_decode",
                reasoning=(
                    "Base64 decode pipeline detected. Commands that decode an "
                    "encoded payload at runtime are a classic evasion technique used "
                    "to hide malicious commands from security scanners and shell history."
                ),
                impact_summary=(
                    "Executes a hidden, encoded payload — the true command is not "
                    "visible in your shell history or terminal output."
                ),
                safer_alternative=None,
                safer_alternative_explanation=(
                    "If you need to run a script, save it to a file, inspect it, then run it directly."
                ),
                tier_used="rule_engine",
            )

        # 2. eval with subshell
        if _EVAL_SUBSHELL_RE.search(s):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="eval_subshell",
                reasoning=(
                    "eval with command substitution detected. eval executes its argument "
                    "as a shell command — when combined with $() or backticks, the actual "
                    "command being run is dynamically generated and invisible before execution."
                ),
                impact_summary=(
                    "Dynamically generates and executes a command that cannot be "
                    "pre-inspected. High risk of hidden malicious execution."
                ),
                safer_alternative=None,
                safer_alternative_explanation=(
                    "Assign the computed value to a variable, inspect it, then run explicitly."
                ),
                tier_used="rule_engine",
            )

        # 3. Hex/binary decode to shell
        if _HEX_DECODE_RE.search(s):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=1.0,
                matched_pattern="obfuscated_hex_exec",
                reasoning=(
                    "Hex or binary decode pipeline feeding a shell interpreter. "
                    "This pattern encodes a shell command as hex bytes and pipes "
                    "the decoded output directly to sh/bash for execution."
                ),
                impact_summary=(
                    "Executes a hidden binary-encoded payload. "
                    "True command content is invisible without manual decoding."
                ),
                safer_alternative=None,
                safer_alternative_explanation=(
                    "Never pipe decoded binary data directly into a shell. "
                    "Decode first, inspect the content, then decide."
                ),
                tier_used="rule_engine",
            )

        # 4. HISTFILE wipe
        if _HISTFILE_WIPE_RE.search(s):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.HIGH,
                confidence=0.95,
                matched_pattern="histfile_wipe",
                reasoning=(
                    "HISTFILE=/dev/null detected. This environment variable prefix "
                    "routes all shell history to /dev/null, effectively erasing the "
                    "audit trail for the current session. This is a deliberate "
                    "anti-forensics technique."
                ),
                impact_summary=(
                    "Disables shell history logging for this command, hiding it "
                    "from all terminal audit tools and ~/.bash_history."
                ),
                safer_alternative=None,
                safer_alternative_explanation=(
                    "Remove the HISTFILE prefix. If you need to run a sensitive command, "
                    "discuss it with your system administrator."
                ),
                tier_used="rule_engine",
            )

        # 5. Interpreter one-liner with system call
        if _INTERPRETER_ONELINER_RE.search(s):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.CRITICAL,
                confidence=0.95,
                matched_pattern="interpreter_oneliner_exec",
                reasoning=(
                    "Python/Perl/Ruby one-liner containing os.system, exec, or system() detected. "
                    "This is frequently used to bypass shell-level security controls by "
                    "running system commands through a language interpreter."
                ),
                impact_summary=(
                    "Executes a system command through a language interpreter, "
                    "potentially bypassing shell-level security hooks."
                ),
                safer_alternative=None,
                safer_alternative_explanation=(
                    "Run the target command directly in the shell so the Intent Engine "
                    "can inspect it properly."
                ),
                tier_used="rule_engine",
            )

        # 6. declare/typeset eval trick
        if _DECLARE_EVAL_RE.search(s):
            return VerdictBuilder.build_verdict(
                risk_level=RiskLevel.HIGH,
                confidence=0.90,
                matched_pattern="declare_eval_trick",
                reasoning=(
                    "declare/typeset assignment combined with eval detected. "
                    "This is a multi-step obfuscation technique."
                ),
                impact_summary=(
                    "Potential eval-based command obfuscation via shell variable assignment."
                ),
                safer_alternative=None,
                safer_alternative_explanation=(
                    "Run the target command directly without the declare/eval indirection."
                ),
                tier_used="rule_engine",
            )

        return None
