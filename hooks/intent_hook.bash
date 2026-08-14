#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Bash Shell Hook
# Owner: Harshit
# ═══════════════════════════════════════════════════════════════════════════════
#
# Bash doesn't have preexec natively. We use:
#   - `trap ... DEBUG`   to intercept commands BEFORE they run
#   - `shopt -s extdebug` to enable the DEBUG trap with pre-execution semantics
#
# Returning 1 from the DEBUG trap prevents command execution.
# ═══════════════════════════════════════════════════════════════════════════════

INTENT_SOCKET="${INTENT_SOCKET:-/tmp/intent_engine.sock}"
INTENT_ENGINE_ENABLED="${INTENT_ENGINE_ENABLED:-1}"
INTENT_SESSION_ID="${INTENT_SESSION_ID:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null || echo "$$-$(date +%s)")}"

export INTENT_SESSION_ID

shopt -s extdebug

_intent_preexec() {
    local cmd="$BASH_COMMAND"

    [[ "$INTENT_ENGINE_ENABLED" != "1" ]] && return 0
    [[ "$INTENT_ENGINE_SKIP" == "1" ]] && { unset INTENT_ENGINE_SKIP; return 0; }
    [[ "$cmd" == *"intent"* || "$cmd" == "_intent"* ]] && return 0
    [[ "$cmd" == "true" || "$cmd" == ":" ]] && return 0  # Shell internals

    local payload
    payload=$(python3 -c "
import json, os, sys
print(json.dumps({
    'context': {
        'command': sys.argv[1],
        'cwd': os.getcwd(),
        'user': os.environ.get('USER', ''),
        'is_sudo': sys.argv[1].strip().startswith('sudo'),
        'shell': 'bash',
        'session_id': os.environ.get('INTENT_SESSION_ID', ''),
    },
    'dry_run': False
}))
" "$cmd" 2>/dev/null)

    [[ -z "$payload" ]] && return 0

    local response
    response=$(curl --silent --max-time 4 \
        --unix-socket "$INTENT_SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null)

    [[ -z "$response" ]] && return 0

    local should_block
    should_block=$(echo "$response" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('1' if d.get('should_block') else '0')
except: print('0')
" 2>/dev/null)

    if [[ "$should_block" == "1" ]]; then
        local user_action
        user_action=$(echo "$response" | python3 -m engine.ui.terminal_ui 2>/dev/null)

        case "$user_action" in
            ABORT)
                echo -e "\n\033[31m✗ Command aborted by Intent Engine.\033[0m" >&2
                return 1  # Prevents the command from executing
                ;;
            USE_SAFER)
                local safer
                safer=$(echo "$response" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('verdict', {}).get('safer_alternative', '') or '')
" 2>/dev/null)
                if [[ -n "$safer" ]]; then
                    echo -e "\n\033[32m→ Running safer: $safer\033[0m" >&2
                    eval "$safer"
                fi
                return 1
                ;;
            EXECUTE)
                return 0
                ;;
        esac
    fi
    return 0
}

trap '_intent_preexec' DEBUG
