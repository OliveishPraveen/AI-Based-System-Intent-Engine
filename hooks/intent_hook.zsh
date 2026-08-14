#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Zsh Shell Hook
# Owner: Harshit
# ═══════════════════════════════════════════════════════════════════════════════
#
# HOW IT WORKS:
#   Zsh fires `preexec` with the command string BEFORE executing it.
#   We send the command to the daemon and, if RISKY, block it and show
#   the confirmation UI. The user then chooses to proceed, abort, or edit.
#
# INSTALL:
#   The install.sh script appends `source ~/.intent_engine/hooks/intent_hook.zsh`
#   to your ~/.zshrc automatically.
#
# BYPASS:
#   Set INTENT_ENGINE_SKIP=1 to disable for a single command:
#     INTENT_ENGINE_SKIP=1 rm -rf /tmp/test
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Config ───────────────────────────────────────────────────────────────────
INTENT_SOCKET="${INTENT_SOCKET:-/tmp/intent_engine.sock}"
INTENT_DAEMON_URL="http://localhost:8765"  # HTTP fallback if socket unavailable
INTENT_ENGINE_ENABLED="${INTENT_ENGINE_ENABLED:-1}"
INTENT_SESSION_ID="${INTENT_SESSION_ID:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen)}"

# ─── Daemon health check (runs once at shell startup) ─────────────────────────
_intent_check_daemon() {
    curl --silent --unix-socket "$INTENT_SOCKET" \
         http://localhost/health > /dev/null 2>&1
}

# Start daemon if not running
_intent_start_daemon() {
    if ! _intent_check_daemon; then
        python3 -m engine.daemon.server &
        disown
        sleep 0.5  # Give daemon a moment to bind the socket
    fi
}
_intent_start_daemon

# ─── Main intercept hook ──────────────────────────────────────────────────────
preexec() {
    local cmd="$1"

    # Skip if engine disabled, or if the command is the engine itself
    [[ "$INTENT_ENGINE_ENABLED" != "1" ]] && return
    [[ "$INTENT_ENGINE_SKIP" == "1" ]] && { unset INTENT_ENGINE_SKIP; return; }
    [[ "$cmd" == *"intent"* ]] && return  # Don't analyze engine commands

    # Build JSON payload
    local payload
    payload=$(python3 -c "
import json, os, sys
print(json.dumps({
    'context': {
        'command': sys.argv[1],
        'cwd': os.getcwd(),
        'user': os.environ.get('USER', ''),
        'is_sudo': sys.argv[1].strip().startswith('sudo'),
        'shell': 'zsh',
        'session_id': os.environ.get('INTENT_SESSION_ID', ''),
    },
    'dry_run': False
}))
" "$cmd" 2>/dev/null)

    [[ -z "$payload" ]] && return

    # Call daemon
    local response
    response=$(curl --silent --max-time 4 \
        --unix-socket "$INTENT_SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null)

    [[ -z "$response" ]] && return

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
        # Delegate to Python UI for the confirmation prompt
        local user_action
        user_action=$(echo "$response" | python3 -m engine.ui.terminal_ui 2>/dev/null)

        case "$user_action" in
            ABORT)
                print -u2 "\n\033[31m✗ Command aborted.\033[0m"
                # Prevent execution by clearing the command buffer
                zle send-break 2>/dev/null
                return 1
                ;;
            USE_SAFER)
                # Replace command with safer alternative — re-inject into readline
                local safer
                safer=$(echo "$response" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('verdict', {}).get('safer_alternative', '') or '')
" 2>/dev/null)
                if [[ -n "$safer" ]]; then
                    print -u2 "\n\033[32m→ Running safer alternative: $safer\033[0m"
                    eval "$safer"
                    return 1
                fi
                ;;
            EXECUTE)
                # User confirmed — let the command proceed normally
                return 0
                ;;
        esac
    fi
}
