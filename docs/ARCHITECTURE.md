# System Architecture
## AI-Based System Intent Engine for Safe Linux Command Execution

---

## 1. High-Level Overview

The Intent Engine is a **transparent, always-on safety layer** between a user's keypress and shell execution. It intercepts commands, classifies their risk in milliseconds, and presents a human-readable verdict before anything runs.

```
┌─────────────────────────────────────────────────────────┐
│                    USER'S TERMINAL                       │
│   $ rm -rf /var/log/*     ← user presses Enter          │
└──────────────────────┬──────────────────────────────────┘
                       │
          zsh preexec / bash DEBUG trap
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  SHELL HOOK (thin client)                │
│  - Builds JSON payload from command + context            │
│  - Sends to daemon via Unix socket (< 5ms overhead)      │
│  - On BLOCK response: shows UI, waits for user choice    │
│  - On SAFE response:  does nothing, command runs         │
└──────────────────────┬──────────────────────────────────┘
                       │ Unix domain socket
                       │ POST /analyze
┌──────────────────────▼──────────────────────────────────┐
│            INTENT ENGINE DAEMON (FastAPI)                │
│                                                          │
│  1. Parser  →  ParsedCommand                             │
│  2. Router  →  picks Tier                               │
│                                                          │
│  ┌─────────────────┐        ┌──────────────────────┐    │
│  │  TIER 0 / 1     │        │  TIER 2 (only if     │    │
│  │  Rule Engine    │─AMBIG─►│  AMBIGUOUS)          │    │
│  │  (Praveen)      │        │  LLM Reasoner        │    │
│  │  < 50ms         │        │  (Vansh) < 3.5s      │    │
│  └────────┬────────┘        └──────────┬───────────┘    │
│           └──────────┬─────────────────┘                │
│                      │ Verdict                           │
│  3. Build AnalyzeResponse                               │
│  4. Write audit log                                      │
└──────────────────────┬──────────────────────────────────┘
                       │ should_block: true/false
┌──────────────────────▼──────────────────────────────────┐
│              CONFIRMATION UI (if blocked)                │
│                                                          │
│  ⚠ HIGH: rm -rf /var/log/*                              │
│  Impact: Permanently deletes all system logs.            │
│  Safer:  sudo journalctl --vacuum-size=500M              │
│                                                          │
│  [y] Execute  [n] Abort  [e] Edit  [s] Use safer         │
└──────────────────────┬──────────────────────────────────┘
                       │ user choice
                  Shell executes
                  (or doesn't)
```

---

## 2. Component Architecture

### 2.1 Shell Hook

**Files:** `hooks/intent_hook.zsh`, `hooks/intent_hook.bash`
**Owner:** Harshit

The hook is intentionally **thin** — it contains zero business logic.

```
Shell fires event (preexec / DEBUG trap)
    │
    ├─ Is engine enabled?           → NO  → pass through
    ├─ Is INTENT_ENGINE_SKIP set?   → YES → pass through (one command)
    ├─ Is it an engine command?     → YES → pass through
    │
    ▼
Build JSON:  {command, cwd, user, is_sudo, shell, session_id}
    │
    ▼
POST /analyze via Unix socket (curl, max 4s timeout)
    │
    ├─ Daemon unreachable? → warn once, deactivate for session
    │
    ▼
Read AnalyzeResponse
    │
    ├─ should_block = false → do nothing, command runs
    │
    └─ should_block = true  → pipe response to terminal_ui.py
                                │
                                ├─ EXECUTE     → let command run
                                ├─ ABORT       → suppress command
                                ├─ EDIT        → return to shell prompt
                                └─ USE_SAFER   → eval safer alternative
```

**Integration methods:**

| Shell | Mechanism | How block works |
|---|---|---|
| Zsh | `preexec()` function | `zle send-break` cancels the command |
| Bash | `trap '...' DEBUG` + `shopt -s extdebug` | Return 1 from trap prevents execution |

