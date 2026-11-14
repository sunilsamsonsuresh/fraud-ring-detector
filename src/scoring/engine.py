"""The scoring engine: rules -> category scores -> total score -> band.

Formulas:
1. Category score = points of the fired rules in the category / all points of the category x 100.
2. Total score = sum of (category weight x category score). From 0 to 100.
3. A rule with a missing fact is "not evaluated". It counts as not fired.
4. Coverage = points of the evaluated rules / all points x 100. A low coverage means
   "not fully examined": the score is only as good as the rules that could run.
5. Band = the first row of config.BANDS whose minimum the total score reaches.

Plain code only. The same facts always give the same score (CLAUDE.md, rule 18).
The engine does not read the graph and does not save anything. It works on a facts dict.
"""

from src import config
from src.scoring.rule_results import not_evaluated
from src.scoring.rules_catalog import CATEGORY_NAMES, RULES, points_by_category
from src.scoring.rules_dates import DATE_RULE_CHECKS
from src.scoring.rules_documents import DOCUMENT_RULE_CHECKS
from src.scoring.rules_findings import FINDING_RULE_CHECKS
from src.scoring.rules_money import MONEY_RULE_CHECKS
from src.scoring.rules_network import NETWORK_RULE_CHECKS
from src.scoring.rules_tables import TABLE_RULE_CHECKS

# Rule ID -> its check. Each new group of rules adds its dict here.
RULE_CHECKS = {
    **TABLE_RULE_CHECKS,
    **DATE_RULE_CHECKS,
    **MONEY_RULE_CHECKS,
    **NETWORK_RULE_CHECKS,
    **DOCUMENT_RULE_CHECKS,
    **FINDING_RULE_CHECKS,
}


def run_rules(facts):
    """{rule ID: rule result} for every rule of the catalog, in catalog order."""
    results = {}
    for rule in RULES:
        check = RULE_CHECKS.get(rule.rule_id)
        if check is None:
            results[rule.rule_id] = not_evaluated(
                "no check is written for this rule yet"
            )
        else:
            results[rule.rule_id] = check(facts)
    return results


def band_for(total_score):
    """(band name, action) for a total score."""
    for minimum, band, action in config.BANDS:
        if total_score >= minimum:
            return band, action
    return config.BANDS[-1][1], config.BANDS[-1][2]


def score_rule_results(rule_results):
    """Turn the rule results into the score. Return a dict (the keys are at the end)."""
    points_in_category = points_by_category()
    earned_points = {category: 0 for category in CATEGORY_NAMES}
    evaluated_points = 0
    fired_rules = []
    for rule in RULES:
        result = rule_results[rule.rule_id]
        if result["status"] != "not_evaluated":
            evaluated_points += rule.points
        if result["status"] == "fired":
            earned_points[rule.category] += rule.points
            # How much this one rule adds to the total score: weight x points / category points x 100.
            share = (
                config.CATEGORY_WEIGHTS[rule.category]
                * rule.points
                / points_in_category[rule.category]
                * 100
            )
            fired_rules.append(
                {
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "category": rule.category,
                    "points": rule.points,
                    "points_in_total": round(share, 2),
                    "proof": result["proof"],
                }
            )

    category_scores = {}
    total = 0.0
    for category in CATEGORY_NAMES:
        category_score = earned_points[category] / points_in_category[category] * 100
        category_scores[category] = round(category_score, 1)
        total += config.CATEGORY_WEIGHTS[category] * category_score
    total_score = round(total, 1)
    band, action = band_for(total_score)
    return {
        "total_score": total_score,
        "band": band,
        "action": action,
        "category_scores": category_scores,
        "coverage_pct": round(
            evaluated_points / sum(points_in_category.values()) * 100, 1
        ),
        "fired_rules": fired_rules,
        "rule_results": rule_results,
    }


def score_facts(facts):
    """Score one claim from its facts dict (src/scoring/facts.py)."""
    result = score_rule_results(run_rules(facts))
    result["claim_id"] = facts["claim_id"]
    return result


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.scoring.engine      (needs no Neo4j)
if __name__ == "__main__":
    import datetime

    loss_date = datetime.date(2024, 12, 15)
    # Made-up facts: the same shape that read_claim_facts() returns.
    sample_facts = {
        "claim_id": "C-TEST",
        "loss_date": loss_date,
        "attorney_retained_date": loss_date
        + datetime.timedelta(days=1),  # attorney on day 1 ...
        "visit_dates": [
            loss_date
            + datetime.timedelta(days=5 + number % 20)  # ... first visit on day 5
            for number in range(14)
        ],  # 14 visits in 30 days
        "direct_links": [
            {
                "linked_claim_id": f"C-90{number}",
                "kind": "clinic_and_attorney",
                "shared_value": "Clinic A + Attorney B",
            }
            for number in range(5)
        ],
    }

    # Step 1: run_rules -> one result per rule (32). Put a break point here to look at them.
    rule_results = run_rules(sample_facts)
    print("1. run_rules: results that are not 'not_evaluated':")
    for rule_id, result in rule_results.items():
        if result["status"] != "not_evaluated":
            print("  ", rule_id, result["status"], result["proof"])

    # Step 2: band_for -> the band for a total score.
    print("2. band_for(25):", band_for(25))

    # Step 3: score_rule_results -> the score from the rule results.
    scored = score_rule_results(rule_results)
    print(
        "3. score_rule_results: total",
        scored["total_score"],
        "| band",
        scored["band"],
        "| coverage",
        scored["coverage_pct"],
        "| categories",
        scored["category_scores"],
    )
    for fired in scored["fired_rules"]:
        print(
            "   fired:",
            fired["rule_id"],
            "points",
            fired["points"],
            "adds",
            fired["points_in_total"],
        )

    # Step 4: score_facts -> steps 1 and 3 together, plus the claim ID. The other files call this one.
    final = score_facts(sample_facts)
    print(
        "4. score_facts: claim",
        final["claim_id"],
        "| total",
        final["total_score"],
        "| action",
        final["action"],
    )
