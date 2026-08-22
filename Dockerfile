# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine — Sandbox Container
# ═══════════════════════════════════════════════════════════════════════════════
#
# Provides a fully-isolated Fedora environment for testing dangerous commands
# against the intent engine hook safely.
#
# Build:   podman build -t intent-sandbox .
# Run:     podman run -it --rm intent-sandbox
# ═══════════════════════════════════════════════════════════════════════════════

FROM fedora:40

# ─── System deps ─────────────────────────────────────────────────────────────
RUN dnf install -y \
        python3 \
        python3-pip \
        curl \
        bash \
        procps-ng \
        findutils \
        util-linux \
        coreutils \
        && dnf clean all

# ─── Working directory ───────────────────────────────────────────────────────
WORKDIR /opt/intent-engine

# ─── Copy project ────────────────────────────────────────────────────────────
COPY . .

# ─── Install Python package ──────────────────────────────────────────────────
RUN pip3 install -e ".[dev]" --quiet

# ─── Environment ────────────────────────────────────────────────────────────
ENV PYTHONPATH=/opt/intent-engine
ENV INTENT_SOCKET=/tmp/intent_engine.sock
ENV INTENT_ENGINE_ENABLED=1

# ─── Entrypoint ──────────────────────────────────────────────────────────────
CMD ["/opt/intent-engine/scripts/sandbox_test.sh"]