---

### 2.2 Daemon

**Files:** `engine/daemon/server.py`, `engine/daemon/router.py`, `engine/daemon/session.py`
**Owner:** Harshit

The daemon is a **warm Python process** started at shell login. It stays resident so there is no interpreter startup cost per command (~100-300ms saved per invocation).

```
Startup sequence:
  1. Bind Unix socket at /tmp/intent_engine.sock
  2. Write PID to /tmp/intent_engine.pid
  3. Load config from ~/.intent_engine/config/config.toml
  4. Initialize IntentRouter
     ├─ Load RuleEngineClassifier (Praveen) → compile regex patterns
     └─ Initialize LLMReasoner (Vansh)      → warm up LLM client
  5. Ready — serve requests

Per-request sequence (router.py):
  AnalyzeRequest
      │
      ▼
  Parser.parse()  →  ParsedCommand
      │
      ├─ Check session allowlist (ALWAYS_ALLOW) → return SAFE instantly
      ├─ Check ALWAYS_DENY list                 → return CRITICAL instantly
      │
      ▼
  RuleEngineClassifier.classify(parsed, ctx)
      │
      ├─ SAFE / LOW / MEDIUM / HIGH / CRITICAL  → build AnalyzeResponse
      │
      └─ AMBIGUOUS  ─────────────────────────►  LLMReasoner.reason()
                                                     │
                                                     ├─ Returns Verdict
                                                     └─ Timeout (3s) → fallback LOW

  Build AnalyzeResponse:
      verdict.risk_level >= block_threshold?
          YES → should_block = true
          NO  → should_block = false

  Write AuditLogEntry to ~/.intent_engine/logs/YYYY-MM-DD.jsonl

  Return AnalyzeResponse
```

**Daemon endpoints:**

| Endpoint | Method | Purpose |
|---|---|---|
| `/analyze` | POST | Primary — analyze a command |
| `/health` | GET | Liveness check (shell hook pings at startup) |
| `/reload-rules` | POST | Hot-reload pattern library without restart |
| `/stats` | GET | Session stats by risk level |

---

### 2.3 Command Parser

**Files:** `engine/parser/command_parser.py`
**Owner:** Harshit

Converts a raw shell string into a structured `ParsedCommand` that carries all structural information the rule engine and LLM need.

```
Input:  "sudo rm -rf /var/log/* | tee /tmp/deleted.txt"

Pipeline:
  1. _split_pipes()         → ["sudo rm -rf /var/log/*", "tee /tmp/deleted.txt"]
  2. _parse_single() each segment:
       tokens    = shlex.split(segment)
       is_sudo   = tokens[0] in {sudo, su, doas}
       base_cmd  = first non-sudo token
       flags     = tokens starting with "-"
       arguments = tokens not starting with "-"
       has_redirect = bool(redirect_regex.search(raw))
       has_subshell = bool(subshell_regex.search(raw))
       is_glob      = any("*?[" in arg)
  3. Attach pipe_segments to root ParsedCommand

Output: ParsedCommand(
    raw         = "sudo rm -rf /var/log/* | tee /tmp/deleted.txt",
    base_command = "rm",
    flags        = ["-r", "-f"],
    arguments    = ["/var/log/*"],
    is_sudo      = True,
    has_pipe     = True,
    is_glob      = True,
    glob_patterns = ["/var/log/*"],
    pipe_segments = [<rm segment>, <tee segment>]
)
```

**Edge cases handled:**

| Case | Handling |
|---|---|
| Unclosed quotes | `shlex` raises `ValueError` → fallback to whitespace split |
| `\|\|` (logical OR) | Detected and NOT split as pipe |
| `&&` chains | Split as separate segments, all analyzed |
| `;` chains | Split as separate segments, all analyzed |
| Fork bomb `:(){ :\|:&};:` | Survives tokenization without crash |
| Nested subshells `$(...)` | `has_subshell=True`, content noted |

