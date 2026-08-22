#!/usr/bin/env zsh
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — CLI Copilot (POSTDISPLAY inline ghost-text style)
#
# Install:  source /path/to/hooks/intent_autocomplete.zsh  (in Zsh ONLY)
# Toggle:   INTENT_AUTOCOMPLETE=0  to disable
#
# ── Zsh guard ────────────────────────────────────────────────────────────────
[[ -z "$ZSH_VERSION" ]] && { echo "[intent-copilot] Error: This file requires Zsh. Run: exec zsh"; return 1; }
#
# UX:
#   As you type ≥3 chars, a faded ghost-text suggestion appears in-line
#   after your cursor (VS Code / Fish shell style via ZLE POSTDISPLAY).
#   Tab  → accept the suggestion
#   Esc  → dismiss
#   Enter → dismisses suggestion and runs command (goes through safety engine)
#
# PLUGIN CHAINING (Priority 4 fix):
#   This hook properly saves and chains any previously-bound self-insert
#   widget. Compatible with zsh-autosuggestions and zsh-syntax-highlighting.
# ═══════════════════════════════════════════════════════════════════════════════

[[ "${INTENT_AUTOCOMPLETE:-1}" != "1" ]] && return 0
INTENT_SOCKET="${INTENT_SOCKET:-/tmp/intent_engine.sock}"

# ─── State ────────────────────────────────────────────────────────────────────
typeset -g  _IAC_SUGGESTION=""   # current ghost-text (without the typed prefix)
typeset -g  _IAC_FD=""           # async curl fd
typeset -g  _IAC_LAST=""         # last buffer we fetched for (dedup)

# ─── Plugin chaining: save whatever self-insert is bound to RIGHT NOW ─────────
# This makes us compatible with zsh-autosuggestions and zsh-syntax-highlighting.
# If another plugin binds self-insert after us, they need to do the same.
if (( ${+functions[_intent_orig_self_insert]} == 0 )); then
    if zle -l self-insert &>/dev/null 2>&1; then
        # Another plugin has already overridden self-insert — save their version
        functions[_intent_orig_self_insert]=$functions[self-insert]
    else
        # No override yet — use the built-in .self-insert
        _intent_orig_self_insert() { zle .self-insert }
    fi
fi

