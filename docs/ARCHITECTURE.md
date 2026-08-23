# AI System Intent Engine — Architecture

## 1. System Overview

```mermaid
graph TB
    User["👤 User<br/>(Linux Shell)"]

    subgraph Shell["Shell Layer (Zsh/Bash)"]
        ZSH["ZLE accept-line<br/>hook override"]
        AC["Intent Copilot<br/>Ghost-text autocomplete"]
    end

    subgraph Daemon["Intent Engine Daemon (FastAPI + Unix Socket)"]
        direction TB
        Router["Verdict Router"]

        subgraph Pipeline["Three-Tier Decision Pipeline"]
            T0["Tier 0<br/>Hardcoded Regex<br/>< 1ms"]
            T1["Tier 1<br/>TOML Pattern Library<br/>41 patterns · < 50ms"]
            T2["Tier 2<br/>Gemini 3.6 Flash<br/>LRU Cache · < 2s"]
        end

        T0 -->|"AMBIGUOUS"| T1
        T1 -->|"AMBIGUOUS"| T2
    end

    subgraph Output["Output Layer"]
        UI["Terminal UI<br/>ANSI 256-color prompt<br/>[y/n/s]"]
        Audit["Audit Logger<br/>~/.intent_engine/logs/audit.jsonl"]
        Allow["Shell continues<br/>Command executes"]
    end

    User -->|"types command"| AC
    AC -.->|"ghost-text"| User
    User -->|"presses Enter"| ZSH
    ZSH -->|"HTTP POST /analyze<br/>Unix Socket"| Router
    Router --> Pipeline
    Pipeline --> Router
    Router -->|"risk >= threshold"| UI
    Router -->|"risk < threshold"| Allow
    UI -->|"user chooses"| Audit
    Allow --> Audit

    style T0 fill:#c0392b,color:#fff
    style T1 fill:#e67e22,color:#fff
    style T2 fill:#2980b9,color:#fff
    style UI fill:#27ae60,color:#fff
    style Audit fill:#8e44ad,color:#fff
```

---

## 2. Three-Tier Decision Pipeline

```mermaid
flowchart TD
    CMD(["Raw Command<br/>e.g. sudo rm -rf /opt/db"])

    CMD --> PRE["Command Parser<br/>shlex · AST · alias resolution"]

    PRE --> T0{"Tier 0<br/>Hardcoded Regex<br/>Fork bomb · rm -rf / · dd to device<br/>curl|bash"}

    T0 -->|"MATCH"| CRIT["CRITICAL Verdict<br/>< 1ms · 100% confidence"]

    T0 -->|"NO MATCH"| T1{"Tier 1<br/>TOML Pattern Library<br/>41 patterns · confidence scoring"}

    T1 -->|"HIGH confidence<br/>match"| VERDICT1["Definitive Verdict<br/>SAFE / LOW / MEDIUM / HIGH / CRITICAL<br/>< 50ms"]

    T1 -->|"confidence < threshold<br/>AMBIGUOUS"| CACHE{"LRU Cache<br/>128 entries<br/>MD5 key on raw command"}

    CACHE -->|"HIT"| CACHED["Cached Verdict<br/>< 1ms"]
    CACHE -->|"MISS"| T2["Tier 2<br/>Gemini 3.6 Flash API<br/>Structured JSON response<br/>~800ms – 2s"]

    T2 --> PARSE["ResponseParser<br/>JSON schema validation"]
    PARSE --> STORE["Store in LRU cache"]
    STORE --> VERDICT2["LLM Verdict<br/>risk · confidence · reasoning<br/>impact · safer alternative"]

    CRIT --> ROUTER
    VERDICT1 --> ROUTER
    CACHED --> ROUTER
    VERDICT2 --> ROUTER

    ROUTER{"Verdict Router<br/>compare risk_level<br/>to block_threshold"}
    ROUTER -->|"risk >= threshold"| BLOCK["Render Terminal UI<br/>Wait for [y/n/s]"]
    ROUTER -->|"risk < threshold"| PASS["Allow execution"]

    style CRIT fill:#c0392b,color:#fff
    style T0 fill:#c0392b,color:#fff,stroke:#922b21
    style T1 fill:#e67e22,color:#fff,stroke:#a04000
    style T2 fill:#2980b9,color:#fff,stroke:#1a5276
    style CACHE fill:#16a085,color:#fff
    style BLOCK fill:#27ae60,color:#fff
```

