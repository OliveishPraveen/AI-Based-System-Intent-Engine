import json

from engine.llm.ollama_client import OllamaClient
from engine.llm.schemas import LLMIntentResponse


client = OllamaClient()

prompt = """
Analyze this Linux command:

find . -type f -delete

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

Do not include markdown.
Do not include any text outside the JSON object.
"""

response = client.generate(prompt)

print("\nRaw LLM response:")
print(response)

data = json.loads(response)

result = LLMIntentResponse.model_validate(data)

print("\nValidated result:")
print(result)

print("\nValidated dictionary:")
print(result.model_dump())