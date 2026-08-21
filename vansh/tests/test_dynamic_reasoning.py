import json

from engine.contracts.rule_result import RuleResult, RuleClassification
from engine.llm.ollama_client import OllamaClient
from engine.llm.prompts import build_intent_prompt
from engine.llm.schemas import LLMIntentResponse


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

client = OllamaClient()

response = client.generate(prompt)

print("\nRAW RESPONSE:")
print(response)

data = json.loads(response)

result = LLMIntentResponse.model_validate(data)

print("\nVALIDATED RESULT:")
print(result)

print("\nRESULT DICTIONARY:")
print(result.model_dump())