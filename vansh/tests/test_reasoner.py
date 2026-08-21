from engine.contracts.rule_result import RuleResult, RuleClassification
from engine.llm.ollama_client import OllamaClient
from engine.llm.reasoner import IntentReasoner


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

client = OllamaClient()

reasoner = IntentReasoner(client)

result = reasoner.analyze(rule_result)

print("\nFINAL INTENT RESULT:")
print(result)

print("\nFINAL DICTIONARY:")
print(result.model_dump())