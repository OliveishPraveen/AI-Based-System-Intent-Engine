"""
LLM Package
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is Vansh's primary domain. Architecture mirrors NEXUS-AI's:
  - Multi-provider LLM client (Ollama / Gemini / OpenAI)
  - Structured prompt builder (analogous to NEXUS-AI's planner)
  - Reflection + validation layer (analogous to NEXUS-AI's reflection phase)
  - Safer-alternative suggester (analogous to NEXUS-AI's tool selection)
  - Human-in-loop approval design (analogous to NEXUS-AI's HITL step)

Modules:
  - client.py          : Abstract LLM client + provider factory
  - providers/         : Ollama, Gemini, OpenAI adapters
  - prompt_builder.py  : Structured prompt assembly from ParsedCommand + context
  - reasoner.py        : Core reasoning + reflection loop
  - suggester.py       : Safer alternative command suggestion
  - response_parser.py : Parse + validate LLM JSON response
"""
