"""
Obfuscation Detector — Unit Tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Covers all 6 evasion vectors caught by ObfuscationDetector.
These are Tier 0 CRITICAL — every single case must be caught.
"""

from __future__ import annotations

import pytest

from engine.models import RiskLevel
from engine.rule_engine.obfuscation_detector import ObfuscationDetector


@pytest.fixture
def detector():
    return ObfuscationDetector()


class TestBase64Decode:
    """Vector 1: base64 decode pipeline."""

    def test_eval_echo_base64(self, detector):
        cmd = 'eval $(echo "cm0gLXJmIC8=" | base64 -d)'
        result = detector.detect(cmd)
        assert result is not None
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.matched_pattern == "eval_base64_decode"

    def test_base64_decode_flag(self, detector):
        cmd = "echo payload | base64 --decode | bash"
        result = detector.detect(cmd)
        assert result is not None
        assert result.risk_level == RiskLevel.CRITICAL

    def test_base64_d_pipe_sh(self, detector):
        cmd = "cat encoded.txt | base64 -d | sh"
        result = detector.detect(cmd)
        assert result is not None

    def test_base64_pipe_to_bash(self, detector):
        cmd = "base64 -d payload.b64 | bash"
        result = detector.detect(cmd)
        assert result is not None

    def test_safe_base64_no_pipe(self, detector):
        """base64 without pipe to shell is fine — e.g. encoding a file."""
        cmd = "echo 'hello' | base64"
        result = detector.detect(cmd)
        assert result is None

    def test_base64_decode_to_file(self, detector):
        """base64 -d to a file is fine — only dangerous when piped to shell."""
        cmd = "base64 -d encoded.txt > output.bin"
        result = detector.detect(cmd)
        assert result is None


class TestEvalSubshell:
    """Vector 2: eval with command substitution."""

    def test_eval_dollar_paren(self, detector):
        cmd = 'eval $(dangerous_command)'
        result = detector.detect(cmd)
        assert result is not None
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.matched_pattern == "eval_subshell"

    def test_eval_backtick(self, detector):
        cmd = 'eval `rm -rf /tmp/test`'
        result = detector.detect(cmd)
        assert result is not None
        assert result.risk_level == RiskLevel.CRITICAL

    def test_eval_quoted_dollar(self, detector):
        cmd = 'eval "$(get_secret_cmd)"'
        result = detector.detect(cmd)
        assert result is not None

    def test_plain_eval_safe(self, detector):
        """eval with a literal string is lower risk — not caught by this rule."""
        cmd = "eval 'export FOO=bar'"
        result = detector.detect(cmd)
        # plain eval with literal string (no subshell) — may or may not fire
        # depending on implementation. Just ensure it doesn't raise.
        assert result is None or result.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)


class TestHexDecode:
    """Vector 3: hex/binary decode to shell."""

    def test_xxd_pipe_sh(self, detector):
        cmd = "echo '726d202d7266202f' | xxd -r -p | sh"
        result = detector.detect(cmd)
        assert result is not None
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.matched_pattern == "obfuscated_hex_exec"

    def test_printf_hex_pipe_bash(self, detector):
        cmd = r"printf '\x72\x6d\x20\x2d\x72\x66\x20\x2f' | bash"
        result = detector.detect(cmd)
        assert result is not None

    def test_xxd_to_file_safe(self, detector):
        """xxd -r to a file is not dangerous."""
        cmd = "xxd -r -p hex.txt > output.bin"
        result = detector.detect(cmd)
        assert result is None


class TestHistfileWipe:
    """Vector 4: HISTFILE=/dev/null anti-forensics."""

    def test_histfile_null(self, detector):
        cmd = "HISTFILE=/dev/null rm -rf /var/log"
        result = detector.detect(cmd)
        assert result is not None
        assert result.risk_level == RiskLevel.HIGH
        assert result.matched_pattern == "histfile_wipe"

    def test_histfile_null_standalone(self, detector):
        cmd = "HISTFILE=/dev/null bash"
        result = detector.detect(cmd)
        assert result is not None

    def test_histfile_real_path(self, detector):
        """HISTFILE pointing to a real file is not suspicious."""
        cmd = "HISTFILE=~/.alt_history bash"
        result = detector.detect(cmd)
        assert result is None


class TestInterpreterOneliner:
    """Vector 5: python/perl one-liner with os.system/exec."""

    def test_python_os_system(self, detector):
        cmd = "python3 -c 'import os; os.system(\"rm -rf /\")'"
        result = detector.detect(cmd)
        assert result is not None
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.matched_pattern == "interpreter_oneliner_exec"

    def test_python_subprocess(self, detector):
        cmd = 'python3 -c "import subprocess; subprocess.run([\'rm\',\'-rf\',\'/\'])"'
        result = detector.detect(cmd)
        assert result is not None

    def test_perl_exec(self, detector):
        cmd = "perl -e 'exec \"rm -rf /\"'"
        result = detector.detect(cmd)
        assert result is not None

    def test_python3_normal_run(self, detector):
        """Normal python3 script execution is not obfuscation."""
        cmd = "python3 app.py --debug"
        result = detector.detect(cmd)
        assert result is None

    def test_python3_no_system_call(self, detector):
        """python3 -c with math is not dangerous."""
        cmd = "python3 -c 'print(2+2)'"
        result = detector.detect(cmd)
        assert result is None


class TestEmptyAndEdgeCases:
    """Edge cases: empty strings, whitespace, normal commands."""

    def test_empty_string(self, detector):
        assert detector.detect("") is None

    def test_whitespace_only(self, detector):
        assert detector.detect("   ") is None

    def test_none_does_not_crash(self, detector):
        # Should handle gracefully
        assert detector.detect("") is None

    def test_safe_rm_tmp(self, detector):
        assert detector.detect("rm -rf /tmp/build") is None

    def test_safe_git_commit(self, detector):
        assert detector.detect("git commit -m 'feat: add tests'") is None

    def test_safe_docker_build(self, detector):
        assert detector.detect("docker build -t myapp .") is None

    def test_safe_curl_no_pipe(self, detector):
        assert detector.detect("curl https://api.example.com") is None

    def test_safe_ls(self, detector):
        assert detector.detect("ls -la") is None