# ─── Local command dictionary (pure Zsh, 0ms, no subprocess) ─────────────────
typeset -gA _IAC_DICT
_IAC_DICT=(
  # File Operations
  "ls -la"                            "List all files detailed"
  "ls -lh"                            "List with human sizes"
  "cat "                              "Display file contents"
  "cat -n "                           "Display with line numbers"
  "cp -r "                            "Copy dir recursively"
  "cp -i "                            "Copy with confirm"
  "mv -i "                            "Move with confirm"
  "rm -rf "                           "Remove dir recursively"
  "rm -i "                            "Remove with confirm"
  "mkdir -p "                         "Create nested dirs"
  "touch "                            "Create empty file"
  "ln -s "                            "Create symlink"
  "head -n 20 "                       "Show first 20 lines"
  "tail -f "                          "Follow file real time"
  "tail -n 50 "                       "Show last 50 lines"
  "less "                             "View file scrollable"
  "wc -l "                            "Count lines"
  "sort -u "                          "Sort unique"
  "diff -u "                          "Unified diff"
  # Text Processing
  "grep -rn "                         "Recursive search"
  "grep -rn --include='*.py' "        "Search Python files"
  "grep -i "                          "Case insensitive search"
  "sed -i 's///g' "                   "Find and replace"
  "awk '{print \$1}' "                "Print first column"
  "xargs -I {} "                      "Execute per line"
  # Search
  "find . -name '*.py' -type f"       "Find Python files"
  "find . -mtime -1 -type f"          "Files modified last 24h"
  "find . -size +100M"                "Files larger than 100MB"
  "which "                            "Find command location"
  # Package Managers
  "pip install "                      "Install Python package"
  "pip install -r requirements.txt"   "Install from requirements"
  "pip list"                          "List installed packages"
  "pip freeze > requirements.txt"     "Export requirements"
  "pip show "                         "Show package info"
  "pip3 install "                     "Install Python3 package"
  "apt update && apt upgrade -y"      "Update all packages"
  "apt install "                      "Install package"
  "apt search "                       "Search packages"
  "apt remove "                       "Remove package"
  "brew install "                     "Install brew package"
  "brew update && brew upgrade"       "Update brew packages"
  "snap install "                     "Install snap"
  # System Monitoring
  "ps aux"                            "List all processes"
  "ps aux | grep "                    "Find process"
  "htop"                              "Process viewer"
  "df -h"                             "Disk usage"
  "df -hT"                            "Disk usage with fs type"
  "du -sh "                           "Directory size"
  "du -sh * | sort -rh | head"        "Top 10 largest items"
  "free -h"                           "Memory usage"
  "uptime"                            "System uptime"
  "lsof -i :"                         "Find process on port"
  # Networking
  "ping -c 4 "                        "Ping host"
  "curl -s  | jq ."                   "Fetch JSON pretty"
  "curl -X POST -H 'Content-Type: application/json' -d" "POST JSON"
  "curl -I "                          "Fetch headers"
  "curl -o "                          "Download file"
  "wget "                             "Download file"
  "ssh -i ~/.ssh/id_ed25519 "         "Connect with key"
  "ssh -L 8080:localhost:8080 "       "Port forward"
  "scp -r  user@host:"               "Copy to remote"
  "rsync -avzP "                      "Sync with progress"
  "netstat -tlnp"                     "Show listening ports"
  "ss -tlnp"                          "Show listening ports"
  "ip addr show"                      "Show IP addresses"
  "dig "                              "DNS lookup"
  # Permissions
  "chmod +x "                         "Make executable"
  "chmod 755 "                        "Standard permissions"
  "chown -R "                         "Change owner recursive"
  # Compression
  "tar -czf archive.tar.gz "          "Create tar.gz"
  "tar -xzf "                         "Extract tar.gz"
  "zip -r archive.zip "               "Create zip"
  "unzip "                            "Extract zip"
  # Git
  "git commit -m \"\""                "Commit with message"
  "git push origin"                   "Push to remote"
  "git pull --rebase"                 "Fetch and rebase"
  "git status"                        "Working tree status"
  "git log --oneline --graph"         "Visual commit history"
  "git checkout -b "                  "Create new branch"
  "git diff --staged"                 "Show staged changes"
  "git stash push -m \"\""            "Stash with label"
  "git fetch --all"                   "Fetch all remotes"
  "git rebase -i HEAD~3"              "Interactive rebase"
  "git reset --hard HEAD"             "Discard all changes"
  "git clone "                        "Clone repository"
  "git add ."                         "Stage all changes"
  "git branch -d "                    "Delete branch"
  "git cherry-pick "                  "Apply commit"
  # Docker
  "docker ps -a"                      "List all containers"
  "docker build -t "                  "Build image"
  "docker run -it --rm "              "Run interactively"
  "docker-compose up -d"              "Start services"
  "docker exec -it "                  "Shell into container"
  "docker logs -f "                   "Follow logs"
  "docker system prune -af"           "Remove unused"
  "docker images"                     "List images"
  # Services
  "systemctl status "                 "Service status"
  "systemctl restart "                "Restart service"
  "systemctl enable --now "           "Enable and start"
  "systemctl list-units --failed"     "List failed units"
  "journalctl -u "                    "View service logs"
  "journalctl -f"                     "Follow journal"
  # Kubernetes
  "kubectl get pods -n "              "List pods"
  "kubectl logs -f "                  "Follow pod logs"
  "kubectl apply -f "                 "Apply manifest"
  "kubectl exec -it "                 "Shell into pod"
  # Dev Tools
  "npm run dev"                       "Start dev server"
  "npm install "                      "Install package"
  "npm run build"                     "Build production"
  "npm test"                          "Run tests"
  "npm init -y"                       "Initialize package"
  "npx "                              "Run npm package"
  "yarn add "                         "Add package"
  "yarn dev"                          "Start dev server"
  "cargo build --release"             "Build optimized"
  "cargo test"                        "Run Rust tests"
  "python3 -m venv .venv"             "Create virtual env"
  "python3 -m pytest"                 "Run pytest"
  "python3 -m pip install "           "Install package"
  "python3 -m http.server 8080"       "Local HTTP server"
  "python3 "                          "Run Python script"
  "pytest -v --tb=short"              "Run tests verbose"
  "pytest --cov= "                    "Run with coverage"
  "make"                              "Run default target"
  "make clean"                        "Clean build"
  "go build ./..."                    "Build Go project"
  "go test ./..."                     "Run Go tests"
  "node "                             "Run JavaScript"
  # Editors
  "nano "                             "Edit with nano"
  "vim "                              "Edit with vim"
  "code ."                            "Open VS Code here"
  # Misc
  "echo "                             "Print to stdout"
  "echo \$PATH"                       "Show PATH"
  "export PATH=\$PATH:"              "Add to PATH"
  "history | grep "                   "Search history"
  "man "                              "Show manual"
  "date"                              "Show date/time"
  "whoami"                            "Current user"
  "env"                               "Show env vars"
  "kill -9 "                          "Force kill process"
  "tmux new -s "                      "Create tmux session"
  "tmux attach -t "                   "Attach tmux session"
  "tmux ls"                           "List tmux sessions"
  "screen -S "                        "Create screen session"
  "crontab -l"                        "List cron jobs"
  "crontab -e"                        "Edit cron jobs"
  "watch -n 1 "                       "Run every second"
  "sudo "                             "Run as superuser"
  "sudo su"                           "Switch to root"
  "sudo apt update"                   "Update packages"
  # Intent Engine
  "PYTHONPATH=. python3 -m engine.daemon.server" "Start Intent daemon"
  "pytest tests/unit/ -v --tb=short"  "Run unit tests"
  "pytest tests/ -v --cov=engine"     "Run tests with coverage"
)

