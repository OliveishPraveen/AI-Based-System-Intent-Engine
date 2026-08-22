#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Install Script
# Usage: ./install.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_BASH="$REPO_DIR/hooks/intent_hook.bash"
HOOK_ZSH="$REPO_DIR/hooks/intent_hook.zsh"

GREEN="\033[32m"
YELLOW="\033[33m"
GREY="\033[38;5;246m"
BOLD="\033[1m"
R="\033[0m"

_ok()   { echo -e "  ${GREEN}✓${R}  $*"; }
_warn() { echo -e "  ${YELLOW}⚠${R}  $*"; }
_info() { echo -e "  ${GREY}·${R}  $*"; }
_head() { echo -e "\n${BOLD}$*${R}"; }

echo ""
echo -e "${BOLD}  Intent Engine — Installer${R}"
echo -e "  ${GREY}AI-based shell safety for Linux${R}"
echo ""

# ─── 1. Python dependencies ───────────────────────────────────────────────────
_head "[1/5] Python dependencies"
if pip install -e "$REPO_DIR[dev]" -q; then
    _ok "Dependencies installed"
else
    _warn "pip install failed — continuing (may already be installed)"
fi

# ─── 2. Bash hook ─────────────────────────────────────────────────────────────
_head "[2/5] Bash hook → ~/.bashrc"
BASH_LINE="source \"$HOOK_BASH\""
if grep -qF "$HOOK_BASH" "$HOME/.bashrc" 2>/dev/null; then
    _ok "Bash hook already present"
else
    echo "" >> "$HOME/.bashrc"
    echo "# Intent Engine — shell safety hook" >> "$HOME/.bashrc"
    echo "$BASH_LINE" >> "$HOME/.bashrc"
    _ok "Added to ~/.bashrc"
fi

# ─── 3. Zsh hooks ─────────────────────────────────────────────────────────────
_head "[3/5] Zsh hooks → ~/.zshrc"
HOOK_ZSH_COPILOT="$REPO_DIR/hooks/intent_autocomplete.zsh"
if [[ -f "$HOME/.zshrc" ]]; then
    # Safety hook
    if grep -qF "$HOOK_ZSH" "$HOME/.zshrc" 2>/dev/null; then
        _ok "Zsh safety hook already present"
    else
        echo "" >> "$HOME/.zshrc"
        echo "# Intent Engine — shell safety hook" >> "$HOME/.zshrc"
        echo "source \"$HOOK_ZSH\"" >> "$HOME/.zshrc"
        _ok "Safety hook added to ~/.zshrc"
    fi
    # CLI Copilot (autocomplete) hook
    if grep -qF "$HOOK_ZSH_COPILOT" "$HOME/.zshrc" 2>/dev/null; then
        _ok "CLI Copilot hook already present"
    else
        echo "" >> "$HOME/.zshrc"
        echo "# Intent Engine — CLI Copilot (inline autocomplete)" >> "$HOME/.zshrc"
        echo "source \"$HOOK_ZSH_COPILOT\"" >> "$HOME/.zshrc"
        _ok "CLI Copilot hook added to ~/.zshrc"
    fi
else
    _info "~/.zshrc not found — skipping zsh hooks"
fi

# ─── 3b. Daemon watchdog (Zsh precmd) ────────────────────────────────────────
# Adds a lightweight function that fires on each new prompt and restarts
# the daemon if it has crashed. Zero UX impact — runs in background.
WATCHDOG_MARKER="# Intent Engine — daemon watchdog"
if [[ -f "$HOME/.zshrc" ]]; then
    if grep -qF "$WATCHDOG_MARKER" "$HOME/.zshrc" 2>/dev/null; then
        _ok "Daemon watchdog already present"
    else
        cat >> "$HOME/.zshrc" << WATCHDOG

$WATCHDOG_MARKER
_intent_watchdog() {
    local pid_file="/tmp/intent_engine.pid"
    local socket="/tmp/intent_engine.sock"
    [[ -S "\$socket" ]] && return  # socket exists → daemon is up
    local pid
    pid=\$(cat "\$pid_file" 2>/dev/null || true)
    if [[ -n "\$pid" ]] && kill -0 "\$pid" 2>/dev/null; then
        return  # PID alive but socket missing — still starting
    fi
    # Daemon is gone — restart silently in background
    local repo_dir="${REPO_DIR}"
    if [[ -f "\$repo_dir/engine/daemon/server.py" ]]; then
        (PYTHONPATH="\$repo_dir" python3 -m engine.daemon.server </dev/null &>/dev/null &)
    fi
}
# Fire watchdog on every new prompt
autoload -Uz add-zsh-hook
add-zsh-hook precmd _intent_watchdog
WATCHDOG
        _ok "Daemon watchdog added to ~/.zshrc"
    fi
