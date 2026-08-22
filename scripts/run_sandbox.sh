#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Sandbox Runner
# Usage:  ./scripts/run_sandbox.sh
#
# Builds a Fedora container with the engine installed and runs the full
# test suite inside it. Dangerous commands run inside the container only —
# zero risk to your host system.
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="intent-engine-sandbox"
TAG="latest"

B="\033[1m"
G="\033[38;5;108m"
Y="\033[38;5;222m"
RST="\033[0m"
DIM="\033[2m"

# Use podman if available, fallback to docker
if command -v podman &>/dev/null; then
    RUNTIME="podman"
elif command -v docker &>/dev/null; then
    RUNTIME="docker"
else
    echo "Error: neither podman nor docker found. Install one first."
    echo "  Fedora: sudo dnf install podman"
    exit 1
fi

echo ""
echo -e "${B}  Intent Engine — Sandbox Test Runner${RST}"
echo -e "  ${DIM}Runtime: $RUNTIME${RST}"
echo ""

# ─── Build ───────────────────────────────────────────────────────────────────
echo -e "  ${Y}Building container image...${RST}"
"$RUNTIME" build \
    --tag "${IMAGE}:${TAG}" \
    --file "$REPO_DIR/Dockerfile" \
    "$REPO_DIR" \
    --quiet

echo -e "  ${G}Image built: ${IMAGE}:${TAG}${RST}"
echo ""

# ─── Run ─────────────────────────────────────────────────────────────────────
echo -e "  ${Y}Running sandbox tests...${RST}"
echo -e "  ${DIM}(dangerous commands run INSIDE container — host is safe)${RST}"
echo ""

"$RUNTIME" run \
    --rm \
    --name intent-sandbox-run \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    "${IMAGE}:${TAG}" \
    bash /opt/intent-engine/scripts/sandbox_test.sh

EXIT_CODE=$?

echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
    echo -e "  ${G}${B}Sandbox tests PASSED.${RST}"
else
    echo -e "  \033[38;5;174m${B}Sandbox tests FAILED (exit $EXIT_CODE).${RST}"
fi
echo ""
exit $EXIT_CODE
