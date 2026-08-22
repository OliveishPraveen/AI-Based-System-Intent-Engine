#!/usr/bin/env python3
"""
Intent Engine — Interactive Setup Wizard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

First-run configuration for LLM provider, model, and shell integration.

Usage:
    python3 -m engine.setup          # interactive
    python3 -m engine.setup --auto   # auto-detect everything
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ─── ANSI styling ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[38;5;82m"
YELLOW = "\033[38;5;220m"
RED    = "\033[38;5;196m"
CYAN   = "\033[38;5;81m"
GREY   = "\033[38;5;240m"
WHITE  = "\033[38;5;255m"
BAR    = f"{GREY}{'─' * 60}{RESET}"

CONFIG_DIR  = Path.home() / ".intent_engine"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DEFAULT_CFG = Path(__file__).resolve().parent.parent / "config" / "default_config.toml"

# ─── LLM provider profiles ───────────────────────────────────────────────────
PROVIDERS = {
    "ollama": {
        "name": "Ollama (Local, Free, Private)",
        "needs_key": False,
        "models": ["qwen2.5:7b", "llama3.1:8b", "llama3.2:3b", "deepseek-r1:7b"],
        "recommended": "qwen2.5:7b",
        "check_cmd": ["ollama", "list"],
    },
    "gemini": {
        "name": "Google Gemini (API Key)",
        "needs_key": True,
        "env_var": "INTENT_GEMINI_API_KEY",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro"],
        "recommended": "gemini-2.0-flash",
    },
    "openai": {
        "name": "OpenAI (API Key)",
        "needs_key": True,
        "env_var": "INTENT_OPENAI_API_KEY",
        "models": ["gpt-4o-mini", "gpt-4o"],
        "recommended": "gpt-4o-mini",
    },
}


def _print_header():
    print(f"""
{BOLD}{CYAN}┌──────────────────────────────────────────────────────────┐
│         Intent Engine — Setup Wizard                     │
│         AI-Based System Intent Engine                    │
└──────────────────────────────────────────────────────────┘{RESET}
""")


def _ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str):
    print(f"  {YELLOW}⚠{RESET} {msg}")


def _err(msg: str):
    print(f"  {RED}✗{RESET} {msg}")


def _info(msg: str):
    print(f"  {DIM}→{RESET} {msg}")


# ─── Detection helpers ────────────────────────────────────────────────────────

def _check_python() -> bool:
    v = sys.version_info
    ok = v >= (3, 10)
    if ok:
        _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _err(f"Python {v.major}.{v.minor} — requires 3.10+")
    return ok


def _check_zsh() -> tuple[bool, str]:
    zsh = shutil.which("zsh")
    if zsh:
        _ok(f"Zsh found: {zsh}")
        # Check if it's the default shell
        current_shell = os.environ.get("SHELL", "")
        if "zsh" in current_shell:
            _ok("Zsh is your default shell")
        else:
            _warn(f"Default shell is {current_shell} — run: chsh -s {zsh}")
        return True, zsh
    else:
        _warn("Zsh not found — Bash hook only, no CLI Copilot")
        return False, ""


def _check_ollama() -> tuple[bool, list[str]]:
    """Check if Ollama is installed and return list of available models."""
    ollama = shutil.which("ollama")
    if not ollama:
        return False, []
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return False, []
        models = []
        for line in result.stdout.strip().split("\n")[1:]:  # skip header
            if line.strip():
                name = line.split()[0]
                models.append(name)
        return True, models
    except Exception:
        return False, []


def _ollama_pull(model: str) -> bool:
    """Pull an Ollama model with progress."""
    print(f"\n  {CYAN}↓{RESET} Pulling {BOLD}{model}{RESET} ...")
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            timeout=600,  # 10 minute max
        )
        return result.returncode == 0
    except Exception as e:
        _err(f"Pull failed: {e}")
        return False


def _smoke_test_ollama(model: str) -> tuple[bool, float]:
    """Quick test: ask Ollama to classify 'ls /tmp'."""
    import httpx
    try:
        t0 = time.perf_counter()
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Reply only with: SAFE"},
                        {"role": "user", "content": "Classify: ls /tmp"},
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            elapsed = (time.perf_counter() - t0) * 1000
            content = resp.json()["message"]["content"]
            ok = "SAFE" in content.upper()
            return ok, elapsed
    except Exception as e:
        return False, 0.0


def _smoke_test_daemon() -> tuple[bool, dict]:
    """Check if the daemon is running and responds to /health."""
    import httpx
    try:
        transport = httpx.HTTPTransport(uds="/tmp/intent_engine.sock")
        with httpx.Client(transport=transport, timeout=3.0) as client:
            resp = client.get("http://localhost/health")
            return resp.status_code == 200, resp.json()
    except Exception:
        return False, {}


def _write_config(provider: str, model: str, api_key_var: Optional[str] = None):
    """Copy default config and patch the LLM provider/model."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if DEFAULT_CFG.exists():
        content = DEFAULT_CFG.read_text()
    else:
        content = f"""[daemon]
socket_path = "/tmp/intent_engine.sock"
pid_file = "/tmp/intent_engine.pid"
log_dir = "~/.intent_engine/logs"
log_level = "INFO"

[safety]
block_threshold = "HIGH"

[llm]
provider = "{provider}"
model = "{model}"
timeout_s = 3.0
ollama_url = "http://localhost:11434"

[ui]
theme = "dark"

[audit]
log_flagged = true
log_format = "json"
"""
    # Patch provider and model
    import re
    content = re.sub(r'^provider\s*=\s*".*"', f'provider = "{provider}"', content, flags=re.MULTILINE)
    content = re.sub(r'^model\s*=\s*".*"', f'model    = "{model}"', content, flags=re.MULTILINE)
    CONFIG_FILE.write_text(content)
    _ok(f"Config written to {CONFIG_FILE}")

    if api_key_var:
        key = os.environ.get(api_key_var, "")
        if key:
            _ok(f"API key found in ${api_key_var}")
        else:
            _warn(f"Set your API key: export {api_key_var}=<your-key>")


