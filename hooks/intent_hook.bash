#!/usr/bin/env bash
# Intent Engine — Bash Shell Hook (Owner: Harshit)
#
# INSTALL: source /path/to/intent_hook.bash  (add to ~/.bashrc)
# BYPASS:  INTENT_ENGINE_SKIP=1 <command>

INTENT_SOCKET="${INTENT_SOCKET:-/tmp/intent_engine.sock}"
INTENT_ENGINE_ENABLED="${INTENT_ENGINE_ENABLED:-1}"
INTENT_SESSION_ID="${INTENT_SESSION_ID:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$$-$(date +%s)")}"
INTENT_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export INTENT_SESSION_ID
export PYTHONPATH="${INTENT_REPO_DIR}:${PYTHONPATH}"

shopt -s extdebug

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
    nc netcat ncat
    iptables ip6tables nftables
    fdisk parted gdisk
    mount umount
    kill killall pkill
    crontab at
)

# Build a lookup set for O(1) check
declare -A _INTENT_WATCH_SET
for _w in "${_INTENT_WATCH[@]}"; do
    _INTENT_WATCH_SET["$_w"]=1
done

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
    local first="${cmd%% *}"   # first word only

    # ── Only analyze commands in the watch list (or fork bombs) ──────────────
    # Fork bomb: starts with :(
    if [[ "$first" != ":("* ]]; then
        # Not a fork bomb — check watch list
        [[ -z "${_INTENT_WATCH_SET[$first]+x}" ]] && return 0
    fi

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
echo -e "\033[2m  Intent Engine: active (watching ${#_INTENT_WATCH[@]} command families)\033[0m" >&2