---

### 2.4 Rule Engine (Tier 0/1)

**Files:** `engine/rule_engine/classifier.py`, `engine/rule_engine/pattern_matcher.py`
**Owner:** Praveen
**Data:** `rules/dangerous_patterns.toml`

Two-tier classification with deterministic, fast-path logic.

```
classify(ParsedCommand, CommandContext)
    │
    ▼
check_tier0(parsed)   ← Instant, 100% confidence, always CRITICAL
    │
    Checks (structural, not regex):
    ├─ Fork bomb syntax detected?          → CRITICAL (confidence 1.0)
    ├─ rm targeting / or /*?               → CRITICAL (confidence 1.0)
    ├─ dd writing to /dev/sd* /dev/nvme*?  → CRITICAL (confidence 1.0)
    ├─ mkfs.* targeting /dev/*?            → CRITICAL (confidence 1.0)
    └─ pipe_segments[-1] is sh/bash AND
       pipe_segments[0] is curl/wget?     → CRITICAL (confidence 1.0)

    None matched → proceed to Tier 1
    │
    ▼
match(parsed, ctx)   ← Pattern library scan
    │
    For each compiled pattern in dangerous_patterns.toml:
        regex matches raw command?
              │
              YES → compute confidence:
                     base_score = 0.70
                     + 0.15  if is_sudo
                     + 0.10  if target_path is /etc /boot /bin /sbin /dev
                     + 0.08  if is_glob
                     - 0.15  if target is /tmp
                     - 0.20  if --dry-run / -n flag present
                     - 0.05  if user is root

    Take highest-confidence match.
    confidence >= 0.55 → return Verdict(risk_level, confidence, ...)
    confidence <  0.55 → return Verdict(AMBIGUOUS)
```

**Pattern library structure (`dangerous_patterns.toml`):**

```
Tier 0 (instant CRITICAL):
  fork_bomb, rm_rf_root, dd_raw_device, mkfs_device, curl_pipe_shell

Tier 1 HIGH:
  rm_rf_var_log, chmod_777_system, shred_device, truncate_log,
  rm_boot, iptables_flush, ufw_disable, crontab_remove,
  reverse_shell_nc, history_erasure

Tier 1 MEDIUM:
  cat_shadow, expose_ssh_key, find_exec_delete, chmod_sudoers,
  passwd_file_edit, sysrq_trigger
```

---

### 2.5 LLM Reasoner (Tier 2)

**Files:** `engine/llm/reasoner.py`, `engine/llm/providers/`
**Owner:** Vansh

Only invoked when the rule engine returns `AMBIGUOUS`. Hard 3-second timeout.

```
reason(ParsedCommand, CommandContext, rule_hint_Verdict)
    │
    ▼
PromptBuilder.build_system_prompt()    ← strict JSON schema enforcement
PromptBuilder.build_analysis_prompt()  ← command + parsed details + context
    │
    ▼
asyncio.wait_for(
    LLMClient.complete(prompt, system),
    timeout = 3.0s
)
    │
    ├─ TimeoutError → router catches → fallback LOW verdict
    │
    ▼
ResponseParser.parse(raw_json)
    ├─ Validates JSON schema
    ├─ Validates risk_level in {SAFE,LOW,MEDIUM,HIGH,CRITICAL}
    ├─ Clamps confidence to [0.0, 1.0]
    └─ Raises ValueError on malformed → router catches → fallback

    │
    ▼
SaferAlternativeSuggester.suggest()
    ├─ Phase 1: table lookup (instant)
    └─ Phase 2: LLM-generated (if no table entry)

    │
    ▼
Return Verdict (never AMBIGUOUS)
```

**Provider chain:**

