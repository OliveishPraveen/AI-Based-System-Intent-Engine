#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — One-Command Installer
# Owner: Harshit
# ═══════════════════════════════════════════════════════════════════════════════
set -e

INSTALL_DIR="$HOME/.intent_engine"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$INSTALL_DIR/config"
HOOKS_DIR="$INSTALL_DIR/hooks"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Intent Engine — Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Create directories
mkdir -p "$INSTALL_DIR/logs" "$CONFIG_DIR" "$HOOKS_DIR"

# 2. Install Python package
echo "→ Installing Python package..."
pip install -e "$REPO_DIR" --quiet

# 3. Copy default config (don't overwrite if user has customized)
if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
    cp "$REPO_DIR/config/default_config.toml" "$CONFIG_DIR/config.toml"
    echo "→ Created config at $CONFIG_DIR/config.toml"
fi

# 4. Copy hooks
cp "$REPO_DIR/hooks/intent_hook.zsh"  "$HOOKS_DIR/"
cp "$REPO_DIR/hooks/intent_hook.bash" "$HOOKS_DIR/"

# 5. Add hook source lines to shell rc files
ZSH_LINE="source \"$HOOKS_DIR/intent_hook.zsh\""
BASH_LINE="source \"$HOOKS_DIR/intent_hook.bash\""

if [[ -f "$HOME/.zshrc" ]] && ! grep -q "intent_hook.zsh" "$HOME/.zshrc"; then
    echo "" >> "$HOME/.zshrc"
    echo "# Intent Engine — AI-Based Safe Command Execution" >> "$HOME/.zshrc"
    echo "$ZSH_LINE" >> "$HOME/.zshrc"
    echo "→ Added zsh hook to ~/.zshrc"
fi

if [[ -f "$HOME/.bashrc" ]] && ! grep -q "intent_hook.bash" "$HOME/.bashrc"; then
    echo "" >> "$HOME/.bashrc"
    echo "# Intent Engine — AI-Based Safe Command Execution" >> "$HOME/.bashrc"
    echo "$BASH_LINE" >> "$HOME/.bashrc"
    echo "→ Added bash hook to ~/.bashrc"
fi

# 6. Start daemon
echo "→ Starting Intent Engine daemon..."
python3 -m engine.daemon.server &
disown
sleep 1

# 7. Health check
if curl --silent --max-time 2 --unix-socket /tmp/intent_engine.sock http://localhost/health | grep -q "ok"; then
    echo "✓ Daemon is running"
else
    echo "⚠ Daemon health check failed — run 'python3 -m engine.daemon.server' manually"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Intent Engine installed successfully!"
echo "  Restart your terminal or run: source ~/.zshrc"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
