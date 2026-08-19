#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 Setup + Verification Script
# Run this to install deps, start the daemon, and verify everything works.
# Usage: bash scripts/setup_phase1.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOCKET_PATH="/tmp/intent_engine.sock"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Intent Engine — Phase 1 Setup & Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Install dependencies ───────────────────────────────────────────────────
echo ""
echo "→ [1/5] Installing Python dependencies..."
pip install fastapi "uvicorn[standard]" pydantic toml structlog httpx rich click psutil --quiet
echo "  ✓ Dependencies installed"

# ── 2. Install package in editable mode ──────────────────────────────────────
echo ""
echo "→ [2/5] Installing intent-engine package (editable)..."
pip install -e "$REPO_DIR" --quiet
echo "  ✓ Package installed"

# ── 3. Kill any existing daemon ───────────────────────────────────────────────
echo ""
echo "→ [3/5] Stopping any existing daemon..."
if [ -f /tmp/intent_engine.pid ]; then
    OLD_PID=$(cat /tmp/intent_engine.pid)
    kill "$OLD_PID" 2>/dev/null && echo "  ✓ Stopped old daemon (PID $OLD_PID)" || echo "  ~ No daemon was running"
    rm -f /tmp/intent_engine.pid /tmp/intent_engine.sock
else
    echo "  ~ No existing daemon found"
fi

# ── 4. Start daemon in MOCK MODE ─────────────────────────────────────────────
echo ""
echo "→ [4/5] Starting daemon in MOCK MODE..."
export INTENT_MOCK_MODE=1
cd "$REPO_DIR"
python3 -m engine.daemon.server &
DAEMON_PID=$!
echo "  ~ Daemon PID: $DAEMON_PID (mock mode)"

# Wait for socket to be created
MAX_WAIT=10
WAITED=0
while [ ! -S "$SOCKET_PATH" ] && [ $WAITED -lt $MAX_WAIT ]; do
    sleep 0.3
    WAITED=$((WAITED + 1))
done

if [ ! -S "$SOCKET_PATH" ]; then
    echo "  ✗ ERROR: Daemon did not create socket at $SOCKET_PATH"
    echo "  Run manually: INTENT_MOCK_MODE=1 python3 -m engine.daemon.server"
    exit 1
fi
echo "  ✓ Socket ready at $SOCKET_PATH"

# ── 5. Verify endpoints ───────────────────────────────────────────────────────
echo ""
echo "→ [5/5] Verifying endpoints..."

# Health check
HEALTH=$(curl --silent --max-time 3 --unix-socket "$SOCKET_PATH" http://localhost/health)
if echo "$HEALTH" | grep -q '"ok"'; then
    echo "  ✓ /health → $HEALTH"
else
    echo "  ✗ /health failed: $HEALTH"
    exit 1
fi

# Analyze a safe command
SAFE_RESP=$(curl --silent --max-time 3 \
    --unix-socket "$SOCKET_PATH" \
    -X POST http://localhost/analyze \
    -H "Content-Type: application/json" \
    -d '{
        "context": {
            "command": "ls -la /home",
            "cwd": "/home",
            "user": "harshit",
            "is_sudo": false,
            "shell": "bash",
            "session_id": "phase1-test-001"
        },
        "dry_run": false
    }')

if echo "$SAFE_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'verdict' in d, 'missing verdict'
assert 'should_block' in d, 'missing should_block'
print(f'  ✓ /analyze → risk={d[\"verdict\"][\"risk_level\"]}, blocked={d[\"should_block\"]}')
" 2>&1; then
    echo ""
else
    echo "  ✗ /analyze failed: $SAFE_RESP"
    exit 1
fi

# Stats
STATS=$(curl --silent --max-time 3 --unix-socket "$SOCKET_PATH" http://localhost/stats)
echo "  ✓ /stats → $STATS"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Phase 1 daemon is running (MOCK MODE)"
echo ""
echo "  To test manually:"
echo '  curl --unix-socket /tmp/intent_engine.sock \
    -X POST http://localhost/analyze \
    -H "Content-Type: application/json" \
    -d '"'"'{"context":{"command":"rm -rf /","cwd":"/","user":"test","is_sudo":false,"shell":"bash","session_id":"t1"},"dry_run":false}'"'"' | python3 -m json.tool'
echo ""
echo "  To stop daemon:  kill $(cat /tmp/intent_engine.pid 2>/dev/null)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
