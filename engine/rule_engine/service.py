"""
Standalone Rule Engine Service — Owner: Praveen (OliveishPraveen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FastAPI microservice serving standalone Rule Engine verdicts, pattern library
introspection, and runtime rule reload endpoints.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from engine.models import CommandContext, Verdict
from engine.parser.command_parser import CommandParser
from engine.rule_engine.classifier import RuleEngineClassifier
from engine.rule_engine.pattern_loader import PatternLoader

# Module-level instances
classifier = RuleEngineClassifier()
parser = CommandParser()
loader = PatternLoader()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Load patterns on service startup."""
    await classifier.load_patterns()
    yield


app = FastAPI(
    title="Intent Engine — Rule Classifier Microservice",
    description="Tier 0/1 deterministic and context-weighted rule classification API.",
    version="1.0.0",
    lifespan=lifespan,
)


class ClassifyRequest(BaseModel):
    """Request payload for standalone classification."""
    command: str = Field(..., description="Raw shell command string")
    cwd: str = Field("/home/user", description="Working directory")
    user: str = Field("user", description="Executing username")
    is_sudo: bool = Field(False, description="Whether command uses sudo")
    shell: str = Field("bash", description="Shell type")
    session_id: str = Field("standalone-session", description="Session identifier")


class ReloadResponse(BaseModel):
    """Response returned after hot-reloading rules."""
    status: str
    patterns_count: int


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check returning service status and active pattern count."""
    count = len(classifier._matcher._patterns) if classifier._matcher else 0
    return {
        "status": "ok",
        "service": "rule_engine",
        "patterns_loaded": count,
    }


@app.post("/classify", response_model=Verdict)
async def classify_command(req: ClassifyRequest) -> Verdict:
    """Analyze a raw command string and return the Rule Engine verdict."""
    try:
        ctx = CommandContext(
            command=req.command,
            cwd=req.cwd,
            user=req.user,
            is_sudo=req.is_sudo or req.command.strip().startswith("sudo"),
            shell=req.shell,
            session_id=req.session_id,
        )
        parsed = parser.parse(req.command, cwd=req.cwd, user=req.user)
        return await classifier.classify(parsed, ctx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Classification error: {str(e)}") from e


@app.get("/rules")
async def list_rules() -> dict[str, Any]:
    """Introspect and list all loaded rule definitions and risk breakdown."""
    patterns = await loader.load()
    tier0_count = sum(1 for p in patterns if p.get("tier") == 0)
    tier1_count = sum(1 for p in patterns if p.get("tier") == 1)

    by_risk: dict[str, int] = {}
    for p in patterns:
        lvl = p.get("risk_level", "UNKNOWN")
        by_risk[lvl] = by_risk.get(lvl, 0) + 1

    return {
        "total_patterns": len(patterns),
        "tier0_count": tier0_count,
        "tier1_count": tier1_count,
        "by_risk_level": by_risk,
        "patterns": [
            {
                "name": p.get("name"),
                "tier": p.get("tier"),
                "risk_level": p.get("risk_level"),
                "category": p.get("category"),
                "commands": p.get("commands"),
            }
            for p in patterns
        ],
    }


@app.post("/reload", response_model=ReloadResponse)
async def reload_rules() -> ReloadResponse:
    """Hot-reload rules directly from rules/dangerous_patterns.toml."""
    count = classifier.reload_patterns()
    return ReloadResponse(status="reloaded", patterns_count=count)
