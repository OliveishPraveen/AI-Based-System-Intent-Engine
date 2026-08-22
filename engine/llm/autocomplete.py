"""
Autocomplete Engine — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLI Copilot: LLM-powered shell command autocomplete.
Completely separate from the safety engine pipeline.

3-Tier speed strategy:
  Tier A: Local dictionary       → 0ms   (hardcoded common commands)
  Tier B: LRU prefix cache       → 0ms   (repeated queries in session)
  Tier C: Streaming Ollama call  → 80–300ms first token

Design constraints:
  - NEVER blocks the keystroke. All calls are async.
  - Minimum prefix length: 3 chars (prevents spamming on 'l', 'ls')
  - Hard timeout: 800ms (vs 3s for safety engine)
  - Returns empty list on any error (graceful degradation)
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_OLLAMA_BASE = "http://localhost:11434"
_AUTOCOMPLETE_TIMEOUT_S = 0.8   # 800ms hard cap — faster than the safety engine's 3s
_MIN_PREFIX_LEN = 3              # Don't fire LLM for 1-2 char prefixes
_CACHE_MAX_SIZE = 64             # LRU eviction after 64 unique prefixes

# ─── Tier A: Local Command Dictionary ─────────────────────────────────────────
# Covers the 20 most common command families. Shown instantly with 0ms latency.
# Key = first word of the partial command.
_LOCAL_DICT: dict[str, list[tuple[str, str]]] = {
    "git": [
        ("git commit -m \"\"",              "Commit staged changes with message"),
        ("git push origin",                 "Push current branch to remote"),
        ("git pull --rebase",               "Fetch + rebase on upstream"),
        ("git rebase -i HEAD~3",            "Interactively rebase last 3 commits"),
        ("git stash push -m \"\"",          "Stash uncommitted changes with label"),
        ("git log --oneline --graph",       "Compact visual commit history"),
        ("git checkout -b ",                "Create and switch to new branch"),
        ("git diff --staged",               "Show staged changes before commit"),
    ],
    "docker": [
        ("docker ps -a",                    "List all containers (running + stopped)"),
        ("docker build -t  .",              "Build image from current Dockerfile"),
        ("docker run -it --rm ",            "Run container interactively, auto-remove"),
        ("docker-compose up -d",            "Start all services in background"),
        ("docker exec -it  bash",           "Open shell in running container"),
        ("docker logs -f ",                 "Follow container log output"),
    ],
    "systemctl": [
        ("systemctl status ",               "Show service status and recent logs"),
        ("systemctl restart ",              "Restart a system service"),
        ("systemctl enable --now ",         "Enable and immediately start a service"),
        ("systemctl list-units --failed",   "Show all failed units"),
    ],
    "kubectl": [
        ("kubectl get pods -n ",            "List pods in namespace"),
        ("kubectl logs -f ",                "Follow pod logs"),
        ("kubectl apply -f ",               "Apply manifest from file"),
        ("kubectl describe pod ",           "Show pod details and events"),
        ("kubectl exec -it  -- bash",       "Open shell in pod"),
    ],
    "npm": [
        ("npm run dev",                     "Start development server"),
        ("npm install ",                    "Install a package"),
        ("npm run build",                   "Build production bundle"),
        ("npm test",                        "Run test suite"),
    ],
    "cargo": [
        ("cargo build --release",           "Build optimized release binary"),
        ("cargo test",                      "Run all tests"),
        ("cargo clippy",                    "Lint with Clippy"),
        ("cargo add ",                      "Add a dependency"),
    ],
    "python3": [
        ("python3 -m venv .venv",           "Create virtual environment"),
        ("python3 -m pytest",               "Run test suite with pytest"),
        ("python3 -m pip install ",         "Install package via pip"),
        ("python3 -m http.server 8080",     "Quick local HTTP server"),
    ],
    "ssh": [
        ("ssh -i ~/.ssh/id_ed25519 ",       "Connect using ed25519 key"),
        ("ssh -L 8080:localhost:8080 ",     "Create local port forward tunnel"),
    ],
    "curl": [
        ("curl -s  | jq .",                 "Fetch JSON and pretty-print"),
        ("curl -X POST -H 'Content-Type: application/json' -d '{}'", "POST JSON body"),
        ("curl -o  ",                       "Download file to disk"),
    ],
    "find": [
        ("find . -name '*.py' -type f",     "Find all Python files recursively"),
        ("find . -mtime -1 -type f",        "Files modified in last 24 hours"),
        ("find /tmp -name '*.log' -delete", "Delete old log files in /tmp"),
    ],
    "grep": [
        ("grep -rn  .",                     "Recursive search with line numbers"),
        ("grep -rn --include='*.py'  .",    "Search only Python files"),
    ],
    "tar": [
        ("tar -czf archive.tar.gz ",        "Create compressed archive"),
        ("tar -xzf ",                       "Extract compressed archive"),
    ],
    "rsync": [
        ("rsync -avzP  user@host:",         "Sync folder to remote with progress"),
        ("rsync -avz --delete  ",           "Sync and delete removed files"),
    ],
    "journalctl": [
        ("journalctl -u  -f",               "Follow logs for specific service"),
        ("journalctl --since '1 hour ago'", "Logs from the last hour"),
        ("journalctl -p err -b",            "Errors since last boot"),
    ],
}


class AutocompleteEngine:
    """
    3-tier command completion engine.

    Usage:
        engine = AutocompleteEngine(config)
        completions = await engine.get_completions(partial="git re", cwd="/home/user")
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._model = config.get("llm", {}).get("model", "llama3.2:3b")
        self._ollama_url = config.get("llm", {}).get("ollama_url", _OLLAMA_BASE)
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._ollama_healthy: bool | None = None  # None = not yet checked

    async def get_completions(
        self,
        partial: str,
        cwd: str = "",
    ) -> tuple[list[dict], str]:
        """
        Return (completions, source) where source is 'local' | 'cache' | 'llm'.

        Never raises — returns ([], 'error') on any failure.
        """
        t0 = time.perf_counter()
        partial = partial.strip()

        # Guard: minimum prefix length
        if len(partial) < _MIN_PREFIX_LEN:
            return [], "too_short"

        # ── Tier A: Local dictionary ───────────────────────────────────────────
        local_results = self._local_lookup(partial)
        if local_results:
            log.debug("autocomplete_local_hit", prefix=partial[:20])
            return local_results, "local"

        # ── Tier B: LRU cache ──────────────────────────────────────────────────
        cache_key = self._cache_key(partial)
        async with self._cache_lock:
            if cache_key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(cache_key)
                cached = self._cache[cache_key]
                log.debug("autocomplete_cache_hit", prefix=partial[:20])
                return cached, "cache"

        # ── Tier C: Streaming Ollama ───────────────────────────────────────────
        try:
            results = await asyncio.wait_for(
                self._ollama_complete(partial, cwd),
                timeout=_AUTOCOMPLETE_TIMEOUT_S,
            )
            if results:
                await self._cache_set(cache_key, results)
                elapsed = (time.perf_counter() - t0) * 1000
                log.debug("autocomplete_llm_result", prefix=partial[:20], latency_ms=round(elapsed, 1))
                return results, "llm"
        except asyncio.TimeoutError:
            log.debug("autocomplete_llm_timeout", prefix=partial[:20])
        except Exception as e:
            log.debug("autocomplete_llm_error", error=str(e)[:80])

        return [], "error"

    def _local_lookup(self, partial: str) -> list[dict]:
        """
        Check the local dictionary for completions matching the partial command.

        Match priority (stops at first hit):
        1. Prefix match by first word  (e.g. "git co" → "git commit -m ...")
        2. Prefix match across all entries  (e.g. "docker ps" → exact prefix)
        3. Substring match  (e.g. "commit" → "git commit -m ..." — fish-style)
        """
        if not partial or not partial.strip():
            return []

        first_word = partial.split()[0] if partial.split() else ""
        results: list[dict] = []

        # ── Tier 1: exact first-word match in local dict ──────────────────────
        if first_word in _LOCAL_DICT:
            for cmd, desc in _LOCAL_DICT[first_word]:
                if cmd.startswith(partial) or partial in cmd:
                    results.append({"cmd": cmd, "desc": desc})
        if results:
            return results[:4]

        # ── Tier 2: prefix match across ALL entries ───────────────────────────
        for cmd_list in _LOCAL_DICT.values():
            for cmd, desc in cmd_list:
                if cmd.startswith(partial):
                    results.append({"cmd": cmd, "desc": desc})
        if results:
            return results[:4]

        # ── Tier 3: substring / contains match (fish-style) ──────────────────
        # Allows typing "rebase" to surface "git rebase -i HEAD~3"
        for cmd_list in _LOCAL_DICT.values():
            for cmd, desc in cmd_list:
                if partial.lower() in cmd.lower() and {"cmd": cmd, "desc": desc} not in results:
                    results.append({"cmd": cmd, "desc": desc})
        return results[:4]


    async def _ollama_complete(self, partial: str, cwd: str) -> list[dict]:
        """
        Call Ollama's /api/generate with streaming — first token arrives in ~80ms.

        Strategy: stream tokens and stop as soon as we have a valid JSON object.
        This avoids waiting for the full completion (~400ms → ~80ms for first result).
        """
        prompt = (
            f"Complete this partial shell command: \"{partial}\"\n"
            f"Context: cwd={cwd or '~'}\n"
            "Respond ONLY with valid JSON. No markdown. No explanation.\n"
            'Schema: {"completions":[{"cmd":"<complete command>","desc":"<max 6 words>"}]}\n'
            "Return exactly 3 completions, most likely first."
        )

        collected = ""
        async with httpx.AsyncClient(timeout=_AUTOCOMPLETE_TIMEOUT_S) as client:
            async with client.stream(
                "POST",
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": True,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,   # low temp = more predictable completions
                        "num_predict": 200,   # cap tokens — completions are short
                    },
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    collected += chunk.get("response", "")
                    # Early exit: try to parse as soon as we have a closing }
                    if "}" in collected:
                        try:
                            parsed = json.loads(collected)
                            raw = parsed.get("completions", [])
                            if raw:
                                return [
                                    {"cmd": str(item.get("cmd", "")), "desc": str(item.get("desc", ""))}
                                    for item in raw
                                    if item.get("cmd")
                                ][:4]
                        except json.JSONDecodeError:
                            pass  # keep collecting
                    if chunk.get("done"):
                        break

        # Final attempt on complete buffer
        try:
            parsed = json.loads(collected)
            raw = parsed.get("completions", [])
            return [
                {"cmd": str(item.get("cmd", "")), "desc": str(item.get("desc", ""))}
                for item in raw
                if item.get("cmd")
            ][:4]
        except (json.JSONDecodeError, KeyError):
            return []


    async def _cache_set(self, key: str, value: list[dict]) -> None:
        async with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                self._cache[key] = value
                if len(self._cache) > _CACHE_MAX_SIZE:
                    self._cache.popitem(last=False)  # Evict LRU entry

    @staticmethod
    def _cache_key(partial: str) -> str:
        return partial.strip().lower()
