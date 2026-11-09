"""What each layer adds (PLAN-v2.md A10, V15). Plain code only: no LLM, nothing is saved.

For every claim of the TEST split, the claim is scored three times:
  (a) tables and notes rules only: the 6 NL rules count as not evaluated (no network layer),
  (b) plus the network rules: all 32 rules, the normal score (score-claim),
  (c) plus the Challenger: the fixed adjustments of the Challenger (the same plain code the
      Challenger agent runs; its LLM only writes words, so it cannot change this score).
The answer key (ground_truth.json) is read only here, to measure. The scoring never reads it.
"""

import json

from src import config
from src.scoring.as_of import facts_as_of
from src.scoring.challenge_checks import run_challenge_checks
from src.scoring.engine import run_rules, score_rule_results
from src.scoring.facts import read_raw_facts
from src.scoring.rules_catalog import RULES

LAYERS = ["a_tables_and_notes", "b_plus_network", "c_plus_challenger"]
LAYER_NAMES = {"a_tables_and_notes": "(a) tables + notes rules",
               "b_plus_network": "(b) + network rules",
               "c_plus_challenger": "(c) + Challenger"}
NETWORK_RULE_IDS = [rule.rule_id for rule in RULES if rule.category == "NL"]


def load_truth():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


def claims_of_split(truth, split):
    return sorted(claim_id for claim_id, claim in truth["claims"].items() if claim["split"] == split)


def without_network(rule_results):
    """Layer (a): the NL rules become "not evaluated", as if the network layer did not exist."""
    results = dict(rule_results)
    for rule_id in NETWORK_RULE_IDS:
        results[rule_id] = {"status": "not_evaluated", "proof": {"missing": "layer (a) has no network rules"}}
    return results


def score_row(claim_id, claim_truth, result):
    return {"claim_id": claim_id, "is_fraud": claim_truth["is_fraud"], "fraud_type": claim_truth["fraud_type"],
            "lookalike_group": claim_truth["lookalike_group"], "total_score": result["total_score"],
            "band": result["band"], "fired_rules": [rule["rule_id"] for rule in result["fired_rules"]]}


def score_layers(driver, truth, claim_ids):
    """{layer: [row per claim]} for the three layers."""
    rows = {layer: [] for layer in LAYERS}
    for claim_id in claim_ids:
        raw = read_raw_facts(driver, claim_id)
        rule_results = run_rules(facts_as_of(raw))
        claim_truth = truth["claims"][claim_id]
        rows["a_tables_and_notes"].append(score_row(claim_id, claim_truth,
                                                    score_rule_results(without_network(rule_results))))
        rows["b_plus_network"].append(score_row(claim_id, claim_truth, score_rule_results(rule_results)))
        final, _ = run_challenge_checks(driver, raw)
        rows["c_plus_challenger"].append(score_row(claim_id, claim_truth, final))
    return rows
