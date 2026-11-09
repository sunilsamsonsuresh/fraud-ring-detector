"""The scoring engine: rules -> category scores -> total score -> band (PLAN-v2.md A7, V7).

Formulas (A7):
1. Category score = points of fired rules in the category / enabled points of the category x 100.
2. Total score = sum of (category weight x category score). 0 to 100.
3. A rule with a missing input is "not evaluated": it counts as not fired.
4. Coverage = enabled points of the evaluated rules / all enabled points x 100.
5. Band: the first row of config.BANDS whose minimum the total score reaches.

Plain code only. Same facts give the same score (CLAUDE.md, rule 18).
"""

import json

from src import config
from src.graph import queries
from src.scoring.as_of import facts_as_of
from src.scoring.facts import read_raw_facts
from src.scoring.rules import RULE_CHECKS
from src.scoring.rules_catalog import CATEGORY_NAMES, RULES, enabled_points_by_category


def run_rules(facts):
    """{rule ID: {"status", "proof"}} for every enabled rule, in catalog order."""
    results = {}
    for rule in RULES:
        if rule.enabled:
            results[rule.rule_id] = RULE_CHECKS[rule.rule_id](facts)
    return results


def band_for(total_score):
    """(band name, action) for a total score."""
    for minimum, band, action in config.BANDS:
        if total_score >= minimum:
            return band, action
    return config.BANDS[-1][1], config.BANDS[-1][2]


def score_rule_results(rule_results):
    """Turn the rule results into the score. Return a dict (see the keys at the end)."""
    enabled_points = enabled_points_by_category()
    earned = {category: 0 for category in CATEGORY_NAMES}
    evaluated_points = 0
    fired_rules = []
    for rule in RULES:
        if not rule.enabled:
            continue
        status = rule_results[rule.rule_id]["status"]
        if status != "not_evaluated":
            evaluated_points += rule.points
        if status == "fired":
            earned[rule.category] += rule.points
            # The share of the total score this rule gives: weight x points / category points x 100.
            share = config.CATEGORY_WEIGHTS[rule.category] * rule.points / enabled_points[rule.category] * 100
            fired_rules.append({"rule_id": rule.rule_id, "name": rule.name, "category": rule.category,
                                "points": rule.points, "points_in_total": round(share, 2),
                                "proof": rule_results[rule.rule_id]["proof"]})

    category_scores = {}
    total = 0.0
    for category in CATEGORY_NAMES:
        category_score = earned[category] / enabled_points[category] * 100
        category_scores[category] = round(category_score, 1)
        total += config.CATEGORY_WEIGHTS[category] * category_score
    total_score = round(total, 1)
    band, action = band_for(total_score)
    return {
        "total_score": total_score,
        "band": band,
        "action": action,
        "category_scores": category_scores,
        "coverage_pct": round(evaluated_points / sum(enabled_points.values()) * 100, 1),
        "fired_rules": fired_rules,
        "rule_results": rule_results,
    }


def score_facts(facts):
    result = score_rule_results(run_rules(facts))
    result["claim_id"] = facts["claim_id"]
    result["weak_findings"] = facts["weak_findings"]
    return result


def save_snapshot(driver, result, as_of_date):
    scores = result["category_scores"]
    driver.execute_query(
        queries.SAVE_SCORE_SNAPSHOT, claim_id=result["claim_id"],
        snapshot_id=f"{result['claim_id']}-{as_of_date.isoformat()}", as_of_date=as_of_date.isoformat(),
        total_score=result["total_score"], band=result["band"],
        bi_score=scores["BI"], as_score=scores["AS"], bf_score=scores["BF"], ct_score=scores["CT"],
        nl_score=scores["NL"], coverage_pct=result["coverage_pct"],
        fired_rule_ids=[rule["rule_id"] for rule in result["fired_rules"]],
        # default=str writes dates as text ("2024-03-05"); sort_keys keeps the text the same on every run.
        fired_rules_json=json.dumps(result["fired_rules"], default=str, sort_keys=True))


def score_claim(driver, claim_id, as_of_date, save=True):
    """Score one claim with all its facts (the current score). Save a ScoreSnapshot dated
    as_of_date (the day of scoring). Return the result, or None."""
    raw = read_raw_facts(driver, claim_id)
    if raw is None:
        return None
    result = score_facts(facts_as_of(raw, None))
    if save:
        save_snapshot(driver, result, as_of_date)
    return result


def all_claim_ids(driver):
    records, _, _ = driver.execute_query(queries.ALL_CLAIM_IDS)
    return [record["claim_id"] for record in records]


def score_all_claims(driver, as_of_date):
    """Score every claim and save a snapshot for each. No LLM call. Return {claim ID: result}."""
    result_by_claim_id = {}
    for claim_id in all_claim_ids(driver):
        result_by_claim_id[claim_id] = score_claim(driver, claim_id, as_of_date)
    return result_by_claim_id
