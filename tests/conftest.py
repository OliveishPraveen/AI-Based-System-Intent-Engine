"""
Test fixtures and shared utilities for the Intent Engine test suite.

All tests should use these fixtures rather than constructing raw objects directly.
"""

from __future__ import annotations

import pytest


def pytest_configure(config):
    """Enable asyncio_mode=auto only when pytest-asyncio is installed."""
    try:
        import pytest_asyncio  # noqa: F401
        config.option.__dict__.setdefault("asyncio_mode", "auto")
    except (ImportError, AttributeError):
        pass

from engine.models import CommandContext, RiskLevel
from engine.parser.command_parser import CommandParser, ParsedCommand


@pytest.fixture
def parser() -> CommandParser:
    return CommandParser()


@pytest.fixture
def default_context() -> CommandContext:
    return CommandContext(
        command="",
        cwd="/home/testuser",
        user="testuser",
        is_sudo=False,
        shell="bash",
        session_id="test-session-001",
    )


@pytest.fixture
def root_context() -> CommandContext:
    return CommandContext(
        command="",
        cwd="/root",
        user="root",
        is_sudo=True,
        shell="zsh",
        session_id="test-session-root",
    )


def make_context(command: str, **kwargs) -> CommandContext:
    """Helper: create a CommandContext for a given command."""
    defaults = dict(
        cwd="/home/testuser",
        user="testuser",
        is_sudo=command.strip().startswith("sudo"),
        shell="bash",
        session_id="test-session-001",
    )
    defaults.update(kwargs)
    return CommandContext(command=command, **defaults)