---

## 3. Shell Hook Integration

```mermaid
sequenceDiagram
    participant U as User
    participant ZSH as Zsh Shell
    participant H as intent_hook.zsh<br/>(accept-line override)
    participant D as Daemon<br/>/tmp/intent_engine.sock
    participant UI as terminal_ui.py

    U->>ZSH: types "sudo rm -rf /opt/db" + Enter
    ZSH->>H: accept-line fires (before execution)
    H->>D: curl POST /analyze (JSON payload)
    Note over H,D: synchronous — shell is paused

    alt Risk >= block_threshold
        D-->>H: {"should_block": true, "verdict": {...}}
        H->>UI: pipe verdict JSON to terminal_ui.py
        UI-->>U: render ANSI risk prompt [y/n/s]
        U-->>UI: chooses 'n' (abort)
        UI-->>H: exit code = ABORT
        H->>ZSH: discard command, return to prompt
    else Risk < block_threshold
        D-->>H: {"should_block": false, "verdict": {...}}
        H->>ZSH: call .accept-line (execute normally)
    end

    H->>D: POST /audit (fire-and-forget)
```

---

## 4. Autocomplete (CLI Copilot) Flow

```mermaid
flowchart LR
    KEY["Keystroke<br/>(self-insert ZLE widget)"]

    KEY --> LEN{"len(buffer) ≥ 3?"}
    LEN -->|"No"| NONE["No suggestion"]

    LEN -->|"Yes"| LOCAL{"Tier A<br/>Local Dict lookup<br/>400+ entries<br/>pure Zsh associative array"}

    LOCAL -->|"HIT"| GHOST["Show ghost-text<br/>via POSTDISPLAY<br/>0ms · This keypress"]

    LOCAL -->|"MISS"| ASYNC["Fire async fetch<br/>(non-blocking)"]

    ASYNC --> APICALL["POST /autocomplete<br/>Daemon → Gemini API<br/>~600ms"]

    APICALL --> CB["_iac_llm_cb<br/>ZLE file descriptor callback"]
    CB --> GHOST2["Show ghost-text<br/>when result arrives"]

    GHOST --> TAB{"User presses Tab?"}
    GHOST2 --> TAB

    TAB -->|"Yes"| ACCEPT["BUFFER = full suggestion<br/>POSTDISPLAY = ''"]
    TAB -->|"No (ESC)"| DISMISS["Clear ghost-text"]
    TAB -->|"No (Enter)"| SAFETY["Chain to<br/>intent_hook.zsh<br/>(safety engine)"]

    style LOCAL fill:#16a085,color:#fff
    style APICALL fill:#2980b9,color:#fff
    style GHOST fill:#27ae60,color:#fff
    style GHOST2 fill:#27ae60,color:#fff
    style SAFETY fill:#e67e22,color:#fff
```

---

## 5. LLM Reasoning Component

```mermaid
flowchart TD
    INPUT["ParsedCommand + CommandContext + rule_hint"]

    INPUT --> CACHE_CHECK{"LRU Verdict Cache<br/>128 entries<br/>keyed on MD5(raw_command)"}

    CACHE_CHECK -->|"HIT"| RETURN_CACHE["Return cached Verdict<br/>< 1ms"]

    CACHE_CHECK -->|"MISS"| PROMPT["PromptBuilder<br/>System prompt: schema + rules<br/>User prompt: command + context + hint<br/>~350 tokens total"]

    PROMPT --> GEMINI["GeminiClient<br/>google-genai SDK<br/>model: gemini-3.6-flash<br/>response_mime_type: application/json<br/>temperature: 0.1<br/>runs in executor (async)"]

    GEMINI --> PARSE["ResponseParser<br/>JSON schema validation<br/>risk_level · confidence<br/>reasoning · impact · safer_alt"]

    PARSE --> SUGGEST["SaferAlternativeSuggester<br/>Curated lookup table first<br/>LLM output as fallback<br/>No second API call"]

    SUGGEST --> BUILD["Build final Verdict"]
    BUILD --> STORE_CACHE["Store in LRU cache<br/>(if not AMBIGUOUS)"]
    STORE_CACHE --> RETURN_LLM["Return Verdict"]

    style GEMINI fill:#2980b9,color:#fff
    style CACHE_CHECK fill:#16a085,color:#fff
    style RETURN_CACHE fill:#16a085,color:#fff
```

---

