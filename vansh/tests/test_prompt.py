from engine.contracts.rule_result import RuleResult, RuleClassification
from engine.llm.prompts import build_intent_prompt


rule_result = RuleResult(
    command="find . -type f -delete",
    classification=RuleClassification.AMBIGUOUS,
    confidence=0.42,
    matched_rules=[],
    context={
        "shell": "bash",
        "cwd": "/home/vansh/project"
    }
)

prompt = build_intent_prompt(rule_result)

print(prompt)