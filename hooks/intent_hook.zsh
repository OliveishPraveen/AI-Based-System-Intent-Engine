#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Zsh Shell Hook
# Owner: Harshit
# ═══════════════════════════════════════════════════════════════════════════════
#
# Zsh fires `preexec` BEFORE executing each command. We send the command
# to the daemon and, if RISKY, present a confirmation UI.
#
# IMPORTANT: Zsh's preexec() cannot directly prevent execution.
# We use a flag + precmd() to clear the buffer if the user chose ABORT.
#
# INSTALL:
#   Add to your ~/.zshrc:
#     source /path/to/intent_hook.zsh
#
# BYPASS:
#   INTENT_ENGINE_SKIP=1 rm -rf /tmp/test
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Config ───────────────────────────────────────────────────────────────────
INTENT_SOCKET="${INTENT_SOCKET:-/tmp/intent_engine.sock}"
INTENT_ENGINE_ENABLED="${INTENT_ENGINE_ENABLED:-1}"
INTENT_SESSION_ID="${INTENT_SESSION_ID:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$$-$(date +%s)")}"
export INTENT_SESSION_ID

# Repo root for module resolution
INTENT_REPO_DIR="${0:A:h:h}"
export PYTHONPATH="${INTENT_REPO_DIR}:${PYTHONPATH}"

# ─── State ────────────────────────────────────────────────────────────────────
typeset -g _INTENT_BLOCK=0       # 1 = user chose ABORT, suppress next command
typeset -g _INTENT_INTERNAL=0    # Guard against recursive interception

# ─── Daemon health check ─────────────────────────────────────────────────────
_intent_check_daemon() {
    curl --silent --max-time 1 --unix-socket "$INTENT_SOCKET" \
         http://localhost/health > /dev/null 2>&1
}

# Start daemon if not running
if ! _intent_check_daemon; then
    print -u2 "\033[2m  Intent Engine: daemon not running. Starting...\033[0m"
    (cd "$INTENT_REPO_DIR" && python3 -m engine.daemon.server &) 2>/dev/null
    disown 2>/dev/null
    sleep 1
    if _intent_check_daemon; then
        print -u2 "\033[32m  ✓ Intent Engine daemon started.\033[0m"
    else
        print -u2 "\033[33m  ⚠ Intent Engine: could not start daemon.\033[0m"
        INTENT_ENGINE_ENABLED=0
    fi
fi

# ─── Intercept: runs BEFORE every command ─────────────────────────────────────
_intent_preexec() {
    local cmd="$1"

    # Skip conditions
    [[ "$INTENT_ENGINE_ENABLED" != "1" ]] && return
    [[ "$_INTENT_INTERNAL" == "1" ]] && return
    [[ "$INTENT_ENGINE_SKIP" == "1" ]] && { unset INTENT_ENGINE_SKIP; return; }
    [[ "$cmd" == *"intent"* ]] && return
    [[ -z "$cmd" ]] && return

    _INTENT_INTERNAL=1

    # Build JSON payload
    local payload
    payload=$(python3 -c "
import json, os, sys
cmd = sys.argv[1]
print(json.dumps({
    'context': {
        'command': cmd,
        'cwd': os.getcwd(),
        'user': os.environ.get('USER', ''),
        'is_sudo': cmd.strip().startswith('sudo'),
        'shell': 'zsh',
        'session_id': os.environ.get('INTENT_SESSION_ID', ''),
    },
    'dry_run': False
}))
" "$cmd" 2>/dev/null)

    [[ -z "$payload" ]] && { _INTENT_INTERNAL=0; return; }

    # Call daemon
    local response
    response=$(curl --silent --max-time 4 \
        --unix-socket "$INTENT_SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null)

    [[ -z "$response" ]] && { _INTENT_INTERNAL=0; return; }

    # Check should_block
    local should_block
    should_block=$(echo "$response" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('1' if d.get('should_block') else '0')
except: print('0')
" 2>/dev/null)

    if [[ "$should_block" == "1" ]]; then
        # Show confirmation UI
        local user_action
        user_action=$(echo "$response" | python3 -m engine.ui.terminal_ui 2>/dev/tty)

        case "$user_action" in
            ABORT)
                print -u2 "\n\033[31m  ✗ Command aborted by Intent Engine.\033[0m"
                _INTENT_BLOCK=1
                ;;
            USE_SAFER)
                local safer
                safer=$(echo "$response" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('verdict', {}).get('safer_alternative', '') or '')
" 2>/dev/null)
                if [[ -n "$safer" ]]; then
                    print -u2 "\n\033[32m  → Running safer: $safer\033[0m"
                    _INTENT_BLOCK=1
                    _INTENT_INTERNAL=0
                    eval "$safer"
                    return
                fi
                _INTENT_BLOCK=1
                ;;
            EXECUTE)
                # User confirmed — let command proceed
                ;;
        esac
    fi

    _INTENT_INTERNAL=0
}

# ─── precmd: abort the command if _INTENT_BLOCK is set ────────────────────────
_intent_precmd() {
    if [[ "$_INTENT_BLOCK" == "1" ]]; then
        _INTENT_BLOCK=0
        # Kill the current command line by sending Ctrl-C to ZLE
        if [[ -n "$ZLE_LINE" ]]; then
            zle send-break 2>/dev/null
        fi
    fi
}

# ─── Register hooks ──────────────────────────────────────────────────────────
autoload -Uz add-zsh-hook
add-zsh-hook preexec _intent_preexec
add-zsh-hook precmd _intent_precmd

print -u2 "\033[2m  Intent Engine: shell hook active (session $INTENT_SESSION_ID)\033[0m"
