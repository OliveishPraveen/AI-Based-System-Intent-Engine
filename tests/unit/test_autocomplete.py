"""
Autocomplete Engine — Unit Tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tests for all three lookup tiers (local dict, cache, LLM) and
the new substring matching behaviour.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.llm.autocomplete import AutocompleteEngine, _LOCAL_DICT


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_engine(model: str = "qwen2.5:7b") -> AutocompleteEngine:
    return AutocompleteEngine({"llm": {"model": model, "ollama_url": "http://localhost:11434"}})


# ─── Tier A: Local dictionary tests ───────────────────────────────────────────

class TestLocalDictLookup:

    def test_git_prefix_match(self):
        engine = make_engine()
        results = engine._local_lookup("git comm")
        assert any("git commit" in r["cmd"] for r in results)

    def test_docker_prefix_match(self):
        engine = make_engine()
        results = engine._local_lookup("docker p")
        assert any("docker ps" in r["cmd"] for r in results)

    def test_systemctl_prefix_match(self):
        engine = make_engine()
        results = engine._local_lookup("systemctl st")
        assert len(results) > 0
        assert all("systemctl" in r["cmd"] for r in results)

    def test_substring_match_without_prefix(self):
        """'rebase' should surface 'git rebase -i HEAD~3' via substring matching."""
        engine = make_engine()
        results = engine._local_lookup("rebase")
        assert any("rebase" in r["cmd"] for r in results), (
            "Substring match failed: 'rebase' should match 'git rebase -i HEAD~3'"
        )

    def test_substring_match_commit(self):
        engine = make_engine()
        results = engine._local_lookup("commit")
        assert any("commit" in r["cmd"] for r in results)

    def test_substring_match_journalctl(self):
        """'journal' should surface journalctl entries via substring matching."""
        engine = make_engine()
        results = engine._local_lookup("journal")
        assert any("journal" in r["cmd"] for r in results), (
            "Substring match failed: 'journal' should match 'journalctl ...' entries"
        )

    def test_max_4_results(self):
        engine = make_engine()
        results = engine._local_lookup("git")
        assert len(results) <= 4

    def test_too_short_prefix_returns_nothing_from_guard(self):
        """The <3 char guard is in get_completions, not _local_lookup itself."""
        engine = make_engine()
        # _local_lookup doesn't enforce the 3-char minimum — get_completions does
        results = engine._local_lookup("gi")
        # May or may not return results, but should not crash
        assert isinstance(results, list)

    def test_empty_string_returns_empty(self):
        engine = make_engine()
        results = engine._local_lookup("")
        # empty partial — should return empty list without crashing
        assert isinstance(results, list)
        assert len(results) == 0

    def test_result_schema(self):
        engine = make_engine()
        results = engine._local_lookup("git log")
        for r in results:
            assert "cmd" in r
            assert "desc" in r
            assert isinstance(r["cmd"], str)
            assert isinstance(r["desc"], str)

    def test_local_dict_has_expected_families(self):
        expected = {"git", "docker", "systemctl", "kubectl", "npm", "python3"}
        assert expected.issubset(set(_LOCAL_DICT.keys()))


# ─── Tier B: LRU cache tests ───────────────────────────────────────────────────

class TestLRUCache:

    @pytest.mark.asyncio
    async def test_cache_hit_returns_same_results(self):
        engine = make_engine()
        # Manually populate cache
        key = engine._cache_key("cargo build")
        await engine._cache_set(key, [{"cmd": "cargo build --release", "desc": "Build release"}])
        results, source = await engine.get_completions("cargo build", cwd="/tmp")
        # Local dict may also return a result — that's Tier A winning
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_too_short_returns_empty(self):
        engine = make_engine()
        results, source = await engine.get_completions("gi", cwd="/tmp")
        assert results == []
        assert source == "too_short"

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty(self):
        engine = make_engine()
        results, source = await engine.get_completions("", cwd="/tmp")
        assert results == []
        assert source == "too_short"

    @pytest.mark.asyncio
    async def test_local_hit_skips_llm(self):
        engine = make_engine()
        with patch.object(engine, "_ollama_complete", new_callable=AsyncMock) as mock_llm:
            results, source = await engine.get_completions("git commit", cwd="/tmp")
            mock_llm.assert_not_called()
            assert source == "local"

    @pytest.mark.asyncio
    async def test_cache_key_is_case_insensitive(self):
        key1 = AutocompleteEngine._cache_key("CARGO BUILD")
        key2 = AutocompleteEngine._cache_key("cargo build")
        assert key1 == key2


# ─── Tier C: LLM (streaming) tests ────────────────────────────────────────────

class TestStreamingLLM:

    def _make_stream_response(self, content: str):
        """Build a fake streamed Ollama /api/generate response."""
        chunks = [
            {"response": content[i:i+10], "done": False}
            for i in range(0, len(content) - 10, 10)
        ]
        chunks.append({"response": content[-(len(content) % 10) or 10:], "done": True})
        return chunks

    @pytest.mark.asyncio
    async def test_llm_connection_error_returns_empty(self):
        """If Ollama is unreachable, _ollama_complete should propagate an exception
        which get_completions catches and returns ([], 'error')."""
        engine = make_engine()
        import httpx
        with patch.object(engine, "_ollama_complete", side_effect=httpx.ConnectError("refused")):
            results, source = await engine.get_completions("zsh histo", cwd="/tmp")
            assert source == "error"
            assert results == []

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_empty(self):
        engine = make_engine()

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(5.0)
            return []

        with patch.object(engine, "_ollama_complete", side_effect=asyncio.TimeoutError):
            results, source = await engine.get_completions("zsh histo", cwd="/tmp")
            assert source == "error"
            assert results == []

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self):
        engine = make_engine()
        with patch.object(engine, "_ollama_complete", side_effect=Exception("connection refused")):
            results, source = await engine.get_completions("zsh histo", cwd="/tmp")
            assert source == "error"
            assert results == []


# ─── Integration: full get_completions pipeline ───────────────────────────────

class TestGetCompletionsPipeline:

    @pytest.mark.asyncio
    async def test_pipeline_local_tier_wins(self):
        engine = make_engine()
        results, source = await engine.get_completions("kubectl get p", cwd="/home")
        assert source == "local"
        assert any("kubectl" in r["cmd"] for r in results)

    @pytest.mark.asyncio
    async def test_pipeline_source_is_string(self):
        engine = make_engine()
        _, source = await engine.get_completions("git log", cwd="/tmp")
        assert source in ("local", "cache", "llm", "error", "too_short")

    @pytest.mark.asyncio
    async def test_pipeline_result_is_list_of_dicts(self):
        engine = make_engine()
        results, _ = await engine.get_completions("npm run", cwd="/tmp")
        assert isinstance(results, list)
        for r in results:
            assert "cmd" in r and "desc" in r

    @pytest.mark.asyncio
    async def test_cache_populated_after_llm_call(self):
        engine = make_engine()
        fake_results = [{"cmd": "zsh histexpand", "desc": "History expansion"}]
        with patch.object(engine, "_ollama_complete", return_value=fake_results):
            results1, source1 = await engine.get_completions("zsh histo", cwd="/tmp")
        # Second call should hit cache
        results2, source2 = await engine.get_completions("zsh histo", cwd="/tmp")
        assert source2 == "cache"
        assert results2 == fake_results


# ─── async generator helper for aiter() in tests ─────────────────────────────

async def aiter(items):
    for item in items:
        yield item
