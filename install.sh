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

# ─── 3. Zsh hook ──────────────────────────────────────────────────────────────
_head "[3/5] Zsh hook → ~/.zshrc"
if [[ -f "$HOME/.zshrc" ]]; then
    if grep -qF "$HOOK_ZSH" "$HOME/.zshrc" 2>/dev/null; then
        _ok "Zsh hook already present"
    else
        echo "" >> "$HOME/.zshrc"
        echo "# Intent Engine — shell safety hook" >> "$HOME/.zshrc"
        echo "source \"$HOOK_ZSH\"" >> "$HOME/.zshrc"
        _ok "Added to ~/.zshrc"
    fi
else
    _info "~/.zshrc not found — skipping zsh hook"
fi

# ─── 4. Start daemon ──────────────────────────────────────────────────────────
_head "[4/5] Starting daemon"
SOCKET="/tmp/intent_engine.sock"
PID_FILE="/tmp/intent_engine.pid"

# Kill any stale daemon
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE" "$SOCKET"
fi

PYTHONPATH="$REPO_DIR" python3 -m engine.daemon.server &
DAEMON_PID=$!
disown "$DAEMON_PID" 2>/dev/null || true

# Wait for socket
for i in $(seq 1 8); do
    if [[ -S "$SOCKET" ]]; then break; fi
    sleep 0.5
done

if curl --silent --max-time 1 --unix-socket "$SOCKET" http://localhost/health >/dev/null 2>&1; then
    _ok "Daemon running (PID $DAEMON_PID)"
    _info "Logs → ~/.intent_engine/logs/daemon.log"
    _info "Audit → ~/.intent_engine/logs/audit.jsonl"
else
    _warn "Daemon did not start — check logs at ~/.intent_engine/logs/daemon.log"
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
