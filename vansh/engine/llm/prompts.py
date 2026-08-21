from engine.contracts.rule_result import RuleResult


SYSTEM_PROMPT = """
You are a Linux command safety analyzer.

Your job is to understand the user's intent and assess the potential
impact of a Linux command.

You are an analyzer, NOT an executor.

Never execute commands.
Never modify commands automatically.
Never assume an operation is safe when important information is missing.

Analyze:

1. The user's likely intent.
2. The potential impact.
3. The affected resources.
4. Whether the operation is reversible.
5. The risk level.
6. Whether user confirmation should be required.
7. A clear explanation in plain language.

Risk levels:

SAFE
LOW
MEDIUM
HIGH
CRITICAL

Return ONLY valid JSON.

Use exactly these fields:

{
  "risk_level": "SAFE | LOW | MEDIUM | HIGH | CRITICAL",
  "confidence": 0.0,
  "intent": "string",
  "impact": "string",
  "affected_resources": ["string"],
  "reversible": true,
  "requires_confirmation": true,
  "explanation": "string"
}

Do not return Markdown.
Do not return text outside the JSON object.
"""


def build_intent_prompt(rule_result: RuleResult) -> str:
    """
    Build the reasoning prompt dynamically from the Rule Engine result.
    """

    context = rule_result.context

    shell = context.get("shell", "unknown")
    cwd = context.get("cwd", "unknown")

    matched_rules = (
        ", ".join(rule_result.matched_rules)
        if rule_result.matched_rules
        else "None"
    )

    return f"""
{SYSTEM_PROMPT}

Analyze the following Linux command.

COMMAND:
{rule_result.command}

RULE ENGINE CLASSIFICATION:
{rule_result.classification.value}

RULE ENGINE CONFIDENCE:
{rule_result.confidence}

MATCHED RULES:
{matched_rules}

SHELL:
{shell}

CURRENT WORKING DIRECTORY:
{cwd}

Remember:
- The Rule Engine has already performed deterministic analysis.
- You are handling semantic/ambiguous reasoning.
- Do not execute the command.
- Return ONLY the requested JSON object.
"""