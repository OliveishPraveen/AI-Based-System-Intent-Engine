"""
Daemon package — Harshit's domain.

Contains:
  - server.py    : FastAPI app + Uvicorn runner + Unix socket setup
  - router.py    : Tier routing logic (rule engine → LLM escalation)
  - session.py   : Per-session state and allowlist management
  - health.py    : Health check and daemon lifecycle endpoints
"""