## 6. Rule Engine Component (Tier 0 + Tier 1)

```mermaid
flowchart TD
    RAW["Raw command string"]

    RAW --> PARSER["CommandParser<br/>shlex · pipeline · redirect · subshell AST<br/>alias resolution"]

    PARSER --> OBF["ObfuscationDetector<br/>base64 · hex · variable expansion<br/>eval · backtick nesting"]

    OBF --> T0["Tier 0 Structural Checks<br/>Hardcoded regex — no TOML<br/>_FORK_BOMB_RE · _RM_ROOT_RE<br/>_DD_DEVICE_RE · _CURL_PIPE_RE"]

    T0 -->|"MATCH"| CRIT_VERDICT["CRITICAL Verdict<br/>confidence=1.0<br/>< 1ms"]

    T0 -->|"NO MATCH"| PER_SEG["Per-segment iteration<br/>(handles pipelines A | B | C)"]

    PER_SEG --> TOML["TOML Pattern Matcher<br/>41 patterns loaded at startup<br/>hot-reloadable via /reload-rules"]

    TOML --> SCORE["Confidence Scorer<br/>base_confidence<br/>+0.15 if is_sudo<br/>+0.20 if path in critical prefixes<br/>+0.10 per relevant flag present<br/>+0.05 if cwd near dangerous path"]

    SCORE --> THRESH{"confidence ≥<br/>ambiguous_threshold?"}

    THRESH -->|"Yes"| DEFINITE["Definitive verdict<br/>SAFE · LOW · MEDIUM · HIGH · CRITICAL<br/>< 50ms"]

    THRESH -->|"No"| AMB["AMBIGUOUS<br/>Escalate to Tier 2"]

    style T0 fill:#c0392b,color:#fff
    style TOML fill:#e67e22,color:#fff
    style CRIT_VERDICT fill:#c0392b,color:#fff
    style AMB fill:#2980b9,color:#fff
```

---

## 7. Data Flow & Component Layers

```mermaid
graph LR
    subgraph Infra["Infrastructure Layer"]
        H1["engine/daemon/"]
        H2["engine/parser/"]
        H3["engine/ui/"]
        H4["engine/audit/"]
        H5["hooks/"]
        H6["install.sh"]
    end

    subgraph Rules["Rule Engine Layer"]
        P1["engine/rule_engine/"]
        P2["rules/dangerous_patterns.toml"]
    end

    subgraph AI["AI Reasoning Layer"]
        V1["engine/llm/"]
        V2["engine/alternatives/"]
        V3["engine/risk/"]
        V4["engine/contracts/"]
    end

    H5 -->|"Unix socket POST"| H1
    H1 -->|"ParsedCommand"| H2
    H2 -->|"ParsedCommand"| P1
    P1 -->|"Verdict / AMBIGUOUS"| H1
    H1 -->|"AMBIGUOUS → reason()"| V1
    V1 -->|"Verdict"| H1
    H1 -->|"Verdict"| H3
    H3 -->|"user decision"| H4
    V4 -->|"shared schemas"| H1
    V4 -->|"shared schemas"| P1
    V4 -->|"shared schemas"| V1

    style Infra fill:#1a252f,color:#fff,stroke:#2980b9
    style Rules fill:#1a252f,color:#fff,stroke:#e67e22
    style AI fill:#1a252f,color:#fff,stroke:#27ae60
```

---

## 8. Audit Log Pipeline

```mermaid
flowchart LR
    VERDICT["Final Verdict<br/>+ user decision"] --> LOGGER["AuditLogger<br/>engine/audit/"]

    LOGGER --> JSONL["~/.intent_engine/logs/audit.jsonl<br/>append-only"]

    JSONL --> FORMAT["JSON Record:<br/>timestamp · command · risk_level<br/>confidence · pattern · tier<br/>action · user · cwd<br/>session_id · latency_ms"]

    FORMAT -.->|"future"| ANALYTICS["Analytics Dashboard<br/>(planned)"]

    style LOGGER fill:#8e44ad,color:#fff
    style JSONL fill:#2c3e50,color:#fff
```

---

## 9. Performance Summary

```mermaid
xychart-beta
    title "Latency by Tier (ms, log scale)"
    x-axis ["Tier 0 (regex)", "Tier 1 (TOML)", "LRU Cache hit", "Tier 2 (Gemini)"]
    y-axis "Latency (ms)" 0 --> 2000
    bar [1, 50, 1, 1200]
```
