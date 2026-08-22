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
_AUTOCOMPLETE_TIMEOUT_S = 2.0    # 2s cap — enough for warm LLM on CPU
_MIN_PREFIX_LEN = 3              # Don't fire LLM for 1-2 char prefixes
_CACHE_MAX_SIZE = 64             # LRU eviction after 64 unique prefixes

# ─── Tier A: Local Command Dictionary ─────────────────────────────────────────
# Covers the 20 most common command families. Shown instantly with 0ms latency.
# Key = first word of the partial command.
_LOCAL_DICT: dict[str, list[tuple[str, str]]] = {
    # ── File Operations ───────────────────────────────────────────────────────
    "ls": [
        ("ls -la",                          "List all files with details"),
        ("ls -lh",                          "List files with human sizes"),
        ("ls -lt",                          "List files sorted by time"),
        ("ls -R",                           "List files recursively"),
    ],
    "cat": [
        ("cat ",                            "Display file contents"),
        ("cat -n ",                         "Display with line numbers"),
    ],
    "cp": [
        ("cp -r ",                          "Copy directory recursively"),
        ("cp -i ",                          "Copy with overwrite prompt"),
        ("cp -a ",                          "Copy preserving attributes"),
    ],
    "mv": [
        ("mv -i ",                          "Move with overwrite prompt"),
        ("mv ",                             "Move or rename files"),
    ],
    "rm": [
        ("rm -rf ",                         "Remove directory recursively"),
        ("rm -i ",                          "Remove with confirmation"),
    ],
    "mkdir": [
        ("mkdir -p ",                       "Create nested directories"),
    ],
    "touch": [
        ("touch ",                          "Create empty file"),
    ],
    "ln": [
        ("ln -s ",                          "Create symbolic link"),
    ],
    "head": [
        ("head -n 20 ",                     "Show first 20 lines"),
    ],
    "tail": [
        ("tail -f ",                        "Follow file in real time"),
        ("tail -n 50 ",                     "Show last 50 lines"),
    ],
    "less": [
        ("less ",                           "View file with scrolling"),
    ],
    "wc": [
        ("wc -l ",                          "Count lines in file"),
    ],
    "sort": [
        ("sort -u ",                        "Sort and remove duplicates"),
        ("sort -n ",                        "Sort numerically"),
    ],
    "uniq": [
        ("uniq -c ",                        "Count unique occurrences"),
    ],
    "diff": [
        ("diff -u ",                        "Unified diff format"),
    ],
    # ── Text Processing ───────────────────────────────────────────────────────
    "grep": [
        ("grep -rn ",                       "Recursive search with lines"),
        ("grep -rn --include='*.py' ",      "Search Python files only"),
        ("grep -i ",                        "Case-insensitive search"),
        ("grep -c ",                        "Count matches"),
    ],
    "sed": [
        ("sed -i 's///g' ",                 "Find and replace in file"),
        ("sed -n '1,10p' ",                 "Print lines 1-10"),
    ],
    "awk": [
        ("awk '{print $1}' ",              "Print first column"),
        ("awk -F: '{print $1}' ",          "Split by colon print first"),
    ],
    "xargs": [
        ("xargs -I {} ",                    "Execute per input line"),
    ],
    "tee": [
        ("tee ",                            "Write to stdout and file"),
    ],
    # ── Search & Find ─────────────────────────────────────────────────────────
    "find": [
        ("find . -name '*.py' -type f",     "Find Python files"),
        ("find . -mtime -1 -type f",        "Files modified last 24h"),
        ("find . -size +100M",              "Files larger than 100MB"),
    ],
    "which": [
        ("which ",                          "Find command location"),
    ],
    "locate": [
        ("locate ",                         "Fast file search"),
    ],
    # ── Package Managers ──────────────────────────────────────────────────────
    "pip": [
        ("pip install ",                    "Install Python package"),
        ("pip install -r requirements.txt", "Install from requirements"),
        ("pip list",                        "List installed packages"),
        ("pip freeze > requirements.txt",   "Export requirements"),
        ("pip uninstall ",                  "Uninstall package"),
        ("pip show ",                       "Show package info"),
    ],
    "pip3": [
        ("pip3 install ",                   "Install Python3 package"),
        ("pip3 list",                       "List installed packages"),
    ],
    "apt": [
        ("apt update && apt upgrade -y",    "Update all packages"),
        ("apt install ",                    "Install package"),
        ("apt search ",                     "Search for package"),
        ("apt remove ",                     "Remove package"),
        ("apt autoremove",                  "Remove unused packages"),
    ],
    "brew": [
        ("brew install ",                   "Install Homebrew package"),
        ("brew update && brew upgrade",     "Update all packages"),
        ("brew search ",                    "Search packages"),
        ("brew list",                       "List installed packages"),
    ],
    "snap": [
        ("snap install ",                   "Install snap package"),
        ("snap list",                       "List snaps"),
    ],
    # ── System Monitoring ─────────────────────────────────────────────────────
    "ps": [
        ("ps aux",                          "List all processes"),
        ("ps aux | grep ",                  "Find specific process"),
    ],
    "top": [
        ("top",                             "Interactive process monitor"),
        ("top -b -n 1",                     "Batch mode single snapshot"),
    ],
    "htop": [
        ("htop",                            "Interactive process viewer"),
    ],
    "df": [
        ("df -h",                           "Disk usage human readable"),
        ("df -hT",                          "Disk usage with filesystem"),
    ],
    "du": [
        ("du -sh ",                         "Directory size summary"),
        ("du -sh * | sort -rh | head",      "Top 10 largest items"),
    ],
    "free": [
        ("free -h",                         "Memory usage human readable"),
    ],
    "uptime": [
        ("uptime",                          "System uptime and load"),
    ],
    "lsof": [
        ("lsof -i :",                       "Find process on port"),
    ],
    # ── Networking ────────────────────────────────────────────────────────────
    "ping": [
        ("ping -c 4 ",                      "Ping host 4 times"),
    ],
    "curl": [
        ("curl -s  | jq .",                 "Fetch JSON pretty-print"),
        ("curl -X POST -H 'Content-Type: application/json' -d '{}'", "POST JSON"),
        ("curl -o  ",                       "Download file"),
        ("curl -I ",                        "Fetch headers only"),
    ],
    "wget": [
        ("wget ",                           "Download file"),
        ("wget -c ",                        "Resume download"),
    ],
    "ssh": [
        ("ssh -i ~/.ssh/id_ed25519 ",       "Connect with key"),
        ("ssh -L 8080:localhost:8080 ",     "Local port forward"),
    ],
    "scp": [
        ("scp -r  user@host:",             "Copy dir to remote"),
    ],
    "rsync": [
        ("rsync -avzP  user@host:",         "Sync with progress"),
        ("rsync -avz --delete  ",           "Sync delete removed"),
    ],
    "netstat": [
        ("netstat -tlnp",                   "Show listening ports"),
    ],
    "ss": [
        ("ss -tlnp",                        "Show listening ports"),
    ],
    "ip": [
        ("ip addr show",                    "Show IP addresses"),
        ("ip route show",                   "Show routing table"),
    ],
    "nslookup": [
        ("nslookup ",                       "DNS lookup"),
    ],
    "dig": [
        ("dig ",                            "Detailed DNS lookup"),
    ],
    # ── Permissions ───────────────────────────────────────────────────────────
    "chmod": [
        ("chmod +x ",                       "Make file executable"),
        ("chmod 755 ",                      "Owner rwx group/other rx"),
        ("chmod -R 644 ",                   "Recursive file permissions"),
    ],
    "chown": [
        ("chown -R  ",                      "Change owner recursively"),
    ],
    # ── Compression ───────────────────────────────────────────────────────────
    "tar": [
        ("tar -czf archive.tar.gz ",        "Create tar.gz archive"),
        ("tar -xzf ",                       "Extract tar.gz"),
        ("tar -xvf ",                       "Extract with verbose"),
    ],
    "zip": [
        ("zip -r archive.zip ",             "Create zip archive"),
    ],
    "unzip": [
        ("unzip ",                          "Extract zip archive"),
    ],
    "gzip": [
        ("gzip ",                           "Compress file"),
        ("gunzip ",                         "Decompress file"),
    ],
    # ── Git ───────────────────────────────────────────────────────────────────
    "git": [
        ("git commit -m \"\"",              "Commit with message"),
        ("git push origin",                 "Push to remote"),
        ("git pull --rebase",               "Fetch + rebase"),
        ("git status",                      "Working tree status"),
        ("git log --oneline --graph",       "Visual commit history"),
        ("git checkout -b ",                "Create new branch"),
        ("git diff --staged",               "Show staged changes"),
        ("git stash push -m \"\"",          "Stash with label"),
        ("git branch -d ",                  "Delete local branch"),
        ("git fetch --all",                 "Fetch all remotes"),
        ("git rebase -i HEAD~3",            "Interactive rebase"),
        ("git reset --hard HEAD",           "Discard all changes"),
        ("git cherry-pick ",                "Apply specific commit"),
        ("git clone ",                      "Clone repository"),
        ("git add .",                       "Stage all changes"),
    ],
    # ── Docker ────────────────────────────────────────────────────────────────
    "docker": [
        ("docker ps -a",                    "List all containers"),
        ("docker build -t  .",              "Build image"),
        ("docker run -it --rm ",            "Run interactively"),
        ("docker-compose up -d",            "Start services detached"),
        ("docker exec -it  bash",           "Shell into container"),
        ("docker logs -f ",                 "Follow container logs"),
        ("docker system prune -af",         "Remove unused resources"),
        ("docker images",                   "List images"),
        ("docker stop ",                    "Stop container"),
    ],
    # ── Services ──────────────────────────────────────────────────────────────
    "systemctl": [
        ("systemctl status ",               "Show service status"),
        ("systemctl restart ",              "Restart service"),
        ("systemctl enable --now ",         "Enable and start service"),
        ("systemctl list-units --failed",   "List failed units"),
    ],
    "journalctl": [
        ("journalctl -u  -f",              "Follow service logs"),
        ("journalctl --since '1 hour ago'", "Logs last hour"),
        ("journalctl -p err -b",            "Errors since boot"),
    ],
    "service": [
        ("service  status",                 "Check service status"),
    ],
    # ── Kubernetes ────────────────────────────────────────────────────────────
    "kubectl": [
        ("kubectl get pods -n ",            "List pods"),
        ("kubectl logs -f ",                "Follow pod logs"),
        ("kubectl apply -f ",               "Apply manifest"),
        ("kubectl exec -it  -- bash",       "Shell into pod"),
        ("kubectl describe pod ",           "Pod details"),
    ],
    # ── Dev Tools ─────────────────────────────────────────────────────────────
    "npm": [
        ("npm run dev",                     "Start dev server"),
        ("npm install ",                    "Install package"),
        ("npm run build",                   "Build production"),
        ("npm test",                        "Run tests"),
        ("npm init -y",                     "Initialize package"),
    ],
    "npx": [
        ("npx ",                            "Run npm package"),
    ],
    "yarn": [
        ("yarn add ",                       "Add package"),
        ("yarn dev",                        "Start dev server"),
    ],
    "cargo": [
        ("cargo build --release",           "Build optimized binary"),
        ("cargo test",                      "Run tests"),
        ("cargo clippy",                    "Lint code"),
        ("cargo add ",                      "Add dependency"),
    ],
    "python3": [
        ("python3 -m venv .venv",           "Create virtual env"),
        ("python3 -m pytest",               "Run pytest"),
        ("python3 -m pip install ",         "Install package"),
        ("python3 -m http.server 8080",     "Local HTTP server"),
        ("python3 ",                        "Run Python script"),
    ],
    "python": [
        ("python -m venv .venv",            "Create virtual env"),
        ("python -m pytest",                "Run pytest"),
    ],
    "pytest": [
        ("pytest -v --tb=short",            "Run tests verbose"),
        ("pytest --cov= ",                  "Run with coverage"),
        ("pytest -k ",                      "Run matching tests"),
    ],
    "make": [
        ("make",                            "Run default target"),
        ("make clean",                      "Clean build files"),
        ("make install",                    "Install built project"),
    ],
    "cmake": [
        ("cmake -B build",                  "Configure build"),
        ("cmake --build build",             "Build project"),
    ],
    "go": [
        ("go build ./...",                  "Build Go project"),
        ("go test ./...",                   "Run Go tests"),
        ("go mod tidy",                     "Clean dependencies"),
        ("go run ",                         "Run Go file"),
    ],
    "node": [
        ("node ",                           "Run JavaScript file"),
    ],
    # ── Editors ───────────────────────────────────────────────────────────────
    "nano": [
        ("nano ",                           "Edit file with nano"),
    ],
    "vim": [
        ("vim ",                            "Edit file with vim"),
    ],
    "code": [
        ("code .",                          "Open VS Code here"),
        ("code ",                           "Open file in VS Code"),
    ],
    # ── Misc ──────────────────────────────────────────────────────────────────
    "echo": [
        ("echo ",                           "Print text to stdout"),
        ("echo $PATH",                      "Show PATH variable"),
    ],
    "export": [
        ("export PATH=$PATH:",              "Add to PATH"),
    ],
    "alias": [
        ("alias",                           "List all aliases"),
    ],
    "history": [
        ("history | grep ",                 "Search command history"),
    ],
    "man": [
        ("man ",                            "Show manual page"),
    ],
    "date": [
        ("date",                            "Show current date/time"),
        ("date +%Y-%m-%d",                  "Date in ISO format"),
    ],
    "whoami": [
        ("whoami",                          "Show current user"),
    ],
    "hostname": [
        ("hostname",                        "Show system hostname"),
    ],
    "env": [
        ("env",                             "Show environment vars"),
    ],
    "xdg-open": [
        ("xdg-open ",                       "Open file with default app"),
    ],
    "kill": [
        ("kill -9 ",                        "Force kill process"),
        ("kill ",                           "Terminate process"),
    ],
    "killall": [
        ("killall ",                        "Kill processes by name"),
    ],
    "screen": [
        ("screen -S ",                      "Create named session"),
        ("screen -r ",                      "Reattach session"),
    ],
    "tmux": [
        ("tmux new -s ",                    "Create named session"),
        ("tmux attach -t ",                 "Attach to session"),
        ("tmux ls",                         "List sessions"),
    ],
    "crontab": [
        ("crontab -l",                      "List cron jobs"),
        ("crontab -e",                      "Edit cron jobs"),
    ],
    "watch": [
        ("watch -n 1 ",                     "Run command every second"),
    ],
    "sudo": [
        ("sudo ",                           "Run as superuser"),
        ("sudo su",                         "Switch to root"),
        ("sudo apt update",                 "Update package list"),
    ],
    "su": [
        ("su -",                            "Switch to root"),
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
