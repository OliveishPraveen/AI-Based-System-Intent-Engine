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
# 400+ entries — covers every major Linux/dev command family.
# Goal: <5% LLM fallback rate in normal developer workflows.
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
  "sudo apt install "                 "Install package as root"
  "sudo systemctl restart "           "Restart service as root"
  "sudo journalctl -u "               "View service logs as root"
  "sudo vim "                         "Edit file as root"
  "sudo nano "                        "Edit file with nano as root"
  "sudo chmod "                       "Change permissions as root"
  "sudo chown "                       "Change ownership as root"
  # ── Process & Signal ───────────────────────────────────────────────────────
  "kill -9 "                          "Force kill by PID"
  "kill -15 "                         "Graceful terminate by PID"
  "killall "                          "Kill all by name"
  "pkill -f "                         "Kill by process name pattern"
  "pkill -9 "                         "Force kill by pattern"
  "pgrep -f "                         "Find PIDs by name"
  "nice -n 10 "                       "Run with lower priority"
  "renice -n 5 -p "                   "Change running priority"
  "nohup "                            "Run immune to hangup"
  "disown"                            "Disown background job"
  # ── Disk & Filesystem ──────────────────────────────────────────────────────
  "lsblk"                             "List block devices"
  "lsblk -f"                          "Block devices with filesystems"
  "fdisk -l"                          "List disk partitions"
  "blkid"                             "Show block device UUIDs"
  "mount "                            "Mount a filesystem"
  "umount "                           "Unmount a filesystem"
  "fsck "                             "Check filesystem integrity"
  "mkfs.ext4 "                        "Format as ext4"
  "mkfs.xfs "                         "Format as XFS"
  "resize2fs "                        "Resize ext filesystem"
  "dd if=/dev/zero bs=1M count=1024" "Create 1GB file of zeros"
  "dd if=/dev/urandom of= bs=1M"     "Fill file with random data"
  "shred -vzn 3 "                     "Securely overwrite file"
  "truncate -s 0 "                    "Truncate file to zero size"
  "fallocate -l 1G "                  "Allocate 1GB file"
  "inotifywait -m -r "               "Watch directory for changes"
  # ── LVM ───────────────────────────────────────────────────────────────────
  "lvdisplay"                         "Show logical volumes"
  "vgdisplay"                         "Show volume groups"
  "pvdisplay"                         "Show physical volumes"
  "lvcreate -L 10G -n "              "Create 10GB logical volume"
  "lvextend -L +5G "                  "Extend volume by 5GB"
  # ── Archives & Transfer ────────────────────────────────────────────────────
  "tar -czf archive.tar.gz "          "Create tar.gz archive"
  "tar -xzf "                         "Extract tar.gz"
  "tar -xvf "                         "Extract with verbose"
  "tar -tvf "                         "List tar contents"
  "zip -r archive.zip "               "Create zip archive"
  "unzip "                            "Extract zip"
  "unzip -l "                         "List zip contents"
  "gzip "                             "Compress file"
  "gunzip "                           "Decompress file"
  "bzip2 "                            "Compress with bzip2"
  "xz -9 "                            "Compress with xz max"
  "7z a archive.7z "                  "Create 7zip archive"
  "7z x "                             "Extract 7zip archive"
  "rsync -avzP "                      "Sync with progress"
  "rsync -avz --delete "              "Sync delete removed"
  "rsync -avzP --exclude="            "Sync excluding pattern"
  # ── Network Diagnostics ────────────────────────────────────────────────────
  "nmap -sV "                         "Scan ports with versions"
  "nmap -A "                          "Aggressive scan"
  "nmap -p 1-65535 "                  "Scan all ports"
  "nmap -sn "                         "Ping sweep no port scan"
  "netstat -tlnp"                     "Show listening ports"
  "ss -tlnp"                          "Show listening sockets"
  "ss -tnp"                           "Show established connections"
  "ip addr show"                      "Show IP addresses"
  "ip route show"                     "Show routing table"
  "ip link show"                      "Show network interfaces"
  "ip neigh show"                     "Show ARP table"
  "tcpdump -i eth0 -n"                "Capture packets on eth0"
  "tcpdump -i any port 80"            "Capture HTTP traffic"
  "tcpdump -w capture.pcap"           "Write capture to file"
  "iptables -L -n -v"                 "List all firewall rules"
  "iptables -A INPUT -p tcp --dport" "Add firewall rule"
  "iptables -F"                       "Flush all firewall rules"
  "ufw status verbose"                "UFW firewall status"
  "ufw allow "                        "Allow port in UFW"
  "ufw deny "                         "Deny port in UFW"
  "ufw enable"                        "Enable UFW firewall"
  "traceroute "                       "Trace network route"
  "mtr "                              "Live traceroute"
  "nc -lvnp "                         "Listen on port"
  "nc -zv  22"                        "Test port connectivity"
  "socat TCP-LISTEN: "                "Multipurpose relay"
  "dig +short "                       "Quick DNS lookup"
  "dig @8.8.8.8 "                     "DNS lookup via Google"
  "nslookup "                         "DNS lookup"
  "host "                             "DNS lookup utility"
  "whois "                            "Domain registration info"
  "curl -s  | jq ."                   "Fetch JSON pretty"
  "curl -X POST -H 'Content-Type: application/json' -d '{}' " "POST JSON"
  "curl -I "                          "Fetch headers only"
  "curl -o "                          "Download to file"
  "curl -L "                          "Follow redirects"
  "curl -u user:pass "                "HTTP basic auth"
  "curl --cert  --key "               "Client certificate auth"
  "wget "                             "Download file"
  "wget -c "                          "Resume download"
  "wget -r -np "                      "Recursive download"
  # ── SSH & Remote ──────────────────────────────────────────────────────────
  "ssh -i ~/.ssh/id_ed25519 "         "Connect with key"
  "ssh -L 8080:localhost:8080 "       "Local port forward"
  "ssh -R 8080:localhost:8080 "       "Remote port forward"
  "ssh -D 1080 "                      "SOCKS proxy via SSH"
  "ssh -o StrictHostKeyChecking=no " "Skip host key check"
  "ssh-keygen -t ed25519 -C "         "Generate ED25519 key"
  "ssh-copy-id -i ~/.ssh/id_ed25519" "Copy key to server"
  "ssh-add ~/.ssh/id_ed25519"         "Add key to agent"
  "scp -r  user@host:"               "Copy dir to remote"
  "sftp "                             "Secure file transfer"
  # ── OpenSSL & Crypto ──────────────────────────────────────────────────────
  "openssl genrsa -out key.pem 4096" "Generate RSA 4096 key"
  "openssl req -new -x509 -days 365" "Self-signed certificate"
  "openssl x509 -in cert.pem -text" "Show certificate details"
  "openssl s_client -connect :443"   "Test TLS connection"
  "openssl enc -aes-256-cbc -in "    "Encrypt file AES-256"
  "openssl dgst -sha256 "            "SHA256 hash of file"
  # ── Strace & Debugging ────────────────────────────────────────────────────
  "strace -p "                        "Trace syscalls of PID"
  "strace -e trace=file "             "Trace file syscalls"
  "strace -o trace.log "              "Write strace to file"
  "ltrace "                           "Trace library calls"
  "gdb "                              "GNU debugger"
  "gdb -p "                           "Attach GDB to PID"
  "valgrind --leak-check=full "       "Memory leak check"
  "perf stat "                        "Performance statistics"
  "perf top"                          "Live CPU profiling"
  "perf record -g "                   "Record with callgraph"
  "ldd "                              "Show shared library deps"
  "objdump -d "                       "Disassemble binary"
  "nm "                               "List symbols in binary"
  "strings "                          "Print printable strings"
  "file "                             "Identify file type"
  "hexdump -C "                       "Hex dump of file"
  "xxd "                              "Hex dump / reverse"
  # ── User & Group Management ───────────────────────────────────────────────
  "useradd -m -s /bin/bash "          "Create user with home"
  "usermod -aG sudo "                 "Add user to sudo group"
  "userdel -r "                       "Delete user and home"
  "passwd "                           "Change user password"
  "groupadd "                         "Create new group"
  "groups "                           "Show user groups"
  "id "                               "User and group IDs"
  "who"                               "Show logged in users"
  "w"                                 "Who is logged in doing what"
  "last"                              "Show login history"
  "lastlog"                           "Show last logins"
  "finger "                           "User info"
  # ── Virtualization ────────────────────────────────────────────────────────
  "virsh list --all"                  "List all VMs"
  "virsh start "                      "Start VM"
  "virsh shutdown "                   "Shutdown VM gracefully"
  "virsh destroy "                    "Force stop VM"
  "virsh snapshot-create-as "         "Create VM snapshot"
  "vboxmanage list runningvms"        "List VirtualBox VMs"
  "qemu-system-x86_64 "              "Run QEMU VM"
  # ── Containers (Podman/Compose) ───────────────────────────────────────────
  "podman ps -a"                      "List all Podman containers"
  "podman run -it --rm "              "Run Podman interactively"
  "podman build -t "                  "Build Podman image"
  "docker-compose up -d"             "Start compose services"
  "docker-compose down"               "Stop compose services"
  "docker-compose logs -f "           "Follow compose logs"
  "docker-compose ps"                 "List compose services"
  "docker-compose pull"               "Pull latest images"
  "docker network ls"                 "List Docker networks"
  "docker volume ls"                  "List Docker volumes"
  "docker inspect "                   "Inspect container/image"
  "docker stats"                      "Live container stats"
  # ── Kubernetes (Extended) ─────────────────────────────────────────────────
  "kubectl get pods -n "              "List pods in namespace"
  "kubectl get all -n "               "Get all resources"
  "kubectl get svc -n "               "List services"
  "kubectl get nodes"                 "List cluster nodes"
  "kubectl logs -f "                  "Follow pod logs"
  "kubectl apply -f "                 "Apply manifest"
  "kubectl delete -f "                "Delete from manifest"
  "kubectl exec -it  -- bash"         "Shell into pod"
  "kubectl describe pod "             "Pod details"
  "kubectl scale deployment  --replicas=" "Scale deployment"
  "kubectl rollout restart deployment/" "Rolling restart"
  "kubectl rollout status deployment/"  "Check rollout"
  "kubectl port-forward  8080:80"     "Forward pod port"
  "kubectl top pods"                  "Pod resource usage"
  "kubectl top nodes"                 "Node resource usage"
  "kubectl config get-contexts"       "List kubeconfig contexts"
  "kubectl config use-context "       "Switch context"
  "helm install "                     "Install Helm chart"
  "helm upgrade  "                    "Upgrade Helm release"
  "helm list"                         "List Helm releases"
  "helm rollback "                    "Rollback Helm release"
  # ── Databases ─────────────────────────────────────────────────────────────
  "mysql -u root -p"                  "Connect to MySQL as root"
  "mysqldump -u root -p  > "          "Dump MySQL database"
  "psql -U postgres"                  "Connect to PostgreSQL"
  "pg_dump -U postgres  > "           "Dump PostgreSQL database"
  "redis-cli"                         "Connect to Redis CLI"
  "redis-cli PING"                    "Test Redis connection"
  "mongo"                             "Connect to MongoDB"
  "mongodump --db  --out "            "Dump MongoDB database"
  "sqlite3 "                          "Open SQLite database"
  # ── Media / FFmpeg ────────────────────────────────────────────────────────
  "ffmpeg -i  -c:v libx264 "          "Convert video to H.264"
  "ffmpeg -i  -vn -acodec mp3 "       "Extract audio as MP3"
  "ffmpeg -i  -ss 00:01:00 -t 60 "   "Trim video 60 seconds"
  "ffmpeg -i  -vf scale=1280:720 "    "Resize video to 720p"
  # ── Terraform / IaC ───────────────────────────────────────────────────────
  "terraform init"                    "Initialize Terraform"
  "terraform plan"                    "Preview changes"
  "terraform apply"                   "Apply changes"
  "terraform destroy"                 "Destroy infrastructure"
  "terraform fmt"                     "Format Terraform code"
  "ansible-playbook -i inventory "    "Run Ansible playbook"
  "ansible -m ping all"               "Ping all Ansible hosts"
  # ── Python & Env ──────────────────────────────────────────────────────────
  "python3 -m venv .venv"             "Create virtual env"
  "python3 -m pytest"                 "Run pytest"
  "python3 -m pip install "           "Install package"
  "python3 -m http.server 8080"       "Local HTTP server"
  "python3 -m json.tool"              "Pretty print JSON"
  "python3 -m cProfile -o  "          "Profile Python script"
  "poetry install"                    "Install via Poetry"
  "poetry add "                       "Add Poetry dependency"
  "poetry run "                       "Run in Poetry env"
  "pipenv install"                    "Install via Pipenv"
  "pipenv shell"                      "Activate Pipenv shell"
  "uvicorn  --reload"                 "Start FastAPI dev server"
  "gunicorn -w 4 -b 0.0.0.0:8000 "   "Start production server"
  "celery -A  worker -l info"         "Start Celery worker"
  "black "                            "Format Python with Black"
  "ruff check "                       "Lint with Ruff"
  "mypy "                             "Type check with mypy"
  "isort "                            "Sort Python imports"
  # ── Go (Extended) ─────────────────────────────────────────────────────────
  "go build ./..."                    "Build Go project"
  "go test ./..."                     "Run Go tests"
  "go test -race ./..."               "Test with race detector"
  "go mod tidy"                       "Clean dependencies"
  "go mod download"                   "Download dependencies"
  "go vet ./..."                      "Go static analysis"
  "go run "                           "Run Go file"
  "golangci-lint run"                 "Run Go linters"
  # ── Rust (Extended) ───────────────────────────────────────────────────────
  "cargo build --release"             "Build optimized binary"
  "cargo test"                        "Run tests"
  "cargo clippy -- -D warnings"       "Lint as errors"
  "cargo fmt"                         "Format Rust code"
  "cargo add "                        "Add dependency"
  "cargo update"                      "Update dependencies"
  "cargo run -- "                     "Run with args"
  # ── Node / Bun ────────────────────────────────────────────────────────────
  "npm run dev"                       "Start dev server"
  "npm install "                      "Install package"
  "npm run build"                     "Build production"
  "npm test"                          "Run tests"
  "npm init -y"                       "Initialize package"
  "npm audit fix"                     "Fix vulnerabilities"
  "npm outdated"                      "Show outdated packages"
  "npx "                              "Run npm package"
  "yarn add "                         "Add package"
  "yarn dev"                          "Start dev server"
  "yarn build"                        "Build production"
  "bun install"                       "Install via Bun"
  "bun run dev"                       "Start dev with Bun"
  "bun add "                          "Add Bun dependency"
  # ── AWS CLI ───────────────────────────────────────────────────────────────
  "aws s3 ls"                         "List S3 buckets"
  "aws s3 cp "                        "Copy file to/from S3"
  "aws s3 sync "                      "Sync directory to S3"
  "aws ec2 describe-instances"        "List EC2 instances"
  "aws logs tail  --follow"          "Tail CloudWatch logs"
  "aws sts get-caller-identity"       "Show current IAM identity"
  # ── GCP / gcloud ──────────────────────────────────────────────────────────
  "gcloud compute instances list"     "List GCP instances"
  "gcloud container clusters get-credentials" "Get GKE credentials"
  "gsutil ls "                        "List GCS bucket"
  "gsutil cp "                        "Copy to/from GCS"
  # ── Git (Extended) ────────────────────────────────────────────────────────
  "git commit -m \"\""                "Commit with message"
  "git commit --amend --no-edit"      "Amend last commit"
  "git push origin"                   "Push to remote"
  "git push --force-with-lease"       "Safe force push"
  "git pull --rebase"                 "Fetch and rebase"
  "git status"                        "Working tree status"
  "git log --oneline --graph"         "Visual commit history"
  "git log --author= --oneline"       "Commits by author"
  "git checkout -b "                  "Create new branch"
  "git diff --staged"                 "Show staged changes"
  "git stash push -m \"\""            "Stash with label"
  "git stash pop"                     "Apply last stash"
  "git stash list"                    "List stashes"
  "git fetch --all"                   "Fetch all remotes"
  "git rebase -i HEAD~3"              "Interactive rebase"
  "git reset --hard HEAD"             "Discard all changes"
  "git reset --soft HEAD~1"           "Undo last commit keep changes"
  "git clone "                        "Clone repository"
  "git add ."                         "Stage all changes"
  "git branch -d "                    "Delete branch"
  "git cherry-pick "                  "Apply commit"
  "git bisect start"                  "Start binary search"
  "git tag -a v "                     "Create annotated tag"
  "git submodule update --init"       "Init submodules"
  "git worktree add "                 "Create linked worktree"
  # ── Misc / Utility ────────────────────────────────────────────────────────
  "echo "                             "Print to stdout"
  "echo \$PATH"                       "Show PATH"
  "export PATH=\$PATH:"              "Add to PATH"
  "history | grep "                   "Search history"
  "man "                              "Show manual"
  "date"                              "Show date/time"
  "date +%Y-%m-%d"                    "Date in ISO format"
  "whoami"                            "Current user"
  "env"                               "Show env vars"
  "printenv "                         "Print env variable"
  "tmux new -s "                      "Create tmux session"
  "tmux attach -t "                   "Attach tmux session"
  "tmux ls"                           "List tmux sessions"
  "screen -S "                        "Create screen session"
  "crontab -l"                        "List cron jobs"
  "crontab -e"                        "Edit cron jobs"
  "watch -n 1 "                       "Run every second"
  "xargs "                            "Build and execute commands"
  "tee "                              "Write stdout and file"
  "time "                             "Time a command"
  "timeout 30 "                       "Run with 30s timeout"
  "yes | "                            "Auto-confirm prompts"
  "tr -d '\\n' "                     "Remove newlines"
  "column -t"                         "Align columns"
  "jq . "                             "Pretty print JSON"
  "jq '.[] | .' "                     "Iterate JSON array"
  "yq . "                             "Parse YAML"
  "base64 -d "                        "Decode base64"
  "base64 "                           "Encode to base64"
  # ── Intent Engine ─────────────────────────────────────────────────────────
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