# ─── Clear ghost text ─────────────────────────────────────────────────────────
_iac_clear() {
    POSTDISPLAY=""
    _IAC_SUGGESTION=""
}

# ─── Show ghost text (suffix only — ZLE handles the dim rendering) ────────────
_iac_show() {
    local full_cmd="$1"
    local partial="$BUFFER"
    # Ghost text = everything after what's already typed
    if [[ "$full_cmd" == ${partial}* ]]; then
        POSTDISPLAY="${full_cmd#$partial}"
        _IAC_SUGGESTION="$full_cmd"
    fi
}

# ─── Pure-shell prefix lookup (0ms) ──────────────────────────────────────────
_iac_local_lookup() {
    local partial="$1"
    local best="" cmd
    for cmd in "${(@k)_IAC_DICT}"; do
        if [[ "$cmd" == ${partial}* ]]; then
            # Pick the shortest matching key (most specific to what's typed)
            if [[ -z "$best" || ${#cmd} -lt ${#best} ]]; then
                best="$cmd"
            fi
        fi
    done
    echo "$best"
}

# ─── Async LLM callback (fires only if local dict missed) ────────────────────
_iac_llm_cb() {
    local fd=$1 data
    IFS= read -r -u $fd data 2>/dev/null
    zle -F $fd 2>/dev/null
    exec {fd}<&- 2>/dev/null
    _IAC_FD=""

    # Only apply if buffer matches what we queried and no local suggestion showing
    [[ "$BUFFER" != "$_IAC_LAST" || -z "$data" || -n "$POSTDISPLAY" ]] && return

    local top
    top=$(python3 -c "
import json,sys
try:
    d=json.loads(sys.argv[1])
    c=d.get('completions',[])
    if c: print(c[0].get('cmd',''))
except: pass
" "$data" 2>/dev/null)

    [[ -n "$top" && "$top" == ${BUFFER}* ]] && _iac_show "$top"
    zle reset-prompt
}

# ─── Start async fetch from daemon ───────────────────────────────────────────
_iac_fetch_async() {
    local partial="$BUFFER"
    (( ${#partial} < 3 )) && return
    [[ ! -S "$INTENT_SOCKET" ]] && return
    [[ "$partial" == "$_IAC_LAST" ]] && return
    _IAC_LAST="$partial"

    # Clean up any previous pending request
    [[ -n "$_IAC_FD" ]] && { zle -F "$_IAC_FD" 2>/dev/null; exec {_IAC_FD}<&-; _IAC_FD=""; }

    local p
    p=$(python3 -c "
import json,os,sys
print(json.dumps({'partial':sys.argv[1],'cwd':os.getcwd()}))
" "$partial" 2>/dev/null)
    [[ -z "$p" ]] && return

    exec {_IAC_FD}< <(
        curl -s --max-time 2.0 --unix-socket "$INTENT_SOCKET" \
            -X POST http://localhost/autocomplete \
            -H 'Content-Type: application/json' \
            -d "$p" 2>/dev/null
    )
    zle -F "$_IAC_FD" _iac_llm_cb
}

# ─── Main keystroke handler ───────────────────────────────────────────────────
_iac_self_insert() {
    # Chain: call the previously-bound self-insert first
    _intent_orig_self_insert
    POSTDISPLAY=""   # Clear old ghost text immediately

    local partial="$BUFFER"
    (( ${#partial} < 3 )) && return

    # TIER A: synchronous local dict (0ms — shows on THIS keypress)
    local match
    match=$(_iac_local_lookup "$partial")
    if [[ -n "$match" ]]; then
        _iac_show "$match"
        return
    fi

    # TIER B: async LLM (shows when result arrives, ~80ms first token)
    _iac_fetch_async
}

# ─── Tab: accept ghost text ───────────────────────────────────────────────────
_iac_tab() {
    if [[ -n "$_IAC_SUGGESTION" ]]; then
        BUFFER="$_IAC_SUGGESTION"
        CURSOR="${#BUFFER}"
        POSTDISPLAY=""
        _IAC_SUGGESTION=""
    else
        zle expand-or-complete
    fi
}

# ─── Escape: dismiss ghost text ───────────────────────────────────────────────
_iac_escape() {
    if [[ -n "$POSTDISPLAY" ]]; then
        _iac_clear
    else
        zle send-break
    fi
}

# ─── Backspace: clear ghost + delete char ────────────────────────────────────
_iac_backspace() {
    POSTDISPLAY=""
    _IAC_SUGGESTION=""
    zle backward-delete-char
}

# ─── Enter: dismiss ghost + run through safety engine ─────────────────────────
_iac_enter() {
    _iac_clear
    # Clean up any pending async fd
    [[ -n "$_IAC_FD" ]] && { zle -F "$_IAC_FD" 2>/dev/null; exec {_IAC_FD}<&-; _IAC_FD=""; }
    # Chain to safety hook if loaded, otherwise run normally
    if zle -l _intent_accept_line &>/dev/null 2>&1; then
        zle _intent_accept_line
    else
        zle .accept-line
    fi
}

# ─── Register widgets & bind keys ────────────────────────────────────────────
zle -N self-insert       _iac_self_insert
zle -N _iac_tab
zle -N _iac_escape
zle -N _iac_backspace
zle -N _iac_enter

bindkey '^I'         _iac_tab          # Tab
bindkey '^['         _iac_escape       # Escape
bindkey '^?'         _iac_backspace    # Backspace
bindkey '^H'         _iac_backspace    # Ctrl-H (alt backspace)
bindkey '^M'         _iac_enter        # Enter
bindkey '^J'         _iac_enter        # Ctrl-J (newline)

echo "  Intent Copilot: type to suggest  Tab=accept  Esc=dismiss"
