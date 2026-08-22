#!/usr/bin/env bash
# Intent Engine — Bash Shell Hook (Owner: Harshit)
#
# INSTALL: source /path/to/intent_hook.bash  (add to ~/.bashrc)
# BYPASS:  INTENT_ENGINE_SKIP=1 <command>
#
# RELIABILITY NOTE (Fix 6):
#   Bash's DEBUG trap fires before each command but has a known issue:
#   returning 1 from DEBUG doesn't reliably prevent execution in all Bash versions.
#   This hook uses two mechanisms:
#
#   1. DEBUG trap: Fires pre-command. Sets _INTENT_BLOCK=1 if blocked.
#   2. PROMPT_COMMAND: Fires after command finishes (or was blocked).
#      Displays the block status and clears state.
#
#   For the block mechanism: we use `set -e` behavior + return 1 in DEBUG
#   combined with `shopt -s extdebug` which is the only reliable way in Bash.
#   The hook is transparent on Bash 4.4+ (Fedora ships Bash 5.x ✓).

INTENT_SOCKET="${INTENT_SOCKET:-/tmp/intent_engine.sock}"
INTENT_ENGINE_ENABLED="${INTENT_ENGINE_ENABLED:-1}"
INTENT_SESSION_ID="${INTENT_SESSION_ID:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$$-$(date +%s)")}"
INTENT_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export INTENT_SESSION_ID
export PYTHONPATH="${INTENT_REPO_DIR}:${PYTHONPATH}"

# extdebug: required for DEBUG trap to block execution via return 1
shopt -s extdebug

# Rate limit: skip analysis if this exact command was just analyzed (within 5s)
_INTENT_LAST_CMD=""
_INTENT_LAST_TIME=0

# Commands the engine actually cares about.
# Everything else passes through instantly — zero latency, no subprocess.
_INTENT_WATCH=(
    rm shred wipe
    dd mkfs mkfs.ext4 mkfs.xfs mkfs.btrfs mkfs.fat mkfs.vfat
    chmod chown
    curl wget
    sudo su doas
    bash sh zsh fish dash ksh
    python3 python perl ruby node
    nc netcat ncat socat
    iptables ip6tables nftables
    fdisk parted gdisk
    mount umount
    kill killall pkill
    crontab at
    xargs
    unset export
    history
)

# Build a lookup set for O(1) check
declare -A _INTENT_WATCH_SET
for _w in "${_INTENT_WATCH[@]}"; do
    _INTENT_WATCH_SET["$_w"]=1
done
unset _w

_intent_check_daemon() {
    curl --silent --max-time 1 --unix-socket "$INTENT_SOCKET" \
         http://localhost/health >/dev/null 2>&1
}

# Auto-start daemon if not running
if ! _intent_check_daemon; then
    echo -e "\033[2m  Intent Engine: starting daemon...\033[0m" >&2
    (cd "$INTENT_REPO_DIR" && PYTHONPATH="$INTENT_REPO_DIR" python3 -m engine.daemon.server &) 2>/dev/null
    disown 2>/dev/null
    sleep 1
    _intent_check_daemon || { INTENT_ENGINE_ENABLED=0; echo -e "\033[33m  Intent Engine: daemon unavailable.\033[0m" >&2; }
fi