fi


# ─── 4. Start daemon (systemd-first, fall back to background process) ─────────
_head "[4/5] Starting daemon"
SOCKET="/tmp/intent_engine.sock"
PID_FILE="/tmp/intent_engine.pid"
SERVICE_NAME="engine.daemon"
SYSTEMD_UNIT_DIR="$HOME/.config/systemd/user"
SRC_UNIT="$REPO_DIR/engine.daemon.service"
DST_UNIT="$SYSTEMD_UNIT_DIR/$SERVICE_NAME.service"

# Kill any stale daemon before starting fresh
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE" "$SOCKET"
fi

USED_SYSTEMD=0

# ── Attempt systemd user session ──────────────────────────────────────────────
if systemctl --user status > /dev/null 2>&1; then
    mkdir -p "$SYSTEMD_UNIT_DIR"

    # Generate a unit file with the correct absolute REPO_DIR baked in
    sed \
        -e "s|%h/Documents/CDAC_Hackathon_Intent_Engine|$REPO_DIR|g" \
        -e "s|WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|" \
        -e "s|Environment=PYTHONPATH=.*|Environment=PYTHONPATH=$REPO_DIR|" \
        "$SRC_UNIT" > "$DST_UNIT"

    systemctl --user daemon-reload
    if systemctl --user enable --now "$SERVICE_NAME" 2>/dev/null; then
        sleep 2
        if curl --silent --max-time 1 --unix-socket "$SOCKET" http://localhost/health > /dev/null 2>&1; then
            _ok "Daemon running via systemd (Restart=always, CPU≤25%, RAM≤256M)"
            _info "Manage: systemctl --user {start|stop|status|restart} $SERVICE_NAME"
            _info "Logs  → ~/.intent_engine/logs/daemon.log"
            _info "Audit → ~/.intent_engine/logs/audit.jsonl"
            USED_SYSTEMD=1
        fi
    fi
fi

# ── Fall back to background process if systemd unavailable ────────────────────
if [[ "$USED_SYSTEMD" -eq 0 ]]; then
    _info "systemd --user not available — using background process"
    PYTHONPATH="$REPO_DIR" python3 -m engine.daemon.server &
    DAEMON_PID=$!
    disown "$DAEMON_PID" 2>/dev/null || true

    for i in $(seq 1 8); do
        [[ -S "$SOCKET" ]] && break
        sleep 0.5
    done

    if curl --silent --max-time 1 --unix-socket "$SOCKET" http://localhost/health > /dev/null 2>&1; then
        _ok "Daemon running as background process (PID $DAEMON_PID)"
        _info "Logs → ~/.intent_engine/logs/daemon.log"
    else
        _warn "Daemon did not start — check ~/.intent_engine/logs/daemon.log"
    fi
fi

# ─── 5. Verify ────────────────────────────────────────────────────────────────
_head "[5/5] Smoke test"
RESULT=$(curl --silent --max-time 3 \
    --unix-socket "$SOCKET" \
    -X POST http://localhost/analyze \
    -H "Content-Type: application/json" \
    -d '{"context":{"command":"rm -rf /","cwd":"/","user":"install","is_sudo":false,"shell":"bash","session_id":"install"},"dry_run":true}' \
    2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    b=d.get('should_block',False)
    r=d.get('verdict',{}).get('risk_level','?')
    print(f'BLOCKED={b} RISK={r}')
except:
    print('PARSE_ERROR')
" 2>/dev/null)

if [[ "$RESULT" == *"BLOCKED=True"* ]] && [[ "$RESULT" == *"CRITICAL"* ]]; then
    _ok "Smoke test passed — $RESULT"
else
    _warn "Smoke test result: $RESULT"
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}${GREEN}Installation complete.${R}"
echo ""
echo -e "  ${GREY}To activate in your current session:${R}"
echo -e "  ${BOLD}    source ~/.bashrc${R}"
echo ""
echo -e "  ${GREY}Test it:${R}"
echo -e "  ${GREY}    dd if=/dev/zero of=/dev/sda${R}   ${GREEN}← will be intercepted${R}"
echo -e "  ${GREY}    rm -rf /                 ${R}   ${GREEN}← will be intercepted${R}"
echo -e "  ${GREY}    curl http://x.com/s.sh | bash${R} ${GREEN}← will be intercepted${R}"
echo ""
