#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Zsh Shell Hook (Owner: Harshit)
# ═══════════════════════════════════════════════════════════════════════════════
#
# ARCHITECTURE: ZLE accept-line override
# ───────────────────────────────────────
# The previous approach used preexec(), which fires AFTER the command is
# already committed to execute — it's too late to stop it.
#
# This hook overrides the ZLE `accept-line` widget, which fires when the
# user presses Enter — BEFORE execution. We can:
#   • Clear BUFFER → command is wiped, never executes   (ABORT)
#   • Replace BUFFER → run a safer alternative          (USE_SAFER)
#   • Call original accept-line → command runs normally (EXECUTE)
#
# INSTALL:
#   Add to ~/.zshrc:
#     source /path/to/intent_hook.zsh
#
# BYPASS (one-shot):
#   INTENT_ENGINE_SKIP=1 <dangerous-command>
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Config ───────────────────────────────────────────────────────────────────
INTENT_SOCKET="${INTENT_SOCKET:-/tmp/intent_engine.sock}"
INTENT_ENGINE_ENABLED="${INTENT_ENGINE_ENABLED:-1}"
INTENT_SESSION_ID="${INTENT_SESSION_ID:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$$-$(date +%s)")}"
export INTENT_SESSION_ID

# Repo root (this file is hooks/intent_hook.zsh → parent is repo root)
INTENT_REPO_DIR="${0:A:h:h}"
export PYTHONPATH="${INTENT_REPO_DIR}:${PYTHONPATH:-}"

# ─── Watched command families (same as bash hook) ─────────────────────────────
typeset -A _INTENT_WATCH_SET
for _w in rm shred wipe dd \
          mkfs mkfs.ext4 mkfs.xfs mkfs.btrfs mkfs.fat mkfs.vfat \
          chmod chown \
          curl wget \
          sudo su doas \
          bash sh zsh fish dash ksh \
          python3 python perl ruby node \
          nc netcat ncat \
          iptables ip6tables nftables \
          fdisk parted gdisk \
          mount umount \
          kill killall pkill \
          crontab at; do
    _INTENT_WATCH_SET[$_w]=1
done

# ─── Daemon health check ─────────────────────────────────────────────────────
_intent_check_daemon() {
    curl --silent --max-time 1 --unix-socket "$INTENT_SOCKET" \
         http://localhost/health >/dev/null 2>&1
}

# Auto-start daemon if socket is missing
if [[ ! -S "$INTENT_SOCKET" ]]; then
    print -u2 "\033[2m  Intent Engine: daemon not running. Starting...\033[0m"
    (cd "$INTENT_REPO_DIR" && PYTHONPATH="$INTENT_REPO_DIR" \
        python3 -m engine.daemon.server &) 2>/dev/null
    disown 2>/dev/null
    sleep 1
    if _intent_check_daemon; then
        print -u2 "\033[32m  ✓ Intent Engine started.\033[0m"
    else
        print -u2 "\033[33m  ⚠ Intent Engine: could not start daemon.\033[0m"
        INTENT_ENGINE_ENABLED=0
    fi
fi

# ─── ZLE widget: intercepts Enter key BEFORE execution ────────────────────────
_intent_accept_line() {
    local cmd="$BUFFER"

    # ── Fast-path skips ───────────────────────────────────────────────────────
    if [[ "$INTENT_ENGINE_ENABLED" != "1" || -z "$cmd" ]]; then
        zle .accept-line
        return
    fi

    # One-shot bypass
    if [[ "$INTENT_ENGINE_SKIP" == "1" ]]; then
        unset INTENT_ENGINE_SKIP
        zle .accept-line
        return
    fi

    # ── Allowlist check (first word) ──────────────────────────────────────────
    local first="${cmd%% *}"
    # Always check fork bombs; skip everything else not in watch set
    if [[ "$first" != ":("* && -z "${_INTENT_WATCH_SET[$first]+x}" ]]; then
        zle .accept-line
        return
    fi

    # ── Daemon must be reachable ──────────────────────────────────────────────
    if [[ ! -S "$INTENT_SOCKET" ]]; then
        zle .accept-line
        return
    fi

    # ── Build JSON payload ────────────────────────────────────────────────────
    local payload
    payload=$(python3 - "$cmd" <<'PYEOF'
import json, os, sys
cmd = sys.argv[1]
print(json.dumps({
    "context": {
        "command": cmd,
        "cwd":     os.getcwd(),
        "user":    os.environ.get("USER", ""),
        "is_sudo": cmd.strip().startswith("sudo"),
        "shell":   "zsh",
        "session_id": os.environ.get("INTENT_SESSION_ID", ""),
    },
    "dry_run": False
}))
PYEOF
) 2>/dev/null

    if [[ -z "$payload" ]]; then
        zle .accept-line
        return
    fi

    # ── Call daemon ────────────────────────────────────────────────────────────
    local response
    response=$(curl --silent --max-time 4 \
        --unix-socket "$INTENT_SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null)

    if [[ -z "$response" ]]; then
        zle .accept-line
        return
    fi

    # ── Parse verdict ─────────────────────────────────────────────────────────
    local should_block
    should_block=$(python3 -c "
import json,sys
try: print('1' if json.loads(sys.argv[1]).get('should_block') else '0')
except: print('0')
" "$response" 2>/dev/null)

    if [[ "$should_block" != "1" ]]; then
        zle .accept-line
        return
    fi

    # ── Show confirmation UI ──────────────────────────────────────────────────
    # Print a newline first so UI renders below the current prompt line
    print </dev/tty
    local user_action
    user_action=$(echo "$response" | python3 -m engine.ui.terminal_ui 2>/dev/tty)

    case "$user_action" in
        EXECUTE)
            # User confirmed — run the command as-is
            zle .accept-line
            ;;

        USE_SAFER)
            local safer
            safer=$(python3 -c "
import json,sys
try: print(json.loads(sys.argv[1]).get('verdict',{}).get('safer_alternative','') or '')
except: print('')
" "$response" 2>/dev/null)
            if [[ -n "$safer" ]]; then
                # Replace buffer with safer command and re-render
                BUFFER="$safer"
                CURSOR=${#BUFFER}
                zle redisplay
                print -u2 "\n\033[2m  → replaced with: $safer\033[0m"
                # Do NOT call accept-line — user sees the safer command and decides
            else
                # No safer alternative available — treat as ABORT
                BUFFER=""
                CURSOR=0
                zle redisplay
                print -u2 "\n\033[2m  Intent Engine: aborted (no safer alternative).\033[0m"
            fi
            ;;

        ABORT|*)
            # ── TRUE ABORT: clear the buffer ─────────────────────────────────
            # The command is NEVER executed. BUFFER="" means nothing is submitted.
            BUFFER=""
            CURSOR=0
            zle redisplay
            print -u2 "\n\033[2m  Intent Engine: command aborted.\033[0m"
            ;;
    esac
}

# Register the widget
zle -N _intent_accept_line
# Bind Enter (^M) and Ctrl-J (^J) to our widget
bindkey "^M" _intent_accept_line
bindkey "^J" _intent_accept_line

print -u2 "\033[2m  Intent Engine: zsh hook active · session ${INTENT_SESSION_ID:0:8}\033[0m"