```
Config: provider = "ollama"

LLMClientFactory.create(config)
    │
    ├─ Create OllamaClient
    ├─ health_check() → True?  → use it
    └─ False → create fallback_provider (e.g. GeminiClient)

Providers:
  OllamaClient  → POST http://localhost:11434/api/chat  (local, private)
  GeminiClient  → google.generativeai SDK               (API, cloud)
  OpenAIClient  → openai SDK                            (API, cloud)
```

**LLM output schema (enforced in system prompt):**

```json
{
  "risk_level": "SAFE|LOW|MEDIUM|HIGH|CRITICAL",
  "confidence": 0.0-1.0,
  "reasoning": "detailed technical explanation",
  "impact_summary": "one sentence plain-English impact",
  "safer_alternative": "safer command or null"
}
```

---

### 2.6 Confirmation UI

**File:** `engine/ui/terminal_ui.py`
**Owner:** Harshit

Called by the shell hook via `echo "$response" | python3 -m engine.ui.terminal_ui`. Returns the user's choice on stdout.

```
╔══════════════════════════════════════════════════════════╗
║  ⚠  INTENT ENGINE — HIGH                               ║
╠══════════════════════════════════════════════════════════╣
║  Risk    : ████████░░ HIGH                              ║
║  Impact  : Permanently deletes all system logs.         ║
║  Detail  : Active logs in use by syslog and journald.   ║
╠══════════════════════════════════════════════════════════╣
║  Safer   : sudo journalctl --vacuum-size=500M           ║
╠══════════════════════════════════════════════════════════╣
║  [y] Execute original  [n] Abort  [e] Edit  [s] Safer  ║
╚══════════════════════════════════════════════════════════╝
Your choice: _

Outputs to stdout: EXECUTE | ABORT | EDIT | USE_SAFER
```

---

## 3. Data Flow

### 3.1 SAFE Command (Fast Path)

```
User types: ls -la /home
    │
    Hook → POST /analyze (< 5ms socket overhead)
    │
    Daemon → Parser → ParsedCommand(base="ls", flags=["-la"])
    │
    Router → check session allowlist → not found
    │
    Rule Engine Tier 0 → no match
    Rule Engine Tier 1 → no pattern matches → confidence 0.0 → AMBIGUOUS?
           wait — "ls" is not in any command list → SAFE returned directly
    │
    AnalyzeResponse(should_block=False)
    │
    Hook → does nothing
    │
    Shell executes: ls -la /home        ← total overhead < 20ms
```

### 3.2 CRITICAL Command (Rule Engine Fast Path)

```
User types: rm -rf /
    │
    Hook → POST /analyze
    │
    Daemon → Parser → ParsedCommand(
        base="rm", flags=["-r","-f"], arguments=["/"], is_sudo=False
    )
    │
    Router → Rule Engine Tier 0 → check_tier0()
        rm + recursive + force + target="/" → MATCH
        Returns Verdict(CRITICAL, confidence=1.0, tier="rule_engine")
    │
    AnalyzeResponse(should_block=True)        ← total: < 30ms
    │
    Hook → pipes response to terminal_ui.py
    │
    User sees prompt, types "n"
    │
    Hook suppresses the command — nothing is deleted
```

### 3.3 AMBIGUOUS Command (LLM Path)

```
User types: find /home -name ".env" -exec cat {} \;
    │
    Hook → POST /analyze
    │
    Parser → ParsedCommand(base="find", has_subshell=False, ...)
    │
    Rule Engine → no Tier 0 match
    Rule Engine Tier 1 → "find" patterns check:
        find_exec_delete? No (-exec cat, not rm)
        find_root_delete? No (/home not /)
        confidence = 0.40 → below threshold → AMBIGUOUS
    │
    Router → escalate to LLM (Tier 2)
    │
    LLM Prompt includes:
        command, flags, paths, is_sudo, cwd, user,
        rule hint: "confidence 0.40, escalating"
    │
    LLM responds (< 2s local):
        {"risk_level":"MEDIUM","confidence":0.82,
         "reasoning":"Executes cat on every .env file found...",
         "impact_summary":"Exposes all secret keys in .env files.",
         "safer_alternative":"find /home -name '.env' -ls"}
    │
    ResponseParser validates → Verdict(MEDIUM, 0.82, tier="llm")
    │
    AnalyzeResponse(should_block=True)        ← total: < 2.5s
    │
    User sees MEDIUM warning, types "s" (use safer)
    │
    Hook runs: find /home -name '.env' -ls   ← lists without exposing content
```

