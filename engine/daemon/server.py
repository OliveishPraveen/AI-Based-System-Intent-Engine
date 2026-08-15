"""
Daemon Server — Owner: Harshit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Responsibilities:
  - Start a warm FastAPI/Uvicorn process at shell login
  - Listen on a Unix domain socket (faster than TCP loopback)
  - Route incoming AnalyzeRequests to the correct tier
  - Return AnalyzeResponse to the shell hook
  - Write structured audit logs for every flagged command
  - Expose /health, /status, /reload-rules endpoints
  - Manage PID file and graceful shutdown

Usage:
  python -m engine.daemon.server   (started by install.sh at shell login)
"""

from __future__ import annotations

import os
import signal
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from engine.config import get_config
from engine.daemon.router import IntentRouter
from engine.models import AnalyzeRequest, AnalyzeResponse, Verdict, RiskLevel

log = structlog.get_logger()

# ─── Runtime paths ────────────────────────────────────────────────────────────
SOCKET_PATH = Path(os.environ.get("INTENT_SOCKET", "/tmp/intent_engine.sock"))
PID_FILE    = Path(os.environ.get("INTENT_PID",    "/tmp/intent_engine.pid"))
LOG_DIR     = Path.home() / ".intent_engine" / "logs"
LOG_FILE    = LOG_DIR / "daemon.log"


def _configure_logging() -> None:
    """Route all structlog output to a log file, keeping the terminal clean."""
    import logging
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # File handler — all daemon logs go here, not to the terminal
    file_handler = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    logging.basicConfig(
        handlers=[file_handler],
        level=logging.DEBUG,
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()

# ─── Lifespan ─────────────────────────────────────────────────────────────────
_router: IntentRouter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle for the daemon."""
    global _router
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    cfg = get_config()
    _router = IntentRouter(cfg)
    await _router.initialize()
    log.info("intent_engine_started", socket=str(SOCKET_PATH), pid=os.getpid())
    yield
    # Shutdown
    PID_FILE.unlink(missing_ok=True)
    log.info("intent_engine_stopped")


# ─── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Intent Engine Daemon",
    description="AI-Based System Intent Engine for Safe Linux Command Execution",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Primary endpoint called by the shell hook.

    Flow:
      1. Parse the command
      2. Route to rule engine (Tier 0/1, Praveen)
      3. If AMBIGUOUS, escalate to LLM tier (Tier 2, Vansh)
      4. Return unified AnalyzeResponse
    """
    if _router is None:
        raise HTTPException(status_code=503, detail="Router not initialized")

    start = time.perf_counter()
    response = await _router.route(request)
    elapsed = (time.perf_counter() - start) * 1000

    log.info(
        "command_analyzed",
        command=request.context.command[:80],
        risk=response.verdict.risk_level,
        tier=response.verdict.tier_used,
        latency_ms=round(elapsed, 2),
        blocked=response.should_block,
    )
    return response


@app.get("/health")
async def health() -> dict:
    """Liveness check — shell hook pings this at startup to confirm daemon is ready."""
    return {"status": "ok", "pid": os.getpid(), "version": "0.1.0"}


@app.post("/reload-rules")
async def reload_rules() -> dict:
    """Hot-reload the dangerous pattern library without restarting the daemon."""
    if _router is None:
        raise HTTPException(status_code=503, detail="Router not initialized")
    await _router.reload_rules()
    return {"status": "rules_reloaded"}


@app.get("/stats")
async def stats() -> dict:
    """Return session stats: total commands, flagged counts by risk level."""
    if _router is None:
        return {}
    return _router.get_stats()


# ─── Entry point ──────────────────────────────────────────────────────────────
def run() -> None:
    """Start the daemon. Called by the shell hook installer and CLI."""
    config = uvicorn.Config(
        app=app,
        uds=str(SOCKET_PATH),   # Unix domain socket — faster than TCP loopback
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _handle_sigterm(sig: int, frame: object) -> None:
        log.info("sigterm_received")
        server.should_exit = True

    signal.signal(signal.SIGTERM, _handle_sigterm)
    server.run()


if __name__ == "__main__":
    run()
