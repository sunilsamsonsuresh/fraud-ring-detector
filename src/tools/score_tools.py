"""The scoring tool: the score of ONE claim, with the proof of every rule that fired. No LLM is called here.

This file joins three parts we already have:
  facts.py reads the claim from the graph -> engine.py scores the facts -> this file shapes the answer.

The tool only reads. It saves nothing. See the note at the bottom for why.
It returns the same two shapes as the other tools: {"facts", "notes", "sources"} or {"message"}.
"""

import json

from src.scoring.engine import score_facts
from src.scoring.facts import read_claim_facts
from src.scoring.rules_catalog import RULES


def make_json_safe(value):
    """Python dates become text like "2024-12-16", so the answer can be sent as JSON.

    json.dumps(default=str) writes any value it does not know as text. json.loads reads it back
    as plain dicts, lists and text."""
    return json.loads(json.dumps(value, default=str))


def get_claim_score(driver, claim_id):
    """The score, band and coverage of one claim, and for each fired rule its points and proof."""
    facts = read_claim_facts(driver, claim_id)
    if facts is None:
        return {"message": f"Claim {claim_id} was not found in the graph."}
    result = score_facts(facts)

    # For a rule that could not run, the person needs WHAT the rule checks and WHAT was missing.
    rule_by_id = {rule.rule_id: rule for rule in RULES}
    not_evaluated_rule_ids = []
    not_evaluated_rules = []
    for rule_id, rule_result in result["rule_results"].items():
        if rule_result["status"] == "not_evaluated":
            rule = rule_by_id[rule_id]
            not_evaluated_rule_ids.append(rule_id)
            not_evaluated_rules.append(
                {
                    "rule_id": rule_id,
                    "name": rule.name,
                    "points": rule.points,
                    "fires_when": rule.description,
                    "missing": rule_result["proof"]["missing"],
                }
            )
    fired_rules = make_json_safe(result["fired_rules"])
    for fired_rule in fired_rules:
        fired_rule["fires_when"] = rule_by_id[fired_rule["rule_id"]].description

    score = {
        "claim_id": claim_id,
        "total_score": result["total_score"],
        "band": result["band"],
        "action": result["action"],
        "category_scores": result["category_scores"],
        "coverage_pct": result["coverage_pct"],
        "fired_rules": fired_rules,
        "not_evaluated_rule_ids": not_evaluated_rule_ids,
        "not_evaluated_rules": not_evaluated_rules,
    }
    notes = [
        (
            f"Coverage is {result['coverage_pct']}%. A rule that could not run counts as not fired, "
            f"so a low coverage means the score may be too low."
        ),
        "The score is a pointer for a human reviewer. It is not a finding of fraud.",
    ]
    sources = [
        f"Scoring rules applied to the graph facts of {claim_id} (dates, visits, direct links)"
    ]
    return {"facts": score, "notes": notes, "sources": sources}


# Why this tool saves nothing: a chat tool only reads. The pipeline saves the scores of all claims
# (src/data_loading/save_scores_into_graph.py, step 4 of `python main.py build-graph`).
