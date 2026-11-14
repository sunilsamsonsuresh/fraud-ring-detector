"""The two ways a rule check can answer. Every rule file and the engine use these.

A rule result is a dict: {"status": "fired" | "not_fired" | "not_evaluated", "proof": {...}}.
"not_evaluated" means a needed fact is missing. The rule then counts as not fired,
and the engine does not count its points as examined (coverage).
"""


def fired_or_not(is_fired, proof):
    return {"status": "fired" if is_fired else "not_fired", "proof": proof}


def not_evaluated(reason):
    return {"status": "not_evaluated", "proof": {"missing": reason}}