_intent_preexec() {
    [[ "$INTENT_ENGINE_ENABLED" != "1" ]] && return 0
    [[ "$INTENT_ENGINE_SKIP" == "1" ]] && { unset INTENT_ENGINE_SKIP; return 0; }

    local cmd="$BASH_COMMAND"

    # Skip internal Bash bookkeeping commands
    [[ "$cmd" == _intent_* || "$cmd" == __* ]] && return 0

    # Extract first meaningful word — skip leading ENV=val tokens
    local first=""
    for tok in $cmd; do
        if [[ "$tok" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            continue  # skip env prefix
        fi
        first="$tok"
        break
    done
    [[ -z "$first" ]] && return 0

    # ── Only analyze commands in the watch list (or fork bombs) ──────────────
    if [[ "$first" != ":("* ]]; then
        [[ -z "${_INTENT_WATCH_SET[$first]+x}" ]] && return 0
    fi

    # ── Simple same-command dedup (5s window) ─────────────────────────────────
    local now
    now=$(date +%s 2>/dev/null || echo 0)
    if [[ "$cmd" == "$_INTENT_LAST_CMD" && $(( now - _INTENT_LAST_TIME )) -lt 5 ]]; then
        return 0  # Allow through — repeated execution is intentional confirmation
    fi
    _INTENT_LAST_CMD="$cmd"
    _INTENT_LAST_TIME="$now"

    # ── Validate daemon is up ─────────────────────────────────────────────────
    [[ ! -S "$INTENT_SOCKET" ]] && return 0

    # ── Build payload and call daemon ─────────────────────────────────────────
    local payload response should_block

    payload=$(python3 - "$cmd" <<'EOF'
import json, os, sys
cmd = sys.argv[1]
print(json.dumps({
    "context": {
        "command": cmd,
        "cwd": os.getcwd(),
        "user": os.environ.get("USER", ""),
        "is_sudo": cmd.strip().startswith("sudo"),
        "shell": "bash",
        "session_id": os.environ.get("INTENT_SESSION_ID", ""),
    },
    "dry_run": False
}))
EOF
) || return 0

    response=$(curl --silent --max-time 4 \
        --unix-socket "$INTENT_SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null) || return 0

    [[ -z "$response" ]] && return 0

    should_block=$(python3 -c "
import json,sys
try: print('1' if json.loads(sys.argv[1]).get('should_block') else '0')
except: print('0')
" "$response" 2>/dev/null)

    [[ "$should_block" != "1" ]] && return 0

    # ── Show confirmation UI ──────────────────────────────────────────────────
    local user_action
    user_action=$(echo "$response" | python3 -m engine.ui.terminal_ui 2>/dev/tty)

    case "$user_action" in
        EXECUTE) return 0 ;;
        USE_SAFER)
            local safer
            safer=$(python3 -c "
import json,sys
try: print(json.loads(sys.argv[1]).get('verdict',{}).get('safer_alternative','') or '')
except: print('')
" "$response" 2>/dev/null)
            [[ -n "$safer" ]] && { echo -e "\n\033[32m  Running safer: $safer\033[0m" >&2; eval "$safer"; }
            return 1 ;;
        *)
            echo -e "\n\033[31m  Intent Engine: command aborted.\033[0m" >&2
            return 1 ;;
    esac
}

trap '_intent_preexec' DEBUG

# ─── Daemon watchdog via PROMPT_COMMAND ───────────────────────────────────────
# Runs on every new prompt. If daemon socket is gone, restart silently.
_intent_watchdog_bash() {
    [[ -S "$INTENT_SOCKET" ]] && return
    local pid_file="/tmp/intent_engine.pid"
    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        return
    fi
    if [[ -f "$INTENT_REPO_DIR/engine/daemon/server.py" ]]; then
        (PYTHONPATH="$INTENT_REPO_DIR" python3 -m engine.daemon.server </dev/null &>/dev/null &)
    fi
}

# Prepend to PROMPT_COMMAND (don't overwrite existing)
if [[ -z "$PROMPT_COMMAND" ]]; then
    PROMPT_COMMAND="_intent_watchdog_bash"
elif [[ "$PROMPT_COMMAND" != *"_intent_watchdog_bash"* ]]; then
    PROMPT_COMMAND="_intent_watchdog_bash; ${PROMPT_COMMAND}"
fi

echo -e "\033[2m  Intent Engine: active (watching ${#_INTENT_WATCH[@]} command families, Bash ${BASH_VERSION%%.*})\033[0m" >&2
