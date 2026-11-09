"""How well did Intake read the findings? Compare with the ground truth (PLAN-v2.md V6, A10).

For each feature: the claims where the PDFs carry a planted value, and how often the merged
finding (one value per claim, A6 merge rule) equals it. Also the share of LLM findings that
passed the checks (verified quote), and every dropped finding with its reason.
"""

import json

from src import config
from src.documents.feature_catalog import FEATURES
from src.documents.feature_extraction import merge_findings


def load_planted_features():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        truth = json.load(file)
    return {claim_id: claim["planted_features"] for claim_id, claim in truth["claims"].items()}


def feature_scores(result_by_claim_id, planted_by_claim):
    """{feature: {"planted", "found_same", "found_other", "not_found", "examples"}}."""
    scores = {feature.code: {"planted": 0, "found_same": 0, "found_other": 0, "not_found": 0, "examples": []}
              for feature in FEATURES}
    for claim_id, result in sorted(result_by_claim_id.items()):
        merged = merge_findings(result["findings"])
        for code, planted_value in planted_by_claim[claim_id].items():
            score = scores[code]
            score["planted"] += 1
            if code not in merged:
                score["not_found"] += 1
            elif merged[code]["value"] == planted_value:
                score["found_same"] += 1
            else:
                score["found_other"] += 1
                if len(score["examples"]) < 3:
                    score["examples"].append(f"{claim_id}: planted {planted_value}, read {merged[code]['value']}")
    return scores


def print_findings_summary(result_by_claim_id):
    planted_by_claim = load_planted_features()
    kept = sum(len(result["findings"]) for result in result_by_claim_id.values())
    dropped = [item for result in result_by_claim_id.values() for item in result["dropped_findings"]]
    weak = sum(1 for result in result_by_claim_id.values() for item in result["findings"] if item["confidence"] == "Low")
    print(f"\nFindings: {kept} kept ({weak} weak, Low confidence), {len(dropped)} dropped. "
          f"Verified quote: {100 * kept / max(kept + len(dropped), 1):.1f}% of all LLM findings.")
    print(f"\n{'Feature':<26} {'planted':>7} {'same':>6} {'other':>6} {'missing':>8}  same %")
    for code, score in feature_scores(result_by_claim_id, planted_by_claim).items():
        share = 100 * score["found_same"] / max(score["planted"], 1)
        print(f"{code:<26} {score['planted']:>7} {score['found_same']:>6} {score['found_other']:>6} "
              f"{score['not_found']:>8}  {share:5.1f}%")
        for example in score["examples"]:
            print(f"    {example}")
    print(f"\nDropped findings ({len(dropped)}):")
    for item in dropped:
        print(f"  {item.get('document_id', '?')} p{item.get('page_number', '?')} {item['feature']} "
              f"'{item.get('rating')}': {item['reason']}")
