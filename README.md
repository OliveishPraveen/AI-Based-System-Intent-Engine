# AI-Based System Intent Engine
### Safe Linux Command Execution — CDAC Hackathon Project

> **Your command, understood before it runs.**

A transparent AI safety layer that sits between the moment you type a Linux command and the moment your shell executes it. It reasons about *intent and impact* — explains what a dangerous command will do in plain English, suggests a safer alternative, and waits for your confirmation before anything runs.

---

## How It Works

```
$ rm -rf /var/log/*              ← you type this
        │
        ▼  (zsh preexec / bash DEBUG trap intercepts)
        │
  ┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
  │ Rule Engine │ OR │  LLM Reasoning   │ →  │ Confirmation UI  │
  │  (< 50ms)   │    │  (< 3.5s, local) │    │ [y/n/e/safer]    │
  └─────────────┘    └──────────────────┘    └──────────────────┘
        │
        ▼
  ⚠ HIGH RISK: Permanently deletes all system logs.
  Safer: sudo journalctl --vacuum-size=500M
  [y] Execute  [n] Abort  [e] Edit  [s] Use safer
```

The user **always stays in control** — nothing is ever silently blocked or auto-corrected.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Shell integration | Zsh `preexec` + Bash `DEBUG` trap |
| Daemon | Python + FastAPI + Uvicorn (Unix domain socket) |
| Command parsing | Python `shlex` + custom AST |
| Rule engine | Pattern library (TOML) + confidence scoring |
| LLM reasoning | Ollama (local) + Gemini/OpenAI (API fallback) |
| UI | ANSI terminal prompt (zero dependencies) |

---

## Quick Start

```bash
# 1. Clone
git clone git@github.com:Harshit7623/AI-Based-System-Intent-Engine.git
cd AI-Based-System-Intent-Engine

# 2. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Run installer (copies hooks, starts daemon)
bash scripts/install.sh

# 4. Restart terminal or:
source ~/.zshrc   # or ~/.bashrc
```

---

## Documentation

| Document | What It Covers |
|---|---|
| [`docs/WORK_DIVISION.md`](docs/WORK_DIVISION.md) | Team ownership, 13-day phases, per-member tasks |
| [`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md) | Every directory explained, where to add files, dev workflow |
| [`rules/dangerous_patterns.toml`](rules/dangerous_patterns.toml) | The curated dangerous pattern library |
| [`config/default_config.toml`](config/default_config.toml) | All configuration options |

---

## Team

| Member | Domain |
|---|---|
| Harshit | Shell hooks, daemon, parser, system architecture |
| Praveen | Rule engine (Tier 0/1), pattern library |
| Vansh | LLM reasoning (Tier 2), safer alternatives |

---

## Running Tests

```bash
pytest tests/unit/ -v --cov=engine --cov-report=term-missing
```