# ─── Interactive setup flow ───────────────────────────────────────────────────

def setup_interactive():
    _print_header()

    # ── Step 1: Environment check ─────────────────────────────────────────────
    print(f"{BAR}")
    print(f"  {BOLD}[1/5] Environment Check{RESET}")
    print(f"{BAR}")

    if not _check_python():
        _err("Python 3.10+ required. Aborting.")
        sys.exit(1)

    has_zsh, zsh_path = _check_zsh()

    # ── Step 2: LLM Provider ─────────────────────────────────────────────────
    print(f"\n{BAR}")
    print(f"  {BOLD}[2/5] LLM Provider Selection{RESET}")
    print(f"{BAR}\n")

    ollama_ok, ollama_models = _check_ollama()

    if ollama_ok:
        _ok(f"Ollama installed ({len(ollama_models)} models available)")
        for m in ollama_models[:8]:
            _info(f"  {m}")
    else:
        _warn("Ollama not found")

    print(f"\n  Choose your LLM provider:\n")
    print(f"    {BOLD}[1]{RESET} Ollama (local, free, private)    {GREEN}← RECOMMENDED{RESET}")
    print(f"    {BOLD}[2]{RESET} Google Gemini (API key required)")
    print(f"    {BOLD}[3]{RESET} OpenAI (API key required)")
    print(f"    {BOLD}[4]{RESET} Rules-only mode (no LLM tier)\n")

    choice = input(f"  {CYAN}▶{RESET} Choice [1]: ").strip() or "1"

    provider = "ollama"
    model = "qwen2.5:7b"
    api_var = None

    if choice == "1":
        provider = "ollama"
        profile = PROVIDERS["ollama"]
        if not ollama_ok:
            _err("Ollama not installed. Install from: https://ollama.ai/download")
            _info("After installing, run: ollama serve")
            sys.exit(1)
        # Model selection
        print(f"\n  Available models:")
        for i, m in enumerate(profile["models"], 1):
            rec = f" {GREEN}← recommended{RESET}" if m == profile["recommended"] else ""
            installed = f" {DIM}(installed){RESET}" if m in ollama_models else ""
            print(f"    {BOLD}[{i}]{RESET} {m}{rec}{installed}")
        mchoice = input(f"\n  {CYAN}▶{RESET} Model [{profile['recommended']}]: ").strip()
        if mchoice.isdigit() and 1 <= int(mchoice) <= len(profile["models"]):
            model = profile["models"][int(mchoice) - 1]
        elif mchoice:
            model = mchoice
        else:
            model = profile["recommended"]
        # Pull if needed
        if model not in ollama_models:
            if not _ollama_pull(model):
                _err(f"Failed to pull {model}")
                sys.exit(1)

    elif choice == "2":
        provider = "gemini"
        model = "gemini-2.0-flash"
        api_var = "INTENT_GEMINI_API_KEY"
        key = input(f"\n  {CYAN}▶{RESET} Gemini API key (or press Enter to set later): ").strip()
        if key:
            os.environ[api_var] = key
            _info(f"Add to your shell profile: export {api_var}={key}")

    elif choice == "3":
        provider = "openai"
        model = "gpt-4o-mini"
        api_var = "INTENT_OPENAI_API_KEY"
        key = input(f"\n  {CYAN}▶{RESET} OpenAI API key (or press Enter to set later): ").strip()
        if key:
            os.environ[api_var] = key
            _info(f"Add to your shell profile: export {api_var}={key}")

    elif choice == "4":
        provider = "none"
        model = "none"
        _info("Rules-only mode: Tier 2 LLM reasoning disabled.")
        _info("Only Tier 0/1 pattern matching will be active.")

    # ── Step 3: Write config ──────────────────────────────────────────────────
    print(f"\n{BAR}")
    print(f"  {BOLD}[3/5] Configuration{RESET}")
    print(f"{BAR}")
    _write_config(provider, model, api_var)

    # ── Step 4: Smoke test ────────────────────────────────────────────────────
    print(f"\n{BAR}")
    print(f"  {BOLD}[4/5] Smoke Test{RESET}")
    print(f"{BAR}")

    if provider == "ollama":
        print(f"\n  Testing {model} ...")
        ok, latency = _smoke_test_ollama(model)
        if ok:
            _ok(f"LLM responded correctly ({latency:.0f}ms)")
            if latency > 3000:
                _warn(f"Response time is {latency:.0f}ms — consider a smaller model")
            elif latency > 1500:
                _info(f"Response time: {latency:.0f}ms — acceptable for safety tier")
            else:
                _ok(f"Excellent latency: {latency:.0f}ms")
        else:
            _warn("LLM smoke test failed — is Ollama running? (ollama serve)")
    elif provider == "none":
        _info("No LLM — skipping smoke test")
    else:
        _info(f"Cloud provider ({provider}) — set the API key and restart daemon to verify")

    # Daemon check
    daemon_ok, health = _smoke_test_daemon()
    if daemon_ok:
        _ok(f"Daemon running (PID {health.get('pid', '?')})")
    else:
        _warn("Daemon not running. Start with: python3 -m engine.daemon.server &")

    # ── Step 5: Summary ───────────────────────────────────────────────────────
    print(f"\n{BAR}")
    print(f"  {BOLD}[5/5] Setup Complete{RESET}")
    print(f"{BAR}\n")

    print(f"  {BOLD}Provider:{RESET}  {provider}")
    print(f"  {BOLD}Model:{RESET}     {model}")
    print(f"  {BOLD}Config:{RESET}    {CONFIG_FILE}")
    print(f"  {BOLD}Shell:{RESET}     {'Zsh (full features)' if has_zsh else 'Bash (safety only)'}")

    print(f"\n  {BOLD}Next steps:{RESET}")
    print(f"    1. Start daemon:  {CYAN}python3 -m engine.daemon.server &{RESET}")
    if has_zsh and "zsh" not in os.environ.get("SHELL", ""):
        print(f"    2. Switch shell:  {CYAN}chsh -s {zsh_path}{RESET}")
    print(f"    3. Test it:       {CYAN}rm -rf /tmp/test{RESET}  ← should be intercepted")
    print()


# ─── Auto mode ────────────────────────────────────────────────────────────────

def setup_auto():
    """Non-interactive: detect everything, write config, print summary."""
    _print_header()
    _check_python()
    has_zsh, _ = _check_zsh()
    ollama_ok, models = _check_ollama()

    if ollama_ok:
        _ok("Ollama detected — using as provider")
        model = "qwen2.5:7b"
        if model not in models:
            _ollama_pull(model)
        _write_config("ollama", model)
    else:
        _warn("No Ollama — configuring rules-only mode")
        _write_config("none", "none")

    daemon_ok, _ = _smoke_test_daemon()
    if daemon_ok:
        _ok("Daemon is running")
    else:
        _warn("Start daemon: python3 -m engine.daemon.server &")

    print()
    _ok("Setup complete")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    if "--auto" in sys.argv:
        setup_auto()
    else:
        setup_interactive()


if __name__ == "__main__":
    main()
