"""
Rule Engine CLI Runner — Owner: Praveen (OliveishPraveen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Direct terminal runner for executing the Rule Engine on shell commands.
Outputs structured Verdict data (JSON or plain text) to stdout, serving as the
direct input payload for downstream routing and the LLM Reasoning Engine.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from engine.models import CommandContext, Verdict
from engine.parser.command_parser import CommandParser
from engine.rule_engine.classifier import RuleEngineClassifier

parser = CommandParser()


async def evaluate_command(
    command_str: str,
    classifier: RuleEngineClassifier,
    cwd: str = "/home/user",
    user: str = "testuser",
) -> tuple[Verdict, float]:
    """Parse and classify a single command string."""
    ctx = CommandContext(
        command=command_str,
        cwd=cwd,
        user=user,
        is_sudo=command_str.strip().startswith("sudo"),
        shell="bash",
        session_id="cli-session",
    )
    parsed = parser.parse(command_str, cwd=cwd, user=user)

    t0 = time.perf_counter()
    verdict = await classifier.classify(parsed, ctx)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return verdict, elapsed_ms


async def run_single(command: str, as_json: bool = True) -> None:
    """Evaluate a single command and output the raw Verdict to terminal."""
    classifier = RuleEngineClassifier()
    await classifier.load_patterns()

    verdict, elapsed = await evaluate_command(command, classifier)

    if as_json:
        # Dump exact Verdict model JSON for LLM engine ingestion
        sys.stdout.write(json.dumps(verdict.model_dump(), indent=2) + "\n")
    else:
        sys.stdout.write(f"Command:        {command}\n")
        sys.stdout.write(f"Risk Level:     {verdict.risk_level.value}\n")
        sys.stdout.write(f"Confidence:     {verdict.confidence:.2f}\n")
        sys.stdout.write(f"Matched Rule:   {verdict.matched_pattern or 'None'}\n")
        sys.stdout.write(f"Tier Used:      {verdict.tier_used}\n")
        sys.stdout.write(f"Latency (ms):   {verdict.latency_ms:.2f}\n")
        sys.stdout.write(f"Impact Summary: {verdict.impact_summary}\n")
        sys.stdout.write(f"Reasoning:      {verdict.reasoning}\n")
        if verdict.safer_alternative:
            sys.stdout.write(f"Safer Alt:      {verdict.safer_alternative}\n")
            if verdict.safer_alternative_explanation:
                sys.stdout.write(f"Safer Reason:   {verdict.safer_alternative_explanation}\n")


async def run_corpus(file_path: Path, expected_type: str = "dangerous") -> None:
    """Evaluate fixture corpus line-by-line and print output directly."""
    if not file_path.exists():
        sys.stderr.write(f"Corpus file not found: {file_path}\n")
        return

    classifier = RuleEngineClassifier()
    await classifier.load_patterns()

    commands = [
        line.strip()
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    sys.stdout.write(f"--- Evaluating {file_path.name} ({len(commands)} commands) ---\n")
    pass_count = 0
    total_time_ms = 0.0

    for idx, cmd in enumerate(commands, 1):
        verdict, elapsed = await evaluate_command(cmd, classifier)
        total_time_ms += elapsed

        if expected_type == "dangerous":
            is_pass = verdict.risk_level.value in ("MEDIUM", "HIGH", "CRITICAL")
        else:
            is_pass = verdict.risk_level.value in ("SAFE", "LOW")

        if is_pass:
            pass_count += 1

        sys.stdout.write(
            f"[{idx:02d}] {verdict.risk_level.value:<8} | conf={verdict.confidence:.2f} | "
            f"rule={verdict.matched_pattern or 'None':<20} | {elapsed:.2f}ms | {cmd}\n"
        )

    avg_ms = total_time_ms / len(commands) if commands else 0.0
    sys.stdout.write(f"\nResult: {pass_count}/{len(commands)} passed | Avg Latency: {avg_ms:.2f} ms | Total: {total_time_ms:.1f} ms\n\n")


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]
    root_dir = Path(__file__).resolve().parent.parent.parent

    if not args or args[0] in ("-h", "--help"):
        sys.stdout.write("Usage:\n")
        sys.stdout.write("  python -m engine.rule_engine.visualizer '<command>' [--text]\n")
        sys.stdout.write("  python -m engine.rule_engine.visualizer --dangerous\n")
        sys.stdout.write("  python -m engine.rule_engine.visualizer --safe\n")
        sys.stdout.write("  python -m engine.rule_engine.visualizer --all\n")
        return

    if args[0] == "--dangerous":
        fixture = root_dir / "tests" / "fixtures" / "dangerous_commands.txt"
        asyncio.run(run_corpus(fixture, "dangerous"))
    elif args[0] == "--safe":
        fixture = root_dir / "tests" / "fixtures" / "safe_commands.txt"
        asyncio.run(run_corpus(fixture, "safe"))
    elif args[0] == "--all":
        fixture_d = root_dir / "tests" / "fixtures" / "dangerous_commands.txt"
        fixture_s = root_dir / "tests" / "fixtures" / "safe_commands.txt"
        asyncio.run(run_corpus(fixture_d, "dangerous"))
        asyncio.run(run_corpus(fixture_s, "safe"))
    else:
        as_json = "--text" not in args
        cmd_args = [a for a in args if a != "--text"]
        command = " ".join(cmd_args)
        asyncio.run(run_single(command, as_json=as_json))


if __name__ == "__main__":
    main()
