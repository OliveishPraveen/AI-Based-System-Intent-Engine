"""
Rule Engine Package — Owner: Praveen (OliveishPraveen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is Praveen's primary domain. Architecture mirrors his Ai_Email_Classifier:
  - Pattern library (analogous to rule-based filter layer)
  - ML/heuristic classifier (analogous to DistilBERT model)
  - FastAPI verdict serving (same backend pattern he already uses)

Modules:
  - classifier.py       : Main entry — orchestrates pattern matching
  - pattern_matcher.py  : Regex + structural pattern matching engine
  - verdict.py          : Verdict assembly and confidence scoring
  - pattern_loader.py   : Loads + validates dangerous_patterns.toml
"""