---

## 4. Latency Budget

| Code Path | Target | How Achieved |
|---|---|---|
| SAFE — pass-through | **< 20ms** | Warm daemon + Unix socket + instant rule skip |
| RISKY — Tier 0 | **< 30ms** | Pure in-memory structural check, no regex |
| RISKY — Tier 1 | **< 50ms** | Pre-compiled regex, ~30 patterns, no I/O |
| AMBIGUOUS → LLM | **< 3.5s** | 3s hard timeout, local 3B model |
| LLM timeout fallback | **< 20ms** | In-memory fallback verdict |

**Why Unix socket over TCP loopback:**
- TCP loopback: ~0.1–0.5ms per round trip (connection overhead)
- Unix socket: ~0.01–0.05ms per round trip
- At 100 commands/minute, this saves ~50ms/min — imperceptible but clean

---

## 5. Security Properties

| Property | How It's Achieved |
|---|---|
| **Never auto-execute** | `should_block=true` only pauses. User must type `y` to proceed. |
| **Never silent block** | Every interception shows a visible UI with reasoning. |
| **Privacy-first** | Ollama is the default LLM — commands never leave the machine. |
| **Fail-open** | If daemon crashes or times out, commands pass through with a one-time warning. The engine is a safety aid, not a gatekeeper. |
| **No root required** | Engine runs as the current user. No SUID, no kernel modules. |
| **Audit trail** | All flagged commands logged to `~/.intent_engine/logs/` in JSONL format. |
| **No command storage** | Only flagged commands are logged. SAFE commands are never persisted. |

---

## 6. File → Responsibility Map

```
engine/
├── models.py                ← Shared contract. All teams import this.
├── config.py                ← Config loader (TOML, user overrides)
│
├── daemon/
│   ├── server.py            ← FastAPI app, Unix socket, /analyze endpoint
│   ├── router.py            ← Tier orchestration, latency tracking
│   └── session.py           ← Per-session allowlist, stats
│
├── parser/
│   └── command_parser.py    ← shlex tokenizer, pipe splitter, structural detection
│
├── rule_engine/
│   ├── classifier.py        ← Entry point: classify(ParsedCommand) → Verdict
│   ├── pattern_matcher.py   ← check_tier0() + match() implementations
│   ├── pattern_loader.py    ← Loads + validates dangerous_patterns.toml
│   └── service.py           ← Standalone FastAPI for isolated testing
│
├── llm/
│   ├── client.py            ← Abstract base + provider factory
│   ├── providers/
│   │   ├── ollama.py        ← Local Ollama HTTP client
│   │   ├── gemini.py        ← Google Gemini API
│   │   └── openai.py        ← OpenAI API
│   ├── prompt_builder.py    ← System prompt + analysis prompt assembly
│   ├── reasoner.py          ← Core pipeline: prompt → LLM → parse → Verdict
│   ├── response_parser.py   ← JSON parse + schema validation
│   └── suggester.py         ← Safer alternative (table + LLM)
│
└── ui/
    └── terminal_ui.py       ← ANSI confirmation prompt, stdin/stdout interface

hooks/
├── intent_hook.zsh          ← Zsh preexec intercept
└── intent_hook.bash         ← Bash DEBUG trap intercept

rules/
└── dangerous_patterns.toml  ← Pattern library (Tier 0 + Tier 1)

config/
└── default_config.toml      ← All tuneable parameters with defaults
```
