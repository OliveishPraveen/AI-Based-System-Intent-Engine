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
  "git commit -m \"\""            "Commit staged changes"
  "git push origin"               "Push current branch"
  "git pull --rebase"             "Fetch and rebase"
  "git rebase -i HEAD~3"          "Interactive rebase"
  "git stash push -m \"\""        "Stash with label"
  "git log --oneline --graph"     "Visual commit history"
  "git checkout -b "              "Create new branch"
  "git diff --staged"             "Show staged changes"
  "git status"                    "Show working tree status"
  "git fetch --all"               "Fetch all remotes"
  "git reset --hard HEAD"         "Discard all local changes"
  "git merge --no-ff "            "Merge with merge commit"
  "docker ps -a"                  "List all containers"
  "docker build -t "              "Build Docker image"
  "docker run -it --rm "          "Run container interactively"
  "docker-compose up -d"          "Start services detached"
  "docker exec -it "              "Shell into container"
  "docker logs -f "               "Follow container logs"
  "docker system prune -af"       "Remove unused resources"
  "systemctl status "             "Show service status"
  "systemctl restart "            "Restart service"
  "systemctl enable --now "       "Enable and start service"
  "systemctl list-units --failed" "List failed units"
  "journalctl -u "                "View service logs"
  "journalctl -f"                 "Follow system journal"
  "journalctl -p err -b"          "Errors since last boot"
  "kubectl get pods -n "          "List pods in namespace"
  "kubectl logs -f "              "Follow pod logs"
  "kubectl apply -f "             "Apply manifest file"
  "kubectl exec -it "             "Shell into pod"
  "kubectl describe pod "         "Show pod details"
  "npm run dev"                   "Start dev server"
  "npm install "                  "Install package"
  "npm run build"                 "Build production bundle"
  "npm test"                      "Run test suite"
  "python3 -m venv .venv"         "Create virtual environment"
  "python3 -m pytest"             "Run tests with pytest"
  "python3 -m http.server 8080"   "Start local HTTP server"
  "python3 -m pip install "       "Install package via pip"
  "cargo build --release"         "Build optimized binary"
  "cargo test"                    "Run Rust tests"
  "cargo clippy"                  "Lint with Clippy"
  "cargo add "                    "Add dependency"
  "ssh -i ~/.ssh/id_ed25519 "     "Connect with key"
  "curl -s "                      "Silent HTTP request"
  "curl -X POST -H 'Content-Type: application/json' -d" "POST JSON body"
  "find . -name '*.py' -type f"   "Find Python files"
  "find . -mtime -1 -type f"      "Files modified last 24h"
  "grep -rn "                     "Recursive search"
  "grep -rn --include='*.py' "    "Search Python files"
  "tar -czf archive.tar.gz "      "Create tar archive"
  "tar -xzf "                     "Extract tar archive"
  "rsync -avzP "                  "Sync with progress"
  "rsync -avz --delete "          "Sync and delete removed"
  "PYTHONPATH=. python3 -m engine.daemon.server" "Start Intent Engine daemon"
  "pytest tests/unit/ -v --tb=short" "Run unit tests"
  "pytest tests/ -v --cov=engine" "Run all tests with coverage"
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
        curl -s --max-time 0.8 --unix-socket "$INTENT_SOCKET" \
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
